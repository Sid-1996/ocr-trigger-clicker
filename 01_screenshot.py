import time

import mss
import numpy as np
import pygetwindow as gw


def list_windows() -> list[str]:
    return [w.title for w in gw.getWindowsWithTitle("") if w.title and w.visible]


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
