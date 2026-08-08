"""統一台式截圖管道 — 依 interaction_mode 選用唯一截圖方法，全路徑同源。

建立模板 / 測試 / 圖片比對 / 主循環執行全部走 capture_frame()，
確保比對畫面與建立模板畫面來源一致（前景 mss，後台 PrintWindow）。
"""

import logging

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


def _capture_foreground(title: str) -> np.ndarray | None:
    img = _screenshot.capture(title)
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


def capture_frame(mode: str, title: str, hwnd: int | None = None) -> np.ndarray | None:
    """依 interaction_mode 取得全視窗 BGR 影像（含黑邊填補）。"""
    if mode != "pynput":
        return _capture_background(title, hwnd)
    return _capture_foreground(title)


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
