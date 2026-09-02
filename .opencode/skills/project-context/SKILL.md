---
name: project-context
description: ocr-trigger-clicker 專案的架構知識、已知陷阱與子系統摘要。涉及 ROI 座標系統、OCR vs 模板比對、規則執行引擎（StepContext、on_fail、fail_duration_sec）、dxcam 截圖備援、box_utils 座標工具、執行日誌面板、效能警告、GUI 規則樹拖曳排序、任務檔案格式、i18n 多語言、自動更新、路徑集中化設計。
---

# ocr-trigger-clicker 架構與陷阱筆記

> 基準版本：git commit `4c1844b` (2026-08-03, after v0.1.9 / Unreleased)
> 本文件內容已逐項對照實際原始碼驗證（見文末驗證記錄），可信度高。
> 行號參照可能因持續開發而偏移，建議以 `rg` 確認為準。

## 目錄結構

模組地圖與各模組職責詳見 `docs/dev/ARCHITECTURE.md`，此處僅列關鍵檔案與本 skill 關注的細節。

### core/

| 檔案 | 一行摘要 | 本 skill 關鍵細節 |
|---|---|---|
| `00_global_hotkey.py` | 全域熱鍵 F8/F9 | hid=1：開始/暫停/停止；hid=2：錄製開始/停止 |
| `00_logging_config.py` | 日誌初始化 | rotation、等級、格式 |
| `01_screenshot.py` | 視窗截圖 | mss → mss/DXGI 雙層備援，GDI 備援僅客戶區；統一管線見 `17_capture_pipeline` |
| `02_ocr_engine.py` | OCR 引擎 | `_DEFAULT_MAX_SIDE_LEN = 480`，但主循環繞過此預設 |
| `03_pynput_input.py` | 輸入模擬 | pynput SendInput，**取代已刪除的 AHK**（`03_ahk_socket.py` 不存在） |
| `04_rule_engine.py` | 規則引擎 hub | re-export + 16 個 self-check |
| `05_main_loop.py` | 主偵測迴圈 | 2224 行，整個應用的心臟（見規則執行引擎） |
| `10_performance_monitor.py` | 效能監控 | FPS/CPU/記憶體、速率限制、`get_total_clicks()` |
| `11_template_matching.py` | 模板比對 | OpenCV matchTemplate + NMS |
| `12_updater.py` | 自動更新 | Velopack 薄封裝：feed 讀取（烘入制）、檢查、下載並套用 |
| `15_print_window.py` | PrintWindow 截圖（後台） | `capture_print_window` / `is_admin` / `is_black_capture` |
| `16_bg_input.py` | 後台輸入 | pynput / frida 雙模。frida 支援點擊＋鍵盤（`18_frida_bg.py` 假造游標/鍵盤狀態 + PostMessage）；滾輪/拖曳回退 PostMessage primitive（Unity 下可能無效） |
| `17_capture_pipeline.py` | 統一截圖管線 | `capture_frame()` 前景 mss / 後台 PrintWindow 單一入口 |
| `19_recorder.py` | 滑鼠示範錄製器 | 全域攔截＋動作前截圖＋前景重送，session 輸出到 `recordings/` |
| `20_recorder_convert.py` | 錄製 session → 規則轉換 | 離線後處理，三層錨點（OCR/模板/計時） |
| `box_utils.py` | 座標工具集 | 10 純函式 + 17 self-check（見 box_utils 小節） |
| `rule_models.py` | 資料模型 | `Rule`、`Step`、`RuleGroup`、`ImportPreview` |
| `rule_migration.py` | 舊格式遷移 | v1→v2/v2→v3 + `_STEP_DEFAULTS` |
| `rule_serialization.py` | JSON 序列化 | `load_rules`/`save_rules`/`load_groups`/`save_groups` |
| `task_management.py` | 任務 CRUD | `list_tasks`/`load_task`/`save_task`/`import_task`/`export_task` |
| `run_config.py` | 執行配置 | 視窗標題、執行模式、擷取尺寸 |
| `file_utils.py` | 原子寫入 | `_replace_file()` |
| `_paths.py` | 路徑集中 | `get_data_path`/`get_resource_path`/`_appdata_path` |

### gui/

| 檔案 | 一行摘要 | 本 skill 關鍵細節 |
|---|---|---|
| `06_gui_main.py` | 主視窗 | 6006 行，含 `_ExecutionLogWidget`、`_StopGroupsPicker`、`_open_log_viewer` |
| `07_gui_roi.py` | ROI 框選 | 前景全螢幕 overlay |
| `09_ocr_debug.py` | OCR 除錯 | 即時辨識結果、全黑偵測 |
| `12_log_viewer.py` | LogViewer 日誌檢視器 | `LogViewer(QDialog)` 獨立視窗顯示 `app.log` |
| `13_gui_click_picker.py` | 點擊座標選取 | 前景螢幕絕對 → 比例座標 |
| `14_capture_region.py` | 模板擷取 | base64 編碼、capture_size |
| `15_template_crop.py` | 內嵌模板修剪 | `trim_template_dialog()` 四邊空間化雙向箭頭按鈕（貼圖四側，上/下橫排、左/右直排）＋底部數值行；核心邏輯 `core/11_template_matching.py` `crop_template_b64` + `clamp_margins`（交叉限制，`MIN_TEMPLATE_SIDE=4`） |
| `group_settings_controller.py` | 群組設定 | 對話框邏輯 |
| `rule_config_controller.py` | 規則設定 | 對話框邏輯 |
| `screenshot_controller.py` | 截圖設定 | 對話框邏輯 |
| `test_run_controller.py` | 測試執行 | 乾執行模擬 |

### 根目錄

| 檔案 | 一行摘要 |
|---|---|
| `_loader.py` | 動態載入數字開頭模組，RLock 快取 |
| `_version.py` | 版本號單一事實來源 |
| `build.py` | PyInstaller 打包 + updater.exe 構建 |
| `updater_main.py` | 獨立更新/重啟程序 |

另有 `i18n/`（多語言，701 keys × 2 語言）與 `tests/`（pytest 單元測試）。

