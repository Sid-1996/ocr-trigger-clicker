import logging
import threading
import time

import numpy as np
from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from _loader import load_sibling
from i18n import T

_screenshot = load_sibling("screenshot", "core/01_screenshot.py")
_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_bg_input = load_sibling("bg_input", "core/16_bg_input.py")
_capture_pipeline = load_sibling("capture_pipeline", "core/17_capture_pipeline.py")
capture_frame = _capture_pipeline.capture_frame
_pw_mod = load_sibling("print_window", "core/15_print_window.py")
is_black_capture = _pw_mod.is_black_capture
is_admin = _pw_mod.is_admin

activate_window = _screenshot.activate_window
capture_window_content = getattr(_screenshot, "capture_window_content", lambda title: None)
recognize = _ocr.recognize


def _get_interaction_mode() -> str:
    import json
    from pathlib import Path

    try:
        from core._paths import _bundle_root, _is_frozen, get_data_path

        if _is_frozen():
            p = Path(get_data_path("config.json"))
        else:
            p = _bundle_root() / "config.json"
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("interaction_mode", "pynput")
    except Exception:
        return "pynput"


def _find_text_after_click(block_results: list, target: str) -> bool:
    """True if the same target text is still detected (case-insensitive, fuzzy)."""
    try:
        return bool(_ocr.find_text(block_results, target, "fuzzy", 0.8))
    except Exception:
        return False


_KEY_TEST_DEFAULT = "space"  # 16_bg_input / 03_pynput_input 兩邊都相容的按鍵名
_KEY_TEST_OPTIONS = (
    "space",
    "enter",
    "escape",
    "tab",
    "1",
    "2",
    "3",
    "up",
    "down",
    "f5",
)
_KEY_TEST_WAIT_SEC = 0.6
_KEY_PIXEL_TOLERANCE = 12
_KEY_SIMILAR_THRESHOLD = 0.90


def _frame_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """回傳 0~1 的相似度：像素差 > 12 的像素比例反算。"""
    if a.shape != b.shape:
        return 0.0
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    changed = (diff > _KEY_PIXEL_TOLERANCE).any(axis=2)
    return float(1.0 - changed.mean())


class _ClickBanner(QLabel):
    """單行結論列：點擊開啟完整結果對話框。"""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(T("ocr_debug.verify.detail_hint"))
        self.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _ImageLabel(QLabel):
    clicked = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setScaledContents(False)
        self.setStyleSheet("background-color: #1e1e1e; color: #888; font-size: 14px;")
        self.setMinimumSize(400, 300)

    def mousePressEvent(self, event):
        self.clicked.emit(int(event.position().x()), int(event.position().y()))
        super().mousePressEvent(event)


class _OcrSignals(QObject):
    ocr_done = pyqtSignal(list, float, int)
    ocr_status = pyqtSignal(str)
    click_verify_done = pyqtSignal(dict)
    key_verify_done = pyqtSignal(dict)


