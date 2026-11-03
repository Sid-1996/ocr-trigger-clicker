"""P2-3：_notified_conditions（通知去重鎖存）的生命週期。

語意（依實際程式碼與呼叫鏈，非變數名稱推測）：

- `_notified_conditions` 記錄的是「本次條件成立期間已經通知過的 rule.id」，
  不是「目前持續成立的條件」。
- 寫入：`core/05_main_loop.py:1780` `_handle_notify` 在送出通知且
  `ctx.matched_ns` 有值（代表前面有偵測步驟成立）時 `add(rule.id)`。
- 重新武裝：`core/05_main_loop.py:2061` `_run_rule` 在「首個偵測步驟失敗」
  （條件不成立）時 `discard(rule.id)`，使條件再次成立時可以再通知。
- 觀察期邊界：`start()`（每次啟動）與 `_load_rules()`（規則重載）必須清除，
  否則上一個觀察期的鎖存會抑制新觀察期的首次命中。

本檔以真實的 `_run_rule` / `_handle_notify` / `start` / `stop` / `_load_rules`
驅動狀態轉換，只取代 OCR 輸入與通知接收端；不直接改寫 `_notified_conditions`
的內容來製造結果。
"""

import sys
from pathlib import Path

import numpy as np
import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from conftest import make_main_loop  # noqa: E402

from _loader import load_sibling  # noqa: E402

_ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
_ocr_mod = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_ser_mod = load_sibling("rule_serialization", "core/rule_serialization.py")

Rule = _rule_mod.Rule
Step = _rule_mod.Step
RuleGroup = _rule_mod.RuleGroup
OcrResult = _ocr_mod.OcrResult

TARGET = "確定"
MSG = "P2-3 通知訊息"

# 100x100：寬度 ≤ 800，不會觸發 _handle_detect 的大尺寸效能警告
# （該警告會呼叫 on_warning，污染通知計數）。
IMG = np.zeros((100, 100, 3), dtype=np.uint8)
RECT = {"x": 0, "y": 0, "w": 100, "h": 100}


@pytest.fixture
def ml(monkeypatch):
    """MainLoop 實例：可控制 OCR 與通知接收端，且不會啟動真實擷取執行緒。"""
    # start()/stop() 會寫 app.log；測試不污染使用者的 log。
    monkeypatch.setattr(_ml_mod, "log_main", lambda *a, **k: None)
    m = make_main_loop()
    m._thread = None
    # 讓 start() 產生的背景執行緒立即結束（不真的擷取、不真的送輸入）。
    m._loop = lambda: None
    return m


def _notify_rule(rule_id: str = "r1") -> Rule:
    """首步偵測、次步通知的規則（canonical Step 物件，preflight 可通過）。"""
    return Rule(
        id=rule_id,
        name="通知規則",
        enabled=True,
        steps=[
            Step(type="detect", params={"text": TARGET}),
            Step(type="notify", params={"message": MSG}),
        ],
    )


def _ocr_hit(m) -> None:
    """OCR 命中：偵測條件成立。"""
    m._ocr_region = lambda img, roi: [OcrResult(text=TARGET, x=0, y=0, w=10, h=10, confidence=0.9)]


def _ocr_miss(m) -> None:
    """OCR 未命中：偵測條件不成立。"""
    m._ocr_region = lambda img, roi: []


def _run(m, rule):
    """跑一次規則（每次呼叫都是新的 StepContext，等同新一幀的評估）。"""
    return m._run_rule(rule, IMG, RECT)


# ── 1. 條件首次成立時正常通知 ───────────────────────────────────────────


def test_first_match_notifies(ml):
    notifications: list[str] = []
    ml.on_warning = notifications.append
    rule = _notify_rule()
    _ocr_hit(ml)

    _run(ml, rule)

    assert notifications == [MSG], "條件首次成立必須送出通知"
    assert rule.id in ml._notified_conditions, "通知後必須上膛去重鎖存"


# ── 2. 條件持續成立時不重複通知 ─────────────────────────────────────────


def test_persistent_condition_notifies_only_once(ml):
    notifications: list[str] = []
    ml.on_warning = notifications.append
    rule = _notify_rule()
    _ocr_hit(ml)

    for _ in range(5):
        _run(ml, rule)

    assert notifications == [MSG], "條件持續成立時不得重複通知"


# ── 3. 條件解除後再次成立時可以重新通知 ───────────────────────────────


def test_condition_released_then_matched_again_notifies(ml):
    notifications: list[str] = []
    ml.on_warning = notifications.append
    rule = _notify_rule()

    _ocr_hit(ml)
    _run(ml, rule)
    assert notifications == [MSG]

    # 條件解除（偵測失敗）→ 重新武裝
    _ocr_miss(ml)
    _run(ml, rule)
    assert notifications == [MSG], "條件不成立時不得通知"
    assert rule.id not in ml._notified_conditions, "條件解除後鎖存必須失效（重新武裝）"

    # 條件再次成立 → 再次通知
    _ocr_hit(ml)
    _run(ml, rule)
    assert notifications == [MSG, MSG], "條件再次成立時必須可以重新通知"


