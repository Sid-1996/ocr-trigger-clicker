# 下一步（NEXT_STEPS）

> 最後更新：2026-11-04

## 建議順序

### 0. 發布前收尾（本次已完成程式碼與文件收斂，剩餘待辦）

程式碼與測試已收斂進 `45aefbd`（R-1／R-3 修正＋新測試）、`0f77931`（R-5 修正＋新測試）
與文件 commit；工作區僅剩 `.agents/`、`skills-lock.json` 兩個工具檔（不納入任何 commit、不刪除）。

待辦：
- `.\release.ps1 -Version "0.4.9" -FeedTest` → 試發沙箱
- E2E 驗證（檢查更新／自動更新／防雙開／切換語言）
- `.\release.ps1 -Version "0.4.9"` → 正式庫
- 發布說明以 `docs/dev/CHANGELOG.md` 的 v0.4.9 草稿為基礎

### 1. 真機驗證（阻塞 frida 相關結案宣告）
- **Frida 輸入取消與 Release 語意**（E2-A2／E2-A2-F1）：目前只以假物件測試覆蓋
  （`tests/test_frida_cancel.py` 16 項）。真實 Frida 注入測試
  （`tests/test_frida_real.py` 5 項）只驗握手／spoof／key／focus，不含取消與放開。
  需在真實遊戲驗證：停止後不再送出 DOWN、UP 必定送出、放開失敗可被回報。
- **frida 模式拖曳**：序列 `down → move → up`，真實遊戲是否需要更長按住時間未知。
- **hybrid 前景路徑拖曳**：未驗證。
- 至少在一款支援 frida 後台的遊戲上驗證；不通過則回到 §拖曳 章節調整間隔／游標同步策略。

### 2. C-2a-2：Drag Repair UI（新階段）
目標：讓 `_migration`／`validate_drag_endpoint()` 有 GUI 消費端——拖曳規則缺終點時顯示「修復終點」入口（拾取終點 → 一鍵清除 `_migration` → 儲存 → 自動 reload 重檢）。
前置已備齊：marker 貫穿 save/load/copy/deepcopy、`validate_drag_endpoint()` 純函式與測試、dry-run BLOCKED 顯示。
注意：**不要**自動清洗既有假 marker（產品決策 keep）——修復流程應為「使用者確認後清除」。

### 3. 後台失敗回報的剩餘項目

- **R-2（log 量）**：C-3 之後每次後台失敗都寫一筆 log。若某規則每幀都失敗
  （約 500ms／幀），一天約 17 萬筆。需產品決策是否對 log 也限流（與「每次都要寫」衝突）。
- **R-4（UP 失敗後重試）**：Frida UP 失敗後規則視為未 triggered → 下一幀會再試一次按鍵。
  與既有 click 失敗語意一致、受 CPS 上限約束；先觀察，必要時再調整。
- **R-6（中止提示）**：被作廢的驗證 worker 不再提示使用者「已中止」，
  只看到按鈕恢復。是否補提示屬產品決策，不影響輸入安全。

### 4. 已知限制（保留，非阻斷）

- **C-4**：`_last_error` 跨執行緒歸屬／遺失風險。已用 C-5 限制重疊操作；
  若要嚴格歸屬需 per-operation error handle（架構擴張，暫不做）。
- **C-6**：`_notified_conditions` 只在「規則被評估到且偵測失敗」時重新武裝；
  群組輪替期間條件不為真卻未被觀察到時，條件再次成立不會再通知。
  修正需改變通知觸發條件 → 產品決策。
- **C-9**：後台失敗回報僅 frida 模式生效（pynput／hybrid 維持原語意）。
- **C-10**：死碼清理（`RuleRunOutcome` 死成員、`_preflight_last_fingerprint`、死綁定）。
- **C-11**：環境性 flaky（frida 游標 1px、座標校正首次必失敗）。

### 5. 效能與清理（P3）

- F-08 fingerprint 效能重構（算一次往下傳；detect fp 改 hash）
- F-09 刪 `_preflight_last_fingerprint`；F-10 死綁定清理；`RuleRunOutcome` 死成員
- F-11 競態測試未真正製造競態（hold 僅 5ms）；F-16 WM_ACTIVATE 的「不中斷」只對回傳 0 成立
- F-17 測試缺口彙整

### 6. 全員 disabled 並行群組 stall（另案，已記為 C2-1）

與 NEW-C 同類等待語義，但屬使用者明確配置；需要產品決策（等待提示 vs 視為結束）。

### 7. 已完成（不需重做）

- 輸入層 cancel 傳遞鏈（舊 F-6／F-7／F-8）→ **E2-A2 已完成**
- Stop 路徑整體設計審查（E-2）→ **E2-A1／E2-A2／E2-A2-F1 已完成並驗收**
- 回傳值判斷覆蓋（舊 F-14）→ **鍵盤於 F1、滾輪於 C-2、點擊於 R-1 已完成**
- 後台失敗回報（舊 F-15）→ **drag／scroll 已於 C-2 完成；click 已於 R-1（`45aefbd`）完成**
- Global Stop 與 Scheduler 控制流程（E2-A1）→ **已完成**
- `_last_error` 生命週期（P2-1）與跨執行緒審查（P2-1-R）→ **已完成**
- 通知去重鎖存跨啟動／重載殘留（P2-3）→ **已完成**
- C-1／C-2／C-3／C-5 診斷與輸入回報缺陷 → **已完成**
- R-1 Click PostMessage 失敗原因、R-3 在途驗證 worker 中止 → **已完成（`45aefbd`）**
- R-5 MainLoop 啟動與 OCR Debug 閘門的競態窗口 → **已完成（`0f77931`）**

## 暫時不要做的事

- **不要**自動清洗既有任務檔的假 `_migration`（keep 決策）。
- **不要**把 Parallel Once 全 BLOCKED 改成自動推進或自動停止（C 決策：等待＋reload 恢復）。
- **不要**在未真機驗證前宣稱「frida／hybrid 拖曳可用」或「frida 輸入取消已驗證」。
- **不要**動 `_loader.load_sibling()` 與 canonical `rule_models` 載入路徑；**不要**以 `from core.rule_models import ...` 進產品路徑。
- **不要**只為了 lint 格式化無關檔案。
- **不要**為了拆分 commit 而做 hunk 級手術（本次已收斂為單一整合 commit）。
- **不要**把 `.agents/`、`skills-lock.json` 納入任何 commit。
