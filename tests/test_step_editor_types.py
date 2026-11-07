"""Step Editor 的 Step type 覆蓋與 wait / jump 編輯表單測試。

背景
----
GUI 的「新增 Step」選單提供 11 種 type，但 `_StepListWidget._build_form()`
原本只有 9 個分支，缺 `wait` 與 `jump`：

- 新增 wait / jump step **可以成功**（選單有、`_add_step` 有），
- 但點編輯鈕時 `_build_form()` 回傳 None → **完全沒有反應**，
- `_WaitStepForm` / `_JumpStepForm` 兩個完整實作從未被實例化（死碼）。

本檔鎖住：
- 選單型別 ↔ 可編輯表單的對應（新增選項卻忘記接表單時必須失敗）
- wait / jump 的回填、保存、重新開啟、JSON round-trip
- 舊資料相容與其他 Step type 不受影響
"""

import ast
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402
from core.rule_models import Rule, RuleGroup, Step  # noqa: E402

_GUI = load_sibling("gui_main", "gui/06_gui_main.py")
_MIG = load_sibling("rule_migration", "core/rule_migration.py")
_SER = load_sibling("rule_serialization", "core/rule_serialization.py")
_INPUT = load_sibling("pynput_input", "core/03_pynput_input.py")

_GUI_SOURCE = _root / "gui" / "06_gui_main.py"

# wait 表單數值框的既有範圍（gui/06_gui_main.py _WaitStepForm）
_WAIT_MIN = 0
_WAIT_MAX = 60000
_WAIT_DEFAULT = 500


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


# ── 從程式碼取出「新增 Step 選單」實際提供的型別 ────────────────────────────


def _menu_step_types() -> tuple[str, ...]:
    """解析 GUI 原始碼，取出新增 Step 選單的 type 清單。

    選單是在 MainWindow 建構時就地建立的 QMenu，無法脫離主視窗單獨取得，
    因此以 AST 讀取該清單本體（來源即使用者實際看得到的選項）。
    """
    tree = ast.parse(_GUI_SOURCE.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "step_types" for t in node.targets):
            continue
        if not isinstance(node.value, ast.List):
            continue
        types = []
        for el in node.value.elts:
            if (
                isinstance(el, ast.Tuple)
                and el.elts
                and isinstance(el.elts[0], ast.Constant)
                and isinstance(el.elts[0].value, str)
            ):
                types.append(el.elts[0].value)
        if types:
            found.append(tuple(types))
    assert len(found) == 1, f"新增 Step 選單清單不唯一：{found}"
    return found[0]


