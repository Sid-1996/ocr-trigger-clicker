import logging
import random
import re
import sys as _sys
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _loader import load_sibling  # noqa: E402

_screenshot = load_sibling("screenshot", "core/01_screenshot.py")
_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_ahk = load_sibling("ahk_socket", "core/03_ahk_socket.py")
_rule = load_sibling("rule_engine", "core/04_rule_engine.py")
_perf = load_sibling("performance_monitor", "core/10_performance_monitor.py")
PerformanceMonitor = _perf.PerformanceMonitor
get_window_hwnd_orig = getattr(_screenshot, "get_window_hwnd", lambda title: None)

_MIN_INTERVAL_SEC = 0.1
_RUNAWAY_THRESHOLD = 5
_RUNAWAY_WINDOW_SEC = 10.0
_MAX_CPS = 5
_CPS_WINDOW_SEC = 1.0
_MAX_PENDING_TRIGGERS = 200
_AUTO_DISABLE_RECOVERY_SEC = 30.0

list_windows = _screenshot.list_windows
get_window_rect = _screenshot.get_window_rect
get_dpi_scaling_factor = getattr(_screenshot, "get_dpi_scaling_factor", lambda hwnd: 1.0)
capture = _screenshot.capture
capture_window_full = getattr(_screenshot, "capture_window_content", lambda title: None)
activate_window = _screenshot.activate_window
is_window_foreground = _perf.is_window_foreground
OcrResult = _ocr.OcrResult
recognize = _ocr.recognize
find_text = _ocr.find_text
init_engine = _ocr.init_engine
Rule = _rule.Rule
load_rules = _rule.load_rules
save_rules = _rule.save_rules


def crop_roi(img: np.ndarray, roi: dict) -> np.ndarray | None:
    h, w = img.shape[:2]
    x1 = max(0, roi["x"])
    y1 = max(0, roi["y"])
    x2 = min(w, roi["x"] + roi["w"])
    y2 = min(h, roi["y"] + roi["h"])
    if x2 <= x1 or y2 <= y1:
        return None
    return img[y1:y2, x1:x2]


def extract_number(text: str, pick: str) -> float | None:
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    if not nums:
        return None
    idx = 0 if pick == "first" else -1
    return float(nums[idx])


def poll_roi_value(
    roi: dict, pick: str, timeout_ms: int, title: str, stop_event=None
) -> float | None:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if stop_event and stop_event.is_set():
            return None
        img = capture(title)
        if img is None:
            img = capture_window_full(title)
        if img is not None:
            roi_img = crop_roi(img, roi)
            if roi_img is not None:
                results = recognize(roi_img, preprocess=False, max_side_len=0, min_confidence=0.25)
                for r in results:
                    val = extract_number(r.text, pick)
                    if val is not None:
                        return val
        if (stop_event or threading.Event()).wait(timeout=0.2):
            return None
    return None


@dataclass
class TriggerLog:
    timestamp: float
    rule_id: str
    rule_name: str
    matched_text: str
    click_x: int
    click_y: int


@dataclass
class StepContext:
    img: np.ndarray
    rect: dict
    matched_text: Optional[OcrResult] = None
    forced: bool = False


@dataclass
class StepResult:
    action: str  # "continue" | "stop" | "jump" | "retry_from"
    rule_id: Optional[str] = None
    data: dict = field(default_factory=dict)


