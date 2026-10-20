"""The Jobs section (UI-6): stored jobs as cards in the window, with the
nine score dimensions, and Save, Track and Prepare using the existing job
tools and the existing confirmation.

Python side here: the exact "id:" reference the buttons use, the read-only
snapshot the section reads, and each action run as a recorded task — with
preparing an application and saying you applied both asking you first.
"""
from __future__ import annotations

import threading
import time

import pytest

from jarvis.app import bridge, tasks
from jarvis.jobs import apply, engine, matching, resume, store
from jarvis.tools import permissions


PROFILE = {
    "candidate": {
        "name": "Aditya Gupta", "email": "aditya@example.com", "phone": "9999999999",
        "location": "Prayagraj, India", "degree": "B.Tech CSE", "graduation_year": "2026",
        "education": ["B.Tech CSE, 2026"],
        "skills": ["React", "Node.js", "MongoDB", "Express", "Python", "TypeScript"],
        "languages": ["Python"], "frameworks": ["Next.js"],
        "projects": ["BloodBridge AI", "QuantDesk"],
        "experience": [], "internships": [], "certifications": [],
    },
    "preferences": {"roles": ["full stack developer"], "locations": ["Bangalore", "Remote"],
                    "work_modes": ["remote"], "countries": ["india"], "employment_types": []},
    "source_file": "aditya-resume.pdf",
}


def _store(company, title, url=None, description="React, Node.js and MongoDB. Remote.", **extra):
    job = {"job_id": store.job_id_for(company, title), "company": company, "title": title,
           "location": "Remote", "description": description, "platform": "adzuna",
           "url": url if url is not None else f"https://example.com/{company}/{title}".replace(" ", "-"),
           **extra}
    scored = matching.score_job(job, PROFILE)
    store.upsert_job(scored)
    return scored["job_id"]


@pytest.fixture(autouse=True)
def fresh():
    tasks.reset()
    resume.save_profile(PROFILE)
    yield
    tasks.reset()


class Quiet:
    muted, running = True, False
    def handle(self, text): ...


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
    original = permissions.confirm_fn
    made = bridge.Api(assistant=Quiet())
    yield made
    permissions.set_confirm(original)


