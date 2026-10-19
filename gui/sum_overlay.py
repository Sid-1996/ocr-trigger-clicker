"""數字加總結果浮層：置頂、點擊穿透、不搶焦點，5 秒後淡出。"""

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

_HIDE_MS = 5000
_FADE_MS = 300
_GAP = 6


class SumOverlay(QWidget):
    def __init__(self):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._label = QLabel(self)
        self._label.setStyleSheet(
            "background: rgba(20, 20, 20, 210); color: #FFFFFF;"
            "border-radius: 6px; padding: 6px 10px; font-size: 15px; font-weight: bold;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(_FADE_MS)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.InQuad)
        self._fade.finished.connect(self.hide)
        self.hide()

    def show_sum(self, x: int, y: int, w: int, h: int, text: str) -> None:
        self._fade.stop()
        self._timer.stop()
        self.setWindowOpacity(1.0)
        self._label.setText(text)
        self.adjustSize()

        geo = self._screen_geometry(QPoint(x, y))
        px = min(max(x, geo.left()), max(geo.left(), geo.right() - self.width() + 1))
        py = y - self.height() - _GAP
        if py < geo.top():
            py = y + h + _GAP
        py = min(max(py, geo.top()), max(geo.top(), geo.bottom() - self.height() + 1))
        self.move(px, py)
        self.show()
        self.raise_()
        self._timer.start(_HIDE_MS)

    def hide_now(self) -> None:
        self._timer.stop()
        self._fade.stop()
        self.hide()

    def _fade_out(self) -> None:
        self._fade.start()

    @staticmethod
    def _screen_geometry(point: QPoint):
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    overlay = SumOverlay()
    overlay.show_sum(300, 400, 200, 60, "合計 55（3 個數字）")
    QTimer.singleShot(800, app.quit)
    app.exec()
    print("  [OK] SumOverlay shown")
