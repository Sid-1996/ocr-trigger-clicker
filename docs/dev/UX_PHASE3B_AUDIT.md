# UX Phase 3B 測試閉環調查（READ-ONLY Audit）

> 調查日期：2026-11-10（以 HEAD 實際程式碼為準）
> 本文件僅為調查與設計方案，未修改任何正式程式碼。HTML 原型見 `devtools/ux_prototypes/phase3b/index.html`。

> **⚠ 基準說明（2026-11-10 驗收時補註）**
> 本調查的**基準 HEAD 是 `cb9000d`**，而目前 HEAD 已是 `c26b722`（`feat: 規則測試結果定位、測試生命週期守衛與取消、Debug 追加步驟回饋（Phase 3B）`）。
> 下文 §11「建議的下一個 Coding Agent 實作任務」等屬**設計提案時點的待辦**，其中已於 `c26b722` 實作者：
> - **B1（測試結果定位 half）** — 已實作：`gui/06_gui_main.py:_locate_from_test:8560`、`_test_log_html:734`、結果帶 `locate` 上下文。
> - **B2（UX3-08 Debug 靜默回饋）** — 已實作：`gui/09_ocr_debug.py:1263/1310`（`ocr_debug.step_sent`）、目標規則名標示 `1053`。
> - **B4（取消 + 狀態旗標）** — 已實作：`gui/run_controller.py:_cancel_event:85/127`、`gui/06_gui_main.py:_is_testing:8550/8937`。
> - **B3（UX3-05 sum gate 示範）** — **尚未實作**：`gui/run_controller.py:661` 的 `sum` 分支仍只回報 `test.sum_result`／`test.sum_no_roi`／`test.sum_no_number`，無 gate 條件示範。
> - **B5（F3/F4 定位化）** — 依原提案延後，未實作。
>
> 本文其餘內容為**設計調查紀錄**，保留作為實作依據與行號對照；引用前請以上述目前 HEAD 的實際程式碼為準。

---

## 1. 調查基準

| 項目 | 實測值 |
|---|---|
| Branch | `master` |
| HEAD | `cb9000d` — `feat: 執行日誌定位規則／步驟，啟動檢核改用 preflight` |
| `origin/master` | `cb9000d`（ahead/behind 0/0；調查前已核實，`git branch` = master） |
| 工作區 | `git status --porcelain` 空（調查開始前已乾淨；本輪新增僅本報告 + Phase 3B 原型，未 commit/push） |
| 前置 commit | `4fe24c8`（Phase 3 Audit 文件 + Phase 3 原型）、`cb9000d`（Phase 3A 實作） |
| Phase 3A 範圍 | `core/05_main_loop.py`（40 行）、`gui/06_gui_main.py`（152 行）、`gui/execution_log_widget.py`（78 行）、i18n 13 key ×3 語言、`tests/test_locate_rule_target.py`（347 行） |
| 本調查方法 | CodeGraph / 內建 Grep / Read 直接複核 + 三路 subagent 並行追蹤後主線抽查關鍵行號；未啟動真 GUI（見 §10） |

> **注意**：`gui/run_controller.py` **不在** `cb9000d` 的 8 個變更檔中。Phase 3A 未動測試（dry-run）控制器本身——這正是本階段的核心缺口（見 §4）。

---

## 2. 原始 Audit 定義及核對結果

任務書候選描述（UX3-08「測試結果與規則定位整合」、UX3-04「測試與執行狀態區分」、UX3-05「測試失敗後的恢復引導」）與原始 Audit 定義**不一致**。以下為原始定義原文核對：

### 2.1 UX3-04 — 規則測試無取消、結果不可回跳【P2 / 成本 S】

- **原始問題描述**（`UX_PHASE3_AUDIT.md:178`）：「規則測試無取消、結果不可回跳」。
- **實際操作情境**（`:182`）：使用者按「測試」後截圖/OCR 卡住或發現選錯視窗，想取消；或測試結果顯示某 step miss，想直接跳回去調參。
- **現況**（`:183`）：測試 dialog 只有 `Close`，無取消鈕；結果 log 行不可點；關閉後回到同一規則編輯頁但不定位到出錯 step。
- **原始程式碼證據**：`run_controller.py:on_test_rule:85-151`（背景執行緒 `_run_rule_test:155-170`，無 cancel flag）；`_show_test_result:8519-8571`（僅 Close）；結果 log 行 `test.detect_hit/miss` 等無 click 處理。
- **嚴重程度與使用者影響**：P2。測試等待不可控；診斷結果到設定之間仍需手動對應步數（`:184`）。
- **原始建議方向**（`:186`）：測試 dialog 加「取消測試」按鈕（取消旗標 + 等待執行緒收尾，不碰進行中輸入——dry-run 本就不送輸入）；結果 log 行可點，關 dialog 並跳到對應 step 表單。
- **核對結果**：定義成立。HEAD 現況與 Audit 記載一致（行號經漂移，現況 `gui/06_gui_main.py:8535-8587`；見 §4.1）。Phase 3A **未解決**——測試結果 dialog 未接定位。

### 2.2 UX3-05 — Sum 閘門在 dry-run 不評估【P2 / 成本 S】

