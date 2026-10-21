import ctypes
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

_rec = load_sibling("recorder", "core/19_recorder.py")


def test_virtual_abs_matches_windows_normalization():
    assert _rec._virtual_abs(100, 100, {"x": 0, "y": 0, "w": 1920, "h": 1080}) == (3415, 6073)
    assert _rec._virtual_abs(-1900, 100, {"x": -1920, "y": 0, "w": 3840, "h": 1080}) == (
        341,
        6073,
    )


def test_replay_move_flags_use_virtual_desktop():
    assert _rec._MOVE_FLAGS & _rec.MOUSEEVENTF_VIRTUALDESK
    assert _rec._MOVE_FLAGS & _rec.MOUSEEVENTF_ABSOLUTE


def test_click_passes_through_when_other_window_is_on_top(monkeypatch):
    rec = _rec.Recorder()
    rec._hwnd = 100
    monkeypatch.setattr(_rec, "_window_root", lambda hwnd: hwnd)

    monkeypatch.setattr(_rec, "_window_from_point", lambda x, y: 200)
    assert rec._is_target_click(10, 10) is False

    monkeypatch.setattr(_rec, "_window_from_point", lambda x, y: 101)
    monkeypatch.setattr(
        _rec,
        "_window_root",
        lambda hwnd: 100 if hwnd in (100, 101) else hwnd,
    )
    assert rec._is_target_click(10, 10) is True

    monkeypatch.setattr(_rec, "_window_from_point", lambda x, y: 0)
    assert rec._is_target_click(10, 10) is False


def test_non_target_down_clears_stale_blocked_button(monkeypatch):
    rec = _rec.Recorder()
    rec._hwnd = 100
    rec._running = True
    rec._blocked_buttons.add("left")
    monkeypatch.setattr(rec, "_in_window", lambda x, y: False)

    info = _rec._MSLLHOOKSTRUCT()
    info.pt.x, info.pt.y = 10, 10
    info.dwExtraInfo = 0
    lparam = ctypes.cast(ctypes.pointer(info), ctypes.c_void_p).value

    rec._hook_proc_cb(0, _rec.WM_LBUTTONDOWN, lparam)

    assert rec._blocked_buttons == set()
