"""The tools JARVIS can run.

Each module here is one domain and knows nothing about the model. The
registry assembles them and describes them; permissions holds the
confirmation gate; workspace holds the filesystem fence.

Importing this package gives the same names the single tools.py used to,
so the rest of the code and the tests did not have to change shape.
"""
from __future__ import annotations

from .permissions import NEEDS_CONFIRMATION, confirm, confirm_fn, set_confirm
from .registry import FUNCTIONS, TOOL_SCHEMAS, execute_tool
from .workspace import safe_path

__all__ = [
    "FUNCTIONS", "TOOL_SCHEMAS", "execute_tool",
    "NEEDS_CONFIRMATION", "confirm", "confirm_fn", "set_confirm",
    "safe_path",
]
