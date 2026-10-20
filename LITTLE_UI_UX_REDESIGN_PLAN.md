# LITTLE — UI/UX redesign plan

**Status: UI-10 done — UI/UX complete.** UI-10 was the final UI phase: the
planned UI-10, UI-11 and UI-12 combined into one, at your request. There
are no further UI phases; nothing else starts until you say.

The goal is "LITTLE — your personal AI operating system": one calm,
futuristic command center that always answers five questions — *where am I,
what can I do, what is LITTLE doing, what happened, what next* — using only
real data.

---

## 0. Fix these first — found during inspection

> **Done, ahead of UI-1** (27 Sep 2026, shipped on its own). The panel no
> longer writes any value as HTML; dashboard links are http/https only; the
> dashboard server sends a Content-Security-Policy; both confirmation
> dialogs open on No, and the panel's Yes arms after 0.7 s.
> `tests/test_ui_safety.py` replays the original attack — with the old code
> put back it fails five tests, with the fix it passes. The panel itself has
> no CSP yet: it loads from `file://` inside WebView2, which can't be tested
> here, so that waits for R2. UI-1 no longer needs to include these.

Two problems in the current panel matter more than anything visual, and
both get worse as the redesign puts more outside text on screen.

### 0.1 Untrusted text can run code inside the assistant window

The panel writes some values into the page as HTML (`innerHTML`). One of
them is reminder text, which the model supplies through `set_reminder` —
a tool that needs no confirmation. The model also reads web pages and
WhatsApp chats, so text planted on a page could steer it into setting a
reminder containing HTML, and that HTML would run inside the panel.

Code running in the panel has the full bridge: it can call `send()` to run
commands, and read a pending confirmation's id from `poll()` and answer it
with `confirm_reply(id, true)`. **That bypasses the confirmation gate** —
the one thing that stops a WhatsApp message being sent or a file deleted
without you saying yes.

**Reproduced, not theoretical.** Rendering the real panel with a stand-in
bridge, a reminder whose text was a single `<img>` tag approved a pending
*"Send this to Rahul?"* confirmation with no click — `confirm_reply(7, true)`
was called by the page itself.

It needs several things to line up, but the redesign would widen it a lot:
job descriptions, page summaries and chat replies are all outside text, and
all of them would appear in this same privileged window.

**Fix (first commit of UI-1):**
- One rule for the whole UI: data is only ever written with `textContent`.
  `innerHTML` is allowed for fixed markup only, never for a value.
- Links are rendered only if they are `http:` or `https:`, so a job board
  can't hand the window a `javascript:` link.
- A test fails the build if any UI file writes a value through `innerHTML`.
- A Content-Security-Policy, if it can be made to hold on the way the window
  loads (see risk R2); verified in the real window, not assumed.

### 0.2 The confirmation dialog defaults to "Yes"

When a confirmation opens, focus goes to **Yes** (confirmed in the same
test run). If you are typing a command and press Enter as the dialog
appears, you have just approved it.
The spec says destructive actions must never be easy to trigger by
accident. **Fix (UI-1):** focus lands on Cancel; Enter never confirms;
Escape still cancels. The full dialog redesign follows in UI-9.

---

## 1. What exists today

### Three front doors

| | Where it runs | Loaded as | Size |
| --- | --- | --- | --- |
| **Assistant panel** | pywebview window (Edge WebView2 on Windows), `launcher_web.py` | `file://…/ui/index.html` | 131 + 263 + 443 lines (HTML, JS, CSS) |
| **Job dashboard** | your normal browser, `http://127.0.0.1:3000/jobs`, `jarvis/jobs/dashboard.py` | local HTTP server | 92 + 323 + 247 lines |
| **Plain window** | Tkinter, `launcher.py` — the fallback when pywebview is missing | Python widgets | 206 lines |

### Framework

None. Plain HTML, CSS and JavaScript, no build step, no npm, no bundler.
This is a strength here: the project installs with one `pip install`, and
the panel is a local file that opens in a millisecond.

### Pages and routes

- **Panel:** one page. Three columns — System / Voice / Session on the left;
  the core, state and activity feed in the middle; Plan / Tools run /
  Reminders / Resources on the right — and a command bar at the bottom.
- **Dashboard:** one page with six tabs switched in JavaScript: Dashboard,
  Jobs, Applications, Analytics, Resume, Activity.
- **Dashboard server routes:** `GET /api/state` (JSON), `GET /`, `/jobs`,
  and static files. **Read-only by design** and bound to `127.0.0.1`.

### How the page talks to Python

**Panel — pywebview bridge** (`Api` class in `launcher_web.py`):

| Method | What it does |
| --- | --- |
| `poll()` | Every 200 ms: current status, new log lines, a system snapshot (refreshed every 0.5 s), and a pending confirmation if there is one |
| `send(text)` | Runs a command on a background thread |
| `toggle()` | Starts or stops listening |
| `control(action)` | `stop` (Esc), `mute`, `browser` (close it) |
| `confirm_reply(id, ok)` | Answers a confirmation |

Status values: `offline`, `calibrating`, `listening`, `waiting`,
`thinking`, `executing`, `speaking`.

Log lines are plain text with prefixes the page parses: `You: `, `LITTLE: `
(and the old `JARVIS: `), `   > tool {…}`, `   heard: …`, and anything else
as a note or warning.

**Dashboard — HTTP:** `GET /api/state` every 4 seconds, returning jobs (up
to 60, each with the nine-dimension score breakdown, concerns, posting age),
applications, audit trail, missing-skill counts, counts, and the resume
profile and preferences.

### State management

Polling snapshots, and a handful of module-level variables per page
(`NAME`, `busySince`, `pendingAsk` in the panel; `data` in the dashboard).
No store, no framework state.

### Authentication

None — it's a local, single-user app, and the dashboard only listens on this
computer. **The redesign adds none**; there is nothing to log into.

### Voice UI

The core orb with Little's face (asleep, blinking, glancing, talking), a
state word and hint under it, a timer while it works, a decorative radar in
the Voice panel, a Mute button, Esc to stop and Ctrl+Space to toggle.

### Assistant / chat UI

The activity feed — one mixed stream of your commands, LITTLE's replies,
tool calls, `heard:` lines and notes, capped at 400 rows. There is no
separate conversation view.

### Job and resume UI

Only in the browser dashboard: job cards with score, skills and concerns;
filters by text, minimum score and status; an application feed; three bar
charts; a resume summary; an audit table.

### Theme

CSS custom properties on `:root` — surfaces (`--void`, `--deep`,
`--panel`), lines, ink, and one colour per state, with `--now` following
the state. **Two separate copies**, one per page, which have already started
to drift. Dark only.

### Responsive

The panel has none: a fixed 272 / flexible / 288 px grid, and the window
won't shrink below 1040 × 660. The dashboard's card grids reflow
(`auto-fill`) but it has no breakpoints.

### Animation

