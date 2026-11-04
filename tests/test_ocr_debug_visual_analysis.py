"""Visual frame-difference analysis for OCR Debug tests (Phase 2).

Uses real NumPy arrays for the diff/ROI math. Only capture_frame and Qt
wiring are faked at the boundary; the comparison itself is never mocked.
"""

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from _loader import load_sibling

_debug = load_sibling("ocr_debug", "gui/09_ocr_debug.py")


@pytest.fixture
def panel(qt_app):
    result = _debug.OcrDebugPanel("Target")
    yield result
    result.deleteLater()
    qt_app.processEvents()


def _frame(h=20, w=30, value=100):
    return np.full((h, w, 3), value, dtype=np.uint8)


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


def _target(x=5, y=4, w=6, h=5):
    return _debug._OcrTarget("OK", x, y, w, h)


# ── 1-4. pure diff math ────────────────────────────────────────────────────


def test_visual_detects_obvious_change():
    before = _frame()
    after = _frame()
    after[8:12, 10:15] = 200
    v = _debug._compare_visual(before, after, (0, 0, 30, 20), scope="frame")
    assert v.status is _debug.ObservationStatus.CHANGED
    assert v.diff_pixels == 20
    assert v.before is not None and v.after is not None and v.heatmap is not None
    assert v.before.shape == (20, 30, 3)


def test_visual_no_change_for_same_pixels():
    v = _debug._compare_visual(_frame(), _frame(), (0, 0, 30, 20), scope="frame")
    assert v.status is _debug.ObservationStatus.NO_CHANGE
    assert v.diff_pixels == 0
    assert v.diff_ratio == 0.0


def test_visual_diff_ratio_is_exact_fraction():
    before = _frame(4, 5)
    after = _frame(4, 5)
    after[0, 0] = after[1, 1] = after[3, 4] = 200
    v = _debug._compare_visual(before, after, (0, 0, 5, 4), scope="frame")
    assert v.diff_pixels == 3
    assert v.diff_ratio == pytest.approx(3 / 20)


def test_visual_heatmap_marks_changed_coordinates_only():
    before = _frame(4, 5)
    after = _frame(4, 5)
    after[2, 3] = 250
    v = _debug._compare_visual(before, after, (0, 0, 5, 4), scope="frame")
    assert v.heatmap is not None
    assert v.heatmap[2, 3] == 255
    assert v.heatmap.sum() == 255


def test_visual_tolerance_ignores_tiny_noise():
    before = _frame()
    after = (before.astype(np.int16) + 5).astype(np.uint8)
    v = _debug._compare_visual(before, after, (0, 0, 30, 20), scope="frame", tolerance=12)
    assert v.status is _debug.ObservationStatus.NO_CHANGE
    v2 = _debug._compare_visual(before, after, (0, 0, 30, 20), scope="frame", tolerance=0)
    assert v2.status is _debug.ObservationStatus.CHANGED


# ── 5-6. ROI selection / clipping ──────────────────────────────────────────


def test_roi_is_padded_and_clipped_to_image():
    roi = _debug._roi_bounds(_target(0, 0, 4, 4), (20, 30, 3))
    assert roi == (0, 0, 8, 8)
    roi = _debug._roi_bounds(_target(28, 18, 10, 10), (20, 30, 3))
    assert roi == (24, 14, 6, 6)


def test_click_uses_target_roi_with_padding():
    roi, scope = _debug._select_visual_roi(_request("click", target=_target()), (20, 30, 3))
    assert scope == "roi"
    assert roi is not None
    assert roi[0] < 5 and roi[1] < 4
    assert roi[0] + roi[2] > 5 + 6 and roi[1] + roi[3] > 4 + 5


def test_key_without_target_falls_back_to_full_frame():
    roi, scope = _debug._select_visual_roi(_request("key", target=None), (20, 30, 3))
    assert scope == "frame"
    assert roi == (0, 0, 30, 20)


def test_empty_roi_is_unavailable():
    roi = _debug._roi_bounds(_debug._OcrTarget("x", 100, 100, 5, 5), (20, 30, 3))
    assert roi is None
    v = _debug._compare_visual(_frame(), _frame(), None, scope="roi")
    assert v.status is _debug.ObservationStatus.UNAVAILABLE
    assert v.reason == "roi_unavailable"
    v0 = _debug._compare_visual(_frame(), _frame(), (5, 5, 0, 4), scope="roi")
    assert v0.status is _debug.ObservationStatus.UNAVAILABLE


def test_roi_out_of_bounds_is_unavailable():
    v = _debug._compare_visual(_frame(), _frame(), (25, 15, 30, 20), scope="roi")
    assert v.status is _debug.ObservationStatus.UNAVAILABLE
    assert v.reason == "roi_out_of_bounds"


# ── 7-8. invalid frames ────────────────────────────────────────────────────


