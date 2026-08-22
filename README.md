<p align="center">
  <img src="docs/images/ocr-trigger-clicker.png" alt="OCR Trigger Clicker" width="280">
</p>

<h1 align="center">OCR Trigger Clicker</h1>

<p align="center">
  <em>給一般玩家的免寫程式遊戲自動化工具 — 看畫面文字點兩下就建好規則，或錄製一遍操作自動轉成腳本</em><br>
  支援繁體中文 / English / 日本語 UI 切換 · Author: Sid
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/github/v/release/Sid-1996/ocr-trigger-clicker?style=flat-square&color=blue" alt="Version">
  <img src="https://img.shields.io/github/downloads/Sid-1996/ocr-trigger-clicker/total?label=%E4%B8%8B%E8%BC%89%E6%AC%A1%E6%95%B8&color=238636&style=flat-square" alt="Downloads">
  <img src="https://img.shields.io/github/stars/Sid-1996/ocr-trigger-clicker?style=flat-square&color=yellow" alt="Stars">
  <img src="https://img.shields.io/github/license/Sid-1996/ocr-trigger-clicker?style=flat-square" alt="License">
</p>

<p align="center">
  <a href="./README.en.md">English</a> · <strong>繁體中文</strong>
</p>

---

> 🎯 **第一次使用？你是來「用」的，不是來看程式碼的。**
> 請看 [📖 快速上手指南](./START.md) — 3 分鐘從下載到啟動

---

## 預覽

<p align="center">
  <img src="docs/images/gui-main.png" alt="主介面" width="880"><br>
  <em>規則列表 + 步驟編輯 — 深色主題、中文介面</em>
</p>

<br>

<p align="center">
  <img src="docs/images/ocr-diagnostic.png" alt="OCR 診斷面板" width="880"><br>
  <em>OCR 診斷 — 即時辨識畫面文字，選取目標後一鍵建立規則</em>
</p>

<br>

<p align="center">
  <a href="https://www.dailymotion.com/video/xaxgcfq">🎬 看示範影片 — 一鏡到底示範錄製操作、自動轉規則與前景／後台模式</a>
</p>

---

## 它能做什麼

| 功能 | 說明 |
|:----:|------|
| 🔍 | **自動偵測螢幕上的字** — 設定要找的文字和觸發動作，找到就自動執行（OCR 以繁體中文為主；English 語系自動改用英文模型，英文與數字亦可辨識） |
| 🖼️ | **用圖片來找按鈕** — 截圖當範本比對，沒文字的地方也能用；範本截圖後還可**修剪微調**，套到最準的範圍 |
| 🔗 | **多步驟串成流程** — 偵測→點擊→等待→拖曳…全部自動跑完 |
| 📂 | **不同場景切換任務** — 不同遊戲或工作存成獨立檔案，一鍵切換 |
| 📐 | **同比例換解析度也不怕** — 座標存為視窗比例，相同長寬比（16:9，如 1080p↔900p）的解析度間通用，換螢幕不用重設 |
| 👁️ | **看著畫面設定規則** — OCR 診斷面板列出畫面上所有可辨識文字，選取目標後一鍵「建立為新文字規則」 |
| 🎮 | **後台掛機** — 後台模式用 PrintWindow 截圖 + Frida 注入點擊與按鍵，視窗可被其他視窗遮蓋（但**不能最小化**），零游標干擾、不搶焦點（多數 Unity 遊戲不支援後台，屬遊戲底層限制，非工具問題）；滑鼠與鍵盤分開驗證——後台滑鼠可用不代表鍵盤也可 |
| 🔀 | **混合模式** — 遊戲只吃前景操控（如多數 Unity 遊戲）也能掛機：平時以後台截圖偵測、零干擾，需要動作時才自動把遊戲短暫切到前景點一下、完成後復原你原本的視窗與滑鼠位置。適合低頻動作的任務——例如遊戲正在自動戰鬥爬主線，只有過關時要點「下一關」，寫好規則後就能掛著去做別的事 |
| ⌨️ | **F8 全域熱鍵** — 不用切回工具視窗，任何時候按 F8 就能啟動／停止任務；暫停中按 F8 則繼續執行 |
| 🎬 | **錄製操作** — 按 F9 開始錄製，在遊戲裡點擊示範一遍，停止後自動轉成規則，不用手動設定（只記錄滑鼠點擊，點在文字或圖示上效果最佳） |
| 🔄 | **自動更新** — 啟動時自動檢查新版本，差異更新只下載變更檔案（省 90% 以上流量），更新器一鍵完成升級 |
| 🌐 | **多語介面** — 繁體中文 / English / 日本語 一鍵切換 |

