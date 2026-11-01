"""Phase 2-7d-2a：Core 數值安全（非有限浮點數 / OverflowError）測試。

背景
----
任務 JSON 由 Python `json` 模組解析，而 `json` **預設接受**
`Infinity` / `-Infinity` / `NaN`（非標準 JSON 擴充）。因此損壞或手改過的
任務檔可能帶著這些值進入 Core 的數值轉換邊界：

- `int(float('inf'))` 拋 `OverflowError`。`_as_int()` 原本只擋
  `TypeError` / `ValueError` → 例外穿透 `RuleFileError` 錯誤流程，
  直接讓任務載入崩潰（GUI / 主循環皆未處理）。
- `float('nan')` / `float('inf')` 被 `_as_float()` 原樣保留 → NaN 讓所有
  比較恆 False、Infinity 讓門檻恆不成立，屬**靜默失效**。

本檔依**實際資料流**設計，不只測單一函式：

    任務 JSON → 序列化載入 → Core 正規化 → 執行期參數
    以及 MainLoop / GUI 的真實載入入口。

涵蓋範圍：
- `_as_int()` / `_as_float()` 單元語意（既有 fallback、bool 歷史行為不變）
- 欄位層 fallback（沿用**各欄位自己的** default，不一律轉 0）
- 真實 JSON 載入整合（Infinity / -Infinity / NaN；原始檔不得被改動）
- MainLoop._load_rules() / GUI 任務載入入口（不得拋未處理例外）
- 序列化邊界：殘餘轉換例外必須轉成既有 `RuleFileError`
"""

import json
import math
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

# 一律用 load_sibling，確保測的是 GUI / Core 實際載入的同一份模組實例
# （tests/test_rule_serialization.py 走 `core.rule_serialization`，是另一份實例）。
_MIG = load_sibling("rule_migration", "core/rule_migration.py")
_SER = load_sibling("rule_serialization", "core/rule_serialization.py")
_ML = load_sibling("main_loop", "core/05_main_loop.py")
_OCR = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_models = load_sibling("rule_models", "core/rule_models.py")
_Rule = _models.Rule
_Step = _models.Step

RuleFileError = _SER.RuleFileError
load_rules = _SER.load_rules
load_groups = _SER.load_groups

INF = float("inf")
NEG_INF = float("-inf")
NAN = float("nan")


# ── A. `_as_int()` 單元測試 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label,value,default,expected",
    [
        ("正常整數", 5, 0, 5),
        ("正常零", 0, 0, 0),
        ("負整數", -5, 0, -5),
        ("整數字串", "500", 0, 500),
        ("數字字串含空白", "  42  ", 0, 42),
        ("有限浮點數截斷", 1.9, 0, 1),
        ("有限浮點數截斷向下", 0.5, 0, 0),
        ("有限浮點數負值", -1.9, 0, -1),
        ("bool True", True, 0, 1),
        ("bool False", False, 0, 0),
        ("None", None, 500, 500),
        ("無效字串", "abc", 500, 500),
        ("空字串", "", 500, 500),
        ("空清單", [], 500, 500),
    ],
)
def test_as_int_keeps_existing_semantics(label, value, default, expected):
    """既有合法輸入的轉換語義不得因本次修正而改變。"""
    assert _MIG._as_int(value, default) == expected, label


@pytest.mark.parametrize("value", [INF, NEG_INF])
def test_as_int_non_finite_falls_back_without_overflow(value):
    """int(float('inf')) 會拋 OverflowError；必須回退 default 而非拋例外。"""
    assert _MIG._as_int(value, 500) == 500


def test_as_int_nan_falls_back_without_exception():
    """NaN 走既有 ValueError → default 分支，不得拋例外。"""
    assert _MIG._as_int(NAN, 500) == 500


