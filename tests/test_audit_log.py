"""Chapter 41 — the audit log: what LITTLE did, kept without what it shouldn't.

Each task and each tool run is a line: when, the intent, the tool, its
arguments as its policy allows, a summary of the result or only its
length, how long, whether it worked, any question and your answer, any
error. Keys, passwords and tokens never land in it — or in the log file —
nor do messages, what you asked to be remembered, or your resume. "Show me
what you did for my last task" reads it back.
"""
from __future__ import annotations

import json

import pytest

from jarvis import tools
from jarvis.app import assistant, audit, config, tasks
from jarvis.jobs import resume
from jarvis.routing.router import fast_route
from jarvis.tools import registry
from jarvis.tools.registry import FUNCTIONS

KEY = "AIzaSyA1234567890abcdefghijklmn"


def lines():
    return [json.loads(line) for line in audit.PATH.read_text(encoding="utf-8").splitlines()]


def everything() -> str:
    return audit.PATH.read_text(encoding="utf-8") if audit.PATH.exists() else ""


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
    made = assistant.Jarvis(log_fn=lambda _l: None)
    made.muted = True
    return made


class Tooling:
    """A brain that runs the tools it's given, through the real registry."""

    def __init__(self, *calls, reply="Done."):
        self.calls, self.reply = calls, reply

    def ask(self, text, on_action=None):
        for name, args in self.calls:
            registry.execute_tool(name, args)
        return self.reply


# =============================================================== the lines

class TestWhatIsRecorded:
    def test_a_task_and_its_tools(self, bot, workspace):
        bot.brain = Tooling(("create_folder", {"path": "notes"}), ("list_dir", {"path": "."}))
        bot.handle("make a notes folder")
        folder, listing, task = lines()
        assert (folder["kind"], folder["tool"], folder["args"], folder["ok"]) == \
            ("tool", "create_folder", {"path": "notes"}, True)
        assert folder["result"].startswith("Folder ready: ") and folder["ms"] >= 0 and folder["error"] == ""
        assert listing["result"].endswith("characters, not logged]"), "a listing of your files is only measured"
        assert (task["kind"], task["intent"], task["path"], task["status"], task["ok"]) == \
            ("task", "make a notes folder", "ai", "done", True)
        assert folder["task"] == task["task"] and folder["session"] == task["session"] == audit.SESSION

    def test_a_question_and_your_answer(self, workspace):
        (workspace / "old.txt").write_text("x")
        tools.set_confirm(lambda _ask: False)
        try:
            registry.execute_tool("delete_path", {"path": "old.txt"})
        finally:
            tools.set_confirm(lambda _m: False)
        (entry,) = lines()
        assert entry["confirmation"] == [{"action": entry["confirmation"][0]["action"], "answer": "no"}]
        assert entry["confirmation"][0]["action"]

    def test_failures(self, monkeypatch):
        monkeypatch.setitem(FUNCTIONS, "list_dir", lambda **_k: 1 / 0)
        registry.execute_tool("list_dir", {})
        registry.execute_tool("no_such_tool", {})
        monkeypatch.setenv("JARVIS_BLOCKED_TOOLS", "open_url")
        registry.execute_tool("open_url", {"url": "https://example.com"})
        crashed, unknown, blocked = lines()
        assert (crashed["ok"], crashed["error"], crashed["result"]) == (False, "ZeroDivisionError: division by zero", "")
        assert (unknown["error"], blocked["error"]) == ("no such tool", "blocked")

    def test_a_task_that_failed(self, bot):
        class Broken:
            def ask(self, *_a, **_k):
                raise RuntimeError("I can't reach the internet right now.")
        bot.brain = Broken()
        bot.handle("tell me a story")
        (task,) = lines()
        assert (task["status"], task["ok"], task["error"]) == ("failed", False, "I can't reach the internet right now.")


# ============================================================ never in it

