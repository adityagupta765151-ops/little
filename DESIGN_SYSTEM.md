# LITTLE design system

A small, intelligent companion: dark, calm, glassy, with light used
sparingly to mean something. This page is the contract every screen follows;
`tests/test_design_system.py` enforces most of it.

## Files

| File | Holds |
| --- | --- |
| `ui/css/tokens.css` | Every value — colour, type, space, shape, depth, motion. **The only file allowed to write a colour.** |
| `ui/css/base.css` | Reset, type, focus ring, scrollbars, `.sr-only`, reduced motion |
| `ui/css/components.css` | The pieces: panel, button, badge, meter, key/value, lists, steps, message rows, field, modal, orb |
| `ui/app.css` | The window's layout — shell, Home, the sections — and nothing else |
| `ui/js/core/h.js` | `h()`, `mount()`, `safeUrl()` — the one way to put anything on the page |
| `ui/js/core/bridge.js` | `Little.bridge` — the one place the page talks to Python |
| `ui/js/core/tasks.js` | `Little.tasks` — the task record as the page knows it, merged from each poll's changes |
| `ui/js/core/router.js` | `Little.router` — which section shows, focus, window title, Alt+1…9 |
| `ui/js/components/sidenav.js` | The navigation's three shapes |
| `ui/js/components/palette.js` | The command palette, Ctrl+K |
| `ui/js/views/home.js` | Home: the task in hand, quick actions, waiting for you, recent |
| `ui/js/views/chat.js` | Chat: turns, the steps inside each reply, the reply actions |
| `ui/js/views/taskcenter.js` | Tasks: filters, the list, and the timeline of the task you pick |
| `ui/js/views/jobs.js` | Jobs: search, filters, sort, and a card per job with its score's nine parts |
| `ui/jobs/app.css` | The browser dashboard's layout — on `/css/tokens.css` and `/css/base.css`, served by the dashboard; held to the same rules |
| `ui/js/views/resume.js`, `projects.js`, `memory.js`, `system.js`, `tools.js` | The other sections, one file each |
| `ui/js/views/sections.js` | The palette's commands; the holder for a section without a view (none since UI-10) |

Load order is tokens → base → components → page, then scripts in the order
`h.js`, `bridge.js`, `tasks.js`, `router.js`, the views, the components,
`app.js` (tested). Everything is plain CSS and classic scripts: no build step, and the
panel loads from `file://`, where JavaScript modules don't work.

## The rules

**Values come from tokens.** No hex, `rgb()` or `hsl()` outside
`tokens.css`. Font sizes come from the `--fs-*` scale.

**Nothing on screen is smaller than 12px.** Body text is 14px.

**Text is readable.** Every text colour is at least 4.5:1 on every surface
it can sit on, including the lightest glass and the dialog. The state
colours are text too — the word under the orb is written in them. And the
text as actually drawn — every section, and the dialog — is measured over
what's actually behind it (`test_final_polish.py`), so a translucent
surface or a faded element can't slip under.

**Every control has a name**, from its text, its label or `aria-label` —
checked in every section. One `h1` names where you are; the sidebar is a
`nav`, the top bar a `header`, the sections `main`.

**Only the orb glows.** Borders are hairlines, never lit. Depth comes from
translucency, a hairline and a soft shadow — three levels, no more.

**Motion is 120–240 ms, and only for state, navigation, progress, voice and
feedback.** The orb's slow loops are ambience. Under reduced motion,
nothing moves; colours still change.

**Values are written as text, never as markup.** Build with `h()`. It has no
way to pass HTML, drops `on…` attributes and style strings, and lets a link
through only if it is `http` or `https`. Text in this window comes from the
model, web pages, job boards and chats, and in this window, code that runs
can answer a confirmation by itself.

**Real data only.** No invented metrics, scores or counts. When there's
nothing to show, say what's missing, why it matters, and what to do.

**One door to Python.** Only `bridge.js` touches `window.pywebview.api`
(tested). It sends a confirmation's answer as `ok === true`, and Python
accepts only a real `True` — so a page bug that sends `"true"` or `1` is a
no.

**A confirmation always wins.** The palette closes when one arrives, won't
open over one, and shortcuts wait until it's answered.

**Errors are reported, never swallowed.** A drawing step that fails is
caught so the rest still draws — and logged with `console.error`, which
every render test treats as a failure. A silent `catch` once hid a Chat
bug that a test was passing over.

