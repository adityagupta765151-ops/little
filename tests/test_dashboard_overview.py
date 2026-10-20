"""Chapter 40 — Dashboard 2.0: everything at a glance, from real data only.

Eleven sections read from the same places the rest of LITTLE reads. What
isn't available says so; nothing is estimated; a section that can't be read
says that instead of showing zeros. Shown at the top of the System section,
and as words for "status report".
"""
from __future__ import annotations

import json

import pytest

from jarvis.app import assistant, bridge, config, latency, overview, stats, tasks
from jarvis.jobs import store
from jarvis.store import knowledge, memory
from jarvis.tools import permissions

IDS = ["system", "ai", "voice", "memory", "tools", "tasks", "browser", "jobs", "applications", "security", "logs"]


def rows(section_id, assistant_=None):
    found = next(s for s in overview.snapshot(assistant_) if s["id"] == section_id)
    return dict((a, b) for a, b in found["rows"] if a), found["state"]


@pytest.fixture(autouse=True)
def fresh():
    latency.reset()
    yield
    latency.reset()


class Running:
    running, muted = True, False


# =============================================================== the shape

class TestTheShape:
    def test_eleven_sections_in_order(self):
        found = overview.snapshot()
        assert [s["id"] for s in found] == IDS
        assert all(s["state"] in ("ok", "warn", "off") for s in found)
        assert all(isinstance(a, str) and isinstance(b, str) for s in found for a, b in s["rows"])
        json.dumps(found)

    def test_one_that_cant_be_read_says_so_and_the_rest_carry_on(self, monkeypatch):
        monkeypatch.setattr(overview, "SECTIONS", tuple((i, (lambda: 1 / 0) if i == "jobs" else f)
                                                        for i, f in overview.SECTIONS))
        found = {s["id"]: s for s in overview.snapshot()}
        assert found["jobs"] == {"id": "jobs", "title": "Jobs", "state": "off",
                                 "rows": [["Couldn't read it", "ZeroDivisionError"]]}
        assert found["memory"]["state"] == "ok"


# ============================================================ real numbers

