"""狀態列互動方法按鈕（UX Phase 2C）。

以真實 MainWindow（offscreen）+ 真實 ConfigStore／任務檔驗證：
按鈕顯示、Menu 勾選、雙寫、任務寫入失敗回滾、回滾失敗不假成功、
非法 mode 拒絕、GUI＋MainLoop 雙快取 reset、任務切換同步、設定視窗同步、
showMessage 不覆蓋按鈕。不 mock 資料寫入本身（只在失敗路徑替換寫入點）。
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QMessageBox, QToolButton

from _loader import load_sibling
from i18n import T

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

_gui = load_sibling("gui_main", "gui/06_gui_main.py")
_config_store = load_sibling("config_store", "core/config_store.py")
ConfigStore = _config_store.ConfigStore


@pytest.fixture
def win(real_mainwindow, monkeypatch):
    """真實主視窗 + 攔截 critical 彈窗（失敗路徑不斷言阻塞）。"""
    criticals = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda *a, **k: criticals.append((a, k))),
    )
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    real_mainwindow._criticals = criticals
    yield real_mainwindow


def _set_global_mode(win, mode):
    assert win._rule_config_ctrl.set_setting(win, "interaction_mode", mode)


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _task_path(win, name="A"):
    return str(_gui._rule_mod.get_tasks_dir() / f"{name}.json")


def _make_task(win, write_task, name="A", mode="pynput"):
    write_task(name, [], [])
    assert _gui.set_task_interaction_mode(_task_path(win, name), mode)
    win._current_task = name
    return _task_path(win, name)


def test_button_shows_current_mode_and_menu_checks(win):
    _set_global_mode(win, "frida")
    win._update_interaction_mode_label()
    btn = win._interaction_mode_label
    assert isinstance(btn, QToolButton)
    assert btn.text() == f"🟣 {T('combo.interaction_bg_frida')}"
    assert set(win._interaction_mode_actions) == {"pynput", "frida", "hybrid"}
    assert win._interaction_mode_actions["frida"].isChecked()
    assert not win._interaction_mode_actions["pynput"].isChecked()
    assert not win._interaction_mode_actions["hybrid"].isChecked()
    assert btn.menu() is not None
    assert T("status.mode_switch.records_task") in btn.toolTip()
    assert T("settings.interaction_mode.tooltip") in btn.toolTip()


def test_select_mode_updates_global_and_task(win, write_task):
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")
    win._update_interaction_mode_label()

    win._on_status_mode_selected("frida")

    assert _read_json(win._config_path)["interaction_mode"] == "frida"
    assert _read_json(_task_path(win))["interaction_mode"] == "frida"
    assert win._interaction_mode_label.text() == f"🟣 {T('combo.interaction_bg_frida')}"
    assert win._interaction_mode_actions["frida"].isChecked()
    assert not win._criticals


def test_menu_action_trigger_switches_mode(win, write_task):
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")
    win._update_interaction_mode_label()

    win._interaction_mode_actions["hybrid"].trigger()

    assert _read_json(win._config_path)["interaction_mode"] == "hybrid"
    assert win._interaction_mode_label.text() == f"🟠 {T('combo.interaction_hybrid')}"


def test_task_write_failure_rolls_back_global(win, write_task, monkeypatch):
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")
    win._update_interaction_mode_label()
    monkeypatch.setattr(_gui, "set_task_interaction_mode", lambda *a, **k: False)

    win._on_status_mode_selected("hybrid")

    assert _read_json(win._config_path)["interaction_mode"] == "pynput"
    assert _read_json(_task_path(win))["interaction_mode"] == "pynput"
    assert win._interaction_mode_label.text() == f"🟢 {T('combo.interaction_fg')}"
    assert win._criticals, "任務寫入失敗必須提示，不得假裝成功"


def test_rollback_failure_does_not_show_success(win, write_task, monkeypatch):
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")
    win._update_interaction_mode_label()
    monkeypatch.setattr(_gui, "set_task_interaction_mode", lambda *a, **k: False)
    saves = {"n": 0}

    def _flaky_save(data):
        saves["n"] += 1
        return saves["n"] == 1  # 全域寫入成功、回滾寫入失敗

    monkeypatch.setattr(win, "_save_config", _flaky_save)

    win._on_status_mode_selected("frida")

    assert saves["n"] == 2
    assert win._interaction_mode_label.text() == f"🟢 {T('combo.interaction_fg')}"
    assert not win._interaction_mode_actions["frida"].isChecked()
    assert win._criticals, "回滾失敗必須提示，不得假裝成功"


def test_config_write_failure_no_change(win, write_task, monkeypatch):
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")
    win._update_interaction_mode_label()
    monkeypatch.setattr(win, "_save_config", lambda data: False)

    win._on_status_mode_selected("frida")

    assert _read_json(win._config_path)["interaction_mode"] == "pynput"
    assert _read_json(_task_path(win))["interaction_mode"] == "pynput"
    assert win._interaction_mode_label.text() == f"🟢 {T('combo.interaction_fg')}"
    assert win._criticals


def test_invalid_and_same_mode_rejected(win, write_task, monkeypatch):
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")
    win._update_interaction_mode_label()

    def _boom(data):
        raise AssertionError("非法/相同 mode 不得寫入")

    monkeypatch.setattr(win, "_save_config", _boom)
    win._on_status_mode_selected("bogus")
    win._on_status_mode_selected("")
    win._on_status_mode_selected("pynput")  # 與目前相同

    assert _read_json(win._config_path)["interaction_mode"] == "pynput"
    assert not win._criticals


def test_both_caches_reset_loop_not_rebuilt(win, write_task):
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")
    loop_ctrl = ConfigStore(str(win._config_path))
    assert loop_ctrl.get("interaction_mode") == "pynput"  # 先建立 loop 快取
    loop = SimpleNamespace(_config_store=loop_ctrl, stop=lambda: None)
    win._loop = loop

    win._on_status_mode_selected("hybrid")

    assert win._loop is loop, "切換不得重建 MainLoop"
    # 未 reset 會回快取舊值 pynput；reset 後才讀到檔案新值 hybrid
    assert loop_ctrl.get("interaction_mode") == "hybrid"
    assert win._rule_config_ctrl.get_setting(win, "interaction_mode") == "hybrid"


def test_task_switch_syncs_button(win, write_task, monkeypatch):
    _make_task(win, write_task, name="A", mode="pynput")
    _make_task(win, write_task, name="B", mode="frida")
    _set_global_mode(win, "pynput")
    win._current_task = "A"
    monkeypatch.setattr(win, "_flush_save", lambda: True)

    win._on_task_changed("B")

    assert win._interaction_mode_label.text() == f"🟣 {T('combo.interaction_bg_frida')}"
    assert win._interaction_mode_actions["frida"].isChecked()
    assert win._rule_config_ctrl.get_setting(win, "interaction_mode") == "frida"


def test_settings_dialog_shows_switched_value(win, write_task):
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")

    win._on_status_mode_selected("hybrid")

    dlg = _gui.SettingsDialog(win)
    try:
        assert dlg._interaction_mode.currentData() == "hybrid"
    finally:
        dlg.close()


def test_settings_dialog_accept_syncs_button(win, write_task, monkeypatch):
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")
    win._update_interaction_mode_label()
    monkeypatch.setattr(win, "_flush_save", lambda: True)

    dlg = _gui.SettingsDialog(win)
    dlg._interaction_mode.setCurrentIndex(1)  # frida
    dlg._on_accept()
    assert dlg.result() == dlg.DialogCode.Accepted
    dlg.close()
    # _open_settings() 關窗後的同步（06:9144-9150）
    win._rule_config_ctrl.reset_cache()
    win._update_interaction_mode_label()

    assert win._interaction_mode_label.text() == f"🟣 {T('combo.interaction_bg_frida')}"
    assert win._interaction_mode_actions["frida"].isChecked()
    assert _read_json(_task_path(win))["interaction_mode"] == "frida"


def test_show_message_keeps_button(win, write_task):
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")
    win._update_interaction_mode_label()
    before = win._interaction_mode_label.text()

    win._status_bar.showMessage("暫時訊息", 3000)

    assert win._interaction_mode_label.parentWidget() is win._status_bar
    assert win._interaction_mode_label.text() == before


def test_settings_accept_task_failure_still_rolls_back(win, write_task, monkeypatch):
    """共用 helper 不得改變設定視窗既有回滾行為（test_gui_save_safety 互補）。"""
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")
    monkeypatch.setattr(win, "_flush_save", lambda: True)
    monkeypatch.setattr(_gui, "set_task_interaction_mode", lambda *a, **k: False)

    dlg = _gui.SettingsDialog(win)
    dlg._interaction_mode.setCurrentIndex(1)  # frida
    dlg._on_accept()

    assert dlg.result() != dlg.DialogCode.Accepted, "失敗時對話框不得關閉"
    assert _read_json(win._config_path)["interaction_mode"] == "pynput"
    dlg.close()


def test_no_real_input_on_switch(win, write_task, monkeypatch):
    """切換只走設定寫入（task spec：不 mock 輸入、但確認 handler 不碰輸入模組）。"""
    _make_task(win, write_task, mode="pynput")
    _set_global_mode(win, "pynput")

    def _boom(*a, **k):
        raise AssertionError("狀態列切換不得送出真實輸入")

    monkeypatch.setattr(_gui, "_input_mod", SimpleNamespace(send_click=_boom))
    win._on_status_mode_selected("frida")
    assert _read_json(win._config_path)["interaction_mode"] == "frida"
