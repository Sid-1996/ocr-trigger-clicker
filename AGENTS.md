# 專案筆記

## 專案理念與方向

### 核心原則
- **最小主義，務實**。最好的程式碼是從未被寫出的程式碼（YAGNI）。
- **社群標準優先，不造輪子**。匯入匯出用 JSON `_meta` schema、有現成函式庫就用、不重做別人做過的事。
- **普通使用者面向**。進階選項摺疊隱藏、預設行為簡單直覺、不讓使用者看到實作細節。
- **刪除優先於新增**。功能不必要就砍（排程器、強制前景），減少維護負擔。保留的例外：F8 全域熱鍵（啟動/停止，暫停中按為繼續）有實際用途，勿刪。
- **不懶惰的地方**：信任邊界驗證、資料遺失防止、安全性。

### 目標方向
普通遊戲玩家能輕鬆設定的日常自動化腳本工具。流程：
1. 選視窗 → 2. 框偵測區域 → 3. 打關鍵字 → 4. 選動作 → 5. 分享

---

## 文件索引

| 路徑 | 對象 | 用途 |
|---|---|---|
| `README.md` / `.en.md` | 使用者 | 專案首頁、下載連結 |
| `START.md` / `START.en.md` | 使用者 | 快速上手指南（3 分鐘） |
| `docs/dev/TECHNICAL.md` | 開發者 | 技術規格與比較表 |
| `docs/dev/ARCHITECTURE.md` | 開發者 | 系統架構與模組地圖 |
| `docs/dev/CHANGELOG.md` | 開發者 | 版本記錄 |
| `AGENTS.md` | AI agent | 本檔案 — 工作規範與流程 |
| `docs/index.html` | 使用者 | 完整教學網站 |
| `docs/starsavior.html` | 使用者 | StarSavior 遊戲任務頁 |

---

## 工作完成規範

每個獨立任務完成後應立即單獨 commit，不得累積多個不相關任務到同一個 commit。若同一輪對話涉及多個檔案的不同修改目的（例如同時改了架構文件又改了授權檔案），必須拆成多次 git add + commit，逐一提交，不要合併成一個 commit message 帶過。

每次完成任何程式碼修改後，**必須主動依序跑完以下檢查清單，不得等待使用者提醒**。使用者是 vibe coding，不會提醒你做這些事——這份清單就是你的提醒：

1. **Lint / 格式化**（本次有改 `.py` 檔才需要，純文件/設定變更跳過）：
   ```powershell
   pwsh -Command "Set-Location 'C:\Code play first\ocr-trigger-clicker'; uv run ruff check --fix .; uv run ruff format ."
   ```
   確認無殘留 error 才進下一步。

2. **自檢測試**（本次有改 `core/` 或 `gui/` 下任何非 trivial 邏輯——有分支、迴圈、解析、信任邊界/資料安全路徑——才需要）：
   檢查該檔案是否有 `if __name__ == "__main__":` self-check，有就執行：
   ```powershell
   uv run python -c "import sys,runpy; sys.path.insert(0,'.'); runpy.run_path('<改動的檔案路徑>', run_name='__main__')"
   ```
   把 `<改動的檔案路徑>` 換成實際修改的檔案（例如 `core/04_rule_engine.py`）。單行 trivial 變更、或該檔案本來就沒有 self-check，跳過。不要依賴任何寫死的檔名清單——用「這次改了什麼檔」來判斷，而不是查表。self-check 以可斷言、非互動的 `__main__` 為限（Qt overlay／主視窗啟動器、無 `__main__` 的檔跳過，例如 `core/10_performance_monitor.py`）。

   同時跑 pytest 套件（`tests/` 對應的 `test_*.py`，或整個套件冒煙）：
   ```powershell
   uv run python -m pytest --no-cov -q
   ```
   改 `core/` 邏輯後不跑 pytest 視為未完成。對應範圍除了實體 import，也含 `tests/conftest.py` 的 fixture／factory（`make_main_loop` / `tmp_tasks_dir`）落點；改含 `T()` 的 `.py` 或 `i18n/*.json` 時加跑 `tests/test_i18n.py`。整合測試（`test_ocr_merge` / `test_prematch_equiv` / `test_template_cache`）需本機 RapidOCR model 且在無 model 環境會自動 skip；對應測試因環境 skip 時改用該模組 self-check 補位並在回覆明說，不當作綠燈。

