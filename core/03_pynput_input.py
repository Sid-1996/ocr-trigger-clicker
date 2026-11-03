import logging
import threading
import time

import pynput.keyboard
import pynput.mouse

_log = logging.getLogger(__name__)
_lock = threading.Lock()

_Key = pynput.keyboard.Key
_Button = pynput.mouse.Button


class _PressLedger:
    """記錄「已確認 press 成功」的輸入，離開時依 LIFO 逐項嘗試釋放。

    語義：
    - 只有 press 呼叫成功回來才登記；未登記者一律不送出 release（不誤放）。
    - 釋放順序為 press 的相反順序（LIFO），多鍵組合才不會先放掉仍在使用的修飾鍵。
    - 每一項釋放各自 try/except：某一項失敗不得阻止其餘已登記項目的釋放。
    - 釋放失敗會記 warning，不得靜默。

    提供的是「盡可能嘗試釋放」，不是 OS 層的絕對成功保證——真實按鍵／按鈕是否
    真的放開取決於作業系統與目標視窗，程式端無法百分之百確認。
    """

    def __init__(self) -> None:
        self._held: list[tuple[str, object]] = []

    def record(self, label: str, release_fn) -> None:
        """登記一個已確認 press 成功的輸入及其釋放動作。"""
        self._held.append((label, release_fn))

    def release_all(self) -> int:
        """依相反順序逐項嘗試釋放；回傳失敗的項目數。一次操作只應呼叫一次。"""
        failures = 0
        for label, release_fn in reversed(self._held):
            try:
                release_fn()
            except Exception as e:
                failures += 1
                _log.warning("釋放 %s 失敗: %s", label, e)
        self._held.clear()
        return failures

    def __enter__(self) -> "_PressLedger":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release_all()
        return False  # 不吞掉原始例外


def _interruptible_wait(ms: int, cancel=None) -> bool:
    """等待 ms 毫秒；回傳 True 代表等待期間被取消。

    cancel is None 時保留舊有的 time.sleep 行為，既有呼叫者零影響。
    """
    if cancel is None:
        if ms > 0:
            time.sleep(ms / 1000.0)
        return False
    return cancel.wait(timeout=max(0.0, ms / 1000.0))


_KEY_MAP: dict[str, pynput.keyboard.Key] = {
    "enter": _Key.enter,
    "escape": _Key.esc,
    "space": _Key.space,
    "tab": _Key.tab,
    "backspace": _Key.backspace,
    "delete": _Key.delete,
    "insert": _Key.insert,
    "home": _Key.home,
    "end": _Key.end,
    "pgup": _Key.page_up,
    "pgdn": _Key.page_down,
    "up": _Key.up,
    "down": _Key.down,
    "left": _Key.left,
    "right": _Key.right,
    "f1": _Key.f1,
    "f2": _Key.f2,
    "f3": _Key.f3,
    "f4": _Key.f4,
    "f5": _Key.f5,
    "f6": _Key.f6,
    "f7": _Key.f7,
    "f8": _Key.f8,
    "f9": _Key.f9,
    "f10": _Key.f10,
    "f11": _Key.f11,
    "f12": _Key.f12,
    "capslock": _Key.caps_lock,
    "numlock": _Key.num_lock,
    "scrolllock": _Key.scroll_lock,
    "printscreen": _Key.print_screen,
    "pause": _Key.pause,
    "menu": _Key.menu,
    "shift": _Key.shift,
    "ctrl": _Key.ctrl,
    "alt": _Key.alt,
    "lshift": _Key.shift_l,
    "rshift": _Key.shift_r,
    "lctrl": _Key.ctrl_l,
    "rctrl": _Key.ctrl_r,
    "lalt": _Key.alt_l,
    "ralt": _Key.alt_r,
    "win": _Key.cmd,
    "windows": _Key.cmd,
}

_NUMPAD_VK: dict[str, int] = {
    "numpad0": 0x60,
    "numpad1": 0x61,
    "numpad2": 0x62,
    "numpad3": 0x63,
    "numpad4": 0x64,
    "numpad5": 0x65,
    "numpad6": 0x66,
    "numpad7": 0x67,
    "numpad8": 0x68,
    "numpad9": 0x69,
    "numpadadd": 0x6B,
    "numpadsub": 0x6D,
    "numpadmult": 0x6A,
    "numpaddiv": 0x6F,
    "numpadenter": 0x0D,
    "numpaddel": 0x2E,
}


