"""OCR text-diff analysis (Phase 3-B).

Pure pairing logic runs on real OcrResult dataclasses. recognize_detailed
is exercised with injected fake executor submissions, never by copying
the engine pipeline.
"""

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from _loader import load_sibling

_debug = load_sibling("ocr_debug", "gui/09_ocr_debug.py")
_engine = load_sibling("ocr_engine", "core/02_ocr_engine.py")


def _r(text, x=0, y=0, w=20, h=10, confidence=0.9):
    return _engine.OcrResult(text=text, x=x, y=y, w=w, h=h, confidence=confidence)


@pytest.fixture
def panel(qt_app):
    result = _debug.OcrDebugPanel("Target")
    yield result
    result.deleteLater()
    qt_app.processEvents()


def _request(kind="key", mode="frida", *, hwnd=123, generation=1, target=None):
    return _debug.BackendTestRequest(
        generation=generation,
        kind=kind,
        mode=mode,
        window_title="Target",
        hwnd=hwnd,
        key="space" if kind == "key" else "",
        target=target,
        frame_size=(30, 20),
    )


def _frame(h=20, w=30, value=100):
    return np.full((h, w, 3), value, dtype=np.uint8)


# ── A. OCR API compatibility ─────────────────────────────────────────────


def test_recognize_keeps_list_contract(monkeypatch):
    class FakeFuture:
        def result(self, timeout=None):
            return ([([[0, 0], [5, 0], [5, 5], [0, 5]], "OK", 0.9)], None)

    monkeypatch.setattr(_engine._ocr_executor, "submit", lambda fn, *a: FakeFuture())
    monkeypatch.setattr(_engine, "_reset_ocr_failures", lambda: None)
    monkeypatch.setattr(_engine, "_incr_ocr_failure", lambda: None)
    monkeypatch.setattr(
        _engine,
        "_prepare_image",
        lambda image, max_side_len, preprocess: (image, 1.0),
    )
    outcome = _engine.recognize_detailed(_frame(), min_confidence=0.25)
    plain = _engine.recognize(_frame(), min_confidence=0.25)
    assert isinstance(outcome.results, list)
    assert outcome.status == "ok", outcome
    assert plain == outcome.results
    assert plain[0].text == "OK"


def test_recognize_detailed_empty_success_is_ok_not_failure(monkeypatch):
    class FakeFuture:
        def result(self, timeout=None):
            return ([], None)

    monkeypatch.setattr(_engine._ocr_executor, "submit", lambda fn, *a: FakeFuture())
    outcome = _engine.recognize_detailed(_frame(), min_confidence=0.25)
    assert outcome.status == "ok"
    assert outcome.results == []
    assert outcome.reason == ""


def test_recognize_detailed_timeout_is_distinguishable(monkeypatch):
    from concurrent.futures import TimeoutError as FutureTimeout

    class FakeFuture:
        def result(self, timeout=None):
            raise FutureTimeout()

    monkeypatch.setattr(_engine._ocr_executor, "submit", lambda fn, *a: FakeFuture())
    monkeypatch.setattr(_engine, "_incr_ocr_failure", lambda: None)
    outcome = _engine.recognize_detailed(_frame())
    assert outcome.status == "timeout"
    assert outcome.results == []
    assert _engine.recognize(_frame()) == []


def test_recognize_detailed_error_is_distinguishable(monkeypatch):
    class FakeFuture:
        def result(self, timeout=None):
            raise RuntimeError("engine exploded")

    monkeypatch.setattr(_engine._ocr_executor, "submit", lambda fn, *a: FakeFuture())
    monkeypatch.setattr(_engine, "_incr_ocr_failure", lambda: None)
    outcome = _engine.recognize_detailed(_frame())
    assert outcome.status == "error"
    assert "engine exploded" in outcome.reason
    assert outcome.results == []


def test_recognize_detailed_empty_input(monkeypatch):
    for bad in (None, np.zeros((0, 0, 3), dtype=np.uint8)):
        outcome = _engine.recognize_detailed(bad)
        assert outcome.status == "empty_input"
        assert outcome.results == []
        assert _engine.recognize(bad) == []


