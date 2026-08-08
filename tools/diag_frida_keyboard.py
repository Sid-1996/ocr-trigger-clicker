"""Frida 鍵盤輸入後端診斷工具。

用途：判定目標遊戲實際用哪條 API 讀鍵盤輸入，決定後台鍵盤該 hook 什麼。
執行期間使用者需手動操作（對焦遊戲後按按鍵），觀察 log 顯示哪個 API 被呼叫。

用法:
    python tools/diag_frida_keyboard.py "<視窗標題>"

會 hook：
- GetKeyState / GetAsyncKeyState / GetKeyboardState（legacy key-state polling）
- GetMessageW / PeekMessageW（偵測 WM_KEYDOWN/WM_INPUT/WM_CHAR 訊息流入）
- RegisterRawInputDevices / GetRawInputData / GetRawInputBuffer（Raw Input 路徑）

log 即時印出，Ctrl+C 結束。
"""

import ctypes
import ctypes.wintypes as wintypes
import sys
import time

DIAG_JS = r"""
'use strict';
var user32 = Process.findModuleByName('user32.dll');

function logMsg(m) { send(m); }

function hookKeyState(name) {
  var addr = user32.findExportByName(name);
  if (addr === null) { logMsg(['skip', name]); return; }
  Interceptor.attach(addr, {
    onEnter: function (args) { this.vk = args[0].toInt32() & 0xFF; },
    onLeave: function (retval) {
      logMsg(['keystate', name, this.vk, retval.toInt32() & 0xFFFF]);
    }
  });
}
hookKeyState('GetKeyState');
hookKeyState('GetAsyncKeyState');

var gkb = user32.findExportByName('GetKeyboardState');
if (gkb !== null) {
  Interceptor.attach(gkb, {
    onEnter: function () { this.t0 = Date.now(); },
    onLeave: function () { logMsg(['keyboardstate', Date.now() - this.t0]); }
  });
}

var kbdMsgIds = { 0x0100: 'WM_KEYDOWN', 0x0101: 'WM_KEYUP', 0x0102: 'WM_CHAR',
                  0x0104: 'WM_SYSKEYDOWN', 0x0105: 'WM_SYSKEYUP', 0x00FF: 'WM_INPUT' };

function hookMsgGet(name) {
  var addr = user32.findExportByName(name);
  if (addr === null) { logMsg(['skip', name]); return; }
  Interceptor.attach(addr, {
    onEnter: function (args) { this.msg = args[0]; },
    onLeave: function (retval) {
      if (this.msg.isNull()) return;
      var m = this.msg.add(Process.pointerSize).readU32();  // message id（hwnd 之後）
      if (kbdMsgIds[m] !== undefined) {
        var wparam = this.msg.add(Process.pointerSize + 4).readU32();
        logMsg(['msg', name, kbdMsgIds[m], m, wparam & 0xFFFF]);
      }
    }
  });
}
hookMsgGet('GetMessageW');
hookMsgGet('PeekMessageW');

function hookRawInput() {
  var rrid = user32.findExportByName('RegisterRawInputDevices');
  if (rrid !== null) {
    Interceptor.attach(rrid, {
      onEnter: function (args) {
        var n = args[1].toInt32();
        logMsg(['rawinput', 'RegisterRawInputDevices', n]);
      }
    });
  }
  var grid = user32.findExportByName('GetRawInputData');
  if (grid !== null) {
    Interceptor.attach(grid, {
      onEnter: function (args) { this.t0 = Date.now(); },
      onLeave: function () { logMsg(['rawinput', 'GetRawInputData', Date.now() - this.t0]); }
    });
  }
  var grib = user32.findExportByName('GetRawInputBuffer');
  if (grib !== null) {
    Interceptor.attach(grib, {
      onEnter: function (args) { this.t0 = Date.now(); },
      onLeave: function () { logMsg(['rawinput', 'GetRawInputBuffer', Date.now() - this.t0]); }
    });
  }
}
hookRawInput();

send('ready');
"""


# ── Windows 視窗搜尋（與 core/01_screenshot.py 同法，確保一致）──
def _find_hwnd(title: str) -> int | None:
    sys.path.insert(0, ".")  # 專案根，讓 core/ 可 import
    from _loader import load_sibling

    screenshot = load_sibling("screenshot", "core/01_screenshot.py")
    return screenshot.get_window_hwnd(title)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-l", "--list", "list"):
        print("=== 可見視窗清單（與主工具同法）===")
        sys.path.insert(0, ".")
        from _loader import load_sibling

        screenshot = load_sibling("screenshot", "core/01_screenshot.py")
        for t in sorted(screenshot.list_windows()):
            print(f"  {t}")
        print('\n用法: python tools/diag_frida_keyboard.py "<視窗標題子字串>"')
        return 0
    title = sys.argv[1]
    hwnd = _find_hwnd(title)
    if hwnd is None:
        print(f"找不到視窗: {title}")
        return 1
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    print(f"attaching pid={pid.value} hwnd={hwnd}")

    import frida

    session = frida.attach(int(pid.value))
    script = session.create_script(DIAG_JS)
    script.on("message", lambda message, data: _on_message(message))
    script.load()

    print("已注入。現在：對焦遊戲視窗 → 手動按幾下想測試的按鍵（如 Escape）→ 看 log。")
    print("Ctrl+C 結束。\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        script.unload()
        session.detach()
        print("\n已 detach")
    return 0


def _on_message(message):
    if message.get("type") != "send":
        return
    payload = message.get("payload", [])
    tag = payload[0]
    if tag == "skip":
        print(f"  [skip] {payload[1]} 不在 user32（遊戲可能沒用該 API）")
        return
    if tag == "keystate":
        print(f"  [keystate] {payload[1]}(vk={payload[2]:#x}) ret={payload[3]:#06x}")
    elif tag == "keyboardstate":
        print(f"  [keyboardstate] 呼叫（{payload[1]}ms）")
    elif tag == "msg":
        print(f"  [msg] {payload[1]}() -> {payload[2]} {payload[3]:#06x} wparam={payload[4]:#06x}")
    elif tag == "rawinput":
        print(f"  [rawinput] {payload[1]} n={payload[2]}")


if __name__ == "__main__":
    sys.exit(main())
