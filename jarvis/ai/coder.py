"""The coding agent (Chapter 44): inspect, explain the plan, make the smallest
change, test, report.

  INSPECT       the project's files, the ones the request names or that
                contain its words, read — and how its tests are run
  EXPLAIN PLAN  the strong model says what it understood and plans, as exact
                small replacements ("this text" becomes "that text"); you
                see the plan and the changes before anything is touched
  MINIMAL       every change is checked before any is made: inside the
  CHANGE        workspace, the old text found exactly once, no rewriting
                whole files, at most a few files — or nothing is changed.
                Originals are kept so the change can be undone
  TEST          the tests run before (so failures that were already there
                aren't blamed on the change) and after
  REPORT        what was read, the plan, what changed, the tests before and
                after, and how to undo it

Changing your files and running your tests is one question, asked once,
with the changes in it. "Undo the last code change" puts the originals back
(and removes files it created), asking first.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..app import config
from ..app.config import log

MAX_FILES_CHANGED = 5
MAX_LINES_PER_CHANGE = 40
MAX_CONTEXT_CHARS = 14000
MAX_FILE_CHARS = 5000
TEST_TIMEOUT = 300
CODE_SUFFIXES = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".rb", ".php", ".c", ".cpp", ".h",
                 ".cs", ".kt", ".swift", ".css", ".html", ".json", ".toml", ".yaml", ".yml", ".md", ".sql", ".sh"}
BACKUPS = config.MEMORY_DIR / "code_backups"

PLAN_PROMPT = """You are making a small, careful change to a code project.

Request: {request}

Files in the project:
{files}

Files read:
{contents}

Tests are run with: {tests}

Reply with one JSON object and nothing else:
{{"understood": "the request in one sentence",
  "plan": ["short step", "..."],
  "changes": [{{"path": "relative/path", "old": "exact text now in the file", "new": "what replaces it",
               "why": "a few words"}}],
  "create": [{{"path": "relative/path/new_file", "content": "...", "why": "a few words"}}]}}
Rules: the smallest change that does it. "old" must be copied exactly from the file and appear in it once.
Don't rewrite whole files. Don't change tests to make them pass unless the request says so. No explanation
outside the JSON."""

_last: dict | None = None        # the last change made, for undo


class Refused(Exception):
    """A plan that isn't safe or small enough to apply, in words."""


# ----------------------------------------------------------------- inspect

def _root(path: str) -> Path:
    from ..tools.workspace import safe_path
    root = safe_path(path or ".")
    if not root.is_dir():
        raise Refused(f"{root} isn't a folder.")
    return root


def _project_files(root: Path) -> list[Path]:
    from ..tools.workspace import SKIP_DIRS
    found = [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix.lower() in CODE_SUFFIXES
             and not any(part in SKIP_DIRS or part.startswith(".") for part in p.relative_to(root).parts)]
    return found[:400]


def _words(request: str) -> set[str]:
    return {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", request)
            if w.lower() not in {"the", "and", "fix", "add", "make", "change", "function", "file", "code", "bug",
                                 "please", "that", "this", "with", "into", "for", "from", "test", "tests"}}


def relevant(root: Path, request: str, files: list[Path]) -> list[Path]:
    """The files the request names, then those containing its words, most
    matches first; at most six."""
    words = _words(request)
    lowered = {w.lower() for w in words}
    named = [f for f in files if f.name in request or str(f.relative_to(root)) in request
             or f.stem.lower() in lowered]
    scored = []
    for f in files:
        if f in named:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = sum(1 for w in words if w in text)
        if hits:
            scored.append((hits, f))
    scored.sort(key=lambda pair: -pair[0])
    return (named + [f for _, f in scored])[:6]


def test_command(root: Path) -> list[str] | None:
    """How this project's tests run, or None if it has none this knows."""
    if (root / "package.json").exists():
        try:
            scripts = json.loads((root / "package.json").read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, json.JSONDecodeError):
            scripts = {}
        if "test" in scripts and "no test specified" not in scripts["test"]:
            return ["npm", "test", "--silent"]
    python_tests = any(root.glob("test_*.py")) or any(root.glob("tests/test_*.py")) or \
        any((root / n).exists() for n in ("pytest.ini", "tox.ini"))
    return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"] if python_tests else None


def shown(command: list[str] | None) -> str:
    """A test command as a person would type it."""
    if not command:
        return ""
    if command[0] == sys.executable:
        return "python " + " ".join(command[1:4])
    return " ".join(command)


