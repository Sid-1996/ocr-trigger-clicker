# 優化計畫書：導入 ok-script 概念

> 目標：參考 ok-script 實作，以 ocr-trigger-clicker 既有設計風格為核心，導入三個優化項目

---

## 總覽

| 項目 | 優先級 | 影響範圍 | 風險 | 估計工時 |
|------|--------|----------|------|----------|
| 1. AHK 替換為 pynput | P0 | AHK socket + MainLoop + GUI + i18n + build | 中（取代外部相依） | 1~2 sessions |
| 2. 多重截圖後端 | P1 | 截圖模組 + 主循環 | 中（WGC 複雜度高） | 2~3 sessions |
| 3. Box 座標工具集 | P2 | rule_models + migration + serialization | 低（加工具不刪既有） | 1 session |

執行順序：1 → 2 → 3（相依性遞減，風險遞減）

---

## 完成標準（共用於所有 Phase）

每個 Phase 完成前需通過以下驗收：

- [ ] ruff check + format 無 error
- [ ] 改動過的核心模組（`core/` 下）的 `if __name__ == "__main__"` self-check 全部通過
- [ ] `tests/` 目錄下的 pytest 全部通過（`python -m pytest`）
- [ ] `git status` 顯示預期改動檔案，無遺漏
- [ ] 基本功能手動測試：開工具 → 載入既有任務 → 啟動循環 → 確認規則正常執行

若 Phase 失敗，回溯程序：
1. `git checkout master`（回到主分支）
2. `git branch -D backup/pre-optimization` 刪除備份分支（選擇性）
3. `git checkout -b backup/pre-optimization` 重建備份分支（若已刪除，直接從 `git archive` 備份還原）

---

## 項目一：AHK 替換為 pynput

### 現狀

`core/03_ahk_socket.py`（461 行）：
- TCP socket server 等待 AHK.exe 連線
- 需下載 AHK v2（10MB ZIP + 解壓）
- Heartbeat 執行緒每 5 秒 PING
- 失敗自動重啟（kill + relaunch）
- 支援命令：CLICK / KEY / DRAG / SCROLL / HOLDKEY / ESTOP
- 螢幕邊界驗證防止點擊超出螢幕

**受影響的完整檔案列表（不限 core/）：**

| 檔案 | 行數 | 影響 |
|------|------|------|
| `core/03_ahk_socket.py` | 461 | 整份移除 |
| `core/05_main_loop.py` | 導入 + 5 處呼叫 | 改 import + 改 5 個函式呼叫 |
| `core/05_main_loop.py` | 1466-1469 | self-check 中 mock `_ahk.send_key` 需更新 |
| `gui/06_gui_main.py` | 2469 模組級 import | 改載入新模組 |
| `gui/06_gui_main.py` | 3104-3174 | AHK 初始化 + 下載流程 (~80 行) |
| `gui/06_gui_main.py` | 3498-3500 | `_ahk_status_label` 狀態列元件 |
| `gui/06_gui_main.py` | 3563-3573 | `_update_ahk_status()` 方法 |
| `gui/06_gui_main.py` | 5736 | `_ahk_mod.shutdown()` 清理邏輯 |
| `gui/09_ocr_debug.py` | 643-646 | 除錯面板點擊測試用 AHK 呼叫 |
| `build.py` | 58-60 | `clicker.ahk` 資料檔包含 |
| `build.py` | 160 | pynput 列於排除清單！需移出 |
| `i18n/zh_TW.json` | ~294 | `update.download_ahk` 等 7 個 key |
| `i18n/zh_CN.json` | ~294 | 同上 |
| `i18n/en.json` | ~294 | 同上 |
| `clicker.ahk` | ~? | 整份移除 |
| `ARCHITECTURE.md` | 67, 319, 514 | 更新規格文件 |

### 參考（ok-script pynput）

`ok/device/interaction_methods/pynput.py`（207 行）：
- `pynput.mouse.Controller` + `pynput.keyboard.Controller`
- click / send_key / send_key_down/send_key_up / scroll / move / swipe
- 需要管理員權限（GetForegroundWindow 驗證）
- 有 KEY_MAP 做按鍵名轉換

### 設計原則（ponytail）

