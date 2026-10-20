"""Chapter 35 — voice conversation mode.

After answering you, LITTLE listens a little longer without its name, for a
few follow-ups at most. "Close it" knows what was just opened. STOP and
CANCEL stop; NEVER MIND drops it without asking the model; CONTINUE picks a
stopped plan up where it stopped. Stand-in microphone throughout.
"""
from __future__ import annotations

import json

import pytest

from jarvis import tools
from jarvis.ai import planner
from jarvis.app import assistant, tasks
from jarvis.routing import router
from jarvis.voice import conversation


class FakeBrain:
    def __init__(self, reply="All done."):
        self.reply, self.asked = reply, []

    def ask(self, text, on_action=None):
        self.asked.append(text)
        return self.reply


@pytest.fixture(autouse=True)
def fresh():
    conversation.forget()
    planner._resumable = None
    yield
    conversation.forget()
    planner._resumable = None


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
    made = assistant.Jarvis(log_fn=lambda _l: None)
    made.muted = True
    made.brain = FakeBrain()
    return made


@pytest.fixture
def apps(monkeypatch):
    done = []
    monkeypatch.setattr(router.apps, "open_app", lambda name: done.append(("open", name)) or f"Opening {name}.")
    monkeypatch.setattr(router.apps, "close_app", lambda name: done.append(("close", name)) or f"Closed {name}.")
    return done


def texts(n):
    return [t["text"] for t in reversed(tasks.recent(n))]


# ================================================================ context

