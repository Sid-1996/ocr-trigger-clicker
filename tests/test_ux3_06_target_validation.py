"""UX3-06：Click／Drag 目標選項與驗證改善。

本檔鎖住本次實作的每一條行為契約：

- target 白名單是唯一事實來源（core/rule_migration.STEP_TARGETS），
  Click 與 Drag 各用自己的白名單，不得互相套用（cursor 只屬於 Click）。
- 未知 target 在 preflight 就被擋下（status=blocked），
  使用者在開始前就看到要改哪個欄位，不必等到執行期每幀 stop。
- dry-run 預覽不得靜默略過未知 target，必須產生 terminal 記錄，
  且後續步驟必須被標記為不會執行（與引擎行為一致）。
- 執行期 MainLoop 的防禦性 stop 仍然存在（preflight 不是唯一防線）。
- GUI：cursor 目標停用抖動但保留原值；自訂座標未設定時顯示提示，
  提示純為顯示，不得變成阻擋式保存驗證。
- 三語（zh_TW／en／ja）文案鍵齊全，且 Drag 不再借用 Click 文案。
- 舊版資料與既有 Drag endpoint 修復流程不受本次改動影響。
"""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

# 正式產品路徑的 Rule/Step class object（load_sibling 的共用 rule_models 模組實例）。
# preflight 與 fingerprint 都以這個 class object 判定，測試必須用同一份建構。
_models = load_sibling("rule_models", "core/rule_models.py")
Rule = _models.Rule
Step = _models.Step

# 與 gui/run_controller.py 使用同一個 rule_preflight 模組實例（load_sibling 依
# (name, filename) 快取），因此 monkeypatch 這裡的 rule_preflight 會直接影響
# dry-run 的早退判斷。
_pre = load_sibling("rule_preflight", "core/rule_preflight.py")
rule_preflight = _pre.rule_preflight

_mig = load_sibling("rule_migration", "core/rule_migration.py")
_rc = load_sibling("run_controller", "gui/run_controller.py")
_gui = load_sibling("gui_main", "gui/06_gui_main.py")
_ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
T = _gui.T


# ── helpers ──────────────────────────────────────────────────────────────


def _rule(*steps, name="R"):
    return Rule(id="r-ux306", name=name, enabled=True, steps=list(steps))


def _click(target, **extra):
    return Step(type="click", params={"target": target, **extra})


def _drag(target, **extra):
    return Step(type="drag", params={"target": target, **extra})


class _FakeCombo:
    @staticmethod
    def currentText():
        return "dummy"


class _FakeWin:
    _window_combo = _FakeCombo()
    _rules = []


def _fake_self():
    return SimpleNamespace(
        _win=_FakeWin(),
        _of_summary=lambda *a, **k: "",
        _resolve_rule_name=lambda r: getattr(r, "name", ""),
    )


def _blank_frame():
    return np.zeros((10, 10, 3), dtype=np.uint8)


@pytest.fixture
def step_list(qt_app):
    lst = _gui._StepListWidget()
    lst.set_rules_provider(lambda: [])
    lst.set_groups_provider(lambda: [])
    lst.set_rule_id("r1")
    yield lst
    lst.deleteLater()
    qt_app.processEvents()


# ── 1／2：合法 target 通過 preflight ────────────────────────────────────


def test_click_legal_targets_pass_preflight():
    """Click 的三個合法 target（text_center／custom／cursor）都必須通過。"""
    for target in ("text_center", "custom", "cursor"):
        rule = _rule(_click(target, x=0.5, y=0.5))
        result = rule_preflight(rule)
        assert result.status == "passed", (target, result.problems)
        assert result.problems == [], (target, result.problems)


def test_drag_legal_targets_pass_preflight():
    """Drag 的兩個合法 target（text_center／custom）都必須通過。"""
    for target in ("text_center", "custom"):
        rule = _rule(_drag(target, x=0.5, y=0.5, end_x=0.6, end_y=0.6))
        result = rule_preflight(rule)
        assert result.status == "passed", (target, result.problems)
        assert result.problems == [], (target, result.problems)


