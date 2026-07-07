# main.log 改善計畫

## 問題現狀

從實際 `logs/main.log`（2026-07-07 約 200 行）分析：

| 事件 | 佔比 | 說明 |
|---|---|---|
| `任務已儲存：N 條規則` | ~80% | 500ms 防抖儲存每次觸發都寫入，編輯時每秒多次 |
| `群組「X」第 N 輪完成` | ~8% | 正常 |
| `所有選中/所有群組執行完畢，停止/持續運行中` | ~4% | 正常 |
| `規則「X」從 OCR 診斷新增` | ~4% | 正常 |
| `已載入任務「X」` | ~2% | 正常 |
| `規則「X」已刪除` / 複製 | ~2% | 正常 |

### 核心問題

**噪音太多：** `任務已儲存` 佔 80%，真實事件被淹沒。來源是 `gui/06_gui_main.py` 的 `_do_debounced_save()`，每次 debounce timer 觸發（任何編輯 blur、下拉選單變更等）都寫入。

**關鍵診斷事件完全缺失：** 使用者常見 bug report 包含「按了開始沒反應」、「規則沒觸發」、「亂點位置」，但 main.log 沒有任何能對應這些狀況的資訊。

---

## 遺漏邏輯位置檢查

> 註：現有 `_log()`（`05_main_loop.py:216`）內部 `self._logger.info(msg)` **永遠執行**（`_verbose` 僅控制 stdout print），
> 但部分呼叫點（視窗恢復、截圖失敗、畫面靜止）外包了 `if self._verbose:` 條件，導致非 verbose 模式時不進 main.log。
> 計畫以下「以關鍵字／方法名為準，行號僅供參考」，因行號可能隨修改偏移。

### 審查委員會糾正項目

審查報告所載問題以下標記：

| 編號 | 問題 | 來源 |
|---|---|---|
| R1 | `emergency_stop()` 未覆蓋（`05_main_loop.py` ~1050） | 審查 §2.1 |
| R2 | OCR 匹配無 `conf` 欄位（`OcrResult` 有但 `MatchResult` 無） | 審查 §2.2 |
| R3 | 點擊被擋需區分 CPS 與工具前景兩條獨立路徑 | 審查 §2.3 |
| R4 | `_handle_on_fail` notify+stop_groups 全無 log | 審查 §2.4 |
| R5 | 效能警告三者皆無 main.log | 審查 §2.5 |
| R6 | 階段三去重不可行（無現成機制、需重新設計） | 審查 §三、四 |

---

### A) 循環生命週期 — 無任何記錄

| 位置 | 方法 | 應記錄訊息 |
|---|---|---|
| `05_main_loop.py` | `__init__()` 完成後 | `應用啟動 v{version}，目標視窗「{title}」，載入 {N} 條規則` |
| `05_main_loop.py` | `start()` | `循環開始，目標視窗「{title}」` |
| `05_main_loop.py` | `stop()` | `循環停止` |
| `05_main_loop.py` | `pause()` | `循環暫停` |
| `05_main_loop.py` | `resume()` | `循環恢復` |
| `05_main_loop.py` | `emergency_stop()` ~1050 | `⚠ 緊急停止` **← R1 新增** |

### B) 視窗狀態

| 位置 | 方法 | 現狀 | 改為 |
|---|---|---|---|
| `05_main_loop.py` | `_loop()` 視窗遺失分支 | 僅 `on_window_lost` callback | `視窗「{title}」遺失，自動暫停` |
| `05_main_loop.py` | `_loop()` 視窗恢復分支 | `if self._verbose:` `_log()` | `視窗「{title}」已恢復`（always） |
| `05_main_loop.py` | `_loop()` 全部截圖失敗 | `if self._verbose and iteration%30:` `_log()` | `截圖失敗：{title}`（always，iteration%30 去重） |
| `05_main_loop.py` | `_loop()` 畫面靜止跳過 | `if self._verbose and iteration%30:` `_log()` | **維持現狀**（高頻，無資訊價值） |

### C) 規則執行結果

