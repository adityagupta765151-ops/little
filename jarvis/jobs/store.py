"""Where jobs, applications and the audit trail live.

One SQLite file under memory/. Plain SQL rather than an ORM, because the
schema is small and readable this way, and the file can be opened with any
SQLite viewer if something looks wrong.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import sqlite3
import threading
from typing import Any

from ..app.config import MEMORY_DIR, log

DB_PATH = MEMORY_DIR / "jobs.db"

# Chapter 27: a job's life, in order. SUBMITTED means the submission was
# verified — a confirmation page seen in LITTLE's browser, or a confirmation
# number you give. Your word alone ("I applied") is USER_APPROVED.
STATUSES = ("FOUND", "ANALYZED", "SAVED", "PREPARED", "USER_APPROVED", "SUBMITTED",
            "REJECTED", "INTERVIEW", "OFFER", "WITHDRAWN")
BEFORE_APPLYING = ("FOUND", "ANALYZED", "SAVED", "PREPARED")
APPLIED = ("USER_APPROVED", "SUBMITTED")
OUTCOMES = ("INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN")

# The names used before Chapter 27, and what each became. Stored jobs are
# renamed once, with the old name kept in the job's history and a copy of
# the database made first; the old words are still accepted as input.
LEGACY = {"SHORTLISTED": "SAVED", "READY_TO_APPLY": "PREPARED", "NEEDS_USER_ACTION": "PREPARED",
          "APPLIED": "USER_APPROVED", "APPLICATION_FAILED": "FOUND"}

# Where a job may go next. Forward is free — a recruiter can call about a
# job you never saved — but nothing goes back to before you applied, an
# ended job stays ended, and SUBMITTED is reached only from a prepared or
# applied job, with proof (change_status).
TRANSITIONS = {
    "FOUND":         {"ANALYZED", "SAVED", "PREPARED", "USER_APPROVED"} | set(OUTCOMES),
    "ANALYZED":      {"FOUND", "SAVED", "PREPARED", "USER_APPROVED"} | set(OUTCOMES),
    "SAVED":         {"FOUND", "ANALYZED", "PREPARED", "USER_APPROVED"} | set(OUTCOMES),
    "PREPARED":      {"FOUND", "SAVED", "USER_APPROVED", "SUBMITTED"} | set(OUTCOMES),
    "USER_APPROVED": {"SUBMITTED"} | set(OUTCOMES),
    "SUBMITTED":     set(OUTCOMES),
    "INTERVIEW":     {"INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"},
    "OFFER":         {"REJECTED", "WITHDRAWN"},
    "REJECTED":      set(),
    "WITHDRAWN":     set(),
}
WORDS = {"FOUND": "found", "ANALYZED": "analyzed", "SAVED": "saved", "PREPARED": "prepared",
         "USER_APPROVED": "applied (your word)", "SUBMITTED": "submitted (verified)",
         "REJECTED": "rejected", "INTERVIEW": "interview", "OFFER": "offer", "WITHDRAWN": "withdrawn"}


def status_name(word: str) -> str:
    """A status as the store keeps it, from what people or old code say:
    "shortlisted" is SAVED, "applied" is USER_APPROVED. "" if it's none."""
    name = str(word or "").upper().strip().replace(" ", "_").replace("-", "_")
    name = LEGACY.get(name, name) if name != "APPLICATION_FAILED" else ""
    return name if name in STATUSES else ""

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    company          TEXT NOT NULL,
    title            TEXT NOT NULL,
    location         TEXT,
    work_mode        TEXT,
    salary           TEXT,
    platform         TEXT,
    url              TEXT,
    description      TEXT,
    match_score      INTEGER DEFAULT 0,
    score_breakdown  TEXT,
    skills_required  TEXT,
    skills_matched   TEXT,
    skills_missing   TEXT,
    skills_partial   TEXT,
    why              TEXT,
    discovered_at    TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'FOUND',
    posted_at        TEXT,
    employment_type  TEXT,
    seniority        TEXT,
    city             TEXT,
    country          TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    application_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL REFERENCES jobs(job_id),
    applied_at      TEXT,
    resume_version  TEXT,
    status          TEXT NOT NULL,
    source          TEXT,
    confirmation_id TEXT,
    notes           TEXT,
    follow_up_date  TEXT
);

