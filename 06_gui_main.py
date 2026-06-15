import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from _loader import load_sibling

_here = Path(__file__).parent


class _NoWheelCombo(QComboBox):
    def wheelEvent(self, e):
        e.ignore()


class _NoWheelSpin(QSpinBox):
    def wheelEvent(self, e):
        e.ignore()


_ahk_mod = load_sibling("ahk_socket", "03_ahk_socket.py")
_main_loop_mod = load_sibling("main_loop", "05_main_loop.py")
MainLoop = _main_loop_mod.MainLoop
TriggerLog = _main_loop_mod.TriggerLog
Rule = _main_loop_mod.Rule
list_windows = _main_loop_mod.list_windows
load_rules = _main_loop_mod.load_rules
save_rules = _main_loop_mod.save_rules


class WorkerSignals(QObject):
    trigger_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)
    window_lost_signal = pyqtSignal()


class InitWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, rules_path: str, window_title: str, signals: WorkerSignals):
        super().__init__()
        self._rules_path = rules_path
        self._window_title = window_title
        self._signals = signals
        self.loop: Optional[MainLoop] = None

    def run(self):
        try:
            loop = MainLoop(self._rules_path, self._window_title)
            loop.on_trigger = lambda log: self._signals.trigger_signal.emit(log)
            loop.on_error = lambda msg: self._signals.error_signal.emit(msg)
            loop.on_window_lost = lambda: self._signals.window_lost_signal.emit()
            loop.start()
            self.loop = loop
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OCR Trigger Clicker")
        self.resize(900, 650)

        try:
            from build import get_data_path

            self._rules_path = get_data_path("rules.json")
            self._config_path = get_data_path("config.json")
        except ImportError:
            here = Path(__file__).parent
            self._rules_path = str(here / "rules.json")
            self._config_path = str(here / "config.json")
        self._ensure_rules()

        self._signals = WorkerSignals()
        self._loop: Optional[MainLoop] = None
        self._selected_rule_id: Optional[str] = None
        self._window_lost = False
        self._debug_window = None

        self._setup_ui()
        self._connect_signals()
        self._setup_shortcuts()

        self._refresh_window_list()
        self._restore_last_window()
        self._refresh_rule_list()

        self._ahk_ready = _ahk_mod.init_ahk()
        if not self._ahk_ready:
            self._status_bar.showMessage("⚠ AHK 未啟動，點擊功能將無法使用")

    def _ensure_rules(self):
        if not Path(self._rules_path).exists():
            save_rules([], self._rules_path)

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

    def _restore_last_window(self):
        config = self._load_config()
        last = config.get("last_window", "")
        if not last:
            return
        idx = self._window_combo.findText(last)
        if idx >= 0:
            self._window_combo.setCurrentIndex(idx)
        else:
            self._window_combo.setPlaceholderText(f"⚠ 上次的視窗「{last}」已不存在，請重新選擇")
            self._status_bar.showMessage(f"⚠ 上次的視窗「{last}」已不存在")

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)

        # === Top toolbar ===
        toolbar = QHBoxLayout()
        self._window_combo = _NoWheelCombo()
        self._window_combo.setMinimumWidth(250)
        self._window_combo.setPlaceholderText("← 點擊「重新整理」載入視窗")
        self._refresh_btn = QPushButton("重新整理")
        self._refresh_btn.setToolTip("重新掃描所有可見視窗")
        self._btn_toggle = QPushButton("啟動")
        self._btn_toggle.setMinimumWidth(80)
        self._btn_toggle.setToolTip("開始偵測所選視窗（按 F9 暫停／繼續）")
        self._debug_btn = QPushButton("OCR 診斷")
        self._debug_btn.setToolTip("即時顯示視窗內所有辨識到的文字與位置")
        self._import_btn = QPushButton("匯入規則")
        self._import_btn.setToolTip("從 JSON 檔案載入規則")
        self._export_btn = QPushButton("匯出規則")
        self._export_btn.setToolTip("將規則備份為 JSON 檔案")

        toolbar.addWidget(QLabel("目標視窗:"))
        toolbar.addWidget(self._window_combo)
        toolbar.addWidget(self._refresh_btn)
        toolbar.addSpacing(12)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        toolbar.addWidget(sep)
        toolbar.addWidget(self._btn_toggle)
        toolbar.addWidget(self._debug_btn)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        toolbar.addWidget(sep2)
        toolbar.addWidget(self._import_btn)
        toolbar.addWidget(self._export_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # === Middle: rule list + edit panel ===
        mid = QHBoxLayout()
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("規則列表"))

        self._rule_list = QListWidget()
        self._rule_list.setMinimumWidth(180)
        left_layout.addWidget(self._rule_list)

        self._rule_hint = QLabel("← 點擊「新增」建立第一條規則")
        self._rule_hint.setStyleSheet("color: #888; font-size: 11px;")
        left_layout.addWidget(self._rule_hint)

        rule_btn_bar = QHBoxLayout()
        self._add_rule_btn = QPushButton("新增")
        self._add_rule_btn.setToolTip("新增一條空白規則")
        self._del_rule_btn = QPushButton("刪除")
        self._del_rule_btn.setToolTip("刪除目前選取的規則")
        rule_btn_bar.addWidget(self._add_rule_btn)
        rule_btn_bar.addWidget(self._del_rule_btn)
        left_layout.addLayout(rule_btn_bar)

        mid.addWidget(left_widget, 1)

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
            "按 F9 可暫停／繼續\n"
            "框選偵測區域可限制 OCR 範圍"
        )
        guide_label.setStyleSheet("color: #666; font-size: 13px;")
        guide_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        guide_layout.addWidget(guide_label)
        self._edit_stack.addWidget(guide_page)

        # -- Page 1: edit form --
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._edit_panel = QWidget()
        self._edit_form = QFormLayout(self._edit_panel)

        self._edit_name = QLineEdit()
        self._edit_name.setToolTip("觸發規則的名稱，便於辨識")
        self._edit_target = QLineEdit()
        self._edit_target.setToolTip("OCR 比對的目標文字，支援模糊比對")
        self._edit_enabled = QCheckBox()
        self._edit_enabled.setToolTip("啟用或停用此規則")
        self._edit_roi_label = QLabel("全視窗")
        self._edit_roi_btn = QPushButton("框選偵測區域")
        self._edit_roi_btn.setToolTip("用滑鼠拖曳選取螢幕上的偵測範圍")
        self._edit_cooldown = _NoWheelSpin()
        self._edit_cooldown.setRange(0, 60000)
        self._edit_cooldown.setSuffix(" ms")
        self._edit_cooldown.setToolTip("觸發後冷卻時間，期間內不重複觸發")
        self._edit_trigger_mode = _NoWheelCombo()
        self._edit_trigger_mode.addItems(["once", "repeat"])
        self._edit_trigger_mode.setToolTip("once：觸發一次後停用 ｜ repeat：持續觸發")
        self._edit_click_button = _NoWheelCombo()
        self._edit_click_button.addItems(["left", "right"])
        self._edit_click_button.setToolTip("點擊使用的滑鼠按鍵")
        self._edit_click_position = _NoWheelCombo()
        self._edit_click_position.addItems(["text_center", "custom"])
        self._edit_click_position.setToolTip("text_center：點擊文字中心 ｜ custom：自訂座標")
        self._edit_custom_x = _NoWheelSpin()
        self._edit_custom_x.setRange(0, 99999)
        self._edit_custom_x.setToolTip("自訂點擊的 X 座標（相對視窗左上角）")
        self._edit_custom_y = _NoWheelSpin()
        self._edit_custom_y.setRange(0, 99999)
        self._edit_custom_y.setToolTip("自訂點擊的 Y 座標（相對視窗左上角）")
        self._edit_fuzzy = QCheckBox()
        self._edit_fuzzy.setToolTip("啟用模糊比對，可容許文字拼寫差異")
        self._edit_fuzzy_threshold = _NoWheelSpin()
        self._edit_fuzzy_threshold.setRange(1, 100)
        self._edit_fuzzy_threshold.setSuffix(" %")
        self._edit_fuzzy_threshold.setValue(80)
        self._edit_fuzzy_threshold.setToolTip("模糊比對的相似度門檻（越高越嚴格）")
        self._edit_max_triggers = _NoWheelSpin()
        self._edit_max_triggers.setRange(-1, 9999)
        self._edit_max_triggers.setSpecialValueText("無限")
        self._edit_max_triggers.setValue(-1)
        self._edit_max_triggers.setToolTip("此規則最多觸發次數（-1 = 無限制）")
        self._edit_random_offset = _NoWheelSpin()
        self._edit_random_offset.setRange(0, 100)
        self._edit_random_offset.setSuffix(" px")
        self._edit_random_offset.setValue(3)
        self._edit_random_offset.setToolTip("點擊位置隨機偏移像素，模擬真人點擊")

        self._edit_save_btn = QPushButton("儲存規則")
        self._edit_save_btn.setEnabled(False)
        self._edit_save_btn.setToolTip("儲存目前編輯的規則")

        # Build form
        self._edit_form.addRow("啟用:", self._edit_enabled)
        self._edit_form.addRow("名稱:", self._edit_name)
        self._edit_form.addRow("目標文字:", self._edit_target)
        self._edit_form.addRow("偵測區域:", self._edit_roi_label)
        self._edit_form.addRow("", self._edit_roi_btn)
        self._edit_form.addRow("冷卻時間:", self._edit_cooldown)
        self._edit_form.addRow("觸發模式:", self._edit_trigger_mode)
        self._edit_form.addRow("滑鼠按鈕:", self._edit_click_button)
        self._edit_form.addRow("點擊位置:", self._edit_click_position)
        self._edit_form.addRow("自訂 X:", self._edit_custom_x)
        self._edit_form.addRow("自訂 Y:", self._edit_custom_y)
        self._edit_form.addRow("模糊比對:", self._edit_fuzzy)
        self._edit_form.addRow("模糊閾值:", self._edit_fuzzy_threshold)
        self._edit_form.addRow("最大觸發:", self._edit_max_triggers)
        self._edit_form.addRow("隨機抖動:", self._edit_random_offset)
        self._edit_form.addRow(self._edit_save_btn)

        scroll.setWidget(self._edit_panel)
        self._edit_stack.addWidget(scroll)
        self._edit_stack.setCurrentIndex(0)
        mid.addWidget(self._edit_stack, 2)
        layout.addLayout(mid)

        # === Bottom: log area ===
        log_mod = load_sibling("gui_log", "08_gui_log.py")
        self._log_widget = log_mod.LogWidget()
        layout.addWidget(self._log_widget)

        # === Status bar ===
        self._status_bar = QStatusBar()
        self._status_bar.showMessage("就緒 — 請選擇視窗並新增規則")
        self.setStatusBar(self._status_bar)

    def _connect_signals(self):
        self._refresh_btn.clicked.connect(self._refresh_window_list)
        self._window_combo.currentTextChanged.connect(self._on_window_changed)
        self._btn_toggle.clicked.connect(self._toggle_start)
        self._import_btn.clicked.connect(self._import_rules)
        self._export_btn.clicked.connect(self._export_rules)
        self._add_rule_btn.clicked.connect(self._add_rule)
        self._del_rule_btn.clicked.connect(self._delete_rule)
        self._rule_list.currentRowChanged.connect(self._on_rule_selected)
        self._edit_save_btn.clicked.connect(self._save_current_rule)
        self._edit_roi_btn.clicked.connect(self._open_roi_selector)
        self._debug_btn.clicked.connect(self._open_ocr_debug)

        self._edit_click_position.currentTextChanged.connect(self._on_click_position_changed)
        self._edit_fuzzy.stateChanged.connect(self._on_fuzzy_changed)

        self._signals.trigger_signal.connect(self._on_trigger_from_thread)
        self._signals.error_signal.connect(self._on_error_from_thread)
        self._signals.window_lost_signal.connect(self._on_window_lost_from_thread)

    def _setup_shortcuts(self):
        QShortcut(
            QKeySequence("F9"),
            self,
            self._toggle_pause,
            context=Qt.ShortcutContext.ApplicationShortcutContext,
        )
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_current_rule)
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
        self._save_config({"last_window": title})

    # === Rule list ===
    def _refresh_rule_list(self):
        self._rules = load_rules(self._rules_path)
        self._rule_list.blockSignals(True)
        self._rule_list.clear()
        for r in self._rules:
            item = QListWidgetItem()
            text = f"[{'✓' if r.enabled else '✗'}] {r.name}"
            item.setText(text)
            item.setData(Qt.ItemDataRole.UserRole, r.id)
            self._rule_list.addItem(item)
        self._rule_list.blockSignals(False)
        self._rule_hint.setVisible(len(self._rules) == 0)
        if self._rules:
            self._rule_list.setCurrentRow(0)
        else:
            self._selected_rule_id = None
            self._show_rule_detail(None)

    def _get_current_rule(self) -> Optional[Rule]:
        for r in self._rules:
            if r.id == self._selected_rule_id:
                return r
        return None

    def _on_rule_selected(self, row: int):
        if 0 <= row < len(self._rules):
            rule = self._rules[row]
            self._selected_rule_id = rule.id
            self._show_rule_detail(rule)
        else:
            self._selected_rule_id = None
            self._show_rule_detail(None)

    def _show_rule_detail(self, rule: Optional[Rule]):
        if rule is None:
            self._edit_stack.setCurrentIndex(0)
            return
        self._edit_stack.setCurrentIndex(1)
        self._edit_save_btn.setEnabled(True)
        self._edit_roi_btn.setEnabled(True)
        self._edit_name.setEnabled(True)
        self._edit_target.setEnabled(True)
        self._edit_enabled.setEnabled(True)
        self._edit_cooldown.setEnabled(True)
        self._edit_trigger_mode.setEnabled(True)
        self._edit_click_button.setEnabled(True)
        self._edit_click_position.setEnabled(True)
        self._edit_custom_x.setEnabled(True)
        self._edit_custom_y.setEnabled(True)
        self._edit_fuzzy.setEnabled(True)
        self._edit_fuzzy_threshold.setEnabled(True)
        self._edit_max_triggers.setEnabled(True)
        self._edit_random_offset.setEnabled(True)
        self._edit_name.setText(rule.name)
        self._edit_target.setText(rule.target_text)
        self._edit_enabled.setChecked(rule.enabled)
        self._edit_roi_label.setText(
            f"x={rule.roi['x']} y={rule.roi['y']} w={rule.roi['w']} h={rule.roi['h']}"
            if not all(rule.roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
            else "全視窗"
        )
        self._edit_cooldown.setValue(rule.cooldown_ms)
        self._edit_trigger_mode.setCurrentText(rule.trigger_mode)
        self._edit_click_button.setCurrentText(rule.click_button)
        self._edit_click_position.setCurrentText(rule.click_position)
        self._edit_custom_x.setValue(rule.custom_x)
        self._edit_custom_y.setValue(rule.custom_y)
        self._edit_fuzzy.setChecked(rule.fuzzy)
        self._edit_fuzzy_threshold.setValue(int(rule.fuzzy_threshold * 100))
        self._edit_max_triggers.setValue(rule.max_triggers)
        self._edit_random_offset.setValue(rule.random_offset)

    def _on_click_position_changed(self, pos: str):
        is_custom = pos == "custom"
        self._edit_custom_x.setEnabled(is_custom)
        self._edit_custom_y.setEnabled(is_custom)

    def _on_fuzzy_changed(self, state):
        self._edit_fuzzy_threshold.setEnabled(state == 2)

    def _add_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再新增規則")
            return
        import uuid

        rule = Rule(
            id=f"rule_{uuid.uuid4().hex[:8]}",
            name="新規則",
            enabled=True,
            target_text="請輸入文字",
            fuzzy=False,
            fuzzy_threshold=0.8,
            roi={"x": 0, "y": 0, "w": 0, "h": 0},
            click_position="text_center",
            click_button="left",
            cooldown_ms=2000,
            trigger_mode="once",
            max_triggers=-1,
            random_offset=3,
        )
        self._rules.append(rule)
        save_rules(self._rules, self._rules_path)
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()
        idx = len(self._rules) - 1
        self._rule_list.setCurrentRow(idx)

    def _delete_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再刪除規則")
            return
        rule = self._get_current_rule()
        if rule is None:
            return
        if (
            QMessageBox.question(
                self,
                "刪除規則",
                f"確定刪除規則「{rule.name}」？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._rules = [r for r in self._rules if r.id != rule.id]
        save_rules(self._rules, self._rules_path)
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()

    def _save_current_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再儲存規則")
            return
        rule = self._get_current_rule()
        if rule is None:
            return
        target = self._edit_target.text().strip()
        if not target:
            QMessageBox.warning(self, "無效規則", "目標文字不可為空白")
            return
        rule.name = self._edit_name.text()
        rule.target_text = target
        rule.enabled = self._edit_enabled.isChecked()
        rule.cooldown_ms = self._edit_cooldown.value()
        rule.trigger_mode = self._edit_trigger_mode.currentText()
        rule.click_button = self._edit_click_button.currentText()
        rule.click_position = self._edit_click_position.currentText()
        rule.custom_x = self._edit_custom_x.value()
        rule.custom_y = self._edit_custom_y.value()
        rule.fuzzy = self._edit_fuzzy.isChecked()
        rule.fuzzy_threshold = self._edit_fuzzy_threshold.value() / 100.0
        rule.max_triggers = self._edit_max_triggers.value()
        rule.random_offset = self._edit_random_offset.value()
        save_rules(self._rules, self._rules_path)
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()

    # === ROI selector ===
    def _open_roi_selector(self):
        mod = load_sibling("roi", "07_gui_roi.py")
        result = mod.select_roi(parent_window=self)
        rule = self._get_current_rule()
        if result and rule:
            rule.roi = result
            self._edit_roi_label.setText(
                f"x={result['x']} y={result['y']} w={result['w']} h={result['h']}"
            )
            save_rules(self._rules, self._rules_path)

    # === OCR diagnostic ===
    def _open_ocr_debug(self):
        if self._debug_window is not None and self._debug_window.isVisible():
            self._debug_window.close()
            return
        if self._loop is not None and self._loop.is_running:
            QMessageBox.warning(self, "無法開啟", "請先停止偵測循環再開啟診斷模式。")
            return
        title = self._window_combo.currentText()
        if not title:
            QMessageBox.warning(self, "警告", "請先選擇目標視窗")
            return
        mod = load_sibling("ocr_debug", "09_ocr_debug.py")
        self._debug_window = mod.OcrDebugWindow(title, self)
        self._debug_window.roi_selected.connect(self._on_debug_roi_selected)
        self._debug_window.rule_requested.connect(self._on_debug_rule_requested)
        self._debug_window.closed.connect(self._on_debug_closed)
        self._debug_window.show()
        self._debug_btn.setText("關閉診斷")

    def _on_debug_closed(self):
        self._debug_window = None
        self._debug_btn.setText("OCR 診斷")

    def _on_debug_roi_selected(self, roi: dict):
        rule = self._get_current_rule()
        if rule is None:
            QMessageBox.information(self, "提示", "請先在左側選取一條規則再套用 ROI。")
            return
        rule.roi = roi
        save_rules(self._rules, self._rules_path)
        self._show_rule_detail(rule)
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()
        self._status_bar.showMessage(
            f"已套用 ROI 至規則「{rule.name}」: x={roi['x']} y={roi['y']} w={roi['w']} h={roi['h']}"
        )

    def _on_debug_rule_requested(self, rule_data: dict):
        import uuid

        rule = Rule(
            id=f"rule_{uuid.uuid4().hex[:8]}",
            name=rule_data["target_text"],
            enabled=True,
            target_text=str(rule_data["target_text"]).strip() or "請輸入文字",
            fuzzy=rule_data.get("fuzzy", False),
            fuzzy_threshold=0.8,
            roi=rule_data.get("roi", {"x": 0, "y": 0, "w": 0, "h": 0}),
            click_position=rule_data.get("click_position", "text_center"),
            click_button="left",
            cooldown_ms=int(rule_data.get("cooldown", 1.0) * 1000),
            trigger_mode="once",
            max_triggers=-1,
            random_offset=3,
        )
        self._rules.append(rule)
        save_rules(self._rules, self._rules_path)
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()
        idx = len(self._rules) - 1
        self._rule_list.setCurrentRow(idx)
        self._status_bar.showMessage(f"已從 OCR 診斷新增規則：「{rule_data['target_text']}」")

    # === Start / Pause ===
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
        self._btn_toggle.setEnabled(False)
        self._btn_toggle.setText("初始化中...")
        self._status_bar.showMessage("正在初始化 OCR 引擎…")
        self._init_worker = InitWorker(self._rules_path, title, self._signals)
        self._init_worker.finished.connect(self._on_init_finished)
        self._init_worker.start()

    def _on_init_finished(self, success: bool, error_msg: str):
        self._btn_toggle.setEnabled(True)
        if success:
            self._loop = self._init_worker.loop
            self._btn_toggle.setText("暫停")
            self._update_edit_enabled(False)
            self._status_bar.showMessage(
                f"偵測中 — 目標: {self._window_combo.currentText()}（按 F9 暫停）"
            )
        else:
            QMessageBox.critical(self, "初始化失敗", f"無法啟動主迴圈：\n{error_msg}")
            self._btn_toggle.setText("啟動")
            self._status_bar.showMessage(f"初始化失敗 — {error_msg}")

    def _stop_loop(self):
        if self._loop:
            self._loop.stop()
            self._loop = None
        self._btn_toggle.setText("啟動")
        self._update_edit_enabled(True)
        self._status_bar.showMessage("已停止")

    def _toggle_pause(self):
        if self._loop is None or not self._loop.is_running:
            return
        if self._loop.is_paused:
            self._loop.resume()
            self._btn_toggle.setText("暫停")
            self._log_widget.append_error("▶ 恢復偵測")
            self._status_bar.showMessage("偵測中（按 F9 暫停）")
        else:
            self._loop.pause()
            self._btn_toggle.setText("繼續")
            self._log_widget.append_error("⏸ 暫停偵測")
            self._status_bar.showMessage("已暫停 — 按 F9 繼續")

    def _update_edit_enabled(self, enabled: bool):
        self._rule_list.setEnabled(enabled)
        self._add_rule_btn.setEnabled(enabled)
        self._del_rule_btn.setEnabled(enabled)
        self._import_btn.setEnabled(enabled)
        self._export_btn.setEnabled(enabled)
        self._refresh_btn.setEnabled(enabled)
        self._debug_btn.setEnabled(enabled)
        if enabled:
            self._show_rule_detail(self._get_current_rule())
        else:
            self._edit_save_btn.setEnabled(False)
            self._edit_roi_btn.setEnabled(False)
            self._edit_name.setEnabled(False)
            self._edit_target.setEnabled(False)
            self._edit_enabled.setEnabled(False)
            self._edit_cooldown.setEnabled(False)
            self._edit_trigger_mode.setEnabled(False)
            self._edit_click_button.setEnabled(False)
            self._edit_click_position.setEnabled(False)
            self._edit_custom_x.setEnabled(False)
            self._edit_custom_y.setEnabled(False)
            self._edit_fuzzy.setEnabled(False)
            self._edit_fuzzy_threshold.setEnabled(False)
            self._edit_max_triggers.setEnabled(False)
            self._edit_random_offset.setEnabled(False)

    # === Import / Export ===
    def _import_rules(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入規則", str(_here), "JSON (*.json)")
        if not path:
            return
        imported = load_rules(path)
        if not imported:
            QMessageBox.warning(self, "匯入失敗", "檔案中沒有有效規則")
            return
        self._rules = imported
        save_rules(self._rules, self._rules_path)
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()

    def _export_rules(self):
        if not self._rules:
            QMessageBox.information(self, "匯出規則", "目前沒有任何規則可匯出。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "匯出規則", str(_here / "rules_export.json"), "JSON (*.json)"
        )
        if not path:
            return
        save_rules(self._rules, path)

    # === Thread-safe callbacks ===
    def _on_trigger_from_thread(self, log: TriggerLog):
        self._log_widget.append_trigger(log)

    def _on_error_from_thread(self, msg: str):
        self._log_widget.append_error(msg)

    def _on_window_lost_from_thread(self):
        self._window_lost = True
        self._btn_toggle.setText("繼續")
        self._log_widget.append_error("⚠ 目標視窗消失，偵測已暫停")
        self._status_bar.showMessage("⚠ 目標視窗已關閉，偵測已暫停")

    # === Close ===
    def closeEvent(self, event):
        if self._debug_window:
            self._debug_window.close()
            self._debug_window = None
        if self._loop:
            self._loop.stop()
        _ahk_mod.shutdown()
        event.accept()


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
