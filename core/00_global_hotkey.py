import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000

_HOTKEYS = {
    1: ("F8", 0x77),
    2: ("F12", 0x7B),
}


class GlobalHotkeyFilter(QObject):
    triggered = pyqtSignal(int)

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam in _HOTKEYS:
                self.triggered.emit(msg.wParam)
                return True, 0
        return False, 0


def register(hwnd: int) -> None:
    for hid, (_, vk) in _HOTKEYS.items():
        ctypes.windll.user32.RegisterHotKey(hwnd, hid, MOD_NOREPEAT, vk)


def unregister(hwnd: int) -> None:
    for hid in _HOTKEYS:
        ctypes.windll.user32.UnregisterHotKey(hwnd, hid)
