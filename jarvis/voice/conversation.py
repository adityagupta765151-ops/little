"""Talking with LITTLE, not just at it (Chapter 35).

- **Follow-ups.** After answering something you said, LITTLE keeps
  listening for a few seconds without needing its name, so "and tomorrow?"
  or "open the second one" can follow. The window closes on silence, after
  a few follow-ups in a row (so a TV can't keep it open), or when you say
  never mind. `JARVIS_FOLLOW_UP` sets the seconds; 0 turns it off.
- **Context.** The model keeps the conversation itself. For what's answered
  on this computer, the last thing opened is remembered for a couple of
  minutes, so "close it" knows what "it" is. Nothing else is guessed: with
  nothing recent, "it" is left for the model to ask about.
- **The four words.** STOP and CANCEL stop what's running and the voice;
  NEVER MIND does that and closes the follow-up window, and isn't sent to
  the model; CONTINUE picks a stopped plan up where it stopped (it asks
  again at anything that needs your yes), or, with no plan to resume, goes
  to the model as before.
"""
from __future__ import annotations

import os
import re
import threading
import time


def _seconds(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw not in (None, "") else default
    except ValueError:
        value = default
    return max(0.0, min(30.0, value))


FOLLOW_UP = _seconds(os.getenv("JARVIS_FOLLOW_UP"), 6.0)   # seconds; 0 turns it off
MAX_FOLLOW_UPS = 3        # in a row without the name, then the name is needed again
SUBJECT_FOR = 120.0       # seconds "it" keeps meaning the last thing opened

NEVER_MIND = re.compile(r"(?:never ?mind|nevermind|forget it|leave it|koi baat nahi|rehne do|chhodo)[.!]?", re.I)
CONTINUE = re.compile(r"(?:continue|carry on|go on|keep going|resume|go ahead and continue|aage badho|jaari rakho)"
                      r"(?: (?:the|my) (?:plan|task))?[.!]?", re.I)
STOP_WORDS = ("stop", "cancel", "ruko", "chup")

OPENED = re.compile(r"(?:open|launch|start|khol(?:o|do)?)\s+(?:the\s+)?(.+?)(?:\s+app)?[.!]?$", re.I)
PRONOUN = re.compile(r"^(close|quit|open|minimi[sz]e|maximi[sz]e|switch to)\s+(it|that|this|this one|that one)[.!]?$",
                     re.I)

_lock = threading.Lock()
_subject: dict = {}


def never_mind(text: str) -> bool:
    return bool(NEVER_MIND.fullmatch((text or "").strip()))


def wants_to_continue(text: str) -> bool:
    return bool(CONTINUE.fullmatch((text or "").strip()))


def note(command: str, reply: str, route: str) -> None:
    """After a command: remember what was opened on this computer, so
    "close it" can find it."""
    match = OPENED.fullmatch((command or "").strip())
    if route == "local" and match and not str(reply or "").lower().startswith(("i couldn't", "i can't", "that isn't")):
        with _lock:
            _subject.update(name=match.group(1).strip(), at=time.monotonic())


def resolve(command: str) -> str:
    """"close it" → "close chrome" when Chrome was opened in the last couple
    of minutes; anything else unchanged."""
    match = PRONOUN.fullmatch((command or "").strip())
    if not match:
        return command
    with _lock:
        name, at = _subject.get("name"), _subject.get("at", 0.0)
    if not name or time.monotonic() - at > SUBJECT_FOR:
        return command
    return f"{match.group(1)} {name}"


def forget() -> None:
    with _lock:
        _subject.clear()
