# Architecture

LITTLE is one Python package (`jarvis`, from the assistant's old name), a
window drawn in plain HTML and JavaScript with no build step, and a folder
of your data. Nothing runs as a server except the job dashboard, on
`127.0.0.1` only.

## How a command travels

    microphone ─▶ wake word ─▶ speech to text ─┐
                  (on this computer            │
                   first, if it can)           ▼
    typed in the window ─▶ bridge ─▶ assistant.handle ─▶ task record (Home, Chat, Tasks)
                                          │
                                          ▼
                                  router.fast_route ── answered? ──▶ reply
                                          │ no                (fast / normal path)
                                          ▼
                          planner (several parts) or brain (one question)
                                          │  ai / agent path
                                          ▼
                         model ⇄ registry.execute_tool ─▶ tool
                                          │                 │ may ask you
                                          ▼                 ▼
                                   audit log          permissions.confirm
                                          │
                                          ▼
                     reply on screen; a sentence or two spoken

Each command is one **task**: its text, where it went (route and path),
each tool step with its time, any question it asked you, its reply and how
it ended. Home, Chat and the Task Center read the task record; the audit
log keeps it.

**Four paths, cheapest first** (Chapter 33). *fast*: answered from what
LITTLE holds (the clock, memory, reminders). *normal*: its own tools, no
model (a job search, a page, the knowledge base). *ai*: one conversation
with the model, which may call tools. *agent*: a plan of several steps,
each checked against what the tools returned. The router decides in well
under a millisecond (Chapter 46 measured 0.05 ms typical).

**Two model tiers** (Chapter 43). *fast* for small jobs — checking a plan's
step, summarising a page; *strong* for tools, plans, code, documents, the
resume and the screen. Each tier has its fallbacks; the fast one ends at
the strong model.

## The packages

    launcher_web.py          opens the window (pywebview); launcher.py is a plain fallback
    ui/                      the window and the job dashboard — HTML, CSS, JS, no build step
      js/core/h.js           the one way the page builds anything (no innerHTML)
      js/core/bridge.js      the one place the page talks to Python
      js/views/              Home, Chat, Tasks, Jobs, Resume, Projects, Memory, Tools, System
    jarvis/
      app/                   the assistant and everything around it
        assistant.py         the loop: listen, route, answer, speak
        bridge.py            everything the window may ask (see API.md)
        tasks.py             every command as a task
        config.py            paths, .env settings, the log (redacted)
        health.py            eighteen probes: what's broken, why, the fix
        latency.py           every stage timed in use
        benchmark.py         "benchmark yourself": timed here, kept, compared
        overview.py          Dashboard 2.0: eleven sections from real data
        audit.py             audit.jsonl: every task and tool run, redacted
        recovery.py          retry where it's safe, say so always
        security.py          the Security Center report
        proactive.py         suggestions from local data; never acts
        settings.py          every setting in effect, for the System section
        stats.py             live readings for the panel
        demo.py              the 53-second demo
      voice/
        listening.py         microphone, calibration, speech to text
        local_wake.py        hearing its name offline (pocketsphinx)
        wake.py              finding its name in a transcript
        conversation.py      follow-ups without the name; "close it"; never mind
        speaking.py          the neural voice, the local one as fallback
        brief.py             what's said aloud versus what's shown
      routing/
        router.py            the fast lane, English and Hinglish
      ai/
        provider.py          the only file that knows the model's HTTP shape
        models.py            which tier answers what
        brain.py             conversation history and the tool-calling loop
        planner.py           goal → plan → run → observe → verify → result
        coder.py             the coding agent: smallest change, tests before and after
        prompts.py           what LITTLE is told about itself
      tools/
        registry.py          the 90 tools as the model sees them; execute_tool
        catalog.py           every tool in full: level, timeout, uses, log policy
        permissions.py       levels and the confirmation gate
        workspace.py         the filesystem fence
        external.py          outside tools over MCP
        browser.py           LITTLE's own browser (Playwright, one thread)
        browser_agent.py     observe → act → verify, with gates
        files.py system.py apps.py screen.py reminders.py
        whatsapp.py whatsapp_web.py contacts.py project_check.py
      store/
        memory.py            five tiers: conversation, task, project, long-term, preferences
        knowledge.py         your documents: parse, chunk, index, retrieve, cite
        notes.py             Chat's Save
      jobs/
        resume.py resume_check.py    a resume into a profile; checking it
        sources.py normalise.py      six boards, one shape
        matching.py grades.py        the 0–100 score and its parts
        store.py                     SQLite: jobs, applications, history
        engine.py apply.py advice.py projects.py dashboard.py
    tests/                   2,900+ tests; no network, sound card, display or key needed

## The rules that hold the shape

- **Tools don't know the model exists.** A tool module exposes plain
  functions. `registry.py` names and describes them; `execute_tool` is the
  only way the model reaches one.
- **Two places to audit for harm.** Everything that could do damage goes
  through `permissions.confirm` and `workspace.safe_path`. Every tool has a
  level in `permissions.py`, and a tool without one fails the tests.
- **One door to the model.** `provider.py` alone knows its HTTP shape, so
  swapping providers is one file.
- **Real numbers only.** Every reading shown — CPU, timings, counts, match
  scores — is measured or read from the store at that moment. "Not
  measured yet" where nothing has been.
- **Say it, don't fake it.** A step that failed says so; an application is
  SUBMITTED only with proof from the page; a retry is announced.

## Threads

The window's thread serves the bridge. Each command runs on its own
thread, bound to its task. LITTLE's browser runs on one dedicated thread
(Playwright isn't thread-safe) and every browser step is handed to it.
The voice loop, reminders, proactive checks, the demo and each outside
tool server have their own. Shared state (the task record, latency, answers,
events) is behind locks, and a test drives the task record from eight
threads at once.

## Data

Everything LITTLE keeps is in `memory/` beside the project (or
`JARVIS_MEMORY_DIR`), plus `jarvis.log`. API.md lists each file; SECURITY.md
says what is never written to any of them.

## Where to read more

| | |
| --- | --- |
| `API.md` | the bridge, the dashboard, the registry, MCP, the files |
| `SECURITY.md` | levels, the gate, what's kept, the Chapter 48 audit |
| `INSTALLATION.md` | installing, upgrading, troubleshooting |
| `JARVIS_PHASE2_PLAN.md` | every chapter: what was there, what was built, which files |
| `DESIGN_SYSTEM.md`, `LITTLE_IDENTITY.md` | the window's design, the persona and voice |
