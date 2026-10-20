"""Tool registry 2.0 (Chapter 38): every tool, described in full.

For each tool: its name, what it does, its parameters, its permission level
(Chapter 37), its timeout, the function that handles it, what it uses (my
browser, your browser, the internet, the model, files, the screen,
messages, this computer), and its logging policy — how much of its
arguments may appear in the activity log and the task record:

  args      its arguments, cut short, anything secret-looking hidden
  names     only which arguments it had, never their values: messages,
            contact numbers, what you asked to be remembered, file contents
  none      nothing at all

Built from what's actually registered — FUNCTIONS, TOOL_SCHEMAS and the
permission levels — so it can't drift from them; a tool missing from any
of them fails the tests. The questions "what tools do you have?", "which
tools use the browser?" and "which tools require confirmation?" are
answered from here, on this computer.

Timeouts: a SAFE tool (it only reads) that runs past its timeout is stopped
waiting for — it can't have changed anything. For anything that changes
things, the timeout is advisory: it's shown and a run past it is recorded
as slow, but it isn't abandoned halfway through an action.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import permissions

# What each tool reaches, beyond LITTLE's own memory folder.
MY_BROWSER, YOUR_BROWSER, INTERNET, MODEL, FILES, SCREEN, MESSAGES, COMPUTER = (
    "my browser", "your browser", "the internet", "the model", "files", "the screen", "messages", "this computer")
OUTSIDE = "an outside tool"

_USES = {
    MY_BROWSER: """open_page read_page summarize_page click_text fill_field press_key browser_screenshot
                   close_browser find_on_page look_at_page browser_task prepare_application verify_submission
                   search_web_and_read wa_open wa_contacts wa_open_chat wa_read_chat wa_draft_web wa_send_web
                   click_on_screen""",
    YOUR_BROWSER: "open_url search_web open_job_board open_job_dashboard",
    INTERNET: """open_page read_page summarize_page search_web_and_read find_jobs browser_task look_at_page
                 prepare_application wa_open wa_contacts wa_open_chat wa_read_chat wa_draft_web wa_send_web""",
    MODEL: """describe_screen find_on_screen click_on_screen summarize_page ask_documents scan_resume
              browser_task search_web_and_read code_change""",
    FILES: """list_dir read_file write_file edit_file create_folder move_path copy_path delete_path search_files
              check_github_ready add_document scan_resume import_contacts open_in_vscode take_screenshot code_change
              undo_code_change""",
    SCREEN: "take_screenshot describe_screen find_on_screen click_on_screen",
    MESSAGES: """draft_whatsapp_message send_whatsapp_message open_whatsapp open_contact wa_open wa_contacts
                 wa_open_chat wa_read_chat wa_draft_web wa_send_web""",
    COMPUTER: """run_command open_app close_app get_system_info open_in_vscode system_check check_component
                 click_on_screen code_change""",
}
USES: dict[str, set[str]] = {}
for _what, _listed in _USES.items():
    for _name in _listed.split():
        USES.setdefault(_name, set()).add(_what)

# How much of a tool's arguments may be shown or kept.
_NAMES_ONLY = """send_whatsapp_message draft_whatsapp_message wa_draft_web wa_send_web add_contact remember
                 remember_for_project remember_preference note_for_task write_file edit_file fill_field
                 update_resume_profile mark_submitted set_reminder"""
LOG_POLICY = {name: "names" for name in _NAMES_ONLY.split()}

# Seconds. By what a tool reaches; a few need longer.
TIMEOUTS = {"code_change": 900, "find_jobs": 180, "search_web_and_read": 120, "browser_task": 300, "scan_resume": 180,
            "system_check": 90, "run_command": 600, "ask_documents": 120, "add_document": 120,
            "prepare_application": 120, "check_github_ready": 60, "search_files": 60}


def timeout_for(name: str) -> int:
    if name in TIMEOUTS:
        return TIMEOUTS[name]
    uses = USES.get(name, set())
    if MODEL in uses or MY_BROWSER in uses:
        return 90
    if INTERNET in uses:
        return 60
    return 30


def log_policy(name: str) -> str:
    return LOG_POLICY.get(name, "args")


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    required: list
    permission: str
    timeout: int
    handler: object
    group: str
    uses: list = field(default_factory=list)
    log: str = "args"

    def public(self) -> dict:
        """Everything but the handler, for the window and the tests."""
        return {"name": self.name, "does": self.description, "params": self.params, "required": self.required,
                "level": self.permission, "timeout": self.timeout, "group": self.group,
                "uses": self.uses, "log": self.log}


def tools() -> list[Tool]:
    """Every registered tool, in full, by group then name."""
    from ..app.bridge import TOOL_GROUPS
    from .registry import FUNCTIONS, TOOL_SCHEMAS
    out = []
    for schema in TOOL_SCHEMAS:
        name = schema["name"]
        handler = FUNCTIONS.get(name)
        module = getattr(handler, "__module__", "") or ""
        spec = schema.get("input_schema", {})
        out.append(Tool(name=name, description=schema.get("description", ""),
                        params=dict(spec.get("properties", {})), required=list(spec.get("required", [])),
                        permission=permissions.level(name), timeout=timeout_for(name), handler=handler,
                        group=TOOL_GROUPS.get(module.rsplit(".", 1)[-1], "Other"),
                        uses=sorted(USES.get(name, set())), log=log_policy(name)))
    return sorted(out, key=lambda t: (t.group, t.name))


def get(name: str) -> Tool | None:
    return next((t for t in tools() if t.name == name), None)


# ------------------------------------------------------------- questions

def _names(found: list[Tool]) -> str:
    return ", ".join(sorted(t.name for t in found))


def what_tools() -> str:
    """ "What tools do you have?" """
    found = tools()
    groups: dict[str, int] = {}
    for t in found:
        groups[t.group] = groups.get(t.group, 0) + 1
    asking = [t for t in found if t.permission in (permissions.CONFIRM, permissions.HIGH_RISK)]
    return (f"{len(found)} tools in {len(groups)} groups: "
            + ", ".join(f"{g} {n}" for g, n in sorted(groups.items()))
            + f". {len(asking)} of them ask you first. The Tools section lists every one.")


def using(what: str) -> str:
    """ "Which tools use the browser?" — and the internet, the model, files,
    the screen, messages, this computer."""
    words = " ".join(str(what or "").lower().split())
    if "browser" in words:
        mine = [t for t in tools() if MY_BROWSER in t.uses]
        yours = [t for t in tools() if YOUR_BROWSER in t.uses]
        return (f"In my own browser ({len(mine)}): {_names(mine)}. "
                f"In your normal browser ({len(yours)}): {_names(yours)}.")
    aliases = {OUTSIDE: ("mcp", "outside", "external"),
               INTERNET: ("internet", "network", "web", "online"), MODEL: ("model", "ai", "gemini"),
               FILES: ("file", "files", "disk"), SCREEN: ("screen", "screenshot"),
               MESSAGES: ("message", "messages", "whatsapp"), COMPUTER: ("computer", "system", "command")}
    for key, names in aliases.items():
        if any(w in words.split() for w in names):
            found = [t for t in tools() if key in t.uses]
            return f"{len(found)} tools use {key}: {_names(found)}."
    return ("I can say which tools use the browser, the internet, the model, files, the screen, messages or "
            "this computer.")


def asking() -> str:
    """ "Which tools require confirmation?" """
    found = tools()
    every = [t for t in found if t.permission == permissions.HIGH_RISK]
    when = [t for t in found if t.permission == permissions.CONFIRM]
    blocked = [t for t in found if t.permission == permissions.BLOCKED]
    said = (f"Every time ({len(every)}): {_names(every)}. "
            f"When it matters — a submit, a send, a click from a screenshot ({len(when)}): {_names(when)}.")
    if blocked:
        said += f" Blocked, never run: {_names(blocked)}."
    return said
