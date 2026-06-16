import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from typing import Callable, Optional

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

OCR_BACKEND = "rapidocr"  # 可切換為 "easyocr" / "cnocr"

_engine = None
_engine_lock = threading.RLock()
_ocr_executor = ThreadPoolExecutor(max_workers=1)
_DEFAULT_DET_LIMIT_SIDE_LEN = 480
_DEFAULT_MAX_SIDE_LEN = 480
_DET_USE_V5: bool = False

_OCR_FAILURE_COUNT = 0
_OCR_FAILURE_LOCK = threading.Lock()
_OCR_MAX_FAILURES = 5
_OCR_HEALTH_CALLBACK: Optional[Callable[[str], None]] = None

def get_ocr_failure_count() -> int:
    with _OCR_FAILURE_LOCK:
        return _OCR_FAILURE_COUNT

def reset_ocr_failures():
    with _OCR_FAILURE_LOCK:
        _OCR_FAILURE_COUNT = 0

def set_ocr_health_callback(cb: Optional[Callable[[str], None]]):
    global _OCR_HEALTH_CALLBACK
    _OCR_HEALTH_CALLBACK = cb

def _incr_ocr_failure():
    global _engine, _OCR_FAILURE_COUNT
    with _OCR_FAILURE_LOCK:
        _OCR_FAILURE_COUNT += 1
        if _OCR_FAILURE_COUNT >= _OCR_MAX_FAILURES:
            msg = f"OCR 連續失敗 {_OCR_FAILURE_COUNT} 次，正在重啟引擎"
            print(f"[ocr_health] {msg}")
            with _engine_lock:
                _engine = None
            init_engine()
            _OCR_FAILURE_COUNT = 0
            cb = _OCR_HEALTH_CALLBACK
            if cb:
                cb(msg)
            return True
    return False

def _reset_ocr_failures():
    global _OCR_FAILURE_COUNT
    with _OCR_FAILURE_LOCK:
        _OCR_FAILURE_COUNT = 0


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
    with _engine_lock:
        if _engine is not None:
            return
        if OCR_BACKEND == "rapidocr":
            _here = Path(__file__).parent
            custom_dir = _here / "custom_models"
            rec_path = custom_dir / "chinese_cht_rec_mobile.onnx"
            dict_path = custom_dir / "chinese_cht_dict.txt"
            kwargs: dict = dict(
                det_limit_type="max",
                det_limit_side_len=_DEFAULT_DET_LIMIT_SIDE_LEN,
                use_cls=False,
                provider=["DmlExecutionProvider", "CPUExecutionProvider"],
                rec_model_path=str(rec_path),
                rec_img_shape=[3, 48, 320],
                rec_batch_num=1,
            )
            if _DET_USE_V5:
                det_path = custom_dir / "ch_PP-OCRv5_server_det.onnx"
                if det_path.exists():
                    kwargs["det_model_path"] = str(det_path)
            if dict_path.exists():
                kwargs["rec_keys_path"] = str(dict_path)

            _engine = RapidOCR(**kwargs)

            # 修正：v5 mobile rec 模型的 input width 是靜態 320，但 RapidOCR 的 resize_norm_img
            # 會根據 max_wh_ratio 動態計算 padding 寬度，導致寬度 >320 時模型 crash。
            # 這裡 monkey-patch 把 width 限制在 rec_image_shape[2]（320）以內。
            _orig_resize = type(_engine.text_rec).resize_norm_img
            def _patched_resize(self, img, max_wh_ratio):
                max_wh_ratio = min(max_wh_ratio, self.rec_image_shape[2] / self.rec_image_shape[1])
                return _orig_resize(self, img, max_wh_ratio)
            _engine.text_rec.resize_norm_img = _patched_resize.__get__(_engine.text_rec, type(_engine.text_rec))

            # 預先跑一次極小測試圖，避免第一次正式 OCR 才做模型 warm-up。
            warmup = np.full((96, 256, 3), 255, dtype=np.uint8)
            cv2.putText(
                warmup,
                "warmup",
                (12, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 0, 0),
                2,
                cv2.LINE_AA,
            )
            try:
                _engine(warmup, use_cls=False)
            except Exception:
                import traceback; traceback.print_exc()
        elif OCR_BACKEND == "easyocr":
            import easyocr

            _engine = easyocr.Reader(["ch_tra", "en"], gpu=False)
        elif OCR_BACKEND == "cnocr":
            from cnocr import CnOcr

            _engine = CnOcr(rec_model_name="densenet_lite_136-gru")


