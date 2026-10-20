import numpy as np
import pytest
from conftest import make_main_loop

from _loader import load_sibling
from core.rule_migration import _normalize_step_params
from core.rule_models import Rule, Step

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


def _ctx(rect=None):
    rect = rect or {"x": 100, "y": 200, "w": 800, "h": 600}
    return _ml.StepContext(img=np.zeros((600, 800, 3), dtype=np.uint8), rect=rect)


class _ModeConfig:
    def __init__(self, mode):
        self.mode = mode

    def get_setting(self, win, key="interaction_mode"):
        return self.mode


class _ListLogger:
    def __init__(self):
        self.lines = []

    def info(self, msg, *args):
        self.lines.append(msg % args)


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

    res = ml._handle_sum({"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}, _ctx(), rule)
    assert calls == [], "first sighting must wait for confirmation"

    now[0] += 0.4
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

    ml._handle_sum(params, _ctx(), rule)  # 中途值 35，先不顯示
    now[0] += 0.2
    current = [_ocr.OcrResult(text="+43", x=0, y=0, w=10, h=10, confidence=0.9)]
    ml._handle_sum(params, _ctx(), rule)  # 值變動：舊值淡出，等新值穩定
    assert calls == []
    assert hides == []

    now[0] += 0.2
    ml._handle_sum(params, _ctx(), rule)
    assert calls == [], "0.2s is shorter than the confirmation window"

    now[0] += 0.2
    ml._handle_sum(params, _ctx(), rule)
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

    ml._handle_sum(params, _ctx(), rule)
    now[0] += 0.4
    ml._handle_sum(params, _ctx(), rule)
    assert calls == [(110, 220, 100, 50, 43, 1)]

    current = [_ocr.OcrResult(text="+10", x=0, y=0, w=10, h=10, confidence=0.9)]
    ml._handle_sum(params, _ctx(), rule)
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

    ml._handle_sum(params, _ctx(), rule)
    now[0] += 0.4
    ml._handle_sum(params, _ctx(), rule)
    assert ml._sum_active_rule == "r"

    current = [_ocr.OcrResult(text="RANK", x=0, y=0, w=10, h=10, confidence=0.9)]
    ml._handle_sum(params, _ctx(), rule)
    assert hides == [True]
    assert ml._sum_active_rule is None
    assert "r" not in ml._sum_candidate


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


@pytest.mark.parametrize("mode", ["frida", "hybrid"])
def test_handle_sum_non_foreground_logs_without_overlay(monkeypatch, mode):
    ml = make_main_loop()
    ml._rule_config_ctrl = _ModeConfig(mode)
    ml._logger = _ListLogger()
    ml._ocr_region = lambda img, roi: [
        _ocr.OcrResult(text="+26", x=0, y=0, w=20, h=10, confidence=0.9),
        _ocr.OcrResult(text="+9", x=0, y=20, w=20, h=10, confidence=0.9),
    ]
    calls = []
    ml.on_sum = lambda *args: calls.append(args)
    rule = Rule(id="r", name="加總", enabled=True, steps=[])
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    ctx = _ctx()
    params = {"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}

    ml._handle_sum(params, ctx, rule)
    now[0] += 0.4
    ml._handle_sum(params, ctx, rule)

    assert calls == []
    assert ctx.sum_stable is True
    assert ctx.sum_foreground is False
    assert ml._sum_active_rule is None
    assert len(ml._logger.lines) == 1
    line = ml._logger.lines[0]
    assert f"mode={mode}" in line
    assert "total=35" in line
    assert "+26" in line


def test_handle_sum_background_rule_never_shows_overlay(monkeypatch):
    ml = make_main_loop()
    ml._logger = _ListLogger()
    ml._ocr_region = lambda img, roi: [
        _ocr.OcrResult(text="+43", x=0, y=0, w=20, h=10, confidence=0.9)
    ]
    calls = []
    ml.on_sum = lambda *args: calls.append(args)
    rule = Rule(id="bg", name="背景加總", enabled=True, background=True, steps=[])
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    ctx = _ctx()
    params = {"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}

    ml._handle_sum(params, ctx, rule)
    now[0] += 0.4
    ml._handle_sum(params, ctx, rule)

    assert calls == []
    assert ctx.sum_stable is True
    assert ctx.sum_foreground is False
    assert len(ml._logger.lines) == 1
    assert "mode=pynput" in ml._logger.lines[0]


def test_sum_log_deduped_until_value_changes(monkeypatch):
    ml = make_main_loop()
    ml._rule_config_ctrl = _ModeConfig("frida")
    ml._logger = _ListLogger()
    current = [_ocr.OcrResult(text="+43", x=0, y=0, w=20, h=10, confidence=0.9)]
    ml._ocr_region = lambda img, roi: current
    ml.on_sum = lambda *args: None
    rule = Rule(id="r", name="加總", enabled=True, steps=[])
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    ctx = _ctx()
    params = {"roi": {"x": 10, "y": 20, "w": 100, "h": 50}}

    for _ in range(3):
        ml._handle_sum(params, ctx, rule)
        now[0] += 0.4

    assert len(ml._logger.lines) == 1

    current = [_ocr.OcrResult(text="+10", x=0, y=0, w=20, h=10, confidence=0.9)]
    ml._handle_sum(params, ctx, rule)
    now[0] += 0.4
    ml._handle_sum(params, ctx, rule)

    assert len(ml._logger.lines) == 2
    assert "total=10" in ml._logger.lines[1]


def test_sum_log_dedupes_per_step():
    ml = make_main_loop()
    ml._logger = _ListLogger()
    rule = Rule(id="r", name="加總", enabled=True, steps=[])
    roi = {"x": 10, "y": 20, "w": 100, "h": 50}
    ctx0 = _ctx()
    ctx0.step_idx = 0
    ctx1 = _ctx()
    ctx1.step_idx = 1

    ml._log_sum_result(rule, ctx0, roi, 35, 2, "+35", "frida")
    ml._log_sum_result(rule, ctx1, roi, 35, 2, "+35", "frida")
    ml._log_sum_result(rule, ctx0, roi, 35, 2, "+35", "frida")

    assert len(ml._logger.lines) == 2
    assert "step=0" in ml._logger.lines[0]
    assert "step=1" in ml._logger.lines[1]


def test_sum_panel_log_only_when_foreground():
    ml = make_main_loop()
    logged = []
    ml._log_exec = lambda *args: logged.append(args)

    def run_step(step, ctx, rule):
        ctx.sum_total = 35
        ctx.sum_count = 2
        return _ml.StepResult("continue")

    ml._run_step = run_step
    rule = Rule(id="r", name="加總", enabled=True, steps=[Step(type="sum", params={})])
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    rect = {"x": 0, "y": 0, "w": 10, "h": 10}

    ml._run_rule(rule, img, rect)
    assert logged == []

    ctx = _ctx()
    ctx.sum_foreground = True
    ml._run_rule(rule, img, rect, ctx)
    assert len(logged) == 1
    assert logged[0][2:4] == ("sum", "ok")
