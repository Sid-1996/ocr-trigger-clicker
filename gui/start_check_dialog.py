"""啟動前檢核結果對話框（UX3-03）。

把「這次執行會被什麼擋下」攤平成一張清單：每一行是一個問題，
按「定位到這一步」可直接跳到出問題的規則與步驟。

定位會切換規則選取並重建編輯區，因此實際定位由呼叫端在對話框關閉後執行
（對話框選好目標後存在 selected_target，由呼叫端讀取）。
"""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from i18n import T


class StartCheckDialog(QDialog):
    """UX3-03 啟動前檢核清單。

    issues／warnings：每筆 {rule_id, rule_name, step_idx, severity, text, background}
      severity：blocked＝會擋住這次執行；warning＝只提醒、不擋。
      step_idx：0-based 步驟位置；None 或 <0＝整條規則層級的問題。
    """

    def __init__(self, parent=None, issues=None, warnings=None):
        super().__init__(parent)
        self.setWindowTitle(T("start.check_title"))
        self.issues = list(issues or [])
        self.warnings = list(warnings or [])
        # 使用者選了要定位的目標：(rule_id, step_idx, rule_name)。
        # 由呼叫端在對話框關閉後執行定位（定位會重建編輯區，不能在對話框開著時做）。
        self.selected_target = None
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        intro = QLabel(T("start.check_intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(220)
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        for issue in self.issues:
            box.addWidget(self._build_row(issue))
        for issue in self.warnings:
            box.addWidget(self._build_row(issue))
        box.addStretch()
        scroll.setWidget(holder)
        layout.addWidget(scroll)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText(T("ui.cancel"))
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _build_row(self, issue) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(8)

        blocked = issue.get("severity") == "blocked"
        badge = QLabel(T("start.check_blocked") if blocked else T("start.check_warning"))
        badge.setStyleSheet(
            "color: #e2564d; font-size: 12px;" if blocked else "color: #e0a458; font-size: 12px;"
        )
        badge.setFixedWidth(70)
        h.addWidget(badge)

        step_idx = issue.get("step_idx")
        if isinstance(step_idx, int) and step_idx >= 0:
            where = T("start.check_at_step", rule=issue.get("rule_name", ""), n=step_idx + 1)
        else:
            where = T("start.check_at_rule", rule=issue.get("rule_name", ""))
        name_label = QLabel(where)
        name_label.setStyleSheet("font-weight: bold;")
        h.addWidget(name_label)

        if issue.get("background"):
            bg = QLabel(T("start.check_background"))
            bg.setStyleSheet("color: #9aa4b2; font-size: 12px;")
            h.addWidget(bg)

        text_label = QLabel(issue.get("text", ""))
        text_label.setWordWrap(True)
        h.addWidget(text_label, 1)

        btn = QPushButton(T("start.check_locate"))
        btn.clicked.connect(lambda _checked=False, it=issue: self._choose(it))
        h.addWidget(btn)
        return row

    def _choose(self, issue):
        self.selected_target = (
            issue.get("rule_id", ""),
            issue.get("step_idx"),
            issue.get("rule_name", ""),
        )
        self.accept()
