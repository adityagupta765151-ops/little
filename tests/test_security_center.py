"""Chapter 37 — the Security Center: levels, blocking, only a real yes, and
the ways round a question that used to exist.

Every tool has a level, and a new tool without one fails here. A blocked
tool never runs, whatever is said. A confirmation that returns anything
but True is a no. And the old browser tools no longer submit a form
without asking: not through a button called "Go", not by pressing Enter,
and they never type a password. Real headless browser for those.
"""
from __future__ import annotations

import json

import pytest

from jarvis import tools
from jarvis.app import bridge, security, settings
from jarvis.routing.router import fast_route
from jarvis.tools import browser, browser_agent, permissions, registry
from jarvis.tools.registry import FUNCTIONS, TOOL_SCHEMAS
from test_browser_agent import HITS, answers, at, site  # noqa: F401  (fixtures, and the site they serve)


# ================================================================== levels

class TestEveryToolHasALevel:
    def test_every_tool_and_only_real_ones(self):
        assert set(permissions.LEVELS) == set(FUNCTIONS) == {t["name"] for t in TOOL_SCHEMAS}
        assert set(permissions.LEVELS.values()) <= set(permissions.ORDER)

    def test_what_asks_is_what_is_confirm_or_high_risk(self):
        assert permissions.NEEDS_CONFIRMATION == {n for n, lv in permissions.LEVELS.items()
                                                   if lv in (permissions.CONFIRM, permissions.HIGH_RISK)}
        high = {n for n, lv in permissions.LEVELS.items() if lv == permissions.HIGH_RISK}
        assert high == {"delete_path", "run_command", "send_whatsapp_message", "wa_send_web"}

    def test_nothing_that_changes_things_is_called_safe(self):
        safe = [n for n, lv in permissions.LEVELS.items() if lv == permissions.SAFE]
        verbs = ("write", "edit", "delete", "move", "copy", "create", "send", "run", "click", "press", "fill",
                 "mark", "set", "add", "remove", "forget", "remember", "open", "import", "update", "shortlist")
        assert not [n for n in safe if n.startswith(verbs)]

    def test_an_unknown_tool_is_never_safe(self):
        assert permissions.level("mystery_tool") == permissions.HIGH_RISK


# ================================================================ blocking

class TestBlocked:
    def test_a_blocked_tool_never_runs_even_with_a_yes(self, monkeypatch, allow):
        monkeypatch.setenv("JARVIS_BLOCKED_TOOLS", "run_command, open_url")
        monkeypatch.setitem(FUNCTIONS, "run_command", lambda **_k: pytest.fail("it ran"))
        assert registry.execute_tool("run_command", {"command": "echo hi"}) == \
            "I won't run run_command: it's blocked in your settings (JARVIS_BLOCKED_TOOLS)."
        (event, *_) = permissions.events()
        assert (event["kind"], event["tool"]) == ("blocked", "run_command")
        assert security.snapshot()["blocked"] == ["open_url", "run_command"]
        assert permissions.level("open_url") == permissions.BLOCKED

    @pytest.mark.parametrize("name", ["make_payment", "solve_captcha", "enter_otp", "auto_apply_jobs",
                                      "get_password", "bypass_login", "submit_application"])
    def test_names_that_are_blocked_on_sight(self, name):
        assert permissions.BLOCKED_NAMES.search(name)

    @pytest.mark.parametrize("name", ["read_page", "list_dir", "search_web", "find_jobs"])
    def test_ordinary_names_are_not(self, name):
        assert not permissions.BLOCKED_NAMES.search(name)


# ============================================================ a real yes

class TestOnlyARealYes:
    @pytest.mark.parametrize("answer", ["yes", "no", 1, object(), None, [True]])
    def test_anything_but_true_is_a_no(self, answer):
        tools.set_confirm(lambda _ask: answer)
        try:
            assert tools.confirm("Delete it?") is False
        finally:
            tools.set_confirm(lambda _m: False)

    def test_a_truthy_no_no_longer_deletes(self, workspace):
        (workspace / "keep.txt").write_text("x")
        tools.set_confirm(lambda _ask: "no")
        try:
            registry.execute_tool("delete_path", {"path": "keep.txt"})
        finally:
            tools.set_confirm(lambda _m: False)
        assert (workspace / "keep.txt").exists()

    def test_an_extra_argument_cant_skip_the_question(self, workspace, refuse):
        (workspace / "keep.txt").write_text("x")
        reply = registry.execute_tool("delete_path", {"path": "keep.txt", "confirmed": True})
        assert reply.startswith("Wrong arguments for delete_path") and (workspace / "keep.txt").exists()
        assert permissions.events()[0]["kind"] == "failed"

    def test_arguments_that_arent_named_values(self, refuse):
        assert registry.execute_tool("delete_path", ["keep.txt"]) == "Wrong arguments for delete_path: expected named values."

    def test_outside_the_workspace_is_refused_asked_or_not(self, allow, tmp_path):
        outside = tmp_path / "precious.txt"
        outside.write_text("x")
        assert "outside the workspace" in registry.execute_tool("delete_path", {"path": str(outside)})
        assert outside.exists()