- **原始問題描述**（`UX_PHASE3_AUDIT.md:192`）：「Sum 閘門在 dry-run 不評估」。
- **實際操作情境**（`:196`）：使用者設定數字加總閘門（operator/value/wait），按測試顯示總和看起來正常就啟動，正式執行時閘門逾時/不符。
- **現況**（`:197`）：dry-run 的 sum 分支只加總回報，不評估 gate/operator/value/timeout/on_fail，與引擎語意不一致。
- **原始程式碼證據**：`gui/run_controller.py:615-647` vs `core/05_main_loop.py:1274-1363`（等待中不走 on_fail、穩定值才比對）。
- **嚴重程度**：P2。測試給出過度樂觀信心；閘門等待語意完全未覆蓋（`:198`）。
- **原始建議方向**（`:200`）：dry-run sum 分支補上 gate 評估——顯示「會等多久、等到什麼條件、目前加總是否已符合」，不符時標示將如何處理（stop/advance/notify）；不改變引擎等待語意；需明示為「條件判斷示範」而非實際等待（`:202`）。
- **核對結果**：定義成立。HEAD `run_controller.py:615-647` sum 分支仍只回報 `test.sum_result/sum_no_roi/sum_no_number`，無 gate 評估（§4.1）。Phase 3A **未解決**（`cb9000d` 未動此檔；僅 `tests/test_number_sum.py` 的 6 行調整與 preflight 間接相關）。

### 2.3 UX3-08 — OCR Debug「追加步驟」在無目前規則時靜默無反應【P2 / 成本 S】

- **原始問題描述**（`UX_PHASE3_AUDIT.md:234`）：「OCR Debug『追加步驟』在無目前規則時靜默無反應」。
- **實際操作情境**（`:238`）：使用者在 OCR Debug 辨識出文字，按「新增步驟」想追加到規則，但主視窗尚未選任何規則。
- **現況**（`:239`）：`_on_debug_step_requested` / `_on_debug_template_step_requested` 取不到目前規則時直接 `return`，無任何提示；使用者以為按鈕壞掉。
- **原始程式碼證據**：Audit 記載 `06_gui_main.py:8660-8662`、`8766-8768`（`if rule is None: return`，HEAD 已漂移為 `8677-8678`、`8783-8784`）；對比新規則路徑 `8590-8656` 有完整回饋（現況 `_on_debug_rule_requested:8606`）。
- **嚴重程度**：P2。無回饋的靜默失敗；「追加到哪條」目標在 Debug 面板不可見（`:240`）。
- **原始建議方向**（`:242`）：無目前規則時彈白話提示並提供「改為建立新規則」選項；Debug 面板頂部顯示目前目標規則名（唯讀標示）。
- **核對結果**：定義成立。但**任務書將其描述為「測試結果與規則定位整合」屬誤標**——UX3-08 與測試結果 dialog 無關，是 OCR Debug 建立步驟的分支提示問題。Phase 3A **未解決**（同上，`cb9000d` 未動 `_on_debug_*`）。

### 2.4 另附：與本階段相關但非候選的原始定義

| ID | 定義 | 與本階段關係 |
|---|---|---|
| UX3-01 | 執行日誌無法定位規則/步驟（UX-E2）【P1】 | **Phase 3A 已解決**（`execution_log_widget.py:22,164-179` + `locate_rule_target:9227`）。本階段應**重用**，不重做。 |
| UX3-03 | 啟動前檢核與執行期 preflight 落差【P1】 | **Phase 3A 已解決**（`_rule_hard_problems:8429` 改走 `rule_preflight`）。測試前置閘同時受惠（`run_controller.py:92`）。本階段只需處理其「測試 dialog 側無定位」殘留。 |

### 2.5 問題矩陣（原始定義 → 現況）

| 問題 | 原始 Audit 定義 | 現況（HEAD cb9000d） | 使用者影響 | 是否已部分解決 |
|---|---|---|---|---|
| UX3-04 | 測試無取消、結果不可回跳 | 仍存在：`_show_test_result:8535` 僅 Close；結果 dict 無 rule_id/step_idx；執行緒無 cancel | 卡住時無法中斷；miss 後需手找 step | **否**（Phase 3A 未動 run_controller） |
| UX3-05 | Sum 閘門 dry-run 不評估 | 仍存在：`run_controller.py:615-647` 只回報總和 | 測好跑了才發現閘門問題 | **否**（Phase 3A 未動 run_controller） |
| UX3-08 | Debug 追加步驟靜默無反應 | 仍存在：`8677-8678`、`8783-8784` 靜默 return | 以為按鈕壞掉；不知落到哪條規則 | **否**（Phase 3A 未動 `_on_debug_*`） |
| 任務書新增「狀態區分」 | 非原始 Audit 編號 | 測試中僅按鈕改字；硬擋彈窗與正式執行共用問題文字但標題/按鈕不同；無 `_is_testing` 旗標（見 §6） | 測試/正式混淆風險低，但「測試未回來又按開始」可鑽 | **部分**（Phase 3A 的硬擋定位已区分；測試態未收斂） |
| 任務書新增「失敗恢復引導」 | 非原始 Audit 編號 | 依失敗類型而定（見 §7 矩陣）：部分可定位、部分僅 log | 需手動對應步數 | **否**（定位機制存在但測試結果未接） |

> 結論：三個原始 UX 編號**全部未解**，且任務書的兩個新方向（狀態區分、恢復引導）是 UX3-04 的自然延伸，非第四個獨立問題。本階段不應拆三個 Phase（見 §9）。

---

## 3. 重要測試流程的完整呼叫鏈

「測試」在專案中是 **7 種不同語意**，不可互換（呼叫鏈終點與資料形狀完全不同）：

