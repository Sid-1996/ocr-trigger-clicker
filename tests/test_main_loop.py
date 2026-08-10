import logging
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from conftest import make_main_loop as _make_ml  # noqa: E402

from _loader import load_sibling  # noqa: E402
from core.rule_models import Rule, RuleGroup, Step  # noqa: E402

_tmpl = load_sibling("template_matching", "core/11_template_matching.py")
img_to_b64 = _tmpl.img_to_b64


# Import the MainLoop module using _loader (module name starts with digit)
_ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
StepContext = _ml_mod.StepContext
StepResult = _ml_mod.StepResult


# ── StepResult / StepContext ──


def test_step_result():
    sr = StepResult("continue")
    assert sr.action == "continue"
    assert sr.step_index == -1
    sr2 = StepResult("stop")
    assert sr2.action == "stop"
    sr3 = StepResult("jump_step", step_index=4)
    assert sr3.action == "jump_step"
    assert sr3.step_index == 4


def test_step_context():
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    assert ctx.matched_text is None
    _ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
    ocr = _ocr.OcrResult(text="test", x=0, y=0, w=10, h=10, confidence=0.9)
    ctx.matched_text = ocr
    assert ctx.matched_text.text == "test"


# ── _to_screen_coords ──


def test_to_screen_coords():
    ml = _make_ml()
    sx, sy = ml._to_screen_coords({"x": 100, "y": 200, "w": 800, "h": 600}, 50, 60)
    assert sx == 150 and sy == 260


# ── _run_step dispatcher ──


def test_run_step_dispatcher():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    ml._send_click = lambda x, y, button="left", hold_ms=0: True  # 防止測試送出真實輸入
    ml._send_key = lambda key: True
    ml._send_scroll = lambda direction: True
    for hn in [
        "detect",
        "click",
        "key",
        "wait",
        "jump",
        "drag",
        "scroll",
        "match_image",
        "compare",
        "notify",
    ]:
        step = Step(type=hn, params={})
        result = ml._run_step(step, ctx, test_rule)
        assert isinstance(result, StepResult), f"{hn} should return StepResult"
    unknown_step = Step(type="nonexistent", params={})
    result = ml._run_step(unknown_step, ctx, test_rule)
    assert result.action == "stop"


# ── _handle_jump with group restriction ──


def test_handle_jump_group_restriction():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    ml._rules = [
        Rule(id="rule_a", name="A", enabled=True, steps=[]),
        Rule(id="rule_b", name="B", enabled=True, steps=[]),
        Rule(id="rule_c", name="C", enabled=True, steps=[]),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [
        RuleGroup(id="g1", name="G1", rule_ids=["rule_a", "rule_b"]),
    ]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    result = ml._handle_jump({"rule_id": "rule_b"}, ctx, test_rule)
    assert result.action == "stop"
    assert ml._rule_in_group_ptr == 1
    ml._rule_in_group_ptr = 0
    result = ml._handle_jump({"rule_id": "rule_c"}, ctx, test_rule)
    assert result.action == "stop"
    assert ml._rule_in_group_ptr == 0
    result = ml._handle_jump({"rule_id": "ghost"}, ctx, test_rule)
    assert result.action == "stop"
    assert ml._rule_in_group_ptr == 0


# ── _handle_detect empty text ──


def test_handle_detect_empty_text():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    result = ml._handle_detect({"text": "", "roi": None}, ctx, test_rule)
    assert result.action == "stop"


# ── _ocr_region cache-hit marker ──


def test_ocr_region_cache_hit_marker():
    """Second detect on a ROI served by _ocr_region superset cache must flag
    ocr_cache_hit and _build_ok_detail must render the shared-cache marker."""
    ml = _make_ml()
    ml._frame_ocr_cache = {}
    ml._ocr_cache_hits = 0
    calls = []

    OrigResult = _ml_mod.OcrResult

    def fake_recognize(img, **kw):
        calls.append(int(img.shape[1]))
        # Result at (0,0) in sub-image; after shift by roi1's x1=10,y=10
        # lands at (10,10,10,10) — well inside roi2 at (10,10,30,30).
        return [OrigResult(text="對話", x=0, y=0, w=10, h=10, confidence=0.9)]

    orig = _ml_mod.recognize
    _ml_mod.recognize = fake_recognize
    try:
        img = np.zeros((400, 400, 3), dtype=np.uint8)
        # roi1 is large, roi2 is a strict subset fully containing the shifted result
        roi1 = {"x": 10, "y": 10, "w": 100, "h": 60}
        roi2 = {"x": 10, "y": 10, "w": 30, "h": 30}

        hits_before = ml._ocr_cache_hits
        ml._ocr_region(img, roi1)
        assert len(calls) == 1, "first call should run recognize"
        assert ml._ocr_cache_hits == hits_before, "first call is a miss"

        hits_before = ml._ocr_cache_hits
        r2 = ml._ocr_region(img, roi2)
        assert ml._ocr_cache_hits > hits_before, "nested ROI must be flagged as cache hit"
        assert len(calls) == 1, "nested ROI should reuse cache, no extra recognize"

        # Verify the detail renderer shows the marker
        ctx = StepContext(img=img, rect={"x": 0, "y": 0, "w": 400, "h": 400})
        ctx.matched_text = r2[0]
        ctx.ocr_cache_hit = True
        ctx.ocr_elapsed_ms = 0
        detail = ml._build_ok_detail(Step(type="detect", params={}), ctx)
        assert "共用快取" in detail, f"renderer should show shared-cache marker, got: {detail}"
        assert "0ms" in detail
    finally:
        _ml_mod.recognize = orig


# ── _handle_click without matched_text ──


def test_handle_click_no_match():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    ctx.matched_text = None
    result = ml._handle_click({"target": "text_center"}, ctx, test_rule)
    assert result.action == "stop"


# ── _handle_click cursor target (background = window center) ──


def test_handle_click_cursor_bg():
    ml = _make_ml()
    ml._window_hwnd = 12345
    ml._rule_config_ctrl = type(
        "FakeRuleConfig", (), {"get_setting": lambda self, win, key="interaction_mode": "dxcam"}
    )()
    captured = {}
    ml._send_click = lambda x, y, button="left", hold_ms=0: (
        captured.update(x=x, y=y, button=button, hold_ms=hold_ms) or True
    )
    ml._activate_window = lambda: True
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8),
        rect={"x": 100, "y": 200, "w": 800, "h": 600},
    )
    result = ml._handle_click(
        {"target": "cursor", "button": "right", "hold_ms": 150}, ctx, test_rule
    )
    assert result.action == "continue"
    assert captured["x"] == 100 + 400
    assert captured["y"] == 200 + 300
    assert captured["button"] == "right"
    assert captured["hold_ms"] == 150
    assert ctx.triggered


