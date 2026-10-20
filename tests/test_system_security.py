"""System and security (UI-9).

Security: every tool that asks first now says what it will do — what, to
what, the details to read, and what can't be taken back — and the dialog
lays that out with Cancel, Review and Confirm. Confirm arms after a moment,
and when there's more than the preview shows, only after Review. Each of
the five confirming tools (and the two Jobs buttons) is driven through the
real bridge, and each real question is rendered.

System: every setting in effect with its .env key, keys only ever "set" or
"missing"; the health check probe by probe; testing the voice; the
microphones; recalibrating; what asks first; your answers this session;
the job activity trail.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from jarvis.app import bridge, config, health, settings, tasks
from jarvis.jobs import store
from jarvis.store import memory
from jarvis.tools import browser, files, permissions, system, whatsapp, whatsapp_web
from jarvis.tools.permissions import Ask

ATTACK = '<img src=x onerror="window.__ran=1">'


class Quiet:
    muted, running = False, False
    brain = None

    def __init__(self):
        self.said = []

    def handle(self, text): ...

    def say(self, text):
        self.said.append(text)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
    original = permissions.confirm_fn
    made = bridge.Api(assistant=Quiet())
    yield made
    permissions.set_confirm(original)


@pytest.fixture(autouse=True)
def fresh():
    tasks.reset()
    whatsapp._pending = whatsapp_web._pending = None
    yield
    tasks.reset()
    whatsapp._pending = whatsapp_web._pending = None


# ====================================================== the question itself

class TestAnAsk:
    def test_it_is_still_the_question_as_text(self):
        ask = Ask("Delete x? This can't be undone.", action="Delete a file", target="x",
                  details="x — a file", consequence="Gone for good.", tone="danger", verb="Delete",
                  tool="delete_path")
        assert ask == "Delete x? This can't be undone." and isinstance(ask, str)
        assert json.loads(json.dumps({"q": ask})) == {"q": "Delete x? This can't be undone."}
        assert ask.parts() == {"action": "Delete a file", "target": "x", "details": "x — a file",
                               "consequence": "Gone for good.", "tone": "danger", "verb": "Delete",
                               "tool": "delete_path"}

    def test_an_unknown_tone_is_caution(self):
        assert Ask("q", action="a", tone="fine").tone == "caution"


def _asked(run):
    """Run a tool with a confirm that records the question and says no."""
    seen = []
    original = permissions.confirm_fn
    permissions.set_confirm(lambda question: seen.append(question) or False)
    try:
        reply = run()
    finally:
        permissions.set_confirm(original)
    assert len(seen) == 1, f"asked {len(seen)} times"
    return seen[0], reply


class TestEachConfirmingToolSaysWhatItWillDo:
    def test_deleting_a_file(self, workspace):
        (workspace / "notes.txt").write_text("x" * 2048)
        ask, reply = _asked(lambda: files.delete_path("notes.txt"))
        target = workspace / "notes.txt"
        assert ask == f"Delete {target}? This can't be undone.", "the text is as it was"
        assert (ask.action, ask.target, ask.details) == ("Delete a file", str(target), "notes.txt — a file, 2 KB")
        assert (ask.tone, ask.verb, ask.tool) == ("danger", "Delete", "delete_path")
        assert "Recycle Bin" in ask.consequence
        assert reply == "You declined, so nothing was deleted." and target.exists()

    def test_deleting_a_folder_says_how_much_is_in_it(self, workspace):
        (workspace / "old").mkdir()
        for n in range(3):
            (workspace / "old" / f"{n}.log").write_text("x")
        ask, _ = _asked(lambda: files.delete_path("old"))
        assert ask.action == "Delete a folder and everything in it"
        assert ask.details == "old — a folder with 3 things inside"
        assert (workspace / "old").exists()

    def test_running_a_command(self, workspace):
        ask, reply = _asked(lambda: system.run_command("echo made > proof.txt"))
        assert ask == f"Run this command in {workspace}?\n\necho made > proof.txt"
        assert (ask.action, ask.details, ask.verb, ask.tone) == (
            "Run a command on your computer", "echo made > proof.txt", "Run", "danger")
        assert ask.target == f"in {workspace}"
        assert reply == "You declined, so the command didn't run."
        assert not (workspace / "proof.txt").exists()

    def test_sending_a_whatsapp_message_names_the_number_masked(self):
        memory.add_contact("rahul", "+919812345678")
        whatsapp._pending = {"name": "rahul", "message": "Running late, start without me."}
        ask, reply = _asked(whatsapp.send_whatsapp_message)
        assert ask == "Send this to rahul?\n\nRunning late, start without me."
        assert (ask.action, ask.target, ask.details) == (
            "Send a WhatsApp message", "to rahul (+91 ••••••5678)", "Running late, start without me.")
        assert (ask.verb, ask.tool) == ("Send", "send_whatsapp_message")
        assert "9812345678" not in json.dumps(ask.parts(), ensure_ascii=False)
        assert reply == "Cancelled. Nothing was sent."

    def test_sending_on_whatsapp_web(self):
        whatsapp_web._pending = {"name": "mom", "message": "Reached."}
        ask, reply = _asked(whatsapp_web.wa_send_web)
        assert ask == "Send this to mom on WhatsApp?\n\nReached."
        assert (ask.action, ask.target, ask.details, ask.tool) == (
            "Send a WhatsApp message", "to mom, in WhatsApp Web", "Reached.", "wa_send_web")
        assert reply == "Cancelled. Nothing was sent."

    def test_clicking_a_button_that_could_buy_something(self, monkeypatch):
        started = []
        monkeypatch.setattr(browser._worker, "run", lambda job: started.append(job) or "")
        ask, reply = _asked(lambda: browser.click_text("Pay now"))
        assert ask.startswith('Click "Pay now" on this page?')
        assert (ask.action, ask.target, ask.verb, ask.tool) == (
            "Click a button on a web page", "“Pay now”", "Click", "click_text")
        assert reply == "You declined, so I didn't click it."
        assert started == [], "the browser wasn't started just to ask"

    def test_the_page_address_is_named_when_a_page_is_open(self, monkeypatch):
        class Page:
            url = "https://shop.example.com/cart"

            def is_closed(self):
                return False
        monkeypatch.setattr(browser._worker, "page", Page())
        monkeypatch.setattr(browser._worker, "run", lambda job: job())
        ask, _ = _asked(lambda: browser.click_text("Place order"))
        assert ask.target == "“Place order” on shop.example.com"
        assert ask.details.endswith("Page: https://shop.example.com/cart")

    def test_the_list_of_tools_that_ask(self):
        # Chapter 37 added the three that already asked at their consequential
        # step (a submit in a browser task, a click from a screenshot, Enter
        # on a form) to the list, with every tool's level.
        # Chapter 44 added the coding agent's change and its undo, which ask too.
        assert permissions.NEEDS_CONFIRMATION == {
            "delete_path", "run_command", "send_whatsapp_message", "wa_send_web", "click_text",
            "browser_task", "click_on_screen", "press_key", "code_change", "undo_code_change"}


# ================================================ through the real bridge

def _real_question(api, run):
    """Install the bridge's own confirm, run the tool, read the question the
    page would get from poll(), answer no."""
    permissions.set_confirm(api.confirm)
    box = {}
    worker = threading.Thread(target=lambda: box.setdefault("reply", run()), daemon=True)
    worker.start()
    for _ in range(300):
        ask = api.poll().get("ask")
        if ask:
            api.confirm_reply(ask["id"], False)
            worker.join(3)
            return ask, box.get("reply")
        time.sleep(0.01)
    raise AssertionError("no question reached the page")


# The five whose questions these tests replay through the bridge; the three
# Chapter 37 added are replayed in test_security_center.py.
FIVE = ("click_text", "delete_path", "run_command", "send_whatsapp_message", "wa_send_web")


def _five(workspace):
    (workspace / "old.txt").write_text("x")
    memory.add_contact("rahul", "+919812345678")

    def send():
        whatsapp._pending = {"name": "rahul", "message": "On my way."}
        return whatsapp.send_whatsapp_message()

    def send_web():
        whatsapp_web._pending = {"name": "rahul", "message": "On my way."}
        return whatsapp_web.wa_send_web()

    return {
        "delete_path": lambda: files.delete_path("old.txt"),
        "run_command": lambda: system.run_command("echo hi"),
        "send_whatsapp_message": send,
        "wa_send_web": send_web,
        "click_text": lambda: browser.click_text("Delete account"),
    }


class TestThePageGetsTheWholeQuestion:
    @pytest.mark.parametrize("tool", FIVE)
    def test_each_tool_through_the_bridge(self, api, workspace, monkeypatch, tool):
        monkeypatch.setattr(browser._worker, "run", lambda job: "")
        ask, reply = _real_question(api, _five(workspace)[tool])
        assert ask["tool"] == tool
        assert ask["action"] and ask["target"] and ask["details"] and ask["consequence"] and ask["verb"]
        assert "?" in ask["message"], "the plain question still travels, for the Tk window"
        assert reply and ("declined" in reply or "Cancelled" in reply)

    def test_a_plain_question_stays_plain(self, api):
        ask, answer = _real_question(api, lambda: permissions.confirm("Go on?"))
        assert set(ask) == {"id", "message"} and ask["message"] == "Go on?" and answer is False

    def test_long_details_are_cut_for_the_trip_and_marked(self, api):
        ask, _ = _real_question(api, lambda: permissions.confirm(
            Ask("Run it?", action="Run", details="x" * 9000)))
        assert len(ask["details"]) == bridge.ASK_DETAILS_MAX + 1 and ask["details"].endswith("…")

    def test_waiting_shows_the_question_as_text(self, api):
        permissions.set_confirm(api.confirm)
        tid = []

        def run():
            tid.append(tasks.start("delete it"))
            return permissions.confirm(Ask("Delete it?", action="Delete a file"))
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        for _ in range(300):
            if tid and tasks.get(tid[0])["status"] == tasks.WAITING:
                break
            time.sleep(0.01)
        asking = tasks.get(tid[0])["asking"]
        assert asking == "Delete it?" and type(asking) is str, "Home shows it as it always did"
        ask = api.poll()["ask"]
        api.confirm_reply(ask["id"], False)
        worker.join(3)

    @pytest.mark.parametrize("action,verb,tone", [("prepare", "Open and fill", "safe"),
                                                  ("applied", "Record it", "caution")])
    def test_the_two_jobs_buttons(self, api, action, verb, tone):
        from jarvis.jobs import matching, resume
        resume.save_profile({"candidate": {"name": "A", "skills": ["React"]}, "preferences": {}})
        job = {"job_id": "j1", "company": "Acme", "title": "Dev", "location": "", "description": "React",
               "platform": "x", "url": "https://example.com"}
        store.upsert_job(matching.score_job(job, resume.load_profile()))
        permissions.set_confirm(api.confirm)
        assert api.job("j1", action) == ""
        for _ in range(300):
            ask = api.poll().get("ask")
            if ask:
                break
            time.sleep(0.01)
        api.confirm_reply(ask["id"], False)
        assert (ask["verb"], ask["tone"], ask["target"]) == (verb, tone, "“Dev” at Acme")


# ================================================================ settings

class TestTheSettings:
    def test_every_group_the_spec_names_is_there(self, api):
        out = api.system()
        assert [g["id"] for g in out["groups"]] == ["ai", "voice", "mic", "wake", "browser", "jobs", "files"]
        for group in out["groups"]:
            for row in group["rows"]:
                assert set(row) == {"label", "value", "key", "note"} and row["value"] != ""

    def test_values_are_the_ones_in_effect(self, api):
        rows = {(g["id"], r["label"]): r for g in api.system()["groups"] for r in g["rows"]}
        assert rows[("ai", "Model")]["value"] == config.MODEL
        assert rows[("ai", "Model")]["key"] == "GEMINI_MODEL"
        assert rows[("voice", "Voice")]["value"] == config.VOICE
        assert rows[("voice", "Pitch")]["value"] == config.VOICE_PITCH
        assert rows[("wake", "Answers to")]["value"] == ", ".join(config.WAKE_WORDS)
        assert rows[("files", "Workspace")]["value"] == str(config.WORKSPACE)
        assert rows[("files", "Memory folder")]["value"] == str(config.MEMORY_DIR)

    def test_no_key_ever_leaves_as_a_value(self, api, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy-THE-REAL-KEY")
        monkeypatch.setenv("ADZUNA_APP_ID", "adz-id-4411")
        monkeypatch.setenv("ADZUNA_APP_KEY", "adz-key-9922")
        monkeypatch.delenv("MUSE_API_KEY", raising=False)
        out = json.dumps(api.system())
        for secret in ("AIzaSy", "THE-REAL-KEY", "adz-id-4411", "adz-key-9922", "test-key-not-used"):
            assert secret not in out
        rows = {r["key"]: r["value"] for g in api.system()["groups"] for r in g["rows"] if r["key"]}
        assert [rows[k] for k in settings.SECRETS] == ["set", "set", "set", "missing"]

    def test_what_asks_first_is_the_real_list(self, api):
        names = [t["name"] for t in api.system()["asks_first"]]
        gated = len(permissions.NEEDS_CONFIRMATION)
        assert names[:gated] == sorted(permissions.NEEDS_CONFIRMATION)
        assert names[gated:] == ["Jobs: Prepare application…", "Jobs: I applied"]
        assert all(t["does"] for t in api.system()["asks_first"])

    def test_the_env_file_and_the_audit_trail(self, api):
        store.audit("open_posting", platform="adzuna", company="Acme", job="Dev", result="opened")
        out = api.system()
        assert out["env"]["path"] == str(config.BASE_DIR / ".env")
        assert out["audit"][0]["action"] == "open_posting" and out["audit"][0]["company"] == "Acme"

    def test_a_broken_read_is_an_answer(self, api, monkeypatch):
        monkeypatch.setattr(settings, "groups", lambda *_a: 1 / 0)
        assert api.system() == {"error": "I couldn't read the settings."}


class TestTheHealthCheck:
    def test_every_probe_with_what_to_do(self, api):
        checks = api.health()["checks"]
        assert [c["group"] for c in checks] == list(health.PROBES)
        for c in checks:
            assert c["state"] in (health.OK, health.WARN, health.FAIL)
            if c["state"] != health.OK:
                assert c["problem"] and c["cause"] and c["fix"], c["group"]

    def test_the_model_is_asked_only_when_you_say_so(self, api, monkeypatch):
        asked = []
        monkeypatch.setattr(health, "check_model_live", lambda: asked.append(1) or health.Check("ai"))
        api.health("yes")
        api.health(1)
        assert asked == []
        checks = api.health(True)["checks"]
        assert asked == [1] and checks[0]["group"] == "ai"


class TestTestingTheVoice:
    def test_it_says_a_sentence(self, api):
        assert api.test_voice() == ""
        for _ in range(100):
            if api.jarvis.said:
                break
            time.sleep(0.01)
        assert api.jarvis.said == [f"Hi, I'm {config.ASSISTANT_CALL}. This is how I sound."]

    def test_not_while_muted(self, api):
        api.jarvis.muted = True
        assert api.test_voice() == "Voice is muted. Unmute it to hear this."
        assert api.jarvis.said == []


# ============================================================ in a browser

import _ui  # noqa: E402


@pytest.fixture(scope="module")
def browser_ok():
    if not _ui.available():
        pytest.skip("Playwright isn't installed")


def _render(check, opening=None, extra="", route="home", **kw):
    opening = opening or {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}
    result, errors = _ui.open_panel(check, script=_ui.bridge(opening) + extra, route=route, **kw)
    if result is _ui.NO_BROWSER:
        pytest.skip("no browser to render the panel with")
    assert errors == [], errors
    return result


DIALOG = """() => {
  const text = (id) => document.getElementById(id).textContent;
  const shown = (id) => !document.getElementById(id).hidden;
  return {
    open: shown('veil'), kicker: text('askKicker'), title: text('askTitle'),
    target: shown('askTarget') ? text('askTarget') : null,
    preview: text('askText'), more: shown('askMore'),
    consequence: shown('askConsequence') ? text('askConsequence') : null,
    tone: document.getElementById('askConsequence').dataset.tone,
    review: shown('askReviewBtn'), reviewOpen: shown('askReview'),
    expanded: document.getElementById('askReviewBtn').getAttribute('aria-expanded'),
    full: text('askFull'), tool: text('askTool'),
    yes: text('askYes'), yesOff: document.getElementById('askYes').disabled,
    yesClass: document.getElementById('askYes').className,
    focus: document.activeElement && document.activeElement.id,
    calls: window.__calls, images: document.querySelectorAll('#veil img').length, ran: window.__ran || 0,
  };
}"""


def _with_ask(ask):
    return {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}, "ask": ask}


class TestTheDialog:
    @pytest.mark.parametrize("tool", FIVE)
    def test_each_tools_real_question_shows_what_will_happen(self, browser_ok, api, workspace,
                                                              monkeypatch, tool):
        monkeypatch.setattr(browser._worker, "run", lambda job: "")
        ask, _ = _real_question(api, _five(workspace)[tool])

        async def check(page):
            await page.wait_for_timeout(750)
            return await page.evaluate(DIALOG)

        seen = _render(check, _with_ask(ask))
        assert seen["open"] and seen["kicker"] == "Little wants to"
        assert seen["title"] == ask["action"] and seen["target"] == ask["target"]
        assert seen["preview"] == ask["details"] and seen["consequence"] == ask["consequence"]
        assert seen["tone"] == ask["tone"] and seen["yes"] == ask["verb"]
        assert seen["focus"] == "askNo", "it opens on Cancel"
        assert seen["review"] and not seen["reviewOpen"]
        assert seen["yesOff"] is False, "short details: armed after the moment"

    def test_review_shows_everything_and_the_tool(self, browser_ok):
        ask = {"id": 7, "message": "Run it?", "action": "Run a command on your computer",
               "target": "in D:/w", "details": "\n".join(f"step {n}" for n in range(12)),
               "consequence": "It runs as you.", "tone": "danger", "verb": "Run", "tool": "run_command"}

        async def check(page):
            await page.wait_for_timeout(750)
            before = await page.evaluate(DIALOG)
            await page.click("#askReviewBtn")
            opened = await page.evaluate(DIALOG)
            await page.click("#askYes")
            return before, opened, await page.evaluate(DIALOG)

        before, opened, done = _render(check, _with_ask(ask))
        assert before["preview"] == "\n".join(f"step {n}" for n in range(6)) and before["more"]
        assert before["yesOff"] is True, "more than fits: Review first"
        assert opened["reviewOpen"] and opened["expanded"] == "true"
        assert opened["full"] == ask["details"] and opened["tool"] == "Tool: run_command"
        assert opened["yesOff"] is False
        assert ["confirm_reply", 7, True] in done["calls"] and not done["open"]

    def test_the_moment_still_applies_after_review(self, browser_ok):
        ask = {"id": 7, "message": "x", "action": "Run", "details": "a\n" * 20, "tone": "danger", "verb": "Run"}

        async def check(page):
            await page.click("#askReviewBtn")
            return await page.evaluate(DIALOG)

        assert _render(check, _with_ask(ask), wait_ms=150)["yesOff"] is True, \
            "Review opened at once still waits out the moment"

    def test_a_plain_question_reads_as_before(self, browser_ok):
        async def check(page):
            await page.wait_for_timeout(750)
            return await page.evaluate(DIALOG)

        seen = _render(check, _with_ask({"id": 3, "message": "Go on?"}))
        assert seen["title"] == "Confirmation required" and seen["kicker"] == "Little needs your OK"
        assert seen["preview"] == "Go on?" and seen["target"] is None and seen["consequence"] is None
        assert not seen["review"] and seen["yes"] == "Yes, go ahead" and seen["yesOff"] is False

    def test_something_safe_is_not_dressed_as_danger(self, browser_ok):
        ask = {"id": 5, "message": "Open?", "action": "Open an application and fill it in",
               "details": "Your name.", "consequence": "Nothing is submitted.", "tone": "safe",
               "verb": "Open and fill"}
        seen = _render(lambda page: page.evaluate(DIALOG), _with_ask(ask))
        assert "btn--primary" in seen["yesClass"] and "btn--caution" not in seen["yesClass"]

    @pytest.mark.parametrize("key", ["Enter", "Escape"])
    def test_enter_or_escape_as_it_opens_cancels(self, browser_ok, key):
        ask = {"id": 9, "message": "Delete?", "action": "Delete a file", "details": "x", "tone": "danger",
               "verb": "Delete"}

        async def check(page):
            await page.keyboard.press(key)
            await page.wait_for_timeout(80)
            return await page.evaluate(DIALOG)

        seen = _render(check, _with_ask(ask))
        assert seen["calls"].count(["confirm_reply", 9, False]) == 1
        assert ["confirm_reply", 9, True] not in seen["calls"]

    def test_text_is_shown_as_text(self, browser_ok):
        ask = {"id": 4, "message": ATTACK, "action": ATTACK, "target": ATTACK, "details": ATTACK,
               "consequence": ATTACK, "tone": "danger", "verb": ATTACK, "tool": ATTACK}
        seen = _render(lambda page: page.evaluate(DIALOG), _with_ask(ask))
        assert seen["title"] == ATTACK and seen["images"] == 0 and seen["ran"] == 0
        assert not any(c[0] == "confirm_reply" for c in seen["calls"]), "nothing answered by itself"


SYSTEM = """() => {
  const text = (id) => document.getElementById(id).textContent;
  const q = (s) => [...document.querySelectorAll(s)];
  return {
    calls: window.__calls, env: text('sysEnv'),
    groups: q('#sysSettings > .panel').map(p => p.dataset.group),
    rows: Object.fromEntries(q('#sysSettings .sys-rows dt').map(dt => [dt.textContent,
      [dt.nextElementSibling.querySelector('.sys-value').textContent,
       (dt.nextElementSibling.querySelector('.sys-key') || {}).textContent || '']])),
    checks: q('#sysChecks .sys-check').map(c => [c.dataset.check, c.querySelector('.badge').textContent,
      c.querySelector('.sys-trouble') ? c.querySelector('.sys-trouble').textContent : '']),
    summary: text('sysHealthSummary'),
    asks: q('#sysAsks code').map(c => c.textContent),
    answers: q('#sysAnswers li').map(li => li.textContent),
    audit: q('#sysAudit li').map(li => li.textContent),
    mics: q('.sys-mics li').map(li => li.textContent),
    recalibrate: (document.querySelector('[data-key="recalibrate"]') || {}).disabled,
    outs: q('.sys-out').map(o => o.textContent),
    all: document.querySelector('[data-view="system"]').textContent,
    images: document.querySelectorAll('[data-view="system"] img').length, ran: window.__ran || 0,
  };
}"""


def _snap(api, **change):
    out = json.loads(json.dumps(api.system()))
    out.update(change)
    return out


def _sys(api, _unused=None, **change):
    extra = "window.__system = %s; window.__health = %s;" % (
        json.dumps(_snap(api, **change)), json.dumps(api.health()))
    return extra


class TestTheSystemSection:
    def test_every_setting_with_its_key(self, browser_ok, api):
        seen = _render(lambda page: page.evaluate(SYSTEM), extra=_sys(api, None), route="system")
        assert seen["groups"] == ["ai", "voice", "mic", "wake", "browser", "jobs", "files",
                                  "notifications", "appearance"]
        assert seen["rows"]["Model"] == [config.MODEL, "GEMINI_MODEL"]
        assert seen["rows"]["API key"] == ["set", "GEMINI_API_KEY"]
        assert seen["rows"]["Voice"] == [config.VOICE, "JARVIS_VOICE"]
        assert seen["rows"]["Theme"] == ["Dark — the only one", ""]
        assert "test-key-not-used" not in seen["all"]
        assert "restart Little" in seen["env"] or "no .env file" in seen["env"]

    def test_the_health_check_runs_once_and_shows_what_to_do(self, browser_ok, api):
        async def check(page):
            before = await page.evaluate(SYSTEM)
            await page.click("#sysHealthRun")
            await page.click("#sysHealthLive")
            await page.wait_for_timeout(100)
            return before, await page.evaluate(SYSTEM)

        before, after = _render(check, extra=_sys(api, None), route="system")
        real = api.health()["checks"]
        assert [c[0] for c in before["checks"]] == [c["group"] for c in real]
        for (group, badge, trouble), probe in zip(before["checks"], real):
            if probe["state"] == "ok":
                assert badge.endswith("ok") and trouble == ""
            else:
                assert probe["fix"] in trouble and probe["problem"] in trouble
        assert [c for c in after["calls"] if c[0] == "health"] == [["health", False], ["health", False],
                                                                     ["health", True]]

    def test_one_health_check_at_a_time(self, browser_ok, api):
        slow = """window.pywebview.api.health = async (live) => {
            window.__calls.push(["health", live]);
            await new Promise((r) => setTimeout(r, 500));
            return window.__health; };"""

        async def check(page):
            running = await page.evaluate("[document.getElementById('sysHealthRun').disabled,"
                                          " document.getElementById('sysHealthSummary').textContent]")
            await page.evaluate("document.getElementById('sysHealthRun').click();"
                                "document.getElementById('sysHealthLive').click()")
            await page.wait_for_timeout(700)
            return running, await page.evaluate(SYSTEM)

        running, seen = _render(check, extra=_sys(api, None) + slow, route="system", wait_ms=200)
        assert running == [True, "Checking…"]
        assert [c for c in seen["calls"] if c[0] == "health"] == [["health", False]], \
            "clicks while it's checking start nothing"

    def test_the_voice_can_be_tried(self, browser_ok, api):
        async def check(page):
            await page.click('[data-key="test-voice"]')
            await page.wait_for_timeout(80)
            return await page.evaluate(SYSTEM)

        seen = _render(check, extra=_sys(api, None) + "window.__answers = {test_voice: 'Voice is muted. Unmute it to hear this.'};",
                       route="system")
        assert ["test_voice"] in seen["calls"]
        assert "Voice is muted. Unmute it to hear this." in seen["outs"]

    def test_a_command_is_run_and_its_reply_shown_here(self, browser_ok, api):
        done = {"id": 12, "text": "what voice are you using", "source": "typed", "status": "done",
                "route": "local", "started": 1, "ms": 900, "steps": [], "reply": "Neerja, neural, +10Hz.",
                "error": "", "plan": None, "reset": False, "again_of": None, "stopping": False,
                "stop_at": None, "v": 4}

        other = {**done, "id": 13, "text": "what's the time", "reply": "It's 1 pm.", "v": 5}

        async def check(page):
            await page.click('[data-key="voice-report"]')
            await page.evaluate("window.__queue.push({status: 'listening', lines: [], tasks: %s})"
                                % json.dumps({"v": 5, "changed": [done, other]}))
            await page.wait_for_timeout(400)
            return await page.evaluate(SYSTEM)

        seen = _render(check, extra=_sys(api, None), route="system")
        assert ["send", "what voice are you using"] in seen["calls"]
        assert "Neerja, neural, +10Hz." in seen["outs"], "its own reply"
        assert not any("1 pm" in out for out in seen["outs"]), "not another command's, even a newer one"

    @pytest.mark.parametrize("listening", [False, True])
    def test_microphones_and_recalibrate(self, browser_ok, api, listening):
        async def check(page):
            before = await page.evaluate(SYSTEM)
            if listening:
                await page.click('[data-key="recalibrate"]')
                await page.wait_for_timeout(60)
            return before, await page.evaluate(SYSTEM)

        before, after = _render(check, extra=_sys(api, None, mics=["Mic A", "Headset B"], listening=listening),
                                route="system")
        assert before["mics"] == ["#0 Mic A", "#1 Headset B"]
        assert before["recalibrate"] is (not listening)
        assert (["send", "recalibrate mic"] in after["calls"]) is listening

    def test_your_answers_this_session(self, browser_ok, api):
        task = {"id": 3, "text": "send it", "source": "typed", "status": "done", "route": "model",
                "started": 1, "ms": 10, "reply": "Cancelled.", "error": "", "plan": None, "reset": False,
                "again_of": None, "stopping": False, "stop_at": None, "v": 2,
                "steps": [{"n": 0, "name": "your answer", "detail": "declined",
                           "question": "Send this to rahul?\n\nhi", "status": "done", "ms": None,
                           "at": 1, "part": None}]}
        opening = {"status": "listening", "lines": [], "tasks": {"v": 2, "changed": [task]}}
        seen = _render(lambda page: page.evaluate(SYSTEM), opening, _sys(api, None), route="system")
        assert seen["answers"] == ["You said noSend this to rahul?"]

    def test_the_job_activity_trail(self, browser_ok, api):
        store.audit("open_posting", platform="adzuna", company="Acme", job="Dev", result="opened")
        seen = _render(lambda page: page.evaluate(SYSTEM), extra=_sys(api, None), route="system")
        assert any("open_posting · Acme · Dev" in row and "opened" in row for row in seen["audit"])
        assert seen["asks"][:len(permissions.NEEDS_CONFIRMATION)] == sorted(permissions.NEEDS_CONFIRMATION)

    def test_text_is_shown_as_text(self, browser_ok, api):
        snap = _snap(api, mics=[ATTACK])
        snap["groups"][0]["rows"][0]["value"] = ATTACK
        extra = "window.__system = %s; window.__health = %s;" % (json.dumps(snap), json.dumps(
            {"checks": [{"group": ATTACK, "state": "fail", "detail": ATTACK, "problem": ATTACK,
                         "cause": ATTACK, "fix": ATTACK}]}))
        seen = _render(lambda page: page.evaluate(SYSTEM), extra=extra, route="system")
        assert seen["images"] == 0 and seen["ran"] == 0

    @pytest.mark.parametrize("size", [(1040, 660), (1280, 800), (700, 800)], ids=lambda s: f"{s[0]}x{s[1]}")
    def test_nothing_spills_sideways(self, browser_ok, api, size):
        async def check(page):
            return await page.evaluate("""() => {
              const view = document.querySelector('[data-view="system"]');
              const right = view.getBoundingClientRect().right + 1;
              return {overflow: view.scrollWidth - view.clientWidth,
                      wide: [...view.querySelectorAll('*')].filter(el => el.getBoundingClientRect().right > right)
                              .map(el => el.id || el.className)};
            }""")

        seen = _render(check, extra=_sys(api, None, mics=["A very long microphone name " * 4]),
                       route="system", viewport=size)
        assert seen["overflow"] <= 0 and seen["wide"] == [], seen
