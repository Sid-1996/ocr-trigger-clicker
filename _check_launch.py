import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

# redirect stderr to file before Qt swallows it
import io
_errlog = open("_err.txt", "w", encoding="utf-8")
sys.stderr = _errlog

import traceback
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("gui_main", "gui/06_gui_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.MainWindow  # just verify class exists
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    win = mod.MainWindow()
    win.show()
    sys.exit(app.exec())
except SystemExit as e:
    _errlog.write(f"SystemExit: {e}\n")
    traceback.print_exc(file=_errlog)
except Exception:
    traceback.print_exc(file=_errlog)
finally:
    _errlog.flush()
    _errlog.close()
