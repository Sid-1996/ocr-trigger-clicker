---
name: project-context
description: ocr-trigger-clicker 專案的架構知識與已知陷阱。涉及 ROI 座標系統、OCR/模板比對、規則執行引擎（StepContext、on_fail、fail_duration_sec）、GUI 規則樹拖曳排序、任務檔案格式時使用此 skill。
---

# ocr-trigger-clicker 架構與陷阱筆記

> 基準版本：git commit `e8ebfb8` (2026-07-03)
> 本文件內容已逐項對照實際原始碼驗證（見文末驗證記錄），可信度高。
> 若目前 HEAD 與基準 commit 差距很大，請對涉及的子系統提高警覺，必要時重新核對代碼。

## 目錄結構（與舊文件不同，請以此為準）

實際路徑分兩個子目錄，不是平鋪在根目錄：

- `core/01_screenshot.py` — 視窗截圖核心（mss 截圖含邊框 / GDI 備援僅客戶區）
- `core/02_ocr_engine.py` — OCR 引擎封裝（RapidOCR），`recognize()` / `find_text()`
- `core/03_ahk_socket.py` — AutoHotkey TCP 通訊層
- `core/04_rule_engine.py` — 規則/步驟/群組資料模型、序列化、任務 CRUD、格式遷移
- `core/05_main_loop.py` — 主偵測迴圈，核心邏輯所在（1665 行，整個應用的心臟）
- `core/10_performance_monitor.py` — FPS/CPU/記憶體監控、全域點擊速率限制
- `core/11_template_matching.py` — OpenCV 模板比對（多尺度、NMS）
- `gui/06_gui_main.py` — 主視窗，規則樹、步驟編輯器、任務管理
- `gui/07_gui_roi.py` — ROI 框選覆蓋層
- `gui/09_ocr_debug.py` — OCR 除錯面板
- `gui/13_gui_click_picker.py` — 點擊座標選取器
- `gui/14_capture_region.py` — 模板圖片擷取器（含 base64 編碼、capture_size 記錄）
- `_loader.py`（根目錄）— 動態載入數字開頭模組的工具，含 RLock 快取

