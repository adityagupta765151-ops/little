"""Home (UI-3): what Little is doing, what you can do, what happened, and
what needs you — all from the task record, rendered in a real browser.

Task payloads here are made by the real registry (jarvis/app/tasks.py), so
the page is tested against exactly what Python sends. The end-to-end tests
go further: a real command runs through the real assistant and bridge, and
what the bridge handed over is replayed into the page.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

import _ui
from jarvis.app import assistant, bridge, tasks
from jarvis.tools import permissions

ROOT = Path(__file__).resolve().parent.parent
ATTACK = '<img src=x onerror="window.__ran=1">'


@pytest.fixture(scope="module")
def browser_ok():
    if not _ui.available():
        pytest.skip("Playwright isn't installed")


@pytest.fixture(autouse=True)
def fresh():
    tasks.reset()
    yield
    tasks.reset()


def _render(check, **kw):
    result, errors = _ui.open_panel(check, **kw)
    if result is _ui.NO_BROWSER:
        pytest.skip("no browser to render the panel with")
    assert errors == [], errors
    return result


def _stats(warnings=()):
    return {
        "identity": {"name": "LITTLE", "call": "Little"}, "system": {"available": False},
        "session": {"uptime": "0", "commands": 0, "tools": 0, "os": "Windows 11"},
        "voice": {"mic": "on", "speech": "on", "voice": "Neerja", "lang": "en-IN", "model": "m"},
        "tools": [], "reminders": [], "plan": None, "browser": "closed", "contacts": 0,
        "workspace": "C:/w", "warnings": list(warnings),
    }


def _delta(since=0):
    version, changed = tasks.changed_since(since)
    return {"v": version, "changed": changed}


def _poll(status="listening", since=0, warnings=(), **extra):
    return {"status": status, "lines": [], "stats": _stats(warnings),
            "tasks": _delta(since), **extra}


def _finished(text, status=tasks.DONE, route="local", error="", steps=()):
    tid = tasks.start(text)
    tasks.route(route)
    for name in steps:
        tasks.step_finished(tasks.step_started(name, '{"x": 1}'))
    tasks.finish(status, error)
    return tid


HOME = """() => ({
  hint: !document.getElementById('hint').hidden,
  now: !document.getElementById('now').hidden,
  nowText: document.getElementById('nowText').textContent,
  nowMeta: document.getElementById('nowMeta').textContent,
  elapsed: document.getElementById('elapsed').textContent,
  steps: [...document.querySelectorAll('#nowSteps li')].map(li => [li.className, li.textContent]),
  last: document.getElementById('lastTask').hidden ? null : document.getElementById('lastTask').textContent,
  recent: [...document.querySelectorAll('#recentList li')].map(li => [li.className, li.textContent]),
  waiting: [...document.querySelectorAll('#waitList li')].map(li => [li.className, li.textContent]),
  waitCount: document.getElementById('waitCount').textContent,
  flash: document.body.dataset.flash || null,
  calls: window.__calls,
  since: window.__since,
  hash: location.hash,
})"""


# ============================================================ quick actions

class TestQuickActions:
    def test_they_are_there(self, browser_ok):
        seen = _render(lambda page: page.evaluate(
            "[...document.querySelectorAll('#quick button')].map(b => b.textContent)"))
        assert seen == ["Find jobs", "My resume", "What you remember",
                        "Look something up…", "Set a reminder…", "Several steps…"]

    def test_a_command_is_sent_as_it_is(self, browser_ok):
        async def check(page):
            await page.click('#quick [data-say="find jobs for me"]')
            await page.wait_for_timeout(100)
            return await page.evaluate(HOME)

        seen = _render(check)
        assert seen["calls"] == [["send", "find jobs for me"]]
        assert seen["hash"] == "#/home"

    def test_a_start_is_put_in_the_box_for_you_to_finish_and_nothing_is_sent(self, browser_ok):
        async def check(page):
            await page.click('#quick [data-fill="remind me to "]')
            return await page.evaluate("""() => ({
              value: document.getElementById('input').value,
              focus: document.activeElement.id,
              caret: document.getElementById('input').selectionStart,
              calls: window.__calls })""")

        seen = _render(check)
        assert seen["value"] == "remind me to " and seen["focus"] == "input"
        assert seen["caret"] == len("remind me to ")
        assert seen["calls"] == []


# ================================================================== the hero

class TestTheTaskInHand:
    def test_the_page_asks_only_for_what_changed(self, browser_ok):
        _finished("what's the time")
        poll = _poll()
        seen = _render(lambda page: page.evaluate(HOME), script=_ui.bridge(poll))
        assert seen["since"] == poll["tasks"]["v"], "the next poll asks from the version it has"

    def test_it_shows_what_is_running_and_its_latest_steps(self, browser_ok):
        tasks.start("summarise the readme and list the todos")
        tasks.route("model")
        for name in ("list_dir", "read_file", "search_files", "read_file"):
            tasks.step_finished(tasks.step_started(name, '{"path": "x"}'))
        tasks.step_started("summarise_page")                  # still running
        seen = _render(lambda page: page.evaluate(HOME), script=_ui.bridge(_poll("executing")))

        assert seen["now"] and not seen["hint"]
        assert seen["nowText"] == "“summarise the readme and list the todos”"
        assert seen["nowMeta"] == "asking the model"
        assert seen["elapsed"].endswith("s")
        assert seen["steps"][0] == ["muted", "2 earlier steps"]
        assert [cls for cls, _ in seen["steps"][1:]] == ["done", "done", "now"]
        assert seen["steps"][-1][1].startswith("summarise_page")

    def test_a_question_waiting_on_you_is_said_plainly(self, browser_ok):
        tasks.start("delete notes.txt")
        tasks.waiting("Delete notes.txt?")
        seen = _render(lambda page: page.evaluate(HOME), script=_ui.bridge(_poll()))
        assert seen["nowMeta"] == "waiting for your answer"
        assert seen["recent"][0][0] == "is-waiting"

    def test_a_spoken_command_says_so(self, browser_ok):
        tasks.start("find jobs for me", source="voice")
        tasks.route("local")
        seen = _render(lambda page: page.evaluate(HOME), script=_ui.bridge(_poll()))
        assert seen["nowMeta"] == "on this computer · you said it"

    def test_with_nothing_running_it_shows_the_hint_and_the_last_task(self, browser_ok):
        _finished("what's the time")
        seen = _render(lambda page: page.evaluate(HOME), script=_ui.bridge(_poll()))
        assert seen["hint"] and not seen["now"]
        assert seen["last"].startswith("Last: “what's the time” · done · ")

    def test_before_anything_has_run_there_is_no_last_task(self, browser_ok):
        seen = _render(lambda page: page.evaluate(HOME), script=_ui.bridge(_poll()))
        assert seen["last"] is None and seen["hint"]


# ==================================================================== recent

class TestRecent:
    def test_each_task_says_how_it_ended(self, browser_ok):
        _finished("one")
        _finished("two", tasks.FAILED, error="broke")
        _finished("three", tasks.STOPPED)
        tasks.start("four")
        seen = _render(lambda page: page.evaluate(HOME), script=_ui.bridge(_poll()))
        assert [cls for cls, _ in seen["recent"]] == ["is-active", "is-stopped", "is-failed", "is-done"]
        # the outcome is in words for a screen reader, not only a glyph
        assert seen["recent"][2][1].startswith("didn't finish: two")
        assert seen["recent"][0][1].endswith("running")

    def test_it_keeps_to_the_last_five(self, browser_ok):
        for i in range(8):
            _finished(f"task {i}")
        seen = _render(lambda page: page.evaluate(HOME), script=_ui.bridge(_poll()))
        assert len(seen["recent"]) == 5 and "task 7" in seen["recent"][0][1]

    def test_empty_it_says_what_will_appear(self, browser_ok):
        seen = _render(lambda page: page.evaluate(HOME), script=_ui.bridge(_poll()))
        assert seen["recent"] == [["muted", "Nothing yet. What you ask shows up here."]]


# ============================================================ waiting for you

class TestWaitingForYou:
    def test_nothing_waiting_says_so(self, browser_ok):
        seen = _render(lambda page: page.evaluate(HOME), script=_ui.bridge(_poll()))
        assert seen["waiting"] == [["muted", "Nothing needs you right now."]]
        assert seen["waitCount"] == ""

    def test_a_setup_problem_is_put_in_front_of_you(self, browser_ok):
        warning = {"id": "api-key", "text": "No Gemini API key, so only built-in commands work.",
                   "fix": "Add GEMINI_API_KEY to the .env file, then restart Little."}
        seen = _render(lambda page: page.evaluate(HOME),
                       script=_ui.bridge(_poll(warnings=[warning])))
        assert seen["waiting"][0][0] == "is-warn"
        assert "GEMINI_API_KEY" in seen["waiting"][0][1]
        assert seen["waitCount"] == "1"

    def test_a_failed_task_offers_to_try_again(self, browser_ok):
        _finished("find jobs for me", tasks.FAILED, error="I can't reach the internet right now.")

        async def check(page):
            before = await page.evaluate(HOME)
            await page.click("#waitList button:has-text('Try again')")
            await page.wait_for_timeout(100)
            return before, await page.evaluate(HOME)

        before, after = _render(check, script=_ui.bridge(_poll()))
        assert before["waiting"][0][0] == "is-failed"
        assert "Didn't finish: “find jobs for me”" in before["waiting"][0][1]
        assert "I can't reach the internet right now." in before["waiting"][0][1]
        assert after["calls"] == [["send", "find jobs for me"]]
        assert after["waiting"] == [["muted", "Nothing needs you right now."]]

    def test_dismiss_only_hides_it(self, browser_ok):
        _finished("find jobs for me", tasks.FAILED, error="offline")

        async def check(page):
            await page.click("#waitList button:has-text('Dismiss')")
            return await page.evaluate(HOME)

        seen = _render(check, script=_ui.bridge(_poll()))
        assert seen["calls"] == [] and seen["waitCount"] == ""

    def test_an_update_doesnt_knock_keyboard_focus_off_a_button(self, browser_ok):
        """The list re-renders whenever a task changes. Someone tabbing to a
        Dismiss button mustn't find focus thrown back to the top of the page."""
        _finished("first failure", tasks.FAILED, error="x")
        second = _finished("second failure", tasks.FAILED, error="y")
        first = _poll()
        _finished("something else that finished meanwhile")
        later = _poll(since=first["tasks"]["v"])
        script = _ui.bridge(first) + "window.__later = %s;" % __import__("json").dumps(later)

        async def check(page):
            await page.focus(f'[data-key="dismiss-{second}"]')
            await page.evaluate("window.__queue.push(window.__later)")
            await page.wait_for_timeout(450)
            return {"focus": await page.evaluate("document.activeElement.dataset.key || ''"),
                    "recent": (await page.evaluate(HOME))["recent"][0][1]}

        seen = _render(check, script=script)
        assert "something else" in seen["recent"], "the update did arrive"
        assert seen["focus"] == f"dismiss-{second}"

    def test_the_dismiss_button_names_what_it_dismisses(self, browser_ok):
        _finished("find jobs for me", tasks.FAILED, error="offline")
        seen = _render(lambda page: page.get_by_role(
            "button", name="Dismiss “find jobs for me”").count(), script=_ui.bridge(_poll()))
        assert seen == 1


