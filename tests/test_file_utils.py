import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from core.file_utils import _replace_file  # noqa: E402


def test_replace_creates_and_overwrites(tmp_path):
    dst = tmp_path / "data.json"
    tmp1 = tmp_path / "tmp1"
    tmp1.write_text("v1", encoding="utf-8")
    _replace_file(str(tmp1), str(dst))
    assert dst.read_text(encoding="utf-8") == "v1"
    assert not tmp1.exists(), "replace 後暫存檔應消失"

    # 覆蓋既有檔案
    tmp2 = tmp_path / "tmp2"
    tmp2.write_text("v2", encoding="utf-8")
    _replace_file(str(tmp2), str(dst))
    assert dst.read_text(encoding="utf-8") == "v2"
    assert not tmp2.exists()


def test_replace_failure_cleans_tmp_and_raises(tmp_path, monkeypatch):
    dst = tmp_path / "data.json"
    dst.write_text("old", encoding="utf-8")
    tmp = tmp_path / "tmp_x"
    tmp.write_text("new", encoding="utf-8")

    def _boom(src, d):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", _boom)
    with pytest.raises(OSError):
        _replace_file(str(tmp), str(dst))
    assert not tmp.exists(), "失敗時應清理暫存檔"
    assert dst.read_text(encoding="utf-8") == "old", "失敗時原檔不應被破壞"
