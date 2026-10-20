"""Chapter 36 — LITTLE speaking up, rarely, and only to suggest.

A suggestion comes from what's already on this computer, is raised once,
at most one an hour and four a day, can be turned off (all of them or one
kind), is spoken only when asked for and never in quiet hours — and never
does anything itself.
"""
from __future__ import annotations

import datetime
import threading

import pytest

from jarvis.ai import planner
from jarvis.app import proactive, settings
from jarvis.jobs import store
from jarvis.routing.router import fast_route
from jarvis.tools import registry

NOW = datetime.datetime(2026, 9, 28, 11, 0, 0)
_REAL_DISK = proactive._disk


def _job(company, title, score=80, status="FOUND", found_hours_ago=2):
    job = {"job_id": store.job_id_for(company, title), "company": company, "title": title, "location": "Remote",
           "url": f"https://{company.lower()}.example/job", "platform": "adzuna", "match_score": score,
           "description": "Python."}
    store.upsert_job(job)
    conn = store.connect()
    conn.execute("UPDATE jobs SET discovered_at = ?, status = ? WHERE job_id = ?",
                 ((NOW - datetime.timedelta(hours=found_hours_ago)).isoformat(timespec="seconds"), status,
                  job["job_id"]))
    conn.commit()
    conn.close()
    return job["job_id"]


def _applied(jid, days_ago, status="USER_APPROVED"):
    store.record_application(jid, "USER_APPROVED")
    conn = store.connect()
    conn.execute("UPDATE applications SET applied_at = ? WHERE job_id = ?",
                 ((NOW - datetime.timedelta(days=days_ago)).isoformat(timespec="seconds"), jid))
    conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, jid))
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    planner._resumable = None
    monkeypatch.delenv("JARVIS_PROACTIVE", raising=False)
    monkeypatch.delenv("JARVIS_PROACTIVE_SPEAK", raising=False)
    monkeypatch.delenv("JARVIS_QUIET_HOURS", raising=False)
    monkeypatch.setattr(proactive, "_disk", lambda now: [])
    yield
    planner._resumable = None
    proactive.stop()


def kinds(found):
    return [c["kind"] for c in found]


# ============================================================ what's found

