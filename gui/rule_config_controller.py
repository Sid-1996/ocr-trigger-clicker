import json
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt

from _loader import load_sibling
from i18n import T

_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
list_tasks = _rule_mod.list_tasks

_utils = load_sibling("file_utils", "core/file_utils.py")
_replace_file = _utils._replace_file


class RuleConfigController:
    DEFAULTS = {
        "close_behavior": "tray",
        "show_close_confirm": True,
        "skip_update_check": False,
        "max_cps": 5,
        "scan_interval_ms": 500,
        "default_match_mode": "fuzzy",
        "default_fuzzy_threshold": 0.8,
        "default_template_threshold": 0.85,
        "default_color_tolerance": 10,
        "default_mouse_button": "left",
        "default_random_offset": 3,
        "default_wait_ms": 500,
        "default_after_delay_ms": 250,
        "default_detect_after_delay_ms": 250,
        # 錄製操作轉換專屬延時（與全域延時分離，穩定性優先；見 docs/adr/0002）
        "record_after_delay_ms": 500,
        "record_detect_after_delay_ms": 500,
        "language": "zh_TW",
        "notify_resource_warn": True,
        "ask_group_selection": True,
        "observation_shadow_enabled": False,
        "auto_resize_standard": False,
    }

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

    def get_setting(self, win, key: str, default=None):
        return self.load_config(win).get(key, self.DEFAULTS.get(key, default))

    def set_setting(self, win, key: str, value):
        cfg = self.load_config(win)
        cfg[key] = value
        self.save_config(win, cfg)

    def save_config(self, win, data: dict):
        # 原子寫入（tempfile + _replace_file）：中途崩潰不會留下半份 config.json
        tmp_path = ""
        try:
            p = Path(win._config_path)
            with tempfile.NamedTemporaryFile(
                "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
            ) as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                tmp_path = f.name
            _replace_file(tmp_path, str(p))
            self._config_cache = data
        except OSError:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

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
