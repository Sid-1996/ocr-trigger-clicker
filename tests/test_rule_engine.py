import json
import tempfile
from pathlib import Path

from core.rule_migration import _migrate_v1_to_v2, migrate_v2_to_v3
from core.rule_models import Rule, RuleGroup, Step
from core.rule_serialization import (
    _dict_to_group,
    _dict_to_rule,
    _group_to_dict,
    _rule_to_dict,
    load_groups,
    load_rules,
    save_groups,
)

# ── V1 → V2 migration ──


def test_trigger_rule_migration():
    old_trigger = {
        "id": "rule_t1",
        "name": "觸發測試",
        "enabled": True,
        "target_text": "確認",
        "fuzzy": False,
        "fuzzy_threshold": 0.8,
        "roi": {"x": 100, "y": 200, "w": 300, "h": 100},
        "click_position": "text_center",
        "click_button": "left",
        "trigger_mode": "once",
        "action_type": "click",
        "post_delay_ms": 500,
    }
    new = _migrate_v1_to_v2(old_trigger)
    assert "steps" in new
    assert new["steps"][0]["type"] == "detect"
    assert new["steps"][1]["type"] == "click"
    assert new["steps"][2]["type"] == "wait"
    assert new["steps"][0]["params"]["text"] == "確認"
    assert new["steps"][0]["params"]["roi"]["x"] == 100
    assert "cooldown_ms" not in new["steps"][0]["params"]
    assert "trigger_mode" not in new["steps"][0]["params"]
    assert "max_triggers" not in new["steps"][0]["params"]


def test_sub_target_migration():
    old_trigger = {
        "id": "rule_t1",
        "name": "觸發測試",
        "enabled": True,
        "target_text": "確認",
        "roi": {"x": 100, "y": 200, "w": 300, "h": 100},
        "action_type": "click",
    }
    old_with_sub = dict(old_trigger)
    old_with_sub["sub_target_text"] = "子目標"
    old_with_sub["sub_roi"] = {"x": 10, "y": 20, "w": 50, "h": 30}
    new_sub = _migrate_v1_to_v2(old_with_sub)
    detect_count = sum(1 for s in new_sub["steps"] if s["type"] == "detect")
    assert detect_count == 2
    sub_detect = [s for s in new_sub["steps"] if s["type"] == "detect"][1]
    assert sub_detect["params"]["text"] == "子目標"
    assert sub_detect["params"]["roi"]["x"] == 10


def test_sub_target_zero_roi_inherits():
    old_trigger = {
        "id": "rule_t1",
        "name": "觸發測試",
        "enabled": True,
        "target_text": "確認",
        "roi": {"x": 100, "y": 200, "w": 300, "h": 100},
        "action_type": "click",
    }
    old_sub_zero = dict(old_trigger)
    old_sub_zero["sub_target_text"] = "子目標2"
    old_sub_zero["sub_roi"] = {"x": 0, "y": 0, "w": 0, "h": 0}
    new_sub_zero = _migrate_v1_to_v2(old_sub_zero)
    sub_d2 = [s for s in new_sub_zero["steps"] if s["type"] == "detect"][1]
    assert sub_d2["params"]["roi"]["x"] == 100


def test_compare_rule_migration():
    old_compare = {
        "id": "rule_c1",
        "name": "比較測試",
        "enabled": True,
        "rule_type": "compare",
        "target_text": "訓練畫面",
        "confirm_action_type": "click",
        "confirm_x": 100,
        "confirm_y": 200,
    }
    new_c = _migrate_v1_to_v2(old_compare)
    assert "steps" in new_c
    assert new_c["steps"][0]["type"] == "detect"
    assert new_c["steps"][1]["type"] == "click"
    assert new_c["steps"][1]["params"]["x"] == 100
    assert new_c["steps"][1]["params"]["y"] == 200


def test_compare_key_action_migration():
    old_compare = {
        "id": "rule_c1",
        "name": "比較測試",
        "enabled": True,
        "rule_type": "compare",
        "target_text": "訓練畫面",
        "confirm_action_type": "click",
        "confirm_x": 100,
        "confirm_y": 200,
    }
    old_compare_key = dict(old_compare)
    old_compare_key["confirm_action_type"] = "key"
    old_compare_key["confirm_key"] = " "
    new_ck = _migrate_v1_to_v2(old_compare_key)
    assert new_ck["steps"][1]["type"] == "key"
    assert new_ck["steps"][1]["params"]["key"] == " "