Radar sweep, scan ring while thinking, breathing core, the face's blink /
glance / talk, colour transitions on state. Both pages honour
`prefers-reduced-motion`.

### Design system

None formal. The reusable pieces are helper functions rather than
components: `el()`, `kv()`, `gauge()`, `tile()`, `addRow()`, `jobCard()`,
`drawBars()`, `statusWord()`, `fmtTime()`.

### Tests touching the UI

`tests/test_identity.py` checks the pages' titles, face and wording by
reading the files. Nothing renders the UI in a test yet.

---

## 2. What the spec asks for, and what the backend can honestly supply

The spec's rule is *real data, never fake*. Several requested features have
no data behind them today. Each is either wired to something real, built
as a small honest backend addition, or left out — never faked.

| Asked for | Today | Plan |
| --- | --- | --- |
| Streaming responses | The model call is not streamed; a reply arrives whole | Show real progress while it works (each tool as it runs). No fake typing effect. True streaming is a backend change — **your decision** (D1) |
| Tool execution timeline | Tool calls exist only as log text | Structured events from Python: task started, tool started/finished, reply ready |
| UNDERSTAND → PLAN → TOOL → PROCESS → VERIFY → RESULT | The planner exists for multi-part requests; **no verify step exists** | Show PLAN only when a plan ran, and VERIFY only when something was actually checked (Chapter 32 adds that). Never a step that didn't happen |
| Task center: ACTIVE / WAITING / COMPLETED / FAILED | No record of tasks at all | A small task registry in Python, in memory, last 50. WAITING = waiting for your confirmation — a real state |
| SUCCESS and ERROR orb states | The status has no outcome | Come from the task registry's result, shown for about a second |
| Copy / Retry / Regenerate / Clear | — | All real: copy is the browser, retry resends, regenerate asks again, clear resets the conversation (exists) |
| Speak (re-read a message) | — | New bridge call using the existing voice and brevity |
| Save a message | Nothing to save it to | **Your decision** (D2): into memory, or into a notes file in the workspace |
| Quick actions | Find Jobs, Analyze Resume, Search Web, Open Browser, Check Memory all exist | "Create Task" and "Run Automation" have no backend: Create Task maps to reminders, Run Automation opens the command box for a multi-step instruction (the planner) — labelled as what they are |
| "Run Tool" in the palette | 67 tools, each with arguments | Lists tools and asks LITTLE to use one. A raw form-per-tool runner is deferred |
| Notifications | Reminders, pending confirmations, failed tasks and health warnings are real | Only those. No invented notification feed |
| Projects with tech / status / links / backend / database | The resume gives a name and one line per project | Show what's there; every other field says "not in your resume yet". Nothing invented |
| Memory by category | Preferences, contacts, conversation log, resume profile | Those four, shown for what they are. Contact numbers masked |
| System controls | Settings live in `.env`, read at start | Show every real setting with a way to test it. Editing `.env` from the UI is **your decision** (D3) |
| Voice settings | Voice, speed, pitch, volume, on/off, neural on/off | Exactly those, plus a "test voice" button |
| Mobile | A desktop window; the dashboard listens only on this computer | Proper layouts for narrow windows. Reaching it from a phone needs network exposure and a login — **your decision** (D4), recommended out of scope |
| Authentication | None | None added |

---

## 3. Architecture decisions

**Stay framework-free.** No React, no build step. A framework would add
Node, npm and a build to a project that installs today with `pip`, for a UI
of nine views. Components become small plain-JavaScript functions.

**Classic scripts, not ES modules.** The panel loads from `file://`, where
Chromium refuses module imports. Code is split into files under `ui/js/`
loaded in order, sharing one `window.Little` namespace. The alternative —
pywebview's built-in local server, which makes modules and CSP easy — is
kept in reserve (R2).

**One shell, in the window.** Home, Chat, Tasks, Jobs, Resume, Projects,
Memory, Tools and System all live in the pywebview window, with jobs and
resume data coming over the bridge instead of HTTP.

**The browser dashboard stays read-only.** Any website open in your browser
can send requests to `localhost`. A dashboard that could run commands or
change jobs over HTTP could be driven by any page you visit. So actions
stay in the window, and `localhost:3000` keeps serving a read-only view,
restyled with the same tokens so it looks like LITTLE.

**Hash routing** (`#/jobs`) — works on `file://`, back and forward work,
nothing to configure.

**The bridge moves to `jarvis/app/bridge.py`.** Today it lives in
`launcher_web.py`, which exits if pywebview isn't installed, so none of it
can be tested. Moved, every bridge call gets tests in CI.

**Events alongside lines.** `poll()` keeps returning `lines` exactly as now
(the Tk window and old code keep working) and adds `events` — typed,
structured records the new UI reads instead of parsing text.

**One safe way to build DOM.** An `h(tag, props, children)` helper that only
ever sets text, and a `safeUrl()` for links. Enforced by a test.

---

## 4. LITTLE's visual identity

Not Iron Man. A small, intelligent companion: dark, calm, glassy, with
light used sparingly to mean something.

| | |
| --- | --- |
| **Surfaces** | Near-black blue base; glass panels as a translucent fill + 1px hairline + soft shadow for depth. Three elevation levels, no more |
| **Colour** | One accent per state, kept from today so nothing has to be relearned: listening cyan, thinking violet, working amber, speaking green. Plus success green and a soft coral for errors — not alarm red |
| **Glow budget** | Glow only on the orb and the one thing that changed. Borders are hairlines, never lit |
| **Type** | Segoe UI Variable for text, Bahnschrift for labels and the wordmark, Cascadia Mono for data. Base size up from 11–12px to 14–15px — the current panel is too small to read comfortably |
| **Spacing** | 4px base grid, generous padding, fewer boxes: sections are separated by space before borders |
| **Shape** | 14px radius on panels, 10px on controls, pills for status |
| **Motion** | 120–240ms, ease-out; only for state change, navigation, tool progress, voice and feedback. Everything stops under reduced motion |

### The orb — seven states

Today's face evolves into the orb, and stays the same character.

| State | Feedback |
| --- | --- |
| IDLE | Asleep, eyes closed, still |
| LISTENING | Awake, a gentle slow pulse, blinking |
| THINKING | A slow orbiting arc, eyes glancing |
| EXECUTING | Small ticks around the ring, one per tool step as it actually happens |
| SPEAKING | A subtle waveform under the face |
| SUCCESS | A brief check and a warm flash, about one second |
| ERROR | Coral tint and a small "hmm" expression — clear, not alarming |

The speaking waveform is **state feedback, not a measurement**. Python
doesn't expose the audio level, so it carries no numbers and doesn't
pretend to be a meter. The current radar, which measures nothing, goes.

---

## 5. Information architecture

Sidebar on desktop; bottom navigation on narrow windows.

