"""Background (frida) drag 的行為護欄。

涵蓋 F-13：drag() 在持有 _lock 時呼叫同樣會取鎖的 click()，造成同執行緒重入
非重入 Lock 而永久死鎖；以及拖曳語意必須是 down → move → up（不得提前放開）。

全部使用 Fake backend：不呼叫真實 Win32 API，也不建立真實 Frida session。
"""

import logging
import threading
import time

import pytest

from _loader import load_sibling

_BG = load_sibling("bg_input", "core/16_bg_input.py")
_FRIDA = load_sibling("frida_bg", "core/18_frida_bg.py")


class FakeUser32:
    """只記錄訊息的假 user32。

    fail 用來模擬 PostMessageW 回傳 0（真實 Win32 失敗模式），
    raise_on 用來模擬 API 本身拋例外。
    """

    def __init__(self):
        self.sent = []
        self.fail = set()
        self.raise_on = set()

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        if msg in self.raise_on:
            raise RuntimeError(f"PostMessageW 失敗: msg=0x{msg:04X}")
        self.sent.append(msg)
        return 0 if msg in self.fail else 1


class FakeFrida:
    """假 frida 模組：只記錄游標同步與按鍵事件，不建立真實 session。"""

    def __init__(self):
        self.syncs = []
        self.keys = []
        self.attached = 0
        self.sync_fail_at = None  # 第 N 次 sync_cursor 失敗（1-based）
        self.sync_delay = 0.0

    def ensure_attached(self, hwnd):
        self.attached += 1
        return True

    def sync_cursor(self, hwnd, x, y):
        if self.sync_delay:
            time.sleep(self.sync_delay)
        self.syncs.append((x, y))
        if self.sync_fail_at is not None and len(self.syncs) == self.sync_fail_at:
            return False
        return True

    def click(self, hwnd, x, y, button="left", hold_ms=0, cancel=None):
        return _BG._click_postmessage(hwnd, x, y, button, hold_ms, cancel)

    def key(self, hwnd, vk, down):
        self.keys.append((vk, down))
        return True


@pytest.fixture
def bg_frida(monkeypatch):
    """切到 frida 模式並安裝假 backend；測試結束後自動還原。"""
    prev_method = _BG.get_method()
    fake_user32 = FakeUser32()
    fake_frida = FakeFrida()
    monkeypatch.setattr(_BG, "user32", fake_user32)
    monkeypatch.setattr(_BG, "_frida", lambda: fake_frida)
    _BG.set_method("frida")
    try:
        yield fake_user32, fake_frida
    finally:
        _BG.set_method(prev_method)


def test_bg_frida_drag_completes_without_deadlock(bg_frida):
    """F-13 核心：drag 必須在合理時間內結束，不得因重入 _lock 永久卡住。"""
    result = {}

    def worker():
        result["ret"] = _BG.drag(1, 10, 20, 30, 40, "left")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=2.0)
    assert not t.is_alive(), "drag 未在 2 秒內結束：疑似 _lock 自我死鎖"
    assert result.get("ret") is True


def test_bg_frida_drag_sends_down_move_up_in_order(bg_frida):
    """拖曳必須是 ACTIVATE → DOWN → MOVE → UP，且不得提前放開按鈕。"""
    fake_user32, _fake_frida = bg_frida
    assert _BG.drag(1, 10, 20, 30, 40, "left") is True
    assert fake_user32.sent == [
        _BG.WM_ACTIVATE,
        _BG.WM_LBUTTONDOWN,
        _BG.WM_MOUSEMOVE,
        _BG.WM_LBUTTONUP,
    ]


def test_bg_frida_drag_releases_when_move_fails(bg_frida):
    """MOVE 失敗仍必須送出 UP，且回傳值誠實反映失敗。"""
    fake_user32, _fake_frida = bg_frida
    fake_user32.fail = {_BG.WM_MOUSEMOVE}
    assert _BG.drag(1, 10, 20, 30, 40, "left") is False
    assert _BG.WM_MOUSEMOVE in fake_user32.sent
    assert _BG.WM_LBUTTONUP in fake_user32.sent


def test_bg_frida_drag_returns_false_and_warns_when_up_fails(bg_frida, caplog):
    """UP 失敗必須回 False 並留下 WARNING 紀錄。"""
    fake_user32, _fake_frida = bg_frida
    fake_user32.fail = {_BG.WM_LBUTTONUP}
    with caplog.at_level(logging.WARNING):
        assert _BG.drag(1, 10, 20, 30, 40, "left") is False
    warns = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "放開訊息失敗" in r.getMessage()
    ]
    assert warns, "UP 失敗必須留下 warning"


