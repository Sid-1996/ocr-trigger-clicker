import argparse
import ctypes
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def _log(log_path, msg):
    if not log_path:
        return
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()} [updater] {msg}\n")
    except Exception:
        pass


def _wait_for_pid_exit(pid: int, timeout_sec: int, log_path):
    PROCESS_SYNCHRONIZE = 0x00100000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not handle:
        _log(log_path, f"OpenProcess failed for pid={pid}（可能已結束）")
        return
    WAIT_TIMEOUT = 0x00000102
    result = kernel32.WaitForSingleObject(handle, timeout_sec * 1000)
    kernel32.CloseHandle(handle)
    _log(log_path, f"WaitForSingleObject result={result}（0=已結束, {WAIT_TIMEOUT}=逾時）")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", required=True)
    parser.add_argument("--new", required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--log", default=None)
    args = parser.parse_args()

    log_path = args.log
    old_path = Path(args.old)
    new_path = Path(args.new)

    _log(log_path, f"updater started, old={old_path}, new={new_path}, waiting pid={args.pid}")
    _wait_for_pid_exit(args.pid, timeout_sec=30, log_path=log_path)

    success = False
    last_err = None
    for i in range(10):
        try:
            shutil.copyfile(str(new_path), str(old_path))
            success = True
            break
        except (PermissionError, OSError) as e:
            last_err = e
            _log(log_path, f"copy attempt {i + 1}/10 failed: {e}")
            time.sleep(1)

    if not success:
        _log(log_path, f"copy failed after all retries: {last_err}")
        sys.exit(1)

    _log(log_path, "copy success, relaunching old exe")
    try:
        subprocess.Popen([str(old_path)], cwd=str(old_path.parent))
    except Exception as e:
        _log(log_path, f"relaunch failed: {e}")

    try:
        for _entry in Path(new_path).parent.iterdir():
            if _entry.name == Path(sys.executable).name:
                continue
            try:
                if _entry.is_file():
                    _entry.unlink()
                elif _entry.is_dir():
                    shutil.rmtree(str(_entry), ignore_errors=True)
            except Exception:
                pass
    except Exception as e:
        _log(log_path, f"cleanup failed: {e}")

    _log(log_path, "updater finished successfully")


if __name__ == "__main__":
    main()