**The page names things by id.** Chat's Speak, Save and Ask again send a
task id; Python looks up the words itself, so the page can't hand it text
to say or write.

**`hidden` means hidden.** `[hidden]` is `display: none !important`, so a
component's own `display` can't make a hidden thing show.

## Tokens at a glance

| | |
| --- | --- |
| Surfaces | `--bg-0` window, `--bg-1` floor, `--surface-1/2/3` glass (rest, raised, pressed), `--surface-solid` dialogs, `--line` / `--line-strong` hairlines |
| Text | `--ink-1` primary, `--ink-2` secondary, `--ink-3` tertiary, `--ink-on-accent` on filled buttons |
| Brand | `--brand` soft sky |
| States | `--st-idle`, `--st-listening`, `--st-thinking`, `--st-executing`, `--st-speaking`, `--st-success`, `--st-error`; `--now` is always the current one |
| Tones | `--tone-ok`, `--tone-warn`, `--tone-bad`, `--tone-info` for badges and messages |
| Type | `--font-ui` Segoe UI Variable, `--font-display` Bahnschrift, `--font-mono` Cascadia; `--fs-2xs` 12 … `--fs-2xl` 26 |
| Space | `--sp-0` 2 … `--sp-8` 32, on a 4px grid |
| Shape | `--r-md` 10 controls, `--r-lg` 14 panels, `--r-xl` 20 dialogs, `--r-pill` |
| Motion | `--dur-1/2/3` 120/180/240 ms, `--ease` |

**One trap, now tested:** a token on `:root` that mentions `var(--now)`
resolves once at the root and never follows the state. Mix the state colour
where it's used instead.

## State

`<body data-state="…">` is what LITTLE is doing — `offline`,
`calibrating`, `listening`, `waiting`, `thinking`, `executing`,
`speaking` — and sets `--now`. `<body data-flash="success|error">` shows an
outcome over it for `--flash` (1.1 s), via `Little.orb.flash(kind)`. Home
calls it when a task ends done or failed in Python's task record; stopped
shows neither, and tasks already over when the page opened never flash.

## Components

| Class | Use |
| --- | --- |
| `.panel` + `h2` | A glass section with its label; `.count` for a number beside it |
| `.btn`, `--primary`, `--caution`, `--ghost`, `--sm` | Caution is for approving something that can't be undone — never the default |
| `.badge`, `--ok/--warn/--bad/--info`; `.pip` | Status; the pip is a tiny orb in the current colour |
| `.gauges` / `.gauge` / `.bar i` | A real reading as a meter |
| `.kv` | Label / value pairs |
| `.list`, `.steps` | Rows; plan steps with done ✓, now ▸, failed ×; a `.step-ms` makes room for a timing |
| `.tasklist` + `li.is-done/-failed/-stopped/-active/-waiting` | A task per row, its outcome as a glyph and, for a screen reader, in words |
| `.waitlist` + `.wait-title/-detail/-acts`, `li.is-warn/-failed` | Things that need you, each with what to do |
| `.row` `.you/.assistant/.tool/.note/.warn` | Conversation and activity lines |
| `.field` | The command input |
| `.veil` + `.ask` | The confirmation: `.ask-kicker`, the action as its title, `.ask-target`, a preview, `.ask-consequence[data-tone]`, `.ask-review`; Cancel / Review / Confirm. Opens on Cancel; Confirm arms after 0.7 s, and after Review when the details don't fit |
| `.veil--top` + `.palette` | The command palette: a combobox over a grouped listbox |
| `.navlink` | A navigation row; `aria-current="page"` fills it and tints the icon |
| `.search` | The palette's trigger, shaped like a field |
| `.ico`, `.ico--solid` | Line icons on a 24px grid, in the surrounding text colour |
| `kbd` | A key cap |
| `.skip` | "Skip to content", unseen until focused |
| `.turn` + `.msg--you` / `.msg--little` | A command and its reply; `.msg-who`, `.msg-when`, `.msg-reply`, `.msg-fail`, `.msg-working`, `.msg-asking` inside |
| `.steps-toggle` + `.steps.trace` | The steps inside a reply: a disclosure over tool, arguments and timing |
| `.msg-acts` | The actions under a reply |
| `.chip` + `aria-pressed` | A toggle in a row of filters; `.count` beside its label |
| `.tc-item` | A task in the Task Center's list; `aria-current` on the one shown |
| `.timeline` + `.tl.tl--{kind}.is-{state}` | What happened, in order: a time, a mark on a line, what it was. `--inner` nests a plan step's tools |
| `.textfield`, `.select`, `.check` | A text field, a select and a checkbox on the same glass |
| `.job-card` | A job: `.job-head` with `.job-score`, `.dims` (the nine parts), `.skills` (`--have/--near/--gap`), `.job-concerns`, `.job-why`, `.job-foot` |
| `.cv-action` | A question as a card: its name, what it does, and where it runs ("Asks Gemini" / "On this computer") |
| `.cv-result` | An answer shown where it was asked: title, a state that's also a status (`data-status`), the text as text, and its actions |
| `.proj-card` | A project: name, its line, `.proj-named` skills, `.proj-links`, and `.proj-missing` — what the line doesn't say |
| `.mem-row` + `.mem-what` / `.mem-acts` | A kept thing and, at its end, the way to take it back; `.is-asking` while it asks |
| `.orb` | LITTLE — see below |

