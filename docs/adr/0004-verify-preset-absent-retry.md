# 動作後驗證採「三檔預設＋消失語義＋默認重試1次」的最小可用設計

Status: accepted（2026-09-02）

動作後驗證（`verify`）原為單一 `timeout_ms/poll_interval_ms/delay_before_ms` 的固定輪詢，且僅支援「出現即成功」；普通使用者在三類痛點（轉場加載方差大、關彈窗需驗消失、多成功分支）上頻繁誤判逾時，且逾時直接走 `on_fail` 無重試，半夜掛機中斷。

決定：不做「分級軟/硬逾時」「非阻塞狀態機」等重方案，改以最小可用三件套覆蓋 80% 場景——普通使用者零心智負擔，進階設定摺疊保留細調。

## Considered Options

- **分級逾時（soft→hard timeout）**：語義精確，但 UI 需兩套時長＋狀態機，普通使用者難以理解
- **非阻塞驗證（下幀續驗，不卡主循環）**：可解決長等待卡群組，但需把 `verify` 改為跨幀狀態，改動面大（`_run_rule`/`_process_rules`/`StepContext`），風險高
- **固定三檔 preset＋expect=absent＋默認重試1次（採用）**：UI 只多「短/中/長」「出現/消失」兩選項，後端在 `_check_verify_condition` 加 `expect` 分支、`_run_rule` 加重試迴圈；改動局部、向下相容（舊任務無 `expect` 視為 `present`、無 `retries` 視為 1）

## Consequences

- `verify.preset` 為 GUI 快捷，正規化後仍寫 `timeout_ms`（2000/5000/10000），`poll` 依 preset 自適應（短 100ms / 中 300ms / 長 500ms），儲存仍為毫秒，舊任務讀取不受影響
- `verify.expect` 預設 `present`，僅 `absent` 時反轉判定（文字/圖片皆適用）；多成功分支以逗號 `,` 視為 OR（`勝利,失敗` 任一出現即成功），僅對 `type=detect` 生效
- `verify.retries` 預設 1、`retry_delay_ms` 預設 500ms，摺疊於進階；0 表示不重試（行為等同舊版）
- 逾時重試為「重跑動作＋重驗」一次（`click/key/drag/scroll/match_image` 皆適用），非單純重輪詢，避免「點沒點到」無法自癒
- 術語寫入 `CONTEXT.md`：Verify / VerifyCondition / VerifyPolicy / VerifyResult
