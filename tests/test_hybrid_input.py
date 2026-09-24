import importlib
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

_hybrid = importlib.import_module("core.19_hybrid_input")
_perf = importlib.import_module("core.10_performance_monitor")


def test_is_window_minimized_uses_iconic(monkeypatch):
    monkeypatch.setattr(_perf, "_IsIconic", lambda hwnd: hwnd == 42)
    assert _perf.is_window_minimized(42) is True
    assert _perf.is_window_minimized(7) is False
    assert _perf.is_window_minimized(0) is False


class _FakeUser32:
    def __init__(self, foreground=42, iconic=False):
        self.foreground = foreground
        self.iconic = iconic

    def GetForegroundWindow(self):
        return self.foreground

    def GetCursorPos(self, _point):
        return True

    def SetCursorPos(self, _x, _y):
        return True

    def IsWindow(self, hwnd):
        return hwnd == 42

    def IsIconic(self, hwnd):
        return hwnd == 42 and self.iconic

    def GetWindowThreadProcessId(self, _hwnd, _pid):
        return 1

    def AttachThreadInput(self, *_args):
        return True

    def SetForegroundWindow(self, hwnd):
        self.foreground = hwnd
        return True


def test_focus_guard_blocks_minimized_target(monkeypatch):
    monkeypatch.setattr(_hybrid, "_user32", _FakeUser32(iconic=True))
    monkeypatch.setattr(_hybrid.time, "sleep", lambda _seconds: None)

    with _hybrid.focus_guard("game", lambda _title: True, 42) as ready:
        assert ready is False


def test_focus_guard_blocks_failed_activation(monkeypatch):
    monkeypatch.setattr(_hybrid, "_user32", _FakeUser32())
    monkeypatch.setattr(_hybrid.time, "sleep", lambda _seconds: None)

    with _hybrid.focus_guard("game", lambda _title: False, 42) as ready:
        assert ready is False


def test_focus_guard_allows_foreground_target(monkeypatch):
    monkeypatch.setattr(_hybrid, "_user32", _FakeUser32())
    monkeypatch.setattr(_hybrid.time, "sleep", lambda _seconds: None)

    with _hybrid.focus_guard("game", lambda _title: True, 42) as ready:
        assert ready is True