測試速度紅線：整套 `pytest` 的標準時間約 1 分鐘。實境截圖幀清單集中在 `tests/data_frames.py`（新增截圖：ASCII 檔名 → 加入 `ALL_FRAMES`；截圖不入版控，只在本地），**預設只跑 `CORE_FRAMES`**；全量 12 幀會讓 OCR 整合測試約翻倍（約 +50s），只在需要時設 `OTC_FULL_FRAMES=1` 跑，不要讓預設路徑變慢。

3. **座標校正自檢**（本次改到座標換算／輸入分派／截圖客戶區時必跑；純文件/UI 文案跳過）：
   ```powershell
   uv run python devtools/coordinate_calibration.py --self-check
   uv run python devtools/coordinate_calibration.py --diagnose
   ```
   `--diagnose` 是安全層：只驗證實際客戶區尺寸下的座標數學與三模式路由，不碰滑鼠。若改動涉及真點擊、前景/hybrid 激活或 input 路徑，**依風險加跑真點擊驗證**（會移動滑鼠、短暫搶焦點）：
   ```powershell
   uv run python devtools/coordinate_calibration.py --e2e             # T2：1600x900 有框/無框 × 3 模式 = 6
   uv run python devtools/coordinate_calibration.py --e2e --cross-res # T3：1600/1920 有框/無框 × 3 模式 = 12
   uv run python devtools/coordinate_calibration.py --e2e --full      # 發版：1280/1600/1920 有框/無框 × 3 模式 = 18
   ```
   狀態檔在 `%TEMP%\otc_calibration_status.json`；exit code 非 0 即未完成。三模式需要 Frida 環境，失敗時先跑 `--diagnose` 區分「座標數學」與「注入/前景」問題。

### 測試分級（同比例跨解析度）

產品合約：16:9 的 `1280×720`、`1600×900`、`1920×1080` 必須能互相替換；其他長寬比列 best-effort，不作為阻擋條件。

核心不變量：

1. 比例座標（ROI／點擊）在三個代表尺寸間映射誤差 **≤3px**，且不得出現誤點。
2. 模板 `capture_size` 是「擷取當下客戶區尺寸」；跨解析度時以 `capture_size` 對 `current_size` 換算，不可用被裁切影像或 ROI 寬度推算。
3. 錄製輸出全視窗比例；轉換出的模板步驟寫入客戶區 `capture_size`；前景 selector 建立的 ROI／點擊維持 `roi_coord:"client"`。

分級與適用時機：

- **T0 文件／文案**：不跑 pytest；有改 `.py` 才跑 ruff。
- **T1 座標數學／解析**：self-check + pytest + `--self-check` + `--diagnose`。一般座標重構、轉換器、模板尺度邏輯至少到這層。
- **T2 真輸入／焦點／截圖**：`--e2e` 6 組。改 input 分派、前景/hybrid 激活、截圖客戶區時必跑。
- **T3 跨解析度／發版**：`--e2e --cross-res` 12 組；發版候選跑 `--full` 18 組。DPI 125%/150% 與多螢幕列手動驗證，不進自動矩陣。

通過標準：所有組 0 miss、偏差 ≤3px、三模式不得 fallback；模板尺度維持 5 段候選，不因跨解析度退化成 13 段全掃。Bug fix 必須先重現失敗案例，再補對應 T 層；只跑 T1 不可宣稱跨解析度已修好。

4. **add + commit + push**（一次完成）：
   ```powershell
   pwsh -Command "
     [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
     Set-Location 'C:\Code play first\ocr-trigger-clicker'
     git add -A
     '類型: 說明' | Out-File -FilePath __commit_msg.txt -Encoding utf8
     git commit -F __commit_msg.txt
     Remove-Item __commit_msg.txt
     git push origin master
   "
   ```

