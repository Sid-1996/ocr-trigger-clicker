import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _loader import load_sibling

_utils = load_sibling("file_utils", "core/file_utils.py")
_replace_file = _utils._replace_file


def get_task_window(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        title = data.get("window_title", "")
        return title if title else None
    except (OSError, json.JSONDecodeError):
        return None


def set_task_window(path: str, title: str) -> bool:
    tmp_path: str = ""
    try:
        p = Path(path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        data["window_title"] = title
        with tempfile.NamedTemporaryFile(
            "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path = f.name
        _replace_file(tmp_path, str(p))
        return True
    except (OSError, json.JSONDecodeError):
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return False


def get_run_mode(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"mode": "once", "repeat_times": 1, "between_rounds_sec": 0}
    return {
        "mode": str(data.get("run_mode", "once")),
        "repeat_times": int(data.get("repeat_times", 1)),
        "between_rounds_sec": int(data.get("between_rounds_sec", 0)),
    }


def set_run_mode(path: str, mode: str, repeat_times: int = 1, between_rounds_sec: int = 0) -> bool:
    tmp_path: str = ""
    try:
        p = Path(path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        data["run_mode"] = mode
        data["repeat_times"] = repeat_times
        data["between_rounds_sec"] = between_rounds_sec
        with tempfile.NamedTemporaryFile(
            "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path = f.name
        _replace_file(tmp_path, str(p))
        return True
    except (OSError, json.JSONDecodeError):
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return False


def get_capture_size(path: str) -> list | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cs = data.get("capture_size")
        if isinstance(cs, list) and len(cs) == 2:
            return [int(cs[0]), int(cs[1])]
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return None


def set_capture_size(path: str, w: int, h: int) -> bool:
    tmp_path: str = ""
    try:
        p = Path(path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        data["capture_size"] = [w, h]
        with tempfile.NamedTemporaryFile(
            "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path = f.name
        _replace_file(tmp_path, str(p))
        return True
    except (OSError, json.JSONDecodeError):
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        return False
