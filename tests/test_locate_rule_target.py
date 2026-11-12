"""UX3-01/03 執行問題定位機制測試。

覆蓋：
- 核心 _log_exec 日誌攜帶 rule_id / task；同名規則去重不互相抑制。
- ExecutionLogWidget 點擊列發射 locate_requested（同名以 id 區分）。
- MainWindow.locate_rule_target：定位規則／步驟、同名不錯位、不同群組區分、
  無步驟 id 時僅定位規則、已刪除規則／任務的明確訊息、未提交表單不丟資料、
  執行中記 pending、停止後自動定位、搜尋過濾不阻擋定位。
- _rule_hard_problems 與 core preflight 同步（sum gate／未知類型亦阻擋）。
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from conftest import make_main_loop as _make_ml  # noqa: E402

from _loader import load_sibling  # noqa: E402

_gui = load_sibling("gui_main", "gui/06_gui_main.py")
T = _gui.T

_exec_mod = load_sibling("execution_log_widget", "gui/execution_log_widget.py")

_models = load_sibling("rule_models", "core/rule_models.py")


def _load_task(win, name: str) -> None:
    win._refresh_task_list()
    win._on_task_changed(name)


def _status_text(win) -> str:
    return win._status_bar.currentMessage() if hasattr(win._status_bar, "currentMessage") else ""


# ── 核心：_log_exec 識別欄位 ──


def test_log_exec_carries_rule_id_and_task(tmp_path):
    ml = _make_ml()
    ml._rules_path = str(tmp_path / "mytask.json")
    ml._log_exec("同名規則", 1, "detect", "stop", "未偵測到目標", rule_id="r-42")
    assert len(ml._execution_log) == 1
    entry = ml._execution_log[0]
    assert entry["rule_id"] == "r-42"
    assert entry["task"] == "mytask"
    assert entry["rule_name"] == "同名規則"
    assert entry["step_idx"] == 1


def test_log_exec_same_name_rules_do_not_suppress_each_other():
    """去重鍵以 rule_id 優先：同名不同規則的相同 stop 不得互相抑制。"""
    ml = _make_ml()
    ml._log_exec("同名規則", 0, "detect", "stop", "未偵測到目標", rule_id="r-a")
    ml._log_exec("同名規則", 0, "detect", "stop", "未偵測到目標", rule_id="r-b")
    assert len(ml._execution_log) == 2
    assert {e["rule_id"] for e in ml._execution_log} == {"r-a", "r-b"}


def test_log_exec_legacy_call_without_rule_id_still_works():
    """舊呼叫（無 rule_id）相容：日誌可讀，rule_id 為空字串。"""
    ml = _make_ml()
    ml._log_exec("Q", 0, "detect", "stop", "no match")
    assert len(ml._execution_log) == 1
    assert ml._execution_log[0]["rule_id"] == ""
    assert ml._execution_log[0]["task"] == ""


# ── Widget：點擊列發射定位訊號 ──


def test_exec_log_widget_emits_locate_with_rule_id(qt_app):
    w = _exec_mod.ExecutionLogWidget()
    got = []
    w.locate_requested.connect(lambda *a: got.append(a))
    w._populate(
        [
            {
                "ts": "10:00:00",
                "rule_name": "同名規則",
                "rule_id": "r-1",
                "task": "taskA",
                "step_idx": 2,
                "step_type": "detect",
                "result": "stop",
                "detail": "",
            },
            {
                "ts": "10:00:01",
                "rule_name": "同名規則",
                "rule_id": "r-2",
                "task": "taskA",
                "step_idx": -1,
                "step_type": "completed",
                "result": "completed",
                "detail": "",
            },
        ]
    )
    w._on_cell_clicked(0, 1)
    assert got[-1] == ("taskA", "r-1", 2, "同名規則")
    w._on_cell_clicked(1, 1)
    assert got[-1] == ("taskA", "r-2", -1, "同名規則")
    w.deleteLater()


def test_exec_log_widget_old_entry_emits_empty_rule_id(qt_app):
    w = _exec_mod.ExecutionLogWidget()
    got = []
    w.locate_requested.connect(lambda *a: got.append(a))
    w._populate(
        [
            {
                "ts": "10:00:00",
                "rule_name": "舊規則",
                "step_idx": 0,
                "step_type": "detect",
                "result": "stop",
                "detail": "",
            }
        ]
    )
    w._on_cell_clicked(0, 1)
    assert got[-1][1] == ""
    w.deleteLater()


# ── MainWindow.locate_rule_target ──


def _two_task_setup(real_mainwindow, write_task, make_step, make_rule):
    """taskA：同名規則 r-a（群組 g1）與 r-b（群組 g2）；各 2 步。"""
    win = real_mainwindow
    RuleGroup = _models.RuleGroup
    write_task(
        "taskA",
        [
            make_rule(
                "r-a",
                "同名規則",
                [make_step("detect", text="甲"), make_step("click", target="text_center")],
            ),
            make_rule(
                "r-b",
                "同名規則",
                [make_step("detect", text="乙"), make_step("notify", message="hi")],
            ),
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


def test_locate_rule_and_step_by_id_not_name(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    assert win._selected_rule_id in ("r-a", "r-b")  # 載入後選了第一條
    ok = win.locate_rule_target("taskA", "r-b", 1, "同名規則")
    assert ok is True
    assert win._selected_rule_id == "r-b", "同名規則必須以 id 定位，不可錯位到 r-a"
    assert win._step_list._expanded_idx == 1, "應展開步驟 2 的表單"
    assert T("locate.located_step", name="同名規則", n=2) in _status_text(win)


def test_locate_rule_only_when_no_step_idx(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    ok = win.locate_rule_target("taskA", "r-a", -1, "同名規則")
    assert ok is True
    assert win._selected_rule_id == "r-a"
    assert win._step_list._expanded_idx is None, "無步驟定位時不展開任何步驟"
    assert T("locate.located_rule", name="同名規則") in _status_text(win)


def test_locate_step_gone_falls_back_to_rule(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    # 步驟 9 不存在（被刪除或重排）：停在規則層級，不猜測指向別步
    ok = win.locate_rule_target("taskA", "r-a", 9, "同名規則")
    assert ok is True
    assert win._selected_rule_id == "r-a"
    assert win._step_list._expanded_idx is None
    assert T("locate.step_gone", name="同名規則") in _status_text(win)


def test_locate_deleted_rule_shows_not_found(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    before = win._selected_rule_id
    ok = win.locate_rule_target("taskA", "r-gone", 0, "已刪除規則")
    assert ok is False
    assert win._selected_rule_id == before, "定位失敗不得改變目前選取"
    assert T("locate.rule_not_found", name="已刪除規則") in _status_text(win)


def test_locate_old_log_without_rule_id(real_mainwindow, write_task, make_step, make_rule, qt_app):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    ok = win.locate_rule_target("taskA", "", 0, "舊規則")
    assert ok is False
    assert T("locate.old_log_no_id") in _status_text(win)


def test_locate_missing_task_shows_not_found(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    ok = win.locate_rule_target("不存在的任務", "r-a", 0, "同名規則")
    assert ok is False
    assert T("locate.task_not_found", name="不存在的任務") in _status_text(win)


def test_locate_switches_task_via_existing_flow(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    assert win._current_task == "taskA"
    ok = win.locate_rule_target("taskB", "r-c", 0, "別任務規則")
    assert ok is True
    assert win._current_task == "taskB"
    assert win._selected_rule_id == "r-c"
    assert win._step_list._expanded_idx == 0


def test_locate_clears_search_filter(real_mainwindow, write_task, make_step, make_rule, qt_app):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._rule_search_edit.setText("不存在的關鍵字")
    item = win._find_rule_tree_item("r-b")
    assert item is not None and item.isHidden(), "前置：搜尋應隱藏 r-b"
    ok = win.locate_rule_target("taskA", "r-b", None, "同名規則")
    assert ok is True
    assert win._selected_rule_id == "r-b"
    assert win._rule_search_edit.text() == "", "定位前應清除搜尋過濾"


def test_locate_blocked_by_uncommitted_form_keeps_selection(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    """展開中的 Drag 半套終點表單拒絕提交時：中止定位，保留使用者輸入與選取。"""
    win = real_mainwindow
    write_task(
        "taskA",
        [
            make_rule("r-drag", "拖曳規則", [make_step("drag", target="custom", x=0.2, y=0.3)]),
            make_rule("r-other", "其他規則", [make_step("wait", ms=100)]),
        ],
    )
    _load_task(win, "taskA")
    win._selected_rule_id = "r-drag"
    win._refresh_rule_list()
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    assert form is not None
    form._end_x_spin.setValue(0.3)  # 只填一軸 → save() 拒絕提交
    assert form.save() is False

    ok = win.locate_rule_target("taskA", "r-other", None, "其他規則")
    assert ok is False
    assert win._selected_rule_id == "r-drag", "定位被擋時選取不得移動"
    assert win._step_list._expanded_form is form, "未完成的表單與輸入必須保留"
    assert T("locate.commit_blocked") in _status_text(win)


def test_locate_while_running_records_pending(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._loop = SimpleNamespace(
        is_running=True,
        get_execution_log=lambda: [],
        stop=lambda: None,
    )
    ok = win.locate_rule_target("taskA", "r-b", 1, "同名規則")
    assert ok is False
    assert win._pending_locate == ("taskA", "r-b", 1, "同名規則")
    assert T("locate.pending_after_stop", name="同名規則") in _status_text(win)
    # 停止後自動執行 pending 定位
    win._stop_loop()
    assert win._pending_locate is None
    assert win._selected_rule_id == "r-b"
    assert win._step_list._expanded_idx == 1


def test_locate_respects_unsaved_name_edit(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    """未存檔的規則名稱編輯必須經既有流程保存，不可被定位丟棄。"""
    win = _two_task_setup(real_mainwindow, write_task, make_step, make_rule)
    win._selected_rule_id = "r-a"
    win._refresh_rule_list()
    win._edit_name.setText("改過的名字")
    ok = win.locate_rule_target("taskA", "r-b", None, "同名規則")
    assert ok is True
    rule_a = next(r for r in win._rules if r.id == "r-a")
    assert rule_a.name == "改過的名字", "上一條規則的編輯應由既有選取流程保存"


# ── UX3-03：_rule_hard_problems 與 preflight 同步 ──


def _fake_window():
    """_rule_hard_problems 會呼叫 _rule_preflight_issues → 假視窗要提供這個入口。"""
    win = SimpleNamespace()
    win._rule_preflight_issues = lambda rule: _gui.MainWindow._rule_preflight_issues(win, rule)
    return win


def test_hard_problems_include_sum_gate_and_unknown_type(make_rule, make_step):
    win = _fake_window()
    sum_rule = make_rule(
        "r-sum",
        "加總規則",
        [
            make_step("detect", text="數字"),
            make_step("sum", gate=True, operator=">=", value=5),  # 無 ROI
        ],
    )
    problems = _gui.MainWindow._rule_hard_problems(win, sum_rule)
    assert T("exec_log.reason.sum_gate_roi_unset") in problems

    unknown_rule = make_rule("r-unk", "未知規則", [make_step("teleport")])
    problems = _gui.MainWindow._rule_hard_problems(win, unknown_rule)
    assert T("exec_log.reason.unknown_step_type") in problems


def test_hard_problems_keep_legacy_zero_click_block(make_rule, make_step):
    win = _fake_window()
    rule = make_rule(
        "r-zero",
        "零點擊規則",
        [make_step("click", target="custom", x=0, y=0)],
    )
    problems = _gui.MainWindow._rule_hard_problems(win, rule)
    assert T("notif.rule_validation_zero_click", idx=1) in problems
