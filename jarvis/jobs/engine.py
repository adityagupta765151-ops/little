"""The job-hunt pipeline, and the sentences JARVIS says about it.

Resume profile -> search -> deduplicate -> score -> store -> top ten.
Nothing here applies to anything; that lives in apply.py and always goes
through the user.
"""
from __future__ import annotations

import re

from ..app.config import log
from . import matching, normalise, sources, store
from .resume import load_profile


def _profile_or_complaint() -> tuple[dict | None, str]:
    profile = load_profile()
    person = profile.get("candidate", {})
    if not person.get("skills"):
        from .resume import scan_hint
        return None, ("I don't have your resume yet, so I have nothing to match "
                      "against. " + scan_hint())
    return profile, ""


# A skill is not a job title. Boards match titles, so "MERN Stack AI/ML
# fundamentals REST APIs" — three skills glued together — matches nothing
# anywhere. Each family of skills maps to what the job is actually called.
ROLE_FOR_SKILL = {
    "react": "frontend developer", "react.js": "frontend developer",
    "next": "frontend developer", "next.js": "frontend developer",
    "angular": "frontend developer", "vue": "frontend developer",
    "javascript": "frontend developer", "typescript": "frontend developer",
    "html": "frontend developer", "css": "frontend developer",
    "tailwind": "frontend developer",
    "node": "backend developer", "node.js": "backend developer",
    "express": "backend developer", "express.js": "backend developer",
    "mongodb": "backend developer", "sql": "backend developer",
    "postgresql": "backend developer", "mysql": "backend developer",
    "rest api": "backend developer", "rest apis": "backend developer",
    "django": "python developer", "flask": "python developer",
    "python": "python developer",
    "java": "java developer", "spring": "java developer",
    "c++": "software developer", "c": "software developer",
    "mern": "full stack developer", "mern stack": "full stack developer",
    "full stack": "full stack developer", "fullstack": "full stack developer",
    "machine learning": "machine learning engineer",
    "deep learning": "machine learning engineer",
    "tensorflow": "machine learning engineer", "pytorch": "machine learning engineer",
    "nlp": "machine learning engineer", "ai": "machine learning engineer",
    "ai/ml": "machine learning engineer", "data science": "data scientist",
    "pandas": "data analyst", "numpy": "data analyst", "power bi": "data analyst",
    "excel": "data analyst", "tableau": "data analyst",
}

MAX_QUERIES = 3
RESCORE_LIMIT = 2000


def rescore_stored(profile: dict | None = None) -> int:
    """Score every stored job again against the profile as it is now, so a
    corrected CGPA, a new skill or a new resume shows on the jobs you already
    have — their concerns included. Status and history are untouched
    (store.upsert_job only refreshes the scoring). Returns how many."""
    from .resume import is_ready
    profile = profile if profile is not None else load_profile()
    if not is_ready(profile):
        return 0
    stored = store.top_jobs(limit=RESCORE_LIMIT)
    for job in stored:
        store.upsert_job(matching.score_job(job, profile))
    if stored:
        store.audit("rescore", result=f"{len(stored)} jobs re-scored against the current profile")
    return len(stored)


def _queries_from(profile: dict, override: str = "") -> list[str]:
    """The searches to run, as things a job board would recognise.

    Several rather than one, because a person is employable as more than
    one job title and a single query only ever finds one of them. Capped,
    because every extra query is another round of six boards.
    """
    if override.strip():
        return [override.strip()]

    roles = [r for r in profile.get("preferences", {}).get("roles", []) if r.strip()]
    if roles:
        return roles[:MAX_QUERIES]

    queries: list[str] = []
    for skill in profile["candidate"].get("skills", []):
        # Resumes say "AI/ML fundamentals" and "REST APIs (basics)", not
        # "ai/ml" — so a skill counts if it contains a known one.
        key = skill.lower().strip()
        role = ROLE_FOR_SKILL.get(key)
        if not role:
            hits = [r for k, r in ROLE_FOR_SKILL.items()
                    if len(k) > 2 and re.search(rf"(?<!\w){re.escape(k)}(?!\w)", key)]
            role = hits[0] if hits else None
        if role and role not in queries:
            queries.append(role)
        if len(queries) >= MAX_QUERIES:
            break
    return queries or ["software developer"]


