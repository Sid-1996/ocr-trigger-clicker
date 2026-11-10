# Phase 3B — 規則 Dry-run 速度基準測量報告（READ-ONLY）

> 調查日期：2026-11-10（取消窗口指標於同日修正後重測）  
> 本報告僅量測，**未修改任何正式產品程式碼**（`gui/`、`core/`、`_loader.py` 零改動）、未改變原有執行邏輯、未建立 commit、未 push。  
> 獨立測量腳本：`devtools/benchmarks/phase3b_bench.py`  
> 測量結果：`devtools/benchmarks/phase3b_bench_results.json`（由腳本實際執行產生，非手改；`meta.titles`／`meta.part_b_note`／`meta.part_c_note` 內含各 section 的標題與解讀邊界）  
> **本文件所有數字皆與該 JSON 對應同一輪執行**（JSON `meta.generated_at` = 2026-11-10T19:10:20+08:00）。
> 重跑腳本會覆寫 JSON，數字隨機器負載浮動 —— 本輪執行時機器閒置，數字較接近乾淨基線，
> 但 OCR 相關數字仍應視為**該次負載下的量測值**，不是產品效能定值。
>
> **修訂記錄（同日，驗收時修正）**：前一版 Part B 的量測結果不可信，已修正後重測：
> 1. `wrapped_dry_run` 的關鍵字參數名與呼叫端不一致（`cancel2` vs `cancel`），導致 dry-run 每次都拋 `TypeError`，
>    Part B **實際上從未執行過 dry-run**，量到的是例外路徑。已修正。
> 2. `button_visible_ms` 讀的是從未被賦值的字典鍵，恆為 `0.0`（假值），非真實量測。已改讀 setVisible 實際呼叫時刻，
>    並改名為 `button_show_call_ms`（原名易被誤讀為「按鈕可見時間」）。
> 3. `signal_latency_ms` 原以「GUI 釋放→恢復」計算，在假 win 下會得到**負值**（同步 handler 先於 GUI 釋放發生）。
>    已改為「訊號發出→恢復」，並在統計時排除負值。
> 4. 缺少時間戳時 `ms()` 回傳 `0.0`，偽裝成「瞬間完成」；已改為 `None`。
> 5. 第二個測試案例會抓到第一個案例的 wrapper（closure 指向舊 rec），導致 dry-run 時間寫錯字典；已修正為固定抓原始方法。

---

## 1. Git 與環境資訊

| 項目 | 值 |
|---|---|
| Branch | `master` |
| HEAD commit | `c26b722` (`feat: 規則測試結果定位、測試生命週期守衛與取消（Phase 3B）`) |
| origin/master | 與 HEAD 一致（up to date，ahead/behind 0/0） |
| 工作區狀態 | 量測時無未提交修改（`git diff --stat` 為空），正式產品程式碼零改動；五個交付物（`devtools/benchmarks/`、`devtools/ux_prototypes/phase3b/`、`docs/dev/UX_PHASE3B_AUDIT.md`、`docs/dev/UX_PHASE3B_BENCHMARK.md`）已納入獨立 commit（`docs: add UX Phase 3B audit and benchmark artifacts`） |
| 專案版本 | `0.4.9`（`_version.py` / `pyproject.toml`） |
| 作業系統 | Windows 10 Home 2009（`OsName` 回報 Microsoft Windows 11 家用版） |
| Python | 3.13（`uv run python` 回報 3.13.14；`python --version` 回報 3.13.15） |
| CPU | Intel(R) Core(TM) i5-7600K @ 3.80GHz，4 核心 / 4 執行緒 |
| OCR 引擎 | RapidOCR (`rapidocr_onnxruntime`)，ONNX Runtime (`DmlExecutionProvider` / `CPUExecutionProvider`) |
| OCR 模型 | 引擎可懶載入並成功辨識（`core/custom_models/` 為空，使用內建/預設模型）；未離線 |
| 測試影像 | `tests/data/test.png`，1920×1080 |
| GUI 是否實際啟動 | 未開啟真實可見主視窗；使用 Qt Offscreen 平台（`QT_QPA_PLATFORM=offscreen`），以假 `win` 替身驅動 `TestRunController` |
| 假 win 的訊號機制 | **行程內同步 handler 清單**（`_SignalBus`：`emit()` 直接在呼叫端執行緒同步呼叫 handler）。**非**真實 Qt Signal/Slot、**非** queued connection。正式程式為 `gui/06_gui_main.py:5053` 的 `pyqtSignal(dict)`（QObject + 跨執行緒 queued connection，事件由 GUI 執行緒 event loop 分派） |
| 測試資料是否使用 mock | Part A 同時測「真實 OCR」與「mock OCR（控制流程測量）」；Part B 使用真實 OCR，但 `capture_frame` 被替換為即時回傳測試影像（與實際遊戲視窗擷取耗時分離） |

