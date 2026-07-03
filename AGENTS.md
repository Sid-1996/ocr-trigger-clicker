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

每次完成任何程式碼修改後，**必須主動執行以下步驟，不得等待使用者提醒**：

1. 用 pwsh 執行以下整段（一次完成 add + commit + push）：

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

所有 ROI / 點擊座標統一儲存為**視窗相對座標**（window-relative）。

| 來源 | 原始座標系 | 轉換方式 |
|---|---|---|
| OCR 辨識結果 | 視窗相對（OCR 在截圖上執行，截圖 = 視窗內容） | 不轉換 |
| debug panel「建立為新規則」 | 視窗相對（同上） | 不轉換 |
| 框選偵測區域 (ROI selector) | 螢幕絕對 | `- win_rect` 轉為視窗相對 |
| 選取點擊座標 (click picker) | 螢幕絕對 | `- win_rect` 轉為視窗相對 |

### 主循環處理

1. `capture()` 透過 mss 截取全視窗（含邊框標題列），回傳影像 = 全視窗大小
2. 若 mss 失敗，fallback `capture_window_content()` 只取得 client area
   - 自動填補黑邊到全視窗大小（使用 `get_window_client_offset` 計算 chrome offset）
3. `_process_rules` 對每個規則：裁切 ROI → OCR 裁切區域 → 補回 offset → 比對 → 點擊
   - ROI 座標直接作為影像裁切索引，不需額外轉換

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
**Lint 和格式化一律用 `ruff`，不用 flake8 / black / isort。**

```powershell
# 檢查整個專案
ruff check "C:\Code play first\ocr-trigger-clicker"

# 自動修復可修的問題
ruff check --fix "C:\Code play first\ocr-trigger-clicker"

# 格式化
ruff format "C:\Code play first\ocr-trigger-clicker"
```

修改程式碼後，commit 前先跑 `ruff check --fix` + `ruff format`，確認無 error 才提交。

### 自檢測試
修改 `core/` 下任何非 trivial 邏輯後，手動執行該檔案的 `__main__` self-check：

```powershell
python -c "import core.04_rule_engine; core.04_rule_engine.demo()"
python -c "import core.05_main_loop; core.05_main_loop.demo()"
python -c "import core.11_template_matching; core.11_template_matching.demo()"
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
1. 更新 `_version.py` + `latest_version.txt`
2. commit + push
3. `python build.py` 打包
4. 壓 ZIP
5. git tag + push
6. `gh release create` 上傳至 GitHub Releases
7. 輸出 release 網址

若 `-Notes` 省略則不寫 release note，可在 GitHub 上手動補充。

### CHANGELOG 維護

每次執行 `release.ps1` 發版前，必須先手動更新根目錄 `CHANGELOG.md`，
新增一個對應版本區塊（格式參照 Keep a Changelog，
既有 `v0.0.0`~`v0.0.4` 區塊可當範本）。

`CHANGELOG.md` 內容應與該版本的 GitHub release note 技術細節區段
（見 `SKILL.md`「Release Notes 寫法規範」）保持一致，
避免兩邊漂移。
