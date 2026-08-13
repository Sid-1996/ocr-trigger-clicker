"""Regression test: step-0 detect/compare ROI 預聚類（方案 B）+ 跨幀內容快取（方案 A）
對現行 union-chain 的行為等價與效能改善，在 StarSavior-跑馬輔助 快照
（tests/data/fixture_task.json）與 3 張實境圖上驗證。

- 等價：優化排程（prewarm clusters + _ocr_region）對每個 detect/compare 步驟的
  find_text 命中結果，必須與現行 per-rect union-chain 完全一致（dropped==0、
  false_pos==0），且每幀不劣化。
- 序列模擬：依序餵 test.png → test2.png → test3.png（模擬動畫切換），跨幀保留
  _xframe_ocr_cache，OCR 呼叫總數必須嚴格少於逐幀重跑。

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

from conftest import make_main_loop as _make_ml  # noqa: E402

from _loader import load_sibling  # noqa: E402
from core.rule_models import Rule, RuleGroup, Step  # noqa: E402

ROOT = _ROOT
DATA = Path(__file__).resolve().parent / "data"
JOB = DATA / "fixture_task.json"
FRAMES = ["test.png", "test2.png", "test3.png"]
WIN = (1920.0, 1080.0)

_ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
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


def _load_task_model():
    """從 fixture 建立 Rule/RuleGroup 物件，回傳 (rules, groups, active_group_ids,
    runnable_rule_ids)。runnable = 背景規則 + 啟用群組的規則（與 prewarm 收集範圍一致）。"""
    d = json.load(open(JOB, encoding="utf-8"))
    rules = {}
    for r in d.get("rules", []):
        rules[r["id"]] = Rule(
            id=r["id"],
            name=r.get("name", r["id"]),
            enabled=r.get("enabled", True),
            background=r.get("background", False),
            steps=[
                Step(type=s.get("type", ""), params=dict(s.get("params", {})))
                for s in r.get("steps", [])
            ],
        )
    groups = []
    active = []
    for g in d.get("groups", []):
        rg = RuleGroup(
            id=g["id"],
            name=g.get("name", g["id"]),
            enabled=g.get("enabled", True),
            mode=g.get("mode", "once"),
            repeat_times=g.get("repeat_times", 1),
            between_rounds_sec=g.get("between_rounds_sec", 0),
            rule_ids=[rid for rid in g.get("rule_ids", [])],
            order=g.get("order", "sequential"),
        )
        groups.append(rg)
        if rg.enabled:
            active.append(rg.id)
    runnable: set[str] = {r.id for r in rules.values() if r.background}
    for g in groups:
        if g.enabled:
            runnable.update(g.rule_ids)
    return rules, groups, active, runnable


def _extract_steps(rules, runnable):
    """啟用且本幀會執行的規則中，OCR 型 step（detect 文字 / compare），依規則順序 + 步驟序。"""
    steps = []
    for r in rules.values():
        if not r.enabled or r.id not in runnable:
            continue
        for i, s in enumerate(r.steps):
            if s.type == "detect":
                text = (s.params.get("text") or "").strip()
                if not text:
                    continue
                steps.append(
                    {
                        "rule_id": r.id,
                        "idx": i,
                        "type": "detect",
                        "roi": s.params.get("roi", {}),
                        "target": text,
                    }
                )
            elif s.type == "compare":
                steps.append(
                    {"rule_id": r.id, "idx": i, "type": "compare", "roi": s.params.get("roi", {})}
                )
    return steps


def _build_ml(rules, groups, active):
    ml = _make_ml()
    ml._rules = [r for r in rules.values()]
    ml._groups = groups
    ml._active_group_ids = active
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._rule_map = {r.id: r for r in rules.values()}
    ml._has_detect_rules = True
    return ml


def _count_calls(ml, img, steps, prewarm=False):
    """在 ml 上執行 detect/compare 的 _ocr_region 呼叫（可選 prewarm），
    回傳 (recognize 呼叫次數, {step_id: matched_text_or_None})。"""
    calls = {"n": 0}
    orig = _ocr.recognize

    def counting(crop, *a, **k):
        calls["n"] += 1
        return orig(crop, *a, **k)

    # _ml_mod.recognize 是 ocr_engine.recognize 的別名——直接換掉 module 層引用
    _ml_mod.recognize = counting
    hits = {}
    try:
        if prewarm:
            ml._prewarm_ocr_clusters(img, {"x": 0, "y": 0, "w": WIN[0], "h": WIN[1]})
        for i, st in enumerate(steps):
            roi = ml._resolve_roi(st["roi"], {"x": 0, "y": 0, "w": WIN[0], "h": WIN[1]})
            results = ml._ocr_region(img, roi)
            hits[i] = _find_in(results, st["target"]) if st["type"] == "detect" else bool(results)
    finally:
        _ml_mod.recognize = orig
    return calls["n"], hits


def _rect_px(st):
    roi = st["roi"]
    return (
        int(roi.get("x", 0) * WIN[0]),
        int(roi.get("y", 0) * WIN[1]),
        int(roi.get("w", 0) * WIN[0]),
        int(roi.get("h", 0) * WIN[1]),
    )


def _current_hits(img, steps):
    """現行 union-chain 語義：逐 step 依序呼叫 _ocr_region，每幀全新快取。"""
    rules, groups, active, _ = _load_task_model()
    ml = _build_ml(rules, groups, active)
    ml._frame_ocr_cache = {}
    calls, hits = _count_calls(ml, img, steps, prewarm=False)
    return calls, hits


@needs_model
def test_precluster_never_drops_and_not_worse():
    """方案 B 預聚類：每幀命中結果與現行完全一致，且 OCR 呼叫數不劣化。"""
    _ocr.init_engine()
    rules, groups, active, runnable = _load_task_model()
    steps = _extract_steps(rules, runnable)
    for frame in FRAMES:
        img = cv2.imread(str(DATA / frame))
        cur_calls, cur_hits = _current_hits(img, steps)
        ml = _build_ml(rules, groups, active)
        ml._frame_ocr_cache = {}
        opt_calls, opt_hits = _count_calls(ml, img, steps, prewarm=True)
        dropped = sum(1 for i in cur_hits if cur_hits[i] is not None and opt_hits[i] is None)
        false_pos = sum(1 for i in cur_hits if cur_hits[i] is None and opt_hits[i] is not None)
        assert dropped == 0, (
            f"{frame}: prewarm dropped {dropped} triggers (exact hit, prewarm miss)"
        )
        assert false_pos == 0, f"{frame}: prewarm false-positived {false_pos}"
        assert opt_calls <= cur_calls, (
            f"{frame}: prewarm used {opt_calls} calls vs current {cur_calls}"
        )


@needs_model
def test_sequence_optimization_effective():
    """模擬 3 幀連續切換：跨幀快取 + 每幀預聚類，總呼叫數必須嚴格少於逐幀重跑，
    且每幀命中結果與現行一致。"""
    _ocr.init_engine()
    rules, groups, active, runnable = _load_task_model()
    steps = _extract_steps(rules, runnable)

    cur_total = 0
    cur_per_frame = []
    for frame in FRAMES:
        img = cv2.imread(str(DATA / frame))
        c, _ = _current_hits(img, steps)
        cur_total += c
        cur_per_frame.append(c)

    # 優化：單一 MainLoop 跨幀（保留 _xframe_ocr_cache），每幀清幀內快取如 _process_rules
    ml = _build_ml(rules, groups, active)
    opt_total = 0
    opt_per_frame = []
    print()
    for frame in FRAMES:
        img = cv2.imread(str(DATA / frame))
        ml._frame_ocr_cache = {}
        calls, hits = _count_calls(ml, img, steps, prewarm=True)
        opt_total += calls
        opt_per_frame.append(calls)
        print(
            f"  [{frame:<10}] current={cur_per_frame[len(opt_per_frame) - 1]:>2} "
            f"optimized={calls:>2}  (xframe_cache={len(ml._xframe_ocr_cache)})"
        )

    print(f"  序列總計: current={cur_total} → optimized={opt_total}")
    for i, frame in enumerate(FRAMES):
        assert opt_per_frame[i] <= cur_per_frame[i], (
            f"{frame}: 每幀不劣化失敗 ({opt_per_frame[i]} > {cur_per_frame[i]})"
        )
    assert opt_total < cur_total, (
        f"序列優化應嚴格省呼叫: optimized={opt_total} vs current={cur_total}"
    )
    # 最後再驗證一次每幀命中等價（跨幀快取不得改變偵測結果）
    for frame in FRAMES:
        img = cv2.imread(str(DATA / frame))
        _, cur_hits = _current_hits(img, steps)
        ml._frame_ocr_cache = {}
        _, opt_hits = _count_calls(ml, img, steps, prewarm=True)
        dropped = sum(1 for i in cur_hits if cur_hits[i] is not None and opt_hits[i] is None)
        false_pos = sum(1 for i in cur_hits if cur_hits[i] is None and opt_hits[i] is not None)
        assert dropped == 0 and false_pos == 0, f"{frame}: 跨幀快取改變偵測結果"


@needs_model
def test_crossframe_cache_reuses_identical_crop():
    """同一幀連續兩次：第二次不得再跑 OCR（跨幀內容快取命中），結果逐位元一致。"""
    _ocr.init_engine()
    rules, groups, active, runnable = _load_task_model()
    steps = _extract_steps(rules, runnable)
    img = cv2.imread(str(DATA / "test.png"))
    ml = _build_ml(rules, groups, active)

    ml._frame_ocr_cache = {}
    c1, h1 = _count_calls(ml, img, steps, prewarm=True)
    ml._frame_ocr_cache = {}
    c2, h2 = _count_calls(ml, img, steps, prewarm=True)
    assert c2 == 0, f"相同內容第二幀應 0 次 OCR call，實際 {c2}"
    assert h1 == h2, "跨幀快取命中的偵測結果必須與首次一致"


def test_crop_hash_distinct():
    """_crop_hash 對不同內容必須產生不同指紋（LRU key 不會誤撞）。"""
    import numpy as np

    a = np.zeros((10, 20, 3), dtype=np.uint8)
    b = np.zeros_like(a)
    b[5, 5] = 255
    assert _ml_mod._crop_hash(a) != _ml_mod._crop_hash(b)
    assert _ml_mod._crop_hash(a) == _ml_mod._crop_hash(a.copy())
