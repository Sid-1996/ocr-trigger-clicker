"""OCR Debug 面板非同步任務安全（Phase 3）回歸測試。

涵蓋範圍：
- clear_results() 必須使三種背景任務（OCR／Click Verify／Key Verify）全部失效，
  舊結果不得回填、舊錯誤不得覆蓋新狀態。
- Worker 不得直接操作 QWidget；成功與失敗都必須經 signal 回 GUI thread。
- Verify worker 的每一條完成路徑都必須 emit，不得靜默早退（否則按鈕永久卡在「驗證中」）。
- 過期任務不得解鎖新任務的按鈕、不得覆蓋新任務狀態、不得觸發 bg_inject_fail。

測試策略：真實 QWidget（QT_QPA_PLATFORM=offscreen）+ 可控制的假 signal 通道。
worker 測試時把 panel._signals 換成記錄器，slot 不會被觸發，
因此可直接觀察 worker 本身是否碰過 widget。不依賴真實遊戲視窗或 OCR 引擎。
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402
from i18n import T  # noqa: E402

_mod = load_sibling("ocr_debug", "gui/09_ocr_debug.py")
OcrDebugPanel = _mod.OcrDebugPanel


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def panel(qapp):
    p = OcrDebugPanel("", None)
    yield p
    p.deleteLater()
    qapp.processEvents()


class _Sig:
    """最小 signal 替身：只記錄 emit 呼叫，不觸發任何 slot。"""

    def __init__(self, sink):
        self._sink = sink

    def emit(self, *args):
        self._sink.append(args)


def _fake_signals():
    """假 signal 通道：記錄 worker 的所有 emit，不觸發任何 slot。"""
    rec = SimpleNamespace(status=[], done=[], failed=[], click=[], key=[])
    rec.ocr_status = _Sig(rec.status)
    rec.ocr_done = _Sig(rec.done)
    rec.ocr_failed = _Sig(rec.failed)
    rec.click_verify_done = _Sig(rec.click)
    rec.key_verify_done = _Sig(rec.key)
    return rec


def _ocr_result(text="確定", x=1, y=2, w=3, h=4, confidence=0.9):
    return SimpleNamespace(text=text, x=x, y=y, w=w, h=h, confidence=confidence)


def _image():
    return np.zeros((4, 4, 3), dtype=np.uint8)


def _click_payload(request_id, state="success"):
    return {
        "state": state,
        "text": "確定",
        "sx": 10,
        "sy": 20,
        "ms": 1.0,
        "still": "no",
        "last_error": "",
        "request_id": request_id,
    }


def _key_payload(request_id, state="success"):
    return {
        "state": state,
        "similar": 10.0,
        "err": "",
        "ms": 1.0,
        "key": "space",
        "request_id": request_id,
    }


# ── 1. clear_results() 使在途 OCR 結果失效 ───────────────────────────────────


def test_clear_results_invalidates_inflight_ocr_result(panel):
    panel._ocr_request_id = 5
    panel.clear_results()
    assert panel._ocr_request_id == 6

    # 舊 worker（request_id=5）完成 → 不得回填結果與表格
    panel._on_ocr_done([_ocr_result("舊視窗文字")], 12.0, 5)
    assert panel._ocr_results == []
    assert panel._result_table.rowCount() == 0


def test_clear_results_invalidates_inflight_ocr_failure(panel):
    panel._ocr_request_id = 5
    panel.clear_results()
    before = panel._status_bar.currentMessage()
    panel._on_ocr_failed("boom", 5)
    assert panel._status_bar.currentMessage() == before


def test_stale_ocr_failure_does_not_restore_new_task_button(panel):
    panel._ocr_request_id = 5
    panel.clear_results()
    # 新任務進行中：擷取按鈕停用
    panel._capture_btn.setEnabled(False)
    panel._capture_btn.setText("辨識中…")

    panel._on_ocr_failed("boom", 5)

    assert panel._capture_btn.isEnabled() is False, "過期任務不得復原新任務的按鈕"
    assert panel._capture_btn.text() == "辨識中…"


def test_stale_ocr_success_does_not_restore_new_task_button(panel):
    panel._ocr_request_id = 5
    panel.clear_results()
    panel._capture_btn.setEnabled(False)
    panel._capture_btn.setText("辨識中…")

    panel._on_ocr_done([_ocr_result()], 1.0, 5)

    assert panel._capture_btn.isEnabled() is False
    assert panel._capture_btn.text() == "辨識中…"


# ── 2. Worker 不得直接操作 QWidget ────────────────────────────────────────────


def test_ocr_worker_failure_does_not_touch_widgets(panel, monkeypatch):
    rec = _fake_signals()
    panel._signals = rec
    before_text = panel._capture_btn.text()
    before_enabled = panel._capture_btn.isEnabled()

    def _boom(*_a, **_k):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(_mod, "recognize", _boom)
    panel._do_ocr(_image(), 1)

    assert rec.failed, "Worker 失敗必須以 signal 回報"
    assert rec.failed[0][1] == 1, "失敗訊息必須帶 request id"
    assert panel._capture_btn.text() == before_text, "Worker 不得直接操作 QWidget"
    assert panel._capture_btn.isEnabled() == before_enabled, "Worker 不得直接操作 QWidget"


def test_ocr_worker_success_reports_via_signal(panel, monkeypatch):
    rec = _fake_signals()
    panel._signals = rec
    monkeypatch.setattr(_mod, "recognize", lambda img, **kw: [_ocr_result()])

    panel._do_ocr(_image(), 3)

    assert rec.done and rec.done[0][2] == 3
    assert not rec.failed


def test_ocr_worker_failure_message_has_no_traceback(panel, monkeypatch):
    rec = _fake_signals()
    panel._signals = rec

    def _boom(*_a, **_k):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(_mod, "recognize", _boom)
    panel._do_ocr(_image(), 1)

    msg = rec.failed[0][0]
    assert "Traceback" not in msg
    assert "engine exploded" in msg


# ── 3. 按鈕狀態：擷取失敗 / Worker 啟動失敗 ────────────────────────────────────


def test_capture_failure_restores_button(panel, monkeypatch):
    monkeypatch.setattr(panel, "_minimize_and_capture", lambda: (None, ""))
    panel._take_snapshot()
    assert panel._capture_btn.isEnabled() is True
    assert panel._capture_btn.text() == T("ocr_debug.capture")


def test_worker_start_failure_restores_button(panel, monkeypatch):
    monkeypatch.setattr(panel, "_minimize_and_capture", lambda: (_image(), "src"))

    class _BoomThread:
        def __init__(self, *_a, **_k):
            pass

        def start(self):
            raise RuntimeError("cannot start thread")

    monkeypatch.setattr(_mod.threading, "Thread", _BoomThread)
    panel._take_snapshot()

    assert panel._capture_btn.isEnabled() is True
    assert panel._capture_btn.text() == T("ocr_debug.capture")


# ── 4. Verify worker 的所有完成路徑都必須 emit ───────────────────────────────


def test_click_verify_worker_emits_on_early_return(panel, monkeypatch):
    rec = _fake_signals()
    panel._signals = rec
    monkeypatch.setattr(_mod.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_mod, "_get_interaction_mode", lambda: "pynput")

    panel._click_verify_worker(_ocr_result(), 10, 20, 100, 100, 1)

    assert rec.click, "早退路徑必須發出完成訊號，否則按鈕會永久卡在「驗證中」"
    assert rec.click[0][0]["request_id"] == 1


def test_click_verify_worker_emits_when_window_gone(panel, monkeypatch):
    rec = _fake_signals()
    panel._signals = rec
    monkeypatch.setattr(_mod.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_mod, "_get_interaction_mode", lambda: "frida")
    monkeypatch.setattr(_mod._screenshot, "get_window_hwnd", lambda *_a, **_k: None, raising=False)

    panel._click_verify_worker(_ocr_result(), 10, 20, 100, 100, 1)

    assert rec.click, "目標視窗消失也必須發出完成訊號"
    assert rec.click[0][0]["request_id"] == 1


def test_key_verify_worker_emits_on_mode_switch(panel, monkeypatch):
    rec = _fake_signals()
    panel._signals = rec
    monkeypatch.setattr(_mod.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_mod, "_get_interaction_mode", lambda: "pynput")

    panel._key_verify_worker(123, "space", 1)

    assert rec.key, "模式改變必須發出完成訊號"
    assert rec.key[0][0]["request_id"] == 1


def test_key_verify_worker_emits_on_exception(panel, monkeypatch):
    rec = _fake_signals()
    panel._signals = rec
    monkeypatch.setattr(_mod.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_mod, "_get_interaction_mode", lambda: "frida")

    def _boom(*_a, **_k):
        raise RuntimeError("capture failed")

    monkeypatch.setattr(_mod, "capture_frame", _boom)
    panel._key_verify_worker(123, "space", 1)

    assert rec.key, "Worker 內部例外也必須發出完成訊號"
    assert rec.key[0][0]["state"] == "fail"
    assert rec.key[0][0]["request_id"] == 1


# ── 5. 過期 Verify 不得干擾新任務 ─────────────────────────────────────────────


def test_stale_click_verify_does_not_unlock_new_verify(panel):
    # A 啟動（id=1）
    panel._click_verify_request_id = 1
    panel._verif_in_progress = True
    panel._click_test_btn.setEnabled(False)
    panel._click_test_btn.setText(T("ocr_debug.verifying"))
    # A 失效、B 啟動（id=2）
    panel._click_verify_request_id = 2
    panel._verif_in_progress = True
    panel._click_test_btn.setEnabled(False)

    # A 最後才完成 → 必須被忽略
    panel._on_click_verify_done(_click_payload(1))

    assert panel._verif_in_progress is True, "過期任務不得把新任務的 in-progress 清掉"
    assert panel._click_test_btn.isEnabled() is False, "過期任務不得解鎖新任務的按鈕"


def test_stale_key_verify_does_not_unlock_new_verify(panel):
    panel._key_verify_request_id = 1
    panel._key_verif_in_progress = True
    panel._key_test_btn.setEnabled(False)
    panel._key_verify_request_id = 2
    panel._key_verif_in_progress = True
    panel._key_test_btn.setEnabled(False)

    panel._on_key_verify_done(_key_payload(1))

    assert panel._key_verif_in_progress is True
    assert panel._key_test_btn.isEnabled() is False


def test_stale_click_verify_does_not_emit_bg_inject_fail(panel):
    fired = []
    panel.bg_inject_fail.connect(lambda: fired.append(True))
    panel._click_verify_request_id = 2

    panel._on_click_verify_done(_click_payload(1, state="no_response"))

    assert fired == [], "過期任務不得觸發背景注入錯誤訊號"


def test_stale_key_verify_does_not_emit_bg_inject_fail(panel):
    fired = []
    panel.bg_inject_fail.connect(lambda: fired.append(True))
    panel._key_verify_request_id = 2

    panel._on_key_verify_done(_key_payload(1, state="no_change"))

    assert fired == [], "過期任務不得觸發背景注入錯誤訊號"


# ── 6. clear_results() 清除所有依賴舊結果的狀態 ───────────────────────────────


def test_clear_results_clears_all_result_dependent_state(panel):
    panel._ocr_request_id = 1
    panel._on_ocr_done([_ocr_result("文字")], 10.0, 1)
    assert panel._result_table.rowCount() == 1

    panel._capture_source = "螢幕"
    panel._add_rule_btn.setEnabled(True)
    panel._template_btn.setEnabled(True)
    panel._click_test_btn.setEnabled(True)

    panel.clear_results()

    assert panel._ocr_results == []
    assert panel._latest_raw is None
    assert panel._capture_source == ""
    assert panel._selected_index == -1
    assert panel._result_table.rowCount() == 0
    assert panel._add_rule_btn.isEnabled() is False
    assert panel._template_btn.isEnabled() is False
    assert panel._click_test_btn.isEnabled() is False
    assert panel._info_label.text() == ""


def test_clear_results_resets_verify_in_progress(panel):
    panel._verif_in_progress = True
    panel._key_verif_in_progress = True
    panel._click_test_btn.setEnabled(False)
    panel._click_test_btn.setText(T("ocr_debug.verifying"))
    panel._key_test_btn.setEnabled(False)
    panel._key_test_btn.setText(T("ocr_debug.key_test.verifying"))

    panel.clear_results()

    assert panel._verif_in_progress is False
    assert panel._key_verif_in_progress is False
    assert panel._key_test_btn.isEnabled() is True, "鍵盤測試按鈕不得永久卡住"
    assert panel._key_test_btn.text() == T("ocr_debug.key_test")


def test_generation_ids_are_independent(panel):
    panel._ocr_request_id = 1
    panel._click_verify_request_id = 2
    panel._key_verify_request_id = 3

    panel.clear_results()

    assert panel._ocr_request_id == 2
    assert panel._click_verify_request_id == 3
    assert panel._key_verify_request_id == 4


def test_ocr_busy_flag_is_removed(panel):
    assert not hasattr(panel, "_ocr_busy"), "_ocr_busy 是沒有讀取點的死旗標，應已移除"


# ── 7. 擷取按鈕不得永久卡死 ──────────────────────────────────────────────────


class _NoThread:
    """不啟動任何執行緒的 Thread 替身。"""

    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


def test_new_capture_clears_previous_results(panel, monkeypatch):
    panel._ocr_request_id = 1
    panel._on_ocr_done([_ocr_result("舊視窗文字")], 10.0, 1)
    assert panel._result_table.rowCount() == 1
    panel._selected_index = 0
    panel._click_test_btn.setEnabled(True)

    monkeypatch.setattr(panel, "_minimize_and_capture", lambda: (_image(), "src"))
    monkeypatch.setattr(_mod.threading, "Thread", _NoThread)
    panel._take_snapshot()

    # 舊結果必須被清掉：舊座標配上新視窗 rect 會點錯位置
    assert panel._ocr_results == []
    assert panel._result_table.rowCount() == 0
    assert panel._click_test_btn.isEnabled() is False


def test_current_ocr_failure_restores_capture_button(panel):
    panel._ocr_request_id = 7
    panel._capture_btn.setEnabled(False)
    panel._capture_btn.setText(T("ocr_debug.recognizing"))

    panel._on_ocr_failed("boom", 7)

    assert panel._capture_btn.isEnabled() is True
    assert panel._capture_btn.text() == T("ocr_debug.capture")
    assert "boom" in panel._status_bar.currentMessage()


def test_clear_results_restores_capture_button(panel):
    panel._capture_btn.setEnabled(False)
    panel._capture_btn.setText(T("ocr_debug.recognizing"))

    panel.clear_results()

    assert panel._capture_btn.isEnabled() is True
    assert panel._capture_btn.text() == T("ocr_debug.capture")


# ── 8. 驗證進行中不得提前解鎖 ────────────────────────────────────────────────


def test_selection_change_does_not_unlock_click_test_during_verify(panel):
    panel._ocr_request_id = 1
    panel._on_ocr_done([_ocr_result("文字")], 10.0, 1)
    assert panel._result_table.rowCount() == 1

    # 驗證進行中
    panel._verif_in_progress = True
    panel._click_test_btn.setEnabled(False)
    panel._click_test_btn.setText(T("ocr_debug.verifying"))

    panel._result_table.selectRow(0)

    assert panel._click_test_btn.isEnabled() is False, "驗證進行中不得提前解鎖"
    assert panel._click_test_btn.text() == T("ocr_debug.verifying")
