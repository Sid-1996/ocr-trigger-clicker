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


def clear_log_file(handler: "logging.Handler | None" = None) -> None:
    # 清空 app.log 供乾淨起跑抓 bug 回報。要透過 handler 自己的 stream 截斷，
    # 否則外開 handle 截斷會在檔頭留下 null 空洞（handler 內部位置未歸零）。
    # startup_error.log 由啟動時整檔覆寫、無持有 handle，直接移除即可。
    if handler is None:
        _ensure_root_handler()
        handler = _handler
    if handler is not None:
        try:
            stream = handler.stream
            stream.seek(0)
            stream.truncate(0)
            stream.flush()
        except OSError:
            pass
    (get_log_dir() / "startup_error.log").unlink(missing_ok=True)


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

    # ── clear_log_file self-check：用臨時檔 handler，不碰真實 app.log ──
    import tempfile

    _tmp_dir = tempfile.TemporaryDirectory()
    _tpath = Path(_tmp_dir.name) / "clear_test.log"
    _tpath.write_text("old line\n", encoding="utf-8")
    _th = TimedRotatingFileHandler(_tpath, when="midnight", backupCount=1, encoding="utf-8")
    _th.stream.write("tail\n")
    _th.stream.flush()
    clear_log_file(_th)
    _th.stream.write("new\n")
    _th.stream.flush()
    _th.close()
    _content = _tpath.read_text(encoding="utf-8")
    assert _content == "new\n", f"expected only new line, got {_content!r}"
    _tmp_dir.cleanup()
    print("  [OK] clear_log_file truncates without null-hole")
