import ctypes
import threading
import time
from collections import deque
from ctypes import wintypes
from typing import Callable, Optional


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32
_psapi = ctypes.windll.psapi

_GetSystemTimes = _kernel32.GetSystemTimes
_GetSystemTimes.argtypes = [
    ctypes.POINTER(_FILETIME),
    ctypes.POINTER(_FILETIME),
    ctypes.POINTER(_FILETIME),
]

_GetProcessTimes = _kernel32.GetProcessTimes
_GetProcessTimes.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_FILETIME),
    ctypes.POINTER(_FILETIME),
    ctypes.POINTER(_FILETIME),
    ctypes.POINTER(_FILETIME),
]

_GetProcessMemoryInfo = _psapi.GetProcessMemoryInfo
_GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
    wintypes.DWORD,
]

_GetForegroundWindow = _user32.GetForegroundWindow
_GetForegroundWindow.restype = wintypes.HWND

_GetWindowThreadProcessId = _user32.GetWindowThreadProcessId
_GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

_GetSystemMetrics = _user32.GetSystemMetrics
_GetSystemMetrics.restype = ctypes.c_int
_GetSystemMetrics.argtypes = [ctypes.c_int]

_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79

_GetCurrentProcess = _kernel32.GetCurrentProcess
_GetCurrentProcess.restype = wintypes.HANDLE

def _ft_to_int(ft) -> int:
    return (ft.dwHighDateTime << 32) + ft.dwLowDateTime


def _filetime_now() -> int:
    ft = _FILETIME()
    _kernel32.GetSystemTimeAsFileTime(ctypes.byref(ft))
    return _ft_to_int(ft)


_CPU_INTERVAL = 0.5
_CPU_SAMPLES = 60
_FPS_WINDOW = 300
_CLICK_WINDOW = 50
_LATENCY_WINDOW = 100
_LOOP_WINDOW = 100
_OCR_FAIL_WINDOW = 100
_MEMORY_WARN_MB = 500
_CPU_WARN_PCT = 80.0
_CPU_WARN_DURATION = 10.0
_MAX_CPS = 5
_RATE_LIMIT_PENALTY_S = 2.0
_RATE_LIMIT_MAX_VIOLATIONS = 3
_RATE_LIMIT_WINDOW_S = 30.0


def get_screen_bounds() -> dict:
    x = _GetSystemMetrics(_SM_XVIRTUALSCREEN)
    y = _GetSystemMetrics(_SM_YVIRTUALSCREEN)
    w = _GetSystemMetrics(_SM_CXVIRTUALSCREEN)
    h = _GetSystemMetrics(_SM_CYVIRTUALSCREEN)
    return {"x": x, "y": y, "w": w, "h": h}


def is_coordinate_safe(x: int, y: int) -> bool:
    bounds = get_screen_bounds()
    return bounds["x"] <= x < bounds["x"] + bounds["w"] and bounds["y"] <= y < bounds["y"] + bounds["h"]


def is_window_foreground(hwnd: int) -> bool:
    return _GetForegroundWindow() == hwnd


