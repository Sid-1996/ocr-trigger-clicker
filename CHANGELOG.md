# Changelog

## [v0.0.14] - 2026-07-15

### 新增
- 新增 `scroll`（滑鼠滾輪）與 `drag`（滑鼠拖曳）步驟類型，支援正規表達式比對
- OCR 診斷面板新增「建立為模板」按鈕：選取辨識結果後一鍵截圖裁切為模板，
  建立 match_image + click + wait 規則（模板用 OCR 精確邊框，ROI 維持 pad=20 搜尋範圍）
- OCR 診斷面板新增「加入模板步驟」按鈕：將辨識區塊截圖追加為現有規則的 match_image 步驟
- 步驟卡片顏色區分：10 種步驟類型各配對應顏色（`_STEP_COLORS`）
- 規則圓點顯示 5 種狀態：停用（灰）、就緒（綠）、運行中（藍）、失敗（紅）、已完成（深藍）
- 狀態欄常駐 AHK 🟢/🔴 連接指示器
- 步驟參數即時校驗：detect 文字、notify 訊息、compare 步驟紅色邊框提示
- 步驟列表支援 Del 快捷鍵刪除選中步驟

### 修正
- 步驟列表 Del 快捷鍵改用 `WidgetShortcut` context，避免攔截規則列表的 Del 刪除功能
- OCR 診斷面板模板截圖色彩空間：`_latest_raw` 為 RGB，裁切後轉 BGR 再編碼，
  避免 match_template 執行時 R↔B 互換導致比對失敗
- `_step_summary` 補充 `template_center` 摘要顯示（後改用統一 `text_center`）

### 重構
- OCR 診斷面板提取 `_compute_roi()` 輔助方法，`_on_add_rule`、`_on_set_sub_target`、
  `_on_add_template`、`_on_add_template_step` 四處共用 ROI 計算邏輯
- 移除多餘的 `template_center` click target，match_image 規則統一用 `text_center`，
  runtime 已透過 `ctx.matched_text` 介面兼容 detect 與 match_image

## [v0.0.13] - 2026-07-15

### 移除
- 移除 `condition_list` 步驟類型（條件清單），其功能已由 `detect` + `click`/`key`/`jump` 步驟組合完全取代
- 移除相關 GUI 元件（`_CondCardWidget`、`_ConditionListStepForm`）、引擎 handler（`_handle_condition_list`）、
  資料模型（`Condition`、`ConditionListParams`）、遷移函式（`_migrate_condition_list_to_step`）
- 清理 tasks JSON 中的 legacy null 欄位（`use_condition_list`、`condition_list`、`condition_list_advance_on_no_match`）
- 無任何實際任務使用此步驟，移除不影響現有功能

## [v0.0.12] - 2026-07-15

### 重構
- 條件清單與 Step 系統合併：將獨立的「條件清單」模式併入 Step 系統，
  新增 `condition_list` Step 類型，消除雙軌架構
- 舊格式任務檔（`use_condition_list` + `condition_list`）自動遷移為
  新的 `condition_list` Step，無需手動轉換
- GUI 移除「條件清單」勾選框，改為在步驟下拉選單中新增
- 執行引擎從兩套獨立路徑（`_run_condition_list` / `_execute_steps`）
  統一為單一 `_run_step` 分派，`condition_list` 由 `_handle_condition_list` 處理
- 條件清單驗證從阻塞彈窗（QMessageBox）改為狀態列非阻塞警告
- 新增條件後自動捲動至新卡片可見區域

### 新增
- 首次啟動自動建立預設任務「我的任務」
- 新手教學改為狀態列輕量提示（toast），不再阻塞啟動
- AHK 未安裝時改為狀態列點擊安裝，不再彈窗
- 版本檢查改為狀態列點擊更新，不再彈窗
- 步驟初始化使用 `_STEP_DEFAULTS` 預設值，新增等待/條件清單等步驟不再空白

## [v0.0.11] - 2026-07-11

### 新增
- on_fail 新增動作「跳過此規則（換下一條）」（action: advance）：
  搭配 fail_duration_sec，連續偵測失敗滿 N 秒後跳過該規則、
  推進到同群組下一條規則（而非原地持續重試），群組重新輪到此規則時
  會重新獲得完整容忍期

### 修正
- _normalize_on_fail 缺少 "advance" action 分支，導致規則重新載入時
  該設定被靜默降級為 "stop"、fail_duration_sec 遺失（存檔後表現異常）

### 重構
- 移除三份分散在不同檔案的重複 _tasks_dir() wrapper，
  統一直接呼叫 get_tasks_dir()

## [v0.0.10] - 2026-07-10

### 重構
- MainWindow 拆分：抽出 GroupSettingsController、ScreenshotController、
  RuleConfigController、TestRunController，MainWindow 從 3260 行降至約一半
- rule_engine 拆分：core/04_rule_engine.py 從 1439 行拆為
  rule_models.py / rule_migration.py / rule_serialization.py /
  task_management.py / run_config.py / file_utils.py，從 1439 行降至約 530 行
- 純內部重構，無使用者可見功能變更，所有拆分皆經過手動功能驗證

## [v0.0.9] - 2026-07-10

### 新增
- 啟動加速：UI 優先顯示，OCR 引擎與 AHK 初始化改為背景 deferred init
- 啟動 3 秒後自動檢查更新（遵循 `skip_update_check` 設定）
- 主頁增加「日誌」按鈕，點擊開啟日誌目錄

### 修正
- 規則拖曳到另一規則上時 UI 項目消失（Qt InternalMove 幽靈清除）
- 樹狀拖曳多重修正：阻擋 rule 成為 child、自動改為 sibling、支援背景規則群組
- `_init_ahk_async` QThread GC 導致閃退
- `_match_image_warn_counter` 無界字典隨規則重載清除
- 關鍵錯誤路徑從 `print()` 遷移至 `logging`，補上遺失的 traceback

### 改善
- 統一日誌至單一 `app.log`，移除 `main.log` / `debug.log` 分散寫入
- 清理過時 docstring 及舊路徑 `update_debug.log` 殘留
- 降低主循環常規 log 等級（info → debug）

### 移除
- 全面移除「觸發紀錄」與「比較輪次日誌」UI 面板及底層資料通道
- 移除 `_rules_dirty` 及相關週期存檔 dead code

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

[v0.0.14]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.14
[v0.0.13]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.13
[v0.0.12]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.12
[v0.0.11]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.11
[v0.0.10]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.10
[v0.0.9]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.9
[v0.0.8]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.8
[v0.0.7]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.7
[v0.0.6]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.6
[v0.0.5]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.5
[v0.0.4]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.4
[v0.0.3]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.3
[v0.0.2]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.2
[v0.0.1]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.1
[v0.0.0]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.0
