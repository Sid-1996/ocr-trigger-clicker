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
_as_int = _migration._as_int
migrate_v2_to_v3 = _migration.migrate_v2_to_v3
_migrate_roi_to_ratio = _migration._migrate_roi_to_ratio
_migrate_roi_coord = _migration._migrate_roi_coord

_models = load_sibling("rule_models", "core/rule_models.py")
Rule = _models.Rule
Step = _models.Step
RuleGroup = _models.RuleGroup


_utils = load_sibling("file_utils", "core/file_utils.py")
_replace_file = _utils._replace_file


class RuleFileError(Exception):
    """JSON task/config load or unsafe overwrite error."""

    def __init__(self, path: str | Path, reason: str):
        self.path = str(path)
        self.reason = str(reason)
        super().__init__(f"「{self.path}」: {self.reason}")


def _read_json_object(path: str | Path) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeError) as e:
        err = RuleFileError(p, f"無法讀取或解析 JSON：{e}")
        log_main(f"JSON 載入失敗：{err}")
        raise err from e
    if not isinstance(data, dict):
        err = RuleFileError(p, "JSON 根層級必須是物件")
        log_main(f"JSON 載入失敗：{err}")
        raise err
    return data


def _validate_task_structure(data: dict, p: Path, *, overwrite: bool = False) -> None:
    suffix = "，拒絕覆寫" if overwrite else ""
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise RuleFileError(p, f"rules 必須是陣列{suffix}")
    groups = data.get("groups", [])
    if not isinstance(groups, list):
        raise RuleFileError(p, f"groups 必須是陣列{suffix}")
    for i, group in enumerate(groups):
        if not isinstance(group, dict):
            raise RuleFileError(p, f"群組 {i} 必須是物件{suffix}")
        rule_ids = group.get("rule_ids", [])
        if not isinstance(rule_ids, list) or any(not isinstance(rid, str) for rid in rule_ids):
            raise RuleFileError(p, f"群組 {i} 的 rule_ids 必須是字串陣列{suffix}")
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise RuleFileError(p, f"規則 {i} 必須是物件{suffix}")
        if "steps" not in rule:
            continue  # v1 legacy, migrated by _dict_to_rule
        name = rule.get("name", "")
        label = f"規則 {i}" + (f"「{name}」" if isinstance(name, str) and name else "")
        steps = rule["steps"]
        if not isinstance(steps, list):
            raise RuleFileError(p, f"{label} 的 steps 必須是陣列{suffix}")
        for j, step in enumerate(steps):
            if not isinstance(step, dict):
                raise RuleFileError(p, f"{label} 的步驟 {j} 必須是物件{suffix}")
            if "params" in step and not isinstance(step["params"], dict):
                raise RuleFileError(p, f"{label} 的步驟 {j} 的 params 必須是物件{suffix}")


def _read_existing_for_save(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            existing = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeError) as e:
        raise RuleFileError(p, f"既有檔案無法解析，拒絕覆寫：{e}") from e
    if not isinstance(existing, dict):
        raise RuleFileError(p, "既有檔案根層級不是物件，拒絕覆寫")
    _validate_task_structure(existing, p, overwrite=True)
    return existing


def _dict_to_rule(d: dict) -> Rule:
    if "steps" not in d:
        d = _migrate_v1_to_v2(d)
    steps = [
        Step(
            type=str(s.get("type", "")),
            params=_normalize_step_params(
                str(s.get("type", "")), s.get("params"), rule_name=str(d.get("name", ""))
            ),
        )
        for s in d.get("steps", [])
    ]
    return Rule(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        enabled=bool(d.get("enabled", True)),
        steps=steps,
        background=bool(d.get("background", False)),
        quiet=bool(d.get("quiet", False)),
        notes=str(d.get("notes", "")),
    )


def _rule_to_dict(r: Rule) -> dict:
    d = asdict(r)
    d.pop("trigger_count", None)
    d.pop("last_trigger_time", None)
    return d


