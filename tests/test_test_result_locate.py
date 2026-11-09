"""B1 + B4 GUI 級：規則測試結果定位、生命週期守衛與過期結果防護。

覆蓋：
- 測試結果以啟動時保存的 rule_id/task/seq 顯示：「定位至問題規則」重用
  Phase 3A `locate_rule_target`（含跨任務切換）。
- 缺少 rule_id 的結果：顯示提示、不提供定位鈕，不以規則名稱猜測。
- 舊格式結果（無 locate 欄）相容不炸。
- 過期結果（seq 舊）不得覆蓋新測試：略過顯示、不動 UI 狀態。
- 測試進行中：重複啟動被擋、`_start_loop` 被擋、切換規則不重啟用測試鈕。
- 取消是明確狀態：`{"cancelled": True}` 只顯示訊息，不算失敗、不開結果視窗。
- 結束路徑（成功／錯誤）恢復 UI 狀態；正式執行中保持測試鈕停用。
"""

import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from PyQt6.QtWidgets import QDialog, QLabel, QMessageBox, QPushButton  # noqa: E402

from _loader import load_sibling  # noqa: E402

_gui = load_sibling("gui_main", "gui/06_gui_main.py")
_models = load_sibling("rule_models", "core/rule_models.py")
T = _gui.T
RuleGroup = _models.RuleGroup


def _load_task(win, name: str) -> None:
    win._refresh_task_list()
    win._on_task_changed(name)


def _status_text(win) -> str:
    return win._status_bar.currentMessage() if hasattr(win._status_bar, "currentMessage") else ""


def _two_task_setup(real_mainwindow, write_task, make_step, make_rule):
    """taskA：同名規則 r-a（g1）/ r-b（g2）；taskB：r-c。與 locate 測試同構。"""
    win = real_mainwindow
    write_task(
        "taskA",
        [
            make_rule(
                "r-a",
                "同名規則",
                [make_step("detect", text="甲"), make_step("click", target="text_center")],
            ),
            make_rule("r-b", "同名規則", [make_step("wait", ms=50)]),
        ],
        groups=[
            RuleGroup(id="g1", name="群組一", enabled=True, rule_ids=["r-a"]),
            RuleGroup(id="g2", name="群組二", enabled=True, rule_ids=["r-b"]),
        ],
    )
    write_task(
        "taskB",
        [make_rule("r-c", "別任務規則", [make_step("wait", ms=100)])],
        groups=[RuleGroup(id="g1", name="群組一", enabled=True, rule_ids=["r-c"])],
    )
    _load_task(win, "taskA")
    return win


@pytest.fixture
def no_modal(monkeypatch):
    """QMessageBox 不被秒擋；QDialog.exec 不阻塞（記下對話框供檢查）。"""
    warned = []
    shown = []

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: warned.append((a, k)) or QMessageBox.StandardButton.Ok),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda *a, **k: warned.append((a, k)) or QMessageBox.StandardButton.Ok),
    )
    monkeypatch.setattr(QDialog, "exec", lambda self: shown.append(self) or 0)
    no_modal.warned = warned  # type: ignore[attr-defined]
    no_modal.shown = shown  # type: ignore[attr-defined]
    return no_modal


def _result(win, **over):
    """以偵測到的待測 seq 組一筆最小成功結果（無 OCR 依賴）。"""
    ctrl = win._test_ctrl
    ctrl._run_seq += 1
    r = {
        "image": np.zeros((4, 4, 3), dtype=np.uint8),
        "log": T("test.rule_header", name="x", count=1),
        "log_dead": [],
        "locate": {
            "task": "taskA",
            "rule_id": "r-b",
            "rule_name": "同名規則",
            "seq": ctrl._run_seq,
        },
    }
    r.update(over)
    return r


def _locate_btn(dlg):
    want = T("dialog.locate_problem")
    return next((b for b in dlg.findChildren(QPushButton) if b.text() == want), None)


# ── B1：定位 ──


