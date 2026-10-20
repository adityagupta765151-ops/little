# JARVIS Phase 2 — Production and Intelligence

Roadmap for chapters 23–48. One chapter at a time; nothing is marked complete
until its tests pass and the full suite still passes.

**Legend** ⬜ not started · 🟡 in progress · ✅ completed · ❌ failed

## Baseline at the start of Phase 2

| | |
| --- | --- |
| Python | 4,707 lines across 39 files |
| Packages | 8 (`app`, `voice`, `routing`, `ai`, `tools`, `store`, `jobs`, root) |
| Tools | 65 registered, 5 behind a confirmation gate |
| Router patterns | 40 |
| Tests | 123, all passing, no network or sound card needed |
| Job sources | adzuna, jobicy, themuse, remotive, remoteok, arbeitnow |

## Chapters

| # | Chapter | State | Note |
| --- | --- | --- | --- |
| 23 | Health check and self-diagnostics | ✅ | `app/health.py`, 17 probes + 1 live, 2 tools, 3 routes, 65 tests |
| 24 | Real job search engine | ✅ | `jobs/normalise.py`, dates + type + seniority + split location, migration, parallel search, 115 tests |
| 25 | Better job matching | ✅ | Nine weighted dimensions, transparent breakdown, concerns, never claims fit; 48 tests |
| 26 | Resume intelligence | ✅ | CGPA / Class 12 / Class 10 marks, achievements and links, each held to the resume's text; correcting the profile by command; academic bars as job concerns; a resume check on this computer; 123 tests |
| 27 | Application tracker | ✅ | The ten Phase 2 statuses with enforced moves; SUBMITTED only with proof; a history per job (card, timeline command, counts); old statuses renamed once, with a backup |
| 28 | Smart browser agent | ✅ | `browser_agent`: observe (fields, buttons, links, errors), a fixed step set, gates (submit asks, secrets never typed, job boards never submitted), verify after every step, an 8-step loop |
| 29 | Computer vision | ✅ | Capture on request; `find_on_screen` says where something is and how sure; `click_on_screen` tries LITTLE's browser by words first, and clicks from a picture only when sure, not risky and you say yes |
| 30 | True JARVIS memory | ✅ | Five tiers — short-term (the conversation), task (RAM, its own task only), project, long-term, preferences; remember / recall / update (says what it was) / forget by exact name; passwords, codes, PINs, card and ID numbers and keys refused and hidden from the log |
| 31 | Personal knowledge base (RAG) | ✅ | `store/knowledge.py`: parse (text, code, HTML, PDF with pages, Word) → chunk → local sparse vectors → sqlite → BM25 with a half-the-words gate → answer; facts checked against the parts they cite, labelled RETRIEVED FACT or GENERATED SUGGESTION; nothing retrieved means no model call |
| 32 | Agentic planner 2.0 | ✅ | Goal → understand → plan (steps with checks and files) → execute through the gated tools → observe the tools' output → verify (files on disk, the check judged from tool output, never the model's word) → one recovery try → result; a no ends the plan; GitHub readiness checklist re-run by LITTLE |
| 33 | Local-first intelligence | ✅ | Four paths — fast (what LITTLE holds), normal (its own tools), ai, agent — tried cheapest first; each task's path on its record; every task's time measured under its path, and the router's own cost; "how fast are you" reports p50/p95 |
| 34 | Local wake word | ✅ | With pocketsphinx, each phrase is checked offline for the name first; one without it never leaves the computer; one with it must still open with the name in the cloud transcript; sensitivity, room calibration, a report; without pocketsphinx or on an offline error it listens exactly as before |
| 35 | Voice conversation mode | ✅ | A follow-up window after each spoken answer (no name needed, 3 in a row at most, closes on silence); "close it" knows what was just opened; NEVER MIND drops it without the model; CONTINUE resumes a stopped plan at the step it stopped, asking again where it must |
| 36 | Proactive JARVIS | ✅ | `app/proactive.py`: new good matches, unanswered applications, unverified ones, a stopped plan, a full disk — from local data only; one at a time, an hour apart, four a day, each thing once; off entirely or by kind; spoken only when asked for, unmuted and outside quiet hours; never acts |
| 37 | Security centre | ✅ | Every tool has a level (SAFE, LOW_RISK, CONFIRM, HIGH_RISK, BLOCKED); blocked tools never run; only a real True is a yes; three bypasses in the old browser tools closed; answers and failed/blocked runs recorded; keys, services and levels in the System section and "security report" |
| 38 | Tool registry 2.0 | ✅ | `tools/catalog.py`: name, description, params, level, timeout, handler, group, what it uses, logging policy — built from the registry; read-only tools stopped waiting for after their timeout; messages and personal values never logged; "what tools do you have", "which use the browser", "which require confirmation" |
| 39 | MCP / external tools | ✅ | `tools/external.py`: an MCP stdio client for servers listed in mcp_servers.json; tools ask before every call by default, validated against their own schemas, logged by name, results marked as data and redacted; blocked by name for paying, passwords, OTP, CAPTCHA, bypass, auto-apply; failures reported and the server dropped |
| 40 | Dashboard 2.0 | ✅ | `app/overview.py`: system, AI, voice, memory, tools, tasks, browser, jobs, applications, security, logs — read fresh from real data, "not measured yet" where nothing is; "At a glance" at the top of the System section and "everything at a glance" in words |
| 41 | Observability and audit | ✅ | `app/audit.py`: every task and tool run in audit.jsonl — time, intent, tool, arguments by policy, result summary or length, duration, success, your answers, error; keys, passwords, tokens, messages, remembered values and resume contents never kept; the log file redacted too; "show me what you did for my last task" |
| 42 | Failure recovery | ✅ | A switch to a lighter model recorded; no internet → a short hold instead of the same retries, and what still works said; a browser closed under a step reopened and the step retried once, saying so; read-only tools retried once after a passing failure, nothing else ever; every missing optional package a sentence |
| 43 | AI model router | ✅ | `ai/models.py`: local (no model), fast (JARVIS_MODEL_FAST — checking a plan step, summarising a page) and strong (GEMINI_MODEL — tools, plans, code, documents, resume, screen); each tier keeps its fallback, the fast one ending at the strong model; each timed; "which model do you use for what" |
| 44 | Coding agent | ✅ | `ai/coder.py`: inspect (the files the request names or mentions, how tests run) → explain the plan as exact small replacements → one question showing the changes → minimal change checked first (all or nothing, originals kept) → tests before and after → report; "undo the last code change" |
| 45 | Test expansion | ✅ | `tests/test_expansion.py`: property and hostile-input tests across the router (English and Hinglish), every tool, fallback, the browser's error words, scoring, parsers, memory, planner, permissions, dashboard, wake word, config and recovery; three bugs found and fixed; a guard so the test count only goes up |
| 46 | Performance benchmarking | ✅ | Every stage timed in use (wake, speech to text, router, each model tier, tool, browser step, and each command start to reply by path); "benchmark yourself" times the router, a tool and document search here, keeps each run and compares it with the last; the model only when asked |
| 47 | Demo mode | ✅ | "Start the demo": 53 seconds of real commands, the same every time — nothing personal read, no internet or model needed, nothing changed; the one risky step goes through the real gate and is refused; timed by the clock; `DEMO_SCRIPT.md` |
| 48 | Final production audit | ✅ | Tests, lint (ruff), types (mypy), static security (bandit), dependencies (pip-audit), secrets, startup, configuration, permissions, logging, packaging; four command-line injection paths and a DNS-rebinding read closed; vulnerable dependency minimums raised; every setting documented; ARCHITECTURE, SECURITY, INSTALLATION, API and CHANGELOG written |

All 26 chapters (23 to 48) are complete, each with the full suite green.

## Chapter 23 — plan

A health check is worth building first because every later chapter depends on
something it would verify, and because the failures it catches are the ones
that waste the most time: a missing package, an unread `.env`, a mic on the
wrong device.

### What it checks

| Group | Probe | Fails when |
| --- | --- | --- |
| Runtime | Python version, project root, workspace writable | under 3.10; root resolves to the package; workspace not writable |
| Config | `.env` found and read, API key present, model name | file missing; key blank |
| AI | one tiny live call to the provider | no network, rejected key, model gone |
| Packages | each import in `requirements.txt` | not installed |
| Voice out | pyttsx3 present, edge-tts present, a voice installed | no engine at all |
| Voice in | SpeechRecognition, PyAudio, at least one input device | no device |
| Browser | Playwright installed, a browser it can drive | neither bundled Chromium nor installed Chrome/Edge |
| Database | `jobs.db` opens, schema applies | locked or corrupt |
| Memory | `memory/` writable, JSON files parse | unwritable; corrupt JSON |
| Disk | free space on the workspace drive | under 500 MB |
| Network | DNS resolves | offline |
| Registry | every tool has a schema and every schema a tool | drift |
| Router | patterns compile | a bad regex |
| Dashboard | its `ui/jobs` files are present | moved or missing |
| Job sources | which have keys, which need none | — |

Each check returns a status, and on failure a **problem**, a **cause** and a
**suggested fix** — a health check that says `FAILED` without naming the fix
is a worse version of the traceback it replaced.

Three states, not two: `ok`, `warn` (works, degraded — no Adzuna key, no
neural voice) and `fail` (something is actually broken).

### Files

| File | Change |
| --- | --- |
| `jarvis/app/health.py` | new — the probes and the report |
| `jarvis/tools/registry.py` | register `system_check`, `check_component` |
| `jarvis/routing/router.py` | route "run a system check", "are you healthy" locally |
| `tests/test_health.py` | new |
| `README.md` | document it |
| `JARVIS_PHASE2_PLAN.md` | mark 23 complete |

Nothing existing is modified beyond two registration lines.

### Tests

- every probe returns one of the three states and never raises, including
  when the package it probes is absent
- a missing API key produces `fail` on config, not a crash
- a missing optional package produces `warn`, not `fail`
- every failing check carries a non-empty cause and suggested fix
- the registry check detects a deliberately desynchronised tool
- the report renders with no probe reaching the network, so CI can run it
- the full 123 keep passing

### Risks

The live API probe costs a request and needs the network, so it runs only in
the full check, is skipped in tests, and is the one probe allowed to be slow.

The browser probe must not launch a browser — starting Chromium to prove
Chromium starts would make the check take ten seconds. It checks for the
executable instead and says so.

The mic probe enumerates devices without opening a stream, so it can't
collide with a listener that is already running.

### Chapter 23 — what shipped

| File | Change |
| --- | --- |
| `jarvis/app/health.py` | new, 553 lines — 17 probes, 1 live probe, the report |
| `jarvis/tools/registry.py` | `system_check` and `check_component` registered |
| `jarvis/routing/router.py` | three local routes, no model call |
| `tests/test_health.py` | new, 65 tests |
| `README.md` | a Self-diagnostics section |
| `jarvis/app/assistant.py` | two stale imports fixed |
| `jarvis/tools/whatsapp.py`, `whatsapp_web.py`, `browser.py` | stale `confirm_fn` import fixed |

Tests went 123 → 188, all passing. Tool count 65 → 67. Router patterns
40 → 43. The whole report runs in 0.9 s on this machine.

### What it caught on day one

Four imports left broken by the Phase 1 refactor, none of which any test or
any amount of use had found, because a function-level import doesn't run
until the one command that needs it does:

