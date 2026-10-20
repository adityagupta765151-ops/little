"""Chapter 45 — test expansion: the edges and properties the chapters left thin.

Router (English and Hinglish), tools, fallback, the browser's error words,
scoring, parsers, memory, the planner, permissions, the dashboard, the wake
word, configuration and recovery — each pushed with awkward, random or
hostile input. Random inputs use fixed seeds, so a failure repeats.
And a guard: the number of tests may only go up.
"""
from __future__ import annotations

import random
import re
import string
from pathlib import Path

import pytest

from jarvis import tools
from jarvis.ai import planner, provider
from jarvis.app import config, latency, overview, recovery
from jarvis.jobs import matching, normalise, resume
from jarvis.routing import router
from jarvis.store import knowledge, memory
from jarvis.tools import browser, catalog, permissions, registry
from jarvis.voice import wake

RNG = random.Random(4512)


def junk(n=40, alphabet=string.printable + "हिंदीअआ→—“”\x00\x07"):
    return "".join(RNG.choice(alphabet) for _ in range(RNG.randint(0, n)))


JUNK = [junk() for _ in range(60)] + ["", " ", "\n\n", "{", "}", "{}", "[]", "null", "{\"a\":", "\x00" * 5]


# ================================================================== router

class TestRouterHinglish:
    @pytest.fixture
    def stubbed(self, monkeypatch):
        calls = []

        def stub(owner, name):
            monkeypatch.setattr(owner, name, lambda *a, **_k: calls.append((name, a)) or f"<{name}>")
        stub(router.apps, "open_app")
        stub(router.apps, "close_app")
        stub(router.browser, "close_browser")
        stub(router.browser, "read_page")
        stub(router.screen, "describe_screen")
        stub(router.health, "system_check")
        stub(router.jobs, "top_matches")
        monkeypatch.setattr(router, "_open_url", lambda url, said: calls.append(("open_url", (url,))) or said)
        return calls

    @pytest.mark.parametrize("said,expect", [
        ("chrome kholo", ("open_app", ("chrome",))),
        ("notepad khol do", ("open_app", ("notepad",))),
        ("chrome band karo", ("close_app", ("chrome",))),
        ("browser band karo", ("close_browser", ())),
        ("page padho", ("read_page", ())),
        ("screen par kya hai", ("describe_screen", ())),
        ("sab thik hai?", ("system_check", ())),
    ])
    def test_the_verb_after_the_thing(self, stubbed, said, expect):
        router.fast_route(said)
        assert stubbed[0][0] == expect[0] and stubbed[0][1][:len(expect[1])] == expect[1]

    def test_dhundo_searches(self, stubbed):
        assert router.fast_route("dhundo python internships") == "Searching for python internships."

    @pytest.mark.parametrize("said", ["time kya hai", "time kya h", "aaj ki date"])
    def test_clock(self, said):
        assert router.fast_route(said).startswith(("It's", "Today is"))

    @pytest.mark.parametrize("said", JUNK)
    def test_anything_at_all_is_answered_or_passed_on_never_crashes(self, said, monkeypatch):
        monkeypatch.setattr(router.apps, "open_app", lambda *_a: "<open>")
        monkeypatch.setattr(router.apps, "close_app", lambda *_a: "<close>")
        monkeypatch.setattr(router, "_open_url", lambda *_a: "<url>")
        result = router.fast_route(said)
        assert result is None or isinstance(result, str)

    @pytest.mark.parametrize("said", ["what is the meaning of life", "write a poem about rain",
                                      "explain recursion to me", "koi achhi movie batao"])
    def test_open_questions_go_to_the_model(self, said):
        assert router.fast_route(said) is None


# ================================================================== tools

