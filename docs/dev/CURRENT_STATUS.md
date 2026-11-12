# 目前狀態（CURRENT_STATUS）

> 最後更新：2026-11-12
> 對應階段：**E2／P2 階段收斂 ＋ v0.4.9 發布前修正**（Global Stop／輸入取消／後台失敗回報／通知去重／R-1／R-3／R-5）
> 2026-11-12 補充：UX3-01／UX3-03（執行日誌定位 ＋ 啟動前檢核深化）——詳見下方「本次完成」的 UX3-01／UX3-03 章節
> 2026-11-12 補充：UX3-07（執行中「在跑什麼」可視化）——詳見下方「本次完成」的 UX3-07 章節
> 2026-11-10 補充：UX3-06（Click／Drag 目標選項與驗證改善）——詳見下方「本次完成」的 UX3-06 章節
> 2026-11-07 補充：AppCompat 自癒、OCR Debug UX、輸入整合驗證 harness（P0，未執行）、hybrid 啟動最小化、數字加總閘門、死碼清理——詳見下方「2026-11-05～11-07 補充」

## 階段進度

| 階段 | 內容 | 狀態 |
|---|---|---|
| 2-7d-2b-2a | wait／jump 步驟編輯表單接通 | ✅ 已 commit（`1e05938`） |
| 1de9239 | 輸入安全、數值驗證與步驟編輯器 | ✅ 已 commit（未 push） |
| 3d01f0a | Drag 終點拾取＋輸入驗證 | ✅ 已 commit（未 push） |
| c06649e | P2-3：通知去重鎖存跨啟動／重載殘留 | ✅ 已 commit（未 push） |
| **C-2a-1** | Preflight／BLOCKED／Drag Legacy／Parallel Once 等待語義 | ✅ **完成，已 commit**（`2f1aa9c`） |
| **E2-A1** | Global Stop／Scheduler 控制流程 | ✅ **完成，已 commit**（`2f1aa9c`） |
| **E2-A2** | Input Cancellation（輸入取消鏈） | ✅ **完成，已 commit**（`2f1aa9c`） |
| **E2-A2-F1** | Frida 取消邊界與 Release 回報 | ✅ **完成，已 commit**（`2f1aa9c`） |
| **P2-1** | `_last_error` 生命週期修正 | ✅ **完成，已 commit**（`2f1aa9c`） |
| **C-1／C-2／C-3／C-5** | 後台失敗回報與 OCR Debug 測試按鈕停用 | ✅ **完成，已 commit**（`2f1aa9c`） |
| **R-1** | Click PostMessage DOWN／UP 失敗原因 | ✅ **完成，已 commit**（`45aefbd`） |
| **R-3** | 主循環啟動時在途 OCR Debug 驗證 worker | ✅ **完成，已 commit**（`45aefbd`） |
| **R-5** | MainLoop 啟動與 OCR Debug 閘門的競態窗口 | ✅ **完成，已 commit**（`0f77931`） |
| **C-2a-2** | Drag Repair UI（`_migration` 消費端、needs_repair 修復流程） | ✅ **完成，已 commit**（UX Phase 3C：修復 banner＋拾取終點＋使用者確認才清除 marker） |
| **UX3-06** | Click／Drag 目標選項與驗證改善（target 白名單＋preflight 事前擋下、dry-run 不再靜默略過、Drag 專屬文案、cursor 目標停用抖動、custom 未設座標提示） | ✅ **完成，已 commit**（**真機 GUI 驗證未完成**；`hold_ms` 死欄位與 validator 差異僅記錄事實，未改契約） |
| **UX3-07** | 執行中「在跑什麼」可視化（狀態列顯示「群組／規則／步驟」、群組選擇對話框顯示啟用規則數） | ✅ **完成，已 commit**（**真機 GUI 驗證未完成**；主按鈕圖示 enhancement 明確排除） |
| **UX3-01／UX3-03** | 執行日誌定位（以 `rule_id` 區分＋定位到步驟）＋啟動前統一檢核（背景規則納入、逐步驟粒度、逐項可定位） | ✅ **完成，已 commit**（**真機 GUI 驗證未完成**；主體早於本次，本次為深化） |
| **真機驗證** | Frida 輸入取消／Release、frida／hybrid 拖曳 | ⬜ 未完成 |

