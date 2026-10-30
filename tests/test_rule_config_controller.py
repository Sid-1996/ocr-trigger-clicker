import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402
from gui.rule_config_controller import RuleConfigController  # noqa: E402

# 設定讀寫實作已抽到 core/config_store.py；_replace_file 隨實作一併搬過去。
# 必須用 load_sibling 取得「與程式碼同一個」模組物件（sys.modules["config_store"]），
# 直接 import core.config_store 會載入第二份模組，patch 不會生效、測試變空轉。
_config_store = load_sibling("config_store", "core/config_store.py")


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


def test_set_setting_returns_true_on_success(tmp_path):
    win = _make_win(tmp_path)
    ctrl = RuleConfigController()
    assert ctrl.set_setting(win, "language", "en") is True


def test_set_setting_returns_false_and_rolls_back_cache_on_failure(tmp_path, monkeypatch):
    win = _make_win(tmp_path)
    ctrl = RuleConfigController()
    assert ctrl.set_setting(win, "language", "zh_TW") is True

    def _boom(t, d):
        raise OSError("disk full")

    monkeypatch.setattr(_config_store, "_replace_file", _boom)
    assert ctrl.set_setting(win, "language", "en") is False
    assert ctrl.get_setting(win, "language") == "zh_TW"


def test_set_setting_failure_removes_new_key_from_cache(tmp_path, monkeypatch):
    win = _make_win(tmp_path)
    ctrl = RuleConfigController()

    def _boom(t, d):
        raise OSError("disk full")

    monkeypatch.setattr(_config_store, "_replace_file", _boom)
    assert ctrl.set_setting(win, "language", "en") is False
    assert "language" not in ctrl.load_config(win)


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

    def _boom(t, d):
        raise OSError("disk full")

    monkeypatch.setattr(_config_store, "_replace_file", _boom)
    ctrl.set_setting(win, "language", "en")
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["language"] == (
        "zh_TW"
    ), "寫入失敗時舊 config 不應被破壞"
    assert not list(tmp_path.glob("*.tmp")), "失敗時應清理暫存檔"


def test_corrupt_config_blocks_save_and_preserves_bytes(tmp_path):
    win = _make_win(tmp_path)
    p = tmp_path / "config.json"
    original = b'{"language": '
    p.write_bytes(original)
    ctrl = RuleConfigController()
    assert ctrl.get_setting(win, "scan_interval_ms") == 500
    err = ctrl.get_load_error()
    assert err is not None
    assert err.path == str(p)

    ctrl.set_setting(win, "language", "en")
    assert p.read_bytes() == original
    assert ctrl.save_config(win, {"language": "en"}) is False
    assert p.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_non_dict_config_blocks_save(tmp_path):
    win = _make_win(tmp_path)
    p = tmp_path / "config.json"
    p.write_text("[]", encoding="utf-8")
    ctrl = RuleConfigController()
    assert ctrl.get_setting(win, "language") == "zh_TW"
    assert ctrl.get_load_error() is not None
    assert ctrl.save_config(win, {"language": "en"}) is False
    assert p.read_text(encoding="utf-8") == "[]"


def test_config_save_refuses_external_corruption(tmp_path):
    win = _make_win(tmp_path)
    p = tmp_path / "config.json"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    ctrl = RuleConfigController()
    assert ctrl.get_setting(win, "language") == "ja"

    p.write_bytes(b'{"language": ')
    assert ctrl.save_config(win, {"language": "en"}) is False
    assert p.read_bytes() == b'{"language": '
    assert ctrl.get_load_error() is not None


def test_config_save_works_after_repair(tmp_path):
    win = _make_win(tmp_path)
    p = tmp_path / "config.json"
    p.write_text("not json", encoding="utf-8")
    ctrl = RuleConfigController()
    assert ctrl.get_setting(win, "language") == "zh_TW"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    ctrl.reset_cache()
    assert ctrl.get_load_error() is None
    assert ctrl.get_setting(win, "language") == "ja"
    assert ctrl.save_config(win, {"language": "en"}) is True
    assert json.loads(p.read_text(encoding="utf-8"))["language"] == "en"


