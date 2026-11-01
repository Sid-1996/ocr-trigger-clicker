"""Step Editor 持久化與生命週期測試（Phase 2-4a 建立，Phase 2-4b-1 更新）。

涵蓋：
  T-4  _flush_save / _quit_app 的「成功存檔路徑」
       （既有測試只走到失敗分支或提前 return，成功路徑從未被執行）
  T-5  未觸發 editingFinished 的輸入值，在存檔 / 退出時的處置
  Qt   Widget 生命週期：重建後舊 widget 必須真的被釋放

Phase 2-4b-1 變更：
  舊缺陷 —— _do_debounced_save() 直接把 self._rules 寫入磁碟，不先提交展開中的
  Step 表單；使用者尚未讓輸入框失去焦點（未觸發 editingFinished）時輸入的值
  只存在於 Qt widget，於是被舊值覆蓋而遺失。
  修復後 —— 寫入磁碟前一律先提交表單，下列斷言已翻轉為「最新值成功保存」，
  並保留能重現舊缺陷的說明。修復的完整回歸測試見
  tests/test_step_editor_uncommitted_save.py。
"""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QCoreApplication, QEvent  # noqa: E402


def _read_task_json(isolated_data_dir, name: str) -> dict:
    path = isolated_data_dir / "tasks" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _drain_deferred_delete(qt_app) -> None:
    """確定性回收 DeferredDelete（單靠 processEvents 不會釋放）。"""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_app.processEvents()


# ── T-4：成功存檔路徑 ───────────────────────────────────────────────────────


def test_flush_save_writes_json(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    win._on_task_changed("t1")

    assert win._flush_save() is True

    data = _read_task_json(isolated_data_dir, "t1")
    assert len(data["rules"]) == 1
    assert data["rules"][0]["id"] == "r0"
    assert data["rules"][0]["steps"][0]["params"]["ms"] == 500


def test_saved_json_reloads_with_same_step_params(
    real_mainwindow, write_task, make_step, make_rule, rule_engine
):
    """存檔後重新載入，step 參數必須一致（往返不遺失）。"""
    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule(
                "r0",
                "規則零",
                [make_step("wait", ms=1234), make_step("jump", rule_id="rX")],
            )
        ],
    )
    win._on_task_changed("t1")

    assert win._flush_save() is True

    reloaded = rule_engine.load_task("t1")
    assert len(reloaded) == 1
    assert reloaded[0].steps[0].params["ms"] == 1234
    assert reloaded[0].steps[1].params["rule_id"] == "rX"


def test_quit_app_saves_current_rule_to_disk(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """_quit_app 的成功存檔路徑：退出前必須把規則寫進磁碟。

    既有測試（tests/test_gui_save_safety.py）只覆蓋失敗分支與跳過存檔的分支，
    這裡補上成功路徑。
    """
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=777)])])
    win._on_task_changed("t1")

    assert win._quit_app() is True

    data = _read_task_json(isolated_data_dir, "t1")
    assert len(data["rules"]) == 1
    assert data["rules"][0]["steps"][0]["params"]["ms"] == 777


def test_save_current_rule_persists_step_params(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """_save_current_rule 會把 step 參數寫回規則並排入存檔。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    win._on_task_changed("t1")

    win._step_list._toggle_expand(0)
    win._step_list._expanded_form._ms.setValue(2468)
    win._save_current_rule()

    assert win._rules[0].steps[0].params["ms"] == 2468
    win._flush_save()
    data = _read_task_json(isolated_data_dir, "t1")
    assert data["rules"][0]["steps"][0]["params"]["ms"] == 2468


def test_flush_save_is_noop_without_current_task(real_mainwindow, isolated_data_dir):
    """沒有選取任務時，_flush_save 應直接回 True 且不寫任何檔案。"""
    win = real_mainwindow

    assert win._flush_save() is True
    assert not (isolated_data_dir / "tasks" / ".json").exists()


# ── T-5：未提交輸入的處置 ──────────────────────────────────────────────────
#
# 舊缺陷（Phase 2-4b-1 修復前）：
#     _do_debounced_save() 直接把 self._rules 寫入磁碟，不先提交展開中的表單。
#     使用者尚未讓輸入框失去焦點（未觸發 editingFinished）時輸入的值只存在於
#     Qt widget，於是被舊值覆蓋而遺失。
# 修復後：寫入磁碟前一律先呼叫 _commit_open_step_form() 提交表單。


def test_uncommitted_wait_value_is_written_to_disk_on_flush(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """wait 欄位未 commit（未觸發 editingFinished）的值仍必須寫入磁碟。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    win._on_task_changed("t1")
    win._step_list._toggle_expand(0)

    form = win._step_list._expanded_form
    form._ms.setValue(1234)  # 只改 widget，不觸發 editingFinished
    assert win._rules[0].steps[0].params["ms"] == 500, "尚未 commit 時 params 應仍是舊值"

    win._flush_save()

    data = _read_task_json(isolated_data_dir, "t1")
    assert data["rules"][0]["steps"][0]["params"]["ms"] == 1234, "未 commit 的值也必須寫入磁碟"


def test_uncommitted_notify_value_is_written_to_disk_on_flush(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """notify 表單：未 commit 的訊息同樣必須寫入磁碟。

    舊缺陷（Phase 2-4b-1 修復前）：
        _do_debounced_save() 直接把 self._rules 寫入磁碟，不先提交展開中的表單，
        因此使用者尚未讓輸入框失去焦點（未觸發 editingFinished）時輸入的訊息
        會被舊值覆蓋而遺失。修復後寫入前會先提交表單（_commit_open_step_form）。
    """
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("notify", message="old")])])
    win._on_task_changed("t1")
    win._step_list._toggle_expand(0)

    form = win._step_list._expanded_form
    form._msg.setText("new")

    win._flush_save()

    data = _read_task_json(isolated_data_dir, "t1")
    assert data["rules"][0]["steps"][0]["params"]["message"] == "new"


