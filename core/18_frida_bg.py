"""Frida-based background input — zero-flicker clicks for Unity games.

Unity 驗證 WM_LBUTTON 事件時會用 GetCursorPos/ScreenToClient 對照實體游標位置，
純 PostMessage 因實體游標不在目標點而被丟棄。本模組注入目標行程 hook 這兩個 API，
在收到 update 訊息時回傳假座標，讓 Unity 通過驗證 —— 全程游標不動、焦點不搶。

鍵盤（key）已同步支援：與點擊同架構——hook GetKeyState / GetAsyncKeyState /
GetKeyboardState 假造按鍵狀態（僅覆寫注入中的 vk，其餘 pass-through），再
PostMessage 送 WM_KEYDOWN/UP，讓 Unity 無論走訊息佇列或 state-polling 都收得到。

v1 限制：
- 僅保證點擊（click）與鍵盤（key）；滾輪/拖曳仍走 PostMessage（Unity 下可能無效）
- 遊戲若要求視窗聚焦（Application.isFocused）仍無效
- EAC/BattlEye 等防作弊會封鎖 Frida（行程注入可被偵測）

握手：rpc.exports（同步、無 ack round-trip）。frida 的 recv() 每次註冊只接收
「下一個」訊息（one-shot），頂層註冊一次只讓第一次點擊成功，之後全 ack 逾時；
rpc.exports 可重複呼叫。對 ack 逾時/呼叫失敗會自動 detach + re-attach 重試一次，
避免注入死亡後需重開 app 才恢復。

spoof 是暫時性的：update 設定假座標後經 _SPOOF_GRACE_MS 自動還原（pass-through，
hook 不再覆寫，遊戲回傳真實游標），避免 frida 點完後把使用者真實滑鼠操作永遠
卡在最後一次 spoof 座標。
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
_ready = threading.Event()
_script_error = ""
_last_error = ""

_ATTACH_READY_TIMEOUT = 3.0  # load() 在 frida 17 對頂層 JS 錯誤不拋例外，靠 ready 心跳偵測
_SPOOF_GRACE_MS = 400  # spoof 有效期間；太短點擊可能漏註冊，太長卡使用者滑鼠
_KEY_GRACE_MS = 10000  # key spoof 保險寬限期；up 未送達時自動清除，避免遊戲內按鍵卡住


def build_hook_script() -> str:
    """Return the Frida JS hook script (GetCursorPos + ScreenToClient spoof).

    ponytail: 握手用 rpc.exports.update（同步、可重複呼叫）取代 recv/send('ack')
    —— frida 的 recv() 是 one-shot，頂層註冊一次只會收到第一次 update，之後每次
    點擊都 ack 逾時（「成功幾次後永久失敗」的根因）。
    用 Process.findModuleByName().findExportByName()，不用 Module.getExportByName
    —— 後者在 frida 17.x (QJS) 會直接拋 TypeError: not a function，頂層 JS 掛掉
    導致握手永不回應。

    spoof 自動還原：onLeave 只在 spoofing 開啟時覆寫游標輸出，update 設定後
    經 __SPOOF_MS__ ms 自動關閉（pass-through 回傳真實游標），讓使用者後續
    手動滑鼠操作回到真實位置。

    鍵盤（key）：hookKeyState 覆寫 GetKeyState / GetAsyncKeyState（scalar，高 bit
    0x8000 = 按下）與 GetKeyboardState（256-byte 陣列，bit 0x80 = 按下），只在
    keys[vk] 為 down 時覆寫該按鍵，其餘 pass-through——不影響使用者物理鍵盤。
    rpc.exports.key(vk, down) 設定/清除，down 時 arm __KEY_MS__ 保險 timer。

    診斷證實（diag_frida_keyboard）：BrownDust II（Unity 新 Input System）讀鍵盤
    走 GetRawInputBuffer（buffered raw input）——診斷 10s 內 101 次呼叫、WM_INPUT
    68 次，且 GetKeyState 只查 6 個修飾鍵。PostMessage 的 WM_KEYDOWN 不會產生
    WM_INPUT，進不了 raw input 佇列，故被遊戲忽略（Phase 1 實測無效的根因）。

    因此 Phase 3：hook GetRawInputBuffer，在遊戲每次 buffered read 時把合成的
    RAWKEYBOARD 事件插入 buffer 開頭（合成事件先於真實事件，Unity 以 dwSize 遍歷
    所有結構）。rawDevice 取真實 keyboard hDevice：優先複製真實事件 header 的
    hDevice，其次用 GetRawInputDeviceList 列舉 keyboard。rpc.exports.key 同時 push
    到 pendingRaw 佇列（與 keys 共用 KEY_MS 保險 timer）。
    """
    return (
        r"""
