"""Chat (UI-4): each command as a turn, with the tool steps it took inside
the reply, and Copy, Retry, Ask again, Speak and Save on each.

The Python side: replies are kept on the task record; "Ask again" makes
the model answer afresh without repeating anything it did; Speak and Save
act on a task by its id, never on text sent from the page.
"""
from __future__ import annotations

import re
import threading
import time

import pytest

from jarvis.ai import brain as brain_module
from jarvis.app import assistant, bridge, config, tasks
from jarvis.store import notes
from jarvis.tools import permissions, registry
from jarvis.voice.brief import for_speech


@pytest.fixture(autouse=True)
def fresh():
    tasks.reset()
    yield
    tasks.reset()


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
    lines = []
    made = assistant.Jarvis(log_fn=lines.append)
    made.muted = True
    made.lines = lines
    return made


def _wait_for(predicate, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _ended(text=None):
    return [t for t in tasks.recent(tasks.LIMIT)
            if t["status"] in tasks.ENDED and (text is None or t["text"] == text)]


class FakeBrain:
    def __init__(self, reply="All done.", raises=None):
        self.reply, self.raises = reply, raises

    def ask(self, text, on_action=None):
        if self.raises:
            raise self.raises
        return self.reply

    def reset(self):
        self.was_reset = True


# ============================================================ the replies

class TestTheReplyIsKept:
    def test_a_local_answer(self, bot):
        bot.handle("what's the time")
        assert tasks.recent(1)[0]["reply"].startswith("It's ")

    def test_a_model_answer(self, bot):
        bot.brain = FakeBrain("Pumpkins are squash.")
        bot.handle("tell me about pumpkins")
        assert tasks.recent(1)[0]["reply"] == "Pumpkins are squash."

    def test_a_failure_keeps_what_was_said(self, bot):
        bot.brain = FakeBrain(raises=RuntimeError("I can't reach the internet right now."))
        bot.handle("tell me about pumpkins")
        task = tasks.recent(1)[0]
        assert task["status"] == tasks.FAILED
        assert task["reply"] == "I can't reach the internet right now."

    @pytest.mark.parametrize("command,reply", [
        ("little", "Yes?"),
        ("stop", "Stopped."),
        ("recalibrate mic", "The mic isn't on yet. Click the core first."),
    ])
    def test_answers_that_are_only_spoken_are_kept_too(self, bot, command, reply):
        bot.handle(command)
        assert tasks.recent(1)[0]["reply"] == reply

    def test_the_microphone_list(self, bot, monkeypatch):
        import jarvis.voice
        monkeypatch.setattr(jarvis.voice, "microphones", lambda: "0: Built-in mic")
        bot.handle("list microphones")
        assert tasks.recent(1)[0]["reply"] == "0: Built-in mic"

    def test_a_new_conversation_is_marked(self, bot):
        bot.brain = FakeBrain()
        bot.handle("new conversation")
        task = tasks.recent(1)[0]
        assert task["reset"] is True and task["reply"] == "Fresh start. What's next?"
        assert bot.brain.was_reset

    def test_an_ordinary_command_is_not_marked(self, bot):
        bot.handle("what's the time")
        assert tasks.recent(1)[0]["reset"] is False

    def test_a_very_long_reply_is_kept_up_to_a_limit_and_says_so(self):
        tasks.start("x")
        tasks.reply("a" * (tasks.REPLY_MAX + 50))
        task = tasks.current()
        assert len(task["reply"]) == tasks.REPLY_MAX and task["reply_cut"] is True

    def test_a_thread_with_no_task_records_no_reply(self):
        tid = tasks.start("mine")
        t = threading.Thread(target=tasks.reply, args=("not yours",))
        t.start(); t.join()
        assert tasks.get(tid)["reply"] == ""


class TestLookingATaskUp:
    @pytest.mark.parametrize("bad", ["1", 1.0, True, None, [1], -1, 999])
    def test_only_a_real_id_finds_anything(self, bad):
        tasks.start("x")
        assert tasks.get(bad) is None

    def test_the_latest_by_route(self):
        a = tasks.start("a"); tasks.route("model"); tasks.finish(tasks.DONE)
        tasks.start("b"); tasks.route("local"); tasks.finish(tasks.DONE)
        assert tasks.latest("model")["id"] == a
        assert tasks.latest("plan") is None


# ============================================================ ask again

def _answers(monkeypatch, *texts):
    """The model, answering from a script, one reply per call."""
    queue = list(texts)

    def call(_payload):
        return {"candidates": [{"content": {"parts": [{"text": queue.pop(0)}]}}]}
    monkeypatch.setattr(brain_module, "call_gemini", call)


class TestForgetLast:
    def test_a_plain_exchange_is_taken_back(self, monkeypatch):
        _answers(monkeypatch, "one")
        b = brain_module.Brain()
        b.ask("tell me a joke")
        assert b.forget_last("tell me a joke") is True
        assert b.history == []

    def test_only_if_it_was_that_question(self, monkeypatch):
        _answers(monkeypatch, "one")
        b = brain_module.Brain()
        b.ask("tell me a joke")
        assert b.forget_last("tell me a story") is False
        assert len(b.history) == 2

    def test_never_an_exchange_that_ran_tools(self, monkeypatch):
        """Tool calls already happened; taking the words back wouldn't undo
        them, and asking again would do them twice."""
        replies = [
            {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "fake_tool", "args": {}}}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "Did it."}]}}]},
        ]
        monkeypatch.setattr(brain_module, "call_gemini", lambda _p: replies.pop(0))
        monkeypatch.setitem(registry.FUNCTIONS, "fake_tool", lambda **_k: "ok")
        b = brain_module.Brain()
        b.ask("do the thing")
        assert b.forget_last("do the thing") is False
        assert len(b.history) == 4

    def test_never_one_left_holding_a_tool_call(self):
        """A history that ends on the model asking for a tool — cut off
        before the tool ran — is not a plain answer either."""
        b = brain_module.Brain()
        b.history = [{"role": "user", "parts": [{"text": "do it"}]},
                     {"role": "model", "parts": [{"functionCall": {"name": "run_command", "args": {}}}]}]
        assert b.forget_last("do it") is False and len(b.history) == 2

    def test_nothing_to_forget(self):
        assert brain_module.Brain().forget_last("anything") is False


