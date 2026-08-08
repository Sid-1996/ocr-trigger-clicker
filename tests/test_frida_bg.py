import sys

from _loader import load_sibling

_fb = load_sibling("frida_bg", "core/18_frida_bg.py")


def _make_fake_frida():
    class FakeScript:
        def __init__(self):
            self.loaded = False
            self.posted = []
            self.unloaded = False
            self._handler = None

        def on(self, name, cb):
            self._handler = cb

        def load(self):
            self.loaded = True

        def post(self, msg):
            self.posted.append(msg)
            self._handler({"type": "send", "payload": "ack"}, None)

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
    for needle in ("GetCursorPos", "ScreenToClient", "recv('update'", "send('ack')"):
        assert needle in js


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
    assert fake.script.posted
    up = fake.script.posted[0]
    assert up["cx"] == 30 and up["cy"] == 40
    assert "sx" in up and "sy" in up
    assert 0x0201 in captured_msgs and 0x0202 in captured_msgs

    _fb.detach()
    assert fake.script.unloaded