## 工作區狀態

- branch：`master`
- HEAD = UX3-01／UX3-03 批次（程式碼 `56b08aa` ＋ 本次文件 commit）；`origin/master` = `0af3cf0` → **ahead 2 / behind 0**，**尚未 push**
- **staged：空**；工作區乾淨（2026-11-12 盤點）
- 距上次發布（`v0.4.8`）累計 **96 顆** commit 未發布（`git rev-list --count v0.4.8..HEAD`，2026-11-12 核實）
- **v0.4.9 尚未發布**：無 tag、無 GitHub Release（`gh release view v0.4.9` → not found）；`_version.py`／`pyproject.toml` 仍為 `0.4.8`，最新正式版仍是 `v0.4.8`（2026-10-24）

## 測試統計（實測）

| 範圍 | 狀態 |
|---|---|
| `tests/test_bg_diag_reporting.py`（新增，C-1／C-2／C-3） | 20 passed ✅ |
| `tests/test_debug_panel_run_state.py`（新增，C-5） | 7 passed ✅ |
| `tests/test_stop_cancel.py`（E2-A2） | 28 passed ✅ |
| `tests/test_frida_cancel.py`（E2-A2-F1） | 16 passed ✅ |
| `tests/test_bg_error_lifecycle.py`（P2-1） | 10 passed ✅ |
| `tests/test_notify_dedup.py`（P2-3） | 8 passed ✅ |
| `tests/test_rule_preflight.py`（C-2a-1） | 37 passed ✅ |
| `tests/test_drag_legacy.py`（C-2a-1） | 34 passed ✅ |
| `tests/test_run_controller.py`（C-2a-1） | 2 passed ✅ |
| `tests/test_bg_click_error_reporting.py`（新增，R-1） | 12 passed ✅ |
| `tests/test_debug_verify_abort_on_run.py`（新增，R-3） | 16 passed ✅ |
| `tests/test_debug_gate_before_loop_start.py`（新增，R-5） | 11 passed ✅ |
| `tests/test_ux3_06_target_validation.py`（新增，UX3-06） | 27 passed ✅ |
| `tests/test_ux3_07_execution_visibility.py`（新增，UX3-07／UX3-07-F1） | 22 passed ✅ |
| `tests/test_ux3_03_start_check.py`（新增，UX3-01／UX3-03） | 19 passed ✅ |
| **完整套件** | **1828 passed, 13 skipped**（2026-11-12 本次重跑，exit 0；13 skipped 為需桌面／環境的真實整合測試） |

## 2026-11-05～11-07 補充（E2／P2 之後已落地）

- **AppCompat 自癒**（`989fd10`、`a957e3b`、`7059ce4`）：清除「以系統管理員身分執行」RUNASADMIN 層級，解決 Velopack 安裝／更新失敗（os error -2147024156）；`core/13_appcompat.py` + `tests/test_appcompat.py`。
- **OCR Debug UX**（`2375f42`～`535c80a`、`b0d11c1`）：Visual 畫面差異、文字差異分析、OCR 框開關、比較切換、診斷精簡；測試隔離使用者設定檔（`f4fe6ae`）。
- **輸入整合驗證 harness（P0）**（`600c393`、`4db77f`、`0a8afbb`）：`devtools/input_target.py`（測試目標程序）＋`devtools/input_test_bench.py`（工作台）＋`tests/test_input_cancel_release_integration.py`（A/B/C 取消／Release 驗證，需 `OTC_RUN_INPUT_INTEGRATION=1`）。**僅新增測試 harness，未修改產品程式碼；2026-11-07 本次重跑中 13 項 skip，未實際執行，不得視為已驗證。**
- **Hybrid 啟動最小化**（`10ea662`）：啟動循環前先最小化主視窗，避免前景保護擋住第一次循環。
- **數字加總閘門**（`ed88873`）：加總步驟新增可選閘門（ADR-0007、`tests/test_number_sum.py`、`tests/test_sum_gate_form.py`）。
- **死碼清理**（`8eac072`、`2fc9f67`、`d49ea3c`）：移除無法觸及的緊急停止路徑、全域執行模式 API、未使用函式。

