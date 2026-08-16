"""內嵌模板圖片修剪對話框（match_image 步驟「修剪模板」用）。

在應用程式內對已存 base64 模板做裁切：原圖放大顯示、中央十字標記（=
點擊落點提示）、圖片四邊的雙向箭頭按鈕（貼圖放置，箭頭指向圖片中心＝
往內剪，反向＝往外還原，每格 1px）、底部精確數值行、「還原」重置回整張
原圖。互動一律經按鈕／數值輸入，不做拖曳選框——非每位使用者都能一次框選
正確。只有按「確認」才把裁切結果回傳給呼叫端，取消／Esc 回傳 None（呼叫
端不寫入任何值）。
"""

import base64
from typing import Optional

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from _loader import load_sibling
from i18n import T

_tmpl = load_sibling("template_matching", "core/11_template_matching.py")
crop_template_b64 = _tmpl.crop_template_b64
MIN_TEMPLATE_SIDE = _tmpl.MIN_TEMPLATE_SIDE
margins_from_rect = _tmpl.margins_from_rect
rect_from_margins = _tmpl.rect_from_margins
clamp_margins = _tmpl.clamp_margins


class _CropView(QWidget):
    """顯示模板原圖與目前保留範圍（選取框以原圖像素座標儲存）。

    純視覺呈現，不處理滑鼠互動——選取範圍一律由步進器驅動。
    """

    selection_changed = pyqtSignal()

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._sel = QRect(0, 0, pixmap.width(), pixmap.height())
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def image_size(self) -> tuple[int, int]:
        return self._pixmap.width(), self._pixmap.height()

    def reset(self):
        """「還原」：選取框重置回整張原圖。"""
        if self._pixmap.isNull():
            return
        self._sel = QRect(0, 0, self._pixmap.width(), self._pixmap.height())
        self.update()
        self.selection_changed.emit()

    def set_selection(self, x: int, y: int, w: int, h: int):
        """設定選取框（防呆 clamp：落在圖內、寬高 ≥ 1），再通知更新。"""
        iw, ih = self._pixmap.width(), self._pixmap.height()
        x = max(0, min(iw, x))
        y = max(0, min(ih, y))
        w = max(1, min(iw - x, w))
        h = max(1, min(ih - y, h))
        self._sel = QRect(x, y, w, h)
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
        self._view.selection_changed.connect(self._sync_steppers_from_view)

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

        # 四邊空間化箭頭按鈕：上/下橫排、左/右直排，貼圖放置（箭頭指向圖片中心＝往內剪）
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        top_in = self._make_arrow_btn("top", 1, "↓", "template_crop.trim_in")
        top_out = self._make_arrow_btn("top", -1, "↑", "template_crop.expand_out")
        bottom_in = self._make_arrow_btn("bottom", 1, "↑", "template_crop.trim_in")
        bottom_out = self._make_arrow_btn("bottom", -1, "↓", "template_crop.expand_out")
        left_in = self._make_arrow_btn("left", 1, "→", "template_crop.trim_in")
        left_out = self._make_arrow_btn("left", -1, "←", "template_crop.expand_out")
        right_in = self._make_arrow_btn("right", 1, "←", "template_crop.trim_in")
        right_out = self._make_arrow_btn("right", -1, "→", "template_crop.expand_out")

        top_bar = QHBoxLayout()
        top_bar.addStretch()
        top_bar.addWidget(top_in)
        top_bar.addWidget(top_out)
        top_bar.addStretch()
        grid.addLayout(top_bar, 0, 1)

        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        bottom_bar.addWidget(bottom_in)
        bottom_bar.addWidget(bottom_out)
        bottom_bar.addStretch()
        grid.addLayout(bottom_bar, 2, 1)

        left_col = QVBoxLayout()
        left_col.addStretch()
        left_col.addWidget(left_in)
        left_col.addWidget(left_out)
        left_col.addStretch()
        grid.addLayout(left_col, 1, 0)

        right_col = QVBoxLayout()
        right_col.addStretch()
        right_col.addWidget(right_in)
        right_col.addWidget(right_out)
        right_col.addStretch()
        grid.addLayout(right_col, 1, 2)

        grid.addWidget(self._view, 1, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(1, 1)

        # 底部精確數值行：上/下/左/右 四個 spinbox，可直接輸入 px
        margin_box = QGroupBox(T("template_crop.margins"))
        margin_bar = QHBoxLayout(margin_box)
        margin_bar.setSpacing(8)
        self._spins: dict[str, QSpinBox] = {}
        for side in ("top", "bottom", "left", "right"):
            margin_bar.addWidget(QLabel(T(f"template_crop.margin_{side}")))
            spin = QSpinBox()
            spin.setRange(0, 0)
            spin.setSingleStep(1)
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.setSuffix(" px")
            spin.valueChanged.connect(self._on_margin_changed)
            margin_bar.addWidget(spin)
            self._spins[side] = spin
        margin_bar.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._restore_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._ok_btn)
        btn_row.addWidget(self._cancel_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addLayout(grid, 1)
        layout.addWidget(margin_box)
        layout.addWidget(self._hint_label)
        layout.addLayout(btn_row)

        self._sync_steppers_from_view()
        self._update_size_label()

    def _make_arrow_btn(self, side: str, delta: int, arrow: str, tip_key: str) -> QToolButton:
        btn = QToolButton()
        btn.setText(arrow)
        btn.setFixedSize(30, 30)
        btn.setToolTip(T(tip_key))
        btn.clicked.connect(lambda _checked, s=side, d=delta: self._adjust_margin(s, d))
        return btn

    def _adjust_margin(self, side: str, delta: int):
        """點箭頭：該側邊距 ±1px（Qt 會 clamp 到範圍，min 0、max 交叉限制）。"""
        spin = self._spins[side]
        spin.setValue(spin.value() + delta)

    def _on_margin_changed(self):
        """步進器任一值變動 → clamp 四邊距 → 更新選取框（迴圈由 sync 攔截）。"""
        iw, ih = self._view.image_size()
        cur = (
            self._spins["left"].value(),
            self._spins["top"].value(),
            self._spins["right"].value(),
            self._spins["bottom"].value(),
        )
        x, y, w, h = rect_from_margins(clamp_margins(cur, iw, ih, MIN_TEMPLATE_SIDE), iw, ih)
        self._view.set_selection(x, y, w, h)

    def _sync_steppers_from_view(self):
        """選取框變動 → 反推四邊距更新步進器（blockSignals 防回圈）。"""
        x, y, w, h = self._view.selection_pixels()
        iw, ih = self._view.image_size()
        left, top, right, bottom = margins_from_rect(x, y, w, h, iw, ih)
        maxima = {
            "left": max(0, iw - MIN_TEMPLATE_SIDE - right),
            "right": max(0, iw - MIN_TEMPLATE_SIDE - left),
            "top": max(0, ih - MIN_TEMPLATE_SIDE - bottom),
            "bottom": max(0, ih - MIN_TEMPLATE_SIDE - top),
        }
        values = {"left": left, "top": top, "right": right, "bottom": bottom}
        for side, spin in self._spins.items():
            spin.blockSignals(True)
            spin.setMaximum(maxima[side])
            spin.setValue(values[side])
            spin.blockSignals(False)

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
