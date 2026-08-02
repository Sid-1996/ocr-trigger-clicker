

## [Unreleased]

### 新增
- `click` 步驟新增 **目前游標位置** 目標（`target: cursor`）：不需設定座標，直接點擊
  - 前景模式點擊目前滑鼠游標位置（動作遊戲左鍵普攻適用）
  - 後台模式（PostMessage）點擊目標視窗正中心
  - 新增 `hold_ms` 按住毫秒（0=立即點擊），與 `key` 步驟的按住行為一致
- match_image 模板標記**來源互動模式**（`template_source`：foreground/background），並持久化於任務 JSON，匯入匯出自動攜帶
  - 建立模板（截取區域 / OCR 診斷建模板）時自動記錄目前模式；舊任務無此欄位一律視為**前景**（此版本前無後台模式）
  - **圖片比對 / 測試按鈕**：模板來源與目前互動模式不符時，**靜默**在結果／測試日誌顯示橘色警告（測試為模擬預覽，不彈窗）
  - **啟動任務前防呆**（唯一彈窗）：掃描所選群組內所有 match_image 步驟，發現模式不符時警告（告知目前模式、逐條列出不符模板），可選擇「仍要執行」或「取消」
- `_pick_template`（從檔案挑圖）來源標記為未知（視為前景）
- **後台截圖全黑偵測**：部分遊戲（如鳴潮）在非系統管理員權限下 PrintWindow 回傳全黑畫面
  - `core/15_print_window.py` 新增 `is_admin()` / `is_black_capture()`（全像素為零才命中，暗色遊戲不誤判）
  - **OCR 診斷 / 測試 / 圖片比對按鈕**：後台截圖全黑 + 非系統管理員 → 靜默在資訊列／結果／日誌顯示提醒
  - **啟動任務前**：後台模式先截測試幀，全黑 + 非系統管理員 → 彈窗提醒以系統管理員重啟（可仍要執行/取消）

### 修復
- 後台模式（PostMessage）啟動後，click/key/scroll/drag 不再被「工具處於前景」保護誤擋（`_is_tool_foreground` 對後台模式直接回傳 False，前景模式行為不變）


## [v0.1.9] - 2026-08-01

### 新增
- **後台操控功能**：新增兩種互動方法（前景 pynput / 後台 PostMessage），用戶可在偏好設定中選擇
- `core/16_bg_input.py` — 後台互動模組，支援 PostMessage、pynput 兩種方法
- `core/01_screenshot.py` 新增 `activate_window_bg()` — 用 WM_ACTIVATE 喚醒視窗（不偷焦點）
- 偏好設定新增「互動方法」下拉選單，支援切換前景/後台模式
- 狀態列顯示當前互動方法（前景/後台 PM）
- 主循環根據互動方法自動選擇對應的點擊/按鍵/喚醒邏輯
- **GUI 全面後台化**：選擇後台模式時，所有 GUI 操作在後台完成，不切換視窗
  - `gui/17_bg_roi_selector.py` — 後台偵測區域選取器（PrintWindow 截圖 + QLabel）
  - `gui/18_bg_click_picker.py` — 後台座標選取器（PrintWindow 截圖 + QLabel）
  - 截圖/測試/點擊/框選/座標選取均已支援後台模式

### 技術說明
- 後台模式透過 PrintWindow 截圖 + PostMessage 點擊實現
- Unity 遊戲不支援 PostMessage，需使用前景模式
- 其他遊戲可嘗試後台模式，用戶需自行測試
- 預設值 = `foreground`，不改變現有行為
- 後台模式下 ROI/座標選取改用 GUI 內嵌截圖，不使用全螢幕 overlay
- 後台模式完整支援：截圖、測試、點擊、拖曳、滾動、按鍵（含 hold）、框選、座標選取

### 修復
- 修復 `_activate_window()` 前景模式無限遞迴 bug
- 修復測試按鈕在後台模式下仍切換視窗問題（test_run_controller、09_ocr_debug、06_gui_main）
- 修復 `_send_scroll()` 未支援後台模式
- 修復 `_handle_key(hold_ms)` 繞過後台輸入問題
- 修復 `_handle_drag()` 未支援後台模式
- 修復 OCR 診斷 `RuleConfigController(None)` crash

