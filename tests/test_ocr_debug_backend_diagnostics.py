"""Backend result and worker routing for OCR Debug input tests."""

import ctypes
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from _loader import load_sibling

_debug = load_sibling("ocr_debug", "gui/09_ocr_debug.py")
_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def panel(qt_app):
    result = _debug.OcrDebugPanel("Target")
    yield result
    result.deleteLater()
    qt_app.processEvents()


def _request(kind, mode, *, hwnd=123, generation=1):
    return _debug.BackendTestRequest(
        generation=generation,
        kind=kind,
        mode=mode,
        window_title="Target",
        hwnd=hwnd,
        key="space" if kind == "key" else "",
        target=_debug._OcrTarget("OK", 10, 20, 8, 6) if kind == "click" else None,
        window_rect=(100, 200, 800, 600),
    )


def _install_input_fakes(monkeypatch, *, click_result=True, key_result=True, error=""):
    calls = []
    state = {"error": error}

    class FakeBackground:
        def set_method(self, mode):
            calls.append(("set_method", mode, threading.get_ident()))

        def last_error(self):
            return state["error"]

        def click(self, hwnd, x, y, cancel=None):
            calls.append(("frida_click", hwnd, x, y, threading.get_ident()))
            return click_result

        def send_key(self, hwnd, key, cancel=None):
            calls.append(("frida_key", hwnd, key, threading.get_ident()))
            return key_result

    class FakePynput:
        def send_click(self, x, y, cancel=None):
            calls.append(("pynput_click", x, y, threading.get_ident()))
            return click_result

        def send_key(self, key, cancel=None):
            calls.append(("pynput_key", key, threading.get_ident()))
            return key_result

    @contextmanager
    def focus_guard(*args):
        calls.append(("focus_guard", threading.get_ident()))
        yield True

    monkeypatch.setattr(_debug, "_bg_input", FakeBackground())
    monkeypatch.setattr(_debug, "_pynput_input", FakePynput())
    monkeypatch.setattr(_debug._hybrid, "focus_guard", focus_guard)
    monkeypatch.setattr(_debug, "activate_window", lambda *_: True)
    monkeypatch.setattr(_debug._screenshot, "get_window_client_offset", lambda *_: (0, 0))
    fake_user32 = SimpleNamespace(
        ClientToScreen=lambda hwnd, point_ref: (
            setattr(point_ref._obj, "x", 100) or setattr(point_ref._obj, "y", 200) or 1
        )
    )
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=fake_user32), raising=False)
    return calls, state


@pytest.mark.parametrize(
    ("kind", "mode", "expected"),
    [
        ("click", "frida", "frida_click"),
        ("key", "frida", "frida_key"),
        ("click", "hybrid", "pynput_click"),
        ("key", "hybrid", "pynput_key"),
        ("click", "pynput", "pynput_click"),
        ("key", "pynput", "pynput_key"),
    ],
)
def test_all_backend_modes_dispatch_on_worker_thread(panel, monkeypatch, kind, mode, expected):
    calls, _ = _install_input_fakes(monkeypatch)
    request = _request(kind, mode)
    outcome = []
    worker = threading.Thread(
        target=lambda: outcome.append(panel._dispatch_backend_test(request, threading.Event()))
    )
    worker.start()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert outcome[0][0].backend_status is _debug.BackendStatus.SUCCESS
    api_calls = [
        call
        for call in calls
        if call[0] in ("frida_click", "frida_key", "pynput_click", "pynput_key")
    ]
    assert len(api_calls) == 1
    assert api_calls[0][0] == expected
    assert api_calls[0][-1] != threading.get_ident()


@pytest.mark.parametrize(
    ("api_result", "previous_error", "current_error", "expected_error"),
    [
        (False, "", "specific current failure", "specific current failure"),
        (False, "same old failure", "same old failure", "error_unavailable"),
        (False, "old error", "", "error_unavailable"),
        (True, "stale error", "", ""),
    ],
)
def test_backend_error_is_only_shown_when_distinguishable(
    panel, monkeypatch, api_result, previous_error, current_error, expected_error
):
    calls, state = _install_input_fakes(monkeypatch, key_result=api_result, error=previous_error)

    class FreshErrorBackground:
        def set_method(self, mode):
            pass

        def last_error(self):
            return state["error"]

        def send_key(self, hwnd, key, cancel=None):
            state["error"] = current_error
            return api_result

    monkeypatch.setattr(_debug, "_bg_input", FreshErrorBackground())
    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: "frida")
    result, _ = panel._dispatch_backend_test(_request("key", "frida"), threading.Event())
    assert result.backend_status is (
        _debug.BackendStatus.SUCCESS if api_result else _debug.BackendStatus.FAILED
    )
    assert result.error == expected_error


def test_cancel_and_mainloop_gate_do_not_call_input(panel, monkeypatch):
    calls, _ = _install_input_fakes(monkeypatch)
    request = _request("key", "frida")
    cancelled = threading.Event()
    cancelled.set()
    result, _ = panel._dispatch_backend_test(request, cancelled)
    assert result.backend_status is _debug.BackendStatus.CANCELLED
    assert result.cancelled is True
    panel.set_run_active(True)
    result, _ = panel._dispatch_backend_test(request, threading.Event())
    assert result.backend_status is _debug.BackendStatus.NOT_EXECUTED
    assert calls == []


