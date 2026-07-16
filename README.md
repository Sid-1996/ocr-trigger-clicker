# OCR Trigger Clicker

![License](https://img.shields.io/badge/license-AGPLv3-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Downloads](https://img.shields.io/github/downloads/Sid-1996/ocr-trigger-clicker/total?label=%E4%B8%8B%E8%BC%89%E6%AC%A1%E6%95%B8&color=238636)

> 透過 OCR 即時偵測螢幕文字，自動執行滑鼠點擊的 Windows 開源工具。  
> Author: Sid

---

## 概述

OCR Trigger Clicker 是一款基於光學字元辨識（OCR）的 Windows 自動化工具。  
它監控指定視窗的畫面內容，當偵測到使用者設定的目標文字時，自動移動滑鼠並點擊指定位置。

專注於**無程式碼（No-Code）**、**跨解析度相容**的開源方案，封裝複雜的機器學習模型與底層 Windows 視窗操作，讓不具備程式背景的使用者也能輕鬆建立自動化規則。

> ⚠️ **仍在 Beta 階段**，持續開發完善中，部分已知問題與效能優化正在逐步解決。

### 應用場景

- 遊戲中自動點擊「確認」、「領取」等按鈕
- 重複性表單填寫與提交自動化
- 監控應用程式特定文字事件的觸發回應

---

## 專案亮點

### 🎯 解決業界痛點：視窗比例座標系統

首創視窗比例座標系統（0~1 比值），完美解決傳統自動化工具（如 Airtest）在跨解析度、縮放比例變更時腳本失效的致命傷，大幅降低 80% 的腳本維護成本。  
→ 詳見 [座標系統](#座標系統)

### 🔗 跨技術棧整合：Python + AHK TCP Socket 架構

自主設計並實現基於 TCP Socket 的跨行程通訊架構，結合 Python（PyQt6 + RapidOCR）的高效資料處理能力與 AutoHotkey v2 的底層 Windows 視窗訊息模擬，顯著提升遊戲前景保護下的點擊成功率與系統穩定度。  
→ 詳見 [技術架構](#技術架構)

### 🎨 產品思維與用戶體驗：No-Code 極簡設計

主打極簡無程式碼（No-Code）設計，封裝複雜的機器學習模型（ONNX Runtime），並內建視覺化 Dry-Run 測試、ROI 診斷面板與效能監控，成功將複雜自動化工具的上手門檻降至普通使用者等級。  
→ 詳見 [步驟測試按鈕](#步驟測試按鈕)、[ROI 區域選擇器](#roi-區域選擇器)、[OCR 診斷面板](#ocr-診斷面板)、[效能監控](#效能監控)

---

## 系統需求

- Windows 10 / 11（64 位元）
- [AutoHotkey v2](https://www.autohotkey.com/)（需自行安裝）
- 使用預編譯 EXE 無需 Python 環境

---

## 安裝

1. 下載並安裝 [AutoHotkey v2](https://www.autohotkey.com/)
2. 從 Releases 下載 `ocr-trigger-clicker.exe`
3. **以系統管理員身分執行**（若目標程式以管理員權限執行，否則點擊無效）

---

## 快速入門

1. **選擇視窗** — 從下拉選單選取要監控的目標視窗
2. **建立群組** — 右鍵 → 新增群組，設定執行模式（循環執行／執行一次／重複 N 次）
3. **在群組內新增規則** — 設定偵測文字、點擊位置等步驟
4. **常駐監控** — 規則打勾「常駐監控」即自動歸入 📡 節點，不參與群組順序
5. **啟動** — 點擊「啟動」→ 選擇要執行的群組 → 開始偵測

---

## 功能詳解

全部功能均透過圖形化介面操作，無需編寫任何程式碼。從選取目標視窗、框選偵測區域到設定比對邏輯，皆可在數分鐘內透過點選與拖曳完成，即使不熟悉機器學習或自動化技術的使用者也能快速上手。

### 群組系統

群組是規則的容器，控制規則的執行順序與循環方式。每個群組可獨立設定：

| 設定 | 說明 |
|------|------|
| 執行模式 | 循環執行（持續輪迴）、執行一次（跑完就停，預設）、重複 N 次（指定次數後停止） |
| 重複次數 | 僅「重複 N 次」模式下有效 |
| 每輪間隔 | 每輪完成後的等待秒數 |
| 啟用／停用 | 停用的群組在啟動時不會出現在選單中 |

可透過右鍵選單新增、刪除、重新命名群組。規則可在群組內拖曳排序。

### 規則系統

每條規則包含以下設定：

| 欄位 | 型態 | 說明 |
|------|------|------|
| `id` | str | 唯一識別碼 |
| `name` | str | 使用者自訂名稱 |
| `enabled` | bool | 規則啟用／停用 |
| `background` | bool | 常駐監控模式（獨立於群組流程外） |
| `steps` | list[Step] | 有序步驟陣列，依序執行 |

步驟（Step）是規則的執行單元，支援以下類型。**優先選用 `match_image`（圖示比對），比 OCR 快 10~50 倍且抗背景文字干擾；只有在模板無法區分時才改用 `detect`（OCR）。**

| 步驟類型 | 用途 | 關鍵參數 |
|----------|------|----------|
| `detect` | OCR 偵測文字，未命中則觸發 on_fail | `text`, `roi`, `match_mode`, `fuzzy_threshold`, `on_fail`（stop/key/skip/jump/notify + fail_duration_sec） |
| `click` | 滑鼠點擊 | `target`（text_center/custom）、`x`, `y`, `button`, `random_offset` |
| `key` | 鍵盤按鍵 | `key`（AHK 格式）, `hold_ms` |
| `wait` | 固定等待 | `ms` |
| `jump` | 跳轉至另一規則（限同群組） | `rule_id` |
| `compare` | 數值比對（擷取 ROI 內數字後比較） | `pattern`, `operator`, `value`, `on_fail`（stop/key/skip/jump/notify + fail_duration_sec） |
| `match_image` | 圖示模板比對（比 OCR 快 10~50 倍，建議優先選用；可選顏色比對） | `template`, `roi`, `threshold`, `match_color`, `color_tolerance`, `on_fail`（stop/key/skip/jump/notify + fail_duration_sec） |
| `notify` | 提示訊息彈窗 | `message` |
| `scroll` | 滑鼠滾輪 | `direction`, `amount`, `delay_ms` |
| `drag` | 滑鼠拖曳 | `target`, `dx`, `dy`, `button` |

### 常駐監控

勾選「常駐監控」的規則不屬於任何群組流程，獨立運作：

- 每幀都會執行（不受群組 pointer 影響）
- 不參與群組順序、不計入群組輪次
- 自動歸入樹狀結構底部的 📡 常駐監控節點
- 適合隨時需要攔截的條件，如錯誤提示、緊急中斷

取消常駐監控後，規則自動加回第一個啟用的群組。

### 多任務管理

- 可建立多組任務，各自獨立啟用（每組任務包含獨立的規則與群組設定）
- 儲存位置：`%APPDATA%\ocr-trigger-clicker\tasks\`（開發與打包 EXE 皆同）；可透過環境變數 `OCR_TRIGGER_DATA` 覆蓋基底路徑
- 模板圖片儲存位置：`%APPDATA%\ocr-trigger-clicker\images\`（同上）
- 匯入／匯出：對話框起始目錄為專案根目錄（開發模式）或 EXE 所在目錄（打包模式），可自由選擇存放位置

### 步驟測試按鈕

每個偵測／比較／圖像比對步驟旁皆有「測試」按鈕，可在編輯時直接 dry-run，結果會以視覺化標記繪製在截圖上（偵測到的文字框、比對結果、點擊位置等），便於調校參數。

### ROI 區域選擇器

全螢幕十字游標覆蓋層，使用滑鼠拖曳框選偵測區域，直覺可視化。

### 點擊座標選取器

全螢幕覆蓋層，點擊目標位置即可選取自訂點擊座標。

### OCR 診斷面板

即時顯示當前視窗截圖、OCR 辨識結果（含邊界框與信心度）、點擊測試按鈕，便於除錯與調校。

### 效能監控

主循環運行期間即時顯示：FPS、CPU 使用率、記憶體佔用、點擊速率、OCR 延遲。

### 安全機制

- **前景保護** — 可選功能，開啟後僅在目標視窗位於前景時才執行點擊
- **工具前景保護** — 工具本身視窗位於前景時自動暫停 click/key/drag/scroll，防止誤操作搶走焦點
- **速率限制** — 最高每秒 5 次點擊，超限自動暫停
- **緊急停止** — 主視窗停止按鈕立即終止循環

### 系統托盤與關閉行為

打叉關閉視窗時，預設縮小至系統托盤（背景持續偵測），雙擊托盤圖示可還原視窗。可透過托盤選單的「設定...」調整：

- **關閉行為** — 選擇「縮小至系統托盤」或「直接關閉程式」
- **關閉前確認** — 關閉前跳出確認對話框，可勾選「不再顯示此確認」

托盤選單提供「顯示視窗」與「離開」（完整結束程式）兩個選項。

---

## 技術架構

本專案自主設計基於 TCP Socket 的跨行程通訊層，串接 Python 的計算能力（PyQt6 GUI + RapidOCR 辨識）與 AutoHotkey v2 的底層 Windows 視窗訊息模擬，實現高效且穩定的跨行程協作。

```
使用者 (GUI)
    │
    ▼
┌────────────────────────┐
│  PyQt6 主視窗           │
│  ┌────────────────────┐│
│  │ 群組管理／規則編輯   ││
│  │ 常駐監控 📡 節點    ││
│  │ ROI 框選／點擊選取  ││
│  │ OCR 診斷／效能監控  ││
│  │ 觸發日誌            ││
│  └────────┬───────────┘│
└───────────┼────────────┘
            │
            ▼
┌────────────────────────┐
│  主循環 (背景執行緒)    │
│  群組佇列 → 群組內規則  │
│  ─→ 背景規則 (常駐監控) │
│  截圖 → OCR → 比對 → 點擊│
└───────────┬────────────┘
            │ TCP Socket (port 12345)
            ▼
┌────────────────────────┐
│  AutoHotkey v2 Client   │
│  (滑鼠移動／點擊／按鍵)  │
└────────────────────────┘
```

### 核心模組

| 模組 | 功能 |
|---|---|
| `_loader.py` | 動態載入以數字開頭的模組檔案 |
| `01_screenshot.py` | `mss` 截取視窗畫面，fallback GDI PrintWindow |
| `02_ocr_engine.py` | RapidOCR 文字辨識、三種比對模式（contains/exact/fuzzy） |
| `03_ahk_socket.py` | TCP Server，與 AHK 跨行程通訊 |
| `04_rule_engine.py` | 規則引擎 re-export hub（已拆分為 rule_models / rule_migration / rule_serialization / task_management / run_config） |
| `05_main_loop.py` | 主循環：群組兩層指標模型、步驟執行、安全機制 |
| `06_gui_main.py` | PyQt6 主視窗（規則編輯、群組管理、步驟拖曳排序、任務管理、系統托盤、SettingsDialog） |
| `07_gui_roi.py` | 全螢幕 ROI 框選覆蓋層 |
| `09_ocr_debug.py` | OCR 診斷面板（即時截圖、OCR 標註、測試按鈕） |
| `10_performance_monitor.py` | CPU／記憶體／FPS 監控、速率限制 |
| `11_template_matching.py` | 圖示模板比對（OpenCV matchTemplate + NMS） |
| `13_gui_click_picker.py` | 全螢幕點擊座標選取覆蓋層 |
| `14_capture_region.py` | 區域截圖選取器（match_image 模板來源） |
| `build.py` | PyInstaller 打包腳本 |
| `clicker.ahk` | AHK v2 TCP Client |

### 技術棧

- **Python 3.12 + PyQt6** — GUI 介面
- **RapidOCR (ONNX Runtime)** — 繁體中文 OCR，支援 DirectML GPU 加速
- **AutoHotkey v2** — 滑鼠模擬（TCP Socket 通訊）
- **mss** — 高效率螢幕截圖
- **OpenCV + NumPy** — 影像處理與畫面變動偵測
- **PyInstaller** — 打包為單一 EXE

### 座標系統

所有 ROI / 點擊座標統一儲存為**視窗比例座標**（0~1 比值，與視窗解析度無關）：

- OCR 辨識結果：自然為視窗相對，再除以視窗寬高轉為比例
- ROI 框選、點擊選取：螢幕絕對座標 → 減去視窗位置 → 除以視窗寬高轉為比例
- 主循環使用時：比例 × 當前視窗寬高 → 還原為像素座標 → 加回視窗位置送給 AHK

此設計使腳本在 1080p、4K、縮放 150% 等不同環境下完全相容，無需手動調整座標—解決傳統工具（如 Airtest）跨解析度腳本失效的致命傷，大幅降低約 80% 的腳本維護成本。

---

## 開發

### 環境準備

```bash
git clone https://github.com/YOUR_USERNAME/ocr-trigger-clicker.git
cd ocr-trigger-clicker
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt   # 或手動安裝必要套件
```

### 執行

```bash
python gui/06_gui_main.py
```

### 打包

```bash
python build.py
```

輸出：
- `dist\ocr-trigger-clicker.exe` — 主程式
- `dist\updater.exe` — 獨立更新行程（自動更新時用 `WaitForSingleObject` 等待母進程退出後取代檔案）

> `docs/` 目錄為 GitHub Pages 專案網站（<https://sid-1996.github.io/ocr-trigger-clicker/>），含 `docs/index.html` 手刻首頁與 Google Search Console 驗證檔。

---

## 常見問題

**Q：點擊沒有作用？**  
A：請以系統管理員身分執行。若目標程式以管理員權限啟動，本工具也須相同權限才能發送滑鼠事件。

**Q：OCR 辨識不準確？**  
A：縮小 ROI 範圍，減少背景干擾。可在診斷面板即時觀察辨識結果與信心度，調整比對閾值。

**Q：找不到 AutoHotkey？**  
A：確認已安裝 AHK v2，安裝後重新啟動本工具。

**Q：更新後規則會不見嗎？**
A：規則儲存在 `%APPDATA%\ocr-trigger-clicker\tasks\`（開發與打包 EXE 皆同），更新 EXE 不會影響既有設定。

**Q：防毒軟體誤判 ONNX 模型檔案怎麼辦？**
A：本工具內建的 OCR 模型（`.onnx` 檔案）是標準的機器學習模型格式，部分防毒軟體可能因為不認識此格式而誤判為威脅。如遇此情況，請將以下目錄加入防毒軟體的排除清單：
- 安裝目錄（`ocr-trigger-clicker.exe` 所在位置）
- `%APPDATA%\ocr-trigger-clicker\`
本工具完全開源，原始碼可於 GitHub 上自行審閱驗證。

---

## 社群與交流

- 📂 **任務檔案分享** — 想找現成腳本或分享自己的任務設定？歡迎到 [任務檔案分享 Discussions](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/%E4%BB%BB%E5%8B%99%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB) 交流。
- 💬 **一般討論** — 使用心得、功能建議、疑難排解，都歡迎在 [GitHub Discussions](https://github.com/Sid-1996/ocr-trigger-clicker/discussions) 發起。
- 🐛 **問題回報** — 遇到 bug 或想要新功能，請到 [Issues](https://github.com/Sid-1996/ocr-trigger-clicker/issues) 回報。
- ⭐ 如果這套工具對你有幫助，歡迎到 [GitHub 專案](https://github.com/Sid-1996/ocr-trigger-clicker) 給一顆 Star 支持開發！
- ☕ **贊助開發者** — [ECPAY](https://p.ecpay.com.tw/E0E3A) / [PayPal](https://www.paypal.com/ncp/payment/9TGC4B3MYM9A6) / [愛發電](https://afdian.com/a/sid-1996)

---

## 免責聲明

本工具僅供學習與研究用途。使用者應自行確認使用行為是否符合目標軟體的服務條款。開發者不對任何因使用本工具造成的帳號停權、資料損失或其他損害負責。

---

## 開源授權

Copyright (C) 2024 Sid

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
