![License](https://img.shields.io/badge/license-MIT-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.12-blue)

# OCR Trigger Clicker

透過 OCR 偵測螢幕文字，自動執行滑鼠點擊的開源工具。

### ✨ 特色

- 🖱️ 無需寫程式，GUI 操作
- 🎯 自定義文字觸發規則
- 📖 支援繁體中文 OCR
- 📦 規則可匯出分享
- 🔓 開源免費

---

## 📋 系統需求

- Windows 10 / 11（64 位元）
- [AutoHotkey v2](https://www.autohotkey.com/)（需使用者自行安裝）
- 不需要 Python 環境（EXE 已內嵌）

---

## ⚙️ 安裝步驟

1. 下載並安裝 [AutoHotkey v2](https://www.autohotkey.com/)
2. 從 GitHub Releases 下載 `ocr-trigger-clicker.exe`
3. 以系統管理員身分執行 EXE

---

## 📖 使用教學

1. **選擇視窗** — 下拉選單選擇要監控的目標視窗
2. **新增規則** — 設定目標文字，可用「框選偵測區域」縮小偵測範圍
3. **設定冷卻** — 避免短時間內重複觸發
4. **啟動** — 點擊「啟動」按鈕開始偵測
5. **緊急暫停** — 按下 `F9` 可暫停／繼續

---

## 🔧 進階設定

### 規則欄位說明

| 欄位 | 說明 |
|------|------|
| `target_text` | 要偵測的目標文字（大小寫不敏感） |
| `fuzzy` | 啟用模糊比對，可容忍錯字 |
| `fuzzy_threshold` | 模糊比對相似度閾值（0.0 ~ 1.0） |
| `roi` | 偵測區域（x/y/w/h），全 0 表示全視窗 |
| `click_position` | `text_center` 點擊文字中心，`custom` 點擊自訂座標 |
| `click_button` | `left` 或 `right` |
| `cooldown_ms` | 觸發後冷卻時間（毫秒） |
| `trigger_mode` | `once` 觸發一次，`repeat` 循環觸發 |
| `max_triggers` | 最大觸發次數，`-1` 為無限 |
| `random_offset` | 點擊座標隨機抖動像素，模擬真人操作 |

### 規則 JSON 格式

```json
{
  "rules": [
    {
      "id": "rule_001",
      "name": "確認按鈕",
      "enabled": true,
      "target_text": "確認",
      "fuzzy": false,
      "fuzzy_threshold": 0.8,
      "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
      "click_position": "text_center",
      "click_button": "left",
      "cooldown_ms": 2000,
      "trigger_mode": "once",
      "max_triggers": -1,
      "random_offset": 3
    }
  ]
}
```

規則檔案位置：`%APPDATA%\ocr-trigger-clicker\rules.json`

---

## ❓ 常見問題

**Q：點擊沒有作用？**  
A：請以系統管理員身分執行本工具（若目標程式是管理員權限啟動）。

**Q：OCR 辨識不準確？**  
A：縮小偵測區域（ROI）可避免背景干擾，建議框選精確的文字範圍。

**Q：找不到 AutoHotkey？**  
A：請確認已安裝 AHK v2，安裝後重新啟動本工具。

**Q：規則設定存在哪裡？更新後會不會消失？**  
A：規則儲存在 `%APPDATA%\ocr-trigger-clicker\rules.json`，更新工具後設定不會被覆蓋。

---

## ⚠️ 免責聲明

本工具僅供學習與研究用途。使用者應自行確認是否符合所使用軟體的服務條款（ToS）。開發者不對任何因使用本工具造成的帳號停權、資料損失或其他損害負責。

---

## 📄 開源授權

MIT License

---

## 🧱 技術架構

- **Python 3.12 + PyQt6** — GUI 介面
- **RapidOCR** — 繁體中文 OCR 辨識
- **AutoHotkey v2** — 滑鼠模擬點擊
- **TCP Socket** — Python 與 AHK 跨程序通訊

### 模組說明

| 模組 | 功能 |
|------|------|
| `01_screenshot.py` | 使用 `mss` 截取指定視窗畫面 |
| `02_ocr_engine.py` | RapidOCR 文字辨識與模糊比對 |
| `03_ahk_socket.py` | TCP Server，操控 AHK 執行滑鼠動作 |
| `04_rule_engine.py` | 規則載入、觸發判斷、冷卻管理 |
| `05_main_loop.py` | 整合核心迴圈（截圖 → OCR → 判斷 → 點擊） |
| `06_gui_main.py` | PyQt6 主視窗 |
| `07_gui_roi.py` | 全螢幕 ROI 框選工具 |
| `08_gui_log.py` | 觸發日誌表格元件 |
| `build.py` | PyInstaller 打包腳本 |
| `clicker.ahk` | AHK v2 TCP Client，執行滑鼠點擊 |