def _wait_for(predicate, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _done():
    return _wait_for(lambda: any(t["status"] in tasks.ENDED for t in tasks.recent(5)))


def _answer_next_question(api, ok):
    """Play the page: wait for the confirmation dialog, then answer it."""
    box = {}

    def page():
        for _ in range(300):
            ask = api.poll().get("ask")
            if ask:
                box["message"] = ask["message"]
                api.confirm_reply(ask["id"], ok)
                return
            time.sleep(0.01)
    t = threading.Thread(target=page, daemon=True)
    t.start()
    return box


# ================================================== the exact reference

class TestTheButtonsNameOneJobExactly:
    def test_id_finds_that_job_and_nothing_else(self):
        jid = _store("Acme", "Frontend Developer")
        assert store.by_reference(f"id:{jid}")["title"] == "Frontend Developer"
        assert store.by_reference("id:nope") is None
        assert store.by_reference("Acme") is None, "other forms are the tools' own business"

    def test_two_jobs_at_one_company_are_told_apart(self):
        """By name, "Acme" means whichever Acme job ranks first. By id, the
        click lands on the card it was on."""
        first = _store("Acme", "Full Stack Developer")
        second = _store("Acme", "Data Analyst", description="Excel and Power BI.")
        assert engine.shortlist("Acme").endswith("at Acme.")
        assert engine.shortlist(f"id:{second}") == "Shortlisted Data Analyst at Acme."
        assert store.get_job(second)["status"] == "SAVED"          # SHORTLISTED before Chapter 27
        assert apply.mark_status(f"id:{first}", "interview").startswith("Acme — Full Stack Developer")
        assert "MATCH ANALYSIS" in engine.why_this_job(f"id:{second}")
        assert "Data Analyst" in engine.why_this_job(f"id:{second}")

    def test_the_old_ways_still_work(self):
        _store("Acme", "Full Stack Developer")
        assert engine.shortlist("1") == "Shortlisted Full Stack Developer at Acme."
        assert apply.mark_status("acme", "offer").endswith("is now offer.")


# ============================================================ the snapshot

class TestTheSnapshot:
    def test_it_carries_the_scores_and_their_reasons(self, api):
        _store("Acme", "Full Stack Developer")
        out = api.jobs()
        (job,) = out["jobs"]
        dims = job["score_breakdown"]["dimensions"]
        assert set(dims) == set(matching.WEIGHTS), "all nine dimensions"
        assert set(job["score_breakdown"]["notes"]) == set(matching.WEIGHTS)
        assert job["skills_matched"] and "posted_phrase" in job
        assert out["resume"]["ready"] is True and out["resume"]["file"] == "aditya-resume.pdf"

    def test_descriptions_are_trimmed_not_sent_whole(self, api):
        _store("Acme", "Full Stack Developer", description="React. " * 400)
        (job,) = api.jobs()["jobs"]
        assert "description" not in job
        assert len(job["excerpt"]) <= bridge.EXCERPT + 1 and job["excerpt"].endswith("…")

    def test_with_no_resume_it_says_so(self, api):
        resume.PROFILE_PATH.unlink()
        assert api.jobs()["resume"]["ready"] is False

    def test_a_broken_store_is_an_answer_not_a_crash(self, api, monkeypatch):
        from jarvis.jobs import dashboard
        monkeypatch.setattr(dashboard, "state", lambda: 1 / 0)
        assert api.jobs() == {"error": "I couldn't read the job store."}

    def test_it_only_reads(self, api):
        jid = _store("Acme", "Full Stack Developer")
        before = store.get_job(jid)
        api.jobs(); api.jobs()
        assert store.get_job(jid) == before


# ============================================================== the actions

class TestSaveAndTrack:
    def test_save_runs_the_shortlist_tool_on_that_job_as_a_task(self, api):
        _store("Acme", "Full Stack Developer")
        jid = _store("Acme", "Data Analyst", description="Excel.")
        assert api.job(jid, "save") == ""
        assert _done()
        task = tasks.recent(1)[0]
        assert task["text"] == "Save “Data Analyst” at Acme" and task["route"] == "local"
        assert [(s["name"], s["detail"]) for s in task["steps"]] == [
            ("shortlist_job", f'{{"reference": "id:{jid}"}}')]
        assert task["reply"] == "Shortlisted Data Analyst at Acme."
        assert store.get_job(jid)["status"] == "SAVED"          # SHORTLISTED before Chapter 27
        assert "You: Save “Data Analyst” at Acme" in list(api.lines.queue)

    @pytest.mark.parametrize("action,status", [
        ("unsave", "FOUND"), ("interview", "INTERVIEW"), ("offer", "OFFER"),
        ("rejected", "REJECTED"), ("withdrawn", "WITHDRAWN")])
    def test_a_status_is_set_with_the_status_tool(self, api, action, status):
        jid = _store("Acme", "Full Stack Developer")
        store.set_status(jid, "SHORTLISTED")
        assert api.job(jid, action) == ""
        assert _done()
        assert store.get_job(jid)["status"] == status
        assert tasks.recent(1)[0]["steps"][0]["name"] == "mark_job_status"

    @pytest.mark.parametrize("action", ["delete", "submit", "", None, 5])
    def test_only_the_actions_it_knows(self, api, action):
        jid = _store("Acme", "Full Stack Developer")
        assert api.job(jid, action) == "That isn't something I can do with a job."

    @pytest.mark.parametrize("job_id", ["nope", "", None, 5, True])
    def test_only_a_job_that_exists(self, api, job_id):
        assert api.job(job_id, "save") == "I can't find that job any more."


class TestSayingYouApplied:
    def test_it_asks_first_and_no_records_nothing(self, api):
        jid = _store("Acme", "Full Stack Developer")
        asked = _answer_next_question(api, False)
        assert api.job(jid, "applied") == ""
        assert _done()
        assert "Only say yes if you submitted the application yourself." in asked["message"]
        assert tasks.recent(1)[0]["reply"] == "Okay, nothing recorded."
        assert not store.already_applied(jid)

    def test_yes_records_it(self, api):
        jid = _store("Acme", "Full Stack Developer")
        _answer_next_question(api, True)
        api.job(jid, "applied")
        assert _done()
        assert store.already_applied(jid)
        task = tasks.recent(1)[0]
        assert [s["name"] for s in task["steps"]] == ["your answer", "mark_applied"]
        assert task["steps"][0]["detail"] == "approved"


class TestPreparing:
    @pytest.fixture
    def browser(self, monkeypatch):
        from jarvis.tools import browser as b
        seen = {"opened": [], "filled": []}
        monkeypatch.setattr(b, "open_page", lambda url: seen["opened"].append(url) or f"Opened {url}")
        monkeypatch.setattr(b, "fill_field", lambda label, value: seen["filled"].append(label) or f"Filled {label}")
        monkeypatch.setattr(b, "read_page", lambda: "Name Email Phone Location")
        return seen

    def test_no_means_the_browser_is_never_touched(self, api, browser):
        jid = _store("Acme", "Full Stack Developer")
        asked = _answer_next_question(api, False)
        api.job(jid, "prepare")
        assert _done()
        assert "Nothing is submitted" in asked["message"]
        assert browser["opened"] == [] and browser["filled"] == []
        assert tasks.recent(1)[0]["reply"] == "Okay, I left it."
        assert store.get_job(jid)["status"] == "FOUND"

    def test_yes_opens_that_exact_posting_and_never_submits(self, api, browser):
        _store("Acme", "Full Stack Developer", url="https://example.com/fullstack")
        jid = _store("Acme", "Data Analyst", url="https://example.com/analyst", description="Excel.")
        _answer_next_question(api, True)
        api.job(jid, "prepare")
        assert _done()
        assert browser["opened"] == ["https://example.com/analyst"]
        reply = tasks.recent(1)[0]["reply"]
        assert "press submit yourself" in reply
        assert store.get_job(jid)["status"] == "PREPARED"   # READY_TO_APPLY / NEEDS_USER_ACTION before
        assert not store.already_applied(jid), "preparing is never applying"


class TestOpeningAPosting:
    @pytest.fixture
    def opened(self, monkeypatch):
        import webbrowser
        seen = []
        monkeypatch.setattr(webbrowser, "open", lambda url: seen.append(url))
        return seen

    def test_a_web_address_opens(self, api, opened):
        jid = _store("Acme", "Full Stack Developer", url="https://example.com/job")
        assert api.open_posting(jid) == "" and opened == ["https://example.com/job"]
        assert store.audit_trail(1)[0]["action"] == "open_posting"

    @pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///C:/Windows", "ftp://x/y",
                                     "data:text/html,hi"])
    def test_anything_else_is_refused(self, api, opened, url):
        jid = _store("Acme", "Full Stack Developer", url=url)
        assert api.open_posting(jid) == "That link isn't a web address, so I won't open it."
        assert opened == []

    def test_no_link_says_so(self, api, opened):
        jid = _store("Acme", "Full Stack Developer", url="")
        assert api.open_posting(jid) == "This one has no link stored."

    @pytest.mark.parametrize("job_id", ["nope", None, 3])
    def test_only_a_stored_job(self, api, opened, job_id):
        assert api.open_posting(job_id) == "I can't find that job any more."


