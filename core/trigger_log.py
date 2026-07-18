import json
import logging
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

_LOG_DIR = Path.home() / "AppData" / "Roaming" / "ocr-trigger-clicker" / "logs"


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
        with open(_LOG_DIR / "triggers.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        _log.debug("trigger log write failed: %s", e)
