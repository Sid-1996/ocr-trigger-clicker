import json
import logging
import os
import sys
import tempfile
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure project root is on sys.path for _loader
_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from _loader import load_sibling  # noqa: E402

_ocr_mod = load_sibling("ocr_engine", "core/02_ocr_engine.py")
OcrResult = _ocr_mod.OcrResult
find_text = _ocr_mod.find_text

_FORMAT_VERSION = 1
_IMPORT_DESCRIPTION_MAX = 200


def _replace_file(tmp_path: str, dst: str) -> None:
    """Windows-safe atomic replace: unlink + rename (raises OSError on failure)."""
    try:
        os.unlink(dst)
    except FileNotFoundError:
        pass
    try:
        os.rename(tmp_path, dst)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@dataclass
class ImportPreview:
    meta: dict
    rule_names: list[str]
    rule_count: int
    warnings: list[str]
    raw_data: dict


# ── New dataclasses ──


@dataclass
class Step:
    type: str
    params: dict


@dataclass
class Rule:
    id: str
    name: str
    enabled: bool
    steps: list[Step]
    background: bool = False


@dataclass
class RuleGroup:
    id: str
    name: str
    enabled: bool = True
    mode: str = "once"
    repeat_times: int = 1
    between_rounds_sec: int = 0
    rule_ids: list[str] = field(default_factory=list)
    order: str = "sequential"


_STEP_DEFAULTS = {
    "detect": {
        "text": "",
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "match_mode": "fuzzy",
        "fuzzy_threshold": 0.8,
        "on_fail": "stop",
    },
    "click": {
        "target": "text_center",
        "x": 0,
        "y": 0,
        "button": "left",
        "random_offset": 3,
    },
    "key": {"key": "", "hold_ms": 0},
    "drag": {
        "target": "text_center",
        "x": 0,
        "y": 0,
        "text": "",
        "dx": 0,
        "dy": 0,
        "button": "left",
    },
    "scroll": {"direction": "WheelDown", "amount": 1, "delay_ms": 30},
    "wait": {"ms": 1000},
    "jump": {"rule_id": ""},
    "compare": {
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "pattern": r"-?\d+\.?\d*",
        "operator": ">=",
        "value": 0.0,
        "on_fail": "stop",
    },
    "match_image": {
        "template": "",
        "template_data": "",
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "threshold": 0.8,
        "match_color": False,
        "color_tolerance": 100,  # 0~255，預設 100 可過濾明顯色差（如灰 vs 白），同時保留正常亮度差異
        "on_fail": "stop",
    },
    "notify": {"message": ""},
}


# ── Helpers ──


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sanitize_roi(roi: dict | None) -> dict:
    roi = roi if isinstance(roi, dict) else {}
    result = {
        "x": max(0.0, _as_float(roi.get("x", 0))),
        "y": max(0.0, _as_float(roi.get("y", 0))),
        "w": max(0.0, _as_float(roi.get("w", 0))),
        "h": max(0.0, _as_float(roi.get("h", 0))),
    }
    if roi.get("roi_coord") == "client":
        result["roi_coord"] = "client"
    return result


def _normalize_action(action: dict | None, default_type: str = "key") -> dict:
    action = action if isinstance(action, dict) else {}
    action_type = str(action.get("type", default_type))
    if action_type == "click":
        return {
            "type": "click",
            "x": _as_int(action.get("x", 0), 0),
            "y": _as_int(action.get("y", 0), 0),
            "button": str(action.get("button", "left")),
        }
    if action_type == "jump":
        return {"type": "jump", "rule_id": str(action.get("rule_id", ""))}
    return {"type": "key", "key": str(action.get("key", ""))}