class TestAskAgain:
    @pytest.fixture
    def api(self, monkeypatch):
        monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
        monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
        original = permissions.confirm_fn
        made = bridge.Api()
        made.jarvis.muted = True
        yield made
        permissions.set_confirm(original)

    def _asked(self, api, text):
        before = len(_ended())
        api.send(text)
        assert _wait_for(lambda: len(_ended()) > before), "the command never finished"
        return tasks.recent(1)[0]

    def test_the_model_answers_afresh_and_forgets_the_first_answer(self, api, monkeypatch):
        _answers(monkeypatch, "Why did the chicken…", "A horse walks into a bar…")
        first = self._asked(api, "tell me a joke")
        assert first["route"] == "model" and first["reply"] == "Why did the chicken…"

        assert api.regenerate(first["id"]) == ""
        assert _wait_for(lambda: len(_ended()) == 2)
        again = tasks.recent(1)[0]
        assert again["again_of"] == first["id"] and again["text"] == "tell me a joke"
        assert again["reply"] == "A horse walks into a bar…"
        history = api.jarvis.brain.history
        assert [m["parts"][0]["text"] for m in history] == ["tell me a joke", "A horse walks into a bar…"], \
            "the first answer is gone from what the model remembers"

    def test_not_an_older_answer(self, api, monkeypatch):
        _answers(monkeypatch, "one", "two")
        first = self._asked(api, "tell me a joke")
        self._asked(api, "tell me another")
        assert api.regenerate(first["id"]) == "Only the latest answer can be asked again."

    def test_not_a_local_answer(self, api):
        task = self._asked(api, "what's the time")
        assert "plain answer from the model" in api.regenerate(task["id"])

    def test_not_an_answer_that_ran_tools(self, api):
        tasks.start("do the thing")
        tasks.route("model")
        tasks.step_finished(tasks.step_started("fake_tool"))
        tasks.reply("Did it.")
        tasks.finish(tasks.DONE)
        assert "plain answer" in api.regenerate(tasks.recent(1)[0]["id"])

    def test_not_a_failed_one(self, api):
        tasks.start("x"); tasks.route("model"); tasks.finish(tasks.FAILED, "offline")
        assert "plain answer" in api.regenerate(tasks.recent(1)[0]["id"])

    def test_not_while_something_else_is_running(self, api):
        tasks.start("done one"); tasks.route("model"); tasks.reply("ok"); tasks.finish(tasks.DONE)
        done = tasks.recent(1)[0]["id"]
        holder = threading.Thread(target=lambda: (tasks.start("busy"), time.sleep(0.3)))
        holder.start()
        time.sleep(0.05)
        assert api.regenerate(done) == "I'm still working on something. Ask again when I'm done."
        holder.join()

    @pytest.mark.parametrize("bad", ["1", True, None, 999])
    def test_not_for_an_id_that_isnt_one(self, api, bad):
        assert api.regenerate(bad) != ""

    def test_the_brain_refusing_is_passed_on(self, api, monkeypatch):
        """If the history has moved on in a way the checks didn't see, the
        assistant itself refuses rather than asking twice."""
        _answers(monkeypatch, "one")
        first = self._asked(api, "tell me a joke")
        api.jarvis.brain.history.append({"role": "user", "parts": [{"text": "something else"}]})
        assert api.regenerate(first["id"]) == "Only the latest answer can be asked again."


