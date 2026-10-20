"""Shared test setup.

The workspace, the memory folder and the log have to be pointed at
temporary places before anything under jarvis/ is imported, because
config.py reads them at import time. Nothing here touches the real machine.

The memory folder matters most. It holds your resume profile, your jobs,
your contacts and what LITTLE remembers — and every test starts by emptying
it. Until UI-7 it was the project's own memory folder, so running the tests
on your computer deleted all of that. Now it is a temporary folder, and the
run stops before the first test if it ever isn't.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_sandbox = Path(tempfile.mkdtemp(prefix="jarvis-tests-"))
_memory = Path(tempfile.mkdtemp(prefix="little-test-memory-")).resolve()
os.environ["JARVIS_WORKSPACE"] = str(_sandbox)
os.environ["JARVIS_MEMORY_DIR"] = str(_memory)
os.environ["JARVIS_LOG_FILE"] = str(_memory / "jarvis.log")
for _folder in (_sandbox, _memory):          # gone when the run ends
    atexit.register(shutil.rmtree, _folder, ignore_errors=True)
os.environ["GEMINI_API_KEY"] = "test-key-not-used"
os.environ["JARVIS_BROWSER_HEADLESS"] = "true"

import pytest  # noqa: E402

from jarvis import tools
from jarvis.app import config  # noqa: E402
from jarvis.store import memory  # noqa: E402

# Refuse to run at all against real data.
if config.MEMORY_DIR != _memory or config.LOG_FILE.parent != _memory:
    pytest.exit(f"The tests would use {config.MEMORY_DIR}, not a temporary folder. "
                f"Stopped before touching anything.", returncode=3)


def _gone(path: Path) -> None:
    """Delete a file the tests made — only ever inside the temporary folder."""
    if not path.resolve().is_relative_to(_memory):
        raise RuntimeError(f"refusing to delete {path}: it isn't test data")
    if path.exists():
        path.unlink()


@pytest.fixture
def workspace() -> Path:
    return _sandbox


@pytest.fixture(autouse=True)
def clean_workspace(monkeypatch):
    """Every test starts with an empty workspace and no stored memory, and
    never looks in your own Downloads, Documents or Desktop for a resume —
    one there once made two resume tests read it and fail."""
    for item in _sandbox.iterdir():
        if item.is_dir():
            __import__("shutil").rmtree(item)
        else:
            item.unlink()
    from jarvis.app import audit, benchmark, proactive
    for path in (memory.PREFERENCES, memory.CONTACTS, memory.HISTORY, memory.PROFILE, memory.PROJECT_MEMORY,
                 proactive.STATE_PATH, audit.PATH, benchmark.PATH):
        _gone(path)
    memory._task_notes.clear()
    from jarvis.ai import coder
    coder._last = None
    from jarvis.app import recovery
    from jarvis.tools import permissions
    recovery._offline_since = None
    permissions._events.clear()         # failures, blocks and recoveries start fresh
    from jarvis.app import demo
    demo._running.clear()
    demo._stop.clear()

    # The job database and resume profile start empty for every test too.
    from jarvis.jobs import resume as resume_module, store as job_store
    from jarvis.store import knowledge
    for path in (job_store.DB_PATH, resume_module.PROFILE_PATH, knowledge.DB_PATH):
        _gone(path)
    monkeypatch.setattr(resume_module, "SEARCH_FOLDERS", ())
    yield


@pytest.fixture
def allow():
    """Answer yes to every confirmation."""
    tools.set_confirm(lambda _message: True)
    yield
    tools.set_confirm(lambda _message: False)


@pytest.fixture
def refuse():
    """Answer no to every confirmation."""
    tools.set_confirm(lambda _message: False)
    yield
