"""The planner decides when a request is worth an extra model call, and
what happens when one of its steps fails."""
from __future__ import annotations

import pytest

from jarvis.ai import planner


class FakeBrain:
    """Stands in for the model so a whole plan can run with no network."""

    def __init__(self, fail_at: int | set | None = None) -> None:
        self.asked: list[str] = []
        self.fail_at = {fail_at} if isinstance(fail_at, int) else (fail_at or set())

    def ask(self, text: str) -> str:
        self.asked.append(text)
        if len(self.asked) in self.fail_at:
            return "FAILED: npm is not on PATH"
        return f"step {len(self.asked)} done"


@pytest.fixture
def four_steps(monkeypatch):
    monkeypatch.setattr(planner, "ask_text", lambda _p: """1. Check that Node.js is installed
2. Create the project with Vite
3. Install dependencies
4. Start the dev server""")


class TestWhenToPlan:
    @pytest.mark.parametrize("command", [
        "create a react portfolio project and run it",
        "install the dependencies and then start the server",
        "make a python project with tests",
        "fix all the errors in my project",
        "set up an express api and run it",
    ])
    def test_multi_part_requests_are_planned(self, command):
        assert planner.should_plan(command) is True

    @pytest.mark.parametrize("command", [
        "open chrome",
        "what is the time",
        "summarize this page",
        "remind me to call mom at 8 pm",
        "draft a message to rahul saying I will be late",
        "create a folder called notes",
    ])
    def test_single_actions_skip_the_planning_call(self, command):
        assert planner.should_plan(command) is False


class TestParsing:
    def test_numbered_lines_become_steps_and_prose_is_ignored(self):
        steps = planner._parse("""Here is the plan:
1. Check Node.js
2) Create the project
something that is not a step
3. Install dependencies""")
        assert steps == ["Check Node.js", "Create the project", "Install dependencies"]

    def test_the_step_count_is_capped(self):
        many = "\n".join(f"{i}. step {i}" for i in range(1, 30))
        assert len(planner._parse(many)) <= planner.MAX_STEPS


class TestRunning:
    def test_every_step_runs_in_order(self, four_steps):
        brain = FakeBrain()
        lines: list[str] = []
        result = planner.run("create a react app and run it", brain, lines.append, lambda s: None)
        assert len(brain.asked) == 4
        assert "all 4 steps" in result
        assert "[1/4]" in "".join(lines) and "[4/4]" in "".join(lines)

    def test_a_failed_step_stops_the_rest(self, four_steps):
        # Chapter 32: a failed step gets one more try; failing again, it stops.
        brain = FakeBrain(fail_at={2, 3})
        result = planner.run("create a react app and run it", brain, lambda _l: None, lambda s: None)
        assert len(brain.asked) == 3, "steps after the failure should not run"
        assert brain.asked[2].startswith("Step 2 of your plan didn't work.")
        assert not any("Do step 3" in asked for asked in brain.asked)
        assert "step 2 of 4" in result and "npm is not on PATH" in result

    def test_the_model_can_say_the_request_is_simple(self, monkeypatch):
        monkeypatch.setattr(planner, "ask_text", lambda _p: "SIMPLE")
        brain = FakeBrain()
        result = planner.run("create a thing", brain, lambda _l: None, lambda s: None)
        assert result == "step 1 done"
        assert len(brain.asked) == 1

    def test_a_one_line_plan_is_run_directly(self, monkeypatch):
        monkeypatch.setattr(planner, "ask_text", lambda _p: "1. Just do it")
        brain = FakeBrain()
        planner.run("do the thing", brain, lambda _l: None, lambda s: None)
        assert len(brain.asked) == 1

    def test_the_plan_is_visible_while_it_runs_and_cleared_after(self, four_steps):
        seen: list[dict] = []

        class Watching(FakeBrain):
            def ask(self, text):
                snapshot = planner.current()
                if snapshot:
                    seen.append(dict(snapshot))
                return super().ask(text)

        planner.run("create a react app and run it", Watching(), lambda _l: None, lambda s: None)
        assert [s["at"] for s in seen] == [1, 2, 3, 4]
        assert planner.current() is None, "the panel should not show a finished plan"

    def test_cancelling_stops_between_steps(self, four_steps):
        class Cancelling(FakeBrain):
            def ask(self, text):
                planner.cancel()
                return super().ask(text)

        result = planner.run("create a react app and run it", Cancelling(),
                             lambda _l: None, lambda s: None)
        assert "Stopped after step 1" in result

    def test_a_model_outage_is_reported_in_words(self, monkeypatch):
        def boom(_p):
            raise RuntimeError("I can't reach the internet right now.")
        monkeypatch.setattr(planner, "ask_text", boom)
        result = planner.run("create a react app and run it", FakeBrain(),
                             lambda _l: None, lambda s: None)
        assert "can't reach the internet" in result
