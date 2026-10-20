"""What the model is allowed to do, and how it is described to it.

Every tool module stays unaware of the model: it just exposes functions.
This file is the only place that knows about schemas, and the only place
that has to change when a tool is added.
"""
from __future__ import annotations

import threading
import time

from ..app import audit, health, latency, recovery, stats, tasks
from ..app.config import log
from ..jobs import apply as job_apply
from ..jobs import dashboard as job_dashboard
from ..jobs import engine as job_engine
from ..jobs import resume as job_resume
from ..jobs import resume_check as job_resume_check
from ..store import knowledge, memory
from ..voice import speaking
from . import (apps, browser, browser_agent, contacts, files, project_check, reminders, screen, system, whatsapp,
               whatsapp_web)
from . import permissions
from .permissions import NEEDS_CONFIRMATION  # noqa: F401  re-exported for older callers


def _code_change(request: str, path: str = ".") -> str:
    from ..ai import coder                  # the coding agent (Chapter 44)
    return coder.code_change(request, path)


def _undo_code_change() -> str:
    from ..ai import coder
    return coder.undo_last()


FUNCTIONS = {
    # files
    "list_dir": files.list_dir,
    "read_file": files.read_file,
    "write_file": files.write_file,
    "edit_file": files.edit_file,
    "create_folder": files.create_folder,
    "move_path": files.move_path,
    "copy_path": files.copy_path,
    "delete_path": files.delete_path,
    "search_files": files.search_files,
    # system
    "run_command": system.run_command,
    "open_in_vscode": system.open_in_vscode,
    "open_url": system.open_url,
    "search_web": system.search_web,
    "get_datetime": system.get_datetime,
    "get_system_info": system.get_system_info,
    # applications
    "open_app": apps.open_app,
    "close_app": apps.close_app,
    # browser
    "open_page": browser.open_page,
    "read_page": browser.read_page,
    "summarize_page": browser.summarize_page,
    "search_web_and_read": browser.search_web_and_read,
    "find_on_page": browser.find_on_page,
    "look_at_page": browser_agent.look_at_page,
    "browser_task": browser_agent.run_task,
    "click_text": browser.click_text,
    "fill_field": browser.fill_field,
    "press_key": browser.press_key,
    "browser_screenshot": browser.browser_screenshot,
    "close_browser": browser.close_browser,
    # whatsapp, desktop app and browser
    "open_whatsapp": whatsapp.open_whatsapp,
    "open_contact": whatsapp.open_contact,
    "draft_whatsapp_message": whatsapp.draft_whatsapp_message,
    "send_whatsapp_message": whatsapp.send_whatsapp_message,
    "add_contact": whatsapp.add_contact,
    "wa_open": whatsapp_web.wa_open,
    "wa_contacts": whatsapp_web.wa_contacts,
    "wa_open_chat": whatsapp_web.wa_open_chat,
    "wa_draft_web": whatsapp_web.wa_draft_web,
    "wa_send_web": whatsapp_web.wa_send_web,
    "wa_read_chat": whatsapp_web.wa_read_chat,
    # contacts
    "import_contacts": contacts.import_contacts,
    "find_contacts": contacts.find_contacts,
    "count_contacts": contacts.count_contacts,
    # reminders
    "set_reminder": reminders.set_reminder,
    "list_reminders": reminders.list_reminders,
    "cancel_reminders": reminders.cancel_reminders,
    # memory
    "remember": memory.remember,
    "forget": memory.forget_anything,
    "recall": memory.recall,
    "recall_memory": memory.recall_about,
    "remember_preference": memory.set_preference,
    "remember_for_project": memory.remember_for_project,
    "recall_project": memory.recall_project,
    "forget_for_project": memory.forget_for_project,
    "note_for_task": memory.note_for_task,
    # projects
    "check_github_ready": project_check.check_github_ready,
    "code_change": _code_change,
    "undo_code_change": _undo_code_change,
    # your knowledge base
    "add_document": knowledge.add_document,
    "list_documents": knowledge.list_documents,
    "remove_document": knowledge.remove_document,
    "search_documents": knowledge.search_documents,
    "ask_documents": knowledge.ask_documents,
    # screen
    "take_screenshot": screen.take_screenshot,
    "describe_screen": screen.describe_screen,
    "find_on_screen": screen.find_on_screen,
    "click_on_screen": screen.click_on_screen,
    # voice
    "voice_report": speaking.voice_report,
    # self-diagnostics
    "system_check": health.system_check,
    "check_component": health.check_component,
    # job hunting
    "scan_resume": job_resume.scan_resume,
    "show_resume_profile": job_resume.show_profile,
    "set_job_preference": job_resume.set_preference,
    "update_resume_profile": job_resume.edit_profile,
    "check_resume": job_resume_check.check_resume,
    "find_jobs": job_engine.find_jobs,
    "top_matches": job_engine.top_matches,
    "why_this_job": job_engine.why_this_job,
    "missing_skills": job_engine.missing_skills,
    "shortlist_job": job_engine.shortlist,
    "open_job_board": job_engine.open_board,
    "application_status": job_engine.application_status,
    "effectiveness": job_engine.effectiveness,
    "prepare_application": job_apply.prepare_application,
    "mark_applied": job_apply.mark_applied,
    "mark_job_status": job_apply.mark_status,
    "verify_submission": job_apply.verify_submission,
    "mark_submitted": job_apply.mark_submitted,
    "job_history": job_engine.job_history,
    "open_job_dashboard": job_dashboard.open_dashboard,
}


