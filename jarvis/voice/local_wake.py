"""Hearing its name on this computer (Chapter 34).

Before, every phrase the microphone picked up was sent to Google's speech
service, and only then checked for the name. Now, when pocketsphinx is
installed, each phrase is first checked here, offline, for the name alone
(keyword spotting — no full transcription). Only a phrase that passes goes
to the cloud, where the transcript must still open with the name
(`wake.wake_position`) before anything runs. So:

- what's said in the room without the name never leaves this computer;
- a false alarm here costs one cloud check, not a command — the cloud
  transcript has to agree;
- without pocketsphinx, or if it fails, it listens exactly as before.

Settings (.env): JARVIS_WAKE_MODE = auto (local when it can, the default),
local, or cloud; JARVIS_WAKE_SENSITIVITY = 0.05–0.95 (higher hears the name
more readily and wakes by mistake more often). "Calibrate the wake word"
listens to the room for a few seconds and lowers the sensitivity if the
noise alone sounds like the name.
"""
from __future__ import annotations

import importlib.util
import os
import threading

from ..app.config import ASSISTANT_CALL, WAKE_WORDS, log

MODES = ("auto", "local", "cloud")
DEFAULT_SENSITIVITY = 0.6
LOWEST, HIGHEST, STEP = 0.2, 0.95, 0.1
# Only real words: the misspellings in WAKE_WORDS ("jervis", "javis") are
# there for the cloud's transcripts, and aren't in the offline dictionary.
DICTIONARY_NAMES = ("little", "jarvis")


def _mode() -> str:
    mode = os.getenv("JARVIS_WAKE_MODE", "auto").strip().lower()
    return mode if mode in MODES else "auto"


def _sensitivity(raw: str | None) -> float:
    try:
        value = float(raw) if raw not in (None, "") else DEFAULT_SENSITIVITY
    except ValueError:
        value = DEFAULT_SENSITIVITY
    return round(min(HIGHEST, max(0.05, value)), 2)


def installed() -> bool:
    try:
        return importlib.util.find_spec("pocketsphinx") is not None
    except (ImportError, ValueError):
        return False


class LocalWake:
    """Spots the name in a phrase of audio, offline, or says it can't."""

    def __init__(self, recognizer, mode: str | None = None, sensitivity: float | None = None) -> None:
        self.recognizer = recognizer
        self.mode = mode if mode in MODES else _mode()
        self.sensitivity = _sensitivity(str(sensitivity) if sensitivity is not None
                                        else os.getenv("JARVIS_WAKE_SENSITIVITY"))
        stems = {w.split()[-1] for w in WAKE_WORDS} | {ASSISTANT_CALL.lower()}
        self.words = sorted(w for w in stems if w in DICTIONARY_NAMES)
        self.broken = ""
        self._lock = threading.Lock()
        self.counts = {"checked": 0, "passed": 0, "kept_here": 0, "confirmed": 0, "rejected": 0, "errors": 0}

    # --------------------------------------------------------------- state

    def why_not(self) -> str:
        """Why the name isn't checked here, or "" when it is."""
        if self.mode == "cloud":
            return "set to the cloud (JARVIS_WAKE_MODE=cloud)"
        if not self.words:
            return "none of its names is in the offline dictionary"
        if not installed():
            return "pocketsphinx isn't installed (pip install --prefer-binary pocketsphinx)"
        if self.recognizer is not None and not hasattr(self.recognizer, "recognize_sphinx"):
            return "this SpeechRecognition has no offline recogniser"
        if self.broken:
            return f"the offline check failed: {self.broken}"
        return ""

    def active(self) -> bool:
        return not self.why_not()

    def _count(self, name: str) -> None:
        with self._lock:
            self.counts[name] += 1

    # ------------------------------------------------------------ hearing

    def heard(self, audio) -> bool | None:
        """True if the phrase has its name in it, False if it doesn't, None
        if it couldn't tell (then the cloud decides, as before)."""
        if not self.active():
            return None
        self._count("checked")
        try:
            said = self.recognizer.recognize_sphinx(
                audio, keyword_entries=[(word, self.sensitivity) for word in self.words])
        except Exception as e:  # noqa: BLE001
            if type(e).__name__ == "UnknownValueError":       # nothing like the name
                self._count("kept_here")
                return False
            self.broken = str(e) or type(e).__name__
            self._count("errors")
            log(f"local wake check failed, back to the cloud: {self.broken}")
            return None
        found = any(word in str(said or "").lower().split() for word in self.words)
        self._count("passed" if found else "kept_here")
        return found

    def confirmed(self, agreed: bool) -> None:
        """What the cloud made of a phrase that passed here."""
        self._count("confirmed" if agreed else "rejected")

    # -------------------------------------------------------- calibrating

    def calibrate(self, listen_audio, phrases: int = 4) -> str:
        """Listen to the room with nobody talking to LITTLE. Each phrase of
        noise that passes as its name lowers the sensitivity a step.
        `listen_audio()` returns one phrase of audio, or None for silence."""
        if not self.active():
            return f"The wake word is checked in the cloud here: {self.why_not()}."
        before, false_alarms, heard_anything = self.sensitivity, 0, 0
        for _ in range(phrases):
            audio = listen_audio()
            if audio is None:
                continue
            heard_anything += 1
            if self.heard(audio):
                false_alarms += 1
                self.sensitivity = round(max(LOWEST, self.sensitivity - STEP), 2)
        if not heard_anything:
            return (f"The room was quiet, so nothing to adjust. Sensitivity stays {self.sensitivity:g}.")
        if not false_alarms:
            return (f"The room's noise never sounded like my name. Sensitivity stays {self.sensitivity:g}.")
        return (f"The room's noise sounded like my name {false_alarms} time{'s' if false_alarms > 1 else ''}, "
                f"so I lowered the sensitivity from {before:g} to {self.sensitivity:g} for now. To keep it, put "
                f"JARVIS_WAKE_SENSITIVITY={self.sensitivity:g} in .env.")

    # ------------------------------------------------------------ report

    def report(self) -> str:
        c = self.counts
        if not self.active():
            where = f"My name is checked in the cloud: {self.why_not()}."
        else:
            where = (f"My name is checked on this computer first (words: {', '.join(self.words)}; "
                     f"sensitivity {self.sensitivity:g}).")
        if not c["checked"]:
            return where
        return (f"{where} Of {c['checked']} phrases, {c['kept_here']} stayed on this computer and "
                f"{c['passed']} went to the cloud to confirm: {c['confirmed']} confirmed, "
                f"{c['rejected']} weren't my name after all.")


# The one in use, for the report command. Set by the Listener.
current: LocalWake | None = None


def report() -> str:
    if current is None:
        return "Voice isn't on, so I'm not listening for my name yet."
    return current.report()
