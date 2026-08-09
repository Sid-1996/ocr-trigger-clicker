import logging
import os
import random
import re
import sys as _sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _loader import load_sibling  # noqa: E402
from _version import __version__  # noqa: E402
from i18n import T  # noqa: E402

_screenshot = load_sibling("screenshot", "core/01_screenshot.py")
_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_input_mod = load_sibling("pynput_input", "core/03_pynput_input.py")
_bg_input = load_sibling("bg_input", "core/16_bg_input.py")
_rule = load_sibling("rule_engine", "core/04_rule_engine.py")
_perf = load_sibling("performance_monitor", "core/10_performance_monitor.py")
PerformanceMonitor = _perf.PerformanceMonitor
_rule_config = load_sibling("rule_config_controller", "gui/rule_config_controller.py")
RuleConfigController = _rule_config.RuleConfigController
get_window_hwnd_orig = getattr(_screenshot, "get_window_hwnd", lambda title: None)

_MIN_INTERVAL_SEC = 0.1
_MAX_CPS = 5
_CPS_WINDOW_SEC = 1.0

list_windows = _screenshot.list_windows
get_window_rect = _screenshot.get_window_rect
get_dpi_scaling_factor = getattr(_screenshot, "get_dpi_scaling_factor", lambda hwnd: 1.0)
capture = _screenshot.capture
capture_window_content = getattr(_screenshot, "capture_window_content", lambda title: None)
_capture_pipeline = load_sibling("capture_pipeline", "core/17_capture_pipeline.py")
capture_frame = _capture_pipeline.capture_frame
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
_logging_config = load_sibling("logging_config", "core/00_logging_config.py")


def _ensure_main_logger() -> logging.Logger:
    return _logging_config.get_logger("main_loop")


def log_main(msg: str):
    _ensure_main_logger().info(msg)


def crop_roi(img: np.ndarray, roi: dict) -> np.ndarray | None:
    h, w = img.shape[:2]
    x1 = max(0, int(roi["x"]))
    y1 = max(0, int(roi["y"]))
    x2 = min(w, int(roi["x"]) + int(roi["w"]))
    y2 = min(h, int(roi["y"]) + int(roi["h"]))
    if x2 <= x1 or y2 <= y1:
        return None
    return img[y1:y2, x1:x2]


@dataclass
class StepContext:
    img: np.ndarray
    rect: dict
    matched_text: Optional[OcrResult] = None
    matched_box: Optional[dict] = None
    triggered: bool = False
    force_advance: bool = False
    on_fail_fired: bool = False
    step_idx: int = -1
    best_confidence: float = -1.0
    ocr_elapsed_ms: float = 0
    ocr_cache_hit: bool = False
    prematch: Optional[dict] = None


@dataclass
class StepResult:
    action: str  # "continue" | "stop" | "jump_step"
    step_index: int = -1
    detail: str = ""


def _prematch_pure(
    img: np.ndarray,
    template_path: str,
    roi: dict | None,
    threshold: float,
    template_data: str | None,
    capture_size,
    current_size,
    match_color: bool,
    color_tolerance,
):
    """執行緒池純計算函式：只跑 match_template，不碰任何執行個體狀態、不讀檔、
    不呼叫 Win32。capture_size/current_size/roi 皆由主執行緒預算後傳入，避免
    N 次/幀的重複 I/O（變慢元兇）。回傳 match_template(return_best=True) 原始結果。
    """
    return match_template(
        img,
        template_path,
        roi,
        threshold,
        template_data=template_data,
        capture_size=capture_size,
        current_size=current_size,
        match_color=match_color,
        color_tolerance=color_tolerance,
        return_best=True,
    )


