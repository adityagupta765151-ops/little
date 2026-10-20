"""Scoring a job against the resume.

Nine dimensions, each scored out of 100 on its own terms, then combined by
weight. The score is arithmetic rather than a model's opinion, so "why did
you pick this one?" always has a real answer that can be argued with.

Two rules run through the whole file.

A high total must mean *worth applying to*, not *keywords line up*. Knowing
the stack is no help if the posting filters you out before a human reads it,
so a job that cannot be got is capped however well it reads.

And nothing here claims a job is suitable. It reports what matches, what
doesn't, and what to be aware of. The decision is the candidate's.
"""
from __future__ import annotations

import re

# What each dimension is worth. They sum to 100, so a score is a percentage
# of a perfect fit rather than points out of an arbitrary ceiling.
WEIGHTS = {
    "skills": 30,
    "role": 16,
    "seniority": 12,
    "experience": 12,
    "location": 12,
    "employment_type": 6,
    "work_mode": 6,
    "education": 4,
    "projects": 2,
}

ORDER = ("skills", "role", "seniority", "experience", "location",
         "employment_type", "work_mode", "education", "projects")

# However good the skill overlap, a role a fresher cannot realistically get
# should not sit at the top of the list.
REACH_CAP = 45          # senior title, or a years bar far above the candidate
ELIGIBILITY_CAP = 25    # the listing is not open to where they live
OFF_FIELD_CAP = 30      # no technology named and nothing of theirs matched

# Technologies worth spotting in a posting even when the resume lacks them,
# so "skills you are missing" is informative rather than empty.
VOCABULARY = {
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "rust", "php",
    "ruby", "kotlin", "swift", "sql", "html", "css", "bash",
    "react", "next.js", "nextjs", "angular", "vue", "svelte", "node.js", "nodejs",
    "express", "django", "flask", "fastapi", "spring", "spring boot", "laravel",
    "react native", "flutter", "tailwind", "bootstrap", "redux",
    "mongodb", "postgresql", "mysql", "sqlite", "redis", "firebase", "dynamodb",
    "elasticsearch", "kafka", "rabbitmq", "graphql", "rest api", "microservices",
    "aws", "azure", "gcp", "docker", "kubernetes", "jenkins", "terraform", "ansible",
    "ci/cd", "git", "github actions", "linux", "nginx",
    "machine learning", "deep learning", "nlp", "computer vision", "pytorch",
    "tensorflow", "scikit-learn", "pandas", "numpy", "opencv", "langchain", "llm",
    "data analysis", "power bi", "tableau", "excel",
    "agile", "scrum", "jira", "unit testing", "pytest", "jest", "selenium", "playwright",
}

# Skills close enough that having one is worth something when the posting
# asks for the other. Half credit, and said out loud as partial rather than
# quietly counted as a match — the candidate is the one who has to answer
# for it in an interview.
RELATED = {
    "next.js": {"react"}, "nextjs": {"react"}, "react": {"next.js", "vue", "angular"},
    "typescript": {"javascript"}, "javascript": {"typescript"},
    "express": {"node.js"}, "node.js": {"express"},
    "postgresql": {"sql", "mysql"}, "mysql": {"sql", "postgresql"},
    "sql": {"postgresql", "mysql", "sqlite"}, "sqlite": {"sql"},
    "mongodb": {"firebase", "dynamodb"},
    "django": {"python", "flask", "fastapi"}, "flask": {"python", "django", "fastapi"},
    "fastapi": {"python", "flask", "django"},
    "pytorch": {"tensorflow", "machine learning"},
    "tensorflow": {"pytorch", "machine learning"},
    "deep learning": {"machine learning"}, "nlp": {"machine learning"},
    "computer vision": {"machine learning", "opencv"},
    "kubernetes": {"docker"}, "docker": {"kubernetes"},
    "azure": {"aws", "gcp"}, "gcp": {"aws", "azure"}, "aws": {"azure", "gcp"},
    "jest": {"unit testing", "pytest"}, "pytest": {"unit testing", "jest"},
    "selenium": {"playwright"}, "playwright": {"selenium"},
    "tailwind": {"css", "bootstrap"}, "bootstrap": {"css", "tailwind"},
    "vue": {"react", "angular"}, "angular": {"react", "vue"},
}

SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff|head of|manager|architect|"
                    r"director|vp|chief)\b", re.I)
