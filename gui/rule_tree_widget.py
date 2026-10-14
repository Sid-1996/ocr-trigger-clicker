from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QTreeWidget


class RuleTreeWidget(QTreeWidget):
    reordered = pyqtSignal()

    def dropEvent(self, event):
        src = self.currentItem()
        if src is None:
            event.ignore()
            return
        src_data = src.data(0, Qt.ItemDataRole.UserRole)
        indicator = self.dropIndicatorPosition()
        target_item = self.itemAt(event.position().toPoint())

        # ── 通用攔截：src=rule 且 target=rule，一律手動插為 sibling ──
        if target_item and src_data and src_data[0] == "rule":
            tgt_data = target_item.data(0, Qt.ItemDataRole.UserRole)
            if tgt_data and tgt_data[0] == "rule":
                if src == target_item:
                    event.ignore()
                    return
                parent = target_item.parent()
                if parent is None:
                    event.ignore()
                    return
                target_idx = parent.indexOfChild(target_item)

                if indicator == QAbstractItemView.DropIndicatorPosition.AboveItem:
                    insert_pos = target_idx
                elif indicator == QAbstractItemView.DropIndicatorPosition.BelowItem:
                    insert_pos = target_idx + 1
                else:
                    rect = self.visualItemRect(target_item)
                    mouse_y = event.position().toPoint().y()
                    insert_pos = (
                        target_idx
                        if mouse_y < (rect.top() + rect.height() // 2)
                        else target_idx + 1
                    )

                old_parent = src.parent()
                if old_parent is None:
                    event.ignore()
                    return
                old_idx = old_parent.indexOfChild(src)
                taken = old_parent.takeChild(old_idx)
                if old_parent == parent and old_idx < insert_pos:
                    insert_pos -= 1
                insert_pos = max(0, min(insert_pos, parent.childCount()))
                parent.insertChild(insert_pos, taken)
                self.setCurrentItem(taken)
                self.reordered.emit()
                event.setDropAction(Qt.DropAction.IgnoreAction)
                event.accept()
                return

        # ── OnItem：rule → bg_group/group ──
        if indicator == QAbstractItemView.DropIndicatorPosition.OnItem:
            if src_data and src_data[0] == "rule" and target_item:
                tgt_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                if tgt_data and tgt_data[0] == "bg_group":
                    event.ignore()
                    return
                if tgt_data and tgt_data[0] == "group":
                    super().dropEvent(event)
                    self.reordered.emit()
                    return
            event.ignore()
            return

        if not src_data or src_data[0] != "rule":
            super().dropEvent(event)
            self.reordered.emit()
            return

        # 不該進到這裡（規則的 Above/Below 已被上方攔截）
        super().dropEvent(event)
        self.reordered.emit()

    def dragMoveEvent(self, event):
        src = self.currentItem()
        if src is None:
            event.ignore()
            return
        src_data = src.data(0, Qt.ItemDataRole.UserRole)

        if src_data and src_data[0] == "group":
            pos = event.position().toPoint()
            target = self.itemAt(pos)
            if target:
                if target.parent():
                    event.ignore()
                    return
                if self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.OnItem:
                    event.ignore()
                    return
        super().dragMoveEvent(event)
