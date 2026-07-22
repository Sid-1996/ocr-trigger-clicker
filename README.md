# OCR Trigger Clicker

![License](https://img.shields.io/badge/license-AGPLv3-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Downloads](https://img.shields.io/github/downloads/Sid-1996/ocr-trigger-clicker/total?label=%E4%B8%8B%E8%BC%89%E6%AC%A1%E6%95%B8&color=238636)

> 免寫程式的 Windows 自動化工具 — 透過 OCR 即時偵測螢幕文字，自動執行滑鼠點擊與鍵盤操作。  
> 支援繁體中文 / 簡體中文 UI 切換。Author: Sid

[**English**](./README.en.md) · [**简体中文**](./README.zh-CN.md) · **繁體中文**

---

## 目錄

- [概述](#概述)
- [截圖一覽](#截圖一覽)
- [功能一覽](#功能一覽)
- [與其他工具比較](#與其他工具比較)
- [系統需求](#系統需求)
- [安裝](#安裝)
- [快速入門](#快速入門)
- [完整文件](#完整文件)
- [社群與交流](#社群與交流)
- [贊助開發者](#贊助開發者)
- [授權](#授權)

---

## 概述

OCR Trigger Clicker 是一款基於光學字元辨識（OCR）的 Windows 自動化工具。它監控指定視窗的畫面內容，當偵測到使用者設定的目標文字或圖示時，自動執行滑鼠點擊、鍵盤按鍵、拖曳等動作。

**無程式碼（No-Code）**、**視窗比例座標（跨解析度相容）**、**多語言介面**，讓不具備程式背景的使用者也能快速建立自動化規則。

---

## 截圖一覽

![主介面](docs/images/gui-main.png)

![OCR 診斷面板](docs/images/ocr-diagnostic.png)

---

## 功能一覽

- **OCR 文字偵測** — 基於 RapidOCR，支援繁體／簡體中文，可框選 ROI 減少干擾
- **圖示模板比對** — OpenCV matchTemplate + NMS，比 OCR 快 10~50 倍，適合無文字按鈕
- **視窗比例座標** — 所有座標儲存為 0~1 比值，1080p / 4K / 縮放 150% 皆相容
- **群組規則管理** — 拖曳排序、循環執行／執行一次／重複 N 次、群組並行與依序
- **步驟系統** — detect / click / key / wait / jump / compare / match_image / notify / scroll / drag，可組合複雜流程
- **常駐監控模式** — 不受群組流程影響，每幀獨立執行，適合錯誤攔截
- **前景保護與安全機制** — 可選前景保護、速率限制、緊急停止
- **多任務管理** — 不同場景建立獨立任務，快速切換，JSON 匯入／匯出

---

## 與其他工具比較

| 特性 | OCR Trigger Clicker | AutoHotkey | Airtest | AutoIt |
|------|:---:|:---:|:---:|:---:|
| 上手門檻 | ✅ 圖形化介面，免寫碼 | ❌ 需手寫指令碼 | ⚠️ 需 Python 基礎 | ❌ 需手寫指令碼 |
| OCR 文字偵測 | ✅ 內建，支援繁中 | ❌ 需外掛 | ⚠️ 有，但配置複雜 | ❌ 無 |
| 跨解析度 | ✅ 比例座標，自動適應 | ❌ 像素座標，換螢幕就壞 | ❌ 同左 | ❌ 同左 |
| 圖像模板比對 | ✅ 內建 OpenCV + NMS | ❌ 需外掛 | ✅ 有 | ❌ 無 |
| 滑鼠 / 鍵盤模擬 | ✅ AHK v2 TCP 通訊 | ✅ 原生支援 | ✅ 有 | ✅ 原生支援 |
| 多規則群組管理 | ✅ 拖曳排序、循環、跳轉 | ❌ 需手寫邏輯 | ❌ 需手寫邏輯 | ❌ 需手寫邏輯 |
| 開源免費 | ✅ AGPLv3 | ✅ 免費 | ✅ Apache 2.0 | ✅ 免費 |

---

## 系統需求

- Windows 10 / 11（64 位元）
- [AutoHotkey v2](https://www.autohotkey.com/)（需自行安裝）
- 使用預編譯 EXE 無需 Python 環境

---

## 安裝

1. 下載並安裝 [AutoHotkey v2](https://www.autohotkey.com/)
2. 從 [Releases](https://github.com/Sid-1996/ocr-trigger-clicker/releases) 下載 `ocr-trigger-clicker.zip`
3. 解壓縮後執行 `ocr-trigger-clicker.exe`
4. **以系統管理員身分執行**（若目標程式以管理員權限執行，否則點擊無效）

---

## 快速入門

1. **選擇視窗** — 從下拉選單選取要監控的目標視窗
2. **建立群組** — 右鍵 → 新增群組，設定執行模式（循環執行／執行一次／重複 N 次）
3. **在群組內新增規則** — 設定偵測文字、點擊位置等步驟
4. **常駐監控** — 規則打勾「常駐監控」即自動歸入 📡 節點，不參與群組順序
5. **啟動** — 點擊「啟動」→ 選擇要執行的群組 → 開始偵測

---

## 完整文件

詳細的功能說明、使用教學、技術架構與常見問題，請參閱：

👉 [**文件網站**](https://sid-1996.github.io/ocr-trigger-clicker/)（含介面截圖、工具教學、腳本設計範例）

---

## 社群與交流

- 📂 **任務檔案分享** — 想找現成腳本或分享自己的任務設定？歡迎到 [任務檔案分享 Discussions](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/%E4%BB%BB%E5%8B%99%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB) 交流。
- 💬 **一般討論** — 使用心得、功能建議、疑難排解，都歡迎在 [GitHub Discussions](https://github.com/Sid-1996/ocr-trigger-clicker/discussions) 發起。
- 🐛 **問題回報** — 遇到 bug 或想要新功能，請到 [Issues](https://github.com/Sid-1996/ocr-trigger-clicker/issues) 回報。
- ⭐ 如果這套工具對你有幫助，歡迎到 [GitHub 專案](https://github.com/Sid-1996/ocr-trigger-clicker) 給一顆 Star 支持開發！

---

## 贊助開發者

- ☕ [ECPAY](https://p.ecpay.com.tw/E0E3A)
- ☕ [PayPal](https://www.paypal.com/ncp/payment/9TGC4B3MYM9A6)
- ☕ [愛發電](https://afdian.com/a/sid-1996)

---

## 授權

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