# ========================================================== in a browser

import datetime  # noqa: E402
import json  # noqa: E402

import _ui  # noqa: E402

ATTACK = '<img src=x onerror="window.__ran=1">'


@pytest.fixture(scope="module")
def browser_ok():
    if not _ui.available():
        pytest.skip("Playwright isn't installed")


def _render(check, snapshot=None, extra="", **kw):
    kw.setdefault("route", "jobs")
    opening = {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}
    script = _ui.bridge(opening) + (
        "window.__jobs = %s;" % json.dumps(snapshot, default=str) if snapshot is not None else "") + extra
    result, errors = _ui.open_panel(check, script=script, **kw)
    if result is _ui.NO_BROWSER:
        pytest.skip("no browser to render the panel with")
    assert errors == [], errors
    return result


def _snapshot(api):
    return json.loads(json.dumps(api.jobs(), default=str))


JOBS = """() => ({
  cards: [...document.querySelectorAll('#jobsList .job-card')].map(c => ({
    id: c.dataset.job,
    title: c.querySelector('h3').textContent,
    score: c.querySelector('.job-score b').textContent,
    capped: c.querySelector('.job-score').classList.contains('is-capped'),
    dims: [...c.querySelectorAll('.dims li')].map(li => [li.querySelector('.dim-name').textContent,
             li.querySelector('.dim-val').textContent, li.querySelector('.bar i').style.width, li.title]),
    skills: [...c.querySelectorAll('.skill')].map(s => [s.className.replace('skill skill--', ''), s.textContent]),
    concerns: [...c.querySelectorAll('.job-concerns li')].map(li => li.textContent),
    age: c.querySelector('.job-age').textContent,
    why: [...c.querySelectorAll('.job-why li')].map(li => li.textContent),
    status: c.querySelector('.job-foot .badge').textContent,
    acts: [...c.querySelectorAll('.job-acts [data-act]')].map(b => b.textContent),
    track: [...c.querySelectorAll('.job-acts select option')].map(o => o.value).filter(Boolean),
  })),
  summary: document.getElementById('jobsSummary').textContent,
  gaps: document.getElementById('jobsGaps').hidden ? null : document.getElementById('jobsGaps').textContent,
  empty: document.getElementById('jobsEmpty').hidden ? null : document.getElementById('jobsEmpty').textContent,
  filters: Object.fromEntries([...document.querySelectorAll('#jobsFilters [data-group]')].map(b =>
    [b.dataset.group, b.querySelector('.count').textContent])),
  status: document.getElementById('jobsStatus').textContent,
  calls: window.__calls,
  hash: location.hash,
})"""


