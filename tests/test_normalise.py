"""Six boards, six ways of saying the same thing.

The rule these tests hold to is that an unreadable field comes back empty
and never invented. A job with no posting date is still a job; a job with
today's date stamped on it because the parser gave up is a lie the user
would act on.
"""
from __future__ import annotations

import datetime

import pytest

from jarvis.jobs import normalise as n
from jarvis.jobs import store

TODAY = datetime.date.today()


def days_ago(days: int) -> str:
    return (TODAY - datetime.timedelta(days=days)).isoformat()


# ------------------------------------------------------------------ dates

@pytest.mark.parametrize("sent,expected", [
    ("2026-09-20T10:30:00Z", "2026-09-20"),          # Adzuna
    ("2026-09-20T10:30:00", "2026-09-20"),           # Remotive
    ("2026-09-20 10:30:00", "2026-09-20"),
    ("2026-09-20", "2026-09-20"),
    ("Mon, 15 Sep 2026 08:00:00 +0530", "2026-09-15"),   # Jobicy, out of RSS
    ("2026-09-20T10:30:00+05:30", "2026-09-20"),
    ("20 Sep 2026", "2026-09-20"),
])
def test_every_board_s_date_format_is_understood(sent, expected):
    assert n.parse_date(sent) == expected


def test_a_unix_epoch_is_understood():
    """RemoteOK sends seconds since 1970, sometimes as a string."""
    epoch = int(datetime.datetime(2026, 9, 20, tzinfo=datetime.timezone.utc).timestamp())
    assert n.parse_date(epoch) == "2026-09-20"
    assert n.parse_date(str(epoch)) == "2026-09-20"
    assert n.parse_date(epoch * 1000) == "2026-09-20"       # milliseconds


@pytest.mark.parametrize("junk", ["", None, "rubbish", "soon", 0, -1, 99, [], {}, "2026-13-45"])
def test_an_unreadable_date_is_empty_not_today(junk):
    """The failure that matters: a parser that gives up and stamps the job
    with today's date makes every stale posting look fresh."""
    assert n.parse_date(junk) == ""


def test_a_nonsense_epoch_is_rejected_rather_than_accepted():
    assert n.parse_date(5) == ""                     # 1970, not a job posting
    assert n.parse_date(99_999_999_999_999_999) == ""


# ------------------------------------------------------------------- age

@pytest.mark.parametrize("days,phrase", [
    (0, "today"), (1, "yesterday"), (3, "3 days ago"),
    (8, "last week"), (21, "3 weeks ago"), (75, "2 months ago"),
])
def test_age_is_said_the_way_a_person_would_say_it(days, phrase):
    assert n.age_phrase(days_ago(days)) == phrase


def test_no_date_means_no_age_rather_than_a_guess():
    assert n.age_phrase("") == ""
    assert n.days_since("") is None


def test_a_future_date_does_not_go_negative():
    assert n.days_since((TODAY + datetime.timedelta(days=5)).isoformat()) == 0


def test_stale_is_about_age_not_about_missing_information():
    """Not knowing when something was posted is not the same as knowing it
    is old, and a job with no date must not be quietly written off."""
    assert n.is_stale(days_ago(n.STALE_DAYS + 1)) is True
    assert n.is_stale(days_ago(3)) is False
    assert n.is_stale("") is False


# -------------------------------------------------------- employment type

@pytest.mark.parametrize("declared,expected", [
    ("FULL_TIME", "full-time"), ("full time", "full-time"), ("Permanent", "full-time"),
    ("part_time", "part-time"), ("Contract", "contract"), ("freelance", "contract"),
    ("Internship", "internship"), ("temp", "temporary"),
])
def test_a_board_s_own_type_field_is_taken_at_its_word(declared, expected):
    assert n.employment_type(declared) == expected