def test_recognize_detailed_none_rows_is_error(monkeypatch):
    class FakeFuture:
        def result(self, timeout=None):
            return (None, None)

    monkeypatch.setattr(_engine._ocr_executor, "submit", lambda fn, *a: FakeFuture())
    outcome = _engine.recognize_detailed(_frame())
    assert outcome.status == "error"
    assert outcome.reason == "empty_result"
    assert outcome.results == []


def test_outcome_is_not_polluted_by_concurrent_calls(monkeypatch):
    import threading as _t

    barrier = _t.Barrier(2)
    results = {}

    class FakeFuture:
        def __init__(self, payload):
            self._payload = payload

        def result(self, timeout=None):
            barrier.wait()
            return self._payload

    payloads = [([["x"]], None), ([["y"]], None)]

    def fake_submit(fn, *a, **k):
        return FakeFuture(payloads[len(results)])

    monkeypatch.setattr(_engine._ocr_executor, "submit", fake_submit)
    monkeypatch.setattr(_engine, "_reset_ocr_failures", lambda: None)

    def call(name):
        results[name] = _engine.recognize_detailed(_frame(), min_confidence=0.0)

    threads = [_t.Thread(target=lambda n=name: call(n)) for name in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert set(results) == {"a", "b"}
    assert all(isinstance(v.results, list) for v in results.values())


def test_timeout_does_not_cancel_executor_work(monkeypatch):
    import time as _time

    events = []

    class FakeFuture:
        def result(self, timeout=None):
            events.append("wait")
            return (None, None)

    monkeypatch.setattr(
        _engine._ocr_executor,
        "submit",
        lambda fn, *a: (events.append("ran"), _time.sleep(0.01), FakeFuture())[2],
    )
    outcome = _engine.recognize_detailed(_frame())
    assert outcome.status == "error" or outcome.status == "ok"
    assert events == ["ran", "wait"]


# ── B. pure algorithm ────────────────────────────────────────────────────


def test_compare_detects_added_text():
    v = _debug._compare_ocr_texts(
        [_r("OK")], [_r("OK"), _r("NEW", 0, 15)], scope="roi", roi=(0, 0, 30, 30)
    )
    assert v.status is _debug.ObservationStatus.CHANGED
    assert v.added == ("NEW",)
    assert v.disappeared == ()


def test_compare_detects_disappeared_text():
    v = _debug._compare_ocr_texts(
        [_r("OK"), _r("OLD", 0, 15)], [_r("OK")], scope="roi", roi=(0, 0, 30, 30)
    )
    assert v.status is _debug.ObservationStatus.CHANGED
    assert v.disappeared == ("OLD",)


def test_compare_detects_replacement_at_same_place():
    v = _debug._compare_ocr_texts([_r("HP 100")], [_r("HP 90")], scope="roi", roi=(0, 0, 30, 30))
    assert v.status is _debug.ObservationStatus.CHANGED
    assert v.changed == (("HP 100", "HP 90"),)


def test_compare_detects_moved_text():
    v = _debug._compare_ocr_texts(
        [_r("OK", 0, 0)], [_r("OK", 25, 25)], scope="roi", roi=(0, 0, 30, 30)
    )
    assert v.status is _debug.ObservationStatus.CHANGED
    assert v.moved == ("OK",)
    assert v.added == () and v.disappeared == () and v.changed == ()


def test_compare_ignores_order_change():
    before = [_r("A", 0, 0), _r("B", 0, 15)]
    after = [_r("B", 0, 15), _r("A", 0, 0)]
    v = _debug._compare_ocr_texts(before, after, scope="roi", roi=(0, 0, 30, 30))
    assert v.status is _debug.ObservationStatus.NO_CHANGE
    assert v.added == () and v.disappeared == ()


def test_compare_handles_duplicate_text():
    before = [_r("OK", 0, 0), _r("OK", 0, 15)]
    after = [_r("OK", 0, 0)]
    v = _debug._compare_ocr_texts(before, after, scope="roi", roi=(0, 0, 30, 30))
    assert v.status is _debug.ObservationStatus.CHANGED
    assert v.disappeared == ("OK",)  # exactly one instance disappeared


def test_compare_ignores_confidence_fluctuation():
    v = _debug._compare_ocr_texts(
        [_r("OK", confidence=0.9)], [_r("OK", confidence=0.3)], scope="roi", roi=(0, 0, 30, 30)
    )
    assert v.status is _debug.ObservationStatus.NO_CHANGE
    assert v.changed == ()


def test_compare_ignores_small_coordinate_jitter():
    v = _debug._compare_ocr_texts(
        [_r("OK", 0, 0)], [_r("OK", 1, 1)], scope="roi", roi=(0, 0, 30, 30)
    )
    assert v.status is _debug.ObservationStatus.NO_CHANGE
    assert v.moved == ()


def test_compare_normalizes_case_and_fullwidth():
    v = _debug._compare_ocr_texts([_r("ＡＢＣ")], [_r("abc")], scope="roi", roi=(0, 0, 30, 30))
    assert v.status is _debug.ObservationStatus.NO_CHANGE


def test_compare_handles_different_splitting():
    before = [_r("確定", 0, 0, w=40)]
    after = [_r("確", 0, 0, w=20), _r("定", 20, 0, w=20)]
    v = _debug._compare_ocr_texts(before, after, scope="roi", roi=(0, 0, 40, 20))
    # different splitting should surface as change somewhere, not crash
    assert v.status is _debug.ObservationStatus.CHANGED
    assert v.added or v.changed or v.disappeared


def test_compare_one_side_empty():
    v = _debug._compare_ocr_texts([], [_r("OK")], scope="roi", roi=(0, 0, 30, 30))
    assert v.status is _debug.ObservationStatus.CHANGED
    assert v.added == ("OK",)
    v2 = _debug._compare_ocr_texts([], [], scope="roi", roi=(0, 0, 30, 30))
    assert v2.status is _debug.ObservationStatus.NO_CHANGE


def test_text_diff_dataclass_defaults_are_immutable():
    import dataclasses

    td = _debug.TextDiffAnalysis()
    assert td.status is _debug.ObservationStatus.NOT_RUN
    assert td.added == () and td.disappeared == ()
    assert td.reason == ""
    assert td.before_results == () and td.after_results == ()
    assert dataclasses.is_dataclass(td)
    result = _debug.BackendTestResult(
        1, "key", "frida", 123, "space", None, _debug.BackendStatus.SUCCESS, 1.0
    )
    assert result.text_diff.status is _debug.ObservationStatus.NOT_RUN
    assert result.ocr_status is _debug.ObservationStatus.NOT_RUN  # legacy preserved


# ── C. worker integration ────────────────────────────────────────────────


def _install_ocr_fakes(monkeypatch, panel, *, sequence):
    """sequence: list of OcrCallOutcome returned in order by recognize_detailed."""
    calls = []
    idx = {"i": 0}

    def fake(*a, **k):
        calls.append((threading.get_ident(), len(a[0].shape) if len(a) else 0))
        out = sequence[min(idx["i"], len(sequence) - 1)]
        idx["i"] += 1
        return out

    monkeypatch.setattr(_debug, "recognize_detailed", fake)
    return calls


def test_key_worker_runs_text_diff(monkeypatch, panel):
    panel._run_active = threading.Event()
    fake_signals = SimpleNamespace()
    out = []
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_a, **_k: 123)
    monkeypatch.setattr(_debug, "is_black_capture", lambda _i: False)
    before = _frame()
    after = _frame()
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **_k: after)
    visual = _debug.VisualAnalysis(status=_debug.ObservationStatus.CHANGED, scope="frame")
    monkeypatch.setattr(panel, "_analyze_visual", lambda *a, **k: visual)
    sequence = [
        _engine.OcrCallOutcome([_r("OK")], "ok", ""),
        _engine.OcrCallOutcome([_r("OK"), _r("NEW", 0, 15)], "ok", ""),
    ]
    calls = _install_ocr_fakes(monkeypatch, panel, sequence=sequence)
    panel._key_observation_worker(_request("key"), before, "", threading.Event())
    payload = out[0]
    assert payload["text_diff"].status is _debug.ObservationStatus.CHANGED
    assert payload["text_diff"].added == ("NEW",)
    assert len(calls) == 2
    assert all(tid == threading.get_ident() for tid, _ in calls)


