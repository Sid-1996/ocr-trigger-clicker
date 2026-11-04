import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="release.ps1 integration tests require Windows"
)

ROOT = Path(__file__).resolve().parent.parent
RELEASE_PS1 = ROOT / "release.ps1"
TRACKED_FILES = ("_version.py", "pyproject.toml", "uv.lock", "docs/dev/CHANGELOG.md")
VERSION = "9.9.9"


def _run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=30)


def _make_repo(root):
    (root / "docs" / "dev").mkdir(parents=True, exist_ok=True)
    originals = {
        "_version.py": '__version__ = "0.4.8"\n',
        "pyproject.toml": '[project]\nname = "ocr-trigger-clicker"\nversion = "0.4.8"\n',
        "uv.lock": '[[package]]\nname = "ocr-trigger-clicker"\nversion = "0.4.8"\nsource = { virtual = "." }\n',
        "docs/dev/CHANGELOG.md": (
            "## [v9.9.9] - 草稿（尚未發布）\n\n"
            "**請下載 OCRTriggerClicker-win-Setup.exe**，安裝後自動更新。\n\n"
            "### 新功能\n\n- test\n"
        ),
    }
    for rel, content in originals.items():
        (root / rel).write_text(content, encoding="utf-8", newline="\n")

    (root / "release.ps1").write_bytes(RELEASE_PS1.read_bytes())
    assert _run(["git", "init", "-b", "master", "-q"], cwd=root).returncode == 0
    assert _run(["git", "config", "user.email", "test@example.invalid"], cwd=root).returncode == 0
    assert _run(["git", "config", "user.name", "FeedTest"], cwd=root).returncode == 0
    assert _run(["git", "add", "-A"], cwd=root).returncode == 0
    assert _run(["git", "commit", "-q", "-m", "initial"], cwd=root).returncode == 0
    return originals


_STUBS = r"""
function uv {
    if ($args[0] -eq 'run') {
        $lock = [IO.File]::ReadAllText('uv.lock') -replace 'version = "0.4.8"', 'version = "9.9.9"'
        [IO.File]::WriteAllText('uv.lock', $lock)
        if ($env:OTC_STUB_BUILD_MODE -eq 'fail') { $global:LASTEXITCODE = 1; return }
        if ($env:OTC_STUB_BUILD_MODE -eq 'throw') { throw "uv exploded" }
    }
    $global:LASTEXITCODE = 0
}

function gh {
    if ($args[0] -eq 'auth' -and $args[1] -eq 'status') { $global:LASTEXITCODE = 0; return }
    if ($args[0] -eq 'auth' -and $args[1] -eq 'token') { Write-Output "fake-token"; $global:LASTEXITCODE = 0; return }
    if ($args[0] -eq 'release' -and $args[1] -eq 'edit') { $global:LASTEXITCODE = 0; return }
    $global:LASTEXITCODE = 0
}

function vpk {
    if ($args[0] -eq 'upload' -and $env:OTC_STUB_UPLOAD_MODE -eq 'fail') {
        $global:LASTEXITCODE = 1
        return
    }
    $global:LASTEXITCODE = 0
}
"""


def _run_release(root, *, feed_test=True, build_mode="success", upload_mode="success"):
    env = os.environ.copy()
    env["OTC_STUB_BUILD_MODE"] = build_mode
    env["OTC_STUB_UPLOAD_MODE"] = upload_mode
    root_ps = str(root).replace("\\", "/")
    script_ps = str(root / "release.ps1").replace("\\", "/")
    feed_flag = " -FeedTest" if feed_test else ""
    command = (
        _STUBS
        + f'\nSet-Location "{root_ps}"\n'
        + f'& "{script_ps}" -Version "{VERSION}"{feed_flag}\n'
    )
    return subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=root,
        env=env,
        capture_output=True,
        timeout=60,
    )


def _bytes(root, rel):
    return (root / rel).read_bytes()


def _output(proc):
    return (proc.stderr + proc.stdout).decode(errors="replace")


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    originals = _make_repo(root)
    return root, originals


def _assert_original(repo_root, originals):
    for rel, content in originals.items():
        assert _bytes(repo_root, rel) == content.encode("utf-8")


def test_feedtest_success_restores_tracked_files(repo):
    repo_root, originals = repo
    proc = _run_release(repo_root, feed_test=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    _assert_original(repo_root, originals)


def test_feedtest_build_failure_restores_and_reports(repo):
    repo_root, originals = repo
    proc = _run_release(repo_root, feed_test=True, build_mode="fail")
    assert proc.returncode != 0
    assert "build.py" in _output(proc)
    _assert_original(repo_root, originals)


def test_feedtest_upload_failure_restores_and_reports(repo):
    repo_root, originals = repo
    proc = _run_release(repo_root, feed_test=True, upload_mode="fail")
    assert proc.returncode != 0
    assert "upload" in _output(proc).lower()
    _assert_original(repo_root, originals)


def test_feedtest_exception_restores_and_reports(repo):
    repo_root, originals = repo
    proc = _run_release(repo_root, feed_test=True, build_mode="throw")
    assert proc.returncode != 0
    assert "uv exploded" in _output(proc)
    _assert_original(repo_root, originals)


def test_formal_release_retains_version_updates(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)

    remote = tmp_path / "remote.git"
    assert _run(["git", "init", "--bare", "-b", "master", "-q", str(remote)]).returncode == 0
    assert _run(["git", "remote", "add", "origin", str(remote)], cwd=root).returncode == 0
    assert _run(["git", "push", "-q", "origin", "master"], cwd=root).returncode == 0

    proc = _run_release(root, feed_test=False)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert b'__version__ = "9.9.9"' in _bytes(root, "_version.py")
    assert b'version = "9.9.9"' in _bytes(root, "pyproject.toml")
    assert b'version = "9.9.9"' in _bytes(root, "uv.lock")
    assert b"2026-" in _bytes(root, "docs/dev/CHANGELOG.md")
    assert _run(["git", "tag", "-l", "v9.9.9"], cwd=root).stdout.strip() == b"v9.9.9"
    assert _run(["git", "ls-remote", "--tags", str(remote)]).stdout.count(b"v9.9.9") >= 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
