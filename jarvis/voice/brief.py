"""What gets said out loud, as opposed to what gets shown.

A reply can be long — ten job listings, a health report, a score broken
into nine parts — and the panel is the right place for all of it. Read
aloud, the same text is a minute of monologue nobody listens to. So the
screen gets everything and the voice gets one or two short sentences,
with a pointer to the rest when there is a rest.
"""
from __future__ import annotations

import re

MAX_SPOKEN = 130          # characters; about two short sentences
ON_SCREEN = "The rest is on screen."

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _clean(line: str) -> str:
    line = re.sub(r"https?://\S+", "", line)
    line = re.sub(r"[*_#`>|✓✗△⚠·•]", "", line)
    return re.sub(r"\s+", " ", line).strip(" -—:")


def _special(text: str, lines: list[str]) -> str | None:
    """Long reports with a shape of their own, summed up the way a person
    would sum them up rather than by reading their first line."""
    first = lines[0].strip()

    if first.startswith("SYSTEM HEALTH"):
        tail = lines[-1].strip()
        if tail.startswith("Everything checks out"):
            return "System check done. Everything checks out."
        return f"System check done. {tail}"

    if first.startswith("MATCH ANALYSIS"):
        score = re.search(r"—\s*(\d+)/100", text)
        if score:
            return f"It scores {score.group(1)} out of 100. The breakdown is on screen."
        return "The breakdown is on screen."

    if first.startswith("Job #"):
        count = len(re.findall(r"^Job #\d+", text, re.M))
        noun = "match" if count == 1 else "matches"
        return f"Here {'is' if count == 1 else 'are'} your top {count} {noun}. They're on screen."

    return None


def for_speech(text: str) -> str:
    """One or two short sentences to say aloud; everything if it's already short."""
    text = (text or "").strip()
    if not text:
        return ""

    lines = [line for line in text.splitlines() if line.strip()]
    special = _special(text, lines)
    if special:
        return special

    first = _clean(lines[0])
    sentences = [s for s in _SENTENCE.split(first) if s]
    spoken = " ".join(sentences[:2])
    if len(spoken) > MAX_SPOKEN and len(sentences) > 1:
        spoken = sentences[0]
    if len(spoken) > MAX_SPOKEN:
        # Cut at the last clause break that fits, so it still sounds like a
        # sentence; only fall back to a word boundary when there is none.
        head = spoken[:MAX_SPOKEN]
        breaks = [m.start() for m in re.finditer(r",\s|;\s|\s(?:and|then|but|which)\s", head)]
        stop = breaks[-1] if breaks and breaks[-1] > 40 else head.rfind(" ")
        spoken = head[:stop].rstrip(",;: ") + "."

    left_out = len(lines) > 1 or len(spoken) + 20 < len(first)
    if left_out and spoken:
        return f"{spoken} {ON_SCREEN}"
    return spoken or _clean(text)[:MAX_SPOKEN]
