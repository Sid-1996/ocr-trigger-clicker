"""E2-A2-F1：Frida 後端的取消邊界與 Key Release 回報。

涵蓋 E2-A2-R 驗收報告的 P1-1 / P1-2 / P2-4 / P2-2：

- Frida ``key()``：attach 前與 attach 後都要檢查 cancel；attach 期間抵達的 Stop
  不得變成一次真實按鍵；DOWN 成功後 UP 永不受閘阻擋。
- Frida ``click()``：DOWN 送出前必須補齊取消閘（sync_cursor / attach 可能阻塞數秒）。
- Frida ``send_hold_key()``：cancel 必須傳進 frida ``key()`` 的 DOWN 路徑。
- ``_key_postmessage()``：必須檢查 PostMessageW 的 BOOL 回傳值，DOWN/UP 失敗都要
  留下錯誤資訊，UP 失敗不得回報成成功。

全部使用可控的假 script / 假 RPC / 假 PostMessage：驗證實際呼叫順序與副作用，
不送出任何真實輸入，也不建立真實 Frida session。
"""

import threading

import pytest

from _loader import load_sibling

_BG = load_sibling("bg_input", "core/16_bg_input.py")
_FR = load_sibling("frida_bg", "core/18_frida_bg.py")


# ── 假 Win32 / 假 Frida ─────────────────────────────────────────────
class _FakeUser32:
    """只記錄訊息的假 user32。

    fail 用來模擬 PostMessageW 回傳 0（真實 Win32 失敗模式）；
    on_send 用來在特定訊息送出後觸發副作用（例如模擬使用者在此刻按 Stop）。
    """

    def __init__(self):
        self.sent = []
        self.fail = set()
        self.on_send = None

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        self.sent.append(msg)
        if self.on_send is not None:
            self.on_send(msg)
        return 0 if msg in self.fail else 1

    def ClientToScreen(self, hwnd, point):
        return None  # 保持傳入的 client 座標不變即可

    def GetAsyncKeyState(self, vk):
        return 0

    def MapVirtualKeyW(self, vk, mode):
        return vk  # 掃碼只需非零即可（測試不驗證實際掃碼值）


class _FakeExports:
    """假 rpc.exports：記錄 key / update 呼叫並回傳 1（腳本已接受）。"""

    def __init__(self, calls):
        self.calls = calls
        self.on_key = None

    def key(self, vk, down):
        self.calls.append(("rpc_key", vk, down))
        if self.on_key is not None:
            self.on_key(vk, down)
        return 1

    def update(self, sx, sy, cx, cy):
        self.calls.append(("rpc_update", cx, cy))
        return 1


class _FakeScript:
    def __init__(self, exports):
        self.exports = exports


class _FakeSession:
    is_detached = False


@pytest.fixture
def frida_env(monkeypatch):
    """安裝可控的假 frida 環境。

    回傳的 env 可設定 ``on_attach``（在 ensure_attached 期間執行的 hook，
    用來模擬 attach 期間抵達 Stop）與 ``exports.on_key``（DOWN RPC 副作用）。
    """
    prev_method = _BG.get_method()
    calls: list = []
    exports = _FakeExports(calls)
    user32 = _FakeUser32()

    monkeypatch.setattr(_FR, "_script", _FakeScript(exports))
    monkeypatch.setattr(_FR, "_session", _FakeSession())
    monkeypatch.setattr(_FR, "_pid", 0)
    monkeypatch.setattr(_BG, "user32", user32)
    monkeypatch.setattr(_BG, "_last_error", "")
    # frida 模組的 _last_error 是跨測試黏著的模組級別名稱，必須一併歸零，
    # 否則其他測試（例如 frida 注入失敗）留下的錯誤會污染本檔的斷言。
    monkeypatch.setattr(_FR, "_last_error", "")
    monkeypatch.setattr(_BG, "_frida", lambda: _FR)

    env = {
        "calls": calls,
        "exports": exports,
        "user32": user32,
        "on_attach": None,
    }

    def _ensure_attached(_hwnd):
        hook = env.get("on_attach")
        if hook is not None:
            hook()
        return True

    monkeypatch.setattr(_FR, "ensure_attached", _ensure_attached)
    _BG.set_method("frida")
    try:
        yield env
    finally:
        _BG.set_method(prev_method)


def _rpc_keys(env):
    return [c for c in env["calls"] if c[0] == "rpc_key"]


# ══════════════════════════════════════════════════════════════════════
# 1-3. Frida key：取消邊界
# ══════════════════════════════════════════════════════════════════════


def test_frida_key_cancel_already_set_sends_no_down(frida_env):
    """需求 1：cancel 初始已設定 → 不得送出 DOWN。"""
    cancel = threading.Event()
    cancel.set()

    assert _FR.key(1, 0x41, True, cancel) is False
    assert _rpc_keys(frida_env) == [], "已取消時不得發出 key rpc"
    assert _BG.WM_KEYDOWN not in frida_env["user32"].sent, "已取消時不得送出 WM_KEYDOWN"