# ============================================================ speak, save

class Speaker:
    def __init__(self, muted=False):
        self.muted, self.said = muted, []
        self._said = threading.Event()

    def say(self, text):
        self.said.append(text)
        self._said.set()

    def handle(self, text): ...


@pytest.fixture
def quiet_api(monkeypatch):
    monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
    original = permissions.confirm_fn
    made = bridge.Api(assistant=Speaker())
    yield made
    permissions.set_confirm(original)


def _answered(text, reply, status=tasks.DONE):
    tid = tasks.start(text)
    tasks.reply(reply)
    tasks.finish(status, "x" if status == tasks.FAILED else "")
    return tid


class TestSpeak:
    def test_it_reads_the_reply_as_briefly_as_the_voice_does(self, quiet_api):
        long = "Here are your top matches. " + "A long list. " * 30
        tid = _answered("show my top matches", long)
        assert quiet_api.speak(tid) == ""
        assert quiet_api.jarvis._said.wait(2)
        assert quiet_api.jarvis.said == [for_speech(long)]

    def test_muted_it_says_so_instead(self, quiet_api):
        tid = _answered("x", "Hello.")
        quiet_api.jarvis.muted = True
        assert quiet_api.speak(tid) == "Voice is muted. Unmute it to hear this."
        time.sleep(0.05)
        assert quiet_api.jarvis.said == []

    @pytest.mark.parametrize("bad", ["1", True, None, 999])
    def test_only_for_a_real_task(self, quiet_api, bad):
        _answered("x", "Hello.")
        assert quiet_api.speak(bad) == "There's nothing to read out for that one."
        assert quiet_api.jarvis.said == []

    def test_not_for_a_task_with_nothing_said(self, quiet_api):
        tid = tasks.start("still going")
        assert quiet_api.speak(tid) == "There's nothing to read out for that one."


