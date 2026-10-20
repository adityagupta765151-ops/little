"""Chapter 27 — the job application tracker.

Ten statuses in order: FOUND, ANALYZED, SAVED, PREPARED, USER_APPROVED,
SUBMITTED, then INTERVIEW, OFFER, REJECTED, WITHDRAWN. Forward is free;
nothing goes back to before you applied; an ended job stays ended.

SUBMITTED is never written without proof: a confirmation page in LITTLE's
own browser that is about this job, or a confirmation number you give.
"I applied" is USER_APPROVED — your word, recorded as your word.

Every change goes into the job's history, which the card, the timeline
command and the dashboard counts all read. The old statuses are renamed
once, with a copy of the database made first and the old name kept.
"""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from jarvis.app import bridge, tasks
from jarvis.jobs import apply, engine, store
from jarvis.routing.router import fast_route
from jarvis.tools import browser, permissions
from jarvis.tools.registry import FUNCTIONS, TOOL_SCHEMAS

import _ui


def _job(company="Acme", title="Full Stack Developer", url="https://jobs.acme.example/fsd", score=80):
    job = {"job_id": store.job_id_for(company, title), "company": company, "title": title,
           "location": "Bangalore", "url": url, "platform": "adzuna", "match_score": score,
           "description": "React and Node.js."}
    store.upsert_job(job)
    return job["job_id"]


def _status(jid):
    return store.get_job(jid)["status"]


def _move(jid, *path):
    for status in path:
        assert store.set_status(jid, status), status


class Quiet:
    muted, running = False, False
    brain = None

    def handle(self, text): ...


@pytest.fixture(autouse=True)
def fresh():
    tasks.reset()
    yield
    tasks.reset()


@pytest.fixture
def page(monkeypatch):
    """The page open in LITTLE's browser, as the test says it is. Anything
    that would drive the browser fails the test."""
    shown = {"page": None}
    monkeypatch.setattr(browser, "current_page", lambda: shown["page"])
    for name in ("open_page", "click_text", "fill_field", "press_key"):
        monkeypatch.setattr(browser, name, lambda *_a, _n=name, **_k: pytest.fail(f"{_n} was called"))
    return shown


CONFIRMATION = {"url": "https://jobs.acme.example/fsd/thanks", "title": "Application received",
                "text": "Thank you for applying to Acme. We have received your application."}


# ============================================================ the statuses

class TestTheStatuses:
    def test_the_ten_in_order(self):
        assert store.STATUSES == ("FOUND", "ANALYZED", "SAVED", "PREPARED", "USER_APPROVED",
                                  "SUBMITTED", "REJECTED", "INTERVIEW", "OFFER", "WITHDRAWN")
        assert set(store.TRANSITIONS) == set(store.STATUSES)

    @pytest.mark.parametrize("word,name", [
        ("shortlisted", "SAVED"), ("SHORTLISTED", "SAVED"), ("ready to apply", "PREPARED"),
        ("NEEDS_USER_ACTION", "PREPARED"), ("applied", "USER_APPROVED"), ("saved", "SAVED"),
        ("user approved", "USER_APPROVED"), ("Interview", "INTERVIEW"), ("application failed", ""),
        ("pending", ""), ("", ""),
    ])
    def test_old_and_everyday_names(self, word, name):
        assert store.status_name(word) == name


