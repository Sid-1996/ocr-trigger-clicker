# 改造計畫：從「有狀態規則引擎」回歸「純指令碼執行器」

## 目標

建立一個以 **AHK 哲學** 為基礎的 OCR 自動化工具：**不做任何隱含假設**，所有行為由使用者明確指定，系統只提供「找到文字 → 執行動作 → 跳到下一條」的核心循環。

## 為什麼要改

目前的 Rule 不是「腳本片段」，而是「有狀態的物件」。每個 Rule 身上背了太多「替你著想」的自動行為：

| 隱含行為 | 預設值 | 實際問題 |
|---|---|---|
| `trigger_mode: "once"` | 只觸發一次 | detect 在第一次成功後永久封鎖，無法再次觸發 |
| `trigger_count` auto++ | 側面副作用 | 被多處用來做決策，但使用者從未設定它 |
| `cooldown_ms: 500` | 自動冷卻 | 使用者不知道有冷卻存在，點擊被跳過 |
| `timeout_ms: 5000` (wait_rule) | 5 秒倒數 | 鏈中所有 rule 同時開始倒數，全部同時逾時 |
| `_wait_rule_done` | 逾期永久跳過 | 沒有機制恢復 |
| `jump` discard on fail | 只嘗試一次 | detect 失敗後 trigger 直接被吃掉 |
| `_auto_disabled` | 系統判定太頻繁 | 使用者沒有任何控制權 |

AHK 為什麼可靠？因為它**不做任何假設**：

```ahk
Loop {
    ImageSearch,,, 3_3.png      ; 找到就繼續，沒找到下一圈再找
    if ErrorLevel = 0 {
        Click
        break
    }
    Sleep 500
}
goto LoopStart                  ; 無條件跳轉，永遠成功
```

沒有 `trigger_count`、沒有 `cooldown`、沒有 `timeout`、沒有「觸發模式」。Loop 就是循環，goto 就是跳轉。

## 保留的 AHK 輸入層

AHK 的價值（滑鼠/鍵盤模擬）**完全保留**。只改造規則執行引擎。

## 新執行模型：Rule Pointer

將多條 Rule 視為一串指令，用一個 pointer 指向「正在執行的 Rule」。

```
Rules (有序清單):
  [0] 每日重新派遣  → [detect, click, jump "地區派遣"]
  [1] 地區派遣      → [detect, click, jump "進入"]
  [2] 進入          → [detect, click, ...]
  [3] 一鍵領取      → [...]
  [4] 重新派遣      → [...]
  ...
  [N] 0/3           → [detect, click, jump "3/3"]  ← 循環回 [0]

_rule_pointer = 0  ← 唯一的外部狀態
```

### 每幀流程

```
if 暫停 → wait; continue
if 前景失效 → wait; continue

截圖
OCR 全畫面

rule = rules[_rule_pointer]
執行 rule 的所有 steps (依序)

step[0] = detect "..." 
  → 文字在畫面? YES → continue (往下個 step)
  → 文字在畫面? NO  → stop (整條 rule 中斷，下一幀重試同一條 rule)
  
step[1] = click  / key / drag / scroll
  → 執行輸入，stop (中斷，不繼續下一條 rule)

step[2] = jump "下一條 Rule 的名稱/id"
  → _rule_pointer = find_index("下一條")
  → stop (中斷，下一幀從新指針開始)

step[?] = wait N ms
  → sleep N ms，continue
```

### 與 AHK 對照

| AHK 概念 | 新模型 |
|---|---|
| `Label:` | Rule |
| `ImageSearch` → 命中則 Click | Step: detect → click |
| `goto Label` | Step: jump "Label" |
| `return` | rule 執行完畢 → 下一幀同 pointer |
| `Loop { ... }` | 內建（每幀自然循環） |
| `Sleep 500` | Step: wait |
| 程式計數器 (IP) | `_rule_pointer` |

## 移除清單

### Rule 層級 — 完全移除

