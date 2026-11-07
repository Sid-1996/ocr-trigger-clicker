"""Step Editor 流程整合測試（Phase 2-4a）。

以真實 MainWindow + 真實 Step 表單驗證以下面向：

  T-1  MainWindow 真實呼叫鏈（_on_steps_changed / _refresh_rule_list /
       _on_rule_selected / _show_rule_detail / set_steps / _rebuild）
  T-2  Step 展開狀態與重建
  T-3  結構操作（新增 / 刪除 / 排序 / 拖曳）
  T-6  資料一致性與重建安全

設計原則：
  * 優先使用真實 MainWindow，不用 SimpleNamespace 假物件取代整個流程。
  * 斷言使用者可觀察的行為與最後保存的資料，不只斷言內部實作細節。
  * 覆蓋率數據顯示 MainWindow 側的呼叫鏈幾乎沒有測試，因此本檔重點補上
    這條鏈的「現況行為」。

Characterization 說明：
  目前編輯 Step 後表單會折疊（由 steps_changed → _refresh_rule_list →
  setCurrentItem → currentItemChanged → _show_rule_detail → set_steps → _rebuild
  間接造成）。這是**現況**，不是未來必須保留的產品規格；
  Phase 2-4b 若修正折疊，下列標示為 current_behavior 的測試需一併更新。
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QMimeData, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QDropEvent  # noqa: E402
from PyQt6.QtWidgets import QMessageBox  # noqa: E402


def _yes_delete(monkeypatch):
    """步驟刪除確認 → 一律回 Yes（保持既有測試的刪除語意）。"""
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )


# ── 輔助 ────────────────────────────────────────────────────────────────────


def _load_task(win, name: str) -> None:
    """載入任務（走真實 _on_task_changed）。"""
    win._on_task_changed(name)


def _select_rule(win, rule_id: str) -> None:
    """切換選取的規則（走真實 _refresh_rule_list → currentItemChanged 鏈）。"""
    win._selected_rule_id = rule_id
    win._refresh_rule_list()


def _find_rule_item(win, rule_id: str):
    """在規則樹中找到指定 rule id 的 QTreeWidgetItem。"""
    root = win._rule_list.invisibleRootItem()
    for i in range(root.childCount()):
        top = root.child(i)
        for j in range(top.childCount()):
            child = top.child(j)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "rule" and data[1] == rule_id:
                return child
    return None


def _step_types(steps) -> list:
    return [s.type for s in steps]


# QDropEvent 不接管 QMimeData 的所有權；若離開函式後 QMimeData 被回收，
# dropEvent 內部會取到懸垂指標（Windows 上直接 access violation）。
# 因此把建立的 QMimeData 保留在模組層級清單中，避免被 GC。
_MIME_KEEPALIVE: list = []


def _make_drop_event(src_index: int) -> QDropEvent:
    mime = QMimeData()
    mime.setData("step/index", str(src_index).encode())
    _MIME_KEEPALIVE.append(mime)
    return QDropEvent(
        QPointF(0.0, 0.0),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


# ── T-1：MainWindow 真實呼叫鏈 ──────────────────────────────────────────────


def test_task_load_selects_first_rule_and_shows_its_steps(
    real_mainwindow, write_task, make_step, make_rule
):
    """載入任務後，規則清單應自動選中第一條規則，Step 列表顯示該規則的步驟。"""
    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule(
                "r0",
                "規則零",
                [make_step("wait", ms=500), make_step("notify", message="hi")],
            ),
            make_rule("r1", "規則壹", [make_step("wait", ms=700)]),
        ],
    )

    _load_task(win, "t1")

    assert win._current_task == "t1"
    assert len(win._rules) == 2
    assert win._selected_rule_id == "r0", "載入任務後應自動選中第一條規則"
    assert _step_types(win._step_list.get_steps()) == ["wait", "notify"]


def test_steps_changed_rebuilds_rule_tree_and_reselects_rule(
    real_mainwindow, write_task, make_step, make_rule, call_recorder
):
    """steps_changed 應觸發規則樹重建 → 規則選取 → 明細顯示 → Step 列表重建。"""
    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule("r0", "規則零", [make_step("wait", ms=500)]),
            make_rule("r1", "規則壹", [make_step("wait", ms=700)]),
        ],
    )
    _load_task(win, "t1")
    _select_rule(win, "r1")
    call_recorder.reset()

    # 展開第一個 step 的表單
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    assert form is not None

    # 真實觸發：wait 表單的 editingFinished → steps_changed
    form._ms.setValue(1234)
    form._ms.editingFinished.emit()

    assert call_recorder.get("MainWindow._refresh_rule_list") >= 1, "規則樹必須重建"
    assert call_recorder.get("MainWindow._on_rule_selected") >= 1, "必須重新進入規則選取"
    assert call_recorder.get("MainWindow._show_rule_detail") >= 1, "必須重新顯示規則明細"
    assert call_recorder.get("_StepListWidget._rebuild") >= 1, "Step 列表必須重建"
    assert win._selected_rule_id == "r1", "重建後仍應停在原本的規則"


def test_single_callback_saves_current_rule_once(
    real_mainwindow, write_task, make_step, make_rule, call_recorder
):
    """單次 steps_changed 只應觸發一次 _save_current_rule（不重複存檔）。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    _load_task(win, "t1")
    win._step_list._toggle_expand(0)
    call_recorder.reset()

    win._step_list._expanded_form._ms.editingFinished.emit()

    assert call_recorder.get("MainWindow._save_current_rule") == 1


