import json
import sys
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtWidgets import QInputDialog, QMessageBox

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

_gui = load_sibling("gui_main", "gui/06_gui_main.py")
MainWindow = _gui.MainWindow
RuleGroup = _gui.RuleGroup
T = _gui.T


class _Widget:
    def __init__(self):
        self.enabled = None
        self.drag = None
        self.context = None

    def setEnabled(self, value):
        self.enabled = value

    def setDragDropMode(self, value):
        self.drag = value

    def setContextMenuPolicy(self, value):
        self.context = value


class _Timer:
    def __init__(self):
        self.stops = 0

    def stop(self):
        self.stops += 1


class _Notif:
    def __init__(self):
        self.messages = []

    def push(self, message):
        self.messages.append(message)


class _Combo:
    def __init__(self, names):
        self.names = list(names)
        self.index = -1
        self.blocked = False

    def findText(self, name):
        return self.names.index(name) if name in self.names else -1

    def setCurrentIndex(self, index):
        self.index = index

    def blockSignals(self, blocked):
        self.blocked = blocked


class _Status:
    def __init__(self):
        self.messages = []

    def showMessage(self, message, timeout=0):
        self.messages.append(message)


def _edit_widgets():
    return SimpleNamespace(
        _rule_list=_Widget(),
        _add_group_btn=_Widget(),
        _add_rule_btn=_Widget(),
        _del_rule_btn=_Widget(),
        _debug_btn=_Widget(),
        _task_combo=_Widget(),
        _task_new_btn=_Widget(),
        _task_del_btn=_Widget(),
        _task_import_btn=_Widget(),
        _task_export_btn=_Widget(),
        _edit_test_btn=_Widget(),
        _edit_name=_Widget(),
        _edit_enabled=_Widget(),
        _edit_background=_Widget(),
        _edit_quiet=_Widget(),
        _step_list=_Widget(),
        _get_current_rule=lambda: None,
        _show_rule_detail=lambda rule: None,
    )


def _new_task_window(tmp_path, save_ok, monkeypatch):
    combo = _Combo(["old"])
    status = _Status()
    old_groups = [RuleGroup(id="__old__", name="old")]
    calls = {"refresh": 0, "saved": []}

    def _refresh():
        calls["refresh"] += 1
        combo.names.append("new")

    def _save(rules, groups, path):
        calls["saved"].append((rules, groups, path))
        return save_ok

    fake = SimpleNamespace(
        _groups=old_groups,
        _task_combo=combo,
        _status_bar=status,
        _refresh_task_list=_refresh,
    )
    monkeypatch.setattr(_gui, "list_tasks", lambda: ["old"])
    monkeypatch.setattr(_gui, "save_task_with_groups", _save)
    monkeypatch.setattr(_gui._rule_mod, "get_tasks_dir", lambda: tmp_path)
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *args, **kwargs: ("new", True))
    )
    return fake, old_groups, calls, combo, status


class _Value:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def currentData(self):
        return self._value

    def isChecked(self):
        return self._value


def _settings_dialog(
    save_results,
    *,
    old_lang="zh_TW",
    new_lang="zh_TW",
    task_path=None,
    old_mode="frida",
    new_mode="pynput",
    controller=None,
    config_path="config.json",
):
    accepted = []
    configured = []
    reports = []
    results = list(save_results)

    def _save_config(data):
        configured.append(dict(data))
        return results.pop(0) if results else True

    win = SimpleNamespace(
        _task_load_failed=False,
        _flush_save=lambda: True,
        _report_task_save_failed=lambda *args: reports.append(args),
        _current_task="task" if task_path else "",
        _config_path=config_path,
        _save_config=_save_config,
    )
    if controller is None:
        ctrl = SimpleNamespace(
            get_setting=lambda win, key, default=None: (
                False if key == "power_save_mode" else default
            ),
            load_config=lambda win: {"language": old_lang, "interaction_mode": old_mode},
            get_load_error=lambda: None,
        )
    else:
        ctrl = controller
        win._save_config = lambda data: controller.save_config(win, data)
    fake = SimpleNamespace(
        _win=win,
        _ctrl=ctrl,
        _save_blocked=False,
        _buttons=None,
        _max_cps=_Value(7),
        _scan_interval=_Value(250),
        _match_mode=_Value("exact"),
        _close_behavior=_Value("quit"),
        _show_close_confirm=_Value(False),
        _notify_resource_warn=_Value(False),
        _power_save=_Value(False),
        _auto_update=_Value(False),
        _ask_group=_Value(False),
        _interaction_mode=_Value(new_mode),
        _mouse_btn=_Value("right"),
        _random_offset=_Value(4),
        _default_wait_ms=_Value(600),
        _default_after_delay=_Value(300),
        _default_detect_after_delay=_Value(350),
        _record_after_delay=_Value(700),
        _record_detect_after_delay=_Value(800),
        _fuzzy_th=_Value(0.7),
        _template_th=_Value(0.9),
        _color_tol=_Value(12),
        _language=_Value(new_lang),
        accept=lambda: accepted.append(True),
    )
    fake._block_save = lambda: _gui.SettingsDialog._block_save(fake)
    return fake, accepted, configured, reports


