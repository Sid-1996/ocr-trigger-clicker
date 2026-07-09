import io
import logging
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import winreg
import zipfile
from pathlib import Path
from typing import Callable, Optional

_server: Optional[socket.socket] = None
_conn: Optional[socket.socket] = None
_ahk_process: Optional[subprocess.Popen] = None
_lock = threading.Lock()
_restart_lock = threading.Lock()
_heartbeat_event = threading.Event()
_initialized = False
_restart_fail_count = 0
_MAX_RESTART_ATTEMPTS = 3

_recv_buffers: dict[int, bytes] = {}


def _cleanup_recv_buffer(conn: socket.socket) -> None:
    _recv_buffers.pop(id(conn), None)


_AHK_DOWNLOAD_URL = (
    "https://github.com/AutoHotkey/AutoHotkey/releases/download/v2.0.26/AutoHotkey_2.0.26.zip"
)


def _ahk_data_dir() -> Path:
    try:
        from build import get_data_path

        return Path(get_data_path("ahk"))
    except ImportError:
        return Path.home() / "AppData" / "Roaming" / "ocr-trigger-clicker" / "ahk"


def _find_ahk() -> str:
    try:
        from build import get_resource_path

        p = Path(get_resource_path("clicker.ahk"))
        if p.exists():
            return str(p.resolve())
    except ImportError:
        pass
    candidates = [
        Path(__file__).resolve().parent.parent / "clicker.ahk",
        Path.cwd() / "clicker.ahk",
    ]
    for p in candidates:
        if p.exists():
            return str(p.resolve())
    return str(candidates[0])


def _recv_line(conn: socket.socket, timeout: float = 1.0) -> str:
    conn.settimeout(timeout)
    conn_id = id(conn)
    buf = _recv_buffers.pop(conn_id, b"")

    while True:
        idx = buf.find(b"\n")
        if idx != -1:
            line = buf[:idx]
            rest = buf[idx + 1 :]
            if rest:
                _recv_buffers[conn_id] = rest
            return line.decode("utf-8", errors="replace").strip()

        try:
            chunk = conn.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk

    if buf:
        _recv_buffers[conn_id] = buf
    return ""


def _send_cmd(cmd: str) -> bool:
    global _conn
    for attempt in range(2):
        with _lock:
            if _conn is None:
                return False
            try:
                _conn.sendall((cmd + "\n").encode("utf-8"))
                resp = _recv_line(_conn)
                if resp == "OK":
                    return True
            except (BrokenPipeError, ConnectionError, OSError):
                _cleanup_recv_buffer(_conn)
                _conn = None
    return False


def _heartbeat_loop():
    consecutive_fail = 0
    while not _heartbeat_event.is_set():
        if not _send_cmd("PING"):
            consecutive_fail += 1
            if consecutive_fail >= 3:
                _emergency_stop()
                break
            if not _restart_ahk():
                consecutive_fail += 1
        else:
            consecutive_fail = 0
        _heartbeat_event.wait(5)


def _restart_ahk() -> bool:
    global _conn, _ahk_process, _restart_fail_count
    if not _restart_lock.acquire(blocking=False):
        return False
    try:
        if _restart_fail_count >= _MAX_RESTART_ATTEMPTS:
            _emergency_stop()
            return False

        with _lock:
            if _conn:
                try:
                    _conn.close()
                except OSError:
                    pass
                _cleanup_recv_buffer(_conn)
                _conn = None
            if _ahk_process:
                try:
                    _ahk_process.kill()
                    _ahk_process.wait(timeout=2)
                except OSError:
                    pass
                _ahk_process = None

        time.sleep(0.5)

        port = getattr(_launch_ahk, "port", 12345)
        if not _launch_ahk(port):
            _restart_fail_count += 1
            return False

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with _lock:
                if _conn is not None:
                    _restart_fail_count = 0
                    return True
            time.sleep(0.2)

        _restart_fail_count += 1
        return False
    finally:
        _restart_lock.release()


