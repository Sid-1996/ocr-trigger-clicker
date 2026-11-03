"""E2-A2：全域 Stop 必須能完整中斷輸入鏈。

涵蓋範圍：

- Backend 取消傳播（pynput / bg_input）：
  停止後不得送出新的輸入（click / key / drag DOWN / scroll）；
  已送出的 DOWN 必須完成 UP / Release（取消閘不得阻擋釋放）。
- MainLoop：全域 STOPPED 優先於任何 StepResult（continue / stop / jump_step）；
  不推進 pointer、不計入 completed、Parallel / Background 正確傳遞。
- Verify / VerifyRetry：Stop 不得被當成一般驗證失敗，不得重送輸入。

全部使用 fake backend：不送出任何真實滑鼠／鍵盤事件，也不建立真實 Frida session。
"""

import threading

import numpy as np
import pytest
from conftest import make_main_loop

from _loader import load_sibling

_PIN = load_sibling("pynput_input", "core/03_pynput_input.py")
_BG = load_sibling("bg_input", "core/16_bg_input.py")
_ML = load_sibling("main_loop", "core/05_main_loop.py")

_models = load_sibling("rule_models", "core/rule_models.py")
Rule = _models.Rule
RuleGroup = _models.RuleGroup
Step = _models.Step

RuleRunOutcome = _ML.RuleRunOutcome
StepContext = _ML.StepContext

_BLANK = np.zeros((100, 100, 3), dtype=np.uint8)
_RECT = {"x": 0, "y": 0, "w": 100, "h": 100}


# ── Fake pynput 裝置 ─────────────────────────────────────────────────
class _FakeMouse:
    def __init__(self, events, positions):
        self.events = events
        self.positions = positions
        self.press_error = None
        self.on_press = None
        self._pos = None

    @property
    def position(self):
        return self._pos

    @position.setter
    def position(self, value):
        self.positions.append(value)
        self._pos = value

    def press(self, button):
        if self.press_error is not None:
            self.events.append(("press_failed", str(button)))
            raise self.press_error
        self.events.append(("press", str(button)))
        if self.on_press is not None:
            self.on_press()

    def release(self, button):
        self.events.append(("release", str(button)))

    def scroll(self, dx, dy):
        self.events.append(("scroll", dx, dy))


class _FakeKeyboard:
    def __init__(self, events):
        self.events = events
        self.on_press = None

    def press(self, key):
        self.events.append(("press", str(key)))
        if self.on_press is not None:
            self.on_press()

    def release(self, key):
        self.events.append(("release", str(key)))


@pytest.fixture
def devices(monkeypatch):
    """以假 pynput 控制器取代真實 Controller（不送出任何真實輸入事件）。"""
    events: list = []
    positions: list = []
    mouse = _FakeMouse(events, positions)
    kb = _FakeKeyboard(events)
    monkeypatch.setattr(_PIN.pynput.mouse, "Controller", lambda: mouse)
    monkeypatch.setattr(_PIN.pynput.keyboard, "Controller", lambda: kb)
    return {"events": events, "positions": positions, "mouse": mouse, "kb": kb}


def _kinds(events):
    return [e[0] for e in events]


# ── Fake 後台（frida）後端 ───────────────────────────────────────────
class _FakeUser32:
    """只記錄訊息的假 user32；fail 模擬 PostMessageW 回傳 0。"""

    def __init__(self):
        self.sent = []
        self.fail = set()
        self.on_send = None

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        self.sent.append(msg)
        if self.on_send is not None:
            self.on_send(msg)
        return 0 if msg in self.fail else 1


class _FakeFrida:
    """假 frida 模組：只記錄游標同步與按鍵事件，不建立真實 session。"""

    def __init__(self):
        self.syncs = []
        self.keys = []
        self.fail_key_up = False
        self.on_key_down = None

    def ensure_attached(self, hwnd):
        return True

    def sync_cursor(self, hwnd, x, y):
        self.syncs.append((x, y))
        return True

    def click(self, hwnd, x, y, button="left", hold_ms=0, cancel=None):
        return _BG._click_postmessage(hwnd, x, y, button, hold_ms, cancel)

    def key(self, hwnd, vk, down, cancel=None):
        self.keys.append((vk, down))
        if down:
            if self.on_key_down is not None:
                self.on_key_down()
        elif self.fail_key_up:
            return False
        return True


