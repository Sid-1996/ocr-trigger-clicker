# OCR Trigger Clicker — 架構文件

## 專案定位

針對 Windows 遊戲／應用程式的畫面 OCR 自動化點擊工具：定期擷取視窗畫面，透過 OCR 辨識文字，比對觸發規則後自動模擬滑鼠點擊或鍵盤按鍵。

## 技術棧速覽

| 層級 | 技術 | 用途 |
|------|------|------|
| 語言 | Python 3.12 | 主程式 |
| GUI | PyQt6 | 設定視窗、偵測日誌、除錯面板、日誌檢視器 |
| OCR | rapidocr-onnxruntime (DirectML + CPU) | 文字辨識 |
| 影像處理 | OpenCV (cv2), numpy | 截圖、縮放、二值化、差異偵測 |
| 輸入模擬（前景） | pynput | 滑鼠點擊／移動、鍵盤按鍵（SendInput） |
| 輸入模擬（後台） | Win32 PostMessage | 後台模式不搶焦點模擬輸入 |
| 截圖 | mss / dxcam / GDI PrintWindow | 前景 mss → dxcam → GDI 備援；後台 PrintWindow |
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
gui/06_gui_main.py  ──→  _loader ──→  core/04_rule_engine   ──→  core/02_ocr_engine
                  │               └──→  core/05_main_loop     ──→  core/17_capture_pipeline
                   │               └──→  core/03_pynput_input  ──→  core/02_ocr_engine
                   │               └──→  gui/09_ocr_debug      ──→  core/03_pynput_input
                  │               └──→  gui/07_gui_roi        ──→  core/04_rule_engine
                  │               └──→  core/02_ocr_engine
                  │               └──→  core/10_performance_monitor
                  │               └──→  core/11_template_matching
                  │               └──→  core/12_updater
                  │               └──→  core/00_global_hotkey
                  │               └──→  core/00_logging_config
                  │               └──→  core/16_bg_input
                  │               └──→  gui/group_settings_controller
                  │               └──→  gui/screenshot_controller
                  │               └──→  gui/rule_config_controller
                  │               └──→  gui/test_run_controller
                  │
core/05_main_loop ──→  _loader ──→  core/17_capture_pipeline
                   │               └──→  core/02_ocr_engine
                    │               └──→  core/03_pynput_input
                    │               └──→  core/16_bg_input
                    │               └──→  core/04_rule_engine
                   │               └──→  core/10_performance_monitor
                   │               └──→  core/11_template_matching
                   │               └──→  core/00_logging_config
                   │
core/17_capture_pipeline ──→ _loader ──→  core/01_screenshot
                    │               └──→  core/15_print_window
                   │