class TestTools:
    @pytest.mark.parametrize("name", sorted(registry.FUNCTIONS))
    def test_every_tool_survives_nonsense_arguments(self, name, monkeypatch, refuse):
        # Nothing opens, sends, runs or asks for real: every gate says no, the
        # browser and apps are stood in for.
        monkeypatch.setattr(browser._worker, "run", lambda job: "<browser>")
        monkeypatch.setattr(registry.apps, "open_app", lambda *_a: "<open>", raising=False)
        monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)
        said = registry.execute_tool(name, {"zzz_not_an_argument": 1})
        assert isinstance(said, str) and said

    def test_every_described_parameter_type_is_one_the_model_knows(self):
        known = {"string", "integer", "number", "boolean"}
        for schema in registry.TOOL_SCHEMAS:
            for prop in schema["input_schema"]["properties"].values():
                assert prop.get("type") in known, schema["name"]

    def test_timeouts_and_levels_are_sane(self):
        for tool in catalog.tools():
            assert 1 <= tool.timeout <= 900 and tool.permission in permissions.ORDER


# ================================================================ fallback

class TestFallback:
    def test_fallback_models_are_distinct_and_named(self):
        assert provider.FALLBACK_MODELS and len(set(provider.FALLBACK_MODELS)) == len(provider.FALLBACK_MODELS)
        assert all(re.fullmatch(r"[a-z0-9.\-]+", m) for m in provider.FALLBACK_MODELS)

    @pytest.mark.parametrize("text", ["", "x", "{}"])
    def test_an_answer_with_no_candidates_is_empty_text(self, text):
        assert provider._text_of({}) == "" and provider._text_of({"candidates": []}) == ""


# ================================================================= browser

class TestBrowserWords:
    @pytest.mark.parametrize("error,said", [
        (TimeoutError("Timeout 20000ms exceeded"), "The page took too long to respond."),
        (RuntimeError("net::ERR_NAME_NOT_RESOLVED at https://x"), "That address doesn't exist."),
        (RuntimeError("net::ERR_INTERNET_DISCONNECTED"), "I can't reach the internet right now."),
        (RuntimeError("Browser has been closed"), "The browser window was closed."),
        (RuntimeError("something odd"), "The browser hit a problem: something odd"),
    ])
    def test_each_error_in_words(self, error, said):
        assert browser._friendly(error).startswith(said)

    @pytest.mark.parametrize("url,tidy", [("example.com", "https://example.com"), (" http://x.org ", "http://x.org"),
                                          ("https://a.b/c?d=e", "https://a.b/c?d=e")])
    def test_addresses_are_tidied(self, url, tidy):
        assert browser._tidy(url) == tidy


# ================================================================= scoring

PROFILE = {"candidate": {"name": "A", "skills": ["Python", "React", "Node.js", "SQL"], "languages": [],
                         "frameworks": [], "experience": [], "internships": [], "projects": ["P - Python"],
                         "degree": "B.Tech", "education": [], "location": "Pune, India"},
           "preferences": {"roles": ["backend developer"]}}


class TestScoring:
    @pytest.mark.parametrize("seed", range(25))
    def test_every_score_is_between_0_and_100_and_repeatable(self, seed):
        rng = random.Random(seed)
        words = ["Python", "Java", "senior", "intern", "remote", "Pune", "React", "10 years", "PhD", "Kubernetes",
                 "backend", "sales", "", "मुंबई", "C++", "Go"]
        job = {"title": " ".join(rng.choice(words) for _ in range(3)), "company": "Co",
               "description": " ".join(rng.choice(words) for _ in range(rng.randint(0, 40))),
               "location": rng.choice(["Pune, India", "Remote", "", "Berlin, Germany"])}
        first = matching.score_job(dict(job), PROFILE)
        second = matching.score_job(dict(job), PROFILE)
        assert 0 <= first["match_score"] <= 100 and first["match_score"] == second["match_score"]

    def test_more_of_your_skills_never_scores_lower(self):
        base = {"title": "Backend developer", "company": "Co", "location": "Pune, India",
                "description": "We use Python."}
        more = dict(base, description="We use Python, React, Node.js and SQL.")
        assert matching.score_job(dict(more), PROFILE)["match_score"] >= \
            matching.score_job(dict(base), PROFILE)["match_score"]


