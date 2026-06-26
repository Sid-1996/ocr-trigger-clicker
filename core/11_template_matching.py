import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


@dataclass
class MatchResult:
    x: int
    y: int
    w: int
    h: int
    confidence: float
    template_name: str = ""
    center_x: int = field(init=False)
    center_y: int = field(init=False)

    def __post_init__(self):
        self.center_x = self.x + self.w // 2
        self.center_y = self.y + self.h // 2

    @property
    def text(self) -> str:
        return self.template_name


def _resolve_template(template_path: str) -> Optional[Path]:
    p = Path(template_path)
    if p.is_absolute() and p.exists():
        return p
    project_root = Path(__file__).resolve().parent.parent
    candidate = project_root / "images" / p.name
    if candidate.exists():
        return candidate
    if hasattr(sys, "_MEIPASS"):
        try:
            from build import get_data_path

            candidate = Path(get_data_path("images")) / p.name
            if candidate.exists():
                return candidate
        except ImportError:
            pass
    return None


def match_template(
    img: np.ndarray,
    template_path: str,
    roi: Optional[dict] = None,
    threshold: float = 0.8,
    max_results: int = 5,
    scale_range: Optional[tuple[float, float]] = (0.8, 1.2),
    scale_step: float = 0.1,
) -> list[MatchResult]:
    resolved = _resolve_template(template_path)
    if resolved is None:
        return []

    template = cv2.imread(str(resolved), cv2.IMREAD_COLOR)
    if template is None:
        return []

    if roi is not None and any(roi.get(k, 0) != 0 for k in ("w", "h")):
        h, w = img.shape[:2]
        x1 = max(0, roi["x"])
        y1 = max(0, roi["y"])
        x2 = min(w, roi["x"] + roi["w"])
        y2 = min(h, roi["y"] + roi["h"])
        if x2 > x1 and y2 > y1:
            search_img = img[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1
        else:
            search_img = img
            offset_x = offset_y = 0
    else:
        search_img = img
        offset_x = offset_y = 0

    th, tw = template.shape[:2]
    min_side = 8

    if scale_range is None:
        scales = [1.0]
    else:
        num = int((scale_range[1] - scale_range[0]) / scale_step) + 1
        scales = [round(scale_range[0] + i * scale_step, 4) for i in range(num)]

    matches = []
    for scale in scales:
        sw = max(min_side, int(tw * scale))
        sh = max(min_side, int(th * scale))
        if sw > search_img.shape[1] or sh > search_img.shape[0]:
            continue
        if scale == 1.0:
            scaled = template
        else:
            interpolation = cv2.INTER_LINEAR if scale > 1.0 else cv2.INTER_AREA
            scaled = cv2.resize(template, (sw, sh), interpolation=interpolation)

        result_map = cv2.matchTemplate(search_img, scaled, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result_map >= threshold)
        for pt in zip(*locations[::-1]):
            matches.append(
                MatchResult(
                    x=int(pt[0]) + offset_x,
                    y=int(pt[1]) + offset_y,
                    w=sw,
                    h=sh,
                    confidence=float(result_map[pt[1], pt[0]]),
                    template_name=Path(template_path).stem,
                )
            )

    if not matches:
        return []

    # non-maximum suppression across all scales
    matches.sort(key=lambda m: m.confidence, reverse=True)
    kept = []
    for m in matches:
        overlap = False
        for k in kept:
            ix = max(m.x, k.x)
            iy = max(m.y, k.y)
            ix2 = min(m.x + m.w, k.x + k.w)
            iy2 = min(m.y + m.h, k.y + k.h)
            if ix < ix2 and iy < iy2:
                overlap_area = (ix2 - ix) * (iy2 - iy)
                min_area = min(m.w * m.h, k.w * k.h)
                if min_area > 0 and overlap_area / min_area > 0.5:
                    overlap = True
                    break
        if not overlap:
            kept.append(m)
        if len(kept) >= max_results:
            break

    return kept


def nms_suppress(matches: list[MatchResult], iou_threshold: float = 0.5) -> list[MatchResult]:
    if not matches:
        return []
    matches = sorted(matches, key=lambda m: m.confidence, reverse=True)
    kept = []
    for m in matches:
        overlap = False
        for k in kept:
            ix = max(m.x, k.x)
            iy = max(m.y, k.y)
            ix2 = min(m.x + m.w, k.x + k.w)
            iy2 = min(m.y + m.h, k.y + k.h)
            if ix < ix2 and iy < iy2:
                overlap_area = (ix2 - ix) * (iy2 - iy)
                union = m.w * m.h + k.w * k.h - overlap_area
                if union > 0 and overlap_area / union > iou_threshold:
                    overlap = True
                    break
        if not overlap:
            kept.append(m)
    return kept


if __name__ == "__main__":
    print("=== Template Matching Self-Check ===\n")

    # non-uniform pattern so TM_CCOEFF_NORMED has variance
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 10), (30, 30), (180, 200, 220), -1)
    cv2.rectangle(img, (15, 15), (25, 25), (50, 60, 70), -1)  # inner rect for variance
    template = img[10:31, 10:31].copy()

    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    cv2.imwrite(tmp.name, template)
    tmp_path = Path(tmp.name)

    results = match_template(img, tmp_path, threshold=0.5)
    assert len(results) >= 1, f"expected at least 1 match, got {len(results)}"
    assert results[0].x == 10
    assert results[0].y == 10
    assert results[0].w == 21
    assert results[0].h == 21
    assert results[0].center_x == 10 + 21 // 2
    assert results[0].center_y == 10 + 21 // 2
    assert results[0].confidence >= 0.5
    assert results[0].text == Path(tmp_path).stem
    print("  [OK] match_template basic match")

    # no match
    blank = np.zeros((100, 100, 3), dtype=np.uint8)
    no_match = match_template(blank, tmp_path, threshold=0.9)
    assert len(no_match) == 0
    print("  [OK] match_template no match (blank image)")

    # nonexistent template
    missing = match_template(img, "nonexistent.png", threshold=0.5)
    assert len(missing) == 0
    print("  [OK] match_template missing template returns empty")

    # NMS
    matches = [
        MatchResult(x=10, y=10, w=20, h=20, confidence=0.9),
        MatchResult(x=12, y=12, w=20, h=20, confidence=0.8),
        MatchResult(x=100, y=100, w=20, h=20, confidence=0.7),
    ]
    suppressed = nms_suppress(matches, iou_threshold=0.3)
    assert len(suppressed) == 2, f"NMS should keep 2, got {len(suppressed)}"
    assert suppressed[0].confidence == 0.9
    assert suppressed[1].confidence == 0.7
    print("  [OK] nms_suppress removes overlapping matches")

    # MatchResult quacks like OcrResult for center_x/center_y/text
    mr = MatchResult(x=5, y=5, w=10, h=10, confidence=0.95, template_name="btn_ok")
    assert mr.center_x == 10
    assert mr.center_y == 10
    assert mr.text == "btn_ok"
    print("  [OK] MatchResult center_x/center_y/text compatibility")

    # ── Multi-scale matching ──
    # create a 48x48 template (with inner variance), place at 20x20
    # then 2x larger (96x96) at 80x80 — same pattern, scaled
    big_img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.rectangle(big_img, (20, 20), (68, 68), (120, 140, 160), -1)
    cv2.rectangle(big_img, (30, 30), (58, 58), (50, 60, 70), -1)  # inner variance
    cv2.rectangle(big_img, (80, 80), (176, 176), (120, 140, 160), -1)  # 96x96
    cv2.rectangle(big_img, (100, 100), (156, 156), (50, 60, 70), -1)  # inner variance
    tiny_tpl = big_img[20:68, 20:68].copy()
    tmp2 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp2.close()
    cv2.imwrite(tmp2.name, tiny_tpl)
    tmp2_path = Path(tmp2.name)

    # single-scale should only find the exact-size match
    single = match_template(big_img, tmp2_path, threshold=0.5, scale_range=None)
    assert len(single) >= 1, "single-scale should find the 48x48 match"
    assert single[0].w == 48 and single[0].h == 48
    print(f"  [OK] single-scale finds 48x48 (confidence={single[0].confidence:.3f})")

    # multi-scale should find both sizes
    multi = match_template(
        big_img, tmp2_path, threshold=0.5, scale_range=(0.5, 2.0), scale_step=0.1
    )
    assert len(multi) >= 2, f"multi-scale should find both, got {len(multi)}"
    sizes = {(m.w, m.h) for m in multi}
    assert (48, 48) in sizes, "should include 48x48 match"
    has_larger = any(w >= 80 and h >= 80 for w, h in sizes)
    assert has_larger, f"should include larger match, sizes={sizes}"
    print(f"  [OK] multi-scale finds both sizes: {sizes}")

    # scale_range defaults work
    default = match_template(big_img, tmp2_path, threshold=0.5)
    assert len(default) >= 1
    print("  [OK] default scale_range=(0.8,1.2) finds match")

    Path(tmp2_path).unlink(missing_ok=True)

    print("\n=== All 8 tests passed ===")
