# Phase 2 — Step Editor 審查報告（供討論）

> 產出日期：2026-10-30
> 適用版本：`master` @ `8674838`（本地領先 `origin/master` 4 個 commit，**尚未 push**）
> 狀態：**程式碼完成、驗證通過，但有 2 項決策待拍板，故尚未 commit**

---

## 0. 一頁摘要

| # | 項目 | 狀態 | 說明 |
|---|---|---|---|
| 1 | Phase 2-1 `fail_duration_sec` 載入遺失 | ✅ 已修，待 commit | 修復前 9 項測試失敗，修復後 73 項全過 |
| 2 | Phase 2-2 wait/jump 編輯表單接線 | ✅ 已做，待 commit | 接線前 22 項測試失敗，接線後 39 項全過 |
| 3 | 人工 GUI 驗收 4 項 | 3 通過 / 1 無法重現 | 無法重現者**非缺陷**，原因已定位（見 §4.1） |
| 4 | 新發現缺陷：空 `rule_id` 靜默改寫 | ⚠️ **待決策** | 本次接線才第一次對使用者生效（見 §5） |
| 5 | 已知待修問題 6 項 + 1 項超範圍 | 📋 僅記錄未修 | 見 §6 |
| 6 | 全套測試 | ✅ 661 passed | 基線 549 → 622 → 661 |
| 7 | `ruff check .` | ✅ 全綠 | |

**一句話總結**：Phase 2-1 與 2-2 兩項修改程式碼與測試都已完成且全綠，卡在「1 個新缺陷要不要修」與「怎麼 commit」兩個決策上。

---

## 1. 目前 Git 狀態

```
branch : master
HEAD   : 8674838  fix: 修正 OCR Debug 驗證狀態與 i18n key 對應
origin/master : c3625b6（領先 4 個 commit，未 push）

 M core/rule_migration.py          ← Phase 2-1（+8 行）
 M gui/06_gui_main.py              ← Phase 2-2（+11 行）
?? tests/test_fail_duration_sec.py ← Phase 2-1（73 項測試）
?? tests/test_step_editor_types.py ← Phase 2-2（39 項測試）
?? .agents/                        ← 工具檔，未動
?? skills-lock.json                ← 工具檔，未動
```

`git diff --stat`：`2 files changed, 19 insertions(+)`，無刪除行。

---

## 2. Phase 2-1：`fail_duration_sec` 在載入時被靜默丟失（已修，待 commit）

### 2.1 缺陷

`on_fail` 的 step-level（6 選，含 stop）與 verify-level（5 選，無 stop）**分屬兩個層級**（依 `CONTEXT.md:135` 與 `core/05_main_loop.py:2042`），不可合併。

GUI 寫入 stop + 容忍期時會存成 dict：

```python
{"action": "stop", "fail_duration_sec": 9.0}
```

但 Core 在載入時的正規化函式 `core/rule_migration.py:_normalize_on_fail()` 沒有 `action == "stop"` 分支，dict 會被壓成裸字串 `"stop"`，**`fail_duration_sec` 就此蒸發**。

實測症狀（端到端）：存檔前 `9.0` → 存檔再開變成 `0.0`。

### 2.2 修復

只動一處：`core/rule_migration.py:_normalize_on_fail()`，新增 `elif action == "stop":` 分支（+8 行）。

```python
elif action == "stop":
    # stop 搭配容忍期：GUI 寫入 {"action":"stop","fail_duration_sec":N}，
    # 不可壓成裸字串 "stop"，否則容忍期在重新載入後被靜默丟棄，
    # 使用者設定的「持續失敗 N 秒」會在存檔再開後失效。
    # fd == 0 時維持既有向下相容寫法（純字串 "stop"）。
    if fd > 0:
        return {"action": "stop", "fail_duration_sec": fd}
    return "stop"
```

**只有一種輸入形狀改變**：`{"action":"stop","fail_duration_sec":N}` 且 `N > 0`。
`N == 0` 維持原本的裸字串 `"stop"`，16 種輸入逐一比對確認其餘 15 種完全相同。

### 2.3 驗證

- `tests/test_fail_duration_sec.py`：73 項測試，全過
- 修復前該檔 9 項失敗（含端到端 `assert 0.0 == 9.0`，精確重現症狀）
- 全套 `pytest`：**661 passed**

### 2.4 設計界線（避免討論時走偏）

