"""Chapter 32 — Planner 2.0: understand, plan, execute, observe, verify,
recover, result.

A step is done when something shows it: the files it should leave are on
disk, or the tools' own output meets its check. The model's word alone is
never a check. A step that fails gets one more try; your "no" gets none.
And "prepare my project for GitHub" ends with the checklist run again,
by LITTLE, not by the model.
"""
from __future__ import annotations

import json

import pytest

from jarvis import tools
from jarvis.ai import planner
from jarvis.app import tasks
from jarvis.tools import project_check, registry


def plan(*steps, goal="Make the thing"):
    return json.dumps({"goal": goal, "steps": list(steps)})


class Scripted:
    """A brain that, for each ask, runs the tools its script names through
    the real registry, keeps the model's history the way the brain does,
    and answers with the script's words."""

    def __init__(self, *script):
        self.script = list(script)
        self.asked: list[str] = []
        self.history: list[dict] = []

    def ask(self, text):
        self.asked.append(text)
        calls, reply = self.script.pop(0) if self.script else ([], "Done.")
        self.history.append({"role": "user", "parts": [{"text": text}]})
        if calls:
            self.history.append({"role": "model", "parts": [{"functionCall": {"name": n, "args": a}} for n, a in calls]})
            self.history.append({"role": "user", "parts": [
                {"functionResponse": {"name": n, "response": {"result": registry.execute_tool(n, a)}}}
                for n, a in calls]})
        self.history.append({"role": "model", "parts": [{"text": reply}]})
        return reply


@pytest.fixture
def model(monkeypatch):
    """The planning call returns `plan`; each check returns the next of `checks`."""
    said = {"plan": "", "checks": [], "prompts": []}

    def ask(prompt):
        said["prompts"].append(prompt)
        if prompt.startswith("Break this request"):
            return said["plan"]
        if not said["checks"]:
            raise AssertionError("an unexpected check was asked")
        answer = said["checks"].pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer)
    monkeypatch.setattr(planner, "ask_text", ask)
    return said


def run(command, brain):
    lines, outcome = [], {}
    reply = planner.run(command, brain, lines.append, lambda _s: None, outcome=outcome)
    return reply, outcome, lines


# ============================================================ understand

class TestUnderstandingAndPlanning:
    def test_a_json_plan_brings_the_goal_checks_and_files(self):
        goal, steps = planner._parse_plan('Sure! {"goal": "Build it", "steps": ['
                                          '{"do": "Write app.py.", "check": "the file is written", "files": ["app.py"]},'
                                          ' "Run the tests", {"do": "x"}, 7, {"do": "Open it", "files": "no"}]}')
        assert goal == "Build it"
        assert steps == [{"do": "Write app.py", "check": "the file is written", "files": ["app.py"]},
                         {"do": "Run the tests", "check": "", "files": []},
                         {"do": "Open it", "check": "", "files": []}]

    def test_a_numbered_list_still_works_without_checks(self):
        goal, steps = planner._parse_plan("1. One thing\n2. Another thing")
        assert goal == "" and [s["do"] for s in steps] == ["One thing", "Another thing"]
        assert all(s["check"] == "" and s["files"] == [] for s in steps)

    def test_capped(self):
        _, steps = planner._parse_plan(plan(*[{"do": f"step {i}"} for i in range(20)]))
        assert len(steps) == planner.MAX_STEPS

    def test_the_goal_is_said_and_each_step_is_told_its_check(self, model, workspace):
        model["plan"] = plan({"do": "Write notes.txt", "files": ["notes.txt"]},
                             {"do": "List the folder", "check": "notes.txt is listed"}, goal="Keep notes")
        model["checks"] = [{"verified": True, "evidence": "notes.txt in the listing"}]
        brain = Scripted(([("write_file", {"path": "notes.txt", "content": "hi"})], "Wrote it."),
                         ([("list_dir", {"path": "."})], "Listed."))
        reply, outcome, lines = run("write notes and then list the folder", brain)
        assert lines[0] == "Goal: Keep notes"
        assert "It worked if: notes.txt is listed" in brain.asked[1]
        assert reply == "Done, all 2 steps, each checked. Listed." and outcome["status"] == "done"

    def test_only_results_and_evidence_are_shown_never_reasoning(self, model, workspace):
        model["plan"] = json.dumps({"goal": "Do it", "reasoning": "SECRET-THOUGHTS because…",
                                    "steps": [{"do": "One", "why": "MORE-THOUGHTS"}, {"do": "Two"}]})
        _, _, lines = run("do one and then two", Scripted())
        shown = "\n".join(lines)
        assert "SECRET-THOUGHTS" not in shown and "MORE-THOUGHTS" not in shown
        assert "no explanation" in planner.PLAN