| Where | Imported | Effect |
| --- | --- | --- |
| `app/assistant.py:162` | `.brain` | every command that reached the AI died |
| `app/assistant.py:140` | `.voice` | "list microphones" died |
| `tools/whatsapp.py:62` | `.tools` | `send_whatsapp_message` died at the gate |
| `tools/whatsapp_web.py:152` | `.tools` | `wa_send_web` died at the gate |
| `tools/browser.py:272` | `.tools` | `click_text` died at the gate |

The three gated ones failed closed — nothing was ever sent without
confirmation — but they failed. This is why probe 17, `imports`, was added
beyond the plan: it reads all 101 internal imports statically, so this class
of bug can't hide again.

Two more defects it now reports that nothing checked before: drift between
`TOOL_SCHEMAS` and `FUNCTIONS`, and `BASE_DIR` resolving to the package
instead of the project — the bug that made `.env` silently unread.

A third defect, in the health check itself: the browser probe looked only
at PATH, where Windows puts neither Chrome nor Edge, so it reported "no
browser" on a machine with two. It now checks the standard install
locations, and an installed browser without Playwright's own Chromium
warns rather than fails — the difference between a 200 MB download someone
needs and one they don't.

Deviations from the plan: the `imports` probe was added (16 probes planned,
17 shipped). Two wording fixes were made while testing — a doubled article
in the package warning, and a summary that read "0 thing(s) broken" when
only warnings were present.

## Chapter 24 — plan

### What is already there

A shared normaliser already exists — `sources._job()` — so the roadmap line
"no shared normaliser" was wrong. Six adapters all pass through it, dedup by
`job_id` already happens in `search()`, and each source already reports its
own count rather than disappearing into a total.

What the spec asks for and the code does not have:

| Field the spec requires | State |
| --- | --- |
| title, company, location, url, source | stored |
| remote / hybrid / on-site | stored, detected from text |
| salary | stored when the board gives one |
| required skills | derived by the matcher |
| **employment type** | missing entirely |
| **publication date** | every API sends one; `_job()` discards all of them |

Also listed as unfinished: location filtering, job-type detection, seniority
detection. Scoring is Chapter 25 and stays out of this one.

### What this chapter does

1. **Posting date.** Each adapter reads its own date field — Adzuna
   `created`, Remotive `publication_date`, Jobicy `pubDate`, The Muse
   `publication_date`, RemoteOK `epoch`, Arbeitnow `created_at` — normalised
   to one ISO string. Shown as an age ("posted 3 days ago"), because that is
   the form the answer is actually wanted in.
2. **Employment type.** full-time / part-time / contract / internship /
   temporary, from the board's own field where it has one, from the title
   and description where it doesn't.
3. **Seniority.** intern / junior / mid / senior / lead, from the title
   first, since titles are far more reliable than descriptions here.
4. **Location, structured.** City and country split out of the free-text
   location, so "remote (India only)" and "Bengaluru, India" both answer the
   question the search is really asking. Chapter 25 scores it; this chapter
   only has to extract it honestly.
5. **Freshness.** Sort and filter by date, and say when a board returns
   nothing but stale postings rather than quietly showing month-old work.
6. **Source attribution** on the dashboard and in every listing, so it is
   always visible which board a job came from.

### Files

| File | Change |
| --- | --- |
| `jarvis/jobs/normalise.py` | new — date parsing, employment type, seniority, location |
| `jarvis/jobs/sources.py` | each adapter passes its date and type through |
| `jarvis/jobs/store.py` | three new columns, added by migration |
| `jarvis/jobs/engine.py` | freshness in the listing, source attribution |
| `ui/jobs/*` | show age, type and source |
| `tests/test_normalise.py` | new |

### The migration

Three columns are added to `jobs`: `posted_at`, `employment_type`,
`seniority`. `jobs.db` on your machine has real rows in it, so the migration
reads `PRAGMA table_info` and adds only what is absent — it runs on every
start, changes nothing once applied, and drops nothing ever. A test builds a
database with the old schema, migrates it, and checks the old rows survived.

### Risks

A date that can't be parsed must leave the job in the list without a date,
never drop it. Half the boards use a format the others don't, and a job with
no date is still a job.

Employment type guessed from text will sometimes be wrong. It is stored as a
guess and shown as one; Chapter 25 must not treat it as certain.

### Chapter 24 — what shipped

| File | Change |
| --- | --- |
| `jarvis/jobs/normalise.py` | new — dates, employment type, seniority, location |
| `jarvis/jobs/sources.py` | all six adapters pass their date and type through |
| `jarvis/jobs/store.py` | five new columns, added by migration; freshness filter |
| `jarvis/jobs/engine.py` | age, type and source in the listing |
| `jarvis/jobs/dashboard.py`, `ui/jobs/*` | age line per card, stale marked amber |
| `jarvis/routing/router.py` | "show new jobs", "jobs posted in the last N days" |
| `tests/test_normalise.py` | new, 100 tests |

Tests went 188 → 303. Tools unchanged at 67; router patterns 43 → 45.

Correction to the roadmap: it claimed there was no shared normaliser. There
was — `sources._job()` — and six adapters already went through it. What was
actually missing was employment type, which existed nowhere, and the posting
date, which every board sends and `_job()` discarded.

The decision worth recording: an unreadable field comes back empty and is
never invented. A parser that gives up and stamps the job with today's date
makes every stale posting look fresh, which is the one failure that would
send someone to apply for work that closed in July. Eleven tests hold that
line, and a job with no date is never filtered out by a freshness question
either — not knowing when something was posted is not evidence that it is
old.

Found on the user's machine straight after shipping: "find jobs for me"
appeared to do nothing. The fast path calls six boards one after another at
25 seconds each — up to two and a half minutes of a voice assistant saying
nothing, which is indistinguishable from broken. The six are now asked in
parallel (they never depended on each other), the timeout is 15 seconds, and
any local command that goes to the network announces itself before starting.
The comment above that code said "usually milliseconds, no model call",
which was true when it was written and stopped being true when the job
search was added to the same path.

A second, larger one found from a screenshot of the panel: a typed command
kept its wake word. Speech arrives with "Jarvis" already stripped by the
wake-word matcher; typing does not, and the panel invites you to type. So
"Jarvis, find jobs for me" matched no local pattern, fell through to the
model, and sat at THINKING for eighty seconds doing what the router answers
instantly. Every typed command had been bypassing the fast lane — the
central idea of the whole project — since the panel was built. `handle()`
now strips an opening address, and only an opening one: "what does jarvis
mean" is a question about the name, not an instruction.

Deviations from the plan: none. The migration behaved as planned — a test
builds a database with the old schema, migrates it, and checks an APPLIED
row kept its status, its score and its history.

## Chapter 25 — plan and outcome

The old score had six components (skills 45, title 20, location 15,
experience 10, education 5, projects 5) with a working cap system already in
place. The spec asks for nine, named exactly: Skills, Role, Experience,
Education, Location, Work Mode, Employment Type, Projects, Seniority — and
a transparent per-dimension report with strong/partial/missing skills and
named concerns, never a claim that a job is suitable.

### What changed

Weights now sum to 100 (`skills 30, role 16, seniority 12, experience 12,
location 12, employment_type 6, work_mode 6, education 4, projects 2`), so
the total is a percentage of a perfect fit rather than points out of an
arbitrary ceiling. Seniority, work mode and employment type are new,
independent dimensions — Chapter 24's fields feed straight into them rather
than being folded into "title" as before.

Skills got a third state. A posting asking for Next.js when the candidate
knows React was previously a flat miss; it now counts as **partial** credit
(half a match), reported with the actual bridging skill named — "you have
react" — never just "something close." Twenty-eight technology pairs are
mapped this way.

`explain()` was rewritten to the spec's own shape — a MATCH ANALYSIS header,
every dimension's raw score and its weighted share, ✓/△/✗ skill lists, and a
⚠ Potential concerns section (a cap, a stretch experience bar, a stale
posting) — and ends with "whether it's worth applying to is your call"
rather than any verdict.

`employment_types` became a settable preference (`jarvis, set employment
type to internship, full-time`), since Chapter 24 introduced the field but
nothing let the candidate say which ones they want.

### What it caught

`engine.open_board` — "open linkedin", "open naukri" — called a function
name (`_query_from`) that Chapter 24's refactor had renamed to
`_queries_from`. It had raised NameError since that refactor shipped, and no
test called it because nothing exercised it: 314 tests passed while that
path was broken. Fixed, and the health check gained an eighteenth probe
(`check_names`) built specifically to catch this class of bug — a rename
with a caller left behind — by reading compiled bytecode for every
`LOAD_GLOBAL` and checking the name actually exists. It proved itself
immediately: reintroducing the old bug made it fail with the exact line.

A schema slip surfaced by a test, not by running the app: the `INSERT`
statement's placeholder count and column count were off by one after adding
`skills_partial`, caught by a round-trip test before it ever reached a real
search.

### Files

| File | Change |
| --- | --- |
| `jarvis/jobs/matching.py` | rewritten — nine dimensions, bridges, concerns |
| `jarvis/jobs/resume.py` | `employment_types` preference |
| `jarvis/jobs/engine.py` | fixed `open_board`'s NameError |
| `jarvis/jobs/store.py` | `skills_partial` column, via migration |
| `jarvis/routing/router.py` | "set employment type to..." |
| `jarvis/tools/registry.py` | schema mentions `employment_types` |
| `jarvis/app/health.py` | new `check_names` probe (18th) |
| `ui/jobs/app.js`, `app.css` | partial-skill chips, concerns |
| `tests/test_matching.py` | new, 48 tests |
| `tests/test_jobs.py` | old breakdown-shape assertions updated |
| `tests/test_health.py` | 3 tests for `check_names` |

Tests went 314 → 362. Tools unchanged at 67; probes 17 → 18.

Deviations from the plan: none in scope. `check_names` was not in the
Chapter 24 plan or this one — it exists because Chapter 25's own testing
found a bug that only bytecode inspection could have caught in advance.

## Interlude — the assistant becomes LITTLE

Between Chapters 25 and 26, at the user's request, the assistant was renamed
from JARVIS to LITTLE, with a new persona, voice and wake word. It is not a
roadmap chapter; it is recorded here so this file stays an accurate history.
Full details are in `LITTLE_IDENTITY.md`.

Two things found during it are worth keeping in mind for later chapters.
"Little" is an everyday word, so the wake word now only counts at the start
of a phrase — without that, "I need a little help" woke it. And an `.env`
made from the old template pins the old voice, so the rename changes nothing
audible until three lines are edited; the system check now points that out.

Tests went 362 → 441. No package, setting, table or file was renamed.

## Chapter 26 — plan and outcome

Where it started: the resume was read into a profile, and the UI-7 Resume
section already edited the job preferences and asked six questions about
it. What the roadmap said was missing — no CGPA, no achievements, no way to
correct the profile — was still missing. You chose four things, and two
rules for them: a new resume scan replaces corrections (rather than keeping
them, as preferences are kept), and corrections are made by command only,
not in the window.

### What it does

