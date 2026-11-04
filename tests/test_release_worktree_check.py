import re
import subprocess
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_release = _root / "release.ps1"
_src = _release.read_text(encoding="utf-8")
_match = re.search(
    r"function Get-BlockingGitStatus \{.*?\n\}\n\s*\n\$status = git status",
    _src,
    re.S,
)
assert _match, "release.ps1 找不到 Get-BlockingGitStatus 函式"
_func = _match.group(0).rsplit("\n$status", 1)[0]
if "function Get-BlockingGitStatus" not in _func:
    tail = _func.rfind("\n}")
    _func = _func[: tail + 2]


def _run(lines):
    script = _func + "\n@(" + ",".join(
        "'" + line.replace("'", "''") + "'" for line in lines
    ) + ") | ForEach-Object { Get-BlockingGitStatus -StatusLines @($_) } | ForEach-Object { $_ }"
    proc = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_only_agents_passes():
    assert _run(["?? .agents/"]).strip() == ""


def test_only_skills_lock_passes():
    assert _run(["?? skills-lock.json"]).strip() == ""


def test_both_allowed_pass():
    assert _run(["?? .agents/", "?? skills-lock.json"]).strip() == ""


def test_other_untracked_blocks():
    assert "?? other.txt" in _run(["?? other.txt"])


def test_tracked_unstaged_blocks():
    assert " M README.md" in _run([" M README.md"])


def test_tracked_staged_blocks():
    assert "M  README.md" in _run(["M  README.md"])


def test_allowed_plus_other_blocks():
    out = _run(["?? .agents/", "?? skills-lock.json", " M README.md"])
    assert " M README.md" in out


def test_similar_path_not_allowed():
    assert "?? .agents-extra/" in _run(["?? .agents-extra/"])


def test_quoted_path_and_whitespace():
    assert _run(['?? ".agents/" ']).strip() == ""


if __name__ == "__main__":
    test_only_agents_passes()
    test_only_skills_lock_passes()
    test_both_allowed_pass()
    test_other_untracked_blocks()
    test_tracked_unstaged_blocks()
    test_tracked_staged_blocks()
    test_allowed_plus_other_blocks()
    test_similar_path_not_allowed()
    test_quoted_path_and_whitespace()
    print("OK release worktree check self-check")
