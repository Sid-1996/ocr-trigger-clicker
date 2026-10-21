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
