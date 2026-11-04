"""GUI 啟動循環時的最小化行為（hybrid 前景保護 UX 修正）。

問題根因
    hybrid 依賴前景物理輸入。``MainLoop._is_tool_foreground()``
    （``core/05_main_loop.py``）在「工具自身視窗位於前景」時會擋掉每一個輸入
    動作（click／key／drag／scroll 皆回 ``StepResult("stop")``，規則本回合結束、
    下一幀重試）。舊流程在 GUI 按「開始循環」後視窗仍留在前景 → 使用者必須
    手動切到別的視窗，第一次循環才會真的送出動作。

修正（只動 GUI 啟動流程，Focus Guard 本身不動）
    hybrid 啟動前先最小化主視窗並確認已離開前景，再啟動循環。
    非 hybrid（frida／pynput）行為不變；啟動失敗時視窗必須還原。

本檔以真實 MainWindow 驅動實際啟動流程，驗證「最小化確實發生在啟動循環之前」
與實際視窗狀態；不 mock 最小化函式本身。
"""

import ctypes

import pytest
from conftest import make_main_loop as _make_ml
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from _loader import load_sibling

_gui = load_sibling("gui_main", "gui/06_gui_main.py")
_rule_models = load_sibling("rule_models", "core/rule_models.py")
_ml_mod = load_sibling("main_loop", "core/05_main_loop.py")


class _FakeLoop:
    def __init__(self):
        self.tool_hwnd = None
        self.stopped = False

    def set_tool_hwnd(self, hwnd):
        self.tool_hwnd = hwnd

    def stop(self):
        self.stopped = True

    def get_execution_log(self):
        return []


class _FakeInitWorker(QObject):
    """假的 InitWorker：記錄「啟動當下」主視窗的實際狀態。

    重點在於狀態是在 ``start()`` 被呼叫的當下取樣 → 若最小化發生在啟動之後，
    取樣就會是 False，測試即可抓到呼叫順序錯誤。
    """

    finished = pyqtSignal(bool, str)

    window = None
    start_error: Exception | None = None

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.loop = _FakeLoop()
        self.started = False
        self.minimized_when_started = None
        self.tool_was_foreground_when_started = None

    def start(self):
        if type(self).start_error is not None:
            raise type(self).start_error
        self.started = True
        win = type(self).window
        self.minimized_when_started = win.isMinimized()
        self.tool_was_foreground_when_started = win._is_foreground_window()


@pytest.fixture
def win(real_mainwindow, monkeypatch):
    """真實主視窗（offscreen），InitWorker 以假物件取代。"""
    window = real_mainwindow
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(_gui, "activate_window", lambda title: True)
    monkeypatch.setattr(_gui, "activate_window_bg", lambda title: True)
    # 後台模式的啟動前截幀檢查：測試不需要真實截圖
    monkeypatch.setattr(_gui, "is_admin", lambda: True)
    monkeypatch.setattr(_gui, "get_window_hwnd", lambda title: 0)
    monkeypatch.setattr(_gui, "capture_frame", lambda *a, **k: None)
    monkeypatch.setattr(
        window,
        "_window_combo",
        type("_Combo", (), {"currentText": lambda self: "測試視窗"})(),
    )
    monkeypatch.setattr(window, "_save_current_rule", lambda: None)
    monkeypatch.setattr(window, "_flush_save", lambda: True)
    window._rules = [
        _rule_models.Rule(
            id="r1",
            name="規則",
            enabled=True,
            steps=[_rule_models.Step(type="detect", params={"text": "確定"})],
        )
    ]
    window._groups = []
    window._current_task = ""

    _FakeInitWorker.window = window
    _FakeInitWorker.start_error = None
    monkeypatch.setattr(_gui, "InitWorker", _FakeInitWorker)
    try:
        yield window
    finally:
        _FakeInitWorker.window = None
        timer = getattr(window, "_exec_log_timer", None)
        if timer is not None:
            timer.stop()
        window._minimized_for_loop = False


def _set_mode(win, monkeypatch, mode: str) -> None:
    """設定互動模式（GUI 以 interaction_mode 判斷 hybrid／frida／pynput）。"""
    ctrl = win._rule_config_ctrl
    original = ctrl.get_setting

    def _get_setting(_win, key, default=None):
        if key == "interaction_mode":
            return mode
        return original(_win, key, default)

    monkeypatch.setattr(ctrl, "get_setting", _get_setting)
    monkeypatch.setattr(win, "_is_bg_mode", lambda: mode != "pynput")