class TestWhereAJobCanGo:
    @pytest.mark.parametrize("path", [
        ["ANALYZED", "SAVED", "PREPARED", "USER_APPROVED", "INTERVIEW", "OFFER", "WITHDRAWN"],
        ["SAVED", "FOUND"],                                   # unsave
        ["PREPARED", "SAVED"],                                # changed your mind before applying
        ["INTERVIEW"],                                        # a recruiter called about it
        ["USER_APPROVED", "REJECTED"],
        ["USER_APPROVED", "INTERVIEW", "INTERVIEW", "OFFER"],  # a second round
    ])
    def test_forward_moves(self, path):
        jid = _job()
        for status in path:
            moved, why = store.change_status(jid, status, source="test")
            assert moved, (status, why)
        assert _status(jid) == path[-1]

    @pytest.mark.parametrize("before,after,why", [
        (["USER_APPROVED"], "SAVED", "It can't go from applied (your word) to saved."),
        (["USER_APPROVED"], "PREPARED", "It can't go from applied (your word) to prepared."),
        (["INTERVIEW"], "FOUND", "It can't go from interview to found."),
        (["INTERVIEW", "OFFER"], "INTERVIEW", "It can't go from offer to interview."),
        (["REJECTED"], "INTERVIEW", "It can't go from rejected to interview: it has ended."),
        (["WITHDRAWN"], "SAVED", "It can't go from withdrawn to saved: it has ended."),
        (["SAVED"], "SAVED", "It's already saved."),
    ])
    def test_backward_and_ended_moves_are_refused_and_change_nothing(self, before, after, why):
        jid = _job()
        _move(jid, *before)
        events = len(store.history(jid))
        assert store.change_status(jid, after) == (False, why)
        assert _status(jid) == before[-1] and len(store.history(jid)) == events

    def test_an_unknown_status(self):
        moved, why = store.change_status(_job(), "pending")
        assert not moved and why.startswith("Status must be one of: found, analyzed, saved")

    def test_an_unknown_job(self):
        assert store.change_status("nope", "SAVED") == (False, "I can't find that job any more.")


class TestSubmittedNeedsProof:
    def test_never_without_evidence(self):
        jid = _job()
        _move(jid, "USER_APPROVED")
        moved, why = store.change_status(jid, "SUBMITTED")
        assert not moved and why.startswith("Submitted means the submission was verified")
        assert _status(jid) == "USER_APPROVED"

    def test_never_from_before_applying_even_with_evidence(self):
        jid = _job()
        moved, _ = store.change_status(jid, "SUBMITTED", evidence="a page said so")
        assert not moved and _status(jid) == "FOUND"

    def test_the_direct_setter_cannot_write_it(self):
        jid = _job()
        _move(jid, "USER_APPROVED")
        assert store.set_status(jid, "SUBMITTED") is False
        assert _status(jid) == "USER_APPROVED"

    def test_an_application_record_cannot_claim_it(self):
        with pytest.raises(ValueError):
            store.record_application(_job(), "SUBMITTED")

    def test_asking_for_it_by_status_explains_how(self):
        jid = _job()
        _move(jid, "USER_APPROVED")
        reply = apply.mark_status(f"id:{jid}", "submitted")
        assert reply.startswith("Submitted means the submission was verified.")
        assert "verify my application" in reply and "confirmation" in reply
        assert _status(jid) == "USER_APPROVED"


# ============================================================ applying

class TestSayingYouApplied:
    def test_it_is_your_word_not_a_verification(self):
        jid = _job()
        reply = apply.mark_applied(f"id:{jid}")
        assert reply.startswith("Recorded: applied to Full Stack Developer at Acme — on your word.")
        assert _status(jid) == "USER_APPROVED" and store.already_applied(jid)
        assert store.counts()["applied"] == 1 and store.counts()["submitted"] == 0
        last = store.history(jid)[-1]
        assert (last["from_status"], last["to_status"], last["source"]) == ("FOUND", "USER_APPROVED", "you")

    def test_once_only(self):
        jid = _job()
        apply.mark_applied(f"id:{jid}")
        assert apply.mark_applied(f"id:{jid}") == "That one is already recorded as applied."

    def test_not_for_a_job_that_has_ended(self):
        jid = _job()
        _move(jid, "REJECTED")
        assert apply.mark_applied(f"id:{jid}").endswith("so there's no application to record now.")
        assert not store.already_applied(jid)

    def test_applied_by_status_word_goes_the_same_way(self):
        jid = _job()
        assert apply.mark_status(f"id:{jid}", "applied").startswith("Recorded: applied to")
        assert _status(jid) == "USER_APPROVED"


