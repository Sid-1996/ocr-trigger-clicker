---
name: project-context
description: ocr-trigger-clicker 專案的架構知識與已知陷阱。涉及 ROI 座標系統、OCR/模板比對、規則執行引擎（StepContext、on_fail、fail_duration_sec）、GUI 規則樹拖曳排序、任務檔案格式時使用此 skill。
---

# ocr-trigger-clicker 架構與陷阱筆記

> 基準版本：git commit `a9fd6fc` (2026-06-30)
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

**`roi_coord: "client"` 機制。** ROI 比例預設以全視窗尺寸為基準儲存。若 `roi` 字典含 `"roi_coord": "client"`，代表比例是相對於客戶區（不含標題列/邊框）。還原時（`_resolve_roi()`）需呼叫 `get_window_client_offset()` 取得邊框偏移量，再轉換為含邊框的全視窗像素座標 —— 因為 `capture()` 截圖本身含邊框。忽略此標記會導致裁切區域系統性偏移。舊任務（無此標記）視為以全視窗比例儲存，向下相容。

## 規則執行引擎

`StepContext` 攜帶單次規則執行期間跨步驟的狀態：`img`（截圖）、`rect`（視窗位置尺寸）、`matched_text`（上一偵測步驟結果）、`triggered`（是否已觸發動作，決定是否推進群組指標）、`step_idx`。

**主循環執行順序**：每幀先跑所有 `background=True` 規則（獨立於群組、`jump` 步驟無效但 `on_fail.jump` 仍有效）→ 根據群組模式（`sequential` 用 `_rule_in_group_ptr` 指向單一規則 / `parallel` 從頭掃描只執行第一個觸發的規則）執行當前規則 → 規則內逐步驟執行，每步回傳 `continue` / `stop` / `jump_step` → 若 `ctx.triggered == True` 則 `_advance_rule_in_group()` 前進；否則停留原規則下幀重試 → 指標超出範圍時觸發 `_on_group_complete()`（依 `loop`/`once`/`repeat` 決定重置或前進）。

**`fail_duration_sec`（已驗證，05_main_loop.py:164-166, 455-465）**：
```python
self._fail_since: dict[str, float] = {}  # key=f"{rule_id}:{step_idx}" -> first-fail monotonic timestamp
```
邏輯：首次失敗時記錄 `time.monotonic()` 時間戳並回傳 `continue`（不觸發失敗動作）；後續每幀檢查 `now - first_fail < fail_duration`，未到時長持續回傳 `continue`；超過時長才 pop 該 key 並真正執行 `on_fail` 動作。成功偵測時（`_handle_on_fail`/`_handle_match_image`/`_handle_compare` 命中時）會主動 `pop` 該 key 清除失敗計時。`stop` 動作在 0 秒時維持向下相容寫法（純字串 `"stop"`），其餘動作一律帶 `fail_duration_sec` 欄位。

**畫面變化檢測跳幀（已驗證，05_main_loop.py:251-252, 907）**：
```python
if change_ratio < 0.02 and not self._should_process_static_frame():
```
是 AND 條件。`_should_process_static_frame()` 直接回傳 `self._has_detect_rules`（規則含 `detect`/`match_image` 步驟時為 True）。也就是說：畫面靜止且當前沒有需要偵測的規則時才跳過整幀處理。這個機制有單元測試覆蓋（約 1372-1425 行，Test 12）。診斷「規則明明該觸發卻沒反應」時，這是優先排查點之一——尤其當畫面長時間無變化、且規則集中沒有 detect 類步驟時。

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

## 診斷工作流程慣例

加印 debug log 在關鍵 signal/slot 邊界（如 `dropEvent`、`_on_rules_reordered`、`_refresh_rule_list`）→ 從終端機執行重現以取得輸出 → 找出實際分歧的程式碼路徑 → 修根因 → 用 `git log` 驗證 commit 確實落地。改動指令給執行端（小弟/OpenCode）時必須完整明確，不預期來回確認。

---

## 驗證記錄

以下兩項已用 `Select-String` 直接對照原始碼第一手確認（非僅憑模型自我審查）：

- `_fail_since` 字典與鍵值格式 `f"{rule_id}:{step_idx}"` — 確認存在於 `core/05_main_loop.py:164-166`，邏輯分布於 358/401/431/457-463/1122 行。
- 畫面變化檢測 AND 條件 — 確認 `core/05_main_loop.py:907` 為 `change_ratio < 0.02 and not self._should_process_static_frame()`，且有對應單元測試（約 1372-1425 行）。

其餘內容來自 DeepSeek V4 Pro 對代碼的分析與自我審查，審查時逐項附上程式碼引用，未發現推測性內容，但未逐一做第一手覆核，使用時若涉及關鍵決策建議二次確認。
