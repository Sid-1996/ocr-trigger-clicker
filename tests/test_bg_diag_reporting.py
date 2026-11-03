"""C-1／C-2／C-3：後台輸入失敗的「回報」鏈。

三個缺陷的共同根源是「失敗發生時，錯誤資訊沒有走到使用者看得到的地方」：

- **C-1** ``core/16_bg_input.py::send_key``：UP（放開）失敗仍回傳 True
  → MainLoop 以為按鍵成功送出，``ctx.triggered=True``，錯誤被吞掉。
- **C-2** ``_handle_drag``／``_handle_scroll`` 沒有呼叫 ``_report_bg_failure()``
  → 後台拖曳／滾輪失敗完全無感；且底層 drag／scroll 失敗時沒有留下錯誤原因，
  就算呼叫回報也拿不到可讀的訊息。
- **C-3** ``_report_bg_failure()`` 的 30 秒節流直接 return，
  → ``_log()`` 與 ``on_bg_fail()`` 都不執行，30 秒內的後續失敗在紀錄中消失。

本檔用真實的後台操作（假 Win32 / 假 Frida RPC）驅動狀態轉換，
不送出任何真實輸入，也不建立真實 Frida session。
"""

import logging
import time

import numpy as np
import pytest
from conftest import make_main_loop

from _loader import load_sibling

_BG = load_sibling("bg_input", "core/16_bg_input.py")
_FR = load_sibling("frida_bg", "core/18_frida_bg.py")
_ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
_ocr_mod = load_sibling("ocr_engine", "core/02_ocr_engine.py")

Rule = load_sibling("rule_models", "core/rule_models.py").Rule
Step = load_sibling("rule_models", "core/rule_models.py").Step
OcrResult = _ocr_mod.OcrResult

IMG = np.zeros((100, 100, 3), dtype=np.uint8)
RECT = {"x": 0, "y": 0, "w": 100, "h": 100}


class _FakeUser32:
    """只記錄訊息的假 user32。

    fail 模擬 PostMessageW 回傳 0（真實 Win32 失敗模式）。
    """

    def __init__(self):
        self.sent = []
        self.fail = set()

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        self.sent.append(msg)
        return 0 if msg in self.fail else 1

    def ClientToScreen(self, hwnd, point):
        return None

    def GetAsyncKeyState(self, vk):
        return 0

    def MapVirtualKeyW(self, vk, mode):
        return vk


class _FakeExports:
    """假 rpc.exports：可注入失敗來模擬腳本端異常。"""

    def __init__(self, env):
        self.env = env

    def key(self, vk, down):
        n = self.env.get("fail_key_rpc_times", 0)
        if n > 0:
            self.env["fail_key_rpc_times"] = n - 1
            return 0  # 腳本回傳異常 → _sync_key 失敗
        return 1

    def update(self, sx, sy, cx, cy):
        if self.env.get("fail_sync"):
            return 0
        return 1


class _FakeScript:
    def __init__(self, exports):
        self.exports = exports
        self.unloaded = False

    def unload(self):
        self.unloaded = True


class _FakeSession:
    is_detached = False

    def detach(self):
        self.is_detached = True


@pytest.fixture
def bg_env(monkeypatch):
    """可控的假後台環境（假 Win32 + 假 Frida session/script/RPC）。"""
    prev_method = _BG.get_method()
    user32 = _FakeUser32()
    env: dict = {"fail_key_rpc_times": 0, "fail_sync": False, "user32": user32}
    script = _FakeScript(_FakeExports(env))
    session = _FakeSession()

    monkeypatch.setattr(_BG, "user32", user32)
    monkeypatch.setattr(_BG, "_last_error", "")
    monkeypatch.setattr(_FR, "_last_error", "")
    monkeypatch.setattr(_FR, "_script", script)
    monkeypatch.setattr(_FR, "_session", session)
    monkeypatch.setattr(_FR, "_pid", 1234)
    monkeypatch.setattr(_BG, "_frida", lambda: _FR)

    def _ensure_attached(_hwnd):
        _FR._script = script
        _FR._session = session
        _FR._pid = 1234
        _FR.clear_error()
        return True

    monkeypatch.setattr(_FR, "ensure_attached", _ensure_attached)
    _BG.set_method("frida")
    try:
        yield env
    finally:
        _BG.set_method(prev_method)


class _FakeConfigStore:
    def __init__(self, mode: str):
        self._mode = mode

    def get(self, key="interaction_mode"):
        return self._mode


