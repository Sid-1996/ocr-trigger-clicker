---
name: project-context
description: ocr-trigger-clicker 專案的架構知識、已知陷阱與子系統摘要。涉及 ROI 座標系統、OCR vs 模板比對、規則執行引擎（StepContext、on_fail、fail_duration_sec）、dxcam 截圖備援、box_utils 座標工具、執行日誌面板、效能警告、GUI 規則樹拖曳排序、任務檔案格式、i18n 多語言、自動更新、路徑集中化設計。
---

# ocr-trigger-clicker 架構與陷阱筆記

> 基準版本：git commit `e01a1e1` (2026-08-01, v0.1.8)
> 本文件內容已逐項對照實際原始碼驗證（見文末驗證記錄），可信度高。
> 行號參照可能因持續開發而偏移，建議以 `rg` 確認為準。

## 目錄結構

模組地圖與各模組職責詳見 `docs/dev/ARCHITECTURE.md`，此處僅列關鍵檔案與本 skill 關注的細節。

### core/

| 檔案 | 一行摘要 | 本 skill 關鍵細節 |
|---|---|---|
| `00_global_hotkey.py` | 全域熱鍵 F8 | 僅 hid=1，切換開始/暫停/停止 |
| `00_logging_config.py` | 日誌初始化 | rotation、等級、格式 |
| `01_screenshot.py` | 視窗截圖 | **mss → dxcam 雙層備援**，GDI 備援僅客戶區（見截圖備援鏈） |
| `02_ocr_engine.py` | OCR 引擎 | `_DEFAULT_MAX_SIDE_LEN = 480`，但主循環繞過此預設 |
| `03_pynput_input.py` | 輸入模擬 | pynput SendInput，**取代已刪除的 AHK**（`03_ahk_socket.py` 不存在） |
| `04_rule_engine.py` | 規則引擎 hub | re-export + 16 個 self-check |
| `box_utils.py` | 座標工具集 | 10 純函式 + 17 self-check（見 box_utils 小節） |
| `rule_models.py` | 資料模型 | `Rule`、`Step`、`RuleGroup`、`ImportPreview` |
| `rule_migration.py` | 舊格式遷移 | v1→v2/v2→v3 + `_STEP_DEFAULTS` |
| `rule_serialization.py` | JSON 序列化 | `load_rules`/`save_rules`/`load_groups`/`save_groups` |
| `task_management.py` | 任務 CRUD | `list_tasks`/`load_task`/`save_task`/`import_task`/`export_task` |
| `run_config.py` | 執行配置 | 視窗標題、執行模式、擷取尺寸 |
| `file_utils.py` | 原子寫入 | `_replace_file()` |
| `05_main_loop.py` | 主偵測迴圈 | 2182 行，整個應用的心臟（見規則執行引擎） |
| `10_performance_monitor.py` | 效能監控 | FPS/CPU/記憶體、速率限制 |
| `11_template_matching.py` | 模板比對 | OpenCV matchTemplate + NMS |
| `12_updater.py` | 自動更新 | GitHub Releases 版本比對 |
| `trigger_log.py` | 觸發紀錄 | JSONL 格式 |
| `_paths.py` | 路徑集中 | `get_data_path`/`get_resource_path`/`_appdata_path` |

### gui/

| 檔案 | 一行摘要 | 本 skill 關鍵細節 |
|---|---|---|
| `06_gui_main.py` | 主視窗 | 5826 行，含 `_ExecutionLogWidget`、`_StopGroupsPicker` |
| `07_gui_roi.py` | ROI 框選 | 全螢幕 overlay |
| `09_ocr_debug.py` | OCR 除錯 | 即時辨識結果 |
| `13_gui_click_picker.py` | 點擊座標選取 | 螢幕绝对 → 比例座標 |
| `14_capture_region.py` | 模板擷取 | base64 編碼、capture_size |
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

另有 `i18n/`（多語言，614 keys × 3 語言）與 `tests/`（pytest 單元測試）。

