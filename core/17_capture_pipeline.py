"""統一台式截圖管道 — 依 interaction_mode 選用唯一截圖方法，全路徑同源。

建立模板 / 測試 / 圖片比對 / 主循環執行全部走 capture_frame()，
確保比對畫面與建立模板畫面來源一致（前景 mss，後台 PrintWindow）。
"""

import logging
import threading

import numpy as np

from _loader import load_sibling

_log = logging.getLogger(__name__)

_screenshot = load_sibling("screenshot", "core/01_screenshot.py")
_pw = load_sibling("print_window", "core/15_print_window.py")


def _pad_to_full(img: np.ndarray, title: str) -> np.ndarray:
    wr = _screenshot.get_window_rect(title)
    if wr and (img.shape[0] != wr["h"] or img.shape[1] != wr["w"]):
        chrome = _screenshot.get_window_client_offset(title) or (0, 0)
        cx, cy = chrome
        full_h, full_w = wr["h"], wr["w"]
        padded = np.zeros((full_h, full_w, img.shape[2]), dtype=img.dtype)
        padded[cy : cy + img.shape[0], cx : cx + img.shape[1]] = img
        return padded
    return img


def _capture_foreground(
    title: str, rect: dict | None = None, hwnd: int | None = None
) -> np.ndarray | None:
    img = _screenshot.capture(title, rect, hwnd)
    if img is not None:
        return img
    img = _screenshot.capture_window_content(title)
    if img is not None:
        return _pad_to_full(img, title)
    return None


def _capture_background(title: str, hwnd: int | None) -> np.ndarray | None:
    img = _pw.capture_print_window_hwnd(hwnd) if hwnd else _pw.capture_print_window(title)
    if img is not None:
        return img
    return _capture_foreground(title)


def capture_frame(
    mode: str, title: str, hwnd: int | None = None, rect: dict | None = None
) -> np.ndarray | None:
    """依 interaction_mode 取得全視窗 BGR 影像（含黑邊填補）。

    rect/hwnd 由呼叫端提供時，前景路徑不需再做標題列舉（避開跨行程
    GetWindowText 阻塞整個行程的 GIL）。
    """
    if mode != "pynput":
        return _capture_background(title, hwnd)
    return _capture_foreground(title, rect, hwnd)


class TimedCapture:
    """Run background captures on a daemon worker so PrintWindow can't freeze the loop.

    A capture that exceeds ``timeout`` returns ``(None, True)``; the worker keeps
    running and its result is returned by the next call instead of piling up
    another PrintWindow request. Pass ``fresh=True`` to discard a pending result
    and wait for a capture taken after the call (used by verify polling).
    """

    def __init__(self):
        self._cv = threading.Condition()
        self._request = None
        self._result = None
        self._has_result = False
        self._busy = False
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="capture-worker", daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            with self._cv:
                self._cv.wait_for(lambda: self._request is not None or self._closed)
                if self._closed:
                    return
                request = self._request
                self._request = None
            try:
                result = capture_frame(*request)
            except Exception:
                _log.exception("background capture failed")
                result = None
            with self._cv:
                self._result = result
                self._has_result = True
                self._busy = False
                self._cv.notify_all()

    def capture(
        self,
        mode: str,
        title: str,
        hwnd: int | None = None,
        rect: dict | None = None,
        timeout: float = 0.5,
        fresh: bool = False,
    ) -> tuple[np.ndarray | None, bool]:
        request = (mode, title, hwnd, rect)
        with self._cv:
            if self._closed:
                return None, False
            if fresh:
                if self._has_result:
                    self._result = None
                    self._has_result = False
                elif self._busy:
                    if not self._cv.wait_for(
                        lambda: self._has_result or self._closed, timeout=timeout
                    ):
                        return None, True
                    if not self._has_result:
                        return None, False
                    self._result = None
                    self._has_result = False
            elif self._has_result:
                result = self._result
                self._result = None
                self._has_result = False
                return result, False
            if self._closed:
                return None, False
            if not self._busy:
                self._request = request
                self._busy = True
                self._cv.notify()
            if not self._cv.wait_for(lambda: self._has_result or self._closed, timeout=timeout):
                return None, True
            if not self._has_result:
                return None, False
            result = self._result
            self._result = None
            self._has_result = False
            return result, False

    def close(self):
        with self._cv:
            self._closed = True
            self._cv.notify_all()


if __name__ == "__main__":
    print("=== Capture Pipeline Self-Check ===\n")

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
        for mode in ("pynput", "frida"):
            img = capture_frame(mode, test_title)
            if img is not None:
                print(f"  [{mode}] OK {img.shape[1]}x{img.shape[0]}")
                import cv2

                cv2.imwrite(f"__pipeline_{mode}.png", img)
            else:
                print(f"  [{mode}] FAIL")
    else:
        print("\n  找不到 StarSavior，跳過截圖測試")

    print("\n=== Self-Check 完成 ===")
