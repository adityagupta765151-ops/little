"""The two ways the confirmation gate could be walked past, and proof they're shut.

1. Text reaching the panel as markup. Reminder text comes from the model, and
   the model reads web pages. The panel used to write it with innerHTML, so a
   reminder whose text was an <img> tag ran code inside the window — and code
   there can answer a confirmation. It was reproduced: a planted tag approved
   "Send this to Rahul?" with no click.

2. A dialog that opened on Yes. An Enter meant for the command box, pressed
   as the dialog appeared, approved whatever it was asking.

The static tests keep the patterns out of the code. The render tests replay
the original attack against the real page and need a browser; they skip
where there isn't one.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UI_SCRIPTS = sorted((ROOT / "ui").rglob("*.js"))
ATTACK = '<img src=x onerror="window.__ran=1;window.pywebview&&window.pywebview.api.confirm_reply(7,true)">'


def _code(path: Path) -> str:
    """The script with its comments removed, so a comment that names a
    pattern doesn't count as using it."""
    text = path.read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


# ------------------------------------------------------------------ static

class TestNothingIsWrittenAsMarkup:
    def test_there_are_scripts_to_check(self):
        assert UI_SCRIPTS, "no UI scripts found"

    @pytest.mark.parametrize("script", UI_SCRIPTS, ids=lambda p: str(p.relative_to(ROOT)))
    def test_no_script_writes_html_strings(self, script):
        code = _code(script)
        for pattern in (r"\.innerHTML\b", r"\.outerHTML\s*=", r"insertAdjacentHTML",
                        r"document\.write"):
            assert not re.search(pattern, code), \
                f"{script.name} uses {pattern} — build elements and set textContent instead"

    @pytest.mark.parametrize("script", UI_SCRIPTS, ids=lambda p: str(p.relative_to(ROOT)))
    def test_every_link_goes_through_safe_url(self, script):
        """A job board's link is outside text too. Only http and https may
        become a link, so a posting can't hand the page javascript:."""
        code = _code(script)
        for line in re.findall(r"\.href\s*=\s*([^;]+);", code):
            assert line.strip() == "href" or line.strip().startswith("safeUrl("), \
                f"{script.name} sets a link without safeUrl: {line.strip()}"
        if re.search(r"\.href\s*=", code):
            assert "function safeUrl" in code


class TestConfirmationsOpenOnNo:
    def test_the_panel_dialog_focuses_cancel(self):
        code = _code(ROOT / "ui" / "app.js")
        show = code[code.index("function showAsk"):code.index("function answerAsk")]
        assert '$("askNo").focus()' in show
        assert '$("askYes").focus()' not in show

    def test_yes_is_not_clickable_the_moment_the_dialog_opens(self):
        code = _code(ROOT / "ui" / "app.js")
        show = code[code.index("function showAsk"):code.index("function answerAsk")]
        assert "yes.disabled = true" in show
        assert "ARM_MS" in show

    def test_the_plain_window_dialog_defaults_to_no(self):
        """The Tk fallback asks through messagebox.askyesno, which defaults
        to Yes unless told otherwise."""
        source = (ROOT / "launcher.py").read_text(encoding="utf-8")
        call = source[source.index("messagebox.askyesno("):]
        call = call[:call.index(")") + 1]
        assert "default=messagebox.NO" in call

    def test_the_terminal_prompt_already_defaults_to_no(self):
        from jarvis.tools import permissions
        import builtins
        original = builtins.input
        try:
            builtins.input = lambda _prompt: ""          # just pressing Enter
            assert permissions._ask_on_the_terminal("Delete it?") is False
        finally:
            builtins.input = original


class TestTheDashboardRefusesInlineCode:
    """The job dashboard shows text from job boards in your normal browser.
    Its server tells the browser to run only the page's own script file."""

    @pytest.fixture
    def served(self):
        from jarvis.jobs import dashboard
        server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{server.server_address[1]}"
        server.shutdown()
        server.server_close()

    @pytest.mark.parametrize("path", ["/jobs", "/api/state", "/app.js"])
    def test_every_response_carries_the_policy(self, served, path):
        with urllib.request.urlopen(served + path, timeout=5) as response:
            policy = response.headers.get("Content-Security-Policy", "")
            assert "script-src 'self'" in policy
            assert "frame-ancestors 'none'" in policy
            assert response.headers.get("X-Content-Type-Options") == "nosniff"


# ------------------------------------------------------------------ render

def _browser_or_skip(pw):
    """Playwright's own Chromium, else the installed Chrome or Edge, as the
    app itself does. No browser at all: skip rather than fail."""
    async def launch():
        for channel in (None, "chrome", "msedge"):
            try:
                return await pw.chromium.launch(**({"channel": channel} if channel else {}))
            except Exception:  # noqa: BLE001
                continue
        return None
    return launch()


def _run(coro):
    return asyncio.run(coro)


def _panel_stub(reminders=None, tools=None, plan=None, workspace="C:/w", model="m", ask=True):
    stats = {
        "identity": {"name": "LITTLE", "call": "Little"},
        "system": {"available": False},
        "session": {"uptime": "0", "commands": 0, "tools": 0, "os": "Windows 11"},
        "voice": {"mic": "on", "speech": "on", "voice": "Neerja", "lang": "en-IN", "model": model},
        "tools": tools or [], "reminders": reminders or [], "plan": plan,
        "browser": "closed", "contacts": 0, "workspace": workspace,
    }
    pending = {"id": 7, "message": "Send this to Rahul?\n\nhello"} if ask else None
    return """
      window.__calls = [];
      const stats = %s;
      let pending = %s;
      window.pywebview = { api: {
        poll: async () => { const out = {status: "listening", lines: [], stats, ask: pending};
                            pending = null; return out; },
        confirm_reply: async (id, ok) => window.__calls.push(["confirm_reply", id, ok]),
        send: async (t) => window.__calls.push(["send", t]),
        toggle: async () => {}, control: async () => "" } };
      // As pywebview does: the API is ready once the page has loaded.
      window.addEventListener("load", () => window.dispatchEvent(new Event("pywebviewready")));
    """ % (json.dumps(stats), json.dumps(pending))