def test_size_mismatch_is_unavailable():
    v = _debug._compare_visual(_frame(20, 30), _frame(10, 30), (0, 0, 30, 20), scope="frame")
    assert v.status is _debug.ObservationStatus.UNAVAILABLE
    assert v.reason == "frame_size_changed"


def test_missing_frames_are_unavailable():
    for before, after in ((None, _frame()), (_frame(), None)):
        v = _debug._compare_visual(before, after, (0, 0, 30, 20), scope="frame")
        assert v.status is _debug.ObservationStatus.UNAVAILABLE
        assert v.reason == "capture_unavailable"


# ── 9-11. workers: black / source-hwnd / exception ─────────────────────────


def _install_worker_fakes(monkeypatch, panel, *, after, before=None, mode="frida", hwnd=123):
    captured = []
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: mode)
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_a, **_k: hwnd)
    fake_signals = SimpleNamespace(key=[], click=[])
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: captured.append(("key", d)))
    fake_signals.click_verify_done = SimpleNamespace(emit=lambda d: captured.append(("click", d)))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **_k: after)
    return captured


def test_key_worker_black_after_is_unavailable(monkeypatch, panel):
    panel._run_active = threading.Event()
    fake_signals = SimpleNamespace()
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: fake_signals.out.append(d))
    fake_signals.out = []
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_debug, "is_black_capture", lambda _img: True)
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **_k: _frame())
    panel._key_observation_worker(_request("key"), _frame(), "", threading.Event())
    payload = fake_signals.out[0]
    assert payload["visual"].status is _debug.ObservationStatus.UNAVAILABLE
    assert payload["visual"].reason == "black_capture"


def test_visual_source_change_is_unavailable(panel, monkeypatch):
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "hybrid")
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_a, **_k: 123)
    v = panel._analyze_visual(_request("key", mode="frida"), _frame(), _frame())
    assert v.status is _debug.ObservationStatus.UNAVAILABLE
    assert v.reason == "source_changed"


def test_visual_hwnd_change_is_unavailable(panel, monkeypatch):
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_a, **_k: 999)
    v = panel._analyze_visual(_request("key", mode="frida"), _frame(), _frame())
    assert v.status is _debug.ObservationStatus.UNAVAILABLE
    assert v.reason == "window_changed"


def test_visual_worker_exception_reports_unavailable(panel, monkeypatch):
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")
    monkeypatch.setattr(
        _debug._screenshot,
        "get_window_hwnd",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    v = panel._analyze_visual(_request("key", mode="frida"), _frame(), _frame())
    assert v.status is _debug.ObservationStatus.UNAVAILABLE
    assert v.reason == "worker_error"


def test_visual_changed_through_key_worker(monkeypatch, panel):
    panel._run_active = threading.Event()
    out = []
    fake_signals = SimpleNamespace()
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_a, **_k: 123)
    monkeypatch.setattr(_debug, "is_black_capture", lambda _img: False)
    after = _frame()
    after[5:9, 5:10] = 255
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **_k: after)
    panel._key_observation_worker(_request("key"), _frame(), "", threading.Event())
    visual = out[0]["visual"]
    assert visual.status is _debug.ObservationStatus.CHANGED
    assert visual.scope == "frame"
    assert visual.before is not None and visual.heatmap is not None


# ── 12-14. cancel / mainloop / generation ──────────────────────────────────


def test_cancelled_visual_is_unavailable(monkeypatch, panel):
    panel._run_active = threading.Event()
    out = []
    fake_signals = SimpleNamespace()
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    cancel = threading.Event()
    cancel.set()
    panel._key_observation_worker(_request("key"), _frame(), "", cancel)
    visual = out[0]["visual"]
    assert visual.status is _debug.ObservationStatus.UNAVAILABLE
    assert visual.reason == "cancelled"


def test_mainloop_start_discards_visual(monkeypatch, panel):
    panel._run_active = threading.Event()
    panel._run_active.set()
    out = []
    fake_signals = SimpleNamespace()
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    panel._key_observation_worker(_request("key"), _frame(), "", threading.Event())
    visual = out[0]["visual"]
    assert visual.status is _debug.ObservationStatus.UNAVAILABLE
    assert visual.reason == "main_loop_running"


def test_click_cancel_discards_visual(monkeypatch, panel):
    panel._run_active = threading.Event()
    out = []
    fake_signals = SimpleNamespace()
    fake_signals.click_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    cancel = threading.Event()
    cancel.set()
    panel._click_verify_worker(
        _target(),
        10,
        20,
        30,
        20,
        1,
        request=_request("click", target=_target()),
        cancel=cancel,
        before=_frame(),
    )
    visual = out[0]["visual"]
    assert visual.status is _debug.ObservationStatus.UNAVAILABLE
    assert visual.reason == "cancelled"


def test_stale_generation_visual_does_not_overwrite(panel):
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
            "visual": _debug.VisualAnalysis(status=_debug.ObservationStatus.CHANGED),
        }
    )
    assert panel._diagnostic_label.text() == "new test"
    assert panel._diagnostic_result is backend


