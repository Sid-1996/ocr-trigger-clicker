"""數字加總結果浮層：置頂、點擊穿透、不搶焦點，5 秒後淡出。"""

import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QWindow
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

_HIDE_MS = 5000
_FADE_MS = 300
_GAP = 6


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _monitor_origin(hwnd: int | None) -> tuple[int, int]:
    """目標視窗所在螢幕的物理原點；取不到時回 (0, 0)。"""
    if not hwnd:
        return 0, 0
    try:
        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        hmon = user32.MonitorFromWindow(ctypes.c_void_p(int(hwnd)), 2)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return int(info.rcMonitor.left), int(info.rcMonitor.top)
    except Exception:
        pass
    return 0, 0


def _physical_to_logical(
    x: int,
    y: int,
    w: int,
    h: int,
    screen_left: int,
    screen_top: int,
    dpr: float,
    monitor_left: int,
    monitor_top: int,
) -> tuple[float, float, float, float]:
    """Win32 物理像素 → Qt 邏輯座標；origin 是該螢幕的物理左上角。"""
    dpr = dpr or 1.0
    return (
        screen_left + (x - monitor_left) / dpr,
        screen_top + (y - monitor_top) / dpr,
        w / dpr,
        h / dpr,
    )


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
        self._timer.timeout.connect(self.fade_out)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(_FADE_MS)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.InQuad)
        self._fade.finished.connect(self.hide)
        self.hide()

    def show_sum(self, x: int, y: int, w: int, h: int, text: str, hwnd: int | None = None) -> None:
        self._fade.stop()
        self._timer.stop()
        self.setWindowOpacity(1.0)
        self._label.setText(text)
        self.adjustSize()

        screen = self._screen_for(hwnd, QPoint(x, y))
        if screen is None:
            return
        sgeo = screen.geometry()
        geo = screen.availableGeometry()
        ox, oy = _monitor_origin(hwnd)
        lx, ly, lw, lh = _physical_to_logical(
            x,
            y,
            w,
            h,
            sgeo.left(),
            sgeo.top(),
            screen.devicePixelRatio(),
            ox,
            oy,
        )

        px = min(max(lx, geo.left()), max(geo.left(), geo.right() - self.width() + 1))
        py = ly - self.height() - _GAP
        if py < geo.top():
            py = ly + lh + _GAP
        py = min(max(py, geo.top()), max(geo.top(), geo.bottom() - self.height() + 1))
        self.move(int(px), int(py))
        self.show()
        self.raise_()
        self._timer.start(_HIDE_MS)

    def hide_now(self) -> None:
        self._timer.stop()
        self._fade.stop()
        self.hide()

    def fade_out(self) -> None:
        """前置條件失效時立刻淡出，不必等到 5 秒計時。"""
        self._timer.stop()
        if not self.isVisible():
            return
        self._fade.stop()
        self._fade.start()

    @staticmethod
    def _screen_for(hwnd: int | None, point: QPoint):
        if hwnd:
            try:
                window = QWindow.fromWinId(int(hwnd))
                if window is not None:
                    screen = window.screen()
                    window.deleteLater()
                    if screen is not None:
                        return screen
            except Exception:
                pass
        return QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    overlay = SumOverlay()
    overlay.show_sum(300, 400, 200, 60, "合計 55（3 個數字）")
    QTimer.singleShot(800, app.quit)
    app.exec()
    print("  [OK] SumOverlay shown")
