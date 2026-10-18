import subprocess
from pathlib import Path

__version__ = "0.4.7"
__author__ = "Sid"
__github__ = "https://github.com/Sid-1996/ocr-trigger-clicker"


def build_id() -> str:
    """建置識別：dev 取 git 短雜湊，凍結 exe 無 .git 時退回空字串。

    效能量測需分辨「同版號、不同 commit」的 A/B，只靠 __version__ 不夠。
    """
    root = Path(__file__).resolve().parent
    if not (root / ".git").exists():
        return ""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""