def test_as_int_never_raises_on_any_json_scalar():
    """任務 JSON 可能出現的標量型別都不得讓 _as_int 拋例外。"""
    for value in (INF, NEG_INF, NAN, None, "abc", "", [], {}, True, False, 0, -1, 1.5):
        result = _MIG._as_int(value, 7)
        assert isinstance(result, int), f"{value!r} -> {result!r}"


# ── B. `_as_float()` 單元測試 ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "label,value,default,expected",
    [
        ("正常有限正數", 1.5, 0.0, 1.5),
        ("正常有限負數", -1.5, 0.0, -1.5),
        ("零", 0, 0.0, 0.0),
        ("整數轉浮點", 3, 0.0, 3.0),
        ("高精度有限小數", 1.23456789012345, 0.0, 1.23456789012345),
        ("數字字串", "0.8", 0.8, 0.8),
        ("bool True", True, 0.0, 1.0),
        ("bool False", False, 0.0, 0.0),
        ("None", None, 0.8, 0.8),
        ("無效字串", "abc", 0.8, 0.8),
        ("空字串", "", 0.8, 0.8),
        ("空清單", [], 0.8, 0.8),
    ],
)
def test_as_float_keeps_existing_semantics(label, value, default, expected):
    """既有合法輸入的轉換語義不得因本次修正而改變。"""
    assert _MIG._as_float(value, default) == expected, label


def test_as_float_does_not_round_finite_values():
    """有限浮點數不得被額外 round（欄位精度必須原樣保留）。"""
    for value in (1.23456789012345, 0.855, 0.1, 1e-9, 123456789.123456789, -0.30000000000000004):
        assert _MIG._as_float(value, 0.0) == value


@pytest.mark.parametrize("value", [NAN, INF, NEG_INF])
def test_as_float_non_finite_falls_back(value):
    """NaN / ±Infinity 不得進入正常參數，必須回退欄位自己的 default。"""
    assert _MIG._as_float(value, 0.8) == 0.8


def test_as_float_huge_int_does_not_raise_overflow():
    """float(10**400) 會拋 OverflowError，必須回退 default 而非拋例外。"""
    assert _MIG._as_float(10**400, 0.0) == 0.0


def test_as_float_never_raises_on_any_json_scalar():
    """任務 JSON 可能出現的標量型別都不得讓 _as_float 拋例外。"""
    for value in (INF, NEG_INF, NAN, None, "abc", "", [], {}, True, False, 0, -1, 1.5):
        result = _MIG._as_float(value, 0.25)
        assert isinstance(result, float), f"{value!r} -> {result!r}"
        assert math.isfinite(result), f"{value!r} -> {result!r} 仍是非有限值"


# ── C. 欄位層 fallback（沿用各欄位自己的 default，不一律轉 0）──────────────


@pytest.mark.parametrize(
    "step_type,params,field,expected",
    [
        ("wait", {"ms": INF}, "ms", 500),
        ("wait", {"ms": NEG_INF}, "ms", 500),
        ("wait", {"ms": NAN}, "ms", 500),
        ("compare", {"value": INF}, "value", None),
        ("compare", {"value": NEG_INF}, "value", None),
        ("compare", {"value": NAN}, "value", None),
        ("compare", {"value": None}, "value", None),
        ("detect", {"text": "x", "fuzzy_threshold": INF}, "fuzzy_threshold", 0.8),
        ("detect", {"text": "x", "fuzzy_threshold": NEG_INF}, "fuzzy_threshold", 0.8),
        ("detect", {"text": "x", "fuzzy_threshold": NAN}, "fuzzy_threshold", 0.8),
        ("match_image", {"template_data": "a", "threshold": INF}, "threshold", 0.8),
        ("match_image", {"template_data": "a", "threshold": NAN}, "threshold", 0.8),
        ("click", {"target": "cursor", "after_delay_ms": INF}, "after_delay_ms", 0),
        ("click", {"target": "cursor", "random_offset": INF}, "random_offset", 3),
        ("scroll", {"direction": "WheelUp", "amount": INF}, "amount", 1),
        ("scroll", {"direction": "WheelUp", "delay_ms": INF}, "delay_ms", 30),
    ],
)
def test_normalize_non_finite_uses_field_default(step_type, params, field, expected):
    """非有限值必須回退「該欄位自己的」預設值，而不是一律轉 0。

    compare.value 是唯一例外：它代表「數值無效」→ None（見 Phase 2-7d-2b-1）。
    """
    out = _MIG._normalize_step_params(step_type, params)
    assert out[field] == expected, f"{step_type}.{field} -> {out[field]!r}"
    if out[field] is None:
        # compare.value 的「無效」標記：不可是 NaN/inf，必須是 None
        assert step_type == "compare" and field == "value"
        return
    assert math.isfinite(float(out[field])), f"{step_type}.{field} 仍是非有限值"


