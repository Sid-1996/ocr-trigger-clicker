# OCR Trigger Clicker — 架構文件

## 專案定位

針對 Windows 遊戲／應用程式的畫面 OCR 自動化點擊工具：定期擷取視窗畫面，透過 OCR 辨識文字，比對觸發規則後自動模擬滑鼠點擊或鍵盤按鍵。

## 技術棧速覽

| 層級 | 技術 | 用途 |
|------|------|------|
| 語言 | Python 3.12 | 主程式 |
| GUI | PyQt6 | 設定視窗、偵測日誌、除錯面板 |
| OCR | rapidocr-onnxruntime (DirectML + CPU) | 文字辨識 |
| 影像處理 | OpenCV (cv2), numpy | 截圖、縮放、二值化、差異偵測 |
| 輸入模擬 | AutoHotkey v2 | 滑鼠點擊／移動、鍵盤按鍵 |
| 通訊 | TCP socket (127.0.0.1:12345) | Python ↔ AHK |
| 作業系統 | Windows (GDI / win32 API) | 視窗列舉、DPI 縮放、前景判斷 |

## 模組地圖與依賴關係

### _loader.py — 動態載入機制

Python 標準 `import` 無法載入以數字開頭的 `.py` 檔（如 `01_screenshot.py`），故全專案透過 `_loader.load_sibling(name, filename)` 統一載入。

```python
load_sibling("screenshot", "core/01_screenshot.py")
```

- 以 `threading.RLock` + dict 快取，確保每個模組只被載入一次
- 載入後註冊進 `sys.modules`，若已存在則直接回傳

### 模組依賴圖

```
gui/06_gui_main.py  ──→  _loader ──→  core/04_rule_engine  ──→  core/02_ocr_engine
                  │               └──→  core/05_main_loop    ──→  core/01_screenshot
                  │               └──→  core/03_ahk_socket   ──→  core/02_ocr_engine
                  │               └──→  gui/09_ocr_debug     ──→  core/03_ahk_socket
                  │               └──→  gui/07_gui_roi       ──→  core/04_rule_engine
                   │               └──→  gui/13_gui_click_picker  ──→  core/10_performance_monitor
                   │
core/05_main_loop ──→  _loader ──→  core/01_screenshot
                   │               └──→  core/02_ocr_engine
                   │               └──→  core/03_ahk_socket
                   │               └──→  core/04_rule_engine
                   │               └──→  core/10_performance_monitor
                   │               └──→  core/11_template_matching
                   │
core/03_ahk_socket─→  _loader ──→  core/10_performance_monitor（螢幕邊界檢查用）
```

### 各模組職責

| 檔案 | 角色 | 對外暴露 |
|------|------|----------|
| `core/01_screenshot.py` | 視窗擷取 | `capture()`, `capture_window_content()`, `list_windows()`, `get_window_rect()`, `activate_window()` |
| `core/02_ocr_engine.py` | OCR 引擎 | `init_engine()`, `recognize()`, `find_text()`, `OcrResult` |
| `core/03_ahk_socket.py` | AHK 輸入橋接 | `init_ahk()`, `send_click()`, `send_move()`, `send_key()`, `shutdown()` |
| `core/04_rule_engine.py` | 規則模型 + 步驟系統 + 群組管理 + 任務管理 | `Rule`, `RuleGroup`, `Step`, `load_groups()`, `save_groups()`, `load_rules()`, `save_rules()`, `_migrate_v1_to_v2()` |
| `core/05_main_loop.py` | 主偵測迴圈（群組兩層指標模型） | `MainLoop` class, `StepContext`, `StepResult`, `set_active_groups()` |
| `core/10_performance_monitor.py` | 效能監控 + 速率限制 | `PerformanceMonitor`, `get_screen_bounds()`, `is_window_foreground()` |
| `core/11_template_matching.py` | 圖示模板比對 | `match_template()`, `nms_suppress()`, `MatchResult` |
| `gui/06_gui_main.py` | 主視窗（工具列、規則編輯、狀態列） | `MainWindow` |
| `gui/07_gui_roi.py` | 框選偵測區域（全螢幕 overlay） | `select_roi()` |
| `gui/09_ocr_debug.py` | OCR 除錯面板（即時截圖＋標註） | `OcrDebugPanel` |
| `gui/13_gui_click_picker.py` | 點擊座標選取器（全螢幕 overlay） | `pick_click_position()` |
| `clicker.ahk` | AHK TCP 伺服器 | 被動等待指令，執行滑鼠／鍵盤動作 |
| `images/` | 模板圖片庫 | `match_image` 步驟使用的圖示模板 PNG |

