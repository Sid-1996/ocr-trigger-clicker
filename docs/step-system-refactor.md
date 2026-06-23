> ✅ **實作完成：** 本文件描述的所有 Phase（資料層、執行層、GUI、收尾）已於 v0.1.0 實作完畢。
> 保留供架構參考，不再更新。

# 步驟系統重構計畫（Step System Refactor）

## 開發宗旨

針對 Windows 應用程式（以遊戲為主），透過 OCR 即時偵測畫面文字，自動執行滑鼠或鍵盤動作的自動化工具。

**核心價值**
- OCR 是唯一觸發來源——所有判斷基於畫面上看得到的文字
- 無程式碼操作——使用者用 GUI 設定規則，不需要寫任何腳本
- 安全導向——速率限制、失控偵測、緊急停止
- 直覺優先——不看文件就能建出第一條規則
- 進階功能不擋路——簡單用法兩三步，複雜場景自然延伸

**不做的事**
- 不錄製操作
- 不讀記憶體、不 hook 遊戲
- 不是通用 macro 工具，OCR 偵測是必要前提

---

## 背景與動機

### 現有架構的根本缺陷

現有系統有兩種規則類型（`trigger` / `compare`），用同一個大表單切換，導致：

1. **每輪觸發動作無法不同**：比較規則的 `retry_key` 假設每輪按同一個鍵，無法支援「第一輪按 1、第二輪按 2、第三輪按 3」的場景
2. **指標數量固定為 2**：ROI-A / ROI-B 寫死，無法擴充至 3 個以上指標
3. **最終動作無法動態對應輪次**：確認動作固定，無法做到「第 N 輪贏就執行第 N 輪的對應動作」
4. **表單以欄位為核心，不以意圖為核心**：使用者看到的是一堆欄位，不是「我在做什麼」

### 目標場景（設計基準）

遊戲畫面有 3 個訓練選項，每個選項需要先觸發才能看到數值：

```
點擊「力量」（或按 1）→ 畫面顯示：失敗率 5%、成長幅度 150%  → 記錄
點擊「體力」（或按 2）→ 畫面顯示：失敗率 6%、成長幅度 170%  → 記錄
點擊「韌性」（或按 3）→ 畫面顯示：失敗率 10%、成長幅度 200% → 記錄

比較三組：
  門檻：失敗率 < 50% AND 成長幅度 > 180%
  最佳：成長幅度最高的達標輪次 → 選項 3

達標 → 按 3 → 按空白鍵確認
全不達標 → 按 ESC
```

---

## 新架構：統一步驟系統

### 核心設計原則

**廢除規則類型區分。** 不再有「觸發規則」和「比較規則」，只有一種 `Rule`，裡面放有序的 `Step` 陣列。觸發規則就是步驟組合最簡單的規則。

### 資料結構

```python
@dataclass
class Metric:
    """單一指標的讀取與評估設定"""
    roi: dict              # {x, y, w, h}，全零 = 全視窗
    pick: str              # "first" | "last"（取第幾個數字）
    direction: str         # "higher_better" | "lower_better"
    threshold: float       # 達標門檻
    timeout_ms: int        # 輪詢 OCR 超時（ms）

@dataclass
class Round:
    """比較輪次定義：每輪的觸發動作 + 要讀的指標"""
    trigger_action: dict   # {"type": "key", "key": "1"} 或
                           # {"type": "click_text", "text": "力量", "roi": {...}}
    metrics: list[Metric]  # 本輪要讀取的指標列表（順序對應比較時的欄位）
    result_action: dict    # 本輪「若被選中」要執行的動作
                           # {"type": "key", "key": "1"} 或 {"type": "click", ...}

@dataclass
class Step:
    """單一步驟"""
    type: str
    params: dict

@dataclass
class Rule:
    id: str
    name: str
    enabled: bool
    steps: list[Step]

    # 執行期（不存 JSON）
    trigger_count: int = field(default=0, repr=False)
    last_trigger_time: float = field(default=0.0, repr=False)
```

### Step 類型定義

