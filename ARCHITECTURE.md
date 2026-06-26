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
| `core/04_rule_engine.py` | 規則模型 + 步驟系統 + 任務管理 | `Rule`, `Step`, `load_rules()`, `save_rules()`, `_migrate_v1_to_v2()` |
| `core/05_main_loop.py` | 主偵測迴圈（Rule Pointer 執行模型） | `MainLoop` class, `StepContext`, `StepResult` |
| `core/10_performance_monitor.py` | 效能監控 + 速率限制 | `PerformanceMonitor`, `get_screen_bounds()`, `is_window_foreground()` |
| `core/11_template_matching.py` | 圖示模板比對 | `match_template()`, `nms_suppress()`, `MatchResult` |
| `gui/06_gui_main.py` | 主視窗（工具列、規則編輯、狀態列） | `MainWindow` |
| `gui/07_gui_roi.py` | 框選偵測區域（全螢幕 overlay） | `select_roi()` |
| `gui/09_ocr_debug.py` | OCR 除錯面板（即時截圖＋標註） | `OcrDebugPanel` |
| `gui/13_gui_click_picker.py` | 點擊座標選取器（全螢幕 overlay） | `pick_click_position()` |
| `clicker.ahk` | AHK TCP 伺服器 | 被動等待指令，執行滑鼠／鍵盤動作 |
| `images/` | 模板圖片庫 | `match_image` 步驟使用的圖示模板 PNG |

## Rule 資料結構

定義於 `core/04_rule_engine.py:47`。

v0.0.2 起改為統一步驟系統（Step System），不再區分觸發規則／比較規則。

### Rule（規則）

| 欄位 | 型態 | 說明 |
|------|------|------|
| `id` | str | UUID，如 `rule_a1b2c3d4` |
| `name` | str | 使用者自訂名稱 |
| `enabled` | bool | 是否啟用 |
| `steps` | list[Step] | 有序步驟陣列，順序執行 |

### Step（步驟）

| 欄位 | 型態 | 說明 |
|------|------|------|
| `type` | str | 步驟類型（見下方對照表） |
| `params` | dict | 依類型而異的參數 |

### Step 類型對照表

| type | 用途 | params 關鍵欄位 |
|------|------|----------------|
| `detect` | OCR 偵測文字，未命中則中斷規則 | `text`, `roi`, `match_mode`, `fuzzy_threshold`, `on_fail`（stop/key/skip） |
| `match_image` | 圖示模板比對，未命中則中斷規則 | `template`, `roi`, `threshold`, `on_fail`（stop/key/skip） |
| `click` | 滑鼠點擊 | `target`（`text_center`/`custom`）、`x`, `y`, `button`, `random_offset` |
| `key` | 鍵盤按鍵 | `key`（AHK 格式） |
| `wait` | 固定等待 | `ms` |
| `jump` | 無條件跳轉至另一規則 | `rule_id` |

### 舊格式自動遷移

`_migrate_v1_to_v2()`（`04_rule_engine.py:150`）偵測 JSON 中無 `"steps"` 欄位時自動將舊格式轉換為新步驟結構，保障 v0.0.1 任務不遺失。

## 主循環資料流 — Rule Pointer 執行模型

定義於 `core/05_main_loop.py` 的 `MainLoop._loop()`。

v0.1.0 起採用 **Rule Pointer** 模型：一幀只執行 `rules[_rule_pointer]`，不再有「依序掃描全部規則」的行為。
每條規則執行完後 pointer 前進 1，除非 `jump` 步驟指定跳到某規則 ID（pointer 設為該規則索引）。

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
                   │  畫面差異偵測     │  cv2.absdiff()，變化 < 2% 跳過 OCR
                   │  (前一幀比對)     │
                   └────────┬─────────┘
                            │
                   ┌────────▼─────────┐
                   │  執行 rules[_ptr]  │  _rule_pointer 指向當幀要跑的規則
                   │  單一規則，無疊代  │
                   └────────┬─────────┘
                            │
                   ┌────────▼─────────┐
                   │  依序執行各 step  │  _run_rule() → StepContext
                   │  ┌─────────────┐  │
                   │  │ detect      │──│── OCR 比對，未命中 → stop(forward ptr)
                   │  │ match_image │  │    命中 → ctx.matched_text 傳遞
                   │  │ click       │  │    → AHK 發送指令
                   │  │ key         │  │    → AHK 發送按鍵
                   │  │ wait        │  │    → time.sleep()
                   │  │ jump        │  │    → _rule_pointer = 目標索引
                   │  └─────────────┘  │
                   │  step 回傳 stop   │
                   │  或 jump 即中斷   │
                   └────────┬─────────┘
                            │
                   ┌────────▼─────────┐
                   │    pointer += 1   │  除非 jump 已改寫 pointer
                   │   (除非 jumo 已   │
                   │    改寫 pointer)  │
                   └────────┬─────────┘
                            │
                   ┌────────▼─────────┐
                   │   fps 控制 ~2fps  │  time.sleep(0.5)
                   └────────────────────┘
