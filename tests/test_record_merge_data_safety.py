"""錄製轉換合併時的 Step 編輯資料安全性（Phase 2-4b-1a）。

背景
----
`_on_convert_done()` 會從**磁碟**讀取既有任務資料，再把錄製轉換結果合併進去。
若合併目標就是目前開啟的任務，而 GUI 記憶體中仍有尚未寫盤的修改
（已提交到記憶體的 Step 變更、或展開中 Step 表單尚未觸發 editingFinished 的欄位值），
磁碟舊版會把它們蓋掉，造成資料遺失。

本檔以真實 MainWindow + 真實磁碟 JSON 驗證：
  A. 當前任務：未提交表單值
  B. 當前任務：已提交但尚未寫盤
  C. 非當前任務合併
  D. 保存失敗必須中止合併
  E. Debounce timer 競態
  F. 合併後重新載入
"""

import json
import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QMessageBox  # noqa: E402

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

_gui = load_sibling("gui_main", "gui/06_gui_main.py")


# ── 輔助 ─────────────────────────────────────────────────────────────────────


def _task_file(isolated_data_dir, name):
    return isolated_data_dir / "tasks" / f"{name}.json"


def _read_json(isolated_data_dir, name):
    return json.loads(_task_file(isolated_data_dir, name).read_text(encoding="utf-8"))


def _recording_result(rule_engine, make_step, rule_id="rec1", group_id="recg1"):
    """模擬一次「錄製轉換」的結果：一條新規則 + 一個新群組。"""
    rule = rule_engine.Rule(
        id=rule_id,
        name="錄製規則",
        enabled=True,
        steps=[make_step("notify", message="from-recording")],
    )
    group = rule_engine.RuleGroup(id=group_id, name="錄製群組", rule_ids=[rule_id])
    return {"rules": [rule], "groups": [group], "stats": {}}


def _run_merge(win, merge_into, result, task_name=None):
    """走真實的 `_on_convert_done()` 流程執行一次錄製轉換合併。"""
    win._pending_merge_into = merge_into
    win._pending_task_name = task_name or merge_into
    win._pending_session_dirs = []
    win._on_convert_done(result)


def _wait_step_rule(make_rule, make_step, ms=500):
    return make_rule("r0", "既有規則", [make_step("wait", ms=ms)])


@pytest.fixture
def event_log(monkeypatch):
    """記錄「存檔」與「寫檔」的先後順序，用來驗證合併前後的時序。

    * ("flush", task)  → _flush_save() 被呼叫，當下的目前任務名稱
    * ("write", task)  → 任務 JSON 被寫入
    """
    events = []

    orig_flush = _gui.MainWindow._flush_save

    def flush(self):
        events.append(("flush", getattr(self, "_current_task", "")))
        return orig_flush(self)

    monkeypatch.setattr(_gui.MainWindow, "_flush_save", flush)

    orig_save = _gui.save_task_with_groups

    def save(rules, groups, path):
        events.append(("write", Path(path).stem))
        return orig_save(rules, groups, path)

    monkeypatch.setattr(_gui, "save_task_with_groups", save)
    return events


@pytest.fixture
def no_modal(monkeypatch):
    """關掉會阻塞測試的 modal 對話框，並記錄呼叫。"""
    calls = {"critical": [], "warning": []}
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *args: calls["critical"].append(args))
    )
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *args: calls["warning"].append(args))
    )
    return calls


# ── A. 當前任務：未提交表單值 ─────────────────────────────────────────────────


def test_merge_into_current_task_keeps_uncommitted_form_value(
    real_mainwindow, write_task, make_step, make_rule, rule_engine, isolated_data_dir
):
    """展開中的表單尚未觸發 editingFinished，合併後該值仍必須存在。"""
    win = real_mainwindow
    write_task("t1", [_wait_step_rule(make_rule, make_step)])
    win._on_task_changed("t1")

    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    form._ms.setValue(9999)  # 只在 widget 裡，未觸發 editingFinished
    assert win._rules[0].steps[0].params["ms"] == 500, "前提：記憶體仍是舊值"

    _run_merge(win, "t1", _recording_result(rule_engine, make_step))

    data = _read_json(isolated_data_dir, "t1")
    wait_params = [s["params"] for r in data["rules"] for s in r["steps"] if s["type"] == "wait"]
    assert wait_params, "既有 wait 步驟不應消失"
    assert wait_params[0]["ms"] == 9999, "未提交的表單值必須在合併後存活"


