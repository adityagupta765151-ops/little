"""Chapter 43 — which model answers what.

Local answers use no model. Short jobs — checking a plan step, summarising
a page — use the fast model; anything with tools, plans, code, documents, a
resume or the screen uses the strong one. Each tier keeps its fallback, the
fast one ending at the strong model, and each tier's calls are timed.
"""
from __future__ import annotations

import json
import threading

import pytest

from jarvis.ai import brain, models, planner, provider
from jarvis.app import latency, settings
from jarvis.routing.router import fast_route
from jarvis.tools import browser


class Response:
    def __init__(self, status, text="ok"):
        self.status_code, self.text = status, "x"
        self._body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}

    def json(self):
        return self._body


@pytest.fixture
def network(monkeypatch):
    """The model's HTTP: records which model each request went to."""
    seen = {"models": [], "status": {}}
    monkeypatch.setattr(provider, "API_KEY", "test-key")
    monkeypatch.setattr(provider.time, "sleep", lambda _s: None)
    monkeypatch.setattr(provider, "_current_model", "strong-model")
    monkeypatch.setattr(provider, "_current_fast", "fast-model")
    monkeypatch.setattr(provider, "FALLBACK_MODELS", ["lite-a", "lite-b"])

    def post(url, **kwargs):
        model = url.split("/models/")[1].split(":")[0]
        seen["models"].append(model)
        text = json.dumps({"verified": True, "evidence": "shown"}) if "A step of a plan" in json.dumps(kwargs["json"]) \
            else "An answer."
        return Response(seen["status"].get(model, 200), text)
    monkeypatch.setattr(provider._session, "post", post)
    latency.reset()
    yield seen
    latency.reset()


class TestTiers:
    def test_strong_unless_asked(self):
        assert models.current() == "strong"
        with models.use("fast"):
            assert models.current() == "fast"
        assert models.current() == "strong"

    def test_restored_after_an_error_and_per_thread(self):
        with pytest.raises(RuntimeError):
            with models.use("fast"):
                raise RuntimeError("boom")
        assert models.current() == "strong"
        seen = {}
        with models.use("fast"):
            worker = threading.Thread(target=lambda: seen.setdefault("other", models.current()))
            worker.start()
            worker.join()
        assert seen["other"] == "strong"

    def test_only_real_tiers(self):
        with pytest.raises(ValueError):
            with models.use("medium"):
                pass

    def test_the_chains(self, network):
        assert models.chain("strong") == ["strong-model", "lite-a", "lite-b"]
        assert models.chain("fast") == ["fast-model", "lite-a", "lite-b", "strong-model"], "the strong model last"


class TestRouting:
    def test_a_request_goes_to_its_tiers_model(self, network):
        provider.ask_text("hello")
        with models.use("fast"):
            provider.ask_text("hello")
        assert network["models"] == ["strong-model", "fast-model"]

    def test_each_tier_falls_back_on_its_own(self, network):
        network["status"] = {"fast-model": 404, "lite-a": 404}
        with models.use("fast"):
            provider.ask_text("hello")
        assert network["models"] == ["fast-model", "lite-a", "lite-b"]
        assert provider._current_fast == "lite-b" and provider._current_model == "strong-model"

    def test_the_fast_tier_ends_at_the_strong_model(self, network):
        network["status"] = {"fast-model": 404, "lite-a": 404, "lite-b": 404}
        with models.use("fast"):
            assert provider.ask_text("hello") == "An answer."
        assert network["models"][-1] == "strong-model"

    def test_the_brain_with_its_tools_is_strong(self, network):
        brain.Brain().ask("tell me a joke")
        assert network["models"] == ["strong-model"]

    def test_checking_a_plan_step_is_fast_and_the_plan_strong(self, network, monkeypatch, workspace):
        plan = json.dumps({"goal": "x", "steps": [{"do": "List it", "check": "a listing"}, {"do": "Two"}]})
        calls = iter([plan])
        real_ask = provider.ask_text
        monkeypatch.setattr(planner, "ask_text", lambda p: next(calls) if p.startswith("Break") else real_ask(p))

        class Tooling:
            history: list = []

            def ask(self, text):
                from jarvis.tools import registry
                self.history.append({"role": "model", "parts": [{"functionCall": {"name": "list_dir", "args": {}}}]})
                self.history.append({"role": "user", "parts": [{"functionResponse": {
                    "name": "list_dir", "response": {"result": registry.execute_tool("list_dir", {})}}}]})
                return "Done."
        planner.run("list it and then two", Tooling(), lambda _l: None, lambda _s: None)
        assert network["models"] == ["fast-model"], "only the check went to a model here"

    def test_a_page_summary_is_fast(self, network, monkeypatch):
        monkeypatch.setattr(browser, "_read", lambda url: (True, "Page text about otters."))
        browser.summarize_page("https://example.com")
        assert network["models"] == ["fast-model"]

    def test_each_tier_is_timed(self, network):
        provider.ask_text("a")
        with models.use("fast"):
            provider.ask_text("b")
            provider.ask_text("c")
        found = latency.summary()
        assert found["model_strong"]["count"] == 1 and found["model_fast"]["count"] == 2


class TestSayingSo:
    def test_the_report(self, network):
        said = fast_route("which model do you use for what?")
        assert "the time, memory, reminders, stored jobs, searching your documents: no model — on this computer" in said
        assert "checking a plan step against what the tools returned: the fast model (fast-model)" in said
        assert "anything with tools, plans or code: the strong model (strong-model)" in said
        assert "(The strong model is standing in for" in said, "strong-model isn't the configured one"

    def test_the_settings_row(self, network):
        rows = {r["label"]: r for g in settings.groups() if g["id"] == "ai" for r in g["rows"]}
        assert rows["Fast model"]["value"] == "fast-model" and rows["Fast model"]["key"] == "JARVIS_MODEL_FAST"