| type | 用途 | params 欄位 |
|------|------|------------|
| `detect` | OCR 偵測文字，未命中則停止本規則 | `text`, `roi`, `fuzzy`, `fuzzy_threshold`, `cooldown_ms`, `trigger_mode`, `max_triggers` |
| `click` | 滑鼠點擊 | `target`: `"text_center"` / `"custom"` / `"click_text"`, `x`, `y`, `button`, `random_offset`, `text`（click_text 時用） |
| `key` | 鍵盤按鍵 | `key`（AHK 格式） |
| `wait` | 固定等待 | `ms` |
| `wait_rule` | 等待指定規則觸發過才繼續 | `rule_id` |
| `collect_rounds` | 多輪收集數值 + 比較選最佳 | 見下方詳述 |
| `jump` | 無條件跳轉觸發另一條規則 | `rule_id` |

### `collect_rounds` step params 詳述

這個 step 封裝了原本比較規則的全部邏輯：

```python
{
  "rounds": [
    {
      "trigger_action": {"type": "key", "key": "1"},
      "metrics": [
        {"roi": {...}, "pick": "first", "direction": "lower_better", "threshold": 50, "timeout_ms": 3000},
        {"roi": {...}, "pick": "first", "direction": "higher_better", "threshold": 180, "timeout_ms": 3000}
      ],
      "result_action": {"type": "key", "key": "1"}
    },
    {
      "trigger_action": {"type": "key", "key": "2"},
      "metrics": [...],
      "result_action": {"type": "key", "key": "2"}
    },
    {
      "trigger_action": {"type": "key", "key": "3"},
      "metrics": [...],
      "result_action": {"type": "key", "key": "3"}
    }
  ],
  "primary_metric_index": 1,       # 達標輪次中以第幾個指標選最佳（0-based）
  "confirm_action": {"type": "key", "key": " "},  # 選出最佳後的確認動作
  "on_all_fail": {"type": "key", "key": "Escape"}  # 全輪未達標的動作
}
```

**執行邏輯：**
1. 依序執行每個 round 的 `trigger_action`
2. 等待並輪詢 OCR 讀取所有 metrics 的數值
3. 判斷本輪是否所有 metrics 均達標
4. 所有輪次跑完後，從「全部達標」的輪次中，依 `primary_metric_index` 選最佳
5. 若無全部達標的輪次，從「主要指標達標」的輪次中選最佳
6. 執行最佳輪次的 `result_action` → `confirm_action`
7. 若無任何達標輪次 → 執行 `on_all_fail`

### 典型規則範例

**觸發規則（最簡單）**
```json
{
  "id": "rule_abc123",
  "name": "點擊確認",
  "enabled": true,
  "steps": [
    {"type": "detect", "params": {"text": "確認", "roi": {"x":0,"y":0,"w":0,"h":0}, "fuzzy": false, "fuzzy_threshold": 0.8, "cooldown_ms": 2000, "trigger_mode": "repeat", "max_triggers": -1}},
    {"type": "click",  "params": {"target": "text_center", "button": "left", "random_offset": 3}}
  ]
}
```

**多輪比較規則（完整場景）**
```json
{
  "id": "rule_def456",
  "name": "訓練選項比較",
  "enabled": true,
  "steps": [
    {"type": "detect", "params": {"text": "力量", "roi": {...}, "cooldown_ms": 5000, "trigger_mode": "repeat", "max_triggers": -1}},
    {"type": "collect_rounds", "params": {
      "rounds": [
        {"trigger_action": {"type": "key", "key": "1"}, "metrics": [...], "result_action": {"type": "key", "key": "1"}},
        {"trigger_action": {"type": "key", "key": "2"}, "metrics": [...], "result_action": {"type": "key", "key": "2"}},
        {"trigger_action": {"type": "key", "key": "3"}, "metrics": [...], "result_action": {"type": "key", "key": "3"}}
      ],
      "primary_metric_index": 1,
      "confirm_action": {"type": "key", "key": " "},
      "on_all_fail": {"type": "key", "key": "Escape"}
    }}
  ]
}
```

---

## GUI 設計

### 整體佈局（不變）
左側規則列表 + 右側規則編輯區，維持現有分割視窗結構。

### 規則編輯區（重構）

