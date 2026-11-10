r"""Phase 3B ??Rule Dry-run Speed Benchmark (READ-ONLY, no formal code changes).

This script only measures; it does not modify formal code, change execution logic,
commit, or push. All timing of formal modules is done via monkeypatch inside this
script only; the formal code itself is untouched.

Usage:
    cd C:\Code play first\ocr-trigger-clicker
    uv run python devtools\benchmarks\phase3b_bench.py

Output:
    - Prints measurement tables (ms) to console
    - Writes devtools\benchmarks\phase3b_bench_results.json (for cross-version comparison)

Scope:
    A. _run_dry_run() core execution time (0/1/3-5/10 steps, OCR-heavy cases;
       real OCR vs mock OCR reported separately)
    B. GUI lifecycle timing (fake window; actual cancel window NOT measured):
       test start -> setVisible(True) call -> worker start -> dry-run end
       -> handler dispatch -> UI restore.
       NOTE: fake window only. Uses a synchronous in-process handler list, NOT a
       real Qt queued connection; paint/click intervals are unmeasurable (N/A).
       No real user-operable cancel window is derived from this part.
    C. Cancel-success probability ESTIMATE (execution time vs assumed human
       reaction time; NOT a user study and NOT a cancel-rate statistic.
       A single in-flight OCR cannot be interrupted by the step-boundary check.)

Timing boundaries (see report section 2): all use time.perf_counter_ns(), unit ms.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import cv2  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from _loader import load_sibling  # noqa: E402

_rc = load_sibling("run_controller", "gui/run_controller.py")
_models = load_sibling("rule_models", "core/rule_models.py")
Rule = _models.Rule
Step = _models.Step
T = _rc.T

_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
recognize_real = _ocr.recognize

IMG_PATH = os.path.join(_ROOT, "tests", "data", "test.png")
RESULTS_PATH = os.path.join(_ROOT, "devtools", "benchmarks", "phase3b_bench_results.json")


def _percentile(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * q / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return float(s[int(k)])
    return s[f] * (c - k) + s[c] * (k - f)


def _stats_ms(ns_samples):
    ms = [n / 1_000_000.0 for n in ns_samples]
    return {
        "min": round(min(ms), 3),
        "avg": round(sum(ms) / len(ms), 3),
        "p50": round(_percentile(ms, 50), 3),
        "p95": round(_percentile(ms, 95), 3),
        "max": round(max(ms), 3),
        "count": len(ms),
    }


class _FakeBtn:
    def __init__(self):
        self.visible = False
        self.enabled = True
        self.text = ""

    def setVisible(self, v):
        self.visible = bool(v)

    def setEnabled(self, v):
        self.enabled = bool(v)

    def setText(self, t):
        self.text = t


class _SignalSlot:
    """只是 _SignalBus 的代稱物件，模仿 pyqtSignal 的 .emit() 介面。"""

    def __init__(self, bus):
        self._bus = bus

    def emit(self, result):
        self._bus.emit(result)


class _SignalBus:
    """行程內同步 handler 清單 —— **不是**真實 Qt Signal/Slot。

    正式程式用 `gui/06_gui_main.py:5053` 的 `pyqtSignal(dict)`（跨執行緒 queued
    connection，事件由 GUI 執行緒的 event loop 分派）。這裡沒有 QObject、
    沒有 event loop、沒有 queued connection：`emit()` 直接在呼叫端執行緒
    同步呼叫 handler。因此：
      - 沒有真實訊息佇列延遲 → signal_latency_ms 僅為環境參考
      - 沒有真實輸入路由 → cancel_input_operable_ms 為 N/A
    """

    def __init__(self):
        self.emitted = []
        self._handlers = []
        self.test_done_signal = _SignalSlot(self)

    def connect(self, handler):
        self._handlers.append(handler)

    def emit(self, result):
        self.emitted.append(result)
        for h in self._handlers:
            try:
                h(result)
            except Exception:
                pass


class _FakeWin:
    def __init__(self, img):
        self.img = img
        self._window_combo = SimpleNamespace(currentText=lambda: "dummy")
        self._loop = None
        self._is_testing = False
        self._current_task = ""
        self._edit_test_btn = _FakeBtn()
        self._edit_test_cancel_btn = _FakeBtn()
        self._edit_stack = SimpleNamespace(setCurrentIndex=lambda idx: None)
        self._signals = _SignalBus()
        self.t = {"set_test_running": None, "restore_test_btn": None}

    def _save_current_rule(self):
        pass

    def _get_current_rule(self):
        return self._rule_under_test

    def _rule_hard_problems(self, rule):
        return []

    def _set_test_running(self, running):
        self._is_testing = bool(running)
        self._edit_test_cancel_btn.setVisible(running)
        if running:
            self.t["set_test_running"] = time.perf_counter_ns()

    def _restore_test_btn(self):
        self._is_testing = False
        self._edit_test_cancel_btn.setVisible(False)
        self._edit_test_btn.setEnabled(True)
        self._edit_test_btn.setText(T("ui.test"))
        self.t["restore_test_btn"] = time.perf_counter_ns()


def _make_ctrl(win):
    return _rc.TestRunController(
        win,
        of_summary=lambda *a, **k: "",
        resolve_rule_name=lambda r: getattr(r, "name", ""),
    )


def _step_detect(text="ABC", roi=None, match_mode="fuzzy", threshold=0.8):
    p = {"text": text, "match_mode": match_mode, "fuzzy_threshold": threshold}
    if roi is not None:
        p["roi"] = roi
    return Step(type="detect", params=p)


def _step_click(target="text_center"):
    return Step(type="click", params={"target": target})


def _step_key(key="enter"):
    return Step(type="key", params={"key": key})


def _step_wait(ms=100):
    return Step(type="wait", params={"ms": ms})


def _step_scroll():
    return Step(type="scroll", params={"direction": "WheelDown", "amount": 1})


def _step_sum(roi):
    return Step(type="sum", params={"roi": roi})


def _load_image():
    img = cv2.imread(IMG_PATH)
    if img is None:
        raise RuntimeError("Cannot read test image: " + IMG_PATH)
    return img


ROI_SMALL = {"x": 400, "y": 200, "w": 200, "h": 100, "roi_coord": "client"}
ROI_MED = {"x": 500, "y": 300, "w": 600, "h": 400, "roi_coord": "client"}
ROI_FULL = {"x": 0, "y": 0, "w": 0, "h": 0}


def _patch_env_for_dry_run(targets):
    _rc.get_client_rect_for_image = targets.get("get_client_rect_for_image", lambda *a, **k: None)
    _rc.get_window_client_offset = targets.get("get_window_client_offset", lambda *a, **k: (0, 0))


def _run_dry_run_timed(ctrl, rule, img, cancel=None, iterations=30):
    samples = []
    last = None
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        markers, log, dead = ctrl._run_dry_run(rule, img, cancel=cancel)
        t1 = time.perf_counter_ns()
        samples.append(t1 - t0)
        last = (markers, log, dead)
    return samples, last


def part_a_real_ocr(img, iterations=60):
    print("\n" + "=" * 72)
    print("Part A - _run_dry_run() core execution time (real OCR, warm start)")
    print("=" * 72)

    _patch_env_for_dry_run({})
    ctrl = _make_ctrl(_FakeWin(img))
    warmup = Rule(id="w", name="Warmup", enabled=True, steps=[_step_detect("ABC", ROI_SMALL)])
    ctrl._run_dry_run(warmup, img, cancel=None)

    scenarios = [
        ("0 steps (empty rule)", Rule(id="r0", name="R0", enabled=True, steps=[]), img, iterations),
        (
            "1 step detect (small ROI, hit, OCR ~7 ms)",
            Rule(id="r1", name="R1", enabled=True, steps=[_step_detect("target", ROI_SMALL)]),
            img,
            iterations,
        ),
        (
            "1 step detect (full-image ROI, OCR ~1 s)",
            Rule(id="r2", name="R2", enabled=True, steps=[_step_detect("target", ROI_FULL)]),
            img,
            max(8, iterations // 6),
        ),
        (
            "3 steps detect-small+click+key",
            Rule(
                id="r3",
                name="R3",
                enabled=True,
                steps=[_step_detect("target", ROI_SMALL), _step_click(), _step_key()],
            ),
            img,
            iterations,
        ),
        (
            "5 steps detect-small+click+key+wait+scroll",
            Rule(
                id="r5",
                name="R5",
                enabled=True,
                steps=[
                    _step_detect("target", ROI_SMALL),
                    _step_click(),
                    _step_key(),
                    _step_wait(),
                    _step_scroll(),
                ],
            ),
            img,
            iterations,
        ),
        (
            "10 steps (interleaved detect/click/key/wait/sum small ROI)",
            Rule(
                id="r10",
                name="R10",
                enabled=True,
                steps=[
                    _step_detect("target", ROI_SMALL),
                    _step_click(),
                    _step_key(),
                    _step_wait(),
                    _step_scroll(),
                    _step_detect("minor", ROI_SMALL),
                    _step_click(),
                    _step_key(),
                    _step_wait(),
                    _step_sum(ROI_SMALL),
                ],
            ),
            img,
            iterations,
        ),
        (
            "OCR heavy: 3x detect (medium ROI, ~60 ms each)",
            Rule(
                id="rmed",
                name="Rmed",
                enabled=True,
                steps=[
                    _step_detect("A", ROI_MED),
                    _step_detect("B", ROI_MED),
                    _step_detect("C", ROI_MED),
                ],
            ),
            img,
            max(8, iterations // 4),
        ),
    ]

    rows = []
    for name, rule, use_img, it in scenarios:
        ctrl = _make_ctrl(_FakeWin(use_img))
        samples, _ = _run_dry_run_timed(ctrl, rule, use_img, iterations=it)
        st = _stats_ms(samples)
        rows.append({"name": name, "n": it, **st})
        print(
            f"{name:48s} n={it:<3} min={st['min']:>7} avg={st['avg']:>7} "
            f"p50={st['p50']:>7} p95={st['p95']:>7} max={st['max']:>7} ms"
        )
    return rows


def part_a_mock_ocr(img, iterations=100):
    print("\n" + "=" * 72)
    print("Part A - _run_dry_run() core execution time (mock OCR, control-flow measurement)")
    print("=" * 72)

    _rc.recognize = lambda *a, **k: []
    _patch_env_for_dry_run({})

    scenarios = [
        ("0 steps (empty rule)", Rule(id="m0", name="M0", enabled=True, steps=[]), img, iterations),
        (
            "1 step detect (mock empty result)",
            Rule(id="m1", name="M1", enabled=True, steps=[_step_detect("ABC", ROI_SMALL)]),
            img,
            iterations,
        ),
        (
            "10 steps (mock OCR)",
            Rule(
                id="m10",
                name="M10",
                enabled=True,
                steps=[
                    _step_detect("A", ROI_SMALL),
                    _step_click(),
                    _step_key(),
                    _step_wait(),
                    _step_scroll(),
                    _step_detect("B", ROI_SMALL),
                    _step_click(),
                    _step_key(),
                    _step_wait(),
                    _step_sum(ROI_SMALL),
                ],
            ),
            img,
            iterations,
        ),
    ]

    rows = []
    for name, rule, use_img, it in scenarios:
        ctrl = _make_ctrl(_FakeWin(use_img))
        samples, _ = _run_dry_run_timed(ctrl, rule, use_img, iterations=it)
        st = _stats_ms(samples)
        rows.append({"name": name, "n": it, **st})
        print(
            f"{name:48s} n={it:<3} min={st['min']:>7} avg={st['avg']:>7} "
            f"p50={st['p50']:>7} p95={st['p95']:>7} max={st['max']:>7} ms"
        )
    _rc.recognize = recognize_real
    return rows


# ponytail: 保留「未包裝」的原始方法。每個 case 都重新包裝時若抓當下的類別屬性，
# 第二個 case 會抓到上一個 case 的 wrapper（closure 指向舊 rec），導致量測寫錯字典。
_ORIG_RUN_RULE_TEST = _rc.TestRunController._run_rule_test
_ORIG_RUN_DRY_RUN = _rc.TestRunController._run_dry_run


def _install_b_hooks(ctrl, win, rec):
    orig_run_rule_test = _ORIG_RUN_RULE_TEST
    orig_run_dry_run = _ORIG_RUN_DRY_RUN

    def wrapped_run_rule_test(self_, rule, img, warn="", ctx=None, cancel=None):
        rec["worker_started"] = time.perf_counter_ns()

        def wrapped_dry_run(self2, rule2, img2, cancel=None):
            # ponytail: 參數名必須與 _run_rule_test 呼叫端一致（cancel=），否則直接 TypeError
            rec["dry_start"] = time.perf_counter_ns()
            res = orig_run_dry_run(self2, rule2, img2, cancel=cancel)
            rec["dry_end"] = time.perf_counter_ns()
            return res

        _rc.TestRunController._run_dry_run = wrapped_dry_run
        try:
            return orig_run_rule_test(self_, rule, img, warn=warn, ctx=ctx, cancel=cancel)
        finally:
            _rc.TestRunController._run_dry_run = orig_run_dry_run

    _rc.TestRunController._run_rule_test = wrapped_run_rule_test

    orig_emit = win._signals.emit

    def wrapped_emit(result):
        rec["signal_emitted"] = time.perf_counter_ns()
        return orig_emit(result)

    win._signals.emit = wrapped_emit

    orig_restore = win._restore_test_btn

    def wrapped_restore():
        rec["restore_called"] = time.perf_counter_ns()
        return orig_restore()

    win._restore_test_btn = wrapped_restore


def part_b_gui_cancel_window(img, iterations=30):
    print("\n" + "=" * 72)
    # ponytail: 輸出標題必須誠實 — 本節是假視窗的流程生命週期計時，
    # 並未量得真實使用者的可操作取消窗口（paint/click 間隔皆為 N/A）。
    print("Part B - GUI lifecycle timing (fake window; actual cancel window not measured)")
    print("=" * 72)

    # Capture is monkeypatched to return the test image instantly; real capture_frame
    # cost depends on the target game window and is reported separately (Part A full-image OCR).
    _rc.capture_frame = lambda mode, title, hwnd=None: img
    _rc.get_window_hwnd = lambda title: None
    _rc.get_client_rect_for_image = lambda *a, **k: None
    _rc.get_window_client_offset = lambda *a, **k: (0, 0)
    _rc.recognize = recognize_real
    _rc._get_interaction_mode = lambda: "frida"  # non-pynput: no window ops/sleeps on fake win

    app = QApplication.instance() or QApplication([])

    rows = []
    cases = [
        (
            "fast rule (5 steps, small ROI detect, total ~tens of ms)",
            [
                _step_detect("target", ROI_SMALL),
                _step_click(),
                _step_key(),
                _step_wait(),
                _step_scroll(),
            ],
        ),
        (
            "slower rule (3x medium ROI detect, total ~150-250 ms)",
            [_step_detect("A", ROI_MED), _step_detect("B", ROI_MED), _step_detect("C", ROI_MED)],
        ),
    ]

    for label, steps in cases:
        rec = {
            k: None
            for k in [
                "entry",
                "after_processevents",
                "worker_started",
                "dry_start",
                "dry_end",
                "signal_emitted",
                "signal_received",
                "restore_called",
            ]
        }
        win = _FakeWin(img)
        win._rule_under_test = Rule(id="b", name="B", enabled=True, steps=steps)
        ctrl = _make_ctrl(win)
        _install_b_hooks(ctrl, win, rec)

        def on_result(result, rec=rec, win=win):
            rec["signal_received"] = time.perf_counter_ns()
            win._restore_test_btn()

        win._signals.connect(on_result)

        samples = []
        for _ in range(iterations):
            for k in rec:
                rec[k] = None
            win.t["set_test_running"] = None
            win.t["restore_test_btn"] = None

            t_entry = time.perf_counter_ns()
            rec["entry"] = t_entry
            ctrl.on_test_rule()  # GUI thread: set_test_running -> processEvents -> capture -> t.start()
            rec["after_processevents"] = time.perf_counter_ns()
            # worker_started is set inside _install_b_hooks wrapped_run_rule_test when on_test_rule runs
            # It marks when the worker thread begins processing
            deadline = time.perf_counter_ns() + 30_000_000_000
            while rec.get("restore_called") is None and time.perf_counter_ns() < deadline:
                app.processEvents()
                time.sleep(0.001)
            t_restore = rec["restore_called"] or time.perf_counter_ns()

            def ms(ns):
                # ponytail: 缺時間戳必須是 None，不可回傳 0.0（否則「沒量到」會偽裝成「瞬間」）
                return None if ns is None else (ns - rec["entry"]) / 1_000_000.0

            dry_ms = (
                ((rec["dry_end"] - rec["dry_start"]) / 1_000_000.0)
                if rec["dry_start"] and rec["dry_end"]
                else None
            )
            # Metric 1: button_show_call_ms - 測試開始 → setVisible(True) 呼叫返回的耗時。
            # _FakeWin._set_test_running 在 setVisible(True) 返回後立即取時鐘，故此值僅為
            # 「程式已呼叫 setVisible(True)」，不代表畫面已繪製、也不代表滑鼠可點。
            # 命名刻意用 show_call 而非 visible：避免被誤讀為「按鈕可見時間」。
            button_show_call_ms = ms(win.t["set_test_running"])

            # Metric 2: button_painted_to_hidden_ms - N/A in fake win (no real paint/rendering)
            # The fake win has no QWidget paint system; _restore_test_btn just toggles visibility
            # via setVisible() without any QPainter rendering. This interval is N/A.
            button_painted_to_hidden_ms = None

            # Metric 3: cancel_input_operable_ms - N/A in fake win (no real GUI input pipeline)
            # The fake win's signal/slot is an in-process handler list, not a real Qt queued connection.
            # There is no actual message pump or input routing. This interval is N/A.
            cancel_input_operable_ms = None

            # Legacy reference（僅環境參考）：訊號發出 → UI 恢復的間隔。
            # 注意：假 win 的 _SignalBus 是在 worker 執行緒內同步呼叫 handler，
            # 沒有真實 Qt queued connection 的事件佇列延遲，因此這個值
            # 「不是」真實 GUI 的訊號延遲，更不是使用者可操作窗口。
            signal_latency_ms = (
                (t_restore - rec["signal_emitted"]) / 1_000_000.0
                if rec["signal_emitted"] and t_restore
                else None
            )

            # GUI 執行緒釋放點：on_test_rule() 返回後 GUI 才回到事件迴圈，
            # 此前按鈕雖已 setVisible(True) 但 GUI 執行緒被佔用。
            # 這是「環境參考」，不等同於 cancel_input_operable（假 win 無真實輸入管線）。
            gui_release_ms = ms(rec["after_processevents"])

            samples.append(
                {
                    "label": label,
                    "button_show_call_ms": button_show_call_ms,
                    "button_painted_to_hidden_ms": button_painted_to_hidden_ms,
                    "cancel_input_operable_ms": cancel_input_operable_ms,
                    # Legacy reference metrics (document only, do not call "operable window")
                    "signal_latency_ms": signal_latency_ms,
                    "gui_release_ms": gui_release_ms,
                    "t_dry_ms": dry_ms,
                    "t_signal_ms": ms(rec["signal_emitted"]),
                    "t_restore_ms": ms(t_restore),
                }
            )

        def field(f):
            # 負值一律不納入有效統計（時序量測不該出現負值，出現即代表量測無效）
            return [s[f] for s in samples if s[f] is not None and s[f] >= 0]

        f_vis = field("button_show_call_ms")
        # button_painted_to_hidden_ms / cancel_input_operable_ms 全為 None（假 win 量不到），
        # 故不另建統計變數，直接於 agg 以 "N/A" 呈現。
        f_sig = field("signal_latency_ms")
        f_release = field("gui_release_ms")
        f_res = field("t_restore_ms")
        f_dry = field("t_dry_ms")

        agg = {
            "label": label,
            "n": len(samples),
            # 有效量測：測試開始 → setVisible(True) 呼叫返回（非「可見時間」）
            "show_call_avg": round(sum(f_vis) / len(f_vis), 3) if f_vis else None,
            # N/A metrics - all values are None in fake win environment
            "painted_to_hidden_avg": "N/A",
            "cancel_input_operable_avg": "N/A",
            # Legacy reference averages (document only, do not call "operable window")
            "signal_latency_avg": round(sum(f_sig) / len(f_sig), 3) if f_sig else None,
            "gui_release_avg": round(sum(f_release) / len(f_release), 3) if f_release else None,
            "dry_avg": round(sum(f_dry) / len(f_dry), 3) if f_dry else None,
            "restore_avg": round(sum(f_res) / len(f_res), 3) if f_res else None,
        }
        rows.append(agg)
        print(
            f"{label:62s} n={agg['n']} show_call={agg['show_call_avg']}ms painted_to_hidden={agg['painted_to_hidden_avg']}ms "
            f"cancel_input={agg['cancel_input_operable_avg']}ms signal_latency={agg['signal_latency_avg']}ms "
            f"dry={agg['dry_avg']}ms restore={agg['restore_avg']}ms"
        )

    _rc.capture_frame = None
    return rows


def part_c_cancel_probability(img, iterations=40):
    print("\n" + "=" * 72)
    print(
        "Part C - Cancel-success probability ESTIMATE "
        "(execution time vs assumed human reaction time; NOT a user study, NOT a cancel-rate statistic)"
    )
    print("=" * 72)

    _rc.get_client_rect_for_image = lambda *a, **k: None
    _rc.get_window_client_offset = lambda *a, **k: (0, 0)
    _rc.recognize = recognize_real

    rules = [
        ("1 step detect small ROI", [_step_detect("target", ROI_SMALL)]),
        (
            "3 steps (detect-small+click+key)",
            [_step_detect("target", ROI_SMALL), _step_click(), _step_key()],
        ),
        (
            "5 steps",
            [
                _step_detect("target", ROI_SMALL),
                _step_click(),
                _step_key(),
                _step_wait(),
                _step_scroll(),
            ],
        ),
        (
            "10 steps (incl sum small ROI)",
            [
                _step_detect("target", ROI_SMALL),
                _step_click(),
                _step_key(),
                _step_wait(),
                _step_scroll(),
                _step_detect("B", ROI_SMALL),
                _step_click(),
                _step_key(),
                _step_wait(),
                _step_sum(ROI_SMALL),
            ],
        ),
        (
            "OCR heavy (3x medium ROI detect)",
            [_step_detect("A", ROI_MED), _step_detect("B", ROI_MED), _step_detect("C", ROI_MED)],
        ),
    ]

    print(
        f"{'rule':44s} {'n':>3} {'min':>7} {'avg':>7} {'p50':>7} {'p95':>7} {'max':>7} ms  |"
        f" human reaction 250ms / 500ms / 1000ms can-cancel (estimate, not measured)"
    )
    for name, steps in rules:
        rule = Rule(id="c", name="C", enabled=True, steps=steps)
        ctrl = _make_ctrl(_FakeWin(img))
        samples, _ = _run_dry_run_timed(ctrl, rule, img, iterations=iterations)
        st = _stats_ms(samples)

        def chance(H):
            return "likely" if H < st["p50"] else ("possible" if H < st["p95"] else "unlikely")

        print(
            f"{name:44s} {st['count']:>3} {st['min']:>7} {st['avg']:>7} {st['p50']:>7} {st['p95']:>7} {st['max']:>7} ms  |"
            f" 250ms:{chance(250):10s} 500ms:{chance(500):10s} 1000ms:{chance(1000):10s}"
        )
    return rules


def main():
    print("Phase 3B Dry-run Speed Benchmark (READ-ONLY)")
    print(
        "Test image: %s  (%dx%d)"
        % (IMG_PATH, cv2.imread(IMG_PATH).shape[1], cv2.imread(IMG_PATH).shape[0])
    )
    print("Python: %s" % sys.version.split()[0])

    img = _load_image()

    print("\n--- Cold-start OCR reference (incl. engine init) ---")
    t0 = time.perf_counter_ns()
    _ocr.init_engine()
    t1 = time.perf_counter_ns()
    print("init_engine(): %.1f ms" % ((t1 - t0) / 1_000_000.0))
    t0 = time.perf_counter_ns()
    _ocr.recognize(img, preprocess=False, max_side_len=0, min_confidence=0.25)
    t1 = time.perf_counter_ns()
    print("first recognise (cold, full 1920x1080): %.1f ms" % ((t1 - t0) / 1_000_000.0))
    t0 = time.perf_counter_ns()
    _ocr.recognize(img, preprocess=False, max_side_len=0, min_confidence=0.25)
    t1 = time.perf_counter_ns()
    print("second recognise (warm, full 1920x1080): %.1f ms" % ((t1 - t0) / 1_000_000.0))

    a_real = part_a_real_ocr(img)
    a_mock = part_a_mock_ocr(img)
    b = part_b_gui_cancel_window(img)
    part_c_cancel_probability(img)

    results = {
        "meta": {
            "image": IMG_PATH,
            "image_size": [cv2.imread(IMG_PATH).shape[1], cv2.imread(IMG_PATH).shape[0]],
            # 生成時間戳：可證明本 JSON 由腳本實際執行產生（非手改）
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            # section 標題：與腳本輸出、benchmark 文件一致，避免讀者誤讀量測範圍
            "titles": {
                "part_a_real_ocr": "Part A - _run_dry_run() core execution time (real OCR, warm start)",
                "part_a_mock_ocr": "Part A - _run_dry_run() core execution time (mock OCR, control-flow measurement)",
                "part_b_gui_lifecycle": "Part B - GUI lifecycle timing (fake window; actual cancel window not measured)",
            },
            # Part B 指標解讀邊界（寫進結果檔本身，避免只看 JSON 就誤讀）
            "part_b_note": (
                "假視窗（fake win）流程計時，非真實 GUI："
                "painted_to_hidden_avg / cancel_input_operable_avg 為 N/A（未量測）；"
                "signal_latency_avg 為同步 Python handler list 的執行時間，"
                "不代表正式 GUI 跨執行緒 Qt Signal/Slot 延遲；"
                "dry_avg / restore_avg 為假視窗測試流程耗時，不等於真實使用者取消窗口。"
            ),
            "part_c_note": (
                "can-cancel 欄位為「執行時間 vs 假設反應時間」的推估，"
                "非實際使用者測試，也非取消成功率統計；"
                "單次 OCR 執行期間無法靠步驟邊界檢查立即中斷；"
                "實際取消結果仍取決於步驟邊界與 GUI 事件派送。"
            ),
        },
        "part_a_real_ocr": a_real,
        "part_a_mock_ocr": a_mock,
        "part_b_gui_lifecycle": b,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nResults written to: %s" % RESULTS_PATH)
    print("This script only measures; it did not modify any formal code, commit, or push.")


if __name__ == "__main__":
    main()
