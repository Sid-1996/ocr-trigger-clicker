# 已知問題（KNOWN_ISSUES）

> 最後更新：2026-11-10（新增「UX3-06 查核（2026-11-10）」一節；其餘內容沿用 2026-11-07）
> 來源：E1-R 查核（F-1～F-12，舊編號）、E1-R2-V 查核（F-13～F-17，舊編號）、**C-2a-1 Closeout（2026-11-03）**、**E2／P2 階段查核（2026-11-04）**、**v0.4.9 發布前修正 R-1／R-3（2026-11-04）**、**UX3-06 查核（2026-11-10）**

## E2／P2 階段查核（2026-11-04）

涵蓋 Global Stop 控制流程（E2-A1）、輸入取消（E2-A2）、Frida 邊界（E2-A2-F1）、
`_last_error` 生命週期（P2-1）、通知去重鎖存（P2-3），以及診斷與輸入回報缺陷
（C-1／C-2／C-3／C-5）。

| ID | 嚴重度 | 狀態 | 問題 |
|---|---|---|---|
| E2-A1 | — | ✅ 已修（E2-A1） | Global Stop 優先於任何 StepResult：停止後不再重送輸入、不推進指標、不計入 completed；停止與 local `on_fail` 語意分離 |
| E2-A2 | — | ✅ 已修（E2-A2） | 輸入鏈不可中斷：停止後按鍵放開（UP）、拖曳放開、滾輪、驗證重試皆可被中止，且必要的 Release 不受停止閘阻擋 |
| E2-A2-F1 | — | ✅ 已修（E2-A2-F1） | Frida attach 期間抵達的 Stop 仍會送出 DOWN；`key()` 的 UP 失敗不被回報。已補 attach 前後／重試後的取消閘與 Release 回報 |
| P2-1 | — | ✅ 已修（P2-1） | `_last_error` 黏著：舊錯誤會遮蔽新錯誤、讓回報過期原因。已改為每次操作開始歸零（bg 層與 frida 層同時歸零） |
| P2-3 | — | ✅ 已修（P2-3） | `_notified_conditions` 跨啟動／跨規則重載殘留 → 重新啟動後首次命中不再通知。已在 `start()` 與 `_load_rules()` 清除 |
| C-1 | P2 | ✅ 已修（2026-11-04） | Frida `send_key()` 的 UP 失敗仍回傳 True → MainLoop 記「按鍵已送出」、`ctx.triggered=True`，錯誤被吞。已改為回傳 False 並記錄原因（`core/16_bg_input.py` `send_key()`） |
| C-2 | P2 | ✅ 已修（2026-11-04） | 後台拖曳／滾輪失敗不回報、底層失敗不留原因（滾輪甚至忽略 `PostMessageW` 回傳值＝假成功）。已補錯誤原因與 `_report_bg_failure()` 呼叫（`_handle_drag`／`_handle_scroll`／`_scroll_postmessage`／`drag()`） |
| C-3 | P2 | ✅ 已修（2026-11-04） | 30 秒錯誤節流直接 `return`，連 log 都不寫 → 30 秒內的後續後台失敗在紀錄中消失。已改為每次失敗都寫 log，節流只擋 GUI 通知 |
| C-5 | P2 | ✅ 已修（2026-11-04） | 主循環執行期間 OCR Debug 的點擊／按鍵測試按鈕仍可操作 → 與主循環共用同一組後台輸入狀態。已於循環執行期間停用，停止後依面板原狀還原 |
| **C-4** | P2 | ℹ️ 已知限制 | `_last_error` 跨執行緒歸屬：`_reset_error_state()` 在取鎖之前、`last_error()` 不取鎖 → 兩執行緒交錯時可能互相覆蓋或遺失錯誤。**本次以 C-5 限制重疊操作**（循環執行期間停用除錯測試鈕），未引入 per-operation error handle。影響僅限診斷文字 |
| **C-6** | P3 | ℹ️ 已知限制 | `_notified_conditions` 只在「規則被評估到且偵測失敗」時重新武裝。群組輪替期間（每幀只評估一條規則）條件若在不為真的期間未被觀察到，鎖存會過期 → 條件再次成立時不通知。修正需改變通知觸發條件，屬產品決策 |
| **C-7** | P3 | ⬜ 未完成（待真機） | Frida 輸入取消與 Release 尚未完成真機驗證（見下方「待真機驗證」）。2026-11-07 補充：P0 真實整合驗證 harness 已落地（`0a8afbb`，需 `OTC_RUN_INPUT_INTEGRATION=1`），但本次重跑 13 項 skip、未實際執行 |
| **C-8** | P3 | ✅ 已修（2026-11-04） | 本文件與 CURRENT_STATUS／NEXT_STEPS／HANDOFF 的狀態落後於程式碼 → 已同步 |
| C-9 | P3 | ℹ️ 保留（原本裁定） | 後台失敗回報僅在 frida 模式生效；pynput／hybrid 模式的失敗語意維持原樣 |
| C-10 | P3 | ℹ️ 保留（原本裁定） | 死碼清理：`RuleRunOutcome` 死成員、`_preflight_last_fingerprint` 死欄位、annotation-only 綁定 |
| C-11 | — | ℹ️ 保留（環境性） | `tests/test_frida_real.py::test_spoof_auto_restores` 游標 1px 抖動、`coordinate_calibration.py --diagnose` 首次必失敗（校正視窗冷啟動） |