| Section | Shows | From |
| --- | --- | --- |
| **Home** | Orb and status, "Ask LITTLE anything…", quick actions, current task, recent activity, things waiting for you, active plan | status, events, task registry, reminders, planner |
| **Chat** | Conversation turns with tool steps inside LITTLE's reply; copy, retry, regenerate, speak, save, clear | events, log |
| **Tasks** | Active / Waiting / Completed / Failed, each with a step timeline, tools used, times, and Cancel while active | task registry, planner |
| **Jobs** | Cards with the nine score dimensions made visible, skills matched / close / missing, concerns, posting age, source; search, filter, sort, save, track, open, prepare | `dashboard.state()` over the bridge; existing job tools |
| **Resume** | Profile, skills, education, projects, experience, preferences (editable); analyze, skill gaps, match to a job, improve, interview prep, inconsistencies | resume profile; existing tools; the model for the advice-type actions |
| **Projects** | Each project from the resume, with only the fields that exist | resume profile |
| **Memory** | What LITTLE remembers, by kind, with Forget; contacts masked; a plain privacy note | memory store |
| **Tools** | All tools, which ones need your OK, recent runs with timings | registry, stats |
| **System** | AI provider, voice, microphone, wake word, browser, memory, tools, security, notifications, appearance — and the 18-probe health check | config, health, audit |

**Command palette (Ctrl+K):** jump to any section, ask LITTLE, run a quick
action, find a job by name. Fully keyboard-driven.

**Privacy note, as it will read on the Memory page:** *Everything here is
stored on this computer, in the `memory` folder. LITTLE sends the model the
current conversation, and looks something up from memory only when a
request needs it.* (Verified against `brain.py`: stored memory isn't
attached to every request.)

---

## 6. Components

### Reused (restyled and made safe)

| Today | Becomes |
| --- | --- |
| `el()`, `kv()` | `h()` — the one safe DOM builder |
| The face in the core | `AIOrb` |
| `addRow()` and the feed | `AIMessage` / `ActivityItem` |
| `jobCard()` | `JobCard`, with score dimensions |
| `tile()`, `gauge()`, `drawBars()` | `Stat`, `Meter`, `BarList` |
| The confirmation veil | `ConfirmationDialog` |
| `statusWord()`, `fmtTime()` | shared formatters |
| The token block in each CSS file | one `ui/css/tokens.css` for both pages |

### Created

`Button`, `Card`, `Modal`, `Input`, `Badge`, `Status`, `CommandPalette`,
`TaskCard`, `ResumeCard`, `ToolExecution`, `Sidebar`, `BottomNav`,
`VoiceVisualizer`, `LoadingState`, `EmptyState`, `ErrorState`, a small
router, and `bridge.js` — the one place the UI talks to Python.

### Empty states

Every section has one, written as *what's missing, why it matters, what to
do*. For example: *"No saved jobs yet. Ask LITTLE to find jobs matching
your resume."* Never "No data".

---

## 7. Files

### New

```
ui/css/tokens.css          design tokens, shared by both pages
ui/css/base.css            reset, type, focus, motion rules
ui/css/components.css      every component's styles
ui/js/core/h.js            safe DOM building, safeUrl
ui/js/core/bridge.js       pywebview calls, polling, events
ui/js/core/router.js       hash routes
ui/js/core/tasks.js        the task record, as the page knows it (was store.js)
ui/js/components/*.js      one file per component
ui/js/views/*.js           home, chat, tasks, jobs, resume, projects,
                           memory, tools, system
jarvis/app/bridge.py       the Api class, moved and extended
jarvis/app/tasks.py        the task registry
tests/test_bridge.py       every bridge call
tests/test_ui_safety.py    no innerHTML with data, safe links, ids exist
tests/test_ui_render.py    renders each view with a fake bridge (skipped
                           where no browser is installed)
```

### Changed

```
ui/index.html              becomes the shell
ui/app.js, ui/app.css      split into the files above, then retired
ui/jobs/*                  restyled on the shared tokens, stays read-only
launcher_web.py            imports the bridge; smaller minimum window
jarvis/app/assistant.py    reports task and tool events
jarvis/ai/brain.py         passes tool results to the event, not just names
jarvis/tools/permissions.py  confirmations can carry structured details
jarvis/tools/*.py          the five confirming tools say what they'll do
README.md, LITTLE_IDENTITY.md, this file
```

### Not touched

The job engine, matching, resume parsing, voice, wake word, router, memory
store, health checks, and the Tk launcher's behaviour.

---

## 8. Risks

| # | Risk | Handling |
| --- | --- | --- |
| R1 | Outside text in a window that can run commands (§0.1) | Fixed first; safe-DOM rule enforced by a test |
| R2 | `file://` blocks JS modules and makes CSP unreliable | Classic scripts. If CSP can't hold on `file://`, switch pywebview to its local server — one-line change, tested in the real window before relying on it |
| R3 | Actions over HTTP could be triggered by any website | Dashboard stays read-only; actions only through the bridge |
| R4 | WebView2 differs from the Chromium used in tests | Every phase ends with screenshots from your machine, not only mine |
| R5 | The task registry is new shared state, written from background threads | A lock, a size limit, and tests that hammer it from several threads |
| R6 | Larger polls every 200 ms | Events are deltas; jobs and resume load on demand, not every poll |
| R7 | Twelve phases is a lot of surface; some asks have no backend | §2 decides each honestly up front; nothing faked to fill a screen |
| R8 | Old wording in code and tests | The identity tests already guard "no JARVIS on screen"; extended to the new views |
| R9 | The Tk window falls behind | It stays the plain fallback, and keeps working because `lines` are unchanged |
| R10 | Editing `.env` from the UI touches your API key | Only if you choose it (D3), with a fixed list of editable keys and the key itself never shown |

---

## 9. Implementation order

Each phase: inspect → build only that → tests → regressions → docs → mark
done → **stop**.

| Phase | Scope | Proves it works |
| --- | --- | --- |
| **UI-1** ✅ Design system + identity | (§0 fixes already shipped) `tokens.css`, `base.css`, `components.css`; `h()` and `safeUrl()`; the orb's seven states; restyle the current panel on the new tokens without moving anything | Safety tests; a render of every orb state; all existing tests |
| **UI-2** ✅ Shell + navigation | Bridge moved to `bridge.py` with tests; sidebar, bottom nav, router, command palette; the current panel becomes Home inside the shell | Bridge tests; keyboard-only navigation of every section |
| **UI-3** ✅ Home | Command input, quick actions, current task, recent activity, waiting-for-you; **the task registry lands here**, because Home needs it | Registry tests; Home shows a real command end to end |
| **UI-4** ✅ Chat | Turns, tool steps inside replies, copy / retry / regenerate / speak / save / clear | A command with two tool calls shows both steps, in order |
| **UI-5** ✅ Tasks + tool timeline | Task Center; the honest timeline; cancel | A planned task shows its steps; cancel stops it |
| **UI-6** ✅ Jobs | Jobs in the window with score dimensions and actions; browser dashboard restyled, still read-only | Save, track and prepare use the existing tools and the existing confirmation |
| **UI-7** ✅ Resume | Profile, file picker for scanning, editable preferences, the six actions | A scan from the picker; preferences round-trip |
| **UI-8** ✅ Projects + Memory | Both sections; Forget; masked contacts; privacy note | Forget really removes the entry |
| **UI-9** ✅ System + security | Every real setting; test voice; mic list and recalibrate; health check; audit trail; the new confirmation dialog with Cancel / Review / Confirm | Each of the five confirming tools shows what it will do before you approve |
| **UI-10** ✅ Final: responsive, accessibility, performance, polish | (UI-10, 11 and 12 combined — the last UI phase) Every section at eight window sizes; tablet-width Home; 480 × 560 minimum window; touch targets; dialog focus held and the page behind inert; replies said to a screen reader; contrast measured as drawn; idle redraws cut; the Tools section | Every section renders at 1440 → 390 px; a name on every control; text 4.5:1 as drawn; Tab stays in the dialog; idle page measured before and after |