| # | 流程 | 入口（file:line） | 執行緒模型 | 結果結構 | 攜帶定位？ |
|---|---|---|---|---|---|
| F1 | 規則整條 dry-run 測試 | `06_gui_main.py:6127` 按鈕 → `run_controller.py:85 on_test_rule` | GUI 截圖 + `threading.Thread(daemon=True):150-151` | `{"image","log","log_dead"}`（`:163-167`） | **否**（見下） |
| F2 | MatchImage 步驟內嵌「比較圖片」 | `06_gui_main.py:1375` → `1750 _img_compare_match` | **同步 GUI 執行緒** | 表單內 label 文字（`1745 _show_compare_result`） | 間接（render 在 step 表單內） |
| F3 | OCR Debug 截圖+OCR | `09_ocr_debug.py:802 _take_snapshot` → `838` thread | GUI 截圖 + daemon thread | `list[OcrResult]` 經 `_OcrSignals:463-467` | 否（僅 window_title） |
| F4 | OCR Debug 點擊/按鍵後台輸入測試 | `09:542/553` 按鈕 → `1574/1615` → `1659 _start_backend_test` | `Thread(daemon=False):1663` → `_run_backend_test:1787` → 觀察 worker | `BackendTestResult:163` + `VisualAnalysis:119` + `TextDiffAnalysis:134` | 否（snapshot `_OcrTarget`，非規則引用） |
| F5 | Debug 建立新規則/追加步驟 | `09:473-476` 四訊號 → `06:8606/8674/8710/8780` | GUI 同步 | 無結果（直接建立 `Rule/Step` 落盤） | 請求無 id（隱式 `_selected_rule_id`） |
| F6 | 啟動前硬問題檢查（預檢，非測試但共窗） | `06:8845 _start_loop` → `8429 _rule_hard_problems` | GUI 同步 | `list[str]` + 彈窗 | **是**（Phase 3A：`first_problem_rule_id` → `locate_rule_target:8917`） |
| F7 | 啟動時後台黑畫面探測截圖 | `06:8926`（`_start_loop` 內，frida 模式） | GUI 同步 | `is_black_capture` 布林 → Yes/No 彈窗 | 否（作用域為整視窗模式） |
| — | ROI/點擊/模板拾取（明確**非測試**） | `13/07/14_gui_*` overlay | 前景同步 | 比例座標 | 否（與測試無關，列此防混淆） |

### F1 規則 dry-run（主線，§「A」目標的重點）

```
使用者按「測試」 _edit_test_btn（06:6127，初始 Enabled=False/Visible=False）
→ _show_rule_detail 有規則才顯示/啟用（06:7643-7654）
→ clicked → _test_ctrl.on_test_rule（06:6246 → run_controller.py:85）
  1. _save_current_rule → _get_current_rule（live object，非 copy，06:7535-7539）
  2. _rule_hard_problems（06:8429）攔截 → QMessageBox.warning + return（:92-95）
     ※ 此點在按鈕 disable 之前，按鈕不會卡住
  3. 無 window_title → warning + return（:96-99）
  4. disable +「測試中…」+ processEvents（:100-102）※ 唯一 in-flight 擋
  5. 截幀（GUI 執行緒）：非 pynput 直接 capture_frame（:110-111）；
     pynput 縮窗→啟動目標視窗→mss→失敗 fallback capture_window_content+黑邊填補（:112-137）
  6. img=None → 恢復按鈕 + warning + return（:139-144）
  7. 黑圖+非 admin → 累積 warn 字串（:145-148，靜默寫 log 不彈窗）
  8. Thread(target=_run_rule_test).start() + return（:150-151）※ 無 handle、無 token
→ _run_rule_test（:155-170）：_run_dry_run → _draw_test_annotations（複本）→ emit
   失敗 → {"error": T("test.exception")}（:168-169）
→ test_done_signal.emit（:170）※ WorkerSignals:06:5053，queued 連接
→ _show_test_result（06:8535-8587）：先恢復按鈕（:8536-8537）
   error → warning + return；否則 modal 對話框（標題=首行、圖片 scroll、log QTextEdit、僅 Close，:8552-8587）
→ 使用者後續：只能 Close 後重按「測試」全跑一次（無 locate/re-test/edit 按鈕）
```

- **結果資料結構**：成功恰 `{"image","log","log_dead"}`（`:163-167`）；`log_dead` 為 `log.split("\n")` 的行號索引（含兩處 +1 位移：`:832-834` legend 插入、`:159-161` warn 插入）。`markers`（`step: idx+1`、形狀/座標，`:840-943`）僅供畫圖不進結果。**無 rule_id / step_idx / task / run token**——step 身分只剩 log 行首 `[idx]` 與圖上數字。
- **執行緒與競態**：
  1. 無 in-flight 守衛：清空選取或 `_update_edit_enabled:9352` 會**重啟用**測試鈕，可開第二執行緒 → 第二 dialog（`_show_rule_detail:7653-7654` 無條件 Enabled(True)）。
  2. 結果與目前選取無關：切任務/規則後 worker 的舊結果照彈，且無過期提示。
  3. Worker 讀 live `rule` 物件 + 讀 `win._window_combo/_current_task/_rules`（`:220-223,684-689,667`），與 GUI 執行緒無同步。
  4. `dead_lines` 續數靠裸索引 +1 的脆弱算術，新增 insert 易錯位。
- **失敗訊息來源五層**：pre-capture gate（`_rule_hard_problems`）；dry-run 內 BLOCKED 早退（`:225-237`，delivered as 正常 success dict）；逐 step `T("test.*")`（`:254-825`）；worker exception（`:168-169`）；截圖失敗（`:143`）。

### F2 MatchImage 內嵌比較（同步、表單內）

`1375` 按鈕 → `_img_compare_match:1750`：讀**即時表單值**（threshold 為 spin 即時值非已儲存值，`:1765`）→ 同步 `capture_frame` → `match_template:1849`（miss 再呼 `threshold=0.01` 求 `best_below`，`:1876-1887`）→ `_show_compare_result:1745` 寫 label（綠命中/紅 + 尺度診斷 + 顏色拒絕註記 + 黑圖 admin 警告，`:1796-1961`）。**無 worker、無 race**；但測試結果（draft threshold）與存檔值可不一致——使用者調完不存即测。

### F3 OCR 截圖測試（`09_ocr_debug.py`）

