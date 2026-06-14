import threading
import time

import numpy as np
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
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

capture = _screenshot.capture
capture_window_content = _screenshot.capture_window_content
recognize = _ocr.recognize


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
    ocr_done = pyqtSignal(list, float)


class OcrDebugWindow(QMainWindow):
    roi_selected = pyqtSignal(dict)

    def __init__(self, window_title: str, parent=None):
        super().__init__(parent)
        self._window_title = window_title
        self._ocr_busy = False
        self._ocr_results: list = []
        self._latest_raw: np.ndarray | None = None
        self._annotated_pixmap: QPixmap | None = None
        self._capture_source = ""
        self._selected_index = -1
        self._signals = _OcrSignals()
        self._signals.ocr_done.connect(self._on_ocr_done)

        self.setWindowTitle(f"OCR 診斷 — {window_title}")
        self.resize(1000, 650)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)

        toolbar = QHBoxLayout()
        self._capture_btn = QPushButton("拍一張")
        self._capture_btn.setToolTip("擷取一次畫面並執行 OCR 辨識")
        self._close_btn = QPushButton("關閉")
        self._close_btn.clicked.connect(self.close)
        toolbar.addWidget(self._capture_btn)
        toolbar.addWidget(self._close_btn)
        toolbar.addStretch()
        self._info_label = QLabel("")
        toolbar.addWidget(self._info_label)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._image_label = _ImageLabel()
        self._image_label.setText("尚未截圖 — 點擊「拍一張」開始")
        self._image_label.clicked.connect(self._on_image_clicked)
        splitter.addWidget(self._image_label)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._result_table = QTableWidget()
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

        self._apply_roi_btn = QPushButton("套用至目前規則 ROI")
        self._apply_roi_btn.setEnabled(False)
        self._apply_roi_btn.setToolTip("將選取的文字區塊座標設為目前規則的偵測範圍")
        self._apply_roi_btn.clicked.connect(self._on_apply_roi)
        right_layout.addWidget(self._apply_roi_btn)

        splitter.addWidget(right_panel)
        splitter.setSizes([650, 350])
        layout.addWidget(splitter)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("就緒")

        self._capture_btn.clicked.connect(self._take_snapshot)

    def _take_snapshot(self):
        self._capture_btn.setEnabled(False)
        self._capture_btn.setText("辨識中…")
        self._info_label.setText("")
        self._selected_index = -1
        self._apply_roi_btn.setEnabled(False)

        raw = capture_window_content(self._window_title)
        src = "PrintWindow"
        if raw is None:
            raw = capture(self._window_title)
            src = "mss"
        self._capture_source = src

        if raw is None:
            self._status_bar.showMessage(f"無法擷取視窗「{self._window_title}」")
            self._capture_btn.setText("拍一張")
            self._capture_btn.setEnabled(True)
            return

        self._latest_raw = raw
        self._ocr_busy = True
        threading.Thread(target=self._do_ocr, args=(raw.copy(),), daemon=True).start()

    def _do_ocr(self, img: np.ndarray):
        try:
            t0 = time.monotonic()
            results = recognize(img)
            elapsed = (time.monotonic() - t0) * 1000
            self._signals.ocr_done.emit(results, elapsed)
        finally:
            self._ocr_busy = False

    def _on_ocr_done(self, results: list, elapsed_ms: float):
        self._ocr_results = results
        self._capture_btn.setText("拍一張")
        self._capture_btn.setEnabled(True)
        self._populate_table()
        self._rebuild_annotated()
        self._update_display()
        h, w = self._latest_raw.shape[:2]
        self._info_label.setText(f"耗時: {elapsed_ms:.0f} ms  {len(results)} 個區塊")
        self._status_bar.showMessage(
            f"{self._capture_source} | {w}×{h} | {len(results)} 個區塊 | {elapsed_ms:.0f} ms"
        )

    def _populate_table(self):
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

    def _on_table_selection_changed(self):
        rows = self._result_table.selectedIndexes()
        if rows:
            self._selected_index = rows[0].row()
            self._apply_roi_btn.setEnabled(True)
        else:
            self._selected_index = -1
            self._apply_roi_btn.setEnabled(False)
        self._rebuild_annotated()
        self._update_display()

    def _on_image_clicked(self, label_x: int, label_y: int):
        if self._latest_raw is None or not self._ocr_results:
            return
        pixmap = self._image_label.pixmap()
        if pixmap is None:
            return

        scaled_w = pixmap.width()
        scaled_h = pixmap.height()
        offset_x = max(0, (self._image_label.width() - scaled_w) // 2)
        offset_y = max(0, (self._image_label.height() - scaled_h) // 2)

        img_x = label_x - offset_x
        img_y = label_y - offset_y
        if img_x < 0 or img_y < 0 or img_x >= scaled_w or img_y >= scaled_h:
            return

        orig_w = self._latest_raw.shape[1]
        orig_h = self._latest_raw.shape[0]
        orig_x = int(img_x / scaled_w * orig_w)
        orig_y = int(img_y / scaled_h * orig_h)

        for i, r in enumerate(self._ocr_results):
            if r.x <= orig_x <= r.x + r.w and r.y <= orig_y <= r.y + r.h:
                self._selected_index = i
                self._result_table.blockSignals(True)
                self._result_table.selectRow(i)
                self._result_table.blockSignals(False)
                self._apply_roi_btn.setEnabled(True)
                self._rebuild_annotated()
                self._update_display()
                return

    def _on_apply_roi(self):
        if self._selected_index < 0 or self._selected_index >= len(self._ocr_results):
            return
        r = self._ocr_results[self._selected_index]
        self.roi_selected.emit({"x": r.x, "y": r.y, "w": r.w, "h": r.h})

    def _rebuild_annotated(self):
        if self._latest_raw is None:
            self._annotated_pixmap = None
            return
        img = np.ascontiguousarray(self._latest_raw)
        h, w, ch = img.shape
        q_img = QImage(img.tobytes(), w, h, ch * w, QImage.Format.Format_RGB888).rgbSwapped()
        pixmap = QPixmap.fromImage(q_img)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        FONT = QFont("Consolas", 9)
        painter.setFont(FONT)

        for i, r in enumerate(self._ocr_results):
            if r.confidence >= 0.5:
                color = QColor(0, 220, 255)
            else:
                color = QColor(255, 80, 80)

            if i == self._selected_index:
                painter.setPen(QPen(QColor(255, 220, 0), 3))
            else:
                painter.setPen(QPen(color, 2))

            painter.drawRect(r.x, r.y, r.w, r.h)

            if r.confidence >= 0.5:
                label = f"{i + 1}  {r.text}  {r.confidence:.2f}"
                fm = painter.fontMetrics()
                tw = fm.horizontalAdvance(label)
                th = fm.height()
                label_x = r.x + r.w - tw - 6
                if label_x < r.x:
                    label_x = r.x
                painter.fillRect(label_x - 3, r.y, tw + 6, th + 4, QColor(0, 0, 0, 180))
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(label_x, r.y + th + 2, label)

        painter.end()
        self._annotated_pixmap = pixmap

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