CREATE TABLE IF NOT EXISTS audit (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      TEXT NOT NULL,
    action         TEXT NOT NULL,
    platform       TEXT,
    company        TEXT,
    job            TEXT,
    result         TEXT,
    error          TEXT,
    application_id INTEGER
);

CREATE TABLE IF NOT EXISTS job_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       TEXT NOT NULL REFERENCES jobs(job_id),
    at           TEXT NOT NULL,
    kind         TEXT NOT NULL,
    from_status  TEXT,
    to_status    TEXT,
    source       TEXT,
    note         TEXT,
    evidence     TEXT
);

CREATE INDEX IF NOT EXISTS jobs_score ON jobs(match_score DESC);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS job_events_job ON job_events(job_id, id);
"""

_lock = threading.Lock()


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# Columns added after the first release. A database created before them
# gets them added in place; nothing is rebuilt and no row is rewritten.
ADDED_COLUMNS = {
    "posted_at": "TEXT",            # when the board says it went up
    "employment_type": "TEXT",      # full-time, internship, contract...
    "seniority": "TEXT",            # intern, junior, mid, senior, lead
    "city": "TEXT",
    "country": "TEXT",
    "skills_partial": "TEXT",       # skills the candidate has something close to
}


def _migrate(conn: sqlite3.Connection) -> list[str]:
    """Add any column this version expects and the file doesn't have.

    SQLite can add a column to a populated table without touching its rows,
    which is the whole reason the new fields are nullable and have no
    default: an existing job simply has no posting date, and that is the
    truth about it.
    """
    have = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    added = []
    for name, kind in ADDED_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {kind}")
            added.append(name)
    if added:
        conn.commit()
        log(f"jobs.db migrated: added {', '.join(added)}")
    return added


def _migrate_statuses(conn: sqlite3.Connection) -> int:
    """Chapter 27: rename the old statuses, once. A copy of the database is
    made first (jobs.before-chapter27.db beside it), and each renamed job
    gets a history line saying what it was called. Nothing is deleted: a
    job whose Prepare once failed goes back to FOUND, with the failure in
    its history. Returns how many jobs were renamed."""
    old = tuple(LEGACY)
    marks = ",".join("?" * len(old))
    rows = conn.execute(f"SELECT job_id, status FROM jobs WHERE status IN ({marks})", old).fetchall()
    stale_apps = conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'APPLIED'").fetchone()[0]
    if not rows and not stale_apps:
        return 0
    backup = DB_PATH.with_name("jobs.before-chapter27.db")
    if not backup.exists():
        copy = sqlite3.connect(backup)
        try:
            conn.backup(copy)
        finally:
            copy.close()
    now = _now()
    for row in rows:
        new = LEGACY[row["status"]]
        conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (new, row["job_id"]))
        note = ("Prepare couldn't open this posting (before Chapter 27)"
                if row["status"] == "APPLICATION_FAILED"
                else f"Renamed from {row['status']} (Chapter 27)")
        conn.execute("""INSERT INTO job_events (job_id, at, kind, from_status, to_status, source, note)
                        VALUES (?,?,?,?,?,?,?)""",
                     (row["job_id"], now, "migrated", row["status"], new, "chapter 27", note))
    conn.execute("UPDATE applications SET status = 'USER_APPROVED' WHERE status = 'APPLIED'")
    conn.commit()
    log(f"jobs.db: renamed {len(rows)} job statuses for Chapter 27; copy kept at {backup.name}")
    return len(rows)


def connect() -> sqlite3.Connection:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    _migrate_statuses(conn)
    return conn


def job_id_for(company: str, title: str, url: str = "") -> str:
    """The same posting listed on two boards should collapse into one row.

    Company and title decide identity, normalised hard enough that
    "Google India Pvt Ltd" and "Google" don't count as different, and the
    URL is deliberately ignored.
    """
    def squash(text: str) -> str:
        text = (text or "").lower()
        text = re.sub(r"\b(pvt|private|ltd|limited|inc|llp|technologies|technology|"
                      r"solutions|services|india|labs|systems)\b", " ", text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    key = f"{squash(company)}|{squash(title)}"
    return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:16]   # a dedup key, not a secret


def upsert_job(job: dict) -> bool:
    """Store a job. Returns True if it was new, False if already known.

    An existing row keeps its status and application history; only the
    scoring and the description are refreshed.
    """
    with _lock:
        conn = connect()
        try:
            existing = conn.execute("SELECT job_id FROM jobs WHERE job_id = ?",
                                    (job["job_id"],)).fetchone()
            if existing:
                # A row stored before these fields existed gets them filled
                # in the first time a board sends them; a row that has them
                # keeps what it has, because a posting's date never changes.
                conn.execute("""
                    UPDATE jobs SET match_score = ?, score_breakdown = ?,
                        skills_required = ?, skills_matched = ?, skills_missing = ?,
                        skills_partial = ?,
                        why = ?, description = COALESCE(NULLIF(?, ''), description),
                        posted_at = COALESCE(NULLIF(posted_at, ''), ?),
                        employment_type = COALESCE(NULLIF(employment_type, ''), ?),
                        seniority = COALESCE(NULLIF(seniority, ''), ?),
                        city = COALESCE(NULLIF(city, ''), ?),
                        country = COALESCE(NULLIF(country, ''), ?)
                    WHERE job_id = ?""",
                    (job.get("match_score", 0), json.dumps(job.get("score_breakdown", {})),
                     json.dumps(job.get("skills_required", [])),
                     json.dumps(job.get("skills_matched", [])),
                     json.dumps(job.get("skills_missing", [])),
                     json.dumps(job.get("skills_partial", [])),
                     job.get("why", ""), job.get("description", ""),
                     job.get("posted_at", ""), job.get("employment_type", ""),
                     job.get("seniority", ""), job.get("city", ""), job.get("country", ""),
                     job["job_id"]))
                conn.commit()
                return False

            conn.execute("""
                INSERT INTO jobs (job_id, company, title, location, work_mode, salary,
                    platform, url, description, match_score, score_breakdown,
                    skills_required, skills_matched, skills_missing, skills_partial, why,
                    discovered_at, status,
                    posted_at, employment_type, seniority, city, country)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job["job_id"], job["company"], job["title"], job.get("location", ""),
                 job.get("work_mode", ""), job.get("salary", ""), job.get("platform", ""),
                 job.get("url", ""), job.get("description", ""), job.get("match_score", 0),
                 json.dumps(job.get("score_breakdown", {})),
                 json.dumps(job.get("skills_required", [])),
                 json.dumps(job.get("skills_matched", [])),
                 json.dumps(job.get("skills_missing", [])),
                 json.dumps(job.get("skills_partial", [])),
                 job.get("why", ""), _now(), "FOUND",
                 job.get("posted_at", ""), job.get("employment_type", ""),
                 job.get("seniority", ""), job.get("city", ""), job.get("country", "")))
            conn.commit()
            return True
        finally:
            conn.close()