core/03_pynput_input                              （無外部依賴，螢幕邊界檢查內聯於模組本身）
```

### 各模組職責

| 檔案 | 角色 | 對外暴露 |
|------|------|----------|
| `core/01_screenshot.py` | 視窗擷取 | `capture()`, `capture_window_content()`, `list_windows()`, `get_window_rect()`, `activate_window()`, `activate_window_bg()` |
| `core/02_ocr_engine.py` | OCR 引擎 | `init_engine()`, `recognize()`, `find_text()`, `OcrResult` |
| `core/03_pynput_input.py` | 輸入模擬（前景 pynput SendInput） | `send_click()`, `send_key()`, `send_scroll()`, `send_drag()`, `send_hold_key()` |
| `core/box_utils.py` | 座標工具集（純函式） | `roi_center()`, `roi_to_pixels()`, `roi_crop()`, `roi_sanitize()`, `box_to_rect()` 等 10 函式 |
| `core/04_rule_engine.py` | 規則引擎 re-export hub（委派給 6 個子模組） | `Rule`, `RuleGroup`, `Step`, `load_groups()`, `save_groups()`, `load_rules()`, `save_rules()` |
| `core/rule_models.py` | 資料模型（dataclass） | `Rule`, `RuleGroup`, `Step`, `ImportPreview` |
| `core/rule_migration.py` | 舊格式遷移 + 步驟正規化 | `_migrate_v1_to_v2()`, `migrate_v2_to_v3()`, `_normalize_step_params()` |
| `core/rule_serialization.py` | 規則/群組 JSON 序列化 | `load_rules()`, `save_rules()`, `load_groups()`, `save_groups()` |
| `core/task_management.py` | 任務檔案 CRUD | `list_tasks()`, `load_task()`, `save_task()`, `import_task()`, `export_task()` |
| `core/run_config.py` | 任務視窗/執行模式/擷取尺寸存取 | `get_task_window()`, `set_run_mode()`, `get_capture_size()` |
| `core/file_utils.py` | 原子檔案寫入工具 | `_replace_file()` |
| `core/05_main_loop.py` | 主偵測迴圈（群組兩層指標模型 + 重疊 ROI OCR 合併） | `MainLoop` class, `StepContext`, `StepResult`, `set_active_groups()` |
| `core/15_print_window.py` | 後台截圖（PrintWindow）＋權限/全黑偵測 | `capture_print_window_hwnd()`, `capture_print_window()`, `is_admin()`, `is_black_capture()` |
| `core/16_bg_input.py` | 後台互動（PostMessage / pynput 切換） | `set_method()`, `click()`, `key()`, `drag()`, `scroll()` |
| `core/17_capture_pipeline.py` | 統一台式截圖管道（依互動模式選唯一來源，全路徑同源） | `capture_frame(mode, title, hwnd)` |
| `core/10_performance_monitor.py` | 效能監控 + 速率限制 + 點擊統計 | `PerformanceMonitor`, `get_screen_bounds()`, `is_window_foreground()`, `get_total_clicks()` |
| `core/11_template_matching.py` | 圖示模板比對 + inline 模板 LRU 解碼快取 | `match_template()`, `nms_suppress()`, `MatchResult`, `clear_template_cache()` |
| `gui/06_gui_main.py` | 主視窗（工具列、規則編輯、狀態列、系統托盤、設定對話框） | `MainWindow`, `SettingsDialog` |
| `gui/07_gui_roi.py` | 框選偵測區域（全螢幕 overlay） | `select_roi()` |
| `gui/09_ocr_debug.py` | OCR 除錯面板（即時截圖＋標註） | `OcrDebugPanel` |
| `gui/13_gui_click_picker.py` | 點擊座標選取器（全螢幕 overlay） | `pick_click_position()` |
| `core/12_updater.py` | 自動更新核心邏輯（版本檢查、下載、解壓、套用更新） | `check_for_update()`, `download_update()`, `apply_update()` |
| `core/00_logging_config.py` | 日誌設定 | `get_logger()`, `get_log_dir()`, `set_debug()`, `is_debug_enabled()` |
| `gui/12_log_viewer.py` | 日誌檢視器（tail app.log、層級過濾、搜尋、DEBUG 切換、捲動保持） | `LogViewer` |
| `gui/17_bg_roi_selector.py` | 後台偵測區域選取器（PrintWindow 截圖 + QLabel） | `BgRoiSelector` |
| `gui/18_bg_click_picker.py` | 後台座標選取器（PrintWindow 截圖 + QLabel） | `BgClickPicker` |
| `core/00_global_hotkey.py` | 全域熱鍵（Win32 `RegisterHotKey`） | F8 熱鍵註冊 |
| `gui/group_settings_controller.py` | 群組設定對話框控制器（v0.0.10 從 MainWindow 拆出） | `GroupSettingsController` |
| `gui/screenshot_controller.py` | 截圖／模板控制器（v0.0.10 從 MainWindow 拆出） | `ScreenshotController` |
| `gui/rule_config_controller.py` | 規則配置控制器（v0.0.10 從 MainWindow 拆出） | `RuleConfigController` |
| `gui/test_run_controller.py` | 乾執行測試控制器（v0.0.10 從 MainWindow 拆出） | `TestRunController` |
| `gui/14_capture_region.py` | 區域截圖選取器（match_image 模板來源） | `capture_region()` |
| `updater_main.py` | 獨立更新行程（以 `WaitForSingleObject` 等待母進程、重試複製、重新啟動、清理暫存） | **無對外匯出**，由 `apply_update()` 以 `subprocess.Popen` 啟動 |
| `docs/` | GitHub Pages 專案網站（含 `index.html`、Google Search Console 驗證） | 由 `sid-1996.github.io/ocr-trigger-clicker/` 發布 |
| （無對應資料夾） | match_image 模板隨任務 `.json` 內嵌 | `match_image` 步驟的 `template_data` 為 base64 PNG，存於任務檔本身；不另設 `images/` 目錄 |

## Rule 資料結構

定義於 `core/rule_models.py` 的 `Rule` dataclass。

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
| `mode` | str | 執行模式：`loop` 循環執行／`once` 執行一次（預設）／`repeat` 重複 N 次 |
| `repeat_times` | int | 重複次數（僅 `mode=repeat` 有效） |
| `between_rounds_sec` | int | 每輪完成後的等待秒數 |
| `rule_ids` | list[str] | 群組內規則 ID 的有序列表 |
| `order` | str | 執行順序模式：`sequential` 依序（預設） |

### Step（步驟）

| 欄位 | 型態 | 說明 |
|------|------|------|
| `type` | str | 步驟類型（見下方對照表） |
| `params` | dict | 依類型而異的參數 |

### Step 類型對照表

| type | 用途 | params 關鍵欄位 |
|------|------|----------------|
| `detect` | OCR 偵測文字，未命中則觸發 on_fail | `text`, `roi`, `match_mode`, `fuzzy_threshold`, `on_fail`（stop/key/skip/jump/notify + fail_duration_sec） |
| `match_image` | 圖示模板比對，未命中則觸發 on_fail | `template`, `roi`, `threshold`, `match_color`, `color_tolerance`, `on_fail`（stop/key/skip/jump/notify + fail_duration_sec） |
| `click` | 滑鼠點擊（設 `ctx.triggered = True`） | `target`（`text_center`/`custom`/`cursor`）、`x`, `y`, `button`, `random_offset`, `hold_ms` |
| `key` | 鍵盤按鍵（設 `ctx.triggered = True`） | `key`（pynput 格式）、`hold_ms` |
| `wait` | 固定等待 | `ms` |
| `jump` | 跳轉至另一規則（限同群組） | `rule_id` |
| `compare` | ROI 內數值比對 | `pattern`, `operator`, `value`, `on_fail`（stop/key/skip/jump/notify + fail_duration_sec） |
| `notify` | 提示訊息彈窗（設 `ctx.triggered = True`） | `message` |
| `scroll` | 滑鼠滾輪（設 `ctx.triggered = True`） | `direction`, `amount`, `delay_ms` |
| `drag` | 滑鼠拖曳（設 `ctx.triggered = True`） | `target`, `dx`, `dy`, `button` |

### on_fail fail_duration_sec

`on_fail` 支援選擇性欄位 `fail_duration_sec`（float，秒）：

- 設為 0（預設）：on_fail 立即生效
- 設為 >0：首次觸發 on_fail 時不立即執行動作，而是等待指定秒數後再次檢查 → 若仍未命中才執行動作
- 用途：避免短暫的畫面閃爍或遮擋導致誤判，可用於「等待文字持續消失 N 秒後再執行」的情境
- 支援：`detect`、`match_image`、`compare` 的 on_fail

### 舊格式自動遷移

- `_migrate_v1_to_v2()` 偵測 JSON 中無 `"steps"` 欄位時自動將舊格式轉換為新步驟結構，保障 v0.0.1 任務不遺失

## 主循環資料流 — 群組兩層指標模型

定義於 `core/05_main_loop.py` 的 `MainLoop._loop()`。

v0.1.0 起採用**群組兩層指標模型**，由 `_group_queue_idx`（群組佇列指標）與 `_rule_in_group_ptr`（群組內規則指標）共同控制執行順序。

```
                    ┌──────────────────┐
                    │  選擇目標視窗     │
                    │  啟動主循環       │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                     │  擷取視窗畫面     │  capture_frame() 統一管線
                     │  (前景 mss →     │  依互動模式選唯一來源：
                     │   dxcam → GDI;   │  前景 mss 三層備援 / 後台 PrintWindow
                     │   後台 PrintWindow)│
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
                     │  │ detect      │──│── OCR 比對（支援同幀快取）
                     │  │ match_image │  │    命中 → matched_text 傳遞給 click
                     │  │ compare     │  │    未命中 → on_fail（stop/key/skip/jump/notify）
                    │  │ click/key   │  │    → ctx.triggered = True
                    │  │ notify      │  │    → ctx.triggered = True
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