# ── 1. 正常啟動 ─────────────────────────────────────────────────────


def test_hybrid_start_minimizes_before_loop_starts(win, monkeypatch):
    """hybrid：啟動循環前必須已完成最小化（呼叫順序，不可事後才補）。"""
    _set_mode(win, monkeypatch, "hybrid")
    win._start_loop(group_ids=["g1"])

    assert win._init_worker.started, "前置條件：InitWorker 應已啟動"
    assert win._init_worker.minimized_when_started is True, (
        "啟動循環當下主視窗必須已是最小化狀態（最小化必須發生在啟動之前）"
    )
    assert win.isMinimized(), "啟動循環後主視窗應維持最小化"
    assert win._minimized_for_loop is True


def test_hybrid_start_leaves_tool_out_of_foreground(win, monkeypatch):
    """啟動循環當下工具視窗不得仍是前景（否則第一次循環仍被擋下）。"""
    _set_mode(win, monkeypatch, "hybrid")
    win._start_loop(group_ids=["g1"])

    assert win._init_worker.tool_was_foreground_when_started is False, (
        "啟動循環當下工具視窗不得是前景視窗，使用者不需再手動切換視窗"
    )


def test_hybrid_start_needs_no_manual_window_switch(win, monkeypatch):
    """完整走一次啟動：不需要使用者切換視窗，啟動流程自己把工具移出前景。"""
    _set_mode(win, monkeypatch, "hybrid")
    win._start_loop(group_ids=["g1"])
    win._init_worker.finished.emit(True, "")

    assert win._init_worker.started
    assert win._init_worker.minimized_when_started is True
    assert win._init_worker.tool_was_foreground_when_started is False


def test_minimize_waits_until_foreground_really_cleared(win, monkeypatch):
    """不可假設呼叫最小化後前景立即同步：必須輪詢確認確實離開前景。"""
    win.showNormal()
    calls = {"n": 0}

    def _still_foreground():
        calls["n"] += 1
        return calls["n"] <= 3  # 前三次視窗管理員還沒切走

    monkeypatch.setattr(win, "_is_foreground_window", _still_foreground)
    assert win._minimize_for_loop_start() is True
    assert calls["n"] > 3, "必須反覆確認前景狀態，不可呼叫 showMinimized 就當作完成"


def test_minimize_timeout_does_not_hang_gui(win, monkeypatch):
    """前景一直不讓步時不得卡住 GUI：逾時後仍以實際最小化狀態為準。"""
    monkeypatch.setattr(_gui, "_MINIMIZE_CONFIRM_TIMEOUT_SEC", 0.2)
    monkeypatch.setattr(win, "_is_foreground_window", lambda: True)
    assert win._minimize_for_loop_start() is True  # 已最小化
    assert win.isMinimized() is True


# ── 2. Hybrid Focus Guard 保留（情境 B） ───────────────────────────


def test_focus_guard_blocks_action_while_tool_in_foreground(monkeypatch):
    """工具在前景時，輸入動作仍必須被擋下（Focus Guard 不得被這次修正繞過）。"""
    ml = _make_ml()
    ml._tool_hwnd = 999
    ml._config_store = type(
        "FakeConfigStore", (), {"get": lambda self, key="interaction_mode": "hybrid"}
    )()
    orig = ctypes.windll.user32.GetForegroundWindow
    try:
        ctypes.windll.user32.GetForegroundWindow = lambda: 999  # 工具在前景
        assert _ml_mod.MainLoop._is_tool_foreground(ml) is True
    finally:
        ctypes.windll.user32.GetForegroundWindow = orig


def test_action_resumes_after_tool_leaves_foreground(monkeypatch):
    """使用者離開 GUI 後，既有恢復行為不得退化（下一幀即可繼續送出動作）。"""
    ml = _make_ml()
    ml._tool_hwnd = 999
    ml._config_store = type(
        "FakeConfigStore", (), {"get": lambda self, key="interaction_mode": "hybrid"}
    )()
    orig = ctypes.windll.user32.GetForegroundWindow
    try:
        ctypes.windll.user32.GetForegroundWindow = lambda: 1234  # 使用者已切離
        assert _ml_mod.MainLoop._is_tool_foreground(ml) is False
    finally:
        ctypes.windll.user32.GetForegroundWindow = orig


