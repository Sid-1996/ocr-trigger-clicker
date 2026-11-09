"""B2：OCR Debug「追加步驟／建立規則」的路徑修復測試（UX3-08）。

覆蓋：
- 無選取規則時不靜默無反應：詢問改建新規則（True→建立；False→明確取消訊息）。
- 文字步驟與圖片（template）步驟兩分支都涵蓋。
- 提交失敗（Drag 半套終點表單）時中止建立：不追加、不蓋檔、保留使用者輸入。
- 成功路徑照舊：追加 detect / match_image 步驟 + 狀態列回饋。
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

_gui = load_sibling("gui_main", "gui/06_gui_main.py")
T = _gui.T


def _load_task(win, name: str) -> None:
    win._refresh_task_list()
    win._on_task_changed(name)


def _status_text(win) -> str:
    return win._status_bar.currentMessage()


def _setup_drag_rule(real_mainwindow, write_task, make_step, make_rule):
    """一條帶 Drag 步驟的規則（可造成表單半套拒絕提交）。"""
    win = real_mainwindow
    write_task(
        "taskA",
        [make_rule("r-drag", "拖曳規則", [make_step("drag", target="custom", x=0.2, y=0.3)])],
    )
    _load_task(win, "taskA")
    win._selected_rule_id = "r-drag"
    win._refresh_rule_list()
    return win


# ── 無選取規則 ──


def test_text_step_no_rule_user_picks_cancel(
    real_mainwindow, write_task, make_step, make_rule, qt_app, monkeypatch
):
    win = real_mainwindow
    win._selected_rule_id = None
    monkeypatch.setattr(_gui.MainWindow, "_ask_debug_create_new_rule", lambda self: False)
    before_rules = len(win._rules)
    win._on_debug_step_requested({"target_text": "家", "roi": {"x": 0, "y": 0, "w": 0, "h": 0}})
    assert len(win._rules) == before_rules, "使用者取消後不得建立／異動任何規則"
    assert T("debug.step_cancelled") in _status_text(win), "不得靜默無反應"


def test_text_step_no_rule_user_picks_create(
    real_mainwindow, write_task, make_step, make_rule, qt_app, monkeypatch
):
    win = real_mainwindow
    win._selected_rule_id = None
    monkeypatch.setattr(_gui.MainWindow, "_ask_debug_create_new_rule", lambda self: True)
    before = len(win._rules)
    win._on_debug_step_requested({"target_text": "家", "roi": {"x": 0, "y": 0, "w": 0, "h": 0}})
    assert len(win._rules) == before + 1
    new = win._rules[-1]
    assert new.name == "家"
    assert new.steps[0].type == "detect" and new.steps[0].params["text"] == "家"
    assert new.steps[1].type == "click"


def test_template_step_no_rule_user_picks_create(
    real_mainwindow, write_task, make_step, make_rule, qt_app, monkeypatch
):
    win = real_mainwindow
    win._selected_rule_id = None
    monkeypatch.setattr(_gui.MainWindow, "_ask_debug_create_new_rule", lambda self: True)
    before = len(win._rules)
    data = {
        "name": "圖片規則",
        "template_data": "iVBORw0KGgo=",
        "capture_size": {"w": 10, "h": 10},
        "roi": {"x": 0, "y": 0, "w": 0.1, "h": 0.1},
    }
    win._on_debug_template_step_requested(data)
    assert len(win._rules) == before + 1
    new = win._rules[-1]
    assert new.steps[0].type == "match_image"
    assert new.steps[0].params["template_data"] == "iVBORw0KGgo="
    assert win._selected_rule_id == new.id


# ── 提交失敗 → 中止建立，保留輸入 ──


def test_text_step_blocked_by_half_drag_form(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    """Drag 半套終點表單拒絕提交時：追加被中止、規則不變、表單輸入保留。"""
    win = _setup_drag_rule(real_mainwindow, write_task, make_step, make_rule)
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    assert form is not None
    form._end_x_spin.setValue(0.35)  # 只填一軸 → save() 拒絕
    before = len(win._get_current_rule().steps)
    win._on_debug_step_requested({"target_text": "家", "roi": {"x": 0, "y": 0, "w": 0, "h": 0}})
    rule = win._get_current_rule()
    assert len(rule.steps) == before == 1, "提交失敗時不得追加步驟"
    assert win._step_list._expanded_form is form, "半套表單與輸入必須保留"
    assert T("debug.commit_blocked") in _status_text(win)


def test_template_step_blocked_by_half_drag_form(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    win = _setup_drag_rule(real_mainwindow, write_task, make_step, make_rule)
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    form._end_x_spin.setValue(0.35)
    before = len(win._get_current_rule().steps)
    data = {
        "name": "圖片步驟",
        "template_data": "iVBORw0KGgo=",
        "capture_size": {"w": 10, "h": 10},
        "roi": {"x": 0, "y": 0, "w": 0.1, "h": 0.1},
    }
    win._on_debug_template_step_requested(data)
    rule = win._get_current_rule()
    assert len(rule.steps) == before == 1
    assert win._step_list._expanded_form is form
    assert T("debug.commit_blocked") in _status_text(win)


# ── 既有成功路徑不回歸 ──


def test_text_step_appended_when_committed(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    win = _setup_drag_rule(real_mainwindow, write_task, make_step, make_rule)
    before = len(win._get_current_rule().steps)
    win._on_debug_step_requested({"target_text": "家", "roi": {"x": 0, "y": 0, "w": 0, "h": 0}})
    rule = win._get_current_rule()
    assert len(rule.steps) == before + 1
    added = rule.steps[-1]
    assert added.type == "detect" and added.params["text"] == "家"
    assert T("notif.step_added_from_debug", text="家") in _status_text(win)


def test_template_step_appended_when_committed(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    win = _setup_drag_rule(real_mainwindow, write_task, make_step, make_rule)
    before = len(win._get_current_rule().steps)
    data = {
        "name": "圖片步驟",
        "template_data": "iVBORw0KGgo=",
        "capture_size": {"w": 10, "h": 10},
        "roi": {"x": 0, "y": 0, "w": 0.1, "h": 0.1},
    }
    win._on_debug_template_step_requested(data)
    rule = win._get_current_rule()
    assert len(rule.steps) == before + 1
    assert rule.steps[-1].type == "match_image"
    assert T("notif.template_step_added_from_debug", name="圖片步驟") in _status_text(win)


def test_create_rule_blocked_by_half_drag_form(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    """「建立為新規則」也必須尊重未提交表單：中止並保留輸入。"""
    win = _setup_drag_rule(real_mainwindow, write_task, make_step, make_rule)
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    form._end_x_spin.setValue(0.35)
    before = len(win._rules)
    win._on_debug_rule_requested({"target_text": "新規則", "roi": {"x": 0, "y": 0, "w": 0, "h": 0}})
    assert len(win._rules) == before, "提交失敗時不得建立新規則"
    assert win._selected_rule_id == "r-drag"
    assert win._step_list._expanded_form is form
    assert T("debug.commit_blocked") in _status_text(win)


def test_ask_dialog_wire_returns_true_only_on_create(
    real_mainwindow, write_task, make_step, make_rule, qt_app, monkeypatch
):
    """`_ask_debug_create_new_rule`：使用者關閉對話框（未選建立）時回 False。"""
    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    win = real_mainwindow
    assert win._ask_debug_create_new_rule() is False, "未按「建立新規則」不得改建"