class PerformanceMonitor:
    def __init__(self):
        self._lock = threading.Lock()

        self._cpu_samples: deque = deque(maxlen=_CPU_SAMPLES)
        self._fps_history: deque = deque(maxlen=_FPS_WINDOW)
        self._click_timestamps: deque = deque(maxlen=_CLICK_WINDOW)
        self._ocr_latency_samples: deque = deque(maxlen=_LATENCY_WINDOW)
        self._loop_time_samples: deque = deque(maxlen=_LOOP_WINDOW)
        self._ocr_fail_count = 0
        self._memory_mb: float = 0.0
        self._memory_peak_mb: float = 0.0
        self._loop_count = 0
        self._last_fps_sample = 0.0
        self._fps_cached: float = 0.0
        self._last_loop_time: float = 0.0

        self._cpu_above_threshold_since: Optional[float] = None
        self._cpu_warned = False
        self._memory_warned = False

        self._rate_violations = 0
        self._rate_violation_window_start = 0.0
        self._penalty_until = 0.0

        self._prev_idle = _FILETIME()
        self._prev_kernel = _FILETIME()
        self._prev_user = _FILETIME()
        self._cpu_initialized = False

        self._process_handle = _GetCurrentProcess()

        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.on_cpu_warn: Optional[Callable[[float], None]] = None
        self.on_memory_warn: Optional[Callable[[float], None]] = None
        self.on_rate_limit_exceeded: Optional[Callable[[], None]] = None

    # ── CPU 取樣 ──

    def _sample_cpu(self) -> Optional[float]:
        idle = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        if not _GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        if not self._cpu_initialized:
            self._prev_idle, self._prev_kernel, self._prev_user = idle, kernel, user
            self._cpu_initialized = True
            return 0.0
        idle_delta = _ft_to_int(idle) - _ft_to_int(self._prev_idle)
        kernel_delta = _ft_to_int(kernel) - _ft_to_int(self._prev_kernel)
        user_delta = _ft_to_int(user) - _ft_to_int(self._prev_user)
        total_delta = kernel_delta + user_delta
        self._prev_idle, self._prev_kernel, self._prev_user = idle, kernel, user
        if total_delta == 0:
            return None
        pct = (total_delta - idle_delta) / total_delta * 100.0
        return pct

    # ── 記憶體取樣 ──

    def _sample_memory(self) -> float:
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        if _GetProcessMemoryInfo(self._process_handle, ctypes.byref(counters), counters.cb):
            mb = counters.WorkingSetSize / (1024 * 1024)
            self._memory_peak_mb = max(self._memory_peak_mb, mb)
            return mb
        return 0.0

    # ── 公開記錄方法 ──

    def record_frame(self, ocr_ms: Optional[float] = None, loop_ms: Optional[float] = None):
        with self._lock:
            self._loop_count += 1
            now = time.monotonic()
            if self._last_fps_sample > 0:
                elapsed = now - self._last_fps_sample
                if elapsed >= 1.0:
                    self._fps_cached = self._loop_count / elapsed
                    self._fps_history.append(self._fps_cached)
                    self._loop_count = 0
                    self._last_fps_sample = now
                    self._update_resource_warnings()
            else:
                self._last_fps_sample = now
            if ocr_ms is not None:
                self._ocr_latency_samples.append(ocr_ms)
            if loop_ms is not None:
                self._loop_time_samples.append(loop_ms)
                self._last_loop_time = loop_ms

    def record_click(self):
        with self._lock:
            self._click_timestamps.append(time.monotonic())

    def record_ocr_failure(self):
        with self._lock:
            self._ocr_fail_count += 1

    def reset_ocr_failures(self):
        with self._lock:
            self._ocr_fail_count = 0

    # ── 速率限制 ──

    def check_rate_limit(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if now < self._penalty_until:
                return False
            cutoff = now - 1.0
            while self._click_timestamps and self._click_timestamps[0] < cutoff:
                self._click_timestamps.popleft()
            cps = len(self._click_timestamps)
            if cps > _MAX_CPS:
                self._rate_violations += 1
                if self._rate_violation_window_start == 0:
                    self._rate_violation_window_start = now
                elif now - self._rate_violation_window_start > _RATE_LIMIT_WINDOW_S:
                    self._rate_violations = 1
                    self._rate_violation_window_start = now
                self._penalty_until = now + _RATE_LIMIT_PENALTY_S
                if self._rate_violations >= _RATE_LIMIT_MAX_VIOLATIONS:
                    if self.on_rate_limit_exceeded:
                        self.on_rate_limit_exceeded()
                    self._rate_violations = 0
                    self._rate_violation_window_start = 0
                return False
            return True

    # ── 資源警告 ──

    def _update_resource_warnings(self):
        now = time.monotonic()

        cpu = self._cpu_samples[-1] if self._cpu_samples else 0.0
        if cpu >= _CPU_WARN_PCT and not self._cpu_warned:
            if self._cpu_above_threshold_since is None:
                self._cpu_above_threshold_since = now
            elif now - self._cpu_above_threshold_since >= _CPU_WARN_DURATION:
                self._cpu_warned = True
                if self.on_cpu_warn:
                    self.on_cpu_warn(cpu)
        elif cpu < _CPU_WARN_PCT:
            self._cpu_above_threshold_since = None
            self._cpu_warned = False

        if self._memory_mb >= _MEMORY_WARN_MB and not self._memory_warned:
            self._memory_warned = True
            if self.on_memory_warn:
                self.on_memory_warn(self._memory_mb)
        elif self._memory_mb < _MEMORY_WARN_MB:
            self._memory_warned = False

    # ── 取樣執行緒 ──

    def _poll_loop(self):
        while not self._stop_event.is_set():
            cpu = self._sample_cpu()
            with self._lock:
                if cpu is not None:
                    self._cpu_samples.append(cpu)
                self._memory_mb = self._sample_memory()
            self._stop_event.wait(_CPU_INTERVAL)

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    # ── 統計查詢 ──

    def get_stats(self) -> dict:
        with self._lock:
            cpu_avg = sum(self._cpu_samples) / len(self._cpu_samples) if self._cpu_samples else 0.0
            cpu_max = max(self._cpu_samples) if self._cpu_samples else 0.0
            ocr_avg = (
                sum(self._ocr_latency_samples) / len(self._ocr_latency_samples)
                if self._ocr_latency_samples
                else 0.0
            )
            ocr_max = max(self._ocr_latency_samples) if self._ocr_latency_samples else 0.0
            loop_avg = (
                sum(self._loop_time_samples) / len(self._loop_time_samples)
                if self._loop_time_samples
                else 0.0
            )
            loop_max = max(self._loop_time_samples) if self._loop_time_samples else 0.0
            click_rate = self._get_click_rate_raw()
            return {
                "fps": self._fps_cached,
                "cpu_pct": cpu_avg,
                "cpu_max": cpu_max,
                "memory_mb": self._memory_mb,
                "memory_peak_mb": self._memory_peak_mb,
                "ocr_avg_ms": ocr_avg,
                "ocr_max_ms": ocr_max,
                "loop_avg_ms": loop_avg,
                "loop_max_ms": loop_max,
                "click_rate": click_rate,
                "ocr_failures": self._ocr_fail_count,
            }

    def get_cpu_pct(self) -> float:
        with self._lock:
            return sum(self._cpu_samples) / len(self._cpu_samples) if self._cpu_samples else 0.0

    def get_memory_mb(self) -> float:
        with self._lock:
            return self._memory_mb

    def get_fps(self) -> float:
        with self._lock:
            return self._fps_cached

    def get_click_rate(self) -> float:
        with self._lock:
            return self._get_click_rate_raw()

    def _get_click_rate_raw(self) -> float:
        cutoff = time.monotonic() - 1.0
        return sum(1 for t in self._click_timestamps if t >= cutoff)

    def get_last_loop_time_ms(self) -> float:
        with self._lock:
            return self._last_loop_time

    def get_ocr_failures(self) -> int:
        with self._lock:
            return self._ocr_fail_count

    def reset_rate_limit(self):
        with self._lock:
            self._rate_violations = 0
            self._rate_violation_window_start = 0.0
            self._penalty_until = 0.0
