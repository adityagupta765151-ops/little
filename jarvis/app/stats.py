"""Live numbers for the panel.

Everything here is real. If a reading isn't available the panel says so
rather than showing a plausible-looking number.
"""
from __future__ import annotations

import platform
import time
from collections import deque

from .config import ASSISTANT_CALL, ASSISTANT_NAME, LANG, MODEL, VOICE, WORKSPACE

try:
    import psutil
except ImportError:
    psutil = None

STARTED = time.time()

commands_run = 0
tool_log: deque = deque(maxlen=12)   # (name, seconds)
_last_tool_start: dict[str, float] = {}


def note_command() -> None:
    global commands_run
    commands_run += 1


def tool_started(name: str) -> None:
    _last_tool_start[name] = time.perf_counter()


def tool_finished(name: str) -> None:
    started = _last_tool_start.pop(name, None)
    tool_log.appendleft((name, time.perf_counter() - started if started else 0.0))


def _uptime() -> str:
    seconds = int(time.time() - STARTED)
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def system() -> dict:
    """CPU, memory and disk, or a note that psutil isn't installed."""
    if psutil is None:
        return {"available": False}
    try:
        disk = psutil.disk_usage(str(WORKSPACE.anchor or WORKSPACE))
        memory = psutil.virtual_memory()
        return {
            "available": True,
            "cpu": round(psutil.cpu_percent(interval=None)),
            "ram": round(memory.percent),
            "ram_used": round(memory.used / 1e9, 1),
            "ram_total": round(memory.total / 1e9, 1),
            "disk": round(disk.percent),
            "disk_free": round(disk.free / 1e9),
        }
    except Exception:  # noqa: BLE001
        return {"available": False}


def _voice_label() -> str:
    """"en-IN-NeerjaNeural" reads as "Neerja" on the panel. The voice that
    is actually speaking, if the chosen one had to be stood in for."""
    try:
        from ..voice import speaking
        name = speaking._active_voice or VOICE
    except Exception:  # noqa: BLE001
        name = VOICE
    parts = name.split("-")
    return parts[-1].replace("Neural", "").replace("Multilingual", "") if len(parts) >= 3 else name


def warnings() -> list[dict]:
    """Setup problems to put in front of you on Home. Only ones known for
    certain and free to check — no probing, no network."""
    from . import config
    out = []
    if not config.API_KEY:
        out.append({
            "id": "api-key",
            "text": "No Gemini API key, so only built-in commands work.",
            "fix": f"Add GEMINI_API_KEY to the .env file, then restart {ASSISTANT_CALL}.",
        })
    return out


def snapshot(jarvis, muted: bool) -> dict:
    """Everything the panel shows, gathered in one go."""
    from ..ai import planner
    from ..store import memory as mem
    from ..tools import browser, reminders

    pending = [
        {"at": r["at"].strftime("%H:%M"), "text": r["text"]}
        for r in reminders._timers if r["timer"].is_alive()
    ]

    return {
        "system": system(),
        "session": {
            "uptime": _uptime(),
            "commands": commands_run,
            "tools": len(tool_log),
            "os": f"{platform.system()} {platform.release()}",
        },
        "identity": {"name": ASSISTANT_NAME, "call": ASSISTANT_CALL},
        "voice": {
            "mic": "on" if jarvis.running else "off",
            "speech": "muted" if muted else "on",
            "voice": _voice_label(),
            "lang": LANG,
            "model": MODEL,
        },
        "tools": [{"name": n, "ms": round(s * 1000)} for n, s in list(tool_log)[:6]],
        "reminders": pending[:4],
        "plan": planner.current(),
        "browser": "open" if browser._worker.context else "closed",
        "contacts": len(mem.contacts()),
        "workspace": str(WORKSPACE),
        "warnings": warnings(),
    }