- 不抽 `_OnFailEditor` 共用元件（那是 Phase 2-4 的議題）
- 不動 GUI（GUI 層本來就有防禦性 float 轉換，見 `gui/06_gui_main.py:1202-1207` / `1906-1911` / `3656-3661`）
- 不動 JSON schema、不動 `on_fail` 的兩層級設計

---

## 3. Phase 2-2：wait / jump 可新增但不可編輯（已做，待 commit）

### 3.1 缺陷

`_StepListWidget._build_form()`（`gui/06_gui_main.py:884`）沒有 `wait` / `jump` 分支 → 這兩型 step 點開時回 `None`，表單從不顯示，等於只能新增、不能編輯。

`_WaitStepForm`（`gui/06_gui_main.py:3984-4001`）與 `_JumpStepForm`（`gui/06_gui_main.py:4004-4031`）**早已存在**，只是從未被呼叫到。

### 3.2 修復

只接通既有表單，**不改表單設計、不改 UI 語意、不動 Core、不動 JSON schema**（+11 行）：

```python
if t == "wait":
    return _WaitStepForm(self, step, idx)
if t == "jump":
    return _JumpStepForm(
        self,
        step,
        idx,
        self._rules_provider,
        self._groups_provider,
        self._rule_id,
    )
```

### 3.3 驗證

`tests/test_step_editor_types.py`：39 項測試全過（接線前 22 項失敗）。

涵蓋範圍：

- **型別覆蓋**：11 種 step type 的 `_build_form` 分派
- **Wait**：回填 / 保存 / 重開 / JSON round-trip / 單位（毫秒整數；Core 端 `core/05_main_loop.py:1602-1612` 用 `ms/1000.0`）
- **Jump**：群組階層（`群組 › 規則`）、`exclude_rule_id` 自我排除、目標不存在時顯示「(未知: xxx)」且保留原值不被靜默換人
- **舊資料相容**：未知 step type 回 `None` → `_toggle_expand` 的 `if form:` 守衛（L800）→ 不呼叫 `save()` → params 原封不動

### 3.4 額外產物

`_populate_rule_combo()`（`gui/06_gui_main.py:254-269`）本來就支援「群組 › 規則」階層與未分群規則平鋪，本次直接沿用，**未新增邏輯**。

---

## 4. 人工 GUI 驗收結果

| 項目 | 結果 |
|---|---|
| 第 1 項 | ✅ 通過（使用者回報） |
| 第 2 項 | ✅ 通過（使用者回報） |
| **第 3 項**：目標已被刪除的既有 jump step → 點開 → 確認顯示「(未知: xxx)」而非被自動換成其他規則 → 直接保存 → 確認目標未被改寫 | ❌ **無法人工重現** |
| 第 4 項 | ✅ 通過（使用者回報） |

### 4.1 第 3 項為何無法重現（證據鏈）

**結論：無法重現是預期行為，不是缺陷。**

關鍵在 `gui/06_gui_main.py:6880-6890`（`_delete_rule`）：

```python
# 自動清理其他規則指向被刪規則的參照（含 on_fail: jump）
for r in self._rules:
    for s in r.steps:
        if s.type == "jump" and s.params.get("rule_id", "") == rule.id:
            s.params["rule_id"] = ""
```

在 GUI 裡刪掉目標規則時，指向它的 jump 引用會**自動被清成空字串 `""`**。
所以「孤兒 `rule_id`」（指向已不存在的 id 的**非空**字串）在正常 GUI 操作流程中**根本不會產生**。

再看 `_JumpStepForm.__init__`（`gui/06_gui_main.py:4014-4028`）：

```python
idx_r = self._combo.findData(current_id)
if idx_r >= 0:
    self._combo.setCurrentIndex(idx_r)
elif current_id:  # ← 只有非空才進來
    self._combo.addItem(T("step_form.unknown_rule", id=current_id), current_id)
    self._combo.setCurrentIndex(self._combo.count() - 1)
```

| `current_id` | 分支 | combo 結果 | save 後 |
|---|---|---|---|
| 非空且存在 | `idx_r >= 0` | 選中該規則 | 保留原值 ✅ |
| **非空但不存在**（情況 A） | `elif current_id:` | **顯示「(未知: xxx)」並選中** | **保留原值 ✅** |
| **空字串 `""`**（情況 B） | 兩者都不成立 | **停在第一項** | **變成第一條規則 ❌** |

