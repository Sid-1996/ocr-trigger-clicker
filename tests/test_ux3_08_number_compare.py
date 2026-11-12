"""UX3-08：數字比對步驟易用性（數值顯示 + 數字格式）回歸測試。

鎖住三件事：
- 數值欄位只去掉「顯示上」的無意義尾隨零，widget 值、存檔值、比較結果不變。
- 數字格式選單由既有 pattern 回推；舊規則的 pattern（含自訂與空白）存檔後
  必須逐字保留，選單初始化不得覆寫。
- 三種常用格式與 core `_handle_compare` 的實際匹配語意一致。
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from conftest import make_main_loop  # noqa: E402

from _loader import load_sibling  # noqa: E402

_GUI = load_sibling("gui_main", "gui/06_gui_main.py")
_ML = load_sibling("main_loop", "core/05_main_loop.py")
_OCR = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_models = load_sibling("rule_models", "core/rule_models.py")

Step = _models.Step
Rule = _models.Rule

FORMAT_DATA = [item[0] for item in _GUI.COMPARE_NUMBER_FORMATS]
FORMAT_REGEX = {data: regex for data, _label, regex, _hint in _GUI.COMPARE_NUMBER_FORMATS}


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _form(params):
    step = Step("compare", dict(params))
    return _GUI._CompareStepForm(None, step, 0, None)


# ── A. 數值顯示 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,shown",
    [
        (55.0, "55"),
        (55.5, "55.5"),
        (55.1234, "55.1234"),
        (-12.0, "-12"),
        (0.0, "0"),
        (1.23456789012345, "1.23456789012345"),
    ],
    ids=["integer", "one_dp", "four_dp", "negative", "zero", "high_dp"],
)
def test_value_display_trims_meaningless_zeros(qapp, raw, shown):
    form = _form({"pattern": r"-?\d+\.?\d*", "operator": ">=", "value": raw})
    assert form._value.text() == shown, f"{raw!r} 顯示成 {form._value.text()!r}"
    assert form._value.value() == raw, "顯示格式化不得改變 widget 值"


def test_value_display_does_not_change_saved_value_or_precision(qapp):
    form = _form({"pattern": r"\d+", "operator": "==", "value": 55.0})
    form.save()
    assert form._step.params["value"] == 55.0

    form2 = _form({"pattern": r"\d+", "operator": ">=", "value": 1.23456789012345})
    assert form2._value.text() == "1.23456789012345"
    form2.save()
    assert form2._step.params["value"] == 1.23456789012345


def test_summary_uses_trimmed_number(qapp):
    summary = _GUI._step_summary(
        Step("compare", {"pattern": r"\d+", "operator": ">=", "value": 55.0})
    )
    assert summary.startswith(">= 55 "), summary


# ── B. 數字格式選單與相容性 ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "pattern,expected",
    [
        (r"-?\d+\.?\d*", "auto"),
        (r"-?\d+", "int"),
        (r"-?\d+\.\d+", "decimal"),
        (r"\d{2,4}", "custom"),
        ("", "custom"),
        ("  \\d+ ", "custom"),
    ],
    ids=["auto", "int", "decimal", "custom_regex", "empty", "whitespace"],
)
def test_pattern_maps_to_plain_language_option(qapp, pattern, expected):
    form = _form({"pattern": pattern, "operator": ">=", "value": 1.0})
    assert form._number_format.currentData() == expected


def test_default_format_regex_matches_core_default():
    """「一般數字」必須就是 core 的預設 pattern，語意不得被悄悄改掉。"""
    assert FORMAT_REGEX["auto"] == r"-?\d+\.?\d*"
    assert FORMAT_REGEX["auto"] == _GUI.COMPARE_DEFAULT_PATTERN


@pytest.mark.parametrize(
    "pattern",
    [r"-?\d+\.?\d*", r"\d{2,4}", "  \\d+  ", "", r"[A-Z]+(\\d+)"],
    ids=["default", "custom", "whitespace", "empty", "groups"],
)
def test_legacy_pattern_survives_open_and_save_verbatim(qapp, pattern):
    """開表單不動、直接存檔，舊規則的 pattern 必須逐字保留。"""
    form = _form({"pattern": pattern, "operator": ">=", "value": 1.0})
    form.save()
    assert form._step.params["pattern"] == pattern


def test_untouched_preset_stays_identical_string(qapp):
    for data in ("auto", "int", "decimal"):
        pattern = FORMAT_REGEX[data]
        form = _form({"pattern": pattern, "operator": ">=", "value": 1.0})
        form.save()
        assert form._step.params["pattern"] == pattern


@pytest.mark.parametrize("data", ["auto", "int", "decimal"])
def test_switch_to_preset_writes_that_preset_regex(qapp, data):
    form = _form({"pattern": r"\d{3}", "operator": ">=", "value": 1.0})
    form._number_format.setCurrentIndex(form._number_format.findData(data))
    form.save()
    assert form._step.params["pattern"] == FORMAT_REGEX[data]


def test_custom_draft_restored_after_switching_away(qapp):
    form = _form({"pattern": r"-?\d+\.?\d*", "operator": ">=", "value": 1.0})
    form._number_format.setCurrentIndex(form._number_format.findData("custom"))
    form._pattern.setText(r"\d{3}")
    form._pattern.textEdited.emit(r"\d{3}")  # 模擬使用者手動輸入
    form._number_format.setCurrentIndex(form._number_format.findData("int"))
    form.save()
    assert form._step.params["pattern"] == r"-?\d+"

    form._number_format.setCurrentIndex(form._number_format.findData("custom"))
    assert form._pattern.text() == r"\d{3}", "切回自訂必須還原使用者輸入"
    form.save()
    assert form._step.params["pattern"] == r"\d{3}"


def test_invalid_regex_shows_inline_error_without_rewriting(qapp):
    form = _form({"pattern": r"\d{3}", "operator": ">=", "value": 1.0})
    form._pattern.setText("(unclosed")
    form._pattern.textEdited.emit("(unclosed")
    form._validate_pattern()
    assert not form._pattern_error.isHidden(), "無效格式必須顯示白話錯誤"
    form.save()
    assert form._step.params["pattern"] == "(unclosed", "不得吞掉或改寫使用者輸入"

    form._pattern.setText(r"\d{3}")
    form._validate_pattern()
    assert form._pattern_error.isHidden(), "修好後錯誤提示必須消失"


# ── C. 實際匹配語意（core _handle_compare） ─────────────────────────────────


def _run_compare(ocr_text, pattern, operator=">=", value=0.0):
    """用 stub OCR 跑真規則引擎；回傳 (後續點擊, ctx)。"""
    import numpy as np

    ml = make_main_loop()
    clicks = []
    ml._send_click = lambda x, y, button="left", hold_ms=0: clicks.append((x, y)) or True
    ml._can_perform_action = lambda: True
    ml._is_tool_foreground = lambda: False
    ml._activate_window = lambda: True
    ml._ocr_region = lambda img, roi: [
        _OCR.OcrResult(text=ocr_text, x=0, y=0, w=10, h=10, confidence=0.95)
    ]
    ml._shadow_check_ocr = lambda *a, **k: None
    ctx = _ML.StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    params = {"pattern": pattern, "operator": operator, "value": value, "on_fail": "stop"}
    rule = Rule(
        id="r",
        name="規則",
        enabled=True,
        steps=[
            Step("compare", params),
            Step("click", {"target": "custom", "x": 10, "y": 10}),
        ],
    )
    ml._run_rule(rule, ctx.img, ctx.rect, ctx)
    return clicks, ctx


@pytest.mark.parametrize(
    "ocr_text,expected_number,condition_holds",
    [
        ("Lv.55", 55.0, True),
        ("55.5", 55.5, True),
        ("-12", -12.0, True),
    ],
    ids=["integer", "decimal", "negative"],
)
def test_auto_format_reads_integers_and_decimals(ocr_text, expected_number, condition_holds):
    clicks, ctx = _run_compare(ocr_text, FORMAT_REGEX["auto"], value=expected_number)
    assert ctx.matched_box is not None and ctx.matched_box["number"] == expected_number
    assert bool(clicks) is condition_holds


def test_int_format_does_not_take_decimal_part():
    """整數模式：「55.5」讀成 55（不吞掉小數部分成 555，也不讀 55.5）。"""
    clicks, ctx = _run_compare("55.5", FORMAT_REGEX["int"], operator="==", value=55.0)
    assert ctx.matched_box is not None
    assert ctx.matched_box["number"] == 55.0
    assert clicks == [(10, 10)]


def test_decimal_format_rejects_plain_integer():
    clicks, ctx = _run_compare("55", FORMAT_REGEX["decimal"], value=0.0)
    assert ctx.matched_box is None, "小數模式不應接受沒有小數點的數字"
    assert clicks == []


def test_decimal_format_accepts_decimal():
    clicks, ctx = _run_compare("55.5", FORMAT_REGEX["decimal"], value=55.5)
    assert ctx.matched_box is not None
    assert ctx.matched_box["number"] == 55.5
    assert clicks == [(10, 10)]


def test_percent_text_uses_plain_number_without_unit():
    """百分比沒有獨立選項：現行語意本來就只取數字（% 不會進 float）。"""
    clicks, ctx = _run_compare("26%", FORMAT_REGEX["auto"], value=26.0)
    assert ctx.matched_box is not None and ctx.matched_box["number"] == 26.0
    assert clicks == [(10, 10)]
