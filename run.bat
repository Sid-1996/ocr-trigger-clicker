@echo off
chcp 65001 > nul
cd /d "%~dp0"
python gui/06_gui_main.py --debug
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
