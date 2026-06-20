# 比較規則（Compare Rule）實作規格

## 背景與命名

工具現有唯一規則類型統一命名為**觸發規則（Trigger Rule）**。本次新增第二種類型：**比較規則（Compare Rule）**。兩種規則可任意串接。

| rule_type | 行為 |
|-----------|------|
| `trigger` | 持續 OCR 監看，符合文字條件就執行動作（現有，不動） |
| `compare` | 多輪收集 OCR 數值，比較後選最佳輪次執行動作（新增） |

---

## 建議串接模式（寫入 GUI tooltip / 說明文字）

```
規則 A — 觸發規則（有動作）
  OCR 看到關鍵字 → 點擊進入畫面

  ↓ 畫面過場（時間不確定）

規則 B — 觸發規則（純 OCR，無動作）
  OCR 確認目標畫面關鍵字出現 → 畫面就緒信號

  ↓ 畫面確認有效

規則 C — 比較規則
  多輪收集數值 → 選最佳 → 執行確認動作

  ↓ 完成，回到觸發規則循環
```

規則 B 作為畫面就緒偵測器，利用現有 OCR 比對機制確認過場結束，不需要猜固定等待時間。

---

## 比較規則執行流程

1. 讀當前畫面算第 1 輪（不先按重試鍵）
2. 對每個啟用的 ROI 執行輪詢 OCR：每 200ms 重試，偵測到數值出現才繼續，超時上限 `round_wait_ms`（預設 3000ms）
3. 從 OCR 字串提取數值（見數值解析規則）
4. 記錄本輪所有 ROI 的數值
5. 判斷是否立即達標（所有啟用的 ROI 均滿足門檻）→ 若是，立即執行確認動作，結束比較規則
6. 若未達標且未到 `max_rounds`，按 `retry_key` → 回到步驟 2

### N 輪結束後分支

| 情況 | 處理 |
|------|------|
| 有輪次所有 ROI 均達標 | 依主要 ROI 比較方向選最佳輪次，執行確認動作 |
| 有輪次部分 ROI 達標 | 從「ROI-A 達標」的輪次中依比較方向選最佳，執行確認動作 |
| 全部輪次未達標或解析失敗 | 執行 `on_all_fail` 指定的觸發規則 ID，記錄警告 |

---

## 數值解析規則（通用）

不依賴 OCR 文字內容，從結果字串中提取數字：

```python
import re
nums = re.findall(r'\d+(?:\.\d+)?', ocr_text)
value = float(nums[index]) if nums else None
# index: 0 = "first"（預設），-1 = "last"（使用者可選）
```

| OCR 結果範例 | first | last |
|-------------|-------|------|
| `失敗率 35%` | 35 | 35 |
| `106%` | 106 | 106 |
| `HP 1250/2000` | 1250 | 2000 |
| `命中率 92.5%` | 92.5 | 92.5 |

---

## Rule dataclass 新增欄位

| 欄位 | 型態 | 預設值 | 說明 |
|------|------|--------|------|
| `rule_type` | str | `"trigger"` | `"trigger"` 或 `"compare"` |
| `retry_key` | str | `""` | 每輪換下一組的按鍵 |
| `confirm_action_type` | str | `"key"` | `"key"` 或 `"click"` |
| `confirm_key` | str | `""` | 達標時執行的按鍵 |
| `confirm_x` | int | `0` | 達標時點擊 X 座標 |
| `confirm_y` | int | `0` | 達標時點擊 Y 座標 |
| `max_rounds` | int | `5` | 最多嘗試幾輪 |
| `round_wait_ms` | int | `3000` | 每輪輪詢 OCR 的超時上限（ms） |
| `roi_count` | int | `1` | 啟用的 ROI 數量（1 或 2） |
| `roi_a` | dict | `{x,y,w,h}` | 第一個擷取區域 |
| `roi_a_compare` | str | `"higher_better"` | `"higher_better"` 或 `"lower_better"` |
| `roi_a_threshold` | float | `0` | ROI-A 達標門檻 |
| `roi_a_value_pick` | str | `"first"` | `"first"` 或 `"last"` |
| `roi_b` | dict | `{x,y,w,h}` | 第二個擷取區域（`roi_count=2` 時啟用） |
| `roi_b_compare` | str | `"lower_better"` | `"higher_better"` 或 `"lower_better"` |
| `roi_b_threshold` | float | `50` | ROI-B 達標門檻 |
| `roi_b_value_pick` | str | `"first"` | `"first"` 或 `"last"` |
| `on_all_fail` | str | `""` | 全輪失敗時跳轉的觸發規則 ID |

---

## 邊界條件

```
OCR 解析不到數字（空字串/純文字） → 本輪該 ROI 跳過，不納入比較
輪詢超時（round_wait_ms 內無有效數值） → 同上，跳過本輪
所有輪次均跳過 → 執行 on_all_fail，記錄警告
數值相同時 → 選順序最前的輪次
roi_count=1 時 → roi_b 所有欄位忽略，GUI 隱藏
```

---

## 需修改的檔案

| 檔案 | 修改內容 |
|------|----------|
| `core/04_rule_engine.py` | `Rule` dataclass 新增上表所有欄位；`_rule_to_dict` / `_dict_to_rule` / `_FIELD_DEFAULTS` 同步更新 |
| `core/05_main_loop.py` | `_process_rules()` 依 `rule_type` 分流；新增 `_run_compare_rule()` 實作多輪收集、輪詢等待、最佳選取、失敗分支 |
| `gui/06_gui_main.py` | 編輯表單頂部新增 `rule_type` 下拉；依類型切換欄位群組；`roi_count` 控制 ROI-B 欄位顯示；`_save_current_rule()` / `_show_rule_detail()` 讀寫新欄位 |

## 不需修改的檔案

`core/01_screenshot.py`、`core/02_ocr_engine.py`、`core/03_ahk_bridge.py`、`gui/07_gui_roi.py`、`gui/09_ocr_debug.py`、`gui/13_gui_click_picker.py`

`on_all_fail` 的失敗序列完全由現有觸發規則串接實現，無需新機制。
