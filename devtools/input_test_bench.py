"""OCR Trigger Clicker 輸入後台測試工作台。

對獨立的測試目標程序（``devtools/input_target.py``）發送真實輸入，並以三層
判定確認結果：

1. **Backend**：產品既有 Input Backend 的回傳值與 ``last_error()``。
2. **Target Received**：目標程式狀態檔中出現預期事件（以測試前的 ``seq`` 為基準）。
3. **Expected Behavior**：目標端的語意狀態達到預期（點擊計數、按鍵已放開、
   物件真的移動、滾輪計數…）。

輸入一律走產品既有 API，不另寫一套：

- Frida：``core/16_bg_input.py``（``set_method`` / ``click`` / ``send_key`` /
  ``send_hold_key`` / ``drag`` / ``scroll`` / ``last_error`` / ``detach``）
- Hybrid：``core/19_hybrid_input.py::focus_guard`` ＋ ``core/03_pynput_input.py``
- 前景：``core/03_pynput_input.py``

用法：
    uv run python devtools/input_test_bench.py            # 工作台 GUI
    uv run python devtools/input_test_bench.py --self-check
    uv run python devtools/input_test_bench.py --integration
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _loader import load_sibling  # noqa: E402

TARGET_SCRIPT = ROOT / "devtools" / "input_target.py"
MODES = ("frida", "hybrid", "pynput")
MODE_LABELS = {
    "frida": "Frida（後台注入）",
    "hybrid": "Hybrid（後台截圖＋前景輸入）",
    "pynput": "前景 pynput",
}
WM_CLOSE = 0x0010
# 目標程式狀態檔以 150ms 節流寫入；事件流連續這麼久沒變才視為「已靜止」，
# 否則最後一筆放開事件還沒寫出來就會被誤判成失敗。
EVENT_QUIET_SEC = 0.25

_target_mod = None


def target_module():
    """載入目標程式模組（重用其 session token 與區域幾何）。

    目標模組在 import 前會設定 ``QT_SCALE_FACTOR=1``；這裡在載入後還原，
    避免污染工作台自身的 Qt 縮放設定（目標程序自己會設定）。
    """
    global _target_mod
    if _target_mod is None:
        saved = os.environ.get("QT_SCALE_FACTOR")
        try:
            _target_mod = load_sibling("input_target", "devtools/input_target.py")
        finally:
            if saved is None:
                os.environ.pop("QT_SCALE_FACTOR", None)
            else:
                os.environ["QT_SCALE_FACTOR"] = saved
    return _target_mod


# ── 目標狀態 ────────────────────────────────────────────────────────


@dataclass
class TargetStatus:
    """目標程式狀態檔的快照。"""

    session: str = ""
    pid: int = 0
    hwnd: int = 0
    seq: int = 0
    events: list = field(default_factory=list)
    state: dict = field(default_factory=dict)
    dpr: float = 1.0
    closed: bool = False
    dropped: int = 0

    @classmethod
    def from_payload(cls, payload: dict) -> TargetStatus:
        return cls(
            session=str(payload.get("session") or ""),
            pid=int(payload.get("pid") or 0),
            hwnd=int(payload.get("hwnd") or 0),
            seq=int(payload.get("seq") or 0),
            events=list(payload.get("events") or []),
            state=dict(payload.get("state") or {}),
            dpr=float(payload.get("dpr") or 1.0),
            closed=bool(payload.get("closed")),
            dropped=int(payload.get("dropped") or 0),
        )


class TargetProcess:
    """目標程式生命週期：啟動、輪詢狀態檔、正常結束。

    不信任 ``subprocess.Popen`` 的 pid：以狀態檔回報的 pid 為準（Windows 的
    venv ``python.exe`` 是轉導器，會再 spawn 真正的 python 行程）。
    """

    def __init__(self, script: Path = TARGET_SCRIPT):
        self._script = Path(script)
        self._proc: subprocess.Popen | None = None
        self._session = ""
        self._status_path: Path | None = None
        self._status: TargetStatus | None = None
        self.last_error = ""

    # ── 啟動 ──

    def start(
        self, session: str = "", size: str = "900x640", timeout: float = 25.0
    ) -> TargetStatus:
        """啟動目標程式並等待狀態檔就緒（session / pid / hwnd 皆有效）。"""
        self.stop()
        session = session or target_module().new_session_token("bench")
        status_path = Path(tempfile.gettempdir()) / f"otc_input_target_{session}.json"
        env = dict(os.environ)
        # 只給目標程序；工作台自身不受影響（目標模組 import 時也會設一次）。
        env["QT_SCALE_FACTOR"] = "1"
        self._proc = subprocess.Popen(
            [
                sys.executable,
                str(self._script),
                "--session",
                session,
                "--status-path",
                str(status_path),
                "--size",
                size,
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._session = session
        self._status_path = status_path
        try:
            status = self._wait_for_status(session, timeout)
        except Exception:
            self.stop()
            raise
        self._status = status
        return status

    def _wait_for_status(self, session: str, timeout: float) -> TargetStatus:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError(f"目標程式提前結束（exit={self._proc.returncode}）")
            payload = self._read_payload()
            if payload is not None:
                if payload.get("session") != session:
                    raise RuntimeError(
                        f"狀態檔的 session 不符（期望 {session}，實際 {payload.get('session')}）"
                    )
                status = TargetStatus.from_payload(payload)
                if status.pid > 0 and status.hwnd > 0:
                    return status
            time.sleep(0.05)
        raise RuntimeError("目標程式狀態檔未就緒（逾時）")

    def _read_payload(self) -> dict | None:
        if self._status_path is None:
            return None
        try:
            return json.loads(self._status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # ── 輪詢 ──

    def read_status(self) -> TargetStatus | None:
        """讀取目前狀態（讀不到回 None）。"""
        payload = self._read_payload()
        if payload is None:
            return None
        self._status = TargetStatus.from_payload(payload)
        return self._status

    @property
    def status(self) -> TargetStatus | None:
        return self._status

    @property
    def session(self) -> str:
        return self._session

    @property
    def hwnd(self) -> int:
        return self._status.hwnd if self._status else 0

    @property
    def pid(self) -> int:
        return self._status.pid if self._status else 0

    def is_running(self) -> bool:
        """目標程式是否還活著（以行程結束狀態判定，不看狀態檔）。"""
        return self._proc is not None and self._proc.poll() is None

    # ── 結束 ──

    def stop(self, timeout: float = 10.0) -> None:
        """正常要求目標程式結束；必要時才強制結束殘留行程。"""
        proc, self._proc = self._proc, None
        status = self._status
        if proc is None:
            return
        if proc.poll() is None and status is not None and status.hwnd:
            try:
                ctypes.windll.user32.PostMessageW(status.hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        try:
            proc.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            pass
        # 必要時才強制結束：以狀態檔回報的 pid 為準（不是 Popen 的 pid）。
        pid = status.pid if status and status.pid else proc.pid
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


# ── 測試結果 ────────────────────────────────────────────────────────


@dataclass
class TestOutcome:
    """一項測試的三層結果（三層不合併成單一 True/False）。"""

    name: str
    backend_ok: bool = False
    backend_detail: str = ""
    received: bool = False
    received_detail: str = ""
    expected_ok: bool = False
    expected_detail: str = ""
    gap: str = ""

    @property
    def passed(self) -> bool:
        return self.backend_ok and self.received and self.expected_ok

    def summary(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return (
            f"[{mark}] {self.name}｜Backend={'OK' if self.backend_ok else 'NG'}"
            f"｜Received={'OK' if self.received else 'NG'}"
            f"｜Expected={'OK' if self.expected_ok else 'NG'}"
        )


# ── Backend 執行器 ──────────────────────────────────────────────────


def _normalize_key(key: str) -> str:
    """把工作台的按鍵名稱轉成目標端 Qt 會回報的名稱。

    目標端用 ``QKeySequence``／``Qt.Key`` 轉名稱：字母 → "A"、space → "Space"。
    """
    k = key.strip()
    if len(k) == 1 and k.isalpha():
        return k.upper()
    special = {
        "space": "Space",
        "shift": "Shift",
        "ctrl": "Ctrl",
        "control": "Ctrl",
        "alt": "Alt",
        "tab": "Tab",
        "enter": "Return",
        "return": "Return",
        "esc": "Escape",
        "escape": "Escape",
    }
    return special.get(k.lower(), k)


class BenchRunner:
    """對目標程式發送真實輸入並做三層判定。"""

    def __init__(self, target: TargetProcess, mode: str = "frida"):
        self._target = target
        self._mode = mode
        self._cancel = threading.Event()
        self._bg = load_sibling("bg_input", "core/16_bg_input.py")
        self._pynput = load_sibling("pynput_input", "core/03_pynput_input.py")
        self._hybrid = load_sibling("hybrid_input", "core/19_hybrid_input.py")
        self._screenshot = load_sibling("screenshot", "core/01_screenshot.py")

    # ── 取消 ──

    @property
    def cancel_event(self) -> threading.Event:
        """工作台自己的 cancel Event（不動 MainLoop 的 _stop_event）。"""
        return self._cancel

    def cancel(self) -> None:
        self._cancel.set()

    def reset_cancel(self) -> None:
        self._cancel.clear()

    # ── 幾何 ──

    def _client_size(self, hwnd: int) -> tuple[int, int]:
        size = self._screenshot.get_client_size_hwnd(hwnd)
        return (int(size[0]), int(size[1])) if size else (0, 0)

    def _regions(self, hwnd: int) -> dict:
        w, h = self._client_size(hwnd)
        return target_module()._regions(w, h)

    def _client_to_screen(self, hwnd: int, x: int, y: int) -> tuple[int, int]:
        """客戶區座標 → 螢幕絕對座標（前景／hybrid 輸入需要）。

        螢幕 = 視窗左上（GetWindowRect）＋邊框偏移（ClientToScreen 差值）＋客戶區座標。
        注意 ``get_client_offset_hwnd`` 回傳的是「視窗左上到客戶區左上」的相對
        偏移，不可直接當絕對座標用。
        """
        rect = self._screenshot.get_window_rect_hwnd(hwnd)
        offset = self._screenshot.get_client_offset_hwnd(hwnd) or (0, 0)
        if rect is None:
            return int(x), int(y)
        return (
            int(rect["x"] + offset[0] + x),
            int(rect["y"] + offset[1] + y),
        )

    @staticmethod
    def _move_cursor(x: int, y: int) -> None:
        """把游標移到螢幕座標（前景輸入的前置設定，不送出任何輸入事件）。"""
        try:
            import pynput.mouse

            pynput.mouse.Controller().position = (int(x), int(y))
            time.sleep(0.02)
        except Exception:
            pass

    # ── 主流程 ──

    def _run(self, name, expected_types, backend_call, expected_check, timeout=8.0) -> TestOutcome:
        outcome = TestOutcome(name=name)
        status = self._target.read_status()
        if status is None or not status.hwnd:
            outcome.backend_detail = "目標狀態檔不可讀（目標未啟動或已結束）"
            return outcome
        baseline_seq = status.seq
        before_state = dict(status.state)

        try:
            ok = backend_call()
        except Exception as e:
            outcome.backend_detail = f"Backend 例外：{e}"
            return outcome
        outcome.backend_ok = bool(ok)
        err = ""
        if self._mode == "frida":
            # 只有 frida 走 bg_input 的錯誤通道；hybrid／前景走 pynput，沒有 last_error。
            err = self._bg.last_error() or ""
        outcome.backend_detail = f"回傳 {bool(ok)}" + (f"；last_error={err}" if err else "")

        # Backend 失敗時不會有新事件：只給短暫等待，不要讓失敗卡住整段 timeout。
        events, final = self._wait_events(
            baseline_seq, expected_types, timeout if ok else min(timeout, 0.5)
        )
        outcome.received_detail = self._format_events(events)
        outcome.gap = self._gap_info(final, baseline_seq, events)
        outcome.received = self._check_received(events, expected_types)
        after_state = dict(final.state) if final else {}
        outcome.expected_ok, outcome.expected_detail = expected_check(
            before_state, after_state, events
        )
        return outcome

    def _wait_events(self, baseline_seq: int, expected_types: set, timeout: float):
        """等待目標端出現預期事件（以 baseline_seq 為基準，只算本次的新事件）。

        必須等事件流「靜止」才算完成：Backend 回傳後，目標程式的狀態檔是
        節流寫入的，最後幾筆事件（例如放開）可能還沒寫出來；只等「出現過某種
        事件」會提早下判定，把殘留的按住狀態誤判成失敗。
        """
        deadline = time.monotonic() + timeout
        events: list = []
        status = None
        last_count = -1
        last_change = time.monotonic()
        while time.monotonic() < deadline:
            status = self._target.read_status()
            if status is not None:
                events = [e for e in status.events if int(e.get("seq", 0)) > baseline_seq]
                if len(events) != last_count:
                    last_count = len(events)
                    last_change = time.monotonic()
                types = {e.get("type") for e in events}
                quiet = time.monotonic() - last_change
                if expected_types.issubset(types) and quiet >= EVENT_QUIET_SEC:
                    return events, status
            time.sleep(0.03)
        return events, status

    @staticmethod
    def _format_events(events: list) -> str:
        if not events:
            return "（沒有事件）"
        parts = []
        for e in events:
            bits = [f"#{e.get('seq')}", str(e.get("type"))]
            if "x" in e:
                bits.append(f"({e.get('x')},{e.get('y')})")
            if "key" in e:
                bits.append(str(e.get("key")))
            if "dy" in e:
                bits.append(f"d=({e.get('dx')},{e.get('dy')})")
            parts.append(" ".join(bits))
        return " | ".join(parts)

    @staticmethod
    def _check_received(events: list, expected_types: set) -> bool:
        types = {e.get("type") for e in events}
        return expected_types.issubset(types)

    @staticmethod
    def _gap_info(status, baseline_seq: int, events: list) -> str:
        """事件跳號（被目標程式的紀錄上限丟棄）提示。"""
        if status is None:
            return ""
        total = int(status.seq) - baseline_seq
        got = len(events)
        notes = []
        if total > got:
            notes.append(f"事件序號跳號 {total - got} 筆（目標程式可能已丟棄部分事件）")
        if int(getattr(status, "dropped", 0)) > 0:
            notes.append(f"目標程式累計丟棄事件 {status.dropped} 筆（紀錄上限）")
        return "；".join(notes)

    # ── 各項測試 ──

    def run_click(self, region: str = "click") -> TestOutcome:
        hwnd = self._target.hwnd
        rect = self._regions(hwnd)[region]
        cx, cy = int(rect.center().x()), int(rect.center().y())

        if self._mode == "frida":

            def call():
                self._bg.set_method("frida")
                return self._bg.click(hwnd, cx, cy, "left", 0, self._cancel)

        else:
            sx, sy = self._client_to_screen(hwnd, cx, cy)

            def call():
                if self._mode == "hybrid":
                    with self._hybrid.focus_guard(
                        self._title(), self._activate(hwnd), hwnd
                    ) as focus_ok:
                        if not focus_ok:
                            return False
                        return self._pynput.send_click(sx, sy, "left", 0, self._cancel)
                self._activate(hwnd)()
                return self._pynput.send_click(sx, sy, "left", 0, self._cancel)

        def expected(before, after, events):
            b = int(before.get("click_count", 0))
            a = int(after.get("click_count", 0))
            return a - b == 1, f"click_count {b} → {a}（+{a - b}）"

        return self._run("Click", {"mouse_press", "mouse_release"}, call, expected)

    def run_key(self, key: str = "a") -> TestOutcome:
        hwnd = self._target.hwnd
        want = _normalize_key(key)

        if self._mode == "frida":

            def call():
                self._bg.set_method("frida")
                return self._bg.send_key(hwnd, key, self._cancel)

        else:

            def call():
                if self._mode == "hybrid":
                    with self._hybrid.focus_guard(
                        self._title(), self._activate(hwnd), hwnd
                    ) as focus_ok:
                        if not focus_ok:
                            return False
                        return self._pynput.send_key(key, self._cancel)
                self._activate(hwnd)()
                return self._pynput.send_key(key, self._cancel)

        def expected(before, after, events):
            pressed = [e for e in events if e.get("type") == "key_press"]
            released = [e for e in events if e.get("type") == "key_release"]
            matched = [e for e in pressed if str(e.get("key", "")).lower() == want.lower()]
            held = want.lower() in [str(k).lower() for k in after.get("pressed_keys", [])]
            ok = bool(matched) and bool(released) and not held
            detail = (
                f"按下鍵={matched[0].get('key') if matched else '無'}"
                f"（期望 {want}）；放開事件={len(released)}；殘留按住={after.get('pressed_keys')}"
            )
            return ok, detail

        return self._run("Key", {"key_press", "key_release"}, call, expected)

    def run_hold(self, key: str = "a", hold_ms: int = 1200) -> TestOutcome:
        """按住鍵：確認「按住期間真的有按下去」與「結束後已放開」。"""
        hwnd = self._target.hwnd
        want = _normalize_key(key)
        observed = {"held": False, "samples": 0}

        def _watch():
            deadline = time.monotonic() + (hold_ms / 1000.0) + 1.5
            while time.monotonic() < deadline:
                status = self._target.read_status()
                if status is not None:
                    observed["samples"] += 1
                    keys = [str(k).lower() for k in status.state.get("pressed_keys", [])]
                    if want.lower() in keys:
                        observed["held"] = True
                        return
                time.sleep(0.05)

        if self._mode == "frida":

            def call():
                self._bg.set_method("frida")
                return self._bg.send_hold_key(hwnd, key, hold_ms, self._cancel)

        else:

            def call():
                if self._mode == "hybrid":
                    with self._hybrid.focus_guard(
                        self._title(), self._activate(hwnd), hwnd
                    ) as focus_ok:
                        if not focus_ok:
                            return False
                        return self._pynput.send_hold_key(key, hold_ms, self._cancel)
                self._activate(hwnd)()
                return self._pynput.send_hold_key(key, hold_ms, self._cancel)

        watcher = threading.Thread(target=_watch, daemon=True)
        watcher.start()
        t0 = time.monotonic()
        outcome = self._run(
            "Hold", {"key_press", "key_release"}, call, self._hold_expected(want, hold_ms)
        )
        elapsed = (time.monotonic() - t0) * 1000
        watcher.join(timeout=2.0)
        if elapsed < hold_ms * 0.5:
            outcome.expected_detail += f"；實際按住耗時 {elapsed:.0f}ms"
        if not observed["held"]:
            # 按住期間必須真的觀察到「按鍵處於按下狀態」，否則語意層不成立。
            outcome.expected_ok = False
            outcome.expected_detail += "；按住期間未觀察到按鍵處於按下狀態"
        else:
            outcome.expected_detail += "；按住期間已觀察到按鍵按下"
        return outcome

    def _hold_expected(self, want: str, hold_ms: int):
        def expected(before, after, events):
            pressed = [e for e in events if e.get("type") == "key_press"]
            released = [e for e in events if e.get("type") == "key_release"]
            matched = [e for e in pressed if str(e.get("key", "")).lower() == want.lower()]
            held = want.lower() in [str(k).lower() for k in after.get("pressed_keys", [])]
            ok = bool(matched) and bool(released) and not held
            detail = (
                f"按下鍵={matched[0].get('key') if matched else '無'}（期望 {want}）；"
                f"放開事件={len(released)}；殘留按住={after.get('pressed_keys')}"
            )
            return ok, detail

        return expected

    def run_drag(self, dx: int = 90, dy: int = 60) -> TestOutcome:
        """拖曳：起點取物件目前位置，終點往右下偏移（物件必須真的移動）。"""
        hwnd = self._target.hwnd
        regions = self._regions(hwnd)
        area = regions["drag"]
        status = self._target.read_status()
        pos = (status.state.get("drag_pos") if status else None) or [0.0, 0.0]
        size = target_module().DRAG_OBJECT_SIZE
        start = (int(pos[0] + size / 2), int(pos[1] + size / 2))
        start = (
            int(min(max(start[0], area.left() + 4), area.right() - 4)),
            int(min(max(start[1], area.top() + 4), area.bottom() - 4)),
        )
        end = (
            int(min(start[0] + dx, area.right() - size / 2)),
            int(min(start[1] + dy, area.bottom() - size / 2)),
        )

        if self._mode == "frida":

            def call():
                self._bg.set_method("frida")
                return self._bg.drag(hwnd, start[0], start[1], end[0], end[1], "left", self._cancel)

        else:
            s1 = self._client_to_screen(hwnd, start[0], start[1])
            s2 = self._client_to_screen(hwnd, end[0], end[1])

            def call():
                if self._mode == "hybrid":
                    with self._hybrid.focus_guard(
                        self._title(), self._activate(hwnd), hwnd
                    ) as focus_ok:
                        if not focus_ok:
                            return False
                        return self._pynput.send_drag(
                            s1[0], s1[1], s2[0], s2[1], "left", self._cancel
                        )
                self._activate(hwnd)()
                return self._pynput.send_drag(s1[0], s1[1], s2[0], s2[1], "left", self._cancel)

        def expected(before, after, events):
            b = before.get("drag_pos") or [0, 0]
            a = after.get("drag_pos") or [0, 0]
            moved = bool(after.get("drag_moved"))
            dist = float(after.get("drag_distance") or 0)
            ok = moved and dist > 0 and a != b
            detail = (
                f"物件位置 {b} → {a}；drag_moved={moved}；距離={dist:.0f}px；"
                f"起點={start} 終點={end}"
            )
            return ok, detail

        return self._run("Drag", {"mouse_press", "mouse_move", "mouse_release"}, call, expected)

    def run_scroll(self, amount: int = 1) -> TestOutcome:
        hwnd = self._target.hwnd
        rect = self._regions(hwnd)["scroll"]
        cx, cy = int(rect.center().x()), int(rect.center().y())

        if self._mode == "frida":

            def call():
                self._bg.set_method("frida")
                # 後台滾輪：正值 = 上（與 bg_input.scroll 契約一致）
                return self._bg.scroll(hwnd, cx, cy, amount, False, self._cancel)

        else:
            sx, sy = self._client_to_screen(hwnd, cx, cy)

            def call():
                # 前景滾輪送在游標當下位置：先把游標移到滾輪區（測試前置設定，
                # 不是輸入機制本身）。
                self._move_cursor(sx, sy)
                if self._mode == "hybrid":
                    with self._hybrid.focus_guard(
                        self._title(), self._activate(hwnd), hwnd
                    ) as focus_ok:
                        if not focus_ok:
                            return False
                        return self._pynput.send_scroll(amount, "WheelUp", self._cancel)
                self._activate(hwnd)()
                return self._pynput.send_scroll(amount, "WheelUp", self._cancel)

        def expected(before, after, events):
            b = int(before.get("scroll_events", 0))
            a = int(after.get("scroll_events", 0))
            return a - b >= 1, f"scroll_events {b} → {a}；累積 dy={after.get('scroll_dy')}"

        return self._run("Scroll", {"mouse_wheel"}, call, expected)

    # ── 取消／Release ──

    def run_cancel_release(
        self, key: str = "a", hold_ms: int = 3000, cancel_after_ms: int = 500
    ) -> TestOutcome:
        """按下後中途取消：確認 UP 仍被送出、殘留按住為空、且提早結束。

        產品的既有語意：DOWN 送出後的取消只會「提早放開」，放開永不受取消閘阻擋
        （``core/16_bg_input.py`` 的 ``send_hold_key`` 以 finally 送 UP、
        ``core/03_pynput_input.py`` 以 _PressLedger 釋放）。本測試不修改產品
        行為，只驗證實際事件序列是否符合此語意。
        """
        outcome = TestOutcome(name="Cancel/Release")
        status = self._target.read_status()
        if status is None or not status.hwnd:
            outcome.backend_detail = "目標程式未啟動"
            outcome.received_detail = "無狀態"
            outcome.expected_detail = "無狀態"
            return outcome
        hwnd = status.hwnd
        want = _normalize_key(key)
        baseline_seq = status.seq
        self.reset_cancel()
        result: dict = {}

        def call():
            if self._mode == "frida":
                self._bg.set_method("frida")
                result["ok"] = self._bg.send_hold_key(hwnd, key, hold_ms, self._cancel)
            else:

                def _do():
                    if self._mode == "hybrid":
                        with self._hybrid.focus_guard(
                            self._title(), self._activate(hwnd), hwnd
                        ) as focus_ok:
                            if not focus_ok:
                                result["ok"] = False
                                return
                            result["ok"] = self._pynput.send_hold_key(key, hold_ms, self._cancel)
                        return
                    self._activate(hwnd)()
                    result["ok"] = self._pynput.send_hold_key(key, hold_ms, self._cancel)

                _do()

        worker = threading.Thread(target=call, daemon=True)
        t0 = time.monotonic()
        worker.start()
        time.sleep(cancel_after_ms / 1000.0)
        self._cancel.set()
        worker.join(timeout=15)
        elapsed = (time.monotonic() - t0) * 1000

        outcome.backend_ok = bool(result.get("ok"))
        outcome.backend_detail = (
            f"取消後 Backend 回傳 {result.get('ok')}；實際耗時 {elapsed:.0f}ms"
            f"（按住設定 {hold_ms}ms）"
        )
        events, final = self._wait_events(
            baseline_seq, {"key_press", "key_release"}, 8.0 if outcome.backend_ok else 0.5
        )
        outcome.received_detail = self._format_events(events)
        outcome.gap = self._gap_info(final, baseline_seq, events)
        outcome.received = self._check_received(events, {"key_press", "key_release"})

        after = dict(final.state) if final else {}
        pressed = [e for e in events if e.get("type") == "key_press"]
        released = [e for e in events if e.get("type") == "key_release"]
        matched_press = [e for e in pressed if str(e.get("key", "")).lower() == want.lower()]
        still_held = [k for k in after.get("pressed_keys", []) if str(k).lower() == want.lower()]
        # 放開必須發生在按下之後；且取消後必須提早結束（沒等到 hold_ms 結束）。
        released_after_press = bool(matched_press) and bool(released)
        early = elapsed < hold_ms
        outcome.expected_ok = released_after_press and not still_held and early
        outcome.expected_detail = (
            f"按下 {want}×{len(matched_press)}；放開事件={len(released)}；"
            f"殘留按住={after.get('pressed_keys')}；"
            f"{'提早' if early else '未提早'}結束（{elapsed:.0f}ms < {hold_ms}ms）"
        )
        return outcome

    # ── 輔助 ──

    def _title(self) -> str:
        return target_module().WINDOW_TITLE

    def _activate(self, hwnd: int):
        """給 focus_guard 用的 activate_fn（以 hwnd 精準定位）。

        簽章同時符合兩種呼叫：``focus_guard`` 會傳入 title，裸呼叫則不傳。
        """
        return lambda _title=None: self._screenshot.activate_window_hwnd(hwnd)

    def detach(self) -> None:
        """解除 Frida 注入（工作台結束時呼叫）。"""
        try:
            self._bg.detach()
        except Exception:
            pass


# ── GUI ─────────────────────────────────────────────────────────────


class _BenchSignals(QObject):
    result_ready = pyqtSignal(object)
    finished = pyqtSignal()


class InputTestBenchWindow(QMainWindow):
    """測試工作台視窗。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OCR 輸入後台測試工作台")
        self.resize(980, 720)
        self._target = TargetProcess()
        self._runner: BenchRunner | None = None
        self._signals = _BenchSignals()
        self._signals.result_ready.connect(self._on_result)
        self._signals.finished.connect(self._on_finished)
        self._last_seq = 0
        self._busy = False
        self._build_ui()

        self._poll = QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._refresh_target)
        self._poll.start()

    # ── UI ──

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        # 目標程式
        target_box = QGroupBox("目標程式")
        trow = QHBoxLayout(target_box)
        self._btn_start = QPushButton("啟動目標程式")
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop = QPushButton("關閉目標程式")
        self._btn_stop.clicked.connect(self._on_stop)
        self._lbl_target = QLabel("狀態：未啟動")
        trow.addWidget(self._btn_start)
        trow.addWidget(self._btn_stop)
        trow.addWidget(self._lbl_target, 1)
        layout.addWidget(target_box)

        # 測試控制
        ctrl_box = QGroupBox("測試控制")
        crow = QHBoxLayout(ctrl_box)
        self._cmb_mode = QComboBox()
        for mode in MODES:
            self._cmb_mode.addItem(MODE_LABELS[mode], mode)
        self._cmb_mode.setCurrentIndex(0)
        self._edt_key = QLineEdit("a")
        self._edt_key.setMaximumWidth(80)
        self._spin_hold = QSpinBox()
        self._spin_hold.setRange(200, 10000)
        self._spin_hold.setValue(1200)
        self._spin_hold.setSuffix(" ms")
        self._btn_click = QPushButton("Click")
        self._btn_key = QPushButton("Key")
        self._btn_hold = QPushButton("Hold")
        self._btn_drag = QPushButton("Drag")
        self._btn_scroll = QPushButton("Scroll")
        self._btn_cancel_release = QPushButton("取消／Release")
        self._btn_click.clicked.connect(lambda: self._run_test("click"))
        self._btn_key.clicked.connect(lambda: self._run_test("key"))
        self._btn_hold.clicked.connect(lambda: self._run_test("hold"))
        self._btn_drag.clicked.connect(lambda: self._run_test("drag"))
        self._btn_scroll.clicked.connect(lambda: self._run_test("scroll"))
        self._btn_cancel_release.clicked.connect(lambda: self._run_test("cancel_release"))
        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.clicked.connect(self._on_cancel)
        self._btn_reset = QPushButton("重置")
        self._btn_reset.clicked.connect(self._on_reset)
        crow.addWidget(QLabel("模式"))
        crow.addWidget(self._cmb_mode)
        crow.addWidget(QLabel("按鍵"))
        crow.addWidget(self._edt_key)
        crow.addWidget(QLabel("按住"))
        crow.addWidget(self._spin_hold)
        for btn in (
            self._btn_click,
            self._btn_key,
            self._btn_hold,
            self._btn_drag,
            self._btn_scroll,
            self._btn_cancel_release,
        ):
            crow.addWidget(btn)
        crow.addWidget(self._btn_cancel)
        crow.addWidget(self._btn_reset)
        crow.addStretch(1)
        layout.addWidget(ctrl_box)

        # 結果 + 事件
        splitter = QSplitter(Qt.Orientation.Vertical)
        self._tree = QTreeWidget()
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(
            ["測試", "Backend", "Target Received", "Expected Behavior", "詳情"]
        )
        splitter.addWidget(self._tree)
        self._lbl_error = QLabel("")
        self._lbl_error.setStyleSheet("color:#e05a5a;")
        splitter.addWidget(self._lbl_error)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

    # ── 目標程序 ──

    def _on_start(self) -> None:
        self._on_stop()
        try:
            status = self._target.start()
        except Exception as e:
            self._lbl_target.setText(f"狀態：啟動失敗（{e}）")
            self._lbl_error.setText(str(e))
            return
        self._last_seq = 0
        self._runner = BenchRunner(self._target, self._cmb_mode.currentData())
        self._lbl_target.setText(
            f"狀態：執行中｜session={status.session}｜pid={status.pid}｜hwnd={status.hwnd}"
        )

    def _on_stop(self) -> None:
        self._target.stop()
        self._lbl_target.setText("狀態：未啟動")

    def _refresh_target(self) -> None:
        status = self._target.read_status()
        if status is None:
            if self._target.is_running():
                self._lbl_target.setText("狀態：等待狀態檔…")
            return
        if status.closed and self._target.is_running():
            self._lbl_target.setText("狀態：目標已關閉（行程可能仍在結束）")
        else:
            self._lbl_target.setText(
                f"狀態：執行中｜session={status.session}｜pid={status.pid}"
                f"｜hwnd={status.hwnd}｜seq={status.seq}"
            )
        new_events = [e for e in status.events if int(e.get("seq", 0)) > self._last_seq]
        if new_events:
            self._last_seq = int(new_events[-1].get("seq", self._last_seq))
            self._append_events(new_events)

    def _append_events(self, events: list) -> None:
        for e in events:
            parts = [f"#{e.get('seq')}", str(e.get("type"))]
            if "x" in e:
                parts.append(f"({e.get('x')},{e.get('y')})")
            if "key" in e:
                parts.append(str(e.get("key")))
            if "dy" in e:
                parts.append(f"d=({e.get('dx')},{e.get('dy')})")
            self._tree.addTopLevelItem(QTreeWidgetItem(["事件", " ".join(parts), "", "", ""]))

    # ── 測試 ──

    def _run_test(self, kind: str) -> None:
        if self._busy:
            return
        if self._runner is None or not self._target.is_running():
            self._lbl_error.setText("目標程式未啟動")
            return
        mode = self._cmb_mode.currentData()
        key = self._edt_key.text() or "a"
        hold_ms = self._spin_hold.value()
        # runner 在 GUI 執行緒建立（cancel Event 必須是同一個，取消按鈕才有效）。
        runner = BenchRunner(self._target, mode)
        runner.reset_cancel()
        self._runner = runner
        self._busy = True
        threading.Thread(
            target=self._do_test, args=(runner, kind, key, hold_ms), daemon=True
        ).start()

    def _do_test(self, runner: BenchRunner, kind: str, key: str, hold_ms: int) -> None:
        try:
            if kind == "click":
                outcome = runner.run_click()
            elif kind == "key":
                outcome = runner.run_key(key)
            elif kind == "hold":
                outcome = runner.run_hold(key, hold_ms)
            elif kind == "drag":
                outcome = runner.run_drag()
            elif kind == "cancel_release":
                outcome = runner.run_cancel_release(key)
            else:
                outcome = runner.run_scroll()
        except Exception as e:
            outcome = TestOutcome(name=kind, backend_detail=f"例外：{e}")
        self._signals.result_ready.emit(outcome)

    def _on_result(self, outcome: TestOutcome) -> None:
        self._tree.addTopLevelItem(
            QTreeWidgetItem(
                [
                    outcome.name,
                    "OK" if outcome.backend_ok else f"NG｜{outcome.backend_detail}",
                    "OK" if outcome.received else f"NG｜{outcome.received_detail}",
                    "OK" if outcome.expected_ok else f"NG｜{outcome.expected_detail}",
                    outcome.gap,
                ]
            )
        )
        self._lbl_error.setText("" if outcome.passed else outcome.summary())
        self._busy = False

    def _on_cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()
            self._lbl_error.setText("已送出取消訊號")

    def _on_reset(self) -> None:
        self._tree.clear()
        self._lbl_error.setText("")
        self._last_seq = 0

    def _on_finished(self) -> None:
        self._busy = False

    def closeEvent(self, event):
        """關閉工作台：解除注入並正常結束目標程式。"""
        if self._runner is not None:
            self._runner.detach()
        self._target.stop()
        super().closeEvent(event)


