"""The audit log (Chapter 41): what LITTLE did, and how it went.

One line of JSON per event in `audit.jsonl` in the memory folder:

  task   a command finished — when, what you asked (the intent), the path
         that answered, how it ended, how long it took, any error
  tool   a tool ran for it — the tool, its arguments as its logging policy
         allows, what it returned (a summary, or only how long it was),
         how long it took, whether it worked, any question it asked and
         your answer, any error

What never goes in: API keys, passwords, tokens and anything shaped like
them (hidden as [hidden] wherever they appear); the values of arguments a
tool's policy keeps out (messages, contacts, what you asked to be
remembered, file contents, form values); and what tools return about you —
your resume, files, pages, chats, memory — which is logged only as a
length. Arguments and results are cut short either way.

"Show me what you did for my last task" is answered from here; so is
"show the audit log". The file keeps about the last megabyte: when it grows
past that, the older half goes.
"""
from __future__ import annotations

import datetime
import json
import threading
import uuid

from . import config
from .config import log

PATH = config.MEMORY_DIR / "audit.jsonl"
MAX_BYTES = 1024 * 1024
INTENT_CHARS, ARG_CHARS, RESULT_CHARS, ERROR_CHARS = 120, 80, 160, 200
SESSION = uuid.uuid4().hex[:8]          # task ids start again at 1 each run

# What these tools return is about you — your resume, files, pages, chats,
# memory — so only its length is logged.
PRIVATE_RESULTS = set("""read_file read_page summarize_page look_at_page find_on_page describe_screen show_resume_profile
check_resume scan_resume recall recall_memory recall_project ask_documents search_documents wa_read_chat wa_contacts
find_contacts count_contacts why_this_job missing_skills search_files list_dir get_system_info
search_web_and_read""".split())
SECRET_WORDS = {"password", "passcode", "passphrase", "token", "secret", "otp", "pin", "cvv", "credential"}
SECRET_KEYS = {"api_key", "apikey", "access_key", "private_key", "auth", "authorization"}

_lock = threading.Lock()


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _redact(text) -> str:
    from ..store.memory import redact
    return redact(" ".join(str(text or "").split()))


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def sanitize_args(name: str, args) -> dict:
    """A tool's arguments as they may be kept: by its logging policy, with
    anything named or shaped like a secret hidden, and every value cut."""
    from ..tools.catalog import log_policy
    if not isinstance(args, dict):
        return {}
    policy = log_policy(name)
    if policy == "none":
        return {}
    out = {}
    for key, value in args.items():
        key = str(key)[:40]
        if policy == "names":
            out[key] = "[not logged]"
        elif key.lower() in SECRET_KEYS or set(key.lower().replace("-", "_").split("_")) & SECRET_WORDS:
            out[key] = "[hidden]"
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
        else:
            out[key] = _cut(_redact(value if isinstance(value, str) else json.dumps(value, default=str)), ARG_CHARS)
    return out


def sanitize_result(name: str, result) -> str:
    """What a tool returned, as it may be kept: a short summary, or — when
    it's about you, or echoes arguments that aren't logged — only its length."""
    from ..tools.catalog import log_policy
    text = str(result if result is not None else "")
    if name in PRIVATE_RESULTS or name.startswith("mcp__") or log_policy(name) != "args":
        return f"[{len(text)} characters, not logged]"
    return _cut(_redact(text), RESULT_CHARS)


def _write(entry: dict) -> None:
    line = json.dumps(entry, ensure_ascii=False, default=str)
    with _lock:
        try:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            with PATH.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            if PATH.stat().st_size > MAX_BYTES:
                kept = PATH.read_text(encoding="utf-8").splitlines()
                PATH.write_text("\n".join(kept[len(kept) // 2:]) + "\n", encoding="utf-8")
        except OSError as e:
            log(f"audit write failed: {e}")


def tool_run(name: str, args, result, ms: float, error: str = "", answers: list | None = None,
             task_id: int | None = None) -> None:
    """One tool run, for the task it belongs to."""
    asked = [{"action": a.get("action", ""), "answer": "yes" if a.get("approved") else "no"} for a in answers or []]
    _write({"kind": "tool", "at": _now(), "session": SESSION, "task": task_id, "tool": str(name)[:80],
            "args": sanitize_args(name, args), "result": sanitize_result(name, result) if not error else "",
            "ms": round(ms), "ok": not error, "confirmation": asked or None,
            "error": _cut(_redact(error), ERROR_CHARS) if error else ""})


def task_done(task: dict) -> None:
    """A finished task: what you asked and how it ended."""
    _write({"kind": "task", "at": _now(), "session": SESSION, "task": task.get("id"),
            "intent": _cut(_redact(task.get("text", "")), INTENT_CHARS), "route": task.get("route"),
            "path": task.get("path"), "status": task.get("status"), "ms": task.get("ms"),
            "ok": task.get("status") == "done",
            "error": _cut(_redact(task.get("error", "")), ERROR_CHARS)})


# ----------------------------------------------------------------- reading

def entries(limit: int = 500) -> list[dict]:
    """The newest `limit` entries, oldest first. Lines that can't be read
    are skipped."""
    if not PATH.exists():
        return []
    try:
        lines = PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def _seconds(ms) -> str:
    if not isinstance(ms, (int, float)):
        return "?"
    return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


PATH_WORDS = {"fast": "on this computer", "normal": "with this computer's tools", "ai": "with the model",
              "agent": "as a plan"}


def last_task() -> str:
    """ "Show me what you did for my last task." """
    found = entries(2000)
    done = [e for e in found if e.get("kind") == "task"]
    if not done:
        return "I haven't finished a task yet, so there's nothing to show."
    task = done[-1]
    steps = [e for e in found if e.get("kind") == "tool" and e.get("session") == task.get("session")
             and e.get("task") == task.get("task")]
    how = {"done": "done", "failed": "failed", "stopped": "stopped"}.get(task.get("status"), task.get("status"))
    lines = [f"Your last task: “{task.get('intent')}” — {how} in {_seconds(task.get('ms'))}, "
             f"{PATH_WORDS.get(task.get('path'), 'answered')}."]
    if task.get("error"):
        lines.append(f"What went wrong: {task['error']}")
    if not steps:
        lines.append("No tools ran for it.")
    for n, step in enumerate(steps, 1):
        args = ", ".join(f"{k}={v}" for k, v in (step.get("args") or {}).items())
        outcome = "worked" if step.get("ok") else f"failed: {step.get('error')}"
        line = f"{n}. {step.get('tool')}({args}) — {outcome}, {_seconds(step.get('ms'))}"
        for question in step.get("confirmation") or []:
            line += f"; asked “{question['action']}”, you said {question['answer']}"
        if step.get("ok") and step.get("result"):
            line += f". {step['result']}"
        lines.append(line)
    return "\n".join(lines)


def recent_report(limit: int = 10) -> str:
    """ "Show the audit log": the latest tasks, one line each."""
    done = [e for e in entries(2000) if e.get("kind") == "task"][-limit:]
    if not done:
        return "The audit log is empty."
    return "\n".join(f"{e.get('at', '')[11:16]} {e.get('status')}: “{e.get('intent')}” ({_seconds(e.get('ms'))})"
                     for e in reversed(done))
