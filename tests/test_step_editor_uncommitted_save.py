"""Step Editor「未提交輸入值」的保存回歸測試（Phase 2-4b-1）。

缺陷背景
--------
`MainWindow._do_debounced_save()` 是所有路徑寫入任務 JSON 的唯一底層函式
（自動儲存 timer、`_flush_save()`、`_quit_app()` 都會走到它）。
修復前它直接寫入 `self._rules`，從不先提交展開中的 Step 表單；
而各 Step 表單的值只存在於 Qt widget，直到 `save()` 被呼叫才寫回 `Step.params`。
因此使用者尚未讓輸入框失去焦點（未觸發 `editingFinished`）時輸入的值，
會在存檔 / 退出時被舊值覆蓋而遺失。

修復
----
寫入磁碟前先呼叫 `_commit_open_step_form()`（內部走既有的
`get_steps() → _save_expanded() → 表單.save()`），不重建表單、不發
`steps_changed`、不改變展開狀態與 Step 順序。

本檔全部使用真實 MainWindow + 真實 Step 表單 + 暫存目錄中的實際 JSON 檔案驗證，
不使用 mock 斷言「某函式有被呼叫」來代替磁碟結果。
"""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QFileDialog  # noqa: E402

# ── 輔助 ────────────────────────────────────────────────────────────────────


def _read_task_json(isolated_data_dir, name: str) -> dict:
    path = isolated_data_dir / "tasks" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _saved_params(isolated_data_dir, name: str, rule_index: int = 0, step_index: int = 0) -> dict:
    data = _read_task_json(isolated_data_dir, name)
    return data["rules"][rule_index]["steps"][step_index]["params"]


def _open_form(win, step, index: int = 0):
    """讓 Step 列表顯示指定 step 並展開其表單（回傳展開中的表單）。"""
    win._rules[0].steps = (
        list(win._rules[0].steps[:index]) + [step] + list(win._rules[0].steps[index + 1 :])
    )
    win._step_list._collapse()
    win._step_list.set_steps(win._rules[0].steps)
    win._step_list._toggle_expand(index)
    form = win._step_list._expanded_form
    assert form is not None, "表單必須成功展開"
    return form


def _setup_task(win, write_task, make_rule, make_step, name="t1", steps=None, rules=None):
    """建立任務並載入（第一次載入不會觸發 flush，磁碟內容保持原樣）。"""
    if rules is None:
        rules = [make_rule("r0", "規則零", steps or [make_step("wait", ms=500)])]
    write_task(name, rules)
    win._on_task_changed(name)
    return win


# ── A. Wait ────────────────────────────────────────────────────────────────


