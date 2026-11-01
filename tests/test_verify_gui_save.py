"""Phase 2-4b-3：Step Editor 的 Verify GUI 保存路徑自動化測試。

背景
----
`_VerifyWidget`（`gui/06_gui_main.py:2358`）是 click / drag / scroll / key 四種
Step 的「動作後驗證」編輯器。它是主 Step form 的 Qt 子 widget，其 `save()`
（`:3149`）把 GUI 欄位寫回 `Step.params["verify"]`。

Phase 2-4b-2b 的唯讀診斷已確認產品程式碼沒有資料完整性缺陷，但也確認
「Step Editor 的 Verify GUI 保存路徑」在整個測試套件中**零覆蓋**：
既有 verify 相關測試只涵蓋 `core/rule_migration._normalize_verify`（純資料）、
`core/05_main_loop` 的執行期 verify，以及 OCR Debug 面板的 verify worker
（另一個功能）。

本檔補上這一層覆蓋：真實 MainWindow + 真實 `_VerifyWidget` + 真實磁碟 JSON，
並在每一項測試中同時檢查 GUI 欄位、`Step.params["verify"]` 與落盤 JSON。

本檔只新增測試，不修改任何產品程式碼或既有測試檔。
"""

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from PyQt6.QtCore import QMetaObject, Qt  # noqa: E402

# verify 僅支援這四種「動作型」Step（core/rule_migration.py:290）
VERIFY_STEP_TYPES = ("click", "drag", "scroll", "key")


# ── 輔助 ───────────────────────────────────────────────────────────────────


def _base_verify(text: str = "原始文字") -> dict:
    """一個合法（可通過 rule_migration 正規化）的 detect 型 verify 設定。"""
    return {
        "type": "detect",
        "text": text,
        "preset": "medium",
        "expect": "present",
        "timeout_ms": 5000,
        "poll_interval_ms": 300,
        "delay_before_ms": 0,
        "retries": 1,
        "retry_delay_ms": 500,
        "on_fail": {"action": "advance"},
    }


def _task_file(isolated_data_dir, name: str) -> Path:
    return isolated_data_dir / "tasks" / f"{name}.json"


def _disk_verify(isolated_data_dir, name: str = "t1", rule_index: int = 0, step_index: int = 0):
    """從磁碟讀回該 step 的 verify 設定（真的落盤，不是記憶體物件）。"""
    data = json.loads(_task_file(isolated_data_dir, name).read_text(encoding="utf-8"))
    return data["rules"][rule_index]["steps"][step_index]["params"].get("verify")


def _memory_verify(win, rule_index: int = 0, step_index: int = 0):
    """記憶體中該 step 的 verify 設定。"""
    return win._rules[rule_index].steps[step_index].params.get("verify")


def _open_form(win, index: int = 0):
    """展開目前選中規則的第 index 個 step 表單（走真實展開流程）。"""
    win._step_list._collapse()
    win._step_list._toggle_expand(index)
    form = win._step_list._expanded_form
    assert form is not None, "表單必須成功展開"
    return form


def _rule_item(win, rule_id: str):
    """在規則樹中找到指定 rule_id 的 item（規則樹以 UserRole 存 ("rule", id)）。"""
    root = win._rule_list.invisibleRootItem()
    for i in range(root.childCount()):
        top = root.child(i)
        for j in range(top.childCount()):
            child = top.child(j)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "rule" and data[1] == rule_id:
                return child
    return None


def _load_task(win, write_task, make_rule, name: str, rules) -> None:
    """建立任務檔並載入（載入後 GUI 已選中第一條規則並顯示其 steps）。"""
    write_task(name, rules)
    win._on_task_changed(name)


def _click_step(make_step, text: str = "原始文字"):
    return make_step("click", verify=_base_verify(text))


# ── A. 四種 Step 類型的 Verify 基本保存 ─────────────────────────────────────


