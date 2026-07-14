import json
import logging
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _loader import load_sibling, log_main

_migration = load_sibling("rule_migration", "core/rule_migration.py")
_migrate_v1_to_v2 = _migration._migrate_v1_to_v2
_normalize_step_params = _migration._normalize_step_params
migrate_v2_to_v3 = _migration.migrate_v2_to_v3
_migrate_roi_to_ratio = _migration._migrate_roi_to_ratio
_migrate_roi_coord = _migration._migrate_roi_coord

_models = load_sibling("rule_models", "core/rule_models.py")
Rule = _models.Rule
Step = _models.Step
RuleGroup = _models.RuleGroup

_utils = load_sibling("file_utils", "core/file_utils.py")
_replace_file = _utils._replace_file


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
        use_condition_list=bool(d.get("use_condition_list", False)),
        condition_list=d.get("condition_list"),
        condition_list_advance_on_no_match=bool(d.get("condition_list_advance_on_no_match", False)),
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
    groups = [_dict_to_group(g) for g in groups]
    logging.info("[load_groups] loaded=%s", [(g.id, list(g.rule_ids)) for g in groups])
    return groups


def save_groups(groups: list[RuleGroup], path: str) -> bool:
    logging.info(
        "[save_groups] path=%s groups=%s", path, [(g.id, list(g.rule_ids)) for g in groups]
    )
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


def load_rules(path: str) -> list[Rule]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, KeyError) as e:
        log_main(f"規則檔案載入失敗「{path}」: {e}")
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
            log_main(f"規則項目解析失敗，已略過: {e}")
            continue
    logging.info(
        "[load_rules] loaded=%d background=%s", len(rules), [r.id for r in rules if r.background]
    )
    return rules


def save_rules(rules: list[Rule], path: str) -> bool:
    bg_ids = [r.id for r in rules if r.background]
    logging.info("[save] save_rules: rules=%d, background=%s, path=%s", len(rules), bg_ids, path)
    logging.info(
        "[save_rules] rules(%d) names=%s background_ids=%s",
        len(rules),
        [r.name for r in rules],
        bg_ids,
    )
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
