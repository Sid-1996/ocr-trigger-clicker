import threading
import time

import numpy as np
from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _loader import load_sibling

_screenshot = load_sibling("screenshot", "01_screenshot.py")
_ocr = load_sibling("ocr_engine", "02_ocr_engine.py")

activate_window = _screenshot.activate_window
capture = _screenshot.capture
capture_window_content = _screenshot.capture_window_content
recognize = _ocr.recognize


class _NoWheelCombo(QComboBox):
    def wheelEvent(self, e):
        e.ignore()


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


class OcrDebugWindow(QMainWindow):
    roi_selected = pyqtSignal(dict)
    rule_requested = pyqtSignal(dict)
    closed = pyqtSignal()

    _OCR_MODES = {
        "完整測試": {"preprocess": False, "max_side_len": 0, "min_confidence": 0.25},
        "平衡": {"preprocess": True, "max_side_len": 960, "min_confidence": 0.35},
        "快速": {"preprocess": True, "max_side_len": 640, "min_confidence": 0.5},
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
        self._selected_index = -1
        self._request_id = 0
        self._signals = _OcrSignals()
        self._signals.ocr_done.connect(self._on_ocr_done)

        self.setWindowTitle(f"OCR 診斷 — {window_title}")
        self.resize(1000, 650)
        self.setMinimumSize(800, 500)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self._capture_btn = QPushButton("拍一張(&C)")
        self._capture_btn.setMinimumWidth(80)
        self._capture_btn.setToolTip("擷取一次畫面並執行 OCR 辨識 (Alt+C)")
        self._ocr_mode = _NoWheelCombo()
        self._ocr_mode.addItems(list(self._OCR_MODES))
        self._ocr_mode.setCurrentText("完整測試")
        self._ocr_mode.setToolTip("完整測試：保留更多細節；快速：偏向即時回饋")
        self._close_btn = QPushButton("關閉")
        self._close_btn.setMinimumWidth(80)
        self._close_btn.clicked.connect(self.close)
        toolbar.addWidget(self._capture_btn)
        toolbar.addWidget(self._ocr_mode)
        self._click_test_btn = QPushButton("點擊測試(&T)")
        self._click_test_btn.setMinimumWidth(80)
        self._click_test_btn.setToolTip("點擊選取文字的目標位置，驗證座標是否正確")
        self._click_test_btn.setEnabled(False)
        self._click_test_btn.clicked.connect(self._on_click_test)
        toolbar.addWidget(self._click_test_btn)
        toolbar.addWidget(self._close_btn)
        toolbar.addStretch()
        self._info_label = QLabel("")
        toolbar.addWidget(self._info_label)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._image_label = _ImageLabel()
        self._image_label.setText("尚未截圖 — 點擊「拍一張」開始")
        self._image_label.clicked.connect(self._on_image_clicked)
        self._image_label.installEventFilter(self)
        splitter.addWidget(self._image_label)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._summary_label = QLabel("視窗：-\n來源：-\n尺寸：-\n區塊：-\n耗時：-")
        self._summary_label.setWordWrap(True)
        self._summary_label.setMinimumHeight(96)
        self._style_card(self._summary_label, dark=False)
        right_layout.addWidget(self._summary_label)

        self._result_table = QTableWidget()
        self._result_table.setFont(QFont("Consolas", 9))
        self._result_table.setColumnCount(3)
        self._result_table.setHorizontalHeaderLabels(["#", "文字", "信心度"])
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

        crop_title = QLabel("選取區塊預覽")
        crop_title.setStyleSheet("font-weight: 600; color: #666;")
        right_layout.addWidget(crop_title)

        self._crop_label = QLabel("點選表格中的一列，這裡會顯示裁切預覽")
        self._crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._crop_label.setMinimumHeight(180)
        self._crop_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._crop_label.setFixedHeight(200)
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

        self._selected_detail = QLabel("選取區塊：尚未選取")
        self._selected_detail.setWordWrap(True)
        self._selected_detail.setMinimumHeight(110)
        self._style_card(self._selected_detail, dark=True)
        right_layout.addWidget(self._selected_detail)

        self._apply_roi_btn = QPushButton("套用至目前規則 ROI(&R)")
        self._apply_roi_btn.setEnabled(False)
        self._apply_roi_btn.setToolTip("將選取的文字區塊座標設為目前規則的偵測範圍")
        self._apply_roi_btn.clicked.connect(self._on_apply_roi)
        right_layout.addWidget(self._apply_roi_btn)

        self._add_rule_btn = QPushButton("建立為新規則(&N)")
        self._add_rule_btn.setEnabled(False)
        self._add_rule_btn.setToolTip("將選取的文字與位置直接建立為一條新的偵測規則")
        self._add_rule_btn.clicked.connect(self._on_add_rule)
        right_layout.addWidget(self._add_rule_btn)

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

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("就緒")

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
        mode = self._ocr_mode.currentText()
        return self._OCR_MODES.get(mode, self._OCR_MODES["完整測試"])

    def _minimize_and_capture(self):
        try:
            parent = self.parent() if self.parent() else None

            self.showMinimized()
            if parent:
                parent.showMinimized()
            QApplication.processEvents()
            time.sleep(0.08)

            activate_window(self._window_title)
            time.sleep(0.12)

            img = capture(self._window_title)
            source = "螢幕截圖"

            if img is None:
                img = capture_window_content(self._window_title)
                source = "視窗內容"

            return img, source
        except Exception:
            return None, ""
        finally:
            parent = self.parent() if self.parent() else None
            if parent and parent.isMinimized():
                parent.showNormal()
                parent.activateWindow()
            if self.isMinimized():
                self.showNormal()

    def _take_snapshot(self):
        self._request_id += 1
        request_id = self._request_id
        self._capture_btn.setEnabled(False)
        self._capture_btn.setText("辨識中…")
        self._info_label.setText("")
        self._selected_index = -1
        self._apply_roi_btn.setEnabled(False)
        self._add_rule_btn.setEnabled(False)
        self._click_test_btn.setEnabled(False)

        raw, src = self._minimize_and_capture()
        self._capture_source = src

        if raw is None:
            self._status_bar.showMessage(f"無法擷取視窗「{self._window_title}」")
            self._capture_btn.setText("拍一張")
            self._capture_btn.setEnabled(True)
            return

        self._latest_raw = raw
        self._ocr_busy = True
        threading.Thread(target=self._do_ocr, args=(raw.copy(), request_id), daemon=True).start()

    def _do_ocr(self, img: np.ndarray, request_id: int):
        try:
            self._status_bar.showMessage("OCR 引擎載入中...")
            QApplication.processEvents()
            t0 = time.monotonic()
            opts = self._ocr_options()
            results = recognize(img, **opts)
            elapsed = (time.monotonic() - t0) * 1000
            self._signals.ocr_done.emit(results, elapsed, request_id)
        finally:
            self._ocr_busy = False

    def _on_ocr_done(self, results: list, elapsed_ms: float, request_id: int):
        try:
            if request_id != self._request_id:
                return
            self._ocr_results = results
            self._capture_btn.setText("拍一張")
            self._capture_btn.setEnabled(True)
            self._populate_table()
            self._rebuild_annotated()
            self._update_display()
            if self._latest_raw is None:
                return
            h, w = self._latest_raw.shape[:2]
            self._info_label.setText(f"耗時: {elapsed_ms:.0f} ms  {len(results)} 個區塊")
            self._summary_label.setText(
                f"視窗：{self._window_title}\n"
                f"來源：{self._capture_source or '未知'}\n"
                f"尺寸：{w} × {h}\n"
                f"區塊：{len(results)}\n"
                f"耗時：{elapsed_ms:.0f} ms"
            )
            self._status_bar.showMessage(
                f"[{self._capture_source}] {w}×{h} | {len(results)} 個區塊 | {elapsed_ms:.0f} ms"
            )
        except Exception:
            pass

    def _populate_table(self):
        self._result_table.blockSignals(True)
        self._result_table.setRowCount(len(self._ocr_results))
        for i, r in enumerate(self._ocr_results):
            self._result_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self._result_table.setItem(i, 1, QTableWidgetItem(r.text))
            item = QTableWidgetItem(f"{r.confidence:.2f}")
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
                self._apply_roi_btn.setEnabled(True)
                self._add_rule_btn.setEnabled(True)
                self._click_test_btn.setEnabled(True)
            else:
                self._selected_index = -1
                self._apply_roi_btn.setEnabled(False)
                self._add_rule_btn.setEnabled(False)
                self._click_test_btn.setEnabled(False)
            self._rebuild_annotated()
            self._update_display()
        except Exception as e:
            print(f"[_on_table_selection_changed] {e}")

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

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
                self._apply_roi_btn.setEnabled(True)
                self._add_rule_btn.setEnabled(True)
                self._click_test_btn.setEnabled(True)
                try:
                    self._rebuild_annotated()
                    self._update_display()
                except Exception:
                    pass
                return

    def _on_apply_roi(self):
        if self._selected_index < 0 or self._selected_index >= len(self._ocr_results):
            return
        r = self._ocr_results[self._selected_index]
        self.roi_selected.emit({"x": r.x, "y": r.y, "w": r.w, "h": r.h})

    def _on_add_rule(self):
        if self._selected_index < 0 or self._selected_index >= len(self._ocr_results):
            return
        r = self._ocr_results[self._selected_index]

        pad = 20
        img_h, img_w = self._latest_raw.shape[:2] if self._latest_raw is not None else (9999, 9999)
        roi = {
            "x": max(0, r.x - pad),
            "y": max(0, r.y - pad),
            "w": min(img_w - max(0, r.x - pad), r.w + pad * 2),
            "h": min(img_h - max(0, r.y - pad), r.h + pad * 2),
        }

        self.rule_requested.emit(
            {
                "target_text": r.text,
                "roi": roi,
                "fuzzy": True,
                "cooldown": 1.0,
                "click_position": "text_center",
            }
        )

        self._status_bar.showMessage(
            f"✓ 已建立新規則：「{r.text}」"
            f"  ROI: x={roi['x']}, y={roi['y']}, w={roi['w']}, h={roi['h']}"
        )

    def _on_click_test(self):
        if self._selected_index < 0 or self._selected_index >= len(self._ocr_results):
            return
        r = self._ocr_results[self._selected_index]

        from _loader import load_sibling

        _screenshot = load_sibling("screenshot", "01_screenshot.py")
        rect = _screenshot.get_window_rect(self._window_title)
        if rect is None:
            self._status_bar.showMessage(f"無法取得視窗「{self._window_title}」的座標")
            return

        cx = rect["x"] + int(r.x + r.w / 2)
        cy = rect["y"] + int(r.y + r.h / 2)

        _screenshot.activate_window(self._window_title)
        QApplication.processEvents()
        time.sleep(0.15)

        _ahk = load_sibling("ahk_socket", "03_ahk_socket.py")
        click_ok = _ahk.send_click(cx, cy)
        if not click_ok:
            _ahk.init_ahk()
            click_ok = _ahk.send_click(cx, cy)
        time.sleep(0.1)

        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QToolTip

        btn_pos = self._click_test_btn.mapToGlobal(QPoint(0, self._click_test_btn.height()))
        status_icon = "✓" if click_ok else "✗"
        status_text = "成功" if click_ok else "失敗"
        QToolTip.showText(
            btn_pos,
            f"{status_icon} 點擊{status_text}：{r.text}  ({cx}, {cy})",
            self._click_test_btn,
        )
        QTimer.singleShot(1500, QToolTip.hideText)

        self._status_bar.showMessage(f"點擊測試{status_text}：「{r.text}」  螢幕座標 ({cx}, {cy})")

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
            q_img = QImage(img.tobytes(), w, h, ch * w, QImage.Format.Format_RGB888).rgbSwapped()
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

                label = f"{i + 1}  {r.text}  {r.confidence:.2f}"
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
            self._annotated_pixmap = None
            self._crop_pixmap = None

    def _update_crop_preview(self):
        try:
            self._crop_pixmap = None
            self._selected_detail.setText("選取區塊：尚未選取")
            if self._latest_raw is None:
                self._crop_label.setText("無預覽")
                self._crop_label.setPixmap(QPixmap())
                return

            if self._selected_index < 0 or self._selected_index >= len(self._ocr_results):
                self._crop_label.setText("點選表格中的一列，這裡會顯示裁切預覽")
                self._crop_label.setPixmap(QPixmap())
                return

            r = self._ocr_results[self._selected_index]
            pad = 24
            x0 = max(0, r.x - pad)
            y0 = max(0, r.y - pad)
            x1 = min(self._latest_raw.shape[1], r.x + r.w + pad)
            y1 = min(self._latest_raw.shape[0], r.y + r.h + pad)
            if x1 <= x0 or y1 <= y0:
                self._crop_label.setText("無法產生裁切預覽")
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
            ).rgbSwapped()
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
                "選取區塊："
                f"#{self._selected_index + 1}\n"
                f"文字：{r.text}\n"
                f"座標：x={r.x}, y={r.y}, w={r.w}, h={r.h}\n"
                f"信心度：{r.confidence:.2f}"
            )
        except Exception as e:
            print(f"[_update_crop_preview] {e}")

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()
        self._update_crop_preview()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            if obj is self._image_label:
                QTimer.singleShot(0, self._update_display)

        return super().eventFilter(obj, event)
