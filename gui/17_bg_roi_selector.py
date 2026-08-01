"""Background ROI selector: shows target window screenshot inside a dialog.
User drags on the screenshot to select ROI, coordinates returned as client-relative ratio (0~1).
"""

from typing import Optional

import numpy as np
from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QVBoxLayout,
)

from i18n import T


class _RoiImageLabel(QLabel):
    """Label that displays the target window screenshot and allows ROI selection."""

    finished = pyqtSignal()

    def __init__(self, pixmap: QPixmap, img_w: int, img_h: int):
        super().__init__()
        self._pixmap = pixmap
        self._img_w = img_w
        self._img_h = img_h
        self._start = QPoint()
        self._end = QPoint()
        self._selecting = False
        self._result: Optional[dict] = None

        self.setMinimumSize(320, 240)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def _display_rect(self) -> QRect:
        """The rect where the image is actually drawn within the label."""
        avail = self.contentsRect()
        scaled = self._pixmap.scaled(
            avail, Qt.AspectRatioMode.KeepAspectRatio, Qt.SmoothTransformation
        )
        x = avail.x() + (avail.width() - scaled.width()) // 2
        y = avail.y() + (avail.height() - scaled.height()) // 2
        return QRect(x, y, scaled.width(), scaled.height())

    def _get_selection_rect(self) -> Optional[QRect]:
        if not self._selecting and self._start == self._end:
            return None
        x = min(self._start.x(), self._end.x())
        y = min(self._start.y(), self._end.y())
        w = abs(self._end.x() - self._start.x())
        h = abs(self._end.y() - self._start.y())
        if w < 5 or h < 5:
            return None
        disp = self._display_rect()
        sel = QRect(x, y, w, h).intersected(disp)
        return sel if sel.isValid() else None

    def paintEvent(self, event):
        painter = QPainter(self)
        disp = self._display_rect()
        painter.drawPixmap(disp, self._pixmap)

        rect = self._get_selection_rect()
        if rect:
            overlay = QColor(0, 0, 0, 120)
            painter.fillRect(self.rect(), overlay)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawPixmap(rect, self._pixmap, rect)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(Qt.GlobalColor.white, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            size = 8
            for cx, cy in [
                (rect.x(), rect.y()),
                (rect.x() + rect.width() - size, rect.y()),
                (rect.x(), rect.y() + rect.height() - size),
                (rect.x() + rect.width() - size, rect.y() + rect.height() - size),
            ]:
                painter.setBrush(QBrush(Qt.GlobalColor.white))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(cx, cy, size, size)
        else:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 80))

        painter.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(14)
        painter.setFont(font)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if rect:
            dim_w = int(rect.width() * self._img_w / disp.width()) if disp.width() > 0 else 0
            dim_h = int(rect.height() * self._img_h / disp.height()) if disp.height() > 0 else 0
            dim = f"  |  {T('overlay.roi_dimension', w=dim_w, h=dim_h)}"
            painter.drawText(8, self.rect().height() - 12, T("overlay.roi_instruction", dim=dim))
        else:
            painter.drawText(8, self.rect().height() - 12, T("overlay.roi_instruction", dim=""))

    def _set_result_from_rect(self):
        rect = self._get_selection_rect()
        if not rect:
            return
        disp = self._display_rect()
        if disp.width() <= 0 or disp.height() <= 0:
            return
        img_x = int((rect.x() - disp.x()) * self._img_w / disp.width())
        img_y = int((rect.y() - disp.y()) * self._img_h / disp.height())
        img_w = int(rect.width() * self._img_w / disp.width())
        img_h = int(rect.height() * self._img_h / disp.height())
        self._result = {
            "x": max(0, min(img_x, self._img_w)),
            "y": max(0, min(img_y, self._img_h)),
            "w": max(0, min(img_w, self._img_w - img_x)),
            "h": max(0, min(img_h, self._img_h - img_y)),
        }

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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._result = None
            self.finished.emit()

    def get_result(self) -> Optional[dict]:
        return self._result


def _np_to_qpix(img: np.ndarray) -> QPixmap:
    """Convert BGR numpy image to QPixmap."""
    h, w = img.shape[:2]
    if img.ndim == 3 and img.shape[2] == 3:
        qimg = QImage(img.data, w, h, 3 * w, QImage.Format.Format_RGB888).rgbSwapped()
    elif img.ndim == 3 and img.shape[2] == 4:
        qimg = QImage(img.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).rgbSwapped()
    else:
        gray = QImage(img.data, w, h, w, QImage.Format.Format_Grayscale8)
        return QPixmap.fromImage(gray)
    return QPixmap.fromImage(qimg)


def select_roi_bg(
    parent,
    img: np.ndarray,
    window_title: str = "",
) -> Optional[dict]:
    """Show background ROI selector dialog.

    Args:
        parent: Parent QWidget (main window).
        img: BGR numpy image from PrintWindow (client area).
        window_title: For display in dialog title.

    Returns:
        dict with keys x, y, w, h (client-area pixels) and roi_coord="client", or None if cancelled.
    """
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    pixmap = _np_to_qpix(img)
    label = _RoiImageLabel(pixmap, w, h)
    label.setMinimumSize(max(320, w // 2), max(240, h // 2))

    dlg = QDialog(parent)
    dlg.setWindowTitle(
        T("bg_roi.title", title=window_title) if window_title else T("bg_roi.title_no_title")
    )
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(label)

    from PyQt6.QtCore import QEventLoop

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
    r = select_roi_bg(None, dummy, "Test Window")
    if r:
        print(f"ROI: x={r['x']} y={r['y']} w={r['w']} h={r['h']}")
    else:
        print("Cancelled")
    sys.exit(0)