class TestTheCards:
    def test_every_part_of_the_score_is_shown_with_its_weight_and_reason(self, browser_ok, api):
        jid = _store("Razorpay", "Full Stack Developer", salary="6-9 LPA")
        seen = _render(lambda page: page.evaluate(JOBS), _snapshot(api))
        (card,) = seen["cards"]
        job = store.get_job(jid)
        dims = job["score_breakdown"]["dimensions"]
        notes = job["score_breakdown"]["notes"]
        assert card["score"] == str(job["match_score"])
        assert [d[0] for d in card["dims"]] == [
            "Skills 30%", "Role 16%", "Seniority 12%", "Experience 12%", "Location 12%",
            "Job type 6%", "Work mode 6%", "Education 4%", "Projects 2%"]
        order = ["skills", "role", "seniority", "experience", "location",
                 "employment_type", "work_mode", "education", "projects"]
        assert [d[1] for d in card["dims"]] == [str(dims[k]) for k in order]
        assert [d[2] for d in card["dims"]] == [f"{dims[k]}%" for k in order]
        assert [d[3] for d in card["dims"]] == [notes[k] for k in order]
        # the reasons are text too, not only tooltips
        assert any(line.startswith("Skills: ") for line in card["why"])
        assert any(line.startswith("Weighted total: ") for line in card["why"])

    def test_skills_say_have_close_and_missing_in_words_too(self, browser_ok, api):
        _store("Razorpay", "Full Stack Developer",
               description="React, Node.js, JavaScript, AWS and Docker. Remote.")
        seen = _render(lambda page: page.evaluate(JOBS), _snapshot(api))
        kinds = {kind for kind, _ in seen["cards"][0]["skills"]}
        assert kinds == {"have", "near", "gap"}
        assert any(text == "✓ you have: react" for kind, text in seen["cards"][0]["skills"])
        assert any(text.startswith("✗ missing: ") for kind, text in seen["cards"][0]["skills"])

    def test_age_source_and_concerns_are_on_it(self, browser_ok, api):
        old = str(datetime.date.today() - datetime.timedelta(days=60))
        _store("Freshworks", "Senior Backend Engineer",
               description="Java, Spring Boot. 5+ years experience. Bangalore.", posted_at=old)
        seen = _render(lambda page: page.evaluate(JOBS), _snapshot(api))
        card = seen["cards"][0]
        assert "so it may be filled" in card["age"] and card["age"].endswith("via adzuna")
        assert card["concerns"], "anything worth knowing before applying is shown"
        assert card["concerns"] == store.top_jobs(1)[0]["score_breakdown"]["concerns"]

    def test_a_capped_score_says_it_was_capped_and_why(self, browser_ok, api):
        """A strong-reading senior posting: the stack lines up (71 on its
        own), but the experience bar caps it at 45."""
        _store("Acme", "Senior Full Stack Developer",
               description="React, Node.js, MongoDB, TypeScript, Express. Remote. 5+ years experience.")
        job = store.top_jobs(1)[0]
        assert job["score_breakdown"]["capped_at"] == job["match_score"] < job["score_breakdown"]["weighted"]

        async def check(page):
            await page.click(".job-why summary")
            return {**await page.evaluate(JOBS), "cap": await page.evaluate(
                "document.querySelector('.job-cap').textContent")}

        seen = _render(check, _snapshot(api))
        card = seen["cards"][0]
        assert card["capped"] is True
        assert seen["cap"] == f"Capped at {job['match_score']}: the experience bar is well above your profile"
        assert f"Weighted total: {job['score_breakdown']['weighted']}/100" in card["why"]

    def test_the_summary_and_the_gaps_are_real_counts(self, browser_ok, api):
        _store("A", "Full Stack Developer", description="React, AWS. Remote.")
        _store("B", "Full Stack Developer", description="React, AWS, Docker. Remote.")
        seen = _render(lambda page: page.evaluate(JOBS), _snapshot(api))
        assert seen["summary"].startswith("2 stored · 2 found today · 0 applied")
        assert "aws (2)" in seen["gaps"] and "docker (1)" in seen["gaps"]