def _normalize_on_fail(raw: object, allow_skip: bool = False) -> str | dict:
    if isinstance(raw, dict):
        action = str(raw.get("action", "stop"))
        fd = raw.get("fail_duration_sec", 0)
        try:
            fd = float(fd)
        except (TypeError, ValueError):
            fd = 0.0
        if action == "notify":
            result: dict = {
                "action": "notify",
                "message": str(raw.get("message", "")).strip(),
                "stop_groups": [str(g) for g in raw.get("stop_groups", []) if g],
            }
        elif action == "key":
            result = {"action": "key", "key": str(raw.get("key", ""))}
        elif action == "skip" and allow_skip:
            result = {"action": "skip", "skip_to": max(0, int(raw.get("skip_to", 0)))}
        elif action == "jump":
            result = {"action": "jump", "rule_id": str(raw.get("rule_id", ""))}
        else:
            return "stop"
        if fd > 0:
            result["fail_duration_sec"] = fd
        return result
    return str(raw) if str(raw) in ("key", "stop") else "stop"


def _normalize_step_params(step_type: str, params: dict | None) -> dict:
    base = deepcopy(_STEP_DEFAULTS.get(step_type, {}))
    params = params if isinstance(params, dict) else {}
    base.update(params)

    if step_type == "detect":
        base["text"] = str(base.get("text", "")).strip()
        base["roi"] = _sanitize_roi(base.get("roi"))
        base["match_mode"] = str(base.get("match_mode", "fuzzy"))
        base["fuzzy_threshold"] = max(
            0.0, min(1.0, _as_float(base.get("fuzzy_threshold", 0.8), 0.8))
        )
        base["on_fail"] = _normalize_on_fail(base.get("on_fail", "stop"), allow_skip=True)
    elif step_type in ("click", "drag"):
        base["target"] = str(base.get("target", "text_center"))
        base["x"] = _as_float(base.get("x", 0), 0)
        base["y"] = _as_float(base.get("y", 0), 0)
        base["text"] = str(base.get("text", "")).strip()
        base["button"] = str(base.get("button", "left"))
        if step_type == "click":
            base["random_offset"] = max(0, _as_int(base.get("random_offset", 3), 3))
        else:
            base["dx"] = _as_int(base.get("dx", 0), 0)
            base["dy"] = _as_int(base.get("dy", 0), 0)
    elif step_type == "key":
        base["key"] = str(base.get("key", ""))
        base["hold_ms"] = max(0, _as_int(base.get("hold_ms", 0), 0))
    elif step_type == "scroll":
        base["direction"] = str(base.get("direction", "WheelDown"))
        base["amount"] = max(1, _as_int(base.get("amount", 1), 1))
        base["delay_ms"] = max(0, _as_int(base.get("delay_ms", 30), 30))
    elif step_type == "wait":
        base["ms"] = max(0, _as_int(base.get("ms", 1000), 1000))
    elif step_type == "jump":
        base["rule_id"] = str(base.get("rule_id", ""))
    elif step_type == "compare":
        base["roi"] = _sanitize_roi(base.get("roi"))
        base["pattern"] = str(base.get("pattern", r"-?\d+\.?\d*"))
        base["operator"] = str(base.get("operator", ">="))
        base["value"] = _as_float(base.get("value", 0.0), 0.0)
        base["on_fail"] = _normalize_on_fail(base.get("on_fail", "stop"), allow_skip=True)
    elif step_type == "match_image":
        base["template"] = str(base.get("template", "")).strip()
        base["template_data"] = str(base.get("template_data", ""))
        base["roi"] = _sanitize_roi(base.get("roi"))
        base["threshold"] = max(0.0, min(1.0, _as_float(base.get("threshold", 0.8), 0.8)))
        base["match_color"] = bool(base.get("match_color", False))
        base["color_tolerance"] = max(0, min(255, _as_int(base.get("color_tolerance", 100), 100)))
        base["on_fail"] = _normalize_on_fail(base.get("on_fail", "stop"), allow_skip=True)
        if base["template"] and not base["template_data"]:
            p = Path(base["template"])
            if p.exists():
                import base64 as _b64

                import cv2 as _cv2

                _tmp_img = _cv2.imread(str(p), _cv2.IMREAD_COLOR)
                if _tmp_img is not None:
                    _, _buf = _cv2.imencode(".png", _tmp_img)
                    base["template_data"] = _b64.b64encode(_buf).decode("ascii")
    return base


