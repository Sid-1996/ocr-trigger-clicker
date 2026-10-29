import json

import pytest

from core.rule_models import Rule, RuleGroup, Step
from core.rule_serialization import (
    RuleFileError,
    _dict_to_group,
    _dict_to_rule,
    _group_to_dict,
    _rule_to_dict,
    load_groups,
    load_rules,
    save_groups,
    save_rules,
    save_task_with_groups,
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
        quiet=True,
    )
    d = _rule_to_dict(rule)
    restored = _dict_to_rule(d)
    assert restored.id == rule.id
    assert restored.name == rule.name
    assert restored.enabled == rule.enabled
    assert restored.quiet is True
    assert len(restored.steps) == 1
    assert restored.steps[0].type == "detect"
    assert restored.steps[0].params["text"] == "hello"


def test_match_image_color_mask_round_trip():
    mask = {
        "colors": [[10, 20, 30], [40, 50, 60]],
        "tolerance": 20,
        "mode": "keep",
    }
    rule = Rule(
        id="cm1",
        name="Color Mask",
        enabled=True,
        steps=[
            Step(
                type="match_image",
                params={"template_data": "abc==", "color_mask": mask},
            )
        ],
    )
    restored = _dict_to_rule(_rule_to_dict(rule))
    assert restored.steps[0].params["color_mask"] == mask


def test_dict_to_rule_quiet_defaults_false():
    restored = _dict_to_rule({"id": "q0", "name": "Q0", "enabled": True, "steps": []})
    assert restored.quiet is False


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
    with pytest.raises(RuleFileError) as exc:
        load_rules(str(f))
    assert str(f) in str(exc.value)


def test_load_groups_corrupt(tmp_path):
    f = tmp_path / "corrupt.json"
    f.write_text("not json!!!", encoding="utf-8")
    with pytest.raises(RuleFileError) as exc:
        load_groups(str(f))
    assert str(f) in str(exc.value)


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


def test_after_delay_ms_round_trip():
    rule = Rule(
        id="ad1",
        name="After Delay",
        enabled=True,
        steps=[
            Step(
                type="click",
                params={"target": "text_center", "x": 0, "y": 0, "after_delay_ms": 800},
            ),
        ],
    )
    restored = _dict_to_rule(_rule_to_dict(rule))
    assert restored.steps[0].params["after_delay_ms"] == 800


def test_after_delay_ms_defaults_zero_for_all_actions():
    for t in ("click", "key", "drag", "scroll"):
        rule = _dict_to_rule({"id": f"r-{t}", "name": "R", "steps": [{"type": t, "params": {}}]})
        assert rule.steps[0].params.get("after_delay_ms") == 0, t


def test_after_delay_ms_coerces_bad_input():
    rule = _dict_to_rule(
        {
            "id": "ad-bad",
            "name": "B",
            "steps": [{"type": "click", "params": {"after_delay_ms": "not-a-number"}}],
        }
    )
    assert rule.steps[0].params["after_delay_ms"] == 0
    rule_neg = _dict_to_rule(
        {"id": "ad-neg", "name": "N", "steps": [{"type": "key", "params": {"after_delay_ms": -50}}]}
    )
    assert rule_neg.steps[0].params["after_delay_ms"] == 0


def test_scroll_delay_ms_kept_distinct():
    rule = _dict_to_rule(
        {
            "id": "ad-sc",
            "name": "S",
            "steps": [
                {"type": "scroll", "params": {"delay_ms": 40, "after_delay_ms": 500}},
            ],
        }
    )
    assert rule.steps[0].params["delay_ms"] == 40
    assert rule.steps[0].params["after_delay_ms"] == 500


def test_dict_to_group_invalid_values_are_safe():
    g = _dict_to_group(
        {
            "id": "g1",
            "name": "G1",
            "mode": "weird",
            "order": "weird",
            "repeat_times": "abc",
            "between_rounds_sec": None,
            "rule_ids": "not-a-list",
        }
    )
    assert g.mode == "once"
    assert g.order == "sequential"
    assert g.repeat_times == 1
    assert g.between_rounds_sec == 0
    assert g.rule_ids == []


def test_load_rules_bad_encoding_and_non_dict_root(tmp_path):
    bad_encoding = tmp_path / "bad_utf8.json"
    bad_encoding.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(RuleFileError):
        load_rules(str(bad_encoding))
    with pytest.raises(RuleFileError):
        load_groups(str(bad_encoding))

    non_dict = tmp_path / "list_root.json"
    non_dict.write_text("[]", encoding="utf-8")
    with pytest.raises(RuleFileError):
        load_rules(str(non_dict))
    with pytest.raises(RuleFileError):
        load_groups(str(non_dict))