def _parse_key(key: str):
    key_stripped = key.strip()
    if not key_stripped:
        return None
    key_lower = key_stripped.lower()
    mapped = _KEY_MAP.get(key_lower)
    if mapped is not None:
        return mapped
    vk = _NUMPAD_VK.get(key_lower)
    if vk is not None:
        return pynput.keyboard.KeyCode.from_vk(vk)
    if len(key_stripped) == 1:
        return pynput.keyboard.KeyCode.from_char(key_stripped)
    return None


def _send_simple_key(key: str, cancel=None) -> bool:
    parsed = _parse_key(key)
    if parsed is None:
        _log.warning("無法解析按鍵: %s", key)
        return False
    if cancel is not None and cancel.is_set():
        _log.info("已取消，略過按鍵 %s", key)
        return False
    kb = pynput.keyboard.Controller()
    with _PressLedger() as ledger:
        kb.press(parsed)
        ledger.record(f"按鍵 {parsed}", lambda: kb.release(parsed))
        _interruptible_wait(20, cancel)
    return True


def _send_ctrl_combo(combo: str, cancel=None) -> bool:
    if len(combo) < 2 or combo[0] != "^":
        return False
    rest = combo[1:]
    if not rest:
        return False
    char_key = _parse_key(rest)
    if char_key is None:
        return False
    if cancel is not None and cancel.is_set():
        _log.info("已取消，略過組合鍵 %s", combo)
        return False
    kb = pynput.keyboard.Controller()
    # 多鍵組合：Ctrl 與字元都要登記，釋放依 LIFO（先字元、後 Ctrl）。
    # 第二個 press 失敗時只會釋放已登記的 Ctrl，不會誤送字元 release。
    with _PressLedger() as ledger:
        kb.press(_Key.ctrl)
        ledger.record("Ctrl 鍵", lambda: kb.release(_Key.ctrl))
        kb.press(char_key)
        ledger.record(f"按鍵 {char_key}", lambda: kb.release(char_key))
        _interruptible_wait(20, cancel)
    return True


def _load_screen_bounds() -> dict:
    import ctypes

    user32 = ctypes.windll.user32
    return {
        "x": user32.GetSystemMetrics(76),
        "y": user32.GetSystemMetrics(77),
        "w": user32.GetSystemMetrics(78),
        "h": user32.GetSystemMetrics(79),
    }


def _validate_coords(x: int, y: int) -> bool:
    bounds = _load_screen_bounds()
    if (
        x < bounds["x"]
        or y < bounds["y"]
        or x >= bounds["x"] + bounds["w"]
        or y >= bounds["y"] + bounds["h"]
    ):
        _log.warning("拒絕超出螢幕的點擊: (%d, %d) 螢幕=%s", x, y, bounds)
        return False
    return True


def send_click(x: int, y: int, button: str = "left", hold_ms: int = 0, cancel=None) -> bool:
    if not _validate_coords(x, y):
        return False
    if cancel is not None and cancel.is_set():
        _log.info("已取消，略過點擊 (%d,%d)", x, y)
        return False
    btn = {"left": _Button.left, "right": _Button.right, "middle": _Button.middle}.get(
        button, _Button.left
    )
    mouse = pynput.mouse.Controller()
    with _lock:
        if cancel is not None and cancel.is_set():
            return False
        with _PressLedger() as ledger:
            mouse.position = (x, y)
            time.sleep(0.01)
            mouse.press(btn)
            ledger.record(f"滑鼠按鈕 {btn}", lambda: mouse.release(btn))
            if hold_ms > 0:
                _interruptible_wait(hold_ms, cancel)
    return True


def send_key(key: str, cancel=None) -> bool:
    key = key.strip().replace("\n", "").replace("\r", "")
    if not key:
        return False
    with _lock:
        if key.startswith("^") and len(key) == 2:
            return _send_ctrl_combo(key, cancel)
        return _send_simple_key(key, cancel)


def send_drag(x1: int, y1: int, x2: int, y2: int, button: str = "left", cancel=None) -> bool:
    if not _validate_coords(x1, y1) or not _validate_coords(x2, y2):
        return False
    if cancel is not None and cancel.is_set():
        _log.info("已取消，略過拖曳")
        return False
    btn = {"left": _Button.left, "right": _Button.right, "middle": _Button.middle}.get(
        button, _Button.left
    )
    mouse = pynput.mouse.Controller()
    with _lock:
        if cancel is not None and cancel.is_set():
            return False
        with _PressLedger() as ledger:
            mouse.position = (x1, y1)
            time.sleep(0.02)
            mouse.press(btn)
            ledger.record(f"滑鼠按鈕 {btn}", lambda: mouse.release(btn))
            # DOWN 已送出 → 之後只能停止 MOVE，不能跳過 Release（ledger 離開時釋放）。
            if cancel is not None and cancel.is_set():
                _log.info("拖曳已取消，提前放開滑鼠按鈕")
                return True
            if _interruptible_wait(20, cancel):
                _log.info("拖曳已取消，停止移動並提前放開滑鼠按鈕")
                return True
            mouse.position = (x2, y2)
            time.sleep(0.02)
    return True


