"""可供 OCR Trigger Clicker 校正前景、Frida 後台與混合模式的測試視窗。

啟動：uv run python devtools/coordinate_calibration.py
建立測試任務：在控制台按「建立測試任務」，再於主程式選「座標校正測試」。
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import tempfile
import time
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
SIZE_PRESETS = {
    "1280 × 720": (1280, 720),
    "1600 × 900": (1600, 900),
    "1920 × 1080": (1920, 1080),
}
TARGETS = (
    {
        "id": "CENTER",
        "token": "CENTER 1042 READY",
        "detect_text": "1042",
        "x": 0.5,
        "y": 0.5,
        "kind": "cursor",
    },
    {
        "id": "A",
        "token": "A-6318 READY",
        "detect_text": "6318",
        "x": 0.2,
        "y": 0.2,
        "kind": "custom",
    },
    {
        "id": "B",
        "token": "B-7824 READY",
        "detect_text": "7824",
        "x": 0.8,
        "y": 0.2,
        "kind": "custom",
    },
    {
        "id": "C",
        "token": "C-9051 READY",
        "detect_text": "9051",
        "x": 0.2,
        "y": 0.8,
        "kind": "custom",
    },
    {
        "id": "D",
        "token": "D-3167 READY",
        "detect_text": "3167",
        "x": 0.8,
        "y": 0.8,
        "kind": "custom",
    },
)
CARD_WIDTH = 330
CARD_HEIGHT = 132

STATUS_PATH = Path(tempfile.gettempdir()) / "otc_calibration_status.json"
STATUS_SCHEMA = 1
CLICK_TOLERANCE_PX = 3


def _card_rect(width: int, height: int, target: dict) -> QRectF:
    cx = width * target["x"]
    cy = height * target["y"]
    return QRectF(cx - CARD_WIDTH / 2, cy - CARD_HEIGHT / 2, CARD_WIDTH, CARD_HEIGHT)


def _card_hit(x: float, y: float, width: int, height: int) -> dict | None:
    """Return the hit record for a client-area click, or None for a miss."""
    for target in TARGETS:
        rect = _card_rect(width, height, target)
        if rect.left() <= x <= rect.right() and rect.top() <= y <= rect.bottom():
            return {
                "id": target["id"],
                "x": int(round(x)),
                "y": int(round(y)),
                "dx": int(round(x - rect.center().x())),
                "dy": int(round(y - rect.center().y())),
            }
    return None


def _status_payload(
    *,
    session: str,
    seq: int,
    frame_size: tuple[int, int],
    client_size: tuple[int, int],
    dpi: float,
    hits: list[dict],
    misses: int,
    last_click: dict | None,
    closed: bool = False,
    hwnd: int = 0,
) -> dict:
    return {
        "schema": STATUS_SCHEMA,
        "session": session,
        "pid": os.getpid(),
        "hwnd": int(hwnd),
        "seq": seq,
        "timestamp": round(time.time(), 3),
        "window": {
            "frame_w": int(frame_size[0]),
            "frame_h": int(frame_size[1]),
            "client_w": int(client_size[0]),
            "client_h": int(client_size[1]),
        },
        "dpi": round(float(dpi), 3),
        "hits": list(hits),
        "hit_ids": [hit["id"] for hit in hits],
        "misses": int(misses),
        "last_click": last_click,
        "closed": bool(closed),
    }


def _write_status_file(path: Path, payload: dict) -> None:
    """直接覆寫，不用 os.replace：Windows 上讀者開著檔案時 replace 會失敗而靜默丟失狀態。"""
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    for attempt in range(20):
        try:
            path.write_text(data, encoding="utf-8")
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.005)


def _arg_value(name: str, default: str | None = None) -> str | None:
    try:
        return sys.argv[sys.argv.index(name) + 1]
    except (ValueError, IndexError):
        return default


def _parse_size(text: str | None) -> tuple[int, int]:
    if not text:
        return SIZE_PRESETS["1600 × 900"]
    normalized = text.lower().replace("×", "x").replace(" ", "")
    for label, size in SIZE_PRESETS.items():
        if label.lower().replace("×", "x").replace(" ", "") == normalized:
            return size
    width, _, height = normalized.partition("x")
    return int(width), int(height)


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
                            "text": target["detect_text"],
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
    def __init__(self, session: str = "", status_path: Path = STATUS_PATH):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(900, 600)
        self.setMouseTracking(True)
        self._session = session
        self._status_path = status_path
        self._seq = 0
        self._hits: set[str] = set()
        self._hit_records: dict[str, dict] = {}
        self._misses = 0
        self._last_click: dict | None = None
        self._write_status()

    def reset(self):
        self._hits.clear()
        self._hit_records.clear()
        self._misses = 0
        self._last_click = None
        self._write_status()
        self.update()

    def _write_status(self, closed: bool = False):
        if not self._status_path:
            return
        self._seq += 1
        frame = self.frameGeometry()
        payload = _status_payload(
            session=self._session,
            seq=self._seq,
            frame_size=(frame.width(), frame.height()),
            client_size=(self.width(), self.height()),
            dpi=self.devicePixelRatioF(),
            hits=list(self._hit_records.values()),
            misses=self._misses,
            last_click=self._last_click,
            closed=closed,
            hwnd=int(self.winId()),
        )
        try:
            _write_status_file(self._status_path, payload)
        except OSError:
            pass

    def apply_preset(self, size: tuple[int, int], borderless: bool):
        flags = Qt.WindowType.Window
        if borderless:
            flags |= Qt.WindowType.FramelessWindowHint
        self.setWindowFlags(flags)
        self.show()
        # Qt 的 resize 指定客戶區大小；這裡調整外框，使視窗總尺寸符合選項。
        QTimer.singleShot(100, lambda: self._resize_outer(size))

    def _resize_outer(self, size: tuple[int, int]):
        self.resize(*size)  # Qt 頂層視窗的 resize 即客戶區尺寸，與比例座標基準一致
        screen = QApplication.primaryScreen()
        if screen:
            bounds = screen.geometry()
            self.move(
                bounds.x() + (bounds.width() - size[0]) // 2,
                bounds.y() + (bounds.height() - size[1]) // 2,
            )
        QTimer.singleShot(120, self._write_status)

    def _targets(self):
        return [(target, _card_rect(self.width(), self.height(), target)) for target in TARGETS]

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        record = _card_hit(x, y, self.width(), self.height())
        if record is not None:
            self._hits.add(record["id"])
            self._hit_records[record["id"]] = record
            self._last_click = record
        else:
            self._misses += 1
            self._last_click = {
                "id": "MISS",
                "x": int(round(x)),
                "y": int(round(y)),
                "dx": 0,
                "dy": 0,
            }
        self._write_status()
        self.update()

    def closeEvent(self, event):
        self._write_status(closed=True)
        super().closeEvent(event)

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
            painter.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
            painter.drawText(
                QRectF(rect.left() + 16, rect.top() + 9, rect.width() - 32, 24),
                Qt.AlignmentFlag.AlignCenter,
                f"HIT {target['id']}" if hit else target["id"],
            )
            painter.setFont(QFont("Consolas", 25, QFont.Weight.Bold))
            painter.drawText(
                QRectF(rect.left() + 12, rect.top() + 34, rect.width() - 24, 65),
                Qt.AlignmentFlag.AlignCenter,
                target["detect_text"],
            )

        if self._last_click:
            click = self._last_click
            x, y = click["x"], click["y"]
            painter.setPen(QPen(QColor("#ff4d6d"), 5))
            painter.drawEllipse(x - 10, y - 10, 20, 20)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
            detail = (
                f"最近點擊 {click['id']} @ ({x}, {y})  "
                f"偏差 Δx={click['dx']:+d}, Δy={click['dy']:+d}"
            )
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
    assert _card_hit(800, 450, 1600, 900)["id"] == "CENTER"
    assert _card_hit(320, 180, 1600, 900)["id"] == "A"
    assert _card_hit(10, 10, 1600, 900) is None
    assert _parse_size("1600x900") == (1600, 900)
    assert _parse_size("1920×1080") == (1920, 1080)
    assert _parse_size("1280x720") == (1280, 720)
    assert len(_e2e_runs()) * 3 == 6
    assert len(_e2e_runs(cross_res=True)) * 3 == 12
    assert len(_e2e_runs(full=True)) * 3 == 18
    payload = _status_payload(
        session="self-check",
        seq=1,
        frame_size=(1616, 908),
        client_size=(1600, 900),
        dpi=1.0,
        hits=[{"id": "A", "dx": 1, "dy": -2}],
        misses=0,
        last_click=None,
    )
    assert payload["schema"] == STATUS_SCHEMA
    assert payload["window"]["client_w"] == 1600
    assert payload["hit_ids"] == ["A"]
    _check_production_coordinate_math()
    print("coordinate calibration self-check passed")


def _check_production_coordinate_math():
    """Exercise the real MainLoop converters for framed and borderless sizes."""
    from _loader import load_sibling

    main_loop = load_sibling("main_loop", "core/05_main_loop.py")
    loop = main_loop.MainLoop.__new__(main_loop.MainLoop)
    loop._window_hwnd = None
    loop._frame_client_size = None
    for width, height in ((1280, 720), (1600, 900), (1920, 1080)):
        for chrome in ((8, 31), (0, 0)):
            loop._frame_chrome = chrome
            rect = {"x": 120, "y": 75, "w": width, "h": height}
            client_w, client_h = max(1, width - 2 * chrome[0]), max(1, height - 2 * chrome[1])
            for target in TARGETS:
                px, py = target["x"], target["y"]
                expected_point = (
                    int(round(px * client_w)) + chrome[0],
                    int(round(py * client_h)) + chrome[1],
                )
                assert loop._resolve_point(px, py, rect, "client") == expected_point
                roi = {
                    "x": max(0.0, px - 0.13),
                    "y": max(0.0, py - 0.09),
                    "w": 0.26,
                    "h": 0.18,
                    "roi_coord": "client",
                }
                resolved = loop._resolve_roi(roi, rect, chrome=chrome)
                assert resolved == {
                    "x": int(round(roi["x"] * client_w)) + chrome[0],
                    "y": int(round(roi["y"] * client_h)) + chrome[1],
                    "w": int(round(roi["w"] * client_w)),
                    "h": int(round(roi["h"] * client_h)),
                }


def _autostart_window() -> int:
    """啟動一個自己的校正視窗，讓 --diagnose 不需人工先開窗。"""
    session = f"diagnose-{time.time_ns()}"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--session",
            session,
            "--size",
            "1600x900",
        ],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def _cleanup():
        _stop_process_tree(proc)
        _wait_window_gone()

    atexit.register(_cleanup)
    status = _wait_for_status(session, timeout=20)
    if not status:
        _cleanup()
        raise RuntimeError("自動啟動校正視窗失敗（狀態檔未更新）")
    time.sleep(1.2)
    status = _read_status() or status
    hwnd = int(status.get("hwnd") or 0)
    if not hwnd:
        _cleanup()
        raise RuntimeError("自動啟動校正視窗失敗（沒有視窗代碼）")
    return hwnd


def _diagnose():
    """Run captures, OCR, production coordinate conversion, and safe input routing.

    Input backends are stubbed only at the final dispatch call, so this reports
    where each mode would click without sending clicks to the desktop.
    """
    from _loader import load_sibling

    screenshot = load_sibling("screenshot", "core/01_screenshot.py")
    capture_pipeline = load_sibling("capture_pipeline", "core/17_capture_pipeline.py")
    ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
    main_loop = load_sibling("main_loop", "core/05_main_loop.py")

    hwnd = screenshot.get_window_hwnd(WINDOW_TITLE)
    if not hwnd:
        print("找不到測試視窗，自動啟動一個…")
        hwnd = _autostart_window()
    rect = screenshot.get_window_rect_hwnd(hwnd)
    if not rect:
        raise RuntimeError("無法取得測試視窗尺寸；請確認視窗沒有最小化。")
    chrome = screenshot.get_client_offset_hwnd(hwnd) or (0, 0)
    foreground = main_loop.is_window_foreground(hwnd)
    if not foreground:
        screenshot.activate_window_hwnd(hwnd)
        time.sleep(0.35)
        foreground = main_loop.is_window_foreground(hwnd)
    print("座標校正自動診斷")
    print(f"目標：{WINDOW_TITLE}，外框 {rect['w']}×{rect['h']}，客戶區偏移 {chrome}")
    print(f"目標目前在最前面：{'是' if foreground else '否'}")
    print("點擊安全模式：只記錄即將送出的座標，不會真的操作滑鼠或遊戲。")

    ml = main_loop.MainLoop.__new__(main_loop.MainLoop)
    ml._window_title = WINDOW_TITLE
    ml._frame_chrome = chrome
    ml._frame_client_size = None
    ml._window_hwnd = hwnd
    ml._rule_config_ctrl = type(
        "_ModeConfig",
        (),
        {
            "get_setting": lambda _self, _loop, key, default=None: (
                mode if key == "interaction_mode" else default
            )
        },
    )()

    original_send_click = main_loop._input_mod.send_click
    original_bg_click = main_loop._bg_input.click
    original_bg_method = getattr(main_loop._bg_input, "get_method", lambda: "pynput")()
    failures = []
    try:
        for mode in ("pynput", "frida", "hybrid"):
            print(f"\n[{mode}]")
            if mode == "pynput":
                # 螢幕擷取需要目標真的在最上層；前景可能在啟動後被其他視窗搶走
                screenshot.activate_window_hwnd(hwnd)
                time.sleep(0.1)
            frame = capture_pipeline.capture_frame(mode, WINDOW_TITLE, hwnd, rect)
            if frame is None:
                print("  截圖：失敗（後台模式需提升權限或目標不支援 PrintWindow）")
                print("  OCR：跳過（沒有影像）")
                failures.append(f"{mode}: 無法截圖")
            else:
                print(f"  截圖：成功 {frame.shape[1]}×{frame.shape[0]}")
                detected = set()
                anchors = {}
                ml._ocr_region = lambda img, roi: ocr.recognize(
                    main_loop.crop_roi(img, roi),
                    roi_offset={"x": roi["x"], "y": roi["y"]},
                    preprocess=False,
                    max_side_len=0,
                    min_confidence=0.25,
                )
                ml._ocr_cache_hits = 0
                ml._detect_warn_counter = {}
                ml._fail_since = {}
                for rule_data, target in zip(build_task()["rules"], TARGETS, strict=True):
                    ctx = main_loop.StepContext(img=frame, rect=rect, step_idx=0)
                    rule = main_loop.Rule(
                        id=rule_data["id"],
                        name=rule_data["name"],
                        enabled=True,
                        steps=[],
                    )
                    result = ml._handle_detect(rule_data["steps"][0]["params"], ctx, rule)
                    if result.action == "continue" and ctx.matched_text:
                        detected.add(target["id"])
                        anchors[target["id"]] = ctx.matched_text
                print(
                    f"  正式辨識流程：通過 {len(detected)}/5 個標記 "
                    f"({', '.join(sorted(detected)) or '無'})"
                )
                if len(detected) != len(TARGETS):
                    failures.append(
                        f"{mode}: OCR 僅辨識 {len(detected)}/5；檢查視窗遮擋、截圖與 OCR"
                    )
                anchors_ok = 0
                for target in TARGETS:
                    anchor = anchors.get(target["id"])
                    px, py = ml._resolve_point(target["x"], target["y"], rect, "client")
                    if anchor is None:
                        print(f"  畫面定位 {target['id']}：找不到文字錨點")
                        failures.append(f"{mode}: {target['id']} 無法取得畫面座標錨點")
                        continue
                    dx = anchor.center_x - px
                    dy = anchor.center_y - py
                    aligned = abs(dx) <= 18 and abs(dy) <= 18
                    anchors_ok += int(aligned)
                    print(
                        f"  畫面定位 {target['id']}：{'對齊' if aligned else '偏移'} "
                        f"Δx={dx:+d}, Δy={dy:+d} px"
                    )
                    if not aligned:
                        failures.append(f"{mode}: {target['id']} OCR 位置與點擊座標偏差超過 18 px")
                print(f"  畫面座標對齊：{anchors_ok}/5")

            actual = []
            main_loop._input_mod.send_click = lambda x, y, button="left", hold_ms=0: (
                actual.append(("screen", x, y)) or True
            )
            main_loop._bg_input.click = lambda _hwnd, x, y, button="left", hold_ms=0: (
                actual.append(("client", x, y)) or True
            )
            for target in TARGETS:
                if target["kind"] == "cursor":
                    if mode != "frida":
                        print("  點擊 CENTER：跳過（前景／混合由 --e2e 驗證實際游標位置）")
                        continue
                    center = ml._client_center_offset(rect)
                    if center is None:
                        print("  點擊 CENTER：異常，無法取得客戶區中心")
                        failures.append(f"{mode}: CENTER 無法取得客戶區中心")
                        continue
                    cx, cy = center
                    screen_x, screen_y = ml._to_screen_coords(rect, cx, cy)
                    expected = ("client", cx - chrome[0], cy - chrome[1])
                else:
                    cx, cy = ml._resolve_point(target["x"], target["y"], rect, "client")
                    screen_x, screen_y = ml._to_screen_coords(rect, cx, cy)
                    if mode == "frida":
                        client_w, client_h = ml._client_size(rect)
                        expected = (
                            "client",
                            round(target["x"] * client_w),
                            round(target["y"] * client_h),
                        )
                    else:
                        expected = ("screen", screen_x, screen_y)
                ok = ml._send_click(screen_x, screen_y, "left")
                route, sent_x, sent_y = actual[-1]
                status = "OK" if ok and (route, sent_x, sent_y) == expected else "異常"
                print(
                    f"  點擊 {target['id']}：{status}，送出 ({sent_x},{sent_y})"
                    f" {route}，預期 ({expected[1]},{expected[2]})"
                )
                if status != "OK":
                    failures.append(f"{mode}: {target['id']} 點擊座標路由不符")
    finally:
        main_loop._input_mod.send_click = original_send_click
        main_loop._bg_input.click = original_bg_click
        main_loop._bg_input.set_method(original_bg_method)
    if failures:
        print("\n結果：未通過")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("\n結果：通過；三種模式的截圖、OCR 與座標路由均符合預期。")


def _read_status(path: Path = STATUS_PATH) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _wait_for_status(session: str, timeout: float = 15.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _read_status()
        if status and status.get("session") == session:
            return status
        time.sleep(0.05)
    return None


def _wait_for_window(timeout: float = 20.0) -> int | None:
    from _loader import load_sibling

    screenshot = load_sibling("screenshot", "core/01_screenshot.py")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = screenshot.get_window_hwnd(WINDOW_TITLE)
        if hwnd:
            return hwnd
        time.sleep(0.1)
    return None


def _wait_window_gone(timeout: float = 5.0) -> bool:
    from _loader import load_sibling

    screenshot = load_sibling("screenshot", "core/01_screenshot.py")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not screenshot.get_window_hwnd(WINDOW_TITLE):
            return True
        time.sleep(0.05)
    return False


def _wait_for_hit(
    session: str,
    target_id: str,
    after_seq: int,
    timeout: float = 5.0,
) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _read_status()
        if status and status.get("session") == session and status.get("seq", 0) > after_seq:
            last = status.get("last_click") or {}
            if last.get("id") == "MISS":
                return None
            if last.get("id") == target_id:
                for hit in status.get("hits", []):
                    if hit.get("id") == target_id:
                        return hit
                return last
        time.sleep(0.03)
    return None


class _ModeConfig:
    def __init__(self, mode: str):
        self.mode = mode

    def get_setting(self, _win, key, default=None):
        return self.mode if key == "interaction_mode" else default


class _FakePerf:
    def check_rate_limit(self) -> bool:
        return True

    def record_click(self) -> None:
        pass


def _set_cursor(x: int, y: int) -> None:
    import ctypes

    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def _prepare_loop(mode: str, hwnd: int, chrome: tuple[int, int], main_loop):
    ml = main_loop.MainLoop.__new__(main_loop.MainLoop)
    ml._window_title = WINDOW_TITLE
    ml._window_hwnd = hwnd
    ml._frame_chrome = chrome
    ml._frame_client_size = None
    ml._tool_hwnd = None
    ml._rule_config_ctrl = _ModeConfig(mode)
    ml._perf = _FakePerf()
    ml._last_frida_err_ts = 0.0
    ml._FRIDA_ERR_THROTTLE_SEC = 30.0
    ml.on_bg_fail = None
    ml._log = lambda *args, **kwargs: None
    return ml


def _stop_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _e2e_run(mode: str, size_label: str, borderless: bool) -> dict:
    from _loader import load_sibling

    screenshot = load_sibling("screenshot", "core/01_screenshot.py")
    main_loop = load_sibling("main_loop", "core/05_main_loop.py")
    bg_input = load_sibling("bg_input", "core/16_bg_input.py")

    label = f"{mode}-{size_label}-{'borderless' if borderless else 'framed'}"
    session = f"{label}-{time.time_ns()}"
    args = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--session",
        session,
        "--size",
        size_label,
    ]
    if borderless:
        args.append("--borderless")
    proc = subprocess.Popen(
        args,
        cwd=str(Path(__file__).resolve().parents[1]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started = time.monotonic()
    try:
        status = _wait_for_status(session, timeout=15)
        if status is None:
            return {"label": label, "ok": False, "error": "校正狀態檔未更新"}
        time.sleep(1.2)  # 等 apply_preset 的 resize/move 與狀態寫入穩定
        status = _read_status() or status
        if status.get("session") != session:
            return {"label": label, "ok": False, "error": "校正狀態檔被其他視窗覆寫"}
        hwnd = int(status.get("hwnd") or 0) or _wait_for_window()
        if not hwnd:
            return {"label": label, "ok": False, "error": "校正視窗未出現"}
        rect = screenshot.get_window_rect_hwnd(hwnd)
        if not rect:
            return {"label": label, "ok": False, "error": "無法取得校正視窗尺寸"}
        chrome = screenshot.get_client_offset_hwnd(hwnd) or (0, 0)
        ml = _prepare_loop(mode, hwnd, chrome, main_loop)
        task = build_task()
        max_delta = 0
        for rule_data, target in zip(task["rules"], TARGETS, strict=True):
            before = _read_status() or {}
            if before.get("session") != session:
                before = _wait_for_status(session) or {}
            seq = before.get("seq", 0)
            if mode != "frida":
                screenshot.activate_window_hwnd(hwnd)
                time.sleep(0.35)
                if not main_loop.is_window_foreground(hwnd):
                    return {"label": label, "ok": False, "error": "無法把校正視窗帶到前景"}
            if target["kind"] == "cursor" and mode != "frida":
                cx, cy = ml._resolve_point(target["x"], target["y"], rect, "client")
                sx, sy = ml._to_screen_coords(rect, cx, cy)
                _set_cursor(sx, sy)
                time.sleep(0.05)
            click_params = rule_data["steps"][1]["params"]
            if mode != "frida" and target["kind"] != "cursor":
                cx, cy = ml._resolve_point(target["x"], target["y"], rect, "client")
                sx, sy = ml._to_screen_coords(rect, cx, cy)
                if not (
                    rect["x"] <= sx < rect["x"] + rect["w"]
                    and rect["y"] <= sy < rect["y"] + rect["h"]
                ):
                    return {"label": label, "ok": False, "error": f"{target['id']} 點擊點超出視窗"}
            if mode == "pynput":
                # 擊點前重新抬升：控制台會浮在畫面中央，且前景可能被其他視窗搶走
                screenshot.activate_window_hwnd(hwnd)
                time.sleep(0.08)
                if not main_loop.is_window_foreground(hwnd):
                    return {"label": label, "ok": False, "error": "前景被其他視窗搶走"}
            ctx = main_loop.StepContext(img=None, rect=rect, step_idx=0)
            rule = main_loop.Rule(
                id=rule_data["id"], name=rule_data["name"], enabled=True, steps=[]
            )
            ml._handle_click(click_params, ctx, rule)
            hit = _wait_for_hit(session, target["id"], seq, timeout=5)
            if hit is None:
                after = _read_status() or {}
                detail = after.get("last_click")
                error = bg_input.last_error() if mode == "frida" else ""
                return {
                    "label": label,
                    "ok": False,
                    "error": (
                        f"{target['id']} 未命中（seq={after.get('seq')}, "
                        f"misses={after.get('misses')}, last={detail}）"
                        + (f" frida={error}" if error else "")
                    ),
                }
            dx, dy = hit.get("dx", 0), hit.get("dy", 0)
            max_delta = max(max_delta, abs(dx), abs(dy))
            if abs(dx) > CLICK_TOLERANCE_PX or abs(dy) > CLICK_TOLERANCE_PX:
                return {
                    "label": label,
                    "ok": False,
                    "error": f"{target['id']} 偏差 Δx={dx:+d}, Δy={dy:+d} 超過 {CLICK_TOLERANCE_PX}px",
                }
        return {
            "label": label,
            "ok": True,
            "hits": len(TARGETS),
            "max_delta": max_delta,
            "elapsed": time.monotonic() - started,
        }
    finally:
        if mode == "frida":
            try:
                bg_input.detach()
            except Exception:
                pass
        _stop_process_tree(proc)
        _wait_window_gone()


def _e2e_runs(full: bool = False, cross_res: bool = False) -> list[tuple[str, bool]]:
    """Return (size, borderless) runs; each run covers all three input modes."""
    if full:
        sizes = ("1280x720", "1600x900", "1920x1080")
    elif cross_res:
        sizes = ("1600x900", "1920x1080")
    else:
        sizes = ("1600x900",)
    return [(size, borderless) for size in sizes for borderless in (False, True)]


def _e2e(full: bool = False, cross_res: bool = False) -> None:
    """One-click live test: open window, click all targets, assert the status file."""
    from _loader import load_sibling

    screenshot = load_sibling("screenshot", "core/01_screenshot.py")
    if screenshot.get_window_hwnd(WINDOW_TITLE):
        raise SystemExit(f"請先關閉既有「{WINDOW_TITLE}」視窗，避免誤點到舊視窗。")

    runs = _e2e_runs(full=full, cross_res=cross_res)
    print("座標校正真點擊驗證")
    print("執行期間會移動滑鼠並短暫搶焦點；只點擊校正視窗內的目標。")
    results = []
    for size_label, borderless in runs:
        for mode in ("frida", "pynput", "hybrid"):
            result = _e2e_run(mode, size_label, borderless)
            results.append(result)
            if result["ok"]:
                print(
                    f"[PASS] {result['label']}  "
                    f"{result['hits']}/{len(TARGETS)}  最大偏差 {result['max_delta']}px  "
                    f"{result['elapsed']:.1f}s"
                )
            else:
                print(f"[FAIL] {result['label']}  {result['error']}")
    failed = [result for result in results if not result["ok"]]
    print(f"\n結果：{len(results) - len(failed)}/{len(results)} 通過")
    if failed:
        raise SystemExit(1)


def main():
    if "--self-check" in sys.argv:
        _self_check()
        return
    if "--diagnose" in sys.argv:
        _diagnose()
        return
    if "--e2e" in sys.argv:
        _e2e(full="--full" in sys.argv, cross_res="--cross-res" in sys.argv)
        return
    specified_session = _arg_value("--session", "") or ""
    specified_size = _parse_size(_arg_value("--size"))
    borderless = "--borderless" in sys.argv
    app = QApplication(sys.argv)
    app.setApplicationName("OCR 座標校正")
    surface = CalibrationSurface(session=specified_session)
    panel = CalibrationPanel(surface)
    panel.show()
    surface.apply_preset(specified_size, borderless)
    QTimer.singleShot(250, surface.raise_)
    print(f"校正狀態檔：{STATUS_PATH}")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
