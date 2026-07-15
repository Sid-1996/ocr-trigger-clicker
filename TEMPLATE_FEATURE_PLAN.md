# OCR 診斷面板「建立為模板」功能計畫

> 文件版本：1.0
> 建立日期：2026-07-15
> 狀態：待執行

---

## 一、需求概述

在 OCR 診斷面板（`gui/09_ocr_debug.py`）新增「建立為模板」按鈕，讓使用者在 OCR 辨識結果中選取一個文字區塊後，直接將該區塊的截圖裁切為模板圖片，建立一條 `match_image` 規則。

**使用者流程：**
1. 開啟 OCR 診斷面板 → 點「拍一張」
2. 在辨識結果表格中選取一個文字區塊
3. 點「建立為模板」→ 自動裁切該區塊為模板 + 建立 match_image 規則
4. 自動跳回規則編輯頁，顯示新建的 match_image 步驟

**與「建立為新規則」的差異：**

| | 建立為新規則（已有） | 建立為模板（新增） |
|---|---|---|
| 步驟類型 | `detect`（OCR 文字比對） | `match_image`（圖片比對） |
| 模板來源 | OCR 辨識出的文字 | 截圖裁切的圖片區塊 |
| 適用場景 | 能被 OCR 辨識的文字 | 圖標、圖片、OCR 識別不良的文字 |

---

## 二、技術分析

### 2.1 關鍵發現：色彩空間問題

**問題：** `_latest_raw` 是 **RGB** 格式，但 `match_template` 期望 **BGR** 格式。

```python
# _minimize_and_capture() 第 236 行：
img = img[:, :, ::-1].copy()   # mss 回傳 BGR → 反轉為 RGB

# img_to_b64() 第 31 行：
cv2.imencode(".png", img)       # 原樣寫入 PNG（不做色彩轉換）

# b64_to_img() 第 40 行：
cv2.imdecode(arr, IMREAD_COLOR) # 讀回時當作 BGR → R↔B 互換
```

若直接用 `_latest_raw` 裁切並呼叫 `img_to_b64()`，儲存的模板圖片會有 R↔B 互換。
執行時 `match_template()` 截圖是 BGR（mss 直出），模板是被誤讀的 RGB → **比對失敗**。

**解決方案：** 裁切後執行 `cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)` 再呼叫 `img_to_b64()`。

> 已有的 `open_capture_region` 路徑不受影響，因為它直接用 `capture()` 回傳的 BGR 陣列裁切。

### 2.2 ROI 座標系統

`_on_add_rule` 已有完整的 ROI 計算邏輯（行 412-441），需要複用：

```
1. OCR 結果的 px_x/px_y/px_w/px_h（帶 pad=20）
2. 判斷截圖來源（GDI vs mss）
3. mss 模式需扣除 chrome offset 轉換為 client 座標
4. 輸出比例座標 (0~1) + roi_coord="client"
```

「建立為模板」的 ROI 與「建立為新規則」完全相同——都是搜尋區域範圍。差異只在模板圖片本身。

### 2.3 模板 match_image 規則結構

從 `_on_debug_rule_requested`（行 4559-4620）參考，新建規則需要：

```python
Step(
    type="match_image",
    params={
        "template_data": "<base64 PNG>",    # 裁切的模板圖片
        "roi": { ... },                      # 搜尋區域（比例座標）
        "threshold": 0.8,                    # 相似度閾值
        "match_color": False,                # 灰階比對
        "color_tolerance": 100,              # 色差容許
    },
)
```

---

## 三、改動範圍

### 3.1 `gui/09_ocr_debug.py` — OCR 診斷面板

| 改動 | 位置 | 說明 |
|------|------|------|
| 新增 signal | 類別頂部（行 59-60） | `template_requested = pyqtSignal(dict)` |
| 新增按鈕 | `_init_ui`（行 168 附近） | `_template_btn = QPushButton("建立為模板(&M)")` |
| 按鈕啟用/停用 | `_on_table_selection_changed`（行 341）、`_on_image_clicked`（行 358）、`_take_snapshot`（行 253） | 與 `_add_rule_btn` 同步 |
| 新增方法 | 類別方法 | `_on_add_template()` — 核心邏輯 |