@pytest.mark.parametrize(
    "external",
    [
        {"language": "en", "keep": 1},
        {"language": "ja"},
        {"language": "ja", "keep": 1, "external_only": True},
    ],
    ids=["modify", "delete", "add"],
)
def test_save_config_refuses_valid_external_field_changes(tmp_path, external):
    win = _make_win(tmp_path)
    p = tmp_path / "config.json"
    baseline = {"language": "ja", "keep": 1}
    p.write_text(json.dumps(baseline), encoding="utf-8")
    ctrl = RuleConfigController()
    assert ctrl.load_config(win) == baseline

    external_bytes = json.dumps(external).encode("utf-8")
    p.write_bytes(external_bytes)

    assert ctrl.save_config(win, {"language": "zh_TW", "max_cps": 7}) is False
    assert p.read_bytes() == external_bytes
    assert ctrl.get_save_conflict() is not None
    assert ctrl.get_load_error() is None
    assert ctrl.get_setting(win, "language") == "ja"
    assert ctrl.get_setting(win, "max_cps") == 5


def test_save_config_refuses_external_creation_and_deletion(tmp_path):
    win = _make_win(tmp_path)
    p = tmp_path / "config.json"
    ctrl = RuleConfigController()
    assert ctrl.load_config(win) == {}

    created = {"language": "en", "external_only": True}
    p.write_text(json.dumps(created), encoding="utf-8")
    assert ctrl.save_config(win, {"language": "zh_TW"}) is False
    assert json.loads(p.read_text(encoding="utf-8")) == created
    assert ctrl.get_save_conflict() is not None

    ctrl.reset_cache()
    assert ctrl.load_config(win) == created
    p.unlink()
    assert ctrl.save_config(win, {"language": "zh_TW"}) is False
    assert not p.exists()
    assert ctrl.get_save_conflict() is not None
    assert ctrl.get_setting(win, "language") == "en"


def test_conflict_does_not_call_replace_and_reset_reloads_external_file(tmp_path, monkeypatch):
    win = _make_win(tmp_path)
    p = tmp_path / "config.json"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    ctrl = RuleConfigController()
    assert ctrl.load_config(win) == {"language": "ja"}

    external = {"language": "en", "external_only": True}
    p.write_text(json.dumps(external), encoding="utf-8")
    called = []
    real_replace = _config_store._replace_file
    monkeypatch.setattr(_config_store, "_replace_file", lambda *args: called.append(args))

    assert ctrl.save_config(win, {"language": "zh_TW"}) is False
    assert called == []
    assert json.loads(p.read_text(encoding="utf-8")) == external
    assert not list(tmp_path.glob("*.tmp"))

    monkeypatch.setattr(_config_store, "_replace_file", real_replace)
    ctrl.reset_cache()
    assert ctrl.get_save_conflict() is None
    assert ctrl.load_config(win) == external
    assert ctrl.save_config(win, {"language": "zh_TW"}) is True
    assert json.loads(p.read_text(encoding="utf-8")) == {"language": "zh_TW"}


def test_set_setting_rolls_back_cache_on_external_change(tmp_path):
    win = _make_win(tmp_path)
    p = tmp_path / "config.json"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    ctrl = RuleConfigController()
    assert ctrl.load_config(win) == {"language": "ja"}

    external = {"language": "en", "external_only": True}
    p.write_text(json.dumps(external), encoding="utf-8")

    assert ctrl.set_setting(win, "language", "zh_TW") is False
    assert ctrl.get_setting(win, "language") == "ja"
    assert json.loads(p.read_text(encoding="utf-8")) == external


def test_replace_time_race_is_a_known_residual_limitation(tmp_path, monkeypatch):
    """Pins the remaining TOCTOU window after the last baseline check.

    The implementation rechecks immediately before ``_replace_file``; it cannot
    prevent another writer from changing the target between that check and the
    atomic replace. This test documents that boundary rather than claiming the
    race is eliminated.
    """
    win = _make_win(tmp_path)
    p = tmp_path / "config.json"
    p.write_text('{"language": "ja"}', encoding="utf-8")
    ctrl = RuleConfigController()
    assert ctrl.load_config(win) == {"language": "ja"}

    real_replace = _config_store._replace_file

    def _racing_replace(src, dst):
        Path(dst).write_text(
            json.dumps({"language": "en", "external_only": True}),
            encoding="utf-8",
        )
        real_replace(src, dst)

    monkeypatch.setattr(_config_store, "_replace_file", _racing_replace)

    assert ctrl.save_config(win, {"language": "zh_TW", "max_cps": 7}) is True
    assert json.loads(p.read_text(encoding="utf-8")) == {
        "language": "zh_TW",
        "max_cps": 7,
    }
    assert ctrl.get_save_conflict() is None