class TestWhatIsWorthMentioning:
    def test_nothing_is_nothing(self):
        assert proactive.candidates(NOW) == []

    def test_new_good_matches_from_the_last_day(self):
        _job("Acme", "Backend Intern", score=86)
        _job("Beta", "Data Intern", score=72)
        _job("Old", "Dev", score=90, found_hours_ago=30)
        _job("Weak", "Dev", score=50)
        _job("Seen", "Dev", score=95, status="SAVED")
        (found,) = proactive.candidates(NOW)
        assert found["text"] == ("2 new jobs match you at 70% or more since yesterday — the best is Backend Intern at "
                                 "Acme (86%). Say: show new jobs.")
        assert found["key"] == "new_matches:2026-09-28"

    def test_an_application_with_no_answer_after_a_week(self):
        _applied(_job("Acme", "Backend Intern", found_hours_ago=300), days_ago=10)
        _applied(_job("Beta", "Data Intern", found_hours_ago=300), days_ago=10, status="SUBMITTED")
        _applied(_job("Gamma", "ML Intern", found_hours_ago=300), days_ago=10, status="INTERVIEW")
        _applied(_job("Delta", "QA Intern", found_hours_ago=300), days_ago=3)
        found = proactive.candidates(NOW)
        texts = sorted(c["text"] for c in found if c["kind"] == "follow_up")
        assert texts == ["It's been 10 days since you applied to Acme — Backend Intern, with no answer recorded. "
                         "If you've heard back, say: mark Acme interview — or rejected.",
                         "It's been 10 days since you applied to Beta — Data Intern, with no answer recorded. "
                         "If you've heard back, say: mark Beta interview — or rejected."]
        verify = [c["key"] for c in found if c["kind"] == "verify"]
        assert sorted(verify) == sorted([f"verify:{store.job_id_for('Acme', 'Backend Intern')}",
                                         f"verify:{store.job_id_for('Delta', 'QA Intern')}"]), "not the verified one"

    def test_a_stopped_plan_comes_first(self):
        _job("Acme", "Backend Intern")
        planner._resumable = {"command": "set up the api", "understood": "", "steps": [{"do": "a"}] * 3, "at": 2,
                              "when": planner.time.monotonic()}
        found = proactive.candidates(NOW)
        assert kinds(found) == ["plan", "new_matches"]
        assert found[0]["text"] == "“set up the api” stopped at step 2 of 3. Say continue to pick it up."

    def test_a_nearly_full_disk(self, monkeypatch):
        import types
        import psutil
        monkeypatch.setattr(proactive, "_disk", _REAL_DISK)
        monkeypatch.setattr(psutil, "disk_usage", lambda _p: types.SimpleNamespace(free=1.2e9))
        assert [c["text"] for c in proactive.candidates(NOW)] == [
            "Only 1.2 GB is free on the disk. Downloads and the browser may start failing."]
        monkeypatch.setattr(psutil, "disk_usage", lambda _p: types.SimpleNamespace(free=50e9))
        assert proactive.candidates(NOW) == []

    def test_looking_changes_nothing_and_runs_nothing(self, monkeypatch):
        jid = _job("Acme", "Backend Intern")
        _applied(_job("Beta", "Data Intern", found_hours_ago=300), days_ago=10)
        monkeypatch.setattr(registry, "execute_tool", lambda *_a: pytest.fail("a tool ran"))
        before = (store.counts(), store.get_job(jid)["status"], len(store.history(jid)))
        proactive.candidates(NOW)
        proactive.due(NOW)
        assert (store.counts(), store.get_job(jid)["status"], len(store.history(jid))) == before

    def test_a_broken_look_is_skipped(self, monkeypatch):
        monkeypatch.setattr(proactive, "_new_matches", lambda now: 1 / 0)
        planner._resumable = {"command": "x", "understood": "", "steps": [{"do": "a"}] * 2, "at": 2,
                              "when": planner.time.monotonic()}
        assert kinds(proactive.candidates(NOW)) == ["plan"]


# ============================================================ not a nuisance

class TestNotANuisance:
    @pytest.fixture
    def plenty(self):
        for i in range(8):
            _applied(_job(f"Co{i}", "Intern", found_hours_ago=300), days_ago=10, status="SUBMITTED")

    def test_one_at_a_time_and_an_hour_apart(self, plenty):
        first = proactive.due(NOW)
        assert first and proactive.due(NOW + datetime.timedelta(minutes=59)) is None
        second = proactive.due(NOW + datetime.timedelta(minutes=61))
        assert second and second["key"] != first["key"], "each thing once"

    def test_four_a_day_at_most(self, plenty):
        said = [proactive.due(NOW + datetime.timedelta(hours=h)) for h in range(0, 12, 2) if NOW.hour + h < 24]
        assert len([s for s in said if s]) == 4
        assert proactive.due(NOW.replace(hour=23)) is None
        assert proactive.due(NOW + datetime.timedelta(days=1)) is not None, "a new day"

    def test_the_same_thing_is_never_raised_twice(self):
        _applied(_job("Acme", "Backend Intern", found_hours_ago=300), days_ago=10, status="SUBMITTED")
        assert proactive.due(NOW)["kind"] == "follow_up"
        assert proactive.due(NOW + datetime.timedelta(days=3)) is None

    def test_what_was_raised_is_forgotten_after_a_while(self):
        _applied(_job("Acme", "Backend Intern", found_hours_ago=300), days_ago=10, status="SUBMITTED")
        proactive.due(NOW)
        assert proactive.due(NOW + datetime.timedelta(days=proactive.REMEMBER_DAYS + 1)) is not None

    def test_off_means_off(self, plenty, monkeypatch):
        monkeypatch.setenv("JARVIS_PROACTIVE", "off")
        assert proactive.due(NOW) is None
        assert fast_route("turn on suggestions").startswith("Suggestions are on.")
        assert proactive.due(NOW) is not None, "what you say beats .env"
        assert fast_route("stop suggestions") == "Okay, no more suggestions. Say turn on suggestions to bring them back."
        assert proactive.due(NOW + datetime.timedelta(hours=2)) is None

    def test_one_kind_can_be_turned_off(self):
        _applied(_job("Acme", "Backend Intern", found_hours_ago=300), days_ago=10)
        assert fast_route("stop suggesting follow ups") == "Stopped: suggestions about follow ups."
        assert proactive.due(NOW)["kind"] == "verify"
        assert fast_route("stop suggesting about the weather").startswith("I don't make suggestions about the weather.")
        assert fast_route("start suggesting follow ups") == "Back on: suggestions about follow ups."


