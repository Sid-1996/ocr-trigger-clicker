# UX Phase 3 全流程易用性盤點（READ-ONLY Audit）

> 調查日期：2026-11-10（以 HEAD 實際程式碼為準，非沿用舊報告）
> 本文件僅為調查與規劃，未修改任何正式應用程式碼。

---

## 1. 調查基準

| 項目 | 實測值 |
|---|---|
| Branch | `master` |
| HEAD | `eda31c4` — `fix: 校正 normalGeometry frame 偏移避免還原位置逐輪下移` |
| `origin/master` | `eda31c4`（ahead/behind **0/0**，調查當下 `git fetch` 後核實） |
| 工作區 | `git status --porcelain=v1` 為空（staged / unstaged / untracked 皆無；調查開始前已乾淨） |
| 版本 | `v0.4.9`（`_version.py:4`、`pyproject.toml:3`；注意此為工作區版本號，未代表已發布） |
| 技術環境 | Windows 11；PowerShell 7（`pwsh`）；Python ≥3.13,<3.14；`uv` 管理依賴；PyQt6 6.11；RapidOCR ONNX；Velopack 1.2.0（`pyproject.toml:1-21`） |
| CodeGraph | `.codegraph/` 已建索引；本調查以 `codegraph_explore` + 內建 Grep/Read 為主，subagent 三路並行追蹤後由主線複核關鍵證據 |

### 實際主視窗與相關模組（HEAD 現況）

| 領域 | 模組 |
|---|---|
| 主視窗、規則編輯、步驟表單 | `gui/06_gui_main.py`（全域約 9,500 行：`_DetectStepForm:2093`、`_ClickStepForm:3624`、`_DragStepForm:3780`、`_VerifyWidget:2722` 等 11 種 Step 表單由 `_build_form:1191` 分派） |
| 規則樹 | `gui/rule_tree_widget.py`（拖曳排序 `dropEvent:8`） |
| 群組設定／群組選擇 | `gui/group_settings_controller.py`、`gui/group_selection_controller.py` |
| 測試（dry-run） | `gui/run_controller.py`（`on_test_rule:85`、`_run_dry_run:174`） |
| OCR Debug | `gui/09_ocr_debug.py`（建立規則／步驟四訊號 `473-476`） |
| 執行日誌 | `gui/execution_log_widget.py`、`core/05_main_loop.py::_log_exec:579` |
| 檔案日誌 | `gui/12_log_viewer.py`、`core/00_logging_config.py`（`%APPDATA%/ocr-trigger-clicker/logs/app.log`） |
| 通知 | `gui/notification_stack.py`（右下堆疊，自動 2 秒消失） |
| 執行引擎 | `core/05_main_loop.py`（`_run_step:2084`、`_run_rule:2118`、`start:3227`、`stop:3249`） |
| 資料模型 | `core/rule_models.py`（`Rule/RuleGroup/Step` 純 dataclass，無驗證） |
| 預檢 | `core/rule_preflight.py::rule_preflight:89`（純邏輯，不碰 ctx/HWND/OCR） |
| 遷移／驗證 | `core/rule_migration.py`（`_STEP_DEFAULTS:5`、`_normalize_step_params:475`、`_normalize_on_fail:341`、`validate_drag_endpoint:197`、`_detect_drag_legacy_marker:121`） |
| 任務管理 | `core/task_management.py`（匯入預覽 `preview_import_task:228`、匯出 `export_task:194`） |
| 設定 | `core/config_store.py`、`core/run_config.py`（互動方法雙寫 `gui/06_gui_main.py::_commit_config_and_task_mode:5123`） |

---

## 2. 六階段使用流程現況

### A. 建立規則

- **新建任務**：工具列 `＋`（`06_gui_main.py:5861`）→ `QInputDialog`、重名擋（`6628`）、自動建 `__default__` 群組（`6618-6646`）。空任務組合框亦自動建預設任務（`gui/rule_config_controller.py:50-68`）。
- **新增規則**：`_add_rule_btn`（`6002-6015`）、快捷鍵 `Ctrl+N→_add_rule`（`6276`）；實作預填空 `detect` 步驟（`7923-7991`）。**新規則的 detect 文字為空**，使用者必須自行填寫。
- **新增群組／步驟**：「＋群組」建 `RuleGroup(name=T("ui.new_group"))` 並 inline 改名（`7782-7796`）；「＋步驟」下拉 11 型附 i18n 說明（`6094-6117`）→ `_add_step:7993`，自動展開（2B）。
- **空狀態**：無規則 hint（`5991`，`7338`）、搜尋無結果提示（`5995-5998`）、未選取時 guide page（`6022-6042`，文案 `guide.usage/step1-5`）、一次性啟動指南（`5803-5809`）、網頁指南按鈕（`5922-5924`）。
- **複製/刪除/改名**：右鍵選單（`8135-8187`）含複製、複製到群組、移動到群組、群組改名/上移/下移/刪除；複製自動 `(2)/(3)` 後綴（`8189-8229`）。刪規則有 jump 參照警告與孤兒範本清理（`8047-8133`）；刪群組級聯刪規則、禁刪 `__uncategorized__`（`7846-7890`）。任務改名/刪有最少保留 1 個與未儲存確認（`6901-6975`）。
- **搜尋/排序/展開**：搜尋（`7151-7234`）僅 `setHidden`、命中群組自動展開、清除恢復快照；**搜尋期間停用拖曳**（`7229-7234`）。無字母排序；手動拖曳（`rule_tree_widget.py:8-80`）+ 群組上移/下移（`7798-7816`）。展開/折疊狀態持久化到任務檔 `_collapsed_groups`（`7512-7528`）。
- **自動儲存**：四態 `dirty/saving/saved/failed`（`329-360`，2B），500ms debounce（`8321-8411`）。

