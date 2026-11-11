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
_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_ser_mod = load_sibling("rule_serialization", "core/rule_serialization.py")
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


def _detect(text):
    return Step(type="detect", params={"text": text})


def _click():
    return Step(type="click", params={"target": "text_center"})


def _process_loop(rules, groups, group_ids=None):
    """建立可直接跑 _process_rules 的 MainLoop，並攔截所有輸入送出。

    這是「端到端語意」測試的入口：走真實的 _process_rules → _run_rule →
    _handle_detect 控制流程，而不是直接呼叫 _run_rule 或手動設定 _current_target。
    """
    ml = _main_loop()
    ml._rules = list(rules)
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = list(groups)
    ml._active_group_ids = list(group_ids if group_ids is not None else [groups[0].id])
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._last_active_rule_id = None
    ml._current_target = None
    sent: list[tuple] = []
    ml._send_click = lambda *a, **k: sent.append(("click", *a)) or True
    ml._send_key = lambda *a, **k: sent.append(("key", *a)) or True
    return ml, sent


def _ocr_returns(texts):
    """模擬 OCR 結果：回傳含指定文字的 OcrResult（空清單＝找不到任何文字）。"""

    def _region(img, roi):
        return [_ocr.OcrResult(text=t, x=100, y=200, w=40, h=20, confidence=0.99) for t in texts]

    return _region


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


# ── 8：端到端語意回歸（真實 _process_rules 控制流程）──────────────────────
#
# 下列測試一律走真實的 _process_rules → _run_rule → _handle_detect 路徑。
# 不直接手動設定 _current_target 製造預期狀態：那樣只能證明 accessor 的組字，
# 證明不了「條件未成立時，執行目標仍指向正在等待條件的那條規則」。


def test_waiting_rule_stays_as_execution_target():
    """條件未成立 → 指標不推進、從未觸發，但執行目標必須持續指向等待中的規則。"""
    rule = Rule(
        id="r-wait",
        name="等待規則",
        enabled=True,
        steps=[_detect("NEVER_MATCH"), _click()],
    )
    group = RuleGroup(
        id="g1",
        name="群組一",
        enabled=True,
        mode="once",
        order="sequential",
        rule_ids=[rule.id],
    )
    ml, sent = _process_loop([rule], [group])
    ml._ocr_region = _ocr_returns([])  # OCR 找不到文字 → 條件不成立

    for _ in range(3):
        ml._process_rules(_img(), _rect())

    assert ml._rule_in_group_ptr == 0, "條件未成立時指標不得推進"
    assert ml._last_active_rule_id is None, "未觸發的規則不得寫入 pointer"
    target = ml.get_execution_target()
    assert target is not None, "等待中的規則必須是執行目標"
    assert target["rule_id"] == rule.id
    assert target["rule_name"] == "等待規則"
    assert target["group_name"] == "群組一"
    assert target["step_idx"] == 0, "條件未成立時停在第一個步驟"
    assert target["step_total"] == 2
    assert sent == [], "條件未成立不得送出任何輸入"


def test_execution_target_advances_after_rule_triggers():
    """第一條規則條件成立並觸發後，執行目標必須切到第二條，不得殘留舊目標。"""
    first = Rule(id="r-1", name="規則一", enabled=True, steps=[_detect("MATCH"), _click()])
    second = Rule(id="r-2", name="規則二", enabled=True, steps=[_detect("ALSO_NEVER"), _click()])
    group = RuleGroup(
        id="g1",
        name="群組一",
        enabled=True,
        mode="once",
        order="sequential",
        rule_ids=[first.id, second.id],
    )
    ml, sent = _process_loop([first, second], [group])
    ml._ocr_region = _ocr_returns(["MATCH"])  # 只有第一條的條件成立

    ml._process_rules(_img(), _rect())
    assert ml._rule_in_group_ptr == 1, "觸發後指標必須推進到第二條"
    assert ml._last_active_rule_id == first.id
    assert len(sent) == 1, "只應送出第一條規則的點擊"

    ml._process_rules(_img(), _rect())
    target = ml.get_execution_target()
    assert target["rule_id"] == second.id, "目標必須切換到第二條規則"
    assert target["rule_name"] == "規則二"


