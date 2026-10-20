"""The Task Center (UI-5): every task's honest timeline, and a way to stop
one that's running.

The plan's test for this phase: a planned task shows its steps, and cancel
stops it. Stopping is a request honoured between steps — before the model
is asked again, before each tool, before each plan step — so these tests
check both that it stops and that nothing is pretended: a tool already
running finishes, and what ran stays in the record.
"""
from __future__ import annotations

import threading
import time

import pytest

from jarvis.ai import brain as brain_module
from jarvis.ai import planner
from jarvis.app import assistant, bridge, tasks
from jarvis.tools import permissions, registry


@pytest.fixture(autouse=True)
def fresh():
    tasks.reset()
    planner._cancel.clear()
    yield
    tasks.reset()


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
    made = assistant.Jarvis(log_fn=lambda _l: None)
    made.muted = True
    return made


def _wait_for(predicate, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _model(monkeypatch, *responses):
    """The model, answering from a script. Returns the list of payloads it
    was sent, so a test can count the calls."""
    queue, sent = list(responses), []

    def call(payload):
        sent.append(payload)
        return queue.pop(0)
    monkeypatch.setattr(brain_module, "call_gemini", call)
    return sent


def _calls(*names):
    return {"candidates": [{"content": {"parts": [
        {"functionCall": {"name": n, "args": {"n": i}}} for i, n in enumerate(names)]}}]}


def _text(t):
    return {"candidates": [{"content": {"parts": [{"text": t}]}}]}


def _alternates(history):
    roles = [m["role"] for m in history]
    return all(a != b for a, b in zip(roles, roles[1:])) and roles[-1] == "model"


# ========================================================== plans recorded

class ToolPerStep:
    """A brain that runs one real tool (through the registry) per plan step."""

    def __init__(self, fail_on=None, stop_in=None, stop_after=None):
        self.n = 0
        self.fail_on, self.stop_in, self.stop_after = fail_on, stop_in, stop_after

    def ask(self, text, on_action=None):
        self.n += 1
        if self.n == self.stop_in:
            raise tasks.Stopped()
        registry.execute_tool("fake_tool", {"step": self.n})
        if self.n == self.stop_after:
            tasks.request_stop(tasks.current_id())
        if self.n == self.fail_on or (isinstance(self.fail_on, set) and self.n in self.fail_on):
            return "FAILED: npm isn't installed"
        return f"Step {self.n} done."


@pytest.fixture
def planned(monkeypatch, bot):
    monkeypatch.setattr(planner, "ask_text",
                        lambda *_a, **_k: "1. Make the app\n2. Install packages\n3. Run it")
    monkeypatch.setitem(registry.FUNCTIONS, "fake_tool", lambda **_k: "ok")
    return bot


class TestAPlannedTaskShowsItsSteps:
    def test_the_plan_and_each_steps_tools_are_recorded(self, planned):
        planned.brain = ToolPerStep()
        planned.handle("create a react app and run it")
        task = tasks.recent(1)[0]
        assert task["route"] == "plan" and task["status"] == tasks.DONE
        assert [(p["text"], p["status"]) for p in task["plan"]] == [
            ("Make the app", "done"), ("Install packages", "done"), ("Run it", "done")]
        assert [(s["name"], s["part"]) for s in task["steps"]] == [
            ("fake_tool", 1), ("fake_tool", 2), ("fake_tool", 3)]
        ats = [s["at"] for s in task["steps"]]
        assert ats == sorted(ats) and all(a >= 0 for a in ats)
        assert task["part"] is None, "nothing is running once it's done"

    def test_a_failed_step_is_marked_and_the_rest_never_started(self, planned):
        # Chapter 32: step 2 fails, and fails again on its one more try.
        planned.brain = ToolPerStep(fail_on={2, 3})
        planned.handle("create a react app and run it")
        task = tasks.recent(1)[0]
        assert task["status"] == tasks.FAILED
        assert [p["status"] for p in task["plan"]] == ["done", "failed", "pending"]
        assert [s["part"] for s in task["steps"]] == [1, 2, 2], "the retry is recorded under its step"

    def test_a_request_the_planner_calls_simple_has_no_plan(self, planned, monkeypatch):
        monkeypatch.setattr(planner, "ask_text", lambda *_a, **_k: "SIMPLE")
        planned.brain = ToolPerStep()
        planned.handle("create a react app and run it")
        assert tasks.recent(1)[0]["plan"] is None

    def test_plan_state_is_only_what_it_can_be(self):
        tasks.start("x")
        tasks.plan(["a", "b"])
        tasks.plan_step(1, "exploded")
        tasks.plan_step(9, "done")
        tasks.plan_step(0, "done")
        assert [p["status"] for p in tasks.current()["plan"]] == ["pending", "pending"]


# ================================================================ stopping

class TestAPlanStops:
    def test_between_steps(self, planned):
        planned.brain = ToolPerStep(stop_after=1)
        planned.handle("create a react app and run it")
        task = tasks.recent(1)[0]
        assert task["status"] == tasks.STOPPED
        assert [p["status"] for p in task["plan"]] == ["done", "pending", "pending"]
        assert len(task["steps"]) == 1, "steps 2 and 3 never ran"
        assert task["reply"] == "Stopped after step 1 of 3."
        assert task["stopping"] and task["stop_at"] >= 0

    def test_partway_through_a_step(self, planned):
        planned.brain = ToolPerStep(stop_in=2)
        planned.handle("create a react app and run it")
        task = tasks.recent(1)[0]
        assert task["status"] == tasks.STOPPED
        assert [p["status"] for p in task["plan"]] == ["done", "stopped", "pending"]
        assert task["reply"] == "Stopped during step 2 of 3."


class TestTheModelStops:
    @pytest.fixture
    def tools(self, monkeypatch):
        ran = []

        def stopper(**k):
            ran.append(("stopper", k))
            tasks.request_stop(tasks.current_id())       # you press Stop while it runs
            return "ok"

        monkeypatch.setitem(registry.FUNCTIONS, "stopper", stopper)
        monkeypatch.setitem(registry.FUNCTIONS, "second", lambda **k: ran.append(("second", k)) or "ok")
        return ran

    def test_before_asking_the_model_again(self, bot, monkeypatch, tools):
        sent = _model(monkeypatch, _calls("stopper"), _text("never reached"))
        bot.brain = brain_module.Brain()
        bot.handle("tidy my project folder")
        task = tasks.recent(1)[0]
        assert task["status"] == tasks.STOPPED and task["reply"] == "Stopped."
        assert len(sent) == 1, "the model wasn't asked again"
        assert tools == [("stopper", {"n": 0})]
        assert [s["name"] for s in task["steps"]] == ["stopper"], "what ran stays in the record"

    def test_before_the_next_tool_in_the_same_answer(self, bot, monkeypatch, tools):
        _model(monkeypatch, _calls("stopper", "second"))
        bot.brain = brain_module.Brain()
        bot.handle("tidy my project folder")
        assert tools == [("stopper", {"n": 0})], "the second tool never ran"
        told = bot.brain.history[-2]["parts"][1]["functionResponse"]["response"]["result"]
        assert told == brain_module.NOT_RUN, "the model is told it didn't run"

    def test_the_conversation_carries_on_afterwards(self, bot, monkeypatch, tools):
        _model(monkeypatch, _calls("stopper"), _text("Hello again."))
        bot.brain = brain_module.Brain()
        bot.handle("tidy my project folder")
        assert _alternates(bot.brain.history), "every tool call answered, the model last"
        assert bot.brain.history[-1]["parts"] == [{"text": brain_module.STOPPED_NOTE}]
        bot.handle("hello")
        assert tasks.recent(1)[0]["reply"] == "Hello again."
        assert _alternates(bot.brain.history)

    def test_a_stop_already_asked_for_means_no_call_at_all(self, monkeypatch):
        sent = _model(monkeypatch, _text("never"))
        tasks.start("x")
        tasks.request_stop(tasks.current_id())
        b = brain_module.Brain()
        with pytest.raises(tasks.Stopped):
            b.ask("hello")
        assert sent == [] and _alternates(b.history)

    def test_a_stop_is_not_a_failure(self, bot, monkeypatch, tools):
        _model(monkeypatch, _calls("stopper"))
        bot.brain = brain_module.Brain()
        bot.handle("tidy my project folder")
        assert tasks.recent(1)[0]["error"] == ""


class TestEscapeAndSayingStop:
    def test_saying_stop_stops_the_other_task_not_itself(self, bot, monkeypatch):
        go, started = threading.Event(), threading.Event()

        def slow(**_k):
            started.set()
            go.wait(3)
            return "ok"

        monkeypatch.setitem(registry.FUNCTIONS, "slow", slow)
        _model(monkeypatch, _calls("slow"), _text("never reached"))
        bot.brain = brain_module.Brain()
        worker = threading.Thread(target=bot.handle, args=("tidy my project folder",))
        worker.start()
        assert started.wait(3)

        bot.handle("stop")                     # from another thread, as the voice loop would
        go.set()
        worker.join(3)

        by_text = {t["text"]: t for t in tasks.recent(10)}
        assert by_text["tidy my project folder"]["status"] == tasks.STOPPED
        assert by_text["stop"]["status"] == tasks.DONE
        assert by_text["stop"]["stopping"] is False
        assert by_text["tidy my project folder"]["steps"][0]["status"] == "done", \
            "the tool that was running finished; nothing pretends it was cut off"

    def test_the_stop_button_from_the_window_stops_what_is_open(self):
        tid = tasks.start("something long")
        tasks.route("model")
        box = {}
        t = threading.Thread(target=lambda: box.setdefault("stopped", tasks.stop_open()))
        t.start(); t.join()
        assert box["stopped"] == [tid] and tasks.stop_requested(tid)

    def test_a_finished_task_cant_be_asked_to_stop(self):
        tid = tasks.start("x")
        tasks.finish(tasks.DONE)
        assert tasks.request_stop(tid) is False


# ============================================================ the bridge

class TestStopThis:
    @pytest.fixture
    def api(self, monkeypatch):
        monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
        original = permissions.confirm_fn

        class Quiet:
            muted, running = True, False
            def handle(self, text): ...

        yield bridge.Api(assistant=Quiet())
        permissions.set_confirm(original)

    def _open(self, route):
        box = {}
        release = threading.Event()

        def work():
            box["id"] = tasks.start("working")
            tasks.route(route)
            release.wait(3)

        t = threading.Thread(target=work, daemon=True)
        t.start()
        assert _wait_for(lambda: "id" in box)
        return box["id"], release

    def test_a_model_task_is_asked_to_stop(self, api):
        tid, release = self._open("model")
        assert api.cancel(tid) == ""
        assert tasks.stop_requested(tid)
        assert api.cancel(tid) == "It's already stopping."
        release.set()

    def test_a_plan_is_asked_to_stop(self, api):
        tid, release = self._open("plan")
        assert api.cancel(tid) == "" and tasks.stop_requested(tid)
        release.set()

    def test_a_local_command_says_it_cant_be_stopped_partway(self, api):
        tid, release = self._open("local")
        assert "can't be stopped partway" in api.cancel(tid)
        assert not tasks.stop_requested(tid)
        release.set()

    def test_a_finished_one_says_so(self, api):
        tid = tasks.start("x"); tasks.route("model"); tasks.finish(tasks.DONE)
        assert api.cancel(tid) == "That one has already finished."

    @pytest.mark.parametrize("bad", ["1", True, None, 999, 1.5])
    def test_only_a_real_task(self, api, bad):
        assert api.cancel(bad) == "That one has already finished."

    def test_a_question_it_is_waiting_on_is_answered_no(self, api):
        box = {}

        def work():
            box["id"] = tasks.start("delete notes.txt")
            tasks.route("model")
            box["ok"] = permissions.confirm("Delete notes.txt?")
            try:
                tasks.check_stop()
                tasks.finish(tasks.DONE)
            except tasks.Stopped:
                tasks.finish(tasks.STOPPED)

        t = threading.Thread(target=work, daemon=True)
        t.start()
        assert _wait_for(lambda: "id" in box and tasks.get(box["id"])["status"] == tasks.WAITING)
        assert api.cancel(box["id"]) == ""
        t.join(3)
        task = tasks.get(box["id"])
        assert box["ok"] is False, "stopping answered its question No"
        assert task["status"] == tasks.STOPPED
        assert task["steps"][-1]["detail"] == "declined"
        assert task["steps"][-1]["question"] == "Delete notes.txt?"


# ========================================================== in a browser

import json  # noqa: E402

import _ui  # noqa: E402

ATTACK = '<img src=x onerror="window.__ran=1">'


@pytest.fixture(scope="module")
def browser_ok():
    if not _ui.available():
        pytest.skip("Playwright isn't installed")


def _render(check, **kw):
    kw.setdefault("route", "tasks")
    result, errors = _ui.open_panel(check, **kw)
    if result is _ui.NO_BROWSER:
        pytest.skip("no browser to render the panel with")
    assert errors == [], errors
    return result


def _stats():
    return {
        "identity": {"name": "LITTLE", "call": "Little"}, "system": {"available": False},
        "session": {"uptime": "0", "commands": 0, "tools": 0, "os": "Windows 11"},
        "voice": {"mic": "on", "speech": "on", "voice": "Neerja", "lang": "en-IN", "model": "m"},
        "tools": [], "reminders": [], "plan": None, "browser": "closed", "contacts": 0,
        "workspace": "C:/w", "warnings": [],
    }


def _poll(since=0, status="listening"):
    version, changed = tasks.changed_since(since)
    return {"status": status, "lines": [], "stats": _stats(),
            "tasks": {"v": version, "changed": changed}}


def _task(text, status=tasks.DONE, route="model", steps=(), reply="ok", error=""):
    tid = tasks.start(text)
    tasks.route(route)
    for name, detail in steps:
        tasks.step_finished(tasks.step_started(name, detail))
    tasks.reply(reply)
    if status in tasks.ENDED:
        tasks.finish(status, error)
    return tid


TC = """() => ({
  filters: Object.fromEntries([...document.querySelectorAll('#tcFilters [data-filter]')].map(b =>
    [b.dataset.filter, [b.getAttribute('aria-pressed'), b.querySelector('.count').textContent]])),
  list: [...document.querySelectorAll('#tcList .tc-item')].map(b => [Number(b.dataset.task),
    b.className.replace('tc-item ', ''), b.getAttribute('aria-current')]),
  empty: document.getElementById('tcEmpty').hidden ? null : document.getElementById('tcEmpty').textContent,
  title: document.querySelector('#tcDetail .tc-title') ? document.querySelector('#tcDetail .tc-title').textContent : null,
  meta: document.querySelector('#tcDetail .tc-meta') ? document.querySelector('#tcDetail .tc-meta').textContent : null,
  stop: !!document.querySelector('#tcDetail [data-key="stop"]'),
  note: document.querySelector('#tcDetail .tc-note') ? document.querySelector('#tcDetail .tc-note').textContent : null,
  timeline: [...document.querySelectorAll('#tcDetail .timeline:not(.timeline--inner) > .tl')].map(li => ({
    kind: [...li.classList].find(c => c.startsWith('tl--')).slice(4),
    state: [...li.classList].find(c => c.startsWith('is-')).slice(3),
    at: li.querySelector(':scope > .tl-at').textContent,
    title: li.querySelector(':scope > .tl-body > .tl-title').textContent,
    detail: li.querySelector(':scope > .tl-body > .tl-detail') ? li.querySelector(':scope > .tl-body > .tl-detail').textContent : null,
    inner: [...li.querySelectorAll('.timeline--inner > .tl')].map(s => [
      [...s.classList].find(c => c.startsWith('is-')).slice(3),
      s.querySelector('.tl-title').textContent]),
  })),
  status: document.getElementById('tcStatus').textContent,
  calls: window.__calls,
  hash: location.hash,
  focus: document.activeElement.dataset.key || document.activeElement.id || '',
})"""


def _replay(payloads, check_extra=None):
    opening = {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}
    script = _ui.bridge(opening) + "window.__queue.push(...%s);" % json.dumps(payloads)

    async def check(page):
        for _ in range(300):
            if await page.evaluate("window.__queue.length === 0"):
                break
            await page.wait_for_timeout(25)
        await page.wait_for_timeout(300)
        return await page.evaluate(TC)
    return _render(check, script=script, wait_ms=250)


def _run_through_the_bridge(monkeypatch, command, brain, stop_when=None):
    """Run a command for real — assistant, planner, registry, bridge — and
    record every poll. `stop_when(task)` presses Stop (the bridge's cancel)
    the first time it's true."""
    monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
    original = permissions.confirm_fn
    api = bridge.Api()
    api.jarvis.muted = True
    api.jarvis.brain = brain
    payloads, since, pressed = [], 0, None
    try:
        api.poll(0)
        api.send(command)
        for _ in range(600):
            out = api.poll(since)
            since = out["tasks"]["v"]
            payloads.append(out)
            for task in out["tasks"]["changed"]:
                if stop_when and pressed is None and stop_when(task):
                    pressed = api.cancel(task["id"])
            if any(t["status"] in tasks.ENDED for t in out["tasks"]["changed"]):
                break
            time.sleep(0.01)
    finally:
        permissions.set_confirm(original)
    return payloads, pressed


class TestThePhasesOwnTests:
    def test_a_planned_task_shows_its_steps(self, browser_ok, planned, monkeypatch):
        payloads, _ = _run_through_the_bridge(monkeypatch, "create a react app and run it", ToolPerStep())
        seen = _replay(payloads)
        kinds = [(e["kind"], e["state"], e["title"]) for e in seen["timeline"]]
        assert kinds[0] == ("start", "done", "You typed it")
        assert kinds[1] == ("route", "done", "Planned it: 3 steps")
        plan = [e for e in seen["timeline"] if e["kind"] == "plan"]
        assert [p["title"] for p in plan] == ["Step 1 of 3 · Make the appdone",
                                             "Step 2 of 3 · Install packagesdone",
                                             "Step 3 of 3 · Run itdone"]
        assert all([s[0] for s in p["inner"]] == ["done"] for p in plan), "each step shows the tool it ran"
        assert all(p["inner"][0][1].startswith("fake_tool") for p in plan)
        assert seen["timeline"][-1]["kind"] == "end" and seen["timeline"][-1]["title"].startswith("Done in ")

    def test_stopping_stops_it(self, browser_ok, planned, monkeypatch):
        class Slow(ToolPerStep):
            def ask(self, text, on_action=None):
                time.sleep(0.15)                          # a step that takes a moment
                return super().ask(text, on_action)

        running_step_1 = lambda t: t["plan"] and t["plan"][0]["status"] == "running"
        payloads, pressed = _run_through_the_bridge(
            monkeypatch, "create a react app and run it", Slow(), stop_when=running_step_1)
        assert pressed == "", "the bridge accepted the stop"

        task = tasks.recent(1)[0]
        assert task["status"] == tasks.STOPPED
        assert [p["status"] for p in task["plan"]] == ["done", "pending", "pending"]
        assert len(task["steps"]) == 1, "steps 2 and 3 never ran"

        seen = _replay(payloads)
        titles = [e["title"] for e in seen["timeline"]]
        assert "You asked it to stop" in titles
        assert seen["timeline"][-1]["state"] == "stopped" and seen["timeline"][-1]["title"] == "Stopped"
        plan = [e for e in seen["timeline"] if e["kind"] == "plan"]
        assert [p["state"] for p in plan] == ["done", "pending", "pending"]
        assert plan[1]["title"].endswith("not started")
        assert seen["list"][0][1] == "is-stopped"


class TestTheTimelineIsHonest:
    def test_a_local_command_has_no_steps_it_didnt_take(self, browser_ok):
        _task("what's the time", route="local", reply="It's 8.")
        seen = _render(lambda page: page.evaluate(TC), script=_ui.bridge(_poll()))
        assert [(e["kind"], e["title"]) for e in seen["timeline"]] == [
            ("start", "You typed it"), ("route", "Answered on this computer"), ("end", seen["timeline"][-1]["title"])]
        assert seen["timeline"][-1]["title"].startswith("Done in ")
        assert seen["timeline"][-1]["detail"] == "It's 8."

    def test_tools_show_their_arguments_timing_and_failures(self, browser_ok):
        tid = tasks.start("read my notes")
        tasks.route("model")
        tasks.step_finished(tasks.step_started("list_dir", '{"path": "notes"}'))
        tasks.step_finished(tasks.step_started("read_file", '{"path": "a.txt"}'), error="FileNotFoundError: a.txt")
        tasks.reply("I couldn't find a.txt.")
        tasks.finish(tasks.DONE, task_id=tid)
        seen = _render(lambda page: page.evaluate(TC), script=_ui.bridge(_poll()))
        tools = [e for e in seen["timeline"] if e["kind"] == "tool"]
        assert [(t["state"], t["detail"]) for t in tools] == [
            ("done", '{"path": "notes"}'), ("error", "FileNotFoundError: a.txt")]
        assert all(t["at"].startswith("+") and t["at"].endswith("s") for t in tools)

    def test_a_question_and_your_answer_are_on_it(self, browser_ok):
        tasks.start("delete the build folder")
        tasks.route("model")
        tasks.waiting("Delete project/build? This can't be undone.")
        tasks.answered(False)
        tasks.reply("Left it.")
        tasks.finish(tasks.DONE)
        seen = _render(lambda page: page.evaluate(TC), script=_ui.bridge(_poll()))
        (answer,) = [e for e in seen["timeline"] if e["kind"] == "answer"]
        assert answer["title"] == "You declined" and answer["state"] == "declined"
        assert answer["detail"] == "Delete project/build? This can't be undone."

    def test_waiting_and_running_say_so(self, browser_ok):
        tasks.start("delete the build folder"); tasks.route("model")
        tasks.waiting("Delete project/build?")
        seen = _render(lambda page: page.evaluate(TC), script=_ui.bridge(_poll()))
        assert seen["timeline"][-1]["title"] == "Waiting for your answer"
        assert seen["timeline"][-1]["detail"] == "Delete project/build?"

    def test_an_asked_again_task_says_why_it_ran(self, browser_ok):
        first = _task("tell me a joke")
        tasks.start("tell me a joke", again_of=first); tasks.route("model"); tasks.finish(tasks.DONE)
        seen = _render(lambda page: page.evaluate(TC), script=_ui.bridge(_poll()))
        assert seen["timeline"][0]["detail"] == "Asked again, for a fresh answer"


class TestStopThisInThePage:
    def _open(self, route):
        tid = tasks.start("working on it")
        tasks.route(route)
        return tid

    def test_offered_on_a_model_task_and_it_asks_python_by_id(self, browser_ok):
        tid = self._open("model")

        async def check(page):
            before = await page.evaluate(TC)
            await page.click('#tcDetail [data-key="stop"]')
            await page.wait_for_timeout(60)
            return before, await page.evaluate(TC)

        before, after = _render(check, script=_ui.bridge(_poll()))
        assert before["stop"] is True
        assert after["calls"] == [["cancel", tid]]
        assert after["status"] == "Asked it to stop. It will at its next step."

    def test_what_python_says_back_is_shown(self, browser_ok):
        self._open("plan")
        script = _ui.bridge(_poll()) + "window.__answers = {cancel: 'That one has already finished.'};"

        async def check(page):
            await page.click('#tcDetail [data-key="stop"]')
            await page.wait_for_timeout(60)
            return await page.evaluate(TC)

        assert _render(check, script=script)["status"] == "That one has already finished."

    def test_a_local_command_says_why_there_is_no_button(self, browser_ok):
        self._open("local")
        seen = _render(lambda page: page.evaluate(TC), script=_ui.bridge(_poll()))
        assert seen["stop"] is False and "can't be stopped partway" in seen["note"]

    def test_one_already_stopping_says_so(self, browser_ok):
        tid = self._open("model")
        tasks.request_stop(tid)
        seen = _render(lambda page: page.evaluate(TC), script=_ui.bridge(_poll()))
        assert seen["stop"] is False and seen["note"] == "Stopping at its next step."
        assert "You asked it to stop" in [e["title"] for e in seen["timeline"]]

    def test_not_on_a_finished_task(self, browser_ok):
        _task("x")
        seen = _render(lambda page: page.evaluate(TC), script=_ui.bridge(_poll()))
        assert seen["stop"] is False and seen["note"] is None


class TestFindingTasks:
    def test_filters_count_and_narrow_the_list(self, browser_ok):
        _task("a"); _task("b", tasks.FAILED, error="x"); _task("c", tasks.STOPPED)
        tasks.start("d"); tasks.route("model")

        async def check(page):
            everything = await page.evaluate(TC)
            await page.click('[data-filter="failed"]')
            failed = await page.evaluate(TC)
            await page.click('[data-filter="waiting"]')
            return everything, failed, await page.evaluate(TC)

        everything, failed, waiting = _render(check, script=_ui.bridge(_poll()))
        assert {k: v[1] for k, v in everything["filters"].items()} == {
            "all": "4", "active": "1", "waiting": "0", "done": "1", "failed": "1", "stopped": "1"}
        assert [cls for _, cls, _ in failed["list"]] == ["is-failed"]
        assert failed["filters"]["failed"][0] == "true" and failed["filters"]["all"][0] == "false"
        assert waiting["list"] == [] and waiting["empty"] == "Nothing is waiting for you."

    def test_it_shows_the_task_in_hand_until_you_pick_one(self, browser_ok):
        done = _task("finished one")
        running = tasks.start("running one"); tasks.route("model")
        first = _poll()
        tasks.finish(tasks.DONE, task_id=running)
        newer = tasks.start("a newer one"); tasks.route("model")
        later = _poll(since=first["tasks"]["v"])
        script = _ui.bridge(first) + "window.__later = %s;" % json.dumps(later)

        async def check(page):
            shown_first = (await page.evaluate(TC))["title"]
            await page.click(f'#tcList [data-task="{done}"]')
            await page.evaluate("window.__queue.push(window.__later)")
            await page.wait_for_timeout(450)
            return shown_first, await page.evaluate(TC)

        shown_first, after = _render(check, script=script)
        assert shown_first == "“running one”"
        assert after["title"] == "“finished one”", "your pick stays put as new tasks arrive"
        assert [row[0] for row in after["list"]][0] == newer
        assert [row for row in after["list"] if row[2] == "true"][0][0] == done

    def test_with_nothing_yet_it_says_what_will_appear(self, browser_ok):
        seen = _render(lambda page: page.evaluate(TC), script=_ui.bridge(_poll()))
        assert seen["list"] == [] and seen["empty"].startswith("No tasks yet.")

    def test_homes_recent_opens_a_task_here(self, browser_ok):
        tid = _task("what's the time", route="local")
        _task("something later")

        async def check(page):
            await page.click(f'[data-key="recent-{tid}"]')
            await page.wait_for_timeout(150)
            return await page.evaluate(TC)

        seen = _render(check, script=_ui.bridge(_poll()), route="home")
        assert seen["hash"] == "#/tasks" and seen["title"] == "“what's the time”"

    def test_show_in_chat_goes_to_the_turn(self, browser_ok):
        _task("tell me a joke")

        async def check(page):
            await page.click('#tcDetail [data-key="chat"]')
            await page.wait_for_timeout(150)
            return await page.evaluate(TC)

        assert _render(check, script=_ui.bridge(_poll()))["hash"] == "#/chat"

    def test_picking_with_the_keyboard_and_keeping_focus_through_updates(self, browser_ok):
        a = _task("first"); b = _task("second")
        first = _poll()
        _task("third")
        later = _poll(since=first["tasks"]["v"])
        script = _ui.bridge(first) + "window.__later = %s;" % json.dumps(later)

        async def check(page):
            await page.focus(f'#tcList [data-key="task-{b}"]')
            await page.keyboard.press("Tab")                    # on to "first"
            await page.keyboard.press("Enter")
            await page.evaluate("window.__queue.push(window.__later)")
            await page.wait_for_timeout(450)
            return await page.evaluate(TC)

        seen = _render(check, script=script)
        assert seen["title"] == "“first”"
        assert seen["focus"] == f"task-{a}", "focus stays on the row you picked"
        assert len(seen["list"]) == 3, "the update arrived"


class TestSafeAndFits:
    def test_nothing_from_a_task_runs_as_markup(self, browser_ok):
        tid = tasks.start(ATTACK)
        tasks.route("plan")
        tasks.plan([ATTACK, ATTACK])
        tasks.plan_step(1, "running")
        tasks.step_finished(tasks.step_started(ATTACK, ATTACK), error=ATTACK)
        tasks.waiting(ATTACK); tasks.answered(False)
        tasks.reply(ATTACK)
        tasks.finish(tasks.FAILED, ATTACK, task_id=tid)

        async def check(page):
            return {"images": await page.evaluate("document.querySelectorAll('.taskcenter img').length"),
                    "ran": await page.evaluate("window.__ran || 0"), **await page.evaluate(TC)}

        seen = _render(check, script=_ui.bridge(_poll()))
        assert seen["images"] == 0 and seen["ran"] == 0
        assert seen["title"] == f"“{ATTACK}”"

    @pytest.mark.parametrize("size", [(1040, 660), (1920, 1080)], ids=lambda s: f"{s[0]}x{s[1]}")
    def test_long_ones_wrap_and_nothing_runs_under_the_command_box(self, browser_ok, size):
        tasks.start("x" * 300)
        tasks.route("plan")
        tasks.plan(["y" * 300] * 6)
        for i in range(1, 7):
            tasks.plan_step(i, "running")
            tasks.step_finished(tasks.step_started("read_file", "z" * 300))
            tasks.plan_step(i, "done")
        for i in range(30):
            _task(f"task {i}")

        async def check(page):
            await page.click('#tcList .tc-item:last-child')
            return await page.evaluate("""() => {
              const cmd = document.querySelector('.cmdbar').getBoundingClientRect().top;
              return {
                sideways: document.documentElement.scrollWidth > window.innerWidth
                  || [...document.querySelectorAll('.tc-listwrap, .tc-detail')].some(e => e.scrollWidth > e.clientWidth + 1),
                clear: [...document.querySelectorAll('.tc-listwrap, .tc-detail')]
                  .every(e => e.getBoundingClientRect().bottom <= cmd),
                scrolls: document.querySelector('.tc-listwrap').scrollHeight > document.querySelector('.tc-listwrap').clientHeight,
              };
            }""")

        seen = _render(check, script=_ui.bridge(_poll()), viewport=size)
        assert not seen["sideways"] and seen["clear"]
        assert seen["scrolls"], "a long list scrolls inside its panel"