### B. 設定步驟

- **分派**：`_build_form:1191` 依 `step.type` 建立 11 表單（detect/click/key/match_image/drag/scroll/compare/sum/notify/wait/jump）；未知 type 回 `None`（`1302`）。展開/收合有提交閘：表單 `save() is False` 拒絕收合/重建/排序/刪除（`960-1103`）。
- **預設值來源鏈**：`core/rule_migration.py:_STEP_DEFAULTS:5-53` → `gui/06_gui_main.py:4936` → `_add_step:7993-8028` 以 Settings 覆寫（`5150 SettingsDialog`）→ 載入時 `_normalize_step_params:475-609` 夾值/型別收斂。時間單位一律 `ms`（上限 GUI 60000）；相似度儲存 `0~1 float`、Detect 表單以 `%` 顯示（`2155-2177`）；Drag 終點 `end_x/end_y` 為客戶區比例 `0~1`；座標統一客戶區比例。
- **各 Step 必要/進階區分**（詳見 subagent 證據表）：
  - Detect：基本區為文字 + ROI（`2118-2135`，ROI 明確標為基本設定）；進階區預設展開但 on_fail 子區收合（2A/2B）；on_fail 6 動作（stop/advance/skip/jump/key/notify）+ `fail_duration_sec`（`2234-2350`）。
  - MatchImage：基本區模板 + 搜尋 ROI + 相似度（`1339-1416`）；進階預設收合（2B）；**明確無 Verify**（ADR-0005，`1480,2049`）。
  - Click：基本區目標 + 座標（`3650-3674`）；進階（按鈕/抖動/hold/延遲）預設收合（2B）；Verify 尾端（`3728-3741`）。
  - Drag：基本區含起點/終點/比例 spin/dx-dy/按鈕/延遲**全部常顯、非收合**（`3816-3911`）；**唯一會回 `False` 阻擋提交的表單**（半套終點整筆不寫入 `4010-4015`）；無 `cursor` 目標選項（與 Click 不同）；Verify（`3912-3925`）。
  - Scroll/Key/Wait/Jump/Notify：精簡欄位，無 ROI/on_fail/Verify（Scroll/Key 有 Verify）。
  - Compare：基本區 ROI + 運算子 + 目標值（`4151-4203`）；pattern/on_fail 在預設收合進階區（`4205-4344`）；**無 `after_delay`**（core choke point 白名單不含 compare，`05_main_loop.py:2179-2184`）。
  - Sum：ROI + 閘門（預設關閉，勾選才顯示 operator/value/wait/fail，`4504-4577`）；閘門關閉刪除全部閘門參數（ADR-0006，`4610-4614`）。
- **驗證時機不一致**（詳 §4 UX3-06）：Detect 空文字僅紅框不擋 save（`2364-2370`），硬擋在 preflight（`rule_preflight.py:139-152`）與啟動前 `_rule_hard_problems`（`8424-8433`）；MatchImage 缺模板僅警告（`8459-8464`）；Sum 空 ROI 僅橘色警告不擋（`4493-4497`）。

### C. 測試與校準

- **規則測試（Test）**：`_edit_test_btn` 選中規則才顯示（`6123-6125`、`7638-7650`）→ `run_controller.py:on_test_rule:85`：先存檔 → 硬問題擋 → 截幀 → 背景執行 `_run_dry_run:174-836`。結果首行顯示規則名+步數（`240`），log 每行 `[idx]` 編號，圖片以 step 數字標記（`_draw_test_annotations:840-943`）。命中/未命中列 mode/threshold/best%/Top5 OCR/on_fail hint；on_fail 命運以灰字刪除線標「本輪不會執行」（`_dry_fail_fate:40-74`）。**測試對話框只有 `Close`（`8565-8571`），無中途取消鈕**；測試期間按鈕改「測試中」停用（`100-101`）。
- **MatchImage 內嵌比對**：「比較圖片」按鈕（`1374-1376`），結果只寫表單內 label（`1745-1748`），不彈窗，可直接調 threshold/ROI 繼續校準。
- **OCR Debug**：需已選視窗且主循環未執行（`8574-8588`）；四訊號建立規則/步驟（`09_ocr_debug.py:473-476` → `06_gui_main.py:5592-5597`）：新 detect+click 規則（`_on_debug_rule_requested:8590`）、detect 追加到**目前規則**（`_on_debug_step_requested:8658`）、新 match_image+click 規則（`8694`）、match_image 追加（`8764`）。四者皆 flush-save 後切回 rules 頁並選中目標。**「追加到目前規則」的兩條路徑在無目前規則時靜默 `return`（`8660-8662`、`8766-8768`）**。
- **Click/Key 真輸入測試**：主循環執行期間停用（C-5，`09_ocr_debug.py:1045-1067`）；結果三層顯示（BackendStatus/ObservationStatus/legacy 短結論）。
- **座標校正**：獨立 CLI `devtools/coordinate_calibration.py --self-check/--diagnose/--e2e`；**GUI 內無校正入口**。

### D. 執行與監控

