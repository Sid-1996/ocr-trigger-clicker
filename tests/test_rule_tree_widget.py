import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtWidgets import QAbstractItemView, QApplication, QTreeWidgetItem

from _loader import load_sibling

_APP = QApplication.instance() or QApplication([])
RuleTreeWidget = load_sibling("rule_tree_widget", "gui/rule_tree_widget.py").RuleTreeWidget


class _DropEvent:
    def __init__(self, y=0):
        self._pos = QPointF(0, y)
        self.ignored = False
        self.accepted = False
        self.drop_action = None

    def position(self):
        return self._pos

    def ignore(self):
        self.ignored = True

    def accept(self):
        self.accepted = True

    def setDropAction(self, action):
        self.drop_action = action


class _Tree(RuleTreeWidget):
    def __init__(self, indicator, target=None):
        super().__init__()
        self.indicator = indicator
        self.target = target

    def dropIndicatorPosition(self):
        return self.indicator

    def itemAt(self, _pos):
        return self.target


def _item(kind, item_id):
    item = QTreeWidgetItem([item_id])
    item.setData(0, Qt.ItemDataRole.UserRole, (kind, item_id))
    return item


def test_drop_rule_below_sibling_reorders_and_emits_signal():
    tree = _Tree(QAbstractItemView.DropIndicatorPosition.BelowItem)
    group = _item("group", "g")
    source, middle, target = (_item("rule", item_id) for item_id in ("a", "b", "c"))
    tree.addTopLevelItem(group)
    group.addChildren([source, middle, target])
    tree.setCurrentItem(source)
    tree.target = target
    emitted = []
    tree.reordered.connect(lambda: emitted.append(True))
    event = _DropEvent(y=10)

    tree.dropEvent(event)

    assert [group.child(i).text(0) for i in range(group.childCount())] == ["b", "c", "a"]
    assert tree.currentItem() is source
    assert emitted == [True]
    assert event.accepted and not event.ignored
    assert event.drop_action == Qt.DropAction.IgnoreAction
    tree.deleteLater()


def test_drop_rule_onto_background_group_is_rejected():
    tree = _Tree(QAbstractItemView.DropIndicatorPosition.OnItem)
    group = _item("group", "g")
    source = _item("rule", "a")
    background = _item("bg_group", "__background__")
    tree.addTopLevelItem(group)
    group.addChild(source)
    tree.addTopLevelItem(background)
    tree.setCurrentItem(source)
    tree.target = background
    emitted = []
    tree.reordered.connect(lambda: emitted.append(True))
    event = _DropEvent()

    tree.dropEvent(event)

    assert event.ignored and not event.accepted
    assert group.child(0) is source
    assert emitted == []
    tree.deleteLater()


def test_group_drag_over_child_is_rejected():
    tree = _Tree(QAbstractItemView.DropIndicatorPosition.AboveItem)
    group = _item("group", "g")
    child = _item("rule", "a")
    group.addChild(child)
    tree.addTopLevelItem(group)
    tree.setCurrentItem(group)
    tree.target = child
    event = _DropEvent()

    tree.dragMoveEvent(event)

    assert event.ignored
    tree.deleteLater()