# ================================================================ observe

class TestObserving:
    def test_the_tools_that_ran_and_what_they_returned(self, workspace):
        brain = Scripted(([("write_file", {"path": "a.txt", "content": "x"})], "ok"))
        before = planner._entries(brain)
        brain.ask("go")
        (seen,) = planner._observe(brain, before)
        assert seen["tool"] == "write_file" and seen["args"] == {"path": "a.txt", "content": "x"}
        assert seen["result"].startswith("Created ")

    def test_only_since_the_step_began(self, workspace):
        brain = Scripted(([("list_dir", {"path": "."})], "ok"), ([], "nothing ran"))
        brain.ask("first")
        before = planner._entries(brain)
        brain.ask("second")
        assert planner._observe(brain, before) == []

    def test_a_brain_without_history_is_observed_as_nothing(self):
        class Bare:
            def ask(self, text):
                return "ok"
        assert planner._observe(Bare(), planner._entries(Bare())) == []


# ================================================================= verify

class TestVerifying:
    def test_files_are_looked_for_on_disk(self, model, workspace):
        model["plan"] = plan({"do": "Write a.txt", "files": ["a.txt"]}, {"do": "Write b.txt", "files": ["b.txt"]})
        brain = Scripted(([("write_file", {"path": "a.txt", "content": "x"})], "Wrote a.txt."),
                         ([], "Wrote b.txt."),                     # says so; didn't
                         ([], "Wrote b.txt, really."))             # the one more try, still not
        reply, outcome, lines = run("write a and then b", brain)
        assert outcome["status"] == "failed" and outcome["error"] == "Step 2 of 2: b.txt isn't there."
        assert brain.asked[2].startswith("Step 2 of your plan didn't work.") and "b.txt isn't there" in brain.asked[2]
        assert "      didn't work: b.txt isn't there. Trying once more." in lines

    def test_the_check_is_judged_from_the_tools_output(self, model, workspace):
        (workspace / "app.py").write_text("print(1)", encoding="utf-8")
        model["plan"] = plan({"do": "Read app.py", "check": "it prints something"}, {"do": "Say it's fine"})
        model["checks"] = [{"verified": True, "evidence": "print(1)"}]
        brain = Scripted(([("read_file", {"path": "app.py"})], "It prints 1."), ([], "Fine."))
        reply, _, lines = run("read app.py and then tell me", brain)
        (check,) = [p for p in model["prompts"] if p.startswith("A step of a plan")]
        assert "- read_file:    1 | print(1)" in check and "It worked if: it prints something" in check
        assert "      checked: print(1)" in lines
        assert reply == "Done, all 2 steps; step 2 couldn't be checked. Fine."

    def test_the_models_word_alone_is_never_a_check(self, model, workspace):
        model["plan"] = plan({"do": "Deploy it", "check": "the site is live"}, {"do": "Tell me"})
        reply, outcome, lines = run("deploy it and then tell me", Scripted(([], "Deployed! It's live."), ([], "Told.")))
        assert not [p for p in model["prompts"] if p.startswith("A step of a plan")], "nothing to judge from"
        assert "      not checked: no tool ran, so there was nothing to check" in lines
        assert reply == "Done, all 2 steps; steps 1, 2 couldn't be checked. Told."

    def test_a_failed_check_gets_one_more_try_then_stops(self, model, workspace):
        model["plan"] = plan({"do": "Run the tests", "check": "all pass"}, {"do": "Open the report"})
        model["checks"] = [{"verified": False, "evidence": "2 failed"}, {"verified": False, "evidence": "1 failed"}]
        brain = Scripted(([("list_dir", {"path": "."})], "Ran."), ([("list_dir", {"path": "."})], "Ran again."))
        reply, outcome, _ = run("run the tests and then open the report", brain)
        assert len(brain.asked) == 2 and outcome["error"] == "Step 1 of 2: 1 failed"
        assert reply.startswith("I got to step 1 of 2 and stopped: 1 failed")

    def test_a_retry_that_works_carries_on(self, model, workspace):
        model["plan"] = plan({"do": "Write a.txt", "files": ["a.txt"]}, {"do": "Write b.txt", "files": ["b.txt"]})
        brain = Scripted(([], "Hmm."), ([("write_file", {"path": "a.txt", "content": "x"})], "Wrote it this time."),
                         ([("write_file", {"path": "b.txt", "content": "y"})], "Wrote b."))
        reply, outcome, _ = run("write a and then b", brain)
        assert outcome["status"] == "done" and reply == "Done, all 2 steps, each checked. Wrote b."

    @pytest.mark.parametrize("answer", [RuntimeError("rate limited"), "not json", {"verified": "yes"}])
    def test_a_check_that_cant_run_is_not_a_pass(self, model, workspace, answer):
        model["plan"] = plan({"do": "List files", "check": "readme is there"}, {"do": "Two"})
        model["checks"] = [answer]
        reply, outcome, lines = run("list files and then two", Scripted(([("list_dir", {"path": "."})], "Listed.")))
        assert outcome["status"] == "done" and reply == "Done, all 2 steps; steps 1, 2 couldn't be checked. Done."

    def test_a_file_outside_the_workspace_is_never_found(self, model, workspace):
        model["plan"] = plan({"do": "Write it", "files": ["../../etc/passwd"]}, {"do": "Two"})
        _, outcome, _ = run("write it and then two", Scripted(([], "ok"), ([], "ok")))
        assert outcome["error"] == "Step 1 of 2: ../../etc/passwd (outside the workspace) isn't there."


