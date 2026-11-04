"""AppCompat RUNASADMIN 層級自癒的測試。

背景
----
Windows 把「以系統管理員身分執行」（RUNASADMIN）記錄在
``HKCU\\Software\\Microsoft\\Windows NT\\CurrentVersion\\AppCompatFlags\\Layers``
的值名稱（值名 = 執行檔完整路徑）。Velopack 以**非提權** CreateProcess 啟動
``--veloapp-install`` hook，一旦該執行檔帶著 RUNASADMIN 層級，Windows 就以
Win32 740（``os error -2147024156``）拒絕啟動，安裝／更新必然失敗。

本檔鎖住的不變量：

- 只移除 RUNASADMIN token（含其 ``~``／``$`` 前綴 token），同一條目裡其他
  相容性設定原樣保留，且不留下孤立的前綴 token。
- 只處理「**相對於安裝根目錄**、屬於本程式執行檔」的路徑，安裝目錄內其他
  軟體的同名程式（如外來 ``update.exe``）不得受影響。
- 路徑比對前展開 ``..``：``<root>\\..\\Other\\x.exe`` 不得被當成在根目錄之下。
- 開發模式（未打包）什麼都不做。
- 不得呼叫真 registry（全部注入假的 read / write）。
"""

import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402

_AC = load_sibling("appcompat", "core/13_appcompat.py")


def _velopack_root(tmp_path: Path) -> Path:
    """建立假的 Velopack onedir 安裝根（current + packages 是 Velopack 特有結構）。"""
    root = tmp_path / "OCRTriggerClicker"
    (root / "current").mkdir(parents=True)
    (root / "packages").mkdir()
    (root / "current" / "ocr-trigger-clicker.exe").write_text("", encoding="utf-8")
    (root / "OCR Trigger Clicker.exe").write_text("", encoding="utf-8")
    (root / "Update.exe").write_text("", encoding="utf-8")
    return root


def _portable_dir(tmp_path: Path, name: str = "portable") -> Path:
    """假 portable 版（執行檔直接放在資料夾裡，沒有 Velopack 結構）。"""
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "ocr-trigger-clicker.exe").write_text("", encoding="utf-8")
    return d


# ── 前綴／token 解析 ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        ("~ RUNASADMIN", None),
        ("RUNASADMIN", None),
        ("$ RUNASADMIN", None),
        ("~ runasadmin", None),
        ("$RUNASADMIN", None),
        ("~ RUNASADMIN WINXPSP3", "WINXPSP3"),
        ("RUNASADMIN WINXPSP3", "WINXPSP3"),
        ("$ RUNASADMIN WINXPSP3", "WINXPSP3"),
        ("~ DISABLEDXMAXIMIZEDWINDOWEDMODE RUNASADMIN", "~ DISABLEDXMAXIMIZEDWINDOWEDMODE"),
        ("WINXPSP3", "WINXPSP3"),
        ("~ WINXPSP3", "~ WINXPSP3"),
        ("$ WIN7RTM", "$ WIN7RTM"),
        ("~ PERPROCESSSYSTEMDPIFORCEOFF", "~ PERPROCESSSYSTEMDPIFORCEOFF"),
        # 不得因為含 RUNASADMIN 子字串就誤刪其他旗標
        ("DISABLERUNASADMIN", "DISABLERUNASADMIN"),
        ("", ""),
    ],
)
def test_strip_runasadmin(value, expected):
    assert _AC.strip_runasadmin(value) == expected


def test_strip_runasadmin_never_leaves_orphan_prefix():
    """移除 RUNASADMIN 時不得留下孤立的 '~' / '$' token。"""
    for value in ("~ RUNASADMIN", "$ RUNASADMIN", "~ RUNASADMIN WINXPSP3"):
        result = _AC.strip_runasadmin(value)
        assert result is None or "~" not in result.split()
        assert result is None or "$" not in result.split()


# ── 安裝根目錄推導 ────────────────────────────────────────────────────────


