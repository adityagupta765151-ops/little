"""The browser agent: observe, plan, act, verify (Chapter 28).

Built on the one browser the browser tools already share (browser._worker),
so there is still one Playwright, on one thread.

    observe   what the open page is: address, title, headings, text, links,
              buttons, forms and their fields, error messages, whether it
              can go back. Read with a script on the page; nothing clicked.
    act       one step from a small, fixed set — open, click, fill, select,
              press, back — each checked first. A click or key press that
              could submit, send, buy or delete asks you; a password, OTP or
              card field is never typed into; a submit on a job board whose
              terms forbid automation is never pressed.
    verify    after every step the page is observed again and the step's
              expectation checked against it: the field holds the value, the
              address changed, the text appeared, no new error. A step that
              can't be verified is reported as not verified — never as done.
    run_task  the loop: the model is shown the goal and the page and picks
              the next step from that fixed set; LITTLE checks, acts and
              verifies it. Eight steps at most; it stops at the first step
              that fails or can't be verified, and says so.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from ..app.config import log
from . import browser

MAX_STEPS = 8
ACTION_TIMEOUT_MS = 8000          # one step's wait for the page, not the whole task
TEXT_SHOWN = 1500                 # characters of page text in an observation
ITEMS_SHOWN = 15                  # links, buttons and fields listed per kind
KEYS = ("Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "PageDown", "PageUp")

# Fields that are never typed into: secrets, one-time codes, card details.
SECRET_FIELD = re.compile(r"password|passcode|\botp\b|one[- ]time|verification code|\bcvv\b|\bcvc\b|"
                          r"card number|security code|\bpin\b|captcha", re.I)
# Boards whose terms forbid automated applying: a submit or apply there is
# never pressed by LITTLE, asked or not (jobs/apply.py says why).
NO_AUTOMATION_HOSTS = ("linkedin.com", "naukri.com", "indeed.com", "internshala.com", "wellfound.com")
SUBMITS = re.compile(r"\b(submit|apply|send|post)\b", re.I)

OBSERVE_JS = """(limit) => {
  const shown = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const text = (el) => (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '')
    .replace(/\\s+/g, ' ').trim().slice(0, 80);
  const labelOf = (el) => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return l.innerText.trim(); }
    const wrap = el.closest('label'); if (wrap) return wrap.innerText.trim();
    return el.placeholder || el.name || '';
  };
  const links = [...document.querySelectorAll('a[href]')].filter(shown)
    .map(a => ({text: text(a), href: a.href})).filter(l => l.text).slice(0, limit);
  const buttons = [...document.querySelectorAll('button, input[type=submit], input[type=button], [role=button]')]
    .filter(shown).map(b => ({text: text(b), submit: b.type === 'submit' || (b.tagName === 'BUTTON' && !b.type) ||
      (b.tagName === 'BUTTON' && b.getAttribute('type') === null && !!b.closest('form')), disabled: !!b.disabled}))
    .filter(b => b.text).slice(0, limit);
  const forms = [...document.querySelectorAll('form')].map((f, i) => ({index: i,
    fields: [...f.querySelectorAll('input, select, textarea')].filter(el => el.type !== 'hidden' && shown(el))
      .map(el => ({label: labelOf(el).replace(/\\s+/g, ' ').slice(0, 60), type: el.type || el.tagName.toLowerCase(),
                   required: !!el.required, filled: el.type === 'password' ? !!el.value : String(el.value || '').slice(0, 60),
                   invalid: el.getAttribute('aria-invalid') === 'true'}))
      .slice(0, limit)}));
  const errors = [...document.querySelectorAll('[role=alert], .error, .errors, .invalid-feedback, [aria-invalid=true]')]
    .filter(shown).map(e => (e.innerText || e.getAttribute('aria-label') || '').trim()).filter(Boolean).slice(0, 8);
  const headings = [...document.querySelectorAll('h1, h2')].filter(shown).map(text).filter(Boolean).slice(0, 8);
  return {url: location.href, title: document.title, headings, links, buttons, forms, errors,
          text: (document.body ? document.body.innerText : '').replace(/\\n{3,}/g, '\\n\\n').trim(),
          loading: document.readyState !== 'complete', can_go_back: history.length > 1};
}"""


# ------------------------------------------------------------------ observe

def _no_browser(reason: str) -> dict:
    return {"error": reason}


def observe(start: bool = False) -> dict:
    """What the page open in LITTLE's browser is, as data. Doesn't start the
    browser unless `start` — a question about the page you're on must not
    open a new one. {"error": why} when there's nothing to look at."""
    if browser._worker.page is None and not start:
        return _no_browser("No page is open in my browser.")

    def job():
        page = browser._worker.current() if start else browser._worker.page
        if page is None or page.is_closed() or page.url in ("about:blank", ""):
            return _no_browser("No page is open in my browser.")
        seen = page.evaluate(OBSERVE_JS, ITEMS_SHOWN)
        seen["text"] = (seen.get("text") or "")[:browser.MAX_TEXT]
        return seen
    try:
        found = browser._worker.run(job)
    except Exception as e:  # noqa: BLE001
        return _no_browser(browser._friendly(e))
    return found if isinstance(found, dict) else _no_browser(str(found))


