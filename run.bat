@echo off
chcp 65001 > nul
cd /d "%~dp0"
python gui/06_gui_main.py
if errorlevel 1 (
    echo 啟動過程發生錯誤。
    if exist startup_error.log (
        type startup_error.log
        del startup_error.log
    )
) else (
    echo 程式已結束。
)
pause
