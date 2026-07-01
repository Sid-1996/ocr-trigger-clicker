import base64
import json
import logging
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Optional

import numpy as np
from PyQt6.QtCore import QMimeData, QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

if hasattr(sys, "_MEIPASS"):
    _base = Path(sys._MEIPASS)
else:
    _base = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_base))

from _loader import load_sibling

_here = _base
_GUIDE_URL = "https://sid-1996.github.io/ocr-trigger-clicker/"

from _version import __author__, __github__, __version__  # noqa: E402


def _parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.strip().split("."))


class _NoWheelCombo(QComboBox):
    def wheelEvent(self, e):
        e.ignore()


class _WindowCombo(_NoWheelCombo):
    def __init__(self, refresh_fn, parent=None):
        super().__init__(parent)
        self._refresh_fn = refresh_fn

    def showPopup(self):
        self._refresh_fn()
        super().showPopup()


class _KeyCombo(_NoWheelCombo):
    def keyPressEvent(self, event):
        text = event.text()
        if (
            text
            and len(text) == 1
            and text.isprintable()
            and event.modifiers()
            in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier)
        ):
            key = text.lower()
            count = self.count()
            if count == 0:
                return
            start = self.currentIndex() + 1
            for i in range(count):
                idx = (start + i) % count
                item = self.itemText(idx)
                if item and item.lower().startswith(key):
                    self.setCurrentIndex(idx)
                    if not self.view().isVisible():
                        self.showPopup()
                    return
        super().keyPressEvent(event)


class _NoWheelSpin(QSpinBox):
    def wheelEvent(self, e):
        e.ignore()


class _NoWheelDoubleSpin(QDoubleSpinBox):
    def wheelEvent(self, e):
        e.ignore()


