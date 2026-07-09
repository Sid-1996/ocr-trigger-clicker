import importlib.util
import sys
import threading
from pathlib import Path

if hasattr(sys, "_MEIPASS"):
    _here = Path(sys._MEIPASS)
else:
    _here = Path(__file__).parent
_cache: dict[str, object] = {}
_lock = threading.RLock()


def load_sibling(name: str, filename: str) -> object:
    key = (name, filename)
    with _lock:
        if key in _cache:
            return _cache[key]

        if name in sys.modules:
            mod = sys.modules[name]
            _cache[key] = mod
            return mod

        path = str(_here / filename)
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None:
            raise ImportError(f"找不到模組檔案: {filename}（路徑: {path}）")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        _cache[key] = mod
        return mod


def log_main(msg: str):
    """Write to app.log via lazy import to avoid circular dependency."""
    mod = load_sibling("main_loop", "core/05_main_loop.py")
    mod.log_main(msg)
