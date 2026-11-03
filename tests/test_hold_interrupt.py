"""輸入中斷（hold 可取消）與 Ledger 釋放保護的測試。

背景
----
`core/03_pynput_input.py` 與 `core/16_bg_input.py` 原本用 `time.sleep()` 等待按住
時間，等待期間完全不理會停止訊號；使用者按 Stop 後，遊戲內按鍵／滑鼠仍會持續被
按住最長 60 秒。且按下與放開之間沒有釋放守衛：press 成功後一旦例外，輸入就永久
卡住。

本檔鎖住 Phase 2-7d-2b-2a-E1 的不變量：

- Ledger：只有 press 確認成功才登記；釋放依 press 的相反順序（LIFO）；每一項
  釋放各自 try/except；某一項失敗不得阻止其餘；釋放失敗必須留下 warning；
  不得對未登記者送出 release。
- 可取消等待：cancel 為可選 Event；cancel=None 時維持舊行為；已取消時不得
  開始新的 press；等待期間取消必須立即進入釋放流程且不得跳過釋放。
- cancel 傳遞：MainLoop 必須把 `_stop_event` 傳到 pynput 與 frida 兩條路徑。

全部使用 Fake backend：
- 不實例化真實 pynput Controller（以 monkeypatch 換成記錄事件的假控制器）
- 不 import / 建立真實 Frida session（以假 frida 模組取代）
- 不送出任何真實滑鼠或鍵盤事件
"""

import importlib
import logging
import sys
import threading
import time
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from conftest import make_main_loop as _make_ml  # noqa: E402

from _loader import load_sibling  # noqa: E402

_PIN = load_sibling("pynput_input", "core/03_pynput_input.py")
_BG = load_sibling("bg_input", "core/16_bg_input.py")
_ML = load_sibling("main_loop", "core/05_main_loop.py")

_hybrid = importlib.import_module("core.19_hybrid_input")


# ── Fake 輸入後端 ────────────────────────────────────────────────────
class _FakeDevice:
    """記錄 press/release 事件的假輸入裝置，可注入指定次數的失敗。"""

    def __init__(self, events, fail, pressed_event):
        self.events = events
        self._fail = fail
        self.pressed_event = pressed_event
        self.on_press = None
        self._press_n = 0
        self._release_n = 0

    def _do_press(self, name):
        self._press_n += 1
        if self._fail.get(f"press:{self._press_n}"):
            # press 失敗 → 視為未按下（不計入按住狀態）
            self.events.append(("press_failed", name))
            raise RuntimeError(f"injected press failure #{self._press_n}")
        self.events.append(("press", name))
        self.pressed_event.set()
        if self.on_press is not None:
            self.on_press()

    def _do_release(self, name):
        self._release_n += 1
        if self._fail.get(f"release:{self._release_n}"):
            # release 失敗 → 視為仍按住
            self.events.append(("release_failed", name))
            raise RuntimeError(f"injected release failure #{self._release_n}")
        self.events.append(("release", name))


class _FakeMouse(_FakeDevice):
    def __init__(self, events, fail, pressed_event):
        super().__init__(events, fail, pressed_event)
        self._pos = None
        self.fail_position_after_press = False

    @property
    def position(self):
        return self._pos

    @position.setter
    def position(self, value):
        if self.fail_position_after_press and self._press_n >= 1:
            raise RuntimeError("move failed")
        self._pos = value

    def press(self, button):
        self._do_press(str(button))

    def release(self, button):
        self._do_release(str(button))

    def scroll(self, dx, dy):
        self.events.append(("scroll", dx, dy))


class _FakeKeyboard(_FakeDevice):
    def press(self, key):
        self._do_press(str(key))

    def release(self, key):
        self._do_release(str(key))


class _Devices:
    """fake 裝置群組 + 失敗注入點。"""

    def __init__(self):
        self.events = []
        self.mouse_fail = {}
        self.kb_fail = {}
        self.mouse_pressed = threading.Event()
        self.kb_pressed = threading.Event()
        self.mouse = _FakeMouse(self.events, self.mouse_fail, self.mouse_pressed)
        self.kb = _FakeKeyboard(self.events, self.kb_fail, self.kb_pressed)