After every phase, the full suite runs (1388 tests today) and the health
check's import and name probes stay green.

---

## UI-1 — done

**Shipped:** the design system (`ui/css/tokens.css`, `base.css`,
`components.css`), `h()` / `mount()` / `safeUrl()` in `ui/js/core/h.js`,
the orb's seven states, and the current panel restyled on the new tokens —
same layout, same element ids, same behaviour. `DESIGN_SYSTEM.md` is the
contract for the phases after this one.

**Decisions taken:** D1–D4 went with the recommendations (progress steps,
not streaming; save to a notes file; settings read-only; no phone access).

**Removed:** the Voice panel's radar and the dial's tick marks — decoration
that measured nothing, and the most JARVIS-like parts of the old look.

**Found and fixed while building it:**
- A root-level token that mixed in `var(--now)` froze the orb's glow at the
  idle colour — CSS resolves it once, at `:root`. Now tested.
- The idle colour was 2.9:1 against glass, and the word "OFFLINE" is
  written in it. Raised to 5.2:1; every text colour is now checked.
- The larger type squeezed panels below their content on the smallest
  window the app allows (1040 × 660): rows slid under the next panel and the
  Resources buttons under the command bar. Side columns now scroll instead
  of squeezing; tested at three window sizes.
- The render tests fired pywebview's ready event on a 30 ms timer, which
  could beat the page's own script. They now fire it on load, as pywebview
  does, so they test the page rather than a race.

**Not wired yet, on purpose:** the success and error states are drawn and
tested, but nothing triggers them. They wait for UI-3's task record to
report a real outcome, rather than guessing one from a reply's wording.

**Tests:** 464 → 553. The new design-system tests were checked against
planted regressions (a frozen state token, low-contrast text, a raw colour,
a missing element, squeezing panels) and each one failed as it should.

## UI-2 — done

**Shipped:**
- **The bridge moved** to `jarvis/app/bridge.py`, importable and tested
  without pywebview. `launcher_web.py` now only opens the window. On the
  page, `ui/js/core/bridge.js` is the one place that talks to Python.
- **The shell:** a sidebar with the nine sections (full, icon rail, or a
  bottom bar, by window width; collapsing by hand is kept), a top bar with
  the section's title, the palette button, clock and state, and the command
  box on every section.
- **Hash routes** (`#/jobs`): back and forward work, an unknown address lands
  on Home, the window title names the section, and focus moves to the
  section's heading so a screen reader says where you are.
- **Home** is the UI-1 panel, unchanged, inside the shell.
- **The other eight sections** say what's coming and what already works,
  with buttons that send commands Little already answers on this computer —
  no sample data, no mock screens.
- **Command palette (Ctrl+K):** go to a section, press a control (listen,
  mute, stop, close the browser, clear the log, collapse the sidebar), run a
  known command, or ask anything as typed. Arrows, Enter, Escape; focus
  returns where it was.
- **Keys:** Alt+1…9 for sections; a skip link past the navigation.

**Hardened while moving the bridge:**
- A confirmation answer is accepted only for a question that is actually
  waiting, and only a real `True` approves — `"true"`, `1` or a late answer
  after the timeout are a no. Nobody answering for five minutes is a no.
- The page sends `ok === true`, so the page can't send a truthy non-answer
  either.
- A confirmation always wins over the palette: it closes the palette and
  takes focus, the palette won't open over it, and Alt shortcuts wait.

**Found and fixed while building it:**
- The body carried `data-view` for the current section, so the first
  lookup for a section's element matched `<body>` itself and replaced the
  whole page. The body now uses `data-section`, and lookups are scoped to
  `#main`. Caught by the first render.
- A component's `display` rule beat the `hidden` attribute. `[hidden]` now
  always hides.
- Two new tests passed with their regression planted (the Alt-shortcut test
  read the page before the move landed; the focus-trap test pressed Tab then
  Shift+Tab, which round-trips). Both rewritten; all ten planted regressions
  now fail as they should.

**Tests:** 553 → 695. `tests/test_bridge.py` (every bridge call) and
`tests/test_shell.py` (keyboard route to every section, the palette, the
three navigation shapes, overlap at two sizes, and every section button
checked against the real router with its target stubbed).

**Not done, on purpose:** the full narrow-window layout (UI-10 — below
720px Home stacks so nothing overlaps, but it isn't designed yet), and the
app's minimum window size is unchanged.

## UI-3 — done

**Shipped:**
- **The task registry**, `jarvis/app/tasks.py`. Every command is a task
  from the moment it arrives: typed or said, answered on this computer, by
  the model or by a plan; its tool runs are timed steps; a confirmation puts
  it in WAITING until you answer, and your answer is recorded as a step. In
  memory, last 50, one lock, bound to the thread that runs the command — so
  nothing had to pass a task id through the brain or the tools.
- **Outcomes from the code, never the wording.** DONE: ran to the end.
  FAILED: an error was raised (model unreachable, key missing, a crash), the
  planner stopped on a failed step, or it couldn't start (calibrating with no
  mic). STOPPED: you stopped it. A reply that says "I couldn't…" is still
  DONE — tested, on purpose. A step is an error only if the tool raised or
  didn't exist.
- **Only changes travel.** The page tells `poll()` which task version it has
  and gets back only the tasks that changed. A reload asks from 0 and
  catches up. Chosen over an event stream: a changed record can't be missed
  or applied twice.
- **Home:** the orb beside the task in hand — the command, where the answer
  is coming from, its latest three steps with timings, the elapsed time
  from when Python started it — or the last task when idle. Quick actions
  under it. On the right, **Waiting for you** (a missing API key; tasks that
  didn't finish, with Try again and Dismiss) and **Recent** (last five, with
  how each ended). The readings, plan, tools, reminders and controls are
  all still there.
- **Success and error on the orb** are wired: done flashes success, failed
  flashes error, stopped shows neither, and nothing already over when the
  window opened flashes.

**Quick actions, as built:** Find jobs, My resume, What you remember (sent
as is — each checked against the real router), and Look something up…, Set
a reminder…, Several steps… (put in the command box for you to finish). The
last two are the plan's "Create Task" and "Run Automation", named for what
they do. "Open Browser" was left out: there's no command that opens a
browser without a page to open.

