# Installing LITTLE

LITTLE is built for Windows 10 and 11. The core (routing, tools, memory,
planning, the job hunter) also runs on macOS and Linux, and the tests run
on Linux with no sound card, display or API key.

## What you need

| | Needed for |
| --- | --- |
| Python 3.10 or newer (3.12 recommended) | everything |
| A Gemini API key, free at aistudio.google.com | anything the model answers; local commands work without it |
| A microphone | talking to it; typing works without one |
| VS Code with `code` on PATH | "open this in VS Code" |
| Chrome or Edge | the browser tools, if Playwright's own Chromium isn't installed |

## Install

From the folder that holds `launcher_web.py` (for example `D:\little`), in
PowerShell:

    py -3.12 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    python -m playwright install chromium        # optional

Then copy `.env.example` to `.env` and set at least:

    GEMINI_API_KEY=your-key
    JARVIS_WORKSPACE=D:/Projects                 # the only folder LITTLE may touch

Every other setting is in `.env.example` with its default and what it
does. Settings keep the `JARVIS_` prefix from the assistant's old name.

## Start it

    python launcher_web.py

or double-click `start_little.vbs` (no console window). For a desktop
shortcut, run once:

    powershell -ExecutionPolicy Bypass -File make_shortcut.ps1

## Check it works

1. Type **run a system check**. Eighteen probes — Python, `.env`, the
   workspace, every package, the microphone, the browser, the databases,
   DNS, the tool registry — each with what's wrong and the fix.
2. Type **start the demo**. Fifty-three seconds that exercise the router,
   Hinglish, the confirmation gate and the audit log, with no internet or
   key needed. See `DEMO_SCRIPT.md`.
3. Click the orb (or Ctrl+Space) and say "Little, what's the time".

## Optional parts

Each is picked up when it's installed and skipped, with a sentence, when
it isn't.

| Install | Adds |
| --- | --- |
| `python -m playwright install chromium` | LITTLE's own browser (otherwise your Chrome or Edge is used) |
| `pip install -r requirements-optional.txt` | hearing its name on this computer (pocketsphinx), so what's said without it never leaves the room. Ready-made for Python 3.10 to 3.13; newer Python needs Microsoft's C++ Build Tools |
| `pip install edge-tts playsound3` | the neural voice (otherwise Windows' own) |
| Tesseract OCR, plus `pip install pytesseract` | reading a photographed resume without the model |
| An Adzuna key in `.env` | Indian job listings from Adzuna |

## Upgrading

Copy the new files over the old folder (your `.env`, `memory/` and
`browser_profile/` aren't in the update and stay as they are), then:

    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt --upgrade
    pip install -r requirements-optional.txt       # optional; skip it if it fails

Both files tell pip to use ready-made builds, so nothing has to be
compiled on your PC. The optional file is kept apart because one package
that can't install would otherwise stop everything else installing too.

The upgrade matters after Chapter 48: the minimum versions of pillow,
urllib3 and idna were raised past known vulnerabilities (`SECURITY.md`).
Run **run a system check** afterwards.

### Coming from an old JARVIS folder

Bring three things across: `.env` (your key and settings), `memory/` (your
resume, contacts, preferences and jobs) and `browser_profile/` (the
WhatsApp Web login). Everything else is made fresh.

## Running the tests

    pip install -r requirements-dev.txt
    python -m pytest

The suite needs no network, microphone, display or key. The window and
browser tests need Playwright's Chromium and are skipped without it.
`pytest -n 2` runs it in parallel if `pytest-xdist` is installed.

## If something goes wrong

| Symptom | Fix |
| --- | --- |
| "No GEMINI_API_KEY found" | Put the key in `.env`, beside `launcher_web.py`, and restart |
| It doesn't hear you | "list microphones", then set `JARVIS_MIC`; "recalibrate mic" in a quiet moment |
| It hears its name when nobody said it | "calibrate the wake word", or lower `JARVIS_WAKE_SENSITIVITY` |
| The browser tools say they can't start | `python -m playwright install chromium`, or install Chrome |
| "Port 3000 is already in use" | Something else holds it; close it, or ignore the job dashboard |
| pip says "Failed building wheel for pocketsphinx" | Your Python has no ready-made build of it. LITTLE works without it; skip `requirements-optional.txt`, or use Python 3.12 or 3.13 |
| Anything else | `jarvis.log` beside the project says what failed |

## Removing it

Delete the folder. Nothing is installed outside it except what `pip`
put in `.venv` (inside the folder) and Playwright's browser, which
`python -m playwright uninstall` removes.
