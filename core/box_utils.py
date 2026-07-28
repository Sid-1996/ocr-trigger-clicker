import logging
from typing import Optional

import numpy as np

_log = logging.getLogger(__name__)


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def roi_center(roi: dict) -> tuple[int, int]:
    x = roi.get("x", 0)
    y = roi.get("y", 0)
    w = roi.get("w", 0)
    h = roi.get("h", 0)
    return int(x + w / 2), int(y + h / 2)


def roi_to_pixels(roi: dict, frame_w: int, frame_h: int) -> dict:
    x = roi.get("x", 0)
    y = roi.get("y", 0)
    w = roi.get("w", 0)
    h = roi.get("h", 0)
    if x <= 1.0 and y <= 1.0 and w <= 1.0 and h <= 1.0:
        return {
            "x": int(round(x * frame_w)),
            "y": int(round(y * frame_h)),
            "w": int(round(w * frame_w)),
            "h": int(round(h * frame_h)),
        }
    return roi


def roi_to_ratio(roi: dict, frame_w: int, frame_h: int) -> dict:
    x = roi.get("x", 0)
    y = roi.get("y", 0)
    w = roi.get("w", 0)
    h = roi.get("h", 0)
    if frame_w > 0 and frame_h > 0 and (x > 1.0 or y > 1.0 or w > 1.0 or h > 1.0):
        return {
            "x": round(x / frame_w, 6),
            "y": round(y / frame_h, 6),
            "w": round(w / frame_w, 6),
            "h": round(h / frame_h, 6),
        }
    return roi


def roi_crop(roi: dict, img: np.ndarray) -> Optional[np.ndarray]:
    h, w = img.shape[:2]
    x1 = max(0, int(roi.get("x", 0)))
    y1 = max(0, int(roi.get("y", 0)))
    x2 = min(w, x1 + int(roi.get("w", 0)))
    y2 = min(h, y1 + int(roi.get("h", 0)))
    if x2 <= x1 or y2 <= y1:
        return None
    return img[y1:y2, x1:x2]


def roi_scale(roi: dict, factor: float) -> dict:
    x = roi.get("x", 0)
    y = roi.get("y", 0)
    w = roi.get("w", 0)
    h = roi.get("h", 0)
    nw = max(1, int(w * factor))
    nh = max(1, int(h * factor))
    nx = int(x + (w - nw) / 2)
    ny = int(y + (h - nh) / 2)
    return {"x": nx, "y": ny, "w": nw, "h": nh}


def roi_intersection(a: dict, b: dict) -> Optional[dict]:
    ax1 = a.get("x", 0)
    ay1 = a.get("y", 0)
    ax2 = ax1 + a.get("w", 0)
    ay2 = ay1 + a.get("h", 0)
    bx1 = b.get("x", 0)
    by1 = b.get("y", 0)
    bx2 = bx1 + b.get("w", 0)
    by2 = by1 + b.get("h", 0)
    x1 = max(ax1, bx1)
    y1 = max(ay1, by1)
    x2 = min(ax2, bx2)
    y2 = min(ay2, by2)
    if x2 <= x1 or y2 <= y1:
        return None
    return {"x": int(x1), "y": int(y1), "w": int(x2 - x1), "h": int(y2 - y1)}


def roi_bounding(boxes: list[dict]) -> Optional[dict]:
    if not boxes:
        return None
    xs = [b.get("x", 0) for b in boxes]
    ys = [b.get("y", 0) for b in boxes]
    xe = [b.get("x", 0) + b.get("w", 0) for b in boxes]
    ye = [b.get("y", 0) + b.get("h", 0) for b in boxes]
    x1 = min(xs)
    y1 = min(ys)
    x2 = max(xe)
    y2 = max(ye)
    return {"x": int(x1), "y": int(y1), "w": int(x2 - x1), "h": int(y2 - y1)}


def roi_sanitize(roi: Optional[dict]) -> dict:
    roi = roi if isinstance(roi, dict) else {}
    result = {
        "x": max(0.0, _as_float(roi.get("x", 0))),
        "y": max(0.0, _as_float(roi.get("y", 0))),
        "w": max(0.0, _as_float(roi.get("w", 0))),
        "h": max(0.0, _as_float(roi.get("h", 0))),
    }
    if roi.get("roi_coord") == "client":
        result["roi_coord"] = "client"
    return result


def box_to_rect(box) -> dict:
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    x = min(xs)
    y = min(ys)
    w = max(xs) - x
    h = max(ys) - y
    return {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}