# ── 動作後延遲 after_delay_ms（_run_rule 單一 choke point）──


def test_after_delay_waits_timeout_after_click():
    ml = _make_ml()
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    captured = {}
    ml._stop_event.wait = lambda timeout: captured.update(timeout=timeout) or False
    step = Step(type="click", params={"target": "custom", "x": 10, "y": 10, "after_delay_ms": 750})
    rule = Rule(id="ad-wait", name="ad-wait", enabled=True, steps=[step])
    ml._run_rule(rule, ctx.img, ctx.rect, ctx)
    assert captured == {"timeout": 0.75}


def test_after_delay_interrupt_skips_rest():
    ml = _make_ml()
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    ml._stop_event.wait = lambda timeout: True  # 模擬暫停/停止中斷
    step = Step(type="click", params={"target": "custom", "x": 10, "y": 10, "after_delay_ms": 500})
    rule = Rule(
        id="ad-int",
        name="ad-int",
        enabled=True,
        steps=[step, Step(type="wait", params={"ms": 10})],
    )
    ml._run_rule(rule, ctx.img, ctx.rect, ctx)
    # 中斷 → 動作後延遲回 stop，尾隨的 wait 步驟不應執行（不打「ok」log）
    assert f"{rule.name}:1" not in ml._last_exec_log


def test_after_delay_zero_skips_wait():
    ml = _make_ml()
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    captured = {}
    ml._stop_event.wait = lambda timeout: captured.update(timeout=timeout) or False
    step = Step(type="click", params={"target": "custom", "x": 10, "y": 10, "after_delay_ms": 0})
    rule = Rule(id="ad-zero", name="ad-zero", enabled=True, steps=[step])
    ml._run_rule(rule, ctx.img, ctx.rect, ctx)
    assert captured == {}  # 0 → 不等待


# ── _send_click frida 模式派發 ──


def test_send_click_frida_dispatch(monkeypatch):
    ml = _make_ml()
    ml._window_hwnd = 12345
    ml._rule_config_ctrl = type(
        "FakeRuleConfig", (), {"get_setting": lambda self, win, key="interaction_mode": "frida"}
    )()
    _bg = load_sibling("bg_input", "core/16_bg_input.py")
    captured = {}
    monkeypatch.setattr(
        _bg,
        "click",
        lambda hwnd, x, y, button="left", hold_ms=0: (
            captured.update(hwnd=hwnd, x=x, y=y, button=button, hold_ms=hold_ms) or True
        ),
    )
    try:
        ok = _ml_mod.MainLoop._send_click(ml, 150, 250, "left", 0)
    finally:
        _bg.set_method("pynput")
    assert ok
    assert captured == {"hwnd": 12345, "x": 150, "y": 250, "button": "left", "hold_ms": 0}


