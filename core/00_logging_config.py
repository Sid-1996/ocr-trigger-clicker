import logging
import threading
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_LOG_DIR = Path.home() / "AppData" / "Roaming" / "ocr-trigger-clicker" / "logs"
_handler = None
_lock = threading.Lock()


def get_log_dir() -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def get_logger(name: str) -> logging.Logger:
    _ensure_root_handler()
    return logging.getLogger(name)


def _ensure_root_handler():
    global _handler
    if _handler is not None:
        return
    with _lock:
        if _handler is not None:
            return
        log_dir = get_log_dir()
        _handler = TimedRotatingFileHandler(
            log_dir / "app.log", when="midnight", backupCount=7, encoding="utf-8"
        )
        _handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root = logging.getLogger()
        if _handler not in root.handlers:
            root.addHandler(_handler)
        root.setLevel(logging.INFO)
