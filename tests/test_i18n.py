"""i18n 完整性測試：程式碼用到的 T("key") 必須存在於所有語言檔。

T() 缺 key 時 fallback zh_TW，兩語言都缺則顯示原始 key 字串給使用者。
本測試就是那道守門員，防止新增 T() 呼叫卻忘了寫進 JSON。
"""

import ast
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_I18N = _ROOT / "i18n"
_SKIP = {"tests", "dist", ".opencode", "node_modules", "__pycache__", "build", ".pytest_cache"}


def _load_langs() -> dict[str, dict[str, str]]:
    return {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(_I18N.glob("*.json"))}


def _code_keys() -> set[str]:
    keys = set()
    for py in _ROOT.rglob("*.py"):
        if any(part in _SKIP for part in py.relative_to(_ROOT).parts):
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "T"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
    return keys


def test_code_keys_exist_in_all_langs():
    langs = _load_langs()
    assert langs, "i18n 目錄沒有語言檔"
    all_keys = set().union(*langs.values())
    orphans = sorted(_code_keys() - all_keys)
    assert not orphans, f"程式碼用到的 T() key 在所有語言檔皆缺漏: {orphans}"
