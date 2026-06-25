import json
import logging
import os
import sys
import tempfile
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass
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

    # runtime only (not persisted)
    trigger_count: int = 0
    last_trigger_time: float = 0.0


_STEP_DEFAULTS = {
    "detect": {
        "text": "",
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "match_mode": "fuzzy",
        "fuzzy_threshold": 0.8,
        "cooldown_ms": 500,
        "trigger_mode": "once",
        "max_triggers": -1,
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
    "wait_rule": {"rule_id": "", "timeout_ms": 5000},
    "collect_rounds": {
        "rounds": [],
        "primary_metric_index": 0,
        "confirm_action": {"type": "key", "key": ""},
        "on_all_fail": {"type": "jump", "rule_id": ""},
    },
    "jump": {"rule_id": ""},
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
    return {
        "x": max(0, _as_int(roi.get("x", 0))),
        "y": max(0, _as_int(roi.get("y", 0))),
        "w": max(0, _as_int(roi.get("w", 0))),
        "h": max(0, _as_int(roi.get("h", 0))),
    }


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
        base["cooldown_ms"] = max(0, _as_int(base.get("cooldown_ms", 500), 500))
        base["trigger_mode"] = str(base.get("trigger_mode", "once"))
        base["max_triggers"] = _as_int(base.get("max_triggers", -1), -1)
    elif step_type in ("click", "drag"):
        base["target"] = str(base.get("target", "text_center"))
        base["x"] = _as_int(base.get("x", 0), 0)
        base["y"] = _as_int(base.get("y", 0), 0)
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
    elif step_type in ("wait_rule", "jump"):
        base["rule_id"] = str(base.get("rule_id", ""))
    elif step_type == "collect_rounds":
        rounds = []
        for rd in base.get("rounds", []):
            if not isinstance(rd, dict):
                continue
            metrics = []
            for m in rd.get("metrics", []):
                if not isinstance(m, dict):
                    continue
                metrics.append(
                    {
                        "roi": _sanitize_roi(m.get("roi")),
                        "pick": str(m.get("pick", "first")),
                        "direction": str(m.get("direction", "higher_better")),
                        "threshold": _as_float(m.get("threshold", 0.0), 0.0),
                        "timeout_ms": max(100, _as_int(m.get("timeout_ms", 3000), 3000)),
                    }
                )
            rounds.append(
                {
                    "trigger_action": _normalize_action(rd.get("trigger_action"), "key"),
                    "metrics": metrics,
                    "result_action": _normalize_action(rd.get("result_action"), "key"),
                }
            )
        base["rounds"] = rounds
        base["primary_metric_index"] = max(0, _as_int(base.get("primary_metric_index", 0), 0))
        base["confirm_action"] = _normalize_action(base.get("confirm_action"), "key")
        base["on_all_fail"] = _normalize_action(base.get("on_all_fail"), "jump")
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
    return {
        "text": str(old.get("target_text", "")).strip(),
        "roi": _sanitize_roi(old.get("roi")),
        "match_mode": match_mode_,
        "fuzzy_threshold": max(0.0, min(1.0, _as_float(old.get("fuzzy_threshold", 0.8), 0.8))),
        "cooldown_ms": max(0, _as_int(old.get("cooldown_ms", 500), 500)),
        "trigger_mode": str(old.get("trigger_mode", "once")),
        "max_triggers": _as_int(old.get("max_triggers", -1), -1),
        "on_fail": old.get("on_fail", "stop"),
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

    # Correction 3: depends_on is list[str], each gets a wait_rule step
    for dep_id in _parse_depends_on(old.get("depends_on")):
        steps.append({"type": "wait_rule", "params": {"rule_id": dep_id}})

    if str(old.get("rule_type", "trigger")) == "compare":
        # Compare rule
        if str(old.get("target_text", "")).strip():
            steps.append({"type": "detect", "params": _build_detect_params(old)})

        metrics: list[dict] = []
        roi_a = _sanitize_roi(old.get("roi_a"))
        round_wait = max(100, _as_int(old.get("round_wait_ms", 3000), 3000))
        metrics.append(
            {
                "roi": roi_a,
                "pick": str(old.get("roi_a_value_pick", "first")),
                "direction": str(old.get("roi_a_compare", "higher_better")),
                "threshold": _as_float(old.get("roi_a_threshold", 0.0), 0.0),
                "timeout_ms": round_wait,
            }
        )
        if max(1, min(2, _as_int(old.get("roi_count", 1), 1))) >= 2:
            roi_b = _sanitize_roi(old.get("roi_b"))
            metrics.append(
                {
                    "roi": roi_b,
                    "pick": str(old.get("roi_b_value_pick", "first")),
                    "direction": str(old.get("roi_b_compare", "lower_better")),
                    "threshold": _as_float(old.get("roi_b_threshold", 50.0), 50.0),
                    "timeout_ms": round_wait,
                }
            )

        max_rounds = max(1, _as_int(old.get("max_rounds", 5), 5))
        retry_key = str(old.get("retry_key", ""))
        confirm_action = _build_confirm_action(old)
        rounds = [
            {
                "trigger_action": {"type": "key", "key": retry_key},
                "metrics": deepcopy(metrics),
                "result_action": deepcopy(confirm_action),
            }
            for _ in range(max_rounds)
        ]

        on_all_fail_str = str(old.get("on_all_fail", "")).strip()
        # Correction 2: always {"type": "jump", "rule_id": on_all_fail}
        steps.append(
            {
                "type": "collect_rounds",
                "params": {
                    "rounds": rounds,
                    "primary_metric_index": 1 if len(metrics) >= 2 else 0,
                    "confirm_action": confirm_action,
                    "on_all_fail": (
                        {"type": "jump", "rule_id": on_all_fail_str}
                        if on_all_fail_str
                        else {"type": "jump", "rule_id": ""}
                    ),
                },
            }
        )
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
    )


def _rule_to_dict(r: Rule) -> dict:
    d = asdict(r)
    d.pop("trigger_count", None)
    d.pop("last_trigger_time", None)
    return d


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
    rules: list[Rule] = []
    for raw in data.get("rules", []):
        try:
            rules.append(_dict_to_rule(raw))
        except Exception as e:
            logging.warning("規則項目解析失敗，已略過: %s", e)
            continue
    return rules


def save_rules(rules: list[Rule], path: str) -> bool:
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
        os.replace(tmp_path, p)
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


def get_templates_dir() -> Path:
    tdir = _tasks_base() / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    return tdir


def list_templates() -> list[str]:
    return sorted(f.stem for f in get_templates_dir().glob("*.json"))


def load_template(name: str) -> list[Rule]:
    path = get_templates_dir() / f"{name}.json"
    return load_rules(str(path))


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
        "wait_rule",
        "collect_rounds",
        "jump",
        "drag",
        "scroll",
        "pause",
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


def preview_import_task(src_path: str) -> Optional[ImportPreview]:
    """Read & validate a task file, return preview info without writing anything."""
    src = Path(src_path)
    if not src.exists():
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
    if len(valid_rules) < len(data["rules"]):
        warnings.append(
            f"共 {len(data['rules'])} 條規則，{len(valid_rules)} 條格式正確，{len(data['rules']) - len(valid_rules)} 條已略過"
        )

    return ImportPreview(
        meta=meta,
        rule_names=rule_names,
        rule_count=len(valid_rules),
        warnings=warnings,
        raw_data={"rules": valid_rules},
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
                if s["type"] == "detect" and isinstance(p.get("on_fail"), dict):
                    rid = p["on_fail"].get("jump_rule_id", "")
                    if rid in id_map:
                        p["on_fail"]["jump_rule_id"] = id_map[rid]
                if s["type"] == "collect_rounds":
                    oaf = p.get("on_all_fail", {})
                    if isinstance(oaf, dict):
                        rid = oaf.get("rule_id", "")
                        if rid in id_map:
                            oaf["rule_id"] = id_map[rid]

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


# ── Compat wrappers (TODO Phase 2: remove) ──


if __name__ == "__main__":
    print("=== Phase 1 Self-Check ===\n")

    # ── Test 1: Trigger rule migration ──
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
        "cooldown_ms": 500,
        "trigger_mode": "once",
        "max_triggers": -1,
        "random_offset": 3,
        "action_type": "click",
        "post_delay_ms": 500,
        "depends_on": ["rule_other"],
    }
    new = _migrate_v1_to_v2(old_trigger)
    assert "steps" in new, "missing steps"
    assert new["steps"][0]["type"] == "wait_rule", "depends_on should become wait_rule"
    assert new["steps"][1]["type"] == "detect", "second step should be detect"
    assert new["steps"][2]["type"] == "click", "third step should be click"
    assert new["steps"][3]["type"] == "wait", "post_delay should become wait"
    assert new["steps"][0]["params"]["rule_id"] == "rule_other"
    assert new["steps"][1]["params"]["text"] == "確認"
    assert new["steps"][1]["params"]["roi"]["x"] == 100
    print("  [OK] Trigger rule migration")

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

    # ── Test 2: Compare rule migration ──
    old_compare = {
        "id": "rule_c1",
        "name": "比較測試",
        "enabled": True,
        "rule_type": "compare",
        "target_text": "訓練畫面",
        "retry_key": "1",
        "max_rounds": 3,
        "round_wait_ms": 2000,
        "roi_count": 2,
        "roi_a": {"x": 10, "y": 10, "w": 100, "h": 20},
        "roi_a_compare": "higher_better",
        "roi_a_threshold": 50.0,
        "roi_a_value_pick": "first",
        "roi_b": {"x": 10, "y": 40, "w": 100, "h": 20},
        "roi_b_compare": "lower_better",
        "roi_b_threshold": 30.0,
        "roi_b_value_pick": "last",
        "confirm_action_type": "key",
        "confirm_key": " ",
        "on_all_fail": "rule_escape",
    }
    new_c = _migrate_v1_to_v2(old_compare)
    assert "steps" in new_c
    assert new_c["steps"][0]["type"] == "detect", "compare should have pre-detect"
    assert new_c["steps"][1]["type"] == "collect_rounds"
    cr = new_c["steps"][1]["params"]
    assert len(cr["rounds"]) == 3, f"expected 3 rounds, got {len(cr['rounds'])}"
    assert cr["rounds"][0]["trigger_action"]["key"] == "1"
    assert len(cr["rounds"][0]["metrics"]) == 2
    assert cr["rounds"][0]["metrics"][0]["direction"] == "higher_better"
    assert cr["rounds"][0]["metrics"][1]["pick"] == "last"
    # Correction 2: on_all_fail is {"type": "jump", "rule_id": "rule_escape"}
    assert cr["on_all_fail"]["type"] == "jump"
    assert cr["on_all_fail"]["rule_id"] == "rule_escape"
    assert cr["confirm_action"]["type"] == "key"
    assert cr["confirm_action"]["key"] == " "
    print("  [OK] Compare rule migration")

    # ── Test 2b: Compare with on_all_fail empty ──
    old_c_empty = dict(old_compare)
    old_c_empty["on_all_fail"] = ""
    new_c_empty = _migrate_v1_to_v2(old_c_empty)
    cr_e = [s for s in new_c_empty["steps"] if s["type"] == "collect_rounds"][0]
    assert cr_e["params"]["on_all_fail"]["rule_id"] == ""
    print("  [OK] Compare with empty on_all_fail")

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
                    "fuzzy": False,
                    "fuzzy_threshold": 0.8,
                    "cooldown_ms": 500,
                    "trigger_mode": "once",
                    "max_triggers": -1,
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
        trigger_count=5,
        last_trigger_time=123.456,
    )
    serialized = _rule_to_dict(rule)
    assert "trigger_count" not in serialized, "trigger_count should not be serialized"
    assert "steps" in serialized
    assert len(serialized["steps"]) == 2
    assert serialized["steps"][0]["type"] == "detect"
    assert serialized["steps"][0]["params"]["text"] == "測試"

    deserialized = _dict_to_rule(serialized)
    assert deserialized.id == "rule_rt1"
    assert deserialized.trigger_count == 0, "runtime field should reset"
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
    assert len(loaded[0].steps) == 4  # wait_rule + detect + click + wait
    assert loaded[1].steps[1].type == "collect_rounds"
    Path(tmp_path).unlink()
    print("  [OK] Old-format load with auto-migration")

    # ── Test 6: Step with key action ──
    old_key_rule = {
        "id": "rule_key",
        "name": "按鍵規則",
        "enabled": True,
        "target_text": "請按任意鍵",
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "action_type": "key",
        "key": "Enter",
        "trigger_mode": "once",
    }
    new_key = _migrate_v1_to_v2(old_key_rule)
    assert new_key["steps"][0]["type"] == "detect"
    assert new_key["steps"][1]["type"] == "key"
    assert new_key["steps"][1]["params"]["key"] == "Enter"
    print("  [OK] Key action migration")

    # ── Test 7: No steps in old data with defaults ──
    old_minimal = {"id": "rule_min", "name": "最小規則", "enabled": True}
    new_min = _migrate_v1_to_v2(old_minimal)
    assert len(new_min["steps"]) >= 1
    assert new_min["steps"][0]["type"] == "detect"
    print("  [OK] Minimal old-rule migration")

    # ── Test 8: Step defaults and action normalization ──
    raw_normalize = {
        "id": "rule_norm",
        "name": "正規化",
        "enabled": True,
        "steps": [
            {"type": "click", "params": {"target": "custom", "x": "5", "y": "6"}},
            {
                "type": "collect_rounds",
                "params": {
                    "rounds": [
                        {
                            "trigger_action": {
                                "type": "click",
                                "x": "10",
                                "y": "20",
                                "button": "right",
                            },
                            "metrics": [{"timeout_ms": "500"}],
                            "result_action": {"type": "key", "key": "Enter"},
                        }
                    ],
                    "confirm_action": {"type": "click", "x": "30", "y": "40"},
                },
            },
        ],
    }
    normalized = _dict_to_rule(raw_normalize)
    assert normalized.steps[0].params["random_offset"] == 3
    cr_params = normalized.steps[1].params
    assert cr_params["rounds"][0]["trigger_action"]["x"] == 10
    assert cr_params["confirm_action"]["type"] == "click"
    assert cr_params["confirm_action"]["y"] == 40
    print("  [OK] Step defaults and action normalization")

    # ── Test 9: Import UUID remap covers nested jump references ──
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
                                "on_fail": {"action": "jump", "jump_rule_id": "source_b"},
                            },
                        }
                    ],
                },
                {
                    "id": "source_b",
                    "name": "來源 B",
                    "enabled": True,
                    "steps": [
                        {
                            "type": "collect_rounds",
                            "params": {
                                "rounds": [],
                                "on_all_fail": {"type": "jump", "rule_id": "source_a"},
                            },
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
        detect_jump = imported["rules"][0]["steps"][0]["params"]["on_fail"]["jump_rule_id"]
        collect_jump = imported["rules"][1]["steps"][0]["params"]["on_all_fail"]["rule_id"]
        assert detect_jump in new_ids
        assert collect_jump in new_ids
    print("  [OK] Import UUID remaps nested jumps")

    print("\n=== All 11 tests passed ===")