def _row_to_job(row: sqlite3.Row) -> dict:
    job = dict(row)
    for field in ("skills_required", "skills_matched", "skills_missing", "skills_partial",
                  "score_breakdown"):
        try:
            job[field] = json.loads(job[field] or ("{}" if field == "score_breakdown" else "[]"))
        except json.JSONDecodeError:
            job[field] = {} if field == "score_breakdown" else []
    return job


def top_jobs(limit: int = 10, min_score: int = 0, status: str | None = None,
             max_age_days: int = 0) -> list[dict]:
    """The stored jobs, best match first.

    `max_age_days` keeps only postings that recent. A job with no posting
    date is kept either way: not knowing when it went up is not evidence
    that it is old, and dropping it would hide real work.
    """
    conn = connect()
    try:
        sql = "SELECT * FROM jobs WHERE match_score >= ?"
        params: list[Any] = [min_score]
        if status:
            sql += " AND status = ?"
            params.append(status)
        if max_age_days > 0:
            cutoff = (datetime.date.today()
                      - datetime.timedelta(days=max_age_days)).isoformat()
            sql += " AND (posted_at IS NULL OR posted_at = '' OR posted_at >= ?)"
            params.append(cutoff)
        sql += " ORDER BY match_score DESC, discovered_at DESC LIMIT ?"
        params.append(limit)
        return [_row_to_job(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def get_job(job_id: str) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None
    finally:
        conn.close()


def by_reference(reference: str) -> dict | None:
    """ "id:<job id>" names one stored job exactly — what the window's buttons
    send, so a click acts on the card it was on and not on another posting
    from the same company. Returns None for anything else; the tools'
    looser forms (a rank, part of a name) are theirs to resolve."""
    reference = (reference or "").strip()
    if not reference.startswith("id:"):
        return None
    return get_job(reference[3:].strip())


def _event(conn: sqlite3.Connection, job_id: str, kind: str, from_status: str = "",
           to_status: str = "", source: str = "", note: str = "", evidence: str = "") -> None:
    conn.execute("""INSERT INTO job_events (job_id, at, kind, from_status, to_status, source,
                    note, evidence) VALUES (?,?,?,?,?,?,?,?)""",
                 (job_id, _now(), kind, from_status, to_status, source, note, evidence))


def record_event(job_id: str, kind: str, source: str = "", note: str = "") -> None:
    """Something that happened to a job without changing its status — its
    analysis looked at, a Prepare that couldn't open it."""
    with _lock:
        conn = connect()
        try:
            _event(conn, job_id, kind, source=source, note=note)
            conn.commit()
        finally:
            conn.close()


def set_status(job_id: str, status: str) -> bool:
    """Set a status directly, for code that has already decided (and tests).
    Accepts the old names. Never SUBMITTED: that takes proof, through
    change_status. The change goes into the job's history either way."""
    status = status_name(status)
    if not status or status == "SUBMITTED":
        return False
    with _lock:
        conn = connect()
        try:
            row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return False
            conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))
            if row["status"] != status:
                _event(conn, job_id, "status", row["status"], status, source="set")
            conn.commit()
            return True
        finally:
            conn.close()


