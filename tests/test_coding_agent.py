"""Chapter 44 — the coding agent: inspect, explain the plan, make the smallest
change, test, report.

A real little project with a real bug and real pytest tests, run for real
before and after. The model's plan is played by the test. Nothing is
changed without one yes; a plan that isn't exact, small and inside the
workspace changes nothing; and the change can be undone.
"""
from __future__ import annotations

import json

import pytest

from jarvis import tools
from jarvis.ai import coder, provider
from jarvis.routing.router import fast_route
from jarvis.tools import permissions, registry

CALC = '''def add(a, b):
    return a - b


def double(x):
    return x * 2
'''
TESTS = '''from calc import add, double


def test_add():
    assert add(2, 3) == 5


def test_double():
    assert double(4) == 8
'''
FIX = {"understood": "add subtracts instead of adding.", "plan": ["Read calc.py", "Make add use +"],
       "changes": [{"path": "calc.py", "old": "    return a - b", "new": "    return a + b", "why": "add should add"}]}


@pytest.fixture
def project(workspace):
    root = workspace / "calcproj"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (root / "calc.py").write_text(CALC, encoding="utf-8")
    (root / "test_calc.py").write_text(TESTS, encoding="utf-8")
    (root / "notes.md").write_text("Nothing about maths.", encoding="utf-8")
    return root


@pytest.fixture
def model(monkeypatch):
    said = {"plan": FIX, "prompts": []}

    def ask(prompt, system=None, empty=""):
        said["prompts"].append(prompt)
        if isinstance(said["plan"], Exception):
            raise said["plan"]
        return said["plan"] if isinstance(said["plan"], str) else json.dumps(said["plan"])
    monkeypatch.setattr(provider, "ask_text", ask)
    return said


@pytest.fixture
def answer():
    asked = {"asks": [], "yes": True}
    tools.set_confirm(lambda ask: asked["asks"].append(ask) or asked["yes"])
    yield asked
    tools.set_confirm(lambda _m: False)


class TestTheWholeWay:
    def test_inspect_plan_change_test_report(self, project, model, answer):
        said = coder.code_change("fix the add function in calc.py", "calcproj")
        inspect, plan, change, test, report = said.split("\n")
        assert inspect.startswith("INSPECT: read calc.py") and inspect.endswith("tests run with python -m pytest -q.")
        assert plan == "PLAN: add subtracts instead of adding. Read calc.py → Make add use +"
        assert change == "CHANGE: calc.py (add should add)."
        assert test.startswith("TEST: before the change 1 failed, 1 passed") and "after it passed — 2 passed" in test
        assert report.startswith("REPORT: done, and the tests pass.")
        assert (project / "calc.py").read_text() == CALC.replace("a - b", "a + b")

    def test_the_model_sees_the_relevant_files_and_how_tests_run(self, project, model, answer):
        coder.code_change("fix add in calc", "calcproj")
        (prompt,) = model["prompts"]
        assert "--- calc.py ---\ndef add(a, b):" in prompt and "Tests are run with: " in prompt
        assert "--- notes.md ---" not in prompt, "only what's relevant is read"

    def test_one_question_with_the_changes_in_it(self, project, model, answer):
        coder.code_change("fix the add function", "calcproj")
        (ask,) = answer["asks"]
        parts = ask.parts()
        assert parts["action"] == "Change your code and run its tests" and parts["target"] == "calc.py in calcproj"
        assert "-     return a - b\n+     return a + b" in parts["details"]
        assert parts["details"].endswith("Then the tests: python -m pytest -q")
        assert permissions.level("code_change") == permissions.CONFIRM

    def test_no_means_nothing_changes_and_nothing_runs(self, project, model, answer, monkeypatch):
        answer["yes"] = False
        monkeypatch.setattr(coder, "run_tests", lambda *_a: pytest.fail("tests ran"))
        assert coder.code_change("fix the add function", "calcproj") == "You said no, so I changed nothing."
        assert (project / "calc.py").read_text() == CALC

    def test_a_change_that_breaks_the_tests_is_reported_as_such(self, project, model, answer):
        model["plan"] = {"understood": "x", "plan": ["y"], "changes": [
            {"path": "calc.py", "old": "    return x * 2", "new": "    return x * 3", "why": "triple"}]}
        said = coder.code_change("make double triple", "calcproj")
        assert "after it FAILED" in said and "REPORT: the change is made but the tests don't pass." in said

    def test_a_new_file(self, project, model, answer):
        model["plan"] = {"understood": "x", "plan": ["y"], "changes": [], "create": [
            {"path": "helpers.py", "content": "def triple(x):\n    return x * 3\n", "why": "a helper"}]}
        assert "CHANGE: helpers.py (new file)." in coder.code_change("add a triple helper", "calcproj")
        assert (project / "helpers.py").exists()


