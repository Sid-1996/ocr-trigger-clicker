@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM 檢查系統管理員權限；不足則以管理員身分重新啟動
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要系統管理員權限，正在以管理員身分重新啟動...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM 使用 uv 執行專案（會自動使用 .venv 虛擬環境）
uv run python gui/06_gui_main.py --debug
if errorlevel 1 (
    echo 啟動過程發生錯誤。
    if exist startup_error.log (
        type startup_error.log
        del startup_error.log
    )
    REM 錯誤時暫停，讓開發者能讀錯誤訊息；正常結束則自動關閉視窗。
    pause
) else (
    echo 程式已結束。
)