```
┌─────────────────────────────────────────────────────┐
│  名稱: [訓練選項比較]                      ☑ 啟用    │
├─────────────────────────────────────────────────────┤
│  #   步驟             摘要                     操作  │
│  1   🔍 偵測文字      「力量」  全視窗  冷卻2s   ✎ ✕ │
│  2   🔄 多輪比較      3輪  2指標  主指標:成長幅度 ✎ ✕ │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │ ▾ 步驟 2 設定                                │   │
│  │                                              │   │
│  │  輪次列表:                                   │   │
│  │  ┌─────┬──────────────┬──────────────────┐  │   │
│  │  │ 輪次 │ 觸發動作     │ 結果動作         │  │   │
│  │  ├─────┼──────────────┼──────────────────┤  │   │
│  │  │  1  │ 按鍵 "1"     │ 按鍵 "1"    ✎ ✕ │  │   │
│  │  │  2  │ 按鍵 "2"     │ 按鍵 "2"    ✎ ✕ │  │   │
│  │  │  3  │ 按鍵 "3"     │ 按鍵 "3"    ✎ ✕ │  │   │
│  │  └─────┴──────────────┴──────────────────┘  │   │
│  │  [+ 新增輪次]                                │   │
│  │                                              │   │
│  │  指標列表:                                   │   │
│  │  ┌────┬──────┬────────┬────────┬──────────┐ │   │
│  │  │指標│ ROI  │ 方向   │ 門檻   │ 取數字   │ │   │
│  │  ├────┼──────┼────────┼────────┼──────────┤ │   │
│  │  │ A  │ 框選 │ 越低越好│  50   │ 第一個 ✎ │ │   │
│  │  │ B  │ 框選 │ 越高越好│ 180   │ 第一個 ✎ │ │   │
│  │  └────┴──────┴────────┴────────┴──────────┘ │   │
│  │  [+ 新增指標]                                │   │
│  │                                              │   │
│  │  主要指標: [指標 B ▾]                        │   │
│  │  確認動作: [按鍵 ▾]  [空白鍵        ]        │   │
│  │  全不達標: [按鍵 ▾]  [Escape        ]        │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  [+ 新增步驟 ▾]          [儲存]  [▶ 測試]           │
└─────────────────────────────────────────────────────┘
```

### 步驟列表互動原則
- 點步驟行 → 在下方 inline 展開該步驟的參數編輯區
- 同時只展開一個步驟
- 步驟可拖曳排序
- 每個步驟右側有編輯（✎）和刪除（✕）按鈕
- 步驟摘要欄位自動從 params 生成人話描述

### 新增步驟選單
點「+ 新增步驟」展開下拉：
```
🔍 偵測文字      — 等待畫面出現指定文字才繼續
🖱 點擊          — 點擊文字中心或自訂座標
⌨ 按鍵          — 發送鍵盤按鍵
⏱ 等待          — 固定等待指定毫秒
🔗 等待規則      — 等待另一條規則觸發後才繼續
🔄 多輪比較      — 多輪收集數值、比較選最佳
↩ 跳轉規則      — 立即觸發另一條規則
```

---

## 執行模型

### 主循環變更（`05_main_loop.py`）

```python
def _process_rules(self, ocr_results, img):
    for rule in self._rules:
        if not rule.enabled:
            continue
        self._run_rule(rule, ocr_results, img)

def _run_rule(self, rule, ocr_results, img):
    context = StepContext(ocr_results=ocr_results, img=img)
    for step in rule.steps:
        result = self._run_step(step, context, rule)
        if result.action == "stop":
            break
        if result.action == "jump":
            self._force_trigger(result.rule_id)
            break
        # "continue" → 執行下一個步驟

def _run_step(self, step, context, rule) -> StepResult:
    handler = self._step_handlers[step.type]
    return handler(step.params, context, rule)
```

### StepContext（步驟間傳遞狀態）

```python
@dataclass
class StepContext:
    ocr_results: list[OcrResult]   # 當前幀的 OCR 結果
    img: np.ndarray                # 當前幀截圖
    matched_text: OcrResult | None = None  # detect step 命中的文字（供 click 用）
    round_results: list[dict] | None = None  # collect_rounds 的結果
```

### 各 Step Handler 責任

| step | handler 責任 |
|------|-------------|
| `detect` | 比對 ocr_results，命中 → context.matched_text = result，return continue；未命中 → return stop |
| `click` | 依 target 決定座標（text_center 用 context.matched_text），發送 AHK click |
| `key` | 發送 AHK key |
| `wait` | time.sleep(ms/1000) |
| `wait_rule` | 檢查目標規則 trigger_count >= 1，否則 return stop |
| `collect_rounds` | 執行多輪收集邏輯，選最佳輪次執行動作 |
| `jump` | return StepResult(action="jump", rule_id=...) |