def test_key_action_migration():
    old_key_rule = {
        "id": "rule_key",
        "name": "按鍵規則",
        "enabled": True,
        "target_text": "請按任意鍵",
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "action_type": "key",
        "key": "Enter",
    }
    new_key = _migrate_v1_to_v2(old_key_rule)
    assert new_key["steps"][0]["type"] == "detect"
    assert new_key["steps"][1]["type"] == "key"
    assert new_key["steps"][1]["params"]["key"] == "Enter"


def test_minimal_rule_migration():
    old_minimal = {"id": "rule_min", "name": "最小規則", "enabled": True}
    new_min = _migrate_v1_to_v2(old_minimal)
    assert len(new_min["steps"]) >= 1
    assert new_min["steps"][0]["type"] == "detect"


# ── Round-trip serialization ──


def test_round_trip_serialization():
    rule = Rule(
        id="rule_rt1",
        name="來回測試",
        enabled=True,
        steps=[
            Step(
                type="detect",
                params={
                    "text": "測試",
                    "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
                    "match_mode": "fuzzy",
                    "fuzzy_threshold": 0.8,
                },
            ),
            Step(
                type="click",
                params={
                    "target": "text_center",
                    "x": 0,
                    "y": 0,
                    "button": "left",
                    "random_offset": 3,
                },
            ),
        ],
    )
    serialized = _rule_to_dict(rule)
    assert "steps" in serialized
    assert len(serialized["steps"]) == 2
    assert serialized["steps"][0]["type"] == "detect"
    assert serialized["steps"][0]["params"]["text"] == "測試"

    deserialized = _dict_to_rule(serialized)
    assert deserialized.id == "rule_rt1"
    assert len(deserialized.steps) == 2
    assert deserialized.steps[0].type == "detect"


# ── Old-format load ──


def test_old_format_load():
    old_trigger = {
        "id": "rule_t1",
        "name": "觸發測試",
        "enabled": True,
        "target_text": "確認",
        "roi": {"x": 100, "y": 200, "w": 300, "h": 100},
        "action_type": "click",
        "post_delay_ms": 500,
    }
    old_compare = {
        "id": "rule_c1",
        "name": "比較測試",
        "enabled": True,
        "rule_type": "compare",
        "target_text": "訓練畫面",
        "confirm_action_type": "click",
        "confirm_x": 100,
        "confirm_y": 200,
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"rules": [old_trigger, old_compare]}, f, ensure_ascii=False)
        tmp_path = f.name
    loaded = load_rules(tmp_path)
    assert len(loaded) == 2
    assert loaded[0].id == "rule_t1"
    assert len(loaded[0].steps) == 3
    assert loaded[0].steps[0].type == "detect"
    assert loaded[0].steps[1].type == "click"
    assert loaded[0].steps[2].type == "wait"
    assert loaded[1].steps[0].type == "detect"
    assert loaded[1].steps[1].type == "click"
    Path(tmp_path).unlink()


# ── Step defaults / normalization ──


def test_step_defaults():
    raw_normalize = {
        "id": "rule_norm",
        "name": "正規化",
        "enabled": True,
        "steps": [
            {"type": "click", "params": {"target": "custom", "x": "5", "y": "6"}},
            {"type": "detect", "params": {"on_fail": {"action": "key", "key": "Escape"}}},
        ],
    }
    normalized = _dict_to_rule(raw_normalize)
    assert normalized.steps[0].params["random_offset"] == 3
    assert normalized.steps[1].params["on_fail"] == {"action": "key", "key": "Escape"}


# ── Import UUID remap ──


