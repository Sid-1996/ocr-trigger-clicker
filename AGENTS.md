# 專案筆記

## 專案理念與方向

### 核心原則
- **最小主義，務實**。最好的程式碼是從未被寫出的程式碼（YAGNI）。
- **社群標準優先，不造輪子**。匯入匯出用 JSON `_meta` schema、有現成函式庫就用、不重做別人做過的事。
- **普通使用者面向**。進階選項摺疊隱藏、預設行為簡單直覺、不讓使用者看到實作細節。
- **刪除優先於新增**。功能不必要就砍（熱鍵、強制前景、排程器），減少維護負擔。
- **不懶惰的地方**：信任邊界驗證、資料遺失防止、安全性。

### 目標方向
普通遊戲玩家能輕鬆設定的日常自動化腳本工具。流程：
1. 選視窗 → 2. 框偵測區域 → 3. 打關鍵字 → 4. 選動作 → 5. 分享

---

## 工作完成規範

每個獨立任務完成後應立即單獨 commit，不得累積多個不相關任務到同一個 commit。若同一輪對話涉及多個檔案的不同修改目的（例如同時改了架構文件又改了授權檔案），必須拆成多次 git add + commit，逐一提交，不要合併成一個 commit message 帶過。

每次完成任何程式碼修改後，**必須主動依序跑完以下檢查清單，不得等待使用者提醒**。使用者是 vibe coding，不會提醒你做這些事——這份清單就是你的提醒：

1. **Lint / 格式化**（本次有改 `.py` 檔才需要，純文件/設定變更跳過）：
   ```powershell
   pwsh -Command "Set-Location 'C:\Code play first\ocr-trigger-clicker'; ruff check --fix .; ruff format ."
   ```
   確認無殘留 error 才進下一步。

2. **自檢測試**（本次有改 `core/` 或 `gui/` 下任何非 trivial 邏輯——有分支、迴圈、解析、信任邊界/資料安全路徑——才需要）：
   檢查該檔案是否有 `if __name__ == "__main__":` self-check，有就執行：
   ```powershell
   python -c "import sys,runpy; sys.path.insert(0,'.'); runpy.run_path('<改動的檔案路徑>', run_name='__main__')"
   ```
   把 `<改動的檔案路徑>` 換成實際修改的檔案（例如 `core/04_rule_engine.py`）。單行 trivial 變更、或該檔案本來就沒有 self-check，跳過。不要依賴任何寫死的檔名清單——用「這次改了什麼檔」來判斷，而不是查表。

3. **更新知識圖譜**（本次有改程式碼檔才需要，純文件/CHANGELOG/設定變更跳過）：
   ```powershell
   pwsh -Command "Set-Location 'C:\Code play first\ocr-trigger-clicker'; graphify update ."
   ```
   純程式碼變動不吃 LLM/API，近乎免費。判斷細節見下方「graphify」章節。

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

---

## 座標系統

所有 ROI / 點擊座標統一儲存為**視窗比例座標**（window-ratio, 0~1）。

| 來源 | 原始座標系 | 轉換方式 |
|---|---|---|
| OCR 辨識結果 | 視窗相對（OCR 在截圖上執行） | ÷ win_size → 比例座標 |
| debug panel「建立為新規則」 | 視窗相對（同上） | ÷ win_size → 比例座標 |
| 框選偵測區域 (ROI selector) | 螢幕絕對 | (螢幕 - win_rect) ÷ win_size → 比例 |
| 選取點擊座標 (click picker) | 螢幕絕對 | (螢幕 - win_rect) ÷ win_size → 比例 |

### 主循環處理

1. `capture()` 透過 mss 截取全視窗（含邊框標題列），回傳影像 = 全視窗大小
2. 若 mss 失敗，fallback `capture_window_content()` 只取得 client area
   - 自動填補黑邊到全視窗大小（使用 `get_window_client_offset` 計算 chrome offset）
3. `_process_rules` 對每個規則：`_resolve_roi()` 將比例座標 × 當前尺寸 → 像素 → 裁切 ROI → OCR → 比對 → `_resolve_point()` → AHK 點擊

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

### ripgrep（`rg`）
搜尋程式碼時**一律用 `rg`，不用 `grep` 或 `findstr`**。

```powershell
# 搜尋關鍵字
rg "pattern" "C:\Code play first\ocr-trigger-clicker"

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
ruff check "C:\Code play first\ocr-trigger-clicker"

# 自動修復可修的問題
ruff check --fix "C:\Code play first\ocr-trigger-clicker"

# 格式化
ruff format "C:\Code play first\ocr-trigger-clicker"
```

