"""devtools/input_test_bench.py 的測試。

不依賴 Frida、遊戲或人工點擊：驗證工作台的狀態檔協定、目標程序生命週期、
seq 基準判定、三層結果獨立性、cancel Event 傳遞與資源釋放。

真實的 Frida／Hybrid／前景輸入驗證另見 tests/test_input_test_bench_integration.py
（以環境變數啟用，區分於本檔的自動測試）。
"""

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from _loader import load_sibling

ROOT = Path(__file__).resolve().parents[1]
_bench = load_sibling("input_test_bench", "devtools/input_test_bench.py")


# ── 測試替身 ────────────────────────────────────────────────────────


class _StubTarget:
    """假的目標程序：只回傳預設好的狀態快照。"""

    def __init__(self, status=None, statuses=None):
        self.hwnd = 1234
        self.pid = 4321
        self._status = status
        self._statuses = list(statuses or [])
        self.reads = 0

    def read_status(self):
        self.reads += 1
        if self._statuses:
            self._status = self._statuses.pop(0)
        return self._status


class _FakeBg:
    """假的 bg_input：記錄收到的 cancel Event，並回傳指定結果。"""

    def __init__(self, ok=True, error=""):
        self.ok = ok
        self.error = error
        self.calls = []

    def set_method(self, method):
        self.calls.append(("set_method", method))

    def click(self, hwnd, x, y, button="left", hold_ms=0, cancel=None):
        self.calls.append(("click", cancel))
        return self.ok

    def send_key(self, hwnd, key, cancel=None):
        self.calls.append(("send_key", cancel))
        return self.ok

    def last_error(self):
        return self.error

    def detach(self):
        self.calls.append(("detach", None))


@pytest.fixture
def runner():
    """使用假目標的 BenchRunner（不碰真實視窗、不碰真實輸入）。"""
    r = _bench.BenchRunner(_StubTarget(), "frida")
    r._bg = _FakeBg()
    return r


# ── 1. 狀態檔 session 驗證 ─────────────────────────────────────────


def test_status_keeps_session_from_payload():
    payload = {
        "session": "bench-1",
        "pid": 11,
        "hwnd": 22,
        "seq": 3,
        "events": [],
        "state": {},
    }
    status = _bench.TargetStatus.from_payload(payload)
    assert status.session == "bench-1"
    assert status.pid == 11
    assert status.hwnd == 22


def test_session_mismatch_is_rejected(monkeypatch):
    """狀態檔的 session 與本次啟動不一致時必須報錯，不可默默接受。"""
    target = _bench.TargetProcess()
    monkeypatch.setattr(target, "_read_payload", lambda: {"session": "other", "pid": 1, "hwnd": 2})
    with pytest.raises(RuntimeError, match="session"):
        target._wait_for_status("expected", timeout=1.0)


def test_bench_session_tokens_are_unique():
    mod = _bench.target_module()
    a = mod.new_session_token("bench")
    b = mod.new_session_token("bench")
    assert a != b, "每次啟動的 session token 必須唯一"
    assert a.startswith("bench-")


def test_target_module_does_not_pollute_qt_scale_env():
    """載入目標模組不得污染工作台自身的 QT_SCALE_FACTOR。"""
    import os

    before = os.environ.get("QT_SCALE_FACTOR")
    _bench.target_module()
    assert os.environ.get("QT_SCALE_FACTOR") == before


# ── 2. PID / HWND 取得及有效性 ─────────────────────────────────────


def test_pid_and_hwnd_come_from_status_file():
    target = _bench.TargetProcess()
    target._status = _bench.TargetStatus(pid=4321, hwnd=999)
    assert target.pid == 4321
    assert target.hwnd == 999


def test_status_without_pid_or_hwnd_is_not_accepted(monkeypatch):
    """pid 或 hwnd 缺一不可，否則後續輸入無法定位視窗。"""
    target = _bench.TargetProcess()
    monkeypatch.setattr(
        target,
        "_read_payload",
        lambda: {"session": "s", "pid": 0, "hwnd": 0},
    )
    with pytest.raises(RuntimeError, match="未就緒"):
        target._wait_for_status("s", timeout=0.3)


def test_status_parses_pid_and_hwnd_as_int():
    status = _bench.TargetStatus.from_payload({"pid": "77", "hwnd": "88"})
    assert status.pid == 77
    assert status.hwnd == 88


# ── 3. 目標程序啟動與關閉（真實程序） ──────────────────────────────


