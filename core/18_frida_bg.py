"""Frida-based background input — zero-flicker clicks for Unity games.

Unity 驗證 WM_LBUTTON 事件時會用 GetCursorPos/ScreenToClient 對照實體游標位置，
純 PostMessage 因實體游標不在目標點而被丟棄。本模組注入目標行程 hook 這兩個 API，
在收到 update 訊息時回傳假座標，讓 Unity 通過驗證 —— 全程游標不動、焦點不搶。

v1 限制：
- 僅保證點擊（click）；鍵盤/滾輪/拖曳仍走 PostMessage（Unity 下可能無效）
- 遊戲若要求視窗聚焦（Application.isFocused）仍無效
- EAC/BattlEye 等防作弊會封鎖 Frida（行程注入可被偵測）
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import threading

_log = logging.getLogger(__name__)
_lock = threading.RLock()  # ensure_attached 內會呼叫 detach()，需可重入

_script = None
_session = None
_pid: int | None = None
_ack = threading.Event()
_last_error = ""


def build_hook_script() -> str:
    """Return the Frida JS hook script (GetCursorPos + ScreenToClient spoof)."""
    return r"""
'use strict';

var pos = { sx: 0, sy: 0, cx: 0, cy: 0 };

function hookSpoof(name, writePos) {
  var addr = Module.getExportByName('user32.dll', name);
  if (addr.isNull()) return;
  Interceptor.attach(addr, {
    onEnter: function (args) { this.pt = args[args.length - 1]; },
    onLeave: function (retval) {
      if (this.pt.isNull()) return;
      this.pt.writeS32(writePos.sx());
      this.pt.add(4).writeS32(writePos.sy());
    }
  });
}

hookSpoof('GetCursorPos', { sx: function () { return pos.sx; }, sy: function () { return pos.sy; } });
hookSpoof('ScreenToClient', { sx: function () { return pos.cx; }, sy: function () { return pos.cy; } });

recv('update', function (msg) {
  pos = { sx: msg.sx, sy: msg.sy, cx: msg.cx, cy: msg.cy };
  send('ack');
});
""".strip()


def _bg():
    from _loader import load_sibling

    return load_sibling("bg_input", "core/16_bg_input.py")


def _hwnd_to_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _set_error(msg: str):
    global _last_error
    _last_error = msg
    if msg:
        _log.error(msg)


def last_error() -> str:
    """Last error message (empty if last operation succeeded)."""
    return _last_error


def _on_message(message, data):
    if (
        isinstance(message, dict)
        and message.get("type") == "send"
        and message.get("payload") == "ack"
    ):
        _ack.set()


def ensure_attached(hwnd: int) -> bool:
    """Attach Frida to the process owning hwnd; re-attach if pid changed."""
    global _script, _session, _pid
    if not hwnd:
        _set_error("Frida: 無效 hwnd")
        return False
    cur_pid = _hwnd_to_pid(hwnd)
    with _lock:
        if _script is not None and _pid == cur_pid:
            return True
        detach()
        try:
            import frida
        except ImportError as e:
            _set_error(f"Frida 未安裝: {e}")
            return False
        try:
            _session = frida.attach(cur_pid)
            _script = _session.create_script(build_hook_script())
            _script.on("message", _on_message)
            _script.load()
            _pid = cur_pid
            _last_error = ""
            _log.info("Frida 已注入 pid=%d (hwnd=%d)", cur_pid, hwnd)
            return True
        except Exception as e:
            detach()
            _set_error(f"Frida 注入失敗 pid={cur_pid}: {e}")
            return False


def click(hwnd: int, x: int, y: int, button: str = "left", hold_ms: int = 0) -> bool:
    """Click at (x, y) client coords via spoofed cursor + PostMessage."""
    if not ensure_attached(hwnd):
        return False
    with _lock:
        if _script is None:
            return False
        try:
            sx, sy = _bg()._client_to_screen(hwnd, x, y)
            _ack.clear()
            _script.post({"type": "update", "sx": sx, "sy": sy, "cx": x, "cy": y})
        except Exception as e:
            _set_error(f"Frida 傳遞座標失敗: {e}")
            return False
        if not _ack.wait(1.0):
            _set_error("Frida 座標同步逾時 (ack)")
            return False
    return _bg()._click_postmessage(hwnd, x, y, button, hold_ms)


def detach() -> None:
    """Detach the injected session and restore the game (idempotent)."""
    global _script, _session, _pid
    with _lock:
        if _script is not None:
            try:
                _script.unload()
            except Exception:
                pass
            _script = None
        if _session is not None:
            try:
                _session.detach()
            except Exception:
                pass
            _session = None
        _pid = None


if __name__ == "__main__":
    print("=== Frida BG Self-Check ===\n")

    js = build_hook_script()
    for needle in ("GetCursorPos", "ScreenToClient", "recv('update'", "send('ack')"):
        assert needle in js, f"hook 腳本缺少: {needle}"
    print("  [OK] hook 腳本內容")

    desktop = ctypes.windll.user32.GetDesktopWindow()
    assert _hwnd_to_pid(desktop) > 0, "桌面視窗 pid 應大於 0"
    assert _hwnd_to_pid(0) == 0
    print("  [OK] _hwnd_to_pid 換算")

    assert ensure_attached(0) is False and last_error()
    print("  [OK] 無效 hwnd 拒絕 attach")

    # 假 frida 流程：驗證 update → ack → PostMessage 順序
    import sys

    class _FakeScript:
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

    class _FakeSession:
        def __init__(self, script):
            self.script = script
            self.detached = False

        def create_script(self, js):
            return self.script

        def detach(self):
            self.detached = True

    class _FakeFrida:
        def __init__(self, script):
            self.script = script
            self.pids = []

        def attach(self, pid):
            self.pids.append(pid)
            return _FakeSession(self.script)

    fake_script = _FakeScript()
    fake_frida = _FakeFrida(fake_script)
    sys.modules["frida"] = fake_frida

    detach()
    assert ensure_attached(desktop) is True
    assert fake_script.loaded and fake_frida.pids == [_hwnd_to_pid(desktop)]
    print("  [OK] 假 frida attach")

    captured = {}
    _orig_pm = ctypes.windll.user32.PostMessageW
    ctypes.windll.user32.PostMessageW = lambda hwnd, msg, wparam, lparam: (
        captured.update(msg=msg, wparam=wparam) or True
    )
    try:
        ok = click(desktop, 10, 20, "left", 0)
        assert ok, "click 應成功"
        assert fake_script.posted, "應送出 update"
        up = fake_script.posted[0]
        assert up["cx"] == 10 and up["cy"] == 20, f"client 座標錯誤: {up}"
        assert "sx" in up and "sy" in up
        assert captured["msg"] == 0x0202, "應送 WM_LBUTTONUP"
    finally:
        ctypes.windll.user32.PostMessageW = _orig_pm
    print("  [OK] click: update(client=10,20) → ack → PostMessage")

    detach()
    assert fake_script.unloaded
    print("  [OK] detach 冪等釋放")

    del sys.modules["frida"]
    print("\n=== All 5 checks passed ===")