def execute_tool(name: str, args: dict) -> str:
    """Run a tool and always come back with a sentence, never an exception.

    The model reads the result, so an error has to be describable rather
    than fatal.

    Each run is also a step of the task in progress, so the window can show
    it as it happens. A step is marked as an error only when the tool
    raised or doesn't exist; what a tool says in its own words is its own.
    """
    from . import catalog
    step = tasks.step_started(name, tasks.preview(args, catalog.log_policy(name)) if isinstance(args, dict) else "")
    fn = FUNCTIONS.get(name)
    refused = ("no such tool" if not fn else "blocked" if permissions.level(name) == permissions.BLOCKED
               else "wrong arguments" if not isinstance(args, dict) else "")
    if refused:
        tasks.step_finished(step, error=refused)
        # Chapter 37: blocked means never, whatever the model or a page says.
        permissions.note_event("blocked" if refused == "blocked" else "failed", name,
                               {"no such tool": "no such tool", "blocked": "blocked in JARVIS_BLOCKED_TOOLS",
                                "wrong arguments": "arguments weren't a set of named values"}[refused])
        audit.tool_run(name, args, None, 0, error=refused, task_id=tasks.current_id())
        return {"no such tool": f"Unknown tool: {name}",
                "blocked": f"I won't run {name}: it's blocked in your settings (JARVIS_BLOCKED_TOOLS).",
                "wrong arguments": f"Wrong arguments for {name}: expected named values."}[refused]
    error, result = "", None
    stats.tool_started(name)
    limit, started = catalog.timeout_for(name), time.monotonic()
    answered = permissions.last_answer()
    try:
        if permissions.level(name) == permissions.SAFE:
            try:
                result = _within(fn, args, limit, name)
            except ToolTimeout:
                raise
            except Exception as first:  # noqa: BLE001
                # Chapter 42: a tool that only reads gets one more try after a
                # passing failure. Anything that changes things never does.
                if not recovery.transient(first):
                    raise
                result = _within(fn, args, limit, name)
                recovery.note(name, f"worked on a second try, after {type(first).__name__}", True)
        else:
            result = fn(**args)
        return result
    except ToolTimeout:
        error = f"took over {limit} s"
        result = (f"{name} took longer than {limit} seconds, so I stopped waiting. It only reads, so nothing "
                  f"was changed.")
        return result
    except TypeError as e:
        error = f"wrong arguments: {e}"
        result = f"Wrong arguments for {name}: {e}"
        return result
    except Exception as e:  # noqa: BLE001
        log(f"{name} failed: {e}")
        error = f"{type(e).__name__}: {e}"
        result = f"Error in {name}: {type(e).__name__}: {e}"
        return result
    finally:
        stats.tool_finished(name)
        latency.record("tool", (time.monotonic() - started) * 1000)
        tasks.step_finished(step, error=error)
        # Chapter 41: what ran, as it may be kept — arguments by policy,
        # results summarised or only measured, your answers, any error.
        audit.tool_run(name, args, result, (time.monotonic() - started) * 1000, error=error,
                       answers=permissions.answers(since=answered, this_thread=True), task_id=tasks.current_id())
        if error:
            permissions.note_event("failed", name, error)
        elif time.monotonic() - started > limit:
            # Something that changes things isn't abandoned halfway; it's
            # recorded as slow instead.
            permissions.note_event("slow", name, f"{time.monotonic() - started:.0f} s, over its {limit} s")


