"""LITTLE speaking up on its own (Chapter 36) — rarely, and only to suggest.

Every so often it looks at what it already keeps on this computer and may
mention one thing worth your attention:

  new_matches    jobs found in the last day that match you at 70% or more
  follow_up      an application you recorded a week or more ago with no
                 answer recorded since
  verify         an application recorded on your word only, not yet
                 verified from a confirmation page
  plan           a plan that stopped and can be continued
  disk           the disk nearly full

The rules that keep it from being a nuisance:

- **Optional.** `JARVIS_PROACTIVE=off` in .env, or say "stop suggestions";
  "turn on suggestions" brings them back. One kind can be turned off
  ("stop suggesting follow ups"). What you say is kept in proactive.json.
- **Rate-limited.** One suggestion at a time, at least an hour apart, at
  most four a day, and each thing once — the same job is never raised twice.
- **Quiet.** Suggestions appear in the activity log. They're spoken only if
  `JARVIS_PROACTIVE_SPEAK=on`, the voice isn't muted, and it's outside
  quiet hours (`JARVIS_QUIET_HOURS`, default 22-8).
- **Permission-aware.** A suggestion never does anything: it names the
  command you'd say. It reads only what's already on this computer — the
  job store, the plan that stopped, the disk — and sends nothing anywhere.
"""
from __future__ import annotations

import datetime
import json
import os
import threading

from . import config
from .config import log

STATE_PATH = config.MEMORY_DIR / "proactive.json"
KINDS = ("new_matches", "follow_up", "verify", "plan", "disk")
KIND_WORDS = {"new_matches": ("new jobs", "new matches", "job matches", "matches", "jobs"),
              "follow_up": ("follow ups", "follow-ups", "followups", "follow up", "applications"),
              "verify": ("verification", "verify", "verifying"),
              "plan": ("plans", "plan"),
              "disk": ("disk", "disk space", "storage")}

EVERY = 15 * 60            # seconds between looks
GAP = 60 * 60              # seconds between two suggestions
DAILY_MAX = 4
GOOD_MATCH = 70            # per cent
FOLLOW_UP_DAYS = 7
LOW_DISK_GB = 2.0
REMEMBER_DAYS = 45         # how long a raised key is kept, so it isn't raised again

_lock = threading.RLock()
_stop = threading.Event()


