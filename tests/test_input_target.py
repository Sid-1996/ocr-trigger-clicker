"""devtools/input_target.py 的測試。

不依賴 Frida、遊戲或人工點擊：只用真實的 PyQt6 事件物件送到真實視窗，
驗證事件記錄、語意狀態、狀態檔協定與節流行為。
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent

from _loader import load_sibling

ROOT = Path(__file__).resolve().parents[1]
_target = load_sibling("input_target", "devtools/input_target.py")


# ── 事件物件輔助 ────────────────────────────────────────────────────


def _press(app, window, x, y, button=Qt.MouseButton.LeftButton):
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, y),
        QPointF(x, y),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(window, event)


def _release(app, window, x, y, button=Qt.MouseButton.LeftButton):
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(x, y),
        QPointF(x, y),
        button,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(window, event)


def _move(app, window, x, y):
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(window, event)


def _wheel(app, window, x, y, dy=120):
    event = QWheelEvent(
        QPointF(x, y),
        QPointF(x, y),
        QPoint(0, 0),
        QPoint(0, dy),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    app.sendEvent(window, event)


def _key(app, window, qt_key, text=""):
    event = QKeyEvent(QEvent.Type.KeyPress, qt_key, Qt.KeyboardModifier.NoModifier, text)
    app.sendEvent(window, event)


def _key_release(app, window, qt_key):
    event = QKeyEvent(QEvent.Type.KeyRelease, qt_key, Qt.KeyboardModifier.NoModifier, "")
    app.sendEvent(window, event)


@pytest.fixture
def window(qt_app, tmp_path):
    """測試用目標視窗（offscreen）。"""
    win = _target.InputTargetWindow(
        session="test-session", status_path=tmp_path / "status.json", size=(900, 640)
    )
    yield win
    win.close()


def _center(window, name):
    rect = window.regions()[name]
    return rect.center().x(), rect.center().y()


# ── 1. session token 唯一性 ─────────────────────────────────────────


def test_session_token_is_unique():
    a = _target.new_session_token()
    b = _target.new_session_token()
    assert a != b, "每次啟動的 session token 必須唯一"
    assert a.startswith("input-target-")


def test_default_status_path_is_per_run():
    """狀態檔路徑必須 per-run，避免多個測試程序互相覆寫。"""
    a = _target.default_status_path(_target.new_session_token())
    b = _target.default_status_path(_target.new_session_token())
    assert a != b
    assert a.parent == b.parent
    assert a.name.startswith("otc_input_target_")


# ── 2. 事件序號與欄位 ───────────────────────────────────────────────


def test_event_seq_is_monotonic():
    log = _target.EventLog()
    for i in range(20):
        log.record("mouse_move", x=i, y=i)
    seqs = [e["seq"] for e in log.events]
    assert seqs == list(range(1, 21)), "seq 必須單調遞增且連續"
    assert log.seq == 20


def test_event_fields_are_correct():
    log = _target.EventLog()
    press = log.record("mouse_press", x=10.4, y=20.6, buttons=1)
    wheel = log.record("mouse_wheel", x=5, y=6, buttons=0, extra={"dx": 0, "dy": 120})
    key = log.record("key_press", key="A", extra={"text": "a"})

    assert press["type"] == "mouse_press"
    assert press["x"] == 10 and press["y"] == 21, "座標必須四捨五入成整數"
    assert press["buttons"] == 1
    assert "t" in press and isinstance(press["t"], float), "事件必須帶時間"
    assert wheel["dy"] == 120
    assert key["key"] == "A" and key["text"] == "a"


def test_event_log_respects_limit():
    """事件紀錄必須有上限，避免長時間執行無限制累積。"""
    log = _target.EventLog(limit=5)
    for i in range(50):
        log.record("mouse_move", x=i, y=i)
    assert len(log.events) == 5
    assert log.dropped == 45
    assert log.events[-1]["seq"] == 50, "保留的必須是最新的事件"


# ── 3. 狀態資料結構 ─────────────────────────────────────────────────


def test_status_payload_structure():
    state = _target.TargetState()
    state.click_count = 3
    state.pressed_keys.add("A")
    payload = _target.build_status(
        session="s1",
        seq=7,
        events=[],
        state=state.to_dict(),
        hwnd=1234,
        dpr=1.25,
        closed=False,
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
    assert payload["session"] == "s1"
    assert payload["pid"] == __import__("os").getpid()
    assert payload["hwnd"] == 1234
    assert payload["dpr"] == 1.25
    assert payload["closed"] is False
    assert payload["state"]["click_count"] == 3
    assert payload["state"]["pressed_keys"] == ["A"]


def test_state_dict_contains_required_fields():
    data = _target.TargetState().to_dict()
    for key in (
        "click_count",
        "pressed_keys",
        "mouse_buttons",
        "mouse_buttons_names",
        "drag_pos",
        "scroll_events",
        "closed",
    ):
        assert key in data, f"狀態缺少欄位：{key}"


# ── 4. 狀態檔寫入行為 ───────────────────────────────────────────────


def test_status_write_is_throttled(qt_app, tmp_path):
    """大量變更在節流期間內只寫一次。"""
    path = tmp_path / "status.json"
    calls = []

    def _provider():
        calls.append(1)
        return {"session": "s", "seq": len(calls)}

    writer = _target.StatusWriter(path, _provider, interval_ms=150)
    for _ in range(20):
        writer.mark_dirty()

    assert calls == [], "節流期間內不應立即寫出"
    assert writer.writes == 0

    qt_app.processEvents()
    time.sleep(0.25)
    qt_app.processEvents()

    assert len(calls) == 1, f"節流期間內只應寫一次，實際 {len(calls)} 次"
    assert writer.writes == 1
    assert json.loads(path.read_text(encoding="utf-8"))["session"] == "s"


def test_status_write_failure_does_not_raise(qt_app, tmp_path):
    """狀態檔寫入失敗不得讓 GUI 崩潰（只記錄失敗）。"""
    bad_path = tmp_path / "missing-dir" / "status.json"
    writer = _target.StatusWriter(bad_path, lambda: {"session": "s"})
    writer.mark_dirty()
    assert writer.flush() is False, "寫入失敗必須回 False"
    assert writer.failures == 1
    assert writer.last_error


def test_status_provider_failure_does_not_raise(qt_app, tmp_path):
    """狀態組裝失敗同樣不得拋例外。"""

    def _boom():
        raise RuntimeError("boom")

    writer = _target.StatusWriter(tmp_path / "status.json", _boom)
    writer.mark_dirty()
    assert writer.flush() is False
    assert writer.failures == 1
    assert "provider" in writer.last_error


# ── 5. 視窗實際收到的事件 ───────────────────────────────────────────


def test_window_records_click_and_key(qt_app, window):
    cx, cy = _center(window, "click")
    _press(qt_app, window, cx, cy)
    _release(qt_app, window, cx, cy)
    _key(qt_app, window, Qt.Key.Key_A, "a")

    assert window.state.click_count == 1
    assert "A" in window.state.pressed_keys

    types = [e["type"] for e in window.log.events]
    assert "mouse_press" in types and "mouse_release" in types and "key_press" in types

    press = next(e for e in window.log.events if e["type"] == "mouse_press")
    assert press["region"] == "click"
    assert press["x"] == pytest.approx(cx, abs=1)
    assert window.state.mouse_buttons == 0, "放開後滑鼠按鍵狀態必須歸零"


def test_window_tracks_hold_state(qt_app, window):
    hx, hy = _center(window, "hold")
    _press(qt_app, window, hx, hy)
    assert window.state.hold_count == 1
    assert window.state.hold_active is True
    _release(qt_app, window, hx, hy)
    assert window.state.hold_active is False
    assert window.state.hold_max_ms >= 0


def test_window_records_scroll(qt_app, window):
    sx, sy = _center(window, "scroll")
    _wheel(qt_app, window, sx, sy, dy=120)
    _wheel(qt_app, window, sx, sy, dy=-120)
    assert window.state.scroll_events == 2
    assert window.state.scroll_dy == 0
    wheel = next(e for e in window.log.events if e["type"] == "mouse_wheel")
    assert wheel["region"] == "scroll"


def test_window_drag_moves_object(qt_app, window):
    """Drag 必須真的移動物件（畫面上看得見），不是只記錄滑鼠座標。"""
    dx, dy = _center(window, "drag")
    before = window.state.drag_pos
    _press(qt_app, window, dx, dy)
    assert window.state.drag_active is True
    _move(qt_app, window, dx + 60, dy + 40)
    _release(qt_app, window, dx + 60, dy + 40)

    after = window.state.drag_pos
    assert after != before, "拖曳後物件位置必須改變"
    assert window.state.drag_moved is True
    assert window.state.drag_distance > 0
    assert window.state.drag_active is False
    assert window.state.drag_end is not None


def test_window_key_release_clears_pressed(qt_app, window):
    _key(qt_app, window, Qt.Key.Key_Space, " ")
    assert "Space" in window.state.pressed_keys
    _key_release(qt_app, window, Qt.Key.Key_Space)
    assert "Space" not in window.state.pressed_keys


# ── 6. 關閉時寫入 closed=true ───────────────────────────────────────


def test_close_writes_closed_true(qt_app, tmp_path):
    path = tmp_path / "status.json"
    win = _target.InputTargetWindow(session="close-session", status_path=path, size=(900, 640))
    win.show()
    win.write_status_now()
    win.close()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["closed"] is True
    assert data["session"] == "close-session"
    assert data["hwnd"] != 0, "狀態檔必須帶上視窗代碼"


def test_status_file_contains_live_events(qt_app, window, tmp_path):
    """狀態檔必須帶著實際收到的事件（供後續工作台判讀）。"""
    cx, cy = _center(window, "click")
    _press(qt_app, window, cx, cy)
    window.write_status_now()

    data = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert data["events"], "狀態檔必須包含事件"
    assert data["events"][-1]["type"] == "mouse_press"
    assert data["state"]["click_count"] == 1
    assert data["seq"] >= 1


# ── 7. --self-check ─────────────────────────────────────────────────


def test_self_check_exits_zero():
    """--self-check 必須在沒有視窗操作的情況下正常結束。"""
    result = subprocess.run(
        [sys.executable, str(ROOT / "devtools" / "input_target.py"), "--self-check"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, f"self-check 失敗：\n{result.stdout}\n{result.stderr}"
    assert "Self-Check 完成" in result.stdout


def test_cli_parser_supports_required_flags():
    parser = _target.build_parser()
    args = parser.parse_args(
        ["--session", "abc", "--status-path", "x.json", "--size", "800x600", "--self-check"]
    )
    assert args.session == "abc"
    assert args.status_path == "x.json"
    assert args.size == "800x600"
    assert args.self_check is True


def test_parse_size_handles_bad_input():
    assert _target.parse_size("900x640") == (900, 640)
    assert _target.parse_size("900×640") == (900, 640)
    assert _target.parse_size("garbage") == (900, 640)
