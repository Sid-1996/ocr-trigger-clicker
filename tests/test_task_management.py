import json

import core.task_management as _tm
from core.rule_models import Rule, Step


def test_list_tasks_empty(tmp_tasks_dir):
    assert _tm.list_tasks() == []


def test_save_and_load_task(tmp_tasks_dir):
    rules = [Rule(id="r1", name="R1", enabled=True, steps=[Step(type="wait", params={"ms": 100})])]
    assert _tm.save_task("my_task", rules)
    assert _tm.list_tasks() == ["my_task"]
    loaded = _tm.load_task("my_task")
    assert len(loaded) == 1
    assert loaded[0].id == "r1"
    assert loaded[0].steps[0].params["ms"] == 100


def test_delete_task(tmp_tasks_dir):
    rules = [Rule(id="r1", name="R1", enabled=True, steps=[])]
    _tm.save_task("to_delete", rules)
    assert "to_delete" in _tm.list_tasks()
    assert _tm.delete_task("to_delete")
    assert "to_delete" not in _tm.list_tasks()


def test_rename_task(tmp_tasks_dir):
    rules = [Rule(id="r1", name="R1", enabled=True, steps=[])]
    _tm.save_task("old_name", rules)
    assert _tm.rename_task("old_name", "new_name")
    assert "new_name" in _tm.list_tasks()
    assert "old_name" not in _tm.list_tasks()


def test_rename_task_conflict(tmp_tasks_dir):
    rules = [Rule(id="r1", name="R1", enabled=True, steps=[])]
    _tm.save_task("task_a", rules)
    _tm.save_task("task_b", rules)
    assert not _tm.rename_task("task_a", "task_b")


def test_export_task(tmp_tasks_dir, tmp_path):
    rules = [Rule(id="r1", name="R1", enabled=True, steps=[Step(type="wait", params={"ms": 100})])]
    _tm.save_task("export_me", rules)
    dest = tmp_path / "exported.json"
    assert _tm.export_task("export_me", str(dest))
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert "_meta" in data
    assert "rules" in data
    assert len(data["rules"]) == 1


def test_import_task_basic(tmp_tasks_dir, tmp_path):
    src_data = {
        "rules": [
            {
                "id": "imp1",
                "name": "Imported",
                "enabled": True,
                "steps": [{"type": "wait", "params": {"ms": 200}}],
            }
        ]
    }
    src = tmp_path / "import_src.json"
    src.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

    result = _tm.import_task(str(src), regenerate_uuids=False)
    assert result == "import_src"
    loaded = _tm.load_task("import_src")
    assert len(loaded) == 1
    assert loaded[0].id == "imp1"


def test_import_task_regenerate_uuids(tmp_tasks_dir, tmp_path):
    src_data = {
        "rules": [
            {
                "id": "old_id",
                "name": "A",
                "enabled": True,
                "steps": [
                    {"type": "jump", "params": {"rule_id": "old_id"}},
                ],
            }
        ]
    }
    src = tmp_path / "uuid_import.json"
    src.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

    result = _tm.import_task(str(src), regenerate_uuids=True)
    assert result is not None
    imported = json.loads((tmp_tasks_dir / f"{result}.json").read_text("utf-8"))
    new_ids = {r["id"] for r in imported["rules"]}
    assert "old_id" not in new_ids
    jump_rid = imported["rules"][0]["steps"][0]["params"]["rule_id"]
    assert jump_rid in new_ids


def test_import_task_dedup_name(tmp_tasks_dir, tmp_path):
    src_data = {
        "rules": [
            {
                "id": "r1",
                "name": "R1",
                "enabled": True,
                "steps": [{"type": "wait", "params": {"ms": 100}}],
            }
        ]
    }
    src1 = tmp_path / "dup.json"
    src1.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

    result1 = _tm.import_task(str(src1))
    assert result1 == "dup"

    src2 = tmp_path / "sub" / "dup.json"
    src2.parent.mkdir(exist_ok=True)
    src2.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

    result2 = _tm.import_task(str(src2))
    assert result2 == "dup_1"


def test_preview_import_task_invalid(tmp_tasks_dir, tmp_path):
    assert _tm.preview_import_task("/nonexistent/path.json") is None

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("not json", encoding="utf-8")
    assert _tm.preview_import_task(str(bad_json)) is None


def test_import_task_invalid_rules_filtered(tmp_tasks_dir, tmp_path):
    src_data = {
        "rules": [
            {"id": "", "name": "No ID", "enabled": True, "steps": [{"type": "wait", "params": {}}]},
            {"id": "ok", "name": "", "enabled": True, "steps": [{"type": "wait", "params": {}}]},
            {
                "id": "ok2",
                "name": "Valid",
                "enabled": True,
                "steps": [{"type": "wait", "params": {}}],
            },
        ]
    }
    src = tmp_path / "filtered.json"
    src.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

    result = _tm.import_task(str(src))
    assert result is not None
    loaded = json.loads((tmp_tasks_dir / f"{result}.json").read_text("utf-8"))
    assert len(loaded["rules"]) == 1
    assert loaded["rules"][0]["id"] == "ok2"