### 本次修正後仍存在的新風險（2026-11-04）

| ID | 嚴重度 | 問題 | 位置 | 建議 |
|---|---|---|---|---|
| R-1 | P3 | ✅ **已修（2026-11-04，`45aefbd`）**：Click 路徑的 DOWN／UP 失敗不記錄原因 → `_handle_click` 的 `_report_bg_failure()` 讀到空錯誤而靜默返回 | `core/16_bg_input.py` `_click_postmessage()` | 已補 `_set_error()`（DOWN／UP／例外三種路徑）；取消不算失敗；finally 的 UP 釋放路徑不變 |
| R-2 | P3 | 後台輸入失敗現在每次都寫 log → 若某規則每幀都失敗（約 500ms／幀），一天約 17 萬筆，可能撐大日誌檔 | `core/05_main_loop.py` `_report_bg_failure()` | 需產品決策是否對 log 也限流（與 C-3「每次都要寫」衝突） |
| R-3 | P3 | ✅ **已修（2026-11-04，`45aefbd`）**：循環啟動前已建立的 OCR Debug 驗證 worker 仍會跑完 → 該窗口內仍與主循環共用後台輸入 | `gui/09_ocr_debug.py` 驗證 worker | 已於循環啟動時以既有 generation id 作廢在途驗證＋worker 送出輸入前的自我中止閘；已送出的 DOWN 不受阻斷 |
| R-4 | P3 | Frida UP 失敗後該規則視為未 triggered → 群組指標不推進，下一幀會再試一次按鍵（與既有 click 失敗語意一致，受 CPS 上限約束） | `core/05_main_loop.py` `_handle_key` | 觀察；對「按鍵卡住」反而有助於放開 |
| R-5 | P3 | ✅ **已修（2026-11-04，`0f77931`）**：主循環啟動到 GUI 通知面板之間有毫秒級窗口（`InitWorker.run()` 的 `loop.start()` 先於 `finished.emit`）→ 該窗口內 key 驗證 worker 仍可能送出一次按鍵 | `gui/06_gui_main.py` `_start_loop()`／`InitWorker.run()` | 已於啟動 InitWorker **之前**先 `set_run_active(True)`；啟動失敗（含執行緒起不來）時恢復。`set_run_active` 本身冪等，不會重複作廢 |
| R-6 | P3 | 被作廢的驗證 worker 結果會因 request id 過期而被忽略 → 使用者只看到按鈕恢復，沒有「已中止」提示 | `gui/09_ocr_debug.py` `_abort_running_verifications()` | 產品決策是否要補提示；不影響輸入安全 |