# ── _send_click pynput 分支傳遞 auto_restore_cursor ──


def _fake_cfg(**kw):
    return type(
        "FakeRuleConfig",
        (),
        {
            "get_setting": lambda self, win, key="interaction_mode", default=None: kw.get(
                key, default
            )
        },
    )()


def test_send_click_forwards_restore_cursor_enabled(monkeypatch):
    ml = _make_ml()
    ml._rule_config_ctrl = _fake_cfg(interaction_mode="pynput", auto_restore_cursor=True)
    captured = {}
    monkeypatch.setattr(
        _ml_mod._input_mod,
        "send_click",
        lambda x, y, button="left", hold_ms=0, restore_cursor=True: (
            captured.update(x=x, y=y, button=button, hold_ms=hold_ms, restore_cursor=restore_cursor)
            or True
        ),
    )
    ok = _ml_mod.MainLoop._send_click(ml, 150, 250, "left", 0)
    assert ok
    assert captured == {"x": 150, "y": 250, "button": "left", "hold_ms": 0, "restore_cursor": True}


def test_send_click_forwards_restore_cursor_disabled(monkeypatch):
    ml = _make_ml()
    ml._rule_config_ctrl = _fake_cfg(interaction_mode="pynput", auto_restore_cursor=False)
    captured = {}
    monkeypatch.setattr(
        _ml_mod._input_mod,
        "send_click",
        lambda x, y, button="left", hold_ms=0, restore_cursor=True: (
            captured.update(restore_cursor=restore_cursor) or True
        ),
    )
    ok = _ml_mod.MainLoop._send_click(ml, 150, 250, "left", 0)
    assert ok and captured["restore_cursor"] is False


# ── _handle_on_fail (stop/key) ──


def test_handle_on_fail_stop_key():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    result = ml._handle_on_fail({"on_fail": "stop"}, ctx, test_rule)
    assert result.action == "stop"

    mock_called = []
    _orig_k = ml._send_key
    ml._send_key = lambda k: mock_called.append(k) or True
    result = ml._handle_on_fail({"on_fail": {"action": "key", "key": "Escape"}}, ctx, test_rule)
    ml._send_key = _orig_k
    assert result.action == "continue"
    assert mock_called == ["Escape"]


# ── _handle_on_fail notify (stop_groups) ──