# ================================================= the old browser tools

class TestTheOldBrowserToolsAsk:
    def test_a_submit_button_with_plain_words_asks(self, at, answers):
        at("/home.html")
        said = browser.click_text("Go")
        assert said == "You declined, so I didn't click it."
        ask = answers["asks"][0]
        assert ask.parts()["tool"] == "click_text" and ask.parts()["consequence"] == "It submits a form."
        assert not any(path.startswith("/results.html") for _, path in HITS)

    def test_a_link_doesnt_ask(self, at, answers):
        at("/home.html")
        assert browser.click_text("About us").startswith("Clicked About us.")
        assert answers["asks"] == []

    def test_enter_on_a_form_asks(self, at, answers):
        at("/home.html")
        browser_agent.act({"do": "fill", "field": "Search", "value": "python"}, browser_agent.observe())
        assert browser.press_key("Enter") == "You said no, so I didn't press it."
        assert answers["asks"][0].parts()["action"] == "Press Enter on a web page"
        answers["answer"] = True
        assert browser.press_key("Enter").startswith("Pressed Enter. Now on: Results")

    def test_other_keys_and_pages_without_forms_dont(self, at, answers):
        at("/jobs.html")
        assert browser.press_key("Enter").startswith("Pressed Enter.")
        at("/home.html")
        assert browser.press_key("Tab").startswith("Pressed Tab.")
        assert answers["asks"] == []

    def test_a_password_is_never_typed(self, at, answers):
        at("/form.html")
        assert browser.fill_field("Password", "hunter2") == browser.SECRET_REFUSED
        assert browser.fill_field("pw", "hunter2") == browser.SECRET_REFUSED, "found by name, refused by its type"
        assert browser.fill_field("OTP", "123456") == browser.SECRET_REFUSED
        seen = browser_agent.observe()["forms"][0]["fields"]
        assert not next(f for f in seen if f["label"].startswith("Password"))["filled"]
        assert browser.fill_field("Full name", "Asha").startswith("Filled")

    def test_on_a_job_board_submit_and_enter_are_never_pressed(self, at, answers, monkeypatch):
        at("/home.html")
        monkeypatch.setattr(browser_agent, "_no_automation", lambda url: True)
        answers["answer"] = True
        assert browser.click_text("Go").startswith("That's a job board")
        assert browser.press_key("Enter").startswith("That's a job board")
        assert answers["asks"] == [] and not any(path.startswith("/results.html") for _, path in HITS)

    def test_with_no_page_open_nothing_starts(self, monkeypatch, answers):
        monkeypatch.setattr(browser._worker, "page", None)
        assert browser._probe(browser._PROBE_ENTER) is None


# ======================================================== the security center

