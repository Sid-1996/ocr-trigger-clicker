"""Background input module — supports multiple interaction methods.

Methods:
- pynput: Physical input via pynput (requires foreground, works for all apps)
- frida: Frida 行程注入（零閃爍 Unity 後台操控，見 18_frida_bg.py）
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
WM_SETFOCUS = 0x0007
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


def _activate_focus(hwnd: int) -> None:
    """Tell the window it is active & focused without stealing real focus.

    背景輸入在每個動作前送 WM_ACTIVATE(WA_ACTIVE)+WM_SETFOCUS：遊戲只有在收到啟用
    訊息後才視為可接收輸入（鍵盤不需先點擊一次；搭配 frida keep-active 時更有意義）。
    """
    try:
        user32.PostMessageW(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
        user32.PostMessageW(hwnd, WM_SETFOCUS, 0, 0)
    except Exception as e:
        _log.error("activate_focus failed: %s", e)


# ── PostMessage method ──
def _click_postmessage(hwnd: int, x: int, y: int, button: str = "left", hold_ms: int = 0) -> bool:
    """Click using PostMessage (pure message, no cursor movement)."""
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

        _activate_focus(hwnd)
        time.sleep(0.02)
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)  # 先導：遊戲記錄 last-mouse-pos
        user32.PostMessageW(hwnd, down_msg, mk, lparam)
        if hold_ms > 0:
            time.sleep(hold_ms / 1000.0)
        user32.PostMessageW(hwnd, up_msg, 0, lparam)
        return True
    except Exception as e:
        _log.error("PostMessage click failed: %s", e)
        return False


def _key_postmessage(hwnd: int, vk_code: int, down: bool = True) -> bool:
    """Send key using PostMessage."""
    try:
        _activate_focus(hwnd)
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
        _activate_focus(hwnd)
        lparam = _make_lparam(x, y)
        wParam = (WHEEL_DELTA * amount) << 16
        msg = WM_MOUSEHWHEEL if horizontal else WM_MOUSEWHEEL
        user32.PostMessageW(hwnd, msg, wParam, lparam)
        return True
    except Exception as e:
        _log.error("PostMessage scroll failed: %s", e)
        return False


# ── Pynput method (physical input, requires foreground) ──
def _click_pynput(hwnd: int, x: int, y: int, button: str = "left", hold_ms: int = 0) -> bool:
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

        abs_x, abs_y = _client_to_screen(hwnd, x, y)
        mouse = pynput.mouse.Controller()
        mouse.position = (abs_x, abs_y)
        time.sleep(0.02)
        mouse.press(btn)
        if hold_ms > 0:
            time.sleep(hold_ms / 1000.0)
        mouse.release(btn)
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
def click(hwnd: int, x: int, y: int, button: str = "left", hold_ms: int = 0) -> bool:
    """Click at (x, y) in client coordinates using the current method."""
    with _lock:
        if _method == "frida":
            return _frida().click(hwnd, x, y, button, hold_ms)
        elif _method == "pynput":
            return _click_pynput(hwnd, x, y, button, hold_ms)
        return False


def detach() -> None:
    """Detach any active Frida injection (safe to call in all modes)."""
    try:
        _frida().detach()
    except Exception:
        pass


def keep_active(hwnd: int, on: bool) -> bool:
    """Enable/disable 後台 keep-active（僅 frida 模式有意義）。

    on=True：遊戲視窗持續假造為前景/啟用/焦點，並過濾失焦訊息 → 可被覆蓋、音樂不停。
    on=False：恢復「失焦即暫停」原行為。pynput（前景）模式永遠 no-op 回 True。
    """
    if _method != "frida":
        return True
    try:
        return bool(_frida().keep_active(hwnd, on))
    except Exception as e:
        _log.error("keep_active failed: %s", e)
        return False


def last_error() -> str:
    """Last Frida error message (empty if none)."""
    try:
        return _frida().last_error()
    except Exception:
        return ""


def send_key(hwnd: int, key: str) -> bool:
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
            ok = _key_pynput(hwnd, vk, True)
            time.sleep(0.02)
            ok = _key_pynput(hwnd, vk, False) and ok
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


def send_hold_key(hwnd: int, key: str, hold_ms: float) -> bool:
    """Hold a key for hold_ms milliseconds in background mode."""
    vk = _resolve_vk(key)
    if vk is None:
        _log.warning("Cannot parse key for hold: %s", key)
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
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(remaining, 0.5))
                    f.key(hwnd, vk, True)
                return True
            finally:
                f.key(hwnd, vk, False)
        elif _method == "pynput":
            return False
    return False


def drag(
    hwnd: int, start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left"
) -> bool:
    """Perform a drag operation in background mode."""
    with _lock:
        if _method == "frida":
            ok = click(hwnd, start_x, start_y, button)
            if not ok:
                return False
            time.sleep(0.05)
            lparam = _make_lparam(end_x, end_y)
            user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
            time.sleep(0.05)
            if button == "left":
                up_msg = WM_LBUTTONUP
            elif button == "right":
                up_msg = WM_RBUTTONUP
            elif button == "middle":
                up_msg = WM_MBUTTONUP
            else:
                return False
            user32.PostMessageW(hwnd, up_msg, 0, lparam)
            return True
        elif _method == "pynput":
            return False
    return False


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

    # 動作前啟用：click 依序送 WM_ACTIVATE → WM_SETFOCUS → WM_MOUSEMOVE(先導) → DOWN/UP
    captured = []
    _orig_pm = user32.PostMessageW
    user32.PostMessageW = lambda hwnd, msg, wparam, lparam: (
        captured.append((msg, wparam, lparam)) or True
    )
    try:
        _click_postmessage(1, 5, 6)
        msgs = [m for m, _, _ in captured]
        assert msgs[0:2] == [WM_ACTIVATE, WM_SETFOCUS], f"click 應先送啟用訊息: {msgs}"
        assert msgs[2] == WM_MOUSEMOVE, f"click 應先導 WM_MOUSEMOVE: {msgs}"
        assert WM_LBUTTONDOWN in msgs and WM_LBUTTONUP in msgs, msgs
    finally:
        user32.PostMessageW = _orig_pm
    print("  [OK] _click_postmessage 動作前啟用 + 先導 WM_MOUSEMOVE")

    # keep_active 公開 API：pynput no-op；frida 委派到底層（此處僅測不可用路徑）
    set_method("pynput")
    assert keep_active(1, True) is True, "pynput 模式 keep_active 應 no-op"
    set_method("frida")
    assert keep_active(0, True) is False, "frida 模式無效 hwnd 應失敗"
    assert keep_active(0, False) is True, "frida 模式關閉 keep-active 應成功"
    print("  [OK] keep_active 公開 API")

    print("\n=== All checks passed ===")