class TestTheButtons:
    def test_each_sends_the_job_by_id(self, browser_ok, api):
        jid = _store("Acme", "Full Stack Developer")

        async def check(page):
            await page.click('[data-act="save"]')
            await page.click('[data-act="prepare"]')
            await page.click('[data-act="open"]')
            await page.select_option(".job-acts select", "interview")
            await page.wait_for_timeout(80)
            return await page.evaluate(JOBS)

        seen = _render(check, _snapshot(api))
        acts = [c for c in seen["calls"] if c[0] in ("job", "open_posting")]
        assert acts == [["job", jid, "save"], ["job", jid, "prepare"],
                        ["open_posting", jid], ["job", jid, "interview"]]
        assert seen["cards"][0]["track"] == ["applied", "interview", "offer", "rejected", "withdrawn"]

    def test_a_saved_job_offers_to_put_it_back(self, browser_ok, api):
        jid = _store("Acme", "Full Stack Developer")
        store.set_status(jid, "SHORTLISTED")

        async def check(page):
            await page.click('[data-act="unsave"]')
            await page.wait_for_timeout(60)
            return await page.evaluate(JOBS)

        seen = _render(check, _snapshot(api))
        assert seen["cards"][0]["status"] == "Saved"
        assert ["job", jid, "unsave"] in seen["calls"]

    def test_once_you_have_applied_there_is_nothing_to_save_or_prepare(self, browser_ok, api):
        jid = _store("Acme", "Full Stack Developer")
        store.set_status(jid, "APPLIED")
        seen = _render(lambda page: page.evaluate(JOBS), _snapshot(api))
        card = seen["cards"][0]
        assert card["status"] == "Applied"
        assert card["acts"] == ["Open posting"]
        assert "applied" not in card["track"]

    def test_a_link_that_isnt_a_web_address_gets_no_open_button(self, browser_ok, api):
        _store("Acme", "Full Stack Developer", url="javascript:window.__ran=1")
        seen = _render(lambda page: page.evaluate(JOBS), _snapshot(api))
        assert "Open posting" not in seen["cards"][0]["acts"]

    def test_what_python_says_back_is_shown(self, browser_ok, api):
        _store("Acme", "Full Stack Developer")

        async def check(page):
            await page.click('[data-act="save"]')
            await page.wait_for_timeout(60)
            return await page.evaluate(JOBS)

        seen = _render(check, _snapshot(api), extra="window.__answers = {job: \"I can't find that job any more.\"};")
        assert seen["status"] == "I can't find that job any more."