@pytest.mark.parametrize("title,expected", [
    ("Software Engineering Intern", "internship"),
    ("Summer Analyst", "internship"),
    ("Backend Developer (Contract)", "contract"),
    ("Part-time Data Entry", "part-time"),
    ("Full Time Python Developer", "full-time"),
])
def test_the_title_is_read_when_the_board_has_no_field(title, expected):
    assert n.employment_type("", title) == expected


def test_an_internship_is_not_called_full_time():
    """Half the boards that list internships describe them as full-time,
    which is true of the hours and useless to someone filtering."""
    assert n.employment_type("full_time", "Software Engineering Intern") == "full-time"
    assert n.employment_type("", "Full Time Software Engineering Intern") == "internship"


def test_tags_count_as_a_declaration():
    """RemoteOK has no type field; it puts the type among its tags."""
    assert n.employment_type("dev python full-time remote") == "full-time"


def test_nothing_stated_means_nothing_claimed():
    assert n.employment_type("", "Software Engineer", "We are hiring engineers.") == ""


def test_the_description_is_the_last_resort_not_the_first():
    assert n.employment_type("", "Backend Developer",
                             "This is a 6 month contract role.") == "contract"


# ------------------------------------------------------------- seniority

@pytest.mark.parametrize("title,expected", [
    ("Senior Software Engineer", "senior"),
    ("Sr. Backend Developer", "senior"),
    ("SDE 2", "senior"),
    ("Junior Python Developer", "junior"),
    ("Graduate Software Engineer", "junior"),
    ("Entry-Level Analyst", "junior"),
    ("Fresher Web Developer", "junior"),
    ("Software Engineering Intern", "intern"),
    ("Engineering Manager", "lead"),
    ("Principal Architect", "lead"),
    ("Head of Engineering", "lead"),
])
def test_seniority_is_read_from_the_title(title, expected):
    assert n.seniority(title) == expected


def test_an_unlabelled_title_stays_unlabelled():
    """"Software Engineer" genuinely does not say a level, and calling it
    mid-level would be inventing a fact the posting never stated."""
    assert n.seniority("Software Engineer") == ""


def test_the_description_does_not_promote_a_junior_role():
    """Half the junior postings ever written say "work with senior
    engineers" somewhere in the blurb."""
    assert n.seniority("Junior Developer",
                       "You will work alongside senior engineers.") == "junior"
    assert n.seniority("Software Engineer",
                       "You will work alongside senior engineers.") == ""


# -------------------------------------------------------------- location

@pytest.mark.parametrize("text,city,country", [
    ("Bengaluru, India", "Bengaluru", "India"),
    ("New York, United States", "New York", "United States"),
    ("Remote (India Only)", "", "India"),
    ("Remote - India", "", "India"),
    ("Worldwide", "", "Worldwide"),
    ("Anywhere", "", "Worldwide"),
    ("Prayagraj", "Prayagraj", "India"),
    ("Gurgaon", "Gurgaon", "India"),
    ("Berlin", "Berlin", ""),
    ("", "", ""),
])
def test_a_location_is_split_into_what_it_actually_says(text, city, country):
    assert n.split_location(text) == (city, country)


def test_a_country_on_its_own_is_not_treated_as_a_city():
    assert n.split_location("India") == ("", "India")
    assert n.split_location("USA") == ("", "United States")


def test_an_indian_city_implies_india_and_nothing_else_is_inferred():
    """No other country has a Bengaluru, so that inference is safe. Berlin
    gets no country, because guessing Germany from a city list JARVIS
    doesn't have would be a coin flip."""
    assert n.split_location("Hyderabad")[1] == "India"
    assert n.split_location("Berlin")[1] == ""


# ---------------------------------------------------- the stored shape