**Decided along the way:**
- The "waiting" hook sits in the bridge's `confirm`, not in
  `permissions.confirm`: three tools (the two WhatsApp senders and the
  browser click) call `confirm_fn` directly, and the bridge is the one place
  all five reach.
- Health warnings on Home are limited to what's known for certain at no
  cost — today, a missing Gemini key. Running the health probes on a timer
  would mean network calls for a badge.

**Found and fixed while building it:**
- `replaceChildren(null, …)` writes the word "null" on screen. Caught in the
  first render.
- A container query written before the rule it overrides did nothing — CSS
  order, not specificity. At 1040 × 660 the chips wrapped to four rows and
  squeezed Activity to its title. Now one scrolling row there; tested.
- The render helper read a check that returned `None` as "no browser" and
  skipped — two "shows no flash" tests were silently skipping. It now uses
  an explicit marker, for every render test.
- Removing the registry's lock went unnoticed: the GIL switches threads too
  rarely for eight writers to collide. The hammer now switches every
  microsecond and checks no version is lost or shared — and catches it.
- A voice-only path (`source="voice"`) had no test; it has one now, through
  the real voice loop with a stand-in microphone.

**Tests:** 695 → 784. `tests/test_tasks.py` (the registry, outcomes, threads,
deltas, wiring into the assistant, planner, tools and bridge) and
`tests/test_home.py` (every Home part in a browser, the orb's outcomes,
text-not-markup, fit at three sizes, and two real commands — one done, one
failed — run through the real bridge and replayed into the page). Sixteen
planted regressions, each caught.

**Not done, on purpose:** the full task timeline and Cancel (UI-5), and the
conversation view with tool steps inside replies (UI-4) — the registry
already records what they need.

## UI-4 — done

**Shipped:**
- **Chat**, one turn per command from the task record: what you asked (and
  whether you said it aloud), then Little's reply, with where it came from
  and how long it took. The tools it used sit inside the reply — tool,
  arguments, timing, and any that failed — open while the turn runs, folded
  when it's done.
- **Reply actions:** Copy (clipboard, with a fallback where the clipboard
  API is refused); Speak (read out again as briefly as the voice does;
  off while muted); Save (into `Saved from Little.md` in your workspace —
  D2); Try again (for a turn that failed or was stopped); Ask again (see
  below).
- **New conversation**: the model forgets the conversation, after a second
  click whose default — and Escape — is to keep it. Chat then shows only
  what came after. Typing "new conversation" does the same.
- **The reply is kept on the task** (up to 12,000 characters; longer ones
  say where the rest is), including answers that were only spoken, like
  "Yes?".
- **D1 kept:** no typing effect. The reply arrives whole; the live steps are
  the progress.

**Ask again, made safe.** It takes back the model's last answer and asks
the same question afresh, so the model doesn't see it twice. Offered, and
accepted by Python, only for the model's latest answer that ran no tools —
an answer that deleted a file or sent a message can't be "asked again" into
doing it twice — and not while anything else is running. The brain itself
also refuses unless its history ends with exactly that question and a plain
answer.

**Speak, Save and Ask again send a task id**, not text: Python looks the
words up itself.

**Also fixed:** after speaking with the mic off, the state stayed at
SPEAKING, so the orb read as awake and the next click turned it off rather
than on. It now goes back to offline.

**Found and fixed while building it:**
- Redrawing a turn in the middle of the list threw (it inserted before the
  element it had just replaced), and the task store's listener swallowed the
  error — so the rest of the redraw silently didn't happen, and a scroll test
  passed for the wrong reason. Fixed; and the store, the router and the poll
  now report errors to the console instead of hiding them, which every
  render test treats as a failure. The poll also draws each part separately,
  confirmation first, so one failing panel can't keep a question from
  showing.
- Two tests didn't test what they claimed (a step list "staying open"
  through an update that never redrew it; the brain's tool-call guard, which
  the history's shape already covers). Both rewritten; all nineteen planted
  regressions now fail as they should.
- An interrupted first start of this phase had left backend changes in
  place; they were read, kept where sound, and tested like the rest.

**Tests:** 784 → 865. `tests/test_chat.py`: replies, forgetting, Ask again
and every refusal, Speak and Save by id, the notes file, and in a browser
every kind of turn, each action, New conversation, updates that mustn't get
in the way, text-not-markup, fit — and the phase's own test: a real command
making two tool calls, run through the real assistant, brain loop, registry
and bridge, shows both steps in order inside its reply.

**Not done, on purpose:** Markdown in replies (they're shown as the plain
text they are, which keeps links from navigating the window away), and
per-message delete. Plan steps as their own entries in a turn come with the
task timeline in UI-5.

## UI-5 — done

**Shipped:**
- **The Task Center**: filters (All, Running, Waiting, Done, Didn't finish,
  Stopped) with counts, the list, and the timeline of the task you pick.
  It follows the task in hand until you pick one yourself; then your pick
  stays. Home's Recent rows open a task here; "Show in Chat" goes to its turn.
- **The honest timeline**: how it came in, where the answer came from, the
  plan if there was one (each step with the tools it ran inside it; steps
  that never ran say "not started"), each tool with arguments, timing and any
  error, a question it asked and your answer, a stop you asked for, and how
  it ended — each at the time Python measured. No UNDERSTAND or VERIFY stage
  appears: neither exists yet, so neither is drawn.
- **Plans are on the record**: the planner writes its steps to the task,
  marks each running, done, failed or stopped, and every tool step carries
  the plan step it ran in and when.
- **Stop that stops.** A request honoured between steps: the model is not
  asked again, the next tool in the same answer doesn't run (the model is
  told it didn't), a plan doesn't start its next step. The task ends
  STOPPED, not FAILED; what ran stays in the record. The history is closed
  so the conversation carries on normally afterwards. A task waiting on a
  question has that question answered No.
- **Esc, the Stop button and saying "stop"** now stop whatever is running at
  its next step, as well as the speech — before, they only cut the speech
  and a plan. The "stop" command's own task is never the one stopped.

**What can't be stopped, said plainly.** A command answered on this
computer is one call — a job search across six boards, a page summary — and
can't be interrupted partway without changes inside each tool. The Task
Center says so instead of showing a button that couldn't keep its word. A
tool already running when you press Stop finishes; nothing pretends it was
cut off.

**Found and fixed while building it:**
- A second `class TestStopThis` in the new test file silently replaced the
  first, and eight backend tests never ran — 35 passed instead of 45.
  Renamed; and `tests/test_the_tests.py` now fails the build if any test
  file defines a class or test twice.
- The answer step's pinned shape in a UI-3 test was updated for the new
  fields (the question, the time).

