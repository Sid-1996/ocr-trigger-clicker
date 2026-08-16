#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""發版工具：為「上一版 → 本版」產生差異更新。

由 release.ps1 在 python build.py + 壓整包 ZIP 之後呼叫，輸出：
- <out_dir>/ocr-trigger-clicker-delta.zip  差異壓縮檔（GitHub release asset）
- <repo_root>/manifest.json                 本版完整檔案清單（下一版當基準）
- <repo_root>/delta_info.json               用戶端 raw 讀取用的判定資料

用法：python make_delta.py <version> <base_version> <app_dir> [out_dir]
"""

import importlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

DELTA_ASSET = "ocr-trigger-clicker-delta.zip"
FULL_ASSET = "ocr-trigger-clicker.zip"
# ponytail: delta 超過整包 40% 就沒意義，直接不發布、用戶端走完整更新
_DELTA_MAX_FRACTION = 0.4


def _updater():
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    return importlib.import_module("core.12_updater")


def _write_delta_zip(delta_zip: Path, manifest: dict, app_dir: Path, payload: list[str]) -> None:
    with zipfile.ZipFile(delta_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for rel in payload:
            zf.write(app_dir / rel, f"files/{rel}")


def run(
    version: str,
    base_version: str,
    app_dir: Path,
    out_dir: Path,
    repo_root: Path,
    prev_manifest_path: Path,
) -> None:
    app_dir = Path(app_dir)
    out_dir = Path(out_dir)
    updater = _updater()
    new = updater.build_manifest(app_dir, version, base_version)

    prev_ok = False
    if prev_manifest_path.is_file():
        prev = json.loads(prev_manifest_path.read_text(encoding="utf-8"))
        prev_ok = prev.get("version") == base_version
    else:
        prev = None

    publish_delta = False
    if prev_ok:
        changed, added, removed = updater.diff_manifests(prev, new)
        new["removed"] = removed
        if changed or added or removed:
            delta_zip = out_dir / DELTA_ASSET
            _write_delta_zip(delta_zip, new, app_dir, changed + added)
            full_zip = out_dir / FULL_ASSET
            full_size = full_zip.stat().st_size if full_zip.is_file() else 0
            if full_size and delta_zip.stat().st_size > full_size * _DELTA_MAX_FRACTION:
                delta_zip.unlink(missing_ok=True)
                print(f"[make_delta] delta 過大（>{_DELTA_MAX_FRACTION:.0%} 整包），不發布差異更新")
            else:
                publish_delta = True
                print(
                    f"[make_delta] 產出 {delta_zip.name}: "
                    f"{delta_zip.stat().st_size / 1024:.0f} KB "
                    f"(變更 {len(changed)} / 新增 {len(added)} / 刪除 {len(removed)})"
                )
        else:
            print("[make_delta] 本版與上一版無差異，不產 delta")
    else:
        reason = "無前一版 manifest" if prev is None else "前一版 manifest 版本不符"
        print(f"[make_delta] {reason}（base={base_version}），不產 delta")

    (repo_root / "manifest.json").write_text(
        json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    delta_info = {
        "version": version,
        "base_version": base_version if publish_delta else "",
        "asset": DELTA_ASSET if publish_delta else "",
        "delta_bytes": (out_dir / DELTA_ASSET).stat().st_size if publish_delta else 0,
    }
    (repo_root / "delta_info.json").write_text(
        json.dumps(delta_info, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"[make_delta] manifest.json / delta_info.json 已更新（publish_delta={publish_delta}）")


def main():
    if "--demo" in sys.argv or len(sys.argv) < 4:
        _demo()
        return
    version, base_version = sys.argv[1], sys.argv[2]
    app_dir = Path(sys.argv[3])
    out_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else app_dir.parent
    run(version, base_version, app_dir, out_dir, _ROOT, _ROOT / "manifest.json")


def _demo():
    tmp = Path(tempfile.mkdtemp(prefix="ocr_mkdelta_demo_"))
    try:
        old = tmp / "old"
        new = tmp / "new"
        out = tmp / "out"
        repo = tmp / "repo"
        for d in (old, new, out, repo):
            d.mkdir()
        (old / "a.txt").write_text("a", encoding="utf-8")
        (old / "b.txt").write_text("b", encoding="utf-8")
        (new / "a.txt").write_text("a", encoding="utf-8")
        (new / "b.txt").write_text("b2", encoding="utf-8")
        (new / "c.txt").write_text("c", encoding="utf-8")
        updater = _updater()
        prev = updater.build_manifest(old, "0.1.0", "0.0.9")
        (repo / "manifest.json").write_text(json.dumps(prev, ensure_ascii=False), encoding="utf-8")

        run("0.2.0", "0.1.0", new, out, repo, repo / "manifest.json")

        delta_zip = out / DELTA_ASSET
        assert delta_zip.is_file(), "應產出 delta.zip"
        with zipfile.ZipFile(delta_zip) as zf:
            names = zf.namelist()
            assert "manifest.json" in names, f"delta 缺 manifest.json: {names}"
            assert "files/b.txt" in names and "files/c.txt" in names, names
            assert "files/a.txt" not in names, "未變更檔案不應在 delta"
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["base_version"] == "0.1.0", manifest
        assert manifest["removed"] == [], manifest["removed"]
        info = json.loads((repo / "delta_info.json").read_text(encoding="utf-8"))
        assert info["version"] == "0.2.0" and info["base_version"] == "0.1.0", info
        print("✓ make_delta --demo: 全部通過")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