- **啟動前**：`_start_loop:8829-8955` 依序檢查（任務載入失敗/無視窗/錄製中/無規則/空步驟規則/群組選擇對話框/未歸類警告/硬問題/後台黑畫面測試截圖/flush-save/hybrid 自動最小化）→ `InitWorker:5057-5107` 建立 MainLoop 並接 12 個 callback → `loop.start()`。
- **群組選擇對話框**（`group_selection_controller.py:32-128`）：列出**已啟用群組**、預設全勾、未歸類警告（`50-54`）、全選/全不選、「不再詢問」、一鍵切前景/後台並執行。**只顯示群組名，不顯示每群組規則數/正要執行的規則**。
- **控制語意**：無獨立 Pause 按鈕。F8 / 主按鈕三態：未執行→開始；執行中→停止；暫停中→繼續（`_toggle_start:8815-8827`）。`pause()/resume()` 僅翻 `_pause_event`（`05_main_loop.py:3266-3272`）；自動暫停來源：視窗遺失、速率限制。
- **進度可見性**：狀態列（perf 1s + 互動方法按鈕，`6178-6214`）、規則樹顏色（`_update_rule_status:7420-7487` 讀 `get_rules_status:3362-3385`，含 pointer/failed/group_done）、執行日誌面板（`6146-6158`，500ms poll 增量附加）、sum overlay、通知堆疊（2s 自動消失）。**狀態列無「目前在跑哪條規則/步驟」文字**；pointer 僅以樹上 `#4fc3f7` 高亮表示。
- **停止語意**：Global Stop 優先於任何 StepResult（E2-A2）；已送出 DOWN 後必要 UP/Release 不受停止閘阻擋（`_stop_gate:813-821`）。

### E. 錯誤診斷與恢復

- **錯誤通道**：`on_error`→警告彈窗；`on_warning`→**狀態列 5s + toast 同時**（`6262-6265`）造成重複；`on_bg_fail/on_black_fail`→首次彈恢復對話框（管理員重啟/切前景/保持後台，`9078-9106`）；`on_window_lost/recovered`→按鈕切「繼續/停止」+ toast；資源警告→狀態+可選 toast。
- **Preflight 兩層落差**：core `rule_preflight:89-206` 擋 `empty/invalid_detect_text`、`unknown_step_type`、`sum_gate_*`、`gate_sum_click_no_target` 等（BLOCKED 執行期短路，`05_main_loop.py:2130-2132`，前景 toast+log、背景僅 log）。GUI `_rule_hard_problems:8424-8434` **只有空 detect 文字 + custom click(0,0) 兩項**——sum 閘門、未知 type 等只在執行期 BLOCKED 才出現（`_record_preflight_block:2704-2733`）。
- **恢復操作現況**：視窗遺失自動暫停/恢復；後台失敗有切換對話框；任務載入失敗鎖定編輯（`6551-6563`）；設定/模式寫入失敗有分階段回報（`6426-6475`）。**無「從錯誤跳回編輯位置」、無「重試/重新校準」按鈕**。
- **UX-E2**（見 §6）：執行日誌**不可點、無跳轉、無 rule_id**。

### F. 日常管理

- **任務切換**：`_on_task_changed:6509-6616` 先 flush-save，載入失敗彈 critical 並鎖定編輯；切換時套用任務綁定的互動方法與視窗（`6602-6616`）。執行中任務控制停用（`9202-9206`）。
- **互動方法（2C）三入口一 helper**：Settings 對話框（`5248-5255`）、狀態列按鈕（`6191-6211`，即時切換不重建 loop，`6391-6424`）、群組選擇對話框（`97-115`）；皆經 `_commit_config_and_task_mode:5123-5147` 雙寫（global + task，失敗回滾）。
- **匯入/匯出/分享**：匯出寫 `_meta{format_version:1, app_version, exported_at}`（`task_management.py:194-225`）；匯入有 10MB 上限、結構驗證、預覽對話框（meta/規則名≤20/警告清單/重生 id 選項，`6977-7073`）；分享僅「開啟任務資料夾」+「網站 Discussion 連結」（`5882-5896`），無網路上傳。

---

## 3. 已完成項目排除清單（不得重提）

以下均以 HEAD 實際程式碼/歷史 commit 核實存在，不列入待辦：

### Phase 1（歷史交付，`67763ab` onboarding 等 commit）
- Guide page、tooltips、status bar、placeholders、ROI 尺寸顯示（`67763ab UX onboarding`，現況 `guide.usage/step1-5`、`6022-6042`）。

### Phase 2A
| 項目 | 證據 |
|---|---|
| E1 blocked execution log 翻譯 | `09c9115`；`execution_log_widget.py:_RESULT_KEYS:64-72` 含 `blocked` |
| C2 on_fail 短標籤改善 | `694f5d3` |
| C7 刪除 Step 確認 | `e854d60` |
| C1 Detect ROI 移基本區、on_fail 預設收合 | `9cefb77`；`_DetectStepForm:2126-2135、2212-2223` |
| C3 相似度百分比呈現 | `9ee63c0`；`2155-2177` `%` 顯示 |