class TestSave:
    @pytest.fixture
    def workspace(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WORKSPACE", tmp_path)
        return tmp_path

    def test_it_keeps_the_turn_in_a_notes_file_in_the_workspace(self, quiet_api, workspace):
        tid = _answered("what's the time", "It's 08:41 PM.")
        assert quiet_api.save(tid) == "Saved to Saved from Little.md, in your workspace."
        text = (workspace / "Saved from Little.md").read_text(encoding="utf-8")
        assert text.startswith("# Saved from Little\n")
        assert "**You:** what's the time" in text and "It's 08:41 PM." in text

    def test_each_save_adds_nothing_is_overwritten(self, quiet_api, workspace):
        quiet_api.save(_answered("one", "First."))
        quiet_api.save(_answered("two", "Second."))
        text = (workspace / "Saved from Little.md").read_text(encoding="utf-8")
        assert text.count("# Saved from Little\n") == 1
        assert text.index("First.") < text.index("Second.")

    def test_the_file_is_always_in_the_workspace(self, workspace):
        assert notes.path().parent == workspace

    @pytest.mark.parametrize("bad", ["1", True, None, 999])
    def test_only_for_a_real_task(self, quiet_api, workspace, bad):
        _answered("x", "Hello.")
        assert quiet_api.save(bad) == "There's nothing to save for that one."
        assert not (workspace / "Saved from Little.md").exists()

    def test_a_write_that_fails_says_so(self, quiet_api, workspace, monkeypatch):
        def broken(*_a, **_k):
            raise PermissionError("read-only")
        monkeypatch.setattr(notes, "save_turn", broken)
        tid = _answered("x", "Hello.")
        assert quiet_api.save(tid) == "I couldn't write the notes file. Check the workspace folder."


# ================================================ what the window reads

class TestTheStateAfterSpeaking:
    """say() used to leave the state at SPEAKING when the mic was off, so
    the orb read as awake and the next click turned it off, not on."""

    def test_with_the_mic_off_it_goes_back_to_offline(self, monkeypatch):
        monkeypatch.setattr(assistant, "speak", lambda _t: None)
        seen = []
        bot = assistant.Jarvis(log_fn=lambda _l: None, status_fn=seen.append)
        bot.muted, bot.running = False, False
        bot.say("Hello")
        assert seen[-2:] == ["speaking", "offline"]

    def test_with_the_mic_on_it_goes_back_to_listening(self, monkeypatch):
        monkeypatch.setattr(assistant, "speak", lambda _t: None)
        seen = []
        bot = assistant.Jarvis(log_fn=lambda _l: None, status_fn=seen.append)
        bot.muted, bot.running = False, True
        bot.say("Hello")
        assert seen[-2:] == ["speaking", "listening"]


# ========================================================== in a browser

import json  # noqa: E402

import _ui  # noqa: E402

ATTACK = '<img src=x onerror="window.__ran=1">'


@pytest.fixture(scope="module")
def browser_ok():
    if not _ui.available():
        pytest.skip("Playwright isn't installed")


def _render(check, **kw):
    kw.setdefault("route", "chat")
    result, errors = _ui.open_panel(check, **kw)
    if result is _ui.NO_BROWSER:
        pytest.skip("no browser to render the panel with")
    assert errors == [], errors
    return result


def _stats(muted=False):
    return {
        "identity": {"name": "LITTLE", "call": "Little"}, "system": {"available": False},
        "session": {"uptime": "0", "commands": 0, "tools": 0, "os": "Windows 11"},
        "voice": {"mic": "on", "speech": "muted" if muted else "on", "voice": "Neerja",
                  "lang": "en-IN", "model": "m"},
        "tools": [], "reminders": [], "plan": None, "browser": "closed", "contacts": 0,
        "workspace": "C:/w", "warnings": [],
    }


def _poll(since=0, muted=False, status="listening"):
    version, changed = tasks.changed_since(since)
    return {"status": status, "lines": [], "stats": _stats(muted),
            "tasks": {"v": version, "changed": changed}}


def _turn(text, reply="", status=tasks.DONE, route="model", steps=(), error="", source="typed"):
    tid = tasks.start(text, source=source)
    tasks.route(route)
    for name, detail in steps:
        tasks.step_finished(tasks.step_started(name, detail))
    if reply:
        tasks.reply(reply)
    if status in tasks.ENDED:
        tasks.finish(status, error)
    return tid


CHAT = """() => ({
  turns: [...document.querySelectorAll('#turns > li')].map(li => ({
    id: Number(li.dataset.task), cls: li.className,
    you: li.querySelector('.msg--you .msg-text').textContent,
    when: li.querySelector('.msg--you .msg-when').textContent,
    how: li.querySelector('.msg--little .msg-when').textContent,
    reply: [...li.querySelectorAll('.msg-reply')].map(r => r.textContent),
    fail: !!li.querySelector('.msg-fail'),
    working: li.querySelector('.msg-working') ? li.querySelector('.msg-working').textContent : null,
    asking: li.querySelector('.msg-asking') ? li.querySelector('.msg-asking').textContent : null,
    toggle: li.querySelector('.steps-toggle') ? [li.querySelector('.steps-toggle').textContent,
             li.querySelector('.steps-toggle').getAttribute('aria-expanded')] : null,
    steps: [...li.querySelectorAll('.trace li')].map(s => [s.className,
             s.querySelector('.step-name').textContent, s.querySelector('.step-detail').textContent]),
    stepsShown: li.querySelector('.trace') ? !li.querySelector('.trace').hidden : null,
    acts: [...li.querySelectorAll('.msg-acts button')].map(b => b.textContent + (b.disabled ? ' (off)' : '')),
  })),
  fresh: document.getElementById('chatFresh').hidden ? null : document.getElementById('chatFresh').textContent,
  empty: document.getElementById('chatEmpty').hidden ? null : document.getElementById('chatEmpty').textContent,
  status: document.getElementById('chatStatus').textContent,
  calls: window.__calls,
  focus: document.activeElement.id || document.activeElement.dataset.key || '',
  hash: location.hash,
})"""


class TestAToolUsingCommandEndToEnd:
    """The plan's test for this phase: a command with two tool calls shows
    both steps, in order — run for real through the assistant, the brain's
    tool loop, the registry and the bridge, then replayed into Chat."""

    def test_both_steps_show_in_order_inside_the_reply(self, browser_ok, monkeypatch):
        monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
        monkeypatch.setitem(registry.FUNCTIONS, "list_dir", lambda **_k: "src/ tests/ README.md")
        monkeypatch.setitem(registry.FUNCTIONS, "read_file", lambda **_k: "# Pill Reminder\nTODO: tests")
        script = [
            {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "list_dir", "args": {"path": "project"}}}]}}]},
            {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "read_file", "args": {"path": "project/README.md"}}}]}}]},
            {"candidates": [{"content": {"parts": [
                {"text": "It's a pill reminder app. The README has one TODO: tests."}]}}]},
        ]
        monkeypatch.setattr(brain_module, "call_gemini", lambda _p: script.pop(0))

        original = permissions.confirm_fn
        api = bridge.Api()
        api.jarvis.muted = True
        try:
            api.poll(0)
            api.send("what's in my project and is there a readme")
            payloads, since = [], 0
            for _ in range(300):
                out = api.poll(since)
                since = out["tasks"]["v"]
                payloads.append(out)
                if any(t["status"] in tasks.ENDED for t in out["tasks"]["changed"]):
                    break
                time.sleep(0.01)
        finally:
            permissions.set_confirm(original)

        opening = {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}
        page_script = _ui.bridge(opening) + "window.__queue.push(...%s);" % json.dumps(payloads)

        async def check(page):
            for _ in range(200):
                if await page.evaluate("window.__queue.length === 0"):
                    break
                await page.wait_for_timeout(25)
            await page.wait_for_timeout(250)
            before = await page.evaluate(CHAT)
            await page.click(".steps-toggle")
            return before, await page.evaluate(CHAT)

        folded, opened = _render(check, script=page_script, wait_ms=250)
        (turn,) = opened["turns"]
        assert turn["you"] == "what's in my project and is there a readme"
        assert turn["reply"] == ["It's a pill reminder app. The README has one TODO: tests."]
        assert turn["how"].startswith("by the model")
        assert turn["toggle"][0].startswith("2 steps")
        assert [(cls, name) for cls, name, _ in turn["steps"]] == [("done", "list_dir"), ("done", "read_file")]
        assert turn["steps"][0][2] == '{"path": "project"}'
        assert turn["steps"][1][2] == '{"path": "project/README.md"}'
        assert folded["turns"][0]["stepsShown"] is False, "a finished turn's steps start folded"
        assert opened["turns"][0]["stepsShown"] is True and turn["toggle"][1] == "true"


