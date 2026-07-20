"""輕量 i18n 模組 — JSON 字典式翻譯，需重啟切換語言。"""

import json
import warnings
from pathlib import Path

_dir = Path(__file__).parent
_current = "zh_TW"
_cache: dict[str, dict[str, str]] = {}


def set_language(lang: str) -> None:
    global _current
    _current = lang


def get_language() -> str:
    return _current


def _load(lang: str) -> dict[str, str]:
    if lang not in _cache:
        path = _dir / f"{lang}.json"
        try:
            _cache[lang] = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _cache[lang] = {}
    return _cache[lang]


def T(key: str, **kwargs) -> str:
    """翻譯查表。缺失時 fallback 到 zh_TW 並印 warning。"""
    s = _load(_current).get(key)
    if s is None:
        s = _load("zh_TW").get(key, key)
        warnings.warn(f"[i18n] missing key '{key}' in '{_current}'")
    return s.format(**kwargs) if kwargs else s