- 不要複製 BaseInteraction 類別層級 —— 只要一個簡單的模組級函式集合
- 不要引入額外抽象層：`send_click(x, y, button)` → `send_key(key)` → `send_scroll(dir)` 保持不變
- 保留現有 API 簽名，讓 MainLoop 完全無感切換
- 保留螢幕邊界驗證

### 實作方案

**新檔案：`core/03_pynput_input.py`**

取代 `03_ahk_socket.py` 的 send_click/send_key/send_scroll/send_drag/send_hold_key。
API 完全相容，MainLoop 只需改 import 來源。

**移除的模組與檔案：**
- `core/03_ahk_socket.py` — 整份取代
- `clicker.ahk` — AHK 腳本不再需要
- `_ahk_data_dir()` / `_find_ahk_executable()` — AHK 搜尋/下載邏輯
- `_heartbeat_loop` / `_restart_ahk` — 心跳與重啟邏輯
- `download_ahk()` / `is_ahk_available()` — 不需要下載與檢查
- `init_ahk()` / `shutdown()` / `set_ahk_health_callback()` — 不需要初始化

**保留的功能：**
- `_validate_coords(x, y)` → 內聯到新檔案
- `send_emergency_stop()` → 保留為空殼（保持介面相容，僅記錄 log 並設定 stop_event）

**MainLoop 改動（core/05_main_loop.py）：**
- `_ahk = load_sibling("ahk_socket", ...)` → `_ahk = load_sibling("pynput_input", ...)`
- `_ahk.send_emergency_stop()` → 改為空操作或只設 stop_event
- self-check 中 `_ahk.send_key` mock → 改為 mock 新模組的同名函式

**GUI 改動（gui/06_gui_main.py）：**
- `_ahk_mod = load_sibling(...)` → 載入新模組
- 移除 `_init_ahk_async()` / `_prompt_ahk_install()` / `_on_ahk_init_done()` 整段 AHK 初始化與下載流程
- `_ahk_status_label` → 改為 `_input_status_label`，顯示 🟢 Input（無需初始化，永遠為綠）
- `_update_ahk_status()` → `_update_input_status()` 始終設定為連線成功
- `_quit_app()` 中移除 `_ahk_mod.shutdown()`（無需關閉外部行程）

**GUI 改動（gui/09_ocr_debug.py）：**
- `_ahk.send_click()` → 改為新模組
- `_ahk.init_ahk()` 重試邏輯 → 無需重試，直接呼叫

**依賴管理：**
- `pip install pynput`（專案根目錄執行）
- `build.py` 排除清單中移除 `"pynput"` 項目（若需要的話加入 `--hidden-import=pynput`）
- 無需 `pyproject.toml` 改動（目前無 dependencies 區段）

**i18n 改動：**
移除或重新命名以下 key（三份 JSON 都要改）：

| 舊 key | 處理 |
|--------|------|
| `update.download_ahk` | 移除 |
| `status.ahk_not_installed` | 移除 |
| `status.ahk_starting` | 移除 |
| `status.ahk_not_started` | 移除 |
| `status.ahk_ready` | 移除 |
| `dialog.install_ahk` | 移除 |
| `dialog.install_ahk_msg` | 移除 |
| `dialog.install_ahk_success` | 移除 |

完成後執行 `python -m i18n.check` 確認三語言 key set 一致性。（檢查機制見 `i18n/check.py`）

### AHK 專屬功能落差

| 功能 | 現狀 | pynput 替代 |
|------|------|-------------|
| click | send_click(x,y,button) | pynput.mouse.Controller.click |
| key | send_key(key) | pynput.keyboard.Controller.press/release |
| hold_key | send_hold_key(key, ms) | press + time.sleep + release |
| drag | send_drag(x1,y1,x2,y2) | mouse.position + press + move + release |
| scroll | send_scroll(amount, dir) | mouse.Controller.scroll |
| emergency_stop | send_emergency_stop() → kill AHK process | 空殼（in-process 只設 stop_event） |
| 前景驗證 | AHK 端 `WinActive` | pynput 層用 `GetForegroundWindow()` + `_is_tool_foreground()` |
| 速率限制 | MainLoop `_can_perform_action()` | 不變 |
| 回傳值 | True/False（TCP 通訊結果） | True/False（pynput 無回傳值，成功不拋異常即 True） |

