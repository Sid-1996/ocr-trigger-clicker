# OCR Trigger Clicker 快速上手指南

不是說明書。是從下載到啟動的最短路徑。

---

## 路徑 A：匯入任務直接跑

已經有別人做好的任務設定檔（JSON），你只需要載入就能用。

### ① 下載工具

[GitHub Releases](https://github.com/Sid-1996/ocr-trigger-clicker/releases) → 下載 `ocr-trigger-clicker.zip`

解壓縮，執行 `ocr-trigger-clicker.exe`

> 通常正常啟動就能用。如果遊戲沒反應，再試試**按右鍵 → 以系統管理員身分執行**。

### ② 下載任務

目前可用的任務：

- [StarSavior 每日任務](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/1)
- [StarSavior 跑馬輔助](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/1)

下載 `.json` 檔放到隨便一個資料夾。

### ③ 匯入 + 啟動

工具打開後長這樣：

![主介面](docs/images/gui-main.png)

在上面找到這些東西：

1. **工具列 → 匯入任務** — 選你剛下載的 JSON
2. **下拉選單** — 選你要操控的遊戲視窗（例如 StarSavior）
3. **群組列表** — 勾選你要跑的群組
4. **「啟動」按鈕** — 按下去就開始了

---

## 路徑 B：自己學設定規則

想從頭建立自己的自動化流程？也是四步：

### ① 下載工具

同上，[下載 ZIP](https://github.com/Sid-1996/ocr-trigger-clicker/releases) → 解壓縮 → 執行 exe

### ② 認識主介面

- **左邊** = 群組列表（你的流程大綱）
- **右邊** = 規則編輯區（每一步的細節）
- **工具列** = 匯入/匯出、啟動/停止、OCR 診斷

### ③ 建立第一條規則

1. 按右鍵 → 新增群組（取名「測試」）
2. 在群組上按右鍵 → 新增規則
3. 步驟選「**detect（偵測）**」→ 輸入你要找的文字
4. 再加一個步驟「**click（點擊）**」→ 框選要點的位置
5. 按「▶測試」確認沒問題

> 💡 **最快作法：** 按「OCR 診斷」看畫面裡有哪些字被偵測到，找到你要的目標直接按「建立為新規則」— 偵測條件和位置會自動填好。你只需要補上要按什麼鍵就行。

### ④ 啟動

按「啟動」→ 勾選你的群組 → 開始跑

詳細教學請看[文件網站](https://sid-1996.github.io/ocr-trigger-clicker/)的工具教學章節。

---

## 常見問題

### 工具沒反應？

先確認視窗有選對、工具正在運行中。如果都沒問題，試試**按右鍵 → 以系統管理員身分執行**再開一次。

### 我的解析度不是 1920×1080？

比例座標會自動適應不同解析度，但 ROI 框選位置可能需要微調。先用「OCR 診斷」確認文字有沒有被偵測到。

### 任務檔存在哪裡？

`%APPDATA%\ocr-trigger-clicker\` 底下。砍掉 exe 設定還在，不用擔心。

### 更多問題？

→ [完整 FAQ](https://sid-1996.github.io/ocr-trigger-clicker/#faq)
→ [GitHub Discussions](https://github.com/Sid-1996/ocr-trigger-clicker/discussions)

---

## 連結總整理

| 項目 | 網址 |
|---|---|
| 下載工具 | https://github.com/Sid-1996/ocr-trigger-clicker/releases |
| 文件網站 | https://sid-1996.github.io/ocr-trigger-clicker/ |
| 任務分享 | https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/任務檔案分享 |
| 問題回報 | https://github.com/Sid-1996/ocr-trigger-clicker/issues |
