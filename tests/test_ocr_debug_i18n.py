"""OCR Debug 的 Verify 狀態 → i18n key 對應測試。

背景：程式碼原本用 `T(f"ocr_debug.key_test.{state}")` 直接把 state 當 i18n key，
但 key_test 命名沒有 success（成功文案是 ok），T() 缺 key 時會把原始 key 字串
當成文案回傳 → 使用者看到 "ocr_debug.key_test.success"。

本測試鎖住三件事：
- 每個 Verify 狀態在三種語言都有對應文案。
- 對應關係集中在程式端的對照表，不靠新增重複翻譯。
- 使用者可見文案不會是原始 i18n key。

狀態清單在本檔獨立列出（不從程式碼讀），避免對照表本身寫錯時測試跟著一起錯。
"""

import json
import os
import sys
import warnings
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402
from i18n import T  # noqa: E402

_mod = load_sibling("ocr_debug", "gui/09_ocr_debug.py")

_LANGS = ("zh_TW", "en", "ja")

# 程式實際會 emit 的 Verify 狀態（worker 產出 + 顯示層 fallback）
_CLICK_STATES = (
    "success",
    "no_response",
    "inject_fail",
    "black",
    "window_changed",
    "skipped",
)
_KEY_STATES = ("success", "no_change", "fail", "black", "window_changed")