class TestTurns:
    def test_each_kind_of_turn_reads_as_what_it_is(self, browser_ok):
        _turn("what's the time", "It's 08:41 PM.", route="local")
        _turn("find jobs", "offline", tasks.FAILED, route="local", error="I can't reach the internet right now.")
        _turn("create an app, then run it", "Stopped after step 1 of 2.", tasks.STOPPED, route="plan")
        tid = _turn("delete notes.txt", status=tasks.ACTIVE)
        tasks.waiting("Delete notes.txt?")
        seen = _render(lambda page: page.evaluate(CHAT), script=_ui.bridge(_poll()))
        done, failed, stopped, waiting = seen["turns"]

        assert done["cls"] == "turn is-done" and done["reply"] == ["It's 08:41 PM."]
        assert done["how"].startswith("on this computer · ")
        assert failed["fail"] and failed["reply"] == ["I can't reach the internet right now."]
        assert "Try again" in failed["acts"]
        assert stopped["reply"] == ["Stopped after step 1 of 2."] and "Try again" in stopped["acts"]
        assert waiting["asking"] == "Waiting for your answer: Delete notes.txt?"
        assert waiting["acts"] == [], "nothing to press on a turn still going"
        assert waiting["id"] == tid

    def test_a_running_turn_shows_its_steps_live_and_how_long(self, browser_ok):
        tasks.start("summarise the readme")
        tasks.route("model")
        tasks.step_finished(tasks.step_started("read_file", '{"path": "README.md"}'))
        tasks.step_started("search_files", '{"contains": "TODO"}')
        seen = _render(lambda page: page.evaluate(CHAT), script=_ui.bridge(_poll(status="executing")))
        (turn,) = seen["turns"]
        assert turn["stepsShown"] is True
        assert [cls for cls, _, _ in turn["steps"]] == ["done", "now"]
        assert turn["how"] == "asking the model"
        assert re.match(r"Working on it · \d+\.\ds", turn["working"])

    def test_what_you_said_aloud_says_so(self, browser_ok):
        _turn("what's the time", "It's 8.", route="local", source="voice")
        seen = _render(lambda page: page.evaluate(CHAT), script=_ui.bridge(_poll()))
        assert seen["turns"][0]["when"].endswith(" · said")

    def test_a_long_reply_says_where_the_rest_is(self, browser_ok):
        tasks.start("show everything")
        tasks.reply("x" * (tasks.REPLY_MAX + 10))
        tasks.finish(tasks.DONE)
        seen = _render(lambda page: page.evaluate(
            "document.querySelector('.msg-note') && document.querySelector('.msg-note').textContent"),
            script=_ui.bridge(_poll()))
        assert "Activity on Home has all of it" in seen

    def test_with_nothing_yet_it_says_what_will_appear(self, browser_ok):
        seen = _render(lambda page: page.evaluate(CHAT), script=_ui.bridge(_poll()))
        assert seen["turns"] == [] and seen["empty"].startswith("Nothing here yet.")

    def test_typing_here_stays_here(self, browser_ok):
        async def check(page):
            await page.focus("#input")
            await page.keyboard.type("what's the time")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(100)
            return await page.evaluate(CHAT)

        seen = _render(check, script=_ui.bridge(_poll()))
        assert ["send", "what's the time"] in seen["calls"] and seen["hash"] == "#/chat"
        assert seen["focus"] == "input"


