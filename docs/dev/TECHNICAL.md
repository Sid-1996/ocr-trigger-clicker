# Technical Specifications

> This file is intended for developers, technical evaluators, and AI agents.
> For end-user documentation, see [README.md](../README.md) or the [Quick Start Guide](../START.md).

---

## Feature Details

- **OCR Text Detection** — Powered by RapidOCR, supports Traditional / Simplified Chinese; ROI (region-of-interest) cropping reduces interference and improves speed
- **Image Template Matching** — OpenCV `matchTemplate` + Non-Maximum Suppression (NMS); 10–50× faster than OCR, ideal for buttons without text labels
- **Window-Ratio Coordinates** — All coordinates stored as 0–1 ratios (relative to window size); compatible across 1080p, 4K, 150% DPI scaling, and window resizing
- **Group Rule Management** — Drag-and-drop sorting, loop / run-once / repeat-N-times execution modes, sequential or parallel group processing
- **Step System** — Rules composed of ordered steps: detect, click, key, wait, jump, compare, match_image, notify, scroll, drag; supports conditional branching and complex workflows
- **Background (Daemon) Monitoring** — Rules marked as background run every frame independently of group flow; suitable for error interception and always-on alerts
- **Foreground Protection & Safety** — Optional foreground-only execution, configurable rate limiting, emergency stop, and on_fail actions (stop rule / stop group / send notification)
- **Multi-Task Management** — Independent task files with JSON import/export; quick switch between different scenarios
- **On-Fail Step Handling** — Per-step failure actions: stop rule, press key, jump to step, jump to group, system notification; allows robust error recovery flows

---

## Comparison with Similar Tools

| Feature | OCR Trigger Clicker | AutoHotkey | Airtest | AutoIt |
|---------|:---:|:---:|:---:|:---:|
| Learning Curve | ✅ GUI, no coding required | ❌ Manual scripting | ⚠️ Requires Python basics | ❌ Manual scripting |
| OCR Text Detection | ✅ Built-in, Chinese + English | ❌ Needs plugin | ⚠️ Available but complex setup | ❌ None |
| Resolution Independence | ✅ Ratio coordinates (0–1), auto-adapt | ❌ Pixel coordinates, breaks on resize | ❌ Same | ❌ Same |
| Image Template Matching | ✅ Built-in OpenCV + NMS | ❌ Needs plugin | ✅ Available | ❌ None |
| Mouse / Keyboard Simulation | ✅ pynput (Win32 SendInput) | ✅ Native | ✅ Available | ✅ Native |
| Multi-Rule Group Management | ✅ Drag-and-drop, loop, jump, parallel | ❌ Manual logic required | ❌ Manual logic required | ❌ Manual logic required |
| Open Source | ✅ AGPLv3 | ✅ Free | ✅ Apache 2.0 | ✅ Free |

---

## Build & Packaging

- Single executable bundled via PyInstaller (`build.py`)
- Windows 10/11 64-bit only
- No Python runtime required for end users
- Dependencies: PySide6, rapidocr-onnxruntime, opencv-python-headless, mss, pynput
- Optional GPU acceleration: DirectML via DirectX 12

```powershell
python build.py
```

Output: `dist/ocr-trigger-clicker.exe`
Packaged as: `dist/ocr-trigger-clicker.zip` (includes updater and locale files)

---

## Known Pitfalls

### max_side_len 限制 OCR 輸入尺寸 — 精度嚴重下降 ❌

- **嘗試**：限制 `max_side_len=480/720` 降低全圖 OCR 耗時（從 ~870ms 降至 ~300ms）
- **結果**：遊戲內小字（如「作戰」）被縮到無法辨識，偵測率暴跌
- **結論**：`max_side_len` 只適合大文字 UI（選單、對話框），遊戲場景不可用
- **正確做法**：保持 `max_side_len=0`（原始精度），用 ROI 框選偵測區域提升效能

---

## Related Documents

- [System Architecture](./ARCHITECTURE.md)
- [Changelog](./CHANGELOG.md)
- [Development Notes](./AGENTS.md)
- [Optimization Plans](./PLAN_optimizations.md)
