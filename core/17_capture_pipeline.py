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


_SAMPLE_COLS = 5
_SAMPLE_ROWS = 5
_SAMPLE_EDGE = 0.1
_SAMPLE_PATCH = 2  # ±2px → 5×5 patch
_MIN_VISIBLE_POINTS = 5
# ponytail: 純黑過場與小轉圈/通知低於此門檻；調高會更保守（極暗遊戲可能漏提示）
_CONTENT_MIN_MEAN = 8.0


def _sample_points(width: int, height: int) -> list[tuple[int, int]]:
    """客戶區內的 5×5 取樣點（左上為原點），邊緣留 10% 避開圓角。"""
    xs = [
        min(
            width - 1, int(width * (_SAMPLE_EDGE + (1 - 2 * _SAMPLE_EDGE) * i / (_SAMPLE_COLS - 1)))
        )
        for i in range(_SAMPLE_COLS)
    ]
    ys = [
        min(
            height - 1,
            int(height * (_SAMPLE_EDGE + (1 - 2 * _SAMPLE_EDGE) * i / (_SAMPLE_ROWS - 1))),
        )
        for i in range(_SAMPLE_ROWS)
    ]
    return [(x, y) for y in ys for x in xs]


def _patches_mean(img: np.ndarray, points: list[tuple[int, int]]) -> float | None:
    """取樣點周圍 5×5 像素的平均亮度；完全落在影像外時回 None。"""
    h, w = img.shape[:2]
    values = []
    for x, y in points:
        x1, x2 = max(0, x - _SAMPLE_PATCH), min(w, x + _SAMPLE_PATCH + 1)
        y1, y2 = max(0, y - _SAMPLE_PATCH), min(h, y + _SAMPLE_PATCH + 1)
        if x2 <= x1 or y2 <= y1:
            continue
        values.append(float(img[y1:y2, x1:x2].mean()))
    return sum(values) / len(values) if values else None


def screen_has_content(title: str, hwnd: int | None) -> bool | None:
    """PrintWindow 全黑時，確認螢幕上該視窗是否真的有畫面。

    True  = 未被遮擋的客戶區平均亮度達門檻（遊戲有畫面卻截不到，真不支援）
    False = 可見區域也是近黑（遊戲黑幕過場）
    None  = 無法判定（被遮擋、視窗不在螢幕上、截圖失敗）
    """
    if not hwnd:
        return None
    try:
        rect = _screenshot.get_window_rect_hwnd(hwnd)
        offset = _screenshot.get_client_offset_hwnd(hwnd)
        size = _screenshot.get_client_size_hwnd(hwnd)
        if rect is None or offset is None or size is None:
            return None
        cw, ch = size
        if cw <= 0 or ch <= 0:
            return None

        visible = [
            (offset[0] + x, offset[1] + y)
            for x, y in _sample_points(cw, ch)
            if _pw.is_point_on_window(hwnd, rect["x"] + offset[0] + x, rect["y"] + offset[1] + y)
        ]
        if len(visible) < _MIN_VISIBLE_POINTS:
            return None

        img = _screenshot.capture(title, rect, hwnd)
        if img is None or img.shape[0] != rect["h"] or img.shape[1] != rect["w"]:
            return None
        mean = _patches_mean(img, visible)
        if mean is None:
            return None
        return mean >= _CONTENT_MIN_MEAN
    except Exception:
        _log.debug("screen_has_content failed", exc_info=True)
        return None


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
