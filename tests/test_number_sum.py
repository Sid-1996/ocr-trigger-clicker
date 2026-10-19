import numpy as np
from conftest import make_main_loop

from _loader import load_sibling
from core.rule_migration import _normalize_step_params
from core.rule_models import Rule

_number_sum = load_sibling("number_sum", "core/21_number_sum.py")
_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")


def test_parse_numbers():
    parse = _number_sum.parse_numbers
    assert parse("+26 +9 +20") == [26, 9, 20]
    assert parse("1,234") == [1234]
    assert parse("1,234,567") == [1234567]
    assert parse("2G") == []
    assert parse("26%") == []
    assert parse("1.2K") == []
    assert parse("2,26") == []
    assert parse("＋２６") == [26]
    assert parse("共 26 個") == [26]


def test_sum_numbers():
    assert _number_sum.sum_numbers("+26 +9 +20") == (55, 3)
    assert _number_sum.sum_numbers("no numbers") == (0, 0)


def test_sum_step_normalized():
    params = _normalize_step_params(
        "sum", {"roi": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "roi_coord": "client"}}
    )
    assert params["roi"] == {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "roi_coord": "client"}


def _ctx(rect=None):
    from _loader import load_sibling as _load

    mod = _load("main_loop", "core/05_main_loop.py")
    rect = rect or {"x": 100, "y": 200, "w": 800, "h": 600}
    return mod.StepContext(img=np.zeros((600, 800, 3), dtype=np.uint8), rect=rect)


def test_handle_sum_emits_callback():
    ml = make_main_loop()
    results = [
        _ocr.OcrResult(text="+26", x=10, y=10, w=20, h=10, confidence=0.9),
        _ocr.OcrResult(text="+9", x=10, y=30, w=20, h=10, confidence=0.9),
    ]
    ml._ocr_region = lambda img, roi: results
    calls = []
    ml.on_sum = lambda *args: calls.append(args)
    rule = Rule(id="r", name="加總", enabled=True, steps=[])

    res = ml._handle_sum({"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}, _ctx(), rule)

    assert res.action == "continue"
    assert calls == [(110, 220, 100, 50, 35, 2)]


def test_handle_sum_no_numbers_no_callback():
    ml = make_main_loop()
    ml._ocr_region = lambda img, roi: [
        _ocr.OcrResult(text="RANK", x=0, y=0, w=10, h=10, confidence=0.9)
    ]
    calls = []
    ml.on_sum = lambda *args: calls.append(args)
    rule = Rule(id="r", name="加總", enabled=True, steps=[])

    res = ml._handle_sum({"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}, _ctx(), rule)

    assert res.action == "continue"
    assert calls == []


def test_handle_sum_empty_roi_skips_ocr():
    ml = make_main_loop()

    def _boom(img, roi):
        raise AssertionError("empty ROI must not run OCR")

    ml._ocr_region = _boom
    rule = Rule(id="r", name="加總", enabled=True, steps=[])

    res = ml._handle_sum({"roi": {"x": 0, "y": 0, "w": 0, "h": 0}}, _ctx(), rule)

    assert res.action == "continue"
    assert ml._sum_warn_counter["r"] == 1
