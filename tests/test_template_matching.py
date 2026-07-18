import base64
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

_tm = load_sibling("template_matching", "core/11_template_matching.py")
MatchResult = _tm.MatchResult
match_template = _tm.match_template
nms_suppress = _tm.nms_suppress
img_to_b64 = _tm.img_to_b64


def _make_pattern_image():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 10), (30, 30), (180, 200, 220), -1)
    cv2.rectangle(img, (15, 15), (25, 25), (50, 60, 70), -1)
    return img


def test_match_basic():
    img = _make_pattern_image()
    template = img[10:31, 10:31].copy()
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    cv2.imwrite(tmp.name, template)
    tmp_path = Path(tmp.name)

    results = match_template(img, tmp_path, threshold=0.5)
    assert len(results) >= 1
    assert results[0].x == 10
    assert results[0].y == 10
    assert results[0].w == 21
    assert results[0].h == 21
    assert results[0].center_x == 10 + 21 // 2
    assert results[0].center_y == 10 + 21 // 2
    assert results[0].confidence >= 0.5
    assert results[0].text == Path(tmp_path).stem
    tmp_path.unlink(missing_ok=True)


def test_no_match():
    img = _make_pattern_image()
    template = img[10:31, 10:31].copy()
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    cv2.imwrite(tmp.name, template)
    tmp_path = Path(tmp.name)

    blank = np.zeros((100, 100, 3), dtype=np.uint8)
    no_match = match_template(blank, tmp_path, threshold=0.9)
    assert len(no_match) == 0
    tmp_path.unlink(missing_ok=True)


def test_missing_template():
    img = _make_pattern_image()
    missing = match_template(img, "nonexistent.png", threshold=0.5)
    assert len(missing) == 0


def test_nms():
    matches = [
        MatchResult(x=10, y=10, w=20, h=20, confidence=0.9),
        MatchResult(x=12, y=12, w=20, h=20, confidence=0.8),
        MatchResult(x=100, y=100, w=20, h=20, confidence=0.7),
    ]
    suppressed = nms_suppress(matches, iou_threshold=0.3)
    assert len(suppressed) == 2
    assert suppressed[0].confidence == 0.9
    assert suppressed[1].confidence == 0.7


def test_match_result_compatibility():
    mr = MatchResult(x=5, y=5, w=10, h=10, confidence=0.95, template_name="btn_ok")
    assert mr.center_x == 10
    assert mr.center_y == 10
    assert mr.text == "btn_ok"


def test_multi_scale_single():
    big_img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.rectangle(big_img, (20, 20), (68, 68), (120, 140, 160), -1)
    cv2.rectangle(big_img, (30, 30), (58, 58), (50, 60, 70), -1)
    cv2.rectangle(big_img, (80, 80), (176, 176), (120, 140, 160), -1)
    cv2.rectangle(big_img, (100, 100), (156, 156), (50, 60, 70), -1)
    tiny_tpl = big_img[20:68, 20:68].copy()
    tmp2 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp2.close()
    cv2.imwrite(tmp2.name, tiny_tpl)
    tmp2_path = Path(tmp2.name)

    single = match_template(big_img, tmp2_path, threshold=0.5, scale_range=None)
    assert len(single) >= 1
    assert single[0].w == 48 and single[0].h == 48
    tmp2_path.unlink(missing_ok=True)


def test_multi_scale_both_sizes():
    big_img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.rectangle(big_img, (20, 20), (68, 68), (120, 140, 160), -1)
    cv2.rectangle(big_img, (30, 30), (58, 58), (50, 60, 70), -1)
    cv2.rectangle(big_img, (80, 80), (176, 176), (120, 140, 160), -1)
    cv2.rectangle(big_img, (100, 100), (156, 156), (50, 60, 70), -1)
    tiny_tpl = big_img[20:68, 20:68].copy()
    tmp2 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp2.close()
    cv2.imwrite(tmp2.name, tiny_tpl)
    tmp2_path = Path(tmp2.name)

    multi = match_template(
        big_img, tmp2_path, threshold=0.5, scale_range=(0.5, 2.0), scale_step=0.1
    )
    assert len(multi) >= 2
    sizes = {(m.w, m.h) for m in multi}
    assert (48, 48) in sizes
    has_larger = any(w >= 80 and h >= 80 for w, h in sizes)
    assert has_larger
    tmp2_path.unlink(missing_ok=True)


