#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
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


def wait_for_pid_exit(pid: int, timeout_sec: int = 15) -> None:
    PROCESS_SYNCHRONIZE = 0x00100000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not handle:
        return
    kernel32.WaitForSingleObject(handle, timeout_sec * 1000)
    kernel32.CloseHandle(handle)


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
        if args.wait_pid:
            wait_for_pid_exit(args.wait_pid, timeout_sec=15)
        launch_cmd = [args.launch_exe] + args.launch_arg
        subprocess.Popen(
            launch_cmd,
            cwd=args.launch_cwd,
            shell=False,
            close_fds=True,
        )
        sys.exit(0)

    # onedir update 模式：目錄取代 + rollback
    new_dir = Path(args.new_dir)
    target_dir = Path(args.target_dir)

    if not new_dir.exists():
        print(f"update: 新目錄不存在 {new_dir}")
        sys.exit(1)
    if not target_dir.exists():
        print(f"update: 目標目錄不存在 {target_dir}")

    if args.wait_pid:
        wait_for_pid_exit(args.wait_pid, timeout_sec=15)

    # Phase 1: 備份舊目錄（rename，同磁碟瞬間完成）
    old_backup = target_dir.parent / (target_dir.name + "_old")
    have_backup = False
    if target_dir.exists():
        try:
            os.rename(str(target_dir), str(old_backup))
            have_backup = True
        except OSError:
            print("update: 無法備份舊目錄，直接刪除取代")
            shutil.rmtree(str(target_dir), ignore_errors=True)

    # Phase 2: 取代（rename new → target，同磁碟瞬間完成）
    success = False
    for i in range(5):
        try:
            os.rename(str(new_dir), str(target_dir))
            success = True
            break
        except OSError as e:
            print(f"update: 取代失敗 attempt {i + 1}/5: {e}")
            time.sleep(1)

    if not success:
        print("update: 取代失敗，嘗試還原備份")
        if have_backup:
            try:
                os.rename(str(old_backup), str(target_dir))
                print("update: 已還原備份")
            except OSError as e:
                print(f"update: 還原備份失敗: {e}")
        sys.exit(1)

    # Phase 3: 清理備份
    if have_backup and old_backup.exists():
        shutil.rmtree(str(old_backup), ignore_errors=True)

    # Phase 4: 啟動新版
    exe_path = target_dir / "ocr-trigger-clicker.exe"
    if exe_path.exists():
        subprocess.Popen([str(exe_path)], cwd=str(target_dir), shell=False, close_fds=True)
        print("update: 已啟動新版")
    else:
        print(f"update: 找不到啟動檔 {exe_path}")

    sys.exit(0)


if __name__ == "__main__":
    main()
