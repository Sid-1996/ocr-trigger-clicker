"""
Socket protocol stress test — validates _recv_line from 03_ahk_socket.py.

Tests:
1. Baseline: one-at-a-time commands (as in production)
2. NO-DELAY server: simulates AHK responding immediately
3. NAGLE server: simulates worst-case where Nagle defers response
4. Merged packet: 3 commands in one sendall (TCP coalescing)
5. High-frequency burst: 10ms interval
"""
import socket
import threading
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _loader
_ahk = _loader.load_sibling("ahk_socket", "core/03_ahk_socket.py")
_recv_line = _ahk._recv_line


def echo_server(port, stop, use_nodelay=True):
    """Reads lines, sends OK per line. use_nodelay=False simulates Nagle-delayed AHK."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    srv.settimeout(0.5)

    conn = None
    while not stop.is_set():
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        break
    if conn is None:
        srv.close()
        return

    if use_nodelay:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    buf = b""
    while not stop.is_set():
        try:
            chunk = conn.recv(4096)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                try:
                    conn.sendall(b"OK\n")
                except OSError:
                    break
    try:
        conn.close()
    except OSError:
        pass
    srv.close()


def _send_cmd(conn, cmd):
    """Exact production _send_cmd logic."""
    conn.sendall((cmd + "\n").encode("utf-8"))
    return _recv_line(conn, timeout=1.0)


# ── Test cases ──

def test_baseline(port):
    """2000 single commands — like normal production operation."""
    print(f"\n--- Test 1: Baseline one-at-a-time (2000) ---")
    stop = threading.Event()
    t = threading.Thread(target=echo_server, args=(port, stop, True), daemon=True)
    t.start()
    time.sleep(0.3)

    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cli.settimeout(5)
    cli.connect(("127.0.0.1", port))

    N = 2000
    ok = 0
    fail = 0
    rtt = []

    for i in range(N):
        cmd = "CLICK,100,200" if i % 2 == 0 else "PING"
        t0 = time.monotonic()
        try:
            resp = _send_cmd(cli, cmd)
            dt = (time.monotonic() - t0) * 1000
            rtt.append(dt)
            if resp == "OK":
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1

    stop.set()
    cli.close()
    t.join(timeout=3)
    avg = sum(rtt) / len(rtt) if rtt else 0
    mx = max(rtt) if rtt else 0
    print(f"  OK={ok}/{N} ({ok/N*100:.1f}%)  FAIL={fail}  avg_rtt={avg:.3f}ms  max_rtt={mx:.3f}ms")
    return ok, fail


def test_nagle_server(port):
    """
    Server WITHOUT TCP_NODELAY — simulates Nagle-deferred responses.
    This reveals whether _recv_line's 1-second timeout is vulnerable
    to Nagle-induced delays.
    """
    print(f"\n--- Test 2: Nagle-delayed server (2000) ---")
    stop = threading.Event()
    t = threading.Thread(target=echo_server, args=(port, stop, False), daemon=True)
    t.start()
    time.sleep(0.3)

    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cli.settimeout(5)
    cli.connect(("127.0.0.1", port))

    N = 2000
    ok = 0
    fail = 0
    timeout_count = 0

    for i in range(N):
        cmd = "CLICK,100,200" if i % 2 == 0 else "PING"
        try:
            resp = _send_cmd(cli, cmd)
            if resp == "OK":
                ok += 1
            elif resp == "":
                timeout_count += 1
                fail += 1
            else:
                fail += 1
        except Exception:
            fail += 1
        # 1ms delay between commands to avoid overwhelming Nagle queue
        time.sleep(0.001)

    stop.set()
    cli.close()
    t.join(timeout=3)
    print(f"  OK={ok}/{N} ({ok/N*100:.1f}%)  FAIL={fail}  TIMEOUTS={timeout_count}")
    return ok, fail, timeout_count


def test_merged_packets(port):
    """
    THE CRITICAL TEST: 3 commands in one sendall, read 3 responses.
    If server's OK responses coalesce into one TCP segment, _recv_line
    only takes the first line and discards the rest.
    """
    print(f"\n--- Test 3: Merged packets (3-per-batch × 500 = 1500 cmd) ---")
    stop = threading.Event()
    t = threading.Thread(target=echo_server, args=(port, stop, True), daemon=True)
    t.start()
    time.sleep(0.3)

    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cli.settimeout(1.0)
    cli.connect(("127.0.0.1", port))

    N = 500
    ok = 0
    fail = 0
    timeouts = 0
    misordered = 0

    for i in range(N):
        # 3 commands in one sendall
        batch = f"A{i}\nB{i}\nC{i}\n"
        try:
            cli.sendall(batch.encode("utf-8"))
            # Read 3 responses
            for j in range(3):
                t0 = time.monotonic()
                resp = _recv_line(cli, timeout=1.0)
                if resp == "OK":
                    ok += 1
                elif resp == "":
                    timeouts += 1
                    fail += 1
                else:
                    fail += 1
                    misordered += 1
        except Exception:
            fail += 3

    stop.set()
    cli.close()
    t.join(timeout=3)
    total = N * 3
    print(f"  OK={ok}/{total} ({ok/total*100:.1f}%)  FAIL={fail}  TIMEOUTS={timeouts}  "
          f"MISORDERED={misordered}")
    return ok, fail, timeouts


def test_high_freq(port):
    """200 commands with no delay at all — tests rapid-fire production scenario."""
    print(f"\n--- Test 4: High frequency burst (200, no delay) ---")
    stop = threading.Event()
    t = threading.Thread(target=echo_server, args=(port, stop, True), daemon=True)
    t.start()
    time.sleep(0.3)

    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cli.settimeout(1.0)
    cli.connect(("127.0.0.1", port))

    N = 200
    ok = 0
    fail = 0
    rtt = []

    for i in range(N):
        cmd = "PING"
        t0 = time.monotonic()
        try:
            resp = _send_cmd(cli, cmd)
            rtt.append((time.monotonic() - t0) * 1000)
            if resp == "OK":
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1

    stop.set()
    cli.close()
    t.join(timeout=3)
    avg = sum(rtt) / len(rtt) if rtt else 0
    mx = max(rtt) if rtt else 0
    print(f"  OK={ok}/{N} ({ok/N*100:.1f}%)  FAIL={fail}  avg_rtt={avg:.3f}ms  max_rtt={mx:.3f}ms")
    return ok, fail


def test_partial_read(port):
    """
    Simulates OS splitting TCP data mid-packet: server sends "OK\n" but
    only 2 bytes arrive in the first recv. Tests if _recv_line correctly
    loops around for more data.
    """
    print(f"\n--- Test 5: Partial read (500 cmds, simulated split) ---")
    # Special server that sends byte-by-byte
    def split_server(port, stop):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        srv.settimeout(0.5)
        conn = None
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            break
        if conn is None:
            srv.close()
            return
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        buf = b""
        while not stop.is_set():
            try:
                chunk = conn.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    # Send byte-by-byte with tiny delay
                    for b in b"OK\n":
                        conn.sendall(bytes([b]))
                        time.sleep(0.0001)
        conn.close()
        srv.close()

    stop = threading.Event()
    t = threading.Thread(target=split_server, args=(port, stop), daemon=True)
    t.start()
    time.sleep(0.3)

    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cli.settimeout(1.0)
    cli.connect(("127.0.0.1", port))

    N = 500
    ok = 0
    fail = 0
    rtt = []

    for i in range(N):
        cmd = "PING"
        t0 = time.monotonic()
        try:
            resp = _send_cmd(cli, cmd)
            dt = (time.monotonic() - t0) * 1000
            rtt.append(dt)
            if resp == "OK":
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1

    stop.set()
    cli.close()
    t.join(timeout=3)
    avg = sum(rtt) / len(rtt) if rtt else 0
    mx = max(rtt) if rtt else 0
    print(f"  OK={ok}/{N} ({ok/N*100:.1f}%)  FAIL={fail}  avg_rtt={avg:.3f}ms  max_rtt={mx:.3f}ms")
    return ok, fail


if __name__ == "__main__":
    BASE = 30000
    print("=" * 65)
    print("Socket Protocol Stress Test — _recv_line 驗證")
    print("=" * 65)

    tests = [
        ("baseline (2000)", test_baseline(BASE)),
        ("nagle_srv (2000)", test_nagle_server(BASE + 1)),
        ("merged (1500)", test_merged_packets(BASE + 2)),
        ("highfreq (200)", test_high_freq(BASE + 3)),
        ("partial (500)", test_partial_read(BASE + 4)),
    ]

    print("\n" + "=" * 65)
    print("Results Summary")
    print("=" * 65)
    grand_ok = 0
    grand_fail = 0
    for name, r in tests:
        ok, fail = r[0], r[1]
        grand_ok += ok
        grand_fail += fail
        extra = ""
        if len(r) > 2:
            extra = f"  timeouts={r[2]}"
        total = ok + fail
        print(f"  {name:>20}: OK={ok}/{total} ({ok/total*100:.1f}%)  FAIL={fail}{extra}")

    print(f"\n  {'GRAND TOTAL':>20}: OK={grand_ok}/{grand_ok+grand_fail} "
          f"({grand_ok/(grand_ok+grand_fail)*100:.2f}%)  FAIL={grand_fail}")
    print()
