import importlib.util
import sys
import threading
from pathlib import Path

from core._paths import _bundle_root

_here = _bundle_root()
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

        target = _here / filename
        if not target.exists() and hasattr(sys, "_MEIPASS"):
            _dump_diagnostics(target)
        path = str(target)
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None:
            raise ImportError(f"找不到模組檔案: {filename}（路徑: {path}）")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        _cache[key] = mod
        return mod


def _dump_diagnostics(missing: Path):
    """Log what's in the extraction dir when a file is missing."""
    import logging

    parent = missing.parent
    log = logging.getLogger("_loader")
    log.error("遺失檔案: %s", missing)
    log.error("_MEIPASS: %s", sys._MEIPASS)
    if parent.exists():
        log.error("目錄內容 (%s): %s", parent, [p.name for p in parent.iterdir()])
    else:
        log.error("父目錄不存在: %s", parent)
        _parent = parent.parent
        if _parent.exists():
            log.error("祖父目錄內容: %s", [p.name for p in _parent.iterdir()])


def log_main(msg: str):
    """Write to app.log via lazy import to avoid circular dependency."""
    mod = load_sibling("main_loop", "core/05_main_loop.py")
    mod.log_main(msg)