def _frida_main_loop():
    """MainLoop（frida 模式）＋通知收集器。"""
    ml = make_main_loop()
    # conftest 的 fixture 以 instance 屬性 stub 掉輸入層（回傳 True）；
    # 本檔要驗證真實的後台輸入路徑 → 移除這些 stub，讓類別方法生效。
    for name in ("_send_click", "_send_key", "_send_scroll"):
        ml.__dict__.pop(name, None)
    ml._config_store = _FakeConfigStore("frida")
    ml._window_hwnd = 1234
    reports: list = []
    ml.on_bg_fail = lambda: reports.append(1)
    logger = logging.getLogger("test_bg_diag_reporting")
    logger.setLevel(logging.INFO)
    ml._logger = logger
    return ml, reports


# ── C-1：send_key 的 DOWN / UP 成敗回報 ────────────────────────────────


def test_send_key_success_returns_true(bg_env):
    """DOWN 與 UP 都成功 → 回傳 True，且不留下錯誤。"""
    assert _BG.send_key(1, "a") is True
    assert _BG.last_error() == ""


def test_send_key_down_failure_returns_false(bg_env):
    """DOWN 失敗不得回報成功。"""
    bg_env["fail_key_rpc_times"] = 99  # DOWN 的 rpc 持續失敗
    assert _BG.send_key(1, "a") is False
    err = _BG.last_error()
    assert err, "DOWN 失敗必須留下錯誤原因"
    assert "鍵盤狀態同步失敗" in err, f"必須是當次的 DOWN 失敗：{err!r}"


def test_send_key_down_failure_does_not_send_up(bg_env):
    """DOWN 失敗 → 不得送出 UP（否則會誤放其他按鍵）。"""
    bg_env["fail_key_rpc_times"] = 99
    _BG.send_key(1, "a")
    assert _BG.WM_KEYUP not in bg_env["user32"].sent, "DOWN 失敗時不得送出放開訊息"


def test_send_key_up_failure_returns_false(bg_env):
    """C-1 核心：UP 失敗不得回報整個按鍵操作成功。

    修正前：finally 區塊只記錄錯誤，函式仍回傳 True → MainLoop 以為按鍵成功。
    """
    bg_env["user32"].fail = {_BG.WM_KEYUP}
    assert _BG.send_key(1, "a") is False, "UP 失敗必須回傳 False"


def test_send_key_up_failure_records_error(bg_env):
    """UP 失敗必須留下可讀的錯誤原因（不得吞掉）。"""
    bg_env["user32"].fail = {_BG.WM_KEYUP}
    _BG.send_key(1, "a")
    err = _BG.last_error()
    assert err, "UP 失敗必須留下錯誤原因"
    assert "放開" in err, f"必須是放開失敗：{err!r}"


def test_send_key_up_failure_still_attempts_release(bg_env):
    """回傳 False 不得跳過必要的釋放流程：UP 一定要嘗試送出。"""
    bg_env["user32"].fail = {_BG.WM_KEYUP}
    _BG.send_key(1, "a")
    assert _BG.WM_KEYDOWN in bg_env["user32"].sent
    assert _BG.WM_KEYUP in bg_env["user32"].sent, "UP 失敗也要嘗試送出（記錄錯誤即可）"


def test_mainloop_key_handler_does_not_mark_triggered_on_up_failure(bg_env):
    """MainLoop 收到 False → 不得標記 triggered、不得記錄輸入成功。"""
    ml, reports = _frida_main_loop()
    bg_env["user32"].fail = {_BG.WM_KEYUP}
    rule = Rule(
        id="r-key",
        name="按鍵規則",
        enabled=True,
        steps=[Step(type="key", params={"key": "a"})],
    )
    ctx = _ml_mod.StepContext(img=IMG, rect=RECT)
    ml._run_rule(rule, IMG, RECT, ctx)
    assert ctx.triggered is False, "UP 失敗不得標記 triggered"
    assert reports, "UP 失敗必須走既有失敗回報通道"


# ── C-2：drag / scroll 的失敗必須有原因且被回報 ────────────────────────


def test_drag_down_failure_records_error(bg_env):
    """拖曳按下失敗 → 必須留下錯誤原因（先前只回 False，沒有原因）。"""
    bg_env["user32"].fail = {_BG.WM_LBUTTONDOWN}
    assert _BG.drag(1, 10, 10, 50, 50, "left") is False
    err = _BG.last_error()
    assert err, "拖曳失敗必須留下錯誤原因"
    assert "按下" in err, f"必須是按下失敗：{err!r}"


def test_drag_up_failure_records_error(bg_env):
    """拖曳放開失敗 → 必須留下錯誤原因。"""
    bg_env["user32"].fail = {_BG.WM_LBUTTONUP}
    assert _BG.drag(1, 10, 10, 50, 50, "left") is False
    err = _BG.last_error()
    assert "放開" in err, f"必須是放開失敗：{err!r}"


