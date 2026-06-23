# OCR Trigger Clicker — 專案診斷報告

> **診斷範圍：** 13 個核心模組，共 ~5,500 行程式碼  
> **診斷日期：** 2026-06-23  
> **版本：** v0.1.0 

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
TCP Socket → AutoHotkey v2 → 系統滑鼠 / 鍵盤事件
        ↑
PyQt6 GUI（規則編輯 / 診斷 / 效能監控）
```

### 優點（值得保留）

- Step pipeline 設計清晰，支援 `detect → click → wait → jump` 等組合
- V1 → V2 schema migration 設計良好，附帶 self-test
- `threading.Event` 並發控制模式一致
- 多重安全機制（失控偵測、速率限制、緊急停止）
- OCR engine health callback + 自動重啟機制

---

## 二、診斷問題清單（28 項）

---

### 🔴 P0 — 確認性 Bug（立即影響功能）

#### P0-1　`iteration % 1` 永遠為 0，每幀都輸出日誌

**位置：** `core/05_main_loop.py` 第 665 行

```python
# 現況 ❌ — 任何整數 % 1 都等於 0，永遠為 True
if self._verbose and iteration % 1 == 0:
    self._log(f"視窗位置=({rect['x']},{rect['y']}) ...")
```

**影響：** verbose 模式下每幀都寫 log，約每 500 ms 一筆，長時間執行會讓 log 暴增，I/O 拖慢主循環。

```python
# 修正 ✅
if self._verbose and iteration % 30 == 0:
    self._log(f"視窗位置=({rect['x']},{rect['y']}) ...")
```

---

#### P0-2　fallback 截圖函數名稱錯誤，永遠取不到

**位置：** `core/05_main_loop.py` 第 32 行 vs `core/01_screenshot.py` 第 209 行

```python
# main_loop.py — 找的是 capture_window_full ❌
capture_window_full = getattr(_screenshot, "capture_window_full", lambda title: None)

# screenshot.py — 實際定義的是 capture_window_content（兩者不同！）❌
def capture_window_content(title: str) -> np.ndarray | None:
```

**影響：** 主截圖失敗時，fallback GDI 截圖永遠無法啟動（lambda 直接返回 None），且不會有任何錯誤提示。

```python
# 修正 ✅ — 統一名稱，兩者取其一
capture_window_full = getattr(_screenshot, "capture_window_content", lambda title: None)
# 並在 screenshot.py 新增別名保留相容性
capture_window_full = capture_window_content
```

---

#### P0-3　`_handle_wait` 阻塞執行緒，無法響應停止訊號

**位置：** `core/05_main_loop.py` `_handle_wait` 函式

```python
def _handle_wait(self, params, ctx, rule) -> StepResult:
    ms = params.get("ms", 1000)
    if ms > 0:
        time.sleep(ms / 1000.0)   # ❌ 阻塞期間 F12 / stop() 無效
    return StepResult("continue")
```

**影響：** 規則設定 `wait 30000 ms` 時，緊急停止或手動停止需等 30 秒。

```python
# 修正 ✅ — 改用 stop_event.wait()，可隨時中斷
def _handle_wait(self, params, ctx, rule) -> StepResult:
    ms = params.get("ms", 1000)
    if ms > 0:
        interrupted = self._stop_event.wait(timeout=ms / 1000.0)
        if interrupted:
            return StepResult("stop")
    return StepResult("continue")
```

---

#### P0-4　`save_rules` 非原子寫入，crash 會損毀 JSON

**位置：** `core/04_rule_engine.py` `save_rules` 函式

```python
def save_rules(rules, path) -> bool:
    with open(path, "w", encoding="utf-8") as f:   # ❌ 直接覆蓋
        json.dump(data, f, indent=2, ensure_ascii=False)
```

**影響：** 寫入途中若 crash 或斷電，原始 JSON 被截斷，下次啟動讀取失敗，規則全部消失。

```python
# 修正 ✅ — 先寫暫存檔，成功後再 rename（原子操作）
import tempfile, os