def test_a_job_carries_every_field_the_spec_asks_for():
    from jarvis.jobs import sources
    job = sources._job(
        company="Acme", title="Senior Backend Engineer", location="Bengaluru, India",
        url="https://example.com/1", description="A contract role building APIs.",
        platform="adzuna", salary="12 LPA",
        posted="2026-09-20T10:00:00Z", job_type="contract")

    for field in ("title", "company", "location", "work_mode", "employment_type",
                  "salary", "platform", "url", "posted_at", "seniority",
                  "city", "country"):
        assert field in job, f"{field} missing from a normalised job"
    assert job["posted_at"] == "2026-09-20"
    assert job["employment_type"] == "contract"
    assert job["seniority"] == "senior"
    assert (job["city"], job["country"]) == ("Bengaluru", "India")


def test_a_board_that_sends_no_date_still_produces_a_job():
    from jarvis.jobs import sources
    job = sources._job(company="Acme", title="Engineer", location="Remote",
                       url="https://example.com/2", description="",
                       platform="arbeitnow")
    assert job["job_id"] and job["posted_at"] == ""


# ------------------------------------------------------------ migration

def test_a_database_from_before_this_chapter_keeps_its_rows(tmp_path, monkeypatch):
    """The one that matters: there are real applications in jobs.db, and a
    migration that loses them is worse than no migration."""
    import sqlite3

    db = tmp_path / "old.db"
    old = sqlite3.connect(db)
    old.executescript("""
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL,
            location TEXT, work_mode TEXT, salary TEXT, platform TEXT, url TEXT,
            description TEXT, match_score INTEGER DEFAULT 0, score_breakdown TEXT,
            skills_required TEXT, skills_matched TEXT, skills_missing TEXT, why TEXT,
            discovered_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'FOUND');
    """)
    old.execute("INSERT INTO jobs (job_id, company, title, discovered_at, status, "
                "match_score) VALUES ('keep-me', 'Old Co', 'Engineer', '2026-01-01', "
                "'APPLIED', 88)")
    old.commit()
    old.close()

    monkeypatch.setattr(store, "DB_PATH", db)
    conn = store.connect()
    try:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
        row = conn.execute("SELECT * FROM jobs WHERE job_id = 'keep-me'").fetchone()
    finally:
        conn.close()

    assert set(store.ADDED_COLUMNS) <= columns
    assert row["company"] == "Old Co"
    assert row["status"] == "USER_APPROVED"   # the application survived (APPLIED before Chapter 27)
    assert store.history("keep-me")[-1]["from_status"] == "APPLIED", "and its old name is kept"
    assert row["match_score"] == 88
    assert row["posted_at"] is None        # unknown, not invented


def test_migrating_twice_changes_nothing(tmp_path, monkeypatch):
    db = tmp_path / "twice.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    store.connect().close()
    conn = store.connect()
    try:
        assert store._migrate(conn) == []
    finally:
        conn.close()


def test_the_new_fields_survive_a_round_trip(tmp_path, monkeypatch):
    db = tmp_path / "round.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    job = {
        "job_id": "abc123", "company": "Acme", "title": "Backend Engineer",
        "location": "Bengaluru, India", "work_mode": "onsite", "salary": "",
        "platform": "adzuna", "url": "https://example.com", "description": "",
        "posted_at": "2026-09-20", "employment_type": "full-time",
        "seniority": "senior", "city": "Bengaluru", "country": "India",
    }
    assert store.upsert_job(job) is True
    stored = store.get_job("abc123")
    assert stored["posted_at"] == "2026-09-20"
    assert stored["employment_type"] == "full-time"
    assert stored["seniority"] == "senior"
    assert stored["country"] == "India"


def test_a_row_stored_before_the_date_existed_gets_one_later(tmp_path, monkeypatch):
    """A job found last week has no posting date. When a board sends it
    again with one, the gap should fill rather than stay empty forever."""
    db = tmp_path / "fill.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    bare = {"job_id": "fill1", "company": "Acme", "title": "Engineer"}
    store.upsert_job(bare)
    assert store.get_job("fill1")["posted_at"] in (None, "")

    store.upsert_job({**bare, "posted_at": "2026-09-20", "employment_type": "contract"})
    again = store.get_job("fill1")
    assert again["posted_at"] == "2026-09-20"
    assert again["employment_type"] == "contract"


