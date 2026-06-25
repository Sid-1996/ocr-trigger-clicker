@echo off
cd /d "%~dp0"
python gui/06_gui_main.py
if exist startup_error.log (
    type startup_error.log
    del startup_error.log
    echo.
    echo 啟動失敗，請將上方錯誤訊息截圖回報。
    pause
)