def test_handle_on_fail_notify_stop_groups():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    ctx.triggered = False
    ml._stop_event.clear()
    ml._active_group_ids = ["group_A", "group_B", "group_C"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._groups = [
        RuleGroup(id="group_A", name="A", rule_ids=[]),
        RuleGroup(id="group_B", name="B", rule_ids=[]),
        RuleGroup(id="group_C", name="C", rule_ids=[]),
    ]
    notify_result = ml._handle_on_fail(
        {
            "on_fail": {
                "action": "notify",
                "message": "測試通知",
                "stop_groups": ["group_A", "group_B"],
            }
        },
        ctx,
        test_rule,
    )
    assert notify_result.action == "stop"
    assert not ctx.triggered
    assert "group_A" not in ml._active_group_ids
    assert "group_B" not in ml._active_group_ids
    assert "group_C" in ml._active_group_ids
    assert ml._group_queue_idx == 0
    assert ml._rule_in_group_ptr == 0
    assert not ml._stop_event.is_set()


def test_handle_on_fail_notify_current_group():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    ml._active_group_ids = ["group_X", "group_Y"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._groups = [
        RuleGroup(id="group_X", name="X", rule_ids=[]),
        RuleGroup(id="group_Y", name="Y", rule_ids=[]),
    ]
    ctx.triggered = False
    notify_result = ml._handle_on_fail(
        {"on_fail": {"action": "notify", "message": "單組停止"}}, ctx, test_rule
    )
    assert notify_result.action == "stop"
    assert not ctx.triggered
    assert "group_X" not in ml._active_group_ids
    assert "group_Y" in ml._active_group_ids
    assert not ml._stop_event.is_set()


def test_handle_on_fail_notify_not_current_group():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    ml._active_group_ids = ["group_P", "group_Q"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._groups = [
        RuleGroup(id="group_P", name="P", rule_ids=[]),
        RuleGroup(id="group_Q", name="Q", rule_ids=[]),
    ]
    ctx.triggered = False
    notify_result = ml._handle_on_fail(
        {"on_fail": {"action": "notify", "stop_groups": ["group_Q"], "message": "stop Q"}},
        ctx,
        test_rule,
    )
    assert notify_result.action == "stop"
    assert ctx.triggered
    assert "group_P" in ml._active_group_ids
    assert "group_Q" not in ml._active_group_ids
    assert not ml._stop_event.is_set()


def test_handle_on_fail_notify_default_message_with_group():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    warned = []
    ml.on_warning = warned.append
    ml._active_group_ids = ["group_A", "group_B"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._groups = [
        RuleGroup(id="group_A", name="A", rule_ids=[]),
        RuleGroup(id="group_B", name="B", rule_ids=[]),
    ]
    notify_result = ml._handle_on_fail(
        {"on_fail": {"action": "notify", "stop_groups": ["group_B"]}}, ctx, test_rule
    )
    assert notify_result.action == "stop"
    assert ctx.triggered
    assert warned, "預設訊息應觸發 on_warning"
    assert "分派測試" in warned[0]
    assert "B" in warned[0]
    assert "group_B" not in ml._active_group_ids
    assert "group_A" in ml._active_group_ids


def test_handle_on_fail_notify_default_message_current_group():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    warned = []
    ml.on_warning = warned.append
    ml._active_group_ids = ["group_X", "group_Y"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._groups = [
        RuleGroup(id="group_X", name="X", rule_ids=[]),
        RuleGroup(id="group_Y", name="Y", rule_ids=[]),
    ]
    notify_result = ml._handle_on_fail(
        {"on_fail": {"action": "notify", "message": ""}}, ctx, test_rule
    )
    assert notify_result.action == "stop"
    assert not ctx.triggered
    assert warned
    assert "分派測試" in warned[0]
    assert "X" in warned[0]
    assert "group_X" not in ml._active_group_ids


def test_handle_on_fail_notify_default_no_groups_stopped():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    warned = []
    ml.on_warning = warned.append
    ml._active_group_ids = []
    ml._groups = []
    notify_result = ml._handle_on_fail(
        {"on_fail": {"action": "notify", "message": "   "}}, ctx, test_rule
    )
    assert notify_result.action == "stop"
    assert warned
    assert "分派測試" in warned[0]
    assert "未停止任何群組" in warned[0]


def test_handle_on_fail_notify_placeholder_replacement():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    warned = []
    ml.on_warning = warned.append
    ml._active_group_ids = ["group_A", "group_B"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._groups = [
        RuleGroup(id="group_A", name="A", rule_ids=[]),
        RuleGroup(id="group_B", name="B", rule_ids=[]),
    ]
    notify_result = ml._handle_on_fail(
        {
            "on_fail": {
                "action": "notify",
                "stop_groups": ["group_A", "group_B"],
                "message": "警告：{rule} 失敗，已停 {group}",
            }
        },
        ctx,
        test_rule,
    )
    assert notify_result.action == "stop"
    assert warned
    assert "警告：分派測試 失敗，已停 A、B" in warned[0]
    assert "group_A" not in ml._active_group_ids
    assert "group_B" not in ml._active_group_ids


def test_handle_on_fail_notify_plain_custom_message():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    warned = []
    ml.on_warning = warned.append
    ml._active_group_ids = ["group_A"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._groups = [RuleGroup(id="group_A", name="A", rule_ids=[])]
    notify_result = ml._handle_on_fail(
        {"on_fail": {"action": "notify", "message": "直接自訂文字"}}, ctx, test_rule
    )
    assert notify_result.action == "stop"
    assert warned
    assert warned[0] == "[通知] 直接自訂文字"


def test_handle_on_fail_notify_brace_in_message_no_crash():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    warned = []
    ml.on_warning = warned.append
    ml._active_group_ids = ["group_A"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._groups = [RuleGroup(id="group_A", name="A", rule_ids=[])]
    notify_result = ml._handle_on_fail(
        {"on_fail": {"action": "notify", "message": "含 {foo} 大括號"}}, ctx, test_rule
    )
    assert notify_result.action == "stop"
    assert warned
    assert warned[0] == "[通知] 含 {foo} 大括號"


# ── _process_rules wait-only does not advance ──


def test_process_rules_wait_no_advance():
    ml = _make_ml()
    ml._stop_event.clear()
    ml._rules = [
        Rule(
            id="r0",
            name="規則0",
            enabled=True,
            steps=[Step(type="wait", params={"ms": 0})],
        ),
        Rule(
            id="r1",
            name="規則1",
            enabled=True,
            steps=[Step(type="wait", params={"ms": 0})],
        ),
        Rule(
            id="r_bg",
            name="背景",
            enabled=True,
            background=True,
            steps=[Step(type="wait", params={"ms": 0})],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", rule_ids=["r0", "r1"])]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    rect = {"x": 0, "y": 0, "w": 100, "h": 100}
    ml._process_rules(img, rect)
    assert ml._rule_in_group_ptr == 0


# ── _process_rules skips disabled ──


def test_process_rules_skips_disabled():
    ml = _make_ml()
    ml._rules = [
        Rule(
            id="r0",
            name="規則0",
            enabled=False,
            steps=[Step(type="wait", params={"ms": 0})],
        ),
        Rule(
            id="r1",
            name="規則1",
            enabled=True,
            steps=[Step(type="wait", params={"ms": 0})],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", rule_ids=["r0", "r1"])]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    rect = {"x": 0, "y": 0, "w": 100, "h": 100}
    ml._process_rules(img, rect)
    assert ml._rule_in_group_ptr == 1


# ── _should_process_static_frame ──


def test_should_process_static_frame():
    ml = _make_ml()

    ml._rules = [
        Rule(
            id="r_detect",
            name="有detect",
            enabled=True,
            steps=[Step(type="detect", params={"text": "hi"})],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", rule_ids=["r_detect"])]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    ml._update_has_detect()
    assert ml._should_process_static_frame()

    ml._rules = [
        Rule(
            id="r_no_detect",
            name="無detect",
            enabled=True,
            steps=[Step(type="wait", params={"ms": 100})],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", rule_ids=["r_no_detect"])]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    ml._update_has_detect()
    assert not ml._should_process_static_frame()

    ml._rules = [
        Rule(
            id="r_disabled",
            name="禁用",
            enabled=False,
            steps=[Step(type="detect", params={"text": "hi"})],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", rule_ids=["r_disabled"])]
    ml.set_active_groups(["g1"])
    ml._rule_in_group_ptr = 0
    ml._update_has_detect()
    assert not ml._should_process_static_frame()


# ── _handle_wait stop-event interrupt ──


def test_handle_wait_interrupt():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    ml._stop_event.set()
    result = ml._handle_wait({"ms": 10000}, ctx, test_rule)
    ml._stop_event.clear()
    assert result.action == "stop"


# ── _handle_match_image ──


def test_handle_match_image():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])

    _mi_img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(_mi_img, (10, 10), (30, 30), (180, 200, 220), -1)
    cv2.rectangle(_mi_img, (15, 15), (25, 25), (50, 60, 70), -1)
    _mi_tpl = _mi_img[10:31, 10:31].copy()
    _mi_tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    _mi_tmp.close()
    cv2.imwrite(_mi_tmp.name, _mi_tpl)
    _mi_ctx = StepContext(img=_mi_img, rect={"x": 0, "y": 0, "w": 100, "h": 100})
    result = ml._handle_match_image(
        {"template": _mi_tmp.name, "threshold": 0.5}, _mi_ctx, test_rule
    )
    assert result.action == "continue"
    assert _mi_ctx.matched_text is not None
    assert _mi_ctx.matched_text.center_x == 10 + 21 // 2

    _blank = np.zeros((100, 100, 3), dtype=np.uint8)
    _blank_ctx = StepContext(img=_blank, rect=_mi_ctx.rect)
    result2 = ml._handle_match_image(
        {"template": _mi_tmp.name, "threshold": 0.8}, _blank_ctx, test_rule
    )
    assert result2.action == "stop"

    result3 = ml._handle_match_image({"template": ""}, _mi_ctx, test_rule)
    assert result3.action == "stop"

    _mi_ctx2 = StepContext(img=_mi_img, rect={"x": 0, "y": 0, "w": 100, "h": 100})
    _b64_data = img_to_b64(_mi_tpl)
    result4 = ml._handle_match_image(
        {"template_data": _b64_data, "threshold": 0.5}, _mi_ctx2, test_rule
    )
    assert result4.action == "continue"
    assert _mi_ctx2.matched_text.center_x == 10 + 21 // 2

    _skip_ctx = StepContext(img=_blank, rect=_mi_ctx.rect)
    result5 = ml._handle_match_image(
        {"template": _mi_tmp.name, "threshold": 0.8, "on_fail": {"action": "skip", "skip_to": 5}},
        _skip_ctx,
        test_rule,
    )
    assert result5.action == "jump_step"
    assert result5.step_index == 5
    Path(_mi_tmp.name).unlink(missing_ok=True)


# ── _handle_on_fail skip ──


def test_handle_on_fail_skip():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    _skip_result = ml._handle_on_fail({"on_fail": {"action": "skip", "skip_to": 3}}, ctx, test_rule)
    assert _skip_result.action == "jump_step"
    assert _skip_result.step_index == 3
    _stop_result = ml._handle_on_fail({"on_fail": "stop"}, ctx, test_rule)
    assert _stop_result.action == "stop"
    ml._send_key = lambda key: True  # 防止測試送出真實按鍵
    _key_result = ml._handle_on_fail({"on_fail": {"action": "key", "key": "F5"}}, ctx, test_rule)
    assert _key_result.action == "continue"


# ── Single group once mode ──


def test_single_group_once_mode():
    ml = _make_ml()
    ml._rules = [
        Rule(id="r1", name="R1", enabled=True, steps=[Step(type="wait", params={"ms": 0})]),
        Rule(id="r2", name="R2", enabled=True, steps=[Step(type="wait", params={"ms": 0})]),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", mode="once", rule_ids=["r1", "r2"])]
    ml.set_active_groups(["g1"])
    ml._group_rounds_completed.clear()
    ml._stop_event.clear()
    ml._rule_in_group_ptr = 0
    ml._advance_rule_in_group()
    assert ml._rule_in_group_ptr == 1
    assert not ml._stop_event.is_set()
    ml._advance_rule_in_group()
    assert ml._group_queue_idx == 1
    assert ml._stop_event.is_set()


# ── Multiple groups sequential ──


def test_multiple_groups_sequential():
    ml = _make_ml()
    ml._rules = [
        Rule(id="r1", name="R1", enabled=True, steps=[Step(type="wait", params={"ms": 0})]),
        Rule(id="r2", name="R2", enabled=True, steps=[Step(type="wait", params={"ms": 0})]),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [
        RuleGroup(id="ga", name="Group A", mode="once", rule_ids=["r1"]),
        RuleGroup(id="gb", name="Group B", mode="once", rule_ids=["r2"]),
    ]
    ml.set_active_groups(["ga", "gb"])
    ml._group_rounds_completed.clear()
    ml._stop_event.clear()
    ml._rule_in_group_ptr = 0
    assert ml._current_group() is not None
    assert ml._current_group().id == "ga"
    ml._advance_group_queue()
    assert ml._group_queue_idx == 1
    assert ml._current_group().id == "gb"
    assert not ml._stop_event.is_set()
    ml._advance_group_queue()
    assert ml._group_queue_idx == 2
    assert ml._stop_event.is_set()


# ── Loop+parallel groups ──


def test_loop_parallel_groups():
    ml = _make_ml()
    ml._rules = [
        Rule(id="ra", name="A", enabled=True, steps=[Step(type="wait", params={"ms": 0})]),
        Rule(id="rb", name="B", enabled=True, steps=[Step(type="wait", params={"ms": 0})]),
        Rule(id="rc", name="C", enabled=True, steps=[Step(type="wait", params={"ms": 0})]),
        Rule(id="rd", name="D", enabled=True, steps=[Step(type="wait", params={"ms": 0})]),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [
        RuleGroup(id="gp1", name="P1", mode="loop", order="parallel", rule_ids=["ra", "rb"]),
        RuleGroup(id="gp2", name="P2", mode="loop", order="parallel", rule_ids=["rc", "rd"]),
    ]
    ml._active_group_ids = ["gp1", "gp2"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    rect = {"x": 0, "y": 0, "w": 100, "h": 100}
    n_ok = 0
    for _ in range(10):
        ml._process_rules(img, rect)
        n_ok += 1
    assert "gp1" in ml._active_group_ids
    assert "gp2" in ml._active_group_ids

    ml._groups.append(RuleGroup(id="g_once", name="Once", mode="once", rule_ids=["ra"]))
    ml._active_group_ids = ["gp1", "gp2", "g_once"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._group_rounds_completed.clear()
    ml._process_rules(img, rect)
    current = ml._current_group()
    assert current and current.id == "g_once"


# ── Jump within same group ──


def test_jump_within_group():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    ml._rules = [
        Rule(
            id="j1",
            name="J1",
            enabled=True,
            steps=[Step(type="wait", params={"ms": 0})],
        ),
        Rule(
            id="j2",
            name="J2",
            enabled=True,
            steps=[Step(type="wait", params={"ms": 0})],
        ),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="gj", name="GJ", rule_ids=["j1", "j2"])]
    ml.set_active_groups(["gj"])
    ml._rule_in_group_ptr = 0
    result = ml._handle_jump({"rule_id": "j2"}, ctx, test_rule)
    assert result.action == "stop"
    assert ml._rule_in_group_ptr == 1


# ── Jump across groups ──


def test_jump_across_groups():
    ml = _make_ml()
    test_rule = Rule(id="rule_dispatch", name="分派測試", enabled=True, steps=[])
    ctx = StepContext(
        img=np.zeros((10, 10, 3), dtype=np.uint8), rect={"x": 0, "y": 0, "w": 100, "h": 100}
    )
    ml._rules = [
        Rule(
            id="xa",
            name="XA",
            enabled=True,
            steps=[Step(type="wait", params={"ms": 0})],
        ),
        Rule(id="xb", name="XB", enabled=True, steps=[]),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [
        RuleGroup(id="gxa", name="GXA", rule_ids=["xa"]),
        RuleGroup(id="gxb", name="GXB", rule_ids=["xb"]),
    ]
    ml.set_active_groups(["gxa"])
    ml._rule_in_group_ptr = 0
    result = ml._handle_jump({"rule_id": "xb"}, ctx, test_rule)
    assert result.action == "stop"
    assert ml._rule_in_group_ptr == 0


# ── Background rule prevents stop ──


def test_background_prevents_stop():
    ml = _make_ml()
    ml._rules = [
        Rule(
            id="bg1",
            name="常駐",
            enabled=True,
            background=True,
            steps=[Step(type="wait", params={"ms": 0})],
        ),
        Rule(id="r1", name="R1", enabled=True, steps=[Step(type="wait", params={"ms": 0})]),
    ]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [RuleGroup(id="g1", name="G1", mode="once", rule_ids=["r1"])]
    ml.set_active_groups(["g1"])
    ml._group_rounds_completed.clear()
    ml._stop_event.clear()
    ml._rule_in_group_ptr = 0
    ml._group_queue_idx = 0
    ml._advance_rule_in_group()
    assert not ml._stop_event.is_set()

    ml._rules[0].enabled = False
    ml._groups = [RuleGroup(id="g1", name="G1", mode="once", rule_ids=["r1"])]
    ml.set_active_groups(["g1"])
    ml._group_rounds_completed.clear()
    ml._stop_event.clear()
    ml._rule_in_group_ptr = 0
    ml._group_queue_idx = 0
    ml._advance_rule_in_group()
    assert ml._stop_event.is_set()


# ── _resolve_roi ──


def test_resolve_roi():
    ml = _make_ml()
    rect = {"w": 1920, "h": 1080}
    r = ml._resolve_roi({"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.3}, rect)
    assert r == {"x": 192, "y": 216, "w": 960, "h": 324}
    r = ml._resolve_roi({"x": 0, "y": 0, "w": 0, "h": 0}, rect)
    assert r == {"x": 0, "y": 0, "w": 0, "h": 0}
    r = ml._resolve_roi({"x": 100, "y": 200, "w": 300, "h": 400}, rect)
    assert r == {"x": 100, "y": 200, "w": 300, "h": 400}


# ── _resolve_point ──


def test_resolve_point():
    ml = _make_ml()
    rect = {"w": 1920, "h": 1080}
    px, py = ml._resolve_point(0.5, 0.25, rect)
    assert (px, py) == (960, 270)
    px, py = ml._resolve_point(123, 456, rect)
    assert (px, py) == (123, 456)


# ── fail_duration_sec ──


def test_fail_duration_sec():
    ml = _make_ml()

    _fd25_tpl = np.zeros((20, 20, 3), dtype=np.uint8)
    cv2.rectangle(_fd25_tpl, (5, 5), (15, 15), (200, 200, 200), -1)
    _fd25_b64 = img_to_b64(_fd25_tpl)

    _fd25_rule = Rule(
        id="rule_fd25",
        name="FD測試",
        enabled=True,
        steps=[
            Step(
                type="match_image",
                params={
                    "template": "",
                    "template_data": _fd25_b64,
                    "threshold": 0.99,
                    "on_fail": {
                        "action": "notify",
                        "message": "FD timeout expired",
                        "fail_duration_sec": 5.0,
                    },
                },
            ),
            Step(
                type="detect",
                params={
                    "text": "不該執行",
                    "match_mode": "fuzzy",
                    "on_fail": "stop",
                },
            ),
        ],
    )

    _fd25_blank = np.zeros((100, 100, 3), dtype=np.uint8)
    _fd25_rect = {"x": 0, "y": 0, "w": 100, "h": 100}
    _fd25_ctx = StepContext(img=_fd25_blank, rect=_fd25_rect)

    _fd25_detect_calls = [0]
    _fd25_orig_ocr = ml._ocr_region

    def _fd25_count_ocr(*a, **kw):
        _fd25_detect_calls[0] += 1
        return []

    ml._ocr_region = _fd25_count_ocr

    _fd25_warn_calls = [0]
    _fd25_orig_warn = ml.on_warning

    def _fd25_count_warn(msg):
        _fd25_warn_calls[0] += 1

    ml.on_warning = _fd25_count_warn

    ml._groups = [RuleGroup(id="fd_dummy", name="FD測試群組", rule_ids=["rule_fd25"])]
    ml._fail_since.clear()
    ml._active_group_ids = ["fd_dummy"]
    ml._group_queue_idx = 0
    ml._stop_event.clear()

    ml._run_rule(_fd25_rule, _fd25_blank, _fd25_rect, _fd25_ctx)

    assert _fd25_detect_calls[0] == 0
    assert "rule_fd25:0" in ml._fail_since
    assert not _fd25_ctx.triggered

    _fd25_ctx2 = StepContext(img=_fd25_blank, rect=_fd25_rect)
    ml._fail_since["rule_fd25:0"] = time.monotonic() - 10.0

    ml._run_rule(_fd25_rule, _fd25_blank, _fd25_rect, _fd25_ctx2)

    assert "rule_fd25:0" not in ml._fail_since
    assert _fd25_warn_calls[0] > 0
    assert "fd_dummy" not in ml._active_group_ids
    assert ml._stop_event.is_set()
    assert not _fd25_ctx2.triggered

    ml._ocr_region = _fd25_orig_ocr
    ml.on_warning = _fd25_orig_warn
    ml._stop_event.clear()
    ml._active_group_ids = []
    ml._groups = []


# ── on_fail advance ──


def test_on_fail_advance():
    ml = _make_ml()

    _adv_rule_A = Rule(
        id="rule_adv_A",
        name="Advance A",
        enabled=True,
        steps=[
            Step(
                type="detect",
                params={
                    "text": "GHOST",
                    "on_fail": {"action": "advance", "fail_duration_sec": 1.5},
                },
            ),
        ],
    )
    _adv_rule_B = Rule(
        id="rule_adv_B",
        name="Advance B",
        enabled=True,
        steps=[Step(type="wait", params={"ms": 0})],
    )
    ml._rules = [_adv_rule_A, _adv_rule_B]
    ml._rule_map = {r.id: r for r in ml._rules}
    ml._groups = [
        RuleGroup(id="adv_group", name="ADV", rule_ids=["rule_adv_A", "rule_adv_B"], mode="loop")
    ]
    ml._active_group_ids = ["adv_group"]
    ml._group_queue_idx = 0
    ml._rule_in_group_ptr = 0
    ml._fail_since.clear()
    ml._stop_event.clear()
    _adv_img = np.zeros((100, 100, 3), dtype=np.uint8)
    _adv_rect = {"x": 0, "y": 0, "w": 100, "h": 100}

    ml._ocr_region = lambda img, roi: []
    _adv_ctx = StepContext(img=_adv_img, rect=_adv_rect)
    ml._process_rules(_adv_img, _adv_rect)
    assert "rule_adv_A:0" in ml._fail_since
    assert ml._rule_in_group_ptr == 0

    ml._fail_since["rule_adv_A:0"] = time.monotonic() - 10.0
    ml._process_rules(_adv_img, _adv_rect)
    assert "rule_adv_A:0" not in ml._fail_since
    assert ml._rule_in_group_ptr == 1

    assert ml._rule_in_group_ptr == 1

    ml._advance_rule_in_group()
    assert ml._rule_in_group_ptr == 0
    assert "rule_adv_A:0" not in ml._fail_since

    ml._process_rules(_adv_img, _adv_rect)
    assert "rule_adv_A:0" in ml._fail_since
    assert ml._rule_in_group_ptr == 0

    ml._active_group_ids = []


def test_log_sliding_window_rate_limit():
    ml = _make_ml()
    ml._action_log_ts = {}
    ml._logger.setLevel(logging.INFO)  # pytest 環境 root 預設 WARNING，需明確放行 INFO
    seen = []

    class _Probe(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    probe = _Probe()
    ml._logger.addHandler(probe)
    try:
        ml._log("規則 A 點擊 (1,2) 匹配「X」", dedup_key="a:click")
        ml._log("規則 A 點擊 (3,4) 匹配「Y」", dedup_key="a:click")
        assert seen == ["規則 A 點擊 (1,2) 匹配「X」"], "窗內不同內容同 key 應只留首筆"
        ml._action_log_ts["a:click"] = time.monotonic() - 5.0
        ml._log("規則 A 點擊 (5,6) 匹配「Z」", dedup_key="a:click")
        assert seen.count("規則 A 點擊 (5,6) 匹配「Z」") == 1, "超窗後應重新印出"
        ml._log("規則 B 按鍵「1」", dedup_key="b:key:1")
        assert seen.count("規則 B 按鍵「1」") == 1, "不同 key 互不干擾"
        ml._log("群組完成")
        assert seen.count("群組完成") == 1, "無 dedup_key 一律印出"
    finally:
        ml._logger.removeHandler(probe)