# ================================================================= parsers

class TestParsers:
    @pytest.mark.parametrize("raw", JUNK)
    def test_dates_never_crash(self, raw):
        out = normalise.parse_date(raw)
        assert out == "" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", out)

    @pytest.mark.parametrize("raw,day", [("2026-09-01T10:00:00Z", "2026-09-01"), ("2026-09-01", "2026-09-01"),
                                         (None, ""), ("", ""), ("not a date", "")])
    def test_known_dates(self, raw, day):
        assert normalise.parse_date(raw) == day

    @pytest.mark.parametrize("raw", JUNK + ["```json\n{\"a\": 1}\n```", "Sure! {\"a\": 1} done"])
    def test_resume_json_never_crashes(self, raw):
        out = resume._parse_json(raw)
        assert out is None or isinstance(out, (dict, list, int, float, str))

    def test_fenced_json_is_read(self):
        assert resume._parse_json("```json\n{\"a\": 1}\n```") == {"a": 1}

    @pytest.mark.parametrize("raw", JUNK)
    def test_plans_never_crash(self, raw):
        goal, steps = planner._parse_plan(raw)
        assert isinstance(goal, str) and isinstance(steps, list) and len(steps) <= planner.MAX_STEPS


# ================================================================== memory

class TestMemoryProperties:
    @pytest.mark.parametrize("text", JUNK + ["my password is hunter2", "AIzaSyA1234567890abcdefghijklmn"])
    def test_redacting_twice_is_redacting_once(self, text):
        once = memory.redact(text)
        assert memory.redact(once) == once

    @pytest.mark.parametrize("text", ["call rahul at +91 98765 43210 tomorrow", "pin code 211001", "order 12345",
                                      "meet at 10:30 in room 4B", "version 3.11.2"])
    def test_ordinary_text_is_left_alone(self, text):
        assert memory.redact(text) == text

    @pytest.mark.parametrize("seed", range(10))
    def test_chunks_lose_no_words(self, seed):
        rng = random.Random(seed)
        paragraphs = ["\n".join(" ".join(f"w{rng.randint(0, 9999)}" for _ in range(rng.randint(1, 60)))
                                for _ in range(rng.randint(1, 3))) for _ in range(rng.randint(1, 30))]
        text = "\n\n".join(paragraphs)
        joined = " ".join(p["text"] for p in knowledge.chunk([(None, text)]))
        assert set(text.split()) <= set(joined.split())


# ============================================================= permissions

class TestPermissionProperties:
    @pytest.mark.parametrize("answer", [True, False, None, 0, 1, "yes", "True", [], {}, object()])
    def test_confirm_is_always_a_bool_and_only_true_is_yes(self, answer):
        tools.set_confirm(lambda _m: answer)
        try:
            got = tools.confirm("ok?")
        finally:
            tools.set_confirm(lambda _m: False)
        assert got is (answer is True)

    def test_a_dialog_that_raises_is_not_a_yes(self):
        def broken(_m):
            raise RuntimeError("the window went away")
        tools.set_confirm(broken)
        try:
            with pytest.raises(RuntimeError):
                tools.confirm("ok?")
        finally:
            tools.set_confirm(lambda _m: False)


# =============================================================== dashboard

class TestDashboardProperties:
    def test_all_eleven_even_when_every_reader_fails(self, monkeypatch):
        monkeypatch.setattr(overview, "SECTIONS", tuple((i, (lambda: 1 / 0)) for i, _ in overview.SECTIONS))
        monkeypatch.setattr(overview, "_voice", lambda _a: 1 / 0)
        found = overview.snapshot()
        assert len(found) == 11 and all(s["state"] == "off" for s in found)
        assert overview.report().count("\n") == 9, "ten sections in words, logs left to the screen"


