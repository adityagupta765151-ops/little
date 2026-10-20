"""Who gets asked before something irreversible happens.

This lives on its own so every tool module can ask for confirmation
without importing the registry that imports them back.
"""
from __future__ import annotations

import itertools
import re
import threading
import time
from collections import deque
from typing import Callable


# How serious what's being asked for is. The window colours the warning by
# it; the words always say it too.
TONES = ("danger", "caution", "safe")


class Ask(str):
    """A confirmation that says what will happen, not only asks.

    It *is* the question, as text — the Tk window and the terminal show it
    exactly as before, and anything that treats it as a string still works —
    and it carries the parts the window lays out:

      action       what LITTLE wants to do          "Send a WhatsApp message"
      target       to what, or to whom             "to Rahul (+91 ••••••3210)"
      details      what you should read first      the message, the command
      consequence  what can't be taken back        "It can't be unsent."
      tone         danger, caution or safe
      verb         the button's word               "Send"
      tool         the tool asking, for Review     "send_whatsapp_message"
    """

    def __new__(cls, text: str, *, action: str, target: str = "", details: str = "",
                consequence: str = "", tone: str = "caution", verb: str = "Yes, go ahead",
                tool: str = ""):
        ask = super().__new__(cls, text)
        ask.action, ask.target, ask.details = action, target, details
        ask.consequence, ask.verb, ask.tool = consequence, verb, tool
        ask.tone = tone if tone in TONES else "caution"
        return ask

    def parts(self) -> dict:
        return {"action": self.action, "target": self.target, "details": self.details,
                "consequence": self.consequence, "tone": self.tone, "verb": self.verb,
                "tool": self.tool}


def _ask_on_the_terminal(message: str) -> bool:
    return input(f"{message} [y/N] ").strip().lower() == "y"


# Every answer given, newest last (Chapter 32): which tool asked, what for,
# yes or no, and on which thread — so a plan can tell that you said no, and
# the Security Center can show what was asked. What was asked about (a
# message, a command) is not kept: only the action and the tool.
ANSWERS_KEPT = 200
_answers: deque = deque(maxlen=ANSWERS_KEPT)
_answer_numbers = itertools.count(1)
_answers_lock = threading.Lock()


def _record(message, answer) -> None:
    first_line = str(message).strip().splitlines()[0] if str(message).strip() else ""
    with _answers_lock:
        _answers.append({"n": next(_answer_numbers), "at": time.time(), "thread": threading.get_ident(),
                         "tool": getattr(message, "tool", "") or "",
                         "action": (getattr(message, "action", "") or first_line)[:80],
                         "approved": answer is True})


def answers(since: int = 0, this_thread: bool = False) -> list[dict]:
    """The answers recorded after number `since`, oldest first."""
    me = threading.get_ident()
    with _answers_lock:
        return [dict(a) for a in _answers if a["n"] > since and (not this_thread or a["thread"] == me)]


def last_answer() -> int:
    """The number of the latest answer, to ask `answers(since=…)` later."""
    with _answers_lock:
        return _answers[-1]["n"] if _answers else 0


confirm_fn: Callable[[str], bool] = _ask_on_the_terminal


def set_confirm(fn: Callable[[str], bool]) -> None:
    """The launcher swaps this for a dialog in the panel. Whatever is
    installed, its answers are recorded."""
    global confirm_fn
    fn = getattr(fn, "asks", fn)          # installing one that is already recorded

    def asked(message):
        answer = fn(message)
        _record(message, answer)
        # Only a real yes is a yes (Chapter 37): "no", 1, a dialog's object
        # or a timeout's None can't pass a gate written as `if not confirm(...)`.
        return answer is True
    asked.asks = fn
    confirm_fn = asked


set_confirm(_ask_on_the_terminal)


def confirm(message: str) -> bool:
    """Ask. Always read through this name, never by importing confirm_fn
    directly, or a module captures whatever was installed at import time."""
    return confirm_fn(message)


# ---------------------------------------------------------- levels (Ch. 37)
#
# Every tool has a level, and a new tool without one fails the tests:
#
#   SAFE       reads; changes nothing, sends nothing beyond the request
#   LOW_RISK   changes only LITTLE's own records or the workspace, opens or
#              prepares something, or shows the model your screen on request
#   CONFIRM    can do something outside LITTLE that matters (a click that
#              submits, a step that sends); asks you when it would
#   HIGH_RISK  can't be undone or acts in your name: deleting, running a
#              command, sending a message. Asks every time.
#   BLOCKED    never runs, whatever anyone says. None by default; name tools
#              in JARVIS_BLOCKED_TOOLS (comma-separated) to block them.