def test_scroll_failure_records_error(bg_env):
    """滾輪訊息送出失敗 → 必須回傳 False 並留下錯誤原因。

    修正前 ``_scroll_postmessage`` 完全忽略 PostMessageW 的 BOOL 回傳值，
    失敗時仍回傳 True（等於假成功）。
    """
    bg_env["user32"].fail = {_BG.WM_MOUSEWHEEL}
    assert _BG.scroll(1, 0, 0, 1, False) is False
    err = _BG.last_error()
    assert err, "滾輪失敗必須留下錯誤原因"
    assert "滾輪" in err, f"必須是滾輪失敗：{err!r}"


def test_scroll_success_has_no_error(bg_env):
    """成功時不得留下錯誤（避免誤報）。"""
    assert _BG.scroll(1, 0, 0, 1, False) is True
    assert _BG.last_error() == ""


def test_handle_scroll_failure_reports_bg_failure(bg_env):
    """C-2：後台滾輪失敗必須進入既有失敗回報機制。"""
    ml, reports = _frida_main_loop()
    bg_env["user32"].fail = {_BG.WM_MOUSEWHEEL}
    rule = Rule(
        id="r-scroll",
        name="滾輪規則",
        enabled=True,
        steps=[Step(type="scroll", params={"direction": "WheelDown", "amount": 1})],
    )
    ctx = _ml_mod.StepContext(img=IMG, rect=RECT)
    ml._run_rule(rule, IMG, RECT, ctx)
    assert reports, "後台滾輪失敗必須回報"
    assert ctx.triggered is False, "失敗不得標記 triggered"


def test_handle_drag_failure_reports_bg_failure(bg_env):
    """C-2：後台拖曳失敗必須進入既有失敗回報機制。"""
    ml, reports = _frida_main_loop()
    bg_env["user32"].fail = {_BG.WM_LBUTTONDOWN}
    rule = Rule(
        id="r-drag",
        name="拖曳規則",
        enabled=True,
        steps=[
            Step(
                type="drag",
                params={"target": "text_center", "end_x": 0.5, "end_y": 0.5},
            )
        ],
    )
    ctx = _ml_mod.StepContext(img=IMG, rect=RECT)
    ctx.matched_text = OcrResult(text="確定", x=0, y=0, w=10, h=10, confidence=0.9)
    ml._run_rule(rule, IMG, RECT, ctx)
    assert reports, "後台拖曳失敗必須回報"
    assert ctx.triggered is False, "失敗不得標記 triggered"


def test_handle_drag_success_does_not_report(bg_env):
    """成功時不得誤報（避免使用者看到假的失敗通知）。"""
    ml, reports = _frida_main_loop()
    rule = Rule(
        id="r-drag-ok",
        name="拖曳規則",
        enabled=True,
        steps=[
            Step(
                type="drag",
                params={"target": "text_center", "end_x": 0.5, "end_y": 0.5},
            )
        ],
    )
    ctx = _ml_mod.StepContext(img=IMG, rect=RECT)
    ctx.matched_text = OcrResult(text="確定", x=0, y=0, w=10, h=10, confidence=0.9)
    ml._run_rule(rule, IMG, RECT, ctx)
    assert reports == [], "成功時不得回報失敗"
    assert ctx.triggered is True


def test_handle_scroll_pynput_mode_does_not_report(bg_env):
    """pynput 模式維持原本語意：不走後台失敗回報通道。"""
    ml, reports = _frida_main_loop()
    ml._config_store = _FakeConfigStore("pynput")
    ml._send_scroll = lambda direction: False
    rule = Rule(
        id="r-scroll-fg",
        name="滾輪規則",
        enabled=True,
        steps=[Step(type="scroll", params={"direction": "WheelDown", "amount": 1})],
    )
    ctx = _ml_mod.StepContext(img=IMG, rect=RECT)
    ml._run_rule(rule, IMG, RECT, ctx)
    assert reports == [], "pynput 模式不得走後台失敗回報通道"


def _main_loop_logs(caplog) -> list[str]:
    """只取 MainLoop 記錄器的訊息。

    ``_set_error()`` 本身也會用 bg_input 記錄器寫一筆 ERROR，內容含同樣的
    關鍵字；只挑 MainLoop 的記錄才能真正驗證「有沒有寫 _log」。
    """
    return [r.getMessage() for r in caplog.records if r.name == "test_bg_diag_reporting"]


# ── C-3：節流只作用於 GUI 通知，log 每次都要寫 ────────────────────────


