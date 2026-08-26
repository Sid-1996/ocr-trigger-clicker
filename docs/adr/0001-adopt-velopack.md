# 採用 Velopack 取代自製更新器，並新增公開測試庫作為發版沙箱

Status: accepted（2026-08-26）

自製 updater.exe 的「備份 rename」在安裝目錄被第二實例／防毒鎖住時必敗（v0.3.x 兩度撤回的根因）；
且 Release 在 draft 狀態下資產不可達，「真實使用者下載路徑」永遠無法在發布前端到端驗證。
決定：改用業界標準框架 Velopack（2025/06 起有官方 Python SDK、支援 PyInstaller onedir、內建 delta）——
app 安裝至 `%LocalAppData%\OCRTriggerClicker`，框架的 Update.exe 位於 app 目錄**之外**，
換目錄時不可能鎖住自己，死穴從架構上消失；同時建立公開測試庫
`ocr-trigger-clicker-release-test`，`release.ps1 -FeedTest` 直接公開上傳供 E2E 打靶，
驗證通過才走正式庫 draft 流程，測試不再打擾真實使用者。

## Considered Options

- **修好自製更新器**（rename 優先＋硬蓋兜底＋Win32 錯誤碼 log）：約半小時工，但這顆輪子與 Velopack 功能重疊，修完註定要拆
- **同庫 prerelease 通道**：少維護一個 repo，但測試 tag／release 噪音留在正式庫頁面，且隔離不徹底
- **直接上 Velopack（採用）**：拆除 ~1000 行自製碼（updater_main.py／make_delta.py／manifest 協定）、delta 縮至 ~0.55 MB 且零維護；代價是免安裝形態退役、舊用戶需手動裝一次 Setup.exe（使用者量小，可接受）

## Consequences

- `latest_version.txt` 凍結於 0.3.0 刻意不動：v0.3.x 舊客戶端檢查更新永遠顯示「暫無更新」（斷糧設計，防止誤觸已拆除路徑）
- 建置機需要 .NET SDK（僅為 vpk CLI）；使用者端無任何 .NET 需求
- 免安裝 ZIP 不再發布，單一分發管道；feed 位址由 `build.py --feed prod|test` 烘入並於打包後防呆驗證
- 單一實例防護（CreateMutex）在任何方案下都必要——雙開鎖目錄不是自製更新器獨有的問題