### Phase 2B
| 項目 | 證據 |
|---|---|
| 新手指南文案對齊真實操作 | `deafb6b` |
| 一鍵啟動→全部啟用/停用 | `bb831fc`；`_toggle_all_btn:6008`、`_toggle_all_groups:7826` |
| 儲存狀態 dirty/saving/saved/failed | `7218d1e`；`329-360` |
| 新增步驟自動展開 | `23eb5ed` |
| MatchImage 進階設定摺疊 | `8bda725`；`1418-1434` 預設收合 |
| 規則樹搜尋 | `96ddc55`；`7151-7234` |
| Click 進階及 Verify 預設收合 | `27d3605`；`3676-3727`、`2762-2785` |
| 工具列常用/次要分組 | `a9971f1` |

### Phase 2C
- 狀態列互動方法按鈕即時切換：`c93ebfa`；`6191-6211`、`6391-6424`。

### Phase 2D
- 主視窗大小/位置/最大化記憶（含 normalGeometry frame 偏移修正）：`c70ded2`、`8db6aea`、`eda31c4`。真機測試已通過，不重開。

---

## 4. 仍存在的 UX 問題（含分級）

### UX3-01 — 執行日誌無法定位規則／步驟（UX-E2）【P1】

| 欄位 | 內容 |
|---|---|
| 使用者情境 | 規則執行中出錯（detect 未命中、preflight BLOCKED、驗證逾時），使用者看執行日誌想知道「哪條規則的第幾步」，並直接跳回去改設定 |
| 現況 | 日誌列僅顯示時間/規則名/步數/結果/詳情；**不可點、無跳轉、無 rule_id**；編輯面板執行中停用，使用者只能在執行結束後手動在樹上找同名規則 |
| 問題 | 同名/改名後規則無法區分（`_log_exec` 只存 `rule_name`）；使用者需逐條比對樹與日誌；錯誤恢復第一步被卡住 |
| 證據 | `core/05_main_loop.py:_log_exec:579-586`（`{"ts","rule_name","step_idx","step_type","result","detail"}`，呼叫方皆傳 `rule.name` 如 `2143,2169,2724,2839`，`rule.id` 未存入）；`gui/execution_log_widget.py:36-61`（無 `pyqtSignal`、無 `cellClicked` 接線、無 `UserRole` id，`_populate:110-129`）；`06_gui_main.py:9010` 執行中編輯停用；全倉搜 `cellClicked/itemClicked/doubleClicked` 在 `gui/` 無日誌命中；唯一含 `rule.id` 的日誌是 `[sum]` 檔日誌（`05_main_loop.py:1429-1441`） |
| 改善方案 | `_log_exec` 新增 `rule_id` 欄位（保留 `rule_name` 顯示）；`ExecutionLogWidget` 規則/步驟欄存 `UserRole=(rule_id, step_idx)`，`cellClicked` 發 `locate_requested(rule_id, step_idx)`；執行中點擊→記錄 pending target 並在狀態列提示「停止後將定位到…」，停止後自動選中規則並展開對應 step 表單（重用既有 `_on_rule_selected` / step list scroll）；dry-run 結果 dialog 同理可點 log 行跳 step |
| 效益 | 錯誤→定位→修改→重測形成閉環；同名規則可由 id 區分 |
| 風險 | 編輯面板執行中停用，需決定 pending 語意避免誤導；deque 增量附加（`execution_log_widget.py:74-94`）需保留新欄位的相等比對 |
| 成本 | S |
| 建議 | **本階段處理** |

### UX3-02 — Drag Legacy Marker 無 GUI 修復入口（C-2a-2）【P1】

| 欄位 | 內容 |
|---|---|
| 使用者情境 | 使用者載入舊任務，Drag 步驟終點是舊 PX offset（`dx/dy`），`_migration{kind=drag_endpoint,status=needs_repair}`；拖曳執行期才 terminal（`drag_end_invalid`），編輯器無任何提示 |
| 現況 | 編輯器無「needs_repair」提示、無修復入口、無清除按鈕；使用者只能手改 JSON 或重建規則；preflight 不檢查 drag 終點，故 needs_repair 不會被 BLOCKED |
| 問題 | 核心流程錯誤類：壞規則在測試/執行期才浮現，且無 GUI 路徑可修 |
| 證據 | `gui/` 對 `_migration/needs_repair/validate_drag_endpoint` **零命中**（Grep 實測）；marker 偵測與寫入 `core/rule_migration.py:121-190,482-485`、驗證 `197-261` 僅測試消費（`tests/test_drag_legacy.py`）；GUI 自行重寫狀態機 `_drag_end_state:494-511` 不呼叫 core 驗證；文件一致：`docs/dev/NEXT_STEPS.md:24-27`、`KNOWN_ISSUES.md:C2-3`、`CURRENT_STATUS.md:C-2a-2 ⬜未開始` |
| 改善方案 | 僅在 `validate_drag_endpoint(params)` 回 `needs_repair` 時，於 `_DragStepForm` 頂部顯示修復 banner（白話說明 + 「拾取終點」按鈕）；拾取成功後寫入 `end_x/end_y`（客戶區比例）並**經使用者確認才清除 `_migration`**、flush-save、reload 重檢；不自動清洗既有假 marker（產品決策 keep，`NEXT_STEPS.md:80`）；banner 不出現於任何其他規則 |
| 效益 | 舊任務 Drag 可在 GUI 內自我修復，不再手改 JSON |
| 風險 | 必須以 core `validate_drag_endpoint` 為唯一判定，不得在 GUI 寫第三套狀態機；清除 marker 時機錯誤會丟失原始 dx/dy 診斷資訊 |
| 成本 | M |
| 建議 | **本階段處理** |

