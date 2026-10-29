import numpy as np
from conftest import make_main_loop

from _loader import load_sibling
from core.rule_models import Rule, RuleGroup, Step

_ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
RuleMig = load_sibling("rule_migration", "core/rule_migration.py")
StepContext = _ml_mod.StepContext
StepResult = _ml_mod.StepResult

_BLANK = np.zeros((100, 100, 3), dtype=np.uint8)
_RECT = {"x": 0, "y": 0, "w": 100, "h": 100}
_MISSING = object()


def _verify(on_fail=_MISSING, retries=0):
    v = {
        "type": "detect",
        "text": "never",
        "timeout_ms": 10,
        "poll_interval_ms": 1,
        "retries": retries,
        "retry_delay_ms": 0,
    }
    if on_fail is not _MISSING:
        v["on_fail"] = on_fail
    return v


def _click(x, verify=None):
    params = {"target": "custom", "x": x, "y": x, "after_delay_ms": 0}
    if verify is not None:
        params["verify"] = verify
    return Step("click", params)


def _normalized_click(x, verify):
    params = RuleMig._normalize_step_params(
        "click",
        {
            "target": "custom",
            "x": x,
            "y": x,
            "random_offset": 0,
            "after_delay_ms": 0,
            "verify": verify,
        },
    )
    return Step("click", params)


def _run(monkeypatch, steps):
    ml = make_main_loop()
    clicks = []
    keys = []
    ml._send_click = lambda x, y, button="left", hold_ms=0: clicks.append((x, y)) or True
    ml._send_key = lambda key: keys.append(key) or True
    monkeypatch.setattr(ml, "_poll_verify", lambda verify: "timeout")
    rule = Rule(id="verify-flow", name="verify-flow", enabled=True, steps=steps)
    ctx = StepContext(img=_BLANK, rect=_RECT)
    ml._run_rule(rule, _BLANK, _RECT, ctx)
    return ml, ctx, rule, clicks, keys


def test_verify_missing_on_fail_advances_without_next_step(monkeypatch):
    _, ctx, _, clicks, _ = _run(monkeypatch, [_click(0.1, _verify()), _click(0.8)])

    assert clicks == [(10, 10)]
    assert ctx.force_advance is True
    assert ctx.on_fail_fired is False


def test_verify_empty_key_normalized_advances_without_next_step(monkeypatch):
    for raw in ({"action": "key", "key": ""}, "key"):
        _, ctx, _, clicks, keys = _run(
            monkeypatch, [_normalized_click(0.1, _verify(raw)), _click(0.8)]
        )

        assert keys == [], raw
        assert clicks == [(10, 10)], raw
        assert ctx.force_advance is True, raw
        assert ctx.on_fail_fired is False, raw


def test_verify_empty_key_does_not_repeat_action_or_run_next_step(monkeypatch):
    ml = make_main_loop()
    clicks = []
    keys = []
    ml._send_click = lambda x, y, button="left", hold_ms=0: clicks.append((x, y)) or True
    ml._send_key = lambda key: keys.append(key) or True
    monkeypatch.setattr(ml, "_poll_verify", lambda verify: "timeout")

    first = Rule(
        id="r1",
        name="r1",
        enabled=True,
        steps=[
            _normalized_click(0.1, _verify({"action": "key", "key": ""})),
            _click(0.8),
        ],
    )
    second = Rule(id="r2", name="r2", enabled=True, steps=[Step("wait", {"ms": 0})])
    ml._rules = [first, second]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="g1", rule_ids=["r1", "r2"], mode="once")]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0

    ml._process_rules(_BLANK, _RECT)
    ml._process_rules(_BLANK, _RECT)

    assert keys == []
    assert clicks == [(10, 10)], f"空 key 不應送下一步或每幀重送動作: {clicks}"


def test_verify_missing_on_fail_does_not_repeat_action_each_frame(monkeypatch):
    ml = make_main_loop()
    clicks = []
    ml._send_click = lambda x, y, button="left", hold_ms=0: clicks.append((x, y)) or True
    monkeypatch.setattr(ml, "_poll_verify", lambda verify: "timeout")

    first = Rule(id="r1", name="r1", enabled=True, steps=[_click(0.1, _verify())])
    second = Rule(id="r2", name="r2", enabled=True, steps=[Step("wait", {"ms": 0})])
    ml._rules = [first, second]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="g1", rule_ids=["r1", "r2"], mode="once")]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0

    ml._process_rules(_BLANK, _RECT)
    ml._process_rules(_BLANK, _RECT)

    assert clicks == [(10, 10)], f"缺省 on_fail 不應每幀重送動作: {clicks}"


def test_verify_missing_on_fail_stops_after_default_retry(monkeypatch):
    ml = make_main_loop()
    clicks = []
    ml._send_click = lambda x, y, button="left", hold_ms=0: clicks.append((x, y)) or True
    monkeypatch.setattr(ml, "_poll_verify", lambda verify: "timeout")

    first = Rule(
        id="r1",
        name="r1",
        enabled=True,
        steps=[_click(0.1, _verify(retries=1))],
    )
    second = Rule(id="r2", name="r2", enabled=True, steps=[Step("wait", {"ms": 0})])
    ml._rules = [first, second]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="g1", rule_ids=["r1", "r2"], mode="once")]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0

    ml._process_rules(_BLANK, _RECT)
    ml._process_rules(_BLANK, _RECT)

    assert clicks == [(10, 10), (10, 10)], f"只允許預設一次重試，不得每幀重送: {clicks}"