def describe(seen: dict) -> str:
    """An observation as text, for you and for the model."""
    if "error" in seen:
        return seen["error"]
    lines = [f"Page: {seen['title'] or '(no title)'} — {seen['url']}"]
    if seen.get("errors"):
        lines.append("Errors on the page: " + " | ".join(seen["errors"]))
    if seen.get("headings"):
        lines.append("Headings: " + " | ".join(seen["headings"]))
    for form in seen.get("forms", []):
        fields = ", ".join(f"{f['label'] or '(unlabelled)'} [{f['type']}"
                           + (", required" if f["required"] else "")
                           + (", filled" if f["filled"] else "")
                           + (", marked invalid" if f["invalid"] else "") + "]"
                           for f in form["fields"])
        if fields:
            lines.append(f"Form {form['index'] + 1}: {fields}")
    if seen.get("buttons"):
        lines.append("Buttons: " + ", ".join(b["text"] + (" (submits)" if b["submit"] else "")
                                             for b in seen["buttons"]))
    if seen.get("links"):
        lines.append("Links: " + ", ".join(l["text"] for l in seen["links"]))
    text = (seen.get("text") or "")[:TEXT_SHOWN]
    if text:
        lines.append("Text:\n" + text)
    return "\n".join(lines)


def look_at_page() -> str:
    """The tool: what's on the page open in LITTLE's browser."""
    return describe(observe())


# --------------------------------------------------------------------- act

def _host(url: str) -> str:
    """The host name alone — no port, no user — so a rule about a site holds
    on any port."""
    return (urlparse(url or "").hostname or "").lower()


def _no_automation(url: str) -> bool:
    host = _host(url)
    return any(host == h or host.endswith("." + h) for h in NO_AUTOMATION_HOSTS)


def check(step: dict, seen: dict) -> tuple[str, str]:
    """Is this step allowed, and does it need your yes? Returns ("ok" |
    "ask" | "blocked" | "invalid", why)."""
    do = step.get("do")
    if do == "open":
        url = str(step.get("url") or "")
        if not re.match(r"https?://", url):
            return "invalid", "I only open web addresses that start with http:// or https://."
        return "ok", ""
    if do == "back":
        return "ok", ""
    if do in ("fill", "select"):
        field = str(step.get("field") or "")
        value = str(step.get("value") if do == "fill" else step.get("option") or "")
        if not field or (do == "fill" and len(value) > 500):
            return "invalid", "A field to fill needs its label and a value under 500 characters."
        types = [f["type"] for form in seen.get("forms", []) for f in form["fields"]
                 if field.lower() in (f["label"] or "").lower()]
        if SECRET_FIELD.search(field) or "password" in types:
            return "blocked", ("That field takes a password, a one-time code or card details. "
                               "I never type those; fill it in yourself.")
        return "ok", ""
    if do == "click":
        target = str(step.get("target") or "")
        if not target:
            return "invalid", "A click needs the words on the button or link."
        button = next((b for b in seen.get("buttons", []) if target.lower() in b["text"].lower()), None)
        submits = bool(button and button["submit"])
        if _no_automation(seen.get("url", "")) and (SUBMITS.search(target) or submits):
            return "blocked", (f"{_host(seen.get('url', ''))} doesn't allow automated applying or "
                               f"posting, so I won't press that. Press it yourself.")
        if browser.SENSITIVE.search(target) or submits:
            return "ask", "It could submit, send, buy or delete something."
        return "ok", ""
    if do == "press":
        key = str(step.get("key") or "")
        if key not in KEYS:
            return "invalid", f"I can press {', '.join(KEYS)}."
        if key == "Enter" and seen.get("forms"):
            return "ask", "Enter on a page with a form can submit it."
        return "ok", ""
    return "invalid", "I can open, click, fill, select, press or go back."


def _ask(step: dict, seen: dict, why: str) -> bool:
    from .permissions import Ask, confirm_fn
    what = step.get("target") or step.get("key") or step.get("do")
    host = _host(seen.get("url", ""))
    ask = Ask(f"On {host or 'this page'}, {step['do']} “{what}”?\n\n{why}",
              action="Press something on a web page" if step["do"] == "press" else "Click a button on a web page",
              target=f"“{what}”" + (f" on {host}" if host else ""),
              details=f"Step: {step['do']} “{what}”\nPage: {seen.get('url', '')}",
              consequence=why, tone="caution", verb="Go ahead", tool="browser_task")
    return confirm_fn(ask) is True


