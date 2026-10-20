"""Failure recovery (Chapter 42): try again where it's safe, say so always.

Three places things break, and what LITTLE does about each:

- **The model.** The provider already retries a busy model with doubling
  waits and falls back to lighter ones. Now a switch to a lighter model is
  recorded, not just logged; with no route to the internet it stops trying
  for a short while (so every command doesn't wait out the same retries),
  and a command that needed the model says what still works here.
- **The browser.** If it was closed or crashed under a step, it's started
  again and the step retried once — and the reply says so.
- **Tools.** A tool that only reads is tried once more after a passing
  failure (a timeout, a dropped connection). Anything that changes things
  is never retried by itself: a second try could do it twice.

Nothing is hidden: every recovery and every failure it couldn't get past is
recorded (the Security Center's "Failed or blocked" list, the dashboard,
"what went wrong lately"), and the reply says what happened.
"""
from __future__ import annotations

import re
import time

OFFLINE_HOLD = 20.0          # seconds to stop trying the model after the network was unreachable

# Errors worth one more try for a tool that only reads.
TRANSIENT = (TimeoutError, ConnectionError)
TRANSIENT_WORDS = re.compile(r"timed? ?out|temporar|connection (?:reset|aborted|refused)|try again|busy|"
                             r"remote end closed|EOF occurred", re.I)

# A browser that's gone from under a step.
BROWSER_GONE = re.compile(r"has been closed|browser has disconnected|target closed|connection closed|"
                          r"TargetClosed|browser.*crash", re.I)

STILL_WORKS = ("What still works on this computer: the time and date, reminders, what I remember, your files, "
               "search in your documents, and the jobs and resume already stored.")
OFFLINE_WORDS = re.compile(r"can't reach the internet|servers are busy|rate limit|unreachable", re.I)


def note(part: str, what: str, recovered: bool) -> None:
    """Record a recovery, or a failure that couldn't be got past."""
    from ..tools import permissions
    permissions.note_event("recovered" if recovered else "failed", part, what)


def transient(error: BaseException) -> bool:
    return isinstance(error, TRANSIENT) or bool(TRANSIENT_WORDS.search(f"{type(error).__name__} {error}"))


def browser_gone(error: BaseException) -> bool:
    return bool(BROWSER_GONE.search(f"{type(error).__name__} {error}"))


def with_offline_help(message: str) -> str:
    """A model failure, followed by what can still be done without it — only
    when the failure is the model being out of reach, not, say, a bad key."""
    if OFFLINE_WORDS.search(message or ""):
        return f"{message} {STILL_WORKS}"
    return message


# ------------------------------------------------------------ the model

_offline_since: float | None = None


def offline_hold() -> str | None:
    """The message to answer with straight away, while the network was
    unreachable a moment ago; None to try."""
    if _offline_since is not None and time.monotonic() - _offline_since < OFFLINE_HOLD:
        return "I can't reach the internet right now."
    return None


def went_offline() -> None:
    global _offline_since
    _offline_since = time.monotonic()
    note("model", "no route to the internet; not trying again for a few seconds", False)


def back_online() -> None:
    global _offline_since
    _offline_since = None


def report() -> str:
    """ "What went wrong lately?" — failures and recoveries, newest first."""
    from ..tools import permissions
    import datetime
    found = [e for e in permissions.events(200) if e["kind"] in ("failed", "recovered", "blocked", "slow")][:8]
    if not found:
        return "Nothing has gone wrong this session."
    words = {"failed": "failed", "recovered": "recovered", "blocked": "blocked", "slow": "was slow"}
    return "\n".join(f"{datetime.datetime.fromtimestamp(e['at']):%H:%M} {e['tool']} {words[e['kind']]}"
                     + (f": {e['detail']}" if e["detail"] else "") for e in found)