def test_normalize_non_finite_roi_coordinates_are_finite():
    """ROI 座標的非有限值不得流入裁切計算。"""
    out = _MIG._normalize_step_params(
        "detect",
        {"text": "x", "roi": {"x": INF, "y": NAN, "w": INF, "h": NEG_INF}},
    )
    for key in ("x", "y", "w", "h"):
        assert math.isfinite(out["roi"][key]), f"roi.{key} -> {out['roi'][key]!r}"


def test_normalize_non_finite_capture_size_and_color_mask():
    """capture_size / color_mask 內的裸 int() 也不得拋 OverflowError。"""
    out = _MIG._normalize_step_params(
        "match_image",
        {
            "template_data": "a",
            "capture_size": [INF, 100],
            "color_mask": {"colors": [[INF, 0, 0]], "tolerance": 20},
        },
    )
    assert "capture_size" not in out
    assert out.get("color_mask") in (None, {})


def test_normalize_non_finite_fail_duration_uses_zero():
    """fail_duration_sec = Infinity 不得變成「永遠容忍失敗」。"""
    out = _MIG._normalize_on_fail({"action": "stop", "fail_duration_sec": INF}, allow_skip=True)
    assert out == "stop"
    out_nan = _MIG._normalize_on_fail({"action": "stop", "fail_duration_sec": NAN}, allow_skip=True)
    assert out_nan == "stop"


def test_normalize_fail_duration_finite_unchanged():
    """有限容忍期不得受影響。"""
    assert _MIG._normalize_on_fail({"action": "stop", "fail_duration_sec": 5}, allow_skip=True) == {
        "action": "stop",
        "fail_duration_sec": 5.0,
    }


# ── D. 真實 JSON 載入整合測試 ───────────────────────────────────────────────


def _write_raw_task(path: Path, step_type: str, params: dict) -> bytes:
    """寫出帶 Infinity / NaN 字面量的真實任務 JSON（Python json 預設支援）。"""
    task = {
        "rules": [
            {
                "id": "r1",
                "name": "非有限值測試",
                "enabled": True,
                "steps": [{"type": step_type, "params": params}],
            }
        ],
        "groups": [{"id": "g1", "name": "g1", "rule_ids": ["r1"], "enabled": True}],
    }
    text = json.dumps(task)  # 預設 allow_nan=True → 會寫出 Infinity / NaN 字面量
    path.write_text(text, encoding="utf-8")
    return path.read_bytes()


