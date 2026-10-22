import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from _loader import load_sibling

_APP = QApplication.instance() or QApplication([])

_TMPL = load_sibling("template_matching", "core/11_template_matching.py")
_CM = load_sibling("template_color_mask", "gui/17_template_color_mask.py")


def _template() -> np.ndarray:
    tpl = np.zeros((21, 21, 3), dtype=np.uint8)
    tpl[:] = (100, 100, 100)
    tpl[5:16, 5:16] = (0, 0, 0)
    return tpl


def test_suggest_background_colors_only_uses_border():
    colors = _CM.suggest_background_colors(_template())
    assert colors == [[100, 100, 100]]


def test_dialog_preview_and_result():
    b64 = _TMPL.img_to_b64(_template())
    dlg = _CM._TemplateColorMaskDialog(
        b64,
        {"colors": [[100, 100, 100]], "tolerance": 10, "mode": "ignore"},
    )
    assert dlg._view._mask is not None
    assert int(dlg._view._mask.sum()) == 121
    assert "27%" in dlg._preview_label.text()
    assert "ignore" in dlg._mask_dict()["mode"]

    dlg._keep_radio.setChecked(True)
    assert int(dlg._view._mask.sum()) == 320
    assert "73%" in dlg._preview_label.text()

    dlg._apply()
    assert dlg._result["mode"] == "keep"
    dlg.deleteLater()


def test_dialog_no_colors_clears_result():
    dlg = _CM._TemplateColorMaskDialog(_TMPL.img_to_b64(_template()), None)
    dlg._apply()
    assert dlg._result == {}
    dlg.deleteLater()


def test_color_mask_dialog_rejects_empty_or_bad_b64():
    assert _CM.color_mask_dialog(None, b64="") is None
    assert _CM.color_mask_dialog(None, b64="not-base64!!!") is None
