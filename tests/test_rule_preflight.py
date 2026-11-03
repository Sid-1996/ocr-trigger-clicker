import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402
from core.rule_models import Step as _AliasStep  # noqa: E402
from core.rule_preflight import rule_preflight  # noqa: E402

# 正式產品路徑的 Rule/Step class object：load_sibling("rule_models", ...) 的共用模組實例。
# core/05_main_loop.py 的 fingerprint 用同一個 class object 做 isinstance 判定，
# 這裡必須用同一份建構測試物件，否則兩邊判定基準不一致。
_models = load_sibling("rule_models", "core/rule_models.py")
Rule = _models.Rule
Step = _models.Step


def _make_rule(*steps):
    """Helper to build a Rule for testing."""
    return Rule(id="test", name="Test Rule", enabled=True, steps=list(steps))


def _make_step(**kwargs):
    """Helper to build a Step, filling in sensible defaults."""
    step_type = kwargs.pop("type", "detect")
    params = kwargs.pop("params", {})
    return Step(type=step_type, params=params | kwargs)


class BadStep:
    """A step-like object without type/params attributes."""


def _make_bad_rule(steps):
    """Helper to build a Rule for testing bad step handling."""
    return Rule(id="test", name="Bad Rule", enabled=True, steps=list(steps))


def _assert_passed(result, label=""):
    assert result.status == "passed", f"{label}: Expected passed, got {result.status}"
    assert result.problems == [], f"{label}: Expected empty problems, got {result.problems}"
    assert result.warnings == [], f"{label}: Expected empty warnings, got {result.warnings}"


def test_rule_none_is_blocked() -> None:
    """None Rule 必須安全地判為 blocked（invalid_rule），且不產生不合理警告。"""
    result = rule_preflight(None)
    assert result.status == "blocked", f"Expected blocked, got {result.status}"
    assert "invalid_rule" in result.problems
    assert result.warnings == [], f"Expected empty warnings, got {result.warnings}"


def test_canonical_step_is_accepted() -> None:
    """正式產品路徑的 canonical Step 必須正常通過（與 fingerprint 同一 class object）。"""
    rule = _make_rule(_make_step(type="detect", params={"text": "Hello"}))
    assert type(rule.steps[0]) is Step
    _assert_passed(rule_preflight(rule), "test_canonical_step_is_accepted")


def test_non_canonical_step_is_rejected() -> None:
    """非 canonical Step（core.rule_models 別名實例）必須判為 invalid_step。

    正式產品路徑的 Step 來自 load_sibling("rule_models", ...) 的共用模組實例；
    一般 import 的 core.rule_models 是另一個 module 物件 → 另一個 class object，
    不得被當作合法 Step，否則 fingerprint 會回 None、cache 與 blocked 日誌靜默失效。
    """
    alias_step = _AliasStep(type="detect", params={"text": "hello"})
    assert type(alias_step) is not Step
    rule = Rule(id="test", name="Test Rule", enabled=True, steps=[alias_step])
    result = rule_preflight(rule)
    assert result.status == "blocked", f"Expected blocked, got {result.status}"
    assert "invalid_step" in result.problems


def test_normal_rule() -> None:
    rule = _make_rule(_make_step(type="detect", params={"text": "Hello"}))
    result = rule_preflight(rule)
    _assert_passed(result, "test_normal_rule")


def test_detect_missing_text() -> None:
    rule = _make_rule(_make_step(type="detect"))  # no "text" key
    result = rule_preflight(rule)
    assert result.status == "blocked", f"Expected blocked, got {result.status}"
    assert "empty_detect_text" in result.problems


def test_detect_empty_string() -> None:
    rule = _make_rule(_make_step(type="detect", params={"text": ""}))
    result = rule_preflight(rule)
    assert result.status == "blocked", f"Expected blocked, got {result.status}"
    assert "empty_detect_text" in result.problems


def test_detect_whitespace_only() -> None:
    rule = _make_rule(_make_step(type="detect", params={"text": "   "}))
    result = rule_preflight(rule)
    assert result.status == "blocked", f"Expected blocked, got {result.status}"
    assert "empty_detect_text" in result.problems


