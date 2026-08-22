# Technical Specifications

> This file is intended for developers, technical evaluators, and AI agents.
> For end-user documentation, see [README.md](../README.md) or the [Quick Start Guide](../START.md).

---

## Feature Details

- **OCR Text Detection** — Powered by RapidOCR with bundled models: Traditional Chinese (cht) by default, and a dedicated English (en) model auto-selected when the UI language is English (PP-OCRv4 mobile; real-game testing showed the newer v5 dedicated model degrades on punctuated sentences despite winning synthetic benchmarks — see CHANGELOG Unreleased); the Japanese (ja) UI reuses the cht model — it is a PP-OCRv5 unified model that natively supports Japanese (official benchmark: 54.65% on Japanese, vs 45.69% for the older dedicated japan_PP-OCRv3_mobile_rec); ROI (region-of-interest) cropping reduces interference and improves speed
- **Image Template Matching** — OpenCV `matchTemplate` + Non-Maximum Suppression (NMS); 10–50× faster than OCR, ideal for buttons without text labels
- **Window-Ratio Coordinates** — All coordinates stored as 0–1 ratios (relative to window size); compatible across 1080p, 4K, 150% DPI scaling, and window resizing
- **Group Rule Management** — Drag-and-drop sorting, loop / run-once / repeat-N-times execution modes, sequential or parallel group processing
- **Step System** — Rules composed of ordered steps: detect, click, key, wait, jump, compare, match_image, notify, scroll, drag; supports conditional branching and complex workflows
- **Background (Daemon) Monitoring** — Rules marked as background run every frame independently of group flow; suitable for error interception and always-on alerts
- **Foreground Protection & Safety** — Optional foreground-only execution, configurable rate limiting, emergency stop, and on_fail actions (stop rule / stop group / send notification)
- **Multi-Task Management** — Independent task files with JSON import/export; quick switch between different scenarios
- **On-Fail Step Handling** — Per-step failure actions: stop rule, press key, skip to step, jump to rule in group, advance to next rule, system notification; allows robust error recovery flows
- **Demo Recording (Action Recorder)** — Record mouse clicks on the target window (F9 hotkey / toolbar button) and auto-convert into rules: text-anchored clicks → `detect` + `click(text_center)`, texture-anchored clicks → `match_image` (base64 inline) + `click`, featureless clicks → fixed wait + `click`. Each recording segment becomes a rule group (`mode=once`); sessions may create a new task or merge into an existing one

---

## Comparison with Similar Tools

| Feature | OCR Trigger Clicker | AutoHotkey | Airtest | AutoIt |
|---------|:---:|:---:|:---:|:---:|
| Learning Curve | ✅ GUI, no coding required | ❌ Manual scripting | ⚠️ Requires Python basics | ❌ Manual scripting |
| OCR Text Detection | ✅ Built-in, Traditional Chinese + English | ❌ Needs plugin | ⚠️ Available but complex setup | ❌ None |
| Resolution Independence | ✅ Ratio coordinates (0–1), auto-adapt | ❌ Pixel coordinates, breaks on resize | ❌ Same | ❌ Same |
| Image Template Matching | ✅ Built-in OpenCV + NMS | ❌ Needs plugin | ✅ Available | ❌ None |
| Mouse / Keyboard Simulation | ✅ pynput (Win32 SendInput) | ✅ Native | ✅ Available | ✅ Native |
| Multi-Rule Group Management | ✅ Drag-and-drop, loop, jump, parallel | ❌ Manual logic required | ❌ Manual logic required | ❌ Manual logic required |
| Open Source | ✅ AGPLv3 | ✅ Free | ✅ Apache 2.0 | ✅ Free |

---

## Build & Packaging