- **設為 True 的步驟**：`click`、`key`、`notify`、`scroll`、`drag`（這些步驟代表「已執行動作」）
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

### on_fail notify 流程

`on_fail` 的 `notify` 動作會：
1. 在 GUI 狀態列顯示通知訊息（5 秒自動消失）
2. 同時跳出系統托盤彈窗（5 秒）
3. 若設定了 `stop_groups`，將指定群組從 `_active_group_ids` 移除並呼叫 `_advance_group_queue()`
4. 設 `ctx.triggered = True` 使規則前進，避免卡住重試

### notify（步驟類型）

作為獨立步驟類型使用時（非 on_fail），`notify` 會：
1. 跳出系統托盤彈窗顯示 `message`（5 秒自動消失）
2. 設 `ctx.triggered = True`，推進規則指標
- 不影響群組流程、不停止任何群組
- 適用於「偵測到文字後提醒使用者」的情境，可接在 `detect` 步驟之後

### OCR 結果同幀快取

同一幀內多條背景規則若使用相同 ROI，OCR 結果會被快取（以 ROI tuple 為 key），避免 N+1 次重複辨識。此機制在 `05_main_loop.py` 的 `_process_rules` 中實作，每幀開始時清空快取。

### 核心設計原則

- **每幀只執行一條群組規則**（背景規則除外），避免單幀過載
- **未觸發則停留**：wait-only 或 detect-only 規則不推進，直到觸發動作為止
- **群組間隔**：每輪完成後依 `between_rounds_sec` 等待
- **跳轉限制**：`jump` 僅限同群組內跳轉，跨群組跳轉被拒絕（pointer 不動）

