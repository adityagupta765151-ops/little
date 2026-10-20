"""The bridge: the only door between the panel and Python.

It used to live in launcher_web.py, which exits without pywebview, so none
of it could be tested. Moved to jarvis/app/bridge.py, every call is.
"""
from __future__ import annotations

import threading
import time

import pytest

from jarvis.app import bridge
from jarvis.tools import permissions


class FakeAssistant:
    """Stands in for the assistant, recording what the bridge asks of it."""

    def __init__(self):
        self.handled, self.running, self.muted = [], False, False
        self.started = self.stopped = self.interrupted = 0
        self._done = threading.Event()

    def handle(self, text):
        self.handled.append(text)
        self._done.set()

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def interrupt(self):
        self.interrupted += 1


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {"system": {"available": False}})
    original = permissions.confirm_fn
    made = bridge.Api(assistant=FakeAssistant())
    yield made
    permissions.set_confirm(original)


def _answer_when_asked(api, ok, delay=0.05):
    """Play the page: poll until a question shows up, then answer it."""
    def page():
        for _ in range(200):
            ask = api.poll().get("ask")
            if ask:
                time.sleep(delay)
                api.confirm_reply(ask["id"], ok)
                return
            time.sleep(0.01)
    threading.Thread(target=page, daemon=True).start()


# -------------------------------------------------------------------- poll

class TestPoll:
    def test_it_reports_the_status_and_new_lines(self, api):
        api.lines.put("You: open chrome")
        api.lines.put("LITTLE: Opening Chrome.")
        out = api.poll()
        assert out["status"] == "offline"
        assert out["lines"] == ["You: open chrome", "LITTLE: Opening Chrome."]
        assert api.poll()["lines"] == []                  # each line is handed over once

    def test_a_burst_of_lines_is_handed_over_in_slices(self, api):
        for i in range(100):
            api.lines.put(f"line {i}")
        first = api.poll()["lines"]
        assert len(first) == bridge.LINES_PER_POLL
        assert first[0] == "line 0"

    def test_readings_are_gathered_twice_a_second_not_every_poll(self, api, monkeypatch):
        calls = []
        monkeypatch.setattr(bridge.stats, "snapshot",
                            lambda *_a, **_k: calls.append(1) or {"n": len(calls)})
        for _ in range(10):
            api.poll()
        assert len(calls) == 1

    def test_a_failing_reading_doesnt_break_the_poll(self, api, monkeypatch):
        def broken(*_a, **_k):
            raise RuntimeError("psutil fell over")
        monkeypatch.setattr(bridge.stats, "snapshot", broken)
        api._stats_due = 0
        assert "status" in api.poll()

    def test_the_status_follows_the_assistant(self, api):
        api._on_status("waiting for command")
        assert api.poll()["status"] == "waiting" and api.online
        api._on_status("offline")
        assert api.poll()["status"] == "offline" and not api.online


# ----------------------------------------------------------- confirmations

class TestConfirmations:
    def test_a_yes_from_the_page_approves(self, api):
        _answer_when_asked(api, True)
        assert api.confirm("Send this to Rahul?") is True

    def test_a_no_from_the_page_refuses(self, api):
        _answer_when_asked(api, False)
        assert api.confirm("Delete notes.txt?") is False

    def test_the_question_is_shown_once(self, api):
        threading.Thread(target=api.confirm, args=("Run it?",), daemon=True).start()
        time.sleep(0.05)
        first = api.poll().get("ask")
        assert first and first["message"] == "Run it?"
        assert "ask" not in api.poll()
        api.confirm_reply(first["id"], False)

    def test_nobody_answering_is_a_no(self, api, monkeypatch):
        monkeypatch.setattr(bridge, "CONFIRM_TIMEOUT", 0.1)
        assert api.confirm("Delete everything?") is False

    @pytest.mark.parametrize("ok", ["true", 1, "yes", [True], None])
    def test_only_a_real_true_approves(self, api, ok):
        """A page that sends "true" as a string, or 1, has not said yes."""
        _answer_when_asked(api, ok)
        assert api.confirm("Send it?") is False

    def test_an_answer_to_a_question_nobody_asked_is_ignored(self, api):
        api.confirm_reply(999, True)
        assert 999 not in api._answers

    def test_a_late_answer_after_the_timeout_changes_nothing(self, api, monkeypatch):
        monkeypatch.setattr(bridge, "CONFIRM_TIMEOUT", 0.05)
        assert api.confirm("Send it?") is False
        api.confirm_reply(1, True)                        # arrives too late
        assert api._answers == {}

    def test_the_tools_ask_through_the_bridge(self, api):
        _answer_when_asked(api, True)
        assert permissions.confirm("Click Submit?") is True


# ---------------------------------------------------------------- controls

class TestControls:
    def test_send_runs_the_command_on_its_own_thread(self, api):
        api.send("  open chrome  ")
        assert api.jarvis._done.wait(2)
        assert api.jarvis.handled == ["open chrome"]

    @pytest.mark.parametrize("text", ["", "   ", None, 42, {"x": 1}])
    def test_send_ignores_nothing_and_non_text(self, api, text):
        api.send(text)
        time.sleep(0.05)
        assert api.jarvis.handled == []

    def test_toggle_starts_then_stops_listening(self, api):
        api.toggle()
        assert api.jarvis.started == 1 and api.online
        api.toggle()
        assert api.jarvis.stopped == 1

    def test_stop_interrupts(self, api):
        assert api.control("stop") == ""
        assert api.jarvis.interrupted == 1

    def test_mute_flips_and_says_what_the_button_should_read(self, api):
        assert api.control("mute") == "Unmute voice"
        assert api.jarvis.muted is True
        assert api.control("mute") == "Mute voice"

    def test_an_unknown_control_does_nothing(self, api):
        assert api.control("self-destruct") == ""

    def test_the_launcher_uses_this_bridge(self):
        source = (bridge.__file__.rsplit("jarvis", 1)[0] + "launcher_web.py")
        text = open(source, encoding="utf-8").read()
        assert "from jarvis.app.bridge import Api" in text
        assert "class Api" not in text