**Tests:** 865 → 931. `tests/test_task_center.py`: plans recorded; stopping
in the model's loop (before the next call, before the next tool in the same
answer, the conversation carrying on after) and in the planner (between and
partway through steps); Esc and saying "stop"; the bridge's refusals; and in
a browser, the timeline for every kind of task, Stop this, filters,
selection, keyboard and focus, text-not-markup and fit. The phase's own
tests run through the real assistant, planner, registry and bridge: a
planned task shows its three steps with their tools, and Stop pressed during
step 1 leaves steps 2 and 3 unstarted. Eighteen planted regressions, each
caught.

**Not done, on purpose:** stopping a single long local command partway (it
would need a stop check inside each tool — job search is the one worth
doing, later); a separate task history kept across restarts (the record is
in memory, last 50).

## UI-6 — done

**Shipped:**
- **Jobs in the window**: a card per stored job, best match first — the
  score and all nine parts with their weights and reasons, skills you have,
  are close on and miss, concerns, posting age (old ones flagged, never
  hidden), source board, salary and work mode where given, and status.
  Search (title, company, location or skill), filters (All, New, Saved,
  Ready, Applied, Closed) with counts, sort (best match, newest posting,
  recently found), and "hide older than a week" — which, like the job search
  itself, keeps postings with no date. Real counts on top, and the skills
  asked for most that the resume doesn't list.
- **Actions, on the existing tools and the existing confirmation**: Save /
  Saved (shortlist_job, mark_job_status), Prepare application… (asks first,
  then prepare_application — opens the posting, fills name, email, phone and
  location, never submits), Update status (mark_applied — asks first, since
  only you can say it — or mark_job_status for interview, offer, rejected,
  withdrawn), and Open posting in your browser (only a web address). Each
  runs as a task, so it shows on Home, in Chat and in the Task Center.
- **Exact references**: the job tools accept `id:<job id>`, and the buttons
  use it. By name, "Acme" means whichever Acme job ranks first; by id, a
  click acts on the card it was on.
- **Loaded on demand**: when you open Jobs and after a task ends, not on
  every poll; descriptions are trimmed to 400 characters for the page.
- **The browser dashboard, restyled**: it now loads the window's
  `tokens.css` and `base.css` (served by the dashboard, those two files by
  name and nothing else), and its own stylesheet follows the design rules —
  no raw colours, nothing under 12px, the decorative grid gone. Still
  read-only: POST, PUT, DELETE and PATCH are refused.

**Found and fixed while building it:**
- A job scoring 29 said "capped at 45" in its explanation. The cap is only
  mentioned now when it actually brought the score down (matching.py), with
  tests for both sides.
- A test of the dashboard's file serving accepted any file that merely
  didn't contain a key. It now requires a 404 for everything but the two
  shared stylesheets.
- The regression runs had a blind spot: Python trusts cached bytecode by the
  source's size and modification second, so two same-size edits within a
  second ran stale code and reported a planted bug as missed. Runs now go
  without bytecode (`python -B`); all fifteen planted regressions fail as
  they should.
- Opening Jobs from another section had no test (every test started on it).
  It has one.

**Tests:** 931 → 1013. `tests/test_jobs_section.py`: the exact reference
(two jobs at one company told apart), the snapshot, every action as a task —
Save and each status through the real tools, "I applied" and Prepare
refused and approved through the real confirmation path, with the browser
never touched on a no — opening postings (only web addresses), and in a
browser the nine parts, skills, concerns, a real cap, each button by id,
filters, search, sort and age, the empty states, loading only when it
should, a Save that shows as saved end to end, text-not-markup and fit; and
the dashboard's shared styles, its refusal of anything else, and its
read-only-ness.

**Not done, on purpose:** applying for you (never — only preparing), a
per-job page, and editing jobs by hand.

## UI-7 — done

**Fixed first, because it was losing your data:** the tests used the
project's own `memory` folder and emptied it before every test. Running
`python -m pytest` on your computer deleted your resume profile, your jobs,
your contacts, your preferences and the conversation log. `config.py` now
reads `JARVIS_MEMORY_DIR` and `JARVIS_LOG_FILE` (unset, nothing changes for
you), `tests/conftest.py` points both at temporary folders before anything
is imported, stops the run before the first test if they aren't, and will
only ever delete inside them. `tests/test_your_data_is_safe.py` checks all
of it; with the setting ignored, the run stops with nothing touched. Test
runs also no longer write their made-up failures into your `jarvis.log`.

**Shipped:**
- **Your profile as saved**: name, degree and year, email, phone and
  location (what Prepare application fills in), then skills, languages,
  frameworks, education, projects, experience, internships and
  certifications. Anything the resume didn't say reads "Not on your
  resume" — nothing is filled in. Where it was read from and when.
- **Scan a resume…** opens the system's own file dialog (pywebview's). Python
  keeps the path and hands the page a number and a file name; the page can
  only scan by that number, once, and only the latest pick — so the window
  can't be made to read any file it names. With a profile already there it
  asks first, opening on Cancel with "Scan it" arming after 0.7 s, like the
  confirmation dialog. The scan is a task: reading the file is a step, and
  a stop between reading and asking the model changes nothing.
- **A new scan keeps the preferences you set.** A scan used to replace them
  with whatever the new resume suggested — which is why you had to type yours
  in again after scanning last night. The profile now records which
  preferences you set (typed or in the form); a scan keeps those and takes
  the rest from the resume, and says which it kept. A profile from before
  this counts every preference with a value as yours.
- **Job preferences, editable**: roles, locations, countries you can work
  in, work modes and job types, saved together and checked the way the
  search reads them — work modes and job types only from the values a
  posting can actually have, duplicates and stray spaces tidied, nothing
  saved if any field is wrong. Each field says whether it's yours or the
  resume's, what happens when it's empty ("Not set: “India”, from your
  address, is used"), and that the search uses the first three roles and
  the first location. Undo puts the form back. Unsaved edits survive a
  reload.
- **The six questions**, each a task, so each shows on Home, in Chat and in
  the Task Center:
  - *Skill gaps* and *Match against the job* use the existing tools
    (`missing_skills`, and `why_this_job` by exact id) on this computer.
  - *Analyze*, *Improve*, *Interview prep* and *Inconsistencies* ask the
    model (`jarvis/jobs/advice.py`) with the resume file's own text — or,
    if the file has gone, the saved profile, which the answer says, with
    email and phone left out. Every prompt ends with rules that come before
    the question: use only what the resume says, never invent a number, an
    employer, a date, a link or a skill, mark what you must fill in with
    [square brackets]. Interview prep can take a stored job; its posting is
    fenced off and read as data, never as instructions. Improve and Analyze
    are told the real skill gaps from the jobs you've found.
  - The answer shows in the section as text, with Copy, Save to notes and
    Open in Chat. It is also added to the conversation as one short
    exchange, so a follow-up in Chat knows what was said — not the whole
    resume. It read your resume first, a step, so Chat doesn't offer
    "Ask again" for it.
  - One resume task at a time, in Python and on the page; the orb shows
    working and thinking while it runs.
- **Jobs' "Scan your resume first"** now opens Resume, where the picker is.

**Found and fixed while building it:**
- Between a click and the next poll, the page didn't yet know the task it
  had just started, and counted nothing as running — so the six buttons
  came back on for a moment. A task Python has started and the page hasn't
  heard of now counts as running.
- Two of the new tests started a resume task and didn't wait for it. Run
  alone they passed; run with the rest, the task outlived the test and its
  stand-in model, and tried to reach the real Gemini. Each test now waits
  for what it started — and a full run makes no network calls.
- On your computer one test failed: the job dashboard, rendered in Chrome or
  Edge, logged a 404. A full browser asks for `/favicon.ico` whatever the
  page says, and the dashboard had none; the trimmed headless browser the
  tests used here never asks, so it passed. The dashboard now serves
  LITTLE's own icon (and says nothing, rather than an error, if the file is
  missing), and its render test runs in the full browser, where it fails
  without the fix.