@pytest.fixture
def devices(monkeypatch):
    """以假 pynput 控制器取代真實 Controller（不送出任何真實輸入事件）。"""
    dev = _Devices()
    monkeypatch.setattr(_PIN.pynput.mouse, "Controller", lambda: dev.mouse)
    monkeypatch.setattr(_PIN.pynput.keyboard, "Controller", lambda: dev.kb)
    return dev


@pytest.fixture
def bg_method():
    """把 bg_input 的輸入方法切到 frida，測試結束後還原。"""
    original = _BG.get_method()
    yield _BG.set_method
    _BG.set_method(original)


# ── 斷言輔助 ─────────────────────────────────────────────────────────
def _kinds(events):
    return [e[0] for e in events]


def _still_held(events):
    """事件序列跑完後仍處於「按下」狀態的輸入（多鍵以計數表示）。"""
    held = {}
    for kind, name in events:
        if kind == "press":
            held[name] = held.get(name, 0) + 1
        elif kind == "release":
            if name in held:
                held[name] -= 1
                if held[name] == 0:
                    del held[name]
    return held


def _counts(events):
    return (
        sum(1 for e in events if e[0] == "press"),
        sum(1 for e in events if e[0] == "release"),
    )


# ── 1. 正常完成的 press/release ───────────────────────────────────────
def test_hold_key_releases_exactly_once_on_normal_completion(devices):
    assert _PIN.send_hold_key("a", 30) is True
    assert _kinds(devices.events) == ["press", "release"]
    assert devices.events[0][1] == devices.events[1][1]
    assert _still_held(devices.events) == {}


def test_normal_click_releases_exactly_once(devices):
    assert _PIN.send_click(100, 100, "left", 0) is True
    assert _kinds(devices.events) == ["press", "release"]
    assert _still_held(devices.events) == {}


# ── 2/3. 等待期間被取消 ───────────────────────────────────────────────
def test_hold_key_interrupted_by_cancel_event(devices):
    cancel = threading.Event()
    done = threading.Event()

    def _run():
        _PIN.send_hold_key("a", 5000, cancel)
        done.set()

    th = threading.Thread(target=_run)
    th.start()
    assert devices.kb_pressed.wait(2.0), "按鍵必須在取消前被按下"
    t0 = time.monotonic()
    cancel.set()
    assert done.wait(2.0), "取消後 hold 必須返回"
    assert (time.monotonic() - t0) < 0.1, "取消後必須立即返回，不得等滿 hold 時間"
    th.join()
    assert _kinds(devices.events) == ["press", "release"]
    assert _still_held(devices.events) == {}


def test_click_interrupted_by_cancel_event(devices):
    cancel = threading.Event()
    done = threading.Event()

    def _run():
        _PIN.send_click(100, 100, "left", 5000, cancel)
        done.set()

    th = threading.Thread(target=_run)
    th.start()
    assert devices.mouse_pressed.wait(2.0), "滑鼠必須在取消前被按下"
    t0 = time.monotonic()
    cancel.set()
    assert done.wait(2.0), "取消後 click 必須返回"
    assert (time.monotonic() - t0) < 0.1
    th.join()
    assert _kinds(devices.events) == ["press", "release"]
    assert _still_held(devices.events) == {}


# ── 4/5. press 失敗不得誤送 release ──────────────────────────────────
def test_no_release_sent_when_press_raises(devices):
    devices.mouse_fail["press:1"] = True
    with pytest.raises(RuntimeError):
        _PIN.send_click(100, 100, "left", 0)
    assert _kinds(devices.events) == ["press_failed"], "press 失敗時不得送出任何 release"
    assert _still_held(devices.events) == {}


def test_ctrl_combo_releases_only_ctrl_when_second_press_fails(devices):
    """多鍵組合：第二個 press 失敗時只能釋放已成功 press 的 Ctrl。"""
    devices.kb_fail["press:2"] = True
    with pytest.raises(RuntimeError):
        _PIN.send_key("^a")
    kinds = _kinds(devices.events)
    assert kinds == ["press", "press_failed", "release"], f"事件序列不符: {devices.events}"
    pressed = [e[1] for e in devices.events if e[0] == "press"]
    released = [e[1] for e in devices.events if e[0] == "release"]
    assert len(pressed) == 1
    assert len(released) == 1, "只釋放已成功 press 的 Ctrl，不得誤送字元 release"
    assert released[0] == pressed[0]