# ── 4. Global Stop 發生時，去重狀態不會污染下一次啟動 ─────────────────


def test_stop_then_restart_notifies_again(ml):
    """停止前已通知 → 重新啟動後第一次命中原條件必須可以再通知。"""
    notifications: list[str] = []
    ml.on_warning = notifications.append
    rule = _notify_rule()
    _ocr_hit(ml)

    ml.start()
    _run(ml, rule)
    assert notifications == [MSG]
    assert rule.id in ml._notified_conditions

    ml.stop()
    # 停止本身不負責清除（清除屬於「觀察期邊界」），但下一個觀察期不得沿用
    assert rule.id in ml._notified_conditions

    ml.start()
    assert ml._notified_conditions == set(), "啟動必須清除通知去重鎖存（新的觀察期）"

    _run(ml, rule)
    assert notifications == [MSG, MSG], "重新啟動後第一次命中原條件必須可以正常通知"


def test_stop_during_detect_failure_rearms_latch(ml):
    """停止發生在偵測失敗之後時，重新武裝仍必須執行。

    位置約束：`_run_rule` 的重新武裝（discard）必須排在「步驟後的全域停止閘」
    之前，否則停止當下條件不成立會留下失效鎖存並抑制後續的首次命中。
    """
    notifications: list[str] = []
    ml.on_warning = notifications.append
    rule = _notify_rule()

    _ocr_hit(ml)
    _run(ml, rule)
    assert rule.id in ml._notified_conditions

    # OCR 期間觸發全域停止，且條件不成立
    def _ocr_stop_and_miss(img, roi):
        ml._stop_event.set()
        return []

    ml._ocr_region = _ocr_stop_and_miss
    _run(ml, rule)

    assert rule.id not in ml._notified_conditions, "偵測失敗時的重新武裝不得被停止閘跳過"
    assert notifications == [MSG], "停止不得送出額外通知"


# ── 5. 規則移除／任務切換不會留下不合理的通知狀態 ─────────────────────


def test_reload_rules_clears_notification_latch(tmp_path, ml):
    """規則重載（GUI 存檔路徑）＝新的觀察期：舊鎖存不得抑制首次命中。"""
    notifications: list[str] = []
    ml.on_warning = notifications.append
    rule = _notify_rule()

    _ocr_hit(ml)
    _run(ml, rule)
    assert notifications == [MSG]
    assert rule.id in ml._notified_conditions

    # 寫入真實檔案後 reload（規則從磁碟重建為新物件）
    path = tmp_path / "task.json"
    group = RuleGroup(
        id="g1", name="g1", rule_ids=[rule.id], order="sequential", enabled=True, mode="loop"
    )
    assert _ser_mod.save_task_with_groups([rule], [group], str(path)) is True
    ml._rules_path = str(path)
    ml._load_rules()

    assert ml._notified_conditions == set(), "規則重載必須清除通知去重鎖存"

    reloaded = ml._rule_map[rule.id]
    _run(ml, reloaded)
    assert notifications == [MSG, MSG], "重載後同一條件再次成立必須可以再通知"


def test_removed_rule_leaves_no_latch_after_reload(tmp_path, ml):
    """已被移除的規則不得留下鎖存；同 id 重新加入後仍可正常通知。"""
    notifications: list[str] = []
    ml.on_warning = notifications.append
    rule = _notify_rule()

    _ocr_hit(ml)
    _run(ml, rule)
    assert rule.id in ml._notified_conditions

    # 重載後規則清單不含該規則（模擬使用者刪除規則）
    path = tmp_path / "task.json"
    assert _ser_mod.save_task_with_groups([], [], str(path)) is True
    ml._rules_path = str(path)
    ml._load_rules()

    assert ml._notified_conditions == set(), "已移除的規則不得留下通知鎖存"

    # 同 id 重新加入 → 必須可以正常通知
    assert _ser_mod.save_task_with_groups([rule], [], str(path)) is True
    ml._load_rules()
    _run(ml, ml._rule_map[rule.id])
    assert notifications == [MSG, MSG], "同 id 重新加入的規則必須可以正常通知"


# ── 6. 重複 start / stop 不造成狀態異常 ───────────────────────────────


def test_repeated_start_stop_keeps_state_consistent(ml):
    notifications: list[str] = []
    ml.on_warning = notifications.append
    rule = _notify_rule()
    _ocr_hit(ml)

    ml.start()
    ml.start()  # 重複 start：不得拋例外、不得重複啟動真實擷取執行緒
    _run(ml, rule)
    assert notifications == [MSG]

    ml.stop()
    ml.stop()  # 重複 stop：不得拋例外
    assert ml._stop_event.is_set()

    ml.start()
    assert not ml._stop_event.is_set(), "start() 必須清除停止旗標"
    assert ml._notified_conditions == set(), "start() 必須清除通知去重鎖存"

    _run(ml, rule)
    assert notifications == [MSG, MSG], "重新啟動後第一次命中必須可以正常通知"
