"""Rendering the panel in a real browser engine, for the tests that need to
see it rather than read it.

Uses Playwright's own Chromium, else an installed Chrome or Edge — the same
order the app itself tries. Where there's no browser at all, callers skip.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "ui" / "index.html"


# What open_panel returns when there's no browser to render with. A check
# may legitimately return None, so None can't mean "skip".
NO_BROWSER = object()


def available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
        return True
    except ImportError:
        return False


async def _launch(pw):
    for channel in (None, "chrome", "msedge"):
        try:
            return await pw.chromium.launch(**({"channel": channel} if channel else {}))
        except Exception:  # noqa: BLE001
            continue
    return None


async def _launch_full(pw):
    """A full browser, the way Chrome and Edge run on your computer — it
    asks for things the trimmed headless build skips, like a page's icon."""
    for channel in ("chromium", "chrome", "msedge"):
        try:
            return await pw.chromium.launch(channel=channel)
        except Exception:  # noqa: BLE001
            continue
    return await _launch(pw)


def bridge(poll: dict | None = None) -> str:
    """A stand-in for pywebview's bridge. poll() returns `poll` once, then
    nothing new; the ready event fires on load, as pywebview's does.

    Every call the page makes is recorded in window.__calls. A test can make
    a confirmation arrive later by setting window.__nextAsk = {id, message};
    the next poll delivers it, as Python's would. window.__queue holds more
    payloads, one per poll, in order; window.__since is the task version the
    page last asked from."""
    return """
      window.__calls = [];
      window.__nextAsk = null;
      window.__queue = [];
      window.__since = undefined;
      let first = %s;
      window.pywebview = { api: {
        poll: async (since) => {
          window.__since = since;
          const out = first || (window.__queue.length ? window.__queue.shift() : {});
          first = null;
          if (window.__nextAsk) { out.ask = window.__nextAsk; window.__nextAsk = null; }
          return out; },
        confirm_reply: async (id, ok) => window.__calls.push(["confirm_reply", id, ok]),
        send: async (t) => window.__calls.push(["send", t]),
        toggle: async () => { window.__calls.push(["toggle"]); },
        control: async (a) => { window.__calls.push(["control", a]);
                                return a === "mute" ? "Unmute voice" : ""; },
        // Chat's actions: recorded, answering with window.__answers[name] or "".
        speak: async (id) => { window.__calls.push(["speak", id]); return (window.__answers || {}).speak || ""; },
        save: async (id) => { window.__calls.push(["save", id]); return (window.__answers || {}).save || ""; },
        regenerate: async (id) => { window.__calls.push(["regenerate", id]);
                                    return (window.__answers || {}).regenerate || ""; },
        cancel: async (id) => { window.__calls.push(["cancel", id]); return (window.__answers || {}).cancel || ""; },
        // Jobs: jobs() answers window.__jobs, or an empty store with no resume.
        jobs: async () => { window.__calls.push(["jobs"]); return window.__jobs || {
          jobs: [], counts: {jobs_total: 0, jobs_today: 0, applied: 0, needs_action: 0},
          missing_skills: [], resume: {name: "", file: "", roles: [], ready: false}}; },
        job: async (id, action) => { window.__calls.push(["job", id, action]);
                                     return (window.__answers || {}).job || ""; },
        open_posting: async (id) => { window.__calls.push(["open_posting", id]);
                                      return (window.__answers || {}).open_posting || ""; },
        // Resume: resume() answers window.__resume, or no resume read yet.
        // The others answer window.__answers[name], else a plain success.
        resume: async () => { window.__calls.push(["resume"]); return window.__resume || {
          ready: false, candidate: {name: "", email: "", phone: "", location: "", education: [],
            graduation_year: "", degree: "", skills: [], languages: [], frameworks: [], projects: [],
            experience: [], internships: [], certifications: []},
          file: "", file_found: false, scanned_at: "",
          preferences: {roles: [], locations: [], work_modes: [], countries: [], employment_types: []},
          yours: [], choices: {work_modes: ["remote", "hybrid", "onsite"],
            employment_types: ["internship", "contract", "part-time", "temporary", "full-time"]},
          limits: {items: 12, chars: 60, roles_searched: 3}, home_country: "",
          suggestions: [], jobs: [], gaps: [], running: null}; },
        choose_resume: async () => { window.__calls.push(["choose_resume"]);
          return (window.__answers || {}).choose_resume || {token: 1, name: "resume.pdf"}; },
        scan_picked: async (t) => { window.__calls.push(["scan_picked", t]);
          return (window.__answers || {}).scan_picked || {task: 1}; },
        save_preferences: async (v) => { window.__calls.push(["save_preferences", v]);
          return (window.__answers || {}).save_preferences || {preferences: v, yours: Object.keys(v), message: "Saved."}; },
        resume_action: async (a, j) => { window.__calls.push(["resume_action", a, j]);
          return (window.__answers || {}).resume_action || {task: 1}; },
        // Projects and Memory: window.__projects / window.__memory, else empty.
        projects: async () => { window.__calls.push(["projects"]); return window.__projects || {
          ready: false, file: "", projects: [], not_in_a_line: ["status", "AI/ML parts", "backend",
          "frontend", "database"]}; },
        open_project_link: async (p, l) => { window.__calls.push(["open_project_link", p, l]);
          return (window.__answers || {}).open_project_link || ""; },
        memory_view: async () => { window.__calls.push(["memory_view"]); return window.__memory || {
          facts: [], contacts: [], log: {count: 0, keep: 200, recent: []},
          resume: {ready: false, name: "", skills: 0, projects: 0}, jobs: {total: 0, applied: 0},
          folder: "D:/little/memory"}; },
        forget_fact: async (k, s, p) => { window.__calls.push(s ? ["forget_fact", k, s, p] : ["forget_fact", k]);
          return (window.__answers || {}).forget_fact || {message: "Forgotten."}; },
        remove_contact: async (n) => { window.__calls.push(["remove_contact", n]);
          return (window.__answers || {}).remove_contact || {message: "Removed."}; },
        clear_log: async () => { window.__calls.push(["clear_log"]);
          return (window.__answers || {}).clear_log || {message: "Cleared."}; },
        // System: window.__system / window.__health, else a bare setup.
        system: async () => { window.__calls.push(["system"]); return window.__system || {
          groups: [], env: {path: "D:/little/.env", exists: true}, mics: [], asks_first: [],
          tools: 0, audit: [], muted: false, listening: false}; },
        health: async (live) => { window.__calls.push(["health", live]);
          return window.__health || {checks: []}; },
        test_voice: async () => { window.__calls.push(["test_voice"]);
          return (window.__answers || {}).test_voice || ""; },
        // Tools: window.__tools, else none.
        tools: async () => { window.__calls.push(["tools"]); return window.__tools || {tools: []}; } } };
      window.addEventListener("load", () => window.dispatchEvent(new Event("pywebviewready")));
    """ % json.dumps(poll)


def open_panel(check, script: str = "", wait_ms: int = 600, viewport=(1280, 800),
               route: str | None = None):
    """Load the panel, run `check(page)` (async), return what it returns.
    `route` opens a section by its address, as #/route.
    Returns (NO_BROWSER, []) when no browser could be launched."""
    from playwright.async_api import async_playwright

    async def go():
        async with async_playwright() as pw:
            browser = await _launch(pw)
            if browser is None:
                return NO_BROWSER, []
            page = await browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            await page.add_init_script(script or bridge())
            await page.goto(PANEL.as_uri() + (f"#/{route}" if route else ""))
            await page.wait_for_timeout(wait_ms)
            try:
                return await check(page), errors
            finally:
                await browser.close()

    return asyncio.run(go())