def _build_form_branch_types() -> tuple[str, ...]:
    """解析 `_build_form()` 內的 type 分支。"""
    tree = ast.parse(_GUI_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "_StepListWidget":
            continue
        for m in node.body:
            if not isinstance(m, ast.FunctionDef) or m.name != "_build_form":
                continue
            types = []
            for sub in ast.walk(m):
                if not isinstance(sub, ast.If):
                    continue
                cmp = sub.test
                if (
                    isinstance(cmp, ast.Compare)
                    and isinstance(cmp.left, ast.Name)
                    and cmp.left.id == "t"
                    and len(cmp.comparators) == 1
                    and isinstance(cmp.comparators[0], ast.Constant)
                    and isinstance(cmp.comparators[0].value, str)
                ):
                    types.append(cmp.comparators[0].value)
            return tuple(types)
    raise AssertionError("找不到 _StepListWidget._build_form()")


# ── 共用 fixture ────────────────────────────────────────────────────────────


def _rules():
    return [
        Rule(id="r1", name="規則一", enabled=True, steps=[]),
        Rule(id="r2", name="規則二", enabled=True, steps=[]),
        Rule(id="r3", name="未分群規則", enabled=True, steps=[]),
    ]


def _groups():
    return [RuleGroup(id="g1", name="群組一", rule_ids=["r1", "r2"])]


@pytest.fixture
def step_list(qapp):
    """帶 providers 的 Step 清單元件（current rule = r1，故 r1 不可作為跳轉目標）。"""
    lst = _GUI._StepListWidget()
    lst.set_rules_provider(lambda: list(_rules()))
    lst.set_groups_provider(lambda: list(_groups()))
    lst.set_rule_id("r1")
    yield lst
    lst.deleteLater()
    qapp.processEvents()


def _params_for(step_type: str) -> dict:
    if step_type == "wait":
        return {"ms": _WAIT_DEFAULT}
    if step_type == "jump":
        return {"rule_id": ""}
    return {"on_fail": "stop"}


# ── 5-1：GUI Step type 覆蓋 ─────────────────────────────────────────────────


def test_add_menu_types_all_have_editor_form(step_list, qapp):
    """新增選單中每一種可新增的 Step type 都必須有對應的可編輯表單。

    未來新增 Step 選項卻忘記接通表單時，本測試必須失敗。
    """
    menu_types = _menu_step_types()
    assert "wait" in menu_types and "jump" in menu_types

    missing = []
    for step_type in menu_types:
        step = Step(type=step_type, params=_params_for(step_type))
        form = step_list._build_form(0, step)
        if form is None:
            missing.append(step_type)
        else:
            form.deleteLater()
    qapp.processEvents()
    assert not missing, f"選單可新增但沒有編輯表單：{missing}"


def test_build_form_branches_match_menu_types():
    """`_build_form()` 的分支集合必須與新增選單一致（不多不少）。"""
    assert set(_build_form_branch_types()) == set(_menu_step_types())


def test_unknown_step_type_returns_no_form_and_keeps_params(step_list):
    """未知型別：沒有表單，且不得清空或覆蓋原始 params。"""
    step = Step(type="bogus_type", params={"keep": "me", "on_fail": "stop"})
    assert step_list._build_form(0, step) is None
    assert step.params == {"keep": "me", "on_fail": "stop"}


@pytest.mark.parametrize(
    "step_type,expected_class",
    [
        ("detect", "_DetectStepForm"),
        ("match_image", "_MatchImageStepForm"),
        ("compare", "_CompareStepForm"),
        ("sum", "_SumStepForm"),
        ("click", "_ClickStepForm"),
        ("key", "_KeyStepForm"),
        ("drag", "_DragStepForm"),
        ("scroll", "_ScrollStepForm"),
        ("notify", "_NotifyStepForm"),
    ],
)
def test_existing_step_types_keep_their_form(step_list, qapp, step_type, expected_class):
    """既有 9 型別的表單選擇不得因本次接線而改變。"""
    step = Step(type=step_type, params=_params_for(step_type))
    form = step_list._build_form(0, step)
    assert form is not None
    assert type(form).__name__ == expected_class
    form.deleteLater()
    qapp.processEvents()


def test_drag_form_unset_end_saves_none_pair(step_list, qapp):
    step = Step(
        type="drag",
        params={"target": "custom", "x": 0.2, "y": 0.3, "dx": 10, "dy": 20},
    )
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        assert form._end_x is None
        assert form._end_y is None
        form.save()
        assert step.params["end_x"] is None
        assert step.params["end_y"] is None
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_form_partial_end_not_saved(step_list, qapp):
    step = Step(
        type="drag",
        params={"target": "custom", "x": 0.2, "y": 0.3, "dx": 10, "dy": 20},
    )
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        form._end_x_spin.setValue(0.3)
        assert step.params.get("end_x") is None
        assert step.params.get("end_y") is None
        form._end_y_spin.setValue(0.8)
        assert step.params["end_x"] == 0.3
        assert step.params["end_y"] == 0.8
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_form_manual_zero_end_saves_zero_pair(step_list, qapp):
    step = Step(
        type="drag",
        params={"target": "custom", "x": 0.2, "y": 0.3, "dx": 10, "dy": 20},
    )
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        form._end_x_spin.setValue(0.3)
        form._end_y_spin.setValue(0.8)
        form.save()
        assert step.params["end_x"] == 0.3
        assert step.params["end_y"] == 0.8
        form._end_x_spin.setValue(0.0)
        form._end_y_spin.setValue(0.0)
        form.save()
        assert step.params["end_x"] == 0.0
        assert step.params["end_y"] == 0.0
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_form_cancel_end_pick_keeps_values(step_list, qapp):
    step = Step(
        type="drag",
        params={
            "target": "custom",
            "x": 0.2,
            "y": 0.3,
            "dx": 10,
            "dy": 20,
            "end_x": 0.5,
            "end_y": 0.8,
        },
    )
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        assert form._end_x == 0.5
        assert form._end_y == 0.8
        form._pick_cb = lambda: None
        form._pick_end()
        assert form._end_x == 0.5
        assert form._end_y == 0.8
    finally:
        form.deleteLater()
        qapp.processEvents()


# ── 5-1b：Drag 終點資料邊界（第三階段）─────────────────────────────────────


def _drag_step(**end):
    params = {"target": "custom", "x": 0.2, "y": 0.3, "dx": 10, "dy": 20}
    params.update(end)
    return Step(type="drag", params=params)


def test_drag_end_state_helper():
    assert _GUI._drag_end_state(None, None) == "unset"
    assert _GUI._drag_end_state(None, 0.5) == "incomplete"
    assert _GUI._drag_end_state(0.5, None) == "incomplete"
    assert _GUI._drag_end_state("bad", 0.3) == "invalid"
    assert _GUI._drag_end_state(0.3, "bad") == "invalid"
    assert _GUI._drag_end_state(True, False) == "invalid"
    assert _GUI._drag_end_state(float("nan"), 0.3) == "invalid"
    assert _GUI._drag_end_state(0.3, float("inf")) == "invalid"
    assert _GUI._drag_end_state(10**400, 10**400) == "invalid"
    assert _GUI._drag_end_state(0, 0) == "ratio"
    assert _GUI._drag_end_state(0.5, 0) == "ratio"
    assert _GUI._drag_end_state(960, 540) == "pixel"
    assert _GUI._drag_end_state(1.5, 0.2) == "pixel"


def test_drag_end_spin_value_never_clamps():
    assert _GUI._end_spin_value(0.5) == 0.5
    assert _GUI._end_spin_value(0) == 0.0
    assert _GUI._end_spin_value(None) is None
    assert _GUI._end_spin_value("bad") is None
    assert _GUI._end_spin_value(True) is None
    assert _GUI._end_spin_value(float("nan")) is None
    assert _GUI._end_spin_value(float("inf")) is None
    assert _GUI._end_spin_value(10**400) is None
    assert _GUI._end_spin_value(960) is None
    assert _GUI._end_spin_value(-0.5) is None


def test_fmt_point_mixed_int_float_keeps_decimals():
    assert _GUI._fmt_point(0.5, 0) == "(50%,0%)"
    assert _GUI._fmt_point(0.5, 0.8) == "(50%,80%)"
    assert _GUI._fmt_point(0, 0) == "(0,0)"
    assert _GUI._fmt_point(960, 540) == "(960,540)"
    # 非法值原樣顯示，不拋例外
    assert _GUI._fmt_point("bad", 1) == "(bad,1)"


@pytest.mark.parametrize(
    "bad_end",
    [
        {"end_x": "bad", "end_y": 0.3},
        {"end_x": 10**400, "end_y": 10**400},
        {"end_x": float("nan"), "end_y": 0.3},
        {"end_x": float("inf"), "end_y": 0.3},
        {"end_x": True, "end_y": False},
    ],
)
def test_drag_form_invalid_end_does_not_crash(step_list, qapp, bad_end):
    step = _drag_step(**bad_end)
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        assert form._end_display_text() == _GUI.T("step_form.end_invalid")
        assert not form._end_x_spin.isEnabled()
        assert not form._end_y_spin.isEnabled()
        # 保存其他欄位可以，但不得改寫終點原始資料
        assert form.save() is True
        assert step.params["end_x"] is bad_end["end_x"]
        assert step.params["end_y"] is bad_end["end_y"]
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_form_pixel_end_is_readonly_and_preserved(step_list, qapp):
    step = _drag_step(end_x=960, end_y=540)
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        assert "960" in form._end_display_text()
        assert "540" in form._end_display_text()
        assert not form._end_x_spin.isEnabled()
        assert not form._end_y_spin.isEnabled()
        assert form.save() is True
        assert step.params["end_x"] == 960
        assert step.params["end_y"] == 540
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_form_partial_end_blocks_save_and_collapse(step_list, qapp):
    step = _drag_step()
    step_list.set_steps([step])
    step_list._toggle_expand(0)
    form = step_list._expanded_form
    assert form is not None
    form._end_x_spin.setValue(0.3)

    assert form.save() is False
    assert step.params.get("end_x") is None and step.params.get("end_y") is None
    assert not form._end_hint.isHidden()
    assert form._end_display_text() == _GUI.T("step_form.end_incomplete")

    # 收合必須被拒絕，表單與使用者輸入都要留著
    assert step_list._collapse() is False
    assert step_list._expanded_form is form
    assert form._end_x == 0.3

    # 補齊另一軸後即可保存與收合
    form._end_y_spin.setValue(0.8)
    assert step.params["end_x"] == 0.3
    assert step.params["end_y"] == 0.8
    assert form._end_hint.isHidden()
    assert step_list._collapse() is True
    assert step_list._expanded_form is None


def test_drag_form_complete_end_edit_one_axis_keeps_other(step_list, qapp):
    step = _drag_step(end_x=0.4, end_y=0.6)
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        form._end_x_spin.setValue(0.7)
        assert step.params["end_x"] == 0.7
        assert step.params["end_y"] == 0.6
        form._end_y_spin.setValue(0.9)
        assert step.params["end_x"] == 0.7
        assert step.params["end_y"] == 0.9
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_form_clear_end_restores_unset(step_list, qapp):
    step = _drag_step(end_x=0.4, end_y=0.6, end_roi_coord="client")
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        form._clear_end()
        assert step.params["end_x"] is None
        assert step.params["end_y"] is None
        assert "end_roi_coord" not in step.params
        assert form._end_display_text() == _GUI.T("step_form.end_unset")
        assert form._end_x_spin.isEnabled() and form._end_y_spin.isEnabled()
        # 清除後再手動輸入是新的終點（client 比例）
        form._end_x_spin.setValue(0.25)
        form._end_y_spin.setValue(0.75)
        assert step.params["end_roi_coord"] == "client"
        assert step.params["end_x"] == 0.25
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_form_pick_end_uses_own_coord_space(step_list, qapp):
    step = Step(
        type="drag",
        params={"target": "text_center", "x": 0.2, "y": 0.3, "dx": 10, "dy": 20},
    )
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        form._pick_cb = lambda: (0.25, 0.75)
        form._pick_end()
        assert step.params["end_x"] == 0.25
        assert step.params["end_y"] == 0.75
        assert step.params["end_roi_coord"] == "client"
        # 起點資料與座標系完全不受影響
        assert "roi_coord" not in step.params
        assert step.params["x"] == 0.2 and step.params["y"] == 0.3
        assert step.params["target"] == "text_center"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_form_pick_cancel_from_unset_stays_unset(step_list, qapp):
    step = _drag_step()
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        form._pick_cb = lambda: None
        form._pick_end()
        assert form._end_x is None and form._end_y is None
        assert step.params.get("end_x") is None and step.params.get("end_y") is None
        assert step.params.get("end_roi_coord") is None
        assert form._end_display_text() == _GUI.T("step_form.end_unset")
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_form_save_other_fields_when_end_unset(step_list, qapp):
    step = _drag_step()
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        form._dx.setValue(55)
        assert form.save() is True
        assert step.params["dx"] == 55
        assert step.params["end_x"] is None and step.params["end_y"] is None
    finally:
        form.deleteLater()
        qapp.processEvents()


# ── 5-1c：半套終點在「重建 / 替換表單」入口的保存保護（P2-1）───────────────
#
# 背景：`_DragStepForm.save()` 遇到 incomplete 終點會拒絕保存，但部分呼叫端
# 忽略 `_save_expanded()` / `get_steps()` 的失敗結果 → 使用者剛輸入的單軸終點
# 被靜默丟棄。以下測試鎖住「任何會重建或替換表單的操作都必須中止」。


def _open_partial_end(step_list, idx: int = 0):
    """展開 idx 的 drag 步驟，只填終點 X（Y 維持未設定）。"""
    step_list._toggle_expand(idx)
    form = step_list._expanded_form
    assert form is not None, "drag 表單必須展開"
    form._end_x_spin.setValue(0.4)
    assert form.save() is False, "半套終點必須被 save() 拒絕"
    return form


def test_step_list_partial_end_blocks_move_down(step_list):
    drag = _drag_step()
    step_list.set_steps([drag, Step(type="wait", params={"ms": 100})])
    form = _open_partial_end(step_list, 0)

    step_list._move_down(0)

    assert [s.type for s in step_list._steps] == ["drag", "wait"], "順序不得改變"
    assert step_list._expanded_idx == 0, "展開步驟不得改變"
    assert step_list._expanded_form is form, "表單不得被銷毀"
    assert form._end_x == 0.4 and form._end_y is None, "使用者輸入必須保留"
    assert not form._end_hint.isHidden(), "未完成提示必須保留"
    assert "end_x" not in drag.params, "半套終點不得寫入 params"


def test_step_list_partial_end_blocks_move_up(step_list):
    drag = _drag_step()
    step_list.set_steps([Step(type="wait", params={"ms": 100}), drag])
    form = _open_partial_end(step_list, 1)

    step_list._move_up(1)

    assert [s.type for s in step_list._steps] == ["wait", "drag"]
    assert step_list._expanded_idx == 1
    assert step_list._expanded_form is form
    assert form._end_x == 0.4 and form._end_y is None
    assert "end_x" not in drag.params


def test_step_list_partial_end_blocks_delete_step(step_list):
    drag = _drag_step()
    step_list.set_steps([drag, Step(type="wait", params={"ms": 100})])
    form = _open_partial_end(step_list, 0)

    step_list._delete_step(0)
    assert len(step_list._steps) == 2, "步驟不得被刪除"
    assert step_list._expanded_form is form
    assert form._end_x == 0.4

    step_list._delete_selected_step()
    assert len(step_list._steps) == 2, "Delete 快捷鍵路徑同樣不得刪除"
    assert step_list._expanded_form is form


def test_step_list_partial_end_blocks_set_steps(step_list):
    drag = _drag_step()
    step_list.set_steps([drag])
    form = _open_partial_end(step_list, 0)

    replaced = [Step(type="wait", params={"ms": 999})]
    assert step_list.set_steps(replaced) is False, "替換必須被拒絕"
    assert step_list._steps == [drag], "舊步驟必須保留"
    assert step_list._expanded_form is form
    assert form._end_x == 0.4


def test_step_list_partial_end_blocks_rebuild_and_get_steps_keeps_list(step_list):
    drag = _drag_step()
    step_list.set_steps([drag])
    form = _open_partial_end(step_list, 0)

    assert step_list._rebuild() is False, "_rebuild 必須回報失敗且不動狀態"
    assert step_list._expanded_form is form and step_list._expanded_idx == 0

    # get_steps 維持既有 list 契約：不得把失敗轉成空清單或半套資料
    assert step_list.get_steps() == [drag]
    assert "end_x" not in drag.params
    assert step_list._expanded_form is form


def test_step_list_complete_end_still_moves_deletes_and_replaces(step_list, monkeypatch):
    """完整終點不得被保護機制阻擋（正常流程回歸）。"""
    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    drag = _drag_step(end_x=0.4, end_y=0.6)
    wait = Step(type="wait", params={"ms": 100})
    assert step_list.set_steps([drag, wait]) is True

    step_list._toggle_expand(0)
    assert step_list._expanded_form is not None
    step_list._move_down(0)
    assert [s.type for s in step_list._steps] == ["wait", "drag"]
    assert step_list._expanded_idx is None

    step_list._delete_step(1)
    assert [s.type for s in step_list._steps] == ["wait"]
    assert step_list.set_steps([wait]) is True
    assert step_list.get_steps() == [wait]


def test_partial_drag_end_blocks_task_save_then_recovers(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """真正的存檔呼叫端：半套終點必須中止寫檔，補齊後才落地。"""
    win = real_mainwindow
    drag = make_step("drag", target="custom", x=0.2, y=0.3, dx=10, dy=20, button="left")
    task_path = isolated_data_dir / "tasks" / "t1.json"
    write_task("t1", [make_rule("r0", "規則零", [drag, make_step("wait", ms=100)])])
    before = task_path.read_text(encoding="utf-8")

    win._on_task_changed("t1")
    win._step_list._collapse()
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    assert form is not None
    form._end_x_spin.setValue(0.4)
    assert form._end_y is None

    assert win._flush_save() is False, "半套終點必須中止存檔"
    assert task_path.read_text(encoding="utf-8") == before, "磁碟不得被覆寫"
    assert win._step_list._expanded_form is form, "表單與輸入必須保留"
    assert form._end_x == 0.4

    # 補齊另一軸後即可存檔，且標記為 client 座標系
    form._end_y_spin.setValue(0.6)
    assert win._flush_save() is True
    disk = json.loads(task_path.read_text(encoding="utf-8"))
    params = disk["rules"][0]["steps"][0]["params"]
    assert params["end_x"] == 0.4 and params["end_y"] == 0.6
    assert params["end_roi_coord"] == "client"


# ── 5-2：Wait Step ──────────────────────────────────────────────────────────


def test_wait_form_refills_existing_ms(step_list, qapp):
    step = Step(type="wait", params={"ms": 1234})
    form = step_list._build_form(0, step)
    try:
        assert form is not None
        assert form._ms.value() == 1234
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_wait_form_saves_new_ms(step_list, qapp):
    step = Step(type="wait", params={"ms": 1234})
    form = step_list._build_form(0, step)
    try:
        form._ms.setValue(2500)
        form.save()
        assert step.params["ms"] == 2500
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_wait_form_refills_value_saved_before(step_list, qapp):
    """修改 → 保存 → 重新開啟編輯表單，必須顯示保存後的值。"""
    step = Step(type="wait", params={"ms": 100})
    form = step_list._build_form(0, step)
    try:
        form._ms.setValue(777)
        form.save()
    finally:
        form.deleteLater()

    form2 = step_list._build_form(0, step)
    try:
        assert form2._ms.value() == 777
    finally:
        form2.deleteLater()
        qapp.processEvents()


def test_wait_json_roundtrip_preserves_ms():
    """JSON 序列化與反序列化後，等待時間不變。"""
    step = Step(type="wait", params={"ms": 250})
    rule = Rule(id="rw", name="W", enabled=True, steps=[step])
    raw = _SER._rule_to_dict(rule)
    assert raw["steps"][0]["params"]["ms"] == 250

    reloaded = _SER._dict_to_rule(json.loads(json.dumps(raw, ensure_ascii=False)))
    assert reloaded.steps[0].params["ms"] == 250
    assert reloaded.steps[0].type == "wait"


def test_wait_unit_matches_core_normalization():
    """GUI 寫入的單位必須與 Core 一致（毫秒整數），不得自行換算。"""
    step = Step(type="wait", params={"ms": 250})
    raw = _SER._rule_to_dict(Rule(id="rw2", name="W2", enabled=True, steps=[step]))
    normalized = _MIG._normalize_step_params(
        "wait", dict(raw["steps"][0]["params"]), rule_name="W2"
    )
    assert normalized["ms"] == 250
    assert isinstance(normalized["ms"], int)
    # 執行期以 ms/1000.0 換算秒（core/05_main_loop.py _handle_wait）
    assert normalized["ms"] / 1000.0 == 0.25


@pytest.mark.parametrize("value", [0, 1, 500, 59999, 60000])
def test_wait_accepts_valid_range(step_list, qapp, value):
    step = Step(type="wait", params={"ms": value})
    form = step_list._build_form(0, step)
    try:
        assert form._ms.value() == value
        form.save()
        assert step.params["ms"] == value
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_wait_spinbox_limits(step_list, qapp):
    """數值框的既有範圍不得被本次接線改變。"""
    step = Step(type="wait", params={"ms": 500})
    form = step_list._build_form(0, step)
    try:
        assert form._ms.minimum() == _WAIT_MIN
        assert form._ms.maximum() == _WAIT_MAX
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_wait_default_when_field_missing(step_list, qapp):
    """舊資料缺 ms 欄位時依既有預設值（500）處理，不得崩潰。"""
    step = Step(type="wait", params={})
    form = step_list._build_form(0, step)
    try:
        assert form._ms.value() == _WAIT_DEFAULT
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_wait_core_clamps_negative_to_zero():
    """負值依 Core 既有規則夾為 0（不得自創新規則）。"""
    out = _MIG._normalize_step_params("wait", {"ms": -50}, rule_name="W")
    assert out["ms"] == 0


# ── 5-3：Jump Step ──────────────────────────────────────────────────────────


def test_jump_form_refills_existing_target(step_list, qapp):
    step = Step(type="jump", params={"rule_id": "r2"})
    form = step_list._build_form(0, step)
    try:
        assert form is not None
        assert form._combo.currentData() == "r2"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_form_uses_existing_providers(step_list, qapp):
    """必須沿用既有的 rules_provider / groups_provider（含群組階層與排除規則）。"""
    step = Step(type="jump", params={"rule_id": "r2"})
    form = step_list._build_form(0, step)
    try:
        items = [
            (form._combo.itemText(i), form._combo.itemData(i)) for i in range(form._combo.count())
        ]
        assert ("群組一 › 規則二", "r2") in items, "分群規則應以「群組 › 規則」呈現"
        assert ("未分群規則", "r3") in items, "未分群規則應平鋪在最後"
        assert all(data != "r1" for _text, data in items), "exclude_rule_id 必須排除目前規則"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_form_saves_new_target(step_list, qapp):
    step = Step(type="jump", params={"rule_id": "r2"})
    form = step_list._build_form(0, step)
    try:
        idx = form._combo.findData("r3")
        assert idx >= 0
        form._combo.setCurrentIndex(idx)
        form.save()
        assert step.params["rule_id"] == "r3"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_form_refills_target_saved_before(step_list, qapp):
    step = Step(type="jump", params={"rule_id": "r2"})
    form = step_list._build_form(0, step)
    try:
        idx = form._combo.findData("r3")
        form._combo.setCurrentIndex(idx)
        form.save()
    finally:
        form.deleteLater()

    form2 = step_list._build_form(0, step)
    try:
        assert form2._combo.currentData() == "r3"
    finally:
        form2.deleteLater()
        qapp.processEvents()


def test_jump_json_roundtrip_preserves_target():
    step = Step(type="jump", params={"rule_id": "rule_99561389"})
    rule = Rule(id="rj", name="J", enabled=True, steps=[step])
    raw = _SER._rule_to_dict(rule)
    assert raw["steps"][0]["params"]["rule_id"] == "rule_99561389"

    reloaded = _SER._dict_to_rule(json.loads(json.dumps(raw, ensure_ascii=False)))
    assert reloaded.steps[0].params["rule_id"] == "rule_99561389"
    assert reloaded.steps[0].type == "jump"


def test_jump_missing_target_is_not_silently_switched(step_list, qapp):
    """目標 Rule 已不存在時，不得靜默跳轉到其他 Rule。"""
    step = Step(type="jump", params={"rule_id": "gone"})
    form = step_list._build_form(0, step)
    try:
        assert form._combo.currentData() == "gone", "必須選中原本的（不存在的）目標"
        texts = [form._combo.itemText(i) for i in range(form._combo.count())]
        assert any("gone" in t for t in texts), "應以『未知』項目呈現原本的目標 id"
        form.save()
        assert step.params["rule_id"] == "gone", "不得被改寫成其他 Rule"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_exclude_rule_id_still_works(step_list, qapp):
    """exclude_rule_id 的既有排除行為仍然有效。"""
    step = Step(type="jump", params={"rule_id": ""})
    form = step_list._build_form(0, step)
    try:
        datas = [form._combo.itemData(i) for i in range(form._combo.count())]
        assert "r1" not in datas, "目前規則 r1 不得出現在跳轉目標清單"
        assert "r2" in datas and "r3" in datas
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_params_shape_unchanged(step_list, qapp):
    """不得破壞既有 jump 資料格式：params 只有 rule_id 字串鍵。"""
    step = Step(type="jump", params={"rule_id": "r2"})
    form = step_list._build_form(0, step)
    try:
        form.save()
        assert set(step.params.keys()) == {"rule_id"}
        assert isinstance(step.params["rule_id"], str)
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_core_normalization_keeps_rule_id():
    out = _MIG._normalize_step_params("jump", {"rule_id": "rule_1"}, rule_name="J")
    assert out["rule_id"] == "rule_1"
    assert isinstance(out["rule_id"], str)


# ── 5-4：舊資料相容性 ───────────────────────────────────────────────────────


def _task_files():
    files = [_root / "tests" / "data" / "fixture_task.json"]
    files += sorted((_root / "docs" / "tasks").glob("*.json"))
    return [p for p in files if p.exists()]


def test_existing_wait_and_jump_steps_still_load():
    """既有任務檔的 wait / jump step 仍可載入，且參數不變。"""
    seen = {"wait": 0, "jump": 0}
    for path in _task_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        for raw_rule in data.get("rules", []):
            reloaded = _SER._dict_to_rule(raw_rule)
            for raw_step, step in zip(raw_rule.get("steps", []), reloaded.steps):
                stype = raw_step.get("type")
                if stype not in seen:
                    continue
                seen[stype] += 1
                assert step.type == stype
                assert step.params == raw_step.get("params", {}), (
                    f"{path.name} 的 {stype} step 載入後參數被改變："
                    f"{raw_step.get('params')} → {step.params}"
                )
    assert seen["wait"] > 0, "測試資料中應至少有一筆 wait step"
    assert seen["jump"] > 0, "測試資料中應至少有一筆 jump step"


def test_editing_wait_keeps_other_params(step_list, qapp):
    """編輯並儲存 wait step 後，不得無故丟失其他 params。"""
    step = Step(type="wait", params={"ms": 500, "after_delay_ms": 120})
    form = step_list._build_form(0, step)
    try:
        form._ms.setValue(900)
        form.save()
        assert step.params["ms"] == 900
        assert step.params["after_delay_ms"] == 120, "其他 params 不得被丟失"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_editing_jump_keeps_other_params(step_list, qapp):
    step = Step(type="jump", params={"rule_id": "r2", "after_delay_ms": 30})
    form = step_list._build_form(0, step)
    try:
        idx = form._combo.findData("r3")
        form._combo.setCurrentIndex(idx)
        form.save()
        assert step.params["rule_id"] == "r3"
        assert step.params["after_delay_ms"] == 30, "其他 params 不得被丟失"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_json_schema_not_changed():
    """表單接通不得改變 JSON schema：wait / jump 的欄位名與型別固定。"""
    wait_out = _MIG._normalize_step_params("wait", {"ms": 500}, rule_name="W")
    jump_out = _MIG._normalize_step_params("jump", {"rule_id": "r1"}, rule_name="J")
    assert set(wait_out.keys()) == {"ms"}
    assert set(jump_out.keys()) == {"rule_id"}
    assert isinstance(wait_out["ms"], int)
    assert isinstance(jump_out["rule_id"], str)


def test_wait_form_emits_steps_changed_on_editing_finished(step_list, qapp):
    """Wait 表單沿用既有 editingFinished → steps_changed 回呼。

    模擬 MainWindow 的完整鏈路（`_on_steps_changed` → `_save_current_rule`
    → `_refresh_rule_list` → `_show_rule_detail` → `set_steps` → `_rebuild`），
    驗證：
    1. 修改欄位後資料確實寫入 Step.params；
    2. 重建（表單被銷毀）前已完成保存；
    3. 重建後資料仍在。
    """
    step = Step(type="wait", params={"ms": 500})
    step_list.set_steps([step])

    rebuilt = []

    def _on_steps_changed():
        # _save_current_rule()：rule.steps = get_steps()（內含 _save_expanded → save()）
        current = step_list.get_steps()
        # _refresh_rule_list() → _show_rule_detail() → set_steps() → _rebuild()
        step_list.set_steps(current)
        rebuilt.append(True)

    step_list.steps_changed.connect(_on_steps_changed)

    step_list._toggle_expand(0)
    form = step_list._expanded_form
    assert form is not None, "wait step 必須能展開出編輯表單"

    form._ms.setValue(1500)
    form._ms.editingFinished.emit()
    qapp.processEvents()

    assert rebuilt, "editingFinished 應觸發 steps_changed"
    assert step_list.get_steps()[0].params["ms"] == 1500, "重建後等待時間不得遺失"
    assert step.params["ms"] == 1500


# ── 5-5：空 rule_id 不得被靜默改寫 ──────────────────────────────────────────
#
# 缺陷（Phase 2-2 接線後才第一次對使用者生效）：
#   `_JumpStepForm` 初始化時，若 rule_id 為空字串，
#   `findData("")` 找不到項目、`elif current_id:` 也不成立，
#   ComboBox 便停在第一個規則；`save()` 無條件寫回 combo 選中項，
#   導致「未設定跳轉目標」在存檔時被靜默改寫成第一條規則。
#
# 本節鎖住三種狀態必須彼此區分：
#   A. 空 ID          → 顯示並選中「未設定目標」，存檔仍為 ""
#   B. 有效 ID        → 顯示並選中該規則
#   C. 非空但不存在 ID → 顯示「(未知: xxx)」並選中，存檔仍保留原值


_UNSET_KEY = "step_form.unset_rule"


def _lang_entries() -> dict[str, dict[str, str]]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((_root / "i18n").glob("*.json"))
    }


def _unset_index(form) -> int:
    """代表「未設定目標」的選項索引（data 為空字串）。"""
    idx = form._combo.findData("")
    assert idx >= 0, "combo 必須提供代表『未設定目標』的選項"
    return idx


def test_unset_rule_key_defined_in_all_languages():
    """新增的 i18n key 必須三語齊備且非空。"""
    langs = _lang_entries()
    for required in ("zh_TW", "en", "ja"):
        assert required in langs, f"缺少語言檔 {required}"
    for lang, entries in langs.items():
        assert _UNSET_KEY in entries, f"{lang} 缺少 {_UNSET_KEY}"
        assert entries[_UNSET_KEY].strip(), f"{lang} 的 {_UNSET_KEY} 不得為空字串"


def test_unset_rule_text_is_not_look_like_a_rule_name():
    """「未設定」文案不得看起來像一個有效的規則名稱。"""
    entries = _lang_entries()
    rule_names = [r.name for r in _rules()]
    for lang, texts in entries.items():
        text = texts[_UNSET_KEY]
        for name in rule_names:
            assert name not in text, f"{lang} 的未設定文案看起來像規則名稱：{text}"


def test_jump_empty_target_shows_unset_option_selected(step_list, qapp):
    """狀態 A：空 rule_id 必須顯示「未設定目標」且預設被選取。"""
    step = Step(type="jump", params={"rule_id": ""})
    form = step_list._build_form(0, step)
    try:
        assert form is not None
        idx = _unset_index(form)
        assert form._combo.currentIndex() == idx, "未設定選項必須預設被選取"
        assert form._combo.currentData() == ""
        assert form._combo.itemText(idx) == _GUI.T(_UNSET_KEY)
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_empty_target_is_not_silently_switched(step_list, qapp):
    """核心防線：空 rule_id 開啟表單後直接存檔，必須仍是空字串。"""
    step = Step(type="jump", params={"rule_id": ""})
    form = step_list._build_form(0, step)
    try:
        form.save()
        assert step.params["rule_id"] == "", "空目標不得被靜默改寫成其他規則"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_empty_target_not_auto_selected_first_rule(step_list, qapp):
    """即使清單中有其他規則，也不得自動選中第一條。"""
    step = Step(type="jump", params={"rule_id": ""})
    form = step_list._build_form(0, step)
    try:
        valid_ids = {r.id for r in _rules()}
        assert form._combo.currentData() not in valid_ids, "不得自動選中任一有效規則"
        assert form._combo.currentData() == ""
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_user_can_select_valid_rule_from_unset(step_list, qapp):
    """從未設定切到有效規則，存檔後必須寫入使用者選擇的 ID。"""
    step = Step(type="jump", params={"rule_id": ""})
    form = step_list._build_form(0, step)
    try:
        idx = form._combo.findData("r3")
        assert idx >= 0
        form._combo.setCurrentIndex(idx)
        form.save()
        assert step.params["rule_id"] == "r3"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_user_can_clear_valid_target_back_to_unset(step_list, qapp):
    """從有效規則切回未設定，存檔後必須恢復為空字串。"""
    step = Step(type="jump", params={"rule_id": "r2"})
    form = step_list._build_form(0, step)
    try:
        form._combo.setCurrentIndex(_unset_index(form))
        form.save()
        assert step.params["rule_id"] == ""
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_unknown_target_is_distinct_from_unset(step_list, qapp):
    """狀態 C：非空未知 ID 與空 ID 必須是兩種不同狀態。"""
    step = Step(type="jump", params={"rule_id": "deleted_rule"})
    form = step_list._build_form(0, step)
    try:
        idx_unknown = form._combo.findData("deleted_rule")
        idx_unset = _unset_index(form)
        assert idx_unknown >= 0, "未知 ID 必須仍以獨立項目呈現"
        assert idx_unknown != idx_unset, "未知 ID 不得與未設定混為同一項"
        assert form._combo.currentIndex() == idx_unknown
        assert form._combo.currentData() == "deleted_rule"
        form.save()
        assert step.params["rule_id"] == "deleted_rule", "未知 ID 不得被清成空字串"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_unknown_target_label_keeps_id(step_list, qapp):
    """未知 ID 必須以既有「未知」樣式呈現，且看得見原始 id。"""
    step = Step(type="jump", params={"rule_id": "deleted_rule"})
    form = step_list._build_form(0, step)
    try:
        idx = form._combo.findData("deleted_rule")
        text = form._combo.itemText(idx)
        assert "deleted_rule" in text
        assert text != form._combo.itemText(_unset_index(form))
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_valid_target_still_selected_with_unset_option_present(step_list, qapp):
    """狀態 B：有效 ID 仍正常回填與保存。"""
    step = Step(type="jump", params={"rule_id": "r2"})
    form = step_list._build_form(0, step)
    try:
        assert form._combo.currentData() == "r2"
        form.save()
        assert step.params["rule_id"] == "r2"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_providers_behaviour_unchanged_by_unset_option(step_list, qapp):
    """新增「未設定」選項不得影響群組階層與 exclude_rule_id。"""
    step = Step(type="jump", params={"rule_id": "r2"})
    form = step_list._build_form(0, step)
    try:
        items = [
            (form._combo.itemText(i), form._combo.itemData(i)) for i in range(form._combo.count())
        ]
        assert ("群組一 › 規則二", "r2") in items, "分群規則應以「群組 › 規則」呈現"
        assert ("未分群規則", "r3") in items, "未分群規則應平鋪在最後"
        assert all(data != "r1" for _text, data in items), "exclude_rule_id 必須排除目前規則"
        assert items[0][1] == "", "未設定選項應固定在第一筆"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_jump_empty_target_json_roundtrip_preserves_empty():
    """空目標經 JSON 序列化／反序列化後仍為空字串。"""
    step = Step(type="jump", params={"rule_id": ""})
    rule = Rule(id="rj0", name="J0", enabled=True, steps=[step])
    raw = _SER._rule_to_dict(rule)
    assert raw["steps"][0]["params"]["rule_id"] == ""

    reloaded = _SER._dict_to_rule(json.loads(json.dumps(raw, ensure_ascii=False)))
    assert reloaded.steps[0].params["rule_id"] == ""
    assert reloaded.steps[0].type == "jump"


def test_jump_empty_target_survives_expand_and_rebuild(step_list, qapp):
    """展開表單 → 取回步驟 → 重建清單，空目標必須仍是空字串。"""
    step = Step(type="jump", params={"rule_id": ""})
    step_list.set_steps([step])

    step_list._toggle_expand(0)
    form = step_list._expanded_form
    assert form is not None, "jump step 必須能展開出編輯表單"

    steps = step_list.get_steps()
    assert steps[0].params["rule_id"] == "", "展開後取回步驟時空目標被改寫"

    step_list.set_steps(steps)
    assert step_list.get_steps()[0].params["rule_id"] == "", "重建清單後空目標被改寫"
    qapp.processEvents()


# ── 6：Step Form 靜默資料改寫護欄（Phase 2-7a）─────────────────────────────
#
# Phase 2-7 唯讀診斷確認三類「使用者完全沒有修改、資料卻被改寫」的缺陷：
#
#   D-1：Key Step 的合法按鍵值被清空成 ""
#        Core（core/03_pynput_input.py 的 _KEY_MAP / _NUMPAD_VK）能解析該鍵，
#        但 GUI 的按鍵下拉（gui/06_gui_main.py _make_key_combo）沒有該選項；
#        回填時 findData() 回 -1 → combo 停在 index 0（分隔線）→ 存成 ""。
#
#   D-3：ComboBox 遇到未知值被換成第一個選項
#        （click/drag.target、scroll.direction、compare.operator、detect.match_mode）
#
#   D-4：widget 範圍／精度限制把原值截斷
#        （wait.ms、after_delay_ms、random_offset、scroll.amount、
#          compare.value、detect.fuzzy_threshold）
#
# 本節一律走完整保存路徑（真實 MainWindow + 真實磁碟 JSON）：
#   JSON → 載入任務 → 展開表單（不動任何欄位）→ _flush_save() → 讀回磁碟 JSON → 重新載入
#
# Phase 2-7a 建立本節護欄；Phase 2-7b 已修復 D-1（GUI 按鍵下拉改由 Core 的
# 按鍵定義自動補齊）、Phase 2-7c 已修復 D-3（ComboBox 未知值原樣保留），
# 這兩節的 xfail 標記已移除。D-4 尚未修復，仍以 pytest.mark.xfail(strict=True)
# 標記：strict 代表修復後若沒移除標記會變成 XPASS 而失敗（防止遺漏）。
# 每個案例都附缺陷 ID 與具體原因，不使用無條件 xfail。

_D1_REASON = "D-1: Key Step 的合法按鍵值在 GUI 回填時被清空成空字串"
_D3_REASON = "D-3: ComboBox 未知值在 GUI 回填時被換成第一個選項"
_D4_REASON = "D-4: widget 範圍／精度限制在保存時截斷原值（2-7d-2b-1 已修復）"

# Core 可解析、但 GUI 按鍵下拉未提供的鍵（實測全部會被清空成 ""）
_D1_KEYS = [
    "capslock",
    "numlock",
    "scrolllock",
    "printscreen",
    "pause",
    "menu",
    "shift",
    "ctrl",
    "alt",
    "lshift",
    "rshift",
    "lctrl",
    "rctrl",
    "lalt",
    "ralt",
    "win",
    "windows",
    "numpad0",
    "numpad1",
    "numpad2",
    "numpad3",
    "numpad4",
    "numpad5",
    "numpad6",
    "numpad7",
    "numpad8",
    "numpad9",
    "numpadadd",
    "numpadsub",
    "numpadmult",
    "numpaddiv",
    "numpadenter",
    "numpaddel",
]

# GUI 下拉有提供、必須原樣保留的對照組（正常通過，非 xfail）
_D1_OK_KEYS = ["0", "F12", "a", "Enter", "Space", "Numpad5", "NumpadAdd", "^c"]


def _expand_step_form(win, index: int = 0):
    """展開 step 編輯表單且不修改任何欄位（走真實展開流程）。"""
    win._step_list._collapse()
    win._step_list._toggle_expand(index)
    form = win._step_list._expanded_form
    assert form is not None, "表單必須成功展開"
    return form


def _disk_step_params(isolated_data_dir, name: str = "t1") -> dict:
    """從磁碟讀回第一條規則第一個 step 的 params（真的落盤，不是記憶體物件）。"""
    path = isolated_data_dir / "tasks" / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["rules"][0]["steps"][0]["params"]


def _save_without_editing(
    win, write_task, make_step, make_rule, isolated_data_dir, step_type, params
):
    """走完整保存路徑且不修改任何欄位。

    回傳 (磁碟上的 step params, 重新載入後記憶體中的 step params)。
    """
    step = make_step(step_type, **params)
    write_task("t1", [make_rule("r0", "規則零", [step])])
    win._on_task_changed("t1")
    _expand_step_form(win, 0)
    assert win._flush_save(), "_flush_save 必須成功"
    disk = _disk_step_params(isolated_data_dir, "t1")
    win._on_task_changed("t1")  # 重新載入
    reloaded = win._rules[0].steps[0].params
    return disk, reloaded


# ── 6-1：D-1 Key Step 合法按鍵被清空 ────────────────────────────────────────


def test_d1_key_list_is_really_supported_by_core():
    """D-1 案例清單必須全部是 Core 能解析的鍵，否則不該期待 GUI 保留它們。

    這是護欄本身的自檢：若 Core 日後不再支援某個鍵，這個測試會直接失敗，
    而不是讓對應的 xfail 案例繼續「假裝」是已知缺陷。
    """
    unsupported = [k for k in _D1_KEYS if _INPUT._parse_key(k) is None]
    assert not unsupported, f"這些鍵 Core 無法解析，不屬於 D-1 案例：{unsupported}"


@pytest.mark.parametrize("key", _D1_KEYS)
def test_key_step_core_supported_key_survives_gui_save(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir, key
):
    """D-1：Core 合法但 GUI 下拉未提供的按鍵，展開並存檔後不得被清空。

    Phase 2-7b 已修復（GUI 下拉改由 Core 的按鍵定義自動補齊），
    本測試由 xfail 轉為正常通過，確保不得復發。
    """
    win = real_mainwindow
    disk, reloaded = _save_without_editing(
        win, write_task, make_step, make_rule, isolated_data_dir, "key", {"key": key}
    )
    assert disk["key"] == key, f"按鍵 {key!r} 在磁碟上被清空成 {disk['key']!r}"
    assert reloaded["key"] == key, f"按鍵 {key!r} 重新載入後變成 {reloaded['key']!r}"


def test_gui_key_combo_covers_core_supported_keys(qapp):
    """GUI 按鍵下拉必須涵蓋 Core 支援的所有鍵，且不得提供 Core 不支援的鍵。

    這是「Core 為按鍵事實來源」這個不變量的護欄：
    Core 新增鍵時下拉必須跟著有；Core 不支援的鍵（例如 F13）不得出現在下拉。
    """
    combo = _GUI._make_key_combo()
    values = [combo.itemData(i) for i in range(combo.count())]
    values = [v for v in values if isinstance(v, str)]
    lowered = {v.lower() for v in values}

    core_keys = set(_INPUT._KEY_MAP) | set(_INPUT._NUMPAD_VK)
    missing = sorted(k for k in core_keys if k.lower() not in lowered)
    assert not missing, f"GUI 按鍵下拉缺少 Core 支援的鍵：{missing}"

    # 「^x」形式的 Ctrl 組合由 send_key 的 _send_ctrl_combo 處理，不走 _parse_key。
    unsupported = [v for v in values if not v.startswith("^") and _INPUT._parse_key(v) is None]
    assert not unsupported, f"GUI 按鍵下拉提供 Core 不支援的鍵：{unsupported}"


@pytest.mark.parametrize("key", _D1_OK_KEYS)
def test_key_step_gui_offered_key_survives_gui_save(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir, key
):
    """對照組：GUI 下拉有提供的按鍵，展開並存檔後必須原樣保留。"""
    win = real_mainwindow
    disk, reloaded = _save_without_editing(
        win, write_task, make_step, make_rule, isolated_data_dir, "key", {"key": key}
    )
    assert disk["key"] == key, f"按鍵 {key!r} 在磁碟上變成 {disk['key']!r}"
    assert reloaded["key"] == key, f"按鍵 {key!r} 重新載入後變成 {reloaded['key']!r}"


# ── 6-2：D-3 ComboBox 未知值被換成第一個選項 ───────────────────────────────


_D3_CASES = [
    pytest.param("click", {"target": "cursor_v2"}, "target", "cursor_v2", id="click.target"),
    pytest.param("drag", {"target": "cursor_v2"}, "target", "cursor_v2", id="drag.target"),
    pytest.param(
        "scroll", {"direction": "WheelUp2"}, "direction", "WheelUp2", id="scroll.direction"
    ),
    pytest.param(
        "compare",
        {"pattern": r"\d+", "operator": "=>", "value": 1.0},
        "operator",
        "=>",
        id="compare.operator",
    ),
    pytest.param(
        "detect",
        {"text": "戰鬥", "match_mode": "fuzzy_v2"},
        "match_mode",
        "fuzzy_v2",
        id="detect.match_mode",
    ),
]

# GUI 有提供、必須原樣保留的對照值（正常通過，非 xfail）
_D3_OK_CASES = [
    ("click", {"target": "cursor"}, "target", "cursor"),
    ("drag", {"target": "custom", "x": 3, "y": 4}, "target", "custom"),
    ("scroll", {"direction": "WheelUp"}, "direction", "WheelUp"),
    ("compare", {"pattern": r"\d+", "operator": "!=", "value": 1.0}, "operator", "!="),
    ("detect", {"text": "戰鬥", "match_mode": "exact"}, "match_mode", "exact"),
]

# 欄位 → 對應 Form 的 ComboBox 屬性（不同欄位的 ComboBox 行為必須分別驗證）
_D3_COMBO_ATTR = {
    "target": "_target",
    "direction": "_direction",
    "operator": "_operator",
    "match_mode": "_match_mode",
}


@pytest.mark.parametrize("step_type,params,field,expected", _D3_CASES)
def test_combo_unknown_value_survives_no_edit_save(
    real_mainwindow,
    write_task,
    make_step,
    make_rule,
    isolated_data_dir,
    step_type,
    params,
    field,
    expected,
):
    """D-3：下拉選項以外的未知值，不該在使用者未修改時被換成第一個選項。"""
    win = real_mainwindow
    disk, reloaded = _save_without_editing(
        win, write_task, make_step, make_rule, isolated_data_dir, step_type, params
    )
    assert disk[field] == expected, f"{step_type}.{field} 在磁碟上變成 {disk[field]!r}"
    assert reloaded[field] == expected, f"{step_type}.{field} 重新載入後變成 {reloaded[field]!r}"


@pytest.mark.parametrize("step_type,params,field,expected", _D3_OK_CASES)
def test_combo_known_value_survives_no_edit_save(
    real_mainwindow,
    write_task,
    make_step,
    make_rule,
    isolated_data_dir,
    step_type,
    params,
    field,
    expected,
):
    """對照組：下拉有提供的合法值，不該在使用者未修改時被改動。"""
    win = real_mainwindow
    disk, reloaded = _save_without_editing(
        win, write_task, make_step, make_rule, isolated_data_dir, step_type, params
    )
    assert disk[field] == expected, f"{step_type}.{field} 在磁碟上變成 {disk[field]!r}"
    assert reloaded[field] == expected, f"{step_type}.{field} 重新載入後變成 {reloaded[field]!r}"


@pytest.mark.parametrize("step_type,params,field,unknown", _D3_CASES)
def test_combo_unknown_value_replaced_when_user_picks_valid_option(
    real_mainwindow,
    write_task,
    make_step,
    make_rule,
    isolated_data_dir,
    step_type,
    params,
    field,
    unknown,
):
    """D-3：使用者主動改選有效選項後，必須保存新值，不得繼續保存原本的未知值。"""
    win = real_mainwindow
    step = make_step(step_type, **params)
    write_task("t1", [make_rule("r0", "規則零", [step])])
    win._on_task_changed("t1")

    form = _expand_step_form(win, 0)
    combo = getattr(form, _D3_COMBO_ATTR[field])
    # 使用者明確改選清單中的第一個合法選項（未知值項目排在最後）
    combo.setCurrentIndex(0)
    new_value = combo.currentData()
    assert new_value != unknown, "改選後的值不該還是原本的未知值"

    win._flush_save()
    disk = _disk_step_params(isolated_data_dir, "t1")
    assert disk[field] == new_value, f"{step_type}.{field} 在磁碟上變成 {disk[field]!r}"
    assert disk[field] != unknown, "使用者已改選，原始未知值不該被保留"

    # 重新載入後應回填新選項（不再是未知值項目）
    win._on_task_changed("t1")
    form2 = _expand_step_form(win, 0)
    combo2 = getattr(form2, _D3_COMBO_ATTR[field])
    assert combo2.currentData() == new_value, "重新載入後應回填使用者選擇的新值"


@pytest.mark.parametrize("step_type,params,field,unknown", _D3_CASES)
def test_combo_unknown_value_survives_collapse_and_reexpand(
    real_mainwindow,
    write_task,
    make_step,
    make_rule,
    isolated_data_dir,
    step_type,
    params,
    field,
    unknown,
):
    """D-3：展開 → 折疊 → 重新展開 → 保存，未知值仍必須原樣保留。"""
    win = real_mainwindow
    step = make_step(step_type, **params)
    write_task("t1", [make_rule("r0", "規則零", [step])])
    win._on_task_changed("t1")

    form = _expand_step_form(win, 0)
    combo = getattr(form, _D3_COMBO_ATTR[field])
    assert combo.currentData() == unknown, "展開時未知值應被選中"

    win._step_list._collapse()  # 折疊（內含一次保存）
    form2 = _expand_step_form(win, 0)  # 重新展開
    combo2 = getattr(form2, _D3_COMBO_ATTR[field])
    assert combo2.currentData() == unknown, "重新展開後未知值應仍在"

    win._flush_save()
    disk = _disk_step_params(isolated_data_dir, "t1")
    assert disk[field] == unknown, f"{step_type}.{field} 在磁碟上變成 {disk[field]!r}"

    win._on_task_changed("t1")
    reloaded = win._rules[0].steps[0].params
    assert reloaded[field] == unknown, f"{step_type}.{field} 重新載入後變成 {reloaded[field]!r}"


# ── 6-3：D-4 widget 範圍／精度截斷（Phase 2-7d-2b-1 已修復）────────────────
#
# 原本這 6 個案例是 xfail(strict=True)：GUI 在未編輯的情況下就把既有任務的
# 數值截斷成 widget 的夾制值。修復方式：
#   - fuzzy_threshold → QDoubleSpinBox 0.00–1.00（3 位小數），不再做百分比往返
#   - compare.value    → 15 位小數，保留 ±999999 範圍
#   - 整數欄位         → 未編輯時保存原始值（_RawValue），使用者主動改過才寫新值
# 下列斷言維持「值必須完全等於原值」，不放寬。


_D4_CASES = [
    pytest.param("wait", {"ms": 120000}, "ms", 120000, id="wait.ms"),
    pytest.param(
        "click",
        {"target": "cursor", "after_delay_ms": 120000},
        "after_delay_ms",
        120000,
        id="click.after_delay_ms",
    ),
    pytest.param(
        "click",
        {"target": "cursor", "random_offset": 150},
        "random_offset",
        150,
        id="click.random_offset",
    ),
    pytest.param(
        "scroll",
        {"direction": "WheelUp", "amount": 100},
        "amount",
        100,
        id="scroll.amount",
    ),
    pytest.param(
        "compare",
        {"pattern": r"\d+", "operator": ">=", "value": 1.23456},
        "value",
        1.23456,
        id="compare.value",
    ),
    pytest.param(
        "detect",
        {"text": "戰鬥", "fuzzy_threshold": 0.855},
        "fuzzy_threshold",
        0.855,
        id="detect.fuzzy_threshold",
    ),
]


@pytest.mark.parametrize("step_type,params,field,expected", _D4_CASES)
def test_out_of_range_value_survives_no_edit_save(
    real_mainwindow,
    write_task,
    make_step,
    make_rule,
    isolated_data_dir,
    step_type,
    params,
    field,
    expected,
):
    """D-4：超出 widget 範圍或小數位數的值，不該在使用者未修改時被截斷。"""
    win = real_mainwindow
    disk, reloaded = _save_without_editing(
        win, write_task, make_step, make_rule, isolated_data_dir, step_type, params
    )
    assert disk[field] == expected, f"{step_type}.{field} 在磁碟上變成 {disk[field]!r}"
    assert reloaded[field] == expected, f"{step_type}.{field} 重新載入後變成 {reloaded[field]!r}"


# ── 6-4：fuzzy_threshold 完整 0.0–1.0 範圍無損往返 ───────────────────────


@pytest.mark.parametrize(
    "value",
    [0.0, 0.01, 0.29, 0.57, 0.58, 0.855, 0.9, 1.0],
    ids=[
        "zero",
        "one_percent",
        "29_percent",
        "57_percent",
        "58_percent",
        "85_5_percent",
        "90_percent",
        "one",
    ],
)
def test_fuzzy_threshold_roundtrip_is_lossless(
    real_mainwindow,
    write_task,
    make_step,
    make_rule,
    isolated_data_dir,
    value,
):
    """fuzzy_threshold 必須無損往返：0.29/0.57/0.58 不得因 IEEE754 掉位。

    舊版用 int(value*100) 的整數百分比，0.29*100 = 28.999999999999996 → 28。
    """
    win = real_mainwindow
    disk, reloaded = _save_without_editing(
        win,
        write_task,
        make_step,
        make_rule,
        isolated_data_dir,
        "detect",
        {"text": "戰鬥", "fuzzy_threshold": value},
    )
    assert disk["fuzzy_threshold"] == value, f"磁碟上變成 {disk['fuzzy_threshold']!r}"
    assert reloaded["fuzzy_threshold"] == value, f"重載後變成 {reloaded['fuzzy_threshold']!r}"


# ── 6-5：compare.value 高精度小數無損往返 ─────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [1.23456, 1.23456789012345, -1.23456, 0.1, 55.0],
    ids=["five_dp", "high_dp", "negative", "one_dp", "integral"],
)
def test_compare_value_roundtrip_is_lossless(
    real_mainwindow,
    write_task,
    make_step,
    make_rule,
    isolated_data_dir,
    value,
):
    """compare.value 必須精確往返：舊版 3 位小數會把 1.23456 四捨五入成 1.235。

    這會讓 Core 的 == 比較結果改變（原本成立變成不成立）。
    """
    win = real_mainwindow
    disk, reloaded = _save_without_editing(
        win,
        write_task,
        make_step,
        make_rule,
        isolated_data_dir,
        "compare",
        {"pattern": r"\d+", "operator": ">=", "value": value},
    )
    assert disk["value"] == value, f"磁碟上變成 {disk['value']!r}"
    assert reloaded["value"] == value, f"重載後變成 {reloaded['value']!r}"


