import json
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
from urllib.error import HTTPError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

_GITHUB_OWNER = "Sid-1996"
_GITHUB_REPO = "ocr-trigger-clicker"
_USER_AGENT = "ocr-trigger-clicker-updater/1.0"
RAW_VERSION_URL = (
    f"https://raw.githubusercontent.com/{_GITHUB_OWNER}/{_GITHUB_REPO}/master/latest_version.txt"
)
ASSET_NAME = "ocr-trigger-clicker.zip"
DELTA_ASSET_NAME = "ocr-trigger-clicker-delta.zip"
MANIFEST_FILENAME = "manifest.json"
DELTA_PAYLOAD_DIR = "files"
UPDATER_EXE_NAME = "updater.exe"
_API_RELEASES = f"https://api.github.com/repos/{_GITHUB_OWNER}/{_GITHUB_REPO}/releases"
RAW_DELTA_URL = (
    f"https://raw.githubusercontent.com/{_GITHUB_OWNER}/{_GITHUB_REPO}/master/delta_info.json"
)


class DeltaUpdateError(RuntimeError):
    """delta 不適用於本機安裝（版本基準不符／payload 驗證失敗）。

    只代表「差異更新行不通」，呼叫端應改用完整更新。
    """


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    release_url: str
    delta_url: str | None = None
    delta_base_version: str | None = None
    delta_bytes: int = 0


def _parse_version(v: str) -> tuple[int, ...]:
    v = v.strip().lstrip("v")
    if not v:
        return (0,)
    parts = []
    for x in v.split("."):
        m = re.match(r"(\d+)", x)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts)


def fetch_release_notes(version: str) -> str | None:
    url = f"{_API_RELEASES}/tags/v{version}"
    req = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("body")
    except Exception:
        log.warning("fetch_release_notes failed for v%s", version)
        return None


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def current_exe_path() -> Path:
    return Path(sys.executable).resolve()


def _asset_reachable(url: str) -> bool:
    """探測 release 資產是否已公開可下載。

    發行流程先推 latest_version.txt、Release 仍為 Draft——此時資產 URL 回
    404/403，應視為「尚未發布」而非錯誤。用 GET + Range 只取狀態不拉 body
    （GitHub 轉址到 S3 presigned URL 綁定 verb，HEAD 不保險）。
    僅「確定 404/403」回 False；其餘網路異常 fail-open（True），讓下載
    階段呈現真實錯誤，避免弱網使用者永遠收不到更新。
    """
    req = Request(url, headers={"User-Agent": _USER_AGENT, "Range": "bytes=0-0"})
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status < 300
    except HTTPError as e:
        if e.code in (403, 404):
            return False
        return True
    except Exception:
        return True


def check_for_update(current_version: str) -> UpdateInfo | None:
    with urlopen(RAW_VERSION_URL, timeout=10) as resp:
        latest = _parse_version(resp.read().decode("utf-8"))
    current = _parse_version(current_version)

    if latest <= current:
        return None

    version_str = ".".join(str(x) for x in latest)
    info = UpdateInfo(
        version=version_str,
        download_url=(
            f"https://github.com/{_GITHUB_OWNER}/{_GITHUB_REPO}"
            f"/releases/download/v{version_str}/{ASSET_NAME}"
        ),
        release_url=(
            f"https://github.com/{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/tag/v{version_str}"
        ),
    )

    # delta 資訊非必要：取得失敗一律退回整包更新，不能擋掉更新檢查。
    try:
        req = Request(RAW_DELTA_URL, headers={"User-Agent": _USER_AGENT})
        with urlopen(req, timeout=10) as resp:
            delta_info = json.loads(resp.read().decode("utf-8"))
        if (
            delta_info.get("version") == version_str
            and delta_info.get("base_version") == current_version
            and delta_info.get("asset")
        ):
            info.delta_url = (
                f"https://github.com/{_GITHUB_OWNER}/{_GITHUB_REPO}"
                f"/releases/download/v{version_str}/{delta_info['asset']}"
            )
            info.delta_base_version = delta_info["base_version"]
            info.delta_bytes = int(delta_info.get("delta_bytes") or 0)
            log.info("v%s 提供差異更新（base=%s）", version_str, info.delta_base_version)
    except Exception:
        log.info("delta_info 取得失敗，v%s 改用完整更新", version_str)

    # 發行端先推版本檔、Release 可能還在 Draft：資產未公開前不出現假更新提示。
    if not _asset_reachable(info.download_url):
        log.info("v%s 資產尚未發布（404），本次不提示更新", version_str)
        return None
    if info.delta_url and not _asset_reachable(info.delta_url):
        log.info("v%s 差異更新資產缺席，改用整包", version_str)
        info.delta_url = None
        info.delta_base_version = None
        info.delta_bytes = 0

    return info


