import inspect
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

# 必須用 load_sibling 取得與程式碼同一個模組物件（sys.modules["config_store"]）；
# 直接 import core.config_store 會載入第二份模組，monkeypatch 不生效、測試變空轉。
_config_store = load_sibling("config_store", "core/config_store.py")
ConfigStore = _config_store.ConfigStore

from gui.rule_config_controller import RuleConfigController  # noqa: E402

# 抽離前的 DEFAULTS 全量清單（20 個 key）。抽離不得新增或更動任何預設 key。
_EXPECTED_DEFAULT_KEYS = {
    "close_behavior",
    "show_close_confirm",
    "skip_update_check",
    "max_cps",
    "scan_interval_ms",
    "default_match_mode",
    "default_fuzzy_threshold",
    "default_template_threshold",
    "default_color_tolerance",
    "default_mouse_button",
    "default_random_offset",
    "default_wait_ms",
    "default_after_delay_ms",
    "default_detect_after_delay_ms",
    "record_after_delay_ms",
    "record_detect_after_delay_ms",
    "language",
    "notify_resource_warn",
    "ask_group_selection",
    "observation_shadow_enabled",
}


def _win(path: Path) -> SimpleNamespace:
    return SimpleNamespace(_config_path=str(path))


# ── 1. 每個 owner 實例各自快取（既有行為，抽離後不得改變）────────────────────


def test_four_owner_instances_keep_independent_caches(tmp_path):
    """GUI 主視窗／設定視窗／背景 worker／主循環各持一個實例，各自有快取。"""
    p = tmp_path / "config.json"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    win = _win(p)
    owners = [RuleConfigController() for _ in range(4)]
    for o in owners:
        assert o.get_setting(win, "language") == "ja"

    assert owners[0].set_setting(win, "language", "en") is True
    assert owners[0].get_setting(win, "language") == "en"
    # 其餘 owner 仍看到自己快取裡的舊值——這是既有行為，不因抽離而改變
    assert owners[1].get_setting(win, "language") == "ja"
    assert owners[2].get_setting(win, "language") == "ja"
    assert owners[3].get_setting(win, "language") == "ja"
    # 檔案本身已是新值
    assert json.loads(p.read_text(encoding="utf-8"))["language"] == "en"


def test_core_owner_store_is_independent_from_gui_owner(tmp_path):
    """Core 端 ConfigStore 與 GUI 端 RuleConfigController 是兩個實例、各自快取。"""
    p = tmp_path / "config.json"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    gui_ctrl = RuleConfigController()
    core_store = ConfigStore(str(p))
    win = _win(p)

    assert gui_ctrl.get_setting(win, "language") == "ja"
    assert core_store.get("language") == "ja"

    assert gui_ctrl.set_setting(win, "language", "en") is True
    assert core_store.get("language") == "ja", "Core store 是另一實例，不該看到 GUI 的寫入"

    core_store.reset_cache()
    assert core_store.get("language") == "en"


