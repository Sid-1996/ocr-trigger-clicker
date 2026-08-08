"""Background input module — supports multiple interaction methods.

Methods:
- postmessage: Pure PostMessage (no cursor movement, works for some apps)
- pynput: Physical input via pynput (requires foreground, works for all apps)
- frida: Frida 行程注入 + PostMessage（零閃爍 Unity 後台點擊，見 18_frida_bg.py）
  click 委派給 frida 模組；key/scroll/drag 回退 postmessage（v1 限制）

Usage:
    from core.bg_input import click, send_key, set_method
    set_method("postmessage")
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
WM_ACTIVATE = 0x0006
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010
WA_ACTIVE = 0x01
WHEEL_DELTA = 120


# ── Current method ──
_method = "pynput"  # default: foreground mode (safe)


def set_method(method: str) -> None:
    """Set the interaction method: 'postmessage', 'pynput', or 'frida'."""
    global _method
    if method not in ("postmessage", "pynput", "frida"):
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

        user32.PostMessageW(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
        time.sleep(0.02)
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
        scan_code = user32.MapVirtualKeyW(vk_code, 0)
        lparam = (scan_code << 16) | 1
        if not down:
            lparam |= (1 << 30) | (1 << 31)
        msg = WM_KEYDOWN if down else WM_KEYUP
        user32.PostMessageW(hwnd, msg, vk_code, lparam)
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
        if _method == "postmessage":
            return _click_postmessage(hwnd, x, y, button, hold_ms)
        elif _method == "frida":
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


def last_error() -> str:
    """Last Frida error message (empty if none)."""
    try:
        return _frida().last_error()
    except Exception:
        return ""


def send_key(hwnd: int, key: str) -> bool:
    """Send a key press and release."""
    vk_map = {
        "enter": 0x0D,
        "escape": 0x1B,
        "space": 0x20,
        "tab": 0x09,
        "backspace": 0x08,
        "delete": 0x2E,
        "up": 0x26,
        "down": 0x28,
        "left": 0x25,
        "right": 0x27,
        "f1": 0x70,
        "f5": 0x74,
    }
    key_lower = key.strip().lower()
    vk = vk_map.get(key_lower)
    if vk is None and len(key) == 1:
        vk = ord(key.upper())
    if vk is None:
        _log.warning("Cannot parse key: %s", key)
        return False

    with _lock:
        if _method in ("postmessage", "frida"):
            ok = _key_postmessage(hwnd, vk, True)
            time.sleep(0.02)
            ok = _key_postmessage(hwnd, vk, False) and ok
            return ok
        elif _method == "pynput":
            ok = _key_pynput(hwnd, vk, True)
            time.sleep(0.02)
            ok = _key_pynput(hwnd, vk, False) and ok
            return ok
        return False


def scroll(hwnd: int, x: int, y: int, amount: int = 1, horizontal: bool = False) -> bool:
    """Scroll at (x, y). Positive = up/right, negative = down/left."""
    with _lock:
        if _method in ("postmessage", "frida"):
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
    vk_map = {
        "enter": 0x0D,
        "escape": 0x1B,
        "space": 0x20,
        "tab": 0x09,
        "backspace": 0x08,
        "delete": 0x2E,
        "up": 0x26,
        "down": 0x28,
        "left": 0x25,
        "right": 0x27,
        "f1": 0x70,
        "f5": 0x74,
    }
    key_lower = key.strip().lower()
    vk = vk_map.get(key_lower)
    if vk is None and len(key) == 1:
        vk = ord(key.upper())
    if vk is None:
        _log.warning("Cannot parse key for hold: %s", key)
        return False

    with _lock:
        if _method in ("postmessage", "frida"):
            ok = _key_postmessage(hwnd, vk, True)
            time.sleep(hold_ms / 1000.0)
            ok = _key_postmessage(hwnd, vk, False) and ok
            return ok
        elif _method == "pynput":
            return False
    return False


def drag(
    hwnd: int, start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left"
) -> bool:
    """Perform a drag operation in background mode."""
    with _lock:
        if _method in ("postmessage", "frida"):
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

    set_method("postmessage")
    assert get_method() == "postmessage"
    print("  [OK] set_method('postmessage')")

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
    set_method("postmessage")
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

    print("\n=== All 5 tests passed ===")
