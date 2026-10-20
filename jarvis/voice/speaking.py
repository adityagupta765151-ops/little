"""Speech out.

Two engines. Edge TTS uses Microsoft's neural voices, which sound like a
person and include Indian English and Hindi; it needs a network connection.
pyttsx3 uses whatever Windows has locally, which is robotic but always
there. The neural one is preferred, and the local one takes over without a
word when it can't be reached.

Which voice, how fast, how high and how loud all come from config.py, so
changing Little's voice is an .env edit rather than a code change. A voice
name that turns out not to exist falls through to the next one in the
chain instead of leaving the assistant mute.
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
import threading
from pathlib import Path

from ..app.config import (DEFAULT_VOICE, USE_NEURAL, VOICE, VOICE_PITCH, VOICE_RATE,
                          VOICE_SPEED, VOICE_VOLUME, log)

# pyttsx3 needs a sound card, which a test run doesn't have. Importing
# without it is fine; only speaking aloud needs it.
try:
    import pyttsx3
except Exception:  # noqa: BLE001
    pyttsx3 = None


# Kept under their old names too, for anything that already imports them.
NEURAL_VOICE = VOICE
NEURAL_RATE = VOICE_SPEED
NEURAL_PITCH = VOICE_PITCH
NEURAL_VOLUME = VOICE_VOLUME

# Tried in order when the chosen voice can't be synthesised — a typo in
# .env, or a voice Microsoft retired. Every name here has been in the
# service for years; the chosen one comes first whatever it is.
FALLBACK_VOICES = (DEFAULT_VOICE, "en-US-JennyNeural", "en-US-AriaNeural")

SUGGESTED = {
    "en-IN-NeerjaNeural": "Indian English, female — Little's voice",
    "en-US-JennyNeural": "American English, female, warm and friendly",
    "en-US-AriaNeural": "American English, female, bright and expressive",
    "en-GB-SoniaNeural": "British English, female, calm",
    "hi-IN-SwaraNeural": "Hindi, female",
    "en-US-AnaNeural": "American English, a child's voice — younger than Little",
    "en-IN-PrabhatNeural": "Indian English, male — the old JARVIS voice",
}

_tts_lock = threading.Lock()
_stop_flag = threading.Event()
_engine = None
_player = None
_neural_broken = False      # set once, so a missing package isn't retried per sentence
_active_voice: str | None = None    # the first voice in the chain that actually worked


def _spoken(text: str) -> str:
    """Strip what should never be read out loud."""
    text = re.sub(r"```.*?```", " The code is in the file. ", text, flags=re.S)
    text = re.sub(r"https?://\S+", " the link ", text)
    text = re.sub(r"[*_#`>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- neural

def _synthesise(text: str, path: Path, voice: str | None = None) -> bool:
    try:
        import edge_tts
    except ImportError:
        return False

    async def run():
        speech = edge_tts.Communicate(text, voice or NEURAL_VOICE, rate=NEURAL_RATE,
                                      pitch=NEURAL_PITCH, volume=NEURAL_VOLUME)
        await speech.save(str(path))

    try:
        asyncio.run(run())
        return path.exists() and path.stat().st_size > 800
    except Exception as e:  # noqa: BLE001
        log(f"edge-tts failed with {voice or NEURAL_VOICE}: {e}")
        return False


def _voice_chain() -> list[str]:
    """The chosen voice, then the fallbacks, without repeats."""
    chain = []
    for voice in (_active_voice, NEURAL_VOICE, *FALLBACK_VOICES):
        if voice and voice not in chain:
            chain.append(voice)
    return chain


def _synthesise_any(text: str, path: Path) -> bool:
    """Try the chain until a voice works, and remember which one did.

    A voice that doesn't exist and a network that isn't there fail the
    same way, so the chain stops at three attempts: past that it is almost
    certainly the network, and the local voice is the right answer.
    """
    global _active_voice
    for voice in _voice_chain()[:3]:
        if _synthesise(text, path, voice):
            if voice != _active_voice:
                if _active_voice is None and voice != NEURAL_VOICE:
                    log(f"voice {NEURAL_VOICE} didn't work; using {voice} instead")
                _active_voice = voice
            return True
    return False


def _play(path: Path) -> bool:
    """Play an mp3, trying whichever player is installed."""
    global _player
    try:
        from playsound3 import playsound
        _player = playsound(str(path), block=False)
        while _player.is_alive():
            if _stop_flag.is_set():
                _player.stop()
                break
            _stop_flag.wait(0.05)
        _player = None
        return True
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        log(f"playsound3 failed: {e}")

    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            if _stop_flag.is_set():
                pygame.mixer.music.stop()
                break
            _stop_flag.wait(0.05)
        pygame.mixer.music.unload()
        return True
    except ImportError:
        return False
    except Exception as e:  # noqa: BLE001
        log(f"pygame playback failed: {e}")
        return False


def _speak_neural(text: str) -> bool:
    global _neural_broken
    if _neural_broken or not USE_NEURAL:
        return False

    path = Path(tempfile.gettempdir()) / f"jarvis-speech-{os.getpid()}.mp3"
    if not _synthesise_any(text, path):
        _neural_broken = True
        log("falling back to the local voice for the rest of this session")
        return False
    try:
        return _play(path)
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------- local

def _best_local_voice(engine) -> str | None:
    """Windows 11 ships far better voices than the old default, but only if
    they have been added. Pick the best one present."""
    try:
        voices = engine.getProperty("voices")
    except Exception:  # noqa: BLE001
        return None

    # Little is a light, warm voice, so the female voices come first at
    # every level of quality; a male voice is still better than silence.
    warm = ("jenny", "aria", "sonia", "neerja", "heera", "zira", "hazel", "susan")

    def rank(voice) -> int:
        name = (getattr(voice, "name", "") or "").lower()
        natural = "natural" in name          # the neural Windows voices
        female = any(n in name for n in warm)
        if natural and female:
            return 0
        if natural:
            return 1
        if "heera" in name:
            return 2                         # Indian English
        if female:
            return 3
        return 4

    best = sorted(voices, key=rank)
    return best[0].id if best else None


def _local_volume() -> float:
    """"+0%" is full volume for the local engine, "-30%" is 0.7."""
    try:
        return max(0.1, min(1.0, 1.0 + int(NEURAL_VOLUME.rstrip("%")) / 100))
    except ValueError:
        return 1.0


def _speak_local(text: str) -> None:
    global _engine
    if pyttsx3 is None:
        log("no speech engine available; staying silent")
        return
    try:
        # A fresh engine per call keeps pyttsx3 from hanging on a second
        # runAndWait in a background thread.
        _engine = pyttsx3.init()
        chosen = _best_local_voice(_engine)
        if chosen:
            _engine.setProperty("voice", chosen)
        _engine.setProperty("rate", VOICE_RATE)
        _engine.setProperty("volume", _local_volume())
        _engine.say(text)
        _engine.runAndWait()
        _engine.stop()
    except Exception as e:  # noqa: BLE001
        log(f"tts failed: {e}")
    finally:
        _engine = None


# ---------------------------------------------------------------- public

def speak(text: str) -> None:
    text = _spoken(text)
    if not text:
        return
    _stop_flag.clear()
    with _tts_lock:
        if not _speak_neural(text[:900]):
            _speak_local(text[:700])


def stop_speaking() -> None:
    """Cut the current sentence short, whichever engine is talking."""
    _stop_flag.set()
    try:
        if _engine:
            _engine.stop()
    except Exception as e:  # noqa: BLE001
        log(f"tts stop failed: {e}")


def _live_voices(timeout: float = 6.0) -> list[dict] | None:
    """Ask Microsoft which voices exist right now. None if it can't be reached,
    so the report can say its list is unchecked rather than pretend."""
    try:
        import edge_tts
    except ImportError:
        return None

    async def fetch():
        return await asyncio.wait_for(edge_tts.list_voices(), timeout)

    try:
        return asyncio.run(fetch())
    except Exception as e:  # noqa: BLE001
        log(f"couldn't list voices: {e}")
        return None


def voice_report() -> str:
    """Which voice is actually speaking, its settings, and what else there is."""
    from ..app.config import ASSISTANT_CALL, VOICE_ENABLED

    lines = [f"{ASSISTANT_CALL}'s voice"]
    try:
        import edge_tts  # noqa: F401
        speaking = _active_voice or NEURAL_VOICE
        note = ""
        if _neural_broken:
            note = " (unreachable this session, so the local voice is speaking)"
        elif _active_voice and _active_voice != NEURAL_VOICE:
            note = f" (standing in, because {NEURAL_VOICE} didn't work)"
        lines.append(f"  voice   {speaking}{note}")
    except ImportError:
        lines.append("  voice   neural voice not installed — pip install edge-tts playsound3")
    lines.append(f"  speed   {NEURAL_RATE}    pitch  {NEURAL_PITCH}    volume  {NEURAL_VOLUME}")
    lines.append(f"  speech  {'on' if VOICE_ENABLED else 'off at start (JARVIS_VOICE_ENABLED)'}")

    if pyttsx3 is None:
        lines.append("  local   pyttsx3 isn't installed on this machine")
    else:
        try:
            engine = pyttsx3.init()
            names = [getattr(v, "name", "?") for v in engine.getProperty("voices")]
            engine.stop()
            lines.append("  local   " + (", ".join(names[:5]) or "none installed"))
        except Exception:  # noqa: BLE001
            lines.append("  local   couldn't read the installed voices")

    live = _live_voices()
    lines.append("")
    if live:
        wanted = ("en-IN", "en-US", "en-GB", "hi-IN")
        pick = [v for v in live if v.get("Locale") in wanted and v.get("Gender") == "Female"]
        names = {v.get("ShortName") for v in live}
        if NEURAL_VOICE not in names:
            lines.append(f"Heads up: {NEURAL_VOICE} isn't a voice Microsoft offers right now.")
        lines.append("Female voices available right now (set one in .env as JARVIS_VOICE):")
        for v in pick[:12]:
            tags = ", ".join((v.get("VoiceTag") or {}).get("VoicePersonalities", [])[:3])
            lines.append(f"  {v.get('ShortName', '?'):<30} {tags}")
    else:
        lines.append("Voices you can set in .env as JARVIS_VOICE "
                     "(couldn't check the live list just now):")
        for name, description in SUGGESTED.items():
            lines.append(f"  {name:<24} {description}")
    return "\n".join(lines)
