

## [Unreleased]

### 給使用者

- **介面術語統一為「圖片比對」**：原本同一個功能混用「模板比對／範本圖片／圖示辨識」多種說法，現全面統一——步驟類型叫「**圖片比對**」（match_image）、截下來的小圖就叫「圖片」、「修剪模板」按鈕更名「**修剪圖片**」。英日文同步（Template→Image、テンプレート→画像）。文字偵測裡的進階比對模式由「模板比對」更名「**文字樣式比對**」，不再與圖片比對撞名。功能行為完全不變；技術上它是以截圖特徵做相似度匹配，不是死板的像素全等比較。
- **修正 OCR 診斷信心度顯示**：結果列表的信心度欄位改為固定深色文字配淺色底，修正深色系統佈景下白字壓淡色背景、數值完全看不清楚的問題。
- **定位文案對齊實際使用場景**：工具的甜蜜點是「快速設定的小任務與重複操作代勞」，文件與介面文案同步調整——「後台掛機」改為「後台操控」、「三種掛機模式」改為「三種互動方式」、混合模式描述改以「低頻動作任務」呈現、群組循環模式說明改為「適合重複執行的流程」（不再暗示長時間無人值守）、省電模式說明改為「工具運作時還需要同時使用電腦」。功能本身不變；理論上仍可長時間執行，但需要較完整的規則涵蓋。
- **狀態列負載數字更好懂**：「CPU／系統」改為「**工具CPU**／**電腦CPU**」，一眼分清楚哪個是本工具、哪個是整台電腦（遊戲吃滿 CPU 不會算進工具）；「MEM」改為「記憶體」；滑鼠懸停說明同步補齊三個欄位的定義；高負載警告改為完整文字（如「⚠工具CPU偏高」），並支援英日介面。

## [v0.3.0] - 2026-08-23

### 給使用者

- **新增「混合模式」**：設定 → 自動化 / 辨識 → 互動方法 → 混合模式（後台偵測＋前景操作）。平時以後台截圖辨識、零干擾；偵測到需要操作時，短暫把遊戲帶到前景做物理點擊/按鍵，完成後自動復原你原本的前景視窗與滑鼠位置。適合不支援後台注入（Frida）的遊戲——例如遊戲只吃前景操控、正在自動戰鬥爬主線，只有過關時要手動點「下一關」：寫好規則後就能掛著去做別的事，畫面一出現「下一關」，工具自動切回去點擊並復原你原本的狀態。因每次操作會短暫搶焦點，較適合低頻動作的任務。
- **CPU 警告不再誤報**：警告原本量測「整台電腦」的 CPU（遊戲本身吃滿 80% 時工具會被連坐誤報），改為只量測本工具自身的使用率；狀態列同時顯示「工具 CPU」與「系統 CPU」兩個數字，一眼看出負載來源。
- **靜止畫面大幅省電**：畫面完全沒變時，文字辨識與圖示比對直接沿用上次結果（先前只有框選過偵測區的規則有此優化，現在未框選的全窗掃描與圖示比對也適用）。辨識結果與即時計算完全一致。
- **新增「省電模式」**：設定 → 一般 → 省電模式。限制 OCR 執行緒數以大幅降低 CPU 占用率，適合 CPU 較弱或需邊掛機邊使用電腦的情境；代價是單次辨識速度略慢。變更後立即生效（自動重置 OCR 引擎，免重啟）。
- **診斷面板的後台失敗彈窗改為測試語境**：點擊/按鍵測試在後台注入失敗時，不再跳出「執行中」語境的對話框（舊版會提到「請再按開始」「重新開始」）；新版文案說明此結果代表執行任務也會失敗，「切換到前景模式」按鈕只切設定、不會停止或重啟正在跑的任務。「以系統管理員重新啟動」入口保留。
- **文件與實際功能同步校正**：修正 README／快速上手指南（中英文）／文件網站與實際行為的落差——F8 全域熱鍵說明改為「啟動／停止，暫停中按 F8 為繼續」（F8 不會主動暫停）；OCR 診斷建立規則改述為「選取目標後按『建立為新文字規則』」（面板無雙擊操作）；任務匯出 JSON 說明改為「不含帳號等機密資料，但含目標視窗名稱、互動模式等任務資訊」；錄製操作補註「按下錄製時會自動把遊戲帶到前景，開始後零干擾」。

### 給開發者

- **混合模式（`interaction_mode: "hybrid"`）**：新增 `core/19_hybrid_input.py`（`focus_guard` context manager：save 前景 hwnd＋游標 → 激活 → 動作 → restore，模組鎖序列化並發）。主循環所有輸入分派條件由 `mode != "pynput"` 收斂為 `== "frida"`（hybrid 截圖走背景、輸入走前景物理），`_is_tool_foreground` 保護對 hybrid 保留（僅 frida 跳過）；`_activate_window` 加已前景 early-exit。任務匯入白名單（task_management/run_config）同步加入 hybrid。診斷面板點擊測試 hybrid 走 ClientToScreen 物理路徑＋focus_guard，驗證重拍放寬為非 pynput 皆可。
- **en rec 模型試升級 v5 後回滾至 v4**：曾換入 RapidAI 轉換的 `en_PP-OCRv5_rec_mobile.onnx`（合成測試快 30%、命中 200/200），但實戰遊戲畫面（hololive-Dreams，1413×825）三模型對照顯示 v5 en 對含標點/空格的長句嚴重退化——`'1 result(s) available to claim.'` 讀成 `'1reul(vaiabl '`（67-69%），v4 與 v5 cht 均全對（92-98%）；計數器類 v4 4/5、v5 en 5/5 但 v5 en 會插空格。合成字型基準（Hershey 短詞）未能暴露此弱點，實戰驗證才是準繩。`custom_models/` 維持 v4 不變，本次無發行物變更。
- **遷移至 Python 3.13 與 uv 管理**（commit `a6fcac6`）：`pyproject.toml` 改 `requires-python = ">=3.13,<3.14"` 並整合依賴宣告，`uv.lock` 為鎖定檔，`requirements.txt` 退役刪除。開發依賴由全域 `uv` 管理，先 `uv sync --dev`，日常命令（build / pytest / ruff）一律 `uv run ...` 執行；`build.py`、`release.ps1`、`run.bat` 同步改用 uv 啟動。
- **修正 run.bat 啟動**（commit `f767d4a`）：改用 `uv run python gui/06_gui_main.py --debug`，並在 `build.py` 隱藏導入 `logging.handlers` 補足 PyInstaller 靜態分析遺漏。
- **文件稽核與術語表**：逐條對照程式碼稽核使用者／開發者文件——移除官網無基準測試支持的 match_image「快 OCR 10~50 倍」量化宣稱；官網 match_image 步驟對齊現行 GUI（截取區域／修剪模板／框選搜尋區域，門檻預設 0.85）；START.en.md「右鍵新增群組/規則」修正為工具列「+ 群組」「+ 規則」（右鍵選單無此功能）；ARCHITECTURE/AGENTS 的 F8 描述同步修正；新增根目錄 `CONTEXT.md` 術語表作為日後文件用語的事實來源。

## [v0.2.9] - 2026-08-17

### 給使用者

- **安裝包瘦身**：移除打包時夾帶、但從未被使用的檔案（未參考的 OCR 偵測模型、OpenCV 影片編碼元件、AVIF 支援、dxcam 原始碼），安裝後佔用空間約減少 150 MB，下載更省時。
- **差異更新正式生效**：自本版起自動更新全面走「差異更新」——只下載真正變更的檔案；安裝在 v0.2.8 的使用者可直接套用，其餘版本自動退回整包下載。

### 給開發者

- **打包瘦身**（commit `33da4e9`）：build.py 新增 `slim_dist()`，於 build 後移除已實測確認為零使用的檔案——`custom_models/ch_PP-OCRv5_server_det.onnx`（84 MB，det 實際用 rapidocr 內建 v4 模型）、`cv2` 兩顆 ffmpeg DLL（54.6 MB，全專案無 `VideoCapture`/`VideoWriter`）、`PIL/_avif*`（7.5 MB，`AvifImagePlugin` 的 `_avif` import 有 `try/except ImportError` 保護）、`dxcam/processor/_numpy_kernels.{c,pyx}`（1.5 MB，打包夾帶的原始碼）。瘦身前後：dist 606 MB/1524 檔 → 458.5 MB/1518 檔。commit `21c3cf6` 修正 `pathlib.glob` 不支援花括號 pattern 導致的 dxcam 原始碼未移除。
- **差異更新首次生效**：`delta_info.json` base_version = 0.2.8，v0.2.8 使用者走 delta（`removed` 清單含本次 5 個瘦身檔），其餘自動退回整包。