`711` 按鈕 → `_take_snapshot:802`（GUI 截圖、清表、重置 `_selected_index=-1`、request_id+1）→ daemon thread `_do_ocr:847` → `_on_ocr_done:880`（stale 檢查 `request_id != _ocr_request_id` 後回填）。**僅防回填、不取消 worker**（註解 `498-500`）。結果僅 window_title + timestamp 可歸因，無規則上下文。

### F4 點擊/按鍵後台輸入測試（`09_ocr_debug.py`，兩階段）

`542/553` → `_on_click_test:1574` / `_on_key_test:1615`（建 `BackendTestRequest:149`，generation=request_id+1）→ `_start_backend_test:1659`（每 kind 一個 cancel Event `1660-1661`，`Thread(daemon=False):1663`）→ `_run_backend_test:1787`（worker 內先截 before 幀 → `_dispatch_backend_test:1817` 送輸入）→ emit `backend_test_done` → `_on_backend_test_done:1976`（stale 檢查 + `_render_diagnostic_result:1989` 三行摘要）→ 觀察階段（click `_click_verify_worker:1297` / key `_key_observation_worker:2140`）→ `_finish_test_ui:2119`。

- **三層狀態分明**：`BackendStatus`（注入成功否）/ `VisualAnalysis.status`（像素變化）/ `TextDiffAnalysis.status`（文字變化）分開渲染（`:1989-2013`），legacy `still/no_response` 不覆蓋 Backend（`:1568-1570` 明示）。
- **保護機制**：generation 三 id（OCR/click/key `500-502`）、per-kind cancel Event（`503`）、`_run_active:516`（Event，`set_run_active:1045-1067` 先 set 全 cancel 再 set `_run_active`，再 `_abort_running_verifications:1069` 僅作廢不取消）；主循環期間按鈕 disable（`1101-1113`）+ worker 內多點 `_verify_input_blocked:1093` 檢查。R-1/R-3/R-5 已修（見 `KNOWN_ISSUES.md:31-40`）。
- **不攜帶 rule_id**：target 是 `_OcrTarget`（文字+框），非規則引用。後台失敗僅 frida 模式 emit `bg_inject_fail:478` → `_on_debug_bg_fail:06:9141`（一次/程序）。

### F5 Debug 建立（UX3-08）

`09:473-476` 四訊號（payload 均**無 rule_id/task**，`:1172-1281`）→ `06:8606 _on_debug_rule_requested`（`_ensure_steps_committed:8609` 失敗靜默 return；成功建 `Rule(uuid)` + detect+click、flush-save、切回規則頁）／`8674 _on_debug_step_requested`（`_get_current_rule is None → return:8677-8678` 靜默；另有 `_ensure_steps_committed:8679` 靜默分支）／`8710 _on_debug_template_requested`／`8780 _on_debug_template_step_requested`（`rule is None → return:8783-8784` 靜默，**且缺 `_ensure_steps_committed`**——半填 Drag 表單可能被覆寫遺失）。

### F6 正式執行啟動（對照組，已接 Phase 3A）

`F8/_btn_toggle` → `_toggle_start:8831` → `_start_loop:8845` → 硬問題彙總 → Warning 彈窗 +「定位到問題規則」按鈕（`8911-8917`，僅首條問題規則）→ 黑圖探測（F7）→ `_is_starting=True` + InitWorker → `_on_init_finished:9023` → 執行中（exec log 500ms poll `9210-9215`、執行中點擊日誌 → `_pending_locate:9242`，停止後自動 `locate_rule_target:9078-9081`）。

---

## 4. Phase 3A 定位機制的重用性分析

### 4.1 現況機制（`cb9000d`）

- **契約**：`locate_rule_target(task_name, rule_id, step_idx=None, rule_name="") -> bool`（`06:9227-9310`）。只以 `rule_id` 比對（`:9264`），絕不以名猜測；`step_idx` 為 0-based 位置（Step 無 id），`<0/None` 只定位規則（`:9289`）；執行中記 `_pending_locate`、狀態條提示「執行中先記錄：停止後將定位到…」（`:9241-9246` + i18n `locate.pending_after_stop`）；跨任務走既有切換；展開表單半填被拒 → 中止定位不丟輸入（`:9250-9252,9285-9288`）；已刪除/不存在明示訊息（`locate.*` 8 個 key，i18n `zh_TW.json:1041-1049`）。
- **已有消費者**：`ExecutionLogWidget.locate_requested`（`execution_log_widget.py:22`）→ `_on_exec_log_locate:9223`；啟動硬問題彈窗「定位到問題規則」（`:8911-8917`）。`ExecutionLogWidget` 每列 rule 欄存 `UserRole=(task, rule_id, locate_step, rule_name)`（`:126-145`），`completed/preflight/background` 行強制 `-1` 只定位規則（`:130-134`）；舊日誌發空 id 由主窗提示（`:5242-5249` 對應文案 `old_log_no_id`）；增量附加不破效能紅線（`:81-98`，prefix-keep + 滑動對齊）。
- **測試 `tests/test_locate_rule_target.py`（347 行）**：同名不錯位、不同群組區分、step 消失、rule 已刪、舊日誌空 id、任務不存在、跨任務、半填拒絕、pending 語意——覆蓋完整。

### 4.2 對六個問題的回答

1. **測試流程目前是否保留足夠定位上下文？**
   **僅 F1（dry-run）保留 `rule` 物件參考 + 每 log 行 `[idx]`，但結果 dict 無 rule_id/step_idx/task**。F2 在 step 表單內（上下文可見，間接足夠）。F3/F4 皆無 rule 上下文（F4 僅 snapshot-local `_OcrTarget`）。F5 隱式 `_selected_rule_id`，請求本身無 id。