# ── B. 當前任務：已提交但尚未寫盤 ─────────────────────────────────────────────


def test_merge_into_current_task_keeps_committed_but_unsaved_value(
    real_mainwindow, write_task, make_step, make_rule, rule_engine, isolated_data_dir
):
    """已提交到 GUI 記憶體但尚未寫入磁碟的 Step 變更，合併後仍必須存在。"""
    win = real_mainwindow
    write_task("t1", [_wait_step_rule(make_rule, make_step)])
    win._on_task_changed("t1")

    win._rules[0].steps[0].params["ms"] = 7777  # 已進記憶體，未寫盤
    assert _read_json(isolated_data_dir, "t1")["rules"][0]["steps"][0]["params"]["ms"] == 500

    _run_merge(win, "t1", _recording_result(rule_engine, make_step))

    data = _read_json(isolated_data_dir, "t1")
    wait_params = [s["params"] for r in data["rules"] for s in r["steps"] if s["type"] == "wait"]
    assert wait_params[0]["ms"] == 7777, "已提交但未寫盤的值必須在合併後存活"


# ── C. 非當前任務合併 ───────────────────────────────────────────────────────


def test_merge_into_other_task_does_not_flush_current_task_first(
    real_mainwindow, write_task, make_step, make_rule, rule_engine, isolated_data_dir, event_log
):
    """合併到其他任務時，不得為了合併而額外 flush 目前任務。"""
    win = real_mainwindow
    write_task("taskA", [_wait_step_rule(make_rule, make_step)])
    write_task("taskB", [make_rule("b0", "B 既有規則", [make_step("wait", ms=100)])])
    win._on_task_changed("taskA")

    win._rules[0].steps[0].params["ms"] = 5555  # taskA 有未寫盤的修改
    event_log.clear()

    _run_merge(win, "taskB", _recording_result(rule_engine, make_step))

    write_b = next(i for i, e in enumerate(event_log) if e == ("write", "taskB"))
    flush_a = [i for i, e in enumerate(event_log) if e == ("flush", "taskA")]
    assert not flush_a or min(flush_a) > write_b, "合併 taskB 前不得先 flush taskA"

    # taskB 的既有合併行為不受影響
    data_b = _read_json(isolated_data_dir, "taskB")
    ids = {r["id"] for r in data_b["rules"]}
    assert ids == {"b0", "rec1"}, "taskB 應同時保有既有規則與錄製結果"
    # taskA 沒有被塞入錄製結果
    ids_a = {r["id"] for r in _read_json(isolated_data_dir, "taskA")["rules"]}
    assert ids_a == {"r0"}, "taskA 不得被合併結果污染"


def test_merge_into_other_task_keeps_current_task_data_intact(
    real_mainwindow, write_task, make_step, make_rule, rule_engine, isolated_data_dir
):
    """合併其他任務不得改變目前任務的資料。

    註：既有行為是合併完成後切到合併目標任務（`_on_convert_done` 末尾
    `setCurrentIndex(target)`），這與本次修復無關，不得被誤判為副作用。
    """
    win = real_mainwindow
    write_task("taskA", [_wait_step_rule(make_rule, make_step)])
    write_task("taskB", [make_rule("b0", "B 既有規則", [make_step("wait", ms=100)])])
    win._on_task_changed("taskA")

    win._rules[0].steps[0].params["ms"] = 5555

    _run_merge(win, "taskB", _recording_result(rule_engine, make_step))

    # taskA 不得被合併結果污染
    data_a = _read_json(isolated_data_dir, "taskA")
    assert {r["id"] for r in data_a["rules"]} == {"r0"}, "taskA 不得被合併結果污染"
    assert [s["type"] for r in data_a["rules"] for s in r["steps"]] == ["wait"], (
        "taskA 的 Step 不得被改動"
    )

    # taskB 的既有合併行為正常
    data_b = _read_json(isolated_data_dir, "taskB")
    assert {r["id"] for r in data_b["rules"]} == {"b0", "rec1"}
    assert any(
        s["params"].get("message") == "from-recording" for r in data_b["rules"] for s in r["steps"]
    ), "taskB 必須含錄製轉換結果"

    # 既有行為：合併完成後切到合併目標任務
    assert win._current_task == "taskB"