class ToolTimeout(Exception):
    pass


def _within(fn, args: dict, seconds: float, name: str):
    """Run a read-only tool, waiting at most `seconds`. It runs on a helper
    thread that still reports to the same task; if it's still going when
    time's up, it's left to finish on its own — it can't change anything."""
    box: dict = {}
    parent = tasks.current_id()

    def work():
        tasks.bind(parent)
        try:
            box["out"] = fn(**args)
        except BaseException as e:  # noqa: BLE001
            box["err"] = e
        finally:
            tasks.bind(None)

    helper = threading.Thread(target=work, daemon=True, name=f"tool-{name}")
    helper.start()
    helper.join(seconds)
    if helper.is_alive():
        raise ToolTimeout(name)
    if "err" in box:
        raise box["err"]
    return box["out"]


def _schema(name, description, props=None, required=None):
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props or {},
                             "required": required or []}}


S, I = {"type": "string"}, {"type": "integer"}

TOOL_SCHEMAS = [
    _schema("list_dir", "Show the folder tree inside the workspace.", {"path": S, "depth": I}),
    _schema("read_file", "Read a text file, PDF or Word document.",
            {"path": S, "start_line": I, "end_line": I}, ["path"]),
    _schema("write_file", "Create or overwrite a file. Existing files are backed up first.",
            {"path": S, "content": S}, ["path", "content"]),
    _schema("edit_file", "Replace one exact, unique block of text in a file.",
            {"path": S, "old_text": S, "new_text": S}, ["path", "old_text", "new_text"]),
    _schema("create_folder", "Create a folder.", {"path": S}, ["path"]),
    _schema("move_path", "Move or rename a file or folder.",
            {"source": S, "destination": S}, ["source", "destination"]),
    _schema("copy_path", "Copy a file or folder.",
            {"source": S, "destination": S}, ["source", "destination"]),
    _schema("delete_path", "Delete a file or folder. The user confirms first.",
            {"path": S}, ["path"]),
    _schema("search_files", "Find files by glob like '*.py', optionally by text inside them.",
            {"name_pattern": S, "contains": S, "path": S}),
    _schema("run_command", "Run a shell command. The user confirms first.",
            {"command": S, "cwd": S}, ["command"]),
    _schema("open_in_vscode", "Open a file or folder in VS Code, optionally at a line.",
            {"path": S, "line": I}),
    _schema("open_url", "Just open a website in the user's normal browser. You cannot read "
                        "the page afterwards, so prefer read_page when the content matters.",
            {"url": S}, ["url"]),
    _schema("search_web", "Open a Google search in the user's normal browser, results unread.",
            {"query": S}, ["query"]),
    _schema("get_datetime", "Current local date and time."),
    _schema("get_system_info", "OS, Python version and workspace path."),
    _schema("open_app", "Open a desktop app by name: chrome, vs code, whatsapp, spotify, "
                        "calculator.", {"name": S}, ["name"]),
    _schema("close_app", "Close a running desktop app by name.", {"name": S}, ["name"]),
    _schema("open_page", "Open a page in your own automation browser, which you can then read and click.",
            {"url": S}, ["url"]),
    _schema("read_page", "Read the visible text of a web page. Pass a url, or omit it to read "
                         "the page already open.", {"url": S}),
    _schema("summarize_page", "Read a page and summarise it, or answer a question about it.",
            {"url": S, "question": S}),
    _schema("search_web_and_read", "Search the web and return the top results with their links, "
                                   "so you can actually use them.",
            {"query": S, "count": I}, ["query"]),
    _schema("find_on_page", "Ask something about the open page: a price, a date, a heading.",
            {"what": S}, ["what"]),
    _schema("look_at_page", "What the page open in the automation browser is: its address, title, "
                            "headings, form fields, buttons, links, error messages and text. "
                            "Reads only; never opens a browser that isn't open."),
    _schema("browser_task", "Reach a goal in the automation browser step by step: observe the page, "
                            "take one step (open, click, fill, select, press, back), verify it on the "
                            "page, repeat. Asks before anything that could submit, send, buy or delete; "
                            "never types passwords, codes or card numbers; stops at a step it can't "
                            "verify. Use for multi-step web tasks, not for reading one page.",
            {"goal": S}, ["goal"]),
    _schema("click_text", "Click a link or button by the words on it. The user confirms if it "
                          "looks like it buys, sends, submits or deletes something.",
            {"text": S}, ["text"]),
    _schema("fill_field", "Type into a form field, found by its label or placeholder.",
            {"label": S, "value": S}, ["label", "value"]),
    _schema("press_key", "Press a key on the page, usually Enter to submit a search box.",
            {"key": S}),
    _schema("browser_screenshot", "Save a picture of the page your automation browser is showing."),
    _schema("close_browser", "Close your automation browser and free its memory."),
    _schema("open_whatsapp", "Open WhatsApp."),
    _schema("open_contact", "Open a WhatsApp chat with a saved contact.", {"name": S}, ["name"]),
    _schema("draft_whatsapp_message",
            "Open a chat with a message typed in but NOT sent. Use this for any new message.",
            {"name": S, "message": S}, ["name", "message"]),
    _schema("send_whatsapp_message",
            "Send the drafted WhatsApp message. The user confirms first.",
            {"name": S, "message": S}),
    _schema("add_contact", "Save a contact name and phone number with country code.",
            {"name": S, "number": S}, ["name", "number"]),
    _schema("wa_open", "Open WhatsApp Web in your automation browser. Needs a one-time QR scan."),
    _schema("wa_contacts", "List the people in the WhatsApp chat list. Use this when the user "
                           "asks who they can message.", {"limit": I}),
    _schema("wa_open_chat", "Open someone's WhatsApp chat by searching their name in WhatsApp "
                            "Web. Works for any name in the chat list, no saved number needed.",
            {"name": S}, ["name"]),
    _schema("wa_draft_web", "Type a WhatsApp message to someone in the browser without sending "
                            "it. Prefer this over draft_whatsapp_message when the person isn't "
                            "in saved contacts.", {"name": S, "message": S}, ["name", "message"]),
    _schema("wa_send_web", "Send the message typed in WhatsApp Web. The user confirms first.",
            {"name": S, "message": S}),
    _schema("wa_read_chat", "Read the last few messages in the open WhatsApp chat.", {"count": I}),
    _schema("import_contacts", "Import many contacts at once from a Google Contacts CSV "
                               "export or a .vcf vCard file.",
            {"path": S, "country_code": S}, ["path"]),
    _schema("find_contacts", "Search saved contacts by part of a name.", {"query": S}, ["query"]),
    _schema("count_contacts", "How many contacts are saved."),
    _schema("set_reminder", "Remind the user later. when can be '8 pm' or 'in 10 minutes'.",
            {"text": S, "when": S}, ["text", "when"]),
    _schema("list_reminders", "List pending reminders."),
    _schema("cancel_reminders", "Cancel all pending reminders."),
    _schema("remember", "Long-term memory: store a fact the user asks you to remember. Saying it again "
                        "with a new value updates it. Passwords, codes, PINs, card or ID numbers and keys "
                        "are refused.", {"key": S, "value": S}, ["key", "value"]),
    _schema("forget", "Forget the one thing stored under exactly this name (a fact, a preference or a "
                      "project's fact). Says so if the name is in more than one place.", {"key": S}, ["key"]),
    _schema("recall", "Recall what's stored: one thing by its name, or with no name everything (facts, "
                      "preferences, projects).", {"key": S}),
    _schema("recall_memory", "Look up what's stored about something, across facts, preferences, projects "
                             "and this task's notes. Use it when a request needs something the user may "
                             "have told you before.", {"query": S}, ["query"]),
    _schema("remember_preference", "Store how the user likes something done, e.g. key 'browser', value "
                                   "'Firefox'. Updates it if already set.", {"key": S, "value": S},
            ["key", "value"]),
    _schema("remember_for_project", "Store a fact about one named project, e.g. its deadline or stack.",
            {"project": S, "key": S, "value": S}, ["project", "key", "value"]),
    _schema("recall_project", "Everything stored for one named project.", {"project": S}, ["project"]),
    _schema("forget_for_project", "Forget one fact stored for a project, by its exact name.",
            {"project": S, "key": S}, ["project", "key"]),
    _schema("note_for_task", "Task memory: note something to use later in the task you're doing now "
                             "(gone when the task is over). Read it back with recall_memory.",
            {"key": S, "value": S}, ["key", "value"]),
    _schema("code_change", "Make a small, tested change to a code project in the workspace: it reads the relevant "
                           "files, plans exact small replacements, asks the user once (showing the changes), runs "
                           "the tests before and after, and reports. Use it for fixing or changing code.",
            {"request": S, "path": S}, ["request"]),
    _schema("undo_code_change", "Undo the last change code_change made, after asking."),
    _schema("check_github_ready", "Check a project folder in the workspace before it goes on GitHub: README, "
                                  ".gitignore, secret files and keys kept out, bulky folders, files over 50 MB, "
                                  "git set up. Reads only.", {"path": S}),
    _schema("add_document", "Add a file, or every readable file in a folder, from the workspace to the "
                            "user's knowledge base (text, Markdown, code, CSV, JSON, HTML, PDF, Word). "
                            "Read on this computer; the file isn't changed.", {"path": S}, ["path"]),
    _schema("list_documents", "List the documents in the user's knowledge base."),
    _schema("remove_document", "Take a document out of the knowledge base by its file name. The file "
                               "itself is untouched.", {"name": S}, ["name"]),
    _schema("search_documents", "Find the passages in the user's own documents that match, with their "
                                "sources. Uses no model.", {"query": S}, ["query"]),
    _schema("ask_documents", "Answer a question from the user's own documents. Facts found there are "
                             "marked RETRIEVED FACT with their source; anything the model adds is marked "
                             "GENERATED SUGGESTION. Says so when nothing in them answers it.",
            {"question": S}, ["question"]),
    _schema("take_screenshot", "Save a screenshot of the screen."),
    _schema("find_on_screen", "Say where something is on the screen and how sure the model is. "
                              "Looks only; clicks nothing.", {"what": S}, ["what"]),
    _schema("click_on_screen", "Click something on the screen. In the automation browser it's found "
                               "by its words; otherwise from a screenshot, only when the model is sure, "
                               "never for anything that could pay, send, submit or delete, and only "
                               "after the user says yes.", {"what": S}, ["what"]),
    _schema("describe_screen", "Capture the screen and describe or explain what's on it.",
            {"question": S}),
    _schema("voice_report", "Which voice you are speaking with, its speed, pitch and "
                            "volume, and which other voices are available."),
    _schema("system_check", "Check every part of the assistant — packages, .env, microphone, "
                            "voice, browser, database, memory, disk, network, tools, "
                            "router, dashboard, job sources — and report what is broken, "
                            "why, and how to fix it. Set live to true to also make one "
                            "real call to the AI model, which uses a request.",
            {"live": {"type": "boolean"}}),
    _schema("check_component", "Check one part only: runtime, project, config, workspace, "
                               "packages, tts, mic, browser, database, memory, disk, "
                               "network, tools, router, dashboard, jobs, or ai.",
            {"name": S}, ["name"]),
    _schema("scan_resume", "Read a resume (PDF, Word, image or text) and build the "
                           "candidate profile everything else matches against.",
            {"path": S}, ["path"]),
    _schema("show_resume_profile", "Show what you know about the candidate."),
    _schema("set_job_preference", "Set roles, locations, countries, work_modes or "
                                  "employment_types (internship, full-time, contract...) "
                                  "for job search. Value is a comma separated list.",
            {"field": S, "value": S}, ["field", "value"]),
    _schema("update_resume_profile",
            "Correct the candidate profile when the user says a detail is wrong or missing. "
            "change is set, add, remove or clear. Single values (set): name, email, phone, "
            "address, degree, graduation_year, degree_score (CGPA or %, as the user says it), "
            "class_12, class_10, github, linkedin. Lists (add/remove): skills, languages, "
            "frameworks, projects, experience, internships, certifications, education, "
            "achievements, links. Use only what the user said; never guess a value.",
            {"field": S, "value": S, "change": S}, ["field"]),
    _schema("check_resume", "Check the resume on this computer: contact details, GitHub and "
                            "LinkedIn, CGPA, degree and batch, projects, skills shown in work, "
                            "length and achievements. Nothing is sent to the model."),
    _schema("find_jobs", "Search the job boards, score every result against the resume "
                         "and store them. Leave query empty to use the saved target role.",
            {"query": S, "location": S, "limit": I}),
    _schema("top_matches", "Show the best stored jobs with their scores, posting age, "
                           "employment type and skill gaps. max_age_days narrows it to "
                           "recent postings, e.g. 7 for this week.",
            {"count": I, "min_score": I, "max_age_days": I}),
    _schema("why_this_job", "Explain a job's score in full. Reference is a rank number "
                            "or part of the company name.", {"reference": S}, ["reference"]),
    _schema("missing_skills", "Which skills employers keep asking for that the resume "
                              "doesn't list.", {"limit": I}),
    _schema("shortlist_job", "Mark a stored job as one to go for.",
            {"reference": S}, ["reference"]),
    _schema("open_job_board", "Open LinkedIn, Naukri, Indeed, Internshala or Wellfound "
                              "in the browser to search by hand. You cannot automate "
                              "these; their terms forbid it.",
            {"board": S, "query": S, "location": S}, ["board"]),
    _schema("application_status", "List the applications recorded so far."),
    _schema("effectiveness", "Success rate, interview rate and match averages."),
    _schema("prepare_application", "Open a job posting and fill the fields the resume can "
                                   "answer. Never submits: the user presses submit.",
            {"reference": S}, ["reference"]),
    _schema("mark_applied", "Record that the user submitted an application themselves.",
            {"reference": S, "notes": S}, ["reference"]),
    _schema("mark_job_status", "Set a job's status: saved, found (unsave), interview, offer, "
                               "rejected, withdrawn. Only moves forward; an ended job stays ended. "
                               "Never 'submitted' — that needs proof (verify_submission, mark_submitted).",
            {"reference": S, "status": S}, ["reference", "status"]),
    _schema("verify_submission", "Check the page open in the automation browser for a confirmation "
                                 "that the application to this job went in. Marks it submitted "
                                 "only with that proof; reads the page, clicks nothing.",
            {"reference": S}, ["reference"]),
    _schema("mark_submitted", "Record that an application was submitted, with the confirmation "
                              "or reference number the user was given. Only with a number the "
                              "user actually said.",
            {"reference": S, "confirmation": S}, ["reference", "confirmation"]),
    _schema("job_history", "A job's timeline: when it was found and every status change and "
                           "event since, with where each came from.",
            {"reference": S}, ["reference"]),
    _schema("open_job_dashboard", "Start and open the job dashboard at localhost:3000/jobs."),
]
