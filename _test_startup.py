import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test loading without GUI
try:
    import importlib.util

    spec = importlib.util.spec_from_file_location("gui_main", "gui/06_gui_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    print("GUI module loaded OK")
except Exception:
    traceback.print_exc()
    sys.exit(1)

# Test key engine modules
try:
    from _loader import load_sibling

    r = load_sibling("rule_engine", "core/04_rule_engine.py")
    print(f"Tasks dir: {r.get_tasks_dir()}")
    print(f"Tasks: {r.list_tasks()}")
    print("All ok")
except Exception:
    traceback.print_exc()
    sys.exit(1)