# ── CLI ─────────────────────────────────────────────────────────────


def _self_check() -> int:
    """離線自我檢查：不需要目標程式、不需要 Frida。"""
    mod = target_module()
    a, b = mod.new_session_token("bench"), mod.new_session_token("bench")
    assert a != b, "session token 必須唯一"
    assert mod.default_status_path(a) != mod.default_status_path(b)

    outcome = TestOutcome(name="demo")
    assert not outcome.passed, "三層未完成時不得視為通過"
    outcome.backend_ok = True
    assert not outcome.passed, "僅 Backend 成功不得視為通過"
    outcome.received = True
    assert not outcome.passed, "僅兩層成功不得視為通過"
    outcome.expected_ok = True
    assert outcome.passed, "三層皆成功才算通過"

    regions = mod._regions(900, 640)
    for name in ("click", "hold", "key", "drag", "scroll"):
        assert name in regions, f"缺少測試區：{name}"
        assert regions[name].width() > 0 and regions[name].height() > 0

    assert BenchRunner._gap_info(TargetStatus(seq=10), 5, []) != "", "必須偵測事件跳號"
    assert "跳號" in BenchRunner._gap_info(TargetStatus(seq=10), 5, [])
    assert BenchRunner._gap_info(TargetStatus(seq=5), 5, []) == ""

    assert _normalize_key("a") == "A"
    assert _normalize_key("space") == "Space"

    print("  [OK] session token 唯一")
    print("  [OK] 三層判定不合併（Backend / Received / Expected 各自獨立）")
    print("  [OK] 事件跳號偵測")
    print("  [OK] 測試區幾何與按鍵名稱對照")
    print("\n=== Input Test Bench Self-Check 完成 ===")
    return 0


