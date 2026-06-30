"""
MainLoop CPU profiling — measures CPU, OCR count, capture count,
loop interval under three scenarios.

Scenarios:
  1. Normal mode: MainLoop running on a real window (60s)
  2. No-window mode: window_title pointing to nonexistent window (60s)
  3. poll_roi_value: busy-polling OCR loop (60s)

NOTE: This test actually runs the MainLoop, which is blocking.
      Each scenario runs for up to 60s. Use --quick for 10s each.
"""
import argparse
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _loader

_main_loop = _loader.load_sibling("main_loop", "core/05_main_loop.py")
MainLoop = _main_loop.MainLoop
poll_roi_value = _main_loop.poll_roi_value

# Disable verbose logging
_VERBOSE = False


def _find_any_window():
    """Pick first visible window as target."""
    import pygetwindow as gw
    wins = [w for w in gw.getWindowsWithTitle("") if w.title and w.visible]
    if wins:
        return wins[0].title
    return None


def profile_normal(duration, rules_path, window_title):
    """Run MainLoop normally for `duration` seconds."""
    print(f"\n=== Scenario: Normal mode ({duration}s) ===")
    print(f"   Window: {window_title}")
    print(f"   Rules:  {rules_path}")

    loop = MainLoop(rules_path, window_title, interval_ms=500, verbose=_VERBOSE)
    stats = loop.perf_monitor

    info = []
    loop.on_info = lambda msg: info.append(msg) if len(info) < 100 else None

    loop.start()
    time.sleep(duration)
    loop.stop()

    s = stats.get_stats()
    print(f"   FPS:            {s['fps']:.2f}")
    print(f"   CPU:            {s['cpu_pct']:.1f}% (max {s['cpu_max']:.1f}%)")
    print(f"   Memory:         {s['memory_mb']:.0f} MB (peak {s['memory_peak_mb']:.0f})")
    print(f"   OCR avg:        {s['ocr_avg_ms']:.1f}ms (max {s['ocr_max_ms']:.1f}ms)")
    print(f"   Loop avg:       {s['loop_avg_ms']:.1f}ms (max {s['loop_max_ms']:.1f}ms)")
    print(f"   Click rate:     {s['click_rate']:.1f}/s")
    print(f"   OCR failures:   {s['ocr_failures']}")
    return s


def profile_no_window(duration):
    """Run MainLoop pointing to a nonexistent window."""
    print(f"\n=== Scenario: No-window mode ({duration}s) ===")
    print("   Window: __NONEXISTENT_DEADBEEF__")

    loop = MainLoop("", "__NONEXISTENT_DEADBEEF__", interval_ms=500, verbose=_VERBOSE)
    stats = loop.perf_monitor

    loop.start()
    time.sleep(duration)
    loop.stop()

    s = stats.get_stats()
    print(f"   FPS:            {s['fps']:.2f}")
    print(f"   CPU:            {s['cpu_pct']:.1f}% (max {s['cpu_max']:.1f}%)")
    print(f"   Memory:         {s['memory_mb']:.0f} MB")
    print(f"   Loop avg:       {s['loop_avg_ms']:.1f}ms (max {s['loop_max_ms']:.1f}ms)")
    return s


def profile_poll_roi_value(duration):
    """Run poll_roi_value in a tight loop (simulates the busy polling)."""
    print(f"\n=== Scenario: poll_roi_value ({duration}s) ===")
    roi = {"x": 0, "y": 0, "w": 100, "h": 100}
    title = "__NONEXISTENT_DEADBEEF__"
    stop = threading.Event()

    calls = [0]
    t0 = time.monotonic()

    def _poll_thread():
        while not stop.is_set() and time.monotonic() - t0 < duration:
            poll_roi_value(roi, "first", 5000, title, stop)
            calls[0] += 1

    t = threading.Thread(target=_poll_thread, daemon=True)
    t.start()
    t.join(timeout=duration + 5)

    elapsed = time.monotonic() - t0
    print(f"   poll_roi_value calls: {calls[0]}")
    print(f"   Elapsed: {elapsed:.1f}s")
    print(f"   Rate: {calls[0]/elapsed:.1f} calls/s")

    # Rough CPU — use psutil if available
    try:
        import psutil
        p = psutil.Process()
        cpu = p.cpu_percent(interval=2)
        print(f"   CPU (psutil): {cpu:.1f}%")
    except ImportError:
        print("   CPU: (install psutil for measurement)")
    return calls[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Run 10s instead of 60s")
    args = parser.parse_args()

    duration = 10 if args.quick else 60

    print("=" * 60)
    print("MainLoop CPU Profile")
    print("=" * 60)
    print(f"Duration per scenario: {duration}s")

    # Create a minimal rules file
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8")
    import json
    json.dump({"rules": [], "groups": [{"id": "__default__", "name": "Default", "rule_ids": []}]}, tmp)
    tmp.close()
    rules_path = tmp.name

    # Find a window
    window = _find_any_window()
    if window is None:
        print("WARNING: No visible windows found. Normal scenario will fallback to no-window path.")

    scenarios = []
    if window:
        s1 = profile_normal(duration, rules_path, window)
        scenarios.append(("normal", s1))
    else:
        print("Skipping normal mode (no window available)")

    s2 = profile_no_window(duration)
    scenarios.append(("no_window", s2))

    # poll_roi_value
    poll_calls = profile_poll_roi_value(duration)
    scenarios.append(("poll_roi_value", {"calls": poll_calls}))

    # Clean up
    Path(tmp.name).unlink(missing_ok=True)

    print("\n" + "=" * 60)
    print("Profile Summary")
    print("=" * 60)
    for name, s in scenarios:
        if name == "poll_roi_value":
            print(f"  {name:>15}: {s.get('calls', 0)} calls in {duration}s")
        else:
            print(f"  {name:>15}: FPS={s.get('fps', 0):.1f} CPU={s.get('cpu_pct', 0):.1f}% "
                  f"OCR_avg={s.get('ocr_avg_ms', 0):.1f}ms "
                  f"Loop_avg={s.get('loop_avg_ms', 0):.1f}ms")
    print()
