"""WhatsApp through the browser, so any name in your chat list works
without adding numbers by hand.

You scan the QR code once. The browser keeps its own profile folder, so
the login survives restarts. Nothing is ever sent without your yes.

WhatsApp changes its page markup from time to time, so every step tries
a few ways of finding things and says plainly when it can't.
"""
from __future__ import annotations

import re

from .browser import _worker
from ..app.config import log

URL = "https://web.whatsapp.com/"
_pending: dict | None = None


def _find(page, strategies, what: str):
    """Try each way of locating something and return the first that exists."""
    for describe, build in strategies:
        try:
            target = build().first
            if target.count() > 0:
                return target
        except Exception as e:  # noqa: BLE001
            log(f"whatsapp: {what} via {describe} failed: {str(e)[:80]}")
    return None


def _search_box(page):
    return _find(page, [
        ("role", lambda: page.get_by_role("textbox", name=re.compile("search", re.I))),
        ("data-tab", lambda: page.locator('div[contenteditable="true"][data-tab="3"]')),
        ("side panel", lambda: page.locator('#side div[contenteditable="true"]')),
    ], "search box")


def _composer(page):
    return _find(page, [
        ("role", lambda: page.get_by_role("textbox", name=re.compile("message|type a", re.I))),
        ("data-tab", lambda: page.locator('div[contenteditable="true"][data-tab="10"]')),
        ("footer", lambda: page.locator('footer div[contenteditable="true"]')),
    ], "message box")


def _goto(page):
    if not page.url.startswith(URL):
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)


def _logged_in(page) -> bool:
    return _search_box(page) is not None


def wa_open() -> str:
    """Open WhatsApp Web in JARVIS's browser."""
    def job():
        page = _worker.current()
        _goto(page)
        page.wait_for_timeout(2000)
        if _logged_in(page):
            return "WhatsApp Web is open and signed in."
        return ("WhatsApp Web is open but not signed in. Scan the QR code on screen "
                "with your phone, then tell me to try again. You only do this once.")
    return _worker.run(job)


def wa_contacts(limit: int = 40) -> str:
    """List the people in your WhatsApp chat list."""
    def job():
        page = _worker.current()
        _goto(page)
        if not _logged_in(page):
            return "WhatsApp Web isn't signed in yet. Open it and scan the QR code first."
        page.wait_for_timeout(1200)
        names = page.evaluate("""(n) => {
            const side = document.querySelector('#pane-side') || document;
            const out = [];
            side.querySelectorAll('span[title]').forEach(s => {
                const t = (s.getAttribute('title') || '').trim();
                if (t && !out.includes(t) && out.length < n) out.push(t);
            });
            return out;
        }""", limit)
        if not names:
            return "I couldn't read your chat list. Scroll the list once and ask me again."
        return f"{len(names)} chats visible:\n" + "\n".join(names)
    return _worker.run(job)


def wa_open_chat(name: str) -> str:
    """Open someone's chat by searching for their name."""
    def job():
        page = _worker.current()
        _goto(page)
        if not _logged_in(page):
            return "WhatsApp Web isn't signed in yet. Open it and scan the QR code first."

        box = _search_box(page)
        if box is None:
            return "I couldn't find WhatsApp's search box. Its layout may have changed."
        box.click()
        page.keyboard.press("Control+A")
        box.fill("")
        page.keyboard.type(name, delay=40)
        page.wait_for_timeout(1800)

        # The first result under the search list is the best match.
        result = _find(page, [
            ("listitem", lambda: page.locator('#pane-side [role="listitem"]')),
            ("grid row", lambda: page.locator('[role="grid"] [role="row"]')),
        ], "search result")
        if result is None:
            return f"No chat came up for {name}. Check the spelling, or they may not be in your list."
        result.click()
        page.wait_for_timeout(1500)
        return f"Opened the chat with {name}."
    return _worker.run(job)


def wa_draft_web(name: str, message: str) -> str:
    """Open someone's chat and type a message, without sending it."""
    global _pending
    opened = wa_open_chat(name)
    if not opened.startswith("Opened"):
        return opened

    def job():
        page = _worker.current()
        box = _composer(page)
        if box is None:
            return "I opened the chat but couldn't find the message box."
        box.click()
        page.keyboard.type(message, delay=15)
        page.wait_for_timeout(400)
        return "typed"

    result = _worker.run(job)
    if result != "typed":
        return result
    _pending = {"name": name, "message": message}
    return f"Typed to {name}: {message}. Say send it to confirm."


def wa_send_web(name: str | None = None, message: str | None = None) -> str:
    """Send the typed message. Asks you first."""
    global _pending
    from .permissions import confirm_fn

    if name and message:
        drafted = wa_draft_web(name, message)
        if not drafted.startswith("Typed"):
            return drafted

    if not _pending:
        return "There's nothing typed yet. Ask me to draft a message first."

    who, what = _pending["name"], _pending["message"]
    from .permissions import Ask
    ask = Ask(f"Send this to {who} on WhatsApp?\n\n{what}",
              action="Send a WhatsApp message", target=f"to {who}, in WhatsApp Web",
              details=what, consequence="It goes from your WhatsApp and can't be unsent.",
              tone="caution", verb="Send", tool="wa_send_web")
    if not confirm_fn(ask):
        _pending = None
        return "Cancelled. Nothing was sent."

    def job():
        page = _worker.current()
        box = _composer(page)
        if box is None:
            return "The message box disappeared. Nothing was sent."
        box.click()
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)
        return "sent"

    result = _worker.run(job)
    _pending = None
    return f"Sent to {who}." if result == "sent" else result


def has_draft() -> bool:
    """True when a message is typed and waiting for your yes."""
    return _pending is not None


def wa_read_chat(count: int = 12) -> str:
    """Read the last few messages in the open chat."""
    def job():
        page = _worker.current()
        if not page.url.startswith(URL):
            return "WhatsApp Web isn't open. Ask me to open a chat first."
        messages = page.evaluate("""(n) => {
            const rows = document.querySelectorAll('[role="row"]');
            const out = [];
            rows.forEach(r => {
                const t = (r.innerText || '').trim().split('\\n')[0];
                if (t) out.push(t);
            });
            return out.slice(-n);
        }""", count)
        if not messages:
            return "I couldn't read any messages. Open a chat first."
        return "Last messages:\n" + "\n".join(messages)
    return _worker.run(job)
