import json
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402
from core.rule_models import Rule, RuleGroup, Step  # noqa: E402

_conv = load_sibling("recorder_convert", "core/20_recorder_convert.py")
_serial = load_sibling("rule_serialization", "core/rule_serialization.py")

merge_rule_entries = _conv.merge_rule_entries
save_task_with_groups = _serial.save_task_with_groups
convert_sessions = _conv.convert_sessions


def _rule(rid):
    return Rule(
        id=rid,
        name=f"rule-{rid}",
        enabled=True,
        steps=[Step(type="wait", params={"ms": 100})],
    )


def _group(gid, rule_ids):
    return RuleGroup(id=gid, name=gid, enabled=True, mode="once", rule_ids=rule_ids)


def _ids(items):
    return [x.id for x in items]


def test_merge_no_collision():
    ext_rules, ext_groups = [_rule("a")], [_group("g1", ["a"])]
    new_rules, new_groups = [_rule("b")], [_group("g2", ["b"])]
    rules, groups = merge_rule_entries(ext_rules, ext_groups, new_rules, new_groups)
    assert _ids(rules) == ["a", "b"]
    assert _ids(groups) == ["g1", "g2"]
    assert groups[1].rule_ids == ["b"]
    # 傳入物件不被修改
    assert ext_rules[0].id == "a"
    assert ext_groups[0].rule_ids == ["a"]


def test_merge_rule_id_collision():
    ext_rules, ext_groups = [_rule("x")], [_group("g1", ["x"])]
    # 新規則 id 撞既有規則，且新群組的 rule_ids 也指向同一個碰撞 id
    new_rules, new_groups = [_rule("x")], [_group("g2", ["x"])]
    rules, groups = merge_rule_entries(ext_rules, ext_groups, new_rules, new_groups)
    assert len(_ids(rules)) == 2 and len(set(_ids(rules))) == 2
    assert "x" in _ids(rules)  # 既有規則保留原 id
    assert len(_ids(groups)) == 2 and len(set(_ids(groups))) == 2
    # 被重刷的新規則 id 必須同步進新群組的 rule_ids
    assert groups[1].id == "g2"
    assert groups[1].rule_ids == [rules[1].id]
    assert groups[0].rule_ids == ["x"]


def test_merge_group_id_collision():
    ext_rules, ext_groups = [_rule("a")], [_group("same", ["a"])]
    new_rules, new_groups = [_rule("b")], [_group("same", ["b"])]
    rules, groups = merge_rule_entries(ext_rules, ext_groups, new_rules, new_groups)
    assert _ids(groups) == ["same", groups[1].id]
    # 新群組 id 被重刷但 rule_ids 仍指向新規則
    assert groups[1].rule_ids == ["b"]
    assert groups[0].id == "same" and groups[0].rule_ids == ["a"]


def test_merge_both_collide_and_keep_keep():
    ext_rules, ext_groups = [_rule("dup")], [_group("dup", ["dup"])]
    new_rules, new_groups = [_rule("dup"), _rule("fresh")], [_group("dup", ["dup", "fresh"])]
    rules, groups = merge_rule_entries(ext_rules, ext_groups, new_rules, new_groups)
    by_id = {r.id: r for r in rules}
    assert by_id["dup"] is ext_rules[0] or by_id["dup"].steps[0].type == "wait"
    assert "fresh" in by_id
    new_ids = _ids(rules)[1:]
    assert len(new_ids) == len(set(new_ids))
    assert groups[0].id == "dup" and groups[0].rule_ids == ["dup"]  # 既有不受影響
    merged = groups[1]
    assert merged.id != "dup"
    assert len(set(merged.rule_ids)) == 2
    assert "fresh" in merged.rule_ids
    assert merged.rule_ids[0] in set(_ids(rules))


def test_merge_existing_empty():
    rules, groups = merge_rule_entries([], [], [_rule("a")], [_group("g", ["a"])])
    assert _ids(rules) == ["a"]
    assert groups[0].rule_ids == ["a"]