def run_tests(root: Path, command: list[str] | None) -> dict:
    """{"ran", "ok", "summary"}: exit status and the last line that says how it went."""
    if not command:
        return {"ran": False, "ok": None, "summary": "no tests found to run"}
    try:
        # No bytecode written, so a change made within the same second as a
        # cached copy can't be run from the stale cache.
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=TEST_TIMEOUT, env=env)
    except FileNotFoundError:
        return {"ran": False, "ok": None, "summary": f"{command[0]} isn't installed"}
    except subprocess.TimeoutExpired:
        return {"ran": True, "ok": False, "summary": f"still running after {TEST_TIMEOUT} s, so I stopped them"}
    lines = [line.strip() for line in (done.stdout + "\n" + done.stderr).splitlines() if line.strip()]
    summary = next((line for line in reversed(lines) if re.search(r"\bpassed\b|\bfailed\b|\berror|tests?\b", line,
                                                                re.I)), lines[-1] if lines else "")
    return {"ran": True, "ok": done.returncode == 0, "summary": summary.strip("= ")[:200]}


# -------------------------------------------------------------------- plan

def _ask_plan(request: str, root: Path, files: list[Path], read: list[Path], tests: list[str] | None) -> dict:
    from . import models
    from .provider import ask_text
    listing = "\n".join(str(f.relative_to(root)) for f in files[:200])
    contents, used = [], 0
    for f in read:
        text = f.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
        if used + len(text) > MAX_CONTEXT_CHARS:
            break
        used += len(text)
        contents.append(f"--- {f.relative_to(root)} ---\n{text}")
    with models.use("strong"):
        raw = ask_text(PLAN_PROMPT.format(request=request, files=listing or "(none)", contents="\n\n".join(contents)
                                          or "(none)", tests=" ".join(tests) if tests else "no tests found"), empty="")
    match = re.search(r"\{.*\}", raw or "", re.S)
    try:
        plan = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        plan = None
    if not isinstance(plan, dict):
        raise Refused("The plan I got back couldn't be read, so I changed nothing.")
    return plan


def check(plan: dict, root: Path) -> list[dict]:
    """Every change, checked before any is made: [{"path", "file", "old",
    "new", "why", "kind"}]. Raises Refused with the first reason."""
    from ..tools.workspace import safe_path
    out = []

    def inside(path: str) -> Path:
        try:
            return safe_path(str(root / path))
        except PermissionError as e:
            raise Refused(f"{path} is outside the workspace, so I won't touch it.") from e

    for change in plan.get("changes") or []:
        if not isinstance(change, dict) or not all(isinstance(change.get(k), str) for k in ("path", "old", "new")):
            raise Refused("A change in the plan was missing its file or text.")
        target = inside(change["path"])
        if not target.is_file():
            raise Refused(f"{change['path']} doesn't exist.")
        text = target.read_text(encoding="utf-8", errors="replace")
        found = text.count(change["old"]) if change["old"] else 0
        if found != 1:
            raise Refused(f"In {change['path']}, the text to replace was found {found} times, not once.")
        lines_old, lines_new = change["old"].count("\n") + 1, change["new"].count("\n") + 1
        if max(lines_old, lines_new) > MAX_LINES_PER_CHANGE or (
                text.count("\n") > 40 and len(change["old"]) > len(text) * 0.6):
            raise Refused(f"The change to {change['path']} rewrites too much of it to be a small change.")
        out.append({"path": change["path"], "file": target, "old": change["old"], "new": change["new"],
                    "why": str(change.get("why", ""))[:120], "kind": "edit"})
    for new in plan.get("create") or []:
        if not isinstance(new, dict) or not isinstance(new.get("path"), str) or not isinstance(new.get("content"), str):
            raise Refused("A new file in the plan was missing its name or content.")
        target = inside(new["path"])
        if target.exists():
            raise Refused(f"{new['path']} already exists; I won't overwrite it.")
        if new["content"].count("\n") > MAX_LINES_PER_CHANGE * 3:
            raise Refused(f"The new file {new['path']} is too big to be a small change.")
        out.append({"path": new["path"], "file": target, "old": "", "new": new["content"],
                    "why": str(new.get("why", ""))[:120], "kind": "create"})
    if not out:
        raise Refused("The plan had no changes in it.")
    if len({c["path"] for c in out}) > MAX_FILES_CHANGED:
        raise Refused(f"The plan touches more than {MAX_FILES_CHANGED} files; that's not a small change.")
    return out


def _diff(changes: list[dict]) -> str:
    parts = []
    for c in changes:
        if c["kind"] == "create":
            parts.append(f"new file {c['path']} ({c['new'].count(chr(10)) + 1} lines) — {c['why']}")
        else:
            parts.append(f"{c['path']} — {c['why']}\n- " + "\n- ".join(c["old"].splitlines()) +
                         "\n+ " + "\n+ ".join(c["new"].splitlines()))
    return "\n\n".join(parts)


# ------------------------------------------------------------------- apply