def test_install_root_detects_velopack_layout(tmp_path, monkeypatch):
    root = _velopack_root(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(root / "current" / "ocr-trigger-clicker.exe"))
    assert _AC.install_root() == root


def test_install_root_uses_exe_dir_for_portable(tmp_path, monkeypatch):
    d = _portable_dir(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(d / "ocr-trigger-clicker.exe"))
    assert _AC.install_root() == d


def test_install_root_does_not_widen_for_portable_named_current(tmp_path, monkeypatch):
    """portable 版放在名為 'current' 的資料夾時，不得回推到上一層。"""
    d = _portable_dir(tmp_path, name="current")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(d / "ocr-trigger-clicker.exe"))
    assert _AC.install_root() == d


def test_install_root_arbitrary_directory(tmp_path, monkeypatch):
    d = tmp_path / "whatever"
    d.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(d / "ocr-trigger-clicker.exe"))
    assert _AC.install_root() == d


def test_install_root_none_in_dev_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert _AC.install_root() is None


# ── 候選路徑篩選 ──────────────────────────────────────────────────────────


def test_candidate_paths_accepts_own_executables_in_velopack_root(tmp_path):
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")
    names = [
        own,
        str(root / "OCR Trigger Clicker.exe"),
        str(root / "Update.exe"),
    ]
    assert _AC.candidate_paths(root, names=names, exe=own) == names


def test_candidate_paths_keeps_foreign_update_exe_inside_root(tmp_path):
    """安裝根目錄內的外來 update.exe 不得列入候選。"""
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")
    foreign = str(root / "current" / "update.exe")
    names = [own, str(root / "Update.exe"), foreign]
    assert foreign not in _AC.candidate_paths(root, names=names, exe=own)


def test_candidate_paths_keeps_update_exe_in_non_velopack_root(tmp_path):
    """無法確認是 Velopack 根目錄時，寧可不處理 update.exe。"""
    d = _portable_dir(tmp_path)
    own = str(d / "ocr-trigger-clicker.exe")
    names = [own, str(d / "update.exe")]
    assert _AC.candidate_paths(d, names=names, exe=own) == [own]


def test_candidate_paths_rejects_path_escaping_root(tmp_path):
    """<root>\\..\\Other\\x.exe 不得被當成在 root 之下。"""
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")
    escape = str(root / ".." / "Other" / "ocr-trigger-clicker.exe")
    assert escape not in _AC.candidate_paths(root, names=[own, escape], exe=own)


def test_candidate_paths_rejects_sibling_prefix(tmp_path):
    """根目錄字串相同但不同資料夾的路徑不可誤判。"""
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")
    sibling = str(tmp_path / "OCRTriggerClickerEvil" / "current" / "ocr-trigger-clicker.exe")
    assert sibling not in _AC.candidate_paths(root, names=[own, sibling], exe=own)


def test_candidate_paths_is_case_insensitive(tmp_path):
    """Windows 路徑大小寫不敏感。"""
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")
    lower = own.replace("OCRTriggerClicker", "ocrtriggerclicker")
    assert _AC.candidate_paths(root, names=[lower], exe=own) == [lower]


def test_candidate_paths_empty_without_root():
    assert _AC.candidate_paths(None, names=[r"C:\app\current\ocr-trigger-clicker.exe"]) == []


# ── 清除行為 ──────────────────────────────────────────────────────────────


def _fake_registry(store):
    def _read(path):
        return store.get(path)

    def _write(path, value):
        if value is None:
            store.pop(path, None)
        else:
            store[path] = value
        return True

    return _read, _write


def test_clear_runasadmin_removes_entry_and_reports(tmp_path):
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")
    store = {own: "~ RUNASADMIN"}
    read, write = _fake_registry(store)
    fixed = _AC.clear_runasadmin(
        _AC.candidate_paths(root, names=list(store), exe=own), read=read, write=write
    )
    assert fixed == [own]
    assert store == {}


