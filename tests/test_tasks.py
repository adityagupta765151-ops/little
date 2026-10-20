"""The task registry: what LITTLE is doing, and how each command ended.

Home is built on it (UI-3), so it has to be right in three ways:
  * outcomes come from what the code knows — an error raised, a plan that
    stopped, a stop you asked for — never from how a reply is worded;
  * it's shared by several threads at once and must stay consistent;
  * the window only ever receives what changed.
"""
from __future__ import annotations

import threading
import time

import pytest

from jarvis.app import assistant, bridge, stats, tasks
from jarvis.ai import planner
from jarvis.tools import permissions, registry


@pytest.fixture(autouse=True)
def fresh():
    tasks.reset()
    yield
    tasks.reset()


def _task(tid):
    return next(t for t in tasks.recent(tasks.LIMIT) if t["id"] == tid)


# ============================================================ the registry

class TestLifecycle:
    def test_a_command_starts_active_and_ends_done(self):
        tid = tasks.start("what time is it")
        assert tasks.current()["id"] == tid
        assert _task(tid)["status"] == tasks.ACTIVE
        tasks.route("local")
        tasks.finish(tasks.DONE)
        task = _task(tid)
        assert task["status"] == tasks.DONE and task["route"] == "local"
        assert task["ms"] is not None and task["finished"] >= task["started"]
        assert tasks.current() is None

    def test_a_failure_keeps_its_reason(self):
        tid = tasks.start("find jobs")
        tasks.finish(tasks.FAILED, "I can't reach the internet right now.")
        assert _task(tid)["error"] == "I can't reach the internet right now."

    def test_only_a_failure_carries_an_error(self):
        tid = tasks.start("x")
        tasks.finish(tasks.DONE, "not an error")
        assert _task(tid)["error"] == ""

    def test_it_says_where_it_came_from(self):
        tasks.start("x", source="voice")
        assert tasks.current()["source"] == "voice"
        tasks.start("y", source="something odd")
        assert tasks.recent(1)[0]["source"] == "typed"

    def test_a_finished_task_cannot_be_reopened_or_refinished(self):
        tid = tasks.start("x")
        tasks.finish(tasks.FAILED, "broke", task_id=tid)
        tasks.finish(tasks.DONE, task_id=tid)
        tasks.waiting("Delete it?", task_id=tid)
        assert _task(tid)["status"] == tasks.FAILED

    def test_an_unknown_outcome_counts_as_done_not_as_something_worse(self):
        tid = tasks.start("x")
        tasks.finish("exploded")
        assert _task(tid)["status"] == tasks.DONE

    def test_only_known_routes_are_recorded(self):
        tid = tasks.start("x")
        tasks.route("the moon")
        assert _task(tid)["route"] is None


class TestSteps:
    def test_a_tool_run_is_a_timed_step(self):
        tid = tasks.start("x")
        n = tasks.step_started("read_file", '{"path": "a.txt"}')
        running = _task(tid)["steps"][0]
        assert running["status"] == "running" and running["ms"] is None
        tasks.step_finished(n)
        step = _task(tid)["steps"][0]
        assert step["status"] == "done" and step["ms"] >= 0
        assert step["detail"] == '{"path": "a.txt"}'

    def test_an_error_replaces_the_detail(self):
        tasks.start("x")
        n = tasks.step_started("read_file", "a.txt")
        tasks.step_finished(n, error="FileNotFoundError: a.txt")
        step = tasks.current()["steps"][0]
        assert step["status"] == "error" and "FileNotFoundError" in step["detail"]

    def test_a_step_still_running_when_the_task_ends_is_closed(self):
        tid = tasks.start("x")
        tasks.step_started("find_jobs")
        tasks.finish(tasks.FAILED, "gave up")
        assert _task(tid)["steps"][0]["status"] == "error"

    def test_a_long_task_keeps_its_newest_steps(self):
        tid = tasks.start("x")
        for i in range(tasks.STEP_LIMIT + 5):
            tasks.step_finished(tasks.step_started(f"tool{i}"))
        steps = _task(tid)["steps"]
        assert len(steps) == tasks.STEP_LIMIT
        assert steps[-1]["name"] == f"tool{tasks.STEP_LIMIT + 4}"
        assert steps[-1]["n"] == tasks.STEP_LIMIT + 4          # numbering carries on

    def test_arguments_are_shortened_for_one_line(self):
        text = tasks.preview({"message": "x" * 500, "count": 3})
        assert len(text) <= tasks.DETAIL_MAX
        assert "…" in text and '"count": 3' in text, "the long value is cut, the rest kept"
        assert len(tasks.preview({f"k{i}": "v" * 50 for i in range(9)})) == tasks.DETAIL_MAX
        assert tasks.preview({"path": "a.txt"}) == '{"path": "a.txt"}'
        assert tasks.preview({}) == "" and tasks.preview(None) == ""


