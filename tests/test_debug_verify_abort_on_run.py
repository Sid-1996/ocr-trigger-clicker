"""R-3：主循環啟動時，先前已啟動的 OCR Debug click／key 驗證 worker 必須中止。

缺陷（修正前）：``set_run_active(True)`` 只停用測試按鈕，先前已在背景執行緒
跑的驗證 worker 仍會繼續：click 驗證會繼續重拍畫面並 OCR（主循環會改變畫面，
結論必然是假的「沒有反應」），key 驗證更會直接送出按鍵，與主循環同時操作
後台輸入。

本檔驗證三層防線：
1. **作廢**：主循環啟動時，既有 generation id 讓在途結果失效，旗標歸零。
2. **自我中止閘**：worker 在「送出輸入前」再次確認主循環是否已啟動。
3. **不阻斷釋放**：DOWN 已送出後，必要的 UP 不受任何閘阻擋。

同時驗證 MainLoop 停止後 OCR Debug 的原有能力完全恢復。
"""

import threading

import numpy as np
import pytest
from test_bg_diag_reporting import _BG

from _loader import load_sibling
from i18n import T

_debug = load_sibling("ocr_debug", "gui/09_ocr_debug.py")

_ERR_RUN_ACTIVE = getattr(_debug, "_ERR_RUN_ACTIVE", "main loop running")


@pytest.fixture
def panel(qt_app):
    """獨立建立 OCR Debug 面板（offscreen，不依賴 MainWindow）。"""
    p = _debug.OcrDebugPanel("測試視窗")
    yield p
    p.deleteLater()


@pytest.fixture
def frida_mode(monkeypatch):
    """面板內的互動模式固定為 frida（避免讀到使用者真實設定檔）。"""
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")


def _result():
    """一個帶文字的 OCR 結果（供 _roi_patch 使用）。"""
    from _loader import load_sibling

    ocr_mod = load_sibling("ocr_engine", "core/02_ocr_engine.py")
    return ocr_mod.OcrResult(text="確定", x=0, y=0, w=10, h=10, confidence=0.9)


class _FakeBgInput:
    """假的後台輸入模組（記錄送出的按鍵）。"""

    def __init__(self, on_send=None, result=True):
        self.sent: list = []
        self._on_send = on_send
        self._result = result

    def set_method(self, mode: str) -> None:
        self.mode = mode

    def send_key(self, hwnd, key):
        self.sent.append((hwnd, key))
        if self._on_send is not None:
            self._on_send()
        return self._result

    def last_error(self) -> str:
        return ""


def _collect(panel) -> list[dict]:
    """收集 worker 送出的結果（signal 在同執行緒 → direct 連線 → 立即收到）。"""
    got: list[dict] = []
    panel._signals.click_verify_done.connect(lambda d: got.append(d))
    panel._signals.key_verify_done.connect(lambda d: got.append(d))
    return got


# ── 1. 作廢在途驗證（主循環啟動） ───────────────────────────────────


def test_run_active_aborts_inflight_click_verify(panel):
    """主循環啟動 → 在途的 click 驗證旗標必須歸零、按鈕不得卡在「驗證中」。"""
    panel._verif_in_progress = True
    panel._click_test_available = False
    panel._click_test_btn.setText(T("ocr_debug.verifying"))

    panel.set_run_active(True)

    assert panel._verif_in_progress is False, "在途驗證必須被作廢"
    assert panel._click_test_btn.text() == T("ocr_debug.click_test"), "按鈕文字必須復原"


def test_run_active_aborts_inflight_key_verify(panel):
    """主循環啟動 → 在途的 key 驗證旗標必須歸零。"""
    panel._key_verif_in_progress = True
    panel._key_test_available = False
    panel._key_test_btn.setText(T("ocr_debug.key_test.verifying"))

    panel.set_run_active(True)

    assert panel._key_verif_in_progress is False, "在途驗證必須被作廢"
    assert panel._key_test_btn.text() == T("ocr_debug.key_test"), "按鈕文字必須復原"


def test_run_active_bumps_generation_ids(panel):
    """作廢必須靠 generation id 讓在途結果失效（否則舊結果會覆蓋新狀態）。"""
    before_click = panel._click_verify_request_id
    before_key = panel._key_verify_request_id
    panel.set_run_active(True)
    assert panel._click_verify_request_id > before_click
    assert panel._key_verify_request_id > before_key