JUNIOR = re.compile(r"\b(intern|internship|trainee|graduate|fresher|entry[- ]level|"
                    r"junior|jr\.?|associate|apprentice|campus)\b", re.I)
REMOTE = re.compile(r"\bremote\b|work from home|\bwfh\b", re.I)
HYBRID = re.compile(r"\bhybrid\b", re.I)

# "Remote" on a job board usually means remote within a named set of
# countries. A listing open only to the USA is not a match for someone in
# Prayagraj, however well the stack lines up.
OPEN_TO_ALL = re.compile(r"\b(worldwide|anywhere|global|any location|"
                         r"no location restriction|international)\b", re.I)

COUNTRY_WORDS = re.compile(
    r"\b(usa|u\.s\.a?|united states|canada|mexico|brazil|argentina|peru|chile|"
    r"colombia|united kingdom|uk|ireland|germany|deutschland|france|spain|italy|"
    r"portugal|netherlands|belgium|poland|sweden|norway|denmark|finland|"
    r"switzerland|austria|czech|romania|ukraine|turkey|israel|"
    r"australia|new zealand|japan|singapore|china|korea|vietnam|philippines|"
    r"indonesia|thailand|malaysia|nigeria|kenya|south africa|egypt|uae|"
    r"emea|latam|apac|europe|european union|eu)\b", re.I)

ANYWHERE_WORDS = ("worldwide", "anywhere", "global", "international")

YEARS = re.compile(r"(\d+)\s*(?:\+|plus)?\s*(?:-|to)?\s*(\d+)?\s*(?:years?|yrs?)\s*"
                   r"(?:of\s+)?(?:relevant\s+)?experience", re.I)

# What a fresher is normally after, used only when nothing was stated.
DEFAULT_TYPES = ("internship", "full-time")
ENTRY_LEVELS = ("intern", "junior")


def _normalise(skill: str) -> str:
    skill = skill.lower().strip()
    return {"node": "node.js", "nodejs": "node.js", "js": "javascript",
            "ts": "typescript", "next": "next.js", "nextjs": "next.js",
            "postgres": "postgresql", "mongo": "mongodb",
            "k8s": "kubernetes", "ml": "machine learning"}.get(skill, skill)


def _mentions(text: str, skill: str) -> bool:
    """Whole-word match, so 'go' doesn't match 'good' and 'r' matches nothing."""
    if len(skill) < 2:
        return False
    return re.search(rf"(?<![\w.+#]){re.escape(skill)}(?![\w+#])", text, re.I) is not None


def skills_in(text: str, extra: set[str] | None = None) -> set[str]:
    """Skills a posting asks for, from a fixed vocabulary plus the
    candidate's own list, so their unusual skills are spotted too."""
    haystack = text.lower()
    pool = VOCABULARY | {_normalise(s) for s in (extra or set())}
    return {s for s in pool if _mentions(haystack, s)}


# ------------------------------------------------------------- dimensions
# Each returns (0-100, a sentence saying why).

def score_skills(required: set[str], mine: set[str]
                ) -> tuple[int, str, list[str], list[str], dict[str, list[str]]]:
    """Out of what the posting asks for, how much the candidate has.

    Related skills count half: someone who knows React can learn Next.js in
    a weekend, and pretending otherwise buries good matches. It is reported
    as partial, never folded silently into the total — and the bridge is
    named, not just the fact of one, since "you have something close" is
    not an answer anyone can act on.
    """
    if not required:
        # A posting naming no technology at all is usually not a job in this
        # field: a sales or writing role reads as "no skills listed" exactly
        # like a vague engineering one.
        return 15, "names no technology at all", [], [], {}

    matched = sorted(required & mine)
    rest = required - mine
    bridges = {s: sorted(RELATED.get(s, set()) & mine) for s in rest}
    bridges = {s: have for s, have in bridges.items() if have}
    partial = sorted(bridges)
    missing = sorted(rest - set(partial))

    credit = len(matched) + 0.5 * len(partial)
    score = round(100 * credit / len(required))
    note = f"{len(matched)} of {len(required)} listed skills"
    if partial:
        note += f", {len(partial)} close"
    return score, note, partial, missing, bridges