def test_legal_targets_via_whitelist_function():
    """白名單純函式：合法值為 True；沒有 target 概念的 step type 一律 True。"""
    assert _mig.is_known_step_target("click", "text_center") is True
    assert _mig.is_known_step_target("click", "custom") is True
    assert _mig.is_known_step_target("click", "cursor") is True
    assert _mig.is_known_step_target("drag", "text_center") is True
    assert _mig.is_known_step_target("drag", "custom") is True
    # 沒有 target 概念的 step type → 不由本函式判斷
    assert _mig.is_known_step_target("detect", "text_center") is True
    assert _mig.is_known_step_target("key", None) is True
    # 未知值 / 非字串一律 False（不放寬）
    assert _mig.is_known_step_target("click", "bogus") is False
    assert _mig.is_known_step_target("click", None) is False
    assert _mig.is_known_step_target("click", 123) is False


# ── 3／4：未知 target → blocked ─────────────────────────────────────────


def test_unknown_click_target_blocked():
    """未知 Click target 必須在 preflight 被擋下（不再只到執行期才 stop）。"""
    rule = _rule(_click("bogus"))
    result = rule_preflight(rule)
    assert result.status == "blocked", result
    assert "unknown_click_target" in result.problems, result.problems


def test_unknown_drag_target_blocked():
    """未知 Drag target 必須在 preflight 被擋下。"""
    rule = _rule(_drag("bogus"))
    result = rule_preflight(rule)
    assert result.status == "blocked", result
    assert "unknown_drag_target" in result.problems, result.problems


# ── 5：兩種 step type 不得互相套用白名單 ────────────────────────────────


def test_drag_must_not_accept_click_only_cursor_target():
    """cursor 是 Click 專屬：Drag 用 cursor 必須被判 blocked（且問題鍵為 drag）。"""
    assert _mig.is_known_step_target("drag", "cursor") is False
    rule = _rule(_drag("cursor"))
    result = rule_preflight(rule)
    assert result.status == "blocked", result
    assert "unknown_drag_target" in result.problems, result.problems
    assert "unknown_click_target" not in result.problems, result.problems


def test_click_still_accepts_cursor_target():
    """反方向：cursor 對 Click 仍合法，不得因 Drag 白名單較窄而誤擋。"""
    rule = _rule(_click("cursor"))
    result = rule_preflight(rule)
    assert result.status == "passed", result.problems
    assert result.problems == [], result.problems


# ── 6：dry-run 不得靜默略過未知 target ──────────────────────────────────


def _bypass_preflight(monkeypatch):
    """把 preflight 換成「全部通過」，以便測到 dry-run 的步驟模擬分支。

    正常流程下未知 target 會在 preflight 就被擋下並早退（見下一支測試），
    因此這個分支是防禦性路徑，必須繞過 preflight 才驗得到。
    """
    monkeypatch.setattr(
        _pre,
        "rule_preflight",
        lambda rule: _pre.PreflightResult(status="passed", problems=[], warnings=[]),
    )


def test_dry_run_unknown_click_target_logs_terminal_and_kills_following_steps(monkeypatch):
    """未知 Click target：預覽必須留下錯誤訊息，且後續步驟標記為不會執行。"""
    monkeypatch.setattr(_rc, "get_client_rect_for_image", lambda *a, **k: None)
    monkeypatch.setattr(_rc, "get_window_client_offset", lambda *a, **k: (0, 0))
    monkeypatch.setattr(_rc, "recognize", lambda *a, **k: [])
    _bypass_preflight(monkeypatch)

    rule = _rule(
        _click("bogus"),
        Step(type="key", params={"key": "a"}),
        name="DryClick",
    )
    markers, log, dead_lines = _rc.TestRunController._run_dry_run(
        _fake_self(), rule, _blank_frame()
    )

    assert markers == []
    joined = "\n".join(log)
    assert T("exec_log.detail.unknown_click_target") in joined, joined
    # 不得出現任何假成功列
    assert "\u2713" not in joined, joined

    # 第 2 步在引擎不會執行（引擎對未知 target 直接 stop）→ 其 log 行必須被標記
    key_line = T("test.key_action", idx=2, action=T("test.key_press"), key="a")
    assert key_line in log, log
    assert log.index(key_line) in dead_lines, (log, dead_lines)


