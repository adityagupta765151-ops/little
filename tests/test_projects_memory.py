"""Projects and Memory (UI-8).

Projects: each project the resume lists, with only what its line says —
the skills from your own resume it names and any web address in it — and a
plain "not in your resume yet" for the rest. Nothing is guessed.

Memory: what LITTLE keeps about you, by kind, where it's kept, contact
numbers masked before they reach the page, and Forget / Remove / Clear that
really delete — by exact key or name, asking first in the window. And the
privacy note is checked against what the model is actually sent.
"""
from __future__ import annotations

import json
import sys
import threading

import pytest

from jarvis.ai import brain as brain_module
from jarvis.app import bridge
from jarvis.jobs import matching, projects, resume, store
from jarvis.store import memory

ATTACK = '<img src=x onerror="window.__ran=1">'

PROFILE = {
    "candidate": {
        "name": "Aditya Gupta", "email": "a@example.com", "phone": "1", "location": "Prayagraj, India",
        "degree": "B.Tech CSE", "graduation_year": "2026", "education": [],
        "skills": ["React", "Node.js", "MongoDB", "Python", "Go", "C++"],
        "languages": ["JavaScript"], "frameworks": ["Next.js"],
        "projects": [
            "Blood Bridge AI - emergency requests in Node.js and MongoDB, github.com/aditya/bloodbridge",
            "Medicine Reminder – a React app for doses",
            "QuantDesk: paper trading, see https://quantdesk.example.com.",
            "Portfolio",
        ],
        "experience": [], "internships": [], "certifications": [],
    },
    "preferences": {"roles": []},
    "source_file": "aditya-resume.pdf",
}


class Quiet:
    muted, running = True, False
    brain = None

    def handle(self, text): ...


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
    return bridge.Api(assistant=Quiet())


@pytest.fixture
def profile():
    resume.save_profile(json.loads(json.dumps(PROFILE)))


