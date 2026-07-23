import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _loader import load_sibling

_serial = load_sibling("rule_serialization", "core/rule_serialization.py")
load_rules = _serial.load_rules
save_rules = _serial.save_rules

_models = load_sibling("rule_models", "core/rule_models.py")
ImportPreview = _models.ImportPreview
Rule = _models.Rule

_FORMAT_VERSION = 1
_IMPORT_DESCRIPTION_MAX = 200
_MAX_IMPORT_SIZE = 10 * 1024 * 1024


def _tasks_base() -> Path:
    from core._paths import get_data_path

    return Path(get_data_path("_")).parent


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


def preview_import_task(src_path: str) -> Optional[ImportPreview]:
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