任務檔案實際路徑：`%APPDATA%\ocr-trigger-clicker\tasks\`（不在專案目錄內）。

## 核心原則

**OCR 與模板比對對座標誤差的容忍度不同。** OCR 是語意比對，位置有小幅偏移仍能辨識成功；模板比對是像素級比對，座標只要偏移幾個 pixel 就會比對失敗。診斷「比對失敗但 OCR 正常」類問題時，先往座標精度方向查。

**`roi_coord: "client"` 機制。** ROI 比例預設以全視窗尺寸為基準儲存。若 `roi` 字典含 `"roi_coord": "client"`，代表比例是相對於客戶區（不含標題列/邊框）。還原時（`_resolve_roi()`）需呼叫 `get_window_client_offset()` 取得邊框偏移量，再轉換為含邊框的全視窗像素座標 —— 因為 `capture()` 截圖本身含邊框。忽略此標記會導致裁切區域系統性偏移。舊任務（無此標記）視為以全視窗比例儲存，向下相容。此機制在基準版本前已修補了多處遺漏（`_CompareStepForm`、OCR 診斷面板、舊檔載入路徑），commits：`2cc7db6`、`db094f4`、`2502b52`、`ff2ffb0`。

**後台座標**：後台模式下的 ROI/點擊比例是相對於客戶區影像像素。`_resolve_roi()`（`05_main_loop.py:380`）和 `_resolve_point()`（`05_main_loop.py:408`）讀取 `roi_coord` 標記，若為 `"client"` 即用 `client_offset` 轉換。**ROI/點擊/模板選取統一走前景 selector**（`07_gui_roi`、`13_gui_click_picker`、`14_capture_region`，螢幕絕對 → 客戶區比例，`screenshot_controller.open_roi_selector` / `_capture_rect_to_roi` 與 `06_gui_main._on_pick_coord` 統一收斂），後台模式設定時也會把目標視窗前景化，不再有後台 PrintWindow 選取 UI（`17_bg_roi_selector.py`、`18_bg_click_picker.py` 均已刪）。已實測前景(mss)模板與後台執行截圖（PrintWindow）比對一致（BrownDust II 前景→後台比對信心全數 1.0），故後台模板不再需要 PrintWindow 框選。`template_source` 僅為寫入 metadata（後台建模板時標 `"background"`），比對時不再檢查一致性（commit `a075576` 移除跨模式防呆），後台執行一律對 PrintWindow 畫面比對。

## 截圖備援鏈

`17_capture_pipeline.py` `capture_frame(mode, title, hwnd)` 是**全應用唯一的截圖入口**（commit `cc0bcf1`），依 `interaction_mode`（config.json 中 `"pynput"`=前景 / 其他=後台）選擇路徑：

**前景**（`_capture_foreground`，`17_capture_pipeline.py:31`）：
1. **mss** — 跨平台截圖，含邊框（`_capture_mss`）
2. **DXGI mss** — mss 改用 DXGI backend（`__mss_get_backend` runtime monkey-patch）
3. 若 1+2 皆失敗 → 呼叫 `capture_window_content()` 作為最後 GDI 備援（PrintWindow → BitBlt），只取客戶區，會自動填補黑邊到全視窗大小

**後台**（`_capture_background`，`17_capture_pipeline.py:41`）：
- `capture_print_window()`（`15_print_window.py`）：GDI PrintWindow 直接取客戶區，全黑時 `is_black_capture()` 偵測 + 非管理員時精準提示（如鳴潮遊戲）

所有主循環 `_process_rules` 與 match_image 建立模板的截圖統一走 `capture_frame()`，確保模板與實際比對畫面來源一致。

**關鍵陷阱**：後台 PrintWindow 全黑 ≠ 不可用——`is_black_capture()`（`15_print_window.py:25`，全像素為 0 才命中，真實畫面再暗也有非零像素）會先檢查是否為系統管理員，非管理員時提示權限不足（commit `4281972`、`e43b97c`）。

## box_utils 座標工具

`core/box_utils.py` — 10 個純函式，被 `05_main_loop.py` 和 GUI 端的 ROI/點擊選取器使用：

| 函式 | 用途 |
|---|---|
| `roi_center(roi)` | 取得 ROI 中心點 |
| `roi_to_pixels(roi, w, h)` | 比例座標 → 像素 |
| `roi_to_ratio(roi, w, h)` | 像素 → 比例座標 |
| `roi_crop(roi, img)` | 從影像裁切 ROI 區域 |
| `roi_scale(roi, factor)` | 縮放 ROI |
| `roi_intersection(a, b)` | 兩 ROI 交集 |
| `roi_bounding(boxes)` | 多框最小包圍矩形 |
| `roi_sanitize(roi)` | 修正無效 ROI（負值、超出邊界等） |
| `box_to_rect(box)` | 模板比對結果 → GUI rect |
| `point_to_pixels(px, py, w, h)` | 比例點 → 像素點 |

含 17 項 self-check 測試（`if __name__ == "__main__"`）。

## max_side_len 與全圖 OCR

`02_ocr_engine.py` 定義 `_DEFAULT_MAX_SIDE_LEN = 480`，`recognize()` 預設使用此值將大圖縮小後再辨識。

**但主循環完全繞過此預設**：`_ocr_region()`（`05_main_loop.py:342-413`）所有 `recognize()` 呼叫皆直接傳 `max_side_len=0`（無縮限）。ROI 分支裁切後的子圖也傳 0。

歷史：曾短暫實作全圖 `max_side_len=480`→`720` 限制（commits `c98b883`、`a4460a4`），後因偵測精度考量全數移除（commit `9ca2998`）。

**效能警告**：空 ROI + 畫面寬度 > 800px 時，`_handle_detect` 會發出警告並透過 `on_warning` 通知 GUI（`05_main_loop.py:470-478`）。

## on_warning 回呼機制

`MainLoop.on_warning: Optional[Callable[[str], None]]`（`05_main_loop.py:195`）

觸發時機：
- 空 ROI + 畫面寬 > 800px（`05_main_loop.py:480-481`）
- match_image 首次匹配成功（`05_main_loop.py:526`）
- compare 步驟全圖 OCR（`05_main_loop.py:564`）
- 流程停止（`05_main_loop.py:674`，含 `[通知]` 前綴）
- 規則異常（`05_main_loop.py:1116`, `1074`, `1140`）
- 全黑截圖警告（`05_main_loop.py:1254`，log 而非 on_warning）
- 背景截圖失敗（`15_print_window.py:149`）

GUI 連接：`loop.on_warning = lambda msg: self._signals.warning_signal.emit(msg)`（`gui/06_gui_main.py:2669`）

## 執行日誌面板

`_ExecutionLogWidget`（`gui/06_gui_main.py:2993`）— 即時顯示規則逐步驟執行紀錄。

**資料來源**：`MainLoop._log_exec()`（`05_main_loop.py:224-276`），每步執行結果寫入 `_execution_log` 佇列，GUI 定時拉取。

**兩層抑制**（避免 flood）：
1. **同 key 去重**：`_last_exec_log` 字典，相同 `(rule_name, step_idx)` 若 result+detail 不變則跳過
2. **completed 節流**：同一 rule_name 的 completed 訊息 1 秒內只顯示一次

GUI 端也有自己的 suppression（commit `bc2ff06`：用 `step.type + rule.id + scroll 4 方向` 去重）。

**人類可讀摘要**：`_infer_stop_detail()`（`05_main_loop.py:974`）產生 stop 原因，`_build_ok_detail()`（`05_main_loop.py:995`）產生 ok 摘要（含 match_image 百分比、scroll/drag 方向等）。

### 日誌架構（基準版本後新增）

**LogViewer 日誌檢視器**（`gui/12_log_viewer.py:30` `LogViewer(QDialog)`）：
- 開啟方式：工具列 Ctrl+L 或 `_open_log_viewer()`（`gui/06_gui_main.py:5645`），獨立 QDialog 視窗
- 即時 tail `app.log`、文字搜尋（層級過濾與「啟用詳細日誌」checkbox 已移除，主循環診斷全為 INFO 直接可見）
- 內容未變更時不強制捲動，使用者向上瀏覽不會被自動拉回底部（commit `27b9dfa`）
- 關閉時停止刷新（commit `d640509`），重開經 `showEvent` 重新啟動 timer（commit `a21283d` 後）

**`[exec]` 寫入 app.log**（commit `17d4735`、`249d2cf`）：觸發射紀錄已移除 `triggers.jsonl`，改為結構化 `[exec]` 行寫入 `app.log`（INFO 層級）。`_log_exec()` 每次執行紀錄也寫入 app.log，deque maxlen=10。

**生命週期日誌**（commit `249d2cf`）：`log_main()` GUI 寫入提升為 INFO；`set_debug()`/`is_debug_enabled()` 於 `core/00_logging_config.py`，僅供開發者 `--debug` 啟動旗標使用（`gui/06_gui_main.py` `__main__`）；`cleanup_stale_logs()` 清理過期日誌（含 `triggers.jsonl*` glob）。

**異常 traceback**（commit `20b9cf1`）：背景規則/規則/並行/主循環 4 處改為 `self._logger.exception()`，會自動附上完整 traceback。

**循環停止統計**（commit `20b9cf1`）：`MainLoop._started_at` 記錄啟動時間戳，`PerformanceMonitor._total_clicks` + `get_total_clicks()` 累計點擊數。`stop()`（`05_main_loop.py:1308-1321`）輸出 `"循環停止：執行 {秒數} 秒，點擊 {次數} 次，規則 {數量} 條"`。

## 後台操控模式（基準版本後新增）

`interaction_mode` 存放於 `config.json`，由 `_get_interaction_mode()`（`gui/06_gui_main.py:85-95`）讀取，預設 `"pynput"`（前景）。非 `"pynput"` 即後台模式。OCR 診斷面板（`gui/09_ocr_debug.py:43-55`）也有獨立複本。

### 截圖

**單一管道**：`17_capture_pipeline.capture_frame()` — 前景走 mss 三層備援、後台走 PrintWindow。全路徑同源，確保模板建立與比對畫面一致。

### 輸入

`16_bg_input.py` — 雙模切換：前景用 pynput SendInput，後台用 frida 注入（`18_frida_bg.py`）。`click`/`send_key`/`scroll`/`drag`/`send_hold_key` 等 5 個入口自動依 `get_method()` 選路。後台 PostMessage 模式已移除（Unity 讀 OS 游標、無法精準點擊），底層 `_*_postmessage` 保留作為 frida 的傳送層。frida 鍵盤：hook `GetKeyState`/`GetAsyncKeyState`/`GetKeyboardState` 假造按鍵狀態（只覆寫注入中的 vk）+ `WM_KEYDOWN/UP`；`_key_postmessage` 對方向鍵等設 extended-key lParam（bit 24）。

後台輸入需視窗 hwnd，座標為**客戶區像素**（非螢幕絕對值），`_client_to_screen()` 轉換後形成 `lparam`。

### 座標

後台模式下的 ROI/點擊比例是相對於客戶區影像像素（無邊框）。`roi_coord: "client"` 標記指示 `_resolve_roi()`（`05_main_loop.py:380`）和 `_resolve_point()`（`05_main_loop.py:408`）需加 `client_offset` 校正。選取流程：前景 selector（`07_gui_roi`/`13_gui_click_picker`/`14_capture_region`）回傳螢幕絕對座標 → `screenshot_controller`/`06_gui_main` 用 `get_window_rect` + `get_window_client_offset` 收斂為含 `roi_coord:"client"` 的客戶區比例座標（模板另由 `14_capture_region` 寫 `capture_size`）。後台模板與執行時截圖來源不同但比對一致（BrownDust II 實測信心 1.0），故不再需要後台 PrintWindow 框選 UI。

### 全黑偵測

`is_black_capture()`（`15_print_window.py:25`）檢查 PrintWindow 輸出全像素為 0 才判為全黑（真實畫面再暗也有非零像素；None/空圖回 False）。非管理員時提示權限不足（如鳴潮遊戲），commit `4281972`、`72a9456`。OCR 診斷面板（`gui/09_ocr_debug.py:356`）也會檢查全黑並合併提示。

### 工具保護排除

後台模式不會被工具前景保護擋下（commit `c2c5327`: `_ensure_window_foreground()` 在後台模式跳過保護）。

### `template_source` 寫入 metadata

`match_image` 模板建立時仍會寫入 `template_source`（前景/後台），但僅為留存的 metadata，比對與啟動不再做任何一致性檢查（commit `a075576` 移除跨模式防呆；前景/後台截圖像素相容，差異只在輸入能否後台操控，已由後台黑畫面偵測、硬性問題檢查與實測機制負責）。改動前要小心：曾有過 `fddd7f7` 防呆，錄製轉換遺漏 `template_source` 曾導致誤報「模板來源不符」。

## 一鍵啟動/取消群組

`_StopGroupsPicker`（`gui/06_gui_main.py:164`）+ `_toggle_all_groups()`（`gui/06_gui_main.py:4497`）

按鈕文字隨狀態切換：`T("main.toggle_all_on")` / `T("main.toggle_all_off")`。點擊後一次性切換所有群組的 `enabled` 狀態。

## 規則執行引擎

`StepContext` 攜帶單次規則執行期間跨步驟的狀態：`img`（截圖）、`rect`（視窗位置尺寸）、`matched_text`（上一偵測步驟結果）、`triggered`（是否已觸發動作，決定是否推進群組指標）、`step_idx`。

**主循環執行順序**：每幀先跑所有 `background=True` 規則（獨立於群組、`jump` 步驟無效但 `on_fail.jump` 仍有效）→ 根據群組模式（`sequential` 用 `_rule_in_group_ptr` 指向單一規則 / `parallel` 從頭掃描只執行第一個觸發的規則）執行當前規則 → 規則內逐步驟執行，每步回傳 `continue` / `stop` / `jump_step` → 若 `ctx.triggered == True` 則 `_advance_rule_in_group()` 前進；否則停留原規則下幀重試 → 指標超出範圍時觸發 `_on_group_complete()`（依 `loop`/`once`/`repeat` 決定重置或前進；新建群組預設為 `once`，commit `3b171e6` 前為 `loop`）。

**`fail_duration_sec`（已驗證，05_main_loop.py:182）**：
```python
self._fail_since: dict[
    str, float
] = {}  # key=f"{rule_id}:{step_idx}" -> first-fail monotonic timestamp
```
邏輯：首次失敗時記錄 `time.monotonic()` 時間戳並回傳 `stop`（不觸發失敗動作，本幀提前結束、不設 triggered、下幀從步驟 0 重試）；後續每幀檢查 `now - first_fail < fail_duration`，未到時長持續回傳 `stop`。修復於 commit `4cb403c`：原本回傳 `continue` 會讓 `_run_rule` 誤判「等待中」為「本步驟已通過」，導致後續步驟（如 click）在容忍期內被誤觸發。成功偵測時（`_handle_detect`/`_handle_match_image`/`_handle_compare` 命中時）會主動 `pop` 該 key 清除失敗計時。`stop` 動作在 0 秒時維持向下相容寫法（純字串 `"stop"`），其餘動作一律帶 `fail_duration_sec` 欄位。

**動作後延遲 `after_delay_ms`（毫秒、預設 0，動作步驟 click/key/drag/scroll 通用）**：動作成功送出後固定等待，等價社群「動作後 sleep」、可取代 `[動作, wait]` 成對步驟。實作在 `_run_rule` 步驟迴圈單一 choke point（`core/05_main_loop.py`：動作類型 step 且 `result.action=="continue"` 且 `ms>0` → `_stop_event.wait(ms/1000)`，中斷回 stop interrupted、尾隨步驟不執行）；不經四個 handler、與 scroll 既有 `delay_ms`（格間延遲）語意不同。GUI 四個表單各提供「動作後延遲」spin，摘要 `>0` 才顯示；序列化在 `rule_migration._normalize_step_params` 對應分支收斂（字串/負數→0），舊規則缺欄位→0 向後相容。

**on_fail 動作語意速查（StarSavior 任務實測驗證）**：
- `stop`（預設）＝無限輪詢等待：本幀 stop、指標不動、下幀從步驟 0 重試。偵測閘（每日 ×63、跑馬 ×65）與跑馬每個事件規則 step0 全用它。
- `advance`＝有界放棄本規則：fd 期滿設 `force_advance`，`_process_rules` 推進到下一規則。once/sequential 的「可選 UI 前置」用（每日 ×12）；**loop/parallel 與背景規則下是靜默 no-op**（parallel 只查 `triggered`、背景結果捨棄）。
- `notify`＝有界放棄整鏈：fd 期滿顯示訊息並把 `stop_groups` 移出 active。**loop/parallel 下會永久移除該群組**，可能整場停止──跑馬刻意不用 notify，每日用（×16，常見 message 模板＝「沒有找到…」「沒有…可領取」）。
- `key`＝次要失敗回退：fd 期滿按 fallback 鍵、`triggered=True` 視同觸發。跑馬邏輯判定規則（×7）、每日按 Escape（×2）。已與 `_handle_key` 同步補 CPS/前景 guard（05_main_loop.py on_fail key 分支）。
- `skip`/`jump`＝流程跳轉：目前無任何真實任務使用，刻意保留。
- **三階分工**＝stop 無界等 / advance 有界放棄本規則 / notify 有界放棄整鏈。loop/parallel 只用 stop+key，每日才用 advance/notify。
- fd 微值（0.1~0.5s）實際＝延後一幀再動作（解析度受 scan_interval 限制）；「stop 配 fd」會週期性重複 stop、永不推進，無任務使用、刻意避開。

**畫面變化檢測跳幀（已驗證，05_main_loop.py:1209）**：
```python
if change_ratio < 0.02 and not self._should_process_static_frame():
```
是 AND 條件。`_should_process_static_frame()` 直接回傳 `self._has_detect_rules`（規則含 `detect`/`match_image` 步驟時為 True）。也就是說：畫面靜止且當前沒有需要偵測的規則時才跳過整幀處理。這個機制有單元測試覆蓋（1435-1488 行，Test 12）。診斷「規則明明該觸發卻沒反應」時，這是優先排查點之一——尤其當畫面長時間無變化、且規則集中沒有 detect 類步驟時。

**notify 步驟類型（commit `5f0f187`）。** notify 是新的步驟類型，用於在螢幕右下角疊加顯示提示訊息，不影響規則流程（回傳 `continue`）。`_NotificationStack`（`gui/06_gui_main.py:2908`）使用 label 手動定位取代 QVBoxLayout（commit `e73dc86`），因為多則訊息在 QVBoxLayout 下會互相覆蓋。任務匯入白名單需含 `notify`，否則含此步驟的規則會被拒（commit `c89fdf1`）。

**match_image 雙階段驗證（commit `0516abc`、`a7394ef`）。** match_image 新增「比對顏色」選項（`match_color`），模板比對通過後再做顏色篩選：灰階只比形狀，啟用比對顏色則保留 BGR 三通道資訊，並以 `color_tolerance`（`core/11_template_matching.py:80`）過濾平均色差超過容許值的候選框。`color_tolerance` 預設值從 40 改為 100（commit `c6f044e`）。`_run_dry_run` 測試按鈕需同步傳遞 `match_color` 參數（commit `1fda9e2`）；圖片比對按鈕改讀 widget 即時值，不依賴 save()（commit `fac2cef`）。

## GUI 規則樹拖曳排序

`_RuleTreeWidget` 繼承 `QTreeWidget`，重寫 `dropEvent`，自訂 `reordered = pyqtSignal()` 訊號在拖放成功後發射（不依賴 Qt 內建的 `model().rowsMoved`，該訊號對頂層群組項目拖曳不可靠，已在 commit `2ebacc0` 棄用）。`MainWindow` 連接 `reordered` → `_on_rules_reordered`：重建 `self._rules`/`self._groups` → `_flush_save()`（立即寫入，跳過防抖）。一般編輯變更則走 `_schedule_save()`，500ms 防抖合併多次變更。

## 任務檔案格式

JSON 結構：`rules`（含 `id`/`name`/`enabled`/`background`/`steps`）、`groups`（含 `mode`/`rule_ids`/`order` 等）、`window_title`、`capture_size`、`_collapsed_groups`。讀取時自動執行舊格式遷移（`_migrate_v1_to_v2`、`migrate_v2_to_v3`），並依 `capture_size` 將座標轉為比例。寫入採原子寫入（暫存檔 + `os.rename` replace），避免中途崩潰損毀檔案。`import_task()` 的 UUID 重新生成是**可選**（`regenerate_uuids: bool = False`，預設關閉，需呼叫端主動傳 `True`）。

## 已知陷阱（避免誤判）

1. ~~打包遺漏陷阱（已解決）~~：`build.py` 的 `py_datas` 已於 commit `f45f9ad` 改為 glob 自動掃描 `core/` 和 `gui/` 下所有 `*.py`，新增檔案不再需要手動同步。

2. **「測試」≠「測試比對」**：規則編輯面板的「測試」（`TestRunController.on_test_rule` → `_run_dry_run`，位於 `gui/test_run_controller.py`）是整條規則的乾執行，模擬全部步驟但不送出實際點擊/按鍵。`match_image` 步驟內的「測試比對」（`_img_compare_match`，`gui/06_gui_main.py:1311`）只直接呼叫 `_tmpl_mod.match_template()`，不經過規則引擎，與規則流程無關。修一個不會自動修好另一個。

3. **背景規則自動脫離群組**：規則標記為 `background=True` 後會自動從所屬群組移除（顯示於樹狀圖「📡 常駐監控」節點），取消標記則移回「未歸類」群組。背景規則內的 `jump` 步驟對群組指標無效（執行前後會 save/restore `_rule_pointer`），但 `on_fail.jump` 仍可作用於同群組規則。

4. **`skip_to` 是 0-based**：`on_fail` 的 `skip` 動作中 `skip_to` 對應內部 `step_idx`（0-based）。GUI 下拉選單顯示「步驟 N」（1-based），實際儲存 `i-1`。手動編輯 JSON 需注意換算。

5. **`capture_size` 影響模板比對搜尋範圍**：任務檔案若記錄了建立範本時的視窗尺寸（`capture_size`），`match_template()` 會依當前尺寸與 `capture_size` 比值，只在窄範圍尺度（約 0.9~1.1）搜尋，大幅提速；若缺少 `capture_size` 則退回較寬的多尺度範圍，跨解析度時比對結果可能不穩定。

6. **Qt `model().rowsMoved` 不可靠**：對頂層群組項目的拖曳操作，這個內建訊號可能不觸發或順序不對，導致資料看似拖完了但實際沒存。一律用自訂 `pyqtSignal` 取代，不要依賴它做持久化判斷依據。

7. ~~控制器檔案打包遺漏（已解決）~~：同陷阱 1，`build.py` 的 glob 自動掃描已涵蓋 `gui/` 下所有 `*.py`（含非數字開頭的 controller），不再需要手動列出。

8. **`max_side_len=0` 繞過預設**：`02_ocr_engine.py` 定義 `_DEFAULT_MAX_SIDE_LEN = 480`，但主循環 `_ocr_region()` 所有 `recognize()` 呼叫皆直接傳 `max_side_len=0`（無縮限），完全繞過此預設。若要限制全圖 OCR 尺寸，需在 `_ocr_region()` 修改，而非改 `_DEFAULT_MAX_SIDE_LEN`。

9. **`capture()` 回傳 None ≠ 回傳黑圖像**：`capture()` 回傳 None 時，主循環才會呼叫 `capture_window_content()`（GDI 備援）。但若 mss/dxcam 回傳全黑但非 None 的圖像，GDI 備援不會被觸發。診斷「截圖全黑」問題時，先確認是 None 還是黑圖。

10. **後台截圖全黑需管理員權限**（commit `4281972`、`e43b97c`、`72a9456`）：PrintWindow 對受保護視窗（如鳴潮遊戲）可能回全黑。`is_black_capture()`（`15_print_window.py:25`）自動偵測，非管理員時精準提示需以系統管理員權限執行。OCR 診斷面板（`gui/09_ocr_debug.py:356`）合併提示避免覆蓋。

11. **後台座標轉換遺漏會系統性偏移**（已修復，commit `e852d38`）：ROI/點擊/擷取/拖曳 4 處需 `ScreenToClient` 轉換，漏一項即偏移。修復後後台座標 `roi_coord:"client"` 由 `_resolve_roi()`/`_resolve_point()` 自動處理。

12. **後台模式不被工具前景保護誤擋**（已修復，commit `c2c5327`）：`_ensure_window_foreground()` 在後台模式跳過窗口保護。若後台執行時視窗不斷被拉回前景，檢查 `interaction_mode` 是否正確。

13. **`template_source` 跨模式防呆已移除（commit `a075576`）**：曾有 `fddd7f7` 檢查模板來源（前景/後台）與互動模式一致性，因前景/後台截圖像素相容、防呆只是誤報源（錄製轉換遺漏 `template_source` 時錄製任務必彈警告），已整個拔除。現 `template_source` 僅為寫入 metadata，不參與比對；跨模式比對不再產生警告。

14. **效能檔位功能評估後不實作（2026-08-11）**：曾被提案加入「效能檔位」（節能/均衡/高效能，三檔一鍵調整 + 進階微調），評估後拒絕（YAGNI、刪除優先）。理由：實際可調的全局效能參數僅 `scan_interval_ms`（偵測頻率，`06_gui_main.py:2880`）＋ `max_cps`（點擊上限，`06_gui_main.py:2874`）兩顆，皆早已在設定頁可見——三檔只是重打包既有旋鈕，無實質增值。補充佐證：主循環 OCR 完全不縮圖（見第 8 條），高效能檔沒有更快空間；模板 scale 候選數（`11_template_matching.py` 13/5 個）是唯一「強硬體可多做工」的旋鈕，但影響有限不開放；內部常數（`_MIN_INTERVAL_SEC`、GPU provider、`_RATE_LIMIT_*`）屬實作細節或反作弊保護，不開放。

## GUI／MainLoop 檔案層級 write-write race（已修復，commit `7974267` + `eda47c2`）

**病灶**：`MainLoop` 執行中每 20 次迭代（或停止時），若 `_rules_dirty=True`（規則觸發時設定），會用自己記憶體中的 `self._rules` 快照直接呼叫 `save_rules()` 覆寫任務檔（此邏輯已於 commit `eda47c2` 完全移除，不再存在於目前的 `05_main_loop.py`）。GUI 端的一般規則編輯（`_save_current_rule`）在 loop 執行中會被 UI disabled 擋住，但 `_on_background_changed`（勾選「常駐監控」）沒有這層防護，可以在 loop 執行中直接存檔。GUI 的 `save_task()`/`save_groups()` 呼叫與 loop 的週期性存檔之間存在檔案層級的 write-write race：GUI 剛寫入的新規則，可能在下一瞬間被 loop 用舊快照覆寫掉。症狀：新建立的「常駐監控」規則，在 loop 執行過幾輪、且使用者編輯過後，重啟工具即消失。

**修復歷程**：commit `7974267` 先將 `_do_debounced_save()`（`gui/06_gui_main.py:4855`）改為當 `self._loop` 存在時，`save_task` + `save_groups` + `loop._load_rules()` 全部包在 `with self._loop._rules_lock:` 內原子執行（`_rules_lock` 是 `threading.RLock()`，可重入不會死鎖）。隨後 commit `eda47c2` 進一步移除 loop 的週期性存檔與 `_rules_dirty` 死碼，消除 race 的根本源頭——目前 loop 完全不寫任務檔，GUI 是唯一的寫入者，`_rules_lock` 仍用於保護 GUI 寫入與 loop `_load_rules()` 讀取之間的競爭。

**壓力測試驗證**（真實 threading 併發，非循序模擬，50 次疊代）：修復前規則遺失率 100%（21 條預期→實際 1~6 條存活），修復後 0%（21 條全數存活）。

**診斷教訓**：純程式碼靜態分析＋循序模擬的 round-trip 測試（load→save→load）無法揭露這類 bug，因為兩個獨立寫入者各自的循序邏輯都「正確」，問題只在真正併發交錯時出現。懷疑寫入遺失且靜態分析找不到根因時，優先檢查是否有多個執行緒／執行路徑各自直接寫同一檔案，而非透過共同的鎖或單一寫入點。

## 已修復 bug 清單（基準版本後）

| commit | 修復內容 |
|---|---|
| `d15022a` | 最大化狀態在 minimize/restore 後遺失 |
| `386a82e` | float ROI 切片 crash（三處 slice 入口補 `int()` 防禦） |
| `e31110c` + `73c4850` | 群組展開收起 widget 殘影（用 `setUpdatesEnabled` 凍結父容器） |
| `1d87b89` + `a70fd1b` | `_collapsed_groups` 狀態被 `itemExpanded` 污染（用 suppress flag） |
| `3c5ad4a` | 迴圈停止時執行日誌未 flush（成功步驟不顯示） |
| `5ef4f5a` | `_DetectStepForm` 缺 `self._list` 賦值致框選偵測區域 crash |
| `0fe678b` | F8 停止主循環時破壞視窗最大化狀態 |
| `0c20b64` | 後台操控模式整合（PrintWindow 截圖、PostMessage 輸入、GUI 後台化） |
| `e852d38` | 後台模式座標轉換錯誤（ROI/點擊/擷取/拖曳 4 處） |
| `c2c5327` | 後台模式不再被工具前景保護誤擋 |
| `4281972` | 後台截圖全黑偵測，非系統管理員時精準提醒（如鳴潮） |
| `e43b97c` | 後台截圖失敗文案精簡 |
| `72a9456` | OCR 診斷全黑提示改與耗時訊息合併顯示，避免被覆蓋 |
| `6618a31` | 前景模式圖片比對先縮小主視窗再 mss 截圖並用 finally 復原 |
| `d1df9dc` | 圖片比對回饋無法作用（`_MatchImageStepForm` 呼叫 MainWindow 方法崩潰） |
| `ae68d27` | ROI debug 格式化對 `roi_coord` 字串值防呆 |
| `fddd7f7` | `match_image` 模板標記來源互動模式並於比對/啟動防呆（防呆已於 `a075576` 移除，標記保留為 metadata） |
| `17d4735` | 統一執行事件寫入 app.log，移除無消費者 `triggers.jsonl` |
| `249d2cf` | 清掃殘留 `triggers.jsonl`，新增 `is_debug_enabled`，生命週期事件提升為 INFO |
| `27b9dfa` | LogViewer 內容未變更時不打斷捲動，向上瀏覽不再被自動拉回底部 |
| `d640509` | LogViewer 關閉停止刷新，同步 debug 狀態，方法更名為 `_open_log_viewer` |
| `20b9cf1` | 異常加 traceback，循環停止新增執行統計（秒數+點擊+規則數） |

## 未記錄子系統摘要（基準版本後新增）

### A. i18n 多語言系統（commit `21a611c` 起至 `ad9a65e`、`db7de24` 等）

`T(msg_id, **kwargs)` 函式（`i18n/__init__.py`）查目前語言 JSON → fallback `zh_TW` → 回傳原始 key。兩份 JSON（zh_TW/en.json 各 701 keys）均為扁平 dot-separated key。`i18n/check.py` 強制雙語言 key set 一致。

v0.1.8 新增 key：`main.toggle_all_on`、`main.toggle_all_off`、`tooltip.toggle_all_groups`。移除 AHK 相關 6 個 key（`status.ahk_*`、`dialog.install_ahk*`）。

語言切換（`gui/06_gui_main.py` near line 2891）→ 寫入 config.json → `subprocess.Popen(updater_main.py --mode=relaunch --wait-pid=<pid>)` → 等待舊 process 結束 → 啟動新 process。覆蓋範圍：~570+ T() 呼叫（`gui/06_gui_main.py` 內 571 次，加上各 controller/selectors），僅限 gui/ 層。`core/` 層無 i18n。

### B. 自動更新機制——Velopack（v0.4.0 起，ADR `docs/adr/0001-adopt-velopack.md`）

v0.4.0 起由 **Velopack** 框架接管，自製 updater.exe／manifest-delta 協定已拆除：

- 安裝形態：Setup.exe → `%LocalAppData%\OCRTriggerClicker\current\`；框架 `Update.exe` 在 app 目錄**之外**，換目錄不可能自我鎖定
- feed：GitHub Releases 的 `releases.win.json`；位址由 `build.py --feed prod|test` 烘入 `_update_feed.py`，打包後防呆驗證。`test` = 公開沙箱庫 `ocr-trigger-clicker-release-test`（`release.ps1 -FeedTest` 直接發布打靶）
- 用戶端：main() 最頂端 `velopack App().set_auto_apply_on_startup(True).run()`；`core/12_updater.py:check_for_update()`／`download_and_apply()` 薄封裝；GUI `_start_download` 套用成功即 quit+`os._exit(0)` 讓框架重啟
- delta：`release.ps1` 先 `vpk download github` 取前版，`vpk pack` 自動產生（實測 0.4.0→0.4.1 約 0.55 MB）；失敗自動退回 full
- **單一實例防護**：`CreateMutexW("Local\\OCRTriggerClicker.SingleInstance")`，第二份提示退出——雙開鎖安裝目錄曾致舊 updater rename 必敗（v0.3.1 兩度撤回根因）
- **relaunch 內建化**：語言切換重啟改 app 自帶 `--wait-exit-pid=N` 參數（`_wait_exit_pid_arg()` 於 main 最早執行），不再借道外部 exe，與 mutex 不互撞
- `latest_version.txt` 凍結於 0.3.0（舊客戶端斷糧顯示暫無更新）；`clean_stale_temp_dirs()` 保留於啟動清掃，兜底清舊制殘留的 `%TEMP%\ocr_update_*`

### C. 任務目錄統一 APPDATA（commit `2e7895e`）

dev/frozen 雙軌模式 → 一律 `%APPDATA%\ocr-trigger-clicker\tasks\`。受 `OCR_TRIGGER_DATA` 環境變數覆寫。`core/task_management.py:24-33` 不再區分 `_is_frozen()`；`core/04_rule_engine.py:67-74` 遷移邏輯同步統一。

仍保留 dev/frozen 分支的項目（資源路徑、範本圖片、設定檔、重啟程式路徑）屬合理範圍，非路徑重複。

### D. 路徑邏輯集中 core/_paths.py + build.py glob（commit `f45f9ad`）

`core/_paths.py`（29 行）：`_is_frozen()`、`_bundle_root()`、`_appdata_path()`、`get_data_path()`、`get_resource_path()`。取代先前散落在 10+ 檔案中的內聯路徑邏輯。

`build.py` 手動 25+ 條 `py_datas` → `core/` 與 `gui/` 各一行 `rglob("*.py")`。新增 `.py` 檔案不再需手動同步。

### E. 規則列表 UI 變更（`05a7f24` 起 ~13 commits）

`_RuleTreeWidget` 現為雙欄位：Column 0 = 名稱（stretch），格式 `"👁 [✓] RuleName"`；Column 1 = 標籤（ResizeToContents），靠右垂直置中，格式 `"5步 失敗"`。

比對模式名稱演進：`正規`→`模板比對`，`模糊`→`模糊比對`→`近似比對`。工具列 tooltip（on_fail/點擊目標/群組模式）、模板比對輔助按鈕等。`default_wait_ms` 可自訂；閒置時狀態列顯示真實 CPU/記憶體。

### F. build.py 打包更新（v0.1.7~v0.1.8）

AHK 移除後，`clicker.ahk` datas 已刪除。新增 `pynput`、`dxcam`、`comtypes` 至 `hiddenimports`（lazy-imported，靜態掃描可能遺漏），並加 `--collect-all=comtypes`、`--collect-all=dxcam`、`--collect-all=pynput` 收集所有二進位。

排除清單新增：`mypy`、`ast_serialize`（numpy typing stubs 拉入的開發工具）、`lxml`、`Pythonwin`、`win32`、`pythoncom`、`win32com`、`pywin32_bootstrap`（無人使用的 XML/COM 相關）。dist 瘦身效果顯著。

### G. 錄製操作（示範錄製，v0.2.3 後）

**資料流**：GUI 按「錄製操作」（`_record_btn`，`gui/06_gui_main.py:3500`）或按 F9（`core/00_global_hotkey.py` 新增 hid=2；`_on_hotkey` hid==2 → `_on_record_clicked()`，hid==1 → `_restore_window()`+`_toggle_start()`）→ `Recorder.start(title, hwnd, session_dir)`（`core/19_recorder.py:228`）開始攔截目標視窗內滑鼠點擊 → 停止後（`_stop_recording`，`gui/06_gui_main.py:4045`，先 `_restore_window()`）問是否轉換 → `_convert_recording_to_task`（`gui/06_gui_main.py:4082`）以 QInputDialog 選「新任務」或「併入既有任務」（`list_tasks()`），併入用 `merge_rule_entries` + `save_task_with_groups`。

**session 目錄**：`%APPDATA%\ocr-trigger-clicker\recordings\session-YYYYMMDD-HHMMSS\`（`events.json` + `frames/*.jpg`），由 `_recordings_dir()` = `get_data_path("recordings")`。轉換成功後清除已用 session（commit `dd0fb06`）。

**三層轉換規則**（`core/20_recorder_convert.py`，每滑鼠事件一條規則）：
1. 點擊落於動作前畫面的 OCR 文字區塊 → `detect(關鍵字, roi, on_fail=stop)` + `click(text_center)`（等文字出現再點，座標隨文字縮放）。錨點參數：`_ANCHOR_RADIUS=160`、`_ANCHOR_MARGIN=12`、`_ROI_EXPAND=0.25`。
2. 無文字但有紋理 → 以點擊座標向外擴張裁特徵方塊存 `match_image`（base64 內嵌）+ `click(text_center)`。參數：`_TMPL_MIN_RADIUS=24`/`_MAX_RADIUS=56`/`_STEP=8`、`_TMPL_STD_MIN=16.0`、`_TMPL_THRESHOLD=0.8`。
3. 無特徵或被裁剪 → `wait(錄製間隔)` + `click(custom 比例)`（純計時播放，`_FALLBACK_GAP_MS=(300,5000)`）。

座標一律**視窗比例**（0~1）；session 轉成群組 `mode=once`。**`template_source` 防呆已於 `a075576` 移除**（見陷阱 13），轉換規則不會誤報模板來源警告。

**設定窗預設套用**：`convert_sessions(session_dirs, defaults=None)` 接受預設 dict（`fuzzy_threshold` / `template_threshold` / `color_tolerance` / `random_offset` / `after_delay_ms`），由 GUI `_convert_recording_to_task`（`gui/06_gui_main.py:4082`）從 `RuleConfigController` 組出經 `RecordConvertWorker` 傳入；`None` 回退模組內建常數。`after_delay_ms` 只在 `> 0` 寫入（缺欄位＝0 等價，JSON 精簡）。刻意排除：anchored 固定 `match_mode=fuzzy`（錨點設計）、button 沿用錄製實際按鍵、timing 的 wait 用錄製間隔。

**測試**：`tests/test_recorder_convert.py`（11 測試）涵蓋轉換三層、群組結構與預設套用。GUI 端 `Recorder`/`RecordConvertWorker`（`gui/06_gui_main.py:2765/2791`）依賴 Win32 畫面，無 pytest，以手動驗證。

## 診斷工作流程慣例

加印 debug log 在關鍵 signal/slot 邊界（如 `dropEvent`、`_on_rules_reordered`、`_refresh_rule_list`）→ 從終端機執行重現以取得輸出 → 找出實際分歧的程式碼路徑 → 修根因 → 用 `git log` 驗證 commit 確實落地。改動指令給執行端（小弟/OpenCode）時必須完整明確，不預期來回確認。

**提案前必做核實**：任何推薦/優化建議前，必須先以 `codegraph_explore` 優先（`Grep+Read` 備選）檢索相關符號/檔名/文案 key，有結果即視為已存在；每項建議附 `file:line` 定位，無定位視為未完成（見 `AGENTS.md:提案/推薦前必做核實`）。

## Release Notes 寫法規範

Release notes 必須分兩層，先一般使用者後技術細節，中間用 `---` 分隔：

1. **一般使用者摘要** — 白話、功能角度，不說內部機制。用「你可以…」「適合用來…」這類表達。條列 3~5 項重點。
2. **技術細節** — 提交類型分類（`✨ 新功能` / `🔧 修正` / `🚀 改善`），附 commit hash。寫給貢獻者與進階使用者看。

範例結構：

```
## vX.Y.Z 更新內容

### 🎯 一般使用者更新摘要

**功能 A**
一句話說明做了什麼、對使用者有什麼好處。

**功能 B**
同上。

---

### 🔧 技術細節

### ✨ 新功能
- 功能（commit `xxxxxxx`）

### 🔧 修正
- 修正（commit `xxxxxxx`）

### 🚀 改善
- 改善（commit `xxxxxxx`）
```

---

## 驗證記錄

以下項目已用 `rg` 直接對照原始碼第一手確認（非僅憑模型自我審查）。行號參照可能因持續開發而偏移，建議以 `rg` 確認為準。

- `_fail_since` 字典與鍵值格式 `f"{rule_id}:{step_idx}"` — 確認存在於 `core/05_main_loop.py:182`，邏輯分布於 `_handle_detect`、`_handle_match_image`、`_handle_compare`、`_handle_on_fail`、`get_rules_status`。
- fail_duration_sec 修正（commit `4cb403c`）— 首次失敗回傳 `stop`、容忍期內持續 `stop`、過期後正常觸發 on_fail，完整生命週期覆蓋。
- 畫面變化檢測 AND 條件 — 確認 `core/05_main_loop.py:1265` 為 `change_ratio < 0.02 and not self._should_process_static_frame()`。
- GUI／MainLoop write-write race 與其修復（commit `7974267` + `eda47c2`）— 根因定位、修改內容、`git show` diff、真實併發壓力測試結果，皆直接讀取原始碼與執行測試腳本第一手確認。
- 全域熱鍵 — `core/00_global_hotkey.py` 註冊 F8（hid=1，對應 `MainWindow._on_hotkey()` → `_restore_window()`+`_toggle_start()`）與 F9（hid=2，→ `_on_record_clicked()`）。
- i18n 系統 — `T()` 實作於 `i18n/__init__.py`，三語言 JSON 經 `tests/test_i18n.py` 驗證一致性。語言切換重啟為 app 內建 relaunch（`--wait-exit-pid` 參數）。
- 自動更新 — Velopack 框架接管（見上「B. 自動更新機制」）：`core/12_updater.py` 薄封裝 `check_for_update()`／`download_and_apply()`，feed 由 `build.py --feed prod|test` 烘入 `_update_feed.py`；單一實例 CreateMutex 防護；`latest_version.txt` 凍結 0.3.0 斷糧舊客戶端。
- 路徑集中 — `core/_paths.py` 5 函式，取代 10+ 檔案內聯路徑。`build.py` glob `rglob("*.py")` 取代手動 py_datas。
- 截圖 — `core/17_capture_pipeline.py:48` `capture_frame(mode, title, hwnd)` 為統一管線：前景 `_capture_foreground`（mss 三層備援）、後台 `_capture_background`（PrintWindow）。`core/15_print_window.py:25` `is_black_capture()` 全黑偵測。
- `_log_exec` 去重 — `core/05_main_loop.py:224` 兩層抑制：同 key 去重 + completed 1 秒節流。
- `on_warning` 觸發點 — `core/05_main_loop.py:195` 宣告，觸發於空 ROI 效能警告（line 480）、match_image 首次匹配（line 526）、compare 全圖 OCR（line 564）、流程停止（line 674）、規則異常（line 1116/1074/1140）、全黑警告（line 1254，log）、背景截圖失敗（`15_print_window.py:149`）。
- `_toggle_all_groups` — `gui/06_gui_main.py:4496`，切換所有群組啟用狀態。
- `_img_compare_match` 行號 — `gui/06_gui_main.py:1311`。
- `_do_debounced_save` 行號 — `gui/06_gui_main.py:4954`。
- 後台模式 — `_get_interaction_mode()` 於 `gui/06_gui_main.py:85-95`，後台輸入 `core/16_bg_input.py:192` `click()`，ROI/點擊/模板選取統一走前景 selector（後台模式設定時會將目標視窗前景化）。
- LogViewer — `gui/12_log_viewer.py:30` `LogViewer(QDialog)`，開啟於 `gui/06_gui_main.py:5644` `_open_log_viewer()`。
- 停止統計 — `core/05_main_loop.py:1308-1321` `start()`/`stop()`，`_started_at` + `_total_clicks`（`core/10_performance_monitor.py` `get_total_clicks()`）。
- 錄製操作 — `core/19_recorder.py:228` `Recorder.start()`、`core/20_recorder_convert.py` `convert_sessions()`/`merge_rule_entries()`、`core/00_global_hotkey.py` F9（hid=2）、`gui/06_gui_main.py` `_on_record_clicked`(4001)/`_start_recording`(4007)/`_stop_recording`(4045)/`_convert_recording_to_task`(4082)。

其餘內容來自代碼分析與自我審查，審查時逐項附上程式碼引用，未發現推測性內容，但未逐一做第一手覆核，使用時若涉及關鍵決策建議二次確認。
