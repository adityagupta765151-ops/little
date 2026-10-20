"""One place for paths, settings and logging. Everything else imports this."""
from __future__ import annotations

import datetime
import os
import re
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

# The project root, not the package. Counting parents breaks the moment a
# module moves, so find the folder that actually holds the project instead.
# The installed app (PyInstaller) runs from a folder it may not write to, and
# unpacks its own files somewhere temporary. Your .env, memory and log live
# in your profile instead, so reinstalling or updating never touches them.
FROZEN = bool(getattr(sys, "frozen", False))


def _project_root() -> Path:
    if FROZEN:
        root = Path.home() / "AppData" / "Local" / "Little"
        root.mkdir(parents=True, exist_ok=True)
        return root
    here = Path(__file__).resolve()
    for folder in here.parents:
        if (folder / "requirements.txt").exists() or (folder / ".env").exists():
            return folder
    return here.parents[2]          # jarvis/app/config.py -> the project


BASE_DIR = _project_root()
# The files that ship with the app and are only read: ui/, little.ico.
APP_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
if FROZEN and not (BASE_DIR / ".env").exists() and (APP_DIR / ".env.example").exists():
    shutil.copyfile(APP_DIR / ".env.example", BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env")

WORKSPACE = Path(
    os.getenv("JARVIS_WORKSPACE", str(Path.home() / "JarvisWorkspace"))
).expanduser().resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

# Where your resume profile, jobs, contacts and memories live, and the log.
# The tests point both somewhere temporary (tests/conftest.py): a test run
# once used these very files, and wiped them on every test.
MEMORY_DIR = Path(
    os.getenv("JARVIS_MEMORY_DIR", str(BASE_DIR / "memory"))
).expanduser().resolve()
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = Path(
    os.getenv("JARVIS_LOG_FILE", str(BASE_DIR / "jarvis.log"))
).expanduser().resolve()


def log(message: str) -> None:
    """Technical detail goes to the log file, not to the user."""
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    # Chapter 41: whatever a message carries, nothing shaped like a key,
    # password or card number reaches the log file.
    try:
        from ..store.memory import redact
        message = redact(message)
    except Exception:  # noqa: BLE001  (memory not importable yet: log as is)
        pass
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


# ---------------------------------------------------------------- identity
# The assistant is called LITTLE. The Python package, the log file and the
# JARVIS_* settings keep their original names, so existing installs, .env
# files and imports carry on working; only what the user sees and hears
# changed.

ASSISTANT_NAME = (os.getenv("JARVIS_ASSISTANT_NAME", "LITTLE").strip() or "LITTLE").upper()
ASSISTANT_CALL = ASSISTANT_NAME.title()        # "Little" — how it's said and written in prose

# What the assistant used to be called. It still answers to these, so
# nothing anyone has already learned to say stops working.
LEGACY_WAKE = ["hey jarvis", "jarvis", "jervis", "javis"]


def _wake_words() -> list[str]:
    """Its own name always wakes it, whatever .env says.

    An .env written for the old name pins JARVIS_WAKE to "hey jarvis,
    jarvis" — without this, renaming the assistant would leave it deaf to
    its new name on every machine that was already set up.
    """
    own = ASSISTANT_CALL.lower()
    mine = [f"hey {own}", f"ok {own}", f"okay {own}", own]
    configured = [w.strip().lower() for w in os.getenv("JARVIS_WAKE", "").split(",")
                  if w.strip()]
    words, seen = [], set()
    for word in mine + (configured or LEGACY_WAKE):
        if word not in seen:
            seen.add(word)
            words.append(word)
    return words


WAKE_WORDS = _wake_words()
LANG = os.getenv("JARVIS_LANG", "en-IN")
MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
API_KEY = os.getenv("GEMINI_API_KEY")

# ------------------------------------------------------------------- voice
# Little's voice: Microsoft's Indian English Neerja, lifted slightly in
# pitch and pace so it reads young, light and warm rather than formal. An
# Indian voice first, because it says Indian names — contacts, cities —
# the way they are actually said.

DEFAULT_VOICE = "en-IN-NeerjaNeural"
DEFAULT_SPEED = "+5%"
DEFAULT_PITCH = "+10Hz"
DEFAULT_VOLUME = "+0%"

# The JARVIS voice, as the old .env.example shipped it. Spotting it lets the
# health check point out an .env that was never updated for the new voice.
OLD_VOICE = "en-IN-PrabhatNeural"

_PERCENT = re.compile(r"^[+-]\d{1,3}%$")
_HERTZ = re.compile(r"^[+-]\d{1,3}Hz$")


def _setting(name: str, default: str, shape: re.Pattern) -> str:
    """A malformed value would make every sentence fail to synthesise, which
    sounds exactly like the voice being broken. Fall back, and log why."""
    value = (os.getenv(name) or default).strip()
    if shape.match(value):
        return value
    log(f"{name}={value!r} isn't in the right form (like {default}); using {default}")
    return default


VOICE = (os.getenv("JARVIS_VOICE") or DEFAULT_VOICE).strip()
VOICE_SPEED = _setting("JARVIS_VOICE_SPEED", DEFAULT_SPEED, _PERCENT)
VOICE_PITCH = _setting("JARVIS_VOICE_PITCH", DEFAULT_PITCH, _HERTZ)
VOICE_VOLUME = _setting("JARVIS_VOICE_VOLUME", DEFAULT_VOLUME, _PERCENT)
VOICE_ENABLED = os.getenv("JARVIS_VOICE_ENABLED", "true").strip().lower() != "false"
USE_NEURAL = os.getenv("JARVIS_NEURAL_VOICE", "true").strip().lower() != "false"
VOICE_RATE = int(os.getenv("JARVIS_VOICE_RATE", "180"))    # local fallback, words a minute

# Browser automation
BROWSER_HEADLESS = os.getenv("JARVIS_BROWSER_HEADLESS", "false").lower() == "true"
BROWSER_PROFILE = BASE_DIR / "browser_profile"