def test_flush_save_returns_false_on_save_failure(monkeypatch):
    monkeypatch.setattr(_gui._main_loop_mod, "log_main", lambda message: None)
    timer = _Timer()
    fake = SimpleNamespace(
        _rules=[],
        _save_timer=timer,
        _current_task="task",
        _do_debounced_save=lambda: False,
    )
    assert MainWindow._flush_save(fake) is False
    assert timer.stops == 1


def test_flush_save_returns_true_without_current_task():
    fake = SimpleNamespace(
        _rules=[],
        _save_timer=_Timer(),
        _current_task="",
        _do_debounced_save=lambda: (_ for _ in ()).throw(AssertionError("must not save")),
    )
    assert MainWindow._flush_save(fake) is True


def test_flush_save_startup_before_rules_initialized_does_not_crash():
    # 啟動時 _on_task_changed 可能在 _rules 建立前由任務選擇元件觸發；
    # _current_task 尚未設定時，_flush_save 不得存取尚未存在的 _rules。
    fake = SimpleNamespace(
        _save_timer=SimpleNamespace(isActive=lambda: False, stop=lambda: None),
        _current_task="",
        _do_debounced_save=lambda: (_ for _ in ()).throw(AssertionError("must not save")),
    )
    assert MainWindow._flush_save(fake) is True


def test_on_task_changed_startup_before_rules_initialized(monkeypatch):
    monkeypatch.setattr(_gui._main_loop_mod, "log_main", lambda message: None)
    fake = SimpleNamespace(
        _loop=None,
        _save_timer=SimpleNamespace(isActive=lambda: False, stop=lambda: None),
        _task_load_failed=False,
        _task_load_error=None,
        _task_load_failed_notified=False,
        _current_task="",
        _task_combo=_Combo([""]),
        _flush_save=lambda: MainWindow._flush_save(fake),
        _report_task_save_failed=lambda *args: (_ for _ in ()).throw(
            AssertionError("must not report")
        ),
        _restore_task_selection=lambda: None,
        _refresh_rule_list=lambda: None,
        _update_edit_enabled=lambda enabled: None,
        _status_bar=_Status(),
    )
    # 故意不設定 _rules，模擬初始化尚未建立規則清單的時點。
    assert not hasattr(fake, "_rules")

    MainWindow._on_task_changed(fake, "")

    assert fake._current_task == ""
    assert fake._rules == []
    assert fake._task_load_failed is False


def test_do_debounced_save_blocks_and_notifies_once():
    notif = _Notif()
    fake = SimpleNamespace(
        _current_task="task",
        _task_load_failed=True,
        _task_load_failed_notified=False,
        _notif_stack=notif,
    )
    assert MainWindow._do_debounced_save(fake) is False
    assert MainWindow._do_debounced_save(fake) is False
    assert notif.messages == [T("dialog.task_load_failed")]


def test_on_task_changed_load_failure_enters_readonly_state(tmp_path, monkeypatch):
    task_path = tmp_path / "bad.json"
    err = _gui.RuleFileError(task_path, "bad json")
    critical = []
    update_calls = []

    def _raise(name):
        raise err

    monkeypatch.setattr(_gui, "load_task", _raise)
    monkeypatch.setattr(_gui._rule_mod, "get_tasks_dir", lambda: tmp_path)
    monkeypatch.setattr(_gui._main_loop_mod, "log_main", lambda message: None)
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))
    fake = SimpleNamespace(
        _loop=None,
        _save_timer=SimpleNamespace(isActive=lambda: False, stop=lambda: None),
        _rules=[object()],
        _groups=[object()],
        _selected_rule_id="old",
        _task_load_failed=False,
        _task_load_error=None,
        _task_load_failed_notified=False,
        _refresh_rule_list=lambda: None,
        _update_edit_enabled=lambda enabled: update_calls.append(enabled),
        _status_bar=_Status(),
        _flush_save=lambda: True,
    )

    MainWindow._on_task_changed(fake, "bad")

    assert fake._current_task == "bad"
    assert fake._task_load_failed is True
    assert fake._task_load_error is err
    assert fake._rules == []
    assert fake._groups == []
    assert fake._selected_rule_id is None
    assert update_calls == [True]
    assert critical