class TestVerifyingASubmission:
    def test_with_the_confirmation_page_open(self, page):
        jid = _job()
        _move(jid, "PREPARED")
        page["page"] = CONFIRMATION
        reply = apply.verify_submission(f"id:{jid}")
        assert reply.startswith("Verified: Full Stack Developer at Acme is submitted")
        assert _status(jid) == "SUBMITTED"
        last = store.history(jid)[-1]
        assert last["source"] == "browser" and "jobs.acme.example/fsd/thanks" in last["evidence"]
        assert store.counts()["submitted"] == 1 and store.already_applied(jid)
        assert any(a["action"] == "verify" and a["result"] == "submitted (verified)"
                   for a in store.audit_trail())

    def test_without_a_page(self, page):
        jid = _job()
        _move(jid, "USER_APPROVED")
        reply = apply.verify_submission(f"id:{jid}")
        assert reply.startswith("No page is open in my browser")
        assert "mark Acme submitted with confirmation" in reply
        assert _status(jid) == "USER_APPROVED"

    def test_a_page_that_doesnt_confirm(self, page):
        jid = _job()
        _move(jid, "PREPARED")
        page["page"] = {"url": "https://jobs.acme.example/fsd", "title": "Apply", "text": "Full name Email Submit"}
        assert "it doesn't say the application was received" in apply.verify_submission(f"id:{jid}")
        assert _status(jid) == "PREPARED"

    def test_a_confirmation_for_some_other_job(self, page):
        jid = _job()
        _move(jid, "PREPARED")
        page["page"] = {"url": "https://careers.other.example/done", "title": "Done",
                        "text": "Thank you for applying to Globex."}
        assert "it doesn't mention this job or its company" in apply.verify_submission(f"id:{jid}")
        assert _status(jid) == "PREPARED"

    def test_only_after_preparing_or_applying(self, page):
        jid = _job()
        page["page"] = CONFIRMATION
        assert apply.verify_submission(f"id:{jid}").endswith("Prepare it or tell me you applied first.")
        assert _status(jid) == "FOUND"

    def test_with_a_confirmation_number(self):
        jid = _job()
        _move(jid, "USER_APPROVED")
        assert apply.mark_submitted(f"id:{jid}", "APP-2026-4411") == \
            "Recorded: Full Stack Developer at Acme is submitted, confirmation APP-2026-4411."
        assert _status(jid) == "SUBMITTED"
        record = [a for a in store.applications() if a["job_id"] == jid][0]
        assert record["status"] == "SUBMITTED" and record["confirmation_id"] == "APP-2026-4411"
        assert apply.mark_submitted(f"id:{jid}", "APP-2") .endswith("already verified as submitted.")

    @pytest.mark.parametrize("number", ["", "ok", "yes it went in", "<b>1234</b>"])
    def test_a_confirmation_number_must_look_like_one(self, number):
        jid = _job()
        _move(jid, "USER_APPROVED")
        assert apply.mark_submitted(f"id:{jid}", number).startswith("Give me the confirmation")
        assert _status(jid) == "USER_APPROVED"

    def test_a_number_for_a_job_you_never_applied_to(self):
        jid = _job()
        reply = apply.mark_submitted(f"id:{jid}", "APP-1234")
        assert reply.endswith("Tell me you applied first.") and _status(jid) == "FOUND"


