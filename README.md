# OCR Trigger Clicker

![License](https://img.shields.io/badge/license-AGPLv3-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.12-blue)

> 透過 OCR 即時偵測螢幕文字，自動執行滑鼠點擊的 Windows 開源工具。  
> Author: Sid

---

## 概述

OCR Trigger Clicker 是一款基於光學字元辨識（OCR）的 Windows 自動化工具。  
它監控指定視窗的畫面內容，當偵測到使用者設定的目標文字時，自動移動滑鼠並點擊指定位置。

全圖形化介面操作，無需撰寫任何程式碼。

### 應用場景

- 遊戲中自動點擊「確認」、「領取」等按鈕
- 重複性表單填寫與提交自動化
- 監控應用程式特定文字事件的觸發回應

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
2. **新增規則** — 設定目標文字，可框選 ROI 縮小偵測範圍
3. **調整冷卻時間** — 避免短時間內重複觸發
4. **啟動主循環** — 點擊「啟動」按鈕開始偵測

---

## 功能詳解

### 規則系統

每條規則包含以下設定：

| 欄位 | 說明 |
|---|---|
| `text` | 目標文字（大小寫不敏感） |
| `match_mode` | `contains` 包含關鍵字／`exact` 完全符合／`fuzzy` 近似比對 |
| `fuzzy_threshold` | 近似比對相似度閾值（0.0 ~ 1.0） |
| `roi` | 偵測區域 `{x, y, w, h}`，全 0 表示全視窗 |
| `trigger_mode` | `once` 觸發一次（多輪比較用）／`repeat` 循環觸發 |
| `cooldown_ms` | 觸發後冷卻時間（毫秒） |
| `max_triggers` | 最大觸發次數（`-1` 為無限） |

### 多任務管理

- 可建立多組規則集（任務），各自獨立啟用
- 任務可匯出／匯入，便於分享與備份
- 儲存位置：`%APPDATA%\ocr-trigger-clicker\`

### ROI 區域選擇器

全螢幕十字游標覆蓋層，使用滑鼠拖曳框選偵測區域，直覺可視化。

### 點擊座標選取器

全螢幕覆蓋層，點擊目標位置即可選取自訂點擊座標。

### OCR 診斷面板

即時顯示當前視窗截圖、OCR 辨識結果（含邊界框與信心度）、點擊測試按鈕，便於除錯與調校。

### 效能監控

主循環運行期間即時顯示：FPS、CPU 使用率、記憶體佔用、點擊速率、OCR 延遲。

### 安全機制

- **前景保護** — 僅在目標視窗位於前景時才執行點擊，非前景時靜默等待
- **速率限制** — 最高每秒 5 次點擊，超限自動暫停
- **失控規則偵測** — 規則 10 秒內觸發超過 5 次自動停用，30 秒後自動恢復
- **緊急停止** — 主視窗停止按鈕立即終止循環

---

## 技術架構

```
使用者 (GUI)
    │
    ▼
┌──────────────────────┐
│  PyQt6 主視窗         │
│  ┌──────────────────┐│
│  │ 規則編輯／任務管理 ││
│  │ ROI 框選／點擊選取 ││
│  │ OCR 診斷／觸發日誌 ││
│  │ 效能監控          ││
│  └────────┬─────────┘│
└───────────┼──────────┘
            │
            ▼
┌──────────────────────┐
│  主循環 (背景執行緒)   │
│ 截圖 → OCR → 比對 → 點擊│
└───────────┬──────────┘
            │ TCP Socket (port 12345)
            ▼
┌──────────────────────┐
│  AutoHotkey v2 Client │
│  (滑鼠移動／點擊)      │
└──────────────────────┘
```

### 核心模組

| 模組 | 功能 |
|---|---|
| `_loader.py` | 動態載入以數字開頭的模組檔案 |
| `01_screenshot.py` | `mss` 截取視窗畫面，fallback GDI PrintWindow |
| `02_ocr_engine.py` | RapidOCR 文字辨識、三種比對模式（contains/exact/fuzzy） |
| `03_ahk_socket.py` | TCP Server，與 AHK 跨行程通訊 |
| `04_rule_engine.py` | 規則模型、步驟系統、任務管理、舊格式遷移 |
| `05_main_loop.py` | 主循環：步驟執行模型、安全機制、跳轉偵測 |
| `06_gui_main.py` | PyQt6 主視窗（規則編輯、步驟拖曳排序、任務管理） |
| `07_gui_roi.py` | 全螢幕 ROI 框選覆蓋層 |
| `09_ocr_debug.py` | OCR 診斷面板（即時截圖、OCR 標註、測試按鈕） |
| `10_performance_monitor.py` | CPU／記憶體／FPS 監控、速率限制 |
| `13_gui_click_picker.py` | 全螢幕點擊座標選取覆蓋層 |
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

所有 ROI / 點擊座標統一儲存為**視窗相對座標**：

- OCR 辨識結果：自然為視窗相對（在視窗截圖上執行）
- ROI 框選、點擊選取：螢幕絕對座標 → 減去視窗位置轉為視窗相對
- 主循環點擊前：視窗相對 → 加回視窗位置轉為螢幕絕對，送給 AHK

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

輸出：`dist\ocr-trigger-clicker.exe`

---

## 常見問題

**Q：點擊沒有作用？**  
A：請以系統管理員身分執行。若目標程式以管理員權限啟動，本工具也須相同權限才能發送滑鼠事件。

**Q：OCR 辨識不準確？**  
A：縮小 ROI 範圍，減少背景干擾。可在診斷面板即時觀察辨識結果與信心度，調整比對閾值。

**Q：找不到 AutoHotkey？**  
A：確認已安裝 AHK v2，安裝後重新啟動本工具。

**Q：更新後規則會不見嗎？**
A：規則儲存在 `%APPDATA%\ocr-trigger-clicker\`，更新 EXE 不會影響既有設定。

**Q：防毒軟體誤判 ONNX 模型檔案怎麼辦？**
A：本工具內建的 OCR 模型（`.onnx` 檔案）是標準的機器學習模型格式，部分防毒軟體可能因為不認識此格式而誤判為威脅。如遇此情況，請將以下目錄加入防毒軟體的排除清單：
- 安裝目錄（`ocr-trigger-clicker.exe` 所在位置）
- `%APPDATA%\ocr-trigger-clicker\`
本工具完全開源，原始碼可於 GitHub 上自行審閱驗證。

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