def test_task_switch_aborts_and_restores_combo_when_flush_fails():
    reports = []
    combo = _Combo(["old", "new"])
    combo.index = 1
    fake = SimpleNamespace(
        _loop=None,
        _save_timer=SimpleNamespace(isActive=lambda: False, stop=lambda: None),
        _task_load_failed=False,
        _current_task="old",
        _task_combo=combo,
        _flush_save=lambda: False,
        _report_task_save_failed=lambda *args: reports.append(args),
    )
    fake._restore_task_selection = lambda: MainWindow._restore_task_selection(fake)

    MainWindow._on_task_changed(fake, "new")

    assert fake._current_task == "old"
    assert combo.index == 0
    assert combo.blocked is False
    assert reports


def test_task_switch_allowed_after_current_task_load_failure(monkeypatch):
    monkeypatch.setattr(_gui, "load_task", lambda name: [])
    monkeypatch.setattr(_gui, "load_groups", lambda path: [])
    monkeypatch.setattr(_gui._main_loop_mod, "log_main", lambda message: None)
    fake = SimpleNamespace(
        _loop=None,
        _save_timer=SimpleNamespace(isActive=lambda: False, stop=lambda: None),
        _task_load_failed=True,
        _task_load_error=object(),
        _task_load_failed_notified=True,
        _current_task="bad",
        _rules=[],
        _groups=[],
        _selected_rule_id=None,
        _collapsed_groups=set(),
        _refresh_rule_list=lambda: None,
        _update_edit_enabled=lambda enabled: None,
        _status_bar=_Status(),
        _load_config=lambda: {},
        _save_config=lambda data: None,
        _flush_save=lambda: (_ for _ in ()).throw(AssertionError("must skip save")),
    )

    MainWindow._on_task_changed(fake, "good")

    assert fake._current_task == "good"
    assert fake._task_load_failed is False


def test_task_rename_aborts_when_flush_fails(monkeypatch):
    reports = []
    renames = []
    fake = SimpleNamespace(
        _current_task="old",
        _task_load_failed=False,
        _flush_save=lambda: False,
        _report_task_save_failed=lambda *args: reports.append(args),
    )
    monkeypatch.setattr(_gui, "list_tasks", lambda: ["old"])
    monkeypatch.setattr(_gui, "rename_task", lambda old, new: renames.append((old, new)) or True)
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *args, **kwargs: ("new", True))
    )

    MainWindow._on_task_rename(fake)

    assert renames == []
    assert reports


def _delete_question_sequence(monkeypatch, answers):
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: answers.pop(0)),
    )


def _make_delete_fake(flush_result=True, load_failed=False):
    flush_calls = []

    def flush():
        flush_calls.append(True)
        return flush_result

    return SimpleNamespace(
        _current_task="old",
        _task_load_failed=load_failed,
        _loop=None,
        _rules=[object()],
        _groups=[object()],
        _selected_rule_id="r1",
        _flush_save=flush,
        _flush_calls=flush_calls,
        _report_task_save_failed=lambda *args: None,
        _refresh_task_list=lambda: None,
    )


def test_task_delete_first_confirmation_no_does_not_delete(monkeypatch):
    deletes = []
    fake = _make_delete_fake()
    monkeypatch.setattr(_gui, "list_tasks", lambda: ["old", "keep"])
    monkeypatch.setattr(_gui, "delete_task", lambda name: deletes.append(name) or True)
    _delete_question_sequence(monkeypatch, [QMessageBox.StandardButton.No])

    MainWindow._on_task_delete(fake)

    assert fake._flush_calls == []
    assert deletes == []
    assert fake._current_task == "old"


def test_task_delete_flush_fails_second_confirmation_no_keeps_task(monkeypatch):
    reports = []
    deletes = []
    fake = _make_delete_fake(flush_result=False)
    fake._report_task_save_failed = lambda *args: reports.append(args)
    monkeypatch.setattr(_gui, "list_tasks", lambda: ["old", "keep"])
    monkeypatch.setattr(_gui, "delete_task", lambda name: deletes.append(name) or True)
    _delete_question_sequence(
        monkeypatch, [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No]
    )

    MainWindow._on_task_delete(fake)

    assert fake._flush_calls == [True]
    assert deletes == []
    assert reports == []
    assert fake._current_task == "old"
    assert len(fake._rules) == 1
    assert len(fake._groups) == 1
    assert fake._selected_rule_id == "r1"


