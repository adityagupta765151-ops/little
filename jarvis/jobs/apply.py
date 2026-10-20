"""Helping with an application, without ever submitting one.

JARVIS opens the posting, fills the fields it can answer from the resume,
and then stops. The final click is yours, for three reasons: LinkedIn,
Naukri and Indeed all forbid automated submission in their terms; an
answer JARVIS guessed would be a claim made in your name; and a wrong
application cannot be taken back.

Nothing is ever written as applied unless you say it was, and nothing is
ever SUBMITTED without proof: a confirmation page in LITTLE's own browser,
or the confirmation number you were given (Chapter 27).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .resume import load_profile
from .store import (WORDS, already_applied, audit, by_reference, change_status, record_application,
                    record_submission, status_name, top_jobs)

# Fields that can be answered from the resume, with the labels employers
# tend to use for them.
FIELD_MAP = {
    "name": ["full name", "your name", "name", "first name"],
    "email": ["email", "e-mail", "email address"],
    "phone": ["phone", "mobile", "contact number", "phone number"],
    "location": ["location", "city", "current location", "address"],
}

# Anything in this list is a judgement call, a legal declaration or a
# secret. JARVIS never answers these, even if it could guess.
ALWAYS_ASK = [
    "salary", "expected ctc", "current ctc", "notice period", "why do you want",
    "cover letter", "visa", "work authorization", "sponsorship", "relocate",
    "gender", "race", "ethnicity", "disability", "veteran", "date of birth",
    "captcha", "otp", "verification code", "password", "consent", "declare",
    "certify", "agree to", "references",
]


def _resolve(reference: str) -> dict | None:
    """Accept "id:<job id>" (exact), a rank number from the top list, or
    part of a company name."""
    reference = (reference or "").strip()
    if reference.startswith("id:"):
        return by_reference(reference)
    jobs = top_jobs(limit=25)
    if not jobs:
        return None
    if reference.isdigit() and 1 <= int(reference) <= len(jobs):
        return jobs[int(reference) - 1]
    needle = reference.lower()
    return next((j for j in jobs
                 if needle in j["company"].lower() or needle in j["title"].lower()), None)


def prepare_application(reference: str) -> str:
    """Open a job and fill in what the resume can answer. Does not submit."""
    from ..tools import browser

    job = _resolve(reference)
    if not job:
        return f"I couldn't find '{reference}' in the stored jobs. Say show my top matches."

    if already_applied(job["job_id"]):
        return (f"You already applied to {job['title']} at {job['company']}. "
                f"I won't open a duplicate.")

    if not job["url"]:
        record_application(job["job_id"], "APPLICATION_FAILED", source="browser",
                           notes="no application link stored")
        return f"{job['company']} has no application link stored, so I can't open it."

    profile = load_profile()
    person = profile.get("candidate", {})

    opened = browser.open_page(job["url"])
    if not opened.startswith("Opened"):
        record_application(job["job_id"], "APPLICATION_FAILED", source="browser",
                           notes=opened)
        audit("prepare", platform=job["platform"], company=job["company"],
              job=job["title"], result="failed", error=opened)
        return f"I couldn't open the posting: {opened}"

    filled: list[str] = []
    for field, labels in FIELD_MAP.items():
        value = person.get(field, "")
        if not value:
            continue
        for label in labels:
            result = browser.fill_field(label, value)
            if result.startswith("Filled"):
                filled.append(f"{field} = {value}")
                break

    page = browser.read_page()
    asks_for = [phrase for phrase in ALWAYS_ASK if phrase in page.lower()]

    note = f"filled {len(filled)} field{'s' if len(filled) != 1 else ''}"
    if asks_for:
        note += "; the form asks " + ", ".join(sorted(set(asks_for))[:6]) + " — yours to answer"
    moved, _why = change_status(job["job_id"], "PREPARED", source="prepare", note=note)
    if not moved:
        from .store import record_event
        record_event(job["job_id"], "prepared", source="prepare", note=note)
    audit("prepare", platform=job["platform"], company=job["company"], job=job["title"],
          result=f"filled {len(filled)} fields")

    lines = [
        f"{job['title']} at {job['company']} — match {job['match_score']}/100",
        f"{job['url']}",
        "",
        f"Resume on file: {profile.get('source_file') or 'none'}",
    ]
    lines.append("Filled in: " + (", ".join(filled) if filled
                                  else "nothing — I couldn't find fields I could answer"))
    if asks_for:
        lines.append("")
        lines.append("This form asks things I won't answer for you: "
                     + ", ".join(sorted(set(asks_for))[:6]) + ".")
    lines.append("")
    lines.append("The page is open. Check every field, attach your resume, and press "
                 "submit yourself. Then tell me: mark 1 as applied — and once the "
                 "confirmation page shows, say: verify my application to 1.")
    return "\n".join(lines)


def mark_applied(reference: str, notes: str = "") -> str:
    """Record that you submitted an application. Only you can say this, and
    it's recorded as your word (USER_APPROVED), not as verified."""
    job = _resolve(reference)
    if not job:
        return f"I couldn't find '{reference}' in the stored jobs."
    if already_applied(job["job_id"]):
        return "That one is already recorded as applied."
    if job["status"] not in ("FOUND", "ANALYZED", "SAVED", "PREPARED"):
        return (f"{job['company']} — {job['title']} is {WORDS.get(job['status'], job['status'])}, "
                f"so there's no application to record now.")

    application_id = record_application(job["job_id"], "USER_APPROVED",
                                        source=job["platform"], notes=notes)
    audit("applied", platform=job["platform"], company=job["company"], job=job["title"],
          result="recorded (your word)", application_id=application_id)
    return (f"Recorded: applied to {job['title']} at {job['company']} — on your word. "
            f"When you have the confirmation page or number, I can mark it verified.")


