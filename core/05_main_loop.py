import logging
import random
import re
import sys as _sys
import threading
import time
from collections import deque
from dataclasses import dataclass
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
_MAX_CPS = 5
_CPS_WINDOW_SEC = 1.0

list_windows = _screenshot.list_windows
get_window_rect = _screenshot.get_window_rect
get_dpi_scaling_factor = getattr(_screenshot, "get_dpi_scaling_factor", lambda hwnd: 1.0)
capture = _screenshot.capture
capture_window_content = getattr(_screenshot, "capture_window_content", lambda title: None)
activate_window = _screenshot.activate_window
get_window_client_offset = getattr(_screenshot, "get_window_client_offset", lambda title: None)
is_window_foreground = _perf.is_window_foreground
OcrResult = _ocr.OcrResult
recognize = _ocr.recognize
find_text = _ocr.find_text
init_engine = _ocr.init_engine
Rule = _rule.Rule
RuleGroup = _rule.RuleGroup
load_rules = _rule.load_rules
load_groups = _rule.load_groups
save_rules = _rule.save_rules
get_capture_size = _rule.get_capture_size
_tmpl = load_sibling("template_matching", "core/11_template_matching.py")
MatchResult = _tmpl.MatchResult
match_template = _tmpl.match_template
img_to_b64 = _tmpl.img_to_b64


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
            img = capture_window_content(title)
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
    matched_box: Optional[dict] = None
    triggered: bool = False
    step_idx: int = -1