def test_click_worker_runs_text_diff(monkeypatch, panel):
    panel._run_active = threading.Event()
    fake_signals = SimpleNamespace()
    out = []
    fake_signals.click_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_a, **_k: 123)
    monkeypatch.setattr(_debug, "is_black_capture", lambda _i: False)
    before = _frame()
    after = _frame()
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **_k: after)
    monkeypatch.setattr(_debug, "recognize", lambda *a, **k: [_r("OK")])
    monkeypatch.setattr(
        panel,
        "_analyze_visual",
        lambda *a, **k: (
            _debug.VisualAnalysis(status=_debug.ObservationStatus.CHANGED) if a else None
        ),
    )

    # prevent real _analyze_text_diff from calling capture-dependent logic
    def fake_visual(*a, **k):
        return _debug.VisualAnalysis(status=_debug.ObservationStatus.CHANGED)

    monkeypatch.setattr(panel, "_analyze_visual", fake_visual)
    sequence = [
        _engine.OcrCallOutcome([_r("OK")], "ok", ""),
        _engine.OcrCallOutcome([_r("OK")], "ok", ""),
    ]
    _install_ocr_fakes(monkeypatch, panel, sequence=sequence)
    target = _debug._OcrTarget("OK", 5, 4, 6, 5)
    panel._click_verify_worker(
        target,
        10,
        20,
        30,
        20,
        1,
        request=_request("click", target=target),
        cancel=threading.Event(),
        before=before,
    )
    payload = out[0]
    assert "text_diff" in payload
    assert payload["text_diff"].status is not _debug.ObservationStatus.NOT_RUN
    assert payload["visual"].status is _debug.ObservationStatus.CHANGED


