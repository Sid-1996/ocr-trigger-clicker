# OCR Trigger Clicker

給一般玩家的 Windows 遊戲自動化工具：以 OCR／圖像比對偵測畫面，觸發點擊、按鍵等動作。本檔是專案術語的事實來源——文件、UI 與對話應使用這裡的 canonical terms。

## Language

### 任務結構

**任務 (Task)**:
一個 JSON 檔案，內含群組與規則，可匯入匯出分享。
_Avoid_: 腳本、profile

**群組 (Group)**:
任務內的一組規則，啟動時以群組為單位勾選執行。
_Avoid_: 分類、collection

**規則 (Rule)**:
一條自動化流程，由多個步驟串成。
_Avoid_: 條件式、macro

**步驟 (Step)**:
規則內的單一動作，共十種：detect / click / key / wait / jump / drag / scroll / match_image / compare / notify。
_Avoid_: 指令、action（泛稱時）

### 偵測與比對

**OCR 診斷 (Diagnostic Panel)**:
即時列出畫面上可辨識文字的面板；選取目標後按「建立為新文字規則」產生規則。沒有雙擊操作。
_Avoid_: 「按兩下建立規則」的說法

**偵測區域 (ROI)**:
規則監看的畫面範圍；未框選即全視窗掃描。

**客戶區比例座標**:
ROI／點擊座標的統一儲存格式：0~1 比例，以視窗客戶區（不含標題列/邊框）為基準。相同長寬比的解析度間自動通用。

**圖片比對 (match_image)**:
以截圖的圖片在畫面上找位置的步驟類型，用於無文字的按鈕或圖示。
_Avoid_: 模板比對、範本、模板、圖示辨識、以圖找字

**修剪圖片**:
對已截取圖片做逐像素微調的對話框，把範圍剪到最準再比對。

### 互動方法

**互動方法 (Interaction Mode)**:
工具操控遊戲的方式，三選一：前景（pynput）、後台（frida）、混合（hybrid）。
_Avoid_: 互動模式、輸入模式

**前景模式 (pynput)**:
以物理輸入（SendInput）操作，遊戲必須在前景。

**後台模式 (frida)**:
PrintWindow 截圖＋Frida 注入輸入；遊戲視窗可被遮蓋但不能最小化，零游標/焦點干擾。多數 Unity 遊戲因底層限制不支援。
_Avoid_: PostMessage 模式（已移除）

**混合模式 (hybrid)**:
平時以後台截圖偵測零干擾，需要動作時短暫把遊戲帶到前景做物理輸入，完成後復原使用者原本的前景視窗與滑鼠位置。適合低頻動作。

### 執行與控制

**主循環 (Main Loop)**:
啟動後持續截圖→比對→觸發的執行迴圈；以群組為單位跑。

**失敗處理 (on_fail)**:
步驟未命中時的行為：跳過本次（預設）/跳過此規則/跳至步驟/跳轉至規則/按下按鍵後繼續/通知並停止群組。

**F8 全域熱鍵**:
任何時候按 F8 啟動或停止任務；暫停中按 F8 為繼續。F8 不會主動暫停（暫停僅由限速等機制自動觸發）。
_Avoid_: 「開始/暫停/停止循環」的說法

**錄製操作 (Recording, F9)**:
示範一遍滑鼠點擊，自動轉成規則；只記錄滑鼠左/右/中鍵。按下錄製時會先把遊戲帶到前景，開始錄製後零干擾。

**錄製操作設定 (Record Conversion Settings)**:
錄製操作轉成規則時專用的延時預設（動作後延遲／偵測後延時），與全域的延遲預設分開，預設 500ms，穩定性優先。
_Avoid_: 把它與全域「動作後延遲預設／偵測後延時預設」混用

### 更新與儲存

**差異更新 (Delta Update)**:
自動更新只下載自上一版真正變更的檔案；不適用時自動退回整包下載。
_Avoid_: 增量更新

**安裝版 (Setup)**:
以 Setup.exe 安裝至 `%LocalAppData%\OCRTriggerClicker` 的發行形態（v0.4.0 起唯一形態），具自動更新與桌面／開始選單捷徑。任務與設定存於 %APPDATA%，不受安裝位置影響。
_Avoid_: 免安裝版、綠色版、portable

**省電模式**:
限制 OCR 執行緒數以降低 CPU 占用的設定；變更立即生效，代價是單次辨識略慢。

### 動作後驗證

**動作後驗證 (Verify)**:
動作步驟（click / key / drag / scroll / match_image）執行後，對新畫面做一次額外檢查，成功才算本步完成，否則走逾時處理。預設摺疊隱藏，普通使用者不需理解實作。
_Avoid_: 後驗證、二次確認

**驗證條件 (VerifyCondition)**:
一次驗證要檢查什麼。含 `type`（文字 detect / 圖片 match_image）、`roi`（驗證區域，可與偵測區域不同）、`expect`（present=要出現 / absent=要消失，預設 present）。
_Avoid_: 驗證目標、驗證對象

**驗證策略 (VerifyPolicy)**:
一次驗證怎麼等。含 `preset`（短 2s / 中 5s / 長 10s，三選一，普通使用者只看此項）、`timeout_ms` / `poll_interval_ms` / `delay_before_ms`（進階才展開的毫秒值）、`retries`（逾時後重試次數，預設 1）與 `retry_delay_ms`（重試間隔，預設 500ms）。
_Avoid_: 逾時設定、輪詢設定（單指某個毫秒值時）

**驗證結果 (VerifyResult)**:
單次輪詢的結論：`success`（條件滿足）、`timeout`（限時內未滿足）、`cancelled`（被停止/暫停/緊急停止打斷）。
_Avoid_: 驗證成功/失敗（未區分取消時）