def test_task_delete_flush_fails_second_confirmation_yes_deletes(monkeypatch):
    reports = []
    deletes = []
    refreshed = []
    fake = _make_delete_fake(flush_result=False)
    fake._report_task_save_failed = lambda *args: reports.append(args)
    fake._refresh_task_list = lambda: refreshed.append(True)
    monkeypatch.setattr(_gui, "list_tasks", lambda: ["old", "keep"])
    monkeypatch.setattr(_gui, "delete_task", lambda name: deletes.append(name) or True)
    _delete_question_sequence(
        monkeypatch, [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Yes]
    )

    MainWindow._on_task_delete(fake)

    assert fake._flush_calls == [True]
    assert deletes == ["old"]
    assert reports == []
    assert fake._current_task == ""
    assert fake._rules == []
    assert fake._groups == []
    assert fake._selected_rule_id is None
    assert refreshed == [True]


def test_task_delete_flush_ok_but_delete_fails_keeps_task(monkeypatch):
    deletes = []
    refreshed = []
    fake = _make_delete_fake(flush_result=True)
    fake._refresh_task_list = lambda: refreshed.append(True)
    monkeypatch.setattr(_gui, "list_tasks", lambda: ["old", "keep"])
    monkeypatch.setattr(_gui, "delete_task", lambda name: deletes.append(name) or False)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args: None))
    _delete_question_sequence(monkeypatch, [QMessageBox.StandardButton.Yes])

    MainWindow._on_task_delete(fake)

    assert fake._flush_calls == [True]
    assert deletes == ["old"]
    assert fake._current_task == "old"
    assert len(fake._rules) == 1
    assert len(fake._groups) == 1
    assert fake._selected_rule_id == "r1"
    assert refreshed == []


def test_task_delete_flush_fails_second_yes_but_delete_fails_keeps_task(monkeypatch):
    reports = []
    deletes = []
    refreshed = []
    fake = _make_delete_fake(flush_result=False)
    fake._report_task_save_failed = lambda *args: reports.append(args)
    fake._refresh_task_list = lambda: refreshed.append(True)
    monkeypatch.setattr(_gui, "list_tasks", lambda: ["old", "keep"])
    monkeypatch.setattr(_gui, "delete_task", lambda name: deletes.append(name) or False)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args: None))
    _delete_question_sequence(
        monkeypatch, [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Yes]
    )

    MainWindow._on_task_delete(fake)

    assert fake._flush_calls == [True]
    assert deletes == ["old"]
    assert reports == []
    assert fake._current_task == "old"
    assert len(fake._rules) == 1
    assert len(fake._groups) == 1
    assert fake._selected_rule_id == "r1"
    assert refreshed == []


def test_task_delete_failure_shows_warning_and_keeps_ui_state(monkeypatch):
    warnings = []
    deletes = []
    refreshed = []
    fake = _make_delete_fake(flush_result=True)
    fake._task_load_error = SimpleNamespace(path="old.json", reason="locked")
    fake._task_load_failed_notified = True
    fake._refresh_task_list = lambda: refreshed.append(True)
    monkeypatch.setattr(_gui, "list_tasks", lambda: ["old", "keep"])
    monkeypatch.setattr(_gui, "delete_task", lambda name: deletes.append(name) or False)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *args: warnings.append(args)),
    )
    _delete_question_sequence(monkeypatch, [QMessageBox.StandardButton.Yes])

    MainWindow._on_task_delete(fake)

    assert fake._flush_calls == [True]
    assert deletes == ["old"]
    assert warnings
    assert warnings[0][1] == T("dialog.cannot_delete")
    assert warnings[0][2] == T("dialog.cannot_delete")
    assert fake._current_task == "old"
    assert len(fake._rules) == 1
    assert len(fake._groups) == 1
    assert fake._selected_rule_id == "r1"
    assert fake._task_load_error is not None
    assert fake._task_load_failed_notified is True
    assert refreshed == []


