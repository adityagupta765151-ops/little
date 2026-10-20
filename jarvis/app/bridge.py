"""Everything the panel is allowed to ask Python to do.

The page and Python talk through this one object, handed to pywebview as
its js_api. The page asks what changed every 200 ms (`poll`), and calls in
to send a command, answer a confirmation, or press a control. Polling
behaves the same on every pywebview version and keeps all UI work on the
UI thread.

A poll carries the new log lines, the readings, a confirmation if one is
waiting, and — when the page says which version it has — the tasks that
changed since (jarvis/app/tasks.py). Only changes travel, so the poll stays
small however long the session runs.

It lives here rather than in launcher_web.py so it can be imported — and
tested — without pywebview installed.
"""
from __future__ import annotations

import contextlib
import math
import queue
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from .. import tools
from . import stats, tasks
from .assistant import REPLY, Jarvis
from .config import API_KEY, log

# The assistant's wording -> the page's state names.
STATE_NAMES = {
    "offline": "offline",
    "calibrating": "calibrating",
    "listening": "listening",
    "waiting for command": "waiting",
    "thinking": "thinking",
    "executing": "executing",
    "speaking": "speaking",
}

# What a job card's buttons may do, and the existing tool each one uses.
# "applied" and "prepare" ask you first, through the normal confirmation.
JOB_ACTIONS = {
    "save":      ("shortlist_job", None, "Save"),
    "unsave":    ("mark_job_status", "found", "Unsave"),
    "prepare":   ("prepare_application", None, "Prepare the application for"),
    "applied":   ("mark_applied", None, "Mark as applied:"),
    "interview": ("mark_job_status", "interview", "Mark as interviewing:"),
    "offer":     ("mark_job_status", "offer", "Mark as an offer:"),
    "rejected":  ("mark_job_status", "rejected", "Mark as rejected:"),
    "withdrawn": ("mark_job_status", "withdrawn", "Mark as withdrawn:"),
    "verify":    ("verify_submission", None, "Check the submission of"),
}
EXCERPT = 400          # characters of a posting's description sent to the page

# The Resume section's six questions: (how the task reads, where it's
# answered). Skill gaps and Match use the existing job tools on this
# computer; the other four ask the model (jarvis/jobs/advice.py).
RESUME_ACTIONS = {
    "analyze":         ("Analyze my resume", "model"),
    "gaps":            ("Find my skill gaps", "local"),
    "match":           ("Match my resume against", "local"),
    "improve":         ("Suggest improvements to my resume", "model"),
    "interview":       ("Prepare me for an interview for", "model"),
    "inconsistencies": ("Find inconsistencies in my resume", "model"),
    "health":          ("Check my resume", "local"),
}
RESUME_JOBS = 25       # stored jobs offered to Match and Interview prep
JOB_EVENTS = 12        # history lines per job card
# The Jobs card's "Update status" choices, and the status each leads to.
TRACK_TO = (("applied", "USER_APPROVED"), ("verify", "SUBMITTED"), ("interview", "INTERVIEW"),
            ("offer", "OFFER"), ("rejected", "REJECTED"), ("withdrawn", "WITHDRAWN"))
MEMORY_TURNS = 15      # conversation log turns the Memory section shows
SYSTEM_AUDIT = 40      # audit trail rows the System section shows
# Where each tool's module belongs, as the Tools section groups them.
TOOL_GROUPS = {
    "files": "Files", "project_check": "Files", "registry": "Files", "system": "Your computer", "apps": "Apps", "screen": "Screen",
    "browser": "Browser", "browser_agent": "Browser", "whatsapp": "WhatsApp", "whatsapp_web": "WhatsApp",
    "contacts": "Contacts", "reminders": "Reminders", "memory": "Memory",
    "engine": "Jobs", "apply": "Jobs", "dashboard": "Jobs", "resume": "Resume",
    "resume_check": "Resume", "knowledge": "Your documents", "external": "Outside tools",
    "health": "Health", "speaking": "Voice",
}
MEMORY_TURN_CHARS = 240
# The system's Open dialog, filtered to what scanning can read.
RESUME_FILE_TYPES = ("Resumes (*.pdf;*.docx;*.doc;*.png;*.jpg;*.jpeg;*.webp;*.txt;*.md)",
                     "All files (*.*)")

# Most lines handed over per poll, so one burst can't stall the page.
LINES_PER_POLL = 40
STATS_EVERY = 0.5              # seconds between system readings
CONFIRM_TIMEOUT = 300          # seconds; nobody answering counts as no
ASK_DETAILS_MAX = 4000         # characters of a question's details sent to the page