SAFE, LOW_RISK, CONFIRM, HIGH_RISK, BLOCKED = "SAFE", "LOW_RISK", "CONFIRM", "HIGH_RISK", "BLOCKED"
ORDER = (SAFE, LOW_RISK, CONFIRM, HIGH_RISK, BLOCKED)

_SAFE = """application_status ask_documents browser_screenshot check_component check_github_ready check_resume
count_contacts effectiveness find_contacts find_on_page get_datetime get_system_info job_history list_dir
list_documents list_reminders look_at_page missing_skills read_file read_page recall recall_memory recall_project
search_documents search_files show_resume_profile summarize_page system_check top_matches voice_report
wa_contacts wa_read_chat why_this_job"""
_LOW_RISK = """add_contact add_document cancel_reminders close_app close_browser copy_path create_folder describe_screen
draft_whatsapp_message edit_file fill_field find_jobs find_on_screen forget forget_for_project import_contacts
mark_applied mark_job_status mark_submitted move_path note_for_task open_app open_contact open_in_vscode
open_job_board open_job_dashboard open_page open_url open_whatsapp prepare_application remember
remember_for_project remember_preference remove_document scan_resume search_web search_web_and_read
set_job_preference set_reminder shortlist_job take_screenshot update_resume_profile verify_submission wa_draft_web
wa_open wa_open_chat write_file"""
_CONFIRM = "browser_task click_on_screen click_text press_key code_change undo_code_change"
_HIGH_RISK = "delete_path run_command send_whatsapp_message wa_send_web"

LEVELS: dict[str, str] = {
    **{name: SAFE for name in _SAFE.split()},
    **{name: LOW_RISK for name in _LOW_RISK.split()},
    **{name: CONFIRM for name in _CONFIRM.split()},
    **{name: HIGH_RISK for name in _HIGH_RISK.split()},
}

# Words that make an outside tool (Chapter 39) blocked by its name alone:
# nothing that pays, enters secrets or gets past a platform's own checks
# runs here.
BLOCKED_NAMES = re.compile(
    r"pay|purchase|checkout|captcha|otp|2fa|mfa|password|credential|bypass|auto_?apply|submit_application", re.I)


def blocked_tools() -> set[str]:
    """The tools you blocked in .env (JARVIS_BLOCKED_TOOLS)."""
    import os
    return {t.strip() for t in os.getenv("JARVIS_BLOCKED_TOOLS", "").split(",") if t.strip()}


# Outside tools (Chapter 39) get their levels here when they're loaded.
EXTRA_LEVELS: dict[str, str] = {}


def level(name: str) -> str:
    """A tool's level. Blocked if you blocked it; an unknown tool is treated
    as HIGH_RISK, never as safe."""
    if name in blocked_tools():
        return BLOCKED
    return LEVELS.get(name) or EXTRA_LEVELS.get(name, HIGH_RISK)


# Tools that ask first — every time for HIGH_RISK, at the consequential
# step for CONFIRM. Applying to a job is not here because it is not
# automated at all: LITTLE fills a form and stops.
NEEDS_CONFIRMATION = {name for name, lv in LEVELS.items() if lv in (CONFIRM, HIGH_RISK)}


# ------------------------------------------- what happened (Chapter 37)
# Blocked tools, failed tool runs, and a gated tool that returned without a
# question being answered. Kept in RAM, the last 200; tool names and short
# reasons only — never arguments, which can hold messages or paths.
EVENTS_KEPT = 200
_events: deque = deque(maxlen=EVENTS_KEPT)


def note_event(kind: str, tool: str, detail: str = "") -> None:
    from ..store.memory import redact
    with _answers_lock:
        _events.append({"at": time.time(), "kind": kind, "tool": str(tool)[:80],
                        "detail": redact(" ".join(str(detail).split()))[:200]})


def events(limit: int = 50) -> list[dict]:
    with _answers_lock:
        return [dict(e) for e in list(_events)[-limit:]][::-1]
