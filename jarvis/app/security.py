"""The Security Center (Chapter 37): what LITTLE may do, and what it did.

Read-only, from what's actually in effect: which keys are set (never their
values), which outside services it talks to and for what, every tool's
permission level, what's blocked, the answers you gave to its questions,
and the tool runs that failed or were blocked. Shown in the System
section; "security report" says it in words.
"""
from __future__ import annotations

import datetime
import os

from ..tools import permissions

KEYS = (("Gemini API key", "GEMINI_API_KEY"), ("Adzuna app id", "ADZUNA_APP_ID"),
        ("Adzuna app key", "ADZUNA_APP_KEY"), ("The Muse key", "MUSE_API_KEY"))


def _set(key: str) -> bool:
    return bool((os.getenv(key) or "").strip())


def keys() -> list[dict]:
    return [{"name": name, "key": key, "state": "set" if _set(key) else "missing"} for name, key in KEYS]


def services() -> list[dict]:
    """The outside services LITTLE uses, what for, and whether it can."""
    from ..voice import local_wake
    from . import config
    wake = local_wake.current or local_wake.LocalWake(recognizer=None)
    heard = ("only phrases with its name (checked here first)" if wake.active()
             else "every phrase the microphone hears while listening")
    return [
        {"name": "Google Gemini", "for": "answers, plans and tools that need the model",
         "state": "key set" if _set("GEMINI_API_KEY") else "no key — the model can't be used"},
        {"name": "Google speech", "for": "turning speech into text", "state": heard},
        {"name": "Microsoft Edge voice", "for": "the natural voice",
         "state": "on" if config.USE_NEURAL else "off — the Windows voice speaks"},
        {"name": "Adzuna", "for": "job search",
         "state": "keyed" if _set("ADZUNA_APP_ID") and _set("ADZUNA_APP_KEY") else "not set — skipped"},
        {"name": "Job boards and web pages", "for": "reading public listings and pages you ask about",
         "state": "only when asked; never submits an application"},
    ]


def levels() -> dict:
    """{level: [tool names]} for every level, blocked included."""
    from ..tools.registry import FUNCTIONS
    out = {lv: [] for lv in permissions.ORDER}
    for name in sorted(FUNCTIONS):
        out[permissions.level(name)].append(name)
    return out


def snapshot() -> dict:
    return {
        "keys": keys(),
        "services": services(),
        "levels": {lv: len(names) for lv, names in levels().items()},
        "blocked": levels()[permissions.BLOCKED],
        "answers": [{"at": a["at"], "tool": a["tool"], "action": a["action"], "approved": a["approved"]}
                    for a in reversed(permissions.answers()[-30:])],
        "events": permissions.events(30),
    }


def _when(stamp: float) -> str:
    return datetime.datetime.fromtimestamp(stamp).strftime("%H:%M")


def report() -> str:
    """The command: the Security Center in words."""
    snap = snapshot()
    counts = ", ".join(f"{n} {lv.lower().replace('_', ' ')}" for lv, n in snap["levels"].items() if n)
    lines = [f"Tools by level: {counts}.",
             "Keys: " + ", ".join(f"{k['name']} {k['state']}" for k in snap["keys"]) + " (values are never shown)."]
    if snap["blocked"]:
        lines.append("Blocked: " + ", ".join(snap["blocked"]) + ".")
    asked = snap["answers"]
    if asked:
        said_no = sum(not a["approved"] for a in asked)
        lines.append(f"Questions this session: {len(asked)} ({len(asked) - said_no} yes, {said_no} no).")
    trouble = snap["events"]
    if trouble:
        lines.append("Failed or blocked lately: " + "; ".join(
            f"{_when(e['at'])} {e['tool']} {e['kind']}" for e in trouble[:5]) + ".")
    else:
        lines.append("No tool has failed or been blocked this session.")
    return "\n".join(lines)