class TestPreparing:
    @pytest.fixture
    def opened(self, monkeypatch):
        calls = {"filled": []}
        monkeypatch.setattr(browser, "open_page", lambda url: calls.setdefault("url", url) and "Opened Apply")
        monkeypatch.setattr(browser, "fill_field", lambda label, value: calls["filled"].append(label) or f"Filled {label}")
        monkeypatch.setattr(browser, "read_page", lambda *_a: "Full name Email Expected salary")
        from jarvis.jobs import resume
        resume.save_profile({"candidate": {"name": "A", "email": "a@b.co", "phone": "", "location": ""},
                             "preferences": {}})
        return calls

    def test_filled_is_prepared_with_what_it_asks_in_the_history(self, opened):
        jid = _job()
        apply.prepare_application(f"id:{jid}")
        assert _status(jid) == "PREPARED"
        last = store.history(jid)[-1]
        assert last["source"] == "prepare" and "filled 2 fields" in last["note"]
        assert "salary" in last["note"] and "yours to answer" in last["note"]
        assert store.counts()["needs_action"] == 1

    def test_a_posting_that_wont_open_changes_no_status(self, monkeypatch):
        monkeypatch.setattr(browser, "open_page", lambda url: "The page took too long to respond.")
        jid = _job()
        _move(jid, "SAVED")
        apply.prepare_application(f"id:{jid}")
        assert _status(jid) == "SAVED"
        assert store.history(jid)[-1]["kind"] == "prepare_failed"
        assert store.counts()["failed"] == 1

    def test_preparing_again_is_in_the_history(self, opened):
        jid = _job()
        apply.prepare_application(f"id:{jid}")
        apply.prepare_application(f"id:{jid}")
        assert _status(jid) == "PREPARED" and store.history(jid)[-1]["kind"] == "prepared"


class TestLookingAtTheAnalysis:
    def test_a_new_job_becomes_analyzed(self):
        jid = _job()
        assert "MATCH ANALYSIS" in engine.why_this_job(f"id:{jid}")
        assert _status(jid) == "ANALYZED"

    def test_a_saved_job_stays_saved_with_a_line_in_its_history(self):
        jid = _job()
        _move(jid, "SAVED")
        engine.why_this_job(f"id:{jid}")
        assert _status(jid) == "SAVED" and store.history(jid)[-1]["kind"] == "analyzed"


# ============================================================ the timeline

class TestTheTimeline:
    def test_it_reads_in_order_with_where_each_came_from(self, page):
        jid = _job()
        engine.why_this_job(f"id:{jid}")
        engine.shortlist(f"id:{jid}")
        apply.mark_applied(f"id:{jid}")
        page["page"] = CONFIRMATION
        apply.verify_submission(f"id:{jid}")
        text = engine.job_history(f"id:{jid}")
        lines = text.splitlines()
        assert lines[0] == "TIMELINE — Full Stack Developer at Acme"
        body = [l for l in lines[2:] if l.startswith("  ")]
        assert "found via adzuna" in body[0]
        assert "found → analyzed — you looked at its full analysis" in body[1]
        assert "analyzed → saved" in body[2]
        assert "saved → applied (your word)" in body[3]
        assert "applied (your word) → submitted (verified)" in body[4] and "confirmation page" in body[4]
        assert lines[-1] == "Now: submitted (verified)."

    @pytest.mark.parametrize("command", ["history of job 1", "show the timeline for acme",
                                         "job 1 history", "timeline of 1"])
    def test_said_any_way(self, command):
        _job()
        assert fast_route(command).startswith("TIMELINE — Full Stack Developer at Acme")

    def test_an_unknown_job(self):
        _job()
        assert engine.job_history("globex") == "I couldn't find a stored job matching 'globex'."

    def test_verify_and_confirmation_by_command(self, page):
        jid = _job()
        _move(jid, "PREPARED")
        page["page"] = CONFIRMATION
        assert fast_route("verify my application to 1").startswith("Verified:")
        other = _job("Globex", "Backend Developer", url="https://globex.example/be", score=10)
        _move(other, "USER_APPROVED")
        assert fast_route("mark globex submitted with confirmation GX-99812") == \
            "Recorded: Backend Developer at Globex is submitted, confirmation GX-99812."


