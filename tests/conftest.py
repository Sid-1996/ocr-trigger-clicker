import logging
import os
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
    ml._frame_chrome = None
    ml._frame_client_size = None
    ml._frame_count = 0
    ml._phase_sums = dict.fromkeys(
        (
            "iter",
            "cpu",
            "cpu_thr",
            "capture",
            "pre",
            "pre_cpu",
            "pre_thr",
            "pre_set",
            "pre_lock",
            "pre_minz",
            "pre_rect",
            "pre_fg",
            "mid",
            "total",
            "prewarm",
            "background",
            "groups",
        ),
        0.0,
    )
    ml._phase_frames = 0
    ml._phase_since = 0.0
    ml._notified_conditions = set()
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
    ml._tmpl_cache = OrderedDict()
    ml._tmpl_cache_max = 64
    ml._logger = logging.getLogger("main_loop_test")
    ml._stop_event = threading.Event()
    ml._pause_event = threading.Event()
    ml._emergency_event = threading.Event()
    ml._perf = _perf.PerformanceMonitor(max_cps=5)
    ml._config_store = type(
        "FakeConfigStore", (), {"get": lambda self, key="interaction_mode": "pynput"}
    )()
    ml._execution_log = deque(maxlen=100)
    ml._quiet_names = set()
    ml._last_exec_log = {}
    ml._rule_completed = set()
    ml._last_completed_log = {}
    ml._action_log_ts = {}
    ml._match_image_warn_counter = {}
    ml._detect_warn_counter = {}
    ml._sum_warn_counter = {}
    ml._sum_candidate = {}
    ml._last_sum_report = {}
    ml._sum_active_rule = None
    ml._sum_seen = None
    ml._slow_loop_warned = False
    ml._frame_waited_ms = 0.0
    ml._verify_blocked_ms = 0.0
    ml._black_since = None
    ml._black_next_verify = 0.0
    ml._black_warned = False
    ml._black_logged = False
    ml._last_frida_err_ts = 0.0
    ml._FRIDA_ERR_THROTTLE_SEC = 30.0
    ml._prematch_pool = None
    ml.on_error = None
    ml.on_warning = None
    ml.on_bg_fail = None
    ml.on_black_fail = None
    ml.on_info = None
    ml.on_sum = None
    ml.on_sum_hide = None
    ml.on_window_lost = None
    ml.on_window_recovered = None
    ml.on_emergency = None
    # Preflight cache 狀態：走正式 MainLoop 的同一個初始化入口，避免欄位漂移
    ml._init_preflight_state()
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


# ── Step Editor 整合測試（Phase 2-4a）───────────────────────────────────────
#
# 本區塊只提供「測試用環境」，不修改任何產品程式碼。
# 隔離方式全部走既有鉤子：
#   * core/_paths.py:14-19 的 _appdata_path() 每次呼叫都讀 OCR_TRIGGER_DATA，
#     因此只要設定環境變數即可把設定檔／任務檔完全隔離到 tmp_path。
#   * deferred init / 版本檢查 / 全域熱鍵 / QApplication.quit 都會對外產生
#     副作用（連網、列舉視窗、動到 hotkey registry、結束應用程式），
#     在測試中以 monkeypatch 換掉。