@pytest.mark.parametrize("step_type", VERIFY_STEP_TYPES)
def test_verify_widget_writes_full_schema_for_each_step_type(
    real_mainwindow, write_task, make_step, make_rule, step_type
):
    """四種動作 Step 的 Verify 表單都必須把 GUI 值完整寫回 Step.params["verify"]。"""
    win = real_mainwindow
    step = make_step(step_type, verify=_base_verify("原始文字"))
    _load_task(win, write_task, make_rule, "t1", [make_rule("r0", "規則零", [step])])

    form = _open_form(win, 0)
    verify = form._verify
    verify._enable.setChecked(True)
    verify._text.setText("編輯後文字")
    verify._preset.setCurrentIndex(verify._preset.findData("long"))
    verify._expect.setCurrentIndex(verify._expect.findData("absent"))
    verify._timeout.setValue(1234)
    verify._retries.setValue(2)

    win._flush_save()

    saved = _memory_verify(win)
    assert saved is not None, "verify 必須被寫回 params"
    assert saved["type"] == "detect"
    assert saved["text"] == "編輯後文字"
    assert saved["preset"] == "long"
    assert saved["expect"] == "absent"
    assert saved["timeout_ms"] == 1234
    assert saved["retries"] == 2
    assert saved["match_mode"] == "fuzzy"
    assert saved["fuzzy_threshold"] == 0.8
    assert saved["on_fail"] == {"action": "advance"}


@pytest.mark.parametrize("step_type", VERIFY_STEP_TYPES)
def test_verify_disabled_removes_verify_from_params(
    real_mainwindow, write_task, make_step, make_rule, step_type
):
    """關閉「動作後驗證」時，verify 必須從 params 移除（不是留空殼）。"""
    win = real_mainwindow
    step = make_step(step_type, verify=_base_verify("原始文字"))
    _load_task(win, write_task, make_rule, "t1", [make_rule("r0", "規則零", [step])])

    form = _open_form(win, 0)
    assert form._verify._enable.isChecked(), "前提：載入後 verify 為啟用狀態"
    form._verify._enable.setChecked(False)

    win._flush_save()

    assert "verify" not in win._rules[0].steps[0].params, "關閉後 params 不得殘留 verify"


# ── B. Verify 編輯後切換 Step ──────────────────────────────────────────────


def test_verify_edit_survives_step_switch(real_mainwindow, write_task, make_step, make_rule):
    """切到其他 step 再切回來，Verify 編輯值必須仍在（GUI 回填 + params）。"""
    win = real_mainwindow
    _load_task(
        win,
        write_task,
        make_rule,
        "t1",
        [make_rule("r0", "規則零", [_click_step(make_step), make_step("wait", ms=300)])],
    )

    form = _open_form(win, 0)
    form._verify._text.setText("切換 Step 前的編輯值")

    win._step_list._toggle_expand(1)
    assert win._step_list._expanded_idx == 1, "必須切到第二個 step"

    win._step_list._toggle_expand(0)
    assert win._step_list._expanded_idx == 0, "必須切回第一個 step"

    form = win._step_list._expanded_form
    assert form._verify._text.text() == "切換 Step 前的編輯值", "切回後 GUI 必須回填編輯值"
    assert _memory_verify(win)["text"] == "切換 Step 前的編輯值", "params 必須保留編輯值"


# ── C. Verify 編輯後切換 Rule ──────────────────────────────────────────────


def test_verify_edit_survives_rule_switch(real_mainwindow, write_task, make_step, make_rule):
    """切到另一條規則再切回來，Verify 值必須完整保留，且不污染另一條規則。"""
    win = real_mainwindow
    _load_task(
        win,
        write_task,
        make_rule,
        "t1",
        [
            make_rule("r0", "規則零", [_click_step(make_step)]),
            make_rule("r1", "規則壹", [make_step("wait", ms=300)]),
        ],
    )

    form = _open_form(win, 0)
    form._verify._text.setText("切換 Rule 前的編輯值")

    item = _rule_item(win, "r1")
    assert item is not None, "規則樹中必須找得到 r1"
    win._rule_list.setCurrentItem(item)
    assert win._selected_rule_id == "r1", "必須已切到 r1"

    assert _memory_verify(win, rule_index=0)["text"] == "切換 Rule 前的編輯值", "r0 的值必須保留"
    assert "verify" not in win._rules[1].steps[0].params, "r1 不得被污染"

    win._rule_list.setCurrentItem(_rule_item(win, "r0"))
    assert win._selected_rule_id == "r0", "必須已切回 r0"

    form = _open_form(win, 0)
    assert form._verify._text.text() == "切換 Rule 前的編輯值", "切回後 GUI 必須回填編輯值"


# ── D. Verify 編輯後切換任務 ──────────────────────────────────────────────


