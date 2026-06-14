import threading
import time

import cv2
import numpy as np
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QMainWindow, QStatusBar, QVBoxLayout, QWidget

from _loader import load_sibling

_screenshot = load_sibling("screenshot", "01_screenshot.py")
_ocr = load_sibling("ocr_engine", "02_ocr_engine.py")

capture = _screenshot.capture
capture_window_content = _screenshot.capture_window_content
activate_window = _screenshot.activate_window
recognize = _ocr.recognize
OcrResult = _ocr.OcrResult


class _OcrSignals(QObject):
    frame_ready = pyqtSignal(object, list)  # annotated (np.ndarray | None), results
    ocr_done = pyqtSignal(object, list, float)  # annotated, results, elapsed_ms


class OcrDebugWindow(QMainWindow):
    def __init__(self, window_title: str, parent=None):
        super().__init__(parent)
        self._window_title = window_title
        self._ocr_busy = False
        self._ocr_results: list = []
        self._latest_raw: np.ndarray | None = None
        self._capture_source = ""
        self._signals = _OcrSignals()
        self._signals.frame_ready.connect(self._on_frame)
        self._signals.ocr_done.connect(self._on_ocr_done)

        self.setWindowTitle(f"OCR 效能診斷 — {window_title}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(640, 480)
        self.resize(960, 720)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._image_label = QLabel("正在初始化 OCR 診斷…")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background-color: #1e1e1e; color: #aaa; font-size: 14px;")
        layout.addWidget(self._image_label)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("就緒")

        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)

    def start(self, interval_ms: int = 1000):
        activate_window(self._window_title)
        self._timer.start(interval_ms)
        self._tick()

    def stop(self):
        self._timer.stop()
        self._ocr_busy = False

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

    def _tick(self):
        raw = capture_window_content(self._window_title)
        src = "PrintWindow"
        if raw is None:
            raw = capture(self._window_title)
            src = "mss (fallback)"
        self._capture_source = src

        if raw is None:
            self._ocr_busy = False
            self._signals.frame_ready.emit(None, [])
            return

        self._latest_raw = raw

        if self._ocr_results:
            annotated = self._annotate(raw, self._ocr_results)
            self._signals.frame_ready.emit(annotated, self._ocr_results)
        else:
            self._signals.frame_ready.emit(raw, [])

        if not self._ocr_busy:
            self._ocr_busy = True
            threading.Thread(target=self._do_ocr, args=(raw.copy(),), daemon=True).start()

    def _do_ocr(self, img: np.ndarray):
        try:
            t0 = time.monotonic()
            results = recognize(img)
            elapsed = (time.monotonic() - t0) * 1000
            annotated = self._annotate(img, results)
            self._signals.ocr_done.emit(annotated, results, elapsed)
        finally:
            self._ocr_busy = False

    @staticmethod
    def _annotate(img: np.ndarray, results: list) -> np.ndarray:
        annotated = img.copy()
        for r in results:
            x, y, w, h = r.x, r.y, r.w, r.h
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)
            label = f"{r.text} ({r.confidence:.2f})"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(annotated, (x, y - th - 4), (x + tw + 4, y), (0, 255, 0), -1)
            cv2.putText(
                annotated, label, (x + 2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1
            )
        return annotated

    def _on_frame(self, annotated: np.ndarray | None, results: list):
        if annotated is None:
            self._status_bar.showMessage(f"無法擷取視窗「{self._window_title}」")
            self._image_label.setText(f"⚠ 找不到視窗「{self._window_title}」\n請確認視窗仍開啟")
            return

        h, w = annotated.shape[:2]
        self._show_image(annotated)
        if not results:
            self._status_bar.showMessage(f"{self._capture_source} | {w}×{h} | 尚未取得辨識結果…")

    def _on_ocr_done(self, annotated: np.ndarray | None, results: list, elapsed_ms: float):
        self._ocr_results = results
        if annotated is not None:
            self._show_image(annotated)
            h, w = annotated.shape[:2]
            status = f"{self._capture_source} | {w}×{h} | {len(results)} 個文字區塊 | {elapsed_ms:.0f} ms"
        else:
            status = f"{len(results)} 個文字區塊 | {elapsed_ms:.0f} ms"
        self._status_bar.showMessage(status)

    def _show_image(self, img: np.ndarray):
        img = np.ascontiguousarray(img)
        h, w, ch = img.shape
        bytes_per_line = ch * w
        q_img = QImage(
            img.tobytes(), w, h, bytes_per_line, QImage.Format.Format_RGB888
        ).rgbSwapped()
        pixmap = QPixmap.fromImage(q_img)
        scaled = pixmap.scaled(
            self._image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