@pytest.fixture
def bg_frida(monkeypatch):
    """切到 frida 模式並安裝假 backend；測試結束後自動還原。"""
    prev_method = _BG.get_method()
    fake_user32 = _FakeUser32()
    fake_frida = _FakeFrida()
    monkeypatch.setattr(_BG, "user32", fake_user32)
    monkeypatch.setattr(_BG, "_frida", lambda: fake_frida)
    monkeypatch.setattr(_BG, "_last_error", "")
    _BG.set_method("frida")
    try:
        yield fake_user32, fake_frida
    finally:
        _BG.set_method(prev_method)


# ══════════════════════════════════════════════════════════════════════
# Backend：取消傳播（需求 1-10）
# ══════════════════════════════════════════════════════════════════════


def test_stop_prevents_click(devices):
    """需求 1：已停止時不得送出點擊。"""
    cancel = threading.Event()
    cancel.set()
    assert _PIN.send_click(100, 100, "left", 0, cancel) is False
    assert devices["events"] == [], "已停止時不得送出任何輸入"


def test_stop_prevents_key(devices):
    """需求 2：已停止時不得送出按鍵。"""
    cancel = threading.Event()
    cancel.set()
    assert _PIN.send_key("a", cancel) is False
    assert devices["events"] == [], "已停止時不得送出任何輸入"


def test_stop_prevents_drag_down(devices):
    """需求 3：已停止時不得送出拖曳的 DOWN。"""
    cancel = threading.Event()
    cancel.set()
    assert _PIN.send_drag(10, 10, 50, 50, "left", cancel) is False
    assert devices["events"] == []
    assert devices["positions"] == [], "已停止時不得移動游標"


def test_stop_prevents_scroll(devices):
    """需求 4：已停止時不得送出滾輪。"""
    cancel = threading.Event()
    cancel.set()
    assert _PIN.send_scroll(1, "WheelDown", cancel) is False
    assert devices["events"] == []


def test_key_releases_even_when_stopped_after_down(devices):
    """需求 5：DOWN 已送出後才停止，仍必須送出 UP。"""
    cancel = threading.Event()
    devices["kb"].on_press = cancel.set  # DOWN 成功後立刻停止
    assert _PIN.send_key("a", cancel) is True
    assert _kinds(devices["events"]) == ["press", "release"], "DOWN 之後必須送出 UP"


def test_drag_stops_move_and_releases_after_stop(devices):
    """需求 6：DOWN 已送出後停止 → 停止 MOVE，但仍送 UP。"""
    cancel = threading.Event()
    devices["mouse"].on_press = cancel.set
    assert _PIN.send_drag(10, 10, 50, 50, "left", cancel) is True
    assert _kinds(devices["events"]) == ["press", "release"]
    assert devices["positions"] == [(10, 10)], "取消後不得再移到終點"


def test_drag_down_failure_does_not_send_up(devices):
    """需求 7：DOWN 失敗時不得送出 UP（避免誤放）。"""
    devices["mouse"].press_error = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        _PIN.send_drag(10, 10, 50, 50, "left")
    assert "release" not in _kinds(devices["events"]), "DOWN 失敗不得送出 UP"


def test_cancel_none_keeps_legacy_behaviour(devices):
    """需求 9：cancel=None 維持既有行為（舊的 positional 呼叫端不受影響）。"""
    assert _PIN.send_click(100, 100, "left", 0) is True
    assert _PIN.send_key("a") is True
    assert _PIN.send_drag(10, 10, 50, 50) is True
    assert _PIN.send_scroll(1, "WheelDown") is True
    assert _PIN.send_hold_key("a", 0) is True
    kinds = _kinds(devices["events"])
    assert kinds.count("press") == 4
    assert kinds.count("release") == 4, "每次 press 都必須有對應的 release"
    assert kinds.count("scroll") == 1


