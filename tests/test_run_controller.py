"""Dry Run 的 Preflight 行為：BLOCKED 規則必須明確顯示，不得假成功。

只測 BLOCKED 早退路徑（不會跑 OCR），不觸碰 Qt 視窗物件：
get_client_rect_for_image / get_window_client_offset 以 monkeypatch 換成純函式，
self 以 SimpleNamespace 替身取代（只需要 _win / _of_summary / _resolve_rule_name）。
"""

import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np  # noqa: E402

from _loader import load_sibling  # noqa: E402

_rc = load_sibling("run_controller", "gui/run_controller.py")
_models = load_sibling("rule_models", "core/rule_models.py")
Rule = _models.Rule
Step = _models.Step


class _FakeCombo:
    @staticmethod
    def currentText():
        return "dummy"


class _FakeWin:
    _window_combo = _FakeCombo()


def _fake_self():
    return SimpleNamespace(
        _win=_FakeWin(),
        _of_summary=lambda *a, **k: "",
        _resolve_rule_name=lambda r: getattr(r, "name", ""),
    )


def _blank_frame():
    return np.zeros((10, 10, 3), dtype=np.uint8)


def test_dry_run_blocked_rule_shows_blocked_not_success(monkeypatch):
    monkeypatch.setattr(_rc, "get_client_rect_for_image", lambda *a, **k: None)
    monkeypatch.setattr(_rc, "get_window_client_offset", lambda *a, **k: (0, 0))

    # OCR 被呼叫即失敗：BLOCKED 早退不得碰 OCR
    def _ocr_must_not_run(*a, **k):
        raise AssertionError("BLOCKED 規則不得執行 OCR / 步驟模擬")

    monkeypatch.setattr(_rc, "recognize", _ocr_must_not_run)

    rule = Rule(
        id="r1",
        name="R1",
        enabled=True,
        steps=[Step(type="detect", params={"text": ""})],
    )
    markers, log, dead_lines = _rc.TestRunController._run_dry_run(
        _fake_self(), rule, _blank_frame()
    )

    assert markers == []
    reasons = "、".join(_rc.T(f"exec_log.reason.{p}") for p in ["empty_detect_text"])
    expected = _rc.T("test.rule_blocked_header", name="R1", problems=reasons)
    assert expected in log
    assert dead_lines == {3}, f"BLOCKED 行應被標記為不可執行：{dead_lines}"
    joined = "\n".join(log)
    # 不得出現任何假成功列（✓ 通過/完成一類的符號）
    assert "✓" not in joined


def test_dry_run_normal_rule_not_affected(monkeypatch):
    """正常規則不進入 BLOCKED 早退路徑（dry-run 流程與 BLOCKED header 無關）。"""
    monkeypatch.setattr(_rc, "get_client_rect_for_image", lambda *a, **k: None)
    monkeypatch.setattr(_rc, "get_window_client_offset", lambda *a, **k: (0, 0))

    # 不跑 OCR：以假 OCR 回傳空列表，驗證未被擋下（會走正常流程、得到「未偵測到」類訊息）
    monkeypatch.setattr(_rc, "recognize", lambda *a, **k: [])

    rule = Rule(
        id="r2",
        name="R2",
        enabled=True,
        steps=[Step(type="detect", params={"text": "hello"})],
    )
    markers, log, dead_lines = _rc.TestRunController._run_dry_run(
        _fake_self(), rule, _blank_frame()
    )
    joined = "\n".join(log)
    assert "exec_log.reason." not in joined
    # 正常路徑不會出現 BLOCKED header
    assert _rc.T("test.rule_blocked_header", name="R2", problems="x") not in joined


# ── B4：取消（步驟之間協作式檢查）與 B1：結果附帶定位上下文 ──

T = _rc.T


class _FakeSignals:
    def __init__(self):
        self.emitted = []

        class _Sig:
            def emit(self_s, result):
                self.emitted.append(result)

        self.test_done_signal = _Sig()


def _fake_win(signals=None):
    return SimpleNamespace(
        _window_combo=_FakeCombo(),
        _signals=signals or _FakeSignals(),
    )


def _runner_self(signals=None):
    """SimpleNamespace 替身，但補綁 `_run_rule_test` 內會用到的同類方法。

    `_run_rule_test` 以 `self.` 呼叫 `_run_dry_run`/`_draw_test_annotations`；
    替身必須明確補上（既有 `_fake_self()` 不含方法）。
    """
    self_ns = _fake_self()
    self_ns._win = _fake_win(signals)
    self_ns._run_dry_run = lambda rule, img, cancel=None: _rc.TestRunController._run_dry_run(
        self_ns, rule, img, cancel=cancel
    )
    self_ns._draw_test_annotations = lambda img, markers: img
    return self_ns


