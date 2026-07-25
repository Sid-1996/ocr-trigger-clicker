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


def wait_for_pid_exit(pid: int) -> None:
    PROCESS_SYNCHRONIZE = 0x00100000
    INFINITE = 0xFFFFFFFF
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not handle:
        return
    kernel32.WaitForSingleObject(handle, INFINITE)
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
            wait_for_pid_exit(args.wait_pid)
        launch_cmd = [args.launch_exe] + args.launch_arg
        subprocess.Popen(
            launch_cmd,
            cwd=args.launch_cwd,
            shell=False,
            close_fds=True,
        )
        sys.exit(0)

    # onedir update 模式：暫存 → 逐檔複製取代 + rollback
    staging = Path(args.new_dir)
    target_dir = Path(args.target_dir)

    if not staging.exists():
        print(f"update: 暫存目錄不存在 {staging}")
        sys.exit(1)

    if args.wait_pid:
        wait_for_pid_exit(args.wait_pid)

    # Phase 1: 備份（rename，同磁碟瞬間完成）
    old_backup = target_dir.parent / (target_dir.name + "_old")
    have_backup = False
    if target_dir.exists():
        try:
            os.rename(str(target_dir), str(old_backup))
            have_backup = True
        except OSError:
            print("update: 無法備份舊目錄，直接刪除取代")
            shutil.rmtree(str(target_dir), ignore_errors=True)

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


if __name__ == "__main__":
    main()
