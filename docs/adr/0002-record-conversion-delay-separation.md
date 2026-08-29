# 錄製轉換延時與全域延時設定分離，穩定性優先

Status: accepted（2026-08-30）

錄製操作（F9）轉出的規則原先共用全域「動作後延遲／偵測後延時」預設；使用者把全域延時調成 0
（常見於手動規則想全速跑）會直接讓錄製腳本失去所有緩衝，穩定性被不相干的全域設定綁架。
決定：錄製轉換改用專屬的「錄製操作設定」（`record_after_delay_ms` / `record_detect_after_delay_ms`），
預設 500ms（穩定性優先，寧慢勿斷），與全域延時**徹底分離**——錄製轉換完全不再讀
`default_after_delay_ms` / `default_detect_after_delay_ms`。

## Considered Options

- **沿用全域延時**（原狀）：零工，但兩種需求（手動規則的節奏 vs 錄製腳本的穩定同步）互相污染
- **初值帶全域一次、之後獨立**：語義曖昧，使用者分不清哪邊生效
- **徹底分離＋內建 500ms 兜底（採用）**：設定窗新增「錄製操作」兩列；defaults 缺 key 時
  `core/20_recorder_convert.py` 內建 `_RECORD_*_AFTER_DELAY_MS = 500` 兜底（保護離線/舊設定檔路徑）；
  使用者明確設 0 仍尊重（不等待）

## Consequences

- 僅對**之後的新轉換**生效；已轉換存檔的舊任務不回溯改寫（可能是使用者手工調過的產物）
- 設定 key 的單一事實來源是 `gui/rule_config_controller.py` 的 `DEFAULTS`（500），
  core 內建常數僅為 defaults=None 時的第二道防線，兩處數字需一致
- 全域 tooltip 已移除「或錄製轉換規則時」描述，避免誤導
