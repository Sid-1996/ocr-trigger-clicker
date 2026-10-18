from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from i18n import T


class ExecutionLogWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._title_label = QLabel(T("exec_log.title"))
        self._title_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        header.addWidget(self._title_label)
        header.addStretch()
        self._clear_btn = QPushButton(T("exec_log.clear"))
        self._clear_btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self._clear_btn.clicked.connect(self._clear)
        header.addWidget(self._clear_btn)
        layout.addLayout(header)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            [
                T("exec_log.col_time"),
                T("exec_log.col_rule"),
                T("exec_log.col_step"),
                T("exec_log.col_result"),
                T("exec_log.col_detail"),
            ]
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setMaximumHeight(150)
        hdr_view = self._table.horizontalHeader()
        hdr_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.setStyleSheet(
            "QTableWidget { font-size: 11px; }QTableWidget::item { padding: 2px 4px; }"
        )
        layout.addWidget(self._table)
        self._rendered: list[dict] = []

    _RESULT_KEYS = {
        "ok": "exec_log.result.ok",
        "stop": "exec_log.result.stop",
        "jump": "exec_log.result.jump",
        "wait": "exec_log.result.wait",
        "completed": "exec_log.result.completed",
        "triggered": "exec_log.result.triggered",
    }

    def _populate(self, entries: list[dict]):
        # 只補上新增的尾端列。日誌為 deque(maxlen=50) 且每 500ms 全量傳入，
        # 全量重建（每列 5 個 QTableWidgetItem + ResizeToContents 重算）曾讓
        # GUI 執行緒吃掉整個行程的 GIL，主循環被餓死（實測 217ms/幀 → 574ms/幀）。
        n = len(self._rendered)
        keep = 0
        while keep < n and keep < len(entries) and self._rendered[keep] == entries[keep]:
            keep += 1
        if keep < n:
            self._table.setRowCount(keep)
            del self._rendered[keep:]
        self._table.setRowCount(len(entries))
        for row in range(keep, len(entries)):
            e = entries[row]
            result = e.get("result", "")
            result_label = T(self._RESULT_KEYS.get(result, result))
            detail = e.get("detail", "")
            step_idx = e.get("step_idx", 0)
            step_type = e.get("step_type", "")
            if step_idx < 0 or step_type in ("completed", "background"):
                step_label = T(f"exec_log.type.{step_type}")
            else:
                step_label = (
                    f"{T('exec_log.type.step')} {step_idx + 1} {T(f'exec_log.type.{step_type}')}"
                )
            items = [
                e.get("ts", ""),
                e.get("rule_name", ""),
                step_label,
                result_label,
                detail,
            ]
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                if result == "ok":
                    item.setForeground(QColor(0, 160, 0))
                elif result in ("completed", "triggered"):
                    item.setForeground(QColor(0, 130, 80))
                elif result == "stop":
                    item.setForeground(QColor(220, 50, 50))
                elif result == "jump":
                    item.setForeground(QColor(80, 120, 200))
                elif result == "wait":
                    item.setForeground(QColor(140, 140, 140))
                self._table.setItem(row, col, item)
            self._rendered.append(e)
        if entries:
            self._table.scrollToBottom()

    def _clear(self):
        self._table.setRowCount(0)
        self._rendered.clear()


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from PyQt6.QtWidgets import QApplication

    app = QApplication([])
    w = ExecutionLogWidget()

    def entry(ts, result="ok", step_idx=0, step_type="detect"):
        return {
            "ts": ts,
            "rule_name": "測試規則",
            "step_idx": step_idx,
            "step_type": step_type,
            "result": result,
            "detail": "",
        }

    one = [entry("1")]
    w._populate(one)
    assert w._table.rowCount() == 1, w._table.rowCount()
    print("  [OK] 初次填入 1 列")

    two = one + [entry("2", "completed", -1, "completed")]
    w._populate(two)
    assert w._table.rowCount() == 2, w._table.rowCount()
    assert w._table.item(0, 0).text() == "1", w._table.item(0, 0).text()
    assert w._table.item(1, 0).text() == "2", w._table.item(1, 0).text()
    print("  [OK] 增量附加保留既有列")

    w._populate(two)
    assert w._table.rowCount() == 2, w._table.rowCount()
    assert w._table.item(0, 0).text() == "1", w._table.item(0, 0).text()
    print("  [OK] 內容未變不動既有列")

    w._populate(two[1:])
    assert w._table.rowCount() == 1, w._table.rowCount()
    assert w._table.item(0, 0).text() == "2", w._table.item(0, 0).text()
    print("  [OK] 前端被丟棄（deque maxlen）時截斷")

    w._clear()
    assert w._table.rowCount() == 0, w._table.rowCount()
    w._populate(two)
    assert w._table.rowCount() == 2, w._table.rowCount()
    assert w._table.item(0, 0).text() == "1", w._table.item(0, 0).text()
    print("  [OK] 清除後可重新填入")

    print("\n=== All ExecutionLogWidget checks passed ===")
    raise SystemExit(0)
