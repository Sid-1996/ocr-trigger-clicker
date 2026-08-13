import json

from core.run_config import (
    get_task_interaction_mode,
    set_task_interaction_mode,
    set_task_window,
)


def test_set_get_task_interaction_mode_round_trip(tmp_path):
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({"rules": []}, ensure_ascii=False), encoding="utf-8")

    assert set_task_interaction_mode(str(task_file), "frida")
    assert get_task_interaction_mode(str(task_file)) == "frida"

    assert set_task_interaction_mode(str(task_file), "pynput")
    assert get_task_interaction_mode(str(task_file)) == "pynput"


def test_get_task_interaction_mode_defaults(tmp_path):
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps({"window_title": "Win", "interaction_mode": "postmessage"}),
        encoding="utf-8",
    )
    assert get_task_interaction_mode(str(task_file)) is None

    task_file.write_text(json.dumps({"window_title": "Win"}), encoding="utf-8")
    assert get_task_interaction_mode(str(task_file)) is None


def test_get_task_interaction_mode_missing_file(tmp_path):
    assert get_task_interaction_mode(str(tmp_path / "nope.json")) is None


def test_set_task_interaction_mode_rejects_invalid(tmp_path):
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({"rules": []}), encoding="utf-8")
    assert not set_task_interaction_mode(str(task_file), "postmessage")
    assert not set_task_interaction_mode(str(task_file), "dxcam")
    assert get_task_interaction_mode(str(task_file)) is None


def test_set_task_interaction_mode_preserves_other_keys(tmp_path):
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {"window_title": "Win", "capture_size": [1280, 720], "rules": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert set_task_interaction_mode(str(task_file), "frida")
    data = json.loads(task_file.read_text(encoding="utf-8"))
    assert data["window_title"] == "Win"
    assert data["capture_size"] == [1280, 720]
    assert data["interaction_mode"] == "frida"


def test_set_task_interaction_mode_creates_file(tmp_path):
    task_file = tmp_path / "new_task.json"
    assert set_task_interaction_mode(str(task_file), "pynput")
    data = json.loads(task_file.read_text(encoding="utf-8"))
    assert data["interaction_mode"] == "pynput"


def test_task_window_and_mode_independent(tmp_path):
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({"rules": []}), encoding="utf-8")
    set_task_window(str(task_file), "StarSavior")
    set_task_interaction_mode(str(task_file), "frida")
    data = json.loads(task_file.read_text(encoding="utf-8"))
    assert data["window_title"] == "StarSavior"
    assert data["interaction_mode"] == "frida"