**Reads more, and only what's there.** The profile gains `degree_score`,
`class_12` and `class_10` (as the resume writes them — "7.0/10", "85.4%"),
`achievements` and `links`. The model is told never to convert a CGPA into a
percentage or back. Then each is held to the resume's own text
(`resume.only_what_it_says`): a score whose number isn't in the text, a link
that isn't in it, an achievement whose words aren't in it — each was made up
and is left out, and the log says so. A score the model missed but the text
states plainly on one line is read from the text on this computer
(`grades.scores_in`); a field with two different candidates stays empty
rather than guessed.

**Correcting by command.** `set my phone to …`, `set my cgpa to 7.8/10`,
`set my 12th percentage to 85%`, `add Docker, AWS to my skills`, `add project
…`, `remove QuantDesk from my projects`, `set my github to github.com/you`,
`clear my cgpa` — and `meri cgpa 7.2 kar do`. On this computer, no model
call. Each value is checked (an email is an address, a phone has 7–15
digits, a year is four digits, a score is a score); a bare `7` is saved as
`7/10` so it can't be misread later. GitHub and LinkedIn have one slot each.
An ambiguous remove removes nothing and asks for more. Each correction is
marked, the Resume section shows "corrected by you" beside it, and the first
one says a new scan replaces it. The model can do the same through
`update_resume_profile`. **`set my location to …` is still the job-search
preference it always was**; your own address is `set my address to …`.

**A new scan replaces corrections, and says so.** The window's rescan
question names them ("including what you corrected (phone, CGPA or %)"), and
the reply after says which were replaced. Preferences you set are still kept.

**Academic bars as concerns.** `grades.cutoffs` reads "CGPA of 7.5 and
above", "7+ CGPA", "60% throughout", "65% in 12th and 60% in graduation",
"12th: 70%, B.Tech: 7 CGPA", "3.5/4 GPA" — each bar attached to the exam
named nearest it. Salary, remote-work, hike and growth percentages are not
bars, and "no CGPA cutoff" has none. `grades.concerns` compares on the same
scale only: below it, not stated on the resume, or on a different scale
("check how your university converts it") — and "65% or 6.5 CGPA" is met by
meeting either. It's a concern on the job card and in `why job 1`: **the
score doesn't change and the job isn't hidden.** A correction or a new scan
re-scores the stored jobs (`engine.rescore_stored`), keeping each job's
status and history.

**A resume check on this computer.** `check my resume`, or the Resume
section's new card: contact details, GitHub and LinkedIn, degree and batch,
CGPA (and how many of your stored jobs ask for more), projects (and whether
any has a real number — a year doesn't count; "never estimate ones you
don't have"), skills no project mentions, length, achievements (a note, not
a demand), what your stored jobs ask for, and your corrections. Nothing is
sent to the model.

### Files

| File | Change |
| --- | --- |
| `jarvis/jobs/grades.py` | new — reading scores and bars, comparing on one scale |
| `jarvis/jobs/resume_check.py` | new — the resume check |
| `jarvis/jobs/resume.py` | new fields and prompt rules, `only_what_it_says`, `edit_profile`, `save_scanned` |
| `jarvis/jobs/matching.py` | academic concerns on each job |
| `jarvis/jobs/engine.py` | `rescore_stored` |
| `jarvis/routing/router.py` | correction commands, `check my resume` |
| `jarvis/tools/registry.py` | `update_resume_profile`, `check_resume` (69 tools; still 5 ask first) |
| `jarvis/app/bridge.py` | the check as a Resume task, corrections in the snapshot, the scan's new message |
| `ui/index.html`, `ui/js/views/resume.js` | marks, achievements, links, "corrected by you", the check's card, the rescan question |
| `ui/js/views/sections.js` | "Check my resume" in the palette |
| `tests/test_resume_intelligence.py` | new |
| `tests/test_shell.py` | the new palette command registered |

Tests went 1388 → 1513 (the UI/UX redesign, recorded in
`LITTLE_UI_UX_REDESIGN_PLAN.md`, took them from 441 to 1388). Thirty-nine planted
regressions — scales converted, money and remote percentages read as bars,
"no CGPA cutoff" read as one, alternatives not honoured, a bar given the
wrong exam, meeting a bar still a concern, a score or link or achievement
the resume doesn't contain kept, two scores guessed between, corrections
kept by a new scan or not mentioned, bad emails and phones accepted, a bare
CGPA saved without its scale, `set my github` wiping every link, an
ambiguous remove guessing, a project split on its commas, corrections
unmarked, stored jobs not re-scored (or re-scored on a phone change, or
their status reset), a name lowercased, `set my location` taken from the job
search, the bar missing from the job or lowering its score, the check
asking the model, a year counted as a result, achievements demanded, a
broken email passed, and on the page every field marked, marks missing and
the rescan question hiding corrections — each fail as they should.

Deviations from the plan: none in scope. Not done, on purpose: filling
GitHub and LinkedIn into application forms (Prepare still fills name,
email, phone and location only), and editing the profile in the window (you
chose commands).


## Chapter 27 — plan and outcome

Where it started: ten statuses (FOUND, SHORTLISTED, READY_TO_APPLY,
APPLIED, APPLICATION_FAILED, NEEDS_USER_ACTION, REJECTED, INTERVIEW, OFFER,
WITHDRAWN), any of which could be set from any other, an `applications`
table and an `audit` table, but no history per job.

**The ten Phase 2 statuses**, in order: FOUND, ANALYZED, SAVED, PREPARED,
USER_APPROVED, SUBMITTED, then INTERVIEW, OFFER, REJECTED, WITHDRAWN.
`store.TRANSITIONS` says where each can go: forward is free (a recruiter
can call about a job you never saved), nothing goes back to before you
applied, and an ended job stays ended. `store.change_status` enforces it
and writes every change to a new `job_events` table with its source, note
and evidence.

**SUBMITTED needs proof.** "I applied" is USER_APPROVED — your word,
recorded as your word. SUBMITTED is reached only from PREPARED or
USER_APPROVED, and only with evidence: `verify_submission` reads the page
already open in LITTLE's browser (it never starts one, never clicks) and
needs a confirmation message ("thank you for applying", "application
received") on a page about this job — its host, company or title; or
`mark_submitted` with a confirmation number you give. The direct setter
refuses SUBMITTED outright, and an application record can't claim it.

**What sets each status.** A search: FOUND. Looking at the full analysis
(`why job 1`, Match): ANALYZED — for a job further along, a history line
instead. Save: SAVED. Prepare application: PREPARED, with how many fields
it filled and what the form asks that is yours to answer; a posting that
won't open changes no status and goes in the history. "I applied":
USER_APPROVED. Proof: SUBMITTED.

**History everywhere.** Each Jobs card has a History disclosure and offers
only the status moves the store allows (sent by Python, so the page can't
offer one it would refuse). `history of job 1` / `job 1 timeline` reads the
timeline; `application status` and the dashboard count applied (your word)
and verified submissions apart, with every status counted.

**The old statuses are renamed once.** On first open the database is
copied to `jobs.before-chapter27.db`, then SHORTLISTED → SAVED,
READY_TO_APPLY and NEEDS_USER_ACTION → PREPARED, APPLIED → USER_APPROVED
(not SUBMITTED: it was never verified), and APPLICATION_FAILED → FOUND with
the failure in the history. Each renamed job keeps its old name in its
history. The old words are still accepted as input.

**A router bug found on the way:** "timeline of 1" was answered with the
time — the time pattern matched any word starting with "time". Fixed with a
word boundary; "timer" no longer gets the time either.

### Files

| File | Change |
| --- | --- |
| `jarvis/jobs/store.py` | statuses, transitions, `job_events`, `change_status`, `history`, `record_submission`, the rename with its backup, counts |
| `jarvis/jobs/apply.py` | `verify_submission`, `mark_submitted`; applying and marking through the transitions |
| `jarvis/jobs/engine.py` | ANALYZED on analysis, `job_history`, application status and effectiveness in the new terms |
| `jarvis/tools/browser.py` | `current_page` — the open page, never starting the browser |
| `jarvis/tools/registry.py` | `verify_submission`, `mark_submitted`, `job_history` |
| `jarvis/routing/router.py` | history, verify and confirmation commands; the time pattern's word boundary |
| `jarvis/app/bridge.py` | each job's history and allowed moves in the snapshot; the verify action |
| `ui/js/views/jobs.js`, `ui/css/components.css` | new status labels, History, moves from Python |
| `ui/jobs/app.js` | applied and verified submitted as separate tiles |
| `tests/test_application_tracker.py` | new |
| `tests/test_jobs.py`, `test_jobs_section.py`, `test_normalise.py`, `test_resume_intelligence.py` | status assertions under the new names (SHORTLISTED → SAVED, READY_TO_APPLY → PREPARED, APPLIED → USER_APPROVED); the migration test also checks the old name is kept |


## Chapter 28 — plan and outcome

Where it started: separate browser tools — open, read, summarise, click by
words, fill by label, press a key — with clicks on "pay/buy/submit/delete"
words asking first. Nothing looked at a page as a whole, and nothing
checked that a step did what it was meant to.

**`jarvis/tools/browser_agent.py`**, on the same single browser thread:

- **Observe.** One script on the page returns its address, title,
  headings, text, links, buttons (and which submit a form), every form's
  visible fields (label, type, required, filled, marked invalid), the
  page's own error messages, whether it is still loading and whether it
  can go back. `look_at_page` describes it; it never starts a browser that
  isn't open.
- **Act.** One step from a fixed set — open, click, fill, select, press,
  back — checked first: only http/https addresses; a click on anything that
  submits a form, or whose words could submit, send, buy or delete, asks
  you (the same dialog as every other question); Enter on a page with a
  form asks; a password, one-time code or card field is never typed into,
  asked or not; a submit or apply on LinkedIn, Naukri, Indeed, Internshala
  or Wellfound is never pressed (their terms forbid it — matched on the
  host name, whatever the port).
- **Verify.** After each step the page is observed again and checked: the
  step's own expectation (the address, the text, the title), or what the
  step implies (a field holds what was typed; a click or key changed the
  page; an address opened). A new error message on the page fails it. A
  step that isn't verified is reported as "Not verified", never as done.
- **The loop (`browser_task`).** The model sees the goal, the steps so far
  and the page, and answers one step as JSON from that set; LITTLE checks,
  acts and verifies it. It stops at the first step refused, failed or not
  verified, at a reply that isn't a step, when the model is unreachable, or
  after eight steps — and lists every step with what was verified.

`what's on this page` and `in the browser, <goal>` reach them without the
model deciding to.

**Found on the way:** the job-board block compared the whole network
location, so a port number hid the host; it compares host names now.

Deferred to Chapter 37 (permission levels): listing `browser_task` among
the tools that can ask first. The gate itself is in place now.

### Files

| File | Change |
| --- | --- |
| `jarvis/tools/browser_agent.py` | new — observe, check, act, verify, the loop |
| `jarvis/tools/registry.py` | `look_at_page`, `browser_task` |
| `jarvis/routing/router.py` | "what's on this page", "in the browser, …" |
| `jarvis/app/bridge.py` | the new tools grouped under Browser |
| `tests/test_browser_agent.py` | new — a real headless browser against a site served by the test |


## Chapter 29 — plan and outcome

Where it started: `take_screenshot` saved a picture and `describe_screen`
sent one to the model and read back a description. Nothing located a
thing on the screen, and nothing acted on what the model saw.

The order of preference is fixed: **words before pictures**. A page in
LITTLE's own browser is handled through its page structure (Chapter 28),
where a button is found by its text and every gate applies. A picture is
the fallback, for everything outside that browser.

**`jarvis/tools/screen.py`:**

- **Capture.** On request only, never in the background. The picture sent
  is shrunk to 1600 px; the real screen size is kept so a position on the
  picture can be scaled back to the screen.
- **Recognise (`locate`).** The model answers one JSON object: found or
  not, the element's words, a box, its own confidence and whether clicking
  it could pay, send, submit, delete or install. Every answer is checked
  before anything uses it: a reply that isn't JSON, a confidence that
  isn't a number, a box off the picture or with no size — each counts as
  *not found*, with the reason said. The model is told not to guess.
- **`find_on_screen`** says where something is and how sure the model is
  (its own estimate, named as such). It clicks nothing.
- **`click_on_screen`** first looks at LITTLE's browser: if the words are
  among the open page's buttons or links, it clicks there by words, and the
  browser's checks (submit asks, job boards never submitted) still apply.
  Otherwise it locates from a picture and clicks only when all three hold:
  the model is at least 85% sure; the target isn't risky (the model's flag
  *or* risky words in what you named or what it read — pay, buy, order,
  delete, send, submit, apply, install, allow, sign out, shut down…); and
  you say yes to a question that names the place and how sure it is.
  Below 85% it asks nothing and clicks nothing. A risky target is never
  clicked from a picture, however sure — you click it yourself.