def score_role(job_title: str, wanted_roles: list[str], mine: set[str]) -> tuple[int, str]:
    """Is this the job they are looking for, by name."""
    title = (job_title or "").lower()
    for role in wanted_roles:
        role = role.lower().strip()
        if role and (role in title or title in role):
            return 100, f"title matches your target role ({role})"

    words = {w for role in wanted_roles for w in role.lower().split() if len(w) > 3}
    overlap = [w for w in words if w in title]
    if overlap:
        return 70, f"title shares {', '.join(sorted(overlap)[:2])} with your target roles"
    if any(_mentions(title, s) for s in mine):
        return 60, "title names your stack but not your target role"
    if not wanted_roles:
        return 50, "no target roles set, so the title can't be judged"
    return 25, "title isn't one of your target roles"


def score_seniority(job: dict, is_fresher: bool) -> tuple[int, str]:
    """The level the posting is pitched at, against where they actually are.

    Chapter 24 reads this off the title, which is far more reliable than the
    description: half the junior postings ever written mention working with
    senior engineers.
    """
    level = (job.get("seniority") or "").lower()
    if not level:
        title = (job.get("title") or "")
        if SENIOR.search(title) and not JUNIOR.search(title):
            level = "senior"
        elif JUNIOR.search(title):
            level = "junior"

    if not is_fresher:
        return (80, f"{level} role") if level else (70, "level not stated")

    if level in ENTRY_LEVELS:
        return 100, f"{level}-level, which is where you are"
    if level == "mid":
        return 45, "mid-level, a stretch from where you are"
    if level in ("senior", "lead"):
        return 5, f"{level}-level, likely out of reach for now"
    return 65, "level not stated"


def score_experience(text: str, has_experience: bool) -> tuple[int, str]:
    match = YEARS.search(text)
    if not match:
        return 70, "no experience bar stated"
    low = int(match.group(1))
    if low <= 1:
        return 100, f"asks for {low} year or less"
    if low == 2:
        return (60, "asks for about 2 years") if has_experience else (40, "asks for about 2 years")
    if low <= 4:
        return (30, f"asks for {low}+ years") if has_experience else (15, f"asks for {low}+ years")
    return 0, f"asks for {low}+ years, well above your profile"


def score_education(person: dict, text: str) -> tuple[int, str]:
    has_degree = bool(person.get("degree") or person.get("education"))
    wants_degree = re.search(r"\b(bachelor|b\.?tech|b\.?e\.?|degree|graduat|master|"
                             r"m\.?tech|computer science)\b", text, re.I)
    if has_degree:
        return 100, "your degree covers what it asks for" if wants_degree else "degree on file"
    if wants_degree:
        return 20, "asks for a degree and none is on your profile"
    return 60, "no degree asked for"


def can_work_there(job: dict, allowed: list[str]) -> tuple[bool, str]:
    """Is this job open to someone in one of the candidate's countries?

    A listing that names countries and doesn't name any of theirs is one
    they cannot take, whatever else fits. With no countries set, nothing is
    ruled out — silence is not a reason to discard jobs.
    """
    if not allowed:
        return True, ""

    place = f"{job.get('location', '')} {job.get('description', '')[:300]}".lower()
    if any(word in place for word in ANYWHERE_WORDS):
        return True, ""
    if any(country in place for country in allowed):
        return True, ""

    named = COUNTRY_WORDS.findall(job.get("location", ""))
    if named:
        return False, f"open to {job.get('location')}, where you can't work"
    return True, ""


def score_location(job: dict, prefs: dict, home: str, allowed: list[str]) -> tuple[int, str]:
    """Can they work there, and is it where they want to be."""
    eligible, note = can_work_there(job, allowed)
    if not eligible:
        return 0, note

    country = (job.get("country") or "").lower()
    city = (job.get("city") or "").lower()
    place = (job.get("location") or "").lower()
    wanted_places = [p.lower() for p in prefs.get("locations", []) if str(p).strip()]
    text = f"{place} {job.get('work_mode','')} {job.get('description','')[:400]}"

    if country in ("worldwide",) or OPEN_TO_ALL.search(text):
        return 95, "open worldwide"
    for wanted in wanted_places:
        if wanted and (wanted in place or wanted in city or place in wanted):
            return 100, f"in {job.get('location')}"
    if home and home.lower().split(",")[0].strip() in place:
        return 100, "in your city"
    if any(c in (country, place) for c in allowed):
        return 85, f"in {job.get('location') or country.title()}, where you can work"
    if REMOTE.search(text):
        return 75, "remote, though not somewhere you listed"
    if not wanted_places:
        return 60, "location not stated as a preference"
    return 30, f"in {job.get('location') or 'an unlisted location'}, not on your list"


