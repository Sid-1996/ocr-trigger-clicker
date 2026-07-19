import json
import logging
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

_LOG_DIR = Path.home() / "AppData" / "Roaming" / "ocr-trigger-clicker" / "logs"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3


def _rotate(path: Path) -> None:
    if not path.exists() or path.stat().st_size < _MAX_BYTES:
        return
    for i in range(_BACKUP_COUNT, 0, -1):
        src = path if i == 1 else path.with_suffix(f".jsonl.{i - 1}")
        dst = path.with_suffix(f".jsonl.{i}")
        if src.exists():
            if dst.exists():
                dst.unlink()
            src.rename(dst)
    path.touch()


def log_trigger(rule_id: str, rule_name: str, task_name: str, group_id: str = "") -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "rule_id": rule_id,
        "rule_name": rule_name,
        "task": task_name,
        "group": group_id,
    }
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        p = _LOG_DIR / "triggers.jsonl"
        _rotate(p)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        _log.debug("trigger log write failed: %s", e)


if __name__ == "__main__":
    log_trigger("r1", "test_rule", "test_task", "g1")
    log_trigger("r2", "another_rule", "test_task")
    print("trigger_log self-check passed")