---

## 2. 測量方法及計時邊界

### 2.1 乾淨度原則
本腳本**只讀不改**：透過 `monkeypatch` 在腳本記憶體內替換 `recognize`、`capture_frame`、`get_client_rect_for_image` 等，正式程式碼檔（`gui/run_controller.py`、`gui/06_gui_main.py`、`core/*`）零改動。所有計時皆使用 `time.perf_counter_ns()`，單位統一為 **ms**。

### 2.2 Dry-run 完整呼叫鏈與計時邊界
**正式程式**的實際呼叫鏈（使用者按下「測試」→ 結果回來）：

1. `on_test_rule()`（GUI 執行緒）：前置檢查、儲存規則、建立 `threading.Event` 取消旗標、`_set_test_running(True)` 使取消按鈕可見、`QApplication.processEvents()` 刷新畫面、`capture_frame()`（GUI 執行緒阻塞）、建立並啟動 Worker 執行緒。
2. Worker 執行緒 `_run_rule_test()` → `_run_dry_run(rule, img, cancel=cancel)`：**dry-run 核心**（在背景執行，不阻塞 GUI）。
3. `_run_dry_run` 結束後，Worker 發送 `test_done_signal` 訊號。
4. GUI 執行緒收到訊號 → `_show_test_result()` → `_restore_test_btn()` 恢復 UI（取消按鈕隱藏、測試按鈕恢復）。

> **Part B 與正式程式的差異（重要）**：本輪 benchmark 以假 `win` 替身驅動 `TestRunController`，
> 第 4 步**不是**經由真實 Qt queued connection 分派到 GUI 執行緒，而是由腳本內的
> `_SignalBus`（同步 handler 清單）在 worker 執行緒直接呼叫 handler。
> 因此 Part B 的訊號相關數值僅能代表「程式層呼叫順序」，不能代表真實 GUI 的跨執行緒分派行為。

### 2.3 關鍵時區定義（Part B）與量測邊界限制

Part B 使用**假 `win` 替身**（非真實 QWidget），因此只能量到「程式層呼叫」，
無法量到「畫面已繪製」或「滑鼠可點擊」。三個取消窗口指標的語意嚴格區分如下：

| 指標 | 本輪量測結果 | 精確語意 | 不可宣稱的事 |
|---|---|---|---|
| `button_show_call_ms` | **有效數值**（約 0.01~0.03 ms） | 測試開始 → `_set_test_running(True)` 內 `setVisible(True)` 呼叫返回 | 不可稱為「按鈕可見時間」「使用者看得到」或「可點擊」 |
| `button_painted_to_hidden_ms` | **N/A（未量測）** | 假 win 無 QWidget paint 系統，無 QPainter 繪製事件可量 | 不可宣稱「按鈕已在畫面上」 |
| `cancel_input_operable_ms` | **N/A（未量測）** | 假 win 的訊號／插槽是行程內同步 handler 清單（無 QObject、無 event loop、無 queued connection），無真實訊息迴圈與輸入路由 | 不可宣稱「使用者真的按得到」 |
| `signal_latency_ms`（保留，僅環境參考） | 有效數值（約 0.003~0.004 ms） | **同步 Python handler list 的執行時間**（`emit()` 直接在呼叫端執行緒呼叫 handler） | **不代表**正式 GUI 跨執行緒 Qt Signal/Slot 延遲；不可稱為使用者可操作時間 |
| `dry_avg` / `restore_avg`（保留，僅環境參考） | 有效數值 | **假視窗測試流程**的耗時 | **不等於**真實使用者取消窗口 |

