"""Breaking a big request into steps, then working through them.

Only complex requests come here. A one-line job goes straight to the
brain, because planning costs an extra model call and would only slow it
down. While a plan runs, its steps and their state are readable from
`current()`, which is what the panel shows.

Planner 2.0 (Chapter 32) runs every plan the same way:

  GOAL -> UNDERSTAND -> PLAN -> EXECUTE -> OBSERVE -> VERIFY -> RECOVER -> RESULT

- UNDERSTAND + PLAN: one call. The model restates the goal in a sentence
  and lists steps, each with how to tell it worked and any files it should
  leave. (A plain numbered list still works; its steps just have no check.)
- EXECUTE: each step through the brain, with the tools it already has —
  and their gates: anything that deletes, runs a command or sends asks you.
- OBSERVE: what the tools returned during the step, read from the brain's
  history, and whether you said no to anything.
- VERIFY: files the step should leave are looked for on disk; the step's
  check is judged against the tools' output, never the model's word alone.
  A step with nothing to judge it by is "not checked", not "done".
- RECOVER: a step that failed or wasn't verified gets one more try, told
  what went wrong. Not after you said no: that ends the plan.
- RESULT: what was checked, what couldn't be, and where it stopped. Only
  results and evidence are shown — never the model's reasoning.
"""
from __future__ import annotations

import json
import re
import threading
import time

from ..app import tasks
from ..app.config import log
from ..tools import permissions
from .prompts import PLAN, RECOVER, STEP, VERIFY
from .provider import ask_text

MAX_STEPS = 8
RECOVERIES = 1          # more tries per step after the first
OBSERVED_CHARS = 1200   # of each tool result shown to the check

# Phrasings that suggest more than one action. Deliberately narrow: a
# request that slips through just goes to the brain as before.
COMPLEX = re.compile(
    r"\b(and then|then |after that|first .* then)\b"
    r"|\b(create|make|build|set ?up|scaffold|generate)\b.*\b(project|app|website|api|server|component)\b"
    r"|\brun (my|the) project\b"
    r"|\b(install|clone)\b.*\b(and|then)\b"
    r"|\bfix\b.*\b(all|every|errors)\b"
    r"|\b(prepare|get)\b.*\b(project|repo|code)\b.*\b(for|on|to)\b.*\b(github|git|release|submission)\b", re.I)
GITHUB = re.compile(r"\bgithub\b", re.I)

FAILED = re.compile(r"^FAILED:|(\bI )?(couldn't|could not|failed to|unable to)\b", re.I)

_lock = threading.Lock()
_current: dict | None = None
_cancel = threading.Event()


def current() -> dict | None:
    """What the panel shows: the goal, the steps and where we are."""
    return _current


def cancel() -> None:
    _cancel.set()


def should_plan(command: str) -> bool:
    """Worth the extra call? Only for requests that clearly have parts."""
    text = command.strip()
    if len(text.split()) < 5:
        return False
    return bool(COMPLEX.search(text))


def _parse(raw: str) -> list[str]:
    steps = []
    for line in raw.splitlines():
        match = re.match(r"\s*(\d+)[.)]\s+(.{3,})", line)
        if match:
            steps.append(match.group(2).strip().rstrip("."))
    return steps[:MAX_STEPS]


def _parse_plan(raw: str) -> tuple[str, list[dict]]:
    """The goal as understood and the steps: [{"do", "check", "files"}].
    A JSON plan first; otherwise numbered lines, whose steps have no check."""
    match = re.search(r"\{.*\}", raw or "", re.S)
    data = None
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
    if isinstance(data, dict) and isinstance(data.get("steps"), list):
        steps = []
        for item in data["steps"]:
            item = {"do": item} if isinstance(item, str) else item
            if not isinstance(item, dict):
                continue
            do = " ".join(str(item.get("do") or "").split()).rstrip(".")
            if len(do) < 3:
                continue
            files = item.get("files") if isinstance(item.get("files"), list) else []
            steps.append({"do": do, "check": " ".join(str(item.get("check") or "").split()),
                          "files": [str(f).strip() for f in files if isinstance(f, str) and f.strip()][:10]})
        return " ".join(str(data.get("goal") or "").split())[:200], steps[:MAX_STEPS]
    return "", [{"do": step, "check": "", "files": []} for step in _parse(raw or "")]


# ----------------------------------------------------------------- observe

def _entries(brain) -> set[int]:
    history = getattr(brain, "history", None)
    return {id(e) for e in history} if isinstance(history, list) else set()


def _observe(brain, before: set[int]) -> list[dict]:
    """The tools that ran since `before`, with their arguments and what they
    returned, in order. Nothing if the brain keeps no history."""
    history = getattr(brain, "history", None)
    if not isinstance(history, list):
        return []
    calls, seen = [], []
    for entry in history:
        if id(entry) in before or not isinstance(entry, dict):
            continue
        for part in entry.get("parts", []):
            if "functionCall" in part:
                calls.append(part["functionCall"])
            if "functionResponse" in part:
                response = part["functionResponse"]
                args = next((c.get("args") or {} for c in calls if c.get("name") == response.get("name")), {})
                seen.append({"tool": str(response.get("name")), "args": args,
                             "result": str((response.get("response") or {}).get("result"))[:OBSERVED_CHARS]})
    return seen


