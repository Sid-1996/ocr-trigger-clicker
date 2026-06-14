import ctypes
import threading
import time

import numpy as np
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QMainWindow

from _loader import load_sibling

_screenshot = load_sibling("screenshot", "01_screenshot.py")
_ocr = load_sibling("ocr_engine", "02_ocr_engine.py")

capture = _screenshot.capture
capture_window_content = _screenshot.capture_window_content
get_window_rect = _screenshot.get_window_rect
recognize = _ocr.recognize


class _OcrSignals(QObject):
    ocr_done = pyqtSignal(list, float)


class OcrDebugWindow(QMainWindow):
    def __init__(self, window_title: str, parent=None):
        super().__init__(parent)
        self._window_title = window_title
        self._ocr_busy = False
        self._ocr_results: list = []
        self._capture_source = ""
        self._status_text = "就緒"
        self._signals = _OcrSignals()
        self._signals.ocr_done.connect(self._on_ocr_done)

        self.setWindowTitle(f"OCR 效能診斷 — {window_title}")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._frame_timer = QTimer()
        self._frame_timer.timeout.connect(self._tick)

        self._ocr_timer = QTimer()
        self._ocr_timer.timeout.connect(self._schedule_ocr)

    def start(self, interval_ms: int = 1500):
        self._frame_timer.start(200)
        self._ocr_timer.start(interval_ms)
        self._tick()
        self._schedule_ocr()

    def stop(self):
        self._frame_timer.stop()
        self._ocr_timer.stop()
        self._ocr_busy = False

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._set_mouse_transparent()

    def _set_mouse_transparent(self):
        try:
            hwnd = int(self.winId())
            if not hwnd:
                return
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            )
        except Exception:
            pass

    def _sync_geometry(self):
        rect = get_window_rect(self._window_title)
        if rect is not None:
            self.setGeometry(rect["x"], rect["y"], rect["w"], rect["h"])
            return True
        return False

    def _tick(self):
        if not self._sync_geometry():
            self._status_text = f"找不到視窗「{self._window_title}」"
            self.update()

    def _schedule_ocr(self):
        if self._ocr_busy:
            return
        rect = get_window_rect(self._window_title)
        if rect is None:
            return
        raw = capture_window_content(self._window_title)
        src = "PrintWindow"
        if raw is None:
            raw = capture(self._window_title)
            src = "mss"
        self._capture_source = src
        if raw is None:
            return
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
        self._status_text = f"[{self._capture_source}] {len(results)} 個區塊 | {elapsed_ms:.0f} ms"
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        BOX_COLOR = QColor(0, 220, 255, 220)
        BG_COLOR = QColor(0, 0, 0, 180)
        TEXT_COLOR = QColor(255, 255, 255)
        STATUS_COLOR = QColor(0, 220, 255)
        FONT = QFont("Consolas", 10)
        painter.setFont(FONT)
        fm = painter.fontMetrics()
        th = fm.height()

        painter.setPen(QPen(BOX_COLOR, 2))
        for r in self._ocr_results:
            painter.drawRect(r.x, r.y, r.w, r.h)

        for r in self._ocr_results:
            if r.confidence < 0.7:
                continue
            label = f"{r.text}  {r.confidence:.2f}"
            tw = fm.horizontalAdvance(label)
            label_y = r.y + r.h + th + 2
            if label_y + 4 > self.height():
                label_y = r.y - 4
            bg_y = label_y - th
            painter.fillRect(r.x, bg_y, tw + 8, th + 4, BG_COLOR)
            painter.setPen(TEXT_COLOR)
            painter.drawText(r.x + 4, label_y, label)

        if self._status_text:
            status = self._status_text + "  |  ESC 關閉"
            sw = fm.horizontalAdvance(status)
            painter.fillRect(4, self.height() - th - 12, sw + 12, th + 8, BG_COLOR)
            painter.setPen(STATUS_COLOR)
            painter.setFont(QFont("Consolas", 11))
            painter.drawText(10, self.height() - 6, status)

        painter.end()
