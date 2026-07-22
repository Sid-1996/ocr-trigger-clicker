import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Optional

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
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QTextBrowser,
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
from i18n import T, set_language

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
            self._btn.setText(T("ui.no_group"))
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
            self._btn.setToolTip(
                T("tooltip.stop_group_selected", names="\n".join(f"• {n}" for n in names))
            )
        else:
            self._btn.setToolTip(T("tooltip.stop_group_none"))

    def _open_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(T("ui.select_stop_group"))
        dialog.setMinimumWidth(320)
        dialog.setMinimumHeight(400)
        layout = QVBoxLayout(dialog)

        search = QLineEdit()
        search.setPlaceholderText(T("ui.search_groups"))
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
        ok_btn = QPushButton(T("ui.confirm"))
        cancel_btn = QPushButton(T("ui.cancel"))
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
        indicator = self.dropIndicatorPosition()
        target_item = self.itemAt(event.position().toPoint())

        # ── 通用攔截：src=rule 且 target=rule，一律手動插為 sibling ──
        if target_item and src_data and src_data[0] == "rule":
            tgt_data = target_item.data(0, Qt.ItemDataRole.UserRole)
            if tgt_data and tgt_data[0] == "rule":
                if src == target_item:
                    event.ignore()
                    return
                parent = target_item.parent()
                if parent is None:
                    event.ignore()
                    return
                target_idx = parent.indexOfChild(target_item)

                if indicator == QAbstractItemView.DropIndicatorPosition.AboveItem:
                    insert_pos = target_idx
                elif indicator == QAbstractItemView.DropIndicatorPosition.BelowItem:
                    insert_pos = target_idx + 1
                else:
                    rect = self.visualItemRect(target_item)
                    mouse_y = event.position().toPoint().y()
                    insert_pos = (
                        target_idx
                        if mouse_y < (rect.top() + rect.height() // 2)
                        else target_idx + 1
                    )

                old_parent = src.parent()
                if old_parent is None:
                    event.ignore()
                    return
                old_idx = old_parent.indexOfChild(src)
                taken = old_parent.takeChild(old_idx)
                if old_parent == parent and old_idx < insert_pos:
                    insert_pos -= 1
                insert_pos = max(0, min(insert_pos, parent.childCount()))
                parent.insertChild(insert_pos, taken)
                self.setCurrentItem(taken)
                self.reordered.emit()
                event.setDropAction(Qt.DropAction.IgnoreAction)
                event.accept()
                return

        # ── OnItem：rule → bg_group/group ──
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

        # 不該進到這裡（規則的 Above/Below 已被上方攔截）
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
    "notify": "💬",
}

_STEP_TYPE_LABELS = {
    "detect": T("step_form.step_detect"),
    "match_image": T("step_form.step_match_image"),
    "compare": T("step_form.step_compare"),
    "click": T("step_form.step_click"),
    "key": T("step_form.step_key"),
    "wait": T("step_form.step_wait"),
    "jump": T("step_form.step_jump"),
    "drag": T("step_form.step_drag"),
    "scroll": T("step_form.step_scroll"),
    "notify": T("step_form.step_notify"),
}