def test_bg_stop_prevents_key(bg_frida):
    """需求 2（後台）：已停止時不得送出按鍵。"""
    _fake_user32, fake_frida = bg_frida
    cancel = threading.Event()
    cancel.set()
    assert _BG.send_key(1, "a", cancel) is False
    assert fake_frida.keys == [], "已停止時不得送出任何按鍵"


def test_bg_stop_prevents_scroll(bg_frida):
    """需求 4（後台）：已停止時不得送出滾輪。"""
    fake_user32, _fake_frida = bg_frida
    cancel = threading.Event()
    cancel.set()
    assert _BG.scroll(1, 0, 0, 1, False, cancel) is False
    assert _BG.WM_MOUSEWHEEL not in fake_user32.sent


def test_bg_stop_prevents_drag_down(bg_frida):
    """需求 3（後台）：已停止時不得送出拖曳的 DOWN。"""
    fake_user32, fake_frida = bg_frida
    cancel = threading.Event()
    cancel.set()
    assert _BG.drag(1, 10, 20, 30, 40, "left", cancel) is False
    assert _BG.WM_LBUTTONDOWN not in fake_user32.sent
    assert fake_frida.syncs == [], "已停止時不得同步游標"


def test_bg_drag_stop_after_down_releases_without_move(bg_frida):
    """需求 6（後台）：DOWN 已送出後停止 → 不再 MOVE，但仍送 UP。"""
    fake_user32, _fake_frida = bg_frida
    cancel = threading.Event()
    fake_user32.on_send = lambda msg: cancel.set() if msg == _BG.WM_LBUTTONDOWN else None
    assert _BG.drag(1, 10, 20, 30, 40, "left", cancel) is False
    assert _BG.WM_LBUTTONUP in fake_user32.sent, "DOWN 已送出就必須送 UP"
    assert _BG.WM_MOUSEMOVE not in fake_user32.sent, "取消後不得再移動"


def test_bg_drag_down_failure_does_not_send_up(bg_frida):
    """需求 7（後台）：DOWN 失敗時不得送出 UP。"""
    fake_user32, _fake_frida = bg_frida
    fake_user32.fail = {_BG.WM_LBUTTONDOWN}
    assert _BG.drag(1, 10, 20, 30, 40, "left") is False
    assert _BG.WM_LBUTTONUP not in fake_user32.sent


def test_bg_frida_up_failure_is_reported(bg_frida):
    """需求 8：Frida 的 UP 失敗必須留下錯誤資訊（不得只寫 log 就當沒發生）。"""
    fake_user32, _fake_frida = bg_frida
    fake_user32.fail = {_BG.WM_LBUTTONUP}
    assert _BG.drag(1, 10, 20, 30, 40, "left") is False
    assert _BG.last_error(), "UP 失敗必須保留錯誤資訊供 GUI 回報"


def test_bg_key_releases_after_stop(bg_frida):
    """需求 5（後台）：DOWN 已送出後才停止，仍必須送出 UP。"""
    _fake_user32, fake_frida = bg_frida
    cancel = threading.Event()
    fake_frida.on_key_down = cancel.set
    assert _BG.send_key(1, "a", cancel) is True
    downs = [d for _vk, d in fake_frida.keys]
    assert downs == [True, False], "DOWN 之後必須送出 UP"


def test_bg_cancel_none_keeps_legacy_behaviour(bg_frida):
    """需求 9/10（後台）：cancel=None 與舊 positional 呼叫端維持原行為。"""
    fake_user32, fake_frida = bg_frida
    assert _BG.send_key(1, "a") is True
    assert _BG.scroll(1, 0, 0, 1) is True
    assert _BG.drag(1, 10, 20, 30, 40, "left") is True
    assert _BG.WM_LBUTTONUP in fake_user32.sent
    assert fake_frida.keys, "send_key 仍應走 frida 按鍵通道"


# ══════════════════════════════════════════════════════════════════════
# MainLoop：全域 STOPPED 優先權（需求 11-17）
# ══════════════════════════════════════════════════════════════════════


