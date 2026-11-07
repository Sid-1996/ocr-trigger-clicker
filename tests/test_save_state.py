"""UX 2B-03：自動儲存狀態時序測試。

驗證 MainWindow 的 _saved_label 只在實際 persistence 成功後顯示「已儲存」，
且寫入期間的再次修改、規則切換、寫入失敗/例外不會被誤報為已儲存。
"""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from _loader import load_sibling  # noqa: E402
from i18n import T  # noqa: E402

_gui = load_sibling("gui_main", "gui/06_gui_main.py")


def _load_task(win, name: str) -> None:
    win._on_task_changed(name)


def _select_rule(win, rule_id: str) -> None:
    win._selected_rule_id = rule_id
    win._refresh_rule_list()


def _setup(win, write_task, make_rule, make_step):
    write_task(
        "t1",
        [
            make_rule("r0", "規則零", [make_step("wait", ms=1)]),
            make_rule("r1", "規則一", [make_step("wait", ms=2)]),
        ],
    )
    _load_task(win, "t1")
    _select_rule(win, "r0")


def _disk_task(isolated_data_dir):
    return json.loads((isolated_data_dir / "tasks" / "t1.json").read_text(encoding="utf-8"))


def _modify_name(win, name: str):
    win._edit_name.setText(name)
    win._on_name_changed()
    win._save_timer.stop()  # 避免 debounce 在斷言間觸發，時序由測試顯式驅動


def test_loaded_task_is_saved(real_mainwindow, write_task, make_rule, make_step, monkeypatch):
    win = real_mainwindow
    _setup(win, write_task, make_rule, make_step)
    assert win._save_state == "saved"
    assert win._saved_label.text() == T("status.saved")


def test_modify_marks_dirty_and_disk_unchanged(
    real_mainwindow, write_task, make_rule, make_step, isolated_data_dir
):
    win = real_mainwindow
    _setup(win, write_task, make_rule, make_step)
    before = _disk_task(isolated_data_dir)

    _modify_name(win, "改名後")
    # debounce 尚未觸發：狀態為未儲存，且磁碟內容不變
    assert win._save_state == "dirty"
    assert win._saved_label.text() == T("status.unsaved")
    assert _disk_task(isolated_data_dir) == before


def test_write_success_marks_saved(
    real_mainwindow, write_task, make_rule, make_step, isolated_data_dir
):
    win = real_mainwindow
    _setup(win, write_task, make_rule, make_step)
    _modify_name(win, "改名後")

    assert win._do_debounced_save() is True
    assert win._save_state == "saved"
    assert win._saved_label.text() == T("status.saved")
    disk = _disk_task(isolated_data_dir)
    assert {r["name"] for r in disk["rules"]} >= {"改名後"}


def test_write_failure_marks_failed(real_mainwindow, write_task, make_rule, make_step, monkeypatch):
    win = real_mainwindow
    _setup(win, write_task, make_rule, make_step)
    _modify_name(win, "改名後")
    monkeypatch.setattr(_gui, "save_task_with_groups", lambda *a, **k: False)

    assert win._do_debounced_save() is False
    assert win._save_state == "failed"
    assert win._saved_label.text() == T("status.save_failed")


def test_write_exception_marks_failed_and_propagates(
    real_mainwindow, write_task, make_rule, make_step, monkeypatch
):
    win = real_mainwindow
    _setup(win, write_task, make_rule, make_step)
    _modify_name(win, "改名後")

    def _boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(_gui, "save_task_with_groups", _boom)
    with pytest.raises(RuntimeError):
        win._do_debounced_save()
    assert win._save_state == "failed"
    assert win._saved_label.text() == T("status.save_failed")


def test_continuous_modifications_saved_only_after_latest_write(
    real_mainwindow, write_task, make_rule, make_step, isolated_data_dir
):
    win = real_mainwindow
    _setup(win, write_task, make_rule, make_step)
    _modify_name(win, "第一次")
    _modify_name(win, "第二次")
    assert win._save_state == "dirty"

    assert win._do_debounced_save() is True
    assert win._save_state == "saved"
    names = {r["name"] for r in _disk_task(isolated_data_dir)["rules"]}
    assert "第二次" in names
    assert "第一次" not in names


def test_switching_rule_keeps_dirty_state(real_mainwindow, write_task, make_rule, make_step):
    """A 修改後切換 B：狀態仍為未儲存，不得被 B 的顯示覆成已儲存。"""
    win = real_mainwindow
    _setup(win, write_task, make_rule, make_step)
    _modify_name(win, "改名 A")

    _select_rule(win, "r1")
    assert win._save_state == "dirty"
    assert win._saved_label.text() == T("status.unsaved")

    assert win._do_debounced_save() is True
    assert win._save_state == "saved"


def test_modification_during_write_not_cleared_by_old_write(
    real_mainwindow, write_task, make_rule, make_step, isolated_data_dir, monkeypatch
):
    """寫入期間真正改資料：舊一輪成功不得清除新一輪 dirty，且第二輪磁碟正確。"""
    win = real_mainwindow
    _setup(win, write_task, make_rule, make_step)
    _modify_name(win, "第一輪")

    real_save = _gui.save_task_with_groups

    def _save_then_modify(rules, groups, path):
        # 第一輪執行真正的 persistence 寫入
        ok = real_save(rules, groups, path)
        # 寫入完成、回傳之前：真正修改目前規則資料並重新排程
        win._rules[0].name = "第二輪"
        win._schedule_save()
        win._save_timer.stop()  # 第二輪由測試顯式驅動，避免 timer 搶跑
        return ok

    monkeypatch.setattr(_gui, "save_task_with_groups", _save_then_modify)
    assert win._do_debounced_save() is True
    # 第一輪返回後仍是 dirty，且磁碟只有第一輪的值
    assert win._save_state == "dirty"
    assert win._saved_label.text() == T("status.unsaved")
    names1 = {r["name"] for r in _disk_task(isolated_data_dir)["rules"]}
    assert "第一輪" in names1
    assert "第二輪" not in names1

    # 第二輪真正儲存：磁碟包含第二輪修改，之後才顯示已儲存
    monkeypatch.setattr(_gui, "save_task_with_groups", real_save)
    assert win._do_debounced_save() is True
    assert win._save_state == "saved"
    names2 = {r["name"] for r in _disk_task(isolated_data_dir)["rules"]}
    assert "第二輪" in names2
    assert "第一輪" not in names2


def test_debounce_timer_fires_automatically(
    real_mainwindow, write_task, make_rule, make_step, isolated_data_dir, qt_app
):
    """正常 _schedule_save 後 timer 真正觸發儲存（不手動 stop、不手動呼叫）。"""
    from PyQt6.QtTest import QTest

    win = real_mainwindow
    _setup(win, write_task, make_rule, make_step)
    win._edit_name.setText("自動名稱")
    win._on_name_changed()
    assert win._save_state == "dirty"
    assert win._save_timer.isActive() is True

    # 等待 Qt timer（500ms）自動觸發：QTest.qWait 驅動事件迴圈，不用 sleep
    QTest.qWait(700)
    assert win._save_state == "saved"
    assert "自動名稱" in {r["name"] for r in _disk_task(isolated_data_dir)["rules"]}
