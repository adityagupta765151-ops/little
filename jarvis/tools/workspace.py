"""The fence around the filesystem.

Every path a tool touches is resolved through _safe, which refuses
anything outside the workspace folder. One function, one rule, one place
to audit.
"""
from __future__ import annotations

from pathlib import Path

from ..app.config import WORKSPACE

MAX_OUTPUT = 8000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             ".next", "dist", "build"}


def safe_path(path: str) -> Path:
    """Resolve a path inside the workspace, or refuse it."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = WORKSPACE / p
    p = p.resolve()
    if p != WORKSPACE and WORKSPACE not in p.parents:
        raise PermissionError(f"'{p}' is outside the workspace ({WORKSPACE}).")
    return p


def clip(text: str, limit: int = MAX_OUTPUT) -> str:
    """Keep tool output short enough to hand back to the model."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[cut {len(text) - limit} characters]"