---

## 遷移策略

### JSON 版本識別

讀取 JSON 時，以 `"steps"` 欄位是否存在判斷版本：

```python
def load_rules(path) -> list[Rule]:
    data = json.loads(path.read_text())
    rules_raw = data.get("rules", [])
    return [
        _dict_to_rule(r) if "steps" in r else _migrate_v1_to_v2(r)
        for r in rules_raw
    ]
```

### `_migrate_v1_to_v2` 轉換邏輯

**觸發規則 → steps**
```
target_text + roi + fuzzy + cooldown_ms + trigger_mode + max_triggers
  → Step(type="detect", params={...})

click_position + custom_x/y + button + random_offset
  → Step(type="click", params={...})

key + action_type="key"
  → Step(type="key", params={key: ...})

post_delay_ms > 0
  → Step(type="wait", params={ms: post_delay_ms})

depends_on
  → Step(type="wait_rule", params={rule_id: depends_on}) 插在 detect 之前
```

**比較規則 → steps**
```
target_text（若有）
  → Step(type="detect", params={...}) 插在最前

retry_key + max_rounds + roi_a + roi_b + ...
  → Step(type="collect_rounds", params={
      rounds: [每輪 trigger_action=retry_key, metrics=[roi_a, roi_b]],
      confirm_action: {type: confirm_action_type, ...},
      on_all_fail: {type: "rule", rule_id: on_all_fail}
    })

注意：舊版比較規則每輪 trigger_action 相同（都是 retry_key），
遷移後每輪的 result_action 也相同，使用者可事後手動改成不同按鍵。
```

---

## 需修改的檔案

| 檔案 | 修改內容 |
|------|----------|
| `core/04_rule_engine.py` | 完全重寫：`Rule` 改為 steps 架構，`Step` / `Metric` / `Round` dataclass，新增 `_migrate_v1_to_v2()`，`load_rules` / `save_rules` 讀寫新格式 |
| `core/05_main_loop.py` | `_process_rules()` 改為步驟執行模型，新增 `StepContext`、各 step handler、`_run_collect_rounds()` |
| `gui/06_gui_main.py` | 規則編輯區完全重寫：步驟列表 widget、各 step 的 inline 展開表單、`collect_rounds` 的輪次+指標列表編輯 UI |

## 不需修改的檔案

| 檔案 | 原因 |
|------|------|
| `core/01_screenshot.py` | 截圖邏輯不變 |
| `core/02_ocr_engine.py` | OCR 引擎不變 |
| `core/03_ahk_socket.py` | AHK 通訊協定不變 |
| `core/10_performance_monitor.py` | 效能監控不變 |
| `gui/07_gui_roi.py` | ROI 框選 overlay 不變，供 step 編輯 UI 呼叫 |
| `gui/09_ocr_debug.py` | OCR 診斷面板不變 |
| `gui/13_gui_click_picker.py` | 點擊座標選取 overlay 不變 |
| `clicker.ahk` | AHK 端不變 |

---

## 執行計畫（分 Phase）

### Phase 1：資料層重構
**目標**：新 `Rule` / `Step` 資料結構上線，舊 JSON 自動遷移，GUI 暫時不動

**檔案**：`core/04_rule_engine.py`

**任務清單**：
1. 定義 `Metric`、`Round`、`Step`、`Rule` dataclass
2. 實作 `_STEP_DEFAULTS`（各 step type 的預設 params）
3. 實作 `_rule_to_dict()` / `_dict_to_rule()` 讀寫新格式
4. 實作 `_migrate_v1_to_v2()` 自動遷移舊格式
5. `load_rules()` 加版本偵測，`save_rules()` 統一寫新格式
6. 移除舊有的 `check_trigger()` / `apply_trigger()` / `get_roi()`（Phase 2 後才能移除，先保留）
7. 加 `__main__` self-check：載入舊格式 JSON → 遷移 → 序列化 → 驗證欄位完整