## Rule 資料結構

定義於 `core/04_rule_engine.py` 的 `Rule` dataclass。

v0.0.2 起改為統一步驟系統（Step System），不再區分觸發規則／比較規則。

### Rule（規則）

| 欄位 | 型態 | 說明 |
|------|------|------|
| `id` | str | UUID，如 `rule_a1b2c3d4` |
| `name` | str | 使用者自訂名稱 |
| `enabled` | bool | 是否啟用 |
| `background` | bool | 常駐監控模式，預設 `false` |
| `steps` | list[Step] | 有序步驟陣列，順序執行 |

### RuleGroup（規則群組）

| 欄位 | 型態 | 說明 |
|------|------|------|
| `id` | str | UUID |
| `name` | str | 使用者自訂名稱 |
| `enabled` | bool | 群組啟用／停用（停用群組不出現在啟動選單） |
| `mode` | str | 執行模式：`loop` 循環執行／`once` 執行一次／`repeat` 重複 N 次 |
| `repeat_times` | int | 重複次數（僅 `mode=repeat` 有效） |
| `between_rounds_sec` | int | 每輪完成後的等待秒數 |
| `rule_ids` | list[str] | 群組內規則 ID 的有序列表 |

### Step（步驟）

| 欄位 | 型態 | 說明 |
|------|------|------|
| `type` | str | 步驟類型（見下方對照表） |
| `params` | dict | 依類型而異的參數 |

### Step 類型對照表

| type | 用途 | params 關鍵欄位 |
|------|------|----------------|
| `detect` | OCR 偵測文字，未命中則觸發 on_fail | `text`, `roi`, `match_mode`, `fuzzy_threshold`, `on_fail`（stop/key/skip/jump） |
| `match_image` | 圖示模板比對，未命中則觸發 on_fail | `template`, `roi`, `threshold`, `on_fail`（stop/key/skip/jump） |
| `click` | 滑鼠點擊（設 `ctx.triggered = True`） | `target`（`text_center`/`custom`）、`x`, `y`, `button`, `random_offset` |
| `key` | 鍵盤按鍵（設 `ctx.triggered = True`） | `key`（AHK 格式）、`hold_ms` |
| `wait` | 固定等待 | `ms` |
| `jump` | 跳轉至另一規則（限同群組） | `rule_id` |
| `compare` | ROI 內數值比對 | `pattern`, `operator`, `value`, `on_fail` |
| `scroll` | 滑鼠滾輪（設 `ctx.triggered = True`） | `direction`, `amount`, `delay_ms` |
| `drag` | 滑鼠拖曳（設 `ctx.triggered = True`） | `target`, `dx`, `dy`, `button` |

### 舊格式自動遷移

`_migrate_v1_to_v2()` 偵測 JSON 中無 `"steps"` 欄位時自動將舊格式轉換為新步驟結構，保障 v0.0.1 任務不遺失。

## 主循環資料流 — 群組兩層指標模型

定義於 `core/05_main_loop.py` 的 `MainLoop._loop()`。

v0.3.0 起採用**群組兩層指標模型**，由 `_group_queue_idx`（群組佇列指標）與 `_rule_in_group_ptr`（群組內規則指標）共同控制執行順序。

```
                    ┌──────────────────┐
                    │  選擇目標視窗     │
                    │  啟動主循環       │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  擷取視窗畫面     │  capture() / capture_window_content()
                    │  (mss → fallback  │
                    │   GDI PrintWindow)│
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  畫面差異偵測     │  cv2.absdiff()
                    │  (前一幀比對)     │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  執行背景規則     │  每幀執行所有 background=True 的規則
                    │  (每幀全部執行)   │  獨立於群組流程，跳轉不生效
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  群組佇列指向     │  _active_group_ids[_group_queue_idx]
                    │  → 取得當前群組   │  → _current_group()
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  群組內規則指向   │  group.rule_ids[_rule_in_group_ptr]
                    │  → 取得當前規則   │  → _rule_map[rule_id]
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  執行規則的各步驟 │  _run_rule() → StepContext
                    │  ┌─────────────┐  │
                    │  │ detect      │──│── OCR 比對
                    │  │ match_image │  │    命中 → matched_text 傳遞給 click
                    │  │ compare     │  │    未命中 → on_fail（stop/key/skip/jump）
                    │  │ click/key   │  │    → ctx.triggered = True
                    │  │ scroll/drag │  │    → ctx.triggered = True
                    │  │ wait        │  │    → time.sleep()
                    │  │ jump        │  │    → 改寫 _rule_in_group_ptr
                    │  └─────────────┘  │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  ctx.triggered ? │  click/key/scroll/drag 任一執行過？
                    │  是→ 推進規則指標│  → _advance_rule_in_group()
                    │  否→ 停留原規則   │  下幀重試同一規則（等待觸發）
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  fps 控制 ~2fps  │  time.sleep(interval)
                    └────────────────────┘
```

