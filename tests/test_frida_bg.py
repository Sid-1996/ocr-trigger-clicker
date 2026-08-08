import sys

from _loader import load_sibling

_fb = load_sibling("frida_bg", "core/18_frida_bg.py")


def _make_fake_frida():
    class FakeExports:
        def __init__(self, updates):
            self._updates = updates

        def update(self, sx, sy, cx, cy):
            self._updates.append((sx, sy, cx, cy))
            return 1

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
        "findExportByName",
        "send('ready')",
        "rpc.exports",
        "update: function",
    ):
        assert needle in js
    assert "Module.getExportByName" not in js
    assert "recv('update'" not in js, "one-shot recv 只會成功一次，不得回歸"


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
