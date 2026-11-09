import numpy as np
import pytest
from conftest import make_main_loop

from _loader import load_sibling
from core.rule_migration import _normalize_step_params

_number_sum = load_sibling("number_sum", "core/21_number_sum.py")
_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_ml = load_sibling("main_loop", "core/05_main_loop.py")

# 正式產品路徑的 Rule/Step class object（load_sibling 的共用 rule_models 模組實例）。
# Preflight 與 fingerprint 都以這個 class object 判定，測試必須用同一份建構；
# 用別名實例（from core.rule_models import ...）會讓規則被判 invalid_step 而 BLOCKED，
# 動作不會執行。
_models = load_sibling("rule_models", "core/rule_models.py")
Rule = _models.Rule
Step = _models.Step


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

    def get(self, key="interaction_mode"):
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
    assert not ml._sum_candidate


def test_sum_frame_start_hides_rule_not_evaluated():
    ml = make_main_loop()
    hides = []
    ml.on_sum_hide = lambda: hides.append(True)
    ml._sum_active_rule = "r"
    ml._sum_candidate = {("r", 0): (43, 1, 100.0), ("r", 1): (10, 1, 100.0)}
    ml._sum_seen = set()

    ml._sum_frame_start()

    assert hides == [True]
    assert ml._sum_active_rule is None
    assert not ml._sum_candidate
    assert ml._sum_seen == set()


@pytest.mark.parametrize("mode", ["frida", "hybrid"])
def test_handle_sum_non_foreground_logs_without_overlay(monkeypatch, mode):
    ml = make_main_loop()
    ml._config_store = _ModeConfig(mode)
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
    ml._config_store = _ModeConfig("frida")
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


def test_two_sum_steps_track_independently(monkeypatch):
    ml = make_main_loop()
    ml._logger = _ListLogger()
    rule = Rule(id="r", name="加總", enabled=True, steps=[])
    roi = {"x": 10, "y": 20, "w": 100, "h": 50}
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])

    ctxs = []
    for step_idx, total, count in ((0, 35, 2), (1, 10, 1)):
        ctx = _ctx()
        ctx.step_idx = step_idx
        ml._update_sum(rule, ctx, roi, total, count, "")
        ctxs.append((ctx, total, count))

    now[0] += 0.4
    for ctx, total, count in ctxs:
        ml._update_sum(rule, ctx, roi, total, count, "")
        assert ctx.sum_stable is True, f"step {ctx.step_idx} 應各自穩定"

    assert set(ml._last_sum_report["r"]) == {0, 1}
    assert len(ml._logger.lines) == 2


def test_sum_panel_log_in_all_modes():
    ml = make_main_loop()
    logged = []
    ml._log_exec = lambda *args, **kwargs: logged.append((args, kwargs))

    def run_step(step, ctx, rule):
        ctx.sum_total = 35
        ctx.sum_count = 2
        ctx.sum_stable = True
        return _ml.StepResult("continue")

    ml._run_step = run_step
    rule = Rule(id="r", name="加總", enabled=True, steps=[Step(type="sum", params={})])
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    rect = {"x": 0, "y": 0, "w": 10, "h": 10}

    ml._run_rule(rule, img, rect)
    assert len(logged) == 1
    assert logged[0][0][2:4] == ("sum", "ok")

    ctx = _ctx()
    ctx.sum_foreground = True
    ml._run_rule(rule, img, rect, ctx)
    assert len(logged) == 2
    assert logged[1][0][2:4] == ("sum", "ok")


# ── 加總閘門（ADR-0007）───────────────────────────────────────────────────

_GATE_ROI = {"x": 10, "y": 20, "w": 100, "h": 50}


def _gate_params(**over):
    params = {
        "roi": dict(_GATE_ROI),
        "gate": True,
        "operator": ">=",
        "value": 50,
        "gate_timeout_sec": 5,
        "on_fail": "stop",
    }
    params.update(over)
    return params


def _sum_text(total):
    return [_ocr.OcrResult(text=f"+{total}", x=0, y=0, w=20, h=10, confidence=0.9)]


def test_sum_gate_normalization_off_strips_gate_keys():
    params = _normalize_step_params(
        "sum",
        {
            "roi": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
            "operator": ">=",
            "value": 0,
            "on_fail": "stop",
        },
    )
    for key in ("gate", "operator", "value", "gate_timeout_sec", "on_fail"):
        assert key not in params


