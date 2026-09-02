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
_dxcam_tls = threading.local()


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


# 獨立 DLL 實例，argtypes/restype 只作用於本模組，不污染 ctypes.windll 全域
# （避免影響 pygetwindow 等其他未設 argtypes 的 ctypes.windll 呼叫端）
_user32 = ctypes.WinDLL("user32")
_gdi32 = ctypes.WinDLL("gdi32")
_shcore = ctypes.WinDLL("shcore")

_user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetClientRect.restype = wintypes.BOOL
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_user32.ClientToScreen.restype = wintypes.BOOL
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_user32.ReleaseDC.restype = ctypes.c_int
_user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
_user32.PrintWindow.restype = wintypes.BOOL
_user32.GetDpiForWindow.argtypes = [wintypes.HWND]
_user32.GetDpiForWindow.restype = wintypes.UINT
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = wintypes.HMONITOR
_user32.GetDesktopWindow.restype = wintypes.HWND
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.IsZoomed.argtypes = [wintypes.HWND]
_user32.IsZoomed.restype = wintypes.BOOL
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
_user32.GetMonitorInfoW.restype = wintypes.BOOL
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int

_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
_gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteObject.restype = wintypes.BOOL
_gdi32.DeleteDC.argtypes = [wintypes.HDC]
_gdi32.DeleteDC.restype = wintypes.BOOL
_gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.POINTER(_BITMAPINFOHEADER),
    wintypes.UINT,
]
_gdi32.GetDIBits.restype = ctypes.c_int
_gdi32.BitBlt.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
]
_gdi32.BitBlt.restype = wintypes.BOOL

_shcore.GetDpiForMonitor.argtypes = [
    wintypes.HMONITOR,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
]
_shcore.GetDpiForMonitor.restype = ctypes.c_long


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


# ── Window standard working size helpers (generic, not 1600x900-locked) ──


def _calc_outer_size(client_w: int, client_h: int, chrome_w: int, chrome_h: int) -> tuple[int, int]:
    """Pure: outer = client + chrome (chrome = outer-client). No Win32."""
    return client_w + chrome_w, client_h + chrome_h


def _calc_centered_pos(
    work_x: int, work_y: int, work_w: int, work_h: int, outer_w: int, outer_h: int
) -> tuple[int, int]:
    """Pure: centered top-left inside work area (clamped to work origin)."""
    x = work_x + (work_w - outer_w) // 2
    y = work_y + (work_h - outer_h) // 2
    if outer_w >= work_w:
        x = work_x
    if outer_h >= work_h:
        y = work_y
    return x, y


def _rects_equal_fullscreen(
    win_left: int,
    win_top: int,
    win_right: int,
    win_bottom: int,
    mon_left: int,
    mon_top: int,
    mon_right: int,
    mon_bottom: int,
) -> bool:
    """Pure: window outer covers monitor (allow fullscreen/borderless)."""
    return (
        win_left <= mon_left
        and win_top <= mon_top
        and win_right >= mon_right
        and win_bottom >= mon_bottom
    )


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
        _user32.ClientToScreen(hwnd, ctypes.byref(pt))
        window_rect = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(window_rect))
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


def activate_window_bg(title: str) -> bool:
    """Activate window using WM_ACTIVATE (does not steal foreground focus)."""
    hwnd = get_window_hwnd(title)
    if hwnd is None:
        return False
    try:
        user32 = _user32
        WM_ACTIVATE = 0x0006
        WA_ACTIVE = 0x01
        user32.PostMessageW(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
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


def get_window_client_size(title: str) -> tuple[int, int] | None:
    """Returns (client_w, client_h) for the window, or None if not found."""
    try:
        hwnd = get_window_hwnd(title)
        if hwnd is None:
            return None
        rect = wintypes.RECT()
        if not _user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        return int(rect.right), int(rect.bottom)
    except Exception:
        return None


def is_window_fullscreen(title: str) -> bool:
    """True if window outer covers its monitor (exclusive/borderless/maximized fullscreen)."""
    try:
        hwnd = get_window_hwnd(title)
        if hwnd is None:
            return False
        win = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(win)):
            return False
        mon = _user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        if not mon:
            return False
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return False
        return _rects_equal_fullscreen(
            win.left,
            win.top,
            win.right,
            win.bottom,
            mi.rcMonitor.left,
            mi.rcMonitor.top,
            mi.rcMonitor.right,
            mi.rcMonitor.bottom,
        )
    except Exception:
        return False