@pytest.fixture(scope="module")
def playwright_available():
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        pytest.skip("Playwright isn't installed")


class TestTheOriginalAttack:
    """Replays what was reproduced, against the real panel."""

    def _open(self, script, after=None, wait_ms=900):
        from playwright.async_api import async_playwright

        async def go():
            async with async_playwright() as pw:
                browser = await _browser_or_skip(pw)
                if browser is None:
                    return None
                page = await browser.new_page()
                await page.add_init_script(script)
                await page.goto((ROOT / "ui" / "index.html").as_uri())
                await page.wait_for_timeout(wait_ms)
                result = await after(page)
                await browser.close()
                return result
        result = _run(go())
        if result is None:
            pytest.skip("no browser to render the panel with")
        return result

    def test_a_planted_tag_in_a_reminder_can_no_longer_approve_anything(self, playwright_available):
        async def check(page):
            return {
                "calls": await page.evaluate("window.__calls"),
                "ran": await page.evaluate("window.__ran || 0"),
                "shown": await page.inner_text("#remList"),
                "images": await page.evaluate("document.querySelectorAll('#remList img').length"),
            }
        seen = self._open(_panel_stub(reminders=[{"text": ATTACK, "at": "20:00"}]), check)
        assert seen["calls"] == [], f"the page answered on its own: {seen['calls']}"
        assert seen["ran"] == 0
        assert seen["images"] == 0
        assert "<img" in seen["shown"]            # shown as the text it is

    @pytest.mark.parametrize("field", ["tools", "plan", "workspace", "model"])
    def test_no_other_field_runs_as_markup_either(self, playwright_available, field):
        values = {
            "tools": {"tools": [{"name": ATTACK, "ms": 3}]},
            "plan": {"plan": {"at": 1, "steps": [ATTACK], "done": []}},
            "workspace": {"workspace": "C:/" + ATTACK},
            "model": {"model": ATTACK},
        }[field]

        async def check(page):
            return {"calls": await page.evaluate("window.__calls"),
                    "ran": await page.evaluate("window.__ran || 0")}
        seen = self._open(_panel_stub(**values), check)
        assert seen == {"calls": [], "ran": 0}

    def test_the_dialog_opens_on_no_with_yes_not_yet_armed(self, playwright_available):
        async def check(page):
            return {"focus": await page.evaluate("document.activeElement.id"),
                    "yes_disabled": await page.evaluate("document.getElementById('askYes').disabled")}
        seen = self._open(_panel_stub(), check, wait_ms=300)
        assert seen["focus"] == "askNo"
        assert seen["yes_disabled"] is True

    def test_an_enter_as_the_dialog_appears_cancels_rather_than_approves(self, playwright_available):
        async def check(page):
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(100)
            return await page.evaluate("window.__calls")
        calls = self._open(_panel_stub(), check, wait_ms=300)
        assert ["confirm_reply", 7, True] not in calls
        assert calls == [["confirm_reply", 7, False]]

    def test_yes_still_works_when_you_mean_it(self, playwright_available):
        async def check(page):
            await page.wait_for_timeout(900)            # past the arming delay
            await page.click("#askYes")
            await page.wait_for_timeout(100)
            return await page.evaluate("window.__calls")
        calls = self._open(_panel_stub(), check, wait_ms=300)
        assert calls == [["confirm_reply", 7, True]]


class TestTheDashboardLinks:
    def test_only_web_addresses_become_links(self, playwright_available, tmp_path, monkeypatch):
        from playwright.async_api import async_playwright

        from jarvis.jobs import dashboard

        jobs = [
            {"job_id": "a", "company": "Safe Co", "title": "Engineer", "url": "https://example.com/job",
             "status": "FOUND", "match_score": 80, "skills_matched": [], "skills_missing": []},
            {"job_id": "b", "company": "Evil Co", "title": "Engineer", "url": "javascript:window.__ran=1",
             "status": "FOUND", "match_score": 79, "skills_matched": [], "skills_missing": []},
        ]
        monkeypatch.setattr(dashboard, "state", lambda: {
            "assistant": "LITTLE", "counts": {}, "jobs": jobs, "applications": [], "audit": [],
            "missing_skills": [], "resume": {"name": "", "skills": [], "roles": [], "projects": [],
                                             "file": "", "degree": "", "graduation_year": "",
                                             "location": ""}})
        server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}/jobs"

        async def go():
            async with async_playwright() as pw:
                browser = await _browser_or_skip(pw)
                if browser is None:
                    return None
                page = await browser.new_page()
                await page.goto(url)
                await page.wait_for_timeout(900)
                result = await page.evaluate("""() => ({
                  hrefs: [...document.querySelectorAll('#dashCards a')].map(a => a.href),
                  cards: document.querySelectorAll('#dashCards .card').length })""")
                await browser.close()
                return result
        try:
            seen = _run(go())
        finally:
            server.shutdown()
            server.server_close()
        if seen is None:
            pytest.skip("no browser to render the dashboard with")
        assert seen["cards"] == 2, "the page didn't render under its security policy"
        assert seen["hrefs"] == ["https://example.com/job"]
