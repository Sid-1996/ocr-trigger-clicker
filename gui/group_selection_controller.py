from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from _loader import load_sibling
from core.rule_models import group_display_name
from i18n import T

_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
set_task_interaction_mode = _rule_mod.set_task_interaction_mode


class GroupSelectionController:
    def uncat_enabled_count(self, win) -> int:
        """未歸類中「啟用中」的規則數（這些規則啟動時不會執行）。"""
        uncat = next((g for g in win._groups if g.id == "__uncategorized__"), None)
        if not uncat:
            return 0
        live = {r.id for r in win._rules if r.enabled}
        return sum(1 for rid in uncat.rule_ids if rid in live)

    def show(self, win) -> list[str] | None:
        enabled = [g for g in win._groups if g.enabled]
        uncat_count = self.uncat_enabled_count(win)
        if len(enabled) <= 1:
            return [g.id for g in enabled] if enabled else []
        # 「不再詢問」：跳過群組確認窗，直接執行全部啟用群組。
        # 重新開啟詢問：設定 → 一般 → 「啟動時詢問要執行的群組」。
        if not win._rule_config_ctrl.get_setting(win, "ask_group_selection", True):
            return [g.id for g in enabled]
        # 沒有勾「不再詢問」→ 每次啟動照常詢問、預設全部啟用群組打勾。
        dialog = QDialog(win)
        dialog.setWindowTitle(T("dialog.group_selection"))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        hint = QLabel(T("ui.select_group_hint", count=len(enabled)))
        layout.addWidget(hint)
        if uncat_count:
            warn = QLabel(T("dialog.uncat_skip_hint", count=uncat_count))
            warn.setStyleSheet("color: #b58900; font-size: 12px;")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        # ── 核取清單：2 欄排列 + 捲動區域（群組多時彈窗不會過長）──
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        checks = []
        per_col = (len(enabled) + 1) // 2
        for i, g in enumerate(enabled):
            cb = QCheckBox(group_display_name(g))
            cb.setChecked(True)  # 每次開啟預設全部啟用群組打勾
            cb.setProperty("gid", g.id)
            checks.append(cb)
            grid.addWidget(cb, i % per_col, i // per_col)

        # 全選 / 全不選（依當前狀態切換）
        toggle_all_btn = QPushButton(T("dialog.group_toggle_all_none"))

        def _toggle_all():
            target = not all(cb.isChecked() for cb in checks)
            for cb in checks:
                cb.setChecked(target)
            toggle_all_btn.setText(
                T("dialog.group_toggle_all_none" if not target else "dialog.group_toggle_all")
            )

        toggle_all_btn.clicked.connect(_toggle_all)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        avail = QApplication.primaryScreen().availableGeometry().height()
        scroll.setMaximumHeight(int(avail * 0.55))
        layout.addWidget(toggle_all_btn)
        layout.addWidget(scroll)

        # 不再詢問：勾選後從此 F8 / 開始按鈕啟動不再彈群組確認窗，直接執行全部啟用群組。
        dont_ask_cb = QCheckBox(T("dialog.group_dont_ask"))
        dont_ask_cb.setToolTip(T("dialog.group_dont_ask.tooltip"))
        layout.addWidget(dont_ask_cb)

        # 便利按鈕：一鍵切換互動方法並執行（前景 ↔ 後台）
        if win._is_bg_mode():
            switch_text = T("dialog.group_switch_to_fg")
            switch_target = "pynput"
        else:
            switch_text = T("dialog.group_switch_to_bg")
            switch_target = "frida"

        def _switch_mode_and_run():
            win._rule_config_ctrl.set_setting(win, "interaction_mode", switch_target)
            if win._current_task:
                task_path = str(_rule_mod.get_tasks_dir() / f"{win._current_task}.json")
                set_task_interaction_mode(task_path, switch_target)
            win._update_interaction_mode_label()
            dialog.accept()

        switch_btn = QPushButton(switch_text)
        switch_btn.clicked.connect(_switch_mode_and_run)
        layout.addWidget(switch_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(T("dialog.group_ok"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        if dont_ask_cb.isChecked():
            win._rule_config_ctrl.set_setting(win, "ask_group_selection", False)
        return [cb.property("gid") for cb in checks if cb.isChecked()]


if __name__ == "__main__":
    from types import SimpleNamespace

    controller = GroupSelectionController()
    win = SimpleNamespace(
        _groups=[
            SimpleNamespace(id="__uncategorized__", rule_ids=["on", "off", "missing"]),
            SimpleNamespace(id="g1", rule_ids=["on"]),
        ],
        _rules=[
            SimpleNamespace(id="on", enabled=True),
            SimpleNamespace(id="off", enabled=False),
        ],
    )
    assert controller.uncat_enabled_count(win) == 1
    win._groups = []
    assert controller.uncat_enabled_count(win) == 0
    print("group_selection_controller self-check passed")
