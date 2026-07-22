import argparse
import ctypes
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


class _UpdaterParser(argparse.ArgumentParser):
    def error(self, message):
        ctypes.windll.user32.MessageBoxW(
            0,
            f"?ÉÊï∏?ØË™§Ôºö{message}\n\nË´ãÂãø?¥Êé•?∑Ë? updater.exeÔº?
            "Ê≠§Ê?Ê°àÁî± OCR Trigger Clicker ?™Â??¥Êñ∞?ÇÂëº?´„Ä?,
            "?¥Êñ∞?ØË™§",
            0,
        )
        sys.exit(2)


def _log(log_path, msg):
    if not log_path:
        return
    try:
        p = Path(log_path)
        if p.exists() and p.stat().st_size > 1_000_000:
            lines = p.read_text(encoding="utf-8").splitlines()[-500:]
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()} [updater] {msg}\n")
    except Exception:
        pass


def _wait_for_pid_exit(pid: int, timeout_sec: int, log_path):
    PROCESS_SYNCHRONIZE = 0x00100000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not handle:
        _log(log_path, f"OpenProcess failed for pid={pid}ÔºàÂèØ?ΩÂ∑≤ÁµêÊ?Ôº?)
        return
    WAIT_TIMEOUT = 0x00000102
    result = kernel32.WaitForSingleObject(handle, timeout_sec * 1000)
    kernel32.CloseHandle(handle)
    _log(log_path, f"WaitForSingleObject result={result}Ôº?=Â∑≤Á??? {WAIT_TIMEOUT}=?æÊ?Ôº?)


def _relaunch(args):
    log_path = args.log
    _wait_for_pid_exit(args.wait_pid, timeout_sec=15, log_path=log_path)
    _log(
        log_path,
        f"relaunch: launching {args.launch_exe} args={args.launch_arg} cwd={args.launch_cwd}",
    )
    try:
        subprocess.Popen(
            [args.launch_exe] + (args.launch_arg or []),
            cwd=args.launch_cwd,
        )
    except Exception as e:
        _log(log_path, f"relaunch failed: {e}")
        sys.exit(1)
    _log(log_path, "relaunch finished")


def main():
    parser = _UpdaterParser()
    parser.add_argument("--mode", default="update", choices=["update", "relaunch"])
    parser.add_argument("--old")
    parser.add_argument("--new")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--wait-pid", type=int)
    parser.add_argument("--launch-exe")
    parser.add_argument("--launch-arg", action="append", default=[])
    parser.add_argument("--launch-cwd")
    parser.add_argument("--log", default=None)
    args = parser.parse_args()

    if args.mode == "relaunch":
        _relaunch(args)
        sys.exit(0)\r\n
    # ?Ä?Ä update mode (default) ?Ä?Ä
    log_path = args.log
    old_path = Path(args.old)
    new_path = Path(args.new)
    tmp_dir = new_path.parent

    _log(log_path, f"updater started, old={old_path}, new={new_path}, waiting pid={args.pid}")
    try:
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

        _log(log_path, "updater finished successfully")
    finally:
        try:
            for _entry in tmp_dir.iterdir():
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
        try:
            tmp_dir.rmdir()
        except Exception:
            pass


if __name__ == "__main__":
    main()