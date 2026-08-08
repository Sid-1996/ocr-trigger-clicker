"""Frida 鍵盤輸入後端診斷工具。

用途：判定目標遊戲實際用哪條 API 讀鍵盤輸入，決定後台鍵盤該 hook 什麼。
試跑期間使用者需手動操作（對焦遊戲後按幾下按鍵），時間到自動印摘要。

用法:
    python tools/diag_frida_keyboard.py "<視窗標題>" [秒數]

會 hook：
- GetKeyState / GetAsyncKeyState / GetKeyboardState（legacy key-state polling）
- GetMessageW / PeekMessageW（偵測 WM_KEYDOWN/WM_INPUT/WM_CHAR 訊息流入）
- RegisterRawInputDevices / GetRawInputData / GetRawInputBuffer（Raw Input 路徑）

聚合在 JS 端，只有每 2 秒心跳 + 結束時一次摘要走 IPC，log 不會爆炸。
摘要同時寫入 tools/diag_report.txt。
"""

import ctypes
import ctypes.wintypes as wintypes
import json
import sys
import time

DIAG_JS = r"""
'use strict';
var user32 = Process.findModuleByName('user32.dll');

var stats = {
  keystate: {},    // name -> { vk: count }
  keyboardstate: 0,
  msg: {},         // name -> { typeName: count }
  rawinput: {},    // name -> count
  skips: [],
  total: 0
};

function keyOf(name, vk) {
  if (!stats.keystate[name]) stats.keystate[name] = {};
  var k = '0x' + vk.toString(16);
  if (!(k in stats.keystate[name])) stats.keystate[name][k] = 0;
  return k;
}

function hookKeyState(name) {
  var addr = user32.findExportByName(name);
  if (addr === null) { stats.skips.push(name); return; }
  Interceptor.attach(addr, {
    onEnter: function (args) { this.vk = args[0].toInt32() & 0xFF; },
    onLeave: function () {
      stats.total++;
      var k = keyOf(name, this.vk);
      stats.keystate[name][k]++;
    }
  });
}
hookKeyState('GetKeyState');
hookKeyState('GetAsyncKeyState');

var gkb = user32.findExportByName('GetKeyboardState');
if (gkb === null) {
  stats.skips.push('GetKeyboardState');
} else {
  Interceptor.attach(gkb, {
    onEnter: function () {},
    onLeave: function () { stats.total++; stats.keyboardstate++; }
  });
}

var kbdMsgIds = { 0x0100: 'WM_KEYDOWN', 0x0101: 'WM_KEYUP', 0x0102: 'WM_CHAR',
                  0x0104: 'WM_SYSKEYDOWN', 0x0105: 'WM_SYSKEYUP', 0x00FF: 'WM_INPUT' };

function hookMsgGet(name) {
  var addr = user32.findExportByName(name);
  if (addr === null) { stats.skips.push(name); return; }
  Interceptor.attach(addr, {
    onEnter: function (args) { this.msg = args[0]; },
    onLeave: function () {
      if (this.msg.isNull()) return;
      var m = this.msg.add(Process.pointerSize).readU32();
      var typeName = kbdMsgIds[m];
      if (typeName === undefined) return;
      stats.total++;
      if (!stats.msg[name]) stats.msg[name] = {};
      if (!(typeName in stats.msg[name])) stats.msg[name][typeName] = 0;
      stats.msg[name][typeName]++;
    }
  });
}
hookMsgGet('GetMessageW');
hookMsgGet('PeekMessageW');

function hookRawInput() {
  var rrid = user32.findExportByName('RegisterRawInputDevices');
  if (rrid === null) { stats.skips.push('RegisterRawInputDevices'); }
  else {
    Interceptor.attach(rrid, {
      onEnter: function () {},
      onLeave: function () { stats.total++; stats.rawinput['RegisterRawInputDevices'] = (stats.rawinput['RegisterRawInputDevices'] || 0) + 1; }
    });
  }
  ['GetRawInputData', 'GetRawInputBuffer'].forEach(function (name) {
    var addr = user32.findExportByName(name);
    if (addr === null) { stats.skips.push(name); return; }
    Interceptor.attach(addr, {
      onEnter: function () {},
      onLeave: function () { stats.total++; stats.rawinput[name] = (stats.rawinput[name] || 0) + 1; }
    });
  });
}
hookRawInput();

rpc.exports = {
  finish: function () { return stats; }
};

send('ready');
"""


