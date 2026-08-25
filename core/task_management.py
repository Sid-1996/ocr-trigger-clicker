import base64
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
        p = s.get("params")
        if p is not None and not isinstance(p, dict):
            warnings.append(f"規則「{raw['name']}」步驟 {i} params 格式錯誤，已略過")
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
    if isinstance(data.get("window_title"), str) and data["window_title"]:
        raw_data["window_title"] = data["window_title"]
    if data.get("interaction_mode") in ("pynput", "frida", "hybrid"):
        raw_data["interaction_mode"] = data["interaction_mode"]
    cs = data.get("capture_size")
    if isinstance(cs, list) and len(cs) == 2:
        raw_data["capture_size"] = cs

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
                if s["type"] == "jump":
                    rid = p.get("rule_id", "")
                    if rid in id_map:
                        p["rule_id"] = id_map[rid]
                if s["type"] in ("detect", "compare", "match_image") and isinstance(
                    p.get("on_fail"), dict
                ):
                    rid = p["on_fail"].get("rule_id", "") or p["on_fail"].get("jump_rule_id", "")
                    if rid in id_map:
                        p["on_fail"]["rule_id"] = id_map[rid]
                    p["on_fail"].pop("jump_rule_id", None)
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


def collect_templates(
    live_rules: Optional[list] = None,
    live_task_name: str = "",
    exclude: Optional[tuple] = None,
) -> list[dict]:
    """收集所有任務裡 match_image 步驟的內嵌圖片（供「選擇現有圖片」挑選）。

    回傳 [{"task", "rule_id", "rule_name", "step_idx", "b64"}]，任務名排序、
    檔內規則順序；b64 僅做 base64 結構驗證，能否解碼成影像由呼叫端判斷。

    live_rules + live_task_name：以記憶體中的規則取代該任務的磁碟版本，
    讓尚未存檔的截圖也能被挑選；exclude=(rule_id, step_idx) 排除自身步驟。
    """
    found: list[dict] = []

    def _scan(rules, task_name):
        for r in rules or []:
            for i, s in enumerate(getattr(r, "steps", None) or []):
                if getattr(s, "type", "") != "match_image":
                    continue
                b64 = (getattr(s, "params", None) or {}).get("template_data", "")
                if not isinstance(b64, str) or not b64.strip():
                    continue
                try:
                    base64.b64decode(b64, validate=True)
                except (ValueError, TypeError):
                    continue
                if exclude and exclude == (getattr(r, "id", ""), i):
                    continue
                found.append(
                    {
                        "task": task_name,
                        "rule_id": getattr(r, "id", ""),
                        "rule_name": getattr(r, "name", ""),
                        "step_idx": i,
                        "b64": b64,
                    }
                )

    has_live = live_rules is not None and bool(live_task_name)
    for name in list_tasks():
        if has_live and name == live_task_name:
            continue
        try:
            _scan(load_task(name), name)
        except Exception:
            continue
    if has_live:
        _scan(live_rules, live_task_name)
    return found


if __name__ == "__main__":
    # self-check：收集／live 覆蓋磁碟版／排除自身／壞 b64 略過
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="otc_collect_tmpl_"))
    get_tasks_dir = lambda: (  # noqa: E731
        (tmp / "tasks").mkdir(parents=True, exist_ok=True) or (tmp / "tasks")
    )

    _B64_PNG_1PX = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    Step = _models.Step
    _mk_mi = lambda b64: Step(type="match_image", params={"template_data": b64})  # noqa: E731

    save_task("t1", [Rule(id="a1", name="A1", enabled=True, steps=[_mk_mi(_B64_PNG_1PX)])])
    save_task(
        "t2",
        [
            Rule(
                id="b1",
                name="B1",
                enabled=True,
                steps=[
                    Step(type="wait", params={"ms": 100}),
                    _mk_mi("not-valid-b64!!!"),
                    _mk_mi(_B64_PNG_1PX),
                ],
            )
        ],
    )

    items = collect_templates()
    assert len(items) == 2, items
    assert items[0]["task"] == "t1" and items[1]["task"] == "t2", items
    assert items[0]["step_idx"] == 0 and items[1]["step_idx"] == 2

    got = collect_templates(exclude=("b1", 2))
    assert len(got) == 1 and got[0]["rule_id"] == "a1"

    live = [Rule(id="c1", name="C1", enabled=True, steps=[_mk_mi(_B64_PNG_1PX)])]
    merged = collect_templates(live_rules=live, live_task_name="t1")
    # t1 磁碟版被 live 取代，其他任務照常收集
    assert [(m["task"], m["rule_id"]) for m in merged] == [
        ("t2", "b1"),
        ("t1", "c1"),
    ], merged
    assert all(it["rule_id"] != "a1" for it in merged), "live 應取代 t1 的磁碟版"

    print("✓ task_management collect_templates: 全部通過")
