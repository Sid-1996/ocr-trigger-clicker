# OCR Trigger Clicker — 架構文件

## 專案定位

針對 Windows 遊戲／應用程式的畫面 OCR 自動化點擊工具：定期擷取視窗畫面，透過 OCR 辨識文字，比對觸發規則後自動模擬滑鼠點擊或鍵盤按鍵。

## 技術棧速覽

| 層級 | 技術 | 用途 |
|------|------|------|
| 語言 | Python 3.10+ | 主程式 |
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
                  │
core/03_ahk_socket─→  _loader ──→  core/10_performance_monitor（螢幕邊界檢查用）
```

### 各模組職責

| 檔案 | 角色 | 對外暴露 |
|------|------|----------|
| `core/01_screenshot.py` | 視窗擷取 | `capture()`, `capture_window_content()`, `list_windows()`, `get_window_rect()`, `activate_window()` |
| `core/02_ocr_engine.py` | OCR 引擎 | `init_engine()`, `recognize()`, `find_text()`, `OcrResult` |
| `core/03_ahk_socket.py` | AHK 輸入橋接 | `init_ahk()`, `send_click()`, `send_move()`, `send_key()`, `shutdown()` |
| `core/04_rule_engine.py` | 規則模型 + 任務管理 | `Rule`, `check_trigger()`, `apply_trigger()`, `load_task()`, `save_task()` |
| `core/05_main_loop.py` | 主偵測迴圈 | `MainLoop` class |
| `core/10_performance_monitor.py` | 效能監控 + 速率限制 | `PerformanceMonitor`, `get_screen_bounds()`, `is_window_foreground()` |
| `gui/06_gui_main.py` | 主視窗（工具列、規則編輯、狀態列） | `MainWindow` |
| `gui/07_gui_roi.py` | 框選偵測區域（全螢幕 overlay） | `select_roi()` |
| `gui/09_ocr_debug.py` | OCR 除錯面板（即時截圖＋標註） | `OcrDebugPanel` |
| `gui/13_gui_click_picker.py` | 點擊座標選取器（全螢幕 overlay） | `pick_click_position()` |
| `clicker.ahk` | AHK TCP 伺服器 | 被動等待指令，執行滑鼠／鍵盤動作 |

## Rule 資料結構

定義於 `core/04_rule_engine.py:16`。

### 基本欄位

| 欄位 | 型態 | 說明 |
|------|------|------|
| `id` | str | UUID，如 `rule_a1b2c3d4` |
| `name` | str | 使用者自訂名稱 |
| `enabled` | bool | 是否啟用 |
| `target_text` | str | OCR 比對目標文字 |
| `fuzzy` | bool | 是否啟用模糊比對 |
| `fuzzy_threshold` | float | 模糊比對相似度門檻（0~1） |
| `cooldown_ms` | int | 觸發後冷卻時間（毫秒） |
| `trigger_mode` | str | `"once"`（觸發一次後停用）／`"repeat"`（持續觸發） |
| `max_triggers` | int | 最大觸發次數（`-1` = 無限制） |

### 位置欄位

| 欄位 | 型態 | 座標系 | 說明 |
|------|------|--------|------|
| `roi` | dict | 視窗相對 | 偵測區域 `{x, y, w, h}`，全零 = 全視窗 |
| `click_position` | str | — | `"text_center"`（文字中心）／`"custom"`（自訂座標） |
| `custom_x`, `custom_y` | int | 視窗相對 | 自訂點擊座標 |
| `random_offset` | int | — | 點擊位置隨機抖動像素 |

### 動作欄位

| 欄位 | 型態 | 說明 |
|------|------|------|
| `action_type` | str | `"click"`（滑鼠點擊）／`"key"`（鍵盤按鍵） |
| `key` | str | 按鍵名稱（如 `Enter`, `^c` 等 AHK 格式） |
| `click_button` | str | `"left"`／`"right"` |
| `post_delay_ms` | int | 點擊／按鍵後等待毫秒 |

### 子目標（Phase 2）欄位

| 欄位 | 型態 | 說明 |
|------|------|------|
| `sub_target_text` | str | 子目標文字 |
| `sub_roi` | dict | 子目標偵測區域，全零 = 與主目標相同 |
| `sub_not_found_retries` | int | 子目標連續未找到容錯次數 |
| `on_found_action` | str | `"click_sub_center"`／`"click_custom"` |
| `on_found_custom_x`, `on_found_custom_y` | int | 子目標命中自訂座標 |
| `on_not_found_action` | str | `"click_nothing"`／`"click_custom"` |
| `on_not_found_custom_x`, `on_not_found_custom_y` | int | 子目標未找到自訂座標 |

### 依賴欄位

| 欄位 | 型態 | 說明 |
|------|------|------|
| `depends_on` | Optional[str] | 前置規則的 `id`。設此欄位後，主循環（`05_main_loop.py:392`）會檢查依賴的規則 `trigger_count >= 1` 才處理此規則 |

### 不持久化的執行期欄位

以下兩個欄位**不會寫入 JSON**（`_rule_to_dict` 在 `04_rule_engine.py:135` 以 `pop` 移除）：

| 欄位 | 型態 | 說明 |
|------|------|------|
| `trigger_count` | int | 已觸發次數，影響 `once` 模式與 `max_triggers` |
| `last_trigger_time` | float | 最後觸發時間（`time.monotonic`），用於冷卻檢查 |

## 主循環資料流

定義於 `core/05_main_loop.py` 的 `MainLoop._loop()`。

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
                   │  圖片前處理       │  _prepare_image() → 縮放 + 二值化（Otsu）
                   │  (光二值化)       │  (02_ocr_engine.py:152)
                   └────────┬─────────┘
                            │
                   ┌────────▼─────────┐
                   │  OCR 文字辨識     │  RapidOCR（DirectML + CPU）
                   │  (全畫面或 ROI)   │  30 秒 timeout，連續失敗 5 次重啟引擎
                   └────────┬─────────┘
                            │
                   ┌────────▼─────────┐
                   │  比對所有規則     │  check_trigger()：enabled、冷卻、模式、
                   │  (依序處理)       │  max_triggers、depends_on、模糊比對
                   └────────┬─────────┘
                            │
                   ┌────────▼─────────┐
                   │  命中 → 執行動作  │  apply_trigger() → 螢幕座標轉換
                   │  子目標檢查       │  _handle_sub_target()（可選階段二）
                   │  AHK 發送指令     │  _send_click() / _send_key()
                   └────────┬─────────┘
                            │
                   ┌────────▼─────────┐
                   │  冷卻等待         │  post_delay_ms（可選）
                   │  回寫 JSON        │  save_rules() 即時寫入
                   │  記錄 TriggerLog  │
                   └────────┬─────────┘
                            │
                   ┌────────▼─────────┐
                   │  循環間隔         │  預設 500ms（最小 100ms）
                   │  (FPS 顯示)       │
                   └────────────────────┘
```

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
      "target_text": "確認",
      "fuzzy": false,
      "fuzzy_threshold": 0.8,
      "roi": { "x": 0, "y": 0, "w": 0, "h": 0 },
      "click_position": "text_center",
      "click_button": "left",
      "cooldown_ms": 2000,
      "trigger_mode": "once",
      "max_triggers": -1,
      "random_offset": 3,
      "custom_x": 0,
      "custom_y": 0,
      "sub_target_text": "",
      "sub_roi": { "x": 0, "y": 0, "w": 0, "h": 0 },
      "sub_not_found_retries": 3,
      "on_found_action": "click_sub_center",
      "on_found_custom_x": 0,
      "on_found_custom_y": 0,
      "on_not_found_action": "click_nothing",
      "on_not_found_custom_x": 0,
      "on_not_found_custom_y": 0,
      "action_type": "click",
      "key": "",
      "post_delay_ms": 0,
      "depends_on": null
    }
  ]
}
```

### 不存入 JSON 的欄位

- `trigger_count`
- `last_trigger_time`

`_rule_to_dict()` (`04_rule_engine.py:135`) 將 `Rule` dataclass 序列化為 dict 後以 `pop()` 移除這兩個執行期狀態。

### 讀取時的回溯相容

`_dict_to_rule()` (`04_rule_engine.py:101`) 透過 `_FIELD_DEFAULTS` (`04_rule_engine.py:49`) 合併舊版 JSON：若檔案缺少某欄位則套用預設值，保障舊設定檔不因新增欄位而炸裂。

### 舊版遷移

`migrate_old_rules()` (`04_rule_engine.py:296`)：
- 若 `tasks/` 目錄為空，檢查舊版單一檔案 `rules.json`
- 存在則搬移為預設任務

## 安全機制摘要

| 機制 | 位置 | 說明 |
|------|------|------|
| 螢幕邊界檢查 | `03_ahk_socket.py:274` | 發送 CLICK 前檢查座標是否在螢幕範圍內 |
| 全域速率限制 (CPS) | `10_performance_monitor.py:224` | 限制每秒點擊 ≤ 5 次，違規 3 次自動暫停偵測 |
| Runaway 規則偵測 | `05_main_loop.py:617` | 10 秒內觸發 ≥ 5 次的規則自動停用 |
| 前景安全模式 | `05_main_loop.py:131` | 啟用後僅在目標視窗為前景時才執行點擊 |
| 緊急停止 (F12) | `05_main_loop.py:591` | 設事件旗標 + 發送 ESTOP 給 AHK（釋放所有按鍵） |
| OCR 連續失敗重啟 | `02_ocr_engine.py:41` | 連續 5 次失敗 → 重建引擎實例 |
| 視窗消失自動暫停 | `05_main_loop.py:451` | `get_window_rect()` 回傳 None → 暫停循環，每 5 秒檢查視窗是否重現 |

## 開發注意事項

### 新增規則欄位時需同步

若在 `Rule` dataclass (`04_rule_engine.py`) 新增欄位：

1. **`_FIELD_DEFAULTS`** (`04_rule_engine.py:49`) — 加入預設值，確保讀取舊 JSON 不炸裂
2. **`_dict_to_rule()`** (`04_rule_engine.py:101`) — 加入讀取邏輯（含型態轉換與 sanitize）
3. **`_rule_to_dict()`** (`04_rule_engine.py:135`) — 若該欄位不應持久化，在此 `pop()`
4. **GUI 編輯表單** (`06_gui_main.py`) — 新增對應的 `QLineEdit`／`QSpinBox`／`QComboBox` 等
5. **`_show_rule_detail()`** — 填入欄位值
6. **`_save_current_rule()`** — 讀取欄位值回寫 rule
7. **`_has_unsaved_changes()`**（若有）— 加入欄位比對

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
