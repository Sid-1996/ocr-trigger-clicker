"""加總閘門表單（_SumStepForm）的存檔契約。

表單是唯一的使用者入口，這裡驗證的是「使用者看到什麼、存下來變成什麼」：
閘門關閉不得留下任何閘門參數（否則 migration 會把它當成開啟），
閘門開啟才寫入 operator/value/等待時間/失敗處理。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _loader import load_sibling  # noqa: E402

_GATE_KEYS = ("gate", "operator", "value", "gate_timeout_sec", "on_fail")
_ROI = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}


def _make_form(params):
    gui = load_sibling("gui_main", "gui/06_gui_main.py")
    models = load_sibling("rule_models", "core/rule_models.py")
    step = models.Step(type="sum", params=dict(params))
    return gui._SumStepForm(None, step, 0, None), step


def test_gate_off_by_default_and_strips_keys(qt_app):
    form, step = _make_form({"roi": dict(_ROI), "operator": ">=", "value": 0})

    assert form._gate.isChecked() is False
    assert form._gate_box.isVisibleTo(form) is False

    form.save()

    for key in _GATE_KEYS:
        assert key not in step.params, f"閘門關閉時不得留下 {key}"
    assert step.params["roi"] == _ROI


def test_gate_on_round_trips_saved_values(qt_app):
    form, step = _make_form(
        {
            "roi": dict(_ROI),
            "gate": True,
            "operator": "<",
            "value": 120,
            "gate_timeout_sec": 10,
            "on_fail": {"action": "advance"},
        }
    )

    assert form._gate.isChecked() is True
    assert form._op.currentData() == "<"
    assert form._value.value() == 120
    assert form._wait.currentData() == 10
    assert form._fail.currentData() == "advance"

    form.save()

    assert step.params["gate"] is True
    assert step.params["operator"] == "<"
    assert step.params["value"] == 120.0
    assert step.params["gate_timeout_sec"] == 10.0
    assert step.params["on_fail"] == {"action": "advance"}


def test_toggle_writes_and_removes_gate_params(qt_app):
    form, step = _make_form({"roi": dict(_ROI)})

    form._gate.setChecked(True)

    assert step.params["gate"] is True
    assert step.params["operator"] == ">="
    assert step.params["value"] == 100.0
    assert step.params["gate_timeout_sec"] == 5.0
    assert step.params["on_fail"] == "stop"

    form._gate.setChecked(False)

    for key in _GATE_KEYS:
        assert key not in step.params


def test_notify_failure_writes_dict(qt_app):
    form, step = _make_form({"roi": dict(_ROI), "gate": True, "value": 5})

    idx = form._fail.findData("notify")
    assert idx >= 0
    form._fail.setCurrentIndex(idx)
    form.save()

    assert step.params["on_fail"] == {
        "action": "notify",
        "message": "",
        "stop_groups": [],
    }


def test_step_summary_mentions_gate_condition(qt_app):
    from i18n import T

    gui = load_sibling("gui_main", "gui/06_gui_main.py")
    models = load_sibling("rule_models", "core/rule_models.py")

    gated = models.Step(
        type="sum",
        params={"roi": dict(_ROI), "gate": True, "operator": ">=", "value": 100},
    )
    text = gui._step_summary(gated)
    assert "100" in text
    assert T("step_form.sum_op_at_least") in text

    plain = models.Step(type="sum", params={"roi": dict(_ROI)})
    assert T("step_form.sum_op_at_least") not in gui._step_summary(plain)