其他輔助參考值（同樣僅供環境參考）：
- **Dry-run 時間**：Worker 內 `_run_dry_run` 從開始到結束，**這是本輪唯一真實有效的執行時間量測**。
- **GUI 釋放**：`on_test_rule()` 返回後 GUI 才回到事件迴圈；此前按鈕雖已 `setVisible(True)`，但 GUI 執行緒仍被佔用。
- **恢復 UI**：`_restore_test_btn()` 執行時刻。

> 限制說明：本輪 Part B 以 `capture_frame` 即時回傳測試影像進行，故「GUI 釋放」間隔僅含控制器開銷，**不含**實際遊戲視窗擷取耗時。實際擷取（mss／PrintWindow／pynput 視窗切換）會拉長此間隙，見 §8。
---

## 3. 各情境測量數據表

### 3.1 A. `_run_dry_run()` 核心執行時間（真實 OCR，暖啟動）

| 情境 | n | min | avg | p50 | p95 | max (ms) |
|---|---|---|---|---|---|---|
| 0 步驟（空規則） | 60 | 0.004 | 0.004 | 0.004 | 0.005 | 0.019 |
| 1 步驟 detect（小 ROI，命中，OCR ~7 ms） | 60 | 4.379 | 6.096 | 4.937 | 7.034 | 62.091 |
| 1 步驟 detect（全圖 ROI，OCR ~1 s） | 10 | 897.506 | 1092.723 | 1056.564 | 1389.985 | 1525.915 |
| 3 步驟（detect 小 + click + key） | 60 | 4.478 | 7.598 | 5.865 | 10.296 | 41.377 |
| 5 步驟（detect 小 + click + key + wait + scroll） | 60 | 4.562 | 6.749 | 6.458 | 9.765 | 12.958 |
| 10 步驟（交錯 detect/click/key/wait/sum，小 ROI） | 60 | 13.46 | 16.463 | 14.982 | 25.896 | 33.157 |
| OCR 較重（3× detect，中 ROI，各 ~60 ms） | 15 | 182.232 | 335.82 | 257.145 | 699.514 | 1086.063 |

### 3.2 A. `_run_dry_run()` 核心執行時間（mock OCR，控制流程測量）

| 情境 | n | avg (ms) |
|---|---|---|
| 0 步驟（空規則） | 100 | 0.004 |
| 1 步驟 detect（mock 空結果） | 100 | 0.013 |
| 10 步驟（mock OCR） | 100 | 0.048 |

### 3.3 B. GUI lifecycle timing（fake window；**實際取消窗口未量測**）

> 腳本輸出對應標題：`Part B - GUI lifecycle timing (fake window; actual cancel window not measured)`

**機制說明**：本節以**假 `win` 替身**（Qt offscreen）驅動 `TestRunController`，
量的是「程式層呼叫的先後與耗時」，**不是**真實 GUI 上的可操作取消窗口。
本節的「訊號／插槽」是腳本內的 `_SignalBus` —— 一個**行程內同步 handler 清單**，
**不是**真實 Qt Signal/Slot，也不是 queued connection。正式程式用的是
`gui/06_gui_main.py:5053` 的 `pyqtSignal(dict)`（跨執行緒 queued connection）。
因此 Part B **沒有**真實 event loop 佇列延遲、也沒有真實輸入路由。