def _pick_file() -> str | None:
    """The system's own Open dialog, in the app window. The path picked, or
    None if you cancelled. RuntimeError where there's no window to open it
    in — the plain Tk window, or a test."""
    try:
        import webview
    except ImportError as e:
        raise RuntimeError("no window") from e
    if not getattr(webview, "windows", None):
        raise RuntimeError("no window")
    kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
    if kind is None:
        kind = webview.OPEN_DIALOG
    start = next((str(d) for d in (Path.home() / "Downloads", Path.home() / "Documents")
                  if d.is_dir()), "")
    chosen = webview.windows[0].create_file_dialog(
        kind, directory=start, allow_multiple=False, file_types=RESUME_FILE_TYPES)
    if not chosen:
        return None
    return str(chosen[0] if isinstance(chosen, (list, tuple)) else chosen)


def _cursor(since) -> int | None:
    """A task version from the page: a whole number, 0 or more. Anything
    else — true, "5", -1 — is not one."""
    if isinstance(since, bool) or not isinstance(since, (int, float)):
        return None
    if isinstance(since, float) and not (math.isfinite(since) and since.is_integer()):
        return None
    return int(since) if since >= 0 else None


class Api:
    """Everything the page is allowed to ask Python to do."""

    def __init__(self, assistant: Jarvis | None = None) -> None:
        self.lines: queue.Queue = queue.Queue()
        self.status = "offline"
        self.online = False
        self._stats_due = 0.0
        self._stats: dict | None = None

        self._ask: dict | None = None
        self._answers: dict[int, bool] = {}
        self._events: dict[int, threading.Event] = {}
        self._ask_task: dict[int, int | None] = {}     # question -> the task asking it
        self._next_id = 0
        self._ask_lock = threading.Lock()

        # The Resume section: the file you picked, by a number the page
        # hands back — never a path from the page — and one resume task at
        # a time.
        self._picked: dict | None = None
        self._picks = 0
        self._resume_lock = threading.Lock()
        self._resume_task_id: int | None = None

        self.jarvis = assistant or Jarvis(log_fn=self.lines.put, status_fn=self._on_status)
        tools.set_confirm(self.confirm)

        if not API_KEY:
            self.lines.put("No GEMINI_API_KEY found. Add it to the .env file, then restart.")

    # -------------------------------------------------- from the assistant

    def _on_status(self, status: str) -> None:
        self.status = STATE_NAMES.get(status, "listening")
        self.online = status != "offline"

    def confirm(self, message: str) -> bool:
        """Ask in the page and wait. Called from a worker thread.

        Fails closed: no answer within CONFIRM_TIMEOUT is a no.
        """
        with self._ask_lock:
            self._next_id += 1
            ask_id = self._next_id
            event = threading.Event()
            self._events[ask_id] = event
            self._ask_task[ask_id] = tasks.current_id()
            self._ask = {"id": ask_id, "message": str(message)}
            # A structured question says what will happen; the window lays
            # its parts out. Long details are cut for the trip, and marked.
            parts = getattr(message, "parts", None)
            if callable(parts):
                for key, value in parts().items():
                    value = str(value or "")
                    self._ask[key] = (value[:ASK_DETAILS_MAX] + "…"
                                      if len(value) > ASK_DETAILS_MAX else value)

        # The task asking is waiting on you — a real state, shown on Home.
        tasks.waiting(str(message))
        approved = False
        try:
            if not event.wait(timeout=CONFIRM_TIMEOUT):
                with self._ask_lock:
                    self._events.pop(ask_id, None)
                    if self._ask and self._ask.get("id") == ask_id:
                        self._ask = None
                return False
            with self._ask_lock:
                approved = self._answers.pop(ask_id, False)
            return approved
        finally:
            with self._ask_lock:
                self._ask_task.pop(ask_id, None)
            tasks.answered(approved)

    # -------------------------------------------------- from the page

    def poll(self, since=None) -> dict:
        """What changed. `since` is the task version the page already has;
        without one, no tasks are sent (callers from before tasks existed)."""
        lines = []
        while not self.lines.empty() and len(lines) < LINES_PER_POLL:
            lines.append(self.lines.get())

        payload: dict = {"status": self.status, "lines": lines}

        # Readings are gathered twice a second, not on every poll, so the
        # panel stays live without the panel itself costing anything.
        now = time.monotonic()
        if now >= self._stats_due:
            self._stats_due = now + STATS_EVERY
            try:
                self._stats = stats.snapshot(self.jarvis, self.jarvis.muted)
            except Exception as e:  # noqa: BLE001
                log(f"stats failed: {e}")
        if self._stats:
            payload["stats"] = self._stats

        cursor = _cursor(since)
        if cursor is not None:
            version, changed = tasks.changed_since(cursor)
            payload["tasks"] = {"v": version, "changed": changed}

        with self._ask_lock:
            if self._ask:
                payload["ask"] = self._ask
                self._ask = None
        return payload

    def confirm_reply(self, ask_id: int, ok: bool) -> None:
        """Only a question that is actually waiting can be answered, and only
        a real true approves — not "true", not 1."""
        with self._ask_lock:
            event = self._events.pop(ask_id, None)
            if event is None:
                log(f"ignored an answer to confirmation {ask_id!r}, which isn't waiting")
                return
            self._answers[ask_id] = ok is True
        event.set()

    def toggle(self) -> None:
        if self.online:
            self.jarvis.stop()
        else:
            self.online = True
            self.jarvis.start()

    def send(self, text: str) -> None:
        text = (text or "").strip() if isinstance(text, str) else ""
        if text:
            threading.Thread(target=self.jarvis.handle, args=(text,), daemon=True).start()

    # -------------------------------------------------- Chat's actions

    def speak(self, task_id) -> str:
        """Read a reply out again, as briefly as it was the first time.
        Returns "" when it starts, or why it can't."""
        task = tasks.get(task_id)
        if not task or not task["reply"].strip():
            return "There's nothing to read out for that one."
        if self.jarvis.muted:
            return "Voice is muted. Unmute it to hear this."
        from ..voice.brief import for_speech
        threading.Thread(target=self.jarvis.say, args=(for_speech(task["reply"]),),
                         daemon=True).start()
        return ""

    def save(self, task_id) -> str:
        """Keep a turn in the notes file in your workspace. Says where."""
        task = tasks.get(task_id)
        if not task or not task["reply"].strip():
            return "There's nothing to save for that one."
        from ..store import notes
        try:
            where = notes.save_turn(task["text"], task["reply"], task["started"])
        except OSError as e:
            log(f"save failed: {e}")
            return "I couldn't write the notes file. Check the workspace folder."
        return f"Saved to {where.name}, in your workspace."

    def regenerate(self, task_id) -> str:
        """Ask the model the same question again. Only its latest plain
        answer — one that ran no tools, so nothing gets done twice. Returns
        "" when it has started, or why it can't."""
        task = tasks.get(task_id)
        if (not task or task["status"] != tasks.DONE or task["route"] != "model"
                or task["steps"]):
            return "Only a plain answer from the model can be asked again."
        latest = tasks.latest("model")
        if not latest or latest["id"] != task["id"]:
            return "Only the latest answer can be asked again."
        # Refuse rather than wait: the assistant is busy until the command in
        # hand finishes, and this call comes from the window.
        if tasks.current() is not None:
            return "I'm still working on something. Ask again when I'm done."
        asker = getattr(self.jarvis, "regenerate", None)
        if asker is None:
            return "Asking again isn't available here."
        return asker(task["text"], task["id"])

    def cancel(self, task_id) -> str:
        """The Task Center's "Stop this". Returns "" when the task has been
        asked to stop, or why it can't be.

        A task stops at its next step, so only one that has steps between
        which to stop can be: the model working through tools, or a plan.
        A command answered on this computer is one call — it finishes on its
        own. A question the task is waiting on is answered No, so it can."""
        task = tasks.get(task_id)
        if not task or task["status"] not in tasks.OPEN:
            return "That one has already finished."
        if task["stopping"]:
            return "It's already stopping."
        if task["route"] not in ("model", "plan") and task["status"] != tasks.WAITING:
            return "That one runs on this computer in one go and can't be stopped partway. It will finish on its own."
        tasks.request_stop(task["id"])
        with self._ask_lock:
            asked = [a for a, t in self._ask_task.items() if t == task["id"] and a in self._events]
        for ask_id in asked:
            self.confirm_reply(ask_id, False)
        return ""

    # -------------------------------------------------- the Jobs section

    def jobs(self) -> dict:
        """What the Jobs section shows, read fresh from the job store. Only
        reads. Asked for when the section opens and after an action, not on
        every poll — sixty scored jobs are too much to send five times a
        second."""
        from ..jobs import dashboard
        try:
            state = dashboard.state()
        except Exception as e:  # noqa: BLE001
            log(f"jobs state failed: {e}")
            return {"error": "I couldn't read the job store."}
        from ..jobs import store
        jobs = []
        for job in state["jobs"]:
            job = dict(job)
            description = job.pop("description", "") or ""
            job["excerpt"] = description[:EXCERPT] + ("…" if len(description) > EXCERPT else "")
            # The card's history and the moves it can make from here — the
            # store's own rules, so the page never offers one it would refuse.
            try:
                job["events"] = store.history(job["job_id"], limit=JOB_EVENTS)
            except Exception as e:  # noqa: BLE001
                log(f"job history failed: {e}")
                job["events"] = []
            allowed = store.TRANSITIONS.get(job.get("status"), set())
            job["next"] = [action for action, target in TRACK_TO if target in allowed]
            jobs.append(job)
        resume = state["resume"]
        return {
            "jobs": jobs,
            "counts": state["counts"],
            "missing_skills": [list(pair) for pair in state["missing_skills"]],
            "resume": {"name": resume["name"], "file": resume["file"], "roles": resume["roles"],
                       "ready": bool(resume["file"] or resume["skills"])},
        }

    def job(self, job_id, action) -> str:
        """A job card's button. Runs the existing tool on that exact job, as
        a task — so it shows on Home, in Chat and in the Task Center — and,
        for preparing an application or saying you applied, asks first.
        Returns "" when it has started, or why it can't."""
        from ..jobs import store
        if action not in JOB_ACTIONS:
            return "That isn't something I can do with a job."
        job = store.get_job(job_id) if isinstance(job_id, str) and job_id else None
        if not job:
            return "I can't find that job any more."
        threading.Thread(target=self._job_task, args=(job, action), daemon=True).start()
        return ""

    def _job_task(self, job: dict, action: str) -> None:
        from ..tools import permissions
        from ..tools.registry import execute_tool

        tool, status, verb = JOB_ACTIONS[action]
        text = f"{verb} “{job['title']}” at {job['company']}"
        self.lines.put(f"You: {text}")
        tid = tasks.start(text)
        tasks.route("local")
        reply, outcome = "", tasks.DONE
        # Wait for whatever else is running: preparing uses the browser, and
        # so might the model's tools.
        busy = getattr(self.jarvis, "_busy", None) or contextlib.nullcontext()
        try:
            with busy:
                question = None
                where = f"“{job['title']}” at {job['company']}"
                if action == "prepare":
                    question = permissions.Ask(
                        f"Open {where} in the browser and fill in "
                        f"your name, email, phone and location from your resume?\n\n"
                        f"Nothing is submitted. You check every field and press submit yourself.",
                        action="Open an application and fill it in", target=where,
                        details="Your name, email, phone and location, from your resume.",
                        consequence="Nothing is submitted. You check every field and press submit yourself.",
                        tone="safe", verb="Open and fill", tool="prepare_application")
                elif action == "applied":
                    question = permissions.Ask(
                        f"Record that you applied to {where}?\n\n"
                        f"Only say yes if you submitted the application yourself.",
                        action="Record that you applied", target=where,
                        consequence="Only say yes if you submitted the application yourself.",
                        tone="caution", verb="Record it", tool="mark_applied")
                if question and permissions.confirm(question) is not True:
                    reply = "Okay, I left it." if action == "prepare" else "Okay, nothing recorded."
                else:
                    args = {"reference": f"id:{job['job_id']}"}
                    if status:
                        args["status"] = status
                    reply = execute_tool(tool, args)
        except Exception as e:  # noqa: BLE001
            log(f"job action {action} failed: {e}")
            reply, outcome = f"That didn't work: {e}", tasks.FAILED
        tasks.reply(reply)
        self.lines.put(f"{REPLY}{reply}")
        tasks.finish(outcome, reply if outcome == tasks.FAILED else "", task_id=tid)

    # -------------------------------------------------- the Resume section

    def resume(self) -> dict:
        """What the Resume section shows, read fresh. Only reads. Asked for
        when the section opens and after a task ends, not on every poll."""
        from ..jobs import engine, store
        from ..jobs import resume as cv
        try:
            profile = cv.load_profile()
        except Exception as e:  # noqa: BLE001
            log(f"resume state failed: {e}")
            return {"error": "I couldn't read your resume profile."}
        person = profile.get("candidate", {})
        ready = cv.is_ready(profile)
        prefs = cv.preferences(profile)
        try:
            jobs = [{"id": j["job_id"], "title": j["title"], "company": j["company"],
                     "score": j.get("match_score")} for j in store.top_jobs(limit=RESUME_JOBS)]
            gaps = [list(pair) for pair in store.missing_skill_counts(12)]
        except Exception as e:  # noqa: BLE001
            log(f"resume jobs failed: {e}")
            jobs, gaps = [], []
        try:
            found = cv.resume_file(profile) if ready else None
        except OSError:
            found = None
        # With no countries set, the search takes the one in your address.
        home = (person.get("location") or "").split(",")[-1].strip()
        current = tasks.get(self._resume_task_id) if self._resume_task_id else None
        return {
            "ready": ready,
            "candidate": {key: person.get(key, empty) for key, empty in cv.EMPTY_PROFILE["candidate"].items()},
            "file": profile.get("source_file", "") if ready else "",
            "file_found": found is not None,
            "scanned_at": profile.get("scanned_at", "") if ready else "",
            "preferences": prefs,
            "yours": cv.yours(profile),
            "edited": cv.edited(profile) if ready else [],
            "choices": {field: list(values) for field, values in cv.CHOICES.items()},
            "limits": {"items": cv.MAX_ITEMS, "chars": cv.MAX_CHARS,
                       "roles_searched": engine.MAX_QUERIES},
            "home_country": home,
            "suggestions": [] if ready else cv.list_candidate_resumes(4),
            "jobs": jobs,
            "gaps": gaps,
            "running": current["id"] if current and current["status"] in tasks.OPEN else None,
        }

    def choose_resume(self) -> dict:
        """Open the system's file dialog. Returns the file's name and a
        number to scan it by — {"token", "name"} — or {"cancelled": True},
        or {"error"}. Nothing is read yet."""
        from ..jobs import resume as cv
        try:
            chosen = _pick_file()
        except RuntimeError:
            return {"error": "The file picker only opens in the app window. "
                             "Type: scan my resume and the file's name."}
        except Exception as e:  # noqa: BLE001
            log(f"file dialog failed: {e}")
            return {"error": "The file picker didn't open. Try again."}
        if not chosen:
            return {"cancelled": True}
        path = Path(chosen)
        if path.suffix.lower() not in cv.RESUME_SUFFIXES:
            return {"error": "That isn't a file I can read. Pick a PDF, Word file, image or text file."}
        if not path.is_file():
            return {"error": "I can't open that file."}
        with self._ask_lock:
            self._picks += 1
            self._picked = {"token": self._picks, "path": str(path)}
            return {"token": self._picks, "name": path.name}

    def scan_picked(self, token) -> dict:
        """Scan the file just picked, as a task. Only the latest pick, and
        only once. Returns {"task": id}, or {"error"}."""
        with self._ask_lock:
            picked = self._picked
            if (not picked or isinstance(token, bool) or not isinstance(token, int)
                    or token != picked["token"]):
                return {"error": "Choose the file again."}
            self._picked = None
        return self._start_resume_task(self._scan_task, Path(picked["path"]))

    def save_preferences(self, values) -> dict:
        """The preferences form. Checked and saved all together, or not at
        all. Returns {"preferences", "yours", "message"} or {"error"}."""
        from ..jobs import resume as cv
        try:
            saved, message = cv.set_preferences(values)
        except Exception as e:  # noqa: BLE001
            log(f"saving preferences failed: {e}")
            return {"error": "I couldn't save them. Check the memory folder."}
        if saved is None:
            return {"error": message}
        return {"preferences": saved, "yours": cv.yours(cv.load_profile()), "message": message}

    def resume_action(self, action, job_id=None) -> dict:
        """One of the six questions, as a task — so it shows on Home, in Chat
        and in the Task Center too. Match needs a stored job; Interview prep
        takes one or uses your target roles. Returns {"task": id} or
        {"error"}."""
        from ..jobs import resume as cv
        from ..jobs import store
        if not isinstance(action, str) or action not in RESUME_ACTIONS:
            return {"error": "That isn't something I can do with your resume."}
        if not cv.is_ready(cv.load_profile()):
            return {"error": "Scan your resume first."}
        job = None
        if action == "match" or (action == "interview" and job_id not in (None, "")):
            if action == "match" and job_id in (None, ""):
                return {"error": "Pick a job to match against."}
            job = store.get_job(job_id) if isinstance(job_id, str) and job_id else None
            if not job:
                return {"error": "I can't find that job any more."}
        return self._start_resume_task(self._resume_task, action, job)

    # One resume task at a time, and the page gets its id straight away.

    def _start_resume_task(self, work, *args) -> dict:
        if not self._resume_lock.acquire(blocking=False):
            return {"error": "Wait for the resume task that's running to finish."}
        started: dict = {}
        ready = threading.Event()

        def run():
            try:
                work(*args, started=started, ready=ready)
            finally:
                ready.set()
                self._resume_lock.release()

        threading.Thread(target=run, daemon=True).start()
        ready.wait(timeout=5)
        return {"task": started["id"]} if "id" in started else {"error": "It didn't start. Try again."}

    def _begin(self, text: str, started: dict, ready: threading.Event) -> int:
        self.lines.put(f"You: {text}")
        tid = tasks.start(text)
        self._resume_task_id = tid
        started["id"] = tid
        ready.set()
        return tid

    def _end(self, tid: int, reply: str, outcome: str) -> None:
        tasks.reply(reply, task_id=tid)
        self.lines.put(f"{REPLY}{reply}")
        tasks.finish(outcome, reply if outcome == tasks.FAILED else "", task_id=tid)

    @contextlib.contextmanager
    def _showing(self, state: str):
        """The orb shows the work while it happens, then goes back — unless
        something else changed it meanwhile."""
        before = self.status
        self.status = state
        try:
            yield
        finally:
            if self.status == state:
                self.status = before

    def _read_step(self, read, name: str):
        """Reading the resume, as a step you can see. Returns what `read`
        returned."""
        n = tasks.step_started("read_resume", name)
        try:
            out = read()
        except Exception as e:
            tasks.step_finished(n, str(e) or "couldn't read it")
            raise
        tasks.step_finished(n)
        return out

    def _scan_task(self, path: Path, started: dict, ready: threading.Event) -> None:
        """Read the file, have the model structure it, save it — keeping
        the preferences you set. Stops between reading and asking if you
        say so, and then nothing changes."""
        from ..jobs import resume as cv
        tid = self._begin(f"Scan my resume “{path.name}”", started, ready)
        reply, outcome = "", tasks.DONE
        busy = getattr(self.jarvis, "_busy", None) or contextlib.nullcontext()
        try:
            with busy:
                tasks.route("model")
                with self._showing("executing"):
                    text = self._read_step(lambda: cv.extract_text(path), path.name)
                if len(text.strip()) < cv.MIN_TEXT:
                    reply, outcome = cv.UNREADABLE, tasks.FAILED
                else:
                    tasks.check_stop()
                    with self._showing("thinking"):
                        profile, why_not = cv.structure(text, path)
                    if profile is None:
                        reply, outcome = why_not, tasks.FAILED
                    else:
                        reply = cv.save_scanned(profile)
        except tasks.Stopped:
            reply, outcome = "Stopped. Your profile wasn't changed.", tasks.STOPPED
        except Exception as e:  # noqa: BLE001
            log(f"resume scan failed: {e}")
            reply, outcome = f"That didn't work: {e}", tasks.FAILED
        self._end(tid, reply, outcome)

    def _resume_task(self, action: str, job: dict | None, started: dict,
                     ready: threading.Event) -> None:
        from ..jobs import advice, store
        from ..jobs import resume as cv
        from ..tools.registry import execute_tool

        words, where = RESUME_ACTIONS[action]
        if action == "match":
            text = f"{words} “{job['title']}” at {job['company']}"
        elif action == "interview":
            text = (f"{words} “{job['title']}” at {job['company']}" if job
                    else f"{words} my target roles")
        else:
            text = words
        tid = self._begin(text, started, ready)
        reply, outcome = "", tasks.DONE
        busy = getattr(self.jarvis, "_busy", None) or contextlib.nullcontext()
        try:
            with busy:
                tasks.route(where)
                if action == "gaps":
                    with self._showing("executing"):
                        reply = execute_tool("missing_skills", {})
                elif action == "health":
                    with self._showing("executing"):
                        reply = execute_tool("check_resume", {})
                elif action == "match":
                    with self._showing("executing"):
                        reply = execute_tool("why_this_job", {"reference": f"id:{job['job_id']}"})
                else:
                    profile = cv.load_profile()
                    with self._showing("executing"):
                        body, source = self._read_step(lambda: cv.resume_text(profile),
                                                       profile.get("source_file") or "saved profile")
                    tasks.check_stop()
                    gaps = store.missing_skill_counts(8)
                    with self._showing("thinking"):
                        answer = advice.ask(action, body, source, profile, job, gaps)
                    note = ("" if source != "your saved profile" else
                            "From your saved profile — I couldn't find the resume file itself, "
                            "so this can't quote its exact wording.\n\n")
                    reply = note + answer
                    # So a follow-up question in the conversation knows what was said.
                    if hasattr(self.jarvis, "brain"):
                        if self.jarvis.brain is None:
                            from ..ai.brain import Brain
                            self.jarvis.brain = Brain()
                        self.jarvis.brain.note_exchange(text, reply)
        except tasks.Stopped:
            reply, outcome = "Stopped.", tasks.STOPPED
        except Exception as e:  # noqa: BLE001
            log(f"resume action {action} failed: {e}")
            reply, outcome = str(e) or "Something went wrong on my side.", tasks.FAILED
        self._end(tid, reply, outcome)

    # -------------------------------------------------- the Projects section

    def projects(self) -> dict:
        """Your projects, from the resume profile. Only reads."""
        from ..jobs import projects as proj
        from ..jobs import resume as cv
        try:
            profile = cv.load_profile()
        except Exception as e:  # noqa: BLE001
            log(f"projects failed: {e}")
            return {"error": "I couldn't read your resume profile."}
        return {"ready": cv.is_ready(profile),
                "file": profile.get("source_file", "") if cv.is_ready(profile) else "",
                "projects": proj.from_profile(profile),
                "not_in_a_line": list(proj.NOT_IN_A_LINE)}

    def open_project_link(self, project, link) -> str:
        """Open a web address written in a project's line, in your normal
        browser. Named by position; Python reads the address itself, and
        opens only http or https. Returns "" when opened, or why not."""
        import webbrowser

        from ..jobs import projects as proj
        from ..jobs import resume as cv
        found = proj.from_profile(cv.load_profile())
        ok = lambda n, size: isinstance(n, int) and not isinstance(n, bool) and 0 <= n < size  # noqa: E731
        if not ok(project, len(found)) or not ok(link, len(found[project]["links"])):
            return "That link isn't in your resume any more."
        url = found[project]["links"][link]
        if urlparse(url).scheme not in ("http", "https"):
            return "That isn't a web address, so I won't open it."
        webbrowser.open(url)
        return ""

    # -------------------------------------------------- the Memory section

    def memory_view(self) -> dict:
        """What LITTLE keeps about you, read fresh. Contact numbers come
        masked — the page never gets them whole. Only reads."""
        from ..jobs import resume as cv
        from ..jobs import store
        from ..store import memory
        from .config import MEMORY_DIR
        try:
            facts = memory.facts()
            preferred = memory.preferred()
            projects = memory.project_memory()
            book = memory.contacts()
            turns = memory.history()
        except Exception as e:  # noqa: BLE001
            log(f"memory view failed: {e}")
            return {"error": "I couldn't read the memory folder."}
        try:
            profile = cv.load_profile()
            person = profile.get("candidate", {})
            resume = {"ready": cv.is_ready(profile), "name": person.get("name", ""),
                      "skills": len(person.get("skills", [])), "projects": len(person.get("projects", []))}
        except Exception:  # noqa: BLE001
            resume = {"ready": False, "name": "", "skills": 0, "projects": 0}
        try:
            counts = store.counts()
            jobs = {"total": counts.get("jobs_total", 0), "applied": counts.get("applied", 0)}
        except Exception:  # noqa: BLE001
            jobs = {"total": 0, "applied": 0}

        try:
            from ..store import knowledge
            documents = [{"name": d["name"], "pages": d["pages"], "parts": d["parts"], "added": d["added"]}
                         for d in knowledge.documents()]
        except Exception as e:  # noqa: BLE001
            log(f"knowledge list failed: {e}")
            documents = []

        def cut(text) -> str:
            text = " ".join(str(text or "").split())
            return text[:MEMORY_TURN_CHARS] + ("…" if len(text) > MEMORY_TURN_CHARS else "")

        return {
            "facts": [{"key": k, "value": v} for k, v in facts.items()],
            "preferences": [{"key": k, "value": v} for k, v in preferred.items()],
            "projects": [{"name": name, "facts": [{"key": k, "value": v} for k, v in notes.items()]}
                         for name, notes in projects.items()],
            "contacts": [{"name": name, "number": memory.mask(number),
                          "sample": memory.is_sample(name, number)}
                         for name, number in sorted(book.items())],
            "log": {"count": len(turns), "keep": memory.HISTORY_KEEP,
                    "recent": [{"user": cut(t.get("user")), "assistant": cut(t.get("assistant"))}
                               for t in reversed(turns[-MEMORY_TURNS:])]},
            "resume": resume,
            "jobs": jobs,
            "documents": documents,
            "folder": str(MEMORY_DIR),
        }

    def forget_fact(self, key, scope=None, project=None) -> dict:
        """Forget one thing you asked to be remembered, by its exact key: a
        fact, or with `scope` a preference or one project's fact."""
        from ..store import memory
        if scope == "preference":
            if not isinstance(key, str) or key not in memory.preferred():
                return {"error": "I had nothing stored under that."}
            message = memory.forget_preference(key)
        elif scope == "project":
            notes = memory.project_memory().get(project) if isinstance(project, str) else None
            if not isinstance(key, str) or not notes or key not in notes:
                return {"error": "I had nothing stored under that."}
            message = memory.forget_for_project(project, key)
        else:
            if not isinstance(key, str) or key not in memory.facts():
                return {"error": "I had nothing stored under that."}
            message = memory.forget(key)
        log(f"memory: forgot a {scope or 'fact'} ({len(key)} chars)")
        return {"message": message}

    def remove_contact(self, name) -> dict:
        """Remove one contact, by its exact saved name."""
        from ..store import memory
        message = memory.remove_contact(name) if isinstance(name, str) and name else None
        if message is None:
            return {"error": "That contact isn't saved any more."}
        log("memory: removed a contact")
        return {"message": message}

    def clear_log(self) -> dict:
        """Empty the conversation log."""
        from ..store import memory
        count = memory.clear_history()
        log(f"memory: cleared the conversation log ({count} turns)")
        return {"message": f"Cleared {count} turn{'' if count == 1 else 's'} from the log."}

    # -------------------------------------------------- the System section

    def system(self) -> dict:
        """Every setting in effect, the microphones, what asks first, and
        the audit trail. Keys are only ever "set" or "missing". Only reads."""
        from ..jobs import store
        from ..voice import Listener
        from . import settings
        try:
            groups = settings.groups(self.jarvis)
        except Exception as e:  # noqa: BLE001
            log(f"settings failed: {e}")
            return {"error": "I couldn't read the settings."}
        try:
            mics = Listener.devices()
        except Exception:  # noqa: BLE001
            mics = []
        try:
            audit = [{k: row.get(k) for k in ("timestamp", "action", "platform", "company",
                                               "job", "result", "error")}
                     for row in store.audit_trail(SYSTEM_AUDIT)]
        except Exception as e:  # noqa: BLE001
            log(f"audit trail failed: {e}")
            audit = []
        try:
            from . import overview
            glance = overview.snapshot(self.jarvis)
        except Exception as e:  # noqa: BLE001
            log(f"dashboard failed: {e}")
            glance = None
        try:
            from . import security
            guarded = security.snapshot()
        except Exception as e:  # noqa: BLE001
            log(f"security snapshot failed: {e}")
            guarded = None
        return {"groups": groups, "env": settings.env_file(), "mics": mics,
                "asks_first": settings.asks_first(), "tools": settings.tool_count(),
                "audit": audit, "muted": bool(getattr(self.jarvis, "muted", False)),
                "listening": bool(getattr(self.jarvis, "running", False)), "security": guarded,
                "dashboard": glance}

    def health(self, live=False) -> dict:
        """The health check, probe by probe: what's wrong, why, and the fix.
        `live` also asks the model — one real request — so only when the
        button that says so is pressed."""
        from . import health as probes
        checks = probes.run_checks(include_live=live is True)
        return {"checks": [{"group": c.group, "state": c.state, "detail": c.detail,
                            "problem": c.problem, "cause": c.cause, "fix": c.fix} for c in checks]}

    def test_voice(self) -> str:
        """Say a sentence in the voice as set. Returns "" when it starts,
        or why it can't."""
        if getattr(self.jarvis, "muted", False):
            return "Voice is muted. Unmute it to hear this."
        from .config import ASSISTANT_CALL
        line = f"Hi, I'm {ASSISTANT_CALL}. This is how I sound."
        threading.Thread(target=self.jarvis.say, args=(line,), daemon=True).start()
        return ""

    # -------------------------------------------------- the Tools section

    def tools(self) -> dict:
        """Every tool, what it does in its own words, where it belongs, and
        whether it asks first. Only reads."""
        from ..tools import catalog
        from ..tools.permissions import CONFIRM, HIGH_RISK
        out = []
        for tool in catalog.tools():
            item = tool.public()
            item["asks"] = tool.permission in (CONFIRM, HIGH_RISK)
            out.append(item)
        return {"tools": out}

    def open_posting(self, job_id) -> str:
        """Open a job's own posting in your normal browser. Only a web
        address is opened — a stored link that is anything else is refused."""
        import webbrowser

        from ..jobs import store
        job = store.get_job(job_id) if isinstance(job_id, str) and job_id else None
        if not job:
            return "I can't find that job any more."
        url = (job.get("url") or "").strip()
        if not url:
            return "This one has no link stored."
        if urlparse(url).scheme not in ("http", "https"):
            return "That link isn't a web address, so I won't open it."
        webbrowser.open(url)
        store.audit("open_posting", platform=job.get("platform", ""), company=job["company"],
                    job=job["title"], result="opened")
        return ""

    def control(self, action: str) -> str:
        if action == "stop":
            self.jarvis.interrupt()
            return ""
        if action == "mute":
            self.jarvis.muted = not self.jarvis.muted
            return "Unmute voice" if self.jarvis.muted else "Mute voice"
        if action == "browser":
            def job():
                from ..tools import browser
                self.lines.put(browser.close_browser())
            threading.Thread(target=job, daemon=True).start()
            return ""
        return ""
