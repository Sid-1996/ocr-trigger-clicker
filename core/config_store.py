import hashlib
import json
import sys
import tempfile
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from _loader import load_sibling, log_main  # noqa: E402

_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
RuleFileError = _rule_mod.RuleFileError

_utils = load_sibling("file_utils", "core/file_utils.py")
_replace_file = _utils._replace_file


class ConfigStore:
    """設定檔讀寫（純資料層，不依賴 Qt）。

    由 gui/rule_config_controller.py 抽離而來。每個 owner（GUI 主視窗／設定視窗／
    背景 worker／主循環）各自持有一個實例、各自快取 config.json —— 這是既有行為，
    抽離時原樣保留，勿順手改成跨實例共享快取。

    讀寫語意（不變）：
    - load() 命中快取且路徑相同即直接回傳，必須 reset_cache() 才失效。
    - save() 以 SHA256 baseline 偵測「載入後被外部修改」，衝突時拒絕覆寫。
    - 寫入採 tempfile + _replace_file 原子替換，中途崩潰不留半份檔案。

    路徑來源有二種：
    - 建構時綁定（core/05_main_loop.py 用）：ConfigStore(config_path)，呼叫端不必帶路徑。
    - 每次呼叫覆寫（gui/rule_config_controller.py 用）：路徑存在於 win._config_path，
      呼叫端在每次呼叫時以 path= 明確帶入。
    """

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

    def __init__(self, path: str = ""):
        self._path = str(path)
        self._config_cache: dict | None = None
        self._load_error: RuleFileError | None = None
        self._save_conflict: RuleFileError | None = None
        self._config_baseline_exists = False
        self._config_baseline_digest: str | None = None
        self._config_baseline_path: str | None = None

    def _resolve_path(self, path: str | None) -> str:
        return str(path) if path is not None else self._path

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

    def load(self, path: str | None = None) -> dict:
        path = self._resolve_path(path)
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

    def get(self, key: str, default=None, path: str | None = None):
        return self.load(path).get(key, self.DEFAULTS.get(key, default))

    def set(self, key: str, value, path: str | None = None) -> bool:
        cfg = self.load(path)
        had_key = key in cfg
        old_value = cfg.get(key)
        cfg[key] = value
        if self.save(cfg, path):
            return True
        if had_key:
            cfg[key] = old_value
        else:
            cfg.pop(key, None)
        return False

    def save(self, data: dict, path: str | None = None) -> bool:
        # 原子寫入（tempfile + _replace_file）：中途崩潰不會留下半份 config.json
        if self._load_error is not None:
            log_main(f"設定檔載入失敗，拒絕覆寫：{self._load_error}")
            return False
        if self._save_conflict is not None:
            log_main(f"設定檔外部變更尚未處理，拒絕寫入：{self._save_conflict}")
            return False
        p = Path(self._resolve_path(path))
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
