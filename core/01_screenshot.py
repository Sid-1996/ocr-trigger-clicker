import ctypes
import logging
import threading
import time
from ctypes import wintypes

import cv2
import mss
import numpy as np
import pygetwindow as gw

_mss_tls = threading.local()


def _get_mss() -> mss.mss:
    if not hasattr(_mss_tls, "instance") or _mss_tls.instance is None:
        _mss_tls.instance = mss.mss()
    return _mss_tls.instance


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


def _matching_windows(title: str):
    matches = [w for w in gw.getWindowsWithTitle(title) if w.title and w.visible]
    exact = [w for w in matches if w.title == title]
    return exact or matches


def get_window_hwnd(title: str) -> int | None:
    matches = _matching_windows(title)
    if not matches:
        return None
    return getattr(matches[0], "_hWnd", None)


def get_window_client_offset(title: str) -> tuple[int, int] | None:
    """Returns (offset_x, offset_y) from window top-left to client area top-left."""
    try:
        hwnd = get_window_hwnd(title)
        if hwnd is None:
            return None

        pt = wintypes.POINT(0, 0)
        ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
        window_rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(window_rect))
        return (pt.x - window_rect.left, pt.y - window_rect.top)
    except Exception:
        return None


def activate_window(title: str) -> bool:
    matches = _matching_windows(title)
    if not matches:
        return False
    try:
        matches[0].activate()
        return True
    except Exception:
        return False


def get_window_rect(title: str) -> dict | None:
    try:
        matches = _matching_windows(title)
        if not matches:
            return None
        window = matches[0]
        if window.isMinimized:
            return None
        return {"x": window.left, "y": window.top, "w": window.width, "h": window.height}
    except Exception:
        return None


def capture(title: str) -> np.ndarray | None:
    rect = get_window_rect(title)
    if rect is None:
        return None
    try:
        sct = _get_mss()
        left = rect["x"]
        top = rect["y"]
        right = rect["x"] + rect["w"]
        bottom = rect["y"] + rect["h"]

        # 多螢幕支援：找出涵蓋此視窗的螢幕（跳過 monitors[0] 全局虛擬螢幕）
        best_monitor = None
        for m in sct.monitors[1:]:
            mx1, my1 = m["left"], m["top"]
            mx2, my2 = mx1 + m["width"], my1 + m["height"]
            if left < mx2 and right > mx1 and top < my2 and bottom > my1:
                best_monitor = m
                break
        if best_monitor is None:
            best_monitor = sct.monitors[0]

        x1 = max(left, best_monitor["left"])
        y1 = max(top, best_monitor["top"])
        x2 = min(right, best_monitor["left"] + best_monitor["width"])
        y2 = min(bottom, best_monitor["top"] + best_monitor["height"])
        if x2 <= x1 or y2 <= y1:
            return None

        region = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}
        img = sct.grab(region)
        arr = np.array(img)
        return arr[:, :, :3]
    except Exception:
        logging.warning("mss capture failed for '%s'", title, exc_info=True)
        return None


def get_dpi_scaling_factor(hwnd: int | None) -> float:
    if not hwnd:
        return 1.0
    try:
        from ctypes import byref, c_int, windll

        dpi_x = c_int()
        dpi_y = c_int()
        if hasattr(windll.user32, "GetDpiForWindow"):
            dpi = windll.user32.GetDpiForWindow(hwnd)
            if dpi:
                return dpi / 96.0
        monitor = windll.user32.MonitorFromWindow(hwnd, 2)
        if monitor and hasattr(windll.shcore, "GetDpiForMonitor"):
            windll.shcore.GetDpiForMonitor(monitor, 0, byref(dpi_x), byref(dpi_y))
            if dpi_x.value:
                return dpi_x.value / 96.0
    except Exception:
        pass
    return 1.0


def _gdi_capture(hwnd: int, render_fn) -> np.ndarray | None:
    """Generic GDI capture: set up DC+bitmap, call render_fn(mem_dc, hwnd, w, h), read pixels."""
    hwnd_dc = None
    mem_dc = None
    hbitmap = None
    try:
        rect = wintypes.RECT()
        ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
        w = rect.right
        h = rect.bottom
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
        logging.warning("GDI capture failed for hwnd=%s", hwnd, exc_info=True)
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
    try:
        matches = _matching_windows(title)
        if not matches:
            return None
        hwnd = matches[0]._hWnd
    except Exception:
        return None

    img = _gdi_capture(hwnd, _pw_render)
    if img is not None:
        return img

    return _gdi_capture(hwnd, _bitblt_render)


capture_window_full = capture_window_content  # backward compat alias


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
