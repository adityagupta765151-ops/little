"""Looking at the screen, only when you ask.

Chapter 29 adds finding something on it — with how sure the model is —
and clicking it. A page in LITTLE's own browser is found by its words
there, not by a picture. Anything found in a screenshot is clicked only
when the model is sure, it isn't something that could pay, send, submit or
delete, and you say yes.
"""
from __future__ import annotations

import datetime
import io
import json
import re

from ..app.config import MEMORY_DIR, log
from ..ai.provider import ask_about_image


def _grab() -> bytes | None:
    try:
        from PIL import ImageGrab
        image = ImageGrab.grab()
    except Exception:  # noqa: BLE001
        try:
            import pyautogui
            image = pyautogui.screenshot()
        except Exception as e:  # noqa: BLE001
            log(f"screenshot failed: {e}")
            return None
    image.thumbnail((1600, 1600))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def take_screenshot() -> str:
    """Save a screenshot to the memory folder."""
    data = _grab()
    if not data:
        return "I couldn't capture the screen. Install pillow with pip install pillow."
    path = MEMORY_DIR / datetime.datetime.now().strftime("screen-%H%M%S.png")
    path.write_bytes(data)
    return f"Screenshot saved to {path}."


def describe_screen(question: str = "What is on this screen? If there is an error, explain it.") -> str:
    """Capture the screen and have the model read it."""
    data = _grab()
    if not data:
        return "I couldn't capture the screen. Install pillow with pip install pillow."
    try:
        return ask_about_image(data, question)
    except Exception as e:  # noqa: BLE001
        log(f"describe_screen failed: {e}")
        return str(e) or "Something went wrong while reading the screen."


# ------------------------------------------ Chapter 29: finding things on it

# How sure the model must be before a place on the screen is acted on, and
# the words that make a target risky: a click there is never made from a
# picture, however sure — you click it yourself.
CONFIDENT = 0.85
RISKY = re.compile(r"\b(pay|payment|buy|purchase|checkout|order|subscribe|delete|remove|erase|format|"
                   r"uninstall|send|submit|confirm|transfer|apply|sign out|log ?out|shut ?down|restart|"
                   r"install|allow|grant)\b", re.I)

LOCATE = """Find this on the screenshot: {what}

Reply with one JSON object and nothing else:
{{"found": true or false, "element": "the words or name on it, as shown",
  "box": [x, y, width, height] in this image's pixels, "confidence": 0.0 to 1.0,
  "risky": true if clicking it could pay, send, submit, delete, install or change settings}}
If it isn't clearly visible, say found false. Don't guess a position."""


def _capture() -> tuple[bytes, tuple[int, int], tuple[int, int]] | None:
    """A screenshot as PNG, with the screen's size and the picture's (the
    picture is shrunk, so a position on it is scaled back to the screen)."""
    try:
        from PIL import ImageGrab
        image = ImageGrab.grab()
    except Exception:  # noqa: BLE001
        try:
            import pyautogui
            image = pyautogui.screenshot()
        except Exception as e:  # noqa: BLE001
            log(f"screenshot failed: {e}")
            return None
    screen_size = image.size
    image.thumbnail((1600, 1600))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), screen_size, image.size


