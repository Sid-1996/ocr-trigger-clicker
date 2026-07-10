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
        dialog.setWindowTitle(f"群組設定 — {group.name}")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        layout.addWidget(QLabel("群組名稱"))
        name_edit = QLineEdit(group.name)
        layout.addWidget(name_edit)

        layout.addWidget(QLabel("執行模式"))
        mode_combo = QComboBox()
        mode_combo.addItem("循環執行", "loop")
        mode_combo.addItem("執行一次", "once")
        mode_combo.addItem("重複 N 次", "repeat")
        idx = mode_combo.findData(group.mode)
        if idx >= 0:
            mode_combo.setCurrentIndex(idx)
        layout.addWidget(mode_combo)

        layout.addWidget(QLabel("規則執行順序"))
        order_combo = QComboBox()
        order_combo.addItem("依序執行（↻）", "sequential")
        order_combo.addItem("並行掃描（∥）", "parallel")
        idx2 = order_combo.findData(group.order)
        if idx2 >= 0:
            order_combo.setCurrentIndex(idx2)
        order_combo.setToolTip(
            "依序：每次只跑列表當前的規則，觸發才前進到下一條。未觸發會卡住指標。\n"
            "並行：每幀從頭掃全部規則，第一條命中的執行，其餘跳過。不卡指標。"
        )
        layout.addWidget(order_combo)
        seq_hint = QLabel(
            "依序：每次只檢查列表中的一個規則，該規則觸發後指標才前進到下一條。未觸發則重複執行同一條。"
        )
        par_hint = QLabel(
            "並行：每幀從列表最上方開始依序掃描，第一個命中目標的規則會執行其動作，其餘直接跳過。下幀重新從頭掃描。"
        )
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
        repeat_layout.addWidget(QLabel("重複次數"))
        repeat_spin = QSpinBox()
        repeat_spin.setRange(1, 9999)
        repeat_spin.setValue(group.repeat_times)
        repeat_layout.addWidget(repeat_spin)
        layout.addWidget(repeat_widget)

        interval_widget = QWidget()
        interval_layout = QVBoxLayout(interval_widget)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.addWidget(QLabel("每輪間隔 (秒)"))
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

        enabled_cb = QCheckBox("啟用群組")
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