def test_ctrl_combo_releases_in_reverse_order(devices):
    assert _PIN.send_key("^a") is True
    kinds = _kinds(devices.events)
    assert kinds == ["press", "press", "release", "release"]
    pressed = [e[1] for e in devices.events if e[0] == "press"]
    released = [e[1] for e in devices.events if e[0] == "release"]
    assert released == list(reversed(pressed)), "釋放必須依 press 的相反順序"
    assert _still_held(devices.events) == {}


# ── 7/8. release 失敗 ────────────────────────────────────────────────
def test_release_failure_does_not_block_other_releases(devices):
    devices.kb_fail["release:1"] = True
    assert _PIN.send_key("^a") is True
    released = [e[1] for e in devices.events if e[0] == "release"]
    assert len(released) == 1, "第一個釋放失敗不得阻止第二個釋放"
    assert released[0] != "'a'", "失敗的那一項不得被當成已釋放"
    assert _still_held(devices.events) == {"'a'": 1}, "第一項釋放失敗時該鍵仍記為按住"


def test_release_failure_is_logged_as_warning(devices, caplog):
    """釋放失敗必須留下 level >= WARNING、且含輸入類型／標籤的紀錄。"""
    caplog.set_level(logging.WARNING)
    devices.kb_fail["release:1"] = True
    _PIN.send_hold_key("a", 10)
    records = [r for r in caplog.records if "釋放" in r.getMessage()]
    assert records, "釋放失敗必須留下紀錄，不得靜默"
    assert all(r.levelno >= logging.WARNING for r in records), (
        f"釋放失敗紀錄至少要是 WARNING：{[r.levelname for r in records]}"
    )
    assert any("按鍵" in r.getMessage() for r in records), "紀錄必須包含輸入類型／標籤"


# ── 9/10. 鎖在例外與取消後可立即重新取得 ─────────────────────────────
def test_lock_released_after_press_exception(devices):
    devices.mouse_fail["press:1"] = True
    with pytest.raises(RuntimeError):
        _PIN.send_click(100, 100, "left", 0)
    devices.mouse_fail.clear()
    done = threading.Event()

    def _run():
        _PIN.send_click(100, 100, "left", 0)
        done.set()

    th = threading.Thread(target=_run)
    th.start()
    assert done.wait(1.0), "例外後輸入鎖必須已釋放"
    th.join()


def test_lock_released_after_cancel(devices):
    cancel = threading.Event()
    done = threading.Event()

    def _run():
        _PIN.send_hold_key("a", 5000, cancel)
        done.set()

    th = threading.Thread(target=_run)
    th.start()
    assert devices.kb_pressed.wait(2.0)
    cancel.set()
    assert done.wait(2.0)
    th.join()
    assert _PIN.send_hold_key("b", 0) is True, "取消後輸入鎖必須已釋放"


