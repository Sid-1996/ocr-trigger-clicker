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
class Condition:
    detect: dict
    action: dict
    on_match: str = "next_step"


@dataclass
class ConditionListParams:
    conditions: list[Condition]
    advance_on_no_match: bool = False
    loop: bool = True


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
