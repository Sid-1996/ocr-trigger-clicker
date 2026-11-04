"""OCR Trigger Clicker 輸入後台測試目標程序 — 獨立 PID 的可視化測試視窗。

用途：供後續的「測試工作台」以 Frida／Hybrid／pynput 對本程序發送真實輸入，
並透過狀態檔觀察本程序「實際收到」了什麼。

啟動：
    uv run python devtools/input_target.py
    uv run python devtools/input_target.py --session run-1 --size 900x640
    uv run python devtools/input_target.py --self-check   # 不開視窗，只驗協定

設計約束：
- 只接收與記錄事件；不主動改變焦點、不移動游標、不彈對話框（避免干擾測試）。
- 狀態檔 per-run（session token ＋ 專屬檔名），避免多個測試程序互相覆寫。
- 狀態檔節流寫入；寫入失敗只記錄 warning，不得讓 GUI 崩潰或終止程序。
- 按鍵／滑鼠按住狀態以「自己收到的 press/release」為準，不信任 event.buttons()：
  後台注入（PostMessage）不會改變實體按鍵狀態，Qt 回報的 buttons() 會是空的。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

# QT_SCALE_FACTOR 必須在 PyQt6 載入前設定，Qt 才會採用；
# 固定為 1 才能讓 client 座標與邏輯座標一致（DPR 仍記錄在狀態檔供驗證）。
os.environ["QT_SCALE_FACTOR"] = "1"

from PyQt6.QtCore import QCoreApplication, QRectF, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QKeySequence, QPainter, QPen  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

_log = logging.getLogger(__name__)

WINDOW_TITLE = "OCR 輸入測試目標"
STATUS_SCHEMA = 1
EVENT_LIMIT = 2000
STATUS_WRITE_INTERVAL_MS = 150
DRAG_OBJECT_SIZE = 44
MAX_LOG_LINES = 14


# ── session / 路徑 ───────────────────────────────────────────────────


def new_session_token(prefix: str = "input-target") -> str:
    """產生本次執行的唯一 session token（含時間 ns 與 pid）。"""
    return f"{prefix}-{time.time_ns()}-{os.getpid()}"


def default_status_path(session: str) -> Path:
    """per-run 狀態檔路徑：不同 session 不會互相覆寫。"""
    return Path(tempfile.gettempdir()) / f"otc_input_target_{session}.json"


def parse_size(text: str) -> tuple[int, int]:
    """解析 WxH（例：900x640）；格式錯誤時回退到預設值。"""
    try:
        w, h = text.lower().replace("×", "x").replace("*", "x").split("x")
        return max(int(w), 320), max(int(h), 240)
    except (AttributeError, ValueError):
        return 900, 640


# ── 事件記錄 ────────────────────────────────────────────────────────


class EventLog:
    """事件記錄（記憶體）。seq 單調遞增，事件數有上限。"""

    def __init__(self, limit: int = EVENT_LIMIT):
        self._limit = max(1, limit)
        self._events: list[dict] = []
        self._seq = 0
        self._dropped = 0

    def record(
        self,
        etype: str,
        *,
        x: float | None = None,
        y: float | None = None,
        key: str | None = None,
        buttons: int | None = None,
        extra: dict | None = None,
    ) -> dict:
        """記錄一筆事件並回傳（seq 由這裡指派）。"""
        self._seq += 1
        event: dict = {
            "seq": self._seq,
            "t": round(time.monotonic(), 6),
            "type": etype,
        }
        if x is not None:
            event["x"] = int(round(x))
        if y is not None:
            event["y"] = int(round(y))
        if key is not None:
            event["key"] = key
        if buttons is not None:
            event["buttons"] = int(buttons)
        if extra:
            event.update(extra)
        self._events.append(event)
        if len(self._events) > self._limit:
            del self._events[: len(self._events) - self._limit]
            self._dropped += 1
        return event

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def dropped(self) -> int:
        """因超過上限而被丟棄的事件數。"""
        return self._dropped

    @property
    def events(self) -> list[dict]:
        return list(self._events)

    def recent(self, count: int = MAX_LOG_LINES) -> list[dict]:
        return list(self._events[-count:])


# ── 語意狀態 ────────────────────────────────────────────────────────


class TargetState:
    """語意狀態：click 計數、按住的按鍵、滑鼠按鍵、drag 物件位置、scroll 計數。"""

    def __init__(self):
        self.click_count = 0
        self.hold_count = 0
        self.hold_active = False
        self.hold_max_ms = 0.0
        self.hold_started_at = 0.0
        self.scroll_events = 0
        self.scroll_dx = 0
        self.scroll_dy = 0
        self.pressed_keys: set[str] = set()
        self.mouse_buttons = 0
        self.drag_pos = (0.0, 0.0)
        self.drag_start: tuple[float, float] | None = None
        self.drag_end: tuple[float, float] | None = None
        self.drag_active = False
        self.drag_moved = False
        self.drag_distance = 0.0
        self.closed = False

    def to_dict(self) -> dict:
        return {
            "click_count": self.click_count,
            "hold_count": self.hold_count,
            "hold_active": self.hold_active,
            "hold_max_ms": round(self.hold_max_ms, 1),
            "scroll_events": self.scroll_events,
            "scroll_dx": self.scroll_dx,
            "scroll_dy": self.scroll_dy,
            "pressed_keys": sorted(self.pressed_keys),
            "mouse_buttons": int(self.mouse_buttons),
            "mouse_buttons_names": button_names(self.mouse_buttons),
            "drag_pos": [round(self.drag_pos[0], 1), round(self.drag_pos[1], 1)],
            "drag_start": (
                None
                if self.drag_start is None
                else [round(self.drag_start[0], 1), round(self.drag_start[1], 1)]
            ),
            "drag_end": (
                None
                if self.drag_end is None
                else [round(self.drag_end[0], 1), round(self.drag_end[1], 1)]
            ),
            "drag_active": self.drag_active,
            "drag_moved": self.drag_moved,
            "drag_distance": round(self.drag_distance, 1),
            "closed": bool(self.closed),
        }


def button_names(mask: int) -> list[str]:
    """Qt 滑鼠按鍵 bitmask → 名稱清單。

    Qt.MouseButton 在 PyQt6 是 enum.Flag（不是 IntEnum），比對時取 .value。
    """
    names = []
    for flag, name in (
        (Qt.MouseButton.LeftButton, "left"),
        (Qt.MouseButton.RightButton, "right"),
        (Qt.MouseButton.MiddleButton, "middle"),
    ):
        if mask & flag.value:
            names.append(name)
    return names


def _enum_value(value) -> int:
    """Qt enum → int（PyQt6 的 enum 不是 IntEnum，不能直接 int()）。"""
    return int(getattr(value, "value", value))


def key_name(qt_key) -> str:
    """Qt key code → 可讀名稱（例：Key_A → "A"、Key_Space → "Space"）。"""
    value = _enum_value(qt_key)
    try:
        text = QKeySequence(value).toString()
        if text:
            return text
    except Exception:
        pass
    try:
        return Qt.Key(value).name
    except Exception:
        return f"Key({value})"


# ── 狀態檔 ──────────────────────────────────────────────────────────


def build_status(
    *,
    session: str,
    seq: int,
    events: list[dict],
    state: dict,
    hwnd: int = 0,
    dpr: float = 1.0,
    closed: bool = False,
    write_seq: int = 0,
    dropped: int = 0,
) -> dict:
    """組出狀態檔內容（純函式，方便測試與離線檢查）。"""
    return {
        "schema": STATUS_SCHEMA,
        "session": session,
        "pid": os.getpid(),
        "hwnd": int(hwnd),
        "seq": int(seq),
        "write_seq": int(write_seq),
        "dropped": int(dropped),
        "timestamp": round(time.time(), 3),
        "dpr": round(float(dpr), 3),
        "events": list(events),
        "state": dict(state),
        "closed": bool(closed),
    }


def write_status_file(
    path: Path, payload: dict, *, attempts: int = 20, delay: float = 0.005
) -> bool:
    """寫入狀態檔；Windows 上檔案可能被暫時占用 → 重試。

    回傳 False 代表寫入失敗（呼叫端自行決定怎麼處理），不丟例外。
    """
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    last = ""
    for attempt in range(max(1, attempts)):
        try:
            # 直接覆寫、不用 os.replace：Windows 上讀者開著檔案時 replace 會失敗而靜默丟狀態。
            path.write_text(data, encoding="utf-8")
            return True
        except PermissionError as e:
            last = str(e)
            time.sleep(delay)
        except OSError as e:
            _log.warning("狀態檔寫入失敗：%s", e)
            return False
    _log.warning("狀態檔寫入失敗（重試 %d 次）：%s", attempts, last)
    return False


class StatusWriter:
    """節流寫入狀態檔。

    mark_dirty() 只標記「狀態已過期」，實際寫入由 QTimer 節流（預設 150ms），
    避免大量事件時把磁碟與 GUI 執行緒拖垮。寫入失敗只記錄，不讓 GUI 崩潰。
    """

    def __init__(self, path: Path, provider, *, interval_ms: int = STATUS_WRITE_INTERVAL_MS):
        self.path = Path(path)
        self._provider = provider
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(1, interval_ms))
        self._timer.timeout.connect(self._on_timeout)
        self._pending = False
        self.writes = 0
        self.failures = 0
        self.last_error = ""

    def mark_dirty(self) -> None:
        """標記狀態已過期（節流：這段期間內只會寫一次）。"""
        self._pending = True
        # 沒有 QApplication 時（例如 --self-check）不啟動計時器：
        # QTimer 在沒有事件迴圈時 start() 會噴 Qt 警告，且不會觸發。
        if QCoreApplication.instance() is None:
            return
        if not self._timer.isActive():
            self._timer.start()

    def force(self) -> bool:
        """忽略節流，立即寫出目前狀態。"""
        self._pending = True
        return self.flush()

    def _on_timeout(self) -> None:
        self.flush()

    def flush(self) -> bool:
        """立即寫出目前狀態（無待寫內容時不寫）。"""
        if not self._pending:
            return False
        self._pending = False
        try:
            payload = self._provider()
        except Exception as e:  # provider 出錯不得讓 GUI 崩潰
            self.failures += 1
            self.last_error = f"provider: {e}"
            _log.warning("狀態組裝失敗：%s", e)
            return False
        try:
            ok = write_status_file(self.path, payload)
        except Exception as e:  # 保險：寫入層也不得讓 GUI 崩潰
            self.failures += 1
            self.last_error = str(e)
            _log.warning("狀態檔寫入例外：%s", e)
            return False
        if ok:
            self.writes += 1
        else:
            self.failures += 1
            self.last_error = str(self.path)
        return ok


# ── 視窗 ────────────────────────────────────────────────────────────


def _regions(width: int, height: int) -> dict[str, QRectF]:
    """各測試區在視窗客戶區中的位置（比例推導，視窗縮放時自動跟著走）。"""

    def rect(x0: float, y0: float, x1: float, y1: float) -> QRectF:
        return QRectF(width * x0, height * y0, width * (x1 - x0), height * (y1 - y0))

    return {
        "click": rect(0.03, 0.04, 0.28, 0.30),
        "hold": rect(0.03, 0.33, 0.28, 0.59),
        "scroll": rect(0.03, 0.62, 0.28, 0.96),
        "key": rect(0.31, 0.04, 0.62, 0.30),
        "drag": rect(0.31, 0.33, 0.62, 0.96),
        "status": rect(0.65, 0.04, 0.97, 0.40),
        "log": rect(0.65, 0.43, 0.97, 0.96),
    }


class InputTargetWindow(QWidget):
    """測試目標視窗：接收事件、記錄狀態、顯示結果。

    只做事：接收事件 → 更新狀態 → 重繪 → 標記狀態檔過期。
    不主動改變焦點、不移動游標、不彈對話框。
    """

    def __init__(
        self,
        session: str,
        status_path: Path,
        size: tuple[int, int] = (900, 640),
        *,
        event_limit: int = EVENT_LIMIT,
    ):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.resize(*size)
        self._session = session
        self._status_path = Path(status_path)
        self.log = EventLog(limit=event_limit)
        self.state = TargetState()
        self._write_seq = 0
        self._closed_written = False
        self.writer = StatusWriter(self._status_path, self.status_payload)
        self._drag_area = _regions(*size)["drag"]
        # 物件初始置於拖曳區中央（拖曳時物件中心跟著游標，見 mouseMoveEvent）。
        self.state.drag_pos = (
            self._drag_area.left() + (self._drag_area.width() - DRAG_OBJECT_SIZE) / 2,
            self._drag_area.top() + (self._drag_area.height() - DRAG_OBJECT_SIZE) / 2,
        )

    # ── 狀態組裝 ──

    def status_payload(self, closed: bool | None = None) -> dict:
        """目前狀態的快照（狀態檔內容）。"""
        is_closed = self.state.closed if closed is None else closed
        return build_status(
            session=self._session,
            seq=self.log.seq,
            events=self.log.events,
            state=self.state.to_dict(),
            hwnd=int(self.winId()),
            dpr=self.devicePixelRatioF(),
            closed=is_closed,
            write_seq=self._write_seq,
            dropped=self.log.dropped,
        )

    def _mark_dirty(self) -> None:
        self.writer.mark_dirty()

    def write_status_now(self, closed: bool = False) -> bool:
        """立即寫出狀態（啟動時與關閉時用；不經節流）。"""
        if closed:
            self.state.closed = True
        self._write_seq += 1
        return self.writer.force()

    # ── 事件 ──

    def _region_at(self, x: float, y: float) -> str:
        for name in ("click", "hold", "scroll", "key", "drag"):
            if self.regions()[name].contains(x, y):
                return name
        return ""

    def regions(self) -> dict[str, QRectF]:
        """目前視窗尺寸下各測試區的位置。"""
        return _regions(self.width(), self.height())

    def mousePressEvent(self, event):
        x, y = event.position().x(), event.position().y()
        button = _enum_value(event.button())
        self.state.mouse_buttons |= button
        region = self._region_at(x, y)
        extra = {"region": region, "qt_buttons": _enum_value(event.buttons())}
        if region == "click":
            self.state.click_count += 1
        elif region == "hold":
            self.state.hold_count += 1
            self.state.hold_active = True
            self.state.hold_started_at = time.monotonic()
        elif region == "drag":
            self.state.drag_active = True
            self.state.drag_moved = False
            self.state.drag_start = (x, y)
            self.state.drag_end = None
            self.state.drag_distance = 0.0
        self.log.record("mouse_press", x=x, y=y, buttons=self.state.mouse_buttons, extra=extra)
        self._mark_dirty()
        self.update()

    def mouseMoveEvent(self, event):
        x, y = event.position().x(), event.position().y()
        moved = False
        # 用「自己收到的按下狀態」判定拖曳：後台注入不會改變實體按鍵，
        # event.buttons() 在 PostMessage 情境下會是空的。
        if self.state.drag_active and self.state.mouse_buttons & Qt.MouseButton.LeftButton.value:
            area = self.regions()["drag"]
            nx = min(max(x - DRAG_OBJECT_SIZE / 2, area.left()), area.right() - DRAG_OBJECT_SIZE)
            ny = min(max(y - DRAG_OBJECT_SIZE / 2, area.top()), area.bottom() - DRAG_OBJECT_SIZE)
            self.state.drag_pos = (nx, ny)
            self.state.drag_moved = True
            moved = True
        self.log.record(
            "mouse_move",
            x=x,
            y=y,
            buttons=self.state.mouse_buttons,
            extra={"qt_buttons": _enum_value(event.buttons()), "dragging": moved},
        )
        if moved:
            self._mark_dirty()
        self.update()

    def mouseReleaseEvent(self, event):
        x, y = event.position().x(), event.position().y()
        button = _enum_value(event.button())
        self.state.mouse_buttons &= ~button
        if self.state.drag_active:
            self.state.drag_active = False
            self.state.drag_end = (x, y)
            if self.state.drag_start is not None:
                dx = x - self.state.drag_start[0]
                dy = y - self.state.drag_start[1]
                self.state.drag_distance = (dx * dx + dy * dy) ** 0.5
        if self.state.hold_active:
            elapsed = (time.monotonic() - self.state.hold_started_at) * 1000
            self.state.hold_max_ms = max(self.state.hold_max_ms, elapsed)
            self.state.hold_active = False
        self.log.record(
            "mouse_release",
            x=x,
            y=y,
            buttons=self.state.mouse_buttons,
            extra={"qt_buttons": _enum_value(event.buttons())},
        )
        self._mark_dirty()
        self.update()

    def wheelEvent(self, event):
        x, y = event.position().x(), event.position().y()
        delta = event.angleDelta()
        dx, dy = int(delta.x()), int(delta.y())
        self.state.scroll_events += 1
        self.state.scroll_dx += dx
        self.state.scroll_dy += dy
        region = self._region_at(x, y)
        self.log.record(
            "mouse_wheel",
            x=x,
            y=y,
            buttons=self.state.mouse_buttons,
            extra={"dx": dx, "dy": dy, "region": region},
        )
        self._mark_dirty()
        self.update()

    def keyPressEvent(self, event):
        name = key_name(event.key())
        self.state.pressed_keys.add(name)
        self.log.record("key_press", key=name, extra={"text": event.text()})
        self._mark_dirty()
        self.update()

    def keyReleaseEvent(self, event):
        name = key_name(event.key())
        self.state.pressed_keys.discard(name)
        self.log.record("key_release", key=name)
        self._mark_dirty()
        self.update()

    def event(self, event):
        # ShortcutOverride 一律接受，確保按鍵事件能送到視窗（部分平台會攔截）。
        if event.type() == event.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def closeEvent(self, event):
        """關閉時盡可能寫出最後一次狀態（closed=true）。"""
        self.state.closed = True
        if not self._closed_written:
            self._closed_written = True
            self.write_status_now(closed=True)
        super().closeEvent(event)

    # ── 繪製 ──

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        regions = self.regions()
        labels = {
            "click": "Click 測試區",
            "hold": "Hold 測試區",
            "scroll": "Scroll 測試區",
            "key": "Keyboard 測試區",
            "drag": "Drag 測試區",
        }
        for name, rect in regions.items():
            if name in ("status", "log"):
                continue
            painter.setPen(QPen(QColor("#3a3a3a"), 1))
            painter.setBrush(QColor("#252525"))
            painter.drawRect(rect)
            painter.setPen(QColor("#888888"))
            painter.drawText(
                rect.adjusted(8, 6, -8, -8),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                labels[name],
            )
        self._paint_click(painter, regions["click"])
        self._paint_hold(painter, regions["hold"])
        self._paint_scroll(painter, regions["scroll"])
        self._paint_key(painter, regions["key"])
        self._paint_drag(painter, regions["drag"])
        self._paint_status(painter, regions["status"])
        self._paint_log(painter, regions["log"])
        painter.end()

    def _text(self, painter, rect, text, color="#dddddd"):
        painter.setPen(QColor(color))
        painter.drawText(
            rect.adjusted(8, 4, -8, -4),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
            text,
        )

    def _paint_click(self, painter, rect):
        self._text(painter, rect, f"點擊次數：{self.state.click_count}", "#7fd88f")

    def _paint_hold(self, painter, rect):
        flag = "按住中" if self.state.hold_active else "未按住"
        self._text(painter, rect, f"按住次數：{self.state.hold_count}（{flag}）", "#7fd88f")
        self._text(
            painter,
            rect.adjusted(0, rect.height() * 0.28, 0, 0),
            f"最長按住：{self.state.hold_max_ms:.0f} ms",
            "#aaaaaa",
        )

    def _paint_scroll(self, painter, rect):
        self._text(painter, rect, f"滾輪事件：{self.state.scroll_events}", "#7fd88f")
        self._text(
            painter,
            rect.adjusted(0, rect.height() * 0.28, 0, 0),
            f"累積 dx={self.state.scroll_dx} dy={self.state.scroll_dy}",
            "#aaaaaa",
        )

    def _paint_key(self, painter, rect):
        keys = "、".join(sorted(self.state.pressed_keys)) or "（無）"
        self._text(painter, rect, f"目前按住：{keys}", "#7fd88f")

    def _paint_drag(self, painter, rect):
        x, y = self.state.drag_pos
        painter.setBrush(QColor("#e0a458"))
        painter.setPen(QPen(QColor("#f0c070"), 1))
        painter.drawRect(QRectF(x, y, DRAG_OBJECT_SIZE, DRAG_OBJECT_SIZE))
        self._text(
            painter,
            rect.adjusted(0, rect.height() - 30, 0, 0),
            f"物件位置：({x:.0f}, {y:.0f})　已移動：{'是' if self.state.drag_moved else '否'}",
            "#aaaaaa",
        )

    def _paint_status(self, painter, rect):
        lines = [
            f"session：{self._session}",
            f"seq：{self.log.seq}（丟棄 {self.log.dropped}）",
            f"滑鼠按鍵：{','.join(button_names(self.state.mouse_buttons)) or '無'}",
            f"按鍵：{','.join(sorted(self.state.pressed_keys)) or '無'}",
            f"drag 距離：{self.state.drag_distance:.0f}px",
            f"DPR：{self.devicePixelRatioF():.2f}",
        ]
        painter.setPen(QColor("#dddddd"))
        for i, line in enumerate(lines):
            painter.drawText(
                rect.adjusted(8, 6 + i * 20, -8, 0),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                line,
            )

    def _paint_log(self, painter, rect):
        painter.setPen(QColor("#dddddd"))
        for i, event in enumerate(self.log.recent(MAX_LOG_LINES)):
            bits = [f"#{event['seq']}", event["type"]]
            if "x" in event:
                bits.append(f"({event['x']},{event['y']})")
            if "key" in event:
                bits.append(event["key"])
            if "dx" in event:
                bits.append(f"d=({event['dx']},{event['dy']})")
            painter.drawText(
                rect.adjusted(8, 6 + i * 18, -8, 0),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                " ".join(bits),
            )


# ── CLI ─────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="input_target",
        description="OCR Trigger Clicker 輸入後台測試目標程序（獨立 PID）",
    )
    parser.add_argument("--session", default="", help="本次執行的 session token（預設自動產生）")
    parser.add_argument(
        "--status-path", default="", help="狀態檔路徑（預設：%%TEMP%% 下 per-run 檔名）"
    )
    parser.add_argument("--size", default="900x640", help="視窗客戶區大小 WxH（預設 900x640）")
    parser.add_argument(
        "--self-check", action="store_true", help="不開視窗，只驗證狀態協定與資料結構"
    )
    return parser


def run_self_check() -> int:
    """驗證 session、事件記錄、狀態資料結構與狀態檔協定。

    不需要人工操作視窗、不需要 Frida 或遊戲。
    """
    # 1. session token 唯一性
    a = new_session_token()
    b = new_session_token()
    assert a != b, "session token 必須唯一"
    assert default_status_path(a) != default_status_path(b), "狀態檔路徑必須 per-run"

    # 2. 事件記錄：seq 單調遞增、欄位正確
    log = EventLog(limit=10)
    log.record("mouse_press", x=10, y=20, buttons=1)
    log.record("mouse_move", x=11, y=21, buttons=1)
    log.record("mouse_release", x=12, y=22, buttons=0)
    log.record("mouse_wheel", x=5, y=6, buttons=0, extra={"dx": 0, "dy": 120})
    log.record("key_press", key="A")
    log.record("key_release", key="A")
    seqs = [e["seq"] for e in log.events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "seq 必須單調遞增且唯一"
    assert log.events[0]["type"] == "mouse_press" and log.events[0]["x"] == 10
    assert log.events[3]["type"] == "mouse_wheel" and log.events[3]["dy"] == 120
    assert log.events[4]["key"] == "A"

    # 3. 事件上限
    limited = EventLog(limit=3)
    for i in range(10):
        limited.record("mouse_move", x=i, y=i)
    assert len(limited.events) == 3, "事件紀錄必須有上限"
    assert limited.dropped == 7, "被丟棄的事件必須計數"

    # 4. 狀態檔協定：寫出 → 讀回 → 欄位完整
    state = TargetState()
    state.click_count = 2
    state.pressed_keys.add("A")
    payload = build_status(
        session=a,
        seq=log.seq,
        events=log.events,
        state=state.to_dict(),
        hwnd=1234,
        dpr=1.0,
        closed=True,
    )
    for key in (
        "schema",
        "session",
        "pid",
        "hwnd",
        "seq",
        "timestamp",
        "dpr",
        "events",
        "state",
        "closed",
    ):
        assert key in payload, f"狀態檔缺少欄位：{key}"
    assert payload["closed"] is True

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "status.json"
        writer = StatusWriter(path, lambda: payload)
        writer.mark_dirty()
        assert writer.flush(), "狀態檔寫入應該成功"
        assert writer.writes == 1
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["session"] == a and data["closed"] is True

        # 5. 寫入失敗不得拋例外（視為失敗並記錄）
        bad = StatusWriter(Path(tmp) / "no-such-dir" / "status.json", lambda: payload)
        bad.mark_dirty()
        assert bad.flush() is False, "寫入失敗必須回 False"
        assert bad.failures == 1

    print("  [OK] session token 唯一、狀態檔路徑 per-run")
    print("  [OK] 事件 seq 單調遞增、欄位正確、有上限")
    print("  [OK] 狀態資料結構完整（session/pid/hwnd/seq/events/state/closed/dpr）")
    print("  [OK] 狀態檔可寫入可讀回；寫入失敗不會拋例外")
    print("\n=== Input Target Self-Check 完成 ===")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.self_check:
        return run_self_check()

    session = args.session.strip() or new_session_token()
    status_path = Path(args.status_path) if args.status_path else default_status_path(session)
    size = parse_size(args.size)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = InputTargetWindow(session=session, status_path=status_path, size=size)
    window.show()
    # 立刻寫一次，讓工作台可以取得 hwnd / pid（DPR 也一併記錄）。
    window.write_status_now()
    print(f"input_target: session={session} pid={os.getpid()} status={status_path}")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