'use strict';

var pos = { sx: 0, sy: 0, cx: 0, cy: 0 };
var spoofing = false;
var spoofTimer = null;
var SPOOF_MS = __SPOOF_MS__;
var keys = {};
var pendingRaw = [];
var keyTimer = null;
var KEY_MS = __KEY_MS__;
var user32 = Process.findModuleByName('user32.dll');

var RIM_TYPEKEYBOARD = 1;
var RI_KEY_MAKE = 0;
var RI_KEY_BREAK = 1;
var RI_KEY_E0 = 2;
var WM_KEYDOWN = 0x0100;
var WM_KEYUP = 0x0101;
var PS = Process.pointerSize;
// 需 extended-key（scan code 有 0xE0 前綴）的按鍵，與 16_bg_input._EXTENDED_VK 一致
var EXTENDED_VK = [0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x6F, 0x90];

// 真實 keyboard hDevice（緩存）。Unity 以 hDevice 對應輸入設備，0 可能被忽略。
var rawDevice = ptr(0);

function disableSpoof() {
  spoofing = false;
}

function clearKeys() {
  keys = {};
  pendingRaw = [];
  keyTimer = null;
}

function hookSpoof(name, ptIndex, writePos) {
  var addr = user32.findExportByName(name);
  if (addr === null) return;
  Interceptor.attach(addr, {
    onEnter: function (args) { this.pt = args[ptIndex]; },
    onLeave: function (retval) {
      if (!this.pt || this.pt.isNull()) return;
      if (!spoofing) return; // 還原：pass-through，回傳真實游標位置
      this.pt.writeS32(writePos.sx());
      this.pt.add(4).writeS32(writePos.sy());
    }
  });
}

function hookKeyState(name, isArray) {
  var addr = user32.findExportByName(name);
  if (addr === null) return;
  Interceptor.attach(addr, {
    onEnter: function (args) {
      this.vk = args[0].toInt32() & 0xFF;
      this.buf = args[0];
    },
    onLeave: function (retval) {
      if (isArray) {
        // GetKeyboardState: 256-byte 陣列，只覆寫正在注入且為 down 的按鍵
        if (!this.buf || this.buf.isNull()) return;
        for (var vk in keys) {
          if (!keys[vk]) continue;
          var b = this.buf.add(parseInt(vk, 10));
          b.writeU8(b.readU8() | 0x80);
        }
        return;
      }
      if (keys[this.vk]) retval.replace(0x8000);
    }
  });
}

// 用 GetRawInputDeviceList 列舉 keyboard 設備 handle（rawDevice 尚無值時兜底）
function fetchKeyboardDevice() {
  var fn = user32.findExportByName('GetRawInputDeviceList');
  if (fn === null) return ptr(0);
  var gridl = new NativeFunction(fn, 'uint', ['pointer', 'pointer', 'uint']);
  var stride = PS + 4; // RAWINPUTDEVICELIST { HANDLE hDevice; DWORD dwType; }，frida 會對齊
  if (PS === 8) stride = 16;
  var n1 = ptr(0);
  gridl(ptr(0), n1, stride);
  var count = n1.toInt32();
  if (count <= 0) return ptr(0);
  var buf = Memory.alloc(count * stride);
  var n2 = ptr(count);
  gridl(buf, n2, stride);
  for (var i = 0; i < count; i++) {
    var entry = buf.add(i * stride);
    if (entry.add(PS).readU32() === RIM_TYPEKEYBOARD) {
      return entry.readPointer();
    }
  }
  return ptr(0);
}

