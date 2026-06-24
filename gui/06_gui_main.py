import json
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Optional

import numpy as np
from PyQt6.QtCore import QMimeData, QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
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
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
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


class _RuleTreeWidget(QTreeWidget):
    def dropEvent(self, event):
        if self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.OnItem:
            event.ignore()
            return
        super().dropEvent(event)


# ── Step list helpers ──

_STEP_TYPE_ICONS = {
    "detect": "🔍",
    "click": "🖱",
    "key": "⌨",
    "wait": "⏱",
    "wait_rule": "🔗",
    "collect_rounds": "🔄",
    "jump": "↩",
}

_STEP_TYPE_LABELS = {
    "detect": "偵測文字",
    "click": "點擊",
    "key": "按鍵",
    "wait": "等待",
    "wait_rule": "等待規則",
    "collect_rounds": "多輪比較",
    "jump": "跳轉規則",
}


def _resolve_rule_name(rule_id: str, rules_provider=None) -> str:
    if not rule_id or not rules_provider:
        return rule_id
    for r in rules_provider():
        if r.id == rule_id:
            return r.name
    return rule_id


def _step_summary(step, rules_provider=None) -> str:
    p = step.params
    t = step.type
    if t == "detect":
        text = p.get("text", "")
        roi = p.get("roi", {})
        zero_roi = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        roi_str = "全視窗" if zero_roi else f"({roi['x']},{roi['y']}){roi['w']}×{roi['h']}"
        cd = p.get("cooldown_ms", 0)
        parts = [f"「{text}」" if text else "未設定"]
        parts.append(roi_str)
        if cd:
            parts.append(f"冷卻{cd}ms")
        tm = p.get("trigger_mode", "once")
        if tm == "repeat":
            parts.append("[重複]")
        return " ".join(parts)
    if t == "click":
        target = p.get("target", "text_center")
        if target == "text_center":
            return "點擊文字中心"
        if target == "custom":
            return f"點擊 ({p.get('x', 0)},{p.get('y', 0)})"
        if target == "click_text":
            return f"點擊文字「{p.get('text', '')}」"
    if t == "key":
        return f"按鍵 {p.get('key', '')}"
    if t == "wait":
        return f"等待 {p.get('ms', 1000)}ms"
    if t == "wait_rule":
        name = _resolve_rule_name(p.get("rule_id", ""), rules_provider)
        return f"等待規則「{name}」"
    if t == "collect_rounds":
        rds = p.get("rounds", [])
        mcount = len(rds[0].get("metrics", [])) if rds else 0
        return f"{len(rds)}輪 {mcount}指標"
    if t == "jump":
        name = _resolve_rule_name(p.get("rule_id", ""), rules_provider)
        return f"跳轉規則「{name}」"
    return t


def _has_repeat_step(rule) -> bool:
    return any(s.type == "detect" and s.params.get("trigger_mode") == "repeat" for s in rule.steps)


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
        self._click_pick_callback: Optional[callable] = None
        self._rules_provider: Optional[callable] = None  # () -> list[Rule]
        self._rule_id: str = ""

    def set_roi_callback(self, cb):
        self._roi_callback = cb

    def set_click_pick_callback(self, cb):
        self._click_pick_callback = cb

    def set_rules_provider(self, cb):
        self._rules_provider = cb

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

    def _collapse(self):
        if self._expanded_form:
            self._save_expanded()
            self._layout.removeWidget(self._expanded_form)
            self._expanded_form.deleteLater()
            self._expanded_form = None
            self._expanded_idx = None

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

    # drag-drop reorder
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat("step/index"):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        src = int(e.mimeData().data("step/index").data().decode())
        self._collapse()
        y = e.position().y()
        # row height 32 + spacing 2 = 34 per row
        target = max(0, min(len(self._steps) - 1, int(y / 34)))
        if src == target:
            return
        self._steps.insert(target, self._steps.pop(src))
        self._rebuild()
        self.steps_changed.emit()

    def add_step(self, step_type: str):
        step = Step(type=step_type, params=deepcopy(_STEP_DEFAULTS.get(step_type, {})))
        self._steps.append(step)
        self._rebuild()
        self._toggle_expand(len(self._steps) - 1)
        self.steps_changed.emit()

    def _build_form(self, idx: int, step) -> Optional[QWidget]:
        t = step.type
        if t == "detect":
            return _DetectStepForm(self, step, idx, self._roi_callback)
        if t == "click":
            return _ClickStepForm(self, step, idx, self._click_pick_callback)
        if t == "key":
            return _KeyStepForm(self, step, idx)
        if t == "wait":
            return _WaitStepForm(self, step, idx)
        if t == "wait_rule":
            return _WaitRuleStepForm(self, step, idx, self._rules_provider, self._rule_id)
        if t == "collect_rounds":
            return _CollectRoundsStepForm(
                self, step, idx, self._roi_callback, self._click_pick_callback
            )
        if t == "jump":
            return _JumpStepForm(self, step, idx, self._rules_provider, self._rule_id)
        return None


# ── Step inline forms ──