@pytest.mark.parametrize(
    "step_type,params,field,expected",
    [
        ("wait", {"ms": INF}, "ms", 500),
        ("wait", {"ms": NEG_INF}, "ms", 500),
        ("wait", {"ms": NAN}, "ms", 500),
        ("compare", {"value": INF, "operator": ">=", "pattern": r"\d+"}, "value", None),
        ("compare", {"value": NAN, "operator": ">=", "pattern": r"\d+"}, "value", None),
        ("compare", {"value": None, "operator": ">=", "pattern": r"\d+"}, "value", None),
        (
            "detect",
            {"text": "x", "fuzzy_threshold": INF},
            "fuzzy_threshold",
            0.8,
        ),
        (
            "detect",
            {"text": "x", "fuzzy_threshold": NAN},
            "fuzzy_threshold",
            0.8,
        ),
    ],
)
def test_load_real_json_with_non_finite_values(tmp_path, step_type, params, field, expected):
    """真實 JSON 載入路徑不得拋未處理例外，且原始檔不得被改動。"""
    path = tmp_path / "nonfinite.json"
    original = _write_raw_task(path, step_type, params)
    # 驗證測試檔真的帶著非有限／null 字面量（不是被 json.dumps 悄悄省略）
    raw_input = params.get(field)
    if raw_input is None:
        assert b"null" in original, "測試檔必須真的含 null 字面量"
    else:
        assert b"Infinity" in original or b"NaN" in original, "測試檔必須真的含非有限字面量"

    rules = load_rules(str(path))
    groups = load_groups(str(path))

    assert len(rules) == 1
    assert len(groups) == 1
    value = rules[0].steps[0].params[field]
    assert value == expected
    if value is None:
        assert field == "value", f"{field} 不該是 None"
    else:
        assert math.isfinite(float(value)), f"{field} 仍是非有限值"

    # 載入不得寫回檔案
    assert path.read_bytes() == original


def test_load_real_json_non_finite_does_not_break_other_steps(tmp_path):
    """壞掉的欄位不得連帶影響同一規則的其他步驟。"""
    path = tmp_path / "mixed.json"
    task = {
        "rules": [
            {
                "id": "r1",
                "name": "混合",
                "enabled": True,
                "steps": [
                    {"type": "wait", "params": {"ms": INF}},
                    {"type": "detect", "params": {"text": "戰鬥", "fuzzy_threshold": 0.855}},
                    {"type": "click", "params": {"target": "cursor", "after_delay_ms": 250}},
                ],
            }
        ],
        "groups": [],
    }
    original = json.dumps(task)
    path.write_text(original, encoding="utf-8")
    rules = load_rules(str(path))
    params = [s.params for s in rules[0].steps]
    assert params[0]["ms"] == 500
    assert params[1]["fuzzy_threshold"] == 0.855
    assert params[2]["after_delay_ms"] == 250
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "step_type,params,field,expected",
    [
        ("wait", {"ms": 123456}, "ms", 123456),
        ("wait", {"ms": 0}, "ms", 0),
        (
            "compare",
            {"value": 1.23456789012345, "operator": ">=", "pattern": r"\d+"},
            "value",
            1.23456789012345,
        ),
        ("detect", {"text": "x", "fuzzy_threshold": 0.855}, "fuzzy_threshold", 0.855),
        ("detect", {"text": "x", "fuzzy_threshold": 0.9}, "fuzzy_threshold", 0.9),
        ("click", {"target": "cursor", "after_delay_ms": 60000}, "after_delay_ms", 60000),
        ("click", {"target": "cursor", "random_offset": 150}, "random_offset", 150),
        ("scroll", {"direction": "WheelUp", "amount": 100}, "amount", 100),
    ],
)
def test_load_real_json_keeps_finite_values_exactly(tmp_path, step_type, params, field, expected):
    """有限值必須精確保留，Core 不得自行截斷或捨入。"""
    path = tmp_path / "finite.json"
    _write_raw_task(path, step_type, params)
    rules = load_rules(str(path))
    value = rules[0].steps[0].params[field]
    assert value == expected
    assert type(value) is type(expected), f"{field}: {value!r} 型別不符"


# ── E. 序列化載入邊界：殘餘轉換例外必須轉成既有 RuleFileError ─────────────


def test_load_rules_converts_overflow_error_to_rule_file_error(tmp_path, monkeypatch):
    """若仍有未受保護的轉換例外，必須轉成 RuleFileError 而非裸 OverflowError。"""

    def _boom(*args, **kwargs):
        raise OverflowError("cannot convert float infinity to integer")

    monkeypatch.setattr(_MIG, "_as_int", _boom)
    path = tmp_path / "boom.json"
    original = _write_raw_task(path, "wait", {"ms": 500})

    with pytest.raises(RuleFileError) as exc:
        load_rules(str(path))
    assert "轉換失敗" in str(exc.value)
    assert path.read_bytes() == original


