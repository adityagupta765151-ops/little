# LITTLE — demo script

A 53 seconds demo that runs itself and comes out the same every time. It
shows the three things that set LITTLE apart: it answers on this computer
first, it asks before anything risky, and it keeps a record of what it did.

It's built to be safe to run in front of anyone:

- **Nothing personal.** No step reads your memory, contacts, resume, jobs,
  files, screen or browser, so none of it can appear on screen.
- **No internet, no model key needed.** Every step is answered on this
  computer, so it works offline and on a fresh install.
- **Nothing changes.** Nothing opens, nothing is sent, and the demo's turns
  stay out of your conversation history. The audit log does record them —
  it records everything that runs.
- **The risky step is refused.** It asks to run a command through the real
  confirmation gate; the demo answers No for you and says so. It can never
  answer Yes, and the command never runs.

## Before you start

1. Start LITTLE (`start_little.vbs`, or `python launcher_web.py`).
2. Turn the voice on if you want the narration heard (the speaker icon, or
   say "unmute"). The demo takes the same time with the voice off.
3. Open **Home** so the tasks appear as they run, or **Chat** to show the
   replies in full.

## Run it

Type **start the demo** in the chat box, or press **Ctrl+K** and pick
**Run the demo**. Saying it works too ("Little, start the demo"). Other
wordings: "run the demo", "demo mode", "show me a demo", "demo dikhao".

Say **stop**, press **Esc** or the Stop button to end it early — it stops
before the next step.

## The script

| At | LITTLE says | LITTLE runs | What the audience sees |
| --- | --- | --- | --- |
| 0:00 | Hi, I'm LITTLE. I try this computer first, and I ask before anything risky. | — | The narration in the activity feed |
| 0:07 | Asking the time never leaves this computer. | `what's the time` | The time, answered on the fast path in milliseconds |
| 0:13 | Hinglish works too. | `time kya hai` | The same answer, from Hinglish |
| 0:19 | These tools always ask you first. | `which tools require confirmation` | The four tools that ask every time, and the six that ask when it matters: a submit, a send, a click from a screenshot |
| 0:26 | Now something risky: running a command. In the demo, the answer is no. | `run the command: echo hello` | The real gate is asked, the answer is no: "You declined, so the command didn't run." |
| 0:34 | Every step is kept in an audit log, including that no. | `what did you do for my last task` | The audit of that task: `run_command(command=echo hello)`, what it asked, "you said no" |
| 0:41 | And everything is timed as it happens. | `how fast are you` | The measured times of the demo's own commands |
| 0:47 | That's LITTLE. Nothing of yours was read, sent, opened or changed. | — | "Demo finished in 53 s." |

Each step has a fixed slot, and the next starts when the slot ends, so the
demo takes 53 seconds whether the voice is on, off, fast or slow. Only the
narration is spoken; the replies are on screen.

## Talking over it

If you're presenting live, three lines land well:

- After the time: "That didn't touch the internet — a command LITTLE knows
  is answered here, in under a millisecond."
- After the refusal: "That was the real confirmation gate. With the demo
  off, you'd see the dialog, and nothing runs until you say yes."
- After the audit: "Every tool run is logged — without passwords, keys,
  messages or your resume."

## After the demo (optional, live)

These go beyond the scripted part and need the internet and a model key.
They aren't timed and they can vary, so try them before presenting:

- "Explain what a REST API is in two lines." — a question for the model.
- "Benchmark yourself." — the router, a tool and document search, timed
  just now.
- Open **System** to show everything at a glance, read from real data.

Avoid commands that show your own data (your resume, jobs, contacts or
memory) if the screen is being shared or recorded.

## If something looks wrong

- **Nothing happens:** check the chat box shows "Starting the demo". If it
  says the demo is already running, say **stop** and start it again.
- **No voice:** the voice is muted, or no speech engine is available. The
  demo still runs on screen, with the same timing.
- **A step fails:** the demo stops and says at which step. Run
  **run a system check** to see what's wrong.
