# -*- coding: utf-8 -*-
"""自動更新（Velopack）：檢查／下載／套用皆由框架處理，此模組僅薄封裝。

feed 倉庫位址由 build.py 依 --feed 烘入 _update_feed.py（測試庫／正式庫切換）；
開發模式（未經 Velopack 安裝）下所有更新 API 安全地回報無更新。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:  # 打包時由 build.py 產生在 bundle 根目錄；開發模式不存在 → 正式庫
    from _update_feed import FEED_REPO_URL  # type: ignore[attr-defined]
except ImportError:
    FEED_REPO_URL = "https://github.com/Sid-1996/ocr-trigger-clicker"

log = logging.getLogger(__name__)


@dataclass
class UpdateInfo:
    """GUI 顯示用的新版資訊（刻意與 velopack.UpdateInfo 解耦）。"""

    version: str
    release_url: str = ""
    release_notes: str = ""


def clean_stale_temp_dirs():
    """清掃舊版自製更新器遺留的 %TEMP%\\ocr_update_* 殘骸。"""
    for d in Path(tempfile.gettempdir()).glob("ocr_update_*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)


def check_for_update(_current_version: str) -> UpdateInfo | None:
    """查詢 feed 是否有新版；開發模式或無網路時回 None，不拋例外。

    版本比較交給 Velopack（以其安裝 manifest 為準），參數僅保留相容舊呼叫端。
    """
    try:
        from velopack import GithubSource, UpdateManager

        um = UpdateManager(GithubSource(FEED_REPO_URL))
        info = um.check_for_updates()
    except Exception as e:
        log.info("更新檢查不可用：%s", e)
        return None
    if info is None:
        return None
    target = info.TargetFullRelease
    log.info("發現新版 v%s", target.Version)
    return UpdateInfo(
        version=str(target.Version),
        release_url=f"{FEED_REPO_URL}/releases/tag/v{target.Version}",
        release_notes=target.NotesMarkdown or "",
    )


def download_and_apply(_info: UpdateInfo, progress_cb=None) -> None:
    """下載並排程套用更新（框架會等本程序退出後換目錄並重啟）。

    呼叫端在此函式返回後應盡快退出，讓 Update.exe 接手。
    progress_cb(value) 原樣轉發框架回報的進度值，UI 端自行容錯。
    """
    from velopack import GithubSource, UpdateManager

    um = UpdateManager(GithubSource(FEED_REPO_URL))
    pending = um.get_update_pending_restart()
    if pending is not None:
        # 已下載完成待重啟套用（例如上次下載後程序被中斷）：直接套用，不再下載
        um.apply_updates_and_restart(pending)
        return
    ui = um.check_for_updates()
    if ui is None:
        raise RuntimeError("找不到可套用的更新")
    if progress_cb is not None:
        um.download_updates(ui, progress_callback=progress_cb)
    else:
        um.download_updates(ui)
    um.apply_updates_and_restart(ui)


def demo():
    # 薄封裝自檢：匯入完整、TEMP 清掃可執行、開發模式下檢查安全回 None
    assert FEED_REPO_URL.startswith("https://github.com/")
    clean_stale_temp_dirs()
    result = check_for_update("0.0.1")
    assert result is None or result.version
    print("✓ velopack client self-check passed")


if __name__ == "__main__":
    demo()
