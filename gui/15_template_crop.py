"""內嵌模板圖片修剪對話框（match_image 步驟「修剪模板」用）。

在應用程式內對已存 base64 模板做裁切：原圖放大顯示、拖曳選框、中央十字
標記（= 點擊落點提示）、「還原」重置回整張原圖。只有按「確認」才把裁切
結果回傳給呼叫端，取消／Esc 回傳 None（呼叫端不寫入任何值）。
"""

import base64
from typing import Optional

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from _loader import load_sibling
from i18n import T

_tmpl = load_sibling("template_matching", "core/11_template_matching.py")
crop_template_b64 = _tmpl.crop_template_b64
MIN_TEMPLATE_SIDE = _tmpl.MIN_TEMPLATE_SIDE


class _CropView(QWidget):
    """顯示模板原圖並讓使用者拖曳選取保留範圍（選取框以原圖像素座標儲存）。"""

    selection_changed = pyqtSignal()

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._sel = QRect(0, 0, pixmap.width(), pixmap.height())
        self._drag_anchor: QPoint | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def reset(self):
        """「還原」：選取框重置回整張原圖。"""
        if self._pixmap.isNull():
            return
        self._sel = QRect(0, 0, self._pixmap.width(), self._pixmap.height())
        self._drag_anchor = None
        self.update()
        self.selection_changed.emit()

    def selection_pixels(self) -> tuple[int, int, int, int]:
        s = self._sel
        return s.x(), s.y(), s.width(), s.height()

    def _fit_rect(self) -> QRect:
        """原圖等比縮放後在 widget 內的實際繪製矩形（維持長寬比）。"""
        if self._pixmap.isNull() or self._pixmap.width() <= 0 or self._pixmap.height() <= 0:
            return QRect()
        avail = self.rect()
        scale = min(avail.width() / self._pixmap.width(), avail.height() / self._pixmap.height())
        w = max(1, int(self._pixmap.width() * scale))
        h = max(1, int(self._pixmap.height() * scale))
        x = avail.x() + (avail.width() - w) // 2
        y = avail.y() + (avail.height() - h) // 2
        return QRect(x, y, w, h)

    def _to_image(self, pt: QPoint) -> QPoint:
        """widget 座標 → 原圖像素座標（clamp 到圖內）。"""
        fit = self._fit_rect()
        if fit.isValid():
            ix = (pt.x() - fit.x()) * self._pixmap.width() / fit.width()
            iy = (pt.y() - fit.y()) * self._pixmap.height() / fit.height()
            return QPoint(
                max(0, min(self._pixmap.width() - 1, int(ix))),
                max(0, min(self._pixmap.height() - 1, int(iy))),
            )
        return QPoint(0, 0)

    @staticmethod
    def _normalize(a: QPoint, b: QPoint) -> QRect:
        return QRect(min(a.x(), b.x()), min(a.y(), b.y()), abs(b.x() - a.x()), abs(b.y() - a.y()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_anchor = self._to_image(event.position().toPoint())
            self._sel = self._normalize(self._drag_anchor, self._drag_anchor)
            self.update()
            self.selection_changed.emit()

    def mouseMoveEvent(self, event):
        if self._drag_anchor is not None:
            self._sel = self._normalize(
                self._drag_anchor, self._to_image(event.position().toPoint())
            )
            self.update()
            self.selection_changed.emit()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_anchor is not None:
            self._sel = self._normalize(
                self._drag_anchor, self._to_image(event.position().toPoint())
            )
            self._drag_anchor = None
            self.update()
            self.selection_changed.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(28, 28, 30))
        fit = self._fit_rect()
        if fit.isValid():
            painter.drawPixmap(fit, self._pixmap)
            img_w, img_h = self._pixmap.width(), self._pixmap.height()
            rx = fit.x() + int(self._sel.x() * fit.width() / img_w)
            ry = fit.y() + int(self._sel.y() * fit.height() / img_h)
            rw = max(1, int(self._sel.width() * fit.width() / img_w))
            rh = max(1, int(self._sel.height() * fit.height() / img_h))
            painter.setPen(QPen(QColor(66, 165, 245), 2))
            painter.drawRect(QRect(rx, ry, rw, rh))
            cx = fit.x() + fit.width() // 2
            cy = fit.y() + fit.height() // 2
            painter.setPen(QPen(QColor(255, 255, 255, 170), 1, Qt.PenStyle.DashLine))
            painter.drawLine(cx - 12, cy, cx + 12, cy)
            painter.drawLine(cx, cy - 12, cx, cy + 12)
        painter.end()


class _TemplateCropDialog(QDialog):
    def __init__(self, b64: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("template_crop.title"))
        self.setModal(True)
        self._b64 = b64
        self._result: Optional[str] = None

        pix = QPixmap()
        pix.loadFromData(base64.b64decode(b64))
        self._view = _CropView(pix, self)
        self._view.selection_changed.connect(self._update_size_label)

        self._size_label = QLabel()
        self._size_label.setStyleSheet("color: #888;")
        self._hint_label = QLabel("")
        self._hint_label.setStyleSheet("color: #e67e22; font-weight: bold;")

        self._restore_btn = QPushButton(T("template_crop.restore"))
        self._restore_btn.clicked.connect(self._view.reset)
        self._ok_btn = QPushButton(T("template_crop.ok"))
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._apply)
        self._cancel_btn = QPushButton(T("template_crop.cancel"))
        self._cancel_btn.clicked.connect(self.reject)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel(T("template_crop.instruction")))
        top_row.addStretch()
        top_row.addWidget(self._size_label)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._restore_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._ok_btn)
        btn_row.addWidget(self._cancel_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self._view, 1)
        layout.addWidget(self._hint_label)
        layout.addLayout(btn_row)

        self._update_size_label()

    def _update_size_label(self):
        _, _, w, h = self._view.selection_pixels()
        self._size_label.setText(T("template_crop.size", w=w, h=h))

    def _apply(self):
        x, y, w, h = self._view.selection_pixels()
        if w < MIN_TEMPLATE_SIDE or h < MIN_TEMPLATE_SIDE:
            self._hint_label.setText(T("template_crop.too_small", min=MIN_TEMPLATE_SIDE))
            return
        out = crop_template_b64(self._b64, x, y, w, h)
        if out is None:
            self._hint_label.setText(T("template_crop.too_small", min=MIN_TEMPLATE_SIDE))
            return
        self._result = out
        self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


def trim_template_dialog(parent=None, b64: str = "") -> Optional[str]:
    """開模態對話框讓使用者修剪內嵌模板，確認後回傳新 b64；取消／無效回 None。"""
    if not b64:
        return None
    try:
        base64.b64decode(b64, validate=True)
    except (ValueError, TypeError):
        return None
    dlg = _TemplateCropDialog(b64, parent)
    dlg.exec()
    return dlg._result