# ── D. 保存失敗 ─────────────────────────────────────────────────────────────


def test_merge_aborts_when_saving_current_task_fails(
    real_mainwindow,
    write_task,
    make_step,
    make_rule,
    rule_engine,
    isolated_data_dir,
    monkeypatch,
    no_modal,
):
    """保存失敗必須中止合併：舊檔不得被覆寫，GUI 資料不得被清除。"""
    win = real_mainwindow
    write_task("t1", [_wait_step_rule(make_rule, make_step)])
    win._on_task_changed("t1")

    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    form._ms.setValue(9999)

    before = _task_file(isolated_data_dir, "t1").read_bytes()

    monkeypatch.setattr(_gui, "save_task_with_groups", lambda *a, **k: False)

    _run_merge(win, "t1", _recording_result(rule_engine, make_step))

    # 舊檔完全沒被覆寫（也沒有被部分寫入）
    assert _task_file(isolated_data_dir, "t1").read_bytes() == before, "舊任務檔不得被覆寫"
    # 合併沒有發生：錄製結果不在檔案裡
    data = _read_json(isolated_data_dir, "t1")
    assert {r["id"] for r in data["rules"]} == {"r0"}, "合併必須被中止"
    # 使用者仍保有未保存的資料
    assert form._ms.value() == 9999, "表單上的未提交值不得被清除"
    # 使用者收到既有錯誤回饋
    assert no_modal["critical"], "必須以既有 modal 提示告知使用者"


def test_merge_abort_keeps_pending_form_value_in_memory(
    real_mainwindow, write_task, make_step, make_rule, rule_engine, monkeypatch, no_modal
):
    """保存失敗中止合併後，記憶體中的 Step 資料仍保留。"""
    win = real_mainwindow
    write_task("t1", [_wait_step_rule(make_rule, make_step)])
    win._on_task_changed("t1")

    win._step_list._toggle_expand(0)
    win._step_list._expanded_form._ms.setValue(9999)

    monkeypatch.setattr(_gui, "save_task_with_groups", lambda *a, **k: False)

    _run_merge(win, "t1", _recording_result(rule_engine, make_step))

    assert win._rules[0].steps[0].params["ms"] == 9999, "記憶體中的已提交值不得被清除"
    assert len(win._rules) == 1, "記憶體規則不得被合併結果取代"


# ── E. Debounce timer 競態 ──────────────────────────────────────────────────


def test_pending_debounce_timer_does_not_overwrite_merge_result(
    real_mainwindow, write_task, make_step, make_rule, rule_engine, isolated_data_dir
):
    """合併前若已有 pending 的 debounce save，合併後它不得反向覆寫合併結果。"""
    win = real_mainwindow
    write_task("t1", [_wait_step_rule(make_rule, make_step)])
    win._on_task_changed("t1")

    win._step_list._toggle_expand(0)
    win._step_list._expanded_form._ms.setValue(9999)
    win._schedule_save()  # 建立尚未觸發的 pending debounce save
    assert win._save_timer.isActive(), "前提：pending timer 存在"

    _run_merge(win, "t1", _recording_result(rule_engine, make_step))

    assert not win._save_timer.isActive(), "合併後不得留有 pending 的舊 debounce save"

    # 主動觸發原本 pending 的 timer（模擬它在合併之後才到期的情況）
    win._do_debounced_save()

    data = _read_json(isolated_data_dir, "t1")
    ids = {r["id"] for r in data["rules"]}
    assert "rec1" in ids, "合併結果不得被舊的 pending save 覆蓋掉"
    wait_params = [s["params"] for r in data["rules"] for s in r["steps"] if s["type"] == "wait"]
    assert wait_params[0]["ms"] == 9999, "未提交值也不得被覆蓋"


