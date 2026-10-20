"""The local dashboard at http://localhost:3000/jobs

Served by Python's own http.server on a background thread, so there is no
Node, no npm and no build step. The page asks /api/state for everything
and redraws; JARVIS never pushes to it.
"""
from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..app.config import APP_DIR, ASSISTANT_NAME, log
from . import normalise, store
from .resume import load_profile

UI_DIR = APP_DIR / "ui" / "jobs"
PORT = 3000

# The window's design system, shared so the dashboard looks like the same
# app. Exactly these two files, by name — nothing else under ui/ is served.
SHARED_CSS = {
    "/css/tokens.css": APP_DIR / "ui" / "css" / "tokens.css",
    "/css/base.css": APP_DIR / "ui" / "css" / "base.css",
}

# The app's own icon, for the browser tab. Without it a real browser asks
# for /favicon.ico anyway and logs the 404 as an error.
ICON = APP_DIR / "little.ico"

_server: ThreadingHTTPServer | None = None


def state() -> dict:
    """Everything the page shows, read fresh from the database."""
    counts = store.counts()
    jobs = store.top_jobs(limit=60)
    # The page shows an age, not a date, so the phrasing is worked out here
    # rather than reimplemented in JavaScript against a different calendar.
    for job in jobs:
        posted = job.get("posted_at") or ""
        job["posted_phrase"] = normalise.age_phrase(posted)
        job["stale"] = normalise.is_stale(posted)
    profile = load_profile()
    person = profile.get("candidate", {})

    return {
        "assistant": ASSISTANT_NAME,
        "counts": counts,
        "jobs": jobs,
        "applications": store.applications(limit=40),
        "audit": store.audit_trail(limit=60),
        "missing_skills": store.missing_skill_counts(12),
        "resume": {
            "name": person.get("name", ""),
            "file": profile.get("source_file", ""),
            "skills": person.get("skills", []),
            "degree": person.get("degree", ""),
            "graduation_year": person.get("graduation_year", ""),
            "location": person.get("location", ""),
            "projects": person.get("projects", []),
            "roles": profile.get("preferences", {}).get("roles", []),
        },
    }


# The page shows text that came from job boards. If any of it were ever
# written as markup by mistake, this stops it running: only the page's own
# script files may execute, nothing inline, and no other site can frame it.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def end_headers(self):
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def _for_this_computer(self) -> bool:
        """Chapter 48: only a page this computer addressed as localhost may
        ask. A website that points its own name at 127.0.0.1 (DNS
        rebinding) would otherwise be able to read /api/state — your name,
        skills and applications. Its requests carry its own name as Host."""
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]
        return host in {f"localhost:{port}", f"127.0.0.1:{port}", "localhost", "127.0.0.1"}

    def do_GET(self):  # noqa: N802
        if not self._for_this_computer():
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if self.path.startswith("/api/state"):
            return self._json(state())
        if self.path in SHARED_CSS:
            return self._file(SHARED_CSS[self.path], "text/css; charset=utf-8")
        if self.path == "/favicon.ico":
            if ICON.is_file():
                return self._file(ICON, "image/x-icon")
            self.send_response(204)          # no icon: nothing, rather than an error
            self.end_headers()
            return None
        if self.path in ("/", "/jobs", "/jobs/"):
            self.path = "/index.html"
        return super().do_GET()

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, kind: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        """Keep request noise out of the terminal; it goes to jarvis.log."""
        log("dashboard: " + (fmt % args))


def start() -> str:
    """Start the dashboard if it isn't already running."""
    global _server
    if _server is not None:
        return f"The dashboard is already at http://localhost:{PORT}/jobs"

    if not (UI_DIR / "index.html").exists():
        return f"The dashboard files are missing from {UI_DIR}."

    try:
        _server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        log(f"dashboard bind failed: {e}")
        return (f"Port {PORT} is already in use by something else. "
                f"Close it, or the dashboard can't start.")

    threading.Thread(target=_server.serve_forever, daemon=True).start()
    log(f"dashboard listening on {PORT}")
    return f"Dashboard running at http://localhost:{PORT}/jobs"


def stop() -> str:
    global _server
    if _server is None:
        return "The dashboard isn't running."
    _server.shutdown()
    _server.server_close()
    _server = None
    return "Dashboard stopped."


def open_dashboard() -> str:
    """Start it if needed, then show it."""
    import webbrowser

    message = start()
    if "running" in message or "already" in message:
        webbrowser.open(f"http://localhost:{PORT}/jobs")
    return message