def test_save_task_with_groups_atomic_and_preserves_keys(tmp_path):
    p = tmp_path / "task.json"
    p.write_text(
        json.dumps(
            {
                "window_title": "MyGame",
                "_meta": {"format_version": 1},
                "rules": [
                    {
                        "id": "old",
                        "name": "old",
                        "enabled": True,
                        "steps": [],
                        "background": False,
                        "notes": "",
                    }
                ],
                "groups": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ok = save_task_with_groups([_rule("new")], [_group("g", ["new"])], str(p))
    assert ok
    data = json.loads(p.read_text(encoding="utf-8"))
    # 既有鍵保留
    assert data["window_title"] == "MyGame"
    assert data["_meta"]["format_version"] == 1
    assert len(data["rules"]) == 1 and data["rules"][0]["id"] == "new"
    assert data["groups"][0]["id"] == "g"


def _blank_session(tmp_path, name="session-20260812-140000", n=2):
    """合成無文字的空白 frame session（全走計時規則，不需 OCR model）。"""
    import cv2
    import numpy as np

    sd = tmp_path / name
    (sd / "frames").mkdir(parents=True)
    frame = np.full((600, 800, 3), 200, dtype=np.uint8)
    events = []
    for i in range(n):
        fname = f"{i + 1:05d}.jpg"
        cv2.imwrite(str(sd / "frames" / fname), frame)
        events.append(
            {"t": 100.0 + i * 1.2, "button": "left", "wx": 400, "wy": 300, "frame": fname}
        )
    (sd / "events.json").write_text(
        json.dumps({"meta": {"window_title": "test"}, "events": events}), encoding="utf-8"
    )
    return sd


def test_convert_applies_defaults(tmp_path):
    """轉換時套用設定窗預設（random_offset / after_delay_ms），0 時不寫入欄位。"""
    sd = _blank_session(tmp_path)
    res = convert_sessions([sd], {"random_offset": 5, "after_delay_ms": 800})
    assert res["stats"]["rules"] == 2, res["stats"]
    for rule in res["rules"]:
        click = [s for s in rule.steps if s.type == "click"][0]
        assert click.params["random_offset"] == 5
        assert click.params["after_delay_ms"] == 800


def test_convert_defaults_zero_omits_after_delay(tmp_path):
    """after_delay_ms=0 時不寫入欄位（缺欄位＝0 行為等價，維持 JSON 精簡）。"""
    sd = _blank_session(tmp_path)
    res = convert_sessions([sd], {"random_offset": 0, "after_delay_ms": 0})
    for rule in res["rules"]:
        click = [s for s in rule.steps if s.type == "click"][0]
        assert "after_delay_ms" not in click.params
        assert click.params["random_offset"] == 0


def test_convert_detect_after_delay_applied():
    """偵測後延時預設套用到轉換出的 detect / match_image 步驟，0 不寫入。"""
    roi = {"x": 0, "y": 0, "w": 0.2, "h": 0.1}
    defs = {"detect_after_delay_ms": 500}
    ar = _conv._build_anchored_rule(0, "確定", roi, "left", defs)
    detect = [s for s in ar.steps if s.type == "detect"][0]
    assert detect.params["after_delay_ms"] == 500
    tr = _conv._build_template_rule(0, "b64data", roi, "left", defs)
    mt = [s for s in tr.steps if s.type == "match_image"][0]
    assert mt.params["after_delay_ms"] == 500
    # 明確設 0 → 不寫入欄位
    ar0 = _conv._build_anchored_rule(0, "確定", roi, "left", {"detect_after_delay_ms": 0})
    d0 = [s for s in ar0.steps if s.type == "detect"][0]
    assert "after_delay_ms" not in d0.params


def test_convert_no_defaults_keeps_builtins(tmp_path):
    """未傳 defaults 時：延時用錄製專屬內建 500ms（穩定性優先），random_offset 維持 0。"""
    sd = _blank_session(tmp_path)
    res = convert_sessions([sd])
    for rule in res["rules"]:
        click = [s for s in rule.steps if s.type == "click"][0]
        assert click.params["after_delay_ms"] == _conv._RECORD_AFTER_DELAY_MS
        assert click.params["random_offset"] == 0


def test_convert_missing_delay_keys_fall_back_to_record_defaults(tmp_path):
    """defaults 缺延時 key（例如舊設定檔）→ 兜底錄製專屬內建 500ms；明確 0 仍尊重。"""
    sd = _blank_session(tmp_path)
    res = convert_sessions([sd], {"random_offset": 2})
    for rule in res["rules"]:
        click = [s for s in rule.steps if s.type == "click"][0]
        assert click.params["after_delay_ms"] == _conv._RECORD_AFTER_DELAY_MS
    # 偵測步驟同樣兜底（detect / match_image）
    ar = _conv._build_anchored_rule(0, "確定", {"x": 0, "y": 0, "w": 0.1, "h": 0.1}, "left", {})
    d = [s for s in ar.steps if s.type == "detect"][0]
    assert d.params["after_delay_ms"] == _conv._RECORD_DETECT_AFTER_DELAY_MS


def test_build_template_rule_applies_threshold_and_color(tmp_path):
    """模板規則套用 template_threshold / color_tolerance，缺省時不寫 color_tolerance。"""
    r = _conv._build_template_rule(
        0,
        "b64",
        {"x": 0, "y": 0, "w": 0.1, "h": 0.1},
        "left",
        {"template_threshold": 0.9, "color_tolerance": 20, "random_offset": 4},
    )
    mt = r.steps[0]
    assert mt.params["threshold"] == 0.9
    assert mt.params["color_tolerance"] == 20
    assert r.steps[1].params["random_offset"] == 4
    r0 = _conv._build_template_rule(0, "b64", {"x": 0, "y": 0, "w": 0.1, "h": 0.1}, "left")
    assert r0.steps[0].params["threshold"] == _conv._TMPL_THRESHOLD
    assert "color_tolerance" not in r0.steps[0].params


def test_build_template_rule_writes_capture_size():
    """錄製模板要帶自己的來源尺寸，避免 runtime 誤用任務層或退化多尺度。"""
    r = _conv._build_template_rule(
        0,
        "b64",
        {"x": 0, "y": 0, "w": 0.1, "h": 0.1},
        "left",
        capture_size=(1600, 900),
    )
    assert r.steps[0].params["capture_size"] == [1600, 900]


def test_convert_uses_event_window_size_not_clipped_frame_size(tmp_path):
    """視窗跨螢幕時截圖會被裁切；比例分母要用事件記錄的視窗尺寸。"""
    sd = _blank_session(tmp_path)
    data = json.loads((sd / "events.json").read_text(encoding="utf-8"))
    for ev in data["events"]:
        ev["window_size"] = [1000, 800]
        ev["wx"] = 500
        ev["wy"] = 400
    (sd / "events.json").write_text(json.dumps(data), encoding="utf-8")

    res = convert_sessions([sd])
    click = [s for s in res["rules"][0].steps if s.type == "click"][0]
    assert abs(click.params["x"] - 0.5) < 1e-3
    assert abs(click.params["y"] - 0.5) < 1e-3


def test_convert_uses_anchor_when_frame_matches_window(tmp_path, monkeypatch):
    """幀尺寸等於視窗尺寸時，維持原本錨點路徑。"""
    sd = _blank_session(tmp_path, n=1)
    data = json.loads((sd / "events.json").read_text(encoding="utf-8"))
    data["events"][0]["window_size"] = [800, 600]
    (sd / "events.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(
        _conv, "_find_anchor", lambda *a, **k: ("確認", {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2})
    )

    res = convert_sessions([sd])

    assert res["stats"]["anchored"] == 1
    assert res["rules"][0].steps[0].type == "detect"


def test_convert_skips_anchor_and_template_for_clipped_frame(tmp_path, monkeypatch):
    """舊 session 的裁切幀原點未知；不可用錯位影像產生錨點/模板規則。"""
    sd = _blank_session(tmp_path, n=1)
    data = json.loads((sd / "events.json").read_text(encoding="utf-8"))
    data["events"][0]["window_size"] = [1000, 800]
    (sd / "events.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(_conv, "_find_anchor", lambda *a, **k: pytest.fail("裁切幀不該找錨點"))
    monkeypatch.setattr(_conv, "_make_template", lambda *a, **k: pytest.fail("裁切幀不該做模板"))

    res = convert_sessions([sd])

    assert res["stats"]["timing"] == 1
    assert res["stats"]["anchored"] == res["stats"]["template"] == 0
    click = [s for s in res["rules"][0].steps if s.type == "click"][0]
    assert abs(click.params["x"] - 0.4) < 1e-3
    assert abs(click.params["y"] - 0.375) < 1e-3


def test_convert_keeps_timing_event_without_frame_if_window_size_known(tmp_path):
    """截圖失敗但事件有 window_size 時，仍可轉成計時規則，不應被跳過。"""
    sd = tmp_path / "session-20260812-140001"
    sd.mkdir()
    events = [
        {"t": 100.0, "button": "left", "wx": 400, "wy": 300, "window_size": [800, 600]},
    ]
    (sd / "events.json").write_text(json.dumps({"meta": {}, "events": events}), encoding="utf-8")
    res = convert_sessions([sd])
    assert res["stats"]["timing"] == 1
    click = [s for s in res["rules"][0].steps if s.type == "click"][0]
    assert click.params["x"] == 0.5
    assert click.params["y"] == 0.5


def test_build_anchored_rule_applies_fuzzy_threshold():
    """錨點規則套用 fuzzy_threshold；match_mode 固定 fuzzy（錨點設計）。"""
    r = _conv._build_anchored_rule(
        0, "確認", {"x": 0, "y": 0, "w": 0.1, "h": 0.1}, "left", {"fuzzy_threshold": 0.7}
    )
    assert r.steps[0].params["match_mode"] == "fuzzy"
    assert r.steps[0].params["fuzzy_threshold"] == 0.7
    r0 = _conv._build_anchored_rule(0, "確認", {"x": 0, "y": 0, "w": 0.1, "h": 0.1}, "left")
    assert r0.steps[0].params["fuzzy_threshold"] == _conv._FUZZY_THRESHOLD
