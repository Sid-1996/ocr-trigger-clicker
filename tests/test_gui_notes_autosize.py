"""備註欄隨內容自動長高：短備註維持 60px、長備註最高 240px。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from _loader import load_sibling  # noqa: E402

_gui = load_sibling("gui_main", "gui/06_gui_main.py")


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_notes_height_clamp():
    assert _gui._notes_height(20) == 60
    assert _gui._notes_height(100) == 110
    assert _gui._notes_height(1000) == 240


def test_notes_editor_height_follows_document(qapp):
    from PyQt6.QtWidgets import QPlainTextEdit

    def height(editor):
        return _gui._notes_height(_gui._notes_doc_height(editor.document()) + 12)

    ed = QPlainTextEdit()
    ed.setPlainText("短備註")
    assert height(ed) == 60

    ed.setPlainText("\n".join(f"第{i}行 選項獎勵 力量+10 體力+20" for i in range(12)))
    assert 60 < height(ed) <= 240

    ed.setPlainText("\n".join(f"第{i}行" for i in range(40)))
    assert height(ed) == 240
    ed.deleteLater()