任務檔案實際路徑：`%APPDATA%\ocr-trigger-clicker\tasks\`（不在專案目錄內）。

## 核心原則

**OCR 與模板比對對座標誤差的容忍度不同。** OCR 是語意比對，位置有小幅偏移仍能辨識成功；模板比對是像素級比對，座標只要偏移幾個 pixel 就會比對失敗。診斷「比對失敗但 OCR 正常」類問題時，先往座標精度方向查。

**`roi_coord: "client"` 機制。** ROI 比例預設以全視窗尺寸為基準儲存。若 `roi` 字典含 `"roi_coord": "client"`，代表比例是相對於客戶區（不含標題列/邊框）。還原時（`_resolve_roi()`）需呼叫 `get_window_client_offset()` 取得邊框偏移量，再轉換為含邊框的全視窗像素座標 —— 因為 `capture()` 截圖本身含邊框。忽略此標記會導致裁切區域系統性偏移。舊任務（無此標記）視為以全視窗比例儲存，向下相容。此機制在 baseline 之後又發現並修補了多處遺漏（`_CompareStepForm`、OCR 診斷面板、舊檔載入路徑），commits：`2cc7db6`、`db094f4`、`2502b52`、`ff2ffb0`。

## 規則執行引擎

`StepContext` 攜帶單次規則執行期間跨步驟的狀態：`img`（截圖）、`rect`（視窗位置尺寸）、`matched_text`（上一偵測步驟結果）、`triggered`（是否已觸發動作，決定是否推進群組指標）、`step_idx`。

**主循環執行順序**：每幀先跑所有 `background=True` 規則（獨立於群組、`jump` 步驟無效但 `on_fail.jump` 仍有效）→ 根據群組模式（`sequential` 用 `_rule_in_group_ptr` 指向單一規則 / `parallel` 從頭掃描只執行第一個觸發的規則）執行當前規則 → 規則內逐步驟執行，每步回傳 `continue` / `stop` / `jump_step` → 若 `ctx.triggered == True` 則 `_advance_rule_in_group()` 前進；否則停留原規則下幀重試 → 指標超出範圍時觸發 `_on_group_complete()`（依 `loop`/`once`/`repeat` 決定重置或前進；新建群組預設為 `once`，commit `3b171e6` 前為 `loop`）。

**`fail_duration_sec`（已驗證，05_main_loop.py:164-166, 455-465）**：
```python
self._fail_since: dict[str, float] = {}  # key=f"{rule_id}:{step_idx}" -> first-fail monotonic timestamp
```
邏輯：首次失敗時記錄 `time.monotonic()` 時間戳並回傳 `stop`（不觸發失敗動作，本幀提前結束、不設 triggered、下幀從步驟 0 重試）；後續每幀檢查 `now - first_fail < fail_duration`，未到時長持續回傳 `stop`。修復於 commit `4cb403c`：原本回傳 `continue` 會讓 `_run_rule` 誤判「等待中」為「本步驟已通過」，導致後續步驟（如 click）在容忍期內被誤觸發。成功偵測時（`_handle_detect`/`_handle_match_image`/`_handle_compare` 命中時）會主動 `pop` 該 key 清除失敗計時。`stop` 動作在 0 秒時維持向下相容寫法（純字串 `"stop"`），其餘動作一律帶 `fail_duration_sec` 欄位。

**畫面變化檢測跳幀（已驗證，05_main_loop.py:251-252, 907）**：
```python
if change_ratio < 0.02 and not self._should_process_static_frame():
```
是 AND 條件。`_should_process_static_frame()` 直接回傳 `self._has_detect_rules`（規則含 `detect`/`match_image` 步驟時為 True）。也就是說：畫面靜止且當前沒有需要偵測的規則時才跳過整幀處理。這個機制有單元測試覆蓋（約 1372-1425 行，Test 12）。診斷「規則明明該觸發卻沒反應」時，這是優先排查點之一——尤其當畫面長時間無變化、且規則集中沒有 detect 類步驟時。

**notify 步驟類型（commit `5f0f187`）。** notify 是新的步驟類型，用於在螢幕右下角疊加顯示提示訊息，不影響規則流程（回傳 `continue`）。`_NotificationStack`（`gui/06_gui_main.py:2422`）使用 label 手動定位取代 QVBoxLayout（commit `e73dc86`），因為多則訊息在 QVBoxLayout 下會互相覆蓋。任務匯入白名單需含 `notify`，否則含此步驟的規則會被拒（commit `c89fdf1`）。

**match_image 雙階段驗證（commit `0516abc`、`a7394ef`）。** match_image 新增「比對顏色」選項（`match_color`），模板比對通過後再做顏色篩選：灰階只比形狀，啟用比對顏色則保留 BGR 三通道資訊，並以 `color_tolerance`（`core/11_template_matching.py:77`）過濾平均色差超過容許值的候選框。`color_tolerance` 預設值從 40 改為 100（commit `c6f044e`）。`_run_dry_run` 測試按鈕需同步傳遞 `match_color` 參數（commit `1fda9e2`）；圖片比對按鈕改讀 widget 即時值，不依賴 save()（commit `fac2cef`）。

## GUI 規則樹拖曳排序

`_RuleTreeWidget` 繼承 `QTreeWidget`，重寫 `dropEvent`，自訂 `reordered = pyqtSignal()` 訊號在拖放成功後發射（不依賴 Qt 內建的 `model().rowsMoved`，該訊號對頂層群組項目拖曳不可靠，已在 commit `2ebacc0` 棄用）。`MainWindow` 連接 `reordered` → `_on_rules_reordered`：重建 `self._rules`/`self._groups` → `_flush_save()`（立即寫入，跳過防抖）。一般編輯變更則走 `_schedule_save()`，500ms 防抖合併多次變更。

## 任務檔案格式

JSON 結構：`rules`（含 `id`/`name`/`enabled`/`background`/`steps`）、`groups`（含 `mode`/`rule_ids`/`order` 等）、`window_title`、`capture_size`、`_collapsed_groups`。讀取時自動執行舊格式遷移（`_migrate_v1_to_v2`、`migrate_v2_to_v3`），並依 `capture_size` 將座標轉為比例。寫入採原子寫入（暫存檔 + `os.rename` replace），避免中途崩潰損毀檔案。`import_task()` 的 UUID 重新生成是**可選**（`regenerate_uuids: bool = False`，預設關閉，需呼叫端主動傳 `True`）。

## 已知陷阱（避免誤判）

1. **「測試」≠「測試比對」**：規則編輯面板的「測試」（`_on_test_rule` → `_run_dry_run`）是整條規則的乾執行，模擬全部步驟但不送出實際點擊/按鍵。`match_image` 步驟內的「測試比對」（`_test_match`）只直接呼叫 `match_template()`，不經過規則引擎，與規則流程無關。修一個不會自動修好另一個。

2. **背景規則自動脫離群組**：規則標記為 `background=True` 後會自動從所屬群組移除（顯示於樹狀圖「📡 常駐監控」節點），取消標記則移回「未歸類」群組。背景規則內的 `jump` 步驟對群組指標無效（執行前後會 save/restore `_rule_pointer`），但 `on_fail.jump` 仍可作用於同群組規則。

3. **`skip_to` 是 0-based**：`on_fail` 的 `skip` 動作中 `skip_to` 對應內部 `step_idx`（0-based）。GUI 下拉選單顯示「步驟 N」（1-based），實際儲存 `i-1`。手動編輯 JSON 需注意換算。

4. **`capture_size` 影響模板比對搜尋範圍**：任務檔案若記錄了建立範本時的視窗尺寸（`capture_size`），`match_template()` 會依當前尺寸與 `capture_size` 比值，只在窄範圍尺度（約 0.9~1.1）搜尋，大幅提速；若缺少 `capture_size` 則退回較寬的多尺度範圍，跨解析度時比對結果可能不穩定。

5. **Qt `model().rowsMoved` 不可靠**：對頂層群組項目的拖曳操作，這個內建訊號可能不觸發或順序不對，導致資料看似拖完了但實際沒存。一律用自訂 `pyqtSignal` 取代，不要依賴它做持久化判斷依據。

## GUI／MainLoop 檔案層級 write-write race（已修復，commit `7974267`）

**病灶**：`MainLoop` 執行中每 20 次迭代（或停止時），若 `_rules_dirty=True`（規則觸發時設定），會用自己記憶體中的 `self._rules` 快照直接呼叫 `save_rules()` 覆寫任務檔（`05_main_loop.py:940/971`）。GUI 端的一般規則編輯（`_save_current_rule`）在 loop 執行中會被 UI disabled 擋住，但 `_on_background_changed`（勾選「常駐監控」）沒有這層防護，可以在 loop 執行中直接存檔。GUI 的 `save_task()`/`save_groups()` 呼叫完全沒有 acquire `loop._rules_lock`，與 loop 的週期性存檔之間存在檔案層級的 write-write race：GUI 剛寫入的新規則，可能在下一瞬間被 loop 用舊快照覆寫掉。症狀：新建立的「常駐監控」規則，在 loop 執行過幾輪、且使用者編輯過後，重啟工具即消失。

**修復**：`_do_debounced_save()`（`gui/06_gui_main.py:4217`）改為當 `self._loop` 存在時，`save_task` + `save_groups` + 清除 `loop._rules_dirty` + `loop._load_rules()` 全部包在 `with self._loop._rules_lock:` 內原子執行（`_rules_lock` 是 `threading.RLock()`，可重入不會死鎖）。

**壓力測試驗證**（真實 threading 併發，非循序模擬，50 次疊代）：修復前規則遺失率 100%（21 條預期→實際 1~6 條存活），修復後 0%（21 條全數存活）。

**診斷教訓**：純程式碼靜態分析＋循序模擬的 round-trip 測試（load→save→load）無法揭露這類 bug，因為兩個獨立寫入者各自的循序邏輯都「正確」，問題只在真正併發交錯時出現。懷疑寫入遺失且靜態分析找不到根因時，優先檢查是否有多個執行緒／執行路徑各自直接寫同一檔案，而非透過共同的鎖或單一寫入點。

## 診斷工作流程慣例

加印 debug log 在關鍵 signal/slot 邊界（如 `dropEvent`、`_on_rules_reordered`、`_refresh_rule_list`）→ 從終端機執行重現以取得輸出 → 找出實際分歧的程式碼路徑 → 修根因 → 用 `git log` 驗證 commit 確實落地。改動指令給執行端（小弟/OpenCode）時必須完整明確，不預期來回確認。

---

## 驗證記錄

以下兩項已用 `Select-String` 直接對照原始碼第一手確認（非僅憑模型自我審查）：

- `_fail_since` 字典與鍵值格式 `f"{rule_id}:{step_idx}"` — 確認存在於 `core/05_main_loop.py:164-166`，邏輯分布於 358/401/431/457-463/1122 行。
- fail_duration_sec 修正（commit `4cb403c`）與 Test 25（`core/05_main_loop.py:1674-1768`）— 首次失敗回傳 `stop`、容忍期內持續 `stop`、過期後正常觸發 on_fail，完整生命週期覆蓋。
- 畫面變化檢測 AND 條件 — 確認 `core/05_main_loop.py:907` 為 `change_ratio < 0.02 and not self._should_process_static_frame()`，且有對應單元測試（Test 12，約 1372-1425 行）。
- GUI／MainLoop write-write race 與其修復（commit `7974267`）— 根因定位、修改內容、`git show` diff、真實併發壓力測試結果，皆由 Claude 直接讀取原始碼與執行測試腳本第一手確認，非模型自我審查。

其餘內容來自 DeepSeek V4 Pro 對代碼的分析與自我審查，審查時逐項附上程式碼引用，未發現推測性內容，但未逐一做第一手覆核，使用時若涉及關鍵決策建議二次確認。