class TestTheCounts:
    def test_every_status_counted_zero_included(self):
        _, b, c = _job("A"), _job("B"), _job("C")
        _move(b, "SAVED")
        _move(c, "PREPARED")
        pipeline = store.counts()["pipeline"]
        assert list(pipeline) == list(store.STATUSES)
        assert pipeline["FOUND"] == 1 and pipeline["SAVED"] == 1 and pipeline["PREPARED"] == 1
        assert pipeline["SUBMITTED"] == 0

    def test_applied_and_verified_are_told_apart(self):
        a, b = _job("A"), _job("B")
        apply.mark_applied(f"id:{a}")
        apply.mark_applied(f"id:{b}")
        apply.mark_submitted(f"id:{b}", "REF-7788")
        c = store.counts()
        assert (c["applied"], c["submitted"]) == (2, 1)
        text = engine.application_status()
        assert "applied (your word)" in text and "submitted (verified)" in text
        assert "confirmation REF-7788" in text
        assert "Where every stored job stands: applied (your word) 1, submitted (verified) 1" in text


# ============================================================ the old names

class TestTheOldStatusesAreRenamedOnce:
    @pytest.fixture
    def old_db(self, tmp_path, monkeypatch):
        db = tmp_path / "jobs.db"
        monkeypatch.setattr(store, "DB_PATH", db)
        conn = store.connect()                     # today's schema, empty
        for jid, status in [("a", "SHORTLISTED"), ("b", "READY_TO_APPLY"), ("c", "NEEDS_USER_ACTION"),
                            ("d", "APPLIED"), ("e", "APPLICATION_FAILED"), ("f", "INTERVIEW")]:
            conn.execute("INSERT INTO jobs (job_id, company, title, discovered_at, status) "
                         "VALUES (?, ?, 'Dev', '2026-01-01', ?)", (jid, f"Co {jid}", status))
        conn.execute("INSERT INTO applications (job_id, applied_at, status) VALUES ('d', '2026-01-02', 'APPLIED')")
        conn.commit()
        conn.close()
        return db

    def test_each_becomes_its_new_name_with_the_old_one_kept(self, old_db):
        conn = store.connect()
        try:
            got = dict(conn.execute("SELECT job_id, status FROM jobs").fetchall())
        finally:
            conn.close()
        assert got == {"a": "SAVED", "b": "PREPARED", "c": "PREPARED", "d": "USER_APPROVED",
                       "e": "FOUND", "f": "INTERVIEW"}
        assert store.history("a")[-1]["from_status"] == "SHORTLISTED"
        assert "Prepare couldn't open this posting" in store.history("e")[-1]["note"]
        assert store.already_applied("d")

    def test_a_copy_is_made_first_and_it_happens_once(self, old_db):
        store.connect().close()
        backup = old_db.with_name("jobs.before-chapter27.db")
        copy = sqlite3.connect(backup)
        try:
            assert dict(copy.execute("SELECT job_id, status FROM jobs").fetchall())["a"] == "SHORTLISTED"
        finally:
            copy.close()
        events = len(store.history("a"))
        store.connect().close()
        assert len(store.history("a")) == events, "nothing renamed twice"

    def test_the_old_names_still_work_as_words(self):
        jid = _job()
        assert store.set_status(jid, "SHORTLISTED") and _status(jid) == "SAVED"
        assert apply.mark_status(f"id:{jid}", "shortlisted") == \
            "Acme — Full Stack Developer: It's already saved."


# ============================================================ the window

