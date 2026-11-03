"""P2-1：後台輸入 ``_last_error`` 的生命週期。

``last_error()`` 的每一個讀取點都緊接在「剛失敗的操作」之後——
``core/05_main_loop.py`` 的 ``_report_bg_failure()``、``gui/09_ocr_debug.py`` 的
失敗分支、``devtools/coordinate_calibration.py`` 的診斷分支——
語意是「剛才那次操作失敗的原因」，不是「歷史上最後一次錯誤」。

本檔用真實的後台操作（假 Win32 / 假 Frida RPC）驅動狀態轉換，驗證：

1. 前一次操作失敗 → 下一次操作成功 → 錯誤不殘留
2. 前一次操作失敗 → 下一次操作產生不同錯誤 → 新錯誤不被舊錯誤遮蔽
3. bg 層與 frida 層連續失敗 → 各自的錯誤都看得到
4. 舊錯誤不遮蔽新錯誤（兩層優先序維持不變）
5. 取消的操作不留下錯誤、也不讓 _report_bg_failure 回報過期原因
6. Release（UP）與重試路徑回報的是當次操作的錯誤

不送出任何真實輸入，也不建立真實 Frida session。
"""

import threading

import pytest
from conftest import make_main_loop

from _loader import load_sibling

_BG = load_sibling("bg_input", "core/16_bg_input.py")
_FR = load_sibling("frida_bg", "core/18_frida_bg.py")


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
        return None  # 保持傳入的 client 座標不變即可

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
        # 真實 ensure_attached 成功時會重新掛上 script 並清空錯誤
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


# ── 1. 前一次失敗 → 下一次成功 ──────────────────────────────────────
def test_error_not_residual_after_next_success(bg_env):
    """前一次操作失敗（UP 放開失敗），下一次成功後不得殘留舊錯誤。"""
    bg_env["fail_key_rpc_times"] = 0
    bg_env["user32"].fail = {_BG.WM_KEYUP}
    _BG.send_key(1, "a")
    old = _BG.last_error()
    assert "放開" in old, f"UP 失敗必須記錄錯誤：{old!r}"

    bg_env["user32"].fail = set()
    _BG.send_key(1, "a")
    assert _BG.last_error() == "", "成功之後不得殘留上一次的錯誤"


# ── 2. 前一次失敗 → 下一次不同錯誤 ──────────────────────────────────
def test_new_error_not_masked_by_previous_error(bg_env):
    """前一次是 bg 層錯誤，下一次是 frida 層錯誤 → 必須看到新的那個。"""
    bg_env["user32"].fail = {_BG.WM_KEYUP}
    _BG.send_key(1, "a")
    old = _BG.last_error()
    assert old

    bg_env["user32"].fail = set()
    bg_env["fail_sync"] = True
    assert _BG.click(1, 10, 20, "left", 0) is False
    err = _BG.last_error()
    assert err != old, f"新錯誤不得被舊錯誤遮蔽：{err!r}"
    assert "座標同步失敗" in err, f"必須是新的 frida 層錯誤：{err!r}"


# ── 3. bg 層與 frida 層連續發生錯誤 ─────────────────────────────────
def test_bg_and_frida_errors_alternate_visible(bg_env):
    """frida 錯誤 → bg 錯誤 → frida 錯誤：每一次都看得到當次的錯誤。"""
    bg_env["fail_sync"] = True
    _BG.click(1, 10, 20, "left", 0)
    assert "座標同步失敗" in _BG.last_error()

    bg_env["fail_sync"] = False
    bg_env["user32"].fail = {_BG.WM_KEYUP}
    _BG.send_key(1, "a")
    assert "放開" in _BG.last_error(), f"必須是 bg 層的放開錯誤：{_BG.last_error()!r}"

    bg_env["user32"].fail = set()
    bg_env["fail_sync"] = True
    _BG.click(1, 10, 20, "left", 0)
    assert "座標同步失敗" in _BG.last_error(), "後續的 frida 錯誤不得被 bg 舊錯誤遮蔽"