// 掃描 GetRawInputBuffer 回傳的真實事件，快取 keyboard hDevice
function captureDevice(pData, count) {
  if (!rawDevice.isNull()) return;
  var cursor = pData;
  for (var i = 0; i < count; i++) {
    var type = cursor.readU32();
    var sz = cursor.add(4).readU32();
    if (type === RIM_TYPEKEYBOARD) {
      rawDevice = cursor.add(8).readPointer();
      if (!rawDevice.isNull()) return;
    }
    cursor = cursor.add(sz);
  }
}

function hookRawInputBuffer() {
  var addr = user32.findExportByName('GetRawInputBuffer');
  if (addr === null) return;
  Interceptor.attach(addr, {
    onEnter: function (args) {
      this.pData = args[0];
      this.pcbSize = args[1];
      this.cap = args[1].isNull() ? 0 : args[1].readU32();
    },
    onLeave: function (retval) {
      if (pendingRaw.length === 0) return;
      if (this.pData.isNull() || this.pcbSize.isNull()) return; // 查大小模式，無法注入
      var realCount = retval.toInt32();
      if (realCount < 0) return; // buffer 太小
      captureDevice(this.pData, realCount);
      // RAWINPUT(keyboard) = header(8 + 2*PS) + RAWKEYBOARD(16)
      var hdr = 8 + 2 * PS;
      var one = hdr + 16;
      var synthBytes = pendingRaw.length * one;
      var realBytes = 0;
      var cursor = this.pData;
      for (var i = 0; i < realCount; i++) {
        var sz = cursor.add(4).readU32();
        realBytes += sz;
        cursor = cursor.add(sz);
      }
      if (realBytes + synthBytes > this.cap) return; // 空間不足，等下批
      if (rawDevice.isNull()) rawDevice = fetchKeyboardDevice();
      if (rawDevice.isNull()) return; // 無 keyboard 設備，Unity 會忽略 hDevice=0
      // 真實資料往後搬，合成事件放開頭
      if (realBytes > 0) {
        var memmove = new NativeFunction(Module.findExportByName(null, 'memmove'),
                                         'void', ['pointer', 'pointer', 'pointer']);
        memmove(this.pData.add(synthBytes), this.pData, ptr(realBytes));
      }
      var dst = this.pData;
      for (var j = 0; j < pendingRaw.length; j++) {
        var ev = pendingRaw[j];
        dst.writeU32(RIM_TYPEKEYBOARD);
        dst.add(4).writeU32(one); // dwSize
        dst.add(8).writePointer(rawDevice);
        dst.add(8 + PS).writePointer(ptr(0)); // wParam = RIM_INPUT
        var kb = dst.add(hdr);
        kb.writeU16(ev.scan);
        kb.add(2).writeU16(ev.flags);
        kb.add(2).writeU16(0); // reserved
        kb.add(2).writeU16(ev.vk);
        kb.add(2).writeU32(ev.msg);
        kb.add(4).writeU32(0); // extra
        dst = dst.add(one);
      }
      retval.replace(realCount + pendingRaw.length);
      this.pcbSize.writeU32(realBytes + synthBytes);
      pendingRaw = [];
    }
  });
}