def test_dry_run_cancel_before_first_step(monkeypatch):
    """取消事件已設下：dry-run 在第一個步驟前就停止，完全不執行步驟。"""
    monkeypatch.setattr(_rc, "get_client_rect_for_image", lambda *a, **k: None)
    monkeypatch.setattr(_rc, "get_window_client_offset", lambda *a, **k: (0, 0))
    monkeypatch.setattr(_rc, "recognize", lambda *a, **k: [])

    rule = Rule(
        id="r3",
        name="R3",
        enabled=True,
        steps=[Step(type="wait", params={"ms": 10}), Step(type="wait", params={"ms": 10})],
    )
    cancel = threading.Event()
    cancel.set()
    markers, log, dead_lines = _rc.TestRunController._run_dry_run(
        _fake_self(), rule, _blank_frame(), cancel=cancel
    )
    assert markers == []
    joined = "\n".join(log)
    assert T("test.wait", idx=1, ms=10) not in joined, "取消後不得再記錄任何步驟"


def test_dry_run_cancel_between_steps(monkeypatch):
    """取消在步驟之間生效：第 1 步完成、第 2 步起不再執行。"""
    monkeypatch.setattr(_rc, "get_client_rect_for_image", lambda *a, **k: None)
    monkeypatch.setattr(_rc, "get_window_client_offset", lambda *a, **k: (0, 0))

    cancel = threading.Event()

    def _ocr_first_then_cancel(*a, **k):
        cancel.set()  # 第一次 OCR 後立即請求取消
        return []

    monkeypatch.setattr(_rc, "recognize", _ocr_first_then_cancel)

    rule = Rule(
        id="r4",
        name="R4",
        enabled=True,
        steps=[
            Step(type="detect", params={"text": "AAA"}),
            Step(type="detect", params={"text": "BBB"}),
        ],
    )
    markers, log, dead_lines = _rc.TestRunController._run_dry_run(
        _fake_self(), rule, _blank_frame(), cancel=cancel
    )
    joined = "\n".join(log)
    assert "AAA" in joined, "取消前的步驟照常執行並記錄"
    assert "BBB" not in joined, "取消後的步驟不得執行"


def test_run_rule_test_cancelled_state(monkeypatch):
    """取消的結果是明確狀態：{'cancelled': True}，附帶定位上下文，不偽裝成失敗。"""
    signals = _FakeSignals()
    self_ns = _runner_self(signals)
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(_rc, "get_client_rect_for_image", lambda *a, **k: None)
    monkeypatch.setattr(_rc, "get_window_client_offset", lambda *a, **k: (0, 0))

    ctx = {"task": "t", "rule_id": "r5", "rule_name": "R5", "seq": 7}
    _rc.TestRunController._run_rule_test(
        self_ns,
        Rule(id="r5", name="R5", enabled=True, steps=[Step(type="wait", params={"ms": 1})]),
        _blank_frame(),
        ctx=ctx,
        cancel=cancel,
    )
    assert len(signals.emitted) == 1
    result = signals.emitted[0]
    assert result["cancelled"] is True
    assert result["locate"] == ctx
    assert "error" not in result and "image" not in result


def test_run_rule_test_attaches_locate_ctx(monkeypatch):
    """正常完成的結果也附帶啟動時保存的定位上下文。"""
    signals = _FakeSignals()
    self_ns = _runner_self(signals)
    monkeypatch.setattr(_rc, "get_client_rect_for_image", lambda *a, **k: None)
    monkeypatch.setattr(_rc, "get_window_client_offset", lambda *a, **k: (0, 0))

    ctx = {"task": "t2", "rule_id": "r6", "rule_name": "R6", "seq": 3}
    _rc.TestRunController._run_rule_test(
        self_ns,
        Rule(id="r6", name="R6", enabled=True, steps=[Step(type="wait", params={"ms": 1})]),
        _blank_frame(),
        ctx=ctx,
    )
    assert len(signals.emitted) == 1
    result = signals.emitted[0]
    assert result["locate"] == ctx
    assert result["log"] and result["image"] is not None


def test_run_rule_test_exception_carries_ctx_and_no_crash(monkeypatch):
    """dry-run 例外路徑（例：影像 dtype 錯誤）也要帶定位上下文並回報 error。"""
    signals = _FakeSignals()
    self_ns = _runner_self(signals)
    monkeypatch.setattr(_rc, "get_client_rect_for_image", lambda *a, **k: None)
    monkeypatch.setattr(_rc, "get_window_client_offset", lambda *a, **k: (0, 0))

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(_rc, "_preflight_mod", SimpleNamespace(rule_preflight=_boom))

    ctx = {"task": "t3", "rule_id": "r7", "rule_name": "R7", "seq": 2}
    _rc.TestRunController._run_rule_test(
        self_ns,
        Rule(id="r7", name="R7", enabled=True, steps=[Step(type="wait", params={"ms": 1})]),
        _blank_frame(),
        ctx=ctx,
    )
    result = signals.emitted[0]
    assert "error" in result
    assert result["locate"] == ctx


def test_controller_cancel_and_seq():
    ctrl = _rc.TestRunController(SimpleNamespace(), lambda *a, **k: "", lambda r: "")
    assert ctrl._run_seq == 0
    assert ctrl._cancel_event is None
    ctrl.cancel()  # 無進行中測試時不得崩潰
    ctrl._cancel_event = threading.Event()
    ctrl.cancel()
    assert ctrl._cancel_event.is_set()
