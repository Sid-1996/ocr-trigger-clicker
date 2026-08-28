# OCR Trigger Clicker — 架構文件

## 專案定位

針對 Windows 遊戲／應用程式的畫面 OCR 自動化點擊工具：定期擷取視窗畫面，透過 OCR 辨識文字，比對觸發規則後自動模擬滑鼠點擊或鍵盤按鍵。

## 技術棧速覽

| 層級 | 技術 | 用途 |
|------|------|------|
| 語言 | Python 3.13 | 主程式 |
| GUI | PyQt6 | 設定視窗、偵測日誌、除錯面板、日誌檢視器 |
| OCR | rapidocr-onnxruntime (DirectML + CPU) | 文字辨識 |
| 影像處理 | OpenCV (cv2), numpy | 截圖、縮放、二值化、差異偵測 |
| 輸入模擬（前景） | pynput | 滑鼠點擊／移動、鍵盤按鍵（SendInput） |
| 輸入模擬（後台） | Frida 注入 | hook GetCursorPos/ScreenToClient 假造座標，零閃爍後台點擊（多數 Unity 遊戲因底層限制不支援，以遊戲視窗自行測試為準） |
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
                  │               └──→  gui/run_controller
                  │               └──→  core/19_recorder        ──→  core/17_capture_pipeline
                  │               └──→  core/20_recorder_convert ──→  core/02_ocr_engine, core/11_template_matching
                  │               └──→  core/group_selection
                  │               └──→  gui/15_template_crop
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
| `core/02_ocr_engine.py` | OCR 引擎（依 i18n 語系自動選模型：`en` 且 en 模型存在時用英文，否則繁中；英文模型缺失 fallback 繁中） | `init_engine()`, `recognize()`, `find_text()`, `OcrResult` |
| `core/03_pynput_input.py` | 輸入模擬（前景 pynput SendInput） | `send_click()`, `send_key()`, `send_scroll()`, `send_drag()`, `send_hold_key()` |
| `core/04_rule_engine.py` | 規則引擎 re-export hub（委派給 6 個子模組） | `Rule`, `RuleGroup`, `Step`, `load_groups()`, `save_groups()`, `load_rules()`, `save_rules()` |
| `core/rule_models.py` | 資料模型（dataclass） | `Rule`, `RuleGroup`, `Step`, `ImportPreview` |
| `core/rule_migration.py` | 舊格式遷移 + 步驟正規化 | `_migrate_v1_to_v2()`, `migrate_v2_to_v3()`, `_normalize_step_params()` |
| `core/rule_serialization.py` | 規則/群組 JSON 序列化 | `load_rules()`, `save_rules()`, `load_groups()`, `save_groups()` |
| `core/task_management.py` | 任務檔案 CRUD ＋ `collect_templates()` 掃描全部任務（含 live 規則）的內嵌圖片 | `list_tasks()`, `load_task()`, `save_task()`, `import_task()`, `export_task()`, `collect_templates()` |
| `core/run_config.py` | 任務視窗/執行模式/擷取尺寸存取 | `get_task_window()`, `set_run_mode()`, `get_capture_size()` |
| `core/group_selection.py` | 啟動群組選擇（記憶上次勾選／skip 旗標） | `should_skip()`, `build_entry()` |
| `core/file_utils.py` | 原子檔案寫入工具 | `_replace_file()` |
| `core/_paths.py` | 路徑集中化（資料目錄／資源目錄解析） | `get_data_path()`, `get_resource_path()` |
| `core/05_main_loop.py` | 主偵測迴圈（群組兩層指標模型 + 重疊 ROI OCR 合併） | `MainLoop` class, `StepContext`, `StepResult`, `set_active_groups()` |
| `core/15_print_window.py` | 後台截圖（PrintWindow）＋權限/全黑偵測 | `capture_print_window_hwnd()`, `capture_print_window()`, `is_admin()`, `is_black_capture()` |
| `core/16_bg_input.py` | 後台互動（pynput / frida 切換，底層 PostMessage primitive 供 frida） | `set_method()`, `click()`, `send_key()`, `send_hold_key()`, `drag()`, `scroll()`, `detach()` |
| `core/18_frida_bg.py` | Frida 行程注入（後台點擊＋鍵盤；多數 Unity 遊戲因底層限制不支援，以遊戲視窗自行測試為準） | `ensure_attached()`, `click()`, `key()`, `detach()`, `last_error()` |
| `core/19_hybrid_input.py` | 混合模式輸入（後台 PrintWindow 偵測＋動作時短暫激活遊戲做 pynput 物理輸入，完成後復原使用者前景與滑鼠） | `focus_guard(title, activate_fn)` context manager |
| `core/19_recorder.py` | 滑鼠示範錄製器（全域攔截＋動作前截圖＋前景重送） | `Recorder` class（`start(title, hwnd, session_dir)` / `stop()`）、session 輸出 `recordings/session-*` |
| `core/20_recorder_convert.py` | 錄製 session → 規則轉換器（離線後處理） | `convert_sessions()`, `merge_rule_entries()`（OCR 錨點 / 模板錨點 / wait+click 三層） |
| `core/17_capture_pipeline.py` | 統一台式截圖管道（依互動模式選唯一來源，全路徑同源） | `capture_frame(mode, title, hwnd)` |
| `core/10_performance_monitor.py` | 效能監控 + 速率限制 + 點擊統計 | `PerformanceMonitor`, `get_screen_bounds()`, `is_window_foreground()`, `get_total_clicks()` |
| `core/11_template_matching.py` | 圖示模板比對 + inline 模板 LRU 解碼快取 | `match_template()`, `nms_suppress()`, `MatchResult`, `clear_template_cache()` |
| `gui/06_gui_main.py` | 主視窗（工具列、規則編輯、狀態列、系統托盤、設定對話框） | `MainWindow`, `SettingsDialog` |
| `gui/07_gui_roi.py` | 框選偵測區域（全螢幕 overlay） | `select_roi()` |
| `gui/09_ocr_debug.py` | OCR 除錯面板（即時截圖＋標註） | `OcrDebugPanel` |
| `gui/13_gui_click_picker.py` | 點擊座標選取器（全螢幕 overlay） | `pick_click_position()` |
| `gui/15_template_crop.py` | 模板修剪對話框（四邊空間化向內剪＋精確數值） | `trim_template_dialog()` |
| `gui/16_template_picker.py` | 「選擇現有圖片」對話框（跨任務重用 match_image 內嵌圖片；含目前編輯中規則） | `pick_template_dialog()` |
| `core/12_updater.py` | 自動更新薄封裝（Velopack）：feed 讀取、檢查、下載並套用 | `check_for_update()`, `download_and_apply()`, `clean_stale_temp_dirs()` |
| `core/00_logging_config.py` | 日誌設定 | `get_logger()`, `get_log_dir()`, `set_debug()`, `is_debug_enabled()` |
| `gui/12_log_viewer.py` | 日誌檢視器（tail app.log、搜尋、捲動保持、清除） | `LogViewer` |
| `core/00_global_hotkey.py` | 全域熱鍵（Win32 `RegisterHotKey`） | F8 熱鍵註冊（啟動／停止；暫停中按 F8 為繼續）＋ F9 熱鍵註冊（錄製開始/停止） |
| `gui/group_settings_controller.py` | 群組設定對話框控制器（v0.0.10 從 MainWindow 拆出） | `GroupSettingsController` |
| `gui/screenshot_controller.py` | 截圖／模板控制器（v0.0.10 從 MainWindow 拆出） | `ScreenshotController` |
| `gui/rule_config_controller.py` | 規則配置控制器（v0.0.10 從 MainWindow 拆出） | `RuleConfigController` |
| `gui/run_controller.py` | 乾執行測試控制器（v0.0.10 從 MainWindow 拆出；原名 `test_run_controller.py`，v0.4.2 改名避免誤為測試檔） | `TestRunController` |
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
| `detect` | OCR 偵測文字，未命中則觸發 on_fail | `text`, `roi`, `match_mode`, `fuzzy_threshold`, `on_fail`（stop/key/skip/jump/advance/notify + fail_duration_sec） |
| `match_image` | 圖示模板比對，未命中則觸發 on_fail | `template`, `roi`, `threshold`, `match_color`, `color_tolerance`, `on_fail`（stop/key/skip/jump/advance/notify + fail_duration_sec） |
| `click` | 滑鼠點擊（設 `ctx.triggered = True`） | `target`（`text_center`/`custom`/`cursor`）、`x`, `y`, `button`, `random_offset`, `hold_ms`, `after_delay_ms` |
| `key` | 鍵盤按鍵（設 `ctx.triggered = True`） | `key`（pynput 格式）、`hold_ms`, `after_delay_ms` |
| `wait` | 固定等待 | `ms` |
| `jump` | 跳轉至另一規則（限同群組） | `rule_id` |
| `compare` | ROI 內數值比對 | `pattern`, `operator`, `value`, `on_fail`（stop/key/skip/jump/advance/notify + fail_duration_sec） |
| `notify` | 右下角疊加通知提示（經 `on_warning` → GUI `_NotificationStack` 顯示；回 `continue`，不設 `ctx.triggered`，不影響規則流程） | `message` |
| `scroll` | 滑鼠滾輪（設 `ctx.triggered = True） | `direction`, `amount`, `delay_ms`, `after_delay_ms` |
| `drag` | 滑鼠拖曳（設 `ctx.triggered = True） | `target`, `dx`, `dy`, `button`, `after_delay_ms` |

