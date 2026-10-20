"""What LITTLE is doing, and what it has done.

Every command becomes a task the moment it arrives, and stays one until
the reply is ready: typed or said, answered on this computer or by the
model, done, failed or stopped. Tools it runs along the way are its steps,
and a confirmation it's waiting on is a real state — WAITING — not a guess.

The window reads this over the bridge: `changed_since(v)` hands over only
the tasks that changed since version v, so a poll stays small and a
reloaded page can catch up by asking from 0.

The registry is in memory, holds the last 50 tasks, and is written from
several threads at once — the voice loop, typed commands, tools — so every
change goes through one lock. A task is bound to the thread that started
it; a tool or a confirmation reports to whatever task its thread is
working on, so nothing has to pass a task id through the brain or the
tools. A thread with no task (a reminder firing, a test) changes nothing.

Outcomes are what the code knows, never read from the wording of a reply:
DONE means the command ran to the end without an error; FAILED means an
error was raised or the planner stopped on a failed step; STOPPED means you
stopped it. A step is "error" only when the tool raised or didn't exist.

Stopping (UI-5) is a request, honoured between steps: the brain checks
before each model call and each tool, the planner before each step, and
`Stopped` is raised from there. A tool already running finishes — nothing
here pretends it can be cut off halfway. What ran stays in the record.

Every step carries `at`, seconds after the task started, and `part`, the
plan step it ran in, so the Task Center can draw the timeline as it was.
"""
from __future__ import annotations

import copy
import itertools
import json
import threading
import time
from collections import OrderedDict

ACTIVE, WAITING, DONE, FAILED, STOPPED = "active", "waiting", "done", "failed", "stopped"
OPEN = (ACTIVE, WAITING)
ENDED = (DONE, FAILED, STOPPED)

LIMIT = 50            # tasks kept
STEP_LIMIT = 40       # steps kept per task; the newest win
TEXT_MAX = 300
DETAIL_MAX = 100
REPLY_MAX = 12000     # a reply is kept whole up to this; the log has all of it

# Where the answer came from. The window says it in words.
ROUTES = ("local", "model", "plan")

# A plan step is "pending" until it starts; the rest say how it went.
PLAN_STATES = ("pending", "running", "done", "failed", "stopped")


class Stopped(Exception):
    """Raised inside a task, between steps, because you asked it to stop."""

_lock = threading.RLock()
_tasks: "OrderedDict[int, dict]" = OrderedDict()
_ids = itertools.count(1)
_version = 0
_local = threading.local()


# ------------------------------------------------------------------ helpers

def _cut(text, limit: int) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _since(task: dict) -> float:
    """Seconds since the task started — where a step sits on its timeline."""
    return round(max(0.0, time.time() - task["started"]), 2)


def _touch(task: dict) -> None:
    global _version
    _version += 1
    task["v"] = _version


def _mine(task_id: int | None) -> dict | None:
    """The task a call is about: the one named, else this thread's."""
    tid = task_id if task_id is not None else getattr(_local, "task", None)
    return _tasks.get(tid) if tid is not None else None


def bind(task_id: int | None) -> None:
    """Report to this task from this thread (a tool run on a helper thread
    still belongs to the task that asked for it)."""
    _local.task = task_id


def preview(args: dict | None, policy: str = "args") -> str:
    """A tool's arguments, short enough for one line, as its logging policy
    allows (Chapter 38): "args" — cut short, anything secret-looking hidden;
    "names" — which arguments, never their values; "none" — nothing."""
    if not args or policy == "none":
        return ""
    if policy == "names":
        return "(" + ", ".join(str(k) for k in args) + ")"
    from ..store.memory import redact
    short = {k: (redact(_cut(v, 60)) if isinstance(v, str) else v) for k, v in args.items()}
    try:
        return _cut(json.dumps(short, ensure_ascii=False), DETAIL_MAX)
    except (TypeError, ValueError):
        return _cut(repr(short), DETAIL_MAX)


# ------------------------------------------------------------ the lifecycle

def start(text: str, source: str = "typed", again_of: int | None = None) -> int:
    """A command arrived. Binds the new task to this thread.

    `again_of` names the task this one asks again (Chat's "Ask again")."""
    with _lock:
        tid = next(_ids)
        task = {
            "id": tid,
            "text": _cut(text, TEXT_MAX),
            "source": "voice" if source == "voice" else "typed",
            "status": ACTIVE,
            "route": None,
            "path": None,        # fast, normal, ai or agent (Chapter 33)
            "started": time.time(),
            "finished": None,
            "ms": None,
            "steps": [],
            "asking": "",
            "error": "",
            "reply": "",
            "reply_cut": False,
            "reset": False,
            "again_of": again_of if isinstance(again_of, int) else None,
            "plan": None,        # [{"text", "status"}] once a plan exists
            "part": None,        # the plan step running now, 1-based
            "stopping": False,   # you asked it to stop
            "stop_at": None,     # when, in seconds after it started
        }
        _tasks[tid] = task
        while len(_tasks) > LIMIT:
            _tasks.popitem(last=False)
        _touch(task)
    _local.task = tid
    return tid