## 品質關卡狀態

| 關卡 | 狀態 | 備註 |
|---|---|---|
| `ruff check` | ✅ All checks passed | exit 0 |
| 完整 pytest | ✅ 1828 passed, 13 skipped | 2026-11-12 本次重跑，exit 0；含 i18n 三語測試；13 skipped 為真實整合測試（需 `OTC_RUN_INPUT_INTEGRATION=1` 桌面執行） |
| `git diff --check` | ✅ exit 0 | 僅既有 LF→CRLF warning |
| core self-check（4 檔） | ✅ 全 exit=0 | `03_pynput_input`／`05_main_loop`／`16_bg_input`／`18_frida_bg` |
| 座標校正 `--self-check` | ✅ passed | |
| 座標校正 `--diagnose` | ✅ 通過 | 三模式截圖／OCR／座標路由全部符合預期 |
| 座標校正 `--e2e` | ✅ 6/6 通過 | 三模式 × 有框／無框，最大偏差 0px |
| i18n 三語齊 | ✅ zh_TW / en / ja 新 key 同步 | |

## 本次完成（E2／P2 階段）

### C-2a-1（Preflight／BLOCKED）

- **NEW-A**：GUI drag 表單不再無條件寫回 `dx/dy`（dirty tracking＋舊資料原樣保留）；新式 endpoint drag 不再被誤判 legacy／mixed
- **F-03**：BLOCKED 使用者可見——前景：execution log＋狀態列／toast（同規則同問題只通知一次）；背景：只寫 execution log；**Dry Run 明確顯示「因設定錯誤不會執行」，不假裝成功**
- **NEW-B**：fp=None 以問題分類 fallback 去重，不靜默、不刷屏
- **NEW-C**：Parallel Once 全 BLOCKED **保持等待**（不推進 queue、不假完成、不觸發 stop）；修復規則並儲存→reload 後自動恢復
- **F-07**：Background／Parallel 的 BLOCKED gate 由 `_run_step` spy 測試鎖定

### E2-A1／E2-A2／E2-A2-F1（停止與輸入取消）

- Global Stop 優先於任何 StepResult：不重送輸入、不執行下一個 Step、不計入 completed、不推進指標
- 輸入鏈可中斷：按鍵放開、拖曳放開、滾輪、驗證輪詢與重試延遲皆可被中止；**必要的 Release 永不受停止閘阻擋**
- Frida：attach 期間抵達的停止不再變成真實點擊／按鍵；UP 失敗可被回報

### P2-1／P2-3（狀態生命週期）

- `_last_error`：每次後台操作開始歸零（bg 層與 frida 層同時），`last_error()` 只反映當次操作
- `_notified_conditions`：啟動與規則重載時清除，條件再次成立可再次通知

### C-1／C-2／C-3／C-5（診斷與輸入回報）

- **C-1**：Frida 按鍵 UP 失敗不再回報成功（回傳 False＋記錄原因），MainLoop 不再標記 triggered
- **C-2**：後台拖曳／滾輪失敗會進入既有回報機制並保留失敗原因（滾輪不再忽略 `PostMessageW` 回傳值）
- **C-3**：30 秒節流只擋 GUI 通知，**日誌每次失敗都寫**
- **C-5**：主循環執行期間停用 OCR Debug 的點擊／按鍵測試按鈕，停止後依面板原狀還原

