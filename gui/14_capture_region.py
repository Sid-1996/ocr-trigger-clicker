import base64
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QBuffer, QByteArray, QEventLoop, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

if hasattr(sys, "_MEIPASS"):
    _base = Path(sys._MEIPASS)
else:
    _base = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_base))

from _loader import load_sibling  # noqa: E402


class CaptureRegionSelector(QWidget):
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._start = QPoint()
        self._end = QPoint()
        self._selecting = False
        self._result: Optional[dict] = None
        self._bg_pixmaps: list[tuple[QPixmap, QRect]] = []

        all_geometry = QRect()
        for screen in QApplication.screens():
            all_geometry = all_geometry.united(screen.geometry())
        self.setGeometry(all_geometry)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        for screen in QApplication.screens():
            geom = screen.geometry()
            pixmap = screen.grabWindow(0, 0, 0, geom.width(), geom.height())
            self._bg_pixmaps.append((pixmap, geom))

    def _get_rect(self) -> Optional[QRect]:
        if not self._selecting and self._start == self._end:
            return None
        x = min(self._start.x(), self._end.x())
        y = min(self._start.y(), self._end.y())
        w = abs(self._end.x() - self._start.x())
        h = abs(self._end.y() - self._start.y())
        if w < 10 or h < 10:
            return None
        return QRect(x, y, w, h)

    def _set_result_from_rect(self):
        rect = self._get_rect()
        if rect:
            self._result = {
                "x": rect.x(),
                "y": rect.y(),
                "w": rect.width(),
                "h": rect.height(),
            }

    def paintEvent(self, event):
        painter = QPainter(self)
        for pixmap, geom in self._bg_pixmaps:
            painter.drawPixmap(geom.topLeft(), pixmap)

        overlay = QColor(0, 0, 0, 120)
        painter.fillRect(self.rect(), overlay)

        rect = self._get_rect()
        if rect:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            for pixmap, geom in self._bg_pixmaps:
                src_rect = rect.intersected(geom)
                if src_rect.isValid():
                    dst_rect = src_rect.translated(-geom.topLeft())
                    painter.drawPixmap(src_rect, pixmap, dst_rect)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            pen = QPen(Qt.GlobalColor.white, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

        painter.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(16)
        painter.setFont(font)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        dim = f"  |  尺寸: {rect.width()}×{rect.height()}" if rect else ""
        painter.drawText(
            16,
            self.rect().height() - 32,
            f"拖拉選取截圖範本{dim}  |  放開滑鼠自動確認  |  Esc 取消",
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._end = self._start
            self._selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self._selecting:
            self._end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._end = event.position().toPoint()
            self._selecting = False
            self.update()
            self._set_result_from_rect()
            if self._result:
                self.finished.emit()
                self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._result = None
            self.finished.emit()
            self.close()


def _extract_template_b64(selector: CaptureRegionSelector, rect: dict) -> Optional[str]:
    x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
    cx, cy = x + w // 2, y + h // 2
    for pixmap, geom in selector._bg_pixmaps:
        if geom.x() <= cx < geom.x() + geom.width() and geom.y() <= cy < geom.y() + geom.height():
            ox, oy = x - geom.x(), y - geom.y()
            cropped = pixmap.copy(ox, oy, w, h)
            if cropped.isNull() or cropped.width() < 1:
                return None
            img = cropped.toImage()
            if img.isNull():
                return None
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QBuffer.OpenModeFlag.WriteOnly)
            if not img.save(buf, "PNG"):
                return None
            return base64.b64encode(ba.data()).decode("ascii")
    return None


def capture_region(parent_window=None, task_path="", window_title="") -> Optional[dict]:
    if parent_window:
        parent_window.showMinimized()
        QApplication.processEvents()

    selector = CaptureRegionSelector()
    selector.setFocus()
    loop = QEventLoop()
    selector.finished.connect(loop.quit)
    selector.show()
    selector.activateWindow()
    selector.raise_()
    loop.exec()

    if parent_window:
        import time

        time.sleep(0.1)
        parent_window.showNormal()
        parent_window.raise_()
        parent_window.activateWindow()
        parent_window.setWindowState(parent_window.windowState() & ~Qt.WindowState.WindowMinimized)
        QApplication.processEvents()

    result = selector._result
    if result and window_title:
        b64 = _extract_template_b64(selector, result)
        if b64:
            result["template_b64"] = b64
        if task_path:
            _screenshot_mod = load_sibling("screenshot", "core/01_screenshot.py")
            _rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
            rect = _screenshot_mod.get_window_rect(window_title)
            if rect:
                chrome = _screenshot_mod.get_window_client_offset(window_title) or (0, 0)
                _rule_mod.set_capture_size(task_path, rect["w"] - chrome[0], rect["h"] - chrome[1])
    selector.close()
    selector.deleteLater()
    return result


if __name__ == "__main__":
    app = QApplication(sys.argv)
    result = capture_region()
    if result:
        print(f"選取區域：x={result['x']} y={result['y']} w={result['w']} h={result['h']}")
    else:
        print("已取消")
    sys.exit(0)
