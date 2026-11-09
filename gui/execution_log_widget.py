from PyQt6.QtCore import Qt, pyqtSignal
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
    # 定位請求：(任務名, 規則 id, 步驟 idx, 規則名)。
    # 舊日誌無 rule_id 時 rule_id 為 ""，由主視窗顯示無法定位的訊息。
    # step_idx < 0 或 step_type 為 completed/preflight/background 時僅定位規則。
    locate_requested = pyqtSignal(str, str, int, str)

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
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table)
        self._rendered: list[dict] = []

    _RESULT_KEYS = {
        "ok": "exec_log.result.ok",
        "stop": "exec_log.result.stop",
        "jump": "exec_log.result.jump",
        "wait": "exec_log.result.wait",
        "completed": "exec_log.result.completed",
        "triggered": "exec_log.result.triggered",
        "blocked": "exec_log.result.blocked",
    }

    def _populate(self, entries: list[dict]):
        # 只補上新增的尾端列。日誌為 deque(maxlen=50) 且每 500ms 全量傳入，
        # 全量重建（每列 5 個 QTableWidgetItem + ResizeToContents 重算）曾讓
        # GUI 執行緒吃掉整個行程的 GIL，主循環被餓死（實測 217ms/幀 → 574ms/幀）。
        # deque 滾出前端時改走滑動窗口對齊，避免整表重建。
        n = len(self._rendered)
        keep = 0
        while keep < n and keep < len(entries) and self._rendered[keep] == entries[keep]:
            keep += 1
        if keep == 0 and n > 0 and len(entries) > 0:
            max_ov = min(n, len(entries))
            for ov in range(max_ov, 0, -1):
                if self._rendered[n - ov :] == entries[:ov]:
                    for _ in range(n - ov):
                        self._table.removeRow(0)
                    del self._rendered[: n - ov]
                    keep = ov
                    break
        if keep < len(self._rendered):
            self._table.setRowCount(keep)
            del self._rendered[keep:]
        added = len(entries) - keep
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
                if col == 1:
                    # 規則欄存定位識別（同名規則以 id 區分；舊日誌無 id 存空字串）。
                    # 完成／預檢／常駐類日誌無對應步驟，step_idx 記 -1 → 僅定位規則，
                    # 不假裝能定位到步驟。
                    _locate_step = (
                        step_idx
                        if step_type not in ("completed", "preflight", "background")
                        else -1
                    )
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        (
                            e.get("task", ""),
                            e.get("rule_id", ""),
                            _locate_step,
                            e.get("rule_name", ""),
                        ),
                    )
                    if e.get("rule_id"):
                        item.setToolTip(T("exec_log.locate_hint"))
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
        # 僅在有新增列且使用者在底部附近時才捲動，避免打斷瀏覽歷史
        if entries and added > 0:
            sb = self._table.verticalScrollBar()
            if sb is not None and sb.value() >= sb.maximum() - 20:
                self._table.scrollToBottom()

    def _on_cell_clicked(self, row: int, _col: int):
        """點擊日誌列 → 請求主視窗定位到對應規則／步驟。

        不改變原有選取行為（選取仍由 QTableWidget 處理），只發射訊號。
        無 rule_id 的舊日誌仍發射（rule_id=""），由主視窗顯示無法定位訊息。
        """
        if row < 0 or row >= self._table.rowCount():
            return
        item = self._table.item(row, 1)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        task, rule_id, step_idx, rule_name = data
        self.locate_requested.emit(task, rule_id, step_idx, rule_name)

    def _clear(self):
        self._table.setRowCount(0)
        self._rendered.clear()
        cb = getattr(self, "_on_clear", None)
        if callable(cb):
            try:
                cb()
            except Exception:
                pass


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

    # 定位訊號：含 rule_id 的列可定位；舊日誌（無 rule_id）仍發射空 id
    got = []
    w.locate_requested.connect(lambda t, rid, si, rn: got.append((t, rid, si, rn)))

    def loc_entry(ts, rule_id="", task="任務A", step_idx=1, step_type="detect"):
        return {
            "ts": ts,
            "rule_name": "同名規則",
            "rule_id": rule_id,
            "task": task,
            "step_idx": step_idx,
            "step_type": step_type,
            "result": "stop",
            "detail": "",
        }

    w._clear()
    w._populate(
        [
            loc_entry("10:00:00", rule_id="r-id-1", step_idx=2),
            loc_entry("10:00:01", rule_id="r-id-2", step_idx=-1, step_type="completed"),
            loc_entry("10:00:02"),  # 舊日誌：無 rule_id
        ]
    )
    w._on_cell_clicked(0, 1)
    assert got[-1] == ("任務A", "r-id-1", 2, "同名規則"), got
    print("  [OK] 點擊有 id 的日誌列發射定位訊號（含步驟 idx）")
    w._on_cell_clicked(1, 1)
    assert got[-1] == ("任務A", "r-id-2", -1, "同名規則"), got
    print("  [OK] 完成類日誌僅定位規則（step_idx=-1）")
    w._on_cell_clicked(2, 1)
    assert got[-1] == ("任務A", "", 1, "同名規則"), got
    print("  [OK] 舊日誌點擊發射空 rule_id（由主視窗提示無法定位）")

    print("\n=== All ExecutionLogWidget checks passed ===")
    raise SystemExit(0)