def _do(step: dict) -> str:
    """On the browser thread: the step itself. A leading \x02 marks "couldn't"."""
    page = browser._worker.current()
    page.set_default_timeout(ACTION_TIMEOUT_MS)
    do = step["do"]
    if do == "open":
        try:
            page.goto(step["url"], wait_until="domcontentloaded", timeout=ACTION_TIMEOUT_MS)
        except Exception as e:  # noqa: BLE001
            # A page that took too long earlier can finish loading over this
            # one. Opening an address only reads, so it's tried once more.
            if "interrupted by another navigation" not in str(e):
                raise
            page.goto(step["url"], wait_until="domcontentloaded", timeout=ACTION_TIMEOUT_MS)
        return f"Opened {page.title() or step['url']}."
    if do == "back":
        page.go_back(wait_until="domcontentloaded", timeout=ACTION_TIMEOUT_MS)
        return f"Went back to {page.title() or page.url}."
    if do == "press":
        page.keyboard.press(step["key"])
        page.wait_for_load_state("domcontentloaded", timeout=ACTION_TIMEOUT_MS)
        return f"Pressed {step['key']}."
    if do == "click":
        target = step["target"]
        for finder in (lambda: page.get_by_role("button", name=target, exact=False),
                       lambda: page.get_by_role("link", name=target, exact=False),
                       lambda: page.get_by_text(target, exact=False)):
            found = finder().first
            if found.count() > 0:
                found.click(timeout=ACTION_TIMEOUT_MS)
                page.wait_for_load_state("domcontentloaded", timeout=ACTION_TIMEOUT_MS)
                return f"Clicked “{target}”."
        return f"\x02I couldn't find “{target}” on the page."
    field = step["field"]
    for finder in (lambda: page.get_by_label(field, exact=False),
                   lambda: page.get_by_placeholder(field, exact=False)):
        found = finder().first
        if found.count() > 0:
            if do == "fill":
                found.fill(str(step["value"]), timeout=ACTION_TIMEOUT_MS)
                return f"Typed into “{field}”."
            found.select_option(label=str(step["option"]), timeout=ACTION_TIMEOUT_MS)
            return f"Chose “{step['option']}” in “{field}”."
    return f"\x02I couldn't find a field called “{field}”."


BROWSER_TROUBLE = ("The page took too long", "The browser", "That address", "I can't reach",
                   "I couldn't start", "Browser automation needs")


def act(step: dict, seen: dict | None = None) -> tuple[bool, str]:
    """Do one step on the page, after checking it. Returns (done, what
    happened) — done means the browser did it, not that it worked; verify
    says that."""
    seen = seen if seen is not None else observe()
    if "error" in seen:
        if step.get("do") != "open":
            return False, seen["error"]
        seen = {}
    verdict, why = check(step, seen)
    if verdict in ("invalid", "blocked"):
        return False, why
    if verdict == "ask" and not _ask(step, seen, why):
        return False, "You said no, so I didn't."
    try:
        said = browser._worker.run(lambda: _do(step))
    except Exception as e:  # noqa: BLE001
        return False, browser._friendly(e)
    if not isinstance(said, str):
        return False, "The browser returned nothing."
    if said.startswith("\x02"):
        return False, said[1:]
    if said.startswith(BROWSER_TROUBLE):
        return False, said
    return True, said


# ------------------------------------------------------------------ verify