# ================================================================ recover

class TestRecovering:
    def test_your_no_ends_the_plan_without_a_retry(self, model, workspace):
        model["plan"] = plan({"do": "Delete the old build", "files": []}, {"do": "Rebuild"})
        tools.set_confirm(lambda _ask: False)
        (workspace / "old").mkdir()
        tasks.start("clean and then rebuild")
        try:
            brain = Scripted(([("delete_path", {"path": "old"})], "You said no."))
            reply, outcome, _ = run("clean the old build and then rebuild", brain)
        finally:
            tasks.finish(tasks.DONE)
        assert outcome["status"] == "stopped" and len(brain.asked) == 1
        assert reply == "You said no during step 1 of 2, so I stopped there. Nothing after it ran."
        assert (workspace / "old").exists()

    def test_a_stop_between_tries_is_honoured(self, model, workspace):
        model["plan"] = plan({"do": "Write a.txt", "files": ["a.txt"]}, {"do": "Two"})

        class StopsAfter(Scripted):
            def ask(self, text):
                planner.cancel()
                return super().ask(text)
        brain = StopsAfter(([], "hmm"))
        reply, outcome, _ = run("write a and then two", brain)
        assert outcome["status"] == "stopped" and len(brain.asked) == 1

    def test_a_no_on_another_thread_isnt_this_plans(self, model, workspace):
        import threading
        model["plan"] = plan({"do": "Write a.txt", "files": ["a.txt"]}, {"do": "Write b.txt", "files": ["b.txt"]})
        tools.set_confirm(lambda _ask: False)

        class Busy(Scripted):
            def ask(self, text):
                elsewhere = threading.Thread(target=lambda: tools.confirm("Something else?"))
                elsewhere.start()
                elsewhere.join()
                return super().ask(text)
        brain = Busy(([("write_file", {"path": "a.txt", "content": "x"})], "a"),
                     ([("write_file", {"path": "b.txt", "content": "y"})], "b"))
        try:
            _, outcome, _ = run("write a and then b", brain)
        finally:
            tools.set_confirm(lambda _m: False)
        assert outcome["status"] == "done"

    def test_one_more_try_at_most(self, model, workspace):
        model["plan"] = plan({"do": "Write a.txt", "files": ["a.txt"]}, {"do": "Two"})
        brain = Scripted(([], "no"), ([], "no"), ([], "no"))
        run("write a and then two", brain)
        assert len(brain.asked) == 1 + planner.RECOVERIES


