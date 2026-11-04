# -*- coding: utf-8 -*-
"""Windows 相容性層級（AppCompat）自癒：移除自身路徑上的「以系統管理員身分執行」。

背景
----
Windows 把「以系統管理員身分執行」（RUNASADMIN）記錄在

    HKCU\\Software\\Microsoft\\Windows NT\\CurrentVersion\\AppCompatFlags\\Layers

的值名稱（值名 = 執行檔完整路徑）。Velopack 的安裝器／更新器以**非提權**
CreateProcess 啟動應用程式的 ``--veloapp-install`` / ``--veloapp-uninstall`` hook；
一旦該執行檔帶著 RUNASADMIN 層級，Windows 會直接拒絕啟動
（Win32 740 ``ERROR_ELEVATION_REQUIRED``，Python 顯示為 ``os error -2147024156``），
使用者就會看到「安裝部分成功／部分安裝失敗」與「Setup 錯誤」兩個錯誤視窗。

解法
----
應用程式啟動時與套用更新前，主動移除**自己安裝目錄下、屬於本程式執行檔**的
RUNASADMIN 層級（同一條目裡其他相容性設定保留）。使用者不必理解 registry
概念，已踩雷的既有安裝也會在下次啟動時自動恢復。

本程式另有「以系統管理員身分重新啟動」按鈕，需要提權時由使用者自己按，
不必靠相容性層級常駐提權。

安全性
------
1. 只刪「**相對於安裝根目錄**、屬於本程式執行檔」的層級——不是只比對檔名，
   因此安裝目錄內其他軟體的 ``update.exe`` 之類同名檔案不受影響。
2. 路徑比對前先展開 ``..`` 並統一大小寫／分隔符，``<root>\\..\\Other\\x.exe``
   不會被誤認為在安裝根目錄之下。
3. 只移除 RUNASADMIN token（含其 ``~``／``$`` 前綴 token），同一條目裡的
   其他相容性設定原樣保留，不重新推斷其語意。
4. 只寫 ``HKEY_CURRENT_USER``，不碰其他 hive。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

LAYERS_SUBKEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
RUNASADMIN = "RUNASADMIN"

# Windows 相容性層級的前綴 token：'~' 與 '$' 都以「前綴 + 空白 + 旗標名」的
# 兩 token 形式出現（本機實測值：'~ RUNASADMIN'、'$ Win7RTM'）。移除旗標時
# 必須連帶移除它的前綴，否則會留下孤立的 '~' / '$'。
_PREFIX_TOKENS = {"~", "$"}

# 相對於安裝根目錄、屬於本程式的執行檔路徑（比對時轉小寫）
_REL_EXE_IN_CURRENT = "current\\ocr-trigger-clicker.exe"
_REL_STUB = "ocr trigger clicker.exe"
_REL_UPDATER = "update.exe"

# Velopack 安裝根目錄的結構特徵：'current' 放目前版本、'packages' 放 nupkg
_VELOPACK_ROOT_MARKERS = ("current", "packages")


# ── registry 存取（winreg 僅限 Windows；非 Windows 一律安全回退）──────────


def layer_value_names() -> list[str]:
    """列出 AppCompat Layers 底下所有值名稱（即被綁定的執行檔路徑）。"""
    try:
        import winreg
    except ImportError:  # pragma: no cover - 非 Windows
        return []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYERS_SUBKEY) as key:
            names = []
            index = 0
            while True:
                try:
                    name, _value, _type = winreg.EnumValue(key, index)
                except OSError:
                    break
                names.append(name)
                index += 1
            return names
    except OSError:
        return []


def read_layer(path: str) -> str | None:
    """讀取某執行檔的 Layers 值內容；沒有紀錄回 None。"""
    try:
        import winreg
    except ImportError:  # pragma: no cover - 非 Windows
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYERS_SUBKEY) as key:
            value, _type = winreg.QueryValueEx(key, path)
            return str(value)
    except OSError:
        return None


def write_layer(path: str, value: str | None) -> bool:
    """寫回 Layers 值；value=None 代表刪除整條。回傳是否成功。"""
    try:
        import winreg
    except ImportError:  # pragma: no cover - 非 Windows
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, LAYERS_SUBKEY) as key:
            if value is None:
                try:
                    winreg.DeleteValue(key, path)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, path, 0, winreg.REG_SZ, value)
        return True
    except OSError as e:
        log.warning("寫入相容性設定失敗（%s）：%s", path, e)
        return False


# ── 純邏輯 ────────────────────────────────────────────────────────────────


def _is_runasadmin(token: str) -> bool:
    """token 是否為 RUNASADMIN 旗標（允許 '~' / '$' 前綴黏在同一 token）。"""
    return token.lstrip("~$").upper() == RUNASADMIN


def strip_runasadmin(value: str) -> str | None:
    """從 Layers 值內容移除 RUNASADMIN（含其前綴 token）。

    Windows 的 Layers 值以空白分隔旗標，且前綴（'~' / '$'）是獨立 token：
    ``~ RUNASADMIN``、``$ RUNASADMIN``、``RUNASADMIN`` 三種寫法都會讓執行檔
    被提權，移除時必須連帶移除該旗標的前綴 token，否則會留下孤立的
    ``~`` / ``$``。

    其他旗標與其前綴原樣保留（不重新推斷前綴語意）。
    回傳新的值內容；若移除後沒有剩餘設定則回 None（代表應刪除整條）。
    """
    tokens = value.split()
    kept: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        # 「~ RUNASADMIN」／「$ RUNASADMIN」：前綴與旗標名以空白分隔，整組移除
        if token in _PREFIX_TOKENS and i + 1 < len(tokens) and _is_runasadmin(tokens[i + 1]):
            i += 2
            continue
        if _is_runasadmin(token):
            i += 1
            continue
        kept.append(token)
        i += 1
    if len(kept) == len(tokens):
        return value
    return " ".join(kept) if kept else None


# ── 路徑篩選 ──────────────────────────────────────────────────────────────


def _norm(path: str) -> str:
    """Windows 路徑正規化：展開 '..'、統一分隔符、忽略大小寫。"""
    return os.path.normcase(os.path.normpath(path))


def _rel_to_root(path: str, root: Path) -> str | None:
    """回傳 path 相對於 root 的正規化相對路徑；不在 root 之下回 None。

    '..' 逃逸（<root>\\..\\Other\\x.exe）與磁碟機不符都在此被擋掉。
    """
    try:
        rel = os.path.relpath(_norm(path), _norm(str(root)))
    except ValueError:
        return None  # 不同磁碟機／無效路徑
    if rel in (os.curdir, os.pardir) or rel.startswith(os.pardir + os.sep):
        return None
    return rel


def is_velopack_root(root: Path) -> bool:
    """是否為 Velopack 安裝根目錄：同時具備 'current' 與 'packages' 子目錄。"""
    return all((root / marker).is_dir() for marker in _VELOPACK_ROOT_MARKERS)


def install_root() -> Path | None:
    """推斷安裝根目錄；非打包版回 None。

    - Velopack onedir：<root>/current/ocr-trigger-clicker.exe → <root>；
      但只有 <root> 確實具備 Velopack 結構特徵（current + packages）時才回推，
      避免 portable 版放在名為 'current' 的資料夾時把清理範圍擴大到上一層。
    - 其餘情形（portable／任意資料夾）：執行檔所在資料夾。
    """
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable)
    parent = exe.parent
    if parent.name.lower() == "current":
        candidate = parent.parent
        if is_velopack_root(candidate):
            return candidate
    return parent


def allowed_rel_paths(root: Path, own_exe_rel: str | None) -> set[str]:
    """允許處理的執行檔（相對於安裝根目錄，小寫）。

    - 自身執行檔：永遠允許（就是 sys.executable 本身）。
    - ``current\\ocr-trigger-clicker.exe``：僅當根目錄確有 'current' 子目錄。
    - 捷徑啟動器與 ``Update.exe``：僅當根目錄確認為 Velopack 安裝根，
      否則寧可不處理（避免誤傷安裝目錄內其他軟體的同名程式）。
    """
    allowed: set[str] = set()
    if own_exe_rel:
        allowed.add(own_exe_rel.lower())
    if (root / "current").is_dir():
        allowed.add(_REL_EXE_IN_CURRENT)
    if is_velopack_root(root):
        allowed.add(_REL_STUB)
        allowed.add(_REL_UPDATER)
    return allowed


def candidate_paths(
    root: Path | None = None,
    names: list[str] | None = None,
    exe: str | None = None,
) -> list[str]:
    """列出可能帶有 RUNASADMIN 層級的自身執行檔路徑。

    只接受「相對於安裝根目錄、屬於本程式執行檔」的路徑（見
    ``allowed_rel_paths``），不以檔名單獨判斷，避免誤刪安裝目錄內其他
    程式的相容性設定。names／exe 可注入以便測試。
    """
    root = root if root is not None else install_root()
    if root is None:
        return []
    if names is None:
        names = layer_value_names()
    exe_path = exe
    if exe_path is None and getattr(sys, "frozen", False):
        exe_path = sys.executable
    own_rel = _rel_to_root(exe_path, root) if exe_path else None
    allowed = allowed_rel_paths(root, own_rel)
    out: list[str] = []
    for name in names:
        rel = _rel_to_root(name, root)
        if rel is None or rel.lower() not in allowed:
            continue
        out.append(name)
    return out


def clear_runasadmin(
    paths: list[str] | None = None,
    *,
    read=None,
    write=None,
) -> list[str]:
    """移除指定路徑上的 RUNASADMIN 層級；回傳實際修正的路徑。

    read / write 可注入（測試用），預設走 registry。
    """
    read = read or read_layer
    write = write or write_layer
    if paths is None:
        paths = candidate_paths()
    fixed: list[str] = []
    for path in paths:
        try:
            value = read(path)
        except Exception as e:  # pragma: no cover - 防禦性
            log.info("讀取相容性設定失敗（%s）：%s", path, e)
            continue
        if not value:
            continue
        new_value = strip_runasadmin(value)
        if new_value == value:
            continue
        if write(path, new_value):
            fixed.append(path)
            log.warning(
                "已移除 %s 的「以系統管理員身分執行」相容性設定（否則更新安裝會失敗）", path
            )
    return fixed


def heal(root: Path | None = None) -> list[str]:
    """自癒入口：移除自身執行檔上的 RUNASADMIN 層級；回傳修正清單。

    root 可指定安裝根目錄（測試用）；None = 由自身執行檔推斷。
    """
    try:
        paths = candidate_paths(root)
    except Exception as e:  # pragma: no cover - 防禦性
        log.info("相容性設定檢查略過：%s", e)
        return []
    if not paths:
        return []
    fixed = clear_runasadmin(paths)
    if fixed:
        log.warning(
            "已移除 %d 個執行檔的「以系統管理員身分執行」相容性設定（否則更新安裝會失敗）",
            len(fixed),
        )
    return fixed


def demo():
    # 自檢：token 解析 + 假 registry 流程（不碰真 registry）
    assert strip_runasadmin("~ RUNASADMIN") is None
    assert strip_runasadmin("RUNASADMIN") is None
    assert strip_runasadmin("$ RUNASADMIN") is None
    assert strip_runasadmin("~ runasadmin") is None
    assert strip_runasadmin("~ RUNASADMIN WINXPSP3") == "WINXPSP3"
    assert strip_runasadmin("RUNASADMIN WINXPSP3") == "WINXPSP3"
    assert strip_runasadmin("$ WIN7RTM") == "$ WIN7RTM"
    assert strip_runasadmin("WINXPSP3") == "WINXPSP3"
    assert strip_runasadmin("~ WINXPSP3") == "~ WINXPSP3"
    assert strip_runasadmin("") == ""

    # 真的建一個假 Velopack 安裝根（is_velopack_root 需要目錄結構佐證）
    import shutil
    import tempfile

    base = Path(tempfile.mkdtemp(prefix="otc_appcompat_"))
    try:
        root = base / "OCRTriggerClicker"
        (root / "current").mkdir(parents=True)
        (root / "packages").mkdir()
        own = root / "current" / "ocr-trigger-clicker.exe"
        stub = root / "OCR Trigger Clicker.exe"
        foreign_update = root / "current" / "update.exe"

        fake = {
            str(own): "~ RUNASADMIN",
            str(stub): "RUNASADMIN WINXPSP3",
            str(foreign_update): "~ RUNASADMIN",
        }

        def _read(path):
            return fake.get(path)

        def _write(path, value):
            if value is None:
                fake.pop(path, None)
            else:
                fake[path] = value
            return True

        paths = candidate_paths(root, names=list(fake), exe=str(own))
        assert paths == [str(own), str(stub)], paths

        fixed = clear_runasadmin(paths, read=_read, write=_write)
        assert fixed == [str(own), str(stub)], fixed
        assert str(own) not in fake
        assert fake[str(stub)] == "WINXPSP3"
        # 安裝目錄內的外來 update.exe 必須原封不動
        assert fake[str(foreign_update)] == "~ RUNASADMIN"
        # 已清乾淨後再跑一次 → 沒有變更
        assert clear_runasadmin(paths, read=_read, write=_write) == []
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("✓ appcompat self-check passed")


if __name__ == "__main__":
    demo()
