# 交接摘要（HANDOFF）

> 最後更新：2026-11-04 ｜ 對應階段：**E2／P2 階段收斂 ＋ v0.4.9 發布前修正**

## 一句話

完成 **Global Stop 控制流程、輸入取消鏈、Frida 邊界、後台錯誤生命週期、通知去重鎖存**
與 **後台失敗回報／OCR Debug 測試按鈕停用** 的必要修正、測試補強與文件更新；
另補齊 **Click PostMessage 失敗原因（R-1）** 與 **在途驗證 worker 中止（R-3）**，
收斂進 commit `2f1aa9c` 與 `45aefbd`，工作區僅剩兩個工具檔。

## 本階段做了什麼

### C-2a-1（Preflight／BLOCKED／Drag Legacy／Parallel Once）

- **NEW-A**：GUI drag 表單不再無條件寫回 `dx/dy`（dirty tracking ＋ 舊資料原樣保留）；新式 endpoint drag 完全不新增 `dx/dy`。
- **F-03**：前景 BLOCKED：execution log 一列（步驟欄「預檢」、結果「⊘ 略過」）＋狀態列／toast（最多兩項問題摘要）；同一規則同一問題**只通知一次**。背景 BLOCKED：只寫 execution log，不彈 toast。
- **NEW-B**：fp=None 以 `(rule.id, problems 分類)` 當 stable fallback key，同規則同問題只通知一次；reload 後可再通知。
- **NEW-C**：全部 BLOCKED → **保持等待**：不推進 `_group_queue_idx`、不計 completed、不觸發 stop；修復規則 → 儲存 → reload 後下一幀重新預檢。
- **F-07**：`_run_step` spy 測試鎖定：Background／Parallel 的 BLOCKED 規則 Step 呼叫數為 0。
- **F-13**：`docs/dev/ARCHITECTURE.md` 新增「Preflight 與 BLOCKED 語義」＋drag 欄位說明；`docs/index.html` 新增「規則為什麼沒有執行？」FAQ。

### E2-A1（Global Stop／Scheduler 控制流程）

- 全域停止優先於任何 StepResult：停止後不重送輸入、不執行下一個 Step、不計入 completed、不推進指標。
- 停止閘落在 handler 入口、步驟送出前、Verify 開始前、重試延遲結束後；全域停止與 local `on_fail` 語意分離。
- 停止摘要回傳 `RuleRunOutcome.STOPPED`，只有全域停止才回 STOPPED，其餘維持原本下一幀重試語意。

### E2-A2（Input Cancellation）

- 輸入鏈可中斷：`send_scroll(cancel=)`、拖曳 MOVE 前可中止、bg 按鍵持窗等待可中斷、驗證輪詢與重試延遲可取消。
- **必要的 Release 永不受停止閘阻擋**（DOWN 已送出就一定嘗試 UP），避免按鍵卡在遊戲裡。
- 停止後不重送輸入；`cancel=None` 時既有呼叫者零影響。

### E2-A2-F1（Frida 邊界）

- Frida 的 `rpc.exports` 是同步呼叫，無法中斷執行中的 RPC → 取消只能體現在階段邊界：attach 前、attach 後、重新 attach 後各補一道閘。
- `key()` 只在「按下」階段檢查取消；放開永不受閘阻擋。UP 失敗會被回報。

### P2-1／P2-3（狀態生命週期）

- **P2-1**：`last_error()` 的讀取點都緊接在「剛失敗的操作」之後 → 語意是當次操作的錯誤。已在每次後台操作開始時歸零 bg 層與 frida 層。
- **P2-3**：`_notified_conditions` 屬於單次執行的觀察期狀態 → 已在 `start()` 與 `_load_rules()` 清除，條件再次成立可再次通知。

### C-1／C-2／C-3／C-5（診斷與輸入回報）

- **C-1**：Frida 按鍵 UP 失敗不再回報成功（`send_key()` 回傳 False ＋ 記錄原因），MainLoop 不再標記 `triggered`、不再記「按鍵已送出」。
- **C-2**：後台拖曳／滾輪失敗會進入既有回報機制（`_handle_drag`／`_handle_scroll` → `_report_bg_failure()`），底層補上失敗原因（滾輪不再忽略 `PostMessageW` 回傳值＝假成功）。
- **C-3**：30 秒節流只擋 GUI 通知，**日誌每次失敗都寫**。
- **C-5**：主循環執行期間停用 OCR Debug 的點擊／按鍵測試按鈕（與主循環共用後台輸入狀態），停止後依面板原本狀態還原；面板自身「有選取結果才可用」的邏輯不受影響。

### R-1／R-3（v0.4.9 發布前修正，`45aefbd`）