class TestRealData:
    def test_nothing_yet_is_said_as_nothing_yet(self):
        assert rows("jobs")[0] == {"Stored": "0", "Found today": "0", "Best match": "none yet",
                                   "Average match": "none yet"}
        assert rows("ai")[0]["Typical answer"] == "not measured yet"
        assert rows("tasks")[0]["Answered here"] == "not measured yet"

    def test_system_readings_or_why_not(self, monkeypatch):
        monkeypatch.setattr(stats, "system", lambda: {"available": True, "cpu": 12, "ram": 40, "ram_used": 3.2,
                                                      "ram_total": 8.0, "disk": 70, "disk_free": 50})
        got, state = rows("system")
        assert got["CPU"] == "12%" and got["Memory"] == "40% (3.2 of 8.0 GB)" and state == "ok"
        monkeypatch.setattr(stats, "system", lambda: {"available": True, "cpu": 12, "ram": 95, "ram_used": 7.6,
                                                      "ram_total": 8.0, "disk": 99, "disk_free": 1})
        assert rows("system")[1] == "warn"
        monkeypatch.setattr(stats, "system", lambda: {"available": False})
        got, state = rows("system")
        assert got["Readings"] == "psutil isn't installed" and state == "off" and "CPU" not in got

    def test_ai(self, monkeypatch):
        monkeypatch.setattr(config, "API_KEY", "")
        latency.record("ai", 2400)
        latency.record("agent", 9000)
        got, state = rows("ai")
        assert got["API key"] == "missing" and state == "warn"
        assert got["Typical answer"] == "2.4 s" and got["Plans run"] == "1"

    def test_voice(self):
        got, state = rows("voice", Running())
        assert (got["Microphone"], got["Speaking"], state) == ("listening", "on", "ok")
        assert rows("voice")[0]["Microphone"] == "unknown", "not told, so not guessed"

    def test_memory(self, workspace):
        memory.remember("editor", "VS Code")
        memory.set_preference("browser", "Firefox")
        memory.remember_for_project("QuantDesk", "broker", "paper")
        memory.add_contact("rahul", "+919812345678")
        memory.log_turn("hi", "hello")
        (workspace / "a.md").write_text("Alpha notes.\n\nBeta notes.", encoding="utf-8")
        knowledge.add_document("a.md")
        got, _ = rows("memory")
        assert got == {"Facts": "1", "Preferences": "1", "Projects": "1", "Contacts": "1",
                       "Documents": "1 (1 part)", "Conversation log": "1 turn"}, "the sample contact isn't counted"

    def test_tools(self, monkeypatch):
        from jarvis.tools import registry
        registry.execute_tool("nope_tool", {})
        got, state = rows("tools")
        assert got["Ask first"] == str(len(permissions.NEEDS_CONFIRMATION)) and got["Outside tools"] == "none"
        assert int(got["Failed or blocked"]) >= 1 and state == "warn"

    def test_tasks(self):
        tasks.reset()               # the record is shared across the whole run
        for status, path in ((tasks.DONE, "fast"), (tasks.FAILED, "ai"), (tasks.DONE, "normal")):
            tid = tasks.start("x")
            tasks.route({"fast": "local", "normal": "local", "ai": "model"}[path])
            tasks.path(path)
            tasks.finish(status, task_id=tid)
        got, state = rows("tasks")
        assert got["This session"].endswith("(2 done, 1 failed, 0 stopped, 0 running)") and state == "warn"
        assert "fast 1, normal 1, ai 1, agent 0" in got["By path"]

    def test_browser_never_starts_one(self, monkeypatch):
        from jarvis.tools import browser
        monkeypatch.setattr(browser, "current_page", lambda: pytest.fail("the browser was asked"))
        got, state = rows("browser")
        assert got["My browser"] == "closed" and got["On"] == "no page" and state == "off"

    def test_jobs_and_applications(self):
        def job(company, score, status):
            jid = store.job_id_for(company, "Intern")
            store.upsert_job({"job_id": jid, "company": company, "title": "Intern", "location": "Remote",
                              "url": f"https://{company.lower()}.example", "platform": "adzuna",
                              "match_score": score, "description": "x"})
            store.set_status(jid, status) if status not in ("FOUND", "SUBMITTED") else None
            return jid
        job("Acme", 91, "FOUND")
        job("Beta", 70, "PREPARED")
        store.record_application(job("Gamma", 60, "FOUND"), "USER_APPROVED")
        job("Delta", 50, "INTERVIEW")
        job("Eps", 40, "REJECTED")
        got, _ = rows("jobs")
        assert got["Stored"] == "5" and got["Best match"] == "91% — Intern at Acme" and got["Average match"] == "62%"
        got, _ = rows("applications")
        assert got == {"Prepared, waiting for you": "1", "Applied (your word)": "1", "Submitted (verified)": "0",
                       "Interviews": "1", "Offers": "0", "Rejected or withdrawn": "1"}

    def test_security(self, monkeypatch):
        monkeypatch.setenv("JARVIS_BLOCKED_TOOLS", "run_command")
        from jarvis import tools
        tools.set_confirm(lambda _a: False)
        tools.confirm("x?")
        tools.set_confirm(lambda _m: False)
        got, _ = rows("security")
        assert got["Blocked"] == "run_command" and got["Asks every time"] == "3"
        assert got["Your answers"].endswith(" no") and int(got["Your answers"].split(", ")[1].split()[0]) >= 1

    def test_logs_are_the_last_lines_with_secrets_hidden(self):
        config.log("first line")
        config.log("key AIzaSyA1234567890abcdefghijklmn used")
        config.log("x" * 400)
        found = next(s for s in overview.snapshot() if s["id"] == "logs")
        shown = [b for a, b in found["rows"][1:]]
        assert len(shown) <= overview.LOG_LINES and all(len(line) <= overview.LOG_CHARS for line in shown)
        assert "AIzaSy" not in json.dumps(found) and any("[hidden]" in line for line in shown)
        assert found["rows"][1][0] == "Latest" and found["rows"][1][1].endswith("x" * 20)


