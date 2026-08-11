"""滑鼠示範錄製器 — 全域滑鼠攔截 + 動作前截圖 + 前景重送。

錄製期間攔截目標視窗內的滑鼠點擊：先截取「動作前」畫面（輸入被擋住、遊戲還沒反應，
保證畫面是觸發前狀態），再把點擊以 SendInput（帶 magic dwExtraInfo）重送給前景的
目標視窗，維持正常的視窗操控節奏。

停止後輸出 session 資料：events.json（事件序列）+ frames/（逐事件事前截圖）。
後處理（core/20_recorder_convert.py）只讀這份 session 資料轉成規則，與本模組零耦合。

無 Qt 依賴；GUI 層透過 load_sibling 載入，跨執行緒以 callback 回報。
"""

import ctypes
import json
import logging
import threading
import time
from ctypes import wintypes
from pathlib import Path

import cv2

from _loader import load_sibling

_log = logging.getLogger(__name__)

_screenshot = load_sibling("screenshot", "core/01_screenshot.py")
_pipeline = load_sibling("capture_pipeline", "core/17_capture_pipeline.py")

# ── Win32 常數 ──
WH_MOUSE_LL = 14

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_RBUTTONDBLCLK = 0x0206
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MBUTTONDBLCLK = 0x0209
WM_QUIT = 0x0012

# 按鍵事件 → 引擎 button 名稱
_DOWN = {
    WM_LBUTTONDOWN: "left",
    WM_RBUTTONDOWN: "right",
    WM_MBUTTONDOWN: "middle",
    WM_LBUTTONDBLCLK: "left",
    WM_RBUTTONDBLCLK: "right",
    WM_MBUTTONDBLCLK: "middle",
}
_UP = {
    WM_LBUTTONUP: "left",
    WM_RBUTTONUP: "right",
    WM_MBUTTONUP: "middle",
}

# 重送用 magic dwExtraInfo：hook 看到即直通，防自錄迴圈
_REPLAY_MAGIC = 0x4F435452  # "OCTR"

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000

_REPLAY_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79

_INPUT_MOUSE = 0

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (HANDLE)-4
_DPI_PMV2 = ctypes.c_void_p(-4)

_JPEG_QUALITY = 92


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", _POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


_LowLevelMouseProc = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    _LowLevelMouseProc,
    wintypes.HINSTANCE,
    wintypes.DWORD,
]
_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_user32.CallNextHookEx.restype = ctypes.c_ssize_t
_user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
_user32.GetMessageW.restype = wintypes.BOOL
_user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_user32.PostThreadMessageW.restype = wintypes.BOOL
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
_user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL


def _virtual_abs(x: int, y: int, bounds: dict) -> tuple[int, int]:
    """螢幕絕對座標 → SendInput 虛擬桌面歸一化座標 (0..65535)。"""
    if bounds["w"] <= 1 or bounds["h"] <= 1:
        return 0, 0
    ax = int((x - bounds["x"]) * 65535 / (bounds["w"] - 1))
    ay = int((y - bounds["y"]) * 65535 / (bounds["h"] - 1))
    return max(0, min(65535, ax)), max(0, min(65535, ay))


def _send_input(inputs: list[_INPUT]) -> None:
    if not inputs:
        return
    arr = (_INPUT * len(inputs))(*inputs)
    _user32.SendInput(len(inputs), ctypes.cast(arr, ctypes.POINTER(_INPUT)), ctypes.sizeof(_INPUT))


def _virtual_screen_bounds() -> dict:
    return {
        "x": _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN),
        "y": _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN),
        "w": _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN),
        "h": _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN),
    }


