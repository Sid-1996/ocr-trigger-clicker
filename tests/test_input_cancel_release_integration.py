"""P0：Frida 後台輸入的「取消／Release」真實整合驗證（A / B / C）。

READ-ONLY 驗證：只呼叫產品既有 Input Backend API
（``core/16_bg_input.py`` → ``core/18_frida_bg.py``），不修改任何產品程式碼、
不改動既有測試、不放寬任何斷言。

被測目標是 ``devtools/input_target.py``（獨立 PyQt6 程序）；工作台
``devtools/input_test_bench.py`` 負責啟動目標程序與讀取狀態檔。

每個案例分三層記錄：

* Backend        — 後端 API 回傳值與 ``last_error()``
* Target Received — 目標程序實際收到的事件序列（含目標端時戳）
* Expected       — 事件順序與最終語意狀態是否符合預期

啟用方式（需要真實 Windows 桌面工作階段與 frida）：

    $env:OTC_RUN_INPUT_INTEGRATION = "1"
    uv run python -m pytest tests/test_input_cancel_release_integration.py -v --no-cov
"""

import os
import threading
import time

import pytest

from _loader import load_sibling

_bench = load_sibling("input_test_bench", "devtools/input_test_bench.py")
_bg = load_sibling("bg_input", "core/16_bg_input.py")
_target_mod = _bench.target_module()

pytestmark = pytest.mark.skipif(
    os.environ.get("OTC_RUN_INPUT_INTEGRATION") != "1",
    reason="真實整合測試：需設定 OTC_RUN_INPUT_INTEGRATION=1 才執行",
)

# 按住長度：必須大於目標狀態檔的 150ms 節流，才能在取消前確認目標端已收到 DOWN。
HOLD_MS = 1500
# 拖曳自然結束約 103ms（DOWN ~2ms → MOVE ~52ms → UP ~103ms）。
# 取消點必須落在 MOVE 送出之後、第二次 50ms 等待結束之前。
DRAG_CANCEL_DELAY = 0.075
DRAG_NATURAL_MS = 95.0
DRAG_TRIALS = 10


# ── 環境 ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def env():
    """真實目標程序 + Frida 模式的產品 Backend。"""
    os.environ["QT_QPA_PLATFORM"] = "windows"
    target = _bench.TargetProcess()
    target.start(timeout=90)
    _bg.set_method("frida")
    runner = _bench.BenchRunner(target, "frida")
    # 暖機：第一次呼叫包含 Frida attach（實測約 650ms），會污染時序量測。
    runner.run_click()
    yield target, runner
    runner.detach()
    target.stop()


# ── 讀取目標狀態 ────────────────────────────────────────────────────


def _baseline(target) -> int:
    st = target.read_status()
    return int(st.seq) if st else 0


def _new_events(target, baseline: int) -> list:
    st = target.read_status()
    if st is None:
        return []
    return [e for e in st.events if int(e.get("seq", 0)) > baseline]


