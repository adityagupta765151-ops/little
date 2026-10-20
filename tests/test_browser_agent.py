"""Chapter 28 — the browser agent: observe, plan, act, verify.

A real headless browser against a small site served from this test:
navigation, forms, a page's own error messages, a slow page, the browser
missing, a step that can't be verified, and the gates — a submit asks
first, a password is never typed, a job board's apply button is never
pressed. The model that plans the steps is played by the test; everything
else is the real code.
"""
from __future__ import annotations

import http.server
import json
import threading
import time

import pytest

from jarvis import tools
from jarvis.ai import provider
from jarvis.routing.router import fast_route
from jarvis.tools import browser, browser_agent as agent
from jarvis.tools.registry import FUNCTIONS, TOOL_SCHEMAS

HITS: list[tuple[str, str]] = []

PAGES = {
    "/home.html": """<!doctype html><title>Home</title><h1>Welcome to Testville</h1>
      <p>Jobs and news for testers.</p><a href="/jobs.html">Jobs</a> <a href="/about.html">About us</a>
      <form action="/results.html" method="get"><label>Search <input name="q"></label>
      <button type="submit">Go</button></form>""",
    "/jobs.html": """<!doctype html><title>Jobs</title><h1>Open roles</h1>
      <a href="/job1.html">Python Intern</a><a href="/job2.html">Frontend Intern</a>""",
    "/results.html": """<!doctype html><title>Results</title><h1>Results</h1><p>2 roles match.</p>""",
    "/about.html": """<!doctype html><title>About</title><h1>About us</h1>""",
    "/form.html": """<!doctype html><title>Order form</title><h1>Order</h1>
      <form action="/submit" method="post">
        <label>Full name <input name="name" required></label>
        <label>Email <input name="email" type="email"></label>
        <label>Password <input name="pw" type="password"></label>
        <label>City <select name="city"><option>Delhi</option><option>Mumbai</option></select></label>
        <div id="err"></div>
        <button type="button" id="check">Check details</button>
        <button type="submit">Place order</button>
      </form>
      <script>
        document.getElementById('check').onclick = () => {
          const e = document.querySelector('[name=email]');
          if (!e.value) { e.setAttribute('aria-invalid', 'true');
            document.getElementById('err').innerHTML = '<p role="alert">Email is required</p>'; }
        };
      </script>""",
}


class Site(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: str, status: int = 200):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        HITS.append(("GET", self.path))
        path = self.path.split("?")[0]
        if path == "/slow.html":
            time.sleep(3)
            return self._send("<title>Slow</title>slow")
        if path in PAGES:
            return self._send(PAGES[path])
        return self._send("<title>Not found</title>Not found", 404)

    def do_POST(self):
        HITS.append(("POST", self.path))
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        return self._send("<!doctype html><title>Done</title><h1>Order placed</h1>")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    try:
        import playwright  # noqa: F401
    except ImportError:
        pytest.skip("Playwright isn't installed")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    patch = pytest.MonkeyPatch()
    patch.setattr(browser, "BROWSER_PROFILE", tmp_path_factory.mktemp("profile"))
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base
    finally:
        browser.close_browser()
        patch.undo()
        server.shutdown()


@pytest.fixture
def at(site):
    """Open a page of the test site in the real browser, then observe it."""
    HITS.clear()

    def go(path):
        ok, said = agent.act({"do": "open", "url": site + path})
        assert ok, said
        return agent.observe()
    return go


@pytest.fixture
def answers(monkeypatch):
    """Confirmations, answered by the test and recorded."""
    asked = {"asks": [], "answer": False}

    def confirm(ask):
        asked["asks"].append(ask)
        return asked["answer"]
    tools.set_confirm(confirm)
    yield asked
    tools.set_confirm(lambda _m: False)


# ================================================================= observe

