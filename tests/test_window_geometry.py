"""主視窗幾何記憶（UX 2B-11）。

以真實 MainWindow（offscreen）+ 真實 ConfigStore 驗證：保存、還原、
舊版/非法資料回退、最大化/最小化語意、多螢幕夾制、Tray 保存路徑。
最大化在 offscreen 的可用面積與真機不同，故僅驗證狀態布林與尺寸保留，
不偽稱多螢幕真機已驗證。
"""

import json
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, QRect

from _loader import load_sibling

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

_gui = load_sibling("gui_main", "gui/06_gui_main.py")
_valid = _gui._valid_window_geometry
_clamp = _gui._clamp_window_rect


def _read_config(win) -> dict:
    return json.loads(Path(win._config_path).read_text(encoding="utf-8"))


def _write_config(win, data: dict) -> None:
    assert win._rule_config_ctrl.save_config(win, data)


def _teardown(win, qt_app) -> None:
    for name in ("_save_timer", "_status_timer", "_perf_timer"):
        timer = getattr(win, name, None)
        if timer is not None:
            timer.stop()
    try:
        win._bg_perf.stop()
    except Exception:
        pass
    loop = getattr(win, "_loop", None)
    if loop is not None:
        loop.stop()
    win.deleteLater()
    from PyQt6.QtCore import QCoreApplication

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_app.processEvents()


def _build_second(qt_app, isolated_data_dir) -> object:
    """在既有 real_mainwindow 測試內再建一扇 MainWindow（沿用 fixture 的 monkeypatch）。"""
    win = _gui.MainWindow()
    win._perf_timer.stop()
    return win


# ── 純函式：資料驗證 ────────────────────────────────────────────


def test_valid_geometry_accepted_and_bool_rejected():
    assert _valid({"x": 0, "y": 0, "width": 900, "height": 650, "maximized": False})
    assert not _valid("not-a-dict")
    assert not _valid({"x": 0, "y": 0, "width": 900, "height": 650})  # 缺 maximized
    assert not _valid({"x": True, "y": 0, "width": 900, "height": 650, "maximized": False})
    assert not _valid({"x": 0, "y": 0, "width": 0, "height": 650, "maximized": False})
    assert not _valid({"x": 0, "y": 0, "width": -5, "height": 650, "maximized": False})
    assert not _valid({"x": 0, "y": 0, "width": 900, "height": 650, "maximized": 1})
    assert not _valid({"x": 0, "y": 0, "width": 99999, "height": 650, "maximized": False})


# ── 純函式：螢幕夾制（真實 QRect 輸入）────────────────────────────


def test_clamp_center_outside_all_screens_returns_none():
    screens = [QRect(0, 0, 1920, 1080), QRect(1920, 0, 1920, 1080)]
    assert _clamp(QRect(5000, 5000, 900, 650), screens) is None


def test_clamp_overflow_shrinks_and_moves_inside():
    screens = [QRect(0, 0, 800, 600)]
    clamped = _clamp(QRect(100, 100, 900, 650), screens)
    assert clamped is not None
    assert clamped.width() <= 800 and clamped.height() <= 600
    assert clamped.x() >= 0 and clamped.y() >= 0
    assert clamped.x() + clamped.width() <= 800
    assert clamped.y() + clamped.height() <= 600
    assert clamped.width() >= 320 and clamped.height() >= 240


def test_clamp_second_screen_negative_origin():
    screens = [QRect(-1920, 0, 1920, 1080), QRect(0, 0, 1920, 1080)]
    clamped = _clamp(QRect(-1800, 100, 900, 650), screens)
    assert clamped is not None
    assert -1920 <= clamped.x() and clamped.x() + clamped.width() <= 0


# ── 保存 / 還原（真實視窗）─────────────────────────────────────


def test_save_normal_and_restore_into_new_window(real_mainwindow, qt_app, isolated_data_dir):
    win = real_mainwindow
    win.showNormal()
    win.move(120, 140)
    win.resize(1300, 700)
    win._save_window_geometry()
    saved = _read_config(win)["window_geometry"]
    assert saved == {"x": 120, "y": 140, "width": 1300, "height": 700, "maximized": False}

    # offscreen 可用螢幕僅 800x800：1300 寬會被夾制到 800（見純函式測試），
    # 此處驗證還原確實執行（centered 旗標）且結果落在可用範圍內。
    win2 = _build_second(qt_app, isolated_data_dir)
    try:
        assert win2._centered_once is True
        assert not win2.isMaximized()
        assert -4 <= win2.x() and win2.x() + win2.width() <= 804
        assert -4 <= win2.y() and win2.y() + win2.height() <= 804
    finally:
        _teardown(win2, qt_app)


