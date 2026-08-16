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