def test_frida_keeps_skipping_foreground_protection(monkeypatch):
    """frida 原本就跳過前景保護，本次修正不得改變這一點。"""
    ml = _make_ml()
    ml._tool_hwnd = 999
    ml._config_store = type(
        "FakeConfigStore", (), {"get": lambda self, key="interaction_mode": "frida"}
    )()
    orig = ctypes.windll.user32.GetForegroundWindow
    try:
        ctypes.windll.user32.GetForegroundWindow = lambda: 999
        assert _ml_mod.MainLoop._is_tool_foreground(ml) is False
    finally:
        ctypes.windll.user32.GetForegroundWindow = orig


# ── 3. 啟動失敗 ─────────────────────────────────────────────────────


def test_validation_failure_does_not_minimize(win, monkeypatch):
    """啟動前驗證失敗（沒有規則）→ 不得最小化視窗，也不得啟動 worker。"""
    _set_mode(win, monkeypatch, "hybrid")
    win._rules = []
    win._start_loop(group_ids=["g1"])

    assert win.isMinimized() is False, "驗證失敗時不得最小化視窗"
    assert win._minimized_for_loop is False
    assert getattr(win, "_init_worker", None) is None, "驗證失敗時不得啟動 InitWorker"


def test_user_cancels_group_selection_does_not_minimize(win, monkeypatch):
    """使用者在群組選擇對話框按取消 → 不得最小化視窗。"""
    _set_mode(win, monkeypatch, "hybrid")
    monkeypatch.setattr(win, "_show_group_selection_dialog", lambda: None)
    win._start_loop()

    assert win.isMinimized() is False, "使用者取消時不得最小化視窗"
    assert win._minimized_for_loop is False


def test_init_failure_restores_window(win, monkeypatch):
    """初始化失敗 → 主視窗必須還原（否則錯誤對話框跟著最小化，使用者找不到工具）。"""
    _set_mode(win, monkeypatch, "hybrid")
    win._start_loop(group_ids=["g1"])
    assert win.isMinimized() is True, "前置條件：啟動前已最小化"

    win._init_worker.finished.emit(False, "boom")

    assert win.isMinimized() is False, "初始化失敗必須把主視窗還原"
    assert win._minimized_for_loop is False
    assert win._btn_toggle.isEnabled(), "失敗後按鈕必須恢復可用"


def test_init_worker_start_exception_restores_window(win, monkeypatch):
    """連 InitWorker 都起不來 → 視窗必須還原，例外照原樣往外拋。"""
    _set_mode(win, monkeypatch, "hybrid")
    _FakeInitWorker.start_error = RuntimeError("boom")
    try:
        with pytest.raises(RuntimeError):
            win._start_loop(group_ids=["g1"])
    finally:
        _FakeInitWorker.start_error = None

    assert win.isMinimized() is False, "啟動例外必須把主視窗還原"
    assert win._minimized_for_loop is False


def test_successful_start_keeps_window_minimized(win, monkeypatch):
    """啟動成功 → 視窗維持最小化（使用者要用時可從匣／工作列還原）。"""
    _set_mode(win, monkeypatch, "hybrid")
    win._start_loop(group_ids=["g1"])
    win._init_worker.finished.emit(True, "")

    assert win.isMinimized() is True
    assert win._minimized_for_loop is True


# ── 4. 既有功能回歸：非 hybrid 不得改變行為 ─────────────────────────


def test_pynput_start_does_not_minimize(win, monkeypatch):
    """pynput：原本由 activate_window 把前景交給目標視窗，不得新增最小化。"""
    _set_mode(win, monkeypatch, "pynput")
    win._start_loop(group_ids=["g1"])

    assert win.isMinimized() is False, "pynput 不得最小化視窗"
    assert win._minimized_for_loop is False
    assert win._init_worker.started is True


def test_frida_start_does_not_minimize(win, monkeypatch):
    """frida：完全不依賴前景，啟動流程不得有最小化等額外行為。"""
    _set_mode(win, monkeypatch, "frida")
    win._start_loop(group_ids=["g1"])

    assert win.isMinimized() is False, "frida 不得最小化視窗"
    assert win._minimized_for_loop is False
    assert win._init_worker.started is True