class TestObserving:
    def test_what_the_page_is(self, at, site):
        seen = at("/home.html")
        assert seen["url"] == site + "/home.html" and seen["title"] == "Home"
        assert seen["headings"] == ["Welcome to Testville"]
        assert {"text": "Jobs", "href": site + "/jobs.html"} in seen["links"]
        assert {"text": "Go", "submit": True, "disabled": False} in seen["buttons"]
        assert seen["forms"][0]["fields"][0]["label"] == "Search"
        assert "Jobs and news for testers." in seen["text"]

    def test_described_for_you_and_the_model(self, at):
        at("/form.html")
        text = agent.look_at_page()
        assert text.startswith("Page: Order form — http://127.0.0.1")
        assert "Full name [text, required]" in text and "Password [password]" in text
        assert "Place order (submits)" in text

    def test_errors_the_page_shows(self, at, answers):
        at("/form.html")
        ok, _ = agent.act({"do": "click", "target": "Check details"})
        assert ok and answers["asks"] == [], "a plain button doesn't ask"
        seen = agent.observe()
        assert seen["errors"][0] == "Email is required"
        assert any(f["invalid"] for f in seen["forms"][0]["fields"])

    def test_nothing_open_starts_nothing(self, monkeypatch):
        monkeypatch.setattr(browser._worker, "page", None)
        monkeypatch.setattr(browser._worker, "run", lambda job: pytest.fail("the browser was used"))
        assert agent.observe() == {"error": "No page is open in my browser."}
        assert agent.look_at_page() == "No page is open in my browser."


# ================================================================ act+verify

class TestActingAndVerifying:
    def test_navigation(self, at, site):
        before = at("/home.html")
        step = {"do": "click", "target": "Jobs", "expect": {"url_contains": "/jobs.html"}}
        ok, said = agent.act(step)
        after = agent.observe()
        assert ok and said == "Clicked “Jobs”."
        assert agent.verify(step, before, after) == (True, "Verified: the address has “/jobs.html”.")
        back = {"do": "back"}
        assert agent.act(back)[0] and agent.verify(back, after, agent.observe())[0]

    def test_filling_is_checked_on_the_page(self, at):
        before = at("/form.html")
        step = {"do": "fill", "field": "Full name", "value": "Test Person"}
        assert agent.act(step) == (True, "Typed into “Full name”.")
        assert agent.verify(step, before, agent.observe()) == (True, "Verified: “Full name” holds what was typed.")
        choose = {"do": "select", "field": "City", "option": "Mumbai"}
        assert agent.act(choose) == (True, "Chose “Mumbai” in “City”.")

    def test_a_step_that_didnt_do_what_it_should_is_not_verified(self, at):
        before = at("/home.html")
        step = {"do": "click", "target": "About us", "expect": {"text_contains": "Order placed"}}
        assert agent.act(step)[0]
        verified, why = agent.verify(step, before, agent.observe())
        assert not verified and why == "Not verified: expected the page says “Order placed”."

    def test_a_field_that_isnt_there(self, at):
        at("/home.html")
        assert agent.act({"do": "fill", "field": "Surname", "value": "x"}) == \
            (False, "I couldn't find a field called “Surname”.")

    def test_a_slow_page_times_out_plainly(self, at, site, monkeypatch):
        at("/home.html")
        monkeypatch.setattr(agent, "ACTION_TIMEOUT_MS", 800)
        ok, said = agent.act({"do": "open", "url": site + "/slow.html"})
        assert not ok and said.startswith("The page took too long to respond.")

    def test_no_browser_at_all(self, monkeypatch):
        monkeypatch.setattr(browser._worker, "page", None)

        def cannot():
            raise RuntimeError(browser.SETUP_HINT)
        monkeypatch.setattr(browser._worker, "current", cannot)
        monkeypatch.setattr(browser._worker, "run", lambda job: job())
        ok, said = agent.act({"do": "open", "url": "http://127.0.0.1:9/"})
        assert not ok and said == browser.SETUP_HINT

    @pytest.mark.parametrize("step,why", [
        ({"do": "open", "url": "javascript:alert(1)"}, "I only open web addresses"),
        ({"do": "open", "url": "file:///etc/passwd"}, "I only open web addresses"),
        ({"do": "press", "key": "Delete"}, "I can press Enter"),
        ({"do": "hover", "target": "x"}, "I can open, click, fill"),
        ({"do": "click"}, "A click needs the words"),
    ])
    def test_steps_outside_the_set_are_refused(self, at, step, why):
        at("/home.html")
        ok, said = agent.act(step)
        assert not ok and said.startswith(why)


# =================================================================== gates