# ================================================================= github

def _project(workspace, *, readme=True, gitignore=".env\nnode_modules/\n", env=True, git=False, key=False):
    root = workspace / "app"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hi')\n" + ("KEY = 'AIzaSyA1234567890abcdefghijklmn'\n" if key else ""),
                                          encoding="utf-8")
    if readme:
        (root / "README.md").write_text("# App\n", encoding="utf-8")
    if gitignore is not None:
        (root / ".gitignore").write_text(gitignore, encoding="utf-8")
    if env:
        (root / ".env").write_text("GEMINI_API_KEY=x\n", encoding="utf-8")
        (root / ".env.example").write_text("GEMINI_API_KEY=\n", encoding="utf-8")
    (root / "node_modules" / "lib").mkdir(parents=True)
    (root / "node_modules" / "lib" / "index.js").write_text("x", encoding="utf-8")
    if git:
        (root / ".git").mkdir()
    return root


class TestTheReadinessCheck:
    def test_a_ready_project(self, workspace):
        _project(workspace, git=True)
        found = project_check.check("app")
        assert found["ready"] and found["files"] == 4          # README, .gitignore, .env.example, src/main.py
        assert project_check.check_github_ready("app").startswith("app looks ready for GitHub (4 files would be committed).")

    def test_each_thing_that_isnt(self, workspace):
        _project(workspace, readme=False, gitignore=None, key=True)
        said = project_check.check_github_ready("app")
        assert said.startswith("app: 6 things to sort before GitHub.")
        assert "✗ README: No README at the top." in said
        assert "✗ .gitignore: None — secrets and bulky folders would be committed." in said
        assert "✗ Secret files kept out: .env would be committed" in said
        assert "✗ No keys in the code: something shaped like a key in src/main.py" in said
        assert "✗ Bulky folders kept out: node_modules would be committed" in said
        assert "✓ No file over 50 MB: none" in said and "✗ git set up: not yet — git init" in said

    def test_a_big_file(self, workspace, monkeypatch):
        root = _project(workspace, git=True)
        (root / "data.bin").write_bytes(b"x" * 2048)
        monkeypatch.setattr(project_check, "TOO_BIG", 1024)
        assert "✗ No file over 50 MB: data.bin (0 MB)" in project_check.check_github_ready("app")

    def test_gitignore_forms(self):
        ignored = project_check._ignored
        assert ignored([".env"], ".env") and ignored(["node_modules/"], "node_modules/lib/index.js")
        assert ignored(["*.log"], "logs/app.log") and ignored(["/dist"], "dist/x.js")
        assert not ignored(["/dist"], "src/dist/x.js") and not ignored(["# .env"], ".env")
        assert not ignored([".env*", "!.env.example"], ".env.example") and ignored([".env*", "!.env.example"], ".env.local")
        assert ignored(["!.env", ".env"], ".env"), "the last pattern that matches decides"

    def test_reads_only_and_only_the_workspace(self, workspace, tmp_path):
        root = _project(workspace)
        before = {p: p.stat().st_mtime_ns for p in root.rglob("*")}
        project_check.check_github_ready("app")
        assert {p: p.stat().st_mtime_ns for p in root.rglob("*")} == before
        assert "outside the workspace" in project_check.check_github_ready(str(tmp_path))
        assert project_check.check_github_ready("nope").startswith("Not a folder:")