- Two resume tests failed on your computer and passed here: they looked
  for the resume file by name, found your real `aditya-resume.pdf` in
  Downloads, and read it. The tests no longer search your Downloads,
  Documents or Desktop at all — a test of its own checks that — and the
  resume tests run from the empty test workspace. Checked by running the
  whole suite here with resumes planted in those folders.

**Tests:** 1013 → 1124. `tests/test_resume_section.py` and
`tests/test_your_data_is_safe.py`. Twenty-nine planted regressions — from the
config ignoring the memory setting, through a scan keeping nothing, any
token scanning, the page being handed the path, a stop that doesn't stop,
the rules against inventing removed, an unfenced posting, contact details
sent from the profile, a Match by name instead of id, to the page's own:
buttons free while a task starts, replacing without asking, "Scan it" armed
at once, Escape stopping Little, an answer written as markup, job types not
sent, edits wiped by a reload — each fail as they should.

**Not done, on purpose:** editing the profile itself (name, skills,
projects) — that's Chapter 26, resume intelligence; re-scoring stored jobs
when preferences change — the next job search scores with them, and the
section says so; and scanning a photographed-only PDF, which still fails
with "export the resume as a PDF with real text": the fallback sends a PDF
to the model labelled as an image. Worth fixing in Chapter 26.

## UI-8 — done

**Shipped:**
- **Projects**: a card per project your resume lists — its name and the
  line describing it, the skills from your own resume that the line names
  ("Named in this line"), and any web address written in it, opened in your
  normal browser through Python by its place in the list (the window never
  navigates, and only http or https opens). A resume keeps a project as one
  line, so each card ends "Not in your resume yet: status, AI/ML parts,
  backend, frontend, database" (and links, where there are none) — nothing
  guessed. A short skill must match its own case, so "go live" isn't Go. The
  way to change them is to update the resume and scan it again; the section
  says so and takes you there.
- **Memory**, by kind:
  - *You asked me to remember* — the facts from "remember that …", each
    with Forget.
  - *Your resume and jobs* — a summary, with the sections that show them.
  - *Contacts* — names, with numbers masked by Python to their country code
    and last four digits; the page never gets a number whole. Search, the
    first 60 shown, Remove on each. The made-up entry a fresh memory folder
    starts with is labelled as that.
  - *Conversation log* — the latest 15 turns of the 200 kept, with Clear.
    It says what it is: LITTLE writes it and never reads it back.
- **Forget really forgets.** By exact key or name — never a near match,
  since it deletes — straight from the file, so recall, WhatsApp and the
  file itself no longer have it. It asks first in the row: Keep has focus,
  the delete button arms after 0.7 s, Escape keeps it, one question at a
  time. The log notes that something was forgotten, never what.
- **The privacy note, checked**: "Everything here is kept on this computer,
  in <the memory folder>. None of it goes to the model with every request:
  the model sees a piece only when a request needs it and I look it up." A
  test sends a real question through the brain with facts, contacts and a
  resume stored, and checks none of them is in what the model is sent.
  Forgetting says the one thing it can't undo: if it came up in the
  conversation you're in, the model still has that until a new one.
- **One change at a time** in the memory files: a "remember that" from a
  command and a Forget from the window no longer save over each other.

**Found while building it:** `user_profile.json` (a name and a language) and
the `browser` / `editor` keys in `preferences.json` are defaults nothing
reads, so the section doesn't show them as things LITTLE knows about you.

**Tests:** 1124 → 1194. `tests/test_projects_memory.py`. Eighteen planted
regressions — masking that shows the number, whole numbers sent to the
page, Forget taking any key or a near-match contact, Forget and Clear that
don't save, no lock, the model sent your memory, a short skill matched in
any case, a bare address not made a web link, a link opened by any
position, and on the page: Forget armed at once, Escape stopping Little,
no reload after, two questions open at once, missing links not said, a link
named by its address from the page, the sample contact unlabelled — each
fail as they should.

**Not done, on purpose:** adding or editing memories from the window (a
command does it: "remember that …", "import contacts …"); fields a
one-line project doesn't have; a GitHub lookup for your repositories.

## UI-9 — done

**Shipped:**
- **Questions that say what will happen.** `permissions.Ask` is the
  question as text — the Tk window and the terminal show it exactly as
  before, and every string use still works — carrying its parts: what
  LITTLE wants to do, to what, the details to read, what can't be taken
  back, how serious (danger, caution, safe), the button's word and the
  tool. Each confirming tool now asks with one:
  - `delete_path` — "Delete a file" / "Delete a folder and everything in
    it", the path, its size or how many things are inside; "deleted for
    good, not moved to the Recycle Bin". Danger, **Delete**.
  - `run_command` — the folder, the whole command; "it runs as you, so it
    can change or delete files". Danger, **Run**.
  - `send_whatsapp_message` — to whom, with the saved number masked
    (+91 ••••••5678), the message; "can't be unsent". **Send**.
  - `wa_send_web` — the same, in WhatsApp Web. **Send**.
  - `click_text` — the button's words and, if a page is already open, its
    address — never starting the browser just to ask. **Click**.
  - And the two Jobs buttons: Prepare (safe — nothing is submitted, **Open
    and fill**) and I applied (**Record it**).
- **The dialog: Cancel, Review, Confirm.** "Little wants to" and the
  action, the target, a preview of the details, and what can't be taken
  back in its tone (always in words too). Review opens everything, with the
  tool's name. It still opens on Cancel and Confirm still arms after 0.7 s;
  when the details are longer than the preview, Confirm also waits until
  you've opened Review — you can't approve what you haven't been shown.
  Something safe gets a normal button, not the warning one. Enter or
  Escape as it opens cancels. Long details are cut at 4,000 characters for
  the trip, and marked.