def score_work_mode(job: dict, prefs: dict) -> tuple[int, str]:
    mode = (job.get("work_mode") or "").lower()
    wanted = [m.lower().strip() for m in prefs.get("work_modes", []) if str(m).strip()]
    if not mode:
        return 60, "work mode not stated"
    if not wanted:
        return 80, mode
    if mode in wanted:
        return 100, f"{mode}, as you prefer"
    if mode == "hybrid" and "onsite" in wanted:
        return 70, "hybrid, partly onsite as you prefer"
    return 35, f"{mode}, and you asked for {' or '.join(wanted)}"


def score_employment_type(job: dict, prefs: dict) -> tuple[int, str]:
    kind = (job.get("employment_type") or "").lower()
    wanted = [t.lower().strip() for t in prefs.get("employment_types", []) if str(t).strip()]
    if not kind:
        return 60, "employment type not stated"
    if not wanted:
        # Nothing stated, so assume what a fresher is normally after, and
        # say that is an assumption rather than a preference of theirs.
        return (90, kind) if kind in DEFAULT_TYPES else (45, f"{kind}, which you didn't ask for")
    if kind in wanted:
        return 100, f"{kind}, as you asked"
    return 30, f"{kind}, and you asked for {' or '.join(wanted)}"


def score_projects(person: dict) -> tuple[int, str]:
    count = len(person.get("projects", []))
    if count >= 3:
        return 100, f"{count} projects to talk about"
    if count:
        return 40 + count * 20, f"{count} project(s) on file"
    return 10, "no projects listed on your resume"


def _allowed_countries(profile: dict) -> list[str]:
    """Countries the candidate can work in, from their stated preference or,
    failing that, the country in their own address."""
    prefs = profile.get("preferences", {})
    listed = [c.lower().strip() for c in prefs.get("countries", []) if str(c).strip()]
    if listed:
        return listed
    home = profile.get("candidate", {}).get("location", "")
    tail = home.split(",")[-1].strip().lower()
    return [tail] if tail else []


# ----------------------------------------------------------------- scoring

def score_job(job: dict, profile: dict) -> dict:
    """Return the job with match_score, the nine dimensions, and the lists
    that explain it."""
    person = profile.get("candidate", {})
    prefs = profile.get("preferences", {})

    mine = {_normalise(s) for s in
            person.get("skills", []) + person.get("languages", []) + person.get("frameworks", [])
            if s.strip()}
    has_experience = bool(person.get("experience") or person.get("internships"))
    is_fresher = not person.get("experience")

    text = " ".join(str(job.get(k, "")) for k in ("title", "description", "company"))
    required = skills_in(text, mine)

    skills, skills_note, partial, missing, bridges = score_skills(required, mine)
    dimensions, notes = {}, {}
    for name, (value, note) in {
        "skills": (skills, skills_note),
        "role": score_role(job.get("title", ""), prefs.get("roles", []), mine),
        "seniority": score_seniority(job, is_fresher),
        "experience": score_experience(text, has_experience),
        "location": score_location(job, prefs, person.get("location", ""),
                                   _allowed_countries(profile)),
        "employment_type": score_employment_type(job, prefs),
        "work_mode": score_work_mode(job, prefs),
        "education": score_education(person, text),
        "projects": score_projects(person),
    }.items():
        dimensions[name] = max(0, min(100, value))
        notes[name] = note

    total = round(sum(WEIGHTS[name] * dimensions[name] / 100 for name in WEIGHTS))
    total = max(0, min(100, total))

    # Knowing the stack doesn't help if the posting filters you out before a
    # human reads it, so a job that cannot realistically be got is capped
    # however well it reads. The top ten has to stay worth applying to.
    matched = sorted(required & mine)
    cap, cap_reason = None, ""
    eligible, where_note = can_work_there(job, _allowed_countries(profile))
    if not eligible:
        cap, cap_reason = ELIGIBILITY_CAP, where_note
    elif dimensions["experience"] == 0:
        cap, cap_reason = REACH_CAP, "the experience bar is well above your profile"
    elif dimensions["seniority"] <= 10:
        cap, cap_reason = REACH_CAP, "a senior-level title"
    elif not required and not matched:
        cap, cap_reason = OFF_FIELD_CAP, "nothing in it matches what you do"

    breakdown = {"dimensions": dimensions, "notes": notes, "weighted": total,
                "skill_bridges": bridges}
    # Only a score that was above the cap was actually capped. One already
    # below it wasn't, and saying "capped at 45" beside a 29 would be false.
    capped = cap is not None and total > cap
    if capped:
        breakdown["capped_at"] = cap
        breakdown["cap_reason"] = cap_reason
        total = cap

    concerns = _concerns(job, dimensions, notes, cap_reason)
    # An academic bar the posting states — "CGPA of 7.5 and above" — and
    # where your resume stands against it. Said, never scored: the job
    # stays in the list and whether to apply is still yours (Chapter 26).
    from . import grades
    concerns += [c for c in grades.concerns(text, person) if c not in concerns]
    breakdown["concerns"] = concerns

    why = "; ".join([skills_note, notes["role"], notes["location"]]
                    + ([f"capped at {cap}: {cap_reason}"] if capped else []))
    if matched:
        why = "you have " + ", ".join(matched[:5]) + "; " + why

    job = dict(job)
    job.update({
        "match_score": total,
        "score_breakdown": breakdown,
        "skills_required": sorted(required),
        "skills_matched": matched,
        "skills_partial": partial,
        "skills_missing": missing,
        "why": why,
    })
    return job