def _dict_to_group(d: dict) -> RuleGroup:
    mode = str(d.get("mode", "once"))
    if mode not in _models._VALID_GROUP_MODES:
        mode = "once"
    order = str(d.get("order", "sequential"))
    if order not in _models._VALID_GROUP_ORDERS:
        order = "sequential"
    rule_ids = d.get("rule_ids", [])
    if not isinstance(rule_ids, (list, tuple)):
        rule_ids = []
    return RuleGroup(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        enabled=bool(d.get("enabled", True)),
        mode=mode,
        repeat_times=_as_int(d.get("repeat_times", 1), 1),
        between_rounds_sec=_as_int(d.get("between_rounds_sec", 0), 0),
        rule_ids=[str(r) for r in rule_ids if r],
        order=order,
    )


def _group_to_dict(g: RuleGroup) -> dict:
    return asdict(g)


def load_groups(path: str) -> list[RuleGroup]:
    p = Path(path)
    data = _read_json_object(p)
    if data is None:
        return []
    _validate_task_structure(data, p)
    if "groups" not in data:
        data = migrate_v2_to_v3(data)
    groups = data.get("groups", [])
    groups = [_dict_to_group(g) for g in groups]
    logging.debug("[load_groups] n=%d", len(groups))
    return groups


def save_groups(groups: list[RuleGroup], path: str) -> bool:
    logging.debug("[save_groups] path=%s n=%d", path, len(groups))
    tmp_path: str = ""
    try:
        data = {"groups": [_group_to_dict(g) for g in groups]}
        p = Path(path)
        for k, v in _read_existing_for_save(p).items():
            if k != "groups":
                data[k] = v
        with tempfile.NamedTemporaryFile(
            "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path = f.name
        _replace_file(tmp_path, str(p))
        return True
    except RuleFileError as e:
        log_main(f"儲存失敗，未覆寫原始檔案：{e}")
        return False
    except OSError:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        return False


def save_task_with_groups(rules: list[Rule], groups: list[RuleGroup], path: str) -> bool:
    """單次原子寫入規則+群組，保留既有其他鍵（meta/window_title/_collapsed_groups）。

    供「錄製轉換加入既有任務」使用：兩段式 save_rules + save_groups 在失敗時
    可能留下半成品任務，此函式一次寫完避免破壞既有任務。
    """
    logging.debug(
        "[save_task_with_groups] path=%s rules=%d groups=%d", path, len(rules), len(groups)
    )
    tmp_path: str = ""
    try:
        data = {
            "rules": [_rule_to_dict(r) for r in rules],
            "groups": [_group_to_dict(g) for g in groups],
        }
        p = Path(path)
        for k, v in _read_existing_for_save(p).items():
            if k not in data:
                data[k] = v
        with tempfile.NamedTemporaryFile(
            "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path = f.name
        _replace_file(tmp_path, str(p))
        return True
    except RuleFileError as e:
        log_main(f"儲存失敗，未覆寫原始檔案：{e}")
        return False
    except OSError:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        return False


def load_rules(path: str) -> list[Rule]:
    p = Path(path)
    data = _read_json_object(p)
    if data is None:
        return []

    _validate_task_structure(data, p)

    migrate = "groups" not in data
    if migrate:
        data = migrate_v2_to_v3(data)

    rules: list[Rule] = []
    for i, raw in enumerate(data.get("rules", [])):
        try:
            rules.append(_dict_to_rule(raw))
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            raise RuleFileError(p, f"規則 {i} 轉換失敗：{e}") from e

    if migrate:
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

    logging.debug("[load_rules] n=%d", len(rules))
    return rules


def save_rules(rules: list[Rule], path: str) -> bool:
    logging.debug("[save_rules] path=%s n=%d", path, len(rules))
    tmp_path: str = ""
    try:
        data = {"rules": [_rule_to_dict(r) for r in rules]}
        p = Path(path)
        for k, v in _read_existing_for_save(p).items():
            if k != "rules":
                data[k] = v
        with tempfile.NamedTemporaryFile(
            "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path = f.name
        _replace_file(tmp_path, str(p))
        return True
    except RuleFileError as e:
        log_main(f"儲存失敗，未覆寫原始檔案：{e}")
        return False
    except OSError:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        return False