| 欄位 | 原因 |
|---|---|
| `trigger_count` | 不追蹤觸發次數。每次執行都是全新的。 |
| `last_trigger_time` | 不追蹤觸發時間。冷卻由 step 自己控制。 |
| (from detect step) `cooldown_ms` | 不需要。想冷卻就插一個 `wait` step。 |
| (from detect step) `trigger_mode` | 不需要。想重複執行的話，在 jump 中自然做到。 |
| (from detect step) `max_triggers` | 不需要。沒有計數器就沒有上限。 |
| (from wait_rule step) `timeout_ms` | 不需要。precondition 沒出現就一直等到出現。 |
| `_wait_rule_deadlines` | 不需要。沒有 timeout 就沒有 deadline。 |
| `_wait_rule_done` | 不需要。不會有人被永久跳過。 |
| `_rule_auto_disabled` | 不需要。不會自動停用。 |
| `_pending_retry` / `retry_from` | 不需要。detect 沒命中自然下一幀重試。 |
| Sequential mode (`_execution_mode`) | 不需要。Rule Pointer 就是 sequential。 |
| `_cycle_visited` | 不需要。不再需要 cycle detection（pointer 不會 cycle）。 |

### Wait_rule step — 保留但簡化

`wait_rule` 仍有用途：等待前置條件滿足。

但改用 pointer 模型，wait_rule 的語意變成：**檢查目標 Rule 的 detect 文字是否已不在畫面上**（表示已被處理過）。如果目標 Rule 的 detect 文字仍在畫面 → 表示尚未執行 → 返回 stop 等待。

或更簡單的定義：**wait_rule 不再需要**，因為 jump 已經承擔了流程控制。如果一條 Rule 需要等待某個畫面，直接在它的第一個 step 用 detect 即可。detect 沒命中就 stop，下一幀自動重試。

**決定：移除 wait_rule step。** 用 detect + jump 取代。如果需要等待前置條件，在該 Rule 的 detect step 等待正確的文字出現即可。

### 保留清單

| 功能 | 保留原因 |
|---|---|
| `detect` step | 核心功能。簡化為只檢查文字是否存在。 |
| `click` / `key` / `drag` / `scroll` steps | 核心功能。不變。 |
| `wait` step | 核心延遲。不變。 |
| `jump` step | 核心流程控制。改為直接設定 `_rule_pointer`。 |
| `on_fail` (detect 失敗處理) | 保留。但簡化，只保留 `key`（按鍵代替點擊）和 `stop`。移除 retry/jump 子選項（因為自然重試 + pointer 控制已涵蓋）。 |
| Rate limiting (`check_rate_limit`) | 安全機制。保留。超過每秒點擊上限時才觸發。 |
| Emergency stop (F12 / ESTOP) | 安全機制。保留。 |
| Pause / Resume | 保留。 |
| Window foreground check | 保留。安全機制。 |
| Static frame detection | 保留但簡化。不需要再檢查 wait_rule deadlines。只需保留基本的「畫面無變化時跳過 OCR」。 |

## Phase 劃分

### Phase 1: Core 引擎改造

**目標：** 讓 rule pointer 模型能跑，所有 rule 無狀態。

**檔案：`core/05_main_loop.py`** 主要改寫：

1. 新增 `_rule_pointer: int = 0`
2. 改寫 `_handle_detect`：
   - 移除 `cooldown_ms` 檢查
   - 移除 `trigger_mode == "once"` 檢查
   - 移除 `trigger_count` 相關比較
   - 移除 `max_triggers` 檢查
   - 只保留：empty text check → OCR → find_text → match 返回 continue / 不 match 返回 on_fail
3. 改寫 `_run_rule`：
   - 遇到 `stop` 時 return
   - 遇到 `jump` 時設定 `_rule_pointer` 再 return
4. 改寫 `_handle_jump`：
   - 不再使用 `_pending_forced_triggers`
   - 直接找 target rule 的 index → 設 `_rule_pointer`
   - 找不到時 log warning
5. 改寫 `_process_rules`：
   - 取代原本的 `for idx, rule in enumerate(rules_snapshot)` 迭代所有 rule
   - 改為只執行 `rules_snapshot[_rule_pointer]`
   - 移除 sequential mode 邏輯
   - 移除 `_wait_rule_deadlines` / `_wait_rule_done` 檢查
   - 移除 `_pending_retry` 處理
   - 移除 `_rule_auto_disabled` 恢復檢查
   - 移除 `_cycle_visited` 處理
   - 移除 `_pending_forced_triggers` 處理
