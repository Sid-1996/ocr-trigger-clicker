"""Background input module — supports multiple interaction methods.

Methods:
- pynput: Physical input via pynput (requires foreground, works for all apps)
- frida: Frida 行程注入（零閃爍後台操控，可嘗試解決部分遊戲無法後台點擊；多數 Unity 遊戲因底層限制不支援，以遊戲視窗自行測試為準，見 18_frida_bg.py）
  click/key 委派給 frida 模組（hook 假造游標/鍵盤狀態 + PostMessage）；scroll/drag
  仍回退 PostMessage primitive（v1 限制，Unity 下可能無效）

後台 PostMessage 模式已移除（Unity 讀取 OS 游標位置而非 lParam，無注入下無法精準點擊）。
底層 `_*_postmessage` 函式保留，作為 frida 的傳送層。

Usage:
    from core.bg_input import click, send_key, set_method
    set_method("frida")
    click(hwnd, x, y)
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import threading
import time

_log = logging.getLogger(__name__)
_lock = threading.Lock()

user32 = ctypes.windll.user32


class _PressLedger:
    """記錄「已確認 press 成功」的輸入，離開時依 LIFO 逐項嘗試釋放。

    與 core/03_pynput_input.py 的同名 helper 各持一份（不抽共用模組）：
    兩個輸入後端分屬不同路徑，後端之間不應互相依賴。

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


# ── Win32 constants ──
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
WM_MOUSEMOVE = 0x0200
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_ACTIVATE = 0x0006
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010
WA_ACTIVE = 0x01
WHEEL_DELTA = 120
VK_MENU = 0x12