def _integration(mode: str = "frida", timeout: float = 25.0) -> int:
    """真實整合驗證：啟動目標程式 → 走產品 Backend → 三層判定。"""
    target = TargetProcess()
    outcomes: list[TestOutcome] = []
    try:
        status = target.start()
        print(
            f"目標程式：session={status.session} pid={status.pid} hwnd={status.hwnd} dpr={status.dpr}"
        )
        runner = BenchRunner(target, mode)
        for name, fn in (
            ("Click", runner.run_click),
            ("Key", lambda: runner.run_key("a")),
            ("Hold", lambda: runner.run_hold("a", 1000)),
            ("Drag", runner.run_drag),
            ("Scroll", runner.run_scroll),
            ("Cancel/Release", lambda: runner.run_cancel_release("a")),
        ):
            outcome = fn()
            outcomes.append(outcome)
            print(f"\n--- {name} ---")
            print(outcome.summary())
            print(f"  Backend：{outcome.backend_detail}")
            print(f"  Received：{outcome.received_detail}")
            print(f"  Expected：{outcome.expected_detail}")
            if outcome.gap:
                print(f"  {outcome.gap}")
        runner.detach()
    except Exception as e:
        print(f"整合驗證例外：{e}")
        return 2
    finally:
        target.stop()

    failed = [o for o in outcomes if not o.passed]
    print(f"\n=== 整合驗證：{len(outcomes) - len(failed)}/{len(outcomes)} 通過（模式 {mode}）===")
    for o in failed:
        print(f"  FAIL：{o.summary()}")
    return 0 if not failed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="input_test_bench",
        description="OCR Trigger Clicker 輸入後台測試工作台",
    )
    parser.add_argument("--self-check", action="store_true", help="離線自我檢查（不啟動目標程式）")
    parser.add_argument(
        "--integration", action="store_true", help="真實整合驗證（啟動目標程式並走產品 Backend）"
    )
    parser.add_argument(
        "--mode", default="frida", choices=list(MODES), help="整合驗證使用的輸入模式"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_check:
        return _self_check()
    if args.integration:
        return _integration(args.mode)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = InputTestBenchWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
