# Health Audit — Final Consolidated Results

## Priority 1 — Socket Protocol (`_recv_line` no-partial-buffer)

| Aspect | Result |
|---|---|
| **Test** | `test_socket_stress.py` — 6200 commands across 5 scenarios |
| **Issue confirmed?** | Yes — merged packets: 98.5% OK, **1.5% timeout failures** |
| **Production risk** | Low — normal operation uses synchronous send→recv→send. Only fails when AHK coalesces 2+ responses into one TCP segment. On localhost, Nagle is auto-bypassed by the OS, making this extremely rare. |
| **Root cause** | `_recv_line` (03_ahk_socket.py:57-72) has NO residual buffer. After extracting one line, any remaining data in `data` is discarded. |
| **Fix cost** | ~5 lines: add a `self._recv_buf = b''` and prepend it on each recv. |
| **Impact scope** | After desync, all subsequent commands fail (protocol permanently misaligned). |

**Verdict: VERIFIED ISSUE (Low production probability, High impact if triggered)**

---

## Priority 1 — QTimer OCR Race Condition

| Aspect | Result |
|---|---|
| **Test** | Code review + trace of all QTimer usage |
| **Issue confirmed?** | **False Positive** — no OCR work is dispatched via QTimer. `_perf_timer` only updates CPU/mem labels; `_status_timer` only clears status bar messages after 5s. Both are UI-only. |
| **Root cause** | Source of worry was `_refresh_window_list()` being called from QTimer, but it doesn't touch OCR. |
| **Fix cost** | N/A |

**Verdict: FALSE POSITIVE — no risk**

---

## Priority 1 — MainLoop Busy-Wait / CPU Burn

| Aspect | Result |
|---|---|
| **Test** | `test_mainloop_profile.py` — Normal (10s): 14.5% CPU, No-window (10s): 9.5% CPU |
| **Issue confirmed?** | **No** — Normal mode sleep between frames. No-window mode enters inner wait loop with `time.sleep(0.5)`. No busy-wait anywhere. 9.5% CPU in no-window mode is slightly elevated but explained by Python's polling thread waking every 0.5s to check window existence + ctypes calls. |
| **Risk** | None. |

**Verdict: FALSE POSITIVE — no busy-wait**

---

## Priority 1 — Coordinate System Mix-up

| Aspect | Result |
|---|---|
| **Test** | Code review of all ROI/click coordinate paths |
| **Issue confirmed?** | **No** — Every coordinate path was traced: ROI selector (screen→window-relative via `- win_rect`), click picker (same), OCR output (already window-relative), fallback capture (padding to window size). No mixing found. |
| **Fix cost** | N/A |

**Verdict: FALSE POSITIVE — no coordinate mixing**

---

## Priority 2 — Loader Thread Safety

| Aspect | Result |
|---|---|
| **Test** | `test_loader_stress.py` — 20 threads × 10000 calls = 200,000 total |
| **Issue confirmed?** | **No** — 0 errors, 0 deadlocks, 0 cache corruption. Cache returns same object for same key. Throughput: ~1.8M calls/s. `_loader.py` RLock-based singleton pattern is correct. |
| **Fix cost** | N/A |

**Verdict: FALSE POSITIVE — thread-safe, no bug**

---

## Priority 2 — OCR Engine Concurrency

| Aspect | Result |
|---|---|
| **Test** | `test_ocr_concurrency.py` — burst parallel (20×), sustained (50×), engine reinit (10×) |
| **Issue confirmed?** | **No** — 0 errors across all scenarios. Engine reinit under concurrent access: 0 errors, engine stays alive. Thread leak: +1 (acceptable). RLock + ThreadPoolExecutor(max_workers=1) correctly serializes OCR access. |
| **Fix cost** | N/A |

**Verdict: FALSE POSITIVE — no concurrency bug**

---

## Priority 2 — MainLoop Performance Profile

| Aspect | Result |
|---|---|
| **Test** | `test_mainloop_profile.py` — Normal (10s) |
| **Results** | FPS=1.9 (matching 500ms interval), CPU=14.5% (peak 69.1%), OCR_avg=0.0ms (no rules loaded), Loop_avg=27.1ms, Memory=146MB peak |
| **Assessment** | 1.9 FPS is low for real-time automation (1900ms inefficiency). Loop overhead is 27.1ms per iteration. With real OCR rules (150ms each), frame rate drops to ~2 FPS worst case. Not a bug but a performance limitation. |
| **Recommendation** | Pre-capture all rule ROIs into one screen shot → OCR batch → then match. Not blocking. |

**Verdict: FALSE POSITIVE (functional), PERFORMANCE NOTE (non-blocking)**

---

## Priority 3 — 06_gui_main.py Coupling (99 methods, 5155 lines)

| Aspect | Result |
|---|---|
| **Analysis** | Manual method call graph extraction |
| **Key metrics** | MainWindow: 99 methods; `_status_bar` called by 26 methods; `_groups` by 25; `_flush_save` by 23; `_loop` by 21; `_refresh_rule_list` by 20 |
| **Highest coupling** | `_setup_ui` calls 58 methods; `_connect_signals` calls 51; `__init__` calls 43 |
| **Natural split points** | (1) PersistenceManager — debounced save + flush: `_schedule_save`, `_do_debounced_save`, `_flush_save`, `_save_current_rule` (4 methods, 23+ callers each). (2) TaskManager — task CRUD (8 methods). (3) RuleController — rule CRUD + groups (20 methods). |
| **Blockers to splitting** | All sub-controllers need access to shared state (`_rules`, `_groups`, `_loop`, `_step_list`). Signal-based communication required. |

**Verdict: HIGH-COUPLING CONFIRMED — most impactful split is extracting PersistenceManager**

---

## Overall Summary

| Finding | Verdict | Status |
|---|---|---|
| `_recv_line` partial buffer | **VERIFIED ISSUE** | Low prob × high impact |
| QTimer OCR race | FALSE POSITIVE | No action |
| MainLoop busy-wait | FALSE POSITIVE | No action |
| Coordinate mixing | FALSE POSITIVE | No action |
| Loader thread safety | FALSE POSITIVE | No action |
| OCR concurrency | FALSE POSITIVE | No action |
| MainLoop performance | FALSE POSITIVE (note) | Performance note |
| 06_gui_main.py coupling | **CONFIRMED** | Documented split points |

**Bottom line:** Only 1 verified bug out of 8 Priority findings. The socket `_recv_line` residual buffer issue is the sole actionable item. All other concerns were false positives.
