import json

from PyQt6.QtCore import Qt

from _loader import load_sibling

_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
list_tasks = _rule_mod.list_tasks


class RuleConfigController:
    def __init__(self):
        self._config_cache: dict | None = None

    def load_config(self, win) -> dict:
        if self._config_cache is None:
            try:
                with open(win._config_path, encoding="utf-8") as f:
                    self._config_cache = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                self._config_cache = {}
        return self._config_cache

    def save_config(self, win, data: dict):
        try:
            with open(win._config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._config_cache = data
        except OSError:
            pass

    def refresh_task_list(self, win):
        win._task_combo.blockSignals(True)
        win._task_combo.clear()
        for t in list_tasks():
            win._task_combo.addItem(t)
            win._task_combo.setItemData(win._task_combo.count() - 1, t, Qt.ItemDataRole.ToolTipRole)
        win._task_combo.blockSignals(False)
        last = self.load_config(win).get("last_task", "")
        if last:
            idx = win._task_combo.findText(last)
            if idx >= 0:
                win._task_combo.setCurrentIndex(idx)
        if win._task_combo.count() == 0:
            win._on_task_new()
        win._on_task_changed(win._task_combo.currentText())