**完成標準**：舊 tasks/*.json 能被正確讀入為新 Rule 結構，且序列化後包含 steps 欄位

---

### Phase 2：執行層重構
**目標**：主循環改為步驟執行模型，所有 step handler 實作完畢

**檔案**：`core/05_main_loop.py`

**任務清單**：
1. 定義 `StepContext`、`StepResult` dataclass
2. 實作 `_run_rule(rule, ocr_results, img)`
3. 實作各 step handler：
   - `_handle_detect(params, ctx, rule)`
   - `_handle_click(params, ctx, rule)`
   - `_handle_key(params, ctx, rule)`
   - `_handle_wait(params, ctx, rule)`
   - `_handle_wait_rule(params, ctx, rule)`
   - `_handle_collect_rounds(params, ctx, rule)`
   - `_handle_jump(params, ctx, rule)`
4. `_run_collect_rounds()` 實作多輪邏輯（觸發 → 輪詢 OCR → 比較 → 選最佳 → 執行）
5. 移除舊的 `_run_compare_rule()` / `_compare_worker()` 等
6. 保留所有安全機制（速率限制、runaway 偵測、緊急停止）不動
7. 加 `__main__` self-check：用 mock Rule + steps 跑一次不發送 AHK 的乾跑

**完成標準**：主循環能正確執行 detect → click 的基本步驟序列，現有任務的功能不退步

---

### Phase 3：GUI 重構
**目標**：規則編輯區改為步驟列表 UI

**檔案**：`gui/06_gui_main.py`

**任務清單**：
1. 實作 `StepListWidget`：步驟行列表，支援點擊展開、拖曳排序、新增/刪除
2. 實作各 step 的 inline 展開表單：
   - `DetectStepForm`
   - `ClickStepForm`
   - `KeyStepForm`
   - `WaitStepForm`
   - `WaitRuleStepForm`
   - `CollectRoundsStepForm`（含輪次列表、指標列表的子 table）
   - `JumpStepForm`
3. 實作步驟摘要自動生成（從 params 生成一行人話）
4. 「+ 新增步驟」下拉選單
5. `_show_rule_detail()` / `_save_current_rule()` 讀寫新 steps 格式
6. 移除所有舊的表單 widget（`_edit_target_text`、`_edit_roi_*`、`_edit_compare_*` 等）
7. 保留任務管理（新增/刪除/匯入/匯出）、規則列表、狀態列、OCR 診斷入口不動

**完成標準**：能用新 UI 建立觸發規則和多輪比較規則，儲存後重新開啟正確顯示

---

### Phase 4：收尾與測試
**目標**：確保舊資料不遺失，整體品質達標

**任務清單**：
1. 用現有 tasks/*.json 實際跑遷移，確認無欄位遺失
2. ruff check --fix + ruff format 整個專案
3. 更新 `ARCHITECTURE.md`（更新模組說明、資料結構、執行流程圖）
4. 舊的 `compare-rule-spec.md` 標記為 deprecated（在檔案頂部加註，不刪除）
5. 版本號更新至 v0.1.0

**完成標準**：ruff 無警告，ARCHITECTURE.md 反映新架構，舊任務遷移無損

---

## Agent 執行指引

### 給 Agent 的總原則
- 嚴格按 Phase 順序執行，Phase N 完成並確認後才開始 Phase N+1
- 每個 Phase 完成後執行 `ruff check --fix` + `ruff format`，再 commit + push
- commit 訊息格式：`refactor: Phase N — 說明`
- 遵守 AGENTS.md 的所有規範（PowerShell 7、ripgrep、Ponytail 風格）
- 不碰「不需修改的檔案」清單中的檔案

### 開始前必讀
- `AGENTS.md`（工作規範、shell 指令、coding 風格）
- `ARCHITECTURE.md`（現有架構全貌）
- `docs/step-system-refactor.md`（本文件）
- `core/04_rule_engine.py`（現有資料結構）
- `core/05_main_loop.py`（現有執行邏輯）
- `gui/06_gui_main.py`（現有 GUI）

### Phase 1 啟動 prompt 範例
```
請閱讀 AGENTS.md、ARCHITECTURE.md、docs/step-system-refactor.md，
然後執行 Phase 1：資料層重構。
目標是重寫 core/04_rule_engine.py，實作新的 Rule/Step 資料結構與舊格式遷移。
完成後執行 ruff check --fix + ruff format，commit 並 push。
```
