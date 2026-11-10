"""UX3-02（C-2a-2）：舊版 Drag 資料的 GUI 修復流程。

背景
----
舊任務的 Drag 終點是像素偏移（dx/dy）。載入時 core 會標 `_migration`
{kind=drag_endpoint, status=needs_repair}；執行期只認 end_x/end_y
（core/05_main_loop.py 的 resolve_drag_end），所以這條規則執行時不會拖曳成功。
GUI 原本對 _migration／validate_drag_endpoint 零消費端：沒有提示、沒有修復入口，
使用者只能手改 JSON 或重建規則。

本檔鎖住：
- 判定一律以 core validate_drag_endpoint 為唯一來源（GUI 不自寫第三套狀態機）
- 舊版 Drag 開啟表單即出現修復 banner；未修復前儲存不得改壞原始資料
- 修復流程：拾取終點 → 使用者確認 → 才移除 dx/dy 與 marker → 儲存 → reload 為 valid
- 資料不足（沒有有效終點）或使用者取消 → 一律保留原資料
- 正常新版 Drag 不受影響（不出 banner、不產生 dx/dy）
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402
from core.rule_models import Rule, Step  # noqa: E402

_GUI = load_sibling("gui_main", "gui/06_gui_main.py")
_MIG = load_sibling("rule_migration", "core/rule_migration.py")
_SER = load_sibling("rule_serialization", "core/rule_serialization.py")
_T = _GUI.T


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def step_list(qapp):
    lst = _GUI._StepListWidget()
    lst.set_rules_provider(lambda: [])
    lst.set_groups_provider(lambda: [])
    lst.set_rule_id("r1")
    yield lst
    lst.deleteLater()
    qapp.processEvents()


def _picker(value=(0.5, 0.6)):
    """假 picker：回傳客戶區比例座標（與 _on_pick_coord 回傳形狀相同）。"""

    return lambda: value


def _build(step_list, step, pick=None):
    if pick is not None:
        step_list.set_click_pick_callback(pick)
    form = step_list._build_form(0, step)
    assert form is not None
    return form


def _legacy_step(**over):
    params = {"target": "custom", "x": 0.2, "y": 0.3, "dx": 30, "dy": 20}
    params.update(over)
    return Step(type="drag", params=params)


def _new_step(**over):
    params = {
        "target": "custom",
        "x": 0.2,
        "y": 0.3,
        "end_x": 0.5,
        "end_y": 0.6,
        "end_roi_coord": "client",
    }
    params.update(over)
    return Step(type="drag", params=params)


def _roundtrip(step, tmp_path):
    """走產品自己的存檔／讀檔 API，讓資料真的落地再讀回來。"""
    path = tmp_path / "task.json"
    rule = Rule(id="r1", name="R1", enabled=True, steps=[step])
    assert _SER.save_rules([rule], str(path)) is True
    return _SER.load_rules(str(path))[0].steps[0].params


# ── 1：正常新版 Drag 載入／編輯／儲存 ───────────────────────────────────────


def test_new_endpoint_drag_has_no_banner(step_list, qapp):
    step = _new_step()
    form = _build(step_list, step)
    try:
        assert form._repair_banner is None
        assert form._repair["status"] == "valid"
        # 舊格式欄位不顯示 → 使用者不會誤填出 dx/dy
        assert form._legacy_row_widgets == []
        assert form.save() is True
        assert "dx" not in step.params and "dy" not in step.params
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_new_endpoint_drag_edit_still_works(step_list, qapp):
    """既有新版 Drag 編輯不受影響：改終點 → 儲存寫入 end_x/end_y。"""
    step = _new_step()
    form = _build(step_list, step)
    try:
        form._end_x_spin.setValue(0.42)
        form._end_y_spin.setValue(0.43)
        assert form.save() is True
        assert step.params["end_x"] == 0.42
        assert step.params["end_y"] == 0.43
        assert "dx" not in step.params and "dy" not in step.params
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_new_endpoint_drag_roundtrip_stays_valid(step_list, qapp, tmp_path):
    step = _new_step()
    form = _build(step_list, step)
    try:
        assert form.save() is True
    finally:
        form.deleteLater()
        qapp.processEvents()
    params = _roundtrip(step, tmp_path)
    assert "_migration" not in params
    assert _MIG.validate_drag_endpoint(params)["status"] == "valid"


# ── 2：舊版 Drag 載入與辨識 ────────────────────────────────────────────────


def test_legacy_drag_shows_repair_banner(step_list, qapp):
    step = _legacy_step()
    form = _build(step_list, step)
    try:
        assert form._repair_banner is not None
        assert form._repair["status"] == "needs_repair"
        assert form._repair["reason"] == "legacy_px_offset"
        # 舊欄位唯讀：使用者不可再改出「不生效」的 dx/dy
        assert form._dx.isEnabled() is False
        assert form._dy.isEnabled() is False
        assert len(form._legacy_row_widgets) == 4
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_new_step_never_shows_banner(step_list, qapp):
    """banner 只出現在需要修復的 Drag，其他步驟／其他規則不會出現。"""
    step = _new_step()
    form = _build(step_list, step)
    try:
        assert form._repair_banner is None
    finally:
        form.deleteLater()
        qapp.processEvents()


# ── 3：未修復前的儲存行為 ──────────────────────────────────────────────────


def test_legacy_save_before_repair_keeps_original_data(step_list, qapp, tmp_path):
    step = _legacy_step()
    form = _build(step_list, step)
    try:
        assert form.save() is True
    finally:
        form.deleteLater()
        qapp.processEvents()
    assert step.params["dx"] == 30 and step.params["dy"] == 20
    params = _roundtrip(step, tmp_path)
    assert params["dx"] == 30 and params["dy"] == 20
    assert params["_migration"]["reason"] == "legacy_px_offset"
    assert _MIG.validate_drag_endpoint(params)["status"] == "needs_repair"


def test_legacy_float_offset_not_truncated(step_list, qapp):
    """未編輯的舊偏移必須原樣保留：QSpinBox 只顯示整數，不可覆寫原值。"""
    step = _legacy_step(dx=10.5, dy=20.25)
    form = _build(step_list, step)
    try:
        assert form.save() is True
    finally:
        form.deleteLater()
        qapp.processEvents()
    assert step.params["dx"] == 10.5
    assert step.params["dy"] == 20.25


def test_legacy_save_keeps_none_pair_contract(step_list, qapp):
    """終點未設定 → 明確寫 None（既有資料契約），且舊的 dx/dy 原樣保留。"""
    step = _legacy_step()
    form = _build(step_list, step)
    try:
        assert form.save() is True
    finally:
        form.deleteLater()
        qapp.processEvents()
    assert step.params["end_x"] is None
    assert step.params["end_y"] is None
    assert step.params["dx"] == 30 and step.params["dy"] == 20


# ── 4：修復成功後的資料完整性 ──────────────────────────────────────────────


def test_repair_pick_then_confirm_clears_legacy(step_list, qapp, tmp_path, monkeypatch):
    step = _legacy_step()
    form = _build(step_list, step, pick=_picker((0.52, 0.61)))
    try:
        assert form._repair_banner is not None
        form._repair_pick_btn.click()
        # 拾取後：新的終點座標寫入，舊資料仍在（未確認不得清除）
        assert step.params["end_x"] == 0.52
        assert step.params["end_y"] == 0.61
        assert step.params["end_roi_coord"] == "client"
        assert step.params["dx"] == 30 and step.params["dy"] == 20
        assert form._repair["status"] == "needs_repair"
        assert form._repair["reason"] == "mixed_legacy_and_endpoint"

        monkeypatch.setattr(
            _GUI.QMessageBox,
            "question",
            staticmethod(lambda *a, **k: _GUI.QMessageBox.StandardButton.Yes),
        )
        form._repair_clear_btn.click()
        assert "dx" not in step.params
        assert "dy" not in step.params
        assert "_migration" not in step.params
        assert step.params["end_x"] == 0.52
        assert step.params["end_y"] == 0.61
        assert form._repair["status"] == "valid"
        assert form._repair_banner.isVisibleTo(form) is False
    finally:
        form.deleteLater()
        qapp.processEvents()

    # reload 重檢：不再需要修復
    params = _roundtrip(step, tmp_path)
    assert "_migration" not in params
    assert params["end_x"] == 0.52 and params["end_y"] == 0.61
    assert _MIG.validate_drag_endpoint(params)["status"] == "valid"


def test_repair_keeps_other_step_fields(step_list, qapp, monkeypatch):
    """修復不得動到其他欄位（起點／按鍵／延遲）。"""
    step = _legacy_step(button="right", after_delay_ms=250)
    form = _build(step_list, step, pick=_picker((0.52, 0.61)))
    try:
        form._repair_pick_btn.click()
        monkeypatch.setattr(
            _GUI.QMessageBox,
            "question",
            staticmethod(lambda *a, **k: _GUI.QMessageBox.StandardButton.Yes),
        )
        form._repair_clear_btn.click()
        assert step.params["target"] == "custom"
        assert step.params["x"] == 0.2 and step.params["y"] == 0.3
        assert step.params["button"] == "right"
        assert step.params["after_delay_ms"] == 250
    finally:
        form.deleteLater()
        qapp.processEvents()


# ── 5：修復失敗／資料不足時的回饋 ─────────────────────────────────────────


def test_clear_without_end_is_refused(step_list, qapp, monkeypatch):
    """終點尚未有效 → 不得移除舊資料，也不得跳出確認對話框。"""
    step = _legacy_step()
    form = _build(step_list, step)
    try:

        def _boom(*a, **k):
            raise AssertionError("終點未設定時不得跳出確認對話框")

        monkeypatch.setattr(_GUI.QMessageBox, "question", staticmethod(_boom))
        # UI 層：按鈕在沒有有效終點時就是 disabled
        assert form._repair_clear_btn.isEnabled() is False
        # 直接呼叫守門分支：同樣必須拒絕
        form._on_repair_clear()
        assert step.params["dx"] == 30 and step.params["dy"] == 20
        assert form._repair["status"] == "needs_repair"
        assert form._repair_body.text() == _T("step_form.drag_legacy_need_end")
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_clear_cancelled_keeps_original_data(step_list, qapp, monkeypatch):
    """使用者按「取消」→ 舊資料與 marker 一律保留。"""
    step = _legacy_step()
    form = _build(step_list, step, pick=_picker((0.52, 0.61)))
    try:
        form._repair_pick_btn.click()
        monkeypatch.setattr(
            _GUI.QMessageBox,
            "question",
            staticmethod(lambda *a, **k: _GUI.QMessageBox.StandardButton.No),
        )
        form._repair_clear_btn.click()
        assert step.params["dx"] == 30 and step.params["dy"] == 20
        assert form._repair["status"] == "needs_repair"
        assert form._repair_banner.isVisibleTo(form) is True
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_repair_pick_without_picker_is_noop(step_list, qapp):
    """沒有 picker（測試／離線情境）時按鈕不可用，不會靜默產生座標。"""
    step = _legacy_step()
    form = _build(step_list, step)
    try:
        assert form._repair_pick_btn.isEnabled() is False
        form._repair_pick_btn.click()
        assert "end_x" not in step.params
        assert step.params["dx"] == 30
    finally:
        form.deleteLater()
        qapp.processEvents()


# ── 6/7：邊界情況 ─────────────────────────────────────────────────────────


def test_legacy_missing_dy_shows_banner(step_list, qapp):
    step = Step(type="drag", params={"target": "custom", "x": 0.2, "y": 0.3, "dx": 30})
    form = _build(step_list, step)
    try:
        assert form._repair_banner is not None
        assert form._repair["reason"] == "incomplete_legacy_offset"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_legacy_invalid_offset_does_not_crash(step_list, qapp):
    """舊偏移是不合法值（字串）→ 表單不可崩潰，且必須提示需要修復。"""
    step = _legacy_step(dx="bad", dy=None)
    form = _build(step_list, step)
    try:
        assert form._repair_banner is not None
        assert form._repair["reason"] == "invalid_legacy_offset"
        assert form.save() is True
        # 不可改寫使用者原值（即使不合法）
        assert step.params["dx"] == "bad"
        assert step.params["dy"] is None
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_new_step_half_end_has_no_repair_banner(step_list, qapp):
    """新版半套終點是「尚未填完」，不是 legacy → 不出修復 banner。"""
    step = Step(type="drag", params={"target": "custom", "x": 0.2, "y": 0.3, "end_x": 0.5})
    form = _build(step_list, step)
    try:
        assert form._repair_banner is None
        assert form._repair["status"] == "incomplete"
    finally:
        form.deleteLater()
        qapp.processEvents()


def test_task_load_counts_legacy_drag_steps():
    """任務載入時提示需要修復的拖曳步驟數量（判定以 core 為準）。"""
    pushed = []
    fake = SimpleNamespace(
        _rules=[
            Rule(
                id="r1",
                name="R1",
                enabled=True,
                steps=[_legacy_step(), _new_step(), Step(type="wait", params={"ms": 100})],
            ),
            Rule(id="r2", name="R2", enabled=True, steps=[_legacy_step()]),
        ],
        _notif_stack=SimpleNamespace(push=pushed.append),
    )
    count = _GUI.MainWindow._notify_drag_legacy_steps(fake)
    assert count == 2
    assert len(pushed) == 1
    assert "2" in pushed[0]


def test_task_load_no_notice_without_legacy():
    pushed = []
    fake = SimpleNamespace(
        _rules=[Rule(id="r1", name="R1", enabled=True, steps=[_new_step()])],
        _notif_stack=SimpleNamespace(push=pushed.append),
    )
    assert _GUI.MainWindow._notify_drag_legacy_steps(fake) == 0
    assert pushed == []