def test_value_already_in_params_survives_flush(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """對照組：已經寫進 Step.params 的值（例如 ROI 立即寫入）一定會存檔。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("detect", on_fail="stop")])])
    win._on_task_changed("t1")

    # 立即寫入型欄位（ROI 選取）會直接寫進 Step.params
    win._rules[0].steps[0].params["roi"] = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}

    win._flush_save()

    data = _read_task_json(isolated_data_dir, "t1")
    assert data["rules"][0]["steps"][0]["params"]["roi"] == {
        "x": 0.1,
        "y": 0.2,
        "w": 0.3,
        "h": 0.4,
    }


def test_get_steps_before_flush_commits_value(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """對照組：先 get_steps()（會觸發 _save_expanded → save）後，值就會存檔。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    win._on_task_changed("t1")
    win._step_list._toggle_expand(0)

    form = win._step_list._expanded_form
    form._ms.setValue(4321)
    win._step_list.get_steps()

    assert win._rules[0].steps[0].params["ms"] == 4321
    win._flush_save()
    data = _read_task_json(isolated_data_dir, "t1")
    assert data["rules"][0]["steps"][0]["params"]["ms"] == 4321


def test_rule_switch_commits_open_form_value(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """切換規則前會呼叫 get_steps()，因此未 commit 的值不會遺失。"""
    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule("r0", "規則零", [make_step("wait", ms=500)]),
            make_rule("r1", "規則壹", [make_step("wait", ms=700)]),
        ],
    )
    win._on_task_changed("t1")
    win._step_list._toggle_expand(0)
    win._step_list._expanded_form._ms.setValue(31337)

    win._selected_rule_id = "r1"
    win._refresh_rule_list()

    assert win._rules[0].steps[0].params["ms"] == 31337


# ── Qt Widget 生命週期 ─────────────────────────────────────────────────────


def test_rebuild_releases_old_row_widgets(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    """重建後舊的 row widget 必須真的被 C++ 釋放（DeferredDelete）。"""
    win = real_mainwindow
    write_task(
        "t1",
        [make_rule("r0", "規則零", [make_step("wait", ms=1) for _ in range(3)])],
    )
    win._on_task_changed("t1")

    old_rows = list(win._step_list._rows)
    assert len(old_rows) == 3

    win._step_list._rebuild()
    _drain_deferred_delete(qt_app)

    assert all(sip.isdeleted(row) for row in old_rows), "舊 row widget 必須被釋放"
    assert len(win._step_list._rows) == 3, "新 row 數量應一致"


def test_rebuild_creates_new_form_and_destroys_old_one(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    """重建後展開的表單是新的 widget 物件，舊的已被銷毀。"""
    win = real_mainwindow
    write_task("t1", [make_rule("r0", "規則零", [make_step("wait", ms=500)])])
    win._on_task_changed("t1")
    win._step_list._toggle_expand(0)
    old_form = win._step_list._expanded_form
    assert old_form is not None

    win._step_list._rebuild()
    _drain_deferred_delete(qt_app)
    assert sip.isdeleted(old_form), "重建後舊表單必須被銷毀"

    win._step_list._toggle_expand(0)
    new_form = win._step_list._expanded_form
    assert new_form is not None
    assert new_form is not old_form
    assert new_form._step is win._step_list.get_steps()[0], "新表單必須綁定目前的 step"


def test_form_save_targets_current_step_only(real_mainwindow, write_task, make_step, make_rule):
    """表單的 save() 只能寫入它綁定的那一個 step。"""
    win = real_mainwindow
    write_task(
        "t1",
        [
            make_rule(
                "r0",
                "規則零",
                [make_step("wait", ms=100), make_step("wait", ms=200)],
            )
        ],
    )
    win._on_task_changed("t1")
    win._step_list._toggle_expand(1)
    form = win._step_list._expanded_form

    form.save()

    steps = win._step_list.get_steps()
    assert steps[0].params["ms"] == 100, "不得影響其他 step"
    assert steps[1].params["ms"] == 200


@pytest.mark.parametrize("n", [1, 3, 10])
def test_rebuild_widget_count_stays_constant(
    real_mainwindow, write_task, make_step, make_rule, qt_app, n
):
    """多次重建後活體 widget 數量不得累積（無孤兒 widget）。"""
    from PyQt6.QtWidgets import QWidget

    win = real_mainwindow
    write_task(
        "t1",
        [make_rule("r0", "規則零", [make_step("wait", ms=1) for _ in range(n)])],
    )
    win._on_task_changed("t1")
    _drain_deferred_delete(qt_app)
    baseline = len(win._step_list.findChildren(QWidget))

    for _ in range(5):
        win._step_list._rebuild()
        _drain_deferred_delete(qt_app)

    assert len(win._step_list.findChildren(QWidget)) == baseline, "widget 數量不得累積"
