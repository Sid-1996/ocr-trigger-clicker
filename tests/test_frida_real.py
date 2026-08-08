"""真實 frida 整合測試（無 frida 環境自動 skip）。

防止 frida 版本回歸（例：17.x 的 Module.getExportByName 直接拋
TypeError: not a function，導致 recv 永不註冊而 ack 逾時）。以無害的子
python 行程為注入目標，驗證 ready/ack 握手與游標 spoof 皆正常。
"""

import subprocess
import sys
import time

import pytest

from _loader import load_sibling

pytest.importorskip("frida")
import frida  # noqa: E402

_fb = load_sibling("frida_bg", "core/18_frida_bg.py")


@pytest.fixture()
def child_pid():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    time.sleep(0.8)
    try:
        yield proc.pid
    finally:
        proc.kill()


def _wait_for(predicate, msgs, timeout=3.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if predicate(msgs):
            return True
        time.sleep(0.05)
    return False


def test_handshake_ready_and_ack(child_pid):
    sess = frida.attach(child_pid)
    sc = sess.create_script(_fb.build_hook_script())
    got = []
    sc.on("message", lambda m, d: got.append(m))
    sc.load()
    assert _wait_for(lambda msgs: any(m.get("payload") == "ready" for m in msgs), got), (
        f"ready 未收到: {got}"
    )
    sc.post({"type": "update", "sx": 1, "sy": 2, "cx": 3, "cy": 4})
    assert _wait_for(lambda msgs: any(m.get("payload") == "ack" for m in msgs), got), (
        f"ack 未收到: {got}"
    )
    errors = [m for m in got if m.get("type") == "error"]
    assert not errors, f"script 錯誤: {errors}"
    sc.unload()
    sess.detach()


def test_cursor_spoof_works(child_pid):
    js = r"""
'use strict';
var pos = { sx: 0, sy: 0 };
var user32 = Process.findModuleByName('user32.dll');
var addr = user32.findExportByName('GetCursorPos');
Interceptor.attach(addr, {
  onEnter: function (args) { this.pt = args[0]; },
  onLeave: function (retval) {
    if (this.pt === null || this.pt.isNull()) return;
    this.pt.writeS32(pos.sx);
    this.pt.add(4).writeS32(pos.sy);
  }
});
var GetCursorPos = new NativeFunction(addr, 'int', ['pointer']);
recv('update', function (msg) {
  pos = { sx: msg.sx, sy: msg.sy };
  var buf = Memory.alloc(8);
  GetCursorPos(buf);
  send(['spoofed', buf.readS32(), buf.add(4).readS32()]);
});
"""
    sess = frida.attach(child_pid)
    sc = sess.create_script(js)
    got = []
    sc.on("message", lambda m, d: got.append(m))
    sc.load()
    sc.post({"type": "update", "sx": 777, "sy": 888})
    ok = _wait_for(
        lambda msgs: any(
            isinstance(m.get("payload"), list) and m["payload"][0] == "spoofed" for m in msgs
        ),
        got,
    )
    assert ok, f"spoof 回報未收到: {got}"
    spoofed = next(
        m["payload"]
        for m in got
        if isinstance(m.get("payload"), list) and m["payload"][0] == "spoofed"
    )
    assert spoofed == ["spoofed", 777, 888], f"spoof 座標錯誤: {got}"
    sc.unload()
    sess.detach()