## [v0.1.8] - 2026-07-31

### 新增
- 規則列表新增**一鍵啟動/取消**按鈕，批量切換所有群組啟用狀態（i18n zh_TW/zh_CN/en）
- 偵測/比較步驟全圖 OCR 時發出**效能警告**，執行日誌面板顯示實際耗時，建議框選 ROI 提升速度
- 測試按鈕失敗時顯示**實際相似度**，幫助使用者理解匹配差距（OCR fuzzy 顯示相似度 %，模板比對顯示最高 %）

### 修復
- 切換任務後群組收起狀態正確保留，不再自動展開第一個群組
- 群組展開/收起時的視覺殘影消除，UI 過渡更流暢
- `_DetectStepForm` 補上遺漏的 `self._list` 賦值，修復框選偵測區域時 crash
- 迴圈停止時執行日誌最終 flush，解決成功步驟不顯示的問題
- 管理員權限從預設改為僅除錯建議
- 三處 slice 入口補 `int()` 防禦，排除 float ROI 繞過轉換造成切片 crash
- OCR 診斷頁面耗時 ms 取整數
- 全圖 OCR `max_side_len` 從 480 改為 720，提高偵測精度；還原 ROI 分支 `max_side_len=0`
- `.gitignore` 放行 `docs/tasks/` 讓任務 JSON 可被網站下載
- `app.log` backupCount 7→1，`startup_error.log` 改覆蓋模式

### 文件
- 全新視覺設計 index.html — 漸層 Hero、Sticky Nav、Card Grid、FAQ Accordion
- 優化三個語言版本 README 視覺排版
- 開發者文件移入 `docs/dev/`，新增快速上手指南 START.md
- 記錄 max_side_len 精度陷阱到 TECHNICAL.md
- 清除 README 與網站中 AHK/AutoHotkey 殘留提及
- 修復 CHANGELOG.md 舊版本中文亂碼
- 刪除已完成的 PLAN_optimizations.md 與 UI_OPTIMIZATION_PLAN.md

## [v0.1.7] - 2026-07-29

### 變更
- 輸入模擬從 AutoHotkey v2（TCP socket + 外部行程）完全替換為 **pynput**（`SendInput`，in-process），刪除 `core/03_ahk_socket.py`、`clicker.ahk`、AHK 下載與初始化流程
- 截圖備援鏈從「mss → GDI」強化為「**mss → dxcam (DXGI) → GDI**」，dxcam 作為 mss 與 GDI 間的中間層，相容性更高
- 移除 8 組 AHK 相關 i18n key（三語言同步），i18n 總 keys 減至 611

### 新增
- `core/03_pynput_input.py` — pynput 輸入模組（10 個公開函式 + 8 項自檢測試）
- `core/box_utils.py` — 座標工具集，10 個純函式（`roi_center`、`roi_to_pixels`、`roi_crop`、`roi_sanitize` 等 + 17 項自檢測試）
- `core/01_screenshot.py` 新增 `_capture_dxcam()` + `--check` 自動自檢

### 移除
- `core/03_ahk_socket.py`（461 行 AHK TCP 伺服器）
- `clicker.ahk`（AHK 腳本）

### 修復
- 主視窗最大化後進行測試、框選區域、點擊選取、OCR 診斷等操作後不再還原為視窗模式，保留最大化狀態（7 處統一修復）

### 相依套件
- 新增 `pynput>=1.7`（取代 AutoHotkey）
- 新增 `dxcam>=0.3`（DXGI 截圖備援）

## [v0.1.6] - 2026-07-28

### 修復
- 語言切換 bug：`__main__` 語言讀取路徑改用與 `MainWindow._config_path` 一致的路徑邏輯（`_bundle_root()` / `_is_frozen()` / `get_data_path()`），避免 dev 模式與 frozen 模式讀到不同位置