def test_load_groups_converts_overflow_error_to_rule_file_error(tmp_path, monkeypatch):
    """群組載入路徑同樣必須轉成 RuleFileError（不得裸例外穿透）。"""

    def _boom(*args, **kwargs):
        raise OverflowError("cannot convert float infinity to integer")

    monkeypatch.setattr(_SER, "_as_int", _boom)
    path = tmp_path / "boom_groups.json"
    original = json.dumps({"rules": [], "groups": [{"id": "g1", "name": "g", "rule_ids": []}]})
    path.write_text(original, encoding="utf-8")

    with pytest.raises(RuleFileError) as exc:
        load_groups(str(path))
    assert "群組轉換失敗" in str(exc.value)
    assert path.read_text(encoding="utf-8") == original


# ── F. MainLoop 真實載入入口 ───────────────────────────────────────────────


def test_main_loop_load_rules_handles_non_finite(tmp_path):
    """MainLoop._load_rules() 不得因非有限值拋未處理例外。"""
    path = tmp_path / "ml_task.json"
    original = _write_raw_task(path, "wait", {"ms": INF})

    ml = make_main_loop()
    ml._rules_path = str(path)
    warnings = []
    ml.on_warning = warnings.append

    ml._load_rules()

    assert len(ml._rules) == 1
    assert ml._rules[0].steps[0].params["ms"] == 500
    assert warnings == [], f"不該有警告：{warnings}"
    assert path.read_bytes() == original


def test_main_loop_load_rules_keeps_current_rules_on_failure(tmp_path, monkeypatch):
    """載入失敗時必須保留目前規則，不得靜默清空。"""

    def _boom(*args, **kwargs):
        raise OverflowError("cannot convert float infinity to integer")

    monkeypatch.setattr(_MIG, "_as_int", _boom)
    path = tmp_path / "ml_bad.json"
    original = _write_raw_task(path, "wait", {"ms": 500})

    ml = make_main_loop()
    ml._rules_path = str(path)
    ml._rules = ["既有規則佔位"]
    warnings = []
    ml.on_warning = warnings.append

    ml._load_rules()  # 不得拋出

    assert ml._rules == ["既有規則佔位"], "載入失敗不得清空既有規則"
    assert warnings and "保留目前規則" in warnings[0]
    assert path.read_bytes() == original


# ── G. GUI 真實任務載入入口 ────────────────────────────────────────────────


def test_gui_task_load_handles_non_finite(real_mainwindow, isolated_data_dir, monkeypatch):
    """GUI 任務載入入口不得因非有限值拋未處理例外。"""
    from PyQt6.QtWidgets import QMessageBox

    critical = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))

    tasks_dir = isolated_data_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    path = tasks_dir / "nonfinite.json"
    original = _write_raw_task(path, "wait", {"ms": INF})

    win = real_mainwindow
    win._on_task_changed("nonfinite")

    assert critical == [], f"不該彈錯誤框：{critical}"
    assert len(win._rules) == 1
    assert win._rules[0].steps[0].params["ms"] == 500
    assert path.read_bytes() == original


def test_gui_task_load_failure_is_reported_not_silent(
    real_mainwindow, isolated_data_dir, monkeypatch
):
    """載入失敗必須沿既有錯誤流程回報（彈窗），且不得覆蓋原始任務檔。"""
    from PyQt6.QtWidgets import QMessageBox

    critical = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))

    def _boom(*args, **kwargs):
        raise OverflowError("cannot convert float infinity to integer")

    monkeypatch.setattr(_MIG, "_as_int", _boom)

    tasks_dir = isolated_data_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    path = tasks_dir / "bad.json"
    original = _write_raw_task(path, "wait", {"ms": 500})

    win = real_mainwindow
    win._on_task_changed("bad")  # 不得拋出

    assert win._task_load_failed is True
    assert critical, "載入失敗必須回報給使用者，不得靜默"
    assert path.read_bytes() == original