| 位置 | 方法 | 應記錄訊息 | 備註 |
|---|---|---|---|
| `05_main_loop.py` | `_handle_detect()` 匹配成功 | `規則「{name}」匹配文字「{text}」` | OCR match 無 `conf` 欄位，**不記錄 conf**（R2） |
| `05_main_loop.py` | `_handle_match_image()` 匹配成功 | `規則「{name}」模板匹配成功 (score={score})` | `MatchResult.score` 存在 |
| `05_main_loop.py` | `_handle_compare()` 比較結果 | `規則「{name}」比較 {num} {op} {val} → 成立/不成立` | 現有 `_log()` 僅 verbose |
| `05_main_loop.py` | `_handle_click()` 點擊成功 | `規則「{name}」點擊 ({sx},{sy}) 匹配「{text}」` | |
| `05_main_loop.py` | `_handle_click()` CPS 阻擋 | `規則「{name}」點擊略過：CPS 速率限制` | 路徑 L573-574 **← R3** |
| `05_main_loop.py` | `_handle_click()` 工具前景阻擋 | `規則「{name}」點擊略過：工具處於前景` | 路徑 L575-576 **← R3** |
| `05_main_loop.py` | `_handle_key()` 按鍵送出 | `規則「{name}」按鍵「{key}」` | |
| `05_main_loop.py` | `_handle_drag()` 拖曳 | `規則「{name}」拖曳 ({sx},{sy})→({ex},{ey})` | |
| `05_main_loop.py` | `_handle_scroll()` 滾輪 | `規則「{name}」滾輪 {direction} x{amount}` | |
| `05_main_loop.py` | `_handle_jump()` 跳轉 | `規則「{name}」跳轉至「{target}」` | |
| `05_main_loop.py` | `_handle_on_fail()` 動作觸發 | `規則「{name}」步驟{i} 失敗 → {action}` | |
| `05_main_loop.py` | `_handle_on_fail()` notify+stop_groups | `規則「{name}」通知並停止群組 {groups}` | 目前全無 **← R4** |
| `05_main_loop.py` | `_handle_notify()` 通知步驟 | `規則「{name}」通知：{msg}` | |

### D) 規則執行異常

| 位置 | 方法 | 現狀 | 改為 |
|---|---|---|---|
| `05_main_loop.py` | `_process_rules()` 背景異常 | `if self._verbose:` `_log()`（~L767） | 移除 verbose 條件，直接 `_log()` |
| `05_main_loop.py` | `_process_rules()` 並行異常 | `if self._verbose:` `_log()`（~L791） | 移除 verbose 條件，直接 `_log()` |
| `05_main_loop.py` | `_process_rules()` 循序異常 | `if self._verbose:` `_log()`（~L817） | 移除 verbose 條件，直接 `_log()` |
| `05_main_loop.py` | `_loop()` 主循環異常 | 僅 `on_error` callback（~L961） | `log_main(msg)`（always） |
| `05_main_loop.py` | `_loop()` 慢循環警告 | 僅 `on_warning` callback（~L954） | `log_main(msg)` 追加 |

### D-2) on_fail 記錄原則（重要）

`_handle_on_fail()` 預設 action 為 `"stop"`（L461），每幀比對失敗時靜默回傳
`StepResult("stop")` 讓規則下幀重試，這是正常行為，**不記錄**。

僅在下列情況記錄：
- `fail_duration_sec > 0` 首次進入容忍期（`規則「{name}」步驟{i} 失敗，進入 {N}s 容忍期`）
- `fail_duration_sec` 到期後執行動作（`規則「{name}」步驟{i} 失敗 {N}s 後執行 {action}`）
- action 非預設 stop：key / skip / jump / notify（each + stop_groups）

### E) 效能監控 ← R5

| 位置 | 方法 | 現狀 | 改為 |
|---|---|---|---|
| `05_main_loop.py` | `_on_rate_limit_exceeded()` | 僅 `on_error` callback | `log_main(msg)` 追加 |
| `05_main_loop.py` | `_on_cpu_warn()` | 僅 `on_warning` callback | `log_main(msg)` 追加 |
| `05_main_loop.py` | `_on_memory_warn()` | 僅 `on_warning` callback | `log_main(msg)` 追加 |

### F) GUI 事件（06_gui_main.py）

已存在（保留）：
- `已載入任務「{name}」，共 {N} 條規則`
- `從未歸類移除 N 條重複規則: ids`
- `規則「{name}」已刪除 (id=...)`
- `規則「{new}」從「{src}」複製 (id=...)`
- `規則「{name}」從 OCR 診斷新增 (id=...)`

