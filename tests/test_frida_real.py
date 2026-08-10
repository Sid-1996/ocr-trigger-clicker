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


_READ_FOCUS_JS = r"""
'use strict';
var user32 = Process.findModuleByName('user32.dll');
var getFg = new NativeFunction(user32.findExportByName('GetForegroundWindow'), 'pointer', []);
var getActive = new NativeFunction(user32.findExportByName('GetActiveWindow'), 'pointer', []);
var getFocus = new NativeFunction(user32.findExportByName('GetFocus'), 'pointer', []);
rpc.exports = {
  readFg: function () { return getFg(); },
  readActive: function () { return getActive(); },
  readFocus: function () { return getFocus(); }
};
"""

# 子行程：建立 message-only 視窗並用自己的 WndProc 記錄收到的訊息；讀 stdin 指令
#  - send:<msgcode>:<wparam>:<idx>  → post 訊息並 pump（GetMessage+DispatchMessage）
# verify keep-active 是否把失焦訊息擋在「WndProc 之前」
_CHILD_CODE = r"""
import ctypes
import sys
from ctypes import wintypes

u = ctypes.windll.user32
HWND = ctypes.c_void_p
FOCUS_LOSS_MSGS = [0x0008, 0x0006]  # WM_KILLFOCUS / WM_ACTIVATE
# 明確 argtypes/restype：預設 c_int 會把 64-bit HWND/參數截斷
u.CreateWindowExW.argtypes = [
    ctypes.c_uint32, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_uint32,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    HWND, HWND, HWND, ctypes.c_void_p,
]
u.CreateWindowExW.restype = HWND
u.PostMessageW.argtypes = [HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
u.PostMessageW.restype = ctypes.c_bool
u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
u.PeekMessageW.restype = ctypes.c_bool
u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
u.DispatchMessageW.restype = ctypes.c_int64
u.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]
u.GetWindowLongPtrW.restype = ctypes.c_int64
u.SetWindowLongPtrW.argtypes = [HWND, ctypes.c_int, ctypes.c_int64]
u.SetWindowLongPtrW.restype = ctypes.c_int64

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_int64, HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint)
delivered = []

@WNDPROC
def wndproc(h, m, w, l):
    if m in FOCUS_LOSS_MSGS:
        delivered.append(m)
    return 0

hwnd = int(u.CreateWindowExW(0, "STATIC", "child", 0, 0, 0, 0, 0, HWND(-3).value, None, 0, None))
assert hwnd, f"CreateWindowExW 失敗: {ctypes.WinError(ctypes.get_last_error())}"
old = u.GetWindowLongPtrW(hwnd, -4)
assert old != 0, "GetWindowLongPtrW 取不到原 WndProc"
u.SetWindowLongPtrW(hwnd, -4, ctypes.cast(wndproc, ctypes.c_void_p).value)
print(f"READY {hwnd}")
sys.stdout.flush()

delivered.clear()
counter = 0
for line in sys.stdin:
    line = line.strip()
    if line == "quit":
        break
    if line.startswith("send:"):
        _, msgcode, wparam, idx = line.split(":")
        msgcode, wparam, idx = int(msgcode), int(wparam), int(idx)
        u.PostMessageW(hwnd, msgcode, wparam, 0)
        m = wintypes.MSG()
        while u.PeekMessageW(ctypes.byref(m), hwnd, 0, 0, 1):
            u.DispatchMessageW(ctypes.byref(m))
        print(f"RESULT {idx} {'NONE' if (msgcode not in delivered) else msgcode}")
        sys.stdout.flush()
        delivered.clear()
    elif line.startswith("focus"):
        print(f"FOCUS {hex(u.GetForegroundWindow())} {hex(u.GetActiveWindow())} {hex(u.GetFocus())}")
        sys.stdout.flush()
"""


def _spawn_child():
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD_CODE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    line = proc.stdout.readline().strip()
    assert line.startswith("READY "), f"子行程未回報 hwnd: {line!r}"
    return proc, int(line.split()[1])