### 3.2 `gui/06_gui_main.py` — 主視窗

| 改動 | 位置 | 說明 |
|------|------|------|
| 連接 signal | `_setup_debug_page`（行 2669-2672） | `self._debug_panel.template_requested.connect(self._on_debug_template_requested)` |
| 新增 handler | 類別方法（`_on_debug_rule_requested` 附近） | `_on_debug_template_requested()` — 建立 match_image 規則 |

### 3.3 不需改動的文件

- `core/11_template_matching.py` — `img_to_b64()` / `b64_to_img()` 不需修改
- `gui/14_capture_region.py` — 已有的截取區域流程不受影響
- `gui/screenshot_controller.py` — 不需修改

---

## 四、詳細實作方案

### 4.1 `gui/09_ocr_debug.py` 改動

#### 4.1.1 新增 signal

```python
class OcrDebugPanel(QWidget):
    rule_requested = pyqtSignal(dict)
    step_requested = pyqtSignal(dict)
    template_requested = pyqtSignal(dict)   # ← 新增
```

#### 4.1.2 新增按鈕（在 `_add_rule_btn` 之後）

```python
self._template_btn = QPushButton("建立為模板(&M)")
self._template_btn.setEnabled(False)
self._template_btn.setToolTip("將選取的區塊截圖建立為圖片比對規則 (match_image)")
self._template_btn.clicked.connect(self._on_add_template)
right_layout.addWidget(self._template_btn)
```

#### 4.1.3 按鈕啟用/停用同步

在以下方法中，與 `_add_rule_btn` 同步：

- `_take_snapshot`（行 260）：加 `self._template_btn.setEnabled(False)`
- `_on_table_selection_changed`（行 346/350）：`self._template_btn.setEnabled(True/False)`
- `_on_image_clicked`（行 389）：`self._template_btn.setEnabled(True)`

#### 4.1.4 核心方法 `_on_add_template()`

```python
def _on_add_template(self):
    import cv2 as _cv2
    from core_11_tmpl import img_to_b64  # 透過 load_sibling

    if self._selected_index < 0 or self._selected_index >= len(self._ocr_results):
        return
    r = self._ocr_results[self._selected_index]

    # 1. 取得截圖尺寸
    img_h, img_w = self._latest_raw.shape[:2] if self._latest_raw is not None else (0, 0)
    if img_w < 1 or img_h < 1:
        return

    # 2. 計算 ROI（與 _on_add_rule 相同的 pad=20 邏輯）
    pad = 20
    px_x = max(0, r.x - pad)
    px_y = max(0, r.y - pad)
    px_w = min(img_w - px_x, r.w + pad * 2)
    px_h = min(img_h - px_y, r.h + pad * 2)

    chrome = _screenshot.get_window_client_offset(self._window_title) or (0, 0)
    cx, cy = chrome
    is_gdi = self._capture_source == "GDI 截圖"
    if is_gdi or (cx <= 0 and cy <= 0):
        roi = {
            "x": px_x / img_w,
            "y": px_y / img_h,
            "w": px_w / img_w,
            "h": px_h / img_h,
            "roi_coord": "client",
        }
    else:
        client_w = img_w - cx
        client_h = img_h - cy
        roi = {
            "x": max(0.0, (px_x - cx) / client_w) if client_w > 0 else 0.0,
            "y": max(0.0, (px_y - cy) / client_h) if client_h > 0 else 0.0,
            "w": min(1.0, px_w / client_w) if client_w > 0 else 0.0,
            "h": min(1.0, px_h / client_h) if client_h > 0 else 0.0,
            "roi_coord": "client",
        }

    # 3. 裁切模板圖片 + 色彩空間轉換（RGB → BGR）
    crop = self._latest_raw[px_y : px_y + px_h, px_x : px_x + px_w].copy()
    crop_bgr = _cv2.cvtColor(crop, _cv2.COLOR_RGB2BGR)
    template_b64 = img_to_b64(crop_bgr)

    # 4. 發出信號
    self.template_requested.emit(
        {
            "template_data": template_b64,
            "roi": roi,
            "name": r.text,
        }
    )

    self._status_bar.showMessage(
        f"✓ 已建立模板規則：「{r.text}」  模板: {px_w}×{px_h}px"
    )
```