def test_restore_exact_geometry_from_config(real_mainwindow, qt_app, isolated_data_dir):
    win = real_mainwindow
    _write_config(
        win,
        {"window_geometry": {"x": 50, "y": 60, "width": 700, "height": 500, "maximized": False}},
    )
    win2 = _build_second(qt_app, isolated_data_dir)
    try:
        assert win2._centered_once is True
        assert (win2.width(), win2.height()) == (700, 500)
        # 隱藏視窗的 x()/y() 含 Qt frame 補償（show 後才精確），故容差 ±4px
        assert abs(win2.x() - 50) <= 4 and abs(win2.y() - 60) <= 4
        assert not win2.isMaximized()
        win2.show()
        qt_app.processEvents()
        assert (win2.x(), win2.y()) == (50, 60)
    finally:
        _teardown(win2, qt_app)


def test_no_old_geometry_keeps_default(real_mainwindow):
    # isolated_data_dir 為空 → 無 window_geometry → 維持 900x650 預設、未還原
    assert "window_geometry" not in real_mainwindow._load_config()
    assert (real_mainwindow.width(), real_mainwindow.height()) == (900, 650)
    assert real_mainwindow._centered_once is False


@pytest.mark.parametrize(
    "bad",
    [
        "x",
        {"x": 0, "y": 0, "width": 900, "height": 650},  # 缺欄位
        {"x": 0, "y": 0, "width": 0, "height": 650, "maximized": False},  # 零尺寸
        {"x": 0, "y": 0, "width": 900, "height": 650, "maximized": "yes"},  # 型別錯誤
    ],
)
def test_invalid_geometry_falls_back_silently(real_mainwindow, bad):
    win = real_mainwindow
    _write_config(win, {"window_geometry": bad})
    win._rule_config_ctrl.reset_cache()
    win.move(10, 10)
    win.resize(500, 400)
    win._centered_once = False
    win._restore_window_geometry()  # 不拋錯
    assert win._centered_once is False  # 未還原 → 之後由 showEvent 置中
    assert (win.width(), win.height()) == (500, 400)


def test_maximized_saved_and_restored(real_mainwindow, qt_app, isolated_data_dir):
    win = real_mainwindow
    win.showNormal()
    win.move(200, 200)
    win.resize(1300, 800)
    win._save_window_geometry()  # 先記一般尺寸
    win.showMaximized()
    win._save_window_geometry()  # 最大化：只翻 maximized，不覆蓋一般尺寸
    saved = _read_config(win)["window_geometry"]
    assert saved["maximized"] is True
    assert (saved["width"], saved["height"]) == (1300, 800)
    # normalGeometry() 含 frame 座標（offscreen 差 2px；Windows 差標題列高），
    # 保存時已扣除正常狀態觀測到的偏移 → 與 geometry() 基準一致
    assert (saved["x"], saved["y"]) == (200, 200)

    # 同上：1300 寬的舊矩形中心在 offscreen 800x800 外會回退預設，
    # 故改以可容納的幾何驗證最大化還原。
    _write_config(
        win,
        {"window_geometry": {"x": 50, "y": 60, "width": 700, "height": 500, "maximized": True}},
    )
    win2 = _build_second(qt_app, isolated_data_dir)
    try:
        assert win2.isMaximized()
        assert win2._centered_once is True
    finally:
        _teardown(win2, qt_app)


def test_minimized_does_not_overwrite(real_mainwindow):
    win = real_mainwindow
    win.showNormal()
    win.move(300, 300)
    win.resize(900, 600)
    win._save_window_geometry()
    before = _read_config(win)["window_geometry"]
    win.showMinimized()
    win._save_window_geometry()  # 必須保留舊資料
    assert _read_config(win)["window_geometry"] == before
    win.showNormal()


def test_restore_does_not_recenter_on_show(real_mainwindow):
    win = real_mainwindow
    win.showNormal()
    win.move(400, 300)
    win.resize(900, 650)
    _write_config(
        win,
        {"window_geometry": {"x": 400, "y": 300, "width": 900, "height": 650, "maximized": False}},
    )
    win._rule_config_ctrl.reset_cache()
    win._restore_window_geometry()
    assert (win.x(), win.y()) == (400, 300)
    win.show()  # showEvent 不得再次置中覆蓋
    assert (win.x(), win.y()) == (400, 300)