def clean_stale_temp_dirs():
    for d in Path(tempfile.gettempdir()).glob("ocr_update_*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)


def _download_to(url: str, dest: Path, progress_cb=None, cancel_event=None) -> None:
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
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


def download_update(
    info: UpdateInfo,
    progress_cb=None,
    cancel_event=None,
) -> Path:
    clean_stale_temp_dirs()
    tmp_dir = Path(tempfile.mkdtemp(prefix="ocr_update_"))
    zip_path = tmp_dir / ASSET_NAME

    try:
        log.info("開始下載更新 v%s", info.version)
        _download_to(info.download_url, zip_path, progress_cb, cancel_event)

        # Detect release type from ZIP structure
        with zipfile.ZipFile(zip_path, "r") as zf:
            has_internal = any(n.startswith("_internal/") for n in zf.namelist())

        if has_internal:
            staging = tmp_dir / "staging"
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(staging)
            new_updater = staging / UPDATER_EXE_NAME
            if not new_updater.exists():
                raise RuntimeError("\u89e3\u58d3\u7e2e\u5f8c\u627e\u4e0d\u5230 updater.exe")
            main_exe = staging / "ocr-trigger-clicker.exe"
            if not (main_exe.exists() and main_exe.read_bytes()[:2] == b"MZ"):
                raise RuntimeError(
                    "\u4e0b\u8f09\u6a94\u6848\u4e0d\u662f\u6709\u6548\u7684 EXE"
                    "\uff08PE \u6a19\u982d\u932f\u8aa4\uff09"
                )
            log.info("onedir \u66f4\u65b0\u89e3\u58d3\u5b8c\u6210: %s", staging)
            return staging

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
        pass  # tmp_dir cleaned above, no stale _new to clean
        raise


# ── 差異更新（delta）─────────────────────────────────────────────
# 每個版本除整包 ZIP 外，另產「只含變更檔案」的 delta.zip。用戶端先抓
# delta_info.json 判定 base_version 是否等於本機版本；相符才走 delta，
# 任何驗證失敗自動退回整包。updater.exe 的備份／rollback 機制完全不變。


def sha256_of_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root: Path, version: str, base_version: str | None = None) -> dict:
    """掃描安裝樹，產出 {version, base_version, files:{rel:{size,sha256}}}。"""
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            st = p.stat()
            files[rel] = {"size": st.st_size, "sha256": sha256_of_file(p)}
    return {"version": version, "base_version": base_version, "files": files}


def diff_manifests(prev: dict, new: dict) -> tuple[list[str], list[str], list[str]]:
    """比對兩份 manifest，回傳 (changed, added, removed) 的 rel 路徑清單。"""
    prev_files = prev.get("files", {})
    new_files = new.get("files", {})
    changed = [r for r in prev_files if r in new_files and new_files[r] != prev_files[r]]
    added = [r for r in new_files if r not in prev_files]
    removed = [r for r in prev_files if r not in new_files]
    return changed, added, removed


def _safe_extract(zip_path: Path, dest: Path) -> None:
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if not (dest / name).resolve().is_relative_to(dest):
                raise DeltaUpdateError("delta 壓縮檔包含非法路徑")
        zf.extractall(dest)


