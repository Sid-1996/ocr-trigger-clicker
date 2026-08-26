#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class _UpdaterParser(argparse.ArgumentParser):
    def error(self, message):
        ctypes.windll.user32.MessageBoxW(
            0,
            f"參數錯誤：{message}\n\n請勿直接執行 updater.exe，\n此檔案由 OCR Trigger Clicker 自動更新時呼叫。",
            "更新錯誤",
            0,
        )
        sys.exit(2)


def wait_for_pid_exit(pid: int, timeout_s: float = 30.0) -> None:
    """等 PID 結束。OpenProcess 失敗（無法同步）立即返回；逾時放行不永久滯留。"""
    PROCESS_SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not handle:
        return
    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            rc = kernel32.WaitForSingleObject(handle, 500)
            if rc != WAIT_TIMEOUT:
                return
        print(f"update: wait-pid {pid} 逾時 {timeout_s}s，繼續更新流程")
    finally:
        kernel32.CloseHandle(handle)


def _backup_existing_target(
    target_dir: Path,
    old_backup: Path,
    retries: int = 6,
    delay: float = 0.5,
) -> bool:
    """把現有安裝目錄 rename 成 *_old 備份。

    回傳是否可安全繼續：True = 已備份成功，或目標本來不存在（首次安裝）；
    False = 目標存在卻始終無法 rename —— 呼叫端必須安全中止，
    絕不可刪除目標目錄（沒有備份就複製，複製一失敗即無法回滾）。

    先清掉上次失敗殘留的 *_old 再重試 rename（防毒/索引鎖多為瞬態）；
    `<安裝名>_old` 視為 updater 專屬備份命名空間。
    """
    try:
        if old_backup.exists():
            shutil.rmtree(str(old_backup), ignore_errors=True)
    except OSError:
        pass
    for attempt in range(1, retries + 1):
        if not target_dir.exists():
            return True
        try:
            os.rename(str(target_dir), str(old_backup))
            return True
        except OSError as e:
            print(f"update: 備份舊目錄失敗 attempt {attempt}/{retries}: {e}")
            time.sleep(delay)
    return False


def main():
    parser = _UpdaterParser(description="OCR Trigger Clicker Updater")
    parser.add_argument("--mode", required=True, choices=["update", "relaunch"])

    # 共用參數
    parser.add_argument("--wait-pid", type=int)

    # update 模式：onedir 目錄取代
    parser.add_argument("--new-dir")
    parser.add_argument("--target-dir")

    # relaunch 模式：語言切換重啟
    parser.add_argument("--launch-exe")
    parser.add_argument("--launch-arg", action="append", default=[])
    parser.add_argument("--launch-cwd")

    args = parser.parse_args()

    if args.mode == "relaunch":
        # 除錯用 relaunch log（固定寫入系統 TEMP，無需額外參數）。
        _relaunch_log = Path(tempfile.gettempdir()) / "ocr_relaunch.log"
        try:
            with _relaunch_log.open("a", encoding="utf-8") as f:
                f.write(
                    f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] relaunch wait_pid={args.wait_pid} "
                    f"launch={args.launch_exe} {args.launch_arg}\n"
                )
        except OSError:
            pass
        if args.wait_pid:
            wait_for_pid_exit(args.wait_pid)
        launch_cmd = [args.launch_exe] + args.launch_arg
        subprocess.Popen(
            launch_cmd,
            cwd=args.launch_cwd,
            shell=False,
            close_fds=True,
        )
        try:
            with _relaunch_log.open("a", encoding="utf-8") as f:
                f.write(
                    f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] relaunch done → "
                    f"{launch_cmd} cwd={args.launch_cwd}\n"
                )
        except OSError:
            pass
        sys.exit(0)

    # onedir update 模式：暫存 → 逐檔複製取代 + rollback
    # 防禦：本程序繼承自主程序的 CWD 常是安裝資料夾本身，而 Windows 不允許
    # rename「任何程序的正當 CWD」——不移出去，Phase 1 備份 rename 必敗。
    # 以下全部使用絕對路徑操作，chdir 不影響行為。
    os.chdir(tempfile.gettempdir())
    staging = Path(args.new_dir)
    target_dir = Path(args.target_dir)

    if not staging.exists():
        print(f"update: 暫存目錄不存在 {staging}")
        sys.exit(1)

    if args.wait_pid:
        wait_for_pid_exit(args.wait_pid)

    # Phase 1: 備份（rename，同磁碟瞬間完成）；無法備份＝安全中止，絕不破壞舊安裝
    old_backup = target_dir.parent / (target_dir.name + "_old")
    if not _backup_existing_target(target_dir, old_backup):
        ctypes.windll.user32.MessageBoxW(
            0,
            f"無法備份現有安裝目錄：\n{target_dir}\n\n"
            "可能原因：防毒軟體鎖定、資料夾權限不足、程式仍在執行中。\n"
            "你的舊安裝未被更動。請關閉相關程式後再執行一次更新。",
            "更新已安全中止",
            0,
        )
        sys.exit(3)
    have_backup = old_backup.exists()

    # Phase 2: 逐檔複製（每檔 retry 3 次，整包 retry 3 次）
    def _robust_copy(src, dst):
        for i in range(3):
            try:
                shutil.copy2(src, dst)
                return
            except OSError as e:
                print(f"update: 複製失敗 {src.name} attempt {i + 1}/3: {e}")
                if i == 2:
                    raise
                time.sleep(0.5)

    success = False
    for i in range(3):
        try:
            shutil.copytree(
                str(staging), str(target_dir), copy_function=_robust_copy, dirs_exist_ok=True
            )
            success = True
            break
        except OSError as e:
            print(f"update: 整包複製失敗 attempt {i + 1}/3: {e}")
            if target_dir.exists():
                shutil.rmtree(str(target_dir), ignore_errors=True)
            time.sleep(1)

    if not success:
        print("update: 取代失敗，嘗試還原備份")
        if have_backup:
            if target_dir.exists():
                shutil.rmtree(str(target_dir), ignore_errors=True)
            try:
                os.rename(str(old_backup), str(target_dir))
                print("update: 已還原備份")
            except OSError as e:
                print(f"update: 還原備份失敗: {e}")
        sys.exit(1)

    # Phase 3: 清理備份 + 暫存目錄
    if have_backup and old_backup.exists():
        shutil.rmtree(str(old_backup), ignore_errors=True)
    temp_root = staging.parent
    if temp_root.name.startswith("ocr_update_"):
        shutil.rmtree(str(temp_root), ignore_errors=True)

    # Phase 4: 啟動新版
    exe_path = target_dir / "ocr-trigger-clicker.exe"
    if exe_path.exists():
        subprocess.Popen([str(exe_path)], cwd=str(target_dir), shell=False, close_fds=True)
        print("update: 已啟動新版")
    else:
        print(f"update: 找不到啟動檔 {exe_path}")

    sys.exit(0)