def _find_ahk_executable() -> str | None:
    for reg_root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(reg_root, r"SOFTWARE\AutoHotkey")
            install_dir = winreg.QueryValueEx(key, "InstallDir")[0]
            for exe_name in ["AutoHotkey64.exe", "AutoHotkey32.exe", "AutoHotkey.exe"]:
                candidate = Path(install_dir) / exe_name
                if candidate.exists():
                    return str(candidate)
        except (FileNotFoundError, OSError):
            continue
    for exe_name in ["autohotkey.exe", "AutoHotkey64.exe", "AutoHotkey32.exe", "AutoHotkey.exe"]:
        path = shutil.which(exe_name)
        if path:
            return path
    # 最後檢查 data dir 是否已下載過
    for exe_name in ["AutoHotkey64.exe", "AutoHotkey32.exe", "AutoHotkey.exe"]:
        candidate = _ahk_data_dir() / exe_name
        if candidate.exists():
            return str(candidate)
    return None


def _launch_ahk(port: int = 12345) -> bool:
    global _ahk_process
    ahk_script = getattr(_launch_ahk, "ahk_path", _find_ahk())
    exe_path = _find_ahk_executable()
    if not exe_path:
        logging.error("找不到 AutoHotkey 執行檔，請確認已安裝 AutoHotkey v2")
        return False
    try:
        _ahk_process = subprocess.Popen(
            [exe_path, ahk_script, str(port)],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception:
        logging.exception("啟動 AutoHotkey 失敗")
        return False


def is_ahk_available() -> bool:
    return _find_ahk_executable() is not None


_health_callback: Optional[Callable[[str], None]] = None


def set_ahk_health_callback(cb: Optional[Callable[[str], None]]):
    global _health_callback
    _health_callback = cb


def download_ahk() -> bool:
    dest_dir = _ahk_data_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    exe_path = dest_dir / "AutoHotkey64.exe"
    if exe_path.exists():
        return True
    try:
        logging.info("正在下載 AutoHotkey v2（%s）...", _AHK_DOWNLOAD_URL)
        resp = urllib.request.urlopen(_AHK_DOWNLOAD_URL, timeout=30)
        total = int(resp.headers.get("Content-Length", 0))
        buf = io.BytesIO()
        chunk_size = 64 * 1024
        downloaded = 0
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            buf.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = downloaded * 100 // total
                logging.info(
                    "AHK 下載進度: %d%% (%d/%d KB)", pct, downloaded // 1024, total // 1024
                )
        logging.info("下載完成（%d bytes），正在解壓縮...", downloaded)
        with zipfile.ZipFile(buf) as zf:
            zf.extractall(dest_dir)
        if exe_path.exists():
            logging.info("AutoHotkey 已安裝至 %s", dest_dir)
            return True
        msg = "解壓縮後找不到 AutoHotkey64.exe"
        logging.error(msg)
        if _health_callback:
            _health_callback(msg)
        return False
    except Exception as e:
        msg = f"下載 AutoHotkey 失敗：{e}"
        logging.error(msg)
        if _health_callback:
            _health_callback(msg)
        return False


def _close_all():
    global _server, _conn, _ahk_process
    if _conn:
        try:
            _conn.close()
        except OSError:
            pass
        _cleanup_recv_buffer(_conn)
        _conn = None
    if _server:
        try:
            _server.close()
        except OSError:
            pass
        _server = None
    if _ahk_process:
        try:
            _ahk_process.kill()
        except OSError:
            pass
        _ahk_process = None


def _emergency_stop():
    _heartbeat_event.set()
    with _lock:
        _close_all()
    logging.error("AHK 通訊永久失效，停止重啟")


def _accept_loop():
    global _conn
    _server.listen(1)
    _server.settimeout(1.0)
    while not _heartbeat_event.is_set():
        try:
            conn, _ = _server.accept()
            with _lock:
                if _conn:
                    try:
                        _conn.close()
                    except OSError:
                        pass
                    _cleanup_recv_buffer(_conn)
                _conn = conn
        except socket.timeout:
            continue
        except OSError:
            break


def init_ahk(ahk_path: str | None = None, port: int = 12345) -> bool:
    global _server, _initialized
    if _initialized:
        return True
    if ahk_path is None:
        ahk_path = _find_ahk()
    _launch_ahk.ahk_path = ahk_path
    _launch_ahk.port = port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} 已被佔用，請確認沒有其他執行中的實例")

    _server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _server.bind(("127.0.0.1", port))

    if not _launch_ahk(port):
        return False

    accept_thread = threading.Thread(target=_accept_loop, daemon=True)
    accept_thread.start()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        with _lock:
            if _conn is not None:
                break
        time.sleep(0.2)
    else:
        return False

    _heartbeat_event.clear()
    hb = threading.Thread(target=_heartbeat_loop, daemon=True)
    hb.start()

    ok = _send_cmd("PING")
    _initialized = ok
    return ok