2. **哪些可直接重用？**
   - **F1 dry-run：直接重用**——結果已有 `rule.id` 可攜出（`win._get_current_rule().id`），log 行 `[idx]` → `step_idx=idx-1`，task 用 `win._current_task`。呼叫 `locate_rule_target(task, rule_id, step_idx, rule_name)` 即可，零新抽象。
   - **F6 啟動硬問題：已重用**（Phase 3A 上線）。
   - **F2 內嵌：不需重用**（已在 step 表單內）。
3. **哪些缺少 rule_id / step_idx？**
   - F1 結果 dict（需補）；F3（設計上無規則可定位——應改為「顯示目標規則名」而非定位；屬 UX3-08 同批）。
   - F4（設計上 input 測試針對視窗非規則——不應硬塞 rule_id）。
   - F5 請求（隱式，改為顯示/提示即可，不需回填 id）。
4. **是否需擴充結果資料結構？**
   **是，但最小擴充**：`_run_rule_test` 結果 dict 加 `rule_id`、`task`、`rule_name`（三個 scalar）即可；log 行定位以 `[idx]` 解析或在 `_test_log_html` 層攜帶 `data-step` 屬性。**不需動 `PreflightResult`、不需動任務 JSON、不需新 signal**（dialog 內 `locate` 按鈕直接呼主窗方法或送 `locate_requested` 同一訊號）。
5. **能否透過 GUI 層最小修改完成？**
   **F1 + F5 均可**（GUI only）。F1 改動在 `run_controller.py`（GUI 層）+ `_show_test_result`（GUI）；不碰 `core/`（dry-run 本就圖像模擬，不送輸入）。F5 改動在 `06_gui_main.py` 兩個 handler + Debug 面板顯示標籤（GUI only）。
6. **Core 修改需求？**
   **無。** Sum gate 評估（UX3-05）是 `run_controller.py:615-647` 的 GUI 層推論（讀 `Step.params` 的 `gate/operator/value/wait` 與引擎 `05_main_loop.py:1274-1363` 語意對齊，屬「條件示範」非等待實作），不改引擎。任何看起來像需要 Core 的項目都違反「dry-run 不送輸入」原則，應保持零 Core 變更——這是本階段與 Phase 3A 相同的硬約束。

### 4.3 注意事項

- **不可為測試複製一套定位**：正確做法是「dialog 按鈕直呼 `locate_rule_target`」或「dialog 內 log 行點擊發 `locate_requested` 同一訊號」。`ExecutionLogWidget` 的 UserRole 存法是模板，不必再包一層。
- **`_run_dry_run` 跨執行緒讀 GUI 狀態**（`:220-223`）是既有檔病毒（見 §6），本階段只在結果 dict 加標量 id，不新增共享可變狀態，避免擴大競態。

---

## 5. 測試狀態區分調查（任務書 D）

### 5.1 使用者實際看到的區分（HEAD 實證）

| 表面 | 測試中 | 啟動前預檢 | 正式執行中 |
|---|---|---|---|
| 測試鈕 | `測試中…` + disable（`run_controller.py:100-101`，含 `processEvents` 確保重繪） | 正常（gate 在 disable 之前 return） | disable（`_update_edit_enabled:9352`） |
| 主按鈕 `_btn_toggle` | **不變（仍顯示「開始」）** | 正常 | 初始化 disabled（`8952`）→「停止」/「繼續」 |
| 狀態列 | **不寫任何訊息** | 非阻擋 hint 8s | 初始化→偵測中→停止/錯誤 |
| 執行日誌 | 無（modal 內 log） | 無 | 500ms poll + 可見 |
| Debug 測試鈕 | 不受影響（F3/F4 在 Debug 頁） | 非預檢 | disable via `_run_active:1045` + 按鈕同步（`:1101-1113`） |
| 按鈕 recovery | 完成/error/截圖失敗三路都先恢復（`8536-8537`、`141-142`） | — | Init 失敗恢復（`9051-9059`） |

**結論**：正式執行可辨識度高；**測試態僅靠按鈕文字，正式/測試共窗但無全域旗標**（無 `_is_testing`）。硬問題彈窗測試與正式共用 `exec_log.reason.*` 文案，僅標題不同（測試用 `test.title`，正式用 `dialog.warning`），且正式獨有「定位到問題規則」按鈕、測試無（`run_controller.py:93-95` vs `06:8905-8917`）——文案相同帶輕微混淆但會隨本階段的定位按鈕再拉開。

### 5.2 特別檢查結果

- **測試期間被誤認為正式執行**：機率低（編輯區仍啟用、主按鈕仍「開始」、無執行日誌 poll）。但 `on_test_rule` 的 pynput 截幀會把主窗最小化（`:113-137`），且是**同步阻塞**——短暫視覺斷裂易被誤解為主程式切走。
- **共用易混狀態/提示**：硬問題文案重複（見上）；`test.title` vs `dialog.warning` 標題差異是唯一民間防線。
- **取消/失敗/成功後恢復**：三路皆恢復（§5.1 表）。**但無任何「測試中」全域旗標**——`_show_rule_detail` 在測試執行中若被觸發（如選別規則），會把測試鈕重啟用（`7653-7654`），使用者可在第一次測試未結束前按第二次。亦無「結果過期」提示（見 §6 競態 #2）。
- **測試結果未回來又開始下一次操作**：三個真實路徑——(a) 選別規則重啟用測試鈕 → 第二執行緒 → 兩 dialog 排隊；(b) 按 F8/開始在測試 worker 進行中 → `test_done_signal` 仍彈窗蓋在正式執行上（modal 不擋 loop，loop 自有執行緒不受 `dialog.exec()` 限制）；(c) 測試工簽(pynput 截幀階段) 與 `_start_loop` 同步跑 → 搶前景/截圖來源。F4 的 Debug 測試有完整的 `_run_active` 守衛，**F1 的 dry-run 沒有**——這是本階段應補的唯一狀態旗標（`_is_testing` + 開測試時阻擋 start、跑 start 前先刷掉在途測試，跟 F4 相同的 `set_run_active` 模式但輕得多）。

