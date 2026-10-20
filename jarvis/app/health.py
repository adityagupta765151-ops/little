"""Does JARVIS actually work right now, and if not, what fixes it.

A check that reports FAILED without naming the fix is a worse version of the
traceback it replaced, so every failure here carries three things: what is
wrong, why, and what to do about it.

Three states rather than two. `warn` means it runs but degraded — no Adzuna
key, no neural voice — which is very different from broken, and lumping the
two together trains people to ignore the report.

No probe may raise, and none may be slow. The browser check does not launch
a browser; the microphone check does not open a stream; the live model call
happens only when explicitly asked for.
"""
from __future__ import annotations

import importlib
import os
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config

OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "ok", WARN: "warn", FAIL: "FAIL"}

MIN_PYTHON = (3, 10)
MIN_FREE_GB = 0.5

# What each import is for, so a missing one can be explained rather than
# just named. Optional packages warn; the rest fail.
PACKAGES = {
    "requests":  ("talking to the model and the job boards", True),
    "dotenv":    ("reading your .env file", True),
    "psutil":    ("the system readings on the panel", False),
    "pypdf":     ("PDF and resume reading", False),
    "docx":      ("Word document reading", False),
    "playwright": ("browsing and page reading", False),
    "pyttsx3":   ("the offline fallback voice", False),
    "edge_tts":  ("the neural voice", False),
    "speech_recognition": ("the speech-to-text step", False),
    "pyaudio":   ("microphone input", False),
    "webview":   ("the panel window", False),
    "pytesseract": ("text reading from a photographed resume", False),
    "pocketsphinx": ("hearing its name on this computer, before anything goes to the cloud", False),
}

INSTALL = {
    "dotenv": "python-dotenv", "docx": "python-docx",
    "speech_recognition": "SpeechRecognition", "webview": "pywebview",
    "edge_tts": "edge-tts", "pyaudio": "PyAudio",
}


@dataclass
class Check:
    """One probe's answer. problem/cause/fix are only filled in on trouble."""
    group: str
    state: str = OK
    detail: str = ""
    problem: str = ""
    cause: str = ""
    fix: str = ""

    def failed(self, problem: str, cause: str, fix: str) -> "Check":
        self.state, self.problem, self.cause, self.fix = FAIL, problem, cause, fix
        return self

    def warned(self, problem: str, cause: str, fix: str) -> "Check":
        self.state, self.problem, self.cause, self.fix = WARN, problem, cause, fix
        return self


