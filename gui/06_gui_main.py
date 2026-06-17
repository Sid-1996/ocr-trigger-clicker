import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
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

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _loader import load_sibling

_here = Path(__file__).resolve().parent.parent


class _NoWheelCombo(QComboBox):
    def wheelEvent(self, e):
        e.ignore()


class _NoWheelSpin(QSpinBox):
    def wheelEvent(self, e):
        e.ignore()


_ahk_mod = load_sibling("ahk_socket", "core/03_ahk_socket.py")
_main_loop_mod = load_sibling("main_loop", "core/05_main_loop.py")
MainLoop = _main_loop_mod.MainLoop
TriggerLog = _main_loop_mod.TriggerLog
Rule = _main_loop_mod.Rule
list_windows = _main_loop_mod.list_windows
load_rules = _main_loop_mod.load_rules
save_rules = _main_loop_mod.save_rules
activate_window = _main_loop_mod.activate_window
get_window_rect = _main_loop_mod.get_window_rect

_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
list_tasks = _rule_mod.list_tasks
load_task = _rule_mod.load_task
save_task = _rule_mod.save_task
delete_task = _rule_mod.delete_task
rename_task = _rule_mod.rename_task
export_task = _rule_mod.export_task
import_task = _rule_mod.import_task
migrate_old_rules = _rule_mod.migrate_old_rules

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


class InitWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, rules_path: str, window_title: str, signals: WorkerSignals, focus_safe: bool = False, verbose: bool = True):
        super().__init__()
        self._rules_path = rules_path
        self._window_title = window_title
        self._signals = signals
        self._focus_safe = focus_safe
        self._verbose = verbose
        self.loop: Optional[MainLoop] = None

    def run(self):
        try:
            loop = MainLoop(self._rules_path, self._window_title, focus_safe=self._focus_safe, verbose=self._verbose)
            loop.on_trigger = lambda log: self._signals.trigger_signal.emit(log)
            loop.on_error = lambda msg: self._signals.error_signal.emit(msg)
            loop.on_warning = lambda msg: self._signals.warning_signal.emit(msg)
            loop.on_info = lambda msg: self._signals.info_signal.emit(msg)
            loop.on_window_lost = lambda: self._signals.window_lost_signal.emit()
            loop.on_emergency = lambda: self._signals.emergency_signal.emit()
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
            self._config_path = get_data_path("config.json")
        except ImportError:
            here = Path(__file__).resolve().parent.parent
            self._config_path = str(here / "config.json")

        migrate_old_rules()

        self._signals = WorkerSignals()
        self._loop: Optional[MainLoop] = None
        self._selected_rule_id: Optional[str] = None
        self._window_lost = False
        self._current_task: str = ""

        self._setup_ui()
        self._debug_panel = OcrDebugPanel("", self)
        self._debug_panel.rule_requested.connect(self._on_debug_rule_requested)
        self._debug_page_layout.addWidget(self._debug_panel, 1)
        self._connect_signals()
        self._setup_shortcuts()

        _ocr_mod.set_ocr_health_callback(self._on_ocr_health)

        self._refresh_window_list()
        self._restore_last_state()
        self._refresh_task_list()

        self._ahk_ready = _ahk_mod.init_ahk()
        if not self._ahk_ready:
            self._status_bar.showMessage("⚠ AHK 未啟動，點擊功能將無法使用")

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

    def _restore_last_state(self):
        config = self._load_config()
        self._focus_safe_cb.setChecked(bool(config.get("focus_safe", False)))
        last_win = config.get("last_window", "")
        if last_win:
            idx = self._window_combo.findText(last_win)
            if idx >= 0:
                self._window_combo.setCurrentIndex(idx)
            else:
                self._window_combo.setPlaceholderText(f"⚠ 上次的視窗「{last_win}」已不存在，請重新選擇")
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
        self._task_save_btn = QPushButton("💾")
        self._task_save_btn.setFixedWidth(28)
        self._task_save_btn.setToolTip("覆蓋儲存目前規則到當前任務")
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
        toolbar.addWidget(self._task_save_btn)
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
        self._btn_toggle.setToolTip("開始偵測所選視窗（按 F9 暫停／繼續）")
        self._debug_btn = QPushButton("🔍OCR 診斷")
        self._debug_btn.setToolTip("即時顯示視窗內所有辨識到的文字與位置")
        self._focus_safe_cb = QCheckBox("僅前景點擊")
        self._focus_safe_cb.setToolTip("啟用後僅在目標視窗為前景視窗時才執行點擊，避免干擾其他操作")
        toolbar.addWidget(self._btn_toggle)
        toolbar.addWidget(self._debug_btn)
        toolbar.addWidget(self._focus_safe_cb)
        toolbar.addStretch()
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
        self._edit_coord_label = QLabel("尚未選取")
        self._edit_pick_coord_btn = QPushButton("選取點擊座標")
        self._edit_pick_coord_btn.clicked.connect(self._on_pick_coord)
        self._coord_row = QWidget()
        coord_layout = QHBoxLayout(self._coord_row)
        coord_layout.setContentsMargins(0, 0, 0, 0)
        coord_layout.addWidget(self._edit_coord_label)
        coord_layout.addWidget(self._edit_pick_coord_btn)
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
        self._edit_form.addRow("點擊座標:", self._coord_row)
        self._edit_form.addRow("模糊比對:", self._edit_fuzzy)
        self._edit_form.addRow("模糊閾值:", self._edit_fuzzy_threshold)
        self._edit_form.addRow("最大觸發:", self._edit_max_triggers)
        self._edit_form.addRow("隨機抖動:", self._edit_random_offset)
        self._edit_form.addRow(self._edit_save_btn)

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

        # === Bottom: log area ===
        log_mod = load_sibling("gui_log", "gui/08_gui_log.py")
        self._log_widget = log_mod.LogWidget()
        layout.addWidget(self._log_widget)

        # === Status bar ===
        self._status_bar = QStatusBar()
        self._status_bar.showMessage("就緒 — 請選擇視窗並新增規則")
        self._perf_label = QLabel("FPS:-- | CPU:--% | MEM:--MB | 點擊:--/s")
        self._perf_label.setStyleSheet("color: #888; font-size: 11px; padding-right: 8px;")
        self._status_bar.addPermanentWidget(self._perf_label)
        self._perf_timer = QTimer()
        self._perf_timer.timeout.connect(self._update_perf_display)
        self._perf_timer.start(1000)
        self.setStatusBar(self._status_bar)

    def _connect_signals(self):
        self._refresh_btn.clicked.connect(self._refresh_window_list)
        self._window_combo.currentTextChanged.connect(self._on_window_changed)
        self._btn_toggle.clicked.connect(self._toggle_start)
        self._add_rule_btn.clicked.connect(self._add_rule)
        self._del_rule_btn.clicked.connect(self._delete_rule)
        self._rule_list.currentRowChanged.connect(self._on_rule_selected)
        self._edit_save_btn.clicked.connect(self._save_current_rule)
        self._edit_roi_btn.clicked.connect(self._open_roi_selector)
        self._debug_btn.clicked.connect(self._switch_to_debug)
        self._debug_back_btn.clicked.connect(self._switch_to_rules)
        self._focus_safe_cb.stateChanged.connect(self._on_focus_safe_changed)

        self._edit_click_position.currentTextChanged.connect(self._on_click_position_changed)
        self._edit_fuzzy.stateChanged.connect(self._on_fuzzy_changed)

        self._task_combo.currentTextChanged.connect(self._on_task_changed)
        self._task_new_btn.clicked.connect(self._on_task_new)
        self._task_save_btn.clicked.connect(self._on_task_save)
        self._task_del_btn.clicked.connect(self._on_task_delete)
        self._task_import_btn.clicked.connect(self._on_task_import)
        self._task_export_btn.clicked.connect(self._on_task_export)

        self._signals.trigger_signal.connect(self._on_trigger_from_thread)
        self._signals.error_signal.connect(self._on_error_from_thread)
        self._signals.warning_signal.connect(self._on_warning_from_thread)
        self._signals.info_signal.connect(self._on_info_from_thread)
        self._signals.window_lost_signal.connect(self._on_window_lost_from_thread)
        self._signals.emergency_signal.connect(self._emergency_stop)

    def _setup_shortcuts(self):
        QShortcut(
            QKeySequence("F9"),
            self,
            self._toggle_pause,
            context=Qt.ShortcutContext.ApplicationShortcut,
        )
        QShortcut(
            QKeySequence("F12"),
            self,
            self._emergency_stop,
            context=Qt.ShortcutContext.ApplicationShortcut,
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
        config = self._load_config()
        config["last_window"] = title
        self._save_config(config)
        if hasattr(self, "_debug_panel") and self._debug_panel is not None:
            self._debug_panel._window_title = title
            self._debug_panel.clear_results()

    def _on_focus_safe_changed(self, state):
        enabled = state == 2
        config = self._load_config()
        config["focus_safe"] = enabled
        self._save_config(config)
        if self._loop:
            self._loop.set_focus_safe(enabled)

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

    def _on_task_save(self):
        if not self._current_task:
            return
        save_task(self._current_task, self._rules)
        if self._loop:
            self._loop.reload_rules()
        self._status_bar.showMessage(f"任務「{self._current_task}」已儲存")

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

    def _on_task_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入任務", str(_here), "JSON (*.json)")
        if not path:
            return
        imported_name = import_task(path)
        if imported_name is None:
            QMessageBox.warning(self, "匯入失敗", "檔案格式無效，請確認是包含 rules 陣列的 JSON。")
            return
        self._refresh_task_list()
        idx = self._task_combo.findText(imported_name)
        if idx >= 0:
            self._task_combo.setCurrentIndex(idx)
        self._status_bar.showMessage(f"已匯入任務「{imported_name}」")

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
    def _refresh_rule_list(self):
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
        self._edit_pick_coord_btn.setEnabled(True)
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
        self._edit_coord_label.setText(f"X: {rule.custom_x}, Y: {rule.custom_y}")
        self._edit_fuzzy.setChecked(rule.fuzzy)
        self._edit_fuzzy_threshold.setValue(int(rule.fuzzy_threshold * 100))
        self._edit_max_triggers.setValue(rule.max_triggers)
        self._edit_random_offset.setValue(rule.random_offset)

    def _on_click_position_changed(self, pos: str):
        self._coord_row.setVisible(pos == "custom")

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
        save_task(self._current_task, self._rules)
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
        save_task(self._current_task, self._rules)
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
        rule.fuzzy = self._edit_fuzzy.isChecked()
        rule.fuzzy_threshold = self._edit_fuzzy_threshold.value() / 100.0
        rule.max_triggers = self._edit_max_triggers.value()
        rule.random_offset = self._edit_random_offset.value()
        save_task(self._current_task, self._rules)
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()

    # === Click coordinate picker ===
    def _on_pick_coord(self):
        rule = self._get_current_rule()
        if rule is None:
            return
        title = self._window_combo.currentText()
        if title:
            activate_window(title)
        mod = load_sibling("click_picker", "gui/13_gui_click_picker.py")
        result = mod.pick_click_position(parent_window=self)
        if result is None:
            return
        title = self._window_combo.currentText()
        if title:
            screen = QApplication.primaryScreen()
            ratio = screen.devicePixelRatio()
            result = (int(result[0] * ratio), int(result[1] * ratio))
            wr = get_window_rect(title)
            if wr:
                result = (result[0] - wr["x"], result[1] - wr["y"])
        rule.custom_x, rule.custom_y = result
        rule.click_position = "custom"
        self._edit_click_position.setCurrentText("custom")
        self._edit_coord_label.setText(f"X: {result[0]}, Y: {result[1]}")
        save_task(self._current_task, self._rules)
        self._edit_stack.setCurrentIndex(1)
        self._status_bar.showMessage(f"已選取點擊座標: X={result[0]}, Y={result[1]}")

    # === ROI selector ===
    def _open_roi_selector(self):
        title = self._window_combo.currentText()
        if title:
            activate_window(title)
        mod = load_sibling("roi", "gui/07_gui_roi.py")
        result = mod.select_roi(parent_window=self)
        if not result:
            return
        rule = self._get_current_rule()
        if rule:
            title = self._window_combo.currentText()
            if title:
                screen = QApplication.primaryScreen()
                ratio = screen.devicePixelRatio()
                result["x"] = int(result["x"] * ratio)
                result["y"] = int(result["y"] * ratio)
                wr = get_window_rect(title)
                if wr:
                    result["x"] -= wr["x"]
                    result["y"] -= wr["y"]
            rule.roi = result
            self._edit_roi_label.setText(
                f"x={result['x']} y={result['y']} w={result['w']} h={result['h']}"
            )
            save_task(self._current_task, self._rules)
        self._edit_stack.setCurrentIndex(1)
        self._status_bar.showMessage(
            f"已選取偵測區域: ({result['x']},{result['y']}) {result['w']}×{result['h']}"
        )

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
        self._log_widget.hide()
        self._status_bar.showMessage(f"OCR 診斷 — 目標: {title}")

    def _switch_to_rules(self):
        self._main_stack.setCurrentIndex(0)
        self._log_widget.show()
        self._status_bar.showMessage("就緒")

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
        save_task(self._current_task, self._rules)
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()
        idx = len(self._rules) - 1
        self._rule_list.setCurrentRow(idx)
        self._main_stack.setCurrentIndex(0)
        self._debug_btn.setText("OCR 診斷")
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
        activate_window(title)
        self._btn_toggle.setEnabled(False)
        self._btn_toggle.setText("初始化中...")
        self._status_bar.showMessage("正在初始化 OCR 引擎…")
        focus_safe = self._focus_safe_cb.isChecked()
        task_path = str(Path(_tasks_dir()) / f"{self._current_task}.json")
        self._init_worker = InitWorker(str(task_path), title, self._signals, focus_safe)
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
            self._log_widget.append_info("恢復偵測")
            self._status_bar.showMessage("偵測中（按 F9 暫停）")
        else:
            self._loop.pause()
            self._btn_toggle.setText("繼續")
            self._log_widget.append_info("暫停偵測")
            self._status_bar.showMessage("已暫停 — 按 F9 繼續")

    def _update_edit_enabled(self, enabled: bool):
        self._rule_list.setEnabled(enabled)
        self._add_rule_btn.setEnabled(enabled)
        self._del_rule_btn.setEnabled(enabled)
        self._refresh_btn.setEnabled(enabled)
        self._debug_btn.setEnabled(enabled)
        self._focus_safe_cb.setEnabled(enabled)
        self._task_new_btn.setEnabled(enabled)
        self._task_save_btn.setEnabled(enabled)
        self._task_del_btn.setEnabled(enabled)
        self._task_import_btn.setEnabled(enabled)
        self._task_export_btn.setEnabled(enabled)
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
            self._edit_pick_coord_btn.setEnabled(False)
            self._edit_fuzzy.setEnabled(False)
            self._edit_fuzzy_threshold.setEnabled(False)
            self._edit_max_triggers.setEnabled(False)
            self._edit_random_offset.setEnabled(False)

    # === Thread-safe callbacks ===
    def _on_trigger_from_thread(self, log: TriggerLog):
        self._log_widget.append_trigger(log)

    def _on_error_from_thread(self, msg: str):
        self._log_widget.append_error(msg)

    def _on_warning_from_thread(self, msg: str):
        self._log_widget.append_warning(msg)

    def _on_info_from_thread(self, msg: str):
        self._log_widget.append_info(msg)

    def _on_window_lost_from_thread(self):
        self._window_lost = True
        self._btn_toggle.setText("繼續")
        self._log_widget.append_warning("目標視窗消失，偵測已暫停")
        self._status_bar.showMessage("⚠ 目標視窗已關閉，偵測已暫停")

    # === Emergency & OCR Health ===
    def _emergency_stop(self):
        if self._loop is None:
            return
        self._loop.emergency_stop()
        self._loop = None
        self._btn_toggle.setText("啟動")
        self._update_edit_enabled(True)
        self._status_bar.showMessage("🛑 緊急停止 — 按「啟動」重新開始")
        self._log_widget.append_info("緊急停止（F12）")

    def _on_ocr_health(self, msg: str):
        self._log_widget.append_warning(f"{msg}")

    # === Close ===
    def closeEvent(self, event):
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