def _ml():
    ml = make_main_loop()
    ml._frame_chrome = (4, 31)
    ml._frame_client_size = (1912, 1041)
    ml._perf.check_rate_limit = lambda: True
    return ml


def _setup_groups(ml, rules, rule_ids, order="sequential"):
    ml._rules = list(rules)
    ml._rule_map = {r.id: r for r in rules}
    ml._groups = [
        RuleGroup(id="g1", name="g1", rule_ids=rule_ids, order=order, enabled=True, mode="once")
    ]
    ml._active_group_ids = ["g1"]
    ml._rule_in_group_ptr = 0
    ml._group_queue_idx = 0
    ml._rule_completed.clear()
    ml._last_active_rule_id = None
    ml._process_counter = 0


def test_global_stop_during_step_returns_stopped_outcome():
    """需求 11：步驟執行期間全域停止 → 一律轉成 STOPPED（不論 StepResult 為何）。"""
    ml = _ml()
    rule = Rule(
        id="A",
        name="A",
        enabled=True,
        steps=[
            Step("click", {"target": "custom", "x": 0.5, "y": 0.5}),
            Step("key", {"key": "space"}),
        ],
    )

    def _click(*_a, **_k):
        ml._stop_event.set()  # 步驟執行「期間」停止，但步驟本身回傳 continue
        return True

    ml._send_click = _click
    ctx = StepContext(img=_BLANK, rect=_RECT)
    outcome = ml._run_rule(rule, _BLANK, _RECT, ctx)

    assert outcome is RuleRunOutcome.STOPPED
    assert ctx.triggered is False, "STOPPED 必須清理 triggered"
    assert ctx.force_advance is False, "STOPPED 必須清理 force_advance"


def test_local_stop_without_event_is_not_stopped():
    """需求 12：局部 on_fail=stop 在全域停止未設定時維持原語意。"""
    ml = _ml()
    rule = Rule(
        id="A",
        name="A",
        enabled=True,
        steps=[Step("detect", {"text": "zzz-never-present", "on_fail": "stop"})],
    )
    ml._ocr_region = lambda *_a, **_k: []
    ctx = StepContext(img=_BLANK, rect=_RECT)
    outcome = ml._run_rule(rule, _BLANK, _RECT, ctx)

    assert outcome is None, "局部 stop 不得升級為 STOPPED"
    assert not ml._stop_event.is_set()


def test_stop_after_step_blocks_next_step_and_pointer():
    """需求 13/14/15：停止後不執行下一步、不推進 pointer、不計入 completed。"""
    ml = _ml()
    rule = Rule(
        id="A",
        name="A",
        enabled=True,
        steps=[
            Step("click", {"target": "custom", "x": 0.5, "y": 0.5}),
            Step("key", {"key": "space"}),
        ],
    )
    nxt = Rule(
        id="B",
        name="B",
        enabled=True,
        steps=[Step("click", {"target": "custom", "x": 0.5, "y": 0.5})],
    )
    _setup_groups(ml, [rule, nxt], ["A", "B"])
    keys: list = []
    clicks: list = []

    def _click(*_a, **_k):
        clicks.append("click")
        ml._stop_event.set()
        return True

    ml._send_click = _click
    ml._send_key = lambda k, *_a, **_k: keys.append(k) or True

    ml._process_rules(_BLANK, _RECT)

    assert keys == [], "停止後不得執行下一個 Step"
    assert clicks == ["click"], "停止後不得執行下一條規則"
    assert ml._rule_completed == set(), "停止不得計入 completed"
    assert ml._rule_in_group_ptr == 0, "停止不得推進 pointer"
    assert ml._group_queue_idx == 0