class MainLoop:
    def __init__(
        self,
        rules_path: str,
        window_title: str,
        interval_ms: int = 500,
        verbose: bool = True,
    ):
        self._rules_path = rules_path
        self._window_title = window_title
        self._interval = max(interval_ms / 1000.0, _MIN_INTERVAL_SEC)
        self._verbose = verbose
        self._window_hwnd = get_window_hwnd_orig(window_title)
        self._dpi_scale = get_dpi_scaling_factor(self._window_hwnd)

        self._rules_lock = threading.RLock()
        self._window_lock = threading.RLock()
        self._foreground_only = True
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
        self._auto_disabled_at: dict[str, float] = {}
        self._pending_forced_triggers: set[str] = set()
        self._rules_dirty: bool = False
        self._save_period_counter: int = 0
        self._cycle_visited: set[str] = set()
        self._process_counter: int = 0

        self._tracking_hwnd: Optional[int] = self._window_hwnd

        self.on_trigger: Optional[Callable[[TriggerLog], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_warning: Optional[Callable[[str], None]] = None
        self.on_info: Optional[Callable[[str], None]] = None
        self.on_window_lost: Optional[Callable[[], None]] = None
        self.on_emergency: Optional[Callable[[], None]] = None
        self.on_compare_round: Optional[Callable[[dict], None]] = None

        self._perf = PerformanceMonitor()
        self._perf.on_rate_limit_exceeded = self._on_rate_limit_exceeded
        self._perf.on_cpu_warn = self._on_cpu_warn
        self._perf.on_memory_warn = self._on_memory_warn
        self._perf.start()

        self._rules: list[Rule] = []
        self._log_dir = Path(__file__).resolve().parent.parent / "logs"
        self._log_dir.mkdir(exist_ok=True)
        self._logger = logging.getLogger("main_loop")
        self._logger.setLevel(logging.INFO)
        self._logger.handlers.clear()
        handler = TimedRotatingFileHandler(
            self._log_dir / "main.log", when="midnight", backupCount=7, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        self._logger.addHandler(handler)
        self._logger.handler = handler
        self._load_rules()
        init_engine()

    def _log(self, msg: str):
        if self._verbose:
            print(f"[主循環] {msg}")
        self._logger.info(msg)

    def _load_rules(self):
        with self._rules_lock:
            self._rules = load_rules(self._rules_path)

    def _send_click(self, x: int, y: int, button: str) -> bool:
        return _ahk.send_click(x, y, button)

    def _send_key(self, key: str) -> bool:
        return _ahk.send_key(key)

    def _send_scroll(self, direction: str) -> bool:
        return _ahk.send_scroll(1, direction)

    def _to_screen_coords(self, rect: dict, x: int, y: int) -> tuple[int, int]:
        return (int(round(rect["x"] + x)), int(round(rect["y"] + y)))

    def _can_perform_action(self, rule: Rule) -> bool:
        if self.check_runaway_rule(rule.id):
            self._rule_auto_disabled.add(rule.id)
            self._auto_disabled_at[rule.id] = time.monotonic()
            rule.enabled = False
            msg = f"規則「{rule.name}」觸發過於頻繁，已自動停用"
            if self.on_warning:
                self.on_warning(msg)
            return False
        return self._perf.check_rate_limit()

    def _mark_rule_triggered(
        self, rule: Rule, matched_text: str = "", screen_x: int = 0, screen_y: int = 0
    ) -> None:
        rule.trigger_count += 1
        rule.last_trigger_time = time.monotonic()

        for s in rule.steps:
            if s.type == "detect":
                mt = s.params.get("max_triggers", -1)
                if 0 < mt <= rule.trigger_count:
                    rule.enabled = False
                break

        self._emit_trigger(self._make_trigger_log(rule, matched_text, screen_x, screen_y))

        with self._rules_lock:
            self._rules_dirty = True

    def _should_process_static_frame(self) -> bool:
        with self._rules_lock:
            if self._pending_forced_triggers:
                return True
            now = time.monotonic()
            for rule in self._rules:
                if not rule.enabled or rule.id in self._rule_auto_disabled:
                    continue
                for step in rule.steps:
                    if step.type != "detect":
                        continue
                    if step.params.get("trigger_mode", "once") != "repeat":
                        continue
                    cooldown = step.params.get("cooldown_ms", 2000) / 1000.0
                    if now - rule.last_trigger_time >= cooldown:
                        return True
        return False

    def _ocr_region(self, img: np.ndarray, roi: dict | None) -> list:
        if roi is None or all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h")):
            return recognize(img, preprocess=False, max_side_len=0, min_confidence=0.25)
        h, w = img.shape[:2]
        x1 = max(0, roi["x"])
        y1 = max(0, roi["y"])
        x2 = min(w, roi["x"] + roi["w"])
        y2 = min(h, roi["y"] + roi["h"])
        if x2 <= x1 or y2 <= y1:
            return []
        roi_img = img[y1:y2, x1:x2]
        results = recognize(roi_img, preprocess=False, max_side_len=0, min_confidence=0.25)
        for r in results:
            r.x += x1
            r.y += y1
            r.center_x = r.x + r.w // 2
            r.center_y = r.y + r.h // 2
        return results

    def _make_trigger_log(self, rule, text: str, x: int, y: int) -> TriggerLog:
        return TriggerLog(
            timestamp=time.time(),
            rule_id=rule.id,
            rule_name=rule.name,
            matched_text=text,
            click_x=x,
            click_y=y,
        )

    def _emit_trigger(self, log: TriggerLog):
        with self._logs_lock:
            self._logs.append(log)
        if self.on_trigger:
            self.on_trigger(log)

    # ── Step handlers ──

    def _handle_detect(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        text = params.get("text", "")
        if not text.strip():
            return StepResult("stop")

        elapsed_ms = (time.monotonic() - rule.last_trigger_time) * 1000
        if elapsed_ms < params.get("cooldown_ms", 2000):
            return StepResult("stop")

        if (
            not ctx.forced
            and params.get("trigger_mode", "once") == "once"
            and rule.trigger_count > 0
        ):
            return StepResult("stop")

        mt = params.get("max_triggers", -1)
        if mt > 0 and rule.trigger_count >= mt:
            return StepResult("stop")

        roi = params.get("roi")
        results = self._ocr_region(ctx.img, roi)
        if not results:
            return self._handle_on_fail(params, ctx, rule)

        matches = find_text(
            results, text, params.get("match_mode", "fuzzy"), params.get("fuzzy_threshold", 0.8)
        )
        if not matches:
            return self._handle_on_fail(params, ctx, rule)

        ctx.matched_text = matches[0]
        return StepResult("continue")

    def _handle_on_fail(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        raw = params.get("on_fail", "stop")
        if isinstance(raw, str):
            action = raw
            retries = 5
            retry_delay_ms = 1000
            fail_key = ""
            jump_rule_id = ""
        elif isinstance(raw, dict):
            action = raw.get("action", "stop")
            try:
                retries = int(raw.get("retries", 5))
                retry_delay_ms = int(raw.get("retry_delay_ms", 1000))
            except (ValueError, TypeError):
                retries = 5
                retry_delay_ms = 1000
            fail_key = str(raw.get("key", ""))
            jump_rule_id = str(raw.get("jump_rule_id", ""))
        else:
            action = "stop"

        if action == "continue":
            return StepResult("continue")

        if action == "retry":
            text = params.get("text", "")
            for attempt in range(retries):
                if self._stop_event.is_set():
                    return StepResult("stop")
                interrupted = self._stop_event.wait(timeout=retry_delay_ms / 1000.0)
                if interrupted:
                    return StepResult("stop")
                img = capture(self._window_title)
                if img is None:
                    img = capture_window_full(self._window_title)
                if img is None:
                    continue
                roi = params.get("roi")
                results = self._ocr_region(img, roi)
                if results:
                    matches = find_text(
                        results,
                        text,
                        params.get("match_mode", "fuzzy"),
                        params.get("fuzzy_threshold", 0.8),
                    )
                    if matches:
                        ctx.matched_text = matches[0]
                        ctx.img = img
                        return StepResult("continue")
            return StepResult("stop")

        if action == "jump":
            if jump_rule_id:
                if jump_rule_id in self._cycle_visited and jump_rule_id != rule.id:
                    if self._verbose:
                        self._log(f"on_fail 跳轉循環偵測，略過「{rule.name}」→「{jump_rule_id}」")
                elif len(self._pending_forced_triggers) >= _MAX_PENDING_TRIGGERS:
                    if self._verbose:
                        self._log(
                            f"跳轉佇列已滿，略過 on_fail 跳轉「{rule.name}」→「{jump_rule_id}」"
                        )
                else:
                    with self._rules_lock:
                        self._pending_forced_triggers.add(jump_rule_id)
            return StepResult("stop")

        if action == "retry_from":
            if not isinstance(raw, dict):
                return StepResult("stop")
            steps = rule.steps
            target = max(0, min(int(raw.get("step_index", 0)), len(steps) - 1))
            return StepResult(
                "retry_from",
                data={
                    "step_index": target,
                    "retries": retries,
                    "retry_delay_ms": retry_delay_ms,
                },
            )

        if action == "key":
            if fail_key:
                activate_window(self._window_title)
                self._send_key(fail_key)
            return StepResult("continue")

        return StepResult("stop")

    def _handle_click(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        target = params.get("target", "text_center")
        off = params.get("random_offset", 0)
        dx = random.randint(-off, off) if off else 0
        dy = random.randint(-off, off) if off else 0

        if target == "text_center":
            if ctx.matched_text is None:
                return StepResult("stop")
            cx = ctx.matched_text.center_x + dx
            cy = ctx.matched_text.center_y + dy
            matched_text = ctx.matched_text.text
        elif target == "custom":
            cx = params.get("x", 0) + dx
            cy = params.get("y", 0) + dy
            matched_text = ""
        elif target == "click_text":
            click_text = params.get("text", "")
            if not click_text:
                return StepResult("stop")
            results = self._ocr_region(ctx.img, None)
            clk_matches = find_text(results, click_text, "contains", 0.8)
            if not clk_matches:
                return StepResult("stop")
            cx = clk_matches[0].center_x + dx
            cy = clk_matches[0].center_y + dy
            matched_text = clk_matches[0].text
        else:
            return StepResult("stop")

        if not self._can_perform_action(rule):
            return StepResult("stop")

        button = params.get("button", "left")
        sx, sy = self._to_screen_coords(ctx.rect, cx, cy)

        activate_window(self._window_title)

        ok = self._send_click(sx, sy, button)
        if ok:
            self._perf.record_click()
            self._mark_rule_triggered(rule, matched_text, sx, sy)

        return StepResult("continue")

    def _handle_key(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        key = params.get("key", "")
        if not key:
            return StepResult("stop")

        if not self._can_perform_action(rule):
            return StepResult("stop")

        activate_window(self._window_title)

        hold_ms = params.get("hold_ms", 0)
        if hold_ms > 0:
            ok = _ahk.send_hold_key(key, hold_ms)
        else:
            ok = self._send_key(key)
        if ok:
            self._perf.record_click()
            self._mark_rule_triggered(rule)

        return StepResult("continue")

    def _handle_drag(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        target = params.get("target", "text_center")
        if target == "text_center":
            if ctx.matched_text is None:
                return StepResult("stop")
            sx = ctx.matched_text.center_x
            sy = ctx.matched_text.center_y
        elif target == "custom":
            sx = params.get("x", 0)
            sy = params.get("y", 0)
        elif target == "click_text":
            click_text = params.get("text", "")
            if not click_text:
                return StepResult("stop")
            results = self._ocr_region(ctx.img, None)
            matches = find_text(results, click_text, "contains", 0.8)
            if not matches:
                return StepResult("stop")
            sx = matches[0].center_x
            sy = matches[0].center_y
        else:
            return StepResult("stop")

        if not self._can_perform_action(rule):
            return StepResult("stop")

        dx = params.get("dx", 0)
        dy = params.get("dy", 0)
        button = params.get("button", "left")

        ssx, ssy = self._to_screen_coords(ctx.rect, sx, sy)
        sex, sey = self._to_screen_coords(ctx.rect, sx + dx, sy + dy)

        activate_window(self._window_title)
        ok = _ahk.send_drag(ssx, ssy, sex, sey, button)
        if ok:
            self._perf.record_click()
            self._mark_rule_triggered(rule, "", ssx, ssy)

        return StepResult("continue")

    def _handle_scroll(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        if not self._can_perform_action(rule):
            return StepResult("stop")

        direction = params.get("direction", "WheelDown")
        amount = params.get("amount", 1)
        delay_ms = params.get("delay_ms", 30)

        activate_window(self._window_title)
        for _ in range(amount):
            ok = self._send_scroll(direction)
            if not ok:
                return StepResult("stop")
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

        self._perf.record_click()
        self._mark_rule_triggered(rule)
        return StepResult("continue")

    def _handle_wait(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        ms = params.get("ms", 1000)
        if ms > 0:
            if self._verbose:
                self._log(f"等待 {ms}ms")
            interrupted = self._stop_event.wait(timeout=ms / 1000.0)
            if interrupted:
                return StepResult("stop")
        return StepResult("continue")

    def _handle_wait_rule(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        target_id = params.get("rule_id", "")
        if not target_id:
            return StepResult("continue")

        with self._rules_lock:
            target = next((r for r in self._rules if r.id == target_id), None)

        if target is None:
            return StepResult("stop")

        # ponytail: re-run target's first detect step on current frame, not historical count
        detect_step = next((s for s in target.steps if s.type == "detect"), None)
        if detect_step is None:
            if self._verbose:
                self._log(f"wait_rule「{rule.name}」→「{target.name}」無偵測步驟，略過等待")
            return StepResult("continue")

        p = detect_step.params
        target_text = p.get("text", "")
        if not target_text.strip():
            return StepResult("stop")

        roi = p.get("roi")
        results = self._ocr_region(ctx.img, roi)
        if not results:
            return StepResult("stop")

        matches = find_text(
            results,
            target_text,
            p.get("match_mode", "fuzzy"),
            p.get("fuzzy_threshold", 0.8),
        )
        if not matches:
            return StepResult("stop")

        return StepResult("continue")

    def _execute_inline_action(self, action: dict, ctx: StepContext) -> tuple[bool, int, int]:
        if not self._perf.check_rate_limit():
            return False, 0, 0
        atype = action.get("type", "")
        if atype == "click":
            x = action.get("x", 0)
            y = action.get("y", 0)
            button = action.get("button", "left")
            sx, sy = self._to_screen_coords(ctx.rect, x, y)
            ok = self._send_click(sx, sy, button)
            if ok:
                self._perf.record_click()
            return ok, sx, sy
        elif atype == "key":
            ok = self._send_key(action.get("key", ""))
            if ok:
                self._perf.record_click()
            return ok, 0, 0
        return False, 0, 0

    def _pick_best_from_rounds(
        self, rounds: list[dict], metric_defs: list[dict], primary_idx: int
    ) -> Optional[dict]:
        if not rounds:
            return None
        if primary_idx >= len(metric_defs):
            return rounds[0]
        direction = metric_defs[primary_idx].get("direction", "higher_better")

        def _val(r):
            if primary_idx < len(r["metrics"]) and r["metrics"][primary_idx]["value"] is not None:
                return r["metrics"][primary_idx]["value"]
            return float("-inf") if direction == "higher_better" else float("inf")

        vals = [_val(r) for r in rounds]
        if direction == "higher_better":
            best_val = max(vals)
        else:
            best_val = min(vals)
        candidates = [r for r in rounds if _val(r) == best_val]
        return min(candidates, key=lambda r: r["round"])

    def _handle_collect_rounds(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        rounds_def = params.get("rounds", [])
        if not rounds_def:
            return StepResult("stop")

        metric_defs = rounds_def[0].get("metrics", []) if rounds_def else []
        confirm_action = params.get("confirm_action", {})
        on_all_fail = params.get("on_all_fail", {})

        if not self._can_perform_action(rule):
            return StepResult("stop")

        round_results = []

        for round_idx, rd in enumerate(rounds_def):
            with self._window_lock:
                title = self._window_title

            trigger_action = rd.get("trigger_action", {})
            self._execute_inline_action(trigger_action, ctx)
            time.sleep(0.3)

            round_metrics = []
            all_ok = True
            for midx, m in enumerate(rd.get("metrics", [])):
                value = poll_roi_value(
                    m.get("roi", {}),
                    m.get("pick", "first"),
                    m.get("timeout_ms", 3000),
                    title,
                    self._stop_event,
                )
                threshold = m.get("threshold", 0)
                direction = m.get("direction", "higher_better")
                if value is not None:
                    thr_ok = (
                        value >= threshold if direction == "higher_better" else value <= threshold
                    )
                else:
                    thr_ok = False

                round_metrics.append({"index": midx, "value": value, "threshold_ok": thr_ok})
                if not thr_ok:
                    all_ok = False

            rdata = {"round": round_idx, "metrics": round_metrics, "all_ok": all_ok}
            round_results.append(rdata)

            if self.on_compare_round:
                self.on_compare_round({"rule_id": rule.id, "rule_name": rule.name, **rdata})

        full = [r for r in round_results if r["all_ok"]]
        partial = [
            r
            for r in round_results
            if not r["all_ok"] and r["metrics"] and r["metrics"][0].get("threshold_ok")
        ]
        best = None
        if full:
            best = self._pick_best_from_rounds(
                full, metric_defs, params.get("primary_metric_index", 0)
            )
        elif partial:
            best = self._pick_best_from_rounds(
                partial, metric_defs, params.get("primary_metric_index", 0)
            )

        if best is not None:
            best_def = rounds_def[best["round"]]
            ok, sx, sy = self._execute_inline_action(best_def.get("result_action", {}), ctx)
            ok2, sx2, sy2 = self._execute_inline_action(confirm_action, ctx)
            if ok or ok2:
                self._mark_rule_triggered(rule, "", sx2 or sx, sy2 or sy)
        elif on_all_fail.get("type") == "jump":
            target_id = on_all_fail.get("rule_id", "")
            if target_id:
                if target_id in self._cycle_visited and target_id != rule.id:
                    if self._verbose:
                        self._log(f"偵測到跳轉循環，略過「{rule.name}」→「{target_id}」")
                    if self.on_warning:
                        self.on_warning(f"規則「{rule.name}」跳轉循環已中斷")
                elif len(self._pending_forced_triggers) >= _MAX_PENDING_TRIGGERS:
                    if self._verbose:
                        self._log(f"跳轉佇列已滿，略過「{rule.name}」→「{target_id}」")
                else:
                    with self._rules_lock:
                        self._pending_forced_triggers.add(target_id)
                    msg = f"多輪比較「{rule.name}」無達標輪次 → 跳轉「{target_id}」"
                    if self.on_warning:
                        self.on_warning(msg)
                    elif self._verbose:
                        self._log(msg)
        elif on_all_fail.get("type") == "key":
            ok, sx, sy = self._execute_inline_action(on_all_fail, ctx)
            if ok:
                self._mark_rule_triggered(rule, "", sx, sy)

        return StepResult("stop")

    def _handle_jump(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        target_id = params.get("rule_id", "")
        if target_id:
            if target_id in self._cycle_visited and target_id != rule.id:
                if self._verbose:
                    self._log(f"偵測到跳轉循環，略過「{rule.name}」→「{target_id}」")
                if self.on_warning:
                    self.on_warning(f"規則「{rule.name}」跳轉循環已中斷")
            elif len(self._pending_forced_triggers) >= _MAX_PENDING_TRIGGERS:
                if self._verbose:
                    self._log(f"跳轉佇列已滿，略過「{rule.name}」→「{target_id}」")
            else:
                with self._rules_lock:
                    self._pending_forced_triggers.add(target_id)
                if self._verbose:
                    self._log(f"規則「{rule.name}」跳轉至「{target_id}」")
        return StepResult("stop")

    def _run_step(self, step, ctx: StepContext, rule: Rule) -> StepResult:
        handlers = {
            "detect": self._handle_detect,
            "click": self._handle_click,
            "key": self._handle_key,
            "wait": self._handle_wait,
            "wait_rule": self._handle_wait_rule,
            "collect_rounds": self._handle_collect_rounds,
            "jump": self._handle_jump,
            "drag": self._handle_drag,
            "scroll": self._handle_scroll,
        }
        handler = handlers.get(step.type)
        if handler is None:
            return StepResult("stop")
        return handler(step.params, ctx, rule)

    def _run_rule(self, rule: Rule, img: np.ndarray, rect: dict, forced: bool = False) -> None:
        ctx = StepContext(img=img, rect=rect, forced=forced)
        steps = rule.steps
        i = 0
        retry_budget: dict[int, int] = {}
        while i < len(steps):
            result = self._run_step(steps[i], ctx, rule)
            if result.action == "stop":
                return
            if result.action == "retry_from":
                target = result.data.get("step_index", 0)
                delay_ms = result.data.get("retry_delay_ms", 1000)
                max_retries = result.data.get("retries", 3)
                budget = retry_budget.get(i, max_retries)
                if budget <= 0:
                    if self._verbose:
                        self._log(f"「{rule.name}」retry_from 重試次數耗盡，放棄")
                    return
                retry_budget[i] = budget - 1
                interrupted = self._stop_event.wait(timeout=delay_ms / 1000.0)
                if interrupted:
                    return
                with self._window_lock:
                    title = self._window_title
                new_img = capture(title)
                if new_img is None:
                    new_img = capture_window_full(title)
                if new_img is not None:
                    ctx.img = new_img
                    new_rect = get_window_rect(title)
                    if new_rect:
                        ctx.rect = new_rect
                ctx.forced = True
                i = target
                continue
            i += 1

    def _process_rules(self, img: np.ndarray, rect: dict) -> None:
        with self._rules_lock:
            rules_snapshot = list(self._rules)
        if not rules_snapshot:
            if self._verbose:
                self._log("無啟用中的規則")
            return

        self._cycle_visited.clear()
        self._process_counter += 1

        for rule in rules_snapshot:
            if not rule.enabled:
                with self._rules_lock:
                    self._pending_forced_triggers.discard(rule.id)
                continue
            with self._rules_lock:
                if rule.id in self._rule_auto_disabled:
                    if (
                        self._auto_disabled_at.get(rule.id, 0) + _AUTO_DISABLE_RECOVERY_SEC
                        < time.monotonic()
                    ):
                        self._rule_auto_disabled.discard(rule.id)
                        self._auto_disabled_at.pop(rule.id, None)
                        rule.enabled = True
                        if self._verbose:
                            self._log(f"規則「{rule.name}」自動恢復啟用")
                    else:
                        continue
            self._cycle_visited.add(rule.id)

            with self._rules_lock:
                if rule.id in self._pending_forced_triggers:
                    self._pending_forced_triggers.discard(rule.id)
                    if self._verbose:
                        self._log(f"強制觸發規則「{rule.name}」")
                    self._run_rule(rule, img, rect, forced=True)
                    continue

            try:
                self._run_rule(rule, img, rect)
            except Exception as e:
                if self._verbose:
                    self._log(f"規則「{rule.name}」處理異常: {e}")
                if self.on_warning:
                    self.on_warning(f"規則「{rule.name}」異常: {e}")

        # 定期清理 orphan pending triggers（不存在於目前規則中的 ID）
        if self._process_counter % 50 == 0:
            with self._rules_lock:
                if self._pending_forced_triggers:
                    valid_ids = {r.id for r in rules_snapshot}
                    orphans = self._pending_forced_triggers - valid_ids
                    if orphans:
                        self._pending_forced_triggers -= orphans
                        if self._verbose:
                            self._log(f"清理 {len(orphans)} 個孤兒跳轉目標")

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

                if self._foreground_only and not is_window_foreground(self._window_hwnd):
                    self._stop_event.wait(0.2)
                    self._perf.record_frame()
                    continue

                t0 = time.monotonic()
                img = capture(self._window_title)
                if img is None:
                    img = capture_window_full(self._window_title)
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
                    if change_ratio < 0.02 and not self._should_process_static_frame():
                        if self._verbose and iteration % 30 == 0:
                            self._log(f"畫面無變化 ({change_ratio:.4f})，跳過 OCR")
                        self._perf.record_frame()
                        self._stop_event.wait(self._interval)
                        continue
                else:
                    self._frame_diff_ratio = 1.0

                if self._verbose and iteration % 30 == 0:
                    self._log(
                        f"視窗位置=({rect['x']},{rect['y']}) 尺寸=({rect['w']}×{rect['h']}) img={img.shape}"
                    )

                t2 = time.monotonic()
                self._process_rules(img, rect)
                t3 = time.monotonic()

                ocr_ms = (t3 - t2) * 1000
                loop_elapsed = (time.monotonic() - loop_start) * 1000
                self._perf.record_frame(ocr_ms=ocr_ms, loop_ms=loop_elapsed)

                self._save_period_counter += 1
                if self._save_period_counter >= 20:
                    self._save_period_counter = 0
                    with self._rules_lock:
                        if self._rules_dirty:
                            save_rules(self._rules, self._rules_path)
                            self._rules_dirty = False

                if loop_elapsed > 2000 and self.on_warning:
                    self.on_warning(
                        f"慢循環: {loop_elapsed:.0f}ms "
                        f"(截圖={(t1 - t0) * 1000:.0f}ms "
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
        with self._rules_lock:
            if self._rules_dirty:
                save_rules(self._rules, self._rules_path)
                self._rules_dirty = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._perf.stop()
        handler = getattr(self._logger, "handler", None)
        if handler:
            handler.close()

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

    @property
    def perf_monitor(self) -> PerformanceMonitor:
        return self._perf

    def emergency_stop(self):
        self._emergency_event.set()
        self._stop_event.set()
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

    @property
    def auto_disabled_rules(self) -> set[str]:
        return self._rule_auto_disabled

    def get_rules_status(self) -> list[dict]:
        with self._rules_lock:
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "enabled": r.enabled,
                    "trigger_count": r.trigger_count,
                    "last_trigger_time": r.last_trigger_time,
                    "cooldown_ms": next(
                        (s.params.get("cooldown_ms", 2000) for s in r.steps if s.type == "detect"),
                        2000,
                    ),
                    "max_triggers": next(
                        (s.params.get("max_triggers", -1) for s in r.steps if s.type == "detect"),
                        -1,
                    ),
                    "auto_disabled": r.id in self._rule_auto_disabled,
                }
                for r in self._rules
            ]

    def check_runaway_rule(self, rule_id: str) -> bool:
        with self._rules_lock:
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
    print("=== Phase 2 Self-Check ===\n")

    # ── Test 1: StepResult dataclass ──
    sr = StepResult("continue")
    assert sr.action == "continue"
    assert sr.rule_id is None
    sr2 = StepResult("jump", "rule_abc")
    assert sr2.action == "jump"
    assert sr2.rule_id == "rule_abc"
    sr3 = StepResult("retry_from", data={"step_index": 0, "retries": 3})
    assert sr3.action == "retry_from"
    assert sr3.data["step_index"] == 0
    assert sr3.data["retries"] == 3
    print("  [OK] StepResult dataclass")

    # ── Test 2: StepContext dataclass ──
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    assert ctx.matched_text is None
    ocr = OcrResult(text="test", x=0, y=0, w=10, h=10, confidence=0.9)
    ctx.matched_text = ocr
    assert ctx.matched_text.text == "test"
    print("  [OK] StepContext dataclass")

    # ── Test 3: _pick_best_from_rounds logic ──
    metric_defs = [
        {
            "direction": "higher_better",
            "threshold": 50,
            "pick": "first",
            "roi": {},
            "timeout_ms": 1000,
        },
        {
            "direction": "lower_better",
            "threshold": 30,
            "pick": "first",
            "roi": {},
            "timeout_ms": 1000,
        },
    ]
    mock_rounds = [
        {
            "round": 0,
            "metrics": [{"value": 60, "threshold_ok": True}, {"value": 20, "threshold_ok": True}],
            "all_ok": True,
        },
        {
            "round": 1,
            "metrics": [{"value": 80, "threshold_ok": True}, {"value": 25, "threshold_ok": True}],
            "all_ok": True,
        },
        {
            "round": 2,
            "metrics": [{"value": 40, "threshold_ok": False}, {"value": 10, "threshold_ok": True}],
            "all_ok": False,
        },
    ]
    ml = MainLoop.__new__(MainLoop)
    ml._rules_path = ""
    ml._window_title = "測試視窗"
    ml._window_hwnd = None
    ml._dpi_scale = 1.0
    ml._interval = 0.5
    ml._rules = []
    ml._rules_lock = threading.RLock()
    ml._window_lock = threading.RLock()
    ml._pending_forced_triggers = set()
    ml._cycle_visited = set()
    ml._process_counter = 0
    ml._logs = deque(maxlen=200)
    ml._logs_lock = threading.Lock()
    ml._rule_trigger_history = defaultdict(lambda: deque(maxlen=100))
    ml._rule_auto_disabled = set()
    ml._rules_dirty = False
    ml._save_period_counter = 0
    ml._tracking_hwnd = None
    ml._verbose = False
    ml._logger = logging.getLogger("main_loop_test")
    ml._logger.setLevel(logging.INFO)
    ml._logger.handlers.clear()
    ml._test_handler = logging.FileHandler(
        Path(__file__).resolve().parent.parent / "logs" / "test.log", encoding="utf-8"
    )
    ml._logger.addHandler(ml._test_handler)
    ml._logger.handler = ml._test_handler
    ml._stop_event = threading.Event()
    ml._pause_event = threading.Event()
    ml._emergency_event = threading.Event()
    ml._perf = _perf.PerformanceMonitor()
    ml.on_trigger = None
    ml.on_error = None
    ml.on_warning = None
    ml.on_info = None
    ml.on_window_lost = None
    ml.on_emergency = None
    ml.on_compare_round = None

    valid_rounds = [r for r in mock_rounds if r["all_ok"]]
    best = ml._pick_best_from_rounds(valid_rounds, metric_defs, 0)
    assert best is not None and best["round"] == 1, "should pick round 1 (highest primary)"
    best2 = ml._pick_best_from_rounds(valid_rounds, metric_defs, 1)
    assert best2 is not None and best2["round"] == 0, (
        "should pick round 0 (lowest secondary, lower_better)"
    )
    empty_best = ml._pick_best_from_rounds([], metric_defs, 0)
    assert empty_best is None
    print("  [OK] _pick_best_from_rounds logic")

    # ── Test 4: _run_step dispatcher coverage ──
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    for hn in ["detect", "click", "key", "wait", "wait_rule", "collect_rounds", "jump"]:
        step = _rule.Step(type=hn, params={})
        result = ml._run_step(step, ctx, test_rule)
        assert isinstance(result, StepResult), f"{hn} should return StepResult"
    # Unknown type → stop
    unknown_step = _rule.Step(type="nonexistent", params={})
    result = ml._run_step(unknown_step, ctx, test_rule)
    assert result.action == "stop", "unknown step type should return stop"
    print("  [OK] _run_step dispatcher covers all types")

    # ── Test 5: _to_screen_coords ──
    sx, sy = ml._to_screen_coords({"x": 100, "y": 200, "w": 800, "h": 600}, 50, 60)
    assert sx == 150 and sy == 260, f"expected (150, 260), got ({sx}, {sy})"
    print("  [OK] _to_screen_coords")

    # ── Test 6: _execute_inline_action ──
    _orig_click = _ahk.send_click
    _orig_key = _ahk.send_key
    called = []

    def _mock_click(x, y, b):
        called.append(("click", x, y, b))
        return True

    def _mock_key(k):
        called.append(("key", k))
        return True

    _ahk.send_click = _mock_click
    _ahk.send_key = _mock_key

    ml._execute_inline_action({"type": "click", "x": 10, "y": 20, "button": "right"}, ctx)
    assert called == [("click", 10, 20, "right")]

    called.clear()
    ml._execute_inline_action({"type": "key", "key": "Space"}, ctx)
    assert called == [("key", "Space")]

    called.clear()
    ml._execute_inline_action({"type": "unknown"}, ctx)
    assert len(called) == 0

    _ahk.send_click = _orig_click
    _ahk.send_key = _orig_key
    print("  [OK] _execute_inline_action")

    # ── Test 7: _handle_wait_rule (live OCR check) ──
    ml._rules = [
        Rule(id="empty_steps", name="無步驟", enabled=True, steps=[], trigger_count=1),
        Rule(
            id="detect_no_match",
            name="不匹配",
            enabled=True,
            steps=[_rule.Step(type="detect", params={"text": "NONEXISTENT"})],
            trigger_count=1,
        ),
    ]
    result = ml._handle_wait_rule({"rule_id": "empty_steps"}, ctx, test_rule)
    assert result.action == "continue", "no detect step should pass (no condition to check)"
    result = ml._handle_wait_rule({"rule_id": "detect_no_match"}, ctx, test_rule)
    assert result.action == "stop", "text not found in current frame should stop"
    result = ml._handle_wait_rule({"rule_id": "nonexistent"}, ctx, test_rule)
    assert result.action == "stop", "nonexistent target should stop"
    result = ml._handle_wait_rule({"rule_id": ""}, ctx, test_rule)
    assert result.action == "continue", "empty rule_id should continue"
    print("  [OK] _handle_wait_rule")

    # ── Test 8: _handle_jump ──
    ml._pending_forced_triggers.clear()
    result = ml._handle_jump({"rule_id": "rule_target"}, ctx, test_rule)
    assert result.action == "stop"
    assert "rule_target" in ml._pending_forced_triggers
    print("  [OK] _handle_jump")

    # ── Test 9: _handle_detect returns stop when text empty ──
    result = ml._handle_detect({"text": "", "roi": None}, ctx, test_rule)
    assert result.action == "stop", "empty text should stop"
    print("  [OK] _handle_detect empty text")

    # ── Test 10: _handle_click missing matched_text ──
    ctx.matched_text = None
    result = ml._handle_click({"target": "text_center"}, ctx, test_rule)
    assert result.action == "stop", "click text_center without matched_text should stop"
    print("  [OK] _handle_click text_center without match")

    # ── Test 11: _handle_on_fail actions ──
    result = ml._handle_on_fail({"on_fail": "stop"}, ctx, test_rule)
    assert result.action == "stop", "on_fail stop should return stop"
    result = ml._handle_on_fail({"on_fail": "continue"}, ctx, test_rule)
    assert result.action == "continue", "on_fail continue should return continue"
    result = ml._handle_on_fail(
        {"on_fail": {"action": "jump", "jump_rule_id": "tgt"}}, ctx, test_rule
    )
    assert result.action == "stop", "on_fail jump should return stop"
    assert "tgt" in ml._pending_forced_triggers, "on_fail jump should enqueue target"
    ml._pending_forced_triggers.clear()
    mock_called = []
    _orig_k = _ahk.send_key
    _ahk.send_key = lambda k: mock_called.append(k) or True
    result = ml._handle_on_fail({"on_fail": {"action": "key", "key": "Escape"}}, ctx, test_rule)
    _ahk.send_key = _orig_k
    assert result.action == "continue", "on_fail key should return continue"
    assert mock_called == ["Escape"], f"on_fail key should send Escape, got {mock_called}"
    print("  [OK] _handle_on_fail")

    ml._test_handler.close()
    (Path(__file__).resolve().parent.parent / "logs" / "test.log").unlink(missing_ok=True)

    print("\n=== All 11 tests passed ===")
