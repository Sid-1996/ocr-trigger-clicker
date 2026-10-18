import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

from _loader import load_sibling
from i18n import T

_APP = QApplication.instance() or QApplication([])
ExecutionLogWidget = load_sibling(
    "execution_log_widget", "gui/execution_log_widget.py"
).ExecutionLogWidget


def test_populate_formats_entries_and_clear_removes_rows():
    widget = ExecutionLogWidget()
    widget._populate(
        [
            {
                "ts": "12:00",
                "rule_name": "Click start",
                "step_idx": 0,
                "step_type": "click",
                "result": "ok",
                "detail": "clicked",
            },
            {
                "ts": "12:01",
                "rule_name": "Task",
                "step_idx": -1,
                "step_type": "completed",
                "result": "completed",
                "detail": "",
            },
        ]
    )

    assert widget._table.rowCount() == 2
    assert [widget._table.item(0, col).text() for col in range(5)] == [
        "12:00",
        "Click start",
        f"{T('exec_log.type.step')} 1 {T('exec_log.type.click')}",
        T("exec_log.result.ok"),
        "clicked",
    ]
    assert widget._table.item(0, 3).foreground().color().getRgb() == (0, 160, 0, 255)
    assert widget._table.item(1, 2).text() == T("exec_log.type.completed")
    assert widget._table.item(1, 3).text() == T("exec_log.result.completed")

    widget._clear()
    assert widget._table.rowCount() == 0
    widget.deleteLater()


def _entry(ts, rule_name="A"):
    return {
        "ts": ts,
        "rule_name": rule_name,
        "step_idx": 0,
        "step_type": "click",
        "result": "ok",
        "detail": "",
    }


def test_populate_reuses_existing_rows_when_unchanged():
    """全量重建（每 500ms 重建 50 列）曾拖垮主循環 GIL，見 TECHNICAL.md「GIL 凍結兩案」。
    以 item 物件身分把關：重複相同資料、或尾端追加時，既有列不得被重建。"""
    widget = ExecutionLogWidget()
    rows = [_entry("12:00"), _entry("12:01", "B")]
    widget._populate(rows)
    first = widget._table.item(0, 0)
    assert first is not None

    widget._populate(list(rows))
    assert widget._table.rowCount() == 2
    assert widget._table.item(0, 0) is first

    widget._populate(rows + [_entry("12:02", "C")])
    assert widget._table.rowCount() == 3
    assert widget._table.item(0, 0) is first
    assert widget._table.item(2, 1).text() == "C"

    widget._populate(rows[1:])
    assert widget._table.rowCount() == 1
    assert widget._table.item(0, 1).text() == "B"
    widget.deleteLater()