全部可對應，無功能遺失。

**緊急停止行為差異（重要）：**
AHK 版本：`send_emergency_stop()` 透過 TCP 發送 ESTOP 指令給外部行程，可立即中斷任何進行中的點擊/按鍵。
pynput 版本：無外部行程可殺。若正在執行 `hold_key` 的 `time.sleep` 期間觸發緊急停止，pynput 無法中途 release key（`pynput.keyboard.Controller.press()` 是 Windows API `SendInput` 呼叫，release 前都會保持按壓狀態）。影響範圍：
- `_handle_key` 的 hold_ms（長按）— 風險：key 可能卡住直到 sleep 結束
- `_handle_scroll` 的多次滾輪 loop — 此路徑有檢查 `_stop_event`，可中斷

緩解：緊急停止時發送對應的 release 事件（先設 stop_event，再發送 keyboard. release）。但這無法保證在 sleep 期間即時生效。

### 風險與緩解

| 風險 | 緩解 |
|------|------|
| pynput 需管理員權限才能跨前景點擊 | 維持前景檢查，記錄警告；若無管理員權限，部分遊戲可能無法點擊 |
| 按鍵名稱對應不完整 | 參考 AHK v2 KeyList 建立完整 KEY_MAP |
| 既有任務中的 hold_ms 功能 | 保持不變，pynput 層做 press + sleep + release |
| Self-check 中的 AHK mock 需更新 | 對應改為 mock 新模組的同名函式 |
| GUI 大範圍改動可能遺漏 signal/slot 連結 | 改動後執行 `rg "ahk\|AHK"` 確認無殘留 |
| i18n key 遺漏更新導致 key 顯示原始文字 | 三份 JSON 同步修改後執行 `python -m i18n.check` |
| 若 pynput 在某些環境（如特定防作弊遊戲）失效 | 回溯程序：見上方「完成標準」章節 |

---

## 項目二：多重截圖後端

### 現狀

`core/01_screenshot.py`（262 行）：
- `capture(title)` → mss 截圖含邊框
- `capture_window_content(title)` → GDI PrintWindow / BitBlt 僅客戶區
- 備援鏈：mss → PrintWindow → BitBlt
- `_mss_tls` thread-local 避免多執行緒問題
- 多螢幕支援（自動找涵蓋視窗的螢幕）
- DPI 感知（GetDpiForWindow）
- `_matching_windows()` 精確比對優先

### 參考（ok-script capture_methods/）

ok-script 有 7 種後端 + 完整類別層級 + `update.py` 設定驅動選擇。但 ok-script 的設計對 ocr-trigger-clicker 來說太重（類別層級 + 設定驅動 + 動態探索）。

### 設計原則（ponytail）

- 不要 class hierarchy。保持函式級別：`_capture_mss()`、`_capture_gdi()`、`_capture_wgc()`
- 不要動態探索。保持明確備援鏈：mss → GDI → WGC
- 不要額外 config 欄位。使用者不需要知道哪個後端
- 唯一值得新增的是 WGC（Windows.Graphics.Capture）

### 實作方案

**改動範圍：`core/01_screenshot.py`**

現有結構不做大重構，只在檔案尾端附加 WGC 截圖函式。備援鏈改為：

```python
def capture(title: str) -> np.ndarray | None:
    rect = get_window_rect(title)
    if rect is None:
        return None
    # 1. mss（現有邏輯）
    img = _capture_mss(title, rect)
    if img is not None:
        return img
    # 2. WGC（新增，比 GDI 優先因為相容性更高）
    img = _capture_wgc(title)
    if img is not None:
        return _wrap_to_full_window(img, title, rect)
    # 3. GDI fallback（既有的 capture_window_content）
    img = capture_window_content(title)
    if img is not None:
        return _wrap_to_full_window(img, title, rect)
    return None
```

**WGC 實作方式：**

提供兩種方案，由實作時決定：

方案 A（推薦）：使用 `ctypes` + WinRT COM interop（參考 ok-script `windows_graphics.py`）
- 不需新增相依套件
- 約 400 行 WinRT 互通代碼
- 需處理：DXGI 裝置建立、`CreateForWindow`、Frame pool、Frame arrival callback、device lost/reset