def route(how: str, task_id: int | None = None) -> None:
    if how not in ROUTES:
        return
    with _lock:
        task = _mine(task_id)
        if task and task["route"] != how:
            task["route"] = how
            # Until told it was the fast path, a local answer is "normal".
            task["path"] = {"local": "normal", "model": "ai", "plan": "agent"}[how]
            _touch(task)


def path(name: str, task_id: int | None = None) -> None:
    """Which of the four paths answered: fast, normal, ai or agent."""
    from .latency import PATHS
    if name not in PATHS:
        return
    with _lock:
        task = _mine(task_id)
        if task and task["path"] != name:
            task["path"] = name
            _touch(task)


def reply(text: str, task_id: int | None = None) -> None:
    """What Little answered, as shown on screen. Chat reads it from here."""
    with _lock:
        task = _mine(task_id)
        if not task:
            return
        text = "" if text is None else str(text)
        task["reply"] = text[:REPLY_MAX]
        task["reply_cut"] = len(text) > REPLY_MAX
        _touch(task)


def mark_reset(task_id: int | None = None) -> None:
    """This command started a new conversation: the model forgot the one
    before it. Chat shows what came after."""
    with _lock:
        task = _mine(task_id)
        if task and not task["reset"]:
            task["reset"] = True
            _touch(task)


def step_started(name: str, detail: str = "", task_id: int | None = None) -> int | None:
    """A tool began. Returns the step's number, for step_finished."""
    with _lock:
        task = _mine(task_id)
        if not task or task["status"] in ENDED:
            return None
        task["steps"].append({
            "n": len(task["steps"]) + task.get("dropped", 0),
            "name": _cut(name, 60),
            "detail": _cut(detail, DETAIL_MAX),
            "status": "running",
            "t0": time.perf_counter(),
            "ms": None,
            "at": _since(task),
            "part": task["part"],
        })
        if len(task["steps"]) > STEP_LIMIT:
            task["steps"].pop(0)
            task["dropped"] = task.get("dropped", 0) + 1
        _touch(task)
        return task["steps"][-1]["n"]


def step_finished(n: int | None, error: str = "", task_id: int | None = None) -> None:
    if n is None:
        return
    with _lock:
        task = _mine(task_id)
        if not task:
            return
        for step in task["steps"]:
            if step["n"] == n and step["status"] == "running":
                step["status"] = "error" if error else "done"
                step["ms"] = round((time.perf_counter() - step.pop("t0")) * 1000)
                if error:
                    step["detail"] = _cut(error, DETAIL_MAX)
                _touch(task)
                return


def waiting(message: str, task_id: int | None = None) -> None:
    """Asking you something. The task can't go on until you answer."""
    with _lock:
        task = _mine(task_id)
        if task and task["status"] == ACTIVE:
            task["status"] = WAITING
            task["asking"] = _cut(message, TEXT_MAX)
            _touch(task)


def answered(approved: bool, task_id: int | None = None) -> None:
    """Your answer came back (or the question timed out, which is a no)."""
    with _lock:
        task = _mine(task_id)
        if task and task["status"] == WAITING:
            question = task["asking"]
            task["status"] = ACTIVE
            task["asking"] = ""
            task["steps"].append({
                "n": len(task["steps"]) + task.get("dropped", 0),
                "name": "your answer",
                "detail": "approved" if approved is True else "declined",
                "question": question,
                "status": "done", "ms": None,
                "at": _since(task),
                "part": task["part"],
            })
            _touch(task)


# ------------------------------------------------------------------ plans

def plan(steps: list[str], task_id: int | None = None) -> None:
    """The planner broke the command into these steps."""
    with _lock:
        task = _mine(task_id)
        if task and task["status"] in OPEN:
            task["plan"] = [{"text": _cut(s, TEXT_MAX), "status": "pending"} for s in steps]
            _touch(task)