def apply_delta_to_staging(
    install_dir: Path, staging: Path, delta_root: Path, manifest: dict
) -> None:
    """複製目前安裝樹到 staging，覆蓋 delta payload，刪除 removed 清單。"""
    shutil.copytree(install_dir, staging, dirs_exist_ok=True)
    payload_dir = delta_root / DELTA_PAYLOAD_DIR
    files = manifest.get("files", {})
    if payload_dir.is_dir():
        for p in sorted(payload_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(payload_dir).as_posix()
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            expect = files.get(rel)
            if expect is None or sha256_of_file(dst) != expect["sha256"]:
                raise DeltaUpdateError(f"delta 檔案驗證失敗: {rel}")
    for rel in manifest.get("removed", []):
        (staging / rel).unlink(missing_ok=True)


def verify_tree(root: Path, manifest: dict) -> bool:
    """整棵 staging 樹對 manifest 全檔驗證（torn copy / 損壞的最後防線）。"""
    files = manifest.get("files", {})
    for rel, meta in files.items():
        p = root / rel
        try:
            if not p.is_file() or p.stat().st_size != meta["size"]:
                return False
            if sha256_of_file(p) != meta["sha256"]:
                return False
        except OSError:
            return False
    return True


def download_delta_update(
    info: UpdateInfo,
    progress_cb=None,
    cancel_event=None,
    fallback_cb=None,
) -> Path:
    """下載 delta.zip → 建立 staging（複製目前安裝樹 + 覆蓋變更）。

    僅「delta 不適用／驗證失敗」（DeltaUpdateError）自動退回整包；
    網路／取消等一般錯誤直接往上拋，與整包下載行為一致。
    """
    if not info.delta_url:
        return download_update(info, progress_cb, cancel_event)

    clean_stale_temp_dirs()
    tmp_dir = Path(tempfile.mkdtemp(prefix="ocr_update_"))
    try:
        zip_path = tmp_dir / DELTA_ASSET_NAME
        log.info("開始下載差異更新 v%s", info.version)
        _download_to(info.delta_url, zip_path, progress_cb, cancel_event)

        delta_root = tmp_dir / "delta"
        _safe_extract(zip_path, delta_root)

        manifest_path = delta_root / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise DeltaUpdateError("delta 缺少 manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("base_version") != info.delta_base_version:
            raise DeltaUpdateError("delta 版本基準不符")

        install_dir = current_exe_path().parent
        if not (install_dir / "_internal").is_dir():
            raise DeltaUpdateError("非 onedir 安裝")

        staging = tmp_dir / "staging"
        apply_delta_to_staging(install_dir, staging, delta_root, manifest)
        if not verify_tree(staging, manifest):
            raise DeltaUpdateError("staging 樹驗證失敗")
        log.info("差異更新完成: %s", staging)
        return staging
    except DeltaUpdateError as e:
        log.warning("差異更新不適用（%s），改用完整更新", e)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if fallback_cb:
            fallback_cb()
        return download_update(info, progress_cb, cancel_event)
    except Exception:
        log.exception("差異更新下載失敗")
        shutil.rmtree(tmp_dir, ignore_errors=True)
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

    # ── delta 純函式 self-check ──
    tmp = Path(tempfile.mkdtemp(prefix="ocr_delta_demo_"))
    try:
        old = tmp / "old"
        new = tmp / "new"
        dl = tmp / "dl"
        for d in (old, new, dl):
            d.mkdir()
        (old / "same.txt").write_text("same", encoding="utf-8")
        (old / "gone.txt").write_text("bye", encoding="utf-8")
        (old / "mod.txt").write_text("old", encoding="utf-8")
        (new / "same.txt").write_text("same", encoding="utf-8")
        (new / "mod.txt").write_text("new", encoding="utf-8")
        (new / "fresh.txt").write_text("hi", encoding="utf-8")

        prev = build_manifest(old, "0.1.0", "0.0.9")
        nxt = build_manifest(new, "0.2.0", "0.1.0")
        changed, added, removed = diff_manifests(prev, nxt)
        assert changed == ["mod.txt"], f"changed={changed}"
        assert added == ["fresh.txt"], f"added={added}"
        assert removed == ["gone.txt"], f"removed={removed}"

        nxt["removed"] = removed
        for rel in changed + added:
            dst = dl / DELTA_PAYLOAD_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(new / rel, dst)

        staging = tmp / "staging"
        apply_delta_to_staging(old, staging, dl, nxt)
        assert (staging / "same.txt").read_text(encoding="utf-8") == "same"
        assert (staging / "mod.txt").read_text(encoding="utf-8") == "new"
        assert (staging / "fresh.txt").read_text(encoding="utf-8") == "hi"
        assert not (staging / "gone.txt").exists()
        assert verify_tree(staging, nxt)

        (staging / "mod.txt").write_text("tampered", encoding="utf-8")
        assert not verify_tree(staging, nxt)
        print("\u2713 delta \u7d14\u51fd\u6578: \u5168\u90e8\u901a\u904e")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    demo()