def _declined(since: int) -> bool:
    """Did you say no to anything on this thread since answer number
    `since`? (A timeout counts as no.)"""
    return any(not a["approved"] for a in permissions.answers(since=since, this_thread=True))


# ------------------------------------------------------------------ verify

def _missing(files: list[str]) -> list[str]:
    from ..tools.workspace import safe_path
    gone = []
    for name in files:
        try:
            if not safe_path(name).exists():
                gone.append(name)
        except PermissionError:
            gone.append(f"{name} (outside the workspace)")
    return gone


def _verify(step: dict, reply: str, observed: list[dict]) -> tuple[bool | None, str]:
    """(True, evidence), (False, why) — or (None, why) when there's nothing
    to judge it by. Files are looked for on disk; the check is judged from
    the tools' output, never from the model's report alone."""
    missing = _missing(step["files"])
    if missing:
        return False, f"{', '.join(missing)} isn't there."
    if not step["check"]:
        return (True, "the files are there") if step["files"] else (None, "")
    if not observed:
        return (True, "the files are there") if step["files"] else (None, "no tool ran, so there was nothing to check")
    shown = "\n".join(f"- {o['tool']}: {o['result']}" for o in observed)
    try:
        from . import models
        with models.use("fast"):            # a short judgement from given evidence (Chapter 43)
            raw = ask_text(VERIFY.format(step=step["do"], check=step["check"], observed=shown, reply=reply[:400]))
    except Exception as e:  # noqa: BLE001
        log(f"plan check failed: {e}")
        return None, "the check couldn't run"
    match = re.search(r"\{.*\}", raw or "", re.S)
    try:
        said = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        said = None
    if not isinstance(said, dict) or not isinstance(said.get("verified"), bool):
        return None, "the check's answer couldn't be read"
    evidence = " ".join(str(said.get("evidence") or "").split())[:200]
    return said["verified"], evidence or ("it shows in the tools' output" if said["verified"] else "it doesn't show")


def _github_check(everything: list[dict]) -> str | None:
    """For a GitHub goal: the checklist again, on the folder the plan looked
    at. None if the plan never looked."""
    paths = [o["args"].get("path", ".") for o in everything if o["tool"] == "check_github_ready"]
    if not paths:
        return None
    from ..tools import project_check
    try:
        found = project_check.check(paths[-1])
    except (PermissionError, NotADirectoryError) as e:
        return str(e)
    todo = [f"{i['what']} ({i['detail']})" for i in found["items"] if not i["ok"]]
    return "" if not todo else "The final check found " + "; ".join(todo) + "."


# --------------------------------------------------------------------- run

def run(command: str, brain, say, status, outcome: dict | None = None) -> str:
    """Plan the request, then carry it out step by step.

    `say` puts a line in the activity log; `status` sets the panel state.
    Returns the sentence to speak at the end.

    `outcome`, if given, is filled in with how it ended — "done", "failed"
    (with the reason) or "stopped" — so the task record can say so without
    reading the sentence.
    """
    ended = outcome if outcome is not None else {}

    def end(how: str, reply: str, error: str = "") -> str:
        ended.update(status=how, error=error)
        return reply

    if not _lock.acquire(blocking=False):
        return end("failed", "I'm already working through a plan. Say stop to cancel it.",
                   "Another plan is still running.")

    _cancel.clear()
    try:
        status("thinking")
        try:
            raw = ask_text(PLAN.format(goal=command, max=MAX_STEPS))
        except RuntimeError as e:
            return end("failed", str(e), str(e))

        if raw.strip().upper().startswith("SIMPLE"):
            return end("done", brain.ask(command))

        understood, steps = _parse_plan(raw)
        if len(steps) < 2:
            return end("done", brain.ask(command))
        return _work(command, understood, steps, 1, brain, say, status, end)
    finally:
        _lock.release()


# A plan that stopped — you stopped it, said no, or a step failed — can be
# picked up where it stopped (Chapter 35: "continue").
RESUMABLE_FOR = 30 * 60           # seconds
_resumable: dict | None = None


def resumable() -> dict | None:
    """The plan "continue" would pick up: {"goal", "at", "count"}, or None."""
    plan = _resumable
    if not plan or time.monotonic() - plan["when"] > RESUMABLE_FOR:
        return None
    return {"goal": plan["command"], "at": plan["at"], "count": len(plan["steps"])}


def resume(brain, say, status, outcome: dict | None = None) -> str | None:
    """Carry on the stopped plan from the step it stopped at — that step is
    done again, and anything in it that needs your yes asks again. None when
    there's no plan to pick up."""
    global _resumable
    ended = outcome if outcome is not None else {}

    def end(how: str, reply: str, error: str = "") -> str:
        ended.update(status=how, error=error)
        return reply

    if resumable() is None:
        return None
    if not _lock.acquire(blocking=False):
        return end("failed", "I'm already working through a plan. Say stop to cancel it.",
                   "Another plan is still running.")
    _cancel.clear()
    try:
        plan, _resumable = _resumable, None
        say(f"Picking up “{plan['command']}” at step {plan['at']} of {len(plan['steps'])}.")
        return _work(plan["command"], plan["understood"], plan["steps"], plan["at"], brain, say, status, end)
    finally:
        _lock.release()


