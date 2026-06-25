
# OCR Trigger Clicker — 修復與優化計畫（agent 執行版）

## 區塊 A：已被原始碼證實、可直接修改

> 此區塊任務均有直接程式碼證據（已於審查報告中貼出）。agent 可直接 apply diff。

### A-1

id:A-1

title:wait_rule 步驟無超時機制，未觸發即中斷

evidence_status:confirmed

target_file:core/05_main_loop.py

target_func:def _handle_wait_rule(self, params: dict, ctx: StepContext, rule: Rule) -> StepResult:

change:

目前邏輯為「目標規則未觸發且當前幀無命中 → 直接回傳 StepResult(」。修改為：

- 新增參數 timeout_ms（預設 5000），從 params 讀取。
- 改為輪詢等待：在 timeout 內反覆檢查目標規則的 trigger_count 是否大於 0，或當前畫面 OCR 是否命中。
- 任何一次檢查成功，回傳 StepResult(。
- 超時仍未命中，則回傳 StepResult(。

新增輪詢間隔 200ms，使用 self._stop_event.wait(0.2) 以便緊急停止能中斷。

player_impact: 流程可靠性提升，避免任務鏈因單幀 OCR 抖動而意外中斷。

acceptance:

- 建立規則 A（偵測「開始」）→ 規則 B（wait_rule 等待 A，超時 3000ms）。
- 僅觸發 A，確認 B 能通過。
- 不觸發 A，確認 B 在 3 秒後停止。
- 在等待期間按下「停止」，確認能立即中斷。

### A-2

id:A-2

title:_save_current_rule 未校驗 detect 步驟的 text 是否為空

evidence_status:confirmed

target_file:gui/06_gui_main.py

target_func:def _save_current_rule(self):

change:

在儲存迴圈中，針對 detect 步驟增加校驗邏輯：

player_impact: 防止玩家儲存無效規則後不知為何沒反應，減少困惑。

acceptance:

- 建立一條規則，detect 步驟的 text 留空 → 點擊儲存 → 彈出警告。
- 建立一條規則，click 步驟的 target= 但 x=0, y=0 → 儲存 → 彈出警告。
- 正常規則儲存不彈出警告。

### A-3

id:A-3

title: 拖拽排序無插入指示線（視覺反饋不足）

evidence_status:confirmed

target_file:gui/06_gui_main.py

target_func:class _StepListWidget 的 dropEvent(self, e):

change:

在 dropEvent 中增加繪製插入指示線的邏輯：

- 在拖拽過程中（dragMoveEvent），記錄鼠標位置對應的插入索引。
- 在 paintEvent 中，於該索引位置繪製一條水平藍色指示線（高度 2px，顏色 #4a90d9）。
- 離開拖拽狀態時清除指示線。

參考實作片段：

player_impact: 拖拽排序時有明確的插入位置提示，操作更直覺。

acceptance:

- 在步驟列表中拖拽一個步驟。
- 滑鼠移動時，應在目標位置顯示一條藍色水平線。
- 放開後，步驟插入至指示線位置。

### A-4

id:A-4

title: 觸發記錄（TriggerLog）未顯示於 GUI

evidence_status:confirmed

target_file:gui/06_gui_main.py

target_func:class MainWindow 的 _setup_ui(self): 與 _connect_signals(self):

change:

在 _setup_ui 中，於主介面底部（self._compare_log_widget 下方或替代之）增加一個簡易觸發記錄顯示區塊：

- 新增 QListWidget，命名為 self._trigger_log_widget，最大高度 100px。
- 在 _connect_signals 中，將 self._signals.trigger_signal 連接至一個新方法 _on_trigger_log_received。
- _on_trigger_log_received 將 TriggerLog 格式化為「時間 + 規則名稱 + 點擊座標」，插入列表頂端，保留最近 20 筆。

player_impact: 玩家能即時看到規則觸發記錄，確認自動化正在正常運作，提升信任感。

acceptance:

- 啟動偵測，觸發至少一條規則。
- 底部列表應出現一條記錄（含規則名稱與時間）。
- 列表保留最近 20 筆，舊記錄自動移除。

### A-5

id:A-5

title: OCR 引擎健康回調未連接至 GUI 狀態列

evidence_status:confirmed

target_file:gui/06_gui_main.py

target_func:def __init__(self): 中的 _ocr_mod.set_ocr_health_callback(None) 處

change:

將 OCR 健康回調連接至 GUI 狀態列：

player_impact: 當 OCR 引擎異常或重啟時，玩家能透過狀態列獲知，不會誤以為規則失效。

acceptance:

- 模擬 OCR 連續失敗（可暫時註解 init_engine 或強制拋出異常）。
- 狀態列應顯示黃色警告訊息「OCR 連續失敗 X 次，正在重啟引擎」。
- 8 秒後警告自動清除。

## 區塊 B：僅檢索未命中、須先驗證才可動手

> 此區塊任務基於「關鍵字檢索未找到」，但可能藏於未完整閱讀的區段或獨立檔案中。agent 必須先執行驗證指令，確認不存在後才可修改。

### B-1

id:B-1

title: 缺少全域啟動/停止熱鍵

evidence_status:needs_verification

verify_cmd:

decision: 若有任一結果 → 停止任務，回報實際檔案與行號（可能已有實作，只是我沒找到）。若均為空 → 執行以下 patch。

target_file:gui/06_gui_main.py

target_func:def _setup_shortcuts(self):

change:

增加一個可設定的全域熱鍵（預設 Ctrl+Shift+F12）以切換偵測啟動/暫停：

- 使用 QHotkey（需新增 dependency）或 Win32 RegisterHotKey。
- 若使用 RegisterHotKey，需在 nativeEventFilter 中攔截 WM_HOTKEY 訊息。
- 按下熱鍵時，觸發與「啟動/暫停」按鈕相同的邏輯（_toggle_start）。
- 在設定中提供熱鍵組合編輯器（可選，預設即可）。

若擔心增加 dependency，優先使用 Win32 API 實作。

player_impact: 玩家可在遊戲全螢幕時，不切回工具視窗即控制自動化啟停，大幅提升掛機便利性。

acceptance:

- 啟動工具，按下 Ctrl+Shift+F12 → 主循環開始偵測。
- 再次按下 Ctrl+Shift+F12 → 主循環暫停。
- 工具視窗無須處於焦點狀態。

### B-2

id:B-2

title: 缺少簡易/快速模式（降低步驟系統門檻）

evidence_status:needs_verification

verify_cmd:

decision: 若有結果 → 停止任務，回報實際檔案與行號（可能已有簡易模式入口）。若為空 → 執行以下 patch。

target_file:gui/06_gui_main.py

target_func:def _setup_ui(self): 中的工具列區段

change:

在工具列中增加一個「切換至簡易模式」按鈕或開關：

- 簡易模式僅顯示「目標文字」、「點擊位置（文字中心/自訂）」、「觸發次數（一次/重複）」三個核心設定。
- 所有進階參數（fuzzy_threshold、cooldown_ms、match_mode、roi、random_offset）摺疊隱藏，使用預設值。
- 切換模式時，保持規則資料完整性（進階參數不遺失）。

簡易模式 UI 示意：

player_impact: 初次使用者可在 3 個欄位內完成第一條規則，大幅降低學習曲線。

acceptance:

- 切換至簡易模式，編輯器僅顯示 3 個欄位。
- 切換回進階模式，所有參數恢復顯示且數值保留。
- 在簡易模式下儲存的規則，在進階模式下仍可正常編輯。

### B-3

id:B-3

title: 缺少內建任務模板

evidence_status:needs_verification

verify_cmd:

decision: 若有結果 → 停止任務，回報實際檔案與路徑（可能已有模板目錄）。若為空 → 執行以下 patch。

target_file:core/04_rule_engine.py 與 gui/06_gui_main.py

target_func: 新增 def _load_template(self, template_name: str) -> list[Rule]: 與 def _apply_template(self, template_name: str):

change:

- 在 tasks/ 旁建立 templates/ 目錄，內含 3~5 個 JSON 模板檔案（如「領取每日獎勵. json」、「跳過對話. json」、「確認彈窗. json」）。
- 在 GUI 的「新增規則」按鈕旁增加「從模板建立」下拉選單。
- 選取模板後，複製其規則至當前任務（深拷貝，不影響原模板）。

模板內容範例（「確認彈窗. json」）：

player_impact: 玩家可一鍵套用常見場景，無需從零理解步驟系統，加速首次使用成功。

acceptance:

- 工具啟動時，templates/ 目錄自動建立。
- 點擊「從模板建立」→ 選擇「確認彈窗」→ 當前任務新增一條規則，名稱為「點擊確認按鈕」。
- 該規則可直接啟動並運作。

### B-4

id:B-4

title: 缺少互動式引導（首次使用導覽）

evidence_status:needs_verification

verify_cmd:

decision: 若有結果 → 停止任務，回報實際檔案與行號（可能已有引導系統）。若為空 → 執行以下 patch。

target_file:gui/ 目錄下新增 gui/14_gui_onboarding.py

change:

建立一個獨立的引導對話框（OnboardingWizard），包含 4~5 個步驟：

- Step 1：選擇視窗 → 引導用戶點擊「重新整理」並選取目標視窗。
- Step 2：建立規則 → 引導用戶輸入目標文字（如「開始」），並解釋點擊行為。
- Step 3：設定偵測區域 → 引導用戶使用 ROI 框選功能（可跳過）。
- Step 4：啟動 → 引導用戶點擊「啟動」按鈕。
- 完成 → 顯示「已成功設定第一條規則！」並提供「建立更多規則」或「關閉」按鈕。

每個步驟帶有動態高亮（指向對應 UI 元件）與說明文字。

player_impact: 新手第一次使用時，無需閱讀外部文件即可完成完整設定，顯著提升初體驗成功率。

acceptance:

- 首次啟動時，自動彈出引導對話框。
- 按步驟操作，每一步都有明確指示。
- 完成後，工具應已設定好一條可用規則。
- 第二次啟動不再自動彈出（可從「新手教學」按鈕手動重啟）。

## 給 agent 的執行守則

- 執行順序：先完成所有 區塊 A 任務（可直接修改），再處理 區塊 B。
- 區塊 B 嚴格流程：先執行 verify_cmd 中列出的所有檢索指令。若有任何結果 → 立即停止該任務，並回報「發現既有實作，位於 [檔案:行號]，建議審查後決定是否調整」，不得執行 patch。若所有結果均為空 → 才執行 change 中所述的修改。
- 回報格式：每完成一項任務，輸出以下格式：text复制下载[DONE] A-1: wait_rule 超時機制修改檔案：core/05_main_loop.py變更行數：+45, -12驗證指令：rg
- 禁止事項：禁止在 needs_verification 任務上跳過驗證步驟直接 patch。禁止修改未明確指定的檔案或函式。禁止移除既有功能（僅新增或修改指定邏輯）。
- 測試優先：每次修改後，先手動執行 acceptance 中的驗收測試，確認通過後再回報完成。
- 謹慎處理 06_gui_main.py：此檔案超過 130KB，修改前先定位目標函式，僅修改指定區段，避免影響不相關的 UI 佈局。

計畫結束。請 agent 按區塊順序逐一執行，每完成一項即回報證據與驗收結果。