# ================================================================ wake word

class TestWakeProperties:
    @pytest.mark.parametrize("text", JUNK)
    def test_never_crashes_and_ends_inside_the_text(self, text):
        end = wake.wake_position(text)
        assert end is None or 0 < end <= len(text)

    @pytest.mark.parametrize("text", ["a little bit", "wait a little", "so little time", "little by little it grew",
                                      "the title of the song", "i need a little help"])
    def test_little_in_a_sentence_never_wakes_it(self, text):
        assert wake.wake_position(text) is None

    @pytest.mark.parametrize("text", ["little", "hey little", "ok little open chrome", "jarvis", "hey jarvis",
                                      "javis what time is it"])
    def test_its_name_first_does(self, text):
        assert wake.wake_position(text) is not None


# =================================================================== config

class TestConfig:
    @pytest.mark.parametrize("raw,shape,default,want", [
        ("+10%", "_PERCENT", "+5%", "+10%"), ("fast", "_PERCENT", "+5%", "+5%"), ("", "_PERCENT", "+5%", "+5%"),
        ("-20Hz", "_HERTZ", "+10Hz", "-20Hz"), ("20", "_HERTZ", "+10Hz", "+10Hz"), ("+1000%", "_PERCENT", "+5%", "+5%"),
    ])
    def test_voice_settings_keep_their_shape(self, monkeypatch, raw, shape, default, want):
        monkeypatch.setenv("JARVIS_TEST_SETTING", raw)
        assert config._setting("JARVIS_TEST_SETTING", default, getattr(config, shape)) == want

    @pytest.mark.parametrize("raw,has", [("", "jarvis"), ("hey buddy, buddy", "buddy"), (" , ,", "jarvis")])
    def test_wake_words(self, monkeypatch, raw, has):
        monkeypatch.setenv("JARVIS_WAKE", raw)
        words = config._wake_words()
        assert has in words and config.ASSISTANT_CALL.lower() in words and all(w == w.strip().lower() for w in words)

    def test_the_tests_never_touch_real_folders(self):
        assert "jarvis-tests" in str(config.MEMORY_DIR) or "tmp" in str(config.MEMORY_DIR)


# ================================================================= recovery

class TestRecoveryProperties:
    @pytest.mark.parametrize("error,passing", [
        (TimeoutError(), True), (ConnectionError(), True), (OSError("Connection reset by peer"), True),
        (RuntimeError("server busy, try again"), True), (ValueError("bad value"), False),
        (KeyError("degree"), False), (ZeroDivisionError(), False), (PermissionError("denied"), False),
    ])
    def test_what_counts_as_passing(self, error, passing):
        assert recovery.transient(error) is passing

    @pytest.mark.parametrize("seed", range(5))
    def test_percentiles_are_ordered(self, seed):
        rng = random.Random(seed)
        latency.reset()
        for _ in range(rng.randint(1, 150)):
            latency.record("ai", rng.random() * 5000)
        s = latency.summary()["ai"]
        assert s["p50"] <= s["p95"] <= s["max"]
        latency.reset()


# ============================================================ the count guard

BASELINE = Path(__file__).with_name("TEST_BASELINE")


def _count_test_functions() -> int:
    total = 0
    for path in Path(__file__).parent.glob("test_*.py"):
        total += len(re.findall(r"^\s*(?:async\s+)?def test_", path.read_text(encoding="utf-8"), re.M))
    return total


class TestTheCountOnlyGoesUp:
    def test_no_test_was_taken_away(self):
        """TEST_BASELINE holds the number of test functions at the last
        chapter's end. Fewer now means a test was deleted: put it back, or
        say why in the plan and lower the number on purpose."""
        baseline = int(BASELINE.read_text(encoding="utf-8").split()[0])
        assert _count_test_functions() >= baseline