def demo():
    tmp = Path(tempfile.mkdtemp(prefix="ocr_test_"))
    staging = tmp / "staging"
    target = tmp / "target"
    target.mkdir()
    (staging / "_internal").mkdir(parents=True)
    (staging / "ocr-trigger-clicker.exe").write_bytes(b"MZ" + b"\x00" * 100)
    (staging / "updater.exe").write_text("dummy")
    (staging / "_internal" / "test.dll").write_text("dll")
    (target / "old.txt").write_text("old")

    old_backup = target.parent / (target.name + "_old")
    assert _backup_existing_target(target, old_backup), "正常情況應備份成功"
    assert old_backup.is_dir() and (old_backup / "old.txt").is_file(), "rename 備份"
    assert not target.exists()
    shutil.copytree(str(staging), str(target), copy_function=shutil.copy2, dirs_exist_ok=True)
    assert (target / "_internal" / "test.dll").is_file(), "取代後應有 test.dll"
    assert not (target / "old.txt").exists(), "取代後不應有 old.txt"

    # 殘留 *_old 預清：上一次失敗留下的舊備份不該擋住這次備份
    stale_target = tmp / "t2"
    stale_target.mkdir()
    (stale_target / "x.txt").write_text("x")
    stale_old = tmp / "t2_old"
    stale_old.mkdir()
    (stale_old / "junk.txt").write_text("junk")
    assert _backup_existing_target(stale_target, stale_old)
    assert (stale_old / "x.txt").is_file() and not (stale_old / "junk.txt").exists()

    # 硬失敗（rename 恆錯）：目標必須原封不動
    stale_target.mkdir()
    (stale_target / "x.txt").write_text("x")
    orig_rename = os.rename

    def _boom(a, b):
        raise OSError("simulated lock")

    os.rename = _boom
    try:
        ok = _backup_existing_target(stale_target, stale_old, retries=2, delay=0.01)
    finally:
        os.rename = orig_rename
    assert not ok, "rename 恆錯應回 False"
    assert stale_target.is_dir() and (stale_target / "x.txt").is_file(), "硬失敗不得破壞目標"

    # 無效 PID：OpenProcess 失敗立即返回，不掛起
    wait_for_pid_exit(999999999, timeout_s=0.5)

    shutil.rmtree(tmp, ignore_errors=True)
    print("✓ update simulation passed")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()