commit 訊息格式：`feat` / `fix` / `refactor` / `docs` / `chore` + 冒號 + 中文說明。

---

## 提案/推薦前必做核實（防推測式建議）

提供任何「推薦/建議/優化方向」前，**必須先實證核實工具是否已存在**，不得僅憑推測：

1. **檢索先行**：以 `codegraph_explore` 優先，`Grep`/`rg` + `Read` 為備選，檢索相關符號/檔名/文案 key（例如 `rule_requested` / `create_text_rule` / `_on_add_rule` / `T("ocr_debug.create_text_rule")`），有結果即視為已存在。
2. **有無分流**：檢索為空且已說明檢索式與範圍，方可提案為「新增」；否則一律歸為「已實現/瘦身/撤案」，並在回覆中標註證據定位 `file:line`。
3. **證據定位**：每項建議必須附 `file:line` 定位，無定位視為未完成。
4. **與完成度掛鉤**：推測式提案（無檢索/無定位）視為與 `Lint 未過/pytest 未跑` 同級的未完成，不得進入 `add + commit + push`。二次審查時以此為必檢項（見本檔「工作完成規範」延伸）。

*Rationale*：診斷主路徑 `gui/09_ocr_debug.py:620 _on_add_rule` → `gui/06_gui_main.py:6486 _on_debug_rule_requested` 的 `detect + click@text_center` 曾被誤判為缺口，補「一鍵成規」屬重複設計；核實可避免重複設計與過度設計。

---

## Shell / Git 指令規範

### ✅ 使用 PowerShell 7（pwsh）執行所有指令

本機已安裝 PowerShell 7+，**所有 shell 指令必須用 `pwsh -Command "..."` 執行**，不要用 cmd 或舊版 PowerShell。
pwsh 預設 UTF-8，中文不需要額外處理。

```powershell
# ✅ 正確：用 pwsh 執行
pwsh -Command "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Set-Location 'C:\Code play first\ocr-trigger-clicker'; git status"
pwsh -Command "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Set-Location 'C:\Code play first\ocr-trigger-clicker'; git log --oneline -5"

# ❌ 錯誤：直接用 cmd 跑 git，中文會亂碼
cmd /c "git log --oneline -5"
```

### 提交流程

中文 commit 訊息用 `-F` 暫存檔方式，避免引號截斷：

```powershell
pwsh -Command "
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  Set-Location 'C:\Code play first\ocr-trigger-clicker'
  git add -A
  '類型: 說明' | Out-File -FilePath __commit_msg.txt -Encoding utf8
  git commit -F __commit_msg.txt
  Remove-Item __commit_msg.txt
  git push origin master
"
```

### 其他規範

- 全局已設 `core.pager=cat`，git log 不需額外加 `--no-pager`
- Python 依賴由全域 `uv` 管理；先跑 `uv sync --dev`，日常命令一律透過 `uv run ...` 執行。`pyproject.toml` + `uv.lock` 是依賴事實來源，不再使用 `requirements.txt`。

---

## 座標系統

所有 ROI / 點擊座標統一儲存為**比例座標**（0~1）。前景 selector 建立時統一收斂為**客戶區比例**（`roi_coord:"client"`，以客戶區不含標題列/邊框為基準）；舊任務無 `roi_coord` 標記視為全視窗比例，向下相容。互動方法三種：`pynput`（前景）、`frida`（後台 Frida 注入，可嘗試解決部分遊戲無法後台點擊；零游標/焦點干擾，有防作弊風險；多數 Unity 遊戲因底層限制不支援後台，以遊戲視窗自行測試為準）、`hybrid`（混合模式：後台 PrintWindow 截圖偵測＋動作時若遊戲已在前景則直接做 pynput 物理輸入，否則短暫激活後復原使用者前景視窗與滑鼠位置；連續動作依 `max_cps` 平滑間隔，見 `core/19_hybrid_input.py` 的 `focus_guard`；適合不支援後台注入的遊戲與低頻動作）。後台 PostMessage 模式已移除。模式分派規則：截圖/黑幕類分支用 `mode != "pynput"`，輸入分派與工具前景保護用 `mode == "frida"`（hybrid 輸入走前景物理路徑）。