---

## 快速開始

<p>
  <kbd>1</kbd> 下載 <code>ocr-trigger-clicker.zip</code> → 解壓縮 → 執行 exe<br><br>
  <kbd>2</kbd> 選取目標視窗 → 按「啟動」
</p>

> 📖 詳細引導請看 [快速上手指南](./START.md)。

> 💡 內建範例：已打包 **星之救援者 StarSavior** 每日任務／跑馬輔助任務檔 → [StarSavior 任務頁](./docs/starsavior.html)

---

## 分享你的任務

設定好的任務不只自己用，也能分享給別人：

<kbd>1</kbd> 工具列按「匯出任務」→ 存成 JSON 檔案<br><br>
<kbd>2</kbd> 到 [任務檔案分享討論區](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/%E4%BB%BB%E5%8B%99%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB) 貼文附上 JSON（建議一併註明來源解析度）<br><br>
<kbd>3</kbd> 別人下載後按「匯入任務」一鍵載入，相同長寬比（16:9）的解析度間座標自動適應；長寬比不同需重新框選

> 任務 JSON 是純文字檔，不含帳號等機密資料；內容只有規則本身與目標視窗名稱、互動模式等任務資訊。

---

## 系統需求與安裝

- **Windows 10 / 11**（64 位元）
- 免安裝、免 Python 環境，下載 ZIP 解壓縮直接執行
- 如果遊戲沒反應、或後台截圖黑畫面，試試 **右鍵 → 以系統管理員身分執行**

---

## 免責聲明

本工具僅供個人自動化重複操作使用。使用前請自行確認符合目標遊戲／軟體的**服務條款**與所在地法規；因使用本工具（含後台模式、Frida 注入）而導致的帳號風險、損失或第三方爭議，作者與貢獻者概不負責。請務必謹慎評估是否在自己的遊戲中使用自動化工具。

---

<details>
<summary><strong>📖 更多資訊</strong></summary>

- 📖 [文件網站](https://sid-1996.github.io/ocr-trigger-clicker/) — 完整教學與範例
- 📂 [任務檔案分享](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/%E4%BB%BB%E5%8B%99%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB) — 下載現成腳本
- 💬 [GitHub Discussions](https://github.com/Sid-1996/ocr-trigger-clicker/discussions) — 使用心得與討論
- 🐛 [Issues](https://github.com/Sid-1996/ocr-trigger-clicker/issues) — 問題回報
- ⭐ [GitHub 專案](https://github.com/Sid-1996/ocr-trigger-clicker) — 給一顆 Star 支持開發

</details>

<details>
<summary><strong>🛠️ 給開發者</strong></summary>

- [技術規格與比較表](./docs/dev/TECHNICAL.md)
- [系統架構](./docs/dev/ARCHITECTURE.md)
- [版本記錄](./docs/dev/CHANGELOG.md)

</details>

---

## 贊助開發者

<a href="https://p.ecpay.com.tw/E0E3A"><img src="https://img.shields.io/badge/ECPAY-請喝咖啡-238636?style=for-the-badge" alt="ECPAY"></a>
<a href="https://www.paypal.com/ncp/payment/9TGC4B3MYM9A6"><img src="https://img.shields.io/badge/PayPal-請喝咖啡-00457C?style=for-the-badge" alt="PayPal"></a>
<a href="https://afdian.com/a/sid-1996"><img src="https://img.shields.io/badge/愛發電-贊助開發者-EA4AAA?style=for-the-badge" alt="愛發電"></a>

---

<p align="center">
  Copyright (C) 2024-2026 Sid · <a href="LICENSE">AGPLv3</a>
</p>