def test_editing_step_does_not_touch_other_rules(real_mainwindow, write_task, make_step, make_rule):
    """編輯 A 規則的 step，不得改動 B 規則的任何資料。"""
    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule("r0", "規則零", [make_step("wait", ms=500)]),
            make_rule("r1", "規則壹", [make_step("wait", ms=700)]),
        ],
    )
    _load_task(win, "t1")
    _select_rule(win, "r0")
    before_r1 = [dict(s.params) for s in win._rules[1].steps]

    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    form._ms.setValue(999)
    form._ms.editingFinished.emit()

    assert [dict(s.params) for s in win._rules[1].steps] == before_r1
    assert win._rules[0].steps[0].params["ms"] == 999


def test_switching_rule_in_tree_saves_previous_rule(
    real_mainwindow, write_task, make_step, make_rule
):
    """在規則樹直接點擊另一條規則時，前一條規則的編輯必須被保存。

    這條路徑與 _refresh_rule_list() 不同：後者會先 clear() 整棵樹，
    導致 currentItemChanged 的 previous 為 None，前一條規則的保存分支
    就不會被執行（見 gui/06_gui_main.py:6326-6346）。
    """
    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule("r0", "規則零", [make_step("wait", ms=500)]),
            make_rule("r1", "規則壹", [make_step("wait", ms=700)]),
        ],
    )
    _load_task(win, "t1")
    assert win._selected_rule_id == "r0"

    # 使用者改動名稱與 step 數值（尚未離開輸入框）
    win._edit_name.setText("改過的名字")
    win._step_list._toggle_expand(0)
    win._step_list._expanded_form._ms.setValue(555)

    # 模擬使用者直接點擊另一條規則
    item_r1 = _find_rule_item(win, "r1")
    assert item_r1 is not None, "規則樹中必須找得到 r1"
    win._rule_list.setCurrentItem(item_r1)

    assert win._selected_rule_id == "r1", "應切換到 r1"
    assert win._rules[0].name == "改過的名字", "前一條規則的名稱必須被保存"
    assert win._rules[0].steps[0].params["ms"] == 555, "前一條規則的 step 必須被保存"