class TestNeverInIt:
    def test_keys_and_passwords_anywhere(self, bot, workspace):
        bot.brain = Tooling(("create_folder", {"path": f"what is {KEY}"}),
                            ("run_command", {"command": "login --password hunter2", "api_key": "sk-xyz"}))
        tools.set_confirm(lambda _a: False)
        try:
            bot.handle(f"search for my password is hunter2 and {KEY}")
        finally:
            tools.set_confirm(lambda _m: False)
        kept = everything()
        for secret in (KEY, "hunter2", "sk-xyz"):
            assert secret not in kept
        assert "[hidden]" in kept

    def test_a_result_that_carries_a_key(self, monkeypatch):
        monkeypatch.setitem(FUNCTIONS, "get_datetime", lambda **_k: f"It's noon. Key {KEY}.")
        registry.execute_tool("get_datetime", {})
        (entry,) = lines()
        assert KEY not in entry["result"] and entry["result"].startswith("It's noon. Key [hidden]")

    def test_a_messages_words(self, refuse):
        registry.execute_tool("send_whatsapp_message", {"name": "rahul", "message": "the private words"})
        (entry,) = lines()
        assert entry["args"] == {"name": "[not logged]", "message": "[not logged]"}
        assert "private words" not in everything()

    def test_what_you_asked_to_be_remembered(self):
        registry.execute_tool("remember", {"key": "locker code", "value": "4471-blue"})
        registry.execute_tool("recall", {})
        assert "4471-blue" not in everything()

    def test_your_resume(self):
        resume.save_profile({"candidate": {
            "name": "Asha Verma", "email": "asha@example.com", "phone": "1", "location": "Pune", "degree": "B.Tech",
            "graduation_year": "2026", "education": [], "skills": ["Rust"], "languages": [], "frameworks": [],
            "projects": ["Secret Thesis Project"], "experience": [], "internships": [], "certifications": []},
            "preferences": {"roles": []}})
        registry.execute_tool("show_resume_profile", {})
        (entry,) = lines()
        assert entry["result"].endswith("characters, not logged]")
        assert "Asha" not in everything() and "Secret Thesis" not in everything()

    def test_long_values_are_cut(self, workspace):
        registry.execute_tool("create_folder", {"path": "x" * 300})
        (entry,) = lines()
        assert len(entry["args"]["path"]) <= audit.ARG_CHARS + 1 and len(entry["result"]) <= audit.RESULT_CHARS + 1

    @pytest.mark.parametrize("name,hidden", [("password", True), ("api_key", True), ("auth_token", True),
                                             ("pin", True), ("key", False), ("path", False), ("pinned", False)])
    def test_argument_names(self, name, hidden):
        assert (audit.sanitize_args("open_url", {name: "value123"})[name] == "[hidden]") is hidden

    def test_the_log_file_too(self):
        config.log(f"calling with key {KEY} and my password is hunter2")
        written = config.LOG_FILE.read_text(encoding="utf-8")
        assert KEY not in written and "hunter2" not in written and "[hidden]" in written


# ======================================================= reading it back

class TestShowMeWhatYouDid:
    def test_the_last_task(self, bot, workspace):
        bot.brain = Tooling(("create_folder", {"path": "notes"}), ("write_file", {"path": "notes/a.txt", "content": "hi"}))
        bot.handle("make notes and write a file")
        bot.handle("show me what you did for my last task")
        said = tasks.recent(1)[0]["reply"]
        first, one, two = said.split("\n")
        assert first.startswith("Your last task: “make notes and write a file” — done in ") and first.endswith("with the model.")
        assert one.startswith("1. create_folder(path=notes) — worked, ") and ". Folder ready: " in one
        assert two.startswith("2. write_file(path=[not logged], content=[not logged]) — worked, ")
        assert tasks.recent(1)[0]["path"] == "fast"

    def test_a_question_asked_and_a_failure(self, bot, workspace):
        (workspace / "old.txt").write_text("x")
        bot.brain = Tooling(("delete_path", {"path": "old.txt"}), ("no_such_tool", {}), reply="Couldn't.")
        tools.set_confirm(lambda _a: False)
        try:
            bot.handle("tidy up")
        finally:
            tools.set_confirm(lambda _m: False)
        said = fast_route("what did you do for my last task?")
        assert "asked “" in said and "you said no" in said
        assert "2. no_such_tool() — failed: no such tool" in said

    def test_only_this_runs_steps(self, bot, workspace):
        bot.brain = Tooling(("create_folder", {"path": "notes"}))
        bot.handle("make notes")
        task = lines()[-1]
        with audit.PATH.open("a", encoding="utf-8") as handle:     # a step from an earlier run, same task number
            handle.write(json.dumps({"kind": "tool", "session": "older", "task": task["task"], "tool": "delete_path",
                                     "args": {}, "ok": True, "ms": 1, "result": ""}) + "\n")
        assert "delete_path" not in fast_route("what did you do for my last task")

    def test_a_task_with_no_tools(self, bot):
        bot.handle("what's the time")
        assert fast_route("what did you just do").endswith("No tools ran for it.")

    def test_nothing_yet(self):
        assert fast_route("show me what you did for my last task") == \
            "I haven't finished a task yet, so there's nothing to show."

    def test_the_audit_log(self, bot):
        assert fast_route("show the audit log") == "The audit log is empty."
        bot.handle("what's the time")
        bot.handle("what's the date")
        first, second = fast_route("audit log").split("\n")
        assert first.endswith("done: “what's the date” (" + first.split("(")[-1]) and "what's the time" in second

    def test_a_broken_line_is_skipped(self, bot):
        bot.handle("what's the time")
        with audit.PATH.open("a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        assert len(audit.entries()) == 1


class TestKeptBounded:
    def test_the_older_half_goes(self, monkeypatch):
        monkeypatch.setattr(audit, "MAX_BYTES", 2000)
        for i in range(60):
            registry.execute_tool("get_datetime", {})
        assert audit.PATH.stat().st_size <= 2000 + 400
        assert 0 < len(lines()) < 60