def test_a_stored_posting_date_is_not_overwritten(tmp_path, monkeypatch):
    """A posting's date is a fact about the posting. A board re-listing it
    must not make it look newer than it is."""
    db = tmp_path / "keep.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    job = {"job_id": "keep1", "company": "Acme", "title": "Engineer",
           "posted_at": "2026-08-01"}
    store.upsert_job(job)
    store.upsert_job({**job, "posted_at": days_ago(0)})
    assert store.get_job("keep1")["posted_at"] == "2026-08-01"


# ------------------------------------------------------------- freshness

def test_asking_for_recent_jobs_leaves_out_the_old_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "fresh.db")
    base = {"company": "Acme", "title": "Engineer", "match_score": 80}
    store.upsert_job({**base, "job_id": "new", "posted_at": days_ago(2)})
    store.upsert_job({**base, "job_id": "old", "posted_at": days_ago(90)})

    recent = {j["job_id"] for j in store.top_jobs(limit=10, max_age_days=7)}
    assert recent == {"new"}
    assert len(store.top_jobs(limit=10)) == 2      # unfiltered still shows both


def test_a_job_with_no_date_is_not_filtered_out(tmp_path, monkeypatch):
    """Not knowing when it was posted is not evidence that it is old, and
    dropping it would hide real work from the person searching."""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "undated.db")
    store.upsert_job({"job_id": "undated", "company": "Acme", "title": "Engineer",
                      "match_score": 80})
    assert len(store.top_jobs(limit=10, max_age_days=7)) == 1


def test_the_listing_says_when_nothing_recent_turned_up(tmp_path, monkeypatch):
    from jarvis.jobs import engine
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "none.db")
    store.upsert_job({"job_id": "old", "company": "Acme", "title": "Engineer",
                      "match_score": 80, "posted_at": days_ago(90)})
    reply = engine.top_matches(max_age_days=7)
    assert "last 7 days" in reply


@pytest.mark.parametrize("said", [
    "show new jobs", "fresh jobs", "recent jobs", "latest jobs",
    "jobs posted this week", "show jobs posted in the last 3 days",
])
def test_freshness_is_askable_in_plain_words(said, tmp_path, monkeypatch):
    from jarvis.routing import router
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "route.db")
    reply = router.fast_route(said)
    assert reply is not None, f"{said!r} fell through to the model"


def test_the_listing_shows_age_type_and_source(tmp_path, monkeypatch):
    from jarvis.jobs import engine
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "shape.db")
    store.upsert_job({
        "job_id": "shape1", "company": "Acme", "title": "Backend Engineer",
        "location": "Bengaluru, India", "work_mode": "onsite", "platform": "adzuna",
        "match_score": 90, "posted_at": days_ago(3),
        "employment_type": "full-time", "seniority": "senior"})
    listing = engine.top_matches(1)
    assert "posted 3 days ago" in listing
    assert "via adzuna" in listing
    assert "full-time" in listing and "senior" in listing


def test_a_stale_posting_is_flagged_in_the_listing(tmp_path, monkeypatch):
    from jarvis.jobs import engine
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "stale.db")
    store.upsert_job({"job_id": "s1", "company": "Acme", "title": "Engineer",
                      "match_score": 90, "posted_at": days_ago(120)})
    assert "likely filled" in engine.top_matches(1)


def test_an_undated_job_says_so_rather_than_showing_a_blank(tmp_path, monkeypatch):
    from jarvis.jobs import engine
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "blank.db")
    store.upsert_job({"job_id": "b1", "company": "Acme", "title": "Engineer",
                      "match_score": 90})
    assert "no date given" in engine.top_matches(1)


# ------------------------------------------------------- searching at once

