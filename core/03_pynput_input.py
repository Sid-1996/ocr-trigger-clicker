import logging
import threading
import time

import pynput.keyboard
import pynput.mouse

_log = logging.getLogger(__name__)
_lock = threading.Lock()

_Key = pynput.keyboard.Key
_Button = pynput.mouse.Button

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


def _send_simple_key(key: str) -> bool:
    parsed = _parse_key(key)
    if parsed is None:
        _log.warning("無法解析按鍵: %s", key)
        return False
    kb = pynput.keyboard.Controller()
    kb.press(parsed)
    time.sleep(0.02)
    kb.release(parsed)
    return True


def _send_ctrl_combo(combo: str) -> bool:
    if len(combo) < 2 or combo[0] != "^":
        return False
    rest = combo[1:]
    if not rest:
        return False
    char_key = _parse_key(rest)
    if char_key is None:
        return False
    kb = pynput.keyboard.Controller()
    kb.press(_Key.ctrl)
    kb.press(char_key)
    time.sleep(0.02)
    kb.release(char_key)
    kb.release(_Key.ctrl)
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


def _should_restore(current: tuple, target: tuple, tol: int = 2) -> bool:
    return abs(current[0] - target[0]) <= tol and abs(current[1] - target[1]) <= tol


def _inside_rect(pos: tuple, rect: dict | None) -> bool:
    if rect is None:
        return False
    x, y = pos
    return rect["x"] <= x < rect["x"] + rect["w"] and rect["y"] <= y < rect["y"] + rect["h"]


def _try_restore(mouse, orig, target, restore_rect=None) -> None:
    """動作完成後把游標移回原本位置。讀寫失敗、使用者已移開、
    或復原位置落在 restore_rect（目標視窗）內時忽略。"""
    if orig is None:
        return
    try:
        if _inside_rect(orig, restore_rect):
            return
        if _should_restore(mouse.position, target):
            mouse.position = orig
    except Exception:
        pass


def send_click(
    x: int,
    y: int,
    button: str = "left",
    hold_ms: int = 0,
    restore_cursor: bool = True,
    restore_rect: dict | None = None,
    restore_grace_ms: int = 0,
) -> bool:
    if not _validate_coords(x, y):
        return False
    btn = {"left": _Button.left, "right": _Button.right, "middle": _Button.middle}.get(
        button, _Button.left
    )
    mouse = pynput.mouse.Controller()
    with _lock:
        orig = None
        if restore_cursor:
            try:
                orig = mouse.position
            except Exception:
                orig = None
        mouse.position = (x, y)
        time.sleep(0.01)
        mouse.press(btn)
        if hold_ms > 0:
            time.sleep(hold_ms / 1000.0)
        mouse.release(btn)
        if restore_cursor:
            # ponytail: grace 延遲讓目標視窗多個 tick 先處理點擊，再移回游標
            if restore_grace_ms > 0:
                time.sleep(restore_grace_ms / 1000.0)
            _try_restore(mouse, orig, (x, y), restore_rect)
    return True


def send_key(key: str) -> bool:
    key = key.strip().replace("\n", "").replace("\r", "")
    if not key:
        return False
    with _lock:
        if key.startswith("^") and len(key) == 2:
            return _send_ctrl_combo(key)
        return _send_simple_key(key)


def send_drag(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    button: str = "left",
    restore_cursor: bool = True,
    restore_rect: dict | None = None,
    restore_grace_ms: int = 0,
) -> bool:
    if not _validate_coords(x1, y1) or not _validate_coords(x2, y2):
        return False
    btn = {"left": _Button.left, "right": _Button.right, "middle": _Button.middle}.get(
        button, _Button.left
    )
    mouse = pynput.mouse.Controller()
    with _lock:
        orig = None
        if restore_cursor:
            try:
                orig = mouse.position
            except Exception:
                orig = None
        mouse.position = (x1, y1)
        time.sleep(0.02)
        mouse.press(btn)
        time.sleep(0.02)
        mouse.position = (x2, y2)
        time.sleep(0.02)
        mouse.release(btn)
        if restore_cursor:
            if restore_grace_ms > 0:
                time.sleep(restore_grace_ms / 1000.0)
            _try_restore(mouse, orig, (x2, y2), restore_rect)
    return True


def send_scroll(amount: int = 1, direction: str = "WheelDown") -> bool:
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
        mouse.scroll(dx, dy)
    return True


def send_hold_key(key: str, duration_ms: int = 0) -> bool:
    key = key.strip().replace("\n", "").replace("\r", "")
    if not key:
        return False
    parsed = _parse_key(key)
    if parsed is None:
        _log.warning("無法解析按鍵: %s", key)
        return False
    kb = pynput.keyboard.Controller()
    with _lock:
        kb.press(parsed)
        if duration_ms > 0:
            time.sleep(duration_ms / 1000.0)
        kb.release(parsed)
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

    assert _should_restore((10, 10), (10, 10)) is True
    assert _should_restore((15, 10), (10, 10)) is False
    assert _should_restore((10, 13), (10, 10)) is False
    assert _should_restore((11, 9), (10, 10)) is True  # 容差 2px 內
    print("  [OK] _should_restore tolerance guard")

    rect = {"x": 100, "y": 100, "w": 200, "h": 150}
    assert _inside_rect((100, 100), rect) is True
    assert _inside_rect((299, 249), rect) is True
    assert _inside_rect((300, 249), rect) is False  # 右/下邊界互斥
    assert _inside_rect((150, 250), rect) is False
    assert _inside_rect((50, 50), None) is False
    print("  [OK] _inside_rect window bound check")

    assert send_emergency_stop() is True
    print("  [OK] send_emergency_stop noop")

    print("\n=== All 9 tests passed ===")