def _work(command, understood, steps, start, brain, say, status, end) -> str:
    """Steps `start` onward: execute, observe, verify, recover. Earlier
    steps (when resuming) are shown as done."""
    global _current, _resumable

    def stop_here(at: int, how: str, reply: str, error: str = "") -> str:
        global _resumable
        _resumable = {"command": command, "understood": understood, "steps": steps, "at": at,
                      "when": time.monotonic()}
        return end(how, reply, error)

    count = len(steps)
    try:
        _current = {"goal": command, "steps": [s["do"] for s in steps], "at": 0, "done": []}
        tasks.plan([s["do"] for s in steps])
        for n in range(1, start):
            tasks.plan_step(n, "done")
        if start == 1:
            if understood:
                say(f"Goal: {understood}")
            say(f"Plan: {count} steps")
            for i, step in enumerate(steps, 1):
                say(f"   {i}. {step['do']}")

        plan_text = "\n".join(f"{i}. {s['do']}" for i, s in enumerate(steps, 1))
        results: list[str] = []
        checked: list[bool | None] = []
        everything: list[dict] = []

        for i, step in enumerate(steps, 1):
            if i < start:
                continue
            if _cancel.is_set() or tasks.stop_requested():
                _current["at"] = 0
                return stop_here(i, "stopped", f"Stopped after step {i - 1} of {count}.")

            _current["at"] = i
            tasks.plan_step(i, "running")
            status("executing")
            say(f"[{i}/{count}] {step['do']}")

            why = ""
            for attempt in range(RECOVERIES + 1):
                if attempt:
                    if _cancel.is_set() or tasks.stop_requested():
                        _current["at"] = 0
                        tasks.plan_step(i, "stopped")
                        return stop_here(i, "stopped", f"Stopped during step {i} of {count}.")
                    say(f"      didn't work: {why} Trying once more.")
                    prompt = RECOVER.format(n=i, goal=command, step=step["do"], why=why)
                else:
                    prompt = STEP.format(goal=command, plan=plan_text, n=i,
                                         check=f"It worked if: {step['check']}\n" if step["check"] else "")
                before, answered = _entries(brain), permissions.last_answer()
                try:
                    reply = brain.ask(prompt)
                except tasks.Stopped:
                    # Stopped partway through this step; it doesn't count as done.
                    _current["at"] = 0
                    tasks.plan_step(i, "stopped")
                    return stop_here(i, "stopped", f"Stopped during step {i} of {count}.")
                except Exception as e:  # noqa: BLE001
                    log(f"plan step {i} crashed: {e}")
                    reply = f"FAILED: {e}"

                observed = _observe(brain, before)
                everything += observed
                if _declined(answered):
                    # Your no is an answer, not a failure to work around.
                    _current["at"] = 0
                    tasks.plan_step(i, "stopped")
                    return stop_here(i, "stopped", f"You said no during step {i} of {count}, so I stopped there. "
                                                   f"Nothing after it ran.")
                clean = re.sub(r"^FAILED:\s*", "", reply).strip()
                if FAILED.match(reply):
                    verified, evidence = False, clean
                else:
                    verified, evidence = _verify(step, reply, observed)
                if verified is not False:
                    break
                why = evidence

            _current["done"].append({"ok": verified is not False, "text": step["do"]})
            if verified is False:
                tasks.plan_step(i, "failed")
                say(f"      could not: {evidence}")
                return stop_here(i, "failed",
                                 f"I got to step {i} of {count} and stopped: {evidence} "
                                 f"Tell me how to get past it and I'll carry on.",
                                 f"Step {i} of {count}: {evidence}")

            tasks.plan_step(i, "done")
            results.append(clean)
            checked.append(verified)
            say(f"      {clean}")
            if verified:
                say(f"      checked: {evidence}")
            elif evidence:
                say(f"      not checked: {evidence}")

        _resumable = None
        done_now = len(results)
        finish = f"Done, all {count} steps." if start == 1 else f"Done: steps {start} to {count}."
        planned_checks = any(s["check"] or s["files"] for s in steps[start - 1:])
        if planned_checks:
            unchecked = [n for n, v in enumerate(checked, start) if v is None]
            head = f"all {count} steps" if start == 1 else f"steps {start} to {count}"
            finish = (f"Done, {head}, each checked." if not unchecked else
                      f"Done, {head}; step{'s' if len(unchecked) > 1 else ''} "
                      f"{', '.join(map(str, unchecked))} couldn't be checked.")
        if GITHUB.search(command):
            final = _github_check(everything)
            if final:
                say(f"      {final}")
                return end("failed", f"I did all {count} steps, but it isn't ready yet. {final}", final)
        return end("done", f"{finish} {results[-1]}" if done_now else finish)
    finally:
        _current = None