def test_parallel_stop_propagates_stopped():
    """需求 16：Parallel 群組的全局停止必須正確傳遞（不得執行其餘規則）。"""
    ml = _ml()
    a = Rule(
        id="A",
        name="A",
        enabled=True,
        steps=[Step("click", {"target": "custom", "x": 0.5, "y": 0.5})],
    )
    b = Rule(
        id="B",
        name="B",
        enabled=True,
        steps=[Step("click", {"target": "custom", "x": 0.5, "y": 0.5})],
    )
    _setup_groups(ml, [a, b], ["A", "B"], order="parallel")
    clicks: list = []

    def _click(*_a, **_k):
        clicks.append("click")
        ml._stop_event.set()
        return True

    ml._send_click = _click

    ml._process_rules(_BLANK, _RECT)

    assert clicks == ["click"], "停止後不得執行同群組剩餘規則"
    assert ml._rule_completed == set()
    assert ml._group_queue_idx == 0, "停止不得推進 queue"


def test_background_stop_does_not_pollute_foreground_pointer():
    """需求 17：Background 的停止不得污染前景 pointer，也不得執行前景規則。"""
    ml = _ml()
    bg = Rule(
        id="BG",
        name="BG",
        enabled=True,
        background=True,
        steps=[Step("click", {"target": "custom", "x": 0.5, "y": 0.5})],
    )
    fg = Rule(
        id="A",
        name="A",
        enabled=True,
        steps=[Step("click", {"target": "custom", "x": 0.5, "y": 0.5})],
    )
    _setup_groups(ml, [bg, fg], ["A"])
    clicks: list = []

    def _click(*_a, **_k):
        clicks.append("click")
        ml._stop_event.set()
        return True

    ml._send_click = _click

    ml._process_rules(_BLANK, _RECT)

    assert clicks == ["click"], "背景停止後不得再執行前景規則"
    assert ml._rule_in_group_ptr == 0, "背景停止不得污染前景 pointer"
    assert ml._rule_completed == set()


def test_handler_stop_gate_blocks_new_input():
    """需求 13（Handler 層）：入口已停止時不得開始新的輸入。"""
    ml = _ml()
    ml._stop_event.set()
    rule = Rule(id="A", name="A", enabled=True, steps=[Step("click", {"target": "custom"})])
    ctx = StepContext(img=_BLANK, rect=_RECT)
    clicks: list = []

    ml._send_click = lambda *a, **k: clicks.append(a) or True
    ml._send_key = lambda *a, **k: clicks.append(a) or True
    ml._send_scroll = lambda *a, **k: clicks.append(a) or True

    assert ml._handle_click({"target": "custom", "x": 0.5, "y": 0.5}, ctx, rule).action == "stop"
    assert ml._handle_key({"key": "space"}, ctx, rule).action == "stop"
    assert ml._handle_drag({"target": "custom", "x": 0.5, "y": 0.5}, ctx, rule).action == "stop"
    assert ml._handle_scroll({"direction": "WheelDown"}, ctx, rule).action == "stop"
    assert clicks == [], "停止閘必須擋下所有新的輸入"


# ══════════════════════════════════════════════════════════════════════
# Verify / VerifyRetry 取消（需求 18-23）
# ══════════════════════════════════════════════════════════════════════


def _verify(retries=0, retry_delay_ms=0):
    return {
        "type": "detect",
        "text": "never",
        "timeout_ms": 10,
        "poll_interval_ms": 1,
        "retries": retries,
        "retry_delay_ms": retry_delay_ms,
    }


def _verify_rule(verify):
    return Rule(
        id="r1",
        name="r1",
        enabled=True,
        steps=[
            Step(
                "click",
                {"target": "custom", "x": 0.5, "y": 0.5, "after_delay_ms": 0, "verify": verify},
            )
        ],
    )


def test_stop_before_verify_blocks_verify(monkeypatch):
    """需求 18：Verify 開始前已停止 → 不得進入驗證流程。"""
    ml = _ml()
    sent: list = []
    polled: list = []

    def _click(*_a, **_k):
        sent.append("click")
        ml._stop_event.set()
        return True

    ml._send_click = _click
    monkeypatch.setattr(ml, "_poll_verify", lambda verify: polled.append(verify) or "timeout")

    ctx = StepContext(img=_BLANK, rect=_RECT)
    outcome = ml._run_rule(_verify_rule(_verify()), _BLANK, _RECT, ctx)

    assert outcome is RuleRunOutcome.STOPPED
    assert polled == [], "全域停止後不得開始 Verify"


