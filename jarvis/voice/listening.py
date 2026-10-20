"""Speech in.

The microphone, the room calibration and the recogniser. Tuned from .env
because a quiet bedroom and a room with a fan need different settings.
"""
from __future__ import annotations

import os
import time

from ..app.config import LANG

# Blank MIC_INDEX means the system default; blank sensitivity means
# calibrate against the room instead of holding a fixed floor.
MIC_INDEX = os.getenv("JARVIS_MIC")
PAUSE = float(os.getenv("JARVIS_PAUSE", "1.0"))
ENERGY = os.getenv("JARVIS_MIC_SENSITIVITY")

try:
    import speech_recognition as sr
except Exception:  # noqa: BLE001
    sr = None

class Listener:
    def __init__(self, device_index: int | None = None) -> None:
        if sr is None:
            raise RuntimeError("SpeechRecognition isn't installed, so voice input is off.")

        if device_index is None and MIC_INDEX and MIC_INDEX.strip().isdigit():
            device_index = int(MIC_INDEX)

        self.recognizer = sr.Recognizer()
        # A pause longer than this ends the phrase. Too short and it cuts
        # you off mid-sentence; too long and every command feels slow.
        self.recognizer.pause_threshold = PAUSE
        self.recognizer.non_speaking_duration = min(0.5, PAUSE / 2)

        if ENERGY and ENERGY.strip():
            self.recognizer.energy_threshold = float(ENERGY)
            self.recognizer.dynamic_energy_threshold = False
        else:
            self.recognizer.dynamic_energy_threshold = True

        self.mic = sr.Microphone(device_index=device_index)
        self.device_index = device_index
        self.calibrate()
        # Chapter 34: its name checked on this computer first, when it can be.
        from . import local_wake
        self.wake = local_wake.LocalWake(self.recognizer)
        local_wake.current = self.wake
        self.kept_here = False

    def calibrate(self, seconds: float = 1.2) -> str:
        """Learn the room's background noise. Worth redoing when a fan goes
        on, or when it starts triggering on nothing."""
        if ENERGY and ENERGY.strip():
            return f"Using the fixed sensitivity you set: {self.recognizer.energy_threshold:.0f}"
        with self.mic as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=seconds)
        return (f"Calibrated. Background noise reads "
                f"{self.recognizer.energy_threshold:.0f}; I'll listen above that.")

    @staticmethod
    def devices() -> list[str]:
        if sr is None:
            return []
        try:
            return list(sr.Microphone.list_microphone_names())
        except Exception:  # noqa: BLE001
            return []

    def _record(self, timeout: float, phrase_limit: float):
        """One phrase of audio from the microphone, or None for silence."""
        with self.mic as source:
            try:
                return self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            except sr.WaitTimeoutError:
                return None

    def listen(self, timeout: float = 5, phrase_limit: float = 12, wake: bool = False) -> str | None:
        """One phrase, as text. With `wake`, a phrase is first checked on
        this computer for the name (when that can be done); one without it
        is dropped here and never sent anywhere — `kept_here` says so."""
        self.kept_here = False
        audio = self._record(timeout, phrase_limit)
        if audio is None:
            return None
        from ..app import latency           # each stage timed (Chapter 46)
        started = time.perf_counter()
        verdict = self.wake.heard(audio) if wake and getattr(self, "wake", None) else None
        if verdict is not None:
            latency.record("wake", (time.perf_counter() - started) * 1000)
        if verdict is False:
            self.kept_here = True
            return None
        started = time.perf_counter()
        try:
            text = self.recognizer.recognize_google(audio, language=LANG).lower()
        except sr.UnknownValueError:
            text = None                     # heard sound, made no words of it
        except sr.RequestError as e:
            raise ConnectionError(f"Speech service unreachable: {e}") from e
        latency.record("stt", (time.perf_counter() - started) * 1000)
        if verdict is True:
            from .wake import wake_position
            self.wake.confirmed(bool(text) and wake_position(text) is not None)
        return text

    def calibrate_wake(self, phrases: int = 4) -> str:
        """Listen to the room for a few short phrases and adjust how readily
        the name is heard here."""
        return self.wake.calibrate(lambda: self._record(timeout=2, phrase_limit=3), phrases)


def microphones() -> str:
    """List the input devices, so a better one than the default can be picked."""
    names = Listener.devices()
    if not names:
        return "I can't see any microphones. Check Windows sound settings."
    lines = ["Microphones this machine reports:"]
    for i, name in enumerate(names):
        lines.append(f"  {i:>2}  {name}")
    lines.append("")
    lines.append("To use one, put its number in .env as JARVIS_MIC, then restart.")
    return "\n".join(lines)