def test_reset_cache_invalidates_cache_and_reloads(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    store = ConfigStore(str(p))
    assert store.get("language") == "ja"

    p.write_text('{"language": "en"}', encoding="utf-8")
    assert store.get("language") == "ja", "未 reset 前仍應回快取值"

    store.reset_cache()
    assert store.get("language") == "en"
    assert store.get_load_error() is None
    assert store.get_save_conflict() is None


# ── 2. 同一實例切換 config path ───────────────────────────────────────────────


def test_same_instance_reloads_when_path_switches(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text('{"language": "ja"}', encoding="utf-8")
    b.write_text('{"language": "en"}', encoding="utf-8")
    ctrl = RuleConfigController()
    assert ctrl.get_setting(_win(a), "language") == "ja"
    assert ctrl.get_setting(_win(b), "language") == "en", "切換路徑應重新載入"


def test_save_to_a_different_path_is_refused_as_path_conflict(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text('{"language": "ja"}', encoding="utf-8")
    b.write_text('{"language": "en"}', encoding="utf-8")
    ctrl = RuleConfigController()
    assert ctrl.get_setting(_win(a), "language") == "ja"

    assert ctrl.save_config(_win(b), {"language": "zh_TW"}) is False
    assert ctrl.get_save_conflict() is not None
    assert ctrl.get_load_error() is None
    assert json.loads(b.read_text(encoding="utf-8"))["language"] == "en"


def test_core_store_uses_bound_path_unless_overridden(tmp_path):
    p = tmp_path / "config.json"
    other = tmp_path / "other.json"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    other.write_text('{"language": "en"}', encoding="utf-8")
    store = ConfigStore(str(p))

    assert store.get("language") == "ja"
    assert store.get("language", path=str(other)) == "en"
    # 綁定路徑不受覆寫影響
    assert store.get("language") == "ja"


# ── 3. config.json 不存在／格式錯誤／寫入失敗 ────────────────────────────────


def test_missing_config_returns_defaults_and_can_be_created(tmp_path):
    p = tmp_path / "config.json"
    ctrl = RuleConfigController()
    win = _win(p)
    assert ctrl.get_setting(win, "language") == "zh_TW"
    assert ctrl.get_load_error() is None, "檔案不存在不算錯誤"

    assert ctrl.save_config(win, {"language": "en"}) is True
    assert json.loads(p.read_text(encoding="utf-8"))["language"] == "en"


def test_corrupt_config_records_error_and_refuses_to_overwrite(tmp_path):
    p = tmp_path / "config.json"
    original = b'{"language": '
    p.write_bytes(original)
    store = ConfigStore(str(p))

    assert store.get("language") == "zh_TW"
    err = store.get_load_error()
    assert err is not None
    assert err.path == str(p)

    assert store.save({"language": "en"}) is False
    assert p.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_non_dict_config_is_rejected(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("[]", encoding="utf-8")
    store = ConfigStore(str(p))
    assert store.get("language") == "zh_TW"
    assert store.get_load_error() is not None
    assert store.save({"language": "en"}) is False
    assert p.read_text(encoding="utf-8") == "[]"


def test_write_failure_keeps_old_file_and_rolls_back_cache(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    store = ConfigStore(str(p))
    assert store.set("language", "zh_TW") is True

    def _boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(_config_store, "_replace_file", _boom)
    assert store.set("language", "en") is False
    assert json.loads(p.read_text(encoding="utf-8"))["language"] == "zh_TW"
    assert not list(tmp_path.glob("*.tmp")), "寫入失敗應清理暫存檔"
    assert store.get("language") == "zh_TW", "寫入失敗應回滾快取"


# ── 4. 外部修改衝突偵測 ──────────────────────────────────────────────────────


def test_external_modification_is_detected_and_write_refused(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    store = ConfigStore(str(p))
    assert store.get("language") == "ja"

    p.write_text('{"language": "en"}', encoding="utf-8")
    assert store.save({"language": "zh_TW"}) is False
    assert store.get_save_conflict() is not None
    assert store.get_load_error() is None
    assert json.loads(p.read_text(encoding="utf-8"))["language"] == "en"
    assert store.get("language") == "ja", "衝突後快取仍是載入時的值"


def test_external_deletion_is_detected(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    store = ConfigStore(str(p))
    assert store.get("language") == "ja"

    p.unlink()
    assert store.save({"language": "zh_TW"}) is False
    assert store.get_save_conflict() is not None
    assert not p.exists()


def test_external_creation_after_load_is_detected(tmp_path):
    p = tmp_path / "config.json"
    store = ConfigStore(str(p))
    assert store.load() == {}

    p.write_text('{"language": "en"}', encoding="utf-8")
    assert store.save({"language": "zh_TW"}) is False
    assert store.get_save_conflict() is not None
    assert json.loads(p.read_text(encoding="utf-8"))["language"] == "en"


# ── 5. GUI Controller 既有 API 完全相容 ──────────────────────────────────────


def test_gui_controller_public_api_signatures_unchanged():
    assert list(inspect.signature(RuleConfigController.load_config).parameters) == ["self", "win"]
    assert list(inspect.signature(RuleConfigController.save_config).parameters) == [
        "self",
        "win",
        "data",
    ]
    assert list(inspect.signature(RuleConfigController.get_setting).parameters) == [
        "self",
        "win",
        "key",
        "default",
    ]
    assert list(inspect.signature(RuleConfigController.set_setting).parameters) == [
        "self",
        "win",
        "key",
        "value",
    ]
    assert list(inspect.signature(RuleConfigController.refresh_task_list).parameters) == [
        "self",
        "win",
    ]
    for name in ("reset_cache", "get_load_error", "get_save_conflict"):
        assert callable(getattr(RuleConfigController, name)), name


def test_defaults_are_unchanged_and_not_extended():
    assert set(ConfigStore.DEFAULTS) == _EXPECTED_DEFAULT_KEYS
    assert set(RuleConfigController.DEFAULTS) == _EXPECTED_DEFAULT_KEYS
    assert RuleConfigController.DEFAULTS is ConfigStore.DEFAULTS
    assert ConfigStore.DEFAULTS["scan_interval_ms"] == 500
    assert ConfigStore.DEFAULTS["language"] == "zh_TW"


def test_interaction_mode_absent_from_defaults_returns_none(tmp_path):
    """interaction_mode 不在 DEFAULTS，缺失時回 None。

    core/05_main_loop.py:2666 以 `in (None, "pynput")` 判斷前景模式，
    這個 None 語意不得因抽離而改變。
    """
    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    ctrl = RuleConfigController()
    win = _win(p)
    assert ctrl.get_setting(win, "interaction_mode") is None
    assert ctrl.get_setting(win, "interaction_mode", "pynput") == "pynput"


def test_gui_controller_round_trip_still_works(tmp_path):
    p = tmp_path / "config.json"
    ctrl = RuleConfigController()
    win = _win(p)
    assert ctrl.get_setting(win, "scan_interval_ms") == 500
    assert ctrl.set_setting(win, "scan_interval_ms", 250) is True
    assert ctrl.get_setting(win, "scan_interval_ms") == 250
    assert json.loads(p.read_text(encoding="utf-8"))["scan_interval_ms"] == 250


# ── 6. Core 不再依賴 GUI 或 PyQt6 ────────────────────────────────────────────


def test_core_main_loop_has_no_gui_dependency():
    src = (_root / "core" / "05_main_loop.py").read_text(encoding="utf-8")
    assert "gui/" not in src, "core/05_main_loop.py 不得依賴 gui/ 模組"
    assert re.search(r"^\s*(from|import)\s+PyQt", src, re.M) is None


def test_no_core_module_imports_pyyqt():
    for f in sorted((_root / "core").glob("*.py")):
        text = f.read_text(encoding="utf-8")
        assert re.search(r"^\s*(from|import)\s+PyQt", text, re.M) is None, (
            f"{f.name} 不得 import PyQt"
        )


def test_importing_core_main_loop_does_not_load_pyyqt_or_gui_controller():
    code = (
        "import sys\n"
        "class _Blocker:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'PyQt6' or name.startswith('PyQt6.'):\n"
        "            raise ImportError('PyQt6 is blocked in this test')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Blocker())\n"
        "sys.path.insert(0, " + repr(str(_root)) + ")\n"
        "from _loader import load_sibling\n"
        "m = load_sibling('main_loop', 'core/05_main_loop.py')\n"
        "assert 'PyQt6' not in sys.modules, sorted(k for k in sys.modules if 'PyQt' in k)\n"
        "assert 'rule_config_controller' not in sys.modules\n"
        "assert 'gui.rule_config_controller' not in sys.modules\n"
        "print('OK')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout


def test_main_loop_binds_config_store_to_its_config_path():
    ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
    src = inspect.getsource(ml_mod.MainLoop.__init__)
    assert "ConfigStore(config_path)" in src, "MainLoop 必須把自身設定路徑綁進 ConfigStore"
