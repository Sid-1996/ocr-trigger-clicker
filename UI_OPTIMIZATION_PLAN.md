# OCR Trigger Clicker UI 優化計畫

> 建立日期：2026-07-15  
> 狀態：F 延後（需高 DPI 硬體測試）

---

## 項目 F：ROI/click picker 高 DPI 適配

| 項目 | 說明 |
|------|------|
| **現狀** | 後端 `get_dpi_scaling_factor()` 已處理截圖 DPI，但 `07_gui_roi.py` 和 `13_gui_click_picker.py` overlay 本身無 DPI 補償 |
| **目標** | overlay 座標轉換時考慮 `devicePixelRatio` |
| **涉及文件** | `gui/07_gui_roi.py`、`gui/13_gui_click_picker.py` |
| **技術方案** | 取得 `screen().devicePixelRatio()` 並套用於座標轉換 |
| **驗收標準** | 150%~200% DPI 下 ROI 框選和點擊選取座標正確 |

---

*文件結束*
