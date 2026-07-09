# Changelog

## [v0.0.9] - 2026-07-09

### 改善
- 大幅提升啟動速度：非關鍵初始化（視窗列表、任務載入、AHK 啟動）延遲至 UI 顯示後背景執行
- `_load_config()` 加入快取，避免啟動時重複讀取設定檔
- AHK 初始化移至背景執行緒，不再凍結 GUI（原可能阻塞 10 秒）

## [v0.0.8] - 2026-07-09

### 新增
- 自動更新系統正式實裝：獨立 `updater.exe`，以 `WaitForSingleObject` 精準等待母進程結束後取代檔案
- `build.py` 打包主程式後自動產生 `updater.exe`
- `release.ps1` ZIP 同時包含 `ocr-trigger-clicker.exe` 與 `updater.exe`

### 修正
- 更新後暫存目錄殘留：updater 清理改為逐檔刪除，略過自身 exe（Windows 不能刪正在執行的檔案）
- `Process.wait()` timeout 改為 `WaitForSingleObject`，解決等待母進程退出不可靠問題

### 改善
- 移除了臨時診斷腳本（IsProcessInJob／輪詢測試等）
- 重整專案結構：刪除過時計畫文檔、舊壓力測試、殘留資料
- 補上 GitHub Pages（`docs/`）與更新架構文件說明

## [v0.0.7] - 2026-07-09

### 改善
- 自動更新改用獨立 `updater.exe`（`WaitForSingleObject` 精準等待母進程結束）
- `build.py` 打包主程式後自動產生 `updater.exe`
- `release.ps1` ZIP 同時包含 `ocr-trigger-clicker.exe` 與 `updater.exe`
- 移除舊批次腳本、Job Object 診斷等暫時性程式碼

## [v0.0.6] - 2026-07-08

### 改善
- 版本號更新（測試自動更新流程）

## [v0.0.5] - 2026-07-08

### 新增
- 自動更新功能（版本檢查、下載、zip 解壓、自我取代、重啟）
- 設定頁「啟動時檢查更新」開關（Settings 分頁）

### 修正
- 啟動時背景檢查更新不再彈阻塞對話框

### 改善
- 版本檢查改用 raw GitHub latest_version.txt 取代 GitHub API（避免 rate limit）

## [v0.0.4] - 2026-07-03

### 新增
- notify 步驟類型（提示訊息）
- match_image 比對顏色選項（match_color）

### 修正
- fail_duration_sec 容忍期誤觸發（commit 4cb403c）
- _NotificationStack 訊息覆蓋、任務匯入白名單、圖片比對按鈕即時值、
  dry_run 缺 match_color、CompareStepForm 缺 fail_duration_sec/roi_coord

### 改善
- 群組預設模式 loop→once、color_tolerance 40→100、移除 debug print

## [v0.0.3] - 2026-06-30

### 新增
- match_image 圖示模板比對、on_fail 異常流程控制、fail_duration_sec、壓力測試套件

### 修正
- EXE 啟動 crash、_recv_line 通訊協定偏移、測試比對按鈕視窗遮擋、
  .gitignore images/ 路徑過寬

## [v0.0.2] - 2026-06-23

### 新增
- 統一步驟系統、比對模式三選一（contains/exact/fuzzy）、觸發模式（once/repeat）

### 修正
- 規則引擎健壯性（跳轉循環偵測、runaway 恢復）、多項 bug（詳見 GH release）

### 移除
- 全面移除熱鍵（F8/F9/F10/F12）

## [v0.0.1] - 2026-06-19

### 新增
- 截圖點擊放大功能（lightbox，commit b1dd4e4）
- 打包圖示與 GUI/OCR 截圖（commit 6634f3f）

### 修正
- OCR 失敗計數重置（commit d48718c）

### 改善
- SEO 全面優化 — 結構化資料、meta、FAQ（commit de6e2ad）
- 介紹頁改為暗色主題（commit 44111b0）
- 新手教學導流與首次啟動提示（commit fc2707a、3ab8ed2）

### 工具
- 新增 release.ps1 自動化發版腳本（commit d761df6）
- AGENTS.md 補上版本管理與發版流程（commit c3015f7）

## [v0.0.0] - 2026-06-18

首次公開發行：OCR 文字辨識觸發規則、繁中自訂模型、視窗框選、AHK 自動安裝、多任務管理

[v0.0.7]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.7
[v0.0.6]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.6
[v0.0.5]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.5
[v0.0.4]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.4
[v0.0.3]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.3
[v0.0.2]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.2
[v0.0.1]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.1
[v0.0.0]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.0