def _concerns(job: dict, dimensions: dict, notes: dict, cap_reason: str) -> list[str]:
    """Things to know before applying. Not reasons not to — that is the
    candidate's call — but things they should not find out afterwards."""
    out = []
    if cap_reason:
        out.append(cap_reason[0].upper() + cap_reason[1:])
    if dimensions["experience"] < 50 and "no experience bar" not in notes["experience"]:
        out.append(notes["experience"][0].upper() + notes["experience"][1:])
    if dimensions["seniority"] <= 45:
        out.append(notes["seniority"][0].upper() + notes["seniority"][1:])
    if dimensions["education"] <= 20:
        out.append(notes["education"][0].upper() + notes["education"][1:])
    if dimensions["employment_type"] <= 45:
        out.append(notes["employment_type"][0].upper() + notes["employment_type"][1:])

    from . import normalise
    if normalise.is_stale(job.get("posted_at") or ""):
        age = normalise.age_phrase(job.get("posted_at") or "")
        out.append(f"Posted {age}, so it may already be filled")

    seen, unique = set(), []
    for item in out:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def rank(jobs: list[dict], profile: dict) -> list[dict]:
    """Score every job and sort best first."""
    return sorted((score_job(j, profile) for j in jobs),
                  key=lambda j: -j["match_score"])


def explain(job: dict) -> str:
    """The answer to "why did you pick this one?", in full.

    Deliberately never says the job is suitable. It shows the arithmetic and
    what sits behind each number; whether to apply is not a thing a weighted
    sum gets to decide.
    """
    breakdown = job.get("score_breakdown") or {}
    dimensions = breakdown.get("dimensions") or {}
    notes = breakdown.get("notes") or {}

    lines = ["MATCH ANALYSIS", "",
             f"{job['title']} at {job['company']} — {job['match_score']}/100", ""]

    for name in ORDER:
        if name not in dimensions:
            continue
        label = name.replace("_", " ").title()
        share = round(WEIGHTS[name] * dimensions[name] / 100, 1)
        lines.append(f"  {label:<16}{dimensions[name]:>4}/100   "
                     f"{share:>4} of {WEIGHTS[name]} — {notes.get(name, '')}")

    if breakdown.get("weighted") is not None:
        lines += ["", f"  Weighted total  {breakdown['weighted']}/100"]
    if breakdown.get("capped_at") is not None:
        lines.append(f"  Capped at       {breakdown['capped_at']} — "
                     f"{breakdown.get('cap_reason', '')}")

    if job.get("skills_matched"):
        lines += ["", "Strong matches:"] + [f"  ✓ {s}" for s in job["skills_matched"]]
    bridges = breakdown.get("skill_bridges") or {}
    if job.get("skills_partial"):
        lines += ["", "Partial:"]
        for s in job["skills_partial"]:
            have = bridges.get(s) or []
            lines.append(f"  △ {s}"
                        + (f" — you have {', '.join(have)}" if have else ""))
    if job.get("skills_missing"):
        lines += ["", "Missing:"] + [f"  ✗ {s}" for s in job["skills_missing"]]

    concerns = breakdown.get("concerns") or []
    if concerns:
        lines += ["", "Potential concerns:"] + [f"  ⚠ {c}" for c in concerns]

    lines += ["", "This is what lines up and what doesn't — whether it's worth "
                  "applying to is your call."]
    return "\n".join(lines)
