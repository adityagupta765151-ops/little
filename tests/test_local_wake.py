"""Chapter 34 — hearing its name on this computer.

With pocketsphinx, each phrase is checked here for the name first; one
without it is dropped here and never sent to the speech service. One that
passes still has to open with the name in the cloud's transcript before
anything runs. Without pocketsphinx — or when the offline check fails — it
listens exactly as it did. These run on a stand-in recogniser and
microphone; nothing here uses a real one.
"""
from __future__ import annotations

import types

import pytest

from jarvis.app import assistant, settings, tasks
from jarvis.routing.router import fast_route
from jarvis.voice import listening, local_wake, wake


class UnknownValueError(Exception):
    """What SpeechRecognition raises when it makes out nothing."""


class Recogniser:
    """Stands in for speech_recognition.Recognizer. Audio is a dict saying
    what the offline check spots and what the cloud transcribes."""

    def __init__(self):
        self.sphinx, self.google = [], []

    def recognize_sphinx(self, audio, keyword_entries=None):
        self.sphinx.append(keyword_entries)
        if "offline_error" in audio:
            raise RuntimeError(audio["offline_error"])
        if not audio.get("spots"):
            raise UnknownValueError()
        return audio["spots"]

    def recognize_google(self, audio, language=None):
        self.google.append(audio)
        if audio.get("says") is None:
            raise UnknownValueError()
        return audio["says"]


@pytest.fixture
def installed(monkeypatch):
    monkeypatch.setattr(local_wake, "installed", lambda: True)


@pytest.fixture
def ear(installed, monkeypatch):
    """A Listener with a stand-in microphone that plays `phrases` in turn."""
    fake_sr = types.SimpleNamespace(UnknownValueError=UnknownValueError, RequestError=ConnectionError,
                                    WaitTimeoutError=TimeoutError)
    monkeypatch.setattr(listening, "sr", fake_sr)
    made = object.__new__(listening.Listener)
    made.recognizer = Recogniser()
    made.phrases = []
    made._record = lambda timeout, phrase_limit: made.phrases.pop(0) if made.phrases else None
    made.wake = local_wake.LocalWake(made.recognizer, mode="auto", sensitivity=0.6)
    made.kept_here = False
    return made


# ================================================================ hearing

class TestTheNameIsCheckedHereFirst:
    def test_a_phrase_without_the_name_never_leaves_this_computer(self, ear):
        ear.phrases = [{"spots": "", "says": "pass me the salt"}]
        assert ear.listen(wake=True) is None and ear.kept_here
        assert ear.recognizer.google == [], "nothing sent to be transcribed"

    def test_a_phrase_with_it_is_transcribed_and_confirmed(self, ear):
        ear.phrases = [{"spots": "little ", "says": "little what's the time"}]
        assert ear.listen(wake=True) == "little what's the time" and not ear.kept_here
        assert ear.wake.counts["confirmed"] == 1

    def test_a_false_alarm_here_is_caught_by_the_transcript(self, ear, monkeypatch):
        ear.phrases = [{"spots": "little", "says": "a little bit more salt"}]
        heard = ear.listen(wake=True)
        assert wake.wake_position(heard) is None, "the loop still won't act on it"
        assert ear.wake.counts["rejected"] == 1

    def test_it_asks_only_for_its_real_names(self, ear):
        ear.phrases = [{"spots": "", "says": "x"}]
        ear.listen(wake=True)
        (entries,) = ear.recognizer.sphinx
        assert entries == [("jarvis", 0.6), ("little", 0.6)], "misspellings are for the cloud, not the dictionary"

    def test_a_command_after_yes_is_not_gated(self, ear):
        ear.phrases = [{"spots": "", "says": "open chrome"}]
        assert ear.listen() == "open chrome" and ear.recognizer.sphinx == []

    def test_silence_is_silence(self, ear):
        assert ear.listen(wake=True) is None and not ear.kept_here


class TestFallingBack:
    def test_without_pocketsphinx_it_listens_as_before(self, ear, monkeypatch):
        monkeypatch.setattr(local_wake, "installed", lambda: False)
        ear.phrases = [{"spots": "", "says": "little open chrome"}]
        assert ear.listen(wake=True) == "little open chrome" and ear.recognizer.sphinx == []
        assert ear.wake.why_not() == "pocketsphinx isn't installed (pip install --prefer-binary pocketsphinx)"

    def test_set_to_the_cloud(self, ear):
        ear.wake.mode = "cloud"
        ear.phrases = [{"spots": "", "says": "little open chrome"}]
        assert ear.listen(wake=True) == "little open chrome"
        assert ear.wake.why_not() == "set to the cloud (JARVIS_WAKE_MODE=cloud)"

    def test_an_offline_failure_falls_back_for_good(self, ear):
        ear.phrases = [{"offline_error": "no dictionary", "says": "little open chrome"},
                       {"spots": "", "says": "pass the salt"}]
        assert ear.listen(wake=True) == "little open chrome", "this phrase isn't lost"
        assert ear.listen(wake=True) == "pass the salt" and len(ear.recognizer.sphinx) == 1
        assert ear.wake.why_not() == "the offline check failed: no dictionary"
        assert ear.wake.counts["errors"] == 1

    def test_a_recogniser_without_the_offline_check(self, installed):
        assert local_wake.LocalWake(object(), mode="auto").why_not() == \
            "this SpeechRecognition has no offline recogniser"

    @pytest.mark.parametrize("raw,value", [("0.3", 0.3), ("", 0.6), ("loud", 0.6), ("5", 0.95), ("-1", 0.05)])
    def test_the_sensitivity_setting(self, monkeypatch, raw, value):
        monkeypatch.setenv("JARVIS_WAKE_SENSITIVITY", raw)
        assert local_wake.LocalWake(Recogniser()).sensitivity == value

    @pytest.mark.parametrize("raw,mode", [("local", "local"), ("CLOUD", "cloud"), ("sometimes", "auto"), ("", "auto")])
    def test_the_mode_setting(self, monkeypatch, raw, mode):
        monkeypatch.setenv("JARVIS_WAKE_MODE", raw)
        assert local_wake.LocalWake(Recogniser()).mode == mode

    def test_the_existing_wake_rules_are_unchanged(self):
        assert wake.wake_position("little open chrome") == len("little")
        assert wake.wake_position("a little bit more") is None
        assert wake.wake_position("hey jarvis what's up") == len("hey jarvis")