def test_wait_uncommitted_value_saved_by_flush_save(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """一般數值：未觸發 editingFinished 的值也必須寫入磁碟。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(1234)
    assert win._rules[0].steps[0].params["ms"] == 500, "尚未 commit 時 params 應仍是舊值"

    win._flush_save()

    assert _saved_params(isolated_data_dir, "t1")["ms"] == 1234


@pytest.mark.parametrize("value", [0, 1, 59999, 60000])
def test_wait_uncommitted_boundary_values_saved(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir, value
):
    """合法上下限（含 0 與上限 60000）都必須完整保存。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(value)

    win._flush_save()

    assert _saved_params(isolated_data_dir, "t1")["ms"] == value


@pytest.mark.parametrize(("typed", "expected"), [(99999, 60000), (-5, 0)])
def test_wait_out_of_range_input_keeps_existing_clamping(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir, typed, expected
):
    """非法輸入沿用既有處理方式（QSpinBox 範圍 0–60000 自動夾限），不得改變單位或上下限。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(typed)
    assert form._ms.value() == expected, "輸入框應夾限到既有上下限"
    assert form._ms.maximum() == 60000 and form._ms.minimum() == 0

    win._flush_save()

    assert _saved_params(isolated_data_dir, "t1")["ms"] == expected


def test_wait_uncommitted_value_saved_by_save_current_rule(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """_save_current_rule() 入口也必須保存未提交值。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(2222)

    win._save_current_rule()
    win._flush_save()

    assert _saved_params(isolated_data_dir, "t1")["ms"] == 2222


def test_wait_uncommitted_value_saved_by_quit_app(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """_quit_app() 退出路徑也必須保存未提交值。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(3333)

    assert win._quit_app() is True

    assert _saved_params(isolated_data_dir, "t1")["ms"] == 3333


def test_wait_uncommitted_value_saved_by_auto_save_timer(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """自動儲存 timer（_save_timer.timeout → _do_debounced_save）路徑也必須保存。

    以 timeout.emit() 直接觸發與 timer 觸發完全相同的 slot，避免等待真實 500ms。
    """
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(4444)

    win._schedule_save()
    assert win._save_timer.isActive(), "debounce timer 應已啟動"
    win._save_timer.timeout.emit()

    assert _saved_params(isolated_data_dir, "t1")["ms"] == 4444


# ── B. Notify ──────────────────────────────────────────────────────────────


def test_notify_uncommitted_message_saved_by_flush_save(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """notify 的 message 欄位未 commit 時也必須保存。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step, steps=[make_step("notify", message="old")])
    form = _open_form(win, make_step("notify", message="old"))
    form._msg.setText("新的訊息")

    win._flush_save()

    assert _saved_params(isolated_data_dir, "t1")["message"] == "新的訊息"


def test_notify_uncommitted_message_saved_by_quit_app(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step, steps=[make_step("notify", message="old")])
    form = _open_form(win, make_step("notify", message="old"))
    form._msg.setText("退出前的訊息")

    assert win._quit_app() is True

    assert _saved_params(isolated_data_dir, "t1")["message"] == "退出前的訊息"


def test_notify_empty_message_is_saved_as_empty_string(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """清空訊息也必須被保存（不得保留舊值）。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step, steps=[make_step("notify", message="old")])
    form = _open_form(win, make_step("notify", message="old"))
    form._msg.setText("")

    win._flush_save()

    assert _saved_params(isolated_data_dir, "t1")["message"] == ""


# ── C. 保存入口 ────────────────────────────────────────────────────────────


def test_manual_export_entry_saves_uncommitted_value(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir, tmp_path, monkeypatch
):
    """手動入口（匯出任務）也必須保存未提交值。

    QFileDialog 屬外部副作用，以 monkeypatch 換成固定路徑；
    磁碟結果仍以真實 JSON 檔案驗證。
    """
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(5555)

    export_path = str(tmp_path / "exported.json")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (export_path, ""))
    )
    monkeypatch.setattr(win, "_copy_task_file", lambda *a, **k: True, raising=False)

    win._on_task_export()

    saved = json.loads(open(export_path, encoding="utf-8").read())
    assert saved["rules"][0]["steps"][0]["params"]["ms"] == 5555
    # 原任務檔也必須同步保存
    assert _saved_params(isolated_data_dir, "t1")["ms"] == 5555


def test_all_save_entry_points_persist_same_value(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """四個保存入口對同一個未提交值都必須得到相同結果。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    for entry in ("flush", "current_rule", "timer", "quit"):
        form = _open_form(win, make_step("wait", ms=500))
        form._ms.setValue(600 + len(entry))
        if entry == "flush":
            win._flush_save()
        elif entry == "current_rule":
            win._save_current_rule()
            win._flush_save()
        elif entry == "timer":
            win._schedule_save()
            win._save_timer.timeout.emit()
        else:
            win._quit_app()
        assert _saved_params(isolated_data_dir, "t1")["ms"] == 600 + len(entry), (
            f"保存入口 {entry} 未保存未提交值"
        )


# ── D. 規則切換 ────────────────────────────────────────────────────────────


def test_switching_rule_saves_rule_a_and_keeps_rule_b(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """切換規則時：Rule A 的未提交值要保存，Rule B 的資料不得被動到。"""
    win = real_mainwindow
    _setup_task(
        win,
        write_task,
        make_rule,
        make_step,
        rules=[
            make_rule("r0", "規則零", [make_step("wait", ms=500)]),
            make_rule("r1", "規則壹", [make_step("wait", ms=700)]),
        ],
    )
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(8888)
    rule_b_before = dict(win._rules[1].steps[0].params)

    # 使用者直接點擊另一條規則（規則樹以 UserRole 存 ("rule", rule_id)）
    item_r1 = None
    root = win._rule_list.invisibleRootItem()
    for i in range(root.childCount()):
        top = root.child(i)
        for j in range(top.childCount()):
            child = top.child(j)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "rule" and data[1] == "r1":
                item_r1 = child
    assert item_r1 is not None, "規則樹中必須找得到 r1"
    win._rule_list.setCurrentItem(item_r1)

    assert win._rules[0].steps[0].params["ms"] == 8888, "Rule A 的未提交值必須保存"
    assert dict(win._rules[1].steps[0].params) == rule_b_before, "Rule B 不得被動到"
    assert win._selected_rule_id == "r1"


def test_switching_back_keeps_latest_value(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """切回 Rule A 後，最新值仍必須存在且已落地。"""
    win = real_mainwindow
    _setup_task(
        win,
        write_task,
        make_rule,
        make_step,
        rules=[
            make_rule("r0", "規則零", [make_step("wait", ms=500)]),
            make_rule("r1", "規則壹", [make_step("wait", ms=700)]),
        ],
    )
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(9999)

    win._selected_rule_id = "r1"
    win._refresh_rule_list()
    win._selected_rule_id = "r0"
    win._refresh_rule_list()

    assert win._rules[0].steps[0].params["ms"] == 9999
    win._flush_save()
    assert _saved_params(isolated_data_dir, "t1")["ms"] == 9999


def test_switching_task_saves_previous_task_uncommitted_value(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """切換任務時，前一個任務的未提交值必須先被保存。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step, name="t1")
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(1212)

    write_task("t2", [make_rule("r9", "另一個任務", [make_step("wait", ms=1)])])
    win._on_task_changed("t2")

    assert _saved_params(isolated_data_dir, "t1")["ms"] == 1212


# ── E. 回歸保護 ────────────────────────────────────────────────────────────


def test_step_order_unchanged_after_flush(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """同步不得改變 Step 順序。"""
    win = real_mainwindow
    steps = [make_step("wait", ms=i) for i in (1, 2, 3)]
    _setup_task(win, write_task, make_rule, make_step, steps=steps)
    form = _open_form(win, make_step("wait", ms=1))
    form._ms.setValue(42)

    win._flush_save()

    data = _read_task_json(isolated_data_dir, "t1")
    assert [s["params"]["ms"] for s in data["rules"][0]["steps"]] == [42, 2, 3]


def test_unknown_step_type_params_preserved_after_flush(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """未知 Step type 與未知 params 必須原樣保留。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    unknown = make_step("future_type", foo="bar", n=7)
    win._rules[0].steps = [unknown]
    win._step_list.set_steps(win._rules[0].steps)

    win._flush_save()

    params = _saved_params(isolated_data_dir, "t1")
    assert params["foo"] == "bar" and params["n"] == 7


def test_jump_empty_target_stays_empty_after_flush(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """未設定的 Jump 目標仍必須保留空字串。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step, steps=[make_step("jump", rule_id="")])
    form = _open_form(win, make_step("jump", rule_id=""))
    assert form._combo.currentData() == ""

    win._flush_save()

    assert _saved_params(isolated_data_dir, "t1")["rule_id"] == ""


def test_other_rule_data_not_overwritten_by_open_form(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """其他規則的資料不得被目前展開的表單覆蓋。"""
    win = real_mainwindow
    _setup_task(
        win,
        write_task,
        make_rule,
        make_step,
        rules=[
            make_rule("r0", "規則零", [make_step("wait", ms=500)]),
            make_rule("r1", "規則壹", [make_step("wait", ms=700)]),
        ],
    )
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(1357)

    win._flush_save()

    data = _read_task_json(isolated_data_dir, "t1")
    by_id = {r["id"]: r for r in data["rules"]}
    assert by_id["r0"]["steps"][0]["params"]["ms"] == 1357
    assert by_id["r1"]["steps"][0]["params"]["ms"] == 700


def test_already_committed_value_saved_and_unchanged(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """已經提交過的值不受影響，且再次同步不得產生額外資料變化。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(1000)
    form._ms.editingFinished.emit()  # 已提交
    before = dict(win._rules[0].steps[0].params)

    win._flush_save()
    win._flush_save()

    assert dict(win._rules[0].steps[0].params) == before
    assert _saved_params(isolated_data_dir, "t1") == before


def test_json_roundtrip_after_flush(real_mainwindow, write_task, make_step, make_rule, rule_engine):
    """同步後的 JSON 重新載入仍須一致（往返不遺失）。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(24680)

    win._flush_save()

    reloaded = rule_engine.load_task("t1")
    assert reloaded[0].steps[0].params["ms"] == 24680


def test_other_step_types_share_the_same_fix(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """其他 Step type 使用同一套提交機制，必須同樣受益（不是只修 wait/notify）。"""
    win = real_mainwindow
    cases = [
        (
            "key",
            {"key": "a"},
            lambda form: form._key.setCurrentIndex(form._key.findData("b")),
            "key",
            "b",
        ),
        ("scroll", {"direction": "up"}, lambda form: form._amount.setValue(7), "amount", 7),
        ("detect", {"text": "old"}, lambda form: form._text.setText("新文字"), "text", "新文字"),
        (
            "compare",
            {"operator": ">", "value": 1, "pattern": "x"},
            lambda form: form._value.setValue(42),
            "value",
            42,
        ),
    ]
    for step_type, params, mutate, field, expected in cases:
        step = make_step(step_type, **params)
        _setup_task(win, write_task, make_rule, make_step, steps=[step])
        form = _open_form(win, step)
        mutate(form)
        win._flush_save()
        saved = _saved_params(isolated_data_dir, "t1")
        assert saved[field] == expected, f"{step_type} 的未提交值未被保存"


def test_jump_target_selection_is_committed(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """Jump 的目標選擇同樣屬於「未提交值」，必須一起被保存。

    ComboBox 的「未設定目標」固定在 index 0（見 `_JumpStepForm.__init__`），
    因此這裡改用 findData 精準定位目標規則，而不是用索引位置。
    """
    win = real_mainwindow
    _setup_task(
        win,
        write_task,
        make_rule,
        make_step,
        rules=[
            make_rule("r0", "規則零", [make_step("jump", rule_id="")]),
            make_rule("r1", "規則壹", [make_step("wait", ms=700)]),
        ],
    )
    form = _open_form(win, make_step("jump", rule_id=""))
    target_idx = form._combo.findData("r1")
    assert target_idx >= 0, "ComboBox 中必須找得到目標規則 r1"
    form._combo.setCurrentIndex(target_idx)
    assert win._rules[0].steps[0].params["rule_id"] == "", "尚未 commit 時 params 應仍是舊值"

    win._flush_save()

    assert _saved_params(isolated_data_dir, "t1", rule_index=0)["rule_id"] == "r1"


# ── F. 邊界條件 ────────────────────────────────────────────────────────────


def test_flush_save_without_selected_rule_is_safe(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """沒有選取 Rule 時不得拋例外，也不得清空磁碟內容。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    win._selected_rule_id = None
    win._step_list._collapse()

    win._flush_save()

    assert len(_read_task_json(isolated_data_dir, "t1")["rules"]) == 1


def test_flush_save_without_expanded_form_is_safe(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """沒有展開表單時，磁碟內容不得被「提交表單」路徑改動。

    基準取「載入後的記憶體 params」而非剛寫入的檔案：
    程式載入任務時會由 `core/rule_migration._normalize_step` 補上預設欄位
    （如 roi / on_fail），這是既有的正規化行為，與本次修復無關；
    這裡要驗證的是「提交路徑沒有額外動到資料」。
    """
    win = real_mainwindow
    _setup_task(
        win,
        write_task,
        make_rule,
        make_step,
        steps=[make_step("compare", operator=">", value=1, pattern="x")],
    )
    win._step_list._collapse()
    assert win._step_list._expanded_form is None, "前提：目前沒有展開中的表單"

    before = dict(win._rules[0].steps[0].params)
    win._flush_save()
    after = _saved_params(isolated_data_dir, "t1")

    assert after == before, "未展開表單時磁碟內容不得被提交路徑改動"
    assert dict(win._rules[0].steps[0].params) == before, "未展開表單時記憶體內容不得改動"


def test_flush_save_without_task_loaded_is_safe(real_mainwindow):
    """沒有載入任務時 _flush_save() 應直接回 True。"""
    win = real_mainwindow
    assert win._current_task == ""
    assert win._flush_save() is True


def test_flush_save_after_form_rebuilt_uses_current_form(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """表單被重建後，提交必須作用於「目前」的表單。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(11)
    win._step_list._rebuild()
    win._step_list._toggle_expand(0)
    new_form = win._step_list._expanded_form
    new_form._ms.setValue(22)

    win._flush_save()

    assert _saved_params(isolated_data_dir, "t1")["ms"] == 22


def test_commit_failure_keeps_original_file_intact(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir, monkeypatch
):
    """表單提交拋例外時不得覆蓋原檔（不可讓不完整資料覆蓋原檔）。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(9999)

    def boom():
        raise ValueError("表單儲存失敗")

    monkeypatch.setattr(form, "save", boom)

    assert win._flush_save() is False, "提交失敗時必須回報失敗"
    assert _saved_params(isolated_data_dir, "t1")["ms"] == 500, "原檔不得被覆蓋"


def test_runtime_error_during_commit_keeps_original_file_intact(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir, monkeypatch
):
    """提交拋出非「widget 已銷毀」的 RuntimeError 時同樣不得覆蓋原檔。

    `_commit_open_step_form` 只對含 "has been deleted" 的 RuntimeError 視為
    widget 已失效（可略過提交繼續存檔），其餘 RuntimeError 一律視為提交失敗。
    """
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(9999)

    def boom():
        raise RuntimeError("表單內部錯誤")

    monkeypatch.setattr(form, "save", boom)

    assert win._flush_save() is False, "提交失敗時必須回報失敗"
    assert _saved_params(isolated_data_dir, "t1")["ms"] == 500, "原檔不得被覆蓋"


def test_commit_without_step_list_is_safe(
    real_mainwindow, write_task, make_step, make_rule, monkeypatch
):
    """視窗尚未建立 Step 清單時，提交步驟必須安全略過（不得拋例外）。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    monkeypatch.delattr(win, "_step_list")  # 模擬 UI 尚未建置完成

    assert win._commit_open_step_form() is True


def test_write_failure_keeps_original_file_intact(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir, monkeypatch
):
    """寫入失敗時原檔必須保持完整。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(8888)

    monkeypatch.setattr(win, "_do_debounced_save", lambda: False)

    assert win._flush_save() is False
    assert _saved_params(isolated_data_dir, "t1")["ms"] == 500


def test_deleted_form_widget_is_tolerated(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """表單 widget 已被 Qt 銷毀時不得崩潰，仍要保存其餘資料。

    已銷毀的 widget 無法再取值，其未提交內容本來就無法搶救；
    預期行為是「保留最後已知值並照常存檔」，不是讓整次存檔失敗。
    """
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(6543)
    sip.delete(form)  # 模擬 widget 被 Qt 銷毀

    assert win._flush_save() is True, "表單失效不得讓存檔整個失敗"

    data = _read_task_json(isolated_data_dir, "t1")
    assert len(data["rules"]) == 1, "其餘資料仍必須完整保存"
    assert len(data["rules"][0]["steps"]) == 1
    assert data["rules"][0]["steps"][0]["params"]["ms"] == 500, "保留最後已知值"


def test_consecutive_saves_do_not_duplicate_data(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """連續觸發保存不得產生重複資料。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(31337)

    for _ in range(5):
        win._flush_save()

    data = _read_task_json(isolated_data_dir, "t1")
    assert len(data["rules"]) == 1
    assert len(data["rules"][0]["steps"]) == 1
    assert data["rules"][0]["steps"][0]["params"] == {"ms": 31337}


def test_quit_app_with_pending_save_timer_saves_latest_value(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """退出時若還有未觸發的 debounce timer，最新值仍必須被保存。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(4567)
    win._schedule_save()
    assert win._save_timer.isActive()

    assert win._quit_app() is True

    assert _saved_params(isolated_data_dir, "t1")["ms"] == 4567


# ── G. 副作用（§八）────────────────────────────────────────────────────────


def test_flush_save_has_no_side_effects(
    real_mainwindow, write_task, make_step, make_rule, call_recorder
):
    """同步不得造成：規則樹重建、表單重建、額外 steps_changed、表單折疊、切換選取規則。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(5150)

    emitted = []
    win._step_list.steps_changed.connect(lambda: emitted.append(1))
    call_recorder.reset()
    selected_before = win._selected_rule_id
    expanded_idx_before = win._step_list._expanded_idx
    form_before = win._step_list._expanded_form
    rows_before = list(win._step_list._rows)

    win._flush_save()

    assert not emitted, "不得額外觸發 steps_changed"
    assert call_recorder.get("MainWindow._refresh_rule_list") == 0, "不得重建規則樹"
    assert call_recorder.get("_StepListWidget._rebuild") == 0, "不得重建 Step 清單"
    assert win._selected_rule_id == selected_before, "不得改變選取的規則"
    assert win._step_list._expanded_idx == expanded_idx_before, "不得折疊表單"
    assert win._step_list._expanded_form is form_before, "不得重建表單"
    assert list(win._step_list._rows) == rows_before, "不得重建 row"


def test_flush_save_does_not_emit_steps_changed_via_signal(
    real_mainwindow, write_task, make_step, make_rule
):
    """再次確認：單次 _flush_save() 不得發出任何 steps_changed。"""
    win = real_mainwindow
    _setup_task(win, write_task, make_rule, make_step)
    form = _open_form(win, make_step("wait", ms=500))
    form._ms.setValue(6060)

    emitted = []
    win._step_list.steps_changed.connect(lambda: emitted.append(1))
    win._flush_save()

    assert emitted == []