def save_rules(rules, path) -> bool:
    p = Path(path)
    data = {"rules": [_rule_to_dict(r) for r in rules]}
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=p.parent, suffix=".tmp",
            delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp_path = tmp.name
        os.replace(tmp_path, p)   # 原子操作
        return True
    except OSError:
        Path(tmp_path).unlink(missing_ok=True)
        return False
```

---

### 🟠 P1 — 高優先（影響效能 / 安全 / 可維護性）

#### P1-1　OCR 計時每次都輸出至 stdout，無法關閉

**位置：** `core/02_ocr_engine.py` 第 212–215 行

```python
# ❌ 硬塞的 print，生產版也會輸出
timings = result[1]
det_ms = timings[0] * 1000
rec_ms = timings[2] * 1000
print(f"[OCR] {det_ms:.0f}ms(檢測) + {rec_ms:.0f}ms(辨識)")
```

每次 OCR 都 print，每秒最多觸發 10 次，對 console、日誌重定向都造成噪音。

```python
# 修正 ✅ — 加 debug 旗標，或移除（perf stats 已有 ocr_latency 追蹤）
if _DEBUG_OCR_TIMING:
    print(f"[OCR] {det_ms:.0f}ms + {rec_ms:.0f}ms")
```

---

#### P1-2　`send_key` 指令未過濾換行，存在 TCP 指令注入風險

**位置：** `core/03_ahk_socket.py` 第 354 行

```python
def send_key(key: str) -> bool:
    return _send_cmd(f"KEY,{key}")   # ❌ key 含 \n 可注入額外指令
```

若 `key = "Enter\nESTOP"` 則會傳送兩條指令。

```python
# 修正 ✅
def send_key(key: str) -> bool:
    key = key.strip().replace("\n", "").replace("\r", "")
    if not key:
        return False
    return _send_cmd(f"KEY,{key}")
```

---

#### P1-3　`capture()` 每次呼叫都重建 `mss.mss()` 實例

**位置：** `core/01_screenshot.py` 第 92 行

```python
def capture(title: str) -> np.ndarray | None:
    with mss.mss() as sct:   # ❌ 每次截圖都重建，約 2–5 ms overhead
        ...
```

主循環每 500 ms 呼叫一次，重建 mss 浪費資源。mss 官方建議複用實例。

```python
# 修正 ✅ — 模組級單例（shutdown 時呼叫 .close() 清理）
_mss_instance: mss.mss | None = None

def _get_mss() -> mss.mss:
    global _mss_instance
    if _mss_instance is None:
        _mss_instance = mss.mss()
    return _mss_instance
```

---

#### ~~P1-4　`_execute_forced_trigger` 複製了 handler 邏輯~~ ✅ 已修正

**commit:** f0cfc04

jump 與 on_all_fail 現直接呼叫 `_run_rule`（含完整 detect → click/key 流程），`_execute_forced_trigger` 已移除。

---

#### P1-5　`poll_roi_value` 用 `time.sleep(0.2)` 無法中斷

**位置：** `core/05_main_loop.py` 第 67–82 行

`collect_rounds` 的 ROI 輪詢最長可阻塞 `timeout_ms`（預設 3000 ms），期間 stop_event 被忽略。

```python
# 修正 ✅ — 傳入 stop_event 並在 sleep 改用 Event.wait()
def poll_roi_value(roi, pick, timeout_ms, title, stop_event=None):
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if stop_event and stop_event.is_set():
            return None
        ...
        if (stop_event or threading.Event()).wait(timeout=0.2):
            return None
    return None
```

---

#### P1-6　前景視窗保護不可設定，主循環無條件跳過非前景視窗

**位置：** `core/05_main_loop.py` 第 632–635 行

```python
if not is_window_foreground(self._window_hwnd):
    self._stop_event.wait(0.2)
    self._perf.record_frame()
    continue   # ❌ 永遠跳過背景視窗，README 說「可設定」但實際無法關閉
```

README 明確說「可設定僅在前景時才執行」，但目前是強制開啟。

```python
# 修正 ✅ — 加入 foreground_only 設定項
if self._foreground_only and not is_window_foreground(self._window_hwnd):
    ...
