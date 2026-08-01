"""Background click position picker: shows target window screenshot inside a dialog.
User clicks on the screenshot to select position, coordinates returned as client-relative ratio (0~1).
"""

from typing import Optional

import numpy as np
from PyQt6.QtCore import QEventLoop, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QVBoxLayout,
)

from i18n import T


class _ClickImageLabel(QLabel):
    """Label that displays the target window screenshot and allows click position selection."""

    finished = pyqtSignal()

    def __init__(self, pixmap: QPixmap, img_w: int, img_h: int):
        super().__init__()
        self._pixmap = pixmap
        self._img_w = img_w
        self._img_h = img_h
        self._result: Optional[tuple[int, int]] = None

        self.setMinimumSize(320, 240)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def _display_rect(self) -> QRect:
        avail = self.contentsRect()
        scaled = self._pixmap.scaled(
            avail, Qt.AspectRatioMode.KeepAspectRatio, Qt.SmoothTransformation
        )
        x = avail.x() + (avail.width() - scaled.width()) // 2
        y = avail.y() + (avail.height() - scaled.height()) // 2
        return QRect(x, y, scaled.width(), scaled.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        disp = self._display_rect()
        painter.drawPixmap(disp, self._pixmap)

        painter.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(14)
        painter.setFont(font)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawText(8, self.rect().height() - 12, T("overlay.click_instruction"))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            disp = self._display_rect()
            if disp.width() <= 0 or disp.height() <= 0:
                return
            img_x = int((pos.x() - disp.x()) * self._img_w / disp.width())
            img_y = int((pos.y() - disp.y()) * self._img_h / disp.height())
            img_x = max(0, min(img_x, self._img_w - 1))
            img_y = max(0, min(img_y, self._img_h - 1))
            self._result = (img_x, img_y)
            self.finished.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._result = None
            self.finished.emit()

    def get_result(self) -> Optional[tuple[int, int]]:
        return self._result


def _np_to_qpix(img: np.ndarray) -> QPixmap:
    h, w = img.shape[:2]
    if img.ndim == 3 and img.shape[2] == 3:
        qimg = QImage(img.data, w, h, 3 * w, QImage.Format.Format_RGB888).rgbSwapped()
    elif img.ndim == 3 and img.shape[2] == 4:
        qimg = QImage(img.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).rgbSwapped()
    else:
        gray = QImage(img.data, w, h, w, QImage.Format.Format_Grayscale8)
        return QPixmap.fromImage(gray)
    return QPixmap.fromImage(qimg)


def pick_click_position_bg(
    parent,
    img: np.ndarray,
    window_title: str = "",
) -> Optional[tuple[int, int]]:
    """Show background click position picker dialog.

    Args:
        parent: Parent QWidget (main window).
        img: BGR numpy image from PrintWindow (client area).
        window_title: For display in dialog title.

    Returns:
        Tuple (x, y) in client-area pixels, or None if cancelled.
    """
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    pixmap = _np_to_qpix(img)
    label = _ClickImageLabel(pixmap, w, h)
    label.setMinimumSize(max(320, w // 2), max(240, h // 2))

    dlg = QDialog(parent)
    dlg.setWindowTitle(
        T("bg_picker.title", title=window_title) if window_title else T("bg_picker.title_no_title")
    )
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(label)

    loop = QEventLoop()
    label.finished.connect(loop.quit)
    dlg.finished.connect(loop.quit)
    dlg.resize(max(400, w // 2 + 40), max(320, h // 2 + 40))
    dlg.show()
    loop.exec()

    result = label.get_result()
    dlg.close()
    dlg.deleteLater()
    return result


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    dummy = np.zeros((600, 800, 3), dtype=np.uint8)
    dummy[100:300, 200:500] = (255, 128, 64)
    r = pick_click_position_bg(None, dummy, "Test Window")
    if r:
        print(f"Position: x={r[0]} y={r[1]}")
    else:
        print("Cancelled")
    sys.exit(0)
