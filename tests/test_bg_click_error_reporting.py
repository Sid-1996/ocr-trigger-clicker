"""R-1：Click PostMessage 的 DOWN / UP 失敗必須留下可回報的錯誤原因。

缺陷（修正前）：``core/16_bg_input.py::_click_postmessage`` 在 DOWN 失敗或
UP 失敗時只寫 log、沒有呼叫 ``_set_error()`` → 呼叫端讀 ``last_error()``
會拿到空字串：

- MainLoop 的 ``_report_bg_failure()`` 讀不到原因就直接 return（沒有原因就
  不回報）→ 使用者完全看不到點擊失敗。
- OCR Debug 的點擊失敗分支拿不到細節，只顯示「失敗」。

本檔沿用既有測試的假環境（假 Win32 / 假 Frida RPC），走真實的後台點擊
呼叫鏈（``bg_input.click`` → ``frida_bg.click`` → ``_click_postmessage``），
不送出任何真實輸入，也不建立真實 Frida session。
"""

import pytest
from conftest import _FakeExports, _FakeScript, _FakeSession
from test_bg_diag_reporting import (
    _BG,
    IMG,
    RECT,
    OcrResult,
    Rule,
    Step,
    _frida_main_loop,
    _main_loop_logs,
    _ml_mod,
)


class _RaisingUser32:
    """PostMessageW 會拋例外的假 user32（模擬 ctypes 層的意外）。"""

    def __init__(self):
        self.sent = []
        self.fail = set()
        self.raise_on = set()

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        self.sent.append(msg)
        if msg in self.raise_on:
            raise OSError("postmessage boom")
        return 0 if msg in self.fail else 1

    def ClientToScreen(self, hwnd, point):
        return None

    def GetAsyncKeyState(self, vk):
        return 0

    def MapVirtualKeyW(self, vk, mode):
        return vk


@pytest.fixture
def raising_user32(bg_env, monkeypatch):
    """把假 Win32 換成會拋例外的版本（DOWN／UP 送出時爆掉）。"""
    fake = _RaisingUser32()
    monkeypatch.setattr(_BG, "user32", fake)
    bg_env["user32"] = fake
    return fake


# ── DOWN 失敗 ─────────────────────────────────────────────────────────


def test_click_down_failure_returns_false(bg_env):
    """DOWN 失敗不得回報成功。"""
    bg_env["user32"].fail = {_BG.WM_LBUTTONDOWN}
    assert _BG.click(1, 10, 10) is False, "DOWN 失敗必須回傳 False"


def test_click_down_failure_records_reason(bg_env):
    """R-1 核心：DOWN 失敗必須留下可讀的錯誤原因（修正前為空字串）。"""
    bg_env["user32"].fail = {_BG.WM_LBUTTONDOWN}
    _BG.click(1, 10, 10)
    err = _BG.last_error()
    assert err, "DOWN 失敗必須留下錯誤原因"
    assert "按下" in err, f"必須是當次的按下失敗：{err!r}"
    assert f"0x{_BG.WM_LBUTTONDOWN:04X}" in err, f"必須標示失敗的訊息代碼：{err!r}"


def test_click_down_failure_does_not_send_up(bg_env):
    """DOWN 沒送出就不得送出 UP（否則會誤放其他按鍵）。"""
    bg_env["user32"].fail = {_BG.WM_LBUTTONDOWN}
    _BG.click(1, 10, 10)
    assert _BG.WM_LBUTTONUP not in bg_env["user32"].sent, "DOWN 失敗時不得送出放開訊息"


# ── UP 失敗 ───────────────────────────────────────────────────────────


def test_click_up_failure_returns_false(bg_env):
    """UP 失敗不得回報整個點擊成功（按鈕可能卡在遊戲裡）。"""
    bg_env["user32"].fail = {_BG.WM_LBUTTONUP}
    assert _BG.click(1, 10, 10) is False, "UP 失敗必須回傳 False"


def test_click_up_failure_records_reason(bg_env):
    """R-1 核心：UP 失敗必須留下可讀的錯誤原因（修正前為空字串）。"""
    bg_env["user32"].fail = {_BG.WM_LBUTTONUP}
    _BG.click(1, 10, 10)
    err = _BG.last_error()
    assert err, "UP 失敗必須留下錯誤原因"
    assert "放開" in err, f"必須是當次的放開失敗：{err!r}"


def test_click_up_failure_still_attempts_release(bg_env):
    """回傳 False 不得跳過必要的釋放：UP 一定要嘗試送出。"""
    bg_env["user32"].fail = {_BG.WM_LBUTTONUP}
    _BG.click(1, 10, 10)
    sent = bg_env["user32"].sent
    assert _BG.WM_LBUTTONDOWN in sent
    assert _BG.WM_LBUTTONUP in sent, "UP 失敗也要嘗試送出（記錄錯誤即可）"
    assert sent.count(_BG.WM_LBUTTONUP) >= 2, "放開失敗必須重試（既有行為）"


# ── 例外路徑 ──────────────────────────────────────────────────────────


def test_click_exception_records_reason(raising_user32):
    """送出訊息時拋例外 → 必須留下錯誤原因（不得只寫 log）。"""
    raising_user32.raise_on = {_BG.WM_LBUTTONDOWN}
    assert _BG.click(1, 10, 10) is False, "例外不得回報成功"
    err = _BG.last_error()
    assert err, "例外必須留下錯誤原因"
    assert "例外" in err, f"必須標示是例外：{err!r}"
    assert _BG.WM_LBUTTONUP not in raising_user32.sent, "DOWN 未送出時不得送 UP"