```

---

### 🟡 P2 — 中優先（可維護性 / 架構問題）

#### P2-1　Step defaults 在兩處重複定義，容易不同步

`core/04_rule_engine.py` 有 `_STEP_DEFAULTS`（第 59–86 行），  
`gui/06_gui_main.py` 有獨立的 `defaults` dict（第 421–447 行）。

**修正方向：** GUI 直接匯入並使用 `_STEP_DEFAULTS`，單一來源：

```python
from core.rule_engine import _STEP_DEFAULTS
step = Step(type=step_type, params=deepcopy(_STEP_DEFAULTS.get(step_type, {})))
```

---

#### P2-2　TCP Port 跨檔案不一致，無法統一修改

- `core/03_ahk_socket.py`：`init_ahk(port=12345)` ✅ 可配置  
- `clicker.ahk` 第 20 行：`PORT := 12345` ❌ 硬編碼

修改 Python 端 port 後，AHK 端不會自動同步。

**修正方向：** 透過 AHK 命令列參數傳入 port：

```python
# Python 端
_ahk_process = subprocess.Popen([exe_path, ahk_script, str(port)], ...)
```

```ahk
; clicker.ahk
PORT := A_Args.Length > 0 ? Integer(A_Args[1]) : 12345
```

---

#### P2-3　`06_gui_main.py` 單體 2,494 行，難以維護

建議拆分：

| 新檔案 | 負責內容 |
|---|---|
| `gui/task_panel.py` | 任務管理（新增 / 刪除 / 匯入匯出） |
| `gui/rule_panel.py` | 規則清單 + Step 編輯器 |
| `gui/step_forms.py` | 各類 Step 的 inline form widget |
| `gui/log_panel.py` | 觸發日誌顯示 |
| `gui/06_gui_main.py` | 主視窗組裝（縮減至 ~300 行） |

---

#### P2-4　compat 包裝函數標記 TODO 但未清理

**位置：** `core/04_rule_engine.py` 第 419–491 行

```python
# ── Compat wrappers (TODO Phase 2: remove) ──
def check_trigger(...):  # TODO Phase 2: remove
def apply_trigger(...):  # TODO Phase 2: remove
def get_roi(...):        # TODO Phase 2: remove
```

這些函數只看第一個 detect/click step，對多步驟規則會給出錯誤結果。如有外部呼叫者依賴這些，應追蹤並移除。

---

#### P2-5　Log 系統缺少 rotation，長期執行會無限增長

**位置：** `core/05_main_loop.py` 第 164–166 行

```python
self._log_file = open(
    self._log_dir / f"{time.strftime('%Y-%m-%d')}.log", "a", encoding="utf-8"
)
```

沒有單檔大小限制；日期切換靠檔名，但 `_log_file` 不會在跨日後自動換新檔。

```python
# 修正 ✅ — 使用標準 logging 模組 + TimedRotatingFileHandler
import logging
from logging.handlers import TimedRotatingFileHandler

logger = logging.getLogger("main_loop")
handler = TimedRotatingFileHandler(
    log_dir / "main.log", when="midnight", backupCount=7, encoding="utf-8"
)
logger.addHandler(handler)
```

---

#### P2-6　OCR `resize_norm_img` monkey-patch 脆弱

**位置：** `core/02_ocr_engine.py` 第 127–134 行

深入修改 RapidOCR 內部 `text_rec.resize_norm_img` 方法，任何版本更新都可能讓 patch 失效甚至靜默產生錯誤結果。

**建議：** 在 monkey-patch 處加上版本斷言，防止靜默出錯：

```python
import rapidocr_onnxruntime
assert rapidocr_onnxruntime.__version__ == "1.3.x", \
    "RapidOCR 版本異動，請重新驗證 resize_norm_img patch"