class _CallRecorder:
    """類別層級呼叫計數器。"""

    def __init__(self):
        self.counts: dict[str, int] = {}

    def hit(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    def get(self, key: str) -> int:
        return self.counts.get(key, 0)

    def reset(self) -> None:
        for key in list(self.counts):
            self.counts[key] = 0


@pytest.fixture(scope="session")
def qt_app():
    """Session 級 QApplication（offscreen）。既有測試各自建構時會重用同一實例。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """把應用資料（設定檔、任務檔）隔離到 tmp_path。"""
    data_dir = tmp_path / "appdata"
    monkeypatch.setenv("OCR_TRIGGER_DATA", str(data_dir))
    return data_dir


@pytest.fixture
def rule_engine():
    """core/04_rule_engine.py 的 sibling 模組（與 GUI 使用的同一份）。"""
    from _loader import load_sibling

    return load_sibling("rule_engine", "core/04_rule_engine.py")


@pytest.fixture
def make_step(rule_engine):
    """建立 Step 物件（使用產品自己的 dataclass）。"""

    def _make(step_type: str, **params):
        return rule_engine.Step(type=step_type, params=dict(params))

    return _make


@pytest.fixture
def make_rule(rule_engine):
    """建立 Rule 物件。"""

    def _make(rule_id: str, name: str, steps=None, enabled: bool = True):
        return rule_engine.Rule(id=rule_id, name=name, enabled=enabled, steps=list(steps or []))

    return _make


@pytest.fixture
def write_task(isolated_data_dir, rule_engine):
    """在隔離目錄建立任務檔（使用產品自己的原子寫入 API）。"""

    def _write(name: str, rules, groups=None) -> str:
        tasks_dir = isolated_data_dir / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        path = str(tasks_dir / f"{name}.json")
        ok = rule_engine.save_task_with_groups(rules, list(groups or []), path)
        assert ok, f"建立任務檔失敗：{path}"
        return path

    return _write


@pytest.fixture
def call_recorder(monkeypatch):
    """在「類別層級」安裝呼叫計數器。

    必須在 MainWindow 建構前安裝：steps_changed.connect(self._on_steps_changed)
    與 currentItemChanged.connect(self._on_rule_selected) 都在 __init__ 內即完成
    綁定，事後再替換 instance 屬性不會被 signal 採用。
    """
    from _loader import load_sibling

    gui = load_sibling("gui_main", "gui/06_gui_main.py")
    recorder = _CallRecorder()
    for cls, name in (
        (gui.MainWindow, "_save_current_rule"),
        (gui.MainWindow, "_refresh_rule_list"),
        (gui.MainWindow, "_on_rule_selected"),
        (gui.MainWindow, "_show_rule_detail"),
        (gui.MainWindow, "_flush_save"),
        (gui._StepListWidget, "_rebuild"),
        (gui._StepListWidget, "set_steps"),
        (gui._StepListWidget, "_collapse"),
        (gui._StepListWidget, "_toggle_expand"),
        (gui._StepListWidget, "_delete_step"),
        (gui._StepListWidget, "_move_up"),
        (gui._StepListWidget, "_move_down"),
    ):
        orig = getattr(cls, name)
        key = f"{cls.__name__}.{name}"
        recorder.counts.setdefault(key, 0)

        def make(orig=orig, key=key):
            def wrapper(self, *args, **kwargs):
                recorder.hit(key)
                return orig(self, *args, **kwargs)

            return wrapper

        monkeypatch.setattr(cls, name, make())
    return recorder


@pytest.fixture
def real_mainwindow(qt_app, isolated_data_dir, call_recorder, monkeypatch):
    """真實 MainWindow（offscreen）；teardown 收掉背景執行緒與計時器。"""
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QApplication

    from _loader import load_sibling

    gui = load_sibling("gui_main", "gui/06_gui_main.py")

    # 延遲初始化會連網查版本、列舉所有視窗、載入真實任務 → 測試不需要
    monkeypatch.setattr(gui.MainWindow, "_deferred_init", lambda self: None)
    monkeypatch.setattr(gui.MainWindow, "_check_version", lambda self, force=False: None)
    # 結束時解除全域熱鍵會碰到真實 hotkey registry
    monkeypatch.setattr(gui, "_hk_unregister", lambda hwnd: None)
    # 退出流程不應真的結束 QApplication
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: None))
    # 背景效能採樣執行緒不是本測試目標。
    # 另注意：tests/test_hybrid_input.py:12 以 importlib.import_module 載入
    # core/10_performance_monitor.py，與 load_sibling 形成「同一檔案兩份實例」，
    # 兩份的 ctypes _FILETIME 類別不同，會讓 _GetProcessTimes 的
    # POINTER(_FILETIME) argtypes 檢查失敗並使採樣執行緒在第一次迴圈就拋例外。
    # 這是測試套件的載入慣例問題（非產品缺陷，單一載入時正常運作），
    # 此處直接不啟動採樣執行緒，避免污染測試輸出。
    perf_mod = load_sibling("performance_monitor", "core/10_performance_monitor.py")
    monkeypatch.setattr(perf_mod.PerformanceMonitor, "start", lambda self: None)

    win = gui.MainWindow()
    win._perf_timer.stop()
    try:
        yield win
    finally:
        for name in ("_save_timer", "_status_timer", "_perf_timer"):
            timer = getattr(win, name, None)
            if timer is not None:
                timer.stop()
        try:
            win._bg_perf.stop()
        except Exception:
            pass
        loop = getattr(win, "_loop", None)
        if loop is not None:
            loop.stop()
        win.deleteLater()
        # DeferredDelete 必須用 sendPostedEvents 才會被處理（processEvents 不會）
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()