class _StopGroupsPicker(QWidget):
    def __init__(self, groups_provider=None, selected=None):
        super().__init__()
        self._groups_provider = groups_provider or (lambda: [])
        self._selected: list[str] = list(selected or [])
        self._layout_ = QHBoxLayout(self)
        self._layout_.setContentsMargins(0, 0, 0, 0)
        self._btn = QPushButton()
        self._btn.setFlat(True)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet(
            "QPushButton { text-align: left; border: 1px solid #ccc; "
            "padding: 4px 8px; min-height: 28px; }"
        )
        self._btn.clicked.connect(self._open_dialog)
        self._layout_.addWidget(self._btn)
        self._update_display()

    def _get_groups(self) -> list:
        raw = self._groups_provider()
        return [
            {
                "id": g.get("id", "") if isinstance(g, dict) else g.id,
                "name": g.get("name", "") if isinstance(g, dict) else g.name,
            }
            for g in raw
        ]

    def _name_for_id(self, gid: str) -> str:
        for g in self._get_groups():
            if g["id"] == gid:
                return g["name"]
        return gid

    def _update_display(self):
        names = [self._name_for_id(gid) for gid in self._selected]
        if not names:
            self._btn.setText("未選擇")
            self._btn.setStyleSheet(
                "QPushButton { text-align: left; border: 1px solid #ccc; "
                "padding: 4px 8px; min-height: 28px; color: #888; }"
            )
        else:
            visible = names[:3]
            parts = [f"[{n}]" for n in visible]
            rest = len(names) - 3
            if rest > 0:
                parts.append(f"[+{rest}]")
            self._btn.setText(" ".join(parts))
            self._btn.setStyleSheet(
                "QPushButton { text-align: left; border: 1px solid #ccc; "
                "padding: 4px 8px; min-height: 28px; }"
            )
        if names:
            self._btn.setToolTip("已選：\n" + "\n".join(f"• {n}" for n in names))
        else:
            self._btn.setToolTip("未選擇任何群組")

    def _open_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("選取停止群組")
        dialog.setMinimumWidth(320)
        dialog.setMinimumHeight(400)
        layout = QVBoxLayout(dialog)

        search = QLineEdit()
        search.setPlaceholderText("搜尋群組...")
        layout.addWidget(search)

        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        groups = self._get_groups()
        for g in groups:
            item = QListWidgetItem(g["name"])
            item.setData(Qt.ItemDataRole.UserRole, g["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if g["id"] in self._selected else Qt.CheckState.Unchecked
            )
            list_widget.addItem(item)
        list_widget.itemClicked.connect(
            lambda item: item.setCheckState(
                Qt.CheckState.Unchecked
                if item.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
        )
        layout.addWidget(list_widget)

        def _filter(text: str):
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                item.setHidden(text.lower() not in item.text().lower())

        search.textChanged.connect(_filter)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("確定")
        cancel_btn = QPushButton("取消")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        def _accept():
            self._selected = [
                list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(list_widget.count())
                if list_widget.item(i).checkState() == Qt.CheckState.Checked
            ]
            self._update_display()
            dialog.accept()

        ok_btn.clicked.connect(_accept)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def selected_ids(self) -> list[str]:
        return list(self._selected)


class _RuleTreeWidget(QTreeWidget):
    reordered = pyqtSignal()

    def dropEvent(self, event):
        src = self.currentItem()
        if src is None:
            event.ignore()
            return
        src_data = src.data(0, Qt.ItemDataRole.UserRole)
        pos = event.position().toPoint()
        indicator = self.dropIndicatorPosition()
        target_item = self.itemAt(pos)

        if indicator == QAbstractItemView.DropIndicatorPosition.OnItem:
            if src_data and src_data[0] == "rule" and target_item:
                tgt_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                if tgt_data and tgt_data[0] == "bg_group":
                    event.ignore()
                    return
                if tgt_data and tgt_data[0] == "group":
                    super().dropEvent(event)
                    self.reordered.emit()
                    return
            event.ignore()
            return

        if not src_data or src_data[0] != "rule":
            super().dropEvent(event)
            self.reordered.emit()
            return

        super().dropEvent(event)
        self.reordered.emit()

    def dragMoveEvent(self, event):
        src = self.currentItem()
        if src is None:
            event.ignore()
            return
        src_data = src.data(0, Qt.ItemDataRole.UserRole)
        if src_data and src_data[0] == "group":
            pos = event.position().toPoint()
            target = self.itemAt(pos)
            if target:
                if target.parent():
                    event.ignore()
                    return
                if self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.OnItem:
                    event.ignore()
                    return
        super().dragMoveEvent(event)


# ── Step list helpers ──

_STEP_TYPE_ICONS = {
    "detect": "🔍",
    "match_image": "🖼",
    "compare": "🔢",
    "click": "🖱",
    "key": "⌨",
    "wait": "⏱",
    "jump": "↩",
    "drag": "↗",
    "scroll": "↕",
}

_STEP_TYPE_LABELS = {
    "detect": "偵測文字",
    "match_image": "圖示辨識",
    "compare": "數字比較",
    "click": "點擊",
    "key": "按鍵",
    "wait": "等待",
    "jump": "跳轉規則",
    "drag": "拖曳",
    "scroll": "滾輪",
}


def _resolve_rule_name(rule_id: str, rules_provider=None) -> str:
    if not rule_id or not rules_provider:
        return rule_id
    for r in rules_provider():
        if r.id == rule_id:
            return r.name
    return rule_id


def _fmt_roi(roi: dict) -> str:
    x, y, w, h = roi.get("x", 0), roi.get("y", 0), roi.get("w", 0), roi.get("h", 0)
    if w <= 1.0 and h <= 1.0 and not (x == 0 and y == 0 and w == 0 and h == 0):
        return f"({x:.0%},{y:.0%}) {w:.0%}×{h:.0%}"
    return f"({int(x)},{int(y)}) {int(w)}×{int(h)}"


def _fmt_point(px, py) -> str:
    if isinstance(px, float) and px <= 1.0 and isinstance(py, float) and py <= 1.0:
        return f"({px:.0%},{py:.0%})"
    return f"({int(px)},{int(py)})"


def _step_summary(step, rules_provider=None) -> str:
    p = step.params
    t = step.type
    if t == "detect":
        text = p.get("text", "")
        roi = p.get("roi", {})
        zero_roi = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        roi_str = "全視窗" if zero_roi else _fmt_roi(roi)
        mode = p.get("match_mode", "fuzzy")
        th = p.get("fuzzy_threshold", 0.8)
        extra = ""
        if mode == "regex":
            extra = " [正規]"
        elif mode == "exact":
            extra = " [完全]"
        elif mode == "contains":
            extra = " [包含]"
        elif mode == "fuzzy" and th != 0.8:
            extra = f" [模糊@{th}]"
        text_label = f"「{text}」" if text else "未設定"
        parts = [text_label + extra]
        parts.append(roi_str)
        of = _of_summary(p.get("on_fail", "stop"), rules_provider)
        if of:
            parts.append(f"| {of}")
        return " ".join(parts)
    if t == "match_image":
        tmpl_data = p.get("template_data", "")
        tmpl = Path(p.get("template", "")).stem or "內嵌" if tmpl_data.strip() else "未設定"
        roi = p.get("roi", {})
        zero_roi = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        parts = [f"「{tmpl}」"]
        parts.append("全視窗" if zero_roi else _fmt_roi(roi))
        th = p.get("threshold", 0.8)
        parts.append(f"閾值{th}")
        of = _of_summary(p.get("on_fail", "stop"), rules_provider)
        if of:
            parts.append(f"| {of}")
        return " ".join(parts)
    if t == "compare":
        op = p.get("operator", ">=")
        val = p.get("value", 0.0)
        roi = p.get("roi", {})
        zero_roi = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        parts = [f"{op} {val}"]
        parts.append("全視窗" if zero_roi else _fmt_roi(roi))
        of = _of_summary(p.get("on_fail", "stop"), rules_provider)
        if of:
            parts.append(f"| {of}")
        return " ".join(parts)
    if t == "click":
        target = p.get("target", "text_center")
        if target == "text_center":
            return "點擊辨識目標"
        if target == "custom":
            return f"點擊 {_fmt_point(p.get('x', 0), p.get('y', 0))}"
        if target == "click_text":
            return f"點擊文字「{p.get('text', '')}」"
    if t == "key":
        return f"按鍵 {p.get('key', '')}"
    if t == "wait":
        return f"等待 {p.get('ms', 500)}ms"
    if t == "jump":
        name = _resolve_rule_name(p.get("rule_id", ""), rules_provider)
        return f"跳轉規則「{name}」"
    if t == "drag":
        target = p.get("target", "text_center")
        dx, dy = p.get("dx", 0), p.get("dy", 0)
        base = {
            "text_center": "辨識目標",
            "custom": "座標",
            "click_text": f"文字「{p.get('text', '')}」",
        }.get(target, "?")
        return f"拖曳 {base} → ({dx:+},{dy:+})"
    if t == "scroll":
        d = p.get("direction", "WheelDown")
        a = p.get("amount", 1)
        dir_label = {
            "WheelDown": "向下",
            "WheelUp": "向上",
            "WheelLeft": "向左",
            "WheelRight": "向右",
        }.get(d, d)
        return f"滾輪 {dir_label} ×{a}"
    return t


def _of_summary(raw: str | dict, rules_provider=None) -> str:
    if isinstance(raw, str):
        return "" if raw == "stop" else "→按鍵"  # bare "key"
    if isinstance(raw, dict):
        action = raw.get("action", "stop")
        try:
            fail_duration = float(raw.get("fail_duration_sec", 0) or 0)
        except (TypeError, ValueError):
            fail_duration = 0.0
        prefix = f"[{fail_duration:g}秒]" if fail_duration > 0 else ""
        if action == "stop":
            return prefix if prefix else ""
        if action == "key":
            return f"{prefix}→按鍵{raw.get('key', '')}"
        if action == "skip":
            idx = raw.get("skip_to", -1)
            if idx < 0:
                return f"{prefix}→停止"
            return f"{prefix}→步驟{idx + 1}"
        if action == "jump":
            name = _resolve_rule_name(raw.get("rule_id", ""), rules_provider)
            return f"{prefix}→規則「{name}」"
        if action == "notify":
            return f"{prefix}→停群組"
        if action == "retry":
            return f"{prefix}→重試"
    return ""


def _make_key_combo(parent=None):
    cb = _KeyCombo(parent)
    for group in [
        [(f"數字鍵 {i}", str(i)) for i in range(10)],
        [
            "Enter",
            "Escape",
            "Space",
            "Tab",
            "Backspace",
            "Delete",
            "Insert",
            "Home",
            "End",
            "PgUp",
            "PgDn",
        ],
        ["Up", "Down", "Left", "Right"],
        [f"F{i}" for i in range(1, 13)],
        [chr(c) for c in range(ord("a"), ord("z") + 1)],
        {
            t: v
            for t, v in zip(
                [
                    "Ctrl+C",
                    "Ctrl+V",
                    "Ctrl+X",
                    "Ctrl+A",
                    "Ctrl+S",
                    "Ctrl+Z",
                    "Ctrl+Y",
                    "Ctrl+F",
                    "Ctrl+D",
                    "Ctrl+W",
                    "Ctrl+T",
                    "Ctrl+N",
                    "Ctrl+O",
                    "Ctrl+P",
                    "Ctrl+R",
                ],
                [
                    "^c",
                    "^v",
                    "^x",
                    "^a",
                    "^s",
                    "^z",
                    "^y",
                    "^f",
                    "^d",
                    "^w",
                    "^t",
                    "^n",
                    "^o",
                    "^p",
                    "^r",
                ],
            )
        }.items(),
        [
            "Numpad0",
            "Numpad1",
            "Numpad2",
            "Numpad3",
            "Numpad4",
            "Numpad5",
            "Numpad6",
            "Numpad7",
            "Numpad8",
            "Numpad9",
            "NumpadAdd",
            "NumpadSub",
            "NumpadMult",
            "NumpadDiv",
            "NumpadEnter",
            "NumpadDel",
        ],
    ]:
        cb.insertSeparator(cb.count())
        for item in group:
            if isinstance(item, tuple):
                text, data = item
            else:
                text = data = item
            cb.addItem(text, data)
    cb.setCurrentIndex(0)
    return cb


# ── DragHandle ──


class _DragHandle(QLabel):
    """⠿ handle that starts a QDrag for step reordering."""

    def __init__(self, idx: int, parent=None):
        super().__init__("⠿", parent)
        self._idx = idx
        self._drag_start = None
        self.setFixedWidth(20)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._drag_start is None:
            return
        if (e.position().toPoint() - self._drag_start).manhattanLength() < 5:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("step/index", str(self._idx).encode())
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)
        self._drag_start = None


# ── StepListWidget ──


class _StepListWidget(QWidget):
    """Step list with inline expandable forms."""

    steps_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._steps: list = []
        self._rows: list[QWidget] = []
        self._expanded_idx: Optional[int] = None
        self._expanded_form: Optional[QWidget] = None
        self._roi_callback: Optional[callable] = None
        self._capture_callback: Optional[callable] = None
        self._click_pick_callback: Optional[callable] = None
        self._rules_provider: Optional[callable] = None  # () -> list[Rule]
        self._groups_provider: Optional[callable] = None  # () -> list[RuleGroup]
        self._window_title_cb: Optional[callable] = None  # () -> str
        self._task_path_cb: Optional[callable] = None  # () -> str
        self._rule_id: str = ""
        self._drag_indicator_idx: int = -1
        self._simplified_mode: bool = False

    def set_roi_callback(self, cb):
        self._roi_callback = cb

    def set_capture_callback(self, cb):
        self._capture_callback = cb

    def set_click_pick_callback(self, cb):
        self._click_pick_callback = cb

    def set_rules_provider(self, cb):
        self._rules_provider = cb

    def set_groups_provider(self, cb):
        self._groups_provider = cb

    def set_window_title_callback(self, cb):
        self._window_title_cb = cb

    def set_task_path_callback(self, cb):
        self._task_path_cb = cb

    def set_rule_id(self, rule_id: str):
        self._rule_id = rule_id

    def set_simplified_mode(self, enabled: bool):
        self._simplified_mode = enabled

    def set_steps(self, steps: list):
        self._steps = list(steps)
        self._rebuild()

    def _save_expanded(self):
        if self._expanded_form and hasattr(self._expanded_form, "save"):
            self._expanded_form.save()

    def get_steps(self) -> list:
        self._save_expanded()
        return list(self._steps)

    def _rebuild(self):
        self._save_expanded()
        self._expanded_idx = None
        self._expanded_form = None
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows.clear()

        for i, step in enumerate(self._steps):
            row = self._build_row(i, step)
            self._rows.append(row)
            self._layout.addWidget(row)
        self._layout.addStretch()

    def _build_row(self, idx: int, step) -> QWidget:
        row = QFrame()
        row.setFrameShape(QFrame.Shape.StyledPanel)
        row.setFixedHeight(32)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(6, 2, 6, 2)

        handle = _DragHandle(idx)
        hl.addWidget(handle)

        num = QLabel(str(idx + 1))
        num.setFixedWidth(20)
        num.setStyleSheet("font-weight:bold;")
        hl.addWidget(num)

        icon = QLabel(_STEP_TYPE_ICONS.get(step.type, "?"))
        hl.addWidget(icon)

        label = _STEP_TYPE_LABELS.get(step.type, step.type)
        tl = QLabel(label)
        tl.setStyleSheet("font-weight:bold;")
        tl.setFixedWidth(60)
        hl.addWidget(tl)

        summary = _step_summary(step, self._rules_provider)
        sl = QLabel(summary)
        sl.setStyleSheet("font-size:11px;")
        hl.addWidget(sl, 1)

        btn_up = QPushButton("↑")
        btn_up.setFixedWidth(24)
        btn_up.setFixedHeight(22)
        btn_up.setStyleSheet("QPushButton { border: none; padding: 2px; }")
        btn_up.setToolTip("上移")
        btn_up.clicked.connect(lambda checked, i=idx: self._move_up(i))
        hl.addWidget(btn_up)

        btn_dn = QPushButton("↓")
        btn_dn.setFixedWidth(24)
        btn_dn.setFixedHeight(22)
        btn_dn.setStyleSheet("QPushButton { border: none; padding: 2px; }")
        btn_dn.setToolTip("下移")
        btn_dn.clicked.connect(lambda checked, i=idx: self._move_down(i))
        hl.addWidget(btn_dn)

        btn_edit = QPushButton("編")
        btn_edit.setFixedWidth(24)
        btn_edit.setFixedHeight(22)
        btn_edit.setStyleSheet("QPushButton { border: none; padding: 2px; }")
        btn_edit.setToolTip("編輯")
        btn_edit.clicked.connect(lambda checked, i=idx: self._toggle_expand(i))
        hl.addWidget(btn_edit)

        btn_del = QPushButton("刪")
        btn_del.setFixedWidth(24)
        btn_del.setFixedHeight(22)
        btn_del.setStyleSheet("QPushButton { border: none; padding: 2px; }")
        btn_del.setToolTip("刪除")
        btn_del.clicked.connect(lambda checked, i=idx: self._delete_step(i))
        hl.addWidget(btn_del)

        row.mousePressEvent = lambda e, i=idx: self._toggle_expand(i)
        return row

    def _expand_advanced(self, form):
        if hasattr(form, "_on_fail_expanded"):
            form._on_fail_expanded = True
            form._on_fail_container.setVisible(True)
            if hasattr(form, "_toggle_btn"):
                text = form._toggle_btn.text()
                form._toggle_btn.setText(text.replace("▶", "▼"))

    def _toggle_expand(self, idx: int):
        if self._expanded_idx == idx:
            self._collapse()
            return
        self._collapse()
        form = self._build_form(idx, self._steps[idx])
        if form:
            self._expanded_idx = idx
            self._expanded_form = form
            self._layout.insertWidget(self._rows.index(self._rows[idx]) + 1, form)
            if not self._simplified_mode:
                self._expand_advanced(form)

    def _collapse(self):
        if self._expanded_form:
            self._save_expanded()
            self._layout.removeWidget(self._expanded_form)
            self._expanded_form.deleteLater()
            self._expanded_form = None
            self._expanded_idx = None
            self._rebuild()

    def _move_up(self, idx: int):
        if idx <= 0:
            return
        self._steps[idx], self._steps[idx - 1] = self._steps[idx - 1], self._steps[idx]
        self._rebuild()
        self.steps_changed.emit()

    def _move_down(self, idx: int):
        if idx >= len(self._steps) - 1:
            return
        self._steps[idx], self._steps[idx + 1] = self._steps[idx + 1], self._steps[idx]
        self._rebuild()
        self.steps_changed.emit()

    def _delete_step(self, idx: int):
        self._steps.pop(idx)
        self._rebuild()
        self.steps_changed.emit()

    # drag-drop reorder with insertion indicator
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat("step/index"):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()
        y = e.position().y()
        row_h = 34
        idx = max(0, min(len(self._steps), int((y + row_h // 2) / row_h)))
        if self._drag_indicator_idx != idx:
            self._drag_indicator_idx = idx
            self.update()

    def dragLeaveEvent(self, e):
        self._drag_indicator_idx = -1
        self.update()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        src = int(e.mimeData().data("step/index").data().decode())
        self._collapse()
        target = self._drag_indicator_idx
        self._drag_indicator_idx = -1
        if target < 0 or target > len(self._steps):
            return
        adjusted = target if target < src else target - 1
        if src == adjusted:
            return
        self._steps.insert(adjusted, self._steps.pop(src))
        self._rebuild()
        self.steps_changed.emit()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._drag_indicator_idx < 0:
            return
        row_h = 34
        y_pos = self._drag_indicator_idx * row_h
        painter = QPainter(self)
        pen = QPen(QColor("#4a90d9"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(0, y_pos, self.width(), y_pos)
        painter.end()

    def add_step(self, step_type: str):
        step = Step(type=step_type, params=deepcopy(_STEP_DEFAULTS.get(step_type, {})))
        self._steps.append(step)
        self._rebuild()
        self._toggle_expand(len(self._steps) - 1)
        self.steps_changed.emit()

    def _build_form(self, idx: int, step) -> Optional[QWidget]:
        t = step.type
        if t == "detect":
            return _DetectStepForm(
                self,
                step,
                idx,
                self._roi_callback,
                self._rules_provider,
                self._rule_id,
                simplified=self._simplified_mode,
                groups_provider=self._groups_provider,
            )
        if t == "click":
            return _ClickStepForm(
                self, step, idx, self._click_pick_callback, simplified=self._simplified_mode
            )
        if t == "key":
            return _KeyStepForm(self, step, idx)
        if t == "wait":
            return _WaitStepForm(self, step, idx)
        if t == "jump":
            return _JumpStepForm(self, step, idx, self._rules_provider, self._rule_id)
        if t == "match_image":
            return _MatchImageStepForm(
                self,
                step,
                idx,
                self._roi_callback,
                self._capture_callback,
                self._rules_provider,
                self._rule_id,
                step_count=len(self._steps),
                window_title_cb=self._window_title_cb,
                groups_provider=self._groups_provider,
                task_path_cb=self._task_path_cb,
            )
        if t == "drag":
            return _DragStepForm(self, step, idx, self._click_pick_callback)
        if t == "scroll":
            return _ScrollStepForm(self, step, idx)
        if t == "compare":
            return _CompareStepForm(
                self,
                step,
                idx,
                self._roi_callback,
                self._rules_provider,
                self._rule_id,
                simplified=self._simplified_mode,
                step_count=len(self._steps),
                groups_provider=self._groups_provider,
            )
        return None


# ── Step inline forms ──


class _MatchImageStepForm(QWidget):
    def __init__(
        self,
        parent_list,
        step,
        idx,
        roi_cb,
        capture_cb=None,
        rules_provider=None,
        exclude_rule_id="",
        step_count=0,
        window_title_cb=None,
        groups_provider=None,
        task_path_cb=None,
    ):
        super().__init__()
        self._list = parent_list
        self._step = step
        self._idx = idx
        self._roi_cb = roi_cb
        self._capture_cb = capture_cb
        self._rules_provider = rules_provider
        self._exclude_rule_id = exclude_rule_id
        self._step_count = step_count
        self._window_title_cb = window_title_cb
        self._groups_provider = groups_provider
        self._task_path_cb = task_path_cb
        p = step.params
        form = QFormLayout(self)
        form.setContentsMargins(12, 6, 12, 6)

        # Template file + test button
        tmpl_row = QWidget()
        tmpl_layout = QHBoxLayout(tmpl_row)
        tmpl_layout.setContentsMargins(0, 0, 0, 0)
        self._thumb = QLabel()
        self._thumb.setFixedSize(64, 64)
        self._thumb.setStyleSheet(
            "border: 1px solid #888; border-radius: 4px; background: #2a2a2a;"
        )
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tmpl_layout.addWidget(self._thumb)
        tmpl_path = p.get("template", "")
        tmpl_data = p.get("template_data", "")
        label_text = (
            Path(tmpl_path).stem
            if tmpl_path.strip()
            else ("內嵌圖片" if tmpl_data.strip() else "未選擇")
        )
        self._tmpl_label = QLabel(label_text)
        self._tmpl_btn = QPushButton("選擇圖片")
        self._tmpl_btn.clicked.connect(self._pick_template)
        self._capture_btn = QPushButton("截取區域")
        self._capture_btn.clicked.connect(self._capture_template)
        self._img_compare_btn = QPushButton("圖片比對")
        self._img_compare_btn.clicked.connect(self._img_compare_match)
        self._img_compare_result = QLabel("")
        tmpl_layout.addWidget(self._tmpl_label, 1)
        tmpl_layout.addWidget(self._tmpl_btn)
        tmpl_layout.addWidget(self._capture_btn)
        tmpl_layout.addWidget(self._img_compare_btn)
        tmpl_layout.addWidget(self._img_compare_result)
        form.addRow("範本圖片:", tmpl_row)
        self._update_thumbnail()

        # ROI
        roi = p.get("roi", {})
        z = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        self._roi_label = QLabel("全視窗" if z else _fmt_roi(roi))
        self._roi_btn = QPushButton("框選搜尋區域")
        self._roi_btn.setToolTip("不設定時掃描整個視窗，建議框選偵測區域以加快速度")
        self._roi_btn.clicked.connect(self._pick_roi)
        roi_row = QWidget()
        rr_layout = QHBoxLayout(roi_row)
        rr_layout.setContentsMargins(0, 0, 0, 0)

        rr_layout.addWidget(self._roi_label)
        rr_layout.addWidget(self._roi_btn)
        form.addRow("搜尋區域:", roi_row)

        # Threshold
        self._threshold = _NoWheelDoubleSpin()
        self._threshold.setRange(0.01, 1.0)
        self._threshold.setDecimals(2)
        self._threshold.setSingleStep(0.05)
        self._threshold.setValue(p.get("threshold", 0.8))
        form.addRow("相似度閾值:", self._threshold)

        # ── on_fail collapsible section ──
        self._on_fail_expanded = False
        self._toggle_btn = QPushButton("▶ 進階：找不到圖示時…")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet(
            "QPushButton { text-align: left; border: none; color: #888; }"
        )
        self._toggle_btn.clicked.connect(self._toggle_on_fail)
        form.addRow(self._toggle_btn)

        self._on_fail_container = QWidget()
        self._on_fail_container.setVisible(False)
        of_form = QFormLayout(self._on_fail_container)
        of_form.setContentsMargins(0, 0, 0, 0)

        self._of_action = _NoWheelCombo()
        self._of_action.addItem("跳過本次（預設）", "stop")
        self._of_action.addItem("跳至步驟", "skip")
        self._of_action.addItem("跳轉至規則", "jump")
        self._of_action.addItem("按下按鍵後繼續", "key")
        self._of_action.addItem("通知並停止群組", "notify")
        raw_of = p.get("on_fail", "stop")
        default_notify_msg = ""
        default_notify_groups: list[str] = []
        if isinstance(raw_of, dict):
            of_act = raw_of.get("action", "stop")
            if raw_of.get("action") == "notify":
                default_notify_msg = raw_of.get("message", "")
                default_notify_groups = raw_of.get("stop_groups", [])
        else:
            of_act = raw_of
        idx_of = self._of_action.findData(of_act)
        if idx_of >= 0:
            self._of_action.setCurrentIndex(idx_of)
        self._of_action.currentIndexChanged.connect(self._on_of_action_changed)
        of_form.addRow("動作:", self._of_action)

        self._of_fail_duration = _NoWheelDoubleSpin()
        self._of_fail_duration.setRange(0.0, 30.0)
        self._of_fail_duration.setSingleStep(0.5)
        self._of_fail_duration.setSuffix(" 秒")
        self._of_fail_duration.setDecimals(1)
        default_duration = raw_of.get("fail_duration_sec", 0.0) if isinstance(raw_of, dict) else 0.0
        try:
            default_duration = float(default_duration)
        except (TypeError, ValueError):
            default_duration = 0.0
        self._of_fail_duration.setValue(default_duration)
        of_form.addRow("持續失敗:", self._of_fail_duration)

        # skip row (jump to step)
        self._of_skip_row = QWidget()
        sf = QHBoxLayout(self._of_skip_row)
        sf.setContentsMargins(0, 0, 0, 0)
        self._of_skip_combo = _NoWheelCombo()
        self._populate_skip_combo(raw_of.get("skip_to", -1) if isinstance(raw_of, dict) else -1)
        sf.addWidget(QLabel("跳至"))
        sf.addWidget(self._of_skip_combo)
        sf.addStretch()
        of_form.addRow("", self._of_skip_row)

        # jump row (jump to rule)
        self._of_jump_row = QWidget()
        jf = QHBoxLayout(self._of_jump_row)
        jf.setContentsMargins(0, 0, 0, 0)
        self._of_jump_combo = _NoWheelCombo()
        rules = rules_provider() if rules_provider else []
        for r in rules:
            if r.id != self._exclude_rule_id:
                self._of_jump_combo.addItem(r.name, r.id)
        if isinstance(raw_of, dict) and raw_of.get("action") == "jump":
            target_id = raw_of.get("rule_id", "")
            j_idx = self._of_jump_combo.findData(target_id)
            if j_idx < 0 and target_id:
                # keep unknown by adding placeholder; jump combo will show it
                self._of_jump_combo.addItem(f"(未知: {target_id})", target_id)
                j_idx = self._of_jump_combo.count() - 1
            self._of_jump_combo.setCurrentIndex(max(j_idx, 0))
        jf.addWidget(QLabel("跳至"))
        jf.addWidget(self._of_jump_combo)
        jf.addStretch()
        of_form.addRow("", self._of_jump_row)

        # key row
        self._of_key = _make_key_combo()
        if isinstance(raw_of, dict) and raw_of.get("action") == "key":
            kv = raw_of.get("key", "")
            k_idx = self._of_key.findData(kv)
            if k_idx >= 0:
                self._of_key.setCurrentIndex(k_idx)
        self._of_key_row = QWidget()
        kf = QHBoxLayout(self._of_key_row)
        kf.setContentsMargins(0, 0, 0, 0)
        kf.addWidget(QLabel("按下"))
        kf.addWidget(self._of_key)
        kf.addWidget(QLabel("後繼續"))
        kf.addStretch()
        of_form.addRow("", self._of_key_row)

        # notify widgets
        self._of_notify_msg = QLineEdit()
        self._of_notify_msg.setPlaceholderText("例如：每日探索次數已為空，已停止流程")
        of_form.addRow("通知訊息:", self._of_notify_msg)
        self._of_notify_msg.setText(default_notify_msg)
        self._of_notify_groups = _StopGroupsPicker(
            groups_provider=groups_provider,
            selected=default_notify_groups,
        )
        of_form.addRow("停止群組:", self._of_notify_groups)

        form.addRow(self._on_fail_container)
        self._on_of_action_changed()

    def _populate_skip_combo(self, current_skip_to):
        self._of_skip_combo.clear()
        self._of_skip_combo.addItem("本規則結束", self._step_count)
        start = self._idx + 2  # 1-based, after current
        for i in range(start, self._step_count + 1):
            self._of_skip_combo.addItem(f"步驟{i}", i - 1)
        if current_skip_to >= 0:
            idx_s = self._of_skip_combo.findData(current_skip_to)
            if idx_s >= 0:
                self._of_skip_combo.setCurrentIndex(idx_s)

    def _update_thumbnail(self):
        data = self._step.params.get("template_data", "")
        if data.strip():
            pix = QPixmap()
            if pix.loadFromData(base64.b64decode(data)):
                self._thumb.setPixmap(
                    pix.scaled(
                        64,
                        64,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        path = self._step.params.get("template", "")
        if path and Path(path).exists():
            pix = QPixmap(path)
            if not pix.isNull():
                self._thumb.setPixmap(
                    pix.scaled(
                        64,
                        64,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        self._thumb.clear()

    def _img_compare_match(self):
        title = self._window_title_cb() if self._window_title_cb else ""
        if not title:
            self._img_compare_result.setText("⚠️ 請先選擇目標視窗")
            self._img_compare_result.setStyleSheet("color: #e67e22; font-weight: bold;")
            return
        tmpl_data = self._step.params.get("template_data", "")
        tmpl_path = self._step.params.get("template", "")
        if not tmpl_data.strip() and not tmpl_path.strip():
            self._img_compare_result.setText("⚠️ 未設定範本圖片")
            self._img_compare_result.setStyleSheet("color: #e67e22; font-weight: bold;")
            return
        roi = self._step.params.get("roi", {})
        threshold = self._step.params.get("threshold", 0.8)
        win = self.window()
        if isinstance(win, QMainWindow):
            win.showMinimized()
            QApplication.processEvents()
            time.sleep(0.08)
            activate_window(title)
            time.sleep(0.12)
        img = capture(title)
        if img is None:
            img = capture_window_content(title)
        if isinstance(win, QMainWindow):
            win.showNormal()
            win.activateWindow()
        if img is None:
            self._img_compare_result.setText("⚠️ 無法截取視窗畫面")
            self._img_compare_result.setStyleSheet("color: #e67e22; font-weight: bold;")
            return
        h, w = img.shape[:2]
        wr = get_window_rect(title)
        chrome = get_window_client_offset(title) or (0, 0)
        cx, cy = chrome
        client_w = wr["w"] - cx if wr else w
        client_h = wr["h"] - cy if wr else h
        if roi and any(isinstance(v, float) for v in roi.values()):
            if roi.get("roi_coord") == "client":
                roi = {
                    "x": int(round(roi.get("x", 0) * client_w)) + cx,
                    "y": int(round(roi.get("y", 0) * client_h)) + cy,
                    "w": max(1, int(round(roi.get("w", 0) * client_w))),
                    "h": max(1, int(round(roi.get("h", 0) * client_h))),
                }
            else:
                roi = {
                    "x": int(round(roi.get("x", 0) * w))
                    if isinstance(roi.get("x"), float)
                    else int(roi.get("x", 0)),
                    "y": int(round(roi.get("y", 0) * h))
                    if isinstance(roi.get("y"), float)
                    else int(roi.get("y", 0)),
                    "w": max(1, int(round(roi.get("w", 0) * w)))
                    if isinstance(roi.get("w"), float)
                    else int(roi.get("w", 0)),
                    "h": max(1, int(round(roi.get("h", 0) * h)))
                    if isinstance(roi.get("h"), float)
                    else int(roi.get("h", 0)),
                }
        current_size = [client_w, client_h] if wr else None
        capture_size = None
        print(
            f"[TEST DEBUG] w={w} h={h} chrome={chrome} client=({client_w},{client_h}) roi_before={self._step.params.get('roi', {})} roi_after={roi} current_size={current_size} capture_size={capture_size}"
        )
        if self._task_path_cb:
            task_path = self._task_path_cb()
            if task_path:
                capture_size = _rule_mod.get_capture_size(task_path)
        results = _tmpl_mod.match_template(
            img,
            tmpl_path,
            roi,
            threshold,
            template_data=tmpl_data or None,
            capture_size=capture_size,
            current_size=current_size,
        )
        if results:
            best = results[0]
            pct = int(best.confidence * 100)
            self._img_compare_result.setText(f"✅ 命中（相似度 {pct}%）")
            self._img_compare_result.setStyleSheet("color: #4caf50; font-weight: bold;")
        else:
            fallback = _tmpl_mod.match_template(
                img,
                tmpl_path,
                roi,
                0.01,
                template_data=tmpl_data or None,
                capture_size=capture_size,
                current_size=current_size,
            )
            top = max(m.confidence for m in fallback) if fallback else 0.0
            top_pct = int(top * 100)
            self._img_compare_result.setText(f"❌ 未命中（最高 {top_pct}%）")
            self._img_compare_result.setStyleSheet("color: #e53935; font-weight: bold;")

    def _capture_template(self):
        if not self._capture_cb:
            return
        data = self._capture_cb()
        if isinstance(data, dict):
            self._step.params["template_data"] = data.get("b64", "")
            self._step.params.pop("template", None)
            if data.get("roi"):
                self._step.params["roi"] = data["roi"]
            self._tmpl_label.setText("內嵌圖片")
            self._update_thumbnail()
            self._list.steps_changed.emit()
        elif data:
            self._step.params["template_data"] = data
            self._step.params.pop("template", None)
            self._tmpl_label.setText("內嵌圖片")
            self._update_thumbnail()
            self._list.steps_changed.emit()

    def _pick_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇範本圖片", "", "圖片 (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            import cv2 as _cv2

            _img = _cv2.imread(path, _cv2.IMREAD_COLOR)
            if _img is not None:
                self._step.params["template_data"] = img_to_b64(_img)
                self._step.params.pop("template", None)
                self._tmpl_label.setText(Path(path).stem)
                self._update_thumbnail()
                self._list.steps_changed.emit()

    def _pick_roi(self):
        if self._roi_cb:
            result = self._roi_cb()
            if result:
                self._step.params["roi"] = result
                z = all(result.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
                self._roi_label.setText("全視窗" if z else _fmt_roi(result))
                self.save()
                self._list.steps_changed.emit()

    def _toggle_on_fail(self):
        self._on_fail_expanded = not self._on_fail_expanded
        self._on_fail_container.setVisible(self._on_fail_expanded)
        self._toggle_btn.setText(
            "▼ 進階：找不到圖示時…" if self._on_fail_expanded else "▶ 進階：找不到圖示時…"
        )

    def _on_of_action_changed(self, idx=None):
        action = self._of_action.currentData()
        self._of_skip_row.setVisible(action == "skip")
        self._of_jump_row.setVisible(action == "jump")
        self._of_key_row.setVisible(action == "key")
        is_notify = action == "notify"
        self._of_notify_msg.setVisible(is_notify)
        self._of_notify_groups.setVisible(is_notify)

    def save(self):
        p = self._step.params
        p["threshold"] = self._threshold.value()
        action = self._of_action.currentData()
        fail_duration = self._of_fail_duration.value()
        if action == "stop":
            if fail_duration > 0:
                p["on_fail"] = {"action": "stop", "fail_duration_sec": fail_duration}
            else:
                p["on_fail"] = "stop"
        elif action == "skip":
            p["on_fail"] = {
                "action": "skip",
                "skip_to": self._of_skip_combo.currentData() or 0,
                "fail_duration_sec": fail_duration,
            }
        elif action == "jump":
            p["on_fail"] = {
                "action": "jump",
                "rule_id": self._of_jump_combo.currentData() or "",
                "fail_duration_sec": fail_duration,
            }
        elif action == "key":
            p["on_fail"] = {
                "action": "key",
                "key": self._of_key.currentData() or self._of_key.currentText(),
                "fail_duration_sec": fail_duration,
            }
        elif action == "notify":
            selected_ids = self._of_notify_groups.selected_ids()
            p["on_fail"] = {
                "action": "notify",
                "message": self._of_notify_msg.text().strip(),
                "stop_groups": selected_ids,
                "fail_duration_sec": fail_duration,
            }
        if p.get("template"):
            self._tmpl_label.setText(Path(p["template"]).stem)
            self._update_thumbnail()


class _DetectStepForm(QWidget):
    def __init__(
        self,
        parent_list,
        step,
        idx,
        roi_cb,
        rules_provider=None,
        exclude_rule_id="",
        simplified=False,
        groups_provider=None,
    ):
        super().__init__()
        self._list = parent_list
        self._step = step
        self._idx = idx
        self._roi_cb = roi_cb
        self._rules_provider = rules_provider
        self._exclude_rule_id = exclude_rule_id
        self._groups_provider = groups_provider
        p = step.params
        form = QFormLayout(self)
        form.setContentsMargins(12, 6, 12, 6)

        self._text = QLineEdit(p.get("text", ""))
        form.addRow("目標文字:", self._text)

        self._advanced_container = QWidget()
        adv_form = QFormLayout(self._advanced_container)
        adv_form.setContentsMargins(0, 0, 0, 0)

        roi = p.get("roi", {})
        zero = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        self._roi_label = QLabel("全視窗" if zero else _fmt_roi(roi))
        self._roi_btn = QPushButton("框選偵測區域")
        self._roi_btn.setToolTip("不設定時掃描整個視窗，建議框選偵測區域以加快速度")
        if roi_cb:
            self._roi_btn.clicked.connect(self._pick_roi)
        adv_form.addRow("偵測區域:", self._roi_label)
        adv_form.addRow("", self._roi_btn)

        self._match_mode = _NoWheelCombo()
        self._match_mode.addItem("包含關鍵字", "contains")
        self._match_mode.addItem("完全符合", "exact")
        self._match_mode.addItem("近似比對", "fuzzy")
        self._match_mode.addItem("正規表達式", "regex")
        idx_mm = self._match_mode.findData(p.get("match_mode", "fuzzy"))
        if idx_mm >= 0:
            self._match_mode.setCurrentIndex(idx_mm)
        self._match_mode.currentIndexChanged.connect(self._on_match_mode_changed)
        adv_form.addRow("比對模式:", self._match_mode)

        self._fuzzy_th = _NoWheelSpin()
        self._fuzzy_th.setRange(1, 100)
        self._fuzzy_th.setSuffix(" %")
        self._fuzzy_th.setValue(int(p.get("fuzzy_threshold", 0.8) * 100))
        self._fuzzy_th.setVisible(self._match_mode.currentData() == "fuzzy")
        adv_form.addRow("精準度:", self._fuzzy_th)

        # ── on_fail collapsible section (in advanced) ──
        self._on_fail_expanded = False
        self._toggle_btn = QPushButton("▶ 進階：找不到文字時…")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet(
            "QPushButton { text-align: left; border: none; color: #888; }"
        )
        self._toggle_btn.clicked.connect(self._toggle_on_fail)
        adv_form.addRow(self._toggle_btn)

        self._on_fail_container = QWidget()
        self._on_fail_container.setVisible(False)
        of_form = QFormLayout(self._on_fail_container)
        of_form.setContentsMargins(0, 0, 0, 0)

        self._of_action = _NoWheelCombo()

        self._advanced_container.setVisible(not simplified)
        form.addRow(self._advanced_container)

        self._of_action.addItem("跳過本次（預設）", "stop")
        self._of_action.addItem("跳轉至規則", "jump")
        self._of_action.addItem("按下按鍵後繼續", "key")
        self._of_action.addItem("通知並停止群組", "notify")
        raw = p.get("on_fail", "stop")
        default_notify_msg = ""
        default_notify_groups: list[str] = []
        if isinstance(raw, dict):
            act = raw.get("action", "stop")
            if raw.get("action") == "notify":
                default_notify_msg = raw.get("message", "")
                default_notify_groups = raw.get("stop_groups", [])
        else:
            act = raw
        idx_of = self._of_action.findData(act)
        if idx_of >= 0:
            self._of_action.setCurrentIndex(idx_of)
        self._of_action.currentIndexChanged.connect(self._on_of_action_changed)
        of_form.addRow("動作:", self._of_action)

        self._of_fail_duration = _NoWheelDoubleSpin()
        self._of_fail_duration.setRange(0.0, 30.0)
        self._of_fail_duration.setSingleStep(0.5)
        self._of_fail_duration.setSuffix(" 秒")
        self._of_fail_duration.setDecimals(1)
        default_duration = raw.get("fail_duration_sec", 0.0) if isinstance(raw, dict) else 0.0
        try:
            default_duration = float(default_duration)
        except (TypeError, ValueError):
            default_duration = 0.0
        self._of_fail_duration.setValue(default_duration)
        of_form.addRow("持續失敗:", self._of_fail_duration)

        # jump row (jump to rule)
        self._of_jump_row = QWidget()
        jf = QHBoxLayout(self._of_jump_row)
        jf.setContentsMargins(0, 0, 0, 0)
        self._of_jump_combo = _NoWheelCombo()
        rules = self._rules_provider() if self._rules_provider else []
        for r in rules:
            if r.id != self._exclude_rule_id:
                self._of_jump_combo.addItem(r.name, r.id)
        if isinstance(raw, dict) and raw.get("action") == "jump":
            target_id = raw.get("rule_id", "")
            j_idx = self._of_jump_combo.findData(target_id)
            if j_idx < 0 and target_id:
                self._of_jump_combo.addItem(f"(未知: {target_id})", target_id)
                j_idx = self._of_jump_combo.count() - 1
            self._of_jump_combo.setCurrentIndex(max(j_idx, 0))
        jf.addWidget(QLabel("跳至"))
        jf.addWidget(self._of_jump_combo)
        jf.addStretch()
        of_form.addRow("", self._of_jump_row)

        # key row
        self._of_key = _make_key_combo()
        if isinstance(raw, dict) and raw.get("action") == "key":
            kv = raw.get("key", "")
            k_idx = self._of_key.findData(kv)
            if k_idx >= 0:
                self._of_key.setCurrentIndex(k_idx)
        self._of_key_row = QWidget()
        kf = QHBoxLayout(self._of_key_row)
        kf.setContentsMargins(0, 0, 0, 0)
        kf.addWidget(QLabel("按下"))
        kf.addWidget(self._of_key)
        kf.addWidget(QLabel("後繼續"))
        kf.addStretch()
        of_form.addRow("", self._of_key_row)

        # notify widgets
        self._of_notify_msg = QLineEdit()
        self._of_notify_msg.setPlaceholderText("例如：每日探索次數已為空，已停止流程")
        of_form.addRow("通知訊息:", self._of_notify_msg)
        self._of_notify_msg.setText(default_notify_msg)
        self._of_notify_groups = _StopGroupsPicker(
            groups_provider=self._groups_provider,
            selected=default_notify_groups,
        )
        of_form.addRow("停止群組:", self._of_notify_groups)

        form.addRow(self._on_fail_container)
        self._on_of_action_changed()

    def _on_match_mode_changed(self, idx):
        self._fuzzy_th.setVisible(self._match_mode.itemData(idx) == "fuzzy")

    def _toggle_on_fail(self):
        self._on_fail_expanded = not self._on_fail_expanded
        self._on_fail_container.setVisible(self._on_fail_expanded)
        self._toggle_btn.setText(
            "▼ 進階：找不到文字時…" if self._on_fail_expanded else "▶ 進階：找不到文字時…"
        )

    def _on_of_action_changed(self, idx=None):
        action = self._of_action.currentData()
        self._of_jump_row.setVisible(action == "jump")
        self._of_key_row.setVisible(action == "key")
        is_notify = action == "notify"
        self._of_notify_msg.setVisible(is_notify)
        self._of_notify_groups.setVisible(is_notify)

    def _pick_roi(self):
        if self._roi_cb:
            result = self._roi_cb()
            if result:
                self._step.params["roi"] = result
                z = all(result.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
                self._roi_label.setText("全視窗" if z else _fmt_roi(result))
                self.save()
                self._list.steps_changed.emit()

    def save(self):
        self._step.params["text"] = self._text.text().strip()
        self._step.params["match_mode"] = self._match_mode.currentData()
        self._step.params["fuzzy_threshold"] = self._fuzzy_th.value() / 100.0
        action = self._of_action.currentData()
        fail_duration = self._of_fail_duration.value()
        if action == "stop":
            if fail_duration > 0:
                self._step.params["on_fail"] = {
                    "action": "stop",
                    "fail_duration_sec": fail_duration,
                }
            else:
                self._step.params["on_fail"] = "stop"
        elif action == "jump":
            self._step.params["on_fail"] = {
                "action": "jump",
                "rule_id": self._of_jump_combo.currentData() or "",
                "fail_duration_sec": fail_duration,
            }
        elif action == "key":
            self._step.params["on_fail"] = {
                "action": "key",
                "key": self._of_key.currentData() or self._of_key.currentText(),
                "fail_duration_sec": fail_duration,
            }
        elif action == "notify":
            selected_ids = self._of_notify_groups.selected_ids()
            self._step.params["on_fail"] = {
                "action": "notify",
                "message": self._of_notify_msg.text().strip(),
                "stop_groups": selected_ids,
                "fail_duration_sec": fail_duration,
            }


class _ClickStepForm(QWidget):
    def __init__(self, parent_list, step, idx, pick_cb, simplified=False):
        super().__init__()
        self._list = parent_list
        self._step = step
        self._idx = idx
        self._pick_cb = pick_cb
        p = step.params
        form = QFormLayout(self)
        form.setContentsMargins(12, 6, 12, 6)

        self._target = _NoWheelCombo()
        self._target.addItem("辨識目標", "text_center")
        self._target.addItem("自訂座標", "custom")
        self._target.addItem("點擊文字", "click_text")
        t_idx = self._target.findData(p.get("target", "text_center"))
        if t_idx >= 0:
            self._target.setCurrentIndex(t_idx)
        self._target.currentIndexChanged.connect(self._on_target_changed)
        form.addRow("點擊目標:", self._target)

        self._click_text = QLineEdit(p.get("text", ""))
        self._click_text.setVisible(p.get("target", "") == "click_text")
        form.addRow("目標文字:", self._click_text)

        self._coord_label = QLabel(_fmt_point(p.get("x", 0), p.get("y", 0)))
        self._pick_btn = QPushButton("選取點擊座標")
        if pick_cb:
            self._pick_btn.clicked.connect(self._pick_coord)
        self._coord_row = QWidget()
        cl = QHBoxLayout(self._coord_row)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self._coord_label)
        cl.addWidget(self._pick_btn)
        self._coord_row.setVisible(p.get("target", "") == "custom")
        form.addRow("點擊座標:", self._coord_row)

        self._adv_container = QWidget()
        adv_form = QFormLayout(self._adv_container)
        adv_form.setContentsMargins(0, 0, 0, 0)

        self._button = _NoWheelCombo()
        self._button.addItem("左鍵", "left")
        self._button.addItem("右鍵", "right")
        b_idx = self._button.findData(p.get("button", "left"))
        if b_idx >= 0:
            self._button.setCurrentIndex(b_idx)
        adv_form.addRow("滑鼠按鈕:", self._button)

        self._offset = _NoWheelSpin()
        self._offset.setRange(0, 100)
        self._offset.setSuffix(" px")
        self._offset.setValue(p.get("random_offset", 3))
        adv_form.addRow("隨機抖動:", self._offset)

        self._adv_container.setVisible(not simplified)
        form.addRow(self._adv_container)

    def _on_target_changed(self, idx):
        t = self._target.currentData()
        self._coord_row.setVisible(t == "custom")
        self._click_text.setVisible(t == "click_text")

    def _pick_coord(self):
        if self._pick_cb:
            result = self._pick_cb()
            if result:
                self._step.params["x"], self._step.params["y"] = result
                self._step.params["target"] = "custom"
                self._coord_label.setText(_fmt_point(result[0], result[1]))
                self._target.setCurrentIndex(self._target.findData("custom"))
                self.save()
                self._list.steps_changed.emit()

    def save(self):
        self._step.params["target"] = self._target.currentData()
        self._step.params["text"] = self._click_text.text().strip()
        self._step.params["button"] = self._button.currentData()
        self._step.params["random_offset"] = self._offset.value()


class _DragStepForm(QWidget):
    def __init__(self, parent_list, step, idx, pick_cb):
        super().__init__()
        self._list = parent_list
        self._step = step
        self._idx = idx
        self._pick_cb = pick_cb
        p = step.params
        form = QFormLayout(self)
        form.setContentsMargins(12, 6, 12, 6)

        self._target = _NoWheelCombo()
        self._target.addItem("辨識目標", "text_center")
        self._target.addItem("自訂座標", "custom")
        self._target.addItem("點擊文字", "click_text")
        t_idx = self._target.findData(p.get("target", "text_center"))
        if t_idx >= 0:
            self._target.setCurrentIndex(t_idx)
        self._target.currentIndexChanged.connect(self._on_target_changed)
        form.addRow("拖曳起點:", self._target)

        self._click_text = QLineEdit(p.get("text", ""))
        self._click_text.setVisible(p.get("target", "") == "click_text")
        form.addRow("目標文字:", self._click_text)

        self._coord_label = QLabel(_fmt_point(p.get("x", 0), p.get("y", 0)))
        self._pick_btn = QPushButton("選取座標")
        if pick_cb:
            self._pick_btn.clicked.connect(self._pick_coord)
        self._coord_row = QWidget()
        cl = QHBoxLayout(self._coord_row)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self._coord_label)
        cl.addWidget(self._pick_btn)
        self._coord_row.setVisible(p.get("target", "") == "custom")
        form.addRow("起點座標:", self._coord_row)
        self._dx = _NoWheelSpin()
        self._dx.setRange(-9999, 9999)
        self._dx.setSuffix(" px")
        self._dx.setValue(p.get("dx", 0))
        form.addRow("水平偏移:", self._dx)

        self._dy = _NoWheelSpin()
        self._dy.setRange(-9999, 9999)
        self._dy.setSuffix(" px")
        self._dy.setValue(p.get("dy", 0))
        form.addRow("垂直偏移:", self._dy)

        self._button = _NoWheelCombo()
        self._button.addItem("左鍵", "left")
        self._button.addItem("右鍵", "right")
        b_idx = self._button.findData(p.get("button", "left"))
        if b_idx >= 0:
            self._button.setCurrentIndex(b_idx)
        form.addRow("滑鼠按鈕:", self._button)

    def _on_target_changed(self, idx):
        t = self._target.currentData()
        self._coord_row.setVisible(t == "custom")
        self._click_text.setVisible(t == "click_text")

    def _pick_coord(self):
        if self._pick_cb:
            result = self._pick_cb()
            if result:
                self._step.params["x"], self._step.params["y"] = result
                self._coord_label.setText(_fmt_point(result[0], result[1]))
                self._target.setCurrentIndex(self._target.findData("custom"))
                self.save()
                self._list.steps_changed.emit()

    def save(self):
        self._step.params["target"] = self._target.currentData()
        self._step.params["text"] = self._click_text.text().strip()
        self._step.params["dx"] = self._dx.value()
        self._step.params["dy"] = self._dy.value()
        self._step.params["button"] = self._button.currentData()


class _ScrollStepForm(QWidget):
    def __init__(self, parent_list, step, idx):
        super().__init__()
        self._list = parent_list
        self._step = step
        form = QFormLayout(self)
        form.setContentsMargins(12, 6, 12, 6)
        p = step.params

        self._direction = _NoWheelCombo()
        self._direction.addItem("向下", "WheelDown")
        self._direction.addItem("向上", "WheelUp")
        self._direction.addItem("向左", "WheelLeft")
        self._direction.addItem("向右", "WheelRight")
        d_idx = self._direction.findData(p.get("direction", "WheelDown"))
        if d_idx >= 0:
            self._direction.setCurrentIndex(d_idx)
        form.addRow("方向:", self._direction)

        self._amount = _NoWheelSpin()
        self._amount.setRange(1, 99)
        self._amount.setValue(p.get("amount", 1))
        form.addRow("次數:", self._amount)

        self._delay = _NoWheelSpin()
        self._delay.setRange(0, 1000)
        self._delay.setSuffix(" ms")
        self._delay.setValue(p.get("delay_ms", 30))
        form.addRow("間隔:", self._delay)

    def save(self):
        self._step.params["direction"] = self._direction.currentData()
        self._step.params["amount"] = self._amount.value()
        self._step.params["delay_ms"] = self._delay.value()


class _CompareStepForm(QWidget):
    def __init__(
        self,
        parent_list,
        step,
        idx,
        roi_cb,
        rules_provider=None,
        exclude_rule_id="",
        simplified=False,
        step_count=0,
        groups_provider=None,
    ):
        super().__init__()
        self._list = parent_list
        self._step = step
        self._idx = idx
        self._roi_cb = roi_cb
        self._rules_provider = rules_provider
        self._exclude_rule_id = exclude_rule_id
        self._groups_provider = groups_provider
        self._step_count = step_count
        self._on_fail_expanded = False
        p = step.params
        form = QFormLayout(self)
        form.setContentsMargins(12, 6, 12, 6)

        # ROI
        roi = p.get("roi", {})
        self._roi = {
            "x": roi.get("x", 0),
            "y": roi.get("y", 0),
            "w": roi.get("w", 0),
            "h": roi.get("h", 0),
        }
        z = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        self._roi_label = QLabel("全視窗" if z else _fmt_roi(roi))
        self._roi_btn = QPushButton("框選偵測區域")
        self._roi_btn.setToolTip("框選要進行 OCR 的區域，不設定時掃描整個視窗")
        self._roi_btn.clicked.connect(self._pick_roi)
        roi_row = QWidget()
        rr = QHBoxLayout(roi_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.addWidget(self._roi_label)
        rr.addWidget(self._roi_btn)
        form.addRow("偵測區域:", roi_row)

        # Operator
        self._operator = _NoWheelCombo()
        for op in (">", "<", ">=", "<=", "==", "!="):
            self._operator.addItem(op, op)
        op_idx = self._operator.findData(p.get("operator", ">="))
        if op_idx >= 0:
            self._operator.setCurrentIndex(op_idx)
        form.addRow("運算子:", self._operator)

        # Value
        self._value = _NoWheelDoubleSpin()
        self._value.setRange(-999999.0, 999999.0)
        self._value.setDecimals(3)
        self._value.setValue(p.get("value", 0.0))
        form.addRow("數值:", self._value)

        # ── Advanced collapsible section ──
        self._toggle_btn = QPushButton("▶ 進階：比對規則與失敗處理")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet(
            "QPushButton { text-align: left; border: none; color: #888; }"
        )
        self._toggle_btn.clicked.connect(self._toggle_advanced)
        form.addRow(self._toggle_btn)

        self._adv_container = QWidget()
        self._adv_container.setVisible(False)
        adv = QFormLayout(self._adv_container)
        adv.setContentsMargins(0, 0, 0, 0)

        self._pattern = QLineEdit()
        self._pattern.setText(p.get("pattern", r"-?\d+\.?\d*"))
        self._pattern.setToolTip("正則表達式，用於從 OCR 文字中擷取數字")
        adv.addRow("比對規則 (regex):", self._pattern)

        # on_fail section (same as detect/match_image)
        self._of_action = _NoWheelCombo()
        self._of_action.addItem("跳過本次（預設）", "stop")
        self._of_action.addItem("跳至步驟", "skip")
        self._of_action.addItem("跳轉至規則", "jump")
        self._of_action.addItem("按下按鍵後繼續", "key")
        self._of_action.addItem("通知並停止群組", "notify")
        raw_of = p.get("on_fail", "stop")
        default_notify_msg = ""
        default_notify_groups: list[str] = []
        of_act = raw_of.get("action", "stop") if isinstance(raw_of, dict) else raw_of
        if isinstance(raw_of, dict) and raw_of.get("action") == "notify":
            default_notify_msg = raw_of.get("message", "")
            default_notify_groups = raw_of.get("stop_groups", [])
        of_idx = self._of_action.findData(of_act)
        if of_idx >= 0:
            self._of_action.setCurrentIndex(of_idx)
        self._of_action.currentIndexChanged.connect(self._on_of_action_changed)
        adv.addRow("失敗動作:", self._of_action)

        self._of_jump_combo = _NoWheelCombo()
        self._of_jump_combo.setMinimumWidth(200)
        rules = rules_provider() if rules_provider else []
        target_id = raw_of.get("rule_id", "") if isinstance(raw_of, dict) else ""
        for r in rules:
            if r.id != exclude_rule_id:
                self._of_jump_combo.addItem(r.name, r.id)
        j_idx = self._of_jump_combo.findData(target_id)
        if j_idx >= 0:
            self._of_jump_combo.setCurrentIndex(j_idx)
        elif target_id:
            self._of_jump_combo.addItem(f"(遺失: {target_id})", target_id)
            j_idx = self._of_jump_combo.count() - 1
            self._of_jump_combo.setCurrentIndex(max(j_idx, 0))
        jf = QWidget()
        jl = QHBoxLayout(jf)
        jl.setContentsMargins(0, 0, 0, 0)
        jl.addWidget(self._of_jump_combo)
        self._of_jump_row = jf
        adv.addRow("", self._of_jump_row)

        skip_to = (
            raw_of.get("skip_to", self._step_count)
            if isinstance(raw_of, dict)
            else self._step_count
        )
        self._of_skip_combo = _NoWheelCombo()
        self._populate_skip_combo(skip_to)
        self._of_skip_row = QWidget()
        skf = QHBoxLayout(self._of_skip_row)
        skf.setContentsMargins(0, 0, 0, 0)
        skf.addWidget(QLabel("跳至"))
        skf.addWidget(self._of_skip_combo)
        skf.addStretch()
        adv.addRow("", self._of_skip_row)

        self._of_key = _make_key_combo()
        kv = raw_of.get("key", "") if isinstance(raw_of, dict) else ""
        k_idx = self._of_key.findData(kv)
        if k_idx >= 0:
            self._of_key.setCurrentIndex(k_idx)
        self._of_key_row = QWidget()
        kf = QHBoxLayout(self._of_key_row)
        kf.setContentsMargins(0, 0, 0, 0)
        kf.addWidget(self._of_key)
        adv.addRow("", self._of_key_row)

        # notify widgets
        self._of_notify_msg = QLineEdit()
        self._of_notify_msg.setPlaceholderText("例如：每日探索次數已為空，已停止流程")
        adv.addRow("通知訊息:", self._of_notify_msg)
        self._of_notify_msg.setText(default_notify_msg)
        self._of_notify_groups = _StopGroupsPicker(
            groups_provider=groups_provider,
            selected=default_notify_groups,
        )
        adv.addRow("停止群組:", self._of_notify_groups)

        form.addRow(self._adv_container)

        self._on_of_action_changed()
        self._adv_container.setVisible(not simplified)
        self._on_fail_container = self._adv_container

    def _populate_skip_combo(self, current_skip_to: int):
        self._of_skip_combo.clear()
        self._of_skip_combo.addItem("本規則結束", self._step_count)
        start = self._idx + 2
        for i in range(start, self._step_count + 1):
            self._of_skip_combo.addItem(f"步驟{i}", i - 1)
        if current_skip_to >= 0:
            idx_s = self._of_skip_combo.findData(current_skip_to)
            if idx_s >= 0:
                self._of_skip_combo.setCurrentIndex(idx_s)

    def save(self):
        self._step.params["roi"] = {
            "x": self._roi.get("x", 0),
            "y": self._roi.get("y", 0),
            "w": self._roi.get("w", 0),
            "h": self._roi.get("h", 0),
        }
        if "roi_coord" in self._roi:
            self._step.params["roi"]["roi_coord"] = self._roi["roi_coord"]
        self._step.params["operator"] = self._operator.currentData()
        self._step.params["value"] = self._value.value()
        self._step.params["pattern"] = self._pattern.text().strip()
        action = self._of_action.currentData()
        if action == "stop":
            self._step.params["on_fail"] = "stop"
        elif action == "skip":
            self._step.params["on_fail"] = {
                "action": "skip",
                "skip_to": self._of_skip_combo.currentData() or 0,
            }
        elif action == "jump":
            self._step.params["on_fail"] = {
                "action": "jump",
                "rule_id": self._of_jump_combo.currentData() or "",
            }
        elif action == "key":
            self._step.params["on_fail"] = {
                "action": "key",
                "key": self._of_key.currentData() or self._of_key.currentText(),
            }
        elif action == "notify":
            selected_ids = self._of_notify_groups.selected_ids()
            self._step.params["on_fail"] = {
                "action": "notify",
                "message": self._of_notify_msg.text().strip(),
                "stop_groups": selected_ids,
            }

    def _pick_roi(self):
        if not self._roi_cb:
            return
        result = self._roi_cb()
        if result:
            self._roi = {
                "x": result.get("x", 0),
                "y": result.get("y", 0),
                "w": result.get("w", 0),
                "h": result.get("h", 0),
            }
            z = all(v == 0 for v in self._roi.values())
            self._roi_label.setText("全視窗" if z else _fmt_roi(self._roi))
            self.save()
            self._list.steps_changed.emit()

    def _toggle_advanced(self):
        expanded = self._adv_container.isVisible()
        self._adv_container.setVisible(not expanded)
        self._toggle_btn.setText(
            "▼ 進階：比對規則與失敗處理" if not expanded else "▶ 進階：比對規則與失敗處理"
        )

    def _on_of_action_changed(self, idx=None):
        action = self._of_action.currentData()
        self._of_skip_row.setVisible(action == "skip")
        self._of_jump_row.setVisible(action == "jump")
        self._of_key_row.setVisible(action == "key")
        is_notify = action == "notify"
        self._of_notify_msg.setVisible(is_notify)
        self._of_notify_groups.setVisible(is_notify)


class _KeyStepForm(QWidget):
    def __init__(self, parent_list, step, idx):
        super().__init__()
        self._list = parent_list
        self._step = step
        form = QFormLayout(self)
        form.setContentsMargins(12, 6, 12, 6)

        self._key = _make_key_combo()
        k = step.params.get("key", "")
        k_idx = self._key.findData(k)
        if k_idx >= 0:
            self._key.setCurrentIndex(k_idx)
        form.addRow("按鍵:", self._key)

        self._hold_ms = _NoWheelSpin()
        self._hold_ms.setRange(0, 60000)
        self._hold_ms.setSuffix(" ms")
        self._hold_ms.setValue(step.params.get("hold_ms", 0))
        self._hold_ms.setToolTip("0 = 立即按下放開，>0 = 按住指定毫秒後放開")
        form.addRow("按住 (0=立即放開):", self._hold_ms)

    def save(self):
        self._step.params["key"] = self._key.currentData() or self._key.currentText()
        self._step.params["hold_ms"] = self._hold_ms.value()


class _WaitStepForm(QWidget):
    def __init__(self, parent_list, step, idx):
        super().__init__()
        self._list = parent_list
        self._step = step
        form = QFormLayout(self)
        form.setContentsMargins(12, 6, 12, 6)

        self._ms = _NoWheelSpin()
        self._ms.setRange(0, 60000)
        self._ms.setSuffix(" ms")
        self._ms.setValue(step.params.get("ms", 500))
        self._ms.editingFinished.connect(lambda: self._list.steps_changed.emit())
        form.addRow("毫秒:", self._ms)

    def save(self):
        self._step.params["ms"] = self._ms.value()


class _JumpStepForm(QWidget):
    def __init__(self, parent_list, step, idx, rules_provider=None, exclude_rule_id=""):
        super().__init__()
        self._list = parent_list
        self._step = step
        form = QFormLayout(self)
        form.setContentsMargins(12, 6, 12, 6)

        self._combo = _NoWheelCombo()
        rules = rules_provider() if rules_provider else []
        current_id = step.params.get("rule_id", "")
        for r in rules:
            if r.id != exclude_rule_id:
                self._combo.addItem(r.name, r.id)
        idx_r = self._combo.findData(current_id)
        if idx_r >= 0:
            self._combo.setCurrentIndex(idx_r)
        elif current_id:
            self._combo.addItem(f"(未知: {current_id})", current_id)
            self._combo.setCurrentIndex(self._combo.count() - 1)
        form.addRow("跳轉至規則:", self._combo)

    def save(self):
        self._step.params["rule_id"] = self._combo.currentData() or ""


class _InlineActionEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, action: dict, pick_cb=None):
        super().__init__()
        self._pick_cb = pick_cb
        action = action if isinstance(action, dict) else {}
        self._x = int(action.get("x", 0) or 0)
        self._y = int(action.get("y", 0) or 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._type = _NoWheelCombo()
        self._type.addItem("按鍵", "key")
        self._type.addItem("點擊", "click")
        idx = self._type.findData(action.get("type", "key"))
        if idx >= 0:
            self._type.setCurrentIndex(idx)
        self._type.currentIndexChanged.connect(self._sync_visible)
        layout.addWidget(self._type)

        self._key = _make_key_combo()
        key = action.get("key", "")
        key_idx = self._key.findData(key)
        if key_idx >= 0:
            self._key.setCurrentIndex(key_idx)
        layout.addWidget(self._key)

        self._click_row = QWidget()
        click_layout = QHBoxLayout(self._click_row)
        click_layout.setContentsMargins(0, 0, 0, 0)
        self._coord_label = QLabel(self._coord_text())
        self._pick_btn = QPushButton("選取座標")
        self._pick_btn.setEnabled(bool(pick_cb))
        self._pick_btn.clicked.connect(self._pick_coord)
        self._button = _NoWheelCombo()
        self._button.addItem("左鍵", "left")
        self._button.addItem("右鍵", "right")
        btn_idx = self._button.findData(action.get("button", "left"))
        if btn_idx >= 0:
            self._button.setCurrentIndex(btn_idx)
        click_layout.addWidget(self._coord_label)
        click_layout.addWidget(self._pick_btn)
        click_layout.addWidget(self._button)
        layout.addWidget(self._click_row)
        self._sync_visible()

    def _coord_text(self) -> str:
        return f"X: {self._x}, Y: {self._y}"

    def _sync_visible(self):
        is_key = self._type.currentData() == "key"
        self._key.setVisible(is_key)
        self._click_row.setVisible(not is_key)

    def _pick_coord(self):
        if not self._pick_cb:
            return
        result = self._pick_cb()
        if result:
            self._x, self._y = result
            self._coord_label.setText(self._coord_text())
            self._type.setCurrentIndex(self._type.findData("click"))
            self.changed.emit()

    def value(self) -> dict:
        if self._type.currentData() == "click":
            return {
                "type": "click",
                "x": self._x,
                "y": self._y,
                "button": self._button.currentData() or "left",
            }
        return {"type": "key", "key": self._key.currentData() or self._key.currentText()}


_ahk_mod = load_sibling("ahk_socket", "core/03_ahk_socket.py")
_main_loop_mod = load_sibling("main_loop", "core/05_main_loop.py")
MainLoop = _main_loop_mod.MainLoop

Rule = _main_loop_mod.Rule
list_windows = _main_loop_mod.list_windows
load_rules = _main_loop_mod.load_rules
save_rules = _main_loop_mod.save_rules
activate_window = _main_loop_mod.activate_window
get_window_rect = _main_loop_mod.get_window_rect
get_window_client_offset = getattr(_main_loop_mod, "get_window_client_offset", lambda title: None)
capture = _main_loop_mod.capture
recognize = _main_loop_mod.recognize
find_text = _main_loop_mod.find_text
poll_roi_value = _main_loop_mod.poll_roi_value
crop_roi = _main_loop_mod.crop_roi
capture_window_content = getattr(_main_loop_mod, "capture_window_content", lambda title: None)

_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
list_tasks = _rule_mod.list_tasks
load_task = _rule_mod.load_task
save_task = _rule_mod.save_task
delete_task = _rule_mod.delete_task
get_task_window = _rule_mod.get_task_window
set_task_window = _rule_mod.set_task_window
get_run_mode = _rule_mod.get_run_mode
set_run_mode = _rule_mod.set_run_mode
rename_task = _rule_mod.rename_task
export_task = _rule_mod.export_task
import_task = _rule_mod.import_task
preview_import_task = _rule_mod.preview_import_task
ImportPreview = _rule_mod.ImportPreview
migrate_old_rules = _rule_mod.migrate_old_rules
Step = _rule_mod.Step
RuleGroup = _rule_mod.RuleGroup
load_groups = _rule_mod.load_groups
save_groups = _rule_mod.save_groups
_STEP_DEFAULTS = _rule_mod._STEP_DEFAULTS
_MAX_IMPORT_SIZE = _rule_mod._MAX_IMPORT_SIZE

_ocr_debug_mod = load_sibling("ocr_debug", "gui/09_ocr_debug.py")
OcrDebugPanel = _ocr_debug_mod.OcrDebugPanel

_ocr_mod = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_perf_mod = load_sibling("performance_monitor", "core/10_performance_monitor.py")
_tmpl_mod = load_sibling("template_matching", "core/11_template_matching.py")
img_to_b64 = _tmpl_mod.img_to_b64
b64_to_img = _tmpl_mod.b64_to_img

# ── Helpers ──


def _tasks_dir() -> str:
    mod = load_sibling("rule_engine", "core/04_rule_engine.py")
    return str(mod.get_tasks_dir())


def _get_images_dir() -> Path:
    """Return writable images directory — project root in dev, %APPDATA% when packaged."""
    if hasattr(sys, "_MEIPASS"):
        try:
            from build import get_data_path

            return Path(get_data_path("images"))
        except ImportError:
            pass
    return Path(__file__).resolve().parent.parent / "images"


class WorkerSignals(QObject):
    trigger_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)
    warning_signal = pyqtSignal(str)
    info_signal = pyqtSignal(str)
    window_lost_signal = pyqtSignal()
    emergency_signal = pyqtSignal()
    test_done_signal = pyqtSignal(dict)
    finished = pyqtSignal(bool, str)


class InitWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(
        self,
        rules_path: str,
        window_title: str,
        signals: WorkerSignals,
        verbose: bool = True,
        active_group_ids: Optional[list[str]] = None,
    ):
        super().__init__()
        self._rules_path = rules_path
        self._window_title = window_title
        self._signals = signals
        self._verbose = verbose
        self._active_group_ids = active_group_ids or []
        self.loop: Optional[MainLoop] = None

    def run(self):
        try:
            loop = MainLoop(
                self._rules_path,
                self._window_title,
                verbose=self._verbose,
            )
            if self._active_group_ids:
                loop.set_active_groups(self._active_group_ids)
            loop.on_trigger = lambda log: self._signals.trigger_signal.emit(log)
            loop.on_error = lambda msg: self._signals.error_signal.emit(msg)
            loop.on_warning = lambda msg: self._signals.warning_signal.emit(msg)
            loop.on_info = lambda msg: self._signals.info_signal.emit(msg)
            loop.on_window_lost = lambda: self._signals.window_lost_signal.emit()
            loop.on_emergency = lambda: self._signals.emergency_signal.emit()
            loop.on_finished = lambda: self._signals.finished.emit(True, "")
            loop.start()
            self.loop = loop
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


def _pixels_to_ratio_expanded(
    px: int, py: int, pw: int, ph: int, ww: int, wh: int, margin: float = 0.2
) -> dict:
    margin_w = max(pw * margin, ww * 0.01)
    margin_h = max(ph * margin, wh * 0.01)
    return {
        "x": max(0.0, min(1.0, (px - margin_w) / ww)),
        "y": max(0.0, min(1.0, (py - margin_h) / wh)),
        "w": max(0.0, min(1.0, (pw + 2 * margin_w) / ww)),
        "h": max(0.0, min(1.0, (ph + 2 * margin_h) / wh)),
    }


class SettingsDialog(QDialog):
    def __init__(self, config_path: str, parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self.setWindowTitle("偏好設定")
        self.setMinimumWidth(350)

        config = self._load_config()
        form = QFormLayout(self)

        self._behavior = QComboBox()
        self._behavior.addItem("縮小至系統托盤", "tray")
        self._behavior.addItem("直接關閉程式", "quit")
        self._behavior.setCurrentIndex(0 if config.get("close_behavior", "tray") == "tray" else 1)
        form.addRow("關閉按鈕行為:", self._behavior)

        self._show_confirm = QCheckBox("關閉前顯示確認視窗（可勾選不再提醒）")
        self._show_confirm.setChecked(config.get("show_close_confirm", True))
        form.addRow("", self._show_confirm)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _load_config(self) -> dict:
        try:
            with open(self._config_path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save_config(self, data: dict):
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _on_accept(self):
        config = self._load_config()
        config["close_behavior"] = self._behavior.currentData()
        config["show_close_confirm"] = self._show_confirm.isChecked()
        self._save_config(config)
        self.accept()


class _NotificationStack(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(4)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._margin = 12

    def push(self, msg: str):
        label = QLabel(msg)
        label.setStyleSheet(
            "background: rgba(50,50,50,230); color: #fff; padding: 6px 10px; "
            "border-radius: 4px; font: 9pt;"
        )
        label.setWordWrap(True)
        label.setMaximumWidth(320)
        self._layout.addWidget(label)
        self._reposition()
        self.show()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda lbl=label, t=timer: self._pop(lbl, t))
        timer.start(2000)

    def _pop(self, label, timer):
        timer.stop()
        timer.deleteLater()
        self._layout.removeWidget(label)
        label.deleteLater()
        self._reposition()
        if self._layout.count() == 0:
            self.hide()

    def _reposition(self):
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        ag = screen.availableGeometry()
        self.move(
            ag.right() - self.width() - self._margin, ag.bottom() - self.height() - self._margin
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"OCR Trigger Clicker v{__version__}")
        self.resize(900, 650)

        try:
            from build import get_data_path

            self._config_path = get_data_path("config.json")
        except ImportError:
            here = Path(__file__).resolve().parent.parent
            self._config_path = str(here / "config.json")

        try:
            migrate_old_rules()

            self._signals = WorkerSignals()
            self._loop: Optional[MainLoop] = None
            self._selected_rule_id: Optional[str] = None
            self._window_lost = False
            self._current_task: str = ""
            self._groups: list[RuleGroup] = []
            self._collapsed_groups: set[str] = set()
            self._simplified_mode = False
            self._notif_stack = _NotificationStack()

            self._setup_ui()
            self._debug_panel = OcrDebugPanel("", self)
            self._debug_panel.rule_requested.connect(self._on_debug_rule_requested)
            self._debug_panel.step_requested.connect(self._on_debug_step_requested)
            self._debug_page_layout.addWidget(self._debug_panel, 1)
            self._connect_signals()
            self._setup_shortcuts()

            _ocr_mod.set_ocr_health_callback(self._on_ocr_health)

            self._refresh_window_list()
            self._restore_last_state()
            self._refresh_task_list()
            self._maybe_show_startup_guide()

            if not _ahk_mod.is_ahk_available():
                reply = QMessageBox.question(
                    self,
                    "安裝 AutoHotkey",
                    "此工具需要 AutoHotkey v2 來執行滑鼠點擊與鍵盤操作。\n"
                    "是否自動下載並安裝？（約 3MB，不需管理員權限）",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._status_bar.showMessage("正在下載 AutoHotkey v2 ...")
                    QApplication.processEvents()
                    _ahk_mod.set_ahk_health_callback(
                        lambda msg: self._status_bar.showMessage(f"⚠ {msg}")
                    )
                    if _ahk_mod.download_ahk():
                        self._status_bar.showMessage("AutoHotkey 下載完成")
                    else:
                        QMessageBox.critical(
                            self,
                            "AutoHotkey 下載失敗",
                            "AutoHotkey 下載失敗，請手動下載並安裝：\n"
                            "https://www.autohotkey.com\n\n"
                            "安裝後重新啟動工具即可自動偵測。",
                        )

            self._ahk_ready = _ahk_mod.init_ahk()
            if not self._ahk_ready:
                self._status_bar.showMessage("⚠ AHK 未啟動，點擊功能將無法使用")
        except Exception as e:
            QMessageBox.critical(self, "啟動失敗", f"初始化過程中發生錯誤：\n{e}")
            raise

        # ── 系統托盤 ──
        _icon_path = Path(__file__).resolve().parent.parent / "icons" / "app.ico"
        _app_icon = QIcon(str(_icon_path)) if _icon_path.exists() else QIcon()
        self.setWindowIcon(_app_icon)
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_app_icon)
        self._tray.setToolTip("OCR Trigger Clicker")
        _tray_menu = QMenu(self)
        _tray_menu.addAction("顯示視窗", self._restore_window)
        _tray_menu.addAction("設定...", self._open_settings)
        _tray_menu.addSeparator()
        _tray_menu.addAction("離開", self._quit_app)
        self._tray.setContextMenu(_tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _load_config(self) -> dict:
        try:
            with open(self._config_path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save_config(self, data: dict):
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _maybe_show_startup_guide(self):
        config = self._load_config()
        if config.get("hide_startup_guide", False):
            return

        box = QMessageBox(self)
        box.setWindowTitle("新手導覽")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("要先看一次新手教學嗎？")
        box.setInformativeText(
            "教學頁會帶你完成第一次使用：選視窗、建立規則、看 OCR 診斷、再啟動。\n"
            "你也可以之後從「新手教學」按鈕打開。"
        )
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("打開教學")
        box.button(QMessageBox.StandardButton.No).setText("先略過")
        checkbox = QCheckBox("不再顯示此提示")
        box.setCheckBox(checkbox)
        result = box.exec()
        if checkbox.isChecked():
            config["hide_startup_guide"] = True
            self._save_config(config)
        if result == QMessageBox.StandardButton.Yes:
            self._open_guide()

    def _restore_last_state(self):
        config = self._load_config()

        last_win = config.get("last_window", "")
        if last_win:
            idx = self._window_combo.findText(last_win)
            if idx >= 0:
                self._window_combo.setCurrentIndex(idx)
            else:
                self._window_combo.setPlaceholderText(
                    f"⚠ 上次的視窗「{last_win}」已不存在，請重新選擇"
                )
                self._status_bar.showMessage(f"⚠ 上次的視窗「{last_win}」已不存在")
        last_task = config.get("last_task", "")
        if last_task:
            idx = self._task_combo.findText(last_task)
            if idx >= 0:
                self._task_combo.setCurrentIndex(idx)

        simplified = config.get("simplified_mode", False)
        if simplified:
            self._simplified_btn.setChecked(True)
            self._simplified_btn.setText("簡易")
            self._simplified_btn.setToolTip("目前為簡易模式，點擊切換至進階模式")
            self._simplified_mode = True
            self._step_list.set_simplified_mode(True)
            self._step_list._rebuild()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)

        # === Top toolbar ===
        toolbar = QHBoxLayout()

        # -- Window section --
        self._window_combo = _WindowCombo(self._refresh_window_list)
        self._window_combo.setMinimumWidth(250)
        self._window_combo.setPlaceholderText("請選擇目標視窗")
        toolbar.addWidget(QLabel("視窗:"))
        toolbar.addWidget(self._window_combo)

        toolbar.addSpacing(8)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        toolbar.addWidget(sep)
        toolbar.addSpacing(8)

        # -- Task section --
        self._task_combo = _NoWheelCombo()
        self._task_combo.setMinimumWidth(160)
        self._task_combo.setToolTip("切換任務 — 每個任務包含一組獨立的規則")
        self._task_new_btn = QPushButton("＋")
        self._task_new_btn.setFixedWidth(28)
        self._task_new_btn.setToolTip("建立新任務")
        self._task_rename_btn = QPushButton("✏️")
        self._task_rename_btn.setFixedWidth(28)
        self._task_rename_btn.setToolTip("重新命名當前任務")
        self._task_del_btn = QPushButton("🗑")
        self._task_del_btn.setFixedWidth(28)
        self._task_del_btn.setToolTip("刪除當前任務")
        self._task_import_btn = QPushButton("📥匯入任務")
        self._task_import_btn.setToolTip("從 .json 檔案匯入任務")
        self._task_export_btn = QPushButton("📤匯出任務")
        self._task_export_btn.setToolTip("將目前任務匯出為 .json 檔案")
        toolbar.addWidget(QLabel("任務:"))
        toolbar.addWidget(self._task_combo)
        toolbar.addWidget(self._task_new_btn)
        toolbar.addWidget(self._task_rename_btn)
        toolbar.addWidget(self._task_del_btn)
        toolbar.addWidget(self._task_import_btn)
        toolbar.addWidget(self._task_export_btn)

        # -- Action section --
        self._btn_toggle = QPushButton("啟動")
        self._btn_toggle.setMinimumWidth(80)
        self._btn_toggle.setToolTip("開始偵測所選視窗")
        self._debug_btn = QPushButton("🔍OCR 診斷")
        self._debug_btn.setToolTip("即時顯示視窗內所有辨識到的文字與位置")
        toolbar.addWidget(self._btn_toggle)
        toolbar.addWidget(self._debug_btn)
        toolbar.addStretch()
        self._sponsor_btn = QPushButton("♥")
        self._sponsor_btn.setFixedSize(28, 28)
        self._sponsor_btn.setToolTip("贊助開發者 ❤️")
        self._sponsor_btn.setStyleSheet(
            """
            QPushButton {
                background: #fce4ec;
                color: #e91e63;
                font-size: 18px;
                border: 1px solid #f8bbd0;
                border-radius: 14px;
            }
            QPushButton:hover {
                background: #f8bbd0;
                color: #c2185b;
            }
            """
        )
        self._sponsor_btn.clicked.connect(self._open_sponsor)
        toolbar.addWidget(self._sponsor_btn)
        self._about_btn = QPushButton("關於")
        self._about_btn.setToolTip(f"OCR Trigger Clicker v{__version__} — 作者: {__author__}")
        self._about_btn.clicked.connect(self._show_about)
        toolbar.addWidget(self._about_btn)
        self._guide_btn = QPushButton("新手教學")
        self._guide_btn.setToolTip("開啟 GitHub Pages 的互動式使用指引")
        self._guide_btn.clicked.connect(self._open_guide)
        toolbar.addWidget(self._guide_btn)
        self._simplified_btn = QPushButton("進階")
        self._simplified_btn.setCheckable(True)
        self._simplified_btn.setChecked(False)
        self._simplified_btn.setToolTip("目前為進階模式，點擊切換至簡易模式")
        self._simplified_btn.clicked.connect(self._toggle_simplified_mode)
        toolbar.addWidget(self._simplified_btn)
        layout.addLayout(toolbar)

        # === Middle: stacked pages (rules / OCR debug) ===
        self._main_stack = QStackedWidget()

        # -- Page 0: rules --
        rules_page = QWidget()
        rules_layout = QHBoxLayout(rules_page)
        rules_layout.setContentsMargins(0, 0, 0, 0)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("規則列表"))

        self._rule_list = _RuleTreeWidget()
        self._rule_list.setMinimumWidth(180)
        self._rule_list.setHeaderHidden(True)
        self._rule_list.setAnimated(True)
        self._rule_list.setIndentation(20)
        self._rule_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._rule_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._rule_list.setMouseTracking(True)
        self._rule_list.setColumnCount(2)
        hdr = self._rule_list.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(1, 80)
        self._rule_list.customContextMenuRequested.connect(self._on_rule_context_menu)
        left_layout.addWidget(self._rule_list)

        self._rule_hint = QLabel("← 點擊「新增」建立第一條規則")
        self._rule_hint.setStyleSheet("color: #888; font-size: 11px;")
        left_layout.addWidget(self._rule_hint)

        rule_btn_bar = QHBoxLayout()
        self._add_group_btn = QPushButton("+ 群組")
        self._add_group_btn.setToolTip("新增一個群組")
        self._add_rule_btn = QPushButton("+ 規則")
        self._add_rule_btn.setToolTip("新增一條空白規則 (Ctrl+N)")
        self._del_rule_btn = QPushButton("刪除 (Del)")
        self._del_rule_btn.setToolTip("刪除目前選取的項目 (Del)")
        rule_btn_bar.addWidget(self._add_group_btn)
        rule_btn_bar.addWidget(self._add_rule_btn)
        rule_btn_bar.addWidget(self._del_rule_btn)
        left_layout.addLayout(rule_btn_bar)

        rules_layout.addWidget(left_widget, 1)

        # Right: stacked edit panel (guide / form)
        self._edit_stack = QStackedWidget()

        # -- Page 0: guide --
        guide_page = QWidget()
        guide_layout = QVBoxLayout(guide_page)
        guide_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        guide_label = QLabel(
            "使用步驟\n\n"
            "① 選擇目標視窗\n"
            "② 點擊「新增」建立規則\n"
            "③ 設定觸發文字與點擊參數\n"
            "④ 點擊「儲存規則」\n"
            "⑤ 點擊「啟動」開始自動偵測\n\n"
            "框選偵測區域可限制 OCR 範圍\n\n"
            "▸ 進階技巧：步驟依序執行。每個步驟可設定「找不到時」的動作，\n"
            "  例如 match_image 沒找到就跳過 detect，直接執行 key。\n"
            "  試試 match_image → detect → click 三層連鎖！"
        )
        guide_label.setStyleSheet("color: #666; font-size: 13px;")
        guide_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        guide_layout.addWidget(guide_label)
        self._edit_stack.addWidget(guide_page)

        # -- Page 1: step-based edit form --
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._edit_panel = QWidget()
        edit_layout = QVBoxLayout(self._edit_panel)
        edit_layout.setContentsMargins(4, 4, 4, 4)

        # Name + enabled header
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("名稱:"))
        self._edit_name = QLineEdit()
        name_row.addWidget(self._edit_name, 1)
        name_row.addWidget(QLabel("啟用:"))
        self._edit_enabled = QCheckBox()
        name_row.addWidget(self._edit_enabled)
        name_row.addWidget(QLabel("背景:"))
        self._edit_background = QCheckBox("常駐監控")
        self._edit_background.setToolTip(
            "常駐監控：每幀獨立偵測，不參與群組流程順序。\n適合隨時需要攔截的條件（如錯誤提示、緊急中斷）"
        )
        name_row.addWidget(self._edit_background)
        edit_layout.addLayout(name_row)

        edit_layout.addWidget(QLabel("步驟列表:"))

        self._step_list = _StepListWidget()
        self._step_list.set_roi_callback(self._open_roi_selector)
        self._step_list.set_capture_callback(self._open_capture_region)
        self._step_list.set_click_pick_callback(self._on_pick_coord)
        self._step_list.set_rules_provider(lambda: list(self._rules))
        self._step_list.set_groups_provider(lambda: self._groups)
        self._step_list.set_window_title_callback(lambda: self._window_combo.currentText())
        self._step_list.set_task_path_callback(
            lambda: (
                str(Path(_tasks_dir()) / f"{self._current_task}.json") if self._current_task else ""
            )
        )
        edit_layout.addWidget(self._step_list, 1)

        # Add step dropdown
        add_dropdown = QPushButton("+ 新增步驟 ▾")
        add_dropdown.setToolTip(
            "新增步驟至規則 — 步驟依序執行，可在進階設定中指定失敗時跳至後續步驟"
        )
        add_menu = QMenu(self)
        step_types = [
            ("detect", "🔍 偵測文字"),
            ("match_image", "🖼 圖示辨識"),
            ("compare", "🔢 數字比較"),
            ("click", "🖱 點擊"),
            ("key", "⌨ 按鍵"),
            ("drag", "↗ 拖曳"),
            ("scroll", "↕ 滾輪"),
            ("wait", "⏱ 等待"),
            ("jump", "↩ 跳轉規則"),
        ]
        for st, label in step_types:
            action = add_menu.addAction(label)
            action.setData(st)
            action.triggered.connect(lambda checked, t=st: self._add_step(t))
        add_dropdown.setMenu(add_menu)
        edit_layout.addWidget(add_dropdown)

        # Save indicator + Test
        self._saved_label = QLabel("✓ 已儲存")
        self._saved_label.setStyleSheet("color: #4caf50; font-weight: bold;")
        self._saved_label.setVisible(False)
        self._edit_test_btn = QPushButton("▶ 測試")
        self._edit_test_btn.setEnabled(False)
        self._edit_test_btn.setVisible(False)
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addWidget(self._saved_label)
        btn_layout.addWidget(self._edit_test_btn)
        btn_layout.addStretch()
        edit_layout.addWidget(btn_row)

        scroll.setWidget(self._edit_panel)
        self._edit_stack.addWidget(scroll)
        self._edit_stack.setCurrentIndex(0)
        rules_layout.addWidget(self._edit_stack, 2)

        self._main_stack.addWidget(rules_page)

        # -- Page 1: OCR debug --
        self._debug_page = QWidget()
        debug_page_layout = QVBoxLayout(self._debug_page)
        debug_page_layout.setContentsMargins(0, 0, 0, 0)
        debug_top_bar = QHBoxLayout()
        self._debug_back_btn = QPushButton("← 返回規則")
        debug_top_bar.addWidget(self._debug_back_btn)
        debug_top_bar.addStretch()
        debug_page_layout.addLayout(debug_top_bar)
        self._debug_page_layout = debug_page_layout

        self._main_stack.addWidget(self._debug_page)
        self._main_stack.setCurrentIndex(0)
        layout.addWidget(self._main_stack)

        # === Compare log panel ===
        self._compare_log_toggle = QPushButton("▸ 比較輪次日誌")
        self._compare_log_toggle.setCheckable(True)
        self._compare_log_toggle.setChecked(False)
        self._compare_log_toggle.clicked.connect(self._toggle_compare_log)
        self._compare_log_widget = QListWidget()
        self._compare_log_widget.setMaximumHeight(120)
        self._compare_log_widget.setVisible(False)
        layout.addWidget(self._compare_log_toggle)
        layout.addWidget(self._compare_log_widget)

        # === Trigger log panel ===
        self._trigger_log_toggle = QPushButton("▸ 觸發記錄")
        self._trigger_log_toggle.setCheckable(True)
        self._trigger_log_toggle.setChecked(False)
        self._trigger_log_toggle.clicked.connect(self._toggle_trigger_log)
        self._trigger_log_widget = QListWidget()
        self._trigger_log_widget.setMaximumHeight(100)
        self._trigger_log_widget.setVisible(False)
        layout.addWidget(self._trigger_log_toggle)
        layout.addWidget(self._trigger_log_widget)

        # === Status bar ===
        self._status_bar = QStatusBar()
        self._status_bar.showMessage("就緒 — 請選擇視窗並新增規則")
        self._perf_label = QLabel("FPS:-- | CPU:--% | MEM:--MB | 點擊:--/s")
        self._perf_label.setStyleSheet("color: #888; font-size: 11px; padding-right: 8px;")
        self._status_bar.addPermanentWidget(self._perf_label)
        self._perf_timer = QTimer()
        self._perf_timer.timeout.connect(self._update_perf_display)
        self._perf_timer.start(1000)
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_rule_status)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._do_debounced_save)
        self.setStatusBar(self._status_bar)
        QTimer.singleShot(3000, self._check_version)

    def _connect_signals(self):
        self._window_combo.currentTextChanged.connect(self._on_window_changed)
        self._window_combo.currentTextChanged.connect(self._on_window_selected)
        self._btn_toggle.clicked.connect(self._toggle_start)
        self._add_group_btn.clicked.connect(self._add_group)
        self._add_rule_btn.clicked.connect(self._add_rule)
        self._del_rule_btn.clicked.connect(self._delete_rule)
        self._rule_list.currentItemChanged.connect(self._on_rule_selected)
        self._rule_list.itemCollapsed.connect(self._on_rule_item_collapsed)
        self._rule_list.itemExpanded.connect(self._on_rule_item_expanded)
        self._rule_list.itemDoubleClicked.connect(self._on_item_double_clicked)

        self._rule_list.reordered.connect(self._on_rules_reordered)
        self._edit_name.editingFinished.connect(self._on_name_changed)
        self._edit_test_btn.clicked.connect(self._on_test_rule)
        self._edit_enabled.stateChanged.connect(self._on_enabled_changed)
        self._edit_background.stateChanged.connect(self._on_background_changed)
        self._debug_btn.clicked.connect(self._switch_to_debug)
        self._debug_back_btn.clicked.connect(self._switch_to_rules)
        self._task_combo.currentTextChanged.connect(self._on_task_changed)
        self._task_new_btn.clicked.connect(self._on_task_new)
        self._task_rename_btn.clicked.connect(self._on_task_rename)
        self._task_del_btn.clicked.connect(self._on_task_delete)
        self._task_import_btn.clicked.connect(self._on_task_import)
        self._task_export_btn.clicked.connect(self._on_task_export)

        self._step_list.steps_changed.connect(self._on_steps_changed)
        self._signals.window_lost_signal.connect(self._on_window_lost_from_thread)
        self._signals.emergency_signal.connect(self._emergency_stop)
        self._signals.test_done_signal.connect(self._show_test_result)
        self._signals.info_signal.connect(lambda msg: self._status_bar.showMessage(msg, 3000))
        self._signals.warning_signal.connect(
            lambda msg: self._status_bar.showMessage(f"⚠ {msg}", 5000)
        )
        self._signals.warning_signal.connect(self._notif_stack.push)
        self._signals.error_signal.connect(lambda msg: QMessageBox.warning(self, "引擎錯誤", msg))
        self._signals.trigger_signal.connect(self._on_trigger_log_received)
        self._signals.finished.connect(self._on_loop_finished)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+N"), self, self._add_rule)
        QShortcut(QKeySequence("Delete"), self, self._delete_rule)

    def _toggle_simplified_mode(self):
        self._simplified_mode = self._simplified_btn.isChecked()
        self._step_list.set_simplified_mode(self._simplified_mode)
        self._step_list._rebuild()
        if self._simplified_mode:
            self._simplified_btn.setText("簡易")
            self._simplified_btn.setToolTip("目前為簡易模式，點擊切換至進階模式")
        else:
            self._simplified_btn.setText("進階")
            self._simplified_btn.setToolTip("目前為進階模式，點擊切換至簡易模式")
        config = self._load_config()
        config["simplified_mode"] = self._simplified_mode
        self._save_config(config)

    def _on_ocr_health(self, msg: str):
        self._status_bar.showMessage(f"⚠ {msg}", 8000)

    # === Window list ===
    def _on_window_selected(self, title: str):
        if title and self._current_task:
            task_path = str(Path(_tasks_dir()) / f"{self._current_task}.json")
            set_task_window(task_path, title)

    def _refresh_window_list(self):
        self._window_combo.clear()
        windows = list_windows()
        if not windows:
            self._window_combo.setPlaceholderText("⚠ 未發現任何視窗，請先開啟目標程式")
        else:
            self._window_combo.setPlaceholderText("請選擇目標視窗")
            for w in windows:
                self._window_combo.addItem(w)

    # === Last window ===
    def _on_window_changed(self, title: str):
        if not title:
            return
        config = self._load_config()
        config["last_window"] = title
        self._save_config(config)
        if hasattr(self, "_debug_panel") and self._debug_panel is not None:
            self._debug_panel._window_title = title
            self._debug_panel.clear_results()

    def _update_perf_display(self):
        if self._loop is None:
            self._perf_label.setText("FPS:-- | CPU:--% | MEM:--MB | 點擊:--/s")
            return
        stats = self._loop.get_perf_stats()
        fps = stats["fps"]
        cpu = stats["cpu_pct"]
        mem = stats["memory_mb"]
        click_rate = stats["click_rate"]
        text = f"FPS:{fps:.1f} | CPU:{cpu:.0f}% | MEM:{mem:.0f}MB | 點擊:{click_rate:.0f}/s"
        if cpu > 80:
            text += " ⚠CPU"
            self._perf_label.setStyleSheet("color: #e67e22; font-size: 11px; padding-right: 8px;")
        elif mem > 500:
            text += " ⚠MEM"
            self._perf_label.setStyleSheet("color: #e67e22; font-size: 11px; padding-right: 8px;")
        else:
            self._perf_label.setStyleSheet("color: #888; font-size: 11px; padding-right: 8px;")
        self._perf_label.setText(text)

    # === Task list ===
    def _refresh_task_list(self):
        self._task_combo.blockSignals(True)
        self._task_combo.clear()
        for t in list_tasks():
            self._task_combo.addItem(t)
        self._task_combo.blockSignals(False)
        last = self._load_config().get("last_task", "")
        if last:
            idx = self._task_combo.findText(last)
            if idx >= 0:
                self._task_combo.setCurrentIndex(idx)
        if self._task_combo.count() == 0:
            self._on_task_new()
        self._on_task_changed(self._task_combo.currentText())

    def _on_task_changed(self, name: str):
        if self._loop and self._loop.is_running:
            self._flush_save()
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_current_rule()
        if not name:
            logging.debug('[task changed] rules=0, task=""')
            self._rules = []
            self._current_task = ""
            self._refresh_rule_list()
            return
        self._current_task = name
        self._rules = load_task(name)
        logging.debug('[task changed] rules=%d, task="%s"', len(self._rules), name)
        task_path = str(Path(_tasks_dir()) / f"{name}.json")
        self._groups = load_groups(task_path)
        # safety net: remove from uncategorized any rule also in a normal group
        uncat = next((g for g in self._groups if g.id == "__uncategorized__"), None)
        if uncat and uncat.rule_ids:
            normal_ids = set()
            for g in self._groups:
                if g.id != "__uncategorized__":
                    normal_ids.update(g.rule_ids)
            dupes = [rid for rid in uncat.rule_ids if rid in normal_ids]
            for rid in dupes:
                uncat.rule_ids.remove(rid)
            if dupes:
                logging.info("[auto-cleanup] 從未歸類移除 %d 條重複規則", len(dupes))
        # load collapsed state from task file
        self._collapsed_groups = set()
        try:
            p = Path(task_path)
            if p.exists():
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                self._collapsed_groups = set(data.get("_collapsed_groups", []))
        except Exception:
            pass
        config = self._load_config()
        config["last_task"] = name
        self._save_config(config)
        self._refresh_rule_list()
        if hasattr(self, "_debug_panel") and self._debug_panel is not None:
            self._debug_panel.clear_results()
        self._status_bar.showMessage(f"任務「{name}」— {len(self._rules)} 條規則")
        # 自動選取任務綁定的視窗
        task_path = str(Path(_tasks_dir()) / f"{name}.json")
        saved_window = get_task_window(task_path)
        if saved_window:
            idx = self._window_combo.findText(saved_window)
            if idx >= 0:
                self._window_combo.setCurrentIndex(idx)

    def _on_task_new(self):
        from PyQt6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "新任務", "請輸入任務名稱：", text="")
        if not ok or not name.strip():
            return
        name = name.strip()
        existing = list_tasks()
        if name in existing:
            QMessageBox.warning(self, "任務已存在", f"任務「{name}」已經存在。")
            return
        self._groups = [RuleGroup(id="__default__", name="所有規則")]
        save_task(name, [])
        save_groups(self._groups, str(Path(_tasks_dir()) / f"{name}.json"))
        self._refresh_task_list()
        idx = self._task_combo.findText(name)
        if idx >= 0:
            self._task_combo.setCurrentIndex(idx)
        self._status_bar.showMessage(f"已建立任務「{name}」")

    def _on_task_rename(self):
        if not self._current_task:
            return
        from PyQt6.QtWidgets import QInputDialog

        old_name = self._current_task
        name, ok = QInputDialog.getText(self, "重新命名任務", "請輸入新任務名稱：", text=old_name)
        if not ok or not name.strip():
            return
        name = name.strip()
        if name == old_name:
            return
        existing = list_tasks()
        if name in existing:
            QMessageBox.warning(self, "任務已存在", f"任務「{name}」已經存在。")
            return
        self._flush_save()
        if not rename_task(old_name, name):
            QMessageBox.warning(self, "重新命名失敗", "無法重新命名任務。")
            return
        self._refresh_task_list()
        idx = self._task_combo.findText(name)
        if idx >= 0:
            self._task_combo.setCurrentIndex(idx)
        self._status_bar.showMessage(f"任務「{old_name}」已重新命名為「{name}」")

    def _on_task_delete(self):
        if not self._current_task:
            return
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再刪除任務")
            return
        tasks = list_tasks()
        if len(tasks) <= 1:
            QMessageBox.warning(self, "無法刪除", "至少需要保留一個任務。")
            return
        if (
            QMessageBox.question(
                self,
                "刪除任務",
                f"確定刪除任務「{self._current_task}」及其所有規則？\n此操作無法復原。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._flush_save()
        delete_task(self._current_task)
        self._refresh_task_list()

    def _show_import_preview_dialog(self, preview: ImportPreview) -> tuple[bool, bool]:
        """Show import preview dialog. Returns (accepted, regenerate_uuids)."""
        dialog = QDialog(self)
        dialog.setWindowTitle("匯入任務預覽")
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)

        meta = preview.meta
        meta_lines = []
        if meta.get("description"):
            meta_lines.append(f"說明：{meta['description']}")
        if meta.get("author"):
            meta_lines.append(f"作者：{meta['author']}")
        if meta.get("game"):
            meta_lines.append(f"遊戲：{meta['game']}")
        if meta.get("app_version"):
            meta_lines.append(f"來源版本：{meta['app_version']}")
        if meta_lines:
            layout.addWidget(QLabel("▸ 任務資訊"))
            meta_label = QLabel("\n".join(meta_lines))
            meta_label.setWordWrap(True)
            layout.addWidget(meta_label)

        layout.addWidget(QLabel(f"▸ 將匯入 {preview.rule_count} 條規則："))
        names_text = "\n".join(f"  • {n}" for n in preview.rule_names[:20])
        if preview.rule_count > 20:
            names_text += f"\n  …及其他 {preview.rule_count - 20} 條"
        names_label = QLabel(names_text)
        names_label.setWordWrap(True)
        layout.addWidget(names_label)

        if preview.warnings:
            layout.addWidget(QLabel("▸ 警告："))
            warn_label = QLabel("\n".join(f"  ⚠ {w}" for w in preview.warnings))
            warn_label.setWordWrap(True)
            warn_label.setStyleSheet("color: #cc8800;")
            layout.addWidget(warn_label)

        cb = QCheckBox("重新產生所有規則 ID（避免與現有規則衝突）")
        cb.setChecked(False)
        layout.addWidget(cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("匯入")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        result = dialog.exec()
        return result == QDialog.DialogCode.Accepted, cb.isChecked()

    def _on_task_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入任務", str(_here), "JSON (*.json)")
        if not path:
            return
        try:
            if Path(path).stat().st_size > _MAX_IMPORT_SIZE:
                QMessageBox.warning(
                    self, "匯入失敗", "檔案過大（超過 10 MB），請確認是否為正確的任務檔案。"
                )
                return
        except OSError:
            pass
        preview = preview_import_task(path)
        if preview is None or preview.rule_count == 0:
            QMessageBox.warning(
                self, "匯入失敗", "檔案格式無效或無有效規則，請確認是包含 rules 陣列的 JSON。"
            )
            return
        accepted, regen = self._show_import_preview_dialog(preview)
        if not accepted:
            return
        imported_name = import_task(path, regenerate_uuids=regen)
        if imported_name is None:
            QMessageBox.warning(self, "匯入失敗", "無法寫入目標檔案。")
            return
        self._refresh_task_list()
        idx = self._task_combo.findText(imported_name)
        if idx >= 0:
            self._task_combo.setCurrentIndex(idx)
        msg = f"已匯入任務「{imported_name}」"
        if preview.warnings:
            msg += f"（{len(preview.warnings)} 條警告）"
        self._status_bar.showMessage(msg, 8000)
        if preview.warnings:
            QMessageBox.information(
                self,
                "匯入完成（有警告）",
                f"任務「{imported_name}」已匯入，但有 {len(preview.warnings)} 條警告：\n\n"
                + "\n".join(preview.warnings),
            )

    def _on_task_export(self):
        if not self._current_task:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "匯出任務", str(_here / f"{self._current_task}.json"), "JSON (*.json)"
        )
        if not path:
            return
        if export_task(self._current_task, path):
            self._status_bar.showMessage(f"任務「{self._current_task}」已匯出")
        else:
            QMessageBox.warning(self, "匯出失敗", "無法寫入目標檔案")

    # === Rule list ===
    @staticmethod
    def _make_circle_icon(color: tuple[int, int, int], size: int = 12) -> QIcon:
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(*color))
        p.setPen(QPen(QColor(*color), 1))
        p.drawEllipse(1, 1, size - 2, size - 2)
        p.end()
        return QIcon(pix)

    def _refresh_rule_list(self):
        self._rule_list.blockSignals(True)
        self._rule_list.clear()
        rule_map = {r.id: r for r in self._rules}

        if not self._groups:
            all_ids = [r.id for r in self._rules]
            if all_ids:
                default = RuleGroup(id="__default__", name="所有規則", rule_ids=list(all_ids))
                self._groups = [default]
            else:
                self._groups = [RuleGroup(id="__default__", name="所有規則")]

        selected_item = None
        for g in self._groups:
            group_item = QTreeWidgetItem()
            if g.enabled:
                if g.mode == "once":
                    prefix = "[1]"
                elif g.mode == "repeat":
                    prefix = "[N]"
                else:
                    prefix = "[∞]"
                order_tag = "∥" if g.order == "parallel" else "↻"
                text = f"{prefix}{order_tag} {g.name}"
                if g.mode == "repeat":
                    text += f" ×{g.repeat_times}"
            else:
                prefix = "[■]"
                text = f"{prefix} {g.name}"
                group_item.setForeground(0, QColor("#888888"))
            group_item.setText(0, text)
            group_item.setData(0, Qt.ItemDataRole.UserRole, ("group", g.id))
            group_item.setFlags(group_item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
            group_item.setToolTip(0, "右鍵可重新命名、群組設定、上移／下移、刪除")
            for rid in g.rule_ids:
                r = rule_map.get(rid)
                if r is None:
                    continue
                child = QTreeWidgetItem()
                text = f"{'👁 ' if r.background else ''}[{'✓' if r.enabled else '✗'}] {r.name}"
                child.setText(0, text)
                child.setData(0, Qt.ItemDataRole.UserRole, ("rule", r.id))
                child.setIcon(
                    0, self._make_circle_icon((0, 180, 0) if r.enabled else (160, 160, 160))
                )
                child.setToolTip(0, "右鍵可複製規則、移動到其他群組")
                group_item.addChild(child)
                if r.id == self._selected_rule_id:
                    selected_item = child
            self._rule_list.addTopLevelItem(group_item)
            self._rule_list.setItemWidget(group_item, 1, self._make_group_buttons(g.id))

        # 常駐監控固定節點
        bg_rules = [r for r in self._rules if r.background]
        if bg_rules:
            bg_item = QTreeWidgetItem()
            bg_item.setText(0, "📡 常駐監控")
            bg_item.setData(0, Qt.ItemDataRole.UserRole, ("bg_group", "__background__"))
            bg_item.setFlags(
                bg_item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled & ~Qt.ItemFlag.ItemIsEditable
            )
            bg_item.setForeground(0, QColor("#aaaaaa"))
            for r in bg_rules:
                child = QTreeWidgetItem()
                child.setText(0, f"[{'✓' if r.enabled else '✗'}] {r.name}")
                child.setData(0, Qt.ItemDataRole.UserRole, ("rule", r.id))
                child.setIcon(
                    0, self._make_circle_icon((0, 180, 0) if r.enabled else (160, 160, 160))
                )
                child.setToolTip(0, "右鍵可複製規則、移動到其他群組")
                bg_item.addChild(child)
                if r.id == self._selected_rule_id:
                    selected_item = child
            self._rule_list.addTopLevelItem(bg_item)
            bg_item.setExpanded("__background__" not in self._collapsed_groups)

        self._rule_list.expandAll()
        for i in range(self._rule_list.topLevelItemCount()):
            item = self._rule_list.topLevelItem(i)
            gid = item.data(0, Qt.ItemDataRole.UserRole)[1]
            if gid in self._collapsed_groups:
                item.setExpanded(False)
        self._rule_list.blockSignals(False)
        self._rule_hint.setVisible(len(self._rules) == 0)

        if selected_item:
            self._rule_list.setCurrentItem(selected_item)
        elif self._rule_list.topLevelItemCount() > 0:
            self._rule_list.topLevelItem(0).setExpanded(True)
            if self._rule_list.topLevelItem(0).childCount() > 0:
                self._rule_list.setCurrentItem(self._rule_list.topLevelItem(0).child(0))
            else:
                self._rule_list.setCurrentItem(self._rule_list.topLevelItem(0))
        else:
            self._selected_rule_id = None
            self._show_rule_detail(None)

    def _update_rule_status(self):
        if not self._loop or not self._loop.is_running:
            if self._loop is not None:
                self._stop_loop()
                return
            self._rule_list.blockSignals(True)
            try:
                for i in range(self._rule_list.topLevelItemCount()):
                    item = self._rule_list.topLevelItem(i)
                    item.setForeground(0, QColor())
                    for j in range(item.childCount()):
                        item.child(j).setForeground(0, QColor())
            finally:
                self._rule_list.blockSignals(False)
            self._refresh_rule_list()
            return
        statuses = self._loop.get_rules_status()
        status_map = {s["id"]: s for s in statuses}
        pointer_id = next((s["id"] for s in statuses if s.get("pointer")), None)

        def _set_text(item):
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "group":
                return
            sid = data[1] if data else None
            st = status_map.get(sid)
            if st is None:
                return
            enabled = st["enabled"]
            icon_color = (0, 180, 0) if enabled else (160, 160, 160)
            base = f"{'👁 ' if st.get('background') else ''}[{'✓' if enabled else '✗'}] {st['name']}"
            if item.text(0) != base:
                item.setText(0, base)
            item.setIcon(0, self._make_circle_icon(icon_color))
            if sid == pointer_id:
                item.setForeground(0, QColor("#4fc3f7"))
            else:
                item.setForeground(0, QColor())

        def _walk(item):
            _set_text(item)
            for j in range(item.childCount()):
                _walk(item.child(j))

        for i in range(self._rule_list.topLevelItemCount()):
            _walk(self._rule_list.topLevelItem(i))

    def _on_rule_item_collapsed(self, item):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "group":
            self._collapsed_groups.add(data[1])
            self._persist_collapsed()

    def _on_rule_item_expanded(self, item):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "group":
            self._collapsed_groups.discard(data[1])
            self._persist_collapsed()

    def _persist_collapsed(self):
        if not self._current_task:
            return
        try:
            task_path = Path(_tasks_dir()) / f"{self._current_task}.json"
            if task_path.exists():
                with open(task_path, encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}
            data["_collapsed_groups"] = list(self._collapsed_groups)
            tmp = task_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp.replace(task_path)
        except Exception:
            pass

    def _get_current_rule(self) -> Optional[Rule]:
        for r in self._rules:
            if r.id == self._selected_rule_id:
                return r
        return None

    def _on_rule_selected(self, current: QTreeWidgetItem, previous: QTreeWidgetItem):
        if previous:
            prev_data = previous.data(0, Qt.ItemDataRole.UserRole)
            if prev_data and prev_data[0] == "rule":
                prev_id = prev_data[1]
                prev_rule = next((r for r in self._rules if r.id == prev_id), None)
                if prev_rule:
                    prev_rule.name = self._edit_name.text()
                    prev_rule.enabled = self._edit_enabled.isChecked()
                    prev_rule.background = self._edit_background.isChecked()
                    prev_rule.steps = self._step_list.get_steps()
                    self._flush_save()
                    prefix = "👁 " if prev_rule.background else ""
                    status = "✓" if prev_rule.enabled else "✗"
                    previous.setText(0, f"{prefix}[{status}] {prev_rule.name}")
                    if self._loop:
                        self._loop.reload_rules()
        if current:
            data = current.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "rule":
                rule_id = data[1]
                rule = next((r for r in self._rules if r.id == rule_id), None)
                if rule:
                    self._selected_rule_id = rule.id
                    self._show_rule_detail(rule)
                    return
        self._selected_rule_id = None
        self._show_rule_detail(None)

    def _on_rules_reordered(self):
        new_order = []
        seen = set()
        new_group_ids = []
        rule_orig_group = {}
        for g in self._groups:
            for rid in list(g.rule_ids):
                rule_orig_group[rid] = g.id

        for i in range(self._rule_list.topLevelItemCount()):
            group_item = self._rule_list.topLevelItem(i)
            gdata = group_item.data(0, Qt.ItemDataRole.UserRole)
            if not gdata or gdata[0] != "group":
                # ponytail: 安全網：將意外變成 top-level 的規則歸回原群組
                if gdata and gdata[0] == "rule" and self._groups:
                    rid = gdata[1]
                    if rid not in seen:
                        seen.add(rid)
                        orig_gid = rule_orig_group.get(rid)
                        orig = next((g for g in self._groups if g.id == orig_gid), self._groups[0])
                        orig.rule_ids.append(rid)
                        rule = next((r for r in self._rules if r.id == rid), None)
                        if rule:
                            new_order.append(rule)
                continue
            gid = gdata[1]
            new_group_ids.append(gid)
            group = next((g for g in self._groups if g.id == gid), None)
            if group:
                group.rule_ids = []
                for j in range(group_item.childCount()):
                    child = group_item.child(j)
                    cdata = child.data(0, Qt.ItemDataRole.UserRole)
                    if cdata and cdata[0] == "rule":
                        rid = cdata[1]
                        if rid not in seen:
                            seen.add(rid)
                            group.rule_ids.append(rid)
                            rule = next((r for r in self._rules if r.id == rid), None)
                            if rule:
                                new_order.append(rule)
        group_map = {g.id: g for g in self._groups}
        self._groups = [group_map[gid] for gid in new_group_ids if gid in group_map]
        self._rules = new_order
        logging.debug("[reorder] drag-drop, ids=[%s]", ",".join(r.id for r in self._rules))
        self._flush_save()
        self._reapply_group_buttons()

    def _show_rule_detail(self, rule: Optional[Rule]):
        if rule is None:
            self._edit_stack.setCurrentIndex(0)
            self._saved_label.setVisible(False)
            self._edit_test_btn.setVisible(False)
            self._debug_panel.set_has_active_rule(False)
            return
        self._edit_stack.setCurrentIndex(1)
        self._saved_label.setVisible(True)
        self._edit_test_btn.setVisible(True)
        self._edit_test_btn.setEnabled(True)
        self._debug_panel.set_has_active_rule(True)
        self._edit_name.setEnabled(True)
        self._edit_enabled.setEnabled(True)
        self._edit_name.setText(rule.name)
        self._edit_enabled.blockSignals(True)
        self._edit_enabled.setChecked(rule.enabled)
        self._edit_enabled.blockSignals(False)
        self._edit_background.blockSignals(True)
        self._edit_background.setChecked(getattr(rule, "background", False))
        self._edit_background.blockSignals(False)
        self._step_list.set_rule_id(rule.id)
        self._step_list.set_steps(rule.steps)

    def _on_enabled_changed(self, state):
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.enabled = state == 2
        self._flush_save()
        item = self._rule_list.currentItem()
        if item:
            prefix = "👁 " if rule.background else ""
            text = f"{prefix}[{'✓' if rule.enabled else '✗'}] {rule.name}"
            item.setText(0, text)

    def _on_background_changed(self, state):
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.background = bool(state)
        if rule.background:
            for g in self._groups:
                if rule.id in g.rule_ids:
                    g.rule_ids.remove(rule.id)
        else:
            target = next((g for g in self._groups if g.id == "__uncategorized__"), None)
            if target is None:
                target = RuleGroup(id="__uncategorized__", name="未歸類", enabled=False)
                self._groups.append(target)
            if rule.id not in target.rule_ids:
                target.rule_ids.append(rule.id)
            if self._groups[-1].id != "__uncategorized__":
                self._groups.remove(target)
                self._groups.append(target)
            self._status_bar.showMessage(f"「{rule.name}」已移至未歸類", 4000)
        self._flush_save()
        self._refresh_rule_list()

    def _clear_uncategorized(self):
        target = next((g for g in self._groups if g.id == "__uncategorized__"), None)
        if target is None or not target.rule_ids:
            return
        count = len(target.rule_ids)
        reply = QMessageBox.question(
            self,
            "清空未歸類",
            f"確定刪除「未歸類」中的所有規則（共 {count} 條）？\n此操作無法復原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        removed = [r for r in self._rules if r.id in target.rule_ids]
        self._rules = [r for r in self._rules if r.id not in target.rule_ids]
        target.rule_ids.clear()
        logging.debug(
            "[clear uncategorized] removed=%d rules, ids=[%s]",
            len(removed),
            ",".join(r.id for r in removed),
        )
        self._selected_rule_id = None
        self._flush_save()
        self._refresh_rule_list()

    def _make_group_buttons(self, gid: str) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(2)
        layout.addStretch()
        group = next((g for g in self._groups if g.id == gid), None)
        if group and group.id == "__uncategorized__":
            return w
        enabled = group.enabled if group else True
        toggle = QPushButton("✓" if enabled else "■")
        toggle.setFixedSize(22, 22)
        toggle.setToolTip("停用群組" if enabled else "啟用群組")
        toggle.setStyleSheet("color: #4a4;" if enabled else "color: #888;")
        toggle.clicked.connect(lambda: self._toggle_group(gid))
        layout.addWidget(toggle)
        up = QPushButton("▲")
        up.setFixedSize(22, 22)
        up.setToolTip("上移群組")
        up.clicked.connect(lambda: self._move_group_up(gid))
        down = QPushButton("▼")
        down.setFixedSize(22, 22)
        down.setToolTip("下移群組")
        down.clicked.connect(lambda: self._move_group_down(gid))
        layout.addWidget(up)
        layout.addWidget(down)
        return w

    def _add_group(self):
        import uuid

        g = RuleGroup(id=f"group_{uuid.uuid4().hex[:8]}", name="新群組")
        self._groups.append(g)
        self._flush_save()
        self._refresh_rule_list()
        # find and select the new group item, start editing
        for i in range(self._rule_list.topLevelItemCount()):
            item = self._rule_list.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "group" and data[1] == g.id:
                self._rule_list.setCurrentItem(item)
                self._rule_list.editItem(item)
                break

    def _move_group_up(self, gid: str):
        if gid == "__uncategorized__":
            return
        idx = next((i for i, g in enumerate(self._groups) if g.id == gid), None)
        if idx is None or idx == 0:
            return
        self._groups[idx], self._groups[idx - 1] = self._groups[idx - 1], self._groups[idx]
        self._refresh_rule_list()
        self._flush_save()

    def _move_group_down(self, gid: str):
        if gid == "__uncategorized__":
            return
        idx = next((i for i, g in enumerate(self._groups) if g.id == gid), None)
        if idx is None or idx == len(self._groups) - 1:
            return
        self._groups[idx], self._groups[idx + 1] = self._groups[idx + 1], self._groups[idx]
        self._refresh_rule_list()
        self._flush_save()

    def _toggle_group(self, gid: str):
        group = next((g for g in self._groups if g.id == gid), None)
        if group is None or group.id == "__uncategorized__":
            return
        group.enabled = not group.enabled
        self._refresh_rule_list()
        self._flush_save()

    def _reapply_group_buttons(self):
        for i in range(self._rule_list.topLevelItemCount()):
            item = self._rule_list.topLevelItem(i)
            gdata = item.data(0, Qt.ItemDataRole.UserRole)
            if gdata and gdata[0] == "group":
                old = self._rule_list.itemWidget(item, 1)
                self._rule_list.removeItemWidget(item, 1)
                if old:
                    old.deleteLater()
                self._rule_list.setItemWidget(item, 1, self._make_group_buttons(gdata[1]))

    def _delete_group(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再刪除群組")
            return
        item = self._rule_list.currentItem()
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "group":
            return
        gid = data[1]
        group = next((g for g in self._groups if g.id == gid), None)
        if group is None:
            return
        if group.id == "__uncategorized__":
            QMessageBox.warning(
                self,
                "無法刪除",
                "「未歸類」為系統保留群組，無法刪除。\n可使用右鍵選單「清空未歸類」移出所有規則。",
            )
            return
        rule_count = len([rid for rid in group.rule_ids if any(r.id == rid for r in self._rules)])
        msg = f"確定刪除群組「{group.name}」？"
        if rule_count > 0:
            msg += f"\n群組內有 {rule_count} 條規則，這些規則也將一併刪除。"
        if (
            QMessageBox.question(
                self,
                "刪除群組",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        # remove rules in this group
        removed = [r for r in self._rules if r.id in group.rule_ids]
        self._rules = [r for r in self._rules if r.id not in group.rule_ids]
        self._groups = [g for g in self._groups if g.id != gid]
        logging.debug('[delete group] group="%s", removed=%d rules', group.name, len(removed))
        self._flush_save()
        self._selected_rule_id = None
        self._refresh_rule_list()

    def _rename_group(self, item):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "group":
            return
        gid = data[1]
        group = next((g for g in self._groups if g.id == gid), None)
        if not group:
            return
        if group.id == "__uncategorized__":
            return
        from PyQt6.QtWidgets import QInputDialog

        new_name, ok = QInputDialog.getText(self, "重新命名群組", "新名稱:", text=group.name)
        if ok and new_name.strip():
            group.name = new_name.strip()
            self._refresh_rule_list()
            self._flush_save()

    def _show_group_settings(self):
        item = self._rule_list.currentItem()
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "group":
            return
        gid = data[1]
        group = next((g for g in self._groups if g.id == gid), None)
        if group is None:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"群組設定 — {group.name}")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        layout.addWidget(QLabel("群組名稱"))
        name_edit = QLineEdit(group.name)
        layout.addWidget(name_edit)

        layout.addWidget(QLabel("執行模式"))
        mode_combo = QComboBox()
        mode_combo.addItem("循環執行", "loop")
        mode_combo.addItem("執行一次", "once")
        mode_combo.addItem("重複 N 次", "repeat")
        idx = mode_combo.findData(group.mode)
        if idx >= 0:
            mode_combo.setCurrentIndex(idx)
        layout.addWidget(mode_combo)

        layout.addWidget(QLabel("規則執行順序"))
        order_combo = QComboBox()
        order_combo.addItem("依序執行（↻）", "sequential")
        order_combo.addItem("並行掃描（∥）", "parallel")
        idx2 = order_combo.findData(group.order)
        if idx2 >= 0:
            order_combo.setCurrentIndex(idx2)
        order_combo.setToolTip(
            "依序：每次只跑列表當前的規則，觸發才前進到下一條。未觸發會卡住指標。\n"
            "並行：每幀從頭掃全部規則，第一條命中的執行，其餘跳過。不卡指標。"
        )
        layout.addWidget(order_combo)
        seq_hint = QLabel(
            "依序：每次只檢查列表中的一個規則，該規則觸發後指標才前進到下一條。未觸發則重複執行同一條。"
        )
        par_hint = QLabel(
            "並行：每幀從列表最上方開始依序掃描，第一個命中目標的規則會執行其動作，其餘直接跳過。下幀重新從頭掃描。"
        )
        for lbl in (seq_hint, par_hint):
            lbl.setStyleSheet("color: #888; font-size: 11px;")
            lbl.setWordWrap(True)
        layout.addWidget(seq_hint)
        layout.addWidget(par_hint)

        def _on_order_changed(idx3):
            is_par = order_combo.currentData() == "parallel"
            seq_hint.setVisible(not is_par)
            par_hint.setVisible(is_par)

        order_combo.currentIndexChanged.connect(_on_order_changed)
        _on_order_changed(order_combo.currentIndex())

        repeat_widget = QWidget()
        repeat_layout = QVBoxLayout(repeat_widget)
        repeat_layout.setContentsMargins(0, 0, 0, 0)
        repeat_layout.addWidget(QLabel("重複次數"))
        repeat_spin = QSpinBox()
        repeat_spin.setRange(1, 9999)
        repeat_spin.setValue(group.repeat_times)
        repeat_layout.addWidget(repeat_spin)
        layout.addWidget(repeat_widget)

        interval_widget = QWidget()
        interval_layout = QVBoxLayout(interval_widget)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.addWidget(QLabel("每輪間隔 (秒)"))
        interval_spin = QSpinBox()
        interval_spin.setRange(0, 99999)
        interval_spin.setValue(group.between_rounds_sec)
        interval_layout.addWidget(interval_spin)
        layout.addWidget(interval_widget)

        def _on_mode_changed(idx):
            mode = mode_combo.currentData()
            repeat_widget.setVisible(mode == "repeat")
            interval_widget.setVisible(mode in ("loop", "repeat"))

        mode_combo.currentIndexChanged.connect(_on_mode_changed)
        _on_mode_changed(mode_combo.currentIndex())

        enabled_cb = QCheckBox("啟用群組")
        enabled_cb.setChecked(group.enabled)
        layout.addWidget(enabled_cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            group.name = name_edit.text().strip() or group.name
            group.mode = mode_combo.currentData()
            group.order = order_combo.currentData()
            group.repeat_times = repeat_spin.value()
            group.between_rounds_sec = interval_spin.value()
            group.enabled = enabled_cb.isChecked()
            self._flush_save()
            self._refresh_rule_list()

    def _on_item_double_clicked(self, item, column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "group":
            gid = data[1]
            if gid == "__uncategorized__":
                return
            self._rename_group(item)

    def _add_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再新增規則")
            return
        cur = self._get_current_rule()
        if cur is not None:
            cur.steps = self._step_list.get_steps()

        # find target group from current selection
        target_group = None
        item = self._rule_list.currentItem()
        if item:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data:
                if data[0] == "group":
                    gid = data[1]
                else:
                    parent = item.parent()
                    if parent:
                        pdata = parent.data(0, Qt.ItemDataRole.UserRole)
                        gid = pdata[1] if pdata and pdata[0] == "group" else None
                    else:
                        gid = None
                if gid:
                    target_group = next((g for g in self._groups if g.id == gid), None)
        if target_group is None and self._groups:
            target_group = self._groups[0]

        import uuid

        rule = Rule(
            id=f"rule_{uuid.uuid4().hex[:8]}",
            name="新規則",
            enabled=True,
            steps=[
                Step(
                    type="detect",
                    params={
                        "text": "",
                        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
                        "match_mode": "fuzzy",
                        "fuzzy_threshold": 0.8,
                    },
                )
            ],
        )
        self._rules.append(rule)
        logging.debug(
            '[add rule] manual, name="%s", id=%s, background=%s',
            rule.name,
            rule.id,
            rule.background,
        )
        if target_group:
            target_group.rule_ids.append(rule.id)
        self._flush_save()
        self._selected_rule_id = rule.id
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()

    def _add_step(self, step_type: str):
        step = Step(type=step_type, params={})
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.steps.append(step)
        self._step_list.set_steps(rule.steps)
        self._save_current_rule()
        self._refresh_rule_list()

    def _on_steps_changed(self):
        self._save_current_rule()
        self._refresh_rule_list()

    def _delete_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再刪除規則")
            return
        item = self._rule_list.currentItem()
        if item:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "group":
                self._delete_group()
                return
        rule = self._get_current_rule()
        if rule is None:
            return

        # 檢查是否有其他規則參照此規則
        def _refs_to(rid: str) -> list[str]:
            result = []
            for r in self._rules:
                if r.id == rid:
                    continue
                for s in r.steps:
                    if s.type == "jump" and s.params.get("rule_id", "") == rid:
                        result.append(r.name)
                        break
                    of = s.params.get("on_fail", {})
                    if (
                        isinstance(of, dict)
                        and of.get("action") == "jump"
                        and of.get("rule_id", "") == rid
                    ):
                        if r.name not in result:
                            result.append(r.name)
            return result

        refs = _refs_to(rule.id)
        msg = f"確定刪除規則「{rule.name}」？"
        if refs:
            msg += "\n\n⚠ 以下規則依賴此規則，刪除後將失效：\n" + "\n".join(
                f"  • {n}" for n in refs
            )
        if (
            QMessageBox.question(
                self,
                "刪除規則",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._rules = [r for r in self._rules if r.id != rule.id]
        logging.debug('[delete rule] manual, name="%s", id=%s', rule.name, rule.id)
        for g in self._groups:
            g.rule_ids = [rid for rid in g.rule_ids if rid != rule.id]
        # 清理被刪規則的孤兒範本圖片（僅限舊版檔案路徑殘留）
        images_dir = _get_images_dir()
        for step in rule.steps:
            if step.type == "match_image":
                tmpl_path = step.params.get("template", "")
                if tmpl_path:
                    tmpl = Path(tmpl_path)
                    if tmpl.exists() and tmpl.parent.resolve() == images_dir.resolve():
                        still_used = any(
                            s.params.get("template", "") == tmpl_path
                            for r in self._rules
                            for s in r.steps
                            if s.type == "match_image"
                        )
                        if not still_used:
                            tmpl.unlink(missing_ok=True)
        # 自動清理其他規則指向被刪規則的參照（含 on_fail: jump）
        for r in self._rules:
            for s in r.steps:
                if s.type == "jump" and s.params.get("rule_id", "") == rule.id:
                    s.params["rule_id"] = ""
                of = s.params.get("on_fail", {})
                if (
                    isinstance(of, dict)
                    and of.get("action") == "jump"
                    and of.get("rule_id", "") == rule.id
                ):
                    of["rule_id"] = ""
        self._flush_save()
        self._refresh_rule_list()
        cur = self._get_current_rule()
        if cur is not None:
            self._step_list.set_steps(cur.steps)

    def _on_rule_context_menu(self, pos):
        item = self._rule_list.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        if data and data[0] == "rule":
            act = menu.addAction("複製規則（同群組）")
            act.triggered.connect(self._duplicate_rule)
            copy_to_menu = menu.addMenu("複製到群組…")
            normal_groups = [g for g in self._groups if not g.id.startswith("__")]
            if normal_groups:
                for g in normal_groups:
                    group_act = copy_to_menu.addAction(g.name)
                    group_act.setData(g.id)
                    group_act.triggered.connect(
                        lambda checked, gid=g.id: self._duplicate_rule_to_group(gid)
                    )
            else:
                copy_to_menu.setEnabled(False)
            move_to_menu = menu.addMenu("移動到群組…")
            if normal_groups:
                for g in normal_groups:
                    group_act = move_to_menu.addAction(g.name)
                    group_act.setData(g.id)
                    group_act.triggered.connect(
                        lambda checked, gid=g.id: self._move_rule_to_group(gid)
                    )
            else:
                move_to_menu.setEnabled(False)
        elif data and data[0] == "group":
            self._rule_list.setCurrentItem(item)
            gid = data[1]
            group = next((g for g in self._groups if g.id == gid), None)
            is_uncat = group and group.id == "__uncategorized__"
            if is_uncat:
                act = menu.addAction("🗑 清空未歸類")
                act.triggered.connect(self._clear_uncategorized)
                menu.addSeparator()
            else:
                act = menu.addAction("✏ 重新命名")
                act.triggered.connect(lambda: self._rename_group(item))
                act = menu.addAction("⚙ 群組設定")
                act.triggered.connect(self._show_group_settings)
                menu.addSeparator()
            act = menu.addAction("▲ 上移")
            act.triggered.connect(lambda checked, gid=gid: self._move_group_up(gid))
            act = menu.addAction("▼ 下移")
            act.triggered.connect(lambda checked, gid=gid: self._move_group_down(gid))
            menu.addSeparator()
            act = menu.addAction("刪除群組")
            act.triggered.connect(self._delete_group)
        menu.exec(self._rule_list.viewport().mapToGlobal(pos))

    def _duplicate_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再複製規則")
            return
        cur = self._get_current_rule()
        if cur is not None:
            cur.steps = self._step_list.get_steps()
        src = self._get_current_rule()
        if src is None:
            return
        import uuid

        new = deepcopy(src)
        new.id = f"rule_{uuid.uuid4().hex[:8]}"
        new.name = f"{src.name} (副本)"
        self._rules.append(new)
        logging.debug(
            '[duplicate rule] manual (same group), name="%s", id=%s <- %s', new.name, new.id, src.id
        )
        for g in self._groups:
            if src.id in g.rule_ids:
                g.rule_ids.append(new.id)
                break
        self._flush_save()
        self._selected_rule_id = new.id
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()

    def _duplicate_rule_to_group(self, target_gid: str):
        """Copy the current rule to the specified group."""
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再複製規則")
            return
        cur = self._get_current_rule()
        if cur is not None:
            cur.steps = self._step_list.get_steps()
        src_rule = self._get_current_rule()
        if src_rule is None:
            return
        target_group = next((g for g in self._groups if g.id == target_gid), None)
        if target_group is None:
            return
        import uuid

        new_rule = deepcopy(src_rule)
        new_rule.id = "rule_" + uuid.uuid4().hex[:8]
        new_rule.name = src_rule.name + " (副本)"
        self._rules.append(new_rule)
        logging.debug(
            '[duplicate rule] manual (to group), name="%s", id=%s <- %s, group="%s"',
            new_rule.name,
            new_rule.id,
            src_rule.id,
            target_group.name,
        )
        target_group.rule_ids.append(new_rule.id)
        self._flush_save()
        self._selected_rule_id = new_rule.id
        self._refresh_rule_list()
        self._status_bar.showMessage(
            "已將「" + src_rule.name + "」複製到群組「" + target_group.name + "」", 4000
        )
        if self._loop:
            self._loop.reload_rules()

    def _move_rule_to_group(self, target_gid: str):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再移動規則")
            return
        src_rule = self._get_current_rule()
        if src_rule is None:
            return
        src_rule.steps = self._step_list.get_steps()
        if any(src_rule.id in g.rule_ids for g in self._groups if g.id == target_gid):
            return
        target_group = next((g for g in self._groups if g.id == target_gid), None)
        if target_group is None:
            return
        for g in self._groups:
            if src_rule.id in g.rule_ids:
                g.rule_ids.remove(src_rule.id)
        target_group.rule_ids.append(src_rule.id)
        self._flush_save()
        self._refresh_rule_list()
        self._status_bar.showMessage(
            f"已將「{src_rule.name}」移動到群組「{target_group.name}」", 4000
        )
        if self._loop:
            self._loop.reload_rules()

    def _on_name_changed(self):
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.name = self._edit_name.text()
        self._schedule_save()
        self._refresh_rule_list()

    def _schedule_save(self):
        self._save_timer.start()

    def _do_debounced_save(self):
        if not self._current_task:
            return
        task_path = str(Path(_tasks_dir()) / f"{self._current_task}.json")
        save_task(self._current_task, self._rules)
        save_groups(self._groups, task_path)
        if self._loop:
            self._loop.reload_rules()

    def _flush_save(self):
        self._save_timer.stop()
        self._do_debounced_save()

    def _save_current_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再儲存規則")
            return
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.name = self._edit_name.text()
        rule.enabled = self._edit_enabled.isChecked()
        rule.steps = self._step_list.get_steps()
        # 校驗 detect 步驟文字不可為空
        for i, s in enumerate(rule.steps):
            if s.type == "detect" and not s.params.get("text", "").strip():
                QMessageBox.warning(self, "儲存失敗", f"步驟 {i + 1} (偵測文字)：目標文字不可為空")
                return
            if s.type == "click" and s.params.get("target", "") == "custom":
                x, y = s.params.get("x", 0), s.params.get("y", 0)
                if x == 0 and y == 0:
                    QMessageBox.warning(
                        self,
                        "儲存失敗",
                        f"步驟 {i + 1} (點擊)：自訂座標 (0,0) 可能未設定正確，請選取座標",
                    )
                    return
        # 檢查 jump 參照的規則是否存在
        valid_ids = {r.id for r in self._rules}
        for s in rule.steps:
            if s.type == "jump":
                tid = s.params.get("rule_id", "")
                if tid and tid not in valid_ids:
                    self._status_bar.showMessage(f"⚠ 步驟「{s.type}」參照的規則已不存在", 5000)
        self._schedule_save()
        item = self._rule_list.currentItem()
        if item:
            item.setText(0, f"[{'✓' if rule.enabled else '✗'}] {rule.name}")

    # === Click coordinate picker ===
    def _on_pick_coord(self):
        """Open click picker overlay, return window-relative (x, y) or None."""
        title = self._window_combo.currentText()
        if title:
            activate_window(title)
        mod = load_sibling("click_picker", "gui/13_gui_click_picker.py")
        result = mod.pick_click_position(parent_window=self)
        if result is None:
            return None
        if title:
            screen = QApplication.primaryScreen()
            ratio = screen.devicePixelRatio()
            result = (int(result[0] * ratio), int(result[1] * ratio))
            wr = get_window_rect(title)
            if wr:
                result = (result[0] - wr["x"], result[1] - wr["y"])
        self._edit_stack.setCurrentIndex(1)
        self._status_bar.showMessage(f"已選取點擊座標: X={result[0]}, Y={result[1]}")
        # Convert to ratio before storing
        if title and wr and wr["w"] > 0 and wr["h"] > 0:
            result = (result[0] / wr["w"], result[1] / wr["h"])
        return result

    # === ROI selector ===
    def _open_roi_selector(self):
        """Open ROI selector overlay, return window-relative ROI dict or None."""
        title = self._window_combo.currentText()
        if title:
            activate_window(title)
        mod = load_sibling("roi", "gui/07_gui_roi.py")
        result = mod.select_roi(parent_window=self)
        if not result:
            return None
        if title:
            screen = QApplication.primaryScreen()
            ratio = screen.devicePixelRatio()
            result["x"] = int(result["x"] * ratio)
            result["y"] = int(result["y"] * ratio)
            wr = get_window_rect(title)
            if wr:
                result["x"] -= wr["x"]
                result["y"] -= wr["y"]
        self._edit_stack.setCurrentIndex(1)
        self._status_bar.showMessage(
            f"已選取偵測區域: ({result['x']},{result['y']}) {result['w']}×{result['h']}"
        )
        # Convert to client-relative ratio before storing
        if title and wr and wr["w"] > 0 and wr["h"] > 0:
            chrome = get_window_client_offset(title) or (0, 0)
            cx, cy = chrome
            client_w = wr["w"] - cx
            client_h = wr["h"] - cy
            if client_w > 0 and client_h > 0:
                result = {
                    "x": max(0.0, (result["x"] - cx) / client_w),
                    "y": max(0.0, (result["y"] - cy) / client_h),
                    "w": min(1.0, result["w"] / client_w),
                    "h": min(1.0, result["h"] / client_h),
                    "roi_coord": "client",
                }
            else:
                result = {
                    "x": result["x"] / wr["w"],
                    "y": result["y"] / wr["h"],
                    "w": result["w"] / wr["w"],
                    "h": result["h"] / wr["h"],
                }
        return result

    def _capture_rect_to_roi(self, rect: dict, title: str) -> dict | None:
        if not title:
            return None
        wr = get_window_rect(title)
        if not wr or wr["w"] <= 0 or wr["h"] <= 0:
            return None
        cx, cy = rect["x"] + rect["w"] // 2, rect["y"] + rect["h"] // 2
        dpr = 1.0
        for screen in QApplication.screens():
            g = screen.geometry()
            if g.x() <= cx < g.x() + g.width() and g.y() <= cy < g.y() + g.height():
                dpr = screen.devicePixelRatio()
                break
        px = int(rect["x"] * dpr) - wr["x"]
        py = int(rect["y"] * dpr) - wr["y"]
        pw = int(rect["w"] * dpr)
        ph = int(rect["h"] * dpr)
        chrome = get_window_client_offset(title) or (0, 0)
        client_px = px - chrome[0]
        client_py = py - chrome[1]
        client_w = wr["w"] - chrome[0]
        client_h = wr["h"] - chrome[1]
        if client_w <= 0 or client_h <= 0:
            return _pixels_to_ratio_expanded(px, py, pw, ph, wr["w"], wr["h"])
        roi = _pixels_to_ratio_expanded(client_px, client_py, pw, ph, client_w, client_h)
        roi["roi_coord"] = "client"
        return roi

    def _open_capture_region(self):
        """Capture a screen region from the target window as template image."""
        title = self._window_combo.currentText()
        if title:
            activate_window(title)
        mod = load_sibling("capture_region", "gui/14_capture_region.py")
        task_path = (
            str(Path(_tasks_dir()) / f"{self._current_task}.json") if self._current_task else ""
        )
        rect = mod.capture_region(parent_window=self, task_path=task_path, window_title=title)
        if not rect:
            return None
        b64 = rect.get("template_b64")
        if b64:
            self._status_bar.showMessage("已截取範本")
            self._edit_stack.setCurrentIndex(1)
            roi_ratio = self._capture_rect_to_roi(rect, title)
            return {"b64": b64, "roi": roi_ratio} if roi_ratio else {"b64": b64}
        if title:
            screen = QApplication.primaryScreen()
            ratio = screen.devicePixelRatio()
            rx = int(rect["x"] * ratio)
            ry = int(rect["y"] * ratio)
            rw = int(rect["w"] * ratio)
            rh = int(rect["h"] * ratio)
            wr = get_window_rect(title)
            if wr:
                rx -= wr["x"]
                ry -= wr["y"]
            if wr:
                chrome = get_window_client_offset(title) or (0, 0)
                client_rx = rx - chrome[0]
                client_ry = ry - chrome[1]
                client_w = wr["w"] - chrome[0]
                client_h = wr["h"] - chrome[1]
                if client_w > 0 and client_h > 0:
                    roi_ratio = _pixels_to_ratio_expanded(
                        client_rx, client_ry, rw, rh, client_w, client_h
                    )
                    roi_ratio["roi_coord"] = "client"
                else:
                    roi_ratio = _pixels_to_ratio_expanded(rx, ry, rw, rh, wr["w"], wr["h"])
            else:
                roi_ratio = None
            img = capture(title)
            if img is not None and img.shape[0] >= ry + rh and img.shape[1] >= rx + rw:
                crop = img[ry : ry + rh, rx : rx + rw]
                b64 = img_to_b64(crop)
                self._status_bar.showMessage(f"已截取範本 ({crop.shape[1]}×{crop.shape[0]})")
                self._edit_stack.setCurrentIndex(1)
                return {"b64": b64, "roi": roi_ratio} if roi_ratio else {"b64": b64}
        return None

    # === Test rule ===
    def _on_test_rule(self):
        self._save_current_rule()
        rule = self._get_current_rule()
        if not rule:
            QMessageBox.warning(self, "測試", "請先選取一條規則")
            return
        title = self._window_combo.currentText()
        if not title:
            QMessageBox.warning(self, "測試", "請先選擇目標視窗")
            return
        self._edit_test_btn.setEnabled(False)
        self._edit_test_btn.setText("測試中…")
        QApplication.processEvents()
        self.showMinimized()
        QApplication.processEvents()
        time.sleep(0.08)
        activate_window(title)
        time.sleep(0.12)
        img = capture(title)
        cap_src = "mss"
        if img is None:
            img = capture_window_content(title)
            cap_src = "fallback(GDI)"
        h, w = img.shape[:2] if img is not None else (0, 0)
        wr = get_window_rect(title) if title else None
        chrome = get_window_client_offset(title) or (0, 0)
        print(f"=== 測試規則「{rule.name}」===")
        print(f"  視窗: {title}")
        if wr:
            print(
                f"  全視窗: {wr['w']}×{wr['h']}  Chrome: {chrome}  Client: {wr['w'] - chrome[0]}×{wr['h'] - chrome[1]}"
            )
        print(f"  截圖: {cap_src} {w}×{h}")
        self.showNormal()
        self.activateWindow()
        self._edit_stack.setCurrentIndex(1)
        if img is None:
            self._edit_test_btn.setEnabled(True)
            self._edit_test_btn.setText("▶ 測試")
            QMessageBox.warning(self, "測試", f"截圖失敗：無法擷取視窗「{title}」")
            return
        t = threading.Thread(target=self._run_rule_test, args=(rule, img), daemon=True)
        t.start()

    def _run_rule_test(self, rule: Rule, img: np.ndarray):
        """Background thread: run all steps dry-run, produce annotated image."""
        result: dict = {}
        try:
            markers, log_lines = self._run_dry_run(rule, img)
            annotated = self._draw_test_annotations(img.copy(), markers)
            result = {
                "image": annotated,
                "log": "\n".join(log_lines),
            }
        except Exception as e:
            result = {"error": f"測試異常：{e}"}
        self._signals.test_done_signal.emit(result)

    def _run_dry_run(self, rule: Rule, img: np.ndarray):
        """Execute all steps in dry-run mode, collect visual markers + log."""

        def _resolve(roi):
            W, H = img.shape[1], img.shape[0]
            x, y, w, h = roi.get("x", 0), roi.get("y", 0), roi.get("w", 0), roi.get("h", 0)
            if x == 0 and y == 0 and w == 0 and h == 0:
                return roi
            if x <= 1.0 and y <= 1.0 and w <= 1.0 and h <= 1.0:
                if roi.get("roi_coord") == "client":
                    chrome = get_window_client_offset(self._window_combo.currentText()) or (0, 0)
                    cx, cy = chrome
                    client_w = W - cx
                    client_h = H - cy
                    if client_w > 0 and client_h > 0:
                        px = {
                            "x": int(round(x * client_w)) + cx,
                            "y": int(round(y * client_h)) + cy,
                            "w": int(round(w * client_w)),
                            "h": int(round(h * client_h)),
                        }
                        print(
                            f"    _resolve(client): ratio=({x},{y},{w},{h}) client=({client_w},{client_h})→ pixel=({px['x']},{px['y']},{px['w']},{px['h']})"
                        )
                        return px
                    print(
                        f"    _resolve(client) FAILED: client_w={client_w} client_h={client_h}, falling back to full-window"
                    )
                px = {"x": int(x * W), "y": int(y * H), "w": int(w * W), "h": int(h * H)}
                print(
                    f"    _resolve(full): ratio=({x},{y},{w},{h}) W×H=({W}×{H})→ pixel=({px['x']},{px['y']},{px['w']},{px['h']})"
                )
                return px
            print(f"    _resolve(pixel, pass-thru): ({x},{y},{w},{h})")
            return roi

        def _resolve_point(px, py):
            W, H = img.shape[1], img.shape[0]
            if isinstance(px, float) and px <= 1.0 and isinstance(py, float) and py <= 1.0:
                return int(px * W), int(py * H)
            return int(px), int(py)

        markers = []
        log = []
        log.append(f"規則「{rule.name}」— {len(rule.steps)} 個步驟")
        log.append("─" * 40)

        last_center = None

        for idx, step in enumerate(rule.steps):
            try:
                if step.type == "detect":
                    p = step.params
                    text = p.get("text", "").strip()
                    if not text:
                        log.append(f"[{idx + 1}] ⚠ 偵測文字為空白")
                        continue
                    roi = _resolve(p.get("roi", {}))
                    use_roi = any(roi.get(k, 0) != 0 for k in ("x", "y", "w", "h"))
                    if use_roi:
                        roi_img = crop_roi(img, roi)
                        if roi_img is None:
                            log.append(f"[{idx + 1}] ⚠ ROI 裁切無效")
                            continue
                    else:
                        roi_img = img
                        roi = {"x": 0, "y": 0, "w": img.shape[1], "h": img.shape[0]}
                    results_ocr = recognize(
                        roi_img, preprocess=False, max_side_len=0, min_confidence=0.25
                    )
                    match_mode = p.get("match_mode", "fuzzy")
                    threshold = p.get("fuzzy_threshold", 0.8)
                    matches = find_text(results_ocr, text, match_mode, threshold)
                    rx = roi.get("x", 0)
                    ry = roi.get("y", 0)
                    print(
                        f"    detect OCR: roi_px=({rx},{ry}) img={roi_img.shape[1]}×{roi_img.shape[0]} raw_hits={len(results_ocr)}"
                    )
                    if matches:
                        m = matches[0]
                        mx = rx + int(m.x)
                        my = ry + int(m.y)
                        mw = int(m.w)
                        mh = int(m.h)
                        cx = mx + mw // 2
                        cy = my + mh // 2
                        print(
                            f"    detect hit: roi_local=({int(m.x)},{int(m.y)},{int(m.w)},{int(m.h)}) +offset=({rx},{ry})→ final=({mx},{my},{mw},{mh}) center=({cx},{cy})"
                        )
                        last_center = (cx, cy)
                        log.append(
                            f"[{idx + 1}] 🔍 命中「{m.text}」{m.confidence:.2f}  ({mx},{my}) {mw}×{mh}"
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "rect",
                                "color": (0, 200, 0),
                                "x": mx,
                                "y": my,
                                "w": mw,
                                "h": mh,
                            }
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "point",
                                "color": (0, 200, 0),
                                "x": cx,
                                "y": cy,
                            }
                        )
                    else:
                        print(
                            f"    detect miss: text=「{text}」mode={match_mode} threshold={threshold}"
                        )
                        log.append(
                            f"[{idx + 1}] ❌ 未命中「{text}」（{match_mode}，閾值 {threshold}）"
                        )
                        rw = roi.get("w", img.shape[1])
                        rh = roi.get("h", img.shape[0])
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "rect",
                                "color": (0, 0, 200),
                                "x": rx,
                                "y": ry,
                                "w": rw,
                                "h": rh,
                            }
                        )
                        if results_ocr:
                            top5 = "、".join(
                                f"「{r.text}」({r.confidence:.2f})" for r in results_ocr[:5]
                            )
                            log.append(f"  附近文字: {top5}")
                            if len(results_ocr) > 5:
                                log.append(f"  … 尚有 {len(results_ocr) - 5} 筆")

                elif step.type == "click":
                    p = step.params
                    target = p.get("target", "text_center")
                    cx, cy = None, None
                    if target == "custom":
                        cx, cy = _resolve_point(p.get("x", 0), p.get("y", 0))
                    elif target == "text_center":
                        if last_center:
                            cx, cy = last_center
                        else:
                            log.append(f"[{idx + 1}] ⚠ 目標「辨識目標」但無前一步偵測結果")
                            continue
                    elif target == "click_text":
                        ct = p.get("text", "").strip()
                        if ct:
                            r = recognize(
                                img, preprocess=False, max_side_len=0, min_confidence=0.25
                            )
                            ms = find_text(r, ct, "fuzzy", 0.8)
                            if ms:
                                m = ms[0]
                                cx = int(m.x + m.w / 2)
                                cy = int(m.y + m.h / 2)
                            else:
                                log.append(f"[{idx + 1}] ⚠ 點擊目標文字「{ct}」未找到")
                                continue
                    if cx is not None:
                        print(f"    click: target={target} → ({cx},{cy})")
                        log.append(f"[{idx + 1}] 🖱 {p.get('button', 'left')} 點擊 ({cx},{cy})")
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "click",
                                "color": (0, 0, 255),
                                "x": cx,
                                "y": cy,
                            }
                        )

                elif step.type == "drag":
                    p = step.params
                    target = p.get("target", "text_center")
                    sx, sy = None, None
                    if target == "custom":
                        sx, sy = _resolve_point(p.get("x", 0), p.get("y", 0))
                    elif target == "text_center":
                        if last_center:
                            sx, sy = last_center
                        else:
                            log.append(f"[{idx + 1}] ⚠ 拖曳起點「辨識目標」但無前一步偵測結果")
                            continue
                    elif target == "click_text":
                        ct = p.get("text", "").strip()
                        if ct:
                            r = recognize(
                                img, preprocess=False, max_side_len=0, min_confidence=0.25
                            )
                            ms = find_text(r, ct, "fuzzy", 0.8)
                            if ms:
                                m = ms[0]
                                sx = int(m.x + m.w / 2)
                                sy = int(m.y + m.h / 2)
                            else:
                                log.append(f"[{idx + 1}] ⚠ 拖曳目標文字「{ct}」未找到")
                                continue
                    if sx is not None:
                        dx = p.get("dx", 0)
                        dy = p.get("dy", 0)
                        ex = sx + dx
                        ey = sy + dy
                        log.append(
                            f"[{idx + 1}] ↗ {p.get('button', 'left')} 拖曳 ({sx},{sy}) → ({ex},{ey})"
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "drag",
                                "color": (255, 150, 0),
                                "x1": sx,
                                "y1": sy,
                                "x2": ex,
                                "y2": ey,
                            }
                        )

                elif step.type == "scroll":
                    p = step.params
                    dirs = {
                        "WheelDown": "向下",
                        "WheelUp": "向上",
                        "WheelLeft": "向左",
                        "WheelRight": "向右",
                    }
                    d = dirs.get(p.get("direction", "WheelDown"), p.get("direction", ""))
                    log.append(f"[{idx + 1}] ↕ 滾輪 {d} ×{p.get('amount', 1)}")

                elif step.type == "compare":
                    p = step.params
                    op = p.get("operator", ">=")
                    val = p.get("value", 0.0)
                    pattern = p.get("pattern", "")
                    roi = p.get("roi", {})
                    z = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
                    roi_str = "全視窗" if z else _fmt_roi(roi)
                    log.append(f"[{idx + 1}] 🔢 {op} {val} {roi_str} regex=「{pattern}」")

                elif step.type == "key":
                    p = step.params
                    k = p.get("key", "")
                    hm = p.get("hold_ms", 0)
                    s = f"按住 {hm}ms" if hm else "按下"
                    log.append(f"[{idx + 1}] ⌨ {s} {k}")

                elif step.type == "wait":
                    p = step.params
                    log.append(f"[{idx + 1}] ⏱ 等待 {p.get('ms', 500)}ms")

                elif step.type == "jump":
                    rid = step.params.get("rule_id", "")
                    name = _resolve_rule_name(rid, lambda: list(self._rules))
                    log.append(f"[{idx + 1}] ↩ 跳轉規則「{name}」")

                elif step.type == "match_image":
                    p = step.params
                    tmpl_data = p.get("template_data", "")
                    tmpl_path = p.get("template", "")
                    if not tmpl_data.strip() and not tmpl_path.strip():
                        log.append(f"[{idx + 1}] ⚠ 未設定範本圖片")
                        continue
                    roi = _resolve(p.get("roi", {}))
                    threshold = p.get("threshold", 0.8)
                    task_path = (
                        str(Path(_tasks_dir()) / f"{self._current_task}.json")
                        if self._current_task
                        else None
                    )
                    cs = _rule_mod.get_capture_size(task_path) if task_path else None
                    title = self._window_combo.currentText()
                    wr = get_window_rect(title) if title else None
                    chrome = get_window_client_offset(title) or (0, 0) if title else (0, 0)
                    if wr and chrome and chrome[0] >= 0 and chrome[1] >= 0:
                        cur_size = [wr["w"] - chrome[0], wr["h"] - chrome[1]]
                    else:
                        cur_size = None
                    print(
                        f"    match_image: roi={roi} capture_size={cs} current_size={cur_size} threshold={threshold}"
                    )
                    results = _main_loop_mod.match_template(
                        img,
                        tmpl_path,
                        roi,
                        threshold,
                        template_data=tmpl_data or None,
                        capture_size=cs,
                        current_size=cur_size,
                    )
                    tmpl_name = "內嵌" if tmpl_data.strip() else Path(tmpl_path).stem
                    if results:
                        m = results[0]
                        cx, cy = m.center_x, m.center_y
                        last_center = (cx, cy)
                        print(
                            f"    match_image hit: 「{tmpl_name}」({m.x},{m.y}) {m.w}×{m.h} center=({cx},{cy}) conf={m.confidence:.2%}"
                        )
                        log.append(
                            f"[{idx + 1}] 🖼 命中「{tmpl_name}」{m.confidence:.2f}  ({m.x},{m.y}) {m.w}×{m.h}"
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "rect",
                                "color": (0, 200, 0),
                                "x": m.x,
                                "y": m.y,
                                "w": m.w,
                                "h": m.h,
                            }
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "point",
                                "color": (0, 200, 0),
                                "x": cx,
                                "y": cy,
                            }
                        )
                    else:
                        rx, ry = roi.get("x", 0), roi.get("y", 0)
                        rw = roi.get("w", img.shape[1]) or img.shape[1]
                        rh = roi.get("h", img.shape[0]) or img.shape[0]
                        of_hint = _of_summary(p.get("on_fail", "stop"))
                        of_suffix = f" → {of_hint}" if of_hint else ""
                        log.append(
                            f"[{idx + 1}] ❌ 未命中「{tmpl_name}」（閾值 {threshold}）{of_suffix}"
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "rect",
                                "color": (0, 0, 200),
                                "x": rx,
                                "y": ry,
                                "w": rw,
                                "h": rh,
                            }
                        )

                else:
                    log.append(f"[{idx + 1}] ? 未知步驟: {step.type}")

            except Exception as e:
                log.append(f"[{idx + 1}] ⚠ {type(e).__name__}: {e}")

        return markers, log

    def _draw_test_annotations(self, img: np.ndarray, markers: list) -> np.ndarray:
        import cv2

        h, w = img.shape[:2]
        overlay = np.zeros_like(img, dtype=np.uint8)

        for m in markers:
            color = m.get("color", (0, 255, 0))
            shape = m.get("shape", "")
            if shape == "rect":
                x = max(0, m["x"])
                y = max(0, m["y"])
                rw = min(w - x, m["w"])
                rh = min(h - y, m["h"])
                if rw > 0 and rh > 0:
                    cv2.rectangle(overlay, (x, y), (x + rw, y + rh), color, -1)
            elif shape == "point":
                cv2.circle(overlay, (m["x"], m["y"]), 6, color, -1)
            elif shape == "click":
                cx, cy = m["x"], m["y"]
                cv2.line(overlay, (cx - 15, cy), (cx + 15, cy), color, 3)
                cv2.line(overlay, (cx, cy - 15), (cx, cy + 15), color, 3)
                cv2.circle(overlay, (cx, cy), 6, color, -1)
            elif shape == "drag":
                cv2.arrowedLine(overlay, (m["x1"], m["y1"]), (m["x2"], m["y2"]), color, 2)
                cv2.circle(overlay, (m["x1"], m["y1"]), 4, color, -1)

        target = img.copy()
        cv2.addWeighted(overlay, 0.25, target, 0.75, 0, target)

        for m in markers:
            color = m.get("color", (0, 255, 0))
            step = m.get("step", 0)
            shape = m.get("shape", "")
            if shape == "rect":
                x = max(0, m["x"])
                y = max(0, m["y"])
                rw = min(w - x, m["w"])
                rh = min(h - y, m["h"])
                if rw > 0 and rh > 0:
                    cv2.rectangle(target, (x, y), (x + rw - 1, y + rh - 1), color, 2)
                    if step:
                        cv2.putText(
                            target,
                            str(step),
                            (x + 4, y + 16),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            (255, 255, 255),
                            2,
                        )
                        cv2.putText(
                            target,
                            str(step),
                            (x + 4, y + 16),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            color,
                            1,
                        )
            elif shape == "click":
                if step:
                    cx, cy = m["x"], m["y"]
                    cv2.putText(
                        target,
                        str(step),
                        (cx + 14, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 255, 255),
                        2,
                    )
                    cv2.putText(
                        target,
                        str(step),
                        (cx + 14, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        color,
                        1,
                    )
            elif shape == "drag":
                if step:
                    sx, sy = m["x1"], m["y1"]
                    cv2.putText(
                        target,
                        str(step),
                        (sx + 6, sy - 6),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 255, 255),
                        2,
                    )
                    cv2.putText(
                        target,
                        str(step),
                        (sx + 6, sy - 6),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        color,
                        1,
                    )

        return target

    def _show_test_result(self, result: dict):
        self._edit_test_btn.setEnabled(True)
        self._edit_test_btn.setText("▶ 測試")
        if "error" in result:
            QMessageBox.warning(self, "測試結果", result["error"])
            return
        img = result["image"]
        log_text = result["log"]

        h, w = img.shape[:2]
        import cv2

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        bytes_per_line = 3 * w
        qt_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_img)

        dialog = QDialog(self)
        dialog.setWindowTitle("測試結果（視覺化）")
        dialog.resize(min(960, w + 40), min(850, h + 200))
        layout = QVBoxLayout(dialog)

        title_lbl = QLabel(log_text.split("\n", 1)[0])
        title_lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_lbl)

        scroll = QScrollArea()
        img_label = QLabel()
        pixmap_scaled = pixmap.scaled(
            min(920, w),
            min(650, h),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        img_label.setPixmap(pixmap_scaled)
        scroll.setWidget(img_label)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(300)
        layout.addWidget(scroll)

        log_edit = QTextEdit()
        log_edit.setReadOnly(True)
        log_edit.setText(log_text)
        log_edit.setMaximumHeight(150)
        layout.addWidget(log_edit)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn = btn_box.button(QDialogButtonBox.StandardButton.Close)
        close_btn.setText("關閉(Esc)")
        btn_box.rejected.connect(dialog.close)
        layout.addWidget(btn_box)

        dialog.exec()

    # === OCR diagnostic ===
    def _switch_to_debug(self):
        title = self._window_combo.currentText()
        if not title:
            QMessageBox.warning(self, "警告", "請先選擇目標視窗")
            return
        if self._loop is not None and self._loop.is_running:
            QMessageBox.warning(self, "無法開啟", "請先停止偵測循環再開啟診斷模式。")
            return
        self._debug_panel._window_title = title
        self._main_stack.setCurrentIndex(1)
        self._status_bar.showMessage(f"OCR 診斷 — 目標: {title}")

    def _switch_to_rules(self):
        self._main_stack.setCurrentIndex(0)
        self._status_bar.showMessage("就緒")

    def _on_debug_rule_requested(self, rule_data: dict):
        import uuid

        rule = Rule(
            id=f"rule_{uuid.uuid4().hex[:8]}",
            name=rule_data["target_text"],
            enabled=True,
            steps=[
                Step(
                    type="detect",
                    params={
                        "text": str(rule_data["target_text"]).strip() or "請輸入文字",
                        "roi": rule_data.get("roi", {"x": 0, "y": 0, "w": 0, "h": 0}),
                        "match_mode": "fuzzy",
                        "fuzzy_threshold": 0.8,
                    },
                ),
                Step(
                    type="click",
                    params={
                        "target": "text_center",
                        "button": "left",
                        "random_offset": 3,
                        "x": 0,
                        "y": 0,
                    },
                ),
            ],
        )
        self._rules.append(rule)
        logging.debug('[add rule] debug panel, name="%s", id=%s', rule.name, rule.id)
        target_group = None
        item = self._rule_list.currentItem()
        if item:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data:
                if data[0] == "group":
                    gid = data[1]
                else:
                    parent = item.parent()
                    if parent:
                        pdata = parent.data(0, Qt.ItemDataRole.UserRole)
                        gid = pdata[1] if pdata and pdata[0] == "group" else None
                    else:
                        gid = None
                if gid:
                    target_group = next((g for g in self._groups if g.id == gid), None)
        if target_group is None and self._groups:
            target_group = self._groups[0]
        if target_group:
            target_group.rule_ids.append(rule.id)
        self._flush_save()
        self._selected_rule_id = rule.id
        self._refresh_rule_list()
        self._main_stack.setCurrentIndex(0)
        self._debug_btn.setText("OCR 診斷")
        self._show_rule_detail(rule)
        self._status_bar.showMessage(f"已從 OCR 診斷新增規則：「{rule_data['target_text']}」")

    def _on_debug_step_requested(self, data: dict):
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.steps.append(
            Step(
                type="detect",
                params={
                    "text": str(data.get("target_text", "")).strip() or "請輸入文字",
                    "roi": data.get("roi", {"x": 0, "y": 0, "w": 0, "h": 0}),
                    "match_mode": "fuzzy",
                    "fuzzy_threshold": 0.8,
                },
            )
        )
        self._flush_save()
        self._step_list.set_steps(rule.steps)
        self._status_bar.showMessage(f"已加入偵測步驟：「{data.get('target_text', '')}」")

    # === Start / Pause ===
    def _show_group_selection_dialog(self) -> Optional[list[str]]:
        enabled = [g for g in self._groups if g.enabled]
        if len(enabled) <= 1:
            return [g.id for g in enabled] if enabled else []
        dialog = QDialog(self)
        dialog.setWindowTitle("選擇要執行的群組")
        layout = QVBoxLayout(dialog)
        checks = []
        for g in enabled:
            cb = QCheckBox(g.name)
            cb.setChecked(True)
            cb.setProperty("gid", g.id)
            checks.append(cb)
            layout.addWidget(cb)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("啟動")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return [cb.property("gid") for cb in checks if cb.isChecked()]

    def _toggle_start(self):
        if self._window_lost:
            self._stop_loop()
        elif self._loop is not None and self._loop.is_running:
            if self._loop.is_paused:
                self._loop.resume()
                self._btn_toggle.setText("暫停")
            else:
                self._stop_loop()
        else:
            self._start_loop()

    def _start_loop(self):
        self._window_lost = False
        title = self._window_combo.currentText()
        if not title:
            QMessageBox.warning(self, "警告", "請先選擇目標視窗")
            return
        if not self._rules:
            QMessageBox.warning(self, "警告", "尚未建立任何規則！\n請先新增至少一條規則。")
            return
        empty_steps = [r.name for r in self._rules if r.enabled and not r.steps]
        if empty_steps:
            names = "\n".join(f"  • {n}" for n in empty_steps[:5])
            suffix = f"\n  …及其他 {len(empty_steps) - 5} 條" if len(empty_steps) > 5 else ""
            QMessageBox.warning(
                self,
                "警告",
                f"以下啟用的規則沒有任何步驟，請先新增步驟：\n{names}{suffix}",
            )
            return
        group_ids = self._show_group_selection_dialog()
        if group_ids is None:
            return
        if not group_ids:
            QMessageBox.warning(self, "警告", "請至少選取一個群組。")
            return
        activate_window(title)
        self._btn_toggle.setEnabled(False)
        self._btn_toggle.setText("初始化中...")
        self._status_bar.showMessage("正在初始化 OCR 引擎…")
        task_path = str(Path(_tasks_dir()) / f"{self._current_task}.json")
        self._init_worker = InitWorker(
            str(task_path),
            title,
            self._signals,
            active_group_ids=group_ids,
        )
        self._init_worker.finished.connect(self._on_init_finished)
        self._init_worker.start()

    def _on_init_finished(self, success: bool, error_msg: str):
        self._btn_toggle.setEnabled(True)
        if success:
            self._loop = self._init_worker.loop
            self._loop.set_tool_hwnd(int(self.winId()))
            self._btn_toggle.setText("暫停")
            self._update_edit_enabled(False)
            self._status_bar.showMessage(f"偵測中 — 目標: {self._window_combo.currentText()}")
            self._status_timer.start(1000)
        else:
            QMessageBox.critical(self, "初始化失敗", f"無法啟動主迴圈：\n{error_msg}")
            self._btn_toggle.setText("啟動")
            self._status_bar.showMessage(f"初始化失敗 — {error_msg}")

    def _stop_loop(self):
        self._status_timer.stop()
        if self._loop:
            self._loop.stop()
            self._loop = None
        self._window_lost = False
        self._btn_toggle.setText("啟動")
        self._update_edit_enabled(True)
        self._status_bar.showMessage("已停止")
        self._update_rule_status()

    def _on_loop_finished(self, success: bool, msg: str):
        if self._loop is not None:
            self._stop_loop()

    def _update_edit_enabled(self, enabled: bool):
        self._rule_list.setEnabled(enabled)
        self._add_group_btn.setEnabled(enabled)
        self._add_rule_btn.setEnabled(enabled)
        self._del_rule_btn.setEnabled(enabled)
        self._debug_btn.setEnabled(enabled)

        self._task_combo.setEnabled(enabled)
        self._task_new_btn.setEnabled(enabled)
        self._task_del_btn.setEnabled(enabled)
        self._task_import_btn.setEnabled(enabled)
        self._task_export_btn.setEnabled(enabled)
        self._edit_test_btn.setEnabled(enabled)
        self._edit_name.setEnabled(enabled)
        self._edit_enabled.setEnabled(enabled)
        self._edit_background.setEnabled(enabled)
        self._step_list.setEnabled(enabled)

        if enabled:
            self._show_rule_detail(self._get_current_rule())

    # === Thread-safe callbacks ===
    def _on_window_lost_from_thread(self):
        self._window_lost = True
        self._btn_toggle.setText("繼續")
        self._status_bar.showMessage("⚠ 目標視窗已關閉，偵測已暫停")

    # === Emergency & OCR Health ===
    def _emergency_stop(self):
        self._status_timer.stop()
        if self._loop is None:
            return
        self._loop.emergency_stop()
        self._loop = None
        self._btn_toggle.setText("啟動")
        self._update_edit_enabled(True)
        self._status_bar.showMessage("🛑 緊急停止 — 按「啟動」重新開始")
        self._update_rule_status()

    # === Compare log ===
    def _toggle_compare_log(self):
        visible = self._compare_log_toggle.isChecked()
        self._compare_log_widget.setVisible(visible)
        self._compare_log_toggle.setText("▾ 比較輪次日誌" if visible else "▸ 比較輪次日誌")

    def _toggle_trigger_log(self):
        visible = self._trigger_log_toggle.isChecked()
        self._trigger_log_widget.setVisible(visible)
        self._trigger_log_toggle.setText("▾ 觸發記錄" if visible else "▸ 觸發記錄")

    def _on_trigger_log_received(self, log):
        ts = time.strftime("%H:%M:%S", time.localtime(log.timestamp))
        text = f"[{ts}] {log.rule_name} → ({log.click_x}, {log.click_y})「{log.matched_text}」"
        self._trigger_log_widget.insertItem(0, text)
        while self._trigger_log_widget.count() > 20:
            self._trigger_log_widget.takeItem(self._trigger_log_widget.count() - 1)
        if not self._trigger_log_toggle.isChecked():
            self._trigger_log_toggle.setChecked(True)
            self._trigger_log_widget.setVisible(True)
            self._trigger_log_toggle.setText("▾ 觸發記錄")

    # === Sponsor ===
    def _open_sponsor(self):
        import webbrowser

        from PyQt6.QtCore import QPoint

        menu = QMenu(self)
        ecpay_icon = self._make_circle_icon((0, 166, 81))
        paypal_icon = self._make_circle_icon((0, 112, 186))
        menu.addAction(ecpay_icon, "ECPAY").triggered.connect(
            lambda: webbrowser.open("https://p.ecpay.com.tw/E0E3A")
        )
        menu.addAction(paypal_icon, "PayPal").triggered.connect(
            lambda: webbrowser.open("https://www.paypal.com/ncp/payment/9TGC4B3MYM9A6")
        )
        menu.exec(self._sponsor_btn.mapToGlobal(QPoint(0, self._sponsor_btn.height())))

    # === About & Version ===
    def _show_about(self):
        QMessageBox.about(
            self,
            "關於 OCR Trigger Clicker",
            f"<h3>OCR Trigger Clicker v{__version__}</h3>"
            f"<p>作者: {__author__}</p>"
            f"<p>專案: <a href='{__github__}'>{__github__}</a></p>"
            f"<p>新手教學: <a href='{_GUIDE_URL}'>{_GUIDE_URL}</a></p>"
            f"<hr><p><b>Beta 版本</b> — 可能有未預期的問題</p>",
        )

    def _open_guide(self):
        import webbrowser

        webbrowser.open(_GUIDE_URL)

    def _check_version(self):
        import urllib.request

        url = f"{__github__}/raw/master/latest_version.txt"
        try:
            resp = urllib.request.urlopen(url, timeout=5)
            latest = resp.read().decode("utf-8").strip()
            current_parts = _parse_version(__version__)
            latest_parts = _parse_version(latest)
            if latest_parts > current_parts:
                btn = QMessageBox.question(
                    self,
                    "發現新版本",
                    f"新版本 v{latest} 已發布（目前 v{__version__}）\n是否前往 GitHub 下載？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if btn == QMessageBox.StandardButton.Yes:
                    import webbrowser

                    webbrowser.open(__github__ + "/releases")
        except Exception:
            pass  # 網路錯誤不影響啟動

    def _open_settings(self):
        SettingsDialog(self._config_path, self).exec()

    def closeEvent(self, event):
        config = self._load_config()
        behavior = config.get("close_behavior", "tray")
        show_confirm = config.get("show_close_confirm", True)

        if show_confirm:
            title = "關閉確認"
            msg = "確定要關閉程式？" if behavior == "quit" else "確定要縮小至系統托盤？"
            box = QMessageBox(self)
            box.setWindowTitle(title)
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(msg)
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            cb = QCheckBox("不再顯示此確認")
            box.setCheckBox(cb)
            if box.exec() != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if cb.isChecked():
                config["show_close_confirm"] = False
                self._save_config(config)

        if behavior == "quit":
            self._quit_app()
            event.accept()
        else:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "OCR Trigger Clicker",
                "程式仍在背景執行，雙擊托盤圖示可重新開啟",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    def _restore_window(self):
        self.showNormal()
        self.activateWindow()

    def _quit_app(self):
        self._flush_save()
        self._status_timer.stop()
        if self._loop:
            self._loop.stop()
        self._perf_timer.stop()
        _ahk_mod.shutdown()
        QApplication.quit()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_window()


if __name__ == "__main__":
    import sys
    import traceback
    from logging.handlers import TimedRotatingFileHandler

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _log_dir = Path.home() / "AppData" / "Roaming" / "ocr-trigger-clicker" / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_handler = TimedRotatingFileHandler(
        _log_dir / "debug.log",
        when="midnight",
        backupCount=7,
        encoding="utf-8",
    )
    _log_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    _log_handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(_log_handler)
    logging.getLogger().setLevel(logging.DEBUG)

    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    except Exception:
        with open("startup_error.log", "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        raise