# ── VK codes（與前景 03_pynput_input._parse_key 的按鍵名一致）──
_VK_MAP: dict[str, int] = {
    "enter": 0x0D,
    "escape": 0x1B,
    "space": 0x20,
    "tab": 0x09,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pgup": 0x21,
    "pgdn": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
    "capslock": 0x14,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "printscreen": 0x2C,
    "pause": 0x13,
    "menu": 0x5D,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
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

# 需要 extended-key 標記（lParam bit 24）的按鍵：方向鍵/Home/End/PgUp/PgDn/Ins/Del/
# NumpadDiv/NumLock。MapVirtualKeyW 不會回填此位元，漏設會讓部分遊戲誤判。
_EXTENDED_VK = frozenset(
    {
        0x21,  # PgUp
        0x22,  # PgDn
        0x23,  # End
        0x24,  # Home
        0x25,  # Left
        0x26,  # Up
        0x27,  # Right
        0x28,  # Down
        0x2C,  # PrintScreen
        0x2D,  # Insert
        0x2E,  # Delete
        0x6F,  # NumpadDiv
        0x90,  # NumLock
    }
)


def _resolve_vk(key: str) -> int | None:
    """Map a key name / single char to a Windows virtual-key code."""
    stripped = key.strip()
    key_lower = stripped.lower()
    vk = _VK_MAP.get(key_lower)
    if vk is not None:
        return vk
    if len(stripped) == 1:
        return ord(stripped.upper())
    return None


def _is_alt_down() -> bool:
    """True if the physical Alt key is currently held (for WM_SYSKEY selection)."""
    try:
        return bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
    except Exception:
        return False


def _vk_to_char(vk_code: int) -> int | None:
    """Map a VK code to a WM_CHAR character code.

    只涵蓋無歧義的文字鍵：A-Z、0-9、空白。導航/功能鍵（0x21-0x28 等）的 VK 碼值
    與可列印 ASCII 重疊，若含入會誤送 WM_CHAR（例如 VK_LEFT 0x25 與 '%' 衝突）。
    """
    if 0x30 <= vk_code <= 0x39 or 0x41 <= vk_code <= 0x5A or vk_code == 0x20:
        return vk_code
    return None


# ── Current method ──
_method = "pynput"  # default: foreground mode (safe)


def set_method(method: str) -> None:
    """Set the interaction method: 'pynput' or 'frida'.

    舊 config 的 'postmessage' 已淘汰，收到時警告並視為 'pynput'，避免主循環崩潰。
    """
    global _method
    if method == "postmessage":
        _log.warning("interaction_mode 'postmessage' 已移除，改用 'pynput'")
        method = "pynput"
    if method not in ("pynput", "frida"):
        raise ValueError(f"Unknown method: {method}")
    _method = method


def get_method() -> str:
    """Get the current interaction method."""
    return _method


def _frida():
    from _loader import load_sibling

    return load_sibling("frida_bg", "core/18_frida_bg.py")


# ── Coordinate helpers ──
def _client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    """Convert client coordinates to screen coordinates."""
    point = wintypes.POINT(x, y)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y


def _make_lparam(x: int, y: int) -> int:
    """Make lParam for mouse messages."""
    return (y << 16) | (x & 0xFFFF)


# ── PostMessage method ──
def _post_message_ok(hwnd: int, msg: int, wparam: int, lparam: int, label: str) -> bool:
    """送出訊息並檢查 Win32 BOOL 回傳值。

    PostMessageW 失敗時**回傳 0 而不拋例外**（ctypes windll 未設 errcheck），
    只靠 Python exception 判斷失敗會完全漏掉真實的 Win32 失敗路徑。
    回傳 True 只代表 PostMessageW 成功**提交**訊息，不代表遊戲已處理該訊息。
    例外會往外拋，由呼叫端處理。
    """
    if user32.PostMessageW(hwnd, msg, wparam, lparam):
        return True
    _log.warning("%s：PostMessageW 回傳 0（msg=0x%04X, hwnd=%s）", label, msg, hwnd)
    return False


def _post_up_with_retry(hwnd: int, up_msg: int, lparam: int) -> bool:
    """送出放開訊息；失敗時再試一次（最多兩次嘗試）。

    回傳 True 只代表 PostMessageW 成功提交放開訊息，不代表遊戲已放開按鈕。
    frida 滑鼠按鈕在遊戲端由 PostMessage 自行追蹤，沒有像鍵盤那樣的 TTL 自動清除，
    因此放開訊息送不出去就會讓按鈕卡住——失敗必須重試並留下 warning。
    """
    for attempt in (1, 2):
        label = f"放開訊息失敗（第 {attempt} 次嘗試）"
        try:
            if _post_message_ok(hwnd, up_msg, 0, lparam, label):
                return True
        except Exception as e:
            _log.warning("%s：送出時發生例外 %s", label, e)
    return False


def _mouse_messages(button: str) -> tuple[int, int, int] | None:
    """回傳 (down_msg, mk, up_msg)；不支援的按鍵回傳 None。

    抽成共用 helper，讓 click 與 drag 的按鍵語意只此一份。
    """
    if button == "left":
        return WM_LBUTTONDOWN, MK_LBUTTON, WM_LBUTTONUP
    if button == "right":
        return WM_RBUTTONDOWN, MK_RBUTTON, WM_RBUTTONUP
    if button == "middle":
        return WM_MBUTTONDOWN, MK_MBUTTON, WM_MBUTTONUP
    return None


def _post_mouse_down(hwnd: int, button: str, x: int, y: int) -> bool:
    """送出滑鼠按下訊息（不取得 _lock，呼叫端負責鎖定）。

    回傳 True 只代表 PostMessageW 成功「提交」訊息，不代表遊戲已處理。
    """
    msgs = _mouse_messages(button)
    if msgs is None:
        return False
    down_msg, mk, _up_msg = msgs
    return _post_message_ok(hwnd, down_msg, mk, _make_lparam(x, y), "按下滑鼠訊息失敗")


def _post_mouse_up(hwnd: int, button: str, x: int, y: int) -> bool:
    """送出滑鼠放開訊息（不取得 _lock，呼叫端負責鎖定）。

    失敗會依 _post_up_with_retry 再試一次並留下 warning。
    """
    msgs = _mouse_messages(button)
    if msgs is None:
        return False
    _down_msg, _mk, up_msg = msgs
    return _post_up_with_retry(hwnd, up_msg, _make_lparam(x, y))


def _click_postmessage(
    hwnd: int, x: int, y: int, button: str = "left", hold_ms: int = 0, cancel=None
) -> bool:
    """Click using PostMessage (pure message, no cursor movement).

    down 送出後一定會嘗試送出 up；up 失敗會再試一次並留下 warning。
    回傳值反映 down/up 是否成功「提交」給目標視窗，不會假裝成功。
    """
    down_sent = False
    released = True
    ok = True
    try:
        lparam = _make_lparam(x, y)
        if button == "left":
            down_msg, mk = WM_LBUTTONDOWN, MK_LBUTTON
            up_msg = WM_LBUTTONUP
        elif button == "right":
            down_msg, mk = WM_RBUTTONDOWN, MK_RBUTTON
            up_msg = WM_RBUTTONUP
        elif button == "middle":
            down_msg, mk = WM_MBUTTONDOWN, MK_MBUTTON
            up_msg = WM_MBUTTONUP
        else:
            return False

        # 激活訊息失敗不中斷點擊（維持原行為），但留下紀錄
        _post_message_ok(hwnd, WM_ACTIVATE, WA_ACTIVE, 0, "視窗激活訊息失敗")
        time.sleep(0.02)
        if not _post_message_ok(hwnd, down_msg, mk, lparam, "按下滑鼠訊息失敗"):
            # down 沒提交成功 → 不得標記 down_sent（否則會送出無意義的 up）
            ok = False
        else:
            down_sent = True
            if hold_ms > 0:
                _interruptible_wait(hold_ms, cancel)
    except Exception as e:
        _log.error("PostMessage click failed: %s", e)
        ok = False
    finally:
        if down_sent:
            # 無論正常、取消或例外，都必須嘗試送出 up
            released = _post_up_with_retry(hwnd, up_msg, lparam)
    return ok and released


def _key_postmessage(hwnd: int, vk_code: int, down: bool = True) -> bool:
    """Send key using PostMessage."""
    try:
        scan_code = user32.MapVirtualKeyW(vk_code, 0)
        lparam = (scan_code << 16) | 1
        if vk_code in _EXTENDED_VK:
            lparam |= 1 << 24  # extended-key（方向鍵/Home/End/... 需此位元）
        if not down:
            lparam |= (1 << 30) | (1 << 31)
        # Alt 按下時用 WM_SYSKEYDOWN/UP（某些遊戲只處理系統鍵）；其餘用 WM_KEYDOWN/UP
        alt_down = _is_alt_down()
        msg = (
            (WM_SYSKEYDOWN if down else WM_SYSKEYUP)
            if alt_down
            else (WM_KEYDOWN if down else WM_KEYUP)
        )
        user32.PostMessageW(hwnd, msg, vk_code, lparam)
        # 可列印字元在按下時補送 WM_CHAR，cover 走 TranslateMessage/字元輸入的遊戲
        if down and not alt_down:
            char = _vk_to_char(vk_code)
            if char is not None:
                user32.PostMessageW(hwnd, WM_CHAR, char, lparam)
        return True
    except Exception as e:
        _log.error("PostMessage key failed: %s", e)
        return False


def _scroll_postmessage(hwnd: int, x: int, y: int, amount: int, horizontal: bool = False) -> bool:
    """Scroll using PostMessage."""
    try:
        lparam = _make_lparam(x, y)
        wParam = (WHEEL_DELTA * amount) << 16
        msg = WM_MOUSEHWHEEL if horizontal else WM_MOUSEWHEEL
        user32.PostMessageW(hwnd, msg, wParam, lparam)
        return True
    except Exception as e:
        _log.error("PostMessage scroll failed: %s", e)
        return False


# ── Pynput method (physical input, requires foreground) ──
def _click_pynput(
    hwnd: int, x: int, y: int, button: str = "left", hold_ms: int = 0, cancel=None
) -> bool:
    """Click using pynput (physical input, requires foreground)."""
    try:
        import pynput.mouse

        btn_map = {
            "left": pynput.mouse.Button.left,
            "right": pynput.mouse.Button.right,
            "middle": pynput.mouse.Button.middle,
        }
        btn = btn_map.get(button)
        if btn is None:
            return False
        if cancel is not None and cancel.is_set():
            _log.info("已取消，略過背景點擊")
            return False

        abs_x, abs_y = _client_to_screen(hwnd, x, y)
        mouse = pynput.mouse.Controller()
        with _PressLedger() as ledger:
            mouse.position = (abs_x, abs_y)
            time.sleep(0.02)
            mouse.press(btn)
            ledger.record(f"滑鼠按鈕 {btn}", lambda: mouse.release(btn))
            if hold_ms > 0:
                _interruptible_wait(hold_ms, cancel)
        return True
    except Exception as e:
        _log.error("pynput click failed: %s", e)
        return False


def _key_pynput(hwnd: int, vk_code: int, down: bool = True) -> bool:
    """Send key using pynput."""
    try:
        import pynput.keyboard

        kb = pynput.keyboard.Controller()
        key = pynput.keyboard.KeyCode.from_vk(vk_code)
        if down:
            kb.press(key)
        else:
            kb.release(key)
        return True
    except Exception as e:
        _log.error("pynput key failed: %s", e)
        return False


def _scroll_pynput(hwnd: int, x: int, y: int, amount: int, horizontal: bool = False) -> bool:
    """Scroll using pynput."""
    try:
        import pynput.mouse

        mouse = pynput.mouse.Controller()
        abs_x, abs_y = _client_to_screen(hwnd, x, y)
        mouse.position = (abs_x, abs_y)
        time.sleep(0.02)
        dx, dy = (amount, 0) if horizontal else (0, amount)
        mouse.scroll(dx, dy)
        return True
    except Exception as e:
        _log.error("pynput scroll failed: %s", e)
        return False


# ── Public API ──
def click(hwnd: int, x: int, y: int, button: str = "left", hold_ms: int = 0, cancel=None) -> bool:
    """Click at (x, y) in client coordinates using the current method."""
    with _lock:
        if _method == "frida":
            return _frida().click(hwnd, x, y, button, hold_ms, cancel)
        elif _method == "pynput":
            return _click_pynput(hwnd, x, y, button, hold_ms, cancel)
        return False


def detach() -> None:
    """Detach any active Frida injection (safe to call in all modes)."""
    try:
        _frida().detach()
    except Exception:
        pass


def last_error() -> str:
    """Last Frida error message (empty if none)."""
    try:
        return _frida().last_error()
    except Exception:
        return ""


def send_key(hwnd: int, key: str, cancel=None) -> bool:
    """Send a key press and release."""
    vk = _resolve_vk(key)
    if vk is None:
        _log.warning("Cannot parse key: %s", key)
        return False

    with _lock:
        if _method == "frida":
            f = _frida()
            if not f.key(hwnd, vk, True):
                return False
            try:
                # 持窗 120ms：確保遊戲以 60Hz（16.7ms/tick）輪詢鍵盤狀態時至少
                # 涵蓋多個 tick，避免 down/up 落在同一個 tick 內被當成沒按下
                time.sleep(0.12)
                return True
            finally:
                f.key(hwnd, vk, False)
        elif _method == "pynput":
            # 只有按下確認成功才登記釋放；未登記者不送出 release（不誤放）。
            with _PressLedger() as ledger:
                ok = _key_pynput(hwnd, vk, True)
                if ok:
                    ledger.record(f"按鍵 vk={vk}", lambda: _key_pynput(hwnd, vk, False))
                time.sleep(0.02)
            return ok
        return False


def scroll(hwnd: int, x: int, y: int, amount: int = 1, horizontal: bool = False) -> bool:
    """Scroll at (x, y). Positive = up/right, negative = down/left."""
    with _lock:
        if _method == "frida":
            return _scroll_postmessage(hwnd, x, y, amount, horizontal)
        elif _method == "pynput":
            return _scroll_pynput(hwnd, x, y, amount, horizontal)
        return False


def activate_window_bg(hwnd: int) -> bool:
    """Activate window using WM_ACTIVATE (does not steal focus)."""
    try:
        user32.PostMessageW(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
        return True
    except Exception as e:
        _log.error("activate_window_bg failed: %s", e)
        return False


def send_hold_key(hwnd: int, key: str, hold_ms: float, cancel=None) -> bool:
    """Hold a key for hold_ms milliseconds in background mode."""
    vk = _resolve_vk(key)
    if vk is None:
        _log.warning("Cannot parse key for hold: %s", key)
        return False
    if cancel is not None and cancel.is_set():
        _log.info("已取消，略過背景按住")
        return False

    with _lock:
        if _method == "frida":
            f = _frida()
            if not f.key(hwnd, vk, True):
                return False
            try:
                # 週期 re-arm spoof 寬限期，支援任意長度的按住；500ms 重送確保
                # 遊戲輪詢永遠能看到 down 狀態（1s 間隔在低頻輪詢下可能跳過）
                deadline = time.monotonic() + hold_ms / 1000.0
                while True:
                    if cancel is not None and cancel.is_set():
                        _log.info("按住已取消，提前放開按鍵")
                        return True
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    if cancel is None:
                        time.sleep(min(remaining, 0.5))
                    elif cancel.wait(min(remaining, 0.5)):
                        _log.info("按住已取消，提前放開按鍵")
                        return True
                    f.key(hwnd, vk, True)
                return True
            finally:
                # 取消或例外都會走到這裡：key(up) 一定被嘗試送出。
                f.key(hwnd, vk, False)
        elif _method == "pynput":
            return False
    return False


def drag(
    hwnd: int, start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left"
) -> bool:
    """Perform a drag operation in background mode.

    訊息順序：WM_ACTIVATE → DOWN(起點) → MOVE(終點) → UP(終點)。

    - 全程只取得一次 _lock：不得呼叫會自行取同一把鎖的 click()，否則同執行緒
      重入非重入 Lock 會永久死鎖。
    - DOWN 成功後，無論 MOVE 成功與否都一定會嘗試 UP（避免遊戲內卡住按鈕）。
    - 回傳值反映 DOWN／MOVE／UP 是否成功「提交」訊息，不代表遊戲已處理。
    """
    with _lock:
        if _method != "frida":
            return False
        if _mouse_messages(button) is None:
            return False
        f = _frida()
        # frida 必須先把注入腳本裡的假造游標移到起點，遊戲才會認為按在該處；
        # sync_cursor 內含 ensure_attached，失敗即中止（尚未按下，不需釋放）。
        if not f.sync_cursor(hwnd, start_x, start_y):
            return False
        # 激活訊息失敗不中斷拖曳（維持 click 的既有行為），但留下紀錄
        _post_message_ok(hwnd, WM_ACTIVATE, WA_ACTIVE, 0, "視窗激活訊息失敗")
        if not _post_mouse_down(hwnd, button, start_x, start_y):
            # DOWN 沒提交成功 → 不得送出 MOVE 或 UP
            return False
        moved = False
        released = False
        try:
            time.sleep(0.05)
            # 拖曳過程遊戲讀的是假造游標 → MOVE 前必須先同步到終點
            if not f.sync_cursor(hwnd, end_x, end_y):
                _log.warning("拖曳終點游標同步失敗，跳過移動訊息")
            else:
                moved = _post_message_ok(
                    hwnd, WM_MOUSEMOVE, 0, _make_lparam(end_x, end_y), "滑鼠移動訊息失敗"
                )
            time.sleep(0.05)
        finally:
            # 無論正常、取消或例外，都必須嘗試送出 UP（DOWN 已成功）
            released = _post_mouse_up(hwnd, button, end_x, end_y)
        return moved and released


if __name__ == "__main__":
    print("=== BG Input Self-Check ===\n")

    assert get_method() == "pynput"
    print("  [OK] Default method is pynput")

    set_method("postmessage")  # 舊 config 值 → 警告並視為 pynput
    assert get_method() == "pynput"
    print("  [OK] 舊 set_method('postmessage') 遷移為 pynput")

    set_method("pynput")
    assert get_method() == "pynput"
    print("  [OK] set_method('pynput')")

    set_method("frida")
    assert get_method() == "frida"
    print("  [OK] set_method('frida')")

    try:
        set_method("sendinput")
        assert False, "Should have raised ValueError"
    except ValueError:
        print("  [OK] set_method('sendinput') raises ValueError")

    try:
        set_method("invalid")
        assert False, "Should have raised ValueError"
    except ValueError:
        print("  [OK] set_method('invalid') raises ValueError")

    # 滾輪語意：正值 = 上/右、負值 = 下/左；水平方向送 WM_MOUSEHWHEEL
    captured = {}
    _orig_pm = user32.PostMessageW
    user32.PostMessageW = lambda hwnd, msg, wparam, lparam: (
        captured.update(msg=msg, wparam=wparam) or True
    )
    try:
        _scroll_postmessage(1, 0, 0, -1)
        assert captured["msg"] == WM_MOUSEWHEEL and captured["wparam"] < 0
        _scroll_postmessage(1, 0, 0, 1)
        assert captured["msg"] == WM_MOUSEWHEEL and captured["wparam"] > 0
        _scroll_postmessage(1, 0, 0, 1, True)
        assert captured["msg"] == WM_MOUSEHWHEEL and captured["wparam"] > 0
        _scroll_postmessage(1, 0, 0, -1, True)
        assert captured["msg"] == WM_MOUSEHWHEEL and captured["wparam"] < 0
    finally:
        user32.PostMessageW = _orig_pm
    print("  [OK] scroll sign/axis: 下左負值、上右正值、水平送 WM_MOUSEHWHEEL")

    # 按鍵 vk 解析：與前景按鍵名一致（f1-f12 / numpad / pgup 等）
    assert _resolve_vk("F5") == 0x74
    assert _resolve_vk("f12") == 0x7B
    assert _resolve_vk("pgdn") == 0x22
    assert _resolve_vk("numpad3") == 0x63
    assert _resolve_vk("a") == 0x41
    assert _resolve_vk("Z") == 0x5A
    assert _resolve_vk("") is None
    assert _resolve_vk("foobar") is None
    print("  [OK] _resolve_vk 按鍵名/單字元解析")

    # extended-key lParam bit 24：方向鍵等需設，普通鍵不需
    captured = []
    _orig_pm = user32.PostMessageW
    user32.PostMessageW = lambda hwnd, msg, wparam, lparam: (
        captured.append((msg, wparam, lparam)) or True
    )
    try:
        _key_postmessage(1, 0x25, True)  # VK_LEFT
        assert captured[-1][2] & (1 << 24), "方向鍵應設 extended-key 位元"
        _key_postmessage(1, 0x41, True)  # 'A'
        assert not (captured[-1][2] & (1 << 24)), "普通鍵不應設 extended-key 位元"
        _key_postmessage(1, 0x25, False)  # VK_LEFT up
        assert captured[-1][2] & (1 << 30), "keyup 應設 transition 位元"
    finally:
        user32.PostMessageW = _orig_pm
    print("  [OK] _key_postmessage extended-key lParam")

    # WM_CHAR：可列印字元按下時補送；導航鍵不送（VK 碼值與 ASCII 重疊）
    captured = []
    _orig_pm = user32.PostMessageW
    user32.PostMessageW = lambda hwnd, msg, wparam, lparam: (
        captured.append((msg, wparam, lparam)) or True
    )
    try:
        _key_postmessage(1, 0x41, True)  # 'A'
        assert (WM_KEYDOWN, 0x41) in [(m, w) for m, w, _ in captured], captured
        assert (WM_CHAR, 0x41) in [(m, w) for m, w, _ in captured], "字母按下應補送 WM_CHAR"
        _key_postmessage(1, 0x41, False)  # 'A' up
        assert (WM_CHAR, 0x41) not in [(m, w) for m, w, _ in captured[-1:]], "keyup 不應送 WM_CHAR"
        captured.clear()
        _key_postmessage(1, 0x25, True)  # VK_LEFT（0x25 與 '%' 衝突）
        assert (WM_CHAR, 0x25) not in [(m, w) for m, w, _ in captured], "導航鍵不應送 WM_CHAR"
    finally:
        user32.PostMessageW = _orig_pm
    print("  [OK] _key_postmessage WM_CHAR（字母送、keyup 不送、導航鍵不送）")

    # frida 拖曳訊息順序：ACTIVATE → DOWN → MOVE → UP（不得提前放開按鈕）
    captured = []
    _orig_pm = user32.PostMessageW
    _orig_frida = _frida
    _orig_method = _method

    class _SelfCheckFrida:
        @staticmethod
        def sync_cursor(hwnd, x, y):
            return True

    def _selfcheck_frida():
        return _SelfCheckFrida()

    user32.PostMessageW = lambda hwnd, msg, wparam, lparam: captured.append((msg, wparam)) or True
    try:
        _frida = _selfcheck_frida
        _method = "frida"
        assert drag(1, 10, 20, 30, 40, "left") is True
        assert [m for m, _w in captured] == [
            WM_ACTIVATE,
            WM_LBUTTONDOWN,
            WM_MOUSEMOVE,
            WM_LBUTTONUP,
        ], captured
    finally:
        _method = _orig_method
        _frida = _orig_frida
        user32.PostMessageW = _orig_pm
    print("  [OK] frida drag 訊息順序：ACTIVATE → DOWN → MOVE → UP")

    print("\n=== All checks passed ===")
