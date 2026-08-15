import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000

_HOTKEYS = {
    1: ("F8", 0x77),
    2: ("F9", 0x78),
}


def handle_native_event(eventType, message):
    """Called from MainWindow.nativeEvent — QC 的 QWidget.nativeEvent
    是最可靠的 Windows 訊息攔截點，QAbstractNativeEventFilter 在 PyQt6 6.11
    實測無法收到 callback。"""
    if eventType == b"windows_generic_MSG":
        try:
            msg = wintypes.MSG.from_address(int(message))
        except Exception as e:
            logger.error(f"MSG.from_address 失敗: {e}")
            return False, 0, None
        if msg.message == WM_HOTKEY:
            wparam = msg.wParam
            if wparam in _HOTKEYS:
                name = _HOTKEYS[wparam][0]
                logger.info(f"handle_native_event: WM_HOTKEY wParam={wparam} ({name})")
                return True, 0, int(wparam)
            else:
                logger.debug(f"WM_HOTKEY wParam={wparam} not registered")
                return True, 0, None
    return False, 0, None


def register(hwnd: int) -> dict[int, bool]:
    results: dict[int, bool] = {}
    for hid, (name, vk) in _HOTKEYS.items():
        ctypes.windll.kernel32.SetLastError(0)
        ok = ctypes.windll.user32.RegisterHotKey(hwnd, hid, MOD_NOREPEAT, vk)
        if not ok:
            err = ctypes.get_last_error()
            logger.warning(f"RegisterHotKey 失敗: {name} (id={hid}) hwnd={hwnd} error_code={err}")
        else:
            logger.info(f"RegisterHotKey 成功: {name} (id={hid}) hwnd={hwnd}")
        results[hid] = bool(ok)
    return results


def unregister(hwnd: int) -> None:
    for hid in _HOTKEYS:
        ctypes.windll.user32.UnregisterHotKey(hwnd, hid)


if __name__ == "__main__":
    # ponytail: automated self-check (run via python core/00_global_hotkey.py)
    assert _HOTKEYS == {1: ("F8", 0x77), 2: ("F9", 0x78)}, _HOTKEYS

    # non-windows event must pass through
    assert handle_native_event("other_event", 0) == (False, 0, None)

    # WM_HOTKEY with a registered id returns (True, 0, hid)
    msg = wintypes.MSG()
    msg.message = WM_HOTKEY
    msg.wParam = 1
    assert handle_native_event(b"windows_generic_MSG", ctypes.addressof(msg)) == (True, 0, 1)

    # WM_HOTKEY with unknown id is swallowed
    msg2 = wintypes.MSG()
    msg2.message = WM_HOTKEY
    msg2.wParam = 999
    assert handle_native_event(b"windows_generic_MSG", ctypes.addressof(msg2)) == (True, 0, None)

    # non-WM_HOTKEY message passes through
    msg3 = wintypes.MSG()
    msg3.message = 0x0100  # WM_KEYDOWN
    assert handle_native_event(b"windows_generic_MSG", ctypes.addressof(msg3)) == (False, 0, None)

    print("  [OK] global_hotkey self-check")
