"""The router decides what never reaches the model. A command that leaks
through costs an API call; one that is caught wrongly does the wrong thing.
Both directions are worth pinning down."""
from __future__ import annotations

import pytest

from jarvis.routing import router
from jarvis.routing.router import fast_route


class TestHandledLocally:
    @pytest.mark.parametrize("command,expect", [
        ("what's the time", "It's"),
        ("time kya hai", "It's"),
        ("what's the date", "Today is"),
        ("aaj ki date", "Today is"),
    ])
    def test_clock_questions_never_reach_the_model(self, command, expect):
        assert expect in router.fast_route(command)

    def test_remember_and_recall_work_without_the_model(self):
        assert "Noted" in router.fast_route("remember that my editor is neovim")
        assert "neovim" in router.fast_route("what do you remember")

    def test_reminders_are_set_locally(self):
        assert "08:00 PM" in router.fast_route("remind me to call mom at 8 pm")
        assert "call mom" in router.fast_route("list reminders")
        router.fast_route("cancel reminders")

    def test_searching_opens_the_browser_without_the_model(self, monkeypatch):
        opened = []
        monkeypatch.setattr(router.webbrowser, "open", opened.append)
        assert "Searching" in router.fast_route("search python internships")
        assert "google.com/search" in opened[0]

    def test_youtube_search_uses_the_youtube_url(self, monkeypatch):
        opened = []
        monkeypatch.setattr(router.webbrowser, "open", opened.append)
        router.fast_route("search react tutorials on youtube")
        assert "youtube.com/results" in opened[0]

    def test_a_known_site_opens_directly(self, monkeypatch):
        opened = []
        monkeypatch.setattr(router.webbrowser, "open", opened.append)
        assert "github" in router.fast_route("open github").lower()
        assert opened == ["https://github.com"]


class TestPassedToTheModel:
    @pytest.mark.parametrize("command", [
        "tell me a joke about cats",
        "explain what a closure is",
        "write a function that reverses a list",
        "why did that fail",
        "open the thing i was working on",
    ])
    def test_anything_needing_thought_falls_through(self, command):
        assert router.fast_route(command) is None

    def test_an_empty_command_falls_through(self):
        assert router.fast_route("   ") is None


class TestHinglish:
    def test_hinglish_open_is_understood(self, monkeypatch):
        monkeypatch.setattr(router.apps, "resolve", lambda n: "chrome")
        monkeypatch.setattr(router.apps, "open_app", lambda n: f"Opening {n}.")
        assert "Opening chrome" in router.fast_route("chrome kholo")

    def test_hinglish_close_is_understood(self, monkeypatch):
        monkeypatch.setattr(router.apps, "resolve", lambda n: "spotify")
        monkeypatch.setattr(router.apps, "close_app", lambda n: f"Closed {n}.")
        assert "Closed spotify" in router.fast_route("spotify band karo")


class TestATypedCommandReachesTheFastLane:
    """The panel invites you to type a command, and people type it the way
    they say it: "Jarvis, find jobs for me". Speech arrives with the wake
    word already removed; typing does not. Left on, it makes every local
    pattern miss, so the command falls through to the model and takes eighty
    seconds to do what the router does instantly.
    """

    @pytest.mark.parametrize("typed,expected", [
        ("Jarvis, find jobs for me", "find jobs for me"),
        ('"Jarvis, find jobs for me', "find jobs for me"),
        ("jarvis open chrome", "open chrome"),
        ("Hey Jarvis, what is the time", "what is the time"),
        ("JARVIS: show my top matches", "show my top matches"),
        ("  'jarvis,  run a system check '  ", "run a system check"),
        ("find jobs for me", "find jobs for me"),
    ])
    def test_the_address_is_removed_however_it_was_typed(self, typed, expected):
        from jarvis.app.assistant import strip_address
        assert strip_address(typed) == expected

    @pytest.mark.parametrize("said", [
        "what does jarvis mean",
        "ask jarvis about the weather",
        "rename the file to jarvis notes",
    ])
    def test_a_sentence_that_merely_mentions_the_name_is_left_alone(self, said):
        """Only an opening address is an address. A question about the name
        is a question."""
        from jarvis.app.assistant import strip_address
        assert strip_address(said) == said

    @pytest.mark.parametrize("typed", [
        "Jarvis, find jobs for me",
        "jarvis, what is the time",
        "Jarvis open chrome",
        "jarvis, show my top matches",
    ])
    def test_these_now_reach_the_router_instead_of_the_model(self, typed, tmp_path,
                                                             monkeypatch):
        from jarvis.app.assistant import strip_address
        from jarvis.jobs import store
        monkeypatch.setattr(store, "DB_PATH", tmp_path / "typed.db")
        assert fast_route(strip_address(typed)) is not None, \
            f"{typed!r} would still go to the model"

    def test_the_name_on_its_own_is_not_a_command(self):
        from jarvis.app.assistant import strip_address
        assert strip_address("Jarvis") == ""
        assert strip_address("  jarvis,  ") == ""


class TestTheStatusTellsTheTruth:
    """The panel's status is the only thing a user has to go on while a
    command runs. A heads-up spoken before the work must not leave the
    status saying SPEAKING while six job boards are being called."""

    def _assistant(self):
        from jarvis.app.assistant import Jarvis
        seen = []
        bot = Jarvis(log_fn=lambda *_a: None, status_fn=seen.append)
        bot.muted = True          # no sound card in tests
        return bot, seen

    def test_the_status_goes_back_to_working_after_the_heads_up(self):
        bot, seen = self._assistant()
        bot.status("executing")
        bot._announce("On it.")
        assert seen[-1] == "executing", f"panel was left showing {seen[-1]!r}"

    def test_a_slow_command_still_ends_up_reporting_its_work(self, monkeypatch):
        from jarvis.app import assistant as assistant_module
        bot, seen = self._assistant()
        monkeypatch.setattr(assistant_module, "fast_route", lambda _c: "done")
        bot.handle("Jarvis, find jobs for me")
        assert "executing" in seen
        # Whatever it said on the way, it must not be left mid-announcement.
        assert seen[-1] in ("listening", "offline")