任務檔案實際路徑：`%APPDATA%\ocr-trigger-clicker\tasks\`（不在專案目錄內）。

## 核心原則

**OCR 與模板比對對座標誤差的容忍度不同。** OCR 是語意比對，位置有小幅偏移仍能辨識成功；模板比對是像素級比對，座標只要偏移幾個 pixel 就會比對失敗。診斷「比對失敗但 OCR 正常」類問題時，先往座標精度方向查。

**`roi_coord: "client"` 機制。** ROI 比例預設以全視窗尺寸為基準儲存。若 `roi` 字典含 `"roi_coord": "client"`，代表比例是相對於客戶區（不含標題列/邊框）。還原時（`_resolve_roi()`）需呼叫 `get_window_client_offset()` 取得邊框偏移量，再轉換為含邊框的全視窗像素座標 —— 因為 `capture()` 截圖本身含邊框。忽略此標記會導致裁切區域系統性偏移。舊任務（無此標記）視為以全視窗比例儲存，向下相容。此機制在基準版本前已修補了多處遺漏（`_CompareStepForm`、OCR 診斷面板、舊檔載入路徑），commits：`2cc7db6`、`db094f4`、`2502b52`、`ff2ffb0`。

## 截圖備援鏈

`capture()`（主循環使用）有兩層備援：
1. **mss** — 跨平台截圖，含邊框（`_capture_mss`）
2. **dxcam** — DXGI 截圖，速度最快但需 DirectX 支援（`_capture_dxcam`）

若兩者皆回傳 None（例如目標視窗被完全遮蔽），主循環（`05_main_loop.py:96`）會呼叫 `capture_window_content()` 作為最後手段：
1. **GDI PrintWindow** — 客戶區，不含邊框
2. **GDI BitBlt** — 備援的備援

**關鍵陷阱**：`capture()` 回傳 None 與回傳全黑圖像是不同的。若 mss/dxcam 回傳全黑但非 None，`capture_window_content()` 不會被呼叫。

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

**但主循環完全繞過此預設**：`_ocr_region()`（`05_main_loop.py:300-328`）所有 `recognize()` 呼叫皆直接傳 `max_side_len=0`（無縮限）。ROI 分支裁切後的子圖也傳 0。

歷史：曾短暫實作全圖 `max_side_len=480`→`720` 限制（commits `c98b883`、`a4460a4`），後因偵測精度考量全數移除（commit `9ca2998`）。

**效能警告**：空 ROI + 畫面寬度 > 800px 時，`_handle_detect` 會發出警告並透過 `on_warning` 通知 GUI（`05_main_loop.py:385-394`）。

## on_warning 回呼機制

`MainLoop.on_warning: Optional[Callable[[str], None]]`（`05_main_loop.py:186`）

觸發時機：
- 空 ROI + 畫面寬 > 800px（`05_main_loop.py:385-394`）
- match_image 首次匹配成功（`05_main_loop.py:434-436`）
- compare 步驟全圖 OCR（`05_main_loop.py:473-475`）
- 流程停止（`05_main_loop.py:582-583`）
- 規則異常（`05_main_loop.py:805-806`, `979-980`, `1023-1024`）

GUI 連接：`loop.on_warning = lambda msg: self._signals.warning_signal.emit(msg)`（`gui/06_gui_main.py:2596`）

## 執行日誌面板

`_ExecutionLogWidget`（`gui/06_gui_main.py:2906`）— 即時顯示規則逐步驟執行紀錄。

**資料來源**：`MainLoop._log_exec()`（`05_main_loop.py:213-244`），每步執行結果寫入 `_execution_log` 佇列，GUI 定時拉取。

**兩層抑制**（避免 flood）：
1. **同 key 去重**：`_last_exec_log` 字典，相同 `(rule_name, step_idx)` 若 result+detail 不變則跳過
2. **completed 節流**：同一 rule_name 的 completed 訊息 1 秒內只顯示一次

GUI 端也有自己的 suppression（commit `bc2ff06`：用 `step.type + rule.id + scroll 4 方向` 去重）。

**人類可讀摘要**：`_infer_stop_detail()`（`05_main_loop.py:881`）產生 stop 原因，`_build_ok_detail()`（`05_main_loop.py:905`）產生 ok 摘要（含 match_image 百分比、scroll/drag 方向等）。

## 一鍵啟動/取消群組

`_StopGroupsPicker`（`gui/06_gui_main.py:136`）+ `_toggle_all_groups()`（`gui/06_gui_main.py:4396`）

按鈕文字隨狀態切換：`T("main.toggle_all_on")` / `T("main.toggle_all_off")`。點擊後一次性切換所有群組的 `enabled` 狀態。

## 規則執行引擎

`StepContext` 攜帶單次規則執行期間跨步驟的狀態：`img`（截圖）、`rect`（視窗位置尺寸）、`matched_text`（上一偵測步驟結果）、`triggered`（是否已觸發動作，決定是否推進群組指標）、`step_idx`。

**主循環執行順序**：每幀先跑所有 `background=True` 規則（獨立於群組、`jump` 步驟無效但 `on_fail.jump` 仍有效）→ 根據群組模式（`sequential` 用 `_rule_in_group_ptr` 指向單一規則 / `parallel` 從頭掃描只執行第一個觸發的規則）執行當前規則 → 規則內逐步驟執行，每步回傳 `continue` / `stop` / `jump_step` → 若 `ctx.triggered == True` 則 `_advance_rule_in_group()` 前進；否則停留原規則下幀重試 → 指標超出範圍時觸發 `_on_group_complete()`（依 `loop`/`once`/`repeat` 決定重置或前進；新建群組預設為 `once`，commit `3b171e6` 前為 `loop`）。

**`fail_duration_sec`（已驗證，05_main_loop.py:173）**：
```python
self._fail_since: dict[str, float] = {}  # key=f"{rule_id}:{step_idx}" -> first-fail monotonic timestamp
```
邏輯：首次失敗時記錄 `time.monotonic()` 時間戳並回傳 `stop`（不觸發失敗動作，本幀提前結束、不設 triggered、下幀從步驟 0 重試）；後續每幀檢查 `now - first_fail < fail_duration`，未到時長持續回傳 `stop`。修復於 commit `4cb403c`：原本回傳 `continue` 會讓 `_run_rule` 誤判「等待中」為「本步驟已通過」，導致後續步驟（如 click）在容忍期內被誤觸發。成功偵測時（`_handle_detect`/`_handle_match_image`/`_handle_compare` 命中時）會主動 `pop` 該 key 清除失敗計時。`stop` 動作在 0 秒時維持向下相容寫法（純字串 `"stop"`），其餘動作一律帶 `fail_duration_sec` 欄位。

**畫面變化檢測跳幀（已驗證，05_main_loop.py:1181）**：
```python
if change_ratio < 0.02 and not self._should_process_static_frame():
```
是 AND 條件。`_should_process_static_frame()` 直接回傳 `self._has_detect_rules`（規則含 `detect`/`match_image` 步驟時為 True）。也就是說：畫面靜止且當前沒有需要偵測的規則時才跳過整幀處理。這個機制有單元測試覆蓋（1435-1488 行，Test 12）。診斷「規則明明該觸發卻沒反應」時，這是優先排查點之一——尤其當畫面長時間無變化、且規則集中沒有 detect 類步驟時。

**notify 步驟類型（commit `5f0f187`）。** notify 是新的步驟類型，用於在螢幕右下角疊加顯示提示訊息，不影響規則流程（回傳 `continue`）。`_NotificationStack`（`gui/06_gui_main.py:2815`）使用 label 手動定位取代 QVBoxLayout（commit `e73dc86`），因為多則訊息在 QVBoxLayout 下會互相覆蓋。任務匯入白名單需含 `notify`，否則含此步驟的規則會被拒（commit `c89fdf1`）。

**match_image 雙階段驗證（commit `0516abc`、`a7394ef`）。** match_image 新增「比對顏色」選項（`match_color`），模板比對通過後再做顏色篩選：灰階只比形狀，啟用比對顏色則保留 BGR 三通道資訊，並以 `color_tolerance`（`core/11_template_matching.py:80`）過濾平均色差超過容許值的候選框。`color_tolerance` 預設值從 40 改為 100（commit `c6f044e`）。`_run_dry_run` 測試按鈕需同步傳遞 `match_color` 參數（commit `1fda9e2`）；圖片比對按鈕改讀 widget 即時值，不依賴 save()（commit `fac2cef`）。

## GUI 規則樹拖曳排序

`_RuleTreeWidget` 繼承 `QTreeWidget`，重寫 `dropEvent`，自訂 `reordered = pyqtSignal()` 訊號在拖放成功後發射（不依賴 Qt 內建的 `model().rowsMoved`，該訊號對頂層群組項目拖曳不可靠，已在 commit `2ebacc0` 棄用）。`MainWindow` 連接 `reordered` → `_on_rules_reordered`：重建 `self._rules`/`self._groups` → `_flush_save()`（立即寫入，跳過防抖）。一般編輯變更則走 `_schedule_save()`，500ms 防抖合併多次變更。

## 任務檔案格式

JSON 結構：`rules`（含 `id`/`name`/`enabled`/`background`/`steps`）、`groups`（含 `mode`/`rule_ids`/`order` 等）、`window_title`、`capture_size`、`_collapsed_groups`。讀取時自動執行舊格式遷移（`_migrate_v1_to_v2`、`migrate_v2_to_v3`），並依 `capture_size` 將座標轉為比例。寫入採原子寫入（暫存檔 + `os.rename` replace），避免中途崩潰損毀檔案。`import_task()` 的 UUID 重新生成是**可選**（`regenerate_uuids: bool = False`，預設關閉，需呼叫端主動傳 `True`）。

## 已知陷阱（避免誤判）

1. ~~打包遺漏陷阱（已解決）~~：`build.py` 的 `py_datas` 已於 commit `f45f9ad` 改為 glob 自動掃描 `core/` 和 `gui/` 下所有 `*.py`，新增檔案不再需要手動同步。

2. **「測試」≠「測試比對」**：規則編輯面板的「測試」（`TestRunController.on_test_rule` → `_run_dry_run`，位於 `gui/test_run_controller.py`）是整條規則的乾執行，模擬全部步驟但不送出實際點擊/按鍵。`match_image` 步驟內的「測試比對」（`_img_compare_match`，`gui/06_gui_main.py:1284`）只直接呼叫 `_tmpl_mod.match_template()`，不經過規則引擎，與規則流程無關。修一個不會自動修好另一個。

3. **背景規則自動脫離群組**：規則標記為 `background=True` 後會自動從所屬群組移除（顯示於樹狀圖「📡 常駐監控」節點），取消標記則移回「未歸類」群組。背景規則內的 `jump` 步驟對群組指標無效（執行前後會 save/restore `_rule_pointer`），但 `on_fail.jump` 仍可作用於同群組規則。

4. **`skip_to` 是 0-based**：`on_fail` 的 `skip` 動作中 `skip_to` 對應內部 `step_idx`（0-based）。GUI 下拉選單顯示「步驟 N」（1-based），實際儲存 `i-1`。手動編輯 JSON 需注意換算。

5. **`capture_size` 影響模板比對搜尋範圍**：任務檔案若記錄了建立範本時的視窗尺寸（`capture_size`），`match_template()` 會依當前尺寸與 `capture_size` 比值，只在窄範圍尺度（約 0.9~1.1）搜尋，大幅提速；若缺少 `capture_size` 則退回較寬的多尺度範圍，跨解析度時比對結果可能不穩定。

6. **Qt `model().rowsMoved` 不可靠**：對頂層群組項目的拖曳操作，這個內建訊號可能不觸發或順序不對，導致資料看似拖完了但實際沒存。一律用自訂 `pyqtSignal` 取代，不要依賴它做持久化判斷依據。

7. ~~控制器檔案打包遺漏（已解決）~~：同陷阱 1，`build.py` 的 glob 自動掃描已涵蓋 `gui/` 下所有 `*.py`（含非數字開頭的 controller），不再需要手動列出。

8. **`max_side_len=0` 繞過預設**：`02_ocr_engine.py` 定義 `_DEFAULT_MAX_SIDE_LEN = 480`，但主循環 `_ocr_region()` 所有 `recognize()` 呼叫皆直接傳 `max_side_len=0`（無縮限），完全繞過此預設。若要限制全圖 OCR 尺寸，需在 `_ocr_region()` 修改，而非改 `_DEFAULT_MAX_SIDE_LEN`。

9. **`capture()` 回傳 None ≠ 回傳黑圖像**：`capture()` 回傳 None 時，主循環才會呼叫 `capture_window_content()`（GDI 備援）。但若 mss/dxcam 回傳全黑但非 None 的圖像，GDI 備援不會被觸發。診斷「截圖全黑」問題時，先確認是 None 還是黑圖。

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

## 未記錄子系統摘要（基準版本後新增）

### A. i18n 多語言系統（commit `21a611c` 起至 `ad9a65e`、`db7de24` 等）

`T(msg_id, **kwargs)` 函式（`i18n/__init__.py`）查目前語言 JSON → fallback `zh_TW` → 回傳原始 key。三份 JSON（zh_TW/zh_CN/en.json 各 614 keys）均為扁平 dot-separated key。`i18n/check.py` 強制三語言 key set 一致。

v0.1.8 新增 key：`main.toggle_all_on`、`main.toggle_all_off`、`tooltip.toggle_all_groups`。移除 AHK 相關 6 個 key（`status.ahk_*`、`dialog.install_ahk*`）。

語言切換（`gui/06_gui_main.py:2756-2811`）→ 寫入 config.json → `subprocess.Popen(updater_main.py --mode=relaunch --wait-pid=<pid>)` → 等待舊 process 結束 → 啟動新 process。覆蓋範圍：~677 T() 呼叫，僅限 gui/ 層。`core/` 層無 i18n。

### B. 自動更新機制（commit `56ba94d`、`295b677` 等）

四階段流程：
1. **版本檢查**（`core/12_updater.py`）：GitHub raw `latest_version.txt` 比對 `__version__`
2. **更新對話框**（`gui/06_gui_main.py:5610-5652` `_UpdateInfoDialog`）：釋出 notes + 自動更新/前往 Release/取消
3. **下載**（`core/12_updater.py:download_update`）：64KB chunks，ZIP 解壓至 `%TEMP%/ocr_update_RANDOM/staging/`
4. **套用**（`updater_main.py --mode=update`）：
   - `os.rename(target→target_old)` 備份（同磁碟瞬間完成）
   - `shutil.copytree(staging→target, copy_function=_robust_copy)` 逐檔複製（每檔 retry 3x，整包 retry 3x）
   - 失敗 → rollback（`os.rename(target_old→target)`）
   - 成功 → `rmtree(target_old)` + 清理 `%TEMP%/ocr_update_*` 暫存目錄 → 啟動新 process
   - `wait_for_pid_exit()` 使用 `INFINITE` 等待（無逾時）

主程式 `--onedir`、updater.exe `--onefile`（`build.py` 228-253）。`--mode=relaunch` 共用於語言切換重啟。`updater_main.py` 含 `demo()` self-check（`--demo` 模式）。

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

## 診斷工作流程慣例

加印 debug log 在關鍵 signal/slot 邊界（如 `dropEvent`、`_on_rules_reordered`、`_refresh_rule_list`）→ 從終端機執行重現以取得輸出 → 找出實際分歧的程式碼路徑 → 修根因 → 用 `git log` 驗證 commit 確實落地。改動指令給執行端（小弟/OpenCode）時必須完整明確，不預期來回確認。

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

- `_fail_since` 字典與鍵值格式 `f"{rule_id}:{step_idx}"` — 確認存在於 `core/05_main_loop.py:173`，邏輯分布於 `_handle_detect`、`_handle_match_image`、`_handle_compare`、`_handle_on_fail`、`get_rules_status`。
- fail_duration_sec 修正（commit `4cb403c`）— 首次失敗回傳 `stop`、容忍期內持續 `stop`、過期後正常觸發 on_fail，完整生命週期覆蓋。
- 畫面變化檢測 AND 條件 — 確認 `core/05_main_loop.py:1181` 為 `change_ratio < 0.02 and not self._should_process_static_frame()`。
- GUI／MainLoop write-write race 與其修復（commit `7974267` + `eda47c2`）— 根因定位、修改內容、`git show` diff、真實併發壓力測試結果，皆直接讀取原始碼與執行測試腳本第一手確認。
- 全域熱鍵 — `core/00_global_hotkey.py` 僅註冊 F8（hid=1），對應 `MainWindow._on_hotkey()` → `_toggle_start()`。
- i18n 系統 — `T()` 實作於 `i18n/__init__.py`，三語言 JSON 各 614 keys 經 `i18n/check.py` 驗證一致性。語言切換重啟流程經 `updater_main.py --mode=relaunch` 確認。
- 自動更新 — `core/12_updater.py:check_for_update` 比對 GitHub raw `latest_version.txt`，`download_update` 下載 ZIP 至 `%TEMP%/ocr_update_*/staging/`，`apply_update` 啟動 `updater.exe --mode=update`。`updater_main.py` 含 copytree 逐檔複製、rollback、暫存目錄清理機制。
- 路徑集中 — `core/_paths.py` 5 函式，取代 10+ 檔案內聯路徑。`build.py` glob `rglob("*.py")` 取代手動 py_datas。
- 截圖備援鏈 — `core/01_screenshot.py:189` `capture()` 為 mss → dxcam 雙層備援；`capture_window_content()`（line 285）為 GDI 備援（PrintWindow → BitBlt）。
- `_log_exec` 去重 — `core/05_main_loop.py:213` 兩層抑制：同 key 去重 + completed 1 秒節流。
- `on_warning` 觸發點 — `core/05_main_loop.py:186` 宣告，觸發於空 ROI 效能警告（line 385）、match_image 首次匹配（line 434）、compare 全圖 OCR（line 473）、流程停止（line 582）、規則異常（line 805/979/1023）。
- `_toggle_all_groups` — `gui/06_gui_main.py:4396`，切換所有群組啟用狀態。
- `_img_compare_match` 行號 — 已從 1282 偏移至 `gui/06_gui_main.py:1284`。
- `_do_debounced_save` 行號 — 已從 4744 偏移至 `gui/06_gui_main.py:4855`。

其餘內容來自代碼分析與自我審查，審查時逐項附上程式碼引用，未發現推測性內容，但未逐一做第一手覆核，使用時若涉及關鍵決策建議二次確認。
