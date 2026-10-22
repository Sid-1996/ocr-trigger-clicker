import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from _loader import load_sibling

_APP = QApplication.instance() or QApplication([])

_GUI = load_sibling("gui_main", "gui/06_gui_main.py")
_TMPL = load_sibling("template_matching", "core/11_template_matching.py")


def _b64_template() -> str:
    return _TMPL.img_to_b64(np.zeros((8, 8, 3), dtype=np.uint8))


def _make_form(params: dict):
    step = _GUI.Step(type="match_image", params=params)
    return _GUI._MatchImageStepForm(None, step, 0, None)


def test_fmt_capture_size_accepts_valid_and_rejects_dirty():
    f = _GUI._fmt_capture_size
    assert f([1920, 1080]) == "1920×1080"
    assert f((1600, 900)) == "1600×900"
    assert f([0, 1080]) is None
    assert f([1920]) is None
    assert f(["bad", 1080]) is None
    assert f(None) is None


def test_source_label_shows_recorded_size():
    form = _make_form({"template_data": _b64_template(), "capture_size": [1920, 1080]})
    assert not form._source_label.isHidden()
    assert form._source_label.text() == _GUI.T("step_form.template_source", size="1920×1080")
    assert form._source_label.toolTip() == _GUI.T("step_form.template_source_tip")
    form.deleteLater()


def test_source_label_warns_when_size_missing():
    form = _make_form({"template_data": _b64_template()})
    assert not form._source_label.isHidden()
    assert form._source_label.text() == _GUI.T("step_form.template_source_missing")
    assert "e67e22" in form._source_label.styleSheet()
    assert form._source_label.toolTip() == _GUI.T("step_form.template_source_missing_tip")
    form.deleteLater()


def test_source_label_hidden_without_template():
    form = _make_form({})
    assert form._source_label.isHidden()
    form.deleteLater()


def test_color_mask_status_and_toggles():
    mask = {"colors": [[0, 0, 0]], "tolerance": 10, "mode": "keep"}
    form = _make_form(
        {
            "template_data": _b64_template(),
            "match_color": True,
            "color_tolerance": 10,
            "color_mask": mask,
        }
    )
    expected = _GUI.T("step_form.color_mask_status_keep", n=1)
    expected += " · " + _GUI.T("step_form.color_mask_check_pct", pct=100)
    assert form._color_mask_status.text() == expected
    assert form._color_mask_btn.isEnabled()

    form._match_color.setChecked(False)
    assert form._color_mask_status.text() == _GUI.T("step_form.color_mask_needs_color")
    assert not form._color_mask_btn.isEnabled()

    form._match_color.setChecked(True)
    form._color_tolerance.setValue(0)
    assert form._color_mask_status.text() == _GUI.T("step_form.color_mask_zero_tolerance")

    form._color_tolerance.setValue(10)
    form.save()
    assert form._step.params["color_mask"] == mask
    form.deleteLater()