class TestPrepareMyProjectForGitHub:
    def test_it_is_planned(self):
        assert planner.should_plan("Prepare my project for GitHub")
        assert planner.should_plan("get my code ready for github please")

    GITHUB_PLAN = plan(
        {"do": "Check where the project stands", "check": "the checklist is shown"},
        {"do": "Write a README", "files": ["app/README.md"]},
        {"do": "Write a .gitignore that keeps .env and node_modules out", "files": ["app/.gitignore"]},
        {"do": "Check it again", "check": "the checklist says it looks ready"},
        goal="Get the app folder ready for GitHub")

    def _brain(self):
        return Scripted(
            ([("check_github_ready", {"path": "app"})], "Three things to sort."),
            ([("write_file", {"path": "app/README.md", "content": "# App\n\nRun: python src/main.py\n"})], "README written."),
            ([("write_file", {"path": "app/.gitignore", "content": ".env\nnode_modules/\n"})], ".gitignore written."),
            ([("check_github_ready", {"path": "app"})], "It looks ready."))

    def test_done_only_when_the_checklist_says_so(self, model, workspace):
        _project(workspace, readme=False, gitignore=None, git=True)
        model["plan"] = self.GITHUB_PLAN
        model["checks"] = [{"verified": True, "evidence": "checklist shown"},
                           {"verified": True, "evidence": "looks ready for GitHub"}]
        reply, outcome, _ = run("prepare my project for GitHub", self._brain())
        assert outcome["status"] == "done"
        assert reply == "Done, all 4 steps, each checked. It looks ready."

    def test_the_final_checklist_is_littles_not_the_models(self, model, workspace):
        # git was never set up; the model says it's ready anyway.
        _project(workspace, readme=False, gitignore=None, git=False)
        model["plan"] = self.GITHUB_PLAN
        model["checks"] = [{"verified": True, "evidence": "checklist shown"},
                           {"verified": True, "evidence": "looks ready"}]
        reply, outcome, _ = run("prepare my project for GitHub", self._brain())
        assert outcome["status"] == "failed"
        assert reply == ("I did all 4 steps, but it isn't ready yet. "
                         "The final check found git set up (not yet — git init).")

    def test_nothing_is_pushed_without_asking(self, model, workspace):
        _project(workspace, git=True)
        model["plan"] = plan({"do": "Push to GitHub"}, {"do": "Tell me"})
        asked = []
        tools.set_confirm(lambda ask: asked.append(ask) or False)
        tasks.start("prepare my project for github")
        try:
            brain = Scripted(([("run_command", {"command": "git push origin main"})], "You declined."))
            reply, outcome, _ = run("prepare my project for github and push it", brain)
        finally:
            tasks.finish(tasks.DONE)
            tools.set_confirm(lambda _m: False)
        assert asked and outcome["status"] == "stopped" and "You said no during step 1" in reply

    def test_the_tool(self):
        described = {t["name"]: t["description"] for t in registry.TOOL_SCHEMAS}
        assert registry.FUNCTIONS["check_github_ready"] is project_check.check_github_ready
        assert "Reads only." in described["check_github_ready"]


# ============================================ answers the plan can see

class TestAnswersAreRecorded:
    def test_what_was_asked_and_the_answer_not_the_details(self):
        from jarvis.tools.permissions import Ask, answers, last_answer
        mark = last_answer()
        tools.set_confirm(lambda _ask: True)
        tools.confirm(Ask("Send it?", action="Send a WhatsApp message", details="the secret message text",
                          tool="send_whatsapp_message"))
        tools.set_confirm(lambda _ask: None)
        tools.confirm("Run this command?\n\ngit push --token=abc")
        (yes, no) = answers(since=mark)
        assert (yes["tool"], yes["action"], yes["approved"]) == ("send_whatsapp_message", "Send a WhatsApp message", True)
        assert (no["action"], no["approved"]) == ("Run this command?", False), "no answer is a no; the command isn't kept"
        assert "secret message" not in str(answers()) and "token" not in str(answers())
        tools.set_confirm(lambda _m: False)

    def test_installing_again_records_once(self):
        from jarvis.tools import permissions
        tools.set_confirm(lambda _ask: False)
        permissions.set_confirm(permissions.confirm_fn)
        mark = permissions.last_answer()
        tools.confirm("x?")
        assert len(permissions.answers(since=mark)) == 1

    def test_only_this_threads_answers(self):
        import threading
        from jarvis.tools import permissions
        tools.set_confirm(lambda _ask: False)
        mark = permissions.last_answer()
        worker = threading.Thread(target=lambda: tools.confirm("elsewhere?"))
        worker.start()
        worker.join()
        assert permissions.answers(since=mark, this_thread=True) == []
        assert len(permissions.answers(since=mark)) == 1
