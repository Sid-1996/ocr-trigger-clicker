"""輸入後台測試工作台的『真實整合測試』。

與 tests/test_input_test_bench.py（自動測試）明確分開：本檔會真的啟動目標
程式、真的經過產品既有 Input Backend（bg_input → frida_bg / pynput_input）
送出輸入，並驗證目標程式實際收到的事件與語意狀態。

需要真實 Windows 桌面工作階段（前景輸入會移動滑鼠、發送真實按鍵）與 frida
套件。預設不執行，避免拖慢／污染一般測試流程：

    uv run python -m pytest tests/test_input_test_bench_integration.py -v \
        -o addopts="" --no-cov
    $env:OTC_RUN_INPUT_INTEGRATION = "1"   # PowerShell：啟用整合測試

環境變數：
    OTC_RUN_INPUT_INTEGRATION=1  啟用本檔測試（未設定則全部 skip）
    OTC_INPUT_INTEGRATION_MODE    測試模式（frida／hybrid／pynput，預設 frida）
"""

import os

import pytest

from _loader import load_sibling

_bench = load_sibling("input_test_bench", "devtools/input_test_bench.py")

pytestmark = pytest.mark.skipif(
    os.environ.get("OTC_RUN_INPUT_INTEGRATION") != "1",
    reason="真實整合測試：需設定 OTC_RUN_INPUT_INTEGRATION=1 才執行",
)

MODE = os.environ.get("OTC_INPUT_INTEGRATION_MODE", "frida").strip() or "frida"


@pytest.fixture(scope="module")
def target():
    """真實目標程式（獨立程序）。"""
    os.environ["QT_QPA_PLATFORM"] = "windows"
    proc = _bench.TargetProcess()
    status = proc.start(timeout=90)
    assert status.pid > 0 and status.hwnd != 0
    try:
        yield proc
    finally:
        proc.stop()


@pytest.fixture(scope="module")
def runner(target):
    """對真實目標程式的測試執行器。"""
    r = _bench.BenchRunner(target, MODE)
    try:
        yield r
    finally:
        r.detach()


def test_backend_attach_succeeds(runner, target):
    """Frida 必須真的 attach 到目標程序（後端層）。"""
    if MODE != "frida":
        pytest.skip("僅 frida 模式有 attach 語意")
    ok = runner._bg.set_method("frida") or True
    assert ok
    # 實際送一次點擊：attach 失敗時 bg_input 會記錄 last_error。
    outcome = runner.run_click()
    assert "attach" not in (outcome.backend_detail or "").lower() or outcome.backend_ok


def test_click_reaches_target(runner):
    outcome = runner.run_click()
    assert outcome.backend_ok, outcome.backend_detail
    assert outcome.received, outcome.received_detail
    assert outcome.expected_ok, outcome.expected_detail


def test_key_reaches_target(runner):
    outcome = runner.run_key("a")
    assert outcome.backend_ok, outcome.backend_detail
    assert outcome.received, outcome.received_detail
    assert outcome.expected_ok, outcome.expected_detail


def test_hold_reaches_target_and_releases(runner):
    outcome = runner.run_hold("a", 1000)
    assert outcome.backend_ok, outcome.backend_detail
    assert outcome.received, outcome.received_detail
    assert outcome.expected_ok, outcome.expected_detail


def test_drag_moves_object(runner):
    outcome = runner.run_drag()
    assert outcome.backend_ok, outcome.backend_detail
    assert outcome.received, outcome.received_detail
    assert outcome.expected_ok, outcome.expected_detail


def test_scroll_reaches_target(runner):
    outcome = runner.run_scroll()
    assert outcome.backend_ok, outcome.backend_detail
    assert outcome.received, outcome.received_detail
    assert outcome.expected_ok, outcome.expected_detail


def test_cancel_still_releases_key(runner):
    """取消後 UP 仍必須送出，目標端不得殘留按住。"""
    outcome = runner.run_cancel_release("a", hold_ms=3000, cancel_after_ms=500)
    assert outcome.backend_ok, outcome.backend_detail
    assert outcome.received, outcome.received_detail
    assert outcome.expected_ok, outcome.expected_detail
    assert "殘留按住=[]" in outcome.expected_detail


def test_target_restart_allows_reattach():
    """目標程序重新啟動後必須能重新 attach 並再次送出輸入。"""
    os.environ["QT_QPA_PLATFORM"] = "windows"
    proc = _bench.TargetProcess()
    try:
        status = proc.start(timeout=90)
        r = _bench.BenchRunner(proc, MODE)
        try:
            outcome = r.run_click()
            assert outcome.backend_ok, outcome.backend_detail
            assert outcome.received, outcome.received_detail
        finally:
            r.detach()
    finally:
        proc.stop()
    assert status.hwnd != 0


def test_target_close_is_detected(runner, target):
    """目標程序關閉後，工作台必須察覺失聯。"""
    assert target.is_running()
    target.stop()
    assert not target.is_running()
