"""Chapter 47 — demo mode.

About fifty seconds, the same every time: real commands through the real
assistant, nothing personal read, nothing needing the internet or the
model, nothing changed. The one risky step goes through the real
confirmation gate and is refused. Timed by the clock, so the voice being
on, off or slow doesn't change how long it takes.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pytest

from jarvis.ai import provider
from jarvis.app import assistant, audit, config, demo, tasks
from jarvis.routing.router import fast_route
from jarvis.store import memory
from jarvis.tools import apps, browser, permissions, system

SCRIPT = Path(__file__).resolve().parent.parent / "DEMO_SCRIPT.md"
COMMANDS = [s.command for s in demo.STEPS if s.command]


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0)
    monkeypatch.setattr(provider, "call_gemini", lambda *_a, **_k: pytest.fail("the model was asked"))
    monkeypatch.setattr(apps, "open_app", lambda *_a, **_k: pytest.fail("an app was opened"))
    monkeypatch.setattr(browser._worker, "current", lambda: pytest.fail("the browser was started"))
    monkeypatch.setattr(system.subprocess, "run", lambda *_a, **_k: pytest.fail("a command ran"))
    tasks.reset()
    yield
    demo.cancel()
    for _ in range(100):
        if not demo.running():
            break
        time.sleep(0.02)
    demo._stop.clear()


@pytest.fixture
def bot(monkeypatch):
    lines, spoken = [], []
    monkeypatch.setattr(assistant, "speak", spoken.append)
    little = assistant.Jarvis(log_fn=lines.append)
    little.muted = False
    little.lines, little.spoken = lines, spoken
    return little


class TestTheScript:
    def test_forty_to_sixty_seconds(self):
        assert 40 <= demo.SECONDS <= 60

    def test_each_narration_fits_its_slot(self):
        for step in demo.STEPS:        # about two and a half words a second, with a second to spare
            assert len(step.narration.split()) / 2.5 + 1 <= step.slot, step.narration

    def test_every_command_is_answered_here_without_the_model(self):
        for command in COMMANDS:
            if command != demo.RISKY:
                assert fast_route(command), command

    def test_nothing_it_asks_reads_your_things(self):
        # No step asks for memory, contacts, the resume, jobs, files, the
        # screen or a page — the words that would read them aren't there.
        reads = re.compile(r"remember|contact|resume|job|file|screen|page|glance|system check|who am i", re.I)
        assert not [c for c in COMMANDS if reads.search(c)]

    def test_the_script_file_says_the_same(self):
        written = SCRIPT.read_text(encoding="utf-8")
        for step in demo.STEPS:
            assert step.narration in written, step.narration
            if step.command:
                assert step.command in written, step.command
        assert f"{demo.SECONDS:.0f} seconds" in written


class TestARun:
    def test_every_step_runs_as_a_real_task(self, bot):
        result = demo.run(bot)
        assert result == {"ran": len(demo.STEPS), "seconds": result["seconds"], "stopped": False,
                          "already": False}
        assert [t["text"] for t in reversed(tasks.recent(20))] == COMMANDS
        assert all(t["status"] == tasks.DONE for t in tasks.recent(20))
        assert bot.lines[-1].startswith("Demo finished in ")

    def test_only_the_narration_is_spoken(self, bot):
        demo.run(bot)
        assert bot.spoken == [s.narration for s in demo.STEPS]
        assert "LITTLE: " + tasks.recent(20)[-1]["reply"] in bot.lines, "the replies are on screen"

    def test_nothing_of_yours_appears(self, bot):
        memory.remember("my sister's name", "Meera Kapoor")
        memory.add_contact("rahul", "+919812345678")
        demo.run(bot)
        shown = "\n".join(bot.lines + bot.spoken + [t["reply"] for t in tasks.recent(20)])
        for private in ("Meera", "Kapoor", "rahul", "98123", str(config.WORKSPACE), str(config.MEMORY_DIR)):
            assert private not in shown, private

    def test_your_conversation_log_is_left_alone(self, bot):
        memory.log_turn("hello", "hi")
        before = memory.history()
        demo.run(bot)
        assert memory.history() == before

    def test_after_the_demo_replies_are_spoken_and_logged_again(self, bot):
        demo.run(bot)
        bot.spoken.clear()
        bot.handle("what's the time")
        assert bot.spoken and memory.history()[-1]["user"] == "what's the time"


class TestTheRiskyStep:
    def test_it_asks_through_the_real_gate_and_is_refused(self, bot):
        demo.run(bot)
        answer = permissions.answers()[-1]
        assert (answer["tool"], answer["approved"]) == ("run_command", False)
        risky = next(t for t in tasks.recent(20) if t["text"] == demo.RISKY)
        assert risky["reply"] == "You declined, so the command didn't run."
        assert [s["name"] for s in risky["steps"]] == ["run_command"]

    def test_the_audit_log_shows_the_no(self, bot):
        demo.run(bot)
        said = next(t for t in tasks.recent(20) if t["text"] == "what did you do for my last task")["reply"]
        assert said.startswith(f"Your last task: “{demo.RISKY}”")
        assert "run_command(command=echo hello)" in said and "you said no" in said
        tool_runs = [e for e in audit.entries(100) if e.get("kind") == "tool"]
        assert tool_runs[-1]["tool"] == "run_command"

    def test_even_if_yes_is_installed_it_says_no(self, bot):
        permissions.set_confirm(lambda _m: True)
        installed = permissions.confirm_fn
        try:
            demo.run(bot)                       # subprocess.run fails the test if the command runs
            assert permissions.confirm_fn is installed, "what was installed is put back"
        finally:
            permissions.set_confirm(lambda _m: False)

    def test_put_back_even_when_a_step_fails(self, bot, monkeypatch):
        from jarvis.tools import registry
        installed = permissions.confirm_fn
        monkeypatch.setattr(registry, "execute_tool", lambda *_a, **_k: 1 / 0)
        result = demo.run(bot)
        assert result["stopped"] and permissions.confirm_fn is installed and not demo.running()
        assert bot.lines[-1] == "The demo stopped at step 5: ZeroDivisionError."
        risky = next(t for t in tasks.recent(20) if t["text"] == demo.RISKY)
        assert risky["status"] == tasks.FAILED, "its task is closed, not left running"


class TestTiming:
    class Clock:
        def __init__(self):
            self.now, self.waits = 0.0, []

        def __call__(self):
            return self.now

    def _fake(self, monkeypatch, clock):
        class Stop:
            def is_set(self):
                return False

            def wait(self, seconds):
                clock.waits.append(seconds)
                clock.now += seconds
                return False

            def set(self):
                pass

            def clear(self):
                pass
        monkeypatch.setattr(demo, "_stop", Stop())
        monkeypatch.setattr(demo, "PACE", 1.0)

    def test_it_takes_the_scripts_time(self, bot, monkeypatch):
        clock = self.Clock()
        self._fake(monkeypatch, clock)
        result = demo.run(bot, clock=clock)
        assert result["seconds"] == demo.SECONDS and sum(clock.waits) == demo.SECONDS

    def test_slow_speech_doesnt_make_it_longer(self, bot, monkeypatch):
        clock = self.Clock()
        self._fake(monkeypatch, clock)
        monkeypatch.setattr(assistant, "speak", lambda _t: setattr(clock, "now", clock.now + 3))
        assert demo.run(bot, clock=clock)["seconds"] == demo.SECONDS

    def test_a_step_that_overruns_its_slot_isnt_waited_for(self, bot, monkeypatch):
        clock = self.Clock()
        self._fake(monkeypatch, clock)
        monkeypatch.setattr(assistant, "speak", lambda _t: setattr(clock, "now", clock.now + 10))
        result = demo.run(bot, clock=clock)
        assert clock.waits == [] and result["seconds"] == 10 * len(demo.STEPS)


class TestStopping:
    def test_stop_ends_it_before_the_next_step(self, bot, monkeypatch):
        said = []

        def speak(text):
            said.append(text)
            if len(said) == 3:
                demo.cancel()
        monkeypatch.setattr(assistant, "speak", speak)
        result = demo.run(bot)
        assert result["ran"] == 3 and result["stopped"]
        assert bot.lines[-1] == f"Demo stopped after 3 of {len(demo.STEPS)} steps."

    def test_saying_stop_stops_it(self, bot):
        assert demo._claim()
        try:
            bot.handle("stop")
            assert demo._stop.is_set()
        finally:
            demo._running.clear()
            demo._stop.clear()

    def test_one_at_a_time(self, bot):
        assert demo._claim()
        try:
            assert demo.start(bot) == demo.ALREADY
            assert demo.run(bot)["already"]
        finally:
            demo._running.clear()

    def test_cancel_when_nothing_runs_does_nothing(self):
        demo.cancel()
        assert not demo._stop.is_set()


class TestByCommand:
    @pytest.mark.parametrize("said", ["start the demo", "run the demo", "demo mode", "show me a demo",
                                      "demo dikhao", "Start the demo."])
    def test_it_starts(self, bot, said):
        bot.handle(said)
        first = tasks.recent(20)[-1]
        assert first["reply"] == demo.STARTING and first["path"] == "fast"
        for _ in range(200):
            if not demo.running():
                break
            time.sleep(0.02)
        assert not demo.running()
        assert [t["text"] for t in reversed(tasks.recent(20))][1:] == COMMANDS

    def test_starting_is_said_before_the_demos_first_line(self, bot):
        bot.handle("start the demo")
        for _ in range(200):
            if not demo.running():
                break
            time.sleep(0.02)
        starting = bot.lines.index("LITTLE: " + demo.STARTING)
        assert starting < bot.lines.index(f"Demo · {demo.STEPS[0].narration}")

    def test_its_own_thread(self, bot):
        seen = []
        real = demo._run
        demo_thread = threading.current_thread()

        def spy(*a):
            seen.append(threading.current_thread() is not demo_thread)
            return real(*a)
        demo._run = spy
        try:
            bot.handle("start the demo")
            for _ in range(200):
                if not demo.running():
                    break
                time.sleep(0.02)
        finally:
            demo._run = real
        assert seen == [True]
