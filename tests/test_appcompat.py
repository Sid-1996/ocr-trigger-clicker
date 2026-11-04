"""AppCompat RUNASADMIN 層級自癒的測試。

背景
----
Windows 把「以系統管理員身分執行」（RUNASADMIN）記錄在
``HKCU\\Software\\Microsoft\\Windows NT\\CurrentVersion\\AppCompatFlags\\Layers``
的值名稱（值名 = 執行檔完整路徑）。Velopack 以**非提權** CreateProcess 啟動
``--veloapp-install`` hook，一旦該執行檔帶著 RUNASADMIN 層級，Windows 就以
Win32 740（``os error -2147024156``）拒絕啟動，安裝／更新必然失敗。

本檔鎖住的不變量：

- 只移除 RUNASADMIN token，同一條目裡其他相容性設定原樣保留。
- 只處理「本程式安裝根目錄下、檔名屬於本程式執行檔」的路徑，
  不得動到使用者的其他程式（例如開發模式的 python.exe）。
- 自癒流程必須可重複執行（第二次沒有變更）。
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


@pytest.mark.parametrize(
    "value,expected",
    [
        ("~ RUNASADMIN", None),
        ("RUNASADMIN", None),
        ("~ runasadmin", None),
        ("~ RUNASADMIN WINXPSP3", "WINXPSP3"),
        ("WINXPSP3 RUNASADMIN", "WINXPSP3"),
        ("~ RUNASADMIN WINXPSP3 DISABLETHEMES", "WINXPSP3 DISABLETHEMES"),
        ("WINXPSP3", "WINXPSP3"),
        ("~ WINXPSP3", "~ WINXPSP3"),
        ("", ""),
    ],
)
def test_strip_runasadmin(value, expected):
    assert _AC.strip_runasadmin(value) == expected


def test_candidate_paths_only_own_executables_under_root():
    """只挑安裝根目錄下、檔名屬本程式執行檔的路徑。"""
    names = [
        r"C:\app\current\ocr-trigger-clicker.exe",
        r"C:\app\current\other-tool.exe",
        r"C:\app\OCR Trigger Clicker.exe",
        r"C:\app\Update.exe",
        r"C:\app\packages\OCRTriggerClicker-0.4.9-full.nupkg",
        r"C:\other\python.exe",
    ]
    paths = _AC.candidate_paths(Path(r"C:\app"), names=names)
    assert paths == [
        r"C:\app\current\ocr-trigger-clicker.exe",
        r"C:\app\OCR Trigger Clicker.exe",
        r"C:\app\Update.exe",
    ]


def test_candidate_paths_ignores_sibling_prefix():
    """根目錄字串相同但不同資料夾的路徑不可誤判（需路徑分隔符才算在根底下）。"""
    names = [r"C:\app2\current\ocr-trigger-clicker.exe"]
    assert _AC.candidate_paths(Path(r"C:\app"), names=names) == []


def test_candidate_paths_empty_without_root():
    assert _AC.candidate_paths(None, names=[r"C:\app\current\ocr-trigger-clicker.exe"]) == []


def test_install_root_detects_velopack_layout(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\app\current\ocr-trigger-clicker.exe")
    assert _AC.install_root() == Path(r"C:\app")


def test_install_root_detects_portable_layout(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\app\ocr-trigger-clicker.exe")
    assert _AC.install_root() == Path(r"C:\app")


def test_install_root_none_in_dev_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert _AC.install_root() is None


def test_candidate_paths_includes_frozen_executable(monkeypatch):
    """打包版的自身執行檔即使 registry 沒記錄也要納入（啟動時自癒）。"""
    exe = r"C:\app\current\ocr-trigger-clicker.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", exe)
    paths = _AC.candidate_paths(Path(r"C:\app"), names=[])
    assert paths == [exe]


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


def test_clear_runasadmin_removes_entry_and_reports():
    store = {r"C:\app\current\ocr-trigger-clicker.exe": "~ RUNASADMIN"}
    read, write = _fake_registry(store)
    fixed = _AC.clear_runasadmin(list(store), read=read, write=write)
    assert fixed == [r"C:\app\current\ocr-trigger-clicker.exe"]
    assert store == {}


def test_clear_runasadmin_preserves_other_flags():
    store = {r"C:\app\OCR Trigger Clicker.exe": "RUNASADMIN WINXPSP3"}
    read, write = _fake_registry(store)
    _AC.clear_runasadmin(list(store), read=read, write=write)
    assert store == {r"C:\app\OCR Trigger Clicker.exe": "WINXPSP3"}


def test_clear_runasadmin_leaves_unrelated_entries_untouched():
    store = {
        r"C:\app\current\ocr-trigger-clicker.exe": "~ RUNASADMIN",
        r"C:\other\python.exe": "RUNASADMIN",
    }
    read, write = _fake_registry(store)
    fixed = _AC.clear_runasadmin(
        [r"C:\app\current\ocr-trigger-clicker.exe"], read=read, write=write
    )
    assert fixed == [r"C:\app\current\ocr-trigger-clicker.exe"]
    assert store[r"C:\other\python.exe"] == "RUNASADMIN"


def test_clear_runasadmin_is_idempotent():
    store = {r"C:\app\current\ocr-trigger-clicker.exe": "~ RUNASADMIN"}
    read, write = _fake_registry(store)
    _AC.clear_runasadmin(list(store), read=read, write=write)
    assert _AC.clear_runasadmin(list(store), read=read, write=write) == []


def test_clear_runasadmin_ignores_entries_without_runasadmin():
    store = {r"C:\app\current\ocr-trigger-clicker.exe": "WINXPSP3"}
    read, write = _fake_registry(store)
    assert _AC.clear_runasadmin(list(store), read=read, write=write) == []
    assert store == {r"C:\app\current\ocr-trigger-clicker.exe": "WINXPSP3"}


def test_clear_runasadmin_survives_write_failure():
    store = {r"C:\app\current\ocr-trigger-clicker.exe": "~ RUNASADMIN"}
    read, _write = _fake_registry(store)
    fixed = _AC.clear_runasadmin(
        list(store),
        read=read,
        write=lambda path, value: False,
    )
    assert fixed == []
    assert store[r"C:\app\current\ocr-trigger-clicker.exe"] == "~ RUNASADMIN"


def test_heal_uses_candidate_paths(monkeypatch):
    store = {r"C:\app\current\ocr-trigger-clicker.exe": "~ RUNASADMIN"}
    read, write = _fake_registry(store)
    monkeypatch.setattr(_AC, "read_layer", read)
    monkeypatch.setattr(_AC, "write_layer", write)
    monkeypatch.setattr(_AC, "candidate_paths", lambda root=None: list(store))
    assert _AC.heal() == [r"C:\app\current\ocr-trigger-clicker.exe"]
    assert store == {}


def test_heal_without_candidates_is_noop(monkeypatch):
    monkeypatch.setattr(_AC, "candidate_paths", lambda: [])
    assert _AC.heal() == []