---

## 6. 測試失敗後的恢復引導調查（任務書 E）

代表性場景 × 使用者下一動作 × 資料來源：

| # | 場景 | 現況訊息（來源層） | 使用者能做什麼（現況） | 應補引導（可執行） | 屬類 |
|---|---|---|---|---|---|
| E1 | 規則/步驟設定錯誤（空 detect / 未知 type / sum 閘門 ROI 等） | 測試前彈窗列 reason（`_rule_hard_problems:8434`）；dry-run 內 BLOCKED header（`run_controller.py:233`） | 列文字但**不可點**；需手在樹上找規則/步驟 | dialog 行內「定位到第 N 步」 → `locate_rule_target(rule_id, step_idx)`；資料：F1 結果 id + `[idx]` | 可直接定位+修正 |
| E2 | OCR 找不到目標（detect/template/compare miss） | log 含 mode/threshold/best%/Top5 + on_fail hint（`:334-367,765-822`），圖上紅框 | 可調文字/ROI/門檻；但需從 `[idx]` 手對步 | miss 行「在編輯器開第 N 步」+ 圖框可點開診斷（Top5、閾值）；資料：markers/log 現有 | 可直接定位+修正 |
| E3 | 輸入後端不可用/操作失敗（frida 注入失敗） | F4：`FAILED` + `_error_for_backend_failure`（`09:1970-1973`）+ 一次性 `bg_inject_fail` 對話框（`06:9141`，切前景選項）；F1 dry-run 用模擬故**不覆蓋真輸入**（已知限制，`KNOWN_ISSUES C-9`） | 切前景/保持後台二選一；關 Debug 面板 | F1 dialog 應**明示「此測試不送出真輸入」**，避免誤解；F4 已有診斷三行 + 詳細切頁（`1989-2105`）應加「前往設定/規則」連結 | 需檢查環境/權限 |
| E4 | 座標/拖曳端點問題（legacy/非法終點） | dry-run `drag_end_invalid` + terminal（`:439-442`，經 `test_preview_fate.py:116` 鎖定）；`_migration` 無 GUI 修復（UX3-02，未解） | 手改 JSON 或重建（無 GUI 路徑） | 本階段僅做「定位到拖曳步驟並顯示診斷」；修復 UI 是 UX3-02 的事，本階段不僭越，但定位是本階段的活 | 可定位+修正（修復面除外） |
| E5 | 使用者取消測試 | **無取消功能**（F1）；F4 有 cancel Event 但結果僅靜默丟棄 `R-6` | 只能等或關程式 | F1 加「取消測試」：旗標 + 等收尾（dry-run 不送輸入故安全）；取消後按鈕恢復 + 狀態列「測試已取消」；資料：`_test_cancel: Event`（F4 模式） | 可重新測試 |
| E6 | 無法歸因至規則/步驟（worker exception / 截圖失敗） | `test.exception`（`:168-169`）→ warning；`capture_failed`（`:143`） | 無定位資訊 | error 結果也帶 `rule_id/rule_name/task` → 至少「定位到規則」；截圖失敗明示選錯視窗可能（window_title）+ 重試 | 需診斷資訊 |

> 沒有單一「增加錯誤提示」解法——每列的出現時機、可執行按鈕、資料來源都不同（見 §8 最小修改方案）。

---

## 7. 設計提案（對照原型）

原型 `devtools/ux_prototypes/phase3b/index.html` 呈現三幅完整操作情境：

1. **測試結果與問題定位整合**：複刻 `_show_test_result` 對話框，log 行可點。「第 2 步未找到」→ 點定位 → 右側假規則樹/步驟列表高亮紅框跳轉（模擬 `locate_rule_target`）。假資料標示規則 `r-dry-run-demo`。
2. **測試/預檢/正式執行狀態區分**：狀態條 + 按鈕列，九態切換按鈕（測試中/預檢/正式執行中/完成/取消/子情況），清楚文案「此測試為模擬預覽，不送出操作」。
3. **失敗恢復引導**：六張情境卡（對應 §6 的 E1-E6），每卡有出現時機、按鈕（定位修正/重新測試/調整設定/檢查環境）、資料來源行。

假資料（行號）：`run_controller.py:291-367` 的 log 文式、`core/rule_preflight.py:89-206` 的 preflight reason 語意、`09_ocr_debug.py:1989-2105` 的三層診斷。

---

## 8. 建議實作順序與最小修改範圍

### 8.1 順序與合併判斷

| 批次 | 內容 | 依賴 | GUI/Core | 估計 |
|---|---|---|---|---|
| B1（先做） | **UX3-04 定位 half**：F1 結果加 `rule_id/task/rule_name`；dialog 內 log 行可點 + 「定位到步驟」按鈕直呼 `locate_rule_target`；`_test_log_html` 攜帶 `data-step`。**不碰 dialog 結構/取消** | 無（重用 Phase 3A 契約） | GUI only | S |
| B2（同批） | **UX3-08**：兩 handler 的靜默 return 改白話提示 + 對話「改為建立新規則」；Debug 面板頂部目標規則名唯讀標示（含 F5 追加路徑的 `_ensure_steps_committed` 缺失補齊——template 步進缺 commit 是靜默遺失輸入，補上） | 無 | GUI only | S |
| B3（同批） | **UX3-05 sum gate 示範**：`run_controller.py:615-647` 加 gate 評估三行（「會等多久、等什麼條件、目前加總是否符合」+ 不符處理 on_fail hint），文案明示「示範非實際等待」 | B1 的結果包裝（同檔） | GUI only | S |
| B4（後） | **UX3-04 取消 + 狀態旗標**：`_is_testing` + cancel Event；`on_test_rule` 入口檢查 loop 執行中→拒；`_start_loop` 開始前檢查 `_is_testing`→拒並提示；取消後狀態列訊息 | B1（結果才有 token 才有守） | GUI only | S |
| B5（延後） | **F3/F4 定位化**：F3 顯示目標規則名（非定位，因設計無規則上下文）；F4 診斷層加「前往設定/規則」深連結——价值低（power user 領會），可與 UX3-07 同批 | — | GUI only | S（可延後） |