# ── 6-6：修改其他欄位不得連帶改寫數值欄位 ────────────────────────────────


@pytest.mark.parametrize(
    "step_type,params,field,expected",
    [
        (
            "click",
            {"target": "cursor", "after_delay_ms": 120000, "random_offset": 150},
            "after_delay_ms",
            120000,
        ),
        ("scroll", {"direction": "WheelUp", "amount": 100}, "amount", 100),
        (
            "compare",
            {"pattern": r"\d+", "operator": ">=", "value": 1.23456},
            "value",
            1.23456,
        ),
        (
            "detect",
            {"text": "戰鬥", "fuzzy_threshold": 0.855},
            "fuzzy_threshold",
            0.855,
        ),
    ],
    ids=["click", "scroll", "compare", "detect"],
)
def test_editing_other_field_does_not_rewrite_numeric(
    real_mainwindow,
    write_task,
    make_step,
    make_rule,
    isolated_data_dir,
    step_type,
    params,
    field,
    expected,
):
    """改了別的欄位再存檔，數值欄位仍必須保持原值。

    wait 步驟只有 ms 一個欄位，無法改「別的欄位」，故不列入本測試。
    """
    win = real_mainwindow
    step = make_step(step_type, **params)
    write_task("t1", [make_rule("r0", "規則零", [step])])
    win._on_task_changed("t1")
    _expand_step_form(win, 0)
    form = win._step_list._expanded_form
    # 動一個「不是數值欄位」的東西
    if step_type == "detect":
        form._text.setText("別的字")
    elif step_type == "compare":
        form._pattern.setText(r"\d{2}")
    elif step_type == "scroll":
        form._direction.setCurrentIndex(form._direction.findData("WheelDown"))
    else:
        form._target.setCurrentIndex(form._target.findData("cursor"))
    assert win._flush_save()
    disk = _disk_step_params(isolated_data_dir, "t1")
    assert disk[field] == expected, f"改其他欄位後 {step_type}.{field} 變成 {disk[field]!r}"