### ctx.triggered 推進機制

`StepContext.triggered` 是控制規則指標前進的核心旗標：

- **設為 True 的步驟**：`click`、`key`、`scroll`、`drag`（這些步驟代表「已執行動作」）
- **不設 True 的步驟**：`detect`、`match_image`、`compare`、`wait`、`jump`（僅檢查或等待，非動作）
- **規則完成後**：若 `ctx.triggered == True`，呼叫 `_advance_rule_in_group()` 前進到下一條規則；若 `False`，指標不動，下幀重複同一規則

這意味著僅包含 `detect` 的規則（無點擊/按鍵）不會自行推進——確保「等待文字出現後才點擊」的語義正確。

### `_advance_rule_in_group()` 行為

1. 嘗試將 `_rule_in_group_ptr` 前進一格
2. 跳過停用的規則（`enabled=False`）
3. 若指標超出群組規則總數 → 呼叫 `_on_group_complete()`
4. `_on_group_complete()` 依群組 `mode` 決定：
   - **loop**：`_rule_in_group_ptr = 0`（回到群組開頭）
   - **once**：呼叫 `_advance_group_queue()` 進到下個群組
   - **repeat**：未達 `repeat_times` → `_rule_in_group_ptr = 0`；已達 → 進到下個群組
5. `_advance_group_queue()` 跳過停用的群組，若所有群組完成則停止循環

### 背景規則（常駐監控）

- `background=True` 的規則**每幀獨立執行**，不受 `_rule_in_group_ptr` 與 `_group_queue_idx` 影響
- 執行前儲存當前 `_rule_pointer`，執行後還原，確保不干擾群組流程
- `jump` 步驟在背景規則中不生效（`on_fail` 的 `jump` 動作不受此限）
- 不計入任何群組輪次，不耗費群組重複次數

### 核心設計原則

- **每幀只執行一條群組規則**（背景規則除外），避免單幀過載
- **未觸發則停留**：wait-only 或 detect-only 規則不推進，直到觸發動作為止
- **群組間隔**：每輪完成後依 `between_rounds_sec` 等待
- **跳轉限制**：`jump` 僅限同群組內跳轉，跨群組跳轉被拒絕（pointer 不動）

### 截圖雙重機制

1. **主要** `capture()`：透過 `mss` 擷取全視窗（含邊框標題列），需處理 DPI 縮放與多螢幕裁切
2. **備援** `capture_window_content()`：當 mss 失敗時，以 GDI `PrintWindow`／`BitBlt` 擷取 client area
   - 若備援結果小於全視窗尺寸，以黑邊填補至 `get_window_rect()` 回傳的大小（`05_main_loop.py:469-478`）

## 座標系統三層說明

### 三種座標

| 層級 | 來源 | 範圍 |
|------|------|------|
| **螢幕絕對** (screen-absolute) | ROI selector、click picker、`GetWindowRect` | 多螢幕虛擬桌面座標 |
| **視窗相對** (window-relative) | OCR 辨識結果、ROI 儲存值、點擊座標儲存值 | 以視窗左上角為 `(0,0)` |
| **影像像素** (image pixel) | numpy array `[h, w, 3]` | 截圖陣列索引 |

### 轉換發生點

```
來源                        原始座標          轉換方式                         最終
─────────────────────────────────────────────────────────────────────────────
OCR 辨識                     視窗相對          不需轉換                         視窗相對
debug panel 建立規則         視窗相對          不需轉換                         視窗相對
框選偵測區域 (gui_roi)       螢幕絕對          螢幕 - win_rect → 視窗相對       視窗相對
選取點擊座標 (click_picker)  螢幕絕對          螢幕 - win_rect → 視窗相對       視窗相對
主循環點擊                   視窗相對          win_rect + 視窗相對 → 螢幕絕對    螢幕絕對（送 AHK）
```

## AHK TCP 通訊協定

### 連線方式

- AHK 以 **TCP client** 模式主動連線 Python TCP server（`127.0.0.1:12345`）
- Python 端 `init_ahk()` 先啟動 socket server，再啟動 AHK 行程，等待 AHK 連入

### 指令格式

純文字行，以 `\n` 結尾。AHK 回覆 `"OK\n"` 表示成功。

