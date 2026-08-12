"""錄製 session → 規則轉換器（後處理，離線執行，不依賴 GUI/Qt）。

輸入：錄製器（core/19_recorder.py）輸出的 session 目錄（events.json + frames/*.jpg）。
輸出：一組可執行的規則 + 群組（RuleGroup mode=once），供 GUI 存成任務。

每個滑鼠事件 → 一條規則：
- 點擊位置落在「動作前畫面」的 OCR 文字區塊上（有錨點）：
  規則 = detect(關鍵字=區塊文字, roi=區塊比例座標, on_fail=stop) + click(text_center)。
  引擎在場景還沒出現該文字時會逐幀等待偵測，達成「等畫面出現再點擊」的穩定同步，
  且點擊座標隨文字位置自動縮放，不怕視窗大小變化。
- 點擊位置沒有文字（點圖示／點角色）：
  先嘗試「模板錨點」：以點擊座標為中心向外擴張，裁出有紋理的特徵方塊存成
  match_image（base64 內嵌）＋ click(text_center)，達成「等圖示出現再點擊」的視覺同步。
- 區域無特徵（點空白）或方塊被視窗邊緣裁剪：
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

_tmpl = load_sibling("template_matching", "core/11_template_matching.py")
img_to_b64 = _tmpl.img_to_b64

_ANCHOR_RADIUS = 160  # 點擊座標周圍 OCR 搜尋半徑（px）
_ANCHOR_MARGIN = 12  # 文字區塊外擴距離（px），落在擴充框內即視為「點在文字上」
_ROI_EXPAND = 0.25  # 偵測 ROI 外擴比例（吸收執行時文字位置微動）
# 模板錨點參數
_TMPL_MIN_RADIUS = 24  # 模板起始半徑（px），由小向外擴張找特徵
_TMPL_MAX_RADIUS = 56  # 模板最大半徑（px），超過仍無特徵則放棄
_TMPL_STEP = 8  # 外擴步進（px）
_TMPL_STD_MIN = 16.0  # 灰階標準差門檻：低於此視為純色／無特徵
_TMPL_THRESHOLD = 0.8  # match_image 相似度門檻（與引擎預設一致）
_TMPL_SEARCH_EXPAND = 1.0  # 搜尋 ROI 相對模板邊的外擴倍率（吸收執行時位移）
# 錨點 OCR 參數與執行時 _ocr_region（preprocess=False / max_side_len=0 / conf=0.25）一致，
# 確保轉換時辨識到的文字在執行時同樣會被找到（同一條 OCR 路徑）。
_MIN_OCR_CONF = 0.25
_FUZZY_THRESHOLD = 0.8
_FALLBACK_GAP_MS = (300, 5000)  # 無錨點規則的 wait 上下限
_DEFAULT_FIRST_GAP_MS = 1000


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _resolved(defaults: dict | None, key: str, fallback):
    """從設定窗預設 dict 取值；defaults 為 None 或缺 key 時回 fallback（維持既有行為）。"""
    return defaults.get(key, fallback) if defaults else fallback


def _with_after_delay(params: dict, defaults: dict | None) -> dict:
    """動作後延遲預設（>0 才寫入，0/缺省＝不等待）。"""
    ad = _resolved(defaults, "after_delay_ms", 0)
    if ad > 0:
        params["after_delay_ms"] = ad
    return params


def _with_detect_after_delay(params: dict, defaults: dict | None) -> dict:
    """偵測後延遲預設（>0 才寫入，0/缺省＝不等待）。套用於 detect / match_image 步驟。"""
    ad = _resolved(defaults, "detect_after_delay_ms", 0)
    if ad > 0:
        params["after_delay_ms"] = ad
    return params


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


def _make_template(img_bgr, cx: int, cy: int):
    """以點擊座標為中心向外擴張，裁出有紋理的特徵方塊作為模板。

    由小到大逐級外擴，選取第一個「完整位於視窗內且灰階 std 達標」的最小方塊；
    被視窗邊緣裁剪或全為純色（無特徵）時回傳 None → 呼叫端退回計時規則。
    回傳 (base64 模板, 搜尋 ROI 視窗比例座標)。
    """
    h, w = img_bgr.shape[:2]
    if w <= 0 or h <= 0:
        return None
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    for r in range(_TMPL_MIN_RADIUS, _TMPL_MAX_RADIUS + 1, _TMPL_STEP):
        if cx - r < 0 or cy - r < 0 or cx + r > w or cy + r > h:
            continue  # 被邊緣裁剪 → 模板中心會偏移點擊座標，放棄
        x0, y0 = cx - r, cy - r
        x1, y1 = cx + r, cy + r
        if float(gray[y0:y1, x0:x1].std()) < _TMPL_STD_MIN:
            continue  # 純色／無特徵 → 再外擴
        b64 = img_to_b64(img_bgr[y0:y1, x0:x1])
        padx = int((x1 - x0) * _TMPL_SEARCH_EXPAND)
        pady = int((y1 - y0) * _TMPL_SEARCH_EXPAND)
        sx0, sy0 = max(0, x0 - padx), max(0, y0 - pady)
        sx1, sy1 = min(w, x1 + padx), min(h, y1 + pady)
        roi = {
            "x": round(sx0 / w, 4),
            "y": round(sy0 / h, 4),
            "w": round((sx1 - sx0) / w, 4),
            "h": round((sy1 - sy0) / h, 4),
        }
        return b64, roi
    return None


def _build_anchored_rule(
    idx: int, keyword: str, roi: dict, button: str, defaults: dict | None = None
) -> Rule:
    return Rule(
        id=uuid.uuid4().hex[:12],
        name=f"{idx + 1:02d} {keyword[:12]}",
        enabled=True,
        steps=[
            Step(
                "detect",
                _with_detect_after_delay(
                    {
                        "text": keyword,
                        "roi": roi,
                        "match_mode": "fuzzy",
                        "fuzzy_threshold": _resolved(defaults, "fuzzy_threshold", _FUZZY_THRESHOLD),
                        "on_fail": "stop",
                    },
                    defaults,
                ),
            ),
            Step(
                "click",
                _with_after_delay(
                    {
                        "target": "text_center",
                        "button": button,
                        "random_offset": _resolved(defaults, "random_offset", 3),
                    },
                    defaults,
                ),
            ),
        ],
    )


def _build_template_rule(
    idx: int, b64: str, roi: dict, button: str, defaults: dict | None = None
) -> Rule:
    mt_params = {
        "template_data": b64,
        "roi": roi,
        "threshold": _resolved(defaults, "template_threshold", _TMPL_THRESHOLD),
        "on_fail": "stop",
    }
    # 顏色容差僅在設定窗有提供時寫入（0 = 不啟用顏色過濾）
    ct = _resolved(defaults, "color_tolerance", None)
    if ct is not None:
        mt_params["color_tolerance"] = ct
    return Rule(
        id=uuid.uuid4().hex[:12],
        name=f"{idx + 1:02d} 圖示",
        enabled=True,
        steps=[
            Step("match_image", _with_detect_after_delay(mt_params, defaults)),
            Step(
                "click",
                _with_after_delay(
                    {
                        "target": "text_center",
                        "button": button,
                        "random_offset": _resolved(defaults, "random_offset", 3),
                    },
                    defaults,
                ),
            ),
        ],
    )


def _build_timing_rule(
    idx: int,
    gap_ms: int,
    wx: int,
    wy: int,
    button: str,
    w: int,
    h: int,
    defaults: dict | None = None,
) -> Rule:
    steps = []
    if gap_ms > 0:
        steps.append(Step("wait", {"ms": gap_ms}))
    steps.append(
        Step(
            "click",
            _with_after_delay(
                {
                    "target": "custom",
                    "x": round(wx / w, 4) if w else 0,
                    "y": round(wy / h, 4) if h else 0,
                    "button": button,
                    "random_offset": _resolved(defaults, "random_offset", 0),
                },
                defaults,
            ),
        )
    )
    return Rule(id=uuid.uuid4().hex[:12], name=f"{idx + 1:02d} 點擊", enabled=True, steps=steps)


def _session_to_rules(session_dir: Path, defaults: dict | None = None) -> tuple[list[Rule], dict]:
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
    stats = {"anchored": 0, "template": 0, "timing": 0, "skipped": 0}
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
                rules.append(_build_anchored_rule(len(rules), keyword, roi, button, defaults))
                stats["anchored"] += 1
                anchored = True

        if not anchored and w > 0 and h > 0:
            tpl = _make_template(img, wx, wy)
            if tpl is not None:
                b64, roi = tpl
                rules.append(_build_template_rule(len(rules), b64, roi, button, defaults))
                stats["template"] += 1
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
            rules.append(
                _build_timing_rule(len(rules), gap_ms, wx, wy, button, known_w, known_h, defaults)
            )
            stats["timing"] += 1
        prev_t = ev.get("t", 0)

    return rules, stats


def convert_sessions(session_dirs: list[Path], defaults: dict | None = None) -> dict:
    """把多個 session 目錄轉成規則 + 群組。

    每個 session 一組群組（mode=once），群組名取錄製時間戳。
    defaults 為設定窗預設值 dict（fuzzy_threshold / template_threshold / color_tolerance /
    random_offset / after_delay_ms），None 時用模組內建常數。
    回傳 {"rules": [...], "groups": [...], "stats": {...}}。
    """
    rules: list[Rule] = []
    groups: list[RuleGroup] = []
    stats = {"sessions": 0, "rules": 0, "anchored": 0, "template": 0, "timing": 0, "skipped": 0}
    for d in session_dirs:
        if not d.is_dir():
            continue
        sess_rules, sess_stats = _session_to_rules(d, defaults)
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
        stats["template"] += sess_stats.get("template", 0)
        stats["timing"] += sess_stats.get("timing", 0)
        stats["skipped"] += sess_stats.get("skipped", 0)
    return {"rules": rules, "groups": groups, "stats": stats}


def merge_rule_entries(
    existing_rules: list[Rule],
    existing_groups: list[RuleGroup],
    new_rules: list[Rule],
    new_groups: list[RuleGroup],
) -> tuple[list[Rule], list[RuleGroup]]:
    """把新轉換出的規則+群組合併進既有任務資料（GUI「加入既有任務」用）。

    - rule.id / group.id 若有碰撞，以 uuid4 重刷並維持唯一。
    - 新規則 id 被重刷時，同步更新其所屬新群組的 rule_ids（轉換規則不含
      step-level 的 rule_id 跳轉，只需處理群組層級引用）。
    回傳 (merged_rules, merged_groups)，不修改傳入物件。
    """
    used_rule_ids = {r.id for r in existing_rules}
    used_group_ids = {g.id for g in existing_groups}
    id_map: dict[str, str] = {}

    merged_rules = list(existing_rules)
    for r in new_rules:
        if r.id in used_rule_ids:
            nid = uuid.uuid4().hex[:12]
            while nid in used_rule_ids:
                nid = uuid.uuid4().hex[:12]
            id_map[r.id] = nid
            used_rule_ids.add(nid)
            merged_rules.append(
                Rule(
                    id=nid,
                    name=r.name,
                    enabled=r.enabled,
                    steps=list(r.steps),
                    background=r.background,
                    notes=r.notes,
                )
            )
        else:
            used_rule_ids.add(r.id)
            merged_rules.append(r)

    merged_groups = list(existing_groups)
    for g in new_groups:
        gid = g.id
        if gid in used_group_ids:
            gid = uuid.uuid4().hex[:12]
            while gid in used_group_ids:
                gid = uuid.uuid4().hex[:12]
            used_group_ids.add(gid)
        else:
            used_group_ids.add(gid)
        merged_groups.append(
            RuleGroup(
                id=gid,
                name=g.name,
                enabled=g.enabled,
                mode=g.mode,
                repeat_times=g.repeat_times,
                between_rounds_sec=g.between_rounds_sec,
                rule_ids=[id_map.get(rid, rid) for rid in g.rule_ids],
                order=g.order,
            )
        )
    return merged_rules, merged_groups


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

        # ── 設定窗預設套用：after_delay_ms / random_offset / thresholds ──
        defaults = {
            "fuzzy_threshold": 0.7,
            "template_threshold": 0.9,
            "color_tolerance": 20,
            "random_offset": 5,
            "after_delay_ms": 800,
        }
        resd = convert_sessions([sd], defaults)
        # 空白 frame → 全走計時規則：click 套用 random_offset + after_delay_ms
        rd0 = resd["rules"][0]
        assert rd0.steps[1].params["random_offset"] == 5, rd0.steps[1].params
        assert rd0.steps[1].params["after_delay_ms"] == 800, rd0.steps[1].params
        # 預設 0 時不寫入欄位（缺欄位＝0 行為等價）
        resz = convert_sessions([sd], {"random_offset": 0, "after_delay_ms": 0})
        assert "after_delay_ms" not in resz["rules"][0].steps[1].params
        assert resz["rules"][0].steps[1].params["random_offset"] == 0
        # anchored / template 規則直接套用 fuzzy_threshold / threshold / color_tolerance
        a = _build_anchored_rule(
            3, "確認", {"x": 0.2, "y": 0.3, "w": 0.1, "h": 0.05}, "left", defaults
        )
        assert a.steps[0].params["fuzzy_threshold"] == 0.7
        assert a.steps[1].params["random_offset"] == 5
        assert a.steps[1].params["after_delay_ms"] == 800
        t = _build_template_rule(
            3, "b64", {"x": 0.2, "y": 0.3, "w": 0.1, "h": 0.05}, "left", defaults
        )
        assert t.steps[0].params["threshold"] == 0.9
        assert t.steps[0].params["color_tolerance"] == 20
        assert t.steps[1].params["random_offset"] == 5
        assert t.steps[1].params["after_delay_ms"] == 800
        # 無 defaults → 維持既有常數、不寫 color_tolerance
        a0 = _build_anchored_rule(3, "確認", {"x": 0.2, "y": 0.3, "w": 0.1, "h": 0.05}, "left")
        assert a0.steps[0].params["fuzzy_threshold"] == _FUZZY_THRESHOLD
        assert "after_delay_ms" not in a0.steps[1].params
        t0 = _build_template_rule(3, "b64", {"x": 0.2, "y": 0.3, "w": 0.1, "h": 0.05}, "left")
        assert t0.steps[0].params["threshold"] == _TMPL_THRESHOLD
        assert "color_tolerance" not in t0.steps[0].params
        print(
            "  [OK] 設定窗預設套用（random_offset / after_delay_ms / thresholds / color_tolerance）"
        )

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

        # ── 模板錨點：紋理特徵 → match_image 規則 ──
        sd2 = Path(td) / "session-20260812-150000"
        (sd2 / "frames").mkdir(parents=True)
        frame2 = np.full((600, 800, 3), 200, dtype=np.uint8)
        # 同心圓圖示：有紋理但 OCR 不讀為文字（寫 PNG 避免 JPEG 偽影誤判）
        cv2.circle(frame2, (400, 300), 44, (60, 80, 120), -1)
        cv2.circle(frame2, (400, 300), 22, (200, 210, 220), -1)
        cv2.imwrite(str(sd2 / "frames" / "00001.png"), frame2)
        events2 = [{"t": 1.0, "button": "left", "wx": 400, "wy": 300, "frame": "00001.png"}]
        (sd2 / "events.json").write_text(
            json.dumps({"meta": {"window_title": "test"}, "events": events2}), encoding="utf-8"
        )
        res2 = convert_sessions([sd2])
        assert res2["stats"]["template"] == 1, res2["stats"]
        assert res2["stats"]["timing"] == 0, res2["stats"]
        r = res2["rules"][0]
        assert r.steps[0].type == "match_image"
        assert r.steps[0].params["template_data"]
        assert r.steps[0].params["on_fail"] == "stop"
        assert r.steps[1].type == "click" and r.steps[1].params["target"] == "text_center"
        print("  [OK] 紋理特徵 → 模板錨點規則（match_image + click）")

        # ── 邊緣裁剪：點擊靠視窗邊緣 → 回退計時 ──
        sd3 = Path(td) / "session-20260812-160000"
        (sd3 / "frames").mkdir(parents=True)
        cv2.imwrite(str(sd3 / "frames" / "00001.jpg"), frame2)
        events3 = [{"t": 1.0, "button": "left", "wx": 5, "wy": 5, "frame": "00001.jpg"}]
        (sd3 / "events.json").write_text(
            json.dumps({"meta": {"window_title": "test"}, "events": events3}), encoding="utf-8"
        )
        res3 = convert_sessions([sd3])
        assert res3["stats"]["timing"] == 1 and res3["stats"]["template"] == 0, res3["stats"]
        print("  [OK] 邊緣裁剪 → 計時規則")

        # ── 純色無特徵 → 回退計時 ──
        sd4 = Path(td) / "session-20260812-170000"
        (sd4 / "frames").mkdir(parents=True)
        cv2.imwrite(str(sd4 / "frames" / "00001.jpg"), frame)  # 全灰 200
        events4 = [{"t": 1.0, "button": "left", "wx": 400, "wy": 300, "frame": "00001.jpg"}]
        (sd4 / "events.json").write_text(
            json.dumps({"meta": {"window_title": "test"}, "events": events4}), encoding="utf-8"
        )
        res4 = convert_sessions([sd4])
        assert res4["stats"]["timing"] == 1 and res4["stats"]["template"] == 0, res4["stats"]
        print("  [OK] 純色無特徵 → 計時規則")

        # ── merge_rule_entries：合併進既有任務，id 碰撞重刷並同步 rule_ids ──
        ext_rule = Rule(
            id="ext-rule",
            name="既有規則",
            enabled=True,
            steps=[Step(type="click", params={"target": "custom", "x": 0.1, "y": 0.1})],
        )
        ext_group = RuleGroup(
            id="ext-group", name="既有群組", enabled=True, mode="once", rule_ids=["ext-rule"]
        )
        new_rule_col = Rule(
            id="ext-rule",
            name="新規則撞 id",
            enabled=True,
            steps=[Step(type="click", params={"x": 0.2, "y": 0.2})],
        )
        new_grp = RuleGroup(
            id="ext-rule",
            name="新群組撞 id",
            enabled=True,
            mode="once",
            rule_ids=["ext-rule", "keep-rule"],
        )
        new_keep = Rule(
            id="keep-rule",
            name="不衝突",
            enabled=True,
            steps=[Step(type="wait", params={"ms": 100})],
        )
        mr, mg = merge_rule_entries([ext_rule], [ext_group], [new_rule_col, new_keep], [new_grp])
        assert len(mr) == 3
        map_rule = {r.id: r for r in mr}
        # 碰撞的規則 id 被重刷，且新群組 rule_ids 同步指向最新 id
        assert "ext-rule" not in map_rule or map_rule["ext-rule"] is ext_rule
        assert "keep-rule" in map_rule
        new_ids = [r.id for r in mr[1:]]
        assert len(set(new_ids)) == len(new_ids)
        assert "keep-rule" in mg[1].rule_ids
        assert mg[1].rule_ids[0] == mr[1].id
        # 群組 id 碰撞重刷，但不影響既有群組
        assert mg[0].id == "ext-group"
        assert len({g.id for g in mg}) == 2
        assert map_rule.get("keep-rule").steps[0].type == "wait"
        print("  [OK] merge_rule_entries：id 碰撞重刷 + rule_ids 同步")

    print("\n=== All checks passed ===")
