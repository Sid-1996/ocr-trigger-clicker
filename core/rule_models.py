from dataclasses import dataclass, field


@dataclass
class ImportPreview:
    meta: dict
    rule_names: list[str]
    rule_count: int
    warnings: list[str]
    raw_data: dict


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
    condition_list: list | None = None
    condition_list_advance_on_no_match: bool = False


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
