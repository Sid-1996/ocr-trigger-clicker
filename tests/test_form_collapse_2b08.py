"""UX 2B-08：Click 進階設定與 Verify 設定區塊預設收合。

驗證重點：收合只影響 UI 呈現；欄位照常載入既有值；展開/收合不改變
設定值、序列化結果（save() 輸出）或執行層取得的 params。
"""

import copy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from _loader import load_sibling  # noqa: E402

_gui = load_sibling("gui_main", "gui/06_gui_main.py")
Step = _gui.Step


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def step_list(qapp):
    lst = _gui._StepListWidget()
    lst.set_rules_provider(lambda: [])
    lst.set_groups_provider(lambda: [])
    lst.set_rule_id("r1")
    yield lst
    lst.deleteLater()
    qapp.processEvents()


def _verify_params(text="戰鬥"):
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
        "match_mode": "fuzzy",
        "fuzzy_threshold": 0.8,
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "on_fail": {"action": "advance"},
    }


def _click_params(with_verify=True):
    params = {
        "target": "custom",
        "x": 0.25,
        "y": 0.5,
        "button": "right",
        "random_offset": 7,
        "hold_ms": 120,
        "after_delay_ms": 250,
    }
    if with_verify:
        params["verify"] = _verify_params()
    return params


# ── A. Click 進階設定 ─────────────────────────────────────────────────


def test_click_advanced_collapsed_by_default_and_values_loaded(step_list, qapp):
    step = Step(type="click", params=_click_params())
    form = step_list._build_form(0, step)
    try:
        assert form._adv_expanded is False
        assert form._adv_container.isHidden()
        assert "▶" in form._adv_toggle_btn.text()
        # 收合時欄位已載入既有值
        assert form._button.currentData() == "right"
        assert form._offset.value() == 7
        assert form._hold_ms.value() == 120
        assert form._after_delay.value() == 250
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_click_advanced_toggle_does_not_change_values_or_save_output(step_list, qapp):
    step = Step(type="click", params=_click_params())
    form = step_list._build_form(0, step)
    try:
        # 收合狀態下儲存一次（執行層讀的即 step.params）
        form.save()
        collapsed_output = copy.deepcopy(step.params)

        form._adv_toggle_btn.click()
        assert not form._adv_container.isHidden()
        assert "▼" in form._adv_toggle_btn.text()
        assert form._button.currentData() == "right"
        assert form._offset.value() == 7
        assert form._hold_ms.value() == 120
        assert form._after_delay.value() == 250
        form.save()
        assert step.params == collapsed_output

        form._adv_toggle_btn.click()
        assert form._adv_container.isHidden()
        assert form._button.currentData() == "right"
        assert form._offset.value() == 7
        form.save()
        assert step.params == collapsed_output
    finally:
        form.deleteLater()
        qapp.processEvents()


# ── B. Verify 設定 ────────────────────────────────────────────────────


def test_verify_collapsed_by_default_even_when_enabled(step_list, qapp):
    step = Step(type="click", params=_click_params())
    form = step_list._build_form(0, step)
    try:
        verify = form._verify
        assert verify._enable.isChecked()
        assert verify._verify_expanded is False
        assert verify._container.isHidden()
        assert "▶" in verify._verify_toggle_btn.text()
        # 收合時欄位已載入既有值
        assert verify._text.text() == "戰鬥"
        assert verify._preset.currentData() == "medium"
        assert verify._timeout.value() == 5000
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_verify_toggle_does_not_change_values_or_save_output(step_list, qapp):
    step = Step(type="click", params=_click_params())
    form = step_list._build_form(0, step)
    try:
        verify = form._verify
        verify.save()
        collapsed_output = copy.deepcopy(step.params)

        verify._verify_toggle_btn.click()
        assert not verify._container.isHidden()
        assert "▼" in verify._verify_toggle_btn.text()
        assert verify._text.text() == "戰鬥"
        assert verify._timeout.value() == 5000
        verify.save()
        assert step.params == collapsed_output

        verify._verify_toggle_btn.click()
        assert verify._container.isHidden()
        assert verify._text.text() == "戰鬥"
        verify.save()
        assert step.params == collapsed_output
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_verify_without_setting_stays_collapsed_and_toggle_disabled(step_list, qapp):
    step = Step(type="click", params=_click_params(with_verify=False))
    form = step_list._build_form(0, step)
    try:
        verify = form._verify
        assert not verify._enable.isChecked()
        assert verify._container.isHidden()
        assert not verify._verify_toggle_btn.isEnabled()
        # 勾選啟用 → 自動展開（既有可發現性）
        verify._enable.setChecked(True)
        assert not verify._container.isHidden()
        # 取消勾選 → 收合且儲存後 verify 消失（既有行為）
        verify._enable.setChecked(False)
        assert verify._container.isHidden()
        verify.save()
        assert "verify" not in step.params
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_collapsed_save_preserves_disk_serialization(
    real_mainwindow, write_task, make_step, make_rule, isolated_data_dir
):
    """真實任務載入 → 表單收合 → 儲存落盤：verify 與 Click 進階值不遺失。"""
    step = make_step(
        "click",
        target="custom",
        x=0.25,
        y=0.5,
        button="right",
        random_offset=7,
        hold_ms=120,
        after_delay_ms=250,
        verify=_verify_params(),
    )
    write_task("t1", [make_rule("r0", "規則零", [step])])
    win = real_mainwindow
    win._on_task_changed("t1")

    win._step_list._collapse()
    win._step_list._toggle_expand(0)
    form = win._step_list._expanded_form
    assert form is not None
    assert form._adv_container.isHidden()
    assert form._verify._container.isHidden()
    assert form._verify._enable.isChecked()

    win._flush_save()

    data = json.loads((isolated_data_dir / "tasks" / "t1.json").read_text(encoding="utf-8"))
    params = data["rules"][0]["steps"][0]["params"]
    assert params["button"] == "right"
    assert params["random_offset"] == 7
    assert params["hold_ms"] == 120
    assert params["after_delay_ms"] == 250
    assert params["verify"]["text"] == "戰鬥"
    assert params["verify"]["timeout_ms"] == 5000
    assert params["verify"]["preset"] == "medium"
