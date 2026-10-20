"""Hearing its own name.

Two rules decide what counts.

The name has to open the phrase. "Little" is an everyday word — "a little
bit", "wait a little", "so little time" — and an assistant that wakes on
any sentence containing it would be answering the room all day. Someone
talking *to* it says its name first, perhaps after a "hey" or an "ok", so
that is the only place it is listened for.

Close-enough spellings count, but only where they help. Speech recognition
mangles a name it doesn't know ("Jarvis" comes back as "javis"), so the old
name keeps a forgiving match. It spells an everyday word like "little"
correctly every time, so the new name needs a much closer match — otherwise
"title of the song" would wake it.
"""
from __future__ import annotations

import difflib
import os
import re

from ..app.config import ASSISTANT_CALL, WAKE_WORDS

# Longest first, so "hey little" is tried before "little".
WAKE_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in
                                        sorted(WAKE_WORDS, key=len, reverse=True)) + r")\b")
WAKE_STEMS = {w.split()[-1] for w in WAKE_WORDS}
FUZZY = float(os.getenv("JARVIS_WAKE_FUZZY", "0.72"))

# How close a misheard word must be to its own name. "title" scores 0.73
# against "little" and "litter" 0.83; "littl" scores 0.91.
OWN_NAME_FUZZY = 0.85

# What people say before the name when they address someone. "a" is not
# here on purpose: "a little bit" is the phrase this list exists to ignore.
LEAD_INS = {"hey", "hi", "hello", "ok", "okay", "oh", "um", "uh", "umm", "hmm",
            "so", "yo", "and", "please"}

# Idioms that open with its name but aren't said to it.
NOT_ADDRESSED = re.compile(r"^\W*by\s+little\b", re.I)


def _cutoff(stem: str) -> float:
    return max(FUZZY, OWN_NAME_FUZZY) if stem == ASSISTANT_CALL.lower() else FUZZY


def _only_lead_ins(words: list[str]) -> bool:
    return all(w.strip(",.!?") in LEAD_INS for w in words)


def wake_position(heard: str) -> int | None:
    """Where the wake word ends in the heard phrase, or None if it wasn't
    said to the assistant."""
    text = (heard or "").lower()

    for match in WAKE_RE.finditer(text):
        if NOT_ADDRESSED.match(text[match.end():]):
            return None                         # "little by little …"
        before = text[:match.start()].split()
        if before and before[-1] == "so" and " " not in match.group(0):
            return None                         # "so little time": the adverb, not a lead-in (Chapter 45)
        if _only_lead_ins(text[:match.start()].split()):
            return match.end()
        break                                   # named mid-sentence: not an address

    # Nothing exact. Try the first word that isn't a lead-in, and only that
    # one, against each name with its own tolerance.
    words = text.split()
    for i, word in enumerate(words[:4]):
        bare = word.strip(",.!?")
        if bare in LEAD_INS:
            continue
        for stem in WAKE_STEMS:
            if difflib.SequenceMatcher(None, bare, stem).ratio() >= _cutoff(stem):
                return len(" ".join(words[:i + 1]))
        return None
    return None
