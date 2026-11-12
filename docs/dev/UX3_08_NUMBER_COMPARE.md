# UX3-08 查核：數字比對步驟易用性（2026-11-12）

> **編號說明**：本專案既有的 `UX3-08`（見 `UX_PHASE3_AUDIT.md`／`UX_PHASE3B_AUDIT.md`）
> 指的是「OCR Debug 追加步驟靜默」，與本節是不同項目。本節依本次任務書的編號記錄
> 「數字比對易用性」，**不重新編號、不改動既有項目**，兩項可並存。

## 1. 現象與根因

| 現象 | 根因 |
|---|---|
| 數值欄位顯示 `55.0000000000` | `_CompareStepForm` 的數值用 `_NoWheelDoubleSpin` 並 `setDecimals(15)`；Qt 依該精度補滿尾隨零（單純顯示問題，值本身正確） |
| 「數字格式」直接顯示 `-?\d+\.?\d*` | 該欄位原本就是一個 raw `QLineEdit`，把 core 用的正規表示式原樣端到使用者面前；沒有白話選項，也沒有「哪裡錯、怎麼修」的說明 |
| 格式錯誤只變紅框 | `_validate_pattern()` 只設定 `QLineEdit` 的樣式與 tooltip，沒有常駐文字說明 |

實際呼叫鏈（改動前後一致）：

```
_CompareStepForm.save()
  → step.params["pattern"] = <字串>
  → core/05_main_loop.py:1206 _handle_compare()
      pattern = params.get("pattern", r"-?\d+\.?\d*")
      m = re.search(pattern, combined)      # 只取第一個匹配
      num = float(m.group())                # 失敗 → on_fail
      ops[operator](num, value)             # 精確浮點比較
```

`core/rule_migration.py:34` 的預設值同為 `-?\d+\.?\d*`，本次未新增 JSON 欄位、未做資料遷移。

## 2. 數值顯示（改善 A）

- 新增 `_TrimDoubleSpin(_NoWheelDoubleSpin)`，只覆寫 `textFromValue()`：
  `repr(round(float(value), decimals()))` → 去掉尾隨 `.0` → `-0` 正規化為 `0`
  → 小數點換成目前 locale 的符號。
- **只影響顯示字串**：不呼叫 `setText()`、不改 `decimals()`、不改 widget 值；
  `value()`、存檔值、比較結果與改動前完全相同（`setDecimals(15)` 保留）。
- 編輯中（使用者正在打字、未提交）不會被重新格式化，游標與輸入內容不受影響。
- 步驟摘要改用 `_fmt_number()`（同一套去掉尾隨零規則），清單不再出現長串零。

顯示對照：

| 值 | 顯示 | 存檔值 |
|---|---|---|
| `55.0` | `55` | `55.0` |
| `55.5` | `55.5` | `55.5` |
| `55.1234` | `55.1234` | `55.1234` |
| `1.23456789012345` | `1.23456789012345` | 同值（精度未降） |

## 3. 數字格式（改善 B）

模組層級新增 `COMPARE_NUMBER_FORMATS`（選項資料、標籤 key、正規表示式、說明 key）：

| 選項 | 正規表示式 | 語意 |
|---|---|---|
| 一般數字（預設） | `-?\d+\.?\d*` | 取第一個數字，整數與小數都支援；**與 core 預設完全相同** |
| 整數 | `-?\d+` | 只取整數段（`55.5` → `55`） |
| 小數 | `-?\d+\.\d+` | 必須有小數點（`55` 不匹配） |
| 自訂格式（進階） | 使用者輸入 | 保留原本的正規表示式能力 |

- 常用格式是基本區的白話 `QComboBox`，下方一行說明；選「自訂格式」才自動展開進階區。
- 正規表示式欄位仍在進階區（label 改為「自訂格式」），另加常駐錯誤說明
  `step_form.regex_invalid_hint`（無效時顯示「格式不正確：括號或反斜線沒有配對…」）。
- 切換格式時，進階欄位同步顯示該選項實際使用的表示式，使用者可驗證、可再修改；
  手動輸入過的自訂內容會記在 `_custom_draft`，切換後再切回可還原。
- **沒有獨立「百分比」選項**：`_handle_compare` 只把 regex 匹配到的字串丟進 `float()`，
  `%` 從不參與轉換（`26%` 取 26，不會變 0.26）。加一個只換名字的選項會讓選單更難懂，
  故以「一般數字」涵蓋並在提示中不誤導。

## 4. 舊資料相容性

| 情境 | 行為 |
|---|---|
| `pattern` 恰為某預設字串 | 選單顯示對應選項；未動就不改寫，存檔字串逐字相同 |
| `pattern` 為自訂值（含 `\d{2,4}`、空字串、前後空白） | 選單顯示「自訂格式」，欄位保留原值 |
| 只開啟編輯器、未儲存 | 不寫入任何變更 |
| 使用者主動切換格式 | 欄位同步換成該預設表示式，存檔即採用（可見、可預期） |
| 舊規則存檔 | `save()` 寫回 `self._pattern.text()`；本次移除原本的 `.strip()`，連前後空白都逐字保留 |

選單狀態是**由既有 `pattern` 字串回推**（`_compare_format_for_pattern()`，僅完全相等才算預設），
因此不需要新增 JSON 欄位、不需要遷移，也不會在載入時覆蓋舊值。

## 5. 驗證

- `tests/test_ux3_08_number_compare.py`（33 項）：顯示去零、值/存檔精度不變、摘要格式、
  選單回推、舊 pattern 逐字保留、切換／還原、無效 regex 提示，以及三種格式在
  `_handle_compare` 的真實匹配語意（整數不吃小數段、小數拒絕純整數、`26%` 取 26）。
- 相關既有套件：`test_numeric_safety`／`test_step_editor_*`／`test_fail_duration_sec`／`test_i18n` 全綠。
- 全套 `pytest --no-cov -q`：1869 passed、13 skipped（Frida/整合測試因環境 skip）。

## 6. 原型

`devtools/ux_prototypes/phase3b/ux3_08_number_compare.html`（改善前後對照、格式語意表、
操作流程、相容性表；可直接在瀏覽器操作選單與數值欄位）。