@dataclass
class StepResult:
    action: str  # "continue" | "stop" | "jump_step"
    step_index: int = -1


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
        self._frame_diff_ratio: float = 0.0
        self._has_detect_rules: bool = False
        self._frame_ocr_cache: dict = {}

        self._rule_pointer: int = 0
        self._groups: list[RuleGroup] = load_groups(rules_path)
        self._active_group_ids: list[str] = []
        self._group_queue_idx: int = 0
        self._rule_in_group_ptr: int = 0
        self._rule_map: dict[str, Rule] = {}
        self._group_rounds_completed: dict[str, int] = {}
        self._rules_dirty: bool = False
        self._save_period_counter: int = 0
        self._process_counter: int = 0
        self._match_image_warn_counter: dict[str, int] = {}
        self._fail_since: dict[
            str, float
        ] = {}  # key=f"{rule_id}:{step_idx}" → first-fail monotonic timestamp

        self._tracking_hwnd: Optional[int] = self._window_hwnd
        self._tool_hwnd: Optional[int] = None

        self.on_trigger: Optional[Callable[[TriggerLog], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_warning: Optional[Callable[[str], None]] = None
        self.on_info: Optional[Callable[[str], None]] = None
        self.on_window_lost: Optional[Callable[[], None]] = None
        self.on_emergency: Optional[Callable[[], None]] = None
        self.on_finished: Optional[Callable[[], None]] = None

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
            self._rule_map = {r.id: r for r in self._rules}
            self._groups = load_groups(self._rules_path)
            self._rule_pointer = 0
            self._group_rounds_completed.clear()
            self._update_has_detect()

    def _current_group(self) -> RuleGroup | None:
        if not self._active_group_ids or self._group_queue_idx >= len(self._active_group_ids):
            return None
        gid = self._active_group_ids[self._group_queue_idx]
        return next((g for g in self._groups if g.id == gid), None)

    def _send_click(self, x: int, y: int, button: str) -> bool:
        return _ahk.send_click(x, y, button)

    def _send_key(self, key: str) -> bool:
        return _ahk.send_key(key)

    def _send_scroll(self, direction: str) -> bool:
        return _ahk.send_scroll(1, direction)

    def _to_screen_coords(self, rect: dict, x: int, y: int) -> tuple[int, int]:
        return (int(round(rect["x"] + x)), int(round(rect["y"] + y)))

    def _can_perform_action(self) -> bool:
        return self._perf.check_rate_limit()

    def _emit_trigger_log(
        self, rule: Rule, matched_text: str = "", screen_x: int = 0, screen_y: int = 0
    ) -> None:
        self._emit_trigger(self._make_trigger_log(rule, matched_text, screen_x, screen_y))

        with self._rules_lock:
            self._rules_dirty = True

    def _update_has_detect(self):
        self._has_detect_rules = any(
            r.enabled and any(s.type in ("detect", "match_image") for s in r.steps)
            for r in self._rules
        )

    def _should_process_static_frame(self) -> bool:
        return self._has_detect_rules

    def _ocr_region(self, img: np.ndarray, roi: dict | None) -> list:
        is_full = roi is None or all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        if is_full:
            cache_key = ("__full__",)
        else:
            cache_key = (roi["x"], roi["y"], roi["w"], roi["h"])
        cached = self._frame_ocr_cache.get(cache_key)
        if cached is not None:
            return cached

        if is_full:
            results = recognize(img, preprocess=False, max_side_len=0, min_confidence=0.25)
        else:
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
        self._frame_ocr_cache[cache_key] = results
        return results

    def _resolve_roi(self, roi: dict, rect: dict) -> dict:
        x, y, w, h = roi.get("x", 0), roi.get("y", 0), roi.get("w", 0), roi.get("h", 0)
        if x == 0 and y == 0 and w == 0 and h == 0:
            return roi
        W, H = rect["w"], rect["h"]
        if W <= 0 or H <= 0:
            return roi
        if x <= 1.0 and y <= 1.0 and w <= 1.0 and h <= 1.0:
            if roi.get("roi_coord") == "client":
                chrome = get_window_client_offset(self._window_title) or (0, 0)
                cx, cy = chrome
                client_w = W - cx
                client_h = H - cy
                if client_w > 0 and client_h > 0:
                    result = {
                        "x": int(round(x * client_w)) + cx,
                        "y": int(round(y * client_h)) + cy,
                        "w": int(round(w * client_w)),
                        "h": int(round(h * client_h)),
                    }
                    print(
                        f"[ROI DEBUG] rect=({W},{H}) chrome=({cx},{cy}) ratio=({x:.4f},{y:.4f},{w:.4f},{h:.4f}) → pixel={result}"
                    )
                    return result
            return {
                "x": int(round(x * W)),
                "y": int(round(y * H)),
                "w": int(round(w * W)),
                "h": int(round(h * H)),
            }
        return roi

    def _resolve_point(self, px: float, py: float, rect: dict) -> tuple[int, int]:
        W, H = rect["w"], rect["h"]
        if W <= 0 or H <= 0:
            return int(px), int(py)
        if px <= 1.0 and py <= 1.0:
            return int(round(px * W)), int(round(py * H))
        return int(px), int(py)

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

        roi = self._resolve_roi(params.get("roi", {}), ctx.rect)
        results = self._ocr_region(ctx.img, roi)
        if not results:
            return self._handle_on_fail(params, ctx, rule)

        matches = find_text(
            results, text, params.get("match_mode", "fuzzy"), params.get("fuzzy_threshold", 0.8)
        )
        if not matches:
            return self._handle_on_fail(params, ctx, rule)

        self._fail_since.pop(f"{rule.id}:{ctx.step_idx}", None)
        ctx.matched_text = matches[0]
        return StepResult("continue")

    def _handle_match_image(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        template_data = params.get("template_data", "")
        template_path = params.get("template", "")
        if not template_data.strip() and not template_path.strip():
            return StepResult("stop")

        capture_size = get_capture_size(self._rules_path)
        chrome = get_window_client_offset(self._window_title)
        if chrome:
            current_size = [ctx.rect["w"] - chrome[0], ctx.rect["h"] - chrome[1]]
        else:
            current_size = [ctx.rect["w"], ctx.rect["h"]]
        roi = self._resolve_roi(params.get("roi", {}), ctx.rect)
        roi_is_empty = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        if roi_is_empty and ctx.img.shape[1] > 800:
            warn_key = rule.id
            last = self._match_image_warn_counter.get(warn_key, 0)
            self._match_image_warn_counter[warn_key] = last + 1
            if last % 30 == 0:
                self._log(
                    "⚠ match_image 未設定搜尋區域，大尺寸畫面會嚴重影響效能，建議框選搜尋區域"
                )
                if self.on_warning:
                    self.on_warning(
                        "圖示辨識未設定搜尋區域，效能會嚴重下降，建議在步驟中框選搜尋區域"
                    )
        threshold = params.get("threshold", 0.8)
        match_color = params.get("match_color", False)
        color_tolerance = params.get("color_tolerance", 100)
        results = match_template(
            ctx.img,
            template_path,
            roi,
            threshold,
            template_data=template_data or None,
            capture_size=capture_size,
            current_size=current_size,
            match_color=match_color,
            color_tolerance=color_tolerance,
        )
        if not results:
            return self._handle_on_fail(params, ctx, rule)

        self._fail_since.pop(f"{rule.id}:{ctx.step_idx}", None)
        ctx.matched_text = results[0]
        return StepResult("continue")

    def _handle_compare(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        roi = self._resolve_roi(params.get("roi", {}), ctx.rect)
        results = self._ocr_region(ctx.img, roi)
        combined = " ".join(r.text for r in results)
        pattern = params.get("pattern", r"-?\d+\.?\d*")
        m = re.search(pattern, combined)
        if not m:
            return self._handle_on_fail(params, ctx, rule)
        try:
            num = float(m.group())
        except (ValueError, TypeError):
            return self._handle_on_fail(params, ctx, rule)
        op = params.get("operator", ">=")
        val = params.get("value", 0.0)
        ops = {
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
        }
        if op not in ops:
            return self._handle_on_fail(params, ctx, rule)
        if not ops[op](num, val):
            return self._handle_on_fail(params, ctx, rule)
        self._fail_since.pop(f"{rule.id}:{ctx.step_idx}", None)
        ctx.matched_text = results[0]
        ctx.matched_box = {
            "x": roi.get("x", 0),
            "y": roi.get("y", 0),
            "w": roi.get("w", 0),
            "h": roi.get("h", 0),
            "number": num,
            "text": combined[:64],
        }
        if self._verbose:
            self._log(f"比較：{num} {op} {val} → 成立")
        return StepResult("continue")

    def _handle_on_fail(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        raw = params.get("on_fail", "stop")

        fail_duration = raw.get("fail_duration_sec", 0) if isinstance(raw, dict) else 0
        try:
            fail_duration = float(fail_duration)
        except (TypeError, ValueError):
            fail_duration = 0.0

        if fail_duration > 0:
            key = f"{rule.id}:{ctx.step_idx}"
            now = time.monotonic()
            first_fail = self._fail_since.get(key)
            if first_fail is None:
                self._fail_since[key] = now
                return StepResult("stop")
            if now - first_fail < fail_duration:
                return StepResult("stop")
            self._fail_since.pop(key, None)
            # fail_duration elapsed → fall through to execute the configured action

        if isinstance(raw, dict):
            action = raw.get("action", "stop")
            fail_key = str(raw.get("key", ""))
        elif isinstance(raw, str):
            action = raw
            fail_key = ""
        else:
            action = "stop"
            fail_key = ""

        if action == "key":
            if fail_key:
                activate_window(self._window_title)
                self._send_key(fail_key)
                ctx.triggered = True
            return StepResult("continue")

        if action == "skip":
            try:
                skip_to = int(raw.get("skip_to", 0)) if isinstance(raw, dict) else 0
            except (TypeError, ValueError):
                skip_to = 0
            return StepResult("jump_step", step_index=skip_to)

        if action == "jump":
            rule_id = raw.get("rule_id", "") if isinstance(raw, dict) else ""
            group = self._current_group()
            if group and rule_id in group.rule_ids:
                self._rule_in_group_ptr = group.rule_ids.index(rule_id)
            return StepResult("stop")

        if action == "notify":
            message = raw.get("message", "") if isinstance(raw, dict) else ""
            stop_groups = raw.get("stop_groups", []) if isinstance(raw, dict) else []
            if self.on_warning:
                self.on_warning(f"[通知] {message}" if message else "[通知] 流程已停止")
            group = self._current_group()
            stopped = False
            if stop_groups:
                for gid in stop_groups:
                    if gid in self._active_group_ids:
                        self._active_group_ids.remove(gid)
                if group and group.id not in self._active_group_ids:
                    self._rule_in_group_ptr = 0
                    stopped = True
            else:
                if group:
                    self._active_group_ids.remove(group.id)
                    self._rule_in_group_ptr = 0
                    stopped = True
            if not self._active_group_ids:
                has_bg = any(r.background and r.enabled for r in self._rules)
                if not has_bg:
                    self._stop_event.set()
                return StepResult("stop")
            if not stopped:
                ctx.triggered = True
            return StepResult("stop")

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
            cx, cy = self._resolve_point(params.get("x", 0), params.get("y", 0), ctx.rect)
            cx += dx
            cy += dy
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

        if not self._can_perform_action():
            return StepResult("stop")
        if self._is_tool_foreground():
            return StepResult("stop")

        button = params.get("button", "left")
        sx, sy = self._to_screen_coords(ctx.rect, cx, cy)

        activate_window(self._window_title)

        ok = self._send_click(sx, sy, button)
        if ok:
            self._perf.record_click()
            ctx.triggered = True
            self._emit_trigger_log(rule, matched_text, sx, sy)

        return StepResult("continue")

    def _handle_key(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        key = params.get("key", "")
        if not key:
            return StepResult("stop")

        if not self._can_perform_action():
            return StepResult("stop")
        if self._is_tool_foreground():
            return StepResult("stop")

        activate_window(self._window_title)

        hold_ms = params.get("hold_ms", 0)
        if hold_ms > 0:
            ok = _ahk.send_hold_key(key, hold_ms)
        else:
            ok = self._send_key(key)
        if ok:
            self._perf.record_click()
            ctx.triggered = True
            self._emit_trigger_log(rule)

        return StepResult("continue")

    def _handle_drag(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        target = params.get("target", "text_center")
        if target == "text_center":
            if ctx.matched_text is None:
                return StepResult("stop")
            sx = ctx.matched_text.center_x
            sy = ctx.matched_text.center_y
        elif target == "custom":
            sx, sy = self._resolve_point(params.get("x", 0), params.get("y", 0), ctx.rect)
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

        if not self._can_perform_action():
            return StepResult("stop")
        if self._is_tool_foreground():
            return StepResult("stop")

        dx = params.get("dx", 0)
        dy = params.get("dy", 0)
        button = params.get("button", "left")

        ssx, ssy = self._to_screen_coords(ctx.rect, sx, sy)
        sex, sey = self._to_screen_coords(ctx.rect, sx + dx, sy + dy)

        activate_window(self._window_title)
        ok = _ahk.send_drag(ssx, ssy, sex, sey, button)
        if not ok:
            return StepResult("stop")
        self._perf.record_click()
        ctx.triggered = True
        self._emit_trigger_log(rule, "", ssx, ssy)
        return StepResult("continue")

    def _handle_scroll(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        if not self._can_perform_action():
            return StepResult("stop")
        if self._is_tool_foreground():
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
                if self._stop_event.wait(timeout=delay_ms / 1000.0):
                    return StepResult("stop")

        self._perf.record_click()
        ctx.triggered = True
        self._emit_trigger_log(rule)
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

    def _handle_jump(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        target_id = params.get("rule_id", "")
        if not target_id:
            return StepResult("stop")
        group = self._current_group()
        if group is None or target_id not in group.rule_ids:
            if self._verbose:
                self._log(f"jump 目標「{target_id}」不在當前群組內，忽略")
            return StepResult("stop")
        self._rule_in_group_ptr = group.rule_ids.index(target_id)
        if self._verbose:
            target_name = getattr(self._rule_map.get(target_id), "name", target_id)
            self._log(f"跳轉至規則 「{target_name}」 (group ptr {self._rule_in_group_ptr})")
        return StepResult("stop")

    def _handle_notify(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        msg = params.get("message", "")
        if msg and self.on_warning:
            self.on_warning(msg)
        return StepResult("continue")

    def _run_step(self, step, ctx: StepContext, rule: Rule) -> StepResult:
        handlers = {
            "detect": self._handle_detect,
            "click": self._handle_click,
            "key": self._handle_key,
            "wait": self._handle_wait,
            "jump": self._handle_jump,
            "drag": self._handle_drag,
            "scroll": self._handle_scroll,
            "match_image": self._handle_match_image,
            "compare": self._handle_compare,
            "notify": self._handle_notify,
        }
        handler = handlers.get(step.type)
        if handler is None:
            return StepResult("stop")
        return handler(step.params, ctx, rule)

    def _run_rule(
        self, rule: Rule, img: np.ndarray, rect: dict, ctx: StepContext | None = None
    ) -> None:
        if ctx is None:
            ctx = StepContext(img=img, rect=rect)
        i = 0
        while i < len(rule.steps):
            ctx.step_idx = i
            result = self._run_step(rule.steps[i], ctx, rule)
            if result.action == "stop":
                return
            if result.action == "jump_step":
                idx = result.step_index
                if idx < 0:
                    idx = 0
                if idx >= len(rule.steps):
                    idx = len(rule.steps) - 1
                if idx < 0:
                    return
                i = idx
                continue
            i += 1

    def _process_rules(self, img: np.ndarray, rect: dict) -> None:
        self._frame_ocr_cache.clear()
        with self._rules_lock:
            rules_snapshot = list(self._rules)
        if not rules_snapshot:
            return

        # ponytail: run all background rules each frame; jumps are cancelled
        for rule in rules_snapshot:
            if rule.enabled and rule.background:
                self._process_counter += 1
                saved_ptr = self._rule_pointer
                try:
                    self._run_rule(rule, img, rect)
                except Exception as e:
                    if self._verbose:
                        self._log(f"背景規則「{rule.name}」異常: {e}")
                    if self.on_warning:
                        self.on_warning(f"背景規則「{rule.name}」異常: {e}")
                self._rule_pointer = saved_ptr

        # ── Group-based rule pointer ──
        group = self._current_group()
        if group is None:
            return

        if group.order == "parallel":
            triggered = False
            for rid in group.rule_ids:
                if triggered:
                    break
                r = self._rule_map.get(rid)
                if r is None or not r.enabled:
                    continue
                r_ctx = StepContext(img=img, rect=rect)
                self._process_counter += 1
                try:
                    self._run_rule(r, img, rect, r_ctx)
                except Exception as e:
                    if self._verbose:
                        self._log(f"並行規則「{r.name}」異常: {e}")
                    if self.on_warning:
                        self.on_warning(f"並行規則「{r.name}」異常: {e}")
                if r_ctx.triggered:
                    triggered = True
            if triggered and group.mode == "once":
                self._advance_group_queue()
            return

        if self._rule_in_group_ptr >= len(group.rule_ids):
            self._advance_group_queue()
            return

        rule_id = group.rule_ids[self._rule_in_group_ptr]
        rule = self._rule_map.get(rule_id)
        if rule is None or not rule.enabled:
            self._advance_rule_in_group()
            return

        self._process_counter += 1
        ctx = StepContext(img=img, rect=rect)

        try:
            self._run_rule(rule, img, rect, ctx)
        except Exception as e:
            if self._verbose:
                self._log(f"規則「{rule.name}」處理異常: {e}")
            if self.on_warning:
                self.on_warning(f"規則「{rule.name}」異常: {e}")

        if ctx.triggered:
            self._advance_rule_in_group()

    def _advance_rule_in_group(self):
        group = self._current_group()
        if group is None:
            return
        nxt = self._rule_in_group_ptr + 1
        while nxt < len(group.rule_ids):
            r = self._rule_map.get(group.rule_ids[nxt])
            if r and r.enabled:
                self._rule_in_group_ptr = nxt
                return
            nxt += 1
        self._on_group_complete(group)

    def _on_group_complete(self, group: RuleGroup):
        completed = self._group_rounds_completed.get(group.id, 0) + 1
        self._group_rounds_completed[group.id] = completed
        self._log(f"群組「{group.name}」第 {completed} 輪完成")
        if group.mode == "once":
            self._advance_group_queue()
        elif group.mode == "repeat":
            if completed >= group.repeat_times:
                self._advance_group_queue()
            else:
                self._rule_in_group_ptr = 0
                if group.between_rounds_sec > 0:
                    if self._verbose:
                        self._log(f"每輪間隔 {group.between_rounds_sec}s")
                    self._stop_event.wait(group.between_rounds_sec)
        else:
            self._rule_in_group_ptr = 0

    def _advance_group_queue(self):
        self._group_queue_idx += 1
        self._rule_in_group_ptr = 0
        while self._group_queue_idx < len(self._active_group_ids):
            g = self._current_group()
            if g and g.enabled:
                return
            self._group_queue_idx += 1
        if self._group_queue_idx >= len(self._active_group_ids):
            has_background = any(r.background and r.enabled for r in self._rules)
            if has_background:
                self._log("所有群組執行完畢，常駐監控持續運行中")
            else:
                self._log("所有選中群組執行完畢，停止")
                self._stop_event.set()

    def _loop(self):
        iteration = 0
        try:
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
                        while not self._stop_event.is_set() and not self._emergency_event.is_set():
                            if not self._pause_event.is_set():
                                break
                            rect = get_window_rect(title)
                            if rect is not None:
                                self._pause_event.clear()
                                if self._verbose:
                                    self._log("視窗已重新出現，恢復偵測")
                                break
                            time.sleep(0.5)
                        self._perf.record_frame()
                        continue

                    if self._window_hwnd is None:
                        with self._window_lock:
                            self._window_hwnd = get_window_hwnd_orig(self._window_title)
                    t0 = time.monotonic()
                    img = capture(self._window_title)
                    if img is None:
                        img = capture_window_content(self._window_title)
                    t1 = time.monotonic()
                    if img is None:
                        if self._verbose and iteration % 30 == 0:
                            self._log(f"所有截圖方式皆失敗: {title}")
                        self._perf.record_frame()
                        continue

                    prev = self._prev_frame
                    self._prev_frame = img

                    if prev is not None and prev.shape == img.shape:
                        diff = cv2.absdiff(prev[::8, ::8], img[::8, ::8])
                        change_ratio = np.mean(diff) / 255.0
                        self._frame_diff_ratio = change_ratio
                        if change_ratio < 0.02 and not self._should_process_static_frame():
                            if self._verbose and iteration % 30 == 0:
                                self._log(f"畫面無變化 ({change_ratio:.4f})，跳過 OCR")
                            if iteration % 10 == 0 and self.on_info:
                                self.on_info("畫面靜止，等待變化")
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
        finally:
            if self.on_finished:
                self.on_finished()

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
        with self._rules_lock:
            self._load_rules()

    def set_active_groups(self, group_ids: list[str]):
        self._active_group_ids = group_ids
        self._group_queue_idx = 0
        self._rule_in_group_ptr = 0
        while self._group_queue_idx < len(self._active_group_ids):
            g = self._current_group()
            if g and g.enabled:
                return
            self._group_queue_idx += 1

    def set_window(self, title: str) -> bool:
        with self._window_lock:
            if get_window_rect(title) is None:
                return False
            self._window_title = title
            self._window_hwnd = get_window_hwnd_orig(title)
            self._dpi_scale = get_dpi_scaling_factor(self._window_hwnd)
            self._tracking_hwnd = self._window_hwnd
            return True

    def set_tool_hwnd(self, hwnd: int) -> None:
        self._tool_hwnd = hwnd

    def _is_tool_foreground(self) -> bool:
        if not self._tool_hwnd:
            return False
        try:
            import ctypes

            return ctypes.windll.user32.GetForegroundWindow() == self._tool_hwnd
        except Exception:
            return False

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

    def get_rules_status(self) -> list[dict]:
        with self._rules_lock:
            current_rule_id = None
            group = self._current_group()
            if group and self._rule_in_group_ptr < len(group.rule_ids):
                current_rule_id = group.rule_ids[self._rule_in_group_ptr]
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "enabled": r.enabled,
                    "background": r.background,
                    "pointer": r.id == current_rule_id,
                }
                for r in self._rules
            ]


if __name__ == "__main__":
    print("=== Rule Pointer Self-Check ===\n")

    # ── Test 1: StepResult dataclass ──
    sr = StepResult("continue")
    assert sr.action == "continue"
    assert sr.step_index == -1
    sr2 = StepResult("stop")
    assert sr2.action == "stop"
    sr3 = StepResult("jump_step", step_index=4)
    assert sr3.action == "jump_step"
    assert sr3.step_index == 4
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

    # ── Test 3: _to_screen_coords ──
    ml = MainLoop.__new__(MainLoop)
    ml._rules_path = ""
    ml._window_title = "測試視窗"
    ml._window_hwnd = None
    ml._dpi_scale = 1.0
    ml._interval = 0.5
    ml._rule_pointer = 0
    ml._rules = []
    ml._groups = []
    ml._active_group_ids = []
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._rule_map = {}
    ml._group_rounds_completed = {}
    ml._fail_since = {}
    ml._rules_lock = threading.RLock()
    ml._window_lock = threading.RLock()
    ml._process_counter = 0
    ml._rules_dirty = False
    ml._save_period_counter = 0
    ml._tracking_hwnd = None
    ml._tool_hwnd = None
    ml._verbose = False
    ml._prev_frame = None
    ml._frame_diff_ratio = 0.0
    ml._has_detect_rules = False
    ml._frame_ocr_cache = {}
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
    ml._logs = deque(maxlen=200)
    ml._logs_lock = threading.Lock()
    ml.on_trigger = None
    ml.on_error = None
    ml.on_warning = None
    ml.on_info = None
    ml.on_window_lost = None
    ml.on_emergency = None
    sx, sy = ml._to_screen_coords({"x": 100, "y": 200, "w": 800, "h": 600}, 50, 60)
    assert sx == 150 and sy == 260, f"expected (150, 260), got ({sx}, {sy})"
    print("  [OK] _to_screen_coords")

    # ── Test 4: _run_step dispatcher coverage ──
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    for hn in [
        "detect",
        "click",
        "key",
        "wait",
        "jump",
        "drag",
        "scroll",
        "match_image",
        "compare",
        "notify",
    ]:
        step = _rule.Step(type=hn, params={})
        result = ml._run_step(step, ctx, test_rule)
        assert isinstance(result, StepResult), f"{hn} should return StepResult"
    # Unknown type → stop
    unknown_step = _rule.Step(type="nonexistent", params={})
    result = ml._run_step(unknown_step, ctx, test_rule)
    assert result.action == "stop", "unknown step type should return stop"
    print("  [OK] _run_step dispatcher covers all types")

    # ── Test 5: _handle_jump with group restriction ──
    ml._rules = [
        Rule(id="rule_a", name="A", enabled=True, steps=[]),
        Rule(id="rule_b", name="B", enabled=True, steps=[]),
        Rule(id="rule_c", name="C", enabled=True, steps=[]),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [
        RuleGroup(id="g1", name="G1", rule_ids=["rule_a", "rule_b"]),
    ]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    # jump to rule_b within same group → success
    result = ml._handle_jump({"rule_id": "rule_b"}, ctx, test_rule)
    assert result.action == "stop"
    assert ml._rule_in_group_ptr == 1
    # jump to rule_c outside group → rejected
    ml._rule_in_group_ptr = 0
    result = ml._handle_jump({"rule_id": "rule_c"}, ctx, test_rule)
    assert result.action == "stop"
    assert ml._rule_in_group_ptr == 0, "cross-group jump should be rejected"
    # jump to nonexistent → rejected
    result = ml._handle_jump({"rule_id": "ghost"}, ctx, test_rule)
    assert result.action == "stop"
    assert ml._rule_in_group_ptr == 0
    print("  [OK] _handle_jump with group restriction")

    # ── Test 6: _handle_detect returns stop when text empty ──
    result = ml._handle_detect({"text": "", "roi": None}, ctx, test_rule)
    assert result.action == "stop", "empty text should stop"
    print("  [OK] _handle_detect empty text")

    # ── Test 7: _handle_click missing matched_text ──
    ctx.matched_text = None
    result = ml._handle_click({"target": "text_center"}, ctx, test_rule)
    assert result.action == "stop", "click text_center without matched_text should stop"
    print("  [OK] _handle_click text_center without match")

    # ── Test 8: _handle_on_fail actions ──
    result = ml._handle_on_fail({"on_fail": "stop"}, ctx, test_rule)
    assert result.action == "stop", "on_fail stop should return stop"

    mock_called = []
    _orig_k = _ahk.send_key
    _ahk.send_key = lambda k: mock_called.append(k) or True
    result = ml._handle_on_fail({"on_fail": {"action": "key", "key": "Escape"}}, ctx, test_rule)
    _ahk.send_key = _orig_k
    assert result.action == "continue", "on_fail key should return continue"
    assert mock_called == ["Escape"], f"on_fail key should send Escape, got {mock_called}"
    print("  [OK] _handle_on_fail (stop/key)")

    # ── Test 9: _handle_on_fail notify action ──
    ctx.triggered = False
    ml._stop_event.clear()
    ml._active_group_ids = ["group_A", "group_B", "group_C"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._groups = [
        RuleGroup(id="group_A", name="A", rule_ids=[]),
        RuleGroup(id="group_B", name="B", rule_ids=[]),
        RuleGroup(id="group_C", name="C", rule_ids=[]),
    ]
    notify_result = ml._handle_on_fail(
        {
            "on_fail": {
                "action": "notify",
                "message": "測試通知",
                "stop_groups": ["group_A", "group_B"],
            }
        },
        ctx,
        test_rule,
    )
    assert notify_result.action == "stop", "notify should return stop"
    assert not ctx.triggered, "notify should NOT set triggered when current group is stopped"
    assert "group_A" not in ml._active_group_ids, "group_A should be removed"
    assert "group_B" not in ml._active_group_ids, "group_B should be removed"
    assert "group_C" in ml._active_group_ids, "group_C should remain"
    assert ml._group_queue_idx == 0, "should NOT advance queue, index shift works naturally"
    assert ml._rule_in_group_ptr == 0, "should reset pointer for the new group"
    assert not ml._stop_event.is_set(), "group_C remains, should not stop"
    print("  [OK] _handle_on_fail notify (stop_groups)")

    # ── Test 9b: notify without stop_groups (current group only) ──
    ml._active_group_ids = ["group_X", "group_Y"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._groups = [
        RuleGroup(id="group_X", name="X", rule_ids=[]),
        RuleGroup(id="group_Y", name="Y", rule_ids=[]),
    ]
    ctx.triggered = False
    notify_result = ml._handle_on_fail(
        {"on_fail": {"action": "notify", "message": "單組停止"}}, ctx, test_rule
    )
    assert notify_result.action == "stop"
    assert not ctx.triggered, "should NOT set triggered when current group is removed"
    assert "group_X" not in ml._active_group_ids, "current group should be removed"
    assert "group_Y" in ml._active_group_ids, "other groups remain"
    assert not ml._stop_event.is_set(), "group_Y remains"
    print("  [OK] _handle_on_fail notify (current group only)")

    # ── Test 9c: notify stop_groups does NOT include current group ──
    ml._active_group_ids = ["group_P", "group_Q"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._groups = [
        RuleGroup(id="group_P", name="P", rule_ids=[]),
        RuleGroup(id="group_Q", name="Q", rule_ids=[]),
    ]
    ctx.triggered = False
    notify_result = ml._handle_on_fail(
        {"on_fail": {"action": "notify", "stop_groups": ["group_Q"], "message": "stop Q"}},
        ctx,
        test_rule,
    )
    assert notify_result.action == "stop"
    assert ctx.triggered, "should set triggered when current group is NOT removed"
    assert "group_P" in ml._active_group_ids, "current group P remains"
    assert "group_Q" not in ml._active_group_ids, "group Q removed"
    assert not ml._stop_event.is_set(), "group_P remains"
    print("  [OK] _handle_on_fail notify (current group not stopped)")

    # ── Test 10: _process_rules advances through group ──
    ml._stop_event.clear()
    ml._rules = [
        Rule(
            id="r0",
            name="規則0",
            enabled=True,
            steps=[
                _rule.Step(type="wait", params={"ms": 0}),
            ],
        ),
        Rule(
            id="r1",
            name="規則1",
            enabled=True,
            steps=[
                _rule.Step(type="wait", params={"ms": 0}),
            ],
        ),
        Rule(
            id="r_bg",
            name="背景",
            enabled=True,
            background=True,
            steps=[
                _rule.Step(type="wait", params={"ms": 0}),
            ],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", rule_ids=["r0", "r1"])]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    rect = {"x": 0, "y": 0, "w": 100, "h": 100}
    ml._process_rules(img, rect)
    assert ml._rule_in_group_ptr == 0, (
        f"wait-only rule should NOT advance (trigger=False), got {ml._rule_in_group_ptr}"
    )
    print("  [OK] wait-only rule does not advance without trigger")

    # ── Test 11: disabled rule is skipped via _advance_rule_in_group ──
    ml._rules = [
        Rule(
            id="r0",
            name="規則0",
            enabled=False,
            steps=[
                _rule.Step(type="wait", params={"ms": 0}),
            ],
        ),
        Rule(
            id="r1",
            name="規則1",
            enabled=True,
            steps=[
                _rule.Step(type="wait", params={"ms": 0}),
            ],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", rule_ids=["r0", "r1"])]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    ml._process_rules(img, rect)
    assert ml._rule_in_group_ptr == 1, "should skip disabled r0"
    print("  [OK] _process_rules skips disabled rule")

    # ── Test 12: _should_process_static_frame (group-based) ──
    ml._rules = [
        Rule(
            id="r_detect",
            name="有detect",
            enabled=True,
            steps=[
                _rule.Step(type="detect", params={"text": "hi"}),
            ],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", rule_ids=["r_detect"])]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    ml._update_has_detect()
    assert ml._should_process_static_frame(), "rule with detect should process static frame"

    ml._rules = [
        Rule(
            id="r_no_detect",
            name="無detect",
            enabled=True,
            steps=[
                _rule.Step(type="wait", params={"ms": 100}),
            ],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", rule_ids=["r_no_detect"])]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    ml._update_has_detect()
    assert not ml._should_process_static_frame(), (
        "rule without detect should NOT process static frame"
    )

    ml._rules = [
        Rule(
            id="r_disabled",
            name="禁用",
            enabled=False,
            steps=[
                _rule.Step(type="detect", params={"text": "hi"}),
            ],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", rule_ids=["r_disabled"])]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    ml._update_has_detect()
    assert not ml._should_process_static_frame(), "disabled rule should NOT process static frame"
    print("  [OK] _should_process_static_frame logic (group-based)")

    # ── Test 13: _emit_trigger_log ──
    trigger_events = []
    ml.on_trigger = lambda log: trigger_events.append(log)
    ml.rules_dirty = False
    test_rule.name = "測試觸發"
    ml._emit_trigger_log(test_rule, "matched_text", 100, 200)
    assert len(trigger_events) == 1
    assert trigger_events[0].rule_name == "測試觸發"
    assert trigger_events[0].matched_text == "matched_text"
    print("  [OK] _emit_trigger_log")

    # ── Test 14: _handle_wait interrupt by stop event ──
    interrupted = []
    ml._stop_event.set()
    result = ml._handle_wait({"ms": 10000}, ctx, test_rule)
    ml._stop_event.clear()
    assert result.action == "stop", "wait should be interrupted by stop event"
    print("  [OK] _handle_wait stop-event interrupt")

    # ── Test 15: _handle_match_image ──
    import tempfile as _tf

    import cv2 as _cv2

    _mi_img = np.zeros((100, 100, 3), dtype=np.uint8)
    _cv2.rectangle(_mi_img, (10, 10), (30, 30), (180, 200, 220), -1)
    _cv2.rectangle(_mi_img, (15, 15), (25, 25), (50, 60, 70), -1)
    _mi_tpl = _mi_img[10:31, 10:31].copy()
    _mi_tmp = _tf.NamedTemporaryFile(suffix=".png", delete=False)
    _mi_tmp.close()
    _cv2.imwrite(_mi_tmp.name, _mi_tpl)
    _mi_ctx = StepContext(img=_mi_img, rect={"x": 0, "y": 0, "w": 100, "h": 100})
    result = ml._handle_match_image(
        {"template": _mi_tmp.name, "threshold": 0.5}, _mi_ctx, test_rule
    )
    assert result.action == "continue", f"match_image should continue, got {result.action}"
    assert _mi_ctx.matched_text is not None
    assert _mi_ctx.matched_text.center_x == 10 + 21 // 2
    # no match case
    _blank = np.zeros((100, 100, 3), dtype=np.uint8)
    _blank_ctx = StepContext(img=_blank, rect=_mi_ctx.rect)
    result2 = ml._handle_match_image(
        {"template": _mi_tmp.name, "threshold": 0.8}, _blank_ctx, test_rule
    )
    assert result2.action == "stop", "no match should stop"
    # empty template
    result3 = ml._handle_match_image({"template": ""}, _mi_ctx, test_rule)
    assert result3.action == "stop", "empty template should stop"
    # template_data path (base64)
    _mi_ctx2 = StepContext(img=_mi_img, rect={"x": 0, "y": 0, "w": 100, "h": 100})
    _b64_data = img_to_b64(_mi_tpl)
    result4 = ml._handle_match_image(
        {"template_data": _b64_data, "threshold": 0.5}, _mi_ctx2, test_rule
    )
    assert result4.action == "continue", f"base64 match should continue, got {result4.action}"
    assert _mi_ctx2.matched_text.center_x == 10 + 21 // 2
    # on_fail=skip (no match → jump_step)
    _skip_ctx = StepContext(img=_blank, rect=_mi_ctx.rect)
    result5 = ml._handle_match_image(
        {"template": _mi_tmp.name, "threshold": 0.8, "on_fail": {"action": "skip", "skip_to": 5}},
        _skip_ctx,
        test_rule,
    )
    assert result5.action == "jump_step", f"on_fail skip should jump, got {result5.action}"
    assert result5.step_index == 5
    Path(_mi_tmp.name).unlink(missing_ok=True)
    print("  [OK] _handle_match_image")

    # ── Test 16: _handle_on_fail skip action ──
    _skip_result = ml._handle_on_fail({"on_fail": {"action": "skip", "skip_to": 3}}, ctx, test_rule)
    assert _skip_result.action == "jump_step"
    assert _skip_result.step_index == 3
    _stop_result = ml._handle_on_fail({"on_fail": "stop"}, ctx, test_rule)
    assert _stop_result.action == "stop"
    _key_result = ml._handle_on_fail({"on_fail": {"action": "key", "key": "F5"}}, ctx, test_rule)
    assert _key_result.action == "continue"
    print("  [OK] _handle_on_fail skip")

    # ── Test 17: Single group once mode finishes and stops (via _advance_rule_in_group) ──
    ml._rules = [
        Rule(id="r1", name="R1", enabled=True, steps=[_rule.Step(type="wait", params={"ms": 0})]),
        Rule(id="r2", name="R2", enabled=True, steps=[_rule.Step(type="wait", params={"ms": 0})]),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", mode="once", rule_ids=["r1", "r2"])]
    ml.set_active_groups(["g1"])
    ml._group_rounds_completed.clear()
    ml._stop_event.clear()
    ml._rule_in_group_ptr = 0
    # simulate r1 triggered → advance
    ml._advance_rule_in_group()
    assert ml._rule_in_group_ptr == 1, f"expected ptr 1, got {ml._rule_in_group_ptr}"
    assert not ml._stop_event.is_set()
    # simulate r2 triggered → group complete → advance_group_queue → stop
    ml._advance_rule_in_group()
    assert ml._group_queue_idx == 1, f"expected queue idx 1, got {ml._group_queue_idx}"
    assert ml._stop_event.is_set(), "once mode should stop after group done"
    print("  [OK] Single group once mode stops after completion")

    # ── Test 18: Multiple groups execute sequentially ──
    ml._groups = [
        RuleGroup(id="ga", name="Group A", mode="once", rule_ids=["r1"]),
        RuleGroup(id="gb", name="Group B", mode="once", rule_ids=["r2"]),
    ]
    ml.set_active_groups(["ga", "gb"])
    ml._group_rounds_completed.clear()
    ml._stop_event.clear()
    ml._rule_in_group_ptr = 0
    assert ml._current_group() is not None
    assert ml._current_group().id == "ga"
    # ga done → advance_group_queue → gb
    ml._advance_group_queue()
    assert ml._group_queue_idx == 1, "ga done → should advance to gb"
    assert ml._current_group().id == "gb"
    assert not ml._stop_event.is_set()
    # gb done → advance_group_queue → stop
    ml._advance_group_queue()
    assert ml._group_queue_idx == 2
    assert ml._stop_event.is_set(), "all groups done → stop"
    print("  [OK] Multiple groups execute sequentially")

    # ── Test 19: Jump within same group succeeds ──
    ml._rules = [
        Rule(
            id="j1",
            name="J1",
            enabled=True,
            steps=[
                _rule.Step(type="wait", params={"ms": 0}),
            ],
        ),
        Rule(
            id="j2",
            name="J2",
            enabled=True,
            steps=[
                _rule.Step(type="wait", params={"ms": 0}),
            ],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="gj", name="GJ", rule_ids=["j1", "j2"])]
    ml.set_active_groups(["gj"])
    ml._rule_in_group_ptr = 0
    result = ml._handle_jump({"rule_id": "j2"}, ctx, test_rule)
    assert result.action == "stop"
    assert ml._rule_in_group_ptr == 1, "jump within group should advance ptr"
    print("  [OK] Jump within same group succeeds")

    # ── Test 20: Jump across groups returns stop ──
    ml._rules = [
        Rule(
            id="xa",
            name="XA",
            enabled=True,
            steps=[
                _rule.Step(type="wait", params={"ms": 0}),
            ],
        ),
        Rule(id="xb", name="XB", enabled=True, steps=[]),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [
        RuleGroup(id="gxa", name="GXA", rule_ids=["xa"]),
        RuleGroup(id="gxb", name="GXB", rule_ids=["xb"]),
    ]
    ml.set_active_groups(["gxa"])
    ml._rule_in_group_ptr = 0
    result = ml._handle_jump({"rule_id": "xb"}, ctx, test_rule)
    assert result.action == "stop"
    assert ml._rule_in_group_ptr == 0, "cross-group jump should be rejected"
    print("  [OK] Jump across groups returns stop")

    ml._test_handler.close()
    (Path(__file__).resolve().parent.parent / "logs" / "test.log").unlink(missing_ok=True)

    # ── Test 21: Background rules prevent stop when groups are done ──
    ml._rules = [
        Rule(
            id="bg1",
            name="常駐",
            enabled=True,
            background=True,
            steps=[_rule.Step(type="wait", params={"ms": 0})],
        ),
        Rule(id="r1", name="R1", enabled=True, steps=[_rule.Step(type="wait", params={"ms": 0})]),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", mode="once", rule_ids=["r1"])]
    ml.set_active_groups(["g1"])
    ml._group_rounds_completed.clear()
    ml._stop_event.clear()
    # point to last rule → advance will exhaust group queue
    ml._rule_in_group_ptr = 0
    ml._group_queue_idx = 0
    ml._advance_rule_in_group()
    assert not ml._stop_event.is_set(), "background rule should prevent stop"
    print("  [OK] Background rule prevents stop after group completion")

    # disable background rule, reset, run again → should stop
    ml._rules[0].enabled = False
    ml._groups = [RuleGroup(id="g1", name="G1", mode="once", rule_ids=["r1"])]
    ml.set_active_groups(["g1"])
    ml._group_rounds_completed.clear()
    ml._stop_event.clear()
    ml._rule_in_group_ptr = 0
    ml._group_queue_idx = 0
    ml._advance_rule_in_group()
    assert ml._stop_event.is_set(), "no background → should stop after group done"
    print("  [OK] No background → stops normally")

    # ── Test 22: _resolve_roi ratio conversion ──
    rect = {"w": 1920, "h": 1080}
    # ratio input → pixel output
    r = ml._resolve_roi({"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.3}, rect)
    assert r == {"x": 192, "y": 216, "w": 960, "h": 324}, f"{r}"
    print("  [OK] _resolve_roi ratio → pixels")

    # all zeros → passthrough
    r = ml._resolve_roi({"x": 0, "y": 0, "w": 0, "h": 0}, rect)
    assert r == {"x": 0, "y": 0, "w": 0, "h": 0}
    print("  [OK] _resolve_roi zero → passthrough")

    # old format pixels → passthrough
    r = ml._resolve_roi({"x": 100, "y": 200, "w": 300, "h": 400}, rect)
    assert r == {"x": 100, "y": 200, "w": 300, "h": 400}
    print("  [OK] _resolve_roi absolute pixels → passthrough")

    # ── Test 24: _resolve_point ratio conversion ──
    px, py = ml._resolve_point(0.5, 0.25, rect)
    assert (px, py) == (960, 270), f"{(px, py)}"
    print("  [OK] _resolve_point ratio → pixels")

    # old format pixels → passthrough
    px, py = ml._resolve_point(123, 456, rect)
    assert (px, py) == (123, 456)
    print("  [OK] _resolve_point absolute → passthrough")

    # ── Test 25: fail_duration_sec prevents subsequent step execution ──
    import time as _time25

    import cv2 as _cv225

    _fd25_tpl = np.zeros((20, 20, 3), dtype=np.uint8)
    _cv225.rectangle(_fd25_tpl, (5, 5), (15, 15), (200, 200, 200), -1)
    _fd25_b64 = img_to_b64(_fd25_tpl)

    _fd25_rule = Rule(
        id="rule_fd25",
        name="FD測試",
        enabled=True,
        steps=[
            _rule.Step(
                type="match_image",
                params={
                    "template": "",
                    "template_data": _fd25_b64,
                    "threshold": 0.99,
                    "on_fail": {
                        "action": "notify",
                        "message": "FD timeout expired",
                        "fail_duration_sec": 5.0,
                    },
                },
            ),
            _rule.Step(
                type="detect",
                params={
                    "text": "不該執行",
                    "match_mode": "fuzzy",
                    "on_fail": "stop",
                },
            ),
        ],
    )

    _fd25_blank = np.zeros((100, 100, 3), dtype=np.uint8)
    _fd25_rect = {"x": 0, "y": 0, "w": 100, "h": 100}
    _fd25_ctx = StepContext(img=_fd25_blank, rect=_fd25_rect)

    _fd25_detect_calls = [0]
    _fd25_orig_ocr = ml._ocr_region

    def _fd25_count_ocr(*a, **kw):
        _fd25_detect_calls[0] += 1
        return []

    ml._ocr_region = _fd25_count_ocr

    _fd25_warn_calls = [0]
    _fd25_orig_warn = ml.on_warning

    def _fd25_count_warn(msg):
        _fd25_warn_calls[0] += 1

    ml.on_warning = _fd25_count_warn

    ml._groups = [RuleGroup(id="fd_dummy", name="FD測試群組", rule_ids=["rule_fd25"])]
    ml._fail_since.clear()
    ml._active_group_ids = ["fd_dummy"]
    ml._group_queue_idx = 0
    ml._stop_event.clear()

    _fd25_key = f"{_fd25_rule.id}:0"

    # First run: match_image fails → _handle_on_fail records fail_since, returns stop → rule stops
    ml._run_rule(_fd25_rule, _fd25_blank, _fd25_rect, _fd25_ctx)

    assert _fd25_detect_calls[0] == 0, (
        f"step 1 (detect) should not execute, got {_fd25_detect_calls[0]} calls"
    )
    assert _fd25_key in ml._fail_since, "fail_since should record key on first failure"
    assert not _fd25_ctx.triggered, "triggered should remain False (action not yet executed)"
    print("  [OK] fail_duration_sec: stop on step 0, step 1 skipped")

    # Second run: fast-forward time past fail_duration
    _fd25_ctx2 = StepContext(img=_fd25_blank, rect=_fd25_rect)
    ml._fail_since[_fd25_key] = _time25.monotonic() - 10.0

    ml._run_rule(_fd25_rule, _fd25_blank, _fd25_rect, _fd25_ctx2)

    assert _fd25_key not in ml._fail_since, "fail_since key should be cleared after duration"
    assert _fd25_warn_calls[0] > 0, "notify action should fire after fail_duration elapsed"
    assert "fd_dummy" not in ml._active_group_ids, "群組應被 notify 移出 active"
    assert ml._stop_event.is_set(), "唯一 active group 被清空且無背景規則，loop 應該停止"
    assert not _fd25_ctx2.triggered, "此路徑下 triggered 不應被設 True"

    ml._ocr_region = _fd25_orig_ocr
    ml.on_warning = _fd25_orig_warn
    ml._stop_event.clear()
    ml._active_group_ids = []
    ml._groups = []
    print("  [OK] fail_duration_sec elapsed → on_fail notify fires")

    print("\n=== All 25 tests passed ===")