class TestAnEarlierSlowPage:
    """Found by the Chapter 46 regression: a page that timed out can finish
    loading over the next one. Opening only reads, so it's tried again."""

    class Page:
        def __init__(self, error):
            self.error, self.visits = error, []

        def set_default_timeout(self, _ms):
            pass

        def goto(self, url, **_k):
            self.visits.append(url)
            if self.error and len(self.visits) == 1:
                raise RuntimeError(self.error)

        def title(self):
            return "Home"

    def test_an_interrupted_open_is_tried_once_more(self, monkeypatch):
        page = self.Page('Page.goto: Navigation to "a" is interrupted by another navigation to "b"')
        monkeypatch.setattr(browser._worker, "current", lambda: page)
        assert agent._do({"do": "open", "url": "http://x/"}) == "Opened Home."
        assert page.visits == ["http://x/", "http://x/"]

    def test_other_failures_are_not(self, monkeypatch):
        page = self.Page("net::ERR_NAME_NOT_RESOLVED")
        monkeypatch.setattr(browser._worker, "current", lambda: page)
        with pytest.raises(RuntimeError):
            agent._do({"do": "open", "url": "http://x/"})
        assert page.visits == ["http://x/"]


class TestTheGates:
    def test_a_submit_asks_and_no_means_nothing_happens(self, at, answers):
        at("/form.html")
        ok, said = agent.act({"do": "click", "target": "Place order"})
        assert (ok, said) == (False, "You said no, so I didn't.")
        ask = answers["asks"][0]
        assert ask.parts()["action"] == "Click a button on a web page" and "Place order" in ask.parts()["target"]
        assert not any(method == "POST" for method, _ in HITS)

    def test_a_button_that_submits_asks_whatever_its_words(self, at, answers):
        """"Go" says nothing about submitting, but it submits the form."""
        at("/home.html")
        assert agent.act({"do": "click", "target": "Go"}) == (False, "You said no, so I didn't.")
        assert answers["asks"] and not any(path.startswith("/results.html") for _, path in HITS)

    def test_yes_does_it(self, at, answers):
        at("/form.html")
        agent.act({"do": "fill", "field": "Full name", "value": "Test Person"})   # the form requires it
        answers["answer"] = True
        assert agent.act({"do": "click", "target": "Place order"}) == (True, "Clicked “Place order”.")
        assert ("POST", "/submit") in HITS and agent.observe()["title"] == "Done"

    def test_enter_on_a_form_asks(self, at, answers):
        at("/home.html")
        agent.act({"do": "fill", "field": "Search", "value": "python"})
        assert agent.act({"do": "press", "key": "Enter"}) == (False, "You said no, so I didn't.")
        assert answers["asks"][0].parts()["action"] == "Press something on a web page"

    @pytest.mark.parametrize("field", ["Password", "OTP", "Card number", "CVV"])
    def test_secrets_are_never_typed_asked_or_not(self, at, answers, field):
        at("/form.html")
        answers["answer"] = True
        ok, said = agent.act({"do": "fill", "field": field, "value": "hunter2"})
        assert not ok and said.startswith("That field takes a password, a one-time code or card details.")
        assert answers["asks"] == [] and all(not f["filled"] for f in agent.observe()["forms"][0]["fields"]
                                              if f["type"] == "password")

    def test_a_job_boards_apply_button_is_never_pressed(self, at, answers, monkeypatch):
        at("/form.html")
        agent.act({"do": "fill", "field": "Full name", "value": "Test Person"})
        monkeypatch.setattr(agent, "NO_AUTOMATION_HOSTS", ("127.0.0.1",))   # on any port
        answers["answer"] = True
        ok, said = agent.act({"do": "click", "target": "Place order"})
        assert not ok and "doesn't allow automated applying or posting" in said
        assert answers["asks"] == [] and not any(m == "POST" for m, _ in HITS)


# ==================================================================== plan

@pytest.fixture
def planner(monkeypatch):
    """The model, answering the next step from a script."""
    script: list = []
    prompts: list[str] = []

    def ask(prompt, *a, **k):
        prompts.append(prompt)
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)
    monkeypatch.setattr(provider, "ask_text", ask)
    return script, prompts