### 截圖統一管線（capture_frame）

`core/17_capture_pipeline.py` 提供 `capture_frame(mode, title, hwnd)`，**全路徑同源**（建立模板／測試／圖片比對／主循環執行共用）：

- **後台模式**（`mode != "pynput"`）：`capture_print_window_hwnd()`（或依 title 查 hwnd）→ PrintWindow 全視窗影像；失敗 fallback 到前景管線
- **前景模式**（`mode == "pynput"`）三層備援：
  1. `capture()`（mss 擷取全視窗，含 DPI 縮放與多螢幕裁切）
  2. `_capture_dxcam()`（mss 失敗時 DXGI 底層，相容性較高）
  3. `capture_window_content()`（GDI PrintWindow/BitBlt 僅 client area）→ `_pad_to_full()` 填補黑邊至全視窗大小

後台 PrintWindow 同樣產出全視窗大小影像（黑邊於 chrome offset 位置），座標還原時以 `roi_coord:"client"` 標記區分客戶區基準。

## 座標系統三層說明

### 三種座標

| 層級 | 來源 | 範圍 |
|------|------|------|
| **螢幕絕對** (screen-absolute) | ROI selector、click picker、`GetWindowRect` | 多螢幕虛擬桌面座標 |
| **視窗相對** (window-relative) | OCR 辨識結果、主循環內部運算 | 以視窗左上角為 `(0,0)`，單位像素 |
| **客戶區比例** (client-ratio) | 後台 ROI/座標選取器、`roi_coord:"client"` 標記 | 0~1 比值，基準為客戶區（不含標題列/邊框） |
| **視窗比例** (window-ratio) | ROI 儲存值、點擊座標儲存值 | 0~1 比值，與視窗解析度無關 |
| **影像像素** (image pixel) | numpy array `[h, w, 3]` | 截圖陣列索引 |