| 來源 | 原始座標系 | 轉換方式 |
|---|---|---|
| OCR 辨識結果 | 視窗相對（OCR 在截圖上執行） | ÷ client_size → 客戶區比例（debug panel 建立規則時） |
| debug panel「建立為新規則」 | 視窗相對（同上） | ÷ client_size → 客戶區比例 |
| 框選偵測區域 (ROI selector) | 螢幕絕對 | (螢幕 - win_rect - chrome) ÷ client_size → 客戶區比例 |
| 選取點擊座標 (click picker) | 螢幕絕對 | (螢幕 - win_rect - chrome) ÷ client_size → 客戶區比例 |
| 模板擷取 (capture region) | 螢幕絕對 | (螢幕 - win_rect - chrome) ÷ client_size → 客戶區比例 |

> ROI/點擊/模板選取**統一走前景 selector**（`07_gui_roi`、`13_gui_click_picker`、`14_capture_region`），後台模式也相同（設定時將目標視窗前景化），收斂為客戶區比例。已實測前景(mss)模板與後台執行截圖（PrintWindow）比對一致（BrownDust II 全部信心 1.0），故後台模板不再需要 PrintWindow 框選 UI。

> **客戶區尺寸**一律用 `get_client_size_hwnd()`（GetClientRect）或 `MainLoop._client_size(rect)`。`get_window_client_offset()` 只回傳客戶區左上角 offset，**不可**拿來算 `W - cx`／`H - cy`（有框視窗的右/下邊框會被漏掉，座標系統性偏移）；無 hwnd 的純數學 fallback 僅供測試。

### 主循環處理

1. `capture_frame()` 依互動模式選唯一截圖來源（前景 mss 三層備援 / 後台 PrintWindow），回傳影像 = 全視窗大小
2. 若 mss 失敗，fallback `capture_window_content()` 只取得 client area
   - 自動填補黑邊到全視窗大小（使用 `get_window_client_offset` 計算 chrome offset）
3. `_process_rules` 對每個規則：`_resolve_roi()` 將比例座標 × 當前尺寸 → 像素 → 裁切 ROI → OCR → 比對 → `_resolve_point()` → pynput / Frida 點擊

### 通用 UI 流程（兩者一致）

框選偵測區域 / 選取點擊座標：

1. `activate_window(title)` → 目標視窗跳到前景
2. `parent_window.showMinimized()` → 主視窗縮小
3. 全螢幕 overlay 出現（幾乎透明，十字游標）
4. 使用者在目標視窗上操作（拖曳框選 / 單擊）
5. overlay 關閉 → 主視窗恢復 → 回到編輯頁 + 狀態列顯示結果

---

## Coding 風格（Ponytail）

你是一個懶惰的資深開發者。懶惰代表高效，不代表不認真。最好的程式碼是從未被寫出的程式碼。

寫任何程式之前，先讀懂任務與它觸及的程式碼、trace 端到端真實流程，再停在第一個能撐住的台階：

1. 這個需要存在嗎？→ 不：跳過（YAGNI）
2. 這個 codebase 已存在嗎？→ 複用既有 helper/util/pattern，不重寫（先 `codegraph_explore`/`Grep` 搜一遍，例如 `core/box_utils`/`core/_paths`/`core/17_capture_pipeline.capture_frame`）
3. 標準函式庫能做？→ 用它
4. 原生平台功能能用？→ 用它
5. 已安裝的 dependency 能解？→ 用它
6. 一行搞定？→ 就一行
7. 以上都不是：才寫最少能跑的程式碼

**不做的事：**
- 沒被要求的抽象層
- 能避免就避免的新 dependency
- 沒人要求的 boilerplate
- 刪除優先於新增
- 無聊優先於聰明
- 檔案數量越少越好
- 對複雜需求提出質疑：「你真的需要 X，還是 Y 就夠了？」

