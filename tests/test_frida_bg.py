import sys

from _loader import load_sibling

_fb = load_sibling("frida_bg", "core/18_frida_bg.py")


def _make_fake_frida():
    class FakeExports:
        def __init__(self, updates):
            self._updates = updates
            self.key_calls = []
            self.arm_calls = []
            self.keep_active_calls = []

        def update(self, sx, sy, cx, cy):
            self._updates.append((sx, sy, cx, cy))
            return 1

        def key(self, vk, down):
            self.key_calls.append((vk, down))
            return 1

        def arm(self, hwnd):
            self.arm_calls.append(hwnd)
            return 1

        def setKeepActive(self, on, hwnd):
            self.keep_active_calls.append((on, hwnd))
            return 1 if on else 0

    class FakeScript:
        def __init__(self):
            self.loaded = False
            self.updates = []
            self.unloaded = False
            self._handler = None
            self.exports = FakeExports(self.updates)

        def on(self, name, cb):
            self._handler = cb

        def load(self):
            self.loaded = True
            self._handler({"type": "send", "payload": "ready"}, None)

        def unload(self):
            self.unloaded = True

    class FakeSession:
        def __init__(self, script):
            self.script = script
            self.detached = False

        def create_script(self, js):
            return self.script

        def detach(self):
            self.detached = True

    class FakeFrida:
        def __init__(self, script):
            self.script = script
            self.pids = []

        def attach(self, pid):
            self.pids.append(pid)
            return FakeSession(self.script)

    return FakeFrida(FakeScript())


def test_hook_script_content():
    js = _fb.build_hook_script()
    for needle in (
        "GetCursorPos",
        "ScreenToClient",
        "GetKeyState",
        "GetAsyncKeyState",
        "GetKeyboardState",
        "hookKeyState",
        "findExportByName",
        "send('ready')",
        "rpc.exports",
        "update: function",
        "key: function",
        "getSpoofing",
        "spoofing",
        "setTimeout(disableSpoof",
        "setTimeout(clearKeys",
        "GetForegroundWindow",
        "GetActiveWindow",
        "GetFocus",
        "SetCursorPos",
        "hookFocus",
        "hookSetCursorPos",
        "focusOn",
        "arm: function",
        "keepActive",
        "setKeepActive: function",
        "subclassFilter",
        "restoreFilter",
        "GetWindowLongPtrW",
        "SetWindowLongPtrW",
        "filterOldAddr",
        "WM_KILLFOCUS",
        "WA_INACTIVE",
    ):
        assert needle in js
    assert "Module.getExportByName" not in js
    assert "recv('update'" not in js, "one-shot recv 只會成功一次，不得回歸"
    assert "__SPOOF_MS__" not in js, "spoof 寬限期應注入實際數值"
    assert "__KEY_MS__" not in js, "key 寬限期應注入實際數值"
    assert f"SPOOF_MS = {_fb._SPOOF_GRACE_MS}" in js, "spoof 寬限期應等於 _SPOOF_GRACE_MS"
    assert f"KEY_MS = {_fb._KEY_GRACE_MS}" in js, "key 寬限期應等於 _KEY_GRACE_MS"


def test_ensure_attached_arms_focus_hwnd(monkeypatch):
    fake = _make_fake_frida()
    monkeypatch.setitem(sys.modules, "frida", fake)
    monkeypatch.setattr(_fb, "_hwnd_to_pid", lambda hwnd: 4242)
    _fb.detach()
    assert _fb.ensure_attached(12345) is True
    assert fake.script.exports.arm_calls == [12345], (
        "attach 成功後應把視窗 hwnd 送進 script 供焦點假造"
    )
    _fb.detach()


def test_hwnd_to_pid_invalid():
    assert _fb._hwnd_to_pid(0) == 0


def test_ensure_attached_rejects_zero_hwnd():
    _fb.detach()
    assert _fb.ensure_attached(0) is False
    assert _fb.last_error()


def test_frida_missing_graceful(monkeypatch):
    # sys.modules 條目設 None 使 `import frida` 觸發 ImportError（確定性）
    monkeypatch.setitem(sys.modules, "frida", None)
    _fb.detach()
    assert _fb.ensure_attached(1) is False
    assert _fb.last_error()


def test_ensure_attached_ready_timeout(monkeypatch):
    # frida 17 的 load() 對頂層 JS 錯誤不拋例外 → 靠 ready 心跳偵測注入失敗
    fake = _make_fake_frida()
    monkeypatch.setitem(sys.modules, "frida", fake)
    monkeypatch.setattr(_fb, "_hwnd_to_pid", lambda hwnd: 4242)
    monkeypatch.setattr(_fb._ready, "wait", lambda timeout: False)
    _fb.detach()
    assert _fb.ensure_attached(12345) is False
    assert "ready" in _fb.last_error()


def test_ensure_attached_and_click_flow(monkeypatch):
    fake = _make_fake_frida()
    monkeypatch.setitem(sys.modules, "frida", fake)
    monkeypatch.setattr(_fb, "_hwnd_to_pid", lambda hwnd: 4242)
    _fb.detach()

    assert _fb.ensure_attached(12345) is True
    assert fake.pids == [4242]

    _bg = _fb._bg()
    captured_msgs = []
    monkeypatch.setattr(
        _bg.user32,
        "PostMessageW",
        lambda hwnd, msg, wparam, lparam: captured_msgs.append(msg) or True,
    )

    assert _fb.click(12345, 30, 40) is True
    assert fake.script.updates
    sx, sy, cx, cy = fake.script.updates[0]
    assert cx == 30 and cy == 40
    assert sx >= 0 and sy >= 0
    assert 0x0201 in captured_msgs and 0x0202 in captured_msgs

    _fb.detach()
    assert fake.script.unloaded