**動作後延遲 `after_delay_ms`（毫秒，預設 0）**：動作步驟（click/key/drag/scroll）成功送出後，固定等待指定毫秒才執行下一步驟。實作於 `_run_rule`（core/05_main_loop.py 單一 choke point）——動作步驟回 `continue` 且 `ms>0` 時用 `_stop_event.wait(ms/1000)` 中斷式等待（暫停/停止立即中止、回 stop interrupted），尾隨步驟不執行。等價社群慣用「動作後 sleep」，可取代 `[動作, wait]` 成對步驟；0 = 不等待。語意與 scroll 的 `delay_ms` 不同（後者是滾輪格間延遲）。不影響 `fail_duration_sec` 容忍邏輯。

### on_fail fail_duration_sec

`on_fail` 支援選擇性欄位 `fail_duration_sec`（float，秒）：

- 設為 0（預設）：on_fail 立即生效
- 設為 >0：首次觸發 on_fail 時不立即執行動作，而是等待指定秒數後再次檢查 → 若仍未命中才執行動作
- 用途：避免短暫的畫面閃爍或遮擋導致誤判，可用於「等待文字持續消失 N 秒後再執行」的情境
- 支援：`detect`、`match_image`、`compare` 的 on_fail

**實測語意補充（依 StarSavior 任務驗證）：**

