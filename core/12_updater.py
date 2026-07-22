import logging
import os as _os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

_GITHUB_OWNER = "Sid-1996"
_GITHUB_REPO = "ocr-trigger-clicker"
_USER_AGENT = "ocr-trigger-clicker-updater/1.0"
RAW_VERSION_URL = (
    f"https://raw.githubusercontent.com/{_GITHUB_OWNER}/{_GITHUB_REPO}/master/latest_version.txt"
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
            f"https://github.com/{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/tag/v{version_str}"
        ),
    )


def _clean_stale_temp_dirs():
    for d in Path(tempfile.gettempdir()).glob("ocr_update_*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)


def download_update(
    info: UpdateInfo,
    progress_cb=None,
    cancel_event=None,
) -> Path:
    _clean_stale_temp_dirs()
    tmp_dir = Path(tempfile.mkdtemp(prefix="ocr_update_"))
    zip_path = tmp_dir / ASSET_NAME

    try:
        log.info("開始下載更新 v%s", info.version)
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

        # Detect release type from ZIP structure
        with zipfile.ZipFile(zip_path, "r") as zf:
            has_internal = any(n.startswith("_internal/") for n in zf.namelist())

        if has_internal:
            # onedir: extract all to a sibling directory
            exe_dir = current_exe_path().parent
            new_dir = exe_dir / "ocr-trigger-clicker_new"
            if new_dir.exists():
                shutil.rmtree(new_dir, ignore_errors=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(new_dir)
            new_updater = new_dir / UPDATER_EXE_NAME
            if not new_updater.exists():
                raise RuntimeError("\u89e3\u58d3\u7e2e\u5f8c\u627e\u4e0d\u5230 updater.exe")
            main_exe = new_dir / "ocr-trigger-clicker.exe"
            if not (main_exe.exists() and main_exe.read_bytes()[:2] == b"MZ"):
                raise RuntimeError(
                    "\u4e0b\u8f09\u6a94\u6848\u4e0d\u662f\u6709\u6548\u7684 EXE"
                    "\uff08PE \u6a19\u982d\u932f\u8aa4\uff09"
                )
            log.info("onedir \u66f4\u65b0\u89e3\u58d3\u5b8c\u6210: %s", new_dir)
            return new_dir

        # onefile: extract exes (backward compatibility)
        exe_path = tmp_dir / "ocr-trigger-clicker.exe"
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
        log.exception("下載更新失敗")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        try:
            _nd = current_exe_path().parent / "ocr-trigger-clicker_new"
            if _nd.exists():
                shutil.rmtree(_nd, ignore_errors=True)
        except Exception:
            pass
        raise


def apply_update(new_path: Path) -> None:
    if not is_frozen():
        log.error("原始碼模式不支援自動更新")
        raise RuntimeError(
            "\u539f\u59cb\u78bc\u6a21\u5f0f\u4e0d\u652f\u63f4\u81ea\u52d5\u66f4\u65b0"
        )

    if new_path.is_dir() and (new_path / "_internal").exists():
        # onedir 更新：啟動新目錄中的 updater.exe 做目錄取代
        new_updater = new_path / UPDATER_EXE_NAME
        if not new_updater.exists():
            log.error("新版本缺少 updater.exe: %s", new_updater)
            raise RuntimeError("\u65b0\u7248\u672c\u7f3a\u5c11 updater.exe")

        target_dir = current_exe_path().parent
        log.info("onedir \u66f4\u65b0: new_dir=%s target_dir=%s", new_path, target_dir)

        creationflags_variants = [
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_BREAKAWAY_FROM_JOB,
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        ]
        for flags in creationflags_variants:
            try:
                subprocess.Popen(
                    [
                        str(new_updater),
                        "--mode=update",
                        f"--wait-pid={_os.getpid()}",
                        f"--new-dir={new_path}",
                        f"--target-dir={target_dir}",
                    ],
                    creationflags=flags,
                    close_fds=True,
                )
                log.info("updater.exe \u555f\u52d5\u6210\u529f")
                return
            except OSError:
                continue
        log.error("\u7121\u6cd5\u555f\u52d5 updater.exe")
        raise RuntimeError("\u7121\u6cd5\u555f\u52d5 updater.exe")

    # 非 onedir 結構（無 _internal/）→ 不支援自動更新
    log.error("不支援的更新結構（非 onedir）: %s", new_path)
    raise RuntimeError(
        "\u4e0d\u652f\u63f4\u7684\u66f4\u65b0\u7d50\u69cb\uff0c\u8acb\u624b\u52d5\u4e0b\u8f09\u6700\u65b0\u7248\u672c"
    )


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
