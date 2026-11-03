"""R-5：MainLoop 真正開始執行前，必須先關上 OCR Debug 的執行中閘門。

競態來源（``gui/06_gui_main.py``）::

    InitWorker.run()      loop.start()        ← MainLoop 執行緒開始跑（:4770）
                          finished.emit(...)  ← queued signal（:4772）
    GUI thread            _on_init_finished() → _update_edit_enabled(False)
                                              → panel.set_run_active(True)

``loop.start()`` 與 GUI 收到 ``finished`` 之間存在窗口：MainLoop 已經在跑，
OCR Debug 卻仍以為沒在跑 → 先前的 key 驗證 worker 會在該窗口內送出一次按鍵，
與主循環重疊操作後台輸入。

修正：啟動 InitWorker 之前先 ``set_run_active(True)``；啟動失敗時恢復。
本檔以真實 MainWindow＋假 InitWorker 驅動實際啟動流程，驗證呼叫順序。
"""

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from _loader import load_sibling

_gui = load_sibling("gui_main", "gui/06_gui_main.py")
_debug = load_sibling("ocr_debug", "gui/09_ocr_debug.py")
_BG = load_sibling("bg_input", "core/16_bg_input.py")
_rule_models = load_sibling("rule_models", "core/rule_models.py")


class _FakeLoop:
    """假的 MainLoop（只提供 GUI 啟動／停止流程會碰到的成員）。"""

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
    """假的 InitWorker：記錄「啟動當下」OCR Debug 的閘門狀態。"""

    finished = pyqtSignal(bool, str)

    window = None  # 由 fixture 指向被測主視窗

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.loop = _FakeLoop()
        self.started = False
        self.gate_when_started = None

    def start(self):
        self.started = True
        panel = getattr(type(self).window, "_debug_panel", None)
        if panel is not None:
            self.gate_when_started = panel._run_active.is_set()


class _FakeBgInput:
    """假的後台輸入模組（記錄送出的按鍵）。"""

    def __init__(self):
        self.sent: list = []

    def set_method(self, mode: str) -> None:
        self.mode = mode

    def send_key(self, hwnd, key):
        self.sent.append((hwnd, key))
        return True

    def last_error(self) -> str:
        return ""


@pytest.fixture
def win(real_mainwindow, monkeypatch):
    """可直接呼叫 _start_loop() 的真實主視窗（InitWorker 以假物件取代）。"""
    window = real_mainwindow
    panel = window._debug_panel
    assert panel is not None

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(_gui, "activate_window", lambda title: True)
    monkeypatch.setattr(_gui, "activate_window_bg", lambda title: True)
    monkeypatch.setattr(
        window, "_window_combo", type("_Combo", (), {"currentText": lambda self: "測試視窗"})()
    )
    monkeypatch.setattr(window, "_is_bg_mode", lambda: False)
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
    monkeypatch.setattr(_gui, "InitWorker", _FakeInitWorker)
    try:
        yield window
    finally:
        _FakeInitWorker.window = None
        timer = getattr(window, "_exec_log_timer", None)
        if timer is not None:
            timer.stop()


# ── 1. 啟動前閘門必須已關 ───────────────────────────────────────────


def test_debug_gate_closed_before_init_worker_starts(win):
    """MainLoop 開始執行前，OCR Debug 的閘門必須已經關上。

    這是 R-5 的核心：閘門若在 ``loop.start()`` 之後才關，兩者之間的窗口內
    先前的驗證 worker 仍會送出按鍵。
    """
    win._start_loop(group_ids=["g1"])

    assert win._init_worker.started, "前置條件：InitWorker 應已啟動"
    assert win._init_worker.gate_when_started is True, (
        "啟動 InitWorker 前必須先關上 OCR Debug 的執行中閘門"
    )


def test_debug_worker_blocked_without_waiting_for_finished(win, monkeypatch):
    """不必等 InitWorker.finished，Debug worker 就已經無法送出輸入。"""
    win._start_loop(group_ids=["g1"])

    panel = win._debug_panel
    assert panel._verify_input_blocked() is True, "閘門必須在 finished 之前就生效"

    fake_bg = _FakeBgInput()
    monkeypatch.setattr(_debug, "_bg_input", fake_bg)
    panel._key_verify_worker(1234, "space", panel._key_verify_request_id)

    assert fake_bg.sent == [], "MainLoop 啟動流程尚未完成時，Debug worker 不得送出按鍵"


def test_debug_buttons_disabled_during_startup(win):
    """啟動流程進行中，Debug 的輸入測試按鈕必須停用。"""
    win._start_loop(group_ids=["g1"])

    panel = win._debug_panel
    assert not panel._key_test_btn.isEnabled()
    assert not panel._click_test_btn.isEnabled()


# ── 2. 啟動成功 ─────────────────────────────────────────────────────