def _parse_depends_on(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value:
        return [value]
    return []


# ── Migration helpers ──


def _build_detect_params(old: dict) -> dict:
    # backward compat: old rules store fuzzy bool instead of match_mode
    if "match_mode" in old:
        match_mode_ = str(old["match_mode"])
    elif "fuzzy" in old:
        match_mode_ = "fuzzy" if bool(old["fuzzy"]) else "contains"
    else:
        match_mode_ = "contains"
    on_fail = old.get("on_fail", "stop")
    if isinstance(on_fail, dict):
        action = str(on_fail.get("action", "stop"))
        if action == "key":
            on_fail = {"action": "key", "key": str(on_fail.get("key", ""))}
        else:
            on_fail = "stop"
    else:
        on_fail = str(on_fail) if str(on_fail) in ("key", "stop") else "stop"
    return {
        "text": str(old.get("target_text", "")).strip(),
        "roi": _sanitize_roi(old.get("roi")),
        "match_mode": match_mode_,
        "fuzzy_threshold": max(0.0, min(1.0, _as_float(old.get("fuzzy_threshold", 0.8), 0.8))),
        "on_fail": on_fail,
    }


def _build_confirm_action(old: dict) -> dict:
    if str(old.get("confirm_action_type", "key")) == "click":
        return {
            "type": "click",
            "x": _as_int(old.get("confirm_x", 0), 0),
            "y": _as_int(old.get("confirm_y", 0), 0),
            "button": str(old.get("click_button", "left")),
        }
    return {"type": "key", "key": str(old.get("confirm_key", ""))}


def _migrate_v1_to_v2(old: dict) -> dict:
    """Convert old-format rule dict to new-format dict with steps."""
    steps: list[dict] = []

    if str(old.get("rule_type", "trigger")) == "compare":
        # Compare rule → convert to detect + click/key
        if str(old.get("target_text", "")).strip():
            steps.append({"type": "detect", "params": _build_detect_params(old)})

        confirm_action = _build_confirm_action(old)
        if confirm_action["type"] == "click":
            steps.append({"type": "click", "params": confirm_action})
        elif confirm_action.get("key", ""):
            steps.append({"type": "key", "params": confirm_action})
    else:
        # Trigger rule
        steps.append({"type": "detect", "params": _build_detect_params(old)})

        # Correction 1: sub_target_text → additional detect step
        sub_text = str(old.get("sub_target_text", "")).strip()
        if sub_text:
            sub_roi = _sanitize_roi(old.get("sub_roi"))
            if all(sub_roi.get(k, 0) == 0 for k in ("x", "y", "w", "h")):
                sub_roi = _sanitize_roi(old.get("roi"))
            sub_params = _build_detect_params(old)
            sub_params["text"] = sub_text
            sub_params["roi"] = sub_roi
            steps.append({"type": "detect", "params": sub_params})

        # Action step
        if str(old.get("action_type", "click")) == "key" and str(old.get("key", "")):
            steps.append({"type": "key", "params": {"key": str(old.get("key", ""))}})
        else:
            steps.append(
                {
                    "type": "click",
                    "params": {
                        "target": str(old.get("click_position", "text_center")),
                        "x": _as_int(old.get("custom_x", 0), 0),
                        "y": _as_int(old.get("custom_y", 0), 0),
                        "button": str(old.get("click_button", "left")),
                        "random_offset": max(0, _as_int(old.get("random_offset", 3), 3)),
                    },
                }
            )

        # Post-delay wait
        post_delay = max(0, _as_int(old.get("post_delay_ms", 0), 0))
        if post_delay > 0:
            steps.append({"type": "wait", "params": {"ms": post_delay}})

    # depends_on → skip (sequencing via rule ordering in new model)

    return {
        "id": str(old.get("id", "")),
        "name": str(old.get("name", "")),
        "enabled": bool(old.get("enabled", True)),
        "steps": steps,
    }


# ── Serialization ──


def _dict_to_rule(d: dict) -> Rule:
    if "steps" not in d:
        d = _migrate_v1_to_v2(d)
    steps = [
        Step(
            type=str(s.get("type", "")),
            params=_normalize_step_params(str(s.get("type", "")), s.get("params")),
        )
        for s in d.get("steps", [])
    ]
    return Rule(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        enabled=bool(d.get("enabled", True)),
        steps=steps,
        background=bool(d.get("background", False)),
    )


def _rule_to_dict(r: Rule) -> dict:
    d = asdict(r)
    d.pop("trigger_count", None)
    d.pop("last_trigger_time", None)
    return d


def _dict_to_group(d: dict) -> RuleGroup:
    return RuleGroup(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        enabled=bool(d.get("enabled", True)),
        mode=str(d.get("mode", "once")),
        repeat_times=int(d.get("repeat_times", 1)),
        between_rounds_sec=int(d.get("between_rounds_sec", 0)),
        rule_ids=[str(r) for r in d.get("rule_ids", []) if r],
        order=str(d.get("order", "sequential")),
    )


def _group_to_dict(g: RuleGroup) -> dict:
    return asdict(g)


def load_groups(path: str) -> list[RuleGroup]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if "groups" not in data:
        data = migrate_v2_to_v3(data)
    groups = data.get("groups", [])
    if not isinstance(groups, list):
        return []
    return [_dict_to_group(g) for g in groups]


def save_groups(groups: list[RuleGroup], path: str) -> bool:
    tmp_path: str = ""
    try:
        data = {"groups": [_group_to_dict(g) for g in groups]}
        p = Path(path)
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    existing = json.load(f)
                for k, v in existing.items():
                    if k != "groups":
                        data[k] = v
            except (json.JSONDecodeError, OSError):
                pass
        with tempfile.NamedTemporaryFile(
            "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path = f.name
        _replace_file(tmp_path, str(p))
        return True
    except OSError:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        return False


def migrate_v2_to_v3(data: dict) -> dict:
    mode = str(data.get("run_mode", "once"))
    repeat_times = int(data.get("repeat_times", 1))
    between_rounds_sec = int(data.get("between_rounds_sec", 0))

    normal_ids = []
    for r in data.get("rules", []):
        if isinstance(r, dict) and not r.get("background", False):
            normal_ids.append(str(r.get("id", "")))

    data["groups"] = [
        {
            "id": "__default__",
            "name": "Default",
            "mode": mode,
            "repeat_times": repeat_times,
            "between_rounds_sec": between_rounds_sec,
            "rule_ids": normal_ids,
            "order": "sequential",
        }
    ]
    data.pop("run_mode", None)
    data.pop("repeat_times", None)
    data.pop("between_rounds_sec", None)
    return data


def _migrate_roi_to_ratio(data: dict) -> dict:
    cap = data.get("capture_size")
    if not cap or len(cap) < 2:
        return data
    W, H = cap[0], cap[1]
    if W <= 0 or H <= 0:
        return data

    for rule in data.get("rules", []):
        for step in rule.get("steps", []):
            if step.get("type") in ("detect", "compare", "match_image"):
                if "roi" in step.get("params", {}):
                    roi = step["params"]["roi"]
                    x, y, w, h = roi.get("x", 0), roi.get("y", 0), roi.get("w", 0), roi.get("h", 0)
                    if not (x <= 1.0 and y <= 1.0 and w <= 1.0 and h <= 1.0):
                        step["params"]["roi"] = {"x": x / W, "y": y / H, "w": w / W, "h": h / H}
            elif step.get("type") == "click":
                p = step.get("params", {})
                px, py = p.get("x", 0), p.get("y", 0)
                if not (px <= 1.0 and py <= 1.0):
                    step["params"] = {**p, "x": px / W, "y": py / H}
            elif step.get("type") == "drag":
                p = step.get("params", {})
                px, py = p.get("x", 0), p.get("y", 0)
                if px > 1.0 or py > 1.0:
                    step["params"] = {**p, "x": px / W, "y": py / H}
    data["ratio_coords"] = True
    return data


def _migrate_roi_coord(data: dict) -> dict:
    for rule in data.get("rules", []):
        for step in rule.get("steps", []):
            if step.get("type") not in ("detect", "compare", "match_image"):
                continue
            roi = step.get("params", {}).get("roi", {})
            if not isinstance(roi, dict):
                continue
            if "roi_coord" in roi:
                continue
            x = roi.get("x", 0)
            if not (isinstance(x, (int, float)) and x <= 1.0 and x >= 0):
                continue
            roi["roi_coord"] = "client"
    return data


def load_rules(path: str) -> list[Rule]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, KeyError) as e:
        logging.warning("規則檔案載入失敗 (%s): %s", path, e)
        return []

    if "groups" not in data:
        data = migrate_v2_to_v3(data)
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
            ) as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                tmp_path = f.name
            _replace_file(tmp_path, str(p))
        except OSError:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    if not data.get("ratio_coords"):
        data = _migrate_roi_to_ratio(data)
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
            ) as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                tmp_path = f.name
            _replace_file(tmp_path, str(p))
        except OSError:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    data = _migrate_roi_coord(data)

    rules: list[Rule] = []
    for raw in data.get("rules", []):
        try:
            rules.append(_dict_to_rule(raw))
        except Exception as e:
            logging.warning("規則項目解析失敗，已略過: %s", e)
            continue
    return rules


