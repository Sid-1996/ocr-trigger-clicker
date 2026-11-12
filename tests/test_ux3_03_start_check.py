"""UX3-03 啟動前檢核 ＋ UX3-01 日誌定位到步驟。

本檔鎖定三件事：

1. core preflight 新增 issues（0-based step_idx ＋ severity），
   且 status／problems／warnings 的內容與順序完全不變（既有呼叫端不受影響）。
2. 執行期 BLOCKED 日誌帶著出問題的步驟 → 點日誌可直接跳到該步。
3. 啟動前檢核涵蓋背景監控規則，並以「編輯器裡尚未存檔的步驟」檢核；
   檢核未通過時確實擋住啟動，且清單可逐項定位到對應規則／步驟。
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pytest  # noqa: E402
from conftest import make_main_loop as _make_ml  # noqa: E402
from PyQt6.QtWidgets import QLabel, QMessageBox, QPushButton  # noqa: E402

from _loader import load_sibling  # noqa: E402

_models = load_sibling("rule_models", "core/rule_models.py")
Rule = _models.Rule
RuleGroup = _models.RuleGroup
Step = _models.Step

_gui = load_sibling("gui_main", "gui/06_gui_main.py")
_exec_mod = load_sibling("execution_log_widget", "gui/execution_log_widget.py")
_preflight_mod = load_sibling("rule_preflight", "core/rule_preflight.py")
T = _gui.T


def _rule(steps, rule_id="r-1", name="規則"):
    return Rule(id=rule_id, name=name, enabled=True, steps=list(steps))


def _load_task(win, name: str) -> None:
    win._refresh_task_list()
    win._on_task_changed(name)


# ── 1. core preflight：issues 附加欄位 ──────────────────────────────────


def test_preflight_issue_carries_step_index():
    """問題要帶 0-based 步驟位置 → GUI 才能指出「是第幾步壞掉」。"""
    rule = _rule(
        [
            Step(type="detect", params={"text": "好"}),
            Step(type="detect", params={"text": "  "}),
        ]
    )
    result = _preflight_mod.rule_preflight(rule)
    assert result.status == "blocked"
    issue = next(i for i in result.issues if i["key"] == "empty_detect_text")
    assert issue["step_idx"] == 1
    assert issue["severity"] == "blocked"


def test_preflight_issues_keep_every_occurrence():
    """problems 維持去重（既有語意），issues 保留每一次發生的位置。"""
    rule = _rule(
        [
            Step(type="detect", params={"text": ""}),
            Step(type="detect", params={"text": ""}),
        ]
    )
    result = _preflight_mod.rule_preflight(rule)
    assert result.problems.count("empty_detect_text") == 1
    assert [i["step_idx"] for i in result.issues if i["key"] == "empty_detect_text"] == [0, 1]


def test_preflight_status_problems_warnings_unchanged():
    """既有輸出契約不可變：status／problems／warnings 的內容與順序。"""
    rule = _rule(
        [
            Step(type="detect", params={"text": ""}),
            Step(type="click", params={"target": "custom", "x": 0, "y": 0}),
        ]
    )
    result = _preflight_mod.rule_preflight(rule)
    assert result.status == "blocked"
    assert result.problems == ["empty_detect_text"]
    assert result.warnings == ["custom_click_at_origin"]


def test_preflight_rule_level_problem_has_no_step():
    """規則層級的問題沒有步驟位置 → 定位停在規則層級。"""
    result = _preflight_mod.rule_preflight(None)
    assert result.status == "blocked"
    assert result.problems == ["invalid_rule"]
    assert result.issues[0]["step_idx"] is None


def test_preflight_warning_is_not_blocking():
    """warning 不得變成 blocking：狀態仍是 passed。"""
    rule = _rule([Step(type="click", params={"target": "custom", "x": 0, "y": 0})])
    result = _preflight_mod.rule_preflight(rule)
    assert result.status == "passed"
    issue = next(i for i in result.issues if i["key"] == "custom_click_at_origin")
    assert issue["severity"] == "warning"


# ── 2. 執行期 BLOCKED 日誌帶著出問題的步驟 ──────────────────────────────


def test_blocked_exec_log_entry_carries_step():
    """BLOCKED 日誌要帶步驟位置 → 使用者點日誌就能跳到出問題的那一步。"""
    ml = _make_ml()
    rule = _rule(
        [
            Step(type="detect", params={"text": "好"}),
            Step(type="detect", params={"text": ""}),
        ]
    )
    result = _preflight_mod.rule_preflight(rule)
    ml._record_preflight_block(rule, result, background=False)
    entry = list(ml._execution_log)[-1]
    assert entry["result"] == "blocked"
    assert entry["step_type"] == "preflight"
    assert entry["step_idx"] == 1
    assert entry["rule_id"] == rule.id


def test_blocked_exec_log_rule_level_problem_has_no_step():
    """規則層級的 BLOCKED 仍是 -1（只定位規則）。"""
    ml = _make_ml()
    rule = _rule([])
    result = _preflight_mod.rule_preflight(rule)
    ml._record_preflight_block(rule, result, background=False)
    entry = list(ml._execution_log)[-1]
    assert entry["step_idx"] == -1


def test_widget_blocked_entry_locates_step(qt_app):
    """BLOCKED 列點擊 → 定位到出問題的步驟。"""
    w = _exec_mod.ExecutionLogWidget()
    got = []
    w.locate_requested.connect(lambda *a: got.append(a))
    w._populate(
        [
            {
                "ts": "10:00:00",
                "rule_name": "規則A",
                "rule_id": "r-1",
                "task": "taskA",
                "step_idx": 1,
                "step_type": "preflight",
                "result": "blocked",
                "detail": "偵測關鍵字為空白",
            }
        ]
    )
    w._on_cell_clicked(0, 1)
    assert got[-1] == ("taskA", "r-1", 1, "規則A")
    w.deleteLater()


def test_widget_background_entry_locates_rule_only(qt_app):
    """背景（日誌 step_idx=0）仍只定位規則，不可假裝能跳到第 1 步。"""
    w = _exec_mod.ExecutionLogWidget()
    got = []
    w.locate_requested.connect(lambda *a: got.append(a))
    w._populate(
        [
            {
                "ts": "10:00:00",
                "rule_name": "背景規則",
                "rule_id": "r-bg",
                "task": "taskA",
                "step_idx": 0,
                "step_type": "background",
                "result": "triggered",
                "detail": "",
            }
        ]
    )
    w._on_cell_clicked(0, 1)
    assert got[-1][2] == -1
    w.deleteLater()


def test_widget_bad_step_idx_does_not_crash(qt_app):
    """舊資料帶非整數 step_idx 不得讓面板爆掉。"""
    w = _exec_mod.ExecutionLogWidget()
    w._populate(
        [
            {
                "ts": "10:00:00",
                "rule_name": "舊規則",
                "step_idx": None,
                "step_type": "detect",
                "result": "stop",
                "detail": "",
            }
        ]
    )
    assert w._table.rowCount() == 1
    w.deleteLater()


# ── 3. GUI：啟動前檢核 ────────────────────────────────────────────────


def test_start_check_includes_background_rules(real_mainwindow, write_task, make_step, make_rule):
    """背景監控規則不在任何群組，但每幀都會評估 → 啟動前也要檢查。"""
    win = real_mainwindow
    bg = make_rule("r-bg", "背景規則", [make_step("detect", text="")])
    bg.background = True
    write_task(
        "taskA",
        [make_rule("r-a", "正常規則", [make_step("wait", ms=100)]), bg],
        groups=[RuleGroup(id="g1", name="群組一", enabled=True, rule_ids=["r-a"])],
    )
    _load_task(win, "taskA")
    issues = win._collect_start_check_issues(["g1"])
    bg_issues = [it for it in issues if it["rule_id"] == "r-bg"]
    assert bg_issues, "背景規則的問題必須出現在啟動前檢核"
    assert bg_issues[0]["step_idx"] == 0
    assert bg_issues[0]["background"] is True


def test_start_check_uses_unsaved_editor_steps(real_mainwindow, write_task, make_step, make_rule):
    """編輯器裡還沒存檔的壞步驟也要被檢核到（否則要到執行期才 BLOCKED）。"""
    win = real_mainwindow
    write_task(
        "taskA",
        [make_rule("r-a", "規則A", [make_step("detect", text="好")])],
        groups=[RuleGroup(id="g1", name="群組一", enabled=True, rule_ids=["r-a"])],
    )
    _load_task(win, "taskA")
    assert win._collect_start_check_issues(["g1"]) == []
    # 使用者在編輯器把偵測文字清空，但還沒存檔
    win._selected_rule_id = "r-a"
    win._step_list.set_steps([Step(type="detect", params={"text": ""})])
    issues = win._collect_start_check_issues(["g1"])
    assert issues, "未存檔的編輯內容也必須一起檢核"
    assert issues[0]["step_idx"] == 0


def test_start_check_skips_disabled_rules(real_mainwindow, write_task, make_step, make_rule):
    """停用規則不會執行 → 不列入檢核。"""
    win = real_mainwindow
    write_task(
        "taskA",
        [make_rule("r-a", "停用規則", [make_step("detect", text="")], enabled=False)],
        groups=[RuleGroup(id="g1", name="群組一", enabled=True, rule_ids=["r-a"])],
    )
    _load_task(win, "taskA")
    assert win._collect_start_check_issues(["g1"]) == []


def test_rule_hard_problems_keeps_legacy_zero_click_block(real_mainwindow, make_rule, make_step):
    """既有硬擋行為保留：自訂點擊 (0,0) 仍擋（不放寬驗證）。"""
    win = real_mainwindow
    rule = make_rule("r-a", "規則A", [make_step("click", target="custom", x=0, y=0)])
    problems = win._rule_hard_problems(rule)
    assert T("notif.rule_validation_zero_click", idx=1) in problems


def test_rule_hard_problems_matches_core_preflight(real_mainwindow, make_rule, make_step):
    """GUI 的硬擋清單與 core preflight 的阻擋問題一致（同一來源）。"""
    win = real_mainwindow
    rule = make_rule(
        "r-a",
        "規則A",
        [make_step("sum", gate=True, operator=">=", value=10, roi={})],
    )
    problems = win._rule_hard_problems(rule)
    assert T("exec_log.reason.sum_gate_roi_unset") in problems


def test_start_check_dialog_selects_target(qt_app):
    """檢核清單按「定位到這一步」→ 記下目標（呼叫端在關閉後定位）。"""
    dlg_mod = load_sibling("start_check_dialog", "gui/start_check_dialog.py")
    issues = [
        {
            "rule_id": "r-1",
            "rule_name": "規則A",
            "step_idx": 2,
            "severity": "blocked",
            "text": "偵測關鍵字為空白",
            "background": False,
        }
    ]
    dlg = dlg_mod.StartCheckDialog(None, issues)
    buttons = [b for b in dlg.findChildren(QPushButton) if b.text() == T("start.check_locate")]
    assert len(buttons) == 1
    buttons[0].click()
    assert dlg.selected_target == ("r-1", 2, "規則A")
    dlg.deleteLater()


def test_start_check_dialog_marks_background_rule(qt_app):
    """背景規則在清單上要標出來（使用者才知道那是常駐監控）。"""
    dlg_mod = load_sibling("start_check_dialog", "gui/start_check_dialog.py")
    dlg = dlg_mod.StartCheckDialog(
        None,
        [
            {
                "rule_id": "r-bg",
                "rule_name": "背景規則",
                "step_idx": None,
                "severity": "blocked",
                "text": "偵測關鍵字為空白",
                "background": True,
            }
        ],
    )
    labels = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert any(T("start.check_background") in text for text in labels)
    dlg.deleteLater()


# ── 4. 整合：_start_loop 真的被檢核擋下 ────────────────────────────────


class _FakeStartCheckDialog:
    """假的檢核對話框：記錄收到的問題，不開真實視窗。"""

    shown: list = []

    def __init__(self, parent, issues, warnings=None):
        self.issues = list(issues)
        self.warnings = list(warnings or [])
        self.selected_target = None

    def exec(self):
        type(self).shown.append(self.issues)
        return 0


@pytest.fixture
def start_win(real_mainwindow, monkeypatch):
    """可驅動 _start_loop 的主視窗（視窗選單／存檔／訊息框皆以假物件取代）。"""
    win = real_mainwindow
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(
        win, "_window_combo", type("_Combo", (), {"currentText": lambda self: "測試視窗"})()
    )
    monkeypatch.setattr(win, "_save_current_rule", lambda: None)
    monkeypatch.setattr(win, "_flush_save", lambda: True)
    monkeypatch.setattr(win, "_is_bg_mode", lambda: False)
    win._task_load_failed = False
    _FakeStartCheckDialog.shown = []
    return win


def test_start_loop_blocked_by_preflight_does_not_start(start_win, monkeypatch):
    """檢核未通過 → 顯示清單且不得啟動。"""
    win = start_win
    win._rules = [
        Rule(id="r-a", name="規則A", enabled=True, steps=[Step(type="detect", params={"text": ""})])
    ]
    win._groups = [RuleGroup(id="g1", name="群組一", enabled=True, rule_ids=["r-a"])]
    monkeypatch.setattr(_gui, "StartCheckDialog", _FakeStartCheckDialog)
    win._start_loop(group_ids=["g1"])
    assert _FakeStartCheckDialog.shown, "有阻擋問題時必須顯示檢核清單"
    assert _FakeStartCheckDialog.shown[0][0]["rule_id"] == "r-a"
    assert _FakeStartCheckDialog.shown[0][0]["step_idx"] == 0
    assert win._loop is None, "檢核未通過不得啟動循環"
    assert not getattr(win, "_is_starting", False)


def test_start_loop_clean_task_shows_no_check_dialog(start_win, monkeypatch):
    """沒有問題時不得顯示檢核清單（不得增加無謂的阻擋）。"""
    win = start_win
    win._rules = [
        Rule(
            id="r-a", name="規則A", enabled=True, steps=[Step(type="detect", params={"text": "好"})]
        )
    ]
    win._groups = [RuleGroup(id="g1", name="群組一", enabled=True, rule_ids=["r-a"])]
    monkeypatch.setattr(_gui, "StartCheckDialog", _FakeStartCheckDialog)

    class _StopAfterCheck(Exception):
        pass

    def _boom():
        raise _StopAfterCheck()

    monkeypatch.setattr(win, "_save_current_rule", _boom)
    with pytest.raises(_StopAfterCheck):
        win._start_loop(group_ids=["g1"])
    assert not _FakeStartCheckDialog.shown, "沒有問題時不得顯示檢核清單"