## UX3-06 查核（2026-11-10）

Click／Drag 目標選項與驗證時機的查核與修正。實作細節見 `docs/dev/ARCHITECTURE.md` 與 `docs/dev/CURRENT_STATUS.md`。

| ID | 嚴重度 | 狀態 | 問題 |
|---|---|---|---|
| **UX3-06-P1-1** | P1 | ✅ 已修（2026-11-10） | 未知 `target` 只在執行期 stop → 使用者要等規則真的跑起來才知道設定錯了。已改為 preflight 事前擋下（問題鍵 `unknown_click_target`／`unknown_drag_target` → `status=blocked`），白名單集中在 `core/rule_migration.py` 的 `STEP_TARGETS`（唯一事實來源）；**執行期防禦性 stop 保留不動** |
| **UX3-06-P1-2** | P1 | ✅ 已修（2026-11-10） | Dry Run 預覽遇到未知 target 靜默略過該步驟 → 預覽呈現「測試通過」的假象。已改為寫入明確錯誤訊息並標記 terminal（後續步驟標為不會執行），與引擎行為一致 |
| **UX3-06-P1-3** | P2 | ✅ 已修（2026-11-10） | Drag 沿用 Click 的「點擊辨識目標／點擊指定的比例座標位置」文案，且未說明拖曳不支援游標目標 → 易被誤讀。已改用 Drag 專屬文案（明確寫出「拖曳起點」）＋ combo tooltip 說明拖曳無 cursor 目標；target 的實際資料值與執行語意不變 |
| **UX3-06-P2-1** | P2 | ✅ 已修（2026-11-10） | `target=cursor` 時 GUI 仍可調整 `random_offset`，但引擎該分支強制把抖動歸零 → 使用者以為抖動有效。已停用該控制項（**值保留**，切回 `text_center`/`custom` 恢復可編輯） |
| **UX3-06-P2-3** | P2 | ✅ 已修（2026-11-10） | `target=custom` 且座標仍是 (0,0) 時 GUI 完全沒有提示 → 使用者以為已設定。已加未設定提示（**純顯示，不阻擋保存**；既有 `custom_click_at_origin` 仍只是 preflight 的警告而非阻擋問題） |
| **UX3-06-P2-4** | P3 | ℹ️ 已知限制（本次僅記錄事實） | Drag 的 `hold_ms` 會被 normalize 寫入 params，但執行期 `_handle_drag` 從不讀取、GUI 也沒有此欄位 → 死欄位。**未改資料契約、未刪欄位、未改行為**，差距記錄於 ARCHITECTURE.md |
| **UX3-06-P2-5** | P3 | ℹ️ 已知限制（本次僅記錄事實） | `validate_drag_endpoint` 要求終點各自落在 0~1（像素終點判 `invalid`／`out_of_range`），執行期 `_resolve_point` 只有「兩軸都 <=1」才走比例、否則當像素 → validator 比執行期嚴格。**未放寬 validator、未改執行行為**，差距記錄於 ARCHITECTURE.md |
| **UX3-06-GUI** | — | ⬜ 未完成（待真機） | 本次僅以自動化測試（`tests/test_ux3_06_target_validation.py`，27 項）鎖定行為，**未在真實 GUI／遊戲上逐項點擊確認** |
| **UX3-06-P2-2** | P2 | ⬜ 開放（本次明確排除） | `custom_click_at_origin` 只有 preflight warning，沒有 GUI 消費端 → 使用者看不到「(0,0) 可能不是你要的位置」以外的說明。本次明確排除，維持原狀 |

## C-2a-1 Closeout 查核（2026-11-03）