def _send(proc, line):
    proc.stdin.write(line + "\n")
    proc.stdin.flush()


def _readline(proc):
    line = proc.stdout.readline().strip()
    assert line, "子行程 stdout 提早關閉（可能已崩潰）"
    return line


def test_keep_active_focus_persistent_no_update():
    # keep-active：setKeepActive(1, hwnd) 後【不需 update()】，GetForegroundWindow/
    # GetActiveWindow/GetFocus 立即且持續回傳遊戲 hwnd（超過 spoof grace 也不消失）；
    # setKeepActive(0) 後恢復 pass-through 真實視窗
    proc, child_hwnd = _spawn_child()
    try:
        sess = frida.attach(proc.pid)
        helper = sess.create_script(_READ_FOCUS_JS)
        helper.load()

        _fb.detach()
        assert _fb.ensure_attached(child_hwnd) is True
        assert _fb.keep_active(child_hwnd, True) is True

        expect = hex(child_hwnd)
        assert helper.exports.readFg() == expect, (
            "keep-active 下 GetForegroundWindow 應回傳遊戲 hwnd"
        )
        assert helper.exports.readActive() == expect, (
            "keep-active 下 GetActiveWindow 應回傳遊戲 hwnd"
        )
        assert helper.exports.readFocus() == expect, "keep-active 下 GetFocus 應回傳遊戲 hwnd"

        time.sleep(_fb._SPOOF_GRACE_MS / 1000 + 0.5)
        assert helper.exports.readFocus() == expect, "keep-active 不應隨 spoof grace 到期而還原"

        assert _fb.keep_active(child_hwnd, False) is True
        time.sleep(0.1)
        after = (
            helper.exports.readFg(),
            helper.exports.readActive(),
            helper.exports.readFocus(),
        )
        assert all(v != expect for v in after), f"關閉 keep-active 後應恢復真實焦點: {after}"

        helper.unload()
        sess.detach()
    finally:
        _send(proc, "quit")
        proc.kill()
        _fb.detach()


def test_keep_active_filters_focus_loss_messages():
    # WndProc subclass 實效：keep-active 開啟時，WM_KILLFOCUS / WM_ACTIVATE(WA_INACTIVE)
    # 不會送達遊戲的 WndProc（子行程以自訂 WndProc 記錄送達與否）；關閉後恢復送達。
    proc, child_hwnd = _spawn_child()
    try:
        _fb.detach()
        assert _fb.ensure_attached(child_hwnd) is True

        _send(proc, "send:8:0:1")  # WM_KILLFOCUS
        assert _readline(proc) == "RESULT 1 8", "off: WM_KILLFOCUS 應送達 WndProc"
        _send(proc, "send:6:0:2")  # WM_ACTIVATE(WA_INACTIVE)
        assert _readline(proc) == "RESULT 2 6", "off: WM_ACTIVATE(WA_INACTIVE) 應送達 WndProc"

        assert _fb.keep_active(child_hwnd, True) is True
        _send(proc, "send:8:0:3")
        assert _readline(proc) == "RESULT 3 NONE", "on: WM_KILLFOCUS 不應送達 WndProc"
        _send(proc, "send:6:0:4")
        assert _readline(proc) == "RESULT 4 NONE", "on: WM_ACTIVATE(WA_INACTIVE) 不應送達 WndProc"
        _send(proc, "send:6:1:5")  # WM_ACTIVATE(WA_ACTIVE) 必須放行
        assert _readline(proc) == "RESULT 5 6", "on: WM_ACTIVATE(WA_ACTIVE) 應正常送達"

        assert _fb.keep_active(child_hwnd, False) is True
        _send(proc, "send:8:0:6")
        assert _readline(proc) == "RESULT 6 8", "off 後應恢復送達 WM_KILLFOCUS"
    finally:
        _send(proc, "quit")
        proc.kill()
        _fb.detach()


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