方案 B：使用 `windows-graphics-capture` PyPI 套件
- 新增相依：`pip install windows-graphics-capture`
- 封裝較好但相依更新風險
- 需加入 build.py 的 hidden import

**WGC 實作要點：**
- 維持 60fps 上限可接受（遊戲場景已足夠）
- 需處理 DXGI 裝置遺失（`DXGI_ERROR_DEVICE_REMOVED` / `DXGI_ERROR_DEVICE_RESET`）
- 回傳 numpy BGR array 相容 OpenCV
- 首次畫面 timeout（參考 ok-script 的 1.5s 驗證）可以在初始化時做一次 warm-up

### 風險與緩解

| 風險 | 緩解 |
|------|------|
| WGC 需要 Windows 10 1903+ | 低風險，目標使用者符合條件；若不支援自動跳過 |
| WinRT COM interop 複雜 | 方案 A 約 400 行；方案 B 用套件但需管理相依 |
| 框架合成導致延遲 | 初始化時 warm-up + timeout；若 timeout 退回 GDI |
| 多螢幕 DPI 處理 | 沿用現有 `get_dpi_scaling_factor`；WGC 回傳 logical pixels 需 * dpi 到 physical |

### WGC 實作複雜度補充

ok-script 的 WGC 實作（`windows_graphics.py`）約 400 行，包含：
- Direct3D11 裝置與紋理管理
- `IGraphicsCaptureItemInterop.CreateForWindow` WinRT 呼叫
- `Direct3D11CaptureFramePool` 框架池管理
- Frame arrived callback（C 回呼轉 Python）
- 子視窗合成（`composite_hwnds`）
- 邊框裁剪（`crop_image`）
- 裝置遺失復原
- 失敗冷卻（failure cooldown）

這不是一個小功能。建議此項目排在 AHK 替換之後，且有完整 session 時間。

---

## 項目三：Box 座標工具集

### 現狀

ROI 與點擊座標全是裸 `dict`：
```python
{"x": 0.5, "y": 0.2, "w": 0.3, "h": 0.1}  # 比例座標
{"x": 100, "y": 200, "w": 300, "h": 100}    # 像素座標
```

座標操作散落各處：
- `_resolve_roi()` — 比例→像素轉換
- `_resolve_point()` — 點座標轉換
- `crop_roi()` — 裁切影像
- `_sanitize_roi()` — 邊界驗證（含 `roi_coord: "client"` 處理）
- `_box_to_rect()` — OCR box 轉 ROI

### 參考（ok-script Box.py）

一個 `Box` 類別 + 10 個模組級函式。有用的方法：
- `center()` → `(cx, cy)`
- `scale(ratio)` → 縮放後的新 Box
- `crop_frame(image)` → 影像切片
- `relative_box(w, h, x, y, to_x, to_y)` → 比例→像素
- `in_boundary(boxes)` / `get_bounding_box(boxes)`
- `copy(x_offset, y_offset)` → 偏移複製
- `closest_distance()` / `center_distance()` → 距離計算

### 設計原則（ponytail）

- 不在每個地方強制使用 Box。step.params dict 仍可存裸 dict
- 提供一個**純工具**模組 `core/box_utils.py`，內含函式供需要處呼叫
- 不改變序列化格式（JSON 裸 dict 相容）
- `_resolve_roi()` / `_resolve_point()` / `_sanitize_roi()` 內部可用 box_utils 簡化實作

### 實作方案

**新檔案：`core/box_utils.py`**

```python
# 純函式工具。所有函式接受 dict ROI 或 (x,y,w,h) tuple，回傳 dict

def roi_center(roi: dict) -> tuple[int, int]
def roi_scale(roi: dict, scale: float) -> dict
def roi_to_pixels(roi: dict, frame_w: int, frame_h: int) -> dict
def roi_to_ratio(roi: dict, frame_w: int, frame_h: int) -> dict
def roi_crop(roi: dict, img: np.ndarray) -> np.ndarray | None
def roi_intersection(a: dict, b: dict) -> dict | None
def roi_bounding(boxes: list[dict]) -> dict
def roi_sanitize(roi: dict | None) -> dict  # 取代 rule_migration._sanitize_roi()
```

