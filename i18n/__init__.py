"""輕量 i18n 模組 — JSON 字典式翻譯，需重啟切換語言。"""

import json
import warnings
from pathlib import Path

_dir = Path(__file__).parent
_current = "zh_TW"
_cache: dict[str, dict[str, str]] = {}

# Windows LANGID primary language：0x04 = 中文（繁中／簡中／港澳皆屬）、0x11 = 日文
_LANG_CHINESE = 0x04
_LANG_JAPANESE = 0x11


def _langid_to_code(lang_id: int) -> str:
    # ponytail: 預設英文，偵測到中文系統用繁體中文、日文系統用日文
    primary = lang_id & 0xFF
    if primary == _LANG_CHINESE:
        return "zh_TW"
    if primary == _LANG_JAPANESE:
        return "ja"
    return "en"


def detect_system_language() -> str:
    """第一次啟動的預設語系：中文系統 → zh_TW、日文系統 → ja，其餘（含偵測失敗）→ en。"""
    try:
        import ctypes

        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if lang_id == 0:
            lang_id = ctypes.windll.kernel32.GetSystemDefaultUILanguage()
        return _langid_to_code(lang_id)
    except Exception:
        return "en"


def set_language(lang: str) -> None:
    # ponytail: 語言檔不存在（如舊 config 存了已淘汰的 zh_CN）時 fallback 繁中，避免 T() 逐 key 警告
    global _current
    path = _dir / f"{lang}.json"
    if not path.exists():
        lang = "zh_TW"
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


def T(msg_id: str, **kwargs) -> str:
    """翻譯查表。缺失時 fallback 到 zh_TW 並印 warning。"""
    s = _load(_current).get(msg_id)
    if s is None:
        s = _load("zh_TW").get(msg_id, msg_id)
        warnings.warn(f"[i18n] missing key '{msg_id}' in '{_current}'")
    return s.format(**kwargs) if kwargs else s