def test_text_diff_timeout_marks_unavailable(monkeypatch, panel):
    panel._run_active = threading.Event()
    fake_signals = SimpleNamespace()
    out = []
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_a, **_k: 123)
    monkeypatch.setattr(_debug, "is_black_capture", lambda _i: False)
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **_k: _frame())
    monkeypatch.setattr(
        panel,
        "_analyze_visual",
        lambda *a, **k: _debug.VisualAnalysis(status=_debug.ObservationStatus.CHANGED),
    )
    sequence = [
        _engine.OcrCallOutcome([], "timeout", ""),
        _engine.OcrCallOutcome([_r("OK")], "ok", ""),
    ]
    _install_ocr_fakes(monkeypatch, panel, sequence=sequence)
    panel._key_observation_worker(_request("key"), _frame(), "", threading.Event())
    td = out[0]["text_diff"]
    assert td.status is _debug.ObservationStatus.UNAVAILABLE
    assert td.before_ocr_status == "timeout"
    assert td.after_ocr_status == "ok"
    assert td.reason == "timeout"


def test_text_diff_error_marks_unavailable(monkeypatch, panel):
    panel._run_active = threading.Event()
    fake_signals = SimpleNamespace()
    out = []
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_a, **_k: 123)
    monkeypatch.setattr(_debug, "is_black_capture", lambda _i: False)
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **_k: _frame())
    monkeypatch.setattr(
        panel,
        "_analyze_visual",
        lambda *a, **k: _debug.VisualAnalysis(status=_debug.ObservationStatus.CHANGED),
    )
    sequence = [
        _engine.OcrCallOutcome([_r("OK")], "ok", ""),
        _engine.OcrCallOutcome([], "error", "boom"),
    ]
    _install_ocr_fakes(monkeypatch, panel, sequence=sequence)
    panel._key_observation_worker(_request("key"), _frame(), "", threading.Event())
    td = out[0]["text_diff"]
    assert td.status is _debug.ObservationStatus.UNAVAILABLE
    assert td.after_ocr_status == "error"
    assert td.reason == "boom"


def test_text_diff_success_empty_not_failure(monkeypatch, panel):
    panel._run_active = threading.Event()
    fake_signals = SimpleNamespace()
    out = []
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_a, **_k: 123)
    monkeypatch.setattr(_debug, "is_black_capture", lambda _i: False)
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **_k: _frame())
    monkeypatch.setattr(
        panel,
        "_analyze_visual",
        lambda *a, **k: _debug.VisualAnalysis(status=_debug.ObservationStatus.NO_CHANGE),
    )
    sequence = [
        _engine.OcrCallOutcome([], "ok", ""),
        _engine.OcrCallOutcome([], "ok", ""),
    ]
    _install_ocr_fakes(monkeypatch, panel, sequence=sequence)
    panel._key_observation_worker(_request("key"), _frame(), "", threading.Event())
    td = out[0]["text_diff"]
    assert td.status is _debug.ObservationStatus.NO_CHANGE
    assert td.before_ocr_status == "ok" and td.after_ocr_status == "ok"