def _load_screen_bounds() -> dict:
    try:
        from _loader import load_sibling

        perf = load_sibling("performance_monitor", "core/10_performance_monitor.py")
        return perf.get_screen_bounds()
    except Exception:
        SM_CXSCREEN = 0
        SM_CYSCREEN = 1
        import ctypes

        user32 = ctypes.windll.user32
        return {
            "x": 0,
            "y": 0,
            "w": user32.GetSystemMetrics(SM_CXSCREEN),
            "h": user32.GetSystemMetrics(SM_CYSCREEN),
        }


def _validate_coords(x: int, y: int) -> bool:
    bounds = _load_screen_bounds()
    if (
        x < bounds["x"]
        or y < bounds["y"]
        or x >= bounds["x"] + bounds["w"]
        or y >= bounds["y"] + bounds["h"]
    ):
        logging.warning("拒絕超出螢幕的點擊: (%d, %d) 螢幕=%s", x, y, bounds)
        return False
    return True


def send_click(x: int, y: int, button: str = "left") -> bool:
    if not _validate_coords(x, y):
        return False
    return _send_cmd(f"CLICK,{x},{y},{button}")


def send_key(key: str) -> bool:
    key = key.strip().replace("\n", "").replace("\r", "")
    if not key:
        return False
    return _send_cmd(f"KEY,{key}")


def send_drag(x1: int, y1: int, x2: int, y2: int, button: str = "left") -> bool:
    if not _validate_coords(x1, y1) or not _validate_coords(x2, y2):
        return False
    return _send_cmd(f"DRAG,{x1},{y1},{x2},{y2},{button}")


def send_scroll(amount: int = 1, direction: str = "WheelDown") -> bool:
    return _send_cmd(f"SCROLL,{amount},{direction}")


def send_hold_key(key: str, duration_ms: int = 0) -> bool:
    key = key.strip().replace("\n", "").replace("\r", "")
    if not key:
        return False
    return _send_cmd(f"HOLDKEY,{key},{duration_ms}")


def send_emergency_stop() -> bool:
    global _conn
    logging.warning("發送緊急停止指令 (ESTOP)")
    with _lock:
        if _conn is None:
            return False
        try:
            _conn.sendall(b"ESTOP\n")
            resp = _recv_line(_conn, timeout=1.0)
            return resp == "OK"
        except (BrokenPipeError, ConnectionError, OSError):
            return False


def shutdown() -> None:
    global _server, _conn, _ahk_process
    _heartbeat_event.set()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if _restart_lock.acquire(blocking=False):
            _restart_lock.release()
            break
        time.sleep(0.05)
    with _lock:
        pass
    _close_all()


if __name__ == "__main__":
    ok = init_ahk()
    print(f"AHK 連線: {'成功' if ok else '失敗'}")
    if not ok:
        raise SystemExit(1)

    print("PING 測試: 成功")

    try:
        inp = input("請輸入測試座標 (x y): ").strip()
        parts = inp.split()
        if len(parts) >= 2:
            x, y = int(parts[0]), int(parts[1])
            print(f"發送 CLICK {x} {y} left...")
            print(f"點擊結果: {send_click(x, y)}")
    except (ValueError, EOFError):
        print("跳過座標測試")

    print("等待 3 秒後關閉...")
    time.sleep(3)
    shutdown()
    print("已關閉")
