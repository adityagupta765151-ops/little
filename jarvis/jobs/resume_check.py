"""Checking a resume for what forms and recruiters look for.

On this computer: nothing is sent to the model. Each check reads the saved
profile — and the stored jobs, for what they ask — and comes back ok, as
something to look at (with why it matters and what to do), or as a note.

It never suggests putting anything on a resume that isn't true. A project
with no numbers gets "if you have real ones", not a number to write.
"""
from __future__ import annotations

import re

from . import grades, store
from . import resume as cv

OK, LOOK, NOTE = "ok", "warn", "note"
MARK = {OK: "✓", LOOK: "!", NOTE: "·"}
SHORT_CHARS = 1300          # about 200 words
LONG_CHARS = 9000           # about 1,400 words — three pages or so
CHARS_PER_WORD = 6.5


def _check(id_: str, title: str, state: str, detail: str, why: str = "", fix: str = "") -> dict:
    return {"id": id_, "title": title, "state": state, "detail": detail, "why": why, "fix": fix}


def _contact(person: dict) -> dict:
    missing = [label for key, label in (("name", "name"), ("email", "email"), ("phone", "phone"))
               if not str(person.get(key) or "").strip()]
    wrong = []
    email = str(person.get("email") or "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", email):
        wrong.append(f"the email ({email}) doesn't look like an address")
    phone = str(person.get("phone") or "")
    if phone.strip() and not 7 <= len(re.sub(r"\D", "", phone)) <= 15:
        wrong.append("the phone number has too few or too many digits")
    if not missing and not wrong:
        return _check("contact", "Contact details", OK, "Name, email and phone are all there.")
    detail = "; ".join(([f"Missing: {', '.join(missing)}"] if missing else []) + wrong) + "."
    first = (missing or ["phone"])[0]
    return _check("contact", "Contact details", LOOK, detail[0].upper() + detail[1:],
                  "Recruiters reach you with these, and Prepare application fills them in from here.",
                  f"Put it on the resume and scan again. To correct the profile now, say: set my {first} to …")


def _links(person: dict) -> dict:
    links = [str(v) for v in person.get("links", [])]
    has = [name for name, domain in (("GitHub", "github.com"), ("LinkedIn", "linkedin.com"))
           if any(domain in link.lower() for link in links)]
    if len(has) == 2:
        return _check("links", "GitHub and LinkedIn", OK, "Both are on it.")
    if has:
        other = "LinkedIn" if has[0] == "GitHub" else "GitHub"
        return _check("links", "GitHub and LinkedIn", NOTE, f"{has[0]} is on it; {other} isn't.",
                      "Many tech forms ask for both.",
                      f"If you have a {other} profile, add it. For now: set my {other.lower()} to …")
    return _check("links", "GitHub and LinkedIn", LOOK, "Neither is on it.",
                  "Tech recruiters look at GitHub for freshers, and many forms ask for LinkedIn.",
                  "Add them to the resume. For now: set my github to github.com/yourname")


def _degree(person: dict) -> dict:
    missing = [label for key, label in (("degree", "degree"), ("graduation_year", "graduation year"))
               if not str(person.get(key) or "").strip()]
    if not missing:
        return _check("degree", "Degree and batch", OK,
                      f"{person['degree']}, graduating {person['graduation_year']}.")
    return _check("degree", "Degree and batch", LOOK, f"Missing: {' and '.join(missing)}.",
                  "Fresher postings filter by degree and batch year.",
                  f"If the resume says it, scan again. Otherwise: set my {missing[0]} to …")


def _score(person: dict, jobs: list[dict]) -> dict:
    mine = str(person.get("degree_score") or "").strip()
    concerns = [c for job in jobs for c in (job.get("score_breakdown") or {}).get("concerns", [])
                if c.startswith("Asks for ")]
    below = sum(1 for job in jobs if any(c.startswith("Asks for ") and "your resume says" in c
                                         for c in (job.get("score_breakdown") or {}).get("concerns", [])))
    if mine and grades.grade(mine):
        detail = f"{mine}."
        if below:
            detail += (f" {below} of your stored jobs ask{'s' if below == 1 else ''} for more than "
                       f"your resume states — their cards say which.")
        return _check("score", "CGPA or %", OK, detail)
    asking = sum(1 for job in jobs if any(c.startswith("Asks for ")
                                          for c in (job.get("score_breakdown") or {}).get("concerns", [])))
    return _check("score", "CGPA or %", LOOK,
                  "Not on your profile." + (f" {asking} of your stored jobs state a bar." if concerns else ""),
                  "Many campus and fresher postings set a CGPA or % bar. Without yours, I can't "
                  "tell you which ones you clear, and recruiters may ask.",
                  "If it's on your resume, scan again. If not: set my cgpa to 7.8/10")


def _projects(person: dict) -> dict:
    projects = [str(p) for p in person.get("projects", []) if str(p).strip()]
    if len(projects) < 2:
        return _check("projects", "Projects", LOOK,
                      "No projects listed." if not projects else "Only one project listed.",
                      "For a fresher, projects are the main evidence of what you can do.",
                      "Add the projects you've actually built, one line each, with what you built them in.")
    numbered = [p for p in projects
                if [n for n in re.findall(r"\d+(?:\.\d+)?", p) if not re.fullmatch(r"(19|20)\d\d", n)]]
    if not numbered:
        return _check("projects", "Projects", LOOK,
                      f"{len(projects)} projects, and none of their lines has a number.",
                      "A real result — users, requests a second, time saved, accuracy — shows scale.",
                      "If you have real numbers, add them. Never estimate ones you don't have.")
    return _check("projects", "Projects", OK,
                  f"{len(projects)} projects; {len(numbered)} with a number in them.")