- **R-1**：`core/16_bg_input.py` `_click_postmessage()` 的 DOWN／UP 失敗改以 `_set_error()` 記錄原因（另含例外路徑）→ MainLoop 的 `_report_bg_failure()` 與 OCR Debug 失敗分支讀得到「為什麼失敗」。回傳值語意與 finally 的 UP 釋放路徑不變；取消不算失敗。
- **R-3**：`gui/09_ocr_debug.py` 主循環啟動時以既有 generation id 作廢在途 click／key 驗證 worker，歸零 in-progress 旗標並還原按鈕文字與可用性；worker 於送出輸入前再確認一次主循環狀態。**已送出的 DOWN 不受阻斷**，必要的 UP 仍由後端層必定送出（`threading.Event` 作為跨執行緒閘）。

## 驗證結果（實測）

```
tests/test_bg_diag_reporting.py（新增 C-1/C-2/C-3）  → 20 passed
tests/test_debug_panel_run_state.py（新增 C-5）      → 7 passed
tests/test_stop_cancel.py（E2-A2）                   → 28 passed
tests/test_frida_cancel.py（E2-A2-F1）               → 16 passed
tests/test_bg_error_lifecycle.py（P2-1）              → 10 passed
tests/test_notify_dedup.py（P2-3）                   → 8 passed
tests/test_rule_preflight.py（C-2a-1）               → 37 passed
tests/test_drag_legacy.py（C-2a-1）                   → 34 passed
tests/test_run_controller.py（C-2a-1）                → 2 passed
tests/test_bg_click_error_reporting.py（新增 R-1）    → 12 passed
tests/test_debug_verify_abort_on_run.py（新增 R-3）   → 16 passed
完整套件                                          → 1325 passed, 0 failed（78.74s）
ruff check                                        → All checks passed（exit 0）
git diff --check                                  → exit 0
core self-check（4 檔）                             → 全 exit=0
coordinate_calibration --self-check                → passed
coordinate_calibration --diagnose                  → 通過（三模式截圖／OCR／座標路由）
coordinate_calibration --e2e                       → 6/6 通過，最大偏差 0px
```

新測試的鑑別力已逐一驗證（以 runtime patch 模擬「修正不存在」）：
C-1 → 2 項失敗、C-2 scroll → 2 項、C-2 drag → 3 項、C-2 回報 → 7 項、C-3 → 2 項、C-5 → 4 項；
**R-1 → 5 項失敗**（DOWN／UP／例外原因＋MainLoop 靜默回報）、**R-3 → 11 項失敗**（16 項中）。

## 交接重點

- **工作區已收斂**：E2／P2 階段的程式碼與測試在 `2f1aa9c`（31 檔，+5153／−112）；本次 R-1／R-3 修正與新測試在 `45aefbd`（6 檔，+779／−100）；文件為本次文件 commit。
- **保留未納入 commit**：`.agents/`、`skills-lock.json`（工具檔，不刪除、不納入）。
- branch `master`，HEAD `45aefbd`，`origin/master` = `d1184e0`（前次已 push），本次領先 1 顆，**尚未 push**。
- 距上次發布（`v0.4.8`）累計 24 顆 commit 未發布（含本次文件 commit）；下一步是 `release.ps1 -Version "0.4.9" -FeedTest`。
- 既有假 `_migration` **不清洗**（產品決策 keep）——使用者任務檔內既有標記保持原狀。
- 並行（∥）群組「**全員**被擋下」＝等待語義，修好→儲存→自動恢復；全員停用（disabled）的並行群組 stall **另案**。
- **真機 frida／hybrid 拖曳、frida 輸入取消與 Release 仍未驗證。**

## 排除範圍（本次未做，見 NEXT_STEPS.md）

C-2a-2 Drag Repair UI；假 marker 清洗；parallel 全員 disabled stall；fingerprint 效能重構（F-08）、
`_preflight_last_fingerprint`（F-09）、dead binding（F-10）、`RuleRunOutcome` 死成員；
C-4 跨執行緒錯誤歸屬（僅以 C-5 限制重疊）；C-6 群組輪替重新武裝；C-9 pynput/hybrid 失敗回報語意；
R-2 log 限流；R-4 UP 失敗後重試；R-5 主循環啟動的毫秒級窗口；R-6 作廢驗證無中止提示。

---

# 歷史交接紀錄（F-13）

> **狀態：歷史紀錄（2026-11-03 依查核報告與現場證據回填）**
> 本節原文收錄於 F-13 階段完成時的 HANDOFF 交接，於 C-2a-1 文件刷新時被整檔覆寫遺失。
> **本節依現行程式碼與提交紀錄（`1de9239`、`3d01f0a`）重建，不是從 Git 恢復**；
> 原文件從未入版控，無法還原逐字。標示「待查」者為證據不足之處，不得臆測。

## F-13 是什麼

- 舊查核編號 **F-13（P1）**：「frida 模式 drag 自我死鎖＋拖曳語意錯誤」（見 `docs/dev/KNOWN_ISSUES.md` 舊清單）。
- 修正隨下列已提交版本落地：
  - `1de9239`「fix: 完成輸入安全、數值驗證與步驟編輯器修正」（含 `core/16_bg_input.py`、`tests/test_bg_drag.py`、`tests/test_hold_interrupt.py`）
  - `3d01f0a`「feat: add drag endpoint picking and input validation」（Drag 終點拾取＋輸入驗證）