- **微值（0.1~0.5s）**＝「本幀先 return stop、下一個掃描週期才執行動作」——把動作延後一幀，避免畫面轉場/閃爍的同幀誤觸。實際解析度受 `scan_interval` 限制：`fd < interval` 時效果等於「延後一幀」，並非精確計時。
- **fd ≥ interval** 才是真正的多幀寬容窗：期間若條件恢復，`_handle_detect`/`_handle_match_image`/`_handle_compare` 命中時會 `pop` 該 key **取消容忍**；期滿才執行真正動作。
- 容忍期計時以 `(rule_id, step_idx)` 為 key（`_fail_since`），各步驟獨立；`reload_rules()` 與動作成功會清除。
- **「stop 動作配 fd」這個組合沒有任何真實任務使用**：容忍期滿後 pop key→下幀重新進新容忍期→每 fd 秒重複 stop、永不推進。任務一律用 `advance`/`notify`/`key` 搭配 fd（三者觸發後都會移轉狀態，不重複）。

### on_fail 動作語意——真實任務設計意圖

on_fail 只存在於感官型步驟（`detect`/`match_image`/`compare`）；動作步驟（click/key…）失敗不回傳 on_fail，直接中止本幀。各動作語意與真實使用分布（StarSavior 每日任務/跑馬輔助驗證）：