> **狀態更新（2026-11-10，UX Phase 3C）**：**已實作**。修復入口已上線：`_DragStepForm` 以 core `validate_drag_endpoint()` 為唯一判定，僅在 `needs_repair` 時顯示修復 banner（拾取終點 → 使用者確認 → 才移除 `dx/dy` 與 marker → 儲存 → reload 重檢）；未修復前舊欄位唯讀且原值保留；任務載入時提示需修復的步驟數。既有假 marker 不自動清洗（keep 決策）。**真機 GUI 驗證尚未完成**（僅自動化測試）。

### UX3-03 — 啟動前檢核與執行期 preflight 落差【P1】

| 欄位 | 內容 |
|---|---|
| 使用者情境 | 使用者設定了 sum 閘門但未設 ROI，或用了未知 step type，按「開始」後以為可以跑，執行期才看到 BLOCKED |
| 現況 | GUI 啟動硬擋僅 2 項（空 detect 文字 + custom click(0,0)）；core preflight 另擋 sum 閘門、未知 type、invalid step 等，執行期才以 log+toast（前景）呈現，背景僅 log |
| 問題 | 使用者無法在啟動前一次看到全部「不會執行」的問題，也無法點進去修；錯誤浮現時機太晚 |
| 證據 | `06_gui_main.py:_rule_hard_problems:8424-8434`（2 項）vs `core/rule_preflight.py:89-206`（`unknown_step_type:155-160`、`sum_gate_*:163-171`、`gate_sum_click_no_target:176-182`）；執行期 `_record_preflight_block:2704-2733`；dry-run 已正確顯示 BLOCKED（`run_controller.py:227-237`） |
| 改善方案 | 啟動前與測試前統一呼叫 `rule_preflight`（純函式，已與 ctx 解耦），以可操作清單呈現全部 blocked 問題，每行可點跳到對應規則/step；GUI `_rule_hard_problems` 改為呼叫 preflight 而非自寫子集；不放寬任何型別驗證 |
| 效益 | 「按開始前就知道哪幾條不會跑、為什麼、點哪裡改」 |
| 風險 | preflight 目前回傳的問題文字為內部 key，需補 i18n 白話對應；注意 BLOCKED 語意（parallel 等待）與啟動擋的區別，不可把等待語意改成錯誤 |
| 成本 | S |
| 建議 | **本階段處理**（與 UX3-01 共用「定位到編輯」機制） |

### UX3-04 — 規則測試無取消、結果不可回跳【P2】

| 欄位 | 內容 |
|---|---|
| 使用者情境 | 使用者按「測試」後截圖/OCR 卡住或發現選錯視窗，想取消；或測試結果顯示某 step miss，想直接跳回去調參 |
| 現況 | 測試 dialog 只有 `Close`，無取消鈕；結果 log 行不可點；關閉後回到同一規則編輯頁但不定位到出錯 step |
| 問題 | 測試等待不可控；診斷結果到設定之間仍需手動對應步數 |
| 證據 | `run_controller.py:on_test_rule:85-151`（背景執行緒 `_run_rule_test:155-170`，無 cancel flag）；`_show_test_result:8519-8571`（僅 Close）；結果 log 行 `test.detect_hit/miss` 等（`291-367`）無 click 處理 |
| 改善方案 | 測試 dialog 加「取消測試」按鈕（取消旗標 + 等待執行緒收尾，不碰進行中輸入——dry-run 本就不送輸入）；結果 log 行可點，關 dialog 並跳到對應 step 表單 |
| 效益 | 測試可控、診斷可回跳 |
| 風險 | 執行緒取消需確認不殘留狀態；與停止/暫停語意分開標示 |
| 成本 | S |
| 建議 | **本階段處理** |

### UX3-05 — Sum 閘門在 dry-run 不評估【P2】

| 欄位 | 內容 |
|---|---|
| 使用者情境 | 使用者設定數字加總閘門（operator/value/wait），按測試顯示總和看起來正常就啟動，正式執行時閘門逾時/不符 |
| 現況 | dry-run 的 sum 分支只加總回報，不評估 gate/operator/value/timeout/on_fail，與引擎語意不一致 |
| 問題 | 測試給出過度樂觀的信心；閘門是「等不到/不符合」的等待語意，測試完全沒覆蓋 |
| 證據 | `gui/run_controller.py:615-647` vs `core/05_main_loop.py:1274-1363`（等待中不走 on_fail、穩定值才比對） |
| 改善方案 | dry-run sum 分支補上 gate 評估：顯示「會等多久、等到什麼條件、目前加總是否已符合」，不符時標示將如何處理（stop/advance/notify）；不改變引擎等待語意 |
| 效益 | 測試結果可信，不再有「測好才跑、跑了才發現閘門問題」 |
| 風險 | dry-run 與真執行等待時間不同，需明示為「條件判斷示範」而非實際等待 |
| 成本 | S |
| 建議 | **本階段處理** |

### UX3-06 — Step 驗證時機與 Drag 雙表示不一致【P2】

