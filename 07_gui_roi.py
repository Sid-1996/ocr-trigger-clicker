import sys
from typing import Optional

from PyQt6.QtCore import QEventLoop, QPoint, QRect, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget


class ROISelector(QWidget):
    def __init__(self):
        super().__init__()
        self._start = QPoint()
        self._end = QPoint()
        self._selecting = False
        self._finished = False
        self._result: Optional[dict] = None

        geometry = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(geometry)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        screen = QApplication.primaryScreen()
        self._bg_pixmap = screen.grabWindow(
            0, geometry.x(), geometry.y(), geometry.width(), geometry.height()
        )

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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._bg_pixmap)

        overlay = QColor(0, 0, 0, 120)
        painter.fillRect(self.rect(), overlay)

        rect = self._get_rect()
        if rect:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawPixmap(rect, self._bg_pixmap, rect)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            pen = QPen(Qt.GlobalColor.white, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

            size = 8
            corners = [
                (rect.x(), rect.y()),
                (rect.x() + rect.width() - size, rect.y()),
                (rect.x(), rect.y() + rect.height() - size),
                (rect.x() + rect.width() - size, rect.y() + rect.height() - size),
            ]
            painter.setBrush(QBrush(Qt.GlobalColor.white))
            painter.setPen(Qt.PenStyle.NoPen)
            for cx, cy in corners:
                painter.drawRect(cx, cy, size, size)

        painter.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(16)
        painter.setFont(font)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        dim = f"  |  尺寸: {rect.width()}×{rect.height()}" if rect else ""
        painter.drawText(
            16, self.rect().height() - 32, f"拖拉選取偵測區域{dim}  |  Enter 確認  |  Esc 取消"
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

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            rect = self._get_rect()
            if rect:
                self._result = {
                    "x": rect.x(),
                    "y": rect.y(),
                    "w": rect.width(),
                    "h": rect.height(),
                }
                self._finished = True
                self.close()
        elif event.key() == Qt.Key.Key_Escape:
            self._result = None
            self._finished = True
            self.close()

    def closeEvent(self, event):
        self._finished = True
        super().closeEvent(event)


def select_roi(parent_window=None) -> Optional[dict]:
    if parent_window:
        parent_window.showMinimized()
        QApplication.processEvents()

    selector = ROISelector()
    selector.show()

    loop = QEventLoop()
    selector.destroyed.connect(loop.quit)
    loop.exec()

    if parent_window:
        import time

        time.sleep(0.1)
        parent_window.showNormal()
        parent_window.raise_()
        parent_window.activateWindow()
        parent_window.setWindowState(
            parent_window.windowState() & ~Qt.WindowState.WindowMinimized
        )

    result = selector._result
    selector.deleteLater()
    return result


if __name__ == "__main__":
    app = QApplication(sys.argv)
    result = select_roi()
    if result:
        print(f"選取區域：x={result['x']} y={result['y']} w={result['w']} h={result['h']}")
    else:
        print("已取消")
    sys.exit(0)