def test_merge_does_not_duplicate_pending_save(
    real_mainwindow, write_task, make_step, make_rule, rule_engine, event_log
):
    """合併不得造成非預期的重複存檔。"""
    win = real_mainwindow
    write_task("t1", [_wait_step_rule(make_rule, make_step)])
    win._on_task_changed("t1")

    win._step_list._toggle_expand(0)
    win._step_list._expanded_form._ms.setValue(9999)
    event_log.clear()

    _run_merge(win, "t1", _recording_result(rule_engine, make_step))

    flushes = [e for e in event_log if e[0] == "flush"]
    assert flushes, "合併前必須先 flush 當前任務，否則磁碟舊版會蓋掉未存檔資料"
    # 第一次 flush 必須發生在任何寫檔之前（= 合併前的落地）
    first_write = next(i for i, e in enumerate(event_log) if e[0] == "write")
    first_flush = next(i for i, e in enumerate(event_log) if e[0] == "flush")
    assert first_flush < first_write, "必須先落地再合併"


# ── F. 合併後重新載入 ───────────────────────────────────────────────────────


def test_reload_after_merge_keeps_everything(
    real_mainwindow, write_task, make_step, make_rule, rule_engine, isolated_data_dir
):
    """合併後重新載入：既有規則、Step、錄製結果、未存檔編輯、群組關聯都要正確。"""
    win = real_mainwindow
    write_task(
        "t1",
        [
            _wait_step_rule(make_rule, make_step),
            make_rule("r1", "第二規則", [make_step("wait", ms=300)]),
        ],
        groups=[rule_engine.RuleGroup(id="g1", name="既有群組", rule_ids=["r0", "r1"])],
    )
    win._on_task_changed("t1")

    win._step_list._toggle_expand(0)
    win._step_list._expanded_form._ms.setValue(9999)

    _run_merge(win, "t1", _recording_result(rule_engine, make_step))

    # 重新載入（走產品自己的載入路徑）
    task_path = str(_task_file(isolated_data_dir, "t1"))
    rules = rule_engine.load_task("t1")
    groups = rule_engine.load_groups(task_path)

    by_id = {r.id: r for r in rules}
    assert set(by_id) == {"r0", "r1", "rec1"}, "既有規則與錄製結果都必須存在"

    # 既有 Step 仍在
    assert [s.type for s in by_id["r0"].steps] == ["wait"]
    assert [s.type for s in by_id["r1"].steps] == ["wait"]
    # 未存檔的編輯內容仍在
    assert by_id["r0"].steps[0].params["ms"] == 9999
    # 錄製結果內容正確
    assert by_id["rec1"].steps[0].params["message"] == "from-recording"

    # groups / rule 關聯
    gids = {g.id: g for g in groups}
    assert "g1" in gids, "既有群組不得遺失"
    assert set(gids["g1"].rule_ids) == {"r0", "r1"}
    assert "recg1" in gids, "錄製結果的群組必須存在"
    assert gids["recg1"].rule_ids == ["rec1"]


def test_reload_after_merge_keeps_unsaved_value_in_edited_rule(
    real_mainwindow, write_task, make_step, make_rule, rule_engine, isolated_data_dir
):
    """合併後重新載入，未存檔的 Step 編輯內容仍在（逐規則檢查）。"""
    win = real_mainwindow
    write_task("t1", [_wait_step_rule(make_rule, make_step)])
    win._on_task_changed("t1")

    win._rules[0].steps[0].params["ms"] = 7777

    _run_merge(win, "t1", _recording_result(rule_engine, make_step))

    rules = rule_engine.load_task("t1")
    by_id = {r.id: r for r in rules}
    assert by_id["r0"].steps[0].params["ms"] == 7777
