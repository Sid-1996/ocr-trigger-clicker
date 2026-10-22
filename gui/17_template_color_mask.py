"""顏色範圍遮罩對話框（match_image 步驟「顏色範圍」用）。

使用者在模板上點選背景色（可多色）或前景色；對話框即時顯示哪些像素
會被檢查。只回傳顏色清單／容差／模式，不儲存遮罩圖。
"""

import base64
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from _loader import load_sibling
from i18n import T

_tmpl = load_sibling("template_matching", "core/11_template_matching.py")
build_color_mask = _tmpl.build_color_mask
b64_to_img = _tmpl.b64_to_img

MAX_COLORS = _tmpl.MAX_COLOR_MASK_COLORS


def suggest_background_colors(template_bgr, max_colors: int = 3) -> list[list[int]]:
    """從模板邊界挑出最常見的幾個顏色（RGB），作為去背起點。"""
    if template_bgr is None or template_bgr.size == 0:
        return []
    border = np.concatenate(
        [template_bgr[0], template_bgr[-1], template_bgr[:, 0], template_bgr[:, -1]],
        axis=0,
    )
    if border.size == 0:
        return []
    quantized = (border // 16).astype(np.int16)
    unique, inverse, counts = np.unique(quantized, axis=0, return_inverse=True, return_counts=True)
    min_count = max(1, int(len(border) * 0.05))
    result: list[list[int]] = []
    for idx in np.argsort(-counts):
        if counts[idx] < min_count:
            break
        pixels = border[inverse == idx]
        b, g, r = (int(v) for v in pixels.mean(axis=0))
        color = [r, g, b]
        if color not in result:
            result.append(color)
        if len(result) >= max_colors:
            break
    return result


class _ColorMaskView(QWidget):
    color_picked = pyqtSignal(int, int)

    def __init__(self, template_bgr, parent=None):
        super().__init__(parent)
        self._bgr = template_bgr
        self._mask = None
        self._pixmap = QPixmap()
        self.setMinimumSize(320, 240)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._rebuild()

    def _rebuild(self):
        if self._bgr is None or self._bgr.size == 0:
            self._pixmap = QPixmap()
            self.update()
            return
        rgb = cv2.cvtColor(self._bgr, cv2.COLOR_BGR2RGB)
        if self._mask is not None and (~self._mask).any():
            rgb = rgb.astype(np.float32)
            ignored = ~self._mask
            rgb[ignored] = rgb[ignored] * 0.4 + np.array((255, 0, 255), dtype=np.float32) * 0.6
            rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        rgb = np.ascontiguousarray(rgb)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(qimg)
        self.update()

    def set_mask(self, mask):
        self._mask = mask
        self._rebuild()

    def _fit_rect(self) -> QRect:
        if self._pixmap.isNull():
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
            painter.setPen(QPen(QColor(80, 80, 80), 1))
            painter.drawRect(fit.adjusted(0, 0, -1, -1))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._bgr is None:
            return
        fit = self._fit_rect()
        pos = event.position().toPoint()
        if not fit.contains(pos):
            return
        x = int((pos.x() - fit.x()) * self._bgr.shape[1] / fit.width())
        y = int((pos.y() - fit.y()) * self._bgr.shape[0] / fit.height())
        x = max(0, min(self._bgr.shape[1] - 1, x))
        y = max(0, min(self._bgr.shape[0] - 1, y))
        self.color_picked.emit(x, y)


class _TemplateColorMaskDialog(QDialog):
    def __init__(self, b64: str, current=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("color_mask.title"))
        self.setModal(True)
        self.resize(760, 520)
        self._result: Optional[dict] = None
        self._template = b64_to_img(b64)
        self._colors: list[list[int]] = []
        self._mode = "ignore"
        self._tolerance = 30
        if isinstance(current, dict):
            self._mode = "keep" if current.get("mode") == "keep" else "ignore"
            try:
                self._tolerance = max(0, min(255, int(current.get("tolerance", 30))))
            except (TypeError, ValueError):
                self._tolerance = 30
            for color in current.get("colors") or []:
                if not isinstance(color, (list, tuple)) or len(color) != 3:
                    continue
                try:
                    item = [max(0, min(255, int(v))) for v in color]
                except (TypeError, ValueError):
                    continue
                if item not in self._colors:
                    self._colors.append(item)
                if len(self._colors) >= MAX_COLORS:
                    break

        self._view = _ColorMaskView(self._template, self)
        self._view.color_picked.connect(self._add_color)

        self._hint = QLabel(T("color_mask.instruction"))
        self._hint.setWordWrap(True)

        mode_box = QGroupBox(T("color_mask.mode"))
        mode_layout = QVBoxLayout(mode_box)
        self._ignore_radio = QRadioButton(T("color_mask.mode_ignore"))
        self._keep_radio = QRadioButton(T("color_mask.mode_keep"))
        mode_layout.addWidget(self._ignore_radio)
        mode_layout.addWidget(self._keep_radio)

        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel(T("color_mask.tolerance")))
        self._tol_slider = QSlider(Qt.Orientation.Horizontal)
        self._tol_slider.setRange(0, 255)
        self._tol_slider.setValue(self._tolerance)
        self._tol_label = QLabel(str(self._tolerance))
        tol_row.addWidget(self._tol_slider, 1)
        tol_row.addWidget(self._tol_label)

        self._list = QListWidget()
        self._list.setMinimumHeight(130)
        self._auto_btn = QPushButton(T("color_mask.auto"))
        self._auto_btn.clicked.connect(self._auto_suggest)
        self._remove_btn = QPushButton(T("color_mask.remove"))
        self._remove_btn.clicked.connect(self._remove_selected)
        self._clear_btn = QPushButton(T("color_mask.clear"))
        self._clear_btn.clicked.connect(self._clear)
        self._preview_label = QLabel()
        self._preview_label.setWordWrap(True)

        right = QVBoxLayout()
        right.addWidget(mode_box)
        right.addLayout(tol_row)
        right.addWidget(QLabel(T("color_mask.selected")))
        right.addWidget(self._list, 1)
        right.addWidget(self._auto_btn)
        right.addWidget(self._remove_btn)
        right.addWidget(self._clear_btn)
        right.addWidget(self._preview_label)

        body = QHBoxLayout()
        body.addWidget(self._view, 1)
        body.addLayout(right)

        self._ok_btn = QPushButton(T("template_crop.ok"))
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._apply)
        self._cancel_btn = QPushButton(T("template_crop.cancel"))
        self._cancel_btn.clicked.connect(self.reject)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._ok_btn)
        btn_row.addWidget(self._cancel_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._hint)
        layout.addLayout(body, 1)
        layout.addLayout(btn_row)

        if self._mode == "keep":
            self._keep_radio.setChecked(True)
        else:
            self._ignore_radio.setChecked(True)
        self._tol_slider.valueChanged.connect(self._on_tolerance_changed)
        self._ignore_radio.toggled.connect(self._refresh)
        self._keep_radio.toggled.connect(self._refresh)
        self._sync_color_list()
        self._refresh()

    def _on_tolerance_changed(self, value: int):
        self._tol_label.setText(str(value))
        self._refresh()

    def _mask_dict(self):
        if not self._colors:
            return None
        return {
            "colors": [list(color) for color in self._colors],
            "tolerance": self._tol_slider.value(),
            "mode": "keep" if self._keep_radio.isChecked() else "ignore",
        }

    def _swatch(self, color: list[int]) -> QIcon:
        pix = QPixmap(16, 16)
        pix.fill(QColor(*color))
        return QIcon(pix)

    def _sync_color_list(self):
        self._list.clear()
        for color in self._colors:
            item = QListWidgetItem(
                self._swatch(color), f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"
            )
            item.setToolTip(f"R,G,B = {color[0]}, {color[1]}, {color[2]}")
            self._list.addItem(item)

    def _refresh(self):
        spec = self._mask_dict()
        mask = build_color_mask(self._template, spec) if spec is not None else None
        self._view.set_mask(mask)
        self._auto_btn.setEnabled(not self._keep_radio.isChecked())
        if spec is None:
            self._preview_label.setText(T("color_mask.no_colors"))
            self._preview_label.setStyleSheet("color:#888;")
            return
        if mask is None:
            self._preview_label.setText(T("color_mask.empty"))
            self._preview_label.setStyleSheet("color:#e67e22; font-weight:bold;")
            return
        pct = int(round(float(mask.mean()) * 100))
        if pct < 5:
            self._preview_label.setText(T("color_mask.too_little", pct=pct))
            self._preview_label.setStyleSheet("color:#e67e22; font-weight:bold;")
        else:
            self._preview_label.setText(T("color_mask.check_pct", pct=pct))
            self._preview_label.setStyleSheet("color:#4caf50; font-weight:bold;")

    def _add_color(self, x: int, y: int):
        if self._template is None:
            return
        b, g, r = (int(v) for v in self._template[y, x])
        color = [r, g, b]
        if color in self._colors:
            self._list.setCurrentRow(self._colors.index(color))
            return
        if len(self._colors) >= MAX_COLORS:
            self._preview_label.setText(T("color_mask.max_colors"))
            self._preview_label.setStyleSheet("color:#e67e22; font-weight:bold;")
            return
        self._colors.append(color)
        self._sync_color_list()
        self._list.setCurrentRow(len(self._colors) - 1)
        self._refresh()

    def _auto_suggest(self):
        for color in suggest_background_colors(self._template):
            if color not in self._colors and len(self._colors) < MAX_COLORS:
                self._colors.append(color)
        self._sync_color_list()
        self._refresh()

    def _remove_selected(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._colors):
            self._colors.pop(row)
            self._sync_color_list()
            self._refresh()

    def _clear(self):
        self._colors = []
        self._sync_color_list()
        self._refresh()

    def _apply(self):
        self._result = self._mask_dict() or {}
        self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


def color_mask_dialog(parent=None, b64: str = "", current=None) -> Optional[dict]:
    """開啟模態顏色範圍對話框；取消回 None，確認回傳 dict（空 dict = 清除）。"""
    if not b64:
        return None
    try:
        base64.b64decode(b64, validate=True)
    except (ValueError, TypeError):
        return None
    dlg = _TemplateColorMaskDialog(b64, current, parent)
    dlg.exec()
    return dlg._result
