"""LITTLE: the name, the wake word, the voice, and what gets said aloud.

The rename is mostly strings, and strings are easy to get right. What these
tests guard is the part that isn't: a new name that is an everyday English
word, an .env from the old name that pins the old voice and wake word, and
a voice that has to stay short without the screen losing anything.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from jarvis.app import config
from jarvis.voice import brief, speaking
from jarvis.voice.wake import wake_position

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ name

class TestTheName:
    def test_the_assistant_is_called_little(self):
        assert config.ASSISTANT_NAME == "LITTLE"
        assert config.ASSISTANT_CALL == "Little"

    def test_the_name_can_be_changed_in_settings(self, monkeypatch):
        monkeypatch.setenv("JARVIS_ASSISTANT_NAME", "nova")
        import importlib
        fresh = importlib.reload(config)
        try:
            assert fresh.ASSISTANT_NAME == "NOVA"
            assert "nova" in fresh.WAKE_WORDS
        finally:
            monkeypatch.delenv("JARVIS_ASSISTANT_NAME")
            importlib.reload(config)

    def test_the_package_and_settings_kept_their_names(self):
        """Renaming these would break every existing install and .env."""
        import jarvis
        assert jarvis.__name__ == "jarvis"
        assert config.LOG_FILE.name == "jarvis.log"
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "JARVIS_VOICE=" in example and "JARVIS_WORKSPACE=" in example


# ------------------------------------------------------------- wake word

class TestTheWakeWord:
    def test_its_own_name_comes_first(self):
        assert config.WAKE_WORDS[:4] == ["hey little", "ok little", "okay little", "little"]

    def test_the_old_name_still_wakes_it(self):
        assert "jarvis" in config.WAKE_WORDS
        assert wake_position("jarvis open chrome") is not None
        assert wake_position("hey jarvis what time is it") is not None

    def test_an_env_pinned_to_the_old_name_cannot_make_it_deaf_to_the_new_one(self, monkeypatch):
        """An .env copied from the JARVIS template sets JARVIS_WAKE to the
        old name only. The new name has to work anyway."""
        monkeypatch.setenv("JARVIS_WAKE", "hey jarvis,jarvis,jervis")
        words = config._wake_words()
        assert "little" in words and "hey little" in words
        assert "jarvis" in words

    @pytest.mark.parametrize("said", [
        "little open chrome",
        "hey little what is the time",
        "ok little set a reminder for 8",
        "okay little",
        "little",
        "um little find jobs for me",
        "so hey little open youtube",
    ])
    def test_being_addressed_wakes_it(self, said):
        assert wake_position(said) is not None, f"{said!r} should wake it"

    @pytest.mark.parametrize("said", [
        "i need a little help",
        "a little bit louder please",
        "wait a little",
        "there was a little dog outside",
        "what does little mean",
        "the title of the song",
        "title of the song",
        "litter box is full",
        "middle of the night",
    ])
    def test_everyday_speech_does_not(self, said):
        """"Little" is an ordinary word. An assistant that woke on every
        sentence containing it would be answering the room all day."""
        assert wake_position(said) is None, f"{said!r} should not wake it"

    def test_a_mishearing_of_its_own_name_still_counts(self):
        assert wake_position("littl open youtube") is not None

    def test_its_own_name_needs_a_closer_match_than_the_old_one(self):
        """Speech recognition spells "little" right every time, so a loose
        match only adds false wakes. "Jarvis" gets mangled, so it keeps the
        forgiving match it always had."""
        from jarvis.voice import wake
        assert wake._cutoff("little") >= 0.85
        assert wake._cutoff("jarvis") == wake.FUZZY

    def test_the_command_after_the_name_is_what_runs(self):
        said = "hey little open chrome"
        assert said[wake_position(said):].strip() == "open chrome"


# --------------------------------------------------------- typed commands

class TestTypedAddress:
    @pytest.mark.parametrize("typed,expected", [
        ("Little, find jobs for me", "find jobs for me"),
        ("little open chrome", "open chrome"),
        ("Hey Little, what is the time", "what is the time"),
        ("LITTLE: show my top matches", "show my top matches"),
        ("Jarvis, find jobs for me", "find jobs for me"),    # the old name, still
    ])
    def test_the_name_is_stripped_before_routing(self, typed, expected):
        from jarvis.app.assistant import strip_address
        assert strip_address(typed) == expected

    def test_a_question_about_the_word_is_left_alone(self):
        from jarvis.app.assistant import strip_address
        assert strip_address("what does little mean") == "what does little mean"

    def test_a_typed_address_reaches_the_fast_lane(self):
        from jarvis.app.assistant import strip_address
        from jarvis.routing.router import fast_route
        assert fast_route(strip_address("Little, what is the time")) is not None


# ------------------------------------------------------------------ voice

class TestVoiceSettings:
    def test_little_speaks_with_a_light_indian_english_voice(self):
        assert config.DEFAULT_VOICE == "en-IN-NeerjaNeural"
        assert config.DEFAULT_PITCH.startswith("+")        # lifted, not deepened

    def test_every_setting_is_exposed(self):
        for name in ("VOICE", "VOICE_SPEED", "VOICE_PITCH", "VOICE_VOLUME",
                     "VOICE_ENABLED", "ASSISTANT_NAME"):
            assert hasattr(config, name)

    @pytest.mark.parametrize("name,bad,default,shape", [
        ("JARVIS_VOICE_SPEED", "fast", config.DEFAULT_SPEED, config._PERCENT),
        ("JARVIS_VOICE_PITCH", "+10", config.DEFAULT_PITCH, config._HERTZ),
        ("JARVIS_VOICE_VOLUME", "loud", config.DEFAULT_VOLUME, config._PERCENT),
    ])
    def test_a_malformed_setting_falls_back_instead_of_silencing_it(self, monkeypatch,
                                                                     name, bad, default, shape):
        monkeypatch.setenv(name, bad)
        assert config._setting(name, default, shape) == default

    @pytest.mark.parametrize("name,good,shape", [
        ("JARVIS_VOICE_SPEED", "-10%", config._PERCENT),
        ("JARVIS_VOICE_PITCH", "+20Hz", config._HERTZ),
        ("JARVIS_VOICE_VOLUME", "+15%", config._PERCENT),
    ])
    def test_a_well_formed_setting_is_used(self, monkeypatch, name, good, shape):
        monkeypatch.setenv(name, good)
        assert config._setting(name, "+0%", shape) == good

    def test_a_blank_setting_means_the_default(self, monkeypatch):
        monkeypatch.setenv("JARVIS_VOICE_PITCH", "")
        assert config._setting("JARVIS_VOICE_PITCH", "+10Hz", config._HERTZ) == "+10Hz"

    def test_the_local_voice_volume_follows_the_setting(self, monkeypatch):
        monkeypatch.setattr(speaking, "NEURAL_VOLUME", "-30%")
        assert speaking._local_volume() == pytest.approx(0.7)
        monkeypatch.setattr(speaking, "NEURAL_VOLUME", "+0%")
        assert speaking._local_volume() == 1.0

    def test_voice_can_start_switched_off(self, monkeypatch):
        from jarvis.app import assistant
        monkeypatch.setattr(assistant, "VOICE_ENABLED", False)
        bot = assistant.Jarvis(log_fn=lambda *_: None)
        assert bot.muted is True


class TestVoiceFallback:
    """A voice name that doesn't exist must not leave the assistant mute."""

    @pytest.fixture(autouse=True)
    def fresh(self, monkeypatch):
        monkeypatch.setattr(speaking, "_active_voice", None)

    def test_the_chosen_voice_is_tried_first(self):
        assert speaking._voice_chain()[0] == speaking.NEURAL_VOICE

    def test_a_voice_that_fails_hands_over_to_the_next(self, monkeypatch, tmp_path):
        tried = []

        def fake(text, path, voice=None):
            tried.append(voice)
            return voice != "en-XX-NoSuchVoiceNeural"

        monkeypatch.setattr(speaking, "NEURAL_VOICE", "en-XX-NoSuchVoiceNeural")
        monkeypatch.setattr(speaking, "_synthesise", fake)
        assert speaking._synthesise_any("hello", tmp_path / "x.mp3") is True
        assert tried[0] == "en-XX-NoSuchVoiceNeural"
        assert speaking._active_voice == speaking.FALLBACK_VOICES[0]

    def test_the_working_voice_is_remembered(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(speaking, "_active_voice", "en-US-JennyNeural")
        monkeypatch.setattr(speaking, "_synthesise",
                            lambda text, path, voice=None: calls.append(voice) or True)
        speaking._synthesise_any("hello", tmp_path / "x.mp3")
        assert calls == ["en-US-JennyNeural"]

    def test_it_gives_up_after_three_rather_than_hanging_on_the_network(self, monkeypatch,
                                                                          tmp_path):
        calls = []
        monkeypatch.setattr(speaking, "_synthesise",
                            lambda text, path, voice=None: calls.append(voice) or False)
        assert speaking._synthesise_any("hello", tmp_path / "x.mp3") is False
        assert len(calls) <= 3

    def test_the_report_names_the_settings_and_checks_the_live_list(self, monkeypatch):
        monkeypatch.setattr(speaking, "_live_voices", lambda timeout=6.0: [
            {"ShortName": "en-IN-NeerjaNeural", "Locale": "en-IN", "Gender": "Female",
             "VoiceTag": {"VoicePersonalities": ["Friendly", "Positive"]}},
            {"ShortName": "en-US-GuyNeural", "Locale": "en-US", "Gender": "Male"},
        ])
        report = speaking.voice_report()
        assert "Little" in report
        assert "pitch" in report and "volume" in report
        assert "en-IN-NeerjaNeural" in report and "Friendly" in report
        assert "en-US-GuyNeural" not in report            # Little's list is the light voices

    def test_the_report_warns_when_the_chosen_voice_does_not_exist(self, monkeypatch):
        monkeypatch.setattr(speaking, "NEURAL_VOICE", "en-XX-NoSuchVoiceNeural")
        monkeypatch.setattr(speaking, "_live_voices", lambda timeout=6.0: [
            {"ShortName": "en-IN-NeerjaNeural", "Locale": "en-IN", "Gender": "Female"}])
        assert "isn't a voice Microsoft offers" in speaking.voice_report()

    def test_offline_the_report_says_its_list_is_unchecked(self, monkeypatch):
        monkeypatch.setattr(speaking, "_live_voices", lambda timeout=6.0: None)
        report = speaking.voice_report()
        assert "couldn't check the live list" in report
        assert "en-IN-NeerjaNeural" in report


# --------------------------------------------------------- what is spoken

class TestSpokenReplies:
    @pytest.mark.parametrize("reply", [
        "Opened Chrome.", "Done. I'll remind you at 8.", "Searching for jobs.",
    ])
    def test_a_short_reply_is_said_as_it_is(self, reply):
        assert brief.for_speech(reply) == reply

    def test_a_simple_command_stays_under_ten_words(self):
        assert len(brief.for_speech("Opened WhatsApp.").split()) < 10

    def test_a_long_reply_is_cut_to_two_sentences_and_points_at_the_screen(self):
        long = ("Found 32 jobs for full stack developer. 5 of them are new. "
                "Adzuna was skipped. Jobicy gave four.\nSources: remotive: 18")
        spoken = brief.for_speech(long)
        assert spoken.startswith("Found 32 jobs for full stack developer. 5 of them are new.")
        assert "Adzuna" not in spoken
        assert spoken.endswith(brief.ON_SCREEN)

    def test_one_long_sentence_is_cut_at_a_clause_not_mid_word(self):
        spoken = brief.for_speech(
            "I opened main.py in VS Code and added a function that validates the "
            "email address using a regular expression, then wrote three tests for it "
            "and they all pass now, which you can see in the terminal.")
        body = spoken.replace(" " + brief.ON_SCREEN, "")
        assert len(body) <= brief.MAX_SPOKEN + 1
        assert body.endswith(".")

    def test_a_top_matches_list_is_summed_up_not_read_out(self):
        listing = "Job #1   MATCH 90/100\n  A — B\n\nJob #2   MATCH 80/100\n  C — D"
        assert brief.for_speech(listing) == "Here are your top 2 matches. They're on screen."

    def test_a_health_report_is_summed_up_by_its_verdict(self):
        report = "SYSTEM HEALTH\n---\nRUNTIME ok\n\n1 broken, 2 degraded but working."
        assert brief.for_speech(report) == "System check done. 1 broken, 2 degraded but working."

    def test_a_match_analysis_is_summed_up_by_its_score(self):
        text = "MATCH ANALYSIS\n\nEngineer at Acme — 84/100\n  Skills 75/100"
        assert brief.for_speech(text).startswith("It scores 84 out of 100.")

    def test_links_and_symbols_are_never_read_aloud(self):
        spoken = brief.for_speech("✓ Opened https://example.com/a/very/long/path for you.")
        assert "http" not in spoken and "✓" not in spoken

    def test_the_screen_still_gets_everything(self, monkeypatch):
        """Shortening is for the voice only. The activity log keeps the whole
        reply."""
        from jarvis.app import assistant
        logged, spoken = [], []
        monkeypatch.setattr(assistant, "fast_route",
                            lambda _c: "Job #1   MATCH 90/100\n  A\n\nJob #2   MATCH 80/100\n  B")
        monkeypatch.setattr(assistant, "speak", spoken.append)
        bot = assistant.Jarvis(log_fn=logged.append)
        bot.muted = False
        bot.handle("show my top matches")
        assert any("Job #2" in line for line in logged)
        assert spoken[-1] == "Here are your top 2 matches. They're on screen."

    def test_its_replies_are_marked_with_its_name_in_the_log(self, monkeypatch):
        from jarvis.app import assistant
        logged = []
        monkeypatch.setattr(assistant, "fast_route", lambda _c: "Opened Chrome.")
        bot = assistant.Jarvis(log_fn=logged.append)
        bot.muted = True
        bot.handle("open chrome")
        assert "LITTLE: Opened Chrome." in logged

    def test_goodbye_works_with_either_name(self):
        from jarvis.app.assistant import SLEEP_PHRASES
        assert "goodbye little" in SLEEP_PHRASES
        assert "goodbye jarvis" in SLEEP_PHRASES


# ---------------------------------------------------------------- persona

class TestPersona:
    def test_it_knows_its_name(self):
        from jarvis.ai.prompts import SYSTEM
        assert SYSTEM.startswith("You are Little")

    def test_it_is_told_to_keep_it_short(self):
        from jarvis.ai.prompts import SYSTEM
        assert "under ten words" in SYSTEM
        assert "one or two short" in SYSTEM

    def test_it_is_told_not_to_be_a_movie_ai(self):
        from jarvis.ai.prompts import PERSONA
        assert 'No "Sir"' in PERSONA
        assert "Don't claim feelings" in PERSONA
        assert "not a movie AI" in PERSONA

    def test_the_old_working_rules_survived(self):
        """The persona is new; how it does the job is not. WhatsApp still
        drafts before it sends."""
        from jarvis.ai.prompts import SYSTEM
        assert "draft_whatsapp_message first" in SYSTEM
        assert "read it first" in SYSTEM

    def test_the_tools_no_longer_describe_themselves_as_jarvis(self):
        from jarvis.tools.registry import TOOL_SCHEMAS
        for schema in TOOL_SCHEMAS:
            assert "JARVIS" not in schema["description"], schema["name"]


# --------------------------------------------------------------- the panel

class TestThePanel:
    def _read(self, *parts):
        return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")

    def test_the_main_panel_is_little(self):
        html = self._read("ui", "index.html")
        assert "<title>LITTLE</title>" in html
        assert "J.A.R.V.I.S" not in html
        assert 'aria-label="Activate Little"' in html

    def _all_css(self):
        """The panel's styles are split into a design system (ui/css/) and
        the page's own layout (ui/app.css); read them as one."""
        return "\n".join(p.read_text(encoding="utf-8")
                         for p in sorted((ROOT / "ui").glob("**/*.css"))
                         if "jobs" not in p.parts)

    def test_the_panel_has_a_face_that_follows_the_state(self):
        html = self._read("ui", "index.html")
        css = self._all_css()
        assert 'class="face"' in html and "eye-l" in html and "eye-r" in html
        for state in ("offline", "listening", "thinking", "speaking"):
            assert f'body[data-state="{state}"] .face' in css

    def test_the_face_respects_reduced_motion(self):
        assert "prefers-reduced-motion" in self._all_css()

    def test_no_screen_still_tells_you_to_say_jarvis(self):
        for parts in (("ui", "app.js"), ("ui", "index.html"),
                      ("ui", "jobs", "app.js"), ("ui", "jobs", "index.html")):
            text = self._read(*parts)
            assert "Hey Jarvis" not in text
            assert "Tell JARVIS" not in text
            assert "J.A.R.V.I.S" not in text

    def test_old_log_lines_still_show_as_replies(self):
        """A log written before the rename says "JARVIS: ...". The panel
        reads both prefixes, so history doesn't turn into anonymous notes."""
        js = self._read("ui", "app.js")
        assert '"JARVIS: "' in js and 'NAME + ": "' in js

    def test_the_jobs_dashboard_is_little(self):
        html = self._read("ui", "jobs", "index.html")
        assert "<title>LITTLE · Job Hunter</title>" in html

    def test_the_panel_is_told_the_name_and_voice(self):
        from jarvis.app import stats

        class Idle:
            running = False

        snap = stats.snapshot(Idle(), muted=False)
        assert snap["identity"] == {"name": "LITTLE", "call": "Little"}
        assert snap["voice"]["voice"] == "Neerja"

    def test_the_jobs_dashboard_is_told_the_name(self):
        from jarvis.jobs import dashboard
        assert dashboard.state()["assistant"] == "LITTLE"


# ---------------------------------------------------------------- health

class TestTheOldVoiceIsNoticed:
    def test_an_env_still_on_the_old_voice_gets_a_nudge(self, monkeypatch):
        from jarvis.app import health
        monkeypatch.setattr(health, "_importable", lambda name: True)
        monkeypatch.setattr(config, "VOICE", config.OLD_VOICE)
        check = health.check_voice_out()
        assert check.state == health.WARN
        assert config.DEFAULT_VOICE in check.fix
        assert "ignore" in check.fix                       # a nudge, not an order

    def test_the_new_voice_gets_no_nudge(self, monkeypatch):
        from jarvis.app import health
        monkeypatch.setattr(health, "_importable", lambda name: True)
        monkeypatch.setattr(config, "VOICE", config.DEFAULT_VOICE)
        assert health.check_voice_out().state == health.OK

    def test_health_messages_use_the_new_name(self):
        source = (ROOT / "jarvis" / "app" / "health.py").read_text(encoding="utf-8")
        assert not re.search(r'"JARVIS (needs|may)', source)


# ----------------------------------------------------------- the shortcut

class TestTheDesktopShortcut:
    """make_shortcut.ps1 names its target and icon by filename. Rename one
    and not the other, and the shortcut points at nothing — which only shows
    up on the desktop of someone setting it up."""

    def test_every_file_the_shortcut_points_at_exists(self):
        script = (ROOT / "make_shortcut.ps1").read_text(encoding="utf-8")
        named = re.findall(r'Join-Path \$here "([^"]+)"', script)
        assert named, "the shortcut script names no files"
        for name in named:
            assert (ROOT / name).exists(), f"make_shortcut.ps1 points at missing {name}"

    def test_the_shortcut_is_little(self):
        script = (ROOT / "make_shortcut.ps1").read_text(encoding="utf-8")
        assert '"LITTLE.lnk"' in script
        assert "start_little.vbs" in script