# ── 6-7：使用者主動修改數值欄位後才寫入新值 ──────────────────────────────


@pytest.mark.parametrize(
    "step_type,params,field,new_value",
    [
        ("wait", {"ms": 120000}, "ms", 500),
        ("click", {"target": "cursor", "random_offset": 150}, "random_offset", 5),
        ("scroll", {"direction": "WheelUp", "amount": 100}, "amount", 3),
        ("compare", {"pattern": r"\d+", "operator": ">=", "value": 1.23456}, "value", 9.5),
        ("detect", {"text": "戰鬥", "fuzzy_threshold": 0.855}, "fuzzy_threshold", 0.9),
    ],
    ids=["wait", "click", "scroll", "compare", "detect"],
)
def test_user_edit_replaces_preserved_value(
    real_mainwindow,
    write_task,
    make_step,
    make_rule,
    isolated_data_dir,
    step_type,
    params,
    field,
    new_value,
):
    """使用者主動改過數值欄位 → 保存新值（不是保留原值）。"""
    win = real_mainwindow
    step = make_step(step_type, **params)
    write_task("t1", [make_rule("r0", "規則零", [step])])
    win._on_task_changed("t1")
    _expand_step_form(win, 0)
    form = win._step_list._expanded_form
    widget = {
        "ms": lambda: form._ms,
        "random_offset": lambda: form._offset,
        "amount": lambda: form._amount,
        "value": lambda: form._value,
        "fuzzy_threshold": lambda: form._fuzzy_th,
    }[field]()
    widget.setValue(new_value)
    assert win._flush_save()
    disk = _disk_step_params(isolated_data_dir, "t1")
    assert disk[field] == new_value, (
        f"{step_type}.{field} 應保存新值 {new_value!r}，實際 {disk[field]!r}"
    )