def _prepare_image(
    image: np.ndarray,
    max_side_len: int,
    preprocess: bool,
) -> tuple[np.ndarray, float]:
    img = image.copy()
    scale = 1.0

    h, w = img.shape[:2]
    max_side = max(h, w)
    if max_side_len > 0 and max_side > max_side_len:
        scale = max_side_len / max_side
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    if preprocess:
        if len(img.shape) == 3:
            if img.shape[2] == 4:
                gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
            else:
                # capture() 回傳 RGB，這裡要用 RGB2GRAY 才能保留正確亮度權重。
                gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            gray = img
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        img = cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)

    return img, scale


def _rescale_box(box, scale: float):
    if scale == 1.0:
        return box
    arr = np.asarray(box, dtype=np.float32)
    arr /= scale
    return arr.astype(np.int32).tolist()


def _run_engine(img, use_cls):
    with _engine_lock:
        if _engine is None:
            init_engine()
        if OCR_BACKEND == "rapidocr":
            result = _engine(img, use_cls=use_cls)
            if result and len(result) == 2 and result[1]:
                det_ms = result[1][0] * 1000
                cls_ms = result[1][1] * 1000
                rec_ms = result[1][2] * 1000
                print(f"[OCR] {det_ms:.0f}ms(檢測) + {rec_ms:.0f}ms(辨識)")
            return result
        elif OCR_BACKEND == "easyocr":
            results = _engine.readtext(img)
            return [([r[0][0], r[0][1], r[0][2], r[0][3]], r[1], r[2]) for r in results]
        elif OCR_BACKEND == "cnocr":
            results = _engine.ocr(img)
            out = []
            for r in results:
                box = r["position"]
                text = r["text"]
                conf = r["score"]
                out.append(([box[0], box[1], box[2], box[3]], text, conf))
            return out


_OCR_TIMEOUT = 30


def recognize(
    image: np.ndarray,
    roi_offset: dict | None = None,
    preprocess: bool = True,
    max_side_len: int = _DEFAULT_MAX_SIDE_LEN,
    min_confidence: float = 0.5,
) -> list[OcrResult]:
    if image is None or image.size == 0:
        return []
    img, scale = _prepare_image(image, max_side_len, preprocess)
    ox, oy = (roi_offset["x"], roi_offset["y"]) if roi_offset else (0, 0)

    future = _ocr_executor.submit(_run_engine, img, False)
    try:
        result = future.result(timeout=_OCR_TIMEOUT)
    except FutureTimeout:
        print("[OCR] timeout (30s)")
        _incr_ocr_failure()
        return []
    except Exception as e:
        print(f"[OCR] exception: {e}")
        _incr_ocr_failure()
        return []

    if result is None:
        _incr_ocr_failure()
        return []
    # rapidocr 回傳 (boxes, elapse)；其他引擎直接回傳 list (box, text, score)
    rows = result[0] if OCR_BACKEND == "rapidocr" else result
    if rows is None:
        _incr_ocr_failure()
        return []
    _reset_ocr_failures()
    results: list[OcrResult] = []
    for box, text, score in rows:
        if score is None or score < min_confidence:
            continue
        rx, ry, rw, rh = _box_to_rect(_rescale_box(box, scale))
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