# ── 4. 舊錯誤不遮蔽新錯誤（優先序維持不變）─────────────────────────
def test_layer_priority_order_unchanged(bg_env):
    """兩層都有錯誤時維持既有優先序（bg 優先）——不改變公開 API 契約。"""
    _BG._set_error("BG-ERROR")
    _FR._set_error("FRIDA-ERROR")
    assert _BG.last_error() == "BG-ERROR"


def test_previous_frida_error_does_not_survive_into_next_operation(bg_env):
    """前一次操作留下的 frida 錯誤，不得在下一次操作後仍被讀到。"""
    bg_env["fail_sync"] = True
    _BG.click(1, 10, 20, "left", 0)
    assert _BG.last_error()

    bg_env["fail_sync"] = False
    _BG.click(1, 10, 20, "left", 0)
    assert _BG.last_error() == "", "成功操作後不得讀到前一次的 frida 錯誤"


# ── 5. 取消操作不破壞錯誤狀態 ───────────────────────────────────────
def test_cancelled_operation_leaves_no_error(bg_env):
    """被取消的操作不得留下錯誤，也不得讓舊錯誤繼續被讀到。"""
    bg_env["user32"].fail = {_BG.WM_KEYUP}
    _BG.send_key(1, "a")
    assert _BG.last_error(), "前置條件：先製造一個真實錯誤"

    bg_env["user32"].fail = set()
    cancel = threading.Event()
    cancel.set()
    assert _BG.send_key(1, "a", cancel) is False
    assert _BG.last_error() == "", "取消的操作不得留下錯誤狀態"


def test_cancelled_operation_does_not_report_stale_bg_failure(bg_env):
    """被取消的操作不得讓 _report_bg_failure 回報過期原因。

    MainLoop 在後台動作回傳 False 時會呼叫 _report_bg_failure()；若錯誤狀態
    殘留，取消（不是失敗）也會被回報成「後台輸入失敗」。
    """
    ml = make_main_loop()
    reports: list = []
    ml.on_bg_fail = lambda: reports.append(1)

    _BG._set_error("STALE-ERROR")
    cancel = threading.Event()
    cancel.set()
    _BG.send_key(1, "a", cancel)

    ml._report_bg_failure()
    assert reports == [], "被取消的操作不得回報過期的背景錯誤"
    assert _BG.last_error() == ""


# ── 6. Release / 重試路徑 ───────────────────────────────────────────
def test_release_failure_reports_current_operation_error(bg_env):
    """UP（Release）失敗必須回報當次操作的錯誤。"""
    bg_env["user32"].fail = {_BG.WM_KEYUP}
    _BG.send_key(1, "a")
    err = _BG.last_error()
    assert "放開" in err, f"Release 失敗必須記錄錯誤：{err!r}"
    assert "STALE" not in err


def test_retry_recovers_without_leaving_error_state(bg_env):
    """rpc 失敗觸發重試、重試成功後不得殘留錯誤狀態。"""
    bg_env["fail_key_rpc_times"] = 1  # 第一次 rpc 失敗 → 重新 attach 後重試
    assert _BG.send_key(1, "a") is True
    assert _BG.last_error() == "", "重試成功後不得殘留錯誤狀態"


def test_down_failure_does_not_leave_stale_release_error(bg_env):
    """DOWN 失敗（不送 UP）時，錯誤必須是當次的 DOWN 失敗，不是更早的舊錯誤。"""
    bg_env["user32"].fail = {_BG.WM_KEYUP}
    _BG.send_key(1, "a")
    assert "放開" in _BG.last_error()

    bg_env["user32"].fail = set()
    bg_env["fail_key_rpc_times"] = 99  # DOWN 的 rpc 持續失敗 → 最終失敗
    _BG.send_key(1, "a")
    err = _BG.last_error()
    assert "放開" not in err, f"不得回報上一次的 Release 錯誤：{err!r}"
    assert "鍵盤狀態同步失敗" in err, f"必須是當次的 DOWN 失敗：{err!r}"
