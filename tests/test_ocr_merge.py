"""Regression test: merged-OCR (_ocr_region superset/union reuse) is behaviorally
equivalent to per-rect OCR on the real StarSavior task, across 3 real de-skill
frames.

Current (exact rect per detect step) vs merged (superset reuse / overlap union),
mirroring core/05_main_loop.py::_ocr_region semantics (no roi_offset double-add;
coordinates are shifted manually after recognize()).

Skips when the local RapidOCR model (custom_models/chinese_cht_rec_mobile.onnx) is
not present, since that path can't run without it.
"""

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _loader import load_sibling  # noqa: E402

ROOT = _ROOT
JOB = ROOT / "docs/tasks/StarSavior-跑馬輔助.json"
DATA = Path(__file__).resolve().parent / "data"
FRAMES = ["test.png", "test2.png", "test3.png"]
WIN = (1920.0, 1080.0)

_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")

_ENGINE_AVAIL = Path(ROOT / "custom_models/chinese_cht_rec_mobile.onnx").exists()
needs_model = pytest.mark.skipif(
    not _ENGINE_AVAIL,
    reason="RapidOCR model (custom_models/chinese_cht_rec_mobile.onnx) not present",
)


def _fuzzy(text, target, threshold=0.8):
    return SequenceMatcher(None, target.lower(), text.lower()).ratio() >= threshold


def _find_in(results, text):
    for r in results:
        if _fuzzy(r.text, text):
            return r
    return None


def _extract_steps():
    d = json.load(open(JOB, encoding="utf-8"))
    steps = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "detect" and o.get("match") != "image":
                p = o.get("params") or {}
                roi, txt = p.get("roi"), p.get("text")
                if roi and txt:
                    steps.append({"roi": roi, "target": txt})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(d)
    return steps


def _ratio_to_px(roi):
    return (
        int(roi["x"] * WIN[0]),
        int(roi["y"] * WIN[1]),
        int(roi["w"] * WIN[0]),
        int(roi["h"] * WIN[1]),
    )


def _inside(results, x1, y1, x2, y2):
    return [
        r for r in results if not (r.x + r.w <= x1 or r.y + r.h <= y1 or r.x >= x2 or r.y >= y2)
    ]


def _current_hits(img, steps):
    cache = {}
    calls = 0
    hits = {}
    for st in steps:
        x, y, w, h = st["px"]
        key = (x, y, w, h)
        if key not in cache:
            res = _ocr.recognize(
                img[y : y + h, x : x + w],
                preprocess=False,
                max_side_len=0,
                min_confidence=0.25,
            )
            for r in res:
                r.x += x
                r.y += y
            cache[key] = res
            calls += 1
        hits[st["id"]] = _find_in(cache[key], st["target"])
    return calls, hits


def _merged_hits(img, steps):
    cache = {}
    calls = 0
    hits = {}
    for st in steps:
        x1, y1, w, h = st["px"]
        x2, y2 = x1 + w, y1 + h
        rect = (x1, y1, w, h)
        got = None
        if rect in cache:
            got = cache[rect]
        else:
            # superset reuse
            for k, res in list(cache.items()):
                cx1, cy1, cw, ch = k
                if cx1 <= x1 and cy1 <= y1 and cx1 + cw >= x2 and cy1 + ch >= y2:
                    got = _inside(res, x1, y1, x2, y2)
                    break
            # overlap -> union, one call
            if got is None:
                for k in list(cache.keys()):
                    cx1, cy1, cw, ch = k
                    if cx1 < x2 and cy1 < y2 and cx1 + cw > x1 and cy1 + ch > y1:
                        ux, uy = min(cx1, x1), min(cy1, y1)
                        ux2, uy2 = max(cx1 + cw, x2), max(cy1 + ch, y2)
                        res = _ocr.recognize(
                            img[uy:uy2, ux:ux2],
                            preprocess=False,
                            max_side_len=0,
                            min_confidence=0.25,
                        )
                        for r in res:
                            r.x += ux
                            r.y += uy
                        cache[(ux, uy, ux2 - ux, uy2 - uy)] = res
                        calls += 1
                        got = _inside(res, x1, y1, x2, y2)
                        break
            # standalone
            if got is None:
                res = _ocr.recognize(
                    img[y1:y2, x1:x2],
                    preprocess=False,
                    max_side_len=0,
                    min_confidence=0.25,
                )
                for r in res:
                    r.x += x1
                    r.y += y1
                cache[rect] = res
                calls += 1
                got = res
        hits[st["id"]] = _find_in(got, st["target"])
    return calls, hits


def _prepare_steps(steps):
    for i, st in enumerate(steps):
        st["px"] = _ratio_to_px(st["roi"])
        st["id"] = i
    return steps


@needs_model
def _run_frame(frame_path):
    _ocr.init_engine()
    img = cv2.imread(str(DATA / frame_path))
    steps = _prepare_steps(_extract_steps())
    cc, ch = _current_hits(img, steps)
    mc, mh = _merged_hits(img, steps)
    dropped = false_pos = 0
    for st in steps:
        c, m = ch[st["id"]], mh[st["id"]]
        if c is not None and m is None:
            dropped += 1
        if c is None and m is not None:
            false_pos += 1
    return steps, cc, mc, dropped, false_pos


@needs_model
def test_merged_never_drops_real_targets():
    """Merged OCR must not lose a target the exact-rect OCR would trigger, on any frame."""
    _ocr.init_engine()
    for frame in FRAMES:
        _, _, _, dropped, false_pos = _run_frame(frame)
        assert dropped == 0, f"{frame}: merged dropped a trigger (exact hit, merged miss)"
        assert false_pos == 0, f"{frame}: merged false-positived"


@needs_model
def test_merged_call_count_not_worse():
    """Merged should not issue more OCR calls than current per-rect."""
    _ocr.init_engine()
    for frame in FRAMES:
        _, cc, mc, _, _ = _run_frame(frame)
        assert mc <= cc, f"{frame}: merged used {mc} calls vs current {cc}"