def locate(what: str) -> dict:
    """Where something is on the screen, as the model reads a screenshot:
    {"found", "element", "center" (screen pixels), "confidence", "risky",
    "why"}. Every answer is checked: a box outside the picture, a
    confidence that isn't a number or a reply that isn't JSON counts as not
    found. Never acts."""
    what = " ".join(str(what or "").split())[:120]
    if not what:
        return {"found": False, "why": "Tell me what to look for."}
    shot = _capture()
    if not shot:
        return {"found": False, "why": "I couldn't capture the screen. Install pillow with pip install pillow."}
    data, (screen_w, screen_h), (img_w, img_h) = shot
    try:
        raw = ask_about_image(data, LOCATE.format(what=what))
    except Exception as e:  # noqa: BLE001
        return {"found": False, "why": str(e) or "The model couldn't read the screenshot."}
    match = re.search(r"\{.*\}", raw or "", re.S)
    try:
        seen = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        seen = None
    if not isinstance(seen, dict):
        return {"found": False, "why": "I couldn't read an answer about the screen."}
    try:
        confidence = float(seen.get("confidence"))
    except (TypeError, ValueError):
        return {"found": False, "why": "The answer didn't say how sure it was."}
    element = " ".join(str(seen.get("element") or "").split())[:80]
    risky = bool(seen.get("risky")) or bool(RISKY.search(f"{what} {element}"))
    if not seen.get("found"):
        return {"found": False, "element": element, "confidence": confidence, "risky": risky,
                "why": f"I can't see “{what}” on the screen."}
    box = seen.get("box")
    if (not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, (int, float)) for v in box)
            or box[2] <= 0 or box[3] <= 0 or box[0] < 0 or box[1] < 0
            or box[0] + box[2] > img_w + 1 or box[1] + box[3] > img_h + 1):
        return {"found": False, "element": element, "confidence": confidence, "risky": risky,
                "why": "The position given wasn't on the screenshot, so I won't use it."}
    scale_x, scale_y = screen_w / img_w, screen_h / img_h
    center = (round((box[0] + box[2] / 2) * scale_x), round((box[1] + box[3] / 2) * scale_y))
    return {"found": True, "element": element or what, "center": center, "confidence": confidence,
            "risky": risky, "why": ""}


def find_on_screen(what: str) -> str:
    """The tool: say where something is on the screen and how sure that is.
    Looks only; clicks nothing."""
    seen = locate(what)
    if not seen["found"]:
        return seen["why"]
    sure = "sure" if seen["confidence"] >= CONFIDENT else "not sure"
    x, y = seen["center"]
    return (f"“{seen['element']}” looks to be at ({x}, {y}) on your screen — {sure} "
            f"({round(seen['confidence'] * 100)}% by the model's own estimate)."
            + (" It looks like something that could pay, send, submit or delete, so I won't click it."
               if seen["risky"] else ""))


def click_on_screen(what: str) -> str:
    """The tool: click something on the screen. A page in LITTLE's own
    browser is clicked by its words there (its checks apply); anything else
    is found in a screenshot and clicked only when the model is sure, the
    target isn't risky, and you say yes."""
    from . import browser_agent
    from .permissions import Ask, confirm_fn

    what = " ".join(str(what or "").split())[:120]
    if not what:
        return "Tell me what to click."
    seen_page = browser_agent.observe()
    if "error" not in seen_page:
        names = [b["text"] for b in seen_page.get("buttons", [])] + [l["text"] for l in seen_page.get("links", [])]
        if any(what.lower() in n.lower() for n in names):
            ok, said = browser_agent.act({"do": "click", "target": what}, seen_page)
            return said + " (in my browser, by its words — no picture needed)"
    seen = locate(what)
    if not seen["found"]:
        return seen["why"] + " I didn't click anything."
    if seen["risky"]:
        return (f"“{seen['element']}” looks like it could pay, send, submit or delete. I don't click "
                f"that from a picture — click it yourself.")
    if seen["confidence"] < CONFIDENT:
        return (f"I think “{seen['element']}” is at {seen['center']}, but I'm only "
                f"{round(seen['confidence'] * 100)}% sure, so I didn't click. Point me to it more exactly.")
    x, y = seen["center"]
    ask = Ask(f"Click “{seen['element']}” at ({x}, {y}) on your screen?",
              action="Click on your screen", target=f"“{seen['element']}” at ({x}, {y})",
              details=f"Found in a screenshot, {round(seen['confidence'] * 100)}% sure.",
              consequence="A click from a picture can land on the wrong thing.",
              tone="caution", verb="Click", tool="click_on_screen")
    if confirm_fn(ask) is not True:
        return "You said no, so I didn't click."
    try:
        import pyautogui
        pyautogui.click(x, y)
    except Exception as e:  # noqa: BLE001
        log(f"screen click failed: {e}")
        return "I couldn't click: pyautogui isn't available or the screen is locked."
    return f"Clicked “{seen['element']}” at ({x}, {y})."