_STEP_COLORS = {
    "detect": "#4A90D9",
    "click": "#27AE60",
    "key": "#F39C12",
    "wait": "#95A5A6",
    "jump": "#9B59B6",
    "compare": "#1ABC9C",
    "match_image": "#E91E63",
    "notify": "#F1C40F",
    "scroll": "#2C3E50",
    "drag": "#E74C3C",
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
        roi_str = T("summary.whole_window") if zero_roi else _fmt_roi(roi)
        mode = p.get("match_mode", "fuzzy")
        th = p.get("fuzzy_threshold", 0.8)
        extra = ""
        if mode == "regex":
            extra = " [" + T("summary.regex") + "]"
        elif mode == "exact":
            extra = " [" + T("summary.exact") + "]"
        elif mode == "contains":
            extra = " [" + T("summary.contains") + "]"
        elif mode == "fuzzy":
            extra = " [" + T("summary.fuzzy") + (f"@{th}" if th != 0.8 else "") + "]"
        text_label = f"「{text}」" if text else T("summary.not_set")
        parts = [text_label + extra]
        parts.append(roi_str)
        of = _of_summary(p.get("on_fail", "stop"), rules_provider)
        if of:
            parts.append(f"| {of}")
        return " ".join(parts)
    if t == "match_image":
        tmpl_data = p.get("template_data", "")
        tmpl = (
            Path(p.get("template", "")).stem or T("summary.embedded")
            if tmpl_data.strip()
            else T("summary.not_set")
        )
        roi = p.get("roi", {})
        zero_roi = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        parts = [f"「{tmpl}」"]
        parts.append(T("summary.whole_window") if zero_roi else _fmt_roi(roi))
        th = p.get("threshold", 0.8)
        parts.append(T("summary.format_threshold", threshold=th))
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
        parts.append(T("summary.whole_window") if zero_roi else _fmt_roi(roi))
        of = _of_summary(p.get("on_fail", "stop"), rules_provider)
        if of:
            parts.append(f"| {of}")
        return " ".join(parts)
    if t == "click":
        target = p.get("target", "text_center")
        if target == "text_center":
            return T("summary.click_target")
        if target == "custom":
            return T("summary.format_click", point=_fmt_point(p.get("x", 0), p.get("y", 0)))
        if target == "click_text":
            return T("summary.format_click_text", text=p.get("text", ""))
    if t == "key":
        return T("summary.format_key_press", key=p.get("key", ""))
    if t == "wait":
        return T("summary.format_wait", ms=p.get("ms", 500))
    if t == "jump":
        name = _resolve_rule_name(p.get("rule_id", ""), rules_provider)
        return T("summary.format_jump", name=name)
    if t == "drag":
        target = p.get("target", "text_center")
        dx, dy = p.get("dx", 0), p.get("dy", 0)
        base = {
            "text_center": T("summary.click_target"),
            "custom": T("step_form.text_coord"),
            "click_text": T("step_form.text_label", text=p.get("text", "")),
        }.get(target, "?")
        return T("summary.format_drag", base=base, dx=dx, dy=dy)
    if t == "scroll":
        d = p.get("direction", "WheelDown")
        a = p.get("amount", 1)
        dir_label = {
            "WheelDown": T("summary.down"),
            "WheelUp": T("summary.up"),
            "WheelLeft": T("summary.left"),
            "WheelRight": T("summary.right"),
        }.get(d, d)
        return T("summary.format_scroll", direction=dir_label, times=a)
    if t == "notify":
        msg = p.get("message", "")
        return T("summary.format_notify", msg=msg) if msg else T("summary.format_notify_empty")
    return t


def _of_summary(raw: str | dict, rules_provider=None) -> str:
    if isinstance(raw, str):
        return "" if raw == "stop" else T("summary.onfail_press_key")  # bare "key"
    if isinstance(raw, dict):
        action = raw.get("action", "stop")
        try:
            fail_duration = float(raw.get("fail_duration_sec", 0) or 0)
        except (TypeError, ValueError):
            fail_duration = 0.0
        prefix = (
            T("summary.format_fail_duration", seconds=f"{fail_duration:g}")
            if fail_duration > 0
            else ""
        )
        if action == "stop":
            return prefix if prefix else ""
        if action == "key":
            return f"{prefix}{T('summary.onfail_press_key')}{raw.get('key', '')}"
        if action == "skip":
            idx = raw.get("skip_to", -1)
            if idx < 0:
                return f"{prefix}{T('summary.onfail_stop')}"
            return f"{prefix}{T('summary.onfail_step', idx=idx + 1)}"
        if action == "jump":
            name = _resolve_rule_name(raw.get("rule_id", ""), rules_provider)
            return f"{prefix}{T('summary.onfail_rule', name=name)}"
        if action == "notify":
            return f"{prefix}{T('summary.onfail_stop_group')}"
        if action == "retry":
            return f"{prefix}{T('summary.onfail_retry')}"
    return ""


def _make_key_combo(parent=None):
    cb = _KeyCombo(parent)
    for group in [
        [(T("summary.format_key", i=i), str(i)) for i in range(10)],
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
        QShortcut(
            QKeySequence("Delete"),
            self,
            self._delete_selected_step,
            context=Qt.ShortcutContext.WidgetShortcut,
        )

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
        _color = _STEP_COLORS.get(step.type)
        if _color:
            icon.setStyleSheet(f"color: {_color};")
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
        btn_up.setToolTip(T("tooltip.up"))
        btn_up.clicked.connect(lambda checked, i=idx: self._move_up(i))
        hl.addWidget(btn_up)

        btn_dn = QPushButton("↓")
        btn_dn.setFixedWidth(24)
        btn_dn.setFixedHeight(22)
        btn_dn.setStyleSheet("QPushButton { border: none; padding: 2px; }")
        btn_dn.setToolTip(T("tooltip.down"))
        btn_dn.clicked.connect(lambda checked, i=idx: self._move_down(i))
        hl.addWidget(btn_dn)

        btn_edit = QPushButton(T("step_form.edit_btn"))
        btn_edit.setFixedWidth(24)
        btn_edit.setFixedHeight(22)
        btn_edit.setStyleSheet("QPushButton { border: none; padding: 2px; }")
        btn_edit.setToolTip(T("tooltip.edit"))
        btn_edit.clicked.connect(lambda checked, i=idx: self._toggle_expand(i))
        hl.addWidget(btn_edit)

        btn_del = QPushButton(T("step_form.del_btn"))
        btn_del.setFixedWidth(24)
        btn_del.setFixedHeight(22)
        btn_del.setStyleSheet("QPushButton { border: none; padding: 2px; }")
        btn_del.setToolTip(T("tooltip.del"))
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

    def _delete_selected_step(self):
        if self._expanded_idx is not None and 0 <= self._expanded_idx < len(self._steps):
            self._delete_step(self._expanded_idx)

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
                groups_provider=self._groups_provider,
            )
        if t == "click":
            return _ClickStepForm(self, step, idx, self._click_pick_callback)
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
                step_count=len(self._steps),
                groups_provider=self._groups_provider,
            )
        if t == "notify":
            return _NotifyStepForm(self, step, idx)
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
            else (T("step_form.embedded_image") if tmpl_data.strip() else T("ui.no_group"))
        )
        self._tmpl_label = QLabel(label_text)
        self._tmpl_btn = QPushButton(T("step_form.select_image"))
        self._tmpl_btn.clicked.connect(self._pick_template)
        self._capture_btn = QPushButton(T("step_form.capture_region"))
        self._capture_btn.clicked.connect(self._capture_template)
        self._img_compare_btn = QPushButton(T("step_form.compare_image"))
        self._img_compare_btn.clicked.connect(self._img_compare_match)
        self._img_compare_result = QLabel("")
        tmpl_layout.addWidget(self._tmpl_label, 1)
        tmpl_layout.addWidget(self._tmpl_btn)
        tmpl_layout.addWidget(self._capture_btn)
        tmpl_layout.addWidget(self._img_compare_btn)
        tmpl_layout.addWidget(self._img_compare_result)
        form.addRow(T("step_form.template_image"), tmpl_row)
        self._update_thumbnail()

        # ROI
        roi = p.get("roi", {})
        z = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        self._roi_label = QLabel(T("summary.whole_window") if z else _fmt_roi(roi))
        self._roi_btn = QPushButton(T("step_form.search_roi"))
        self._roi_btn.setToolTip(T("tooltip.roi"))
        self._roi_btn.clicked.connect(self._pick_roi)
        roi_row = QWidget()
        rr_layout = QHBoxLayout(roi_row)
        rr_layout.setContentsMargins(0, 0, 0, 0)

        rr_layout.addWidget(self._roi_label)
        rr_layout.addWidget(self._roi_btn)
        form.addRow(T("step_form.search_region"), roi_row)

        # Threshold
        self._threshold = _NoWheelDoubleSpin()
        self._threshold.setRange(0.01, 1.0)
        self._threshold.setDecimals(2)
        self._threshold.setSingleStep(0.05)
        self._threshold.setValue(p.get("threshold", 0.8))
        form.addRow(T("step_form.threshold"), self._threshold)

        self._match_color = QCheckBox(T("step_form.match_color"))
        self._match_color.setChecked(p.get("match_color", False))
        self._match_color.setToolTip(T("tooltip.match_color"))
        form.addRow("", self._match_color)

        self._color_tolerance = _NoWheelSpin()
        self._color_tolerance.setRange(0, 255)
        self._color_tolerance.setValue(p.get("color_tolerance", 100))
        self._color_tolerance.setSuffix(T("step_form.color_suffix_short"))
        self._color_tolerance.setToolTip(T("tooltip.color_tolerance"))

        def _on_match_color_toggled(checked):
            self._color_tolerance.setEnabled(checked)

        self._match_color.toggled.connect(_on_match_color_toggled)
        _on_match_color_toggled(self._match_color.isChecked())
        form.addRow("", self._color_tolerance)

        # ── on_fail collapsible section ──
        self._on_fail_expanded = False
        self._toggle_btn = QPushButton(T("step_form.toggle_image_collapsed"))
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
        self._of_action.addItem(T("step_form.of_skip_once"), "stop")
        self._of_action.addItem(T("step_form.of_skip_rule"), "advance")
        self._of_action.addItem(T("step_form.of_jump_step"), "skip")
        self._of_action.addItem(T("step_form.of_jump_rule"), "jump")
        self._of_action.addItem(T("step_form.of_key_continue"), "key")
        self._of_action.addItem(T("step_form.of_notify_stop"), "notify")
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
        of_form.addRow(T("step_form.action"), self._of_action)

        self._of_fail_duration = _NoWheelDoubleSpin()
        self._of_fail_duration.setRange(0.0, 30.0)
        self._of_fail_duration.setSingleStep(0.5)
        self._of_fail_duration.setSuffix(T("step_form.of_skip_suffix"))
        self._of_fail_duration.setDecimals(1)
        default_duration = raw_of.get("fail_duration_sec", 0.0) if isinstance(raw_of, dict) else 0.0
        try:
            default_duration = float(default_duration)
        except (TypeError, ValueError):
            default_duration = 0.0
        self._of_fail_duration.setValue(default_duration)
        of_form.addRow(T("step_form.fail_duration"), self._of_fail_duration)

        # skip row (jump to step)
        self._of_skip_row = QWidget()
        sf = QHBoxLayout(self._of_skip_row)
        sf.setContentsMargins(0, 0, 0, 0)
        self._of_skip_combo = _NoWheelCombo()
        self._populate_skip_combo(raw_of.get("skip_to", -1) if isinstance(raw_of, dict) else -1)
        sf.addWidget(QLabel(T("step_form.skip_to")))
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
                self._of_jump_combo.addItem(T("step_form.unknown_rule", id=target_id), target_id)
                j_idx = self._of_jump_combo.count() - 1
            self._of_jump_combo.setCurrentIndex(max(j_idx, 0))
        jf.addWidget(QLabel(T("step_form.skip_to")))
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
        kf.addWidget(QLabel(T("step_form.press_key")))
        kf.addWidget(self._of_key)
        kf.addWidget(QLabel(T("step_form.then_continue")))
        kf.addStretch()
        of_form.addRow("", self._of_key_row)

        # notify widgets
        self._of_notify_msg = QLineEdit()
        self._of_notify_msg.setPlaceholderText(T("step_form.enter_text"))
        of_form.addRow(T("step_form.notify_message"), self._of_notify_msg)
        self._of_notify_msg.setText(default_notify_msg)
        self._of_notify_groups = _StopGroupsPicker(
            groups_provider=groups_provider,
            selected=default_notify_groups,
        )
        of_form.addRow(T("step_form.stop_groups"), self._of_notify_groups)

        form.addRow(self._on_fail_container)
        self._on_of_action_changed()

    def _populate_skip_combo(self, current_skip_to):
        self._of_skip_combo.clear()
        self._of_skip_combo.addItem(T("step_form.this_rule_end"), self._step_count)
        start = self._idx + 2  # 1-based, after current
        for i in range(start, self._step_count + 1):
            self._of_skip_combo.addItem(T("step_form.step_n", i=i), i - 1)
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
            self._img_compare_result.setText(T("img_compare.no_window"))
            self._img_compare_result.setStyleSheet("color: #e67e22; font-weight: bold;")
            return
        tmpl_data = self._step.params.get("template_data", "")
        tmpl_path = self._step.params.get("template", "")
        if not tmpl_data.strip() and not tmpl_path.strip():
            self._img_compare_result.setText(T("img_compare.no_template"))
            self._img_compare_result.setStyleSheet("color: #e67e22; font-weight: bold;")
            return
        roi = self._step.params.get("roi", {})
        threshold = self._threshold.value()
        match_color = self._match_color.isChecked()
        color_tolerance = self._color_tolerance.value()
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
            self._img_compare_result.setText(T("img_compare.capture_failed"))
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
            match_color=match_color,
            color_tolerance=color_tolerance,
        )
        if results:
            best = results[0]
            pct = int(best.confidence * 100)
            self._img_compare_result.setText(T("img_compare.hit", pct=pct))
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
                match_color=match_color,
                color_tolerance=color_tolerance,
            )
            top = max(m.confidence for m in fallback) if fallback else 0.0
            top_pct = int(top * 100)
            self._img_compare_result.setText(T("img_compare.miss", top_pct=top_pct))
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
            self._tmpl_label.setText(T("format.embedded_image"))
            self._update_thumbnail()
            self._list.steps_changed.emit()
        elif data:
            self._step.params["template_data"] = data
            self._step.params.pop("template", None)
            self._tmpl_label.setText(T("format.embedded_image"))
            self._update_thumbnail()
            self._list.steps_changed.emit()

    def _pick_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, T("step_form.select_image_title"), "", T("step_form.img_file_filter")
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
                self._roi_label.setText(T("summary.whole_window") if z else _fmt_roi(result))
                self.save()
                self._list.steps_changed.emit()

    def _toggle_on_fail(self):
        self._on_fail_expanded = not self._on_fail_expanded
        self._on_fail_container.setVisible(self._on_fail_expanded)
        self._toggle_btn.setText(
            T("step_form.toggle_image_expanded")
            if self._on_fail_expanded
            else T("step_form.toggle_image_collapsed")
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
        p["match_color"] = self._match_color.isChecked()
        p["color_tolerance"] = self._color_tolerance.value()
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
        elif action == "advance":
            p["on_fail"] = {
                "action": "advance",
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
        groups_provider=None,
    ):
        super().__init__(parent_list)
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
        self._text.editingFinished.connect(self._validate_text)
        form.addRow(T("step_form.target_text"), self._text)

        self._advanced_container = QWidget()
        adv_form = QFormLayout(self._advanced_container)
        adv_form.setContentsMargins(0, 0, 0, 0)

        roi = p.get("roi", {})
        zero = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        self._roi_label = QLabel(T("summary.whole_window") if zero else _fmt_roi(roi))
        self._roi_btn = QPushButton(T("step_form.detect_roi"))
        self._roi_btn.setToolTip(T("tooltip.roi"))
        if roi_cb:
            self._roi_btn.clicked.connect(self._pick_roi)
        adv_form.addRow(T("step_form.detect_region"), self._roi_label)
        adv_form.addRow("", self._roi_btn)

        self._match_mode = _NoWheelCombo()
        self._match_mode.addItem(T("combo.contains"), "contains")
        self._match_mode.addItem(T("combo.exact"), "exact")
        self._match_mode.addItem(T("combo.fuzzy"), "fuzzy")
        self._match_mode.addItem(T("combo.regex"), "regex")
        idx_mm = self._match_mode.findData(p.get("match_mode", "fuzzy"))
        if idx_mm >= 0:
            self._match_mode.setCurrentIndex(idx_mm)
        self._match_mode.currentIndexChanged.connect(self._on_match_mode_changed)
        adv_form.addRow(T("step_form.compare_mode"), self._match_mode)

        self._fuzzy_th = _NoWheelSpin()
        self._fuzzy_th.setRange(1, 100)
        self._fuzzy_th.setSuffix(" %")
        self._fuzzy_th.setValue(int(p.get("fuzzy_threshold", 0.8) * 100))
        self._fuzzy_th.setVisible(self._match_mode.currentData() == "fuzzy")
        adv_form.addRow(T("step_form.accuracy"), self._fuzzy_th)

        # ── on_fail collapsible section (in advanced) ──
        self._on_fail_expanded = False
        self._toggle_btn = QPushButton(T("step_form.toggle_detect_collapsed"))
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

        form.addRow(self._advanced_container)
        form.addRow(self._advanced_container)

        self._of_action.addItem(T("step_form.of_skip_once"), "stop")
        self._of_action.addItem(T("step_form.of_skip_rule"), "advance")
        self._of_action.addItem(T("step_form.of_jump_rule"), "jump")
        self._of_action.addItem(T("step_form.of_key_continue"), "key")
        self._of_action.addItem(T("step_form.of_notify_stop"), "notify")
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
        of_form.addRow(T("step_form.action"), self._of_action)

        self._of_fail_duration = _NoWheelDoubleSpin()
        self._of_fail_duration.setRange(0.0, 30.0)
        self._of_fail_duration.setSingleStep(0.5)
        self._of_fail_duration.setSuffix(T("step_form.of_skip_suffix"))
        self._of_fail_duration.setDecimals(1)
        default_duration = raw.get("fail_duration_sec", 0.0) if isinstance(raw, dict) else 0.0
        try:
            default_duration = float(default_duration)
        except (TypeError, ValueError):
            default_duration = 0.0
        self._of_fail_duration.setValue(default_duration)
        of_form.addRow(T("step_form.fail_duration"), self._of_fail_duration)

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
                self._of_jump_combo.addItem(T("step_form.unknown_rule", id=target_id), target_id)
                j_idx = self._of_jump_combo.count() - 1
            self._of_jump_combo.setCurrentIndex(max(j_idx, 0))
        jf.addWidget(QLabel(T("step_form.skip_to")))
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
        kf.addWidget(QLabel(T("step_form.press_key")))
        kf.addWidget(self._of_key)
        kf.addWidget(QLabel(T("step_form.then_continue")))
        kf.addStretch()
        of_form.addRow("", self._of_key_row)

        # notify widgets
        self._of_notify_msg = QLineEdit()
        self._of_notify_msg.setPlaceholderText(T("step_form.enter_text"))
        of_form.addRow(T("step_form.notify_message"), self._of_notify_msg)
        self._of_notify_msg.setText(default_notify_msg)
        self._of_notify_groups = _StopGroupsPicker(
            groups_provider=self._groups_provider,
            selected=default_notify_groups,
        )
        of_form.addRow(T("step_form.stop_groups"), self._of_notify_groups)

        form.addRow(self._on_fail_container)
        self._on_of_action_changed()

    def _on_match_mode_changed(self, idx):
        self._fuzzy_th.setVisible(self._match_mode.itemData(idx) == "fuzzy")

    def _validate_text(self):
        if not self._text.text().strip():
            self._text.setStyleSheet("border: 1px solid #E74C3C;")
            self._text.setToolTip(T("tooltip.target_text_empty"))
        else:
            self._text.setStyleSheet("")
            self._text.setToolTip("")

    def _toggle_on_fail(self):
        self._on_fail_expanded = not self._on_fail_expanded
        self._on_fail_container.setVisible(self._on_fail_expanded)
        self._toggle_btn.setText(
            T("step_form.toggle_detect_expanded")
            if self._on_fail_expanded
            else T("step_form.toggle_detect_collapsed")
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
                self._roi_label.setText(T("summary.whole_window") if z else _fmt_roi(result))
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
        elif action == "advance":
            self._step.params["on_fail"] = {
                "action": "advance",
                "fail_duration_sec": fail_duration,
            }


class _ClickStepForm(QWidget):
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
        self._target.addItem(T("summary.click_target"), "text_center")
        self._target.addItem(T("step_form.text_coord"), "custom")
        self._target.addItem(T("format.click_mode"), "click_text")
        t_idx = self._target.findData(p.get("target", "text_center"))
        if t_idx >= 0:
            self._target.setCurrentIndex(t_idx)
        self._target.currentIndexChanged.connect(self._on_target_changed)
        form.addRow(T("step_form.click_target"), self._target)

        self._click_text = QLineEdit(p.get("text", ""))
        self._click_text.setVisible(p.get("target", "") == "click_text")
        form.addRow(T("step_form.target_text"), self._click_text)

        self._coord_label = QLabel(_fmt_point(p.get("x", 0), p.get("y", 0)))
        self._pick_btn = QPushButton(T("step_form.pick_coord"))
        if pick_cb:
            self._pick_btn.clicked.connect(self._pick_coord)
        self._coord_row = QWidget()
        cl = QHBoxLayout(self._coord_row)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self._coord_label)
        cl.addWidget(self._pick_btn)
        self._coord_row.setVisible(p.get("target", "") == "custom")
        form.addRow(T("step_form.click_coord"), self._coord_row)

        self._adv_container = QWidget()
        adv_form = QFormLayout(self._adv_container)
        adv_form.setContentsMargins(0, 0, 0, 0)

        self._button = _NoWheelCombo()
        self._button.addItem(T("combo.left"), "left")
        self._button.addItem(T("combo.right"), "right")
        b_idx = self._button.findData(p.get("button", "left"))
        if b_idx >= 0:
            self._button.setCurrentIndex(b_idx)
        adv_form.addRow(T("format.mouse_button"), self._button)

        self._offset = _NoWheelSpin()
        self._offset.setRange(0, 100)
        self._offset.setSuffix(" px")
        self._offset.setValue(p.get("random_offset", 3))
        adv_form.addRow(T("format.random_jitter"), self._offset)

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
                self._step.params["roi_coord"] = "client"
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
        self._target.addItem(T("summary.click_target"), "text_center")
        self._target.addItem(T("step_form.text_coord"), "custom")
        self._target.addItem(T("format.click_mode"), "click_text")
        t_idx = self._target.findData(p.get("target", "text_center"))
        if t_idx >= 0:
            self._target.setCurrentIndex(t_idx)
        self._target.currentIndexChanged.connect(self._on_target_changed)
        form.addRow(T("step_form.drag_start"), self._target)

        self._click_text = QLineEdit(p.get("text", ""))
        self._click_text.setVisible(p.get("target", "") == "click_text")
        form.addRow(T("step_form.target_text"), self._click_text)

        self._coord_label = QLabel(_fmt_point(p.get("x", 0), p.get("y", 0)))
        self._pick_btn = QPushButton(T("step_form.pick_coord_short"))
        if pick_cb:
            self._pick_btn.clicked.connect(self._pick_coord)
        self._coord_row = QWidget()
        cl = QHBoxLayout(self._coord_row)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self._coord_label)
        cl.addWidget(self._pick_btn)
        self._coord_row.setVisible(p.get("target", "") == "custom")
        form.addRow(T("step_form.start_coord"), self._coord_row)
        self._dx = _NoWheelSpin()
        self._dx.setRange(-9999, 9999)
        self._dx.setSuffix(" px")
        self._dx.setValue(p.get("dx", 0))
        form.addRow(T("format.horizontal_offset"), self._dx)

        self._dy = _NoWheelSpin()
        self._dy.setRange(-9999, 9999)
        self._dy.setSuffix(" px")
        self._dy.setValue(p.get("dy", 0))
        form.addRow(T("format.vertical_offset"), self._dy)

        self._button = _NoWheelCombo()
        self._button.addItem(T("combo.left"), "left")
        self._button.addItem(T("combo.right"), "right")
        b_idx = self._button.findData(p.get("button", "left"))
        if b_idx >= 0:
            self._button.setCurrentIndex(b_idx)
        form.addRow(T("format.mouse_button"), self._button)

    def _on_target_changed(self, idx):
        t = self._target.currentData()
        self._coord_row.setVisible(t == "custom")
        self._click_text.setVisible(t == "click_text")

    def _pick_coord(self):
        if self._pick_cb:
            result = self._pick_cb()
            if result:
                self._step.params["x"], self._step.params["y"] = result
                self._step.params["roi_coord"] = "client"
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
        self._direction.addItem(T("summary.down"), "WheelDown")
        self._direction.addItem(T("summary.up"), "WheelUp")
        self._direction.addItem(T("summary.left"), "WheelLeft")
        self._direction.addItem(T("summary.right"), "WheelRight")
        d_idx = self._direction.findData(p.get("direction", "WheelDown"))
        if d_idx >= 0:
            self._direction.setCurrentIndex(d_idx)
        form.addRow(T("step_form.direction"), self._direction)

        self._amount = _NoWheelSpin()
        self._amount.setRange(1, 99)
        self._amount.setValue(p.get("amount", 1))
        form.addRow(T("step_form.times"), self._amount)

        self._delay = _NoWheelSpin()
        self._delay.setRange(0, 1000)
        self._delay.setSuffix(" ms")
        self._delay.setValue(p.get("delay_ms", 30))
        form.addRow(T("step_form.interval"), self._delay)

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
        if "roi_coord" in roi:
            self._roi["roi_coord"] = roi["roi_coord"]
        z = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        self._roi_label = QLabel(T("summary.whole_window") if z else _fmt_roi(roi))
        self._roi_btn = QPushButton(T("step_form.detect_roi"))
        self._roi_btn.setToolTip(T("tooltip.roi_compare"))
        self._roi_btn.clicked.connect(self._pick_roi)
        roi_row = QWidget()
        rr = QHBoxLayout(roi_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.addWidget(self._roi_label)
        rr.addWidget(self._roi_btn)
        form.addRow(T("step_form.detect_region"), roi_row)

        # Operator
        self._operator = _NoWheelCombo()
        for op in (">", "<", ">=", "<=", "==", "!="):
            self._operator.addItem(op, op)
        op_idx = self._operator.findData(p.get("operator", ">="))
        if op_idx >= 0:
            self._operator.setCurrentIndex(op_idx)
        form.addRow(T("step_form.compare_mode"), self._operator)

        # Value
        self._value = _NoWheelDoubleSpin()
        self._value.setRange(-999999.0, 999999.0)
        self._value.setDecimals(3)
        self._value.setValue(p.get("value", 0.0))
        form.addRow(T("step_form.value"), self._value)

        # ── Advanced collapsible section ──
        self._toggle_btn = QPushButton(T("step_form.toggle_compare_collapsed"))
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
        self._pattern.editingFinished.connect(self._validate_pattern)
        self._pattern.setToolTip(T("step_form.regex_pattern_tooltip"))
        adv.addRow(T("step_form.number_format"), self._pattern)

        # on_fail section (same as detect/match_image)
        self._of_action = _NoWheelCombo()
        self._of_action.addItem(T("step_form.of_skip_once"), "stop")
        self._of_action.addItem(T("step_form.of_skip_rule"), "advance")
        self._of_action.addItem(T("step_form.of_jump_step"), "skip")
        self._of_action.addItem(T("step_form.of_jump_rule"), "jump")
        self._of_action.addItem(T("step_form.of_key_continue"), "key")
        self._of_action.addItem(T("step_form.of_notify_stop"), "notify")
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
        adv.addRow(T("step_form.action"), self._of_action)

        self._of_fail_duration = _NoWheelDoubleSpin()
        self._of_fail_duration.setRange(0.0, 30.0)
        self._of_fail_duration.setSingleStep(0.5)
        self._of_fail_duration.setSuffix(T("step_form.of_skip_suffix"))
        self._of_fail_duration.setDecimals(1)
        default_duration = raw_of.get("fail_duration_sec", 0.0) if isinstance(raw_of, dict) else 0.0
        try:
            default_duration = float(default_duration)
        except (TypeError, ValueError):
            default_duration = 0.0
        self._of_fail_duration.setValue(default_duration)
        self._of_fail_duration.setToolTip(T("tooltip.fail_duration"))
        adv.addRow(T("step_form.fail_duration"), self._of_fail_duration)

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
            self._of_jump_combo.addItem(T("step_form.missing_rule", id=target_id), target_id)
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
        skf.addWidget(QLabel(T("step_form.skip_to")))
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
        self._of_notify_msg.setPlaceholderText(T("step_form.enter_text"))
        adv.addRow(T("step_form.notify_message"), self._of_notify_msg)
        self._of_notify_msg.setText(default_notify_msg)
        self._of_notify_groups = _StopGroupsPicker(
            groups_provider=groups_provider,
            selected=default_notify_groups,
        )
        adv.addRow(T("step_form.stop_groups"), self._of_notify_groups)

        form.addRow(self._adv_container)

        self._on_of_action_changed()
        form.addRow(self._adv_container)
        self._on_fail_container = self._adv_container

    def _populate_skip_combo(self, current_skip_to: int):
        self._of_skip_combo.clear()
        self._of_skip_combo.addItem(T("step_form.this_rule_end"), self._step_count)
        start = self._idx + 2
        for i in range(start, self._step_count + 1):
            self._of_skip_combo.addItem(T("step_form.step_n", i=i), i - 1)
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
        fail_duration = self._of_fail_duration.value()
        if action == "stop":
            if fail_duration > 0:
                self._step.params["on_fail"] = {
                    "action": "stop",
                    "fail_duration_sec": fail_duration,
                }
            else:
                self._step.params["on_fail"] = "stop"
        elif action == "skip":
            self._step.params["on_fail"] = {
                "action": "skip",
                "skip_to": self._of_skip_combo.currentData() or 0,
                "fail_duration_sec": fail_duration,
            }
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
        elif action == "advance":
            self._step.params["on_fail"] = {
                "action": "advance",
                "fail_duration_sec": fail_duration,
            }

    def _pick_roi(self):
        if not self._roi_cb:
            return
        result = self._roi_cb()
        if result:
            self._roi = dict(result)
            z = all(v == 0 for v in self._roi.values())
            self._roi_label.setText(T("summary.whole_window") if z else _fmt_roi(self._roi))
            self.save()
            self._list.steps_changed.emit()

    def _toggle_advanced(self):
        expanded = self._adv_container.isVisible()
        self._adv_container.setVisible(not expanded)
        self._toggle_btn.setText(
            T("step_form.toggle_compare_expanded")
            if not expanded
            else T("step_form.toggle_compare_collapsed")
        )

    def _validate_pattern(self):
        import re as _re

        try:
            _re.compile(self._pattern.text())
            self._pattern.setStyleSheet("")
            self._pattern.setToolTip("")
        except _re.error:
            self._pattern.setStyleSheet("border: 1px solid #E74C3C;")
            self._pattern.setToolTip(T("tooltip.invalid_regex"))

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
        form.addRow(T("step_form.key_label"), self._key)

        self._hold_ms = _NoWheelSpin()
        self._hold_ms.setRange(0, 60000)
        self._hold_ms.setSuffix(" ms")
        self._hold_ms.setValue(step.params.get("hold_ms", 0))
        self._hold_ms.setToolTip(T("tooltip.hold_ms"))
        form.addRow(T("step_form.hold_label"), self._hold_ms)

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
        self._ms.setToolTip(T("tooltip.wait_ms"))
        self._ms.setValue(step.params.get("ms", 500))
        self._ms.editingFinished.connect(lambda: self._list.steps_changed.emit())
        form.addRow(T("step_form.milliseconds"), self._ms)

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
            self._combo.addItem(T("step_form.unknown_rule", id=current_id), current_id)
            self._combo.setCurrentIndex(self._combo.count() - 1)
        form.addRow(T("step_form.jump_to_rule"), self._combo)

    def save(self):
        self._step.params["rule_id"] = self._combo.currentData() or ""


class _NotifyStepForm(QWidget):
    def __init__(self, parent_list, step, idx):
        super().__init__()
        self._list = parent_list
        self._step = step
        form = QFormLayout(self)
        form.setContentsMargins(12, 6, 12, 6)

        self._msg = QLineEdit()
        self._msg.setText(step.params.get("message", ""))
        self._msg.setPlaceholderText(T("step_form.enter_text"))
        self._msg.editingFinished.connect(self._validate_msg)
        form.addRow(T("step_form.message_text"), self._msg)

    def _validate_msg(self):
        if not self._msg.text().strip():
            self._msg.setStyleSheet("border: 1px solid #E74C3C;")
            self._msg.setToolTip(T("tooltip.notify_msg_empty"))
        else:
            self._msg.setStyleSheet("")
            self._msg.setToolTip("")
        self._list.steps_changed.emit()

    def save(self):
        self._step.params["message"] = self._msg.text()


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
        self._type.addItem(T("step_form.step_key"), "key")
        self._type.addItem(T("step_form.step_click"), "click")
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
        self._pick_btn = QPushButton(T("step_form.pick_coord_short"))
        self._pick_btn.setEnabled(bool(pick_cb))
        self._pick_btn.clicked.connect(self._pick_coord)
        self._button = _NoWheelCombo()
        self._button.addItem(T("combo.left"), "left")
        self._button.addItem(T("combo.right"), "right")
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

_group_settings_mod = load_sibling("group_settings_controller", "gui/group_settings_controller.py")
GroupSettingsController = _group_settings_mod.GroupSettingsController

_screenshot_mod = load_sibling("screenshot_controller", "gui/screenshot_controller.py")
ScreenshotController = _screenshot_mod.ScreenshotController

_rule_config_mod = load_sibling("rule_config_controller", "gui/rule_config_controller.py")
RuleConfigController = _rule_config_mod.RuleConfigController

_test_run_mod = load_sibling("test_run_controller", "gui/test_run_controller.py")
TestRunController = _test_run_mod.TestRunController

_ocr_mod = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_perf_mod = load_sibling("performance_monitor", "core/10_performance_monitor.py")
_tmpl_mod = load_sibling("template_matching", "core/11_template_matching.py")
img_to_b64 = _tmpl_mod.img_to_b64
b64_to_img = _tmpl_mod.b64_to_img

_updater_mod = load_sibling("updater", "core/12_updater.py")

_hk_mod = load_sibling("global_hotkey", "core/00_global_hotkey.py")
_hk_register = _hk_mod.register
_hk_unregister = _hk_mod.unregister
_hk_handle_native = _hk_mod.handle_native_event

# ── Helpers ──


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
        config_path: str = "",
    ):
        super().__init__()
        self._rules_path = rules_path
        self._window_title = window_title
        self._signals = signals
        self._verbose = verbose
        self._active_group_ids = active_group_ids or []
        self._config_path = config_path
        self._rule_config_ctrl = RuleConfigController()
        self.loop: Optional[MainLoop] = None

    def run(self):
        try:
            loop = MainLoop(
                self._rules_path,
                self._window_title,
                verbose=self._verbose,
                max_cps=self._rule_config_ctrl.get_setting(self, "max_cps"),
                config_path=self._config_path,
            )
            if self._active_group_ids:
                loop.set_active_groups(self._active_group_ids)
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
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self._win = win
        self._ctrl = RuleConfigController()
        self.setWindowTitle(T("settings.title"))
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        # ── 一般分頁 ──
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._max_cps = QSpinBox()
        self._max_cps.setRange(1, 20)
        self._max_cps.setValue(self._ctrl.get_setting(win, "max_cps"))
        self._max_cps.setToolTip(T("settings.max_cps.tooltip"))
        form.addRow(T("settings.max_cps"), self._max_cps)

        self._scan_interval = QSpinBox()
        self._scan_interval.setRange(100, 2000)
        self._scan_interval.setSingleStep(50)
        self._scan_interval.setSuffix(" ms")
        self._scan_interval.setValue(self._ctrl.get_setting(win, "scan_interval_ms"))
        self._scan_interval.setToolTip(T("settings.scan_interval.tooltip"))
        form.addRow(T("settings.scan_interval"), self._scan_interval)

        from i18n import get_language

        self._language = QComboBox()
        self._language.addItem("繁體中文", "zh_TW")
        self._language.addItem("简体中文", "zh_CN")
        self._language.addItem("English", "en")
        lang_idx = self._language.findData(get_language())
        self._language.setCurrentIndex(max(0, lang_idx))
        self._language.setToolTip(T("settings.language.tooltip"))
        form.addRow(T("settings.language"), self._language)

        self._match_mode = QComboBox()
        self._match_mode.addItem(T("combo.contains"), "contains")
        self._match_mode.addItem(T("combo.exact"), "exact")
        self._match_mode.addItem(T("combo.fuzzy"), "fuzzy")
        self._match_mode.addItem(T("combo.regex"), "regex")
        idx = self._match_mode.findData(self._ctrl.get_setting(win, "default_match_mode"))
        self._match_mode.setCurrentIndex(max(0, idx))
        self._match_mode.setToolTip(T("settings.default_match_mode.tooltip"))
        form.addRow(T("settings.default_match_mode"), self._match_mode)

        self._close_behavior = QComboBox()
        self._close_behavior.addItem(T("combo.tray"), "tray")
        self._close_behavior.addItem(T("combo.quit"), "quit")
        idx = self._close_behavior.findData(self._ctrl.get_setting(win, "close_behavior"))
        self._close_behavior.setCurrentIndex(max(0, idx))
        self._close_behavior.setToolTip(T("settings.close_behavior.tooltip"))
        form.addRow(T("settings.close_behavior"), self._close_behavior)

        self._show_close_confirm = QCheckBox(T("settings.show_close_confirm"))
        self._show_close_confirm.setChecked(self._ctrl.get_setting(win, "show_close_confirm"))
        self._show_close_confirm.setToolTip(T("settings.show_close_confirm.tooltip"))
        form.addRow("", self._show_close_confirm)

        self._auto_update = QCheckBox(T("settings.auto_update"))
        self._auto_update.setChecked(not self._ctrl.get_setting(win, "skip_update_check"))
        self._auto_update.setToolTip(T("settings.auto_update.tooltip"))
        form.addRow("", self._auto_update)

        # ── 自動化 / 辨識分頁 ──
        auto = QWidget()
        aform = QFormLayout(auto)
        aform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._mouse_btn = QComboBox()
        self._mouse_btn.addItem(T("combo.left"), "left")
        self._mouse_btn.addItem(T("combo.right"), "right")
        self._mouse_btn.addItem(T("combo.middle"), "middle")
        idx = self._mouse_btn.findData(self._ctrl.get_setting(win, "default_mouse_button"))
        self._mouse_btn.setCurrentIndex(max(0, idx))
        self._mouse_btn.setToolTip(T("settings.default_mouse_button.tooltip"))
        aform.addRow(T("settings.default_mouse_button"), self._mouse_btn)

        self._random_offset = QSpinBox()
        self._random_offset.setRange(0, 10)
        self._random_offset.setSuffix(" px")
        self._random_offset.setValue(self._ctrl.get_setting(win, "default_random_offset"))
        self._random_offset.setToolTip(T("settings.default_random_offset.tooltip"))
        aform.addRow(T("settings.default_random_offset"), self._random_offset)

        self._default_wait_ms = QSpinBox()
        self._default_wait_ms.setRange(0, 60000)
        self._default_wait_ms.setSingleStep(100)
        self._default_wait_ms.setSuffix(" ms")
        self._default_wait_ms.setValue(self._ctrl.get_setting(win, "default_wait_ms"))
        self._default_wait_ms.setToolTip(T("settings.default_wait_ms.tooltip"))
        aform.addRow(T("settings.default_wait_ms"), self._default_wait_ms)

        self._fuzzy_th = QDoubleSpinBox()
        self._fuzzy_th.setRange(0.5, 0.95)
        self._fuzzy_th.setSingleStep(0.05)
        self._fuzzy_th.setDecimals(2)
        self._fuzzy_th.setValue(self._ctrl.get_setting(win, "default_fuzzy_threshold"))
        self._fuzzy_th.setToolTip(T("settings.default_fuzzy_threshold.tooltip"))
        aform.addRow(T("settings.default_fuzzy_threshold"), self._fuzzy_th)

        self._template_th = QDoubleSpinBox()
        self._template_th.setRange(0.6, 0.98)
        self._template_th.setSingleStep(0.05)
        self._template_th.setDecimals(2)
        self._template_th.setValue(self._ctrl.get_setting(win, "default_template_threshold"))
        self._template_th.setToolTip(T("settings.default_template_threshold.tooltip"))
        aform.addRow(T("settings.default_template_threshold"), self._template_th)

        self._color_tol = QSpinBox()
        self._color_tol.setRange(0, 50)
        self._color_tol.setValue(self._ctrl.get_setting(win, "default_color_tolerance"))
        self._color_tol.setToolTip(T("settings.default_color_tolerance.tooltip"))
        aform.addRow(T("settings.default_color_tolerance"), self._color_tol)

        tabs = QTabWidget()
        general = QWidget()
        general.setLayout(form)
        tabs.addTab(general, T("settings.tab_general"))
        tabs.addTab(auto, T("settings.tab_auto"))
        layout.addWidget(tabs)

        # 底部按鈕
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        old_lang = self._ctrl.get_setting(self._win, "language")
        self._ctrl.set_setting(self._win, "max_cps", self._max_cps.value())
        self._ctrl.set_setting(self._win, "scan_interval_ms", self._scan_interval.value())
        self._ctrl.set_setting(self._win, "default_match_mode", self._match_mode.currentData())
        self._ctrl.set_setting(self._win, "close_behavior", self._close_behavior.currentData())
        self._ctrl.set_setting(
            self._win, "show_close_confirm", self._show_close_confirm.isChecked()
        )
        self._ctrl.set_setting(self._win, "skip_update_check", not self._auto_update.isChecked())
        self._ctrl.set_setting(self._win, "default_mouse_button", self._mouse_btn.currentData())
        self._ctrl.set_setting(self._win, "default_random_offset", self._random_offset.value())
        self._ctrl.set_setting(self._win, "default_wait_ms", self._default_wait_ms.value())
        self._ctrl.set_setting(self._win, "default_fuzzy_threshold", self._fuzzy_th.value())
        self._ctrl.set_setting(self._win, "default_template_threshold", self._template_th.value())
        self._ctrl.set_setting(self._win, "default_color_tolerance", self._color_tol.value())
        new_lang = self._language.currentData()
        self._ctrl.set_setting(self._win, "language", new_lang)
        if old_lang != new_lang:
            answer = QMessageBox.question(
                self,
                T("settings.title"),
                T("settings.language_restart"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                _is_frozen = getattr(sys, "frozen", False)
                if _is_frozen:
                    _launch_exe = sys.executable
                    _launch_args: list[str] = []
                    _launch_cwd = str(Path(sys.executable).parent)
                    _relaunch_cmd = [
                        str(Path(sys.executable).parent / "updater.exe"),
                    ]
                else:
                    _launch_exe = sys.executable
                    _launch_args = ["gui/06_gui_main.py"]
                    _launch_cwd = str(Path(__file__).resolve().parent.parent)
                    _relaunch_cmd = [
                        sys.executable,
                        str(Path(__file__).resolve().parent.parent / "updater_main.py"),
                    ]
                subprocess.Popen(
                    _relaunch_cmd
                    + [
                        "--mode=relaunch",
                        f"--wait-pid={os.getpid()}",
                        f"--launch-exe={_launch_exe}",
                        *[f"--launch-arg={a}" for a in _launch_args],
                        f"--launch-cwd={_launch_cwd}",
                    ],
                    close_fds=True,
                )
                self.accept()
                self._win._quit_app()
                return
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
        self._margin = 12
        self._spacing = 4
        self._max_width = 320
        self._labels: list[QLabel] = []

    def push(self, msg: str):
        label = QLabel(msg, self)
        label.setStyleSheet(
            "background: rgba(50,50,50,230); color: #fff; padding: 6px 10px; "
            "border-radius: 4px; font: 9pt;"
        )
        label.setWordWrap(True)
        label.setMaximumWidth(self._max_width)
        label.show()

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda lbl=label, t=timer: self._pop(lbl, t))
        timer.start(2000)

        self._labels.append(label)
        self._reposition()
        self.show()
        self.raise_()

    def _pop(self, label, timer):
        timer.stop()
        timer.deleteLater()
        if label not in self._labels:
            return
        self._labels.remove(label)
        label.deleteLater()
        self._reposition()
        if not self._labels:
            self.hide()

    def _reposition(self):
        if not self._labels:
            return

        max_lbl_w = 0
        total_h = 0
        for lbl in self._labels:
            lbl.adjustSize()
            max_lbl_w = max(max_lbl_w, lbl.width())
            total_h += lbl.height()

        padding = 16
        spacing_total = self._spacing * (len(self._labels) - 1)
        w = max(max_lbl_w + padding, 100)
        h = total_h + spacing_total + padding

        screen = QApplication.primaryScreen()
        if screen is None:
            return
        ag = screen.availableGeometry()
        max_h = int(ag.height() * 0.6)
        if h > max_h:
            h = max_h

        self.resize(int(w), int(h))

        cy = int(h) - 8
        for lbl in reversed(self._labels):
            lbl_h = lbl.height()
            cy -= lbl_h
            lbl.move(8, cy)
            cy -= self._spacing

        x = ag.right() - int(w) - self._margin
        y = ag.bottom() - int(h) - self._margin
        self.move(int(x), int(y))


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
            self._is_starting = False
            self._notif_stack = _NotificationStack()
            self._updating = False
            self._downloading = False
            self._update_cancel = None
            self._pending_update_ver = ""

            self._group_settings_ctrl = GroupSettingsController()
            self._screenshot_ctrl = ScreenshotController(self)
            self._rule_config_ctrl = RuleConfigController()
            self._test_ctrl = TestRunController(self, _of_summary, _resolve_rule_name)
            self._setup_ui()
            self._debug_panel = OcrDebugPanel("", self)
            self._debug_panel.rule_requested.connect(self._on_debug_rule_requested)
            self._debug_panel.step_requested.connect(self._on_debug_step_requested)
            self._debug_panel.template_requested.connect(self._on_debug_template_requested)
            self._debug_panel.template_step_requested.connect(
                self._on_debug_template_step_requested
            )
            self._debug_page_layout.addWidget(self._debug_panel, 1)
            self._connect_signals()
            self._setup_shortcuts()

            _ocr_mod.set_ocr_health_callback(self._on_ocr_health)

            QTimer.singleShot(0, self._deferred_init)
        except Exception as e:
            QMessageBox.critical(
                self, T("dialog.startup_failed"), T("dialog.startup_failed_msg", error=e)
            )
            raise

        # ── 系統托盤 ──
        _icon_path = Path(__file__).resolve().parent.parent / "icons" / "app.ico"
        _app_icon = QIcon(str(_icon_path)) if _icon_path.exists() else QIcon()
        self.setWindowIcon(_app_icon)
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_app_icon)
        self._tray.setToolTip("OCR Trigger Clicker")
        _tray_menu = QMenu(self)
        _tray_menu.addAction(T("tray.show"), self._restore_window)
        _tray_menu.addAction(T("tray.settings"), self._open_settings)
        _tray_menu.addAction(T("tray.check_update"), lambda: self._check_version(force=True))
        _tray_menu.addSeparator()
        _tray_menu.addAction(T("tray.quit"), self._quit_app)
        self._tray.setContextMenu(_tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        # ── Global hotkeys ──
        _hk_register(int(self.winId()))

    def _load_config(self) -> dict:
        return self._rule_config_ctrl.load_config(self)

    def _save_config(self, data: dict):
        self._rule_config_ctrl.save_config(self, data)

    def _deferred_init(self):
        try:
            self._status_bar.showMessage(T("status.loading_windows"))
            self._refresh_window_list()

            self._status_bar.showMessage(T("status.loading_task"))
            self._refresh_task_list()

            self._restore_last_state()
            self._maybe_show_startup_guide()

            config = self._load_config()
            updated_ver = config.pop("just_updated", None)
            if updated_ver:
                self._save_config(config)
                QTimer.singleShot(
                    4000,
                    lambda v=updated_ver: (
                        self._status_bar.showMessage(T("status.update_complete", v=v), 8000),
                        self._notif_stack.push(T("step_form.update_toast", v=v)),
                    ),
                )

            QTimer.singleShot(3000, lambda: self._check_version(force=False))

            QTimer.singleShot(100, self._init_ahk_async)
        except Exception as e:
            logging.exception("deferred init failed")
            self._status_bar.showMessage(T("status.partial_init_error", e=e))

    def _init_ahk_async(self):
        if not _ahk_mod.is_ahk_available():
            self._status_bar.showMessage(T("status.ahk_not_installed"), 0)
            self._status_bar.mousePressEvent = lambda e: self._prompt_ahk_install()
            return

        class _AhkWorker(QThread):
            done = pyqtSignal(bool)

            def run(self):
                ok = _ahk_mod.init_ahk()
                self.done.emit(ok)

        self._status_bar.showMessage(T("status.ahk_starting"))
        self._ahk_ready = False
        self._ahk_worker = _AhkWorker()
        self._ahk_worker.done.connect(self._on_ahk_init_done)
        self._ahk_worker.start()

    def _prompt_ahk_install(self):
        reply = QMessageBox.question(
            self,
            T("dialog.install_ahk"),
            T("dialog.install_ahk_msg"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._status_bar.showMessage(T("update.download_ahk"))
            QApplication.processEvents()

            def _ahk_health_cb(msg):
                self._status_bar.showMessage(f"⚠ {msg}")
                self._update_ahk_status(False)

            _ahk_mod.set_ahk_health_callback(_ahk_health_cb)
            if not _ahk_mod.download_ahk():
                QMessageBox.critical(
                    self,
                    T("update.download_failed"),
                    T("update.download_failed_manual")
                    + "https://www.autohotkey.com\n\n"
                    + T("dialog.install_ahk_success"),
                )
                return

            class _AhkWorker(QThread):
                done = pyqtSignal(bool)

                def run(self):
                    ok = _ahk_mod.init_ahk()
                    self.done.emit(ok)

            self._status_bar.showMessage(T("status.ahk_starting"))
            self._ahk_ready = False
            self._ahk_worker = _AhkWorker()
            self._ahk_worker.done.connect(self._on_ahk_init_done)
            self._ahk_worker.start()

    def _on_ahk_init_done(self, ok):
        self._ahk_worker = None
        self._ahk_ready = ok
        self._update_ahk_status(ok)
        if not ok:
            self._status_bar.showMessage(T("status.ahk_not_started"))
        else:
            self._status_bar.showMessage(T("status.ahk_ready"), 3000)

    def _maybe_show_startup_guide(self):
        config = self._load_config()
        if config.get("hide_startup_guide", False):
            return
        config["hide_startup_guide"] = True
        self._save_config(config)
        self._notif_stack.push(T("ui.start_guide"))

    def _restore_last_state(self):
        config = self._load_config()

        last_win = config.get("last_window", "")
        if last_win:
            idx = self._window_combo.findText(last_win)
            if idx >= 0:
                self._window_combo.setCurrentIndex(idx)
            else:
                self._window_combo.setPlaceholderText(
                    T("status.last_window_not_found", title=last_win)
                )
                self._status_bar.showMessage(T("status.last_window_not_found", title=last_win))
        last_task = config.get("last_task", "")
        if last_task:
            idx = self._task_combo.findText(last_task)
            if idx >= 0:
                self._task_combo.setCurrentIndex(idx)

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
        self._window_combo.setPlaceholderText(T("status.select_window"))
        toolbar.addWidget(QLabel(T("main.window")))
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
        self._task_combo.setToolTip(T("tooltip.task_combo"))
        self._task_new_btn = QPushButton("＋")
        self._task_new_btn.setFixedWidth(28)
        self._task_new_btn.setToolTip(T("tooltip.task_new"))
        self._task_rename_btn = QPushButton("✏️")
        self._task_rename_btn.setFixedWidth(28)
        self._task_rename_btn.setToolTip(T("tooltip.task_rename"))
        self._task_del_btn = QPushButton("🗑")
        self._task_del_btn.setFixedWidth(28)
        self._task_del_btn.setToolTip(T("tooltip.task_delete"))
        self._task_import_btn = QPushButton(T("main.import_task"))
        self._task_import_btn.setToolTip(T("tooltip.task_import"))
        self._task_export_btn = QPushButton(T("main.export_task"))
        self._task_export_btn.setToolTip(T("tooltip.task_export"))
        toolbar.addWidget(QLabel(T("main.task")))
        toolbar.addWidget(self._task_combo)
        toolbar.addWidget(self._task_new_btn)
        toolbar.addWidget(self._task_rename_btn)
        toolbar.addWidget(self._task_del_btn)
        toolbar.addWidget(self._task_import_btn)
        toolbar.addWidget(self._task_export_btn)
        self._task_share_btn = QPushButton(T("main.share_task"))
        self._task_share_btn.setToolTip(T("tooltip.task_share"))
        self._task_share_btn.clicked.connect(self._open_task_share)
        toolbar.addWidget(self._task_share_btn)

        # -- Action section --
        self._btn_toggle = QPushButton(T("step_form.start_btn"))
        self._btn_toggle.setMinimumWidth(80)
        self._btn_toggle.setToolTip(T("tooltip.toggle"))
        self._debug_btn = QPushButton(T("main.ocr_debug"))
        self._debug_btn.setToolTip(T("tooltip.debug"))
        toolbar.addWidget(self._btn_toggle)
        toolbar.addWidget(self._debug_btn)
        toolbar.addStretch()
        self._sponsor_btn = QPushButton(T("main.sponsor"))
        self._sponsor_btn.setToolTip(T("tooltip.sponsor"))
        self._sponsor_btn.clicked.connect(self._open_sponsor)
        toolbar.addWidget(self._sponsor_btn)
        self._settings_btn = QPushButton(T("main.settings"))
        self._settings_btn.setToolTip(T("tooltip.settings"))
        self._settings_btn.clicked.connect(self._open_settings)
        toolbar.addWidget(self._settings_btn)
        self._about_btn = QPushButton(T("main.about"))
        self._about_btn.setToolTip(T("tooltip.about", version=__version__, author=__author__))
        self._about_btn.clicked.connect(self._show_about)
        toolbar.addWidget(self._about_btn)
        self._guide_btn = QPushButton(T("main.guide"))
        self._guide_btn.setToolTip(T("tooltip.guide"))
        self._guide_btn.clicked.connect(self._open_guide)
        toolbar.addWidget(self._guide_btn)
        self._update_btn = QPushButton(T("main.update"))
        self._update_btn.setToolTip(T("tooltip.update"))
        self._update_btn.clicked.connect(lambda: self._check_version(force=True))
        toolbar.addWidget(self._update_btn)
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
        left_layout.addWidget(QLabel(T("main.rule_list")))

        self._rule_list = _RuleTreeWidget()
        self._rule_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
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

        self._rule_hint = QLabel(T("ui.add_first_rule"))
        self._rule_hint.setStyleSheet("color: #888; font-size: 11px;")
        left_layout.addWidget(self._rule_hint)

        rule_btn_bar = QHBoxLayout()
        self._add_group_btn = QPushButton(T("main.add_group"))
        self._add_group_btn.setToolTip(T("tooltip.add_group"))
        self._add_rule_btn = QPushButton(T("main.add_rule"))
        self._add_rule_btn.setToolTip(T("tooltip.add_rule"))
        self._del_rule_btn = QPushButton(T("main.delete"))
        self._del_rule_btn.setToolTip(T("tooltip.delete_rule"))
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
            T("guide.usage")
            + T("guide.step1")
            + T("guide.step2")
            + T("guide.step3")
            + T("guide.step4")
            + T("guide.step5")
            + T("step_form.detect_hint")
            + "▸ "
            + T("guide.advanced")
            + T("guide.advanced2")
            + T("guide.advanced3")
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
        name_row.addWidget(QLabel(T("main.name")))
        self._edit_name = QLineEdit()
        name_row.addWidget(self._edit_name, 1)
        name_row.addWidget(QLabel(T("main.enabled")))
        self._edit_enabled = QCheckBox()
        name_row.addWidget(self._edit_enabled)
        name_row.addWidget(QLabel(T("main.background")))
        self._edit_background = QCheckBox(T("ui.background_monitor"))
        self._edit_background.setToolTip(T("ui.background_monitor_hint"))
        name_row.addWidget(self._edit_background)
        edit_layout.addLayout(name_row)

        notes_row = QHBoxLayout()
        notes_row.addWidget(QLabel(T("main.notes")))
        self._edit_notes = QPlainTextEdit()
        self._edit_notes.setPlaceholderText(T("format.notes"))
        self._edit_notes.setMaximumHeight(60)
        notes_row.addWidget(self._edit_notes, 1)
        edit_layout.addLayout(notes_row)

        edit_layout.addWidget(QLabel(T("main.step_list")))

        self._step_list = _StepListWidget()
        self._step_list.set_roi_callback(self._screenshot_ctrl.open_roi_selector)
        self._step_list.set_capture_callback(self._screenshot_ctrl.open_capture_region)
        self._step_list.set_click_pick_callback(self._on_pick_coord)
        self._step_list.set_rules_provider(lambda: list(self._rules))
        self._step_list.set_groups_provider(lambda: self._groups)
        self._step_list.set_window_title_callback(lambda: self._window_combo.currentText())
        self._step_list.set_task_path_callback(
            lambda: (
                str(_rule_mod.get_tasks_dir() / f"{self._current_task}.json")
                if self._current_task
                else ""
            )
        )
        edit_layout.addWidget(self._step_list, 1)

        # Add step dropdown
        add_dropdown = QPushButton(T("ui.add_step"))
        add_dropdown.setToolTip(T("tooltip.add_step"))
        add_menu = QMenu(self)
        step_types = [
            ("detect", T("step.detect_label"), T("step_form.step_detect_desc")),
            ("match_image", T("step.match_image_label"), T("step_form.step_match_image_desc")),
            ("compare", T("step.compare_label"), T("step_form.step_compare_desc")),
            ("click", T("step.click_label"), T("step_form.step_click_desc")),
            ("key", T("step.key_label"), T("step_form.step_key_desc")),
            ("drag", T("step.drag_label"), T("step_form.step_drag_desc")),
            ("scroll", T("step.scroll_label"), T("step_form.step_scroll_desc")),
            ("wait", T("step.wait_label"), T("step_form.step_wait_desc")),
            ("jump", T("step.jump_label"), T("step_form.step_jump_desc")),
            ("notify", T("step.notify_label"), T("step_form.step_notify_desc")),
        ]
        for st, label, tip in step_types:
            action = add_menu.addAction(label)
            action.setData(st)
            action.setToolTip(tip)
            action.triggered.connect(lambda checked, t=st: self._add_step(t))
        add_dropdown.setMenu(add_menu)
        edit_layout.addWidget(add_dropdown)

        # Save indicator + Test
        self._saved_label = QLabel(T("status.saved"))
        self._saved_label.setStyleSheet("color: #4caf50; font-weight: bold;")
        self._saved_label.setVisible(False)
        self._edit_test_btn = QPushButton(T("ui.test"))
        self._edit_test_btn.setEnabled(False)
        self._edit_test_btn.setVisible(False)
        self._open_log_btn = QPushButton(T("main.log"))
        self._open_log_btn.setToolTip(T("tooltip.open_log"))
        self._open_log_btn.setStyleSheet("color: #888888;")
        self._open_log_btn.clicked.connect(self._open_log_dir)
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addWidget(self._saved_label)
        btn_layout.addWidget(self._edit_test_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self._open_log_btn)
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
        self._debug_back_btn = QPushButton(T("ui.back_to_rules"))
        debug_top_bar.addWidget(self._debug_back_btn)
        debug_top_bar.addStretch()
        debug_page_layout.addLayout(debug_top_bar)
        self._debug_page_layout = debug_page_layout

        self._main_stack.addWidget(self._debug_page)
        self._main_stack.setCurrentIndex(0)
        layout.addWidget(self._main_stack)

        # === Status bar ===
        self._status_bar = QStatusBar()
        self._status_bar.showMessage(T("main.ready"))
        self._perf_label = QLabel(T("fps.idle"))
        self._perf_label.setStyleSheet("color: #888; font-size: 11px; padding-right: 8px;")
        self._status_bar.addPermanentWidget(self._perf_label)
        self._ahk_status_label = QLabel("🔴 AHK")
        self._ahk_status_label.setStyleSheet("color: #888; font-size: 11px; padding-right: 8px;")
        self._status_bar.addPermanentWidget(self._ahk_status_label)
        self._perf_timer = QTimer()
        self._perf_timer.timeout.connect(self._update_perf_display)
        self._perf_timer.start(1000)
        self._bg_perf = _perf_mod.PerformanceMonitor(max_cps=999)
        self._bg_perf.start()
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
        self._edit_test_btn.clicked.connect(self._test_ctrl.on_test_rule)
        self._edit_enabled.stateChanged.connect(self._on_enabled_changed)
        self._edit_background.stateChanged.connect(self._on_background_changed)
        self._edit_notes.textChanged.connect(self._on_notes_changed)
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
        self._signals.error_signal.connect(
            lambda msg: QMessageBox.warning(self, T("dialog.engine_error"), msg)
        )
        self._signals.finished.connect(self._on_loop_finished)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+N"), self, self._add_rule)
        QShortcut(QKeySequence("Delete"), self, self._delete_rule)

    def _on_ocr_health(self, msg: str):
        self._status_bar.showMessage(f"⚠ {msg}", 8000)

    def _update_ahk_status(self, connected: bool):
        if connected:
            self._ahk_status_label.setText("🟢 AHK")
            self._ahk_status_label.setStyleSheet(
                "color: #27AE60; font-size: 11px; padding-right: 8px;"
            )
        else:
            self._ahk_status_label.setText("🔴 AHK")
            self._ahk_status_label.setStyleSheet(
                "color: #E74C3C; font-size: 11px; padding-right: 8px;"
            )

    # === Window list ===
    def _on_window_selected(self, title: str):
        if title and self._current_task:
            task_path = str(_rule_mod.get_tasks_dir() / f"{self._current_task}.json")
            set_task_window(task_path, title)

    def _refresh_window_list(self):
        self._window_combo.clear()
        windows = list_windows()
        if not windows:
            self._window_combo.setPlaceholderText(T("status.window_not_found"))
        else:
            self._window_combo.setPlaceholderText(T("main.window") + " " + T("status.no_window"))
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
            stats = self._bg_perf.get_stats()
            text = T(
                "fps.active",
                fps="--",
                cpu=f"{stats['cpu_pct']:.0f}",
                mem=f"{stats['memory_mb']:.0f}",
                click_rate="--",
            )
            self._perf_label.setText(text)
            self._perf_label.setStyleSheet("color: #888; font-size: 11px; padding-right: 8px;")
            return
        stats = self._loop.get_perf_stats()
        fps = stats["fps"]
        cpu = stats["cpu_pct"]
        mem = stats["memory_mb"]
        click_rate = stats["click_rate"]
        text = T(
            "fps.active",
            fps=f"{fps:.1f}",
            cpu=f"{cpu:.0f}",
            mem=f"{mem:.0f}",
            click_rate=f"{click_rate:.0f}",
        )
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
        self._rule_config_ctrl.refresh_task_list(self)

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
        _main_loop_mod.log_main(T("notif.task_loaded", name=name, count=len(self._rules)))
        task_path = str(_rule_mod.get_tasks_dir() / f"{name}.json")
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
                _main_loop_mod.log_main(
                    T("notif.duplicates_removed", count=len(dupes), names=", ".join(dupes))
                )
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
        self._status_bar.showMessage(T("format.task_rules", name=name, count=len(self._rules)))
        # 自動選取任務綁定的視窗
        task_path = str(_rule_mod.get_tasks_dir() / f"{name}.json")
        saved_window = get_task_window(task_path)
        if saved_window:
            idx = self._window_combo.findText(saved_window)
            if idx >= 0:
                self._window_combo.setCurrentIndex(idx)

    def _on_task_new(self):
        from PyQt6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self, T("dialog.new_task"), T("dialog.new_task_hint"), text=""
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        existing = list_tasks()
        if name in existing:
            QMessageBox.warning(
                self, T("dialog.task_exists"), T("dialog.task_exists_msg", name=name)
            )
            return
        self._groups = [RuleGroup(id="__default__", name=T("ui.all_rules"))]
        save_task(name, [])
        save_groups(self._groups, str(_rule_mod.get_tasks_dir() / f"{name}.json"))
        self._refresh_task_list()
        idx = self._task_combo.findText(name)
        if idx >= 0:
            self._task_combo.setCurrentIndex(idx)
        self._status_bar.showMessage(T("notif.task_created", name=name))

    def _on_task_rename(self):
        if not self._current_task:
            return
        from PyQt6.QtWidgets import QInputDialog

        old_name = self._current_task
        name, ok = QInputDialog.getText(
            self, T("dialog.rename_task"), T("dialog.rename_task_hint"), text=old_name
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if name == old_name:
            return
        existing = list_tasks()
        if name in existing:
            QMessageBox.warning(
                self, T("dialog.task_exists"), T("dialog.task_exists_msg", name=name)
            )
            return
        self._flush_save()
        if not rename_task(old_name, name):
            QMessageBox.warning(self, T("dialog.cannot_rename"), T("dialog.cannot_rename"))
            return
        self._refresh_task_list()
        idx = self._task_combo.findText(name)
        if idx >= 0:
            self._task_combo.setCurrentIndex(idx)
        self._status_bar.showMessage(T("notif.task_renamed", old_name=old_name, name=name))

    def _on_task_delete(self):
        if not self._current_task:
            return
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, T("dialog.notice"), T("status.stop_first_delete_task"))
            return
        tasks = list_tasks()
        if len(tasks) <= 1:
            QMessageBox.warning(self, T("dialog.cannot_delete"), T("dialog.at_least_one_task"))
            return
        if (
            QMessageBox.question(
                self,
                T("dialog.delete_task"),
                T("dialog.delete_task_msg", name=self._current_task),
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
        dialog.setWindowTitle(T("dialog.import_task_preview"))
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)

        meta = preview.meta
        meta_lines = []
        if meta.get("description"):
            meta_lines.append(T("format.description", description=meta["description"]))
        if meta.get("author"):
            meta_lines.append(T("format.author", author=meta["author"]))
        if meta.get("game"):
            meta_lines.append(T("format.game", game=meta["game"]))
        if meta.get("app_version"):
            meta_lines.append(T("format.app_version", version=meta["app_version"]))
        if meta_lines:
            layout.addWidget(QLabel(T("format.task_info")))
            meta_label = QLabel("\n".join(meta_lines))
            meta_label.setWordWrap(True)
            layout.addWidget(meta_label)

        layout.addWidget(QLabel(T("format.import_preview", count=preview.rule_count)))
        names_text = "\n".join(f"  • {n}" for n in preview.rule_names[:20])
        if preview.rule_count > 20:
            names_text += "\n  " + T("format.import_overflow", count=preview.rule_count - 20)
        names_label = QLabel(names_text)
        names_label.setWordWrap(True)
        layout.addWidget(names_label)

        if preview.warnings:
            layout.addWidget(QLabel(f"▸ {T('format.warnings_title')}"))
            warn_label = QLabel("\n".join(f"  ⚠ {w}" for w in preview.warnings))
            warn_label.setWordWrap(True)
            warn_label.setStyleSheet("color: #cc8800;")
            layout.addWidget(warn_label)

        cb = QCheckBox(T("ui.regenerate_ids"))
        cb.setChecked(False)
        layout.addWidget(cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(T("dialog.import_task"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        result = dialog.exec()
        return result == QDialog.DialogCode.Accepted, cb.isChecked()

    def _on_task_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, T("dialog.import_task"), str(_here), "JSON (*.json)"
        )
        if not path:
            return
        try:
            if Path(path).stat().st_size > _MAX_IMPORT_SIZE:
                QMessageBox.warning(
                    self, T("dialog.import_task"), T("dialog.import_task_too_large")
                )
                return
        except OSError:
            pass
        preview = preview_import_task(path)
        if preview is None or preview.rule_count == 0:
            QMessageBox.warning(self, T("dialog.import_task"), T("dialog.import_task_invalid"))
            return
        accepted, regen = self._show_import_preview_dialog(preview)
        if not accepted:
            return
        imported_name = import_task(path, regenerate_uuids=regen)
        if imported_name is None:
            QMessageBox.warning(self, T("dialog.import_task"), T("dialog.cannot_write"))
            return
        self._refresh_task_list()
        idx = self._task_combo.findText(imported_name)
        if idx >= 0:
            self._task_combo.setCurrentIndex(idx)
        msg = T("notif.task_imported", name=imported_name)
        if preview.warnings:
            msg += T("notif.task_import_warnings", count=len(preview.warnings))
        self._status_bar.showMessage(msg, 8000)
        if preview.warnings:
            QMessageBox.information(
                self,
                T("dialog.import_task"),
                T(
                    "notif.task_imported_with_warnings",
                    name=imported_name,
                    count=len(preview.warnings),
                )
                + "\n".join(preview.warnings),
            )

    def _on_task_export(self):
        if not self._current_task:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            T("dialog.export_task"),
            str(_here / f"{self._current_task}.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        if export_task(self._current_task, path):
            self._status_bar.showMessage(T("notif.task_exported", name=self._current_task))
        else:
            QMessageBox.warning(self, T("dialog.export_task"), T("dialog.cannot_write"))

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

    def _refresh_rule_list(self, _expand_gid: str | None = None):
        self._rule_list.blockSignals(True)
        self._rule_list.clear()
        rule_map = {r.id: r for r in self._rules}

        if not self._groups:
            all_ids = [r.id for r in self._rules]
            if all_ids:
                default = RuleGroup(
                    id="__default__", name=T("ui.all_rules"), rule_ids=list(all_ids)
                )
                self._groups = [default]
            else:
                self._groups = [RuleGroup(id="__default__", name=T("ui.all_rules"))]

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
            group_item.setToolTip(0, T("tooltip.group_item"))
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
                child.setToolTip(0, T("tooltip.rule_item"))
                group_item.addChild(child)
                if r.id == self._selected_rule_id:
                    selected_item = child
            self._rule_list.addTopLevelItem(group_item)
            self._rule_list.setItemWidget(group_item, 1, self._make_group_buttons(g.id))

        # 常駐監控固定節點
        bg_rules = [r for r in self._rules if r.background]
        if bg_rules:
            bg_item = QTreeWidgetItem()
            bg_item.setText(0, T("ui.background_monitor"))
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
                child.setToolTip(0, T("tooltip.rule_item"))
                bg_item.addChild(child)
                if r.id == self._selected_rule_id:
                    selected_item = child
            self._rule_list.addTopLevelItem(bg_item)
            bg_item.setExpanded("__background__" not in self._collapsed_groups)

        # 設定各群組展開/折疊狀態，跳過 expandAll 避免抖動
        # 此時仍在 blockSignals(True) 保護下，itemExpanded/itemCollapsed 不會誤觸
        for i in range(self._rule_list.topLevelItemCount()):
            item = self._rule_list.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] in ("group", "bg_group"):
                gid = data[1]
                if gid == _expand_gid:
                    item.setExpanded(True)
                else:
                    item.setExpanded(gid not in self._collapsed_groups)
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
            if st.get("failed"):
                icon_color = (220, 50, 50)
            elif st.get("group_done"):
                icon_color = (30, 100, 180)
            elif enabled:
                icon_color = (0, 180, 0)
            else:
                icon_color = (160, 160, 160)
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
            task_path = _rule_mod.get_tasks_dir() / f"{self._current_task}.json"
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
                    logging.info(
                        "[_on_rule_selected] prev=%s checkbox=%s prev_bg=%s groups=%s",
                        prev_rule.name,
                        self._edit_background.isChecked(),
                        prev_rule.background,
                        [(g.id, list(g.rule_ids)) for g in self._groups],
                    )
                    prev_rule.background = self._edit_background.isChecked()
                    prev_rule.notes = self._edit_notes.toPlainText()
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
        logging.warning(
            "[_on_rules_reordered] FIRED topLevelCount=%d", self._rule_list.topLevelItemCount()
        )
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
            if not gdata:
                continue
            if gdata[0] == "bg_group":
                gid = gdata[1]
                new_group_ids.append(gid)
                for j in range(group_item.childCount()):
                    child = group_item.child(j)
                    cdata = child.data(0, Qt.ItemDataRole.UserRole)
                    if cdata and cdata[0] == "rule" and cdata[1] not in seen:
                        seen.add(cdata[1])
                        rule = next((r for r in self._rules if r.id == cdata[1]), None)
                        if rule:
                            new_order.append(rule)
                continue
            if gdata[0] != "group":
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
        self._edit_notes.blockSignals(True)
        self._edit_notes.setPlainText(getattr(rule, "notes", ""))
        self._edit_notes.blockSignals(False)
        self._step_list.setVisible(True)
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
        _before_groups = [(g.id, list(g.rule_ids)) for g in self._groups]
        logging.info(
            "[background_changed] rule=%s background=%s state=%s _selected=%s groups_before=%s",
            rule.name,
            rule.background,
            state,
            self._selected_rule_id,
            _before_groups,
        )
        rule.background = bool(state)
        if rule.background:
            for g in self._groups:
                if rule.id in g.rule_ids:
                    g.rule_ids.remove(rule.id)
        else:
            target = next((g for g in self._groups if g.id == "__uncategorized__"), None)
            if target is None:
                target = RuleGroup(
                    id="__uncategorized__", name=T("ui.uncategorized"), enabled=False
                )
                self._groups.append(target)
            if rule.id not in target.rule_ids:
                target.rule_ids.append(rule.id)
            if self._groups[-1].id != "__uncategorized__":
                self._groups.remove(target)
                self._groups.append(target)
            self._status_bar.showMessage(
                T("notif.rule_removed_from_uncategorized", name=rule.name), 4000
            )
        logging.info(
            "[background_changed] AFTER rules_bg=%s groups=%s",
            [(r.name, r.background) for r in self._rules],
            [(g.id, list(g.rule_ids)) for g in self._groups],
        )
        self._flush_save()
        if self._loop:
            self._loop.reload_rules()
        self._refresh_rule_list()

    def _on_notes_changed(self):
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.notes = self._edit_notes.toPlainText()
        self._schedule_save()

    def _clear_uncategorized(self):
        target = next((g for g in self._groups if g.id == "__uncategorized__"), None)
        if target is None or not target.rule_ids:
            return
        count = len(target.rule_ids)
        reply = QMessageBox.question(
            self,
            T("ui.clear_uncategorized"),
            T("dialog.delete_uncategorized_confirm", count=count),
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
        toggle.setToolTip(T("tooltip.disable_group") if enabled else T("tooltip.enable_group"))
        toggle.setStyleSheet("color: #4a4;" if enabled else "color: #888;")
        toggle.clicked.connect(lambda: self._toggle_group(gid))
        layout.addWidget(toggle)
        up = QPushButton("▲")
        up.setFixedSize(22, 22)
        up.setToolTip(T("tooltip.up_group"))
        up.clicked.connect(lambda: self._move_group_up(gid))
        down = QPushButton("▼")
        down.setFixedSize(22, 22)
        down.setToolTip(T("tooltip.down_group"))
        down.clicked.connect(lambda: self._move_group_down(gid))
        layout.addWidget(up)
        layout.addWidget(down)
        return w

    def _add_group(self):
        import uuid

        g = RuleGroup(id=f"group_{uuid.uuid4().hex[:8]}", name=T("ui.new_group"))
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
            QMessageBox.warning(self, T("dialog.notice"), T("status.stop_first_delete_group"))
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
                T("dialog.cannot_delete"),
                T("dialog.uncategorized_system"),
            )
            return
        rule_count = len([rid for rid in group.rule_ids if any(r.id == rid for r in self._rules)])
        msg = T("dialog.delete_group_confirm", name=group.name)
        if rule_count > 0:
            msg += T("dialog.delete_group_has_rules", count=rule_count)
        if (
            QMessageBox.question(
                self,
                T("ui.delete_group"),
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

        new_name, ok = QInputDialog.getText(
            self, T("step_form.rename_group"), T("format.new_group_name"), text=group.name
        )
        if ok and new_name.strip():
            group.name = new_name.strip()
            self._refresh_rule_list()
            self._flush_save()

    def _show_group_settings(self):
        self._group_settings_ctrl.show(self)

    def _on_item_double_clicked(self, item, column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "group":
            gid = data[1]
            if gid == "__uncategorized__":
                return
            self._rename_group(item)

    def _add_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, T("dialog.notice"), T("status.stop_first_add_rule"))
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

        cfg = self._rule_config_ctrl.load_config(self)
        rule = Rule(
            id=f"rule_{uuid.uuid4().hex[:8]}",
            name=T("ui.new_rule"),
            enabled=True,
            steps=[
                Step(
                    type="detect",
                    params={
                        "text": "",
                        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
                        "match_mode": cfg.get("default_match_mode", "fuzzy"),
                        "fuzzy_threshold": cfg.get("default_fuzzy_threshold", 0.8),
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
        self._refresh_rule_list(target_group.id if target_group else None)
        if self._loop:
            self._loop.reload_rules()

    def _add_step(self, step_type: str):
        default_params = deepcopy(_STEP_DEFAULTS.get(step_type, {}))
        if step_type in ("detect", "compare", "match_image"):
            default_params.setdefault(
                "match_mode", self._rule_config_ctrl.get_setting(self, "default_match_mode")
            )
        if step_type in ("detect",):
            default_params.setdefault(
                "fuzzy_threshold",
                self._rule_config_ctrl.get_setting(self, "default_fuzzy_threshold"),
            )
        if step_type in ("match_image",):
            default_params.setdefault(
                "threshold", self._rule_config_ctrl.get_setting(self, "default_template_threshold")
            )
            default_params.setdefault(
                "color_tolerance",
                self._rule_config_ctrl.get_setting(self, "default_color_tolerance"),
            )
        if step_type in ("click", "drag"):
            default_params.setdefault(
                "button", self._rule_config_ctrl.get_setting(self, "default_mouse_button")
            )
            default_params.setdefault(
                "random_offset", self._rule_config_ctrl.get_setting(self, "default_random_offset")
            )
        if step_type == "wait":
            default_params["ms"] = self._rule_config_ctrl.get_setting(self, "default_wait_ms", 500)
        step = Step(type=step_type, params=default_params)
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
            QMessageBox.warning(self, T("dialog.notice"), T("status.stop_first_delete_rule"))
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
        msg = T("dialog.delete_rule_confirm", name=rule.name)
        if refs:
            msg += "\n\n" + T("dialog.dependency_warning") + "\n".join(f"  • {n}" for n in refs)
        if (
            QMessageBox.question(
                self,
                T("ui.delete_rule"),
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._rules = [r for r in self._rules if r.id != rule.id]
        _main_loop_mod.log_main(T("log.deleted_rule", name=rule.name, id=rule.id))
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
            act = menu.addAction(T("ui.copy_rule"))
            act.triggered.connect(self._duplicate_rule)
            copy_to_menu = menu.addMenu(T("ui.copy_to_group"))
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
            move_to_menu = menu.addMenu(T("ui.move_to_group"))
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
                act = menu.addAction(T("ui.clear_uncategorized"))
                act.triggered.connect(self._clear_uncategorized)
                menu.addSeparator()
            else:
                act = menu.addAction(T("ui.rename"))
                act.triggered.connect(lambda: self._rename_group(item))
                act = menu.addAction(T("ui.group_settings"))
                act.triggered.connect(self._show_group_settings)
                menu.addSeparator()
            act = menu.addAction(T("ui.move_up"))
            act.triggered.connect(lambda checked, gid=gid: self._move_group_up(gid))
            act = menu.addAction(T("ui.move_down"))
            act.triggered.connect(lambda checked, gid=gid: self._move_group_down(gid))
            menu.addSeparator()
            act = menu.addAction(T("ui.delete_group"))
            act.triggered.connect(self._delete_group)
        menu.exec(self._rule_list.viewport().mapToGlobal(pos))

    def _next_duplicate_name(self, src_name: str) -> str:

        base = re.sub(r"\s+\(\d+\)$", "", src_name)
        existing = {r.name for r in self._rules}
        n = 2
        while f"{base} ({n})" in existing:
            n += 1
        return f"{base} ({n})"

    def _duplicate_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, T("dialog.notice"), T("status.stop_first_copy_rule"))
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
        new.name = self._next_duplicate_name(src.name)
        self._rules.append(new)
        _main_loop_mod.log_main(
            T("notif.rule_copied", new_name=new.name, src_name=src.name, new_id=new.id)
        )
        dup_gid = None
        for g in self._groups:
            if src.id in g.rule_ids:
                g.rule_ids.append(new.id)
                dup_gid = g.id
                break
        self._flush_save()
        self._selected_rule_id = new.id
        self._refresh_rule_list(dup_gid)
        if self._loop:
            self._loop.reload_rules()

    def _duplicate_rule_to_group(self, target_gid: str):
        """Copy the current rule to the specified group."""
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, T("dialog.notice"), T("status.stop_first_copy_rule"))
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
        new_rule.name = self._next_duplicate_name(src_rule.name)
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
        self._refresh_rule_list(target_group.id)
        self._status_bar.showMessage(
            T(
                "notif.rule_copied",
                new_name=new_rule.name,
                src_name=src_rule.name,
                new_id=new_rule.id,
            ),
            4000,
        )
        if self._loop:
            self._loop.reload_rules()

    def _move_rule_to_group(self, target_gid: str):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, T("dialog.notice"), T("status.stop_first_move_rule"))
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
            T("notif.rule_moved", rule_name=src_rule.name, group_name=target_group.name), 4000
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
        bg_ids = [r.id for r in self._rules if r.background]
        logging.info("[save] _schedule_save: rules=%d, background=%s", len(self._rules), bg_ids)
        self._save_timer.start()

    def _do_debounced_save(self) -> None:
        if not self._current_task:
            return
        task_path = str(_rule_mod.get_tasks_dir() / f"{self._current_task}.json")
        logging.info(
            "[_do_debounced_save] rules(%d)=%s groups=%s",
            len(self._rules),
            [r.name for r in self._rules],
            [(g.id, list(g.rule_ids)) for g in self._groups],
        )
        if self._loop:
            with self._loop._rules_lock:
                save_task(self._current_task, self._rules)
                save_groups(self._groups, task_path)
                self._loop._load_rules()
        else:
            save_task(self._current_task, self._rules)
            save_groups(self._groups, task_path)

    def _flush_save(self) -> None:
        bg_ids = [r.id for r in self._rules if r.background]
        logging.info("[save] _flush_save: rules=%d, background=%s", len(self._rules), bg_ids)
        self._save_timer.stop()
        self._do_debounced_save()
        _main_loop_mod.log_main(T("status.task_saved", count=len(self._rules)))

    def _save_current_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, T("dialog.notice"), T("status.stop_first_save"))
            return
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.name = self._edit_name.text()
        rule.enabled = self._edit_enabled.isChecked()
        rule.notes = self._edit_notes.toPlainText()
        rule.steps = self._step_list.get_steps()
        # 校驗 detect 步驟文字不可為空
        for i, s in enumerate(rule.steps):
            if s.type == "detect" and not s.params.get("text", "").strip():
                QMessageBox.warning(
                    self, T("dialog.save_failed"), T("notif.rule_validation_empty_text", idx=i + 1)
                )
                return
            if s.type == "click" and s.params.get("target", "") == "custom":
                x, y = s.params.get("x", 0), s.params.get("y", 0)
                if x == 0 and y == 0:
                    QMessageBox.warning(
                        self,
                        T("dialog.save_failed"),
                        T("notif.rule_validation_zero_click", idx=i + 1),
                    )
                    return
        valid_ids = {r.id for r in self._rules}
        warnings = []
        for i, s in enumerate(rule.steps):
            if s.type == "jump":
                tid = s.params.get("rule_id", "")
                if tid and tid not in valid_ids:
                    warnings.append(T("notif.rule_validation_missing_rule", idx=i + 1))
            elif s.type == "match_image" and not s.params.get("template", "").strip():
                warnings.append(T("notif.rule_validation_no_image", idx=i + 1))
            elif (
                s.type == "click"
                and s.params.get("target") == "click_text"
                and not s.params.get("text", "").strip()
            ):
                warnings.append(T("notif.rule_validation_empty_click", idx=i + 1))
            elif s.type == "notify" and not s.params.get("message", "").strip():
                warnings.append(T("notif.rule_validation_empty_notify", idx=i + 1))
            elif s.type == "compare" and not s.params.get("pattern", "").strip():
                warnings.append(T("notif.rule_validation_empty_regex", idx=i + 1))
        if warnings:
            self._status_bar.showMessage("⚠ " + "；".join(warnings), 8000)
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
            wr = get_window_rect(title)
            if wr:
                result = (result[0] - wr["x"], result[1] - wr["y"])
        self._edit_stack.setCurrentIndex(1)
        self._status_bar.showMessage(T("notif.coordinate_selected", x=result[0], y=result[1]))
        # Convert to ratio before storing
        if title and wr and wr["w"] > 0 and wr["h"] > 0:
            chrome = get_window_client_offset(title) or (0, 0)
            cx, cy = chrome
            client_w = wr["w"] - cx
            client_h = wr["h"] - cy
            if client_w > 0 and client_h > 0:
                result = (
                    max(0.0, (result[0] - cx) / client_w),
                    max(0.0, (result[1] - cy) / client_h),
                )
            else:
                result = (result[0] / wr["w"], result[1] / wr["h"])
        return result

    # === ROI selector ===
    def _open_roi_selector(self):
        return self._screenshot_ctrl.open_roi_selector()

    def _open_capture_region(self):
        return self._screenshot_ctrl.open_capture_region()

    # === Test rule (delegated to TestRunController) ===

    def _show_test_result(self, result: dict):
        self._edit_test_btn.setEnabled(True)
        self._edit_test_btn.setText(T("ui.test"))
        if "error" in result:
            QMessageBox.warning(self, T("dialog.test_result"), result["error"])
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
        dialog.setWindowTitle(T("dialog.test_result"))
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
        close_btn.setText(T("dialog.close"))
        btn_box.rejected.connect(dialog.close)
        layout.addWidget(btn_box)

        dialog.exec()

    # === OCR diagnostic ===
    def _switch_to_debug(self):
        title = self._window_combo.currentText()
        if not title:
            QMessageBox.warning(self, T("dialog.warning"), T("status.no_window"))
            return
        if self._loop is not None and self._loop.is_running:
            QMessageBox.warning(self, T("dialog.cannot_open"), T("status.stop_first_debug"))
            return
        self._debug_panel._window_title = title
        self._main_stack.setCurrentIndex(1)
        self._status_bar.showMessage(T("status.detecting", title=title))

    def _switch_to_rules(self):
        self._main_stack.setCurrentIndex(0)
        self._status_bar.showMessage(T("main.ready"))

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
                        "text": str(rule_data["target_text"]).strip()
                        or T("step_form.enter_text_placeholder"),
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
                Step(
                    type="wait",
                    params={"ms": 100},
                ),
            ],
        )
        self._rules.append(rule)
        _main_loop_mod.log_main(T("notif.rule_from_debug", name=rule.name, id=rule.id))
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
        self._refresh_rule_list(target_group.id if target_group else None)
        self._main_stack.setCurrentIndex(0)
        self._debug_btn.setText(T("main.ocr_debug"))
        self._show_rule_detail(rule)
        self._status_bar.showMessage(
            T("notif.rule_added_from_debug", text=rule_data["target_text"])
        )

    def _on_debug_step_requested(self, data: dict):
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.steps.append(
            Step(
                type="detect",
                params={
                    "text": str(data.get("target_text", "")).strip()
                    or T("step_form.enter_text_placeholder"),
                    "roi": data.get("roi", {"x": 0, "y": 0, "w": 0, "h": 0}),
                    "match_mode": "fuzzy",
                    "fuzzy_threshold": 0.8,
                },
            )
        )
        self._flush_save()
        self._step_list.set_steps(rule.steps)
        self._main_stack.setCurrentIndex(0)
        self._debug_btn.setText(T("main.ocr_debug"))
        _main_loop_mod.log_main(
            T(
                "notif.rule_from_debug_detect",
                name=rule.name,
                text=data.get("target_text", ""),
                id=rule.id,
            )
        )
        self._status_bar.showMessage(
            T("notif.step_added_from_debug", text=data.get("target_text", ""))
        )

    def _on_debug_template_requested(self, data: dict):
        import uuid

        rule = Rule(
            id=f"rule_{uuid.uuid4().hex[:8]}",
            name=data.get("name", T("step_form.template_rule_name")),
            enabled=True,
            steps=[
                Step(
                    type="match_image",
                    params={
                        "template_data": data.get("template_data", ""),
                        "roi": data.get("roi", {"x": 0, "y": 0, "w": 0, "h": 0}),
                        "threshold": 0.8,
                        "match_color": False,
                        "color_tolerance": 100,
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
                Step(
                    type="wait",
                    params={"ms": 100},
                ),
            ],
        )
        self._rules.append(rule)
        _main_loop_mod.log_main(T("notif.rule_from_debug_new_template", name=rule.name, id=rule.id))
        target_group = None
        item = self._rule_list.currentItem()
        if item:
            item_data = item.data(0, Qt.ItemDataRole.UserRole)
            if item_data:
                if item_data[0] == "group":
                    gid = item_data[1]
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
        self._refresh_rule_list(target_group.id if target_group else None)
        self._main_stack.setCurrentIndex(0)
        self._debug_btn.setText(T("main.ocr_debug"))
        self._show_rule_detail(rule)
        self._status_bar.showMessage(
            T("notif.template_rule_added_from_debug", name=data.get("name", ""))
        )

    def _on_debug_template_step_requested(self, data: dict):
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.steps.append(
            Step(
                type="match_image",
                params={
                    "template_data": data.get("template_data", ""),
                    "roi": data.get("roi", {"x": 0, "y": 0, "w": 0, "h": 0}),
                    "threshold": 0.8,
                    "match_color": False,
                    "color_tolerance": 100,
                },
            )
        )
        self._flush_save()
        self._step_list.set_steps(rule.steps)
        self._main_stack.setCurrentIndex(0)
        self._debug_btn.setText(T("main.ocr_debug"))
        _main_loop_mod.log_main(T("notif.rule_from_debug_template", name=rule.name, id=rule.id))
        self._status_bar.showMessage(
            T("notif.template_step_added_from_debug", name=data.get("name", ""))
        )

    # === Start / Pause ===
    def _show_group_selection_dialog(self) -> Optional[list[str]]:
        enabled = [g for g in self._groups if g.enabled]
        if len(enabled) <= 1:
            return [g.id for g in enabled] if enabled else []
        dialog = QDialog(self)
        dialog.setWindowTitle(T("dialog.group_selection"))
        dialog.setStyleSheet(
            "QDialog { background-color: #2b2b2b; }"
            "QLabel { color: #aaa; font-size: 12px; padding-bottom: 4px; }"
            "QCheckBox { color: #e0e0e0; spacing: 8px; }"
            "QCheckBox::indicator { width: 18px; height: 18px; }"
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        hint = QLabel(T("ui.select_group_hint", count=len(enabled)))
        layout.addWidget(hint)

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
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(T("main.start"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return [cb.property("gid") for cb in checks if cb.isChecked()]

    def nativeEvent(self, eventType, message):
        handled, result, hid = _hk_handle_native(eventType, message)
        if hid is not None:
            self._on_hotkey(hid)
        return handled, result

    def _on_hotkey(self, hid: int):
        if hid == 1:
            self._restore_window()
            self._toggle_start()

    def _toggle_start(self):
        if self._is_starting:
            return
        if self._window_lost:
            self._stop_loop()
        elif self._loop is not None and self._loop.is_running:
            if self._loop.is_paused:
                self._loop.resume()
                self._btn_toggle.setText(T("main.stop"))
            else:
                self._stop_loop()
        else:
            self._start_loop()

    def _start_loop(self):
        self._window_lost = False
        title = self._window_combo.currentText()
        if not title:
            QMessageBox.warning(self, T("dialog.warning"), T("status.no_window"))
            return
        if not self._rules:
            QMessageBox.warning(self, T("dialog.warning"), T("status.rule_list_empty"))
            return
        empty_steps = [r.name for r in self._rules if r.enabled and not r.steps]
        if empty_steps:
            names = "\n".join(f"  • {n}" for n in empty_steps[:5])
            suffix = (
                f"\n  {T('format.import_overflow', count=len(empty_steps) - 5)}"
                if len(empty_steps) > 5
                else ""
            )
            QMessageBox.warning(
                self,
                T("dialog.warning"),
                T("notif.steps_empty", names=names, suffix=suffix),
            )
            return
        group_ids = self._show_group_selection_dialog()
        if group_ids is None:
            return
        if not group_ids:
            QMessageBox.warning(self, T("dialog.warning"), T("status.at_least_one_group"))
            return
        self._is_starting = True
        activate_window(title)
        self._btn_toggle.setEnabled(False)
        self._btn_toggle.setText(T("status.initializing"))
        self._status_bar.showMessage(T("status.initializing_ocr"))
        task_path = str(_rule_mod.get_tasks_dir() / f"{self._current_task}.json")
        self._init_worker = InitWorker(
            str(task_path),
            title,
            self._signals,
            active_group_ids=group_ids,
            config_path=self._config_path,
        )
        self._init_worker.finished.connect(self._on_init_finished)
        self._init_worker.start()

    def _on_init_finished(self, success: bool, error_msg: str):
        self._btn_toggle.setEnabled(True)
        self._is_starting = False
        if success:
            self._loop = self._init_worker.loop
            self._loop.set_tool_hwnd(int(self.winId()))
            self._btn_toggle.setText(T("main.stop"))
            self._update_edit_enabled(False)
            self._status_bar.showMessage(
                T("status.detecting", title=self._window_combo.currentText())
            )
            self._status_timer.start(1000)
        else:
            QMessageBox.critical(
                self, T("dialog.init_failed"), T("dialog.loop_start_failed", error=error_msg)
            )
            self._btn_toggle.setText(T("main.start"))
            self._status_bar.showMessage(T("status.init_error", error_msg=error_msg))

    def _stop_loop(self):
        self._is_starting = False
        self._status_timer.stop()
        if self._loop:
            self._loop.stop()
            self._loop = None
        self._window_lost = False
        self._btn_toggle.setText(T("main.start"))
        self._update_edit_enabled(True)
        self._status_bar.showMessage(T("status.stopped"))
        self._update_rule_status()

    def _on_loop_finished(self, success: bool, msg: str):
        if self._loop is not None:
            self._stop_loop()

    def _update_edit_enabled(self, enabled: bool):
        self._rule_list.setEnabled(enabled)
        if enabled:
            self._rule_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self._rule_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        else:
            self._rule_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
            self._rule_list.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
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
        self._btn_toggle.setText(T("main.continue"))

    # === Emergency & OCR Health ===
    def _emergency_stop(self):
        self._status_timer.stop()
        if self._loop is None:
            return
        self._loop.emergency_stop()
        self._loop = None
        self._btn_toggle.setText(T("main.start"))
        self._update_edit_enabled(True)
        self._status_bar.showMessage(T("status.emergency_stop"))
        self._update_rule_status()

    # === Sponsor ===
    def _open_sponsor(self):
        import webbrowser

        from PyQt6.QtCore import QPoint

        menu = QMenu(self)
        ecpay_icon = self._make_circle_icon((0, 166, 81))
        paypal_icon = self._make_circle_icon((0, 112, 186))
        afdian_icon = self._make_circle_icon((231, 76, 60))
        menu.addAction(ecpay_icon, "ECPAY").triggered.connect(
            lambda: webbrowser.open("https://p.ecpay.com.tw/E0E3A")
        )
        menu.addAction(paypal_icon, "PayPal").triggered.connect(
            lambda: webbrowser.open("https://www.paypal.com/ncp/payment/9TGC4B3MYM9A6")
        )
        menu.addAction(afdian_icon, T("step_form.love_fadian")).triggered.connect(
            lambda: webbrowser.open("https://afdian.com/a/sid-1996")
        )
        menu.exec(self._sponsor_btn.mapToGlobal(QPoint(0, self._sponsor_btn.height())))

    def _open_log_dir(self):
        log_path = Path.home() / "AppData" / "Roaming" / "ocr-trigger-clicker" / "logs"
        os.startfile(log_path)

    # === About & Version ===
    def _show_about(self):
        QMessageBox.about(
            self,
            T("dialog.about"),
            f"<h3>OCR Trigger Clicker v{__version__}</h3>"
            + T("about.author", author=__author__)
            + T("about.project", url=__github__)
            + T("about.guide", url=_GUIDE_URL),
        )

    def _show_update_dialog(self, info, notes=None):
        dialog = _UpdateInfoDialog(info, notes, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._start_download(info)

    def _open_guide(self):
        import webbrowser

        webbrowser.open(_GUIDE_URL)

    def _open_task_share(self):
        import webbrowser

        webbrowser.open(
            "https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/"
            "%E4%BB%BB%E5%8B%99%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB"
        )

    def _check_version(self, force: bool = False):
        if self._updating:
            return
        if not force:
            config = self._load_config()
            if config.get("skip_update_check", False):
                return

        self._updating = True
        self._update_cancel = threading.Event()
        self._status_bar.showMessage(T("status.checking_update"))

        class _CheckWorker(QThread):
            result = pyqtSignal(object, object)  # (UpdateInfo | None, notes str | None)
            error = pyqtSignal(str, bool)  # (msg, forced)

            def __init__(self, forced):
                super().__init__()
                self.forced = forced

            def run(self):
                try:
                    info = _updater_mod.check_for_update(__version__)
                    notes = None
                    if info:
                        try:
                            notes = _updater_mod.fetch_release_notes(info.version)
                        except Exception:
                            notes = None
                    self.result.emit(info, notes)
                except Exception as e:
                    self.error.emit(str(e), self.forced)

        self._check_worker = _CheckWorker(forced=force)
        self._check_worker.result.connect(self._on_update_checked)
        self._check_worker.error.connect(self._on_update_error)
        self._check_worker.start()

    def _on_update_checked(self, info, notes=None):
        self._updating = False
        if info is None:
            self._status_bar.showMessage(T("status.latest_version"), 3000)
            return

        self._status_bar.showMessage(T("status.update_found", version=info.version), 0)
        self._pending_update_ver = info.version
        self._pending_update_info = info
        self._pending_update_notes = notes
        orig_press = self._status_bar.mousePressEvent

        def _on_click(e):
            self._status_bar.mousePressEvent = orig_press
            self._status_bar.showMessage("")
            self._show_update_dialog(info, notes)

        self._status_bar.mousePressEvent = _on_click
        self._show_update_dialog(info, notes)

    def _on_update_error(self, msg, forced=False):
        self._updating = False
        self._status_bar.showMessage("")
        if forced:
            QMessageBox.warning(
                self,
                T("dialog.update_failed"),
                T("update.check_failed", msg=msg),
            )
        else:
            logging.warning(T("log.update_failed_bg", msg=msg))

    def _start_download(self, info):
        if self._downloading:
            return
        self._downloading = True
        self._update_cancel = threading.Event()

        self._progress = QProgressDialog(T("update.downloading"), T("ui.cancel"), 0, 100, self)
        self._progress.setWindowTitle(T("update.download_version", version=info.version))
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)
        self._progress.canceled.connect(self._cancel_download)

        class _DownloadWorker(QThread):
            finished = pyqtSignal(object)
            error = pyqtSignal(str)
            progress = pyqtSignal(int, int)

            def run(self):
                try:
                    exe_path = _updater_mod.download_update(
                        info,
                        progress_cb=lambda d, t: self.progress.emit(d, t),
                        cancel_event=self.parent()._update_cancel
                        if hasattr(self.parent(), "_update_cancel")
                        else None,
                    )
                    self.finished.emit(exe_path)
                except Exception as e:
                    self.error.emit(str(e))

        self._dl_worker = _DownloadWorker()
        self._dl_worker.setParent(self)
        self._dl_worker.progress.connect(self._on_download_progress)
        self._dl_worker.finished.connect(self._on_download_finished)
        self._dl_worker.error.connect(self._on_download_error)
        self._dl_worker.start()

    def _on_download_progress(self, downloaded, total):
        if total > 0:
            pct = int(downloaded * 100 / total)
            self._progress.setValue(pct)
            self._progress.setLabelText(
                T(
                    "update.downloading_progress",
                    downloaded=downloaded // 1024,
                    total=total // 1024,
                    pct=pct,
                )
            )
        else:
            self._progress.setLabelText(
                T("update.downloading_unknown", downloaded=downloaded // 1024)
            )

    def _cancel_download(self):
        if self._update_cancel:
            self._update_cancel.set()
        self._progress.close()
        self._downloading = False
        self._status_bar.showMessage(T("dialog.download_cancelled"), 3000)

    def _on_download_finished(self, exe_path):
        self._progress.close()
        self._downloading = False

        config = self._load_config()
        config["just_updated"] = self._pending_update_ver
        self._save_config(config)

        btn = QMessageBox.question(
            self,
            T("dialog.update_complete"),
            T("update.apply_prompt", version=self._pending_update_ver),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if btn == QMessageBox.StandardButton.Yes:
            try:
                _updater_mod.apply_update(exe_path)
                QApplication.quit()
                os._exit(0)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    T("dialog.update_failed"),
                    T("update.apply_failed", error=e),
                )
        else:
            shutil.rmtree(exe_path.parent, ignore_errors=True)

    def _on_download_error(self, msg):
        self._progress.close()
        self._downloading = False
        QMessageBox.critical(
            self,
            T("dialog.download_failed"),
            T("update.download_error", msg=msg),
        )

    def _open_settings(self):
        SettingsDialog(self).exec()
        self._rule_config_ctrl._config_cache = None

    def closeEvent(self, event):
        self._rule_config_ctrl._config_cache = None
        config = self._load_config()
        behavior = config.get("close_behavior", "tray")
        show_confirm = config.get("show_close_confirm", True)

        if show_confirm:
            title = T("dialog.close_confirm.title")
            msg = (
                T("dialog.close_confirm.msg")
                if behavior == "quit"
                else T("dialog.close_confirm.tray_msg")
            )
            box = QMessageBox(self)
            box.setWindowTitle(title)
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(msg)
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            cb = QCheckBox(T("dialog.close_confirm.dont_show"))
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
                T("dialog.close_confirm.background_msg"),
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    def _restore_window(self):
        self.showNormal()
        self.activateWindow()

    def _quit_app(self):
        _hk_unregister(int(self.winId()))
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


class _UpdateInfoDialog(QDialog):
    def __init__(self, info, notes=None, parent=None):
        super().__init__(parent)
        self._info = info
        self.setWindowTitle(T("update.dialog.title", version=info.version))
        self.setMinimumSize(480, 380)
        self.resize(560, 500)

        layout = QVBoxLayout(self)

        header = QLabel(T("update.dialog.header", version=info.version))
        header.setWordWrap(True)
        header.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 8px;")
        layout.addWidget(header)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        if notes:
            browser.setMarkdown(notes)
        else:
            browser.setPlainText(T("update.dialog.no_notes"))
        layout.addWidget(browser)

        btn_layout = QHBoxLayout()
        auto_btn = QPushButton(T("update.dialog.auto"))
        auto_btn.clicked.connect(self.accept)

        manual_btn = QPushButton(T("update.dialog.manual"))
        manual_btn.clicked.connect(self._open_release)

        cancel_btn = QPushButton(T("ui.cancel"))
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(auto_btn)
        btn_layout.addWidget(manual_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _open_release(self):
        import webbrowser

        webbrowser.open(self._info.release_url)
        self.reject()


if __name__ == "__main__":
    import sys
    import traceback
    from pathlib import Path

    from _loader import load_sibling

    _log_cfg = load_sibling("logging_config", "core/00_logging_config.py")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _log_cfg.get_logger("gui")  # ensure root handler is set up
    _log_cfg.cleanup_stale_logs()

    # Read language preference before creating any GUI
    _app_cfg_dir = Path(os.environ.get("APPDATA", Path.home())) / "ocr-trigger-clicker"
    try:
        _app_cfg = json.loads((_app_cfg_dir / "config.json").read_text(encoding="utf-8"))
        set_language(_app_cfg.get("language", "zh_TW"))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    except Exception:
        with open(_log_cfg.get_log_dir() / "startup_error.log", "a", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        raise
