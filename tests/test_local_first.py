"""Chapter 33 — local first: FAST, NORMAL, AI, AGENT.

The cheapest path that can answer does: what LITTLE already holds, then
its own tools, then the model, then a plan. Each command's path is on its
task, and each path's time is measured — really measured, from the task's
own start and finish — along with what trying locally first costs.
"""
from __future__ import annotations

import pytest

from jarvis.ai import planner, provider
from jarvis.app import assistant, latency, tasks
from jarvis.routing import router
from jarvis.store import memory


class FakeBrain:
    def __init__(self, reply="All done."):
        self.reply, self.asked = reply, []

    def ask(self, text, on_action=None):
        self.asked.append(text)
        return self.reply


@pytest.fixture(autouse=True)
def fresh():
    latency.reset()
    yield
    latency.reset()


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
    made = assistant.Jarvis(log_fn=lambda _l: None)
    made.muted = True
    made.brain = FakeBrain()
    return made


@pytest.fixture
def no_model(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the model was asked")
    monkeypatch.setattr(provider, "call_gemini", refuse)
    monkeypatch.setattr(planner, "ask_text", refuse)


def last():
    return tasks.recent(1)[0]


# ================================================================== paths

class TestEachCommandTakesTheCheapestPath:
    @pytest.mark.parametrize("command", ["what's the time", "what's the date", "remember that my editor is Vim",
                                         "what do you remember", "list reminders", "how fast are you", ""])
    def test_fast_is_answered_from_what_little_holds(self, bot, no_model, command):
        bot.handle(command)
        assert last()["path"] == "fast" and last()["route"] == "local" and bot.brain.asked == []

    @pytest.mark.parametrize("command,stub", [
        ("find jobs for me", ("jobs", "find_jobs")),
        ("search python internships", ("webbrowser", "open")),
        ("run a system check", ("health", "system_check")),
        ("what's in my knowledge base", None),
    ])
    def test_normal_is_this_computers_tools_without_the_model(self, bot, no_model, monkeypatch, command, stub):
        if stub:
            monkeypatch.setattr(getattr(router, stub[0]), stub[1], lambda *_a, **_k: "ok")
        bot.handle(command)
        assert last()["path"] == "normal" and bot.brain.asked == []

    def test_ai_is_the_model(self, bot):
        bot.handle("tell me a story about pumpkins")
        assert last()["path"] == "ai" and last()["route"] == "model" and bot.brain.asked == ["tell me a story about pumpkins"]

    def test_agent_is_a_plan(self, bot, monkeypatch):
        monkeypatch.setattr(planner, "ask_text", lambda *_a: "1. Make it\n2. Run it")
        bot.handle("create a react app and run it")
        assert last()["path"] == "agent" and last()["route"] == "plan"

    def test_local_is_always_tried_first(self, bot, monkeypatch):
        tried = []
        real = assistant.fast_route
        monkeypatch.setattr(assistant, "fast_route", lambda c: tried.append(c) or real(c))
        bot.handle("tell me a story about pumpkins")
        assert tried == ["tell me a story about pumpkins"]

    def test_a_router_failure_falls_through_to_the_model(self, bot, monkeypatch):
        monkeypatch.setattr(assistant, "fast_route", lambda c: (_ for _ in ()).throw(RuntimeError("bug")))
        bot.handle("what's the time")
        assert last()["path"] == "ai" and bot.brain.asked == ["what's the time"]

    def test_the_path_is_set_per_thread(self, no_model):
        import threading
        seen = {}

        def other():
            assert router.fast_route("tell me a joke about otters") is None
            seen["other"] = router.last_path()
        router.fast_route("what's the time")
        worker = threading.Thread(target=other)
        worker.start()
        worker.join()
        assert router.last_path() == "fast" and seen["other"] == "normal"

    def test_a_section_button_task_counts_too(self):
        tid = tasks.start("Check the submission of x")
        tasks.route("local")
        assert tasks.get(tid)["path"] == "normal"
        tasks.route("model")
        assert tasks.get(tid)["path"] == "ai"
        tasks.path("warp")
        assert tasks.get(tid)["path"] == "ai", "only the four paths"
        tasks.finish(tasks.DONE, task_id=tid)


# ================================================================ latency

class TestLatencyIsMeasured:
    def test_each_task_is_timed_under_its_path(self, bot, monkeypatch):
        bot.handle("what's the time")
        bot.handle("tell me a story about pumpkins")
        found = latency.summary()
        assert found["fast"]["count"] == 1 and found["ai"]["count"] == 1
        assert found["fast"]["last"] == round(tasks.recent(2)[1]["ms"])
        assert found["ai"]["last"] == round(tasks.recent(2)[0]["ms"])
        assert found["router"]["count"] == 2, "trying locally first is timed every time"
        assert found["agent"] == {"count": 0, "p50": None, "p95": None, "max": None, "last": None}

    def test_a_task_is_timed_once(self):
        tid = tasks.start("x")
        tasks.route("local")
        tasks.finish(tasks.DONE, task_id=tid)
        tasks.finish(tasks.DONE, task_id=tid)
        assert latency.summary()["normal"]["count"] == 1

    def test_the_numbers_are_the_tasks_own(self):
        tid = tasks.start("x")
        tasks.route("model")
        tasks.finish(tasks.DONE, task_id=tid)
        assert latency.summary()["ai"]["last"] == round(tasks.get(tid)["ms"])

    def test_percentiles(self):
        for ms in range(1, 101):
            latency.record("ai", ms)
        s = latency.summary()["ai"]
        assert (s["count"], s["p50"], s["p95"], s["max"], s["last"]) == (100, 50, 95, 100, 100)

    def test_only_real_measurements(self):
        for bad in (-1, "fast", None):
            latency.record("fast", bad)
        latency.record("warp", 5)
        assert latency.summary()["fast"]["count"] == 0 and "warp" not in latency.summary()

    def test_bounded(self):
        for i in range(250):
            latency.record("fast", i)
        assert latency.summary()["fast"]["count"] == 200, "the last 200"
        assert latency.summary()["fast"]["max"] == 249

    def test_said_plainly_or_not_at_all(self, no_model):
        assert router.fast_route("how fast are you") == "Nothing measured yet. Ask me a few things and ask again."
        for ms in (5, 7, 9):
            latency.record("fast", ms)
        latency.record("ai", 2400)
        said = router.fast_route("show your latency")
        assert said == ("Fast (on this computer): typically 7 ms, slowest 1 in 20 9 ms (3 measured)\n"
                        "AI (the model): typically 2.4 s, slowest 1 in 20 2.4 s (1 measured)")

    def test_nothing_is_written_to_disk(self, tmp_path):
        before = set(memory.MEMORY_DIR.iterdir())
        latency.record("fast", 3)
        latency.report()
        assert set(memory.MEMORY_DIR.iterdir()) == before
