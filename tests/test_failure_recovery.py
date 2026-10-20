"""Chapter 42 — failure recovery: try again where it's safe, say so always.

The model: a switch to a lighter model is recorded; with no route to the
internet it stops trying for a moment and says what still works. The
browser: closed or crashed under a step, it's reopened and the step tried
once more — with the reply saying so. Tools: one that only reads gets a
second try after a passing failure; one that changes things never does.
And every missing optional package is a sentence, not a crash.
"""
from __future__ import annotations

import sys
import types

import pytest
import requests

from jarvis.ai import provider
from jarvis.app import assistant, recovery, stats, tasks
from jarvis.routing.router import fast_route
from jarvis.store import knowledge
from jarvis.tools import browser, permissions, registry
from jarvis.tools.registry import FUNCTIONS
from jarvis.voice import listening, local_wake, speaking
from test_browser_agent import HITS, at, site  # noqa: F401  (a real browser against a local site)


class Response:
    def __init__(self, status, body=None):
        self.status_code, self._body, self.text = status, body or {"candidates": []}, "x"

    def json(self):
        return self._body


@pytest.fixture
def network(monkeypatch):
    """The model's HTTP, played by the test: `answers` in turn, or an
    exception to raise. Records every attempt."""
    played = {"answers": [], "attempts": []}
    monkeypatch.setattr(provider, "API_KEY", "test-key")
    monkeypatch.setattr(provider.time, "sleep", lambda _s: None)
    monkeypatch.setattr(provider, "_current_model", "main-model")
    monkeypatch.setattr(provider, "FALLBACK_MODELS", ["light-model"])

    def post(url, **_k):
        played["attempts"].append(url)
        answer = played["answers"].pop(0) if played["answers"] else Response(200)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(provider._session, "post", post)
    return played


def events(kind):
    return [e for e in permissions.events(200) if e["kind"] == kind]


# ================================================================ the model

class TestTheModel:
    def test_no_internet_then_no_waiting_out_the_same_retries(self, network):
        network["answers"] = [requests.ConnectionError("down")] * 10
        with pytest.raises(RuntimeError, match="can't reach the internet"):
            provider.call_gemini({})
        tried = len(network["attempts"])
        with pytest.raises(RuntimeError, match="can't reach the internet"):
            provider.call_gemini({})
        assert len(network["attempts"]) == tried, "held: no attempt at all"
        assert events("failed")[0]["tool"] == "model"

    def test_after_the_hold_it_tries_again(self, network, monkeypatch):
        network["answers"] = [requests.ConnectionError("down")] * 2
        with pytest.raises(RuntimeError):
            provider.call_gemini({})
        monkeypatch.setattr(recovery, "_offline_since", recovery.time.monotonic() - recovery.OFFLINE_HOLD - 1)
        assert provider.call_gemini({}) == {"candidates": []}
        assert recovery._offline_since is None, "back online, not just past the hold"

    def test_a_switch_to_a_lighter_model_is_recorded(self, network):
        network["answers"] = [Response(503)] * provider.RETRIES + [Response(200)]
        provider.call_gemini({})
        assert provider._current_model == "light-model"
        (switched, *_) = events("recovered")
        assert switched["tool"] == "model" and switched["detail"] == \
            "main-model was busy or gone, so I switched to light-model"

    def test_a_rejected_key_is_not_an_outage(self, network):
        network["answers"] = [Response(401)]
        with pytest.raises(RuntimeError) as caught:
            provider.call_gemini({})
        assert recovery.with_offline_help(str(caught.value)) == str(caught.value)
        assert recovery.offline_hold() is None

    @pytest.fixture
    def bot(self, monkeypatch):
        monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
        lines = []
        made = assistant.Jarvis(log_fn=lines.append)
        made.muted = True
        made.lines = lines
        return made

    def test_a_command_says_what_still_works(self, bot):
        class Offline:
            def ask(self, *_a, **_k):
                raise RuntimeError("I can't reach the internet right now.")
        bot.brain = Offline()
        bot.handle("tell me a story")
        task = tasks.recent(1)[0]
        assert task["status"] == tasks.FAILED and task["error"] == "I can't reach the internet right now."
        assert bot.lines[-1] == recovery.STILL_WORKS

    def test_but_not_for_a_bad_key(self, bot):
        class Rejected:
            def ask(self, *_a, **_k):
                raise RuntimeError("My API key was rejected. Check GEMINI_API_KEY in .env.")
        bot.brain = Rejected()
        bot.handle("tell me a story")
        assert recovery.STILL_WORKS not in bot.lines


# ============================================================== the browser

def gone():
    raise RuntimeError("Target page, context or browser has been closed")