def point_to_pixels(px: float, py: float, frame_w: int, frame_h: int) -> tuple[int, int]:
    if px <= 1.0 and py <= 1.0:
        return int(round(px * frame_w)), int(round(py * frame_h))
    return int(px), int(py)


if __name__ == "__main__":
    print("=== Box Utils Self-Check ===\n")

    # roi_center
    cx, cy = roi_center({"x": 10, "y": 20, "w": 100, "h": 200})
    assert cx == 60 and cy == 120
    print("  [OK] roi_center")

    # roi_to_pixels
    r = roi_to_pixels({"x": 0.5, "y": 0.25, "w": 0.3, "h": 0.1}, 1920, 1080)
    assert r == {"x": 960, "y": 270, "w": 576, "h": 108}
    print("  [OK] roi_to_pixels ratio")
    r2 = roi_to_pixels({"x": 100, "y": 200, "w": 300, "h": 400}, 1920, 1080)
    assert r2 == {"x": 100, "y": 200, "w": 300, "h": 400}
    print("  [OK] roi_to_pixels absolute passthrough")

    # roi_to_ratio
    r = roi_to_ratio({"x": 960, "y": 270, "w": 576, "h": 108}, 1920, 1080)
    assert abs(r["x"] - 0.5) < 0.001 and abs(r["y"] - 0.25) < 0.001
    print("  [OK] roi_to_ratio")
    r2 = roi_to_ratio({"x": 0.5, "y": 0.25, "w": 0.3, "h": 0.1}, 1920, 1080)
    assert r2 == {"x": 0.5, "y": 0.25, "w": 0.3, "h": 0.1}
    print("  [OK] roi_to_ratio ratio passthrough")

    # roi_crop
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    cropped = roi_crop({"x": 10, "y": 10, "w": 50, "h": 50}, img)
    assert cropped is not None and cropped.shape == (50, 50, 3)
    print("  [OK] roi_crop")
    assert roi_crop({"x": 0, "y": 0, "w": 0, "h": 0}, img) is None
    print("  [OK] roi_crop empty returns None")

    # roi_scale
    r = roi_scale({"x": 10, "y": 10, "w": 100, "h": 100}, 1.5)
    assert r == {"x": -15, "y": -15, "w": 150, "h": 150}
    print("  [OK] roi_scale")

    # roi_intersection
    r = roi_intersection(
        {"x": 0, "y": 0, "w": 100, "h": 100}, {"x": 50, "y": 50, "w": 100, "h": 100}
    )
    assert r == {"x": 50, "y": 50, "w": 50, "h": 50}
    print("  [OK] roi_intersection")
    assert (
        roi_intersection({"x": 0, "y": 0, "w": 10, "h": 10}, {"x": 100, "y": 100, "w": 10, "h": 10})
        is None
    )
    print("  [OK] roi_intersection no overlap")

    # roi_bounding
    r = roi_bounding([{"x": 10, "y": 10, "w": 50, "h": 50}, {"x": 100, "y": 200, "w": 30, "h": 40}])
    assert r == {"x": 10, "y": 10, "w": 120, "h": 230}
    print("  [OK] roi_bounding")
    assert roi_bounding([]) is None
    print("  [OK] roi_bounding empty")

    # roi_sanitize
    r = roi_sanitize({"x": -1, "y": 0.5, "w": "abc", "h": 100})
    assert r["x"] == 0.0 and r["y"] == 0.5 and r["w"] == 0.0 and r["h"] == 100.0
    assert "roi_coord" not in r
    print("  [OK] roi_sanitize defaults")
    r2 = roi_sanitize({"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.3, "roi_coord": "client"})
    assert r2["roi_coord"] == "client"
    print("  [OK] roi_sanitize roi_coord passthrough")
    r3 = roi_sanitize(None)
    assert r3 == {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
    print("  [OK] roi_sanitize None input")

    # box_to_rect
    box = [[10, 20], [50, 20], [50, 80], [10, 80]]
    r = box_to_rect(box)
    assert r == {"x": 10, "y": 20, "w": 40, "h": 60}
    print("  [OK] box_to_rect")

    # point_to_pixels
    px, py = point_to_pixels(0.5, 0.25, 1920, 1080)
    assert px == 960 and py == 270
    print("  [OK] point_to_pixels ratio")
    px2, py2 = point_to_pixels(100, 200, 1920, 1080)
    assert px2 == 100 and py2 == 200
    print("  [OK] point_to_pixels absolute passthrough")

    print("\n=== All 17 tests passed ===")
