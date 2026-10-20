# Changelog

Newest first. Each chapter was one commit, with the full suite green
before it; `JARVIS_PHASE2_PLAN.md` has the detail of each, file by file.

## Phase 2 — Chapters 27 to 48

### After Chapter 48 — installing on Windows
- `pip install -r requirements.txt --upgrade` failed on Python 3.12: it
  reached for pocketsphinx 5.1.1, which has no ready-made Windows build for
  3.12, and a failed compile stopped every other package installing too.
  pocketsphinx (optional) moved to `requirements-optional.txt`, and both files
  now tell pip to prefer ready-made builds (`--prefer-binary`).

### Chapter 48 — Final production audit
- Security fixes: `open_app` refuses command-line characters (a model-chosen
  name could run a second command on Windows); `close_app` refuses
  wildcards (`*` would have closed every program); WhatsApp links bypass
  the command line entirely; `open_in_vscode` refuses paths the command line
  would split; the job dashboard answers only `localhost` (DNS rebinding).
- Dependencies: `pillow>=12.3.0`, `urllib3>=2.7.0`, `idna>=3.15`, past known
  vulnerabilities. Run `pip install -r requirements.txt --upgrade`.
- Every setting the code reads is now in `.env.example`.
- Lint: unused imports and empty f-strings removed; one latent name clash
  renamed. Type checking reviewed (annotation gaps only).
- New: `ARCHITECTURE.md`, `SECURITY.md`, `INSTALLATION.md`, `API.md`, this
  changelog; `tests/test_production_audit.py` holds each fix.

### Chapter 47 — Demo mode
- "Start the demo": 53 seconds of real commands, the same every time. Reads
  nothing personal, needs no internet or key, changes nothing; the risky
  step goes through the real gate and is refused. `DEMO_SCRIPT.md`.

### Chapter 46 — Performance benchmarking
- Every stage timed in use: hearing the name, speech to text, router, each
  model tier, each tool run, each browser step, each command by path.
- "Benchmark yourself" times what can be timed here, keeps each run in
  `benchmarks.jsonl` and compares with the last. The dashboard shows the
  typical browser step and speech-to-text time.
- Fixed: a page that timed out could finish loading over the next one.

### Chapter 45 — Test expansion
- 638 property and hostile-input tests; a guard so the test count only
  goes up (`tests/TEST_BASELINE`).
- Fixed: "so little time" and "little by little" woke it; "page padho"
  didn't read the page.

### Chapter 44 — Coding agent
- "In the code, …": inspect → explain the plan as exact replacements → one
  question showing them → the smallest change → tests before and after →
  report. "Undo the last code change".

### Chapter 43 — AI model router
- A fast tier (`JARVIS_MODEL_FAST`) for checking plan steps and summarising
  pages; the strong tier for the rest; each with fallbacks and timed.
  "Which model do you use for what".
- Fixed afterwards: "status report" is the system health check again.

### Chapter 42 — Failure recovery
- No internet: a short hold and what still works, instead of retries. A
  browser closed under a step reopened and the step retried once, said.
  Read-only tools retried once after a passing failure; nothing else ever.

### Chapter 41 — Observability and audit log
- `audit.jsonl`: every task and tool run, with your answers, redacted.
  "What did you do for my last task", "show the audit log".

### Chapter 40 — Dashboard 2.0
- Eleven sections at a glance, read fresh from real data: system, AI,
  voice, memory, tools, tasks, browser, jobs, applications, security, logs.

### Chapter 39 — MCP / external tools
- Outside tools over MCP, held to the same levels, confirmation,
  validation and logging; dangerous names blocked.

### Chapter 38 — Tool registry 2.0
- Every tool described in full: level, timeout, what it uses, logging
  policy. Read-only tools stopped waiting for after their timeout.

### Chapter 37 — Security center
- Five levels for every tool; blocked tools never run; only a real `True`
  is a yes; three bypasses in the old browser tools closed.

### Chapter 36 — Proactive LITTLE
- Suggestions from local data only — good new matches, unanswered
  applications, a stopped plan, a full disk — rarely, and never acting.

### Chapter 35 — Voice conversation mode
- Follow-ups without the name; "close it" knows what was opened; "never
  mind"; "continue" resumes a stopped plan.

### Chapter 34 — Local wake word
- With pocketsphinx, each phrase is checked offline for the name first; one
  without it never leaves the computer.

### Chapter 33 — Local-first routing
- Four paths, cheapest first (fast, normal, ai, agent); each command timed
  under its path; "how fast are you".

### Chapter 32 — Planner 2.0
- Goal → plan with checks → run through the gated tools → verify from the
  tools' output, never the model's word → one recovery try → result.

### Chapter 31 — RAG (personal knowledge base)
- Documents you add, parsed, chunked, indexed locally and cited; facts
  checked against the parts they cite; nothing retrieved, no model call.

### Chapter 30 — True memory
- Five tiers; remember, recall, update, forget by name; secrets refused.

### Chapter 29 — Computer vision
- Screen capture on request; "find on screen"; clicking from a picture
  only when sure, not risky and you say yes.

### Chapter 28 — Smart browser agent
- Observe, act from a fixed step set, verify after every step; submits
  ask, secrets are never typed, job boards are never submitted.

### Chapter 27 — Job tracker
- Ten application statuses with enforced moves; SUBMITTED only with proof;
  a history per job; old statuses migrated once, with a backup.

## Before Phase 2

Chapter 26 (resume intelligence: CGPA, marks, achievements, links, profile
corrections by command), the window redesign (UI-1 to UI-10: the design
system, the orb's states, the shell and command palette, Home, Chat, the
Task Center, Jobs, Resume, System, responsive and accessibility work), the
job hunter, the health check, the package split and the rename from JARVIS
to LITTLE.
