# -*- coding: utf-8 -*-
"""「選擇現有圖片」對話框：列出各任務（含目前編輯中規則）match_image 步驟的內嵌圖片。

左列表（縮圖＋任務 › 規則 › #步驟）、右側大圖預覽；雙擊或按「確認」回傳選取的 b64。
"""

import base64

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from _loader import load_sibling
from i18n import T

_tmpl = load_sibling("template_matching", "core/11_template_matching.py")
_b64_to_img = _tmpl.b64_to_img

_THUMB = 48
_PREVIEW_MAX = 280


class TemplatePickerDialog(QDialog):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("picker.title"))
        self.setModal(True)
        self.setMinimumSize(560, 400)
        self._result: str | None = None
        self._rows: list[dict] = []  # 與 list rows 對應的可選 items

        self._list = QListWidget(self)
        self._list.setIconSize(QSize(_THUMB, _THUMB))
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.itemDoubleClicked.connect(lambda _item: self._accept())

        self._preview = QLabel(T("picker.empty") if not items else "")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(_PREVIEW_MAX, _PREVIEW_MAX - 60)
        self._preview.setStyleSheet(
            "border: 1px solid #888; border-radius: 4px; background: #2a2a2a;"
        )
        self._size_label = QLabel()
        self._size_label.setStyleSheet("color: #888;")
        self._size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._ok_btn = QPushButton(T("template_crop.ok"))
        self._ok_btn.setDefault(True)
        self._ok_btn.setEnabled(False)
        self._ok_btn.clicked.connect(self._accept)
        self._cancel_btn = QPushButton(T("template_crop.cancel"))
        self._cancel_btn.clicked.connect(self.reject)

        for it in items:
            pm = QPixmap()
            try:
                ok = pm.loadFromData(base64.b64decode(it["b64"]))
            except (ValueError, TypeError):
                ok = False
            if not ok or pm.isNull():
                continue
            row = QListWidgetItem(
                QIcon(
                    pm.scaled(
                        _THUMB,
                        _THUMB,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                ),
                f"{it['task']} › {it['rule_name']} › #{it['step_idx'] + 1}",
            )
            self._list.addItem(row)
            self._rows.append(it)

        if not self._rows:
            placeholder = QListWidgetItem(T("picker.empty"))
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)
            self._preview.setText(T("picker.empty"))

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._ok_btn)
        btn_row.addWidget(self._cancel_btn)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._ok_btn)
        btn_row.addWidget(self._cancel_btn)

        body = QHBoxLayout()
        body.addWidget(self._list, 3)
        right = QVBoxLayout()
        right.addWidget(self._preview, 1)
        right.addWidget(self._size_label)
        body.addLayout(right, 2)

        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addLayout(btn_row)
        if self._rows:
            self._list.setCurrentRow(0)

    def _on_row_changed(self, row):
        has = 0 <= row < len(self._rows)
        self._ok_btn.setEnabled(has)
        if not has:
            self._preview.clear()
            self._size_label.clear()
            return
        it = self._rows[row]
        pm = QPixmap()
        pm.loadFromData(base64.b64decode(it["b64"]))
        scaled = pm.scaled(
            _PREVIEW_MAX,
            _PREVIEW_MAX,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setPixmap(scaled)
        self._size_label.setText(T("template_crop.size", w=pm.width(), h=pm.height()))

    def _accept(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._rows):
            self._result = self._rows[row]["b64"]
            self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


def pick_template_dialog(
    parent=None,
    live_rules=None,
    live_task_name: str = "",
    exclude=None,
) -> str | None:
    """開模態對話框挑選既有圖片，回傳選取的 template_data b64；取消回 None。"""
    tm = load_sibling("task_management", "core/task_management.py")
    items = tm.collect_templates(
        live_rules=live_rules, live_task_name=live_task_name, exclude=exclude
    )
    dlg = TemplatePickerDialog(items, parent)
    dlg.exec()
    return dlg._result