# ── 15-16. backend / visual independence ───────────────────────────────────


def _backend_result(status, test_id=1):
    return _debug.BackendTestResult(
        test_id, "key", "frida", 123, "space", None, status, 1.0, error=""
    )


def test_visual_never_overwrites_failed_backend(panel):
    panel._key_verify_request_id = 1
    panel._diagnostic_result = _backend_result(_debug.BackendStatus.FAILED)
    panel._on_key_verify_done(
        {
            "request_id": 1,
            "state": "success",
            "key": "space",
            "visual": _debug.VisualAnalysis(
                status=_debug.ObservationStatus.CHANGED,
                scope="frame",
                roi=(0, 0, 30, 20),
                diff_pixels=5,
                diff_ratio=0.01,
            ),
        }
    )
    assert panel._diagnostic_result.backend_status is _debug.BackendStatus.FAILED
    assert panel._diagnostic_result.visual.status is _debug.ObservationStatus.CHANGED


def test_backend_success_with_unavailable_visual_still_shows_success(panel):
    panel._key_verify_request_id = 1
    panel._diagnostic_result = _backend_result(_debug.BackendStatus.SUCCESS)
    panel._on_key_verify_done(
        {
            "request_id": 1,
            "state": "black",
            "key": "space",
            "visual": _debug._visual_unavailable("capture_unavailable"),
        }
    )
    assert panel._diagnostic_result.backend_status is _debug.BackendStatus.SUCCESS
    assert panel._diagnostic_result.visual.status is _debug.ObservationStatus.UNAVAILABLE
    assert "Backend API" in panel._diagnostic_label.text()


# ── 17. GUI thread must not run the comparison ─────────────────────────────


def test_comparison_runs_on_worker_thread_not_gui(panel, monkeypatch):
    gui_ident = threading.get_ident()
    worker_idents = []

    real_compare = _debug._compare_visual

    def spy(*a, **k):
        worker_idents.append(threading.get_ident())
        return real_compare(*a, **k)

    monkeypatch.setattr(_debug, "_compare_visual", spy)
    monkeypatch.setattr(_debug.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_a, **_k: 123)
    monkeypatch.setattr(_debug, "is_black_capture", lambda _img: False)
    monkeypatch.setattr(_debug, "capture_frame", lambda *a, **_k: _frame())
    out = []
    fake_signals = SimpleNamespace()
    fake_signals.key_verify_done = SimpleNamespace(emit=lambda d: out.append(d))
    panel._signals = fake_signals
    worker = threading.Thread(
        target=lambda: panel._key_observation_worker(
            _request("key"), _frame(), "", threading.Event()
        )
    )
    worker.start()
    worker.join(timeout=5)
    assert worker_idents and all(i != gui_ident for i in worker_idents)


def test_render_updates_preview_widgets(panel):
    visual = _debug._compare_visual(_frame(), _frame(), (0, 0, 30, 20), scope="frame")
    result = _debug.BackendTestResult(
        1, "key", "frida", 123, "space", None, _debug.BackendStatus.SUCCESS, 1.0, visual=visual
    )
    panel._render_diagnostic_result(result)
    assert not panel._visual_preview.isHidden()
    assert set(panel._visual_preview_pixmaps) == {"before", "after", "heatmap"}
    text = panel._diagnostic_label.text()
    assert "Visual" in text
    assert "ROI" not in text or "全影格" in text or "Full frame" in text or "全画面" in text


# ── 18. i18n completeness ──────────────────────────────────────────────────


def test_visual_i18n_keys_exist_in_all_locales():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    keys = [
        "ocr_debug.diagnostic.visual_line",
        "ocr_debug.diagnostic.scope.roi",
        "ocr_debug.diagnostic.scope.frame",
        "ocr_debug.diagnostic.scope.none",
        "ocr_debug.diagnostic.preview.before",
        "ocr_debug.diagnostic.preview.after",
        "ocr_debug.diagnostic.preview.heatmap",
        "ocr_debug.diagnostic.visual_reason_line",
        "ocr_debug.diagnostic.visual_reason.capture_unavailable",
        "ocr_debug.diagnostic.visual_reason.black_capture",
        "ocr_debug.diagnostic.visual_reason.roi_unavailable",
        "ocr_debug.diagnostic.visual_reason.frame_size_changed",
        "ocr_debug.diagnostic.visual_reason.source_changed",
        "ocr_debug.diagnostic.visual_reason.window_changed",
        "ocr_debug.diagnostic.visual_reason.cancelled",
        "ocr_debug.diagnostic.visual_reason.main_loop_running",
        "ocr_debug.diagnostic.visual_reason.worker_error",
    ]
    for lang in ("zh_TW", "en", "ja"):
        data = json.loads((root / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        assert all(data.get(k) for k in keys), (lang, [k for k in keys if not data.get(k)])