def resize_window_to_client(title: str, width: int, height: int) -> str:
    """Resize window so its client area becomes (width x height).

    Generic — not locked to 1600x900. Caller decides the standard size.
    Returns: "ok" | "not_found" | "minimized" | "fullscreen" | "failed"
    Client notion: GetClientRect size; outer = client + chrome (title bar + borders).
    Centered in the window's current monitor work area.
    """
    if width <= 0 or height <= 0:
        return "failed"
    try:
        hwnd = get_window_hwnd(title)
        if hwnd is None:
            return "not_found"
        if _user32.IsIconic(hwnd):
            return "minimized"
        if is_window_fullscreen(title):
            return "fullscreen"
        # Restore if maximised (IsZoomed) — otherwise SetWindowPos size is ignored
        if _user32.IsZoomed(hwnd):
            SW_RESTORE = 9
            _user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.08)
            if _user32.IsIconic(hwnd) or is_window_fullscreen(title):
                return "fullscreen" if is_window_fullscreen(title) else "minimized"
        c_rect = wintypes.RECT()
        w_rect = wintypes.RECT()
        if not _user32.GetClientRect(hwnd, ctypes.byref(c_rect)):
            return "failed"
        if not _user32.GetWindowRect(hwnd, ctypes.byref(w_rect)):
            return "failed"
        c_w = int(c_rect.right)
        c_h = int(c_rect.bottom)
        if c_w == width and c_h == height:
            return "ok"
        outer_w = int(w_rect.right - w_rect.left)
        outer_h = int(w_rect.bottom - w_rect.top)
        chrome_w = outer_w - c_w
        chrome_h = outer_h - c_h
        # Defensive: some borderless windows report chrome 0 — still valid
        if chrome_w < 0:
            chrome_w = 0
        if chrome_h < 0:
            chrome_h = 0
        need_w, need_h = _calc_outer_size(width, height, chrome_w, chrome_h)
        mon = _user32.MonitorFromWindow(hwnd, 2)
        if mon:
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if _user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                work = mi.rcWork
                work_x, work_y = int(work.left), int(work.top)
                work_w = int(work.right - work.left)
                work_h = int(work.bottom - work.top)
                nx, ny = _calc_centered_pos(work_x, work_y, work_w, work_h, need_w, need_h)
            else:
                nx, ny = int(w_rect.left), int(w_rect.top)
        else:
            nx, ny = int(w_rect.left), int(w_rect.top)
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        ok = _user32.SetWindowPos(hwnd, None, nx, ny, need_w, need_h, SWP_NOZORDER | SWP_NOACTIVATE)
        if not ok:
            logging.warning(
                "resize_window_to_client: SetWindowPos failed for '%s' -> %dx%d client",
                title,
                width,
                height,
            )
            return "failed"
        return "ok"
    except Exception:
        logging.warning("resize_window_to_client failed for '%s'", title, exc_info=True)
        return "failed"


def _get_dxcam_output(window_rect: dict) -> int:
    try:
        user32 = _user32
        vw = user32.GetSystemMetrics(78)
        vh = user32.GetSystemMetrics(79)

        cx = window_rect["x"] + window_rect["w"] // 2
        cy = window_rect["y"] + window_rect["h"] // 2
        if cx < 0 or cy < 0 or cx >= vw or cy >= vh:
            return 0

        if _get_dxcam_output.factory is None:
            from dxcam import DXFactory

            _get_dxcam_output.factory = DXFactory()
        outputs = _get_dxcam_output.factory.outputs

        for idx, group in enumerate(outputs):
            for out in group:
                rw, rh = out.resolution
                if cx < rw and cy < rh:
                    return idx
    except Exception:
        pass
    return 0


_get_dxcam_output.factory = None


def _capture_dxcam(title: str, rect: dict) -> np.ndarray | None:
    import dxcam

    try:
        user32 = _user32
        vx = user32.GetSystemMetrics(76)
        vy = user32.GetSystemMetrics(77)
        vw = user32.GetSystemMetrics(78)
        vh = user32.GetSystemMetrics(79)

        left = max(rect["x"], vx)
        top = max(rect["y"], vy)
        right = min(rect["x"] + rect["w"], vx + vw)
        bottom = min(rect["y"] + rect["h"], vy + vh)
        if right <= left or bottom <= top:
            return None

        out_idx = _get_dxcam_output(rect)
        if not hasattr(_dxcam_tls, "cameras"):
            _dxcam_tls.cameras = {}
        if out_idx not in _dxcam_tls.cameras:
            _dxcam_tls.cameras[out_idx] = dxcam.create(output_idx=out_idx, output_color="BGR")
        camera = _dxcam_tls.cameras[out_idx]
        img = camera.grab(region=(left, top, right, bottom))
        return img
    except Exception:
        logging.warning("dxcam capture failed for '%s'", title, exc_info=True)
        return None


