import json

from core import run_config
from core.run_config import (
    get_capture_size,
    get_config_interaction_mode,
    get_task_interaction_mode,
    set_capture_size,
    set_task_interaction_mode,
    set_task_window,
)


def test_get_config_interaction_mode_reads_appdata(tmp_path, monkeypatch):
    """回歸測試：dev 模式不得讀專案根 config.json（曾殘留 frida 導致前景誤判後台）。"""
    monkeypatch.setenv("OCR_TRIGGER_DATA", str(tmp_path))
    cfg = tmp_path / "config.json"
    # 專案根的真實 config.json 含 "frida"——這裡寫 "pynput"，若函式仍讀專案根就會失敗
    cfg.write_text(json.dumps({"interaction_mode": "pynput"}), encoding="utf-8")
    assert get_config_interaction_mode() == "pynput"

    cfg.write_text(json.dumps({"interaction_mode": "frida"}), encoding="utf-8")
    assert get_config_interaction_mode() == "frida"

    cfg.write_text(json.dumps({"interaction_mode": "hybrid"}), encoding="utf-8")
    assert get_config_interaction_mode() == "hybrid"


def test_get_config_interaction_mode_defaults_and_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("OCR_TRIGGER_DATA", str(tmp_path))
    # 檔案不存在 → 預設 pynput
    assert get_config_interaction_mode() == "pynput"
    # 已淘汰/非法值 → 回退 pynput（與 task 層級驗證一致）
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"interaction_mode": "postmessage"}), encoding="utf-8")
    assert get_config_interaction_mode() == "pynput"
    cfg.write_text("not json", encoding="utf-8")
    assert get_config_interaction_mode() == "pynput"


def test_set_get_task_interaction_mode_round_trip(tmp_path):
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({"rules": []}, ensure_ascii=False), encoding="utf-8")

    assert set_task_interaction_mode(str(task_file), "frida")
    assert get_task_interaction_mode(str(task_file)) == "frida"

    assert set_task_interaction_mode(str(task_file), "hybrid")
    assert get_task_interaction_mode(str(task_file)) == "hybrid"

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


# ── get_capture_size mtime 快取 ──


def test_get_capture_size_basic_and_missing(tmp_path):
    task_file = tmp_path / "task.json"
    assert get_capture_size(str(task_file)) is None
    set_capture_size(str(task_file), 1280, 720)
    assert get_capture_size(str(task_file)) == [1280, 720]


def test_get_capture_size_cached_until_mtime_changes(tmp_path, monkeypatch):
    task_file = tmp_path / "task.json"
    set_capture_size(str(task_file), 1280, 720)
    get_capture_size(str(task_file))  # 填快取

    opens = []
    real_open = open

    def counting_open(path, *a, **k):
        opens.append(path)
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", counting_open)
    assert get_capture_size(str(task_file)) == [1280, 720]
    assert opens == [], "mtime 未變應走快取，不再讀檔"

    # 寫入端（set_capture_size 走 _replace_file）產生新 mtime → 快取自然失效
    monkeypatch.undo()
    set_capture_size(str(task_file), 1920, 1080)
    assert get_capture_size(str(task_file)) == [1920, 1080]


def test_get_capture_size_invalid_content_not_crash(tmp_path):
    task_file = tmp_path / "bad.json"
    task_file.write_text("{ not json", encoding="utf-8")
    assert get_capture_size(str(task_file)) is None

    task_file.write_text(json.dumps({"capture_size": ["abc", "def"]}), encoding="utf-8")
    assert get_capture_size(str(task_file)) is None, "非數字字串不應拋 ValueError"


def test_get_capture_size_returns_copy(tmp_path):
    run_config._capture_size_cache.clear()
    try:
        task_file = tmp_path / "task.json"
        set_capture_size(str(task_file), 1280, 720)
        a = get_capture_size(str(task_file))
        b = get_capture_size(str(task_file))
        assert a == b == [1280, 720]
        assert a is not b, "應回傳複本，呼叫端突變不得污染快取"
        a.append(1)
        assert get_capture_size(str(task_file)) == [1280, 720]
    finally:
        run_config._capture_size_cache.clear()
