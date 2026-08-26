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

3. **add + commit + push**（一次完成）：
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

所有 ROI / 點擊座標統一儲存為**比例座標**（0~1）。前景 selector 建立時統一收斂為**客戶區比例**（`roi_coord:"client"`，以客戶區不含標題列/邊框為基準）；舊任務無 `roi_coord` 標記視為全視窗比例，向下相容。互動方法三種：`pynput`（前景）、`frida`（後台 Frida 注入，可嘗試解決部分遊戲無法後台點擊；零游標/焦點干擾，有防作弊風險；多數 Unity 遊戲因底層限制不支援後台，以遊戲視窗自行測試為準）、`hybrid`（混合模式：後台 PrintWindow 截圖偵測＋動作時短暫激活遊戲做 pynput 物理輸入，完成後復原使用者前景視窗與滑鼠位置，見 `core/19_hybrid_input.py` 的 `focus_guard`；適合不支援後台注入的遊戲，每次操作會短暫搶焦點）。後台 PostMessage 模式已移除。模式分派規則：截圖/黑幕類分支用 `mode != "pynput"`，輸入分派與工具前景保護用 `mode == "frida"`（hybrid 輸入走前景物理路徑）。

| 來源 | 原始座標系 | 轉換方式 |
|---|---|---|
| OCR 辨識結果 | 視窗相對（OCR 在截圖上執行） | ÷ client_size → 客戶區比例（debug panel 建立規則時） |
| debug panel「建立為新規則」 | 視窗相對（同上） | ÷ client_size → 客戶區比例 |
| 框選偵測區域 (ROI selector) | 螢幕絕對 | (螢幕 - win_rect - chrome) ÷ client_size → 客戶區比例 |
| 選取點擊座標 (click picker) | 螢幕絕對 | (螢幕 - win_rect - chrome) ÷ client_size → 客戶區比例 |
| 模板擷取 (capture region) | 螢幕絕對 | (螢幕 - win_rect - chrome) ÷ client_size → 客戶區比例 |

> ROI/點擊/模板選取**統一走前景 selector**（`07_gui_roi`、`13_gui_click_picker`、`14_capture_region`），後台模式也相同（設定時將目標視窗前景化），收斂為客戶區比例。已實測前景(mss)模板與後台執行截圖（PrintWindow）比對一致（BrownDust II 全部信心 1.0），故後台模板不再需要 PrintWindow 框選 UI。

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

寫任何程式之前，先停在第一個能撐住的台階：

1. 這個需要存在嗎？→ 不：跳過（YAGNI）
2. 標準函式庫能做？→ 用它
3. 原生平台功能能用？→ 用它
4. 已安裝的 dependency 能解？→ 用它
5. 一行搞定？→ 就一行
6. 以上都不是：才寫最少能跑的程式碼

**不做的事：**
- 沒被要求的抽象層
- 能避免就避免的新 dependency
- 沒人要求的 boilerplate
- 刪除優先於新增
- 無聊優先於聰明
- 檔案數量越少越好
- 對複雜需求提出質疑：「你真的需要 X，還是 Y 就夠了？」

兩個 stdlib 方案大小相同？選在 edge case 正確的那個。懶惰是寫更少程式碼，不是選更脆弱的演算法。

刻意的簡化用 `# ponytail:` 註解標記，例如：
`# ponytail: 全局鎖，若吞吐量有需求再改為 per-account 鎖`

**懶惰程式碼沒有檢查就是未完成的。** 非平凡邏輯（有分支、迴圈、解析、金流/安全路徑）留下一個可執行的檢查——最小的、邏輯壞掉就會失敗的東西：assert-based demo() / `__main__` self-check 或一個小 `test_*.py`。不用 framework，不用 fixture。單行 trivial 程式碼不需要測試。

**不懶惰的地方：**
- 信任邊界的輸入驗證
- 防止資料遺失的錯誤處理
- 安全性
- 任何被明確要求的事項

`stop ponytail` / `normal mode`：取消。等級持續到更改或 session 結束為止。


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
3. E2E 驗證：安裝測試庫 Setup.exe → 觸發更新 → delta／重啟／雙開防護全綠
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