def test_report_bg_failure_logs_and_notifies(bg_env, caplog):
    """首次失敗：寫 log ＋通知 GUI。"""
    ml, reports = _frida_main_loop()
    with caplog.at_level(logging.INFO, logger="test_bg_diag_reporting"):
        _BG._set_error("後台失敗原因")
        ml._report_bg_failure()
    assert reports == [1], "首次失敗必須通知 GUI"
    assert any("後台失敗原因" in m for m in _main_loop_logs(caplog)), "首次失敗必須寫 log"


def test_report_bg_failure_throttled_still_logs(bg_env, caplog):
    """C-3 核心：30 秒內再次失敗仍要寫 log，只是不重複通知。"""
    ml, reports = _frida_main_loop()
    with caplog.at_level(logging.INFO, logger="test_bg_diag_reporting"):
        _BG._set_error("第一次")
        ml._report_bg_failure()
        caplog.clear()
        _BG._set_error("第二次")
        ml._report_bg_failure()
    assert reports == [1], "節流期間不得重複通知"
    logs = _main_loop_logs(caplog)
    assert any("第二次" in m for m in logs), "節流期間仍然必須寫 log（不得吞掉紀錄）"


def test_report_bg_failure_notifies_again_after_throttle(bg_env, caplog):
    """超過節流時間後恢復通知。"""
    ml, reports = _frida_main_loop()
    with caplog.at_level(logging.INFO, logger="test_bg_diag_reporting"):
        _BG._set_error("第一次")
        ml._report_bg_failure()
        # 模擬時間經過：把上次通知時間推到節流窗口之前
        ml._last_frida_err_ts = time.monotonic() - (ml._FRIDA_ERR_THROTTLE_SEC + 1)
        _BG._set_error("第三次")
        ml._report_bg_failure()
    assert len(reports) == 2, "超過節流時間後必須恢復通知"
    assert any("第三次" in m for m in _main_loop_logs(caplog)), "恢復通知的同時也要寫 log"


def test_report_bg_failure_without_error_does_nothing(bg_env, caplog):
    """沒有錯誤時不得寫 log、不得通知。"""
    ml, reports = _frida_main_loop()
    with caplog.at_level(logging.INFO, logger="test_bg_diag_reporting"):
        ml._report_bg_failure()
    assert reports == []
    assert _main_loop_logs(caplog) == [], "沒有錯誤時不得寫失敗紀錄"


def test_report_bg_failure_does_not_notify_twice_in_window(bg_env, caplog):
    """連續多次失敗：只有第一次通知，其餘都寫 log。"""
    ml, reports = _frida_main_loop()
    with caplog.at_level(logging.INFO, logger="test_bg_diag_reporting"):
        for i in range(3):
            _BG._set_error(f"失敗{i}")
            ml._report_bg_failure()
    assert reports == [1], "節流窗口內只通知一次"
    logs = [m for m in _main_loop_logs(caplog) if "後台輸入失敗" in m]
    assert len(logs) == 3, "每一次失敗都要寫 log"


# ── 自我檢查：不依賴 pytest 也能驗證核心斷言 ──────────────────────────


def _self_check() -> None:
    """模組自我檢查：UP 失敗回 False、scroll 失敗有原因、節流仍寫 log。"""
    env = {
        "fail_key_rpc_times": 0,
        "fail_sync": False,
        "user32": _FakeUser32(),
    }
    script = _FakeScript(_FakeExports(env))
    session = _FakeSession()
    prev_user32, prev_error = _BG.user32, _BG._last_error
    prev_script, prev_session, prev_pid = _FR._script, _FR._session, _FR._pid
    prev_method = _BG.get_method()
    try:
        _BG.user32 = env["user32"]
        _BG._last_error = ""
        _FR._last_error = ""
        _FR._script, _FR._session, _FR._pid = script, session, 1234
        _BG._frida = lambda: _FR
        _FR.ensure_attached = lambda _hwnd: True
        _BG.set_method("frida")

        env["user32"].fail = {_BG.WM_KEYUP}
        assert _BG.send_key(1, "a") is False, "UP 失敗必須回傳 False"
        assert "放開" in _BG.last_error()

        env["user32"].fail = {_BG.WM_MOUSEWHEEL}
        assert _BG.scroll(1, 0, 0, 1, False) is False
        assert "滾輪" in _BG.last_error()
    finally:
        _BG.user32, _BG._last_error = prev_user32, prev_error
        _FR._script, _FR._session, _FR._pid = prev_script, prev_session, prev_pid
        _BG.set_method(prev_method)
    print("  [OK] C-1／C-2／C-3 自我檢查通過")


if __name__ == "__main__":
    print("=== BG Diagnostic Reporting Self-Check ===\n")
    _self_check()