### R-1／R-3（發布前最小範圍修正）

- **R-1**：`core/16_bg_input.py` `_click_postmessage()` 的 DOWN／UP 失敗改以 `_set_error()` 記錄原因 → MainLoop 的 `_report_bg_failure()` 與 OCR Debug 的失敗分支讀得到「為什麼失敗」（先前讀到空字串而靜默返回）。回傳值語意、finally 的 UP 釋放路徑不變；取消不算失敗。
- **R-3**：`gui/09_ocr_debug.py` 主循環啟動時以既有 generation id 作廢在途 click／key 驗證 worker，歸零 in-progress 旗標並還原按鈕文字與可用性；worker 於「送出輸入前」再確認一次主循環狀態。**已送出的 DOWN 不受阻斷**，必要的 UP 仍由後端層必定送出。

### R-5（MainLoop 啟動競態）

- `gui/06_gui_main.py` `InitWorker.run()` 的 `loop.start()` 先於 `finished.emit` → GUI 收到 finished 才 `set_run_active(True)`，兩者之間存在窗口，該窗口內 key 驗證 worker 仍可能送出一次按鍵。
- 修正：`_start_loop()` 在啟動 InitWorker **之前**先 `set_run_active(True)`（閘門先於 `loop.start()` 生效）；啟動失敗（`finished(False, …)` 或連執行緒都起不來）時恢復閘門。`set_run_active` 冪等，不會重複作廢同一批 worker。

### UX3-06（Click／Drag 目標選項與驗證改善）

**已實作（本次，commit 與本文同）**

- **P1-1 未知 target 事前擋下**：`click` 合法 target＝`text_center`/`custom`/`cursor`、`drag` 合法 target＝`text_center`/`custom`；白名單定義在 `core/rule_migration.py` 的 `STEP_TARGETS`（唯一事實來源，GUI／preflight 共用）。未知 target 由 preflight 產生 `unknown_click_target`／`unknown_drag_target` 問題鍵 → `status=blocked` → 規則在開始前就不執行，GUI 以 `exec_log.reason.*` 顯示可讀訊息（三語齊全）。**執行期 MainLoop 的防禦性 stop 保留不動**。
- **P1-2 dry-run 不再靜默略過**：`gui/run_controller.py` 的 click／drag 分支在未知 target 時寫入 `exec_log.detail.unknown_click_target`／`unknown_drag_target` 並標記 terminal（後續步驟標為不會執行），與引擎行為一致；preflight 啟用時則顯示 BLOCKED header，不假裝成功。
- **P1-3 Drag 專屬文案**：Drag 表單不再沿用 Click 的「點擊辨識目標／點擊指定的比例座標位置」，改用 `step_form.drag_target_*` 系列（明確寫出「拖曳起點」），並在 combo tooltip 說明「拖曳不支援游標目標（只有點擊有）」。target 的實際資料值與執行語意不變。
- **P2-1 cursor 目標停用抖動**：`target=cursor` 時 `random_offset` 控制項停用（引擎該分支本就把抖動強制歸零）；切回 `text_center`/`custom` 恢復可編輯。**原值保留**（`_RawValue` 未 dirty 時回傳原值，停用不改值、不歸零）。
- **P2-3 custom 未設座標提示**：`target=custom` 且座標仍為 (0,0) 時顯示紅字提示；選到座標後自動隱藏。**純顯示**：不改變保存行為，既有 `custom_click_at_origin` 仍是 preflight 的「警告」而非阻擋問題。

**僅記錄事實（未改契約／未改行為）**

- **P2-4**：Drag 的 `hold_ms` 會被 normalize 寫入 params，但執行期 `_handle_drag` 從不讀取、GUI 也沒有此欄位 → 死欄位。詳見 ARCHITECTURE.md。
- **P2-5**：`validate_drag_endpoint` 要求終點各自落在 0~1（像素終點判 `invalid`），執行期 `_resolve_point` 只有「兩軸都 <=1」才走比例、否則當像素 → validator 比執行期嚴格。詳見 ARCHITECTURE.md。

