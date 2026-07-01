import base64
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


def img_to_b64(img: np.ndarray) -> str:
    _, buf = cv2.imencode(".png", img)
    return base64.b64encode(buf).decode("ascii")


def b64_to_img(data: str) -> Optional[np.ndarray]:
    try:
        buf = base64.b64decode(data)
        arr = np.frombuffer(buf, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


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
    scale_range: Optional[tuple[float, float]] = (0.7, 1.3),
    scale_step: float = 0.05,
    template_data: Optional[str] = None,
    capture_size: Optional[list] = None,
    current_size: Optional[list] = None,
    match_color: bool = False,  # 預設灰階比對（只看形狀），打勾則保留顏色資訊比對
    color_tolerance: float = 0,  # 第二階段顏色驗證：每個像素平均色差容許值（0~255），0=關閉
) -> list[MatchResult]:
    if template_data:
        template_bgr = b64_to_img(template_data)
        tmpl_name = "inline"
        if template_bgr is None:
            return []
    else:
        resolved = _resolve_template(template_path)
        if resolved is None:
            return []
        template_bgr = cv2.imread(str(resolved), cv2.IMREAD_COLOR)
        if template_bgr is None:
            return []
        tmpl_name = Path(template_path).stem

    if not match_color:
        template = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
    else:
        template = template_bgr  # ponytail: 保留 BGR 三通道，顏色差異會影響 TM_CCOEFF_NORMED 信心度
    th, tw = template.shape[:2]

    if roi is not None and any(roi.get(k, 0) != 0 for k in ("w", "h")):
        h, w = img.shape[:2]
        x1 = max(0, roi["x"])
        y1 = max(0, roi["y"])
        x2 = min(w, roi["x"] + roi["w"])
        y2 = min(h, roi["y"] + roi["h"])
        if x2 > x1 and y2 > y1:
            search_bgr = img[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1
        else:
            search_bgr = img
            offset_x = offset_y = 0
    else:
        search_bgr = img
        offset_x = offset_y = 0

    if not match_color:
        search_img = cv2.cvtColor(search_bgr, cv2.COLOR_BGR2GRAY)
    else:
        search_img = search_bgr
    min_side = 8

    if capture_size is not None and len(capture_size) == 2 and capture_size[0] > 0:
        current_w = current_size[0] if current_size else search_bgr.shape[1]
        center = current_w / capture_size[0]
        center = max(0.5, min(2.0, center))
        scales = [round(center * s, 4) for s in (0.9, 0.95, 1.0, 1.05, 1.1)]
        scales = [s for s in scales if 0.5 <= s <= 2.0]
    elif scale_range is None:
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
                    template_name=tmpl_name,
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

    # ponytail: 第二階段 — 顏色差異驗證（只對 match_color 啟用時生效）
    if match_color and color_tolerance > 0 and kept:
        filtered = []
        for m in kept:
            x1 = max(0, m.x - offset_x)
            y1 = max(0, m.y - offset_y)
            x2 = min(search_bgr.shape[1], x1 + m.w)
            y2 = min(search_bgr.shape[0], y1 + m.h)
            if x2 <= x1 or y2 <= y1:
                continue
            crop = search_bgr[y1:y2, x1:x2]
            if crop.shape[:2] != template_bgr.shape[:2]:
                crop = cv2.resize(
                    crop,
                    (template_bgr.shape[1], template_bgr.shape[0]),
                )
            diff = cv2.absdiff(crop, template_bgr)
            dist = float(np.mean(diff))
            if dist <= color_tolerance:
                filtered.append(m)
        kept = filtered

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
    print("  [OK] default scale_range=(0.7,1.3) step=0.05 finds match")

    # ── Cross-resolution via capture_size ──
    high_res_img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.rectangle(high_res_img, (40, 40), (80, 80), (100, 150, 200), -1)
    cv2.rectangle(high_res_img, (50, 50), (70, 70), (30, 40, 50), -1)
    cropped = high_res_img[40:81, 40:81].copy()
    # simulate lower resolution (80%)
    low_res_img = cv2.resize(high_res_img, (160, 160), interpolation=cv2.INTER_AREA)
    # encode template as base64 (like real tasks)
    _, buf = cv2.imencode(".png", cropped)
    tpl_b64 = base64.b64encode(buf).decode("ascii")

    # matching at same res with exact capture_size
    same = match_template(
        high_res_img,
        "",
        threshold=0.5,
        template_data=tpl_b64,
        capture_size=[200, 200],
        current_size=[200, 200],
    )
    assert len(same) >= 1, "same res with capture_size should match"
    print(f"  [OK] capture_size same-res match ({len(same)} found)")

    # matching at 80% res with capture_size → should trigger ±range scaling
    cross = match_template(
        low_res_img,
        "",
        threshold=0.5,
        template_data=tpl_b64,
        capture_size=[200, 200],
        current_size=[160, 160],
    )
    assert len(cross) >= 1, f"cross-res (200→160) should match via scale range, got {len(cross)}"
    print(f"  [OK] capture_size cross-res 200→160 match ({len(cross)} found)")

    # capture_size without current_size → use search_bgr.shape
    no_current = match_template(
        low_res_img,
        "",
        threshold=0.5,
        template_data=tpl_b64,
        capture_size=[200, 200],
        current_size=None,
    )
    assert len(no_current) >= 1, "should fallback to search_bgr width"
    print(f"  [OK] capture_size without current_size fallback ({len(no_current)} found)")

    # ── color_tolerance second-stage filter ──
    color_img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(color_img, (10, 10), (30, 30), (180, 200, 220), -1)
    cv2.rectangle(color_img, (15, 15), (25, 25), (50, 60, 70), -1)
    color_tpl = color_img[10:31, 10:31].copy()
    tmp3 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp3.close()
    cv2.imwrite(tmp3.name, color_tpl)
    tmp3_path = Path(tmp3.name)

    # same color → should match
    same_color = match_template(
        color_img,
        tmp3_path,
        threshold=0.5,
        match_color=True,
        color_tolerance=30,
    )
    assert len(same_color) >= 1, "same-color should pass color_tolerance"
    print(f"  [OK] color_tolerance: same-color passes ({len(same_color)} match)")

    # different color (blue template vs red square at same position, same shape) → should reject
    diff_color_img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(diff_color_img, (10, 10), (30, 30), (0, 100, 200), -1)  # same location, same shape, red-orange
    cv2.rectangle(diff_color_img, (15, 15), (25, 25), (0, 20, 150), -1)
    diff_color = match_template(
        diff_color_img,
        tmp3_path,
        threshold=0.5,
        match_color=True,
        color_tolerance=30,
    )
    assert len(diff_color) == 0, "blue-vs-red should be rejected by color_tolerance"
    print(f"  [OK] color_tolerance: blue-vs-red rejected (got {len(diff_color)})")

    # match_color=False → color_tolerance ignored → shape-only match works
    gray_match = match_template(
        diff_color_img,
        tmp3_path,
        threshold=0.5,
        match_color=False,
        color_tolerance=30,
    )
    assert len(gray_match) >= 1, "match_color=False should ignore color_tolerance"
    print(f"  [OK] color_tolerance: match_color=False ignores filter ({len(gray_match)} match)")

    tmp3_path.unlink(missing_ok=True)

    Path(tmp2_path).unlink(missing_ok=True)

    print("\n=== All 14 tests passed ===")
