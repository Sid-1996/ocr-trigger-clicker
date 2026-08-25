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


# ── 資產可達性探測（發布窗口期防護）──

import json  # noqa: E402
from urllib.error import HTTPError  # noqa: E402


class _Resp:
    status = 200

    def __init__(self, body=b""):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _fake_urlopen_by_url(routes):
    """routes: list[(predicate(url)->bool, callable(url))]，依序比對。"""

    def fake(req, timeout=0):
        url = getattr(req, "full_url", req)
        for pred, action in routes:
            if pred(url):
                return action(url)
        raise AssertionError(f"未預期的 URL: {url}")

    return fake


def test_check_for_update_skips_when_asset_404(monkeypatch):
    probes = []

    def probe(url):
        probes.append(url)
        raise HTTPError(url, 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr(
        _u,
        "urlopen",
        _fake_urlopen_by_url(
            [
                (lambda u: u == _u.RAW_VERSION_URL, lambda u: _Resp(b"9.9.9\n")),
                (lambda u: u == _u.RAW_DELTA_URL, lambda u: HTTPError(u, 404, "nf", None, None)),
                (lambda u: True, probe),
            ]
        ),
    )
    assert _u.check_for_update("0.1.0") is None
    assert any(_u.ASSET_NAME in u for u in probes), "整包資產應被探測"


def test_check_for_update_drops_missing_delta_asset(monkeypatch):
    delta_info = json.dumps(
        {
            "version": "9.9.9",
            "base_version": "0.1.0",
            "asset": _u.DELTA_ASSET_NAME,
            "delta_bytes": 123,
        }
    ).encode()
    monkeypatch.setattr(
        _u,
        "urlopen",
        _fake_urlopen_by_url(
            [
                (lambda u: u == _u.RAW_VERSION_URL, lambda u: _Resp(b"9.9.9\n")),
                (lambda u: u == _u.RAW_DELTA_URL, lambda u: _Resp(delta_info)),
                (lambda u: _u.DELTA_ASSET_NAME in u, lambda u: HTTPError(u, 404, "nf", None, None)),
                (lambda u: True, lambda u: _Resp()),
            ]
        ),
    )
    info = _u.check_for_update("0.1.0")
    assert info is not None and info.version == "9.9.9"
    assert info.delta_url is None and info.delta_bytes == 0, "delta 資產缺席應捨棄、保留整包"


def test_check_for_update_fail_open_on_network_error(monkeypatch):
    monkeypatch.setattr(
        _u,
        "urlopen",
        _fake_urlopen_by_url(
            [
                (lambda u: u == _u.RAW_VERSION_URL, lambda u: _Resp(b"9.9.9\n")),
                (lambda u: True, lambda u: (_ for _ in ()).throw(OSError("network down"))),
            ]
        ),
    )
    info = _u.check_for_update("0.1.0")
    assert info is not None and info.version == "9.9.9", "網路異常應 fail-open 照常提供更新"