class MainLoop:
    def __init__(
        self,
        rules_path: str,
        window_title: str,
        interval_ms: int = 500,
        max_cps: int = 5,
        verbose: bool = True,
        config_path: str = "",
    ):
        self._rules_path = rules_path
        self._window_title = window_title
        self._config_path = config_path
        self._interval = max(interval_ms / 1000.0, _MIN_INTERVAL_SEC)
        self._max_cps = max_cps
        self._verbose = verbose
        self._started_at = 0.0
        self._window_hwnd = get_window_hwnd_orig(window_title)
        self._dpi_scale = get_dpi_scaling_factor(self._window_hwnd)

        self._rules_lock = threading.RLock()
        self._window_lock = threading.RLock()
        self._foreground_only = True
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._emergency_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._prev_frame: Optional[np.ndarray] = None
        self._frame_diff_ratio: float = 0.0
        self._has_detect_rules: bool = False
        self._frame_ocr_cache: dict = {}
        self._ocr_cache_hits: int = 0

        self._rule_pointer: int = 0
        self._groups: list[RuleGroup] = load_groups(rules_path)
        self._active_group_ids: list[str] = []
        self._group_queue_idx: int = 0
        self._rule_in_group_ptr: int = 0
        self._rule_map: dict[str, Rule] = {}
        self._group_rounds_completed: dict[str, int] = {}
        self._process_counter: int = 0
        self._match_image_warn_counter: dict[str, int] = {}
        self._detect_warn_counter: dict[str, int] = {}
        self._slow_loop_warned: bool = False
        self._fail_since: dict[
            str, float
        ] = {}  # key=f"{rule_id}:{step_idx}" → first-fail monotonic timestamp
        self._last_active_rule_id: str | None = None
        self._execution_log: deque = deque(maxlen=10)
        self._last_exec_log: dict[str, tuple] = {}
        self._rule_completed: set[str] = set()
        self._last_completed_log: dict[str, float] = {}
        self._action_log_ts: dict[str, float] = {}
        self._last_frida_err_ts: float = 0.0
        self._FRIDA_ERR_THROTTLE_SEC: float = 30.0

        self._tracking_hwnd: Optional[int] = self._window_hwnd
        self._tool_hwnd: Optional[int] = None

        self.on_error: Optional[Callable[[str], None]] = None
        self.on_warning: Optional[Callable[[str], None]] = None
        self.on_resource_warning: Optional[Callable[[str], None]] = None
        self.on_info: Optional[Callable[[str], None]] = None
        self.on_window_lost: Optional[Callable[[], None]] = None
        self.on_emergency: Optional[Callable[[], None]] = None
        self.on_finished: Optional[Callable[[], None]] = None

        self._rule_config_ctrl = RuleConfigController()

        self._perf = PerformanceMonitor(max_cps=self._max_cps)
        self._perf.on_rate_limit_exceeded = self._on_rate_limit_exceeded
        self._perf.on_cpu_warn = self._on_cpu_warn
        self._perf.on_memory_warn = self._on_memory_warn
        self._perf.start()

        # 平行預算執行緒池：供並行群組平行計算各規則的 match_image 結果。
        # ponytail: 只在此類群組真正需要時才建立，避免背景全部開一條 pool。
        self._prematch_pool: Optional[ThreadPoolExecutor] = None

        self._rules: list[Rule] = []
        self._logger = _ensure_main_logger()
        self._load_rules()
        init_engine()
        log_main(
            f"應用啟動 v{__version__}，目標視窗「{window_title}」，載入 {len(self._rules)} 條規則"
        )

    _ACTION_LOG_WINDOW = 1.0

    def _log(self, msg: str, dedup_key: str | None = None):
        # 滑動窗速率限制：同一 dedup_key（分類）每秒最多一筆，首筆立即印出、窗內重複丟棄，
        # 純丟棄不累計、無 pending 狀態 → 不會有「尾段爆量次數遺失」的 bug。
        if dedup_key is not None:
            now = time.monotonic()
            last = self._action_log_ts.get(dedup_key)
            if last is not None and now - last < self._ACTION_LOG_WINDOW:
                return
            self._action_log_ts[dedup_key] = now
        self._logger.info(msg)

    _DETECT_STEP_TYPES = frozenset({"detect", "compare", "match_image"})

    def _log_exec(
        self,
        rule_name: str,
        step_idx: int,
        step_type: str,
        result: str,
        detail: str = "",
    ):
        if result == "completed":
            now = time.monotonic()
            last = self._last_completed_log.get(rule_name, 0.0)
            if now - last < 1.0:
                return
            self._last_completed_log[rule_name] = now
            key = f"{rule_name}:{step_idx}"
            self._last_exec_log.pop(key, None)
        else:
            key = f"{rule_name}:{step_idx}"
        entry = (result, detail)
        if self._last_exec_log.get(key) == entry:
            return
        self._last_exec_log[key] = entry
        self._execution_log.append(
            {
                "ts": time.strftime("%H:%M:%S"),
                "rule_name": rule_name,
                "step_idx": step_idx,
                "step_type": step_type,
                "result": result,
                "detail": detail,
            }
        )
        self._logger.info(
            "[exec] rule=%s step=%s type=%s result=%s detail=%s",
            rule_name,
            step_idx,
            step_type,
            result,
            detail,
        )

    def get_execution_log(self) -> list[dict]:
        with self._rules_lock:
            return list(self._execution_log)

    def _load_rules(self):
        with self._rules_lock:
            self._rules = load_rules(self._rules_path)
            self._rule_map = {r.id: r for r in self._rules}
            self._groups = load_groups(self._rules_path)
            self._rule_pointer = 0
            self._group_rounds_completed.clear()
            self._match_image_warn_counter.clear()
            self._detect_warn_counter.clear()
            self._fail_since.clear()
            self._last_active_rule_id = None
            self._update_has_detect()

    def _current_group(self) -> RuleGroup | None:
        if not self._active_group_ids or self._group_queue_idx >= len(self._active_group_ids):
            return None
        # ponytail: skip over loop+parallel groups — they run in the preamble
        idx = self._group_queue_idx
        while idx < len(self._active_group_ids):
            gid = self._active_group_ids[idx]
            g = next((g for g in self._groups if g.id == gid), None)
            if g is not None and not (g.mode == "loop" and g.order == "parallel"):
                return g
            idx += 1
        return None

    def _send_click(self, x: int, y: int, button: str, hold_ms: int = 0) -> bool:
        mode = self._rule_config_ctrl.get_setting(self, "interaction_mode")
        if mode and mode != "pynput" and self._window_hwnd:
            _bg_input.set_method(mode)
            import ctypes

            user32 = ctypes.windll.user32
            pt = wintypes.POINT(x, y)
            user32.ScreenToClient(self._window_hwnd, ctypes.byref(pt))
            return _bg_input.click(self._window_hwnd, pt.x, pt.y, button, hold_ms)
        return _input_mod.send_click(x, y, button, hold_ms)

    def _send_key(self, key: str) -> bool:
        mode = self._rule_config_ctrl.get_setting(self, "interaction_mode")
        if mode and mode != "pynput" and self._window_hwnd:
            _bg_input.set_method(mode)
            return _bg_input.send_key(self._window_hwnd, key)
        return _input_mod.send_key(key)

    def _send_scroll(self, direction: str) -> bool:
        mode = self._rule_config_ctrl.get_setting(self, "interaction_mode")
        if mode and mode != "pynput" and self._window_hwnd:
            _bg_input.set_method(mode)
            # 後台 scroll(): 正值 = 上/右，負值 = 下/左（見 bg_input.scroll docstring）
            horizontal = direction in ("WheelLeft", "WheelRight")
            if horizontal:
                amount = 1 if direction == "WheelRight" else -1
            else:
                amount = -1 if direction == "WheelDown" else 1
            return _bg_input.scroll(self._window_hwnd, 0, 0, amount, horizontal)
        return _input_mod.send_scroll(1, direction)

    def _activate_window(self) -> bool:
        """Activate window using the appropriate method based on interaction mode."""
        mode = self._rule_config_ctrl.get_setting(self, "interaction_mode")
        if mode and mode != "pynput":
            return _screenshot.activate_window_bg(self._window_title)
        return _screenshot.activate_window(self._window_title)

    def _to_screen_coords(self, rect: dict, x: int, y: int) -> tuple[int, int]:
        return (int(round(rect["x"] + x)), int(round(rect["y"] + y)))

    def _can_perform_action(self) -> bool:
        return self._perf.check_rate_limit()

    def _update_has_detect(self):
        self._has_detect_rules = any(
            r.enabled and (any(s.type in ("detect", "match_image") for s in r.steps))
            for r in self._rules
        )

    def _should_process_static_frame(self) -> bool:
        return self._has_detect_rules

    def _ocr_region(self, img: np.ndarray, roi: dict | None) -> list:
        is_full = roi is None or all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        if is_full:
            cache_key = ("__full__",)
            cached = self._frame_ocr_cache.get(cache_key)
            if cached is not None:
                self._ocr_cache_hits += 1
                return cached
            results = recognize(img, preprocess=False, max_side_len=0, min_confidence=0.25)
            self._frame_ocr_cache[cache_key] = results
            return results

        h, w = img.shape[:2]
        x1 = max(0, int(roi["x"]))
        y1 = max(0, int(roi["y"]))
        x2 = min(w, int(roi["x"]) + int(roi["w"]))
        y2 = min(h, int(roi["y"]) + int(roi["h"]))
        if x2 <= x1 or y2 <= y1:
            return []
        rect = (x1, y1, x2 - x1, y2 - y1)

        cached = self._frame_ocr_cache.get(rect)
        if cached is not None:
            self._ocr_cache_hits += 1
            return cached

        # 1) Superset reuse: if an already-OCR'd rect fully contains this one,
        #    reuse its results filtered to this rect (no extra OCR call).
        for key, res in list(self._frame_ocr_cache.items()):
            if not isinstance(key, tuple) or len(key) != 4:
                continue
            cx1, cy1, cw, ch = key
            if cx1 <= x1 and cy1 <= y1 and cx1 + cw >= x2 and cy1 + ch >= y2:
                self._ocr_cache_hits += 1
                return [
                    r
                    for r in res
                    if not (r.x + r.w <= x1 or r.y + r.h <= y1 or r.x >= x2 or r.y >= y2)
                ]

        # 2) Overlapping cached rect: expand to the union and OCR the union once,
        #    then filter to this rect. Overlapping small ROIs → one OCR call.
        for key in list(self._frame_ocr_cache.keys()):
            if not isinstance(key, tuple) or len(key) != 4:
                continue
            cx1, cy1, cw, ch = key
            if cx1 < x2 and cy1 < y2 and cx1 + cw > x1 and cy1 + ch > y1:
                ux, uy = min(cx1, x1), min(cy1, y1)
                ux2, uy2 = max(cx1 + cw, x2), max(cy1 + ch, y2)
                urect = (ux, uy, ux2 - ux, uy2 - uy)
                if urect == rect:
                    continue
                uimg = img[uy:uy2, ux:ux2]
                results = recognize(uimg, preprocess=False, max_side_len=0, min_confidence=0.25)
                for r in results:
                    r.x += ux
                    r.y += uy
                    r.center_x = r.x + r.w // 2
                    r.center_y = r.y + r.h // 2
                self._frame_ocr_cache[urect] = results
                return [
                    r
                    for r in results
                    if not (r.x + r.w <= x1 or r.y + r.h <= y1 or r.x >= x2 or r.y >= y2)
                ]

        roi_img = img[y1:y2, x1:x2]
        results = recognize(roi_img, preprocess=False, max_side_len=0, min_confidence=0.25)
        for r in results:
            r.x += x1
            r.y += y1
            r.center_x = r.x + r.w // 2
            r.center_y = r.y + r.h // 2
        self._frame_ocr_cache[rect] = results
        return results

    def _resolve_roi(self, roi: dict, rect: dict, chrome: tuple | None = None) -> dict:
        x, y, w, h = roi.get("x", 0), roi.get("y", 0), roi.get("w", 0), roi.get("h", 0)
        if x == 0 and y == 0 and w == 0 and h == 0:
            return roi
        W, H = rect["w"], rect["h"]
        if W <= 0 or H <= 0:
            return roi
        if x <= 1.0 and y <= 1.0 and w <= 1.0 and h <= 1.0:
            if roi.get("roi_coord") == "client":
                # ponytail: chrome 可由呼叫端預算後傳入，避免平行預算時 N 次重複 Win32 呼叫
                if chrome is None:
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
                    return result
            return {
                "x": int(round(x * W)),
                "y": int(round(y * H)),
                "w": int(round(w * W)),
                "h": int(round(h * H)),
            }
        return roi

    def _resolve_point(
        self, px: float, py: float, rect: dict, roi_coord: str | None = None
    ) -> tuple[int, int]:
        W, H = rect["w"], rect["h"]
        if W <= 0 or H <= 0:
            return int(px), int(py)
        if px <= 1.0 and py <= 1.0:
            if roi_coord == "client":
                chrome = get_window_client_offset(self._window_title) or (0, 0)
                cx, cy = chrome
                client_w = W - cx
                client_h = H - cy
                if client_w > 0 and client_h > 0:
                    return int(round(px * client_w)) + cx, int(round(py * client_h)) + cy
            return int(round(px * W)), int(round(py * H))
        return int(px), int(py)

    # ── Step handlers ──

    def _handle_detect(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        text = params.get("text", "")
        if not text.strip():
            return StepResult("stop", detail=T("exec_log.detail.detect_empty"))

        roi = self._resolve_roi(params.get("roi", {}), ctx.rect)
        roi_is_empty = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        if roi_is_empty and ctx.img.shape[1] > 800:
            last = self._detect_warn_counter.get(rule.id, 0)
            self._detect_warn_counter[rule.id] = last + 1
            if last % 30 == 0:
                self._log("⚠ 偵測文字未設定搜尋區域，大尺寸畫面會嚴重影響效能，建議框選搜尋區域")
                if self.on_warning:
                    self.on_warning(
                        "偵測文字未設定搜尋區域，效能會嚴重下降，建議在步驟中框選搜尋區域"
                    )
        t_ocr = time.monotonic()
        hits_before = self._ocr_cache_hits
        results = self._ocr_region(ctx.img, roi)
        ctx.ocr_cache_hit = self._ocr_cache_hits > hits_before
        if roi_is_empty and ctx.img.shape[1] > 800:
            ctx.ocr_elapsed_ms = (time.monotonic() - t_ocr) * 1000
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
            return StepResult("stop", detail=T("exec_log.detail.template_empty"))

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
        # 若並行群組已為本 step（index 0）平行預算好 match_template，直接消費，
        # 省去重複的找圖計算；步進>0或無預算時一律照舊即時計算。
        # prematch 只對應第 0 步（並行群組預算的結果），非第 0 步或已消費後一律
        # 即時計算，避免後續 match_image 步驟誤用第 0 步的 ROI/範本比對結果。
        if ctx.step_idx == 0 and ctx.prematch and 0 in ctx.prematch:
            results, best_below = ctx.prematch[0]
            ctx.prematch = None
        else:
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
                return_best=True,
            )
            best_below = -1.0
            if isinstance(results, tuple):
                results, best_below = results
        if not results:
            ctx.best_confidence = best_below
            return self._handle_on_fail(params, ctx, rule)

        self._fail_since.pop(f"{rule.id}:{ctx.step_idx}", None)
        ctx.matched_text = results[0]
        return StepResult("continue")

    def _handle_compare(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        roi = self._resolve_roi(params.get("roi", {}), ctx.rect)
        roi_is_empty = all(roi.get(k, 0) == 0 for k in ("x", "y", "w", "h"))
        if roi_is_empty and ctx.img.shape[1] > 800:
            last = self._detect_warn_counter.get(rule.id, 0)
            self._detect_warn_counter[rule.id] = last + 1
            if last % 30 == 0:
                self._log("⚠ 比較數值未設定搜尋區域，大尺寸畫面會嚴重影響效能，建議框選搜尋區域")
                if self.on_warning:
                    self.on_warning(
                        "比較數值未設定搜尋區域，效能會嚴重下降，建議在步驟中框選搜尋區域"
                    )
        t_ocr = time.monotonic()
        hits_before = self._ocr_cache_hits
        results = self._ocr_region(ctx.img, roi)
        ctx.ocr_cache_hit = self._ocr_cache_hits > hits_before
        if roi_is_empty and ctx.img.shape[1] > 800:
            ctx.ocr_elapsed_ms = (time.monotonic() - t_ocr) * 1000
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
        return StepResult("continue")

    def _build_notify_text(self, message: str, rule: Rule, stopped_groups: list[str]) -> str:
        """組 on_fail notify 的通知文字。

        自訂訊息支援 {rule}/{group} 佔位符（單次代換，避免互相污染）；
        空白訊息用 i18n 預設模板，帶入實際停止的群組名稱。
        """
        names = self._group_names_text(stopped_groups)
        if message and message.strip():
            placeholders = {"{rule}": rule.name, "{group}": names}
            pattern = "|".join(re.escape(k) for k in placeholders)
            if pattern:
                message = re.sub(pattern, lambda m: placeholders[m.group(0)], message)
            return message
        if names:
            return T("notify.fail_default", rule=rule.name, group=names)
        return T("notify.fail_default_nostop", rule=rule.name)

    def _group_names_text(self, group_ids: list[str]) -> str:
        """群組 id 列表 → 名稱文字（支援 dict 或 RuleGroup 物件），多個用 i18n 分隔符。"""
        names = []
        for gid in group_ids:
            for g in self._groups:
                g_id = g.get("id", "") if isinstance(g, dict) else g.id
                if g_id == gid:
                    g_name = g.get("name", gid) if isinstance(g, dict) else g.name
                    names.append(g_name)
                    break
            else:
                names.append(gid)
        return T("notify.group_sep").join(names)

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
                self._log(
                    f"規則「{rule.name}」步驟{ctx.step_idx} 失敗，進入 {fail_duration}s 容忍期"
                )
                return StepResult("stop", detail=T("exec_log.detail.tolerance"))
            if now - first_fail < fail_duration:
                return StepResult("stop", detail=T("exec_log.detail.tolerance"))
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
                self._activate_window()
                self._send_key(fail_key)
                ctx.triggered = True
                ctx.on_fail_fired = True
                self._log(f"規則「{rule.name}」步驟{ctx.step_idx} 失敗 → 使用「{fail_key}」")
            return StepResult("continue")

        if action == "skip":
            try:
                skip_to = int(raw.get("skip_to", 0)) if isinstance(raw, dict) else 0
            except (TypeError, ValueError):
                skip_to = 0
            self._log(f"規則「{rule.name}」步驟{ctx.step_idx} 失敗 → 跳至步驟 {skip_to}")
            return StepResult("jump_step", step_index=skip_to)

        if action == "jump":
            rule_id = raw.get("rule_id", "") if isinstance(raw, dict) else ""
            group = self._current_group()
            if group and rule_id in group.rule_ids:
                target_name = getattr(self._rule_map.get(rule_id), "name", rule_id)
                self._log(
                    f"規則「{rule.name}」步驟{ctx.step_idx} 失敗 → 跳轉至規則「{target_name}」"
                )
                self._rule_in_group_ptr = group.rule_ids.index(rule_id)
            return StepResult("stop", detail=T("exec_log.detail.jump_rule"))

        if action == "notify":
            message = raw.get("message", "") if isinstance(raw, dict) else ""
            stop_groups = raw.get("stop_groups", []) if isinstance(raw, dict) else []
            group = self._current_group()
            # 先算出實際會停止的群組，供預設通知文字使用，再移除
            stopped_groups = (
                [gid for gid in stop_groups if gid in self._active_group_ids]
                if stop_groups
                else ([group.id] if group else [])
            )
            if self.on_warning:
                self.on_warning(f"[通知] {self._build_notify_text(message, rule, stopped_groups)}")
            stopped = False
            if stop_groups:
                for gid in stopped_groups:
                    self._active_group_ids.remove(gid)
                if group and group.id not in self._active_group_ids:
                    self._rule_in_group_ptr = 0
                    stopped = True
                self._log(
                    f"規則「{rule.name}」步驟{ctx.step_idx} 失敗 → 通知並停止群組 {stopped_groups}"
                )
            else:
                if group:
                    self._active_group_ids.remove(group.id)
                    self._rule_in_group_ptr = 0
                    stopped = True
                    self._log(
                        f"規則「{rule.name}」步驟{ctx.step_idx} 失敗 → 通知「{message}」，停止當前群組"
                    )
            if not self._active_group_ids:
                has_bg = any(r.background and r.enabled for r in self._rules)
                if not has_bg:
                    self._stop_event.set()
                return StepResult("stop", detail=T("exec_log.detail.notify_stop"))
            if not stopped:
                ctx.triggered = True
            return StepResult("stop", detail=T("exec_log.detail.notify_stop"))

        if action == "advance":
            ctx.force_advance = True
            return StepResult("stop", detail=T("exec_log.detail.force_advance"))

        return StepResult("stop", detail=T("exec_log.detail.fail_stop"))

    def _handle_click(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        target = params.get("target", "text_center")
        off = params.get("random_offset", 0)
        dx = random.randint(-off, off) if off else 0
        dy = random.randint(-off, off) if off else 0

        if target == "text_center":
            if ctx.matched_text is None:
                return StepResult("stop", detail=T("exec_log.detail.no_target"))
            cx = ctx.matched_text.center_x + dx
            cy = ctx.matched_text.center_y + dy
            matched_text = ctx.matched_text.text
        elif target == "custom":
            cx, cy = self._resolve_point(
                params.get("x", 0), params.get("y", 0), ctx.rect, params.get("roi_coord")
            )
            cx += dx
            cy += dy
            matched_text = ""
        elif target == "cursor":
            mode = self._rule_config_ctrl.get_setting(self, "interaction_mode")
            if mode and mode != "pynput" and self._window_hwnd and ctx.rect:
                cx = ctx.rect["w"] // 2
                cy = ctx.rect["h"] // 2
            else:
                import ctypes

                pt = wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                cx, cy = pt.x, pt.y
            dx = dy = 0
            matched_text = ""
        else:
            return StepResult("stop", detail=T("exec_log.detail.unknown_click_target"))

        if not self._can_perform_action():
            return StepResult("stop", detail=T("exec_log.detail.cps_limit"))
        if self._is_tool_foreground():
            return StepResult("stop", detail=T("exec_log.detail.tool_foreground"))

        button = params.get("button", "left")
        if target == "cursor":
            mode = self._rule_config_ctrl.get_setting(self, "interaction_mode")
            if mode and mode != "pynput" and self._window_hwnd and ctx.rect:
                sx, sy = self._to_screen_coords(ctx.rect, cx, cy)
            else:
                sx, sy = cx, cy
        else:
            sx, sy = self._to_screen_coords(ctx.rect, cx, cy)

        self._activate_window()

        ok = self._send_click(sx, sy, button, params.get("hold_ms", 0))
        if ok:
            self._perf.record_click()
            ctx.triggered = True
            self._log(
                f"規則「{rule.name}」點擊 ({sx},{sy}) 匹配「{matched_text}」",
                dedup_key=f"{rule.id}:click",
            )
        elif (
            self._rule_config_ctrl.get_setting(self, "interaction_mode") == "frida"
            and self.on_error
        ):
            err = _bg_input.last_error()
            if err:
                # 30s 節流：後台持續失敗時不讓彈窗洗版
                now = time.monotonic()
                if now - self._last_frida_err_ts > self._FRIDA_ERR_THROTTLE_SEC:
                    self._last_frida_err_ts = now
                    self.on_error(
                        f"後台點擊失敗。請用「OCR 診斷」頁的點擊測試確認後台操控是否正常，"
                        f"或先切到前景模式使用。除錯詳細：{err}"
                    )

        return StepResult("continue")

    def _handle_key(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        key = params.get("key", "")
        if not key:
            return StepResult("stop", detail=T("exec_log.detail.key_empty"))

        if not self._can_perform_action():
            return StepResult("stop", detail=T("exec_log.detail.cps_limit"))
        if self._is_tool_foreground():
            return StepResult("stop", detail=T("exec_log.detail.tool_foreground"))

        self._activate_window()

        hold_ms = params.get("hold_ms", 0)
        if hold_ms > 0:
            mode = self._rule_config_ctrl.get_setting(self, "interaction_mode")
            if mode and mode != "pynput" and self._window_hwnd:
                _bg_input.set_method(mode)
                ok = _bg_input.send_hold_key(self._window_hwnd, key, hold_ms)
            else:
                ok = _input_mod.send_hold_key(key, hold_ms)
        else:
            ok = self._send_key(key)
        if ok:
            self._perf.record_click()
            ctx.triggered = True
            self._log(
                f"規則「{rule.name}」按鍵「{key}」",
                dedup_key=f"{rule.id}:key:{key}",
            )

        return StepResult("continue")

    def _handle_drag(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        target = params.get("target", "text_center")
        if target == "text_center":
            if ctx.matched_text is None:
                return StepResult("stop", detail=T("exec_log.detail.no_target"))
            sx = ctx.matched_text.center_x
            sy = ctx.matched_text.center_y
        elif target == "custom":
            sx, sy = self._resolve_point(
                params.get("x", 0), params.get("y", 0), ctx.rect, params.get("roi_coord")
            )
        else:
            return StepResult("stop", detail=T("exec_log.detail.unknown_drag_target"))

        if not self._can_perform_action():
            return StepResult("stop", detail=T("exec_log.detail.cps_limit"))
        if self._is_tool_foreground():
            return StepResult("stop", detail=T("exec_log.detail.tool_foreground"))

        dx = params.get("dx", 0)
        dy = params.get("dy", 0)
        button = params.get("button", "left")

        ssx, ssy = self._to_screen_coords(ctx.rect, sx, sy)
        sex, sey = self._to_screen_coords(ctx.rect, sx + dx, sy + dy)

        self._activate_window()
        mode = self._rule_config_ctrl.get_setting(self, "interaction_mode")
        if mode and mode != "pynput" and self._window_hwnd:
            _bg_input.set_method(mode)
            import ctypes

            user32 = ctypes.windll.user32
            pt1 = wintypes.POINT(ssx, ssy)
            user32.ScreenToClient(self._window_hwnd, ctypes.byref(pt1))
            pt2 = wintypes.POINT(sex, sey)
            user32.ScreenToClient(self._window_hwnd, ctypes.byref(pt2))
            ok = _bg_input.drag(self._window_hwnd, pt1.x, pt1.y, pt2.x, pt2.y, button)
        else:
            ok = _input_mod.send_drag(ssx, ssy, sex, sey, button)
        if not ok:
            return StepResult("stop", detail=T("exec_log.detail.comms_fail"))
        self._perf.record_click()
        ctx.triggered = True
        self._log(
            f"規則「{rule.name}」拖曳 ({ssx},{ssy})→({sex},{sey})",
            dedup_key=f"{rule.id}:drag",
        )
        return StepResult("continue")

    def _handle_scroll(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        if not self._can_perform_action():
            return StepResult("stop", detail=T("exec_log.detail.cps_limit"))
        if self._is_tool_foreground():
            return StepResult("stop", detail=T("exec_log.detail.tool_foreground"))

        direction = params.get("direction", "WheelDown")
        amount = params.get("amount", 1)
        delay_ms = params.get("delay_ms", 30)

        self._activate_window()
        for _ in range(amount):
            ok = self._send_scroll(direction)
            if not ok:
                return StepResult("stop", detail=T("exec_log.detail.comms_fail"))
            if delay_ms > 0:
                if self._stop_event.wait(timeout=delay_ms / 1000.0):
                    return StepResult("stop", detail=T("exec_log.detail.interrupted"))

        self._perf.record_click()
        ctx.triggered = True
        self._log(
            f"規則「{rule.name}」滾輪 {direction} x{amount}",
            dedup_key=f"{rule.id}:scroll",
        )
        return StepResult("continue")

    def _handle_wait(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        ms = params.get("ms", 500)
        if ms > 0:
            t0 = time.monotonic()
            interrupted = self._stop_event.wait(timeout=ms / 1000.0)
            elapsed = (time.monotonic() - t0) * 1000
            if interrupted:
                self._log(f"規則「{rule.name}」等待中斷（stop_event），經過 {elapsed:.0f}ms")
                return StepResult("stop", detail=T("exec_log.detail.interrupted"))
        return StepResult("continue")

    def _handle_jump(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        target_id = params.get("rule_id", "")
        if not target_id:
            return StepResult("stop", detail=T("exec_log.detail.jump_empty"))
        group = self._current_group()
        if group is None or target_id not in group.rule_ids:
            self._log(f"規則「{rule.name}」jump 目標「{target_id}」不在當前群組內")
            return StepResult("stop", detail=T("exec_log.detail.jump_not_in_group"))
        self._rule_in_group_ptr = group.rule_ids.index(target_id)
        target_name = getattr(self._rule_map.get(target_id), "name", target_id)
        self._log(
            f"規則「{rule.name}」跳轉至「{target_name}」",
            dedup_key=f"{rule.id}:jump",
        )
        return StepResult("stop")

    def _handle_notify(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:
        msg = params.get("message", "")
        if msg:
            self._log(f"規則「{rule.name}」通知：{msg}")
            if self.on_warning:
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
            return StepResult("stop", detail=T("exec_log.detail.unknown_step"))
        return handler(step.params, ctx, rule)

    def _run_rule(
        self,
        rule: Rule,
        img: np.ndarray,
        rect: dict,
        ctx: StepContext | None = None,
        background: bool = False,
    ) -> None:
        if ctx is None:
            ctx = StepContext(img=img, rect=rect)
        i = 0
        while i < len(rule.steps):
            ctx.step_idx = i
            step = rule.steps[i]
            if step.type == "wait":
                ms = step.params.get("ms", 500)
                if not background:
                    self._log_exec(rule.name, i, "wait", "wait", f"{ms}ms")
            result = self._run_step(step, ctx, rule)
            if step.type == "wait" and result.action == "continue":
                if not background:
                    self._log_exec(rule.name, i, "wait", "ok")
                self._rule_completed.discard(rule.id)
            elif result.action == "stop":
                if not background:
                    detail = result.detail
                    if not detail:
                        detail = self._infer_stop_detail(step, ctx)
                    if rule.id in self._rule_completed and step.type in self._DETECT_STEP_TYPES:
                        self._rule_completed.discard(rule.id)
                    else:
                        self._log_exec(rule.name, i, step.type, "stop", detail)
                return
            elif result.action == "jump_step":
                if not background:
                    self._log_exec(
                        rule.name, i, step.type, "jump", f"→ 步驟 {result.step_index + 1}"
                    )
                idx = result.step_index
                if idx < 0:
                    idx = 0
                if idx >= len(rule.steps):
                    idx = len(rule.steps) - 1
                if idx < 0:
                    return
                # 跳轉必須向前（GUI 也只允許向前 skip），否則可能跳轉成環卡死主執行緒
                if idx <= i:
                    if not background:
                        self._log_exec(
                            rule.name,
                            i,
                            step.type,
                            "stop",
                            "跳轉目標無效（需在目前步驟之後），中止",
                        )
                    return
                i = idx
                continue
            else:
                detail = self._build_ok_detail(step, ctx)
                if not background:
                    self._log_exec(rule.name, i, step.type, "ok", detail)
                self._rule_completed.discard(rule.id)
            i += 1

    def _infer_stop_detail(self, step, ctx: StepContext) -> str:
        t = step.type
        if t in ("detect", "compare"):
            return T("exec_log.detail.detect_not_found") if ctx.matched_text is None else ""
        if t == "click":
            target = step.params.get("target", "text_center")
            if target == "text_center" and ctx.matched_text is None:
                return T("exec_log.detail.no_target")
            return ""
        if t == "match_image":
            if ctx.best_confidence >= 0:
                return T(
                    "exec_log.detail.template_miss", confidence=f"{ctx.best_confidence * 100:.0f}"
                )
            return T("exec_log.detail.template_not_found")
        if t in ("scroll", "drag"):
            return T("exec_log.detail.comms_fail")
        if t == "wait":
            return T("exec_log.detail.interrupted")
        return ""

    def _build_ok_detail(self, step, ctx: StepContext) -> str:
        t = step.type
        if t in ("detect", "compare") and ctx.matched_text and hasattr(ctx.matched_text, "text"):
            detail = ctx.matched_text.text[:15]
            if ctx.ocr_cache_hit:
                detail += " (0ms, 共用快取)"
            elif ctx.ocr_elapsed_ms > 0:
                detail += f" ({ctx.ocr_elapsed_ms:.0f}ms)"
            return detail
        if t == "click" and ctx.matched_text and hasattr(ctx.matched_text, "text"):
            return ctx.matched_text.text[:15]
        if t == "key":
            return step.params.get("key", "")
        if t == "match_image" and ctx.matched_text and hasattr(ctx.matched_text, "confidence"):
            return T(
                "exec_log.detail.match_conf", confidence=f"{ctx.matched_text.confidence * 100:.0f}"
            )
        if t == "compare" and ctx.matched_box:
            num = ctx.matched_box.get("number", "")
            detail = str(num) if num != "" else ""
            if ctx.ocr_cache_hit:
                detail += " (0ms, 共用快取)"
            elif ctx.ocr_elapsed_ms > 0:
                detail += f" ({ctx.ocr_elapsed_ms:.0f}ms)"
            return detail
        if t == "scroll":
            dirs = {
                "WheelDown": T("exec_log.dir.down"),
                "WheelUp": T("exec_log.dir.up"),
                "WheelLeft": T("exec_log.dir.left"),
                "WheelRight": T("exec_log.dir.right"),
            }
            direction = step.params.get("direction", "WheelDown")
            amount = step.params.get("amount", 1)
            return T(
                "exec_log.detail.scroll_dir",
                direction=dirs.get(direction, direction),
                amount=amount,
            )
        if t == "drag":
            dx = step.params.get("dx", 0)
            dy = step.params.get("dy", 0)
            return T("exec_log.detail.drag_offset", dx=f"{dx:+d}", dy=f"{dy:+d}")
        if ctx.on_fail_fired:
            on_fail = step.params.get("on_fail", "stop")
            if isinstance(on_fail, dict) and on_fail.get("action") == "key":
                fk = on_fail.get("key", "")
                if fk:
                    _FAIL_NAMES = {
                        "detect": T("exec_log.type.detect"),
                        "compare": T("exec_log.type.compare"),
                        "match_image": T("exec_log.type.match_image"),
                        "click": T("exec_log.type.click"),
                    }
                    return T(
                        "exec_log.detail.fail_use_key",
                        fail_name=_FAIL_NAMES.get(t, T("exec_log.type.step")),
                        key=fk,
                    )
        return ""

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
                bg_ctx = StepContext(img=img, rect=rect)
                try:
                    self._run_rule(rule, img, rect, bg_ctx, background=True)
                except Exception as e:
                    self._logger.exception("背景規則「%s」異常: %s", rule.name, e)
                    if self.on_warning:
                        self.on_warning(f"背景規則「{rule.name}」異常: {e}")
                if bg_ctx.triggered:
                    self._log_exec(rule.name, 0, "background", "triggered")
                self._rule_pointer = saved_ptr

        # ── Loop+parallel groups: run every frame, independent of queue ──
        for g in self._groups:
            if (
                g.enabled
                and g.id in self._active_group_ids
                and g.mode == "loop"
                and g.order == "parallel"
            ):
                self._run_parallel_group(g, img, rect)

        # ── Group-based rule pointer (sequential / once / repeat) ──
        group = self._current_group()
        if group is None:
            return

        if group.order == "parallel":
            self._run_parallel_group(group, img, rect)
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
            self._logger.exception("規則「%s」處理異常: %s", rule.name, e)
            if self.on_warning:
                self.on_warning(f"規則「{rule.name}」異常: {e}")

        if ctx.triggered or ctx.force_advance:
            if ctx.triggered:
                self._rule_completed.add(rule.id)
                self._log_exec(rule.name, -1, "completed", "completed")
            self._last_active_rule_id = rule.id
            self._advance_rule_in_group()

    def _run_parallel_group(self, group: RuleGroup, img: np.ndarray, rect: dict) -> None:
        # 平行預算：收集本群組各規則第一個 match_image step 的參數（主執行緒解析），
        # 把純 match_template 計算丟進執行緒池平行跑，結果以 rule_id 為鍵存入手稿 ctx.prematch。
        # ponytail: 不跳過任何規則、不改執行路徑（warning/log/on_fail 仍由 _run_rule 依序處理），
        # 只把「找圖計算」平行化後由 _handle_match_image 消費——行為完全等價。
        pending: dict[str, object] = {}
        pool = getattr(self, "_prematch_pool", None)
        if pool is not None or len(group.rule_ids) >= 2:
            if pool is None:
                pool = ThreadPoolExecutor(max_workers=min(8, max(1, os.cpu_count() or 1)))
                self._prematch_pool = pool
            # ponytail: 共享預算——capture_size/chrome/current_size 主線程只算一次，
            # 各 worker 不再各自讀檔/呼叫 Win32（否則 N 次/幀的重複 I/O 是變慢元兇）。
            capture_size = get_capture_size(self._rules_path)
            chrome = get_window_client_offset(self._window_title)
            if chrome:
                current_size = [rect["w"] - chrome[0], rect["h"] - chrome[1]]
            else:
                current_size = [rect["w"], rect["h"]]
            for rid in group.rule_ids:
                r = self._rule_map.get(rid)
                if r is None or not r.enabled or not r.steps:
                    continue
                if r.steps[0].type != "match_image":
                    continue
                p = r.steps[0].params
                tdata = p.get("template_data", "")
                tpath = p.get("template", "")
                if not tdata.strip() and not tpath.strip():
                    continue
                roi = self._resolve_roi(p.get("roi", {}), rect, chrome)
                try:
                    pending[rid] = pool.submit(
                        _prematch_pure,
                        img,
                        tpath,
                        roi,
                        p.get("threshold", 0.8),
                        tdata or None,
                        capture_size,
                        current_size,
                        p.get("match_color", False),
                        p.get("color_tolerance", 100),
                    )
                except RuntimeError:
                    # 池已被外部 shutdown：本幀退回循序匹配，不讓主循環掛掉
                    break

        triggered = False
        for rid in group.rule_ids:
            if triggered:
                break
            r = self._rule_map.get(rid)
            if r is None or not r.enabled:
                continue
            r_ctx = StepContext(img=img, rect=rect)
            if rid in pending:
                fut = pending[rid]
                try:
                    r_ctx.prematch = {0: fut.result()}
                except Exception:
                    r_ctx.prematch = None
            self._process_counter += 1
            try:
                self._run_rule(r, img, rect, r_ctx)
            except Exception as e:
                self._logger.exception("並行規則「%s」異常: %s", r.name, e)
                if self.on_warning:
                    self.on_warning(f"並行規則「{r.name}」異常: {e}")
            if r_ctx.triggered:
                self._last_active_rule_id = r.id
                self._rule_completed.add(r.id)
                self._log_exec(r.name, -1, "completed", "completed")
                triggered = True
        if triggered and group.mode == "once":
            self._advance_group_queue()

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
                # 讀取掃描間隔設定（允許即時生效）
                self._interval = max(
                    self._rule_config_ctrl.get_setting(self, "scan_interval_ms") / 1000.0,
                    _MIN_INTERVAL_SEC,
                )
                try:
                    if self._pause_event.is_set():
                        self._stop_event.wait(0.1)
                        self._perf.record_frame()
                        continue

                    with self._window_lock:
                        title = self._window_title
                    rect = get_window_rect(title)
                    if rect is None:
                        log_main(f"視窗「{title}」遺失，自動暫停")
                        if self.on_window_lost:
                            self.on_window_lost()
                        self._pause_event.set()
                        while not self._stop_event.is_set() and not self._emergency_event.is_set():
                            if not self._pause_event.is_set():
                                break
                            rect = get_window_rect(title)
                            if rect is not None:
                                self._pause_event.clear()
                                self._log("視窗已重新出現，恢復偵測")
                                break
                            time.sleep(0.5)
                        self._perf.record_frame()
                        continue

                    if self._window_hwnd is None:
                        with self._window_lock:
                            self._window_hwnd = get_window_hwnd_orig(self._window_title)
                    if (
                        self._foreground_only
                        and self._window_hwnd
                        and not is_window_foreground(self._window_hwnd)
                        and self._rule_config_ctrl.get_setting(self, "interaction_mode")
                        in (None, "pynput")
                    ):
                        self._perf.record_frame()
                        self._stop_event.wait(self._interval)
                        continue
                    t0 = time.monotonic()
                    mode = self._rule_config_ctrl.get_setting(self, "interaction_mode")
                    img = capture_frame(mode, self._window_title, hwnd=self._window_hwnd)
                    t1 = time.monotonic()
                    if img is None:
                        if iteration % 30 == 0:
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
                            if iteration % 30 == 0:
                                self._log(f"畫面無變化 ({change_ratio:.4f})，跳過 OCR")
                            if iteration % 10 == 0 and self.on_info:
                                self.on_info("畫面靜止，等待變化")
                            self._perf.record_frame()
                            self._stop_event.wait(self._interval)
                            continue
                    else:
                        self._frame_diff_ratio = 1.0

                    t2 = time.monotonic()
                    self._process_rules(img, rect)
                    t3 = time.monotonic()

                    ocr_ms = (t3 - t2) * 1000
                    loop_elapsed = (time.monotonic() - loop_start) * 1000
                    self._perf.record_frame(ocr_ms=ocr_ms, loop_ms=loop_elapsed)

                    if loop_elapsed > 2000:
                        if not self._slow_loop_warned:
                            self._slow_loop_warned = True
                            self._log(
                                f"執行循環過慢: {loop_elapsed:.0f}ms (截圖={(t1 - t0) * 1000:.0f}ms OCR={ocr_ms:.0f}ms)"
                            )
                            if self.on_warning:
                                self.on_warning(
                                    f"偵測執行太慢：本次花費 {loop_elapsed:.0f} 毫秒（超過 2 秒），"
                                    "點擊反應會明顯延遲，建議縮小偵測範圍或減少偵測規則"
                                )
                    else:
                        self._slow_loop_warned = False

                except Exception as e:
                    self._logger.exception("主循環異常: %s", e)
                    if self.on_error:
                        self.on_error(f"主循環異常: {e}")

                if self._pause_event.is_set() or self._emergency_event.is_set():
                    continue

                self._stop_event.wait(self._interval)
        finally:
            # ponytail: pool 只在 loop 執行緒使用，由擁有者在此關閉，
            # 避免 stop()（GUI 執行緒）在 loop 仍 submit 時 shutdown 造成競態崩潰。
            if self._prematch_pool is not None:
                self._prematch_pool.shutdown(wait=False)
                self._prematch_pool = None
            if self.on_finished:
                self.on_finished()

    def start(self) -> None:
        self._started_at = time.monotonic()
        log_main(f"循環開始，目標視窗「{self._window_title}」")
        self._execution_log.clear()
        self._last_exec_log.clear()
        self._rule_completed.clear()
        self._last_completed_log.clear()
        self._stop_event.clear()
        self._pause_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        elapsed = time.monotonic() - self._started_at if self._started_at else 0.0
        log_main(
            f"循環停止：執行 {elapsed:.0f} 秒，點擊 {self._perf.get_total_clicks()} 次，"
            f"規則 {len(self._rules)} 條"
        )
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._perf.stop()
        _bg_input.detach()

    def pause(self) -> None:
        log_main("循環暫停")
        self._pause_event.set()

    def resume(self) -> None:
        log_main("循環恢復")
        self._pause_event.clear()

    @property
    def is_running(self) -> bool:
        return (
            self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()
        )

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

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

            # 後台模式（frida）不依賴前景焦點，工具在前景不影響操作，不需此保護
            mode = self._rule_config_ctrl.get_setting(self, "interaction_mode")
            if mode and mode != "pynput":
                return False
            return ctypes.windll.user32.GetForegroundWindow() == self._tool_hwnd
        except Exception:
            return False

    @property
    def perf_monitor(self) -> PerformanceMonitor:
        return self._perf

    def emergency_stop(self):
        log_main("⚠ 緊急停止")
        self._emergency_event.set()
        self._stop_event.set()
        self._pause_event.set()
        _input_mod.send_emergency_stop()
        if self.on_emergency:
            self.on_emergency()

    def _on_rate_limit_exceeded(self):
        self._pause_event.set()
        msg = "全域速率限制違規次數過多，已自動暫停偵測"
        self._log(msg)
        if self.on_error:
            self.on_error(msg)

    def _on_cpu_warn(self, pct: float):
        msg = f"CPU 使用率過高 ({pct:.0f}%)，請注意系統負載"
        self._log(msg)
        if self.on_resource_warning:
            self.on_resource_warning(msg)

    def _on_memory_warn(self, mb: float):
        msg = f"記憶體使用量過高 ({mb:.0f} MB)，請注意系統負載"
        self._log(msg)
        if self.on_resource_warning:
            self.on_resource_warning(msg)

    def get_perf_stats(self) -> dict:
        return self._perf.get_stats()

    def get_rules_status(self) -> list[dict]:
        with self._rules_lock:
            current_rule_id = self._last_active_rule_id
            active_group_ids = set(self._active_group_ids)
            group = self._current_group()
            current_group_id = group.id if group else None
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "enabled": r.enabled,
                    "background": r.background,
                    "pointer": r.id == current_rule_id,
                    "failed": any(k.startswith(f"{r.id}:") for k in self._fail_since),
                    "group_done": (
                        r.id not in (group.rule_ids if group else [])
                        and not r.background
                        and current_group_id is not None
                        and current_group_id not in active_group_ids
                    ),
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
    ml._tracking_hwnd = None
    ml._tool_hwnd = None
    ml._verbose = False
    ml._prev_frame = None
    ml._frame_diff_ratio = 0.0
    ml._has_detect_rules = False
    ml._frame_ocr_cache = {}
    ml._ocr_cache_hits = 0
    ml._execution_log = deque(maxlen=10)
    ml._last_exec_log = {}
    ml._rule_completed = set()
    ml._last_completed_log = {}
    ml._action_log_ts = {}
    ml._match_image_warn_counter = {}
    ml._last_active_rule_id = None
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
    ml.on_error = None
    ml.on_warning = None
    ml.on_info = None
    ml.on_window_lost = None
    ml.on_emergency = None
    ml._rule_config_ctrl = type(
        "FakeRuleConfig",
        (),
        {"get_setting": lambda self, win, key="interaction_mode": "pynput"},
    )()
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
    _orig_k = _input_mod.send_key
    _input_mod.send_key = lambda k: mock_called.append(k) or True  # type: ignore[assignment]
    result = ml._handle_on_fail({"on_fail": {"action": "key", "key": "Escape"}}, ctx, test_rule)
    _input_mod.send_key = _orig_k
    assert result.action == "continue", "on_fail key should return continue"
    assert ctx.on_fail_fired, "on_fail key should set on_fail_fired"
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

    # ── Test 13: _handle_wait interrupt by stop event ──
    interrupted = []
    ml._stop_event.set()
    result = ml._handle_wait({"ms": 10000}, ctx, test_rule)
    ml._stop_event.clear()
    assert result.action == "stop", "wait should be interrupted by stop event"
    print("  [OK] _handle_wait stop-event interrupt")

    # ── Test 14: _handle_match_image ──
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

    # ── Test 15: _handle_on_fail skip action ──
    _skip_result = ml._handle_on_fail({"on_fail": {"action": "skip", "skip_to": 3}}, ctx, test_rule)
    assert _skip_result.action == "jump_step"
    assert _skip_result.step_index == 3
    _stop_result = ml._handle_on_fail({"on_fail": "stop"}, ctx, test_rule)
    assert _stop_result.action == "stop"
    _key_result = ml._handle_on_fail({"on_fail": {"action": "key", "key": "F5"}}, ctx, test_rule)
    assert _key_result.action == "continue"
    print("  [OK] _handle_on_fail skip")

    # ── Test 16: Single group once mode finishes and stops (via _advance_rule_in_group) ──
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

    # ── Test 17: Multiple groups execute sequentially ──
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

    # ── Test 17b: Loop+parallel groups run concurrently ──
    # Both groups have a trigger-on-first-frame detect step and loop+parallel mode.
    # _process_rules must run both groups' rules each frame.
    ml._groups = [
        RuleGroup(id="gp1", name="P1", mode="loop", order="parallel", rule_ids=["ra", "rb"]),
        RuleGroup(id="gp2", name="P2", mode="loop", order="parallel", rule_ids=["rc", "rd"]),
    ]
    ml._rules = [
        Rule(id="ra", name="A", enabled=True, steps=[_rule.Step(type="wait", params={"ms": 0})]),
        Rule(id="rb", name="B", enabled=True, steps=[_rule.Step(type="wait", params={"ms": 0})]),
        Rule(id="rc", name="C", enabled=True, steps=[_rule.Step(type="wait", params={"ms": 0})]),
        Rule(id="rd", name="D", enabled=True, steps=[_rule.Step(type="wait", params={"ms": 0})]),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._active_group_ids = ["gp1", "gp2"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    rect = {"x": 0, "y": 0, "w": 100, "h": 100}
    # Both groups run in one _process_rules call — no crash, both groups remain active
    n_ok = 0
    for _ in range(10):
        ml._process_rules(img, rect)
        n_ok += 1
    assert "gp1" in ml._active_group_ids, "loop+parallel group gp1 must remain active"
    assert "gp2" in ml._active_group_ids, "loop+parallel group gp2 must remain active"
    # Sequential groups after loop+parallel must still work
    ml._groups.append(RuleGroup(id="g_once", name="Once", mode="once", rule_ids=["ra"]))
    ml._active_group_ids = ["gp1", "gp2", "g_once"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._group_rounds_completed.clear()
    ml._process_rules(img, rect)
    # _current_group should skip past loop+parallel groups and point to g_once
    # (loop+parallel groups run in the new preamble, not the queue)
    current = ml._current_group()
    assert current and current.id == "g_once", (
        f"queue should point to first non-loop-parallel group, got {current.id if current else None}"
    )
    print("  [OK] Loop+parallel groups run concurrently with queue groups")

    # ── Test 18: Jump within same group succeeds ──
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

    # ── Test 19: Jump across groups returns stop ──
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

    # ── Test 20: Background rules prevent stop when groups are done ──
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

    # ── Test 21: _resolve_roi ratio conversion ──
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

    # ── Test 22: _resolve_point ratio conversion ──
    px, py = ml._resolve_point(0.5, 0.25, rect)
    assert (px, py) == (960, 270), f"{(px, py)}"
    print("  [OK] _resolve_point ratio → pixels")

    # old format pixels → passthrough
    px, py = ml._resolve_point(123, 456, rect)
    assert (px, py) == (123, 456)
    print("  [OK] _resolve_point absolute → passthrough")

    # ── Test 23: fail_duration_sec prevents subsequent step execution ──
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

    # ── Test 25: on_fail advance: fail_duration → force_advance → ptr advance ──
    _adv_time = time
    _adv_rule_A = Rule(
        id="rule_adv_A",
        name="Advance A",
        enabled=True,
        steps=[
            _rule.Step(
                type="detect",
                params={
                    "text": "GHOST",
                    "on_fail": {"action": "advance", "fail_duration_sec": 1.5},
                },
            ),
        ],
    )
    _adv_rule_B = Rule(
        id="rule_adv_B",
        name="Advance B",
        enabled=True,
        steps=[
            _rule.Step(type="wait", params={"ms": 0}),
        ],
    )
    ml._rules = [_adv_rule_A, _adv_rule_B]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [
        RuleGroup(id="adv_group", name="ADV", rule_ids=["rule_adv_A", "rule_adv_B"], mode="loop")
    ]
    ml._active_group_ids = ["adv_group"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._fail_since.clear()
    ml._stop_event.clear()
    _adv_img = np.zeros((100, 100, 3), dtype=np.uint8)
    _adv_rect = {"x": 0, "y": 0, "w": 100, "h": 100}

    # First run: detect fails → enter tolerance, ptr stays at 0
    ml._ocr_region = lambda img, roi: []
    _adv_ctx = StepContext(img=_adv_img, rect=_adv_rect)
    ml._process_rules(_adv_img, _adv_rect)
    _adv_key = "rule_adv_A:0"
    assert _adv_key in ml._fail_since, "advance should record fail_since key on first failure"
    assert ml._rule_in_group_ptr == 0, "ptr should stay at 0 during tolerance"
    print("  [OK] advance: first failure enters tolerance, ptr unchanged")

    # Fast-forward past fail_duration
    ml._fail_since[_adv_key] = _adv_time.monotonic() - 10.0
    ml._process_rules(_adv_img, _adv_rect)
    assert _adv_key not in ml._fail_since, "advance should clear fail_since after tolerance"
    assert ml._rule_in_group_ptr == 1, (
        f"advance should advance ptr to 1, got {ml._rule_in_group_ptr}"
    )
    print("  [OK] advance: after tolerance, force_advance=True → ptr advances to B")

    # Rule B runs (wait step) → triggered=False → ptr stays at 1 (B still)
    assert ml._rule_in_group_ptr == 1, "B should be current rule"

    # When B completes (mode=loop) → reset to 0
    ml._advance_rule_in_group()
    assert ml._rule_in_group_ptr == 0, "loop mode should reset ptr to 0"
    assert _adv_key not in ml._fail_since, "fail_since should be clean after group reset"
    print("  [OK] advance: group loop reset clears ptr and fail_since")

    # Verify A gets fresh tolerance after reset
    ml._process_rules(_adv_img, _adv_rect)
    assert _adv_key in ml._fail_since, "A should get fresh fail_since after reset"
    assert ml._rule_in_group_ptr == 0, "ptr should stay at 0 for fresh tolerance"
    print("  [OK] advance: A gets fresh tolerance after group loop reset")

    ml._active_group_ids = []
    print("  [OK] advance: full lifecycle verified")

    # ── Test 27: Scroll direction WheelLeft → 左 x3 ──
    _scroll_step = _rule.Step(type="scroll", params={"direction": "WheelLeft", "amount": 3})
    _scroll_ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    _scroll_detail = ml._build_ok_detail(_scroll_step, _scroll_ctx)
    assert _scroll_detail == "左 x3", f"expected '左 x3', got '{_scroll_detail}'"
    print("  [OK] Scroll direction WheelLeft → 左 x3")

    # ── Test 28: Stop suppression — rule not completed → logs ──
    ml._rules = []
    ml._rule_map = {}
    ml._rule_completed.clear()
    ml._last_completed_log.clear()
    ml._execution_log.clear()
    ml._last_exec_log.clear()
    _sr1 = Rule(
        id="sp1", name="sp1", enabled=True, steps=[_rule.Step(type="detect", params={"text": ""})]
    )
    _simg = np.zeros((100, 100, 3), dtype=np.uint8)
    _srect = {"x": 0, "y": 0, "w": 100, "h": 100}
    ml._run_rule(_sr1, _simg, _srect)
    assert len(ml._execution_log) == 1
    assert ml._execution_log[0]["result"] == "stop"
    print("  [OK] Suppression: not completed → stop logged")

    # ── Test 29: Suppression — completed → first stop suppressed ──
    ml._rule_completed.add(_sr1.id)
    ml._execution_log.clear()
    ml._last_exec_log.clear()
    ml._run_rule(_sr1, _simg, _srect)
    assert len(ml._execution_log) == 0, f"expected 0, got {len(ml._execution_log)}"
    print("  [OK] Suppression: completed → first stop suppressed")

    # ── Test 30: Suppression — completed → second stop logged (flag consumed) ──
    ml._run_rule(_sr1, _simg, _srect)
    assert len(ml._execution_log) == 1
    assert ml._execution_log[0]["result"] == "stop"
    print("  [OK] Suppression: completed → second stop logged again")

    # ── Test 30b: _log sliding-window rate limit ──
    class _Probe(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records: list[str] = []

        def emit(self, record):
            self.records.append(record.getMessage())

    ml._action_log_ts = {}
    _probe = _Probe()
    ml._logger.addHandler(_probe)
    try:
        ml._log("動作A", dedup_key="k1")
        ml._log("動作A", dedup_key="k1")
        assert _probe.records == ["動作A"], f"窗內重複應被丟棄, got {_probe.records}"
        ml._action_log_ts["k1"] = time.monotonic() - 10.0
        ml._log("動作A", dedup_key="k1")
        assert _probe.records.count("動作A") == 2, "超窗後應重新印出"
        ml._log("無去重訊息")
        assert _probe.records.count("無去重訊息") == 1, "無 dedup_key 一律印出"
        ml._log("動作B", dedup_key="k2")
        assert _probe.records.count("動作B") == 1, "不同 key 互不干擾"
    finally:
        ml._logger.removeHandler(_probe)
    print("  [OK] _log sliding-window rate limit")

    # ── Test 31: merged-ROI OCR reuse ──
    _ml_ocr = MainLoop.__new__(MainLoop)
    _ml_ocr._frame_ocr_cache = {}
    _ml_ocr._ocr_cache_hits = 0
    _ocalls = {"n": 0}
    _orig_rec = recognize

    def _fake_reco(bx, roi_offset=None, preprocess=False, max_side_len=0, min_confidence=0.25):
        _ocalls["n"] += 1
        hh, ww = bx.shape[:2]
        ox = roi_offset.get("x", 0) if roi_offset else 0
        oy = roi_offset.get("y", 0) if roi_offset else 0
        return [
            OcrResult(
                text="對 話",
                x=ox + ww // 2 - 4,
                y=oy + hh // 2 - 4,
                w=8,
                h=8,
                confidence=0.9,
            )
        ]

    recognize = _fake_reco
    _mimg = np.zeros((400, 400, 3), dtype=np.uint8)

    # nested subset ROI contained in an already-OCR'd larger ROI → single OCR call
    _ra = _ml_ocr._ocr_region(_mimg, {"x": 10, "y": 10, "w": 100, "h": 60})
    _rb = _ml_ocr._ocr_region(_mimg, {"x": 20, "y": 15, "w": 40, "h": 30})
    assert _ocalls["n"] == 1, "contained ROI should reuse one recognize call"
    assert [r.text for r in _ra] == ["對 話"] and [r.text for r in _rb] == ["對 話"]
    print("  [OK] merged nested ROI: single recognize, both hit")

    # disjoint far-apart ROI → separate call each
    _ml_ocr._frame_ocr_cache = {}
    _ocalls["n"] = 0
    _ra = _ml_ocr._ocr_region(_mimg, {"x": 10, "y": 10, "w": 30, "h": 40})
    _rb = _ml_ocr._ocr_region(_mimg, {"x": 300, "y": 200, "w": 30, "h": 40})
    assert _ocalls["n"] == 2, "disjoint ROI must use separate recognize calls"
    print("  [OK] disjoint ROI: separate recognize calls")

    # overlapping-but-not-contained ROI → union expansion, cluster still low-call
    _ml_ocr._frame_ocr_cache = {}
    _ocalls["n"] = 0
    _ra = _ml_ocr._ocr_region(_mimg, {"x": 10, "y": 10, "w": 30, "h": 30})
    _rb = _ml_ocr._ocr_region(_mimg, {"x": 25, "y": 25, "w": 30, "h": 30})
    _rc = _ml_ocr._ocr_region(_mimg, {"x": 28, "y": 28, "w": 10, "h": 10})
    assert _ocalls["n"] <= 3, f"overlapping cluster should stay low-call, got {_ocalls['n']}"
    assert [r.text for r in _rc] == ["對 話"]
    print("  [OK] overlapping cluster: low calls + all rules hit")

    recognize = _orig_rec
    print("  [OK] Test 31 complete")

    print("\n=== All 30 tests passed ===")
