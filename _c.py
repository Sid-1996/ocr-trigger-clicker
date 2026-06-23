import sys, os, traceback
os.chdir(r"C:\Code play first\ocr-trigger-clicker")
sys.path.insert(0, os.getcwd())

# Patch QApplication to not launch event loop
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

import importlib.util
spec = importlib.util.spec_from_file_location("gui_main", "gui/06_gui_main.py")
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    print("module load OK")
    win = mod.MainWindow()
    print("MainWindow() OK")
    win.show()
    print("show() OK — closing")
    win.close()
    app.quit()
except SystemExit as e:
    print(f"SystemExit({e})")
    traceback.print_exc()
except Exception:
    traceback.print_exc()