class TestFindingJobs:
    @pytest.fixture
    def three(self, api):
        a = _store("Razorpay", "Full Stack Developer", posted_at=str(datetime.date.today()))
        b = _store("Zoho", "Frontend Engineer", description="React, Redux. Chennai.",
                   posted_at=str(datetime.date.today() - datetime.timedelta(days=30)))
        c = _store("CRED", "Data Analyst", description="Excel, Power BI. Bangalore.")
        store.set_status(b, "SHORTLISTED")
        store.set_status(c, "REJECTED")
        return a, b, c

    def _titles(self, seen):
        return [c["title"] for c in seen["cards"]]

    def test_filters_count_and_narrow(self, browser_ok, api, three):
        async def check(page):
            first = await page.evaluate(JOBS)
            await page.click('[data-group="saved"]')
            saved = await page.evaluate(JOBS)
            await page.click('[data-group="closed"]')
            return first, saved, await page.evaluate(JOBS)

        first, saved, closed = _render(check, _snapshot(api))
        assert first["filters"] == {"all": "3", "new": "1", "saved": "1", "ready": "0", "applied": "0", "closed": "1"}
        assert self._titles(saved) == ["Frontend Engineer"]
        assert self._titles(closed) == ["Data Analyst"]

    def test_search_reads_titles_companies_and_skills(self, browser_ok, api, three):
        async def check(page):
            await page.fill("#jobsSearch", "redux")
            await page.wait_for_timeout(250)
            by_skill = await page.evaluate(JOBS)
            await page.fill("#jobsSearch", "cred")
            await page.wait_for_timeout(250)
            by_company = await page.evaluate(JOBS)
            await page.fill("#jobsSearch", "nothing like this")
            await page.wait_for_timeout(250)
            return by_skill, by_company, await page.evaluate(JOBS)

        by_skill, by_company, none = _render(check, _snapshot(api))
        assert self._titles(by_skill) == ["Frontend Engineer"]
        assert self._titles(by_company) == ["Data Analyst"]
        assert none["cards"] == [] and none["empty"] == "No jobs match. Clear the search or pick another filter."

    def test_sorting_and_hiding_old_postings(self, browser_ok, api, three):
        async def check(page):
            await page.select_option("#jobsSort", "newest")
            newest = await page.evaluate(JOBS)
            await page.check("#jobsRecent")
            return newest, await page.evaluate(JOBS)

        newest, recent = _render(check, _snapshot(api))
        assert self._titles(newest)[:2] == ["Full Stack Developer", "Frontend Engineer"], \
            "dated postings newest first; the undated one after"
        assert "Frontend Engineer" not in self._titles(recent), "a month-old posting is hidden"
        assert "Data Analyst" in self._titles(recent), "a posting with no date is kept, as the search does"


class TestWhenThereIsNothingToShow:
    def test_no_resume_says_to_scan_one(self, browser_ok, api):
        resume.PROFILE_PATH.unlink()

        async def check(page):
            before = await page.evaluate(JOBS)
            await page.click("#jobsEmpty button")
            await page.wait_for_timeout(60)
            return before, await page.evaluate("location.hash")

        before, where = _render(check, _snapshot(api))
        assert before["empty"].startswith("Scan your resume first")
        assert where == "#/resume", "the button opens Resume, where the file picker is"

    def test_no_jobs_offers_to_find_some(self, browser_ok, api):
        async def check(page):
            before = await page.evaluate(JOBS)
            await page.click("#jobsEmpty button")
            await page.wait_for_timeout(60)
            return before, await page.evaluate(JOBS)

        before, after = _render(check, _snapshot(api))
        assert before["empty"].startswith("No jobs stored yet.")
        assert ["send", "find jobs for me"] in after["calls"]

    def test_a_store_that_cant_be_read_says_so_and_offers_to_try_again(self, browser_ok):
        async def check(page):
            before = await page.evaluate(JOBS)
            await page.click("#jobsEmpty button")
            await page.wait_for_timeout(60)
            return before, await page.evaluate(JOBS)

        before, after = _render(check, {"error": "I couldn't read the job store."})
        assert before["empty"].startswith("I couldn't read the job store.")
        assert after["calls"].count(["jobs"]) == 2


