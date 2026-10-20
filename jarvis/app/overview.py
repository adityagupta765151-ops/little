"""Dashboard 2.0 (Chapter 40): everything at a glance, from real data only.

Eleven sections — system, AI, voice, memory, tools, tasks, browser, jobs,
applications, security, logs — each read at the moment it's asked for,
from the same places the rest of LITTLE reads: psutil, the model settings,
the measured latencies, the memory files, the tool registry, the task
record, the job store, the permission record, the log file. A number
that isn't available says so ("not measured yet", "psutil isn't
installed"); nothing is estimated, and a section that can't be read says
that rather than showing zeros. Shown at the top of the System section;
"status report" says it in words.

Each section: {"id", "title", "state": "ok" | "warn" | "off", "rows":
[[label, value], ...]}. "warn" is kept for something you'd want to act on.
"""
from __future__ import annotations

import datetime

LOG_LINES = 5
LOG_CHARS = 140


def _section(id_: str, title: str, rows: list, state: str = "ok") -> dict:
    return {"id": id_, "title": title, "state": state, "rows": [[str(a), str(b)] for a, b in rows]}


def _ms(value) -> str:
    if value is None:
        return "not measured yet"
    return f"{value} ms" if value < 1000 else f"{value / 1000:.1f} s"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# ---------------------------------------------------------------- sections

def _system() -> dict:
    from . import stats
    reading = stats.system()
    rows = [["Up for", stats._uptime()]]
    if not reading.get("available"):
        return _section("system", "System", rows + [["Readings", "psutil isn't installed"]], "off")
    state = "warn" if reading["disk_free"] < 2 or reading["ram"] >= 90 else "ok"
    return _section("system", "System", rows + [
        ["CPU", f"{reading['cpu']}%"],
        ["Memory", f"{reading['ram']}% ({reading['ram_used']} of {reading['ram_total']} GB)"],
        ["Disk", f"{reading['disk']}% used, {reading['disk_free']} GB free"]], state)


def _ai() -> dict:
    from ..ai import provider
    from . import config, latency
    found = latency.summary()
    return _section("ai", "AI", [
        ["Model", config.MODEL],
        ["In use now", provider._current_model],
        ["Fast model", provider._current_fast],
        ["API key", "set" if config.API_KEY else "missing"],
        ["Typical answer", _ms(found["ai"]["p50"])],
        ["Plans run", str(found["agent"]["count"])],
    ], "ok" if config.API_KEY else "warn")


def _voice(assistant) -> dict:
    from ..voice import conversation, local_wake
    from . import latency, stats
    running = getattr(assistant, "running", None)
    muted = getattr(assistant, "muted", None)
    wake = local_wake.current or local_wake.LocalWake(recognizer=None)
    return _section("voice", "Voice", [
        ["Microphone", "unknown" if running is None else ("listening" if running else "off")],
        ["Speaking", "unknown" if muted is None else ("muted" if muted else "on")],
        ["Voice", stats._voice_label()],
        ["Name checked", "on this computer first" if wake.active() else "in the cloud"],
        ["Follow-ups", f"{conversation.FOLLOW_UP:g} s without the name" if conversation.FOLLOW_UP else "off"],
        ["Speech to text", _ms(latency.summary()["stt"]["p50"])],
    ], "ok" if running else "off")


def _memory() -> dict:
    from ..store import knowledge, memory
    contacts = [n for n, num in memory.contacts().items() if not memory.is_sample(n, num)]
    documents = knowledge.documents()
    return _section("memory", "Memory", [
        ["Facts", str(len(memory.facts()))],
        ["Preferences", str(len(memory.preferred()))],
        ["Projects", str(len(memory.project_memory()))],
        ["Contacts", str(len(contacts))],
        ["Documents", f"{len(documents)} ({_plural(sum(d['parts'] for d in documents), 'part')})"],
        ["Conversation log", _plural(len(memory.history()), "turn")],
    ])


def _tools() -> dict:
    from ..tools import catalog, external, permissions
    from . import stats
    everything = catalog.tools()
    asking = [t for t in everything if t.permission in (permissions.CONFIRM, permissions.HIGH_RISK)]
    trouble = [e for e in permissions.events(200) if e["kind"] in ("failed", "blocked")]
    last = list(stats.tool_log)[:1]
    return _section("tools", "Tools", [
        ["Tools", str(len(everything))],
        ["Ask first", str(len(asking))],
        ["Outside tools", str(len(external._tools)) if external._tools else "none"],
        ["Last run", f"{last[0][0]} ({_ms(round(last[0][1] * 1000))})" if last else "none yet"],
        ["Failed or blocked", str(len(trouble))],
    ], "warn" if trouble else "ok")