**合併結論**：
- UX3-04（定位 half）+ UX3-05 + UX3-08 **三合一**：皆在「測試閉環」同一表層面（測試 dialog + Debug 面板），同資料形狀（id 攜帶→定位），同 GUI 層集。**不需三個 Phase**，也不需三個 PR（最多拆兩批：B1-B3 同批、B4 後續）。
- UX3-04 取消與定位拆開：定位是 Pure GUI 展示（低風險），取消涉及執行緒收尾與 `_is_testing` 旗標（需仔細設計竞态），不同風險等級。
- 「狀態區分」（任務書新方向）與「恢復引導」（任務書新方向）**不是新編號**，分別是 UX3-04 取消 half 的前半段（狀態旗標）與定位 half 的完整體現（文案+按鈕）。不另立項目。

### 8.2 最小修改方案（每項列文件/函式/影響/測試/風險）

#### B1 — F1 結果攜帶定位 + dialog 定位（UX3-04 定位 half）

| 項目 | 內容 |
|---|---|
| 檔案 | `gui/run_controller.py`（`_run_rule_test:155-170`）；`gui/06_gui_main.py`（`_show_test_result:8535-8587`、`_test_log_html:734-748`） |
| 函式/類別 | `TestRunController._run_rule_test`；`MainWindow._show_test_result`；`_test_log_html` |
| 修改 | 結果 dict 加 `rule_id/task/rule_name`（caller 已有 `rule` 物件）；dialog 加「定位到第 N 步」按鈕（首個 miss 步驟）/ log 行點擊 → `locate_rule_target(task, rule_id, step_idx, rule_name)`；`_test_log_html` 每行攜帶 `data-step="idx"` |
| 既有呼叫影響 | 新增 dict key（`_show_test_result` 用 `.get()` 取，向後相容）；log HTML 加屬性（`test_preview_fate.py:test_log_html_escapes_and_strikes` 仍通過——需確認 `<br>` join 不變） |
| 測試 | 新增 `test_run_locate.py`：設定假 `rule.id/task`，斷言 `test_done_signal` payload 三 key；`_test_log_html` 含 `data-step`；dialog 按鈕呼叫 `locate_rule_target`（offscreen Qt + mock） |
| 風險 | 低。**嚴禁**：不改 BLOCKED 語意（`test.rule_blocked_header`）；不動 `dead_lines` 索引算術 |

#### B2 — UX3-08 靜默分支補提示（F5）

| 項目 | 內容 |
|---|---|
| 檔案 | `gui/06_gui_main.py`（`_on_debug_step_requested:8674`、`_on_debug_template_step_requested:8780`）；`gui/09_ocr_debug.py`（面板頂部目標標示） |
| 修改 | `rule is None` 分支：status-bar 白話提示 + `QMessageBox`「改為建立新規則」選項（複用新規則路徑的 payload）；panel 頂部 `QLabel` 顯示目前目標規則名（`set_has_active_rule:1041` 已有狀態，`_update_step_btn_state:1115` 已知規則）；template 步進路徑補 `_ensure_steps_committed()` |
| 既有影響 | 僅分支提示；新規則 payload 格式不變 |
| 測試 | 新增 handler 單測（無目前規則 → 彈提示不拋；有規則 → 同舊行為）；panel label 顯示名（offscreen） |
| 風險 | 極低。**禁改**：新規則/追加的資料落點規則（群組 fallback `8657-8663` 不動） |

#### B3 — UX3-05 sum gate 示範（同上 B1 結果包裝）

| 項目 | 內容 |
|---|---|
| 檔案 | `gui/run_controller.py`（`:615-647` sum 分支）；i18n `zh_TW/en/ja.json` 3 key |
| 修改 | sum 分支讀 `params.gate/operator/value/wait`（若有）→ 斷言式回報：當前總和與條件比較 + 「將等待/已符合/不符按 on_fail 處理」；明示「示範」用語 |
| 既有影響 | 僅 log 多行；`markers` 綠/紅判定不變；不改引擎 `05_main_loop.py:1274-1363` |
| 測試 | 擴充 `test_preview_fate.py` 模式：sum+gate 已符合/不符/未設 gate 三例 |
| 風險 | 低。**嚴禁**：把「等待」做成真睡（引擎等待語意不變）；「示範」與「實際執行結果」文案不得混淆 |

#### B4 — 取消 + `_is_testing`（UX3-04 取消 half）

| 項目 | 內容 |
|---|---|
| 檔案 | `gui/run_controller.py`（`on_test_rule:85-151`、`_run_rule_test:155-170`）；`gui/06_gui_main.py`（`_show_test_result:8535`、`_toggle_start:8831`/`_start_loop:8845` 守衛） |
| 修改 | `_test_cancel: threading.Event`；`on_test_rule` 起手若 `_is_testing` 或 loop 執行中 → warning 拒；`_start_loop` 起手若 `_is_testing` → 拒並提示「測試中…」；`_run_rule_test` 在步驟間檢查 cancel（不中斷單次 OCR）；`_show_test_result` 按 cancel 分支顯示「測試已取消」 |
| 既有影響 | 新增主窗屬性 `_is_testing`（初始 False），不改 loop 生命週期 |
| 測試 | mock thread + Event 的 on/off 單測（offscreen） |
| 風險 | 中。**禁引入大型 Cancellation Framework**（原則 6）；**DOWN/UP 不受影響**（dry-run 本就不送輸入）；注意與 `_show_rule_detail:7653` 重啟用的竞态（建議該處改為 `setEnabled(not self._is_testing)`） |