# =================================================================== saying

class TestSayingIt:
    @pytest.fixture
    def one(self):
        _applied(_job("Acme", "Backend Intern", found_hours_ago=300), days_ago=10, status="SUBMITTED")

    def test_shown_not_spoken_by_default(self, one):
        shown, spoken = [], []
        proactive.tick(shown.append, spoken.append, muted=lambda: False, now=NOW)
        assert len(shown) == 1 and spoken == []

    def test_spoken_only_when_asked_unmuted_and_not_in_quiet_hours(self, one, monkeypatch):
        monkeypatch.setenv("JARVIS_PROACTIVE_SPEAK", "on")
        spoken = []
        proactive.tick(lambda _t: None, spoken.append, muted=lambda: True, now=NOW)
        assert spoken == []
        proactive.stop()
        _applied(_job("Beta", "Data Intern", found_hours_ago=300), days_ago=10, status="SUBMITTED")
        proactive.tick(lambda _t: None, spoken.append, muted=lambda: False, now=NOW.replace(hour=23))
        assert spoken == []
        _applied(_job("Gamma", "ML Intern", found_hours_ago=300), days_ago=10, status="SUBMITTED")
        proactive.tick(lambda _t: None, spoken.append, muted=lambda: False, now=NOW + datetime.timedelta(days=1))
        assert len(spoken) == 1

    @pytest.mark.parametrize("raw,hour,quiet", [("22-8", 23, True), ("22-8", 7, True), ("22-8", 8, False),
                                                ("22-8", 12, False), ("13-15", 14, True), ("13-15", 15, False),
                                                ("nonsense", 23, True)])
    def test_quiet_hours(self, monkeypatch, raw, hour, quiet):
        monkeypatch.setenv("JARVIS_QUIET_HOURS", raw)
        assert proactive.quiet_now(NOW.replace(hour=hour)) is quiet

    def test_asking_shows_everything_now(self, one):
        proactive.due(NOW)
        said = fast_route("any suggestions?")
        assert said.startswith("It's been ") and "Beta" not in said
        fast_route("stop suggestions")
        assert fast_route("what needs my attention?").endswith("(Suggestions are off, so I won't bring these up myself.)")

    def test_nothing_to_say(self):
        assert fast_route("any suggestions") == "Nothing needs your attention right now."

    def test_the_loop_delivers_and_stops(self, one):
        shown, got = [], threading.Event()
        proactive.start(lambda t: shown.append(t) or got.set(), every=0.01)
        assert got.wait(5)
        proactive.stop()
        assert len(shown) == 1

    def test_the_system_section(self, monkeypatch):
        rows = {r["label"]: r for g in settings.groups() if g["id"] == "voice" for r in g["rows"]}
        assert rows["Suggestions"]["value"] == "on" and rows["Suggestions spoken"]["value"].startswith("no")
        fast_route("stop suggesting disk")
        rows = {r["label"]: r for g in settings.groups() if g["id"] == "voice" for r in g["rows"]}
        assert rows["Suggestions"]["value"] == "on, except disk"
