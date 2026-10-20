"""Chapter 46 — performance benchmarking: measure before optimising.

Every stage is timed in use — hearing its name, speech to text, the
router, each model tier, a tool, a browser step, and each command by path
— and "benchmark yourself" times what can be timed here without sending
anything or changing anything. Each run is kept, so the next can be
compared with it.
"""
from __future__ import annotations

import json
import threading
import types

import pytest

from jarvis.ai import provider
from jarvis.app import benchmark, latency
from jarvis.routing.router import fast_route
from jarvis.store import knowledge, memory
from jarvis.tools import apps, browser, registry
from jarvis.voice import listening, local_wake


@pytest.fixture(autouse=True)
def fresh():
    latency.reset()
    yield
    latency.reset()


@pytest.fixture
def no_model(monkeypatch):
    monkeypatch.setattr(provider, "call_gemini", lambda *_a, **_k: pytest.fail("the model was asked"))


class TestEveryStageIsTimedInUse:
    def test_a_tool_run(self):
        registry.execute_tool("get_datetime", {})
        registry.execute_tool("list_dir", {})
        assert latency.summary()["tool"]["count"] == 2

    def test_a_browser_step(self):
        worker = browser._Worker()
        assert worker.run(lambda: "done") == "done"
        assert latency.summary()["browser"]["count"] == 1

    def test_a_browser_step_given_up_on_is_timed_too(self, monkeypatch):
        monkeypatch.setattr(browser, "STEP_LIMIT", 0.05)
        release = threading.Event()
        worker = browser._Worker()
        said = worker.run(lambda: release.wait(2) and "late")
        release.set()
        assert said == "The browser took too long and I gave up on that step."
        found = latency.summary()["browser"]
        assert found["count"] == 1 and found["max"] >= 50

    def test_hearing_its_name_and_speech_to_text(self, monkeypatch):
        class Recogniser:
            def recognize_sphinx(self, audio, keyword_entries=None):
                return "little"

            def recognize_google(self, audio, language=None):
                return "little what's the time"
        monkeypatch.setattr(local_wake, "installed", lambda: True)
        monkeypatch.setattr(listening, "sr", types.SimpleNamespace(UnknownValueError=ValueError,
                                                                   RequestError=ConnectionError))
        ear = object.__new__(listening.Listener)
        ear.recognizer = Recogniser()
        ear.wake = local_wake.LocalWake(ear.recognizer, mode="auto")
        ear._record = lambda timeout, phrase_limit: {"audio": 1}
        ear.listen(wake=True)
        ear.listen()
        found = latency.summary()
        assert found["wake"]["count"] == 1 and found["stt"]["count"] == 2

    def test_a_model_request_by_tier(self, monkeypatch):
        class Response:
            status_code, text = 200, "x"

            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        monkeypatch.setattr(provider, "API_KEY", "k")
        monkeypatch.setattr(provider._session, "post", lambda *_a, **_k: Response())
        provider.ask_text("hi")
        assert latency.summary()["model_strong"]["count"] == 1


class TestBenchmarkYourself:
    def test_it_times_what_it_can_here_and_nothing_else(self, no_model, monkeypatch):
        monkeypatch.setattr(apps, "open_app", lambda *_a: pytest.fail("an app was opened"))
        before = memory.facts()
        result = benchmark.run()
        now = result["now"]
        assert set(now) == {"router", "tool", "documents"}
        assert now["router"]["count"] == len(benchmark.ROUTER_COMMANDS) * benchmark.ROUNDS
        assert now["tool"]["count"] == benchmark.ROUNDS and now["documents"]["count"] == 0
        assert 0 <= now["router"]["p50"] <= now["router"]["p95"] <= now["router"]["max"]
        assert memory.facts() == before, "nothing it runs writes to your memory"
        assert apps.open_app is not None

    def test_the_apps_stand_in_is_put_back(self, no_model):
        real = apps.open_app
        benchmark.run()
        assert apps.open_app is real

    def test_documents_are_timed_when_there_are_some(self, no_model, workspace):
        (workspace / "a.md").write_text("The project deadline is Friday.", encoding="utf-8")
        knowledge.add_document("a.md")
        assert benchmark.run()["now"]["documents"]["count"] == benchmark.ROUNDS

    def test_in_use_numbers_come_along_and_are_named_as_such(self, no_model):
        latency.record("fast", 4)
        latency.record("ai", 2400)
        said = benchmark.benchmark()
        assert said.startswith("Measured just now, on this computer:")
        assert "Measured in use this session:" in said and "Commands with the model: typically 2.40 s" in said
        assert "Answering here is about 600× faster than asking the model." in said
        assert "Searching your documents: not measured — no documents added yet" in said

    def test_too_quick_to_keep_isnt_called_zero(self):
        assert benchmark._ms(0.0) == "under 0.01 ms" and benchmark._ms(0.19) == "0.19 ms"
        assert benchmark._ms(2400) == "2.40 s" and benchmark._ms(None) == "—"

    def test_each_run_is_kept_and_compared(self, no_model):
        benchmark.run()
        said = benchmark.benchmark()
        assert len(benchmark.history()) == 2 and "The router was " in said
        first = json.loads(benchmark.PATH.read_text(encoding="utf-8").splitlines()[0])
        assert set(first) == {"at", "now", "in_use", "problems"}

    def test_compared_with_the_run_before_not_itself(self, no_model):
        earlier = {"at": "then", "now": {"router": {"count": 1, "p50": 123.0, "p95": 123.0, "max": 123.0}},
                   "in_use": {}, "problems": []}
        benchmark.PATH.write_text(json.dumps(earlier) + "\n", encoding="utf-8")
        said = benchmark.benchmark()
        assert "The router was 123 ms last time, " in said

    def test_the_model_only_when_asked(self, monkeypatch):
        tiers = []

        def ask(prompt, system=None, empty=""):
            from jarvis.ai import models
            tiers.append(models.current())
            return "ok"
        monkeypatch.setattr(provider, "ask_text", ask)
        benchmark.run()
        assert tiers == []
        result = benchmark.run(include_model=True)
        assert tiers == ["fast", "strong"] and result["now"]["model_fast"]["count"] == 1

    def test_a_model_that_cant_be_reached_is_said(self, monkeypatch):
        monkeypatch.setattr(provider, "ask_text", lambda *_a, **_k: (_ for _ in ()).throw(
            RuntimeError("I can't reach the internet right now.")))
        said = benchmark.benchmark(include_model=True)
        assert "Couldn't time the fast model: I can't reach the internet right now." in said

    def test_by_command(self, no_model):
        assert fast_route("benchmark yourself").startswith("Measured just now")
        assert fast_route("how fast is everything?").startswith("Measured just now")


class TestOnTheDashboard:
    def test_measured_steps_show_there(self):
        from jarvis.app import overview
        rows = lambda key: dict(next(x for x in overview.snapshot() if x["id"] == key)["rows"])
        assert rows("browser")["Typical step"] == "not measured yet"
        assert rows("voice")["Speech to text"] == "not measured yet"
        latency.record("browser", 1500)
        latency.record("stt", 640)
        assert rows("browser")["Typical step"] == "1.5 s" and rows("voice")["Speech to text"] == "640 ms"

    def test_benchmark_the_model_by_command(self, monkeypatch):
        asked = []
        monkeypatch.setattr(provider, "ask_text", lambda *_a, **_k: asked.append(1) or "ok")
        said = fast_route("benchmark the models too")
        assert said.startswith("Measured just now") and len(asked) == 2
        assert "The fast model: typically" in said and "The strong model: typically" in said