- Onedir bundle via PyInstaller (`build.py`)
- Windows 10/11 64-bit only
- No Python runtime required for end users
- Dependencies: PyQt6, rapidocr-onnxruntime, opencv-python, mss, pynput, dxcam, numpy, pygetwindow, pywin32, frida
- Optional GPU acceleration: DirectML via DirectX 12
- Foreground input via pynput (SendInput); background mode via Frida inject for background clicks (may not work on most Unity games — engine limitation, verify per window); hybrid mode via PrintWindow capture + foreground pynput input with focus guard (for games where Frida also fails, at the cost of briefly stealing focus per action); no standalone PostMessage mode
- Developer dependencies are managed by global `uv`; run `uv sync --dev` before local development

```powershell
uv run python build.py
```

Output: `dist/ocr-trigger-clicker/` (onedir, includes `ocr-trigger-clicker.exe` + `updater.exe` + `_internal/`)
Packaged as: `dist/ocr-trigger-clicker.zip` (includes updater and locale files)

### 差異更新（Delta Update）

發版時 `release.ps1` 會再跑 `uv run python make_delta.py <version> <base_version> dist\ocr-trigger-clicker dist`，額外產出：

- `dist/ocr-trigger-clicker-delta.zip` — 只含「上一版 → 本版」變更／新增檔案 + `manifest.json`（本版完整檔案清單：rel 路徑 + size + sha256 + `removed`）
- repo 根 `manifest.json` — 本版完整清單，下一版當差異基準
- repo 根 `delta_info.json` — `{version, base_version, asset, delta_bytes}`，用戶端 raw 讀取判定用

典型大小比例：整包 ZIP ~200 MB（v0.2.9 瘦身後，此前 ~318 MB），而變更通常只有應用程式程式碼（core/gui/i18n 共 0.82 MB）+ 主 exe（12.8 MB，PyInstaller 把 PYZ 內嵌其中）→ 典型 delta 約 **1~20 MB**。大檔（frida.pyd、ONNX 模型、cv2.pyd、Qt/onnxruntime/numpy 等）幾乎不變，所以不需要進 delta。

不產 delta 的情況（用戶端自動走整包）：第一次發版（無前一版 manifest）、跳過多版更新（`base_version` 不符）、delta 過大（> 整包 40%）。

---

## Known Pitfalls

### max_side_len 限制 OCR 輸入尺寸 — 精度嚴重下降 ❌

- **嘗試**：限制 `max_side_len=480/720` 降低全圖 OCR 耗時（從 ~870ms 降至 ~300ms）
- **結果**：遊戲內小字（如「作戰」）被縮到無法辨識，偵測率暴跌
- **結論**：`max_side_len` 只適合大文字 UI（選單、對話框），遊戲場景不可用
- **正確做法**：保持 `max_side_len=0`（原始精度），用 ROI 框選偵測區域提升效能

### 後台操控對 Unity 大多無效 — 遊戲底層限制，非工具問題 ⚠️

- **現象**：後台模式（PrintWindow 截圖 + Frida/PostMessage 輸入）對多數 Unity 開發的遊戲無效——截圖黑畫面或輸入無反應
- **底層原因（科普）**：
  - **輸入**：後台 PostMessage 是把視窗訊息塞進目標視窗的 Win32 舊式訊息佇列；Unity 的輸入多走 **Raw Input / 低階注入** 與自家輸入系統，不接受這條路徑 → 點了沒反應；且 Unity 讀取 OS 游標位置而非 lParam，不移動游標就無法精準點擊。因此後台 PostMessage 模式已移除
  - **渲染**：PrintWindow 要求目標以「相容繪圖」把自己畫出來；Unity 用 GPU（DXGI / Direct3D）直接渲染，不公開這條 PrintWindow 路徑 → 截不到畫面內容