# ================================================================= reaching

class TestReachingIt:
    @pytest.fixture
    def api(self, monkeypatch):
        monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
        return bridge.Api(assistant=Running())

    def test_the_system_section_gets_it(self, api, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTHE-REAL-KEY-000000000")
        out = api.system()
        assert [s["id"] for s in out["dashboard"]] == IDS
        assert "THE-REAL-KEY" not in json.dumps(out)

    def test_status_report_by_command(self, monkeypatch):
        monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
        bot = assistant.Jarvis(log_fn=lambda _l: None)
        bot.muted = True

        class NoModel:
            def ask(self, *_a, **_k):
                pytest.fail("the model was asked")
        bot.brain = NoModel()
        bot.handle("everything at a glance")
        task = tasks.recent(1)[0]
        assert task["path"] == "fast"
        lines = task["reply"].split("\n")
        assert [line.split(":")[0].split(" (")[0] for line in lines] == [
            "System", "AI", "Voice", "Memory", "Tools", "Tasks", "Browser", "Jobs", "Applications", "Security"]
        assert "microphone off" in task["reply"], "the assistant knows its own microphone"

    def test_status_report_is_still_the_health_check(self, monkeypatch):
        # It meant the system check before Chapter 40, and still does.
        from jarvis.app import health
        from jarvis.routing import router
        monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
        monkeypatch.setattr(router.health, "system_check", lambda *_a, **_k: "<system check>")
        bot = assistant.Jarvis(log_fn=lambda _l: None)
        bot.muted = True
        bot.handle("status report")
        assert tasks.recent(1)[0]["reply"] == "<system check>"
        assert health.system_check is not None


import _ui  # noqa: E402

GLANCE = """() => ({
  hidden: document.getElementById('sysGlanceWrap').hidden,
  cards: [...document.querySelectorAll('#sysGlance .glance-card')].map(c => ({
    id: c.dataset.id, state: c.dataset.state, title: c.querySelector('h3').textContent,
    rows: [...c.querySelectorAll('dt')].map((dt, i) => [dt.textContent, c.querySelectorAll('dd')[i].textContent])})),
  ran: window.__ran || 0, images: document.querySelectorAll('#sysGlance img').length,
})"""


class TestTheGlancePanel:
    @pytest.fixture(autouse=True)
    def browser_ok(self):
        if not _ui.available():
            pytest.skip("Playwright isn't installed")

    def _render(self, dashboard):
        snapshot = {"groups": [], "env": {"path": "D:/little/.env", "exists": True}, "mics": [], "asks_first": [],
                    "tools": 88, "audit": [], "muted": False, "listening": False}
        if dashboard is not None:
            snapshot["dashboard"] = dashboard
        opening = {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}
        result, errors = _ui.open_panel(lambda page: page.evaluate(GLANCE), route="system",
                                        script=_ui.bridge(opening) + "window.__system = %s;" % json.dumps(snapshot))
        if result is _ui.NO_BROWSER:
            pytest.skip("no browser to render the panel with")
        assert errors == [], errors
        return result

    def test_every_section_as_it_came(self):
        ATTACK = '<img src=x onerror="window.__ran=1">'
        dashboard = overview.snapshot()
        dashboard[0]["rows"].append(["Note", ATTACK])
        dashboard[1]["state"] = "warn"
        seen = self._render(dashboard)
        assert not seen["hidden"] and [c["id"] for c in seen["cards"]] == IDS
        assert seen["cards"][0]["rows"][-1] == ["Note", ATTACK] and seen["ran"] == 0 and seen["images"] == 0
        assert seen["cards"][1]["state"] == "warn" and seen["cards"][1]["title"].startswith("AI")
        assert seen["cards"][1]["title"].endswith("Needs a look")

    def test_an_older_snapshot_shows_no_panel(self):
        assert self._render(None)["hidden"] is True
