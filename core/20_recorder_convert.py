"""錄製 session → 規則轉換器（後處理，離線執行，不依賴 GUI/Qt）。

輸入：錄製器（core/19_recorder.py）輸出的 session 目錄（events.json + frames/*.jpg）。
輸出：一組可執行的規則 + 群組（RuleGroup mode=once），供 GUI 存成任務。

每個滑鼠事件 → 一條規則：
- 點擊位置落在「動作前畫面」的 OCR 文字區塊上（有錨點）：
  規則 = detect(關鍵字=區塊文字, roi=區塊比例座標, on_fail=stop) + click(text_center)。
  引擎在場景還沒出現該文字時會逐幀等待偵測，達成「等畫面出現再點擊」的穩定同步，
  且點擊座標隨文字位置自動縮放，不怕視窗大小變化。
- 點擊位置沒有文字（點空白／點角色／截圖失敗）：
  規則 = wait(錄製間隔) + click(custom 比例座標)。純計時播放，只保證節奏一致。

比率座標一律為「視窗比例」（0~1，對全視窗尺寸），與引擎 _resolve_point/_resolve_roi
的預設一致（前景／後台皆以全視窗為基準）。
"""

import json
import logging
import uuid
from pathlib import Path

import cv2
import numpy as np

from _loader import load_sibling

_log = logging.getLogger(__name__)

_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
recognize = _ocr.recognize

_models = load_sibling("rule_models", "core/rule_models.py")
Step = _models.Step
Rule = _models.Rule
RuleGroup = _models.RuleGroup

_ANCHOR_RADIUS = 160  # 點擊座標周圍 OCR 搜尋半徑（px）
_ANCHOR_MARGIN = 12  # 文字區塊外擴距離（px），落在擴充框內即視為「點在文字上」
_ROI_EXPAND = 0.25  # 偵測 ROI 外擴比例（吸收執行時文字位置微動）
# 錨點 OCR 參數與執行時 _ocr_region（preprocess=False / max_side_len=0 / conf=0.25）一致，
# 確保轉換時辨識到的文字在執行時同樣會被找到（同一條 OCR 路徑）。
_MIN_OCR_CONF = 0.25
_FUZZY_THRESHOLD = 0.8
_FALLBACK_GAP_MS = (300, 5000)  # 無錨點規則的 wait 上下限
_DEFAULT_FIRST_GAP_MS = 1000


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _format_ts(dir_name: str) -> str:
    """session-YYYYMMDD-HHMMSS → 'YYYY-MM-DD HH:MM'。非預期格式回原名。"""
    name = Path(dir_name).name
    parts = name.split("-")
    if len(parts) == 3 and parts[0] == "session" and len(parts[1]) == 8 and len(parts[2]) == 6:
        return f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:8]} {parts[2][:2]}:{parts[2][2:4]}"
    return name


def _find_anchor(img_bgr, cx: int, cy: int):
    """點擊座標是否落在畫面文字區塊內。

    回傳 (keyword, roi_ratio) 或 None。roi_ratio 為外擴後文字區塊的視窗比例座標。
    多個區塊重疊時取面積最小者（最貼近點擊位置的單詞）。
    """
    h, w = img_bgr.shape[:2]
    if w <= 0 or h <= 0:
        return None
    x0 = max(0, cx - _ANCHOR_RADIUS)
    y0 = max(0, cy - _ANCHOR_RADIUS)
    x1 = min(w, cx + _ANCHOR_RADIUS)
    y1 = min(h, cy + _ANCHOR_RADIUS)
    crop = img_bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    try:
        results = recognize(
            rgb,
            roi_offset={"x": x0, "y": y0},
            preprocess=False,
            max_side_len=0,
            min_confidence=_MIN_OCR_CONF,
        )
    except Exception:
        _log.exception("動作前畫面 OCR 失敗，改用計時規則")
        return None

    best = None
    best_area = None
    for r in results:
        bx0, by0 = r.x - _ANCHOR_MARGIN, r.y - _ANCHOR_MARGIN
        bx1, by1 = r.x + r.w + _ANCHOR_MARGIN, r.y + r.h + _ANCHOR_MARGIN
        if not (bx0 <= cx <= bx1 and by0 <= cy <= by1):
            continue
        if not r.text.strip():
            continue
        area = r.w * r.h
        if (
            best is None
            or area < best_area
            or (area == best_area and r.confidence > best.confidence)
        ):
            best = r
            best_area = area
    if best is None:
        return None

    padx = max(2, int(best.w * _ROI_EXPAND))
    pady = max(2, int(best.h * _ROI_EXPAND))
    rx0 = max(0, best.x - padx)
    ry0 = max(0, best.y - pady)
    rx1 = min(w, best.x + best.w + padx)
    ry1 = min(h, best.y + best.h + pady)
    roi = {
        "x": round(rx0 / w, 4),
        "y": round(ry0 / h, 4),
        "w": round((rx1 - rx0) / w, 4),
        "h": round((ry1 - ry0) / h, 4),
    }
    return best.text.strip(), roi