# ── 11. 並發輸入維持序列化 ────────────────────────────────────────────
def test_concurrent_inputs_are_serialized(devices):
    results = []

    def _click():
        results.append(_PIN.send_click(100, 100, "left", 20))

    threads = [threading.Thread(target=_click) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results == [True] * 4
    assert _kinds(devices.events) == ["press", "release"] * 4, "輸入不得交錯"
    assert _still_held(devices.events) == {}


# ── 12. cancel=None 維持舊行為 ───────────────────────────────────────
def test_cancel_none_preserves_legacy_wait_behavior(devices):
    t0 = time.monotonic()
    assert _PIN.send_hold_key("a", 150) is True
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert elapsed_ms >= 120, f"cancel=None 必須維持完整等待，實測 {elapsed_ms:.0f}ms"
    assert _kinds(devices.events) == ["press", "release"]


def test_cancel_none_legacy_signature_still_accepted(devices):
    """舊有呼叫者（位置參數）不得被迫修改。"""
    assert _PIN.send_click(100, 100, "left", 0) is True
    assert _PIN.send_key("a") is True
    assert _PIN.send_hold_key("a", 0) is True
    assert _PIN.send_drag(10, 10, 50, 50) is True


# ── 13/14. cancel 的時機 ─────────────────────────────────────────────
def test_no_press_when_cancel_already_set(devices):
    cancel = threading.Event()
    cancel.set()
    assert _PIN.send_click(100, 100, "left", 0, cancel) is False
    assert devices.events == [], "已取消時不得送出任何 press"
    assert _PIN.send_hold_key("a", 0, cancel) is False
    assert devices.events == []
    assert _PIN.send_drag(10, 10, 50, 50, "left", cancel) is False
    assert devices.events == []


def test_release_still_happens_when_cancelled_between_press_and_wait(devices):
    """press 之後、等待之前取消：仍必須釋放，且不得重複釋放。"""
    cancel = threading.Event()
    devices.kb.on_press = cancel.set
    assert _PIN.send_hold_key("a", 5000, cancel) is True
    assert _kinds(devices.events) == ["press", "release"]
    assert _still_held(devices.events) == {}


# ── 15. cancel 與正常釋放競爭 ────────────────────────────────────────
def test_cancel_racing_with_release_never_double_releases(devices):
    for i in range(20):
        devices.events.clear()
        devices.kb_pressed.clear()
        cancel = threading.Event()
        done = threading.Event()

        def _run():
            _PIN.send_hold_key("a", 5, cancel)
            done.set()

        th = threading.Thread(target=_run)
        th.start()
        devices.kb_pressed.wait(1.0)
        cancel.set()
        assert done.wait(2.0)
        th.join()
        presses, releases = _counts(devices.events)
        assert releases == presses, f"第 {i} 次：釋放次數 {releases} != 按下次數 {presses}"
        assert releases <= 1, f"第 {i} 次：release 不得重複"


# ── 16. frida 鍵盤 hold 取消 ─────────────────────────────────────────
def test_frida_hold_key_attempts_key_up_on_cancel(monkeypatch, bg_method):
    calls = []
    first_down = threading.Event()

    class _FakeFrida:
        def key(self, hwnd, vk, down, cancel=None):
            calls.append("down" if down else "up")
            if down:
                first_down.set()
            return True

    monkeypatch.setattr(_BG, "_frida", lambda: _FakeFrida())
    bg_method("frida")

    cancel = threading.Event()
    done = threading.Event()

    def _run():
        _BG.send_hold_key(1, "a", 5000, cancel)
        done.set()

    th = threading.Thread(target=_run)
    th.start()
    assert first_down.wait(2.0), "frida 按鍵必須被按下"
    cancel.set()
    assert done.wait(2.0), "取消後 frida hold 必須返回"
    th.join()
    assert calls[-1] == "up", "取消後必須嘗試送出 key(up)"
    assert calls.count("up") == 1, "key(up) 不得重複"


# ── 17/18. frida 滑鼠 down/up ────────────────────────────────────────
class _FakeUser32:
    """記錄 PostMessage 的假 user32。

    mode="raise"：指定訊息拋出 OSError（ctypes windll 的真實失敗模式其實是回傳 0，
    兩種都必須被程式正確處理）。
    mode="zero"：指定訊息回傳 0（Win32 BOOL 失敗的標準表現）。
    """

    def __init__(self, fail_messages=(), mode="raise", fail_count=99):
        self.sent = []
        self._fail_messages = set(fail_messages)
        self._mode = mode
        self._fail_count = fail_count
        self._failures = 0
        self.on_message = None

    def PostMessageW(self, hwnd, msg, wp, lp):
        self.sent.append(msg)
        if self.on_message is not None:
            self.on_message(msg)
        if msg in self._fail_messages and self._failures < self._fail_count:
            self._failures += 1
            if self._mode == "raise":
                raise OSError("PostMessageW failed")
            return 0
        return 1


def test_frida_click_retries_up_after_failure(monkeypatch):
    fake = _FakeUser32(fail_messages=(_BG.WM_LBUTTONUP,), fail_count=1)
    monkeypatch.setattr(_BG, "user32", fake)
    assert _BG._click_postmessage(1, 10, 10, "left", 0) is True
    ups = [m for m in fake.sent if m == _BG.WM_LBUTTONUP]
    assert len(ups) == 2, "up 失敗後必須再嘗試一次"


def test_frida_click_reports_failure_when_up_never_succeeds(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    fake = _FakeUser32(fail_messages=(_BG.WM_LBUTTONUP,))
    monkeypatch.setattr(_BG, "user32", fake)
    assert _BG._click_postmessage(1, 10, 10, "left", 0) is False, "放開失敗不得假裝成功"
    assert "放開訊息失敗" in caplog.text, "放開失敗必須留下 warning"
    assert len([m for m in fake.sent if m == _BG.WM_LBUTTONUP]) == 2


def test_frida_click_sends_down_then_up_in_order(monkeypatch):
    fake = _FakeUser32()
    monkeypatch.setattr(_BG, "user32", fake)
    assert _BG._click_postmessage(1, 10, 10, "left", 0) is True
    assert fake.sent == [_BG.WM_ACTIVATE, _BG.WM_LBUTTONDOWN, _BG.WM_LBUTTONUP]


def test_frida_click_does_not_send_up_when_down_failed(monkeypatch):
    fake = _FakeUser32(fail_messages=(_BG.WM_LBUTTONDOWN,))
    monkeypatch.setattr(_BG, "user32", fake)
    assert _BG._click_postmessage(1, 10, 10, "left", 0) is False
    assert not [m for m in fake.sent if m == _BG.WM_LBUTTONUP], "down 未送達時不得送出 up"


# ── PostMessageW 回傳值判斷（Win32 失敗是回傳 0，不是拋例外）──────────
def test_frida_click_succeeds_when_down_and_up_return_nonzero(monkeypatch):
    """down / up 都回傳非零 → 成功，且訊息順序不變。"""
    fake = _FakeUser32()
    monkeypatch.setattr(_BG, "user32", fake)
    assert _BG._click_postmessage(1, 10, 10, "left", 0) is True
    assert fake.sent == [_BG.WM_ACTIVATE, _BG.WM_LBUTTONDOWN, _BG.WM_LBUTTONUP]


def test_frida_click_fails_and_skips_up_when_down_returns_zero(monkeypatch, caplog):
    """down 回傳 0 → 視為失敗；不得標記 down_sent；不得送出 up。"""
    caplog.set_level(logging.WARNING)
    fake = _FakeUser32(fail_messages=(_BG.WM_LBUTTONDOWN,), mode="zero")
    monkeypatch.setattr(_BG, "user32", fake)
    assert _BG._click_postmessage(1, 10, 10, "left", 0) is False
    assert not [m for m in fake.sent if m == _BG.WM_LBUTTONUP], "down 未提交時不得送出 up"
    assert "按下滑鼠訊息失敗" in caplog.text, "down 失敗必須留下錯誤紀錄"


def test_frida_click_retries_when_first_up_returns_zero(monkeypatch):
    """down 成功、第一次 up 回傳 0、第二次成功 → up 嘗試兩次，最終回傳成功。"""
    fake = _FakeUser32(fail_messages=(_BG.WM_LBUTTONUP,), mode="zero", fail_count=1)
    monkeypatch.setattr(_BG, "user32", fake)
    assert _BG._click_postmessage(1, 10, 10, "left", 0) is True
    assert len([m for m in fake.sent if m == _BG.WM_LBUTTONUP]) == 2


def test_frida_click_fails_when_both_ups_return_zero(monkeypatch, caplog):
    """down 成功、兩次 up 都回傳 0 → 回傳失敗並留下 warning。"""
    caplog.set_level(logging.WARNING)
    fake = _FakeUser32(fail_messages=(_BG.WM_LBUTTONUP,), mode="zero")
    monkeypatch.setattr(_BG, "user32", fake)
    assert _BG._click_postmessage(1, 10, 10, "left", 0) is False
    assert len([m for m in fake.sent if m == _BG.WM_LBUTTONUP]) == 2, "最多兩次嘗試"
    assert "放開訊息失敗" in caplog.text, "up 兩次都失敗必須留下 warning"


def test_frida_click_retries_when_first_up_raises(monkeypatch):
    """down 成功、第一次 up 拋例外、第二次成功 → 必須重試。"""
    fake = _FakeUser32(fail_messages=(_BG.WM_LBUTTONUP,), mode="raise", fail_count=1)
    monkeypatch.setattr(_BG, "user32", fake)
    assert _BG._click_postmessage(1, 10, 10, "left", 0) is True
    assert len([m for m in fake.sent if m == _BG.WM_LBUTTONUP]) == 2


def test_frida_click_fails_when_both_ups_raise(monkeypatch, caplog):
    """down 成功、兩次 up 都拋例外 → 回傳失敗。"""
    caplog.set_level(logging.WARNING)
    fake = _FakeUser32(fail_messages=(_BG.WM_LBUTTONUP,), mode="raise")
    monkeypatch.setattr(_BG, "user32", fake)
    assert _BG._click_postmessage(1, 10, 10, "left", 0) is False
    assert len([m for m in fake.sent if m == _BG.WM_LBUTTONUP]) == 2
    assert "放開訊息失敗" in caplog.text


def test_frida_click_still_sends_up_when_cancelled_between_down_and_up(monkeypatch):
    """cancel 發生於 down 與 up 之間 → 必要�� up 不得被跳過。"""
    cancel = threading.Event()
    fake = _FakeUser32()
    fake.on_message = lambda msg: cancel.set() if msg == _BG.WM_LBUTTONDOWN else None
    monkeypatch.setattr(_BG, "user32", fake)
    assert _BG._click_postmessage(1, 10, 10, "left", 5000, cancel) is True
    assert _BG.WM_LBUTTONUP in fake.sent, "取消不得跳過必要的 up"
    assert fake.sent.count(_BG.WM_LBUTTONUP) == 1, "up 不得重複"


# ── 19. background pynput 分支 ───────────────────────────────────────
class _RaisingCancel:
    """模擬按住等待階段拋出例外（press 成功之後的下游失敗）。"""

    def is_set(self):
        return False

    def wait(self, timeout=None):
        raise RuntimeError("hold wait failed")


def test_bg_pynput_click_does_not_release_when_press_failed(monkeypatch):
    """press 本身失敗 → 未登記 → 不得送出 release（不是「press 失敗仍釋放」）。"""
    dev = _Devices()
    monkeypatch.setattr(_PIN.pynput.mouse, "Controller", lambda: dev.mouse)
    monkeypatch.setattr(_BG, "_client_to_screen", lambda hwnd, x, y: (x, y))
    dev.mouse_fail["press:1"] = True
    assert _BG._click_pynput(1, 10, 10, "left", 0) is False
    assert _kinds(dev.events) == ["press_failed"], "press 失敗時不得送出 release"
    assert _still_held(dev.events) == {}


def test_bg_pynput_click_releases_when_step_after_press_fails(monkeypatch):
    """press 成功 → 後續流程拋出例外 → 必須嘗試釋放，且不得留下按住殘留。"""
    dev = _Devices()
    monkeypatch.setattr(_PIN.pynput.mouse, "Controller", lambda: dev.mouse)
    monkeypatch.setattr(_BG, "_client_to_screen", lambda hwnd, x, y: (x, y))
    assert _BG._click_pynput(1, 10, 10, "left", 100, _RaisingCancel()) is False
    assert _kinds(dev.events) == ["press", "release"], "press 成功後必須嘗試釋放"
    assert _still_held(dev.events) == {}, "不得留下 Fake backend 的按住狀態"


def test_bg_pynput_click_releases_normally(monkeypatch):
    dev = _Devices()
    monkeypatch.setattr(_PIN.pynput.mouse, "Controller", lambda: dev.mouse)
    monkeypatch.setattr(_BG, "_client_to_screen", lambda hwnd, x, y: (x, y))
    assert _BG._click_pynput(1, 10, 10, "left", 0) is True
    assert _kinds(dev.events) == ["press", "release"]
    assert _still_held(dev.events) == {}


# ── 20. hybrid focus_guard 仍還原 ───────────────────────────────────
class _FakeUser32Hybrid:
    def __init__(self, foreground=7):
        self.foreground = foreground

    def GetForegroundWindow(self):
        return self.foreground

    def GetCursorPos(self, _point):
        return True

    def SetCursorPos(self, _x, _y):
        return True

    def IsWindow(self, hwnd):
        return hwnd == 42

    def IsIconic(self, hwnd):
        return False

    def GetWindowThreadProcessId(self, _hwnd, _pid):
        return 1

    def AttachThreadInput(self, *_args):
        return True

    def SetForegroundWindow(self, hwnd):
        self.foreground = hwnd
        return True


def test_hybrid_focus_guard_restores_state_after_cancelled_hold(monkeypatch, devices):
    """hold 在 focus_guard 區塊內被取消 → hold 提前結束並釋放，focus_guard 仍還原。

    真實流程中 hybrid 模式的物理輸入就在 focus_guard 的 body 內執行，
    因此取消後的焦點／游標還原是必須成立的不變量。
    """
    calls = {"save": 0, "restore": [], "activate": [], "sleep": []}

    def _save():
        calls["save"] += 1
        return (99, 5, 6)

    def _activate(title):
        calls["activate"].append(title)
        return True

    monkeypatch.setattr(_hybrid, "_user32", _FakeUser32Hybrid())
    monkeypatch.setattr(_hybrid, "save_state", _save)
    monkeypatch.setattr(_hybrid, "restore_state", lambda state: calls["restore"].append(state))
    monkeypatch.setattr(_hybrid.time, "sleep", lambda s: calls["sleep"].append(s))

    cancel = threading.Event()
    hold_done = threading.Event()

    def _hold():
        _PIN.send_hold_key("a", 5000, cancel)
        hold_done.set()

    with _hybrid.focus_guard("game", _activate, 42) as ready:
        assert ready is True
        th = threading.Thread(target=_hold)
        th.start()
        # 等到按鍵確實被按下才取消（事件握手，不用固定 sleep 猜時序）
        assert devices.kb_pressed.wait(2.0), "hold 必須在取消前完成按下"
        cancel.set()
        assert hold_done.wait(2.0), "取消後 hold 必須提前結束"
        th.join(2.0)

    # hold 被取消：已確認 press 的按鍵被釋放，不留按住殘留
    assert _kinds(devices.events) == ["press", "release"]
    assert _still_held(devices.events) == {}

    # focus_guard 最終仍執行還原
    assert calls["save"] == 1
    assert calls["activate"] == ["game"]
    assert calls["restore"] == [(99, 5, 6)], "取消後仍必須還原游標與前景視窗"


# ── 21/22/23. Main Loop 傳遞 _stop_event ─────────────────────────────
def test_main_loop_click_passes_stop_event(monkeypatch):
    ml = _make_ml()
    seen = {}

    def _fake_send_click(x, y, button="left", hold_ms=0, cancel=None):
        seen["cancel"] = cancel
        return True

    monkeypatch.setattr(_ML._input_mod, "send_click", _fake_send_click)
    # make_main_loop 以實例屬性 stub 掉 _send_click；此處要驗證真正的方法本體
    assert _ML.MainLoop._send_click(ml, 150, 250, "left", 0) is True
    assert seen["cancel"] is ml._stop_event, "pynput 路徑必須收到同一個 stop event"


def test_main_loop_hold_key_passes_stop_event(monkeypatch):
    ml = _make_ml()
    seen = {}

    def _fake_send_hold_key(key, duration_ms=0, cancel=None):
        seen["cancel"] = cancel
        return True

    monkeypatch.setattr(_ML._input_mod, "send_hold_key", _fake_send_hold_key)
    monkeypatch.setattr(ml, "_focus_guard", lambda: _NullGuard())
    ml._is_tool_foreground = lambda: False
    ml._can_perform_action = lambda: True
    ml._activate_window = lambda: True

    ctx = _ML.StepContext(img=None, rect={"x": 0, "y": 0, "w": 100, "h": 100})
    rule = _ML.Rule(id="r", name="R", enabled=True, steps=[])
    ml._handle_key({"key": "a", "hold_ms": 500}, ctx, rule)
    assert seen["cancel"] is ml._stop_event, "鍵盤 hold 路徑必須收到同一個 stop event"


def test_main_loop_frida_click_passes_stop_event(monkeypatch):
    ml = _make_ml()
    ml._window_hwnd = 12345
    ml._config_store = type(
        "FakeConfigStore", (), {"get": lambda self, key="interaction_mode": "frida"}
    )()
    seen = {}

    def _fake_click(hwnd, x, y, button="left", hold_ms=0, cancel=None):
        seen["cancel"] = cancel
        return True

    monkeypatch.setattr(_ML._bg_input, "click", _fake_click)
    monkeypatch.setattr(_ML._bg_input, "set_method", lambda _m: None)
    assert _ML.MainLoop._send_click(ml, 150, 250, "left", 0) is True
    assert seen["cancel"] is ml._stop_event, "frida 路徑必須收到同一個 stop event"


class _NullGuard:
    def __enter__(self):
        return True

    def __exit__(self, *args):
        return False


# ── 24/25. drag ──────────────────────────────────────────────────────
def test_drag_cancelled_releases_mouse_button(devices):
    cancel = threading.Event()
    devices.mouse.on_press = cancel.set
    assert _PIN.send_drag(10, 10, 50, 50, "left", cancel) is True
    assert _kinds(devices.events) == ["press", "release"], "取消後必須釋放滑鼠按鈕"
    assert _still_held(devices.events) == {}


def test_drag_does_not_release_when_press_raises(devices):
    """press 本身失敗：沒有登記 → 不得送出 release。

    「press 成功後仍會釋放」由 test_drag_move_failure_releases_mouse_button 驗證。
    """
    devices.mouse_fail["press:1"] = True
    with pytest.raises(RuntimeError):
        _PIN.send_drag(10, 10, 50, 50)
    assert _kinds(devices.events) == ["press_failed"]
    assert not [e for e in devices.events if e[0].startswith("release")]


def test_drag_move_failure_releases_mouse_button(devices):
    """press 成功後移動失敗：必須嘗試釋放滑鼠按鈕。"""
    devices.mouse.fail_position_after_press = True
    with pytest.raises(RuntimeError):
        _PIN.send_drag(10, 10, 50, 50)
    assert _kinds(devices.events) == ["press", "release"], "press 成功後必須嘗試釋放"
    assert _still_held(devices.events) == {}


# ── 26. Stop 後不得開始第二個 hold ───────────────────────────────────
def test_second_hold_not_started_after_stop(devices):
    cancel = threading.Event()
    done = threading.Event()

    def _run():
        _PIN.send_hold_key("a", 3000, cancel)
        done.set()

    th = threading.Thread(target=_run)
    th.start()
    assert devices.kb_pressed.wait(2.0)
    cancel.set()
    assert done.wait(2.0)
    th.join()

    devices.events.clear()
    devices.kb_pressed.clear()
    assert _PIN.send_hold_key("b", 100, cancel) is False
    assert devices.events == [], "停止後不得開始第二個 hold"


# ── 27. 真實輸入設備未被觸碰 ─────────────────────────────────────────
def test_real_pynput_controller_never_instantiated(devices, monkeypatch):
    """真實 pynput Controller 不得被實例化。

    做法：先把 Controller 屬性換成「會記錄並立即失敗」的 tracker，確認輸入路徑
    確實在呼叫時才解析該屬性（因此測試可以完全取代真實裝置）；再換成 Fake
    factory 執行實際輸入路徑，確認 tracker（代表真實類別）從未被實例化。
    """
    instantiated = []

    class _RealTracker:
        """若真實 Controller 被實例化就會被記錄並立即失敗。"""

        def __init__(self, *args, **kwargs):
            instantiated.append(1)
            raise AssertionError("真實 pynput Controller 不得被實例化")

    original_mouse_cls = _PIN.pynput.mouse.Controller
    original_kb_cls = _PIN.pynput.keyboard.Controller

    # (1) 驗證輸入路徑在呼叫時才解析 Controller 屬性（沒有隱藏的真實類別參考）
    monkeypatch.setattr(_PIN.pynput.mouse, "Controller", _RealTracker)
    monkeypatch.setattr(_PIN.pynput.keyboard, "Controller", _RealTracker)
    with pytest.raises(AssertionError):
        _PIN.send_click(100, 100, "left", 0)
    assert instantiated == [1], "輸入路徑必須在呼叫時解析 Controller 屬性"

    # (2) 換成 Fake factory 後執行實際輸入路徑，全程不建立真實 Controller
    instantiated.clear()
    fake_mouse_calls = []
    fake_kb_calls = []

    def _fake_mouse_factory(*_args, **_kwargs):
        fake_mouse_calls.append(1)
        return devices.mouse

    def _fake_kb_factory(*_args, **_kwargs):
        fake_kb_calls.append(1)
        return devices.kb

    monkeypatch.setattr(_PIN.pynput.mouse, "Controller", _fake_mouse_factory)
    monkeypatch.setattr(_PIN.pynput.keyboard, "Controller", _fake_kb_factory)

    _PIN.send_hold_key("a", 10)
    _PIN.send_click(100, 100, "left", 0)

    assert fake_kb_calls == [1], "實際使用的必須是 Fake keyboard backend"
    assert fake_mouse_calls == [1], "實際使用的必須是 Fake mouse backend"
    assert instantiated == [], "真實 pynput Controller 不得被實例化"
    assert original_mouse_cls is not _RealTracker
    assert original_kb_cls is not _RealTracker
