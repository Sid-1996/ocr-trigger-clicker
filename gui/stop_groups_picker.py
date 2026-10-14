from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from _loader import load_sibling
from i18n import T

_group_models = load_sibling("rule_models", "core/rule_models.py")
group_display_name = _group_models.group_display_name


class StopGroupsPicker(QWidget):
    def __init__(self, groups_provider=None, selected=None):
        super().__init__()
        self._groups_provider = groups_provider or (lambda: [])
        self._selected: list[str] = list(selected or [])
        self._layout_ = QHBoxLayout(self)
        self._layout_.setContentsMargins(0, 0, 0, 0)
        self._btn = QPushButton()
        self._btn.setFlat(True)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet(
            "QPushButton { text-align: left; border: 1px solid #ccc; "
            "padding: 4px 8px; min-height: 28px; }"
        )
        self._btn.clicked.connect(self._open_dialog)
        self._layout_.addWidget(self._btn)
        self._update_display()

    def _get_groups(self) -> list:
        raw = self._groups_provider()
        return [
            {
                "id": g.get("id", "") if isinstance(g, dict) else g.id,
                "name": group_display_name(g),
            }
            for g in raw
        ]

    def _name_for_id(self, gid: str) -> str:
        for g in self._get_groups():
            if g["id"] == gid:
                return g["name"]
        return gid

    def _update_display(self):
        names = [self._name_for_id(gid) for gid in self._selected]
        if not names:
            self._btn.setText(T("ui.no_group"))
            self._btn.setStyleSheet(
                "QPushButton { text-align: left; border: 1px solid #ccc; "
                "padding: 4px 8px; min-height: 28px; color: #888; }"
            )
        else:
            visible = names[:3]
            parts = [f"[{n}]" for n in visible]
            rest = len(names) - 3
            if rest > 0:
                parts.append(f"[+{rest}]")
            self._btn.setText(" ".join(parts))
            self._btn.setStyleSheet(
                "QPushButton { text-align: left; border: 1px solid #ccc; "
                "padding: 4px 8px; min-height: 28px; }"
            )
        if names:
            self._btn.setToolTip(
                T("tooltip.stop_group_selected", names="\n".join(f"• {n}" for n in names))
            )
        else:
            self._btn.setToolTip(T("tooltip.stop_group_none"))

    def _open_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(T("ui.select_stop_group"))
        dialog.setMinimumWidth(320)
        dialog.setMinimumHeight(400)
        layout = QVBoxLayout(dialog)

        search = QLineEdit()
        search.setPlaceholderText(T("ui.search_groups"))
        layout.addWidget(search)

        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        groups = self._get_groups()
        for g in groups:
            item = QListWidgetItem(g["name"])
            item.setData(Qt.ItemDataRole.UserRole, g["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if g["id"] in self._selected else Qt.CheckState.Unchecked
            )
            list_widget.addItem(item)
        list_widget.itemClicked.connect(
            lambda item: item.setCheckState(
                Qt.CheckState.Unchecked
                if item.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
        )
        layout.addWidget(list_widget)

        def _filter(text: str):
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                item.setHidden(text.lower() not in item.text().lower())

        search.textChanged.connect(_filter)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(T("ui.confirm"))
        cancel_btn = QPushButton(T("ui.cancel"))
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        def _accept():
            self._selected = [
                list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(list_widget.count())
                if list_widget.item(i).checkState() == Qt.CheckState.Checked
            ]
            self._update_display()
            dialog.accept()

        ok_btn.clicked.connect(_accept)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def selected_ids(self) -> list[str]:
        return list(self._selected)