def _build_anchored_rule(idx: int, keyword: str, roi: dict, button: str) -> Rule:
    return Rule(
        id=uuid.uuid4().hex[:12],
        name=f"{idx + 1:02d} {keyword[:12]}",
        enabled=True,
        steps=[
            Step(
                "detect",
                {
                    "text": keyword,
                    "roi": roi,
                    "match_mode": "fuzzy",
                    "fuzzy_threshold": _FUZZY_THRESHOLD,
                    "on_fail": "stop",
                },
            ),
            Step("click", {"target": "text_center", "button": button, "random_offset": 3}),
        ],
    )


def _build_timing_rule(
    idx: int, gap_ms: int, wx: int, wy: int, button: str, w: int, h: int
) -> Rule:
    steps = []
    if gap_ms > 0:
        steps.append(Step("wait", {"ms": gap_ms}))
    steps.append(
        Step(
            "click",
            {
                "target": "custom",
                "x": round(wx / w, 4) if w else 0,
                "y": round(wy / h, 4) if h else 0,
                "button": button,
                "random_offset": 0,
            },
        )
    )
    return Rule(id=uuid.uuid4().hex[:12], name=f"{idx + 1:02d} 點擊", enabled=True, steps=steps)


def _session_to_rules(session_dir: Path) -> tuple[list[Rule], dict]:
    evt_path = session_dir / "events.json"
    if not evt_path.exists():
        return [], {}
    try:
        with open(evt_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return [], {}
    events = data.get("events", []) or []
    frames_dir = session_dir / "frames"
    rules: list[Rule] = []
    stats = {"anchored": 0, "timing": 0, "skipped": 0}
    frame_cache: dict[str, object] = {}
    known_w, known_h = 0, 0
    prev_t = None

    for i, ev in enumerate(events):
        wx = int(ev.get("wx", 0) or 0)
        wy = int(ev.get("wy", 0) or 0)
        button = str(ev.get("button", "left") or "left")
        frame_name = str(ev.get("frame") or "")
        img = None
        if frame_name:
            if frame_name in frame_cache:
                img = frame_cache[frame_name]
            else:
                fp = frames_dir / frame_name
                if fp.exists():
                    img = cv2.imread(str(fp))
                    frame_cache[frame_name] = img
        h, w = img.shape[:2] if img is not None and img.size > 0 else (0, 0)
        if w > 0 and h > 0:
            known_w, known_h = w, h

        anchored = False
        if w > 0 and h > 0:
            anchor = _find_anchor(img, wx, wy)
            if anchor is not None:
                keyword, roi = anchor
                rules.append(_build_anchored_rule(len(rules), keyword, roi, button))
                stats["anchored"] += 1
                anchored = True

        if not anchored:
            if known_w <= 0 or known_h <= 0:
                stats["skipped"] += 1
                prev_t = ev.get("t", 0)
                continue
            t_now = ev.get("t", 0)
            if prev_t is not None and t_now:
                gap_ms = int(_clamp(round((t_now - prev_t) * 1000), *_FALLBACK_GAP_MS))
            else:
                gap_ms = _DEFAULT_FIRST_GAP_MS
            rules.append(_build_timing_rule(len(rules), gap_ms, wx, wy, button, known_w, known_h))
            stats["timing"] += 1
        prev_t = ev.get("t", 0)

    return rules, stats


def convert_sessions(session_dirs: list[Path]) -> dict:
    """把多個 session 目錄轉成規則 + 群組。

    每個 session 一組群組（mode=once），群組名取錄製時間戳。
    回傳 {"rules": [...], "groups": [...], "stats": {...}}。
    """
    rules: list[Rule] = []
    groups: list[RuleGroup] = []
    stats = {"sessions": 0, "rules": 0, "anchored": 0, "timing": 0, "skipped": 0}
    for d in session_dirs:
        if not d.is_dir():
            continue
        sess_rules, sess_stats = _session_to_rules(d)
        if not sess_rules:
            continue
        group = RuleGroup(
            id=uuid.uuid4().hex[:12],
            name=_format_ts(d.name),
            enabled=True,
            mode="once",
            rule_ids=[r.id for r in sess_rules],
            order="sequential",
        )
        rules.extend(sess_rules)
        groups.append(group)
        stats["sessions"] += 1
        stats["rules"] += len(sess_rules)
        stats["anchored"] += sess_stats.get("anchored", 0)
        stats["timing"] += sess_stats.get("timing", 0)
        stats["skipped"] += sess_stats.get("skipped", 0)
    return {"rules": rules, "groups": groups, "stats": stats}


if __name__ == "__main__":
    import json
    import tempfile

    print("=== Recorder Convert Self-Check ===\n")

    with tempfile.TemporaryDirectory() as td:
        sd = Path(td) / "session-20260812-140000"
        (sd / "frames").mkdir(parents=True)
        # 合成 800x600 空白 frame（無文字 → 全部走計時規則，驗證比例座標）
        frame = np.full((600, 800, 3), 200, dtype=np.uint8)
        for name, ev in zip(("00001.jpg", "00002.jpg", "00003.jpg"), (400, 800, 120)):
            cv2.imwrite(str(sd / "frames" / name), frame)
        events = [
            {"t": 100.0, "button": "left", "wx": 400, "wy": 300, "frame": "00001.jpg"},
            {"t": 101.2, "button": "left", "wx": 800, "wy": 500, "frame": "00002.jpg"},
            {"t": 110.0, "button": "right", "wx": 120, "wy": 90, "frame": "00003.jpg"},
        ]
        (sd / "events.json").write_text(
            json.dumps({"meta": {"window_title": "test"}, "events": events}),
            encoding="utf-8",
        )

        res = convert_sessions([sd])
        assert res["stats"]["sessions"] == 1, res["stats"]
        assert res["stats"]["rules"] == 3, res["stats"]
        assert res["stats"]["timing"] == 3, res["stats"]
        assert res["stats"]["anchored"] == 0
        g = res["groups"][0]
        assert g.mode == "once"
        assert len(g.rule_ids) == 3
        assert g.name == "2026-08-12 14:00", g.name

        r0 = res["rules"][0]
        assert r0.steps[0].type == "wait" and r0.steps[0].params["ms"] == _DEFAULT_FIRST_GAP_MS
        assert r0.steps[1].type == "click"
        assert r0.steps[1].params["target"] == "custom"
        assert abs(r0.steps[1].params["x"] - 400 / 800) < 1e-3
        assert abs(r0.steps[1].params["y"] - 300 / 600) < 1e-3
        print("  [OK] 計時規則（首事件 wait=1000ms，比例座標正確）")

        r1 = res["rules"][1]
        gap1 = r1.steps[0].params["ms"]
        assert 300 <= gap1 <= 5000, gap1
        r2 = res["rules"][2]
        assert r2.steps[0].params["ms"] == 5000, r2.steps[0].params  # 8.8s → 上限 5000
        print("  [OK] wait 間隔與 clamp")

        a = _build_anchored_rule(3, "確認", {"x": 0.2, "y": 0.3, "w": 0.1, "h": 0.05}, "left")
        assert a.steps[0].type == "detect" and a.steps[0].params["text"] == "確認"
        assert a.steps[0].params["on_fail"] == "stop"
        assert a.steps[1].type == "click" and a.steps[1].params["target"] == "text_center"
        print("  [OK] 錨點規則結構")

        t = _build_timing_rule(0, 800, 100, 50, "left", 800, 600)
        assert t.steps[1].params["x"] == round(100 / 800, 4)
        assert t.steps[1].params["y"] == round(50 / 600, 4)
        print("  [OK] 比例座標轉換")

        assert _format_ts("session-20260101-093005") == "2026-01-01 09:30"
        assert _format_ts("foobar") == "foobar"
        print("  [OK] 時間戳格式化")

    print("\n=== All checks passed ===")