def _capture_mss(title: str, rect: dict) -> np.ndarray | None:
    try:
        sct = _get_mss()
        left = rect["x"]
        top = rect["y"]
        right = rect["x"] + rect["w"]
        bottom = rect["y"] + rect["h"]

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


def capture(title: str) -> np.ndarray | None:
    rect = get_window_rect(title)
    if rect is None:
        return None
    img = _capture_mss(title, rect)
    if img is not None:
        return img
    return _capture_dxcam(title, rect)


def get_dpi_scaling_factor(hwnd: int | None) -> float:
    if not hwnd:
        return 1.0
    try:
        from ctypes import byref, c_int

        dpi_x = c_int()
        dpi_y = c_int()
        if hasattr(_user32, "GetDpiForWindow"):
            dpi = _user32.GetDpiForWindow(hwnd)
            if dpi:
                return dpi / 96.0
        monitor = _user32.MonitorFromWindow(hwnd, 2)
        if monitor and hasattr(_shcore, "GetDpiForMonitor"):
            _shcore.GetDpiForMonitor(monitor, 0, byref(dpi_x), byref(dpi_y))
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
        _user32.GetClientRect(hwnd, ctypes.byref(rect))
        w = rect.right
        h = rect.bottom
        if w <= 0 or h <= 0:
            return None

        hwnd_dc = _user32.GetDC(hwnd)
        mem_dc = _gdi32.CreateCompatibleDC(hwnd_dc)
        hbitmap = _gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
        _gdi32.SelectObject(mem_dc, hbitmap)

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
        ok = _gdi32.GetDIBits(mem_dc, hbitmap, 0, h, buf, ctypes.byref(bmp_info), 0)
        if not ok:
            return None

        img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
    except Exception:
        logging.warning("GDI capture failed for hwnd=%s", hwnd, exc_info=True)
        return None
    finally:
        if hbitmap:
            _gdi32.DeleteObject(hbitmap)
        if mem_dc:
            _gdi32.DeleteDC(mem_dc)
        if hwnd_dc:
            _user32.ReleaseDC(hwnd, hwnd_dc)


def _pw_render(hwnd: int, mem_dc: int, w: int, h: int) -> bool:
    return bool(_user32.PrintWindow(hwnd, mem_dc, 3))


def _bitblt_render(hwnd: int, mem_dc: int, w: int, h: int) -> bool:
    hwnd_dc = _user32.GetDC(hwnd)
    try:
        CAPTUREBLT = 0x40000000
        SRCCOPY = 0x00CC0020
        return bool(_gdi32.BitBlt(mem_dc, 0, 0, w, h, hwnd_dc, 0, 0, SRCCOPY | CAPTUREBLT))
    finally:
        _user32.ReleaseDC(hwnd, hwnd_dc)


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
    import sys

    if "--check" in sys.argv:
        # ponytail: automated self-check (run via python core/01_screenshot.py --check)
        print("=== Screenshot Module Self-Check ===\n")
        assert list_windows() is not None
        print("  [OK] list_windows")

        rect = get_window_rect("Program Manager")
        if rect is not None:
            assert all(k in rect for k in ("x", "y", "w", "h"))
            print(f"  [OK] get_window_rect (Program Manager): {rect}")
        else:
            print("  [WARN] Program Manager not found (expected in some sessions)")

        assert get_dpi_scaling_factor(None) == 1.0
        print("  [OK] get_dpi_scaling_factor(default)")

        hwnd = _user32.GetDesktopWindow()
        dpi = get_dpi_scaling_factor(hwnd)
        assert 1.0 <= dpi <= 4.0
        print(f"  [OK] get_dpi_scaling_factor(desktop): {dpi:.2f}")

        offset = get_window_client_offset("Program Manager")
        if offset is not None:
            assert len(offset) == 2
            print(f"  [OK] get_window_client_offset: {offset}")
        else:
            print("  [WARN] get_window_client_offset returned None")

        print("\n=== All automated checks passed ===")
        raise SystemExit(0)

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
