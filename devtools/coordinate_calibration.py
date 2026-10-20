"""可供 OCR Trigger Clicker 校正前景、Frida 後台與混合模式的測試視窗。

啟動：uv run python devtools/coordinate_calibration.py
建立測試任務：在控制台按「建立測試任務」，再於主程式選「座標校正測試」。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WINDOW_TITLE = "OCR 座標校正目標"
TASK_NAME = "座標校正測試"
SIZE_PRESETS = {"1600 × 900": (1600, 900), "1920 × 1080": (1920, 1080)}
TARGETS = (
    {"id": "CENTER", "token": "CENTER 1042 READY", "x": 0.5, "y": 0.5, "kind": "cursor"},
    {"id": "A", "token": "A-6318 READY", "x": 0.2, "y": 0.2, "kind": "custom"},
    {"id": "B", "token": "B-7824 READY", "x": 0.8, "y": 0.2, "kind": "custom"},
    {"id": "C", "token": "C-9051 READY", "x": 0.2, "y": 0.8, "kind": "custom"},
    {"id": "D", "token": "D-3167 READY", "x": 0.8, "y": 0.8, "kind": "custom"},
)
CARD_WIDTH = 330
CARD_HEIGHT = 132


def _card_rect(width: int, height: int, target: dict) -> QRectF:
    cx = width * target["x"]
    cy = height * target["y"]
    return QRectF(cx - CARD_WIDTH / 2, cy - CARD_HEIGHT / 2, CARD_WIDTH, CARD_HEIGHT)


def build_task() -> dict:
    """建立一組先點視窗中心，再點四個比例座標的單次校正任務。"""
    rules = []
    for index, target in enumerate(TARGETS, start=1):
        x, y = target["x"], target["y"]
        rules.append(
            {
                "id": f"coordinate-{target['id'].lower()}",
                "name": f"{index:02d} 點擊 {target['id']}",
                "enabled": True,
                "steps": [
                    {
                        "type": "detect",
                        "params": {
                            "text": target["token"],
                            "match_mode": "contains",
                            "roi": {
                                "x": max(0.0, x - 0.13),
                                "y": max(0.0, y - 0.09),
                                "w": 0.26,
                                "h": 0.18,
                                "roi_coord": "client",
                            },
                            "on_fail": "stop",
                        },
                    },
                    {
                        "type": "click",
                        "params": (
                            {"target": "cursor"}
                            if target["kind"] == "cursor"
                            else {
                                "target": "custom",
                                "x": x,
                                "y": y,
                                "roi_coord": "client",
                            }
                        )
                        | {"button": "left", "random_offset": 0, "after_delay_ms": 350},
                    },
                ],
                "background": False,
                "notes": "座標校正用；命中後測試視窗會將此標記改成綠色。",
            }
        )
    rule_ids = [rule["id"] for rule in rules]
    return {
        "rules": rules,
        "groups": [
            {
                "id": "coordinate-calibration",
                "name": "座標校正",
                "enabled": True,
                "mode": "once",
                "repeat_times": 1,
                "between_rounds_sec": 0,
                "rule_ids": rule_ids,
                "order": "sequential",
            }
        ],
        "_collapsed_groups": [],
        "window_title": WINDOW_TITLE,
        "ratio_coords": True,
    }


def _task_path() -> Path:
    from core._paths import get_data_path

    return Path(get_data_path("_")).parent / "tasks" / f"{TASK_NAME}.json"


def install_task() -> tuple[Path, bool]:
    """建立本機測試任務；遇到同名檔案時保留原檔並改用新名稱。"""
    path = _task_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        index = 2
        while path.with_name(f"{TASK_NAME} ({index}).json").exists():
            index += 1
        path = path.with_name(f"{TASK_NAME} ({index}).json")
    path.write_text(json.dumps(build_task(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path, True


class CalibrationSurface(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(900, 600)
        self.setMouseTracking(True)
        self._hits: set[str] = set()
        self._misses = 0
        self._last_click: tuple[int, int, str, int, int] | None = None

    def reset(self):
        self._hits.clear()
        self._misses = 0
        self._last_click = None
        self.update()

    def apply_preset(self, size: tuple[int, int], borderless: bool):
        flags = Qt.WindowType.Window
        if borderless:
            flags |= Qt.WindowType.FramelessWindowHint
        self.setWindowFlags(flags)
        self.show()
        # Qt 的 resize 指定客戶區大小；這裡調整外框，使視窗總尺寸符合選項。
        QTimer.singleShot(100, lambda: self._resize_outer(size))

    def _resize_outer(self, size: tuple[int, int]):
        outer = self.frameGeometry()
        inner = self.geometry()
        self.resize(
            max(1, size[0] - (outer.width() - inner.width())),
            max(1, size[1] - (outer.height() - inner.height())),
        )
        screen = QApplication.primaryScreen()
        if screen:
            bounds = screen.geometry()
            self.move(
                bounds.x() + (bounds.width() - size[0]) // 2,
                bounds.y() + (bounds.height() - size[1]) // 2,
            )

    def _targets(self):
        return [(target, _card_rect(self.width(), self.height(), target)) for target in TARGETS]

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = round(event.position().x()), round(event.position().y())
        for target, rect in self._targets():
            if rect.contains(event.position()):
                self._hits.add(target["id"])
                dx = round(x - rect.center().x())
                dy = round(y - rect.center().y())
                self._last_click = (x, y, target["id"], dx, dy)
                self.update()
                return
        self._misses += 1
        self._last_click = (x, y, "MISS", 0, 0)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101820"))

        painter.setPen(QColor("#f1f5f9"))
        painter.setFont(QFont("Segoe UI", 21, QFont.Weight.Bold))
        painter.drawText(
            QRectF(20, 12, self.width() - 40, 42),
            Qt.AlignmentFlag.AlignCenter,
            f"座標校正目標  |  {self.frameGeometry().width()} × {self.frameGeometry().height()}",
        )
        painter.setFont(QFont("Segoe UI", 13))
        painter.setPen(QColor("#a8b6c5"))
        painter.drawText(
            QRectF(20, 55, self.width() - 40, 30),
            Qt.AlignmentFlag.AlignCenter,
            f"命中 {len(self._hits)} / {len(TARGETS)}    誤點 {self._misses}",
        )

        for target, rect in self._targets():
            hit = target["id"] in self._hits
            painter.setPen(QPen(QColor("#46d39a" if hit else "#f5b942"), 3))
            painter.setBrush(QColor("#174a3b" if hit else "#243646"))
            painter.drawRoundedRect(rect, 12, 12)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Consolas", 19, QFont.Weight.Bold))
            text = f"HIT {target['id']}" if hit else target["token"]
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

            cx, cy = rect.center().x(), rect.center().y()
            painter.setPen(QPen(QColor("#ff5c5c"), 2))
            painter.drawLine(round(cx) - 12, round(cy), round(cx) + 12, round(cy))
            painter.drawLine(round(cx), round(cy) - 12, round(cx), round(cy) + 12)

        if self._last_click:
            x, y, target_id, dx, dy = self._last_click
            painter.setPen(QPen(QColor("#ff4d6d"), 5))
            painter.drawEllipse(x - 10, y - 10, 20, 20)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
            detail = f"最近點擊 {target_id} @ ({x}, {y})  偏差 Δx={dx:+d}, Δy={dy:+d}"
            painter.drawText(QRectF(20, self.height() - 42, self.width() - 40, 28), detail)


class CalibrationPanel(QMainWindow):
    def __init__(self, surface: CalibrationSurface):
        super().__init__()
        self.surface = surface
        self.setWindowTitle("OCR 座標校正控制台")
        self.setFixedWidth(430)

        root = QWidget()
        layout = QVBoxLayout(root)
        intro = QLabel(
            "這個視窗是自動化點擊的測試目標。\n"
            "請在主工具選「OCR 座標校正目標」和測試任務，\n"
            "逐一切換前景、Frida 後台、混合模式測試。\n"
            "建立任務後，若主工具已開啟，請重新啟動主工具載入任務。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.size_combo = QComboBox()
        self.size_combo.addItems(SIZE_PRESETS)
        form.addRow("外框尺寸", self.size_combo)
        self.borderless = QCheckBox("無標題列、無邊框")
        form.addRow("視窗樣式", self.borderless)
        layout.addLayout(form)

        apply_button = QPushButton("套用尺寸與樣式")
        apply_button.clicked.connect(self._apply)
        layout.addWidget(apply_button)

        reset_button = QPushButton("重設命中狀態")
        reset_button.clicked.connect(self.surface.reset)
        layout.addWidget(reset_button)

        task_button = QPushButton("建立／另存校正測試任務")
        task_button.clicked.connect(self._install_task)
        layout.addWidget(task_button)

        self.status = QLabel(
            "中央標記用來測試「直接點擊」。\n"
            "前景與混合模式開始前，先把滑鼠移到中央紅色十字。\n"
            "其餘四個標記測試固定比例座標。\n"
            "每種模式都要先重設標記，再重新啟動任務；按 Alt+Tab 可切回控制台。"
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.setCentralWidget(root)

    def _apply(self):
        size = SIZE_PRESETS[self.size_combo.currentText()]
        self.surface.reset()
        self.surface.apply_preset(size, self.borderless.isChecked())
        style = "無標題列" if self.borderless.isChecked() else "有標題列"
        self.status.setText(
            f"已套用 {size[0]} × {size[1]}，{style}。請重新啟動主工具中的任務後測試。"
        )

    def _install_task(self):
        path, _created = install_task()
        self.status.setText(
            f"測試任務已建立：{path.name}\n若主工具已開啟，請重新啟動後再選取此任務。"
        )
        QMessageBox.information(
            self,
            "測試任務已建立",
            f"若主工具已開啟，請先重新啟動。\n再選取任務：\n{path.stem}",
        )


def _self_check():
    task = build_task()
    assert len(task["rules"]) == len(TARGETS) == 5
    assert len(task["groups"]) == 1
    assert task["groups"][0]["rule_ids"] == [rule["id"] for rule in task["rules"]]
    assert task["rules"][0]["steps"][1]["params"]["target"] == "cursor"
    assert all(rule["steps"][0]["params"]["roi"]["roi_coord"] == "client" for rule in task["rules"])
    assert all(
        rule["steps"][1]["params"].get("roi_coord") == "client" for rule in task["rules"][1:]
    )
    for target in TARGETS:
        center = _card_rect(1600, 900, target).center()
        assert abs(center.x() / 1600 - target["x"]) < 0.001
        assert abs(center.y() / 900 - target["y"]) < 0.001
    print("coordinate calibration self-check passed")


def main():
    if "--self-check" in sys.argv:
        _self_check()
        return
    app = QApplication(sys.argv)
    app.setApplicationName("OCR 座標校正")
    surface = CalibrationSurface()
    panel = CalibrationPanel(surface)
    panel.show()
    surface.apply_preset(SIZE_PRESETS["1600 × 900"], False)
    QTimer.singleShot(250, surface.raise_)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