### 變更
- 執行日誌摘要文字改進：`StepContext.on_fail_fired` 旗標、detail 顯示 `{fail_name}失敗，使用「{key}」`、前進→強制前進、空設定顯示明確訊息
- `_STEP_TYPE_NAMES` 靜態 dict 移除，統一用 i18n key 查表

### 新增
- 執行日誌全三語 i18n：core 層 `StepResult("stop", detail=...)` 33 條字串全部改用 `T()`，GUI `_RESULT_LABELS` 改為 `_RESULT_KEYS` 並在 `_populate` 執行期以 `T()` 解析，新增 44 組 i18n key（步驟類型、結果標籤、捲動方向、靜態與參數化細節）至 zh_TW/zh_CN/en

## [v0.1.5] - 2026-07-26

### 新增
- 任務分享按鈕改為 QMenu 下拉式（「開啟任務資料夾」+「前往網站」），加入 🌐 圖示
- 發現新版本時彈出更新資訊對話框，含 release notes + 自動更新／前往 Release 頁面按鈕
- 設定可自訂「等待」步驟的預設毫秒數 (default_wait_ms)
- 規則列表每條規則顯示總結標籤（步驟數、有失敗處理、有重試容忍、空白）
- 閒置時狀態列顯示真實 CPU／記憶體數據（背景 PerformanceMonitor 持續取樣）
- 模板比對（regex）模式提供「快速插入」輔助工具列：[數字][英文][任意][空白]
- 失敗處理、點擊目標、群組模式三組下拉選項全部加入 tooltip（懸停說明）
- `updater_main.py` 加入 `--demo` 自檢測試，無需發版即可驗證取代邏輯