def change_status(job_id: str, status: str, source: str = "", note: str = "",
                  evidence: str = "") -> tuple[bool, str]:
    """Move a job to a new status if that's a move it can make. Returns
    (moved, why not). SUBMITTED needs evidence, and only follows a prepared
    or applied job."""
    wanted = status_name(status)
    if not wanted:
        return False, f"Status must be one of: {', '.join(s.lower() for s in STATUSES)}."
    if wanted == "SUBMITTED" and not str(evidence or "").strip():
        return False, ("Submitted means the submission was verified, and I have no proof of it. "
                       "Check the confirmation page, or give me the confirmation number.")
    with _lock:
        conn = connect()
        try:
            row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return False, "I can't find that job any more."
            now = row["status"]
            if now == wanted and wanted != "INTERVIEW":
                return False, f"It's already {WORDS[wanted]}."
            if wanted not in TRANSITIONS.get(now, set()):
                return False, (f"It can't go from {WORDS.get(now, now.lower())} to {WORDS[wanted]}"
                               + (": it has ended." if not TRANSITIONS.get(now) else "."))
            conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (wanted, job_id))
            _event(conn, job_id, "status", now, wanted, source=source, note=note, evidence=evidence)
            conn.commit()
            return True, ""
        finally:
            conn.close()