def test_task_delete_task_load_failed_skips_flush(monkeypatch):
    flush_called = []
    deletes = []
    refreshed = []

    def flush():
        flush_called.append(True)
        return True

    fake = SimpleNamespace(
        _current_task="old",
        _task_load_failed=True,
        _loop=None,
        _rules=[object()],
        _groups=[object()],
        _selected_rule_id="r1",
        _flush_save=flush,
        _report_task_save_failed=lambda *args: None,
        _refresh_task_list=lambda: refreshed.append(True),
    )
    monkeypatch.setattr(_gui, "list_tasks", lambda: ["old", "keep"])
    monkeypatch.setattr(_gui, "delete_task", lambda name: deletes.append(name) or True)
    _delete_question_sequence(monkeypatch, [QMessageBox.StandardButton.Yes])

    MainWindow._on_task_delete(fake)

    assert flush_called == []
    assert deletes == ["old"]
    assert fake._current_task == ""
    assert fake._rules == []
    assert fake._groups == []
    assert fake._selected_rule_id is None
    assert refreshed == [True]


def test_task_delete_success_clears_current_before_refresh(monkeypatch):
    deleted = []
    refreshed = []
    fake = SimpleNamespace(
        _current_task="old",
        _task_load_failed=False,
        _loop=None,
        _rules=[object()],
        _groups=[object()],
        _selected_rule_id="r1",
        _flush_save=lambda: True,
        _refresh_task_list=lambda: refreshed.append(True),
    )
    monkeypatch.setattr(_gui, "list_tasks", lambda: ["old", "keep"])
    monkeypatch.setattr(_gui, "delete_task", lambda name: deleted.append(name) or True)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
    )

    MainWindow._on_task_delete(fake)

    assert deleted == ["old"]
    assert fake._current_task == ""
    assert fake._rules == []
    assert fake._groups == []
    assert fake._selected_rule_id is None
    assert refreshed == [True]


def test_task_export_aborts_when_flush_fails(monkeypatch):
    reports = []
    fake = SimpleNamespace(
        _current_task="old",
        _loop=None,
        _save_current_rule=lambda: None,
        _flush_save=lambda: False,
        _report_task_save_failed=lambda *args: reports.append(args),
    )
    monkeypatch.setattr(
        _gui.QFileDialog,
        "getSaveFileName",
        staticmethod(
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not open"))
        ),
    )

    MainWindow._on_task_export(fake)

    assert reports


def test_quit_aborts_when_flush_fails():
    reports = []
    fake = SimpleNamespace(
        _task_load_failed=False,
        _flush_save=lambda: False,
        _report_task_save_failed=lambda *args: reports.append(args),
    )

    assert MainWindow._quit_app(fake) is False
    assert reports


def test_quit_allows_load_failed_without_save(monkeypatch):
    quits = []
    fake = SimpleNamespace(
        _task_load_failed=True,
        _flush_save=lambda: (_ for _ in ()).throw(AssertionError("must skip save")),
        winId=lambda: 1,
        _recorder=None,
        _status_timer=SimpleNamespace(stop=lambda: None),
        _loop=None,
        _perf_timer=SimpleNamespace(stop=lambda: None),
    )
    monkeypatch.setattr(_gui, "_hk_unregister", lambda hwnd: None)
    monkeypatch.setattr(_gui, "QApplication", SimpleNamespace(quit=lambda: quits.append(True)))

    assert MainWindow._quit_app(fake) is True
    assert quits == [True]


def test_download_finished_aborts_when_flush_fails(monkeypatch):
    reports = []
    fake = SimpleNamespace(
        _task_load_failed=False,
        _downloading=True,
        _flush_save=lambda: False,
        _report_task_save_failed=lambda *args: reports.append(args),
    )
    monkeypatch.setattr(
        _gui,
        "QApplication",
        SimpleNamespace(quit=lambda: (_ for _ in ()).throw(AssertionError("must not quit"))),
    )

    MainWindow._on_download_finished(fake)

    assert fake._downloading is False
    assert reports


def test_settings_accept_aborts_when_flush_fails():
    reports = []
    fake = SimpleNamespace(
        _win=SimpleNamespace(
            _task_load_failed=False,
            _flush_save=lambda: False,
            _report_task_save_failed=lambda *args: reports.append(args),
        )
    )

    _gui.SettingsDialog._on_accept(fake)

    assert reports


def test_do_debounced_save_failure_preserves_corrupt_file(tmp_path, monkeypatch):
    task_path = tmp_path / "task.json"
    original = b'{"rules": '
    task_path.write_bytes(original)
    notif = _Notif()
    fake = SimpleNamespace(
        _current_task="task",
        _task_load_failed=False,
        _task_load_failed_notified=False,
        _notif_stack=notif,
        _rules=[],
        _groups=[],
        _loop=None,
    )
    monkeypatch.setattr(_gui._rule_mod, "get_tasks_dir", lambda: tmp_path)
    monkeypatch.setattr(_gui._main_loop_mod, "log_main", lambda message: None)
    assert MainWindow._do_debounced_save(fake) is False
    assert task_path.read_bytes() == original
    assert notif.messages == [T("notif.task_save_failed_short")]


