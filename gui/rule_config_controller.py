import hashlib
import json
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt

from _loader import load_sibling, log_main
from i18n import T

_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
RuleFileError = _rule_mod.RuleFileError
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
    }

    def __init__(self):
        self._config_cache: dict | None = None
        self._load_error: RuleFileError | None = None
        self._save_conflict: RuleFileError | None = None
        self._config_baseline_exists = False
        self._config_baseline_digest: str | None = None
        self._config_baseline_path: str | None = None

    def reset_cache(self) -> None:
        self._config_cache = None
        self._load_error = None
        self._save_conflict = None
        self._config_baseline_exists = False
        self._config_baseline_digest = None
        self._config_baseline_path = None

    @staticmethod
    def _digest(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    def load_config(self, win) -> dict:
        path = str(win._config_path)
        if self._config_cache is not None and self._config_baseline_path == path:
            return self._config_cache

        self._config_cache = None
        self._load_error = None
        self._save_conflict = None
        self._config_baseline_exists = False
        self._config_baseline_digest = None
        self._config_baseline_path = path
        try:
            raw = Path(path).read_bytes()
        except FileNotFoundError:
            self._config_cache = {}
        except (OSError, UnicodeError) as e:
            self._config_cache = {}
            self._load_error = RuleFileError(path, f"無法讀取或解析 JSON：{e}")
            log_main(f"設定檔載入失敗：{self._load_error}")
        else:
            self._config_baseline_exists = True
            self._config_baseline_digest = self._digest(raw)
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, UnicodeError) as e:
                self._config_cache = {}
                self._load_error = RuleFileError(path, f"無法讀取或解析 JSON：{e}")
                log_main(f"設定檔載入失敗：{self._load_error}")
            else:
                if isinstance(data, dict):
                    self._config_cache = data
                else:
                    self._config_cache = {}
                    self._load_error = RuleFileError(path, "JSON 根層級必須是物件")
                    log_main(f"設定檔載入失敗：{self._load_error}")
        return self._config_cache

    def get_load_error(self) -> RuleFileError | None:
        return self._load_error

    def get_save_conflict(self) -> RuleFileError | None:
        return self._save_conflict

    def _mark_conflict(self, path: Path, reason: str) -> None:
        self._save_conflict = RuleFileError(str(path), reason)
        log_main(f"設定檔已在外部變更，拒絕覆寫：{self._save_conflict}")

    def _check_save_target(self, path: Path) -> bool:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            if self._config_baseline_exists:
                self._mark_conflict(path, "設定檔在載入後被刪除，拒絕寫入")
                return False
            return True
        except OSError as e:
            self._load_error = RuleFileError(str(path), f"無法讀取既有檔案，拒絕寫入：{e}")
            log_main(f"設定檔載入失敗，拒絕覆寫：{self._load_error}")
            return False

        try:
            existing = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError) as e:
            self._load_error = RuleFileError(str(path), f"既有檔案無法解析，拒絕覆寫：{e}")
            log_main(f"設定檔載入失敗，拒絕覆寫：{self._load_error}")
            return False
        if not isinstance(existing, dict):
            self._load_error = RuleFileError(str(path), "既有檔案根層級不是物件，拒絕覆寫")
            log_main(f"設定檔載入失敗，拒絕覆寫：{self._load_error}")
            return False

        if not self._config_baseline_exists:
            self._mark_conflict(path, "載入後偵測到外部建立的設定檔，拒絕覆寫")
            return False
        if self._config_baseline_digest != self._digest(raw):
            self._mark_conflict(path, "設定檔在載入後已被外部修改，拒絕覆寫")
            return False
        return True

    def get_setting(self, win, key: str, default=None):
        return self.load_config(win).get(key, self.DEFAULTS.get(key, default))

    def set_setting(self, win, key: str, value) -> bool:
        cfg = self.load_config(win)
        had_key = key in cfg
        old_value = cfg.get(key)
        cfg[key] = value
        if self.save_config(win, cfg):
            return True
        if had_key:
            cfg[key] = old_value
        else:
            cfg.pop(key, None)
        return False

    def save_config(self, win, data: dict) -> bool:
        # 原子寫入（tempfile + _replace_file）：中途崩潰不會留下半份 config.json
        if self._load_error is not None:
            log_main(f"設定檔載入失敗，拒絕覆寫：{self._load_error}")
            return False
        if self._save_conflict is not None:
            log_main(f"設定檔外部變更尚未處理，拒絕寫入：{self._save_conflict}")
            return False
        p = Path(win._config_path)
        if self._config_baseline_path not in (None, str(p)):
            self._mark_conflict(p, "設定檔路徑已變更，請重新載入設定")
            return False
        if not self._check_save_target(p):
            return False

        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
            ) as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                tmp_path = f.name
            new_digest = self._digest(Path(tmp_path).read_bytes())
            # 縮小檢查與替換間的競態窗口；仍無法涵蓋 replace 當下的外部寫入。
            if not self._check_save_target(p):
                Path(tmp_path).unlink(missing_ok=True)
                return False
            _replace_file(tmp_path, str(p))
            self._config_cache = data
            self._config_baseline_exists = True
            self._config_baseline_digest = new_digest
            self._config_baseline_path = str(p)
            self._save_conflict = None
            return True
        except OSError as e:
            log_main(f"設定檔寫入失敗：{p}：{e}")
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
            return False

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
