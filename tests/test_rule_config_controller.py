import json
import sys
from pathlib import Path
from types import SimpleNamespace

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from gui.rule_config_controller import RuleConfigController  # noqa: E402


def _make_win(tmp_path):
    return SimpleNamespace(_config_path=str(tmp_path / "config.json"))


def test_set_get_setting_round_trip_and_defaults(tmp_path):
    win = _make_win(tmp_path)
    ctrl = RuleConfigController()
    assert ctrl.get_setting(win, "scan_interval_ms") == 500, "未寫入前應回 DEFAULTS"
    ctrl.set_setting(win, "scan_interval_ms", 250)
    assert ctrl.get_setting(win, "scan_interval_ms") == 250
    data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert data["scan_interval_ms"] == 250


def test_save_config_atomic_no_tmp_leftover(tmp_path):
    win = _make_win(tmp_path)
    ctrl = RuleConfigController()
    ctrl.set_setting(win, "language", "en")
    ctrl.set_setting(win, "max_cps", 8)
    files = list(tmp_path.iterdir())
    assert [f.name for f in files] == ["config.json"], "不應殘留 .tmp 暫存檔"
    assert ctrl.get_setting(win, "language") == "en"
    assert ctrl.get_setting(win, "max_cps") == 8


def test_save_config_failure_keeps_old_file(tmp_path, monkeypatch):
    win = _make_win(tmp_path)
    ctrl = RuleConfigController()
    ctrl.set_setting(win, "language", "zh_TW")

    import gui.rule_config_controller as _mod

    def _boom(t, d):
        raise OSError("disk full")

    monkeypatch.setattr(_mod, "_replace_file", _boom)
    ctrl.set_setting(win, "language", "en")
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["language"] == (
        "zh_TW"
    ), "寫入失敗時舊 config 不應被破壞"
    assert not list(tmp_path.glob("*.tmp")), "失敗時應清理暫存檔"