def _importable(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:  # noqa: BLE001  (a broken install is as absent as a missing one)
        return False


# ---------------------------------------------------------------- probes

def check_runtime() -> Check:
    c = Check("runtime", detail=f"Python {sys.version_info.major}.{sys.version_info.minor}"
                                f".{sys.version_info.micro}")
    if sys.version_info < MIN_PYTHON:
        return c.failed(
            f"Python {sys.version_info.major}.{sys.version_info.minor} is too old",
            f"{config.ASSISTANT_CALL} needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer",
            "Install Python 3.12 and rebuild the virtual environment")
    if sys.version_info >= (3, 14):
        c.warned("Python 3.14 or newer",
                 "PyAudio and some other wheels are not published for it yet",
                 "If installs fail, make the venv with py -3.12 instead")
    return c


def check_project() -> Check:
    """The refactor that moved config.py once pointed this at the package
    instead of the project, and .env was silently never read."""
    root = config.BASE_DIR
    c = Check("project", detail=str(root))
    if config.FROZEN:
        return c                    # the installed app keeps its data in your profile
    if root.name == "jarvis":
        return c.failed(
            "The project root resolves to the package folder",
            "config.py is counting directories instead of finding the root",
            "Check _project_root() in jarvis/app/config.py")
    if not (root / "requirements.txt").exists():
        return c.warned(
            f"No requirements.txt in {root}",
            f"{config.ASSISTANT_CALL} may be reading .env and memory/ from the wrong folder",
            "Run it from the folder that holds launcher_web.py")
    return c


def check_config() -> Check:
    env = config.BASE_DIR / ".env"
    c = Check("config", detail=f"model {config.MODEL}")
    if not env.exists():
        return c.failed(
            "No .env file",
            f"Nothing at {env}",
            "Copy .env.example to .env and put your API key in it")
    if not config.API_KEY:
        return c.failed(
            "No API key",
            "GEMINI_API_KEY is missing or blank in .env",
            "Get one free at aistudio.google.com and add it, then restart")
    return c


def check_workspace() -> Check:
    folder = config.WORKSPACE
    c = Check("workspace", detail=str(folder))
    if not folder.exists():
        return c.failed("The workspace folder doesn't exist", str(folder),
                        "Set JARVIS_WORKSPACE in .env to a folder that does")
    probe = folder / ".jarvis-write-test"
    try:
        probe.write_text("x")
        probe.unlink()
    except OSError as e:
        return c.failed("The workspace isn't writable", str(e),
                        "Pick a folder you own, under your user directory")
    return c


def check_packages() -> Check:
    missing_required, missing_optional = [], []
    for name, (purpose, required) in PACKAGES.items():
        if not _importable(name):
            (missing_required if required else missing_optional).append(
                (INSTALL.get(name, name), purpose))

    c = Check("packages",
              detail=f"{len(PACKAGES) - len(missing_required) - len(missing_optional)}"
                     f" of {len(PACKAGES)} installed")
    if missing_required:
        names = ", ".join(n for n, _ in missing_required)
        return c.failed(
            f"Missing: {names}",
            "; ".join(f"{n} is needed for {p}" for n, p in missing_required),
            f"python -m pip install --prefer-binary {' '.join(n for n, _ in missing_required)}")
    if missing_optional:
        names = ", ".join(n for n, _ in missing_optional)
        c.warned(f"Not installed: {names}",
                 "; ".join(f"{n} provides {p}" for n, p in missing_optional),
                 f"python -m pip install --prefer-binary {' '.join(n for n, _ in missing_optional)}")
    return c


def check_voice_out() -> Check:
    neural, local = _importable("edge_tts"), _importable("pyttsx3")
    c = Check("tts", detail=(f"neural ({config.VOICE}, {config.VOICE_PITCH})"
                             if neural else "local voice only")
                     + ("" if config.VOICE_ENABLED else ", starts muted"))
    if not neural and not local:
        return c.failed("No speech engine at all", "Neither edge-tts nor pyttsx3 is installed",
                        "python -m pip install edge-tts playsound3")
    if not neural:
        c.warned("Only the local Windows voice",
                 "edge-tts isn't installed, so the natural voices aren't available",
                 "python -m pip install edge-tts playsound3")
    elif not _importable("playsound3") and not _importable("pygame"):
        c.warned("Neural voice installed but nothing can play it",
                 "edge-tts writes an mp3; no player package is present",
                 "python -m pip install playsound3")
    elif config.VOICE == config.OLD_VOICE and config.ASSISTANT_NAME != "JARVIS":
        # The .env.example that came with JARVIS set this voice, so an .env
        # copied from it keeps speaking in the old voice after the rename.
        c.warned(f"Still the old JARVIS voice, not {config.ASSISTANT_CALL}'s",
                 f".env sets JARVIS_VOICE={config.OLD_VOICE}",
                 f"Change it to {config.DEFAULT_VOICE} (and JARVIS_VOICE_PITCH to "
                 f"{config.DEFAULT_PITCH}), or ignore this if you prefer that voice")
    return c


def check_voice_in() -> Check:
    """Counts input devices without opening a stream, so it can't collide
    with a listener that is already running."""
    c = Check("mic")
    if not _importable("speech_recognition"):
        return c.failed("Can't hear anything", "SpeechRecognition isn't installed",
                        "python -m pip install SpeechRecognition PyAudio")
    if not _importable("pyaudio"):
        return c.failed("No microphone access", "PyAudio isn't installed",
                        "python -m pip install PyAudio, or pipwin install pyaudio on Windows")
    try:
        import speech_recognition as sr
        names = sr.Microphone.list_microphone_names()
    except Exception as e:  # noqa: BLE001
        return c.failed("Couldn't list microphones", str(e)[:90],
                        "Check Windows sound settings for an enabled input device")
    if not names:
        return c.failed("No microphone found", "Windows reports no input devices",
                        "Plug one in, or enable it in Windows sound settings")
    chosen = os.getenv("JARVIS_MIC", "").strip()
    c.detail = f"{len(names)} device(s)" + (f", using #{chosen}" if chosen else ", system default")
    if chosen.isdigit() and int(chosen) >= len(names):
        c.warned(f"JARVIS_MIC is set to {chosen}, which doesn't exist",
                 f"Only {len(names)} devices are present",
                 "Say list microphones and pick a number from that list")
    return c


def _find_browser(command: str, *places: str) -> bool:
    """On Windows neither Chrome nor Edge is on PATH, and Playwright finds
    them through the registry rather than PATH anyway — so looking only at
    PATH reports "no browser" on a machine that has two."""
    if shutil.which(command):
        return True
    return any(Path(os.path.expandvars(p)).exists() for p in places)


def _bundled_chromium() -> bool:
    """Asks Playwright where its own Chromium would be, without starting it."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            return bool(pw.chromium.executable_path
                        and Path(pw.chromium.executable_path).exists())
    except Exception:  # noqa: BLE001
        return False


def check_browser() -> Check:
    """Looks for an executable. Launching a browser to prove a browser
    launches would make the whole check take ten seconds."""
    c = Check("browser")
    if not _importable("playwright"):
        return c.failed("No browser automation", "Playwright isn't installed",
                        "python -m pip install playwright")

    chrome = _find_browser(
        "chrome",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ) or bool(shutil.which("google-chrome") or shutil.which("chromium"))

    edge = _find_browser(
        "msedge",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    )

    installed = [name for name, found in (("Chrome", chrome), ("Edge", edge)) if found]

    if _bundled_chromium():
        c.detail = "Playwright's Chromium" + (f", plus {', '.join(installed)}" if installed else "")
    elif installed:
        c.detail = ", ".join(installed) + " (Playwright's own Chromium not downloaded)"
        c.warned("Using the installed browser",
                 "playwright install chromium hasn't been run",
                 "Fine as is. For the bundled one: python -m playwright install chromium")
    else:
        return c.failed("No browser to drive",
                        "Neither Playwright's Chromium nor an installed Chrome or Edge",
                        "Install Google Chrome, or run python -m playwright install chromium")
    return c


def check_database() -> Check:
    from ..jobs import store as jobs_store
    c = Check("database")
    try:
        conn = jobs_store.connect()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        conn.close()
    except Exception as e:  # noqa: BLE001
        return c.failed("The job database won't open", str(e)[:90],
                        f"Delete {jobs_store.DB_PATH} and let it rebuild")
    missing = {"jobs", "applications", "audit"} - tables
    if missing:
        return c.failed(f"Missing tables: {', '.join(sorted(missing))}",
                        "The schema didn't apply",
                        f"Delete {jobs_store.DB_PATH} and let it rebuild")
    c.detail = f"{jobs} job(s) stored"
    return c


def check_memory() -> Check:
    import json

    from ..store import memory as store
    c = Check("memory", detail=str(config.MEMORY_DIR))
    if not config.MEMORY_DIR.exists():
        return c.failed("The memory folder is missing", str(config.MEMORY_DIR),
                        "It is created on start; check the folder is writable")
    broken = []
    for path in (store.PROFILE, store.PREFERENCES, store.CONTACTS, store.HISTORY):
        if not path.exists():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            broken.append(path.name)
    if broken:
        return c.failed(f"Unreadable: {', '.join(broken)}",
                        "The file isn't valid JSON",
                        f"Delete those files in {config.MEMORY_DIR}; they rebuild empty")
    c.detail = f"{len(store.contacts())} contact(s)"
    return c


def check_disk() -> Check:
    c = Check("disk")
    try:
        usage = shutil.disk_usage(config.WORKSPACE)
    except Exception as e:  # noqa: BLE001
        return c.warned("Couldn't read free space", str(e)[:70], "Usually harmless")
    free = usage.free / 1e9
    c.detail = f"{free:.1f} GB free"
    if free < MIN_FREE_GB:
        return c.failed(f"Only {free:.1f} GB free",
                        "Downloads, browser profiles and screenshots all need room",
                        "Clear some space on that drive")
    return c


def check_network() -> Check:
    """Resolves a name rather than opening a connection, so it is fast and
    can't hang on a captive portal."""
    c = Check("network")
    try:
        socket.setdefaulttimeout(3)
        socket.getaddrinfo("generativelanguage.googleapis.com", 443)
    except Exception as e:  # noqa: BLE001
        return c.failed("No internet", f"DNS lookup failed: {type(e).__name__}",
                        "Without it: no model, no speech recognition, no job search")
    finally:
        socket.setdefaulttimeout(None)
    c.detail = "reachable"
    return c


def check_registry() -> Check:
    from ..tools import registry
    from ..tools.permissions import NEEDS_CONFIRMATION
    c = Check("tools")
    described = {t["name"] for t in registry.TOOL_SCHEMAS}
    implemented = set(registry.FUNCTIONS)
    if described != implemented:
        drift = described ^ implemented
        return c.failed(f"{len(drift)} tool(s) out of step",
                        f"Described but not implemented, or the reverse: {', '.join(sorted(drift))}",
                        "Every tool needs an entry in both FUNCTIONS and TOOL_SCHEMAS")
    unknown = NEEDS_CONFIRMATION - implemented
    if unknown:
        return c.failed("The confirmation list names tools that don't exist",
                        ", ".join(sorted(unknown)),
                        "Fix NEEDS_CONFIRMATION in jarvis/tools/permissions.py")
    c.detail = f"{len(implemented)} tools, {len(NEEDS_CONFIRMATION)} gated"
    return c


def check_imports() -> Check:
    """Imports written inside a function don't run until someone says the one
    command that needs them, so a refactor can move a module and nothing
    notices for a week. This reads them all without running any of them.

    Only relative imports are checked. A missing third-party package is the
    packages probe's job; this one is about the project's own wiring.
    """
    import ast
    import importlib.util

    package = Path(__file__).resolve().parent.parent
    broken, scanned = [], 0

    for path in sorted(package.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as e:
            broken.append(f"{path.name} won't parse ({type(e).__name__})")
            continue

        # A relative import is anchored to the folder the file sits in, so
        # both jarvis/tools/browser.py and jarvis/tools/__init__.py anchor
        # at jarvis.tools.
        parts = path.relative_to(package.parent).with_suffix("").parts
        here = ".".join(parts[:-1])

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            scanned += 1
            target = "." * node.level + (node.module or "")
            try:
                resolved = importlib.util.resolve_name(target, here)
                found = importlib.util.find_spec(resolved) is not None
            except Exception:  # noqa: BLE001  (a parent that doesn't exist lands here)
                resolved, found = target, False
            if not found:
                broken.append(f"{path.name}:{node.lineno} imports {resolved}")

    c = Check("imports", detail=f"{scanned} internal import(s)")
    if broken:
        return c.failed(
            f"{len(broken)} import(s) point at something that isn't there",
            "; ".join(broken[:4]) + (f"; and {len(broken) - 4} more" if len(broken) > 4 else ""),
            "A module moved during a refactor. Fix the import to its new home")
    return c


def check_names() -> Check:
    """Every name a function reaches for must actually exist.

    The imports probe catches a module that moved. This catches the other
    half of the same accident: a function renamed, and one caller left
    behind calling the old name. Python only finds out when that line runs,
    which for `open_board` meant "open linkedin" raising NameError while
    every test and every other command passed.

    Reads compiled bytecode rather than the source — every LOAD_GLOBAL is
    exactly the name the function will reach for at runtime, with no
    guessing about scope.
    """
    import builtins
    import dis
    import importlib
    import pkgutil
    import types

    package = importlib.import_module("jarvis")
    missing, checked = [], 0

    def code_objects(code):
        yield code
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                yield from code_objects(const)

    for info in pkgutil.walk_packages(package.__path__, "jarvis."):
        try:
            module = importlib.import_module(info.name)
        except Exception:  # noqa: BLE001  (the imports probe reports those)
            continue
        known = set(vars(module)) | set(dir(builtins))
        for value in list(vars(module).values()):
            code = getattr(value, "__code__", None)
            if code is None or getattr(value, "__module__", None) != info.name:
                continue
            for block in code_objects(code):
                for step in dis.get_instructions(block):
                    if step.opname == "LOAD_GLOBAL":
                        checked += 1
                        name = (step.argval or "").lstrip("+ ")
                        if name and name not in known:
                            missing.append(f"{info.name}.{value.__name__} calls {name}")

    c = Check("names", detail=f"{checked} reference(s)")
    if missing:
        unique = sorted(set(missing))
        return c.failed(
            f"{len(unique)} call(s) to something that doesn't exist",
            "; ".join(unique[:4]) + (f"; and {len(unique) - 4} more"
                                     if len(unique) > 4 else ""),
            "Usually a rename with a caller left behind. Fix the name or restore it")
    return c


def check_router() -> Check:
    c = Check("router")
    try:
        from ..routing import router
        answer = router.fast_route("what is the time")
    except Exception as e:  # noqa: BLE001
        return c.failed("The router raised", f"{type(e).__name__}: {e}"[:90],
                        "Usually a bad regex in jarvis/routing/router.py")
    if not answer:
        return c.failed("The router answered nothing for a command it should know",
                        "'what is the time' fell through to the model",
                        "Check the clock patterns in jarvis/routing/router.py")
    c.detail = "answering locally"
    return c


def check_dashboard() -> Check:
    from ..jobs import dashboard
    c = Check("dashboard", detail=f"port {dashboard.PORT}")
    missing = [name for name in ("index.html", "app.css", "app.js")
               if not (dashboard.UI_DIR / name).exists()]
    if missing:
        return c.failed(f"Dashboard files missing: {', '.join(missing)}",
                        f"Expected them in {dashboard.UI_DIR}",
                        "Re-extract ui/jobs/ from the project archive")
    return c


def check_job_sources() -> Check:
    from ..jobs import sources
    c = Check("jobs")
    keyed = bool(os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY"))
    free = [n for n in sources.SOURCES if n != "adzuna"]
    c.detail = f"{len(free)} open board(s)" + (", adzuna keyed" if keyed else "")
    if not keyed:
        c.warned("No Adzuna key",
                 "Adzuna is the source that carries Indian listings; the rest are "
                 "international and remote-first",
                 "Free key at developer.adzuna.com, then put it in .env")
    return c


def check_model_live() -> Check:
    """The only probe that costs a request. Runs on demand, never in tests."""
    c = Check("ai")
    if not config.API_KEY:
        return c.failed("No API key to test", "GEMINI_API_KEY is blank",
                        "Add it to .env and restart")
    try:
        from ..ai.provider import ask_text
        reply = ask_text("Reply with the single word: ready")
    except Exception as e:  # noqa: BLE001
        return c.failed("The model didn't answer", str(e)[:110],
                        "Check the key, the network, and GEMINI_MODEL in .env")
    c.detail = f"{config.MODEL} replied"
    if "ready" not in reply.lower():
        c.warned("The model answered something unexpected", reply[:60],
                 "Usually harmless")
    return c


# ---------------------------------------------------------------- report

PROBES = {
    "runtime": check_runtime,
    "project": check_project,
    "config": check_config,
    "workspace": check_workspace,
    "packages": check_packages,
    "tts": check_voice_out,
    "mic": check_voice_in,
    "browser": check_browser,
    "database": check_database,
    "memory": check_memory,
    "disk": check_disk,
    "network": check_network,
    "tools": check_registry,
    "imports": check_imports,
    "names": check_names,
    "router": check_router,
    "dashboard": check_dashboard,
    "jobs": check_job_sources,
}

# Probes that cost a request. They never run unless asked for by name.
LIVE = ("ai",)


def run_checks(include_live: bool = False) -> list[Check]:
    """Every probe, in order. A probe that raises becomes a failed check
    rather than taking the report down with it."""
    probes = dict(PROBES)
    if include_live:
        probes = {"ai": check_model_live, **probes}

    results = []
    for name, probe in probes.items():
        try:
            results.append(probe())
        except Exception as e:  # noqa: BLE001
            results.append(Check(name).failed(
                "The check itself broke", f"{type(e).__name__}: {e}"[:90],
                "This is a bug in health.py, not in what it was checking"))
    return results


def format_report(checks: list[Check]) -> str:
    width = max(len(c.group) for c in checks) + 2
    lines = ["SYSTEM HEALTH", "-" * 40]
    for c in checks:
        lines.append(f"{c.group.upper():<{width}}{MARK[c.state]:<6}{c.detail}".rstrip())

    troubles = [c for c in checks if c.state != OK]
    if not troubles:
        lines += ["", "Everything checks out."]
        return "\n".join(lines)

    lines += ["", "-" * 40]
    for c in troubles:
        lines += ["",
                  f"{c.group.upper()} — {'problem' if c.state == FAIL else 'works, but'}",
                  f"  Problem:  {c.problem}",
                  f"  Cause:    {c.cause}",
                  f"  Fix:      {c.fix}"]

    failures = sum(1 for c in troubles if c.state == FAIL)
    degraded = len(troubles) - failures
    if failures and degraded:
        summary = f"{failures} broken, {degraded} degraded but working."
    elif failures:
        summary = f"{failures} broken."
    else:
        summary = f"Nothing broken. {degraded} running degraded."
    lines += ["", summary]
    return "\n".join(lines)


def system_check(live: bool = False) -> str:
    """Check everything and report it. Pass live=true to also call the model,
    which costs one request."""
    return format_report(run_checks(include_live=bool(live)))


def check_component(name: str) -> str:
    """Check one thing: mic, browser, config, database, network, tools..."""
    key = (name or "").lower().strip()
    aliases = {"voice": "tts", "speaker": "tts", "microphone": "mic",
               "ai": "ai", "model": "ai", "db": "database", "internet": "network"}
    key = aliases.get(key, key)

    if key == "ai":
        return format_report([check_model_live()])
    probe = PROBES.get(key)
    if not probe:
        return ("I can check: " + ", ".join(sorted(set(PROBES) | set(LIVE))) + ". "
                "Or say run a system check for all of them.")
    return format_report([probe()])
