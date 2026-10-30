"""MainWindow._open_settings 的設定快取失效行為（Phase 1 D1 回歸測試）。

背景：Phase 1 把設定讀寫抽到 core/config_store.py，MainLoop 的屬性由
`_rule_config_ctrl` 更名為 `_config_store`。`gui/06_gui_main.py` 的
`_open_settings()` 必須同時失效 MainWindow 與 MainLoop 兩份快取，
「關閉設定視窗 → 設定即時生效」才成立（基準版本即有的行為，非新增功能）。

驗證方式採可觀察行為而非 mock 次數：先讓兩份 ConfigStore 載入舊設定，
模擬設定視窗關閉前寫入新值，`_open_settings()` 返回後再讀一次，
確認兩者都讀得到新值（而非被快取凍結的舊值）。

測試不啟動完整應用程式：沿用 tests/ 既有的 SimpleNamespace fake 呼叫
未綁定方法模式（見 tests/test_gui_save_safety.py），SettingsDialog 以
假的 QDialog 類別取代，故不需要 QApplication，也不需要實際遊戲視窗。
"""

import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from conftest import make_main_loop

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

_gui = load_sibling("gui_main", "gui/06_gui_main.py")
MainWindow = _gui.MainWindow
RuleConfigController = _gui.RuleConfigController

# 必須用 load_sibling 取得與程式碼同一個模組物件（sys.modules["config_store"]），
# 直接 import core.config_store 會載入第二份模組。
_config_store = load_sibling("config_store", "core/config_store.py")
ConfigStore = _config_store.ConfigStore


def _write_config(path: Path, **values):
    path.write_text(json.dumps(values), encoding="utf-8")


def _fake_settings_dialog(monkeypatch, on_exec):
    """以假的 SettingsDialog 取代真的 QDialog，記錄建構與 exec。"""
    calls = {"constructed": [], "exec_count": 0}

    class _FakeDialog:
        def __init__(self, parent):
            calls["constructed"].append(parent)

        def exec(self):
            calls["exec_count"] += 1
            on_exec()
            return 0

    monkeypatch.setattr(_gui, "SettingsDialog", _FakeDialog)
    return calls


def test_open_settings_resets_main_loop_config_store_cache(tmp_path, monkeypatch):
    """執行中關閉設定視窗：MainWindow 與 MainLoop 兩份快取都要失效。"""
    config_path = tmp_path / "config.json"
    _write_config(config_path, language="ja", scan_interval_ms=500)

    win = SimpleNamespace(_config_path=str(config_path))
    main_ctrl = RuleConfigController()  # MainWindow 自己的 controller
    loop_ctrl = ConfigStore(str(config_path))  # MainLoop 的 ConfigStore（core 層）

    # 兩份都先建立快取（讀到舊值 500）
    assert main_ctrl.get_setting(win, "scan_interval_ms") == 500
    assert loop_ctrl.get("scan_interval_ms") == 500

    loop = SimpleNamespace(_config_store=loop_ctrl)
    assert main_ctrl is not loop_ctrl, "兩個 owner 必須是各自獨立的 ConfigStore 實例"

    def _on_exec():
        # 模擬使用者在設定視窗中存檔：設定檔被更新為新值
        _write_config(config_path, language="ja", scan_interval_ms=250)

    dialog_calls = _fake_settings_dialog(monkeypatch, _on_exec)
    label_updates = []
    fake = SimpleNamespace(
        _rule_config_ctrl=main_ctrl,
        _loop=loop,
        _update_interaction_mode_label=lambda: label_updates.append(True),
    )

    MainWindow._open_settings(fake)

    assert dialog_calls["exec_count"] == 1, "SettingsDialog 必須確實執行"
    assert dialog_calls["constructed"] == [fake]
    assert label_updates == [True], "_update_interaction_mode_label() 必須被呼叫"

    # 可觀察的快取失效：兩份都能讀到新值（未失效則仍回舊值 500）
    assert main_ctrl.get_setting(win, "scan_interval_ms") == 250
    assert loop_ctrl.get("scan_interval_ms") == 250


def test_open_settings_without_running_loop_still_resets_own_cache(tmp_path, monkeypatch):
    """MainLoop 不存在時：不得例外，MainWindow 自己的快取仍要失效。"""
    config_path = tmp_path / "config.json"
    _write_config(config_path, language="ja", scan_interval_ms=500)

    win = SimpleNamespace(_config_path=str(config_path))
    main_ctrl = RuleConfigController()
    assert main_ctrl.get_setting(win, "scan_interval_ms") == 500

    def _on_exec():
        _write_config(config_path, language="ja", scan_interval_ms=250)

    dialog_calls = _fake_settings_dialog(monkeypatch, _on_exec)
    label_updates = []
    fake = SimpleNamespace(
        _rule_config_ctrl=main_ctrl,
        _loop=None,
        _update_interaction_mode_label=lambda: label_updates.append(True),
    )

    MainWindow._open_settings(fake)

    assert dialog_calls["exec_count"] == 1
    assert label_updates == [True], "_update_interaction_mode_label() 仍須執行"
    assert main_ctrl.get_setting(win, "scan_interval_ms") == 250


def test_open_settings_makes_new_scan_interval_visible_to_main_loop(tmp_path, monkeypatch):
    """基準版既有行為：設定視窗改 scan_interval_ms 後，MainLoop 下一次讀取拿到新值。

    測試邊界：core/05_main_loop.py:2623 的 scan_interval 讀取位於 _loop()
    （整個主循環，含擷取與 OCR），單元測試不適合真的跑它。這裡以真實
    MainLoop 實例上的同一段讀取運算式
    `self._config_store.get("scan_interval_ms") / 1000.0` 驗證，
    覆蓋「快取失效 → 讀到新值」這個真正的行為。
    """
    config_path = tmp_path / "config.json"
    _write_config(config_path, language="ja", scan_interval_ms=500)

    ml = make_main_loop()
    ml._config_store = ConfigStore(str(config_path))

    # 先讀一次建立快取（MainLoop 讀的是舊值）
    assert ml._config_store.get("scan_interval_ms") / 1000.0 == 0.5

    win = SimpleNamespace(_config_path=str(config_path))
    main_ctrl = RuleConfigController()
    assert main_ctrl.get_setting(win, "scan_interval_ms") == 500

    def _on_exec():
        _write_config(config_path, language="ja", scan_interval_ms=250)

    _fake_settings_dialog(monkeypatch, _on_exec)
    fake = SimpleNamespace(
        _rule_config_ctrl=main_ctrl,
        _loop=ml,
        _update_interaction_mode_label=lambda: None,
    )

    MainWindow._open_settings(fake)

    # MainLoop 下一次讀取拿到新值（0.25 秒），而不是被快取凍結的 0.5 秒
    assert ml._config_store.get("scan_interval_ms") / 1000.0 == 0.25


def test_main_loop_exposes_config_store_attribute():
    """防止 MainLoop 設定屬性再次更名後，_open_settings 靜默失效。

    _open_settings() 直接存取 self._loop._config_store；若日後 MainLoop 的屬性
    改名，這裡會先失敗，而不是等到使用者開設定視窗才炸出 AttributeError。
    """
    ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
    src = inspect.getsource(ml_mod.MainLoop.__init__)
    assert "_config_store" in src, "MainLoop.__init__ 必須建立 _config_store"
    assert "_rule_config_ctrl" not in src, "舊屬性名不應再存在"
