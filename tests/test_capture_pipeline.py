"""截圖管線與視窗幾何測試（全 mock，不需真視窗/螢幕）。

主循環每幀熱路徑：`get_window_rect_hwnd()`＋`capture(rect/hwnd)` 的存在理由是
避開 pygetwindow 逐視窗列舉標題（跨行程同步送訊、持 GIL，曾阻塞 145ms/幀）。
`_pad_to_full()` 是客戶區影像補黑邊的座標數學（見 TECHNICAL.md「GIL 凍結兩案」）。
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import threading
import types

import numpy as np
import pytest

from _loader import load_sibling

_shot = load_sibling("screenshot", "core/01_screenshot.py")
_pipe = load_sibling("capture_pipeline", "core/17_capture_pipeline.py")
_pw = load_sibling("print_window", "core/15_print_window.py")


class _FakeUser32:
    """只實作 get_window_rect_hwnd 用到的兩個 API。"""

    def __init__(self, iconic=False, rect=(10, 20, 110, 220), ok=True):
        self.iconic = iconic
        self.rect = rect
        self.ok = ok
        self.rect_calls = 0

    def IsIconic(self, hwnd):
        return self.iconic

    def GetWindowRect(self, hwnd, ref):
        self.rect_calls += 1
        if not self.ok:
            return False
        r = ctypes.cast(ref, ctypes.POINTER(wintypes.RECT)).contents
        r.left, r.top, r.right, r.bottom = self.rect
        return True


def test_get_window_rect_hwnd_reads_rect(monkeypatch):
    fake = _FakeUser32()
    monkeypatch.setattr(_shot, "_user32", fake)
    assert _shot.get_window_rect_hwnd(1234) == {"x": 10, "y": 20, "w": 100, "h": 200}
    assert fake.rect_calls == 1


def test_get_window_rect_hwnd_none_on_zero_iconic_or_failure(monkeypatch):
    monkeypatch.setattr(_shot, "_user32", _FakeUser32())
    assert _shot.get_window_rect_hwnd(0) is None
    assert _shot.get_window_rect_hwnd(None) is None

    iconic = _FakeUser32(iconic=True)
    monkeypatch.setattr(_shot, "_user32", iconic)
    assert _shot.get_window_rect_hwnd(1234) is None, "最小化視窗應視同不可用"
    assert iconic.rect_calls == 0, "已最小化就不必再問矩形"

    monkeypatch.setattr(_shot, "_user32", _FakeUser32(ok=False))
    assert _shot.get_window_rect_hwnd(1234) is None


def test_capture_uses_hwnd_rect_without_title_lookup(monkeypatch):
    monkeypatch.setattr(_shot, "get_window_rect", lambda title: pytest.fail("不應列舉標題"))
    monkeypatch.setattr(
        _shot, "get_window_rect_hwnd", lambda hwnd: {"x": 0, "y": 0, "w": 4, "h": 4}
    )
    seen = []
    monkeypatch.setattr(
        _shot, "_capture_mss", lambda title, rect: seen.append(rect) or np.ones((4, 4, 3), np.uint8)
    )
    monkeypatch.setattr(_shot, "_capture_dxcam", lambda title, rect: pytest.fail("不該走 dxcam"))

    img = _shot.capture("遊戲視窗", hwnd=999)
    assert img.shape == (4, 4, 3)
    assert seen == [{"x": 0, "y": 0, "w": 4, "h": 4}]


def test_capture_uses_provided_rect_directly(monkeypatch):
    monkeypatch.setattr(_shot, "get_window_rect", lambda title: pytest.fail("不應列舉標題"))
    monkeypatch.setattr(
        _shot, "get_window_rect_hwnd", lambda hwnd: pytest.fail("有 rect 不該問 hwnd")
    )
    monkeypatch.setattr(_shot, "_capture_mss", lambda title, rect: np.full((6, 8, 3), 3, np.uint8))
    img = _shot.capture("t", {"x": 1, "y": 2, "w": 8, "h": 6})
    assert img.shape == (6, 8, 3)


def test_capture_none_when_rect_unavailable(monkeypatch):
    monkeypatch.setattr(_shot, "get_window_rect", lambda title: None)
    monkeypatch.setattr(_shot, "_capture_mss", lambda title, rect: pytest.fail("無矩形不該截圖"))
    assert _shot.capture("t") is None


def test_capture_falls_back_to_dxcam_when_mss_returns_none(monkeypatch):
    monkeypatch.setattr(_shot, "get_window_rect", lambda title: {"x": 0, "y": 0, "w": 4, "h": 4})
    monkeypatch.setattr(_shot, "_capture_mss", lambda title, rect: None)
    monkeypatch.setattr(
        _shot, "_capture_dxcam", lambda title, rect: np.full((4, 4, 3), 7, np.uint8)
    )
    assert _shot.capture("t")[0, 0, 0] == 7


class _FakeGrab:
    def __init__(self, arr):
        self._arr = arr

    def __array__(self, dtype=None, copy=None):
        return self._arr if dtype is None else self._arr.astype(dtype)


class _FakeMSS:
    def __init__(self, arr, monitor):
        self._arr = arr
        self.monitors = [{}, monitor]
        self.region = None

    def grab(self, region):
        self.region = region
        return _FakeGrab(self._arr)


def test_pad_to_window_noop_when_full_size():
    img = np.ones((6, 8, 3), np.uint8)
    assert _shot._pad_to_window(img, {"x": 0, "y": 0, "w": 8, "h": 6}, 0, 0) is img


def test_capture_mss_pads_left_clipped_window(monkeypatch):
    """視窗左側在螢幕外：影像必須補回全視窗尺寸，內容貼在正確的視窗座標。"""
    grabbed = np.full((40, 50, 4), 7, np.uint8)
    fake = _FakeMSS(grabbed, {"left": 0, "top": 0, "width": 100, "height": 100})
    monkeypatch.setattr(_shot, "_get_mss", lambda: fake)

    img = _shot._capture_mss("t", {"x": -20, "y": 0, "w": 70, "h": 40})

    assert fake.region == {"left": 0, "top": 0, "width": 50, "height": 40}
    assert img.shape == (40, 70, 3)
    assert (img[:, 20:] == 7).all(), "可見內容應位移 +20 對齊視窗座標"
    assert img[:, :20].max() == 0, "螢幕外區域補黑"


def test_capture_mss_pads_top_clipped_window(monkeypatch):
    grabbed = np.full((30, 40, 4), 9, np.uint8)
    fake = _FakeMSS(grabbed, {"left": 0, "top": 0, "width": 100, "height": 100})
    monkeypatch.setattr(_shot, "_get_mss", lambda: fake)

    img = _shot._capture_mss("t", {"x": 0, "y": -10, "w": 40, "h": 40})

    assert fake.region == {"left": 0, "top": 0, "width": 40, "height": 30}
    assert img.shape == (40, 40, 3)
    assert (img[10:] == 9).all()
    assert img[:10].max() == 0


def test_capture_foreground_falls_back_to_client_capture_and_pads(monkeypatch):
    assert _pipe._screenshot is _shot, "管線與測試須共用同一模組物件，patch 才生效"
    monkeypatch.setattr(_shot, "capture", lambda title, rect=None, hwnd=None: None)
    monkeypatch.setattr(
        _shot, "capture_window_content", lambda title: np.full((4, 6, 3), 5, np.uint8)
    )
    padded = np.zeros((6, 8, 3), np.uint8)
    monkeypatch.setattr(_pipe, "_pad_to_full", lambda img, title: padded)
    assert _pipe._capture_foreground("t") is padded


def test_pad_to_full_places_client_at_chrome_offset(monkeypatch):
    monkeypatch.setattr(_shot, "get_window_rect", lambda title: {"x": 0, "y": 0, "w": 8, "h": 6})
    monkeypatch.setattr(_shot, "get_window_client_offset", lambda title: (1, 2))
    client = np.full((4, 6, 3), 9, np.uint8)

    out = _pipe._pad_to_full(client, "t")

    assert out.shape == (6, 8, 3)
    assert (out[2:6, 1:7] == 9).all(), "客戶區應貼在 chrome offset 處"
    assert out[:2].max() == 0 and out[:, :1].max() == 0 and out[:, 7:].max() == 0


def test_pad_to_full_noop_when_already_full_size(monkeypatch):
    monkeypatch.setattr(_shot, "get_window_rect", lambda title: {"x": 0, "y": 0, "w": 8, "h": 6})
    monkeypatch.setattr(
        _shot, "get_window_client_offset", lambda title: pytest.fail("尺寸相符不該查")
    )
    img = np.ones((6, 8, 3), np.uint8)
    assert _pipe._pad_to_full(img, "t") is img


def test_capture_frame_dispatches_by_mode(monkeypatch):
    seen = []
    monkeypatch.setattr(
        _pipe,
        "_capture_foreground",
        lambda title, rect=None, hwnd=None: seen.append(("fg", rect, hwnd)) or "fg",
    )
    monkeypatch.setattr(
        _pipe, "_capture_background", lambda title, hwnd: seen.append(("bg", hwnd)) or "bg"
    )

    assert _pipe.capture_frame("frida", "t", hwnd=7) == "bg"
    assert _pipe.capture_frame("hybrid", "t", hwnd=7, rect={"x": 0}) == "bg"
    assert _pipe.capture_frame("pynput", "t", hwnd=7, rect={"x": 0}) == "fg"
    assert seen == [("bg", 7), ("bg", 7), ("fg", {"x": 0}, 7)]


def test_is_black_capture_detects_zero_bitmap():
    assert _pw.is_black_capture(None) is False
    assert _pw.is_black_capture(np.zeros((0, 0, 3), np.uint8)) is False
    assert _pw.is_black_capture(np.zeros((4, 4, 3), np.uint8)) is True
    assert _pw.is_black_capture(np.zeros((4, 4, 3), np.uint8) + 1) is False


def test_slow_capture_log_is_rate_limited(monkeypatch, caplog):
    now = [100.0]
    monkeypatch.setattr(_pw, "time", types.SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(_pw, "_last_slow_capture_log", 0.0)

    with caplog.at_level(logging.WARNING, logger=_pw._log.name):
        _pw._log_slow_capture(1, 10, 10, 600, 550, 40)
        _pw._log_slow_capture(1, 10, 10, 700, 650, 40)
        now[0] += _pw._SLOW_CAPTURE_LOG_SEC + 1
        _pw._log_slow_capture(1, 10, 10, 800, 750, 40)

    slow_logs = [r.getMessage() for r in caplog.records if "PrintWindow 擷取過慢" in r.getMessage()]
    assert len(slow_logs) == 2
    assert "PrintWindow=750ms" in slow_logs[-1]


def test_timed_capture_returns_result(monkeypatch):
    frame = np.ones((2, 2, 3), np.uint8)
    monkeypatch.setattr(_pipe, "capture_frame", lambda *a, **k: frame)
    cap = _pipe.TimedCapture()
    try:
        img, timed_out = cap.capture("frida", "t", timeout=1.0)
        assert img is frame
        assert timed_out is False
    finally:
        cap.close()


def test_timed_capture_timeout_does_not_pile_up_requests(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    frame = np.ones((2, 2, 3), np.uint8)
    calls = []

    def slow(*_args, **_kwargs):
        calls.append(1)
        started.set()
        release.wait(2.0)
        return frame

    monkeypatch.setattr(_pipe, "capture_frame", slow)
    cap = _pipe.TimedCapture()
    try:
        img, timed_out = cap.capture("frida", "t", timeout=0.05)
        assert img is None and timed_out
        assert started.wait(1.0)

        img, timed_out = cap.capture("frida", "t", timeout=0.05)
        assert img is None and timed_out
        assert len(calls) == 1, "worker busy 時不應再排入第二個 PrintWindow"

        release.set()
        img, timed_out = cap.capture("frida", "t", timeout=1.0)
        assert img is frame and timed_out is False
        assert len(calls) == 1
    finally:
        release.set()
        cap.close()


def test_timed_capture_fresh_discards_pending_result(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    old_frame = np.zeros((2, 2, 3), np.uint8)
    new_frame = np.ones((2, 2, 3), np.uint8)
    calls = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            started.set()
            release.wait(2.0)
            return old_frame
        return new_frame

    monkeypatch.setattr(_pipe, "capture_frame", fake)
    cap = _pipe.TimedCapture()
    try:
        img, timed_out = cap.capture("frida", "t", timeout=0.01)
        assert img is None and timed_out
        assert started.wait(1.0)

        release.set()
        img, timed_out = cap.capture("frida", "t", timeout=1.0, fresh=True)
        assert img is new_frame and timed_out is False
        assert len(calls) == 2
    finally:
        release.set()
        cap.close()


def test_timed_capture_close_wakes_waiter(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    frame = np.ones((2, 2, 3), np.uint8)

    def slow(*_args, **_kwargs):
        started.set()
        release.wait(2.0)
        return frame

    monkeypatch.setattr(_pipe, "capture_frame", slow)
    cap = _pipe.TimedCapture()
    result = []
    waiter = threading.Thread(target=lambda: result.append(cap.capture("frida", "t", timeout=5.0)))
    waiter.start()
    try:
        assert started.wait(1.0)
        cap.close()
        waiter.join(1.0)
        assert result == [(None, False)]
    finally:
        release.set()
        cap.close()
