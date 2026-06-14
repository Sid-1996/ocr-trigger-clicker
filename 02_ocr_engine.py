import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

_engine: Optional[RapidOCR] = None


@dataclass
class OcrResult:
    text: str
    x: int
    y: int
    w: int
    h: int
    confidence: float
    center_x: int = field(init=False)
    center_y: int = field(init=False)

    def __post_init__(self):
        self.center_x = self.x + self.w // 2
        self.center_y = self.y + self.h // 2


def _box_to_rect(box) -> tuple[int, int, int, int]:
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    x = min(xs)
    y = min(ys)
    w = max(xs) - x
    h = max(ys) - y
    return int(x), int(y), int(w), int(h)


def init_engine() -> None:
    global _engine
    _engine = RapidOCR()


def recognize(
    image: np.ndarray,
    roi_offset: dict | None = None,
    preprocess: bool = True,
) -> list[OcrResult]:
    if _engine is None:
        init_engine()
    if image is None or image.size == 0:
        return []
    img = image.copy()
    if preprocess:
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        img = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    ox, oy = (roi_offset["x"], roi_offset["y"]) if roi_offset else (0, 0)
    result = _engine(img)
    results: list[OcrResult] = []
    if result is None or result[0] is None:
        return results
    for box, text, score in result[0]:
        if score is None or score < 0.5:
            continue
        rx, ry, rw, rh = _box_to_rect(box)
        results.append(OcrResult(text=text, x=rx + ox, y=ry + oy, w=rw, h=rh, confidence=score))
    return results


def find_text(
    results: list[OcrResult],
    target: str,
    fuzzy: bool = False,
    threshold: float = 0.8,
) -> list[OcrResult]:
    matched: list[OcrResult] = []
    target_lower = target.lower()
    for r in results:
        if fuzzy:
            ratio = SequenceMatcher(None, target_lower, r.text.lower()).ratio()
            if ratio >= threshold:
                matched.append(r)
        else:
            if target_lower in r.text.lower():
                matched.append(r)
    return matched


if __name__ == "__main__":
    t0 = time.perf_counter()
    init_engine()
    t1 = time.perf_counter()
    print(f"引擎初始化完成，耗時 {(t1 - t0) * 1000:.1f} ms")

    png_path = Path(__file__).parent / "test_output.png"
    if not png_path.exists():
        print(f"找不到 {png_path}，請先執行 01_screenshot.py 產生測試截圖")
        raise SystemExit(1)

    img_bgr = cv2.imread(str(png_path))
    print(f"已讀取 {png_path}，尺寸: {img_bgr.shape[1]}x{img_bgr.shape[0]}")

    results = recognize(img_bgr)
    print(f"\n=== OCR 辨識結果（共 {len(results)} 筆）===")
    for r in results:
        print(f"  [{r.confidence:.2f}] {r.text!r}  ({r.x},{r.y}) {r.w}x{r.h}")

    keyword = input("\n請輸入搜尋關鍵字（精確比對）: ").strip()
    exact = find_text(results, keyword)
    print(f"精確比對找到 {len(exact)} 筆:")
    for r in exact:
        print(f"  {r.text!r}  center=({r.center_x},{r.center_y})")

    fuzzy_word = input("\n請輸入搜尋關鍵字（模糊比對，可故意打錯）: ").strip()
    fuzzy = find_text(results, fuzzy_word, fuzzy=True)
    print(f"模糊比對找到 {len(fuzzy)} 筆 (threshold=0.8):")
    for r in fuzzy:
        print(f"  {r.text!r}  center=({r.center_x},{r.center_y})")

    count = 10
    t0 = time.perf_counter()
    for _ in range(count):
        recognize(img_bgr)
    t1 = time.perf_counter()
    avg = (t1 - t0) / count * 1000
    print(f"\n執行 {count} 次 recognize()，平均每次 {avg:.1f} ms")