def history(job_id: str, limit: int = 50) -> list[dict]:
    """A job's timeline, oldest first: when it was found, then every change
    and event, with where each came from."""
    conn = connect()
    try:
        job = conn.execute("SELECT discovered_at, platform FROM jobs WHERE job_id = ?",
                           (job_id,)).fetchone()
        if not job:
            return []
        events = [dict(r) for r in conn.execute(
            "SELECT at, kind, from_status, to_status, source, note, evidence FROM job_events "
            "WHERE job_id = ? ORDER BY id DESC LIMIT ?", (job_id, limit))][::-1]
        found = {"at": job["discovered_at"], "kind": "found", "from_status": "", "to_status": "FOUND",
                 "source": job["platform"] or "", "note": "", "evidence": ""}
        return [found] + events
    finally:
        conn.close()


def record_application(job_id: str, status: str, source: str = "",
                       notes: str = "", confirmation_id: str = "") -> int:
    """A row here means an application was really attempted. USER_APPROVED
    is your word that you submitted it; APPLICATION_FAILED is a Prepare that
    couldn't open the posting, which changes no status. SUBMITTED is never
    written here — change_status does that, with proof."""
    status = "USER_APPROVED" if status == "APPLIED" else status
    if status not in ("USER_APPROVED", "APPLICATION_FAILED"):
        raise ValueError(f"not an application record: {status}")
    with _lock:
        conn = connect()
        try:
            cursor = conn.execute("""
                INSERT INTO applications (job_id, applied_at, resume_version, status,
                    source, confirmation_id, notes)
                VALUES (?,?,?,?,?,?,?)""",
                (job_id, _now() if status == "USER_APPROVED" else None,
                 _resume_version(), status, source, confirmation_id, notes))
            if status == "USER_APPROVED":
                row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
                conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))
                _event(conn, job_id, "status", row["status"] if row else "", status,
                       source="you", note=notes)
            else:
                _event(conn, job_id, "prepare_failed", source=source, note=notes)
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()


def record_submission(job_id: str, evidence: str, confirmation_id: str = "") -> None:
    """The proof that an application went in, on its application record
    (made now if you never said you applied)."""
    with _lock:
        conn = connect()
        try:
            row = conn.execute("""SELECT application_id FROM applications WHERE job_id = ?
                                  AND status IN ('USER_APPROVED', 'SUBMITTED')
                                  ORDER BY application_id DESC LIMIT 1""", (job_id,)).fetchone()
            if row:
                conn.execute("""UPDATE applications SET status = 'SUBMITTED',
                                confirmation_id = COALESCE(NULLIF(?, ''), confirmation_id),
                                notes = ? WHERE application_id = ?""",
                             (confirmation_id, evidence, row["application_id"]))
            else:
                conn.execute("""INSERT INTO applications (job_id, applied_at, resume_version,
                                status, source, confirmation_id, notes) VALUES (?,?,?,?,?,?,?)""",
                             (job_id, _now(), _resume_version(), "SUBMITTED", "verified",
                              confirmation_id, evidence))
            conn.commit()
        finally:
            conn.close()


def _resume_version() -> str:
    from .resume import PROFILE_PATH
    if not PROFILE_PATH.exists():
        return "none"
    stamp = datetime.datetime.fromtimestamp(PROFILE_PATH.stat().st_mtime)
    return stamp.strftime("%Y%m%d-%H%M")


def already_applied(job_id: str) -> bool:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM applications WHERE job_id = ? AND status IN "
            "('USER_APPROVED', 'SUBMITTED', 'APPLIED') LIMIT 1", (job_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


def applications(limit: int = 50) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute("""
            SELECT a.*, j.company, j.title, j.platform, j.url, j.match_score, j.location
            FROM applications a JOIN jobs j ON j.job_id = a.job_id
            ORDER BY a.application_id DESC LIMIT ?""", (limit,))]
    finally:
        conn.close()