# ── 6-8：GUI 範圍不得因本階段被放寬 ──────────────────────────────────────


def test_gui_numeric_ranges_not_widened(qt_app):
    """Phase 2-7d-2b-1 只修精度與資料保全，不得放寬任何數值上限。"""
    from _loader import load_sibling

    gui = load_sibling("gui_main", "gui/06_gui_main.py")
    models = load_sibling("rule_models", "core/rule_models.py")
    Step = models.Step

    cmp_form = gui._CompareStepForm(
        None, Step("compare", {"value": 0.0, "pattern": r"\d+", "operator": ">="}), 0, None
    )
    assert cmp_form._value.minimum() == -999999.0
    assert cmp_form._value.maximum() == 999999.0

    det_form = gui._DetectStepForm(None, Step("detect", {"text": "x"}), 0, None)
    assert det_form._fuzzy_th.minimum() == 0.0
    assert det_form._fuzzy_th.maximum() == 1.0
    assert det_form._fuzzy_th.decimals() == 3

    wait = gui._WaitStepForm(None, Step("wait", {"ms": 500}), 0)
    assert wait._ms.minimum() == 0
    assert wait._ms.maximum() == 60000

    click = gui._ClickStepForm(None, Step("click", {"target": "cursor"}), 0, None, None, None, None)
    assert click._offset.minimum() == 0
    assert click._offset.maximum() == 100
    assert click._after_delay.maximum() == 60000

    scroll = gui._ScrollStepForm(
        None, Step("scroll", {"direction": "WheelUp"}), 0, None, None, None
    )
    assert scroll._amount.minimum() == 1
    assert scroll._amount.maximum() == 99