def _lang_entries(lang: str) -> dict:
    return json.loads((_root / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def panel(qapp):
    p = _mod.OcrDebugPanel("", None)
    yield p
    p.deleteLater()
    qapp.processEvents()


def _click_keys(state: str) -> tuple[str, str]:
    _color, suffix = _mod._CLICK_VERIFY_STATES[state]
    return f"ocr_debug.click_verify.{suffix}", f"ocr_debug.click_verify.short.{suffix}"


def _key_keys(state: str) -> tuple[str, str]:
    _color, g_ns, g_key, s_ns, s_key = _mod._KEY_VERIFY_STATES[state]
    return f"ocr_debug.{g_ns}.{g_key}", f"ocr_debug.{s_ns}.short.{s_key}"


def _looks_like_raw_key(text: str) -> bool:
    return text.startswith("ocr_debug.") or text.startswith("missing key")


# ── 1. 每個狀態在三種語言都要有對應文案 ────────────────────────────────────


@pytest.mark.parametrize("state", _CLICK_STATES)
def test_click_verify_state_has_translation_in_all_langs(state):
    guidance_key, short_key = _click_keys(state)
    for lang in _LANGS:
        entries = _lang_entries(lang)
        assert guidance_key in entries, f"{lang} 缺少 {guidance_key}"
        assert short_key in entries, f"{lang} 缺少 {short_key}"


@pytest.mark.parametrize("state", _KEY_STATES)
def test_key_verify_state_has_translation_in_all_langs(state):
    guidance_key, short_key = _key_keys(state)
    for lang in _LANGS:
        entries = _lang_entries(lang)
        assert guidance_key in entries, f"{lang} 缺少 {guidance_key}"
        assert short_key in entries, f"{lang} 缺少 {short_key}"


def test_three_langs_share_same_verify_keys():
    per_lang = []
    for lang in _LANGS:
        entries = _lang_entries(lang)
        per_lang.append(
            {k for k in entries if k.startswith(("ocr_debug.key_test.", "ocr_debug.click_verify."))}
        )
    assert per_lang[0] == per_lang[1] == per_lang[2], "三種語言的 verify 文案 key 必須一致"


# ── 2. 對應關係本身（不靠新增重複翻譯） ─────────────────────────────────────


def test_key_verify_success_maps_to_existing_ok_key():
    _color, g_ns, g_key, s_ns, s_key = _mod._KEY_VERIFY_STATES["success"]
    assert (g_ns, g_key) == ("key_test", "ok")
    assert (s_ns, s_key) == ("key_test", "ok")


def test_no_duplicate_success_translation_added():
    """修的是 state→key 對應，不是新增一份 success 翻譯。"""
    for lang in _LANGS:
        entries = _lang_entries(lang)
        assert "ocr_debug.key_test.success" not in entries, (
            f"{lang} 不該新增 ocr_debug.key_test.success（應對應既有的 ocr_debug.key_test.ok）"
        )


def test_state_tables_cover_every_state():
    """對照表必須涵蓋所有可達狀態，且不多塞無對應翻譯的狀態。"""
    assert set(_mod._KEY_VERIFY_STATES) == set(_KEY_STATES)
    assert set(_mod._CLICK_VERIFY_STATES) == set(_CLICK_STATES)


# ── 3. 使用者可見文案不得是原始 i18n key ────────────────────────────────────


def test_key_verify_success_never_shows_raw_key(panel):
    """行為層驗證：成功狀態不得把原始 i18n key 當成文案顯示。"""
    panel._show_key_verify({"state": "success", "key": "space", "similar": 10.0})

    guidance = panel._last_verify_guidance
    assert not _looks_like_raw_key(guidance), f"成功狀態顯示原始 key：{guidance}"
    assert "space" in guidance, "成功文案應帶入實際測試按鍵"


def test_key_verify_success_shows_translation(panel):
    panel._show_key_verify({"state": "success", "key": "space", "similar": 10.0})

    guidance = panel._last_verify_guidance
    banner = panel._click_error_label.text()
    assert guidance == T("ocr_debug.key_test.ok", key="space")
    assert not _looks_like_raw_key(guidance), f"成功狀態顯示原始 key：{guidance}"
    assert "space" in guidance, "成功文案應帶入實際測試按鍵"
    assert banner == T("ocr_debug.key_test.short.ok")
    assert not _looks_like_raw_key(banner), f"成功橫幅顯示原始 key：{banner}"


def test_key_verify_failure_shows_translation(panel):
    panel._show_key_verify({"state": "fail", "key": "space", "err": "boom"})

    guidance = panel._last_verify_guidance
    banner = panel._click_error_label.text()
    assert guidance == T("ocr_debug.click_verify.inject_fail")
    assert not _looks_like_raw_key(guidance), f"失敗狀態顯示原始 key：{guidance}"
    assert banner == T("ocr_debug.click_verify.short.inject_fail")
    assert not _looks_like_raw_key(banner), f"失敗橫幅顯示原始 key：{banner}"


def test_click_verify_states_show_translation(panel):
    for state in _CLICK_STATES:
        panel._show_click_verify(state, text="確定", api_ok=True, sx=1, sy=2)
        guidance = panel._last_verify_guidance
        banner = panel._click_error_label.text()
        assert not _looks_like_raw_key(guidance), f"{state} 長文顯示原始 key：{guidance}"
        assert not _looks_like_raw_key(banner), f"{state} 橫幅顯示原始 key：{banner}"
        expected_guidance, expected_short = _click_keys(state)
        assert guidance == T(expected_guidance, text="確定")
        assert banner == T(expected_short)


def test_unknown_state_falls_back_without_raw_key(panel):
    panel._show_key_verify({"state": "不存在的狀態", "key": "space"})
    panel._show_click_verify("不存在的狀態", text="確定", api_ok=True, sx=1, sy=2)

    assert not _looks_like_raw_key(panel._last_verify_guidance)
    assert not _looks_like_raw_key(panel._click_error_label.text())


def test_no_missing_key_warning_for_any_state(panel):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for state in _KEY_STATES:
            panel._show_key_verify({"state": state, "key": "space", "similar": 1.0})
        for state in _CLICK_STATES:
            panel._show_click_verify(state, text="確定", api_ok=True, sx=1, sy=2)
    missing = [str(w.message) for w in caught if "missing key" in str(w.message)]
    assert not missing, f"不得有缺 key 警告：{missing}"