```

核心差異：
- **無 `_cycle_visited`**：不再防呆，使用者要 loop 就自己 loop
- **無 `_auto_disabled`**：永不自動停用規則
- **無 `_pending_forced_triggers`**：所有執行路徑由 `jump` 明確指定
- **無 `wait_rule`/`collect_rounds`**：複雜邏輯回歸簡單順序執行
- **`on_fail` 支援三種值**：`"stop"`（預設，中斷規則）、`{"action":"key","key":"..."}`（發送按鍵後繼續）、`{"action":"skip","skip_to":N}`（跳至第 N 步繼續）。不再有 `retry_from`
- **match_image 行為與 detect 對稱**：`MatchResult` 也提供 center_x/center_y/text，click handler 不需修改

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
  "rules": [
    {
      "id": "rule_a1b2c3d4",
      "name": "點擊確認",
      "enabled": true,
      "steps": [
        {
          "type": "detect",
          "params": {
            "text": "確認",
            "roi": { "x": 0, "y": 0, "w": 0, "h": 0 },
            "fuzzy": false,
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
      "steps": [
        {
          "type": "match_image",
          "params": {
            "template": "images/quest_icon.png",
            "roi": { "x": 100, "y": 200, "w": 50, "h": 50 },
            "threshold": 0.85
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

### 不存入 JSON 的欄位

無。所有 Rule 欄位均持久化，無執行期殘留狀態。

### 讀取時的回溯相容

`_dict_to_rule()` (`04_rule_engine.py:101`) 透過 `_FIELD_DEFAULTS` (`04_rule_engine.py:49`) 合併舊版 JSON：若檔案缺少某欄位則套用預設值，保障舊設定檔不因新增欄位而炸裂。

### 舊版遷移

`migrate_old_rules()` (`04_rule_engine.py`)：
- 若 `tasks/` 目錄為空，檢查舊版單一檔案 `rules.json`
- 存在則搬移為預設任務

### 舊格式 v0.0.x → v0.1.0 欄位遷移

`_migrate_v1_to_v2()` (`04_rule_engine.py`) 處理：
- `wait_rule` step → 跳過（skip），不再支援
- `collect_rounds` step → 還原為 `detect` + `click`/`key`
- `cooldown_ms` / `trigger_mode` / `max_triggers` → 直接清空，不再使用

## 安全機制摘要

| 機制 | 位置 | 說明 |
|------|------|------|
| 螢幕邊界檢查 | `03_ahk_socket.py` | 發送 CLICK 前檢查座標是否在螢幕範圍內 |
| 全域速率限制 (CPS) | `10_performance_monitor.py` | 限制每秒點擊 ≤ 5 次，違規 3 次自動暫停偵測 |
| 前景保護 | `05_main_loop.py` | 僅在目標視窗為前景時才執行點擊，非前景時靜默等待 |
| OCR 連續失敗重啟 | `02_ocr_engine.py` | 連續 5 次失敗 → 重建引擎實例 |
| 視窗消失自動暫停 | `05_main_loop.py` | `get_window_rect()` 回傳 None → 暫停循環，每 5 秒檢查視窗是否重現 |

## 開發注意事項

### 新增規則欄位時需同步

若在 `Rule` dataclass (`04_rule_engine.py`) 新增欄位：

1. **`_FIELD_DEFAULTS`** (`04_rule_engine.py:49`) — 加入預設值，確保讀取舊 JSON 不炸裂
2. **`_dict_to_rule()`** (`04_rule_engine.py:101`) — 加入讀取邏輯（含型態轉換與 sanitize）
3. **`_rule_to_dict()`** (`04_rule_engine.py:135`) — 若該欄位不應持久化，在此 `pop()`
4. **GUI 編輯表單** (`06_gui_main.py`) — 新增對應的 `QLineEdit`／`QSpinBox`／`QComboBox` 等
5. **`_show_rule_detail()`** — 填入欄位值到表單
6. **`_on_name_changed()`** — 若為名稱欄位，在此同步更新 in-memory rule 與列表顯示
7. **`_save_current_rule()`** — 儲存 name/enabled/steps，由切換規則或步驟變動觸發

### capture() 回傳 RGB

`01_screenshot.py` 中：
- `capture()` (`:119`)：`return arr[:, :, :3]` — mss 回傳 BGRA，只取前 3 通道 = BGR，但此處**不做轉換**。呼叫方需注意。
- `capture_window_content()` (`:181`)：GDI 回傳 BGRA，以 `cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)` 轉為 RGB。
- `02_ocr_engine.py:174` 有明確註解「capture() 回傳 RGB，這裡要用 RGB2GRAY」，意即原始 `capture()` 回傳的 `[:,:,:3]` 在上下文中被視為 RGB。

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
- `_rules` 以 `_rules_lock` 保護
- `on_info` 訊息透過 `info_signal` 傳至主執行緒，顯示於狀態列（3 秒自動消失）