def _apply(changes: list[dict], root: Path) -> Path:
    """Keep the originals, then make every change. Returns the backup folder."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = BACKUPS / stamp
    for c in changes:
        if c["kind"] == "edit":
            kept = backup / c["path"]
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(c["file"], kept)
    for c in changes:
        if c["kind"] == "edit":
            before = c["file"].stat().st_mtime
            text = c["file"].read_text(encoding="utf-8")
            c["file"].write_text(text.replace(c["old"], c["new"], 1), encoding="utf-8")
            # A clearly newer time, so nothing cached from before is reused.
            stamp = max(time.time(), before + 2)
            os.utime(c["file"], (stamp, stamp))
        else:
            c["file"].parent.mkdir(parents=True, exist_ok=True)
            c["file"].write_text(c["new"], encoding="utf-8")
    return backup


def code_change(request: str, path: str = ".") -> str:
    """The tool: a small, tested change to a project in the workspace."""
    global _last
    from ..tools.permissions import Ask, confirm
    request = " ".join(str(request or "").split())
    if not request:
        return "Tell me what to change."
    try:
        root = _root(path)
    except (Refused, PermissionError) as e:
        return str(e)
    files = _project_files(root)
    if not files:
        return f"I found no code in {root.name}."
    read = relevant(root, request, files)
    tests = test_command(root)
    try:
        plan = _ask_plan(request, root, files, read, tests)
        changes = check(plan, root)
    except Refused as e:
        return f"INSPECT: read {', '.join(str(f.relative_to(root)) for f in read) or 'nothing relevant'}.\n{e}"
    except RuntimeError as e:
        return f"I couldn't get a plan from the model: {e} Nothing was changed."

    steps = [str(s)[:160] for s in plan.get("plan") or [] if str(s).strip()][:8]
    understood = " ".join(str(plan.get("understood", "")).split())[:200]
    diff = _diff(changes)
    touched = sorted({c["path"] for c in changes})
    ask = Ask(f"Change {len(touched)} file{'s' if len(touched) > 1 else ''} in {root.name}"
              f"{' and run the tests' if tests else ''}?\n\n{diff}",
              action="Change your code" + (" and run its tests" if tests else ""),
              target=f"{', '.join(touched)} in {root.name}",
              details=(f"{understood}\n\n" if understood else "") + diff +
                      (f"\n\nThen the tests: {shown(tests)}" if tests else ""),
              consequence="The originals are kept, so it can be undone.",
              tone="caution", verb="Make the change", tool="code_change")
    if confirm(ask) is not True:
        return "You said no, so I changed nothing."

    before = run_tests(root, tests)
    backup = _apply(changes, root)
    _last = {"root": str(root), "backup": str(backup), "changes": [{"path": c["path"], "kind": c["kind"]}
                                                                    for c in changes]}
    after = run_tests(root, tests)
    log(f"code change: {len(changes)} change(s) in {len(touched)} file(s); tests {after['ok']}")

    lines = [f"INSPECT: read {', '.join(str(f.relative_to(root)) for f in read) or 'the file list'}"
             f"{'; tests run with ' + shown(tests) if tests else '; no tests found'}.",
             "PLAN: " + (understood + " " if understood else "") + " → ".join(steps),
             "CHANGE: " + "; ".join(f"{c['path']} ({'new file' if c['kind'] == 'create' else c['why'] or 'edited'})"
                                    for c in changes) + "."]
    if not after["ran"]:
        lines.append(f"TEST: not run — {after['summary']}. The change is untested.")
    else:
        said_before = "passed" if before["ok"] else before["summary"]
        lines.append(f"TEST: before the change {said_before}; after it "
                     f"{'passed' if after['ok'] else 'FAILED'} — {after['summary']}.")
    lines.append("REPORT: " + ("done, and the tests pass." if after["ok"] else
                               "the change is made but the tests don't pass." if after["ran"] else
                               "the change is made; nothing tested it.")
                 + " Say undo the last code change to put the originals back.")
    return "\n".join(lines)


def undo_last() -> str:
    """Put back what the last code change replaced, and remove files it made."""
    global _last
    from ..tools.permissions import Ask, confirm
    if not _last:
        return "There's no code change of mine to undo."
    root, backup = Path(_last["root"]), Path(_last["backup"])
    names = [c["path"] for c in _last["changes"]]
    ask = Ask(f"Undo the last code change in {root.name}?\n\n" + "\n".join(names),
              action="Undo a code change", target=", ".join(names),
              details="Edited files go back to how they were before it; files it created are removed. Anything "
                      "you changed in them since is lost.",
              consequence="Changes made to these files since then are lost.", tone="caution", verb="Undo",
              tool="code_change")
    if confirm(ask) is not True:
        return "Okay, I left it."
    for change in _last["changes"]:
        target = root / change["path"]
        if change["kind"] == "edit":
            shutil.copy2(backup / change["path"], target)
        elif target.exists():
            target.unlink()
    _last = None
    return f"Undone: {', '.join(names)} are back as they were."