def test_dry_run_unknown_drag_target_logs_terminal_and_kills_following_steps(monkeypatch):
    """未知 Drag target：預覽必須留下錯誤訊息，且後續步驟標記為不會執行。"""
    monkeypatch.setattr(_rc, "get_client_rect_for_image", lambda *a, **k: None)
    monkeypatch.setattr(_rc, "get_window_client_offset", lambda *a, **k: (0, 0))
    monkeypatch.setattr(_rc, "recognize", lambda *a, **k: [])
    _bypass_preflight(monkeypatch)

    rule = _rule(
        _drag("bogus"),
        Step(type="key", params={"key": "a"}),
        name="DryDrag",
    )
    markers, log, dead_lines = _rc.TestRunController._run_dry_run(
        _fake_self(), rule, _blank_frame()
    )

    assert markers == []
    joined = "\n".join(log)
    assert T("exec_log.detail.unknown_drag_target") in joined, joined
    assert "\u2713" not in joined, joined

    key_line = T("test.key_action", idx=2, action=T("test.key_press"), key="a")
    assert key_line in log, log
    assert log.index(key_line) in dead_lines, (log, dead_lines)


def test_dry_run_unknown_target_is_blocked_by_preflight(monkeypatch):
    """整合路徑：preflight 啟用時，未知 target 的規則在預覽就顯示 BLOCKED。"""
    monkeypatch.setattr(_rc, "get_client_rect_for_image", lambda *a, **k: None)
    monkeypatch.setattr(_rc, "get_window_client_offset", lambda *a, **k: (0, 0))

    def _ocr_must_not_run(*a, **k):
        raise AssertionError("BLOCKED 規則不得執行 OCR / 步驟模擬")

    monkeypatch.setattr(_rc, "recognize", _ocr_must_not_run)

    rule = _rule(_click("bogus"), name="BlockedClick")
    markers, log, dead_lines = _rc.TestRunController._run_dry_run(
        _fake_self(), rule, _blank_frame()
    )
    assert markers == []
    reasons = T("exec_log.reason.unknown_click_target")
    expected = T("test.rule_blocked_header", name="BlockedClick", problems=reasons)
    assert expected in log, log
    assert dead_lines, "BLOCKED 行應被標記為不可執行"
    assert "\u2713" not in "\n".join(log)


# ── 7：執行期防禦性 stop 仍然存在 ──────────────────────────────────────


def _main_loop():
    from conftest import make_main_loop

    ml = make_main_loop()
    ml._frame_chrome = (4, 31)
    ml._frame_client_size = (1912, 1041)
    return ml


def _step_context():
    return _ml_mod.StepContext(
        img=np.zeros((1080, 1920, 3), dtype=np.uint8),
        rect={"x": 0, "y": 0, "w": 1920, "h": 1080},
    )


def test_runtime_unknown_click_target_still_stops():
    """MainLoop 的防禦性 stop 不得因新增 preflight 而被移除。"""
    ml = _main_loop()
    sent = []
    ml._send_click = lambda *a, **k: sent.append(a) or True
    rule = _rule(_click("bogus"))
    result = ml._handle_click(rule.steps[0].params, _step_context(), rule)
    assert result.action == "stop", result
    assert result.detail == T("exec_log.detail.unknown_click_target"), result
    assert sent == [], "未知 target 不得送出任何點擊"


def test_runtime_unknown_drag_target_still_stops(monkeypatch):
    """MainLoop 的防禦性 stop 不得因新增 preflight 而被移除。"""
    ml = _main_loop()
    sent = []
    monkeypatch.setattr(
        _ml_mod._input_mod, "send_drag", lambda *a, **k: sent.append(("pynput", a)) or True
    )
    monkeypatch.setattr(
        _ml_mod._bg_input, "drag", lambda *a, **k: sent.append(("frida", a)) or True
    )
    rule = _rule(_drag("bogus"))
    result = ml._handle_drag(rule.steps[0].params, _step_context(), rule)
    assert result.action == "stop", result
    assert result.detail == T("exec_log.detail.unknown_drag_target"), result
    assert sent == [], "未知 target 不得送出任何拖曳"