def verify(step: dict, before: dict, after: dict) -> tuple[bool, str]:
    """Did the step do what it was meant to? Checked on the page as it is
    now. The step's own `expect` if it gave one; otherwise what the step
    itself implies. Returns (verified, the evidence or why not)."""
    if "error" in after:
        return False, after["error"]
    expect = step.get("expect") or {}
    text = f"{after.get('title', '')}\n{after.get('text', '')}".lower()
    checks: list[tuple[bool, str]] = []
    if expect.get("url_contains"):
        want = str(expect["url_contains"]).lower()
        checks.append((want in after["url"].lower(), f"the address has “{want}”"))
    if expect.get("text_contains"):
        want = str(expect["text_contains"]).lower()
        checks.append((want in text, f"the page says “{expect['text_contains']}”"))
    if expect.get("title_contains"):
        want = str(expect["title_contains"]).lower()
        checks.append((want in (after.get("title") or "").lower(), f"the title has “{want}”"))
    if not checks:
        do = step.get("do")
        if do == "fill":
            value = str(step.get("value", ""))[:60]
            has = any(step.get("field", "").lower() in (f["label"] or "").lower() and f["filled"] == value
                      for form in after.get("forms", []) for f in form["fields"])
            checks.append((has, f"“{step.get('field')}” holds what was typed"))
        elif do == "open":
            same = _host(after["url"]).removeprefix("www.") == _host(step.get("url", "")).removeprefix("www.")
            checks.append((same, f"the page at {_host(step.get('url', ''))} is open"))
        elif do in ("click", "press", "back"):
            changed = (after["url"] != before.get("url") or after.get("title") != before.get("title")
                       or after.get("text") != before.get("text") or after.get("errors") != before.get("errors"))
            checks.append((changed, "the page changed"))
        else:
            checks.append((True, "done"))
    new_errors = [e for e in after.get("errors", []) if e not in before.get("errors", [])]
    if expect and expect.get("no_errors", True) and new_errors:
        checks.append((False, f"no error appeared (it says: {new_errors[0]})"))
    failed = [what for ok, what in checks if not ok]
    if failed:
        return False, "Not verified: expected " + "; ".join(failed) + "."
    return True, "Verified: " + "; ".join(what for _, what in checks) + "."


# -------------------------------------------------------------------- plan

PLAN = """You are operating a web browser for the user, one step at a time.

Goal: {goal}

Steps so far:
{done}

The page now:
{page}

Reply with ONE JSON object and nothing else. Either the next step:
  {{"do": "open", "url": "https://...", "expect": {{"url_contains": "..."}}}}
  {{"do": "click", "target": "words on the button or link", "expect": {{"text_contains": "..."}}}}
  {{"do": "fill", "field": "the field's label", "value": "..."}}
  {{"do": "select", "field": "the field's label", "option": "..."}}
  {{"do": "press", "key": "Enter"}}
  {{"do": "back"}}
or, when the goal is reached or can't be, {{"done": true, "answer": "what you found or why not"}}.
"expect" is optional: what the page should show after the step.
Never type passwords, one-time codes or card numbers. Only use what the goal and page say."""


def _next_step(goal: str, history: list[str], seen: dict) -> dict:
    from ..ai.provider import ask_text
    raw = ask_text(PLAN.format(goal=goal, done="\n".join(history) or "(none yet)",
                               page=describe(seen)[:4000]))
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        return {"invalid": "The model didn't answer with a step."}
    try:
        step = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"invalid": "The model's step wasn't valid JSON."}
    return step if isinstance(step, dict) else {"invalid": "The model's step wasn't an object."}


def run_task(goal: str) -> str:
    """The tool: reach a goal in the browser, step by step — observe, have
    the model pick one step from a fixed set, check it (asking you where it
    could submit, send, buy or delete), do it, verify it on the page. Stops
    at the first step that fails or can't be verified."""
    goal = " ".join(str(goal or "").split())[:500]
    if not goal:
        return "Tell me what to do in the browser."
    history: list[str] = []
    seen = observe()
    if "error" in seen:
        seen = {"url": "", "title": "", "text": "", "forms": [], "buttons": [], "links": [], "errors": [],
                "headings": [], "note": seen["error"]}
    for number in range(1, MAX_STEPS + 1):
        try:
            step = _next_step(goal, history, seen)
        except RuntimeError as e:
            return _report(history, f"I stopped: the model couldn't be reached ({e}).")
        if step.get("invalid"):
            return _report(history, f"I stopped: {step['invalid']}")
        if step.get("done"):
            return _report(history, str(step.get("answer") or "Done."), finished=True)
        before = seen
        ok, said = act(step, before if "note" not in before else {"error": before["note"]})
        label = _label(step)
        if not ok:
            history.append(f"{number}. {label} — not done: {said}")
            return _report(history, f"I stopped at step {number}: {said}")
        seen = observe()
        verified, evidence = verify(step, before, seen)
        history.append(f"{number}. {label} — {evidence}")
        log(f"browser_task step {number}: {label}: {evidence}")
        if not verified:
            return _report(history, f"I stopped at step {number}: it didn't do what it should have.")
    return _report(history, f"I stopped after {MAX_STEPS} steps without reaching the goal.")


def _label(step: dict) -> str:
    do = step.get("do")
    return {"open": f"open {step.get('url')}", "click": f"click “{step.get('target')}”",
            "fill": f"fill “{step.get('field')}”", "select": f"choose “{step.get('option')}” in “{step.get('field')}”",
            "press": f"press {step.get('key')}", "back": "go back"}.get(do, str(do))


def _report(history: list[str], ending: str, finished: bool = False) -> str:
    """The steps as they went, each with what was verified, then the end."""
    if not history:
        return ending
    return "\n".join(["BROWSER TASK"] + history + ["", ending])