### 轉換發生點

```
來源                        原始座標          轉換方式                               最終
──────────────────────────────────────────────────────────────────────────────────
OCR 辨識                     視窗相對          × 暫不轉換，保留像素值                  視窗相對
debug panel 建立規則         視窗相對          ÷ win_size → 比例座標                   視窗比例
框選偵測區域 (gui_roi)       螢幕絕對          (螢幕 - win_rect) ÷ win_size → 比例      視窗比例
選取點擊座標 (click_picker)  螢幕絕對          (螢幕 - win_rect) ÷ win_size → 比例      視窗比例
後台框選/座標 (bg selectors) 影像像素          (像素 - chrome) ÷ client_size → 比例     客戶區比例
主循環 _resolve_roi()        視窗比例          × 當前 capture 圖寬高 → 像素              影像像素
主循環 _resolve_point()      視窗比例          × 當前視窗寬高 → 像素 → +win_rect        螢幕絕對（送 pynput / PostMessage）
```

### 比例轉換實作

`05_main_loop.py` 的 `_resolve_roi()` 與 `_resolve_point()` 負責將比例座標還原為像素：

- `_resolve_roi(roi_dict, img_width, img_height)` → `(x, y, w, h)` 像素整數，用於影像裁切
- `_resolve_point(point_dict, win_width, win_height)` → `(x, y)` 像素整數，加上視窗偏移後送 `send_click()`

## 輸入模擬（前景 pynput / 後台 PostMessage）

互動方法由 `interaction_mode` 決定（`foreground` / `postmessage`），`MainLoop._send_click` / `_send_key` / `_send_drag` / `_send_scroll` 依模式分派到對應輸入模組。

### 前景：pynput（SendInput）

`core/03_pynput_input.py` 使用 `pynput.mouse.Controller` 與 `pynput.keyboard.Controller`（底層為 Windows `SendInput` API），所有操作皆為同步、無外部行程。

| 函式 | 用途 | 底層實作 |
|------|------|----------|
| `send_click(x, y, button)` | 滑鼠點擊 | `mouse.position = (x, y)` → `mouse.click(btn)` |
| `send_key(key)` | 鍵盤按鍵（含 Ctrl+Combo `^c` 格式） | `kb.press(parsed)` → `time.sleep(0.02)` → `kb.release(parsed)` |
| `send_hold_key(key, ms)` | 按住一段時間後放開 | `press` → `time.sleep(ms/1000)` → `release` |
| `send_drag(x1,y1,x2,y2,button)` | 拖曳 | `press` at (x1,y1) → `position = (x2,y2)` → `release` |
| `send_scroll(amount, direction)` | 滾輪 | `mouse.scroll(dx, dy)` |
| `send_emergency_stop()` | 緊急停止（in-process noop） | 僅 log + return True，`MainLoop._stop_event` 為實際中斷來源 |

### 後台：PostMessage

`core/16_bg_input.py` 以 Win32 `PostMessage` 直接對目標視窗送出 `WM_LBUTTONDOWN`/`WM_KEYDOWN` 等訊息，**不搶焦點、不需視窗在前景**（適合後台掛機）。使用前 `ScreenToClient` 將螢幕絕對座標轉為客戶區座標。

- `set_method(method)`：切換 PostMessage / pynput（pynput 作為後台模式的 fallback）
- `click(hwnd, x, y, button, hold_ms)` / `key(hwnd, vk, hold_ms)` / `drag(hwnd, x1,y1,x2,y2, button)` / `scroll(hwnd, ...)`

