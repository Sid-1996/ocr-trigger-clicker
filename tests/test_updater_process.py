"""updater.exe 更新程序輔助函式測試（備份策略／PID 等待逾時）。"""

import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

_um = load_sibling("updater_main", "updater_main.py")


def test_backup_success(tmp_path):
    target = tmp_path / "app"
    target.mkdir()
    (target / "core.dll").write_text("dll")
    old_backup = tmp_path / "app_old"
    assert _um._backup_existing_target(target, old_backup)
    assert (old_backup / "core.dll").is_file(), "rename 備份應保留內容"
    assert not target.exists()


def test_backup_noop_when_target_missing(tmp_path):
    old_backup = tmp_path / "app_old"
    assert _um._backup_existing_target(tmp_path / "app", old_backup)
    assert not old_backup.exists(), "目標不存在時不該產出任何東西"


def test_backup_precleans_stale_old(tmp_path):
    # 上次失敗殘留的 *_old 不該擋住這次 rename
    target = tmp_path / "app"
    target.mkdir()
    (target / "new.txt").write_text("n")
    stale_old = tmp_path / "app_old"
    stale_old.mkdir()
    (stale_old / "junk.txt").write_text("junk")

    assert _um._backup_existing_target(target, stale_old)
    assert (stale_old / "new.txt").is_file()
    assert not (stale_old / "junk.txt").exists(), "殘留備份應被預清取代"


def test_backup_hard_fail_leaves_target_intact(tmp_path, monkeypatch):
    target = tmp_path / "app"
    target.mkdir()
    (target / "keep.txt").write_text("k")
    old_backup = tmp_path / "app_old"

    def _boom(src, dst):
        raise OSError("simulated lock")

    monkeypatch.setattr(os, "rename", _boom)
    assert not _um._backup_existing_target(target, old_backup, retries=3, delay=0)
    assert target.is_dir() and (target / "keep.txt").is_file(), "硬失敗不得破壞目標"
    assert not old_backup.exists(), "硬失敗不得留下半套備份"


def test_wait_pid_invalid_pid_returns_immediately():
    # 不存在的 PID：OpenProcess 失敗 → 立即返回（不掛起、不拋錯）
    _um.wait_for_pid_exit(999999999, timeout_s=0.2)


def test_wait_pid_timeout_bounds_hang():
    # 對「自己」的 PID 等待：handle 可開、但自己不可能在時限內退出 → 必須逾時放行
    import time

    start = time.monotonic()
    _um.wait_for_pid_exit(os.getpid(), timeout_s=0.5)
    elapsed = time.monotonic() - start
    assert elapsed < 5, f"逾時未放行（耗時 {elapsed:.1f}s）"