class TestReplyActions:
    def _one(self, **kw):
        tid = _turn("tell me a joke", "Why did the compiler break up with the linker?", **kw)
        return tid

    def test_copy_puts_the_reply_on_the_clipboard(self, browser_ok):
        self._one()
        script = _ui.bridge(_poll()) + """
          Object.defineProperty(navigator, 'clipboard', { value: {
            writeText: async (t) => { window.__copied = t; } } });"""

        async def check(page):
            await page.click('[data-act="copy"]')
            await page.wait_for_timeout(100)
            return await page.evaluate("window.__copied"), await page.evaluate(CHAT)

        copied, seen = _render(check, script=script)
        assert copied == "Why did the compiler break up with the linker?"
        assert seen["status"] == "Copied."

    def test_copy_still_works_where_the_clipboard_api_is_refused(self, browser_ok):
        self._one()
        script = _ui.bridge(_poll()) + """
          Object.defineProperty(navigator, 'clipboard', { value: {
            writeText: async () => { throw new Error('not allowed'); } } });
          document.execCommand = (c) => { window.__exec = [c, document.activeElement.value]; return true; };"""

        async def check(page):
            await page.click('[data-act="copy"]')
            await page.wait_for_timeout(100)
            return await page.evaluate("window.__exec"), await page.evaluate(CHAT)

        executed, seen = _render(check, script=script)
        assert executed == ["copy", "Why did the compiler break up with the linker?"]
        assert seen["status"] == "Copied." and seen["focus"] == f"copy-{seen['turns'][0]['id']}"

    def test_speak_and_save_send_only_the_task_id(self, browser_ok):
        tid = self._one()
        script = _ui.bridge(_poll()) + \
            "window.__answers = {save: 'Saved to Saved from Little.md, in your workspace.'};"

        async def check(page):
            await page.click('[data-act="speak"]')
            await page.wait_for_timeout(60)
            spoke = (await page.evaluate(CHAT))["status"]
            await page.click('[data-act="save"]')
            await page.wait_for_timeout(60)
            return spoke, await page.evaluate(CHAT)

        spoke, seen = _render(check, script=script)
        assert seen["calls"] == [["speak", tid], ["save", tid]]
        assert spoke == "Reading it out."
        assert seen["status"] == "Saved to Saved from Little.md, in your workspace."

    def test_what_python_says_back_is_shown_as_it_is(self, browser_ok):
        self._one()
        script = _ui.bridge(_poll()) + \
            "window.__answers = {speak: 'Voice is muted. Unmute it to hear this.'};"

        async def check(page):
            await page.click('[data-act="speak"]')
            await page.wait_for_timeout(60)
            return await page.evaluate(CHAT)

        assert _render(check, script=script)["status"] == "Voice is muted. Unmute it to hear this."

    def test_speak_is_off_while_the_voice_is_muted(self, browser_ok):
        self._one()
        seen = _render(lambda page: page.evaluate(CHAT), script=_ui.bridge(_poll(muted=True)))
        assert "Speak (off)" in seen["turns"][0]["acts"]

    def test_try_again_sends_the_same_command(self, browser_ok):
        _turn("find jobs for me", "offline", tasks.FAILED, route="local", error="offline")

        async def check(page):
            await page.click('[data-act="retry"]')
            await page.wait_for_timeout(60)
            return await page.evaluate(CHAT)

        seen = _render(check, script=_ui.bridge(_poll()))
        assert seen["calls"] == [["send", "find jobs for me"]] and seen["hash"] == "#/chat"