def test_import_task_preserves_window_and_mode(tmp_tasks_dir, tmp_path):
    src_data = {
        "rules": [
            {
                "id": "imp1",
                "name": "Imported",
                "enabled": True,
                "steps": [{"type": "wait", "params": {"ms": 200}}],
            }
        ],
        "window_title": "StarSavior",
        "interaction_mode": "frida",
    }
    src = tmp_path / "preserve.json"
    src.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

    result = _tm.import_task(str(src), regenerate_uuids=False)
    assert result == "preserve"
    loaded = json.loads((tmp_tasks_dir / f"{result}.json").read_text("utf-8"))
    assert loaded["window_title"] == "StarSavior"
    assert loaded["interaction_mode"] == "frida"


def test_import_task_drops_invalid_mode_and_empty_title(tmp_tasks_dir, tmp_path):
    src_data = {
        "rules": [
            {
                "id": "imp1",
                "name": "Imported",
                "enabled": True,
                "steps": [{"type": "wait", "params": {"ms": 200}}],
            }
        ],
        "window_title": "",
        "interaction_mode": "postmessage",
    }
    src = tmp_path / "drop.json"
    src.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

    result = _tm.import_task(str(src), regenerate_uuids=False)
    assert result == "drop"
    loaded = json.loads((tmp_tasks_dir / f"{result}.json").read_text("utf-8"))
    assert "window_title" not in loaded
    assert "interaction_mode" not in loaded


def test_import_task_remaps_compare_on_fail_jump(tmp_tasks_dir, tmp_path):
    src_data = {
        "rules": [
            {
                "id": "cmp_rule",
                "name": "Compare",
                "enabled": True,
                "steps": [
                    {
                        "type": "compare",
                        "params": {
                            "operator": ">=",
                            "value": 0.0,
                            "on_fail": {"action": "jump", "rule_id": "target_rule"},
                        },
                    }
                ],
            },
            {
                "id": "target_rule",
                "name": "Target",
                "enabled": True,
                "steps": [{"type": "wait", "params": {"ms": 100}}],
            },
        ]
    }
    src = tmp_path / "compare_jump.json"
    src.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

    result = _tm.import_task(str(src), regenerate_uuids=True)
    assert result is not None
    imported = json.loads((tmp_tasks_dir / f"{result}.json").read_text("utf-8"))
    new_ids = {r["id"] for r in imported["rules"]}
    assert "cmp_rule" not in new_ids and "target_rule" not in new_ids
    on_fail = imported["rules"][0]["steps"][0]["params"]["on_fail"]
    assert on_fail["rule_id"] in new_ids


def test_import_task_remaps_detect_and_match_image_on_fail_jump(tmp_tasks_dir, tmp_path):
    src_data = {
        "rules": [
            {
                "id": "det_rule",
                "name": "Detect",
                "enabled": True,
                "steps": [
                    {
                        "type": "detect",
                        "params": {"text": "x", "on_fail": {"action": "jump", "rule_id": "dst"}},
                    },
                    {
                        "type": "match_image",
                        "params": {
                            "template_data": "a",
                            "on_fail": {"action": "jump", "rule_id": "dst"},
                        },
                    },
                ],
            },
            {
                "id": "dst",
                "name": "Dst",
                "enabled": True,
                "steps": [{"type": "wait", "params": {}}],
            },
        ]
    }
    src = tmp_path / "det_img_jump.json"
    src.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

    result = _tm.import_task(str(src), regenerate_uuids=True)
    assert result is not None
    imported = json.loads((tmp_tasks_dir / f"{result}.json").read_text("utf-8"))
    new_ids = {r["id"] for r in imported["rules"]}
    for step in imported["rules"][0]["steps"]:
        assert step["params"]["on_fail"]["rule_id"] in new_ids


def test_import_task_preserves_capture_size(tmp_tasks_dir, tmp_path):
    src_data = {
        "capture_size": [1920, 1080],
        "rules": [
            {
                "id": "imp1",
                "name": "Imported",
                "enabled": True,
                "steps": [{"type": "wait", "params": {"ms": 200}}],
            }
        ],
    }
    src = tmp_path / "with_capture_size.json"
    src.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

    result = _tm.import_task(str(src), regenerate_uuids=False)
    assert result == "with_capture_size"
    loaded = json.loads((tmp_tasks_dir / f"{result}.json").read_text("utf-8"))
    assert loaded["capture_size"] == [1920, 1080]


def test_import_task_drops_malformed_capture_size(tmp_tasks_dir, tmp_path):
    for bad in ("abc", [1], {"w": 10}):
        src_data = {
            "capture_size": bad,
            "rules": [
                {
                    "id": "imp1",
                    "name": "Imported",
                    "enabled": True,
                    "steps": [{"type": "wait", "params": {"ms": 200}}],
                }
            ],
        }
        src = tmp_path / "bad_cap.json"
        src.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

        result = _tm.import_task(str(src), regenerate_uuids=False)
        assert result is not None
        loaded = json.loads((tmp_tasks_dir / f"{result}.json").read_text("utf-8"))
        assert "capture_size" not in loaded


def test_import_task_rejects_non_dict_params(tmp_tasks_dir, tmp_path):
    src_data = {
        "rules": [
            {
                "id": "imp1",
                "name": "Imported",
                "enabled": True,
                "steps": [{"type": "jump", "params": "not_a_dict"}],
            }
        ]
    }
    src = tmp_path / "bad_params.json"
    src.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

    result = _tm.import_task(str(src), regenerate_uuids=True)
    assert result is None
    assert (tmp_tasks_dir / "bad_params.json").exists() is False