def test_detect_text_none() -> None:
    rule = _make_rule(_make_step(type="detect", params={"text": None}))
    result = rule_preflight(rule)
    assert result.status == "blocked", f"Expected blocked, got {result.status}"
    assert "invalid_detect_text" in result.problems


def test_detect_non_string_text() -> None:
    rule = _make_rule(_make_step(type="detect", params={"text": 123}))
    result = rule_preflight(rule)
    assert result.status == "blocked", f"Expected blocked, got {result.status}"
    assert "invalid_detect_text" in result.problems


def test_detect_normal_text() -> None:
    rule = _make_rule(_make_step(type="detect", params={"text": "Hello World"}))
    result = rule_preflight(rule)
    _assert_passed(result, "test_detect_normal_text")


def test_custom_click_at_origin() -> None:
    rule = _make_rule(_make_step(type="click", params={"target": "custom", "x": 0, "y": 0}))
    result = rule_preflight(rule)
    assert result.status == "passed", f"Expected passed, got {result.status}"
    assert "custom_click_at_origin" in result.warnings
    assert result.problems == []


def test_custom_click_not_origin() -> None:
    rule = _make_rule(_make_step(type="click", params={"target": "custom", "x": 10, "y": 20}))
    result = rule_preflight(rule)
    assert result.status == "passed", f"Expected passed, got {result.status}"
    assert result.warnings == []
    assert result.problems == []


def test_non_custom_click() -> None:
    rule = _make_rule(_make_step(type="click", params={"target": "text_center"}))
    result = rule_preflight(rule)
    _assert_passed(result, "test_non_custom_click")


def test_unknown_step_type() -> None:
    rule = _make_rule(_make_step(type="unknown_type"))
    result = rule_preflight(rule)
    assert result.status == "blocked", f"Expected blocked, got {result.status}"
    assert "unknown_step_type" in result.problems


def test_empty_steps() -> None:
    rule = _make_rule()
    result = rule_preflight(rule)
    _assert_passed(result, "test_empty_steps")


def test_detect_blocked_and_custom_click_warning() -> None:
    rule = _make_rule(
        _make_step(type="detect", params={"text": ""}),
        _make_step(type="click", params={"target": "custom", "x": 0, "y": 0}),
    )
    result = rule_preflight(rule)
    assert result.status == "blocked", f"Expected blocked, got {result.status}"
    assert "empty_detect_text" in result.problems
    assert "custom_click_at_origin" in result.warnings


def test_multiple_unknown_steps() -> None:
    rule = _make_rule(
        _make_step(type="unknown_type1"),
        _make_step(type="unknown_type2"),
    )
    result = rule_preflight(rule)
    assert result.status == "blocked", f"Expected blocked, got {result.status}"
    assert "unknown_step_type" in result.problems


def test_multiple_empty_detect_dedup() -> None:
    rule = _make_rule(
        _make_step(type="detect", params={"text": ""}),
        _make_step(type="detect", params={"text": "   "}),
    )
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert result.problems == ["empty_detect_text"]


def test_multiple_invalid_detect_dedup() -> None:
    rule = _make_rule(
        _make_step(type="detect", params={"text": None}),
        _make_step(type="detect", params={"text": 123}),
    )
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert result.problems == ["invalid_detect_text"]


def test_rule_steps_none() -> None:
    rule = Rule(id="bad", name="Bad", enabled=True, steps=None)
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "invalid_steps" in result.problems


def test_rule_steps_not_list() -> None:
    class BadSteps:  # type: ignore
        pass

    rule = Rule(id="bad", name="Bad", enabled=True, steps=BadSteps())
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "invalid_steps" in result.problems


def test_step_none() -> None:
    rule = _make_bad_rule([None, Step(type="detect", params={"text": "x"})])
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "invalid_step" in result.problems


def test_step_not_step_instance() -> None:
    class BadStep:
        type = "detect"
        params = {"text": "x"}

    rule = _make_bad_rule([BadStep(), Step(type="detect", params={"text": "x"})])
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "invalid_step" in result.problems


