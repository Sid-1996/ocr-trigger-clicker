# OCR Trigger Clicker — 專案診斷報告 v2

> **診斷範圍：** 10 個核心模組 + 1 個 AHK 腳本，共 ~6,600 行程式碼
> **診斷日期：** 2026-06-25
> **版本：** v0.0.2

---

## 一、專案概貌

### 目的

Windows OCR 自動化工具。透過 RapidOCR 即時辨識指定視窗的螢幕文字，當偵測到規則定義的目標文字後，經由 TCP Socket 命令 AutoHotkey v2 執行滑鼠點擊 / 鍵盤動作。

### 架構風格

```
截圖 (mss / GDI)
   ↓
OCR 辨識 (RapidOCR ONNX)      ← 背景執行緒
   ↓
Step-based 規則引擎 (dataclass)
   ↓
TCP Socket → AutoHotkey v2 → 系統事件（滑鼠/鍵盤/拖曳/滾輪）
        ↑
PyQt6 GUI（規則編輯 / 診斷 / 效能監控）
```

### 優點（值得保留）

- Step pipeline 設計清晰，支援 9 種步驟類型
- V1 → V2 schema migration 設計良好，附帶 self-test
- `threading.Event` 並發控制模式一致
- 多重安全機制（失控偵測、速率限制、緊急停止、前景保護）
- OCR engine health callback + 自動重啟機制 + 版本斷言保護 monkey-patch
- 多數已診斷問題已於 v0.0.2 修正

---

## 二、尚存問題清單

### 🟠 P1 — 高優先（影響效能 / 安全 / 可維護性）

#### P1-1　OCR 相關 `print` 未完全清理

**位置：** `core/02_ocr_engine.py`

| 行號 | 內容 | 狀態 |
|------|------|------|
| 52 | `print(f"[ocr_health] {msg}")` | health callback，可保留 |
| 224 | `if _DEBUG_OCR_TIMING: print(...)` | ✅ 已包旗標 |
| 259 | `print("[OCR] timeout (30s)")` | ❌ 無旗標，生產線輸出 |
| 263 | `print(f"[OCR] exception: {e}")` | ❌ 無旗標，生產線輸出 |
| 320+ | 其餘 print | 在 `__main__` self-test 內，可接受 |

line 259 與 263 在生產運行時仍會輸出至 stdout / console。

---

#### P1-2　`_handle_collect_rounds` 內 `time.sleep(0.3)` 阻塞

**位置：** `core/05_main_loop.py:588`

```python
time.sleep(0.3)
```

位於 collect_rounds 的每次 round 之間。同類 bug（P0-3 `_handle_wait`）已修，但此處遺漏。雖然僅 0.3 秒，累積多 round 時仍會延遲停止回應。

**建議：** 改為 `self._stop_event.wait(timeout=0.3)`，中斷時回傳 stop。

---

#### P1-3　`_handle_scroll` 內 `time.sleep` 阻塞

**位置：** `core/05_main_loop.py:509`

```python
if delay_ms > 0:
    time.sleep(delay_ms / 1000.0)
```

`amount > 1` 時，每次滾輪間均 sleep，累計可達數秒，期間停止訊號被忽略。

**建議：** 改用 `self._stop_event.wait()`。

---

### 🟡 P2 — 中優先（可維護性 / 架構問題）

#### P2-1　Step defaults 在兩處重複定義

`core/04_rule_engine.py` 有 `_STEP_DEFAULTS`，`gui/06_gui_main.py` 有獨立的 `defaults` dict。新增 `drag`/`scroll`/`hold_ms` 後同步難度更高。

**修正方向：** GUI 直接匯入 `_STEP_DEFAULTS`。

---

#### P2-2　`06_gui_main.py` 單體 2,676 行

舊報告為 2,494 行，隨 `drag`/`scroll`/`regex` 編輯表單新增而繼續成長。建議拆分：