## [v0.2.8] - 2026-08-17

### 給使用者

- **更新更快、更省流量**：自動更新改為「差異更新」——只下載自上一版以來真正變更的檔案（典型約 1~13 MB，取代原本整包 318 MB）。若差異更新不適用（例如跳過多個版本），會自動退回完整下載，安全網不變。

### 給開發者

- **差異更新（Delta Update）**：`core/12_updater.py` 新增 delta 純函式（`sha256_of_file` / `build_manifest` / `diff_manifests` / `apply_delta_to_staging` / `verify_tree`）與 `download_delta_update()`（`DeltaUpdateError` 判定「不適用／驗證失敗」時自動退回整包）；`UpdateInfo` 增 `delta_url` / `delta_base_version` / `delta_bytes`；`check_for_update()` 額外抓 `delta_info.json`（非致命，失敗不擋更新檢查）。`gui/06_gui_main.py` `_start_download` 有 delta_url 優先走 delta、失敗自動回退整包；`_UpdateInfoDialog` 顯示「差異更新約 X MB」提示。i18n 新增 `update.delta_size` / `update.fallback_full`。
- **發版工具**：新增 `make_delta.py`（`release.ps1` 於 build 後呼叫）產出 `ocr-trigger-clicker-delta.zip` + repo 根 `manifest.json` / `delta_info.json`；`release.ps1` 改為 commit 含 delta 判定檔、`gh release create` 附整包 + delta 兩 asset；base_version = 更新 `latest_version.txt` 前的舊版號。第一次發版／跳多版／delta 過大（> 整包 40%）→ 不產 delta。
- **測試**：新增 `tests/test_updater_delta.py` 6 項（diff 分類、staging 覆蓋/刪除/保留、payload 篡改偵測、整樹驗證損壞偵測、路徑穿越拒絕）；`core/12_updater.py` `demo()` 與 `make_delta.py --demo` 補 delta self-check。
- **文件**：AGENTS.md 發版流程與新增「差異更新」章節、ARCHITECTURE.md 新增「自動更新（差異更新）」章節與模組表更新、TECHNICAL.md Build & Packaging 補 delta 產物與大小比例。

## [v0.2.7] - 2026-08-17

### 給使用者

#### 新增
- **修剪模板**：圖示比對（match_image）步驟的範本截圖現在可以再次微調——按「修剪模板」，在彈出視窗中用**貼著圖片四邊的箭頭**把範本四周的空白／雜訊一格一格剪掉（一格 = 1px，也可直接輸入精確像素），剪到最準的範圍再比對，命中率更穩。同時移除幾乎沒人用的「選擇圖片」按鈕（外部圖片需求為零）。
- **F8 確認窗「切換模式並執行」**：按 F8 彈出的執行確認視窗新增一鍵「切換為前景／後台模式並執行」——不用先進設定改互動模式，直接在確認窗切換並開跑。
- **後台模式管理員提醒**：以非系統管理員啟動並使用後台模式時，會提醒「後台模式需以系統管理員啟動才能正常截圖」（每個 session 提醒一次，不阻斷）。

### 給開發者

- **模板修剪**（commits `253868f`、`1b6ea24`、`546da56`）：`core/11_template_matching.py` 新增 `crop_template_b64`（`MIN_TEMPLATE_SIDE=4`）與 margin 純幾何函式 `margins_from_rect`／`rect_from_margins`／`clamp_margins`（交叉限制 `left+right ≤ w−min`、idempotent）；`gui/15_template_crop.py` 新增 `trim_template_dialog()`——四邊空間化雙向箭頭按鈕（上／下橫排、左／右直排，箭頭指向圖片中心＝往內剪）＋底部精確數值行，`_CropView` 移除拖曳選框（非每位使用者都能一次框選正確）；`gui/06_gui_main.py` `_MatchImageStepForm` 移除「選擇圖片」按鈕與 `_pick_template`，新增「修剪模板」；i18n 刪 3 個無引用 key、加 `template_crop.*`。測試 `tests/test_template_crop.py` 11 項，全量 175 通過。
- **F8 切換模式並執行**（commit `27a0954`）：`gui/06_gui_main.py` 群組確認視窗依目前互動模式新增對應的切換按鈕，同步更新 config `interaction_mode` 與任務檔。
- **後台模式管理員提醒**（commit `ed6e054`）：啟動後台模式前以 `is_admin()` 檢查，非管理員以 `_admin_warned` 每 session 只提醒一次。
- **`_get_interaction_mode` 收斂**（commit `a9a5eb4`）：集中至 `core/run_config.py`，`gui/06_gui_main`／`09_ocr_debug`／`test_run_controller` 共用，並移除 6 個 i18n 孤兒 key。
- **測試補強**（commit `a3c6d48`）：`00_global_hotkey`、`10_performance_monitor` 補 `__main__` self-check。
- 清理與文件：移除過時 `.plan.md`、清理 `.gitignore` 註解與已刪本地分支、任務 JSON 同步、README 與首頁 SEO 加入星之救援者 StarSavior 關鍵字、frida 後台模式 Unity 支援宣稱修正。

## [v0.2.6] - 2026-08-14

### 給使用者

#### 新增
- **第一次啟動自動選擇語言**：未存過語言設定的全新安裝，啟動時依系統語言自動決定介面——中文系統用繁體中文、其他系統用英文；之後以設定內的選擇為準。

#### 修復
- **匯入舊版任務可能崩潰或跑錯**：修正匯入匯出跟上現行 schema 的三個落差——①失敗處理（on_fail）為「跳轉至規則」時，目標規則的 UUID 現在會正確重映射到新任務；②形狀正確的 `capture_size`（截圖尺寸）保留，不再被丟棄；③步驟參數不是物件格式時改為略過驗證，不再直接報錯中斷匯入。同時清理已不存在的舊欄位分支（wait_rule／collect_rounds／on_all_fail）。

#### 變更（文件）
- 官網「規則設計原則」改寫為口語化說明：修正「三個原則」→「四個原則」，移除 on_fail／notify 等技術詞，用語對齊 GUI（跳過本次／動作後延遲），並補上「跳過此規則」「按下按鍵後繼續」的例外說明。
- 官網「建立群組／新增規則」改為按工具列的「+ 群組」／「+ 規則」按鈕操作（右鍵選單並無此功能），OCR 診斷按鈕名稱對齊「建立為新文字規則」，功能清單補上「提示訊息」步驟。

### 給開發者

- **系統語系偵測**（`i18n/__init__.py` 新增 `detect_system_language()`）：以 Win32 `GetUserDefaultUILanguage()`（回退 `GetSystemDefaultUILanguage()`）讀取 LANGID，primary language `0x04`（中文）→ `zh_TW`、其餘（含偵測失敗）→ `en`；純函式 `_langid_to_code()` 可測（`tests/test_i18n.py`）。啟動時 config 無 `language` 才套用偵測值；`SettingsDialog._on_accept` 的 `old_lang` 改以 `get_language()` 為準，避免非中文使用者首次進設定未改語言卻誤彈重啟提示。
- **匯入匯出 schema 修正**（`core/task_management.py`，commit `c40bfb2`）：`_remap_ids` 把 on_fail `jump` 的目標 ID 一併重映射（涵蓋 detect／compare／match_image）；`preview_import_task` 僅在 `capture_size` 為長度 2 的 list 時保留；`_validate_rule_structure` 對非 dict 的 `params` 直接略過參數驗證。新增 5 個測試涵蓋上述路徑（`tests/test_task_management.py`）。

## [v0.2.5] - 2026-08-14

### 給使用者

#### 新增
- **English 語系自動改用英文 OCR 模型**：介面切到 English 後，文字偵測自動改用英文專用 OCR 模型，英文與數字的辨識準確度大幅提升；繁體中文介面維持原本的繁中模型。英文模型檔隨安裝包一同提供。

#### 修復
- **語系切換無法自動重啟**：修正設定內切換語言後不會自動重啟的問題（開發模式啟動讀取了錯誤位置的設定檔，導致切換判斷失效、沒有任何反應）。重啟流程改為更新器與主程式完全脫離、確保舊程式確實結束後再啟動新程式，關閉 console 視窗也不再影響；重啟過程會寫入系統暫存檔 `%TEMP%\ocr_relaunch.log` 方便排障。

