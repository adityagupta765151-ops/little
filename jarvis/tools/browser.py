"""Browser automation.

One browser stays open in the background, so the first page costs a few
seconds and every page after that is quick. Playwright's objects belong to
the thread that made them, and JARVIS answers commands on whatever thread
is free, so everything here is funnelled onto one worker thread.

Reading pages is safe and never asks. Clicking and typing ask first when
the target looks like it pays, buys, deletes or submits something.
"""
from __future__ import annotations

import queue
import re
import threading
import time
from urllib.parse import urlparse

from ..app.config import BROWSER_HEADLESS, BROWSER_PROFILE, log
from ..ai.provider import ask_text

MAX_TEXT = 12000          # characters of page text handed to the model
SETUP_HINT = ("Browser automation needs Playwright. In the project folder run: "
              "pip install playwright, then playwright install chromium.")

# A click on any of these gets a confirmation dialog first.
SENSITIVE = re.compile(
    r"\b(pay|payment|buy|purchase|checkout|order|subscribe|donate|"
    r"delete|remove|deactivate|close account|unsubscribe|"
    r"submit|send|confirm|place order|book now|apply now)\b", re.I)


STEP_LIMIT = 180                       # seconds one browser step may take


class _Worker:
    """Owns Playwright on a single thread and runs jobs sent to it."""

    def __init__(self) -> None:
        self.jobs: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.playwright = None
        self.context = None
        self.page = None
        self.lock = threading.Lock()

    def _ensure_thread(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        while True:
            job, box, done = self.jobs.get()
            try:
                box.append(self._attempt(job))
            except Exception as e:  # noqa: BLE001
                log(f"browser job failed: {type(e).__name__}: {e}")
                box.append(_friendly(e))
            finally:
                done.set()

    def _attempt(self, job):
        """Run a job. If the browser was closed or crashed under it, start
        it again and try once more (Chapter 42) — saying so, never quietly.
        A fresh browser opens on a blank page, so a step can't be repeated
        on the page it already acted on."""
        from ..app import recovery
        try:
            return job()
        except Exception as e:  # noqa: BLE001
            if not recovery.browser_gone(e):
                raise
            log(f"browser gone ({type(e).__name__}); starting it again")
            self._forget()
            try:
                result = job()
            except Exception as again:  # noqa: BLE001
                recovery.note("browser", f"it closed and didn't come back: {type(again).__name__}", False)
                raise
            recovery.note("browser", "it had closed; I reopened it and tried the step again", True)
            return _reopened(result)

    def _forget(self) -> None:
        """Drop a browser that's gone, quietly, so the next step starts one."""
        for close in (lambda: self.context and self.context.close(), lambda: self.playwright and self.playwright.stop()):
            try:
                close()
            except Exception:  # noqa: BLE001
                pass
        self.context = self.page = self.playwright = None

    def run(self, job) -> str:
        """Hand a job to the browser thread and wait for its answer."""
        with self.lock:
            self._ensure_thread()
            box: list = []
            done = threading.Event()
            started = time.perf_counter()
            self.jobs.put((job, box, done))
            finished = done.wait(timeout=STEP_LIMIT)
            from ..app import latency           # each step timed, given up on or not (Chapter 46)
            latency.record("browser", (time.perf_counter() - started) * 1000)
            if not finished:
                return "The browser took too long and I gave up on that step."
            return box[0] if box else "The browser returned nothing."

    # -------------------------------------------------- on the worker thread

    def start(self):
        """Launch the browser once, then keep it alive."""
        if self.context:
            return self.context
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(SETUP_HINT) from e

        self.playwright = sync_playwright().start()
        BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)

        # Try Playwright's own Chromium first, then fall back to the Chrome or
        # Edge already on the machine, so a failed 150 MB download isn't fatal.
        # A persistent profile of our own keeps logins between sessions without
        # touching the browser profile you use yourself.
        options = dict(
            headless=BROWSER_HEADLESS,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        problems = []
        for channel in (None, "chrome", "msedge"):
            try:
                extra = {"channel": channel} if channel else {}
                self.context = self.playwright.chromium.launch_persistent_context(
                    str(BROWSER_PROFILE), **options, **extra)
                log(f"browser started ({channel or 'bundled chromium'})")
                break
            except Exception as e:  # noqa: BLE001
                problems.append(f"{channel or 'bundled'}: {str(e)[:80]}")
        else:
            log("no browser could start: " + " | ".join(problems))
            raise RuntimeError(
                "I couldn't start a browser. Either install Google Chrome, or run "
                "python -m playwright install chromium in the project folder.")

        self.context.set_default_timeout(20000)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self.context

    def current(self):
        self.start()
        if self.page is None or self.page.is_closed():
            self.page = self.context.new_page()
        return self.page

    def shutdown(self) -> str:
        if self.context:
            try:
                self.context.close()
            except Exception as e:  # noqa: BLE001
                log(f"context close failed: {e}")
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception as e:  # noqa: BLE001
                log(f"playwright stop failed: {e}")
        self.context = self.page = self.playwright = None
        return "Browser closed."


_worker = _Worker()
REOPENED = "(My browser had closed, so I reopened it.) "


def _reopened(result):
    """A step's answer after the browser was reopened, saying so."""
    if not isinstance(result, str):
        return result
    if result.startswith("\x02"):          # the agent's mark for a step that failed
        return "\x02" + REOPENED + result[1:]
    return REOPENED + result


def _friendly(error: Exception) -> str:
    """Turn a Playwright exception into something worth saying out loud."""
    text = str(error)
    if SETUP_HINT in text:
        return SETUP_HINT
    name = type(error).__name__
    if "Timeout" in name or "Timeout" in text:
        return "The page took too long to respond. It may be slow or the element isn't there."
    if "net::ERR_NAME_NOT_RESOLVED" in text:
        return "That address doesn't exist. Check the spelling."
    if "net::ERR_INTERNET_DISCONNECTED" in text:
        return "I can't reach the internet right now."
    if "closed" in text.lower():
        return "The browser window was closed. Ask me again and I'll reopen it."
    return f"The browser hit a problem: {text[:160]}"


def _ask(prompt: str) -> str:
    """Ask the model about a page, turning an outage into a sentence
    rather than an exception the user would never understand."""
    try:
        return ask_text(prompt)
    except RuntimeError as e:
        return str(e)


def _tidy(url: str) -> str:
    """Add https:// to a bare address, but leave a real scheme alone."""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    return url


def _page_text(page) -> str:
    """Visible text only. Scripts, styles and nav chrome are dropped."""
    text = page.evaluate("""() => {
        const drop = ['script', 'style', 'noscript', 'svg', 'nav', 'footer', 'aside'];
        const clone = document.body.cloneNode(true);
        drop.forEach(tag => clone.querySelectorAll(tag).forEach(n => n.remove()));
        const main = clone.querySelector('main, article, [role=main]') || clone;
        return main.innerText;
    }""")
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    return text[:MAX_TEXT]


# ---------------------------------------------------------------- the tools

def open_page(url: str) -> str:
    """Open a web page in JARVIS's own browser."""
    def job():
        page = _worker.current()
        page.goto(_tidy(url), wait_until="domcontentloaded")
        return f"Opened {page.title() or url}."
    return _worker.run(job)


GOT_TEXT = "\x01"   # the worker prefixes real page content with this


def _read(url: str | None) -> tuple[bool, str]:
    """Returns (did we get page text?, the text or the reason why not)."""
    def job():
        page = _worker.current()
        if url:
            page.goto(_tidy(url), wait_until="domcontentloaded")
            page.wait_for_timeout(600)
        if page.url in ("about:blank", ""):
            return "No page is open yet. Give me a web address and I'll read it."
        text = _page_text(page)
        if not text:
            return "That page had no readable text. It may load its content with a script."
        return f"{GOT_TEXT}{page.title()}\n\n{text}"

    result = _worker.run(job)
    if result.startswith(GOT_TEXT):
        return True, result[len(GOT_TEXT):]
    return False, result


def read_page(url: str | None = None) -> str:
    """Read the visible text of a page. Give a url, or leave it out for
    whatever page is already open."""
    return _read(url)[1]


def summarize_page(url: str | None = None, question: str | None = None) -> str:
    """Read a page and summarise it, or answer a question about it."""
    ok, body = _read(url)
    if not ok:
        return body
    ask = question or "Summarise this page in four or five plain sentences."
    from ..ai import models
    with models.use("fast"):                # a summary doesn't need the strong model (Chapter 43)
        return _ask(f"{ask}\n\nPage content:\n{body}")


def search_web_and_read(query: str, count: int = 5) -> str:
    """Search the web and bring back the top results with their snippets,
    instead of just opening a tab."""
    def job():
        page = _worker.current()
        page.goto("https://duckduckgo.com/?q=" + query.replace(" ", "+"),
                  wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        results = page.evaluate("""(n) => {
            const out = [];
            const seen = new Set();
            document.querySelectorAll('a[href^="http"]').forEach(a => {
                const title = (a.innerText || '').trim();
                if (title.length < 15 || seen.has(a.href)) return;
                if (a.href.includes('duckduckgo.com')) return;
                seen.add(a.href);
                if (out.length < n) out.push(title + ' - ' + a.href);
            });
            return out;
        }""", count)
        if not results:
            return f"I searched for {query} but couldn't read any results."
        return f"Top results for {query}:\n" + "\n".join(results)
    return _worker.run(job)


def find_on_page(what: str) -> str:
    """Ask what's on the page: a price, a heading, a button, a date."""
    ok, body = _read(None)
    if not ok:
        return body
    return _ask(
        f"From this page, find: {what}. Answer in one short sentence. "
        f"If it isn't there, say so plainly.\n\nPage content:\n{body}")


def _current_address() -> str:
    """The address of the page already open, for a question about it. Never
    starts the browser just to ask."""
    if _worker.page is None:
        return ""
    try:
        found = _worker.run(lambda: "" if _worker.page is None or _worker.page.is_closed()
                            else _worker.page.url)
    except Exception:  # noqa: BLE001
        return ""
    return found if isinstance(found, str) and found.startswith(("http://", "https://")) else ""


def current_page() -> dict | None:
    """The page already open in LITTLE's browser — its address, title and
    visible text — or None when there isn't one. Never starts the browser:
    a question about the page you're on can't open a new one."""
    if _worker.page is None:
        return None

    def job():
        page = _worker.page
        if page is None or page.is_closed() or page.url in ("about:blank", ""):
            return None
        return {"url": page.url, "title": page.title(), "text": _page_text(page)}
    try:
        found = _worker.run(job)
    except Exception:  # noqa: BLE001
        return None
    return found if isinstance(found, dict) else None


# What a click or a key would do on the open page (Chapter 37): whether the
# button submits a form, whether Enter would. Read before asking, so a
# button called "Go" is asked about like one called "Submit".
_PROBE_CLICK = """(text) => {
  const t = text.toLowerCase();
  const els = [...document.querySelectorAll('button, input[type=submit], input[type=button], a, [role=button]')];
  const el = els.find(e => ((e.innerText || e.value || e.getAttribute('aria-label') || '') + '')
                              .toLowerCase().includes(t));
  if (!el) return {found: false, submits: false};
  const type = (el.getAttribute('type') || '').toLowerCase();
  const submits = !!el.form && (type === 'submit' || (el.tagName === 'BUTTON' && type === ''))
                  || (el.tagName === 'INPUT' && type === 'submit');
  return {found: true, submits};
}"""
_PROBE_ENTER = "() => !!(document.activeElement && document.activeElement.form) || document.forms.length > 0"


def _probe(script: str, *args):
    """Run a read-only check on the open page; None if there's no page or
    it can't be read. Never starts the browser."""
    if _worker.page is None:
        return None
    try:
        return _worker.run(lambda: None if _worker.page is None or _worker.page.is_closed()
                           else _worker.page.evaluate(script, *args))
    except Exception:  # noqa: BLE001
        return None


def _job_board_page() -> bool:
    from .browser_agent import _no_automation
    return _no_automation(_current_address())


def click_text(text: str) -> str:
    """Click a link or button by the words on it. Asks first if the click
    looks like it spends money or changes something — by its words, or
    because it submits a form. On a job board, a submit is never pressed."""
    from .permissions import confirm_fn

    seen = _probe(_PROBE_CLICK, text)
    submits = isinstance(seen, dict) and seen.get("submits") is True
    if (submits or re.search(r"\bapply\b|\bsubmit\b", text, re.I)) and _job_board_page():
        return ("That's a job board, and their terms don't allow a program to submit or apply. "
                "Press it yourself.")
    if SENSITIVE.search(text) or submits:
        from .permissions import Ask
        where = _current_address()
        ask = Ask(f"Click \"{text}\" on this page?\n\n"
                  f"This looks like it could submit, send, buy or delete something.",
                  action="Click a button on a web page",
                  target=f"“{text}”" + (f" on {urlparse(where).netloc}" if where else ""),
                  details=f"The button or link that says “{text}”"
                          + (f"\nPage: {where}" if where else ""),
                  consequence="It submits a form." if submits and not SENSITIVE.search(text) else
                              "Its words suggest it could submit, send, buy or delete something.",
                  tone="caution", verb="Click", tool="click_text")
        if not confirm_fn(ask):
            return "You declined, so I didn't click it."

    def job():
        page = _worker.current()
        # Look by role first, the way a person reads the page, so a change
        # of styling or class names doesn't break it.
        for finder in (
            lambda: page.get_by_role("button", name=text, exact=False),
            lambda: page.get_by_role("link", name=text, exact=False),
            lambda: page.get_by_text(text, exact=False),
        ):
            target = finder().first
            if target.count() > 0:
                target.click()
                page.wait_for_timeout(1200)
                return f"Clicked {text}. Now on: {page.title()}"
        return f"I couldn't find anything labelled \"{text}\" on this page."
    return _worker.run(job)


SECRET_REFUSED = "I don't type passwords, one-time codes or card details. Type that one yourself."


def fill_field(label: str, value: str) -> str:
    """Type into a form field, found by its label or placeholder. Never a
    password, code or card field — by its label or its type."""
    from .browser_agent import SECRET_FIELD
    if SECRET_FIELD.search(str(label or "")):
        return SECRET_REFUSED

    def job():
        page = _worker.current()
        for finder in (
            lambda: page.get_by_label(label, exact=False),
            lambda: page.get_by_placeholder(label, exact=False),
            lambda: page.locator(f"input[name*='{label}' i], textarea[name*='{label}' i]"),
        ):
            target = finder().first
            if target.count() > 0:
                if (target.get_attribute("type") or "").lower() == "password" or \
                        SECRET_FIELD.search(target.get_attribute("autocomplete") or ""):
                    return SECRET_REFUSED
                target.fill(value)
                return f"Filled {label}."
        return f"I couldn't find a field called \"{label}\" on this page."
    return _worker.run(job)


ENTER_KEYS = {"enter", "return", "numpadenter"}


def press_key(key: str = "Enter") -> str:
    """Press a key, usually Enter to submit a search box. Enter on a page
    with a form asks first — it can submit the form — and on a job board
    it isn't pressed at all."""
    from .permissions import Ask, confirm_fn
    if str(key or "").strip().lower() in ENTER_KEYS and _probe(_PROBE_ENTER) is True:
        if _job_board_page():
            return ("That's a job board, and their terms don't allow a program to submit a form there. "
                    "Press Enter yourself.")
        where = _current_address()
        ask = Ask("Press Enter on this page?\n\nIt could submit the form.",
                  action="Press Enter on a web page",
                  target=urlparse(where).netloc if where else "the open page",
                  details=f"Page: {where}" if where else "",
                  consequence="It could submit the form on the page.",
                  tone="caution", verb="Press Enter", tool="press_key")
        if confirm_fn(ask) is not True:
            return "You said no, so I didn't press it."

    def job():
        page = _worker.current()
        page.keyboard.press(key)
        page.wait_for_timeout(1200)
        return f"Pressed {key}. Now on: {page.title()}"
    return _worker.run(job)


def browser_screenshot() -> str:
    """Save a picture of the current page."""
    from ..app.config import MEMORY_DIR
    import datetime

    def job():
        page = _worker.current()
        path = MEMORY_DIR / datetime.datetime.now().strftime("page-%H%M%S.png")
        page.screenshot(path=str(path), full_page=False)
        return f"Saved a picture of the page to {path}."
    return _worker.run(job)


def close_browser() -> str:
    """Shut the automated browser down and free its memory."""
    return _worker.run(_worker.shutdown)
