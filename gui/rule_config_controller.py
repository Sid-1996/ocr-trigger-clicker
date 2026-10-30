from PyQt6.QtCore import Qt

from _loader import load_sibling
from i18n import T

_config_store = load_sibling("config_store", "core/config_store.py")
ConfigStore = _config_store.ConfigStore
RuleFileError = _config_store.RuleFileError

_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
list_tasks = _rule_mod.list_tasks


class RuleConfigController(ConfigStore):
    """設定存取 + 任務清單刷新（GUI 層外殼）。

    設定讀寫邏輯（快取、SHA256 baseline、原子寫入、外部修改衝突偵測）已抽到
    core/config_store.py，不依賴 Qt；本類保留原有 API（以 win 為參數），
    並額外提供需要 Qt 的任務清單刷新。

    既有行為不變：
    - 每個實例各自快取 config.json，命中快取即回傳（reset_cache 才失效）。
    - 寫入前以 baseline 偵測外部修改，衝突時拒絕覆寫。
    """

    def load_config(self, win) -> dict:
        return super().load(path=str(win._config_path))

    def save_config(self, win, data: dict) -> bool:
        return super().save(data, path=str(win._config_path))

    def get_setting(self, win, key: str, default=None):
        return super().get(key, default, path=str(win._config_path))

    def set_setting(self, win, key: str, value) -> bool:
        return super().set(key, value, path=str(win._config_path))

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
            from _loader import load_sibling

            _tm_mod = load_sibling("task_management", "core/task_management.py")
            _rule_mod2 = load_sibling("rule_engine", "core/04_rule_engine.py")
            _groups_mod = load_sibling(
                "group_settings_controller", "gui/group_settings_controller.py"
            )
            default_name = T("test.default_task")
            _tm_mod.save_task(default_name, [])
            from core.rule_models import RuleGroup

            _tm_mod.save_groups(
                [RuleGroup(id="__default__", name=T("test.default_group"))],
                str(_rule_mod2.get_tasks_dir() / f"{default_name}.json"),
            )
            win._task_combo.addItem(default_name)
            win._task_combo.setCurrentIndex(0)
        win._on_task_changed(win._task_combo.currentText())
