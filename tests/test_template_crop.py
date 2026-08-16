"""crop_template_b64（模板修剪純邏輯）單元測試。"""

import sys
from pathlib import Path

import cv2
import numpy as np

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

_tm = load_sibling("template_matching", "core/11_template_matching.py")
crop_template_b64 = _tm.crop_template_b64
MIN_TEMPLATE_SIDE = _tm.MIN_TEMPLATE_SIDE
img_to_b64 = _tm.img_to_b64
b64_to_img = _tm.b64_to_img


def _make_image(w: int = 48, h: int = 48) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (200, 210, 220), -1)
    cv2.rectangle(img, (w // 4, h // 4), (w - w // 4 - 1, h - h // 4 - 1), (50, 60, 70), -1)
    return img


def test_crop_center_subregion():
    img = _make_image(48, 48)
    b64 = img_to_b64(img)
    out = crop_template_b64(b64, 10, 10, 20, 20)
    assert out is not None
    cropped = b64_to_img(out)
    assert cropped is not None
    assert cropped.shape == (20, 20, 3)
    assert np.array_equal(cropped, img[10:30, 10:30])


def test_crop_full_image_roundtrip():
    img = _make_image(48, 48)
    b64 = img_to_b64(img)
    out = crop_template_b64(b64, 0, 0, 48, 48)
    assert out is not None
    assert np.array_equal(b64_to_img(out), img)


def test_crop_clamps_out_of_bounds():
    img = _make_image(48, 48)
    b64 = img_to_b64(img)
    out = crop_template_b64(b64, -5, -5, 100, 100)
    assert out is not None
    assert b64_to_img(out).shape == (48, 48, 3)
    out2 = crop_template_b64(b64, 40, 40, 20, 20)
    assert out2 is not None
    assert b64_to_img(out2).shape == (8, 8, 3)


def test_crop_too_small_returns_none():
    img = _make_image(48, 48)
    b64 = img_to_b64(img)
    assert crop_template_b64(b64, 0, 0, MIN_TEMPLATE_SIDE - 1, 10) is None
    assert crop_template_b64(b64, 0, 0, 10, MIN_TEMPLATE_SIDE - 1) is None


def test_crop_invalid_b64_returns_none():
    assert crop_template_b64("not-base64!!!", 0, 0, 10, 10) is None
    assert crop_template_b64("", 0, 0, 10, 10) is None


def test_crop_invalid_rect_returns_none():
    img = _make_image(48, 48)
    b64 = img_to_b64(img)
    assert crop_template_b64(b64, 0, 0, 0, 10) is None
    assert crop_template_b64(b64, 0, 0, -5, 10) is None


margins_from_rect = _tm.margins_from_rect
rect_from_margins = _tm.rect_from_margins
clamp_margins = _tm.clamp_margins


def test_margins_roundtrip():
    assert margins_from_rect(5, 7, 10, 10, 30, 20) == (5, 7, 15, 3)
    assert rect_from_margins((5, 7, 15, 3), 30, 20) == (5, 7, 10, 10)
    assert margins_from_rect(0, 0, 30, 20, 30, 20) == (0, 0, 0, 0)


def test_clamp_margins_zeros_and_negative():
    assert clamp_margins((0, 0, 0, 0), 48, 48, 4) == (0, 0, 0, 0)
    assert clamp_margins((-3, -2, -1, 0), 48, 48, 4) == (0, 0, 0, 0)


def test_clamp_margins_cross_constraint():
    # left 過大時，right 的剩餘空間被壓縮
    assert clamp_margins((30, 0, 30, 0), 48, 48, 4) == (14, 0, 30, 0)
    assert clamp_margins((40, 0, 40, 0), 48, 48, 4) == (4, 0, 40, 0)
    # 對邊和 ≤ 尺寸 − min
    for cand in ((10, 10, 10, 10), (0, 0, 0, 0), (40, 40, 40, 40)):
        left_m, top_m, right_m, bottom_m = clamp_margins(cand, 48, 48, 4)
        assert 0 <= left_m <= 48 and 0 <= right_m <= 48 and left_m + right_m <= 44
        assert 0 <= top_m <= 48 and 0 <= bottom_m <= 48 and top_m + bottom_m <= 44


def test_clamp_margins_idempotent():
    m1 = clamp_margins((25, 30, 28, 26), 48, 48, 4)
    assert clamp_margins(m1, 48, 48, 4) == m1


def test_clamp_margins_tiny_image():
    # 圖本身小於 min_side：收斂到全 0 不崩潰
    assert clamp_margins((3, 3, 3, 3), 3, 3, 4) == (0, 0, 0, 0)
