import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


@pytest.fixture
def tmp_tasks_dir(monkeypatch, tmp_path):
    """Patch get_tasks_dir to use a temporary directory."""
    import core.task_management as _tasks

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    monkeypatch.setattr(_tasks, "get_tasks_dir", lambda: tasks_dir)
    return tasks_dir