#### 變更（文件）
- 官網導覽改版：功能卡片可點擊導引、嵌入 DailyMotion 示範影片、補上免責聲明。
- 跨解析度說明補正（同長寬比通用、來源解析度標註）、後台模式限制說明（視窗可遮蓋但不能最小化；StarSavior 僅支援前景）、OCR 語言能力敘述修正。

### 給開發者

- **英文 OCR 模型**（commit `68f762b`）：`core/02_ocr_engine.py::init_engine()` 依 `i18n.get_language()` 選模型——`en` 且 `custom_models/en_rec_mobile.onnx`＋`en_dict.txt` 存在時用英文模型，否則回退繁中。模型隨 release ZIP 分發（`custom_models/` gitignored）。
- **語系切換重啟修正**（commit `5a9f0bf`）：啟動語言統一讀 `get_data_path("config.json")`（不再依 frozen 讀專案根，消除 dev 模式寫 APPDATA／啟動讀專案根的不一致）；relaunch 以 `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`（附掛 `CREATE_BREAKAWAY_FROM_JOB`、OSError fallback 無旗標）啟動 `updater_main.py`；`Popen`／`_quit_app()` 包 try/except，結尾 `os._exit(0)` 並以 3 秒 watchdog 兜底；dev 重啟保留 `--debug`；`updater_main.py` relaunch 分支寫 `%TEMP%\ocr_relaunch.log`。

## [v0.2.4] - 2026-08-13

### 給使用者

#### 新增
- **錄製操作（示範錄製）**：按「錄製操作」按鈕或 F9 開始錄製，在目標視窗點擊示範一遍，停止後自動轉成規則並建立任務。每個錄製段（session）變成一個群組，可選擇建立新任務或併入既有任務。**只記錄滑鼠點擊**（左／右／中鍵），鍵盤按鍵、拖曳、滾輪不會被錄製——錄製時點擊盡量瞄準 UI 文字或圖示等有特徵的位置，轉換品質最好。
  - 點在文字上 → 轉成「偵測該文字後點擊」（等畫面出現再點，不怕視窗大小變化）
  - 點在無文字圖示上 → 嘗試轉成圖示比對（match_image）後點擊
  - 點在空白處或找不到特徵 → 固定等待後點擊
- **錄製時自動激活目標視窗**：開始錄製時自動把目標視窗帶到前景，不用手動切換。
- **轉換後清理錄製原始檔**：轉成規則後自動移除已用的錄製 session，避免累積佔空間。
- **偵測後延時**：OCR 辨識（`detect`）與圖示比對（`match_image`）步驟偵測成功後，可固定等待指定毫秒讓遊戲 UI 準備好，再執行下一步驟，避免畫面一出就瞬間點擊導致點空。新增偵測步驟時會依設定窗的「偵測後延時預設」自動填入；錄製轉換出的偵測規則也會套用。
- **任務記憶互動模式與視窗**：任務會記住上次成功執行用的互動模式（前景／後台）與目標視窗，切換任務時自動套用，不必每次重設；成功執行後也會以實際使用的視窗與模式校正綁定。
- **偵測效能優化**：每幀步驟 0 的偵測區域預聚類合併 OCR，加上跨幀內容快取，跑馬任務每幀 OCR 呼叫從 15 次降到 7~9 次（約 -44%），「偵測執行太慢」警告大幅減少。等價驗證：實境畫面逐位元比對 dropped==0、false_pos==0，精準度不變。

#### 變更
- **互動模式不符警告移除**：錄製轉換的規則不再因 `template_source`（模板來源）與互動模式不符而誤報警告，模板來源僅作為 metadata 留存。
- **錄製轉換套用設定窗預設**：轉出的規則自動套用設定窗的五個預設值（動作後延遲 `default_after_delay_ms`、點擊隨機偏移 `default_random_offset`、模糊比對門檻 `default_fuzzy_threshold`、模板比對門檻 `default_template_threshold`、顏色容差 `default_color_tolerance`），與手動新增動作步驟的行為一致。
- **OCR 診斷建立規則預設帶延時**：從 OCR 診斷一鍵建立規則／步驟時，偵測與動作步驟自動帶上「偵測後延時」「動作後延遲」預設（250ms），移除舊的 wait 步驟。

#### 修復
- **規則跳轉被推進邏輯覆蓋**：修正規則 `jump` 跳轉在「前一步已觸發動作」時被群組指標推進邏輯覆蓋，導致目標規則未執行的問題。

### 給開發者