def test_update_edit_enabled_disables_editing_but_keeps_task_controls():
    fake = _edit_widgets()
    fake._task_load_failed = True

    MainWindow._update_edit_enabled(fake, True)

    assert fake._rule_list.enabled is False
    assert fake._add_rule_btn.enabled is False
    assert fake._add_group_btn.enabled is False
    assert fake._edit_name.enabled is False
    assert fake._step_list.enabled is False
    assert fake._task_combo.enabled is True
    assert fake._task_new_btn.enabled is True
    assert fake._task_del_btn.enabled is True

    fake._task_load_failed = False
    MainWindow._update_edit_enabled(fake, False)
    assert fake._task_combo.enabled is False
    assert fake._add_rule_btn.enabled is False


def test_on_task_new_failure_does_not_replace_current_groups(tmp_path, monkeypatch):
    fake, old_groups, calls, combo, status = _new_task_window(
        tmp_path, save_ok=False, monkeypatch=monkeypatch
    )
    critical = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))

    MainWindow._on_task_new(fake)

    assert fake._groups is old_groups
    assert calls["saved"][0][0] == []
    assert calls["saved"][0][1][0].id == "__default__"
    assert calls["refresh"] == 0
    assert combo.index == -1
    assert status.messages == []
    assert critical


def test_on_task_new_success_does_not_replace_current_groups_before_load(tmp_path, monkeypatch):
    fake, old_groups, calls, combo, status = _new_task_window(
        tmp_path, save_ok=True, monkeypatch=monkeypatch
    )
    warning = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args: warning.append(args)))

    MainWindow._on_task_new(fake)

    assert fake._groups is old_groups
    assert calls["refresh"] == 1
    assert combo.index == 1
    assert status.messages == [T("notif.task_created", name="new")]
    assert warning == []


def test_start_loop_aborts_when_flush_fails(tmp_path, monkeypatch):
    critical = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))
    monkeypatch.setattr(_gui._rule_mod, "get_tasks_dir", lambda: tmp_path)
    rule = SimpleNamespace(id="r1", name="rule", enabled=True, steps=[1])
    fake = SimpleNamespace(
        _task_load_failed=False,
        _window_lost=False,
        _bg_fail_dialog_shown=False,
        _black_fail_dialog_shown=False,
        _window_combo=SimpleNamespace(currentText=lambda: "Game"),
        _recorder=None,
        _rules=[rule],
        _groups=[
            SimpleNamespace(id="g1", enabled=True, rule_ids=["r1"]),
            SimpleNamespace(id="g2", enabled=True, rule_ids=[]),
        ],
        _rule_hard_problems=lambda r: [],
        _is_bg_mode=lambda: False,
        _current_task="task",
        _save_current_rule=lambda: None,
        _flush_save=lambda: False,
        _status_bar=_Status(),
    )

    MainWindow._start_loop(fake, group_ids=["g1"])

    assert critical
    assert not hasattr(fake, "_is_starting")
    assert not hasattr(fake, "_init_worker")


def test_add_rule_and_start_loop_are_blocked_after_load_failure(monkeypatch):
    warning = []
    critical = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args: warning.append(args)))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))
    fake = SimpleNamespace(
        _task_load_failed=True,
        _task_load_failed_message=lambda: "load failed",
    )

    MainWindow._add_rule(fake)
    MainWindow._start_loop(fake)

    assert warning
    assert critical


def test_main_window_save_config_returns_controller_result():
    results = iter([True, False])
    fake = SimpleNamespace(
        _rule_config_ctrl=SimpleNamespace(save_config=lambda win, data: next(results)),
    )

    assert MainWindow._save_config(fake, {}) is True
    assert MainWindow._save_config(fake, {}) is False


def test_settings_save_failure_keeps_dialog_open_and_skips_restart(monkeypatch):
    fake, accepted, configured, _ = _settings_dialog([False], new_lang="en")
    critical = []
    monkeypatch.setattr(_gui, "get_language", lambda: "zh_TW")
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args: (_ for _ in ()).throw(AssertionError("must not ask restart"))),
    )
    monkeypatch.setattr(
        _gui,
        "_relaunch_detached",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not restart")),
    )

    _gui.SettingsDialog._on_accept(fake)

    assert critical
    assert accepted == []
    assert len(configured) == 1
    assert configured[0]["language"] == "en"
    assert configured[0]["max_cps"] == 7
    assert configured[0]["record_detect_after_delay_ms"] == 800
    assert configured[0]["default_color_tolerance"] == 12
    assert configured[0]["interaction_mode"] == "pynput"


