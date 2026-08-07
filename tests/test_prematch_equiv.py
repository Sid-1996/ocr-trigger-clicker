"""Verification: parallel prematch in _run_parallel_group is behaviorally
equivalent to the sequential path. For every match_image-first rule in the
StarSavior task snapshot (tests/data/fixture_task.json), _handle_match_image must
yield identical outcomes whether it consumes a precomputed ctx.prematch or
computes match_template right away."""

import json
import sys
from pathlib import Path

import cv2

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from conftest import make_main_loop as _make_ml  # noqa: E402

from _loader import load_sibling  # noqa: E402

_ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
Rule = _ml_mod.Rule
StepContext = _ml_mod.StepContext
StepResult = _ml_mod.StepResult
Step = _rule_mod.Step
img_to_b64 = _ml_mod.img_to_b64

FRAMES = ["test.png", "test2.png", "test3.png"]
# 快照自 docs/tasks/StarSavior-跑馬輔助.json — 固定基準，任務內容更新不影響回歸測試
JOB = _ROOT / "tests/data/fixture_task.json"


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


_prematch_pure = _ml_mod._prematch_pure


def test_prematch_equiv_all_frames():
    rules = _match_image_rules()
    assert rules, "no match_image-first rules found"
    ml = _make_ml()
    checked = 0
    for fname in FRAMES:
        img = cv2.imread(str(_ROOT / "tests/data" / fname))
        assert img is not None, f"missing {fname}"
        rect = {"x": 0, "y": 0, "w": img.shape[1], "h": img.shape[0]}
        # 模擬 _run_parallel_group 主線程的共享預算（capture_size/chrome/current_size 算一次）
        capture_size = _ml_mod.get_capture_size(ml._rules_path)
        chrome = _ml_mod.get_window_client_offset(ml._window_title)
        if chrome:
            current_size = [rect["w"] - chrome[0], rect["h"] - chrome[1]]
        else:
            current_size = [rect["w"], rect["h"]]
        for rule in rules:
            p = rule.steps[0].params
            roi = ml._resolve_roi(p.get("roi", {}), rect, chrome)
            pre = _prematch_pure(
                img,
                p.get("template", ""),
                roi,
                p.get("threshold", 0.8),
                p.get("template_data", "") or None,
                capture_size,
                current_size,
                p.get("match_color", False),
                p.get("color_tolerance", 100),
            )
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
