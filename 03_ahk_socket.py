import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

_server: Optional[socket.socket] = None
_conn: Optional[socket.socket] = None
_ahk_process: Optional[subprocess.Popen] = None
_lock = threading.Lock()
_heartbeat_event = threading.Event()


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


def _recv_line(conn: socket.socket, timeout: float = 3.0) -> str:
    conn.settimeout(timeout)
    buf = b""
    while True:
        try:
            ch = conn.recv(1)
        except socket.timeout:
            break
        if not ch:
            break
        if ch == b"\n":
            break
        buf += ch
    return buf.decode("utf-8", errors="replace").strip()


def _send_cmd(cmd: str) -> bool:
    global _conn
    with _lock:
        if _conn is None:
            return False
        try:
            _conn.sendall((cmd + "\n").encode("utf-8"))
            resp = _recv_line(_conn)
            return resp == "OK"
        except (BrokenPipeError, ConnectionError, OSError):
            _conn = None
            return False


def _heartbeat_loop():
    while not _heartbeat_event.is_set():
        if not _send_cmd("PING"):
            _restart_ahk()
        _heartbeat_event.wait(5)


def _restart_ahk():
    global _conn, _ahk_process
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
            except OSError:
                pass
            _ahk_process = None
    time.sleep(0.5)
    _launch_ahk()


def _launch_ahk():
    global _ahk_process
    ahk_path = getattr(_launch_ahk, "ahk_path", _find_ahk())
    candidates = ["autohotkey.exe", "AutoHotkey64.exe", "AutoHotkey32.exe", "AutoHotkey.exe"]
    for exe in candidates:
        try:
            _ahk_process = subprocess.Popen(
                [exe, ahk_path],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return
        except FileNotFoundError:
            continue
    raise FileNotFoundError("找不到 AutoHotkey 執行檔")


def _accept_loop():
    global _conn
    _server.listen(1)
    _server.settimeout(1.0)
    while not _heartbeat_event.is_set():
        try:
            conn, _ = _server.accept()
            with _lock:
                _conn = conn
            return
        except socket.timeout:
            continue


def init_ahk(ahk_path: str | None = None, port: int = 12345) -> bool:
    global _server
    if ahk_path is None:
        ahk_path = _find_ahk()
    _launch_ahk.ahk_path = ahk_path

    _server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _server.bind(("127.0.0.1", port))

    _launch_ahk()

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

    return _send_cmd("PING")


def send_click(x: int, y: int, button: str = "left") -> bool:
    return _send_cmd(f"CLICK,{x},{y},{button}")


def send_move(x: int, y: int) -> bool:
    return _send_cmd(f"MOVE,{x},{y}")


def shutdown() -> None:
    _heartbeat_event.set()
    with _lock:
        if _conn:
            try:
                _conn.close()
            except OSError:
                pass
        if _server:
            try:
                _server.close()
            except OSError:
                pass
        if _ahk_process:
            try:
                _ahk_process.kill()
            except OSError:
                pass


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
