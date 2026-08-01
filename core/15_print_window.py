"""PrintWindow 後台截圖模組 — 透過 Win32 API PrintWindow 取得視窗內容，不依賴前景。"""

import ctypes
import logging
from ctypes import wintypes

import numpy as np

_log = logging.getLogger(__name__)

PW_RENDERFULLCONTENT = 0x00000002

_gdi32 = ctypes.windll.gdi32
_user32 = ctypes.windll.user32


def is_admin() -> bool:
    """目前行程是否以系統管理員權限執行。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def is_black_capture(img) -> bool:
    """PrintWindow 權限失敗時回傳零初始化 bitmap（全像素為 0）；真實畫面再暗也有非零像素。"""
    if img is None or img.size == 0:
        return False
    return not img.any()


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def capture_print_window_hwnd(hwnd: int) -> np.ndarray | None:
    """透過 PrintWindow 截取指定 hwnd 的視窗內容。

    Returns:
        BGR numpy array 或 None（失敗時）
    """
    try:
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None

        hdc_window = _user32.GetDC(hwnd)
        if not hdc_window:
            return None

        hdc_mem = _gdi32.CreateCompatibleDC(hdc_window)
        if not hdc_mem:
            _user32.ReleaseDC(hwnd, hdc_window)
            return None

        h_bitmap = _gdi32.CreateCompatibleBitmap(hdc_window, w, h)
        if not h_bitmap:
            _gdi32.DeleteDC(hdc_mem)
            _user32.ReleaseDC(hwnd, hdc_window)
            return None

        old_bitmap = _gdi32.SelectObject(hdc_mem, h_bitmap)

        result = _user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
        if not result:
            _log.warning("PrintWindow failed for hwnd=%s", hwnd)

        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # 負數 = top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(w * h * 4)
        _gdi32.GetDIBits(hdc_mem, h_bitmap, 0, h, buf, ctypes.byref(bmi), 0)

        _gdi32.SelectObject(hdc_mem, old_bitmap)
        _gdi32.DeleteObject(h_bitmap)
        _gdi32.DeleteDC(hdc_mem)
        _user32.ReleaseDC(hwnd, hdc_window)

        frame = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
        return frame[:, :, :3].copy()  # BGRA → BGR

    except Exception as e:
        _log.error("capture_print_window_hwnd error: %s", e)
        return None


def capture_print_window(title: str) -> np.ndarray | None:
    """透過標題列文字找到 hwnd，再用 PrintWindow 截圖。"""
    import pygetwindow as gw

    matches = [w for w in gw.getWindowsWithTitle(title) if w.visible]
    exact = [w for w in matches if w.title == title]
    window = (exact or matches or [None])[0]
    if window is None:
        return None
    hwnd = getattr(window, "_hWnd", None)
    if hwnd is None:
        return None
    return capture_print_window_hwnd(hwnd)


if __name__ == "__main__":
    print("=== PrintWindow Self-Check ===\n")

    import pygetwindow as gw

    windows = [w.title for w in gw.getWindowsWithTitle("") if w.visible and w.title]
    print(f"  可見視窗 ({len(windows)}):")
    for t in windows[:10]:
        print(f"    - {t}")

    test_title = None
    for t in windows:
        if "StarSavior" in t:
            test_title = t
            break

    if test_title:
        print(f"\n  測試截圖: {test_title}")
        img = capture_print_window(test_title)
        if img is not None:
            print(f"  截圖成功: {img.shape[1]}x{img.shape[0]}")
            import cv2

            cv2.imwrite("__pw_test.png", img)
            print("  已儲存: __pw_test.png")
        else:
            print("  截圖失敗")
    else:
        print("\n  找不到 StarSavior，跳過截圖測試")

    print("\n=== Self-Check 完成 ===")