class OcrDebugPanel(QWidget):
    rule_requested = pyqtSignal(dict)
    step_requested = pyqtSignal(dict)
    template_requested = pyqtSignal(dict)
    template_step_requested = pyqtSignal(dict)

    _OCR_MODES = {
        "full_test": {"preprocess": False, "max_side_len": 0, "min_confidence": 0.25},
    }

    def __init__(self, window_title: str, parent=None):
        super().__init__(parent)
        self._window_title = window_title
        self._ocr_busy = False
        self._ocr_results: list = []
        self._latest_raw: np.ndarray | None = None
        self._annotated_pixmap: QPixmap | None = None
        self._crop_pixmap: QPixmap | None = None
        self._capture_source = ""
        self._black_warn_text = ""
        self._selected_index = -1
        self._request_id = 0
        self._has_active_rule = False
        self._verif_in_progress = False
        self._key_verif_in_progress = False
        self._signals = _OcrSignals()
        self._signals.ocr_done.connect(self._on_ocr_done)
        self._signals.ocr_status.connect(self._on_ocr_status)
        self._signals.click_verify_done.connect(self._on_click_verify_done)
        self._signals.key_verify_done.connect(self._on_key_verify_done)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self._capture_btn = QPushButton(T("ocr_debug.capture"))
        self._capture_btn.setMinimumWidth(80)
        self._capture_btn.setToolTip(T("ocr_debug.capture.tooltip"))
        toolbar.addWidget(self._capture_btn)
        self._click_test_btn = QPushButton(T("ocr_debug.click_test"))
        self._click_test_btn.setMinimumWidth(80)
        self._click_test_btn.setToolTip(T("ocr_debug.click_test.tooltip"))
        self._click_test_btn.setEnabled(False)
        self._click_test_btn.clicked.connect(self._on_click_test)
        toolbar.addWidget(self._click_test_btn)
        self._key_test_combo = QComboBox()
        for name in _KEY_TEST_OPTIONS:
            self._key_test_combo.addItem(name.capitalize(), name)
        self._key_test_combo.setCurrentIndex(_KEY_TEST_OPTIONS.index(_KEY_TEST_DEFAULT))
        self._key_test_combo.setToolTip(T("ocr_debug.key_test.key_choose.tooltip"))
        toolbar.addWidget(self._key_test_combo)
        self._key_test_btn = QPushButton(T("ocr_debug.key_test"))
        self._key_test_btn.setMinimumWidth(80)
        self._key_test_btn.setToolTip(T("ocr_debug.key_test.tooltip"))
        self._key_test_btn.clicked.connect(self._on_key_test)
        toolbar.addWidget(self._key_test_btn)
        toolbar.addStretch()
        self._info_label = QLabel("")
        toolbar.addWidget(self._info_label)
        layout.addLayout(toolbar)

        self._click_error_label = _ClickBanner()
        self._click_error_label.setObjectName("clickErrorLabel")
        self._click_error_label.setStyleSheet("color: #c62828;")
        self._click_error_label.clicked.connect(self._open_click_detail)
        layout.addWidget(self._click_error_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._image_label = _ImageLabel()
        self._image_label.setText(T("ocr_debug.no_capture"))
        self._image_label.clicked.connect(self._on_image_clicked)
        self._image_label.installEventFilter(self)
        splitter.addWidget(self._image_label)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._summary_label = QLabel(T("ocr_debug.summary"))
        self._summary_label.setWordWrap(True)
        self._summary_label.setMinimumHeight(96)
        self._style_card(self._summary_label, dark=False)
        right_layout.addWidget(self._summary_label)

        self._result_table = QTableWidget()
        self._result_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._result_table.setFont(QFont("Consolas", 9))
        self._result_table.setColumnCount(3)
        self._result_table.setHorizontalHeaderLabels(
            [T("ocr_debug.col_index"), T("ocr_debug.col_text"), T("ocr_debug.col_confidence")]
        )
        self._result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._result_table.setColumnWidth(0, 40)
        self._result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._result_table.setColumnWidth(2, 70)
        self._result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._result_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._result_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        right_layout.addWidget(self._result_table)

        crop_title = QLabel(T("ocr_debug.crop_preview_title"))
        crop_title.setStyleSheet("font-weight: 600; color: #666;")
        right_layout.addWidget(crop_title)

        self._crop_label = QLabel(T("ocr_debug.crop_hint"))
        self._crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._crop_label.setMinimumHeight(150)
        self._crop_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._crop_label.setStyleSheet(
            "QLabel {"
            "  background: #111;"
            "  color: #a8a8a8;"
            "  border: 1px solid #2a2d33;"
            "  border-radius: 8px;"
            "  padding: 6px;"
            "}"
        )
        right_layout.addWidget(self._crop_label)

        self._selected_detail = QLabel(T("ocr_debug.selected_none"))
        self._selected_detail.setWordWrap(True)
        self._selected_detail.setMinimumHeight(110)
        self._style_card(self._selected_detail, dark=True)
        right_layout.addWidget(self._selected_detail)

        self._template_btn = QPushButton(T("ocr_debug.create_template_rule"))
        self._template_btn.setEnabled(False)
        self._template_btn.setToolTip(T("ocr_debug.create_template_rule.tooltip"))
        self._template_btn.clicked.connect(self._on_add_template)
        right_layout.addWidget(self._template_btn)

        self._add_template_step_btn = QPushButton(T("ocr_debug.add_template_step"))
        self._add_template_step_btn.setEnabled(False)
        self._add_template_step_btn.setToolTip(T("ocr_debug.add_template_step.tooltip"))
        self._add_template_step_btn.clicked.connect(self._on_add_template_step)
        right_layout.addWidget(self._add_template_step_btn)

        self._add_rule_btn = QPushButton(T("ocr_debug.create_text_rule"))
        self._add_rule_btn.setEnabled(False)
        self._add_rule_btn.setToolTip(T("ocr_debug.create_text_rule.tooltip"))
        self._add_rule_btn.clicked.connect(self._on_add_rule)
        right_layout.addWidget(self._add_rule_btn)

        self._set_sub_target_btn = QPushButton(T("ocr_debug.add_text_step"))
        self._set_sub_target_btn.setEnabled(False)
        self._set_sub_target_btn.setToolTip(T("ocr_debug.add_text_step.tooltip"))
        self._set_sub_target_btn.clicked.connect(self._on_set_sub_target)
        right_layout.addWidget(self._set_sub_target_btn)

        # keep a single list for enable/disable iteration
        self._add_buttons = [
            self._template_btn,
            self._add_template_step_btn,
            self._add_rule_btn,
            self._set_sub_target_btn,
        ]

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setWidget(right_panel)

        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setSizes([580, 408])
        layout.addWidget(splitter, 1)

        self._status_bar = QStatusBar(self)
        self._status_bar.showMessage(T("ocr_debug.ready"))
        layout.addWidget(self._status_bar)

        self._capture_btn.clicked.connect(self._take_snapshot)

    def _style_card(self, widget: QLabel, *, dark: bool = False):
        if dark:
            widget.setStyleSheet(
                "QLabel {"
                "  background: #101215;"
                "  color: #d8d8d8;"
                "  border: 1px solid #2a2d33;"
                "  border-radius: 8px;"
                "  padding: 8px;"
                "}"
            )
        else:
            widget.setStyleSheet(
                "QLabel {"
                "  background: #f6f7f9;"
                "  color: #222;"
                "  border: 1px solid #d9dde3;"
                "  border-radius: 8px;"
                "  padding: 8px;"
                "}"
            )

    def _ocr_options(self) -> dict:
        return self._OCR_MODES["full_test"]

    def _minimize_and_capture(self):
        mode = _get_interaction_mode()
        title = self._window_title
        hwnd = _screenshot.get_window_hwnd(title)

        if mode != "pynput":
            img = capture_frame(mode, title, hwnd=hwnd)
            if img is not None:
                logging.debug("ocr_dbg: bg mode=%s %dx%d", mode, img.shape[1], img.shape[0])
                return img[:, :, ::-1].copy(), T("ocr_debug.source_screen")
            return None, ""

        # 前景模式：縮小主視窗 → 啟動目標視窗 → mss 截圖（避免閃爍優先）
        try:
            parent = self.parent() if self.parent() else None
            self_was_maxed = self.isMaximized()
            parent_was_maxed = parent.isMaximized() if parent else False
            self.showMinimized()
            if parent:
                parent.showMinimized()
            QApplication.processEvents()
            time.sleep(0.08)

            activate_window(title)
            QApplication.processEvents()
            time.sleep(0.12)

            img = capture_frame(mode, title, hwnd=hwnd)
            source = T("ocr_debug.source_screen")
            if img is not None:
                logging.debug("ocr_dbg: fg mss %dx%d", img.shape[1], img.shape[0])
                img = img[:, :, ::-1].copy()

            if img is None:
                img = capture_window_content(title)
                source = T("ocr_debug.source_gdi")
                if img is not None:
                    wr = _screenshot.get_window_rect(title)
                    if wr:
                        chrome = _screenshot.get_window_client_offset(title) or (0, 0)
                        full_h, full_w = wr["h"], wr["w"]
                        if img.shape[0] != full_h or img.shape[1] != full_w:
                            padded = np.zeros((full_h, full_w, img.shape[2]), dtype=img.dtype)
                            cx, cy = chrome
                            padded[cy : cy + img.shape[0], cx : cx + img.shape[1]] = img
                            img = padded

            return img, source
        except Exception:
            return None, ""
        finally:
            parent = self.parent() if self.parent() else None
            if parent and parent.isMinimized():
                if parent_was_maxed:
                    parent.showMaximized()
                else:
                    parent.showNormal()
                parent.activateWindow()
            if self.isMinimized():
                if self_was_maxed:
                    self.showMaximized()
                else:
                    self.showNormal()

    def _take_snapshot(self):
        self._request_id += 1
        request_id = self._request_id
        self._capture_btn.setEnabled(False)
        self._capture_btn.setText(T("ocr_debug.recognizing"))
        self._info_label.setText("")
        self._click_error_label.hide()
        self._black_warn_text = ""
        self._selected_index = -1
        self._add_rule_btn.setEnabled(False)
        self._template_btn.setEnabled(False)
        self._click_test_btn.setEnabled(False)
        self._update_step_btn_state()

        raw, src = self._minimize_and_capture()
        self._capture_source = src

        if raw is None:
            logging.warning("capture failed for '%s'", self._window_title)
            self._status_bar.showMessage(T("ocr_debug.capture_failed", title=self._window_title))
            self._capture_btn.setText(T("ocr_debug.capture"))
            self._capture_btn.setEnabled(True)
            return

        # 後台截圖全黑 + 非系統管理員 → 暫存提示，待 OCR 完成後與耗時訊息合併顯示
        if _get_interaction_mode() != "pynput" and is_black_capture(raw) and not is_admin():
            self._black_warn_text = T("bg_capture.black_admin_warn")

        self._latest_raw = raw
        self._ocr_busy = True
        threading.Thread(target=self._do_ocr, args=(raw.copy(), request_id), daemon=True).start()

    def _do_ocr(self, img: np.ndarray, request_id: int):
        try:
            self._signals.ocr_status.emit(T("ocr_debug.ocr_loading"))
            t0 = time.monotonic()
            opts = self._ocr_options()
            results = recognize(img, **opts)
            elapsed = (time.monotonic() - t0) * 1000
            logging.debug("ocr_dbg: %.0fms %d blocks", elapsed, len(results))
            self._signals.ocr_done.emit(results, elapsed, request_id)
        except Exception:
            logging.exception("_do_ocr failed")
            self._capture_btn.setText(T("ocr_debug.capture"))
            self._capture_btn.setEnabled(True)
        finally:
            self._ocr_busy = False

    def _on_ocr_status(self, msg: str):
        self._status_bar.showMessage(msg)

    def _on_ocr_done(self, results: list, elapsed_ms: float, request_id: int):
        try:
            if request_id != self._request_id:
                return
            self._ocr_results = results
            self._capture_btn.setText(T("ocr_debug.capture"))
            self._capture_btn.setEnabled(True)
            self._populate_table()
            self._rebuild_annotated()
            self._update_display()
            if self._latest_raw is None:
                return
            h, w = self._latest_raw.shape[:2]
            info_text = T("ocr_debug.info_label", ms=round(elapsed_ms), n=len(results))
            if self._black_warn_text:
                info_text = f"{info_text}  {self._black_warn_text}"
            self._info_label.setText(info_text)
            self._summary_label.setText(
                T(
                    "ocr_debug.summary_text",
                    title=self._window_title,
                    source=self._capture_source or T("ocr_debug.source_screen"),
                    w=w,
                    h=h,
                    n=len(results),
                    ms=round(elapsed_ms),
                )
            )
            self._status_bar.showMessage(
                T(
                    "ocr_debug.status_bar",
                    source=self._capture_source,
                    w=w,
                    h=h,
                    n=len(results),
                    ms=round(elapsed_ms),
                )
            )
        except Exception:
            logging.exception("_on_ocr_done failed")

    def _populate_table(self):
        self._result_table.blockSignals(True)
        self._result_table.setRowCount(len(self._ocr_results))
        for i, r in enumerate(self._ocr_results):
            self._result_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self._result_table.setItem(i, 1, QTableWidgetItem(r.text))
            item = QTableWidgetItem(f"{int(r.confidence * 100)}%")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if r.confidence >= 0.8:
                bg = QColor(220, 255, 220)
            elif r.confidence >= 0.5:
                bg = QColor(255, 250, 200)
            else:
                bg = QColor(255, 220, 220)
            item.setBackground(bg)
            self._result_table.setItem(i, 2, item)
        self._result_table.blockSignals(False)

    def _on_table_selection_changed(self):
        try:
            rows = self._result_table.selectedIndexes()
            if rows:
                self._selected_index = rows[0].row()
                self._add_rule_btn.setEnabled(True)
                self._template_btn.setEnabled(True)
                self._click_test_btn.setEnabled(True)
            else:
                self._selected_index = -1
                self._add_rule_btn.setEnabled(False)
                self._template_btn.setEnabled(False)
                self._click_test_btn.setEnabled(False)
            self._update_step_btn_state()
            self._rebuild_annotated()
            self._update_display()
        except Exception:
            logging.exception("_on_table_selection_changed failed")

    def _on_image_clicked(self, label_x: int, label_y: int):
        if self._latest_raw is None or not self._ocr_results:
            return
        h, w = self._latest_raw.shape[:2]
        if h < 1 or w < 1:
            return
        pixmap = self._image_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return

        scaled_w = pixmap.width()
        scaled_h = pixmap.height()
        offset_x = max(0, (self._image_label.width() - scaled_w) // 2)
        offset_y = max(0, (self._image_label.height() - scaled_h) // 2)

        img_x = label_x - offset_x
        img_y = label_y - offset_y
        if img_x < 0 or img_y < 0 or img_x >= scaled_w or img_y >= scaled_h:
            return

        orig_w = w
        orig_h = h
        orig_x = int(img_x / scaled_w * orig_w)
        orig_y = int(img_y / scaled_h * orig_h)

        for i, r in enumerate(self._ocr_results):
            if r.x <= orig_x <= r.x + r.w and r.y <= orig_y <= r.y + r.h:
                self._selected_index = i
                self._result_table.blockSignals(True)
                self._result_table.selectRow(i)
                self._result_table.blockSignals(False)
                self._add_rule_btn.setEnabled(True)
                self._template_btn.setEnabled(True)
                self._click_test_btn.setEnabled(True)
                self._update_step_btn_state()
                try:
                    self._rebuild_annotated()
                    self._update_display()
                except Exception:
                    pass
                return

    def set_has_active_rule(self, active: bool):
        self._has_active_rule = active
        self._update_step_btn_state()

    def _update_step_btn_state(self):
        enabled = self._selected_index >= 0 and self._has_active_rule
        self._set_sub_target_btn.setEnabled(enabled)
        self._add_template_step_btn.setEnabled(enabled)

    def _compute_roi(self):
        if self._selected_index < 0 or self._selected_index >= len(self._ocr_results):
            return None
        r = self._ocr_results[self._selected_index]
        img_h, img_w = self._latest_raw.shape[:2] if self._latest_raw is not None else (0, 0)
        if img_w < 1 or img_h < 1:
            return None
        pad = 20
        px_x = max(0, r.x - pad)
        px_y = max(0, r.y - pad)
        px_w = min(img_w - px_x, r.w + pad * 2)
        px_h = min(img_h - px_y, r.h + pad * 2)

        chrome = _screenshot.get_window_client_offset(self._window_title) or (0, 0)
        cx, cy = chrome
        is_gdi = self._capture_source == T("ocr_debug.source_gdi")
        if is_gdi or (cx <= 0 and cy <= 0):
            roi = {
                "x": px_x / img_w,
                "y": px_y / img_h,
                "w": px_w / img_w,
                "h": px_h / img_h,
                "roi_coord": "client",
            }
        else:
            client_w = img_w - cx
            client_h = img_h - cy
            roi = {
                "x": max(0.0, (px_x - cx) / client_w) if client_w > 0 else 0.0,
                "y": max(0.0, (px_y - cy) / client_h) if client_h > 0 else 0.0,
                "w": min(1.0, px_w / client_w) if client_w > 0 else 0.0,
                "h": min(1.0, px_h / client_h) if client_h > 0 else 0.0,
                "roi_coord": "client",
            }
        return roi, px_x, px_y, px_w, px_h

    def _on_add_rule(self):
        result = self._compute_roi()
        if result is None:
            return
        roi, px_x, px_y, px_w, px_h = result
        r = self._ocr_results[self._selected_index]

        self.rule_requested.emit(
            {
                "target_text": r.text,
                "roi": roi,
                "fuzzy": True,
                "click_position": "text_center",
            }
        )

        self._status_bar.showMessage(
            T("ocr_debug.rule_created", text=r.text, x=px_x, y=px_y, w=px_w, h=px_h)
        )

    def _on_add_template(self):
        result = self._compute_roi()
        if result is None:
            return
        roi, _px_x, _px_y, _px_w, _px_h = result
        r = self._ocr_results[self._selected_index]

        import cv2 as _cv2

        from _loader import load_sibling

        _tmpl = load_sibling("template_matching", "core/11_template_matching.py")

        img_h, img_w = self._latest_raw.shape[:2]
        t_x = max(0, r.x)
        t_y = max(0, r.y)
        t_w = min(img_w - t_x, r.w)
        t_h = min(img_h - t_y, r.h)
        if t_w < 1 or t_h < 1:
            return
        crop = self._latest_raw[t_y : t_y + t_h, t_x : t_x + t_w].copy()
        crop_bgr = _cv2.cvtColor(crop, _cv2.COLOR_RGB2BGR)
        template_b64 = _tmpl.img_to_b64(crop_bgr)

        logging.debug(
            "ocr_dbg: template rule src=%s px=(%d,%d) %dx%d roi=%s",
            self._capture_source,
            t_x,
            t_y,
            t_w,
            t_h,
            {k: round(v, 3) if isinstance(v, (int, float)) else v for k, v in roi.items()},
        )

        self.template_requested.emit(
            {
                "template_data": template_b64,
                "roi": roi,
                "name": r.text,
            }
        )

        self._status_bar.showMessage(
            T("ocr_debug.template_rule_created", text=r.text, tw=t_w, th=t_h, rw=_px_w, rh=_px_h)
        )

    def _on_set_sub_target(self):
        result = self._compute_roi()
        if result is None:
            return
        roi, px_x, px_y, px_w, px_h = result
        r = self._ocr_results[self._selected_index]

        self.step_requested.emit(
            {
                "target_text": r.text,
                "roi": roi,
            }
        )

        self._status_bar.showMessage(
            T("ocr_debug.step_added", text=r.text, x=px_x, y=px_y, w=px_w, h=px_h)
        )

    def _on_add_template_step(self):
        result = self._compute_roi()
        if result is None:
            return
        roi, _px_x, _px_y, _px_w, _px_h = result
        r = self._ocr_results[self._selected_index]

        import cv2 as _cv2

        from _loader import load_sibling

        _tmpl = load_sibling("template_matching", "core/11_template_matching.py")

        img_h, img_w = self._latest_raw.shape[:2]
        t_x = max(0, r.x)
        t_y = max(0, r.y)
        t_w = min(img_w - t_x, r.w)
        t_h = min(img_h - t_y, r.h)
        if t_w < 1 or t_h < 1:
            return
        crop = self._latest_raw[t_y : t_y + t_h, t_x : t_x + t_w].copy()
        crop_bgr = _cv2.cvtColor(crop, _cv2.COLOR_RGB2BGR)
        template_b64 = _tmpl.img_to_b64(crop_bgr)

        self.template_step_requested.emit(
            {
                "template_data": template_b64,
                "roi": roi,
                "name": r.text,
            }
        )

        logging.debug(
            "ocr_dbg: template step src=%s px=(%d,%d) %dx%d roi=%s",
            self._capture_source,
            t_x,
            t_y,
            t_w,
            t_h,
            {k: round(v, 3) if isinstance(v, (int, float)) else v for k, v in roi.items()},
        )

        self._status_bar.showMessage(
            T("ocr_debug.template_step_added", text=r.text, tw=t_w, th=t_h)
        )

    def _on_click_test(self):
        if self._selected_index < 0 or self._selected_index >= len(self._ocr_results):
            return
        r = self._ocr_results[self._selected_index]
        self._click_error_label.hide()

        from _loader import load_sibling

        _screenshot = load_sibling("screenshot", "core/01_screenshot.py")
        _input = load_sibling("pynput_input", "core/03_pynput_input.py")

        ocr_center_x = int(r.x + r.w / 2)
        ocr_center_y = int(r.y + r.h / 2)

        rect = _screenshot.get_window_rect(self._window_title)

        # Check if background mode is active
        mode = _get_interaction_mode()

        if mode != "pynput":
            # Background mode: use bg_input.click with client coordinates
            hwnd_val = _screenshot.get_window_hwnd(self._window_title)
            if not hwnd_val:
                self._status_bar.showMessage(
                    T("ocr_debug.window_coords_failed", title=self._window_title)
                )
                return
            # OCR coordinates are relative to the capture image
            # For GDI/PrintWindow capture, they are client-relative
            # For mss capture, they are window-relative (need to subtract chrome)
            if self._capture_source == T("ocr_debug.source_gdi"):
                client_x = ocr_center_x
                client_y = ocr_center_y
            else:
                # mss capture: subtract chrome offset to get client coordinates
                chrome = _screenshot.get_window_client_offset(self._window_title) or (0, 0)
                client_x = ocr_center_x - chrome[0]
                client_y = ocr_center_y - chrome[1]
            _bg_input.set_method(mode)
            click_ok = _bg_input.click(hwnd_val, client_x, client_y)
            cx, cy = client_x, client_y
        else:
            # Foreground mode: use existing pynput logic
            _screenshot.activate_window(self._window_title)
            QApplication.processEvents()
            time.sleep(0.15)

            if self._capture_source == T("ocr_debug.source_gdi"):
                import ctypes
                from ctypes import wintypes

                hwnd_val = _screenshot.get_window_hwnd(self._window_title)
                if hwnd_val:
                    pt = wintypes.POINT()
                    pt.x, pt.y = 0, 0
                    ctypes.windll.user32.ClientToScreen(hwnd_val, ctypes.byref(pt))
                    cx = pt.x + ocr_center_x
                    cy = pt.y + ocr_center_y
                elif rect is not None:
                    cx = rect["x"] + ocr_center_x
                    cy = rect["y"] + ocr_center_y
                else:
                    self._status_bar.showMessage(
                        T("ocr_debug.window_coords_failed", title=self._window_title)
                    )
                    return
                if rect is None:
                    rect = {"x": cx - ocr_center_x, "y": cy - ocr_center_y, "w": 0, "h": 0}
            else:
                if rect is None:
                    self._status_bar.showMessage(
                        T("ocr_debug.window_coords_failed", title=self._window_title)
                    )
                    return
                cx = rect["x"] + ocr_center_x
                cy = rect["y"] + ocr_center_y

            click_ok = _input.send_click(cx, cy)
        time.sleep(0.1)

        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QToolTip

        btn_pos = self._click_test_btn.mapToGlobal(QPoint(0, self._click_test_btn.height()))
        status_icon = "✓" if click_ok else "✗"
        status_text = T("ocr_debug.click_success") if click_ok else T("ocr_debug.click_failed")
        if not click_ok and mode == "frida":
            err_detail = _bg_input.last_error()
            if err_detail:
                status_text = f"{status_text} ({err_detail})"
            self._show_click_verify(
                "inject_fail",
                text=r.text,
                api_ok=False,
                sx=cx,
                sy=cy,
                last_error=err_detail,
            )
        tooltip = T(
            "ocr_debug.click_test_tooltip",
            icon=status_icon,
            status=status_text,
            text=r.text,
            source=self._capture_source,
            rx=rect["x"],
            ry=rect["y"],
            rw=rect["w"],
            rh=rect["h"],
            cx=ocr_center_x,
            cy=ocr_center_y,
            sx=cx,
            sy=cy,
        )
        QToolTip.showText(btn_pos, tooltip, self._click_test_btn)
        QTimer.singleShot(2500, QToolTip.hideText)

        self._status_bar.showMessage(
            T(
                "ocr_debug.click_test_status",
                status=status_text,
                text=r.text,
                rx=rect["x"],
                ry=rect["y"],
                cx=ocr_center_x,
                cy=ocr_center_y,
                sx=cx,
                sy=cy,
            )
        )

        if click_ok and mode == "frida":
            self._start_click_verify(r, cx, cy)

    def _start_click_verify(self, r, sx: int, sy: int):
        if self._verif_in_progress:
            return
        self._verif_in_progress = True
        self._click_test_btn.setEnabled(False)
        self._click_test_btn.setText(T("ocr_debug.verifying"))
        frame_size = self._latest_raw.shape[:2] if self._latest_raw is not None else (0, 0)
        threading.Thread(
            target=self._click_verify_worker,
            args=(r, sx, sy, frame_size[1], frame_size[0]),
            daemon=True,
        ).start()

    def _click_verify_worker(self, r, sx: int, sy: int, frame_w: int, frame_h: int):
        def emit(state: str, still: str, ms: float, err: str = ""):
            self._signals.click_verify_done.emit(
                {
                    "state": state,
                    "text": r.text,
                    "sx": sx,
                    "sy": sy,
                    "ms": ms,
                    "still": still,
                    "last_error": err,
                }
            )

        try:
            # 等 ~0.6s 過場，再重拍目標區塊確認點擊是否有實際反應
            time.sleep(0.6)
            mode = _get_interaction_mode()
            hwnd = _screenshot.get_window_hwnd(self._window_title)
            t0 = time.monotonic()
            if mode != "frida" or not hwnd:
                return
            img = capture_frame(mode, self._window_title, hwnd=hwnd)
            if img is None or is_black_capture(img):
                emit("black", "?", (time.monotonic() - t0) * 1000)
                return
            img = img[:, :, ::-1].copy()
            h, w = img.shape[:2]
            if (w, h) != (frame_w, frame_h):
                emit("window_changed", "?", (time.monotonic() - t0) * 1000)
                return
            crop = self._roi_patch(img, r)
            results = recognize(crop, **self._ocr_options())
            matched = _find_text_after_click(results, r.text)
            emit(
                "no_response" if matched else "success",
                "yes" if matched else "no",
                (time.monotonic() - t0) * 1000,
            )
        except Exception as e:
            logging.exception("click verify failed")
            emit("black", "?", 0.0, str(e))

    def _roi_patch(self, img: np.ndarray, r) -> np.ndarray:
        h, w = img.shape[:2]
        pad = max(4, int(max(r.w, r.h) * 0.25))
        x0 = max(0, r.x - pad)
        y0 = max(0, r.y - pad)
        x1 = min(w, r.x + r.w + pad)
        y1 = min(h, r.y + r.h + pad)
        return img[y0:y1, x0:x1]

    def _on_click_verify_done(self, out: dict):
        self._verif_in_progress = False
        self._click_test_btn.setEnabled(True)
        self._click_test_btn.setText(T("ocr_debug.click_test"))
        self._show_click_verify(
            out["state"],
            text=out["text"],
            api_ok=True,
            sx=out["sx"],
            sy=out["sy"],
            last_error=out.get("last_error", ""),
            ms=out.get("ms", 0.0),
            still=out.get("still", "?"),
        )

    def _show_click_verify(
        self,
        state: str,
        *,
        text: str = "",
        api_ok: bool,
        sx: int,
        sy: int,
        last_error: str = "",
        ms: float = 0.0,
        still: str = "?",
    ):
        colors = {
            "success": "#1e8e3e",
            "no_response": "#b45309",
            "inject_fail": "#c62828",
            "black": "#b45309",
            "window_changed": "#666",
        }
        key = state if state in colors else "black"
        guidance = T(f"ocr_debug.click_verify.{key}", text=text)
        dev = T(
            "ocr_debug.click_verify.dev_info",
            mode="frida",
            source=self._capture_source or "?",
            text=text,
            sx=sx,
            sy=sy,
            hwnd=_screenshot.get_window_hwnd(self._window_title) or "?",
            api=T("ocr_debug.click_success") if api_ok else T("ocr_debug.click_failed"),
            last_error=last_error or "無",
            ms=round(ms),
            still_visible=still,
        )
        self._last_verify_guidance = guidance
        self._last_verify_dev = dev
        self._click_error_label.setStyleSheet(f"color: {colors.get(key, '#666')};")
        self._click_error_label.setText(T(f"ocr_debug.click_verify.short.{key}", text=text))
        self._click_error_label.show()
        QTimer.singleShot(15000, self._click_error_label.hide)
        if key in ("no_response", "inject_fail", "black"):
            logging.warning("ocr_dbg click verify=%s text=%s last_error=%s", key, text, last_error)

    def _on_key_test(self):
        self._click_error_label.hide()
        key = self._key_test_combo.currentData() or _KEY_TEST_DEFAULT
        mode = _get_interaction_mode()
        if mode != "pynput":
            hwnd = _screenshot.get_window_hwnd(self._window_title)
            if not hwnd:
                self._status_bar.showMessage(
                    T("ocr_debug.window_coords_failed", title=self._window_title)
                )
                return
            self._start_key_verify(hwnd, key)
            return
        from _loader import load_sibling

        _input = load_sibling("pynput_input", "core/03_pynput_input.py")
        _screenshot.activate_window(self._window_title)
        QApplication.processEvents()
        time.sleep(0.15)
        ok = _input.send_key(key)
        if ok:
            self._status_bar.showMessage(T("ocr_debug.key_test_sent", key=key))
        else:
            self._status_bar.showMessage(
                T("ocr_debug.key_test_failed", err=getattr(_input, "last_error", lambda: "")())
            )

    def _start_key_verify(self, hwnd: int, key: str):
        if self._key_verif_in_progress:
            return
        self._key_verif_in_progress = True
        self._key_test_btn.setEnabled(False)
        self._key_test_btn.setText(T("ocr_debug.key_test.verifying"))
        threading.Thread(target=self._key_verify_worker, args=(hwnd, key), daemon=True).start()

    def _key_verify_worker(self, hwnd: int, key: str):
        def emit(state: str, **kw):
            self._signals.key_verify_done.emit(
                {"state": state, "similar": "?", "err": "", "ms": 0.0, "key": key, **kw}
            )

        try:
            mode = _get_interaction_mode()
            if mode == "pynput":
                emit("fail", err="mode changed to pynput")
                return
            t0 = time.monotonic()
            before = capture_frame(mode, self._window_title, hwnd=hwnd)
            if before is None or is_black_capture(before):
                emit("black")
                return
            _bg_input.set_method(mode)
            sent = _bg_input.send_key(hwnd, key)
            ms = (time.monotonic() - t0) * 1000
            if not sent:
                emit("fail", err=_bg_input.last_error() or "", ms=ms)
                return
            time.sleep(_KEY_TEST_WAIT_SEC)
            after = capture_frame(mode, self._window_title, hwnd=hwnd)
            if after is None or is_black_capture(after):
                emit("black", ms=(time.monotonic() - t0) * 1000)
                return
            ms = (time.monotonic() - t0) * 1000
            if before.shape != after.shape:
                emit("window_changed", ms=ms)
                return
            sim = _frame_similarity(before, after)
            emit(
                "success" if sim < _KEY_SIMILAR_THRESHOLD else "no_change",
                similar=round(sim * 100, 1),
                ms=ms,
            )
        except Exception as e:
            logging.exception("key verify failed")
            emit("fail", err=str(e))

    def _on_key_verify_done(self, out: dict):
        self._key_verif_in_progress = False
        self._key_test_btn.setEnabled(True)
        self._key_test_btn.setText(T("ocr_debug.key_test"))
        self._show_key_verify(out)

    def _show_key_verify(self, out: dict):
        state = out.get("state", "black")
        colors = {
            "success": "#1e8e3e",
            "no_change": "#b45309",
            "fail": "#c62828",
            "black": "#b45309",
            "window_changed": "#666",
        }
        key = state if state in colors else "black"
        test_key = out.get("key", _KEY_TEST_DEFAULT)
        sim = out.get("similar", "?")
        guidance = (
            T("ocr_debug.click_verify.inject_fail", text="")
            if key == "fail"
            else T(f"ocr_debug.key_test.{key}", sim=sim, key=test_key)
        )
        dev = T(
            "ocr_debug.key_test.dev_info",
            mode="frida",
            source=self._capture_source or "?",
            key=test_key,
            sim=sim,
            hwnd=_screenshot.get_window_hwnd(self._window_title) or "?",
            api="send_key",
            err=out.get("err", "") or "無",
            ms=round(out.get("ms", 0.0)),
        )
        self._last_verify_guidance = guidance
        self._last_verify_dev = dev
        self._last_verify_title = T("ocr_debug.key_test.dialog_title")
        short_for = {
            "success": ("key_test", "ok"),
            "no_change": ("key_test", "no_change"),
            "fail": ("click_verify", "inject_fail"),
            "black": ("click_verify", "black"),
            "window_changed": ("click_verify", "window_changed"),
        }
        ns, sk = short_for.get(key, ("key_test", key))
        self._click_error_label.setStyleSheet(f"color: {colors.get(key, '#666')};")
        self._click_error_label.setText(T(f"ocr_debug.{ns}.short.{sk}"))
        self._click_error_label.show()
        QTimer.singleShot(15000, self._click_error_label.hide)
        if key in ("no_change", "fail", "black"):
            logging.warning(
                "ocr_dbg key verify=%s key=%s err=%s", key, test_key, out.get("err", "")
            )

    def _open_click_detail(self):
        guidance = getattr(self, "_last_verify_guidance", "")
        dev = getattr(self, "_last_verify_dev", "")
        if not guidance and not dev:
            return
        title = getattr(self, "_last_verify_title", "") or T("ocr_debug.verify.dialog_title")
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        v = QVBoxLayout(dlg)
        guide_label = QLabel(guidance)
        guide_label.setWordWrap(True)
        v.addWidget(guide_label)
        dev_view = QTextEdit(dev)
        dev_view.setReadOnly(True)
        dev_view.setFont(QFont("Consolas", 9))
        dev_view.setFixedHeight(150)
        v.addWidget(dev_view)
        row = QHBoxLayout()
        copy_btn = QPushButton(T("ocr_debug.verify.copy"))
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(dev))
        row.addWidget(copy_btn)
        row.addStretch()
        close_btn = QPushButton(T("ocr_debug.verify.close"))
        close_btn.clicked.connect(dlg.accept)
        row.addWidget(close_btn)
        v.addLayout(row)
        dlg.resize(560, 420)
        dlg.exec()

    def _rebuild_annotated(self):
        try:
            if self._latest_raw is None:
                self._annotated_pixmap = None
                self._crop_pixmap = None
                return
            h, w = self._latest_raw.shape[:2]
            if h < 1 or w < 1:
                self._annotated_pixmap = None
                self._crop_pixmap = None
                return
            img = np.ascontiguousarray(self._latest_raw)
            h, w, ch = img.shape
            q_img = QImage(img.tobytes(), w, h, ch * w, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)
            if pixmap.isNull():
                self._annotated_pixmap = None
                self._crop_pixmap = None
                return

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            font = QFont("Consolas", 9)
            painter.setFont(font)
            fm = painter.fontMetrics()
            th = fm.height()

            for i, r in enumerate(self._ocr_results):
                if i == self._selected_index:
                    painter.setPen(QPen(QColor(255, 220, 0), 5))
                elif r.confidence >= 0.5:
                    painter.setPen(QPen(QColor(0, 220, 255), 3))
                else:
                    painter.setPen(QPen(QColor(255, 80, 80), 3))
                painter.drawRect(r.x, r.y, r.w, r.h)

                label = f"{i + 1}  {r.text}  {int(r.confidence * 100)}%"
                tw = fm.horizontalAdvance(label)

                label_x = r.x
                label_y = r.y - 4
                bg_y = label_y - th - 2
                if bg_y < 0:
                    label_y = r.y + th + 4
                    bg_y = r.y

                painter.fillRect(label_x - 2, bg_y - 2, tw + 8, th + 6, QColor(0, 0, 0, 180))
                text_color = QColor(255, 255, 255) if r.confidence >= 0.5 else QColor(255, 180, 180)
                painter.setPen(text_color)
                painter.drawText(label_x + 2, label_y, label)

            painter.end()
            self._annotated_pixmap = pixmap
            self._update_crop_preview()
        except Exception:
            logging.exception("_rebuild_annotated failed")
            self._annotated_pixmap = None
            self._crop_pixmap = None

    def _update_crop_preview(self):
        try:
            self._crop_pixmap = None
            self._selected_detail.setText(T("ocr_debug.selected_none"))
            if self._latest_raw is None:
                self._crop_label.setText(T("ocr_debug.no_preview"))
                self._crop_label.setPixmap(QPixmap())
                return

            if self._selected_index < 0 or self._selected_index >= len(self._ocr_results):
                self._crop_label.setText(T("ocr_debug.crop_hint"))
                self._crop_label.setPixmap(QPixmap())
                return

            r = self._ocr_results[self._selected_index]
            pad = 24
            x0 = max(0, r.x - pad)
            y0 = max(0, r.y - pad)
            x1 = min(self._latest_raw.shape[1], r.x + r.w + pad)
            y1 = min(self._latest_raw.shape[0], r.y + r.h + pad)
            if x1 <= x0 or y1 <= y0:
                self._crop_label.setText(T("ocr_debug.crop_gen_failed"))
                self._crop_label.setPixmap(QPixmap())
                return

            crop = np.ascontiguousarray(self._latest_raw[y0:y1, x0:x1])
            ch = crop.shape[2]
            q_img = QImage(
                crop.tobytes(),
                crop.shape[1],
                crop.shape[0],
                ch * crop.shape[1],
                QImage.Format.Format_RGB888,
            )
            pixmap = QPixmap.fromImage(q_img)
            self._crop_pixmap = pixmap
            self._crop_label.setPixmap(
                pixmap.scaled(
                    self._crop_label.width(),
                    self._crop_label.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self._selected_detail.setText(
                T(
                    "ocr_debug.detail_text",
                    n=self._selected_index + 1,
                    text=r.text,
                    x=r.x,
                    y=r.y,
                    w=r.w,
                    h=r.h,
                    conf=int(r.confidence * 100),
                )
            )
        except Exception:
            logging.exception("_update_crop_preview failed")

    def _update_display(self):
        if self._annotated_pixmap is None:
            return
        target = self._image_label.contentsRect().size()
        if target.width() < 10 or target.height() < 10:
            target = self._image_label.size()
        scaled = self._annotated_pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def clear_results(self):
        self._ocr_results = []
        self._latest_raw = None
        self._annotated_pixmap = None
        self._crop_pixmap = None
        self._selected_index = -1
        self._info_label.setText("")
        self._add_rule_btn.setEnabled(False)
        self._click_test_btn.setEnabled(False)
        self._update_step_btn_state()
        self._image_label.setText(T("ocr_debug.switch_window"))
        self._image_label.setPixmap(QPixmap())
        self._crop_label.setText("")
        self._crop_label.setPixmap(QPixmap())
        self._selected_detail.setText(T("ocr_debug.selected_none"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()
        self._update_crop_preview()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            if obj is self._image_label:
                QTimer.singleShot(0, self._update_display)

        return super().eventFilter(obj, event)