def test_sum_gate_normalization_on_clamps_and_normalizes():
    params = _normalize_step_params(
        "sum",
        {
            "roi": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
            "gate": True,
            "operator": "<",
            "value": "120",
            "gate_timeout_sec": 999,
            "on_fail": {"action": "advance"},
        },
    )
    assert params["gate"] is True
    assert params["operator"] == "<"
    assert params["value"] == 120.0
    assert params["gate_timeout_sec"] == 60.0
    assert params["on_fail"] == {"action": "advance"}


def test_sum_gate_normalization_keeps_invalid_value_as_none():
    params = _normalize_step_params(
        "sum",
        {
            "roi": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
            "gate": True,
            "value": "abc",
        },
    )
    # 無效值不可被 0.0 取代：0 會讓 >= 恆真，變成永遠通過
    assert params["value"] is None
    assert params["gate_timeout_sec"] == 5.0


def test_sum_gate_params_requires_explicit_flag():
    assert _ml.MainLoop._sum_gate_params({"operator": ">=", "value": 0}) is None
    gate = _ml.MainLoop._sum_gate_params({"gate": True})
    assert gate == {"operator": ">=", "value": None, "timeout": 5.0}


def test_is_detect_step_counts_only_gated_sum():
    assert _ml.MainLoop._is_detect_step(Step(type="detect", params={})) is True
    assert _ml.MainLoop._is_detect_step(Step(type="compare", params={})) is True
    assert _ml.MainLoop._is_detect_step(Step(type="match_image", params={})) is True
    assert _ml.MainLoop._is_detect_step(Step(type="sum", params={})) is False
    assert _ml.MainLoop._is_detect_step(Step(type="sum", params={"gate": True})) is True


def test_sum_gate_unreadable_waits_without_failing(monkeypatch):
    ml = make_main_loop()
    ml._ocr_region = lambda img, roi: []
    rule = Rule(id="r", name="閘門", enabled=True, steps=[])
    ctx = _ctx()
    ctx.step_idx = 0

    res = ml._handle_sum(_gate_params(on_fail={"action": "advance"}), ctx, rule)

    assert res.action == "wait", "讀不出數字時必須擋住後續步驟，不可當 0 判失敗"
    assert ctx.on_fail_fired is False
    assert not ctx.force_advance
    assert ("r", 0) in ml._sum_gate_wait


def test_sum_gate_unstable_waits_and_keeps_candidate(monkeypatch):
    ml = make_main_loop()
    ml._ocr_region = lambda img, roi: _sum_text(80)
    rule = Rule(id="r", name="閘門", enabled=True, steps=[])
    ctx = _ctx()
    ctx.step_idx = 0
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])

    res = ml._handle_sum(_gate_params(), ctx, rule)

    assert res.action == "wait", "未穩定不可直接判失敗"
    assert ctx.on_fail_fired is False
    assert ("r", 0) in ml._sum_candidate, "等待中不可清掉候選值，否則永遠等不到穩定"

    now[0] += 0.4
    res = ml._handle_sum(_gate_params(), ctx, rule)

    assert res.action == "continue"
    assert ctx.sum_stable is True
    assert ("r", 0) not in ml._sum_gate_wait


def test_sum_gate_not_met_follows_on_fail(monkeypatch):
    ml = make_main_loop()
    ml._ocr_region = lambda img, roi: _sum_text(10)
    rule = Rule(id="r", name="閘門", enabled=True, steps=[])
    ctx = _ctx()
    ctx.step_idx = 0
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])

    ml._handle_sum(_gate_params(), ctx, rule)
    now[0] += 0.4
    res = ml._handle_sum(_gate_params(), ctx, rule)

    from i18n import T

    assert res.action == "stop"
    assert res.detail == T("exec_log.detail.sum_gate_not_met")
    assert ctx.force_advance is False


