import json

from core.rule_models import Rule, RuleGroup, Step
from core.rule_serialization import (
    _dict_to_group,
    _dict_to_rule,
    _group_to_dict,
    _rule_to_dict,
    load_groups,
    load_rules,
    save_groups,
    save_rules,
)


def test_dict_to_rule_round_trip():
    rule = Rule(
        id="rt1",
        name="Round Trip",
        enabled=True,
        steps=[
            Step(
                type="detect",
                params={"text": "hello", "roi": {"x": 0, "y": 0, "w": 0, "h": 0}},
            ),
        ],
    )
    d = _rule_to_dict(rule)
    restored = _dict_to_rule(d)
    assert restored.id == rule.id
    assert restored.name == rule.name
    assert restored.enabled == rule.enabled
    assert len(restored.steps) == 1
    assert restored.steps[0].type == "detect"
    assert restored.steps[0].params["text"] == "hello"


def test_rule_to_dict_excludes_trigger_fields():
    rule = Rule(
        id="r1",
        name="R1",
        enabled=True,
        steps=[],
        background=False,
    )
    d = _rule_to_dict(rule)
    assert "trigger_count" not in d
    assert "last_trigger_time" not in d


def test_dict_to_group_round_trip():
    g = RuleGroup(
        id="g1",
        name="Group 1",
        enabled=False,
        mode="loop",
        repeat_times=3,
        between_rounds_sec=5,
        rule_ids=["r1", "r2"],
        order="parallel",
    )
    d = _group_to_dict(g)
    restored = _dict_to_group(d)
    assert restored.id == g.id
    assert restored.name == g.name
    assert restored.enabled == g.enabled
    assert restored.mode == g.mode
    assert restored.repeat_times == g.repeat_times
    assert restored.between_rounds_sec == g.between_rounds_sec
    assert restored.rule_ids == g.rule_ids
    assert restored.order == g.order


def test_dict_to_group_integer_coercion():
    g = _dict_to_group({"id": "gn", "name": "N", "rule_ids": [1, 2, 3]})
    assert g.rule_ids == ["1", "2", "3"]


def test_save_load_rules_preserves_groups(tmp_path):
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {"groups": [{"id": "g1", "name": "G1", "rule_ids": ["r1"]}], "window_title": "W"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rules = [Rule(id="r1", name="R1", enabled=True, steps=[Step(type="wait", params={"ms": 50})])]
    assert save_rules(rules, str(task_file))
    data = json.loads(task_file.read_text(encoding="utf-8"))
    assert "groups" in data
    assert data["window_title"] == "W"
    assert len(data["rules"]) == 1


def test_save_load_groups_preserves_rules(tmp_path):
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {"rules": [{"id": "r1", "name": "R1", "enabled": True, "steps": []}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    groups = [RuleGroup(id="g1", name="G1", rule_ids=["r1"])]
    assert save_groups(groups, str(task_file))
    data = json.loads(task_file.read_text(encoding="utf-8"))
    assert "rules" in data
    assert len(data["groups"]) == 1


def test_load_rules_nonexistent():
    assert load_rules("/nonexistent/path.json") == []


def test_load_groups_nonexistent():
    assert load_groups("/nonexistent/path.json") == []


def test_load_rules_corrupt(tmp_path):
    f = tmp_path / "corrupt.json"
    f.write_text("not json!!!", encoding="utf-8")
    assert load_rules(str(f)) == []


def test_load_groups_corrupt(tmp_path):
    f = tmp_path / "corrupt.json"
    f.write_text("not json!!!", encoding="utf-8")
    assert load_groups(str(f)) == []


def test_old_field_compat():
    old = {
        "id": "old",
        "name": "Old Rule",
        "enabled": True,
        "target_text": "text",
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "action_type": "click",
    }
    rule = _dict_to_rule(old)
    assert rule.id == "old"
    assert rule.steps[0].type == "detect"
    assert rule.steps[1].type == "click"


def test_missing_field_defaults():
    raw = {"id": "m", "name": "M", "steps": [{"type": "wait", "params": {"ms": 100}}]}
    rule = _dict_to_rule(raw)
    assert rule.enabled is True
    assert rule.background is False


def test_group_defaults():
    g = _dict_to_group({"id": "gd", "name": "GD"})
    assert g.enabled is True
    assert g.mode == "once"
    assert g.repeat_times == 1
    assert g.between_rounds_sec == 0
    assert g.rule_ids == []
    assert g.order == "sequential"