### 變更
- 路徑邏輯集中至 `core/_paths.py`（`get_data_path` / `get_resource_path` / `_appdata_path`），取代 10+ 檔案中的內聯路徑
- `build.py` py_datas 改為 glob 自動掃描 `core/` 與 `gui/` 下所有 `*.py`，不再手動維護
- 任務目錄統一使用 `%APPDATA%\ocr-trigger-clicker\tasks\`，不再區分 dev/frozen 模式
- 比對模式命名調整：模糊比對（fuzzy）→ 近似比對；模板比對（regex）→ 模板比對；summary／combo 相關標籤同步更新
- 步驟摘要改進：內嵌→截圖、on_fail 顯示全稱、fuzzy 模式永遠顯示 `[近似比對]`、fail_duration 改為「持續N秒後」格式
- 規則列表總結標籤從 column 0 移至 column 1 靠右顯示，resize mode 改為 ResizeToContents

### 修復
- 自動更新機制全面重寫：暫存目錄改為 `%TEMP%`，取代改為逐檔複製 (copy2) + 每檔 retry 3 次 + 整包 retry 3 次 + rollback 強化
- 移除 `ocr-trigger-clicker_new` 目錄模式（不再在 app 目錄內解壓縮）
- 規則列表總結標籤在選取、啟用切換、儲存、更新狀態 4 個操作後被覆蓋消失
- 常駐監控 👁 符號在儲存規則後被覆蓋消失
- 持續失敗時長（fail_duration_sec）在步驟摘要中的格式易讀性
- OCR 診斷規則/步驟改用設定值取代寫死參數（bd6bffc）
- test 結果與步驟表單用語統一「內嵌」→「截圖」（44041a4）
- release.ps1 tag push 失敗時自動刪除 local tag rollback（87a86fe）

## [v0.1.1] - 2026-07-22

### ⚠️ 重要公告：打包格式變更

此版本從 `--onefile`（單一 exe）遷移至 `--onedir`（目錄結構），以消除運行時動態解壓縮帶來的穩定性問題，冷啟動速度從 6.81 秒降至 **1 秒內**。

### 🔴 強烈建議：本次請手動下載

由於本次為打包格式首次轉換，自動更新可能發生錯誤。**所有使用者（無論新舊版本）** 請至 [GitHub Releases](https://github.com/Sid-1996/ocr-trigger-clicker/releases/latest) 手動下載 `ocr-trigger-clicker.zip`。

使用方式：
1. 下載 `ocr-trigger-clicker.zip`
2. 解壓縮至任意目錄
3. 執行 `ocr-trigger-clicker.exe`

**舊版本可直接刪除**，不影響設定檔與規則（儲存於 `%APPDATA%\ocr-trigger-clicker\`）。

### 新增
- 自動更新支援 onedir 結構：`updater.exe --mode=update` 改為整包目錄取代，含備份 + rollback 還原機制
- `_UpdaterParser` MessageBox 防呆：直接雙擊 `updater.exe` 時跳出提示對話框
- `apply_update()` 對 onedir 路徑改為自動啟動新版 `updater.exe` 做目錄取代

### 變更
- 切換為 `--onedir` 打包模式，徹底消除運行時動態解壓縮帶來的穩定性問題
- 冷啟動速度從 6.81 秒大幅提升至 **1 秒內**
- 語言切換重啟改為外部 relauncher（`updater.exe --mode=relaunch`），解決 PyInstaller bootloader 競爭問題
- 移除 `updater_main.py` 中 onefile 時代的參數（`--old`、`--new`、`--pid`、`--log`）與重試邏輯
- 移除已棄用的 `--mode=migrate` 相關程式碼
- `gui/06_gui_main.py` relaunch 呼叫移除除錯用 `--log` 參數

### 技術細節
- `updater.exe` 維持 `--onefile` 打包，不依賴 `_internal/`，確保可獨立執行且原始 exe 不被鎖定
- 更新流程：下載 ZIP → 偵測 `_internal/` → 解壓到 sibling 目錄 → 啟動新版 `updater.exe` → 備份舊目錄 → rename 取代 → 啟動新版
- 失敗還原：取代失敗時自動將備份目錄 rename 回原位，防止程式遺失

## [v0.1.0] - 2026-07-19

### 新增
- 高 DPI 螢幕 overlay 座標修正：ROI 框選、點擊座標選取、截圖區域三個 overlay
  均乘以 `devicePixelRatioF()` 轉換為實體座標，解決高 DPI 下框選偏移問題
- 自動化測試框架：新增 `tests/` 目錄，87 項 pytest 測試涵蓋規則引擎、主迴圈、
  模板比對、任務管理、序列化、觸發紀錄
- 規則備註欄位（notes）：Rule 資料模型新增 `notes: str` 欄位，GUI 規則編輯器
  新增備註文字框，向後相容（舊任務檔自動填入空字串）
- 觸發歷史紀錄：每次規則觸發時寫入 `logs/triggers.jsonl`（JSONL 格式），
  記錄時間戳、規則 ID、規則名稱、任務名稱、群組 ID
- 觸發紀錄 rotation：`triggers.jsonl` 超過 1MB 自動輪替（保留 3 份）
- 啟動時自動清理版本更新殘留死檔（`debug.log`、`run_stderr.log`）

### 修正
- 捕捉區域 overlay 1:1 模式下顯示文字改為物理像素尺寸（乘以 `devicePixelRatioF`）
- 日誌系統優化：root logger 從 DEBUG 提升至 INFO，消除模板不匹配噪音
  （每日 log 量從 ~50,000 行降至 ~3,000 行）
- `_ensure_root_handler()` 加 `threading.Lock` 雙重檢查鎖，修復並發競爭
- `rule_serialization` load/save 日誌從 INFO 降為 DEBUG，移除完整 rule list dump
- 主迴圈 rate-limit / 前景略過日誌從 INFO 降為 DEBUG，減少每幀重複輸出
- 主迴圈 `_log()` 移除 `print()` stdout 輸出，改為純 logging
- `startup_error.log` 從覆寫模式改為追加模式
- 刪除 `debug.log`、`run_stderr.log` 等孤立死檔

### 移除
- 移除「簡易/進階」切換按鈕：進階欄位（ROI、on_fail、滑鼠按鈕等）永遠可見，
  簡化 UI 結構，減少使用者困惑

### 重構
- README SEO 優化：擴充適用場景（10 個情境）、新增工具比較表、
  新增英文與簡體中文關鍵詞段落

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

[v0.1.2]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.1.2
[v0.1.1]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.1.1
[v0.1.0]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.1.0
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
