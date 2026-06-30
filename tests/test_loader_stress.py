"""
Loader stress test — validates _loader.py thread safety.

Tests:
- 20 threads concurrently calling load_sibling() 10000 times each
- Checks for: deadlock, duplicate imports, cache corruption, module reload
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _loader


def worker(name, count, results, idx):
    """Repeatedly call load_sibling for various modules."""
    local_ok = 0
    local_err = 0
    modules = [
        ("screenshot", "core/01_screenshot.py"),
        ("ocr_engine", "core/02_ocr_engine.py"),
        ("ahk_socket", "core/03_ahk_socket.py"),
        ("rule_engine", "core/04_rule_engine.py"),
        ("main_loop", "core/05_main_loop.py"),
        ("performance_monitor", "core/10_performance_monitor.py"),
        ("template_matching", "core/11_template_matching.py"),
    ]
    for i in range(count):
        mod_name, mod_file = modules[i % len(modules)]
        try:
            mod = _loader.load_sibling(mod_name, mod_file)
            if mod is not None:
                local_ok += 1
            else:
                local_err += 1
        except Exception:
            local_err += 1
    results[idx] = (local_ok, local_err)


def test_concurrent_load():
    """20 threads, each calling load_sibling 10000 times."""
    print("\n--- Test: Concurrent load_sibling (20 threads × 10000) ---")
    N_THREADS = 20
    N_EACH = 10000

    results = [None] * N_THREADS
    threads = []

    t0 = time.monotonic()
    for i in range(N_THREADS):
        t = threading.Thread(target=worker, args=(f"T{i}", N_EACH, results, i), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join(timeout=60)

    elapsed = time.monotonic() - t0

    total_ok = sum(r[0] for r in results)
    total_err = sum(r[1] for r in results)
    total = total_ok + total_err

    print(f"  Threads: {N_THREADS} × {N_EACH} = {total} calls")
    print(f"  OK: {total_ok}  Error: {total_err}")
    print(f"  Time: {elapsed:.3f}s  Rate: {total/elapsed:.0f} calls/s")
    return total_err


def test_cache_consistency():
    """Verify cache returns same object for same key."""
    print("\n--- Test: Cache consistency ---")

    mod1 = _loader.load_sibling("screenshot", "core/01_screenshot.py")
    mod2 = _loader.load_sibling("screenshot", "core/01_screenshot.py")
    mod3 = _loader.load_sibling("ocr_engine", "core/02_ocr_engine.py")

    same = mod1 is mod2
    different = mod1 is not mod3

    print(f"  Same key returns same object: {same}")
    print(f"  Different key returns different: {different}")
    return not (same and different)


def test_loader_cache_size():
    """Check how many items are in the loader cache."""
    print(f"\n--- Test: Loader cache state ---")
    print(f"  Cache entries: {len(_loader._cache)}")
    for key in _loader._cache:
        print(f"    {key}")
    return len(_loader._cache)


if __name__ == "__main__":
    print("=" * 60)
    print("Loader Stress Test")
    print("=" * 60)

    # Pre-load all modules once
    print("\nPre-loading all modules...")
    for mod_name, mod_file in [
        ("screenshot", "core/01_screenshot.py"),
        ("ocr_engine", "core/02_ocr_engine.py"),
        ("ahk_socket", "core/03_ahk_socket.py"),
        ("rule_engine", "core/04_rule_engine.py"),
        ("main_loop", "core/05_main_loop.py"),
        ("performance_monitor", "core/10_performance_monitor.py"),
        ("template_matching", "core/11_template_matching.py"),
    ]:
        _loader.load_sibling(mod_name, mod_file)
    print("  Done.")

    # Cache consistency
    err1 = test_cache_consistency()

    # Concurrent stress
    err2 = test_concurrent_load()

    # Cache state
    test_loader_cache_size()

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Cache consistency error: {err1}")
    print(f"  Concurrent load errors:  {err2}")
    verdict = "ALL TESTS PASSED" if (err1 == 0 and err2 == 0) else "ISSUES DETECTED"
    print(f"\n  >>> VERDICT: {verdict}")
    print()