def test_settings_task_mode_failure_rolls_back_and_keeps_dialog(tmp_path, monkeypatch):
    task_path = tmp_path / "task.json"
    fake, accepted, configured, _ = _settings_dialog(
        [True, True],
        new_lang="en",
        task_path=task_path,
        old_mode="frida",
        new_mode="pynput",
    )
    writes = []
    critical = []
    monkeypatch.setattr(_gui, "get_language", lambda: "zh_TW")
    monkeypatch.setattr(_gui._rule_mod, "get_tasks_dir", lambda: tmp_path)
    monkeypatch.setattr(_gui, "get_task_interaction_mode", lambda path: "frida")
    monkeypatch.setattr(
        _gui,
        "set_task_interaction_mode",
        lambda path, mode: writes.append((path, mode)) or False,
    )
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args: (_ for _ in ()).throw(AssertionError("must not ask restart"))),
    )
    monkeypatch.setattr(
        _gui,
        "_relaunch_detached",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not restart")),
    )

    _gui.SettingsDialog._on_accept(fake)

    assert critical
    assert accepted == []
    assert len(writes) == 1
    assert writes[0][1] == "pynput"
    assert configured[0]["interaction_mode"] == "pynput"
    assert configured[1] == {"language": "zh_TW", "interaction_mode": "frida"}


def test_settings_success_saves_all_and_accepts(monkeypatch):
    fake, accepted, configured, _ = _settings_dialog([True])
    critical = []
    monkeypatch.setattr(_gui, "get_language", lambda: "zh_TW")
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))

    _gui.SettingsDialog._on_accept(fake)

    assert not critical
    assert accepted == [True]
    assert len(configured) == 1
    assert configured[0]["language"] == "zh_TW"
    assert configured[0]["max_cps"] == 7
    assert configured[0]["scan_interval_ms"] == 250
    assert configured[0]["default_mouse_button"] == "right"


def test_settings_rollback_failure_keeps_new_config_and_blocks_retry(tmp_path, monkeypatch, caplog):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {"language": "zh_TW", "interaction_mode": "frida", "max_cps": 5},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps({"interaction_mode": "frida"}), encoding="utf-8")
    ctrl = _gui.RuleConfigController()
    fake, accepted, _, _ = _settings_dialog(
        [],
        new_lang="en",
        task_path=task_path,
        old_mode="frida",
        new_mode="pynput",
        controller=ctrl,
        config_path=str(config_path),
    )
    real_replace = _gui._rule_config_mod._replace_file
    calls = 0
    rollback_data = []

    def _flaky_replace(src, dst):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_replace(src, dst)
        rollback_data.append(json.loads(Path(src).read_text(encoding="utf-8")))
        raise OSError("disk full during rollback")

    critical = []
    monkeypatch.setattr(_gui._rule_config_mod, "_replace_file", _flaky_replace)
    monkeypatch.setattr(_gui, "get_language", lambda: "zh_TW")
    monkeypatch.setattr(_gui._rule_mod, "get_tasks_dir", lambda: tmp_path)
    monkeypatch.setattr(_gui, "get_task_interaction_mode", lambda path: "frida")
    monkeypatch.setattr(_gui, "set_task_interaction_mode", lambda path, mode: False)
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args: (_ for _ in ()).throw(AssertionError("must not ask restart"))),
    )
    monkeypatch.setattr(
        _gui,
        "_relaunch_detached",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not restart")),
    )

    _gui.SettingsDialog._on_accept(fake)

    assert accepted == []
    assert fake._save_blocked is True
    assert calls == 2
    assert rollback_data == [{"language": "zh_TW", "interaction_mode": "frida", "max_cps": 5}]
    assert json.loads(config_path.read_text(encoding="utf-8"))["language"] == "en"
    assert ctrl.get_setting(fake._win, "max_cps") == 7
    assert ctrl.get_load_error() is None
    assert critical[0][2] == T(
        "notif.settings_rollback_failed",
        config_path=str(config_path),
        task_path=str(task_path),
    )
    assert any("settings rollback failed" in r.message for r in caplog.records)

    _gui.SettingsDialog._on_accept(fake)

    assert accepted == []
    assert calls == 2
    assert critical[-1][2] == T("notif.settings_reopen_required")