| 動作 | 語意 | 真實使用情境 | 使用量 |
|---|---|---|---|
| `stop`（預設） | 本幀中止、指標不動、下幀從步驟 0 重試 = **無限輪詢等待** | 偵測閘：所有「等待畫面出現再動作」的規則；跑馬每個事件規則的 step0 | 每日 ×63、跑馬 ×65 |
| `advance` | 容忍期滿後設 `force_advance`，由 `_process_rules` 推進到下一規則 = **有界輪詢、跳過本規則** | once 群組的「可選 UI 前置步驟」：好友/禮包/PVP/信件群組的導航檢查、可選段落 | 每日 ×12（fd 0.1~2.0s），跑馬 0 |
| `notify` | 容忍期滿後顯示訊息，並把 `stop_groups` 移出 active = **有界輪詢、硬踢整條群組鏈** | 「沒有找到[帕萊斯立方]任務特徵」「沒有信件可領取」；`stop_groups` 一次帶 2~3 個相關群組；`message` 空白走 i18n 預設模板 | 每日 ×16，跑馬 0 |
| `key` | 容忍期滿後按 fallback 鍵、設 `triggered=True` 視同觸發 = **次要條件失敗的回退動作** | 跑馬邏輯判定規則（BEST/工坊/排球/兔子/救命恩人）、每日「確認/一鍵領取(2)」按 Escape | 每日 ×2、跑馬 ×7 |
| `skip`（跳至步驟） | `jump_step` 跳至本規則內指定步驟（0-based、僅限向前） | **目前無任何真實任務使用**，刻意保留 | 0 |
| `jump`（跳至規則） | 改 `_rule_in_group_ptr` 跳至同群組規則 | **目前無任何真實任務使用**，刻意保留（背景規則的 `on_fail.jump` 不受 `jump` 步驟限制） | 0 |

**三階分工是核心設計**：stop＝無界等待；advance＝有界放棄本規則；notify＝有界放棄整條群組鏈。UI 文案「跳過本次 / 跳過此規則 / 通知並停止群組」與此對應。

**群組模式適用性：**

| on_fail 動作 | once/sequential | loop/sequential | loop/parallel | 背景規則 |
|---|---|---|---|---|
| `stop` | ✅ | ✅ | ✅ | ✅ |
| `advance` | ✅ 推進指標 | ✅ 每輪一次嘗試 | ⚠️ **無效**（parallel 只檢查 `triggered`） | ⚠️ 無效（結果捨棄） |
| `notify` | ✅ 移除群組 | ✅ 移除群組 | ⚠️ **永久移除該群組**，可能連帶整場停止 | ✅ 僅發訊息，無群組可停 |
| `key` | ✅ | ✅ | ✅ | ✅ |

**實務原則**：跑馬（loop/parallel）刻意只用 `stop`+`key`，不碰 `advance`/`notify`；每日（once/sequential）才用 `advance`/`notify`。設定新任務時沿用此分工，避免在 parallel 群組用 advance/notify。

### on_fail notify 流程

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
                     │  │ compare     │  │    未命中 → on_fail（stop/key/skip/jump/advance/notify）
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
| **客戶區比例** (client-ratio) | 統一前景 selector（`07_gui_roi`/`13_gui_click_picker`/`14_capture_region`）、`roi_coord:"client"` 標記 | 0~1 比值，基準為客戶區（不含標題列/邊框） |
| **視窗比例** (window-ratio) | 舊任務無 `roi_coord` 標記（向下相容） | 0~1 比值，與視窗解析度無關 |
| **影像像素** (image pixel) | numpy array `[h, w, 3]` | 截圖陣列索引 |