需移除：
- `任務已儲存：N 條規則`（`_do_debounced_save()` 內）← **噪音來源**

需新增：
- `切換任務：{name}`（任務選取 comboBox 變更處）

### G) 其他核心模組

| 位置 | 目前 | 建議 |
|---|---|---|
| `04_rule_engine.py` 規則載入失敗 | `logging.warning` | 應改為 `log_main`（需 import） |
| `04_rule_engine.py` 規則解析失敗 | `logging.warning` | 應改為 `log_main` |
| `04_rule_engine.py` save_rules | `logging.info` | **保留**（開發者用，非使用者面向） |
| `02_ocr_engine.py` OCR warmup 失敗 | `logging.warning` | 應改為 `log_main`（需 import） |

---

## 改善方案

### 階段一：噪音消除

1. **移除 `_do_debounced_save()` 中的 `log_main`**
   - 理由：每次編輯 blur、下拉變更、排序拖曳都觸發，佔 log 80%+
   - 替代：僅在 `_flush_save()`（拖曳排序完成）與任務切換前記錄

### 階段二：核心事件追加

| 事件等級 | 頻率 | 記錄方式 |
|---|---|---|
| 生命週期（含 emergency_stop） | 極低 | 每事件一次 `log_main()` |
| 視窗狀態變更 | 低（lost/recovered） | 每次 `log_main()` |
| 規則匹配成功 | 中（每幀可能有數次） | 每次 `log_main()` |
| 動作執行 | 中（click/key/drag/scroll） | 每次 `log_main()` |
| on_fail 動作觸發（含 notify） | 中 | 每次 `log_main()` |
| 效能警告 | 低 | 每次 `log_main()` |
| 畫面無變化跳過 | 高（每秒多次） | **不記錄**（維持現狀） |
| 規則異常（background/parallel/sequential） | 低 | **已存在**（`_log()` always） |

### 階段三：按鍵情境去重（❌ 本輪擱置，R6）

審查指出無現成 `_frame_logged: set` 機制，且 `_frame_ocr_cache` 僅供 OCR 結果緩存，**不可誤用**。若需要去重：
- 需新設獨立的 `_frame_logged_events: set[str]`，每幀清空
- 或在 `_run_step` 層級以 `(rule.id, step_idx, step.type)` 為 key 去重
- **本輪先不實作**，待觀察實際 log 量再決定

### 階段四：版本號

在 `MainLoop.__init__()` 初始化完成後（`_load_rules()` 之後）加入：
```
應用啟動 v{version}，目標視窗「{title}」，載入 {N} 條規則
```

---

## 實作摘要（24 項 → 審查後修正為 29 項）

D 類 3 項（背景/並行/循序異常）現為 `if self._verbose:` 包覆，需移除 verbose 條件；追加 `emergency_stop()`。