def _norm(skill: str) -> str:
    s = skill.lower().strip()
    return re.sub(r"(\.js|js)$", "", s) if len(s) > 4 else s


def _evidence(person: dict) -> dict:
    skills = [str(s) for s in person.get("skills", []) + person.get("languages", [])
              + person.get("frameworks", []) if str(s).strip()]
    unique: list[str] = []
    for s in skills:
        if s.lower() not in (u.lower() for u in unique):
            unique.append(s)
    shown = " ".join(str(v) for key in ("projects", "experience", "internships")
                     for v in person.get(key, [])).lower()
    unused = [s for s in unique if _norm(s) not in shown]
    if len(unique) < 3 or not shown.strip():
        return _check("evidence", "Skills shown in your work", NOTE,
                      "Not enough projects or experience to check against.")
    if len(unused) >= 3:
        listed = ", ".join(unused[:6]) + (f" and {len(unused) - 6} more" if len(unused) > 6 else "")
        return _check("evidence", "Skills shown in your work", LOOK,
                      f"Listed, but no project or job mentions them: {listed}.",
                      "Interviewers ask where you used each skill; one no project shows is hard to talk about.",
                      "Name them in the project where you used them — or drop ones you haven't used.")
    return _check("evidence", "Skills shown in your work", OK,
                  f"{len(unique) - len(unused)} of {len(unique)} skills appear in a project or job.")


def _length(profile: dict) -> dict:
    chars = int(profile.get("raw_text_chars") or 0)
    if not chars:
        return _check("length", "Length", NOTE, "Not measured for this profile.",
                      "", "Scan the resume again to measure it.")
    words = round(chars / CHARS_PER_WORD / 10) * 10
    if chars < SHORT_CHARS:
        return _check("length", "Length", LOOK, f"About {words} words — short.",
                      "A thin resume gives a recruiter little to go on.",
                      "Add what's missing above: projects with what you built, skills shown in them.")
    if chars > LONG_CHARS:
        return _check("length", "Length", LOOK, f"About {words} words — long for a fresher.",
                      "Recruiters skim; for a fresher, one page is usual.",
                      "Keep the strongest projects and cut repetition.")
    return _check("length", "Length", OK, f"About {words} words.")


def _achievements(person: dict) -> dict:
    items = [a for a in person.get("achievements", []) if str(a).strip()]
    if items:
        return _check("achievements", "Achievements", OK, f"{len(items)} listed.")
    return _check("achievements", "Achievements", NOTE, "None listed.",
                  "Hackathons, ranks, scholarships and contest ratings help a fresher stand out.",
                  "If you have any, add them. Nothing to add is fine.")


def _gaps() -> dict | None:
    try:
        gaps = store.missing_skill_counts(3)
    except Exception:  # noqa: BLE001
        return None
    if not gaps:
        return None
    listed = ", ".join(f"{skill} ({count} job{'s' if count != 1 else ''})" for skill, count in gaps)
    return _check("gaps", "What your jobs ask for", NOTE, f"Often asked for, not on your resume: {listed}.",
                  "From the jobs you've found, not a general list.",
                  "Learn or show the ones that fit what you want. Don't list what you haven't used.")


def _edited(profile: dict) -> dict | None:
    changed = cv.edited(profile)
    if not changed:
        return None
    return _check("edited", "Corrected by you", NOTE,
                  "You corrected: " + ", ".join(cv.CHANGEABLE[f] for f in changed) + ".",
                  "A new resume scan replaces these with what that resume says.",
                  "Put the same corrections in the resume file, so the next scan keeps them.")


def run(profile: dict | None = None) -> list[dict]:
    """Every check, in order. Reads only; changes nothing."""
    profile = profile if profile is not None else cv.load_profile()
    person = profile.get("candidate", {})
    try:
        jobs = store.top_jobs(limit=500)
    except Exception:  # noqa: BLE001
        jobs = []
    checks = [_contact(person), _links(person), _degree(person), _score(person, jobs),
              _projects(person), _evidence(person), _length(profile), _achievements(person),
              _gaps(), _edited(profile)]
    return [c for c in checks if c]


def report(checks: list[dict], source: str = "") -> str:
    looks = sum(1 for c in checks if c["state"] == LOOK)
    lines = ["RESUME CHECK — on this computer; nothing is sent anywhere."]
    if source:
        lines.append(f"Resume: {source}")
    lines.append("")
    for c in checks:
        lines.append(f"{MARK[c['state']]} {c['title']} — {c['detail']}")
        if c["state"] != OK:
            if c["why"]:
                lines.append(f"    Why: {c['why']}")
            if c["fix"]:
                lines.append(f"    Fix: {c['fix']}")
    lines += ["", "Nothing to look at." if not looks else
              f"{looks} thing{'s' if looks != 1 else ''} to look at."]
    return "\n".join(lines)


def check_resume() -> str:
    """The command and the tool: the whole check, as text."""
    profile = cv.load_profile()
    if not cv.is_ready(profile):
        return "No resume has been scanned yet, so there's nothing to check. " + cv.scan_hint()
    return report(run(profile), str(profile.get("source_file") or ""))