# ================================================================ the orb

class TestTheOrbShowsRealOutcomes:
    def _sequence(self, *polls):
        script = _ui.bridge(polls[0])
        return script + "window.__queue.push(...%s);" % __import__("json").dumps(list(polls[1:]))

    def _flash_after(self, *polls):
        async def check(page):
            for _ in range(20):
                flash = await page.evaluate("document.body.dataset.flash || null")
                if flash:
                    return flash
                await page.wait_for_timeout(50)
            return None
        return _render(check, script=self._sequence(*polls), wait_ms=300)

    def test_a_task_that_finishes_done_shows_success(self, browser_ok):
        tid = tasks.start("what's the time")
        first = _poll("executing")
        v = first["tasks"]["v"]
        tasks.finish(tasks.DONE, task_id=tid)
        assert self._flash_after(first, _poll(since=v)) == "success"

    def test_a_task_that_fails_shows_the_error_sign(self, browser_ok):
        tid = tasks.start("find jobs")
        first = _poll("executing")
        v = first["tasks"]["v"]
        tasks.finish(tasks.FAILED, "offline", task_id=tid)
        assert self._flash_after(first, _poll(since=v)) == "error"

    def test_a_stopped_task_shows_neither(self, browser_ok):
        tid = tasks.start("do a long thing")
        first = _poll("executing")
        v = first["tasks"]["v"]
        tasks.finish(tasks.STOPPED, task_id=tid)
        assert self._flash_after(first, _poll(since=v)) is None

    def test_one_that_starts_and_ends_between_two_polls_still_counts(self, browser_ok):
        first = _poll()
        _finished("what's the time")
        assert self._flash_after(first, _poll(since=first["tasks"]["v"])) == "success"

    def test_history_already_over_when_the_page_opened_shows_nothing(self, browser_ok):
        _finished("old one")
        _finished("older failure", tasks.FAILED, error="x")
        assert self._flash_after(_poll()) is None


