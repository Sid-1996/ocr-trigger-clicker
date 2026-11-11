"""UX3-07：執行中「在跑什麼」可視化。

本檔鎖住本次實作的每一條行為契約：

- 引擎提供 get_execution_target()：回「本幀實際評估到的規則 + 步驟序號」。
  它與「最後觸發的規則」（_last_active_rule_id）是兩件事——等待條件的規則
  不會觸發，只看 pointer 會誤以為程式沒在跑。
- 尚未評估任何規則時回 None；每次啟動都必須重置。
- 背景規則不佔用前景執行目標顯示位。
- GUI 狀態列顯示「群組／規則／步驟」，停止後清空。
- 群組選擇對話框每個群組都顯示啟用規則數。
- 三語文案鍵齊全，且佔位符三語一致。
"""

import json
import os
import string
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

# 正式產品路徑的 Rule/Step/RuleGroup class object（load_sibling 的共用模組實例）。
_models = load_sibling("rule_models", "core/rule_models.py")
Rule = _models.Rule
Step = _models.Step
RuleGroup = _models.RuleGroup
group_display_name = _models.group_display_name

_ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
_gui = load_sibling("gui_main", "gui/06_gui_main.py")
T = _gui.T


# ── helpers ──────────────────────────────────────────────────────────────


def _main_loop():
    from conftest import make_main_loop

    ml = make_main_loop()
    ml._frame_chrome = (4, 31)
    ml._frame_client_size = (1912, 1041)
    ml._last_active_rule_id = None
    return ml


def _rect():
    return {"x": 0, "y": 0, "w": 1920, "h": 1080}


def _img():
    return np.zeros((1080, 1920, 3), dtype=np.uint8)


def _wait_rule(rule_id="r-ux307", name="跑馬規則", steps=3):
    """一條只含 wait 步驟的規則：不送任何輸入，但會真的走完 _run_rule 的步驟迴圈。"""
    return Rule(
        id=rule_id,
        name=name,
        enabled=True,
        steps=[Step(type="wait", params={"ms": 1}) for _ in range(steps)],
    )


def _ctx():
    return _ml_mod.StepContext(img=_img(), rect=_rect())


# ── 1：尚未評估任何規則 → None ───────────────────────────────────────────


def test_execution_target_is_none_before_any_rule_runs():
    """還沒評估過任何規則時不得回報任何執行目標（狀態列應為空）。"""
    ml = _main_loop()
    assert ml._current_target is None
    assert ml.get_execution_target() is None


# ── 2：評估規則後回報「規則 + 群組 + 步驟」 ─────────────────────────────


def test_execution_target_reports_rule_group_and_step():
    """走真實 _run_rule：跑完後必須回報最後評估到的規則、群組與步驟序號。"""
    ml = _main_loop()
    rule = _wait_rule(steps=3)
    group = RuleGroup(id="g-run", name="跑馬", rule_ids=[rule.id])
    ml._rules = [rule]
    ml._rule_map = {rule.id: rule}
    ml._groups = [group]

    ml._run_rule(rule, _img(), _rect(), _ctx())

    target = ml.get_execution_target()
    assert target is not None
    assert target["rule_id"] == rule.id
    assert target["rule_name"] == "跑馬規則"
    assert target["group_id"] == "g-run"
    assert target["group_name"] == "跑馬"
    assert target["step_idx"] == 2, "應是最後評估到的步驟（0-based）"
    assert target["step_total"] == 3


def test_execution_target_is_currently_evaluated_not_last_triggered():
    """pointer（最後觸發）與執行目標（正在評估）必須是兩件事。"""
    ml = _main_loop()
    rule_a = _wait_rule("r-a", "規則甲")
    rule_b = _wait_rule("r-b", "規則乙")
    ml._rules = [rule_a, rule_b]
    ml._rule_map = {r.id: r for r in (rule_a, rule_b)}
    ml._groups = [RuleGroup(id="g", name="群組", rule_ids=[rule_a.id, rule_b.id])]

    ml._last_active_rule_id = rule_a.id  # 最後觸發的是甲
    ml._current_target = (rule_b.id, 0)  # 但正在評估的是乙

    target = ml.get_execution_target()
    assert target["rule_id"] == rule_b.id
    assert target["rule_name"] == "規則乙"


def test_execution_target_none_when_rule_disappeared():
    """規則被刪除／重新載入後，執行目標不得回報幽靈資料。"""
    ml = _main_loop()
    ml._current_target = ("r-gone", 0)
    assert ml.get_execution_target() is None


# ── 3：背景規則不佔用前景執行目標顯示位 ─────────────────────────────────


def test_background_rule_does_not_take_foreground_execution_target():
    """背景規則照跑，但不得覆蓋前景的執行目標顯示。"""
    ml = _main_loop()
    rule = _wait_rule()
    ml._rules = [rule]
    ml._rule_map = {rule.id: rule}
    ml._groups = [RuleGroup(id="g", name="群組", rule_ids=[rule.id])]

    ml._run_rule(rule, _img(), _rect(), _ctx(), background=True)

    assert ml._current_target is None, "背景規則不得寫入前景執行目標"
    assert ml.get_execution_target() is None


# ── 4：啟動時重置執行目標 ───────────────────────────────────────────────


def test_start_resets_execution_target():
    """上一輪的執行目標不得留到新一輪（每次啟動都是新的觀察期）。"""
    ml = _main_loop()
    ml._current_target = ("r-ux307", 1)
    ml._loop = lambda: None  # 避免真的跑擷取迴圈

    ml.start()
    try:
        assert ml._current_target is None
        assert ml.get_execution_target() is None
    finally:
        ml.stop()


