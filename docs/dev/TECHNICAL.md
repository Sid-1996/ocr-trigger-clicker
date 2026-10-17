# Technical Specifications

> This file is intended for developers, technical evaluators, and AI agents.
> For end-user documentation, see [README.md](../README.md) or the [Quick Start Guide](../START.md).

---

## Feature Details

- **OCR Text Detection** — Powered by RapidOCR with bundled models: Traditional Chinese (cht) by default, and a dedicated English (en) model auto-selected when the UI language is English (PP-OCRv4 mobile; real-game testing showed the newer v5 dedicated model degrades on punctuated sentences despite winning synthetic benchmarks — see CHANGELOG Unreleased); the Japanese (ja) UI reuses the cht model — it is a PP-OCRv5 unified model that natively supports Japanese (official benchmark: 54.65% on Japanese, vs 45.69% for the older dedicated japan_PP-OCRv3_mobile_rec); ROI (region-of-interest) cropping reduces interference and improves speed
- **Image Template Matching** — OpenCV `matchTemplate` + Non-Maximum Suppression (NMS); 10–50× faster than OCR, ideal for buttons without text labels
  - **Naming note** — The UI calls this feature and its captured screenshot simply「圖片」(image), but under the hood it is *feature matching*, not pixel-exact comparison: `TM_CCOEFF_NORMED` (normalized cross-correlation) scores similarity 0–1 with a confidence threshold (default 0.85), defaulting to grayscale so lighting/shade shifts tolerate well; optional `match_color` keeps BGR and adds a per-channel tolerance filter. A captured image therefore keeps matching across minor rendering variations — it behaves like a visual signature, not a literal picture compare
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

Output: `dist/ocr-trigger-clicker/` (onedir, includes `ocr-trigger-clicker.exe` + `_internal/`)
Packaged by Velopack (`vpk pack`, invoked by `build.py`) into `Releases/`:
`OCRTriggerClicker-win-Setup.exe`（安裝器）、`OCRTriggerClicker-x.y.z-full.nupkg`、delta nupkg（有前版時自動產生）、`releases.win.json`（更新 feed 索引）。

### 差異更新（Delta Update）

由 Velopack 框架處理，無自訂協定：`release.ps1` 先 `vpk download github` 取回前版資產，
`vpk pack` 即自動產生 `OCRTriggerClicker-x.y.z-delta.nupkg`（實測 0.4.0→0.4.1 僅 ~0.55 MB，
對比整包 ~194 MB）。用戶端 delta 不適用或下載失敗時框架自動退回 full。
首次發版（feed 中無前版 full.nupkg）只有完整包，屬預期行為。

feed 位址由 `build.py --feed prod|test` 烘入 `_update_feed.py`
（prod = 正式庫；test = `ocr-trigger-clicker-release-test` 發版沙箱），打包後自動防呆驗證。

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

### 背景規則與並行群組的跨幀快取（現行）

背景規則與 `order: parallel` 群組的 `match_image` 步驟，一律在各自群組內**即時**計算，靠兩層跨幀快取攤平成本，不做跨群組投機平行預算：

- **`_tmpl_cache`**：`_handle_match_image` 以「搜尋區內容指紋＋模板＋門檻＋顏色參數」為 key，命中即重用上次 `match_template` 結果（`matchTemplate` 對相同輸入 deterministic）。
- **gated OCR**：背景 `detect`/`compare` 規則走 `_gated_ocr`，ROI 指紋變化在容差內即複用上次 OCR 結果，避免對靜態 HUD 反覆 OCR。

### 移除跨群組投機 prematch（v0.4.7）

曾以 `ThreadPoolExecutor`（模組級純函式 `_prematch_pure`）對所有 parallel 群組一次性平行預算首個 `match_image`，結果經 `StepContext.prematch` 由 `_handle_match_image` 消費。真任務 A/B（4 核、StarSavior）顯示此投機平行化會與主執行緒搶 CPU，反而拖慢背景規則／loop 階段；移除後改走 `_tmpl_cache` 即時計算：幀耗時中位數 72.8 → 36.1ms、OCR 預熱中位數 49.6 → 13.1ms、慢速警告 14 → 0，命中行為不變（觸發數相同、命中率 48~49% 一致）。

- **教訓**：推測性平行工作只有在「主執行緒正在等待」時才划算；當主執行緒本身是瓶頸（OCR/template 已吃滿 CPU），平行化只製造 GIL/CPU 競爭。先量測、再平行化。

---

## Related Documents

- [System Architecture](./ARCHITECTURE.md)
- [Changelog](./CHANGELOG.md)
- [Development Notes](../../AGENTS.md)