class TestContext:
    def test_close_it_closes_what_was_just_opened(self, bot, apps):
        bot.handle("open notepad")
        bot.handle("close it")
        assert apps == [("open", "notepad"), ("close", "notepad")]
        assert tasks.recent(1)[0]["text"] == "close it", "the task keeps what you said"

    def test_only_for_a_couple_of_minutes(self, bot, apps, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(conversation.time, "monotonic", lambda: clock[0])
        bot.handle("open notepad")
        clock[0] += conversation.SUBJECT_FOR + 1
        assert conversation.resolve("close it") == "close it"

    def test_a_failed_open_or_the_models_answer_isnt_remembered(self):
        conversation.note("open notepad", "I couldn't find notepad.", "local")
        assert conversation.resolve("close it") == "close it"
        conversation.note("open the pod bay doors", "I'm afraid I can't.", "model")
        assert conversation.resolve("close that") == "close that"

    @pytest.mark.parametrize("said,meant", [("close it", "close chrome"), ("Close that one.", "Close chrome"),
                                            ("minimise it", "minimise chrome"), ("switch to this", "switch to chrome")])
    def test_the_pronouns(self, said, meant):
        conversation.note("open chrome", "Opening chrome.", "local")
        assert conversation.resolve(said) == meant

    def test_everything_else_is_left_alone(self):
        conversation.note("open chrome", "Opening chrome.", "local")
        assert conversation.resolve("close it and open notepad") == "close it and open notepad"
        assert conversation.resolve("what is it") == "what is it"


# =========================================================== the four words

class TestStopCancelNeverMindContinue:
    @pytest.mark.parametrize("said", ["never mind", "Nevermind.", "forget it", "leave it", "rehne do", "chhodo"])
    def test_never_mind_drops_it_without_the_model(self, bot, said, monkeypatch):
        stopped = []
        monkeypatch.setattr(assistant, "stop_speaking", lambda: stopped.append(1))
        bot.conversation_open = True
        bot.handle(said)
        task = tasks.recent(1)[0]
        assert task["reply"] == "Okay." and task["path"] == "fast" and bot.brain.asked == []
        assert stopped and bot.conversation_open is False

    def test_never_mind_in_a_sentence_is_a_sentence(self, bot):
        bot.handle("never mind the weather, tell me a joke")
        assert bot.brain.asked == ["never mind the weather, tell me a joke"]

    @pytest.mark.parametrize("said", ["stop", "cancel"])
    def test_stop_and_cancel_close_the_conversation(self, bot, said):
        bot.conversation_open = True
        bot.handle(said)
        assert tasks.recent(1)[0]["reply"] == "Stopped." and bot.conversation_open is False

    @pytest.mark.parametrize("said", ["continue", "carry on", "Go on.", "resume the plan", "keep going"])
    def test_the_continue_words(self, said):
        assert conversation.wants_to_continue(said)

    def test_continue_with_nothing_to_resume_goes_to_the_model(self, bot):
        bot.handle("continue")
        assert bot.brain.asked == ["continue"] and tasks.recent(1)[0]["path"] == "ai"


class Steps(FakeBrain):
    """Answers each plan step; says no to the first thing that asks."""

    def __init__(self, workspace, fail_first_at=None):
        super().__init__()
        self.workspace, self.fail_first_at = workspace, fail_first_at

    def ask(self, text, on_action=None):
        self.asked.append(text)
        if self.fail_first_at and f"Do step {self.fail_first_at} now" in text and self.fail_first_at not in getattr(self, "failed", set()):
            self.failed = getattr(self, "failed", set()) | {self.fail_first_at}
            return "FAILED: the server is down"
        if text.startswith("Step ") and "didn't work" in text:
            return "FAILED: still down"
        return "Done that."


class TestContinuingAPlan:
    PLAN = json.dumps({"goal": "Three things", "steps": [{"do": "One"}, {"do": "Two"}, {"do": "Three"}]})

    @pytest.fixture
    def planned(self, monkeypatch):
        monkeypatch.setattr(planner, "ask_text", lambda *_a: self.PLAN)

    def test_a_failed_plan_is_picked_up_where_it_stopped(self, bot, planned, workspace):
        bot.brain = Steps(workspace, fail_first_at=2)
        bot.handle("do one and then two and then three")
        assert tasks.recent(1)[0]["status"] == tasks.FAILED
        assert planner.resumable() == {"goal": "do one and then two and then three", "at": 2, "count": 3}
        bot.brain.asked.clear()
        bot.handle("continue")
        task = tasks.recent(1)[0]
        assert task["status"] == tasks.DONE and task["path"] == "agent"
        assert task["reply"] == "Done: steps 2 to 3. Done that."
        assert [p["status"] for p in task["plan"]] == ["done", "done", "done"]
        assert not any("Do step 1 now" in asked for asked in bot.brain.asked), "step 1 isn't done again"
        assert planner.resumable() is None, "a finished plan can't be continued"

    def test_a_no_can_be_continued_and_it_asks_again(self, bot, monkeypatch, workspace):
        (workspace / "old").mkdir()
        monkeypatch.setattr(planner, "ask_text", lambda *_a: json.dumps(
            {"goal": "Clean", "steps": [{"do": "Delete old"}, {"do": "Say done"}]}))
        asked = []

        class Deleting(FakeBrain):
            history: list = []

            def ask(self, text, on_action=None):
                self.asked.append(text)
                if "Delete old" in text and "Do step 1" in text:
                    from jarvis.tools import registry
                    return registry.execute_tool("delete_path", {"path": "old"})
                return "Done."
        bot.brain = Deleting()
        tools.set_confirm(lambda ask: asked.append(ask) or False)
        try:
            bot.handle("clean the old folder and then say done")
            assert tasks.recent(1)[0]["status"] == tasks.STOPPED and planner.resumable()["at"] == 1
            tools.set_confirm(lambda ask: asked.append(ask) or True)
            bot.handle("continue")
        finally:
            tools.set_confirm(lambda _m: False)
        assert len(asked) == 2, "asked again, not carried over"
        assert not (workspace / "old").exists() and tasks.recent(1)[0]["status"] == tasks.DONE

    def test_a_newer_plan_that_finishes_leaves_nothing_to_continue(self, bot, planned, workspace):
        bot.brain = Steps(workspace, fail_first_at=2)
        bot.handle("do one and then two and then three")
        assert planner.resumable() is not None
        bot.brain = Steps(workspace)
        bot.handle("do one and then two and then three again")
        assert planner.resumable() is None

    def test_too_old_to_continue(self, bot, planned, workspace, monkeypatch):
        bot.brain = Steps(workspace, fail_first_at=2)
        bot.handle("do one and then two and then three")
        planner._resumable["when"] -= planner.RESUMABLE_FOR + 1
        assert planner.resumable() is None
        bot.handle("continue")
        assert tasks.recent(1)[0]["path"] == "ai"

    def test_not_while_another_plan_runs(self, planned, workspace):
        planner._resumable = {"command": "x", "understood": "", "steps": [{"do": "a", "check": "", "files": []}] * 2,
                              "at": 2, "when": planner.time.monotonic()}
        planner._lock.acquire()
        try:
            out = {}
            said = planner.resume(FakeBrain(), lambda _l: None, lambda _s: None, outcome=out)
        finally:
            planner._lock.release()
        assert said == "I'm already working through a plan. Say stop to cancel it." and out["status"] == "failed"


# ============================================================ follow-ups

class Mic:
    """Plays phrases in turn; None is silence. Stops the loop when it runs out."""

    def __init__(self, bot, phrases):
        self.bot, self.phrases, self.calls = bot, list(phrases), []
        self.kept_here = False

    def listen(self, **kw):
        self.calls.append(kw)
        if not self.phrases:
            self.bot.running = False
            return None
        return self.phrases.pop(0)


def talk(bot, *phrases):
    states = []
    bot.status = states.append
    bot.listener = Mic(bot, phrases)
    bot.running = True
    bot._voice_loop()
    return bot.listener, states


class TestFollowUps:
    def test_a_follow_up_needs_no_name(self, bot):
        mic, states = talk(bot, "little what's the time", "and the date?", None, "what's the date")
        assert texts(2) == ["what's the time", "and the date"]
        assert mic.calls[1] == {"timeout": conversation.FOLLOW_UP, "phrase_limit": 15}, "not wake-gated"
        assert "waiting for command" in states

    def test_after_a_silence_the_name_is_needed_again(self, bot):
        talk(bot, "little what's the time", None, "what's the date")
        assert texts(1) == ["what's the time"]

    def test_a_few_in_a_row_at_most(self, bot):
        talk(bot, "little what's the time", "one", "two", "three", "four")
        assert texts(4) == ["what's the time", "one", "two", "three"], "the fourth needs the name"

    def test_never_mind_closes_it(self, bot):
        talk(bot, "little what's the time", "never mind", "what's the date")
        assert texts(2) == ["what's the time", "never mind"]

    def test_saying_the_name_in_a_follow_up_is_fine(self, bot):
        talk(bot, "little what's the time", "little what's the date")
        assert texts(2) == ["what's the time", "what's the date"]

    def test_it_keeps_the_context(self, bot, apps):
        talk(bot, "little open notepad", "close it")
        assert apps == [("open", "notepad"), ("close", "notepad")]

    def test_off_when_set_to_zero(self, bot, monkeypatch):
        monkeypatch.setattr(conversation, "FOLLOW_UP", 0.0)
        mic, _ = talk(bot, "little what's the time", "what's the date")
        assert texts(1) == ["what's the time"] and all("wake" in c for c in mic.calls)

    def test_a_lost_connection_ends_it_quietly(self, bot):
        class Flaky(Mic):
            def listen(self, **kw):
                if "wake" not in kw:
                    raise ConnectionError("offline")
                return super().listen(**kw)
        bot.listener = Flaky(bot, ["little what's the time"])
        bot.running = True
        bot._voice_loop()
        assert bot.conversation_open is False

    @pytest.mark.parametrize("raw,value", [("", 6.0), ("0", 0.0), ("10", 10.0), ("99", 30.0), ("soon", 6.0)])
    def test_the_setting(self, raw, value):
        assert conversation._seconds(raw, 6.0) == value