# ── 8：Drag text_center 執行期分支 ──────────────────────────────────────


def test_runtime_drag_text_center_uses_matched_text_center(monkeypatch):
    """Drag target=text_center：起點必須是上一個偵測結果的文字中心。"""
    ml = _main_loop()
    sent = []
    monkeypatch.setattr(_ml_mod._input_mod, "send_drag", lambda *a, **k: sent.append(a) or True)
    ctx = _step_context()
    ctx.matched_text = _ocr.OcrResult(text="START", x=100, y=200, w=40, h=20, confidence=0.99)
    params = {"target": "text_center", "end_x": 0.5, "end_y": 0.5}
    rule = _rule(_drag("text_center", end_x=0.5, end_y=0.5))
    result = ml._handle_drag(params, ctx, rule)

    assert result.action == "continue", result
    assert len(sent) == 1, sent
    args = sent[0]
    # 文字中心 = (100 + 40//2, 200 + 20//2) = (120, 210)；rect 原點為 (0,0)
    assert args[0] == 120 and args[1] == 210, args
    # 終點 0.5/0.5 → (960, 540)
    assert args[2] == 960 and args[3] == 540, args


# ── 9：Drag 專屬文案鍵三語齊全 ──────────────────────────────────────────

_NEW_KEYS = (
    "step_form.drag_target_text_center",
    "step_form.drag_target_custom",
    "step_form.drag_target_text_center_tip",
    "step_form.drag_target_custom_tip",
    "step_form.drag_target_cursor_note",
    "step_form.click_coord_unset_hint",
    "exec_log.reason.unknown_click_target",
    "exec_log.reason.unknown_drag_target",
)


def test_new_i18n_keys_exist_in_all_three_languages():
    """新增文案鍵三語齊全且非空字串。"""
    i18n_dir = _root / "i18n"
    langs = {
        f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(i18n_dir.glob("*.json"))
    }
    assert set(langs) == {"zh_TW", "en", "ja"}, sorted(langs)
    for lang, entries in langs.items():
        for key in _NEW_KEYS:
            assert key in entries, f"{lang} 缺少 {key}"
            assert entries[key].strip(), f"{lang} 的 {key} 是空字串"


def test_drag_form_uses_drag_specific_labels_not_click_labels(step_list):
    """Drag 表單不得再借用 Click 的「點擊…」文案，且不提供 cursor 選項。"""
    from PyQt6.QtCore import Qt

    step = Step(type="drag", params={"target": "custom", "x": 0.2, "y": 0.3})
    form = step_list._build_form(0, step)
    assert form is not None

    datas = [form._target.itemData(i) for i in range(form._target.count())]
    assert datas == ["text_center", "custom"], datas

    assert form._target.itemText(0) == T("step_form.drag_target_text_center")
    assert form._target.itemText(1) == T("step_form.drag_target_custom")
    # 不得與 Click 專屬文案相同
    assert form._target.itemText(0) != T("summary.click_target")
    assert form._target.itemText(1) != T("step_form.text_coord")

    tip0 = form._target.itemData(0, Qt.ItemDataRole.ToolTipRole)
    tip1 = form._target.itemData(1, Qt.ItemDataRole.ToolTipRole)
    assert tip0 == T("step_form.drag_target_text_center_tip")
    assert tip1 == T("step_form.drag_target_custom_tip")
    assert tip0 != T("step_form.target_text_center_tip")
    assert tip1 != T("step_form.target_custom_tip")

    # 明確說明拖曳不支援游標目標
    assert form._target.toolTip() == T("step_form.drag_target_cursor_note")