def test_default_scale_range():
    big_img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.rectangle(big_img, (20, 20), (68, 68), (120, 140, 160), -1)
    cv2.rectangle(big_img, (30, 30), (58, 58), (50, 60, 70), -1)
    cv2.rectangle(big_img, (80, 80), (176, 176), (120, 140, 160), -1)
    cv2.rectangle(big_img, (100, 100), (156, 156), (50, 60, 70), -1)
    tiny_tpl = big_img[20:68, 20:68].copy()
    tmp2 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp2.close()
    cv2.imwrite(tmp2.name, tiny_tpl)
    tmp2_path = Path(tmp2.name)

    default = match_template(big_img, tmp2_path, threshold=0.5)
    assert len(default) >= 1
    tmp2_path.unlink(missing_ok=True)


def test_capture_size_same_res():
    high_res_img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.rectangle(high_res_img, (40, 40), (80, 80), (100, 150, 200), -1)
    cv2.rectangle(high_res_img, (50, 50), (70, 70), (30, 40, 50), -1)
    cropped = high_res_img[40:81, 40:81].copy()
    _, buf = cv2.imencode(".png", cropped)
    tpl_b64 = base64.b64encode(buf).decode("ascii")

    same = match_template(
        high_res_img,
        "",
        threshold=0.5,
        template_data=tpl_b64,
        capture_size=[200, 200],
        current_size=[200, 200],
    )
    assert len(same) >= 1


def test_capture_size_cross_res():
    high_res_img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.rectangle(high_res_img, (40, 40), (80, 80), (100, 150, 200), -1)
    cv2.rectangle(high_res_img, (50, 50), (70, 70), (30, 40, 50), -1)
    cropped = high_res_img[40:81, 40:81].copy()
    low_res_img = cv2.resize(high_res_img, (160, 160), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode(".png", cropped)
    tpl_b64 = base64.b64encode(buf).decode("ascii")

    cross = match_template(
        low_res_img,
        "",
        threshold=0.5,
        template_data=tpl_b64,
        capture_size=[200, 200],
        current_size=[160, 160],
    )
    assert len(cross) >= 1


def test_capture_size_no_current():
    high_res_img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.rectangle(high_res_img, (40, 40), (80, 80), (100, 150, 200), -1)
    cv2.rectangle(high_res_img, (50, 50), (70, 70), (30, 40, 50), -1)
    cropped = high_res_img[40:81, 40:81].copy()
    low_res_img = cv2.resize(high_res_img, (160, 160), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode(".png", cropped)
    tpl_b64 = base64.b64encode(buf).decode("ascii")

    no_current = match_template(
        low_res_img,
        "",
        threshold=0.5,
        template_data=tpl_b64,
        capture_size=[200, 200],
        current_size=None,
    )
    assert len(no_current) >= 1


def test_color_tolerance_same():
    color_img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(color_img, (10, 10), (30, 30), (180, 200, 220), -1)
    cv2.rectangle(color_img, (15, 15), (25, 25), (50, 60, 70), -1)
    color_tpl = color_img[10:31, 10:31].copy()
    tmp3 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp3.close()
    cv2.imwrite(tmp3.name, color_tpl)
    tmp3_path = Path(tmp3.name)

    same_color = match_template(
        color_img, tmp3_path, threshold=0.5, match_color=True, color_tolerance=100
    )
    assert len(same_color) >= 1
    tmp3_path.unlink(missing_ok=True)


def test_color_tolerance_different():
    color_img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(color_img, (10, 10), (30, 30), (180, 200, 220), -1)
    cv2.rectangle(color_img, (15, 15), (25, 25), (50, 60, 70), -1)
    color_tpl = color_img[10:31, 10:31].copy()
    tmp3 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp3.close()
    cv2.imwrite(tmp3.name, color_tpl)
    tmp3_path = Path(tmp3.name)

    diff_color_img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(diff_color_img, (10, 10), (30, 30), (0, 0, 255), -1)
    cv2.rectangle(diff_color_img, (15, 15), (25, 25), (0, 0, 200), -1)
    diff_color = match_template(
        diff_color_img, tmp3_path, threshold=0.5, match_color=True, color_tolerance=100
    )
    assert len(diff_color) == 0

    gray_match = match_template(
        diff_color_img, tmp3_path, threshold=0.5, match_color=False, color_tolerance=100
    )
    assert len(gray_match) >= 1
    tmp3_path.unlink(missing_ok=True)