### 自檢測試
強制執行時機與判斷方式見上方「工作完成規範」清單第 2 步（依實際改動的檔案動態判斷，不要對照固定清單）。單一檔案的執行語法：

```powershell
python -c "import sys,runpy; sys.path.insert(0,'.'); runpy.run_path('<檔案路徑>', run_name='__main__')"
```

---

## 版本管理與發行流程

### 版本資訊
- `_version.py` — 單一事實來源（`__version__` / `__author__` / `__github__`）
- `latest_version.txt` — 給客戶端版本檢查用（純文字，一行版本號）

### 發版指令

```powershell
.\release.ps1 -Version "0.1.0" -Notes "更新說明"
```

此腳本自動完成：
1. Pre-flight 檢查（python / gh / git 乾淨度 / tag 衝突）
2. 更新 `_version.py` + `latest_version.txt`
3. 本地 commit（不 push）
4. `python build.py` 打包 + 壓 ZIP
5. git tag + push commit + tag 到遠端
6. `gh release create --draft --prerelease` 建立 Draft Release
7. 輸出 draft release 網址

> Release 建立為 **Draft** 狀態，必須手動在 GitHub Releases 頁面按「Publish release」
> 才會對外公開，避免 auto-updater 在 asset 上線前抓到新版本。

### 重發流程

若發版後發現打包錯誤（如漏檔）需要同版本重發，使用 `-Force` 參數：

```powershell
.\release.ps1 -Version "0.1.4" -Force -Notes "修復打包漏檔"
```

`-Force` 會自動：
1. 刪除既有遠端 tag（如存在）
2. 刪除既有 GitHub release（如存在）
3. 然後正常建立新 tag + release

不加 `-Force` 時，若 tag 已存在會失敗。

### CHANGELOG 維護

每次執行 `release.ps1` 發版前，必須先手動更新根目錄 `CHANGELOG.md`，
新增一個對應版本區塊（格式參照 Keep a Changelog，
既有 `v0.0.0`~`v0.0.4` 區塊可當範本）。

`CHANGELOG.md` 內容應與該版本的 GitHub release note 技術細節區段
（見 `SKILL.md`「Release Notes 寫法規範」）保持一致，
避免兩邊漂移。

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships. The user is vibe coding — they will never type `/graphify` or any flag themselves. You decide when to use it, based on the rules below. Don't ask for permission first.

**Do NOT default to graphify for everything.** It's a tool for when you'd otherwise have to grep/read multiple files to understand how something connects. Using it on questions you can already answer from the file currently open, or on generic programming questions unrelated to this codebase, is wasted latency and tool calls for no benefit — skip it and just answer.

### When to query (read-only, cheap — use freely within the rule below)

Run `graphify query "<question>"` first, before grepping or reading multiple files by hand, ONLY when the question genuinely needs cross-file/architectural context, e.g.:
- "how does X flow through the app", "what calls Y", "why does Z break when W changes"
- non-trivial refactor/debug tasks where you don't already know the affected call sites

Skip it (just answer directly or use `rg`) when:
- The answer is fully visible in the file already open or just discussed
- It's a one-file, one-function question ("what does this line do")
- It's a generic Python/library question with nothing project-specific about it

Use `graphify path "<A>" "<B>"` for a specific relationship, `graphify explain "<concept>"` for one node — both cheaper and more scoped than a full query.

### When to update (near-free for code-only changes — bake into the commit step)

`graphify update .` only re-extracts changed files and needs no LLM/API cost when every changed file is code (this project always is). Because of that, run it once as part of the commit workflow above — right before `git add -A` — not after every individual edit:

```powershell
pwsh -Command "Set-Location 'C:\Code play first\ocr-trigger-clicker'; graphify update ."
```

Skip this step for pure non-code commits (docs-only, CHANGELOG, config) — nothing structural changed, nothing for the graph to catch.

### When to fully rebuild (expensive — never automatic)

`/graphify .` (no flags) reruns the entire pipeline: reclustering, community relabeling, full report regen. Only do this if the user explicitly asks for a full rebuild, or `graphify update .` reports the graph is stale/corrupt beyond what update can fix. Never trigger it just because a session started or because update "might as well" be a full run.

### Misc

- If `graphify-out/wiki/index.md` exists, use it for broad navigation instead of raw source browsing.
- Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review, or when query/path/explain don't surface enough context.
- Dirty `graphify-out/` files after hooks/incremental updates are expected — not a reason to skip graphify.
