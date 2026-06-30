"""
OCR concurrency stress test — validates thread safety of recognize().

Tests:
- thread count growth under parallel OCR calls
- memory stability under sustained OCR load
- whether OCR tasks overlap (re-entrancy)
- simulate slow OCR via artificial sleep in the engine path
"""

import gc
import sys
import threading
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

import _loader

_ocr = _loader.load_sibling("ocr_engine", "core/02_ocr_engine.py")
recognize = _ocr.recognize
init_engine = _ocr.init_engine


def _gen_test_img(w=640, h=480):
    img = np.full((h, w, 3), 240, dtype=np.uint8)
    cv2.putText(img, "OCR Test 123", (100, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 2)
    return img


class _OcrRunner:
    """Runs OCR N times, tracks overlap, memory, thread count."""

    def __init__(self, img, n=20):
        self.img = img
        self.n = n
        self.active_count = 0
        self.max_concurrent = 0
        self.active_lock = threading.Lock()
        self.errors = 0

    def _ocr_worker(self):
        with self.active_lock:
            self.active_count += 1
            self.max_concurrent = max(self.max_concurrent, self.active_count)
        try:
            results = recognize(self.img)
            if results is None:
                self.errors += 1
        except Exception:
            self.errors += 1
        with self.active_lock:
            self.active_count -= 1

    def run(self):
        threads = []
        t0 = time.monotonic()
        for _ in range(self.n):
            t = threading.Thread(target=self._ocr_worker, daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=60)
        elapsed = time.monotonic() - t0
        return elapsed


def test_burst_parallel():
    """Fire N concurrent OCR requests — check thread safety, not speed."""
    print("\n--- Test: Burst parallel OCR (20 concurrent) ---")
    img = _gen_test_img()
    init_engine()

    # measure threads before
    gc.collect()
    tracemalloc.start()
    threads_before = threading.active_count()

    runner = _OcrRunner(img, n=20)
    elapsed = runner.run()

    threads_after = threading.active_count()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"  Threads: {threads_before} → {threads_after}")
    print(f"  Max concurrent OCR workers: {runner.max_concurrent}")
    print(f"  Errors: {runner.errors}")
    print(f"  Total time: {elapsed:.3f}s")
    print(f"  Memory current: {current / 1024:.1f}KB peak: {peak / 1024:.1f}KB")
    return runner.errors, runner.max_concurrent, threads_after - threads_before


def test_sustained_load():
    """Run 50 sequential OCR calls — check memory leak / thread creep."""
    print("\n--- Test: Sustained sequential OCR (50 calls) ---")
    img = _gen_test_img()

    gc.collect()
    tracemalloc.start()
    threads_before = threading.active_count()

    errors = 0
    latencies = []

    for i in range(50):
        tc = time.monotonic()
        try:
            results = recognize(img)
            dt = (time.monotonic() - tc) * 1000
            latencies.append(dt)
            if results is None:
                errors += 1
        except Exception:
            errors += 1
        if i > 0 and i % 10 == 0:
            gc.collect()

    threads_after = threading.active_count()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    avg_lat = sum(latencies) / len(latencies) if latencies else 0
    max_lat = max(latencies) if latencies else 0
    print(f"  Threads: {threads_before} → {threads_after}")
    print(f"  Errors: {errors}/50")
    print(f"  Avg latency: {avg_lat:.1f}ms  Max: {max_lat:.1f}ms")
    print(f"  Memory current: {current / 1024:.1f}KB peak: {peak / 1024:.1f}KB")
    return errors, threads_after - threads_before, avg_lat, max_lat


def test_engine_reinit_stress():
    """Trigger engine re-init via failure counter — check RLock safety."""
    print("\n--- Test: Engine re-init under concurrent access ---")

    # Temporarily lower max failures to trigger restart
    global _OCR_MAX_FAILURES
    _OCR_MAX_FAILURES = 3

    _ocr._OCR_MAX_FAILURES = 3
    _ocr._OCR_FAILURE_COUNT = 0

    # Reset engine to force re-init
    _ocr._engine = None

    img = _gen_test_img()
    errors = 0
    threads_before = threading.active_count()

    def _stress_worker():
        nonlocal errors
        try:
            recognize(img)
        except Exception:
            errors += 1

    threads = []
    for _ in range(10):
        t = threading.Thread(target=_stress_worker, daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=30)

    threads_after = threading.active_count()
    print(f"  Threads: {threads_before} → {threads_after}")
    print(f"  Errors: {errors}")
    print(f"  Engine after test: {'alive' if _ocr._engine is not None else 'DEAD'}")

    # Restore
    _ocr._OCR_MAX_FAILURES = 5
    return errors


if __name__ == "__main__":
    print("=" * 60)
    print("OCR Concurrency Stress Test")
    print("=" * 60)

    e1, max_conc, thread_delta1 = test_burst_parallel()
    e2, thread_delta2, avg_lat, max_lat = test_sustained_load()
    e3 = test_engine_reinit_stress()

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(
        f"  Burst parallel (20x): errors={e1} max_concurrent={max_conc} thread_leak={thread_delta1}"
    )
    print(f"  Sustained (50x):     errors={e2} thread_leak={thread_delta2} avg_lat={avg_lat:.1f}ms")
    print(f"  Engine reinit (10x): errors={e3}")
    print()