class TestAskAgainIsOfferedOnlyWhereItsSafe:
    def _acts(self):
        seen = _render(lambda page: page.evaluate(CHAT), script=_ui.bridge(_poll()))
        return [t["acts"] for t in seen["turns"]], seen

    def test_only_on_the_models_latest_plain_answer(self, browser_ok):
        _turn("tell me a joke", "one")
        _turn("what's the time", "It's 8.", route="local")
        _turn("tell me another", "two")
        acts, _ = self._acts()
        assert "Ask again" not in acts[0]
        assert "Ask again" not in acts[1]
        assert "Ask again" in acts[2]

    def test_never_on_an_answer_that_ran_tools(self, browser_ok):
        _turn("delete the old logs", "Done.", steps=[("delete_path", '{"path": "logs"}')])
        acts, _ = self._acts()
        assert "Ask again" not in acts[0]

    def test_not_while_something_is_running(self, browser_ok):
        _turn("tell me a joke", "one")
        _turn("find jobs", status=tasks.ACTIVE, route="local")
        acts, _ = self._acts()
        assert "Ask again" not in acts[0]

    def test_pressing_it_asks_python_by_id(self, browser_ok):
        tid = _turn("tell me a joke", "one")

        async def check(page):
            await page.click('[data-act="again"]')
            await page.wait_for_timeout(60)
            return await page.evaluate(CHAT)

        seen = _render(check, script=_ui.bridge(_poll()))
        assert seen["calls"] == [["regenerate", tid]] and seen["status"] == "Asking again."

    def test_an_asked_again_turn_says_so(self, browser_ok):
        first = _turn("tell me a joke", "one")
        tid = tasks.start("tell me a joke", again_of=first)
        tasks.route("model"); tasks.reply("two"); tasks.finish(tasks.DONE)
        seen = _render(lambda page: page.evaluate(CHAT), script=_ui.bridge(_poll()))
        assert seen["turns"][-1]["id"] == tid and "asked again" in seen["turns"][-1]["when"]


class TestNewConversation:
    def test_it_takes_two_clicks_and_the_second_defaults_to_keeping_it(self, browser_ok):
        _turn("tell me a joke", "one")

        async def check(page):
            await page.click("#newChat")
            asked = {"shown": await page.evaluate("!document.getElementById('resetAsk').hidden"),
                     "focus": await page.evaluate("document.activeElement.id")}
            await page.keyboard.press("Enter")                 # on "Keep it"
            kept = await page.evaluate(CHAT)
            await page.click("#newChat")
            await page.keyboard.press("Escape")                # also keeps it
            escaped = await page.evaluate(CHAT)
            await page.click("#newChat")
            await page.click("#resetYes")
            await page.wait_for_timeout(60)
            return asked, kept, escaped, await page.evaluate(CHAT)

        asked, kept, escaped, done = _render(check, script=_ui.bridge(_poll()))
        assert asked == {"shown": True, "focus": "resetKeep"}
        assert kept["calls"] == [] and kept["focus"] == "newChat"
        assert escaped["calls"] == [], "Escape here keeps it, and isn't Stop either"
        assert done["calls"] == [["send", "new conversation"]] and done["hash"] == "#/chat"

    def test_after_one_only_what_follows_shows(self, browser_ok):
        _turn("tell me a joke", "one")
        _turn("tell me another", "two")
        reset = tasks.start("new conversation")
        tasks.route("local"); tasks.mark_reset(); tasks.reply("Fresh start. What's next?")
        tasks.finish(tasks.DONE)
        _turn("what's the time", "It's 8.", route="local")
        seen = _render(lambda page: page.evaluate(CHAT), script=_ui.bridge(_poll()))
        assert [t["you"] for t in seen["turns"]] == ["what's the time"]
        assert seen["fresh"].startswith("New conversation · ")
        assert tasks.get(reset)["reset"]

    def test_right_after_one_it_says_fresh_start(self, browser_ok):
        tasks.start("new conversation"); tasks.mark_reset(); tasks.finish(tasks.DONE)
        seen = _render(lambda page: page.evaluate(CHAT), script=_ui.bridge(_poll()))
        assert seen["turns"] == [] and seen["empty"] == "Fresh start. Ask me anything below."


