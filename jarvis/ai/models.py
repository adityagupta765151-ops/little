"""Which model answers what (Chapter 43).

Three ways an answer can be made, cheapest first:

  local    no model at all — the router's own answers (Chapter 33): the
           time, memory, reminders, jobs already stored, a search of your
           documents. Deterministic, free, instant.
  fast     a light model (JARVIS_MODEL_FAST, default gemini-flash-lite-latest)
           for short jobs that don't need the best judgement: checking a
           plan step against what the tools returned, summarising a page.
  strong   the main model (GEMINI_MODEL) for anything with tools, plans,
           code, answers from your documents, reading a resume or a screen.

A caller says which it needs with `with models.use("fast"):` around the
request; everything else is strong. Each tier keeps the provider's
fallback: when its model is busy or gone it moves to the lighter models
(Chapter 42 records the switch), and the fast tier's last resort is the
strong model, so a job never fails just because the cheap model is down.
Each tier's model calls are timed separately.
"""
from __future__ import annotations

import os
import threading

from ..app import config

TIERS = ("fast", "strong")
FAST = os.getenv("JARVIS_MODEL_FAST", "").strip() or "gemini-flash-lite-latest"

# What each kind of request uses — the table the report reads.
ROUTES = (
    ("the time, memory, reminders, stored jobs, searching your documents", "local"),
    ("checking a plan step against what the tools returned", "fast"),
    ("summarising a web page", "fast"),
    ("anything with tools, plans or code", "strong"),
    ("answers from your documents", "strong"),
    ("reading a resume", "strong"),
    ("looking at the screen", "strong"),
)

_local = threading.local()


def current() -> str:
    """The tier this thread's next model request uses."""
    return getattr(_local, "tier", None) or "strong"


class use:
    """`with models.use("fast"):` — requests inside use this tier; the one
    before is restored after, whatever happens. (A class, not a generator,
    so the self-check that reads every call can follow it.)"""

    def __init__(self, tier: str) -> None:
        if tier not in TIERS:
            raise ValueError(f"not a tier: {tier}")
        self.tier = tier
        self.before = None

    def __enter__(self) -> "use":
        self.before = getattr(_local, "tier", None)
        _local.tier = self.tier
        return self

    def __exit__(self, *_exc) -> bool:
        _local.tier = self.before
        return False


def chain(tier: str) -> list[str]:
    """The models a tier tries, in order: its own (as it last worked), the
    lighter fallbacks, and — for the fast tier — the strong model last."""
    from . import provider
    first = provider._current_fast if tier == "fast" else provider._current_model
    order = [first] + list(provider.FALLBACK_MODELS)
    if tier == "fast":
        order.append(provider._current_model)
    seen: list[str] = []
    for model in order:
        if model and model not in seen:
            seen.append(model)
    return seen


def report() -> str:
    """ "Which model do you use for what?" """
    from . import provider
    names = {"local": "no model — on this computer",
             "fast": f"the fast model ({provider._current_fast})",
             "strong": f"the strong model ({provider._current_model})"}
    lines = [f"{what}: {names[tier]}" for what, tier in ROUTES]
    if provider._current_model != config.MODEL:
        lines.append(f"(The strong model is standing in for {config.MODEL}, which was busy or gone.)")
    if provider._current_fast != FAST:
        lines.append(f"(The fast model is standing in for {FAST}.)")
    return "\n".join(lines)