# ── Windows 視窗搜尋（與 core/01_screenshot.py 同法，確保一致）──
def _find_hwnd(title: str) -> int | None:
    sys.path.insert(0, ".")  # 專案根，讓 core/ 可 import
    from _loader import load_sibling

    screenshot = load_sibling("screenshot", "core/01_screenshot.py")
    return screenshot.get_window_hwnd(title)


def _print_summary(stats: dict) -> None:
    skips = stats.get("skips", [])
    if skips:
        print("\n[skip] 以下 API 不在 user32（遊戲沒用到）：")
        for s in skips:
            print(f"  {s}")
    else:
        print("\n[skip] 所有目標 API 都存在 user32")

    print("\n[keystate] 各 API 查詢的 vk 分布：")
    ks = stats.get("keystate", {})
    for name in sorted(ks):
        counts = ks[name]
        print(f"  {name}: 共 {sum(counts.values())} 次呼叫, 出現 {len(counts)} 種 vk")
        print(f"    vk = {sorted(counts.keys())}")
    if not ks:
        print("  （無任何 keystate 呼叫）")

    print(f"\n[GetKeyboardState] 共 {stats.get('keyboardstate', 0)} 次呼叫")

    print("\n[msg] 鍵盤相關訊息：")
    msg = stats.get("msg", {})
    if msg:
        for name in sorted(msg):
            for type_name, count in sorted(msg[name].items()):
                print(f"  {name}() -> {type_name}: {count} 次")
    else:
        print("  （試跑期間沒有鍵盤訊息）")

    print("\n[rawinput] Raw Input：")
    ri = stats.get("rawinput", {})
    if ri:
        for name, count in sorted(ri.items()):
            print(f"  {name}: {count} 次")
    else:
        print("  （無 Raw Input 呼叫）")

    print(f"\n總計 {stats.get('total', 0)} 次 API 呼叫")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-l", "--list", "list"):
        print("=== 可見視窗清單（與主工具同法）===")
        sys.path.insert(0, ".")
        from _loader import load_sibling

        screenshot = load_sibling("screenshot", "core/01_screenshot.py")
        for t in sorted(screenshot.list_windows()):
            print(f"  {t}")
        print('\n用法: python tools/diag_frida_keyboard.py "<視窗標題子字串>" [秒數]')
        return 0

    title = sys.argv[1]
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0

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

    print("已注入。現在：對焦遊戲視窗 → 試跑期間按幾下想測試的按鍵（如 Escape）。")
    print(f"試跑 {duration:g} 秒後自動結束並印摘要。\n")

    stats = None
    try:
        deadline = time.monotonic() + duration
        last_tick = time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(0.2)
            now = time.monotonic()
            if now - last_tick >= 2.0:
                last_tick = now
                print(f"  ... 進行中（剩 {deadline - now:.0f}s，已收集資料，結束時印摘要）")
        print("\n時間到，取得摘要...")
        stats = script.exports_sync.finish()
    except KeyboardInterrupt:
        print("\n手動中斷，取得摘要...")
        stats = script.exports_sync.finish()
    finally:
        script.unload()
        session.detach()

    _print_summary(stats)
    report_path = "tools/diag_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\n完整資料已寫入 {report_path}")
    return 0


def _on_message(message):
    if message.get("type") != "send":
        return
    payload = message.get("payload", [])
    if payload and payload[0] == "ready":
        print("[ready] 已注入，hook 完成。")


if __name__ == "__main__":
    sys.exit(main())