# ── 7：NEW-A — Drag GUI 寫回不得污染（新式 endpoint drag）─────────────────────
# 新式 endpoint drag 的 params 不含 dx/dy；表單不得在儲存時新增它們，
# 否則 reload 會被 migration 誤判為 legacy / mixed（假 _migration marker）。


def _new_endpoint_step() -> Step:
    return Step(
        type="drag",
        params={
            "target": "custom",
            "x": 0.2,
            "y": 0.3,
            "end_x": 0.5,
            "end_y": 0.6,
            "end_roi_coord": "client",
        },
    )


def _legacy_drag_step() -> Step:
    return Step(
        type="drag",
        params={"target": "custom", "x": 0.2, "y": 0.3, "dx": 10, "dy": 20},
    )


def test_drag_new_endpoint_save_adds_no_dx_dy(step_list, qapp):
    step = _new_endpoint_step()
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        assert form.save() is True
        assert "dx" not in step.params and "dy" not in step.params
        out = _MIG._normalize_step_params("drag", dict(step.params))
        assert "_migration" not in out
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_new_unset_end_save_adds_no_dx_dy(step_list, qapp):
    step = Step(type="drag", params={"target": "custom", "x": 0.2, "y": 0.3})
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        assert form.save() is True
        assert "dx" not in step.params and "dy" not in step.params
        out = _MIG._normalize_step_params("drag", dict(step.params))
        assert "_migration" not in out
        assert _MIG.validate_drag_endpoint(out)["status"] == "unset"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_legacy_roundtrip_preserves_dx_dy(step_list, qapp, tmp_path):
    step = _legacy_drag_step()
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        assert form.save() is True
        assert step.params["dx"] == 10 and step.params["dy"] == 20
    finally:
        form.deleteLater()
        qapp.processEvents()
    p = tmp_path / "task.json"
    rule = Rule(id="r1", name="R1", enabled=True, steps=[step])
    assert _SER.save_rules([rule], str(p)) is True
    loaded = _SER.load_rules(str(p))
    assert loaded[0].steps[0].params["dx"] == 10
    assert loaded[0].steps[0].params["dy"] == 20
    assert loaded[0].steps[0].params["_migration"]["reason"] == "legacy_px_offset"


