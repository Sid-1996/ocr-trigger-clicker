import random
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Optional

import cv2

import numpy as np

from _loader import load_sibling

_screenshot = load_sibling("screenshot", "core/01_screenshot.py")
_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_ahk = load_sibling("ahk_socket", "core/03_ahk_socket.py")
_rule = load_sibling("rule_engine", "core/04_rule_engine.py")
_perf = load_sibling("performance_monitor", "core/10_performance_monitor.py")
PerformanceMonitor = _perf.PerformanceMonitor
is_window_foreground = _perf.is_window_foreground
get_window_hwnd_orig = getattr(_screenshot, "get_window_hwnd", lambda title: None)

_MIN_INTERVAL_SEC = 0.1
_RUNAWAY_THRESHOLD = 5
_RUNAWAY_WINDOW_SEC = 10.0
_MAX_CPS = 5
_CPS_WINDOW_SEC = 1.0

list_windows = _screenshot.list_windows
get_window_rect = _screenshot.get_window_rect
get_window_hwnd = getattr(_screenshot, "get_window_hwnd", lambda title: None)
get_dpi_scaling_factor = getattr(_screenshot, "get_dpi_scaling_factor", lambda hwnd: 1.0)
capture = _screenshot.capture
capture_window_content = getattr(_screenshot, "capture_window_content", lambda title: None)
activate_window = _screenshot.activate_window
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
    def __init__(self, rules_path: str, window_title: str, interval_ms: int = 500, focus_safe: bool = False, verbose: bool = True):
        self._rules_path = rules_path
        self._window_title = window_title
        self._interval = max(interval_ms / 1000.0, _MIN_INTERVAL_SEC)
        self._focus_safe = focus_safe
        self._verbose = verbose
        self._window_hwnd = get_window_hwnd_orig(window_title)
        self._dpi_scale = get_dpi_scaling_factor(self._window_hwnd)

        self._rules_lock = threading.RLock()
        self._window_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._emergency_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._logs: deque = deque(maxlen=200)
        self._logs_lock = threading.Lock()

        self._prev_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._frame_diff_ratio: float = 0.0

        self._rule_trigger_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._rule_auto_disabled: set[str] = set()

        self._tracking_hwnd: Optional[int] = self._window_hwnd

        self.on_trigger: Optional[Callable[[TriggerLog], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_warning: Optional[Callable[[str], None]] = None
        self.on_info: Optional[Callable[[str], None]] = None
        self.on_window_lost: Optional[Callable[[], None]] = None
        self.on_emergency: Optional[Callable[[], None]] = None

        self._perf = PerformanceMonitor()
        self._perf.on_rate_limit_exceeded = self._on_rate_limit_exceeded
        self._perf.on_cpu_warn = self._on_cpu_warn
        self._perf.on_memory_warn = self._on_memory_warn
        self._perf.start()

        self._rules: list[Rule] = []
        self._load_rules()
        init_engine()

    def _log(self, msg: str):
        if self._verbose:
            print(f"[主循環] {msg}")

    def _load_rules(self):
        with self._rules_lock:
            self._rules = load_rules(self._rules_path)

    def _send_click(self, x: int, y: int, button: str) -> bool:
        return _ahk.send_click(x, y, button)

    def _to_screen_coords(self, rect: dict, x: int, y: int) -> tuple[int, int]:
        return (int(round(rect["x"] + x)), int(round(rect["y"] + y)))

    def _process_rules(self, img: np.ndarray, rect: dict) -> None:
        with self._rules_lock:
            rules_snapshot = list(self._rules)
        if not rules_snapshot:
            if self._verbose:
                self._log("無啟用中的規則")
            return

        has_any_rules = any(r.enabled for r in rules_snapshot)
        if not has_any_rules:
            return

        for rule in rules_snapshot:
            if not rule.enabled:
                continue
            if rule.id in self._rule_auto_disabled:
                continue

            if self._verbose:
                self._log(f"處理規則「{rule.name}」目標「{rule.target_text}」")

            try:
                roi = get_roi(rule)
                if roi:
                    h, w = img.shape[:2]
                    x1 = max(0, roi["x"])
                    y1 = max(0, roi["y"])
                    x2 = min(w, roi["x"] + roi["w"])
                    y2 = min(h, roi["y"] + roi["h"])
                    if x2 <= x1 or y2 <= y1:
                        if self._verbose:
                            self._log(f"規則「{rule.name}」ROI 超出畫面，跳過")
                        continue
                    roi_img = img[y1:y2, x1:x2]
                    rule_results = recognize(roi_img, preprocess=False, max_side_len=0, min_confidence=0.25)
                    for r in rule_results:
                        r.x += x1
                        r.y += y1
                        r.center_x = r.x + r.w // 2
                        r.center_y = r.y + r.h // 2
                    if self._verbose:
                        self._log(f"ROI OCR 找到 {len(rule_results)} 個文字區塊: {[r.text for r in rule_results[:5]]}")
                else:
                    rule_results = recognize(img, preprocess=False, max_side_len=0, min_confidence=0.25)
                    if self._verbose:
                        self._log(f"全視窗 OCR 找到 {len(rule_results)} 個文字區塊: {[r.text for r in rule_results[:5]]}")

                if not rule_results:
                    if self._verbose:
                        self._log(f"規則「{rule.name}」OCR 無結果")
                    continue

                hit, matched = check_trigger(rule, rule_results)
                if not hit or matched is None:
                    if self._verbose:
                        self._log(f"規則「{rule.name}」比對「{rule.target_text}」→ 不符合 (共{len(rule_results)}個文字)")
                    continue

                if self._verbose:
                    self._log(f"規則「{rule.name}」命中「{matched.text}」!")
                if self.check_runaway_rule(rule.id):
                    self._rule_auto_disabled.add(rule.id)
                    rule.enabled = False
                    msg = f"規則「{rule.name}」觸發過於頻繁，已自動停用"
                    if self.on_warning:
                        self.on_warning(msg)
                    continue

                if self._focus_safe:
                    with self._window_lock:
                        hwnd = self._tracking_hwnd
                    if hwnd is not None and not is_window_foreground(hwnd):
                        if self._verbose:
                            self._log(f"規則「{rule.name}」命中但視窗不在前景，跳過")
                        continue

                if not self._perf.check_rate_limit():
                    if self._verbose:
                        self._log("全域速率限制生效，跳過此次點擊")
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

                sx, sy = self._to_screen_coords(rect, cx, cy)
                ok = self._send_click(sx, sy, params["button"])
                if ok:
                    self._perf.record_click()

                log = TriggerLog(
                    timestamp=time.time(),
                    rule_id=rule.id,
                    rule_name=rule.name,
                    matched_text=matched.text,
                    click_x=sx,
                    click_y=sy,
                )
                with self._logs_lock:
                    self._logs.append(log)

                if self.on_trigger:
                    self.on_trigger(log)

                with self._rules_lock:
                    save_rules(self._rules, self._rules_path)
            except Exception as e:
                if self._verbose:
                    self._log(f"規則「{rule.name}」處理異常: {e}")
                    if self.on_warning:
                        self.on_warning(f"規則「{rule.name}」異常: {e}")

    def _loop(self):
        iteration = 0
        while not self._stop_event.is_set():
            if self._emergency_event.is_set():
                break
            iteration += 1
            loop_start = time.monotonic()
            try:
                if self._pause_event.is_set():
                    self._stop_event.wait(0.1)
                    self._perf.record_frame()
                    continue

                with self._window_lock:
                    title = self._window_title
                rect = get_window_rect(title)
                if rect is None:
                    if self.on_window_lost:
                        self.on_window_lost()
                    self._pause_event.set()
                    while not self._stop_event.is_set():
                        self._stop_event.wait(5.0)
                        rect = get_window_rect(title)
                        if rect is not None:
                            self._pause_event.clear()
                            if self._verbose:
                                self._log("視窗已重新出現，恢復偵測")
                            break
                    self._perf.record_frame()
                    continue

                t0 = time.monotonic()
                img = capture(self._window_title)
                if img is None:
                    img = capture_window_content(self._window_title)
                    if img is not None:
                        if self._verbose:
                            self._log("使用 PrintWindow 後備截圖成功")
                        h, w = img.shape[:2]
                        if w < rect["w"] or h < rect["h"]:
                            co = _screenshot.get_window_client_offset(title)
                            if co and co[0] + w <= rect["w"] and co[1] + h <= rect["h"]:
                                full = np.zeros((rect["h"], rect["w"], 3), dtype=np.uint8)
                                full[co[1]:co[1]+h, co[0]:co[0]+w] = img
                                img = full
                                if self._verbose:
                                    self._log(f"填補視窗邊框至 {rect['w']}x{rect['h']}")
                t1 = time.monotonic()
                if img is None:
                    if self._verbose and iteration % 30 == 0:
                        self._log(f"所有截圖方式皆失敗: {title}")
                    self._perf.record_frame()
                    continue

                with self._frame_lock:
                    prev = self._prev_frame
                    self._prev_frame = img

                if prev is not None and prev.shape == img.shape:
                    diff = cv2.absdiff(prev, img)
                    change_ratio = np.mean(diff) / 255.0
                    self._frame_diff_ratio = change_ratio
                    if change_ratio < 0.02:
                        if self._verbose and iteration % 30 == 0:
                            self._log(f"畫面無變化 ({change_ratio:.4f})，跳過 OCR")
                        self._perf.record_frame()
                        self._stop_event.wait(self._interval)
                        continue
                else:
                    self._frame_diff_ratio = 1.0

                if self._verbose and iteration % 1 == 0:
                    self._log(f"視窗位置=({rect['x']},{rect['y']}) 尺寸=({rect['w']}×{rect['h']}) img={img.shape}")

                t2 = time.monotonic()
                self._process_rules(img, rect)
                t3 = time.monotonic()

                ocr_ms = (t3 - t2) * 1000
                loop_elapsed = (time.monotonic() - loop_start) * 1000
                self._perf.record_frame(ocr_ms=ocr_ms, loop_ms=loop_elapsed)

                if loop_elapsed > 2000 and self.on_warning:
                    self.on_warning(
                        f"慢循環: {loop_elapsed:.0f}ms "
                        f"(截圖={(t1-t0)*1000:.0f}ms "
                        f"OCR={ocr_ms:.0f}ms)"
                    )

            except Exception as e:
                if self.on_error:
                    self.on_error(f"主循環異常: {e}")

            if self._pause_event.is_set() or self._emergency_event.is_set():
                continue

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
        self._perf.stop()

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
        self._rule_auto_disabled.clear()
        with self._rules_lock:
            self._load_rules()

    def set_window(self, title: str) -> bool:
        with self._window_lock:
            if get_window_rect(title) is None:
                return False
            self._window_title = title
            self._window_hwnd = get_window_hwnd_orig(title)
            self._dpi_scale = get_dpi_scaling_factor(self._window_hwnd)
            self._tracking_hwnd = self._window_hwnd
            return True

    def set_focus_safe(self, enabled: bool):
        self._focus_safe = enabled

    @property
    def focus_safe(self) -> bool:
        return self._focus_safe

    @property
    def perf_monitor(self) -> PerformanceMonitor:
        return self._perf

    def emergency_stop(self):
        self._emergency_event.set()
        self._pause_event.set()
        _ahk.send_emergency_stop()
        if self.on_emergency:
            self.on_emergency()

    def _on_rate_limit_exceeded(self):
        self._pause_event.set()
        msg = "全域速率限制違規次數過多，已自動暫停偵測"
        if self.on_error:
            self.on_error(msg)

    def _on_cpu_warn(self, pct: float):
        msg = f"CPU 使用率過高 ({pct:.0f}%)，請注意系統負載"
        if self.on_warning:
            self.on_warning(msg)

    def _on_memory_warn(self, mb: float):
        msg = f"記憶體使用量過高 ({mb:.0f} MB)，請注意系統負載"
        if self.on_warning:
            self.on_warning(msg)

    def get_perf_stats(self) -> dict:
        return self._perf.get_stats()

    def check_runaway_rule(self, rule_id: str) -> bool:
        now = time.monotonic()
        history = self._rule_trigger_history[rule_id]
        cutoff = now - _RUNAWAY_WINDOW_SEC
        while history and history[0] < cutoff:
            history.popleft()
        history.append(now)
        if len(history) > _RUNAWAY_THRESHOLD:
            return True
        return False


if __name__ == "__main__":
    from pathlib import Path

    _here = Path(__file__).resolve().parent.parent
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