| 指令 | 範例 | 說明 |
|------|------|------|
| `PING` | `PING\n` | 心跳檢查 |
| `CLICK,x,y,button` | `CLICK,500,300,left\n` | 滑鼠點擊，button 為 `left`／`right` |
| `MOVE,x,y` | `MOVE,500,300\n` | 滑鼠移動 |
| `KEY,key` | `KEY,Enter\n` | 鍵盤按鍵，支援 `{Key}` 與 AHK 修飾鍵格式（`^c` 等） |
| `ESTOP` | `ESTOP\n` | 緊急停止：放開所有滑鼠按鍵 |

### 心跳機制

- Python 端每 **5 秒**發送 `PING`
- AHK 端 recv timeout 預設 **5 秒**，心跳逾時 **30 秒**無指令則自動退出
- Python 連續 3 次 PING 失敗 → 觸發自動重啟 AHK（最多 3 次，達上限後永久停止）

### ESTOP 流程

```
MainLoop.emergency_stop()
  → self._emergency_event.set()
  → _ahk.send_emergency_stop()
     → send "ESTOP\n" to AHK
        → AHK 釋放所有滑鼠按鍵（Click Up）
        → 回覆 "OK"
```

## 資料持久化

### 任務路徑

```
專案根目錄/tasks/<任務名稱>.json
```

若使用 `build.get_data_path()`（PyInstaller 打包後），基底目錄改為使用者資料目錄。

### JSON 結構

```json
{
  "groups": [
    {
      "id": "group_a1b2c3d4",
      "name": "主要流程",
      "enabled": true,
      "mode": "loop",
      "repeat_times": 1,
      "between_rounds_sec": 0,
      "rule_ids": ["rule_a1b2c3d4", "rule_e5f6g7h8"]
    }
  ],
  "rules": [
    {
      "id": "rule_a1b2c3d4",
      "name": "點擊確認",
      "enabled": true,
      "background": false,
      "steps": [
        {
          "type": "detect",
          "params": {
            "text": "確認",
            "roi": { "x": 0, "y": 0, "w": 0, "h": 0 },
            "match_mode": "fuzzy",
            "fuzzy_threshold": 0.8,
            "on_fail": "stop"
          }
        },
        {
          "type": "click",
          "params": {
            "target": "text_center",
            "x": 0,
            "y": 0,
            "button": "left",
            "random_offset": 3
          }
        }
      ]
    },
    {
      "id": "rule_e5f6g7h8",
      "name": "檢查圖示",
      "enabled": true,
      "background": false,
      "steps": [
        {
          "type": "match_image",
          "params": {
            "template": "images/quest_icon.png",
            "roi": { "x": 100, "y": 200, "w": 50, "h": 50 },
            "threshold": 0.85,
            "on_fail": "stop"
          }
        },
        {
          "type": "click",
          "params": {
            "target": "text_center",
            "x": 0,
            "y": 0,
            "button": "left",
            "random_offset": 2
          }
        }
      ]
    }
  ]
}
```

### 頂層欄位：capture_size

```json
{
  "capture_size": [1920, 1080],
  "rules": [...]
}
```

`capture_size` 為選擇性欄位，記錄截圖當時的視窗解析度 `[寬, 高]`。寫入時機為使用者在 match_image 步驟截圖存模板時自動寫入。用途：`match_image` 執行時若 `capture_size` 存在，則根據當前視窗尺寸計算縮放比例 → 只跑單一 scale；若不存在（舊任務或手動編輯）則以多尺度 (0.8~1.2) fallback。

### 不存入 JSON 的欄位

無。所有 Rule 欄位均持久化，無執行期殘留狀態。

### 讀取時的回溯相容

`_dict_to_rule()` 透過 `_FIELD_DEFAULTS` 合併舊版 JSON：若檔案缺少某欄位則套用預設值，保障舊設定檔不因新增欄位而炸裂。

### 舊版遷移

`migrate_old_rules()` (`04_rule_engine.py`)：
- 若 `tasks/` 目錄為空，檢查舊版單一檔案 `rules.json`
- 存在則搬移為預設任務

### 舊格式 v0.0.x → v0.1.0 欄位遷移

`_migrate_v1_to_v2()` (`04_rule_engine.py`) 處理：
- `wait_rule` step → 跳過（skip），不再支援
- `collect_rounds` step → 還原為 `detect` + `click`/`key`
- `cooldown_ms` / `trigger_mode` / `max_triggers` → 直接清空，不再使用

### 任務匯入大小限制