**Bug fix = 根因，非症狀**：先 `Grep` 該函式的所有 caller，在共享函式修一次；各 caller 補 guard 是更大 diff，且會漏掉兄弟路徑（例：`core/05_main_loop.py:380 _resolve_roi` 座標還原漏 `roi_coord` 分支）。

兩個 stdlib 方案大小相同？選在 edge case 正確的那個。懶惰是寫更少程式碼，不是選更脆弱的演算法。

刻意的簡化用 `# ponytail:` 註解標記，例如：
`# ponytail: 全局鎖，若吞吐量有需求再改為 per-account 鎖`

**懶惰程式碼沒有檢查就是未完成的。** 非平凡邏輯（有分支、迴圈、解析、金流/安全路徑）留下一個可執行的檢查——最小的、邏輯壞掉就會失敗的東西：assert-based demo() / `__main__` self-check 或一個小 `test_*.py`。不用 framework，不用 fixture。單行 trivial 程式碼不需要測試。

**不懶惰的地方：**
- 信任邊界的輸入驗證
- 防止資料遺失的錯誤處理
- 安全性
- 任何被明確要求的事項
- 已上線任務驗證的必要複雜度（例：`core/18_frida_bg`/`core/19_hybrid_input`/`verify`/`fail_duration_sec` 已由 StarSavior 真實任務驗證）不視為過度設計，不因 YAGNI 而刪

`stop ponytail` / `normal mode`：取消。等級持續到更改或 session 結束為止。


---

## 效能紅線（改動前必讀）

v0.4.3 之後的版本曾因兩處改動把主循環拖慢約 2 倍（GUI 每 500ms 全表重建、每幀列舉全桌面視窗標題），追查成本極高。動到主循環／GUI 更新路徑前套用這四條：

1. **GUI 每個 tick 的工作量必須正比於「新增資料」，不可正比於「資料總量」**——面板/表格/清單更新一律增量附加，禁止每 tick 重建全部項目（欄寬 `ResizeToContents` 重算也算）。
2. **每幀熱路徑禁止列舉視窗、禁止跨行程同步送訊**；視窗矩形／客戶區 offset 每幀查一次就快取（`get_window_rect_hwnd()`、`MainLoop._chrome()`），不要每條規則各查一次。
3. **單執行緒的密集 Python 工作會凍結整個行程**（它自己的 CPU 時間看起來很低，因為在等 GIL）。`[perf]` 出現「某階段耗時暴增但 `執行緒CPU≈0`」就是 GIL 被別人霸佔——去找誰在燒 GIL，不要判定成「loop 執行緒沒被排程」。
4. **效能改動必須附真機 A/B**（同機同遊戲、真 app + F8、兩版連續交替跑，比較 `[perf]` 的幀耗／執行緒CPU；**不要看「循環停止」的平均幀耗**，它含 `scan_interval_ms` 等待）。無 GUI 的 harness／單元測試量不到 GUI 執行緒的 GIL 競爭，曾據此得到「新版較快」的反向結論。協定與成因見 `docs/dev/TECHNICAL.md`「GIL 凍結兩案」。

---

## 可用工具

### 程式碼搜尋
**內建 Grep 工具優先**，速度快、省 token，且不需經過 shell 組指令（避免路徑含空格、pwsh 語法等問題）。
只有內建 Grep 無法滿足時（例如需要計算符合數量、或其他 rg 專屬旗標），才 fallback 用 `rg`，一律不用 `grep` 或 `findstr`。

```powershell
# 只搜尋 Python 檔
rg "pattern" -t py

# 列出有匹配的檔名（不顯示行內容）
rg "pattern" -l

# 搜尋含行號，忽略大小寫
rg "pattern" -n -i
```

### Ruff
**Lint 和格式化一律用 `ruff`，不用 flake8 / black / isort。**強制執行時機見上方「工作完成規範」清單第 1 步，這裡只列常用指令：

```powershell
# 檢查整個專案
uv run ruff check "C:\Code play first\ocr-trigger-clicker"

# 自動修復可修的問題
uv run ruff check --fix "C:\Code play first\ocr-trigger-clicker"

# 格式化
uv run ruff format "C:\Code play first\ocr-trigger-clicker"
```