def test_bg_frida_drag_does_not_send_up_when_down_fails(bg_frida):
    """DOWN 沒提交成功時不得送出 MOVE 或 UP。"""
    fake_user32, _fake_frida = bg_frida
    fake_user32.fail = {_BG.WM_LBUTTONDOWN}
    assert _BG.drag(1, 10, 20, 30, 40, "left") is False
    assert _BG.WM_MOUSEMOVE not in fake_user32.sent
    assert _BG.WM_LBUTTONUP not in fake_user32.sent


def test_bg_frida_drag_holds_lock_for_entire_operation(bg_frida):
    """鎖保護範圍不得縮小：drag 期間其他輸入必須被阻擋到 drag 結束。"""
    _fake_user32, fake_frida = bg_frida
    fake_frida.sync_delay = 0.2
    done = {}

    def run_drag():
        _BG.drag(1, 10, 20, 30, 40, "left")

    def run_click():
        t0 = time.monotonic()
        _BG.click(1, 5, 5, "left")
        done["elapsed"] = time.monotonic() - t0

    td = threading.Thread(target=run_drag, daemon=True)
    tc = threading.Thread(target=run_click, daemon=True)
    td.start()
    time.sleep(0.02)
    tc.start()
    td.join(5)
    tc.join(5)
    assert not tc.is_alive()
    assert done.get("elapsed", 0) >= 0.15, "drag 期間其他輸入必須被 _lock 阻擋"


def test_bg_frida_drag_releases_when_move_raises(bg_frida):
    """DOWN 成功後，MOVE 拋例外仍必須送出 UP，避免遊戲內卡住按鈕。"""
    fake_user32, _fake_frida = bg_frida
    fake_user32.raise_on = {_BG.WM_MOUSEMOVE}
    with pytest.raises(RuntimeError):
        _BG.drag(1, 10, 20, 30, 40, "left")
    assert _BG.WM_LBUTTONUP in fake_user32.sent


def test_bg_frida_drag_up_failure_does_not_mask_move_exception(bg_frida, caplog):
    """UP 失敗不得覆蓋原本的 MOVE 例外，且 UP 失敗本身要留下 warning。"""
    fake_user32, _fake_frida = bg_frida
    fake_user32.raise_on = {_BG.WM_MOUSEMOVE, _BG.WM_LBUTTONUP}
    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError, match="msg=0x0200"):
            _BG.drag(1, 10, 20, 30, 40, "left")
    warns = [r for r in caplog.records if "放開訊息失敗" in r.getMessage()]
    assert warns, "UP 失敗必須留下 warning"


def test_bg_frida_drag_syncs_cursor_start_then_end(bg_frida):
    """假造游標必須先同步起點（DOWN 前），再同步終點（MOVE 前）。"""
    _fake_user32, fake_frida = bg_frida
    assert _BG.drag(1, 10, 20, 30, 40, "left") is True
    assert fake_frida.syncs == [(10, 20), (30, 40)]


def test_bg_frida_drag_sync_failure_aborts_move_but_still_releases(bg_frida):
    """終點游標同步失敗 → 跳過 MOVE，但仍必須送出 UP 並回 False。"""
    fake_user32, fake_frida = bg_frida
    fake_frida.sync_fail_at = 2
    assert _BG.drag(1, 10, 20, 30, 40, "left") is False
    assert _BG.WM_MOUSEMOVE not in fake_user32.sent
    assert _BG.WM_LBUTTONUP in fake_user32.sent


def test_bg_frida_drag_does_not_create_real_frida_session(bg_frida, monkeypatch):
    """整條路徑不得碰真實 frida 模組（tripwire）。"""

    def boom(*_args, **_kwargs):
        raise AssertionError("不應呼叫真實 frida 模組")

    monkeypatch.setattr(_FRIDA, "ensure_attached", boom)
    monkeypatch.setattr(_FRIDA, "_sync_update", boom)
    assert _BG.drag(1, 10, 20, 30, 40, "left") is True


def test_bg_other_background_inputs_unaffected(bg_frida):
    """本次改動不得影響既有的其他背景輸入路徑。"""
    _fake_user32, fake_frida = bg_frida
    assert _BG.click(1, 10, 20, "left") is True
    assert _BG.send_key(1, "a") is True
    assert _BG.scroll(1, 10, 20, 1) is True
    assert _BG.send_hold_key(1, "a", 30) is True
    assert fake_frida.keys, "send_key / send_hold_key 仍應走 frida 按鍵通道"