def test_drag_legacy_edit_other_fields_keeps_dx_dy(step_list, qapp):
    step = _legacy_drag_step()
    before = _MIG._normalize_step_params("drag", dict(step.params))
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        form._button.setCurrentIndex(form._button.findData("right"))
        assert form.save() is True
        assert step.params["dx"] == 10 and step.params["dy"] == 20
        after = _MIG._normalize_step_params("drag", dict(step.params))
        assert before.get("_migration") == after.get("_migration")
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_mixed_legacy_and_endpoint_marker_preserved(step_list, qapp):
    """舊 dx/dy + 新 end_x/end_y 的真混合資料必須維持 mixed_legacy_and_endpoint。"""
    step = Step(
        type="drag",
        params={
            "target": "custom",
            "x": 0.2,
            "y": 0.3,
            "dx": 10,
            "dy": 20,
            "end_x": 0.5,
            "end_y": 0.6,
            "end_roi_coord": "client",
        },
    )
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        assert form.save() is True
        assert step.params["dx"] == 10 and step.params["dy"] == 20
        out = _MIG._normalize_step_params("drag", dict(step.params))
        assert out["_migration"]["reason"] == "mixed_legacy_and_endpoint"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_user_edit_marks_dirty_and_writes_back(step_list, qapp):
    step = _legacy_drag_step()
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        assert form._dx_was_set is True and form._dy_was_set is True
        assert form._dx_dirty is False and form._dy_dirty is False
        form._dx.setValue(55)
        assert form._dx_dirty is True and form._dy_dirty is False
        assert form.save() is True
        assert step.params["dx"] == 55
        assert step.params["dy"] == 20  # dy 未動，原值保留
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_new_form_dirty_tracks_only_user_edit(step_list, qapp):
    """新式 drag：使用者只改 dx → 只寫 dx，dy 不得出現。"""
    step = Step(type="drag", params={"target": "custom", "x": 0.2, "y": 0.3})
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        assert form._dx_was_set is False and form._dy_was_set is False
        assert form._dx_dirty is False and form._dy_dirty is False
        form._dx.setValue(40)
        assert form.save() is True
        assert step.params["dx"] == 40
        assert "dy" not in step.params
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_drag_cancel_keeps_params_untouched(step_list, qapp):
    """取消（不提交）：params 逐欄位不變。"""
    step = _new_endpoint_step()
    before = json.loads(json.dumps(step.params))
    form = step_list._build_form(0, step)
    assert form is not None
    try:
        form._dx.setValue(999)
        form._dy.setValue(888)
        form._button.setCurrentIndex(form._button.findData("right"))
        # 不呼叫 save() → 直接關閉（取消）
    finally:
        form.deleteLater()
        qapp.processEvents()
    assert step.params == before