def test_frida_key_cancel_during_attach_sends_no_down(frida_env):
    """需求 2：ensure_attached 期間收到 Stop → attach 返回後不得送出 DOWN。"""
    cancel = threading.Event()
    frida_env["on_attach"] = cancel.set

    assert _FR.key(1, 0x41, True, cancel) is False
    assert _rpc_keys(frida_env) == [], "attach 期間的 Stop 必須攔下 DOWN"
    assert _BG.WM_KEYDOWN not in frida_env["user32"].sent


def test_frida_key_up_still_sent_after_cancel(frida_env):
    """需求 3：DOWN 成功後才收到 Stop → UP 仍必須送出（不受閘阻擋）。"""
    cancel = threading.Event()
    frida_env["exports"].on_key = lambda vk, down: cancel.set() if down else None

    assert _FR.key(1, 0x41, True, cancel) is True
    assert _BG.WM_KEYDOWN in frida_env["user32"].sent

    # 放開不得受取消閘阻擋：即使 cancel 已設定，UP 一樣要送出
    assert _FR.key(1, 0x41, False) is True
    assert _BG.WM_KEYUP in frida_env["user32"].sent, "DOWN 之後必須送出 UP"
    assert _rpc_keys(frida_env) == [("rpc_key", 0x41, 1), ("rpc_key", 0x41, 0)]


def test_bg_send_key_up_still_sent_when_cancelled_after_down(frida_env):
    """需求 3（完整路徑）：send_key 的 finally 必須補送 UP。"""
    cancel = threading.Event()
    frida_env["exports"].on_key = lambda vk, down: cancel.set() if down else None

    assert _BG.send_key(1, "a", cancel) is True
    downs = [c[2] for c in _rpc_keys(frida_env)]
    assert downs == [1, 0], "DOWN 之後必須補送 UP"
    assert _BG.WM_KEYUP in frida_env["user32"].sent


# ══════════════════════════════════════════════════════════════════════
# 4-6. Frida click：DOWN 前取消閘
# ══════════════════════════════════════════════════════════════════════


def test_frida_click_cancel_already_set_sends_no_down(frida_env):
    """需求 4：cancel 初始已設定 → 不得送出 DOWN。"""
    cancel = threading.Event()
    cancel.set()

    assert _FR.click(1, 10, 20, "left", 0, cancel) is False
    assert _BG.WM_LBUTTONDOWN not in frida_env["user32"].sent


def test_bg_click_cancel_already_set_sends_no_down(frida_env):
    """需求 4（bg 層）：cancel 初始已設定 → 不得送出 DOWN。"""
    cancel = threading.Event()
    cancel.set()

    assert _BG.click(1, 10, 20, "left", 0, cancel) is False
    assert _BG.WM_LBUTTONDOWN not in frida_env["user32"].sent


def test_frida_click_cancel_during_attach_sends_no_down(frida_env):
    """需求 5：attach 期間收到 cancel → 返回後不得送出 DOWN。"""
    cancel = threading.Event()
    frida_env["on_attach"] = cancel.set

    assert _FR.click(1, 10, 20, "left", 0, cancel) is False
    assert _BG.WM_LBUTTONDOWN not in frida_env["user32"].sent, "attach 期間的 Stop 必須攔下 DOWN"


def test_frida_click_up_still_sent_after_cancel(frida_env):
    """需求 6：DOWN 成功後才取消 → UP 仍必須送出。"""
    cancel = threading.Event()
    frida_env["user32"].on_send = lambda msg: cancel.set() if msg == _BG.WM_LBUTTONDOWN else None

    assert _FR.click(1, 10, 20, "left", 0, cancel) is True
    assert _BG.WM_LBUTTONDOWN in frida_env["user32"].sent
    assert _BG.WM_LBUTTONUP in frida_env["user32"].sent, "DOWN 之後必須送出 UP"


# ══════════════════════════════════════════════════════════════════════
# 7-8. Frida hold key：cancel 傳遞
# ══════════════════════════════════════════════════════════════════════


def test_frida_hold_passes_cancel_to_down_path(monkeypatch):
    """需求 7：send_hold_key 必須把 cancel 傳進 frida key() 的 DOWN 路徑。"""
    seen: list = []

    class _Recorder:
        def key(self, hwnd, vk, down, cancel=None):
            seen.append((down, cancel))
            return True

    prev_method = _BG.get_method()
    monkeypatch.setattr(_BG, "_frida", lambda: _Recorder())
    _BG.set_method("frida")
    try:
        cancel = threading.Event()
        _BG.send_hold_key(1, "a", 10, cancel)
    finally:
        _BG.set_method(prev_method)

    assert seen, "hold 必須呼叫 frida key()"
    assert seen[0][0] is True, "第一個呼叫必須是 DOWN"
    assert seen[0][1] is cancel, "DOWN 路徑必須收到同一個 cancel 物件"