### 8.3 明確不做

- 不動 `_loader.py`、不重定義 `Rule/Step`、不放寬 `isinstance`（原則 1-3）。
- 不混淆 Global Stop 與 local `on_fail`（原則 4）——sum gate 示範只讀 on_fail 文案不觸發分派。
- 不破壞 DOWN 後 UP/Release（原則 5）——dry-run 不送輸入，取消只停模擬。
- 不引入大型 Cancellation Framework（原則 6）；不做無關重構（原則 7）。
- F3/F4 不硬塞 rule_id（原則 9：不降低驗證標準；F4 的三層狀態屬注入層證據，非規則診斷）。

---

## 9. HTML 原型索引

| 原型區段 | 用途 | 進入點 |
|---|---|---|
| §1 測試結果 dialog（含可點定位） | UX3-04 定位 half + UX3-05：miss 行點定位跳假規則樹、sum gate 三行示範、BLOCKED 行定位 | `devtools/ux_prototypes/phase3b/index.html#sec-locate` |
| §2 狀態區分 | 九態切換 + 狀態列/主按鈕/測試鈕三 surface 對照 | `#sec-status` |
| §3 失敗恢復引導 | E1-E6 六情境卡（出現時機、按鈕、資料來源） | `#sec-recovery` |
| 索引導覽 | 三段總覽 + 「現況行號對照」表 | `#sec-index` |

假資料（均以 `原型資料` 標示）僅示意互動，不連正式邏輯，瀏覽器直接開啟。

---

## 10. 已執行的驗證及結果 + 未驗證事項

### 已執行（本輪 READ-ONLY）

| 驗證 | 結果 |
|---|---|
| `git status --porcelain`（開始前） | 空（乾淨） |
| `git rev-parse HEAD` / `origin/master` | `cb9000d` / `cb9000d`，0/0 |
| Phase 3A 變更檔核對（`git show --stat 4fe24c8/cb9000d`） | `run_controller.py` 未動；`06_gui_main.py` + `execution_log_widget.py` 為核心 |
| UX3-04/05/08 原文核對（`UX_PHASE3_AUDIT.md:178-246`） | 三定義成立；任務書描述與原文 UX3-08 不符已標註 |
| F1-F7 呼叫鏈行號抽查（Read `run_controller.py:1-260,600-729`；`06:8429-8548,8600-8739,8770-8849,9200-9329,730-789`；Grep `09_ocr_debug.py` 關鍵行） | 與 subagent 回報一致 |
| 原型檔案寫入（新目錄，無覆蓋） | `devtools/ux_prototypes/phase3b/index.html` 建立 |
| 本報告（新檔） | `docs/dev/UX_PHASE3B_AUDIT.md` 建立（未 commit） |

### 尚未驗證（明示）

1. **未啟動真 GUI**：未實際點擊測試 dialog / 日誌行定位；行號以 Read/Grep 為據，未目視。
2. **未跑 pytest 全套**：本輪為 READ-ONLY 調查，未執行覆蓋；`test_locate_rule_target.py` 既有覆蓋未重跑以免衍生快取（可由實作批執行 `uv run python -m pytest --no-cov -q`）。
3. **取消收尾時間未量測**：`_run_rule_test` 的 cancel 檢查點粒度未知（單次 OCR 時間）；原型以概念展示。
4. **真機語意（F4/後台）**：後台輸入失敗體感、`_check_black_frame` 真時機未驗（Audit §10 同限）。
5. **Phase 3A 真機 3 項**：依任務書已全過，本輪未重跑。

---

## 11. 明確結論

- **Phase 3B 最值得先實作的範圍**：B1（F1 结果定位）+ B2（UX3-08）+ B3（UX3-05 sum 示範）。皆 GUI only、零 Core 變更、共用 Phase 3A 契約，因為 NSP 通則「重用不重造」。
- **哪些問題應合併**：UX3-04/05/08 三合一（同一測試閉環、同一 id 攜帶、同一 GUI 層）。「狀態區分」/「失敗恢復」是 UX3-04 的子集，不另立三個 Phase、不另立三個編號。
- **哪些問題不值得現在做**：B5（F3/F4 定位化，value 低）、任何 Core 側 dry-run 推論（違反「不送輸入」/原則 6/9）、新大型定位抽象（違反「不得複製另一套定位」）。
- **阻斷實作的架構問題**：**無**。唯一需小心處是 B4 的 `_is_testing` 旗標競態（`_show_rule_detail:7653`）與 cancel 檢查點粒度——屬大小（S）設計細節，在 B4 批內可控。
- **建議的下一個 Coding Agent 實作任務**：**「Phase 3B B1+B2+B3（測試結果定位 + Debug 靜默修復 + Sum gate 示範）」**——Files: `gui/run_controller.py`（`_run_rule_test:155-170`、`sum:615-647`）、`gui/06_gui_main.py`（`_show_test_result:8535`、`_test_log_html:734`、`_on_debug_step_requested:8674`、`_on_debug_template_step_requested:8780`）、i18n 三語 sum 示範 3 key。驗收：`ruff` + `pytest --no-cov -q` + `test_locate_rule_target.py`/`test_preview_fate.py`/`test_run_controller.py` 全綠 + 真機「測試 miss → 點定位跳步驟」目視。

> 完成後停止，未開始 Phase 3B 實作。