class TestItLoadsWhenItShould:
    def test_on_opening_and_after_a_task_ends_not_on_every_poll(self, browser_ok, api):
        _store("Acme", "Full Stack Developer")
        snap = _snapshot(api)
        tid = tasks.start("save it"); tasks.finish(tasks.DONE)
        version, changed = tasks.changed_since(0)
        ended = {"status": "listening", "lines": [], "tasks": {"v": version, "changed": changed}}
        extra = "window.__ended = %s;" % json.dumps(ended)

        async def check(page):
            await page.wait_for_timeout(700)               # several polls
            quiet = (await page.evaluate("window.__calls")).count(["jobs"])
            await page.evaluate("window.__queue.push(window.__ended)")
            await page.wait_for_timeout(500)
            return quiet, (await page.evaluate("window.__calls")).count(["jobs"])

        quiet, after = _render(check, snap, extra=extra)
        assert quiet == 1, "loaded once on opening, not on each poll"
        assert after == 2, "and again once a task ended"
        assert tid

    def test_going_to_jobs_from_elsewhere_loads_it(self, browser_ok, api):
        _store("Acme", "Full Stack Developer")

        async def check(page):
            before = (await page.evaluate("window.__calls")).count(["jobs"])
            await page.click('[data-route="jobs"]')
            await page.wait_for_timeout(200)
            return before, await page.evaluate(JOBS)

        before, seen = _render(check, _snapshot(api), route="home")
        assert before == 0
        assert seen["calls"].count(["jobs"]) == 1 and len(seen["cards"]) == 1

    def test_elsewhere_it_doesnt_load_at_all(self, browser_ok, api):
        seen = _render(lambda page: page.evaluate("window.__calls"), _snapshot(api), route="home")
        assert ["jobs"] not in seen


class TestEndToEnd:
    def test_save_from_the_card_shows_it_saved(self, browser_ok, api):
        """The page sends the button; Python runs the real shortlist tool as
        a task; the page, seeing the task end, reads the store again."""
        jid = _store("Acme", "Full Stack Developer")
        before = _snapshot(api)
        assert api.job(jid, "save") == ""
        assert _done()
        after = _snapshot(api)
        version, changed = tasks.changed_since(0)
        ended = {"status": "listening", "lines": [], "tasks": {"v": version, "changed": changed}}
        extra = """
          window.__after = %s; window.__ended = %s;
          const realJob = window.pywebview.api.job;
          window.pywebview.api.job = async (id, action) => {
            const out = await realJob(id, action);
            window.__jobs = window.__after;          // Python has now saved it
            window.__queue.push(window.__ended);     // and the task has ended
            return out; };""" % (json.dumps(after, default=str), json.dumps(ended))

        async def check(page):
            before_click = (await page.evaluate(JOBS))["cards"][0]["status"]
            await page.click('[data-act="save"]')
            await page.wait_for_timeout(600)
            return before_click, await page.evaluate(JOBS)

        before_click, seen = _render(check, before, extra=extra)
        assert before_click == "New"
        assert seen["cards"][0]["status"] == "Saved"
        assert seen["cards"][0]["acts"][:2] == ["Open posting", "Saved"]


class TestSafeAndFits:
    def test_nothing_from_a_job_board_runs_as_markup(self, browser_ok, api):
        _store(ATTACK, ATTACK, description=ATTACK, url="javascript:window.__ran=1",
               salary=ATTACK, location=ATTACK)

        async def check(page):
            await page.click(".job-why summary")
            return {"images": await page.evaluate("document.querySelectorAll('.jobsview img').length"),
                    "ran": await page.evaluate("window.__ran || 0"), **await page.evaluate(JOBS)}

        seen = _render(check, _snapshot(api))
        assert seen["images"] == 0 and seen["ran"] == 0
        assert seen["cards"][0]["title"] == ATTACK

    @pytest.mark.parametrize("size", [(1040, 660), (1920, 1080)], ids=lambda s: f"{s[0]}x{s[1]}")
    def test_many_long_cards_scroll_inside_and_nothing_runs_sideways(self, browser_ok, api, size):
        for i in range(12):
            _store(f"Company {i} " + "x" * 80, "Full Stack Developer " + "y" * 120,
                   description="React, Node.js, MongoDB, AWS, Docker, Kubernetes, Redux, Jest. Remote.")

        async def check(page):
            return await page.evaluate("""() => {
              const scroll = document.querySelector('.jobs-scroll');
              return { sideways: document.documentElement.scrollWidth > window.innerWidth
                         || scroll.scrollWidth > scroll.clientWidth + 1,
                       clear: scroll.getBoundingClientRect().bottom
                         <= document.querySelector('.cmdbar').getBoundingClientRect().top,
                       scrolls: scroll.scrollHeight > scroll.clientHeight };
            }""")

        seen = _render(check, _snapshot(api), viewport=size)
        assert not seen["sideways"] and seen["clear"] and seen["scrolls"]