class TestWaitingForYou:
    def test_a_question_puts_the_task_on_hold_and_the_answer_resumes_it(self):
        tid = tasks.start("delete notes.txt")
        tasks.waiting("Delete notes.txt? This can't be undone.")
        task = _task(tid)
        assert task["status"] == tasks.WAITING and task["asking"].startswith("Delete notes.txt")
        assert tasks.current()["id"] == tid, "a task waiting on you is still the current one"
        tasks.answered(False)
        task = _task(tid)
        assert task["status"] == tasks.ACTIVE and task["asking"] == ""
        answer = task["steps"][-1]
        assert {k: answer[k] for k in ("n", "name", "detail", "status", "ms")} == \
            {"n": 0, "name": "your answer", "detail": "declined", "status": "done", "ms": None}
        # the question is kept with the answer, for the timeline (UI-5)
        assert answer["question"] == "Delete notes.txt? This can't be undone."
        assert answer["at"] >= 0 and answer["part"] is None

    def test_only_a_real_true_is_recorded_as_approved(self):
        tasks.start("x")
        tasks.waiting("Send it?")
        tasks.answered("yes")
        assert tasks.current()["steps"][-1]["detail"] == "declined"


class TestThreads:
    def test_a_thread_without_a_task_changes_nothing(self):
        tid = tasks.start("mine")
        seen = {}

        def elsewhere():
            seen["step"] = tasks.step_started("sneaky_tool")
            tasks.waiting("Approve?")
            tasks.finish(tasks.FAILED, "not yours")

        t = threading.Thread(target=elsewhere)
        t.start(); t.join()
        task = _task(tid)
        assert seen["step"] is None
        assert task["steps"] == [] and task["status"] == tasks.ACTIVE

    def test_finishing_unbinds_the_thread(self):
        tasks.start("x")
        tasks.finish(tasks.DONE)
        assert tasks.current_id() is None
        assert tasks.step_started("late") is None

    def test_many_threads_at_once_leave_it_consistent(self):
        """R5 in the plan: new shared state, written from background
        threads. Eight writers and a reader, hammering — with Python told
        to switch threads every microsecond, so a missing lock shows up
        as lost or doubled versions instead of hiding behind the GIL."""
        import sys
        before = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        errors, stop = [], threading.Event()

        def writer(w):
            try:
                for i in range(150):
                    tasks.start(f"w{w} task {i}")
                    n = tasks.step_started("tool", "{}")
                    tasks.waiting("ok?")
                    tasks.answered(True)
                    tasks.step_finished(n)
                    tasks.finish(tasks.DONE if i % 3 else tasks.FAILED, "because")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def reader():
            seen = 0
            try:
                while not stop.is_set():
                    version, changed = tasks.changed_since(seen)
                    assert version >= seen
                    assert all(t["v"] > seen for t in changed)
                    seen = version
                    tasks.current()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        try:
            r = threading.Thread(target=reader)
            r.start()
            ws = [threading.Thread(target=writer, args=(w,)) for w in range(8)]
            for t in ws:
                t.start()
            for t in ws:
                t.join()
            stop.set(); r.join()
        finally:
            sys.setswitchinterval(before)

        assert errors == []
        # Every change got its own version: none lost, none shared.
        versions = [t["v"] for t in tasks.changed_since(0)[1]]
        assert len(set(versions)) == len(versions)
        assert tasks.version() == max(versions)
        kept = tasks.recent(100)
        assert len(kept) == tasks.LIMIT
        assert len({t["id"] for t in kept}) == tasks.LIMIT
        for task in kept:
            assert task["status"] in (tasks.DONE, tasks.FAILED)
            assert [s["name"] for s in task["steps"]] == ["tool", "your answer"]
            assert all(s["status"] == "done" for s in task["steps"])
        assert tasks.current() is None


class TestOnlyChangesTravel:
    def test_changed_since_hands_over_only_what_changed(self):
        a = tasks.start("a")
        tasks.finish(tasks.DONE)
        v, _ = tasks.changed_since(0)
        b = tasks.start("b")
        v2, changed = tasks.changed_since(v)
        assert [t["id"] for t in changed] == [b] and v2 > v
        assert tasks.changed_since(v2)[1] == []
        assert {t["id"] for t in tasks.changed_since(0)[1]} == {a, b}

    def test_it_keeps_the_last_fifty(self):
        ids = []
        for i in range(tasks.LIMIT + 10):
            ids.append(tasks.start(f"t{i}"))
            tasks.finish(tasks.DONE)
        kept = [t["id"] for t in tasks.changed_since(0)[1]]
        assert kept == ids[-tasks.LIMIT:]

    def test_what_it_hands_out_is_a_copy(self):
        tasks.start("x")
        tasks.step_started("tool")
        out = tasks.current()
        out["status"] = "hacked"
        out["steps"][0]["name"] = "hacked"
        assert tasks.current()["status"] == tasks.ACTIVE
        assert tasks.current()["steps"][0]["name"] == "tool"
        assert "t0" not in out["steps"][0], "no timers leak out"