### 自檢測試
強制執行時機與判斷方式見上方「工作完成規範」清單第 2 步（依實際改動的檔案動態判斷，不要對照固定清單）。單一檔案的執行語法：

```powershell
uv run python -c "import sys,runpy; sys.path.insert(0,'.'); runpy.run_path('<檔案路徑>', run_name='__main__')"
```

### 任務模擬器（`sim_task.py`）
以固定 seed 隨機切換 `tests/data` 實境幀，餵給真規則引擎（`MainLoop._process_rules`），動作只計數不執行（`_send_click/_send_key/_send_scroll/_activate_window` 全為 stub，不碰真滑鼠與真視窗），輸出幀耗／OCR 成本／每規則命中、從未命中、從未被評估清單。

```powershell
uv run python sim_task.py --frames 40 --seed 1          # 核心 4 幀
uv run python sim_task.py --frames 120 --seed 7 --full  # 全 12 幀（含本地截圖）
uv run python sim_task.py --out sim.json                # 另存統計，供跨版本／跨 seed 比較
uv run python sim_task.py --self-check                  # 只驗統計邏輯（不載模型）
```

同 seed 可重現；換 seed 換一組抽樣。首幀含模型暖機，看「穩態平均」別看 avg。隨機換幀無時間鄰近性（實機同場景多為連續相似幀），數字屬壓力情境、偏悲觀。

**它不是效能綠燈**：只涵蓋 OCR＋規則引擎（`處理`），沒有 `_loop` 預處理、擷取、黑幕差異、真輸入，也沒有 Qt GUI 執行緒的 GIL 競爭——效能改動一律以「效能紅線」第 4 條的真機 A/B 為準，本工具僅作改動前的快速掃描。

---

## 版本管理與發行流程

### 更新架構（Velopack）

自動更新由 **Velopack** 框架接管（v0.4.0 起，自製 updater 已拆除）：
- 用戶端 `core/12_updater.py` 只是薄封裝；檢查／下載／換目錄／重啟全由框架處理
- feed 位址由 `build.py --feed prod|test` 烘入 `_update_feed.py`（防呆：打包後自動驗證內容）
  - `prod` = 本庫（正式使用者）；`test` = `ocr-trigger-clicker-release-test`（發版沙箱，直接公開、隨便打靶）
- 安裝模式：使用者跑 Setup.exe → 安裝至 `%LocalAppData%\OCRTriggerClicker`，此後更新全自動
- 單一實例防護：雙開會鎖死安裝目錄，第二份啟動即提示退出
- `latest_version.txt` **凍結於 0.3.0、刻意不動**——舊客戶端讀它永遠顯示「暫無更新」（斷糧），請勿刪除或更新

### 版本資訊
- `_version.py` — 單一事實來源（`__version__` / `__author__` / `__github__`）
- `latest_version.txt` — 凍結的歷史檔，僅供 v0.3.x 舊客戶端靜默斷糧用

### 發版流程

**手動準備階段：**
1. 更新 `docs/dev/CHANGELOG.md`，新增一個 `## [v$x.y.z]` 區塊（Keep a Changelog 格式）
2. 測試庫打靶（不打擾使用者）：`.\release.ps1 -Version "x.y.z" -FeedTest`
   - 自動 build → vpk pack → 上傳測試庫並**直接公開**
3. E2E 驗證（安裝測試庫 Setup.exe 後逐項點擊，2026-08-26 實測通過的清單）：
   - 檢查更新 → 應找到沙箱上的新版
   - 按自動更新 → 進度 → app 自動退出並重啟 → 狀態列顯示「已更新至 vX」
   - 防雙開：再開一次程式 → 第二份應彈「程式已在執行中」後退出
   - 切換介面語言 → 應自動重啟且語言生效
4. 失敗 → 修復 → 回到步驟 2

**正式發版：**
```powershell
.\release.ps1 -Version "x.y.z"
```

