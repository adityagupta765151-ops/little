"""Demo mode (Chapter 47): about fifty seconds of LITTLE, the same every time.

"Start the demo" runs a fixed script through the real assistant, so every
step is a real command, answered the normal way and shown on Home, in Chat
and in the audit log. What it's built on keeps it reliable and private:

- **Nothing personal.** No step reads your memory, contacts, resume, jobs
  or files, so nothing of yours can appear on screen. The steps: the time,
  the time in Hinglish, which tools ask first, one risky action, the audit
  log of it, and the measured timings.
- **Nothing needs the internet or the model.** Every command is answered on
  this computer, so the demo works offline and without a key.
- **Nothing is changed.** Nothing opens, nothing is sent, and the demo's
  turns aren't added to your conversation history. The audit log does keep
  them — it records everything that ran, and the demo is no exception.
- **The risky step is refused.** It asks to run a command, through the real
  confirmation gate. The demo answers No for you and says so; it can never
  answer Yes, and the command never runs.
- **Timed by the clock, not by speech.** Each step has a slot; the next one
  starts when the slot ends, so the whole demo takes the same time whether
  the voice is on, off, fast or slow. Only the short narration is spoken;
  the replies are on screen.

"Stop" (or Esc, or the Stop button) ends it before the next step.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .config import log

PACE = 1.0          # seconds per slot-second; the tests set 0


@dataclass(frozen=True)
class Step:
    slot: float        # seconds this step has, narration included
    narration: str     # spoken, and shown
    command: str = ""  # typed to the assistant, "" for none


RISKY = "run the command: echo hello"     # the one step that asks first; refused

STEPS = (
    Step(7, "Hi, I'm LITTLE. I try this computer first, and I ask before anything risky."),
    Step(6, "Asking the time never leaves this computer.", "what's the time"),
    Step(6, "Hinglish works too.", "time kya hai"),
    Step(7, "These tools always ask you first.", "which tools require confirmation"),
    Step(8, "Now something risky: running a command. In the demo, the answer is no.", RISKY),
    Step(7, "Every step is kept in an audit log, including that no.", "what did you do for my last task"),
    Step(6, "And everything is timed as it happens.", "how fast are you"),
    Step(6, "That's LITTLE. Nothing of yours was read, sent, opened or changed."),
)
SECONDS = sum(step.slot for step in STEPS)

STARTING = (f"Starting the demo: about {SECONDS:.0f} seconds, {len(STEPS)} steps. It reads nothing of yours "
            f"and changes nothing. Say stop to end it.")
ALREADY = "The demo is already running. Say stop to end it."

_lock = threading.Lock()
_running = threading.Event()
_stop = threading.Event()
_quiet = threading.local()


def running() -> bool:
    return _running.is_set()


def quiet_here() -> bool:
    """True on the demo's own thread while one of its commands runs: the
    reply is shown but not spoken, and not added to your conversation log."""
    return getattr(_quiet, "on", False)


def cancel() -> None:
    """Stop at the next step (the assistant's interrupt calls this)."""
    if _running.is_set():
        _stop.set()


def _answer_no(_message) -> bool:
    return False


def _risky(assistant) -> None:
    """Ask to run a command through the real gate, and answer no."""
    from ..tools import permissions, registry
    from . import tasks
    from .assistant import REPLY
    assistant.log(f"You: {RISKY}")
    task = tasks.start(RISKY)
    status, error = tasks.DONE, ""
    real = permissions.confirm_fn
    try:
        tasks.route("local")
        tasks.path("normal")
        permissions.set_confirm(_answer_no)      # recorded as a no, like any answer
        said = registry.execute_tool("run_command", {"command": "echo hello"})
        permissions.confirm_fn = real
        tasks.reply(said)
        assistant.log(f"{REPLY}{said}")
    except Exception as e:
        status, error = tasks.FAILED, type(e).__name__
        raise
    finally:
        permissions.confirm_fn = real            # whatever was installed, back
        tasks.finish(status, error, task_id=task)


def _run_step(assistant, step: Step) -> None:
    assistant.log(f"Demo · {step.narration}")
    assistant.say(step.narration)
    if not step.command:
        return
    _quiet.on = True
    try:
        if step.command == RISKY:
            _risky(assistant)
        else:
            assistant.handle(step.command)
    finally:
        _quiet.on = False


def _claim() -> bool:
    """One demo at a time: True if this caller may run it."""
    with _lock:
        if _running.is_set():
            return False
        _running.set()
        _stop.clear()
        return True


def run(assistant, clock=time.monotonic) -> dict:
    """The whole demo, on this thread. Returns what happened."""
    if not _claim():
        return {"ran": 0, "seconds": 0.0, "stopped": False, "already": True}
    return _run(assistant, clock)


def _run(assistant, clock) -> dict:
    started = clock()
    ran, due = 0, 0.0
    try:
        for step in STEPS:
            if _stop.is_set():
                break
            _run_step(assistant, step)
            ran += 1
            due += step.slot * PACE
            left = due - (clock() - started)
            if left > 0 and _stop.wait(left):
                break
    except Exception as e:  # noqa: BLE001
        log(f"demo stopped by an error: {type(e).__name__}: {e}")
        assistant.log(f"The demo stopped at step {ran + 1}: {type(e).__name__}.")
        return {"ran": ran, "seconds": round(clock() - started, 1), "stopped": True, "already": False}
    finally:
        stopped = _stop.is_set()
        _running.clear()
        _stop.clear()
    seconds = round(clock() - started, 1)
    if stopped:
        assistant.log(f"Demo stopped after {ran} of {len(STEPS)} steps.")
    else:
        assistant.log(f"Demo finished in {seconds:.0f} s.")
    return {"ran": ran, "seconds": seconds, "stopped": stopped, "already": False}


def start(assistant, first=None) -> str:
    """The command: start the demo on its own thread and say so. `first`
    is handed what's said before the thread starts, so "Starting the demo"
    comes before the demo's first line, never after it."""
    if not _claim():
        if first:
            first(ALREADY)
        return ALREADY
    if first:
        first(STARTING)
    threading.Thread(target=_run, args=(assistant, time.monotonic), daemon=True, name="little-demo").start()
    return STARTING