### 轉換發生點

```
來源                        原始座標          轉換方式                               最終
──────────────────────────────────────────────────────────────────────────────────
OCR 辨識                     視窗相對          × 暫不轉換，保留像素值                  視窗相對
debug panel 建立規則         視窗相對          ÷ client_size → 比例座標                 客戶區比例
框選偵測區域 (gui_roi)       螢幕絕對          (螢幕 - win_rect - chrome) ÷ client_size → 比例  客戶區比例
選取點擊座標 (click_picker)  螢幕絕對          (螢幕 - win_rect - chrome) ÷ client_size → 比例  客戶區比例
模板擷取 (capture_region)    螢幕絕對          (螢幕 - win_rect - chrome) ÷ client_size → 比例  客戶區比例
主循環 _resolve_roi()        比例＋`roi_coord`  依標記 × client_size+chrome 或 × 圖寬高     影像像素
主循環 _resolve_point()      比例＋`roi_coord`  依標記 × client_size+chrome 或 × 圖寬高     螢幕絕對（送 pynput / Frida）
```

### 比例轉換實作

`05_main_loop.py` 的 `_resolve_roi()` 與 `_resolve_point()` 負責將比例座標還原為像素：

- `_resolve_roi(roi_dict, img_width, img_height)` → `(x, y, w, h)` 像素整數，用於影像裁切
- `_resolve_point(point_dict, win_width, win_height)` → `(x, y)` 像素整數，加上視窗偏移後送 `send_click()`

## 輸入模擬（前景 pynput / 後台 Frida / 混合 hybrid）

互動方法由 `interaction_mode` 決定（`pynput` / `frida` / `hybrid`），`MainLoop._send_click` / `_send_key` / `_send_drag` / `_send_scroll` 依模式分派到對應輸入模組。分派規則：截圖／黑幕類分支用 `mode != "pynput"`，輸入分派與工具前景保護用 `mode == "frida"`（hybrid 輸入走前景物理路徑）。後台一律走 `core/16_bg_input.py`，由該模組再委派到 frida。後台 PostMessage 模式已移除。

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

### 後台 Frida：注入假造輸入

`core/18_frida_bg.py` 以 Frida 注入遊戲行程，hook `GetCursorPos` / `ScreenToClient` 假造游標座標，讓透過此方式驗證輸入的遊戲通過檢查後再 `PostMessage` 點擊——**游標不動、焦點不搶、零閃爍**。鍵盤採同架構：hook `GetKeyState` / `GetAsyncKeyState` / `GetKeyboardState` 假造按鍵狀態（僅覆寫注入中的 vk，其餘 pass-through），再 `PostMessage` 送 `WM_KEYDOWN/UP`，讓此類遊戲無論走訊息佇列或 state-polling 都收得到。`core/16_bg_input.py` 的 `set_method("frida")` 後，`click`/`send_key`/`send_hold_key` 委派到此模組；滾輪/拖曳 v1 回退 PostMessage primitive（多數遊戲下可能無效）。

- `ensure_attached(hwnd)`：懶載入，依 pid 自動重 attach（遊戲重開可自癒）；session 死亡（`is_detached`）會自動重注入
- `click(hwnd, x, y, button, hold_ms)`：rpc.exports.update 假座標 → PostMessage DOWN/UP；呼叫失敗自動 detach + re-attach 重試一次
- `key(hwnd, vk, down)`：rpc.exports.key 假按鍵狀態 → PostMessage WM_KEYDOWN/UP；同樣帶 re-attach 重試
- spoof 為暫時性：游標 update 後約 400ms 自動還原（pass-through 真實游標）；按鍵 down 後約 10s 寬限自動清除（up 未送達的保險），up 送達即時還原
- `detach()`：`MainLoop.stop()` 時釋放，還原遊戲
- v1 限制：滾輪/拖曳僅 PostMessage（多數遊戲下可能無效）；多數 Unity 遊戲因底層限制（GPU 渲染不公開 PrintWindow 路徑、輸入走自家低階系統）不支援後台操控，需以遊戲視窗自行測試為準；遊戲若要求視窗聚焦（`Application.isFocused`）仍無效；EAC/BattlEye 等防作弊會封鎖 Frida（有防作弊偵測風險）