def audit(action: str, platform: str = "", company: str = "", job: str = "",
          result: str = "", error: str = "", application_id: int | None = None) -> None:
    """Every action leaves a trace, successful or not."""
    try:
        with _lock:
            conn = connect()
            try:
                conn.execute("""INSERT INTO audit (timestamp, action, platform, company,
                                job, result, error, application_id) VALUES (?,?,?,?,?,?,?,?)""",
                             (_now(), action, platform, company, job, result, error, application_id))
                conn.commit()
            finally:
                conn.close()
    except Exception as e:  # noqa: BLE001  (logging must never break the task)
        log(f"audit write failed: {e}")


def audit_trail(limit: int = 60) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        conn.close()


def counts() -> dict:
    """The numbers the dashboard shows. All read, none estimated."""
    conn = connect()
    try:
        def scalar(sql: str, params: tuple = ()) -> int:
            return conn.execute(sql, params).fetchone()[0] or 0

        today = datetime.date.today().isoformat()
        by_status = {row["status"]: row["n"] for row in conn.execute(
            "SELECT status, COUNT(*) n FROM jobs GROUP BY status")}

        attempts = scalar("SELECT COUNT(*) FROM applications")
        applied = scalar("SELECT COUNT(*) FROM applications WHERE status IN "
                         "('USER_APPROVED', 'SUBMITTED')")
        submitted = scalar("SELECT COUNT(*) FROM applications WHERE status = 'SUBMITTED'")
        interviews = scalar("SELECT COUNT(*) FROM jobs WHERE status = 'INTERVIEW'")
        offers = scalar("SELECT COUNT(*) FROM jobs WHERE status = 'OFFER'")

        return {
            "jobs_total": scalar("SELECT COUNT(*) FROM jobs"),
            "jobs_today": scalar("SELECT COUNT(*) FROM jobs WHERE discovered_at LIKE ?",
                                 (f"{today}%",)),
            "by_status": by_status,
            # Every status, in order, zero included: the pipeline as it stands.
            "pipeline": {status: by_status.get(status, 0) for status in STATUSES},
            "attempts": attempts,
            "applied": applied,                 # your word or verified
            "submitted": submitted,             # verified only
            "failed": scalar("SELECT COUNT(*) FROM applications WHERE status = 'APPLICATION_FAILED'"),
            "needs_action": by_status.get("PREPARED", 0),   # filled in, waiting for you to submit
            "interviews": interviews,
            "offers": offers,
            "rejected": by_status.get("REJECTED", 0),
            "success_rate": round(applied / attempts * 100) if attempts else 0,
            "interview_rate": round(interviews / applied * 100) if applied else 0,
            "offer_rate": round(offers / applied * 100) if applied else 0,
            "avg_score": round(conn.execute(
                "SELECT AVG(match_score) FROM jobs").fetchone()[0] or 0),
            "by_platform": {r["platform"] or "unknown": r["n"] for r in conn.execute(
                "SELECT platform, COUNT(*) n FROM jobs GROUP BY platform ORDER BY n DESC")},
            "by_location": {r["location"] or "unknown": r["n"] for r in conn.execute(
                """SELECT location, COUNT(*) n FROM jobs GROUP BY location
                   ORDER BY n DESC LIMIT 8""")},
        }
    finally:
        conn.close()


def missing_skill_counts(limit: int = 12) -> list[tuple[str, int]]:
    """Which skills keep coming up in jobs that the resume doesn't have.
    This is the most useful thing the database knows."""
    conn = connect()
    try:
        tally: dict[str, int] = {}
        for row in conn.execute("SELECT skills_missing FROM jobs"):
            try:
                for skill in json.loads(row[0] or "[]"):
                    tally[skill] = tally.get(skill, 0) + 1
            except json.JSONDecodeError:
                continue
        return sorted(tally.items(), key=lambda kv: -kv[1])[:limit]
    finally:
        conn.close()