| 欄位 | 內容 |
|---|---|
| 使用者情境 | 使用者逐一填寫各 Step：Detect 空文字可儲存、Drag 半套終點被擋、MatchImage 缺模板只警告、Sum 空 ROI 只警告 |
| 現況 | 四種驗證強度並存（紅框不擋 / 阻擋提交 / 警告 / 橘色提示）；Drag 同時顯示「終點比例 spin」與「dx/dy px」兩套表示，常顯不收合；Click 有 `cursor` 目標、Drag 無 |
| 問題 | 使用者無法預測「什麼設定會被擋」；Drag 終點到底改哪一組欄位不明確；Click/Drag 目標選項不一致增加學習成本 |
| 證據 | Detect `2364-2370`（僅紅框）；Drag `4010-4015`（唯一阻擋）；MatchImage `8459-8464`（警告）；Sum `4493-4497`（橘色警告）；Drag 常顯欄位 `3816-3911`、Click 進階收合 `3676-3727`；Click 目標 `3650-3662` vs Drag `3816-3826` |
| 改善方案 | 統一為「紅框 + 明確說明 + 啟動/測試前統一擋（UX3-03）」三段式，不新增阻擋點；Drag 終點區改為單一主路徑（拾取/比例）+ dx/dy 收進「舊格式相容」折疊並加白話說明；Click/Drag 目標選項差異加 tooltip 說明理由（或補齊 cursor） |
| 效益 | 驗證行為可預測；Drag 終點不再有兩套真相 |
| 風險 | 不可改變既有儲存格式與 `_normalize_step_params` 語意；折疊/改名為純 GUI 層 |
| 成本 | M |
| 建議 | **本階段處理（Drag 主路徑 + tooltip 先行）**；完整驗證統一可延後 |

### UX3-07 — 執行中「在跑什麼」不夠明確【P2】

| 欄位 | 內容 |
|---|---|
| 使用者情境 | 使用者按 F8 啟動後，想目視確認「現在跑到哪條規則、哪個群組」；群組選擇對話框只看到群組名 |
| 現況 | 狀態列只有 perf 與互動方法，無目前規則/step 文字；pointer 只在樹上以顏色標示；群組對話框不顯示規則數；暫停無獨立按鈕，F8 三態（開始/停止/繼續）無圖示區分 |
| 問題 | 執行狀態只能靠樹顏色 + 日誌推測；群組選擇時不知道勾選會跑多少規則 |
| 證據 | `6178-6214`（狀態列 permanent widgets）；`_update_rule_status:7420-7487`（pointer `#4fc3f7:7477`）；`get_rules_status:3362-3385` 已有 pointer 資料未上狀態列；`group_selection_controller.py:63-68` 僅群組名；`_toggle_start:8815-8827` |
| 改善方案 | 狀態列新增「執行中：{群組} / {規則} / 步驟 {n}」文字（資料已在 `get_rules_status`）；群組選擇每項加「（{n} 條啟用規則）」；主按鈕暫停態加明確圖示/文字區分；不新增 Pause 按鈕（沿用 F8/主按鈕語意） |
| 效益 | 執行進度一目了然；啟動前決策有依據 |
| 風險 | 狀態列更新頻率受效能紅線約束（每 tick 工作量正比新增資料，不可每秒重建）；群組規則數為純顯示計算 |
| 成本 | S |
| 建議 | **本階段處理** |

### UX3-08 — OCR Debug「追加步驟」在無目前規則時靜默無反應【P2】

| 欄位 | 內容 |
|---|---|
| 使用者情境 | 使用者在 OCR Debug 辨識出文字，按「新增步驟」想追加到規則，但主視窗尚未選任何規則 |
| 現況 | `_on_debug_step_requested` / `_on_debug_template_step_requested` 取不到目前規則時直接 `return`，無任何提示；使用者以為按鈕壞掉 |
| 問題 | 無回饋的靜默失敗；且「追加到哪條」的目標在 Debug 面板不可見 |
| 證據 | `06_gui_main.py:8660-8662`、`8766-8768`（`if rule is None: return`）；對比新規則路徑 `8590-8656` 有完整回饋 |
| 改善方案 | 無目前規則時彈白話提示並提供「改為建立新規則」選項；Debug 面板頂部顯示目前目標規則名（唯讀標示），讓「落到哪條」可見 |
| 效益 | 不再有按了沒反應的死路 |
| 風險 | 僅 GUI 分支補提示，不改變資料落點規則 |
| 成本 | S |
| 建議 | **本階段處理** |

### UX3-09 — 警告同時走狀態列與 toast、toast 2 秒過短【P3】

| 欄位 | 內容 |
|---|---|
| 使用者情境 | 執行中出現警告（慢偵測、資源不足、規則異常），使用者在玩遊戲分心，2 秒 toast 消失後狀態列 5 秒也消失，事後無處可查 |
| 現況 | `on_warning` 同一訊息送狀態列 5s + toast 2s；重要錯誤的持久記錄只有檔案日誌（需開 LogViewer 手動翻） |
| 問題 | 雙通道重複且皆短暫；診斷證據在使用者注意力視線外消失 |
| 證據 | `06_gui_main.py:6262-6265`（雙送）；`notification_stack.py:21-39`（2000ms 自動 pop）；`12_log_viewer.py:26-118`（需手動開） |
| 改善方案 | 警告類改為「toast 短暫 + 狀態列持久直到下一事件」或在執行日誌面板加警告列；不新增通道；LogViewer 加「警告」篩選捷徑（既有 substring 搜尋上加預設） |
| 效益 | 警告不再轉瞬即逝 |
| 風險 | 狀態列持久顯示需避免遮蔽其他狀態訊息 |
| 成本 | S |
| 建議 | 延後（與 UX3-01 同批可順手） |

