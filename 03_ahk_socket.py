import shutil
import socket
import subprocess
import threading
import time
import winreg
from pathlib import Path
from typing import Optional

_server: Optional[socket.socket] = None
_conn: Optional[socket.socket] = None
_ahk_process: Optional[subprocess.Popen] = None
_lock = threading.Lock()
_restart_lock = threading.Lock()
_heartbeat_event = threading.Event()
_initialized = False
_restart_fail_count = 0
_MAX_RESTART_ATTEMPTS = 3


def _find_ahk() -> str:
    try:
        from build import get_resource_path

        p = Path(get_resource_path("clicker.ahk"))
        if p.exists():
            return str(p.resolve())
    except ImportError:
        pass
    candidates = [
        Path(__file__).parent / "clicker.ahk",
        Path.cwd() / "clicker.ahk",
    ]
    for p in candidates:
        if p.exists():
            return str(p.resolve())
    return str(candidates[0])


def _recv_line(conn: socket.socket, timeout: float = 5.0) -> str:
    conn.settimeout(timeout)
    buf = b""
    while True:
        try:
            chunk = conn.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        idx = chunk.find(b"\n")
        if idx != -1:
            buf += chunk[:idx]
            break
        buf += chunk
    return buf.decode("utf-8", errors="replace").strip()


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
                _conn = None
        if attempt == 0:
            time.sleep(0.5)
    return False


def _heartbeat_loop():
    consecutive_fail = 0
    while not _heartbeat_event.is_set():
        if not _send_cmd("PING"):
            consecutive_fail += 1
            if consecutive_fail >= 3:
                _emergency_stop()
                break
            _restart_ahk()
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
                _conn = None
            if _ahk_process:
                try:
                    _ahk_process.kill()
                    _ahk_process.wait(timeout=2)
                except OSError:
                    pass
                _ahk_process = None

        time.sleep(0.5)

        if not _launch_ahk():
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
    return None


def _launch_ahk() -> bool:
    global _ahk_process
    ahk_script = getattr(_launch_ahk, "ahk_path", _find_ahk())
    exe_path = _find_ahk_executable()
    if not exe_path:
        print("錯誤：找不到 AutoHotkey 執行檔，請確認已安裝 AutoHotkey v2")
        return False
    try:
        _ahk_process = subprocess.Popen(
            [exe_path, ahk_script],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception as e:
        print(f"啟動 AutoHotkey 失敗：{e}")
        return False


def _close_all():
    global _server, _conn, _ahk_process
    if _conn:
        try:
            _conn.close()
        except OSError:
            pass
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
    print("AHK 通訊永久失效，停止重啟")


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

    _server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _server.bind(("127.0.0.1", port))

    if not _launch_ahk():
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


def send_click(x: int, y: int, button: str = "left") -> bool:
    return _send_cmd(f"CLICK,{x},{y},{button}")


def send_move(x: int, y: int) -> bool:
    return _send_cmd(f"MOVE,{x},{y}")


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
    import os as _os

    _os._exit(0)


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