`where is X on screen` and `click X on my screen` reach them without the
model deciding to. `look at my screen` still describes, unchanged.

Deferred to Chapter 37 (permission levels): listing `click_on_screen`
among the tools that ask first. The gate itself is in place now.

### Files

| File | Change |
| --- | --- |
| `jarvis/tools/screen.py` | `_capture` with sizes, `locate`, `find_on_screen`, `click_on_screen`; the existing screenshot and describe unchanged |
| `jarvis/tools/registry.py` | `find_on_screen`, `click_on_screen` |
| `jarvis/routing/router.py` | "where is X on screen", "click X on my screen" |
| `tests/test_computer_vision.py` | new — capture, recognition, uncertain answers, the click gates, browser first |

## Chapter 30 — plan and outcome

Where it started: `remember that X is Y` stored a fact, `what do you
remember` read them all back, the Memory section could forget one, and the
conversation was the model's own history. One flat list, no update, no
forget by command, and anything could be stored — a password included.

**Five tiers, each kept only as long as it's useful** (`jarvis/store/memory.py`):

| Tier | What | Where | Lasts |
| --- | --- | --- | --- |
| Short-term | the conversation in progress | the model's history, RAM | until New conversation or a restart |
| Task | notes the model makes while a task runs | RAM, by task id | until that task ends (the last 20 at most) |
| Project | facts about one named project | `project_memory.json` | until you forget them |
| Long-term | facts you asked to be remembered | `preferences.json` → `facts` (unchanged) | until you forget them |
| Preferences | how you like things | `preferences.json` → `preferred` | until you forget them |

- **Remember / update.** Saying a fact again with a new value updates it
  and says what it was ("Updated: editor is now Neovim (it was VS Code)");
  the same value changes nothing. Project names keep their capitals and
  match whatever capitals you use later.
- **Recall.** `what do you remember` is every tier; `… about X` searches all
  of them by shared words (a word in the name ranks higher), says where
  each answer is kept, and says plainly when nothing matches. A task sees
  only its own notes.
- **Forget.** By exact name, allowing only for a leading "my". A name kept
  in more than one place forgets nothing and says where it is. Forgetting a
  whole project asks first, with what would go; no answer is a no.
- **Nothing secret.** Passwords, one-time codes, PINs, card, Aadhaar, PAN,
  passport and account numbers, API keys and tokens are refused in every
  tier — by the words used for them, by the shapes keys are published in,
  and by the card checksum (so a phone number or an order id is fine, and
  "pin code" is a postcode). The conversation log hides them as
  `[hidden]` before it's written.
- **Isolation.** Each project answers only for itself; each task reads only
  its own notes, on whichever thread; everything is in the memory folder.
  Nothing goes to the model with a request — checked on the request
  itself — and only what a lookup (`recall_memory`) returns reaches it.

Commands, answered on this computer with capitals kept: `remember that …`,
`remember that my preferred browser is Firefox`, `remember for project
Blood Bridge that the deadline is Friday`, `what do you remember (about
…)`, `what do you know about project …`, `what are my preferences`,
`forget my editor`, `forget deadline from project …`, `forget project …`.
"forget it" and long sentences starting with "forget" still go to the
model. Tools for the model: `recall_memory`, `remember_preference`,
`remember_for_project`, `recall_project`, `forget_for_project`,
`note_for_task`; `forget` now forgets from any tier.

The Memory section lists preferences and project facts under "You asked me
to remember", tagged with where each is kept, and forgets each by its
exact key and place.

### Files

| File | Change |
| --- | --- |
| `jarvis/store/memory.py` | tiers, update wording, search, forget by name, sensitive checks, log redaction |
| `jarvis/routing/router.py` | memory commands matched on what you typed |
| `jarvis/tools/registry.py` | six memory tools; `forget` covers every tier |
| `jarvis/app/tasks.py` | a finished task's notes are dropped |
| `jarvis/app/bridge.py` | preferences and projects in the Memory snapshot; forget by place |
| `ui/js/views/memory.js`, `ui/js/core/bridge.js`, `ui/app.css` | tagged rows, forget by place |
| `tests/test_true_memory.py` | new |
| `tests/conftest.py`, `tests/_ui.py` | project and task memory reset per test; the stub records where a forget is from |

## Chapter 31 — plan and outcome

Where it started: nothing. `read_file` could read a PDF or Word file into a
single request, and the model answered from whatever it was handed.

**`jarvis/store/knowledge.py`** — parse, chunk, embed, store, retrieve, answer:

- **Parse.** Text, Markdown, code, CSV, JSON, YAML, HTML (scripts and styles
  dropped), PDF (each page kept with its number) and Word, only from inside
  the workspace — the sandbox every file tool uses. Unsupported types, files
  over 20 MB and unreadable PDFs are refused in a sentence.
- **Chunk.** Paragraphs packed into parts of about 900 characters; each part
  carries the last ~150 characters of the one before, so a sentence cut at
  a boundary is still found whole. A part never spans two pages.
- **Embed.** On this computer: word stems (a crude stemmer, so "deadlines"
  and "deadline", "deployed" and "deployment" meet) and adjacent pairs,
  without the little words. Nothing is sent anywhere to add a document.
  Semantic embeddings from a provider are future work — this chapter
  measures what local lexical retrieval does first.
- **Store.** `knowledge.db` in the memory folder: documents (name, path,
  SHA-256, pages, parts) and parts with their vectors. Adding the same
  unchanged file does nothing; a changed file is read again and its old
  parts dropped. Removing takes it out of the index and never touches the
  file. The log records counts only, never text.
- **Retrieve.** A part must hold at least half the question's words to
  count at all; those that do are ranked by BM25, so a rare word outweighs
  a common one said often and a long part doesn't win by length. At most
  four parts.
- **Answer.** Only the retrieved parts go to the model, numbered with their
  source. It answers in JSON: facts, each citing parts, and a separate
  suggestion. Every fact is checked — it must cite a real part, and the
  cited parts must hold at least 60% of its words. What passes is shown as
  `RETRIEVED FACT: … [file, page N]`; everything else, including a "fact"
  that fails the check, is shown as `GENERATED SUGGESTION (the model's own,
  not in your documents)`. Nothing retrieved: the model isn't asked and
  nothing is guessed. The model unreachable or its reply unreadable: the
  passages themselves are the answer, labelled RETRIEVED.

Commands: `add notes.pdf to my knowledge base` (a folder adds every readable
file in it, skipping `node_modules` and the like), `what's in my knowledge
base`, `remove notes.pdf from my knowledge base`, `search my documents for
…` (no model), `ask my documents …` / `according to my notes, …`. Adding,
listing and removing need the words "knowledge base" — "add this to my
documents" could mean the Documents folder. Tools for the model:
`add_document`, `list_documents`, `remove_document`, `search_documents`,
`ask_documents`. The Memory section lists the documents by name.

Measured on the test corpus: the right document first for every one of eight
questions, including "where is it deployed" (deployment) and "which
database"; nothing retrieved for five unrelated ones.

### Files

| File | Change |
| --- | --- |
| `jarvis/store/knowledge.py` | new |
| `jarvis/routing/router.py` | knowledge-base commands, matched on what you typed |
| `jarvis/tools/registry.py` | five tools |
| `jarvis/app/bridge.py` | documents in the Memory snapshot; the tools grouped as "Your documents" |
| `ui/js/views/memory.js` | a "Your documents" row |
| `tests/test_knowledge_base.py` | new — a real PDF and Word file, retrieval quality, the answer checks |
| `tests/conftest.py` | the knowledge base starts empty for every test |

## Chapter 32 — plan and outcome

Where it started: the model wrote a numbered list, each step went through
the brain, and a reply starting "FAILED" (or saying "couldn't") stopped the
plan. A step was "done" whenever the model didn't say otherwise.

**`jarvis/ai/planner.py`** now runs every plan the same way:

  GOAL → UNDERSTAND → PLAN → EXECUTE → OBSERVE → VERIFY → RECOVER → RESULT

- **Understand + plan** — one call. The model restates the goal in one
  sentence ("Goal: …" in the activity log) and answers JSON: steps, each
  with how to tell it worked (`check`) and the files it should leave
  (`files`). A plain numbered list still works; its steps have no check.
  Nothing else the model writes is shown — no reasoning, only the goal,
  the steps, results and evidence.
- **Execute** — each step through the brain with the tools it already has,
  and their gates: deleting, running a command, sending all ask you.
- **Observe** — the tools that ran during the step and what they returned,
  read from the brain's own history; and every confirmation answer, now
  recorded by `permissions` whatever dialog asked (tool, action, yes/no,
  thread — never the message or command itself).
- **Verify** — files the step should leave are looked for on disk, inside
  the workspace only. The check is judged by a second call that sees only
  the tools' output; if no tool ran, there's nothing to judge by and the
  step is *not checked* — never "done" on the model's word. A check that
  can't run or can't be read is also *not checked*, not a pass.
