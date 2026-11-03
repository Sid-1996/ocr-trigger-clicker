# 目前狀態（CURRENT_STATUS）

> 最後更新：2026-11-04
> 對應階段：**E2／P2 階段收斂 ＋ v0.4.9 發布前修正**（Global Stop／輸入取消／後台失敗回報／通知去重／R-1／R-3）

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
| **C-2a-2** | Drag Repair UI（`_migration` 消費端、needs_repair 修復流程） | ⬜ 未開始 |
| **真機驗證** | Frida 輸入取消／Release、frida／hybrid 拖曳 | ⬜ 未完成 |

## 工作區狀態

- branch：`master`
- 本次工作區起點：HEAD = `d1184e0` = `origin/master`（ahead/behind **0/0**）
- 本次修正 commit：`45aefbd`（`fix: 補齊 Click PostMessage 失敗原因與在途驗證 worker 中止`），**尚未 push**
- 遠端 `origin/master` = `d1184e0`（`docs: 更新 E2 階段進度與已知問題`）
- **staged：空**；工作區產品修改乾淨（文件 commit 建立前）
- **保留未納入 commit**：`.agents/`、`skills-lock.json`（工具檔，與產品無關）
- 距上次發布（`v0.4.8`）累計 **24 顆** commit 未發布（含本次文件 commit）

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
| **完整套件** | **1325 passed, 0 failed**（目前基線） |

## 品質關卡狀態

| 關卡 | 狀態 | 備註 |
|---|---|---|
| `ruff check` | ✅ All checks passed | exit 0 |
| 完整 pytest | ✅ 1325 passed | 78.74s；含 i18n 三語測試 |
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

## 明確延後（不在本次範圍）

- C-4：`_last_error` 跨執行緒歸屬（已以 C-5 限制重疊操作，不引入 per-operation error handle）
- C-6：`_notified_conditions` 在群組輪替期間未被評估時無法重新武裝
- C-7：Frida 輸入取消／Release 真機驗證
- C-9：pynput／hybrid 失敗回報語意；C-10：死碼清理；C-11：環境性 flaky
- R-2：後台失敗 log 可能大量累積，是否限流待產品決策
- R-4：Frida UP 失敗後規則可能於下一幀重試
- R-5：主循環啟動（`InitWorker.run()` 的 `loop.start()`）到 GUI 通知面板（`finished` → `_update_edit_enabled(False)`）之間有毫秒級窗口，該窗口內 key 驗證 worker 仍可能送出一次按鍵（worker 送出前已有閘，但無法完全消除競態）
- R-6：被作廢的驗證 worker 結果會被忽略 → 使用者只看到按鈕恢復，沒有「已中止」提示
- Drag Repair UI（needs_repair 修復流程、`validate_drag_endpoint` 消費端）→ C-2a-2
- 已汙染任務檔假 marker 的清洗（產品決策 keep：不動）
- 全員 disabled 並行群組的 stall（另案，C2-1）
- F-08 fingerprint 效能重構、F-09 `_preflight_last_fingerprint` 死欄位、F-10 死 binding、`RuleRunOutcome` 死成員