def test_stale_worker_result_is_ignored_after_abort(panel):
    """作廢後回來的舊結果不得覆蓋面板狀態（不得解鎖按鈕）。"""
    panel._verif_in_progress = True
    panel.set_run_active(True)
    stale_id = panel._click_verify_request_id - 1

    panel._on_click_verify_done(
        {
            "state": "success",
            "text": "確定",
            "sx": 1,
            "sy": 1,
            "ms": 0.0,
            "still": "no",
            "last_error": "",
            "request_id": stale_id,
        }
    )

    assert panel._verif_in_progress is False, "過期結果不得改變作廢後的狀態"
    assert not panel._click_test_btn.isEnabled(), "循環執行中按鈕不得被舊結果解鎖"


def test_repeated_run_active_does_not_double_bump(panel):
    """重複啟動不得重複作廢（否則在途結果的 id 會被多跳一次）。"""
    panel.set_run_active(True)
    after_first = panel._click_verify_request_id
    panel.set_run_active(True)
    assert panel._click_verify_request_id == after_first, "重複啟動不得再次作廢"


def test_run_stop_restores_buttons(panel):
    """主循環停止 → 按鈕與面板狀態必須完全復原（OCR Debug 原有能力保留）。"""
    panel.set_run_active(True)
    assert not panel._key_test_btn.isEnabled()
    panel.set_run_active(False)
    assert panel._key_test_btn.isEnabled(), "循環停止後按鍵測試必須恢復"
    assert panel._run_active.is_set() is False


# ── 2. worker 自我中止閘（尚未送出輸入） ────────────────────────────


def test_click_worker_stops_when_run_started(panel, frida_mode, monkeypatch):
    """主循環已啟動 → click 驗證 worker 不得再擷取畫面。"""
    captured: list = []
    monkeypatch.setattr(
        _debug, "capture_frame", lambda *a, **k: captured.append(1) or np.zeros((10, 10, 3))
    )
    got = _collect(panel)
    panel.set_run_active(True)

    panel._click_verify_worker(_result(), 5, 5, 10, 10, panel._click_verify_request_id)

    assert captured == [], "主循環執行中不得再擷取畫面"
    assert got, "worker 必須回報完成（否則按鈕會卡在「驗證中」）"
    assert got[0]["state"] == "skipped"
    assert got[0]["last_error"] == _ERR_RUN_ACTIVE


def test_key_worker_stops_when_run_started(panel, frida_mode, monkeypatch):
    """主循環已啟動 → key 驗證 worker 不得送出按鍵。"""
    fake = _FakeBgInput()
    monkeypatch.setattr(_debug, "_bg_input", fake)
    got = _collect(panel)
    panel.set_run_active(True)

    panel._key_verify_worker(1234, "space", panel._key_verify_request_id)

    assert fake.sent == [], "主循環執行中不得送出按鍵"
    assert got and got[0]["state"] == "fail"
    assert got[0]["err"] == _ERR_RUN_ACTIVE


def test_key_worker_stops_when_run_started_during_capture(panel, frida_mode, monkeypatch):
    """擷取畫面期間主循環啟動 → 送出輸入前仍必須中止。"""
    img = np.full((10, 10, 3), 30, dtype=np.uint8)

    def _capture(*a, **k):
        panel.set_run_active(True)  # 模擬擷取期間主循環啟動
        return img

    fake = _FakeBgInput()
    monkeypatch.setattr(_debug, "capture_frame", _capture)
    monkeypatch.setattr(_debug, "_bg_input", fake)
    got = _collect(panel)

    panel._key_verify_worker(1234, "space", panel._key_verify_request_id)

    assert fake.sent == [], "擷取期間主循環啟動 → 不得送出按鍵"
    assert got and got[0]["state"] == "fail"
    assert got[0]["err"] == _ERR_RUN_ACTIVE


def test_run_active_failure_does_not_open_service_dialog(panel):
    """因主循環啟動而中止不得觸發「診斷＋行動」服務對話框（不是注入失敗）。"""
    triggered: list = []
    panel.bg_inject_fail.connect(lambda: triggered.append(1))

    panel._show_key_verify({"state": "fail", "err": _ERR_RUN_ACTIVE, "key": "space"})
    assert triggered == [], "主循環中止不得觸發服務對話框"

    panel._show_key_verify({"state": "fail", "err": "真的注入失敗", "key": "space"})
    assert triggered == [1], "真正的失敗仍必須觸發服務對話框"


