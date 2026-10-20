import numpy as np
from conftest import make_main_loop

from _loader import load_sibling
from core.rule_migration import _normalize_step_params
from core.rule_models import Rule

_number_sum = load_sibling("number_sum", "core/21_number_sum.py")
_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_ml = load_sibling("main_loop", "core/05_main_loop.py")


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


def _ctx(rect=None, img=None):
    rect = rect or {"x": 100, "y": 200, "w": 800, "h": 600}
    if img is None:
        img = np.zeros((600, 800, 3), dtype=np.uint8)
    return _ml.StepContext(img=img, rect=rect)


def _ctx_for(value: int, rect=None):
    img = np.zeros((600, 800, 3), dtype=np.uint8)
    img[20:70, 10:110] = value
    return _ctx(rect=rect, img=img)


def test_handle_sum_emits_callback(monkeypatch):
    ml = make_main_loop()
    results = [
        _ocr.OcrResult(text="+26", x=10, y=10, w=20, h=10, confidence=0.9),
        _ocr.OcrResult(text="+9", x=10, y=30, w=20, h=10, confidence=0.9),
    ]
    ml._ocr_region = lambda img, roi: results
    calls = []
    ml.on_sum = lambda *args: calls.append(args)
    rule = Rule(id="r", name="加總", enabled=True, steps=[])
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    ctx = _ctx_for(35)

    res = ml._handle_sum({"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}, ctx, rule)
    assert calls == [], "first sighting must wait for confirmation"

    now[0] += 0.4
    res = ml._handle_sum({"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}, ctx, rule)

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


def test_handle_sum_ignores_transient_totals(monkeypatch):
    ml = make_main_loop()
    current = [
        _ocr.OcrResult(text="+20", x=0, y=0, w=10, h=10, confidence=0.9),
        _ocr.OcrResult(text="+15", x=0, y=20, w=10, h=10, confidence=0.9),
    ]
    ml._ocr_region = lambda img, roi: current
    calls, hides = [], []
    ml.on_sum = lambda *args: calls.append(args)
    ml.on_sum_hide = lambda: hides.append(True)
    rule = Rule(id="r", name="加總", enabled=True, steps=[])
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    params = {"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}

    ml._handle_sum(params, _ctx_for(35), rule)  # 中途值 35，先不顯示
    now[0] += 0.2
    current = [_ocr.OcrResult(text="+43", x=0, y=0, w=10, h=10, confidence=0.9)]
    ml._handle_sum(params, _ctx_for(43), rule)  # 值變動：舊值淡出，等新值穩定
    assert calls == []
    assert hides == []

    now[0] += 0.2
    ml._handle_sum(params, _ctx_for(43), rule)
    assert calls == [], "0.2s is shorter than the confirmation window"

    now[0] += 0.2
    ml._handle_sum(params, _ctx_for(43), rule)
    assert calls == [(110, 220, 100, 50, 43, 1)]


def test_handle_sum_hides_old_overlay_when_value_changes(monkeypatch):
    ml = make_main_loop()
    current = [_ocr.OcrResult(text="+43", x=0, y=0, w=10, h=10, confidence=0.9)]
    ml._ocr_region = lambda img, roi: current
    calls, hides = [], []
    ml.on_sum = lambda *args: calls.append(args)
    ml.on_sum_hide = lambda: hides.append(True)
    rule = Rule(id="r", name="加總", enabled=True, steps=[])
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    params = {"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}

    ml._handle_sum(params, _ctx_for(43), rule)
    now[0] += 0.4
    ml._handle_sum(params, _ctx_for(43), rule)
    assert calls == [(110, 220, 100, 50, 43, 1)]

    current = [_ocr.OcrResult(text="+10", x=0, y=0, w=10, h=10, confidence=0.9)]
    ml._handle_sum(params, _ctx_for(10), rule)
    assert hides == [True], "changing value must fade the old total immediately"
    assert len(calls) == 1, "new total must wait for confirmation"


def test_handle_sum_no_numbers_hides_overlay(monkeypatch):
    ml = make_main_loop()
    current = [_ocr.OcrResult(text="+43", x=0, y=0, w=10, h=10, confidence=0.9)]
    ml._ocr_region = lambda img, roi: current
    hides = []
    ml.on_sum = lambda *args: None
    ml.on_sum_hide = lambda: hides.append(True)
    rule = Rule(id="r", name="加總", enabled=True, steps=[])
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    params = {"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}

    ml._handle_sum(params, _ctx_for(43), rule)
    now[0] += 0.4
    ml._handle_sum(params, _ctx_for(43), rule)
    assert ml._sum_active_rule == "r"
    assert "r" in ml._sum_visual

    current = [_ocr.OcrResult(text="RANK", x=0, y=0, w=10, h=10, confidence=0.9)]
    ml._handle_sum(params, _ctx_for(0), rule)
    assert hides == [True]
    assert ml._sum_active_rule is None
    assert "r" not in ml._sum_candidate
    assert "r" in ml._sum_visual, "短暫讀不到數字不該丟掉已確認的組合快取"


def test_sum_visual_cache_reuses_same_group(monkeypatch):
    ml = make_main_loop()
    ocr_calls = []
    results = [_ocr.OcrResult(text="+43", x=0, y=0, w=10, h=10, confidence=0.9)]

    def _fake_ocr(img, roi):
        ocr_calls.append(1)
        return results

    ml._ocr_region = _fake_ocr
    calls = []
    ml.on_sum = lambda *args: calls.append(args)
    rule = Rule(id="r", name="加總", enabled=True, steps=[])
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    params = {"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}
    ctx = _ctx_for(200)

    ml._handle_sum(params, ctx, rule)
    now[0] += 0.4
    ml._handle_sum(params, ctx, rule)
    assert len(ocr_calls) == 2
    assert calls == [(110, 220, 100, 50, 43, 1)]
    assert "r" in ml._sum_visual

    ml._handle_sum(params, ctx, rule)
    assert len(ocr_calls) == 2, "same fingerprint must skip OCR"
    assert len(calls) == 2, "cached group should display immediately"

    noisy = _ctx_for(200)
    noisy.img = noisy.img + 1  # 整體 +1：容忍雜訊，仍應命中
    ml._handle_sum(params, noisy, rule)
    assert len(ocr_calls) == 2

    changed = _ctx_for(200)
    changed.img[25:45, 25:45] = 0  # 局部變化：視為不同組，必須重新 OCR
    ml._handle_sum(params, changed, rule)
    assert len(ocr_calls) == 3


def test_sum_visual_cache_cleared_on_precondition_failure(monkeypatch):
    ml = make_main_loop()
    ml._ocr_region = lambda img, roi: [
        _ocr.OcrResult(text="+43", x=0, y=0, w=10, h=10, confidence=0.9)
    ]
    ml.on_sum = lambda *args: None
    rule = Rule(id="r", name="加總", enabled=True, steps=[])
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    params = {"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}
    ctx = _ctx_for(200)

    ml._handle_sum(params, ctx, rule)
    now[0] += 0.4
    ml._handle_sum(params, ctx, rule)
    assert "r" in ml._sum_visual

    ml._clear_sum("r", drop_cache=True)
    assert "r" not in ml._sum_visual
    assert ml._sum_active_rule is None


def test_sum_visual_cache_revalidates_periodically(monkeypatch):
    ml = make_main_loop()
    ocr_calls = []
    ml._ocr_region = lambda img, roi: (
        ocr_calls.append(1) or [_ocr.OcrResult(text="+43", x=0, y=0, w=10, h=10, confidence=0.9)]
    )
    ml.on_sum = lambda *args: None
    rule = Rule(id="r", name="加總", enabled=True, steps=[])
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(_ml, "_SUM_FP_REVALIDATE_HITS", 2)
    params = {"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}
    ctx = _ctx_for(200)

    ml._handle_sum(params, ctx, rule)
    now[0] += 0.4
    ml._handle_sum(params, ctx, rule)
    assert len(ocr_calls) == 2

    ml._handle_sum(params, ctx, rule)  # hit #1
    assert len(ocr_calls) == 2
    ml._handle_sum(params, ctx, rule)  # hit #2 → 強制 OCR
    assert len(ocr_calls) == 3


def test_sum_frame_start_hides_rule_not_evaluated():
    ml = make_main_loop()
    hides = []
    ml.on_sum_hide = lambda: hides.append(True)
    ml._sum_active_rule = "r"
    ml._sum_candidate = {"r": (43, 1, 100.0)}
    ml._sum_seen = set()

    ml._sum_frame_start()

    assert hides == [True]
    assert ml._sum_active_rule is None
    assert "r" not in ml._sum_candidate
    assert ml._sum_seen == set()
