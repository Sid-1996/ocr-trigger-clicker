import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402
from core.rule_models import Rule, RuleGroup, Step  # noqa: E402

_conv = load_sibling("recorder_convert", "core/20_recorder_convert.py")
_serial = load_sibling("rule_serialization", "core/rule_serialization.py")

merge_rule_entries = _conv.merge_rule_entries
save_task_with_groups = _serial.save_task_with_groups


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