def find_jobs(query: str = "", location: str = "", limit: int = 30) -> str:
    """Search the job boards, score everything against the resume, store it."""
    profile, complaint = _profile_or_complaint()
    if not profile:
        return complaint

    queries = _queries_from(profile, query)
    where = location or (profile["preferences"].get("locations") or [""])[0]
    search_for = ", ".join(queries)

    store.audit("search", platform="all", job=search_for, result="started")

    found, notes = [], []
    seen: set[str] = set()
    for term in queries:
        batch, batch_notes = sources.search(term, where, limit)
        for job in batch:                     # the same posting under two titles
            if job["job_id"] not in seen:
                seen.add(job["job_id"])
                found.append(job)
        notes.append(f"[{term}] " + ", ".join(batch_notes)
                     if len(queries) > 1 else ", ".join(batch_notes))

    if not found:
        store.audit("search", job=search_for, result="0 jobs", error="; ".join(notes))
        return (f"No jobs came back for {search_for}. Searched: {' | '.join(notes)}. "
                f"If adzuna says no key, add ADZUNA_APP_ID and ADZUNA_APP_KEY to your .env.")

    ranked = matching.rank(found, profile)
    new_count = sum(1 for job in ranked if store.upsert_job(job))
    strong = [j for j in ranked if j["match_score"] >= 70]

    store.audit("search", job=search_for,
                result=f"{len(ranked)} scored, {new_count} new, {len(strong)} strong")

    lines = [f"Found {len(ranked)} jobs for {search_for}, {new_count} of them new. "
             f"{len(strong)} score 70 or above."]
    lines.append("Searched: " + " | ".join(notes))
    lines.append("")
    fresh = sum(1 for j in ranked if not normalise.is_stale(j.get("posted_at", "")))
    dated = sum(1 for j in ranked if j.get("posted_at"))
    if dated:
        lines.append(f"{fresh} of them posted in the last {normalise.STALE_DAYS} days.")
    lines.append("")
    for i, job in enumerate(ranked[:5], 1):
        age = normalise.age_phrase(job.get("posted_at", ""))
        lines.append(f"{i}. {job['match_score']:>3}  {job['title']} — {job['company']} "
                     f"({job['location'] or 'location not stated'}"
                     f"{', ' + age if age else ''})")
    if len(ranked) > 5:
        lines.append("... say show my top matches for the full ten.")
    return "\n".join(lines)


def top_matches(count: int = 10, min_score: int = 0, max_age_days: int = 0) -> str:
    """The Top 10 list, in the shape the spec asks for.

    `max_age_days` narrows it to recent postings, for when the last search
    turned up a month of backlog.
    """
    jobs = store.top_jobs(limit=count, min_score=min_score, max_age_days=max_age_days)
    if not jobs:
        if max_age_days:
            return (f"Nothing stored was posted in the last {max_age_days} days. "
                    f"Say find jobs for me to search again.")
        return ("Nothing stored yet. Say find jobs for me first."
                if min_score == 0 else f"No stored job scores {min_score} or above.")

    blocks = []
    for i, job in enumerate(jobs, 1):
        applied = " (already applied)" if store.already_applied(job["job_id"]) else ""
        # Age first: whether a posting is three days or three months old
        # decides whether the rest of the line is worth reading.
        age = normalise.age_phrase(job.get("posted_at", "") or "")
        posted = f"posted {age}" if age else "no date given"
        if normalise.is_stale(job.get("posted_at", "") or ""):
            posted += " — likely filled"
        kind = job.get("employment_type") or ""
        level = job.get("seniority") or ""
        shape = " · ".join(p for p in (job["work_mode"], kind, level) if p)
        blocks.append("\n".join([
            f"Job #{i}   MATCH {job['match_score']}/100{applied}",
            f"  {job['title']} — {job['company']}",
            f"  {job['location'] or 'location not stated'} · {shape}",
            f"  {posted} · via {job['platform']}",
            f"  Salary: {job['salary'] or 'not stated'}",
            f"  You have: {', '.join(job['skills_matched']) or 'nothing listed matched'}",
            f"  Missing:  {', '.join(job['skills_missing']) or 'nothing'}",
            f"  Status:   {job['status']}",
            f"  {job['url']}",
        ]))
    return "\n\n".join(blocks)


def why_this_job(reference: str) -> str:
    """Explain one job's score. Reference can be a rank number or part of
    the company name."""
    reference = reference.strip()
    jobs = store.top_jobs(limit=25)
    if not jobs:
        return "Nothing stored yet."

    job = _find(reference, jobs)
    if not job:
        return f"I couldn't find a stored job matching '{reference}'."
    _analyzed(job)
    return matching.explain(job)


def _find(reference: str, jobs: list[dict]) -> dict | None:
    """ "id:<job id>" exactly, a rank in the top list, or part of the company
    name or title."""
    job = store.by_reference(reference)
    if job:
        return job
    if reference.isdigit() and 1 <= int(reference) <= len(jobs):
        return jobs[int(reference) - 1]
    needle = reference.lower()
    return next((j for j in jobs
                 if needle in j["company"].lower() or needle in j["title"].lower()), None)


def _analyzed(job: dict) -> None:
    """Looking at a job's full analysis moves a new job to ANALYZED; for one
    further along it goes in the history without changing the status."""
    try:
        if job["status"] == "FOUND":
            store.change_status(job["job_id"], "ANALYZED", source="analysis",
                                note="you looked at its full analysis")
        else:
            store.record_event(job["job_id"], "analyzed", source="analysis",
                               note="you looked at its full analysis")
    except Exception as e:  # noqa: BLE001  (the explanation matters more than the record)
        log(f"recording the analysis failed: {e}")