@pytest.mark.parametrize("kind,mode", [("click", "frida"), ("key", "pynput")])
def test_ui_callback_starts_worker_and_ui_result_returns_through_signal(
    panel, qt_app, monkeypatch, kind, mode
):
    main_thread = threading.get_ident()
    dispatched = threading.Event()
    worker_ids = []

    monkeypatch.setattr(_debug, "_get_interaction_mode", lambda: mode)
    monkeypatch.setattr(_debug._screenshot, "get_window_hwnd", lambda *_: 123)
    monkeypatch.setattr(
        _debug._screenshot, "get_window_rect", lambda *_: {"x": 10, "y": 20, "w": 800, "h": 600}
    )
    panel._dispatch_backend_test = lambda request, cancel: (
        worker_ids.append(threading.get_ident())
        or dispatched.set()
        or _debug.BackendTestResult(
            request.generation,
            request.kind,
            request.mode,
            request.hwnd,
            request.key,
            (40, 50) if request.kind == "click" else None,
            _debug.BackendStatus.SUCCESS,
            2.0,
        ),
        (40, 50),
    )
    panel._click_verify_worker = lambda *args, **kwargs: None
    panel._key_observation_worker = lambda *args, **kwargs: None
    rendered_thread = []
    panel._render_diagnostic_result = lambda result: rendered_thread.append(threading.get_ident())

    if kind == "click":
        panel._ocr_results = [SimpleNamespace(text="OK", x=1, y=2, w=8, h=6)]
        panel._selected_index = 0
        panel._latest_raw = __import__("numpy").zeros((10, 10, 3), dtype="uint8")
        panel._capture_source = "screen"
        panel._on_click_test()
    else:
        panel._on_key_test()

    assert dispatched.wait(2), "callback must return while input work runs in the background"
    assert worker_ids[0] != main_thread
    deadline = time.monotonic() + 2
    while not rendered_thread and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    assert rendered_thread == [main_thread]
    assert panel._diagnostic_result.backend_status is _debug.BackendStatus.SUCCESS


def test_observation_result_never_overwrites_backend_status(panel):
    panel._click_verify_request_id = 3
    result = _debug.BackendTestResult(
        3,
        "click",
        "pynput",
        123,
        "",
        (10, 20),
        _debug.BackendStatus.SUCCESS,
        4.0,
    )
    panel._diagnostic_result = result
    panel._show_click_verify = lambda *args, **kwargs: None
    panel._on_click_verify_done(
        {
            "request_id": 3,
            "state": "no_response",
            "still": "yes",
            "text": "OK",
        }
    )
    assert panel._diagnostic_result.backend_status is _debug.BackendStatus.SUCCESS
    assert panel._diagnostic_result.visual_status is _debug.ObservationStatus.NOT_RUN
    assert panel._diagnostic_result.ocr_status is _debug.ObservationStatus.TEXT_PRESENT

    panel._key_verify_request_id = 4
    panel._diagnostic_result = _debug.BackendTestResult(
        4,
        "key",
        "frida",
        123,
        "space",
        None,
        _debug.BackendStatus.SUCCESS,
        4.0,
    )
    panel._show_key_verify = lambda *_: None
    panel._on_key_verify_done({"request_id": 4, "state": "no_change", "key": "space"})
    assert panel._diagnostic_result.backend_status is _debug.BackendStatus.SUCCESS
    assert panel._diagnostic_result.visual_status is _debug.ObservationStatus.NO_CHANGE
    assert panel._diagnostic_result.ocr_status is _debug.ObservationStatus.NOT_RUN


def test_stale_backend_result_does_not_update_diagnostic_ui(panel):
    panel._click_verify_request_id = 9
    panel._diagnostic_label.setText("new test")
    panel._on_backend_test_done(
        _debug.BackendTestResult(
            8,
            "click",
            "frida",
            123,
            "",
            (1, 2),
            _debug.BackendStatus.FAILED,
            1.0,
            error="old error",
        )
    )
    assert panel._diagnostic_label.text() == "new test"
    assert panel._diagnostic_result is None


def test_new_diagnostic_translations_exist_in_all_locales():
    keys = [
        "ocr_debug.diagnostic.kind.click",
        "ocr_debug.diagnostic.kind.key",
        "ocr_debug.diagnostic.identity",
        "ocr_debug.diagnostic.backend_line",
        "ocr_debug.diagnostic.observation_line",
        "ocr_debug.diagnostic.error_unavailable",
        "ocr_debug.diagnostic.backend.success",
        "ocr_debug.diagnostic.backend.failed",
        "ocr_debug.diagnostic.backend.cancelled",
        "ocr_debug.diagnostic.backend.not_executed",
        "ocr_debug.diagnostic.observation.not_run",
        "ocr_debug.diagnostic.observation.changed",
        "ocr_debug.diagnostic.observation.no_change",
        "ocr_debug.diagnostic.observation.text_present",
        "ocr_debug.diagnostic.observation.text_missing",
        "ocr_debug.diagnostic.observation.unavailable",
    ]
    for locale in ("zh_TW", "en", "ja"):
        data = json.loads((_ROOT / "i18n" / f"{locale}.json").read_text(encoding="utf-8"))
        assert all(data.get(key) for key in keys), locale
