from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _loader import load_sibling

_mod = load_sibling("main_loop", "05_main_loop.py")
TriggerLog = _mod.TriggerLog

MAX_ROWS = 500
COL_TIME = 0
COL_RULE = 1
COL_TEXT = 2
COL_CLICK = 3

_COLORS = {
    "bg_odd": QColor(245, 245, 245),
    "bg_even": QColor(255, 255, 255),
    "error_fg": QColor(200, 40, 40),
    "error_bg": QColor(255, 235, 235),
}


class _LogSignals(QObject):
    new_trigger = pyqtSignal(object)
    new_error = pyqtSignal(str)


class LogWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._signals = _LogSignals()
        self._signals.new_trigger.connect(self._insert_trigger)
        self._signals.new_error.connect(self._insert_error)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("偵測日誌"))
        toolbar.addStretch()
        self._clear_btn = QPushButton("清除")
        self._export_btn = QPushButton("匯出 .txt")
        self._auto_scroll_cb = QCheckBox("自動捲動")
        self._auto_scroll_cb.setChecked(True)
        toolbar.addWidget(self._clear_btn)
        toolbar.addWidget(self._export_btn)
        toolbar.addWidget(self._auto_scroll_cb)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["時間", "規則名稱", "觸發文字", "點擊座標"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setMaximumHeight(200)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(COL_TIME, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_RULE, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_TEXT, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_CLICK, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(COL_TIME, 100)
        self._table.setColumnWidth(COL_RULE, 150)
        self._table.setColumnWidth(COL_TEXT, 150)
        self._table.setColumnWidth(COL_CLICK, 120)

        layout.addWidget(self._table)

        self._empty_hint = QLabel("偵測記錄會在此顯示")
        self._empty_hint.setStyleSheet("color: #aaa; font-size: 11px; padding: 2px 0;")
        layout.addWidget(self._empty_hint)

        self._clear_btn.clicked.connect(self._on_clear)
        self._export_btn.clicked.connect(self._on_export)

    def append_trigger(self, log: TriggerLog) -> None:
        self._signals.new_trigger.emit(log)

    def append_error(self, message: str) -> None:
        self._signals.new_error.emit(message)

    def clear(self) -> None:
        self._table.setRowCount(0)
        self._empty_hint.show()

    def export_txt(self, path: str) -> bool:
        try:
            with open(path, "w", encoding="utf-8") as f:
                for row in range(self._table.rowCount()):
                    parts = []
                    for col in range(4):
                        item = self._table.item(row, col)
                        parts.append(item.text() if item else "")
                    f.write("\t".join(parts) + "\n")
            return True
        except OSError:
            return False

    def _trim(self):
        while self._table.rowCount() > MAX_ROWS:
            self._table.removeRow(0)

    def _mkitem(self, text: str, fg: Optional[QColor] = None, bg: Optional[QColor] = None):
        item = QTableWidgetItem(text)
        if fg:
            item.setForeground(fg)
        if bg:
            item.setBackground(bg)
        return item

    def _insert_trigger(self, log: TriggerLog):
        self._empty_hint.hide()
        ts = datetime.fromtimestamp(log.timestamp).strftime("%H:%M:%S")
        click = f"({log.click_x}, {log.click_y})"
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, COL_TIME, self._mkitem(ts))
        self._table.setItem(row, COL_RULE, self._mkitem(log.rule_name))
        self._table.setItem(row, COL_TEXT, self._mkitem(log.matched_text))
        self._table.setItem(row, COL_CLICK, self._mkitem(click))

        bg = _COLORS["bg_odd"] if row % 2 else _COLORS["bg_even"]
        for col in range(4):
            self._table.item(row, col).setBackground(bg)

        self._trim()
        if self._auto_scroll_cb.isChecked():
            self._table.scrollToBottom()

    def _insert_error(self, message: str):
        self._empty_hint.hide()
        ts = datetime.now().strftime("%H:%M:%S")
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(
            row, COL_TIME, self._mkitem(ts, fg=_COLORS["error_fg"], bg=_COLORS["error_bg"])
        )
        self._table.setItem(
            row, COL_RULE, self._mkitem("⚠ 錯誤", fg=_COLORS["error_fg"], bg=_COLORS["error_bg"])
        )
        self._table.setItem(
            row, COL_TEXT, self._mkitem(message, fg=_COLORS["error_fg"], bg=_COLORS["error_bg"])
        )
        self._table.setItem(
            row, COL_CLICK, self._mkitem("—", fg=_COLORS["error_fg"], bg=_COLORS["error_bg"])
        )

        self._trim()
        if self._auto_scroll_cb.isChecked():
            self._table.scrollToBottom()

    def _on_clear(self):
        if self._table.rowCount() == 0:
            return
        if (
            QMessageBox.question(
                self,
                "清除日誌",
                "確定要清除所有日誌記錄嗎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.clear()

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "匯出日誌", str(Path(__file__).parent / "trigger_log.txt"), "文字檔 (*.txt)"
        )
        if not path:
            return
        if not self.export_txt(path):
            QMessageBox.critical(self, "匯出失敗", "無法寫入檔案")


if __name__ == "__main__":
    import sys
    from pathlib import Path

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    w = QWidget()
    w.setWindowTitle("LogWidget 測試")
    layout = QVBoxLayout(w)
    log_widget = LogWidget()
    layout.addWidget(log_widget)
    w.resize(600, 350)
    w.show()

    from time import time

    for i in range(5):
        log = TriggerLog(
            timestamp=time(),
            rule_id=f"rule_{i}",
            rule_name=f"規則{i + 1}",
            matched_text=f"文字{i + 1}",
            click_x=100 + i * 50,
            click_y=200 + i * 30,
        )
        log_widget.append_trigger(log)

    log_widget.append_error("視窗已關閉，無法截圖")

    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w")
    tmp.close()
    ok = log_widget.export_txt(tmp.name)
    with open(tmp.name, encoding="utf-8") as f:
        content = f.read()
    Path(tmp.name).unlink()

    print(f"匯出結果: {ok}")
    print(f"匯出內容:\n{content}")
    sys.exit(app.exec())
