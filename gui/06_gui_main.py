import json
import sys
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
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
    # ponytail: shifted number symbols → digit for combo search
    _SHIFT2DIGIT = {
        "!": "1",
        "@": "2",
        "#": "3",
        "$": "4",
        "%": "5",
        "^": "6",
        "&": "7",
        "*": "8",
        "(": "9",
        ")": "0",
    }

    def keyPressEvent(self, event):
        text = event.text()
        # ponytail: mask out NumLock/Keypad so number keys still work
        _IGNORE = (
            Qt.KeyboardModifier.KeypadModifier
            | Qt.KeyboardModifier.GroupSwitchModifier
        )
        relevant_mods = event.modifiers() & ~_IGNORE
        if (
            text
            and len(text) == 1
            and text.isprintable()
            and relevant_mods
            in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier)
        ):
            key = text.lower()
            key = self._SHIFT2DIGIT.get(key, key)
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


class _RuleTreeWidget(QTreeWidget):
    def dropEvent(self, event):
        if self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.OnItem:
            event.ignore()
            return
        super().dropEvent(event)


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

    def __init__(
        self,
        rules_path: str,
        window_title: str,
        signals: WorkerSignals,
        focus_safe: bool = False,
        verbose: bool = True,
    ):
        super().__init__()
        self._rules_path = rules_path
        self._window_title = window_title
        self._signals = signals
        self._focus_safe = focus_safe
        self._verbose = verbose
        self.loop: Optional[MainLoop] = None

    def run(self):
        try:
            loop = MainLoop(
                self._rules_path,
                self._window_title,
                focus_safe=self._focus_safe,
                verbose=self._verbose,
            )
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
            self._debug_panel.sub_target_requested.connect(self._on_debug_sub_target_requested)
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
        self._focus_safe_cb.setChecked(bool(config.get("focus_safe", False)))
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
        self._btn_toggle.setToolTip("開始偵測所選視窗（按 F9 暫停／繼續）")
        self._debug_btn = QPushButton("🔍OCR 診斷")
        self._debug_btn.setToolTip("即時顯示視窗內所有辨識到的文字與位置")
        self._focus_safe_cb = QCheckBox("僅前景點擊")
        self._focus_safe_cb.setToolTip("啟用後僅在目標視窗為前景視窗時才執行點擊，避免干擾其他操作")
        toolbar.addWidget(self._btn_toggle)
        toolbar.addWidget(self._debug_btn)
        toolbar.addWidget(self._focus_safe_cb)
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
        left_layout.addWidget(self._rule_list)

        self._rule_hint = QLabel("← 點擊「新增」建立第一條規則")
        self._rule_hint.setStyleSheet("color: #888; font-size: 11px;")
        left_layout.addWidget(self._rule_hint)

        rule_btn_bar = QHBoxLayout()
        self._add_rule_btn = QPushButton("新增")
        self._add_rule_btn.setToolTip("新增一條空白規則")
        self._del_rule_btn = QPushButton("刪除 (Del)")
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
        self._edit_trigger_mode.addItem("觸發一次", "once")
        self._edit_trigger_mode.addItem("重複觸發", "repeat")
        self._edit_trigger_mode.setToolTip("once：觸發一次後停用 ｜ repeat：持續觸發")
        self._edit_click_button = _NoWheelCombo()
        self._edit_click_button.addItem("左鍵", "left")
        self._edit_click_button.addItem("右鍵", "right")
        self._edit_click_button.setToolTip("點擊使用的滑鼠按鍵")
        self._edit_click_position = _NoWheelCombo()
        self._edit_click_position.addItem("文字中心", "text_center")
        self._edit_click_position.addItem("自訂座標", "custom")
        self._edit_click_position.setToolTip("text_center：點擊文字中心 ｜ custom：自訂座標")
        self._edit_coord_label = QLabel("尚未選取")
        self._edit_pick_coord_btn = QPushButton("選取點擊座標")
        self._edit_pick_coord_btn.setToolTip("在目標視窗上點擊以選取自訂點擊座標")
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

        # ── P0: 動作類型 / 按鍵 / 點擊後等待 / 等待規則 ──
        self._edit_post_delay = _NoWheelSpin()
        self._edit_post_delay.setRange(0, 30000)
        self._edit_post_delay.setSuffix(" ms")
        self._edit_post_delay.setValue(0)
        self._edit_post_delay.setToolTip("點擊/按鍵後等待 N 毫秒，再進入下一輪偵測")
        self._edit_action_type = _NoWheelCombo()
        self._edit_action_type.addItem("滑鼠點擊", "click")
        self._edit_action_type.addItem("鍵盤按鍵", "key")
        self._edit_action_type.setToolTip("click：滑鼠點擊 ｜ key：鍵盤按鍵")
        self._edit_key = _KeyCombo()
        for group in [
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
            [str(i) for i in range(10)],
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
            ["Alt", "CapsLock", "NumLock", "ScrollLock", "PrintScreen", "Pause", "AppsKey"],
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
            self._edit_key.insertSeparator(self._edit_key.count())
            for item in group:
                if isinstance(item, tuple):
                    text, data = item
                else:
                    text = data = item
                self._edit_key.addItem(text, data)
        self._edit_key.setCurrentIndex(0)
        self._edit_key.setToolTip("選擇或輸入要模擬的按鍵名稱（支援 Shift+字母快速跳轉）")
        self._edit_depends_on = QListWidget()
        self._edit_depends_on.setToolTip(
            "進階設定：本規則需等待哪些規則先完成觸發？勾選的規則都觸發過後，本規則才會開始偵測。"
        )
        self._edit_depends_on.setMaximumHeight(180)
        self._edit_depends_on.setAlternatingRowColors(True)
        self._edit_depends_on_label = QLabel("勾選需全部觸發後才執行本規則的等待規則：")
        self._edit_depends_on_label.setStyleSheet("color: #888; font-size: 11px;")
        self._edit_depends_on_container = QWidget()
        dep_layout = QVBoxLayout(self._edit_depends_on_container)
        dep_layout.setContentsMargins(0, 0, 0, 0)
        dep_layout.setSpacing(2)
        dep_layout.addWidget(self._edit_depends_on_label)
        dep_layout.addWidget(self._edit_depends_on)

        # ── Phase 2: sub-target (if/if-not) ──
        self._sub_toggle_btn = QPushButton("▸ 進階條件 (二次確認)")
        self._sub_toggle_btn.setCheckable(True)
        self._sub_toggle_btn.setChecked(False)
        self._sub_toggle_btn.clicked.connect(self._toggle_sub_section)
        self._sub_panel = QWidget()
        self._sub_panel.setVisible(False)
        self._sub_form = QFormLayout(self._sub_panel)
        self._sub_form.setContentsMargins(0, 0, 0, 0)

        self._edit_sub_target = QLineEdit()
        self._edit_sub_target.setToolTip("進階確認文字：若主目標命中，則進一步檢查此文字是否也存在")
        self._edit_sub_roi_label = QLabel("與主目標相同")
        self._edit_sub_roi_btn = QPushButton("框選確認區域")
        self._edit_sub_roi_btn.setToolTip("確認條件獨立的偵測區域（留空 = 與主目標相同）")
        self._edit_sub_not_found_retries = _NoWheelSpin()
        self._edit_sub_not_found_retries.setRange(1, 99)
        self._edit_sub_not_found_retries.setValue(3)
        self._edit_sub_not_found_retries.setToolTip(
            "確認文字連續未找到的重試次數，達到後才執行未找到動作"
        )
        self._edit_on_found_action = _NoWheelCombo()
        self._edit_on_found_action.addItem("點擊文字中心", "click_sub_center")
        self._edit_on_found_action.addItem("自訂座標", "click_custom")
        self._edit_on_found_action.setToolTip(
            "點擊文字中心：點擊確認文字中心 ｜ 自訂座標：自訂座標"
        )
        self._edit_on_found_custom_label = QLabel("尚未選取")
        self._edit_on_found_pick_btn = QPushButton("選取點擊座標")
        self._edit_on_found_pick_btn.setToolTip("在目標視窗上點擊以選取「找到時」的自訂點擊座標")
        self._edit_on_found_pick_btn.clicked.connect(self._on_pick_sub_found_coord)
        self._on_found_coord_row = QWidget()
        of_layout = QHBoxLayout(self._on_found_coord_row)
        of_layout.setContentsMargins(0, 0, 0, 0)
        of_layout.addWidget(self._edit_on_found_custom_label)
        of_layout.addWidget(self._edit_on_found_pick_btn)
        self._edit_on_not_found_action = _NoWheelCombo()
        self._edit_on_not_found_action.addItem("不動作", "click_nothing")
        self._edit_on_not_found_action.addItem("自訂座標", "click_custom")
        self._edit_on_not_found_action.setToolTip(
            "click_nothing：不執行任何動作 ｜ click_custom：自訂座標點擊"
        )
        self._edit_on_not_found_custom_label = QLabel("尚未選取")
        self._edit_on_not_found_pick_btn = QPushButton("選取點擊座標")
        self._edit_on_not_found_pick_btn.setToolTip(
            "在目標視窗上點擊以選取「未找到時」的自訂點擊座標"
        )
        self._edit_on_not_found_pick_btn.clicked.connect(self._on_pick_sub_not_found_coord)
        self._on_not_found_coord_row = QWidget()
        onf_layout = QHBoxLayout(self._on_not_found_coord_row)
        onf_layout.setContentsMargins(0, 0, 0, 0)
        onf_layout.addWidget(self._edit_on_not_found_custom_label)
        onf_layout.addWidget(self._edit_on_not_found_pick_btn)

        self._sub_form.addRow("確認文字:", self._edit_sub_target)
        self._sub_form.addRow("確認區域:", self._edit_sub_roi_label)
        self._sub_form.addRow("", self._edit_sub_roi_btn)
        self._sub_form.addRow("重試次數:", self._edit_sub_not_found_retries)
        self._sub_form.addRow("找到時動作:", self._edit_on_found_action)
        self._sub_form.addRow("", self._on_found_coord_row)
        self._sub_form.addRow("未找到時動作:", self._edit_on_not_found_action)
        self._sub_form.addRow("", self._on_not_found_coord_row)
        self._clear_sub_btn = QPushButton("清除進階條件")
        self._clear_sub_btn.setToolTip("移除目前規則的進階條件設定")
        self._clear_sub_btn.clicked.connect(self._on_clear_sub_target)
        self._sub_form.addRow(self._clear_sub_btn)

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
        self._edit_form.addRow("點擊後等待:", self._edit_post_delay)
        self._edit_form.addRow("觸發模式:", self._edit_trigger_mode)
        self._edit_form.addRow("動作類型:", self._edit_action_type)
        self._edit_form.addRow("按鍵:", self._edit_key)
        self._edit_form.addRow("滑鼠按鈕:", self._edit_click_button)
        self._edit_form.addRow("等待規則:", self._edit_depends_on_container)
        self._edit_form.addRow("點擊位置:", self._edit_click_position)
        self._edit_form.addRow("點擊座標:", self._coord_row)
        self._edit_form.addRow("模糊比對:", self._edit_fuzzy)
        self._edit_form.addRow("模糊閾值:", self._edit_fuzzy_threshold)
        self._edit_form.addRow("最大觸發:", self._edit_max_triggers)
        self._edit_form.addRow("隨機抖動:", self._edit_random_offset)
        self._edit_form.addRow(self._sub_toggle_btn)
        self._edit_form.addRow(self._sub_panel)
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
        self._log_widget.setMaximumHeight(130)
        self._log_widget.setMinimumHeight(80)
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
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_rule_status)
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
        self._edit_save_btn.clicked.connect(self._save_current_rule)
        self._edit_enabled.stateChanged.connect(self._on_enabled_changed)
        self._edit_roi_btn.clicked.connect(self._open_roi_selector)
        self._debug_btn.clicked.connect(self._switch_to_debug)
        self._debug_back_btn.clicked.connect(self._switch_to_rules)
        self._focus_safe_cb.stateChanged.connect(self._on_focus_safe_changed)

        self._edit_click_position.currentIndexChanged.connect(self._on_click_position_changed)
        self._edit_fuzzy.stateChanged.connect(self._on_fuzzy_changed)
        self._edit_on_found_action.currentIndexChanged.connect(self._on_sub_found_action_changed)
        self._edit_on_not_found_action.currentIndexChanged.connect(
            self._on_sub_not_found_action_changed
        )
        self._edit_sub_roi_btn.clicked.connect(self._on_pick_sub_roi)
        self._edit_action_type.currentIndexChanged.connect(self._on_action_type_changed)

        self._task_combo.currentTextChanged.connect(self._on_task_changed)
        self._task_new_btn.clicked.connect(self._on_task_new)
        self._task_rename_btn.clicked.connect(self._on_task_rename)
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

        existing_ids = {r.id for r in self._rules}
        rule_map = {r.id: r for r in self._rules}

        child_map: dict[str, list[str]] = {}
        assigned: set[str] = set()
        for r in self._rules:
            first_dep = next(
                (dep_id for dep_id in r.depends_on if dep_id in existing_ids and dep_id != r.id),
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
                text = f"[{'✓' if r.enabled else '✗'}] {r.name}"
                item.setText(0, text)
                item.setData(0, Qt.ItemDataRole.UserRole, r.id)
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
        if getattr(self, "_updating_status", False):
            return
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
            if not st["enabled"]:
                if st["auto_disabled"] or (
                    st["max_triggers"] > 0 and st["trigger_count"] >= st["max_triggers"]
                ):
                    suffix = " ❌"
            elif st["trigger_count"] > 0:
                elapsed_ms = (now - st["last_trigger_time"]) * 1000
                if elapsed_ms < st["cooldown_ms"]:
                    suffix = " ⏳"
                elif elapsed_ms < 2000:
                    suffix = " ✅"
            enabled = st["enabled"]
            base = f"[{'✓' if enabled else '✗'}] {st['name']}"
            if item.text(0) != base + suffix:
                item.setText(0, base + suffix)

        def _walk(item):
            _set_text(item)
            for j in range(item.childCount()):
                _walk(item.child(j))

        self._updating_status = True
        try:
            for i in range(self._rule_list.topLevelItemCount()):
                _walk(self._rule_list.topLevelItem(i))
        finally:
            self._updating_status = False

    def _has_cycle(self, rule_id: str, proposed_deps: list[str]) -> bool:
        adj: dict[str, list[str]] = {}
        for r in self._rules:
            if r.id == rule_id:
                adj[rule_id] = proposed_deps
            else:
                adj[r.id] = list(r.depends_on)

        visited: set[str] = set()
        stack: set[str] = set()

        def dfs(node: str) -> bool:
            if node in stack:
                return True
            if node in visited:
                return False
            visited.add(node)
            stack.add(node)
            for dep in adj.get(node, []):
                if dep in adj:
                    if dfs(dep):
                        return True
            stack.remove(node)
            return False

        for node in adj:
            if dfs(node):
                return True
        return False

    def _get_current_rule(self) -> Optional[Rule]:
        for r in self._rules:
            if r.id == self._selected_rule_id:
                return r
        return None

    def _on_rule_selected(self, current: QTreeWidgetItem, previous: QTreeWidgetItem):
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
        self._edit_action_type.setEnabled(True)
        self._edit_key.setEnabled(True)
        self._edit_post_delay.setEnabled(True)
        self._edit_depends_on_container.setEnabled(True)
        self._edit_roi_label.setEnabled(True)
        self._sub_toggle_btn.setEnabled(True)
        self._edit_sub_target.setEnabled(True)
        self._edit_sub_roi_btn.setEnabled(True)
        self._edit_sub_not_found_retries.setEnabled(True)
        self._edit_on_found_action.setEnabled(True)
        self._edit_on_found_pick_btn.setEnabled(True)
        self._edit_on_not_found_action.setEnabled(True)
        self._edit_on_not_found_pick_btn.setEnabled(True)
        self._clear_sub_btn.setEnabled(True)
        self._edit_name.setText(rule.name)
        self._edit_target.setText(rule.target_text)
        self._edit_enabled.setChecked(rule.enabled)
        self._edit_roi_label.setText(
            f"x={rule.roi['x']} y={rule.roi['y']} w={rule.roi['w']} h={rule.roi['h']}"
            if not all(rule.roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
            else "全視窗"
        )
        self._edit_cooldown.setValue(rule.cooldown_ms)
        self._edit_trigger_mode.setCurrentIndex(
            max(0, self._edit_trigger_mode.findData(rule.trigger_mode))
        )
        self._edit_click_button.setCurrentIndex(
            max(0, self._edit_click_button.findData(rule.click_button))
        )
        self._edit_click_position.setCurrentIndex(
            max(0, self._edit_click_position.findData(rule.click_position))
        )
        self._edit_coord_label.setText(f"X: {rule.custom_x}, Y: {rule.custom_y}")
        self._edit_fuzzy.setChecked(rule.fuzzy)
        self._edit_fuzzy_threshold.setValue(int(rule.fuzzy_threshold * 100))
        self._edit_max_triggers.setValue(rule.max_triggers)
        self._edit_random_offset.setValue(rule.random_offset)
        self._edit_post_delay.setValue(rule.post_delay_ms)
        self._edit_action_type.setCurrentIndex(
            max(0, self._edit_action_type.findData(rule.action_type))
        )
        idx = self._edit_key.findData(rule.key)
        self._edit_key.setCurrentIndex(idx if idx >= 0 else 0)
        self._populate_depends_on(rule)
        self._update_action_visibility()

        self._edit_sub_target.setText(rule.sub_target_text)
        has_sub_roi = any(rule.sub_roi.get(k, 0) != 0 for k in ("x", "y", "w", "h"))
        self._edit_sub_roi_label.setText(
            f"x={rule.sub_roi['x']} y={rule.sub_roi['y']} w={rule.sub_roi['w']} h={rule.sub_roi['h']}"
            if has_sub_roi
            else "與主目標相同"
        )
        self._edit_on_found_action.setCurrentIndex(
            max(0, self._edit_on_found_action.findData(rule.on_found_action))
        )
        self._edit_on_found_custom_label.setText(
            f"X: {rule.on_found_custom_x}, Y: {rule.on_found_custom_y}"
        )
        self._edit_on_not_found_action.setCurrentIndex(
            max(0, self._edit_on_not_found_action.findData(rule.on_not_found_action))
        )
        self._edit_on_not_found_custom_label.setText(
            f"X: {rule.on_not_found_custom_x}, Y: {rule.on_not_found_custom_y}"
        )
        self._edit_sub_not_found_retries.setValue(rule.sub_not_found_retries)
        self._update_sub_visibility()

    def _update_sub_visibility(self):
        self._sub_panel.setVisible(self._sub_toggle_btn.isChecked())
        self._on_found_coord_row.setVisible(
            self._edit_on_found_action.currentData() == "click_custom"
        )
        self._on_not_found_coord_row.setVisible(
            self._edit_on_not_found_action.currentData() == "click_custom"
        )

    def _toggle_sub_section(self):
        self._update_sub_visibility()
        self._sub_toggle_btn.setText(
            "▾ 進階條件 (二次確認)" if self._sub_toggle_btn.isChecked() else "▸ 進階條件 (二次確認)"
        )

    def _on_sub_found_action_changed(self, index: int):
        self._on_found_coord_row.setVisible(
            self._edit_on_found_action.currentData() == "click_custom"
        )

    def _on_sub_not_found_action_changed(self, index: int):
        self._on_not_found_coord_row.setVisible(
            self._edit_on_not_found_action.currentData() == "click_custom"
        )

    def _on_click_position_changed(self, index: int):
        is_key = self._edit_action_type.currentData() == "key"
        self._coord_row.setVisible(
            not is_key and self._edit_click_position.currentData() == "custom"
        )

    def _update_action_visibility(self):
        is_key = self._edit_action_type.currentData() == "key"
        self._edit_key.setVisible(is_key)
        self._edit_form.labelForField(self._edit_key).setVisible(is_key)
        self._edit_click_button.setVisible(not is_key)
        self._edit_form.labelForField(self._edit_click_button).setVisible(not is_key)
        self._edit_click_position.setVisible(not is_key)
        self._edit_form.labelForField(self._edit_click_position).setVisible(not is_key)
        is_custom = self._edit_click_position.currentData() == "custom"
        self._coord_row.setVisible(not is_key and is_custom)
        self._edit_form.labelForField(self._coord_row).setVisible(not is_key)
        self._edit_random_offset.setVisible(not is_key)
        self._edit_form.labelForField(self._edit_random_offset).setVisible(not is_key)

    def _on_action_type_changed(self, atype: str):
        self._update_action_visibility()

    def _get_excluded_deps(self, rule_id: str) -> set[str]:
        adj = {r.id: list(r.depends_on) for r in self._rules}

        def _reachable(start: str) -> set[str]:
            visited: set[str] = set()
            stack = [start]
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                for dep in adj.get(node, []):
                    if dep in adj and dep not in visited:
                        stack.append(dep)
            return visited

        excluded = {rule_id}
        for r in self._rules:
            if r.id != rule_id and rule_id in _reachable(r.id):
                excluded.add(r.id)
        return excluded

    def _populate_depends_on(self, rule: Rule):
        self._edit_depends_on.blockSignals(True)
        self._edit_depends_on.clear()
        dep_set = set(rule.depends_on)
        excluded = self._get_excluded_deps(rule.id)
        for r in self._rules:
            if r.id in excluded:
                continue
            item = QListWidgetItem(r.name)
            item.setData(Qt.ItemDataRole.UserRole, r.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if r.id in dep_set else Qt.CheckState.Unchecked
            )
            self._edit_depends_on.addItem(item)
        self._edit_depends_on.blockSignals(False)

    def _on_fuzzy_changed(self, state):
        self._edit_fuzzy_threshold.setEnabled(state == 2)

    def _on_enabled_changed(self, state):
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.enabled = state == 2
        save_task(self._current_task, self._rules)
        item = self._rule_list.currentItem()
        if item:
            text = f"[{'✓' if rule.enabled else '✗'}] {rule.name}"
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
        self._selected_rule_id = rule.id
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()

    def _delete_rule(self):
        if self._loop and self._loop.is_running:
            QMessageBox.warning(self, "提示", "請先停止偵測再刪除規則")
            return
        rule = self._get_current_rule()
        if rule is None:
            return
        dependents = [r for r in self._rules if rule.id in r.depends_on]
        msg = f"確定刪除規則「{rule.name}」？"
        if dependents:
            names = "、".join(f"「{r.name}」" for r in dependents)
            msg = (
                f"規則「{rule.name}」是下列規則的前置條件：\n{names}\n\n"
                f"刪除後將一併清除這些規則的前置條件。\n確定要刪除？"
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
        for r in self._rules:
            r.depends_on = [d for d in r.depends_on if d != rule.id]
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
        if (
            self._edit_click_position.currentData() == "custom"
            and rule.custom_x == 0
            and rule.custom_y == 0
        ):
            QMessageBox.warning(
                self,
                "無效規則",
                "點擊位置為「自訂座標」，但尚未選取有效座標。\n請點擊「選取點擊座標」設定位置。",
            )
            return
        rule.name = self._edit_name.text()
        rule.target_text = target
        rule.enabled = self._edit_enabled.isChecked()
        rule.cooldown_ms = self._edit_cooldown.value()
        rule.trigger_mode = self._edit_trigger_mode.currentData()
        rule.click_button = self._edit_click_button.currentData()
        rule.click_position = self._edit_click_position.currentData()
        rule.fuzzy = self._edit_fuzzy.isChecked()
        rule.fuzzy_threshold = self._edit_fuzzy_threshold.value() / 100.0
        rule.max_triggers = self._edit_max_triggers.value()
        rule.random_offset = self._edit_random_offset.value()
        rule.sub_target_text = self._edit_sub_target.text().strip()
        rule.on_found_action = self._edit_on_found_action.currentData()
        rule.on_not_found_action = self._edit_on_not_found_action.currentData()
        rule.sub_not_found_retries = self._edit_sub_not_found_retries.value()
        rule.post_delay_ms = self._edit_post_delay.value()
        rule.action_type = self._edit_action_type.currentData()
        rule.key = self._edit_key.currentData() or self._edit_key.currentText()
        rule.depends_on = [
            self._edit_depends_on.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._edit_depends_on.count())
            if self._edit_depends_on.item(i).checkState() == Qt.CheckState.Checked
        ]
        if self._has_cycle(rule.id, rule.depends_on):
            QMessageBox.warning(
                self,
                "循環依賴",
                "偵測到循環依賴！\n規則 A 依賴規則 B、規則 B 又依賴規則 A，將導致兩者永遠無法觸發。\n請取消勾選其中一項後再儲存。",
            )
            return
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
        self._edit_click_position.setCurrentIndex(
            max(0, self._edit_click_position.findData("custom"))
        )
        self._edit_coord_label.setText(f"X: {result[0]}, Y: {result[1]}")
        save_task(self._current_task, self._rules)
        self._edit_stack.setCurrentIndex(1)
        self._status_bar.showMessage(f"已選取點擊座標: X={result[0]}, Y={result[1]}")

    def _on_pick_sub_found_coord(self):
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
        rule.on_found_custom_x, rule.on_found_custom_y = result
        rule.on_found_action = "click_custom"
        self._edit_on_found_action.setCurrentIndex(
            max(0, self._edit_on_found_action.findData("click_custom"))
        )
        self._edit_on_found_custom_label.setText(f"X: {result[0]}, Y: {result[1]}")
        save_task(self._current_task, self._rules)
        self._edit_stack.setCurrentIndex(1)
        self._status_bar.showMessage(f"已選取確認觸發點擊座標: X={result[0]}, Y={result[1]}")

    def _on_pick_sub_not_found_coord(self):
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
        rule.on_not_found_custom_x, rule.on_not_found_custom_y = result
        rule.on_not_found_action = "click_custom"
        self._edit_on_not_found_action.setCurrentIndex(
            max(0, self._edit_on_not_found_action.findData("click_custom"))
        )
        self._edit_on_not_found_custom_label.setText(f"X: {result[0]}, Y: {result[1]}")
        save_task(self._current_task, self._rules)
        self._edit_stack.setCurrentIndex(1)
        self._status_bar.showMessage(f"已選取確認未找到點擊座標: X={result[0]}, Y={result[1]}")

    def _on_pick_sub_roi(self):
        rule = self._get_current_rule()
        if rule is None:
            return
        title = self._window_combo.currentText()
        if title:
            activate_window(title)
        mod = load_sibling("roi", "gui/07_gui_roi.py")
        result = mod.select_roi(parent_window=self)
        if not result:
            return
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
            rule.sub_roi = result
            self._edit_sub_roi_label.setText(
                f"x={result['x']} y={result['y']} w={result['w']} h={result['h']}"
            )
            save_task(self._current_task, self._rules)
        self._edit_stack.setCurrentIndex(1)
        self._status_bar.showMessage(
            f"已選取確認偵測區域: ({result['x']},{result['y']}) {result['w']}×{result['h']}"
        )

    def _on_clear_sub_target(self):
        rule = self._get_current_rule()
        if rule is None:
            return
        rule.sub_target_text = ""
        rule.sub_roi = {"x": 0, "y": 0, "w": 0, "h": 0}
        rule.sub_not_found_retries = 3
        rule.on_found_action = "click_sub_center"
        rule.on_found_custom_x = 0
        rule.on_found_custom_y = 0
        rule.on_not_found_action = "click_nothing"
        rule.on_not_found_custom_x = 0
        rule.on_not_found_custom_y = 0
        save_task(self._current_task, self._rules)
        if self._loop:
            self._loop.reload_rules()
        self._sub_toggle_btn.setChecked(False)
        self._sub_toggle_btn.setText("▸ 進階條件 (二次確認)")
        self._show_rule_detail(rule)
        self._status_bar.showMessage(f"已清除規則「{rule.name}」的進階條件設定")

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
        self._selected_rule_id = rule.id
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()
        self._main_stack.setCurrentIndex(0)
        self._debug_btn.setText("OCR 診斷")
        self._status_bar.showMessage(f"已從 OCR 診斷新增規則：「{rule_data['target_text']}」")

    def _on_debug_sub_target_requested(self, data: dict):
        rule = self._get_current_rule()
        if rule is None:
            QMessageBox.warning(self, "無效操作", "請先在規則列表中選取一個規則，再設定進階條件。")
            return
        rule.sub_target_text = str(data.get("target_text", "")).strip()
        if not rule.sub_target_text:
            return
        roi = data.get("roi")
        if roi:
            rule.sub_roi = roi
        save_task(self._current_task, self._rules)
        self._refresh_rule_list()
        if self._loop:
            self._loop.reload_rules()
        self._main_stack.setCurrentIndex(0)
        self._debug_btn.setText("OCR 診斷")
        self._sub_toggle_btn.setChecked(True)
        self._sub_toggle_btn.setText("▾ 進階條件 (二次確認)")
        self._show_rule_detail(rule)
        self._status_bar.showMessage(f"已在當前規則設定進階條件：「{rule.sub_target_text}」")

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
            self._edit_roi_label.setEnabled(False)
            self._edit_name.setEnabled(False)
            self._edit_target.setEnabled(False)
            self._edit_enabled.setEnabled(False)
            self._edit_cooldown.setEnabled(False)
            self._edit_trigger_mode.setEnabled(False)
            self._edit_action_type.setEnabled(False)
            self._edit_key.setEnabled(False)
            self._edit_click_button.setEnabled(False)
            self._edit_click_position.setEnabled(False)
            self._edit_pick_coord_btn.setEnabled(False)
            self._edit_fuzzy.setEnabled(False)
            self._edit_fuzzy_threshold.setEnabled(False)
            self._edit_max_triggers.setEnabled(False)
            self._edit_random_offset.setEnabled(False)
            self._edit_post_delay.setEnabled(False)
            self._edit_depends_on_container.setEnabled(False)
            self._sub_toggle_btn.setEnabled(False)
            self._edit_sub_target.setEnabled(False)
            self._edit_sub_roi_btn.setEnabled(False)
            self._edit_sub_not_found_retries.setEnabled(False)
            self._edit_on_found_action.setEnabled(False)
            self._edit_on_found_pick_btn.setEnabled(False)
            self._edit_on_not_found_action.setEnabled(False)
            self._edit_on_not_found_pick_btn.setEnabled(False)
            self._clear_sub_btn.setEnabled(False)

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
        self._status_timer.stop()
        if self._loop is None:
            return
        self._loop.emergency_stop()
        self._loop = None
        self._btn_toggle.setText("啟動")
        self._update_edit_enabled(True)
        self._status_bar.showMessage("🛑 緊急停止 — 按「啟動」重新開始")
        self._log_widget.append_info("緊急停止（F12）")
        self._update_rule_status()

    def _on_ocr_health(self, msg: str):
        self._log_widget.append_warning(f"{msg}")

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