6. 改寫 `_handle_wait_rule` — 整個移除
7. 移除 `_mark_rule_triggered` — trigger_count 不再存在，改為直接用 flag 或跳過
   - trigger log 仍保留，但從 click handler 直接 emit
8. 改寫 `_should_process_static_frame`：
   - 無需 wait_rule deadline 檢查
   - 保留基本的：repeat mode detect 檢查（若有 repeat step 則不跳過 OCR）
9. 移除 `_handle_collect_rounds` — 整個移除（這是另一個有狀態的複雜功能，後續再考慮是否重新設計）
10. 改寫 `stop()` / `reload_rules()` / `emergency_stop()`：
    - 重置 `_rule_pointer = 0`
    - 移除已清除的 dict/set

**檔案：`core/04_rule_engine.py`**

1. 更新 `Rule` dataclass：移除 `trigger_count`、`last_trigger_time`
2. 更新 `_STEP_DEFAULTS`：
   - `detect`：移除 `cooldown_ms`、`trigger_mode`、`max_triggers`、`on_fail`（改為只在執行層處理）
   - `wait_rule`：整個移除 step type
   - `collect_rounds`：整個移除 step type（可選，非必要）
3. 更新 `_normalize_step_params`：反映新預設值
4. 更新 valid step types
5. 更新 `_migrate_v1_to_v2`：不需要遷移 wait_rule/trigger_mode
6. `StepResult.action` 移除 `"jump"` action type（pointer 直接設定，不需要透過 StepResult）

### Phase 2: GUI Step 編輯器調整

**檔案：`gui/06_gui_main.py`**

1. 更新 `_STEP_TYPE_ICONS` / `_STEP_TYPE_LABELS`：移除 wait_rule、collect_rounds 類型
2. 更新 `_step_summary`：移除 cooldown、trigger_mode 顯示
3. 更新 step form 建置：
   - `_DetectStepForm`：移除 trigger_mode、cooldown_ms、max_triggers、on_fail_jump ui 元素
   - 移除 `_WaitRuleStepForm`
   - 移除 `_CollectRoundsStepForm`
4. 更新 `_RuleTreeWidget`：移除父子關係顯示（不再依賴 wait_rule 父子關係）
   - 或改為顯示 jump 目標的連線（跳轉目標指示）
5. 更新 `_refresh_rule_list`：移除 `_get_wait_rule_ids` 等相關邏輯
6. 更新「加入步驟」選單：移除 wait_rule、collect_rounds 選項
7. 更新 `_delete_rule`：移除 wait_rule 依存檢查
8. 更新 `_add_rule`：移除預設的 `trigger_mode: "once"`

**檔案：`gui/09_ocr_debug.py`**

1. 更新 `_on_add_rule`：移除 `TriggerModeDialog`（不再需要選擇觸發模式）

### Phase 3: 測試與驗證

1. 更新 `core/05_main_loop.py` 的 `__main__` self-check tests
2. 手動測試鏈循環（每日重新派遣 → ... → 0/3 → 回到 3/3 → 再跑一次）
3. 測試 jump 不存在的 rule（應 log warning, 不 crash）
4. 測試 detect 永遠沒命中（應持續重試不 timeout）

### Phase 4: 清理

1. 移除 `tasks/` 目錄下的舊格式 `.json` 檔案（格式改變了）
2. 更新 `templates/` 下的範例 JSON
3. 更新 `ARCHITECTURE.md` 反映新架構
4. 更新 `AGENTS.md` 反映新原則

## 邏輯遺漏檢查

以下是初版計畫中我發現的遺漏：

### 1. Pointer 越界處理

如果 pointer 指向的 index 超出 rules 長度（例如 jump 的目標不存在），應自動重置為 0 + log warning。

### 2. Wait_rule 移除後的序列化問題

Wait_rule 是舊使用者已建立的規則中可能存在的 step。移除後，載入舊規則時應自動忽略或轉換為 detect+jump 組合。

作法：在 `_normalize_step_params` 中，若 step type 是 `"wait_rule"`，自動跳過該 step（或視為 `"jump"`）。