def plan_step(n: int, status: str, task_id: int | None = None) -> None:
    """Step n (1-based) of the plan is now running, done, failed or stopped."""
    if status not in PLAN_STATES:
        return
    with _lock:
        task = _mine(task_id)
        if not task or not task["plan"] or not 1 <= n <= len(task["plan"]):
            return
        task["plan"][n - 1]["status"] = status
        task["part"] = n if status == "running" else None
        _touch(task)


# --------------------------------------------------------------- stopping

def request_stop(task_id: int) -> bool:
    """You asked this task to stop. It will, at its next step."""
    with _lock:
        task = _tasks.get(task_id) if isinstance(task_id, int) and not isinstance(task_id, bool) else None
        if not task or task["status"] not in OPEN or task["stopping"]:
            return False
        task["stopping"] = True
        task["stop_at"] = _since(task)
        _touch(task)
        return True


def stop_open(exclude: int | None = None) -> list[int]:
    """Ask every open task to stop — Esc, the Stop button, saying "stop" —
    except `exclude`, the "stop" command's own task."""
    with _lock:
        ids = [t["id"] for t in _tasks.values() if t["status"] in OPEN and t["id"] != exclude]
    return [tid for tid in ids if request_stop(tid)]


def stop_requested(task_id: int | None = None) -> bool:
    """Has this thread's task (or the one named) been asked to stop?"""
    with _lock:
        task = _mine(task_id)
        return bool(task and task["stopping"])


def check_stop(task_id: int | None = None) -> None:
    """Raise Stopped if this task has been asked to stop. Called between steps."""
    if stop_requested(task_id):
        raise Stopped()


def finish(status: str, error: str = "", task_id: int | None = None) -> None:
    """The reply is ready. Unbinds the task from this thread."""
    if status not in ENDED:
        status = DONE
    status_was_open = False
    with _lock:
        task = _mine(task_id)
        if task and task["status"] in OPEN:
            status_was_open = True
            task["status"] = status
            task["finished"] = time.time()
            task["ms"] = round((task["finished"] - task["started"]) * 1000)
            task["asking"] = ""
            task["error"] = _cut(error, TEXT_MAX) if status == FAILED else ""
            for step in task["steps"]:          # a step can't outlive its task
                if step["status"] == "running":
                    step["status"] = "error" if status == FAILED else "done"
                    step["ms"] = round((time.perf_counter() - step.pop("t0")) * 1000)
            for part in task["plan"] or []:     # nor can a plan step
                if part["status"] == "running":
                    part["status"] = {FAILED: "failed", STOPPED: "stopped"}.get(status, "done")
            task["part"] = None
            _touch(task)
    if task:
        # Task memory (Chapter 30) lives only while its task runs.
        from ..store import memory
        memory.forget_task(task["id"])
        # How long it took, under the path that answered (Chapter 33).
        if task.get("path") and task.get("ms") is not None and status_was_open:
            from . import latency
            latency.record(task["path"], task["ms"])
        # What was asked and how it ended, in the audit log (Chapter 41).
        if status_was_open:
            from . import audit
            audit.task_done(_public(task))
    bound = getattr(_local, "task", None)
    if task_id is None or bound == task_id:
        _local.task = None


# ----------------------------------------------------------------- reading

def _public(task: dict) -> dict:
    """A copy safe to hand out: no timers, nothing that changes under you."""
    out = copy.deepcopy(task)
    out.pop("dropped", None)
    for step in out["steps"]:
        step.pop("t0", None)
    return out


def version() -> int:
    return _version


def changed_since(since: int = 0) -> tuple[int, list[dict]]:
    """(current version, the tasks that changed after `since`), oldest first."""
    with _lock:
        return _version, [_public(t) for t in _tasks.values() if t["v"] > since]


def current() -> dict | None:
    """The task being worked on: the oldest one still open."""
    with _lock:
        for task in _tasks.values():
            if task["status"] in OPEN:
                return _public(task)
    return None


def recent(n: int = 10) -> list[dict]:
    with _lock:
        return [_public(t) for t in list(_tasks.values())[-n:][::-1]]


def get(task_id) -> dict | None:
    """One task by id, or None. Accepts only a real whole number."""
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        return None
    with _lock:
        task = _tasks.get(task_id)
        return _public(task) if task else None


def latest(route: str) -> dict | None:
    """The newest task answered by `route` ("model", "local", "plan")."""
    with _lock:
        for task in reversed(_tasks.values()):
            if task["route"] == route:
                return _public(task)
    return None


def current_id() -> int | None:
    return getattr(_local, "task", None)


def reset() -> None:
    """Forget everything. For tests."""
    global _version
    with _lock:
        _tasks.clear()
        _version = 0
    _local.task = None
