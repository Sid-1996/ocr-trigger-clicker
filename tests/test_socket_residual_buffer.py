"""
Validate _recv_line residual buffer fix for merged/partial TCP packets.

Tests:
1. Merged packets: two responses in one recv ("OK\nPING\n")
2. Partial packets: response split across recv boundaries
3. 10000 repeated sends: >= 99.99% success
4. Multi-connection isolation: buffers don't leak across connections
"""

import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _loader

_ahk = _loader.load_sibling("ahk_socket", "core/03_ahk_socket.py")
_recv_line = _ahk._recv_line
_recv_buffers = _ahk._recv_buffers


def merged_server(port, stop):
    """Echo server: sends 'OK' per line, but with TCP_NODELAY off initially."""
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
                try:
                    conn.sendall(b"OK\n")
                except OSError:
                    break
    try:
        conn.close()
    except OSError:
        pass
    srv.close()


def test_merged_packets():
    """Two responses in one recv: call1 gets OK, call2 gets PING."""
    port = 41000
    stop = threading.Event()
    t = threading.Thread(target=merged_server, args=(port, stop), daemon=True)
    t.start()
    time.sleep(0.3)

    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cli.settimeout(1.0)
    cli.connect(("127.0.0.1", port))

    N = 2000
    fails = 0
    for i in range(N):
        cli.sendall(b"A\nB\n")
        r1 = _recv_line(cli, timeout=1.0)
        r2 = _recv_line(cli, timeout=1.0)
        if r1 != "OK" or r2 != "OK":
            fails += 1

    stop.set()
    cli.close()
    t.join(timeout=3)

    total = N * 2
    rate = (total - fails) / total * 100
    print(f"  merged_packets: OK={total - fails}/{total} ({rate:.2f}%)  FAIL={fails}")
    return fails


def test_partial_packets():
    """Simulates OS splitting TCP data mid-response."""
    port = 41001
    stop = threading.Event()

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
                    for b_ in b"OK\n":
                        conn.sendall(bytes([b_]))
                        time.sleep(0.0005)
        conn.close()
        srv.close()

    t = threading.Thread(target=split_server, args=(port, stop), daemon=True)
    t.start()
    time.sleep(0.3)

    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cli.settimeout(1.0)
    cli.connect(("127.0.0.1", port))

    N = 1000
    fails = 0
    for i in range(N):
        cli.sendall(b"PING\n")
        resp = _recv_line(cli, timeout=1.0)
        if resp != "OK":
            fails += 1

    stop.set()
    cli.close()
    t.join(timeout=3)

    rate = (N - fails) / N * 100
    print(f"  partial_packets: OK={N - fails}/{N} ({rate:.2f}%)  FAIL={fails}")
    return fails


def test_stress_10000():
    """10000 repeated sends MUST achieve >= 99.99% success rate."""
    port = 41002
    stop = threading.Event()
    t = threading.Thread(target=merged_server, args=(port, stop), daemon=True)
    t.start()
    time.sleep(0.3)

    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cli.settimeout(1.0)
    cli.connect(("127.0.0.1", port))

    N = 10000
    fails = 0
    for i in range(N):
        cli.sendall(b"PING\n")
        resp = _recv_line(cli, timeout=1.0)
        if resp != "OK":
            fails += 1

    stop.set()
    cli.close()
    t.join(timeout=5)

    rate = (N - fails) / N * 100
    print(f"  stress_10000: OK={N - fails}/{N} ({rate:.4f}%)  FAIL={fails}")
    assert rate >= 99.99, f"FAIL: success rate {rate}% < 99.99%"
    return fails


def test_multi_connection_isolation():
    """Buffers from one connection must not leak to another."""
    port1 = 41003
    port2 = 41004
    stop = threading.Event()
    t1 = threading.Thread(target=merged_server, args=(port1, stop), daemon=True)
    t2 = threading.Thread(target=merged_server, args=(port2, stop), daemon=True)
    t1.start()
    t2.start()
    time.sleep(0.3)

    c1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c1.settimeout(0.5)
    c1.connect(("127.0.0.1", port1))
    c2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c2.settimeout(0.5)
    c2.connect(("127.0.0.1", port2))

    c1_id = id(c1)
    c2_id = id(c2)

    before_keys = set(_recv_buffers.keys())

    for i in range(500):
        c1.sendall(b"PING\n")
        c2.sendall(b"PING\n")
        r1 = _recv_line(c1, timeout=0.5)
        r2 = _recv_line(c2, timeout=0.5)
        if r1 != "OK":
            pass
        if r2 != "OK":
            pass

    after_keys = set(_recv_buffers.keys())
    leak_keys = after_keys - before_keys - {c1_id, c2_id}
    assert not leak_keys, f"Buffer leak across connections: keys={leak_keys}"

    stop.set()
    c1.close()
    _ahk._cleanup_recv_buffer(c1)
    c2.close()
    _ahk._cleanup_recv_buffer(c2)
    t1.join(timeout=3)
    t2.join(timeout=3)

    final_keys = set(_recv_buffers.keys())
    assert c1_id not in final_keys, "c1 buffer not cleaned up"
    assert c2_id not in final_keys, "c2 buffer not cleaned up"
    print("  multi_connection: PASS (no leak, cleanup ok)")
    return 0


if __name__ == "__main__":
    print("=" * 65)
    print("Residual Buffer Stress Test — _recv_line fix")
    print("=" * 65)

    results = []
    for fn in [
        test_merged_packets,
        test_partial_packets,
        test_stress_10000,
        test_multi_connection_isolation,
    ]:
        name = fn.__name__.replace("test_", "")
        print(f"\n--- Test: {name} ---")
        try:
            fails = fn()
            results.append((name, fails, None))
        except Exception as e:
            results.append((name, -1, str(e)))
            print(f"  ERROR: {e}")

    print("\n" + "=" * 65)
    print("Results Summary")
    print("=" * 65)
    total_ok = 0
    total_fail = 0
    errors = 0
    for name, fails, err in results:
        if err:
            print(f"  {name:>28}: ERROR — {err}")
            errors += 1
            continue
        total_fail += max(0, fails)
        print(f"  {name:>28}: FAIL={fails}")
    print(f"\n  {'TOTAL FAILURES':>28}: {total_fail}")
    if errors:
        print(f"  {'ERRORS':>28}: {errors}")
    else:
        print(f"  {'ERRORS':>28}: 0")
    print()