# ── Tray 保存路徑 ──────────────────────────────────────────────


def test_tray_close_saves_geometry(real_mainwindow, monkeypatch):
    win = real_mainwindow
    win.showNormal()
    win.move(150, 160)
    win.resize(1250, 680)
    _write_config(win, {"close_behavior": "tray", "show_close_confirm": False})
    win._rule_config_ctrl.reset_cache()

    class _FakeEvent:
        def __init__(self):
            self.accepted = None

        def accept(self):
            self.accepted = True

        def ignore(self):
            self.accepted = False

    event = _FakeEvent()
    win.closeEvent(event)  # tray 路徑 → ignore + hide，但必須已保存
    assert event.accepted is False
    assert _read_config(win)["window_geometry"]["width"] == 1250


def test_tray_menu_quit_saves_geometry(real_mainwindow, monkeypatch):
    win = real_mainwindow
    win.showNormal()
    win.move(170, 180)
    win.resize(1260, 690)
    win._quit_app()  # Tray 選單 tray.quit 的實際目標（06_gui_main.py:5566）
    assert _read_config(win)["window_geometry"] == {
        "x": 170,
        "y": 180,
        "width": 1260,
        "height": 690,
        "maximized": False,
    }


# ── 最大化還原迴歸（c70ded2 缺陷：最大化時保存未用 normalGeometry）────
# offscreen 說明：最大化矩形為 796x796；標題列「還原」以 showNormal() 模擬，
# 真正的 Windows WM 還原行為仍需真機驗證（見交付報告）。


def test_default_size_maximized_save_keeps_normal_size(real_mainwindow, qt_app):
    win = real_mainwindow
    # 首次執行：隱藏預設 900x650 → 直接最大化 → 關閉
    win.showMaximized()
    qt_app.processEvents()
    assert win.isMaximized()
    maximized_rect = (win.width(), win.height())
    win._save_window_geometry()
    saved = _read_config(win)["window_geometry"]
    assert saved["maximized"] is True
    # 保存的是還原後的一般尺寸（normalGeometry），不是最大化矩形
    assert (saved["width"], saved["height"]) == (
        win.normalGeometry().width(),
        win.normalGeometry().height(),
    )
    assert (saved["width"], saved["height"]) != maximized_rect
    assert saved["height"] == 650  # 預設高度保留


def test_maximized_restart_then_unmaximize_restores_custom_size(
    real_mainwindow, qt_app, isolated_data_dir
):
    win = real_mainwindow
    _write_config(
        win,
        {"window_geometry": {"x": 50, "y": 60, "width": 700, "height": 500, "maximized": True}},
    )
    win2 = _build_second(qt_app, isolated_data_dir)
    try:
        assert win2.isMaximized()
        win2.showNormal()  # 模擬標題列「還原」按鈕
        qt_app.processEvents()
        assert not win2.isMaximized()
        assert (win2.width(), win2.height()) == (700, 500)
        assert (win2.x(), win2.y()) == (50, 60)
    finally:
        _teardown(win2, qt_app)


def test_maximized_restart_roundtrip_keeps_normal_size(real_mainwindow, qt_app, isolated_data_dir):
    win = real_mainwindow
    _write_config(
        win,
        {"window_geometry": {"x": 50, "y": 60, "width": 700, "height": 500, "maximized": True}},
    )
    win2 = _build_second(qt_app, isolated_data_dir)
    try:
        win2.showNormal()
        qt_app.processEvents()
        win2._save_window_geometry()  # 還原後再次關閉
        assert _read_config(win2)["window_geometry"] == {
            "x": 50,
            "y": 60,
            "width": 700,
            "height": 500,
            "maximized": False,
        }
    finally:
        _teardown(win2, qt_app)
    win3 = _build_second(qt_app, isolated_data_dir)
    try:
        assert not win3.isMaximized()
        assert (win3.width(), win3.height()) == (700, 500)
    finally:
        _teardown(win3, qt_app)