def test_save_current_rule_warns_about_invalid_steps(
    real_mainwindow, write_task, make_step, make_rule
):
    """存檔前遇到有問題的 step 時，狀態列必須顯示警告（但仍要存檔）。"""
    from i18n import T

    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule(
                "r0",
                "規則零",
                [
                    make_step("jump", rule_id="nonexistent"),
                    make_step("match_image"),
                    make_step("notify", message=""),
                    make_step("compare", pattern=""),
                ],
            )
        ],
    )
    _load_task(win, "t1")

    win._save_current_rule()

    message = win._status_bar.currentMessage()
    assert message.startswith("⚠"), f"狀態列必須顯示警告，實際：{message!r}"
    for key, idx in (
        ("notif.rule_validation_missing_rule", 1),
        ("notif.rule_validation_no_image", 2),
        ("notif.rule_validation_empty_notify", 3),
        ("notif.rule_validation_empty_regex", 4),
    ):
        assert T(key, idx=idx) in message, f"警告應包含 {key}（第 {idx} 步）"


# ── T-2：展開狀態與重建 ─────────────────────────────────────────────────────


def test_toggle_expand_opens_form_for_step(real_mainwindow, write_task, make_step, make_rule):
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    _load_task(win, "t1")

    win._step_list._toggle_expand(0)

    assert win._step_list._expanded_idx == 0
    assert win._step_list._expanded_form is not None
    assert type(win._step_list._expanded_form).__name__ == "_WaitStepForm"


def test_toggle_expand_same_index_toggles_closed(real_mainwindow, write_task, make_step, make_rule):
    """對同一個 step 再按一次 → 折疊（current behavior）。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    _load_task(win, "t1")

    win._step_list._toggle_expand(0)
    assert win._step_list._expanded_idx == 0

    win._step_list._toggle_expand(0)
    assert win._step_list._expanded_idx is None
    assert win._step_list._expanded_form is None


def test_expanding_another_step_collapses_previous_form(
    real_mainwindow, write_task, make_step, make_rule
):
    """展開另一個 step 時，先前的表單必須被收起（同一時間只有一個展開槽）。"""
    win = real_mainwindow
    write_task(
        "t1",
        [make_rule("r0", "規則零", [make_step("wait", ms=500), make_step("wait", ms=700)])],
    )
    _load_task(win, "t1")

    win._step_list._toggle_expand(0)
    first_form = win._step_list._expanded_form
    win._step_list._toggle_expand(1)

    assert win._step_list._expanded_idx == 1
    assert win._step_list._expanded_form is not first_form
    assert win._step_list._layout.indexOf(first_form) == -1, "舊表單必須離開 layout"


def test_set_steps_resets_expanded_state(real_mainwindow, write_task, make_step, make_rule):
    """set_steps 會重建清單 → 展開狀態被清掉（current behavior）。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    _load_task(win, "t1")
    win._step_list._toggle_expand(0)
    assert win._step_list._expanded_idx == 0

    win._step_list.set_steps(win._rules[0].steps)

    assert win._step_list._expanded_idx is None
    assert win._step_list._expanded_form is None