### 混合：hybrid（後台偵測＋前景物理輸入）

`core/19_hybrid_input.py` 提供 `focus_guard(title, activate_fn)` context manager：進入時記錄使用者前景視窗 hwnd 與游標位置 → 激活目標遊戲視窗 → 動作以 pynput 物理輸入送出（走前景路徑）→ 離開時復原使用者原本的前景視窗與滑鼠位置。截圖／辨識仍走後台 PrintWindow（零干擾），只有動作瞬間短暫搶焦點。典型場景：遊戲僅支援前景操控（多數 Unity 遊戲）且正在自動戰鬥爬主線，只有過關時需手動點「下一關」——寫好規則後去做別的事，偵測到「下一關」時工具自動切回前景點擊並復原使用者狀態。適合低頻動作任務；高頻動作下頻繁搶焦點反而干擾，應用一般前景模式。主循環側（`05_main_loop.py`）：hybrid 的輸入走前景物理路徑，`_is_tool_foreground` 前景保護對 hybrid 放行（與 frida 同），動作前經 `focus_guard` 確保目標在前景。

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
| `uv run python gui/06_gui_main.py`（開發模式） | `%APPDATA%\ocr-trigger-clicker\` |
| 打包 EXE（PyInstaller） | `%APPDATA%\ocr-trigger-clicker\` |

兩種模式皆同，因為 `core._paths.get_data_path()` 在任何模式皆可 import。可透過環境變數 `OCR_TRIGGER_DATA` 覆蓋基底路徑。

任務檔案：`<基底>/tasks/<任務名稱>.json`（如 `%APPDATA%\ocr-trigger-clicker\tasks\每日任務.json`）。

錄製 session 目錄：`<基底>/recordings/session-YYYYMMDD-HHMMSS/`（`events.json` + `frames/*.jpg`），轉換成任務後由 GUI 清除。

### 匯入／匯出

匯入與匯出的對話框起始目錄：

| 執行模式 | 起始目錄 |
|----------|----------|
| `uv run python gui/06_gui_main.py` | 專案根目錄（`_here` = `Path(__file__).resolve().parent.parent`） |
| 打包 EXE | PyInstaller 暫存目錄（`sys._MEIPASS`），通常為 `%TEMP%\_MEIxxxxx` |

使用者可透過對話框自由選擇任意路徑，起始目錄僅為開啟對話框時的預設位置。

### 全域設定 config.json

路徑：`<data_base>/config.json`（資料庫基底同任務目錄，已移出版本控制，屬使用者設定）

> **欄位唯一事實來源**：`gui/rule_config_controller.py` 的 `DEFAULTS`。此處僅列出使用者常用欄位，完整清單與預設值以程式碼為準。

| Key | 預設值 | 用途 |
|-----|--------|------|
| `interaction_mode` | `"pynput"` | 互動方法：`"pynput"`（前景 SendInput）／`"frida"`（後台 Frida 注入；多數 Unity 遊戲因底層限制不支援，以遊戲視窗自行測試為準） |
| `close_behavior` | `"tray"` | 關閉按鈕行為：`"tray"`（縮小至托盤）／`"quit"`（直接關閉） |
| `max_cps` | `5` | 全域速率限制（每秒點擊上限） |
| `scan_interval_ms` | `500` | 主循環掃描間隔 |
| `language` | `"zh_TW"` | 介面語言（`zh_TW`／`en`） |

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
| 全域速率限制 (CPS) | `10_performance_monitor.py` | 限制每秒點擊上限（`max_cps` 可調，預設 5），違規 3 次自動暫停偵測 |
| 前景保護 (目標視窗) | `05_main_loop.py` | 僅在目標視窗為前景時才執行點擊，非前景時靜默等待 |
| 前景保護 (工具視窗) | `05_main_loop.py` | 工具自身視窗在前景時自動暫停 click/key/drag/scroll，防止誤搶焦點（後台模式直接回傳 False，不誤擋） |
| 後台全黑偵測 | `15_print_window.py` `is_black_capture()` | 後台截圖全像素為零才命中（暗色遊戲不誤判）；搭配 `is_admin()` 提醒以系統管理員重啟 |
| OCR 連續失敗重啟 | `02_ocr_engine.py` | 連續 5 次失敗 → 重建引擎實例 |
| 視窗消失自動暫停 | `05_main_loop.py` | `get_window_rect()` 回傳 None → 暫停循環，每 5 秒檢查視窗是否重現 |
| 座標驗證 | `03_pynput_input.py` `_validate_coords()` | 使用 `GetSystemMetrics(VIRTUALSCREEN)` 確保點擊不超出多螢幕範圍 |
| 關閉行為設定 | `06_gui_main.py` `SettingsDialog` | 可選「縮小至托盤」或「直接關閉」，關閉前可跳出確認對話框 |

## 自動更新（Velopack）

v0.4.0 起自動更新由 [Velopack](https://velopack.io) 框架接管，自製 updater.exe／manifest-delta 協定已拆除。

**架構**：

- 安裝形態：使用者跑 Setup.exe → 安裝至 `%LocalAppData%\OCRTriggerClicker\current\`；
  框架的 `Update.exe` 位於安裝根目錄（**在 app 目錄之外**，換目錄時不會鎖住自己——
  舊自製 updater「抓著要改名的資料夾」的死穴從架構上不存在）
- feed：GitHub Releases 的 `releases.win.json`；位址由 `build.py --feed prod|test`
  烘入 `_update_feed.py`，打包後防呆驗證（防止拿錯包上架）
- delta：`release.ps1` 先 `vpk download github` 取回前版，`vpk pack` 自動產生
  delta nupkg（實測 0.4.0→0.4.1 約 0.55 MB vs 整包 194 MB）；框架下載失敗自動退回 full

**用戶端流程**：

```
main() 最頂端（任何 UI 之前）
  └─ velopack App().set_auto_apply_on_startup(True).run()   # 安裝/更新 hooks

core/12_updater.py
  check_for_update()      # GithubSource(FEED_REPO_URL) → UpdateInfo(version, notes)
  download_and_apply()    # get_update_pending_restart() → 直接套用；
                          # 否則 check_for_updates() → download_updates() → apply_updates_and_restart()
gui/06_gui_main.py        # 啟動背景檢查 + tray/按鈕手動檢查 → 對話框 → 套用後 quit+_exit 讓位
```

**單一實例防護**：`CreateMutexW("Local\\OCRTriggerClicker.SingleInstance")`，第二份啟動即提示退出。
雙開曾鎖死安裝目錄導致舊 updater rename 必敗（v0.3.1 兩度撤回的根因）；relaunch 內建化後新程序以
`--wait-exit-pid=N` 等舊程序退出才初始化，與 mutex 不互撞。

**歷史相容**：`latest_version.txt` 凍結於 0.3.0——v0.3.x 舊客戶端讀它永遠顯示「暫無更新」（斷糧設計），
升級到安裝版需手動下載 Setup.exe 一次；使用者任務／設定存於 %APPDATA%，跨形態沿用。

## 日誌架構（三通道）

`MainLoop` 有三種日誌通道，用途不同，**不可混用**：

| 通道 | 方法 | 寫入目標 | GUI 可見？ | 適用場景 |
|------|------|----------|-----------|----------|
| 檔案日誌 | `self._log()` | Python `logging` → `app.log` | ✅ 日誌檢視器（LogViewer） | debug 記錄、非 GUI 訊息 |
| 執行日誌 | `self._log_exec()` | `self._execution_log` (deque) **+ 同時寫入 `app.log`**（`[exec]` 行） | ✅ 執行日誌面板 + 日誌檢視器 | 步驟成功/失敗/跳轉等結果 |
| 通知彈窗 | `self.on_warning()` | Qt signal → 系統托盤通知 | ✅ 通知彈窗 | 需要使用者注意的警告 |

- `app.log` 路徑：`%APPDATA%\ocr-trigger-clicker\logs\app.log`，`core/00_logging_config.py` 統一管理（midnight 輪替，backupCount=1）
- `set_debug(enabled)` / `is_debug_enabled()`：DEBUG 層級切換，供開發者以 `--debug` 啟動旗標（`06_gui_main.py` `__main__`）取回規則存讀/GUI 編輯等內部診斷；一般使用者預設 root=INFO，主循環診斷與 `[exec]` 執行記錄皆為 INFO 可完整看到
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

## 自動化測試（tests/）

`tests/` 以 pytest 涵蓋核心邏輯，`pyproject.toml` 設定 `addopts = "--cov"`。執行方式：

```powershell
uv run python -m pytest --no-cov -q    # 冒煙（不產覆蓋報告）
uv run python -m pytest                # 含覆蓋報告
```

### 檔案地圖

| 檔案 | 涵蓋範圍 |
|------|----------|
| `test_main_loop.py` | 主迴圈：步驟分派、群組兩層指標、on_fail 各動作、fail_duration_sec、ROI/座標解析、OCR 快取標記、動作日誌 rate-limit |
| `test_rule_engine.py` | 舊格式遷移 V1→V2→V3、規則/群組序列化、on_fail 正規化 |
| `test_rule_serialization.py` | 序列化 round-trip、corrupt 檔、預設值、舊欄位相容 |
| `test_task_management.py` | 任務 CRUD、匯入匯出、UUID 重映射、無效輸入過濾 |
| `test_template_matching.py` | match_template、NMS、多尺度、色彩容差、跨解析度 |
| `test_i18n.py` | 程式碼用到的 `T("key")` 必須存在於所有語言檔 |
| `test_recorder_convert.py` | 錄製 session → 規則轉換（OCR 錨點 / 模板錨點 / wait+click 三層、座標比例、群組結構） |
| `test_ocr_merge.py` | OCR 合併快取 vs 逐 ROI 等價（需本機 RapidOCR model，無則 skip） |
| `test_prematch_equiv.py` | 並行 prematch vs 循序等價 |
| `test_template_cache.py` | 模板解碼 LRU 快取等價/命中/清除 |

### 共用與 fixture 資料

- `tests/conftest.py`：`tmp_tasks_dir` fixture（把任務目錄指向暫存），與 `make_main_loop()`——以 `__new__` 建立不觸發 `__init__` 的 MainLoop 測試實例，`test_main_loop` / `test_prematch_equiv` 共用；`MainLoop.__init__` 新增屬性時必須同步。
- `tests/data/test*.png`：實境遊戲幀（1920×1080），作 OCR／模板比對的回歸基準。
- `tests/data/fixture_task.json`：**快照**自 `docs/tasks/StarSavior-跑馬輔助.json`。整合測試吃這份固定快照、不讀活任務——任務內容更新不會弄紅測試；需同步新任務時重新複製覆寫即可。

### 注意

- 整合測試（`test_ocr_merge` / `test_prematch_equiv` / `test_template_cache`）需本機 `custom_models/chinese_cht_rec_mobile.onnx` 才真正執行，無 model 環境自動 skip。
- 後台模式（`16_bg_input` / `15_print_window` / `17_capture_pipeline`）、`box_utils`、GUI 層依賴 Win32 畫面，僅以 `__main__` self-check 涵蓋；updater 的純邏輯另有 pytest（delta 函式＋資產探測＝`test_updater_delta.py`、備份策略＋PID 逾時＝`test_updater_process.py`）。

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