腳本自動完成：
1. Pre-flight（uv / gh / **vpk** / git 乾淨度 / tag 衝突）
2. 解析 CHANGELOG `## [v$x.y.z]` 區塊作為 release notes（缺日期自動補）
3. 更新 `_version.py` + pyproject version（**不動 latest_version.txt**）
4. `vpk download github` 取回前版資產（供 delta 計算；首次無前版屬正常）
5. `uv run python build.py`（PyInstaller + feed 烘入 + 防呆驗證 + `vpk pack`）
6. git commit（_version.py / pyproject.toml / CHANGELOG）+ tag + push
7. `vpk upload github` 上傳 Setup.exe／nupkg／releases.win.json 為 **Draft**，再以 `gh release edit` 補 notes

**發版後：**
- Draft 冒煙測試（下載 Setup.exe 安裝）→ GitHub 頁面按「Publish release」
- Draft 期間 stable 使用者看不到任何東西；有問題 → `-Force` 重發

### Delta Update

Velopack 內建處理：`vpk download github` 取回前版後，`vpk pack` 自動產生 delta nupkg；
用戶端下載失敗或 delta 不適用時框架自動退回 full。無需人工維護 manifest 協定。
v0.3.0 及更早的免安裝版不在 Velopack 版鏈上，對其永不產生 delta。

### 重發流程

```powershell
.\release.ps1 -Version "x.y.z" -Force            # 正式庫
.\release.ps1 -Version "x.y.z" -Force -FeedTest  # 測試庫
```

`-Force` 自動刪除既有遠端 tag + release 後正常重發。

### CHANGELOG 維護

docs/dev/CHANGELOG.md 是 release notes 的唯一事實來源。
格式：`## [v$x.y.z] - YYYY-MM-DD`（日期由 `release.ps1` 自動補填）。
每次發版前手動新增該版本區塊；`release.ps1` 解析後寫入 GitHub release。

**寫法：白話、面向一般玩家、只講使用者有感的結果**（單人維護，不寫開發者細節／不需維護「給開發者」區塊）：
1. 頂部一行「請下載 XXX（檔名）」，再以分類標題（`### 性能優化`／`### 問題修復`／`### 新功能`）條列。
2. 每條講「使用者看到什麼變化」，不要寫模組名、函式名、毫秒數字（要數字就給體感量級，如「快約 2.6 倍」）。
3. 主要改版（安裝方式變更等）頂部以引用塊標註英日文下載提示（`> **🌐 English**: ...` ／ `> **🌐 日本語**: ...`），直接展開顯示，無需收合。
4. 實作細節留在 commit message 與 `docs/dev/TECHNICAL.md`，不進 CHANGELOG。

## 任務 JSON 同步（GitHub Pages）

本地任務目錄 `%APPDATA%\ocr-trigger-clicker\tasks\` 是唯一事實來源。
`docs/tasks/` 是 GitHub Pages 提供下載的鏡像，兩者需手動同步。

**流程：**
1. **比較差異**：用 Python 載入兩邊 JSON，比對 groups/rules 數量、enabled 狀態、step 內容
2. **覆蓋檔案**：`Copy-Item` 從本地複製到 `docs/tasks/`
3. **提交**：`git add -A` → commit + push 上傳 JSON 即可（commit 訊息：`docs: sync task JSON`）

**HTML 不再逐次同步：** `docs/starsavior.html` 使用通用性介紹（不寫死群組數、群組名稱、規則清單、enabled 狀態），使用者下載 JSON 後自行啟停調整。因此任務內容更新時**不需要**改 HTML。僅當網頁的整體功能描述本身需要調整（例如新增/移除整個功能類別）時才動 HTML。

**注意：**
- `.gitignore` 已放行 `!docs/tasks/`，不需要額外處理
- HTML 下載連結是相對路徑 `tasks/XXX.json`，只要 JSON 檔名不變就不需改链接
- 體力型/力量型跑馬通常是二選一，使用者自行啟停

## CodeGraph

專案已用 `codegraph init` 建過索引（`.codegraph/`），透過 MCP server 自動接給 agent 使用，不需要在這裡寫使用規則——`codegraph_explore` 由 agent 依需求自行判斷呼叫，索引也由檔案監控自動同步，commit 流程不需要任何額外步驟。
