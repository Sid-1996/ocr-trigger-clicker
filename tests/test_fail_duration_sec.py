"""fail_duration_sec（失敗容忍期）資料流測試。

背景
----
GUI 的 detect / match_image / compare 表單會寫入
`{"action": "stop", "fail_duration_sec": N}`（N>0 代表「持續失敗 N 秒」
的容忍期，期間內不執行失敗動作）。

但 Core 載入時的 `core/rule_migration._normalize_on_fail()` 原本把
`action == "stop"` 一律壓成裸字串 `"stop"`，於是：

    GUI 設定容忍期 → 存檔（JSON 正確）→ 重新載入 → 正規化丟棄容忍期
    → GUI 顯示 0 → 下次存檔把 0 寫回 → 使用者設定永久遺失

本檔依**實際資料流**設計，不只測單一函式回傳值：

    GUI 欄位回填 → GUI 保存 → JSON round-trip → Core 正規化 → Core 執行期

涵蓋範圍：
- Core 正規化層（根因）
- GUI 三個有 on_fail 編輯器的表單
- JSON round-trip（Step → Rule → dict → Rule → Step）
- Core 執行期容忍期行為
- 邊界值與舊任務相容性
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from conftest import make_main_loop  # noqa: E402

from _loader import load_sibling  # noqa: E402
from core.rule_models import Rule, Step  # noqa: E402

_GUI = load_sibling("gui_main", "gui/06_gui_main.py")
_MIG = load_sibling("rule_migration", "core/rule_migration.py")
_SER = load_sibling("rule_serialization", "core/rule_serialization.py")
_ML = load_sibling("main_loop", "core/05_main_loop.py")
_TMPL = load_sibling("template_matching", "core/11_template_matching.py")

StepContext = _ML.StepContext

# 有 on_fail（失敗處理）編輯器的三種 step type
_ON_FAIL_TYPES = ("detect", "match_image", "compare")

# GUI 失敗動作下拉選單的 6 種 action（順序與程式一致）
_ACTIONS = ("stop", "advance", "skip", "jump", "key", "notify")

# GUI 容忍期數值框的實際限制（gui/06_gui_main.py _of_fail_duration）
_SPIN_MIN = 0.0
_SPIN_MAX = 30.0
_SPIN_DECIMALS = 1


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _b64_template() -> str:
    return _TMPL.img_to_b64(np.zeros((8, 8, 3), dtype=np.uint8))


def _base_params(kind: str) -> dict:
    if kind == "detect":
        return {
            "text": "關鍵字",
            "roi": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.2},
            "match_mode": "fuzzy",
            "fuzzy_threshold": 0.8,
        }
    if kind == "match_image":
        return {"template_data": _b64_template(), "threshold": 0.9}
    if kind == "compare":
        return {
            "roi": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.2},
            "pattern": r"-?\d+",
            "operator": ">=",
            "value": 1,
        }
    raise ValueError(kind)


def _make_form(kind: str, on_fail, qapp):
    """建立帶有指定 on_fail 的 Step 表單（parent_list 傳 None，與既有測試一致）。"""
    params = _base_params(kind)
    params["on_fail"] = on_fail
    step = Step(type=kind, params=params)
    if kind == "detect":
        form = _GUI._DetectStepForm(None, step, 0, None)
    elif kind == "match_image":
        form = _GUI._MatchImageStepForm(None, step, 0, None)
    elif kind == "compare":
        form = _GUI._CompareStepForm(None, step, 0, None)
    else:
        raise ValueError(kind)
    qapp.processEvents()
    return form, step


def _set_action(form, action: str) -> None:
    idx = form._of_action.findData(action)
    assert idx >= 0, f"表單沒有 {action} 動作選項"
    form._of_action.setCurrentIndex(idx)


# ── Core 正規化層（根因） ────────────────────────────────────────────────────


def test_normalize_keeps_stop_with_tolerance():
    """stop + 容忍期必須保留，不得壓成裸字串。"""
    out = _MIG._normalize_on_fail({"action": "stop", "fail_duration_sec": 5}, allow_skip=True)
    assert out == {"action": "stop", "fail_duration_sec": 5.0}


def test_normalize_stop_without_tolerance_keeps_legacy_shape():
    """fd == 0 時維持既有向下相容寫法（純字串 "stop"），不得改變 JSON 形狀。"""
    assert _MIG._normalize_on_fail({"action": "stop"}, allow_skip=True) == "stop"
    assert (
        _MIG._normalize_on_fail({"action": "stop", "fail_duration_sec": 0}, allow_skip=True)
        == "stop"
    )
    assert _MIG._normalize_on_fail("stop", allow_skip=True) == "stop"


def test_normalize_invalid_tolerance_falls_back_to_stop():
    """非法型別的容忍期退回 0（純字串 "stop"），不得拋例外。"""
    assert (
        _MIG._normalize_on_fail({"action": "stop", "fail_duration_sec": "bad"}, allow_skip=True)
        == "stop"
    )
    assert (
        _MIG._normalize_on_fail({"action": "stop", "fail_duration_sec": -1}, allow_skip=True)
        == "stop"
    )
    assert (
        _MIG._normalize_on_fail({"action": "stop", "fail_duration_sec": None}, allow_skip=True)
        == "stop"
    )


@pytest.mark.parametrize("action", ["advance", "skip", "jump", "key", "notify"])
def test_normalize_other_actions_unchanged(action):
    """其他 action 的既有行為不得因本次修正而改變。"""
    raw = {
        "advance": {"action": "advance"},
        "skip": {"action": "skip", "skip_to": 2},
        "jump": {"action": "jump", "rule_id": "r1"},
        "key": {"action": "key", "key": "X"},
        "notify": {"action": "notify", "message": "m", "stop_groups": ["g"]},
    }[action]
    out = _MIG._normalize_on_fail(raw, allow_skip=True)
    assert out["action"] == action
    assert "fail_duration_sec" not in out


def test_normalize_unknown_action_still_becomes_stop():
    assert _MIG._normalize_on_fail({"action": "bogus"}, allow_skip=True) == "stop"
    assert _MIG._normalize_on_fail("bogus", allow_skip=True) == "stop"


def test_verify_on_fail_still_rejects_stop():
    """verify 層級的 on_fail 仍禁止 stop（不同層級，本次修正不得放寬）。"""
    assert _MIG._normalize_verify({"on_fail": "stop"}, "R") is None
    assert _MIG._normalize_verify({"on_fail": {"action": "stop"}}, "R") is None
    assert (
        _MIG._normalize_verify({"on_fail": {"action": "stop", "fail_duration_sec": 5}}, "R") is None
    )


@pytest.mark.parametrize("kind", _ON_FAIL_TYPES)
def test_normalize_step_params_keeps_tolerance(kind):
    """三個有 on_fail 編輯器的 step type 在載入時都必須保留容忍期。"""
    params = _base_params(kind)
    params["on_fail"] = {"action": "stop", "fail_duration_sec": 5}
    out = _MIG._normalize_step_params(kind, params, rule_name="R")
    assert out["on_fail"] == {"action": "stop", "fail_duration_sec": 5.0}


# ── T1：GUI 欄位回填 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", _ON_FAIL_TYPES)
def test_gui_refills_tolerance_from_existing_step(kind, qapp):
    """載入既有 Step 時，容忍期欄位必須顯示原始值而非預設值。"""
    form, _step = _make_form(kind, {"action": "stop", "fail_duration_sec": 3.5}, qapp)
    try:
        assert form._of_fail_duration.value() == pytest.approx(3.5)
    finally:
        form.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("kind", _ON_FAIL_TYPES)
def test_gui_refills_tolerance_for_non_stop_action(kind, qapp):
    """非 stop 動作也帶容忍期時，欄位同樣必須回填。"""
    form, _step = _make_form(kind, {"action": "advance", "fail_duration_sec": 2.5}, qapp)
    try:
        assert form._of_fail_duration.value() == pytest.approx(2.5)
    finally:
        form.deleteLater()
        qapp.processEvents()


# ── T2：GUI 欄位保存 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", _ON_FAIL_TYPES)
def test_gui_saves_new_tolerance(kind, qapp):
    """使用者修改容忍期後保存，Step.params 必須是使用者設定的新值。"""
    form, step = _make_form(kind, {"action": "stop", "fail_duration_sec": 1.0}, qapp)
    try:
        form._of_fail_duration.setValue(7.5)
        form.save()
        assert step.params["on_fail"] == {"action": "stop", "fail_duration_sec": 7.5}
    finally:
        form.deleteLater()
        qapp.processEvents()


# ── T3：保存其他 on_fail 欄位時不得刪除容忍期 ───────────────────────────────


@pytest.mark.parametrize("kind", _ON_FAIL_TYPES)
@pytest.mark.parametrize("action", ["advance", "skip", "jump", "key", "notify"])
def test_gui_changing_action_keeps_tolerance(kind, action, qapp):
    """切換失敗動作後保存，容忍期不得被意外刪除或重設。"""
    form, step = _make_form(kind, {"action": "stop", "fail_duration_sec": 4.0}, qapp)
    try:
        _set_action(form, action)
        form.save()
        saved = step.params["on_fail"]
        assert isinstance(saved, dict)
        assert saved["action"] == action
        assert saved["fail_duration_sec"] == pytest.approx(4.0)
    finally:
        form.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("kind", _ON_FAIL_TYPES)
def test_gui_changing_action_back_to_stop_keeps_tolerance(kind, qapp):
    """從其他動作切回 stop 時，容忍期同樣不得遺失。"""
    form, step = _make_form(kind, {"action": "advance", "fail_duration_sec": 2.0}, qapp)
    try:
        _set_action(form, "stop")
        form.save()
        saved = step.params["on_fail"]
        assert saved["action"] == "stop"
        assert saved["fail_duration_sec"] == pytest.approx(2.0)
    finally:
        form.deleteLater()
        qapp.processEvents()


# ── T4：各種 action 的容忍期處理 ────────────────────────────────────────────


@pytest.mark.parametrize("kind", _ON_FAIL_TYPES)
def test_gui_stop_with_zero_tolerance_keeps_legacy_string(kind, qapp):
    """stop 且容忍期為 0 時維持既有寫法（純字串 "stop"）。"""
    form, step = _make_form(kind, {"action": "stop", "fail_duration_sec": 0}, qapp)
    try:
        form.save()
        assert step.params["on_fail"] == "stop"
    finally:
        form.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("kind", _ON_FAIL_TYPES)
def test_gui_all_actions_carry_tolerance(kind, qapp):
    """6 種動作都要把容忍期寫進去（stop>0 用 dict，其餘用 dict）。"""
    form, step = _make_form(kind, {"action": "stop", "fail_duration_sec": 6.0}, qapp)
    try:
        for action in _ACTIONS:
            _set_action(form, action)
            form.save()
            saved = step.params["on_fail"]
            assert isinstance(saved, dict), f"{action} 應寫成 dict"
            assert saved["action"] == action
            assert saved["fail_duration_sec"] == pytest.approx(6.0), f"{action} 遺失容忍期"
    finally:
        form.deleteLater()
        qapp.processEvents()


# ── T5：缺少欄位的舊任務 ────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", _ON_FAIL_TYPES)
@pytest.mark.parametrize("on_fail", ["stop", {"action": "stop"}, {"action": "advance"}])
def test_gui_missing_tolerance_falls_back_to_zero(kind, on_fail, qapp):
    """舊任務沒有容忍期時不得崩潰，欄位顯示 0。"""
    form, _step = _make_form(kind, on_fail, qapp)
    try:
        assert form._of_fail_duration.value() == pytest.approx(0.0)
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_legacy_stop_string_still_normalizes_to_stop():
    """舊任務的純字串 "stop" 載入後仍為 "stop"（既有相容契約）。"""
    assert (
        _MIG._normalize_step_params("detect", {"text": "x", "on_fail": "stop"}, "R")["on_fail"]
        == "stop"
    )


# ── T6：JSON round-trip ─────────────────────────────────────────────────────


def test_end_to_end_gui_write_then_reload_keeps_tolerance(qapp):
    """完整使用者情境：GUI 設定容忍期 → 序列化 → 重新載入 → GUI 仍顯示原值。

    這是缺陷的實際症狀（存檔後重開，任���期歸 0），
    只有把 GUI 與 Core 串起來才抓得到。
    """
    form, step = _make_form("detect", {"action": "stop", "fail_duration_sec": 1.0}, qapp)
    try:
        form._of_fail_duration.setValue(9.0)
        form.save()
    finally:
        form.deleteLater()

    raw = _SER._rule_to_dict(Rule(id="r_e2e", name="E2E", enabled=True, steps=[step]))
    reloaded = _SER._dict_to_rule(json.loads(json.dumps(raw, ensure_ascii=False)))

    form2, _step2 = _make_form("detect", reloaded.steps[0].params["on_fail"], qapp)
    try:
        assert form2._of_fail_duration.value() == pytest.approx(9.0)
    finally:
        form2.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("kind", _ON_FAIL_TYPES)
def test_json_roundtrip_preserves_tolerance(kind):
    """Step → Rule → JSON → reload → Step：非預設值不得遺失。"""
    params = _base_params(kind)
    params["on_fail"] = {"action": "stop", "fail_duration_sec": 8.0}
    rule = Rule(id="r1", name="RT", enabled=True, steps=[Step(type=kind, params=params)])

    raw = _SER._rule_to_dict(rule)
    # JSON 層（磁碟上的樣子）必須已含容忍期
    assert raw["steps"][0]["params"]["on_fail"]["fail_duration_sec"] == 8.0

    # 再走一次 JSON 序列化／反序列化，模擬存檔後重新載入
    reloaded = _SER._dict_to_rule(json.loads(json.dumps(raw, ensure_ascii=False)))
    assert reloaded.steps[0].params["on_fail"] == {"action": "stop", "fail_duration_sec": 8.0}


def test_json_roundtrip_legacy_stop_string_unchanged():
    """純字串 "stop" 的舊任務 round-trip 後仍為純字串（不得被改成 dict）。"""
    params = _base_params("detect")
    params["on_fail"] = "stop"
    rule = Rule(id="r2", name="RT2", enabled=True, steps=[Step(type="detect", params=params)])
    raw = _SER._rule_to_dict(rule)
    reloaded = _SER._dict_to_rule(json.loads(json.dumps(raw, ensure_ascii=False)))
    assert reloaded.steps[0].params["on_fail"] == "stop"


def test_shipped_task_json_normalize_unchanged():
    """既有任務檔載入後不得因本次修正而改變任何欄位。"""
    task_files = sorted((_root / "docs" / "tasks").glob("*.json"))
    assert task_files, "找不到 docs/tasks/*.json 供回歸比對"
    for path in task_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for raw_rule in data.get("rules", []):
            for raw_step in raw_rule.get("steps", []):
                stype = str(raw_step.get("type", ""))
                if stype not in _ON_FAIL_TYPES:
                    continue
                params = raw_step.get("params") or {}
                if "on_fail" not in params:
                    continue
                before = params["on_fail"]
                after = _MIG._normalize_step_params(stype, dict(params), rule_name="")["on_fail"]
                assert after == before, (
                    f"{path.name} 的 {stype} on_fail 被改變：{before!r} → {after!r}"
                )


# ── T7：Core 執行期 ─────────────────────────────────────────────────────────


def test_core_runtime_uses_tolerance_window():
    """容忍期 > 0：第一次失敗應記錄起始時間並回傳容忍期結果，而非立即執行失敗動作。"""
    ml = make_main_loop()
    ml._fail_since.clear()
    rule = Rule(id="r_tol", name="容忍期", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 10, "h": 10}
    )

    res = ml._handle_on_fail({"on_fail": {"action": "stop", "fail_duration_sec": 5.0}}, ctx, rule)
    key = f"r_tol:{ctx.step_idx}"

    assert res.action == "stop"
    assert key in ml._fail_since, "容忍期內必須記錄首次失敗時間"

    # 容忍期尚未到期 → 仍不執行失敗動作
    res2 = ml._handle_on_fail({"on_fail": {"action": "stop", "fail_duration_sec": 5.0}}, ctx, rule)
    assert res2.action == "stop"
    assert key in ml._fail_since

    # 容忍期已過 → 記錄被清掉，代表真的執行了失敗動作
    ml._fail_since[key] = time.monotonic() - 10.0
    ml._handle_on_fail({"on_fail": {"action": "stop", "fail_duration_sec": 5.0}}, ctx, rule)
    assert key not in ml._fail_since


def test_core_runtime_without_tolerance_fails_immediately():
    """容忍期缺省（0）：失敗動作立即執行，不應留下容忍期記錄。"""
    ml = make_main_loop()
    ml._fail_since.clear()
    rule = Rule(id="r_notol", name="無容忍期", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 10, "h": 10}
    )

    ml._handle_on_fail({"on_fail": "stop"}, ctx, rule)

    assert f"r_notol:{ctx.step_idx}" not in ml._fail_since


def test_core_runtime_tolerance_after_reload():
    """完整鏈路：GUI 寫入的 JSON 載入後，執行期仍讀得到容忍期。"""
    params = _base_params("detect")
    params["on_fail"] = {"action": "stop", "fail_duration_sec": 5.0}
    rule = Rule(id="r_chain", name="鏈路", enabled=True, steps=[Step(type="detect", params=params)])
    raw = _SER._rule_to_dict(rule)
    reloaded = _SER._dict_to_rule(json.loads(json.dumps(raw, ensure_ascii=False)))

    ml = make_main_loop()
    ml._fail_since.clear()
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 10, "h": 10}
    )
    ml._handle_on_fail(reloaded.steps[0].params, ctx, reloaded)

    assert f"r_chain:{ctx.step_idx}" in ml._fail_since


# ── T8：邊界值 ──────────────────────────────────────────────────────────────


def test_gui_spinbox_limits(qapp):
    """容忍期數值框的實際限制（不得自行創造新政策）。"""
    form, _step = _make_form("detect", {"action": "stop", "fail_duration_sec": 1.0}, qapp)
    try:
        assert form._of_fail_duration.minimum() == pytest.approx(_SPIN_MIN)
        assert form._of_fail_duration.maximum() == pytest.approx(_SPIN_MAX)
        assert form._of_fail_duration.decimals() == _SPIN_DECIMALS
    finally:
        form.deleteLater()


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0, 29.9, 30.0])
def test_gui_accepts_boundary_values(value, qapp):
    """邊界值可正常設定並保存。"""
    form, step = _make_form("detect", {"action": "stop", "fail_duration_sec": 1.0}, qapp)
    try:
        form._of_fail_duration.setValue(value)
        form.save()
        saved = step.params["on_fail"]
        if value == 0.0:
            assert saved == "stop"
        else:
            assert saved["fail_duration_sec"] == pytest.approx(value)
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_gui_clamps_value_above_spinbox_max(qapp):
    """超出數值框上限的值在 GUI 端被截到 30（GUI 既有行為，Core 不做上限裁切）。"""
    form, step = _make_form("detect", {"action": "stop", "fail_duration_sec": 1.0}, qapp)
    try:
        form._of_fail_duration.setValue(999.0)
        assert form._of_fail_duration.value() == pytest.approx(_SPIN_MAX)
        form.save()
        assert step.params["on_fail"]["fail_duration_sec"] == pytest.approx(_SPIN_MAX)
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_core_keeps_value_above_spinbox_max():
    """Core 不裁切上限：手寫 JSON 的大於 30 秒的值必須原樣保留。"""
    out = _MIG._normalize_step_params(
        "detect", {"text": "x", "on_fail": {"action": "stop", "fail_duration_sec": 120}}, "R"
    )
    assert out["on_fail"] == {"action": "stop", "fail_duration_sec": 120.0}
