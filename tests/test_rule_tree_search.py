"""規則樹搜尋（UX 2B-04）整合測試。

以真實 MainWindow + 真實 QTreeWidget 驗證：即時過濾、群組階層、選取/編輯器
不錯亂、展開狀態保存/恢復、新增/刪除/改名/切換任務後結果同步。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QMessageBox  # noqa: E402


def _setup_task(win, write_task, rule_engine, name="t1"):
    write_task(
        name,
        [
            rule_engine.Rule(id="r1", name="Alpha Shop", enabled=True, steps=[]),
            rule_engine.Rule(id="r2", name="Beta Quest", enabled=True, steps=[]),
            rule_engine.Rule(id="r3", name="Gamma Boss", enabled=False, steps=[]),
            rule_engine.Rule(id="r4", name="delta shop", enabled=True, steps=[]),
        ],
        groups=[
            rule_engine.RuleGroup(id="g1", name="日常任務", rule_ids=["r1", "r2"]),
            rule_engine.RuleGroup(id="g2", name="戰鬥任務", rule_ids=["r3", "r4"]),
        ],
    )
    win._on_task_changed(name)


def _visible_rule_ids(win):
    ids = []
    root = win._rule_list.invisibleRootItem()
    for i in range(root.childCount()):
        top = root.child(i)
        if top.isHidden():
            continue
        for j in range(top.childCount()):
            child = top.child(j)
            if child.isHidden():
                continue
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "rule" and data[1] not in ids:
                ids.append(data[1])
    return ids


def _visible_group_ids(win):
    ids = []
    root = win._rule_list.invisibleRootItem()
    for i in range(root.childCount()):
        top = root.child(i)
        if top.isHidden():
            continue
        data = top.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] in ("group", "bg_group"):
            ids.append(data[1])
    return ids


def _find_item(win, rule_id):
    root = win._rule_list.invisibleRootItem()
    for i in range(root.childCount()):
        top = root.child(i)
        for j in range(top.childCount()):
            child = top.child(j)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "rule" and data[1] == rule_id:
                return child
    return None


def _find_group(win, gid):
    root = win._rule_list.invisibleRootItem()
    for i in range(root.childCount()):
        top = root.child(i)
        data = top.data(0, Qt.ItemDataRole.UserRole)
        if data and data[1] == gid:
            return top
    return None


def _search(win, text):
    win._rule_search_edit.setText(text)


def _snapshot(win):
    return [(r.id, r.name, r.enabled, list(r.steps)) for r in win._rules], [
        (g.id, g.name, list(g.rule_ids)) for g in win._groups
    ]


# ── 搜尋比對 ──────────────────────────────────────────────────────────


def test_search_partial_and_full_string(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)

    _search(win, "Alpha")
    assert _visible_rule_ids(win) == ["r1"]

    _search(win, "Alpha Shop")
    assert _visible_rule_ids(win) == ["r1"]

    _search(win, "Shop")
    assert _visible_rule_ids(win) == ["r1", "r4"]


def test_search_is_case_insensitive(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)

    _search(win, "ALPHA")
    assert _visible_rule_ids(win) == ["r1"]

    _search(win, "aLpHa")
    assert _visible_rule_ids(win) == ["r1"]

    _search(win, "DELTA")
    assert _visible_rule_ids(win) == ["r4"]


def test_search_preserves_group_hierarchy(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)

    _search(win, "Shop")
    assert _visible_group_ids(win) == ["g1", "g2"]
    # 命中的規則仍掛在原本的群組底下，不是孤立頂層節點
    assert _find_item(win, "r1").parent() is _find_group(win, "g1")
    assert _find_item(win, "r4").parent() is _find_group(win, "g2")
    assert _find_item(win, "r2").isHidden()
    assert _find_item(win, "r3").isHidden()


def test_search_by_group_name_shows_all_its_rules(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)

    _search(win, "日常")
    assert _visible_group_ids(win) == ["g1"]
    assert _visible_rule_ids(win) == ["r1", "r2"]

    _search(win, "戰鬥")
    assert _visible_group_ids(win) == ["g2"]
    assert _visible_rule_ids(win) == ["r3", "r4"]


def test_search_no_results_shows_empty_state(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)

    _search(win, "不存在的關鍵字")
    assert _visible_rule_ids(win) == []
    assert _visible_group_ids(win) == []
    assert not win._rule_search_empty.isHidden()
    assert "不存在的關鍵字" in win._rule_search_empty.text()


def test_clear_search_restores_everything(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)
    assert win._rule_search_edit.isClearButtonEnabled()

    _search(win, "Alpha")
    assert _visible_rule_ids(win) == ["r1"]

    win._rule_search_edit.clear()
    assert _visible_rule_ids(win) == ["r1", "r2", "r3", "r4"]
    assert _visible_group_ids(win) == ["g1", "g2"]
    assert win._rule_search_empty.isHidden()


def test_search_does_not_mutate_underlying_data(
    real_mainwindow, write_task, rule_engine, call_recorder
):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)
    before = _snapshot(win)
    call_recorder.reset()

    _search(win, "Shop")
    _search(win, "zzz")
    win._rule_search_edit.clear()

    assert _snapshot(win) == before
    # 搜尋過程不得觸發儲存、不得重建規則樹、不得重建編輯器
    assert call_recorder.get("MainWindow._flush_save") == 0
    assert call_recorder.get("MainWindow._save_current_rule") == 0
    assert call_recorder.get("MainWindow._refresh_rule_list") == 0
    assert call_recorder.get("MainWindow._on_rule_selected") == 0
    assert call_recorder.get("MainWindow._show_rule_detail") == 0


# ── 選取與編輯器 ──────────────────────────────────────────────────────


def test_hidden_selection_keeps_editor_and_selection(
    real_mainwindow, write_task, rule_engine, call_recorder
):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)
    win._selected_rule_id = "r1"
    win._refresh_rule_list()
    assert win._edit_name.text() == "Alpha Shop"
    call_recorder.reset()

    _search(win, "Beta")

    assert _find_item(win, "r1").isHidden()
    # 選取與編輯器不被偷偷切換或清空
    assert win._selected_rule_id == "r1"
    assert win._edit_name.text() == "Alpha Shop"
    assert win._edit_stack.currentIndex() == 1
    assert call_recorder.get("MainWindow._on_rule_selected") == 0
    assert call_recorder.get("MainWindow._show_rule_detail") == 0
    current = win._rule_list.currentItem()
    assert current is not None
    assert current.data(0, Qt.ItemDataRole.UserRole) == ("rule", "r1")

    # 刷新（新增/改名等）後，已選規則仍被過濾時也不得誤選第一筆或清空編輯器
    win._refresh_rule_list()
    assert win._selected_rule_id == "r1"
    assert win._edit_name.text() == "Alpha Shop"
    assert win._edit_stack.currentIndex() == 1


def test_selecting_visible_result_switches_editor(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)
    win._selected_rule_id = "r1"
    win._refresh_rule_list()

    _search(win, "Beta")
    win._rule_list.setCurrentItem(_find_item(win, "r2"))

    assert win._selected_rule_id == "r2"
    assert win._edit_name.text() == "Beta Quest"
    assert win._edit_stack.currentIndex() == 1


def test_clear_search_restores_selection_display(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)
    win._selected_rule_id = "r1"
    win._refresh_rule_list()

    _search(win, "Beta")
    win._rule_search_edit.clear()

    assert win._selected_rule_id == "r1"
    assert win._edit_name.text() == "Alpha Shop"
    current = win._rule_list.currentItem()
    assert current is not None
    assert current.data(0, Qt.ItemDataRole.UserRole) == ("rule", "r1")
    assert not current.isHidden()


# ── 資料變更後同步 ────────────────────────────────────────────────────


def test_rename_while_searching_updates_results(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)

    _search(win, "Shop")
    assert _visible_rule_ids(win) == ["r1", "r4"]

    # 走真實改名路徑：選取 r2 → 編輯名稱 → _on_name_changed → refresh
    win._selected_rule_id = "r2"
    win._refresh_rule_list()
    win._edit_name.setText("Beta Shop")
    win._on_name_changed()

    assert _visible_rule_ids(win) == ["r1", "r2", "r4"]


def test_add_and_delete_while_searching_updates_results(
    real_mainwindow, write_task, rule_engine, monkeypatch
):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)

    _search(win, "Shop")
    assert _visible_rule_ids(win) == ["r1", "r4"]

    # 新增一條符合搜尋的規則（直接改資料 + refresh，與 _add_rule 的 refresh 整合點相同）
    new_rule = rule_engine.Rule(id="r5", name="Epsilon Shop", enabled=True, steps=[])
    win._rules.append(new_rule)
    next(g for g in win._groups if g.id == "g2").rule_ids.append("r5")
    win._refresh_rule_list()
    assert _visible_rule_ids(win) == ["r1", "r4", "r5"]

    # 刪除一條符合的規則（走真實 _delete_rule）
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    win._selected_rule_id = "r5"
    win._refresh_rule_list()
    win._delete_rule()
    assert "r5" not in [r.id for r in win._rules]
    assert _visible_rule_ids(win) == ["r1", "r4"]


def test_task_switch_clears_search_and_selection(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)
    _search(win, "Alpha")
    assert _visible_rule_ids(win) == ["r1"]

    write_task(
        "t2",
        [rule_engine.Rule(id="x1", name="Other Task Rule", enabled=True, steps=[])],
        groups=[rule_engine.RuleGroup(id="gx", name="其他群組", rule_ids=["x1"])],
    )
    win._on_task_changed("t2")

    assert win._rule_search_edit.text() == ""
    assert _visible_rule_ids(win) == ["x1"]
    assert win._selected_rule_id == "x1"
    assert win._edit_name.text() == "Other Task Rule"
    assert win._rule_search_empty.isHidden()


# ── 展開狀態 ──────────────────────────────────────────────────────────


def test_expansion_state_preserved_across_search(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    _setup_task(win, write_task, rule_engine)

    # g1 收合、g2 展開（走真實 itemCollapsed/Expanded 訊號鏈）
    g1_item = _find_group(win, "g1")
    g2_item = _find_group(win, "g2")
    g1_item.setExpanded(False)
    g2_item.setExpanded(True)
    assert "g1" in win._collapsed_groups
    assert "g2" not in win._collapsed_groups

    _search(win, "Shop")
    # 命中群組自動展開，但不得污染持久化的收合狀態
    assert g1_item.isExpanded()
    assert g2_item.isExpanded()
    assert "g1" in win._collapsed_groups

    win._rule_search_edit.clear()
    # 清除後恢復搜尋前的展開狀態
    assert not g1_item.isExpanded()
    assert g2_item.isExpanded()
    assert "g1" in win._collapsed_groups


def test_background_rule_searchable(real_mainwindow, write_task, rule_engine):
    win = real_mainwindow
    write_task(
        "t1",
        [
            rule_engine.Rule(id="r1", name="Alpha Shop", enabled=True, steps=[]),
            rule_engine.Rule(
                id="r9", name="Monitor Alert", enabled=True, steps=[], background=True
            ),
        ],
        groups=[rule_engine.RuleGroup(id="g1", name="日常任務", rule_ids=["r1"])],
    )
    win._on_task_changed("t1")

    _search(win, "monitor")
    assert _visible_rule_ids(win) == ["r9"]
    assert "__background__" in _visible_group_ids(win)