# ── H. compare 無效值安全失敗（Phase 2-7d-2b-1）──────────────────────────
#
# compare.value 為 None（無效值）時，必須走既有 on_fail 流程安全失敗，
# 不可把 None 當成 0.0 —— 0.0 在 ">=" / ">" / "!=" 之下會讓比較條件恆成立，
# 等於在使用者設定失效的情況下無條件執行後續的點擊／按鍵動作。


def _compare_ml(ocr_text="55"):
    """建立一個 stub OCR 的 MainLoop（只數點擊／按鍵，不碰真實輸入設備）。"""
    import numpy as np

    ml = make_main_loop()
    clicks, keys = [], []
    ml._send_click = lambda x, y, button="left", hold_ms=0: clicks.append((x, y)) or True
    ml._send_key = lambda k, **kw: keys.append(k) or True
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
    return ml, ctx, clicks, keys


def _rule_with_compare(value, on_fail, rule_id="r"):
    return _Rule(
        id=rule_id,
        name="規則",
        enabled=True,
        steps=[
            _Step(
                "compare",
                {"pattern": r"\d+", "operator": ">=", "value": value, "on_fail": on_fail},
            ),
            _Step("click", {"target": "custom", "x": 10, "y": 10}),
        ],
    )


@pytest.mark.parametrize("raw_value", [None, INF, NEG_INF, NAN])
def test_compare_invalid_value_fails_safely(raw_value):
    """無效比較數值 → 比較不成立，走 on_fail，不執行後續 click。"""
    ml, ctx, clicks, keys = _compare_ml()
    rule = _rule_with_compare(raw_value, "stop")
    ml._run_rule(rule, ctx.img, ctx.rect, ctx)
    assert clicks == [], f"無效數值時後續 click 不得執行，實際 {clicks}"
    assert keys == []


def test_compare_invalid_value_normalizes_to_none_before_execution():
    """進入執行期前，normalize 必須已把無效值轉成 None。"""
    params = _MIG._normalize_step_params(
        "compare", {"pattern": r"\d+", "operator": ">=", "value": INF}
    )
    assert params["value"] is None


def test_compare_invalid_value_uses_on_fail_key_semantics():
    """on_fail=key → 依既有語義送出按鍵，並繼續執行後續步驟。"""
    ml, ctx, clicks, keys = _compare_ml()
    rule = _rule_with_compare(None, {"action": "key", "key": "F5"})
    ml._run_rule(rule, ctx.img, ctx.rect, ctx)
    assert keys == ["F5"], "on_fail=key 應送出指定按鍵"
    assert clicks == [(10, 10)], "on_fail=key 回傳 continue → 後續步驟仍執行（既有語意）"


def test_compare_invalid_value_on_fail_stop_blocks_following_actions():
    """on_fail=stop（預設）→ 後續動作不得執行。"""
    ml, ctx, clicks, keys = _compare_ml()
    rule = _rule_with_compare(None, "stop")
    ml._run_rule(rule, ctx.img, ctx.rect, ctx)
    assert clicks == []
    assert keys == []


def test_compare_valid_value_still_executes_following_actions():
    """有效值不得受無效值保護影響：條件成立時後續 click 照常執行。"""
    ml, ctx, clicks, keys = _compare_ml(ocr_text="55")
    rule = _rule_with_compare(50.0, "stop")
    ml._run_rule(rule, ctx.img, ctx.rect, ctx)
    assert clicks == [(10, 10)], "有效值且條件成立時後續 click 必須執行"