> 限制：Unity 遊戲不支援 PostMessage，需使用前景模式。

### 按鍵對應

- `_KEY_MAP`：29 個命名鍵（F1-F12、方向鍵、修飾鍵等）
- `_NUMPAD_VK`：10 個九宮格鍵（Numpad0-9、NumpadAdd 等）
- 單字元文字：`pynput.keyboard.KeyCode.from_char()`
- Ctrl+Combo：`^` 前綴解析（如 `^c` → Ctrl+C）

### ESTOP 流程（簡化）

```
MainLoop.emergency_stop()
  → self._emergency_event.set()
  → send_emergency_stop()
     → log + return True（無外部行程可殺）
```

## 資料持久化

### 任務路徑

任務 JSON 的基底目錄由 `_tasks_base()`（`core/task_management.py:17`）決定：

| 執行模式 | 基底目錄 |
|----------|----------|
| `python gui/06_gui_main.py`（開發模式） | `%APPDATA%\ocr-trigger-clicker\` |
| 打包 EXE（PyInstaller） | `%APPDATA%\ocr-trigger-clicker\` |

兩種模式皆同，因為 `core._paths.get_data_path()` 在任何模式皆可 import。可透過環境變數 `OCR_TRIGGER_DATA` 覆蓋基底路徑。

任務檔案：`<基底>/tasks/<任務名稱>.json`（如 `%APPDATA%\ocr-trigger-clicker\tasks\每日任務.json`）。

### 匯入／匯出

匯入與匯出的對話框起始目錄：

| 執行模式 | 起始目錄 |
|----------|----------|
| `python gui/06_gui_main.py` | 專案根目錄（`_here` = `Path(__file__).resolve().parent.parent`） |
| 打包 EXE | PyInstaller 暫存目錄（`sys._MEIPASS`），通常為 `%TEMP%\_MEIxxxxx` |

使用者可透過對話框自由選擇任意路徑，起始目錄僅為開啟對話框時的預設位置。

### 全域設定 config.json

路徑：`<data_base>/config.json`（資料庫基底同任務目錄）

| Key | 型態 | 預設值 | 用途 |
|-----|------|--------|------|
| `hide_startup_guide` | bool | false | 是否隱藏新手導覽對話框 |
| `last_window` | str | "" | 上次選取的目標視窗標題 |
| `last_task` | str | "" | 上次選取的任務名稱 |
| `simplified_mode` | bool | false | 簡易模式（隱藏進階選項） |
| `interaction_mode` | str | `"pynput"` | 互動方法：`"pynput"`（前景 SendInput）／`"postmessage"`（後台 PostMessage） |
| `close_behavior` | str | `"tray"` | 關閉按鈕行為：`"tray"`（縮小至托盤）／`"quit"`（直接關閉） |
| `show_close_confirm` | bool | true | 關閉前是否顯示確認對話框 |

寫入時機：`SettingsDialog._on_accept()`（使用者按確定時一次性寫入全部值）。

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
            "on_fail": { "action": "stop" }
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
            "match_color": true,
            "color_tolerance": 100,
            "on_fail": { "action": "stop" }
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

`migrate_old_rules()` (`core/04_rule_engine.py`)：
- 若 `tasks/` 目錄為空，檢查舊版單一檔案 `rules.json`
- 存在則搬移為預設任務

### 舊格式 v0.0.x → v0.1.0 欄位遷移

`_migrate_v1_to_v2()` (`core/rule_migration.py`) 處理：
- `wait_rule` step → 跳過（skip），不再支援
- `collect_rounds` step → 還原為 `detect` + `click`/`key`
- `cooldown_ms` / `trigger_mode` / `max_triggers` → 直接清空，不再使用

### 任務匯入大小限制

`import_task()` 在載入前檢查 JSON 檔案大小，超過 **10MB** 則拒絕匯入，避免惡意或異常大型檔案造成記憶體爆量。

## 安全機制摘要

| 機制 | 位置 | 說明 |
|------|------|------|
| 螢幕邊界檢查 | `03_pynput_input.py` | `send_click()`／`send_drag()` 前檢查座標是否在虛擬螢幕範圍內 |
| 全域速率限制 (CPS) | `10_performance_monitor.py` | 限制每秒點擊 ≤ 5 次，違規 3 次自動暫停偵測 |
| 前景保護 (目標視窗) | `05_main_loop.py` | 僅在目標視窗為前景時才執行點擊，非前景時靜默等待 |
| 前景保護 (工具視窗) | `05_main_loop.py` | 工具自身視窗在前景時自動暫停 click/key/drag/scroll，防止誤搶焦點（後台模式直接回傳 False，不誤擋） |
| 後台全黑偵測 | `15_print_window.py` `is_black_capture()` | 後台截圖全像素為零才命中（暗色遊戲不誤判）；搭配 `is_admin()` 提醒以系統管理員重啟 |
| OCR 連續失敗重啟 | `02_ocr_engine.py` | 連續 5 次失敗 → 重建引擎實例 |
| 視窗消失自動暫停 | `05_main_loop.py` | `get_window_rect()` 回傳 None → 暫停循環，每 5 秒檢查視窗是否重現 |
| 座標驗證 | `03_pynput_input.py` `_validate_coords()` | 使用 `GetSystemMetrics(VIRTUALSCREEN)` 確保點擊不超出多螢幕範圍 |
| 關閉行為設定 | `06_gui_main.py` `SettingsDialog` | 可選「縮小至托盤」或「直接關閉」，關閉前可跳出確認對話框 |

## 日誌架構（三通道）

`MainLoop` 有三種日誌通道，用途不同，**不可混用**：

| 通道 | 方法 | 寫入目標 | GUI 可見？ | 適用場景 |
|------|------|----------|-----------|----------|
| 檔案日誌 | `self._log()` | Python `logging` → `app.log` | ✅ 日誌檢視器（LogViewer） | debug 記錄、非 GUI 訊息 |
| 執行日誌 | `self._log_exec()` | `self._execution_log` (deque) **+ 同時寫入 `app.log`**（`[exec]` 行） | ✅ 執行日誌面板 + 日誌檢視器 | 步驟成功/失敗/跳轉等結果 |
| 通知彈窗 | `self.on_warning()` | Qt signal → 系統托盤通知 | ✅ 通知彈窗 | 需要使用者注意的警告 |

- `app.log` 路徑：`%APPDATA%\ocr-trigger-clicker\logs\app.log`，`core/00_logging_config.py` 統一管理（midnight 輪替，backupCount=1）
- `set_debug(enabled)` / `is_debug_enabled()`：runtime 雙向切換 DEBUG 層級（LogViewer 的「啟用詳細日誌」checkbox）
- 生命週期事件（`log_main()`：循環開始/停止、視窗遺失、應用啟動）與執行事件（`[exec]`）皆為 INFO 層級
- 循環停止時 `log_main()` 輸出統計：執行秒數、點擊次數（`PerformanceMonitor.get_total_clicks()`）、規則數
- `cleanup_stale_logs()`：啟動時刪除 `debug.log` / `run_stderr.log` / `triggers.jsonl*` 舊檔

### LogViewer 捲動行為

- 每 1.5s 定時 tail app.log（500 行），內容未變時**不重繪**（`_last_text` 比對）
- 自動捲到底僅在接近底部時（距底 ≤ `_FOLLOW_TOLERANCE=20`）；向上瀏覽歷史時保留捲動位置，不被新內容拉回

### 執行日誌面板資料流

```
_handle_detect / _handle_compare / _handle_click / ...
       │
       ▼  回傳 StepResult