def test_multiple_rules_waiting_target_updates_in_order():
    """多條規則依序等待時，執行目標必須跟著當前被評估的那條走。"""
    first = Rule(id="r-1", name="規則一", enabled=True, steps=[_detect("MATCH"), _click()])
    # 第二條用「ALSO_NEVER」：與第一條的 OCR 文字「MATCH」相似度不足，不會被
    # 模糊匹配誤判為命中（否則第二條也會觸發，群組直接完成、指標歸零）。
    second = Rule(id="r-2", name="規則二", enabled=True, steps=[_detect("ALSO_NEVER"), _click()])
    group = RuleGroup(
        id="g1",
        name="群組一",
        enabled=True,
        mode="once",
        order="sequential",
        rule_ids=[first.id, second.id],
    )
    ml, sent = _process_loop([first, second], [group])

    # ① 兩條都還沒成立 → 目標是第一條
    ml._ocr_region = _ocr_returns([])
    ml._process_rules(_img(), _rect())
    assert ml.get_execution_target()["rule_id"] == first.id
    assert ml._rule_in_group_ptr == 0

    # ② 第一條條件成立並觸發 → 指標推進
    ml._ocr_region = _ocr_returns(["MATCH"])
    ml._process_rules(_img(), _rect())
    assert ml._rule_in_group_ptr == 1
    assert ml._last_active_rule_id == first.id

    # ③ 第二條仍在等條件 → 目標必須是第二條，不得停在第一條
    ml._ocr_region = _ocr_returns(["MATCH"])
    ml._process_rules(_img(), _rect())
    target = ml.get_execution_target()
    assert target["rule_id"] == second.id, "目標不得錯誤停留在第一條"
    assert target["rule_name"] == "規則二"
    assert ml._rule_in_group_ptr == 1, "第二條條件未成立，指標不得推進"


def test_parallel_group_target_is_last_evaluated():
    """並行群組：多條規則同時被評估，現行語意＝顯示最後評估到的那條。

    本測試鎖定「現行行為」——UX3-07-F1 明確不擴充成多條顯示、不加保護／還原
    邏輯。目的是讓未來的語意變更必須被看見，而不是默默改掉。
    """
    p1 = Rule(id="r-p1", name="平行一", enabled=True, steps=[_detect("NO1")])
    p2 = Rule(id="r-p2", name="平行二", enabled=True, steps=[_detect("NO2")])
    p3 = Rule(id="r-p3", name="平行三", enabled=True, steps=[_detect("NO3")])
    group = RuleGroup(
        id="gp",
        name="平行群組",
        enabled=True,
        mode="loop",
        order="parallel",
        rule_ids=[p1.id, p2.id, p3.id],
    )
    ml, sent = _process_loop([p1, p2, p3], [group])
    ml._ocr_region = _ocr_returns([])

    ml._process_rules(_img(), _rect())

    target = ml.get_execution_target()
    assert target["rule_id"] == p3.id, "並行群組現行語意＝最後評估到的規則"
    assert sent == []


def test_blocked_rule_does_not_become_execution_target():
    """preflight BLOCKED 的規則不會進入執行目標（它本來就被略過、不執行）。"""
    bad = Rule(
        id="r-bad",
        name="壞規則",
        enabled=True,
        steps=[Step(type="click", params={"target": "bogus"})],
    )
    good = Rule(id="r-good", name="好規則", enabled=True, steps=[_detect("NO")])
    group = RuleGroup(
        id="g1",
        name="群組一",
        enabled=True,
        mode="once",
        order="sequential",
        rule_ids=[bad.id, good.id],
    )
    ml, sent = _process_loop([bad, good], [group])
    ml._ocr_region = _ocr_returns([])

    ml._process_rules(_img(), _rect())
    assert ml._rule_in_group_ptr == 1, "BLOCKED 規則應被略過"
    assert ml.get_execution_target() is None, "BLOCKED 規則不得進入執行目標"

    ml._process_rules(_img(), _rect())
    target = ml.get_execution_target()
    assert target["rule_id"] == good.id
    assert sent == []


