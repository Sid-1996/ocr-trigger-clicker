"""OCR Debug UX Phase 4-B：顯示開關 / 比較切換 / 診斷精簡 / 右側收斂。

使用真實 QWidget（offscreen）驗證可見性與 pixmap 內容，不 mock UI 本身；
只在需要時設定 _latest_raw / _ocr_results 測試資料。
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


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def panel(qapp):
    p = _mod.OcrDebugPanel("", None)
    p.show()
    qapp.processEvents()
    yield p
    p.deleteLater()
    qapp.processEvents()


def _ocr_result(text="確定", x=1, y=2, w=6, h=5, confidence=0.99):
    return SimpleNamespace(text=text, x=x, y=y, w=w, h=h, confidence=confidence)


def _image(h=20, w=30, value=100):
    return np.full((h, w, 3), value, dtype=np.uint8)


def _setup_capture(panel, results=None):
    panel._latest_raw = _image(90, 120)
    if results is None:
        results = [_ocr_result(x=10, y=10, w=40, h=20)]
    panel._ocr_results = results
    panel._populate_table()
    panel._rebuild_annotated()
    panel._update_display()


def _pixel(panel):
    """_annotated_pixmap 內 OCR 框區域的像素値，判斷標註有無繪入。"""
    pm = panel._annotated_pixmap
    assert pm is not None and not pm.isNull()
    img = pm.toImage()
    return img.pixelColor(2, 3)


# ── P0：OCR 框顯示開關 ──────────────────────────────────────────────────────


def test_show_boxes_default_off(panel, isolated_data_dir):
    assert panel._show_boxes is False
    assert panel._show_boxes_check.isChecked() is False


def test_show_boxes_restored_true_on_panel_recreate(panel, isolated_data_dir, qapp):
    panel._show_boxes_check.setChecked(True)
    assert panel._show_boxes is True
    panel.deleteLater()
    qapp.processEvents()
    p2 = _mod.OcrDebugPanel("", None)
    try:
        assert p2._show_boxes is True
        assert p2._show_boxes_check.isChecked() is True
    finally:
        p2.deleteLater()
        qapp.processEvents()


def test_show_boxes_restored_false_on_panel_recreate(panel, isolated_data_dir, qapp):
    panel._show_boxes_check.setChecked(True)
    panel._show_boxes_check.setChecked(False)
    assert panel._show_boxes is False
    panel.deleteLater()
    qapp.processEvents()
    p2 = _mod.OcrDebugPanel("", None)
    try:
        assert p2._show_boxes is False
        assert p2._show_boxes_check.isChecked() is False
    finally:
        p2.deleteLater()
        qapp.processEvents()


def test_show_boxes_no_saved_value_defaults_false(isolated_data_dir, qapp):
    p = _mod.OcrDebugPanel("", None)
    try:
        assert p._show_boxes is False
        assert p._show_boxes_check.isChecked() is False
    finally:
        p.deleteLater()
        qapp.processEvents()


def test_show_boxes_off_means_clean_pixmap(panel):
    _setup_capture(panel)
    # 關閉時 pixmap 等於 _latest_raw（無標註）：左上角像素是原圖値 100
    assert panel._annotated_pixmap.width() == 120
    assert panel._annotated_pixmap.height() == 90
    raw_q = panel._annotated_pixmap.toImage()
    assert raw_q.pixelColor(0, 0).value() == 100


def test_show_boxes_on_draws_box(panel):
    _setup_capture(panel, [_ocr_result(x=10, y=30, w=40, h=20, confidence=0.99)])
    panel._show_boxes_check.setChecked(True)
    panel._rebuild_annotated()
    # 框緣：存在低 R、高 G 的青色像素即視為已繪入（pen 抗鋸齒混合取容差；QPixmap 非
    # HiDPI 1:1 時 pen 中心列才放得出純色，低 R 即已充分區分）
    img = panel._annotated_pixmap.toImage()
    found = False
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.red() < 60 and c.green() > 40 and c.blue() > 40:
                found = True
                break
        if found:
            break
    assert found


def test_show_boxes_toggle_keeps_results_and_selection(panel):
    _setup_capture(panel)
    panel._result_table.selectRow(0)
    assert panel._selected_index == 0
    before = list(panel._ocr_results)
    panel._show_boxes_check.setChecked(True)
    assert list(panel._ocr_results) == before
    assert panel._selected_index == 0
    assert panel._result_table.rowCount() == 1
    # crop 預覽仍可用（用 _latest_raw）
    assert panel._crop_pixmap is not None and not panel._crop_pixmap.isNull()


def test_show_boxes_toggle_does_not_rerun_ocr(panel, monkeypatch):
    _setup_capture(panel)
    called = {"n": 0}
    monkeypatch.setattr(panel, "_do_ocr", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    panel._show_boxes_check.setChecked(True)
    panel._show_boxes_check.setChecked(False)
    assert called["n"] == 0


def test_clear_results_keeps_show_boxes_preference(panel, isolated_data_dir):
    panel._show_boxes_check.setChecked(True)
    assert panel._show_boxes is True
    panel.clear_results()
    assert panel._show_boxes is True
    assert panel._show_boxes_check.isChecked() is True


def test_show_boxes_hide_selection_highlight(panel):
    _setup_capture(panel)
    panel._result_table.selectRow(0)
    panel._show_boxes_check.setChecked(False)
    panel._rebuild_annotated()
    px = _pixel(panel)
    # 關閉時選取高亮也消失
    assert (px.red(), px.green(), px.blue()) != (255, 220, 0)


# ── Visual 僅供內部（Phase 4-C 移除使用者可見預覽） ────────────────────────


def _render_visual(panel):
    before = _image(value=80)
    after = _image(value=170)
    visual = _mod._compare_visual(before, after, (0, 0, 30, 20), scope="frame")
    result = _mod.BackendTestResult(
        1, "key", "frida", 123, "space", None, _mod.BackendStatus.SUCCESS, 1.0, visual=visual
    )
    panel._render_diagnostic_result(result)
    return result


def test_visual_no_preview_ui_widgets(panel):
    # 使用者可見的比較預覽 UI 不存在
    assert not hasattr(panel, "_visual_preview")
    assert not hasattr(panel, "_visual_preview_combo")
    assert not hasattr(panel, "_visual_preview_panes")
    assert not hasattr(panel, "_visual_preview_pixmaps")
    assert not hasattr(panel, "_render_visual_preview")
    assert not hasattr(panel, "_update_visual_preview")


def test_visual_result_still_has_arrays_and_status_shown(panel):
    result = _render_visual(panel)
    # 後端資料契約不變：before/after/heatmap 仍完整產生
    assert result.visual.before is not None
    assert result.visual.after is not None
    assert result.visual.heatmap is not None
    # 診斷主層仍顯示 Visual 狀態
    assert "Visual" in panel._diagnostic_label.text()
    # 不產生任何 pixmap 預覽
    assert not hasattr(panel, "_visual_preview_pixmaps")


# ── P1：診斷摘要精簡 ────────────────────────────────────────────────────────


def test_diagnostic_main_shows_three_core_states(panel):
    _render_visual(panel)
    main = panel._diagnostic_label.text()
    assert "Backend" in main
    assert "Visual" in main
    # 精簡後 ratio/pixels/roi 不在主層（後面測 detail 有）
    assert "Visual diff" not in main


def test_diagnostic_detail_expands_and_collapses(panel):
    _render_visual(panel)
    assert panel._diagnostic_detail_btn.isChecked() is False
    assert panel._diagnostic_detail_label.isHidden()
    panel._diagnostic_detail_btn.setChecked(True)
    assert not panel._diagnostic_detail_label.isHidden()
    detail = panel._diagnostic_detail_label.text()
    assert "Visual" in detail
    panel._diagnostic_detail_btn.setChecked(False)
    assert panel._diagnostic_detail_label.isHidden()


def test_diagnostic_backend_failed_error_in_main(panel):
    result = _mod.BackendTestResult(
        1,
        "key",
        "frida",
        123,
        "space",
        None,
        _mod.BackendStatus.FAILED,
        5.0,
        error="window_unavailable",
    )
    panel._render_diagnostic_result(result)
    main = panel._diagnostic_label.text()
    assert T("ocr_debug.diagnostic.backend.failed") in main
    assert T("ocr_debug.diagnostic.reason.window_unavailable") in main


def test_diagnostic_unavailable_reasons_not_lost(panel):
    visual = _mod.VisualAnalysis(
        status=_mod.ObservationStatus.UNAVAILABLE, reason="capture_unavailable"
    )
    text_diff = _mod.TextDiffAnalysis(
        status=_mod.ObservationStatus.UNAVAILABLE, reason="black_capture"
    )
    result = _mod.BackendTestResult(
        1,
        "key",
        "frida",
        123,
        "space",
        None,
        _mod.BackendStatus.SUCCESS,
        1.0,
        visual=visual,
        text_diff=text_diff,
    )
    panel._render_diagnostic_result(result)
    panel._diagnostic_detail_btn.setChecked(True)
    detail = panel._diagnostic_detail_label.text()
    assert T("ocr_debug.diagnostic.visual_reason.capture_unavailable") in detail
    assert T("ocr_debug.diagnostic.text_reason.black_capture") in detail
    # main 仍有 UNAVAILABLE 狀態
    assert T("ocr_debug.diagnostic.observation.unavailable") in panel._diagnostic_label.text()


def test_diagnostic_new_test_clears_old_detail(panel):
    _render_visual(panel)
    panel._diagnostic_detail_btn.setChecked(True)
    assert panel._diagnostic_detail_label.text() != ""
    # 新測試開始走 _on_key_test 會清 detail；直接 clear_results 也清
    panel.clear_results()
    assert panel._diagnostic_detail_label.text() == ""
    assert panel._diagnostic_detail_label.isHidden()
    assert panel._diagnostic_detail_btn.isChecked() is False
    assert panel._diagnostic_label.isHidden()


def test_diagnostic_stale_generation_does_not_overwrite(panel):
    _render_visual(panel)
    assert "Backend" in panel._diagnostic_label.text()
    old_text = panel._diagnostic_label.text()
    # 過期 backend 結果（test_id 與目前 request id 不符或直接呼 _on_backend_test_done 拒收）
    panel._key_verify_request_id = 99
    stale = _mod.BackendTestResult(
        1,
        "key",
        "frida",
        123,
        "space",
        None,
        _mod.BackendStatus.FAILED,
        1.0,
        error="window_unavailable",
    )
    panel._on_backend_test_done(stale)
    assert panel._diagnostic_label.text() == old_text


def test_diagnostic_text_diff_in_detail(panel):
    visual = _mod._compare_visual(_image(), _image(), (0, 0, 30, 20), scope="frame")
    text_diff = _mod.TextDiffAnalysis(
        status=_mod.ObservationStatus.CHANGED,
        scope="frame",
        added=("新文字",),
    )
    result = _mod.BackendTestResult(
        1,
        "key",
        "frida",
        123,
        "space",
        None,
        _mod.BackendStatus.SUCCESS,
        1.0,
        visual=visual,
        text_diff=text_diff,
    )
    panel._render_diagnostic_result(result)
    assert "新文字" not in panel._diagnostic_label.text()
    panel._diagnostic_detail_btn.setChecked(True)
    assert "新文字" in panel._diagnostic_detail_label.text()


# ── P2：右側資訊區可見性 ────────────────────────────────────────────────────


def test_right_widgets_hidden_without_selection(panel):
    assert panel._crop_title.isHidden()
    assert panel._crop_label.isHidden()
    assert panel._selected_detail.isHidden()
    # summary 保留（資訊不刪除）
    assert not panel._summary_label.isHidden()


def test_right_widgets_visible_with_selection(panel):
    _setup_capture(panel)
    panel._result_table.selectRow(0)
    assert not panel._crop_title.isHidden()
    assert not panel._crop_label.isHidden()
    assert not panel._selected_detail.isHidden()
    assert "確定" in panel._selected_detail.text()


def test_right_widgets_hidden_after_deselect(panel):
    _setup_capture(panel)
    panel._result_table.selectRow(0)
    assert not panel._crop_title.isHidden()
    panel._result_table.clearSelection()
    assert panel._crop_title.isHidden()
    assert panel._crop_label.isHidden()
    assert panel._selected_detail.isHidden()


def test_clear_results_restores_right_blank_state(panel):
    _setup_capture(panel)
    panel._result_table.selectRow(0)
    panel.clear_results()
    assert panel._crop_title.isHidden()
    assert panel._crop_label.isHidden()
    assert panel._selected_detail.isHidden()
    assert panel._summary_label.text() == T("ocr_debug.summary")


def test_i18n_new_keys_exist_all_locales():
    import json

    keys = [
        "ocr_debug.show_boxes",
        "ocr_debug.diagnostic.detail",
        "ocr_debug.diagnostic.detail_hide",
    ]
    for lang in ("zh_TW", "en", "ja"):
        data = json.loads((_root / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        for key in keys:
            assert data.get(key), f"{lang} missing {key}"