class TestSmallOrNothing:
    @pytest.mark.parametrize("change,why", [
        ({"path": "calc.py", "old": "return a * b", "new": "x"}, "was found 0 times, not once"),
        ({"path": "calc.py", "old": "    return", "new": "x"}, "was found 2 times, not once"),
        ({"path": "nope.py", "old": "a", "new": "b"}, "nope.py doesn't exist."),
        ({"path": "../../etc/hosts", "old": "a", "new": "b"}, "outside the workspace"),
        ({"path": "calc.py", "old": "    return a - b", "new": "\n".join(["x"] * 60)}, "rewrites too much of it"),
        ({"path": "calc.py"}, "missing its file or text"),
    ])
    def test_a_bad_plan_changes_nothing(self, project, model, answer, change, why):
        model["plan"] = {"understood": "x", "plan": ["y"], "changes": [change]}
        said = coder.code_change("do it", "calcproj")
        assert why in said and answer["asks"] == [] and (project / "calc.py").read_text() == CALC

    def test_one_bad_change_stops_the_good_ones_too(self, project, model, answer):
        model["plan"] = {"understood": "x", "plan": ["y"], "changes": [
            FIX["changes"][0], {"path": "calc.py", "old": "not there", "new": "x"}]}
        coder.code_change("do it", "calcproj")
        assert (project / "calc.py").read_text() == CALC

    def test_rewriting_a_whole_big_file_isnt_small(self, project, model, answer):
        big = "\n".join(f"line_{i} = {i}" for i in range(60)) + "\n"
        (project / "big.py").write_text(big, encoding="utf-8")
        model["plan"] = {"understood": "x", "plan": ["y"], "changes": [
            {"path": "big.py", "old": "\n".join(big.splitlines()[:39]), "new": "x = 1"}]}
        assert "rewrites too much" in coder.code_change("tidy big.py", "calcproj")

    def test_too_many_files(self, project, model, answer):
        for i in range(6):
            (project / f"m{i}.py").write_text(f"v = {i}\n", encoding="utf-8")
        model["plan"] = {"understood": "x", "plan": ["y"], "changes": [
            {"path": f"m{i}.py", "old": f"v = {i}", "new": f"v = {i + 1}"} for i in range(6)]}
        assert "more than 5 files" in coder.code_change("bump them", "calcproj")

    def test_no_overwriting_by_creating(self, project, model, answer):
        model["plan"] = {"understood": "x", "plan": ["y"], "create": [{"path": "calc.py", "content": "x"}]}
        assert "calc.py already exists; I won't overwrite it." in coder.code_change("do it", "calcproj")

    @pytest.mark.parametrize("plan", ["not json at all", "[1, 2]", {"understood": "x", "changes": []}])
    def test_an_unreadable_or_empty_plan(self, project, model, answer, plan):
        model["plan"] = plan
        said = coder.code_change("do it", "calcproj")
        assert ("couldn't be read" in said or "had no changes" in said) and answer["asks"] == []

    def test_the_model_unreachable(self, project, model, answer):
        model["plan"] = RuntimeError("I can't reach the internet right now.")
        assert coder.code_change("do it", "calcproj") == \
            "I couldn't get a plan from the model: I can't reach the internet right now. Nothing was changed."

    def test_outside_the_workspace_or_empty(self, tmp_path, model):
        assert "outside the workspace" in coder.code_change("do it", str(tmp_path))
        assert coder.code_change("  ", "calcproj") == "Tell me what to change."


class TestTests:
    def test_how_tests_are_found(self, workspace):
        root = workspace / "p"
        root.mkdir()
        assert coder.test_command(root) is None
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}), encoding="utf-8")
        assert coder.test_command(root) == ["npm", "test", "--silent"]
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "echo \"Error: no test specified\""}}))
        assert coder.test_command(root) is None
        (root / "tests").mkdir()
        (root / "tests" / "test_x.py").write_text("", encoding="utf-8")
        assert coder.shown(coder.test_command(root)) == "python -m pytest -q"

    def test_no_tests_is_said(self, workspace, model, answer):
        root = workspace / "plain"
        root.mkdir()
        (root / "calc.py").write_text(CALC, encoding="utf-8")
        said = coder.code_change("fix add in calc.py", "plain")
        assert "no tests found" in said and "The change is untested." in said
        assert answer["asks"][0].parts()["action"] == "Change your code"

    def test_a_test_runner_that_isnt_there(self, workspace):
        assert coder.run_tests(workspace, ["no-such-runner-xyz"]) == \
            {"ran": False, "ok": None, "summary": "no-such-runner-xyz isn't installed"}


class TestUndo:
    def test_it_puts_the_originals_back_and_removes_what_it_made(self, project, model, answer):
        model["plan"] = dict(FIX, create=[{"path": "helpers.py", "content": "x = 1\n", "why": "h"}])
        coder.code_change("fix add", "calcproj")
        assert fast_route("undo the last code change") == "Undone: calc.py, helpers.py are back as they were."
        assert (project / "calc.py").read_text() == CALC and not (project / "helpers.py").exists()
        assert answer["asks"][-1].parts()["action"] == "Undo a code change"
        assert coder.undo_last() == "There's no code change of mine to undo."

    def test_no_keeps_it(self, project, model, answer):
        coder.code_change("fix add", "calcproj")
        answer["yes"] = False
        assert coder.undo_last() == "Okay, I left it."
        assert "a + b" in (project / "calc.py").read_text()


class TestReachingIt:
    def test_by_command_and_as_a_tool(self, project, model, answer, monkeypatch):
        said = fast_route("In the code, fix the add function in calcproj/calc.py")
        assert said.startswith("INSPECT:")
        monkeypatch.setattr(coder, "code_change", lambda request, path=".": f"<{request}|{path}>")
        assert registry.execute_tool("code_change", {"request": "fix it", "path": "calcproj"}) == "<fix it|calcproj>"
        assert "code_change" in registry.FUNCTIONS and permissions.level("undo_code_change") == permissions.CONFIRM