| ID | 嚴重度 | 狀態 | 問題 |
|---|---|---|---|
| NEW-A | P2 | ✅ 已修（C-2a-1） | GUI drag 存檔無條件寫 `dx/dy`，新式 endpoint drag 被 migration 誤判 legacy／mixed，產生假 `_migration`（已實測 round-trip 重現）。已改為 dirty tracking＋舊資料原樣保留 |
| F-03 | P2 | ✅ 已修（C-2a-1） | BLOCKED 對使用者完全無訊息。已補 execution log＋toast（前景、同規則同問題只通知一次），背景僅 log |
| NEW-B | P3 | ✅ 已修（C-2a-1） | fp=None 規則零日誌靜默 skip；現以 `(rule.id, problems 分類)` fallback 去重，至少通知一次 |
| NEW-C | P2 | ✅ 已定案（C-2a-1） | Parallel Once 全 BLOCKED 無聲永久等待。**產品決策：保持等待＋可觀察**（不假完成、不推進 queue、reload 後自動恢復） |
| F-07 | P2 | ✅ 已修（測試） | Background／Parallel BLOCKED 測試無鑑別力；已補 `_run_step` spy 測試（Step 呼叫數斷言） |
| F-12 | P2 | ✅ 已裁決（C-2a-1） | `tests/test_drag_legacy_backup.py` 為過時副本（2 個過時斷言失敗）；**已於 2026-11-03 刪除（使用者授權）** |
| F-13 | P3 | ✅ 已修（文件） | Repeat／Loop／Parallel Once／背景 BLOCKED 語義已寫入 ARCHITECTURE.md；index.html 新增 FAQ |
| **C2-1** | P2 | ⬜ 開放（另案） | 並行（∥）群組**全員停用（disabled）**時的 stall（同類等待語義，但全員停用是使用者明確選擇，不在本次範圍） |
| **C2-2** | P2 | ⬜ 開放（產品決策已定 keep） | 既有任務檔內的假 `_migration` 不清洗；新資料不再產生假 marker。需要清洗時另案 |
| **C2-3** | P2 | ✅ 已修（UX Phase 3C） | Drag Repair UI：`_migration`／`validate_drag_endpoint` 無 GUI 消費端。已補：舊版 Drag 開啟即顯示修復 banner（判定以 core `validate_drag_endpoint` 為唯一來源）→「重新拾取終點」→ 使用者確認後才移除 `dx/dy` 與 marker；未修復前舊欄位唯讀且原樣保留；任務載入時提示需修復的步驟數 |
| F-08 | P3 | ⬜ 開放 | fingerprint 每幀每規則重算（fresh BLOCKED 3 次、detect 全文 `!r`）；效能可接受，未重構 |
| F-09 | P3 | ⬜ 開放 | `_preflight_last_fingerprint` 死欄位（僅測試清空用） |
| F-10 | P3 | ⬜ 開放 | `rule_preflight.py` 的 `Rule`、`05_main_loop.py` 的 `PreflightResult` 為 annotation-only 死綁定（ruff 無 F401；非 import） |
| F-11 | — | ✅ 已解（2026-11-04） | 提交拆分：A（drag）／B（preflight）共用 2 檔需 hunk 級拆分 → 最終以單一整合 commit 收斂（C-2a-1＋E2＋P2＋診斷修正），不做高風險 hunk 手術 |
| **BUG-1** | P2-注意 | ℹ️ 已知 | 每個經 GUI 存檔的 drag 都帶 `dx=0/dy=0`，reload 後被標 `mixed_legacy_and_endpoint`（舊檔 3d01f0a 之前已發生者保留原狀，keep 決策） |

## 舊清單（E1-R / E1-R2-V，編號保留）