| 指標 | 快速規則（5 步驟，小 ROI） | 較慢規則（3× 中 ROI detect） | 精確語意 |
|---|---|---|---|
| n | 30 | 30 | — |
| `button_show_call_ms` | 0.013 | 0.016 | 測試開始 → `setVisible(True)` 呼叫返回的耗時。**非**「按鈕可見時間」 |
| `button_painted_to_hidden_ms` | N/A | N/A | **未量測**：假 win 無 QWidget paint 系統，無繪製事件可量 |
| `cancel_input_operable_ms` | N/A | N/A | **未量測**：假 win 無真實輸入管線，無訊息迴圈與輸入路由 |
| `signal_latency_ms` | 0.003 | 0.003 | **同步 Python handler list 的執行時間**。**不代表**正式 GUI 跨執行緒 Qt Signal/Slot 延遲 |
| `dry_avg`（Dry-run 時間） | 6.345 | 258.413 | **假視窗測試流程的耗時**，不等於真實使用者取消窗口 |
| `gui_release_avg`（GUI 釋放） | 4.256 | 4.356 | 假視窗流程的耗時 |
| `restore_avg`（恢復 UI） | 38.362 | 290.092 | **假視窗測試流程的耗時**，不等於真實使用者取消窗口 |

> **界線總結**：本節唯一可量的是「程式何時呼叫了 `setVisible(True)`」。
> 畫面是否已繪製、取消鈕是否真的可點擊，**在本環境下皆未量測（N/A）**。
> `dry_avg` 與 `restore_avg` 描述的是**假視窗流程**的耗時，
> **不可**被引用為「使用者實際可操作取消窗口」。
> `signal_latency_ms` 只是同步 handler list 的執行時間，
> **不可**當作真實 GUI 的跨執行緒訊號延遲。

### 3.4 C. 取消成功機率**推估**（依步驟邊界；對照假設人類反應時間）

> 腳本輸出對應標題：`Part C - Cancel-success probability ESTIMATE (execution time vs assumed human reaction time; NOT a user study, NOT a cancel-rate statistic)`

> **這是推估，不是量測**：
> - `can-cancel` 欄位由「規則執行時間」與「**假設的**人類反應時間（250／500／1000 ms）」對照推得，
>   **不是**實際使用者測試結果，也**不是**取消成功率的統計。
> - 判定僅為相對量級（不太可能／有可能），**不對應**任何實際成功率數字。
> - 單次 OCR 執行**期間**無法靠步驟邊界檢查立即中斷（見 §7.5）。
> - 實際取消結果仍取決於**步驟邊界**與 **GUI 事件派送**兩件事 —— 兩者本輪皆未在真實環境驗證。

| 規則 | n | p50 (ms) | p95 (ms) | 人類反應 250 ms | 500 ms | 1000 ms |
|---|---|---|---|---|---|---|
| 1 步驟 detect 小 ROI | 40 | 8.214 | 12.6 | 不太可能 | 不太可能 | 不太可能 |
| 3 步驟（detect 小 + click + key） | 40 | 8.435 | 14.227 | 不太可能 | 不太可能 | 不太可能 |
| 5 步驟 | 40 | 5.475 | 9.739 | 不太可能 | 不太可能 | 不太可能 |
| 10 步驟（含 sum 小 ROI） | 40 | 16.234 | 19.968 | 不太可能 | 不太可能 | 不太可能 |
| OCR 較重（3× 中 ROI detect） | 40 | 209.167 | 310.409 | 有可能 | 不太可能 | 不太可能 |

> 未納入 Part C 的「全圖 ROI detect」實測約 1.1 s（見 3.1），此類極長單一 OCR 步驟在推估上才讓人類有反應機會；但見 §7.5「單一耗時 OCR 步驟期間無法中斷」的限制。