def test_import_uuid_remap(tmp_tasks_dir):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        src_path = tmp_dir_path / "import_me.json"
        src_data = {
            "rules": [
                {
                    "id": "source_a",
                    "name": "來源 A",
                    "enabled": True,
                    "steps": [
                        {
                            "type": "detect",
                            "params": {
                                "text": "A",
                                "on_fail": {"action": "jump", "rule_id": "source_b"},
                            },
                        },
                        {
                            "type": "jump",
                            "params": {"rule_id": "source_b"},
                        },
                    ],
                },
                {
                    "id": "source_b",
                    "name": "來源 B",
                    "enabled": True,
                    "steps": [
                        {
                            "type": "jump",
                            "params": {"rule_id": "source_a"},
                        }
                    ],
                },
            ]
        }
        src_path.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

        from core.task_management import import_task

        imported_name = import_task(str(src_path), regenerate_uuids=True)
        assert imported_name == "import_me"
        imported = json.loads((tmp_tasks_dir / "import_me.json").read_text("utf-8"))

        new_ids = {r["id"] for r in imported["rules"]}
        assert "source_a" not in new_ids and "source_b" not in new_ids
        jump1 = imported["rules"][0]["steps"][1]["params"]["rule_id"]
        jump2 = imported["rules"][1]["steps"][0]["params"]["rule_id"]
        assert jump1 in new_ids
        assert jump2 in new_ids


# ── on_fail normalization ──


def test_on_fail_normalization():
    raw_on_fail = {
        "id": "rule_of",
        "name": "on_fail 測試",
        "enabled": True,
        "steps": [
            {"type": "detect", "params": {"text": "hi", "on_fail": "stop"}},
            {"type": "detect", "params": {"text": "hi2", "on_fail": "key"}},
            {
                "type": "detect",
                "params": {"text": "hi3", "on_fail": {"action": "key", "key": "F5"}},
            },
            {
                "type": "detect",
                "params": {"text": "hi4", "on_fail": {"action": "jump", "rule_id": "x"}},
            },
            {
                "type": "detect",
                "params": {"text": "hi5", "on_fail": {"action": "skip", "skip_to": 3}},
            },
        ],
    }
    of_rule = _dict_to_rule(raw_on_fail)
    assert of_rule.steps[0].params["on_fail"] == "stop"
    assert of_rule.steps[1].params["on_fail"] == "key"
    assert of_rule.steps[2].params["on_fail"] == {"action": "key", "key": "F5"}
    assert of_rule.steps[3].params["on_fail"] == {"action": "jump", "rule_id": "x"}
    assert of_rule.steps[4].params["on_fail"] == {"action": "skip", "skip_to": 3}


def test_match_image_on_fail_normalization():
    raw_mi_of = {
        "id": "rule_mi_of",
        "name": "match_image on_fail 測試",
        "enabled": True,
        "steps": [
            {"type": "match_image", "params": {"template_data": "a", "on_fail": "stop"}},
            {
                "type": "match_image",
                "params": {"template_data": "b", "on_fail": {"action": "skip", "skip_to": 5}},
            },
            {
                "type": "match_image",
                "params": {"template_data": "c", "on_fail": {"action": "key", "key": "F5"}},
            },
        ],
    }
    mi_of_rule = _dict_to_rule(raw_mi_of)
    assert mi_of_rule.steps[0].params["on_fail"] == "stop"
    assert mi_of_rule.steps[1].params["on_fail"] == {"action": "skip", "skip_to": 5}
    assert mi_of_rule.steps[2].params["on_fail"] == {"action": "key", "key": "F5"}


# ── RuleGroup ──


def test_rule_group_creation():
    g1 = RuleGroup(id="g1", name="Group One")
    assert g1.mode == "once"
    assert g1.repeat_times == 1
    assert g1.between_rounds_sec == 0
    assert g1.rule_ids == []
    assert g1.id == "g1"
    assert g1.name == "Group One"
    g2 = RuleGroup(id="g2", name="Repeat Five", mode="repeat", repeat_times=5, rule_ids=["a", "b"])
    assert g2.mode == "repeat"
    assert g2.repeat_times == 5
    assert g2.rule_ids == ["a", "b"]