def test_unknown_target_problem_keys_have_translated_text():
    """preflight 問題鍵在 GUI 會被轉成 exec_log.reason.* → 必須有翻譯。"""
    for key in ("unknown_click_target", "unknown_drag_target"):
        text = T(f"exec_log.reason.{key}")
        assert text != f"exec_log.reason.{key}", "缺少翻譯"
        assert text.strip()


# ── 10：cursor 目標停用 random_offset，值必須保留 ───────────────────────


def test_cursor_target_disables_random_offset_and_preserves_value(step_list):
    """cursor 目標停用抖動控制項；切回其他目標恢復可編輯；原值不得被歸零。"""
    step = Step(
        type="click",
        params={"target": "cursor", "x": 0.1, "y": 0.2, "random_offset": 7},
    )
    form = step_list._build_form(0, step)
    assert form is not None

    # 停用中：值仍在，且不得因為停用被改寫
    assert form._offset.isEnabled() is False
    assert form._offset.value() == 7

    # 切回 text_center → 恢復可編輯，值不變
    form._target.setCurrentIndex(form._target.findData("text_center"))
    assert form._offset.isEnabled() is True
    assert form._offset.value() == 7
    form.save()
    assert step.params["random_offset"] == 7

    # 切回 custom → 仍可編輯，值不變
    form._target.setCurrentIndex(form._target.findData("custom"))
    assert form._offset.isEnabled() is True
    form.save()
    assert step.params["random_offset"] == 7

    # 再切回 cursor → 停用但原值保留（保存後仍是 7）
    form._target.setCurrentIndex(form._target.findData("cursor"))
    assert form._offset.isEnabled() is False
    form.save()
    assert step.params["random_offset"] == 7
    assert form._offset.value() == 7


def test_non_cursor_targets_keep_random_offset_editable(step_list):
    """其他目標模式不得受影響（抖動控制項維持可編輯）。"""
    for target in ("text_center", "custom"):
        step = Step(
            type="click",
            params={"target": target, "x": 0.1, "y": 0.2, "random_offset": 5},
        )
        form = step_list._build_form(0, step)
        assert form._offset.isEnabled() is True, target


# ── 11／12：Click custom 未設定座標提示（純顯示，不阻擋保存）─────────────


def test_click_custom_unset_coord_hint_is_shown(step_list):
    """target=custom 且座標仍是 (0,0) → 顯示未設定提示。"""
    step = Step(type="click", params={"target": "custom", "x": 0, "y": 0})
    form = step_list._build_form(0, step)
    assert form._coord_hint.isVisibleTo(form) is True


def test_click_custom_with_coord_hint_is_hidden(step_list):
    """已有有效座標 → 隱藏提示。"""
    step = Step(type="click", params={"target": "custom", "x": 0.4, "y": 0.5})
    form = step_list._build_form(0, step)
    assert form._coord_hint.isVisibleTo(form) is False


def test_click_hint_hidden_for_other_targets(step_list):
    """不是 custom 目標 → 不顯示座標提示。"""
    step = Step(type="click", params={"target": "text_center", "x": 0, "y": 0})
    form = step_list._build_form(0, step)
    assert form._coord_hint.isVisibleTo(form) is False


def test_click_hint_clears_after_picking_coordinates(step_list):
    """選取座標後提示必須消失（不再顯示「尚未選取」）。"""
    step_list.set_click_pick_callback(lambda: (0.5, 0.6))
    step = Step(type="click", params={"target": "custom", "x": 0, "y": 0})
    form = step_list._build_form(0, step)
    assert form._coord_hint.isVisibleTo(form) is True

    form._pick_coord()

    assert step.params["x"] == 0.5 and step.params["y"] == 0.6
    assert form._coord_hint.isVisibleTo(form) is False


def test_click_custom_zero_coord_save_is_not_blocked(step_list):
    """提示純為顯示：未設座標的 custom 仍可照常保存，不得變成阻擋式驗證。"""
    step = Step(type="click", params={"target": "custom", "x": 0, "y": 0})
    form = step_list._build_form(0, step)

    form.save()  # 不得拋例外

    assert step.params["target"] == "custom"
    assert step.params["x"] == 0 and step.params["y"] == 0


