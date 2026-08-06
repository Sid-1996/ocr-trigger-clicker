import os
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from _loader import load_sibling
from i18n import T

_log_cfg = load_sibling("logging_config", "core/00_logging_config.py")

_MAX_LINES = 500
_REFRESH_MS = 1500
_FOLLOW_TOLERANCE = 20


class LogViewer(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("log_viewer.title"))
        self.resize(780, 520)

        self._log_path: Path = _log_cfg.get_log_dir() / "app.log"
        self._last_text = ""

        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(T("log_viewer.search_placeholder"))
        self._search_edit.textChanged.connect(self._refresh)
        toolbar.addWidget(self._search_edit, 1)

        self._debug_toggle = QCheckBox(T("log_viewer.debug_toggle"))
        self._debug_toggle.setChecked(_log_cfg.is_debug_enabled())
        self._debug_toggle.toggled.connect(self._on_debug_toggled)
        toolbar.addWidget(self._debug_toggle)

        self._open_dir_btn = QPushButton(T("log_viewer.open_dir"))
        self._open_dir_btn.clicked.connect(self._open_dir)
        toolbar.addWidget(self._open_dir_btn)

        self._clear_btn = QPushButton(T("log_viewer.clear"))
        self._clear_btn.clicked.connect(self._on_clear)
        toolbar.addWidget(self._clear_btn)
        layout.addLayout(toolbar)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setMaximumBlockCount(_MAX_LINES)
        layout.addWidget(self._text)

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

        self._refresh()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)

    def _on_debug_toggled(self, enabled: bool):
        _log_cfg.set_debug(enabled)
        self._refresh()

    def _open_dir(self):
        os.startfile(self._log_path.parent)

    def _on_clear(self):
        answer = QMessageBox.question(
            self,
            T("log_viewer.title"),
            T("log_viewer.clear_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        _log_cfg.clear_log_file()
        self._refresh()

    def _tail_lines(self) -> list[str]:
        try:
            with open(self._log_path, "r", encoding="utf-8", errors="replace") as f:
                return f.readlines()[-_MAX_LINES:]
        except OSError:
            return []

    def _refresh(self):
        query = self._search_edit.text().strip().lower()

        lines = self._tail_lines()
        if query:
            lines = [line for line in lines if query in line.lower()]

        new_text = "".join(lines)
        if new_text == self._last_text:
            return

        bar = self._text.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - _FOLLOW_TOLERANCE
        saved = bar.value()

        self._text.setPlainText(new_text)
        self._last_text = new_text

        if lines:
            bar.setValue(bar.maximum() if at_bottom else min(saved, bar.maximum()))


if __name__ == "__main__":
    _log_cfg.set_debug(False)
    _log_cfg.set_debug(True)
    assert _log_cfg.get_logger("log_viewer").getEffectiveLevel() == 10
    assert callable(_log_cfg.clear_log_file)
    _log_cfg.set_debug(False)
    v = LogViewer.__new__(LogViewer)
    v._log_path = _log_cfg.get_log_dir() / "app.log"
    lines = v._tail_lines()
    assert isinstance(lines, list)
    print("log_viewer self-check passed")
