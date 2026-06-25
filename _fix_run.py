import pathlib, os
p = pathlib.Path("C:/Code play first/ocr-trigger-clicker/run.bat")
os.remove(str(p))
lines = [
    "@echo off",
    'cd /d "%~dp0"',
    "python gui/06_gui_main.py",
    "if errorlevel 1 (",
    "    echo 啟動過程發生錯誤。",
    "    if exist startup_error.log (",
    "        type startup_error.log",
    "        del startup_error.log",
    "    )",
    ") else (",
    "    echo 程式已結束。",
    ")",
    "pause",
]
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("OK")
d = open(str(p), "rb").read()
print("CRLF count:", d.count(b"\r\n"))
print("Broken CRCRLF:", b"\r\r\n" in d)
print("Content repr:", repr(d[:80]))