- **Recover** — a step that failed or wasn't verified gets one more try,
  told what went wrong. Not after you said no to something in it: your no
  ends the plan ("You said no during step 2 of 4, so I stopped there.
  Nothing after it ran."). A stop between tries is honoured. A no on
  another thread isn't this plan's.
- **Result** — "Done, all 4 steps, each checked." only when each was;
  otherwise which steps couldn't be checked, or where it stopped and why.

**"Prepare my project for GitHub"** is planned (it wasn't before), and the
plan is told to start and end with the new `check_github_ready` tool
(`jarvis/tools/project_check.py`, reads only): a README; a `.gitignore`;
no secret files (`.env`, keys, credentials — `.env.example` is fine) or
key-shaped strings in what would be committed; `node_modules`, `venv` and
the like kept out; nothing over 50 MB; git set up. The `.gitignore` is read
the way git reads it for the common forms, including `!` to let something
back in (the last match decides). When the plan is done, LITTLE runs the
checklist again itself on the folder the plan looked at; if anything is
still open, the plan ends as failed with what's left — the model saying
"it looks ready" doesn't make it so. Pushing is a command, and asks.

Two existing tests changed with the behaviour, both kept as strict: a
failed step now fails twice (its retry too) before the rest is shown not
to run, and the Task Center test also checks the retry is recorded under
its step.

### Files

| File | Change |
| --- | --- |
| `jarvis/ai/planner.py` | the loop above |
| `jarvis/ai/prompts.py` | PLAN asks for JSON with checks; STEP carries the check; VERIFY and RECOVER |
| `jarvis/tools/permissions.py` | every answer recorded (`answers`, `last_answer`), whatever is installed |
| `jarvis/tools/project_check.py` | new — the GitHub readiness checklist |
| `jarvis/tools/registry.py`, `jarvis/app/bridge.py` | `check_github_ready`, grouped under Files |
| `jarvis/app/assistant.py` | the planning brain exposes its history to the planner |
| `tests/test_planner_v2.py` | new |
| `tests/test_planner.py`, `tests/test_task_center.py` | the failed-step tests fail the retry too |

## Chapter 33 — plan and outcome

Where it started: the router answered what it could on this computer and
everything else went to the model or the planner. The task record said
`local`, `model` or `plan`; nothing was timed except individual tools.

**Four paths, cheapest first:**

| Path | What answers | Examples |
| --- | --- | --- |
| fast | what LITTLE already holds — no network, no model | time, date, memory, reminders, "how fast are you", stop, new conversation |
| normal | this computer's own tools, still no model | job search, a web search, a page, files, the knowledge base, a system check |
| ai | one conversation with the model (which may call tools) | anything the router doesn't know |
| agent | a plan of checked steps (Chapter 32) | "create a react app and run it", "prepare my project for GitHub" |

- The router marks its fast answers itself (per thread), so the path comes
  from the code that answered, not from how long it happened to take. A
  local answer not marked fast is normal; a section button's task is
  normal or ai by its route.
- Each task carries its `path`. When a task finishes, its own measured time
  (start to reply) is recorded under its path — once, whoever finished it —
  and the router's own time is recorded for every command, since trying
  locally first is a cost even when the model answers in the end.
- `jarvis/app/latency.py` keeps the last 200 of each in RAM and reports
  count, median, 95th percentile (nearest rank), slowest and latest.
  `how fast are you` says it in words; with nothing measured it says so.
  Nothing is estimated and nothing is written to disk.

A router error still falls through to the model, as before.

### Files

| File | Change |
| --- | --- |
| `jarvis/app/latency.py` | new |
| `jarvis/routing/router.py` | fast answers marked; `last_path()`; the speed report command |
| `jarvis/app/tasks.py` | `path` on each task; set from the route, overridden to fast; timed at finish |
| `jarvis/app/assistant.py` | the router timed; paths set |
| `tests/test_local_first.py` | new |

## Chapter 34 — plan and outcome

Where it started: every phrase the microphone picked up went to Google's
speech service, and only its transcript was checked for the name
(`wake.wake_position`, with its rules for "a little bit" and misheard
"Jarvis"). So everything said in the room was sent, name or not.

**`jarvis/voice/local_wake.py`**, used by `Listener.listen(wake=True)`:

- **Local detection.** With pocketsphinx installed, each phrase is first
  checked on this computer by keyword spotting for the real names only —
  "little" and "jarvis" (the misspellings are for the cloud's transcripts,
  and aren't in the offline dictionary). No name: the phrase is dropped
  here and never sent anywhere.
- **False positives.** A phrase that passes still goes to the cloud and its
  transcript must open with the name under the existing rules before
  anything runs. A false alarm here costs one transcription, not a
  command. Both are counted: kept here, passed, confirmed, rejected.
- **Sensitivity.** `JARVIS_WAKE_SENSITIVITY` (0.05–0.95, default 0.6;
  higher hears the name more readily and wakes by mistake more often).
- **Calibration and noise.** "Calibrate the wake word" listens to the room
  for a few short phrases; each bit of noise that passes as the name
  lowers the sensitivity a step (never below 0.2) and says what to put in
  .env to keep it. A quiet or harmless room changes nothing.
- **Fallback.** `JARVIS_WAKE_MODE` = auto (the default: here when it can
  be), local, or cloud. Without pocketsphinx, set to cloud, or after the
  offline check fails once (the phrase isn't lost — the cloud decides it),
  it listens exactly as before. The existing wake word rules are untouched.
- **The loop.** A phrase kept here isn't a "miss", so the "I haven't made
  out anything in a while" hint doesn't fire just because people talked
  without the name. The command after "Yes?" isn't gated.
- **Saying so.** "Wake word status" reports where the name is checked and
  the counts; the System section's Wake word group shows where and why,
  and the sensitivity; the system check lists pocketsphinx as optional.

pocketsphinx is added to requirements.txt as optional (as pytesseract is).
This session has no microphone or pocketsphinx, so the tests run on a
stand-in recogniser and microphone; checking it on a real room is on the
list for the manual pass.

### Files

| File | Change |
| --- | --- |
| `jarvis/voice/local_wake.py` | new |
| `jarvis/voice/listening.py` | `listen(wake=True)` checks here first; `kept_here`; `calibrate_wake` |
| `jarvis/app/assistant.py` | the loop gates on the name; kept phrases aren't misses; the calibrate command |
| `jarvis/routing/router.py` | "wake word status" |
| `jarvis/app/settings.py`, `jarvis/app/health.py` | where the name is checked, the sensitivity; pocketsphinx as optional |
| `requirements.txt` | pocketsphinx (optional) |
| `tests/test_local_wake.py` | new |

## Chapter 35 — plan and outcome

Where it started: every spoken command needed the name; the model kept the
conversation's history; "stop" and "cancel" stopped the voice and whatever
was running. "Never mind" went to the model as a question, and "continue"
after a stopped plan started a new conversation turn with no plan behind it.

**`jarvis/voice/conversation.py`** and the voice loop:

- **Follow-ups.** After answering something you said, LITTLE listens for
  `JARVIS_FOLLOW_UP` seconds (default 6; 0 turns it off) without needing
  its name — the Home orb shows WAITING. Up to three follow-ups in a row;
  then the name is needed again, so a television can't hold it open. A
  silence closes it. Saying the name in a follow-up is fine. Follow-ups
  aren't checked for the name locally (that's the point), so they are
  transcribed in the cloud; only during this short window.
- **Context.** The model keeps its own conversation. For what's answered on
  this computer, the last thing opened is remembered for two minutes, so
  "close it", "minimise that", "switch to this one" know what "it" is. Only
  a successful local open counts; with nothing recent, "it" is left alone.
  The task still records what you said.
- **STOP / CANCEL** stop the voice and whatever is running, and close the
  follow-up window. **NEVER MIND** (also "forget it", "leave it", "rehne
  do", "chhodo") does the same and answers "Okay." — it never reaches the
  model; inside a longer sentence it's just a sentence.
- **CONTINUE** ("carry on", "go on", "resume the plan", "aage badho"…)
  picks a plan that stopped — a failed step, your stop, or your no — up at
  the step it stopped, for 30 minutes. Earlier steps show as done and
  aren't redone; the stopped step runs again, so anything in it that needs
  your yes asks again. A plan that finishes leaves nothing to continue.
  With nothing to pick up, "continue" goes to the model as before.

Not done: talking over LITTLE while it speaks (barge-in). Speaking blocks
the loop; the Stop button and Esc interrupt it, as before.

### Files

| File | Change |
| --- | --- |
| `jarvis/voice/conversation.py` | new |
| `jarvis/app/assistant.py` | the follow-up window; never mind; continue; "it" resolved; the last thing opened noted |
| `jarvis/ai/planner.py` | a stopped plan kept for `resume()`; `_work` runs from any step |
| `tests/test_conversation.py` | new |

## Chapter 36 — plan and outcome

Where it started: reminders spoke when due; nothing else was volunteered.

**`jarvis/app/proactive.py`** looks every 15 minutes at what LITTLE already
keeps on this computer, and may mention one thing:

| Kind | When |
| --- | --- |
| plan | a plan stopped and can be continued (Chapter 35) — first, it's the most current |
| new_matches | jobs found in the last day at 70% or more that you haven't looked at yet |
| follow_up | an application you recorded (or verified) a week or more ago with no answer recorded |
| verify | an application recorded on your word only, a day or more ago |
| disk | less than 2 GB free |

- **Optional.** On by default, shown in the activity log only.
  `JARVIS_PROACTIVE=off`, or "stop suggestions" / "turn on suggestions"
  (what you say is kept in `proactive.json` and beats .env). One kind can
  be stopped: "stop suggesting follow ups".
- **Rate-limited, non-spammy.** One suggestion per look, at least an hour
  between two, at most four a day, and each thing raised once (a job's
  follow-up is never repeated; what was raised is forgotten after 45 days).
- **Spoken only** with `JARVIS_PROACTIVE_SPEAK=on`, the voice not muted,
  and outside quiet hours (`JARVIS_QUIET_HOURS`, default 22-8, overnight
  ranges understood).
- **Permission-aware.** A suggestion never does anything: it names the
  command to say ("Say: show new jobs"). It reads the job store, the
  stopped plan and the disk — nothing is changed, no tool runs, nothing
  is sent anywhere. A look that fails is skipped, not fatal.
- **Asked for,** "any suggestions?" / "what needs my attention?" lists
  everything current, whatever was raised before, and says if suggestions
  are off.

It starts with the window (`launcher_web.py`) and stops when it closes.
The System section's Voice group shows whether suggestions are on, which
kinds are off, and whether they're spoken.

### Files

| File | Change |
| --- | --- |
| `jarvis/app/proactive.py` | new |
| `jarvis/routing/router.py` | the suggestion commands |
| `jarvis/app/settings.py` | Suggestions and Suggestions spoken rows |
| `launcher_web.py` | starts and stops it with the window |
| `tests/test_proactive.py` | new |
| `tests/conftest.py` | `proactive.json` starts empty for every test |

## Chapter 37 — plan and outcome

Where it started: five tools were listed as asking first
(`NEEDS_CONFIRMATION`), each asked inside itself, and the System section
showed that list, whether keys were set, your answers this session and the
job activity trail. Nothing said how risky the other 80-odd tools were, and
nothing could switch a tool off.

**Levels** (`jarvis/tools/permissions.py`). Every tool has one, and a tool
added without one fails the tests:

| Level | Means | Tools |
| --- | --- | --- |
| SAFE | reads; changes nothing | 33 — listings, reading files and pages, recall, checks |
| LOW_RISK | its own records or the workspace; opens or prepares; shows the model your screen on request | 47 |
| CONFIRM | can do something outside LITTLE that matters; asks when it would | click_text, press_key, browser_task, click_on_screen |
| HIGH_RISK | can't be undone or acts in your name; asks every time | delete_path, run_command, send_whatsapp_message, wa_send_web |
| BLOCKED | never runs | none by default; `JARVIS_BLOCKED_TOOLS=run_command,…` |

`NEEDS_CONFIRMATION` is now derived: CONFIRM and HIGH_RISK — eight tools,
the three added (browser_task, click_on_screen, press_key) being the ones
that already asked at their consequential step, or now do. An unknown tool
counts as HIGH_RISK, never as safe. `BLOCKED_NAMES` (pay, captcha, OTP,
password, bypass, auto-apply…) is ready for outside tools (Chapter 39).

**Enforcement** (`registry.execute_tool`): a blocked tool is refused before
it's called, whatever the model or a page says; arguments that aren't named
values are refused; an extra argument (`confirmed: true`) can't skip a
question — the tool rejects it. **Only a real yes**: whatever dialog is
installed, its answer is recorded and anything but `True` — "no", 1, an
object, a timeout — reaches the tools as False. Before this, a gate written
`if not confirm(...)` would have let a truthy "no" through.

**Bypasses closed in the older browser tools** (found by this chapter's
audit; the Chapter 28 agent already had these rules):

- `click_text` asked only by a button's *words*. A submit button called
  "Go" didn't ask. Now the page is read first: a button that submits a
  form asks ("It submits a form."), and on a job board a submit or apply is
  never pressed.
- `press_key("Enter")` submitted forms without asking. Now Enter on a page
  with a form asks, and on a job board isn't pressed.
- `fill_field` would type into a password field. Now a password, one-time
  code or card field is refused — by its label, or by the field's own type.

**What happened** is recorded in RAM: every answer (tool, action, yes/no —
never the message or command), and every tool run that failed or was
blocked (tool, kind, a short reason with anything secret-looking hidden —
never the arguments).

**The Security Center** is the System section's Security panel, extended:
each asking tool shows "Every time" or "When it matters"; every level with
its count (blocked tools by name); the outside services LITTLE talks to,
what for, and whether it can (Gemini with or without a key; Google speech —
every phrase, or only those with the name when the wake word is checked
here; the Edge voice; Adzuna; job boards and pages, only when asked); and
what failed or was blocked. Keys are still only "set" or "missing". An older
snapshot without this shows none of it. "Security report" says it in words.

Tests changed with the behaviour: the pinned list of five is now the list
of eight; the bridge and dialog replays stay on the original five (named
`FIVE`), and the three new ones are covered in `test_security_center.py`;
the Tools section's "5 ask first" follows the list.

### Files

| File | Change |
| --- | --- |
| `jarvis/tools/permissions.py` | levels, blocked tools and names, only a real yes, events |
| `jarvis/tools/registry.py` | blocked refused; arguments checked; failures recorded |
| `jarvis/tools/browser.py` | submit and Enter read from the page and asked about; job boards; secret fields refused |
| `jarvis/app/security.py` | new — keys, services, levels, answers, events; the report |
| `jarvis/app/bridge.py`, `jarvis/app/settings.py` | the security snapshot; each asking tool's level |
| `jarvis/routing/router.py` | "security report" |
| `ui/index.html`, `ui/js/views/system.js` | levels, services, failed or blocked |
| `tests/test_security_center.py` | new |
| `tests/test_system_security.py`, `tests/test_final_polish.py` | the list of eight |

## Chapter 38 — plan and outcome

Where it started: each tool had a name, a description and a parameter
schema (`TOOL_SCHEMAS`) and a function (`FUNCTIONS`); Chapter 37 added a
level. Nothing said what a tool reaches, how long it may take, or how much
of its arguments may be written down — the activity log showed every
argument, a message's text included.

**`jarvis/tools/catalog.py`** — every tool in full, built from what's
registered so it can't drift (a tool missing anywhere fails the tests):
name, description, parameters and which are required, permission level,
timeout, handler, group, what it uses — my browser, your browser, the
internet, the model, files, the screen, messages, this computer — and its
logging policy.

- **Logging policy.** "args": arguments cut short with anything
  secret-looking hidden (the default); "names": which arguments, never
  their values — messages, contacts, what you asked to be remembered, file
  contents, form values, profile edits, reminders; "none". The task
  record's steps and the activity log both follow it.
- **Timeouts.** By what a tool reaches (30 s local, 60 s the internet, 90 s
  the model or my browser) with a few longer (job search 180 s, a browser
  task 300 s). A SAFE tool — it only reads — runs on a helper thread that
  still reports to its task, and past its timeout LITTLE stops waiting
  ("It only reads, so nothing was changed."). Anything that changes things
  isn't abandoned halfway: a run past its timeout is recorded as slow in
  the Security Center's list instead.
- **Questions, answered on this computer:** "what tools do you have?"
  (count by group, how many ask first), "which tools use the browser?"
  (LITTLE's own browser and your normal one, separately — and the same for
  the internet, the model, files, the screen, messages, this computer),
  "which tools require confirmation?" (every time / when it matters /
  blocked).
- **The Tools section** shows each tool's level in words, what it uses, its
  timeout, and "its words aren't logged" where that's the policy.

### Files

| File | Change |
| --- | --- |
| `jarvis/tools/catalog.py` | new |
| `jarvis/tools/registry.py` | the logging policy in steps; SAFE tools timed out; slow runs recorded |
| `jarvis/app/tasks.py` | `preview` by policy, redacted; `bind` for a helper thread |
| `jarvis/app/assistant.py` | the activity log follows the policy |
| `jarvis/app/bridge.py` | the Tools snapshot from the catalog |
| `jarvis/routing/router.py` | the three questions |
| `ui/js/views/tools.js`, `ui/app.css` | level, uses, timeout, logging |
| `tests/test_tool_registry.py` | new |

## Chapter 39 — plan and outcome

Where it started: nothing. Every tool LITTLE had was its own.

**`jarvis/tools/external.py`** — a small MCP client (JSON-RPC 2.0 over
stdio, newline-delimited: `initialize`, `notifications/initialized`,
`tools/list`, `tools/call`). **Optional:** servers are listed in
`mcp_servers.json` in the memory folder (or the file `JARVIS_MCP_CONFIG`
names); without it there are no outside tools and nothing here runs. They
start with the window and stop when it closes; "reload outside tools"
restarts them; "what outside tools do you have" lists them with levels
and any trouble.

    {"servers": {"notes": {"command": "python", "args": ["notes_server.py"],
                           "level": "CONFIRM", "timeout": 30,
                           "tools": {"search_notes": {"level": "SAFE", "log": "args"}}}}}

What an outside tool can't get round:

- **Permissions.** Each gets a level: CONFIRM unless you lower it, tool by
  tool, in the file; a level the file invents is CONFIRM. A name that
  suggests paying, passwords, credentials, one-time codes, CAPTCHAs, 2FA,
  bypassing or auto-applying is BLOCKED whatever the file says and is never
  offered to the model; `JARVIS_BLOCKED_TOOLS` applies too. They show in
  the Security Center's levels and in the Tools section as "Outside tools",
  marked as asking.
- **Confirmation.** The same dialog — "Use an outside tool", which tool from
  which server, the arguments — before every call at CONFIRM or HIGH_RISK;
  only a real yes runs it.
- **Validation.** Arguments are checked against the tool's own schema —
  required present, types right (a boolean isn't a number), nothing extra
  where the schema forbids it; object and array values sent as JSON text
  are read as JSON — before anything is sent. A reply that isn't a proper
  MCP result is refused.
- **Logging.** By argument name only unless you set `"log": "args"`;
  results cut to 4,000 characters with anything secret-looking hidden;
  non-text content noted, not shown.
- **Safety.** A server's own descriptions are cleaned, cut and marked
  untrusted; results are handed to the model as "data, not instructions".
- **Failures.** A command that doesn't exist, a server that never answers,
  talks nonsense, lists its tools wrongly, hangs on a call (its timeout),
  crashes mid-call or reports an error — each is said in words, recorded in
  the Security Center, and the server is dropped or marked not running.
  Everything else carries on.

### Files

| File | Change |
| --- | --- |
| `jarvis/tools/external.py` | new |
| `jarvis/tools/permissions.py` | `EXTRA_LEVELS` for outside tools |
| `jarvis/tools/catalog.py` | "an outside tool" as something a tool uses |
| `jarvis/app/bridge.py` | the "Outside tools" group; asking by level |
| `jarvis/routing/router.py` | list and reload |
| `launcher_web.py` | load at start, stop at close |
| `tests/test_outside_tools.py`, `tests/mcp_fake_server.py` | new — a real MCP server as a child process, misbehaving on request |

## Chapter 40 — plan and outcome

Where it started: Home showed live system readings, voice and session
facts, tasks, tools run and reminders; the job dashboard (localhost:3000)
showed jobs and applications. Nothing brought memory, security, the tool
registry, the model or the logs together.

**`jarvis/app/overview.py`** — eleven sections, each read at the moment
it's asked for, from the same places the rest of LITTLE reads:

| Section | From |
| --- | --- |
| System | psutil (CPU, memory, disk) and uptime — "psutil isn't installed" when it isn't |
| AI | the model set and in use, whether the key is set, the measured typical answer time, plans run |
| Voice | the microphone and voice as the assistant has them, where the name is checked, follow-ups |
| Memory | facts, preferences, projects, contacts (not the sample one), documents and parts, the conversation log |
| Tools | how many, how many ask first, outside tools, the last run, failures and blocks |
| Tasks | this session's tasks by outcome and by path, the measured local answer time, a plan to continue |
| Browser | LITTLE's browser open or closed and on which site — never started just to look |
| Jobs | stored, found today, the best and average match |
| Applications | prepared, applied on your word, verified submitted, interviews, offers, rejected or withdrawn — kept apart |
| Security | tools that ask every time or when it matters, what's blocked, your answers, keys set (never values) |
| Logs | the log file, its size and the last five lines, cut short with anything secret-looking hidden |

- **No fake metrics.** A number that isn't there says so — "not measured
  yet", "none yet", "unknown" when the microphone's state isn't known;
  nothing is estimated. A section that can't be read shows "Couldn't read
  it" and is marked off; the others carry on.
- **States.** "Needs a look" only for something to act on: a missing key, a
  nearly full disk or memory, failed tasks, failed or blocked tools. "Off"
  for what's simply not running.
- **Where.** "At a glance" at the top of the System section — a card per
  section, laid out to fit down to a narrow window — refreshed with the
  section. The window's navigation is unchanged (nine sections, Alt+1–9).
  It isn't added to the localhost job dashboard on purpose: memory,
  security and logs stay inside the window, off the local network port.
- **In words.** "Everything at a glance" (or "dashboard summary") is
  answered by the assistant itself, which knows its own microphone and
  voice — one line per section, logs left to the screen. ("Status report"
  stays what it was before this chapter: the system health check. For a
  while Chapter 40 had taken it over; that was put back, with a test.)

### Files

| File | Change |
| --- | --- |
| `jarvis/app/overview.py` | new |
| `jarvis/app/bridge.py` | the dashboard in the System snapshot |
| `jarvis/app/assistant.py` | "everything at a glance" |
| `ui/index.html`, `ui/js/views/system.js`, `ui/app.css` | the At a glance panel |
| `tests/test_dashboard_overview.py` | new |

## Chapter 41 — plan and outcome

Where it started: job actions had an audit table (`jobs.store.audit`); the
task record held the current session's tasks in RAM; `jarvis.log` took
whatever a message said. Nothing recorded every tool call, and nothing
stopped a key or a password in an error message reaching the log file.

**`jarvis/app/audit.py`** — one JSON line per event in `audit.jsonl` (memory
folder):

- **task** — when, the intent (what you asked, secrets hidden, cut to 120
  characters), route and path, how it ended, how long, any error.
- **tool** — when, which task (with a session id, since task numbers start
  again each run), the tool, its arguments, what it returned, how long,
  whether it worked, any question it asked with your answer, any error.
  Refused runs (no such tool, blocked, wrong arguments) are recorded too.

**Sanitized, by rule:**

- An argument named like a secret (password, token, PIN, OTP, api_key…) is
  `[hidden]`; every value is redacted for key, token, card and "password
  is …" shapes and cut to 80 characters.
- Arguments a tool's logging policy keeps out (Chapter 38 — messages,
  contacts, what you asked to be remembered, file contents, form values)
  are `[not logged]`; so are their results, which usually echo them.
- What a tool returns about you — your resume, files, pages, chats,
  memory, contacts, documents, outside tools' output — is kept only as a
  length ("[1204 characters, not logged]"). Other results are summarised
  in 160 characters, redacted.
- `config.log` now redacts every message before it reaches `jarvis.log`.
- The file keeps about the last megabyte; past that the older half goes.
  A line that can't be read is skipped.

**Reading it back:** "show me what you did for my last task" (also "what
did you just do") — the intent, how it ended, how long and by which path,
then each tool with its arguments as kept, whether it worked, any question
and your answer, and the result summary. "Show the audit log" lists the
latest tasks.

### Files

| File | Change |
| --- | --- |
| `jarvis/app/audit.py` | new |
| `jarvis/tools/registry.py` | every run, including refused ones, recorded |
| `jarvis/app/tasks.py` | every finished task recorded |
| `jarvis/app/config.py` | the log file redacted |
| `jarvis/routing/router.py` | "what did you do for my last task", "show the audit log" |
| `tests/test_audit_log.py` | new |
| `tests/conftest.py` | the audit file starts empty for every test |

## Chapter 42 — plan and outcome

Where it started: the provider retried a busy model with doubling waits
and fell back to lighter ones (logged only); the browser fell back from
its own Chromium to Chrome or Edge at start; a tool's failure came back as
"Error in …". With no internet, every command waited out the same retries;
a browser closed under a step failed that step.

**`jarvis/app/recovery.py`**, used by the provider, the browser worker and
the registry:

- **The model.** A switch to a lighter model is recorded as a recovery
  (not only logged). With no route to the internet, it stops trying for 20
  seconds, so the next commands answer at once instead of waiting out the
  same retries; the first success clears it. A command that needed the
  model says so and — only when the model is out of reach, not for a
  rejected key — adds a line on what still works on this computer.
- **The browser.** A step that finds the browser closed or crashed
  (Playwright's "has been closed", "disconnected", "Target closed") drops
  it, starts a new one and tries the step once more; the reply begins
  "(My browser had closed, so I reopened it.)" — after the agent's own
  failure mark, which stays first. A fresh browser opens on a blank page,
  so a step can't be repeated on the page it already acted on. Gone twice,
  it's reported and recorded. Any other error isn't retried.
- **Tools.** A SAFE tool (it only reads) gets one more try after a passing
  failure — a timeout, a dropped or refused connection. A real error (a
  bug, a missing file) isn't retried; a tool that changes things never is,
  since a second try could do it twice.
- **Never hidden.** Every recovery, and every failure it couldn't get past,
  is recorded: the Security Center's list (now "recovered" and "slow" as
  well as failed and blocked), the dashboard, and "what went wrong lately".
- **Broken dependencies** answer in a sentence and the rest carries on:
  no Playwright (the setup hint), no pypdf or python-docx (which package to
  install), no psutil (readings unavailable), no SpeechRecognition or
  microphone (voice off, typed commands still work), no edge-tts (the
  Windows voice), no pocketsphinx (the cloud checks the name), no API key
  (local commands still answer).

### Files

| File | Change |
| --- | --- |
| `jarvis/app/recovery.py` | new |
| `jarvis/ai/provider.py` | the offline hold; a model switch recorded |
| `jarvis/tools/browser.py` | a browser gone under a step reopened and the step retried once |
| `jarvis/tools/registry.py` | read-only tools retried once after a passing failure |
| `jarvis/app/assistant.py` | what still works, when the model is out of reach |
| `jarvis/routing/router.py` | "what went wrong lately" |
| `ui/js/views/system.js` | recovered and slow in the Security Center's list |
| `tests/test_failure_recovery.py` | new |
| `tests/conftest.py` | the offline hold and the recorded events start fresh for every test |

## Chapter 43 — plan and outcome

Where it started: every request that reached the model went to one model
(GEMINI_MODEL), with the provider falling back to lighter ones when it was
busy. A plan-step check — a short yes/no from given evidence — cost the
same as planning a project.

**`jarvis/ai/models.py`** — three ways an answer is made, cheapest first:

| Tier | Model | Used for |
| --- | --- | --- |
| local | none | the router's own answers: time, memory, reminders, stored jobs, searching your documents (Chapter 33) |
| fast | `JARVIS_MODEL_FAST`, default gemini-flash-lite-latest | checking a plan step against what the tools returned; summarising a web page |
| strong | `GEMINI_MODEL` | anything with tools, plans or code; answers from your documents; reading a resume; looking at the screen |

- A caller asks for the fast tier with `with models.use("fast"):` around its
  request; everything else is strong. The tier is per thread and restored
  afterwards even if the request fails, so nothing else is quietly moved
  to the cheap model. Call signatures are unchanged.
- **Fallback kept, per tier.** Each tier tries its model as it last worked,
  then the lighter fallbacks; the fast tier's last resort is the strong
  model, so a job never fails only because the cheap model is down. A
  switch is remembered for that tier alone and recorded (Chapter 42).
- **Measured.** Each tier's model calls are timed separately
  (`model_fast`, `model_strong` in the latency record, Chapter 46 reads
  them).
- "Which model do you use for what?" answers the table above with the
  models in use, and says when one is standing in for the configured one.
  The System section and the dashboard show the fast model.

### Files

| File | Change |
| --- | --- |
| `jarvis/ai/models.py` | new |
| `jarvis/ai/provider.py` | the chain by tier; a fast-tier fallback kept apart; each tier timed |
| `jarvis/ai/planner.py`, `jarvis/tools/browser.py` | the step check and page summaries on the fast tier |
| `jarvis/app/latency.py` | the two model stages |
| `jarvis/app/settings.py`, `jarvis/app/overview.py` | the fast model shown |
| `jarvis/routing/router.py` | "which model do you use for what" |
| `tests/test_model_router.py` | new |

## Chapter 44 — plan and outcome

Where it started: the model had file tools (read, edit, write, search) and
`run_command` for tests, with a line in its instructions to read a file
before editing it. Nothing held a code change to a shape, and nothing ran
the tests before a change to tell old failures from new ones.

**`jarvis/ai/coder.py`** — `code_change(request, path)`, a tool the model is
told to use for code changes, and "in the code, <request>" by command:

- **INSPECT.** The project's code files (skipping `node_modules`, `.git`,
  virtual environments and the like), then the ones the request names — by
  file name, path or stem — and those containing its words, most matches
  first, at most six, read up to a budget. How the tests run: `npm test`
  when `package.json` has a real test script; `python -m pytest -q` when
  there are `test_*.py` files or a pytest config; otherwise none.
- **EXPLAIN PLAN.** The strong model (Chapter 43) answers JSON: what it
  understood, the plan, and the changes as exact replacements ("this text"
  becomes "that text"), plus any new files. No reasoning beyond that is
  shown.
- **One question** — "Change your code and run its tests" — with the
  understanding, every change as removed and added lines, and the test
  command. No means nothing is changed and nothing runs.
- **MINIMAL CHANGE, all or nothing.** Before anything is touched, every
  change is checked: inside the workspace; the file exists; the old text
  appears exactly once; no change over 40 lines or rewriting most of a
  file; at most five files; a new file never overwrites one. One bad
  change stops them all. Originals are copied to `memory/code_backups/`;
  edited files get a clearly newer modification time and tests run with no
  bytecode written, so a stale cache can't run the old code.
- **TEST** before and after, with the summary line of each (so "1 failed
  before" isn't blamed on the change). No tests, or a runner that isn't
  installed, is said: the change is untested.
- **REPORT**: INSPECT, PLAN, CHANGE, TEST, then done / tests don't pass /
  untested, and how to undo. "Undo the last code change" asks, then puts
  the originals back and removes files it created.

`code_change` and `undo_code_change` are CONFIRM tools (they ask once each),
so the tools that ask first are now ten; the four tests that pinned eight
(the exact list, "8 of them ask you first", the confirm-when-it-matters list,
the dashboard's count) name the two new ones or follow the list.

### Files

| File | Change |
| --- | --- |
| `jarvis/ai/coder.py` | new |
| `jarvis/tools/registry.py`, `permissions.py`, `catalog.py` | the two tools, their level, what they use |
| `jarvis/ai/prompts.py` | the model is told to use it for code changes |
| `jarvis/routing/router.py` | "in the code, …", "undo the last code change" |
| `tests/test_coding_agent.py` | new — a real project with a real bug and real pytest runs |
| `tests/conftest.py` | no code change carried between tests |

## Chapter 45 — plan and outcome

Where it started: each chapter carried its own tests (1,500 at the start of
this batch, 2,165 by Chapter 44), written case by case. What was thin was
input nobody had thought of: random text, other scripts, control
characters, half-JSON, every tool at once.

**`tests/test_expansion.py`** — random inputs use fixed seeds, so a failure
repeats:

| Area | What's pushed |
| --- | --- |
| Router | Hinglish with the verb after the thing ("chrome kholo", "chrome band karo", "browser band karo", "page padho", "screen par kya hai", "sab thik hai", "dhundo …", "time kya hai"); 70 junk strings answered or passed on, never a crash; open questions go to the model |
| Tools | every registered tool with a nonsense argument answers in words; every parameter type is one the model knows; every timeout and level sane |
| Fallback | the fallback models distinct and well-formed; an answer with no candidates is empty text |
| Browser | each Playwright error in words; addresses tidied |
| Scoring | 25 random jobs: every score 0–100 and the same twice; more of your skills never scores lower |
| Parsers | dates, the resume JSON and plans never crash on junk; fenced JSON read |
| Memory | redacting twice equals once; phone numbers, PIN codes, times and versions left alone; chunking loses no words |
| Permissions | only a real `True` is a yes, for ten kinds of answer; a dialog that raises isn't a yes |
| Dashboard | all eleven sections even when every reader fails |
| Wake word | never crashes, never points outside the text; "little" in a sentence never wakes it; its name first does |
| Config | voice settings keep their shape; wake words always include its own name; tests never touch real folders |
| Recovery | what counts as a passing failure; percentiles ordered |

**Found and fixed on the way:**

- **"So little time" woke it.** "so" is a lead-in ("so hey Little …"), so
  "so little …" read as being addressed. Now "so" right before the bare
  name is the adverb; "so hey little" still wakes it.
- **"Little by little it grew" woke it** and sent "by little it grew" to the
  model. The idiom is recognised.
- **"Page padho" didn't read the page** — only "padho page" did. Hinglish
  puts the verb last; both orders work now.

**The count only goes up.** `tests/TEST_BASELINE` holds the number of test
functions (not counting parametrized cases); `test_expansion.py` fails if
there are fewer. It's raised at the end of each chapter.

### Files

| File | Change |
| --- | --- |
| `tests/test_expansion.py`, `tests/TEST_BASELINE` | new |
| `jarvis/voice/wake.py` | "so little …" and "little by little" aren't addresses |
| `jarvis/routing/router.py` | "page padho" |

---

## Chapter 46 — plan and outcome

Where it started: Chapter 33 timed each command start to reply by path
(fast / normal / ai / agent) and the router's own time; Chapter 43 added
each model tier. Hearing the name, speech to text, a tool run and a browser
step weren't timed, and there was no way to take a measurement on demand
and compare it with the last one. The rule for this chapter: measure
first, and change nothing for speed that the numbers don't ask for.

**Every stage, timed in use** (`jarvis/app/latency.py`, in memory, the last
200 of each):

| Stage | Where it's timed |
| --- | --- |
| Hearing its name | `listening.listen`, only when a check on this computer actually ran |
| Speech to text | `listening.listen`, around the cloud transcription |
| Router | `assistant` (Chapter 33) |
| Each model tier | `provider` (Chapter 43) |
| A tool run | `registry.execute_tool`, every run, in `finally` |
| A browser step | `browser._Worker.run` — a step given up on is timed too; that wait was real |
| Total, by path | `tasks` (Chapter 33): fast / normal / ai / agent |

"How fast are you" reads them. The dashboard shows the typical browser
step and speech-to-text time next to the ones it already had.

**"Benchmark yourself"** (`jarvis/app/benchmark.py`) times what can be timed
here without sending anything or changing anything:

- the router on nine fixed commands, 20 rounds each — "chrome kholo" is
  among them, so opening apps is swapped for a stand-in during the run and
  put back after, even on an error;
- a read-only tool (the clock);
- a search of your documents, only if you've added some (said if not).

"Benchmark the model too" adds one request to each model tier — two real
requests; nothing else in a benchmark reaches the network. A tier that
can't be reached is said, not skipped over.

Each run is appended to `benchmarks.jsonl` in the memory folder, and the
report compares the router with the run before. Numbers measured just now
and numbers measured in use are reported separately, never mixed.

**Measured on the build machine** (Linux container, no model key, so the
model and speech to text couldn't be measured there):

| Stage | Typical | Slowest 1 in 20 |
| --- | --- | --- |
| Router, 180 runs | 0.05 ms | 0.66 ms |
| Document search (3 parts), 20 runs | 0.19 ms | 0.23 ms |
| Read-only tool, 20 runs | under 0.01 ms | under 0.01 ms |
| Importing LITTLE's core | ~150 ms, once | |

What that says: trying locally first costs well under a millisecond, so
there's nothing to gain by optimising the router. The waits you feel are
the network ones — the model and speech to text — and those are timed on
your computer as you use it. No optimisation was made in this chapter
because none was called for by a measurement.

### Files

| File | Change |
| --- | --- |
| `jarvis/app/benchmark.py`, `tests/test_benchmark.py` | new |
| `jarvis/app/latency.py` | stages: hearing its name, speech to text, tool, browser step |
| `jarvis/voice/listening.py` | times the name check and the transcription |
| `jarvis/tools/registry.py` | times every tool run |
| `jarvis/tools/browser.py` | times every step; `STEP_LIMIT` named |
| `jarvis/app/overview.py` | browser step and speech to text on the dashboard |
| `jarvis/routing/router.py` | "benchmark yourself", "run a benchmark", "how fast is everything", "benchmark the model too" |
| `tests/conftest.py` | benchmark runs kept in the test's own folder |
| `jarvis/tools/browser_agent.py`, `tests/test_browser_agent.py` | found by this chapter's regression: a page that timed out could finish loading over the next one ("interrupted by another navigation"). Opening an address only reads, so it's tried once more |
| `tests/TEST_BASELINE` | 1,399 test functions (2,824 tests with parametrized cases) |

---

## Chapter 47 — plan and outcome

Where it started: nothing. Showing LITTLE meant typing commands live,
which depends on the network, the model, what's in your memory and what's
on screen — any of which can go wrong, or show something private.

**`jarvis/app/demo.py`** — "start the demo" (or "run the demo", "demo
mode", "show me a demo", "demo dikhao"; also in Ctrl+K as "Run the demo")
runs a fixed script through the real assistant, on its own thread:

| At | Narration | Command |
| --- | --- | --- |
| 0:00 | Hi, I'm LITTLE… | — |
| 0:07 | Asking the time never leaves this computer. | what's the time |
| 0:13 | Hinglish works too. | time kya hai |
| 0:19 | These tools always ask you first. | which tools require confirmation |
| 0:26 | Now something risky… the answer is no. | run the command: echo hello |
| 0:34 | Every step is kept in an audit log… | what did you do for my last task |
| 0:41 | And everything is timed as it happens. | how fast are you |
| 0:47 | That's LITTLE. Nothing of yours was read, sent, opened or changed. | — |

What makes it reliable and safe to show:

- **Every command is answered on this computer** — no internet, no model,
  no key. Tested: each one routes locally with the model call made to fail.
- **Nothing personal.** No step reads memory, contacts, the resume, jobs,
  files, the screen or a page. Tested with a planted fact and contact that
  must not appear anywhere in what's shown, spoken or replied.
- **Nothing changed.** Nothing opens and nothing is sent; the demo's turns
  stay out of the conversation history (which is yours). The audit log
  records them, as it records everything.
- **The risky step is real, and refused.** It goes through
  `registry.execute_tool` and the real confirmation gate, and the demo
  installs a "no" for just that step — recorded as your answer, shown in
  the audit — then puts back whatever was installed, even on an error. It
  can never answer yes: tested with "yes" installed beforehand and the
  command's `subprocess.run` made to fail the test.
- **Timed by the clock.** Each step has a slot and the next starts when it
  ends, so it takes 53 seconds with the voice on, off, fast or slow
  (tested with a fake clock: slow speech doesn't lengthen it; a step that
  overruns isn't waited for). Only the narration is spoken; the replies
  are on screen. Measured end to end on the build machine: 53.1 s.
- **Stop works.** "Stop", Esc or the Stop button ends it before the next
  step. One demo at a time.

**`DEMO_SCRIPT.md`** is the presenter's copy: before you start, the script
with what the audience sees, three lines to say over it, optional live
steps afterwards, and what to do if something looks wrong. A test checks
that every narration and command in the code is in the script, so the two
can't drift apart.

### Files

| File | Change |
| --- | --- |
| `jarvis/app/demo.py`, `tests/test_demo.py`, `DEMO_SCRIPT.md` | new |
| `jarvis/app/assistant.py` | the demo phrases; stop cancels it; a demo step's reply is shown, not spoken or added to your history |
| `ui/js/views/sections.js` | "Run the demo" in Ctrl+K |
| `tests/test_shell.py` | the new palette command is one the assistant answers |
| `tests/conftest.py` | no demo carries over between tests |
| `tests/TEST_BASELINE` | 1423 test functions (2,854 tests with parametrized cases) |

---

## Chapter 48 — plan and outcome

The audit, check by check, and what each found:

| Check | Tool | Found | Done |
| --- | --- | --- | --- |
| Full test suite | pytest | green at every chapter | re-run at the end, below |
| Lint | ruff (pyflakes rules) | 10 unused imports and 4 empty f-strings in the package; 6 unused imports and 1 unused variable in tests; 15 "redefinitions" that are pytest fixtures imported by name | fixed, except the fixtures (the normal pytest pattern); one re-export kept on purpose |
| Types | mypy | 83 findings: optional values the code already checks, untyped dictionaries | reviewed one by one; no runtime fault; a latent name clash in `catalog.py` (a loop variable and a function both `_names`) renamed |
| Static security | bandit | 5 high, 1 medium, 25 low | 4 real (below), fixed; the rest reviewed: `run_command`'s shell is deliberate and asks every time; the SQL is `?` placeholders; SHA-1 is a dedup key (now marked so) |
| Dependencies | pip-audit | pillow 12.2, urllib3 2.6, idna 3.13 with known vulnerabilities | minimums raised; the suite re-run on the patched versions |
| Secrets | pattern scan of every tracked file and the whole git history | none | a test repeats the scan |
| Configuration | every `getenv` against `.env.example` | 12 settings undocumented | documented, with defaults; the two folder settings commented out, since blank would mean "here" |
| Startup | import all 59 modules; the 18-probe health check | imports and names clean; the probes that failed need a microphone, a speech engine and `.env`, which the build machine hasn't | — |
| Permissions | every tool's level | 90 tools, 10 that ask | unchanged; the new tests hold the fixes |
| Logging | what reaches `jarvis.log` and `audit.jsonl` | redaction in place since Chapter 41 | — |
| Packaging | requirements against actual imports | every third-party import is a requirement (pygame is an optional fallback) | a test keeps it so |

**The security fixes.** Four places let a value the model can choose reach
Windows' command line, and one let a website read the job dashboard:

1. `open_app` — `start "" "<name>"` through the shell, callable without
   asking. A name like `x" & <command> & "` ran the command. Names with
   quotes, `&`, `|`, `<`, `>`, `^` or `%` are refused; real names open
   exactly as before (tested with the command line it builds).
2. `close_app` — `taskkill /im *.exe /f` from the name `*`. Names must now
   start with a letter or digit, and hold only letters, digits, spaces,
   `.`, `+`, `-`; on Linux, `pkill -f` gets the dot escaped.
3. WhatsApp links — a saved number, which the model can add, went into
   `start "" "<link>"`. Links now go to `os.startfile` (Windows' own
   handler, no command line), and one with quotes or line breaks opens
   nothing, so no send can follow the draft.
4. `open_in_vscode` — `code.cmd` runs through the command line on Windows;
   a path with `&` or `%` is refused with a sentence.
5. The job dashboard — answered any `Host`, so a site rebinding its name to
   `127.0.0.1` could read `/api/state`. Only `localhost` and `127.0.0.1`
   are answered now.

None needed a decision from you — each only refuses input that was never
legitimate — so they were fixed and are listed here and in `SECURITY.md`
rather than stopping the batch.

**Documents:** `ARCHITECTURE.md`, `SECURITY.md`, `INSTALLATION.md`,
`API.md`, `CHANGELOG.md` are new; the README points to them. A test keeps
`API.md` listing every call the window can make, and the changelog every
chapter.

### Files

| File | Change |
| --- | --- |
| `jarvis/tools/apps.py`, `system.py`, `whatsapp.py`, `jarvis/jobs/dashboard.py` | the fixes above |
| `jarvis/jobs/store.py` | SHA-1 marked as not for security |
| `jarvis/tools/catalog.py` | loop variable renamed |
| 12 package files, 7 test files | unused imports and empty f-strings |
| `requirements.txt`, `requirements-core.txt` | pillow, urllib3, idna minimums |
| `.env.example` | every setting |
| `tests/test_production_audit.py` | new: the fixes, the tripwires, the documents |
| `ARCHITECTURE.md`, `SECURITY.md`, `INSTALLATION.md`, `API.md`, `CHANGELOG.md` | new |
| `tests/TEST_BASELINE` | 1452 test functions (2,911 tests with parametrized cases) |

---

Run `python -m pytest` before and after every chapter. A chapter that leaves
the suite red is not complete, whatever it added.