def test_resize_after_unmaximize_then_remaximize_saves_new_size(
    real_mainwindow, qt_app, isolated_data_dir
):
    win = real_mainwindow
    _write_config(
        win,
        {"window_geometry": {"x": 50, "y": 60, "width": 700, "height": 500, "maximized": True}},
    )
    win2 = _build_second(qt_app, isolated_data_dir)
    try:
        win2.showNormal()
        qt_app.processEvents()
        win2.move(80, 90)
        win2.resize(1200, 520)
        qt_app.processEvents()
        win2.showMaximized()
        qt_app.processEvents()
        win2._save_window_geometry()
        saved = _read_config(win2)["window_geometry"]
        assert saved["maximized"] is True
        assert (saved["width"], saved["height"]) == (1200, 520)
        assert abs(saved["x"] - 80) <= 4 and abs(saved["y"] - 90) <= 4
    finally:
        _teardown(win2, qt_app)


# ── Frame 基準校正（Windows normalGeometry 差標題列高，逐輪位移）────


def test_first_launch_maximize_save_keeps_default_center(real_mainwindow, qt_app):
    win = real_mainwindow
    win.show()  # 首次顯示 → showEvent 置中並觀測偏移
    qt_app.processEvents()
    default_y = win.y()
    default_h = win.height()
    assert default_h == 650
    win.showMaximized()
    qt_app.processEvents()
    win._save_window_geometry()
    saved = _read_config(win)["window_geometry"]
    assert saved["maximized"] is True
    assert saved["height"] == default_h
    assert saved["y"] == default_y  # 扣除 frame 偏移後回到初始中央位置


def test_restored_maximized_save_uses_session_rect(real_mainwindow, qt_app, isolated_data_dir):
    win = real_mainwindow
    _write_config(
        win,
        {"window_geometry": {"x": 50, "y": 60, "width": 700, "height": 500, "maximized": True}},
    )
    win2 = _build_second(qt_app, isolated_data_dir)
    try:
        assert win2.isMaximized()
        assert win2._last_normal_rect == {"x": 50, "y": 60, "width": 700, "height": 500}
        # 剛以最大化還原時 normalGeometry() 無效 → 用會話記住的一般矩形保存
        win2._save_window_geometry()
        assert _read_config(win2)["window_geometry"] == {
            "x": 50,
            "y": 60,
            "width": 700,
            "height": 500,
            "maximized": True,
        }
    finally:
        _teardown(win2, qt_app)


def test_session_resize_then_maximize_saves_latest(real_mainwindow, qt_app):
    win = real_mainwindow
    win.showNormal()
    win.move(100, 100)
    win.resize(1300, 800)
    win._save_window_geometry()  # 舊磁碟值 1300x800
    win.move(150, 150)
    win.resize(1200, 700)  # 未保存的最新一般尺寸
    qt_app.processEvents()
    win.showMaximized()
    qt_app.processEvents()
    win._save_window_geometry()
    saved = _read_config(win)["window_geometry"]
    assert (saved["width"], saved["height"]) == (1200, 700)
    assert (saved["x"], saved["y"]) == (150, 150)


def test_double_save_is_idempotent(real_mainwindow):
    win = real_mainwindow
    win.showNormal()
    win.move(111, 122)
    win.resize(1233, 644)
    win._save_window_geometry()
    first = _read_config(win)["window_geometry"]
    win._save_window_geometry()  # closeEvent + _quit_app 雙重觸發
    assert _read_config(win)["window_geometry"] == first


def test_corrupt_config_does_not_block_startup(qt_app, isolated_data_dir, monkeypatch):
    data_dir = isolated_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.json").write_text("{broken json", encoding="utf-8")
    from PyQt6.QtWidgets import QApplication as _QA

    from _loader import load_sibling

    gui = load_sibling("gui_main", "gui/06_gui_main.py")
    monkeypatch.setattr(gui.MainWindow, "_deferred_init", lambda self: None)
    monkeypatch.setattr(gui.MainWindow, "_check_version", lambda self, force=False: None)
    monkeypatch.setattr(gui, "_hk_unregister", lambda hwnd: None)
    monkeypatch.setattr(_QA, "quit", staticmethod(lambda: None))
    perf_mod = load_sibling("performance_monitor", "core/10_performance_monitor.py")
    monkeypatch.setattr(perf_mod.PerformanceMonitor, "start", lambda self: None)
    win = gui.MainWindow()  # 損壞設定不可阻止啟動
    try:
        assert (win.width(), win.height()) == (900, 650)
    finally:
        _teardown(win, qt_app)
