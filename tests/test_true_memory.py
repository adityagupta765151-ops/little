"""Chapter 30 — memory in tiers: remember, recall, update and forget.

Short-term is the conversation in progress; task notes live while their
task runs; project facts, long-term facts and preferences are plain JSON on
this computer. Each tier keeps to itself, nothing secret is kept anywhere,
and none of it goes to the model unless a request looks it up.
"""
from __future__ import annotations

import json
import threading

import pytest

from jarvis import tools
from jarvis.ai import brain as brain_module
from jarvis.app import bridge, tasks
from jarvis.routing.router import fast_route
from jarvis.store import memory
from jarvis.tools.registry import FUNCTIONS, TOOL_SCHEMAS


def _file(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _everything_on_disk() -> str:
    return "".join(p.read_text(encoding="utf-8") for p in memory.MEMORY_DIR.glob("*.json"))


@pytest.fixture
def asked():
    """Records every question; answers with whatever `said` holds."""
    seen = {"asks": [], "said": False}
    tools.set_confirm(lambda ask: seen["asks"].append(ask) or seen["said"])
    yield seen
    tools.set_confirm(lambda _m: False)


@pytest.fixture
def in_a_task():
    """This thread is working on a task, as a command would be."""
    task_id = tasks.start("a test command")
    yield task_id
    tasks.finish(tasks.DONE, task_id=task_id)


# ================================================================== tiers

class TestEachTierKeepsWhereItShould:
    def test_long_term_is_a_fact_in_preferences_json(self):
        assert memory.remember("project folder", "D:/dev") == "Noted: project folder is D:/dev."
        assert _file(memory.PREFERENCES)["facts"] == {"project folder": "D:/dev"}

    def test_a_preference_is_kept_apart_from_facts(self):
        assert memory.set_preference("my preferred browser", "Firefox") == "Noted: you prefer Firefox for browser."
        stored = _file(memory.PREFERENCES)
        assert stored["preferred"] == {"browser": "Firefox"} and stored["facts"] == {}
        assert memory.recall("browser") == "Firefox"

    def test_a_project_fact_lives_under_its_project(self):
        memory.remember_for_project("Blood Bridge", "deadline", "Friday")
        memory.remember_for_project("blood bridge", "stack", "Node and MongoDB")
        assert _file(memory.PROJECT_MEMORY) == {"Blood Bridge": {"deadline": "Friday", "stack": "Node and MongoDB"}}
        assert memory.recall_project("BLOOD BRIDGE") == "Project Blood Bridge: deadline: Friday; stack: Node and MongoDB."

    def test_task_notes_are_never_written_to_disk(self, in_a_task):
        assert memory.note_for_task("repo path", "D:/dev/zqx-repo") == "Noted for this task: repo path is D:/dev/zqx-repo."
        assert memory.task_notes() == {"repo path": "D:/dev/zqx-repo"}
        assert "zqx-repo" not in _everything_on_disk()

    def test_task_notes_end_with_their_task(self):
        task_id = tasks.start("do a thing")
        memory.note_for_task("draft", "v1")
        tasks.finish(tasks.DONE, task_id=task_id)
        assert memory.task_notes(task_id) == {}

    def test_no_task_no_notes(self):
        assert memory.note_for_task("x", "y") == "There's no task running to note that against."
        assert memory.task_notes() == {}

    def test_only_the_latest_tasks_are_held(self):
        for task_id in range(1, memory.TASKS_KEPT + 6):
            memory.note_for_task("n", str(task_id), task_id=task_id)
        assert len(memory._task_notes) == memory.TASKS_KEPT
        assert memory.task_notes(1) == {} and memory.task_notes(memory.TASKS_KEPT + 5) == {"n": str(memory.TASKS_KEPT + 5)}

    def test_short_term_is_the_conversation_and_long_term_outlives_it(self):
        brain = brain_module.Brain()
        brain.note_exchange("what's my editor?", "VS Code.")
        memory.remember("editor", "VS Code")
        brain.reset()
        assert brain.history == [] and memory.recall("editor") == "VS Code"

    def test_it_survives_a_restart(self):
        memory.remember("editor", "VS Code")
        memory.set_preference("browser", "Firefox")
        memory.remember_for_project("QuantDesk", "broker", "paper")
        # A restart is a fresh read of the files; nothing is cached.
        assert json.loads(memory.PREFERENCES.read_text(encoding="utf-8"))["facts"]["editor"] == "VS Code"
        assert memory.recall() == ("You asked me to remember: editor: VS Code. Your preferences: browser: Firefox. "
                                   "Project QuantDesk: broker: paper.")

    def test_nothing_stored_is_said_plainly(self):
        assert memory.recall().startswith("I haven't stored anything about you yet.")
        assert memory.recall("editor") == "Nothing stored under editor."


# ============================================================== retrieval

class TestFindingThings:
    @pytest.fixture
    def kept(self):
        memory.remember("project folder", "D:/dev")
        memory.remember("college", "UCER Prayagraj")
        memory.set_preference("browser", "Firefox")
        memory.remember_for_project("Blood Bridge", "deadline", "Friday")
        memory.remember_for_project("QuantDesk", "deadline", "next month")

    def test_every_tier_is_searched_and_each_answer_says_where(self, kept):
        assert memory.recall_about("deadline") == "project Blood Bridge: deadline: Friday; project QuantDesk: deadline: next month."
        assert memory.recall_about("browser") == "your preference: browser: Firefox."
        assert memory.recall_about("prayagraj") == "college: UCER Prayagraj."

    def test_a_name_match_ranks_above_a_passing_mention(self):
        memory.remember("editor", "VS Code, opened in the folder above")
        memory.remember("project folder", "D:/dev")
        found = memory.search("folder")
        assert [f["key"] for f in found] == ["project folder", "editor"]

    def test_this_tasks_notes_are_found_too(self, kept, in_a_task):
        memory.note_for_task("build command", "npm run build")
        assert memory.recall_about("build") == "this task: build command: npm run build."

    def test_something_never_stored_is_not_invented(self, kept):
        assert memory.recall_about("salary") == "I don't have anything stored about salary."

    def test_little_words_match_nothing(self, kept):
        memory.remember("standup", "at the office, a daily thing")
        assert memory.search("the of a") == []
        assert memory.recall_about("what is the deadline") == \
            "project Blood Bridge: deadline: Friday; project QuantDesk: deadline: next month."

    def test_about_me_is_everything(self, kept):
        assert memory.recall_about("me") == memory.recall()

    def test_an_unknown_project_lists_the_known_ones(self, kept):
        assert memory.recall_project("Portfolio") == ("I have nothing stored for project Portfolio. "
                                                       "Projects I have notes for: Blood Bridge, QuantDesk.")


# ================================================================= update

class TestUpdating:
    def test_a_new_value_says_what_it_was(self):
        memory.remember("editor", "VS Code")
        assert memory.remember("editor", "Neovim") == "Updated: editor is now Neovim (it was VS Code)."
        assert memory.facts() == {"editor": "Neovim"}

    def test_the_same_value_changes_nothing(self):
        memory.remember("editor", "VS Code")
        before = memory.PREFERENCES.stat().st_mtime_ns
        assert memory.remember("Editor", "VS Code") == "I already have that: editor is VS Code."
        assert memory.PREFERENCES.stat().st_mtime_ns == before

    def test_preferences_and_projects_update_the_same_way(self):
        memory.set_preference("browser", "Chrome")
        assert memory.set_preference("browser", "Firefox") == "Updated: you now prefer Firefox for browser (it was Chrome)."
        memory.remember_for_project("QuantDesk", "broker", "paper")
        assert memory.remember_for_project("quantdesk", "broker", "Zerodha") == \
            "Updated for QuantDesk: broker is now Zerodha (it was paper)."

    def test_empty_is_not_remembered(self):
        assert memory.remember("", "x").startswith("Tell me what to remember")
        assert memory.set_preference("browser", " ").startswith("Tell me the preference")
        assert memory.remember_for_project("", "k", "v").startswith("Tell me the project")
        assert not memory.PREFERENCES.exists() or memory.facts() == {}

    def test_long_values_are_cut_not_refused(self):
        memory.remember("note", "x" * 2000)
        assert len(memory.facts()["note"]) == memory.VALUE_CHARS


# ================================================================= forget

class TestForgetting:
    def test_by_its_exact_name_allowing_only_for_my(self):
        memory.remember("my editor", "VS Code")
        assert memory.forget_anything("edit") == "I had nothing stored under edit."
        assert memory.forget_anything("editor") == "Forgotten: my editor."
        assert memory.facts() == {}

    def test_a_preference_or_a_projects_fact(self):
        memory.set_preference("browser", "Firefox")
        memory.remember_for_project("Blood Bridge", "deadline", "Friday")
        assert memory.forget_anything("my preferred browser") == "Forgotten: your preference for browser."
        assert memory.forget_anything("deadline") == "Forgotten: deadline for Blood Bridge."
        assert memory.preferred() == {} and memory.project_memory() == {}
        assert _file(memory.PROJECT_MEMORY) == {}, "a project with nothing left goes"

    def test_a_name_in_two_places_forgets_neither(self):
        memory.remember_for_project("Blood Bridge", "deadline", "Friday")
        memory.remember_for_project("QuantDesk", "deadline", "next month")
        reply = memory.forget_anything("deadline")
        assert reply.startswith("“deadline” is stored in more than one place (project Blood Bridge, project QuantDesk).")
        assert len(memory.project_memory()) == 2
        assert memory.forget_for_project("quantdesk", "deadline") == "Forgotten: deadline for QuantDesk."
        assert list(memory.project_memory()) == ["Blood Bridge"]

    def test_a_whole_project_asks_first(self, asked):
        memory.remember_for_project("Blood Bridge", "deadline", "Friday")
        memory.remember_for_project("Blood Bridge", "stack", "Node")
        assert memory.forget_project("blood bridge") == "Kept everything for Blood Bridge."
        parts = asked["asks"][0].parts()
        assert parts["action"] == "Forget a project's memory" and parts["target"] == "Blood Bridge"
        assert "deadline: Friday" in parts["details"]
        asked["said"] = True
        assert memory.forget_project("Blood Bridge") == "Forgotten: everything for Blood Bridge (2 things)."
        assert memory.project_memory() == {}

    def test_no_answer_keeps_it(self):
        tools.set_confirm(lambda ask: None)
        try:
            memory.remember_for_project("Blood Bridge", "deadline", "Friday")
            assert memory.forget_project("Blood Bridge") == "Kept everything for Blood Bridge."
        finally:
            tools.set_confirm(lambda _m: False)
        assert memory.project_memory() == {"Blood Bridge": {"deadline": "Friday"}}

    def test_forgetting_what_isnt_there(self, asked):
        assert memory.forget_project("Nope") == "I have nothing stored for project Nope."
        assert memory.forget_preference("browser") == "I had no preference stored for browser."
        assert memory.forget_for_project("Nope", "x") == "I had nothing stored under x for Nope."
        assert asked["asks"] == []


# ======================================================== nothing secret

SECRETS = [
    ("my password", "hunter2"), ("gmail passcode", "abc"), ("otp", "482913"), ("upi pin", "4321"),
    ("my pin", "1234"), ("atm pin", "9876"), ("card number", "4111"), ("api key", "abc"),
    ("gemini key", "abc"), ("github token", "abc"), ("aadhaar", "1234 5678 9012"), ("pan number", "ABCDE1234F"),
    ("bank account", "0012"), ("recovery phrase", "apple banana"),
    ("wifi", "AIzaSyA1234567890abcdefghijklmn"), ("note", "sk-proj-abcdefghijklmnop1234"),
    ("note", "ghp_abcdefghijklmnopqrstuvwxyz123456"), ("my card", "4111 1111 1111 1111"),
    ("login", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"),
]


class TestNothingSecretIsKept:
    @pytest.mark.parametrize("key,value", SECRETS)
    def test_refused_in_every_tier(self, key, value, in_a_task):
        for said in (memory.remember(key, value), memory.set_preference(key, value),
                     memory.remember_for_project("Blood Bridge", key, value), memory.note_for_task(key, value)):
            assert said == memory.REFUSED
        assert memory.facts() == {} and memory.preferred() == {} and memory.project_memory() == {}
        assert memory.task_notes() == {}

    @pytest.mark.parametrize("key,value", [("pin code", "211001"), ("my pincode", "211001"),
                                           ("rahul's number", "+91 98765 43210"), ("rahul", "+919876543210"),
                                           ("secret word", "zanzibar"), ("house key", "under the mat"),
                                           ("order id", "1234567890123")])
    def test_ordinary_things_that_look_close_are_kept(self, key, value):
        assert memory.remember(key, value).startswith("Noted")

    def test_the_conversation_log_hides_them(self):
        memory.log_turn("remember that my password is hunter2", memory.REFUSED)
        memory.log_turn("my card is 4111 1111 1111 1111, key AIzaSyA1234567890abcdefghijklmn", "ok")
        memory.log_turn("my pin code is 211001", "ok")
        logged = memory.HISTORY.read_text(encoding="utf-8")
        for secret in ("hunter2", "4111", "AIzaSy"):
            assert secret not in logged
        assert "my password is [hidden]" in logged and "211001" in logged

    def test_by_command_too(self):
        assert fast_route("remember that my UPI PIN is 4321") == memory.REFUSED
        assert "4321" not in _everything_on_disk()


# ============================================================== isolation

class TestEachKeepsToItself:
    def test_one_project_never_answers_for_another(self):
        memory.remember_for_project("Blood Bridge", "deadline", "Friday")
        memory.remember_for_project("QuantDesk", "broker", "paper")
        assert "broker" not in memory.recall_project("Blood Bridge")
        assert "deadline" not in memory.recall_project("QuantDesk")

    def test_one_task_never_sees_anothers_notes(self):
        memory.note_for_task("secret plan", "alpha", task_id=101)
        memory.note_for_task("other", "beta", task_id=102)
        assert memory.task_notes(101) == {"secret plan": "alpha"}
        assert [f["value"] for f in memory.search("plan", task_id=102)] == []
        assert [f["value"] for f in memory.search("plan", task_id=101)] == ["alpha"]

    def test_a_task_on_another_thread_has_its_own(self):
        seen = {}

        def other():
            task_id = tasks.start("elsewhere")
            memory.note_for_task("where", "thread two")
            seen["theirs"] = memory.task_notes()
            tasks.finish(tasks.DONE, task_id=task_id)

        mine = tasks.start("here")
        memory.note_for_task("where", "thread one")
        worker = threading.Thread(target=other)
        worker.start()
        worker.join()
        assert memory.task_notes() == {"where": "thread one"} and seen["theirs"] == {"where": "thread two"}
        tasks.finish(tasks.DONE, task_id=mine)

    def test_all_of_it_is_in_the_memory_folder(self):
        memory.remember("editor", "VS Code")
        memory.set_preference("browser", "Firefox")
        memory.remember_for_project("QuantDesk", "broker", "paper")
        for path in (memory.PREFERENCES, memory.PROJECT_MEMORY):
            assert path.parent == memory.MEMORY_DIR and path.exists()

    def test_none_of_it_goes_to_the_model_with_a_request(self, monkeypatch, in_a_task):
        memory.remember("secret word", "zanzibar-7731")
        memory.set_preference("browser", "okapi-browser")
        memory.remember_for_project("Pangolin", "deadline", "quetzal-day")
        memory.note_for_task("scratch", "narwhal-99")
        sent = []

        def model(payload):
            sent.append(json.dumps(payload, ensure_ascii=False))
            return {"candidates": [{"content": {"parts": [{"text": "Hello!"}]}}]}
        monkeypatch.setattr(brain_module, "call_gemini", model)
        assert brain_module.Brain().ask("hello") == "Hello!"
        for secret in ("zanzibar", "okapi", "Pangolin", "quetzal", "narwhal"):
            assert secret not in sent[0]

    def test_only_what_a_lookup_returns_reaches_the_model(self, monkeypatch):
        memory.remember_for_project("Pangolin", "deadline", "quetzal-day")
        memory.remember("secret word", "zanzibar-7731")
        replies = iter([
            {"candidates": [{"content": {"parts": [{"functionCall": {"name": "recall_memory",
                                                                      "args": {"query": "deadline"}}}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "Friday-ish."}]}}]},
        ])
        sent = []
        monkeypatch.setattr(brain_module, "call_gemini", lambda p: sent.append(json.dumps(p)) or next(replies))
        brain_module.Brain().ask("when is the pangolin deadline?")
        assert "quetzal-day" in sent[1] and "zanzibar" not in sent[1]


# =============================================================== commands

class TestByCommand:
    def test_each_tier_by_what_you_say(self):
        assert fast_route("remember that my editor is VS Code") == "Noted: my editor is VS Code."
        assert fast_route("Remember for project Blood Bridge that the deadline is Friday") == \
            "Noted for Blood Bridge: deadline is Friday."
        assert fast_route("remember in project blood bridge, stack is Node and MongoDB") == \
            "Noted for Blood Bridge: stack is Node and MongoDB."
        assert fast_route("remember that my preferred browser is Firefox") == "Noted: you prefer Firefox for browser."

    def test_recalling(self):
        fast_route("remember that my editor is VS Code")
        fast_route("remember for project Blood Bridge that the deadline is Friday")
        fast_route("remember that my favourite browser is Firefox")
        assert fast_route("what do you remember about the deadline?") == "project Blood Bridge: deadline: Friday."
        assert fast_route("what do you know about project blood bridge") == "Project Blood Bridge: deadline: Friday."
        assert fast_route("what are my preferences") == "Your preferences: browser: Firefox."
        assert fast_route("what do you remember") == memory.recall()

    def test_updating_and_forgetting(self, asked):
        fast_route("remember that my editor is VS Code")
        assert fast_route("remember that my editor is Neovim") == "Updated: my editor is now Neovim (it was VS Code)."
        assert fast_route("forget my editor") == "Forgotten: my editor."
        fast_route("remember for project QuantDesk that broker is paper")
        assert fast_route("forget broker from project QuantDesk") == "Forgotten: broker for QuantDesk."
        fast_route("remember for project QuantDesk that broker is paper")
        asked["said"] = True
        assert fast_route("forget project QuantDesk") == "Forgotten: everything for QuantDesk (1 thing)."

    @pytest.mark.parametrize("command", ["forget it", "forget that", "forget everything",
                                         "forget about the previous plan and write me a short poem instead"])
    def test_what_isnt_a_name_goes_on_to_the_model(self, command):
        assert fast_route(command) is None

    def test_no_preferences_yet(self):
        assert fast_route("show my preferences").startswith("You haven't told me any preferences yet.")


# ============================================================ reaching it

class TestReachingIt:
    def test_the_tools(self):
        assert FUNCTIONS["forget"] is memory.forget_anything
        for name in ("recall_memory", "remember_preference", "remember_for_project", "recall_project",
                     "forget_for_project", "note_for_task"):
            assert name in FUNCTIONS
        described = {t["name"]: t["description"] for t in TOOL_SCHEMAS}
        assert "are refused" in described["remember"]
        assert "gone when the task is over" in described["note_for_task"]

    @pytest.fixture
    def api(self, monkeypatch):
        class Quiet:
            muted, running, brain = True, False, None
        monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
        return bridge.Api(assistant=Quiet())

    def test_the_memory_section_gets_every_tier(self, api):
        memory.remember("editor", "VS Code")
        memory.set_preference("browser", "Firefox")
        memory.remember_for_project("Blood Bridge", "deadline", "Friday")
        seen = api.memory_view()
        assert seen["facts"] == [{"key": "editor", "value": "VS Code"}]
        assert seen["preferences"] == [{"key": "browser", "value": "Firefox"}]
        assert seen["projects"] == [{"name": "Blood Bridge", "facts": [{"key": "deadline", "value": "Friday"}]}]

    def test_forget_from_the_section_by_exact_key_and_place(self, api):
        memory.set_preference("browser", "Firefox")
        memory.remember_for_project("Blood Bridge", "deadline", "Friday")
        assert api.forget_fact("browser") == {"error": "I had nothing stored under that."}, "not a fact"
        assert api.forget_fact("deadline", "project", "blood bridge") == {"error": "I had nothing stored under that."}
        assert api.forget_fact("browser", "preference") == {"message": "Forgotten: your preference for browser."}
        assert api.forget_fact("deadline", "project", "Blood Bridge") == {"message": "Forgotten: deadline for Blood Bridge."}


import _ui  # noqa: E402

MEMORY = """() => ({
  calls: window.__calls, count: document.getElementById('memFactsCount').textContent,
  rows: [...document.querySelectorAll('#memFacts .mem-row')].map(r => r.querySelector('.mem-what').textContent),
  tags: [...document.querySelectorAll('#memFacts .mem-tag')].map(t => t.textContent),
  status: document.getElementById('memStatus').textContent,
})"""


class TestTheMemorySection:
    @pytest.fixture(autouse=True)
    def browser_ok(self):
        if not _ui.available():
            pytest.skip("Playwright isn't installed")

    def _render(self, check, snapshot, answers=""):
        opening = {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}
        extra = "window.__memory = %s;%s" % (json.dumps(snapshot), answers)
        result, errors = _ui.open_panel(check, script=_ui.bridge(opening) + extra, route="memory")
        if result is _ui.NO_BROWSER:
            pytest.skip("no browser to render the panel with")
        assert errors == [], errors
        return result

    SNAPSHOT = {"facts": [{"key": "editor", "value": "VS Code"}],
                "preferences": [{"key": "browser", "value": "Firefox"}],
                "projects": [{"name": "Blood Bridge", "facts": [{"key": "deadline", "value": "Friday"}]}],
                "contacts": [], "log": {"count": 0, "keep": 200, "recent": []},
                "resume": {"ready": False, "name": "", "skills": 0, "projects": 0},
                "jobs": {"total": 0, "applied": 0}, "folder": "D:/little/memory"}

    def test_each_tier_is_listed_and_tagged(self):
        seen = self._render(lambda page: page.evaluate(MEMORY), self.SNAPSHOT)
        assert seen["rows"] == ["editorVS Code", "browserFirefoxPreference", "deadlineFridayProject · Blood Bridge"]
        assert seen["tags"] == ["Preference", "Project · Blood Bridge"] and seen["count"] == "3"

    def test_forget_names_the_place(self):
        async def check(page):
            await page.click('[data-key="proj-Blood Bridge-deadline"]')
            await page.wait_for_timeout(750)
            await page.click('#memFacts .btn--caution')
            await page.wait_for_timeout(100)
            await page.click('[data-key="pref-browser"]')
            await page.wait_for_timeout(750)
            await page.click('#memFacts .btn--caution')
            await page.wait_for_timeout(100)
            return await page.evaluate(MEMORY)

        seen = self._render(check, self.SNAPSHOT,
                            "window.__answers = {forget_fact: {message: 'Forgotten: deadline for Blood Bridge.'}};")
        assert ["forget_fact", "deadline", "project", "Blood Bridge"] in seen["calls"]
        assert ["forget_fact", "browser", "preference", None] in seen["calls"]

    def test_an_older_snapshot_without_tiers_still_shows_facts(self):
        older = {k: v for k, v in self.SNAPSHOT.items() if k not in ("preferences", "projects")}
        seen = self._render(lambda page: page.evaluate(MEMORY), older)
        assert seen["rows"] == ["editorVS Code"] and seen["tags"] == []