def test_click_custom_zero_coord_preflight_stays_warning_only():
    """既有行為不變：custom (0,0) 在 preflight 只是警告，不是阻擋問題。"""
    rule = _rule(_click("custom", x=0, y=0))
    result = rule_preflight(rule)
    assert result.status == "passed", result.problems
    assert result.problems == [], result.problems
    assert "custom_click_at_origin" in result.warnings, result.warnings


# ── 13：舊版資料與既有 Drag endpoint 修復流程不受影響 ──────────────────


def test_legacy_drag_data_still_detected_by_core():
    """舊版 PX offset 仍由 core 判定為 needs_repair（本次未改資料契約）。"""
    params = {"target": "custom", "x": 0.2, "y": 0.3, "dx": 30, "dy": 20}
    assert _mig.has_legacy_drag_offset(params) is True
    result = _mig.validate_drag_endpoint(params)
    assert result["status"] == "needs_repair", result
    assert result["reason"] == "legacy_px_offset", result


def test_legacy_drag_rule_still_passes_preflight():
    """舊版 Drag 規則的 target=custom 仍合法，不得被新的 target 檢查誤擋。"""
    rule = _rule(_drag("custom", x=0.2, y=0.3, dx=30, dy=20))
    result = rule_preflight(rule)
    assert result.status == "passed", result.problems
    assert result.problems == [], result.problems


def test_legacy_drag_repair_banner_still_appears(step_list):
    """既有修復入口不受影響：舊版 Drag 開啟表單仍出現修復 banner。"""
    legacy = Step(
        type="drag",
        params={"target": "custom", "x": 0.2, "y": 0.3, "dx": 30, "dy": 20},
    )
    form = step_list._build_form(0, legacy)
    assert form._repair_banner is not None

    modern = Step(
        type="drag",
        params={
            "target": "custom",
            "x": 0.2,
            "y": 0.3,
            "end_x": 0.5,
            "end_y": 0.5,
            "end_roi_coord": "client",
        },
    )
    form2 = step_list._build_form(0, modern)
    assert form2._repair_banner is None


# ── GUI 驗收：真實 Qt Widget／真實 MainWindow ─────────────────────────────
#
# 下列測試一律操作真實 Qt Widget（不是 mock、不是 helper）：
#   * step_list     → 真實 _StepListWidget → 真實 _ClickStepForm／_DragStepForm
#   * real_mainwindow → 真實 MainWindow → 真實步驟編輯器 → 真實表單 →
#                      真實存檔（產品自己的 save_task_with_groups）→ 真實重載


def test_click_form_target_options_and_tooltips(step_list):
    """Click 表單的三個選項與 tooltip 必須齊全且互異（Drag 專屬說明不得外洩）。"""
    from PyQt6.QtCore import Qt

    step = Step(type="click", params={"target": "text_center"})
    form = step_list._build_form(0, step)
    assert form is not None

    datas = [form._target.itemData(i) for i in range(form._target.count())]
    assert datas == ["text_center", "custom", "cursor"], datas

    assert form._target.itemText(0) == T("summary.click_target")
    assert form._target.itemText(1) == T("step_form.text_coord")
    assert form._target.itemText(2) == T("step_form.click_target_cursor")

    tips = [
        form._target.itemData(i, Qt.ItemDataRole.ToolTipRole) for i in range(form._target.count())
    ]
    assert tips == [
        T("step_form.target_text_center_tip"),
        T("step_form.target_custom_tip"),
        T("step_form.target_cursor_tip"),
    ], tips
    # 每個選項都要有自己的說明
    assert len(set(tips)) == 3, tips
    # Drag 專屬的「拖曳不支援游標目標」不得出現在 Click 表單
    assert T("step_form.drag_target_cursor_note") not in form._target.toolTip()