def test_clear_runasadmin_preserves_other_flags(tmp_path):
    root = _velopack_root(tmp_path)
    stub = str(root / "OCR Trigger Clicker.exe")
    store = {stub: "RUNASADMIN WINXPSP3"}
    read, write = _fake_registry(store)
    _AC.clear_runasadmin(
        _AC.candidate_paths(root, names=list(store), exe=stub), read=read, write=write
    )
    assert store == {stub: "WINXPSP3"}


def test_clear_runasadmin_keeps_foreign_update_exe_value(tmp_path):
    """端對端守門：安裝根內外來 update.exe 的 Registry 值必須完整保留。"""
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")
    foreign = str(root / "current" / "update.exe")
    store = {
        own: "~ RUNASADMIN",
        foreign: "~ RUNASADMIN",
        str(root / "Update.exe"): "~ RUNASADMIN",
    }
    read, write = _fake_registry(store)
    fixed = _AC.clear_runasadmin(
        _AC.candidate_paths(root, names=list(store), exe=own), read=read, write=write
    )
    assert foreign not in fixed
    assert store[foreign] == "~ RUNASADMIN"
    # Velopack 自己的 Update.exe 仍可被處理（根目錄結構已確認 → 整條刪除）
    assert str(root / "Update.exe") not in store


def test_clear_runasadmin_leaves_unrelated_entries_untouched(tmp_path):
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")
    other = r"C:\other\python.exe"
    store = {own: "~ RUNASADMIN", other: "RUNASADMIN"}
    read, write = _fake_registry(store)
    fixed = _AC.clear_runasadmin(
        _AC.candidate_paths(root, names=list(store), exe=own), read=read, write=write
    )
    assert fixed == [own]
    assert store[other] == "RUNASADMIN"


def test_clear_runasadmin_is_idempotent(tmp_path):
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")
    store = {own: "~ RUNASADMIN"}
    read, write = _fake_registry(store)
    paths = _AC.candidate_paths(root, names=list(store), exe=own)
    _AC.clear_runasadmin(paths, read=read, write=write)
    assert _AC.clear_runasadmin(paths, read=read, write=write) == []


def test_clear_runasadmin_ignores_entries_without_runasadmin(tmp_path):
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")
    store = {own: "WINXPSP3"}
    read, write = _fake_registry(store)
    assert (
        _AC.clear_runasadmin(
            _AC.candidate_paths(root, names=list(store), exe=own), read=read, write=write
        )
        == []
    )
    assert store == {own: "WINXPSP3"}


def test_clear_runasadmin_survives_write_failure(tmp_path):
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")
    store = {own: "~ RUNASADMIN"}
    read, _write = _fake_registry(store)
    fixed = _AC.clear_runasadmin(
        _AC.candidate_paths(root, names=list(store), exe=own),
        read=read,
        write=lambda path, value: False,
    )
    assert fixed == []
    assert store[own] == "~ RUNASADMIN"


def test_clear_runasadmin_survives_read_exception(tmp_path):
    root = _velopack_root(tmp_path)
    own = str(root / "current" / "ocr-trigger-clicker.exe")

    def _boom(_path):
        raise OSError("registry unavailable")

    assert _AC.clear_runasadmin([own], read=_boom, write=lambda p, v: True) == []


def test_heal_uses_candidate_paths(monkeypatch):
    store = {r"C:\app\current\ocr-trigger-clicker.exe": "~ RUNASADMIN"}
    read, write = _fake_registry(store)
    monkeypatch.setattr(_AC, "read_layer", read)
    monkeypatch.setattr(_AC, "write_layer", write)
    monkeypatch.setattr(_AC, "candidate_paths", lambda root=None: list(store))
    assert _AC.heal() == [r"C:\app\current\ocr-trigger-clicker.exe"]
    assert store == {}


def test_heal_without_candidates_is_noop(monkeypatch):
    monkeypatch.setattr(_AC, "candidate_paths", lambda root=None: [])
    assert _AC.heal() == []
