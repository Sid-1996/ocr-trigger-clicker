"""混合模式焦點管理 — 後台偵測、前景操作、狀態還原。

hybrid 模式：截圖辨識走後台 PrintWindow（零干擾），需要動作（點擊/按鍵）時
短暫激活遊戲視窗做物理輸入，完成後復原先前的前景視窗與滑鼠位置。

用法：
    with focus_guard(title):
        ... 激活＋物理輸入 ...
"""

import contextlib
import ctypes
import ctypes.wintypes
import threading
import time

_act_lock = threading.Lock()  # 序列化動作區間（主循環與診斷面板可能並發搶焦點）

_user32 = ctypes.windll.user32

_ACTIVATE_SETTLE_SEC = 0.25  # ponytail: 固定值；激活後等遊戲收輸入，有需求再調
_RESTORE_DELAY_SEC = 0.1  # 動作完成後留給遊戲消化，再還原使用者狀態


def save_state() -> tuple[int, int, int] | None:
    """記錄目前前景視窗 hwnd 與游標位置 (hwnd, x, y)。失敗回 None。"""
    try:
        hwnd = _user32.GetForegroundWindow()
        pt = ctypes.wintypes.POINT()
        if not _user32.GetCursorPos(ctypes.byref(pt)):
            return None
        return (hwnd, pt.x, pt.y)
    except Exception:
        return None


def restore_state(state: tuple[int, int, int] | None) -> None:
    """還原滑鼠位置與前景視窗。各步獨立容錯，任何一步失敗不影響其他。"""
    if not state:
        return
    hwnd, x, y = state
    try:
        _user32.SetCursorPos(int(x), int(y))
    except Exception:
        pass
    try:
        if not hwnd or not _user32.IsWindow(hwnd) or _user32.IsIconic(hwnd):
            return  # 視窗已關閉／最小化：只還原滑鼠，不強行搶回焦點
        _set_foreground(hwnd)
    except Exception:
        pass


def _set_foreground(hwnd: int) -> None:
    """穩健版 SetForegroundWindow：Windows 會擋背景行程搶焦點，
    以 AttachThreadInput 借用前景執行緒的輸入權限繞過。"""
    fg = _user32.GetForegroundWindow()
    if fg == hwnd:
        return
    cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
    fg_tid = _user32.GetWindowThreadProcessId(fg, None)
    target_tid = _user32.GetWindowThreadProcessId(hwnd, None)
    attached = []
    try:
        if fg_tid and fg_tid != cur_tid:
            if _user32.AttachThreadInput(cur_tid, fg_tid, True):
                attached.append(fg_tid)
        if target_tid and target_tid != cur_tid and target_tid not in attached:
            if _user32.AttachThreadInput(cur_tid, target_tid, True):
                attached.append(target_tid)
        _user32.SetForegroundWindow(hwnd)
    finally:
        for tid in attached:
            _user32.AttachThreadInput(cur_tid, tid, False)


@contextlib.contextmanager
def focus_guard(title: str, activate_fn):
    """混合模式動作區間：進入時存檔並激活遊戲，離開時還原使用者狀態。

    activate_fn(title) -> bool：實際激活函式（由呼叫端注入 _screenshot.activate_window，
    避免 core 模組循環載入）。非致命失敗僅記 log——激活失敗時物理點擊仍會嘗試。
    """
    with _act_lock:
        state = save_state()
        ok = False
        try:
            ok = bool(activate_fn(title))
        except Exception:
            pass
        if not ok:
            _log_activate_fail(title)
        time.sleep(_ACTIVATE_SETTLE_SEC)
        try:
            yield ok
        finally:
            time.sleep(_RESTORE_DELAY_SEC)
            restore_state(state)


def _log_activate_fail(title: str) -> None:
    import logging

    logging.getLogger(__name__).warning("hybrid: 激活視窗失敗：%s", title)


if __name__ == "__main__":
    print("=== Hybrid Input Self-Check ===\n")

    # 游標位置往返一致
    pt = ctypes.wintypes.POINT()
    assert _user32.GetCursorPos(ctypes.byref(pt))
    orig = (pt.x, pt.y)
    state = save_state()
    assert state is not None and len(state) == 3
    _user32.SetCursorPos(orig[0] + 50, orig[1] + 50)
    restore_state(state)
    assert _user32.GetCursorPos(ctypes.byref(pt)) and (pt.x, pt.y) == orig
    print("  [OK] save/restore 游標位置往返一致")

    # 防禦性輸入：bogus hwnd / None 不炸
    restore_state((0xDEADBEEF, orig[0], orig[1]))
    restore_state(None)
    print("  [OK] bogus hwnd / None 容錯")

    # focus_guard 進出：activate_fn 用假函式，確認 yield 值與狀態還原
    activated = []

    def fake_activate(t):
        activated.append(t)
        return True

    with focus_guard("dummy", fake_activate) as ok_flag:
        assert ok_flag is True
        _user32.SetCursorPos(orig[0] + 30, orig[1] + 30)
    assert activated == ["dummy"]
    assert _user32.GetCursorPos(ctypes.byref(pt)) and (pt.x, pt.y) == orig
    print("  [OK] focus_guard 進出還原")

    # activate_fn 失敗不炸、仍正常離開
    with focus_guard("dummy", lambda t: False) as ok_flag:
        assert ok_flag is False
    print("  [OK] 激活失敗容錯")

    print("\n=== Self-Check 完成 ===")