---

## 4. GUI lifecycle 時序（假視窗；實際取消窗口未量測）

按下「測試」到 UI 恢復的**程式層呼叫**時序（假視窗，`capture_frame` 模擬即時）：

- 按下測試 → 取消按鈕 `setVisible(true)` 呼叫返回：**0.013 / 0.016 ms**（僅代表程式已呼叫 `setVisible(True)`，**非**「按鈕可見時間」）。
- → **畫面上可見（真實 paint 完成）**：**N/A** —— 假 win 無 QWidget paint 系統，無法量測。
- → **使用者真正可點擊**：**N/A** —— 假 win 無真實輸入管線（訊號／插槽為行程內同步 handler 清單），無法量測。
- → GUI 執行緒釋放（`on_test_rule()` 返回）：**4.256 / 4.356 ms**（假視窗流程耗時；不含實際擷取耗時）。
- → Worker 完成 dry-run：**6.345 / 258.413 ms**（**假視窗流程的執行時間量測**）。
- → UI 恢復：**38.362 / 290.092 ms**（假視窗流程耗時）。

**實際可操作取消窗口**：本輪**無法實測**（假 win 無 paint／輸入管線，兩項指標皆為 N/A，見 §2.3）。
本節量到的是**假視窗流程的耗時**：Dry-run 執行時間對一般規則約 **4~16 ms**
（10 步驟規則約 13~16 ms）；OCR 較重約 **340 ms**；全圖偵測約 **1.1 s**（見 §3.1）。
由於取消旗標只在「步驟之間」檢查（§7.5），真實可操作窗口的**上界**即 Dry-run 時間，
且實際會因真實擷取耗時而**更短**。這些數字**不是**實測的使用者可操作窗口。

> 「已設定 visible」與「使用者實際能點擊」的區別：在 `on_test_rule()` 內，`_set_test_running(True)` 與 `processEvents()` 之後、Worker 啟動之前，GUI 執行緒正在執行 `capture_frame()`，此期間取消按鈕雖已 `setVisible(True)` 但 GUI 執行緒被佔住。本輪以模擬即時擷取壓縮此間隙；實際環境下此間隙等於擷取耗時（pynput 模式固定額外有 ~200 ms 視窗最小化／激活等待）。

---

## 5. 冷啟動與暖啟動差異（OCR 引擎）

| 項目 | 耗時 (ms) |
|---|---|
| `init_engine()`（首次載入 OCR 引擎） | ~1179 |
| 第一次 `recognize()`（冷啟動，含引擎初始化，全圖 1920×1080） | ~1509 |
| 第二次 `recognize()`（暖啟動，全圖 1920×1080） | ~1142 |
| 小 ROI `recognize()`（暖，~200×100） | ~7 |
| 中 ROI `recognize()`（暖，~600×400） | ~60 |

冷啟動約需 **1.5 s** 才能完成第一次全圖辨識；暖起後全圖約 **1.1 s**、小 ROI 約 **7 ms**。Dry-run 屬「每次測試重複辨識」，絕大多數情況為暖起狀態，但首次測試會承受冷啟動開銷。

---

## 6. 真實 OCR 與 mock 測量的區分

- **真實 OCR（Part A 3.1）**：使用實際 RapidOCR 引擎於 `tests/data/test.png` 之 ROI 上辨識。耗時完全由 ROI 尺寸主導：小 ROI ~7 ms、中 ROI ~60 ms、全圖 ~1.1 s。這是產品的真實速度。
- **Mock OCR（Part A 3.2）**：`recognize` 被替換為回傳空列表，僅量測控制流程開銷。結果：**0.004~0.073 ms**，可視為極小，證實 dry-run 的規則引擎本身幾乎不耗時，所有顯著耗時皆來自 OCR／模板比對等外部操作，而非規則判斷邏輯。

兩者明顯分開呈現，未混為一談。
---