def test_sum_gate_not_met_honors_advance(monkeypatch):
    ml = make_main_loop()
    ml._ocr_region = lambda img, roi: _sum_text(10)
    rule = Rule(id="r", name="閘門", enabled=True, steps=[])
    ctx = _ctx()
    ctx.step_idx = 0
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    params = _gate_params(on_fail={"action": "advance"})

    ml._handle_sum(params, ctx, rule)
    now[0] += 0.4
    res = ml._handle_sum(params, ctx, rule)

    assert res.action == "stop"
    assert ctx.force_advance is True, "閘門不符合時必須真的走 on_fail 設定的動作"


def test_sum_gate_empty_times_out_after_wait_budget(monkeypatch):
    ml = make_main_loop()
    ml._frame_count = 5
    ml._ocr_region = lambda img, roi: []
    rule = Rule(id="r", name="閘門", enabled=True, steps=[])
    ctx = _ctx()
    ctx.step_idx = 0
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])

    assert ml._handle_sum(_gate_params(), ctx, rule).action == "wait"

    now[0] += 6.0
    res = ml._handle_sum(_gate_params(), ctx, rule)

    from i18n import T

    assert res.action == "stop"
    assert res.detail == T("exec_log.detail.sum_wait_timeout")
    assert ("r", 0) not in ml._sum_gate_wait


def test_sum_gate_invalid_threshold_fails_safely(monkeypatch):
    ml = make_main_loop()
    ml._ocr_region = lambda img, roi: _sum_text(80)
    rule = Rule(id="r", name="閘門", enabled=True, steps=[])
    ctx = _ctx()
    ctx.step_idx = 0
    now = [100.0]
    monkeypatch.setattr(_ml.time, "monotonic", lambda: now[0])
    params = _gate_params(value=None)

    ml._handle_sum(params, ctx, rule)
    now[0] += 0.4
    res = ml._handle_sum(params, ctx, rule)

    from i18n import T

    assert res.action == "stop"
    assert res.detail == T("exec_log.detail.value_invalid")


def test_sum_gate_wait_blocks_following_steps():
    ml = make_main_loop()
    ml._ocr_region = lambda img, roi: []
    clicks = []
    ml._send_click = lambda *a, **k: clicks.append(a) or True
    rule = Rule(
        id="r",
        name="閘門",
        enabled=True,
        steps=[
            Step(type="sum", params=_gate_params()),
            Step(type="click", params={"target": "custom", "x": 5, "y": 5}),
        ],
    )
    img = np.zeros((600, 800, 3), dtype=np.uint8)
    rect = {"x": 100, "y": 200, "w": 800, "h": 600}

    outcome = ml._run_rule(rule, img, rect)

    assert outcome is None
    assert clicks == [], "等待中不可執行後續動作"


def _preflight(steps):
    from core.rule_preflight import rule_preflight

    return rule_preflight(Rule(id="r", name="p", enabled=True, steps=steps))


def test_preflight_gate_sum_requires_roi():
    res = _preflight(
        [
            Step(
                type="sum",
                params={"gate": True, "operator": ">=", "value": 10, "roi": {}},
            )
        ]
    )
    assert res.status == "blocked"
    assert "sum_gate_roi_unset" in res.problems


def test_preflight_gate_sum_rejects_invalid_threshold():
    res = _preflight(
        [
            Step(
                type="sum",
                params={
                    "gate": True,
                    "operator": "??",
                    "value": None,
                    "roi": _GATE_ROI,
                },
            )
        ]
    )
    assert res.status == "blocked"
    assert "sum_gate_value_invalid" in res.problems


def test_preflight_gate_sum_click_needs_prior_detect():
    sum_step = Step(
        type="sum", params={"gate": True, "operator": ">=", "value": 10, "roi": _GATE_ROI}
    )
    click_step = Step(type="click", params={"target": "text_center"})

    blocked = _preflight([sum_step, click_step])
    assert blocked.status == "blocked"
    assert "gate_sum_click_no_target" in blocked.problems

    passed = _preflight([Step(type="detect", params={"text": "獎勵"}), sum_step, click_step])
    assert passed.status == "passed"


def test_preflight_gate_sum_allows_custom_click():
    res = _preflight(
        [
            Step(
                type="sum",
                params={
                    "gate": True,
                    "operator": ">=",
                    "value": 10,
                    "roi": _GATE_ROI,
                },
            ),
            Step(type="click", params={"target": "custom", "x": 5, "y": 5}),
        ]
    )
    assert res.status == "passed"
