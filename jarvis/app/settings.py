"""Every setting LITTLE runs with, as the System section shows it.

Read from what the code actually uses — config.py and the modules that read
their own settings — not re-parsed from .env, so what's shown is what's in
effect. Settings are read-only in the window (decision D3): each one names
its .env key, and changing it means editing .env and restarting.

No secret ever leaves here. The API keys are reported as set or missing,
never as a value or part of one.
"""
from __future__ import annotations

import importlib.util
import os

from . import config

SECRETS = ("GEMINI_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "MUSE_API_KEY")


def _row(label: str, value, key: str = "", note: str = "") -> dict:
    return {"label": label, "value": str(value), "key": key, "note": note}


def _secret(label: str, key: str, note: str = "") -> dict:
    return _row(label, "set" if (os.getenv(key) or "").strip() else "missing", key, note)


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _suggestions_row() -> dict:
    from . import proactive
    off = proactive._load()["off_kinds"]
    return _row("Suggestions", ("on" if proactive.enabled() else "off")
                + (f", except {', '.join(off)}" if off else ""), "JARVIS_PROACTIVE",
                note="At most one an hour and four a day, each thing once. They suggest; they never act.")


def _offline_sensitivity() -> float:
    from ..voice import local_wake
    if local_wake.current is not None:
        return local_wake.current.sensitivity
    return local_wake._sensitivity(os.getenv("JARVIS_WAKE_SENSITIVITY"))


def _wake_check_row() -> dict:
    """Where the name is checked: here first, or only in the cloud — and why."""
    from ..voice import local_wake
    checker = local_wake.current or local_wake.LocalWake(recognizer=None)
    why = checker.why_not()
    return _row("Where the name is checked", "on this computer first" if not why else "in the cloud",
                "JARVIS_WAKE_MODE", note=why or "Only a phrase that has the name in it is sent to be transcribed.")


def groups(assistant=None) -> list[dict]:
    """The settings, grouped the way the System section lays them out."""
    from ..ai import provider
    from ..voice import listening, wake
    from . import assistant as assistant_module
    from . import proactive

    running = bool(getattr(assistant, "running", False))
    muted = getattr(assistant, "muted", None)

    return [
        {"id": "ai", "title": "AI provider", "rows": [
            _row("Provider", "Google Gemini"),
            _row("Model", config.MODEL, "GEMINI_MODEL"),
            _row("In use now", provider._current_model,
                 note="Differs from the model above after it was busy and I switched to a lighter one."),
            _row("Fast model", provider._current_fast, "JARVIS_MODEL_FAST",
                 note="For short jobs: checking a plan step, summarising a page. Falls back like the main one."),
            _row("Falls back to", ", ".join(provider.FALLBACK_MODELS)),
            _secret("API key", "GEMINI_API_KEY"),
        ]},
        {"id": "voice", "title": "Voice", "rows": [
            _row("Voice", config.VOICE, "JARVIS_VOICE"),
            _row("Speed", config.VOICE_SPEED, "JARVIS_VOICE_SPEED"),
            _row("Pitch", config.VOICE_PITCH, "JARVIS_VOICE_PITCH"),
            _row("Volume", config.VOICE_VOLUME, "JARVIS_VOICE_VOLUME"),
            _row("Natural voice", ("on" if config.USE_NEURAL else "off")
                 + ("" if _installed("edge_tts") else " — edge-tts isn't installed, so the Windows voice speaks"),
                 "JARVIS_NEURAL_VOICE"),
            _row("At start", "speaking" if config.VOICE_ENABLED else "muted", "JARVIS_VOICE_ENABLED"),
            _row("Right now", "unknown" if muted is None else ("muted" if muted else "speaking"),
                 note="The Mute button changes this until the next start."),
            _row("Windows voice speed", f"{config.VOICE_RATE} words a minute", "JARVIS_VOICE_RATE",
                 note="Only when the natural voice can't be used."),
            _suggestions_row(),
            _row("Suggestions spoken", "yes" if proactive._on(os.getenv("JARVIS_PROACTIVE_SPEAK"), False) else
                 "no — shown in the activity log only", "JARVIS_PROACTIVE_SPEAK",
                 note="Never in quiet hours (JARVIS_QUIET_HOURS, now " + "-".join(map(str, proactive._quiet_hours()))
                      + ")."),
        ]},
        {"id": "mic", "title": "Microphone", "rows": [
            _row("Microphone", f"#{listening.MIC_INDEX}" if (listening.MIC_INDEX or "").strip()
                 else "the system default", "JARVIS_MIC"),
            _row("Pause that ends a command", f"{listening.PAUSE:g} s", "JARVIS_PAUSE"),
            _row("Sensitivity", listening.ENERGY.strip() if (listening.ENERGY or "").strip()
                 else "adjusts to the room", "JARVIS_MIC_SENSITIVITY"),
            _row("Listening now", "yes" if running else "no"),
        ]},
        {"id": "wake", "title": "Wake word", "rows": [
            _row("Name", config.ASSISTANT_NAME, "JARVIS_ASSISTANT_NAME"),
            _row("Answers to", ", ".join(config.WAKE_WORDS), "JARVIS_WAKE"),
            _row("How close it must sound", f"{wake.FUZZY:g}", "JARVIS_WAKE_FUZZY",
                 note="Higher is stricter; lower wakes more easily, and by mistake more often."),
            _row("Language", config.LANG, "JARVIS_LANG"),
            _row("Show what it heard", "yes" if assistant_module.SHOW_HEARD else "no", "JARVIS_SHOW_HEARD"),
            _wake_check_row(),
            _row("Offline sensitivity", f"{_offline_sensitivity():g}", "JARVIS_WAKE_SENSITIVITY",
                 note="Higher hears the name more readily, and by mistake more often."),
        ]},
        {"id": "browser", "title": "Browser", "rows": [
            _row("Automation browser", "hidden while it works" if config.BROWSER_HEADLESS
                 else "shown, so you can watch", "JARVIS_BROWSER_HEADLESS"),
            _row("Its own profile", config.BROWSER_PROFILE,
                 note="Its logins stay here, apart from the browser you use yourself."),
        ]},
        {"id": "jobs", "title": "Job search", "rows": [
            _secret("Adzuna app id", "ADZUNA_APP_ID", "Adzuna carries the Indian listings."),
            _secret("Adzuna key", "ADZUNA_APP_KEY"),
            _row("Adzuna country", os.getenv("ADZUNA_COUNTRY", "in"), "ADZUNA_COUNTRY"),
            _row("Region for the other boards", os.getenv("JARVIS_JOB_GEO", "india"), "JARVIS_JOB_GEO"),
            _row("City", os.getenv("JARVIS_JOB_CITY", "") or "not set", "JARVIS_JOB_CITY"),
            _secret("The Muse key", "MUSE_API_KEY", "Optional."),
        ]},
        {"id": "files", "title": "Files and memory", "rows": [
            _row("Workspace", config.WORKSPACE, "JARVIS_WORKSPACE",
                 note="The only folder I may read or write files in."),
            _row("Memory folder", config.MEMORY_DIR,
                 note="Your resume profile, jobs, contacts and what I remember."),
            _row("Log", config.LOG_FILE),
        ]},
    ]


def env_file() -> dict:
    path = config.BASE_DIR / ".env"
    return {"path": str(path), "exists": path.exists()}


def asks_first() -> list[dict]:
    """Every tool that never runs without your yes, in its own words."""
    from ..tools.permissions import NEEDS_CONFIRMATION
    from ..tools.registry import TOOL_SCHEMAS
    described = {t["name"]: t.get("description", "") for t in TOOL_SCHEMAS}
    # Two buttons in Jobs ask too, though their tools don't when the model
    # uses them: preparing never submits, and a record is only a record.
    extra = {
        "Jobs: Prepare application…": "Open a job's application form and fill in what your resume "
                                      "answers. Never submits.",
        "Jobs: I applied": "Record that you applied to a job. Only you can say you did.",
    }
    from ..tools.permissions import level
    tools = [{"name": n, "does": described.get(n, ""), "level": level(n)} for n in sorted(NEEDS_CONFIRMATION)]
    return tools + [{"name": n, "does": d, "level": "CONFIRM"} for n, d in extra.items()]


def tool_count() -> int:
    from ..tools.registry import TOOL_SCHEMAS
    return len(TOOL_SCHEMAS)