class Recorder:
    """一次錄製會話：安裝全域滑鼠 hook、攔截目標視窗點擊、截圖、重送。"""

    def __init__(self):
        self._title = ""
        self._hwnd = 0
        self._session_dir: Path | None = None
        self._frames_dir: Path | None = None
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = None
        self._hook_proc = None
        self._stop_evt = threading.Event()
        self._running = False
        self._blocked_buttons: set[str] = set()
        self._frame_seq = 0
        self._on_event = None
        self._on_error = None

    # ── 對外 API ──

    def start(self, title: str, hwnd: int, session_dir, on_event=None, on_error=None) -> bool:
        if self._running or (self._thread and self._thread.is_alive()):
            return False
        self._title = title
        self._hwnd = int(hwnd)
        self._session_dir = Path(session_dir)
        self._frames_dir = self._session_dir / "frames"
        self._frames_dir.mkdir(parents=True, exist_ok=True)
        self._events = []
        self._blocked_buttons = set()
        self._frame_seq = 0
        self._stop_evt = threading.Event()
        self._on_event = on_event
        self._on_error = on_error
        self._hook = None
        self._hook_proc = None
        self._thread = threading.Thread(target=self._run, name="recorder-hook", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if not self._running and not (self._thread and self._thread.is_alive()):
            return
        self._stop_evt.set()
        tid = self._thread_id
        deadline = time.monotonic() + 1.0
        while not tid and time.monotonic() < deadline:
            time.sleep(0.02)
            tid = self._thread_id
        if tid:
            _user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=5)
        self._write_session()

    @property
    def is_recording(self) -> bool:
        return self._running

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self._events)

    @property
    def title(self) -> str:
        return self._title

    # ── hook 執行緒 ──

    def _run(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        # 確保 hook 執行緒的 DPI awareness 與截圖/視窗座標一致（實體像素）。
        # Qt 已設 PMv2 時會回 FALSE(ERROR_ACCESS_DENIED)，屬預期。
        try:
            _user32.SetProcessDpiAwarenessContext(_DPI_PMV2)
        except Exception:
            pass
        self._hook_proc = _LowLevelMouseProc(self._hook_proc_cb)
        hook = _user32.SetWindowsHookExW(WH_MOUSE_LL, self._hook_proc, None, 0)
        if not hook:
            err = ctypes.get_last_error()
            self._notify_error(f"錄製失敗：無法安裝滑鼠攔截 hook (error={err})")
            return
        self._hook = hook
        self._running = True
        _log.info("錄製開始: %s", self._title)
        try:
            msg = wintypes.MSG()
            while not self._stop_evt.is_set():
                ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook:
                _user32.UnhookWindowsHookEx(self._hook)
                self._hook = None
            self._running = False
            _log.info("錄製停止: %s (%d 事件)", self._title, len(self._events))

    def _hook_proc_cb(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code < 0:
            return _user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
        try:
            info = ctypes.cast(l_param, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
            msg = int(w_param)
            # 自己的重送 → 直通（防自錄迴圈）
            if info.dwExtraInfo == _REPLAY_MAGIC:
                return _user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
            if not self._running:
                return _user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
            button = _DOWN.get(msg)
            if button is not None:
                if self._in_window(info.pt.x, info.pt.y):
                    self._blocked_buttons.add(button)
                    self._handle_down(button, info.pt.x, info.pt.y)
                    return 1  # 阻擋：遊戲不會直接收到原始事件
                return _user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
            up_button = _UP.get(msg)
            if up_button is not None:
                # 只有對應 down 被我們攔下的 up 才吞掉，避免誤吞外部拖入的 up
                if up_button in self._blocked_buttons:
                    self._blocked_buttons.discard(up_button)
                    return 1
                return _user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
        except Exception:
            _log.exception("hook proc 異常")
        return _user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    # ── 事件處理 ──

    def _in_window(self, sx: int, sy: int) -> bool:
        rect = _RECT()
        if not _user32.GetWindowRect(self._hwnd, ctypes.byref(rect)):
            return False
        return rect.left <= sx < rect.right and rect.top <= sy < rect.bottom

    def _handle_down(self, button: str, sx: int, sy: int) -> None:
        # 前景漂移 → 重新激活目標視窗（罕見；重送才會打到對的窗）
        try:
            if _user32.GetForegroundWindow() != self._hwnd and not _user32.IsIconic(self._hwnd):
                _screenshot.activate_window(self._title)
        except Exception:
            _log.exception("重新激活目標視窗失敗")

        rect = _RECT()
        wx, wy = sx, sy
        if _user32.GetWindowRect(self._hwnd, ctypes.byref(rect)):
            wx = sx - rect.left
            wy = sy - rect.top

        frame_name = self._capture_pre_action()
        evt = {
            "t": round(time.time(), 3),
            "button": button,
            "wx": wx,
            "wy": wy,
        }
        if frame_name:
            evt["frame"] = frame_name
        with self._lock:
            self._events.append(evt)
            count = len(self._events)

        self._replay_click(button, sx, sy)

        cb = self._on_event
        if cb:
            try:
                cb(count)
            except Exception:
                _log.exception("on_event callback 異常")

    def _capture_pre_action(self) -> str | None:
        try:
            img = _pipeline.capture_frame("pynput", self._title, self._hwnd)
            if img is None or img.size == 0:
                return None
            self._frame_seq += 1
            name = f"{self._frame_seq:05d}.jpg"
            path = self._frames_dir / name
            cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
            return name
        except Exception:
            _log.exception("動作前截圖失敗")
            return None

    def _replay_click(self, button: str, sx: int, sy: int) -> None:
        flags = _REPLAY_FLAGS.get(button)
        if flags is None:
            return
        # 先移回記錄位置（使用者可能在截圖期間移動滑鼠），再送 down+up
        inputs = []
        ax, ay = _virtual_abs(sx, sy, _virtual_screen_bounds())
        move = _INPUT()
        move.type = _INPUT_MOUSE
        move.u.mi.dx, move.u.mi.dy = ax, ay
        move.u.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
        move.u.mi.dwExtraInfo = _REPLAY_MAGIC
        inputs.append(move)
        for flag in flags:
            inp = _INPUT()
            inp.type = _INPUT_MOUSE
            inp.u.mi.dwFlags = flag
            inp.u.mi.dwExtraInfo = _REPLAY_MAGIC
            inputs.append(inp)
        _send_input(inputs)

    def _write_session(self) -> None:
        if self._session_dir is None:
            return
        try:
            data = {
                "meta": {
                    "window_title": self._title,
                    "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                "events": self._events,
            }
            with open(self._session_dir / "events.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            _log.exception("寫入 events.json 失敗")

    def _notify_error(self, msg: str) -> None:
        _log.error(msg)
        cb = self._on_error
        if cb:
            try:
                cb(msg)
            except Exception:
                _log.exception("on_error callback 異常")


if __name__ == "__main__":
    print("=== Recorder Self-Check ===\n")

    b = _virtual_abs(100, 100, {"x": 0, "y": 0, "w": 1920, "h": 1080})
    assert b == (3413, 6214), b
    print("  [OK] _virtual_abs primary monitor")

    b2 = _virtual_abs(-1900, 100, {"x": -1920, "y": 0, "w": 3840, "h": 1080})
    assert b2 == (341, 6214), b2
    print("  [OK] _virtual_abs dual-monitor negative coords")

    b3 = _virtual_abs(0, 0, {"x": 0, "y": 0, "w": 0, "h": 0})
    assert b3 == (0, 0)
    print("  [OK] _virtual_abs degenerate bounds")

    b4 = _virtual_abs(5000, 5000, {"x": 0, "y": 0, "w": 1920, "h": 1080})
    assert b4 == (65535, 65535), b4
    print("  [OK] _virtual_abs clamp")

    flags = _REPLAY_FLAGS.get("left")
    assert flags is not None and len(flags) == 2
    print("  [OK] _REPLAY_FLAGS")

    print("\n=== All 5 checks passed ===")