`import_task()` 在載入前檢查 JSON 檔案大小，超過 **10MB** 則拒絕匯入，避免惡意或異常大型檔案造成記憶體爆量。

## 安全機制摘要

| 機制 | 位置 | 說明 |
|------|------|------|
| 螢幕邊界檢查 | `03_ahk_socket.py` | 發送 CLICK 前檢查座標是否在螢幕範圍內 |
| 全域速率限制 (CPS) | `10_performance_monitor.py` | 限制每秒點擊 ≤ 5 次，違規 3 次自動暫停偵測 |
| 前景保護 | `05_main_loop.py` | 僅在目標視窗為前景時才執行點擊，非前景時靜默等待 |
| OCR 連續失敗重啟 | `02_ocr_engine.py` | 連續 5 次失敗 → 重建引擎實例 |
| 視窗消失自動暫停 | `05_main_loop.py` | `get_window_rect()` 回傳 None → 暫停循環，每 5 秒檢查視窗是否重現 |
| Port 衝突偵測 | `03_ahk_socket.py` `init_ahk()` | 啟動時檢查 port 12345 是否已被佔用，衝突則中止避免雙行程干擾 |

## 開發注意事項

### 新增規則欄位時需同步

若在 `Rule` dataclass (`04_rule_engine.py`) 新增欄位：

1. **`_dict_to_rule()`** — 加入讀取邏輯（含型態轉換與 sanitize）
2. **`_rule_to_dict()`** — 若該欄位不應持久化，在此 `pop()`
3. **GUI 編輯表單** (`06_gui_main.py`) — 新增對應的 `QLineEdit`／`QSpinBox`／`QComboBox` 等
4. **`_show_rule_detail()`** — 填入欄位值到表單
5. **`_save_current_rule()`** — 儲存 name/enabled/steps/background，由切換規則或步驟變動觸發

### 新增群組欄位時需同步

若在 `RuleGroup` dataclass (`04_rule_engine.py`) 新增欄位：

1. **`_dict_to_group()`** — 加入讀取邏輯
2. **`_group_to_dict()`** — 若使用 `asdict()` 自動序列化則不需要手動處理
3. **`_show_group_settings()`** — 在群組設定對話框新增對應的 UI 元件
4. **`_refresh_rule_list()`** — 若影響群組節點顯示方式，更新繪製邏輯

### capture() / capture_window_content() 色彩格式差異

`01_screenshot.py` 中兩個擷取函式回傳的通道順序**不同**：

| 函式 | 來源 | 回傳格式 |
|------|------|----------|
| `capture()` | mss BGRA → `arr[:,:,:3]` | **BGR**（不做轉換） |
| `capture_window_content()` | GDI BGRA → `cv2.cvtColor(COLOR_BGRA2RGB)` | **RGB** |

`02_ocr_engine.py` 的 `_prepare_image()` 以 `COLOR_RGB2GRAY` 處理影像，因此：
- 若走主要路徑 `capture()`（BGR），通道順序與權重不符，但實務上對 OCR 結果影響極小
- 若走備援路徑 `capture_window_content()`（RGB），轉換正確

由於 RapidOCR 內部統一轉灰階，此差異**不影響最終辨識結果**。

### _loader 的跨模組呼叫

- Core 模組之間也使用 `load_sibling()` 互相依賴（如 `04_rule_engine` 載入 `02_ocr_engine`）
- 主循環 `05_main_loop` 透過 `load_sibling` 引入所有核心模組，然後用 module attribute 暴露給外部

### GUI 全螢幕 overlay 通用流程

ROI selector (`07_gui_roi.py`) 與 click picker (`13_gui_click_picker.py`) 共用模式：

1. 主視窗 `showMinimized()`
2. 建立無邊框全螢幕 widget（`WA_TranslucentBackground`, `FramelessWindowHint`）
3. 設定十字游標
4. 使用者操作（拖曳／單擊）或按 Esc 取消
5. 發送 `finished` signal → 關閉 overlay → 主視窗 `showNormal()`
6. 回傳結果（dict 或 tuple）

### GUI 執行緒安全

- `MainLoop` 在背景執行緒運行
- 回呼 `on_trigger`／`on_error` 等透過 `WorkerSignals` (pyqtSignal) 跨執行緒傳遞至 GUI 執行緒
- `_logs` deque 以 `_logs_lock` 保護
- `_rules` 以 `_rules_lock` 保護（包括 `reload_rules()` 寫入時也取得同一鎖，避免主循環讀取時與 GUI 寫入競爭）
- `on_info` 訊息透過 `info_signal` 傳至主執行緒，顯示於狀態列（3 秒自動消失）