def test_zero_step_rule_still_becomes_execution_target():
    """零步驟規則：步驟迴圈不會執行，仍必須成為執行目標（不得殘留前一條規則）。

    這是「迴圈前寫入 _current_target」的唯一有效情境：步驟數為 0 時迴圈一次都
    不跑，若只在迴圈內寫入，目標會停在上一條規則上。
    """
    empty = Rule(id="r-empty", name="空規則", enabled=True, steps=[])
    group = RuleGroup(
        id="g1",
        name="群組一",
        enabled=True,
        mode="once",
        order="sequential",
        rule_ids=[empty.id],
    )
    ml, sent = _process_loop([empty], [group])

    ml._process_rules(_img(), _rect())

    target = ml.get_execution_target()
    assert target["rule_id"] == empty.id, "零步驟規則仍是當前被評估的規則"
    assert target["step_total"] == 0


# ── 9：_current_target 生命週期（stop / 規則重載）─────────────────────────


def test_execution_target_cleared_after_stop():
    """停止後 accessor 必須回 None（不得靠 GUI 把 _loop 設 None 來掩蓋舊值）。"""
    ml = _main_loop()
    ml._current_target = ("r-ux307", 1)
    ml._thread = None
    ml._started_at = 0.0

    ml.stop()

    assert ml._current_target is None, "停止後不得殘留舊執行目標"
    assert ml.get_execution_target() is None


def test_execution_target_cleared_after_rule_reload(tmp_path):
    """規則重載後不得殘留舊目標（舊規則可能已不存在或步驟數已改變）。"""
    rule = Rule(id="r-1", name="規則一", enabled=True, steps=[_detect("NO"), _click()])
    group = RuleGroup(
        id="g1",
        name="群組一",
        enabled=True,
        mode="once",
        order="sequential",
        rule_ids=[rule.id],
    )
    path = tmp_path / "task.json"
    assert _ser_mod.save_task_with_groups([rule], [group], str(path)) is True

    ml = _main_loop()
    ml._rules_path = str(path)
    ml._rules = [rule]
    ml._rule_map = {rule.id: rule}
    ml._groups = [group]
    ml._current_target = (rule.id, 1)

    ml._load_rules()

    assert ml._current_target is None, "規則重載後不得殘留舊執行目標"
    assert ml.get_execution_target() is None
    # 重載後規則仍可正常被評估（生命週期修整不得影響排程）
    assert ml._rule_map[rule.id].name == "規則一"


def test_execution_target_kept_when_rule_reload_fails(tmp_path, monkeypatch):
    """載入失敗時規則被保留 → 舊目標仍然有效，不得誤清。"""
    monkeypatch.setattr(_ml_mod, "log_main", lambda *a, **k: None)
    bad = tmp_path / "broken.json"
    bad.write_text('{"rules": "not-a-list"}', encoding="utf-8")

    rule = Rule(id="r-ux307", name="仍在執行的規則", enabled=True, steps=[_detect("NO")])
    ml = _main_loop()
    ml._rules_path = str(bad)
    ml._rules = [rule]
    ml._rule_map = {rule.id: rule}
    ml._current_target = (rule.id, 1)

    ml._load_rules()

    assert ml._rules == [rule], "載入失敗時規則必須被保留"
    assert ml._current_target == (rule.id, 1), "載入失敗時規則未變，舊目標仍有效"
    target = ml.get_execution_target()
    assert target is not None, "規則仍在，執行目標不得被誤清"
    assert target["rule_id"] == rule.id