def test_rebuild_commits_params_before_discarding_form(
    real_mainwindow, write_task, make_step, make_rule
):
    """重建前必須先 commit 表單值 —— 資料不得遺失。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    _load_task(win, "t1")
    win._step_list._toggle_expand(0)
    win._step_list._expanded_form._ms.setValue(4321)

    win._step_list._rebuild()

    assert win._rules[0].steps[0].params["ms"] == 4321


def test_collapse_commits_params_before_removing_form(
    real_mainwindow, write_task, make_step, make_rule
):
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    _load_task(win, "t1")
    win._step_list._toggle_expand(0)
    win._step_list._expanded_form._ms.setValue(2468)

    win._step_list._collapse()

    assert win._rules[0].steps[0].params["ms"] == 2468
    assert win._step_list._expanded_idx is None


def test_steps_changed_collapses_expanded_form_current_behavior(
    real_mainwindow, write_task, make_step, make_rule
):
    """Characterization（current behavior）：

    編輯 wait 表單後，steps_changed 會造成表單折疊。
    這是現況而非未來規格；Phase 2-4b 修正折疊後本測試需更新。
    """
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    _load_task(win, "t1")
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form

    form._ms.setValue(1111)
    form._ms.editingFinished.emit()

    assert win._step_list._expanded_idx is None, "現況：編輯後表單會折疊"
    assert win._step_list._expanded_form is None
    # 折疊不得造成資料遺失
    assert win._rules[0].steps[0].params["ms"] == 1111


# ── T-3：結構操作 ───────────────────────────────────────────────────────────


def test_delete_step_removes_target_and_keeps_order(
    real_mainwindow, write_task, make_step, make_rule, monkeypatch
):
    _yes_delete(monkeypatch)
    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule(
                "r0",
                "規則零",
                [make_step("wait", ms=1), make_step("wait", ms=2), make_step("wait", ms=3)],
            )
        ],
    )
    _load_task(win, "t1")

    win._step_list._delete_step(1)

    remaining = win._step_list.get_steps()
    assert _step_types(remaining) == ["wait", "wait"]
    assert [s.params["ms"] for s in remaining] == [1, 3]


def test_delete_selected_step_without_expanded_step_is_noop(
    real_mainwindow, write_task, make_step, make_rule
):
    """沒有展開任何 step 時，刪除鍵不得動到資料。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=1)])])
    _load_task(win, "t1")

    win._step_list._delete_selected_step()

    assert len(win._step_list.get_steps()) == 1


def test_delete_selected_step_removes_expanded_step(
    real_mainwindow, write_task, make_step, make_rule, monkeypatch
):
    _yes_delete(monkeypatch)
    win = real_mainwindow
    write_task(
        "t1",
        [make_rule("r0", "規則零", [make_step("wait", ms=1), make_step("wait", ms=2)])],
    )
    _load_task(win, "t1")
    win._step_list._toggle_expand(1)

    win._step_list._delete_selected_step()

    remaining = win._step_list.get_steps()
    assert [s.params["ms"] for s in remaining] == [1]


def test_move_up_swaps_with_previous_step(real_mainwindow, write_task, make_step, make_rule):
    win = real_mainwindow
    write_task(
        "t1",
        [make_rule("r0", "規則零", [make_step("wait", ms=1), make_step("wait", ms=2)])],
    )
    _load_task(win, "t1")

    win._step_list._move_up(1)

    assert [s.params["ms"] for s in win._step_list.get_steps()] == [2, 1]


def test_move_down_swaps_with_next_step(real_mainwindow, write_task, make_step, make_rule):
    win = real_mainwindow
    write_task(
        "t1",
        [make_rule("r0", "規則零", [make_step("wait", ms=1), make_step("wait", ms=2)])],
    )
    _load_task(win, "t1")

    win._step_list._move_down(0)

    assert [s.params["ms"] for s in win._step_list.get_steps()] == [2, 1]


def test_move_up_on_first_step_does_nothing(real_mainwindow, write_task, make_step, make_rule):
    win = real_mainwindow
    write_task(
        "t1",
        [make_rule("r0", "規則零", [make_step("wait", ms=1), make_step("wait", ms=2)])],
    )
    _load_task(win, "t1")

    win._step_list._move_up(0)

    assert [s.params["ms"] for s in win._step_list.get_steps()] == [1, 2]


def test_drop_event_moves_step_to_target_index(real_mainwindow, write_task, make_step, make_rule):
    """拖曳第 0 個 step 到第 3 個位置 → 應插到索引 2（扣除來源）。"""
    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule(
                "r0",
                "規則零",
                [make_step("wait", ms=1), make_step("wait", ms=2), make_step("wait", ms=3)],
            )
        ],
    )
    _load_task(win, "t1")

    win._step_list._drag_indicator_idx = 3
    win._step_list.dropEvent(_make_drop_event(0))

    assert [s.params["ms"] for s in win._step_list.get_steps()] == [2, 3, 1]