# ── 3. 已開始輸入時不得阻斷必要釋放 ─────────────────────────────────


def test_key_worker_input_is_not_interrupted_once_started(panel, frida_mode, monkeypatch):
    """送出輸入的瞬間主循環啟動 → 這次輸入仍完整送出（不得半途攔截）。"""
    img = np.full((10, 10, 3), 30, dtype=np.uint8)
    fake = _FakeBgInput(on_send=lambda: panel.set_run_active(True))
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **k: img)
    monkeypatch.setattr(_debug, "_bg_input", fake)
    got = _collect(panel)

    panel._key_verify_worker(1234, "space", panel._key_verify_request_id)

    assert fake.sent == [(1234, "space")], "已開始的輸入必須完整送出一次"
    assert got and got[0]["state"] != "fail", "已送出的輸入不得被回報成失敗"


def test_release_is_not_blocked_when_run_starts_mid_press(panel, bg_env, monkeypatch):
    """後端層：DOWN 已送出後主循環啟動 → 必要的 UP 仍必須送出。

    這是輸入安全的不變量：任何閘都不得讓按鍵卡在遊戲裡。
    """

    class _HookUser32:
        def __init__(self):
            self.sent = []

        def PostMessageW(self, hwnd, msg, wparam, lparam):
            self.sent.append(msg)
            if msg == _BG.WM_KEYDOWN:
                panel.set_run_active(True)  # 按下之後主循環啟動
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
    assert _BG.WM_KEYUP in fake.sent, "主循環啟動不得阻斷必要的放開"


# ── 4. 完成／例外後不得留下錯誤的執行中狀態 ─────────────────────────


def test_key_worker_exception_clears_in_progress(panel, frida_mode, monkeypatch):
    """worker 例外 → 旗標必須歸零（不得卡在「驗證中」）。"""

    def _boom(*a, **k):
        raise RuntimeError("capture failed")

    monkeypatch.setattr(_debug, "capture_frame", _boom)
    panel._key_verif_in_progress = True
    panel._key_verify_request_id += 1

    panel._key_verify_worker(1234, "space", panel._key_verify_request_id)

    assert panel._key_verif_in_progress is False, "例外後不得留下執行中狀態"


def test_click_worker_completion_clears_in_progress(panel, frida_mode, monkeypatch):
    """worker 正常完成 → 旗標歸零、按鈕文字復原。"""
    img = np.full((10, 10, 3), 30, dtype=np.uint8)
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **k: img)
    monkeypatch.setattr(_debug, "recognize", lambda *a, **k: [])
    panel._verif_in_progress = True
    panel._click_test_available = False
    panel._click_verify_request_id += 1

    panel._click_verify_worker(_result(), 5, 5, 10, 10, panel._click_verify_request_id)

    assert panel._verif_in_progress is False, "完成後不得留下執行中狀態"
    assert panel._click_test_btn.text() == T("ocr_debug.click_test")


def test_verify_can_start_again_after_run_stopped(panel, monkeypatch):
    """循環停止後可以再次啟動驗證（不得被作廢狀態卡住）。"""
    started: list = []

    class _FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            self.target = target

        def start(self):
            started.append(self.target)

    class _FakeThreading:
        Thread = _FakeThread
        Event = threading.Event

    monkeypatch.setattr(_debug, "threading", _FakeThreading)

    panel._key_verif_in_progress = True
    panel.set_run_active(True)
    assert panel._key_verif_in_progress is False, "啟動循環時在途驗證必須被作廢"

    panel.set_run_active(False)
    panel._start_key_verify(1234, "space")

    assert started, "循環停止後必須能再次啟動驗證"
    assert panel._key_verif_in_progress is True


# ── 5. 主視窗層：循環啟動會作廢在途驗證 ─────────────────────────────


def test_mainwindow_update_edit_enabled_aborts_inflight_verify(real_mainwindow):
    """``_update_edit_enabled(False)``（循環執行中）→ 在途驗證必須被作廢。"""
    win = real_mainwindow
    panel = win._debug_panel
    assert panel is not None

    panel._verif_in_progress = True
    panel._key_verif_in_progress = True

    win._update_edit_enabled(False)

    assert panel._verif_in_progress is False
    assert panel._key_verif_in_progress is False

    win._update_edit_enabled(True)
    assert panel._key_test_btn.isEnabled(), "循環停止後按鍵測試必須恢復"