def test_the_six_boards_are_asked_at_once_not_one_after_another(monkeypatch):
    """Six boards queued behind each other at 15 seconds apiece is ninety
    seconds of a voice assistant saying nothing. They don't depend on one
    another, so they have no reason to queue."""
    import threading
    import time

    from jarvis.jobs import sources

    running, peak = [0], [0]
    lock = threading.Lock()

    def slow(*_args, **_kwargs):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.15)
        with lock:
            running[0] -= 1
        return []

    monkeypatch.setattr(sources, "SOURCES", {f"board{i}": slow for i in range(6)})
    monkeypatch.setattr(sources, "NEEDS_LOCATION", set())

    started = time.time()
    jobs, notes = sources.search("python")
    elapsed = time.time() - started

    assert peak[0] == 6, f"only {peak[0]} board(s) were asked at the same time"
    assert elapsed < 0.6, f"took {elapsed:.2f}s — that is one at a time"
    assert len(notes) == 6


def test_one_board_failing_does_not_take_the_others_down(monkeypatch):
    from jarvis.jobs import sources

    def broken(*_a, **_k):
        raise RuntimeError("board is down")

    def fine(*_a, **_k):
        return [sources._job("Acme", "Engineer", "Remote", "https://x", "", "fine")]

    monkeypatch.setattr(sources, "SOURCES", {"broken": broken, "fine": fine})
    monkeypatch.setattr(sources, "NEEDS_LOCATION", set())
    jobs, notes = sources.search("python")
    assert len(jobs) == 1
    assert "broken: failed" in notes


def test_the_sources_are_reported_in_a_fixed_order(monkeypatch):
    """Whichever board answers first, the same search should read the same
    way twice."""
    from jarvis.jobs import sources

    monkeypatch.setattr(sources, "SOURCES",
                        {"alpha": lambda *a, **k: [], "beta": lambda *a, **k: [],
                         "gamma": lambda *a, **k: []})
    monkeypatch.setattr(sources, "NEEDS_LOCATION", set())
    _, notes = sources.search("python")
    assert [n.split(":")[0] for n in notes] == ["alpha", "beta", "gamma"]


@pytest.mark.parametrize("said", [
    "find jobs for me", "search python jobs", "summarize this page",
    "look up react internships", "import contacts from contacts.csv",
])
def test_a_slow_command_is_announced_before_it_starts(said):
    """A command that goes to the network has to say so, or fifteen seconds
    of silence reads as broken."""
    from jarvis.app.assistant import SLOW_COMMANDS
    assert SLOW_COMMANDS.search(said), f"{said!r} would run silently"


@pytest.mark.parametrize("said", ["what is the time", "open chrome", "show my top matches"])
def test_an_instant_command_is_not_announced(said):
    from jarvis.app.assistant import SLOW_COMMANDS
    assert not SLOW_COMMANDS.search(said)


def test_a_board_that_never_answers_does_not_hold_up_the_search(monkeypatch):
    """Each request has its own timeout, but a hung DNS lookup gets past
    that. Five boards answering beats five minutes of silence."""
    import time

    from jarvis.jobs import sources

    def never(*_a, **_k):
        time.sleep(30)
        return []

    def quick(*_a, **_k):
        return [sources._job("Acme", "Engineer", "Remote", "https://x", "", "quick")]

    monkeypatch.setattr(sources, "SOURCES", {"never": never, "quick": quick})
    monkeypatch.setattr(sources, "NEEDS_LOCATION", set())
    monkeypatch.setattr(sources, "DEADLINE", 0.4)

    started = time.time()
    jobs, notes = sources.search("python")
    elapsed = time.time() - started

    assert elapsed < 3, f"waited {elapsed:.1f}s for a board that never answers"
    assert len(jobs) == 1, "the board that did answer was lost"
    assert "never: too slow, skipped" in notes
    assert "quick: 1" in notes