def _wait_until(target, baseline: int, predicate, timeout: float = 6.0) -> list:
    """等待目標端狀態檔出現符合條件的新事件（狀態檔 150ms 節流寫入）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hit = [e for e in _new_events(target, baseline) if predicate(e)]
        if hit:
            return hit
        time.sleep(0.02)
    return []


def _timeline(events: list, t0: float) -> str:
    """事件序列（含目標端時戳；目標端與本機 time.monotonic() 同源）。"""
    if not events:
        return "（沒有事件）"
    parts = []
    for e in events:
        bits = [f"#{e.get('seq')}", str(e.get("type"))]
        if "x" in e:
            bits.append(f"({e.get('x')},{e.get('y')})")
        if "key" in e:
            bits.append(str(e.get("key")))
        bits.append(f"buttons={e.get('buttons')}")
        rel = (float(e.get("t", 0)) - t0) * 1000
        parts.append(f"{' '.join(bits)}@{rel:.0f}ms")
    return " | ".join(parts)


def _fmt(record: dict) -> str:
    return (
        f"\n  [Backend]      ok={record['backend_ok']}｜{record['backend_detail']}"
        f"\n  [Received]     ok={record['received_ok']}｜{record['received_detail']}"
        f"\n  [Expected]     ok={record['expected_ok']}｜{record['expected_detail']}"
        f"\n  [時間線]       {record['timeline']}"
        f"\n  [取消時序]     呼叫開始 +0ms → 取消 +{record['cancel_at_ms']:.0f}ms"
        f" → Backend 回傳 +{record['ended_at_ms']:.0f}ms（耗時 {record['elapsed_ms']:.0f}ms）"
        f"\n  [最終狀態]     pressed_keys={record['pressed_keys']}"
        f" mouse_buttons={record['mouse_buttons']} mouse_buttons_names={record['buttons_names']}"
    )


# ── A. Key Cancel / Release ─────────────────────────────────────────


def _key_case(env, key: str = "a", hold_ms: int = HOLD_MS) -> dict:
    """後台按鍵：DOWN →（取消）→ UP。

    使用 ``bg.send_hold_key``：DOWN 送出後進入可中斷等待，取消只會提早放開，
    UP 一定送出（``core/16_bg_input.py`` 的 finally 分支）。
    """
    target, runner = env
    baseline = _baseline(target)
    cancel = threading.Event()
    out: dict = {}

    def call():
        out["started"] = time.monotonic()
        out["ok"] = _bg.send_hold_key(target.hwnd, key, hold_ms, cancel)
        out["ended"] = time.monotonic()

    th = threading.Thread(target=call, daemon=True)
    th.start()
    # 先確認目標端確實收到 DOWN，再取消（不靠固定延遲猜測）。
    downs = _wait_until(target, baseline, lambda e: e.get("type") == "key_press")
    cancel_at = time.monotonic()
    cancel.set()
    th.join(timeout=20)
    ended = out.get("ended", time.monotonic())
    started = out.get("started", cancel_at)

    events, final = runner._wait_events(baseline, {"key_press", "key_release"}, 8.0)
    state = dict(final.state) if final else {}

    press_idx = [i for i, e in enumerate(events) if e.get("type") == "key_press"]
    rel_idx = [i for i, e in enumerate(events) if e.get("type") == "key_release"]
    want = key.upper()
    matched_press = [i for i in press_idx if str(events[i].get("key", "")).lower() == want.lower()]
    matched_rel = [i for i in rel_idx if str(events[i].get("key", "")).lower() == want.lower()]

    backend_ok = out.get("ok") is True
    received_ok = bool(matched_press) and bool(matched_rel)
    order_ok = bool(matched_press) and bool(matched_rel) and matched_press[0] < matched_rel[-1]
    held = want.lower() in [str(k).lower() for k in state.get("pressed_keys", [])]
    elapsed_ms = (ended - started) * 1000
    expected_ok = received_ok and order_ok and not held and elapsed_ms < hold_ms

    return {
        "backend_ok": backend_ok,
        "backend_detail": (
            f"send_hold_key 回傳 {out.get('ok')}；last_error={_bg.last_error() or '（無）'}"
        ),
        "received_ok": received_ok,
        "received_detail": (
            f"key_press×{len(matched_press)}（期望 {want}）、key_release×{len(matched_rel)}"
            f"；DOWN 在取消前已被目標確認（確認到 {len(downs)} 筆）"
        ),
        "expected_ok": expected_ok,
        "expected_detail": (
            f"press→release 順序正確={order_ok}；殘留 pressed_keys={state.get('pressed_keys')}；"
            f"耗時 {elapsed_ms:.0f}ms < 設定 {hold_ms}ms（提早結束）"
        ),
        "timeline": _timeline(events, started),
        "cancel_at_ms": (cancel_at - started) * 1000,
        "ended_at_ms": (ended - started) * 1000,
        "elapsed_ms": elapsed_ms,
        "pressed_keys": state.get("pressed_keys", []),
        "mouse_buttons": state.get("mouse_buttons", -1),
        "buttons_names": state.get("mouse_buttons_names", []),
    }


def test_a_key_cancel_release(env):
    """A. Key Cancel / Release：DOWN 已送出後取消，UP 仍必須送出且無殘留按住。"""
    record = _key_case(env)
    print(_fmt(record))
    assert record["backend_ok"], f"Backend 失敗：{record['backend_detail']}"
    assert record["received_ok"], f"目標未收到預期事件：{record['received_detail']}"
    assert record["expected_ok"], f"語意狀態不符預期：{record['expected_detail']}"


def test_a2_key_cancel_release_send_key_path(env):
    """A 補充：``bg.send_key``（120ms 持窗）路徑的取消行為。

    120ms 短於狀態檔 150ms 節流，無法在取消前從狀態檔確認 DOWN；
    因此此例只驗證「UP 仍送出＋無殘留按住」，DOWN 的確認由 A 主案例涵蓋。
    """
    target, runner = env
    baseline = _baseline(target)
    cancel = threading.Event()
    out: dict = {}

    def call():
        out["started"] = time.monotonic()
        out["ok"] = _bg.send_key(target.hwnd, "a", cancel)
        out["ended"] = time.monotonic()

    th = threading.Thread(target=call, daemon=True)
    th.start()
    time.sleep(0.04)
    cancel_at = time.monotonic()
    cancel.set()
    th.join(timeout=20)
    started = out.get("started", cancel_at)

    events, final = runner._wait_events(baseline, {"key_press", "key_release"}, 8.0)
    state = dict(final.state) if final else {}
    press = [e for e in events if e.get("type") == "key_press"]
    rel = [e for e in events if e.get("type") == "key_release"]
    held = "a" in [str(k).lower() for k in state.get("pressed_keys", [])]

    print(
        f"\n  [send_key 路徑] Backend ok={out.get('ok')}"
        f"｜事件 {_timeline(events, started)}"
        f"｜殘留 pressed_keys={state.get('pressed_keys')}"
    )
    assert out.get("ok") is True
    assert press and rel, f"未收到按下／放開：{_timeline(events, started)}"
    assert not held, f"目標端殘留按住：{state.get('pressed_keys')}"


# ── B. Click Cancel / Release ───────────────────────────────────────


def _click_case(env, hold_ms: int = HOLD_MS) -> dict:
    """後台點擊：DOWN →（取消）→ UP。

    使用 ``bg.click(..., hold_ms=...)``：DOWN 送出後進入可中斷等待，
    無論正常、取消或例外，finally 都會送出 UP
    （``core/16_bg_input.py::_click_postmessage``）。
    """
    target, runner = env
    regions = _target_mod._regions(900, 640)
    rect = regions["click"]
    cx, cy = int(rect.center().x()), int(rect.center().y())

    baseline = _baseline(target)
    cancel = threading.Event()
    out: dict = {}

    def call():
        out["started"] = time.monotonic()
        out["ok"] = _bg.click(target.hwnd, cx, cy, "left", hold_ms, cancel)
        out["ended"] = time.monotonic()

    th = threading.Thread(target=call, daemon=True)
    th.start()
    downs = _wait_until(target, baseline, lambda e: e.get("type") == "mouse_press")
    cancel_at = time.monotonic()
    cancel.set()
    th.join(timeout=20)
    ended = out.get("ended", time.monotonic())
    started = out.get("started", cancel_at)

    events, final = runner._wait_events(baseline, {"mouse_press", "mouse_release"}, 8.0)
    state = dict(final.state) if final else {}

    press_idx = [i for i, e in enumerate(events) if e.get("type") == "mouse_press"]
    rel_idx = [i for i, e in enumerate(events) if e.get("type") == "mouse_release"]
    backend_ok = out.get("ok") is True
    received_ok = bool(press_idx) and bool(rel_idx)
    order_ok = bool(press_idx) and bool(rel_idx) and press_idx[0] < rel_idx[-1]
    buttons = int(state.get("mouse_buttons", -1))
    elapsed_ms = (ended - started) * 1000
    expected_ok = received_ok and order_ok and buttons == 0 and elapsed_ms < hold_ms

    return {
        "backend_ok": backend_ok,
        "backend_detail": (
            f"click 回傳 {out.get('ok')}；last_error={_bg.last_error() or '（無）'}"
        ),
        "received_ok": received_ok,
        "received_detail": (
            f"mouse_press×{len(press_idx)}、mouse_release×{len(rel_idx)}"
            f"；DOWN 在取消前已被目標確認（確認到 {len(downs)} 筆）"
        ),
        "expected_ok": expected_ok,
        "expected_detail": (
            f"press→release 順序正確={order_ok}；最終 mouse_buttons={buttons}"
            f"（names={state.get('mouse_buttons_names')}）→ 無殘留按下；"
            f"耗時 {elapsed_ms:.0f}ms < 設定 {hold_ms}ms"
        ),
        "timeline": _timeline(events, started),
        "cancel_at_ms": (cancel_at - started) * 1000,
        "ended_at_ms": (ended - started) * 1000,
        "elapsed_ms": elapsed_ms,
        "pressed_keys": state.get("pressed_keys", []),
        "mouse_buttons": buttons,
        "buttons_names": state.get("mouse_buttons_names", []),
    }


def test_b_click_cancel_release(env):
    """B. Click Cancel / Release：DOWN 已送出後取消，UP 仍必須送出且無殘留按下。"""
    record = _click_case(env)
    print(_fmt(record))
    assert record["backend_ok"], f"Backend 失敗：{record['backend_detail']}"
    assert record["received_ok"], f"目標未收到預期事件：{record['received_detail']}"
    assert record["expected_ok"], f"語意狀態不符預期：{record['expected_detail']}"


# ── C. Drag Cancel / Release ────────────────────────────────────────


def _drag_case(env, cancel_delay: float = DRAG_CANCEL_DELAY) -> dict:
    """後台拖曳：DOWN → MOVE →（取消）→ UP。

    ``bg.drag`` 的 MOVE 在 DOWN 後約 50ms 送出，之後還有 50ms 的可中斷等待；
    取消點落在這之間時，UP 仍會送出（finally），且不會再送出額外 MOVE。
    """
    target, runner = env
    regions = _target_mod._regions(900, 640)
    area = regions["drag"]
    st = target.read_status()
    pos = (st.state.get("drag_pos") if st else None) or [0.0, 0.0]
    size = _target_mod.DRAG_OBJECT_SIZE
    x1 = int(min(max(pos[0] + size / 2, area.left() + 4), area.right() - 4))
    y1 = int(min(max(pos[1] + size / 2, area.top() + 4), area.bottom() - 4))
    x2, y2 = x1 + 60, y1 + 40

    baseline = _baseline(target)
    cancel = threading.Event()
    out: dict = {}

    def call():
        out["started"] = time.monotonic()
        out["ok"] = _bg.drag(target.hwnd, x1, y1, x2, y2, "left", cancel)
        out["ended"] = time.monotonic()

    th = threading.Thread(target=call, daemon=True)
    th.start()
    time.sleep(cancel_delay)
    cancel_at = time.monotonic()
    cancel.set()
    th.join(timeout=20)
    ended = out.get("ended", time.monotonic())
    started = out.get("started", cancel_at)

    events, final = runner._wait_events(
        baseline, {"mouse_press", "mouse_move", "mouse_release"}, 8.0
    )
    state = dict(final.state) if final else {}

    press_idx = [i for i, e in enumerate(events) if e.get("type") == "mouse_press"]
    rel_idx = [i for i, e in enumerate(events) if e.get("type") == "mouse_release"]
    # 拖曳中的 MOVE：按鍵仍按住的移動（spoof 游標定位的那筆 buttons=0 不算）。
    drag_moves = [
        i
        for i, e in enumerate(events)
        if e.get("type") == "mouse_move" and int(e.get("buttons", 0)) & 1
    ]
    moves_after_release = [i for i in drag_moves if rel_idx and i > rel_idx[-1]]
    backend_ok = out.get("ok") is True
    received_ok = bool(press_idx) and bool(drag_moves) and bool(rel_idx)
    order_ok = (
        bool(press_idx)
        and bool(drag_moves)
        and bool(rel_idx)
        and press_idx[0] < drag_moves[0] < rel_idx[-1]
    )
    buttons = int(state.get("mouse_buttons", -1))
    elapsed_ms = (ended - started) * 1000
    interrupted = elapsed_ms < DRAG_NATURAL_MS
    expected_ok = (
        received_ok and order_ok and not moves_after_release and buttons == 0 and interrupted
    )

    return {
        "backend_ok": backend_ok,
        "backend_detail": (f"drag 回傳 {out.get('ok')}；last_error={_bg.last_error() or '（無）'}"),
        "received_ok": received_ok,
        "received_detail": (
            f"mouse_press×{len(press_idx)}、拖曳中 mouse_move×{len(drag_moves)}、"
            f"mouse_release×{len(rel_idx)}"
        ),
        "expected_ok": expected_ok,
        "expected_detail": (
            f"press→move→release 順序正確={order_ok}；放開後額外 MOVE×{len(moves_after_release)}；"
            f"最終 mouse_buttons={buttons}（names={state.get('mouse_buttons_names')}）；"
            f"物件 drag_moved={state.get('drag_moved')} drag_distance={state.get('drag_distance')}"
            f" drag_pos={state.get('drag_pos')}；"
            f"耗時 {elapsed_ms:.0f}ms{' <' if interrupted else ' ≥'} 自然結束 {DRAG_NATURAL_MS:.0f}ms"
            f"（{'取消中斷' if interrupted else '未中斷'}）"
        ),
        "timeline": _timeline(events, started),
        "cancel_at_ms": (cancel_at - started) * 1000,
        "ended_at_ms": (ended - started) * 1000,
        "elapsed_ms": elapsed_ms,
        "pressed_keys": state.get("pressed_keys", []),
        "mouse_buttons": buttons,
        "buttons_names": state.get("mouse_buttons_names", []),
    }


def test_c_drag_cancel_release(env):
    """C. Drag Cancel / Release：取消後不再 MOVE，UP 仍送出且無殘留按下。

    拖曳總長只有約 100ms，狀態檔 150ms 節流無法在取消前確認 DOWN，
    因此以固定延遲取消，並以多次試跑統計通過率：

    * 安全不變量（必須 100%）：UP 仍送出且目標端無殘留按下狀態。
    * 情境條件（時序敏感）：DOWN→MOVE→UP 且取消真的中斷（耗時 < 95ms）。
    """
    records = []
    for _ in range(DRAG_TRIALS):
        records.append(_drag_case(env))
        time.sleep(0.2)

    safe_ok = [r for r in records if r["received_ok"] and r["mouse_buttons"] == 0]
    full_ok = [r for r in records if r["expected_ok"]]

    print(f"\n  C. Drag Cancel/Release（{DRAG_TRIALS} 次試跑）")
    for i, r in enumerate(records):
        print(
            f"   #{i + 1} Backend={r['backend_ok']} Received={r['received_ok']} "
            f"Expected={r['expected_ok']}｜取消 +{r['cancel_at_ms']:.0f}ms → "
            f"回傳 +{r['ended_at_ms']:.0f}ms｜{r['timeline']}"
        )
        print(
            f"       Expected：{r['expected_detail']}"
            f"｜最終 pressed_keys={r['pressed_keys']} mouse_buttons={r['mouse_buttons']}"
        )
    print(
        f"   安全不變量（UP 送出＋無殘留按下）通過 {len(safe_ok)}/{len(records)}；"
        f"完整情境（DOWN→MOVE→UP 且取消中斷）通過 {len(full_ok)}/{len(records)}"
    )

    assert len(safe_ok) == len(records), (
        f"安全不變量失敗：只有 {len(safe_ok)}/{len(records)} 次放開成功且無殘留按下"
    )
    assert full_ok, (
        "沒有任何一次試跑同時滿足 DOWN→MOVE→UP 與取消中斷；"
        f"逐次結果：{[(r['received_ok'], r['expected_ok']) for r in records]}"
    )
