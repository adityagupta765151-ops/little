"""WhatsApp control. Drafting is free; sending always needs your word.

Uses the whatsapp:// deep link so it works with WhatsApp Desktop, and
falls back to web.whatsapp.com. The final Enter press is only ever sent
after you confirm.
"""
from __future__ import annotations

import os
import time
import urllib.parse
import webbrowser

from ..store import memory
from ..app.config import log

try:
    import pyautogui
except Exception:  # noqa: BLE001  (missing package or no display)
    pyautogui = None

_pending: dict | None = None


def _open_link(url: str) -> bool:
    """Hand a whatsapp:// link to the app registered for it.

    Chapter 48: this used to go through the command line (`start "" "…"`),
    and a saved contact's number goes into the link — a number with a quote
    and & in it could run a command. Now it goes straight to Windows' own
    handler (as the browser module does), with no command line between.
    Returns False, having opened nothing, for a link with quotes or line
    breaks in it."""
    if any(ch in url for ch in '"\r\n\x00'):
        log("refused a WhatsApp link with quotes or line breaks in it")
        return False
    startfile = getattr(os, "startfile", None)       # Windows only
    try:
        if startfile:
            startfile(url)
        else:
            webbrowser.open(url)
    except Exception:  # noqa: BLE001
        webbrowser.open(url)
    return True


BAD_NUMBER = "I couldn't open that chat: the saved number has characters a phone number doesn't."


def open_whatsapp() -> str:
    """Open the WhatsApp app."""
    _open_link("whatsapp://")
    return "Opening WhatsApp."


def open_contact(name: str) -> str:
    """Open a chat. Harmless, so no confirmation."""
    number = memory.find_contact(name)
    if not number:
        return f"I couldn't find {name} in your contacts. Add them with add_contact."
    if not _open_link(f"whatsapp://send?phone={number.lstrip('+')}"):
        return BAD_NUMBER
    return f"Opening your chat with {name}."


def draft_whatsapp_message(name: str, message: str) -> str:
    """Open the chat with the message typed in, but do not send it."""
    global _pending
    number = memory.find_contact(name)
    if not number:
        return f"I couldn't find {name} in your contacts."
    text = urllib.parse.quote(message)
    if not _open_link(f"whatsapp://send?phone={number.lstrip('+')}&text={text}"):
        return BAD_NUMBER                     # starts "I couldn't", so nothing is sent after it
    _pending = {"name": name, "message": message}
    return f"Drafted to {name}: {message}. Say send it to confirm, or press Enter yourself."


def send_whatsapp_message(name: str | None = None, message: str | None = None) -> str:
    """Send the drafted message. Asks for confirmation first."""
    global _pending
    from .permissions import confirm_fn  # late import, the launcher sets this

    if name and message:
        result = draft_whatsapp_message(name, message)
        if result.startswith("I couldn't"):
            return result
        time.sleep(3)

    if not _pending:
        return "There's no draft waiting. Ask me to draft a message first."

    who, what = _pending["name"], _pending["message"]
    from ..store import memory
    from .permissions import Ask
    number = memory.find_contact(who)
    ask = Ask(f"Send this to {who}?\n\n{what}",
              action="Send a WhatsApp message",
              target=f"to {who}" + (f" ({memory.mask(number)})" if number else ""),
              details=what, consequence="It goes from your WhatsApp and can't be unsent.",
              tone="caution", verb="Send", tool="send_whatsapp_message")
    if not confirm_fn(ask):
        _pending = None
        return "Cancelled. Nothing was sent."

    if pyautogui is None:
        return ("The draft is open in WhatsApp, but automatic sending needs pyautogui. "
                "Press Enter in the chat window to send it.")
    try:
        time.sleep(1.5)
        pyautogui.press("enter")
        _pending = None
        return f"Sent to {who}."
    except Exception as e:  # noqa: BLE001
        log(f"whatsapp send failed: {e}")
        return "I opened the chat but couldn't press Enter. Send it yourself."


def has_draft() -> bool:
    """True when a message is drafted and waiting for your yes."""
    return _pending is not None


def add_contact(name: str, number: str) -> str:
    """Save a contact so you can say their name later."""
    return memory.add_contact(name, number)
