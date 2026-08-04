"""Verification: parallel prematch in _run_parallel_group is behaviorally
equivalent to the sequential path. For every match_image-first rule in the real
StarSavior task, _handle_match_image must yield identical outcomes whether it
consumes a precomputed ctx.prematch or computes match_template right away."""

import json
import logging
import sys
import threading
from collections import deque
from pathlib import Path

import cv2

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _loader import load_sibling  # noqa: E402

_ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
Rule = _ml_mod.Rule
StepContext = _ml_mod.StepContext
StepResult = _ml_mod.StepResult
Step = _rule_mod.Step
img_to_b64 = _ml_mod.img_to_b64

FRAMES = ["test.png", "test2.png", "test3.png"]
JOB = _ROOT / "docs/tasks/StarSavior-跑馬輔助.json"


def _make_ml():
    ml = _ml_mod.MainLoop.__new__(_ml_mod.MainLoop)
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
    ml._logger = logging.getLogger("prematch_test")
    ml._stop_event = threading.Event()
    ml._pause_event = threading.Event()
    ml._emergency_event = threading.Event()
    ml._rule_config_ctrl = type(
        "FakeRuleConfig", (), {"get_setting": lambda self, win, key="interaction_mode": "pynput"}
    )()
    ml._execution_log = deque(maxlen=10)
    ml._last_exec_log = {}
    ml._rule_completed = set()
    ml._last_completed_log = {}
    ml._match_image_warn_counter = {}
    ml._detect_warn_counter = {}
    ml._prematch_pool = None
    ml.on_error = None
    ml.on_warning = None
    ml.on_info = None
    ml.on_window_lost = None
    ml.on_emergency = None
    ml._send_click = lambda *a, **k: True
    ml._send_key = lambda *a, **k: True
    ml._send_scroll = lambda *a, **k: True
    ml._activate_window = lambda *a, **k: True
    return ml


def _match_image_rules():
    with open(JOB, encoding="utf-8") as f:
        d = json.load(f)
    rules = {r["id"]: r for r in d["rules"]}
    out = []
    for g in d["groups"]:
        if g.get("order") != "parallel":
            continue
        for rid in g["rule_ids"]:
            r = rules.get(rid)
            if not r or not r.get("enabled", True):
                continue
            steps = r.get("steps", [])
            if not steps or steps[0].get("type") != "match_image":
                continue
            if not steps[0].get("params", {}).get("template_data", "").strip():
                continue
            out.append(
                Rule(
                    id=rid,
                    name=r.get("name", rid),
                    enabled=True,
                    background=False,
                    steps=[Step(type=s["type"], params=s.get("params", {})) for s in steps],
                )
            )
    return out


def test_prematch_equiv_all_frames():
    rules = _match_image_rules()
    assert rules, "no match_image-first rules found"
    ml = _make_ml()
    checked = 0
    for fname in FRAMES:
        img = cv2.imread(str(_ROOT / "tests/data" / fname))
        assert img is not None, f"missing {fname}"
        rect = {"x": 0, "y": 0, "w": img.shape[1], "h": img.shape[0]}
        for rule in rules:
            pre = ml._prematch_match(rule, img, rect)  # what the worker computes
            # prematch-consumed path
            ctx_a = StepContext(img=img, rect=rect)
            ctx_a.prematch = {0: pre}
            res_a = ml._handle_match_image(rule.steps[0].params, ctx_a, rule)
            # immediate path
            ctx_b = StepContext(img=img, rect=rect)
            res_b = ml._handle_match_image(rule.steps[0].params, ctx_b, rule)
            assert res_a.action == res_b.action, f"{rule.name}/{fname} action differs"
            con_a = ctx_a.matched_text.confidence if ctx_a.matched_text else None
            con_b = ctx_b.matched_text.confidence if ctx_b.matched_text else None
            assert con_a == con_b, f"{rule.name}/{fname} confidence differs"
            assert ctx_a.best_confidence == ctx_b.best_confidence, (
                f"{rule.name}/{fname} best_conf differs"
            )
            checked += 1
    print(f"prematch equivalence: {len(rules)} rules x {len(FRAMES)} frames = {checked} checks OK")


if __name__ == "__main__":
    test_prematch_equiv_all_frames()
    print("=== test_prematch_equiv passed ===")