class TestUpdatesDontGetInTheWay:
    def test_an_opened_step_list_stays_open_as_new_turns_arrive(self, browser_ok):
        _turn("check the project", "Fine.", steps=[("list_dir", "{}")])
        first = _poll()
        _turn("what's the time", "It's 8.", route="local")
        # Muting redraws every turn (Speak turns off), so this checks the
        # choice is remembered, not just that the element was left alone.
        later = _poll(since=first["tasks"]["v"], muted=True)
        script = _ui.bridge(first) + "window.__later = %s;" % json.dumps(later)

        async def check(page):
            await page.click(".steps-toggle")
            await page.evaluate("window.__queue.push(window.__later)")
            await page.wait_for_timeout(450)
            return await page.evaluate(CHAT)

        seen = _render(check, script=script)
        assert len(seen["turns"]) == 2, "the update arrived"
        assert "Speak (off)" in seen["turns"][0]["acts"], "the turn was redrawn"
        assert seen["turns"][0]["stepsShown"] is True

    def test_keyboard_focus_stays_on_its_button_when_the_turn_is_redrawn(self, browser_ok):
        tid = _turn("tell me a joke", "one")
        first = _poll()
        muted = _poll(since=first["tasks"]["v"], muted=True)   # redraws: Speak turns off
        script = _ui.bridge(first) + "window.__later = %s;" % json.dumps(muted)

        async def check(page):
            await page.focus(f'[data-key="save-{tid}"]')
            await page.evaluate("window.__queue.push(window.__later)")
            await page.wait_for_timeout(450)
            return await page.evaluate(CHAT)

        seen = _render(check, script=script)
        assert "Speak (off)" in seen["turns"][0]["acts"], "the turn was redrawn"
        assert seen["focus"] == f"save-{tid}"

    def test_reading_back_up_isnt_interrupted_but_a_new_turn_is_shown(self, browser_ok):
        for i in range(12):
            _turn(f"question {i}", "a fairly long answer\n" * 4, route="local")
        first = _poll()
        tid = tasks.start("still going"); tasks.route("model")
        update = _poll(since=first["tasks"]["v"])
        tasks.step_finished(tasks.step_started("read_file", "{}"), task_id=tid)
        step = _poll(since=update["tasks"]["v"])
        script = _ui.bridge(first) + "window.__later = %s;" % json.dumps([update, step])

        async def check(page):
            wrap = "document.getElementById('turnsWrap')"
            at_bottom = f"{wrap}.scrollTop + {wrap}.clientHeight >= {wrap}.scrollHeight - 40"
            opened_at_bottom = await page.evaluate(at_bottom)
            await page.evaluate(f"{wrap}.scrollTop = 0")
            await page.evaluate("window.__queue.push(window.__later[0])")   # a new turn
            await page.wait_for_timeout(350)
            new_turn_shown = await page.evaluate(at_bottom)
            await page.evaluate(f"{wrap}.scrollTop = 0")
            await page.evaluate("window.__queue.push(window.__later[1])")   # a step on it
            await page.wait_for_timeout(350)
            return opened_at_bottom, new_turn_shown, await page.evaluate(f"{wrap}.scrollTop")

        opened_at_bottom, new_turn_shown, top_after_step = _render(check, script=script)
        assert opened_at_bottom, "Chat opens on the latest turn"
        assert new_turn_shown, "a new turn is brought into view"
        assert top_after_step == 0, "a step on it doesn't yank you back down while you read"


class TestChatIsSafeAndFits:
    def test_nothing_in_a_turn_runs_as_markup(self, browser_ok):
        tid = tasks.start(ATTACK)
        tasks.step_finished(tasks.step_started(ATTACK, ATTACK))
        tasks.reply(ATTACK)
        tasks.finish(tasks.FAILED, ATTACK, task_id=tid)
        tasks.start(ATTACK)
        tasks.waiting(ATTACK)

        async def check(page):
            await page.click(".steps-toggle")
            return {"images": await page.evaluate("document.querySelectorAll('.chat img').length"),
                    "ran": await page.evaluate("window.__ran || 0"), **await page.evaluate(CHAT)}

        seen = _render(check, script=_ui.bridge(_poll()))
        assert seen["images"] == 0 and seen["ran"] == 0
        assert seen["turns"][0]["you"] == ATTACK and ATTACK in seen["turns"][1]["asking"]

    @pytest.mark.parametrize("size", [(1040, 660), (1920, 1080)], ids=lambda s: f"{s[0]}x{s[1]}")
    def test_long_words_wrap_and_nothing_runs_under_the_command_box(self, browser_ok, size):
        _turn("x" * 400, "y" * 3000, steps=[("read_file", "z" * 300)])
        tasks.start("still going")

        async def check(page):
            await page.click(".steps-toggle")
            return await page.evaluate("""() => {
              const wrap = document.getElementById('turnsWrap');
              return { sideways: wrap.scrollWidth > wrap.clientWidth + 1
                         || document.documentElement.scrollWidth > window.innerWidth,
                       clear: wrap.getBoundingClientRect().bottom
                         <= document.querySelector('.cmdbar').getBoundingClientRect().top };
            }""")

        seen = _render(check, script=_ui.bridge(_poll()), viewport=size)
        assert not seen["sideways"] and seen["clear"]
