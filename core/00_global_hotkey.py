import ctypes

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000

# hotkey_id -> (name, handler_method_name, vk_code)
_HOTKEYS = {
    1: ("F8", "_f8_snapshot", 0x77),
    2: ("F10", "_toggle_start_stop", 0x79),
    3: ("F12", "_close_tool", 0x7B),
}


def register_all(hwnd: int) -> None:
    for hid, (_, _, vk) in _HOTKEYS.items():
        ctypes.windll.user32.RegisterHotKey(ctypes.c_void_p(hwnd), hid, MOD_NOREPEAT, vk)


def unregister_all(hwnd: int) -> None:
    for hid in _HOTKEYS:
        ctypes.windll.user32.UnregisterHotKey(ctypes.c_void_p(hwnd), hid)


def handler_name(msg) -> str | None:
    if msg.message == WM_HOTKEY and msg.wParam in _HOTKEYS:
        return _HOTKEYS[msg.wParam][1]
    return None
