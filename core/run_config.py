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


_VALID_INTERACTION_MODES = frozenset({"pynput", "frida", "hybrid"})


def get_config_power_save() -> bool:
    """Read power_save_mode from config.json (app-level). Defaults to False.

    True 時 OCR 引擎限制 intra-op 執行緒數，降低 CPU 占用（代價：單次辨識稍慢）。
    """
    try:
        from core._paths import get_data_path

        p = Path(get_data_path("config.json"))
        with open(p, encoding="utf-8") as f:
            return bool(json.load(f).get("power_save_mode", False))
    except Exception:
        return False


def get_config_interaction_mode() -> str:
    """Read interaction_mode from config.json (app-level). Defaults to "pynput".

    一律讀 %APPDATA%（get_data_path），與 GUI 的 _config_path 同源——dev 模式若讀
    專案根 config.json 會與 GUI 分歧，導致前景模式被誤判為後台（commit 歷史 bug）。
    """
    try:
        from core._paths import get_data_path

        p = Path(get_data_path("config.json"))
        with open(p, encoding="utf-8") as f:
            mode = json.load(f).get("interaction_mode", "pynput")
        return mode if mode in _VALID_INTERACTION_MODES else "pynput"
    except Exception:
        return "pynput"


def get_task_interaction_mode(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        mode = data.get("interaction_mode")
        return mode if mode in _VALID_INTERACTION_MODES else None
    except (OSError, json.JSONDecodeError):
        return None


def set_task_interaction_mode(path: str, mode: str) -> bool:
    if mode not in _VALID_INTERACTION_MODES:
        return False
    tmp_path: str = ""
    try:
        p = Path(path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        data["interaction_mode"] = mode
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


_capture_size_cache: dict[str, tuple[tuple[int, int], list[int] | None]] = {}
# ponytail: 主循環熱路徑每幀讀取（_handle_match_image/_run_parallel_group）；
# mtime+size 未變直接回快取，寫入走 _replace_file 產生新 mtime 自然失效


def get_capture_size(path: str) -> list | None:
    try:
        st = os.stat(path)
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        _capture_size_cache.pop(path, None)
        return None
    hit = _capture_size_cache.get(path)
    if hit and hit[0] == sig:
        return list(hit[1]) if hit[1] else None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cs = data.get("capture_size")
        val = [int(cs[0]), int(cs[1])] if isinstance(cs, list) and len(cs) == 2 else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        val = None
    _capture_size_cache[path] = (sig, val)
    return list(val) if val else None


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