```

---

#### P2-7　`_loader.py` 阻止 IDE 靜態分析，數字前綴影響可讀性

`load_sibling("screenshot", "core/01_screenshot.py")` 等動態載入讓 IDE 無法提供型別推斷與跳轉。  
數字前綴（`01_`、`02_`）雖有排序意義，但在 Python import 語境中反而是障礙。

**長期建議：** 保留 `_loader` 供打包用，同時保留一份以標準 package 結構（`core/__init__.py`）的可直接 import 路徑。

---

### 🔵 P3 — 低優先（品質 / 維護性改善）

| # | 位置 | 問題 | 建議 |
|---|---|---|---|
| P3-1 | `_version.py` | 版本 `0.1.0` 功能已達 0.3+ 水準 | 更新至語義版號 |
| P3-2 | 根目錄 | 缺 `requirements.txt` / `pyproject.toml` 依賴清單 | 補上依賴與 Python 版本約束 |
| P3-3 | 各 `__main__` 測試 | Self-test 無法被 pytest 自動發現 | 遷移至 `tests/` 目錄，使用 pytest |
| P3-4 | `02_ocr_engine.py:22` | `_DET_USE_V5 = False` 硬編碼 | 透過 config / GUI 開關控制 |
| P3-5 | `05_main_loop.py:173` | Log 只寫 `HH:MM:SS`，跨日無法對應 | 改為 `%Y-%m-%d %H:%M:%S` |
| P3-6 | `01_screenshot.py:209` | 函數名 `capture_window_content` vs 使用方預期 `capture_window_full` | 統一命名並加別名 |
| P3-7 | `06_gui_main.py:448` | `from core.rule_engine import Step` 在函數體內 | 移至模組頂部 |
| P3-8 | 全域 | 型別注解混用 `Optional[X]`（py3.9 前）與 `X \| None`（py3.10+） | 統一使用 `X \| Y` 語法（已用 3.12） |
| P3-9 | `03_ahk_socket.py:19` | `_restart_fail_count` 全域變數，重啟後不重置 | 移至 instance 變數或加重置邏輯 |
| P3-10 | `03_ahk_socket.py:275` | `init_ahk` 呼叫兩次返回 `True`，但未驗證 AHK 版本 | 啟動後以 `VERSION` 指令驗證 AHK v2 |

---

## 三、優化優先順序建議

```
立即修復（本週）
├── P0-1  iteration % 1 日誌洪水
├── P0-2  capture_window_full 名稱錯誤
├── P0-3  _handle_wait 阻塞 stop_event
└── P0-4  save_rules 非原子寫入

高優先（本月）
├── P1-1  OCR stdout 噪音
├── P1-2  send_key 指令注入
├── P1-3  mss 每次重建
├── P1-4  forced trigger 邏輯重複
├── P1-5  poll_roi 無法中斷
└── P1-6  前景保護可設定化

架構重構（下一個 milestone）
├── P2-3  GUI 拆分
├── P2-5  改用 logging 模組
├── P2-1  Step defaults 單一來源
├── P2-2  AHK port 統一
├── P2-4  清除 compat wrappers
└── P3-3  遷移至 pytest
```

---

## 四、快速修復一覽（可直接套用）

```python
# ① P0-1 ── 05_main_loop.py 第 665 行
# 將 iteration % 1 改為 iteration % 30
if self._verbose and iteration % 30 == 0:

# ② P0-2 ── 05_main_loop.py 第 32 行
capture_window_full = getattr(_screenshot, "capture_window_content", lambda title: None)

# ③ P0-3 ── 05_main_loop.py _handle_wait
def _handle_wait(self, params, ctx, rule):
    ms = params.get("ms", 1000)
    if ms > 0:
        interrupted = self._stop_event.wait(timeout=ms / 1000.0)
        if interrupted:
            return StepResult("stop")
    return StepResult("continue")

# ④ P0-4 ── 04_rule_engine.py save_rules（原子寫入）
import tempfile, os
with tempfile.NamedTemporaryFile(
    "w", dir=p.parent, suffix=".tmp", delete=False, encoding="utf-8"
) as tmp:
    json.dump(data, tmp, indent=2, ensure_ascii=False)
    tmp_path = tmp.name
os.replace(tmp_path, p)

# ⑤ P1-2 ── 03_ahk_socket.py send_key
def send_key(key: str) -> bool:
    key = key.strip().replace("\n", "").replace("\r", "")
    if not key:
        return False
    return _send_cmd(f"KEY,{key}")
```

---

*報告由 Tabbit 自動分析生成 · 2026-06-23*