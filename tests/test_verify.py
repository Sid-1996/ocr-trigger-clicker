from _loader import load_sibling

RuleMig = load_sibling("rule_migration", "core/rule_migration.py")
Ser = load_sibling("rule_serialization", "core/rule_serialization.py")
Models = load_sibling("rule_models", "core/rule_models.py")

Rule = Models.Rule
Step = Models.Step


def test_verify_normalize_detect_valid():
    v = {
        "type": "detect",
        "text": " 新場景文字 ",
        "roi": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.3, "roi_coord": "client"},
        "timeout_ms": 3000,
        "poll_interval_ms": 300,
        "delay_before_ms": 0,
        "on_fail": {"action": "notify", "message": "fail", "stop_groups": []},
    }
    nv = RuleMig._normalize_verify(v)
    assert nv is not None
    assert nv["type"] == "detect"
    assert nv["text"] == "新場景文字"
    assert nv["roi"]["roi_coord"] == "client"
    assert nv["timeout_ms"] == 3000
    assert nv["on_fail"]["action"] == "notify"


def test_verify_normalize_match_image_valid():
    v = {
        "type": "match_image",
        "template_data": "abc==",
        "threshold": 0.85,
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "timeout_ms": 5000,
        "on_fail": {"action": "advance"},
    }
    nv = RuleMig._normalize_verify(v)
    assert nv is not None
    assert nv["type"] == "match_image"
    assert nv["threshold"] == 0.85


def test_verify_roundtrip_step_params():
    # Click with verify should survive _normalize_step_params
    params = {
        "target": "custom",
        "x": 0.5,
        "y": 0.5,
        "after_delay_ms": 250,
        "verify": {
            "type": "detect",
            "text": "戰鬥",
            "roi": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5, "roi_coord": "client"},
            "timeout_ms": 3000,
            "poll_interval_ms": 300,
            "delay_before_ms": 0,
            "on_fail": {"action": "notify", "message": "未進戰鬥"},
        },
    }
    out = RuleMig._normalize_step_params("click", params)
    assert out["verify"]["text"] == "戰鬥"
    assert out["verify"]["roi"]["x"] == 0.1
    assert out["after_delay_ms"] == 250


def test_verify_clamp():
    v = {
        "type": "detect",
        "text": "a",
        "timeout_ms": 99999,
        "poll_interval_ms": 1,
        "delay_before_ms": 99999,
    }
    nv = RuleMig._normalize_verify(v)
    assert nv["timeout_ms"] == 30000
    assert nv["poll_interval_ms"] == 50
    assert nv["delay_before_ms"] == 5000


def test_verify_plus_stop_invalid():
    for raw in [
        {"type": "detect", "text": "hi", "on_fail": "stop"},
        {"type": "detect", "text": "hi", "on_fail": {"action": "stop"}},
        {"type": "match_image", "template_data": "abc", "on_fail": "stop"},
    ]:
        assert RuleMig._normalize_verify(raw) is None
        # also dropped at step level
        out = RuleMig._normalize_step_params("click", {"verify": raw})
        assert "verify" not in out


def test_verify_invalid_empty_text_template():
    assert RuleMig._normalize_verify({"type": "detect", "text": "   "}) is None
    assert (
        RuleMig._normalize_verify({"type": "match_image", "template_data": "   ", "template": ""})
        is None
    )
    assert RuleMig._normalize_verify({"type": "detect"}) is None
    assert RuleMig._normalize_verify({"type": "unknown", "text": "hi"}) is None


def test_verify_allowed_on_parent_only():
    # detect step must not keep verify
    out = RuleMig._normalize_step_params(
        "detect", {"text": "hi", "verify": {"type": "detect", "text": "x"}}
    )
    assert "verify" not in out
    # wait must not
    out2 = RuleMig._normalize_step_params(
        "wait", {"ms": 100, "verify": {"type": "detect", "text": "x"}}
    )
    assert "verify" not in out2


def test_backward_compat_no_verify():
    # old task without verify stays unchanged
    out = RuleMig._normalize_step_params("click", {"target": "custom", "x": 0.2, "y": 0.3})
    assert "verify" not in out
    assert out["target"] == "custom"


def test_serialization_roundtrip():
    rule = Rule(
        id="r1",
        name="抽抽樂串",
        enabled=True,
        steps=[
            Step(
                type="detect",
                params={
                    "text": "抽抽樂",
                    "roi": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "roi_coord": "client"},
                },
            ),
            Step(
                type="click",
                params={
                    "target": "custom",
                    "x": 0.5,
                    "y": 0.5,
                    "verify": {
                        "type": "detect",
                        "text": "新的場景文字",
                        "roi": {"x": 0.3, "y": 0.4, "w": 0.2, "h": 0.2, "roi_coord": "client"},
                        "timeout_ms": 3000,
                        "poll_interval_ms": 300,
                        "delay_before_ms": 0,
                        "on_fail": {"action": "notify", "message": "驗證失敗"},
                    },
                },
            ),
        ],
    )
    # simulate save/load via _normalize_step_params roundtrip
    for s in rule.steps:
        norm = RuleMig._normalize_step_params(s.type, s.params)
        s.params = norm
    assert rule.steps[1].params["verify"]["text"] == "新的場景文字"
    assert rule.steps[1].params["verify"]["roi"]["x"] == 0.3
    assert rule.steps[0].params["roi"]["x"] == 0.1
    # verify ROI independent from detect ROI
    assert rule.steps[0].params["roi"]["x"] != rule.steps[1].params["verify"]["roi"]["x"]


def test_verify_gui_independent_roi_smoke():
    # headless verify widget independent ROI
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    _VerifyWidget = m._VerifyWidget
    counter = [0]

    class Sig:
        def emit(self):
            counter[0] += 1

    parent = type("P", (), {})()
    parent.steps_changed = Sig()
    step = Step(type="click", params={})
    w = _VerifyWidget(parent, step)
    w.show()
    app.processEvents()
    # enable verify and pick different ROI
    w._enable.setChecked(True)
    app.processEvents()
    assert not w._container.isHidden()
    # simulate picking verify ROI B different from detect ROI A
    step_detect = Step(
        type="detect",
        params={
            "text": "抽抽樂",
            "roi": {"x": 0.01, "y": 0.01, "w": 0.2, "h": 0.2, "roi_coord": "client"},
        },
    )
    # verify ROI B
    w._step.params["verify"]["roi"] = {
        "x": 0.3,
        "y": 0.4,
        "w": 0.2,
        "h": 0.2,
        "roi_coord": "client",
    }
    w._update_roi_label()
    assert step_detect.params["roi"]["x"] == 0.01
    assert w._step.params["verify"]["roi"]["x"] == 0.3
    # toggle not emit
    assert counter[0] == 0
