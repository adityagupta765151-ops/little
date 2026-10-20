"""One door to the model.

Everything that talks to Gemini goes through here, so retries, model
fallback and error wording live in one place. brain.py adds tools and
history on top; screen.py and browser.py just ask a question.
"""
from __future__ import annotations

import time

import requests

from ..app.config import API_KEY, MODEL, log

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

RETRIES = 4  # per model, with doubling waits
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash-lite"]

_session = requests.Session()  # reused connection, noticeably faster
_current_model = MODEL          # the strong tier's model, as it last worked
_current_fast = None            # the fast tier's (Chapter 43); set below


def call_gemini(payload: dict) -> dict:
    """Send a request, waiting out the busy periods the free tier has.

    Falls back to a lighter model if the main one stays busy or is gone.
    """
    global _current_model, _current_fast
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing. Put it in your .env file.")
    # Chapter 42: no route to the internet a moment ago — don't wait out the
    # same retries on every command.
    from ..app import recovery
    held = recovery.offline_hold()
    if held:
        raise RuntimeError(held)

    # Chapter 43: the tier this request was asked for, and its chain.
    from . import models as tiers
    tier = tiers.current()
    models = tiers.chain(tier)
    last_status = None
    offline = 0
    started = time.monotonic()

    for model in models:
        delay = 2.0
        for _ in range(RETRIES):
            try:
                response = _session.post(
                    ENDPOINT.format(model=model),
                    headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"},
                    json=payload,
                    timeout=120,
                )
            except requests.RequestException as e:
                # No route to Google at all: retrying other models won't help.
                log(f"network error: {e}")
                offline += 1
                if offline >= 2:
                    recovery.went_offline()
                    raise RuntimeError("I can't reach the internet right now.") from e
                time.sleep(2)
                continue

            if response.status_code == 200:
                recovery.back_online()
                was = _current_fast if tier == "fast" else _current_model
                if model != was:
                    log(f"fell back to {model}")
                    recovery.note("model", f"{was} was busy or gone, so I switched to {model}", True)
                    if tier == "fast":
                        _current_fast = model
                    else:
                        _current_model = model
                from ..app import latency
                latency.record(f"model_{tier}", (time.monotonic() - started) * 1000)
                return response.json()

            last_status = response.status_code
            log(f"gemini {response.status_code} on {model}: {response.text[:300]}")

            if response.status_code in (401, 403):
                raise RuntimeError("My API key was rejected. Check GEMINI_API_KEY in .env.")
            if response.status_code == 404:
                break  # wrong model name, try the next one straight away
            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"The model returned an error ({response.status_code}).")

    if last_status == 429:
        raise RuntimeError("I've hit the free tier rate limit. Give it a minute.")
    raise RuntimeError("Google's servers are busy right now. Try again in a moment.")


def _fast_model() -> str:
    from .models import FAST
    return FAST


_current_fast = _fast_model()


def _text_of(data: dict) -> str:
    candidates = data.get("candidates")
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return " ".join(p["text"] for p in parts if "text" in p).strip()


def ask_text(prompt: str, system: str | None = None,
             empty: str = "I couldn't get an answer for that.") -> str:
    """One question, one text answer. No tools, no history. `empty` is what
    comes back when the model says nothing — pass "" to tell that apart."""
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    return _text_of(call_gemini(payload)) or empty


def ask_about_image(image_png: bytes, question: str) -> str:
    """Show the model a picture and ask about it."""
    import base64
    payload = {"contents": [{
        "role": "user",
        "parts": [
            {"inline_data": {"mime_type": "image/png",
                             "data": base64.b64encode(image_png).decode()}},
            {"text": question},
        ],
    }]}
    return _text_of(call_gemini(payload)) or "I couldn't read that image."