def test_group_round_trip():
    g_orig = RuleGroup(
        id="rt1",
        name="Round Trip",
        enabled=False,
        mode="repeat",
        repeat_times=3,
        rule_ids=["r1", "r2"],
    )
    g_dict = _group_to_dict(g_orig)
    assert g_dict["id"] == "rt1"
    assert g_dict["enabled"] is False
    assert g_dict["mode"] == "repeat"
    assert g_dict["rule_ids"] == ["r1", "r2"]
    g_restored = _dict_to_group(g_dict)
    assert g_restored.id == g_orig.id
    assert g_restored.name == g_orig.name
    assert g_restored.enabled == g_orig.enabled
    assert g_restored.mode == g_orig.mode
    assert g_restored.repeat_times == g_orig.repeat_times
    assert g_restored.rule_ids == g_orig.rule_ids
    g_num = _dict_to_group({"id": "gn", "name": "N", "rule_ids": [1, 2]})
    assert g_num.rule_ids == ["1", "2"]


# ── V2 → V3 migration ──


def test_migrate_v2_to_v3_creates_default_group():
    data_v2 = {
        "run_mode": "repeat",
        "repeat_times": 5,
        "between_rounds_sec": 2,
        "rules": [
            {
                "id": "r1",
                "name": "Rule 1",
                "enabled": True,
                "steps": [{"type": "wait", "params": {"ms": 100}}],
            },
            {
                "id": "r2",
                "name": "Rule 2",
                "enabled": True,
                "background": False,
                "steps": [{"type": "wait", "params": {"ms": 100}}],
            },
        ],
    }
    data_v3 = migrate_v2_to_v3(dict(data_v2))
    assert "groups" in data_v3
    assert len(data_v3["groups"]) == 1
    g_def = data_v3["groups"][0]
    assert g_def["id"] == "__default__"
    assert g_def["mode"] == "repeat"
    assert g_def["repeat_times"] == 5
    assert g_def["between_rounds_sec"] == 2
    assert set(g_def["rule_ids"]) == {"r1", "r2"}
    assert "run_mode" not in data_v3
    assert "repeat_times" not in data_v3
    assert "between_rounds_sec" not in data_v3
    assert len(data_v3["rules"]) == 2


def test_migrate_v2_to_v3_excludes_background():
    data_bg = {
        "rules": [
            {
                "id": "bg",
                "name": "Background",
                "enabled": True,
                "background": True,
                "steps": [{"type": "wait", "params": {"ms": 100}}],
            },
            {
                "id": "fg",
                "name": "Foreground",
                "enabled": True,
                "steps": [{"type": "wait", "params": {"ms": 100}}],
            },
        ],
    }
    data_bg_v3 = migrate_v2_to_v3(dict(data_bg))
    assert len(data_bg_v3["groups"]) == 1
    assert "bg" not in data_bg_v3["groups"][0]["rule_ids"]
    assert "fg" in data_bg_v3["groups"][0]["rule_ids"]


# ── save_groups / load_groups ──


def test_save_load_groups_round_trip(tmp_path):
    task_file = tmp_path / "test_task.json"
    task_file.write_text(
        json.dumps({"rules": [], "window_title": "My Window"}, ensure_ascii=False),
        encoding="utf-8",
    )
    groups_in = [
        RuleGroup(id="g1", name="G1", mode="loop", rule_ids=["r1"]),
        RuleGroup(id="g2", name="G2", mode="once", rule_ids=["r2", "r3"]),
    ]
    ok = save_groups(groups_in, str(task_file))
    assert ok
    groups_out = load_groups(str(task_file))
    assert len(groups_out) == 2
    assert groups_out[0].id == "g1"
    assert groups_out[1].rule_ids == ["r2", "r3"]
    saved = json.loads(task_file.read_text(encoding="utf-8"))
    assert saved["window_title"] == "My Window"


# ── load_rules auto-migration ──


def test_load_rules_auto_migration(tmp_path):
    task_file = tmp_path / "auto_migrate.json"
    task_file.write_text(
        json.dumps(
            {
                "run_mode": "once",
                "repeat_times": 1,
                "rules": [
                    {
                        "id": "r1",
                        "name": "R1",
                        "enabled": True,
                        "steps": [{"type": "wait", "params": {"ms": 100}}],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rules = load_rules(str(task_file))
    assert len(rules) == 1
    final = json.loads(task_file.read_text(encoding="utf-8"))
    assert "groups" in final
    assert "run_mode" not in final
    assert final["groups"][0]["id"] == "__default__"
    assert final["groups"][0]["mode"] == "once"