def test_drop_event_with_invalid_target_is_ignored(
    real_mainwindow, write_task, make_step, make_rule
):
    """目標索引超出範圍時不得改動順序。"""
    win = real_mainwindow
    write_task(
        "t1",
        [make_rule("r0", "規則零", [make_step("wait", ms=1), make_step("wait", ms=2)])],
    )
    _load_task(win, "t1")

    win._step_list._drag_indicator_idx = 99
    win._step_list.dropEvent(_make_drop_event(0))

    assert [s.params["ms"] for s in win._step_list.get_steps()] == [1, 2]


def test_structure_change_emits_steps_changed_once(
    real_mainwindow, write_task, make_step, make_rule, monkeypatch
):
    """結構變更（刪除）只應 emit 一次 steps_changed。"""
    _yes_delete(monkeypatch)
    win = real_mainwindow
    write_task(
        "t1",
        [make_rule("r0", "規則零", [make_step("wait", ms=1), make_step("wait", ms=2)])],
    )
    _load_task(win, "t1")

    emitted = []
    win._step_list.steps_changed.connect(lambda: emitted.append(1))

    win._step_list._delete_step(0)

    assert len(emitted) == 1


# ── UX 2B-05：新增 Step 後自動展開 ─────────────────────────────────────


def test_add_step_auto_expands_new_step(real_mainwindow, write_task, make_rule, make_step):
    """新增後自動展開剛新增的步驟；連續新增展開最新的一條。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=1)])])
    _load_task(win, "t1")

    win._add_step("detect")
    lst = win._step_list
    assert lst._expanded_idx == 1
    assert lst._expanded_form is not None
    assert lst._steps[lst._expanded_idx].type == "detect"

    win._add_step("wait")
    assert lst._expanded_idx == 2
    assert lst._expanded_form is not None
    assert lst._steps[lst._expanded_idx].type == "wait"
    assert [s.type for s in lst.get_steps()] == ["wait", "detect", "wait"]


def test_add_step_preserves_previously_expanded_edits(
    real_mainwindow, write_task, make_rule, make_step
):
    """新增前已展開步驟的編輯不得遺失（commit 後再展開新步驟）。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=1)])])
    _load_task(win, "t1")
    lst = win._step_list
    lst._toggle_expand(0)
    form = lst._expanded_form
    form._ms.setValue(999)

    win._add_step("notify")
    assert lst._steps[0].params["ms"] == 999
    assert lst._expanded_idx == 1
    assert lst._steps[lst._expanded_idx].type == "notify"


# ── UX 2B-02：全部啟用／停用按鈕文案 ─────────────────────────────────────


def test_toggle_all_groups_text_and_state(real_mainwindow, write_task, make_rule, rule_engine):
    """按鈕文字反映實際操作結果（全部啟用/全部停用），且不啟動 MainLoop。"""
    from i18n import T

    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [])])
    _load_task(win, "t1")

    def set_groups(enableds):
        win._groups = [
            rule_engine.RuleGroup(id=f"g{i}", name=f"群組{i}", enabled=e, rule_ids=[])
            for i, e in enumerate(enableds)
        ]
        win._refresh_rule_list()

    # 全部停用 → 按鈕顯示「全部啟用」
    set_groups([False, False])
    assert win._toggle_all_btn.text() == T("main.toggle_all_on")
    win._toggle_all_groups()
    assert [g.enabled for g in win._groups] == [True, True]
    assert win._toggle_all_btn.text() == T("main.toggle_all_off")

    # 混合狀態 → 按鈕顯示「全部停用」，點擊後全部停用（既有語意不變）
    set_groups([True, False])
    assert win._toggle_all_btn.text() == T("main.toggle_all_off")
    win._toggle_all_groups()
    assert [g.enabled for g in win._groups] == [False, False]

    # 不得意外啟動 MainLoop
    assert win._loop is None or not win._loop.is_running