class TestTheJobsSection:
    def test_each_card_carries_its_history_and_the_moves_it_can_make(self):
        a, b, c, d = _job("A"), _job("B"), _job("C"), _job("D")
        _move(b, "PREPARED")
        _move(c, "USER_APPROVED")
        _move(d, "REJECTED")
        jobs = {j["job_id"]: j for j in bridge.Api(assistant=Quiet()).jobs()["jobs"]}
        assert jobs[a]["next"] == ["applied", "interview", "offer", "rejected", "withdrawn"]
        assert jobs[b]["next"] == ["applied", "verify", "interview", "offer", "rejected", "withdrawn"]
        assert jobs[c]["next"] == ["verify", "interview", "offer", "rejected", "withdrawn"]
        assert jobs[d]["next"] == []
        assert [e["kind"] for e in jobs[b]["events"]] == ["found", "status"]

    def test_the_verify_button_runs_as_a_task_and_reads_the_page(self, page):
        jid = _job()
        _move(jid, "PREPARED")
        page["page"] = CONFIRMATION
        api = bridge.Api(assistant=Quiet())
        assert api.job(jid, "verify") == ""
        end = time.time() + 5
        while time.time() < end and not (tasks.recent(1) and tasks.recent(1)[0]["status"] in tasks.ENDED):
            time.sleep(0.01)
        task = tasks.recent(1)[0]
        assert task["text"] == "Check the submission of “Full Stack Developer” at Acme"
        assert task["reply"].startswith("Verified:") and _status(jid) == "SUBMITTED"


CARDS = """() => [...document.querySelectorAll('#jobsList .job-card')].map(c => ({
  job: c.dataset.job, status: c.querySelector('.job-foot .badge').textContent,
  track: [...c.querySelectorAll('select option')].map(o => o.value).filter(Boolean),
  history: [...c.querySelectorAll('.job-history li')].map(li => li.textContent),
  summary: (c.querySelector('.job-history summary') || {}).textContent || null}))"""


@pytest.fixture(scope="module")
def browser_ok():
    if not _ui.available():
        pytest.skip("Playwright isn't installed")


def _render(check):
    snapshot = json.loads(json.dumps(bridge.Api(assistant=Quiet()).jobs(), default=str))
    script = _ui.bridge({"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}) + \
        "window.__jobs = %s;" % json.dumps(snapshot)
    result, errors = _ui.open_panel(check, script=script, route="jobs")
    if result is _ui.NO_BROWSER:
        pytest.skip("no browser to render the panel with")
    assert errors == [], errors
    return result


class TestTheCards:
    def test_labels_history_and_only_the_moves_allowed(self, browser_ok):
        a = _job("Alpha", score=90)
        b = _job("Beta", score=80)
        c = _job("Gamma", score=70)
        _move(b, "USER_APPROVED")
        apply.mark_submitted(f"id:{b}", "B-12345")
        _move(c, "REJECTED")
        cards = {card["job"]: card for card in _render(lambda page: page.evaluate(CARDS))}
        assert cards[a]["status"] == "New" and cards[a]["track"] == ["applied", "interview", "offer",
                                                                     "rejected", "withdrawn"]
        assert cards[a]["summary"] is None, "nothing but 'found' yet, so no history to open"
        assert cards[b]["status"] == "Submitted ✓"
        assert cards[b]["track"] == ["interview", "offer", "rejected", "withdrawn"]
        assert cards[b]["summary"] == "History · 3"
        assert "Submitted ✓" in cards[b]["history"][-1] and "B-12345" in cards[b]["history"][-1]
        assert cards[c]["status"] == "Rejected" and cards[c]["track"] == [], "an ended job offers no moves"


class TestTheToolsBehindIt:
    def test_registered_with_honest_descriptions(self):
        for name in ("verify_submission", "mark_submitted", "job_history"):
            assert name in FUNCTIONS and name in {t["name"] for t in TOOL_SCHEMAS}
        described = {t["name"]: t["description"] for t in TOOL_SCHEMAS}
        assert "Never 'submitted'" in described["mark_job_status"]
        assert "clicks nothing" in described["verify_submission"]
        assert not {"verify_submission", "mark_submitted", "job_history"} & permissions.NEEDS_CONFIRMATION