**未完成（不得視為已驗證）**

- **真機 GUI 驗證未完成**：本次只以自動化測試（27 項）鎖定行為，未在真實遊戲／真實 GUI 上逐項點擊確認。
- **P2-2**（`custom_click_at_origin` warning 的消費端整合）與 **C2-2**（假 marker 清洗）本次明確排除，維持原狀。

### UX3-07（執行中「在跑什麼」可視化）

**已實作（本次，commit 與本文同）**

- **引擎執行目標**：`core/05_main_loop.py` 新增 `get_execution_target()`（O(1) 讀取），回報「本幀實際評估到的規則 + 步驟序號 + 群組」。**刻意與 `_last_active_rule_id`（最後觸發的規則）區分**：等待條件的規則不會觸發，只看 pointer 會誤以為程式沒在跑。背景規則不佔用此顯示位；`start()` 重置；規則已不存在時回 None。
- **狀態列**：`gui/06_gui_main.py` 狀態列新增 permanent widget `_exec_target_label`，顯示「執行中｜群組「X」｜規則「Y」｜步驟 n/m」。沿用既有 1 秒 `_status_timer` tick（由 `_update_rule_status()` 頂部呼叫），只在文字變化時 setText（效能紅線：增量、不重建、不新增高頻 timer）；停止後自動清空。滑鼠停留有白話說明。
- **群組選擇對話框**：`gui/group_selection_controller.py` 每個群組附加「（N 條啟用規則）」，啟動前就知道勾選會跑多少規則。
- **文案**：三語各 +4 鍵（`status.exec_target`／`status.exec_target.step`／`status.exec_target.tooltip`／`dialog.group_rule_count`）。

**未實作／明確排除**

- 主按鈕暫停態的圖示區分：開始／停止／繼續三態**文字**已可辨識，圖示屬低價值 enhancement。
- 新增 Pause 按鈕：沿用 F8／主按鈕三態語意（與原始稽核建議一致）。
- 並行群組的多條規則同時顯示：維持現行「顯示最後評估到的那條」，已於 tooltip（三語）與 ARCHITECTURE.md 說明。

### UX3-07-F1（語意回歸測試與生命週期修整）

**已實作（本次，commit 與本文同）**

- **端到端語意回歸**：新增 9 項走真實 `_process_rules → _run_rule → _handle_detect` 控制流程的測試，涵蓋「條件未成立（指標不推進、零輸入送出）」「觸發後目標切換」「多條規則依序等待」「零步驟規則」「並行群組現行語意」「preflight BLOCKED 規則不進入執行目標」；另補 `stop()`／規則重載的生命週期測試。以 **7 項突變測試**確認斷言有效。
- **生命週期修整**：`stop()` 之後清除 `_current_target`；`_load_rules()` 在「規則集真的被替換」時清除（載入失敗、規則被保留時**不清除**）。`_current_target` 仍是純顯示狀態，**不影響排程、觸發條件、on_fail 或 Stop 語意**。
- **文件**：ARCHITECTURE.md 補上生命週期與並行群組語意；UX_PHASE3_AUDIT.md／KNOWN_ISSUES.md 追加 UX3-07-F1 狀態。

**未完成（不得視為已驗證）**

- **真機 GUI 驗證未完成**：本次只以自動化測試（13 項，含 4 項突變測試）鎖定行為，未在真實遊戲／真實 GUI 上逐項確認狀態列文字與對話框排版。

### UX3-01／UX3-03（執行日誌定位 ＋ 啟動前檢核）

**已實作（本次，程式碼 commit `56b08aa`；主體早於本次，本次為深化）**