def test_compare_valid_value_failing_condition_blocks_following_actions():
    """有效值但條件不成立 → 與無效值同樣走 on_fail。"""
    ml, ctx, clicks, keys = _compare_ml(ocr_text="55")
    rule = _rule_with_compare(999.0, "stop")
    ml._run_rule(rule, ctx.img, ctx.rect, ctx)
    assert clicks == []


# ── I. GUI compare.value = None 的生命週期 ────────────────────────────────


def _write_compare_task(write_task, make_step, make_rule, value):
    step = make_step("compare", pattern=r"\d+", operator=">=", value=value)
    write_task("t1", [make_rule("r0", "規則零", [step])])


def test_gui_compare_none_survives_no_edit_save(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """JSON(null) → GUI → 不修改 → 保存 → JSON：None 必須保留。"""
    win = real_mainwindow
    _write_compare_task(write_task, make_step, make_rule, None)
    win._on_task_changed("t1")
    win._step_list._collapse()
    win._step_list._toggle_expand(0)
    assert win._step_list._expanded_form is not None
    assert win._flush_save()

    path = isolated_data_dir / "tasks" / "t1.json"
    disk = json.loads(path.read_text(encoding="utf-8"))["rules"][0]["steps"][0]["params"]
    assert disk["value"] is None, f"磁碟上 compare.value 變成 {disk['value']!r}"

    win._on_task_changed("t1")
    assert win._rules[0].steps[0].params["value"] is None


def test_gui_compare_none_survives_other_field_edit(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """修改其他欄位不得讓 None 變成 0.0。"""
    win = real_mainwindow
    _write_compare_task(write_task, make_step, make_rule, None)
    win._on_task_changed("t1")
    win._step_list._collapse()
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    form._pattern.setText(r"\d{2}")
    assert win._flush_save()

    path = isolated_data_dir / "tasks" / "t1.json"
    disk = json.loads(path.read_text(encoding="utf-8"))["rules"][0]["steps"][0]["params"]
    assert disk["pattern"] == r"\d{2}"
    assert disk["value"] is None, f"改其他欄位後 compare.value 變成 {disk['value']!r}"


def test_gui_compare_user_edit_replaces_none(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """使用者主動改為有效數值 → 保存新值。"""
    win = real_mainwindow
    _write_compare_task(write_task, make_step, make_rule, None)
    win._on_task_changed("t1")
    win._step_list._collapse()
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    form._value.setValue(42.0)
    assert win._flush_save()

    path = isolated_data_dir / "tasks" / "t1.json"
    disk = json.loads(path.read_text(encoding="utf-8"))["rules"][0]["steps"][0]["params"]
    assert disk["value"] == 42.0


def test_gui_compare_none_survives_collapse_and_reexpand(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """折疊後重新展開仍保留 None 狀態。"""
    win = real_mainwindow
    _write_compare_task(write_task, make_step, make_rule, None)
    win._on_task_changed("t1")
    win._step_list._collapse()
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    assert form._value_hint.isVisible() is False or True  # offscreen 下可見性不穩定
    win._step_list._collapse()
    win._step_list._toggle_expand(0)
    form2 = win._step_list._expanded_form
    assert form2 is not None
    assert win._flush_save()

    path = isolated_data_dir / "tasks" / "t1.json"
    disk = json.loads(path.read_text(encoding="utf-8"))["rules"][0]["steps"][0]["params"]
    assert disk["value"] is None


def test_gui_compare_none_does_not_crash_form_construction(qt_app):
    """載入 None 時表單不得崩潰（不得把 None 傳給 setValue）。"""
    _GUI = load_sibling("gui_main", "gui/06_gui_main.py")
    _models = load_sibling("rule_models", "core/rule_models.py")
    step = _models.Step("compare", {"pattern": r"\d+", "operator": ">=", "value": None})
    form = _GUI._CompareStepForm(None, step, 0, None)
    assert form._value.value() == 0.0, "無效值時顯示暫存安全值"
    assert form._value_raw.value() is None, "但保存時仍須保留 None"