| # | 檔案 | 改動 | 等級 | 狀態 |
|---|---|---|---|---|
| 1 | `core/05_main_loop.py` | `__init__` 完成時 log 版本+規則數 | A | 待實作 |
| 2 | `core/05_main_loop.py` | `start()` log 循環開始 | A | 待實作 |
| 3 | `core/05_main_loop.py` | `stop()` log 循環停止 | A | 待實作 |
| 4 | `core/05_main_loop.py` | `pause()` / `resume()` log 暫停/恢復 | A | 待實作 |
| 5 | `core/05_main_loop.py` | `emergency_stop()` log 緊急停止 | A | **← R1 追加** |
| 6 | `core/05_main_loop.py` | window lost → `視窗遺失，自動暫停` | B | 待實作 |
| 7 | `core/05_main_loop.py` | window recovered → `視窗已恢復`（always） | B | 待實作 |
| 8 | `core/05_main_loop.py` | 截圖全部失敗 → always（iteration%30 去重） | B | 待實作 |
| 9 | `core/05_main_loop.py` | `_handle_detect` OCR 匹配成功 | C | 待實作（**不記 conf**） |
| 10 | `core/05_main_loop.py` | `_handle_match_image` 匹配結果 | C | 待實作 |
| 11 | `core/05_main_loop.py` | `_handle_compare` 比較結果（verbose→always） | C | 待實作 |
| 12 | `core/05_main_loop.py` | `_handle_click` 點擊結果 | C | 待實作 |
| 13 | `core/05_main_loop.py` | `_handle_click` CPS 阻擋（獨立 log） | C | **← R3** |
| 14 | `core/05_main_loop.py` | `_handle_click` 工具前景阻擋（獨立 log） | C | **← R3** |
| 15 | `core/05_main_loop.py` | `_handle_key` 按鍵送出 | C | 待實作 |
| 16 | `core/05_main_loop.py` | `_handle_drag` 拖曳 | C | 待實作 |
| 17 | `core/05_main_loop.py` | `_handle_scroll` 滾輪 | C | 待實作 |
| 18 | `core/05_main_loop.py` | `_handle_jump` 跳轉 | C | 待實作 |
| 19 | `core/05_main_loop.py` | `_handle_on_fail` on_fail 動作觸發 | C | 待實作 |
| 20 | `core/05_main_loop.py` | `_handle_on_fail` notify+stop_groups | C | **← R4** |
| 21 | `core/05_main_loop.py` | `_handle_notify` 通知步驟 | C | 待實作 |
| 22 | `core/05_main_loop.py` | `_process_rules()` 背景異常（移除 verbose 條件） | D | 待實作 |
| 23 | `core/05_main_loop.py` | `_process_rules()` 並行異常（移除 verbose 條件） | D | 待實作 |
| 24 | `core/05_main_loop.py` | `_process_rules()` 循序異常（移除 verbose 條件） | D | 待實作 |
| 25 | `core/05_main_loop.py` | `_loop()` 慢循環警告（`on_warning`→`log_main`） | D | 待實作 |
| 26 | `core/05_main_loop.py` | `_loop()` 主循環異常（always） | D | 待實作 |
| 27 | `core/05_main_loop.py` | `_on_rate_limit_exceeded()` | E | 待實作 |
| 28 | `core/05_main_loop.py` | `_on_cpu_warn()` | E | 待實作 |
| 29 | `core/05_main_loop.py` | `_on_memory_warn()` | E | 待實作 |
| 30 | `gui/06_gui_main.py` | 移除 debounced save 的 log_main | 噪音 | 待實作 |
| 31 | `gui/06_gui_main.py` | 任務切換 log | F | 待實作 |
| 32 | `core/02_ocr_engine.py` | OCR warmup 失敗改 log_main | G | 待實作 |
| 33 | `core/04_rule_engine.py` | 規則載入/解析失敗改 log_main | G | 待實作 |

---

## 實作拆分建議（依審查 §四）

| Commit | 內容 | 項目編號 | 風險 |
|---|---|---|---|
| 1 | 噪音消除 + GUI：移除 debounced save log | 29, 30 | 低 |
| 2 | 生命週期 + 視窗狀態 + 版本號：A + B 類 + #1 | 1-8 | 低 |
| 3 | 規則執行 + 異常 + 效能：C + D + E 類 | 9-29 | 中（注意 CPS/前景區分） |
| 4 | 跨模組：02_ocr_engine + 04_rule_engine | 32, 33 | 低 |
| — | 階段三去重 | — | ❌ 擱置（R6） |

---

## 邏輯遺漏檢查結論（審查後更新）

已完整掃描 `core/05_main_loop.py`（1774 行）每條執行路徑，並經審查委員會確認：

- **10 種步驟類型**（detect / click / key / wait / jump / drag / scroll / match_image / compare / notify）全部檢查
  - wait → 不記錄（高頻、無資訊價值）
  - 其餘 9 種 → 均有對應事件應記錄
- **3 種群組模式**（sequential / parallel / background）全部覆蓋
- **GUI 操作路徑**（刪除 / 複製 / 診斷新增 / 任務載入 / 任務切換 / 自動清理）全部覆蓋
- **例外處理**（4 處 try-except）全部覆蓋
- **審查補遺**：`emergency_stop()`、CPS 與前景需獨立區分、on_fail notify 路徑全無 log

### 審查後結論

- 計畫方向正確，80% 噪音來源診斷準確
- 主要修正：D 類 3 項非「已存在」（包在 `verbose` 內），追加 R1-R5 缺漏、慢循環警告、on_fail 預設 stop 不記錄
- 修正後總計 **33 項改動**，拆分 **4 個 commit** 實作
