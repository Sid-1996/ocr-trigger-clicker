# 條件清單（Condition List）移除計畫

> 本計畫用於指導移除 `condition_list` 步驟類型的完整工作。

---

## 專案背景

- **專案名稱**：ocr-trigger-clicker
- **專案路徑**：`C:\Code play first\ocr-trigger-clicker`
- **技術棧**：Python 3.12 + PyQt6 + RapidOCR + AutoHotkey v2
- **決策依據**：
  - `condition_list` 在實際 `tasks/` 任務場景中沒有被使用（診斷確認無任何任務使用此步驟）
  - 其功能（多條件 OCR 偵測 + 動作執行）可由現有的 `detect` + `click`/`key`/`jump` 步驟組合完全取代
  - 為維持產品簡潔性，決定移除此步驟類型

### 移除範圍（診斷結果）

`condition_list` 是一種複合步驟類型，內部執行 OCR 偵測 + 條件動作分派。涉及以下檔案：

| 檔案 | 涉及行數 | 內容 |
|---|---|---|
| `core/rule_models.py` | 20-31 | `Condition`、`ConditionListParams` dataclass |
| `core/rule_serialization.py` | 22-23, 29-90 | import、`_migrate_condition_list_to_step()` 遷移函式 |
| `core/rule_migration.py` | 49-53, 190-224 | `_STEP_DEFAULTS` 條目、`_normalize_step_params` 中的正規化區塊 |
| `core/05_main_loop.py` | 159, 201, 229, 696-751, 765, 1180, 1878-2124 | `_condition_hit_counts`（dead code）、`_update_has_detect` 引用、`_handle_condition_list` handler、dispatch table 條目、Tests 26-29 |
| `gui/06_gui_main.py` | 360, 374, 487-499, 953-956, 2237-2478, 3265, 4632-4640 | icon/label map、summary text、form factory、`_CondCardWidget` + `_ConditionListStepForm` 類別、menu entry、validation |
| `ARCHITECTURE.md` | 128, 142, 211-212 | Step 類型對照表、遷移說明、triggered 說明 |
| `tasks/starsavior-Daily Tasks.json` | 多處 | 舊版 null 欄位（`use_condition_list: false`、`condition_list: null`） |

**注意**：`_condition_hit_counts`（`05_main_loop.py:159,201,1180`）是 dead code —— 初始化和 clear 但從未被讀寫，一併清除。

---

## 階段 0：前置診斷（✅ 已完成）

診斷確認：
- [x] 無任何 `.json` 任務檔案使用 `"type": "condition_list"` 或 `"use_condition_list": true`
- [x] 無專門的元件目錄或獨立型別檔案
- [x] 所有引用集中在上述 6 個程式碼檔案 + 1 個文件檔案

---

## 階段 1：程式碼移除

### 任務 1.1：`core/rule_models.py` — 移除 dataclass

刪除第 19-31 行（`Condition` 和 `ConditionListParams`）。

### 任務 1.2：`core/rule_serialization.py` — 移除 import + 遷移函式

1. 移除第 22-23 行的 `Condition`、`ConditionListParams` import
2. 移除第 29-84 行的 `_migrate_condition_list_to_step()` 函式
3. 移除第 90 行對該函式的呼叫：`d = _migrate_condition_list_to_step(d)`

### 任務 1.3：`core/rule_migration.py` — 移除預設值 + 正規化

1. 移除 `_STEP_DEFAULTS` 字典中的 `"condition_list"` 條目（第 49-53 行）
2. 移除 `_normalize_step_params()` 中的 `elif step_type == "condition_list":` 區塊（第 190-224 行）

### 任務 1.4：`core/05_main_loop.py` — 移除 handler + dead code + tests

1. 移除 `_condition_hit_counts` 初始化（第 159 行）與 clear（第 201 行）—— dead code
2. 移除 `_update_has_detect` 中的 `"condition_list"` 引用（第 229 行）
3. 移除 `_handle_condition_list` 方法（第 696-751 行，~56 行）
4. 移除 `_run_step` dispatch table 中的 `"condition_list"` 條目（第 765 行）
5. 移除測試環境中的 `_condition_hit_counts = {}`（第 1180 行）
6. 移除 Tests 26-29（第 1878-2124 行，~247 行），最後一行改為 `print("\n=== All 25 tests passed ===")`

### 任務 1.5：`gui/06_gui_main.py` — 移除 GUI 元件

1. 移除 `_STEP_ICONS` 中的 `"condition_list": "📋"`（第 360 行）
2. 移除 `_STEP_TYPE_LABELS` 中的 `"condition_list": "條件清單"`（第 374 行）
3. 移除 `_step_summary_text()` 中的 `condition_list` 分支（第 487-499 行）
4. 移除 `_StepListWidget._make_form()` 中的 `condition_list` 分支（第 953-956 行）
5. 移除 `_CondCardWidget` 類別（第 2237-2378 行）和 `_ConditionListStepForm` 類別（第 2380-2478 行），共 ~242 行
6. 移除步驟下拉選單中的 `("condition_list", "📋 條件清單")`（第 3265 行）
7. 移除 `_on_steps_changed()` 驗證中的 `condition_list` 分支（第 4632-4640 行）

---

## 階段 2：功能確認（無需補強）

`condition_list` 是一個複合步驟（在一個步驟內做多條件 OCR + 動作分派），但這功能可由多個獨立步驟組合達成：
- `detect` 步驟做 OCR 偵測 + `on_fail` 控制流程
- `click`/`key`/`jump` 步驟執行動作
- 群組模式（sequential/parallel）提供多規則排列組合

現有步驟系統已完全覆蓋 `condition_list` 的使用場景，**無需額外補強**。

---

## 階段 3：驗證

### 任務 3.1：Ruff lint + format

```powershell
pwsh -Command "Set-Location 'C:\Code play first\ocr-trigger-clicker'; ruff check --fix .; ruff format ."
```

### 任務 3.2：Self-check 測試

```powershell
python -c "import sys,runpy; sys.path.insert(0,'.'); runpy.run_path('core/04_rule_engine.py', run_name='__main__')"
```

```powershell
python -c "import sys,runpy; sys.path.insert(0,'.'); runpy.run_path('core/05_main_loop.py', run_name='__main__')"
```

預期結果：全部通過。

### 任務 3.3：graphify update

```powershell
pwsh -Command "Set-Location 'C:\Code play first\ocr-trigger-clicker'; graphify update ."
```

---

## 階段 4：文件更新

### 任務 4.1：`ARCHITECTURE.md`

- 移除 Step 類型對照表中的 `condition_list` 行（第 128 行）
- 移除 `_migrate_condition_list_to_step()` 遷移說明（第 142 行）
- 更新 `ctx.triggered` 說明，移除 `condition_list` 相關描述（第 211-212 行）

### 任務 4.2：`tasks/starsavior-Daily Tasks.json`

移除所有規則中的 legacy null 欄位（`use_condition_list`、`condition_list`、`condition_list_advance_on_no_match`），保持檔案整潔。

### 任務 4.3：`CHANGELOG.md`

在最新版本區塊新增移除記錄。

### 任務 4.4：`REMOVE_CONDITION_LIST_PLAN.md`

任務完成後刪除此計畫檔案。

---

## 完成確認清單

- [ ] 階段 1：所有 `condition_list` 相關程式碼已移除
- [ ] 階段 2：確認無功能遺失
- [ ] 階段 3：ruff 通過、self-check 測試全部通過
- [ ] 階段 4：文件已更新、CHANGELOG 已記錄
- [ ] git commit + push

---

*計畫更新日期：2026-07-15*
