# 專案筆記

## 工作完成規範

每次完成任何程式碼修改後，**必須主動執行以下步驟，不得等待使用者提醒**：

1. `chcp 65001 > nul`
2. `git add -A`
3. `git commit -m "類型: 簡短說明"`
4. `git push origin master`

commit 訊息格式：`feat` / `fix` / `refactor` / `docs` / `chore` + 冒號 + 中文說明。

---

## Shell / Git 指令規範

- Windows 環境，執行任何 shell 指令前先設定編碼：`chcp 65001`
- git log 必須在 `chcp 65001` 後執行，才能正確顯示中文 commit 訊息
- 禁止使用分頁器：全局已設 `core.pager=cat`，不需額外加 `--no-pager`
- 標準 git log 格式：`git log --oneline -5`

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
