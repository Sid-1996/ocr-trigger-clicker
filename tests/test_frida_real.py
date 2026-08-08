"""真實 frida 整合測試（無 frida 環境自動 skip）。

防止 frida 版本回歸。以無害的子 python 行程為注入目標，驗證
ready 握手、rpc.exports 可重複同步呼叫（one-shot recv 的回歸守門員），
以及游標 spoof 皆正常。
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


def test_handshake_ready_and_rpc_repeatable(child_pid):
    sess = frida.attach(child_pid)
    sc = sess.create_script(_fb.build_hook_script())
    got = []
    sc.on("message", lambda m, d: got.append(m))
    sc.load()
    assert _wait_for(lambda msgs: any(m.get("payload") == "ready" for m in msgs), got), (
        f"ready 未收到: {got}"
    )
    # one-shot recv 的根因回歸：recv 只會成功一次，rpc.exports 必須可重複呼叫
    for i in range(1, 11):
        ret = sc.exports.update(1, 2, 3, 4)
        assert ret == 1, f"第 {i} 次 update 回傳 {ret!r}"
    errors = [m for m in got if m.get("type") == "error"]
    assert not errors, f"script 錯誤: {errors}"
    sc.unload()
    sess.detach()


def test_spoof_auto_restores(child_pid):
    # 回歸：spoof 是暫時性，_SPOOF_GRACE_MS 後自動還原 pass-through 真實游標，
    # 不會把使用者滑鼠永久卡在 spoof 座標
    import ctypes
    from ctypes import wintypes

    sess = frida.attach(child_pid)
    prod = sess.create_script(_fb.build_hook_script())
    prod.load()

    # 輔助 script：呼叫被 hook 的 GetCursorPos（會經過生產腳本的 interceptor）
    helper_js = r"""
'use strict';
var user32 = Process.findModuleByName('user32.dll');
var GetCursorPos = new NativeFunction(user32.findExportByName('GetCursorPos'), 'int', ['pointer']);
rpc.exports = {
  readCursor: function () {
    var buf = Memory.alloc(8);
    GetCursorPos(buf);
    return [buf.readS32(), buf.add(4).readS32()];
  }
};
"""
    helper = sess.create_script(helper_js)
    helper.load()

    assert prod.exports.update(777, 888, 100, 100) == 1
    assert prod.exports.getSpoofing() is True
    assert tuple(helper.exports.readCursor()) == (777, 888), "spoof 啟用時應回傳假座標"

    time.sleep(_fb._SPOOF_GRACE_MS / 1000 + 0.5)
    assert prod.exports.getSpoofing() is False, "寬限期後應自動還原"

    restored = tuple(helper.exports.readCursor())
    assert restored != (777, 888), "還原後不應再回傳 spoof 座標"
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    assert restored == (pt.x, pt.y), f"還原後應回傳真實游標 {pt.x},{pt.y}，得 {restored}"

    prod.unload()
    helper.unload()
    sess.detach()


def test_key_spoof_works(child_pid):
    # 鍵盤 spoof：key(vk, down) 時 GetKeyState/GetAsyncKeyState 高 bit 與
    # GetKeyboardState bit 0x80 被覆寫，只影響目標 vk；up 後還原
    sess = frida.attach(child_pid)
    prod = sess.create_script(_fb.build_hook_script())
    prod.load()

    helper_js = r"""
'use strict';
var user32 = Process.findModuleByName('user32.dll');
// return type 用 'int'（frida NativeFunction 不支援 'short'）；低 16 位元即 SHORT 值
var getAsync = new NativeFunction(user32.findExportByName('GetAsyncKeyState'), 'int', ['int']);
var getState = new NativeFunction(user32.findExportByName('GetKeyState'), 'int', ['int']);
var getKeyboard = new NativeFunction(user32.findExportByName('GetKeyboardState'), 'int', ['pointer']);
rpc.exports = {
  readKey: function (vk) { return getAsync(vk); },
  readGetKeyState: function (vk) { return getState(vk); },
  readKeyboard: function () {
    var buf = Memory.alloc(256);
    getKeyboard(buf);
    var out = [];
    for (var i = 0; i < 256; i++) out.push(buf.add(i).readU8());
    return out;
  }
};
"""
    helper = sess.create_script(helper_js)
    helper.load()

    VK_A, VK_B = 0x41, 0x42
    assert helper.exports.readKey(VK_A) & 0x8000 == 0
    assert helper.exports.readGetKeyState(VK_A) & 0x8000 == 0

    assert prod.exports.key(VK_A, 1) == 1
    assert helper.exports.readKey(VK_A) & 0x8000, "down: GetAsyncKeyState 高 bit 應設"
    assert helper.exports.readGetKeyState(VK_A) & 0x8000, "down: GetKeyState 高 bit 應設"
    assert helper.exports.readKeyboard()[VK_A] & 0x80, "down: GetKeyboardState bit 0x80 應設"
    # 無關按鍵不受影響
    assert helper.exports.readKey(VK_B) & 0x8000 == 0
    assert helper.exports.readKeyboard()[VK_B] & 0x80 == 0

    assert prod.exports.key(VK_A, 0) == 1
    assert helper.exports.readKey(VK_A) & 0x8000 == 0, "up: GetAsyncKeyState 應還原"
    assert helper.exports.readKeyboard()[VK_A] & 0x80 == 0, "up: GetKeyboardState 應還原"

    prod.unload()
    helper.unload()
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
