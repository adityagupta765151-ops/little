# Security

LITTLE runs on your computer, with your files, your browser logins and your
WhatsApp. This page says what it may do, what stops it doing more, what it
keeps, and what the last audit found.

## What it's allowed to touch

- **Files: one folder.** Every path goes through `workspace.safe_path` and
  must resolve inside `JARVIS_WORKSPACE`. Anything outside, including
  through `..` or a link, is refused. Overwriting keeps a `.bak` first.
- **The network:** Google's model API (your key), Google's speech service,
  Microsoft's neural voice, the public job-board APIs, and pages you ask it
  to open. The job dashboard listens on `127.0.0.1:3000` only.
- **Your screen:** only when you ask ("what's on my screen"), never in the
  background.

## Every tool has a level

| Level | Means | Examples |
| --- | --- | --- |
| SAFE | Reads; changes nothing | `read_file`, `list_dir`, `recall`, `top_matches` |
| LOW_RISK | Changes only LITTLE's records or the workspace, or opens something | `write_file`, `open_app`, `remember`, `set_reminder` |
| CONFIRM | Asks you when it matters: a submit, a send, a click from a screenshot | `browser_task`, `click_text`, `click_on_screen`, `code_change` |
| HIGH_RISK | Asks you every time | `delete_path`, `run_command`, `send_whatsapp_message`, `wa_send_web` |
| BLOCKED | Never runs | anything in `JARVIS_BLOCKED_TOOLS` |

A tool without a level fails the tests; an unknown tool is treated as
HIGH_RISK. Outside tools (MCP servers) are CONFIRM unless `mcp_servers.json`
sets a level for a server or a tool, and any whose name mentions paying, passwords, OTP,
CAPTCHA, bypassing or auto-applying is blocked outright.

"Which tools require confirmation" and the Tools section list them live.

## The confirmation gate

- Only a real `True` is a yes. `"yes"`, `1`, a dialog's object or a
  timeout's `None` are all no.
- The window's dialog defaults to No, and no answer in five minutes is a no.
- Text on screen can't answer it: a replayed injection that once did is in
  the tests.
- Every answer is recorded (which tool, what for, yes or no) and shown in
  the audit log. What was asked about — a message, a command — is not kept.
- LITTLE never types passwords, one-time codes or card numbers, never
  solves a CAPTCHA, never submits a job application, and never records an
  application as submitted without proof from the page.

## What's kept, and what never is

| Kept | Where |
| --- | --- |
| Memory: facts you asked it to remember, preferences, contacts, conversation log | `memory/*.json` |
| Your resume, read into a profile | `memory/resume_profile.json` |
| Jobs, applications and their history | `memory/jobs.db` |
| Documents you added | `memory/knowledge.db` |
| Every task and tool run | `memory/audit.jsonl` |
| Benchmark runs | `memory/benchmarks.jsonl` |
| Errors and events | `jarvis.log` |

Never kept, anywhere: API keys, passwords, tokens, one-time codes, card or
ID numbers (refused by memory, redacted from the log and the audit), the
words of a message you sent, what you asked to be remembered (the audit
records that a value was stored, not the value), and — in the log and the
audit — the contents of your resume. `memory/`, `browser_profile/`, `.env` and `jarvis.log` are in
`.gitignore`.

## Secrets

Keys live only in `.env`, which is never committed. `.env.example` holds
placeholders. The Chapter 48 audit scanned every tracked file and the whole
git history for Google, GitHub and OpenAI key patterns and private keys:
none. A test repeats that scan on every run.

## Chapter 48 audit — what was found and fixed

Static analysis (bandit), a dependency audit (pip-audit), lint (ruff), type
checking (mypy) and a read of every place a value reaches a command line.

**Fixed:**

1. **`open_app` could run a second command on Windows.** Apps start through
   `start "" "<name>"` with the shell, and the model can call `open_app`
   without asking — so a web page that talked the model into opening
   `x" & <command> & "` would have run that command. Names with quotes,
   `&`, `|`, `<`, `>`, `^` or `%` are now refused; real names open exactly
   as before.
2. **`close_app` accepted a wildcard.** `taskkill /im *.exe /f` would have
   closed every program, with unsaved work. Names must now start with a
   letter or digit and hold only letters, digits, spaces, `.`, `+` and `-`;
   on Linux a dot is matched as a dot.
3. **A saved WhatsApp number reached the command line.** Links went through
   `start` with the shell, and the number comes from your contacts, which
   the model can add to. Links now go straight to Windows' own handler
   (`os.startfile`) with no command line between, and one with quotes or
   line breaks opens nothing — so a draft can't be followed by a send.
4. **`open_in_vscode` on Windows** runs `code.cmd` through the command line;
   a path with `&` or `%` in it is now refused with a sentence instead.
5. **The job dashboard could be read through DNS rebinding.** A website
   pointing its own name at `127.0.0.1` could have fetched `/api/state`
   (your name, skills and applications). It now answers only requests
   addressed to `localhost` or `127.0.0.1`.
6. **Dependencies with known vulnerabilities.** pillow 12.2 (image parsers,
   out-of-bounds writes), urllib3 2.6 (cross-origin redirects, decompression)
   and idna 3.13. The minimums are now `pillow>=12.3.0`, `urllib3>=2.7.0`
   and `idna>=3.15`; run `pip install -r requirements.txt --upgrade`.

**Reviewed and left as they are:**

- `run_command` uses the shell on purpose; it's HIGH_RISK and asks every
  time, showing the exact command.
- bandit's SQL finding in `jobs/store.py` builds only `?` placeholders; the
  values are bound.
- The job deduplication key uses SHA-1 as a fingerprint, not for security;
  it's now marked `usedforsecurity=False`.
- mypy's 83 findings are annotation gaps (optional values the code already
  checks, untyped dictionaries), not runtime faults. One latent name clash
  in `tools/catalog.py` was renamed.

A test (`tests/test_production_audit.py`) holds each fix, and fails if a new
shell call, `eval`, `exec` or `pickle` appears anywhere in the package until
it's reviewed.

## Reporting a problem

Open an issue on the repository without the details, and ask for a way to
send them privately. Please don't include your `.env`, `memory/` folder or
`jarvis.log` — they hold your key and your data.