# ============================================================ calibrating

class TestCalibrating:
    def test_noise_that_sounds_like_the_name_lowers_the_sensitivity(self, ear):
        ear.phrases = [{"spots": "little"}, {"spots": ""}, {"spots": "jarvis"}, None]
        said = ear.calibrate_wake()
        assert ear.wake.sensitivity == 0.4
        assert said == ("The room's noise sounded like my name 2 times, so I lowered the sensitivity from 0.6 "
                        "to 0.4 for now. To keep it, put JARVIS_WAKE_SENSITIVITY=0.4 in .env.")

    def test_never_below_the_floor(self, ear):
        ear.wake.sensitivity = 0.25
        ear.phrases = [{"spots": "little"}] * 4
        ear.calibrate_wake()
        assert ear.wake.sensitivity == local_wake.LOWEST

    def test_a_quiet_or_harmless_room_changes_nothing(self, ear):
        assert ear.calibrate_wake() == "The room was quiet, so nothing to adjust. Sensitivity stays 0.6."
        ear.phrases = [{"spots": ""}, {"spots": ""}]
        assert ear.calibrate_wake() == "The room's noise never sounded like my name. Sensitivity stays 0.6."

    def test_in_the_cloud_there_is_nothing_to_calibrate(self, ear):
        ear.wake.mode = "cloud"
        assert ear.calibrate_wake().startswith("The wake word is checked in the cloud here: set to the cloud")

    def test_by_command(self, monkeypatch):
        monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
        bot = assistant.Jarvis(log_fn=lambda _l: None)
        bot.muted = True
        bot.handle("calibrate the wake word")
        assert tasks.recent(1)[0]["reply"] == "The mic isn't on yet. Click the core first."
        bot.listener = types.SimpleNamespace(calibrate_wake=lambda: "Calibrated.")
        bot.handle("test the wake word")
        assert tasks.recent(1)[0]["reply"] == "Calibrated." and tasks.recent(1)[0]["path"] == "fast"


# ============================================================ the loop

class TestTheVoiceLoop:
    def test_phrases_kept_here_are_not_misses(self, monkeypatch):
        monkeypatch.setattr(assistant.memory, "log_turn", lambda *_a: None)
        lines = []
        bot = assistant.Jarvis(log_fn=lines.append)
        bot.muted = True

        class Mic:
            kept_here = False
            heard = [None] * 30 + ["little what's the time"]
            asked = []

            def listen(self, **kw):
                Mic.asked.append(kw)
                if not self.heard:
                    bot.running = False
                    return None
                said = self.heard.pop(0)
                self.kept_here = said is None
                return said
        bot.listener = Mic()
        bot.running = True
        bot._voice_loop()
        assert not any("haven't made out anything" in line for line in lines), "30 phrases without the name"
        assert tasks.recent(1)[0]["text"] == "what's the time"
        assert Mic.asked[0] == {"timeout": 5, "phrase_limit": 10, "wake": True}


# ============================================================== reporting

class TestSayingWhereItsChecked:
    def test_the_report(self, ear):
        local_wake.current = ear.wake
        try:
            assert fast_route("wake word status").startswith("My name is checked on this computer first "
                                                             "(words: jarvis, little; sensitivity 0.6).")
            ear.phrases = [{"spots": "", "says": "x"}, {"spots": "little", "says": "little hi"},
                           {"spots": "little", "says": "a little more"}]
            for _ in range(3):
                ear.listen(wake=True)
            assert fast_route("is the wake word local?").endswith(
                "Of 3 phrases, 1 stayed on this computer and 2 went to the cloud to confirm: 1 confirmed, "
                "1 weren't my name after all.")
        finally:
            local_wake.current = None

    def test_before_voice_is_on(self):
        assert fast_route("how do you hear your name") == "Voice isn't on, so I'm not listening for my name yet."

    def test_the_system_section_says_where(self, monkeypatch):
        monkeypatch.setattr(local_wake, "installed", lambda: False)
        rows = {r["label"]: r for g in settings.groups() if g["id"] == "wake" for r in g["rows"]}
        assert rows["Where the name is checked"]["value"] == "in the cloud"
        assert "pocketsphinx isn't installed" in rows["Where the name is checked"]["note"]
        monkeypatch.setattr(local_wake, "installed", lambda: True)
        rows = {r["label"]: r for g in settings.groups() if g["id"] == "wake" for r in g["rows"]}
        assert rows["Where the name is checked"]["value"] == "on this computer first"
        assert rows["Offline sensitivity"]["key"] == "JARVIS_WAKE_SENSITIVITY"
