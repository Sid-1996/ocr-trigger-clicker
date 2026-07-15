# OCR Trigger Clicker UI 優化計畫

> 文件版本：2.1  
> 建立日期：2026-07-15  
> 更新日期：2026-07-15  
> 狀態：A-E 已完成，F 延後（需高 DPI 硬體測試）

---

## 一、現狀盤點（已驗證）

### 已存在的功能（不需重複實作）

| 功能 | 實作位置 | 狀態 |
|------|----------|------|
| 步驟圖標 | `_STEP_TYPE_ICONS`（`gui/06_gui_main.py:349`） | ✅ 已有 |
| 步驟拖拽排序 | `_StepListWidget` drag-drop（`gui/06_gui_main.py:838`） | ✅ 已有 |
| 規則拖拽排序 | `_RuleTreeWidget` InternalMove（`gui/06_gui_main.py:2891`） | ✅ 已有 |
| background 標識 | `👁` emoji 前綴（`gui/06_gui_main.py:3465`） | ✅ 已有 |
| 執行狀態 running 指標 | 藍色圓點高亮（`gui/06_gui_main.py:3562`） | ✅ 已有（僅 running） |
| AHK 狀態訊息 | status bar 暫態訊息（`gui/06_gui_main.py:2692`） | ⚠️ 有但不持久 |
| 自動保存 | 500ms debounce（`gui/06_gui_main.py:3064`） | ✅ 已有 |
| Ctrl+N 新增規則 | `QShortcut`（`gui/06_gui_main.py:3109`） | ✅ 已有 |
| Del 刪除規則 | `QShortcut`（`gui/06_gui_main.py:3111`） | ✅ 已有 |
| 高 DPI 後端處理 | `get_dpi_scaling_factor()`（`core/01_screenshot.py:132`） | ⚠️ 後端有，前端缺 |

### 本次需實作的項目（5 項）

| # | 項目 | 為什麼需要 | 複雜度 | 狀態 |
|---|------|-----------|--------|------|
| A | 步驟顏色 | 圖標已有但無顏色區分，同類型步驟難以快速辨識 | 低 | ✅ 完成 |
| B | 執行狀態完整化 | 現有只有 running 指標，缺少 failed/completed 狀態 | 中 | ✅ 完成 |
| C | AHK 持久指示器 | 暫態訊息容易被忽略，用戶無法感知斷線 | 低 | ✅ 完成 |
| D | 參數即時校驗 | 完全沒有，錯誤保存後才發現 | 中 | ✅ 完成 |
| E | Del 刪除步驟 | 規則已有 Del，步驟沒有，需用滑鼠點選刪除按鈕 | 低 | ✅ 完成 |
| F | ROI/click picker 高 DPI | 後端已處理 DPI，但前端 overlay 缺少縮放補償 | 中 | ⏸ 延後 |

---

## 二、項目 A：步驟顏色

| 項目 | 說明 |
|------|------|
| **現狀** | 步驟有圖標（🔍🖱️⌨️ 等）但無顏色區分，同類型步驟視覺重複 |
| **目標** | 新增 `_STEP_COLORS` 映射表，步驟卡片圖標套用對應顏色 |
| **涉及文件** | `gui/06_gui_main.py`（`_STEP_COLORS` dict + 步驟卡片渲染） |
| **改動範圍** | 新增約 15 行颜色映射，修改步驟卡片 widget 建立邏輯 |
| **驗收標準** | 不同類型步驟以顏色區分，0.5 秒內可辨識 |

**顏色設計：**

| 步驟類型 | 顏色 | Hex |
|----------|------|-----|
| detect | 藍色 | `#4A90D9` |
| click | 綠色 | `#27AE60` |
| key | 橙色 | `#F39C12` |
| wait | 灰色 | `#95A5A6` |
| jump | 紫色 | `#9B59B6` |
| compare | 青色 | `#1ABC9C` |
| match_image | 粉色 | `#E91E63` |
| notify | 黃色 | `#F1C40F` |
| scroll | 深藍 | `#2C3E50` |
| drag | 紅色 | `#E74C3C` |

---

## 三、項目 B：執行狀態完整化

| 項目 | 說明 |
|------|------|
| **現狀** | `_update_rule_status()` 每 1 秒輪詢，用圓點顏色表示 enabled/disabled，running 規則高亮藍色 |
| **目標** | 新增 failed/completed 狀態，狀態變化時圓點顏色跟著變 |
| **涉及文件** | `gui/06_gui_main.py`（`_update_rule_status`、`_make_circle_icon`） |
| **改動範圍** | 擴展 `get_rules_status()` 回傳值，修改狀態渲染邏輯 |
| **驗收標準** | 5 種狀態視覺可區分：灰（停用）→ 綠（啟用）→ 藍（運行中）→ 紅（失敗）→ 深藍（完成） |

**狀態設計：**

| 狀態 | 圓點顏色 | 觸發條件 |
|------|----------|----------|
| 停用 | 灰 `(160,160,160)` | `enabled=false` |
| 就緒 | 綠 `(0,180,0)` | `enabled=true`，等待執行 |
| 運行中 | 藍 `#4fc3f7` | 正在執行步驟（已有） |
| 失敗 | 紅 `(220,50,50)` | 步驟執行異常 |
| 已完成 | 深藍 `(30,100,180)` | once/repeat 模式執行完畢 |