- **結論**：這是遊戲引擎的平台／底層設計，工具無法逾越，**不是工具缺陷**。此類遊戲請改用**前景模式（pynput）**、**後台模式（Frida 注入）**——透過注入遊戲行程 hook `GetCursorPos`/`ScreenToClient` 假造游標座標、hook `GetKeyState`/`GetAsyncKeyState`/`GetKeyboardState` 假造按鍵狀態，讓 Unity 通過輸入驗證，達成零閃爍後台點擊與按鍵（有防作弊偵測風險，滾輪/拖曳不保證可用；遊戲若要求視窗聚焦仍無效）——或**混合模式（hybrid）**：後台 PrintWindow 截圖偵測（零干擾），動作時短暫激活遊戲做 pynput 物理輸入後復原使用者前景與滑鼠（`core/19_hybrid_input.py` 的 `focus_guard`）；適合 Frida 也無效的遊戲，代價是每次操作短暫搶焦點，適合低頻動作
- **實證案例（BrownDust II）**：後台滑鼠點擊可（hook 游標即通過）、後台鍵盤被擋——遊戲鍵盤輸入仍要求視窗焦點，hook 鍵盤狀態無法繞過。可作為「滑鼠可、鍵盤未必可」的基準案例：後台滑鼠與鍵盤需分開驗證。

### 後台截圖全黑 — 試試系統管理員 👑

- **現象**：部分遊戲（如鳴潮）在後台模式截圖全黑、OCR 偵測不到任何字
- **原因**：非系統管理員權限下，遊戲拒絕把畫面繪製給 PrintWindow；`core/15_print_window.py` 的 `is_black_capture()` / `is_admin()` 即用以偵測此情況，並於啟動前提醒
- **解法**：以**系統管理員**身分啟動工具（右鍵 → 以系統管理員身分執行）

---
---

## Performance Notes

### 並行群組 match_image 預算（已實作）

`core/05_main_loop.py` 的 `_run_parallel_group` 對並行（`order: parallel`）群組內所有 `match_image` 規則做**平行預算**——主線程一次算好 `capture_size` / `chrome` / `current_size` / `roi`，worker（`_prematch_pure` 模組級純函式）只跑 `match_template`，不碰執行個體狀態、不讀檔、不呼叫 Win32。結果由 `_handle_match_image` 消費（step 0 命中 `ctx.prematch`）。

- **適用對象**：僅 `match_image` 步驟（純計算、執行緒安全）。`detect`/`compare` 走 OCR，維持順序（已有同幀 OCR 合併快取，不平行）。
- **行為等價**：warning/log/on_fail/triggered/順序全由原 `_run_rule` 處理，命中哪條規則仍依 `rule_ids` 順序決定——使用者零感知（無新設定、無新 UI）。
- **效益**：等待狀態（全不命中）下 N 條 match 從 O(N) 壓成 bounded；N=21 約 33ms → 16ms（~2 倍）。
- **退化教訓**：曾誤讓 worker 各自讀檔/呼叫 Win32，N=21 反而 123ms（慢 4 倍）——已修正為主線程共享預算。

### 命中率切換草案（未實作，待未來評估）

並行預算在**命中密集場景**會略慢於純順序，因為順序靠 `break-on-first-hit` 短路（掃到命中就停），平行卻「全算再取第一個命中」。現況 N=21 下此劣勢無感（每幀差 ~2ms，500ms 掃描間隔下佔 0.4%），但 N 擴充到 80+ 且命中密集時可能微感。

**觸發條件（未來若需實作）**：
- 用滑動窗口追蹤最近 N 幀的命中率（命中幀 / 總幀）
- 命中率 > 閾值（如 60%）持續 M 幀 → 切回順序（享受 break 短路）
- 命中率 < 閾值持續 M 幀 → 切回平行（享受 O(N) 壓縮）
- 需滯後（hysteresis）避免狀態擺盪

**邊界**：N 小（如 ≤21）不值得切換（差距無感）；N 大且命中密集才有感。命中率切換的複雜度（狀態 + 滯後）在 N 小時是過度設計。

**現況判斷**：N=21 實測良好，不需命中率切換。等使用者擴充規則到 80+ 且命中密集期有感再評估。

---

## Related Documents

- [System Architecture](./ARCHITECTURE.md)
- [Changelog](./CHANGELOG.md)
- [Development Notes](../../AGENTS.md)