class TestTheLoop:
    def test_a_goal_reached_step_by_step_each_verified(self, site, planner, answers):
        script, prompts = planner
        answers["answer"] = True
        script += [{"do": "open", "url": site + "/home.html"},
                   {"do": "fill", "field": "Search", "value": "python"},
                   {"do": "click", "target": "Go", "expect": {"url_contains": "q=python"}},
                   {"done": True, "answer": "2 roles match python."}]
        out = agent.run_task("search the test site for python")
        lines = out.splitlines()
        assert lines[0] == "BROWSER TASK"
        assert lines[1].startswith("1. open " + site + "/home.html — Verified: the page at 127.0.0.1")
        assert lines[2] == "2. fill “Search” — Verified: “Search” holds what was typed."
        assert lines[3] == "3. click “Go” — Verified: the address has “q=python”."
        assert lines[-1] == "2 roles match python."
        assert "Goal: search the test site for python" in prompts[1] and "Search [text" in prompts[1]
        assert "1. open" in prompts[2], "each step sees what was done"

    def test_it_stops_at_a_step_it_cant_verify(self, site, planner):
        script, _ = planner
        script += [{"do": "open", "url": site + "/home.html"},
                   {"do": "click", "target": "About us", "expect": {"text_contains": "Careers"}},
                   {"do": "click", "target": "never reached"}]
        out = agent.run_task("find careers")
        assert "2. click “About us” — Not verified: expected the page says “Careers”." in out
        assert out.endswith("I stopped at step 2: it didn't do what it should have.")
        assert len(script) == 1, "nothing after the failed step"

    def test_a_refused_step_stops_it(self, site, planner, answers):
        script, _ = planner
        script += [{"do": "open", "url": site + "/form.html"},
                   {"do": "click", "target": "Place order"}]
        out = agent.run_task("order something")
        assert out.endswith("I stopped at step 2: You said no, so I didn't.")
        assert not any(m == "POST" for m, _ in HITS)

    @pytest.mark.parametrize("reply,why", [
        ("I think you should click Jobs", "The model didn't answer with a step."),
        ("{not json", "The model didn't answer with a step."),
        ('{"do": ', "The model didn't answer with a step."),
    ])
    def test_a_reply_that_isnt_a_step(self, site, planner, reply, why):
        script, _ = planner
        script.append(reply)
        assert agent.run_task("anything") == f"I stopped: {why}"

    def test_the_model_unreachable(self, planner):
        script, _ = planner
        script.append(RuntimeError("I can't reach the internet right now."))
        assert agent.run_task("anything") == \
            "I stopped: the model couldn't be reached (I can't reach the internet right now.)."

    def test_at_most_eight_steps(self, site, planner, monkeypatch):
        script, _ = planner
        script += [{"do": "open", "url": site + "/home.html"}] + \
                  [{"do": "click", "target": t} for t in ["Jobs", "Python Intern"]] + \
                  [{"do": "open", "url": site + p} for p in ["/home.html", "/jobs.html", "/about.html",
                                                              "/home.html", "/jobs.html", "/about.html"]]
        out = agent.run_task("wander")
        assert out.endswith("I stopped after 8 steps without reaching the goal.")
        assert out.count("\n") >= 9

    def test_an_empty_goal(self):
        assert agent.run_task("  ") == "Tell me what to do in the browser."


class TestReachingIt:
    def test_the_tools_and_their_words(self):
        assert FUNCTIONS["look_at_page"] is agent.look_at_page and FUNCTIONS["browser_task"] is agent.run_task
        described = {t["name"]: t["description"] for t in TOOL_SCHEMAS}
        assert "never opens a browser that isn't open" in described["look_at_page"]
        assert "never types passwords" in described["browser_task"]

    @pytest.mark.parametrize("command", ["what's on this page", "describe the page", "inspect this web page"])
    def test_what_is_on_the_page(self, command, monkeypatch):
        monkeypatch.setattr(agent, "look_at_page", lambda: "<page>")
        assert fast_route(command) == "<page>"

    def test_a_goal_in_the_browser(self, monkeypatch):
        monkeypatch.setattr(agent, "run_task", lambda goal: f"<{goal}>")
        assert fast_route("In the browser, find the Python internship on Testville") == \
            "<find the Python internship on Testville>"