→ 「(未知: xxx)」只在 `rule_id` 是「非空且不存在的 id」時出現。
→ 該狀態只能由**手改 JSON** 或**匯入他人任務**產生，GUI 內無法自產。

### 4.2 替代驗證（不需要 GUI，已通過）

```powershell
uv run python -m pytest tests/test_step_editor_types.py -k "missing_target" --no-cov -q
```

實測結果：`1 passed, 38 deselected`。該測試覆蓋情況 A 的完整路徑：
rule_id 指向不存在的 id → combo 出現「(未知: xxx)」並選中 → `save()` 後值未被改寫。

### 4.3 若要人工親眼確認的操作步驟

建議**不要改版控檔案**，改用副本：

1. 複製 `docs/tasks/StarSavior-每日任務.json` 為暫存副本
2. 把其中一個 jump 的 `rule_id` 改成不存在的 id
   （該檔共有三處 jump：`rule_99561389` 在 **L2569**、**L2659**；`rule_5fdede7a` 在 **L2749**）
3. 在程式內匯入副本（或放進 `%APPDATA%\ocr-trigger-clicker\tasks\`）
4. 重開任務 → 展開該規則 → 點開 jump step → 應見「(未知: rule_已不存在)」
5. 直接儲存 → 確認 `rule_id` 仍是 `rule_已不存在`
6. 刪掉匯入的副本任務

> 若直接改 `docs/tasks/` 內的檔，測完請 `git checkout -- docs/tasks/StarSavior-每日任務.json` 還原。

### 4.4 i18n 文案現況

| 語言 | key | 文案 | 位置 |
|---|---|---|---|
| 繁中 | `step_form.unknown_rule` | `(未知: {id})` | `i18n/zh_TW.json:523` |
| 英文 | `step_form.unknown_rule` | `(Unknown: {id})` | `i18n/en.json:523` |
| 日文 | `step_form.unknown_rule` | `（不明: {id}）` | `i18n/ja.json:529` |

---

## 5. 新發現缺陷：空 `rule_id` 被靜默改寫（P3）

### 5.1 為什麼是「本次接線才第一次生效」

Phase 2-2 之前，`_build_form()` 對 `jump` 回 `None` → **jump 表單從未被開啟過** → 下面這個缺陷在現實中不可達。

接線後它第一次對使用者生效。這是本次修改**新暴露的風險面**，不屬於「順手發現的既有老問題」。

### 5.2 證據

`_JumpStepForm.__init__`（`gui/06_gui_main.py:4022-4027`）：
`current_id == ""` 時，`findData("")` 回 -1（`_populate_rule_combo` 從不加入空值項，見 `gui/06_gui_main.py:254-269`），且 `elif current_id:` 為 falsy → **不加入任何代表「未設定」的項目** → combo 停在 index 0。

`_JumpStepForm.save()`（`gui/06_gui_main.py:4030-4031`）：

```python
self._step.params["rule_id"] = self._combo.currentData() or ""
```

→ 無條件寫回 combo 當前選中項。

**實測**：`{"rule_id": ""}` 存檔後變成 `{"rule_id": "r2"}`。

### 5.3 影響

- 觸發路徑：在 GUI 刪掉某個規則（該規則正被某個 jump 指向）→ `_delete_rule` 清成 `""` → 使用者之後**碰到這個 jump step**（展開或整體存檔觸發 `get_steps()` → `_save_expanded()`）→ `rule_id` 被改成列表中的第一條規則。
- 後果：**使用者資料被靜默改寫**為另一條規則，且該規則可能與原本意圖完全無關。
- 與 `AGENTS.md`「不懶惰的地方：防止資料遺失的錯誤處理」「信任邊界的輸入驗證」直接牴觸。

### 5.4 修正選項

#### 選項 A（建議）：combo 開頭插入「未設定」placeholder

在 `_JumpStepForm.__init__` 中，當 `current_id` 為空時，於 combo 第 0 項插入一筆 data 為 `""` 的 placeholder 並選中它 → `save()` 會寫回 `""`，**空值被保留**。

- 顯示文案需要新 i18n key（目前 `i18n/` 內**沒有**可複用的「未設定」key，已確認）
- 需在 `zh_TW.json` / `en.json` / `ja.json` 各新增 1 筆，例：`step_form.unset_rule`
- 改動範圍：`gui/06_gui_main.py`（`_JumpStepForm`）+ 三個 i18n 檔 + 補測試
- 驗收：需跑 `tests/test_i18n.py`（AGENTS.md 明訂：改 `i18n/*.json` 必跑）
- 風險：低。combo 多一項空白列，**不影響**既有非空 `rule_id` 的行為（情況 A 邏輯不動）

#### 選項 B：不修正，記錄為已知限制

- Phase 2-2 範圍內不擴大，缺陷留待後續 Phase 處理
- 代價：接線功能會帶著「可能靜默改寫使用者資料」的行為上線
- 需在 `docs/dev/CHANGELOG.md` 或開發文件中明列

---

## 6. 已知問題清單（本階段未修，僅記錄）

| 編號 | 嚴重度 | 位置 | 說明 | 建議處理時機 |
|---|---|---|---|---|
| **F-1** | P2 | `gui/06_gui_main.py:701-716`（`_rebuild`）、`806-813`（`_collapse`）、`689-691`（`set_steps`） | `steps_changed` 觸發全 Rule 清單重建 → wait/notify 表單編輯完成後折疊。**資料不遺失**（保存早於重建） | Phase 2-4 |
| **F-2** | P3 | `gui/06_gui_main.py:4014-4031` | 空 `rule_id` → combo 停第一項 → 存檔靜默改寫（即 §5） | **本次待決策** |
| **F-3** | P3 | `gui/06_gui_main.py:3997` | wait 每次編輯完成都重建全清單（大量 wait 規則時成本高） | Phase 2-4 |
| **F-4** | Info | `gui/06_gui_main.py:3993` vs `core/rule_migration.py:357` | GUI 數值框有上限（wait 0–60000ms、fail_duration 0–30s），Core 不裁切。屬既有設計，不自創邊界政策 | 不修 |
| **F-5** | P2 | `gui/06_gui_main.py:7154-7156` | 驗證警告只 `showMessage`，隨後仍 `_schedule_save()` → 不阻擋儲存 | 待排程 |
| **F-6** | P3 | `gui/06_gui_main.py:4061-4135`（`_InlineActionEditor`） | 死碼：全專案 grep 只命中 class 定義本身 | Phase 2-4 死碼清理 |
| **G-1** | 超範圍 | `core/rule_migration.py:407-429`（`_build_detect_params`） | v1→v2 遷移同樣丟棄 `fail_duration_sec`（v1 格式本無此欄位） | 本階段未修，僅記錄 |

> F-1、F-3、F-5、F-6 皆**不在** Phase 2-1 / 2-2 的範圍內，依「不擴大範圍順手重構」的原則僅記錄。

---

## 7. 待決策事項

### 決策 1：空 `rule_id` 靜默改寫要不要修？

| 選項 | 內容 | 改動量 | 風險 | 對測試的影響 |
|---|---|---|---|---|
| **A（建議）** | combo 開頭插入「未設定」placeholder，`save()` 保留空值 | `gui/06_gui_main.py` + 3 個 i18n 檔 + 補測試 | 低 | 需跑 `tests/test_i18n.py` + 全套 |
| B | 不修，記錄為已知限制 F-2 | 0 | 資料可能被靜默改寫 | 無 |

### 決策 2：Phase 2-1 / 2-2 怎麼 commit？

| 選項 | 內容 |
|---|---|
| **A（建議）** | 分兩個獨立 commit、不 push<br>① `fix: 修正 fail_duration_sec 在載入時被靜默丟失`<br>② `fix: 接通 wait 與 jump 步驟編輯表單` |
| B | 分兩個獨立 commit、並 push 到 `origin/master`（會一併推送目前領先的 4 個 commit） |
| C | 先不 commit，連同 Phase 2-3 / 2-4 一起處理 |

> 依 `AGENTS.md`：「每個獨立任務完成後應立即單獨 commit，不得累積多個不相關任務到同一個 commit」→ 選項 A 最符合規範。

---

## 8. 建議執行順序

1. **決策 1** → 若選 A：改 `_JumpStepForm` + 三語 i18n + 補測試 → 跑 `tests/test_i18n.py` 與全套 pytest
2. **決策 2** → 分兩個 commit（決策 1 若選 A，其修改併入 ② wait/jump 那個 commit，因為它屬於同一功能範圍）
3. 進入 **Phase 2-3**（型別覆蓋測試補完）
4. 進入 **Phase 2-4**（`_StepListWidget` 更新策略、F-1／F-3、F-6 死碼清理、`_OnFailEditor` 共用元件評估）
5. **Phase 5 需另行核准**