# ====================================================== wired into LITTLE

class FakeBrain:
    def __init__(self, reply="All done.", raises=None, tool=None):
        self.reply, self.raises, self.tool = reply, raises, tool

    def ask(self, text, on_action=None):
        if self.tool:
            if on_action:
                on_action(self.tool, {"x": 1})
            registry.execute_tool(self.tool, {"x": 1})
        if self.raises:
            raise self.raises
        return self.reply


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
    lines = []
    made = assistant.Jarvis(log_fn=lines.append)
    made.muted = True
    made.lines = lines
    return made


class TestEveryCommandIsATask:
    def test_a_local_command(self, bot):
        bot.handle("what's the time")
        task = tasks.recent(1)[0]
        assert task["text"] == "what's the time"
        assert task["status"] == tasks.DONE and task["route"] == "local"
        assert task["source"] == "typed"

    def test_a_model_command_with_a_tool_step(self, bot, monkeypatch):
        monkeypatch.setitem(registry.FUNCTIONS, "fake_tool", lambda **_k: "fine")
        bot.brain = FakeBrain(tool="fake_tool")
        bot.handle("tell me a story about pumpkins")
        task = tasks.recent(1)[0]
        assert task["route"] == "model" and task["status"] == tasks.DONE
        assert [(s["name"], s["status"]) for s in task["steps"]] == [("fake_tool", "done")]
        assert task["steps"][0]["detail"] == '{"x": 1}'

    def test_a_tool_that_raises_is_an_error_step_but_the_task_can_still_finish(self, bot, monkeypatch):
        def broken(**_k):
            raise OSError("disk on fire")
        monkeypatch.setitem(registry.FUNCTIONS, "fake_tool", broken)
        bot.brain = FakeBrain(tool="fake_tool", reply="That file couldn't be read, sorry.")
        bot.handle("tell me a story about pumpkins")
        task = tasks.recent(1)[0]
        assert task["steps"][0]["status"] == "error" and "disk on fire" in task["steps"][0]["detail"]
        assert task["status"] == tasks.DONE, "the model recovered and answered"

    def test_a_reply_that_sounds_like_failure_is_not_read_as_one(self, bot):
        """Outcomes come from the code, not the wording."""
        bot.brain = FakeBrain(reply="I couldn't find that file.")
        bot.handle("tell me a story about pumpkins")
        assert tasks.recent(1)[0]["status"] == tasks.DONE

    def test_a_model_that_cant_be_reached_is_a_failure_with_the_reason(self, bot):
        bot.brain = FakeBrain(raises=RuntimeError("I can't reach the internet right now."))
        bot.handle("tell me a story about pumpkins")
        task = tasks.recent(1)[0]
        assert task["status"] == tasks.FAILED
        assert task["error"] == "I can't reach the internet right now."
        assert "LITTLE: I can't reach the internet right now." in bot.lines

    def test_a_plan_that_stops_on_a_failed_step_fails(self, bot, monkeypatch):
        monkeypatch.setattr(planner, "ask_text", lambda *_a, **_k: "1. Make the app\n2. Run it")

        class Steps(FakeBrain):
            calls = 0
            def ask(self, text, on_action=None):
                Steps.calls += 1
                return "Made it." if Steps.calls == 1 else "FAILED: npm isn't installed"

        bot.brain = Steps()
        bot.handle("create a react app and run it")
        task = tasks.recent(1)[0]
        assert task["route"] == "plan" and task["status"] == tasks.FAILED
        assert task["error"] == "Step 2 of 2: npm isn't installed"

    def test_a_plan_you_stop_is_stopped(self, bot, monkeypatch):
        monkeypatch.setattr(planner, "ask_text", lambda *_a, **_k: "1. One\n2. Two")

        class Cancelling(FakeBrain):
            def ask(self, text, on_action=None):
                planner.cancel()
                return "Did one."

        bot.brain = Cancelling()
        bot.handle("create a react app and run it")
        assert tasks.recent(1)[0]["status"] == tasks.STOPPED

    def test_a_plan_that_finishes_is_done(self, bot, monkeypatch):
        monkeypatch.setattr(planner, "ask_text", lambda *_a, **_k: "1. One\n2. Two")
        bot.brain = FakeBrain(reply="ok")
        bot.handle("create a react app and run it")
        assert tasks.recent(1)[0]["status"] == tasks.DONE

    def test_the_planner_still_works_without_being_asked_how_it_ended(self, monkeypatch):
        monkeypatch.setattr(planner, "ask_text", lambda *_a, **_k: "SIMPLE")
        assert planner.run("x y z w v", FakeBrain(reply="hi"), lambda _l: None,
                           lambda _s: None) == "hi"

    def test_what_you_say_is_marked_as_said(self, bot):
        """Through the real voice loop, with a stand-in microphone that hears
        its name and a command once, then goes quiet."""
        class Mic:
            heard = ["little what's the time"]
            def listen(self, **_k):
                if self.heard:
                    return self.heard.pop()
                bot.running = False
                return ""

        bot.listener, bot.running = Mic(), True
        bot._voice_loop()
        task = tasks.recent(1)[0]
        assert task["text"] == "what's the time" and task["source"] == "voice"

    def test_a_voice_command_is_marked_as_one(self, bot):
        bot.handle("what's the time", source="voice")
        assert tasks.recent(1)[0]["source"] == "voice"

    def test_calibrating_with_no_mic_is_a_failure(self, bot):
        bot.handle("recalibrate mic")
        task = tasks.recent(1)[0]
        assert task["status"] == tasks.FAILED and task["route"] == "local"

    def test_a_crash_inside_still_ends_the_task(self, bot, monkeypatch):
        monkeypatch.setattr(assistant, "strip_address", lambda _c: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            bot.handle("anything")
        task = tasks.recent(1)[0]
        assert task["status"] == tasks.FAILED and task["error"] == "division by zero"
        assert tasks.current_id() is None

    def test_a_confirmation_mid_command_is_waiting_then_answered(self, monkeypatch):
        """Through the real bridge: the task shows WAITING while the dialog
        is up, and the answer is recorded as a step."""
        monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
        original = permissions.confirm_fn

        class Quiet:
            muted, running = True, False
            def start(self): ...
            def stop(self): ...
            def interrupt(self): ...
            def handle(self, text): ...

        api = bridge.Api(assistant=Quiet())
        try:
            seen = {}

            def work():
                tasks.start("delete notes.txt")
                seen["ok"] = permissions.confirm("Delete notes.txt?")
                tasks.finish(tasks.DONE)

            t = threading.Thread(target=work)
            t.start()
            ask = None
            for _ in range(200):
                out = api.poll(0)
                ask = ask or out.get("ask")
                waiting = [x for x in out["tasks"]["changed"] if x["status"] == tasks.WAITING]
                if ask and waiting:
                    break
                time.sleep(0.01)
            assert ask and waiting and waiting[0]["asking"] == "Delete notes.txt?"
            api.confirm_reply(ask["id"], True)
            t.join(2)
            task = tasks.recent(1)[0]
            assert seen["ok"] is True
            assert task["status"] == tasks.DONE
            assert task["steps"][-1]["detail"] == "approved"
        finally:
            permissions.set_confirm(original)


class TestThePollCarriesTasks:
    @pytest.fixture
    def api(self, monkeypatch):
        monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
        original = permissions.confirm_fn

        class Quiet:
            muted, running = False, False
            def handle(self, text): ...

        yield bridge.Api(assistant=Quiet())
        permissions.set_confirm(original)

    def test_from_zero_it_sends_everything_it_has(self, api):
        tasks.start("a"); tasks.finish(tasks.DONE)
        out = api.poll(0)["tasks"]
        assert out["v"] == tasks.version() and [t["text"] for t in out["changed"]] == ["a"]

    def test_from_a_version_it_sends_only_what_changed(self, api):
        tasks.start("a"); tasks.finish(tasks.DONE)
        v = api.poll(0)["tasks"]["v"]
        assert api.poll(v)["tasks"]["changed"] == []
        tasks.start("b")
        assert [t["text"] for t in api.poll(v)["tasks"]["changed"]] == ["b"]

    def test_a_caller_that_doesnt_ask_gets_no_tasks(self, api):
        tasks.start("a")
        assert "tasks" not in api.poll()

    @pytest.mark.parametrize("since", [True, "5", -1, 2.5, None, [0], float("nan")])
    def test_a_version_that_isnt_one_gets_no_tasks(self, api, since):
        tasks.start("a")
        assert "tasks" not in api.poll(since)


class TestSetupWarnings:
    def test_no_api_key_is_put_in_front_of_you(self, monkeypatch):
        from jarvis.app import config
        monkeypatch.setattr(config, "API_KEY", "")
        (warning,) = stats.warnings()
        assert warning["id"] == "api-key" and "GEMINI_API_KEY" in warning["fix"]

    def test_with_a_key_there_is_nothing_to_say(self, monkeypatch):
        from jarvis.app import config
        monkeypatch.setattr(config, "API_KEY", "set")
        assert stats.warnings() == []

    def test_the_readings_carry_them(self):
        class Idle:
            running = False
        assert "warnings" in stats.snapshot(Idle(), muted=False)