def test_result_locate_uses_saved_ctx_across_tasks(
    real_mainwindow, write_task, make_step, make_rule, qt_app, no_modal
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    assert win._current_task == "taskA"
    res = _result(win)
    res["locate"] = {
        "task": "taskB",
        "rule_id": "r-c",
        "rule_name": "別任務規則",
        "seq": win._test_ctrl._run_seq,
    }
    win._show_test_result(res)
    dlg = no_modal.shown[-1]
    btn = _locate_btn(dlg)
    assert btn is not None, "有效 rule_id 的結果必須提供定位鈕"
    btn.click()
    assert win._current_task == "taskB", "定位必須用結果保存的任務，不取當下選取"
    assert win._selected_rule_id == "r-c"
    assert T("locate.located_rule", name="別任務規則") in _status_text(win)


def test_result_locate_within_task_after_user_switched_selection(
    real_mainwindow, write_task, make_step, make_rule, qt_app, no_modal
):
    """結果出現前使用者切到 r-a：定位仍以 ctx 的 r-b 為準，同名不錯位。"""
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    # 搜尋過濾下定位也應自行清掉
    win._rule_search_edit.setText("不存在的關鍵字")
    win._show_test_result(_result(win))  # ctx 指向 r-b
    dlg = no_modal.shown[-1]
    _locate_btn(dlg).click()
    assert win._selected_rule_id == "r-b", "不得錯位到當下選取的 r-a"
    assert win._rule_search_edit.text() == "", "定位前應清除搜尋過濾"


def test_result_without_rule_id_shows_hint_no_locate(
    real_mainwindow, write_task, make_step, make_rule, qt_app, no_modal
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    res = _result(win)
    res["locate"] = {
        "task": "taskA",
        "rule_id": "",
        "rule_name": "同名規則",
        "seq": res["locate"]["seq"],
    }
    win._show_test_result(res)
    dlg = no_modal.shown[-1]
    assert _locate_btn(dlg) is None, "缺少 rule_id 不得提供以名稱猜測的定位"
    hint = next((w for w in dlg.findChildren(QLabel) if w.text() == T("test.no_locate_info")), None)
    assert hint is not None


def test_legacy_result_without_locate_key_compat(
    real_mainwindow, write_task, make_step, make_rule, qt_app, no_modal
):
    """舊格式結果（無 locate 欄）：不得例外，照常顯示但不定位。"""
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    res = _result(win)
    res.pop("locate")
    win._show_test_result(res)
    dlg = no_modal.shown[-1]
    assert _locate_btn(dlg) is None
    assert _status_text(win) != ""


# ── B4：生命週期 ──


def test_stale_result_discarded_keeps_testing_state(
    real_mainwindow, write_task, make_step, make_rule, qt_app, no_modal
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    ctrl = win._test_ctrl
    ctrl._run_seq += 1
    stale_seq = ctrl._run_seq
    # 新一輪已在途
    win._set_test_running(True)
    ctrl._run_seq += 1

    win._show_test_result(
        {
            "image": np.zeros((4, 4, 3), dtype=np.uint8),
            "log": "x",
            "log_dead": [],
            "locate": {"task": "taskA", "rule_id": "r-b", "rule_name": "n", "seq": stale_seq},
        }
    )
    assert no_modal.shown == [], "過期結果不得開結果視窗"
    assert T("test.stale_result") in _status_text(win)
    assert win._is_testing is True, "過期結果不得干擾仍在途的新測試"
    assert win._edit_test_cancel_btn.isVisible() or win._edit_test_cancel_btn.isVisibleTo(
        win._edit_test_cancel_btn.parentWidget()
    )


def test_cancelled_result_is_distinct_state(
    real_mainwindow, write_task, make_step, make_rule, qt_app, no_modal
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._set_test_running(True)
    ctrl = win._test_ctrl
    ctrl._run_seq += 1
    win._show_test_result(
        {
            "cancelled": True,
            "locate": {"task": "taskA", "rule_id": "r-b", "rule_name": "n", "seq": ctrl._run_seq},
        }
    )
    assert no_modal.shown == [], "取消不得開結果視窗"
    assert T("test.cancelled_note") in _status_text(win)
    assert win._is_testing is False
    assert win._edit_test_btn.text() == T("ui.test")


def test_error_result_warns_and_restores(
    real_mainwindow, write_task, make_step, make_rule, qt_app, no_modal
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._set_test_running(True)
    ctrl = win._test_ctrl
    ctrl._run_seq += 1
    win._show_test_result(
        {
            "error": "boom",
            "locate": {"task": "taskA", "rule_id": "r-b", "rule_name": "n", "seq": ctrl._run_seq},
        }
    )
    assert len(no_modal.warned) == 1
    assert no_modal.shown == []
    assert win._is_testing is False


def test_no_duplicate_test_start(
    real_mainwindow, write_task, make_step, make_rule, qt_app, no_modal
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._set_test_running(True)
    before = win._test_ctrl._run_seq
    win._test_ctrl.on_test_rule()  # pytest 不啟動主循環；此處只驗重複啟動被擋
    assert T("test.already_running") in str(no_modal.warned)
    assert win._test_ctrl._run_seq == before, "重複啟動不得開新測試輪"


def test_start_blocked_while_testing(
    real_mainwindow, write_task, make_step, make_rule, qt_app, no_modal
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._set_test_running(True)
    win._start_loop()
    assert T("status.stop_test_first") in str(no_modal.warned)
    assert win._loop is None, "測試在途時不得啟動正式執行"


def test_on_test_rule_blocked_while_loop_running(
    real_mainwindow, write_task, make_step, make_rule, qt_app, no_modal
):
    """正式執行中不得啟動測試（兩狀態互斥；訊息不同於重複啟動）。"""
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._loop = SimpleNamespace(is_running=True, stop=lambda: None)
    before = win._test_ctrl._run_seq
    win._test_ctrl.on_test_rule()
    assert T("status.stop_first_test") in str(no_modal.warned)
    assert win._test_ctrl._run_seq == before


def test_restore_respects_running_loop(real_mainwindow, write_task, make_step, make_rule, qt_app):
    """正式執行進行中時，測試結束的恢復不得重啟用測試鈕。"""
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._set_test_running(True)
    win._loop = SimpleNamespace(is_running=True, stop=lambda: None)
    win._restore_test_btn()
    assert win._is_testing is False
    assert win._edit_test_btn.isEnabled() is False, "正式執行中不得重啟用測試鈕"

    win._loop = None
    win._restore_test_btn()
    assert win._edit_test_btn.isEnabled() is True


def test_show_rule_detail_keeps_test_btn_disabled_while_testing(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    """切換規則（_show_rule_detail）不因既有流程把測試鈕重新啟用。"""
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._set_test_running(True)
    rule_a = next(r for r in win._rules if r.id == "r-a")
    win._show_rule_detail(rule_a)
    assert win._edit_test_btn.isEnabled() is False
    win._set_test_running(False)


def test_cancel_button_sets_ctrl_event(real_mainwindow, write_task, make_step, make_rule, qt_app):
    """取消鈕按下後，TestRunController 的取消事件被置位（下一個步驟邊界生效）。"""
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._test_ctrl._cancel_event = threading.Event()
    win._edit_test_cancel_btn.click()
    assert win._test_ctrl._cancel_event.is_set()


def test_set_test_running_toggles_cancel_button(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._set_test_running(True)
    assert win._is_testing is True
    win._set_test_running(False)
    assert win._is_testing is False
