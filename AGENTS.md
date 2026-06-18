# 專案筆記

## 工作完成規範

每次完成任何程式碼修改後，**必須主動執行以下步驟，不得等待使用者提醒**：

1. `chcp 65001 > nul && git add -A`
2. 將 commit 訊息寫入暫存檔：`echo 類型: 說明 > __commit_msg.txt`
3. `chcp 65001 > nul && git commit -F __commit_msg.txt`
4. `del __commit_msg.txt`
5. `chcp 65001 > nul && git push origin master`

commit 訊息格式：`feat` / `fix` / `refactor` / `docs` / `chore` + 冒號 + 中文說明。

---

## Shell / Git 指令規範

### ⚠️ 編碼問題（最常見失敗原因）

Windows cmd 預設編碼為 CP950，中文會變成亂碼導致所有指令看起來「失效」。
**解法：每一條 shell 指令都必須用 `&&` 串接 `chcp 65001`，不能只執行一次就假設後續生效。**

```
# ✅ 正確：每條指令都串 chcp
chcp 65001 > nul && git status
chcp 65001 > nul && git add -A
chcp 65001 > nul && git commit -m "..."
chcp 65001 > nul && git push origin master

# ❌ 錯誤：只執行一次 chcp 然後分開跑後續指令
chcp 65001
git status   ← 這條可能還是亂碼
```

**如果指令輸出出現亂碼，不代表指令失效，代表沒有串 chcp 65001。請重新執行加上 chcp 65001 的版本，不要放棄。**

### 其他規範

- 禁止使用分頁器：全局已設 `core.pager=cat`，不需額外加 `--no-pager`
- 標準 git log 格式：`chcp 65001 > nul && git log --oneline -5`
- 中文 commit 訊息不能直接放在 `git commit -m "..."` 引號內（Windows 會截斷），必須寫入暫存檔再用 `-F` 參數：

```
echo 類型: 說明 > __commit_msg.txt
chcp 65001 > nul && git commit -F __commit_msg.txt
chcp 65001 > nul && del __commit_msg.txt
```

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