### 3. `on_fail` 在無 state 模型中的語意

目前的 `on_fail: "retry"` 會 block 主循環（在 handler 內 sleep+retry）。移除後，detect 失敗就是自然回 `stop`，下一幀重試。這與 retry 行為一致，但不需要 blocking。

`on_fail: "retry_from"` 指定從特定 step index 重試，在新模型中也由自然重試取代（因為第一幀沒命中，下一幀從頭開始，等於 retry_from 0）。

**決定：`on_fail` 只保留 `"key"`（按鍵代替點擊）和 `"stop"`（預設）。移除 `"retry"`、`"retry_from"`、`"jump"`。**

### 4. `_foreground_only` 與 pointer 的交互

目前 `_foreground_only` 在 `_loop` 層級檢查。如果視窗不在前景，整個循環跳過（不處理任何 rule）。這與現在相同，不需要改變。

但要注意：當 pointer 指向某條 rule 時，若視窗失去前景，recovery 後會從同一條 rule 繼續。這是正確行為。

### 5. 多條 rule 共用 pointer 的順序

使用者可能需要某些 rule「永遠在背景執行」（例如監控某個文字出現就按 F2）。Pointer 模型預設只執行當前指向的 rule。

解決方案：新增 `"background": true` 旗標。背景規則在每幀的 pointer 執行之前或之後執行，不受 pointer 影響。

**此功能非必須，延後實作。**

### 6. Jump 找不到目標時的處理

如果 `jump "XXX"` 且 `XXX` 不在 rules 清單中：
- 應 log `[警告] jump 目標「XXX」不存在`
- 保持 `_rule_pointer` 不變
- 下一幀繼續執行同一條 rule

### 7. 空 rules 清單的處理

若 rules 清單為空，`_process_rules` 直接 return。與目前一致。

若 `_rule_pointer >= len(rules)`，重置為 0（避免 index error）。

### 8. detect 的 ROI 支援是否保留

保留。ROI 裁切與目前一致。不需要變更。

### 9. 靜態畫面偵測是否會阻擋 pointer 前進

會。若畫面無變化且無任何 rule 需要 OCR，則整個 cycle 跳過。

這是好的：當遊戲畫面靜止時（例如 loading），不需要浪費 OCR。畫面變化後自動恢復。

但要注意：若 pointer 指向一個正在等待文字的 rule，且遊戲畫面處於 loading 靜止狀態，靜態畫面偵測會讓該 rule 無法檢查文字。

**解決：`_should_process_static_frame` 應保留「chain 正在運作中」的檢查**。在新模型中，若 `_rule_pointer` 指向的 rule 有 detect step，則不跳過 OCR。

```python
def _should_process_static_frame(self) -> bool:
    with self._rules_lock:
        if self._rule_pointer < len(self._rules):
            rule = self._rules[self._rule_pointer]
            has_detect = any(s.type == "detect" for s in rule.steps)
            if has_detect:
                return True
        ...
```

### 10. 規則新增/刪除時的 pointer 調整

若使用者在編輯器刪除了一條 rule，而 `_rule_pointer` 指向它或之後：
- 若 pointer > 被刪除的 index → `pointer -= 1`
- 若 pointer == 被刪除的 index → `pointer = min(pointer, len(rules)-1)`（前移或歸零）
- 若 pointer < 被刪除的 index → 不變

若新增 rule → 不影響 pointer。

## 風險評估

| 風險 | 可能性 | 影響 | 緩解措施 |
|---|---|---|---|
| 現有使用者的 rules.json 不相容 | 高 | 無法載入 | Phase 1 加入 migrate 邏輯，自動轉換舊格式 |
| Step forms 大幅改動後 UI 有 bug | 中 | 編輯器異常 | Phase 2 後手動測試每種 step type |
| 移除 wait_rule 後某些 sequencing 無法表達 | 中 | 使用者 workflow 改變 | 用 detect+jump 取代，編輯器內提供 migrate guide |
| Pointer 模型不支援「同時監控多個文字」 | 低 | 功能受限 | 先發版，後續評估是否加 background rules |
| 移除 collect_rounds 影響現有使用者 | 低 | 功能遺失 | 舊 task 載入時自動跳過未知 step type |