# =================================================================== safety

class TestTaskTextIsText:
    def test_nothing_from_a_task_runs_as_markup(self, browser_ok):
        tid = tasks.start(ATTACK)
        tasks.step_finished(tasks.step_started(ATTACK, ATTACK))
        tasks.finish(tasks.FAILED, ATTACK, task_id=tid)
        tasks.start(ATTACK)
        tasks.step_started(ATTACK, ATTACK)

        async def check(page):
            return {"images": await page.evaluate("document.querySelectorAll('.home img').length"),
                    "ran": await page.evaluate("window.__ran || 0"),
                    **await page.evaluate(HOME)}

        seen = _render(check, script=_ui.bridge(_poll()))
        assert seen["images"] == 0 and seen["ran"] == 0
        assert ATTACK in seen["nowText"] and ATTACK in seen["waiting"][0][1]

    def test_a_malformed_task_is_skipped_not_fatal(self, browser_ok):
        poll = _poll()
        poll["tasks"]["changed"] = [{"id": "x"}, None, {"id": 3, "status": "done"}, 7]
        seen = _render(lambda page: page.evaluate(HOME), script=_ui.bridge(poll))
        assert seen["recent"] == [["muted", "Nothing yet. What you ask shows up here."]]


# ================================================================== layout

class TestHomeFits:
    @pytest.mark.parametrize("size", [(1040, 660), (1280, 800), (1920, 1080)],
                             ids=lambda s: f"{s[0]}x{s[1]}")
    def test_a_busy_home_still_fits(self, browser_ok, size):
        """The hero at its tallest — a task with steps — plus a warning and a
        failure waiting, on every window size the app allows."""
        _finished("find jobs for me", tasks.FAILED, error="I can't reach the internet right now.")
        tasks.start("summarise the readme in my project and list every todo item it mentions")
        tasks.route("model")
        for name in ("list_dir", "read_file", "search_files", "read_file"):
            tasks.step_finished(tasks.step_started(name))
        warning = {"id": "api-key", "text": "No Gemini API key.", "fix": "Add it to .env."}

        async def check(page):
            return await page.evaluate("""() => ({
              spilling: [...document.querySelectorAll('.home .panel')]
                .filter(p => !p.classList.contains('feedwrap') && p.scrollHeight > p.clientHeight + 1)
                .map(p => p.querySelector('h2').textContent),
              feed: document.getElementById('feed').getBoundingClientRect().height,
              clear: ['.left', '.center', '.right'].every(sel =>
                document.querySelector(sel).getBoundingClientRect().bottom
                  <= document.querySelector('.cmdbar').getBoundingClientRect().top),
              sideways: document.documentElement.scrollWidth > window.innerWidth,
            })""")

        seen = _render(check, script=_ui.bridge(_poll("executing", warnings=[warning])),
                       viewport=size)
        assert seen["spilling"] == []
        assert seen["feed"] >= 80, "Activity keeps room to read"
        assert seen["clear"] and not seen["sideways"]


