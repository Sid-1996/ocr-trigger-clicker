import importlib.util
import random
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


def _import_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_here = Path(__file__).parent
_screenshot = _import_module("screenshot", str(_here / "01_screenshot.py"))
_ocr = _import_module("ocr_engine", str(_here / "02_ocr_engine.py"))
_ahk = _import_module("ahk_socket", str(_here / "03_ahk_socket.py"))
_rule = _import_module("rule_engine", str(_here / "04_rule_engine.py"))

list_windows = _screenshot.list_windows
get_window_rect = _screenshot.get_window_rect
capture = _screenshot.capture
OcrResult = _ocr.OcrResult
recognize = _ocr.recognize
init_engine = _ocr.init_engine
Rule = _rule.Rule
load_rules = _rule.load_rules
save_rules = _rule.save_rules
check_trigger = _rule.check_trigger
apply_trigger = _rule.apply_trigger
get_roi = _rule.get_roi


@dataclass
class TriggerLog:
    timestamp: float
    rule_id: str
    rule_name: str
    matched_text: str
    click_x: int
    click_y: int


class MainLoop:
    def __init__(self, rules_path: str, window_title: str, interval_ms: int = 100):
        self._rules_path = rules_path
        self._window_title = window_title
        self._interval = interval_ms / 1000.0

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._logs: deque = deque(maxlen=200)
        self._logs_lock = threading.Lock()

        self.on_trigger: Optional[Callable[[TriggerLog], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_window_lost: Optional[Callable[[], None]] = None

        self._rules: list[Rule] = []
        self._load_rules()
        init_engine()
        _ahk.init_ahk()

    def _load_rules(self):
        self._rules = load_rules(self._rules_path)

    def _send_click(self, x: int, y: int, button: str) -> bool:
        return _ahk.send_click(x, y, button)

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                if self._pause_event.is_set():
                    self._stop_event.wait(0.1)
                    continue

                rect = get_window_rect(self._window_title)
                if rect is None:
                    if self.on_window_lost:
                        self.on_window_lost()
                    self._pause_event.set()
                    self._stop_event.wait(1.0)
                    continue

                for rule in self._rules:
                    if not rule.enabled:
                        continue

                    roi = get_roi(rule)
                    img = capture(self._window_title, roi)
                    if img is None:
                        continue

                    roi_offset = {"x": roi["x"], "y": roi["y"]} if roi else None
                    results = recognize(img, roi_offset=roi_offset)

                    hit, matched = check_trigger(rule, results)
                    if not hit or matched is None:
                        continue

                    params = apply_trigger(rule)

                    if rule.click_position == "text_center":
                        off = rule.random_offset
                        dx = random.randint(-off, off) if off else 0
                        dy = random.randint(-off, off) if off else 0
                        cx = matched.center_x + dx
                        cy = matched.center_y + dy
                    else:
                        cx, cy = params["x"], params["y"]

                    self._send_click(cx, cy, params["button"])

                    log = TriggerLog(
                        timestamp=time.time(),
                        rule_id=rule.id,
                        rule_name=rule.name,
                        matched_text=matched.text,
                        click_x=cx,
                        click_y=cy,
                    )
                    with self._logs_lock:
                        self._logs.append(log)

                    if self.on_trigger:
                        self.on_trigger(log)

            except Exception as e:
                if self.on_error:
                    self.on_error(str(e))

            self._stop_event.wait(self._interval)

    def start(self) -> None:
        self._stop_event.clear()
        self._pause_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        _ahk.shutdown()

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    @property
    def is_running(self) -> bool:
        return (
            self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()
        )

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def get_logs(self, limit: int = 50) -> list[TriggerLog]:
        with self._logs_lock:
            return list(self._logs)[-limit:]

    def reload_rules(self) -> None:
        self._load_rules()

    def set_window(self, title: str) -> bool:
        if get_window_rect(title) is None:
            return False
        self._window_title = title
        return True


if __name__ == "__main__":
    windows = list_windows()
    print("=== 所有可見視窗 ===")
    for i, w in enumerate(windows, 1):
        print(f"{i:3d}. {w}")

    target = input("\n請輸入目標視窗標題關鍵字: ").strip()
    rect = get_window_rect(target)
    if rect is None:
        print("找不到該視窗")
        raise SystemExit(1)

    rules_path = str(_here / "rules.json")
    loop = MainLoop(rules_path, target)

    def on_trigger(log: TriggerLog):
        print(
            f"[觸發] {log.rule_name} → 點擊 ({log.click_x}, {log.click_y})  文字={log.matched_text!r}"
        )

    def on_error(msg: str):
        print(f"[錯誤] {msg}")

    def on_window_lost():
        print(f"[警告] 視窗 '{target}' 已消失，暫停偵測")

    loop.on_trigger = on_trigger
    loop.on_error = on_error
    loop.on_window_lost = on_window_lost

    loop.start()
    print(f"\n偵測迴圈已啟動（視窗: {target}）")
    print("指令: p=暫停/繼續  r=重新載入規則  q=結束\n")

    import msvcrt

    while loop.is_running:
        if msvcrt.kbhit():
            key = msvcrt.getch().decode().lower()
            if key == "p":
                if loop.is_paused:
                    loop.resume()
                    print("▶ 恢復偵測")
                else:
                    loop.pause()
                    print("⏸ 暫停偵測")
            elif key == "r":
                loop.reload_rules()
                print(f"↻ 已重新載入規則 ({len(loop._rules)} 條)")
            elif key == "q":
                print("正在結束...")
                break
        time.sleep(0.05)

    loop.stop()
    print("已結束")