def send_scroll(amount: int = 1, direction: str = "WheelDown", cancel=None) -> bool:
    if cancel is not None and cancel.is_set():
        _log.info("已取消，略過滾輪")
        return False
    dx = 0
    dy = 0
    if direction == "WheelDown":
        dy = -amount
    elif direction == "WheelUp":
        dy = amount
    elif direction == "WheelLeft":
        dx = -amount
    elif direction == "WheelRight":
        dx = amount
    mouse = pynput.mouse.Controller()
    with _lock:
        if cancel is not None and cancel.is_set():
            return False
        mouse.scroll(dx, dy)
    return True


def send_hold_key(key: str, duration_ms: int = 0, cancel=None) -> bool:
    key = key.strip().replace("\n", "").replace("\r", "")
    if not key:
        return False
    parsed = _parse_key(key)
    if parsed is None:
        _log.warning("無法解析按鍵: %s", key)
        return False
    if cancel is not None and cancel.is_set():
        _log.info("已取消，略過按住 %s", key)
        return False
    kb = pynput.keyboard.Controller()
    with _lock:
        if cancel is not None and cancel.is_set():
            return False
        with _PressLedger() as ledger:
            kb.press(parsed)
            ledger.record(f"按鍵 {parsed}", lambda: kb.release(parsed))
            if duration_ms > 0:
                _interruptible_wait(duration_ms, cancel)
    return True


def send_emergency_stop() -> bool:
    _log.warning("緊急停止請求 (pynput 無外部行程，僅記錄)")
    return True


def shutdown() -> None:
    pass


if __name__ == "__main__":
    print("=== Pynput Input Self-Check ===\n")

    assert _parse_key("Enter") == _Key.enter
    assert _parse_key("escape") == _Key.esc
    assert _parse_key("F5") == _Key.f5
    print("  [OK] _parse_key named keys")

    from pynput.keyboard import KeyCode

    kc = _parse_key("a")
    assert isinstance(kc, KeyCode) and kc.char == "a"
    kc2 = _parse_key("Z")
    assert isinstance(kc2, KeyCode) and kc2.char == "Z"
    print("  [OK] _parse_key letter keys")

    n0 = _parse_key("Numpad0")
    assert n0 is not None and getattr(n0, "vk", None) == 0x60
    ne = _parse_key("NumpadEnter")
    assert ne is not None
    print("  [OK] _parse_key numpad keys")

    assert _parse_key("") is None
    assert _parse_key("  ") is None
    print("  [OK] _parse_key empty/whitespace")

    assert _validate_coords(0, 0) is True
    bounds = _load_screen_bounds()
    assert _validate_coords(bounds["x"] + bounds["w"] + 1, 0) is False
    assert _validate_coords(0, bounds["y"] + bounds["h"] + 1) is False
    print("  [OK] _validate_coords boundary detection")

    assert send_key("") is False
    assert send_key("  ") is False
    print("  [OK] send_key rejects empty")

    assert send_click(0, -9999, "left") is False
    print("  [OK] send_click rejects out-of-bounds")

    assert send_emergency_stop() is True
    print("  [OK] send_emergency_stop noop")

    # Ledger 與可取消等待（不觸碰真實輸入設備）
    released = []
    led = _PressLedger()
    led.record("A", lambda: released.append("A"))
    led.record("B", lambda: released.append("B"))
    assert led.release_all() == 0
    assert released == ["B", "A"], "釋放必須依 press 的相反順序（LIFO）"
    assert led.release_all() == 0, "release_all 不得重複釋放"

    others = []
    led2 = _PressLedger()
    led2.record("X", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    led2.record("Y", lambda: others.append("Y"))
    assert led2.release_all() == 1, "釋放失敗必須被計數"
    assert others == ["Y"], "某一項釋放失敗不得阻止其他已登記項目"

    ev = threading.Event()
    assert _interruptible_wait(0, ev) is False
    ev.set()
    assert _interruptible_wait(0, ev) is True, "已取消時必須回報 True"
    assert _interruptible_wait(1, None) is False, "cancel=None 必須維持舊行為"
    print("  [OK] _PressLedger / _interruptible_wait")

    print("\n=== All 9 tests passed ===")