def test_stop_during_polling_is_cancelled(monkeypatch):
    """需求 19：Polling 期間停止 → 視為取消（不是一般驗證失敗）。"""
    ml = _ml()
    sent: list = []

    def _click(*_a, **_k):
        sent.append("click")
        return True

    def _poll(_verify):
        ml._stop_event.set()
        return "cancelled"

    ml._send_click = _click
    monkeypatch.setattr(ml, "_poll_verify", _poll)

    ctx = StepContext(img=_BLANK, rect=_RECT)
    outcome = ml._run_rule(_verify_rule(_verify(retries=1, retry_delay_ms=50)), _BLANK, _RECT, ctx)

    assert outcome is RuleRunOutcome.STOPPED
    assert sent == ["click"], "取消後不得重送輸入"


def test_stop_during_retry_delay_does_not_resend_input(monkeypatch):
    """需求 20/22：Retry delay 期間停止 → 不得重送輸入、不得觸發一般 retry。"""
    ml = _ml()
    sent: list = []

    def _click(*_a, **_k):
        sent.append("click")
        return True

    def _poll(_verify):
        ml._stop_event.set()  # 第一次驗證逾時，且同時停止
        return "timeout"

    ml._send_click = _click
    monkeypatch.setattr(ml, "_poll_verify", _poll)

    ctx = StepContext(img=_BLANK, rect=_RECT)
    outcome = ml._run_rule(_verify_rule(_verify(retries=1, retry_delay_ms=200)), _BLANK, _RECT, ctx)

    assert outcome is RuleRunOutcome.STOPPED
    assert sent == ["click"], "停止後不得重送輸入"


class _StopAfterWait:
    """等待「結束後」才把停止旗標立起來的假 stop event。

    用來模擬：retry delay 的 wait 回報未中斷，但停止訊號緊接著才抵達。
    """

    def __init__(self):
        self._set = False

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def clear(self):
        self._set = False

    def wait(self, timeout=None):
        if not self._set:
            self._set = True
        return False


def test_stop_after_retry_delay_does_not_resend_input(monkeypatch):
    """需求 21/22：Retry delay 結束後才停止 → 不得重送輸入。"""
    ml = _ml()
    sent: list = []

    def _click(*_a, **_k):
        sent.append("click")
        return True

    ml._send_click = _click
    monkeypatch.setattr(ml, "_poll_verify", lambda verify: "timeout")
    ml._stop_event = _StopAfterWait()

    ctx = StepContext(img=_BLANK, rect=_RECT)
    outcome = ml._run_rule(_verify_rule(_verify(retries=1, retry_delay_ms=10)), _BLANK, _RECT, ctx)

    assert outcome is RuleRunOutcome.STOPPED
    assert sent == ["click"], "停止後不得重送輸入"


def test_normal_verify_success_still_advances(monkeypatch):
    """需求 23：正常 Verify 成功行為不變。"""
    ml = _ml()
    sent: list = []

    def _click(*_a, **_k):
        sent.append("click")
        return True

    ml._send_click = _click
    monkeypatch.setattr(ml, "_poll_verify", lambda verify: "success")

    ctx = StepContext(img=_BLANK, rect=_RECT)
    outcome = ml._run_rule(_verify_rule(_verify()), _BLANK, _RECT, ctx)

    assert outcome is None
    assert ctx.triggered is True, "驗證成功後仍應計入完成"
    assert sent == ["click"]


def test_normal_verify_timeout_still_runs_on_fail(monkeypatch):
    """需求 23：正常 Verify 逾時 → 仍走 on_fail（advance），行為不變。"""
    ml = _ml()
    sent: list = []

    def _click(*_a, **_k):
        sent.append("click")
        return True

    ml._send_click = _click
    monkeypatch.setattr(ml, "_poll_verify", lambda verify: "timeout")

    ctx = StepContext(img=_BLANK, rect=_RECT)
    outcome = ml._run_rule(_verify_rule(_verify()), _BLANK, _RECT, ctx)

    assert outcome is None
    assert ctx.force_advance is True, "驗證逾時仍應依 on_fail 推進"
    assert sent == ["click"]