if (user32 === null) {
  send(['fatal', 'user32.dll 未載入']);
} else {
  hookSpoof('GetCursorPos', 0, { sx: function () { return pos.sx; }, sy: function () { return pos.sy; } });
  hookSpoof('ScreenToClient', 1, { sx: function () { return pos.cx; }, sy: function () { return pos.cy; } });
  hookKeyState('GetKeyState', false);
  hookKeyState('GetAsyncKeyState', false);
  hookKeyState('GetKeyboardState', true);
  hookRawInputBuffer();
  rpc.exports = {
    update: function (sx, sy, cx, cy) {
      pos = { sx: sx, sy: sy, cx: cx, cy: cy };
      spoofing = true;
      if (spoofTimer !== null) clearTimeout(spoofTimer);
      spoofTimer = setTimeout(disableSpoof, SPOOF_MS);
      return 1;
    },
    key: function (vk, down) {
      vk = vk & 0xFF;
      if (down) {
        keys[vk] = true;
        if (keyTimer !== null) clearTimeout(keyTimer);
        keyTimer = setTimeout(clearKeys, KEY_MS);
      } else {
        delete keys[vk];
      }
      var scan = ptr(0);
      try {
        var mvk = new NativeFunction(user32.findExportByName('MapVirtualKeyW'), 'uint', ['uint', 'uint']);
        scan = mvk(vk, 0);
      } catch (e) {
        scan = 0;
      }
      var flags = down ? RI_KEY_MAKE : RI_KEY_BREAK;
      if (EXTENDED_VK.indexOf(vk) !== -1) flags |= RI_KEY_E0;
      pendingRaw.push({
        vk: vk,
        scan: scan,
        flags: flags,
        msg: down ? WM_KEYDOWN : WM_KEYUP
      });
      return 1;
    },
    getSpoofing: function () {
      return spoofing;
    }
  };
  send('ready');
}
""".replace("__SPOOF_MS__", str(_SPOOF_GRACE_MS))
        .replace("__KEY_MS__", str(_KEY_GRACE_MS))
        .strip()
    )


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
    global _script_error
    if not isinstance(message, dict):
        return
    mtype = message.get("type")
    if mtype == "send":
        payload = message.get("payload")
        if payload == "ready":
            _ready.set()
        elif isinstance(payload, list) and payload and payload[0] in ("fatal", "script-error"):
            _script_error = str(payload[1]) if len(payload) > 1 else str(payload[0])
            _log.error("Frida script %s: %s", payload[0], _script_error)
            if payload[0] == "fatal":
                _ready.set()  # 立即解除 attach 等待，回報致命錯誤
    elif mtype == "error":
        _script_error = message.get("description", "")
        _log.error("Frida script 錯誤: %s", _script_error)


def _session_alive(session) -> bool:
    """True if the frida session is still attached.

    frida 17 的 Session.is_detached 是 property（bool），舊版是方法——
    兩種都相容處理；無法判斷時視為存活，交由 _sync_update 失敗後的 re-attach 兜底。
    """
    if session is None:
        return False
    try:
        v = getattr(session, "is_detached", False)
        if callable(v):
            v = v()
        return not bool(v)
    except Exception:
        return True


def ensure_attached(hwnd: int) -> bool:
    """Attach Frida to the process owning hwnd; re-attach if pid changed or session died."""
    global _script, _session, _pid, _script_error
    if not hwnd:
        _set_error("Frida: 無效 hwnd")
        return False
    cur_pid = _hwnd_to_pid(hwnd)
    with _lock:
        if _script is not None and _pid == cur_pid and _session_alive(_session):
            return True
        if _script is not None:
            _log.warning("Frida 重新 attach（pid 改變或 session 已死亡）")
            detach()
        try:
            import frida
        except ImportError as e:
            _set_error(f"Frida 未安裝: {e}")
            return False
        _ready.clear()
        _script_error = ""
        try:
            _session = frida.attach(cur_pid)
            _script = _session.create_script(build_hook_script())
            _script.on("message", _on_message)
            _script.load()
            if not _ready.wait(_ATTACH_READY_TIMEOUT):
                detail = _script_error or "script 未回應 ready（可能被遊戲或防作弊阻擋）"
                raise RuntimeError(detail)
            if _script_error:
                raise RuntimeError(_script_error)
            _pid = cur_pid
            _last_error = ""
            _log.info("Frida 已注入 pid=%d (hwnd=%d)", cur_pid, hwnd)
            return True
        except Exception as e:
            detach()
            _set_error(f"Frida 注入失敗 pid={cur_pid}: {e}")
            return False


def _sync_update(hwnd: int, x: int, y: int) -> tuple[bool, str]:
    """Synchronously push spoofed coords to the injected script via rpc.exports."""
    try:
        sx, sy = _bg()._client_to_screen(hwnd, x, y)
        ret = _script.exports.update(sx, sy, x, y)
        if ret != 1:
            return False, f"script 回傳異常: {ret!r}"
        return True, ""
    except Exception as e:
        return False, str(e)


def click(hwnd: int, x: int, y: int, button: str = "left", hold_ms: int = 0) -> bool:
    """Click at (x, y) client coords via spoofed cursor + PostMessage."""
    if not ensure_attached(hwnd):
        return False
    with _lock:
        if _script is None:
            return False
        ok, err = _sync_update(hwnd, x, y)
        if not ok:
            # 注入可能已死亡 → 重新 attach 重試一次，避免需重開 app 才恢復
            _log.warning("Frida 座標同步失敗 (%s)，重新 attach 重試", err)
            detach()
            if ensure_attached(hwnd) and _script is not None:
                ok, err = _sync_update(hwnd, x, y)
        if not ok:
            _set_error(f"Frida 座標同步失敗: {err}")
            return False
    return _bg()._click_postmessage(hwnd, x, y, button, hold_ms)


def _sync_key(vk: int, down: bool) -> tuple[bool, str]:
    """Synchronously push a key down/up spoof to the injected script via rpc.exports."""
    try:
        ret = _script.exports.key(int(vk), 1 if down else 0)
        if ret != 1:
            return False, f"script 回傳異常: {ret!r}"
        return True, ""
    except Exception as e:
        return False, str(e)


def key(hwnd: int, vk: int, down: bool) -> bool:
    """Press (down=True) or release (down=False) a key via spoofed key-state + PostMessage."""
    if not ensure_attached(hwnd):
        return False
    with _lock:
        if _script is None:
            return False
        ok, err = _sync_key(vk, down)
        if not ok:
            # 注入可能已死亡 → 重新 attach 重試一次，避免需重開 app 才恢復
            _log.warning("Frida 鍵盤狀態同步失敗 (%s)，重新 attach 重試", err)
            detach()
            if ensure_attached(hwnd) and _script is not None:
                ok, err = _sync_key(vk, down)
        if not ok:
            _set_error(f"Frida 鍵盤狀態同步失敗: {err}")
            return False
    return _bg()._key_postmessage(hwnd, int(vk), down)


def detach() -> None:
    """Detach the injected session and restore the game (idempotent)."""
    global _script, _session, _pid, _script_error
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
        _ready.clear()
        _script_error = ""


if __name__ == "__main__":
    print("=== Frida BG Self-Check ===\n")

    js = build_hook_script()
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
        "hookRawInputBuffer",
        "GetRawInputBuffer",
        "RIM_TYPEKEYBOARD",
        "RAWKEYBOARD",
        "pendingRaw",
        "rawDevice",
        "captureDevice",
        "fetchKeyboardDevice",
        "MapVirtualKeyW",
        "EXTENDED_VK",
        "memmove",
    ):
        assert needle in js, f"hook 腳本缺少: {needle}"
    assert "Module.getExportByName" not in js, "不應使用 frida 17 會拋錯的舊 API"
    assert "recv('update'" not in js, "不應使用 one-shot 的 recv 握手（只會成功一次）"
    assert "__SPOOF_MS__" not in js, "spoof 寬限期應注入實際數值"
    assert "__KEY_MS__" not in js, "key 寬限期應注入實際數值"
    assert f"SPOOF_MS = {_SPOOF_GRACE_MS}" in js, "spoof 寬限期應等於 _SPOOF_GRACE_MS"
    assert f"KEY_MS = {_KEY_GRACE_MS}" in js, "key 寬限期應等於 _KEY_GRACE_MS"
    print("  [OK] hook 腳本內容")

    desktop = ctypes.windll.user32.GetDesktopWindow()
    assert _hwnd_to_pid(desktop) > 0, "桌面視窗 pid 應大於 0"
    assert _hwnd_to_pid(0) == 0
    print("  [OK] _hwnd_to_pid 換算")

    assert ensure_attached(0) is False and last_error()
    print("  [OK] 無效 hwnd 拒絕 attach")

    # 假 frida 流程：驗證 rpc.exports.update（同步）→ PostMessage 順序
    import sys

    class _FakeExports:
        def __init__(self):
            self.updates = []
            self.key_calls = []

        def update(self, sx, sy, cx, cy):
            self.updates.append((sx, sy, cx, cy))
            return 1

        def key(self, vk, down):
            self.key_calls.append((vk, down))
            return 1

    class _FakeScript:
        def __init__(self):
            self.loaded = False
            self.unloaded = False
            self._handler = None
            self.exports = _FakeExports()

        def on(self, name, cb):
            self._handler = cb

        def load(self):
            self.loaded = True
            self._handler({"type": "send", "payload": "ready"}, None)

        def unload(self):
            self.unloaded = True

    class _FakeSession:
        def __init__(self, script):
            self.script = script

        def create_script(self, js):
            return self.script

        def detach(self):
            pass

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
        # 連續兩次 click：驗證 rpc.exports 可重複（one-shot recv 的根因回歸）
        assert click(desktop, 10, 20, "left", 0), "click 應成功"
        assert click(desktop, 30, 40, "left", 0), "第二次 click 也應成功（rpc 非 one-shot）"
        up = fake_script.exports.updates
        assert len(up) == 2, f"應收到兩次 update: {up}"
        assert up[0][2] == 10 and up[0][3] == 20, f"client 座標錯誤: {up[0]}"
        assert up[1][2] == 30 and up[1][3] == 40, f"client 座標錯誤: {up[1]}"
        assert captured["msg"] == 0x0202, "應送 WM_LBUTTONUP"
    finally:
        ctypes.windll.user32.PostMessageW = _orig_pm
    print("  [OK] click: rpc.exports.update ×2 → PostMessage")

    captured = {}
    _orig_pm = ctypes.windll.user32.PostMessageW
    ctypes.windll.user32.PostMessageW = lambda hwnd, msg, wparam, lparam: (
        captured.update(msg=msg, wparam=wparam) or True
    )
    try:
        # key down/up：rpc.exports.key 同步 → PostMessage WM_KEYDOWN/UP
        assert key(desktop, 0x41, True), "key down 應成功"
        assert key(desktop, 0x41, False), "key up 應成功"
        kc = fake_script.exports.key_calls
        assert len(kc) == 2, f"應收到兩次 key rpc: {kc}"
        assert kc == [(0x41, 1), (0x41, 0)], f"key rpc 參數錯誤: {kc}"
        assert captured["msg"] == 0x0101, "應送 WM_KEYUP"
    finally:
        ctypes.windll.user32.PostMessageW = _orig_pm
    print("  [OK] key: rpc.exports.key(down/up) → PostMessage WM_KEYDOWN/UP")

    detach()
    assert fake_script.unloaded
    print("  [OK] detach 冪等釋放")

    del sys.modules["frida"]
    print("\n=== All 7 checks passed ===")