def _file(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ================================================================ projects

class TestProjectsAreWhatTheResumeSays:
    def test_each_line_becomes_a_name_and_a_description(self, profile):
        found = projects.from_profile(resume.load_profile())
        assert [(p["name"], p["description"]) for p in found] == [
            ("Blood Bridge AI", "emergency requests in Node.js and MongoDB, github.com/aditya/bloodbridge"),
            ("Medicine Reminder", "a React app for doses"),
            ("QuantDesk", "paper trading, see https://quantdesk.example.com."),
            ("Portfolio", ""),
        ]

    def test_only_skills_from_your_own_resume_are_named(self, profile):
        found = projects.from_profile(resume.load_profile())
        assert found[0]["named"] == ["Node.js", "MongoDB"]
        assert found[1]["named"] == ["React"]
        assert found[3]["named"] == []

    def test_a_skill_the_resume_doesnt_list_is_not_named(self):
        profile = json.loads(json.dumps(PROFILE))
        profile["candidate"]["projects"] = ["Deployer - Docker and Kubernetes on AWS"]
        assert projects.from_profile(profile)[0]["named"] == []

    def test_a_short_skill_needs_its_own_case(self):
        profile = json.loads(json.dumps(PROFILE))
        profile["candidate"]["projects"] = ["Launcher - let's go live fast", "Engine - written in Go and C++"]
        first, second = projects.from_profile(profile)
        assert first["named"] == [], '"go live" is not Go'
        assert second["named"] == ["Go", "C++"]

    def test_web_addresses_in_the_line_become_links(self, profile):
        found = projects.from_profile(resume.load_profile())
        assert found[0]["links"] == ["https://github.com/aditya/bloodbridge"]
        assert found[2]["links"] == ["https://quantdesk.example.com"]
        assert found[1]["links"] == [] and found[3]["links"] == []

    def test_nothing_is_added(self, profile):
        for project in projects.from_profile(resume.load_profile()):
            assert set(project) == {"name", "description", "named", "links"}


class TestTheProjectsSnapshot:
    def test_it_carries_the_projects_and_what_isnt_there(self, api, profile):
        out = api.projects()
        assert out["ready"] is True and out["file"] == "aditya-resume.pdf"
        assert len(out["projects"]) == 4
        assert out["not_in_a_line"] == ["status", "AI/ML parts", "backend", "frontend", "database"]

    def test_with_no_resume(self, api):
        out = api.projects()
        assert out["ready"] is False and out["projects"] == []

    def test_a_broken_profile_is_an_answer(self, api, monkeypatch):
        monkeypatch.setattr(resume, "load_profile", lambda: 1 / 0)
        assert api.projects() == {"error": "I couldn't read your resume profile."}


class TestOpeningAProjectLink:
    @pytest.fixture
    def opened(self, monkeypatch):
        import webbrowser
        seen = []
        monkeypatch.setattr(webbrowser, "open", seen.append)
        return seen

    def test_by_position_python_reads_the_address(self, api, profile, opened):
        assert api.open_project_link(0, 0) == ""
        assert api.open_project_link(2, 0) == ""
        assert opened == ["https://github.com/aditya/bloodbridge", "https://quantdesk.example.com"]

    @pytest.mark.parametrize("where", [(1, 0), (0, 1), (9, 0), (-1, 0), ("0", 0), (True, 0), (0, None)])
    def test_nothing_else(self, api, profile, opened, where):
        assert api.open_project_link(*where) == "That link isn't in your resume any more."
        assert opened == []


# ================================================================== memory

@pytest.fixture
def remembered():
    memory.remember("editor", "VS Code")
    memory.remember("college", "UCER Prayagraj")
    memory.add_contact("mom", "+919876543210")
    memory.add_contact("mohan", "+919812345678")
    for n in range(20):
        memory.log_turn(f"command {n}", f"reply {n} " + "x" * 300)


class TestMasking:
    @pytest.mark.parametrize("number,masked", [
        ("+919876543210", "+91 ••••••3210"),
        ("9876543210", "••••••3210"),
        ("+1 (415) 555-0100", "+1 ••••••0100"),
        ("123", "•••"),
        ("", ""),
    ])
    def test_all_but_the_last_four_digits_are_hidden(self, number, masked):
        assert memory.mask(number) == masked


class TestTheMemorySnapshot:
    def test_it_carries_each_kind(self, api, remembered, profile):
        out = api.memory_view()
        assert out["facts"] == [{"key": "editor", "value": "VS Code"},
                                {"key": "college", "value": "UCER Prayagraj"}]
        names = [c["name"] for c in out["contacts"]]
        assert names == sorted(names) and {"mom", "mohan"} <= set(names)
        assert out["log"]["count"] == 20 and out["log"]["keep"] == memory.HISTORY_KEEP
        assert out["log"]["recent"][0]["user"] == "command 19", "newest first"
        assert len(out["log"]["recent"]) == bridge.MEMORY_TURNS
        assert len(out["log"]["recent"][0]["assistant"]) == bridge.MEMORY_TURN_CHARS + 1
        assert out["resume"] == {"ready": True, "name": "Aditya Gupta", "skills": 6, "projects": 4}
        assert out["folder"] == str(memory.MEMORY_DIR)

    def test_numbers_never_reach_the_page_whole(self, api, remembered):
        flat = json.dumps(api.memory_view(), ensure_ascii=False)
        assert "9876543210" not in flat and "98765" not in flat
        mom = next(c for c in api.memory_view()["contacts"] if c["name"] == "mom")
        assert mom["number"] == "+91 ••••••3210" and mom["sample"] is False

    def test_the_sample_entry_is_called_what_it_is(self, api):
        (example,) = [c for c in api.memory_view()["contacts"] if c["name"] == "example"]
        assert example["sample"] is True

    def test_it_counts_jobs(self, api, profile):
        store.upsert_job(matching.score_job({"job_id": "j1", "company": "A", "title": "Dev", "location": "",
                                             "description": "", "platform": "x", "url": ""},
                                            resume.load_profile()))
        assert api.memory_view()["jobs"] == {"total": 1, "applied": 0}

    def test_a_broken_folder_is_an_answer(self, api, monkeypatch):
        monkeypatch.setattr(memory, "facts", lambda: 1 / 0)
        assert api.memory_view() == {"error": "I couldn't read the memory folder."}


class TestForgetReallyForgets:
    def test_a_fact_leaves_the_file(self, api, remembered):
        assert api.forget_fact("editor") == {"message": "Forgotten: editor."}
        facts = _file(memory.PREFERENCES)["facts"]
        assert "editor" not in facts and facts["college"] == "UCER Prayagraj"
        assert "VS Code" not in memory.recall()
        assert "VS Code" not in memory.PREFERENCES.read_text(encoding="utf-8")

    def test_a_key_saved_with_capitals_by_hand(self, api):
        prefs = memory.preferences()
        prefs["facts"]["Birthday"] = "12 May"
        memory._save(memory.PREFERENCES, prefs)
        assert "message" in api.forget_fact("Birthday")
        assert "Birthday" not in _file(memory.PREFERENCES)["facts"]

    @pytest.mark.parametrize("key", ["nothing", "EDITOR", "", None, 5])
    def test_only_a_key_that_is_there(self, api, remembered, key):
        before = memory.PREFERENCES.read_bytes()
        assert api.forget_fact(key) == {"error": "I had nothing stored under that."}
        assert memory.PREFERENCES.read_bytes() == before

    def test_a_contact_by_its_exact_name(self, api, remembered):
        assert api.remove_contact("mo") == {"error": "That contact isn't saved any more."}
        assert api.remove_contact("mom") == {"message": "Removed mom from your contacts."}
        book = _file(memory.CONTACTS)
        assert "mom" not in book and book["mohan"] == "+919812345678"
        assert memory.find_contact("mom") is None, "WhatsApp can't find it either"
        assert api.remove_contact("mom") == {"error": "That contact isn't saved any more."}

    @pytest.mark.parametrize("name", ["", None, 3, ["mom"]])
    def test_a_contact_name_must_be_a_name(self, api, remembered, name):
        assert "error" in api.remove_contact(name)
        assert "mom" in _file(memory.CONTACTS)

    def test_the_log_is_emptied(self, api, remembered):
        assert api.clear_log() == {"message": "Cleared 20 turns from the log."}
        assert _file(memory.HISTORY) == [] and api.memory_view()["log"]["count"] == 0
        memory.log_turn("hi", "hello")
        assert memory.history() == [{"user": "hi", "assistant": "hello"}]

    def test_nothing_forgotten_is_written_to_the_log(self, api, remembered):
        from jarvis.app import config
        start = config.LOG_FILE.stat().st_size if config.LOG_FILE.exists() else 0
        api.forget_fact("editor")
        api.remove_contact("mom")
        api.clear_log()
        with config.LOG_FILE.open(encoding="utf-8") as handle:
            handle.seek(start)
            written = handle.read()
        assert written.count("memory:") == 3, "each change is noted"
        for secret in ("VS Code", "editor", "mom", "9876543210", "command 1"):
            assert secret not in written


class TestOneChangeAtATime:
    def test_remembering_from_many_threads_loses_nothing(self):
        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            threads = [threading.Thread(target=memory.remember, args=(f"key {n}", str(n))) for n in range(40)]
            threads += [threading.Thread(target=memory.add_contact, args=(f"person {n}", f"+91900000{n:04d}"))
                        for n in range(40)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            sys.setswitchinterval(old)
        assert len(memory.facts()) == 40
        assert sum(name.startswith("person ") for name in memory.contacts()) == 40


class TestThePrivacyNoteIsTrue:
    """The Memory section says none of this goes to the model with every
    request. This checks the request itself."""

    def test_a_question_to_the_model_carries_none_of_it(self, monkeypatch, remembered, profile):
        # Words that appear nowhere in LITTLE's own instructions or tools.
        memory.remember("secret word", "zanzibar-7731")
        memory.add_contact("quokka friend", "+919000077310")
        sent = []

        def model(payload):
            sent.append(json.dumps(payload, ensure_ascii=False))
            return {"candidates": [{"content": {"parts": [{"text": "Hello!"}]}}]}
        monkeypatch.setattr(brain_module, "call_gemini", model)
        assert brain_module.Brain().ask("hello") == "Hello!"
        (payload,) = sent
        for secret in ("zanzibar", "quokka", "9000077310", "UCER Prayagraj", "9876543210", "mohan",
                       "Blood Bridge", "Aditya", "command 19"):
            assert secret not in payload


# ============================================================ in a browser

import _ui  # noqa: E402


@pytest.fixture(scope="module")
def browser_ok():
    if not _ui.available():
        pytest.skip("Playwright isn't installed")


def _render(check, route, extra="", **kw):
    opening = {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}
    result, errors = _ui.open_panel(check, script=_ui.bridge(opening) + extra, route=route, **kw)
    if result is _ui.NO_BROWSER:
        pytest.skip("no browser to render the panel with")
    assert errors == [], errors
    return result


def _with(name, snapshot):
    return "window.__%s = %s;" % (name, json.dumps(snapshot, ensure_ascii=False))


PROJECTS = """() => ({
  calls: window.__calls,
  source: document.getElementById('projSource').textContent,
  status: document.getElementById('projStatus').textContent,
  empty: document.getElementById('projEmpty').hidden ? null : document.getElementById('projEmpty').textContent,
  cards: [...document.querySelectorAll('#projList .proj-card')].map(c => ({
    name: c.querySelector('h3').textContent,
    desc: c.querySelector('.proj-desc').textContent,
    named: [...c.querySelectorAll('.skill')].map(s => s.textContent),
    links: [...c.querySelectorAll('.proj-links button')].map(b => b.textContent),
    missing: c.querySelector('.proj-missing').textContent })),
  images: document.querySelectorAll('[data-view="projects"] img').length,
  ran: window.__ran || 0,
})"""


class TestTheProjectsSection:
    def test_a_card_per_project_with_only_what_it_says(self, browser_ok, api, profile):
        seen = _render(lambda page: page.evaluate(PROJECTS), "projects", _with("projects", api.projects()))
        assert seen["source"] == "4 projects, from aditya-resume.pdf"
        first, second, _, last = seen["cards"]
        assert first["name"] == "Blood Bridge AI" and first["named"] == ["Node.js", "MongoDB"]
        assert first["links"] == ["github.com/aditya/bloodbridge"]
        assert first["missing"] == "Not in your resume yet: status, AI/ML parts, backend, frontend, database."
        assert second["missing"].endswith("database, links.")
        assert last["desc"] == "No description on your resume" and last["named"] == []

    def test_a_link_opens_by_its_place(self, browser_ok, api, profile):
        async def check(page):
            await page.click('[data-project="0"] [data-link="0"]')
            await page.wait_for_timeout(60)
            return await page.evaluate(PROJECTS)

        seen = _render(check, "projects", _with("projects", api.projects()))
        assert ["open_project_link", 0, 0] in seen["calls"]
        assert seen["status"] == "Opened in your browser."

    def test_with_no_resume_it_points_to_resume(self, browser_ok, api):
        async def check(page):
            before = await page.evaluate(PROJECTS)
            await page.click("#projEmpty button")
            await page.wait_for_timeout(60)
            return before, await page.evaluate("location.hash")

        before, where = _render(check, "projects", _with("projects", api.projects()))
        assert before["empty"].startswith("Your projects come from your resume")
        assert where == "#/resume"

    def test_text_is_shown_as_text(self, browser_ok, api):
        profile = json.loads(json.dumps(PROFILE))
        profile["candidate"]["projects"] = [ATTACK + " - " + ATTACK]
        resume.save_profile(profile)
        seen = _render(lambda page: page.evaluate(PROJECTS), "projects", _with("projects", api.projects()))
        assert seen["cards"][0]["name"] == ATTACK and seen["images"] == 0 and seen["ran"] == 0


MEMORY = """() => {
  const text = (id) => document.getElementById(id).textContent;
  const rows = (id) => [...document.querySelectorAll('#' + id + ' .mem-row')].map(r => ({
    what: r.querySelector('.mem-what').textContent,
    acts: [...r.querySelectorAll('.mem-acts button')].map(b => [b.textContent, b.disabled]),
    asking: r.querySelector('.mem-acts').classList.contains('is-asking') }));
  return {
    calls: window.__calls, status: text('memStatus'),
    privacy: text('memPrivacy'),
    facts: rows('memFacts'), factsEmpty: document.querySelector('#memFacts .mem-empty') ? text('memFacts') : null,
    contacts: rows('memContacts'), contactsNote: text('memContactsNote'),
    search: !document.getElementById('memContactSearch').hidden,
    log: [...document.querySelectorAll('#memLog li')].map(li => li.textContent),
    logActs: text('memLogActs'),
    about: text('memAbout'),
    counts: ['memFactsCount', 'memContactsCount', 'memLogCount'].map(text),
    focus: document.activeElement && document.activeElement.textContent,
    input: document.getElementById('input').value,
    images: document.querySelectorAll('[data-view="memory"] img').length,
    ran: window.__ran || 0,
  };
}"""


class TestTheMemorySection:
    def test_each_kind_as_it_is(self, browser_ok, api, remembered, profile):
        seen = _render(lambda page: page.evaluate(MEMORY), "memory", _with("memory", api.memory_view()))
        assert seen["privacy"].startswith(f"Everything here is kept on this computer, in {memory.MEMORY_DIR}.")
        assert "None of it goes to the model with every request" in seen["privacy"]
        assert [f["what"] for f in seen["facts"]] == ["editorVS Code", "collegeUCER Prayagraj"]
        mom = next(c for c in seen["contacts"] if c["what"].startswith("mom"))
        assert mom["what"] == "mom+91 ••••••3210"
        sample = next(c for c in seen["contacts"] if c["what"].startswith("example"))
        assert "a sample entry LITTLE starts with, not a real contact" in sample["what"]
        assert seen["log"][0].startswith("command 19") and len(seen["log"]) == bridge.MEMORY_TURNS
        assert "The latest 15 of 20." in seen["logActs"]
        assert "Aditya Gupta — 6 skills, 4 projects" in seen["about"]
        assert seen["counts"] == ["2", "3", "20"]

    def test_forget_asks_first_then_forgets_that_key(self, browser_ok, api, remembered):
        async def check(page):
            await page.click('[data-key="fact-editor"]')
            asked = await page.evaluate(MEMORY)
            await page.wait_for_timeout(750)
            armed = await page.evaluate(MEMORY)
            await page.click('#memFacts .btn--caution')
            await page.wait_for_timeout(100)
            return asked, armed, await page.evaluate(MEMORY)

        asked, armed, done = _render(check, "memory", _with("memory", api.memory_view()) +
                                     "window.__answers = {forget_fact: {message: 'Forgotten: editor.'}};")
        row = asked["facts"][0]
        assert row["asking"] and row["what"] == "editorVS Code"
        assert row["acts"] == [["Keep", False], ["Forget", True]], "Forget arms after a moment"
        assert asked["focus"] == "Keep" and ["forget_fact", "editor"] not in asked["calls"]
        assert armed["facts"][0]["acts"] == [["Keep", False], ["Forget", False]]
        assert ["forget_fact", "editor"] in done["calls"]
        assert done["status"] == "Forgotten: editor."
        assert done["calls"].count(["memory_view"]) == 2, "read again after"

    @pytest.mark.parametrize("how", ["keep", "escape"])
    def test_keeping_it_deletes_nothing(self, browser_ok, api, remembered, how):
        async def check(page):
            await page.click('[data-key="fact-editor"]')
            if how == "keep":
                await page.click("#memFacts .mem-acts .btn:not(.btn--caution)")
            else:
                await page.keyboard.press("Escape")
            await page.wait_for_timeout(80)
            return await page.evaluate(MEMORY)

        seen = _render(check, "memory", _with("memory", api.memory_view()))
        assert not any(c[0] in ("forget_fact", "control") for c in seen["calls"])
        assert seen["facts"][0]["acts"] == [["Forget", False]] and seen["focus"] == "Forget"

    def test_only_one_question_at_a_time(self, browser_ok, api, remembered):
        async def check(page):
            await page.click('[data-key="fact-editor"]')
            await page.click('[data-key="fact-college"]')
            return await page.evaluate(MEMORY)

        seen = _render(check, "memory", _with("memory", api.memory_view()))
        assert [f["asking"] for f in seen["facts"]] == [False, True]

    def test_remove_a_contact_by_its_name(self, browser_ok, api, remembered):
        async def check(page):
            await page.click('[data-key="contact-mom"]')
            await page.wait_for_timeout(750)
            await page.click('#memContacts .btn--caution')
            await page.wait_for_timeout(100)
            return await page.evaluate(MEMORY)

        seen = _render(check, "memory", _with("memory", api.memory_view()))
        assert ["remove_contact", "mom"] in seen["calls"]

    def test_clearing_the_log_asks_first(self, browser_ok, api, remembered):
        async def check(page):
            await page.click('[data-key="clear-log"]')
            asked = await page.evaluate(MEMORY)
            await page.wait_for_timeout(750)
            await page.click('#memLogActs .btn--caution')
            await page.wait_for_timeout(100)
            return asked, await page.evaluate(MEMORY)

        asked, done = _render(check, "memory", _with("memory", api.memory_view()))
        assert "Clear all 20?" in asked["logActs"] and ["clear_log"] not in asked["calls"]
        assert ["clear_log"] in done["calls"]

    def test_a_refusal_is_shown(self, browser_ok, api, remembered):
        async def check(page):
            await page.click('[data-key="contact-mom"]')
            await page.wait_for_timeout(750)
            await page.click('#memContacts .btn--caution')
            await page.wait_for_timeout(100)
            return await page.evaluate(MEMORY)

        seen = _render(check, "memory", _with("memory", api.memory_view()) +
                       "window.__answers = {remove_contact: {error: \"That contact isn't saved any more.\"}};")
        assert seen["status"] == "That contact isn't saved any more."

    def test_contacts_can_be_searched_and_many_are_shown_in_part(self, browser_ok, api):
        for n in range(70):
            memory.add_contact(f"friend {n:02d}", f"+9190000{n:05d}")
        memory.add_contact("mom", "+919876543210")

        async def check(page):
            before = await page.evaluate(MEMORY)
            await page.fill("#memContactSearch", "mom")
            await page.wait_for_timeout(200)
            return before, await page.evaluate(MEMORY)

        before, found = _render(check, "memory", _with("memory", api.memory_view()))
        assert before["search"] and len(before["contacts"]) == 60
        assert before["contactsNote"].startswith("Showing 60 of 72. Search to find the others.")
        assert [c["what"] for c in found["contacts"]] == ["mom+91 ••••••3210"]

    def test_nothing_remembered_says_how_to_teach_it(self, browser_ok, api):
        async def check(page):
            before = await page.evaluate(MEMORY)
            await page.click("#memFacts .mem-empty button")
            return before, await page.evaluate(MEMORY)

        before, after = _render(check, "memory", _with("memory", api.memory_view()))
        assert "remember that my editor is VS Code" in before["factsEmpty"]
        assert after["input"] == "remember that "
        assert "Nothing logged yet." in before["logActs"]

    def test_text_is_shown_as_text(self, browser_ok, api):
        memory.remember("note", ATTACK)
        memory.add_contact(ATTACK[:40], "+919876543210")
        memory.log_turn(ATTACK, ATTACK)
        seen = _render(lambda page: page.evaluate(MEMORY), "memory", _with("memory", api.memory_view()))
        assert seen["images"] == 0 and seen["ran"] == 0
        assert seen["facts"][0]["what"] == "note" + ATTACK

    def test_it_loads_when_opened_and_after_a_task_ends(self, browser_ok, api):
        done = {"id": 4, "text": "remember that my editor is vim", "source": "typed", "status": "done",
                "route": "local", "started": 1, "ms": 3, "steps": [], "reply": "Noted.", "error": "",
                "plan": None, "reset": False, "again_of": None, "stopping": False, "stop_at": None, "v": 2}

        async def check(page):
            await page.evaluate("window.__queue.push({status: 'listening', lines: [], tasks: %s})"
                                % json.dumps({"v": 2, "changed": [done]}))
            await page.wait_for_timeout(500)
            return await page.evaluate("window.__calls.filter(c => c[0] === 'memory_view').length")

        assert _render(check, "memory", _with("memory", api.memory_view())) == 2


class TestTheyFit:
    @pytest.mark.parametrize("route", ["projects", "memory"])
    @pytest.mark.parametrize("size", [(1040, 660), (1280, 800), (700, 800)], ids=lambda s: f"{s[0]}x{s[1]}")
    def test_nothing_spills_sideways(self, browser_ok, api, remembered, route, size):
        profile = json.loads(json.dumps(PROFILE))
        profile["candidate"]["projects"] = ["A very long project name " * 6 + " - " + "and a long line " * 20]
        resume.save_profile(profile)
        memory.remember("a very long key " * 5, "and a very long value " * 10)

        async def check(page):
            return await page.evaluate("""(route) => {
              const view = document.querySelector(`[data-view="${route}"]`);
              const right = view.getBoundingClientRect().right + 1;
              return {overflow: view.scrollWidth - view.clientWidth,
                      wide: [...view.querySelectorAll('*')].filter(el => el.getBoundingClientRect().right > right)
                              .map(el => el.id || el.className)};
            }""", route)

        extra = _with("projects", api.projects()) + _with("memory", api.memory_view())
        seen = _render(check, route, extra, viewport=size)
        assert seen["overflow"] <= 0 and seen["wide"] == [], seen
