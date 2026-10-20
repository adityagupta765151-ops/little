"""Checks on the test suite itself.

A test class or function defined twice in one file silently replaces the
first — its tests stop running and nothing says so. It happened once
(UI-5: a second `TestStopThis` hid eight backend tests). This keeps it from
happening again.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS = sorted(Path(__file__).resolve().parent.glob("test_*.py"))


@pytest.mark.parametrize("path", TESTS, ids=lambda p: p.name)
def test_no_test_is_hidden_by_another_of_the_same_name(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top = [n.name for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))]
    shadowed = {n for n in top if top.count(n) > 1}
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        names = [m.name for m in cls.body if isinstance(m, ast.FunctionDef)]
        shadowed |= {f"{cls.name}.{n}" for n in names if names.count(n) > 1}
    assert not shadowed, f"defined twice, so only the last one runs: {sorted(shadowed)}"