def _tasks() -> dict:
    from ..ai import planner
    from . import latency, tasks
    recent = tasks.recent(50)
    by = {s: sum(t["status"] == s for t in recent) for s in (tasks.DONE, tasks.FAILED, tasks.STOPPED)}
    open_now = sum(t["status"] in tasks.OPEN for t in recent)
    paths = {p: sum(t.get("path") == p for t in recent) for p in latency.PATHS}
    found = latency.summary()
    stopped_plan = planner.resumable()
    rows = [
        ["This session", f"{len(recent)} ({by['done']} done, {by['failed']} failed, {by['stopped']} stopped, "
                         f"{open_now} running)"],
        ["By path", ", ".join(f"{p} {n}" for p, n in paths.items())],
        ["Answered here", _ms(found["fast"]["p50"])],
        ["Plan to continue", f"step {stopped_plan['at']} of {stopped_plan['count']}" if stopped_plan else "none"],
    ]
    return _section("tasks", "Tasks", rows, "warn" if by["failed"] else "ok")


def _browser() -> dict:
    from ..tools import browser
    from . import latency
    page = browser.current_page() if browser._worker.context else None
    from urllib.parse import urlparse
    return _section("browser", "Browser", [
        ["My browser", "open" if browser._worker.context else "closed"],
        ["On", urlparse(page["url"]).netloc if page else "no page"],
        ["Job boards", "never submits or applies"],
        ["Typical step", _ms(latency.summary()["browser"]["p50"])],
    ], "ok" if browser._worker.context else "off")


def _jobs() -> dict:
    from ..jobs import store
    counts = store.counts()
    best = store.top_jobs(limit=1)
    return _section("jobs", "Jobs", [
        ["Stored", str(counts["jobs_total"])],
        ["Found today", str(counts["jobs_today"])],
        ["Best match", f"{best[0]['match_score']}% — {best[0]['title']} at {best[0]['company']}" if best else "none yet"],
        ["Average match", f"{counts['avg_score']}%" if counts["jobs_total"] else "none yet"],
    ])


def _applications() -> dict:
    from ..jobs import store
    counts = store.counts()
    pipeline = counts["pipeline"]
    return _section("applications", "Applications", [
        ["Prepared, waiting for you", str(counts["needs_action"])],
        ["Applied (your word)", str(pipeline.get("USER_APPROVED", 0))],
        ["Submitted (verified)", str(pipeline.get("SUBMITTED", 0))],
        ["Interviews", str(counts["interviews"])],
        ["Offers", str(counts["offers"])],
        ["Rejected or withdrawn", str(counts["rejected"] + pipeline.get("WITHDRAWN", 0))],
    ])


def _security() -> dict:
    from . import security
    snap = security.snapshot()
    said_no = sum(not a["approved"] for a in snap["answers"])
    levels = snap["levels"]
    return _section("security", "Security", [
        ["Asks every time", str(levels["HIGH_RISK"])],
        ["Asks when it matters", str(levels["CONFIRM"])],
        ["Blocked", ", ".join(snap["blocked"]) or "none"],
        ["Your answers", f"{len(snap['answers']) - said_no} yes, {said_no} no"],
        ["Keys set", f"{sum(k['state'] == 'set' for k in snap['keys'])} of {len(snap['keys'])}"],
    ], "warn" if snap["events"] else "ok")


def _logs() -> dict:
    from ..store.memory import redact
    from . import config
    path = config.LOG_FILE
    if not path.exists():
        return _section("logs", "Logs", [["Log file", f"none yet at {path}"]], "off")
    stat = path.stat()
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, stat.st_size - 16384))
            tail = handle.read().decode("utf-8", errors="replace").splitlines()[-LOG_LINES:]
    except OSError:
        tail = []
    rows = [["Log file", f"{path} ({stat.st_size // 1024} KB, written "
                         f"{datetime.datetime.fromtimestamp(stat.st_mtime):%H:%M})"]]
    rows += [["Latest" if i == 0 else "", redact(line)[:LOG_CHARS]] for i, line in enumerate(reversed(tail))]
    return _section("logs", "Logs", rows)


SECTIONS = (("system", _system), ("ai", _ai), ("voice", None), ("memory", _memory), ("tools", _tools),
            ("tasks", _tasks), ("browser", _browser), ("jobs", _jobs), ("applications", _applications),
            ("security", _security), ("logs", _logs))
TITLES = {"system": "System", "ai": "AI", "voice": "Voice", "memory": "Memory", "tools": "Tools",
          "tasks": "Tasks", "browser": "Browser", "jobs": "Jobs", "applications": "Applications",
          "security": "Security", "logs": "Logs"}


def snapshot(assistant=None) -> list[dict]:
    """All eleven, in order. One that can't be read says so and is marked
    off, rather than stopping the rest."""
    from .config import log
    out = []
    for id_, read in SECTIONS:
        try:
            out.append(_voice(assistant) if id_ == "voice" else read())
        except Exception as e:  # noqa: BLE001
            log(f"dashboard {id_} failed: {e}")
            out.append(_section(id_, TITLES[id_], [["Couldn't read it", type(e).__name__]], "off"))
    return out


def report(assistant=None) -> str:
    """ "Status report": one line per section. Logs are left out of the
    words — they're long and technical; the System section shows them."""
    lines = []
    for section in snapshot(assistant):
        if section["id"] == "logs":
            continue
        shown = "; ".join(f"{a.lower()} {b}" for a, b in section["rows"] if a)
        lines.append(f"{section['title']}{' (needs a look)' if section['state'] == 'warn' else ''}: {shown}.")
    return "\n".join(lines)