**重要：`roi_sanitize()` 必須同時處理 `roi_coord: "client"` 欄位**

`rule_migration._sanitize_roi()` 現有邏輯（`rule_migration.py:66-76`）：
```python
def _sanitize_roi(roi: dict | None) -> dict:
    roi = roi if isinstance(roi, dict) else {}
    result = {"x": ..., "y": ..., "w": ..., "h": ...}
    if roi.get("roi_coord") == "client":
        result["roi_coord"] = "client"
    return result
```

新函式需保留此行為，否則匯入舊任務時 client-area ROI 定位會偏移。

**可選：小型 `Box` dataclass**
```python
@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    coord_sys: str = "ratio"  # "ratio" | "pixel"

    @property
    def center(self) -> tuple[float, float]
    @property
    def area(self) -> float
    def scale(self, factor: float) -> Box
    def to_pixels(self, frame_w: int, frame_h: int) -> Box
    def to_dict(self) -> dict  # 保持序列化相容
    @classmethod
    def from_dict(cls, d: dict) -> Box
```

但考量 ponytail 原則，先只做函式級別。若發現多處重複的 dict 操作才考慮加入 Box dataclass。

**改動範圍：**
- 新增 `core/box_utils.py`
- `rule_migration.py` 的 `_sanitize_roi()` → 可委派給 `roi_sanitize()` 保持向後相容
- `05_main_loop.py` 的 `_resolve_roi()` / `_resolve_point()` / `crop_roi()` → 內部可改用 box_utils
- `11_template_matching.py` 的 ROI 判斷 → 可改用

### 風險

幾乎無風險。新模組 + 既有函式逐步改用，不改序列化格式，不改任何 JSON。

注意事項：
- `_sanitize_roi` 的 `roi_coord` 處理必須保留
- 不要在 `core/box_utils.py` 中導入 `_loader`（避免 circular import）
- 保持所有函式的 None-safe（現有代碼常有 `roi is None` 表示「全畫面」的慣例）

---

## 執行時程

```
Phase 1 [本次]：寫計畫書 + 備份 + AHK→pynput 實作
Phase 2 [下次]：多重截圖後端（WGC）
Phase 3 [下次]：Box 座標工具集
```

每個 Phase 完成後依照 AGENTS.md 規範：
1. ruff check + format
2. 自檢測試（有改的 `core/` 檔案執行 self-check）
3. `python -m pytest`（確保 tests/ 全部通過）
4. `rg "ahk|AHK|AutoHotkey" --include "*.py"` 確認無殘留（僅 Phase 1）
5. graphify update
6. git commit + push

---

## 備份策略（執行任何改動前）

1. `git checkout -b backup/pre-optimization` — 保留分支
2. `git archive -o backup/pre-optimization.zip HEAD` — 完整原始碼壓縮（存到專案目錄外）
3. 所有改動發生在 `master` 主分支，備份分支不動

---

## Phase 1 實作檢查清單

實作 AHK→pynput 時依序執行：

- [ ] 新增 `core/03_pynput_input.py`
- [ ] `core/05_main_loop.py`：改 import + 5 處函式呼叫
- [ ] `core/05_main_loop.py`：self-check mock 更新
- [ ] `gui/06_gui_main.py`：改 import
- [ ] `gui/06_gui_main.py`：移除 AHK 初始化流程（80 行）
- [ ] `gui/06_gui_main.py`：狀態列改為 input_status
- [ ] `gui/06_gui_main.py`：移除 shutdown 呼叫
- [ ] `gui/09_ocr_debug.py`：改 import + 移除 init_ahk 重試
- [ ] `build.py`：移除 clicker.ahk 資料檔
- [ ] `build.py`：從排除清單移除 pynput
- [ ] `i18n/*.json`：移除 7 個 AHK key
- [ ] `pip install pynput`
- [ ] 刪除 `core/03_ahk_socket.py` 與 `clicker.ahk`
- [ ] 確認無殘留 `rg "ahk|AHK|AutoHotkey" -t py`
- [ ] `ruff check --fix . && ruff format .`
- [ ] 執行所有 self-check
- [ ] `python -m pytest`
- [ ] `graphify update .`
- [ ] git add + commit + push
