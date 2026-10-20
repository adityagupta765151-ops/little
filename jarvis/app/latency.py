"""How long each kind of answer takes (Chapter 33).

Every command goes down one of four paths, tried in this order — the
cheapest that can answer, answers:

  fast     on this computer, from what LITTLE already holds: the clock,
           memory, reminders. No network, no model.
  normal   on this computer's tools, still without the model: a job search,
           a web page, a file, the knowledge base.
  ai       one conversation with the model, which may call tools.
  agent    a plan of several steps, each checked (Chapter 32).

Each command's time, start to reply, is recorded under its path, and so
is the router's own time — the cost of trying locally first even when the
model answers in the end. Measured, in RAM, the last 200 of each; nothing
is estimated and nothing is written to disk.

Chapter 46 adds the other stages a command can pass through: hearing its
name on this computer, speech to text, each tool run and each browser
step (including one given up on — that wait was real). `benchmark` keeps
its own runs on disk; these stay in memory.
"""
from __future__ import annotations

import math
import threading
from collections import deque

PATHS = ("fast", "normal", "ai", "agent")
STAGES = ("router", "model_fast", "model_strong", "wake", "stt", "tool", "browser")
KEPT = 200

_lock = threading.Lock()
_times: dict[str, deque] = {name: deque(maxlen=KEPT) for name in PATHS + STAGES}


def record(name: str, ms: float) -> None:
    """One measurement, in milliseconds, under a path or a stage."""
    if name not in _times or not isinstance(ms, (int, float)) or ms < 0:
        return
    with _lock:
        _times[name].append(float(ms))


def _percentile(ordered: list[float], share: float) -> float:
    """Nearest rank: the smallest value at least `share` of them are at or below."""
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def summary() -> dict[str, dict]:
    """{name: {"count", "p50", "p95", "max", "last"}} for every path and
    stage measured so far; one with no measurements has count 0 and None."""
    with _lock:
        copies = {name: list(times) for name, times in _times.items()}
    out = {}
    for name, times in copies.items():
        if not times:
            out[name] = {"count": 0, "p50": None, "p95": None, "max": None, "last": None}
            continue
        ordered = sorted(times)
        out[name] = {"count": len(times), "p50": round(_percentile(ordered, 0.5)),
                     "p95": round(_percentile(ordered, 0.95)), "max": round(ordered[-1]), "last": round(times[-1])}
    return out


def _ms(value: float) -> str:
    return f"{value} ms" if value < 1000 else f"{value / 1000:.1f} s"


def report() -> str:
    """The command: how long each path has taken, as measured."""
    found = summary()
    lines = []
    names = {"fast": "Fast (on this computer)", "normal": "Normal (local tools)",
             "ai": "AI (the model)", "agent": "Agent (plans)", "router": "Trying locally first",
             "model_fast": "The fast model, per request", "model_strong": "The strong model, per request",
             "wake": "Hearing its name", "stt": "Speech to text", "tool": "A tool run", "browser": "A browser step"}
    for name in PATHS + STAGES:
        s = found[name]
        if s["count"]:
            lines.append(f"{names[name]}: typically {_ms(s['p50'])}, slowest 1 in 20 {_ms(s['p95'])} "
                         f"({s['count']} measured)")
    if not lines:
        return "Nothing measured yet. Ask me a few things and ask again."
    return "\n".join(lines)


def reset() -> None:
    with _lock:
        for times in _times.values():
            times.clear()
