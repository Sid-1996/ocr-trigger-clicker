import logging
import sys
import threading
from collections import OrderedDict, deque
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def make_main_loop():
    """Bare MainLoop instance bypassing __init__, with all required attrs.

    共用 factory：test_main_loop / test_prematch_equiv 共用，避免 50 行重複。
    MainLoop.__init__ 新增屬性時，必須同步此處（這是刻意的壞掉信號）。
    """
    from _loader import load_sibling

    _ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
    _perf = load_sibling("performance_monitor", "core/10_performance_monitor.py")
    ml = _ml_mod.MainLoop.__new__(_ml_mod.MainLoop)
    ml._rules_path = ""
    ml._window_title = "測試視窗"
    ml._window_hwnd = None
    ml._dpi_scale = 1.0
    ml._interval = 0.5
    ml._rule_pointer = 0
    ml._rules = []
    ml._groups = []
    ml._active_group_ids = []
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._rule_map = {}
    ml._group_rounds_completed = {}
    ml._fail_since = {}
    ml._rules_lock = threading.RLock()
    ml._window_lock = threading.RLock()
    ml._process_counter = 0
    ml._rules_dirty = False
    ml._tracking_hwnd = None
    ml._tool_hwnd = None
    ml._verbose = False
    ml._prev_frame = None
    ml._frame_diff_ratio = 0.0
    ml._has_detect_rules = False
    ml._frame_ocr_cache = {}
    ml._ocr_cache_hits = 0
    ml._xframe_ocr_cache = OrderedDict()
    ml._xframe_ocr_cache_max = 64
    ml._logger = logging.getLogger("main_loop_test")
    ml._stop_event = threading.Event()
    ml._pause_event = threading.Event()
    ml._emergency_event = threading.Event()
    ml._perf = _perf.PerformanceMonitor(max_cps=5)
    ml._rule_config_ctrl = type(
        "FakeRuleConfig", (), {"get_setting": lambda self, win, key="interaction_mode": "pynput"}
    )()
    ml._execution_log = deque(maxlen=10)
    ml._last_exec_log = {}
    ml._rule_completed = set()
    ml._last_completed_log = {}
    ml._action_log_ts = {}
    ml._match_image_warn_counter = {}
    ml._detect_warn_counter = {}
    ml._black_streak = 0
    ml._prematch_pool = None
    ml.on_error = None
    ml.on_warning = None
    ml.on_info = None
    ml.on_window_lost = None
    ml.on_emergency = None
    ml._send_click = lambda *a, **k: True
    ml._send_key = lambda *a, **k: True
    ml._send_scroll = lambda *a, **k: True
    ml._activate_window = lambda *a, **k: True
    return ml


@pytest.fixture
def tmp_tasks_dir(monkeypatch, tmp_path):
    """Patch get_tasks_dir to use a temporary directory."""
    import core.task_management as _tasks

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    monkeypatch.setattr(_tasks, "get_tasks_dir", lambda: tasks_dir)
    return tasks_dir
