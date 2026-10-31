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