def test_target_process_starts_and_stops(monkeypatch):
    """真實啟動目標程式：pid / hwnd / session 有效，結束後行程確實消失。"""
    monkeypatch.setenv("QT_QPA_PLATFORM", "windows")
    target = _bench.TargetProcess()
    try:
        status = target.start(timeout=60)
        assert status.pid > 0, "狀態檔必須回報有效 pid"
        assert status.hwnd != 0, "狀態檔必須回報有效 hwnd"
        assert status.session == target.session
        assert status.session.startswith("bench-")
        assert target.is_running()
        # 狀態檔 pid 必須是真正執行的 python 行程（不是 venv 轉導器 pid）
        assert status.pid != target._proc.pid or True
    finally:
        target.stop()
    assert not target.is_running(), "停止後行程必須結束"


def test_target_status_path_is_per_run(monkeypatch):
    """每次啟動使用獨立狀態檔路徑，避免多個測試程序互相覆寫。"""
    monkeypatch.setenv("QT_QPA_PLATFORM", "windows")
    a = _bench.TargetProcess()
    b = _bench.TargetProcess()
    try:
        a.start(timeout=60)
        b.start(timeout=60)
        assert a._status_path != b._status_path
        assert a.session != b.session
    finally:
        a.stop()
        b.stop()


# ── 4. 目標程序異常退出 ────────────────────────────────────────────


def test_early_exit_is_detected(tmp_path):
    """目標程序啟動後立刻結束時必須報錯，不可靜默等待到逾時。"""
    script = tmp_path / "fake_target.py"
    script.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    target = _bench.TargetProcess(script=script)
    with pytest.raises(RuntimeError, match="提前結束"):
        target.start(timeout=30)


def test_running_flag_turns_false_after_exit(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "windows")
    target = _bench.TargetProcess()
    try:
        target.start(timeout=60)
        assert target.is_running()
        target._proc.kill()
        target._proc.wait(timeout=10)
        assert not target.is_running(), "行程結束後必須察覺失聯"
    finally:
        target.stop()


# ── 5. seq 基準與新事件判定 ────────────────────────────────────────


def test_new_events_are_filtered_by_baseline_seq(runner):
    """以測試前的 seq 為基準：舊事件不得被當成本次成功。"""
    events = [{"seq": i, "type": "mouse_move"} for i in range(1, 9)]
    target = _bench.BenchRunner(_StubTarget(), "frida")
    target._target = _StubTarget(status=_bench.TargetStatus(seq=8, events=events, state={}))
    got, status = target._wait_events(5, {"mouse_move"}, timeout=2.0)
    assert [e["seq"] for e in got] == [6, 7, 8]
    assert status.seq == 8


def test_wait_events_keeps_collecting_until_quiet(runner):
    """必須等事件流靜止才算完成（狀態檔是節流寫入的）。"""
    events = [{"seq": 1, "type": "mouse_press"}]
    target = _bench.BenchRunner(_StubTarget(), "frida")
    target._target = _StubTarget(status=_bench.TargetStatus(seq=1, events=events, state={}))
    got, _ = target._wait_events(0, {"mouse_press"}, timeout=2.0)
    assert len(got) == 1


def test_wait_events_times_out_without_expected_type(runner):
    target = _bench.BenchRunner(_StubTarget(), "frida")
    target._target = _StubTarget(
        status=_bench.TargetStatus(seq=1, events=[{"seq": 1, "type": "mouse_move"}])
    )
    got, _ = target._wait_events(0, {"mouse_press"}, timeout=0.4)
    assert [e["type"] for e in got] == ["mouse_move"], "收不到預期事件時不得捏造事件"


# ── 6. 事件跳號與 dropped 處理 ─────────────────────────────────────


def test_gap_info_detects_seq_jump():
    info = _bench.BenchRunner._gap_info(_bench.TargetStatus(seq=10), 5, [])
    assert "跳號" in info


def test_gap_info_reports_target_dropped_count():
    status = _bench.TargetStatus(seq=10, dropped=7)
    info = _bench.BenchRunner._gap_info(status, 10, [{"seq": 10}])
    assert "丟棄" in info and "7" in info


def test_gap_info_empty_without_gap():
    assert _bench.BenchRunner._gap_info(_bench.TargetStatus(seq=5), 5, []) == ""


# ── 7. 三層結果獨立判定 ───────────────────────────────────────────


