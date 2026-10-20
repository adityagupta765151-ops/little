"""Your projects, as your resume describes them — for the Projects section.

A resume scan keeps each project as one line: "Name - what it is". This
splits that line into a name and a description, and points out what the
line itself says: the skills from your own resume it names, and any web
address in it. Nothing is added. Status, the backend / frontend / database
split and AI parts aren't in a one-line description, so the section says
they aren't there rather than guessing them.
"""
from __future__ import annotations

import re

# "Name - description", with a hyphen, en or em dash, or a colon.
_SPLIT = re.compile(r"\s+[-–—]\s+|:\s+")
_URL = re.compile(r"(?:https?://|www\.|github\.com/|gitlab\.com/)[^\s,;)]+", re.I)

# What a one-line description never says, named so the page can say so.
NOT_IN_A_LINE = ("status", "AI/ML parts", "backend", "frontend", "database")


def _link(found: str) -> str:
    found = found.rstrip(".")
    return found if found.lower().startswith(("http://", "https://")) else "https://" + found


def _named(line: str, known: list[str]) -> list[str]:
    """Skills from your resume that this line names. A short one (C, Go, R)
    must match its exact case, so "go live" isn't Go."""
    out: list[str] = []
    for skill in known:
        flags = 0 if len(skill) <= 2 else re.I
        if re.search(rf"(?<![\w.+#]){re.escape(skill)}(?![\w+#])", line, flags) \
                and skill.lower() not in (s.lower() for s in out):
            out.append(skill)
    return out


def from_profile(profile: dict) -> list[dict]:
    person = profile.get("candidate", {})
    known: list[str] = []
    for key in ("skills", "languages", "frameworks"):
        for skill in person.get(key, []) or []:
            skill = str(skill).strip()
            if skill and skill.lower() not in (k.lower() for k in known):
                known.append(skill)

    projects = []
    for line in person.get("projects", []) or []:
        line = " ".join(str(line).split())
        if not line:
            continue
        parts = _SPLIT.split(line, maxsplit=1)
        name, description = (parts[0], parts[1]) if len(parts) == 2 else (line, "")
        links = [_link(m) for m in _URL.findall(line)]
        projects.append({
            "name": name,
            "description": description,
            "named": _named(line, known),
            "links": list(dict.fromkeys(links)),
        })
    return projects