class _DetectStepForm(QWidget):
    def __init__(self, parent_list, step, idx, roi_cb):
        super().__init__()
        self._list = parent_list
        self._step = step
        self._idx = idx
        self._roi_cb = roi_cb
        p = step.params
        form = QFormLayout(self)
        form.setContentsMargins(12, 6, 12, 6)

        self._text = QLineEdit(p.get("text", ""))
        form.addRow("目標文字:", self._text)

        roi = p.get("roi", {})
        zero = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        self._roi_label = QLabel(
            "全視窗" if zero else f"x={roi['x']} y={roi['y']} w={roi['w']} h={roi['h']}"
        )
        self._roi_btn = QPushButton("框選偵測區域")
        if roi_cb:
            self._roi_btn.clicked.connect(self._pick_roi)
        form.addRow("偵測區域:", self._roi_label)
        form.addRow("", self._roi_btn)

        self._match_mode = _NoWheelCombo()
        self._match_mode.addItem("包含關鍵字", "contains")
        self._match_mode.addItem("完全符合", "exact")
        self._match_mode.addItem("近似比對", "fuzzy")
        idx_mm = self._match_mode.findData(p.get("match_mode", "fuzzy"))
        if idx_mm >= 0:
            self._match_mode.setCurrentIndex(idx_mm)
        self._match_mode.currentIndexChanged.connect(self._on_match_mode_changed)
        form.addRow("比對模式:", self._match_mode)

        self._fuzzy_th = _NoWheelSpin()
        self._fuzzy_th.setRange(1, 100)
        self._fuzzy_th.setSuffix(" %")
        self._fuzzy_th.setValue(int(p.get("fuzzy_threshold", 0.8) * 100))
        self._fuzzy_th.setVisible(self._match_mode.currentData() == "fuzzy")
        form.addRow("精準度:", self._fuzzy_th)

        self._cooldown = _NoWheelSpin()
        self._cooldown.setRange(0, 60000)
        self._cooldown.setSuffix(" ms")
        self._cooldown.setValue(p.get("cooldown_ms", 2000))
        form.addRow("冷卻時間:", self._cooldown)

        self._mode = _NoWheelCombo()
        self._mode.addItem("觸發一次", "once")
        self._mode.addItem("重複觸發", "repeat")
        idx_m = self._mode.findData(p.get("trigger_mode", "once"))
        if idx_m >= 0:
            self._mode.setCurrentIndex(idx_m)
        form.addRow("觸發模式:", self._mode)

        self._max_triggers = _NoWheelSpin()
        self._max_triggers.setRange(-1, 9999)
        self._max_triggers.setSpecialValueText("無限")
        self._max_triggers.setValue(p.get("max_triggers", -1))
        form.addRow("最大觸發:", self._max_triggers)

    def _on_match_mode_changed(self, idx):
        self._fuzzy_th.setVisible(self._match_mode.itemData(idx) == "fuzzy")

    def _pick_roi(self):
        if self._roi_cb:
            result = self._roi_cb()
            if result:
                self._step.params["roi"] = result
                z = all(result.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
                self._roi_label.setText(
                    "全視窗"
                    if z
                    else f"x={result['x']} y={result['y']} w={result['w']} h={result['h']}"
                )
                self.save()
                self._list.steps_changed.emit()

    def save(self):
        self._step.params["text"] = self._text.text().strip()
        self._step.params["match_mode"] = self._match_mode.currentData()
        self._step.params["fuzzy_threshold"] = self._fuzzy_th.value() / 100.0
        self._step.params["cooldown_ms"] = self._cooldown.value()
        self._step.params["trigger_mode"] = self._mode.currentData()
        self._step.params["max_triggers"] = self._max_triggers.value()


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
        self._target.addItem("文字中心", "text_center")
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

        self._coord_label = QLabel(f"X: {p.get('x', 0)}, Y: {p.get('y', 0)}")
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

        self._button = _NoWheelCombo()
        self._button.addItem("左鍵", "left")
        self._button.addItem("右鍵", "right")
        b_idx = self._button.findData(p.get("button", "left"))
        if b_idx >= 0:
            self._button.setCurrentIndex(b_idx)
        form.addRow("滑鼠按鈕:", self._button)

        self._offset = _NoWheelSpin()
        self._offset.setRange(0, 100)
        self._offset.setSuffix(" px")
        self._offset.setValue(p.get("random_offset", 3))
        form.addRow("隨機抖動:", self._offset)

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
                self._coord_label.setText(f"X: {result[0]}, Y: {result[1]}")
                self._target.setCurrentIndex(self._target.findData("custom"))
                self.save()
                self._list.steps_changed.emit()

    def save(self):
        self._step.params["target"] = self._target.currentData()
        self._step.params["text"] = self._click_text.text().strip()
        self._step.params["button"] = self._button.currentData()
        self._step.params["random_offset"] = self._offset.value()


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

    def save(self):
        self._step.params["key"] = self._key.currentData() or self._key.currentText()


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
        self._ms.setValue(step.params.get("ms", 1000))
        form.addRow("毫秒:", self._ms)

    def save(self):
        self._step.params["ms"] = self._ms.value()


class _WaitRuleStepForm(QWidget):
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
        form.addRow("等待規則:", self._combo)

    def save(self):
        self._step.params["rule_id"] = self._combo.currentData() or ""


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


class _CollectRoundsStepForm(QWidget):
    def __init__(self, parent_list, step, idx, roi_cb, pick_cb):
        super().__init__()
        self._list = parent_list
        self._step = step
        self._idx = idx
        self._roi_cb = roi_cb
        self._pick_cb = pick_cb
        p = step.params
        self._rounds: list[dict] = p.get("rounds", [])
        self._round_widgets: list[dict] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)

        # Rounds section
        layout.addWidget(QLabel("<b>輪次列表</b>"))
        self._rounds_widget = QWidget()
        self._rounds_layout = QVBoxLayout(self._rounds_widget)
        self._rounds_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._rounds_widget)
        self._rebuild_rounds()

        add_round_btn = QPushButton("+ 新增輪次")
        add_round_btn.clicked.connect(self._add_round)
        layout.addWidget(add_round_btn)

        # Primary metric index (only shown when any round has ≥2 metrics)
        self._primary_idx_row = QWidget()
        _pil = QVBoxLayout(self._primary_idx_row)
        _pil.setContentsMargins(0, 0, 0, 0)
        self._primary_idx = _NoWheelSpin()
        self._primary_idx.setRange(0, 99)
        self._primary_idx.setValue(p.get("primary_metric_index", 0))
        _pil.addWidget(QLabel("最佳輪選取依據（第幾個指標，0=第一個）:"))
        _pil.addWidget(self._primary_idx)
        layout.addWidget(self._primary_idx_row)
        self._primary_idx_row.setVisible(self._max_metrics() >= 2)

        # Confirm action
        layout.addWidget(QLabel("<b>確認動作</b>"))
        ca = p.get("confirm_action", {})
        self._ca_type = _NoWheelCombo()
        self._ca_type.addItem("按鍵", "key")
        self._ca_type.addItem("點擊", "click")
        ca_idx = self._ca_type.findData(ca.get("type", "key"))
        if ca_idx >= 0:
            self._ca_type.setCurrentIndex(ca_idx)
        self._ca_type.currentIndexChanged.connect(self._on_ca_type)
        layout.addWidget(self._ca_type)

        self._ca_key = _make_key_combo()
        k = ca.get("key", "")
        k_idx = self._ca_key.findData(k)
        if k_idx >= 0:
            self._ca_key.setCurrentIndex(k_idx)
        self._ca_key.setVisible(ca.get("type", "key") == "key")
        layout.addWidget(self._ca_key)

        self._ca_coord_label = QLabel(f"X: {ca.get('x', 0)}, Y: {ca.get('y', 0)}")
        self._ca_coord_label.setVisible(ca.get("type", "") == "click")
        self._ca_pick_btn = QPushButton("選取確認座標")
        self._ca_pick_btn.setVisible(ca.get("type", "") == "click")
        if pick_cb:
            self._ca_pick_btn.clicked.connect(self._pick_ca_coord)
        layout.addWidget(self._ca_coord_label)
        layout.addWidget(self._ca_pick_btn)

        # On all fail
        layout.addWidget(QLabel("<b>全輪未達標</b>"))
        oaf = p.get("on_all_fail", {})
        self._oaf_type = _NoWheelCombo()
        self._oaf_type.addItem("跳轉規則", "jump")
        self._oaf_type.addItem("按鍵", "key")
        oaf_idx = self._oaf_type.findData(oaf.get("type", "jump"))
        if oaf_idx >= 0:
            self._oaf_type.setCurrentIndex(oaf_idx)
        self._oaf_type.currentIndexChanged.connect(self._on_oaf_type)
        layout.addWidget(self._oaf_type)

        self._oaf_rule_id = QLineEdit(oaf.get("rule_id", ""))
        self._oaf_rule_id.setVisible(oaf.get("type", "jump") == "jump")
        layout.addWidget(self._oaf_rule_id)

        self._oaf_key = _make_key_combo()
        ok = oaf.get("key", "")
        ok_idx = self._oaf_key.findData(ok)
        if ok_idx >= 0:
            self._oaf_key.setCurrentIndex(ok_idx)
        self._oaf_key.setVisible(oaf.get("type", "") == "key")
        layout.addWidget(self._oaf_key)

    def _max_metrics(self) -> int:
        return max((len(rd.get("metrics", [])) for rd in self._rounds), default=0)

    def _sync_widgets_to_rounds(self):
        """將目前 widget 的值 flush 回 self._rounds（不觸碰不存在的 index）。"""
        for ri, rw in enumerate(self._round_widgets):
            if ri < len(self._rounds):
                rd = self._rounds[ri]
                rd.setdefault("trigger_action", {})["type"] = rw["ta_type"].currentData()
                rd.setdefault("trigger_action", {})["key"] = (
                    rw["ta_key"].currentData() or rw["ta_key"].currentText()
                )
                rd.setdefault("result_action", {})["type"] = rw["ra_type"].currentData()
                rd.setdefault("result_action", {})["key"] = (
                    rw["ra_key"].currentData() or rw["ra_key"].currentText()
                )
                for mi, mw in enumerate(rw["metrics"]):
                    if mi < len(rd.get("metrics", [])):
                        rd["metrics"][mi]["direction"] = mw["direction"].currentData()
                        rd["metrics"][mi]["threshold"] = mw["threshold"].value()
                        rd["metrics"][mi]["pick"] = mw["pick"].currentData()
                        rd["metrics"][mi]["timeout_ms"] = mw["timeout"].value()

    def _rebuild_rounds(self):
        self._sync_widgets_to_rounds()
        for i in reversed(range(self._rounds_layout.count())):
            w = self._rounds_layout.itemAt(i).widget()
            if w:
                w.deleteLater()
        self._round_widgets.clear()
        for ri, rd in enumerate(self._rounds):
            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            rl = QVBoxLayout(frame)

            # Round header
            hdr = QHBoxLayout()
            hdr.addWidget(QLabel(f"<b>輪次 {ri + 1}</b>"))
            del_btn = QPushButton("✕")
            del_btn.setFixedWidth(24)
            del_btn.clicked.connect(lambda checked, i=ri: self._del_round(i))
            hdr.addWidget(del_btn)
            hdr.addStretch()
            rl.addLayout(hdr)

            # Trigger action
            ta = rd.get("trigger_action", {})
            ta_type = _NoWheelCombo()
            ta_type.addItem("按鍵", "key")
            ta_type.addItem("點擊", "click")
            tai = ta_type.findData(ta.get("type", "key"))
            if tai >= 0:
                ta_type.setCurrentIndex(tai)
            rl.addWidget(QLabel("觸發動作:"))
            rl.addWidget(ta_type)

            ta_key = _make_key_combo()
            tk = ta.get("key", "")
            tki = ta_key.findData(tk)
            if tki >= 0:
                ta_key.setCurrentIndex(tki)
            rl.addWidget(ta_key)

            # Result action
            ra = rd.get("result_action", {})
            ra_type = _NoWheelCombo()
            ra_type.addItem("按鍵", "key")
            ra_type.addItem("點擊", "click")
            rai = ra_type.findData(ra.get("type", "key"))
            if rai >= 0:
                ra_type.setCurrentIndex(rai)
            rl.addWidget(QLabel("結果動作:"))
            rl.addWidget(ra_type)

            ra_key = _make_key_combo()
            rk = ra.get("key", "")
            rki = ra_key.findData(rk)
            if rki >= 0:
                ra_key.setCurrentIndex(rki)
            rl.addWidget(ra_key)

            round_w = {
                "ta_type": ta_type,
                "ta_key": ta_key,
                "ra_type": ra_type,
                "ra_key": ra_key,
                "metrics": [],
            }

            # Metrics
            rl.addWidget(QLabel("指標:"))
            for mi, m in enumerate(rd.get("metrics", [])):
                mw = self._build_metric_widget(m, ri, mi, round_w)
                rl.addWidget(mw)

            add_m_btn = QPushButton("+ 新增指標")
            add_m_btn.clicked.connect(lambda checked, i=ri: self._add_metric(i))
            rl.addWidget(add_m_btn)

            self._round_widgets.append(round_w)
            self._rounds_layout.addWidget(frame)
        self._primary_idx_row.setVisible(self._max_metrics() >= 2)

    def _build_metric_widget(self, m: dict, ri: int, mi: int, round_store: dict) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(6, 4, 6, 4)

        roi = m.get("roi", {})
        z = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        roi_label = QLabel(
            "全視窗" if z else f"x={roi['x']} y={roi['y']} w={roi['w']} h={roi['h']}"
        )
        roi_btn = QPushButton("框選")
        if self._roi_cb:
            roi_btn.clicked.connect(lambda: self._pick_metric_roi(ri, mi))
        roi_row = QWidget()
        rl = QHBoxLayout(roi_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(roi_label)
        rl.addWidget(roi_btn)
        form.addRow("ROI:", roi_row)

        direction = _NoWheelCombo()
        direction.addItem("越高越好", "higher_better")
        direction.addItem("越低越好", "lower_better")
        di = direction.findData(m.get("direction", "higher_better"))
        if di >= 0:
            direction.setCurrentIndex(di)
        form.addRow("方向:", direction)

        threshold = _NoWheelDoubleSpin()
        threshold.setRange(-999999.0, 999999.0)
        threshold.setDecimals(2)
        threshold.setValue(m.get("threshold", 0.0))
        form.addRow("門檻:", threshold)

        pick = _NoWheelCombo()
        pick.addItem("第一個數字", "first")
        pick.addItem("最後一個數字", "last")
        pi = pick.findData(m.get("pick", "first"))
        if pi >= 0:
            pick.setCurrentIndex(pi)
        form.addRow("取數字:", pick)

        timeout = _NoWheelSpin()
        timeout.setRange(100, 30000)
        timeout.setSuffix(" ms")
        timeout.setValue(m.get("timeout_ms", 3000))
        form.addRow("超時:", timeout)

        round_store["metrics"].append(
            {
                "direction": direction,
                "threshold": threshold,
                "pick": pick,
                "timeout": timeout,
            }
        )

        del_m = QPushButton("✕ 刪除指標")
        del_m.clicked.connect(lambda: self._del_metric(ri, mi))
        form.addRow(del_m)

        form.addRow(QLabel("─" * 20))
        return w

    def _pick_metric_roi(self, ri: int, mi: int):
        if self._roi_cb:
            result = self._roi_cb()
            if result and ri < len(self._rounds) and mi < len(self._rounds[ri].get("metrics", [])):
                self._rounds[ri]["metrics"][mi]["roi"] = result
                self._rebuild_rounds()
                self._list.steps_changed.emit()

    def _add_round(self):
        self._rounds.append(
            {
                "trigger_action": {"type": "key", "key": ""},
                "metrics": [],
                "result_action": {"type": "key", "key": ""},
            }
        )
        self._rebuild_rounds()
        self._list.steps_changed.emit()

    def _del_round(self, ri: int):
        if ri < len(self._rounds):
            self._rounds.pop(ri)
            self._rebuild_rounds()
            self._list.steps_changed.emit()

    def _add_metric(self, ri: int):
        if ri < len(self._rounds):
            self._rounds[ri].setdefault("metrics", []).append(
                {
                    "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
                    "pick": "first",
                    "direction": "higher_better",
                    "threshold": 0.0,
                    "timeout_ms": 3000,
                }
            )
            self._rebuild_rounds()
            self._list.steps_changed.emit()
            self._primary_idx_row.setVisible(self._max_metrics() >= 2)

    def _del_metric(self, ri: int, mi: int):
        if ri < len(self._rounds) and mi < len(self._rounds[ri].get("metrics", [])):
            self._sync_widgets_to_rounds()  # flush 當前值，避免 pop 後 index 錯位覆蓋
            self._rounds[ri]["metrics"].pop(mi)
            self._rebuild_rounds()
            self._list.steps_changed.emit()
            self._primary_idx_row.setVisible(self._max_metrics() >= 2)

    def _on_ta_type(self, ri: int, idx: int):
        pass  # stored on save

    def _on_ca_type(self, idx: int):
        is_key = self._ca_type.currentData() == "key"
        self._ca_key.setVisible(is_key)
        self._ca_coord_label.setVisible(not is_key)
        self._ca_pick_btn.setVisible(not is_key)

    def _on_oaf_type(self, idx: int):
        is_jump = self._oaf_type.currentData() == "jump"
        self._oaf_rule_id.setVisible(is_jump)
        self._oaf_key.setVisible(not is_jump)

    def _pick_ca_coord(self):
        if self._pick_cb:
            result = self._pick_cb()
            if result:
                self._ca_coord_label.setText(f"X: {result[0]}, Y: {result[1]}")

    def save(self):
        rounds = []
        for ri, rw in enumerate(self._round_widgets):
            ta_key_str = rw["ta_key"].currentData() or rw["ta_key"].currentText()
            ra_key_str = rw["ra_key"].currentData() or rw["ra_key"].currentText()
            metrics = []
            for mi, mw in enumerate(rw["metrics"]):
                roi = (
                    self._rounds[ri]["metrics"][mi]["roi"]
                    if ri < len(self._rounds) and mi < len(self._rounds[ri].get("metrics", []))
                    else {"x": 0, "y": 0, "w": 0, "h": 0}
                )
                metrics.append(
                    {
                        "roi": roi,
                        "direction": mw["direction"].currentData(),
                        "threshold": mw["threshold"].value(),
                        "pick": mw["pick"].currentData(),
                        "timeout_ms": mw["timeout"].value(),
                    }
                )
            rounds.append(
                {
                    "trigger_action": {"type": rw["ta_type"].currentData(), "key": ta_key_str},
                    "result_action": {"type": rw["ra_type"].currentData(), "key": ra_key_str},
                    "metrics": metrics,
                }
            )
        self._step.params["rounds"] = rounds
        self._step.params["primary_metric_index"] = self._primary_idx.value()
        ca_type = self._ca_type.currentData()
        if ca_type == "key":
            self._step.params["confirm_action"] = {
                "type": "key",
                "key": self._ca_key.currentData() or self._ca_key.currentText(),
            }
        else:
            txt = (
                self._ca_coord_label.text()
                .replace("X: ", "")
                .replace(", Y:", "")
                .replace(" Y:", "")
            )
            parts = txt.split(" ")
            x = int(parts[0]) if parts else 0
            y = int(parts[1]) if len(parts) > 1 else 0
            self._step.params["confirm_action"] = {
                "type": "click",
                "x": x,
                "y": y,
                "button": "left",
            }
        oaf_type = self._oaf_type.currentData()
        if oaf_type == "jump":
            self._step.params["on_all_fail"] = {
                "type": "jump",
                "rule_id": self._oaf_rule_id.text().strip(),
            }
        else:
            self._step.params["on_all_fail"] = {
                "type": "key",
                "key": self._oaf_key.currentData() or self._oaf_key.currentText(),
            }


_ahk_mod = load_sibling("ahk_socket", "core/03_ahk_socket.py")
_main_loop_mod = load_sibling("main_loop", "core/05_main_loop.py")
MainLoop = _main_loop_mod.MainLoop

Rule = _main_loop_mod.Rule
list_windows = _main_loop_mod.list_windows
load_rules = _main_loop_mod.load_rules
save_rules = _main_loop_mod.save_rules
activate_window = _main_loop_mod.activate_window
get_window_rect = _main_loop_mod.get_window_rect
capture = _main_loop_mod.capture
recognize = _main_loop_mod.recognize
find_text = _main_loop_mod.find_text
poll_roi_value = _main_loop_mod.poll_roi_value
crop_roi = _main_loop_mod.crop_roi
capture_window_full = getattr(_main_loop_mod, "capture_window_full", lambda title: None)

_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
list_tasks = _rule_mod.list_tasks
load_task = _rule_mod.load_task
save_task = _rule_mod.save_task
delete_task = _rule_mod.delete_task
rename_task = _rule_mod.rename_task
export_task = _rule_mod.export_task
import_task = _rule_mod.import_task
preview_import_task = _rule_mod.preview_import_task
ImportPreview = _rule_mod.ImportPreview
migrate_old_rules = _rule_mod.migrate_old_rules
Step = _rule_mod.Step
_STEP_DEFAULTS = _rule_mod._STEP_DEFAULTS

_ocr_debug_mod = load_sibling("ocr_debug", "gui/09_ocr_debug.py")
OcrDebugPanel = _ocr_debug_mod.OcrDebugPanel

_ocr_mod = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_perf_mod = load_sibling("performance_monitor", "core/10_performance_monitor.py")

# ── Helpers ──


def _tasks_dir() -> str:
    mod = load_sibling("rule_engine", "core/04_rule_engine.py")
    return str(mod.get_tasks_dir())


class WorkerSignals(QObject):
    trigger_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)
    warning_signal = pyqtSignal(str)
    info_signal = pyqtSignal(str)
    window_lost_signal = pyqtSignal()
    emergency_signal = pyqtSignal()
    compare_round_signal = pyqtSignal(dict)
    test_done_signal = pyqtSignal(dict)


class InitWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(
        self,
        rules_path: str,
        window_title: str,
        signals: WorkerSignals,
        verbose: bool = True,
    ):
        super().__init__()
        self._rules_path = rules_path
        self._window_title = window_title
        self._signals = signals
        self._verbose = verbose
        self.loop: Optional[MainLoop] = None

    def run(self):
        try:
            loop = MainLoop(
                self._rules_path,
                self._window_title,
                verbose=self._verbose,
            )
            loop.on_trigger = lambda log: self._signals.trigger_signal.emit(log)
            loop.on_error = lambda msg: self._signals.error_signal.emit(msg)
            loop.on_warning = lambda msg: self._signals.warning_signal.emit(msg)
            loop.on_info = lambda msg: self._signals.info_signal.emit(msg)
            loop.on_window_lost = lambda: self._signals.window_lost_signal.emit()
            loop.on_emergency = lambda: self._signals.emergency_signal.emit()
            loop.on_compare_round = lambda d: self._signals.compare_round_signal.emit(d)
            loop.start()
            self.loop = loop
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


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

            self._setup_ui()
            self._debug_panel = OcrDebugPanel("", self)
            self._debug_panel.rule_requested.connect(self._on_debug_rule_requested)
            self._debug_panel.step_requested.connect(self._on_debug_step_requested)
            self._debug_page_layout.addWidget(self._debug_panel, 1)
            self._connect_signals()
            self._setup_shortcuts()

            _ocr_mod.set_ocr_health_callback(None)

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
                    if _ahk_mod.download_ahk():
                        self._status_bar.showMessage("AutoHotkey 下載完成")
                    else:
                        self._status_bar.showMessage(
                            "⚠ AutoHotkey 下載失敗，請手動安裝至 https://autohotkey.com"
                        )

            self._ahk_ready = _ahk_mod.init_ahk()
            if not self._ahk_ready:
                self._status_bar.showMessage("⚠ AHK 未啟動，點擊功能將無法使用")
        except Exception as e:
            QMessageBox.critical(self, "啟動失敗", f"初始化過程中發生錯誤：\n{e}")
            raise

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

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)

        # === Top toolbar ===
        toolbar = QHBoxLayout()

        # -- Window section --
        self._window_combo = _NoWheelCombo()
        self._window_combo.setMinimumWidth(250)
        self._window_combo.setPlaceholderText("← 點擊「重新整理」載入視窗")
        self._refresh_btn = QPushButton("重新整理")
        self._refresh_btn.setToolTip("重新掃描所有可見視窗")
        toolbar.addWidget(QLabel("視窗:"))
        toolbar.addWidget(self._window_combo)
        toolbar.addWidget(self._refresh_btn)

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

        toolbar.addSpacing(8)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        toolbar.addWidget(sep2)
        toolbar.addSpacing(8)

        # -- Action section --
        self._btn_toggle = QPushButton("啟動")
        self._btn_toggle.setMinimumWidth(80)
        self._btn_toggle.setToolTip("開始偵測所選視窗")
        self._debug_btn = QPushButton("🔍OCR 診斷")
        self._debug_btn.setToolTip("即時顯示視窗內所有辨識到的文字與位置")
        toolbar.addWidget(self._btn_toggle)
        toolbar.addWidget(self._debug_btn)
        toolbar.addStretch()
        self._about_btn = QPushButton("關於")
        self._about_btn.setToolTip(f"OCR Trigger Clicker v{__version__} — 作者: {__author__}")
        self._about_btn.clicked.connect(self._show_about)
        toolbar.addWidget(self._about_btn)
        self._guide_btn = QPushButton("新手教學")
        self._guide_btn.setToolTip("開啟 GitHub Pages 的互動式使用指引")
        self._guide_btn.clicked.connect(self._open_guide)
        toolbar.addWidget(self._guide_btn)
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
        self._rule_list.setToolTip("右鍵可複製規則")
        self._rule_list.customContextMenuRequested.connect(self._on_rule_context_menu)
        left_layout.addWidget(self._rule_list)

        self._rule_hint = QLabel("← 點擊「新增」建立第一條規則")
        self._rule_hint.setStyleSheet("color: #888; font-size: 11px;")
        left_layout.addWidget(self._rule_hint)

        rule_btn_bar = QHBoxLayout()
        self._add_rule_btn = QPushButton("新增")
        self._add_rule_btn.setToolTip("新增一條空白規則 (Ctrl+N)")
        self._del_rule_btn = QPushButton("刪除 (Del)")
        self._del_rule_btn.setToolTip("刪除目前選取的規則 (Del)")
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
            "框選偵測區域可限制 OCR 範圍"
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
        edit_layout.addLayout(name_row)

        edit_layout.addWidget(QLabel("步驟列表:"))

        self._step_list = _StepListWidget()
        self._step_list.set_roi_callback(self._open_roi_selector)
        self._step_list.set_click_pick_callback(self._on_pick_coord)
        self._step_list.set_rules_provider(lambda: list(self._rules))
        self._step_list.steps_changed.connect(self._on_steps_changed)
        edit_layout.addWidget(self._step_list, 1)

        # Add step dropdown
        add_dropdown = QPushButton("+ 新增步驟 ▾")
        add_dropdown.setToolTip("新增一個步驟至規則中")
        add_menu = QMenu(self)
        step_types = [
            ("detect", "🔍 偵測文字"),
            ("click", "🖱 點擊"),
            ("key", "⌨ 按鍵"),
            ("wait", "⏱ 等待"),
            ("wait_rule", "🔗 等待規則"),
            ("collect_rounds", "🔄 多輪比較"),
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
        self._refresh_btn.clicked.connect(self._refresh_window_list)
        self._window_combo.currentTextChanged.connect(self._on_window_changed)
        self._btn_toggle.clicked.connect(self._toggle_start)
        self._add_rule_btn.clicked.connect(self._add_rule)
        self._del_rule_btn.clicked.connect(self._delete_rule)
        self._rule_list.currentItemChanged.connect(self._on_rule_selected)
        self._rule_list.model().rowsMoved.connect(self._on_rules_reordered)
        self._edit_name.editingFinished.connect(self._on_name_changed)
        self._edit_test_btn.clicked.connect(self._on_test_rule)
        self._edit_enabled.stateChanged.connect(self._on_enabled_changed)
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
        self._signals.error_signal.connect(lambda msg: QMessageBox.warning(self, "引擎錯誤", msg))

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+N"), self, self._add_rule)
        QShortcut(QKeySequence("Delete"), self, self._delete_rule)

    # === Window list ===
    def _refresh_window_list(self):
        self._window_combo.clear()
        windows = list_windows()
        if not windows:
            self._window_combo.setPlaceholderText("⚠ 未發現任何視窗，請先開啟目標程式")
        else:
            self._window_combo.setPlaceholderText("← 請選擇目標視窗")
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
        if not name:
            self._rules = []
            self._current_task = ""
            self._refresh_rule_list()
            return
        self._current_task = name
        self._rules = load_task(name)
        config = self._load_config()
        config["last_task"] = name
        self._save_config(config)
        self._refresh_rule_list()
        if hasattr(self, "_debug_panel") and self._debug_panel is not None:
            self._debug_panel.clear_results()
        self._status_bar.showMessage(f"任務「{name}」— {len(self._rules)} 條規則")

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
        save_task(name, [])
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
        save_task(self._current_task, self._rules)
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

    @staticmethod
    def _get_wait_rule_ids(r) -> list[str]:
        return [s.params.get("rule_id", "") for s in r.steps if s.type == "wait_rule"]

    def _refresh_rule_list(self):
        self._rule_list.blockSignals(True)
        self._rule_list.clear()

        existing_ids = {r.id for r in self._rules}
        rule_map = {r.id: r for r in self._rules}

        child_map: dict[str, list[str]] = {}
        assigned: set[str] = set()
        for r in self._rules:
            first_dep = next(
                (
                    dep_id
                    for dep_id in self._get_wait_rule_ids(r)
                    if dep_id in existing_ids and dep_id != r.id
                ),
                None,
            )
            if first_dep:
                child_map.setdefault(first_dep, []).append(r.id)
                assigned.add(r.id)
        top_ids = [r.id for r in self._rules if r.id not in assigned]

        selected_item = None

        def _build(parent_id: str | None) -> list[QTreeWidgetItem]:
            items = []
            for rid in top_ids if parent_id is None else child_map.get(parent_id, []):
                r = rule_map[rid]
                item = QTreeWidgetItem()
                suffixes = []
                if any(s.type == "collect_rounds" for s in r.steps):
                    suffixes.append("🎯")
                if _has_repeat_step(r):
                    suffixes.append("🔁")
                suffix_str = " " + " ".join(suffixes) if suffixes else ""
                text = f"[{'✓' if r.enabled else '✗'}] {r.name}{suffix_str}"
                item.setText(0, text)
                item.setData(0, Qt.ItemDataRole.UserRole, r.id)
                item.setIcon(
                    0, self._make_circle_icon((0, 180, 0) if r.enabled else (160, 160, 160))
                )
                for child_item in _build(rid):
                    item.addChild(child_item)
                items.append(item)
                if r.id == self._selected_rule_id:
                    nonlocal selected_item
                    selected_item = item
            return items

        for item in _build(None):
            self._rule_list.addTopLevelItem(item)

        self._rule_list.expandAll()
        self._rule_list.blockSignals(False)
        self._rule_hint.setVisible(len(self._rules) == 0)

        if selected_item:
            self._rule_list.setCurrentItem(selected_item)
        elif self._rule_list.topLevelItemCount() > 0:
            self._rule_list.setCurrentItem(self._rule_list.topLevelItem(0))
        else:
            self._selected_rule_id = None
            self._show_rule_detail(None)

    def _update_rule_status(self):
        if not self._loop or not self._loop.is_running:
            self._refresh_rule_list()
            return
        statuses = self._loop.get_rules_status()
        status_map = {s["id"]: s for s in statuses}
        now = time.monotonic()

        def _set_text(item):
            sid = item.data(0, Qt.ItemDataRole.UserRole)
            st = status_map.get(sid)
            if st is None:
                return
            suffix = ""
            disabled_reason = not st["enabled"] and (
                st["auto_disabled"]
                or (st["max_triggers"] > 0 and st["trigger_count"] >= st["max_triggers"])
            )
            if not st["enabled"] and disabled_reason:
                icon_color = (200, 0, 0)
                suffix = " ❌"
            elif not st["enabled"]:
                icon_color = (160, 160, 160)
                suffix = ""
            elif st["trigger_count"] > 0:
                elapsed_ms = (now - st["last_trigger_time"]) * 1000
                if elapsed_ms < st["cooldown_ms"]:
                    icon_color = (200, 180, 0)
                    suffix = " ⏳"
                elif elapsed_ms < 2000:
                    icon_color = (0, 180, 0)
                    suffix = " ✅"
                else:
                    icon_color = (0, 180, 0)
                    suffix = ""
            else:
                icon_color = (0, 180, 0)
                suffix = ""
            enabled = st["enabled"]
            rule = next((r for r in self._rules if r.id == sid), None)
            suffixes = []
            if rule:
                if any(s.type == "collect_rounds" for s in rule.steps):
                    suffixes.append("🎯")
                if _has_repeat_step(rule):
                    suffixes.append("🔁")
            suffix_str = " " + " ".join(suffixes) if suffixes else ""
            base = f"[{'✓' if enabled else '✗'}] {st['name']}{suffix_str}"
            new_text = base + suffix
            if item.text(0) != new_text:
                item.setText(0, new_text)
            item.setIcon(0, self._make_circle_icon(icon_color))

        def _walk(item):
            _set_text(item)
            for j in range(item.childCount()):
                _walk(item.child(j))

        try:
            for i in range(self._rule_list.topLevelItemCount()):
                _walk(self._rule_list.topLevelItem(i))
        finally:
            pass

    def _get_current_rule(self) -> Optional[Rule]:
        for r in self._rules:
            if r.id == self._selected_rule_id:
                return r
        return None

    def _on_rule_selected(self, current: QTreeWidgetItem, previous: QTreeWidgetItem):
        if previous:
            prev_id = previous.data(0, Qt.ItemDataRole.UserRole)
            if prev_id:
                prev_rule = next((r for r in self._rules if r.id == prev_id), None)
                if prev_rule:
                    prev_rule.name = self._edit_name.text()
                    prev_rule.enabled = self._edit_enabled.isChecked()
                    prev_rule.steps = self._step_list.get_steps()
                    self._flush_save()
                    suffixes = []
                    if any(s.type == "collect_rounds" for s in prev_rule.steps):
                        suffixes.append("🎯")
                    if _has_repeat_step(prev_rule):
                        suffixes.append("🔁")
                    suffix_str = " " + " ".join(suffixes) if suffixes else ""
                    previous.setText(
                        0, f"[{'✓' if prev_rule.enabled else '✗'}] {prev_rule.name}{suffix_str}"
                    )
                    if self._loop:
                        self._loop.reload_rules()
        if current:
            rule_id = current.data(0, Qt.ItemDataRole.UserRole)
            rule = next((r for r in self._rules if r.id == rule_id), None)
            if rule:
                self._selected_rule_id = rule.id
                self._show_rule_detail(rule)
                return
        self._selected_rule_id = None
        self._show_rule_detail(None)

    def _on_rules_reordered(self):
        new_order = []

        def _walk(item):
            rid = item.data(0, Qt.ItemDataRole.UserRole)
            rule = next((r for r in self._rules if r.id == rid), None)
            if rule:
                new_order.append(rule)
            for j in range(item.childCount()):
                _walk(item.child(j))

        for i in range(self._rule_list.topLevelItemCount()):
            _walk(self._rule_list.topLevelItem(i))
        self._rules = new_order
        save_task(self._current_task, self._rules)
        if self._loop:
            self._loop.reload_rules()

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
        self._edit_enabled.setChecked(rule.enabled)
        self._step_list.set_rule_id(rule.id)
        self._step_list.set_steps(rule.steps)

    def _on_enabled_changed(self, state):
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.enabled = state == 2
        save_task(self._current_task, self._rules)
        item = self._rule_list.currentItem()
        if item:
            c_suffix = " [C]" if any(s.type == "collect_rounds" for s in rule.steps) else ""
            text = f"[{'✓' if rule.enabled else '✗'}] {rule.name}{c_suffix}"
            item.setText(0, text)
        if self._loop:
            self._loop.reload_rules()

    def _add_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再新增規則")
            return
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
                        "cooldown_ms": 2000,
                        "trigger_mode": "once",
                        "max_triggers": -1,
                    },
                )
            ],
        )
        self._rules.append(rule)
        save_task(self._current_task, self._rules)
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

    def _on_steps_changed(self):
        self._save_current_rule()
        self._refresh_rule_list()

    def _delete_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再刪除規則")
            return
        rule = self._get_current_rule()
        if rule is None:
            return
        # 檢查是否有其他規則參照此規則
        refs = [
            r.name
            for r in self._rules
            if r.id != rule.id
            and any(
                s.params.get("rule_id", "") == rule.id
                for s in r.steps
                if s.type in ("jump", "wait_rule")
            )
        ]
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
        # 自動清理其他規則指向被刪規則的參照
        for r in self._rules:
            for s in r.steps:
                if s.type in ("jump", "wait_rule") and s.params.get("rule_id", "") == rule.id:
                    s.params["rule_id"] = ""
        save_task(self._current_task, self._rules)
        self._refresh_rule_list()
        cur = self._get_current_rule()
        if cur is not None:
            self._step_list.set_steps(cur.steps)
        if self._loop:
            self._loop.reload_rules()

    def _on_rule_context_menu(self, pos):
        item = self._rule_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        act = menu.addAction("複製規則")
        act.triggered.connect(self._duplicate_rule)
        menu.exec(self._rule_list.viewport().mapToGlobal(pos))

    def _duplicate_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再複製規則")
            return
        src = self._get_current_rule()
        if src is None:
            return
        import uuid

        new = deepcopy(src)
        new.id = f"rule_{uuid.uuid4().hex[:8]}"
        new.name = f"{src.name} (副本)"
        new.trigger_count = 0
        new.last_trigger_time = 0.0
        idx = self._rules.index(src) + 1
        self._rules.insert(idx, new)
        save_task(self._current_task, self._rules)
        self._selected_rule_id = new.id
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()

    def _on_name_changed(self):
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.name = self._edit_name.text()
        item = self._rule_list.currentItem()
        if item:
            c_suffix = " [C]" if any(s.type == "collect_rounds" for s in rule.steps) else ""
            item.setText(0, f"[{'✓' if rule.enabled else '✗'}] {rule.name}{c_suffix}")

    def _schedule_save(self):
        self._save_timer.start()

    def _do_debounced_save(self):
        if not self._current_task:
            return
        save_task(self._current_task, self._rules)
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
        # 檢查 jump/wait_rule 參照的規則是否存在
        valid_ids = {r.id for r in self._rules}
        for s in rule.steps:
            if s.type in ("jump", "wait_rule"):
                tid = s.params.get("rule_id", "")
                if tid and tid not in valid_ids:
                    self._status_bar.showMessage(f"⚠ 步驟「{s.type}」參照的規則已不存在", 5000)
        self._schedule_save()
        item = self._rule_list.currentItem()
        if item:
            c_suffix = " [C]" if any(s.type == "collect_rounds" for s in rule.steps) else ""
            item.setText(0, f"[{'✓' if rule.enabled else '✗'}] {rule.name}{c_suffix}")

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
        return result

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
        if img is None:
            img = capture_window_full(title)
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
        result: dict = {}
        try:
            result = self._test_first_detect_step(rule, img)
        except Exception as e:
            result = {"error": f"測試異常：{e}"}
        self._signals.test_done_signal.emit(result)

    def _test_first_detect_step(self, rule: Rule, img: np.ndarray) -> dict:
        detect = next((s for s in rule.steps if s.type == "detect"), None)
        if detect is None:
            return {"error": "規則中無偵測步驟，請新增一個 detect 步驟"}
        p = detect.params
        text = p.get("text", "").strip()
        if not text:
            return {"error": "偵測步驟的目標文字為空白"}
        roi = p.get("roi", {})
        if any(roi.get(k, 0) != 0 for k in ("x", "y", "w", "h")):
            roi_img = crop_roi(img, roi)
            if roi_img is None:
                return {"error": "裁切區域無效"}
        else:
            roi_img = img
        results = recognize(roi_img, preprocess=False, max_side_len=0, min_confidence=0.25)
        match_mode = p.get("match_mode", "fuzzy")
        threshold = p.get("fuzzy_threshold", 0.8)
        matches = find_text(results, text, match_mode, threshold)
        if matches:
            m = matches[0]
            return {
                "hit": True,
                "matched_text": m.text,
                "confidence": m.confidence,
                "click": (int(m.x + m.w / 2), int(m.y + m.h / 2)),
            }
        texts = [r.text for r in results[:5]]
        return {"hit": False, "ocr_texts": texts}

    def _show_test_result(self, result: dict):
        self._edit_test_btn.setEnabled(True)
        self._edit_test_btn.setText("▶ 測試")
        if "error" in result:
            QMessageBox.warning(self, "測試結果", result["error"])
            return
        r = result
        if r["hit"]:
            msg = (
                f"✅ 命中「{r['matched_text']}」"
                f"\n信心: {r['confidence']:.2f}"
                f"\n座標: ({r['click'][0]}, {r['click'][1]})"
            )
        else:
            texts = r.get("ocr_texts", [])
            msg = "❌ 未命中目標文字"
            if texts:
                msg += "\n\n辨識到的文字:\n" + "\n".join(texts[:5])
        QMessageBox.information(self, "測試結果", msg)

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
                        "cooldown_ms": int(rule_data.get("cooldown", 1.0) * 1000),
                        "trigger_mode": rule_data.get("trigger_mode", "once"),
                        "max_triggers": -1,
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
        save_task(self._current_task, self._rules)
        self._selected_rule_id = rule.id
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()
        self._main_stack.setCurrentIndex(0)
        self._debug_btn.setText("OCR 診斷")
        self._show_rule_detail(rule)
        self._status_bar.showMessage(
            f"已從 OCR 診斷新增規則：「{rule_data['target_text']}」"
            f"  觸發模式: {rule_data.get('trigger_mode', 'once')}"
        )

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
                    "cooldown_ms": 2000,
                    "trigger_mode": "once",
                    "max_triggers": -1,
                },
            )
        )
        save_task(self._current_task, self._rules)
        self._step_list.set_steps(rule.steps)
        self._status_bar.showMessage(f"已加入偵測步驟：「{data.get('target_text', '')}」")

    # === Start / Pause ===
    def _toggle_start_stop(self):
        if self._loop is not None and self._loop.is_running:
            self._stop_loop()
        else:
            self._start_loop()

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
        activate_window(title)
        self._btn_toggle.setEnabled(False)
        self._btn_toggle.setText("初始化中...")
        self._status_bar.showMessage("正在初始化 OCR 引擎…")
        task_path = str(Path(_tasks_dir()) / f"{self._current_task}.json")
        self._init_worker = InitWorker(str(task_path), title, self._signals)
        self._init_worker.finished.connect(self._on_init_finished)
        self._init_worker.start()

    def _on_init_finished(self, success: bool, error_msg: str):
        self._btn_toggle.setEnabled(True)
        if success:
            self._loop = self._init_worker.loop
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
        self._btn_toggle.setText("啟動")
        self._update_edit_enabled(True)
        self._status_bar.showMessage("已停止")
        self._update_rule_status()

    def _update_edit_enabled(self, enabled: bool):
        self._rule_list.setEnabled(enabled)
        self._add_rule_btn.setEnabled(enabled)
        self._del_rule_btn.setEnabled(enabled)
        self._refresh_btn.setEnabled(enabled)
        self._debug_btn.setEnabled(enabled)

        self._task_new_btn.setEnabled(enabled)
        self._task_del_btn.setEnabled(enabled)
        self._task_import_btn.setEnabled(enabled)
        self._task_export_btn.setEnabled(enabled)
        self._edit_test_btn.setEnabled(enabled)
        self._edit_name.setEnabled(enabled)
        self._edit_enabled.setEnabled(enabled)
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

    # === Close ===
    def closeEvent(self, event):
        self._flush_save()
        self._status_timer.stop()
        if self._loop:
            self._loop.stop()
        self._perf_timer.stop()
        _ahk_mod.shutdown()
        event.accept()


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