### UX3-10 — 規則多時的管理斷點【P3】

| 欄位 | 內容 |
|---|---|
| 使用者情境 | 規則累積幾十條後，找規則、排序、區分同名規則變困難 |
| 現況 | 無字母排序（僅手動拖曳）；搜尋期間停用拖曳；同名規則在日誌/樹上難 distinguish（UX3-01 修復後緩解） |
| 問題 | 管理效率問題，非核心阻擋 |
| 證據 | `7151-7234`（搜尋停用拖曳）；無 sort 功能（搜「sort」僅拖曳/群組上下移） |
| 改善方案 | 群組/規則右鍵加「依名稱排序」（僅重排顯示順序，不改執行語意）；重名規則在樹上加 id 後綴提示（僅顯示） |
| 效益 | 大任務管理效率 |
| 風險 | 排序不可改變群組執行順序語意（群組內 rule_ids 順序即執行順序，排序即改語意，需確認） |
| 成本 | S |
| 建議 | 延後（先修 UX3-01 的 id 區分） |

### UX3-11 — 首條規則的空 Detect 預設【P3】

| 欄位 | 內容 |
|---|---|
| 使用者情境 | 新手按「＋規則」，得到一條空文字 detect，不知道下一步該填什麼、ROI 在哪裡 |
| 現況 | Guide page 有 step1-5 說明；新規則 detect 文字為空；ROI 入口在基本區但新手需自行發現 |
| 問題 | 入門最後一步仍靠使用者自學；但 guide 已存在，不構成 P0/P1 |
| 證據 | `_add_rule:7923-7991`（空 detect）；guide `6026-6038`、`START.md:44-72` 路徑 B |
| 改善方案 | 新規則建立後自動把焦點放到文字欄位並顯示「先打你要找的字」一次性提示；不新增 wizard |
| 效益 | 首規則上手 |
| 風險 | 提示不可重複打擾回訪使用者 |
| 成本 | S |
| 建議 | 延後 |

---

## 5. P0～P3 分級總覽與優先順序

| ID | 標題 | 級別 | 成本 | 建議 |
|---|---|---|---|---|
| UX3-01 | 執行日誌定位規則／步驟（UX-E2） | **P1** | S | 本階段 |
| UX3-02 | Drag needs_repair 修復入口（C-2a-2） | **P1** | M | 本階段 |
| UX3-03 | 啟動前檢核與 preflight 落差 | **P1** | S | 本階段 |
| UX3-04 | 測試無取消、結果不可回跳 | P2 | S | 本階段 |
| UX3-05 | Sum 閘門 dry-run 不評估 | P2 | S | 本階段 |
| UX3-06 | Step 驗證不一致 + Drag 雙表示 | P2 | M | 本階段（子項分批） |
| UX3-07 | 執行中「在跑什麼」不明 | P2 | S | 本階段 |
| UX3-08 | Debug 追加步驟靜默無反應 | P2 | S | 本階段 |
| UX3-09 | 警告雙通道＋toast 過短 | P3 | S | 延後 |
| UX3-10 | 規則多時管理斷點 | P3 | S | 延後 |
| UX3-11 | 首條規則空 Detect 預設 | P3 | S | 延後 |

**無 P0**：核心流程（建立→設定→測試→執行→停止）可完整走通，無資料遺失或核心錯誤；P1 皆為「錯誤發生後無法定位/修復」的恢復斷點。

---

## 6. UX-E2、C-2a-2 重新調查結果

### UX-E2：日誌定位規則／步驟 — **仍然存在，未被其他修改解決**

- 執行日誌 entry 無 `rule_id`（`05_main_loop.py:609-618`）；widget 無任何 click signal（`execution_log_widget.py` 全檔無 `pyqtSignal`）；全倉 `gui/` 無 log 點擊接線。
- 唯一例外：`get_rules_status()` 回傳 id-keyed 狀態供樹著色（`3362-3385`），但未與日誌連結。
- 影響範圍：所有 on_fail、BLOCKED、驗證逾時、超時等診斷場景；同名規則完全無法區分。

### C-2a-2：Drag Legacy Marker 修復的 GUI 操作入口 — **仍然存在，未開始**

- `gui/` 對 `_migration / needs_repair / validate_drag_endpoint` 零命中；`validate_drag_endpoint`（`rule_migration.py:197-261`）僅測試消費。
- dry-run 僅在 `resolve_drag_end` 拋錯時 terminal（`run_controller.py:436-442`）；preflight 不檢查 drag 終點。
- 與 `NEXT_STEPS.md:24-27` 規劃一致：目標為「修復終點入口（拾取終點 → 使用者確認清除 `_migration` → 儲存 → reload 重檢）」，前置（marker 貫穿、純函式、測試）已備齊。
- **禁止**自動清洗既有假 marker（keep 決策）；C2-2 假 marker 清洗仍為獨立另案。

---

## 7. 建議的 Phase 3 開發範圍

| 批次 | 內容 | 預估 |
|---|---|---|
| 1 | UX3-01 日誌定位 + UX3-03 preflight 統一檢核（共用「定位到編輯」機制） | S |
| 2 | UX3-02 Drag 修復 banner（以 `validate_drag_endpoint` 為唯一判定） | M |
| 3 | UX3-04 測試取消/回跳 + UX3-05 sum gate dry-run + UX3-08 debug 靜默修復 | S |
| 4 | UX3-07 狀態列執行目標 + 群組對話框規則數 + UX3-06 Drag 主路徑收斂 | S/M |