---

## 四、項目 C：AHK 持久指示器

| 項目 | 說明 |
|------|------|
| **現狀** | AHK 狀態以 `showMessage()` 暫態顯示在 status bar，3 秒後消失 |
| **目標** | 狀態欄新增持久 AHK 連接指示器（🟢/🔴），斷線時可點擊重啟 |
| **涉及文件** | `gui/06_gui_main.py`（status bar 區域） |
| **改動範圍** | 新增一個 `QLabel` 作為持久指示器，監聽 health callback |
| **驗收標準** | 狀態欄右側常駐 🟢/🔴 指示器；🔴 時點擊可重啟 AHK |

---

## 五、項目 D：參數即時校驗

| 項目 | 說明 |
|------|------|
| **現狀** | 步驟參數輸入無即時校驗，錯誤在保存/執行時才被發現 |
| **目標** | 輸入框失去焦點時校驗參數，無效時紅色邊框 + tooltip 提示 |
| **涉及文件** | `gui/06_gui_main.py`（各步驟表單 widget） |
| **技術方案** | `editingFinished` 信號觸發校驗，`setStyleSheet` 紅色邊框 |
| **驗收標準** | 負數坐標、空必填欄位、不存在的 rule_id 即時紅色提示 |

**校驗規則：**

| 參數 | 校驗 |
|------|------|
| ROI 座標 (x, y, w, h) | ≥ 0，w/h > 0 |
| click 點擊坐標 | ≥ 0 |
| wait 等待時間 | ≥ 0 |
| jump 目標 rule_id | 必填，需存在於當前規則列表 |
| detect 關鍵字 | 必填 |

---

## 六、項目 E：Del 刪除步驟

| 項目 | 說明 |
|------|------|
| **現狀** | 規則可用 Del 刪除，但步驟只能用滑鼠點擊行內刪除按鈕 |
| **目標** | 選中步驟時按 Del 可刪除該步驟 |
| **涉及文件** | `gui/06_gui_main.py`（`_StepListWidget` 或步驟列表區域） |
| **改動範圍** | 新增 1 個 `QShortcut`，約 5 行 |
| **驗收標準** | 步驟列表取得焦點時，Del 刪除選中步驟 |

---

## 七、項目 F：ROI/click picker 高 DPI 適配

| 項目 | 說明 |
|------|------|
| **現狀** | 後端 `get_dpi_scaling_factor()` 已處理截圖 DPI，但 `07_gui_roi.py` 和 `13_gui_click_picker.py` overlay 本身無 DPI 補償 |
| **目標** | overlay 座標轉換時考慮 `devicePixelRatio` |
| **涉及文件** | `gui/07_gui_roi.py`、`gui/13_gui_click_picker.py` |
| **技術方案** | 取得 `screen().devicePixelRatio()` 並套用於座標轉換 |
| **驗收標準** | 150%~200% DPI 下 ROI 框選和點擊選取座標正確 |

---

## 八、實施順序

```
A (步驟顏色) ──→ E (Del 刪除步驟) ──→ C (AHK 指示器)
                                          │
B (執行狀態) ─────────────────────────────┘
                                          │
D (參數校驗) ──→ F (高 DPI) ──────────────┘
```

低複雜度先行（A、E、C），再做中等（B、D），最後 F（需多顯示器環境測試）。

---

## 九、驗收清單

### 新功能

- [x] 步驟以顏色區分類型（A）
- [x] 規則圓點顯示 5 種狀態（B）
- [x] 狀態欄常駐 AHK 🟢/🔴 指示器（C）
- [x] 步驟參數無效時紅色提示（D）
- [x] Del 刪除選中步驟（E）
- [ ] 高 DPI 下 ROI/click 座標正確（F — 延後）

### 回歸

- [ ] 現有規則 JSON 正常載入
- [ ] 所有步驟類型執行正常
- [ ] 規則組執行模式（once/loop/repeat）正常
- [ ] ROI 選擇正常
- [ ] OCR 調試面板正常
- [ ] 性能監控面板正常
- [ ] 步驟拖拽排序正常
- [ ] 規則拖拽排序正常
- [ ] 自動保存正常

---

## 十、附錄

### A. 相關文件索引

| 文件 | 主要功能 | 優化涉及 |
|------|----------|----------|
| `gui/06_gui_main.py` | 主視窗 | A、B、C、D、E |
| `gui/07_gui_roi.py` | ROI 選擇 overlay | F |
| `gui/13_gui_click_picker.py` | 點擊座標選擇 overlay | F |
| `core/05_main_loop.py` | 規則執行引擎 | B（狀態回傳） |
| `core/03_ahk_socket.py` | AHK 通訊 | C（health callback） |
| `core/01_screenshot.py` | 截圖 + DPI | F（已有 DPI 處理） |

### B. 參考設計資源

- [PyQt6 樣式表](https://doc.qt.io/qt-6/stylesheet.html)

---

*文件結束*