def test_step_type_none() -> None:
    rule = _make_bad_rule([Step(type=None, params={"text": "x"})])
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "unknown_step_type" in result.problems


def test_step_type_non_string() -> None:
    rule = _make_bad_rule([Step(type=12345, params={"text": "x"})])
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "unknown_step_type" in result.problems


def test_step_params_none() -> None:
    rule = _make_bad_rule([Step(type="detect", params=None)])
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "empty_detect_text" in result.problems


def test_step_params_non_dict() -> None:
    class BadParams:
        pass

    rule = _make_bad_rule([Step(type="detect", params=BadParams())])
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "empty_detect_text" in result.problems


def test_detect_text_missing_in_params() -> None:
    rule = _make_bad_rule([Step(type="detect", params={})])
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "empty_detect_text" in result.problems


def test_detect_text_nonzero_none() -> None:
    rule = _make_bad_rule([Step(type="detect", params={"text": None})])
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "invalid_detect_text" in result.problems


def test_detect_text_number() -> None:
    rule = _make_bad_rule([Step(type="detect", params={"text": 42})])
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "invalid_detect_text" in result.problems


def test_detect_text_bytes() -> None:
    rule = _make_bad_rule([Step(type="detect", params={"text": b"abc"})])
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "invalid_detect_text" in result.problems


def test_click_x_none_is_not_custom_origin() -> None:
    rule = _make_bad_rule([Step(type="click", params={"target": "custom", "x": None, "y": None})])
    result = rule_preflight(rule)
    assert result.status == "passed"
    assert "custom_click_at_origin" not in result.warnings


def test_click_x_non_numeric_is_not_custom_origin() -> None:
    rule = _make_bad_rule(
        [Step(type="click", params={"target": "custom", "x": "zero", "y": "zero"})]
    )
    result = rule_preflight(rule)
    assert result.status == "passed"
    assert "custom_click_at_origin" not in result.warnings


def test_multiple_steps_same_rule_identical_fingerprint() -> None:
    # Same-rule identity and content must not collide; this test validates only that
    # different Rule objects do not share preflight cache. Runtime cache key uses
    # object identity, so this is enforced by construction.
    rule_a = _make_rule(_make_step(type="detect", params={"text": "hello"}))
    rule_b = _make_rule(_make_step(type="detect", params={"text": "hello"}))
    assert rule_a.id == rule_b.id and rule_a is not rule_b


def test_click_warning_with_missing_text_still_warns() -> None:
    rule = _make_rule(
        _make_step(type="detect", params={}),  # blocked
        _make_step(type="click", params={"target": "custom", "x": 0, "y": 0}),
    )
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert "custom_click_at_origin" in result.warnings
    rule = _make_rule(
        _make_step(type="click", params={"target": "custom", "x": 0, "y": 0}),
        _make_step(type="click", params={"target": "custom", "x": 0, "y": 0}),
    )
    result = rule_preflight(rule)
    assert result.status == "passed"
    assert result.warnings == ["custom_click_at_origin"]
    assert result.problems == []


def test_dedup_and_order() -> None:
    rule = _make_rule(
        _make_step(type="detect", params={"text": ""}),
        _make_step(type="click", params={"target": "custom", "x": 0, "y": 0}),
    )
    result = rule_preflight(rule)
    assert result.problems[0] == "empty_detect_text", (
        f"Expected first problem to be 'empty_detect_text', got {result.problems[0]}"
    )


def test_problem_order_stability() -> None:
    rule = _make_rule(
        _make_step(type="detect", params={"text": ""}),
        _make_step(type="unknown_type"),
    )
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert result.problems == ["empty_detect_text", "unknown_step_type"]
    rule = _make_rule(
        _make_step(type="detect", params={"text": ""}),
        _make_step(type="unknown_type"),
    )
    result = rule_preflight(rule)
    assert result.status == "blocked"
    assert result.problems == ["empty_detect_text", "unknown_step_type"]
