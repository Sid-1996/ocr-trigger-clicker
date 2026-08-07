"""Regression test: inline template decode cache (_decode_template LRU) is
behaviorally equivalent to decoding fresh every call, across the StarSavior task
snapshot's parallel-group templates (tests/data/fixture_task.json) and the real
de-skill frames in tests/data.

Also verifies the cache actually hits on repeated identical calls (the perf win),
and that clear_template_cache() resets it.

Uses the same load_sibling pattern as test_template_matching.py / test_ocr_merge.py.
"""

import json
import sys
from pathlib import Path

import cv2

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _loader import load_sibling  # noqa: E402

ROOT = _ROOT
DATA = Path(__file__).resolve().parent / "data"
# 快照自 docs/tasks/StarSavior-跑馬輔助.json — 固定基準，任務內容更新不影響回歸測試
JOB = DATA / "fixture_task.json"
FRAMES = ["test.png", "test2.png", "test3.png"]

_tm = load_sibling("template_matching", "core/11_template_matching.py")
match_template = _tm.match_template
clear_template_cache = _tm.clear_template_cache
_decode_template = _tm._decode_template


def _parallel_match_image_steps():
    """Collect the first-step match_image (template_data + roi) of the largest
    parallel group in the real task."""
    with open(JOB, encoding="utf-8") as f:
        data = json.load(f)
    rules = {r["id"]: r for r in data.get("rules", [])}
    groups = data.get("groups", [])
    parallel = [g for g in groups if g.get("order") == "parallel"]
    group = max(parallel, key=lambda g: len(g.get("rule_ids", [])))
    steps = []
    for rid in group["rule_ids"]:
        r = rules.get(rid, {})
        if not r.get("steps"):
            continue
        s = r["steps"][0]
        if s.get("type") != "match_image":
            continue
        p = s.get("params", {})
        if not p.get("template_data", "").strip():
            continue
        steps.append({"td": p["template_data"], "roi": p.get("roi", {})})
    return steps


def _to_px(roi, w, h):
    return {
        "x": int(roi.get("x", 0) * w),
        "y": int(roi.get("y", 0) * h),
        "w": int(roi.get("w", 0) * w),
        "h": int(roi.get("h", 0) * h),
    }


def _sig(result):
    if isinstance(result, tuple):
        result = result[0]
    return sorted((m.x, m.y, m.w, m.h, round(m.confidence, 4)) for m in result)


def test_cache_equivalence_on_real_frames():
    steps = _parallel_match_image_steps()
    assert len(steps) >= 10, f"expected many match_image steps, got {len(steps)}"

    for fname in FRAMES:
        img = cv2.imread(str(DATA / fname))
        assert img is not None, f"{fname} missing"
        h, w = img.shape[:2]
        clear_template_cache()

        fresh = [
            _sig(
                match_template(
                    img,
                    "",
                    _to_px(s["roi"], w, h),
                    0.8,
                    template_data=s["td"],
                    capture_size=[1920, 1080],
                    current_size=[w, h],
                    return_best=True,
                )
            )
            for s in steps
        ]
        cached = [
            _sig(
                match_template(
                    img,
                    "",
                    _to_px(s["roi"], w, h),
                    0.8,
                    template_data=s["td"],
                    capture_size=[1920, 1080],
                    current_size=[w, h],
                    return_best=True,
                )
            )
            for s in steps
        ]

        assert fresh == cached, f"{fname}: cache changed match results for {len(steps)} steps"


def test_cache_hits_on_repeated_call():
    steps = _parallel_match_image_steps()
    img = cv2.imread(str(DATA / FRAMES[0]))
    h, w = img.shape[:2]
    s = steps[0]

    clear_template_cache()
    match_template(
        img,
        "",
        _to_px(s["roi"], w, h),
        0.8,
        template_data=s["td"],
        capture_size=[1920, 1080],
        current_size=[w, h],
        return_best=True,
    )
    info1 = _decode_template.cache_info()
    match_template(
        img,
        "",
        _to_px(s["roi"], w, h),
        0.8,
        template_data=s["td"],
        capture_size=[1920, 1080],
        current_size=[w, h],
        return_best=True,
    )
    info2 = _decode_template.cache_info()
    assert info2.hits > info1.hits, "repeated identical call should hit decode cache"


def test_clear_cache_resets():
    steps = _parallel_match_image_steps()
    img = cv2.imread(str(DATA / FRAMES[0]))
    h, w = img.shape[:2]
    s = steps[0]
    match_template(
        img,
        "",
        _to_px(s["roi"], w, h),
        0.8,
        template_data=s["td"],
        capture_size=[1920, 1080],
        current_size=[w, h],
        return_best=True,
    )
    assert _decode_template.cache_info().currsize > 0
    clear_template_cache()
    assert _decode_template.cache_info().currsize == 0