def test_verify_key_sends_key_and_continues_next_step(monkeypatch):
    _, _, _, clicks, keys = _run(
        monkeypatch,
        [_click(0.1, _verify({"action": "key", "key": "Escape"})), _click(0.8)],
    )

    assert keys == ["Escape"]
    assert clicks == [(10, 10), (80, 80)]


def test_verify_skip_jumps_to_requested_step(monkeypatch):
    _, _, _, clicks, _ = _run(
        monkeypatch,
        [
            _click(0.1, _verify({"action": "skip", "skip_to": 2})),
            _click(0.5),
            _click(0.8),
        ],
    )

    assert clicks == [(10, 10), (80, 80)]


def test_verify_skip_to_end_finishes_rule(monkeypatch):
    _, ctx, _, clicks, _ = _run(
        monkeypatch,
        [_click(0.1, _verify({"action": "skip", "skip_to": 2})), _click(0.8)],
    )

    assert clicks == [(10, 10)]
    assert ctx.force_advance is False


def test_verify_backward_skip_does_not_loop(monkeypatch):
    _, _, _, clicks, _ = _run(
        monkeypatch,
        [_click(0.1, _verify({"action": "skip", "skip_to": 0})), _click(0.8)],
    )

    assert clicks == [(10, 10)]


def test_verify_stop_and_advance_behaviour_unchanged(monkeypatch):
    _, stop_ctx, _, stop_clicks, _ = _run(
        monkeypatch,
        [_click(0.1, _verify({"action": "stop"})), _click(0.8)],
    )
    assert stop_clicks == [(10, 10)]
    assert stop_ctx.triggered is False
    assert stop_ctx.force_advance is False

    _, advance_ctx, _, advance_clicks, _ = _run(
        monkeypatch,
        [_click(0.1, _verify({"action": "advance"})), _click(0.8)],
    )
    assert advance_clicks == [(10, 10)]
    assert advance_ctx.force_advance is True


def test_verify_jump_rule_behaviour_unchanged(monkeypatch):
    ml = make_main_loop()
    clicks = []
    ml._send_click = lambda x, y, button="left", hold_ms=0: clicks.append((x, y)) or True
    monkeypatch.setattr(ml, "_poll_verify", lambda verify: "timeout")

    target = Rule(id="target", name="target", enabled=True, steps=[Step("wait", {"ms": 0})])
    source = Rule(
        id="source",
        name="source",
        enabled=True,
        steps=[
            _click(0.1, _verify({"action": "jump", "rule_id": "target"})),
            _click(0.8),
        ],
    )
    ml._rules = [source, target]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="g1", rule_ids=["source", "target"], mode="once")]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    ctx = StepContext(img=_BLANK, rect=_RECT)

    ml._run_rule(source, _BLANK, _RECT, ctx)

    assert clicks == [(10, 10)]
    assert ctx.jumped is True
    assert ml._rule_in_group_ptr == 1


def test_verify_cancel_does_not_run_generic_on_fail(monkeypatch):
    ml = make_main_loop()
    clicks = []
    fail_calls = []
    ml._send_click = lambda x, y, button="left", hold_ms=0: clicks.append((x, y)) or True
    monkeypatch.setattr(ml, "_poll_verify", lambda verify: "cancelled")
    monkeypatch.setattr(
        ml,
        "_handle_on_fail",
        lambda *args: fail_calls.append(1) or StepResult("stop"),
    )
    rule = Rule(
        id="cancel",
        name="cancel",
        enabled=True,
        steps=[_click(0.1, _verify({"action": "advance"}))],
    )
    ctx = StepContext(img=_BLANK, rect=_RECT)

    ml._run_rule(rule, _BLANK, _RECT, ctx)

    assert clicks == [(10, 10)]
    assert fail_calls == []
    assert ctx.triggered is False
    assert ctx.force_advance is False


def test_verify_retries_keep_existing_action_count(monkeypatch):
    _, _, _, clicks, _ = _run(monkeypatch, [_click(0.1, _verify(retries=2))])

    assert len(clicks) == 3, f"retries=2 應為原始動作＋2 次重試: {clicks}"


def test_step_key_and_skip_failure_paths_still_work(monkeypatch):
    ml = make_main_loop()
    monkeypatch.setattr(_ml_mod, "recognize", lambda *a, **k: [])
    clicks = []
    keys = []
    ml._send_click = lambda x, y, button="left", hold_ms=0: clicks.append((x, y)) or True
    ml._send_key = lambda key: keys.append(key) or True

    key_rule = Rule(
        id="step-key",
        name="step-key",
        enabled=True,
        steps=[
            Step(
                "detect",
                {
                    "text": "never",
                    "on_fail": {"action": "key", "key": "Escape"},
                },
            ),
            _click(0.8),
        ],
    )
    ml._run_rule(key_rule, _BLANK, _RECT, StepContext(img=_BLANK, rect=_RECT))

    skip_rule = Rule(
        id="step-skip",
        name="step-skip",
        enabled=True,
        steps=[
            Step(
                "detect",
                {
                    "text": "never",
                    "on_fail": {"action": "skip", "skip_to": 1},
                },
            ),
            _click(0.5),
        ],
    )
    ml._run_rule(skip_rule, _BLANK, _RECT, StepContext(img=_BLANK, rect=_RECT))

    assert keys == ["Escape"]
    assert clicks == [(80, 80), (50, 50)]
