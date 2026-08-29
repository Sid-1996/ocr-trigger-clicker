import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402
from i18n import set_language  # noqa: E402

_models = load_sibling("rule_models", "core/rule_models.py")


def test_group_display_name():
    """系統「未歸類」群組依語言顯示；使用者改名或一般群組回資料名稱。"""
    set_language("en")
    try:
        f = _models.group_display_name
        # dict 與 RuleGroup 皆支援；預設中文名 → i18n 值
        assert f({"id": "__uncategorized__", "name": "未歸類"}) == "Uncategorized"
        assert f({"id": "__uncategorized__", "name": "Uncategorized"}) == "Uncategorized"
        g = _models.RuleGroup(id="__uncategorized__", name="未歸類", enabled=False)
        assert f(g) == "Uncategorized"
        # 使用者已改名 → 尊重自訂名稱
        assert f({"id": "__uncategorized__", "name": "雜項"}) == "雜項"
        # 一般群組 → 原名
        assert f({"id": "g1", "name": "每日"}) == "每日"
    finally:
        set_language("zh_TW")  # 復原全域語言，避免污染其他測試