- **滑鼠示範錄製器**：`core/19_recorder.py` 以 `WH_MOUSE_LL` 全域滑鼠攔截目標視窗內點擊，先截「動作前」畫面再以 SendInput（帶 magic `dwExtraInfo`）重送維持操控節奏；輸出 `session-YYYYMMDD-HHMMSS/`（`events.json` + `frames/*.jpg`）至 `%APPDATA%\ocr-trigger-clicker\recordings\`。停止後自動還原目標視窗。無 Qt 依賴，GUI 以 `load_sibling` 載入、callback 回報。
- **錄製 session → 規則轉換器**：`core/20_recorder_convert.py` 離線後處理，每個滑鼠事件一條規則：OCR 錨點（`detect` + `click(text_center)`）、模板錨點（`match_image` base64 內嵌 + `click`）、或 wait+click 純計時；座標一律視窗比例 0~1，session 轉成群組 `mode=once`。`convert_sessions(session_dirs, defaults=None)` 接受設定窗預設 dict（`fuzzy_threshold` / `template_threshold` / `color_tolerance` / `random_offset` / `after_delay_ms`），由 GUI `_convert_recording_to_task` 從 `RuleConfigController` 組出傳入；`None` 時回退模組內建常數維持既有行為。
- **GUI 整合**：`_record_btn` 工具列按鈕 + F9 全域熱鍵（`_on_hotkey` hid=2）開始/停止；`_convert_recording_to_task` 以 QInputDialog 選目標（新任務 / 既有任務，`list_tasks()`），併入既有任務時以 `save_task_with_groups` 合併；`_pending_merge_into` 與併發防護。
- **`template_source` 跨模式防呆移除**（commit `a075576`）：`gui/06_gui_main.py`、`gui/test_run_controller.py` 的來源比對邏輯全數拔除，i18n 對應 5 個 key 一併刪除；`_current_template_type` 保留寫入 metadata，引擎不再檢查。
- **任務記憶互動模式與視窗**（commits `74440e8`、`51ae316`）：`config.task_binding.<task>` 記錄最後成功執行的互動模式與視窗，切換任務時自動套用；成功執行後以實際使用值校正綁定。
- **偵測效能優化**（commit `b12e78f`）：`_prewarm_ocr_clusters()` 以 union-find 將步驟 0 的 detect/compare ROI 預聚類，每叢集 OCR 一次；`_ocr_crop` 跨幀內容快取（blake2b 指紋、LRU 64），standalone 與聯集路徑共用。回歸測試 `tests/test_ocr_precluster.py` 4 項全過，全套 158 測試綠燈。
- **config 路徑統一至 APPDATA**（commit `d10ceb7`）：dev 與 EXE 共用設定，支援一次性遷移。

## [v0.2.3] - 2026-08-11

### 給使用者

#### 新增
- **動作後延遲**：點擊／按鍵／拖曳／滾輪步驟成功送出後，可固定等待指定毫秒再執行下一步驟，取代「動作 + 等待」成對步驟。新增動作步驟時會依設定窗的預設值自動填入。
- **後台模式不再搶走焦點**：Frida 後台點擊／按鍵時會假造視窗焦點與游標位置，遊戲無法察覺焦點被拿走，可安心在後台操作。
- **OCR 診斷鍵盤測試可選按鍵**：鍵盤測試不再固定送 Esc，改為可從下拉選單選擇按鍵（預設 Space）。
- **互動模式不符警告一鍵切換**：當規則需要前景／後台模式但與目前設定不符時，警告訊息可直接一鍵切換模式並立即開始，不用再手動進設定。
- **啟動群組選擇記住上次**：每次啟動詢問執行哪些群組時，會記住上次的選擇並可直接跳過詢問。
- **啟動時自動展開執行日誌**：程式啟動後執行日誌區自動展開，方便直接確認執行狀態。
- **通知動作的預設訊息**：`on_fail notify` 訊息留空時，會自動顯示觸發的規則與停止的群組名稱，不再顯示空白通知。

#### 變更
- **群組列表執行模式改為彩色徽章**：規則樹的群組名稱前的 `[1]/[N]/[∞]` 文字標記改為彩色圓形徽章（藍「1」執行一次、橙「N」重複 N 次、綠「↻」循環、灰點停用），名稱更乾淨、執行模式仍可一眼分辨；僅並行群組保留「∥」前綴，其餘資訊移至滑鼠懸停提示。
- **群組切換與排序按鈕放大**：群組列的啟用／上移／下移按鈕加大，較易點擊。

#### 修復
- **前景點擊復原功能移除**：原本前景點擊後嘗試自動復原滑鼠位置的機制，因實戰測試不達標（復原時機錯亂造成誤點風險）而移除，回到單純的點擊行為。
- **on_fail 使用鍵盤動作的穩定性**：on_fail 為鍵盤動作時補上 CPS 與前景限制的防護，避免連發或背景狀態下送出異常；`skip_to` 裸數字收斂為安全解析。
- **診斷頁建立規則預設步驟**：從 OCR 診斷頁一鍵建立規則時，預設步驟改為「辨識 → 等待 → 點擊」。
- **測試預覽資訊補齊**：動作測試預覽現在會顯示動作後延遲與長按時間。
- **主視窗啟動置中**：主視窗啟動首次顯示時置中螢幕，不再偏離。
- **啟動群組對話框移除深色主題**：啟動群組選擇對話框不再使用寫死的深色樣式，跟隨系統外觀。

### 給開發者

- **`after_delay_ms` 實作於單一 choke point**：動作步驟（click/key/drag/scroll）成功後回 `continue` 且 `ms>0` 時用中斷式等待（暫停／停止立即中止），尾隨步驟不執行；與 scroll 的 `delay_ms`（滾輪格間延遲）語意不同，不影響 `fail_duration_sec` 容忍邏輯。
- **Frida 假造焦點與 SetCursorPos 攔截**：`core/18_frida_bg.py` hook `GetForegroundWindow`/`GetActiveWindow`/`GetFocus` 與 `SetCursorPos`，在點擊／按鍵 spoof 期間遮罩呼叫，re-attach 自動重試；keep-active 方案（過濾失焦訊息）實測後撤銷。
- **群組徽章為純繪圖函式**：`_make_mode_icon` 沿用 `_make_circle_icon` 的 QPainter 自繪風格（16px、Antialiasing），停用群組與規則列的「灰點」視覺語言一致；`_group_tooltip` 彙整模式／次數／間隔／並行摘要。
- **啟動群組選擇**：上次選擇以 `config.group_selection.<task>` 記錄，`skip` 旗標可跳過詢問。
- **on_fail=key 加 guard**：`core/05_main_loop.py` 對 on_fail 鍵盤動作補 CPS 上限與前景模式檢查，`skip_to` 裸 int 統一收斂為 `_as_int`。
- **設定窗新增「動作後延遲預設值」**：新增動作步驟時自動預填，欄位語意見 `after_delay_ms` 設計註記。

## [v0.2.2] - 2026-08-09

### 給使用者

#### 新增
- **Frida 後台模式支援鍵盤按鍵**：後台（Frida）模式現在除了點擊，也能送出鍵盤按鍵（例如 Enter）。按下會刻意持窗 120ms，讓以 60Hz 輪詢鍵盤狀態的遊戲也能偵測到；可列印字元會補送 `WM_CHAR`。
- **後台點擊後自動驗證**：診斷頁「點擊測試」送出後會自動再拍目標區塊並以 OCR 確認文字是否消失，結果按「遊戲有反應 / 沒反應 / 後台注入失敗」分流解說；執行期後台點擊失敗也改為白話提示並節流（30 秒內只提示一次），讓使用者分辨「工具問題」與「遊戲限制」。
- **鍵盤測試**：診斷頁新增「鍵盤測試」按鈕（送出 Esc）。後台模式直接後台送出並自動比對送出前後畫面——相似度 ≥90%（畫面幾乎沒動）時提醒「後台鍵盤可能被阻擋或該遊戲不支援後台鍵盤」，建議切回前景模式測試；前景模式則會先將目標帶到前景再送出。tooltip 會提醒在「靜態畫面」下測試，避免動態畫面誤判。
- **驗證結果單行速覽**：點擊 / 鍵盤驗證的結論改用單行速覽列顯示，點開才有完整說明與可複製的除錯資訊，不再壓縮截圖空間；15 秒後自動隱藏。

#### 變更
- **移除後台 PostMessage 互動模式**：後台模式保留「前景」與「後台 Frida 注入」兩種模式。PostMessage 不移動游標，多數 Unity 遊戲（如 BrownDust II）讀取 OS 游標位置而非 `WM_LBUTTONDOWN` 的 lParam、點擊必然錯位，故淘汰；既有設定 `interaction_mode: "postmessage"` 會自動遷移為 pynput。
- **後台模式 tooltip 強化並分行**：互動方法設定說明補上「若遊戲不響應按鍵，屬遊戲限制（部分遊戲需視窗焦點才能接收鍵盤輸入），非工具問題」，並以換行分行避免過長單行。

#### 修復
- **修復後台模式框選偵測區域/選取點擊座標時 app 無訊息直接關閉**：64 位元 ctypes handle 截斷導致 `GetDIBits` 對無效 handle 寫入記憶體（access violation）。
- **修復後台模板擷取時 app 無訊息直接關閉**：PyQt6 舊式 enum 在 `paintEvent` 執行期觸發 `AttributeError`，未捕捉例外會直接終止程序。
- **後台模板擷取修正比對尺度**：改為前景全螢幕框選並自動寫入 `capture_size`，後台比對尺度不再失準。
- **新增防護**：程式原生崩潰或未捕捉例外不再無聲無息，會寫入 log 並提示使用者。

### 給開發者

- **後台鍵盤維持基礎實作**：曾嘗試改走 `GetRawInputBuffer` 注入合成 RAWKEYBOARD 以支援 Unity raw input 路徑，實測後撤銷（遊戲不響應按鍵屬遊戲限制，部分遊戲需視窗焦點才能接收鍵盤輸入），維持 hook 鍵盤狀態（`GetKeyState`/`GetAsyncKeyState`/`GetKeyboardState`，僅覆寫注入中的 vk，其餘 pass-through）+ PostMessage 方案；補強含 120ms 持窗、`WM_CHAR`、`WM_SYSKEY`、hold re-arm 0.5s 防重複按。
- **移除 `SettingsDialog` 的 `interaction_mode` 遷移覆寫**：不再將過時值（`sendinput`/`postmessage`）自動覆寫為 pynput，保留 `core/16_bg_input.py` 的 `set_method` 兜底防護（手動 config 錯值時安全降級，不崩潰）。
- **後台 ROI / 點擊 / 模板選取統一走前景 selector**：`07_gui_roi`、`13_gui_click_picker`、`14_capture_region`，刪除 `gui/18_bg_click_picker.py` 與 `gui/17_bg_roi_selector.py`。已實測前景（mss）模板與後台執行截圖（PrintWindow）比對一致（BrownDust II 前對比對信心全數 1.0）。
- 移除診斷工具 `tools/diag_frida_keyboard.py`：為單一遊戲後台鍵盤調試而建，已完成使命，回歸通用定位。
- 新增防禦：進入點啟用 `faulthandler` + 自訂 `sys.excepthook`；`core/15_print_window.py`、`core/01_screenshot.py` 改用隔離的 `ctypes.WinDLL` 並設定 `argtypes`/`restype`。

## [v0.2.1] - 2026-08-07

### 給使用者

#### 新增
- **跳轉規則下拉選單依群組分類**：規則多的任務中，跳轉目標以「群組 › 規則」分組呈現，更容易找到

#### 變更
- **步驟摘要顯示非預設重要欄位**：規則列表現在會顯示右鍵點擊、按住時間、色彩比對容差等非預設設定，一眼看出動作差異（預設值仍保持簡潔不顯示）
- **步驟驗證改非阻擋**：儲存時不再攔截未完成的規則，改為執行到才提示，避免編輯途中卡住；並修復自動儲存偶發遺失

#### 修復
- **日誌檢視器移除層級過濾下拉選單**（全部/INFO+/DEBUG+）：過濾與「啟用詳細日誌」開關功能重疊，且清除日誌後低於門檻的新日誌不會觸發刷新（畫面定格）。移除後清除日誌後任何新內容必定刷新，介面更簡單。
- **日誌檢視器關閉後重開不再刷新**：`closeEvent` 停止刷新 timer 後，重開（`show`）未重新啟動，導致執行主循環後新日誌不顯示。新增 `showEvent` 於每次顯示時重新啟動 timer 並立即刷新。
- **移除日誌檢視器「啟用詳細日誌」checkbox**：審計後主循環診斷（效能警告、`[exec]` 逐步執行記錄）與所有失敗路徑（截圖/輸入/OCR/熱鍵/更新/模板）皆為 INFO/WARNING/ERROR，一般使用者預設即可完整看到；checkbox 只額外顯示規則存讀/GUI 編輯等開發者內部訊息，對使用者除錯無幫助。開發者仍可 `--debug` 啟動旗標（`python gui/06_gui_main.py --debug`）取回這些 DEBUG 診斷。
- **英文介面翻譯修正**：步驟編輯列表的步驟名稱、狀態列的互動模式標籤改用 i18n 翻譯，英文介面不再顯示中文
- **慢循環警告白話化並加節流**：高載警告改為通俗用語並限制頻率，避免通知刷屏

### 給開發者

- **移除 on_fail「retry」死碼**：步驟摘要與規則標籤移除已不存在的 retry 動作分支與對應 i18n key
- **移除 debug 群組 dump / 減少儲存日誌刷屏**：規則切換與勾選不再輸出除錯資訊，儲存 debug 日誌降噪
- **config.json 移出版本控制**：加入 `.gitignore`，本機設定不再進 git
- 文件：ARCHITECTURE.md 精簡 config 表、index.html 任務區通用化、任務 JSON 同步流程改為僅上傳 JSON

## [v0.2.0] - 2026-08-05

### 給使用者

#### 新增
- **並行群組加速**：群組模式設為「並行」時，`match_image` 找圖計算改由多執行緒平行處理，大型並行群組（如固定事件 21 條模板）掃描明顯加快（實測快約 2 倍）
- **重疊 OCR 區域合併**：同幀大量重疊的「偵測」規則（如跑馬對話叢集）合併共用單次辨識，掃描更順暢
- **日誌檢視器「清除日誌」按鈕**：一鍵清空 app.log 與 startup_error.log，方便乾淨起跑抓問題
- **設定新增「CPU/記憶體高載彈出通知」開關**：關閉後，系統高負載提醒只顯示在狀態列、不再彈出氣泡通知

#### 變更
- **動作日誌降噪**：同一動作（按鍵/點擊等）每秒最多記錄一筆，高頻操作不再洗版
- 狀態列效能顯示「FPS」改名為「掃描/秒」，語意更精確，並新增懸停說明

#### 修復
- 修復停止任務時偶發報錯「主循環異常: cannot schedule new futures after shutdown」（並行預算執行緒池在停止時的競態）
- 日誌檢視器清除日誌後畫面立即刷新
- 執行日誌在 OCR 合併後顯示「共用快取」標記，取代易誤導的 0ms

### 給開發者

#### 效能與架構
- **並行預算**：`_run_parallel_group` 以 `ThreadPoolExecutor`（惰性建池，`max_workers=min(8, cpu)`）平行化各規則首個 `match_image` 的 `_prematch_pure` 計算，行為與循序路徑語意等價（`tests/test_prematch_equiv.py` 全幀驗證）
- **共享預算修正**：`capture_size` / `chrome` / `current_size` / `roi` 改由主執行緒計算一次傳給 worker，消除每 worker 重複讀檔 / Win32 呼叫的 I/O（實測 N=21：退化版慢 4 倍 → 改良版快 2 倍）
- **prematch pool 生命週期**：`shutdown()` 自 `stop()`（GUI 執行緒）移至 `_loop` 的 `finally`（擁有者執行緒），消除「shutdown 後 submit」競態崩潰；`pool.submit` 加 `RuntimeError` 防禦，未來即使外部 shutdown 也只退回循序匹配
- **OCR 合併**：`_ocr_region` 對同幀重疊 ROI 合併（superset 重用 / overlap union），重疊偵測規則由 N 次 OCR 降為 1 次；執行日誌以「共用快取」標記取代誤導 0ms
- **inline 模板解碼 LRU 快取**：`_decode_template()`（`maxsize=64`）讓大型並行群組免每幀重複解碼（實測每幀省約 4~5ms / 11~13%），並提供 `clear_template_cache()` 供測試與模板重載
- **`_log` 滑動窗速率限制**：每 dedup_key 每秒一筆，純丟棄不累計，無 pending 遺失 bug
- **資源警告拆分**：新增 `on_resource_warning` 獨立回呼，`notify_resource_warn` 設定控制是否彈氣泡（狀態列照舊）

#### 測試
- 新增 `tests/test_ocr_merge.py`、`tests/test_template_cache.py`、`tests/test_prematch_equiv.py`；`tests/data/` 收錄 3 張實境偵測圖作為 OCR / 模板穩定性回歸基準
- `tests/test_main_loop.py` 擴充：執行日誌共用快取標記、滑動窗速率限制
- 修復 `test_log_sliding_window_rate_limit` 在 pytest 環境下失敗（補 `setLevel(INFO)`，與 standalone self-check 對齊）

#### 文件
- README / START / 網站 FAQ / TECHNICAL.md：補後台模式 Unity 底層限制與後台黑畫面系統管理員解法
- TECHNICAL.md：並行預算現況與命中率切換草案
- ARCHITECTURE.md / project-context SKILL：模組表與行號反映 OCR 合併 + 模板快取變更

#### 相依套件
- 無新增（沿用現有 pynput / dxcam / RapidOCR）

## [v0.1.9] - 2026-08-03

### 新增
- **後台操控功能**：新增兩種互動方法（前景 pynput / 後台 PostMessage），用戶可在偏好設定中選擇
- `core/16_bg_input.py` — 後台互動模組，支援 PostMessage、pynput 兩種方法
- `core/01_screenshot.py` 新增 `activate_window_bg()` — 用 WM_ACTIVATE 喚醒視窗（不偷焦點）
- 偏好設定新增「互動方法」下拉選單，支援切換前景/後台模式
- 狀態列顯示當前互動方法（前景/後台 PM）
- 主循環根據互動方法自動選擇對應的點擊/按鍵/喚醒邏輯
- **GUI 全面後台化**：選擇後台模式時，所有 GUI 操作在後台完成，不切換視窗
  - `gui/17_bg_roi_selector.py` — 後台偵測區域選取器（PrintWindow 截圖 + QLabel）
  - `gui/18_bg_click_picker.py` — 後台座標選取器（PrintWindow 截圖 + QLabel）
  - 截圖/測試/點擊/框選/座標選取均已支援後台模式
- `click` 步驟新增 **目前游標位置** 目標（`target: cursor`）：不需設定座標，直接點擊
  - 前景模式點擊目前滑鼠游標位置（動作遊戲左鍵普攻適用）
  - 後台模式（PostMessage）點擊目標視窗正中心
  - 新增 `hold_ms` 按住毫秒（0=立即點擊），與 `key` 步驟的按住行為一致
- match_image 模板標記**來源互動模式**（`template_source`：foreground/background），並持久化於任務 JSON，匯入匯出自動攜帶
  - 建立模板（截取區域 / OCR 診斷建模板）時自動記錄目前模式；舊任務無此欄位一律視為**前景**（此版本前無後台模式）
  - **圖片比對 / 測試按鈕**：模板來源與目前互動模式不符時，**靜默**在結果／測試日誌顯示橘色警告（測試為模擬預覽，不彈窗）
  - **啟動任務前防呆**（唯一彈窗）：掃描所選群組內所有 match_image 步驟，發現模式不符時警告（告知目前模式、逐條列出不符模板），可選擇「仍要執行」或「取消」
- `_pick_template`（從檔案挑圖）來源標記為未知（視為前景）
- **後台截圖全黑偵測**：部分遊戲（如鳴潮）在非系統管理員權限下 PrintWindow 回傳全黑畫面
  - `core/15_print_window.py` 新增 `is_admin()` / `is_black_capture()`（全像素為零才命中，暗色遊戲不誤判）
  - **OCR 診斷 / 測試 / 圖片比對按鈕**：後台截圖全黑 + 非系統管理員 → 靜默在資訊列／結果／日誌顯示提醒
  - **啟動任務前**：後台模式先截測試幀，全黑 + 非系統管理員 → 彈窗提醒以系統管理員重啟（可仍要執行/取消）

### 技術說明
- 後台模式透過 PrintWindow 截圖 + PostMessage 點擊實現
- Unity 遊戲不支援 PostMessage，需使用前景模式
- 其他遊戲可嘗試後台模式，用戶需自行測試
- 預設值 = `foreground`，不改變現有行為
- 後台模式下 ROI/座標選取改用 GUI 內嵌截圖，不使用全螢幕 overlay
- 後台模式完整支援：截圖、測試、點擊、拖曳、滾動、按鍵（含 hold）、框選、座標選取

### 修復
- 後台模式（PostMessage）啟動後，click/key/scroll/drag 不再被「工具處於前景」保護誤擋（`_is_tool_foreground` 對後台模式直接回傳 False，前景模式行為不變）
- 修復 `_activate_window()` 前景模式無限遞迴 bug
- 修復測試按鈕在後台模式下仍切換視窗問題（test_run_controller、09_ocr_debug、06_gui_main）
- 修復 `_send_scroll()` 未支援後台模式
- 修復 `_handle_key(hold_ms)` 繞過後台輸入問題
- 修復 `_handle_drag()` 未支援後台模式
- 修復 OCR 診斷 `RuleConfigController(None)` crash

### 日誌系統整合
- 執行事件統一寫入 `app.log`（`[exec]` 結構化行），移除無消費者的 `triggers.jsonl` 及舊檔清理
- 「📂 日誌」按鈕改為開啟 **日誌檢視器**（LogViewer，`gui/12_log_viewer.py`）：tail app.log、層級過濾、關鍵字搜尋、DEBUG 即時切換、開啟資料夾
- 新增 `set_debug()` / `is_debug_enabled()` 雙向切換，`--debug` 啟動旗標行為不變
- 循環開始/停止等生命週期事件層級從 DEBUG 提升為 INFO（關閉 DEBUG 時仍可見）
- LogViewer 關閉時停止定時刷新，並同步目前 debug 狀態
- **LogViewer 捲動修正**：內容未變時不重繪，向上瀏覽歷史不再被自動拉回底部（`_FOLLOW_TOLERANCE=20`）
- **日誌降噪**：移除高頻成功路徑 `_log`（detect 匹配文字、match_image 模板匹配成功、compare 比較成立、wait 等待開始/完成；保留等待中斷）
- GUI 保存/選取/背景切換等操作日誌從 INFO 降為 DEBUG，移除 `_on_rules_reordered` 的 WARNING 除錯殘留
- **異常排障**：背景/規則/並行/主循環異常改寫入完整 traceback（`_logger.exception()`）
- **循環停止統計**：`PerformanceMonitor` 新增 `_total_clicks` 計數，停止時輸出「執行 X 秒，點擊 X 次，規則 X 條」

### 文件
- 說明「依序執行」時什麼算觸發：只有實體動作步驟（點擊/按鍵/拖曳/滾輪）或 on_fail advance 才算完成推進；僅「通知(notify)」不會推進、會一直重複通知（docs/index.html FAQ 與規則設計原則同步更新）

### 變更
- 啟動/停止/繼續按鈕文字統一標示 [F8]（啟動[F8]/停止[F8]/繼續[F8]），提示 F8 為開始/暫停/停止全域快捷鍵（zh_TW/en）
- 「群組選擇」對話框 OK 鈕改用專屬 key `dialog.group_ok`（開始執行 / Start），與 `main.start` 脫鉤，移除誤導的 [F8] 提示
- 淘汰簡體中文支援：移除 `i18n/zh_CN.json`、`README.zh-CN.md`，並從設定視窗語言下拉刪除簡體選項；今後僅維護繁體中文（zh_TW）與英文（en）。舊 `config.json` 若殘留 `zh_CN` 值會由 `set_language()` 自動 fallback 繁中

## [v0.1.8] - 2026-07-31

### 新增
- 規則列表新增**一鍵啟動/取消**按鈕，批量切換所有群組啟用狀態（i18n zh_TW/zh_CN/en）
- 偵測/比較步驟全圖 OCR 時發出**效能警告**，執行日誌面板顯示實際耗時，建議框選 ROI 提升速度
- 測試按鈕失敗時顯示**實際相似度**，幫助使用者理解匹配差距（OCR fuzzy 顯示相似度 %，模板比對顯示最高 %）

### 修復
- 切換任務後群組收起狀態正確保留，不再自動展開第一個群組
- 群組展開/收起時的視覺殘影消除，UI 過渡更流暢
- `_DetectStepForm` 補上遺漏的 `self._list` 賦值，修復框選偵測區域時 crash
- 迴圈停止時執行日誌最終 flush，解決成功步驟不顯示的問題
- 管理員權限從預設改為僅除錯建議
- 三處 slice 入口補 `int()` 防禦，排除 float ROI 繞過轉換造成切片 crash
- OCR 診斷頁面耗時 ms 取整數
- 全圖 OCR `max_side_len` 從 480 改為 720，提高偵測精度；還原 ROI 分支 `max_side_len=0`
- `.gitignore` 放行 `docs/tasks/` 讓任務 JSON 可被網站下載
- `app.log` backupCount 7→1，`startup_error.log` 改覆蓋模式

### 文件
- 全新視覺設計 index.html — 漸層 Hero、Sticky Nav、Card Grid、FAQ Accordion
- 優化三個語言版本 README 視覺排版
- 開發者文件移入 `docs/dev/`，新增快速上手指南 START.md
- 記錄 max_side_len 精度陷阱到 TECHNICAL.md
- 清除 README 與網站中 AHK/AutoHotkey 殘留提及
- 修復 CHANGELOG.md 舊版本中文亂碼
- 刪除已完成的 PLAN_optimizations.md 與 UI_OPTIMIZATION_PLAN.md

## [v0.1.7] - 2026-07-29

### 變更
- 輸入模擬從 AutoHotkey v2（TCP socket + 外部行程）完全替換為 **pynput**（`SendInput`，in-process），刪除 `core/03_ahk_socket.py`、`clicker.ahk`、AHK 下載與初始化流程
- 截圖備援鏈從「mss → GDI」強化為「**mss → dxcam (DXGI) → GDI**」，dxcam 作為 mss 與 GDI 間的中間層，相容性更高
- 移除 8 組 AHK 相關 i18n key（三語言同步），i18n 總 keys 減至 611

### 新增
- `core/03_pynput_input.py` — pynput 輸入模組（10 個公開函式 + 8 項自檢測試）
- `core/box_utils.py` — 座標工具集，10 個純函式（`roi_center`、`roi_to_pixels`、`roi_crop`、`roi_sanitize` 等 + 17 項自檢測試）
- `core/01_screenshot.py` 新增 `_capture_dxcam()` + `--check` 自動自檢

### 移除
- `core/03_ahk_socket.py`（461 行 AHK TCP 伺服器）
- `clicker.ahk`（AHK 腳本）

### 修復
- 主視窗最大化後進行測試、框選區域、點擊選取、OCR 診斷等操作後不再還原為視窗模式，保留最大化狀態（7 處統一修復）

### 相依套件
- 新增 `pynput>=1.7`（取代 AutoHotkey）
- 新增 `dxcam>=0.3`（DXGI 截圖備援）

## [v0.1.6] - 2026-07-28

### 修復
- 語言切換 bug：`__main__` 語言讀取路徑改用與 `MainWindow._config_path` 一致的路徑邏輯（`_bundle_root()` / `_is_frozen()` / `get_data_path()`），避免 dev 模式與 frozen 模式讀到不同位置

### 變更
- 執行日誌摘要文字改進：`StepContext.on_fail_fired` 旗標、detail 顯示 `{fail_name}失敗，使用「{key}」`、前進→強制前進、空設定顯示明確訊息
- `_STEP_TYPE_NAMES` 靜態 dict 移除，統一用 i18n key 查表

### 新增
- 執行日誌全三語 i18n：core 層 `StepResult("stop", detail=...)` 33 條字串全部改用 `T()`，GUI `_RESULT_LABELS` 改為 `_RESULT_KEYS` 並在 `_populate` 執行期以 `T()` 解析，新增 44 組 i18n key（步驟類型、結果標籤、捲動方向、靜態與參數化細節）至 zh_TW/zh_CN/en

## [v0.1.5] - 2026-07-26

### 新增
- 任務分享按鈕改為 QMenu 下拉式（「開啟任務資料夾」+「前往網站」），加入 🌐 圖示
- 發現新版本時彈出更新資訊對話框，含 release notes + 自動更新／前往 Release 頁面按鈕
- 設定可自訂「等待」步驟的預設毫秒數 (default_wait_ms)
- 規則列表每條規則顯示總結標籤（步驟數、有失敗處理、有重試容忍、空白）
- 閒置時狀態列顯示真實 CPU／記憶體數據（背景 PerformanceMonitor 持續取樣）
- 模板比對（regex）模式提供「快速插入」輔助工具列：[數字][英文][任意][空白]
- 失敗處理、點擊目標、群組模式三組下拉選項全部加入 tooltip（懸停說明）
- `updater_main.py` 加入 `--demo` 自檢測試，無需發版即可驗證取代邏輯

### 變更
- 路徑邏輯集中至 `core/_paths.py`（`get_data_path` / `get_resource_path` / `_appdata_path`），取代 10+ 檔案中的內聯路徑
- `build.py` py_datas 改為 glob 自動掃描 `core/` 與 `gui/` 下所有 `*.py`，不再手動維護
- 任務目錄統一使用 `%APPDATA%\ocr-trigger-clicker\tasks\`，不再區分 dev/frozen 模式
- 比對模式命名調整：模糊比對（fuzzy）→ 近似比對；模板比對（regex）→ 模板比對；summary／combo 相關標籤同步更新
- 步驟摘要改進：內嵌→截圖、on_fail 顯示全稱、fuzzy 模式永遠顯示 `[近似比對]`、fail_duration 改為「持續N秒後」格式
- 規則列表總結標籤從 column 0 移至 column 1 靠右顯示，resize mode 改為 ResizeToContents

### 修復
- 自動更新機制全面重寫：暫存目錄改為 `%TEMP%`，取代改為逐檔複製 (copy2) + 每檔 retry 3 次 + 整包 retry 3 次 + rollback 強化
- 移除 `ocr-trigger-clicker_new` 目錄模式（不再在 app 目錄內解壓縮）
- 規則列表總結標籤在選取、啟用切換、儲存、更新狀態 4 個操作後被覆蓋消失
- 常駐監控 👁 符號在儲存規則後被覆蓋消失
- 持續失敗時長（fail_duration_sec）在步驟摘要中的格式易讀性
- OCR 診斷規則/步驟改用設定值取代寫死參數（bd6bffc）
- test 結果與步驟表單用語統一「內嵌」→「截圖」（44041a4）
- release.ps1 tag push 失敗時自動刪除 local tag rollback（87a86fe）

## [v0.1.1] - 2026-07-22

### ⚠️ 重要公告：打包格式變更

此版本從 `--onefile`（單一 exe）遷移至 `--onedir`（目錄結構），以消除運行時動態解壓縮帶來的穩定性問題，冷啟動速度從 6.81 秒降至 **1 秒內**。

### 🔴 強烈建議：本次請手動下載

由於本次為打包格式首次轉換，自動更新可能發生錯誤。**所有使用者（無論新舊版本）** 請至 [GitHub Releases](https://github.com/Sid-1996/ocr-trigger-clicker/releases/latest) 手動下載 `ocr-trigger-clicker.zip`。

使用方式：
1. 下載 `ocr-trigger-clicker.zip`
2. 解壓縮至任意目錄
3. 執行 `ocr-trigger-clicker.exe`

**舊版本可直接刪除**，不影響設定檔與規則（儲存於 `%APPDATA%\ocr-trigger-clicker\`）。

### 新增
- 自動更新支援 onedir 結構：`updater.exe --mode=update` 改為整包目錄取代，含備份 + rollback 還原機制
- `_UpdaterParser` MessageBox 防呆：直接雙擊 `updater.exe` 時跳出提示對話框
- `apply_update()` 對 onedir 路徑改為自動啟動新版 `updater.exe` 做目錄取代

### 變更
- 切換為 `--onedir` 打包模式，徹底消除運行時動態解壓縮帶來的穩定性問題
- 冷啟動速度從 6.81 秒大幅提升至 **1 秒內**
- 語言切換重啟改為外部 relauncher（`updater.exe --mode=relaunch`），解決 PyInstaller bootloader 競爭問題
- 移除 `updater_main.py` 中 onefile 時代的參數（`--old`、`--new`、`--pid`、`--log`）與重試邏輯
- 移除已棄用的 `--mode=migrate` 相關程式碼
- `gui/06_gui_main.py` relaunch 呼叫移除除錯用 `--log` 參數

### 技術細節
- `updater.exe` 維持 `--onefile` 打包，不依賴 `_internal/`，確保可獨立執行且原始 exe 不被鎖定
- 更新流程：下載 ZIP → 偵測 `_internal/` → 解壓到 sibling 目錄 → 啟動新版 `updater.exe` → 備份舊目錄 → rename 取代 → 啟動新版
- 失敗還原：取代失敗時自動將備份目錄 rename 回原位，防止程式遺失

## [v0.1.0] - 2026-07-19

### 新增
- 高 DPI 螢幕 overlay 座標修正：ROI 框選、點擊座標選取、截圖區域三個 overlay
  均乘以 `devicePixelRatioF()` 轉換為實體座標，解決高 DPI 下框選偏移問題
- 自動化測試框架：新增 `tests/` 目錄，87 項 pytest 測試涵蓋規則引擎、主迴圈、
  模板比對、任務管理、序列化、觸發紀錄
- 規則備註欄位（notes）：Rule 資料模型新增 `notes: str` 欄位，GUI 規則編輯器
  新增備註文字框，向後相容（舊任務檔自動填入空字串）
- 觸發歷史紀錄：每次規則觸發時寫入 `logs/triggers.jsonl`（JSONL 格式），
  記錄時間戳、規則 ID、規則名稱、任務名稱、群組 ID
- 觸發紀錄 rotation：`triggers.jsonl` 超過 1MB 自動輪替（保留 3 份）
- 啟動時自動清理版本更新殘留死檔（`debug.log`、`run_stderr.log`）

### 修正
- 捕捉區域 overlay 1:1 模式下顯示文字改為物理像素尺寸（乘以 `devicePixelRatioF`）
- 日誌系統優化：root logger 從 DEBUG 提升至 INFO，消除模板不匹配噪音
  （每日 log 量從 ~50,000 行降至 ~3,000 行）
- `_ensure_root_handler()` 加 `threading.Lock` 雙重檢查鎖，修復並發競爭
- `rule_serialization` load/save 日誌從 INFO 降為 DEBUG，移除完整 rule list dump
- 主迴圈 rate-limit / 前景略過日誌從 INFO 降為 DEBUG，減少每幀重複輸出
- 主迴圈 `_log()` 移除 `print()` stdout 輸出，改為純 logging
- `startup_error.log` 從覆寫模式改為追加模式
- 刪除 `debug.log`、`run_stderr.log` 等孤立死檔

### 移除
- 移除「簡易/進階」切換按鈕：進階欄位（ROI、on_fail、滑鼠按鈕等）永遠可見，
  簡化 UI 結構，減少使用者困惑

### 重構
- README SEO 優化：擴充適用場景（10 個情境）、新增工具比較表、
  新增英文與簡體中文關鍵詞段落

## [v0.0.14] - 2026-07-15

### 新增
- 新增 `scroll`（滑鼠滾輪）與 `drag`（滑鼠拖曳）步驟類型，支援正規表達式比對
- OCR 診斷面板新增「建立為模板」按鈕：選取辨識結果後一鍵截圖裁切為模板，
  建立 match_image + click + wait 規則（模板用 OCR 精確邊框，ROI 維持 pad=20 搜尋範圍）
- OCR 診斷面板新增「加入模板步驟」按鈕：將辨識區塊截圖追加為現有規則的 match_image 步驟
- 步驟卡片顏色區分：10 種步驟類型各配對應顏色（`_STEP_COLORS`）
- 規則圓點顯示 5 種狀態：停用（灰）、就緒（綠）、運行中（藍）、失敗（紅）、已完成（深藍）
- 狀態欄常駐 AHK 🟢/🔴 連接指示器
- 步驟參數即時校驗：detect 文字、notify 訊息、compare 步驟紅色邊框提示
- 步驟列表支援 Del 快捷鍵刪除選中步驟

### 修正
- 步驟列表 Del 快捷鍵改用 `WidgetShortcut` context，避免攔截規則列表的 Del 刪除功能
- OCR 診斷面板模板截圖色彩空間：`_latest_raw` 為 RGB，裁切後轉 BGR 再編碼，
  避免 match_template 執行時 R↔B 互換導致比對失敗
- `_step_summary` 補充 `template_center` 摘要顯示（後改用統一 `text_center`）

### 重構
- OCR 診斷面板提取 `_compute_roi()` 輔助方法，`_on_add_rule`、`_on_set_sub_target`、
  `_on_add_template`、`_on_add_template_step` 四處共用 ROI 計算邏輯
- 移除多餘的 `template_center` click target，match_image 規則統一用 `text_center`，
  runtime 已透過 `ctx.matched_text` 介面兼容 detect 與 match_image

## [v0.0.13] - 2026-07-15

### 移除
- 移除 `condition_list` 步驟類型（條件清單），其功能已由 `detect` + `click`/`key`/`jump` 步驟組合完全取代
- 移除相關 GUI 元件（`_CondCardWidget`、`_ConditionListStepForm`）、引擎 handler（`_handle_condition_list`）、
  資料模型（`Condition`、`ConditionListParams`）、遷移函式（`_migrate_condition_list_to_step`）
- 清理 tasks JSON 中的 legacy null 欄位（`use_condition_list`、`condition_list`、`condition_list_advance_on_no_match`）
- 無任何實際任務使用此步驟，移除不影響現有功能

## [v0.0.12] - 2026-07-15

### 重構
- 條件清單與 Step 系統合併：將獨立的「條件清單」模式併入 Step 系統，
  新增 `condition_list` Step 類型，消除雙軌架構
- 舊格式任務檔（`use_condition_list` + `condition_list`）自動遷移為
  新的 `condition_list` Step，無需手動轉換
- GUI 移除「條件清單」勾選框，改為在步驟下拉選單中新增
- 執行引擎從兩套獨立路徑（`_run_condition_list` / `_execute_steps`）
  統一為單一 `_run_step` 分派，`condition_list` 由 `_handle_condition_list` 處理
- 條件清單驗證從阻塞彈窗（QMessageBox）改為狀態列非阻塞警告
- 新增條件後自動捲動至新卡片可見區域

### 新增
- 首次啟動自動建立預設任務「我的任務」
- 新手教學改為狀態列輕量提示（toast），不再阻塞啟動
- AHK 未安裝時改為狀態列點擊安裝，不再彈窗
- 版本檢查改為狀態列點擊更新，不再彈窗
- 步驟初始化使用 `_STEP_DEFAULTS` 預設值，新增等待/條件清單等步驟不再空白

## [v0.0.11] - 2026-07-11

### 新增
- on_fail 新增動作「跳過此規則（換下一條）」（action: advance）：
  搭配 fail_duration_sec，連續偵測失敗滿 N 秒後跳過該規則、
  推進到同群組下一條規則（而非原地持續重試），群組重新輪到此規則時
  會重新獲得完整容忍期

### 修正
- _normalize_on_fail 缺少 "advance" action 分支，導致規則重新載入時
  該設定被靜默降級為 "stop"、fail_duration_sec 遺失（存檔後表現異常）

### 重構
- 移除三份分散在不同檔案的重複 _tasks_dir() wrapper，
  統一直接呼叫 get_tasks_dir()

## [v0.0.10] - 2026-07-10

### 重構
- MainWindow 拆分：抽出 GroupSettingsController、ScreenshotController、
  RuleConfigController、TestRunController，MainWindow 從 3260 行降至約一半
- rule_engine 拆分：core/04_rule_engine.py 從 1439 行拆為
  rule_models.py / rule_migration.py / rule_serialization.py /
  task_management.py / run_config.py / file_utils.py，從 1439 行降至約 530 行
- 純內部重構，無使用者可見功能變更，所有拆分皆經過手動功能驗證

## [v0.0.9] - 2026-07-10

### 新增
- 啟動加速：UI 優先顯示，OCR 引擎與 AHK 初始化改為背景 deferred init
- 啟動 3 秒後自動檢查更新（遵循 `skip_update_check` 設定）
- 主頁增加「日誌」按鈕，點擊開啟日誌目錄

### 修正
- 規則拖曳到另一規則上時 UI 項目消失（Qt InternalMove 幽靈清除）
- 樹狀拖曳多重修正：阻擋 rule 成為 child、自動改為 sibling、支援背景規則群組
- `_init_ahk_async` QThread GC 導致閃退
- `_match_image_warn_counter` 無界字典隨規則重載清除
- 關鍵錯誤路徑從 `print()` 遷移至 `logging`，補上遺失的 traceback

### 改善
- 統一日誌至單一 `app.log`，移除 `main.log` / `debug.log` 分散寫入
- 清理過時 docstring 及舊路徑 `update_debug.log` 殘留
- 降低主循環常規 log 等級（info → debug）

### 移除
- 全面移除「觸發紀錄」與「比較輪次日誌」UI 面板及底層資料通道
- 移除 `_rules_dirty` 及相關週期存檔 dead code

## [v0.0.8] - 2026-07-09

### 新增
- 自動更新系統正式實裝：獨立 `updater.exe`，以 `WaitForSingleObject` 精準等待母進程結束後取代檔案
- `build.py` 打包主程式後自動產生 `updater.exe`
- `release.ps1` ZIP 同時包含 `ocr-trigger-clicker.exe` 與 `updater.exe`

### 修正
- 更新後暫存目錄殘留：updater 清理改為逐檔刪除，略過自身 exe（Windows 不能刪正在執行的檔案）
- `Process.wait()` timeout 改為 `WaitForSingleObject`，解決等待母進程退出不可靠問題

### 改善
- 移除了臨時診斷腳本（IsProcessInJob／輪詢測試等）
- 重整專案結構：刪除過時計畫文檔、舊壓力測試、殘留資料
- 補上 GitHub Pages（`docs/`）與更新架構文件說明

## [v0.0.7] - 2026-07-09

### 改善
- 自動更新改用獨立 `updater.exe`（`WaitForSingleObject` 精準等待母進程結束）
- `build.py` 打包主程式後自動產生 `updater.exe`
- `release.ps1` ZIP 同時包含 `ocr-trigger-clicker.exe` 與 `updater.exe`
- 移除舊批次腳本、Job Object 診斷等暫時性程式碼

## [v0.0.6] - 2026-07-08

### 改善
- 版本號更新（測試自動更新流程）

## [v0.0.5] - 2026-07-08

### 新增
- 自動更新功能（版本檢查、下載、zip 解壓、自我取代、重啟）
- 設定頁「啟動時檢查更新」開關（Settings 分頁）

### 修正
- 啟動時背景檢查更新不再彈阻塞對話框

### 改善
- 版本檢查改用 raw GitHub latest_version.txt 取代 GitHub API（避免 rate limit）

## [v0.0.4] - 2026-07-03

### 新增
- notify 步驟類型（提示訊息）
- match_image 比對顏色選項（match_color）

### 修正
- fail_duration_sec 容忍期誤觸發（commit 4cb403c）
- _NotificationStack 訊息覆蓋、任務匯入白名單、圖片比對按鈕即時值、
  dry_run 缺 match_color、CompareStepForm 缺 fail_duration_sec/roi_coord

### 改善
- 群組預設模式 loop→once、color_tolerance 40→100、移除 debug print

## [v0.0.3] - 2026-06-30

### 新增
- match_image 圖示模板比對、on_fail 異常流程控制、fail_duration_sec、壓力測試套件

### 修正
- EXE 啟動 crash、_recv_line 通訊協定偏移、測試比對按鈕視窗遮擋、
  .gitignore images/ 路徑過寬

## [v0.0.2] - 2026-06-23

### 新增
- 統一步驟系統、比對模式三選一（contains/exact/fuzzy）、觸發模式（once/repeat）

### 修正
- 規則引擎健壯性（跳轉循環偵測、runaway 恢復）、多項 bug（詳見 GH release）

### 移除
- 全面移除熱鍵（F8/F9/F10/F12）

## [v0.0.1] - 2026-06-19

### 新增
- 截圖點擊放大功能（lightbox，commit b1dd4e4）
- 打包圖示與 GUI/OCR 截圖（commit 6634f3f）

### 修正
- OCR 失敗計數重置（commit d48718c）

### 改善
- SEO 全面優化 — 結構化資料、meta、FAQ（commit de6e2ad）
- 介紹頁改為暗色主題（commit 44111b0）
- 新手教學導流與首次啟動提示（commit fc2707a、3ab8ed2）

### 工具
- 新增 release.ps1 自動化發版腳本（commit d761df6）
- AGENTS.md 補上版本管理與發版流程（commit c3015f7）

## [v0.0.0] - 2026-06-18

首次公開發行：OCR 文字辨識觸發規則、繁中自訂模型、視窗框選、AHK 自動安裝、多任務管理

[v0.1.2]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.1.2
[v0.1.1]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.1.1
[v0.1.0]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.1.0
[v0.0.14]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.14
[v0.0.13]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.13
[v0.0.12]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.12
[v0.0.11]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.11
[v0.0.10]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.10
[v0.0.9]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.9
[v0.0.8]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.8
[v0.0.7]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.7
[v0.0.6]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.6
[v0.0.5]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.5
[v0.0.4]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.4
[v0.0.3]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.3
[v0.0.2]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.2
[v0.0.1]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.1
[v0.0.0]: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v0.0.0