def test_verify_edit_survives_task_switch(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """切到另一個任務再切回來，任務 A 的 Verify 必須完整保留，任務 B 不得受污染。"""
    win = real_mainwindow
    _load_task(
        win, write_task, make_rule, "taskA", [make_rule("r0", "規則零", [_click_step(make_step)])]
    )
    _load_task(
        win,
        write_task,
        make_rule,
        "taskB",
        [make_rule("b0", "B 規則", [make_step("wait", ms=100)])],
    )
    win._on_task_changed("taskA")

    form = _open_form(win, 0)
    form._verify._text.setText("切換任務前的編輯值")

    win._on_task_changed("taskB")
    assert win._current_task == "taskB", "必須已切到 taskB"
    assert _disk_verify(isolated_data_dir, "taskB") is None, "taskB 不得出現 verify"

    win._on_task_changed("taskA")
    assert win._current_task == "taskA", "必須已切回 taskA"
    disk = _disk_verify(isolated_data_dir, "taskA")
    assert disk is not None, "taskA 的 verify 必須仍在磁碟上"
    assert disk["text"] == "切換任務前的編輯值"


# ── E. 手動保存與 JSON round-trip ──────────────────────────────────────────


def test_verify_value_survives_flush_save_and_reload(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """_flush_save() → 磁碟 JSON → 重新載入 → GUI 回填，Verify 值全程一致。"""
    win = real_mainwindow
    _load_task(
        win, write_task, make_rule, "t1", [make_rule("r0", "規則零", [_click_step(make_step)])]
    )

    form = _open_form(win, 0)
    form._verify._text.setText("保存後的新文字")
    form._verify._preset.setCurrentIndex(form._verify._preset.findData("short"))
    form._verify._expect.setCurrentIndex(form._verify._expect.findData("absent"))

    win._flush_save()

    disk = _disk_verify(isolated_data_dir, "t1")
    assert disk is not None, "verify 必須已落盤"
    assert disk["text"] == "保存後的新文字"
    assert disk["preset"] == "short"
    assert disk["expect"] == "absent"

    # 重新載入任務 → GUI 回填
    win._on_task_changed("t1")
    form = _open_form(win, 0)
    assert form._verify._text.text() == "保存後的新文字", "重新載入後 GUI 必須回填"
    assert form._verify._preset.currentData() == "short"
    assert form._verify._expect.currentData() == "absent"


# ── F. 自動保存路徑 ────────────────────────────────────────────────────────


def test_verify_value_persisted_by_debounce_save(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """自動保存（debounce timer）路徑也必須把 Verify 值寫進磁碟。

    以真實排程入口 `_schedule_save()` 啟動 timer，再用 Qt 的 signal 機制
    直接發出 `timeout`（等同 timer 到期），避免 sleep 造成的不穩定等待。
    """
    win = real_mainwindow
    _load_task(
        win, write_task, make_rule, "t1", [make_rule("r0", "規則零", [_click_step(make_step)])]
    )

    form = _open_form(win, 0)
    form._verify._text.setText("自動保存的新文字")

    win._schedule_save()
    assert win._save_timer.isActive(), "前提：debounce timer 已排程"
    try:
        # 發出 timer 的 timeout signal → 觸發 _do_debounced_save（不 sleep）
        QMetaObject.invokeMethod(win._save_timer, "timeout")
    finally:
        win._save_timer.stop()

    disk = _disk_verify(isolated_data_dir, "t1")
    assert disk is not None, "verify 必須已落盤"
    assert disk["text"] == "自動保存的新文字", "debounce save 必須保存 Verify 值"


# ── G. 非 GUI 管理欄位的保留（Phase 2-6 回歸：Phase 2-5 診斷 D1 / D2）────────
#
# Phase 2-5 唯讀診斷確認：`_VerifyWidget.save()`（gui/06_gui_main.py:3149）
# 以白名單「整份重建」verify dict，會刪掉 GUI 沒有編輯介面的欄位：
#   D1：`capture_size`（範本擷取當下的客戶區尺寸）→ 跨解析度比對失去依據
#   D2：legacy `template` 檔案路徑 → 重載時 verify 被整個移除
# 這裡以真實 GUI 流程（載入 → 展開 → _flush_save → 讀磁碟 → 重載）做回歸。


def _image_verify(**extra) -> dict:
    """match_image 型 Verify 的基底設定（GUI 沒有編輯介面的欄位由 extra 帶入）。"""
    v = {
        "type": "match_image",
        "preset": "medium",
        "expect": "present",
        "roi": {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0},
        "timeout_ms": 5000,
        "poll_interval_ms": 300,
        "delay_before_ms": 0,
        "retries": 1,
        "retry_delay_ms": 500,
        "on_fail": {"action": "advance"},
        "threshold": 0.8,
    }
    v.update(extra)
    return v


def test_verify_capture_size_survives_gui_save(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """D1 回歸：Verify 範本的 capture_size 不得在 GUI 存檔後遺失。

    capture_size 是「擷取當下客戶區尺寸」，Core 以它對 current_size 換算縮放；
    一旦遺失就會退回任務級 capture_size，跨解析度時比對結果不準。
    """
    win = real_mainwindow
    verify = _image_verify(template_data="QUJD", capture_size=[1920, 1080])
    step = make_step("click", verify=verify)
    _load_task(win, write_task, make_rule, "t1", [make_rule("r0", "規則零", [step])])

    form = _open_form(win, 0)
    # 同時驗證 GUI 管理的欄位仍可被正常改寫（不得因保留而變成唯讀）
    form._verify._timeout.setValue(1234)

    win._flush_save()

    disk = _disk_verify(isolated_data_dir, "t1")
    assert disk is not None, "verify 必須已落盤"
    assert list(disk.get("capture_size") or []) == [1920, 1080], (
        f"capture_size 不得在 GUI 存檔後遺失：{disk.get('capture_size')!r}"
    )
    assert disk["timeout_ms"] == 1234, "GUI 管理的欄位仍必須正常更新"

    # 重新載入 → capture_size 仍完整保留
    win._on_task_changed("t1")
    reloaded = _memory_verify(win)
    assert reloaded is not None, "重載後 verify 不得消失"
    assert list(reloaded.get("capture_size") or []) == [1920, 1080], "重載後 capture_size 必須保留"


def test_verify_legacy_template_path_survives_gui_save(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """D2 回歸：legacy `template` 檔案路徑不得在 GUI 存檔後被刪除。

    只留 template 路徑（無 template_data）時，一旦路徑被刪，
    正規化會判定 verify 無效而整個移除 → 使用者的後置條件靜默消失。
    """
    win = real_mainwindow
    verify = _image_verify(template="C:/legacy/tpl.png")
    step = make_step("click", verify=verify)
    _load_task(win, write_task, make_rule, "t1", [make_rule("r0", "規則零", [step])])

    form = _open_form(win, 0)
    form._verify._timeout.setValue(1234)

    win._flush_save()

    disk = _disk_verify(isolated_data_dir, "t1")
    assert disk is not None, "verify 必須已落盤"
    assert disk.get("template") == "C:/legacy/tpl.png", (
        f"legacy template 路徑不得被刪除：{disk.get('template')!r}"
    )
    assert disk["timeout_ms"] == 1234, "GUI 管理的欄位仍必須正常更新"

    # 重新載入 → verify 不得被整個移除
    win._on_task_changed("t1")
    reloaded = _memory_verify(win)
    assert reloaded is not None, "legacy verify 不得在重載後被整個移除"
    assert reloaded.get("template") == "C:/legacy/tpl.png", "重載後 legacy template 必須保留"


@pytest.mark.parametrize("step_type", VERIFY_STEP_TYPES)
def test_verify_non_managed_fields_preserved_for_all_action_types(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir, step_type
):
    """同一根因的通用不變量：GUI 沒編輯介面的欄位，四種動作型 Step 都必須保留。

    click / drag / scroll / key 四種 Step 共用同一個 `_VerifyWidget`，而它的
    `save()` 是唯一把 verify 寫回 Step.params 的地方；這裡逐一以四種 Step
    走完整 GUI 保存流程（載入 → 展開 → _flush_save → 讀磁碟 JSON），
    確認 capture_size / match_color / color_tolerance 不會被整份重建吃掉，
    且 verify 型別本身未被改寫。
    """
    win = real_mainwindow
    verify = _image_verify(
        template_data="QUJD",
        capture_size=[1616, 939],
        match_color=True,
        color_tolerance=77,
    )
    step = make_step(step_type, verify=verify)
    _load_task(win, write_task, make_rule, "t1", [make_rule("r0", "規則零", [step])])

    _open_form(win, 0)
    win._flush_save()

    disk = _disk_verify(isolated_data_dir, "t1")
    assert disk is not None
    assert disk["type"] == "match_image", "verify 型別不得被保存流程改寫"
    assert list(disk.get("capture_size") or []) == [1616, 939]
    assert disk.get("match_color") is True
    assert disk.get("color_tolerance") == 77