| ID | 嚴重度 | 狀態 | 問題 |
|---|---|---|---|
| F-1 | P1 | ✅ 已修（E1-R2） | PostMessageW 只靠 exception 判斷失敗 |
| F-2 | P2 | ✅ 已修（E1-R2） | 測試名稱與斷言相反；bg pynput post-press 失敗無覆蓋 |
| F-3 | P2 | ✅ 已修（E1-R2） | drag 測試名稱反轉 |
| F-4 | P2 | ✅ 已修（E1-R2） | 真實 pynput Controller 防護為恆真式斷言 |
| F-5 | P2 | ✅ 已修（E1-R2） | hybrid 測試的 cancel 未參與 |
| F-10 | P3 | ✅ 已修（E1-R2） | warning 測試未驗 logging level |
| F-13 | P1 | ✅ 已修（F-13 階段） | frida 模式 drag 自我死鎖＋拖曳語意錯誤 |
| **F-6** | P2 | ✅ 已修（E2-A2） | `16_bg_input.send_key` 的 `cancel` 簽章有、函式體未使用 → 現已真正參與等待與送出前閘 |
| **F-7** | P2 | ✅ 已修（E2-A2） | `MainLoop._handle_drag` 未傳遞 `cancel` → 已傳 `self._stop_event`（bg 與 pynput 兩條路徑） |
| **F-8** | P2 | ✅ 已修（E2-A2） | `MainLoop._send_key` 未傳遞 `cancel` → 已傳 `self._stop_event` |
| **F-14** | P2 | ✅ 已修（F1＋C-2） | 鍵盤／捲軸路徑忽略 `PostMessageW` 回傳值 → 鍵盤於 F1 修正；滾輪於 2026-11-04 的 C-2 修正 |
| F-11 | P3 | ⬜ 未修 | 競態測試未真正製造競態（hold 僅 5ms） |
| F-12 | P3 | ✅ 已修（F1） | Background Frida drag 的 up 訊息無保護 → DOWN 成功後 UP 必定嘗試送出 |
| **F-15** | P3 | ✅ 已修（F1＋C-2＋R-1） | 後台點擊失敗未打通統一回報通道 → drag／scroll 已於 C-2 打通；click 失敗的錯誤原因已於 R-1（`45aefbd`）補上，點擊失敗可被回報 |
| F-16 | P3 | ⬜ 未修 | WM_ACTIVATE 的「不中斷」只對回傳 0 成立 |
| F-17 | P3 | ⬜ 未修 | 測試缺口彙整 |

> 舊編號與 C-2a-1 新編號（NEW-A/F-03…）無對應關係；舊 F-xx 指 E1-R 時代。

## 待真機驗證

| 項目 | 說明 | 狀態 |
|---|---|---|
| Frida 輸入取消與 Release 語意 | E2-A2／E2-A2-F1 的取消閘與 UP 必定送出，目前只以假物件測試覆蓋（`tests/test_frida_cancel.py` 16 項）；真實 Frida 注入只驗握手／spoof／key／focus（`tests/test_frida_real.py` 5 項），不含取消與放開。P0 harness 已備（`tests/test_input_cancel_release_integration.py`，需 `OTC_RUN_INPUT_INTEGRATION=1` 桌面執行），2026-11-07 本次重跑 skip、未實際執行 | ⬜ 未驗證 |
| frida 拖曳是否真的拖得動 | F-13 修正後序列 `down → move → up`，真實遊戲是否需要更長按住時間未知 | ⬜ 未驗證 |
| 拖曳間隔 | DOWN→MOVE、MOVE→UP 各間隔 0.05s，沿用原常數 | ⬜ 未驗證 |
| hybrid 拖曳（前景路徑） | 本階段未跑真機 | ⬜ 未驗證 |
| 後台輸入失敗的使用者體感 | 失敗現在會寫 log ＋節流後彈提示（C-2／C-3）；使用者是否能在第一時間注意到仍待真機確認 | ⬜ 未驗證 |

## 環境性 flaky（非產品缺陷）

- `tests/test_frida_real.py::test_spoof_auto_restores`：游標在兩次讀取間移動 1px 即失敗（910 vs 911）；單獨重跑穩定通過。
- `devtools/coordinate_calibration.py --diagnose`：首次執行必失敗（校正視窗冷啟動未就緒），第二次執行通過；前景擷取會抓到使用者當下的前景視窗，devtool 抓到的 rect 可能早於視窗 `move()` 生效 → 座標路由誤判。背景擷取 5/5 標記、對齊 Δ≤2px 正常。