# ── 成功路徑 ──────────────────────────────────────────────────────────


def test_click_success_has_no_error(bg_env):
    """成功時不得留下錯誤（避免誤報失敗）。"""
    assert _BG.click(1, 10, 10) is True
    assert _BG.last_error() == "", "成功路徑不得留下錯誤原因"


def test_click_success_sends_down_and_up(bg_env):
    """成功路徑必須照常送出 DOWN + UP（修正不得影響正常行為）。"""
    assert _BG.click(1, 10, 10) is True
    sent = bg_env["user32"].sent
    assert _BG.WM_LBUTTONDOWN in sent
    assert _BG.WM_LBUTTONUP in sent


# ── MainLoop：錯誤原因必須真的走到回報通道 ───────────────────────────


def _click_rule():
    return Rule(
        id="r-click",
        name="點擊規則",
        enabled=True,
        steps=[Step(type="click", params={"target": "text_center"})],
    )


def _run_click(ml):
    ctx = _ml_mod.StepContext(img=IMG, rect=RECT)
    ctx.matched_text = OcrResult(text="確定", x=0, y=0, w=10, h=10, confidence=0.9)
    ml._run_rule(_click_rule(), IMG, RECT, ctx)
    return ctx


def test_mainloop_click_down_failure_reports_reason(bg_env, caplog):
    """MainLoop 必須拿到錯誤原因並回報（修正前因原因為空而完全靜默）。"""
    ml, reports = _frida_main_loop()
    bg_env["user32"].fail = {_BG.WM_LBUTTONDOWN}
    with caplog.at_level("INFO", logger="test_bg_diag_reporting"):
        ctx = _run_click(ml)
    assert reports, "點擊失敗必須走既有失敗回報通道"
    assert ctx.triggered is False, "失敗不得標記 triggered"
    logs = _main_loop_logs(caplog)
    assert any("按下" in m for m in logs), f"回報必須帶上失敗原因：{logs!r}"


def test_mainloop_click_up_failure_reports_reason(bg_env, caplog):
    """UP 失敗同樣必須帶著原因回報。"""
    ml, reports = _frida_main_loop()
    bg_env["user32"].fail = {_BG.WM_LBUTTONUP}
    with caplog.at_level("INFO", logger="test_bg_diag_reporting"):
        ctx = _run_click(ml)
    assert reports, "點擊失敗必須走既有失敗回報通道"
    assert ctx.triggered is False
    logs = _main_loop_logs(caplog)
    assert any("放開" in m for m in logs), f"回報必須帶上失敗原因：{logs!r}"


def test_mainloop_click_success_does_not_report(bg_env, caplog):
    """成功時不得誤報（避免使用者看到假的失敗通知）。"""
    ml, reports = _frida_main_loop()
    with caplog.at_level("INFO", logger="test_bg_diag_reporting"):
        ctx = _run_click(ml)
    assert reports == [], "成功時不得回報失敗"
    assert ctx.triggered is True
    assert not [m for m in _main_loop_logs(caplog) if "後台輸入失敗" in m], "成功時不得寫失敗紀錄"


# ── 自我檢查：不依賴 pytest 也能驗證核心斷言 ──────────────────────────


def _self_check() -> None:
    """模組自我檢查：DOWN 失敗有原因、UP 失敗有原因、成功無錯誤。"""
    user32 = _RaisingUser32()
    env = {"fail_key_rpc_times": 0, "fail_sync": False, "user32": user32}
    script = _FakeScript(_FakeExports(env))
    session = _FakeSession()
    frida = _BG._frida()
    prev_user32, prev_error = _BG.user32, _BG._last_error
    prev_script, prev_session, prev_pid = frida._script, frida._session, frida._pid
    prev_method = _BG.get_method()
    prev_ensure = frida.ensure_attached
    try:
        _BG.user32 = user32
        _BG._last_error = ""
        frida._script, frida._session, frida._pid = script, session, 1234
        frida.ensure_attached = lambda _hwnd: True
        _BG.set_method("frida")

        user32.raise_on = {_BG.WM_LBUTTONDOWN}
        assert _BG.click(1, 10, 10) is False, "DOWN 失敗必須回傳 False"
        assert "按下" in _BG.last_error(), "DOWN 失敗必須留下原因"

        user32.raise_on = set()
        user32.fail = {_BG.WM_LBUTTONUP}
        assert _BG.click(1, 10, 10) is False, "UP 失敗必須回傳 False"
        assert "放開" in _BG.last_error(), "UP 失敗必須留下原因"

        user32.fail = set()
        assert _BG.click(1, 10, 10) is True, "成功路徑必須回傳 True"
        assert _BG.last_error() == "", "成功路徑不得留下錯誤"
    finally:
        _BG.user32, _BG._last_error = prev_user32, prev_error
        frida._script, frida._session, frida._pid = prev_script, prev_session, prev_pid
        frida.ensure_attached = prev_ensure
        _BG.set_method(prev_method)
    print("  [OK] R-1（Click PostMessage 錯誤原因）自我檢查通過")


if __name__ == "__main__":
    print("=== R-1 Click PostMessage Error Reporting Self-Check ===\n")
    _self_check()