| 新檔案 | 負責內容 |
|---|---|
| `gui/task_panel.py` | 任務管理（新增 / 刪除 / 匯入匯出） |
| `gui/rule_panel.py` | 規則清單 + Step 編輯器 |
| `gui/step_forms.py` | 各類 Step 的 inline form widget |
| `gui/log_panel.py` | 觸發日誌顯示 |
| `gui/06_gui_main.py` | 主視窗組裝（縮減至 ~300 行） |

---

#### P2-3　Compat wrappers 標記 TODO 但未清理

**位置：** `core/04_rule_engine.py:559`

```python
# ── Compat wrappers (TODO Phase 2: remove) ──
```

`check_trigger`、`apply_trigger`、`get_roi` 仍存在，僅看第一個 detect/click step。

---

#### P2-4　`_loader.py` 阻止 IDE 靜態分析

動態載入讓 IDE 無法型別推斷與跳轉。數字前綴在 import 語境中是障礙。

**長期：** 保留 `_loader` 供打包用，同時保留標準 package 結構供開發。

---

### 🔵 P3 — 低優先（品質 / 維護性改善）

| # | 位置 | 問題 |
|---|------|------|
| P3-1 | `02_ocr_engine.py:22` | `_DET_USE_V5 = False` 硬編碼 |
| P3-2 | `03_ahk_socket.py` | `_restart_fail_count` 全域變數，重啟後不重置 |
| P3-3 | 全域 | 型別注解混用 `Optional[X]` 與 `X \| None` |

---

## 三、已修復問題記錄

| Commit | 位置 | 問題 | 修法 |
|--------|------|------|------|
| `3756236` | `core/01_screenshot.py` | `_mss_instance` 全域單例無鎖，主循環 background thread 與 GUI main thread 競爭導致 mss 靜默損壞，`capture()` 回傳 None | 改為 `threading.local()`，每個 thread 各持獨立 mss 實例 |
| `3756236` | `gui/09_ocr_debug.py` | GDI fallback 截的是 client area，OCR 座標從 client 左上角算起，但 `_on_click_test` 加回的是 `rect["y"]`（window 左上角含標題列），偏高約 30px | GDI 路徑改用 `ClientToScreen(hwnd, POINT(0,0))` 取得 client 原點；tooltip 加上截圖來源 |

---

## 四、新功能速覽（v0.0.2 新增，含 bugfix）

| 功能 | Commit | 說明 |
|------|--------|------|
| `match_mode: "regex"` | `770d162` | OCR 比對支援正規表達式 |
| `drag` 步驟 | `770d162` | 滑鼠拖曳（起點 + 偏移量），支援 text_center / custom / click_text |
| `scroll` 步驟 | `770d162` | 滑鼠滾輪，可設方向/次數/間隔 |
| `key` 步驟 `hold_ms` | `770d162` | 按鍵按住指定毫秒後放開 |
| `on_fail` | `3859f31` | detect 步驟未命中時的行為：continue / retry / key / jump |
| 匯入匯出 schema | `63544ce` | JSON `_meta` 格式、預覽對話框、UUID 重生 |
| 刪除規則殘留清理 | `9d5227d` | 刪除規則時自動清理其他規則的 `wait_rule`/`jump` 參照 |
| DPI 縮放修正 | `967f5a1` | 移除錯誤的 `get_dpi_scaling_factor` 乘算 |
| save_rules NameError | `967f5a1` | 補 `tmp_path: str = ""` 初始化 |

---

## 四、優化優先順序建議

```
高優先（本月）
├── P1-1  OCR print 殘留 — 將 line 259/263 改由旗標控制
├── P1-2  collect_rounds time.sleep — 改為 stop_event.wait()
└── P1-3  _handle_scroll time.sleep — 改為 stop_event.wait()

架構重構（下一個 milestone）
├── P2-1  Step defaults 單一來源
├── P2-2  GUI 拆分
├── P2-3  清理 compat wrappers
└── P2-4  標準 package 結構
```

---

*報告生成日期：2026-06-25 · 版本 v0.0.2*
