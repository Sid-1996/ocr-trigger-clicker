# 專案筆記

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