def test_add_step_appends_and_persists(
    real_mainwindow, write_task, make_step, make_rule, call_recorder
):
    """新增 step 應附加到最後並完成存檔。

    注意：_add_step 走的是 set_steps + _save_current_rule + _refresh_rule_list，
    本身不 emit steps_changed（它直接完成刷新），因此這裡以存檔與清單同步斷言。
    """
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=1)])])
    _load_task(win, "t1")
    call_recorder.reset()

    win._add_step("wait")

    steps = win._step_list.get_steps()
    assert len(steps) == 2, "新增的 step 應出現在清單中"
    assert steps[-1].type == "wait"
    assert len(win._rules[0].steps) == 2, "規則本身也必須同步到新 step"
    assert call_recorder.get("MainWindow._save_current_rule") >= 1, "新增後必須存檔"


# ── T-6：資料一致性與重建安全 ───────────────────────────────────────────────


def test_switching_rule_shows_that_rules_steps(real_mainwindow, write_task, make_step, make_rule):
    """切換規則後，Step 列表必須顯示該規則的步驟，不是上一條規則的。"""
    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule("r0", "規則零", [make_step("wait", ms=500)]),
            make_rule("r1", "規則壹", [make_step("wait", ms=700), make_step("wait", ms=800)]),
        ],
    )
    _load_task(win, "t1")
    assert len(win._step_list.get_steps()) == 1

    _select_rule(win, "r1")

    steps = win._step_list.get_steps()
    assert len(steps) == 2
    assert [s.params["ms"] for s in steps] == [700, 800]


def test_step_params_survive_rule_switch(real_mainwindow, write_task, make_step, make_rule):
    """切走再切回，已編輯的 step 參數不得遺失。"""
    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule("r0", "規則零", [make_step("wait", ms=500)]),
            make_rule("r1", "規則壹", [make_step("wait", ms=700)]),
        ],
    )
    _load_task(win, "t1")
    _select_rule(win, "r0")

    win._step_list._toggle_expand(0)
    win._step_list._expanded_form._ms.setValue(321)
    win._step_list._expanded_form._ms.editingFinished.emit()

    _select_rule(win, "r1")
    _select_rule(win, "r0")

    assert win._rules[0].steps[0].params["ms"] == 321


def test_unknown_step_type_params_preserved_through_rebuild(
    real_mainwindow, write_task, make_step, make_rule
):
    """未知 step type 重建後參數必須原封不動（不得被清空或改寫）。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    _load_task(win, "t1")

    # 直接在記憶體放入未知型別的 step（磁碟載入階段另有遷移規則，此處測的是重建行為）
    win._rules[0].steps = [make_step("future_type", foo="bar", n=7)]
    win._step_list.set_steps(win._rules[0].steps)

    win._step_list._rebuild()

    steps = win._step_list.get_steps()
    assert len(steps) == 1
    assert steps[0].type == "future_type"
    assert steps[0].params == {"foo": "bar", "n": 7}


def test_repeated_edits_do_not_duplicate_params(real_mainwindow, write_task, make_step, make_rule):
    """連續編輯不得讓 params 出現重複或殘留鍵。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    _load_task(win, "t1")
    win._step_list._toggle_expand(0)

    for value in (100, 200, 300):
        form = win._step_list._expanded_form
        if form is None:
            win._step_list._toggle_expand(0)
            form = win._step_list._expanded_form
        form._ms.setValue(value)
        form._ms.editingFinished.emit()

    params = win._rules[0].steps[0].params
    assert params == {"ms": 300}, f"params 應只有 ms 一鍵且為最後值，實際：{params}"


@pytest.mark.parametrize("value", [0, 1, 59999, 60000])
def test_wait_value_roundtrips_through_form(
    real_mainwindow, write_task, make_step, make_rule, value
):
    """wait 的毫秒值經表單編輯後應完整保留（含 0 與上限）。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    _load_task(win, "t1")
    win._step_list._toggle_expand(0)

    form = win._step_list._expanded_form
    form._ms.setValue(value)
    form._ms.editingFinished.emit()

    assert win._rules[0].steps[0].params["ms"] == value