def test_settings_general_save_failure_retries_with_current_fields(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"language": "zh_TW", "interaction_mode": "frida", "max_cps": 5}),
        encoding="utf-8",
    )
    ctrl = _gui.RuleConfigController()
    fake, accepted, _, _ = _settings_dialog(
        [],
        new_lang="zh_TW",
        controller=ctrl,
        config_path=str(config_path),
    )
    real_replace = _gui._rule_config_mod._replace_file
    calls = 0

    def _flaky_replace(src, dst):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("disk full")
        return real_replace(src, dst)

    critical = []
    monkeypatch.setattr(_gui._rule_config_mod, "_replace_file", _flaky_replace)
    monkeypatch.setattr(_gui, "get_language", lambda: "zh_TW")
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))

    _gui.SettingsDialog._on_accept(fake)

    assert critical
    assert accepted == []
    assert fake._save_blocked is False
    assert json.loads(config_path.read_text(encoding="utf-8"))["max_cps"] == 5
    assert ctrl.get_setting(fake._win, "max_cps") == 5

    _gui.SettingsDialog._on_accept(fake)

    assert accepted == [True]
    assert fake._save_blocked is False
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["language"] == "zh_TW"
    assert data["interaction_mode"] == "pynput"
    assert data["max_cps"] == 7
    assert data["scan_interval_ms"] == 250
    assert ctrl.get_setting(fake._win, "max_cps") == 7


def test_settings_load_error_requires_reopen_and_does_not_overwrite(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    original = b'{"language": '
    config_path.write_bytes(original)
    ctrl = _gui.RuleConfigController()
    fake, accepted, _, _ = _settings_dialog(
        [],
        controller=ctrl,
        config_path=str(config_path),
    )
    critical = []
    monkeypatch.setattr(_gui, "get_language", lambda: "zh_TW")
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args: (_ for _ in ()).throw(AssertionError("must not ask restart"))),
    )
    monkeypatch.setattr(
        _gui,
        "_relaunch_detached",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not restart")),
    )

    _gui.SettingsDialog._on_accept(fake)

    err = ctrl.get_load_error()
    assert err is not None
    assert accepted == []
    assert fake._save_blocked is True
    assert config_path.read_bytes() == original
    assert critical[0][0] == fake
    assert critical[0][1] == T("dialog.config_load_failed")
    expected = T("dialog.config_load_failed_msg", path=str(config_path), error=err.reason)
    assert critical[0][2] == expected + "\n\n" + T("notif.settings_reopen_required")

    _gui.SettingsDialog._on_accept(fake)

    assert accepted == []
    assert config_path.read_bytes() == original
    assert critical[-1][2] == T("notif.settings_reopen_required")


def test_settings_external_change_blocks_save_and_preserves_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    baseline = {"language": "zh_TW", "interaction_mode": "frida"}
    config_path.write_text(json.dumps(baseline), encoding="utf-8")
    main_ctrl = _gui.RuleConfigController()
    dialog_ctrl = _gui.RuleConfigController()
    fake, accepted, _, _ = _settings_dialog(
        [],
        new_lang="en",
        controller=main_ctrl,
        config_path=str(config_path),
    )
    fake._ctrl = dialog_ctrl
    fake._win._rule_config_ctrl = main_ctrl
    assert main_ctrl.load_config(fake._win) == baseline
    assert dialog_ctrl.load_config(fake._win) == baseline

    external = {"language": "ja", "interaction_mode": "frida", "external_only": True}
    config_path.write_text(json.dumps(external), encoding="utf-8")
    critical = []
    monkeypatch.setattr(_gui, "get_language", lambda: "zh_TW")
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: critical.append(args)))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args: (_ for _ in ()).throw(AssertionError("must not ask restart"))),
    )
    monkeypatch.setattr(
        _gui,
        "_relaunch_detached",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not restart")),
    )

    _gui.SettingsDialog._on_accept(fake)

    conflict = main_ctrl.get_save_conflict()
    assert conflict is not None
    assert dialog_ctrl.get_save_conflict() is None
    assert accepted == []
    assert fake._save_blocked is True
    assert json.loads(config_path.read_text(encoding="utf-8")) == external
    assert critical[0][1] == T("dialog.config_external_change")
    expected = T(
        "dialog.config_external_change_msg",
        path=str(config_path),
        error=conflict.reason,
    )
    assert critical[0][2] == expected + "\n\n" + T("notif.settings_reopen_required")

    _gui.SettingsDialog._on_accept(fake)
    assert accepted == []
    assert critical[-1][2] == T("notif.settings_reopen_required")
