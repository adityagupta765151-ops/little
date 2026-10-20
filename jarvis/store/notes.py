"""Chat's "Save": a turn kept as a note you can open.

Saved turns go into one Markdown file in your workspace — "Saved from
Little.md" — rather than into Little's memory, so they're easy to read,
edit or delete, and don't change what Little knows about you. (Decision D2
in the redesign plan.)

Each save appends; nothing already in the file is touched.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from ..app import config


def path() -> Path:
    return config.WORKSPACE / f"Saved from {config.ASSISTANT_CALL}.md"


def save_turn(asked: str, answered: str, when: float | None = None) -> Path:
    """Append one turn — what you asked and what Little answered."""
    stamp = datetime.datetime.fromtimestamp(when) if when else datetime.datetime.now()
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fresh = not target.exists() or target.stat().st_size == 0

    with target.open("a", encoding="utf-8", newline="\n") as f:
        if fresh:
            f.write(f"# Saved from {config.ASSISTANT_CALL}\n\n")
        f.write(f"## {stamp:%d %b %Y, %H:%M}\n\n")
        f.write(f"**You:** {asked.strip()}\n\n")
        f.write(f"**{config.ASSISTANT_CALL}:**\n\n{answered.strip()}\n\n---\n\n")
    return target