_run_rule()
       │
       ├── result.action == "ok"    → _log_exec(rule, i, type, "ok", detail)
       ├── result.action == "stop"  → _log_exec(rule, i, type, "stop", detail)
       └── result.action == "jump"  → _log_exec(rule, i, type, "jump", detail)
                                       │
                                       ├── ▼
                                       │   self._execution_log.append({ts, rule_name, step_idx, ...})
                                       │   │
                                       │   ▼
                                       │   GUI _update_exec_log() ← 定時輪詢
                                       │   │
                                       │   ▼
                                       │   _exec_log_widget._populate(entries)
                                       │
                                       └── ▼
                                           self._logger.info("[exec] rule=... result=... detail=...")
                                           │
                                           ▼
                                           app.log（LogViewer 每 1.5s tail 500 行）
```

### 常見錯誤

**錯誤：在 step handler 中用 `self._log()` 報告執行結果**
```python
# ❌ 錯誤：只寫入 app.log，GUI 執行日誌面板看不到
self._log(f"規則「{rule.name}」全圖 OCR 耗時 {elapsed_ms:.0f} ms")
```

**正確：透過 `_log_exec` 或在 detail 中附加資訊**
```python
# ✅ 正確：透過 StepContext 傳遞，由 _build_ok_detail 組裝進執行日誌
ctx.ocr_elapsed_ms = elapsed_ms  # 在 handler 中設定
# → _build_ok_detail 會自動附加 "(871ms)" 到 detail 字串
```

### `_build_ok_detail` 產生的 detail 格式

| step_type | detail 內容 |
|-----------|------------|
| detect | 匹配到的文字（前 15 字） |
| compare | 匹配到的數值 |
| match_image | `信心度 XX%` |
| click | 匹配到的文字（前 15 字） |
| key | 按鍵名稱 |
| scroll | 方向 + 次數 |
| drag | 目標類型 |

### 執行日誌 dedup 機制

- `result == "completed"`（輪次完成）：同一規則 1 秒內只記一次
- 其他 result：同一 `rule_name:step_idx` + 同一 `result+detail` 組合只記一次
- `maxlen=10`：只保留最近 10 筆

## 開發注意事項

### 新增規則欄位時需同步

若在 `Rule` dataclass (`core/rule_models.py`) 新增欄位：

1. **`_dict_to_rule()`** — 加入讀取邏輯（含型態轉換與 sanitize）
2. **`_rule_to_dict()`** — 若該欄位不應持久化，在此 `pop()`
3. **GUI 編輯表單** (`06_gui_main.py`) — 新增對應的 `QLineEdit`／`QSpinBox`／`QComboBox` 等
4. **`_show_rule_detail()`** — 填入欄位值到表單
5. **`_save_current_rule()`** — 儲存 name/enabled/steps/background，由切換規則或步驟變動觸發

### 新增群組欄位時需同步

若在 `RuleGroup` dataclass (`core/rule_models.py`) 新增欄位：

1. **`_dict_to_group()`** — 加入讀取邏輯
2. **`_group_to_dict()`** — 若使用 `asdict()` 自動序列化則不需要手動處理
3. **`_show_group_settings()`** — 在群組設定對話框新增對應的 UI 元件
4. **`_refresh_rule_list()`** — 若影響群組節點顯示方式，更新繪製邏輯

### capture() / capture_window_content() 色彩格式差異

`01_screenshot.py` 中兩個擷取函式回傳的通道順序**不同**：

| 函式 | 來源 | 回傳格式 |
|------|------|----------|
| `capture()` | mss BGRA → `arr[:,:,:3]` | **BGR** |
| `capture_window_content()` | GDI BGRA → `cv2.cvtColor(COLOR_BGRA2RGB)` | **RGB** |

`02_ocr_engine.py` 的 `_prepare_image()` 以 `COLOR_RGB2GRAY` 處理影像（以 RGB 權重加權），因此主要路徑 `capture()` 回傳的 BGR 會被視為 RGB 處理——色道權重略有偏差，但 RapidOCR 內部再轉一次灰階，實務上**不影響辨識結果**。

### _loader 的跨模組呼叫

- Core 模組之間也使用 `load_sibling()` 互相依賴（如 `04_rule_engine` 載入 `rule_serialization`、`rule_migration`）
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
