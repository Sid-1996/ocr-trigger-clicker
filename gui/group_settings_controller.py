from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from i18n import T


class GroupSettingsController:
    def show(self, win):
        item = win._rule_list.currentItem()
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "group":
            return
        gid = data[1]
        group = next((g for g in win._groups if g.id == gid), None)
        if group is None:
            return

        dialog = QDialog(win)
        dialog.setWindowTitle(T("group_settings.title", name=group.name))
        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        layout.addWidget(QLabel(T("group_settings.name")))
        name_edit = QLineEdit(group.name)
        layout.addWidget(name_edit)

        layout.addWidget(QLabel(T("group_settings.mode")))
        mode_combo = QComboBox()
        mode_combo.addItem(T("group_settings.mode_loop"), "loop")
        mode_combo.addItem(T("group_settings.mode_once"), "once")
        mode_combo.addItem(T("group_settings.mode_repeat"), "repeat")
        mode_combo.setItemData(0, T("group_settings.mode_loop_tip"), Qt.ItemDataRole.ToolTipRole)
        mode_combo.setItemData(1, T("group_settings.mode_once_tip"), Qt.ItemDataRole.ToolTipRole)
        mode_combo.setItemData(2, T("group_settings.mode_repeat_tip"), Qt.ItemDataRole.ToolTipRole)
        idx = mode_combo.findData(group.mode)
        if idx >= 0:
            mode_combo.setCurrentIndex(idx)
        layout.addWidget(mode_combo)

        layout.addWidget(QLabel(T("group_settings.order")))
        order_combo = QComboBox()
        order_combo.addItem(T("group_settings.order_sequential"), "sequential")
        order_combo.addItem(T("group_settings.order_parallel"), "parallel")
        idx2 = order_combo.findData(group.order)
        if idx2 >= 0:
            order_combo.setCurrentIndex(idx2)
        order_combo.setToolTip(T("group_settings.order.tooltip"))
        layout.addWidget(order_combo)
        seq_hint = QLabel(T("group_settings.seq_hint"))
        par_hint = QLabel(T("group_settings.par_hint"))
        for lbl in (seq_hint, par_hint):
            lbl.setStyleSheet("color: #888; font-size: 11px;")
            lbl.setWordWrap(True)
        layout.addWidget(seq_hint)
        layout.addWidget(par_hint)

        def _on_order_changed(idx3):
            is_par = order_combo.currentData() == "parallel"
            seq_hint.setVisible(not is_par)
            par_hint.setVisible(is_par)

        order_combo.currentIndexChanged.connect(_on_order_changed)
        _on_order_changed(order_combo.currentIndex())

        repeat_widget = QWidget()
        repeat_layout = QVBoxLayout(repeat_widget)
        repeat_layout.setContentsMargins(0, 0, 0, 0)
        repeat_layout.addWidget(QLabel(T("group_settings.repeat_times")))
        repeat_spin = QSpinBox()
        repeat_spin.setRange(1, 9999)
        repeat_spin.setValue(group.repeat_times)
        repeat_layout.addWidget(repeat_spin)
        layout.addWidget(repeat_widget)

        interval_widget = QWidget()
        interval_layout = QVBoxLayout(interval_widget)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.addWidget(QLabel(T("group_settings.interval")))
        interval_spin = QSpinBox()
        interval_spin.setRange(0, 99999)
        interval_spin.setValue(group.between_rounds_sec)
        interval_layout.addWidget(interval_spin)
        layout.addWidget(interval_widget)

        def _on_mode_changed(idx):
            mode = mode_combo.currentData()
            repeat_widget.setVisible(mode == "repeat")
            interval_widget.setVisible(mode in ("loop", "repeat"))

        mode_combo.currentIndexChanged.connect(_on_mode_changed)
        _on_mode_changed(mode_combo.currentIndex())

        enabled_cb = QCheckBox(T("group_settings.enabled"))
        enabled_cb.setChecked(group.enabled)
        layout.addWidget(enabled_cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            group.name = name_edit.text().strip() or group.name
            group.mode = mode_combo.currentData()
            group.order = order_combo.currentData()
            group.repeat_times = repeat_spin.value()
            group.between_rounds_sec = interval_spin.value()
            group.enabled = enabled_cb.isChecked()
            win._flush_save()
            win._refresh_rule_list()