# ================================================ the browser dashboard

import asyncio  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

from jarvis.jobs import dashboard  # noqa: E402


@pytest.fixture
def served():
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _get(url, method="GET"):
    request = urllib.request.Request(url, method=method, data=b"{}" if method != "GET" else None)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), b""


class TestTheDashboardRestyled:
    @pytest.mark.parametrize("name", ["tokens.css", "base.css"])
    def test_it_serves_the_windows_design_system(self, served, name):
        status, headers, body = _get(f"{served}/css/{name}")
        assert status == 200 and headers["Content-Type"].startswith("text/css")
        assert body == (dashboard.APP_DIR / "ui" / "css" / name).read_bytes()
        assert "script-src 'self'" in headers["Content-Security-Policy"]

    @pytest.mark.parametrize("path", ["/css/components.css", "/css/app.css", "/css/",
                                      "/css/..%2F..%2Fjarvis%2Fapp%2Fconfig.py",
                                      "/../jarvis/app/config.py", "/../../.env"])
    def test_and_nothing_else_from_outside_its_folder(self, served, path):
        status, _, body = _get(served + path)
        assert status == 404, f"{path} was served"
        assert b"API_KEY" not in body

    def test_it_has_littles_icon(self, served):
        """A real browser — Chrome, Edge — asks for /favicon.ico whatever the
        page says, and logged the 404 as an error on your computer."""
        status, headers, body = _get(served + "/favicon.ico")
        assert status == 200 and headers["Content-Type"] == "image/x-icon"
        assert body == dashboard.ICON.read_bytes()

    def test_no_icon_is_nothing_not_an_error(self, served, monkeypatch, tmp_path):
        monkeypatch.setattr(dashboard, "ICON", tmp_path / "gone.ico")
        status, _, body = _get(served + "/favicon.ico")
        assert status == 204 and body == b""

    def test_a_dotted_path_lands_back_in_its_own_folder(self, served):
        """http.server folds "/css/../app.js" to "/app.js": the dashboard's
        own script, which it serves anyway — never anything above it."""
        status, _, body = _get(served + "/css/../app.js")
        assert status == 200 and body == (dashboard.UI_DIR / "app.js").read_bytes()

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
    def test_it_is_still_read_only(self, served, method):
        jid = _store("Acme", "Full Stack Developer")
        before = store.get_job(jid)
        status, _, _ = _get(f"{served}/api/state", method=method)
        assert status in (405, 501)
        assert store.get_job(jid) == before

    def test_the_page_loads_the_shared_styles_first(self):
        html = (dashboard.UI_DIR / "index.html").read_text(encoding="utf-8")
        order = [html.index(f'href="{h}"') for h in ("/css/tokens.css", "/css/base.css", "app.css")]
        assert order == sorted(order)

    def test_it_renders_on_the_tokens_under_its_policy(self, browser_ok, served):
        _store("Razorpay", "Full Stack Developer")
        from playwright.async_api import async_playwright

        async def go():
            async with async_playwright() as pw:
                # The full browser, as on your computer: the trimmed headless
                # one never asks for an icon, so it missed the 404.
                browser = await _ui._launch_full(pw)
                if browser is None:
                    return None
                page = await browser.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                await page.goto(served + "/jobs")
                await page.wait_for_timeout(700)
                seen = await page.evaluate("""() => ({
                  background: getComputedStyle(document.body).backgroundColor,
                  brand: getComputedStyle(document.querySelector('.card .score b')).color,
                  cards: document.querySelectorAll('#dashCards .card').length })""")
                await browser.close()
                return seen, errors

        result = asyncio.run(go())
        if result is None:
            pytest.skip("no browser to render the dashboard with")
        seen, errors = result
        assert errors == []
        assert seen["background"] == "rgb(6, 9, 16)", "the window's --bg-0"
        assert seen["brand"] == "rgb(124, 199, 255)", "the window's --brand"
        assert seen["cards"] == 1