# ── 5：GUI 狀態列 ────────────────────────────────────────────────────────


def test_status_label_shows_current_target(real_mainwindow):
    """真實 MainWindow：狀態列必須顯示群組／規則／步驟。"""
    win = real_mainwindow
    ml = _main_loop()
    ml._thread = SimpleNamespace(is_alive=lambda: True)
    rule = _wait_rule(steps=3)
    group = RuleGroup(id="g-run", name="跑馬", rule_ids=[rule.id])
    ml._rules = [rule]
    ml._rule_map = {rule.id: rule}
    ml._groups = [group]
    ml._current_target = (rule.id, 1)

    win._loop = ml
    win._update_rule_status()

    text = win._exec_target_label.text()
    expected = T("status.exec_target", group="跑馬", rule="跑馬規則") + T(
        "status.exec_target.step", step=2, total=3
    )
    assert text == expected, text
    assert "跑馬" in text and "跑馬規則" in text
    assert "2/3" in text, "步驟序號必須是 1-based 顯示"

    # 測試替身不是真的循環：卸下以免 fixture teardown 呼叫 stop()
    win._loop = None


def test_status_label_cleared_when_loop_stopped(real_mainwindow):
    """停止後狀態列必須清空（不得殘留上一輪的執行目標）。"""
    win = real_mainwindow
    ml = _main_loop()
    ml._thread = SimpleNamespace(is_alive=lambda: True)
    rule = _wait_rule(steps=3)
    ml._rules = [rule]
    ml._rule_map = {rule.id: rule}
    ml._groups = [RuleGroup(id="g-run", name="跑馬", rule_ids=[rule.id])]
    ml._current_target = (rule.id, 1)

    win._loop = ml
    win._update_rule_status()
    assert win._exec_target_label.text() != ""

    win._loop = None
    win._update_rule_status()
    assert win._exec_target_label.text() == ""


def test_status_label_empty_before_any_run(real_mainwindow):
    """尚未啟動時狀態列不得顯示任何執行目標。"""
    win = real_mainwindow
    win._update_exec_target_label()
    assert win._exec_target_label.text() == ""


# ── 6：群組選擇對話框顯示啟用規則數 ─────────────────────────────────────


def test_group_dialog_shows_enabled_rule_count(real_mainwindow, monkeypatch):
    """真實 MainWindow + 真實對話框：每個群組都要標出會跑幾條啟用規則。"""
    from PyQt6.QtWidgets import QCheckBox, QDialog

    win = real_mainwindow
    groups = [
        RuleGroup(id="g1", name="跑馬", enabled=True, rule_ids=["r1", "r2"]),
        RuleGroup(id="g2", name="採集", enabled=True, rule_ids=["r3", "r4"]),
    ]
    rules = [
        Rule(id="r1", name="A", enabled=True, steps=[]),
        Rule(id="r2", name="B", enabled=True, steps=[]),
        Rule(id="r3", name="C", enabled=True, steps=[]),
        Rule(id="r4", name="D", enabled=False, steps=[]),
    ]
    win._groups = groups
    win._rules = rules

    captured = {}

    def _fake_exec(self):
        captured["dialog"] = self
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", _fake_exec)

    selected = win._group_selection_ctrl.show(win)
    assert selected == ["g1", "g2"]

    dialog = captured["dialog"]
    boxes = {
        cb.property("gid"): cb.text() for cb in dialog.findChildren(QCheckBox) if cb.property("gid")
    }
    assert boxes["g1"] == group_display_name(groups[0]) + T("dialog.group_rule_count", count=2)
    assert boxes["g2"] == group_display_name(groups[1]) + T("dialog.group_rule_count", count=1)


# ── 7：i18n ──────────────────────────────────────────────────────────────

_NEW_KEYS = (
    "status.exec_target",
    "status.exec_target.step",
    "status.exec_target.tooltip",
    "dialog.group_rule_count",
)

_PLACEHOLDERS = {
    "status.exec_target": {"group", "rule"},
    "status.exec_target.step": {"step", "total"},
    "status.exec_target.tooltip": set(),
    "dialog.group_rule_count": {"count"},
}


def _fields(tpl: str) -> set:
    return {f for _, f, _, _ in string.Formatter().parse(tpl) if f}


def _langs():
    i18n_dir = _root / "i18n"
    return {
        f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(i18n_dir.glob("*.json"))
    }


def test_new_i18n_keys_exist_in_all_three_languages():
    """新增文案鍵三語齊全且非空字串。"""
    langs = _langs()
    assert set(langs) == {"zh_TW", "en", "ja"}, sorted(langs)
    for lang, entries in langs.items():
        for key in _NEW_KEYS:
            assert key in entries, f"{lang} 缺少 {key}"
            assert entries[key].strip(), f"{lang} 的 {key} 是空字串"


def test_exec_target_placeholders_match_across_languages():
    """三語的佔位符必須一致，否則切換語言會直接炸 format()。"""
    for lang, entries in _langs().items():
        for key, expected in _PLACEHOLDERS.items():
            assert _fields(entries[key]) == expected, (lang, key, entries[key])


def test_exec_target_text_formats_without_key_error():
    """實際組字：所有佔位符都必須有值（缺值會在 GUI 直接拋例外）。"""
    text = T("status.exec_target", group="跑馬", rule="跑馬規則") + T(
        "status.exec_target.step", step=2, total=3
    )
    assert "跑馬" in text and "跑馬規則" in text and "2/3" in text
    assert T("dialog.group_rule_count", count=3).strip()
