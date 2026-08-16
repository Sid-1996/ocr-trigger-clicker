"""差異更新（delta）純函式單元測試（無網路、本機 fake tree）。"""

import sys
import zipfile
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

_u = load_sibling("updater", "core/12_updater.py")


def _make_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _payload_dir(dl: Path, rel: str, content: str) -> None:
    dst = dl / _u.DELTA_PAYLOAD_DIR / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content, encoding="utf-8")


def test_build_manifest_hashes_and_metadata(tmp_path):
    _make_tree(tmp_path, {"a.txt": "x", "sub/b.txt": "yy"})
    m = _u.build_manifest(tmp_path, "0.2.0", "0.1.0")
    assert m["version"] == "0.2.0"
    assert m["base_version"] == "0.1.0"
    assert set(m["files"]) == {"a.txt", "sub/b.txt"}
    assert m["files"]["a.txt"]["size"] == 1
    assert m["files"]["a.txt"]["sha256"] == _u.sha256_of_file(tmp_path / "a.txt")


def test_diff_manifests_categories(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _make_tree(old, {"same.txt": "s", "mod.txt": "v1", "gone.txt": "g"})
    _make_tree(new, {"same.txt": "s", "mod.txt": "v2", "fresh.txt": "f"})
    changed, added, removed = _u.diff_manifests(
        _u.build_manifest(old, "0.1.0", "0.0.9"),
        _u.build_manifest(new, "0.2.0", "0.1.0"),
    )
    assert changed == ["mod.txt"]
    assert added == ["fresh.txt"]
    assert removed == ["gone.txt"]


def test_apply_delta_overlay_delete_keep(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    dl = tmp_path / "dl"
    _make_tree(old, {"same.txt": "s", "mod.txt": "v1", "gone.txt": "g"})
    _make_tree(new, {"same.txt": "s", "mod.txt": "v2", "fresh.txt": "f"})
    prev = _u.build_manifest(old, "0.1.0", "0.0.9")
    nxt = _u.build_manifest(new, "0.2.0", "0.1.0")
    changed, added, removed = _u.diff_manifests(prev, nxt)
    nxt["removed"] = removed
    for rel in changed + added:
        _payload_dir(dl, rel, (new / rel).read_text(encoding="utf-8"))

    staging = tmp_path / "staging"
    _u.apply_delta_to_staging(old, staging, dl, nxt)
    assert (staging / "same.txt").read_text(encoding="utf-8") == "s"
    assert (staging / "mod.txt").read_text(encoding="utf-8") == "v2"
    assert (staging / "fresh.txt").read_text(encoding="utf-8") == "f"
    assert not (staging / "gone.txt").exists()
    assert _u.verify_tree(staging, nxt)


def test_apply_delta_detects_tampered_payload(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    dl = tmp_path / "dl"
    _make_tree(old, {"mod.txt": "v1"})
    _make_tree(new, {"mod.txt": "v2"})
    prev = _u.build_manifest(old, "0.1.0", "0.0.9")
    nxt = _u.build_manifest(new, "0.2.0", "0.1.0")
    changed, added, removed = _u.diff_manifests(prev, nxt)
    nxt["removed"] = removed
    _payload_dir(dl, "mod.txt", "TAMPERED")
    try:
        _u.apply_delta_to_staging(old, tmp_path / "staging", dl, nxt)
        assert False, "payload 與 manifest hash 不符應拋錯"
    except _u.DeltaUpdateError:
        pass


def test_verify_tree_detects_corruption(tmp_path):
    root = tmp_path / "tree"
    _make_tree(root, {"a.txt": "ok"})
    m = _u.build_manifest(root, "0.1.0", "0.0.9")
    assert _u.verify_tree(root, m)
    (root / "a.txt").write_text("tampered", encoding="utf-8")
    assert not _u.verify_tree(root, m)
    (root / "a.txt").unlink()
    assert not _u.verify_tree(root, m)


def test_safe_extract_rejects_traversal(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../evil.txt", "boom")
    dest = tmp_path / "dest"
    dest.mkdir()
    try:
        _u._safe_extract(bad, dest)
        assert False, "應拒絕路徑穿越"
    except _u.DeltaUpdateError:
        pass