- **System** — every setting in effect, read from what the code uses:
  AI provider (model, the one in use now after any fallback, the
  fallbacks, the key), voice, microphone, wake word, browser, job search,
  files and memory. Each shows its `.env` key; settings are read-only here
  (D3), and the top of the section says where `.env` is and to restart
  after editing — or that there's no `.env` and everything is default.
  **Keys are only ever "set" or "missing"** — never a value or part of one.
  - Test the voice as set (not while muted), the voice report, the
    microphones Windows reports with their numbers, Recalibrate (only
    while listening), Close the browser.
  - The health check, probe by probe — ok, works-but, problem — with what's
    wrong, why and the fix. It runs when you first open System; asking the
    model too is its own button, because it costs a request.
  - Security: what never runs without your yes (the five tools and the two
    Jobs buttons, each in its own words), the fences (the one workspace
    folder, keys never shown, the read-only dashboard), **your answers
    this session** from the task record, and the job activity trail.
  - Notifications and Appearance say what exists — spoken reminders, the
    dialog, Home's Waiting for you; dark only, motion following Windows —
    with no switch for anything that doesn't exist.
- The Tools placeholder now offers a real check ("check the tools"); the
  System placeholder's commands moved to the palette.

**Tests:** 1194 → 1253. `tests/test_system_security.py` — each of the
five tools asked for real and its question read back; each one's question
through the real bridge and rendered in the dialog; secrets planted in the
environment and never found in what the page gets. Twenty-two planted
regressions — a key sent as its value, a setting read from elsewhere, a
tool asking with a bare string, the command missing from its details, a
whole number in the question, the browser started just to ask, the old
question text changed, parts that never reach the page, long details sent
whole, the model tested on any truthy word, the voice speaking while muted;
and on the page: Confirm focused, no Review needed, Review skipping the
moment, details or consequence not shown, everything dressed as danger,
the health check buttons live while it runs, the plain button asking the model, Recalibrate
with the mic off, a reply taken from the wrong task, the fix not shown —
each fail as they should.

**Not done, on purpose:** editing settings from the window (D3 — it would
mean writing `.env`, which holds your key; `.env` and a restart is the way);
choosing a microphone from the list (the same: `JARVIS_MIC` in `.env`); and
the **Tools section itself** — no phase in §9 builds it. It's the one
placeholder left; say if you'd like it in UI-12.

## UI-10 — done (final: responsive, accessibility, performance, polish)

UI-10, UI-11 and UI-12 were combined into this one phase, at your request.
It is the last UI phase. Nothing from UI-1 to UI-9 was rebuilt.

**Measured first.** Every section at eight sizes (1440, 1280, 1040, 900,
768, 600, 480, 390 px); every control's accessible name; Tab through the
confirmation dialog; DOM changes on an idle page; the poll's size and the
cost of the readings in Python; how often each section loads its data.
What that found, and what was done about it:

- **Home between 720 and 1023 px** squeezed LITTLE and the activity into a
  column under 50 px wide. Now LITTLE and the activity take the wide
  column, what needs you sits beside them and the readings go underneath;
  Home scrolls. At phone width the order is LITTLE, then what needs you,
  then the readings. Every other section already fitted at every size.
- **The minimum window** went from 1040 × 660 to 480 × 560, one of the sizes
  checked, so the narrow layouts can actually be reached.
- **Touch screens** get 44 px buttons, chips, nav links, selects and fields.
- **Tab walked out of the confirmation dialog** into the page behind. Now
  the page behind is `inert` while a question is open — no clicks, no Tab,
  not read out — Tab goes round the dialog's own live buttons, and focus
  goes back where it was when you answer (or to the command box).
- **Replies weren't said to a screen reader.** A polite announcer outside
  the page says each task's reply once when it ends — "Didn't finish: …"
  or "Stopped." when that's what happened — cut at 240 characters. Tasks
  that ended before the page opened aren't said.
- **Every control already had a name**, and all text already met 4.5:1 as
  drawn. Both are now tested in every section, so they stay that way.
- **Idle, the page rebuilt about 360 elements a second**, on every section:
  the readings came with every poll and were redrawn whole. Now they're
  drawn only when they change, and only while Home shows them (the newest
  on arrival). Idle is now the clock, about 2 changes a second. The mute
  state still follows in Chat. The poll itself (787 bytes; the readings
  cost 0.11 ms in Python) was left alone — nothing to gain.
- **Tools was the last placeholder.** It's now a section: every tool
  grouped, in the words the model is given, "Asks first" on the five that
  do, search and an ask-first filter, what ran this session from the task
  record (each run opens its task), and "Check the tools". The list comes
  from a new read-only `tools()` on the bridge.
- **Visual pass.** Across the sections the bars, panels, badges and empty
  states already matched; Tools was built from the same pieces. No new
  effects, no new glow.

**Tests:** 1253 → 1388, all passing, none skipped. `tests/test_final_polish.py` — every section at
every size; Home's tablet and phone order; a name on every control; text
contrast as drawn in every section and the dialog; Tab, inert and focus
return in the dialog; replies said; nothing running under reduced motion;
an idle page doing no work, readings not drawn while hidden and drawn on
arrival; the Tools list against the registry and the section's search,
filter, runs (your answers kept out), the check's reply from its own task,
and escaping. `test_shell.py`'s placeholder tests now check
that no section is a placeholder. Twenty-six planted regressions — the tablet rows,
the tablet block, the phone order, a smaller window, readings redrawn every
poll or while hidden or stale on return, mute followed only on Home, the
page behind reachable or still inert after, Tab escaping or stopping on a
disabled Confirm, focus not given back, replies not said or failures said
as successes or said whole, the announcer not polite, small touch targets,
faint text over glass, a tool ungrouped or its ask-first taken from the
wrong list, and on the Tools page the filter ignored, search by name only,
your answers shown as tool runs, a run not opening its task and the check's
reply taken from any task — each fail as they should.

**Not done, on purpose:** a light theme (§11); trimming the poll (measured,
nothing to gain); new voice controls (only real ones exist); phone access
(D4). UI/UX is complete; the next step is yours.

## 10. Decisions I need from you

These change what gets built. Each has a recommendation, so a plain
`START UI-1` means "go with the recommendations".

| | Question | Recommended |
| --- | --- | --- |
| **D1** | Real word-by-word streaming (changes how the model is called), or real progress steps while it works? | **Progress steps now**; streaming as its own later task |
| **D2** | "Save" a message into LITTLE's memory, or into a notes file in your workspace? | **A notes file**, `Saved from Little.md` — easy to open, doesn't clutter memory |
| **D3** | System settings read-only with "how to change", or editable from the UI (writes `.env`)? | **Read-only in UI-9**; editing as a later step |
| **D4** | Reach LITTLE from your phone? Needs network exposure and a login | **No** — narrow-window layouts only |

And one that isn't a redesign question: **the §0 fixes are security fixes.**
They're scheduled as the first commit of UI-1, but they can go out on their
own, today, if you'd rather not wait.

---

## 11. Out of scope

A new framework or build step. A login system. Phone access over the
network (unless D4 says yes). Word streaming (unless D1 says yes). A light
theme. Redesigning the Tk fallback window. Any change to what LITTLE can do
— this is how it looks and how it tells you what it's doing.
