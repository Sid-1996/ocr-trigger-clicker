import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _loader import load_sibling

RC = load_sibling("run_controller", "gui/run_controller.py")


def test_fate_terminal_actions():
    f = RC._dry_fail_fate
    assert f("stop") == "terminal"
    assert f({"action": "stop"}) == "terminal"
    assert f({"action": "advance"}) == "terminal"
    assert f({"action": "notify"}) == "terminal"
    assert f({"action": "jump", "rule_id": "x"}) == "terminal"
    assert f(None) == "terminal"
    assert f(42) == "terminal"


def test_fate_continue_and_jump():
    f = RC._dry_fail_fate
    assert f("key") == "continue"
    assert f({"action": "key", "key": "Escape"}) == "continue"
    assert f({"action": "skip", "skip_to": 3}) == ("jump", 3)
    # skip_to 缺席 → ("jump", 0)，是否 terminal 由 _dead_after 依 fail_idx 判定
    assert f({"action": "skip"}) == ("jump", 0)
    # 髒 skip_to 不崩
    assert f({"action": "skip", "skip_to": "bad"}) == "terminal"


def test_fate_fail_duration_always_terminal():
    f = RC._dry_fail_fate
    # 單幀快照必定落在容忍期內：連 key 也視為 terminal（保守）
    assert f({"action": "key", "key": "X", "fail_duration_sec": 1.0}) == "terminal"
    assert f({"action": "advance", "fail_duration_sec": 1.0}) == "terminal"
    assert f({"action": "advance", "fail_duration_sec": 0}) == "terminal"
    # 髒 duration 不崩，退回按 action 判定
    assert f({"action": "key", "key": "X", "fail_duration_sec": "bad"}) == "continue"


def test_dead_after_terminal_and_continue():
    d = RC._dead_after
    assert d(0, "terminal", 5) == {1, 2, 3, 4}
    assert d(2, "terminal", 5) == {3, 4}
    assert d(4, "terminal", 5) == set()
    assert d(0, "continue", 5) == set()


def test_dead_after_skip_interval():
    d = RC._dead_after
    # fail 在 0，跳到 3：只死 1、2，3 之後照跑
    assert d(0, ("jump", 3), 5) == {1, 2}
    # 倒跳／等於自己 → 無效，等同 terminal
    assert d(2, ("jump", 1), 5) == {3, 4}
    assert d(1, ("jump", 1), 5) == {2, 3, 4}
    # skip_to 缺席（0）且 fail 在 0 → terminal
    assert d(0, ("jump", 0), 4) == {1, 2, 3}
    # skip_to 超出範圍 → 死到尾
    assert d(0, ("jump", 9), 5) == {1, 2, 3, 4}


def test_log_html_escapes_and_strikes():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])  # noqa: F841 - keep ref
    m = load_sibling("gui_main", "gui/06_gui_main.py")
    out = m._test_log_html("[1] a<b>c\n[2] d&e", [1])
    assert "<b>" not in out and "&lt;b&gt;" in out
    assert "&amp;" in out
    assert out.count("line-through") == 1
    plain = m._test_log_html("[1] ok", [])
    assert "line-through" not in plain
    # 越界 dead 行號不崩
    assert "line-through" not in m._test_log_html("[1] ok", [9])