## 7. 取消成功機率分析

### 7.1 一般規則是否真的在毫秒級完成？
**是。** 對於使用小 ROI 偵測的典型規則（絕大多數使用者規則），`_run_dry_run` 中位數僅 **~5~6.5 ms**，10 步驟規則約 **~15 ms**。使用者實際操作時「幾乎來不及按下取消」的感覺是正確的。

### 7.2 主要耗時來源
**OCR 辨識**，且與 ROI 尺寸呈強正相關。規則引擎（比對、判斷、分派）開銷極小（mock 實測 <0.1 ms）。一個全圖偵測步驟（~1.1 s）的耗時已超過一般規則整體的數十倍。

### 7.3 取消按鈕可操作窗口

本輪**無法實測**真實可操作窗口（假 win 無 paint／輸入管線，見 §2.3）。
可量測的是**假視窗流程**的 Dry-run 執行時間：**一般規則 4~16 ms（10 步驟 13~16 ms），
OCR 較重約 340 ms，全圖偵測約 1.1 s**。
由於取消只在步驟邊界生效（§7.5），真實可操作窗口的**上界**即 Dry-run 時間，
且實際值會更短（真實擷取會佔用 GUI 執行緒）。上述數字**不等於**實測的使用者可操作窗口。

### 7.4 一般使用者是否有合理機會人工取消？（推估）
**對一般規則：沒有（此為推估，非實測）。** 人類正常反應時間約 **250 ms**（保守 500 ms），遠慢於一般 Dry-run 的 4~16 ms。依 §3.4 的推估，於 250/500/1000 ms 假設反應時間下，針對 1~10 步驟規則皆屬「不太可能」來得及取消；OCR 較重規則（p50 209 ms）落在 250 ms 反應的邊緣，屬「有可能」。只有全圖偵測這類 1.1 s 的單一長步驟，人類反應時間才明顯小於執行時間，才有合理機會。

> 再次強調：這是「執行時間 vs 假設反應時間」的**推估**，**不是**實際使用者測試，
> 也**不是**取消成功率統計。實際取消結果仍取決於**步驟邊界**與 **GUI 事件派送**。

### 7.5 單一耗時 OCR 步驟期間能否取消？
**不能。** 程式碼中取消旗標僅在「步驟之間」檢查（`for idx, step in enumerate(rule.steps): if cancel.is_set(): break`），**不會中斷進行中的單一 OCR**。因此即使一個偵測步驟耗時 1.1 s，使用者在其中點擊取消，也必須等到該 OCR 步驟結束、下一個步驟邊界才會生效。這意味著：單一長 OCR 步驟期間，取消按鈕在實務上無法中斷。

### 7.6 是否有必要保留目前 GUI 取消按鈕？
- **保留底層取消能力**（`_cancel_event` + 步驟邊界檢查）：程式碼成本極低，對極長測試（如全圖偵測）有防呆價值，建議保留。
- **GUI 取消按鈕**：對一般（毫秒級）規則，可操作窗口上界（Dry-run 時間）遠短於人類反應時間，幾乎無用；僅對極長測試有邊際價值。若要優化 UX，可考慮**僅在預估較長的測試時顯示取消操作**，或維持現狀（作為防呆，但不必將其視為核心 UX）。

### 7.7 是否有必要做任何程式碼修改？
本任務為 READ-ONLY，**未修改任何正式程式碼**。基於量測結果，若後續決定改善，值得考慮的（非本階段強制）：
1. 將取消旗標檢查細化到單一 OCR 步驟內部（若 OCR 引擎支援中斷），才能真正讓「取消」在長 OCR 期間生效；否則取消按鈕對單一長步驟仍無法即時中斷。
2. 維持現有「測試中…」狀態與測試按鈕停用（已有 `_is_testing` 守衛），避免重複測試。
3. 若欲精簡 UX，可評估是否讓取消按鈕僅在長時間測試時顯示，避免使用者對毫秒級測試抱錯誤預期。