def test_frida_hold_cancelled_down_sends_no_down(monkeypatch):
    """需求 7：DOWN 前已取消 → 不得送出按鍵（frida key() 自行攔下）。"""
    seen: list = []

    class _Recorder:
        def key(self, hwnd, vk, down, cancel=None):
            seen.append((down, cancel))
            if down and cancel is not None and cancel.is_set():
                return False
            return True

    prev_method = _BG.get_method()
    monkeypatch.setattr(_BG, "_frida", lambda: _Recorder())
    _BG.set_method("frida")
    try:
        cancel = threading.Event()
        cancel.set()
        assert _BG.send_hold_key(1, "a", 10, cancel) is False
    finally:
        _BG.set_method(prev_method)

    assert not any(down for down, _c in seen), "已取消時不得送出 DOWN"


def test_frida_hold_up_attempted_after_cancel(monkeypatch):
    """需求 8：DOWN 成功後取消 → 仍必須嘗試 UP（finally 不得被閘阻擋）。"""
    seen: list = []
    cancel = threading.Event()

    class _Recorder:
        def key(self, hwnd, vk, down, cancel=None):
            seen.append(down)
            if down:
                cancel.set()  # DOWN 成功後立刻收到 Stop
            return True

    prev_method = _BG.get_method()
    monkeypatch.setattr(_BG, "_frida", lambda: _Recorder())
    _BG.set_method("frida")
    try:
        _BG.send_hold_key(1, "a", 5000, cancel)
    finally:
        _BG.set_method(prev_method)

    assert seen[-1] is False, "取消後仍必須嘗試 key(up)"
    assert seen.count(False) == 1, "key(up) 不得重複"


# ══════════════════════════════════════════════════════════════════════
# 9-10. _key_postmessage：PostMessageW BOOL 檢查
# ══════════════════════════════════════════════════════════════════════


def test_key_postmessage_down_failure_reports_error(frida_env):
    """需求 9：DOWN 的 PostMessageW 失敗 → 回報錯誤，不得回報成功。"""
    frida_env["user32"].fail = {_BG.WM_KEYDOWN}

    assert _BG._key_postmessage(1, 0x41, True) is False
    assert _BG.last_error(), "DOWN 失敗必須留下錯誤資訊"


def test_key_postmessage_up_failure_reports_error(frida_env):
    """需求 10：UP 的 PostMessageW 失敗 → 回報錯誤且不得回報成功。"""
    frida_env["user32"].fail = {_BG.WM_KEYUP}

    assert _BG._key_postmessage(1, 0x41, False) is False
    assert _BG.last_error(), "UP 失敗必須留下錯誤資訊"


def test_key_postmessage_success_reports_no_error(frida_env):
    """對照組：成功時不得留下錯誤資訊、必須回報成功。"""
    assert _BG._key_postmessage(1, 0x41, True) is True
    assert _BG._key_postmessage(1, 0x41, False) is True
    assert not _BG.last_error(), "成功時不應留下錯誤資訊"


# ══════════════════════════════════════════════════════════════════════
# 11-12. 舊行為相容
# ══════════════════════════════════════════════════════════════════════


def test_cancel_none_keeps_legacy_behaviour(frida_env):
    """需求 11：cancel=None 時行為與舊版一致（照常 DOWN / UP / click）。"""
    assert _FR.key(1, 0x41, True) is True
    assert _FR.key(1, 0x41, False) is True
    assert _rpc_keys(frida_env) == [("rpc_key", 0x41, 1), ("rpc_key", 0x41, 0)]

    frida_env["user32"].sent.clear()
    assert _FR.click(1, 10, 20, "left", 0) is True
    assert _BG.WM_LBUTTONDOWN in frida_env["user32"].sent
    assert _BG.WM_LBUTTONUP in frida_env["user32"].sent


def test_positional_callers_still_work(frida_env):
    """需求 12：舊的 positional 呼叫端不受新增參數影響。"""
    assert _FR.key(1, 0x41, True) is True
    assert _FR.click(1, 10, 20, "left", 0) is True
    assert _BG.click(1, 10, 20, "left", 0) is True
    assert _BG.send_key(1, "a") is True
    assert _BG.scroll(1, 0, 0, 1) is True
    assert _BG.send_hold_key(1, "a", 10) is True
    assert _BG.drag(1, 10, 20, 30, 40, "left") is True

    kinds = [m for m in frida_env["user32"].sent]
    assert _BG.WM_KEYDOWN in kinds
    assert _BG.WM_KEYUP in kinds
    assert _BG.WM_LBUTTONDOWN in kinds
    assert _BG.WM_LBUTTONUP in kinds