## Shell

| Shape | When | What |
| --- | --- | --- |
| `full` | 1440px and wider, unless collapsed by hand | Icons and labels, 224px |
| `rail` | 1200–1439px by default, or collapsed; always below 1200px | Icons, 68px; labels become tooltips on hover and keyboard focus, and stay the links' names |
| `bottom` | Under 720px | Home, Chat, Tasks, Jobs and More (opens the palette) |

`sidenav.js` writes the shape to `<body data-nav>`; the stylesheet does the
rest. The current section is `<body data-section>` — not `data-view`, which
belongs to the section elements themselves.

**Sizes.** Every section is checked at 1440, 1280, 1040, 900, 768, 600, 480
and 390 px wide: nothing runs off the side, the command box is always in
view and never under the bottom bar, and the section gets real room. The
window's minimum is 480 × 560 (`launcher_web.py`), one of those sizes.

| Width | Home |
| --- | --- |
| 1024px and up | Three columns: readings, LITTLE and the activity, what needs you |
| 720–1023px | LITTLE and the activity in the wide column, what needs you beside them, the readings underneath; Home scrolls |
| Under 720px | One column: LITTLE, then what needs you, then the readings |

**Touch.** Under `pointer: coarse`, buttons, chips, nav links, selects and
fields are at least 44px tall.

**Moving between sections** puts focus on the section's heading (`#viewTitle`),
so a screen reader says where you landed and Tab carries on into the
section. The window title becomes "Jobs · LITTLE". Typing a command on
another section takes you to Home, where the reply shows, and keeps the
cursor in the command box.

## Home

The hero is the orb beside what it's doing: the task in hand, where the
answer is coming from (on this computer, the model, a plan), and its
latest steps with their timings; when nothing's running, the hint and the
last task. Quick actions sit under it — a command sent as is, or a start
put in the command box for you to finish (a label ending in "…"). On a
narrow centre column the orb shrinks and the chips become one row that
scrolls sideways, so Activity keeps room to read.

Re-rendering a list keeps keyboard focus on the same control (`data-key`).

## Tasks

The timeline shows only what happened, in the order it happened, at the
time Python measured (`+1.2s` after the task started): how it came in,
where the answer came from, the plan if there was one — each step with the
tools it ran inside it, and steps that never started marked "not started"
— every tool with its arguments, timing and any error, a question and your
answer, a stop you asked for, and how it ended. No stage appears that didn't
run.

Marks: ✓ done, ▸ running, × failed, – declined, ? waiting, ■ stopped, an
empty ring for a plan step not started.

"Stop this" appears only where it can keep its word — the model working
through tools, or a plan, or a task waiting on a question (which is then
answered No). Anywhere else the panel says why there's no button.

## Jobs

A card shows everything the score is made of, never a verdict: the nine
parts in the order they weigh, each with its weight and its reason (as a
tooltip and, under "Why this score", as text). Skills say have / close /
missing in words as well as marks. A capped score says it was capped and
why — only when the cap actually brought it down.

Buttons name the job by id. Preparing an application and saying you
applied ask first, through the normal confirmation. The list loads when you
open Jobs and after a task ends — not on every poll.

## Resume