def _on(raw: str | None, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in ("off", "false", "no", "0")


def _quiet_hours() -> tuple[int, int]:
    raw = os.getenv("JARVIS_QUIET_HOURS", "22-8")
    try:
        start, end = (int(x) % 24 for x in raw.split("-"))
        return start, end
    except ValueError:
        return 22, 8


def quiet_now(now: datetime.datetime | None = None) -> bool:
    hour = (now or datetime.datetime.now()).hour
    start, end = _quiet_hours()
    return start <= hour or hour < end if start > end else start <= hour < end


# ------------------------------------------------------------------ state

def _load() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("raised", {})
    data.setdefault("off_kinds", [])
    return data


def _save(data: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as e:
        log(f"proactive state not saved: {e}")


def enabled() -> bool:
    data = _load()
    if isinstance(data.get("enabled"), bool):
        return data["enabled"]
    return _on(os.getenv("JARVIS_PROACTIVE"), True)


# ---------------------------------------------------------------- looking

def _new_matches(now: datetime.datetime) -> list[dict]:
    from ..jobs import store
    since = (now - datetime.timedelta(days=1)).isoformat(timespec="seconds")
    fresh = [j for j in store.top_jobs(limit=50, min_score=GOOD_MATCH)
             if (j.get("discovered_at") or "") >= since and j.get("status") in ("FOUND", "ANALYZED")]
    if not fresh:
        return []
    return [{"kind": "new_matches", "key": f"new_matches:{now.date().isoformat()}",
             "text": f"{len(fresh)} new job{'s' if len(fresh) > 1 else ''} match you at {GOOD_MATCH}% or more since "
                     f"yesterday — the best is {fresh[0]['title']} at {fresh[0]['company']} "
                     f"({fresh[0]['match_score']}%). Say: show new jobs."}]


def _applications(now: datetime.datetime) -> list[dict]:
    from ..jobs import store
    found, seen = [], set()
    for row in store.applications(limit=200):
        job = store.get_job(row["job_id"])
        if not job or row["job_id"] in seen or not row.get("applied_at"):
            continue
        seen.add(row["job_id"])
        try:
            days = (now - datetime.datetime.fromisoformat(row["applied_at"])).days
        except ValueError:
            continue
        where = f"{job['company']} — {job['title']}"
        if job["status"] in ("USER_APPROVED", "SUBMITTED") and days >= FOLLOW_UP_DAYS:
            found.append({"kind": "follow_up", "key": f"follow_up:{row['job_id']}",
                          "text": f"It's been {days} days since you applied to {where}, with no answer recorded. "
                                  f"If you've heard back, say: mark {job['company']} interview — or rejected."})
        if job["status"] == "USER_APPROVED" and days >= 1:
            found.append({"kind": "verify", "key": f"verify:{row['job_id']}",
                          "text": f"Your application to {where} is recorded on your word only. To have it "
                                  f"verified, open its confirmation page and say: verify {job['company']}."})
    return found


def _plan() -> list[dict]:
    from ..ai import planner
    plan = planner.resumable()
    if not plan:
        return []
    return [{"kind": "plan", "key": f"plan:{plan['goal']}:{plan['at']}",
             "text": f"“{plan['goal']}” stopped at step {plan['at']} of {plan['count']}. Say continue to pick it up."}]


def _disk(now: datetime.datetime) -> list[dict]:
    try:
        import psutil
        free = psutil.disk_usage(str(config.WORKSPACE.anchor or config.WORKSPACE)).free / 1e9
    except Exception:  # noqa: BLE001
        return []
    if free >= LOW_DISK_GB:
        return []
    return [{"kind": "disk", "key": f"disk:{now.date().isoformat()}",
             "text": f"Only {free:.1f} GB is free on the disk. Downloads and the browser may start failing."}]


def candidates(now: datetime.datetime | None = None) -> list[dict]:
    """Everything worth mentioning right now, most useful first. Reads only."""
    now = now or datetime.datetime.now()
    found: list[dict] = []
    for look in (lambda: _plan(), lambda: _new_matches(now), lambda: _applications(now), lambda: _disk(now)):
        try:
            found += look()
        except Exception as e:  # noqa: BLE001
            log(f"proactive look failed: {e}")
    order = {kind: n for n, kind in enumerate(KINDS)}
    found.sort(key=lambda c: order.get(c["kind"], 99) if c["kind"] != "plan" else -1)
    return found


def due(now: datetime.datetime | None = None) -> dict | None:
    """The one suggestion to make now, or None — honouring on/off, the kinds
    turned off, what was already raised, the gap and the daily cap. Marks
    it raised."""
    now = now or datetime.datetime.now()
    with _lock:
        if not enabled():
            return None
        data = _load()
        stamps = sorted(data["raised"].values())
        cutoff = (now - datetime.timedelta(days=REMEMBER_DAYS)).isoformat(timespec="seconds")
        data["raised"] = {k: v for k, v in data["raised"].items() if v >= cutoff}
        if stamps and (now - datetime.datetime.fromisoformat(stamps[-1])).total_seconds() < GAP:
            return None
        today = now.date().isoformat()
        if sum(1 for v in data["raised"].values() if v.startswith(today)) >= DAILY_MAX:
            return None
        for candidate in candidates(now):
            if candidate["kind"] in data["off_kinds"] or candidate["key"] in data["raised"]:
                continue
            data["raised"][candidate["key"]] = now.isoformat(timespec="seconds")
            _save(data)
            return candidate
        _save(data)
        return None


# ---------------------------------------------------------------- the loop

def tick(deliver, speak=None, muted=lambda: True, now: datetime.datetime | None = None) -> dict | None:
    """One look: deliver at most one suggestion. Speaks it only when asked
    to, not muted, and outside quiet hours."""
    suggestion = due(now)
    if not suggestion:
        return None
    deliver(suggestion["text"])
    if speak and _on(os.getenv("JARVIS_PROACTIVE_SPEAK"), False) and not muted() and not quiet_now(now):
        speak(suggestion["text"])
    return suggestion


def start(deliver, speak=None, muted=lambda: True, every: float = EVERY) -> threading.Thread:
    """Look every `every` seconds until stop()."""
    _stop.clear()

    def loop():
        while not _stop.wait(every):
            try:
                tick(deliver, speak, muted)
            except Exception as e:  # noqa: BLE001
                log(f"proactive tick failed: {e}")
    thread = threading.Thread(target=loop, daemon=True, name="proactive")
    thread.start()
    return thread


def stop() -> None:
    _stop.set()


# ------------------------------------------------------------- commands

def set_enabled(on: bool) -> str:
    with _lock:
        data = _load()
        data["enabled"] = on
        _save(data)
    return ("Suggestions are on. I'll mention something only now and then, and never act on it myself."
            if on else "Okay, no more suggestions. Say turn on suggestions to bring them back.")


def _kind(words: str) -> str | None:
    words = " ".join(str(words or "").lower().split())
    return next((k for k, names in KIND_WORDS.items() if words in names or words == k), None)


def set_kind(words: str, on: bool) -> str:
    kind = _kind(words)
    if not kind:
        return f"I don't make suggestions about {words}. I can stop: new jobs, follow ups, verification, plans, disk."
    with _lock:
        data = _load()
        off = set(data["off_kinds"])
        off.discard(kind) if on else off.add(kind)
        data["off_kinds"] = sorted(off)
        _save(data)
    return f"{'Back on' if on else 'Stopped'}: suggestions about {KIND_WORDS[kind][0]}."


def list_now() -> str:
    """The command "any suggestions?": everything worth mentioning, now,
    whatever was raised before. Asked for, so no limits apply."""
    found = [c for c in candidates() if c["kind"] not in _load()["off_kinds"]]
    state = "" if enabled() else " (Suggestions are off, so I won't bring these up myself.)"
    if not found:
        return "Nothing needs your attention right now." + state
    return "\n".join(c["text"] for c in found[:6]) + state