def test_focus_spoof_works(child_pid):
    # 焦點假造：update()/key(down) 觸發 spoof 後，GetForegroundWindow/GetActiveWindow/
    # GetFocus 回傳 arm(hwnd) 指定的遊戲視窗；寬限期到期自動還原，不再回傳假 hwnd
    sess = frida.attach(child_pid)
    prod = sess.create_script(_fb.build_hook_script())
    prod.load()

    helper_js = r"""
'use strict';
var user32 = Process.findModuleByName('user32.dll');
var getFg = new NativeFunction(user32.findExportByName('GetForegroundWindow'), 'pointer', []);
var getActive = new NativeFunction(user32.findExportByName('GetActiveWindow'), 'pointer', []);
var getFocus = new NativeFunction(user32.findExportByName('GetFocus'), 'pointer', []);
rpc.exports = {
  readFg: function () { return getFg(); },
  readActive: function () { return getActive(); },
  readFocus: function () { return getFocus(); }
};
"""
    helper = sess.create_script(helper_js)
    helper.load()

    assert prod.exports.arm(0x12345) == 1
    assert prod.exports.update(100, 100, 100, 100) == 1
    assert helper.exports.readFg() == hex(0x12345), "spoof 時 GetForegroundWindow 應回傳遊戲 hwnd"
    assert helper.exports.readActive() == hex(0x12345), "spoof 時 GetActiveWindow 應回傳遊戲 hwnd"
    assert helper.exports.readFocus() == hex(0x12345), "spoof 時 GetFocus 應回傳遊戲 hwnd"

    time.sleep(_fb._SPOOF_GRACE_MS / 1000 + 0.5)
    after = (helper.exports.readFg(), helper.exports.readActive(), helper.exports.readFocus())
    assert all(v != hex(0x12345) for v in after), f"寬限期後不應再回傳 spoof hwnd: {after}"

    prod.unload()
    helper.unload()
    sess.detach()


def test_set_cursor_pos_blocked_while_spoofing(child_pid):
    # 鼠標 capture：spoof 期間遊戲的 SetCursorPos 被『吃掉』——假裝成功回傳 TRUE、
    # 實體游標不動（host 端讀取驗證），且假座標追上遊戲想設定的位置
    import ctypes
    from ctypes import wintypes

    sess = frida.attach(child_pid)
    prod = sess.create_script(_fb.build_hook_script())
    prod.load()

    helper_js = r"""
'use strict';
var user32 = Process.findModuleByName('user32.dll');
var setCursor = new NativeFunction(user32.findExportByName('SetCursorPos'), 'int', ['int', 'int']);
var getCursor = new NativeFunction(user32.findExportByName('GetCursorPos'), 'int', ['pointer']);
rpc.exports = {
  set: function (x, y) { return setCursor(x, y); },
  read: function () {
    var b = Memory.alloc(8);
    getCursor(b);
    return [b.readS32(), b.add(4).readS32()];
  }
};
"""
    helper = sess.create_script(helper_js)
    helper.load()

    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    before = (pt.x, pt.y)

    assert prod.exports.arm(0x12345) == 1
    assert prod.exports.update(777, 888, 777, 888) == 1
    assert helper.exports.set(10, 10) == 1, "spoof 時 SetCursorPos 應假裝成功"
    pt2 = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt2))
    # 物理游標不經 hook（host 端讀取）。replace 攔截下真不得移動；留 5px 容差
    # 吸收少數環境的硬體 jitter，仍能抓到「被移到 (10,10) 附近」式的真實失敗。
    assert abs(pt2.x - pt.x) < 5 and abs(pt2.y - pt.y) < 5, (
        f"spoof 時 SetCursorPos 不得移動實體游標: {before} → {pt2.x},{pt2.y}"
    )
    assert helper.exports.read() == [10, 10], "假座標應追上遊戲想設定的位置"

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