What the resume says, and nothing it didn't: an empty field reads "Not on
your resume", never a placeholder. The two columns scroll on their own —
the profile on the left, the questions and preferences on the right, where
an answer reads at a comfortable line length.

**Replacing something asks inline**, the way the confirmation dialog does:
it opens on Cancel, the go-ahead arms after 0.7 s, and Escape means "don't",
not "stop". Nothing to replace, nothing to ask.

**A form that the page reloads under you** keeps your unsaved edits; only
its hints move. Save and Undo are off until something changed.

**Marks sit in their own list** under the contact details (`#cvScores`):
CGPA / %, Class 12, Class 10, as the resume writes them. **A value you
corrected by command** carries a `badge--info` "corrected by you" until a new
scan replaces it; the rescan question names those corrections. The section
never edits the profile itself — corrections are commands (Chapter 26) — and
links are shown as text, never as something to click.

**Where something runs is said on the button**, not discovered afterwards.
A question the model answers says so before you press it.

One resume task at a time: from the click until it ends — including the
moment before the page has heard of the task it just started.

## Projects and Memory

A project card shows what the resume's line says and names what it doesn't
("Not in your resume yet: …") — the honest version of an empty field when
the field would otherwise be most of the card.

Deleting a memory asks in its own row (`.mem-acts.is-asking`): the question,
Keep with focus, and the caution button arming after 0.7 s. One question
open at a time; Escape keeps it. The row is where you were looking, so the
question appears there rather than in a dialog.

Anything sensitive is shaped before it reaches the page — a contact's
number arrives masked — so the page can't show more than it should.

## System and confirmations

A setting is a row: what it is, its value as in effect, its `.env` key in
mono under it, and a note only where the value needs one. Secrets are a
value of their own — "set" or "missing" — never a masked string.

A question for you names the action first ("Little wants to — Send a
WhatsApp message"), then what it acts on, then what you should read, then
what can't be taken back, coloured by tone and always in words. The button
says the verb — Send, Delete, Run — not "Yes". Safe actions don't wear the
warning colour.

**While it's open, the page behind is `inert`** — no clicks, no Tab, not
read out — and Tab and Shift+Tab go round the dialog's own buttons that
can be pressed. Answering gives focus back to what had it, if it's still
there, or the command box. The announcer (`#announcer`, polite) sits
outside `.shell`, so a reply is still said while a dialog is up.

## Tools

The list is Python's own: every tool's name, the description the model is
given, its group (by the module it lives in) and whether it asks first.
Search covers all three. What ran this session is the task record's steps
— the same record the Task Center shows — never a separate tally, and each
run opens its task.

## Staying light

Measured before changing anything: idle, the page rebuilt about 360
elements a second on every section, because the readings came with every
poll and were redrawn whole. Now a poll's readings are drawn only when they
differ from what's drawn, and only while Home shows them — the newest are
drawn the moment you go back. The mute state still follows everywhere. The
clock writes only when the second changes. Each section loads its data
when you open it, once, not per poll.

## Chat

One turn per command, from the task record. A turn is redrawn only when
its task changes (or something its buttons depend on does), so an open
step list, the scroll position and keyboard focus survive updates. A new
turn scrolls into view; an update to one doesn't pull you down while you
read back. Steps are open while a turn runs, folded when it's done, and
your choice sticks. No typing effect: the reply arrives whole, and the live
steps are the progress.

**Ask again** only for the model's latest plain answer — never one that ran
a tool, and not while something else runs. **New conversation** takes a
second click, and the second one's default (and Escape) is to keep it.

**Keys:** Ctrl+K palette · Alt+1…9 sections · Ctrl+Space listen · Esc stop,
or close the dialog or palette that's open.

When a task ends, its reply (or "Didn't finish: …", or "Stopped.") is said
once through the announcer, cut at 240 characters. Tasks already over when
the page opened aren't said.

## The orb

| State | Sign |
| --- | --- |
| Idle | eyes closed, still, dim |
| Listening | slow breath of light, blink |
| Thinking | an arc orbiting the ring, eyes glancing |
| Executing | a dotted activity ring, eyes down |
| Speaking | a small waveform where the smile was — state, not a level meter |
| Success | happy eyes, the ring draws closed |
| Error | squint and a wobbly "hmm", soft coral, no shaking |

Each state shows its own sign and no other, and each has its own colour —
both checked by rendering the orb in every state.