架構約束（必須遵守）：不放寬型別驗證、不動 `_loader.py`、不重定義 Rule/Step、不重寫大型核心模組、不引入新框架、不破壞任務 JSON 相容性；新增欄位（如 `rule_id`）僅限執行期日誌結構，不進任務 JSON；Global Stop 與 local on_fail 語意不變；已送出 DOWN 後必要 UP/Release 不受停止閘阻擋。

---

## 8. 不建議處理的項目及理由

| 項目 | 理由 |
|---|---|
| 主視窗幾何相關工作 | 2D 已完成且真機通過（`c70ded2`/`8db6aea`/`eda31c4`），不得重開 |
| Phase 1/2A/2B/2C 已完成項目 | §3 排除清單；無新實證缺陷不重提 |
| 自動清洗假 `_migration` marker | 產品決策 keep（`NEXT_STEPS.md:80`），C2-2 另案 |
| Parallel Once 全 BLOCKED 改自動推進/停止 | 產品決策保持等待＋可觀察（C-2a-1 NEW-C） |
| C-4 `_last_error` 跨執行緒歸屬、C-6 通知重新武裝、C-7 真機驗證 | 非 UX 範圍；C-7 屬真機阻塞項，另行處理 |
| 新增「新規則 wizard」或重做 guide | Guide 已存在（`guide.usage/step1-5`）；UX3-11 以焦點提示即可，無需新流程 |
| 引入新框架/設計系統/圖表庫 | KPI 已足夠；YAGNI |

---

## 9. HTML 原型索引

| 原型 | 用途 | 入口 |
|---|---|---|
| 執行日誌定位（UX3-01/03 共用） | 修改前後對照 + 點擊日誌行→定位到規則/step 的操作流程 | `devtools/ux_prototypes/phase3/p1_exec_log_locate.html` |
| Drag 修復 banner（UX3-02） | needs_repair 狀態的修復入口：banner、拾取終點、確認清除 marker、reload 重檢 | `devtools/ux_prototypes/phase3/p1_drag_repair.html` |
| 啟動前檢核清單（UX3-03/04/05/07） | 啟動前全部問題清單（含可點跳轉）、測試取消、群組規則數、狀態列執行目標 | `devtools/ux_prototypes/phase3/p2_start_check.html` |
| 索引頁 | 三原型總覽 | `devtools/ux_prototypes/phase3/index.html` |

原型僅用 HTML/CSS/JS 假資料，不連正式邏輯，瀏覽器直接開啟。

---

## 10. 未能驗證的項目與限制

1. **未啟動真 GUI**：Agent 環境未實際點擊主視窗、overlay、模板拾取器；所有 UI 行為均以程式碼追蹤（call chain + i18n 文案）為證據，非目視驗證。
2. **未執行 Frida/Hybrid 真機路徑**：後台輸入失敗對話框、黑畫面判定僅追蹤程式碼分支（`_on_bg_fail:9054`、`_check_black_frame:838`）；實際彈窗時機需真機確認。
3. **測試取消可行性**：`_run_rule_test` 執行緒模型僅讀取 `run_controller.py:155-170`，未實際量測取消旗標的收尾時間；原型以概念展示為主。
4. **Sum gate dry-run 評估**：原型展示「條件示範」而非真實等待，實際等待語意仍以真機為準。
5. **Phase 1 歷史逐項核實**：`docs/dev/` 無獨立 Phase 1 交付清單文件，Phase 1 排除以 git 歷史 commit（`67763ab` 等）與現況程式碼存在性確認，未逐項回溯舊報告。
6. **CODEGRAPH 索引延遲**：`codegraph_explore` 回傳曾提示 `core/05_main_loop.py`、`core/04_rule_engine.py` 等「edited since last sync」；凡涉及此類檔案的結論均以直接 Read 複核（`execution_log_widget.py` 全檔已重讀）。

---

## 決策摘要

### 最值得優先處理的 5 項

| 優先 | 項目 | 成本 | 風險 |
|---|---|---|---|
| 1 | **UX3-01** 日誌定位（E2） | S | 低：日誌結構加欄位 + 一個 click handler；執行中 pending 語意需定案 |
| 2 | **UX3-03** 啟動前 preflight 統一檢核 | S | 低：重用純函式，不改驗證規則；需補 i18n 白話 |
| 3 | **UX3-02** Drag 修復（C-2a-2） | M | 中：清除 marker 時機不可錯；必須以 core 驗證為準 |
| 4 | **UX3-08** Debug 靜默無反應 | S | 極低：純提示分支 |
| 5 | **UX3-05** Sum gate dry-run | S | 低：測試層補評估，不碰引擎 |

### 建議實作順序

1. **UX3-01 + UX3-03**（同一批，共用定位機制，一次解決「看不懂、跳不回去」）
2. **UX3-08 + UX3-04 + UX3-05**（測試/診斷閉環收尾）
3. **UX3-02**（Drag 修復，獨立成批以控制清除 marker 風險）
4. **UX3-07 + UX3-06**（執行可視性與 Drag 表單收斂）

### 先做 / 延後

- **先做**：§7 批次 1-3（UX3-01/02/03/04/05/08）——皆為核心流程的錯誤恢復斷點。
- **延後**：UX3-09/10/11（P3，效率/文案層）；UX3-06 完整驗證統一、UX3-07 可視擴充視批次而定。
