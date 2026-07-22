# OCR Trigger Clicker

![License](https://img.shields.io/badge/license-AGPLv3-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Downloads](https://img.shields.io/github/downloads/Sid-1996/ocr-trigger-clicker/total)

> A no-code Windows automation tool — uses OCR to detect text on screen and automatically perform mouse clicks and keyboard actions.  
> Traditional Chinese / Simplified Chinese UI. Author: Sid

**English** · [**简体中文**](./README.zh-CN.md) · [**繁體中文**](./README.md)

---

## Table of Contents

- [Overview](#overview)
- [Screenshots](#screenshots)
- [Features](#features)
- [Comparison](#comparison)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Full Documentation](#full-documentation)
- [Community](#community)
- [Sponsor](#sponsor)
- [License](#license)

---

## Overview

OCR Trigger Clicker is a Windows automation tool powered by optical character recognition (OCR). It monitors a target window in real time, detects configured text or icons on screen, and automatically executes mouse clicks, keyboard presses, drags, and more.

**No-code**, **window-ratio coordinates (resolution-independent)**, and **multi-language UI** — anyone can build automation rules without programming experience.

---

## Screenshots

![Main Interface](docs/images/gui-main.png)

![OCR Diagnostic Panel](docs/images/ocr-diagnostic.png)

---

## Features

- **OCR Text Detection** — Powered by RapidOCR, supports Traditional / Simplified Chinese; ROI support reduces interference
- **Image Template Matching** — OpenCV matchTemplate + NMS, 10–50× faster than OCR, ideal for buttons without text
- **Window-Ratio Coordinates** — All coordinates stored as 0–1 ratios; works across 1080p, 4K, 150% scaling
- **Group Rule Management** — Drag-and-drop sorting, loop / run-once / repeat-N-times, sequential or parallel groups
- **Step System** — detect / click / key / wait / jump / compare / match_image / notify / scroll / drag for complex workflows
- **Background Monitoring** — Runs every frame independently of group flow; ideal for error interception
- **Foreground Protection & Safety** — Optional foreground-only execution, rate limiting, emergency stop
- **Multi-Task Management** — Create independent tasks for different scenarios, quick switching, JSON import/export

---

## Comparison

| Feature | OCR Trigger Clicker | AutoHotkey | Airtest | AutoIt |
|---------|:---:|:---:|:---:|:---:|
| Learning Curve | ✅ GUI, no coding | ❌ Script required | ⚠️ Python basics | ❌ Script required |
| OCR Text Detection | ✅ Built-in, Chinese support | ❌ Needs plugin | ⚠️ Complex setup | ❌ None |
| Resolution Independence | ✅ Ratio coordinates, auto-adapt | ❌ Pixel coords, breaks on resize | ❌ Same | ❌ Same |
| Image Template Matching | ✅ Built-in OpenCV + NMS | ❌ Needs plugin | ✅ Yes | ❌ None |
| Mouse / Keyboard Simulation | ✅ AHK v2 TCP | ✅ Native | ✅ Yes | ✅ Native |
| Multi-Rule Group Management | ✅ Drag-and-drop, loop, jump | ❌ Manual logic | ❌ Manual logic | ❌ Manual logic |
| Open Source | ✅ AGPLv3 | ✅ Free | ✅ Apache 2.0 | ✅ Free |

---

## System Requirements

- Windows 10 / 11 (64-bit)
- [AutoHotkey v2](https://www.autohotkey.com/) (install separately)
- Pre-built EXE requires no Python environment

---

## Installation

1. Download and install [AutoHotkey v2](https://www.autohotkey.com/)
2. Download `ocr-trigger-clicker.zip` from [Releases](https://github.com/Sid-1996/ocr-trigger-clicker/releases)
3. Extract and run `ocr-trigger-clicker.exe`
4. **Run as Administrator** (required if the target app runs with admin privileges, otherwise clicks won't register)

---

## Quick Start

1. **Select Window** — Choose the target window from the dropdown
2. **Create a Group** — Right-click → New Group, set execution mode (loop / once / repeat N times)
3. **Add a Rule** — Add detection text, click position, and other steps inside the group
4. **Background Monitoring** — Check "Background" to move a rule to the 📡 section, independent of group order
5. **Start** — Click "Start" → select groups to run → begin scanning

---

## Full Documentation

For detailed feature explanations, tutorials, architecture, and FAQ:

👉 [**Documentation Site**](https://sid-1996.github.io/ocr-trigger-clicker/) (screenshots, tool guides, script design examples)

---

## Community

- 📂 **Share Task Files** — Find ready-made scripts or share your own on the [Task File Sharing Discussions](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/%E4%BB%BB%E5%8B%99%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB)
- 💬 **General Discussion** — Feedback, questions, and ideas on [GitHub Discussions](https://github.com/Sid-1996/ocr-trigger-clicker/discussions)
- 🐛 **Bug Reports** — Report issues or request features on [Issues](https://github.com/Sid-1996/ocr-trigger-clicker/issues)
- ⭐ If you find this tool useful, please give it a star on [GitHub](https://github.com/Sid-1996/ocr-trigger-clicker)!

---

## Sponsor

- ☕ [ECPAY](https://p.ecpay.com.tw/E0E3A)
- ☕ [PayPal](https://www.paypal.com/ncp/payment/9TGC4B3MYM9A6)
- ☕ [Aifadian](https://afdian.com/a/sid-1996)

---

## License

Copyright (C) 2024-2026 Sid

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