### 4.2 `gui/06_gui_main.py` 改動

#### 4.2.1 連接 signal（在 `_setup_debug_page` 中）

```python
self._debug_panel.template_requested.connect(self._on_debug_template_requested)
```

#### 4.2.2 新增 handler

```python
def _on_debug_template_requested(self, data: dict):
    import uuid

    rule = Rule(
        id=f"rule_{uuid.uuid4().hex[:8]}",
        name=data.get("name", "模板規則"),
        enabled=True,
        steps=[
            Step(
                type="match_image",
                params={
                    "template_data": data.get("template_data", ""),
                    "roi": data.get("roi", {"x": 0, "y": 0, "w": 0, "h": 0}),
                    "threshold": 0.8,
                    "match_color": False,
                    "color_tolerance": 100,
                },
            ),
            Step(
                type="click",
                params={
                    "target": "template_center",
                    "button": "left",
                    "random_offset": 3,
                    "x": 0,
                    "y": 0,
                },
            ),
            Step(
                type="wait",
                params={"ms": 100},
            ),
        ],
    )
    self._rules.append(rule)
    _main_loop_mod.log_main(
        f"規則「{rule.name}」從 OCR 診斛建立為模板 (id={rule.id})"
    )
    # 規則加入群組（與 _on_debug_rule_requested 相同邏輯）
    target_group = None
    item = self._rule_list.currentItem()
    if item:
        data_item = item.data(0, Qt.ItemDataRole.UserRole)
        if data_item:
            if data_item[0] == "group":
                gid = data_item[1]
            else:
                parent = item.parent()
                if parent:
                    pdata = parent.data(0, Qt.ItemDataRole.UserRole)
                    gid = pdata[1] if pdata and pdata[0] == "group" else None
                else:
                    gid = None
            if gid:
                target_group = next((g for g in self._groups if g.id == gid), None)
    if target_group is None and self._groups:
        target_group = self._groups[0]
    if target_group:
        target_group.rule_ids.append(rule.id)
    self._flush_save()
    self._selected_rule_id = rule.id
    self._refresh_rule_list(target_group.id if target_group else None)
    self._main_stack.setCurrentIndex(0)
    self._debug_btn.setText("OCR 診斷")
    self._show_rule_detail(rule)
    self._status_bar.showMessage(f"已從 OCR 診斷建立模板規則：「{data.get('name', '')}」")
```

---

## 五、風險與緩解

### 5.1 色彩空間錯誤（高風險）

**問題：** `_latest_raw` 是 RGB，`match_template` 期望 BGR。
**緩解：** 裁切後轉換 `cv2.COLOR_RGB2BGR`。
**驗證：** 建立模板後用「圖片比對」按鈕測試。

### 5.2 模板品質不佳（中風險）

**問題：** pad=20 的裁切範圍可能不夠或太多。
**緩解：**
- 套用與「建立為新規則」相同的 pad=20，保持一致性
- 使用者可在 match_image 步驟表單中重新截取區域來修正
- 後續可考慮手動框選模板（需要額外 overlay，本次不做）

### 5.3 截圖過期（低風險）

**問題：** 使用者拍照後等待太久才點「建立為模板」。
**緩解：** 這是所有「拍一張」功能的共通限制，非本功能特有。使用者可重新拍一張。

### 5.4 ROI 座標與模板不匹配（中風險）

**問題：** ROI 搜尋範圍是 pad=20 的文字區塊範圍，但模板是同一個裁切範圍。執行時 `match_template` 會在 ROI 範圍內搜尋模板，而模板本身 = ROI 範圍 → 一定找到（閾值低時）。
**分析：** 這其實是正確行為。ROI 限定搜尋範圍（避免全螢幕搜尋），模板是目標外觀。如果 ROI == 模板範圍，效果等同全螢幕搜尋但限縮範圍，這沒問題。實際執行時視窗可能有微小變化，ROI 略大於模板是合理的。

---

## 六、與既有代碼的重複問題

### 6.1 ROI 計算重複

`_on_add_rule`（行 407-441）和 `_on_add_template` 需要完全相同的 ROI 計算。

