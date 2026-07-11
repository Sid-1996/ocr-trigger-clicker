from copy import deepcopy
from pathlib import Path

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
        "color_tolerance": 100,
        "on_fail": "stop",
    },
    "notify": {"message": ""},
}


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
        elif action == "advance":
            result = {"action": "advance"}
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


def _build_detect_params(old: dict) -> dict:
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
    steps: list[dict] = []

    if str(old.get("rule_type", "trigger")) == "compare":
        if str(old.get("target_text", "")).strip():
            steps.append({"type": "detect", "params": _build_detect_params(old)})

        confirm_action = _build_confirm_action(old)
        if confirm_action["type"] == "click":
            steps.append({"type": "click", "params": confirm_action})
        elif confirm_action.get("key", ""):
            steps.append({"type": "key", "params": confirm_action})
    else:
        steps.append({"type": "detect", "params": _build_detect_params(old)})

        sub_text = str(old.get("sub_target_text", "")).strip()
        if sub_text:
            sub_roi = _sanitize_roi(old.get("sub_roi"))
            if all(sub_roi.get(k, 0) == 0 for k in ("x", "y", "w", "h")):
                sub_roi = _sanitize_roi(old.get("roi"))
            sub_params = _build_detect_params(old)
            sub_params["text"] = sub_text
            sub_params["roi"] = sub_roi
            steps.append({"type": "detect", "params": sub_params})

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

        post_delay = max(0, _as_int(old.get("post_delay_ms", 0), 0))
        if post_delay > 0:
            steps.append({"type": "wait", "params": {"ms": post_delay}})

    return {
        "id": str(old.get("id", "")),
        "name": str(old.get("name", "")),
        "enabled": bool(old.get("enabled", True)),
        "steps": steps,
    }


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