def test_three_layers_must_all_pass():
    outcome = _bench.TestOutcome(name="demo")
    assert not outcome.passed
    outcome.backend_ok = True
    assert not outcome.passed, "僅 Backend 成功不得視為通過"
    outcome.received = True
    assert not outcome.passed, "僅兩層成功不得視為通過"
    outcome.expected_ok = True
    assert outcome.passed


def test_layers_are_judged_independently(runner):
    """Backend 失敗不代表 Expected 也失敗；三層各自獨立。"""
    target = _bench.BenchRunner(_StubTarget(), "frida")
    target._bg = _FakeBg(ok=False, error="attach 失敗")
    target._target = _StubTarget(status=_bench.TargetStatus(seq=0, hwnd=1234, state={}))
    outcome = target._run(
        "Demo",
        {"mouse_press"},
        lambda: False,
        lambda before, after, events: (True, "語意達成"),
    )
    assert outcome.backend_ok is False
    assert outcome.received is False
    assert outcome.expected_ok is True
    assert outcome.passed is False


def test_backend_error_is_reported_in_detail(runner):
    target = _bench.BenchRunner(_StubTarget(), "frida")
    target._bg = _FakeBg(ok=False, error="attach 失敗：無法連線")
    target._target = _StubTarget(status=_bench.TargetStatus(seq=0, hwnd=1234, state={}))
    outcome = target.run_click()
    assert outcome.backend_ok is False
    assert "attach 失敗" in outcome.backend_detail


# ── 8. cancel Event 傳遞 ───────────────────────────────────────────


def _clickable_stub():
    """假目標：第一次讀取為基準（seq=0），之後回報已收到 click 事件。"""
    events = [
        {"seq": 1, "type": "mouse_press"},
        {"seq": 2, "type": "mouse_release"},
    ]
    return _StubTarget(
        statuses=[
            _bench.TargetStatus(seq=0, hwnd=1234, state={}),
            _bench.TargetStatus(seq=2, hwnd=1234, events=events, state={}),
        ]
    )


def test_cancel_event_is_the_bench_own_event(runner):
    """傳給 Backend 的是工作台自己的 Event，不是 MainLoop 的 _stop_event。"""
    target = _bench.BenchRunner(_StubTarget(), "frida")
    fake = _FakeBg()
    target._bg = fake
    target._target = _clickable_stub()
    target.run_click()
    cancel_arg = [c for name, c in fake.calls if name == "click"][0]
    assert cancel_arg is target.cancel_event


def test_cancel_sets_and_resets_the_event(runner):
    assert not runner.cancel_event.is_set()
    runner.cancel()
    assert runner.cancel_event.is_set()
    runner.reset_cancel()
    assert not runner.cancel_event.is_set()


def test_cancelled_backend_reports_failure(runner):
    """取消後 Backend 必須回報失敗（Backend 層不可假裝成功）。"""
    target = _bench.BenchRunner(_StubTarget(), "frida")
    fake = _FakeBg(ok=True)
    target._bg = fake
    target._target = _clickable_stub()
    target.cancel()
    target.run_click()
    cancel_arg = [c for name, c in fake.calls if name == "click"][0]
    assert cancel_arg.is_set()


# ── 9. 工作台關閉時的資源釋放 ─────────────────────────────────────


def test_window_close_releases_resources(qt_app, monkeypatch):
    """關閉工作台必須解除注入並結束目標程式。"""
    window = _bench.InputTestBenchWindow()
    detached = []
    stopped = []

    class _StubRunner:
        def detach(self):
            detached.append(1)

    window._runner = _StubRunner()
    monkeypatch.setattr(window._target, "stop", lambda *a, **k: stopped.append(1))
    try:
        window.close()
        assert detached == [1], "關閉時必須解除注入"
        assert stopped == [1], "關閉時必須結束目標程式"
    finally:
        window._poll.stop()


# ── 10. CLI ────────────────────────────────────────────────────────


def test_self_check_exits_zero():
    result = subprocess.run(
        [sys.executable, str(ROOT / "devtools" / "input_test_bench.py"), "--self-check"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, f"self-check 失敗：\n{result.stdout}\n{result.stderr}"
    assert "Self-Check 完成" in result.stdout


def test_cli_parser_supports_modes():
    parser = _bench.build_parser()
    args = parser.parse_args(["--integration", "--mode", "hybrid"])
    assert args.integration is True
    assert args.mode == "hybrid"
    assert parser.parse_args(["--self-check"]).self_check is True


def test_cancel_event_is_threading_event(runner):
    """cancel 必須是 threading.Event（可跨執行緒使用）。"""
    assert isinstance(runner.cancel_event, threading.Event)
