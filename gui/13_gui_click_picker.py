import sys
from typing import Optional

from PyQt6.QtCore import QEventLoop, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QApplication, QWidget


class ClickPicker(QWidget):
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._result: Optional[tuple[int, int]] = None

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

    def paintEvent(self, event):
        painter = QPainter(self)
        overlay = QColor(0, 0, 0, 1)
        painter.fillRect(self.rect(), overlay)

        painter.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(16)
        painter.setFont(font)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawText(16, 36, "請在目標位置點擊  |  Esc 取消")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.globalPosition().toPoint()
            dpr = self.devicePixelRatioF()
            self._result = (int(pos.x() * dpr), int(pos.y() * dpr))
            self.finished.emit()
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._result = None
            self.finished.emit()
            self.close()

    def closeEvent(self, event):
        super().closeEvent(event)


def pick_click_position(parent_window=None) -> Optional[tuple[int, int]]:
    if parent_window:
        parent_window.showMinimized()
        QApplication.processEvents()

    picker = ClickPicker()
    picker.setFocus()
    loop = QEventLoop()
    picker.finished.connect(loop.quit)
    picker.show()
    picker.activateWindow()
    picker.raise_()
    loop.exec()

    if parent_window:
        import time

        time.sleep(0.1)
        parent_window.showNormal()
        parent_window.raise_()
        parent_window.activateWindow()
        parent_window.setWindowState(parent_window.windowState() & ~Qt.WindowState.WindowMinimized)
        QApplication.processEvents()

    result = picker._result
    picker.close()
    picker.deleteLater()
    return result


if __name__ == "__main__":
    app = QApplication(sys.argv)
    result = pick_click_position()
    if result:
        print(f"點擊位置：x={result[0]} y={result[1]}")
    else:
        print("已取消")
    sys.exit(0)