def test_debug_stays_disabled_after_successful_start(win):
    """MainLoop 啟動成功後，Debug 必須維持停用。"""
    win._start_loop(group_ids=["g1"])
    win._init_worker.finished.emit(True, "")

    panel = win._debug_panel
    assert panel._run_active.is_set()
    assert not panel._key_test_btn.isEnabled()


def test_debug_gate_not_aborted_twice_for_same_start(win):
    """不得重複作廢同一批在途 worker（啟動前 + 啟動成功各呼叫一次）。"""
    panel = win._debug_panel
    before = panel._click_verify_request_id

    win._start_loop(group_ids=["g1"])
    after_start = panel._click_verify_request_id
    assert after_start == before + 1, "啟動前應作廢一次"

    win._init_worker.finished.emit(True, "")
    assert panel._click_verify_request_id == after_start, "啟動成功不得再次作廢"


# ── 3. 啟動失敗 ─────────────────────────────────────────────────────


def test_debug_restored_after_failed_start(win):
    """MainLoop 啟動失敗 → Debug 的閘門與按鈕必須恢復。"""
    win._start_loop(group_ids=["g1"])
    panel = win._debug_panel
    assert panel._run_active.is_set(), "前置條件：啟動前閘門已關"

    win._init_worker.finished.emit(False, "boom")

    assert panel._run_active.is_set() is False, "啟動失敗必須恢復 Debug 的閘門"
    assert panel._key_test_btn.isEnabled(), "啟動失敗後按鍵測試必須恢復可用"


def test_failed_start_does_not_leave_inflight_verify(win):
    """啟動失敗後不得留下「驗證中」的卡死狀態。

    情境：啟動前有一個在途的 click 驗證 → 啟動時被作廢 → 啟動失敗後閘門恢復，
    按鈕不得仍卡在「驗證中」。
    """
    panel = win._debug_panel
    panel._verif_in_progress = True
    panel._click_test_available = False
    panel._click_test_btn.setText("驗證中")

    win._start_loop(group_ids=["g1"])
    assert panel._verif_in_progress is False, "啟動時應作廢在途驗證"

    win._init_worker.finished.emit(False, "boom")

    assert panel._verif_in_progress is False
    assert panel._click_test_btn.text() != "驗證中"
    assert panel._key_test_btn.isEnabled()


def test_debug_restored_when_init_worker_cannot_start(win, monkeypatch):
    """連 InitWorker 執行緒都起不來 → Debug 的閘門也必須恢復。"""

    def _boom(self):
        raise RuntimeError("cannot start thread")

    monkeypatch.setattr(_FakeInitWorker, "start", _boom)
    panel = win._debug_panel

    with pytest.raises(RuntimeError):
        win._start_loop(group_ids=["g1"])

    assert panel._run_active.is_set() is False, "啟動失敗必須恢復 Debug 的閘門"
    assert panel._key_test_btn.isEnabled()


# ── 4. 停止 ─────────────────────────────────────────────────────────


def test_debug_restored_after_stop(win):
    """MainLoop 停止後，Debug 必須恢復可用。"""
    win._start_loop(group_ids=["g1"])
    win._init_worker.finished.emit(True, "")

    win._stop_loop()

    panel = win._debug_panel
    assert panel._run_active.is_set() is False
    assert panel._key_test_btn.isEnabled()


def test_repeated_start_stop_keeps_state_consistent(win):
    """重複啟動／停止不得造成狀態錯亂。"""
    panel = win._debug_panel
    for _ in range(2):
        win._start_loop(group_ids=["g1"])
        assert panel._run_active.is_set(), "啟動中閘門必須關閉"
        win._init_worker.finished.emit(True, "")
        assert panel._run_active.is_set(), "啟動成功後閘門必須維持關閉"
        win._stop_loop()
        assert panel._run_active.is_set() is False, "停止後閘門必須恢復"
        assert panel._key_test_btn.isEnabled()


# ── 5. Release 安全 ─────────────────────────────────────────────────


def test_release_not_blocked_when_gate_closes_mid_press(win, bg_env, monkeypatch):
    """DOWN 已送出後閘門關上 → 必要的 UP 仍必須送出（輸入安全不變量）。"""

    class _HookUser32:
        def __init__(self):
            self.sent = []

        def PostMessageW(self, hwnd, msg, wparam, lparam):
            self.sent.append(msg)
            if msg == _BG.WM_KEYDOWN:
                win._debug_panel.set_run_active(True)  # 按下之後閘門關上
            return 1

        def ClientToScreen(self, hwnd, point):
            return None

        def GetAsyncKeyState(self, vk):
            return 0

        def MapVirtualKeyW(self, vk, mode):
            return vk

    fake = _HookUser32()
    monkeypatch.setattr(_BG, "user32", fake)

    assert _BG.send_key(1, "a") is True, "DOWN+UP 都成功 → 整體成功"
    assert _BG.WM_KEYDOWN in fake.sent
    assert _BG.WM_KEYUP in fake.sent, "閘門關閉不得阻斷必要的放開"