# ── 8：UX-C7 — 步驟刪除前確認 ───────────────────────────────────────────────


def _two_steps():
    return [
        Step(type="wait", params={"ms": 500}),
        Step(type="notify", params={"message": "hi"}),
    ]


def test_delete_step_cancel_keeps_steps(step_list, qapp, monkeypatch):
    """取消刪除：步驟、順序完全不變。"""
    from PyQt6.QtWidgets import QMessageBox

    steps = _two_steps()
    assert step_list.set_steps(steps) is True
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )
    step_list._delete_step(0)
    assert [s.type for s in step_list.get_steps()] == ["wait", "notify"]


def test_delete_step_confirm_removes_step(step_list, qapp, monkeypatch):
    """確認刪除：只移除指定的步驟，其餘順序不變。"""
    from PyQt6.QtWidgets import QMessageBox

    steps = _two_steps()
    assert step_list.set_steps(steps) is True
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    step_list._delete_step(0)
    assert [s.type for s in step_list.get_steps()] == ["notify"]


# ── 9：UX-C1 — Detect/MatchImage 基本設定與 on_fail 預設收合 ───────────────


@pytest.mark.parametrize(
    "step_type,params",
    [
        ("detect", {"text": "x"}),
        ("match_image", {"template": "t.png"}),
    ],
)
def test_detect_and_match_image_on_fail_collapsed_on_open(step_list, qapp, step_type, params):
    """打開 Detect/MatchImage 表單時 on_fail 不得被強制展開。"""
    step_list.set_steps([Step(type=step_type, params=params)])
    step_list._toggle_expand(0)
    form = step_list._expanded_form
    assert form is not None
    assert form._on_fail_expanded is False
    assert form._on_fail_container.isVisibleTo(form) is False


def test_compare_on_fail_still_expanded_on_open(step_list, qapp):
    """其他類型（Compare）的展開行為維持不變：打開即展開進階區。"""
    step_list.set_steps(
        [Step(type="compare", params={"value": 1.0, "pattern": r"\d+", "operator": ">="})]
    )
    step_list._toggle_expand(0)
    form = step_list._expanded_form
    assert form is not None
    assert form._on_fail_expanded is True


def test_detect_roi_in_basic_form_layout(step_list, qapp):
    """Detect 的偵測區域必須在基本區（主表單 layout），不在進階容器內。"""
    step_list.set_steps([Step(type="detect", params={"text": "x"})])
    form = step_list._build_form(0, step_list._steps[0])
    try:
        layout = form.layout()
        assert layout.getWidgetPosition(form._roi_label)[0] >= 0
        assert layout.getWidgetPosition(form._roi_btn)[0] >= 0
        assert layout.getWidgetPosition(form._advanced_container)[0] >= 0
        # 進階容器只能包含比對方式等欄位，不得包含 ROI
        adv_layout = form._advanced_container.layout()
        assert adv_layout.getWidgetPosition(form._roi_label)[0] == -1
    finally:
        form.deleteLater()
        qapp.processEvents()