- 修正後的拖曳語義：**DOWN（起點）→ MOVE（終點）→ UP（終點）**；DOWN 成功後無論 MOVE 成功與否都會嘗試 UP（避免遊戲內卡住按鈕）；DOWN→MOVE、MOVE→UP 各間隔 0.05s（沿用原常數）。frida 模式送 MOVE 前必須先 `sync_cursor()` 把注入腳本的假造游標移到終點（遊戲讀的是假游標）；DOWN 前同理需同步到起點。

## 根因（依現場證據重建）

- `core/16_bg_input.py` 的 `_lock` 是**非重入** `threading.Lock()`（`core/16_bg_input.py:25`）。
- 舊實作的拖曳路徑在已持有該鎖的情況下，再次呼叫會自行取得同一把鎖的函式（如背景 `click()`）；同執行緒重入非重入 Lock → **永久死鎖**（frida 模式下背景拖曳直接卡死主循環）。
- 現場留下的防護註解即此根因：

  > 全程只取得一次 _lock：不得呼叫會自行取同一把鎖的 click()，否則同執行緒重入非重入 Lock 會永久死鎖。（`core/16_bg_input.py:602-603`）

- 修正方向是**重構為不巢狀**（整段拖曳只取一次鎖；DOWN 失敗 → 不送 MOVE／UP；DOWN 成功 → `finally` 一定送 UP），而不是放寬鎖的可重入性。
- 待查：原始死鎖的完整呼叫鏈與當時的行號（原交接紀錄已遺失，無法還原）。

## 為什麼不採用 RLock（摘要，非原文）

原文件逐字論述已遺失。以下是依現場證據可支持的摘要，並非還原：

- 現行程式**同時**使用兩種鎖，職責不同：
  - `core/18_frida_bg.py:42` 使用 `threading.RLock()`，註解明示「ensure_attached 內會呼叫 detach()，需可重入」——RLock 用在**確實需要重入**的模組內部。
  - `core/16_bg_input.py:25` 刻意維持非重入 `Lock`。
- RLock 只會讓同執行緒重入不再死鎖，**不會修正「DOWN 之後一定要送出 UP」的語意需求**；問題只會轉移，不會消失。
- 非重入鎖把「拖曳序列不得巢狀取鎖」變成**可被強制遵守的約束**；RLock 會掩蓋未來再次把 click()／其他取鎖路徑巢進拖曳中的迴歸（靜默錯誤取代死鎖，更難發現）。
- 待查：原文件對 RLock 反對理由的完整展開（尤其與 `ensure_attached → detach()` 重入需求的取捨）。

## 當時的驗證證據（歷史數據，非目前數字）

- 完整測試套件 **1027 passed**（F-13 階段基線）
- `tests/test_bg_drag.py` **12 項**
- `tests/test_hold_interrupt.py` **41 項**
- （C-2a-1 Closeout 當時的歷史基線：**1198 passed**。歷史數據僅供追溯，不得與現行比較或宣稱。）

## 當時工作區的警告（仍有效）

F-13／drag 修正與 **E-1 cancel plumbing**（cancel 傳遞鏈，舊 F-6／F-7／F-8）當時混在**同一未提交工作區**。分清如下：

- F-13／drag 修正已隨 `1de9239`、`3d01f0a` **提交**；
- **E-1 cancel plumbing** 已於 **E2-A2 完成**（`2f1aa9c`）；
- 真機 frida／hybrid 拖曳至今仍**未驗證**（見本檔「交接重點」）。

---

# C-2a-1 補正（2026-11-03，Closeout 後）

依獨立唯讀審查報告的三項補正（本檔上方「歷史交接紀錄（F-13）」即其中第一項）：

1. **HANDOFF.md**：回填 F-13 歷史技術紀錄（重建，非 Git 還原；遺失細節標示待查）。
2. **NEXT_STEPS.md**：恢復「E-2：Stop 路徑整體設計審查」（§4，未開始；審查範圍非缺陷預判）。
3. **Reload 一致性**：`_load_rules()` 在 reload 邊界統一清除 `_last_exec_log` 與 `_last_completed_log`（execution log deque 歷史紀錄刻意保留），讓 GUI save 路徑（`gui/06_gui_main.py:7589` 直接呼叫 `_load_rules()`）的去重語義與 `reload_rules()`／任務切換路徑一致——reload 後同一 BLOCKED 問題可再記錄一列、toast 亦可再觸發；同一載入週期內行為不變。

> 補充（2026-11-04）：第 3 項的 reload 邊界於 **P2-3** 再補上 `_notified_conditions` 清除，
> 讓「規則重載後的首次命中」可再次通知。E2 審查（當時列為 §4）已於 **E2-A1／E2-A2／E2-A2-F1** 完成。