def test_click_recovers_after_sync_failure(monkeypatch):
    # 注入死亡時自動 detach + re-attach + 重試一次，不需重開 app
    fake = _make_fake_frida()
    monkeypatch.setitem(sys.modules, "frida", fake)
    monkeypatch.setattr(_fb, "_hwnd_to_pid", lambda hwnd: 4242)
    _fb.detach()
    assert _fb.ensure_attached(12345) is True

    calls = {"n": 0}

    class FailOnceExports:
        def update(self, sx, sy, cx, cy):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("injection dead")
            return 1

    fake.script.exports = FailOnceExports()

    _bg = _fb._bg()
    captured_msgs = []
    monkeypatch.setattr(
        _bg.user32,
        "PostMessageW",
        lambda hwnd, msg, wparam, lparam: captured_msgs.append(msg) or True,
    )

    assert _fb.click(12345, 30, 40) is True
    assert calls["n"] == 2, "第一次失敗後應 re-attach 重試成功"
    assert 0x0201 in captured_msgs and 0x0202 in captured_msgs

    _fb.detach()


def test_key_flow(monkeypatch):
    fake = _make_fake_frida()
    monkeypatch.setitem(sys.modules, "frida", fake)
    monkeypatch.setattr(_fb, "_hwnd_to_pid", lambda hwnd: 4242)
    _fb.detach()
    assert _fb.ensure_attached(12345) is True

    _bg = _fb._bg()
    captured = []
    monkeypatch.setattr(
        _bg.user32,
        "PostMessageW",
        lambda hwnd, msg, wparam, lparam: captured.append((msg, wparam, lparam)) or True,
    )

    assert _fb.key(12345, 0x41, True) is True
    assert _fb.key(12345, 0x41, False) is True
    assert fake.script.exports.key_calls == [(0x41, 1), (0x41, 0)]
    msgs = [m for m, _, _ in captured]
    assert 0x0100 in msgs and 0x0101 in msgs, f"應送 WM_KEYDOWN/UP: {msgs}"
    assert 0x0102 in msgs, f"字母按下應補送 WM_CHAR: {msgs}"

    _fb.detach()
    assert fake.script.unloaded


def test_key_recovers_after_sync_failure(monkeypatch):
    # 注入死亡時自動 detach + re-attach + 重試一次（與 click 同模式）
    fake = _make_fake_frida()
    monkeypatch.setitem(sys.modules, "frida", fake)
    monkeypatch.setattr(_fb, "_hwnd_to_pid", lambda hwnd: 4242)
    _fb.detach()
    assert _fb.ensure_attached(12345) is True

    calls = {"n": 0}

    class FailOnceExports:
        def update(self, sx, sy, cx, cy):
            return 1

        def key(self, vk, down):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("injection dead")
            return 1

    fake.script.exports = FailOnceExports()

    _bg = _fb._bg()
    captured = []
    monkeypatch.setattr(
        _bg.user32,
        "PostMessageW",
        lambda hwnd, msg, wparam, lparam: captured.append(msg) or True,
    )

    assert _fb.key(12345, 0x41, True) is True
    assert calls["n"] == 2, "第一次失敗後應 re-attach 重試成功"
    assert 0x0100 in captured

    _fb.detach()


def test_ensure_attached_reattaches_dead_session(monkeypatch):
    # session 死亡（is_detached=True）時快取不得直接回傳 True，需重新 attach
    fake = _make_fake_frida()
    monkeypatch.setitem(sys.modules, "frida", fake)
    monkeypatch.setattr(_fb, "_hwnd_to_pid", lambda hwnd: 4242)
    _fb.detach()
    assert _fb.ensure_attached(12345) is True
    assert len(fake.pids) == 1

    monkeypatch.setattr(_fb, "_session_alive", lambda session: False)
    assert _fb.ensure_attached(12345) is True
    assert len(fake.pids) == 2, "session 死亡時應重新 attach"


def test_keep_active_wrapper(monkeypatch):
    # keep_active：開 → attach + setKeepActive(1, hwnd)；關 → setKeepActive(0)；
    # 未 attach 時 off 為 no-op（不需注入也保證『關閉』語意）
    fake = _make_fake_frida()
    monkeypatch.setitem(sys.modules, "frida", fake)
    monkeypatch.setattr(_fb, "_hwnd_to_pid", lambda hwnd: 4242)
    _fb.detach()

    assert _fb.keep_active(12345, False) is True
    assert not fake.pids, "off 且未注入時不應 attach"
    assert fake.script.exports.keep_active_calls == []

    assert _fb.keep_active(12345, True) is True
    assert fake.pids == [4242], "on 應先 attach 再推送 rpc"
    assert fake.script.exports.keep_active_calls == [(1, 12345)]

    assert _fb.keep_active(0, True) is False, "無效 hwnd 的 keep_active(True) 應失敗"
    assert fake.script.exports.keep_active_calls == [(1, 12345)], "失敗不應送 rpc"

    assert _fb.keep_active(12345, False) is True
    assert fake.script.exports.keep_active_calls[-1] == (0, 0), "關閉應推送 setKeepActive(0, 0)"

    _fb.detach()
    assert fake.script.unloaded