def test_load_rejects_non_array_rules_and_groups(tmp_path):
    bad_rules = tmp_path / "bad_rules.json"
    bad_rules.write_text('{"rules": {}}', encoding="utf-8")
    with pytest.raises(RuleFileError):
        load_rules(str(bad_rules))

    bad_groups = tmp_path / "bad_groups.json"
    bad_groups.write_text('{"rules": [], "groups": {}}', encoding="utf-8")
    with pytest.raises(RuleFileError):
        load_rules(str(bad_groups))
    with pytest.raises(RuleFileError):
        load_groups(str(bad_groups))


def test_load_accepts_empty_datasets(tmp_path):
    f = tmp_path / "empty.json"
    f.write_text('{"rules": [], "groups": []}', encoding="utf-8")
    assert load_rules(str(f)) == []
    assert load_groups(str(f)) == []


def test_save_refuses_to_overwrite_corrupt_json(tmp_path):
    f = tmp_path / "corrupt.json"
    original = b'{"rules": ['
    f.write_bytes(original)
    rule = Rule(id="r1", name="R1", enabled=True, steps=[])
    assert save_rules([rule], str(f)) is False
    assert save_groups([RuleGroup(id="g1", name="G1")], str(f)) is False
    assert save_task_with_groups([rule], [], str(f)) is False
    assert f.read_bytes() == original


def test_save_refuses_malformed_array_fields(tmp_path):
    f = tmp_path / "bad_shape.json"
    original = '{"rules": {}, "groups": {}}'
    f.write_text(original, encoding="utf-8")
    rule = Rule(id="r1", name="R1", enabled=True, steps=[])
    assert save_rules([rule], str(f)) is False
    assert save_groups([RuleGroup(id="g1", name="G1")], str(f)) is False
    assert save_task_with_groups([rule], [], str(f)) is False
    assert f.read_text(encoding="utf-8") == original


def test_save_succeeds_after_repair(tmp_path):
    f = tmp_path / "repair.json"
    f.write_text("not json", encoding="utf-8")
    rule = Rule(id="r1", name="R1", enabled=True, steps=[])
    assert save_rules([rule], str(f)) is False
    f.write_text('{"rules": [], "groups": []}', encoding="utf-8")
    assert save_rules([rule], str(f)) is True
    assert [r.id for r in load_rules(str(f))] == ["r1"]
    assert json.loads(f.read_text(encoding="utf-8"))["groups"] == []


MALFORMED_TASK_PAYLOADS = [
    '{"rules": [{"id": "r", "name": "R", "steps": []}], "groups": {}}',
    '{"rules": 5, "groups": [{"id": "g", "name": "G"}]}',
    '{"rules": [{"id": "r", "name": "R", "steps": 5}], "groups": []}',
    '{"rules": [{"id": "r", "name": "R", "steps": null}], "groups": []}',
    '{"rules": [{"id": "r", "name": "R", "steps": [1]}], "groups": []}',
    '{"rules": [1], "groups": []}',
]


@pytest.mark.parametrize("payload", MALFORMED_TASK_PAYLOADS)
def test_load_rejects_malformed_nested_rules(tmp_path, payload):
    f = tmp_path / "bad.json"
    f.write_text(payload, encoding="utf-8")
    with pytest.raises(RuleFileError):
        load_rules(str(f))
    with pytest.raises(RuleFileError):
        load_groups(str(f))


@pytest.mark.parametrize("payload", MALFORMED_TASK_PAYLOADS)
def test_save_refuses_any_malformed_task_structure(tmp_path, payload):
    f = tmp_path / "bad.json"
    f.write_text(payload, encoding="utf-8")
    rule = Rule(id="r1", name="R1", enabled=True, steps=[])
    group = RuleGroup(id="g1", name="G1")
    assert save_rules([rule], str(f)) is False
    assert save_groups([group], str(f)) is False
    assert save_task_with_groups([rule], [group], str(f)) is False
    assert f.read_text(encoding="utf-8") == payload


def test_load_migration_does_not_rewrite_invalid_legacy_file(tmp_path):
    f = tmp_path / "legacy_bad.json"
    original = '{"rules": [{"id": "a", "name": "A", "steps": 5}]}'
    f.write_text(original, encoding="utf-8")
    with pytest.raises(RuleFileError):
        load_rules(str(f))
    assert f.read_text(encoding="utf-8") == original