# What a page says once an application has gone in. Read from the page
# LITTLE's browser has open — never guessed from a URL alone.
CONFIRMED = re.compile(
    r"(?:your\s+)?application\s+(?:has\s+been\s+|was\s+)?(?:successfully\s+)?(?:submitted|received|sent)|"
    r"thank(?:s|\s+you)\s+for\s+(?:applying|your\s+application)|"
    r"we(?:'ve|\s+have)\s+received\s+your\s+application|"
    r"successfully\s+(?:applied|submitted)|application\s+(?:complete|successful)", re.I)
CONFIRMATION_NUMBER = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_/#.]{3,63}")


def verify_submission(reference: str) -> str:
    """Check the page open in LITTLE's browser for proof that the application
    went in: a confirmation message on a page about this job. Only then is it
    SUBMITTED. Reads the page; never clicks anything."""
    from ..tools import browser

    job = _resolve(reference)
    if not job:
        return f"I couldn't find '{reference}' in the stored jobs."
    if job["status"] == "SUBMITTED":
        return f"{job['company']} — {job['title']} is already verified as submitted."
    if job["status"] not in ("PREPARED", "USER_APPROVED"):
        return (f"{job['company']} — {job['title']} is {WORDS.get(job['status'], job['status'])}. "
                f"Prepare it or tell me you applied first.")
    page = browser.current_page()
    if not page:
        return ("No page is open in my browser, so I can't see a confirmation. It stays "
                f"{WORDS[job['status']]}. If you have a confirmation number, say: "
                f"mark {job['company']} submitted with confirmation <number>.")
    text = f"{page.get('title', '')}\n{page.get('text', '')}"
    said = CONFIRMED.search(text)
    host = urlparse(page.get("url", "")).netloc.lower()
    job_host = urlparse(job.get("url") or "").netloc.lower()
    about_it = (host and host == job_host) or job["company"].lower() in text.lower() \
        or job["title"].lower() in text.lower()
    if not said or not about_it:
        why = ("it doesn't say the application was received" if not said
               else "it doesn't mention this job or its company")
        audit("verify", company=job["company"], job=job["title"], result="not verified", error=why)
        return (f"I looked at the page open in my browser ({host or 'no address'}), but {why}, "
                f"so it stays {WORDS[job['status']]}.")
    evidence = f"confirmation page {page.get('url', '')}: “{said.group(0)}”"
    moved, why_not = change_status(job["job_id"], "SUBMITTED", source="browser", evidence=evidence)
    if not moved:
        return why_not
    record_submission(job["job_id"], evidence)
    audit("verify", company=job["company"], job=job["title"], result="submitted (verified)")
    return (f"Verified: {job['title']} at {job['company']} is submitted — the page says "
            f"“{said.group(0)}”.")


def mark_submitted(reference: str, confirmation: str) -> str:
    """Record a submission with the confirmation number you were given — the
    proof SUBMITTED needs when the page itself is gone."""
    job = _resolve(reference)
    if not job:
        return f"I couldn't find '{reference}' in the stored jobs."
    number = str(confirmation or "").strip().strip(".,")
    if not CONFIRMATION_NUMBER.fullmatch(number):
        return ("Give me the confirmation or reference number from the confirmation page or "
                "email — letters and digits, like APP-2026-4411.")
    if job["status"] == "SUBMITTED":
        return f"{job['company']} — {job['title']} is already verified as submitted."
    evidence = f"confirmation number {number}, as you gave it"
    moved, why_not = change_status(job["job_id"], "SUBMITTED", source="you", evidence=evidence)
    if not moved:
        return why_not + (" Tell me you applied first." if job["status"] in ("FOUND", "ANALYZED", "SAVED")
                          else "")
    record_submission(job["job_id"], evidence, confirmation_id=number)
    audit("submitted", company=job["company"], job=job["title"], result=f"confirmation {number}")
    return f"Recorded: {job['title']} at {job['company']} is submitted, confirmation {number}."


def mark_status(reference: str, status: str) -> str:
    """Move a job along: saved, interview, offer, rejected, withdrawn — only
    where it can go from where it is. "Applied" is your word; "submitted"
    needs proof."""
    from .store import STATUSES

    wanted = status_name(status)
    if not wanted:
        return f"Status must be one of: {', '.join(s.lower() for s in STATUSES)}."
    if wanted == "USER_APPROVED":
        return mark_applied(reference)
    if wanted == "SUBMITTED":
        return ("Submitted means the submission was verified. With the confirmation page open "
                "in my browser, say: verify my application to it — or give me the confirmation "
                "number: mark it submitted with confirmation <number>.")

    job = _resolve(reference)
    if not job:
        return f"I couldn't find '{reference}' in the stored jobs."

    moved, why_not = change_status(job["job_id"], wanted, source="you")
    if not moved:
        return f"{job['company']} — {job['title']}: {why_not}"
    audit("status", company=job["company"], job=job["title"], result=wanted)
    return f"{job['company']} — {job['title']} is now {WORDS[wanted]}."


def upload_resume_to_form(path: str = "") -> str:
    """Attach the resume file to the open application form."""
    profile = load_profile()
    filename = path or profile.get("source_file", "")
    if not filename:
        return "I don't know which resume file to attach. Scan one first."
    return ("I can't attach files to a form for you — the browser blocks scripted "
            f"file pickers. Attach {filename} yourself; the page is open.")
