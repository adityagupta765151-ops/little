"""Chapter 38 — the tool registry, in full.

Every tool has a name, a description, its parameters, a permission level,
a timeout, a handler, what it uses and a logging policy — built from what's
registered, so it can't drift. A message's text or a contact's number never
reaches the activity log. A tool that only reads is stopped waiting for
after its timeout; one that changes things is recorded as slow instead.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from jarvis.app import assistant, bridge, tasks
from jarvis.routing.router import fast_route
from jarvis.tools import catalog, permissions, registry
from jarvis.tools.registry import FUNCTIONS, TOOL_SCHEMAS


class TestEveryToolInFull:
    def test_every_field_for_every_tool(self):
        found = catalog.tools()
        assert sorted(t.name for t in found) == sorted(FUNCTIONS) == sorted(s["name"] for s in TOOL_SCHEMAS)
        for t in found:
            assert t.description and t.handler is FUNCTIONS[t.name] and t.group != "Other"
            assert t.permission in permissions.ORDER and t.timeout > 0 and t.log in ("args", "names", "none")
            assert set(t.required) <= set(t.params), t.name

    def test_its_the_registrys_own_data(self):
        t = catalog.get("delete_path")
        assert t.params == {"path": {"type": "string"}} and t.required == ["path"]
        assert t.permission == "HIGH_RISK" and t.uses == ["files"] and t.timeout == 30
        assert catalog.get("nope") is None

    def test_uses_name_only_real_tools(self):
        assert set(catalog.USES) <= set(FUNCTIONS)
        assert set(catalog.LOG_POLICY) <= set(FUNCTIONS) and set(catalog.TIMEOUTS) <= set(FUNCTIONS)

    def test_timeouts_by_what_a_tool_reaches(self):
        assert catalog.timeout_for("find_jobs") == 180
        assert catalog.timeout_for("read_page") == 90, "my browser"
        assert catalog.timeout_for("list_dir") == 30

    def test_the_tools_section_gets_it(self, monkeypatch):
        class Quiet:
            muted, running, brain = True, False, None
        monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
        out = bridge.Api(assistant=Quiet()).tools()["tools"]
        item = next(t for t in out if t["name"] == "send_whatsapp_message")
        assert item["level"] == "HIGH_RISK" and item["asks"] and item["log"] == "names"
        assert "messages" in item["uses"] and "handler" not in item
        json.dumps(out)


# ============================================================ the questions

class TestAskingAboutThem:
    def test_what_tools_do_you_have(self):
        said = fast_route("what tools do you have?")
        asking = len(permissions.NEEDS_CONFIRMATION)
        assert said.startswith(f"{len(FUNCTIONS)} tools in ") and f"{asking} of them ask you first." in said
        assert fast_route("list your tools") == said and fast_route("how many tools do you have") == said

    def test_which_use_the_browser(self):
        said = fast_route("which tools use the browser?")
        assert said.startswith("In my own browser (") and "In your normal browser (4): open_job_board, " in said
        for name in ("browser_task", "click_text", "wa_send_web", "prepare_application"):
            assert name in said.split("In your normal browser")[0]
        assert "run_command" not in said

    @pytest.mark.parametrize("what,expect", [("the internet", "find_jobs"), ("the model", "describe_screen"),
                                              ("files", "write_file"), ("whatsapp", "send_whatsapp_message"),
                                              ("the screen", "take_screenshot"), ("this computer", "run_command")])
    def test_which_use_other_things(self, what, expect):
        said = fast_route(f"which tools use {what}")
        assert expect in said and said.split(":")[0].endswith(("the internet", "the model", "files", "messages",
                                                               "the screen", "this computer"))

    def test_something_they_dont_use(self):
        assert fast_route("which tools use bananas").startswith("I can say which tools use the browser")

    def test_which_require_confirmation(self):
        said = fast_route("which tools require confirmation?")
        assert said.startswith("Every time (4): delete_path, run_command, send_whatsapp_message, wa_send_web.")
        assert "(6): browser_task, click_on_screen, click_text, code_change, press_key, undo_code_change." in said
        assert fast_route("which tools ask first") == said

    def test_blocked_ones_are_named(self, monkeypatch):
        monkeypatch.setenv("JARVIS_BLOCKED_TOOLS", "open_url")
        assert fast_route("which tools need your permission").endswith("Blocked, never run: open_url.")


# ============================================================== logging

class TestLoggingPolicy:
    def test_a_messages_words_are_never_shown(self, refuse):
        task = tasks.start("send it")
        registry.execute_tool("send_whatsapp_message", {"name": "rahul", "message": "my secret plan"})
        tasks.finish(tasks.DONE, task_id=task)
        (step, *_) = tasks.get(task)["steps"]
        assert step["detail"] == "(name, message)"

    def test_ordinary_arguments_are_shown_cut_and_redacted(self):
        assert tasks.preview({"path": "a.txt"}) == '{"path": "a.txt"}'
        shown = tasks.preview({"query": "key AIzaSyA1234567890abcdefghijklmn please"})
        assert "AIzaSy" not in shown and "[hidden]" in shown
        assert tasks.preview({"x": 1}, "none") == ""

    def test_the_activity_log_follows_it(self, monkeypatch):
        lines = []
        monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
        bot = assistant.Jarvis(log_fn=lines.append)
        bot._show_action("draft_whatsapp_message", {"name": "rahul", "message": "the private words"})
        bot._show_action("list_dir", {"path": "projects"})
        assert lines == ["   > draft_whatsapp_message (name, message)", '   > list_dir {"path": "projects"}']


# ============================================================= timeouts

class TestTimeouts:
    def test_a_read_only_tool_is_stopped_waiting_for(self, monkeypatch):
        release = threading.Event()
        monkeypatch.setitem(FUNCTIONS, "list_dir", lambda **_k: release.wait(5) and "late")
        monkeypatch.setitem(catalog.TIMEOUTS, "list_dir", 0.2)
        started = time.monotonic()
        said = registry.execute_tool("list_dir", {"path": "."})
        release.set()
        assert time.monotonic() - started < 2
        assert said == "list_dir took longer than 0.2 seconds, so I stopped waiting. It only reads, so nothing was changed."
        assert permissions.events()[0]["kind"] == "failed"

    def test_it_still_reports_to_its_task(self, monkeypatch):
        seen = {}
        monkeypatch.setitem(FUNCTIONS, "list_dir", lambda **_k: seen.setdefault("task", tasks.current_id()) and "ok")
        task = tasks.start("look")
        registry.execute_tool("list_dir", {})
        tasks.finish(tasks.DONE, task_id=task)
        assert seen["task"] == task

    def test_its_errors_still_come_back_in_words(self, monkeypatch):
        monkeypatch.setitem(FUNCTIONS, "list_dir", lambda **_k: 1 / 0)
        assert registry.execute_tool("list_dir", {}) == "Error in list_dir: ZeroDivisionError: division by zero"

    def test_something_that_changes_things_is_never_abandoned(self, monkeypatch):
        monkeypatch.setitem(FUNCTIONS, "write_file", lambda **_k: time.sleep(0.4) or "Written.")
        monkeypatch.setitem(catalog.TIMEOUTS, "write_file", 0.1)
        assert registry.execute_tool("write_file", {"path": "a", "content": "b"}) == "Written."
        event = permissions.events()[0]
        assert (event["kind"], event["tool"]) == ("slow", "write_file") and "over its 0.1 s" in event["detail"]


import _ui  # noqa: E402


class TestTheToolsSection:
    @pytest.fixture(autouse=True)
    def browser_ok(self):
        if not _ui.available():
            pytest.skip("Playwright isn't installed")

    def test_each_tool_says_its_level_and_what_it_uses(self, monkeypatch):
        class Quiet:
            muted, running, brain = True, False, None
        monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
        snapshot = bridge.Api(assistant=Quiet()).tools()
        opening = {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}
        check = """() => Object.fromEntries([...document.querySelectorAll('#toolsList .tools-item')].map(i =>
                    [i.dataset.tool, [i.dataset.level, (i.querySelector('.tools-meta') || {}).textContent]]))"""
        result, errors = _ui.open_panel(lambda page: page.evaluate(check), route="tools",
                                        script=_ui.bridge(opening) + "window.__tools = %s;" % json.dumps(snapshot))
        if result is _ui.NO_BROWSER:
            pytest.skip("no browser to render the panel with")
        assert errors == [], errors
        assert result["send_whatsapp_message"] == ["HIGH_RISK", "Asks every time · uses messages · 30 s · its words aren't logged"]
        assert result["list_dir"] == ["SAFE", "Reads only · uses files · 30 s"]