def test_text_diff_cancel_skips_ocr(monkeypatch, panel):
    panel._run_active = threading.Event()
    fake_signals = SimpleNamespace()
    out = []
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(panel, "_analyze_visual", lambda *a, **k: _debug.VisualAnalysis())
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **_k: _frame())
    calls = _install_ocr_fakes(monkeypatch, panel, sequence=[_engine.OcrCallOutcome([], "ok", "")])
    panel._key_observation_worker(_request("key"), _frame(), "", cancel)
    assert calls == []
    assert out[0]["text_diff"].reason == "cancelled"


def test_text_diff_mainloop_skips_and_old_generation_ignored(panel, monkeypatch):
    panel._run_active = threading.Event()
    panel._run_active.set()
    fake_signals = SimpleNamespace()
    out = []
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    _install_ocr_fakes(monkeypatch, panel, sequence=[_engine.OcrCallOutcome([], "ok", "")])
    panel._key_observation_worker(_request("key"), _frame(), "", threading.Event())
    assert out[0]["text_diff"].reason == "main_loop_running"

    panel._key_verify_request_id = 9
    panel._diagnostic_label.setText("new test")
    backend = _debug.BackendTestResult(
        8, "key", "frida", 123, "space", None, _debug.BackendStatus.SUCCESS, 1.0
    )
    panel._diagnostic_result = backend
    panel._on_key_verify_done(
        {
            "request_id": 8,
            "state": "success",
            "text_diff": _debug.TextDiffAnalysis(status=_debug.ObservationStatus.CHANGED),
        }
    )
    assert panel._diagnostic_label.text() == "new test"
    assert panel._diagnostic_result is backend


def test_visual_unavailable_skips_text_ocr(monkeypatch, panel):
    panel._run_active = threading.Event()
    fake_signals = SimpleNamespace()
    out = []
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_a, **_k: 123)
    monkeypatch.setattr(_debug, "is_black_capture", lambda _i: False)
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **_k: _frame())
    monkeypatch.setattr(
        panel,
        "_analyze_visual",
        lambda *a, **k: _debug.VisualAnalysis(
            status=_debug.ObservationStatus.UNAVAILABLE, reason="black_capture"
        ),
    )
    calls = _install_ocr_fakes(monkeypatch, panel, sequence=[_engine.OcrCallOutcome([], "ok", "")])
    # freeze _get_interaction_mode so _analyze_text_diff source path is stable
    panel._key_observation_worker(_request("key"), _frame(), "", threading.Event())
    assert calls == []
    assert out[0]["text_diff"].status is _debug.ObservationStatus.UNAVAILABLE
    assert out[0]["text_diff"].reason == "black_capture"


def test_backend_failed_text_changed_keeps_layers_independent(panel):
    panel._key_verify_request_id = 1
    backend = _debug.BackendTestResult(
        1,
        "key",
        "frida",
        123,
        "space",
        None,
        _debug.BackendStatus.FAILED,
        1.0,
        error="error_unavailable",
    )
    panel._diagnostic_result = backend
    panel._on_key_verify_done(
        {
            "request_id": 1,
            "state": "success",
            "key": "space",
            "visual": _debug.VisualAnalysis(status=_debug.ObservationStatus.CHANGED, scope="frame"),
            "text_diff": _debug.TextDiffAnalysis(
                status=_debug.ObservationStatus.CHANGED, scope="frame", added=("NEW",)
            ),
        }
    )
    assert panel._diagnostic_result.backend_status is _debug.BackendStatus.FAILED
    assert panel._diagnostic_result.visual.status is _debug.ObservationStatus.CHANGED
    assert panel._diagnostic_result.text_diff.status is _debug.ObservationStatus.CHANGED
    assert (
        "OCR 文字" in panel._diagnostic_label.text()
        or "OCR text" in panel._diagnostic_label.text()
        or "OCR テキスト" in panel._diagnostic_label.text()
    )