# ============================================================== end to end

class TestARealCommandEndToEnd:
    """A command runs through the real assistant and the real bridge. What
    the bridge hands over is replayed into the page, poll by poll."""

    def _run(self, monkeypatch, command):
        monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
        original = permissions.confirm_fn
        api = bridge.Api()
        api.jarvis.muted = True
        try:
            payloads, since = [], 0
            api.poll(0)                                     # the greeting lines, if any
            api.send(command)
            for _ in range(300):
                out = api.poll(since)
                since = out["tasks"]["v"]
                payloads.append(out)
                if any(t["status"] in tasks.ENDED for t in out["tasks"]["changed"]):
                    break
                time.sleep(0.01)
            payloads.append(api.poll(since))               # the reply line can trail the task
            return payloads
        finally:
            permissions.set_confirm(original)

    def _replay(self, payloads):
        opening = {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}
        script = _ui.bridge(opening) + "window.__queue.push(...%s);" % __import__("json").dumps(payloads)

        async def check(page):
            # Sample the orb until every recorded poll has been replayed (one
            # per 200 ms) and a little after, so a short flash can't be missed.
            flash, after = None, 0
            for _ in range(400):
                flash = flash or await page.evaluate("document.body.dataset.flash || null")
                if await page.evaluate("window.__queue.length === 0"):
                    after += 1
                    if after > 12:
                        break
                await page.wait_for_timeout(25)
            return {"flash": flash, **await page.evaluate(HOME), "rows": await page.evaluate(
                "[...document.querySelectorAll('#feed .row')].map(r => [r.className, r.querySelector('.m').textContent])")}
        return _render(check, script=script, wait_ms=250)

    def test_a_local_command_shows_up_done_on_home(self, browser_ok, monkeypatch):
        payloads = self._run(monkeypatch, "what's the time")
        seen = self._replay(payloads)
        assert ["row you", "what's the time"] in seen["rows"]
        assert any(cls == "row assistant" and text.startswith("It's ") for cls, text in seen["rows"])
        assert seen["recent"][0][0] == "is-done" and "what's the time" in seen["recent"][0][1]
        assert seen["last"].startswith("Last: “what's the time” · done")
        assert seen["flash"] == "success"

    def test_a_command_that_cant_be_done_shows_up_failed_and_waits_for_you(self, browser_ok, monkeypatch):
        # With no microphone started, recalibrating can't happen — a real,
        # harmless failure.
        payloads = self._run(monkeypatch, "recalibrate mic")
        seen = self._replay(payloads)
        assert seen["recent"][0][0] == "is-failed"
        assert "Didn't finish: “recalibrate mic”" in seen["waiting"][-1][1]
        assert "The mic isn't on yet." in seen["waiting"][-1][1]
        assert seen["flash"] == "error"
