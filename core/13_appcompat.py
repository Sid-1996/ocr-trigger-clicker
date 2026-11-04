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
只刪「本程式安裝目錄下、檔名屬本程式執行檔」的層級，且只移除 RUNASADMIN
token，同一條目裡的其他相容性設定原樣保留。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

LAYERS_SUBKEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
RUNASADMIN = "RUNASADMIN"

# 本程式相關的執行檔名（Velopack onedir：current\\ocr-trigger-clicker.exe、
# 捷徑啟動器「OCR Trigger Clicker.exe」、更新器 Update.exe）
_APP_EXE_NAMES = {
    "ocr-trigger-clicker.exe",
    "ocr trigger clicker.exe",
    "update.exe",
}


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


def strip_runasadmin(value: str) -> str | None:
    """從 Layers 值內容移除 RUNASADMIN token。

    Windows 的 Layers 值以空白分隔旗標，且「~」是獨立 token：
    ``~ RUNASADMIN``（= 無提示直接提權）與 ``RUNASADMIN`` 都會讓執行檔被提權，
    兩種寫法都要能移除。

    回傳新的值內容；若移除後沒有剩餘設定則回 None（代表應刪除整條）。
    其他 token（如 WINXPSP3）原樣保留。
    """
    tokens = value.split()
    kept: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        # 「~ RUNASADMIN」：~ 與旗標名以空白分隔，需整組移除
        if token == "~" and i + 1 < len(tokens):
            if tokens[i + 1].lstrip("~").upper() == RUNASADMIN:
                i += 2
                continue
        if token.lstrip("~").upper() == RUNASADMIN:
            i += 1
            continue
        kept.append(token)
        i += 1
    if len(kept) == len(tokens):
        return value
    return " ".join(kept) if kept else None


# ── 路徑篩選 ──────────────────────────────────────────────────────────────


def install_root() -> Path | None:
    """推斷安裝根目錄（Velopack onedir：<root>/current/<exe>）；非打包版回 None。"""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable)
    parent = exe.parent
    if parent.name.lower() == "current":
        return parent.parent
    return parent


def candidate_paths(root: Path | None = None, names: list[str] | None = None) -> list[str]:
    """列出可能帶有 RUNASADMIN 層級的自身執行檔路徑。

    只挑「安裝根目錄底下、檔名屬於本程式執行檔」的項目，避免動到使用者的
    其他程式（例如開發模式的 python.exe）。names 可注入以便測試。
    """
    root = root if root is not None else install_root()
    if root is None:
        return []
    if names is None:
        names = layer_value_names()
    prefix = os.path.normcase(str(root)).rstrip("\\/") + os.sep
    out: list[str] = []
    for name in names:
        norm = os.path.normcase(name)
        if not norm.startswith(prefix):
            continue
        if os.path.basename(name).lower() not in _APP_EXE_NAMES:
            continue
        out.append(name)
    exe = sys.executable
    if getattr(sys, "frozen", False) and os.path.normcase(exe).startswith(prefix):
        if exe not in out:
            out.append(exe)
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
    assert strip_runasadmin("~ runasadmin") is None
    assert strip_runasadmin("~ RUNASADMIN WINXPSP3") == "WINXPSP3"
    assert strip_runasadmin("WINXPSP3 RUNASADMIN") == "WINXPSP3"
    assert strip_runasadmin("WINXPSP3") == "WINXPSP3"
    assert strip_runasadmin("~ WINXPSP3") == "~ WINXPSP3"
    assert strip_runasadmin("") == ""

    fake = {
        r"C:\app\current\ocr-trigger-clicker.exe": "~ RUNASADMIN",
        r"C:\app\current\other.exe": "RUNASADMIN",
        r"C:\app\OCR Trigger Clicker.exe": "RUNASADMIN WINXPSP3",
        r"C:\other\python.exe": "RUNASADMIN",
    }

    def _read(path):
        return fake.get(path)

    def _write(path, value):
        if value is None:
            fake.pop(path, None)
        else:
            fake[path] = value
        return True

    paths = candidate_paths(Path(r"C:\app"), names=list(fake))
    assert paths == [
        r"C:\app\current\ocr-trigger-clicker.exe",
        r"C:\app\OCR Trigger Clicker.exe",
    ], paths

    fixed = clear_runasadmin(paths, read=_read, write=_write)
    assert fixed == [
        r"C:\app\current\ocr-trigger-clicker.exe",
        r"C:\app\OCR Trigger Clicker.exe",
    ], fixed
    assert r"C:\app\current\ocr-trigger-clicker.exe" not in fake
    assert fake[r"C:\app\OCR Trigger Clicker.exe"] == "WINXPSP3"
    # 非本程式的路徑不動
    assert fake[r"C:\other\python.exe"] == "RUNASADMIN"
    # 已清乾淨後再跑一次 → 沒有變更
    assert clear_runasadmin(paths, read=_read, write=_write) == []

    print("✓ appcompat self-check passed")


if __name__ == "__main__":
    demo()
