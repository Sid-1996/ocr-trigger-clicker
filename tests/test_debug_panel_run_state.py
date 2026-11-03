"""C-5：主循環執行期間停用 OCR Debug 的輸入測試按鈕。

輸入測試（點擊／按鍵）會直接操作後台輸入（frida 模式），與執行中的主循環
共用同一組後端狀態 → 循環執行期間必須停用，否則兩邊會同時送輸入互相干擾。

驗證三件事：
1. 面板層：``set_run_active(True)`` 停用兩個測試按鈕；解除後依面板自身狀態還原。
2. 面板層：面板自己的啟用邏輯（選取結果）不被 ``set_run_active`` 覆蓋。
3. 主視窗層：``_update_edit_enabled(False)``（＝循環執行中）會停用測試按鈕，
   ``_update_edit_enabled(True)``（＝循環停止）會還原。
"""

import pytest

from _loader import load_sibling

_ocr_mod = load_sibling("ocr_engine", "core/02_ocr_engine.py")
OcrResult = _ocr_mod.OcrResult


@pytest.fixture
def panel(qt_app):
    """獨立建立 OCR Debug 面板（offscreen，不依賴 MainWindow）。"""
    _debug = load_sibling("ocr_debug", "gui/09_ocr_debug.py")
    p = _debug.OcrDebugPanel("測試視窗")
    yield p
    p.deleteLater()


def _select_first_row(p) -> None:
    """模擬使用者選取 OCR 結果表格的第一列（面板的選取流程）。"""
    p._ocr_results = [OcrResult(text="確定", x=0, y=0, w=10, h=10, confidence=0.9)]
    p._result_table.setRowCount(1)
    p._result_table.selectRow(0)
    p._on_table_selection_changed()


# ── 1. 面板層：循環執行中停用 ───────────────────────────────────────


def test_run_active_disables_both_test_buttons(panel):
    """循環執行中 → 點擊測試與按鍵測試都必須停用。"""
    assert panel._key_test_btn.isEnabled(), "前置條件：按鍵測試原本可用"
    panel.set_run_active(True)
    assert not panel._click_test_btn.isEnabled(), "循環執行中不得可點擊測試"
    assert not panel._key_test_btn.isEnabled(), "循環執行中不得可按鍵測試"


def test_run_inactive_restores_panel_state(panel):
    """循環停止後 → 依面板原本狀態還原（沒有選取結果時點擊測試仍停用）。"""
    panel.set_run_active(True)
    panel.set_run_active(False)
    assert panel._key_test_btn.isEnabled(), "循環停止後按鍵測試必須恢復"
    assert not panel._click_test_btn.isEnabled(), "沒有選取結果時點擊測試維持停用"


def test_run_active_preserves_panel_own_state(panel):
    """面板自己的狀態（已選取結果）不得被 set_run_active 覆蓋或遺失。"""
    _select_first_row(panel)
    assert panel._click_test_btn.isEnabled(), "前置條件：選取結果後點擊測試可用"

    panel.set_run_active(True)
    assert not panel._click_test_btn.isEnabled(), "循環執行中必須停用"

    panel.set_run_active(False)
    assert panel._click_test_btn.isEnabled(), "循環停止後必須還原面板原本的可用狀態"


def test_selection_during_run_active_stays_disabled(panel):
    """循環執行期間即使有選取結果，按鈕仍必須停用。"""
    panel.set_run_active(True)
    _select_first_row(panel)
    assert not panel._click_test_btn.isEnabled(), "循環執行中選取結果不得解鎖測試按鈕"

    panel.set_run_active(False)
    assert panel._click_test_btn.isEnabled(), "循環停止後解鎖為面板原本的狀態"


def test_set_run_active_is_idempotent(panel):
    """重複設定同一狀態不得改變結果（不得拋例外）。"""
    panel.set_run_active(True)
    panel.set_run_active(True)
    assert not panel._click_test_btn.isEnabled()
    panel.set_run_active(False)
    panel.set_run_active(False)
    assert panel._key_test_btn.isEnabled()


# ── 2. 主視窗層：與循環狀態同步 ─────────────────────────────────────


def test_mainwindow_update_edit_enabled_follows_loop_state(real_mainwindow):
    """``_update_edit_enabled(False)``＝循環執行中 → 測試按鈕停用。

    所有呼叫點的語意都是「enabled ＝ 循環未執行」
    （啟動 :8137 / 停止 :8167 / 緊急停止 :8362 / 任務載入 :5907,:5944）。
    """
    win = real_mainwindow
    panel = win._debug_panel
    assert panel is not None

    win._update_edit_enabled(False)  # 循環執行中
    assert not panel._click_test_btn.isEnabled(), "循環執行中不得可點擊測試"
    assert not panel._key_test_btn.isEnabled(), "循環執行中不得可按鍵測試"

    win._update_edit_enabled(True)  # 循環停止
    assert panel._key_test_btn.isEnabled(), "循環停止後按鍵測試必須恢復"
    assert not panel._click_test_btn.isEnabled(), "點擊測試維持面板自身狀態"


def test_mainwindow_without_debug_panel_is_safe(real_mainwindow):
    """除錯面板尚未建立時不得拋例外（安全處理）。

    對應「視窗尚未初始化」：``_debug_panel`` 屬性還不存在或為 None。
    只驗證本次新增的呼叫點是安全的——``enabled=True`` 會走既有
    ``_show_rule_detail()``，那條路徑本來就假設面板存在（不在本次範圍）。
    """
    win = real_mainwindow
    panel = win._debug_panel
    try:
        win.__dict__.pop("_debug_panel", None)
        win._update_edit_enabled(False)  # 屬性不存在 → getattr 守衛生效
        win._debug_panel = None
        win._update_edit_enabled(False)  # 屬性為 None → getattr 守衛生效
    finally:
        win._debug_panel = panel
    assert panel is not None
