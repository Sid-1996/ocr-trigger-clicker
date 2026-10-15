import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QListWidget, QPushButton

from _loader import load_sibling
from i18n import T

_APP = QApplication.instance() or QApplication([])
_models = load_sibling("rule_models", "core/rule_models.py")
_picker_mod = load_sibling("stop_groups_picker", "gui/stop_groups_picker.py")
StopGroupsPicker = _picker_mod.StopGroupsPicker
RuleGroup = _models.RuleGroup


def _groups():
    return [RuleGroup(id="alpha", name="Alpha"), RuleGroup(id="beta", name="Beta")]


def _button(dialog, text):
    return next(button for button in dialog.findChildren(QPushButton) if button.text() == text)


def test_search_filters_visible_groups_and_confirm_saves_selection(monkeypatch):
    picker = StopGroupsPicker(_groups, selected=["alpha"])
    observed = {}

    def exec_dialog(dialog):
        search = dialog.findChild(QLineEdit)
        items = dialog.findChild(QListWidget)
        search.setText("beta")
        observed["hidden"] = [items.item(i).isHidden() for i in range(items.count())]
        items.item(1).setCheckState(Qt.CheckState.Checked)
        _button(dialog, T("ui.confirm")).click()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", exec_dialog)
    picker._open_dialog()

    assert observed["hidden"] == [True, False]
    assert picker.selected_ids() == ["alpha", "beta"]
    picker.deleteLater()


def test_cancel_does_not_save_dialog_changes(monkeypatch):
    picker = StopGroupsPicker(_groups, selected=["alpha"])

    def exec_dialog(dialog):
        items = dialog.findChild(QListWidget)
        items.item(1).setCheckState(Qt.CheckState.Checked)
        _button(dialog, T("ui.cancel")).click()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", exec_dialog)
    picker._open_dialog()

    assert picker.selected_ids() == ["alpha"]
    picker.deleteLater()


def test_selected_ids_returns_a_copy():
    picker = StopGroupsPicker(_groups, selected=["alpha"])
    selected = picker.selected_ids()
    selected.append("beta")

    assert picker.selected_ids() == ["alpha"]
    picker.deleteLater()
