"""Reminders that speak up when they're due."""
from __future__ import annotations

import datetime
import re
import threading

from ..app.config import log

_timers: list[dict] = []
_speak = None


def set_speaker(fn) -> None:
    """core.py hands us its voice so reminders can talk."""
    global _speak
    _speak = fn


def _parse_when(when: str) -> datetime.datetime | None:
    text = when.lower().strip()
    now = datetime.datetime.now()

    relative = re.search(r"in\s+(\d+)\s*(min|minute|minutes|hour|hours|sec|second|seconds)", text)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        if unit.startswith("sec"):
            return now + datetime.timedelta(seconds=amount)
        if unit.startswith("hour"):
            return now + datetime.timedelta(hours=amount)
        return now + datetime.timedelta(minutes=amount)

    clock = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if clock:
        hour = int(clock.group(1))
        minute = int(clock.group(2) or 0)
        meridiem = clock.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        target = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        return target
    return None


def set_reminder(text: str, when: str) -> str:
    """Remind the user about something at a time like '8 pm' or 'in 10 minutes'."""
    target = _parse_when(when)
    if not target:
        return f"I couldn't work out when '{when}' is. Try '8 pm' or 'in 10 minutes'."

    delay = (target - datetime.datetime.now()).total_seconds()

    def fire() -> None:
        message = f"Reminder: {text}"
        if _speak:
            _speak(message)
        log(message)

    timer = threading.Timer(delay, fire)
    timer.daemon = True
    timer.start()
    _timers.append({"text": text, "at": target, "timer": timer})
    return f"I'll remind you at {target.strftime('%I:%M %p')}: {text}"


def list_reminders() -> str:
    """List reminders still waiting."""
    pending = [r for r in _timers if r["timer"].is_alive()]
    if not pending:
        return "No reminders set."
    return "; ".join(f"{r['at'].strftime('%I:%M %p')} - {r['text']}" for r in pending)


def cancel_reminders() -> str:
    """Cancel every pending reminder."""
    count = 0
    for reminder in _timers:
        if reminder["timer"].is_alive():
            reminder["timer"].cancel()
            count += 1
    _timers.clear()
    return f"Cancelled {count} reminder(s)."