def test_real_window_cursor_target_survives_save_and_reload(
    real_mainwindow, write_task, make_step, make_rule
):
    """真實視窗：切到 cursor 目標 → 抖動停用 → 存檔 → 重載，設定不得遺失。"""
    win = real_mainwindow
    write_task(
        "t_cursor",
        [
            make_rule(
                "r0",
                "規則零",
                [make_step("click", target="text_center", x=0.2, y=0.3, random_offset=7)],
            )
        ],
    )
    win._on_task_changed("t_cursor")
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    assert type(form).__name__ == "_ClickStepForm"

    # 走真實 combo 的 currentIndexChanged
    form._target.setCurrentIndex(form._target.findData("cursor"))
    assert form._offset.isEnabled() is False
    assert form._offset.value() == 7

    win._save_current_rule()
    assert win._flush_save() is True

    # 重載：真的從磁碟讀回來
    win._on_task_changed("t_cursor")
    win._step_list._toggle_expand(0)
    reloaded = win._step_list._expanded_form
    assert type(reloaded).__name__ == "_ClickStepForm"
    assert reloaded._target.currentData() == "cursor"
    assert reloaded._offset.isEnabled() is False, "重載後 cursor 目標仍應停用抖動"
    assert reloaded._offset.value() == 7
    assert reloaded._step.params["random_offset"] == 7
    # 重載後的規則仍須通過 preflight（cursor 是合法 target）
    assert rule_preflight(win._get_current_rule()).status == "passed"


def test_real_window_picked_coords_survive_save_and_reload(
    real_mainwindow, write_task, make_step, make_rule
):
    """真實視窗：拾取座標（提示消失）→ 存檔 → 重載，座標不得遺失、提示不得復原。"""
    win = real_mainwindow
    write_task(
        "t_coords",
        [make_rule("r0", "規則零", [make_step("click", target="custom", x=0, y=0)])],
    )
    win._on_task_changed("t_coords")
    # 假 picker 必須在建表單之前就緒：表單在建構當下就抓住了 callback
    win._step_list.set_click_pick_callback(lambda: (0.42, 0.55))
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    assert form._coord_hint.isVisibleTo(form) is True, "尚未選取座標時應顯示提示"

    form._pick_coord()
    assert form._step.params["x"] == 0.42 and form._step.params["y"] == 0.55
    assert form._step.params["roi_coord"] == "client"
    assert form._coord_hint.isVisibleTo(form) is False, "選取座標後提示應消失"

    win._save_current_rule()
    assert win._flush_save() is True

    win._on_task_changed("t_coords")
    win._step_list.set_click_pick_callback(lambda: (0.42, 0.55))
    win._step_list._toggle_expand(0)
    reloaded = win._step_list._expanded_form
    assert reloaded._step.params["x"] == 0.42
    assert reloaded._step.params["y"] == 0.55
    assert reloaded._step.params["roi_coord"] == "client"
    assert reloaded._coord_hint.isVisibleTo(reloaded) is False, "重載後座標仍在，提示不得復原"


def test_real_window_step_form_hint_is_visible_and_not_clipped(
    real_mainwindow, write_task, make_step, make_rule, qt_app
):
    """真實版面：座標提示必須可見且未被裁切；拖曳選項文字不得被 elide。"""
    win = real_mainwindow
    write_task(
        "t_layout",
        [
            make_rule(
                "r0",
                "規則零",
                [
                    make_step("click", target="custom", x=0, y=0),
                    make_step(
                        "drag",
                        target="custom",
                        x=0.2,
                        y=0.3,
                        end_x=0.5,
                        end_y=0.5,
                        end_roi_coord="client",
                    ),
                ],
            )
        ],
    )
    win._on_task_changed("t_layout")
    win.show()
    qt_app.processEvents()

    win._step_list._toggle_expand(0)
    click_form = win._step_list._expanded_form
    hint = click_form._coord_hint
    assert hint.isVisibleTo(click_form) is True
    assert hint.width() >= hint.sizeHint().width(), "座標提示文字被裁切"
    assert hint.height() >= hint.sizeHint().height(), "座標提示文字被裁切"

    win._step_list._toggle_expand(1)
    drag_form = win._step_list._expanded_form
    combo = drag_form._target
    fm = combo.fontMetrics()
    widest = max(fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count()))
    assert combo.width() >= widest, "拖曳目標選項文字被 elide"
