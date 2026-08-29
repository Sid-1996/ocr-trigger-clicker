from dataclasses import dataclass, field

from i18n import T  # noqa: E402

_UNCATEGORIZED_ID = "__uncategorized__"
_UNCATEGORIZED_DEFAULT_NAMES = {"未歸類", "Uncategorized", "未分類"}


def group_display_name(g) -> str:
    """群組顯示名稱。

    系統「未歸類」群組（id=__uncategorized__ 且名稱維持內建預設）一律以 i18n
    即時顯示，語言切換立即生效；使用者已改名或一般群組回資料名稱。
    支援 dict 或 RuleGroup 物件。
    """
    gid = g.get("id", "") if isinstance(g, dict) else g.id
    name = g.get("name", "") if isinstance(g, dict) else g.name
    if gid == _UNCATEGORIZED_ID and name in _UNCATEGORIZED_DEFAULT_NAMES:
        return T("ui.uncategorized")
    return name


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
    notes: str = ""


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