**方案 A（推薦 — 懒惰原則）：** 提取 `_compute_roi()` 輔助方法，兩個方法共用。
**方案 B：** 直接複製貼上（~25 行）。

考慮到這是唯一一處共用，且 `_on_add_rule` 只被呼叫一次，方案 B 更「懶惰」。但方案 A 乾淨且只多一個私有方法，**建議用方案 A**。

```python
def _compute_roi(self) -> tuple[dict, int, int, int, int]:
    """回傳 (roi_dict, px_x, px_y, px_w, px_h)"""
    r = self._ocr_results[self._selected_index]
    pad = 20
    img_h, img_w = self._latest_raw.shape[:2] if self._latest_raw is not None else (0, 0)
    px_x = max(0, r.x - pad)
    px_y = max(0, r.y - pad)
    px_w = min(img_w - px_x, r.w + pad * 2)
    px_h = min(img_h - py_y, r.h + pad * 2)
    # ... 座標轉換 ...
    return roi, px_x, px_y, px_w, px_h
```

### 6.2 規則加入群組邏輯重複

`_on_debug_rule_requested`（行 4594-4616）和 `_on_debug_template_requested` 需要相同的「找到當前群組並加入」邏輯。

**方案：** 提取 `_add_rule_to_current_group(rule)` 輔助方法，兩個 handler 共用。但這在 `gui/06_gui_main.py`（5100 行）中，改動成本較高。

**替代方案：** 直接複製貼上（~25 行），保持與 `_on_debug_rule_requested` 完全對稱。**建議此方案**，因為 `_on_debug_rule_requested` 本身也不太可能再被複用。

---

## 七、實施順序

```
1. gui/09_ocr_debug.py — 新增 signal + 按鈕 + _on_add_template
2. gui/06_gui_main.py — 連接 signal + _on_debug_template_requested
3. ruff check + format
4. self-check（如有）
5. graphify update
6. git add + commit + push
```

---

## 八、驗收清單

### 功能

- [ ] OCR 診斷面板出現「建立為模板」按鈕
- [ ] 未選取時按鈕停用，選取後啟用
- [ ] 點擊後建立 match_image 規則（非 detect 規則）
- [ ] 模板圖片正確（色彩無誤、裁切範圍合理）
- [ ] 自動跳回規則編輯頁，顯示 match_image 步驟
- [ ] 規則加入當前選取的群組
- [ ] 模板規則可正常執行（「圖片比對」按鈕可驗證）

### 回歸

- [ ] 「建立為新規則」功能不受影響
- [ ] 「加入偵測步驟」功能不受影響
- [ ] OCR 診斷面板其他功能正常
- [ ] 現有 match_image 規則正常載入執行

---

## 九、附錄

### A. 相關文件索引

| 文件 | 本次改動 | 角色 |
|------|----------|------|
| `gui/09_ocr_debug.py` | ✅ 新增 signal + 按鈕 + 方法 | OCR 診斷面板（前端） |
| `gui/06_gui_main.py` | ✅ 連接 signal + handler | 主視窗（後端） |
| `core/11_template_matching.py` | ❌ 不改 | `img_to_b64` / `match_template` |
| `gui/14_capture_region.py` | ❌ 不改 | 已有截取區域流程（參考用） |
| `gui/screenshot_controller.py` | ❌ 不改 | 已有 capture callback（參考用） |

### B. 關鍵行號索引

| 位置 | 行號 | 內容 |
|------|------|------|
| `09_ocr_debug.py` signal 定義 | 58-60 | `rule_requested`, `step_requested` |
| `09_ocr_debug.py` 按鈕區 | 164-174 | `_add_rule_btn`, `_set_sub_target_btn` |
| `09_ocr_debug.py` 選取切換 | 341-356 | `_on_table_selection_changed` |
| `09_ocr_debug.py` ROI 計算 | 407-441 | `_on_add_rule` |
| `06_gui_main.py` debug signal 連接 | 2669-2672 | `.connect()` |
| `06_gui_main.py` rule handler | 4559-4620 | `_on_debug_rule_requested` |
| `06_gui_main.py` step handler | 4622-4641 | `_on_debug_step_requested` |
| `11_template_matching.py` img_to_b64 | 31-33 | `cv2.imencode` |

---

*文件結束*
