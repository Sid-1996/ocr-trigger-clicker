<p align="center">
  <img src="docs/images/ocr-trigger-clicker.png" alt="OCR Trigger Clicker" width="280">
</p>

<h1 align="center">OCR Trigger Clicker</h1>

<p align="center">
  <em>A no-code game script tool for everyday players — record once or build rules, auto-detect text & icons and click/type for you</em><br>
  Traditional Chinese / English UI · Author: Sid
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/github/v/release/Sid-1996/ocr-trigger-clicker?style=flat-square&color=blue" alt="Version">
  <img src="https://img.shields.io/github/downloads/Sid-1996/ocr-trigger-clicker/total?style=flat-square&color=238636" alt="Downloads">
  <img src="https://img.shields.io/github/stars/Sid-1996/ocr-trigger-clicker?style=flat-square&color=yellow" alt="Stars">
  <img src="https://img.shields.io/github/license/Sid-1996/ocr-trigger-clicker?style=flat-square" alt="License">
</p>

<p align="center">
  <strong>English</strong> · <a href="./README.md">繁體中文</a>
</p>

---

> 🎯 **First time here? You're here to *use* it, not to read code.**
> Check the [📖 Quick Start Guide](./START.en.md) — from download to running in 3 minutes.

---

## Preview

<p align="center">
  <img src="docs/images/gui-main.png" alt="Main Interface" width="880"><br>
  <em>Rule list + step editor — dark theme, Chinese UI</em>
</p>

<br>

<p align="center">
  <img src="docs/images/ocr-diagnostic.png" alt="OCR Diagnostic Panel" width="880"><br>
  <em>OCR diagnostic — real-time text recognition, double-click to create rules</em>
</p>

<br>

<p align="center">
  <a href="https://www.dailymotion.com/video/xaxgcfq">🎬 Watch the demo video — record once, auto-convert to rules, foreground / background modes</a>
</p>

---

## What it does

| | Feature | Description |
|:-:|---------|-------------|
| 🔍 | **Detect text on screen** | Tell it what text to look for and what to do — when found, it acts automatically |
| 🖼️ | **Find buttons with images** | No text? Use a screenshot as a template — faster than reading text |
| 🔗 | **Chain multiple steps** | Detect → click → wait → drag… runs all the way through like a recorded macro |
| 📂 | **Switch between tasks** | Save each game or workflow as a separate file — one-click switch |
| 📐 | **Resolution-proof (same aspect ratio)** | Coordinates are stored as window ratios — switch between same-aspect-ratio (16:9, e.g. 1080p↔900p) resolutions with no reconfiguring; different aspect ratios need re-framing |
| 👁️ | **Set up rules visually** | OCR diagnostic panel lists every text on screen — double-click to create a rule |
| 🎮 | **Background (daemon) mode** | PrintWindow capture + Frida-injected clicks & keys — run with the window minimized or covered, zero cursor disturbance, without stealing focus (most Unity games don't support background mode — that's a game-engine limitation, not a tool issue) |
| ⌨️ | **F8 global hotkey** | Start / pause / stop any time with F8 — no need to switch back to the tool |
| 🎬 | **Record actions** | Press F9 to record, click through the game once as a demo, then convert it into rules automatically — no manual setup (only mouse clicks are recorded; aiming at text or icons gives the best result) |
| 🔄 | **Auto-update** | Checks for new versions on launch, one-click upgrade via the built-in updater |
| 🌐 | **Bilingual UI** | Traditional Chinese / English, switch anytime |

---

## Quick start

<p>
  <kbd>1</kbd> Download <code>ocr-trigger-clicker.zip</code> → extract → run the exe<br><br>
  <kbd>2</kbd> Select your target window → click "Start"
</p>

> 📖 For step-by-step guidance, see the [Quick Start Guide](./START.en.md).

---

## Share your tasks

Your saved tasks aren't just for you — share them:

<kbd>1</kbd> Click "Export Task" in the toolbar → save as a JSON file<br><br>
<kbd>2</kbd> Post it in the [Task file sharing category](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/%E4%BB%BB%E5%8B%99%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB) with the JSON attached (mention the source resolution)<br><br>
<kbd>3</kbd> Others download it, click "Import Task", and it loads instantly — coordinates auto-adapt between same-aspect-ratio (16:9) resolutions; different aspect ratios need re-framing

> Task JSON is a plain-text file; exporting never includes any personal settings or data.

---

## System requirements & installation

- **Windows 10 / 11** (64-bit)
- No installation or Python needed — download the ZIP, extract, run
- If nothing happens, or background capture comes back as a black screen, try **right-click → Run as Administrator**

---

## Disclaimer

This tool is intended for personal automation of repetitive operations. Before using it, please make sure your usage complies with the **terms of service** of the target game / software and applicable laws. The authors and contributors are not liable for any account risk, loss, or third-party disputes arising from the use of this tool (including background mode / Frida injection). Please carefully consider whether automation is appropriate for your game.

---

<details>
<summary><strong>📖 More info</strong></summary>

- 📖 [Documentation site](https://sid-1996.github.io/ocr-trigger-clicker/) — tutorials, examples, FAQ
- 📂 [Task file sharing](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/%E4%BB%BB%E5%8B%99%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB) — download ready-made scripts
- 💬 [GitHub Discussions](https://github.com/Sid-1996/ocr-trigger-clicker/discussions) — community & ideas
- 🐛 [Issues](https://github.com/Sid-1996/ocr-trigger-clicker/issues) — bug reports & feature requests
- ⭐ [GitHub repo](https://github.com/Sid-1996/ocr-trigger-clicker) — give a star to support development

</details>

<details>
<summary><strong>🛠️ For developers</strong></summary>

- [Technical specs & comparison table](./docs/dev/TECHNICAL.md)
- [System architecture](./docs/dev/ARCHITECTURE.md)
- [Changelog](./docs/dev/CHANGELOG.md)

</details>

---

## Sponsor

<a href="https://p.ecpay.com.tw/E0E3A"><img src="https://img.shields.io/badge/ECPAY-Buy_me_a_coffee-238636?style=for-the-badge" alt="ECPAY"></a>
<a href="https://www.paypal.com/ncp/payment/9TGC4B3MYM9A6"><img src="https://img.shields.io/badge/PayPal-Buy_me_a_coffee-00457C?style=for-the-badge" alt="PayPal"></a>
<a href="https://afdian.com/a/sid-1996"><img src="https://img.shields.io/badge/Aifadian-Support-EA4AAA?style=for-the-badge" alt="Aifadian"></a>

---

<p align="center">
  Copyright (C) 2024-2026 Sid · <a href="LICENSE">AGPLv3</a>
</p>
