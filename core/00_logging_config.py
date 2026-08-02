import logging
import sys
import threading
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_LOG_DIR = Path.home() / "AppData" / "Roaming" / "ocr-trigger-clicker" / "logs"
_handler = None
_stream_handler = None
_debug_enabled = False
_lock = threading.Lock()


def get_log_dir() -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


_STALE_FILES = ("debug.log", "run_stderr.log", "triggers.jsonl")


def cleanup_stale_logs() -> None:
    log_dir = get_log_dir()
    stale = list(_STALE_FILES)
    stale += [p.name for p in log_dir.glob("triggers.jsonl*")]
    for name in stale:
        try:
            (log_dir / name).unlink(missing_ok=True)
        except OSError:
            pass


def get_logger(name: str) -> logging.Logger:
    _ensure_root_handler()
    return logging.getLogger(name)


def _ensure_root_handler():
    global _handler, _stream_handler
    if _handler is not None:
        return
    with _lock:
        if _handler is not None:
            return
        root = logging.getLogger()
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        log_dir = get_log_dir()
        _handler = TimedRotatingFileHandler(
            log_dir / "app.log", when="midnight", backupCount=1, encoding="utf-8"
        )
        _handler.setFormatter(fmt)
        if _handler not in root.handlers:
            root.addHandler(_handler)
        # 開發時 cmd 視窗可即時看到 logging 輸出
        if _stream_handler is None:
            _stream_handler = logging.StreamHandler(sys.stdout)
            _stream_handler.setFormatter(fmt)
            if _stream_handler not in root.handlers:
                root.addHandler(_stream_handler)
        root.setLevel(logging.DEBUG if _debug_enabled else logging.INFO)


def set_debug(enabled: bool) -> None:
    global _debug_enabled
    _debug_enabled = enabled
    root = logging.getLogger()
    _ensure_root_handler()
    level = logging.DEBUG if enabled else logging.INFO
    root.setLevel(level)
    for h in list(root.handlers):
        h.setLevel(level)


def is_debug_enabled() -> bool:
    return _debug_enabled


def enable_debug() -> None:
    set_debug(True)


if __name__ == "__main__":
    root = logging.getLogger()
    set_debug(False)
    assert not is_debug_enabled()
    assert root.level == logging.INFO
    set_debug(True)
    assert is_debug_enabled()
    assert root.level == logging.DEBUG
    assert all(h.level == logging.DEBUG for h in root.handlers)
    set_debug(False)
    assert not is_debug_enabled()
    assert root.level == logging.INFO
    assert all(h.level == logging.INFO for h in root.handlers)
    print("logging_config self-check passed")
