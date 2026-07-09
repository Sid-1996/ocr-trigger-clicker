import logging
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen
import os as _os

log = logging.getLogger(__name__)

_GITHUB_OWNER = "Sid-1996"
_GITHUB_REPO = "ocr-trigger-clicker"
_USER_AGENT = "ocr-trigger-clicker-updater/1.0"
RAW_VERSION_URL = (
    f"https://raw.githubusercontent.com/{_GITHUB_OWNER}/{_GITHUB_REPO}"
    "/master/latest_version.txt"
)
ASSET_NAME = "ocr-trigger-clicker.zip"
UPDATER_EXE_NAME = "updater.exe"


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    release_url: str


def _parse_version(v: str) -> tuple[int, ...]:
    v = v.strip().lstrip("v")
    if not v:
        return (0,)
    parts = []
    for x in v.split("."):
        m = re.match(r"(\d+)", x)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def current_exe_path() -> Path:
    return Path(sys.executable).resolve()


def check_for_update(current_version: str) -> UpdateInfo | None:
    with urlopen(RAW_VERSION_URL, timeout=10) as resp:
        latest = _parse_version(resp.read().decode("utf-8"))
    current = _parse_version(current_version)

    if latest <= current:
        return None

    version_str = ".".join(str(x) for x in latest)
    return UpdateInfo(
        version=version_str,
        download_url=(
            f"https://github.com/{_GITHUB_OWNER}/{_GITHUB_REPO}"
            f"/releases/download/v{version_str}/{ASSET_NAME}"
        ),
        release_url=(
            f"https://github.com/{_GITHUB_OWNER}/{_GITHUB_REPO}"
            f"/releases/tag/v{version_str}"
        ),
    )


def download_update(
    info: UpdateInfo,
    progress_cb=None,
    cancel_event=None,
) -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix="ocr_update_"))
    zip_path = tmp_dir / ASSET_NAME
    exe_path = tmp_dir / "ocr-trigger-clicker.exe"

    try:
        req = Request(info.download_url, headers={"User-Agent": _USER_AGENT})
        with urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(zip_path, "wb") as f:
                while True:
                    if cancel_event and cancel_event.is_set():
                        raise RuntimeError("\u4f7f\u7528\u8005\u53d6\u6d88\u4e0b\u8f09")
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)

        with zipfile.ZipFile(zip_path, "r") as zf:
            exe_entries = [n for n in zf.namelist() if n.endswith(".exe")]
            if not exe_entries:
                raise RuntimeError("ZIP \u5167\u7121 .exe \u6a94\u6848")
            target = next(
                (n for n in exe_entries if "/" not in n and "\\" not in n),
                exe_entries[0],
            )
            with zf.open(target) as src, open(exe_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

            updater_entries = [n for n in zf.namelist() if n == UPDATER_EXE_NAME]
            if not updater_entries:
                raise RuntimeError("ZIP \u5185\u7f3a\u5c11 updater.exe")
            updater_dst = tmp_dir / UPDATER_EXE_NAME
            with zf.open(UPDATER_EXE_NAME) as src, open(updater_dst, "wb") as dst:
                shutil.copyfileobj(src, dst)

        with open(exe_path, "rb") as f:
            if f.read(2) != b"MZ":
                raise RuntimeError(
                    "\u4e0b\u8f09\u6a94\u6848\u4e0d\u662f\u6709\u6548\u7684 EXE"
                    "\uff08PE \u6a19\u982d\u932f\u8aa4\uff09"
                )

        return exe_path

    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def apply_update(new_exe_path: Path) -> Path:
    if not is_frozen():
        raise RuntimeError("\u539f\u59cb\u78bc\u6a21\u5f0f\u4e0d\u652f\u63f4\u81ea\u52d5\u66f4\u65b0")

    old_exe = current_exe_path()
    updater_exe = new_exe_path.parent / UPDATER_EXE_NAME
    if not updater_exe.exists():
        raise RuntimeError("\u627e\u4e0d\u5230 updater.exe\uff0c\u7121\u6cd5\u5957\u7528\u66f4\u65b0")

    debug_log_path = Path(_os.environ["LOCALAPPDATA"]) / "ocr-trigger-clicker" / "update_debug.log"
    debug_log_path.parent.mkdir(parents=True, exist_ok=True)

    creationflags_variants = [
        subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_BREAKAWAY_FROM_JOB,
        subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    ]
    launched = False
    for flags in creationflags_variants:
        try:
            subprocess.Popen(
                [str(updater_exe), "--old", str(old_exe), "--new", str(new_exe_path),
                 "--pid", str(_os.getpid()), "--log", str(debug_log_path)],
                cwd=str(old_exe.parent),
                creationflags=flags,
                close_fds=True,
            )
            launched = True
            break
        except OSError:
            continue

    if not launched:
        raise RuntimeError("\u7121\u6cd5\u555f\u52d5 updater.exe")

    return updater_exe


def demo():
    test_cases = [
        ("0.0.4", "0.0.4", False),
        ("0.0.4", "0.0.5", True),
        ("0.0.4", "v0.0.5", True),
        ("0.0.4", "0.0.5.1", True),
        ("0.0.4", "0.0.4.1", True),
        ("0.1.0", "0.0.9", False),
        ("", "", False),
        ("0.0.5-dev", "0.0.4", False),
        ("0.0.5a1", "0.0.5", False),
    ]
    for cur, lat, expect in test_cases:
        result = _parse_version(lat) > _parse_version(cur)
        assert result == expect, f"FAIL: {cur=} {lat=} expect={expect} got={result}"
    print("\u2713 _parse_version: \u5168\u90e8\u901a\u904e")


if __name__ == "__main__":
    demo()