---

## 8. 未能實際測量的項目及原因

| 項目 | 原因 |
|---|---|
| **按鈕已繪製到隱藏（`button_painted_to_hidden_ms`）** | **N/A：假 win 無 QWidget paint 系統**，沒有 QPainter 繪製事件可量。需真實 QWidget + 桌面環境才能量測。 |
| **使用者可操作窗口（`cancel_input_operable_ms`）** | **N/A：假 win 的訊號／插槽是行程內同步 handler 清單**（無 QObject／無 event loop／無 queued connection），無真實訊息迴圈與輸入路由。需真實視窗與真實點擊才能量測。 |
| **真實 GUI 跨執行緒訊號延遲** | 假 win 的 `_SignalBus` 在 worker 執行緒同步呼叫 handler，不經 event loop 佇列；`signal_latency_ms` 僅為環境參考，**不等於**真實 Qt queued connection 的分派延遲。 |
| 實際遊戲視窗的 `capture_frame` 耗時（mss／PrintWindow／pynput） | 本輪無真實目標遊戲視窗；Part B 已以模擬即時擷取進行，與實際擷取耗時分離。pynput 模式程式碼中固定有 `sleep(0.08)` + `sleep(0.12)` 視窗切換，即約 **200 ms** 固定開銷。 |
| 真實使用者反應時間 | 未實測真實人類；§7 僅以 250/500/1000 ms 做推估，並明確標示為非實測。 |
| **實際取消成功率** | 未實測。§3.4／§7.4 的 `can-cancel` 為「執行時間 vs 假設反應時間」的推估，非取消成功率統計。 |
| **單次 OCR 執行期間的中斷行為** | 取消旗標只在步驟之間檢查（§7.5），進行中的單一 OCR **不會**被打斷；此為程式碼語意推論，本輪未在真實環境驗證。 |
| **GUI 事件派送對取消結果的影響** | 假 win 的同步 handler list 不含真實 event loop 分派（§2.2），故派送延遲對取消結果的影響**未量測**。 |
| GUI 在真桌面環境（非 offscreen）下的「可見→可點擊」組合耗時 | Qt Offscreen 下無真實視窗焦點與佈局更新，實際可點擊時間會加上 `capture_frame` 與視窗系統回應。 |
| 全圖 ROI detect 的 Part C 取消機率 | Part C 未納入全圖規則；但其 1.1 s 執行時間已由 Part A 3.1 實測，可推論人類有反應機會（受限於 §7.5 步驟邊界限制）。 |

---

## 9. 結論建議

1. **一般規則 Dry-run 確實普遍在毫秒級完成**（中位數約 5~6 ms），使用者「來不及按下取消」屬事實。
2. **OCR 是唯一顯著耗時來源**，與 ROI 尺寸強相關；規則引擎本身極快。
3. **本輪無法實測真實可操作窗口**（假 win 無 paint／輸入管線，兩項指標皆為 N/A）。可量測的是**假視窗流程**的 Dry-run 時間（一般規則 4~16 ms、OCR 較重 ~340 ms、全圖 ~1.1 s），真實可操作窗口的上界即 Dry-run 時間，且實際更短。僅全圖／長 OCR 規則在**推估**上有合理取消機會，且受限於「僅在步驟之間檢查取消」無法中斷單一長 OCR。
   §7.4 的「能不能來得及取消」為**推估**，非實測成功率。
4. **建議保留底層取消機制**（程式碼成本低、極長測試有防呆價值），但 GUI 取消按鈕對絕大多數使用者幾乎無實際用途；可考慮僅在較長測試時顯示，或維持為防呆而非核心 UX。
5. 本階段未修改任何**正式產品程式碼**、未 commit、未 push；所有數據與腳本保留於 `devtools/benchmarks/`，供後續審查與決定是否修改程式碼。