def save_rules(rules: list[Rule], path: str) -> bool:
    bg_ids = [r.id for r in rules if r.background]
    logging.info("[save] save_rules: rules=%d, background=%s, path=%s", len(rules), bg_ids, path)
    tmp_path: str = ""
    try:
        data = {"rules": [_rule_to_dict(r) for r in rules]}
        p = Path(path)
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    existing = json.load(f)
                for k, v in existing.items():
                    if k != "rules":
                        data[k] = v
            except (json.JSONDecodeError, OSError):
                pass
        with tempfile.NamedTemporaryFile(
            "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path = f.name
        _replace_file(tmp_path, str(p))
        return True
    except OSError:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        return False


# ── Task management ──


def _tasks_base() -> Path:
    try:
        from build import get_data_path

        raw = get_data_path("_")
        return Path(raw).parent
    except ImportError:
        return Path(__file__).resolve().parent.parent


def get_tasks_dir() -> Path:
    tasks_dir = _tasks_base() / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    return tasks_dir


def list_tasks() -> list[str]:
    names = []
    for f in sorted(get_tasks_dir().glob("*.json")):
        if f.stem:
            names.append(f.stem)
    return names


def load_task(name: str) -> list[Rule]:
    return load_rules(str(get_tasks_dir() / f"{name}.json"))


def save_task(name: str, rules: list[Rule]) -> bool:
    return save_rules(rules, str(get_tasks_dir() / f"{name}.json"))


def delete_task(name: str) -> bool:
    try:
        (get_tasks_dir() / f"{name}.json").unlink(missing_ok=True)
        return True
    except OSError:
        return False


def rename_task(old_name: str, new_name: str) -> bool:
    old_p = get_tasks_dir() / f"{old_name}.json"
    new_p = get_tasks_dir() / f"{new_name}.json"
    if new_p.exists():
        return False
    try:
        old_p.rename(new_p)
        return True
    except OSError:
        return False


def _export_meta() -> dict:
    try:
        from _version import __version__
    except ImportError:
        __version__ = "0.0.0"
    return {
        "format_version": _FORMAT_VERSION,
        "app_version": __version__,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


def _validate_rule_structure(raw: dict, warnings: list[str]) -> bool:
    if not isinstance(raw.get("id"), str) or not raw["id"]:
        warnings.append("規則缺少 id，已略過")
        return False
    if not isinstance(raw.get("name"), str) or not raw["name"]:
        warnings.append(f"規則 {raw.get('id', '?')} 缺少 name，已略過")
        return False
    steps = raw.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        warnings.append(f"規則「{raw.get('name', '?')}」缺少 steps，已略過")
        return False
    valid_types = {
        "detect",
        "click",
        "key",
        "wait",
        "jump",
        "drag",
        "scroll",
        "match_image",
        "compare",
        "notify",
    }
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            warnings.append(f"規則「{raw['name']}」步驟 {i} 格式錯誤，已略過")
            return False
        if s.get("type") not in valid_types:
            warnings.append(f"規則「{raw['name']}」步驟 {i} 未知類型「{s.get('type')}」，已略過")
            return False
    return True


def export_task(name: str, dest_path: str) -> bool:
    src = get_tasks_dir() / f"{name}.json"
    if not src.exists():
        return False
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        data["_meta"] = _export_meta()
        Path(dest_path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except (OSError, json.JSONDecodeError):
        return False


_MAX_IMPORT_SIZE = 10 * 1024 * 1024


def preview_import_task(src_path: str) -> Optional[ImportPreview]:
    """Read & validate a task file, return preview info without writing anything."""
    src = Path(src_path)
    if not src.exists():
        return None
    try:
        if src.stat().st_size > _MAX_IMPORT_SIZE:
            return None
    except OSError:
        return None
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or "rules" not in data:
        return None
    if not isinstance(data["rules"], list):
        return None

    meta = data.get("_meta", {})
    if not isinstance(meta, dict):
        meta = {}

    warnings: list[str] = []
    valid_rules = []
    for raw in data["rules"]:
        if isinstance(raw, dict) and _validate_rule_structure(raw, warnings):
            valid_rules.append(raw)

    rule_names = [r.get("name", "?") for r in valid_rules]
    dropped = len(data["rules"]) - len(valid_rules)
    if dropped:
        warnings.append(
            f"共 {len(data['rules'])} 條規則，{len(valid_rules)} 條格式正確，{dropped} 條已略過"
        )

    valid_ids = {r["id"] for r in valid_rules}
    valid_groups = []
    for g in data.get("groups", []):
        gid = g.get("id", "")
        gname = g.get("name", "")
        if not isinstance(gid, str) or not gid:
            warnings.append("群組缺少 id，已略過")
            continue
        if not isinstance(gname, str) or not gname:
            warnings.append(f"群組 {gid} 缺少 name，已略過")
            continue
        raw_ids = g.get("rule_ids", [])
        if not isinstance(raw_ids, list):
            raw_ids = []
        filtered = [rid for rid in raw_ids if isinstance(rid, str) and rid in valid_ids]
        if len(filtered) < len(raw_ids):
            warnings.append(f"群組「{gname}」部分 rule_ids 指向無效規則，已自動過濾")
        g["rule_ids"] = filtered
        valid_groups.append(g)

    raw_data: dict = {"rules": valid_rules}
    if valid_groups:
        raw_data["groups"] = valid_groups

    return ImportPreview(
        meta=meta,
        rule_names=rule_names,
        rule_count=len(valid_rules),
        warnings=warnings,
        raw_data=raw_data,
    )


def import_task(src_path: str, regenerate_uuids: bool = False) -> Optional[str]:
    preview = preview_import_task(src_path)
    if preview is None or preview.rule_count == 0:
        return None
    data = preview.raw_data
    if regenerate_uuids:
        id_map: dict[str, str] = {}
        for r in data["rules"]:
            old_id = r["id"]
            new_id = uuid.uuid4().hex[:12]
            id_map[old_id] = new_id
            r["id"] = new_id
        for r in data["rules"]:
            for s in r.get("steps", []):
                p = s.get("params", {})
                if s["type"] in ("wait_rule", "jump"):
                    rid = p.get("rule_id", "")
                    if rid in id_map:
                        p["rule_id"] = id_map[rid]
                if s["type"] in ("detect", "match_image") and isinstance(p.get("on_fail"), dict):
                    rid = p["on_fail"].get("rule_id", "") or p["on_fail"].get("jump_rule_id", "")
                    if rid in id_map:
                        p["on_fail"]["rule_id"] = id_map[rid]
                    p["on_fail"].pop("jump_rule_id", None)
                if s["type"] == "collect_rounds":
                    oaf = p.get("on_all_fail", {})
                    if isinstance(oaf, dict):
                        rid = oaf.get("rule_id", "")
                        if rid in id_map:
                            oaf["rule_id"] = id_map[rid]
        for g in data.get("groups", []):
            g["rule_ids"] = [id_map.get(rid, rid) for rid in g.get("rule_ids", [])]

    src_name = Path(src_path).stem
    dest = get_tasks_dir() / f"{src_name}.json"
    suffix = 1
    while dest.exists():
        dest = get_tasks_dir() / f"{src_name}_{suffix}.json"
        suffix += 1
    try:
        dest.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return dest.stem
    except OSError:
        return None


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


def migrate_old_rules():
    if any(get_tasks_dir().iterdir()):
        return
    try:
        from build import get_data_path

        old_path = Path(get_data_path("rules.json"))
    except ImportError:
        old_path = _tasks_base() / "rules.json"
    if old_path.exists():
        rules = load_rules(str(old_path))
        save_task("預設任務", rules)


if __name__ == "__main__":
    print("=== Rule Engine Self-Check ===\n")

    # ── Test 1: Trigger rule migration (no more wait_rule/cooldown/trigger_mode/max_triggers) ──
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
    assert "steps" in new, "missing steps"
    assert new["steps"][0]["type"] == "detect", "first step should be detect"
    assert new["steps"][1]["type"] == "click", "second step should be click"
    assert new["steps"][2]["type"] == "wait", "post_delay should become wait"
    assert new["steps"][0]["params"]["text"] == "確認"
    assert new["steps"][0]["params"]["roi"]["x"] == 100
    # cooldown_ms / trigger_mode / max_triggers should NOT be in output
    assert "cooldown_ms" not in new["steps"][0]["params"], "cooldown_ms should be removed"
    assert "trigger_mode" not in new["steps"][0]["params"], "trigger_mode should be removed"
    assert "max_triggers" not in new["steps"][0]["params"], "max_triggers should be removed"
    print("  [OK] Trigger rule migration (no cooldown/trigger_mode/max_triggers)")

    # ── Test 1b: Trigger with sub_target_text (Correction 1) ──
    old_with_sub = dict(old_trigger)
    old_with_sub["sub_target_text"] = "子目標"
    old_with_sub["sub_roi"] = {"x": 10, "y": 20, "w": 50, "h": 30}
    new_sub = _migrate_v1_to_v2(old_with_sub)
    detect_count = sum(1 for s in new_sub["steps"] if s["type"] == "detect")
    assert detect_count == 2, f"expected 2 detect steps, got {detect_count}"
    sub_detect = [s for s in new_sub["steps"] if s["type"] == "detect"][1]
    assert sub_detect["params"]["text"] == "子目標"
    assert sub_detect["params"]["roi"]["x"] == 10
    print("  [OK] Sub-target migration (Correction 1)")

    # ── Test 1c: Sub-target with zero roi uses main roi ──
    old_sub_zero = dict(old_trigger)
    old_sub_zero["sub_target_text"] = "子目標2"
    old_sub_zero["sub_roi"] = {"x": 0, "y": 0, "w": 0, "h": 0}
    new_sub_zero = _migrate_v1_to_v2(old_sub_zero)
    sub_d2 = [s for s in new_sub_zero["steps"] if s["type"] == "detect"][1]
    assert sub_d2["params"]["roi"]["x"] == 100, "should inherit main roi"
    print("  [OK] Sub-target with zero roi inherits main roi")

    # ── Test 2: Compare rule migration (convert to detect + confirm action) ──
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
    assert new_c["steps"][0]["type"] == "detect", "compare should have pre-detect"
    assert new_c["steps"][1]["type"] == "click", "compare should convert to click"
    assert new_c["steps"][1]["params"]["x"] == 100
    assert new_c["steps"][1]["params"]["y"] == 200
    print("  [OK] Compare rule migration → detect + click")

    # ── Test 2b: Compare with key confirm action ──
    old_compare_key = dict(old_compare)
    old_compare_key["confirm_action_type"] = "key"
    old_compare_key["confirm_key"] = " "
    new_ck = _migrate_v1_to_v2(old_compare_key)
    assert new_ck["steps"][1]["type"] == "key"
    assert new_ck["steps"][1]["params"]["key"] == " "
    print("  [OK] Compare rule → detect + key")

    # ── Test 3: Round-trip serialization ──
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
    print("  [OK] Round-trip serialization")

    # ── Test 4: Old-format load ──
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"rules": [old_trigger, old_compare]}, f, ensure_ascii=False)
        tmp_path = f.name
    loaded = load_rules(tmp_path)
    assert len(loaded) == 2
    assert isinstance(loaded[0], Rule)
    # trigger rule: detect + click + wait
    assert len(loaded[0].steps) == 3
    assert loaded[0].steps[0].type == "detect"
    assert loaded[0].steps[1].type == "click"
    assert loaded[0].steps[2].type == "wait"
    # compare rule: detect + click
    assert loaded[1].steps[0].type == "detect"
    assert loaded[1].steps[1].type == "click"
    Path(tmp_path).unlink()
    print("  [OK] Old-format load with auto-migration")

    # ── Test 5: Step with key action ──
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
    print("  [OK] Key action migration")

    # ── Test 6: No steps in old data with defaults ──
    old_minimal = {"id": "rule_min", "name": "最小規則", "enabled": True}
    new_min = _migrate_v1_to_v2(old_minimal)
    assert len(new_min["steps"]) >= 1
    assert new_min["steps"][0]["type"] == "detect"
    print("  [OK] Minimal old-rule migration")

    # ── Test 7: Step defaults and normalization (no collect_rounds) ──
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
    print("  [OK] Step defaults and normalization")

    # ── Test 8: Import UUID remap covers nested jump references ──
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

        _orig_get_tasks_dir = get_tasks_dir

        def _tmp_tasks_dir() -> Path:
            p = tmp_dir_path / "tasks"
            p.mkdir(parents=True, exist_ok=True)
            return p

        globals()["get_tasks_dir"] = _tmp_tasks_dir
        try:
            imported_name = import_task(str(src_path), regenerate_uuids=True)
            assert imported_name == "import_me"
            imported = json.loads((tmp_dir_path / "tasks" / "import_me.json").read_text("utf-8"))
        finally:
            globals()["get_tasks_dir"] = _orig_get_tasks_dir

        new_ids = {r["id"] for r in imported["rules"]}
        assert "source_a" not in new_ids and "source_b" not in new_ids
        jump1 = imported["rules"][0]["steps"][1]["params"]["rule_id"]
        jump2 = imported["rules"][1]["steps"][0]["params"]["rule_id"]
        assert jump1 in new_ids
        assert jump2 in new_ids
    print("  [OK] Import UUID remaps nested jumps")

    # ── Test 9: on_fail normalization (detect) ──
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
    print("  [OK] on_fail normalization (detect)")

    # ── Test 10: match_image on_fail normalization ──
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
    print("  [OK] match_image on_fail normalization")

    # ── Test 11: RuleGroup creation and defaults ──
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
    print("  [OK] RuleGroup creation and defaults")

    # ── Test 12: _dict_to_group / _group_to_dict round-trip ──
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
    # integer→str coercion for rule_ids
    g_num = _dict_to_group({"id": "gn", "name": "N", "rule_ids": [1, 2]})
    assert g_num.rule_ids == ["1", "2"]
    print("  [OK] _dict_to_group / _group_to_dict round-trip")

    # ── Test 13: migrate_v2_to_v3 creates __default__ group ──
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
    # old top-level fields removed
    assert "run_mode" not in data_v3
    assert "repeat_times" not in data_v3
    assert "between_rounds_sec" not in data_v3
    # rules untouched
    assert len(data_v3["rules"]) == 2
    print("  [OK] migrate_v2_to_v3 creates __default__ group")

    # ── Test 14: migrate_v2_to_v3 excludes background rules ──
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
    print("  [OK] migrate_v2_to_v3 excludes background rules")

    # ── Test 15: save_groups / load_groups round-trip (atomic write) ──
    with tempfile.TemporaryDirectory() as tmp_dir:
        task_file = Path(tmp_dir) / "test_task.json"
        # pre-write rules + window_title to test top-level preservation
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
        # other top-level fields preserved
        saved = json.loads(task_file.read_text(encoding="utf-8"))
        assert saved["window_title"] == "My Window"
    print("  [OK] save_groups / load_groups round-trip")

    # ── Test 16: load_rules auto-migration (no groups in file) ──
    with tempfile.TemporaryDirectory() as tmp_dir:
        task_file = Path(tmp_dir) / "auto_migrate.json"
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
        # file was rewritten with groups
        final = json.loads(task_file.read_text(encoding="utf-8"))
        assert "groups" in final
        assert "run_mode" not in final
        assert final["groups"][0]["id"] == "__default__"
        assert final["groups"][0]["mode"] == "once"
    print("  [OK] load_rules auto-migration on missing groups")

    print("\n=== All 16 tests passed ===")
