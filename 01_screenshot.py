import ctypes
import time
from ctypes import wintypes

import cv2
import mss
import numpy as np
import pygetwindow as gw


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


def list_windows() -> list[str]:
    return [w.title for w in gw.getWindowsWithTitle("") if w.title and w.visible]


def activate_window(title: str) -> bool:
    matches = [w for w in gw.getWindowsWithTitle(title) if w.title and w.visible]
    if not matches:
        return False
    try:
        matches[0].activate()
        return True
    except Exception:
        return False


def get_window_rect(title: str) -> dict | None:
    matches = [w for w in gw.getWindowsWithTitle(title) if w.title and w.visible]
    if not matches:
        return None
    window = matches[0]
    if window.isMinimized:
        return None
    return {"x": window.left, "y": window.top, "w": window.width, "h": window.height}


def capture(title: str, roi: dict | None = None) -> np.ndarray | None:
    rect = get_window_rect(title)
    if rect is None:
        return None
    x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
    if roi:
        x += roi["x"]
        y += roi["y"]
        w = roi["w"]
        h = roi["h"]
    region = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
    try:
        with mss.mss() as sct:
            img = sct.grab(region)
            arr = np.array(img)
            return arr[:, :, :3]
    except Exception:
        return None


def _gdi_capture(hwnd: int, render_fn) -> np.ndarray | None:
    """Generic GDI capture: set up DC+bitmap, call render_fn(mem_dc, hwnd, w, h), read pixels."""
    hwnd_dc = None
    mem_dc = None
    hbitmap = None
    try:
        rect = wintypes.RECT()
        ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
        w, h = rect.right, rect.bottom
        if w <= 0 or h <= 0:
            return None

        hwnd_dc = ctypes.windll.user32.GetDC(hwnd)
        mem_dc = ctypes.windll.gdi32.CreateCompatibleDC(hwnd_dc)
        hbitmap = ctypes.windll.gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
        ctypes.windll.gdi32.SelectObject(mem_dc, hbitmap)

        if not render_fn(hwnd, mem_dc, w, h):
            return None

        bmp_info = _BITMAPINFOHEADER()
        bmp_info.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmp_info.biWidth = w
        bmp_info.biHeight = -h
        bmp_info.biPlanes = 1
        bmp_info.biBitCount = 32
        bmp_info.biCompression = 0

        buf = ctypes.create_string_buffer(w * h * 4)
        ok = ctypes.windll.gdi32.GetDIBits(mem_dc, hbitmap, 0, h, buf, ctypes.byref(bmp_info), 0)
        if not ok:
            return None

        img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
    except Exception:
        return None
    finally:
        if hbitmap:
            ctypes.windll.gdi32.DeleteObject(hbitmap)
        if mem_dc:
            ctypes.windll.gdi32.DeleteDC(mem_dc)
        if hwnd_dc:
            ctypes.windll.user32.ReleaseDC(hwnd, hwnd_dc)


def _pw_render(hwnd: int, mem_dc: int, w: int, h: int) -> bool:
    return bool(ctypes.windll.user32.PrintWindow(hwnd, mem_dc, 3))


def _bitblt_render(hwnd: int, mem_dc: int, w: int, h: int) -> bool:
    hwnd_dc = ctypes.windll.user32.GetDC(hwnd)
    try:
        CAPTUREBLT = 0x40000000
        SRCCOPY = 0x00CC0020
        return bool(
            ctypes.windll.gdi32.BitBlt(mem_dc, 0, 0, w, h, hwnd_dc, 0, 0, SRCCOPY | CAPTUREBLT)
        )
    finally:
        ctypes.windll.user32.ReleaseDC(hwnd, hwnd_dc)


def capture_window_content(title: str) -> np.ndarray | None:
    """擷取視窗本身的內容（非螢幕畫面），不受疊層視窗遮擋。

    優先使用 PrintWindow API 直接讀取目標視窗的 client area。
    若 PrintWindow 失敗（常見於 DirectX 遊戲），自動改用
    BitBlt + CAPTUREBLT 從視窗 DC 讀取畫面。
    兩者都失敗則回傳 None，由呼叫端處理。
    """
    matches = [w for w in gw.getWindowsWithTitle(title) if w.title and w.visible]
    if not matches:
        return None
    hwnd = matches[0]._hWnd

    img = _gdi_capture(hwnd, _pw_render)
    if img is not None:
        return img

    return _gdi_capture(hwnd, _bitblt_render)


if __name__ == "__main__":
    windows = list_windows()
    print("=== 所有可見視窗 ===")
    for i, w in enumerate(windows, 1):
        print(f"{i:3d}. {w}")

    target = input("\n請輸入要測試的視窗標題關鍵字: ").strip()
    rect = get_window_rect(target)
    print(f"\n視窗座標: {rect}")

    if rect is not None:
        count = 100
        start = time.perf_counter()
        last_img = None
        for _ in range(count):
            last_img = capture(target)
        elapsed = time.perf_counter() - start
        print(f"\n截圖 {count} 次，耗時 {elapsed:.3f} 秒")
        print(f"平均 FPS: {count / elapsed:.1f}")

        if last_img is not None:
            import cv2

            bgr = cv2.cvtColor(last_img, cv2.COLOR_RGB2BGR)
            cv2.imwrite("test_output.png", bgr)
            print("已儲存 test_output.png")