- **日誌帶定位資訊**：每筆 execution log entry 帶 `rule_id`／`task`／`step_idx`（0-based）→ 以 id 定位，同名規則不錯位。
- **點日誌即定位**：`ExecutionLogWidget` 以 `UserRole` 保存定位目標並發射 `locate_requested`；主視窗重用既有 `locate_rule_target()`（規則／步驟／跨任務；找不到時明講原因）。執行中點擊先記 pending、停止後自動定位。
- **BLOCKED 日誌可跳到出問題的那一步**：`_record_preflight_block()` 帶上第一個問題的步驟位置（規則層級問題維持 -1＝只定位規則）。
- **preflight 附加 `issues`**：`PreflightResult` 新增 `{key, step_idx, severity}`；`status`／`problems`／`warnings` 的內容與順序**完全不變**（既有呼叫端不受影響）。
- **啟動前檢核清單**：新增 `gui/start_check_dialog.py`，每一列都能定位到對應規則／步驟（取代原本只跳「第一個問題規則」的單一按鈕）。
- **檢核涵蓋背景監控規則**：背景規則不在任何群組但每幀都會評估 → 開始前就要讓使用者知道。
- **檢核以編輯器裡尚未存檔的步驟為準**：改壞一步驟還沒存檔就按開始，也會被擋（不再漏到執行期才 BLOCKED）。
- **三語**：每語 +8 鍵（`start.check_*`），移除已不再使用的 `start.hard_problems_msg`。
- **測試**：新增 `tests/test_ux3_03_start_check.py`（19 項：preflight issues 契約、BLOCKED 日誌步驟錨點、背景規則納入、未存檔編輯、對話框逐項定位、`_start_loop` 真的被擋下）。

**未改動（刻意）**

- Preflight 判定規則、型別驗證、BLOCKED 語意、執行期防禦、global stop／local on_fail、輸入 Release 語意、任務 JSON 格式**皆未改動**。
- 啟動前硬擋仍維持「整個任務不啟動」（比執行期「跳過該規則、群組繼續」嚴格）→ 屬既有產品語意，本次不變更。
- `_loader.load_sibling()` 與 canonical `rule_models` 載入路徑未動。

**未完成（不得視為已驗證）**

- **真機 GUI 驗證未完成**：本次以自動化測試（19 項）鎖定行為，未在真實遊戲／真實 GUI 上逐項點擊確認清單版面與定位手感。

## 明確延後（不在本次範圍）

- C-4：`_last_error` 跨執行緒歸屬（已以 C-5 限制重疊操作，不引入 per-operation error handle）
- C-6：`_notified_conditions` 在群組輪替期間未被評估時無法重新武裝
- C-7：Frida 輸入取消／Release 真機驗證
- C-9：pynput／hybrid 失敗回報語意；C-10：死碼清理；C-11：環境性 flaky
- R-2：後台失敗 log 可能大量累積，是否限流待產品決策
- R-4：Frida UP 失敗後規則可能於下一幀重試
- R-6：被作廢的驗證 worker 結果會被忽略 → 使用者只看到按鈕恢復，沒有「已中止」提示
- Drag Repair UI（needs_repair 修復流程、`validate_drag_endpoint` 消費端）→ C-2a-2
- 已汙染任務檔假 marker 的清洗（產品決策 keep：不動）
- UX3-06 明確排除項：P2-2（`custom_click_at_origin` warning 的消費端整合）、Click／Drag 表單大規模重構、全面統一驗證時機、新增 Drag cursor 支援；UX3-06 的真機 GUI 驗證亦未完成
- UX3-07 明確排除項：主按鈕暫停態圖示區分、新增 Pause 按鈕；UX3-07 的真機 GUI 驗證亦未完成
- 全員 disabled 並行群組的 stall（另案，C2-1）
- F-08 fingerprint 效能重構、F-09 `_preflight_last_fingerprint` 死欄位、F-10 死 binding、`RuleRunOutcome` 死成員