def missing_skills(limit: int = 10) -> str:
    """Which skills keep coming up that the resume doesn't have."""
    tally = store.missing_skill_counts(limit)
    if not tally:
        return "No jobs scored yet, so there's nothing to compare against."
    lines = ["Skills asked for most often that your resume doesn't list:"]
    for skill, count in tally:
        lines.append(f"  {skill:<20} in {count} job{'s' if count > 1 else ''}")
    return "\n".join(lines)


def open_board(board: str, query: str = "", location: str = "") -> str:
    """Open a board JARVIS isn't allowed to automate, so you can browse it."""
    import webbrowser

    profile = load_profile()
    # One search box, so the first role rather than all of them.
    search_for = _queries_from(profile, query)[0]
    url = sources.manual_search_url(board, search_for, location)
    if not url:
        return (f"I don't have a search link for {board}. I know linkedin, naukri, "
                f"indeed, internshala and wellfound.")
    webbrowser.open(url)
    store.audit("open_board", platform=board, job=search_for, result="opened for browsing")
    return (f"Opened {board} for {search_for}. I can't search or apply there "
            f"automatically — their terms don't allow it — so have a look yourself.")


def shortlist(reference: str) -> str:
    """Mark a job as one you want to go for. Reference: "id:<job id>", a
    rank number, or part of the company name."""
    jobs = store.top_jobs(limit=25)
    job = store.by_reference(reference)
    if job:
        pass
    elif reference.isdigit() and 1 <= int(reference) <= len(jobs):
        job = jobs[int(reference) - 1]
    else:
        needle = reference.lower()
        job = next((j for j in jobs if needle in j["company"].lower()), None)
    if not job:
        return f"I couldn't find '{reference}' in the stored jobs."
    moved, why_not = store.change_status(job["job_id"], "SAVED", source="you")
    if not moved and not why_not.startswith("It's already"):
        return f"{job['company']} — {job['title']}: {why_not}"
    store.audit("shortlist", company=job["company"], job=job["title"], result="SAVED")
    return f"Shortlisted {job['title']} at {job['company']}."


def application_status() -> str:
    """What has actually been applied to, read from the database."""
    rows = store.applications(limit=20)
    if not rows:
        return "No applications recorded yet."
    words = {"USER_APPROVED": "applied (your word)", "SUBMITTED": "submitted (verified)",
             "APPLICATION_FAILED": "couldn't open", "APPLIED": "applied (your word)"}
    lines = [f"{len(rows)} application record(s):"]
    for row in rows:
        when = (row["applied_at"] or "")[:16].replace("T", " ")
        proof = f" — confirmation {row['confirmation_id']}" if row.get("confirmation_id") else ""
        lines.append(f"  {words.get(row['status'], row['status'].lower()):<21} {row['company']} — "
                     f"{row['title']} {when}{proof}".rstrip())
    c = store.counts()
    lines.append("")
    lines.append("Where every stored job stands: " + ", ".join(
        f"{store.WORDS[s]} {n}" for s, n in c["pipeline"].items() if n))
    return "\n".join(lines)


def job_history(reference: str) -> str:
    """One job's timeline: when it was found, every change since, and where
    each came from. Read from the job store."""
    jobs = store.top_jobs(limit=25)
    job = _find(reference.strip(), jobs) if jobs or reference.startswith("id:") else None
    if not job:
        return f"I couldn't find a stored job matching '{reference}'."
    lines = [f"TIMELINE — {job['title']} at {job['company']}", ""]
    for event in store.history(job["job_id"]):
        when = (event["at"] or "")[:16].replace("T", " ")
        if event["kind"] == "found":
            what = f"found via {event['source'] or 'a search'}"
        elif event["kind"] in ("status", "migrated"):
            what = f"{store.WORDS.get(event['from_status'], (event['from_status'] or '?').lower())} → " \
                   f"{store.WORDS.get(event['to_status'], (event['to_status'] or '?').lower())}"
        elif event["kind"] == "prepare_failed":
            what = "Prepare couldn't open the posting"
        else:
            what = event["kind"].replace("_", " ")
        extra = "; ".join(x for x in (event.get("note"), event.get("evidence")) if x)
        lines.append(f"  {when}  {what}" + (f" — {extra}" if extra else ""))
    lines += ["", f"Now: {store.WORDS.get(job['status'], job['status'].lower())}."]
    return "\n".join(lines)


def effectiveness() -> str:
    """The analytics, spoken rather than drawn."""
    c = store.counts()
    if not c["jobs_total"]:
        return "Nothing found yet, so there's nothing to measure."
    return "\n".join([
        f"Jobs discovered: {c['jobs_total']} ({c['jobs_today']} today)",
        f"Average match score: {c['avg_score']}",
        f"Application attempts: {c['attempts']}, applied: {c['applied']} "
        f"({c['submitted']} verified as submitted), couldn't open: {c['failed']}, "
        f"prepared and waiting for you: {c['needs_action']}",
        f"Success rate: {c['success_rate']}%",
        f"Interviews: {c['interviews']} ({c['interview_rate']}% of applications)",
        f"Offers: {c['offers']} ({c['offer_rate']}%)",
    ])
