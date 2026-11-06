"""Dry Run 的 Preflight 行為：BLOCKED 規則必須明確顯示，不得假成功。

只測 BLOCKED 早退路徑（不會跑 OCR），不觸碰 Qt 視窗物件：
get_client_rect_for_image / get_window_client_offset 以 monkeypatch 換成純函式，
self 以 SimpleNamespace 替身取代（只需要 _win / _of_summary / _resolve_rule_name）。
"""

import os
import sys
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