class TestTheBrowser:
    @pytest.fixture
    def worker(self):
        made = browser._Worker()
        made.forgot = 0

        def forget():
            made.forgot += 1
        made._forget = forget
        return made

    def test_gone_under_a_step_it_is_reopened_and_the_step_retried(self, worker):
        calls = []

        def step():
            calls.append(1)
            return gone() if len(calls) == 1 else "Opened Example."
        assert worker._attempt(step) == browser.REOPENED + "Opened Example."
        assert len(calls) == 2 and worker.forgot == 1 and events("recovered")[0]["tool"] == "browser"

    def test_the_agents_failure_mark_stays_first(self, worker):
        calls = []
        said = worker._attempt(lambda: calls.append(1) or (gone() if len(calls) == 1 else "\x02couldn't find it"))
        assert said == "\x02" + browser.REOPENED + "couldn't find it"
        assert browser._reopened({"url": "x"}) == {"url": "x"}, "an observation isn't touched"

    def test_gone_twice_is_said(self, worker):
        with pytest.raises(RuntimeError):
            worker._attempt(gone)
        assert events("failed")[0]["detail"].startswith("it closed and didn't come back")
        assert browser._friendly(RuntimeError("Target page, context or browser has been closed")) == \
            "The browser window was closed. Ask me again and I'll reopen it."

    def test_any_other_error_isnt_retried(self, worker):
        calls = []
        with pytest.raises(ValueError):
            worker._attempt(lambda: calls.append(1) or (_ for _ in ()).throw(ValueError("no such element")))
        assert len(calls) == 1

    def test_a_real_browser_closed_behind_its_back(self, at, site):
        at("/home.html")
        browser._worker.run(lambda: browser._worker.context.close())
        said = browser.open_page(site + "/about.html")
        assert said.startswith(browser.REOPENED) and "About" in said
        assert browser._worker.context is not None


# ================================================================== tools

class TestTools:
    def test_one_that_only_reads_gets_a_second_try(self, monkeypatch):
        calls = []
        monkeypatch.setitem(FUNCTIONS, "list_dir", lambda **_k: calls.append(1) or (
            (_ for _ in ()).throw(TimeoutError("timed out")) if len(calls) == 1 else "a.txt"))
        assert registry.execute_tool("list_dir", {}) == "a.txt" and len(calls) == 2
        (event, *_) = events("recovered")
        assert event["tool"] == "list_dir" and event["detail"] == "worked on a second try, after TimeoutError"

    def test_twice_is_a_failure(self, monkeypatch):
        calls = []
        monkeypatch.setitem(FUNCTIONS, "list_dir", lambda **_k: calls.append(1) or (_ for _ in ()).throw(
            ConnectionError("connection reset")))
        assert registry.execute_tool("list_dir", {}).startswith("Error in list_dir: ConnectionError")
        assert len(calls) == 2

    def test_a_real_error_isnt_retried(self, monkeypatch):
        calls = []
        monkeypatch.setitem(FUNCTIONS, "list_dir", lambda **_k: calls.append(1) or 1 / 0)
        registry.execute_tool("list_dir", {})
        assert len(calls) == 1

    def test_one_that_changes_things_is_never_retried(self, monkeypatch):
        calls = []
        monkeypatch.setitem(FUNCTIONS, "write_file", lambda **_k: calls.append(1) or (_ for _ in ()).throw(
            TimeoutError("timed out")))
        assert registry.execute_tool("write_file", {"path": "a", "content": "b"}).startswith("Error in write_file")
        assert len(calls) == 1, "a second try could write twice"

    def test_what_went_wrong_lately(self, monkeypatch):
        assert fast_route("what went wrong lately?") == "Nothing has gone wrong this session."
        monkeypatch.setitem(FUNCTIONS, "list_dir", lambda **_k: 1 / 0)
        registry.execute_tool("list_dir", {})
        recovery.note("browser", "it had closed; I reopened it and tried the step again", True)
        first, second = fast_route("any errors today").split("\n")[:2]
        assert first.endswith("browser recovered: it had closed; I reopened it and tried the step again")
        assert second.endswith("list_dir failed: ZeroDivisionError: division by zero")


# ===================================================== broken dependencies

class TestBrokenDependencies:
    def test_no_playwright(self, monkeypatch):
        browser.close_browser()
        monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
        assert browser.open_page("https://example.com") == browser.SETUP_HINT
        assert browser._worker.context is None

    @pytest.mark.parametrize("suffix,module,said", [(".pdf", "pypdf", "Reading PDFs needs pypdf"),
                                                    (".docx", "docx", "Reading Word files needs python-docx")])
    def test_no_document_readers(self, workspace, monkeypatch, suffix, module, said):
        (workspace / f"a{suffix}").write_bytes(b"x")
        monkeypatch.setitem(sys.modules, module, None)
        assert knowledge.add_document(f"a{suffix}").startswith(said)

    def test_no_psutil(self, monkeypatch):
        monkeypatch.setattr(stats, "psutil", None)
        assert stats.system() == {"available": False}

    def test_no_speech_recognition(self, monkeypatch):
        monkeypatch.setattr(listening, "sr", None)
        with pytest.raises(RuntimeError, match="SpeechRecognition isn't installed, so voice input is off."):
            listening.Listener()

    def test_no_microphone_means_typed_commands_still_work(self, monkeypatch):
        lines = []
        bot = assistant.Jarvis(log_fn=lines.append)
        bot.muted = True
        monkeypatch.setattr(assistant, "Listener", lambda: (_ for _ in ()).throw(RuntimeError("no mic")))
        bot.running = True
        bot._voice_loop()
        assert "I couldn't reach your microphone, so voice is off. Typed commands still work." in lines
        assert fast_route("what's the time").startswith("It's")

    def test_no_neural_voice(self, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "edge_tts", None)
        assert speaking._synthesise("hello", tmp_path / "x.mp3") is False

    def test_no_pocketsphinx(self, monkeypatch):
        monkeypatch.setattr(local_wake, "installed", lambda: False)
        assert local_wake.LocalWake(types.SimpleNamespace(recognize_sphinx=None)).why_not() == \
            "pocketsphinx isn't installed (pip install --prefer-binary pocketsphinx)"

    def test_no_api_key(self, monkeypatch):
        monkeypatch.setattr(provider, "API_KEY", "")
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY is missing"):
            provider.call_gemini({})
        assert fast_route("what's the time").startswith("It's"), "what's local still answers"