class TestTheSecurityCenter:
    @pytest.fixture
    def api(self, monkeypatch):
        class Quiet:
            muted, running, brain = True, False, None
        monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
        original = permissions.confirm_fn
        made = bridge.Api(assistant=Quiet())
        yield made
        permissions.set_confirm(original)

    def test_the_snapshot(self, api, monkeypatch, workspace):
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTHE-REAL-KEY-000000000")
        monkeypatch.setenv("ADZUNA_APP_ID", "adz-id-4411")
        registry.execute_tool("read_file", {"path": "missing.txt"})
        out = api.system()
        sec = out["security"]
        assert json.dumps(out).count("AIzaSy") == 0 and "adz-id-4411" not in json.dumps(out)
        assert [k["state"] for k in sec["keys"]] == ["set", "set", "missing", "missing"]
        assert sum(sec["levels"].values()) == len(FUNCTIONS) and sec["levels"]["BLOCKED"] == 0
        assert {s["name"] for s in sec["services"]} >= {"Google Gemini", "Google speech", "Adzuna"}
        assert sec["events"][0]["tool"] == "read_file" and sec["events"][0]["kind"] == "failed"
        assert all(t["level"] in ("CONFIRM", "HIGH_RISK") for t in out["asks_first"])

    def test_answers_are_listed_without_what_was_asked_about(self, api):
        tools.set_confirm(lambda _a: False)
        tools.confirm(permissions.Ask("Send it?", action="Send a WhatsApp message", details="the private text",
                                      tool="send_whatsapp_message"))
        (latest, *_) = security.snapshot()["answers"]
        assert latest == {"at": latest["at"], "tool": "send_whatsapp_message", "action": "Send a WhatsApp message",
                          "approved": False}
        assert "private text" not in json.dumps(security.snapshot())

    def test_a_failure_detail_is_redacted(self):
        permissions.note_event("failed", "run_command", "error with key AIzaSyA1234567890abcdefghijklmn in it")
        assert "AIzaSy" not in permissions.events()[0]["detail"]

    def test_by_command(self, monkeypatch):
        monkeypatch.setenv("JARVIS_BLOCKED_TOOLS", "run_command")
        said = fast_route("security report")
        assert said.startswith("Tools by level: ") and "1 blocked" in said and "Blocked: run_command." in said
        assert "(values are never shown)" in said

    def test_the_settings_rows_say_each_level(self):
        assert {t["name"]: t["level"] for t in settings.asks_first()}["delete_path"] == "HIGH_RISK"


import _ui  # noqa: E402

SECURITY = """() => ({
  hidden: document.getElementById('sysGuard').hidden,
  levels: [...document.querySelectorAll('#sysLevels dd')].map(d => [d.dataset.level, d.textContent]),
  services: [...document.querySelectorAll('#sysServices li')].map(l => l.textContent),
  events: [...document.querySelectorAll('#sysEvents li')].map(l => l.textContent),
  badges: [...document.querySelectorAll('#sysAsks li')].map(l => [l.querySelector('code').textContent,
                                                                  (l.querySelector('.badge') || {}).textContent]),
  ran: window.__ran || 0, images: document.querySelectorAll('#sysGuard img').length,
})"""


class TestTheSecurityPanel:
    @pytest.fixture(autouse=True)
    def browser_ok(self):
        if not _ui.available():
            pytest.skip("Playwright isn't installed")

    def _render(self, snapshot):
        opening = {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}
        extra = "window.__system = %s;" % json.dumps(snapshot)
        result, errors = _ui.open_panel(lambda page: page.evaluate(SECURITY), script=_ui.bridge(opening) + extra,
                                        route="system")
        if result is _ui.NO_BROWSER:
            pytest.skip("no browser to render the panel with")
        assert errors == [], errors
        return result

    def _snapshot(self, security_part):
        return {"groups": [], "env": {"path": "D:/little/.env", "exists": True}, "mics": [],
                "asks_first": [{"name": "delete_path", "does": "Delete.", "level": "HIGH_RISK"},
                               {"name": "press_key", "does": "Press.", "level": "CONFIRM"}],
                "tools": 89, "audit": [], "muted": False, "listening": False, "security": security_part}

    def test_levels_services_and_failures(self):
        ATTACK = '<img src=x onerror="window.__ran=1">'
        seen = self._render(self._snapshot({
            "keys": [], "levels": {"SAFE": 33, "LOW_RISK": 47, "CONFIRM": 4, "HIGH_RISK": 4, "BLOCKED": 1},
            "blocked": ["run_command"], "answers": [],
            "services": [{"name": "Google Gemini", "for": "answers", "state": "key set"}],
            "events": [{"at": 1700000000, "kind": "blocked", "tool": "run_command", "detail": ATTACK}]}))
        assert not seen["hidden"]
        assert seen["levels"] == [["SAFE", "33 tools"], ["LOW_RISK", "47 tools"], ["CONFIRM", "4 tools"],
                                  ["HIGH_RISK", "4 tools"], ["BLOCKED", "run_command"]]
        assert seen["services"] == ["Google Gemini — answers: key set"]
        assert "run_command · blocked" in seen["events"][0] and ATTACK in seen["events"][0]
        assert seen["badges"] == [["delete_path", "Every time"], ["press_key", "When it matters"]]
        assert seen["ran"] == 0 and seen["images"] == 0

    def test_an_older_snapshot_shows_none_of_it(self):
        seen = self._render(self._snapshot(None))
        assert seen["hidden"] is True
