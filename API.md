# LITTLE's interfaces

LITTLE has no public network API. It has four interfaces, all on this
computer: the bridge the window calls, the job dashboard's one JSON
endpoint, the tool registry the model calls, and outside tools over MCP.
The files it writes are listed at the end.

## 1. The bridge — what the window may ask Python to do

`jarvis/app/bridge.py`, class `Api`. pywebview exposes each public method to
the page as `window.pywebview.api.<name>(…)`, returning a promise; the page
reaches them only through `ui/js/core/bridge.js`. Nothing else in the page
talks to Python. Every method answers with plain JSON (strings, numbers,
lists, dicts) and never raises into the page: a failure comes back as a
sentence.

### Commands and control

| Call | Does |
| --- | --- |
| `send(text)` | Hands a typed command to the assistant, on its own thread. Returns nothing; the answer arrives through `poll`. |
| `poll(since=None)` | What changed: status, new activity lines, live readings (twice a second at most), tasks changed since version `since`, and a confirmation waiting for you, if any. |
| `control(action)` | `"stop"` stops speech and whatever is running, at its next step; `"mute"` toggles the voice and returns the next label; `"browser"` closes LITTLE's browser. |
| `toggle()` | Starts or stops listening. |
| `confirm(message)` | Called from a worker thread, not the page: shows the question and waits. No answer in five minutes is a no. |
| `confirm_reply(ask_id, ok)` | The page's answer. Only a question actually waiting can be answered, and only a real `true` approves. |

### Tasks and Chat

| Call | Does |
| --- | --- |
| `cancel(task_id)` | The Task Center's "Stop this". `""` when stopping, or why it can't. |
| `speak(task_id)` | Reads a reply out again, briefly. |
| `save(task_id)` | Keeps a turn in `Saved from Little.md` in your workspace; says where. |
| `regenerate(task_id)` | Asks the model the same question again — only its latest plain answer that ran no tools, so nothing is done twice. |

### Sections

| Call | Returns |
| --- | --- |
| `jobs()` | The Jobs section: job cards read fresh from the job store. |
| `job(job_id, action)` | Runs a job card's button on exactly that job. |
| `open_posting(job_id)` | Opens a job's posting in your normal browser (web addresses only). |
| `resume()` | The Resume section, read fresh. |
| `resume_action(action, job_id=None)` | One of the Resume section's questions, run as a task. |
| `choose_resume()` | The system file dialog; returns the file's name and a token for `scan_picked`. |
| `scan_picked(token)` | Scans the file just picked, as a task. |
| `save_preferences(values)` | The job preferences form, checked and saved all together or not at all. |
| `projects()` | Your projects, from the resume profile. Only reads. |
| `open_project_link(project, link)` | Opens a web address written in one of your project's lines. |
| `memory_view()` | What LITTLE keeps about you; contact numbers come masked. |
| `forget_fact(key, scope=None, project=None)` | Forgets one remembered thing by its exact key. |
| `remove_contact(name)` | Removes one contact by its exact saved name. |
| `clear_log()` | Empties the conversation log. |
| `tools()` | Every tool: what it does, its group, level, timeout, what it uses, its logging policy, and this session's runs. |
| `system()` | Every setting in effect, the microphones, what asks first, and "At a glance" (Dashboard 2.0's eleven sections). |
| `health(live=False)` | The health check, probe by probe: what's wrong, why, the fix. |
| `test_voice()` | Says a sentence in the voice as set. |

A test (`tests/test_production_audit.py`) fails if a public method is added
to `Api` without a line here.

## 2. The job dashboard — `http://localhost:3000/jobs`

`jarvis/jobs/dashboard.py`. Started by "open my dashboard"; bound to
`127.0.0.1` only.

| Request | Returns |
| --- | --- |
| `GET /jobs` | The page (`ui/jobs/index.html`) |
| `GET /api/state` | `{"assistant", "counts", "jobs", "applications", "audit", "missing_skills", "resume"}` — read fresh from the job store and resume profile |

Requests whose `Host` isn't `localhost` or `127.0.0.1` get 403 (so a
website can't read it through DNS rebinding). Responses carry a strict
Content-Security-Policy: only the page's own scripts run, nothing inline,
no framing.

## 3. The tool registry — what the model may call

`jarvis/tools/registry.py` builds the list the model sees (`TOOL_SCHEMAS`:
name, description, parameters) and the functions behind it (`FUNCTIONS`).
Every call goes through `registry.execute_tool(name, args)`, which:

1. refuses an unknown tool, a blocked one, or arguments that aren't named;
2. records the step on the current task;
3. runs a SAFE tool on a helper thread with its timeout, retrying once
   after a passing failure; runs anything else to completion;
4. times it, writes the audit entry (arguments by the tool's logging
   policy, your answers), and notes a slow or failed run.

Confirmation isn't the registry's job: each tool that can do harm asks
itself, through `permissions.confirm`, so a tool reached another way still
asks. `tools/catalog.py` describes every tool in full; ask "what tools do
you have", "which tools use the browser" or "which tools require
confirmation", or open the Tools section. 90 built-in tools today.

## 4. Outside tools — MCP servers

`jarvis/tools/external.py`. List servers in `memory/mcp_servers.json` (or
the file named by `JARVIS_MCP_CONFIG`):

    {"servers": {"notes": {"command": "python", "args": ["notes_server.py"],
                           "level": "CONFIRM", "timeout": 30,
                           "tools": {"search_notes": {"level": "SAFE", "log": "args"}}}}}

Each server is started over stdio; its tools join the registry as
`mcp__<server>__<tool>`, CONFIRM unless you lower them, validated against
their own schema, results handed to the model marked as outside data.
Tools named for paying, passwords, OTP, CAPTCHA, bypassing or auto-applying
are blocked whatever the file says. They start with the window and stop
when it closes; "reload the outside tools" restarts them after an edit,
and "which outside tools do you have" lists them.

## Files LITTLE writes

All in `memory/` (or `JARVIS_MEMORY_DIR`), except the log.

| File | Format |
| --- | --- |
| `audit.jsonl` | One JSON object per line. A task: `kind: "task"`, `at`, `session`, `task`, `intent`, `route`, `path`, `status`, `ms`, `ok`, `error`. A tool run: `kind: "tool"`, `at`, `session`, `task`, `tool`, `args` (by policy), `result` (summary or length), `ms`, `ok`, `confirmation` (`[{"action", "answer"}]`), `error`. |
| `benchmarks.jsonl` | One run per line: `at`, `now` and `in_use` (each `{stage: {count, p50, p95, max}}`, milliseconds), `problems`. |
| `jobs.db` | SQLite: jobs, applications and their history, the job audit trail. |
| `knowledge.db` | SQLite: the documents you added, in parts, with their word vectors. |
| `resume_profile.json` | Your resume, read into a profile, with the preferences you set. |
| `user_profile.json`, `preferences.json`, `contacts.json`, `conversation_history.json`, `project_memory.json` | Memory: what you asked it to remember, your preferences, contacts, the conversation log, per-project notes. |
| `proactive.json` | Which suggestions were made, and when. |
| `code_backups/` | The originals of files the coding agent changed, for "undo the last code change". |
| `jarvis.log` (beside the project, or `JARVIS_LOG_FILE`) | Errors and events, with keys and secrets redacted. |
