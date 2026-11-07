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
    code_keys = _code_keys()
    missing = {lang: sorted(code_keys - entries.keys()) for lang, entries in langs.items()}
    assert not any(missing.values()), f"Missing code translation keys by language: {missing}"


def test_language_keys_match():
    langs = _load_langs()
    assert langs, "No language files found"
    all_keys = set().union(*langs.values())
    missing = {lang: sorted(all_keys - entries.keys()) for lang, entries in langs.items()}
    assert not any(missing.values()), f"Inconsistent language keys: {missing}"


def test_guide_text_has_no_obsolete_ui_names():
    """UX 2B-01：指南不得指向不存在的 UI（「儲存規則」/右上角「？」按鈕）。"""
    langs = _load_langs()
    zh = langs["zh_TW"]
    guide_keys = [
        k for k in zh if k.startswith("guide.") or k in ("ui.start_guide", "step_form.detect_hint")
    ]
    assert guide_keys
    for key in guide_keys:
        text = zh[key]
        assert "儲存規則" not in text, f"過時文案仍在 {key}: {text!r}"
        assert "右上角" not in text, f"過時方位仍在 {key}: {text!r}"
    assert "新增規則" in zh["guide.step2"]
    assert "測試" in zh["guide.step4"]
    assert "自動儲存" in zh["step_form.detect_hint"]


def test_langid_to_code():
    from i18n import _langid_to_code

    # primary language 0x04 = 中文，sublanguage 一律歸繁中
    assert _langid_to_code(0x0404) == "zh_TW"  # zh-TW
    assert _langid_to_code(0x0804) == "zh_TW"  # zh-CN
    assert _langid_to_code(0x0C04) == "zh_TW"  # zh-HK
    # primary language 0x11 = 日文
    assert _langid_to_code(0x0411) == "ja"  # ja-JP
    # 非中文/日文（含偵測失敗的 0）→ 預設英文
    assert _langid_to_code(0x0409) == "en"  # en-US
    assert _langid_to_code(0x0C0A) == "en"  # es-ES
    assert _langid_to_code(0) == "en"
