import json

from core.trigger_log import log_trigger


def test_log_trigger_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr("core.trigger_log._LOG_DIR", tmp_path)
    log_trigger("r1", "Rule One", "my_task", "g1")
    log_file = tmp_path / "triggers.jsonl"
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["rule_id"] == "r1"
    assert entry["rule_name"] == "Rule One"
    assert entry["task"] == "my_task"
    assert entry["group"] == "g1"
    assert "ts" in entry


def test_log_trigger_appends(tmp_path, monkeypatch):
    monkeypatch.setattr("core.trigger_log._LOG_DIR", tmp_path)
    log_trigger("r1", "A", "task1")
    log_trigger("r2", "B", "task2", "g2")
    lines = (tmp_path / "triggers.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    e1 = json.loads(lines[0])
    e2 = json.loads(lines[1])
    assert e1["rule_id"] == "r1"
    assert e2["rule_id"] == "r2"
    assert e2["group"] == "g2"


def test_log_trigger_empty_group(tmp_path, monkeypatch):
    monkeypatch.setattr("core.trigger_log._LOG_DIR", tmp_path)
    log_trigger("r3", "C", "task3")
    entry = json.loads((tmp_path / "triggers.jsonl").read_text(encoding="utf-8").strip())
    assert entry["group"] == ""


def test_log_trigger_io_error(tmp_path, monkeypatch):
    monkeypatch.setattr("core.trigger_log._LOG_DIR", tmp_path)
    original_open = open

    def fail_open(*args, **kwargs):
        if args and "triggers.jsonl" in str(args[0]):
            raise OSError("disk full")
        return original_open(*args, **kwargs)

    monkeypatch.setattr("builtins.open", fail_open)
    log_trigger("r4", "D", "task4")
