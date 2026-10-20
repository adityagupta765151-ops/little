"""The shell (UI-2): nine sections, one navigation, and a command palette.

What has to hold:
  * every section can be reached with the keyboard alone, and focus lands
    somewhere that says where you are;
  * the palette is fully keyboard-driven, shows typed text as text, and
    always gives way to a confirmation;
  * every button on a section that isn't built yet does something real —
    a command the fast lane answers on this computer, never a model call
    and never a mock;
  * the page talks to Python in exactly one place.

The static tests run anywhere. The render tests need a browser engine and
skip where there isn't one.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import _ui

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
HTML = (UI / "index.html").read_text(encoding="utf-8")
ROUTER = (UI / "js" / "core" / "router.js").read_text(encoding="utf-8")
SECTIONS = (UI / "js" / "views" / "sections.js").read_text(encoding="utf-8")
HOME_JS = (UI / "js" / "views" / "home.js").read_text(encoding="utf-8")

ROUTES = re.findall(r'\{ id: "(\w+)",\s+title: "(\w+)"', ROUTER)
IDS = [route for route, _ in ROUTES]
# Sections that still say what's coming (the rest are built).
SOON = re.findall(r'class="view soon" data-view="(\w+)"', HTML)
TITLES = dict(ROUTES)
# Every command a button sends: the sections' and Home's quick actions.
COMMANDS = sorted(set(re.findall(r'say: "([^"]+)"', SECTIONS + HOME_JS)))
# Quick actions that start a command for you to finish.
FILLS = sorted(set(re.findall(r'fill: "([^"]+)"', HOME_JS)))
ATTACK = '<img src=x onerror="window.__ran=1">'


def _code(path: Path) -> str:
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)


# ================================================================== static

class TestTheShellIsWiredUp:
    def test_the_nine_sections_are_there_in_order(self):
        assert IDS == ["home", "chat", "tasks", "jobs", "resume",
                       "projects", "memory", "tools", "system"]

    @pytest.mark.parametrize("route", IDS)
    def test_each_section_has_a_link_and_a_place(self, route):
        assert f'href="#/{route}" data-route="{route}"' in HTML
        assert f'data-view="{route}"' in HTML

    def test_nothing_links_to_a_section_that_doesnt_exist(self):
        assert set(re.findall(r'data-route="(\w+)"', HTML)) == set(IDS)
        assert set(re.findall(r'data-view="(\w+)"', HTML)) == set(IDS)

    def test_each_link_announces_its_shortcut(self):
        keys = re.findall(r'data-route="(\w+)" aria-keyshortcuts="Alt\+(\d)"', HTML)
        assert keys == [(route, str(n)) for n, route in enumerate(IDS, 1)]

    def test_the_scripts_load_in_order(self):
        order = ["js/core/h.js", "js/core/bridge.js", "js/core/tasks.js", "js/core/router.js",
                 "js/views/sections.js", "js/views/home.js", "js/components/sidenav.js",
                 "js/components/palette.js", "app.js"]
        at = [HTML.index(f'src="{src}"') for src in order]
        assert at == sorted(at)

    def test_only_the_bridge_talks_to_python(self):
        """One door. A second place calling window.pywebview.api directly is
        a second place to get confirmations wrong."""
        for script in UI.rglob("*.js"):
            if "jobs" in script.parts or script.name == "bridge.js":
                continue
            assert "pywebview.api" not in _code(script), f"{script.name} calls Python directly"
        assert "pywebview.api" in _code(UI / "js" / "core" / "bridge.js")

    def test_a_yes_can_only_be_a_real_true(self):
        assert "ok === true" in _code(UI / "js" / "core" / "bridge.js")

    @pytest.mark.parametrize("path", [
        "index.html", "js/core/bridge.js", "js/core/tasks.js", "js/core/router.js",
        "js/views/sections.js", "js/views/home.js",
        "js/components/sidenav.js", "js/components/palette.js"])
    def test_no_new_screen_says_jarvis(self, path):
        """Comments may name the Python package (jarvis/), which keeps its
        name; nothing the page shows or runs may."""
        text = (UI / path).read_text(encoding="utf-8")
        text = re.sub(r"/\*.*?\*/|<!--.*?-->", "", text, flags=re.S)
        assert "jarvis" not in text.lower()

    def test_there_is_one_main_landmark(self):
        assert HTML.count("<main") == 1


# ============================================== the buttons do real things

class TestEveryButtonDoesSomethingReal:
    """Each command a section offers must be one LITTLE answers locally.
    Checked against the real router, with what each one would run stubbed,
    so nothing opens, searches or speaks during the test."""

    ROUTED = {
        "find jobs for me": "find_jobs",
        "show my top matches": "top_matches",
        "show new jobs": "top_matches",
        "show my application status": "application_status",
        "open my dashboard": "open_dashboard",
        "show my resume profile": "show_profile",
        "check my resume": "check_resume",
        "which skills am i missing": "missing_skills",
        "what do you remember": "recall",
        "list reminders": "list_reminders",
        "run a system check": "system_check",
        "what voice are you using": "voice_report",
        "check the microphone": "check_component",
        "check the tools": "check_component",
    }
    ASSISTANT = {"list microphones", "start the demo"}       # the demo needs the assistant (Chapter 47)

    @pytest.fixture
    def stubbed(self, monkeypatch):
        from jarvis.jobs import resume, resume_check
        from jarvis.routing import router
        import jarvis.voice

        def stub(owner, name):
            monkeypatch.setattr(owner, name, lambda *_a, **_k: f"<{name}>")

        for name in ("find_jobs", "top_matches", "application_status", "missing_skills"):
            stub(router.jobs, name)
        stub(router.job_dashboard, "open_dashboard")
        stub(resume, "show_profile")
        stub(resume_check, "check_resume")
        stub(router.memory, "recall")
        stub(router.reminders, "list_reminders")
        stub(router.health, "system_check")
        stub(router.health, "check_component")
        stub(jarvis.voice, "voice_report")
        stub(jarvis.voice, "microphones")
        return router

    def test_the_sections_offer_commands(self):
        assert len(COMMANDS) >= 10

    def test_every_offered_command_is_one_this_test_checks(self):
        """A new button without a line here fails, so none slips in unchecked."""
        assert set(COMMANDS) == set(self.ROUTED) | self.ASSISTANT

    @pytest.mark.parametrize("command", sorted(ROUTED))
    def test_it_is_answered_on_this_computer(self, stubbed, command):
        assert stubbed.fast_route(command) == f"<{self.ROUTED[command]}>"

    # A start you finish, finished the way the button suggests, lands where
    # it should — not with the model.
    FINISHED = {
        "look up ": ("look up python decorators", "search_web_and_read"),
        "remind me to ": ("remind me to call mom at 6pm", "set_reminder"),
    }

    def test_every_start_a_button_offers_is_one_this_test_checks(self):
        assert set(FILLS) == set(self.FINISHED) | {"first "}

    @pytest.mark.parametrize("fill", sorted(FINISHED))
    def test_a_finished_start_is_answered_on_this_computer(self, monkeypatch, fill):
        from jarvis.routing import router
        monkeypatch.setattr(router.browser, "search_web_and_read", lambda *_a: "<search_web_and_read>")
        monkeypatch.setattr(router.reminders, "set_reminder", lambda *_a: "<set_reminder>")
        command, target = self.FINISHED[fill]
        assert command.startswith(fill)
        assert router.fast_route(command) == f"<{target}>"

    def test_several_steps_starts_a_plan(self):
        from jarvis.ai import planner
        assert planner.should_plan("first open vs code, then create app.py")

    def test_list_microphones_is_answered_by_the_assistant(self, stubbed):
        from jarvis.app.assistant import Jarvis
        logged = []
        Jarvis(log_fn=logged.append).handle("list microphones")
        assert "<microphones>" in logged


# ========================================================== in a browser

@pytest.fixture(scope="module")
def browser_ok():
    if not _ui.available():
        pytest.skip("Playwright isn't installed")


def _render(check, **kw):
    result, errors = _ui.open_panel(check, **kw)
    if result is _ui.NO_BROWSER:
        pytest.skip("no browser to render the panel with")
    assert errors == [], errors
    return result


WHERE = """() => ({
  hash: location.hash,
  shown: [...document.querySelectorAll('#main > [data-view]')].filter(v => !v.hidden)
           .map(v => v.dataset.view),
  current: [...document.querySelectorAll('[aria-current="page"]')].map(a => a.dataset.route),
  focus: document.activeElement.id,
  heading: document.getElementById('viewTitle').textContent,
  title: document.title,
})"""


async def _tab_to(page, test, limit=40):
    """Press Tab until `test` (a JS expression about document.activeElement)
    is true. Returns how many presses it took, or None."""
    for n in range(1, limit + 1):
        await page.keyboard.press("Tab")
        if await page.evaluate(f"(() => {{ const el = document.activeElement; return !!({test}); }})()"):
            return n
    return None


class TestKeyboardOnly:
    @pytest.mark.parametrize("target", IDS)
    def test_every_section_is_reachable_with_the_keyboard_alone(self, browser_ok, target):
        start = "jobs" if target == "home" else "home"

        async def check(page):
            await page.evaluate("document.getElementById('skipLink').focus()")
            reached = await _tab_to(page, f"el.dataset.route === '{target}'")
            if reached is None:
                return {"reached": False}
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(150)
            where = await page.evaluate(WHERE)
            # From the heading, the section's own controls are a few Tabs on.
            into = await _tab_to(page, f"el.closest('[data-view=\"{target}\"]')", limit=4)
            return {"reached": True, "into": into, **where}

        seen = _render(check, route=start)
        assert seen["reached"], f"Tab never reached the {target} link"
        assert seen["hash"] == f"#/{target}"
        assert seen["shown"] == [target], "exactly one section shows"
        assert seen["current"] == [target], "the link is marked as the current page"
        assert seen["focus"] == "viewTitle", "focus lands on the section's heading"
        assert seen["heading"] == TITLES[target]
        assert seen["title"] == ("LITTLE" if target == "home" else f"{TITLES[target]} · LITTLE")
        assert seen["into"] is not None, "Tab doesn't carry on into the section"

    def test_the_skip_link_is_first_and_jumps_past_the_navigation(self, browser_ok):
        async def check(page):
            # The first thing in tab order, reading the page top to bottom.
            first = await page.evaluate("""() => [...document.querySelectorAll(
                'a[href], button, input, [tabindex]:not([tabindex="-1"])')]
                .find(el => !el.disabled && !el.closest('[hidden]')).id""")
            await page.evaluate("document.getElementById('skipLink').focus()")
            visible = await page.evaluate(
                "document.getElementById('skipLink').getBoundingClientRect().width > 20")
            await page.keyboard.press("Enter")
            landed = await page.evaluate("document.activeElement.id")
            await page.keyboard.press("Tab")
            inside = await page.evaluate("!!document.activeElement.closest('#main')")
            return {"first": first, "visible": visible, "landed": landed, "inside": inside}

        seen = _render(check)
        assert seen["first"] == "skipLink"
        assert seen["visible"], "the skip link shows when it has focus"
        assert seen["landed"] == "main"
        assert seen["inside"], "the next Tab is inside the section, past the navigation"

    def test_alt_and_a_number_jumps_to_a_section(self, browser_ok):
        async def check(page):
            out = []
            for key in ("Alt+4", "Alt+9", "Alt+1"):
                await page.keyboard.press(key)
                await page.wait_for_timeout(120)
                out.append(await page.evaluate(WHERE))
            return out

        jobs, system, home = _render(check)
        assert jobs["shown"] == ["jobs"] and jobs["focus"] == "viewTitle"
        assert system["shown"] == ["system"]
        assert home["shown"] == ["home"]

    def test_back_and_forward_work(self, browser_ok):
        async def check(page):
            await page.click('[data-route="jobs"]')
            await page.click('[data-route="system"]')
            await page.go_back()
            await page.wait_for_timeout(120)
            back = await page.evaluate(WHERE)
            await page.go_forward()
            await page.wait_for_timeout(120)
            return back, await page.evaluate(WHERE)

        back, forward = _render(check)
        assert back["shown"] == ["jobs"]
        assert forward["shown"] == ["system"]

    def test_an_unknown_address_lands_on_home(self, browser_ok):
        seen = _render(lambda page: page.evaluate(WHERE), route="nowhere")
        assert seen["shown"] == ["home"] and seen["hash"] == "#/home"
        assert seen["focus"] != "viewTitle", "opening the app doesn't steal focus"

    def test_the_title_follows_the_name_python_reports(self, browser_ok):
        poll = {"stats": {
            "identity": {"name": "NOVA", "call": "Nova"}, "system": {"available": False},
            "session": {"uptime": "0", "commands": 0, "tools": 0, "os": "Windows 11"},
            "voice": {"mic": "on", "speech": "on", "voice": "Neerja", "lang": "en-IN", "model": "m"},
            "tools": [], "reminders": [], "plan": None, "browser": "closed", "contacts": 0,
            "workspace": "C:/w"}}
        seen = _render(lambda page: page.evaluate("document.title"),
                       route="jobs", script=_ui.bridge(poll))
        assert seen == "Jobs · NOVA"

    def test_typing_a_command_on_another_section_takes_you_home_and_keeps_the_cursor(self, browser_ok):
        async def check(page):
            await page.focus("#input")
            await page.keyboard.type("open chrome")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(150)
            return {**await page.evaluate(WHERE), "calls": await page.evaluate("window.__calls")}

        seen = _render(check, route="jobs")
        assert ["send", "open chrome"] in seen["calls"]
        assert seen["shown"] == ["home"]
        assert seen["focus"] == "input"


class TestEverySectionIsReal:
    """Until UI-10 the unbuilt sections held a place with "Coming here" and
    buttons for what already worked. Every section has its own view now, so
    no promise is left on screen — and the buttons that were placeholders
    became real ones in their sections."""

    def test_no_section_is_a_placeholder(self):
        assert SOON == [], f"still placeholders: {SOON}"
        assert "Coming here" not in HTML

    @pytest.mark.parametrize("route", ["home", "chat", "tasks", "jobs", "resume", "projects",
                                       "memory", "tools", "system"])
    def test_no_section_says_coming_here(self, browser_ok, route):
        seen = _render(lambda page: page.evaluate(f"""() =>
            document.querySelector('#main > [data-view="{route}"]').textContent"""), route=route)
        assert "Coming here" not in seen

    def test_a_command_button_runs_it_and_shows_the_reply_where_you_are(self, browser_ok):
        done = {"id": 3, "text": "check the tools", "source": "typed", "status": "done", "route": "local",
                "started": 1, "ms": 40, "steps": [], "reply": "TOOLS  ok  67 registered", "error": "",
                "plan": None, "reset": False, "again_of": None, "stopping": False, "stop_at": None, "v": 2}

        async def check(page):
            await page.click("#toolsCheck")
            await page.evaluate("window.__queue.push({status: 'listening', lines: [], tasks: %s})"
                                % json.dumps({"v": 2, "changed": [done]}))
            await page.wait_for_timeout(400)
            return {**await page.evaluate(WHERE), "calls": await page.evaluate("window.__calls"),
                    "out": await page.inner_text("#toolsOut")}

        seen = _render(check, route="tools")
        assert ["send", "check the tools"] in seen["calls"]
        assert seen["shown"] == ["tools"], "you stay where you pressed it"
        assert seen["out"] == "TOOLS  ok  67 registered"

    def test_a_go_button_only_navigates(self, browser_ok):
        async def check(page):
            await page.click('[data-view="projects"] #projEdit')
            await page.wait_for_timeout(150)
            return {**await page.evaluate(WHERE), "calls": await page.evaluate("window.__calls")}

        seen = _render(check, route="projects")
        assert not any(c[0] in ("send", "control") for c in seen["calls"])
        assert seen["shown"] == ["resume"]


class TestThePalette:
    OPEN = "Control+k"

    def _state(self):
        return """() => ({
          open: !document.getElementById('paletteVeil').hidden,
          focus: document.activeElement.id,
          active: document.getElementById('paletteInput').getAttribute('aria-activedescendant'),
          selected: [...document.querySelectorAll('#paletteList [aria-selected="true"]')].map(o => o.id),
          options: [...document.querySelectorAll('#paletteList [role="option"]')].map(o => o.textContent),
          groups: [...document.querySelectorAll('#paletteList .palette-group')].map(g => g.textContent),
          calls: window.__calls,
          hash: location.hash,
        })"""

    def test_ctrl_k_opens_it_ready_to_type(self, browser_ok):
        async def check(page):
            await page.keyboard.press(self.OPEN)
            return await page.evaluate(self._state())

        seen = _render(check)
        assert seen["open"] and seen["focus"] == "paletteInput"
        assert seen["groups"][:3] == ["Go to", "Controls", "Commands"]
        assert seen["active"] == "palOpt0" and seen["selected"] == ["palOpt0"]
        assert seen["options"][0].startswith("Home")

    def test_the_search_button_opens_it_too(self, browser_ok):
        async def check(page):
            await page.click("#paletteBtn")
            return await page.evaluate(self._state())

        assert _render(check)["open"]

    def test_type_and_enter_goes_there(self, browser_ok):
        async def check(page):
            await page.keyboard.press(self.OPEN)
            await page.keyboard.type("system")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(150)
            return {**await page.evaluate(self._state()), **await page.evaluate(WHERE)}

        seen = _render(check)
        assert not seen["open"]
        assert seen["shown"] == ["system"] and seen["focus"] == "viewTitle"

    def test_arrows_move_the_highlight_and_wrap(self, browser_ok):
        async def check(page):
            await page.keyboard.press(self.OPEN)
            await page.keyboard.press("ArrowDown")
            down = await page.evaluate(self._state())
            await page.keyboard.press("ArrowUp")
            await page.keyboard.press("ArrowUp")
            up = await page.evaluate(self._state())
            return down, up

        down, up = _render(check)
        assert down["selected"] == ["palOpt1"] and down["active"] == "palOpt1"
        last = f"palOpt{len(up['options']) - 1}"
        assert up["selected"] == [last], "up from the first row wraps to the last"

    def test_escape_closes_it_and_puts_focus_back_without_stopping_anything(self, browser_ok):
        async def check(page):
            await page.focus("#input")
            await page.keyboard.press(self.OPEN)
            await page.keyboard.press("Escape")
            return await page.evaluate(self._state())

        seen = _render(check)
        assert not seen["open"] and seen["focus"] == "input"
        assert ["control", "stop"] not in seen["calls"], "Escape in the palette isn't Stop"

    def test_focus_cannot_wander_out_while_it_is_open(self, browser_ok):
        async def check(page):
            await page.keyboard.press(self.OPEN)
            await page.keyboard.press("Tab")
            after_tab = (await page.evaluate(self._state()))["focus"]
            await page.keyboard.press("Shift+Tab")
            return after_tab, (await page.evaluate(self._state()))["focus"]

        assert _render(check) == ("paletteInput", "paletteInput")

    def test_anything_else_is_asked_as_typed(self, browser_ok):
        async def check(page):
            await page.keyboard.press(self.OPEN)
            await page.keyboard.type("open chrome")
            options = (await page.evaluate(self._state()))["options"]
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(150)
            return {"options": options, **await page.evaluate(self._state()),
                    **await page.evaluate(WHERE)}

        seen = _render(check, route="tools")
        assert seen["options"] == ["Ask Little: “open chrome”"]
        assert ["send", "open chrome"] in seen["calls"]
        assert seen["shown"] == ["home"] and seen["focus"] == "input"

    def test_a_known_command_runs_as_it_is_written(self, browser_ok):
        async def check(page):
            await page.keyboard.press(self.OPEN)
            await page.keyboard.type("top matches")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(150)
            return await page.evaluate(self._state())

        assert ["send", "show my top matches"] in _render(check)["calls"]

    def test_a_control_runs_and_leaves_you_where_you_were(self, browser_ok):
        async def check(page):
            await page.focus("#input")
            await page.keyboard.press(self.OPEN)
            await page.keyboard.type("mute")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(150)
            return {**await page.evaluate(self._state()), **await page.evaluate(WHERE),
                    "mute": await page.inner_text("#muteBtn")}

        seen = _render(check, route="jobs")
        assert ["control", "mute"] in seen["calls"]
        assert seen["mute"] == "Unmute voice", "the button reads what Python said"
        assert seen["shown"] == ["jobs"] and seen["focus"] == "input"

    def test_a_click_runs_a_row(self, browser_ok):
        async def check(page):
            await page.keyboard.press(self.OPEN)
            await page.click('#paletteList [role="option"]:has-text("Resume")')
            await page.wait_for_timeout(150)
            return await page.evaluate(WHERE)

        assert _render(check)["shown"] == ["resume"]

    def test_typed_text_is_shown_as_text(self, browser_ok):
        async def check(page):
            await page.keyboard.press(self.OPEN)
            await page.keyboard.type(ATTACK)
            await page.wait_for_timeout(100)
            return {"images": await page.evaluate("document.querySelectorAll('#paletteList img').length"),
                    "ran": await page.evaluate("window.__ran || 0"),
                    **await page.evaluate(self._state())}

        seen = _render(check)
        assert seen["images"] == 0 and seen["ran"] == 0
        assert seen["options"] == [f"Ask Little: “{ATTACK}”"]

    def test_a_confirmation_takes_over_from_it(self, browser_ok):
        """A question arriving while the palette is open closes the palette
        and gets the focus — and an Enter already on its way cancels."""
        async def check(page):
            await page.keyboard.press(self.OPEN)
            await page.keyboard.type("jobs")
            await page.evaluate("window.__nextAsk = {id: 9, message: 'Send this to Rahul?'}")
            await page.wait_for_timeout(400)
            state = await page.evaluate(self._state())
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(100)
            return state, await page.evaluate(self._state())

        during, after = _render(check)
        assert not during["open"] and during["focus"] == "askNo"
        assert ["confirm_reply", 9, True] not in after["calls"]
        assert ["confirm_reply", 9, False] in after["calls"]
        assert after["hash"] == "#/home", "the Enter didn't also run the palette's row"

    def test_it_wont_open_over_a_confirmation(self, browser_ok):
        async def check(page):
            await page.evaluate("window.__nextAsk = {id: 4, message: 'Delete notes.txt?'}")
            await page.wait_for_timeout(400)
            await page.keyboard.press(self.OPEN)
            await page.keyboard.press("Alt+4")
            await page.wait_for_timeout(200)              # long enough for a move to land
            return {**await page.evaluate(self._state()), **await page.evaluate(WHERE)}

        seen = _render(check)
        assert not seen["open"] and seen["focus"] == "askNo"
        assert seen["shown"] == ["home"], "shortcuts wait until the question is answered"


class TestTheNavigationFitsTheWindow:
    SHAPE = """() => ({
      nav: document.body.dataset.nav,
      toggle: !document.getElementById('navToggle').hidden,
      overflow: document.documentElement.scrollWidth > window.innerWidth,
    })"""

    @pytest.mark.parametrize("size,shape,toggle", [
        ((1040, 660), "rail", False),
        ((1280, 800), "rail", True),
        ((1600, 900), "full", True),
        ((390, 800), "bottom", False),
    ], ids=lambda v: f"{v[0]}x{v[1]}" if isinstance(v, tuple) else str(v))
    def test_its_shape_follows_the_width(self, browser_ok, size, shape, toggle):
        seen = _render(lambda page: page.evaluate(self.SHAPE), viewport=size)
        assert seen["nav"] == shape
        assert seen["toggle"] == toggle
        assert not seen["overflow"], "the page scrolls sideways"

    def test_the_rail_still_names_every_link_and_shows_it_on_focus(self, browser_ok):
        async def check(page):
            names = {title: await page.get_by_role("link", name=title, exact=True).count()
                     for title in TITLES.values()}
            await page.focus('[data-route="memory"]')
            await page.keyboard.press("Shift+Tab")
            await page.keyboard.press("Tab")                    # keyboard focus, so it's :focus-visible
            await page.wait_for_timeout(200)
            tip = await page.evaluate("""() => getComputedStyle(
                document.querySelector('[data-route="memory"] .navlabel')).opacity""")
            return names, float(tip)

        names, tip = _render(check, viewport=(1280, 800))
        assert all(count == 1 for count in names.values()), names
        assert tip == 1.0, "the label shows as a tooltip on keyboard focus"

    def test_collapsing_and_expanding_by_hand_is_remembered(self, browser_ok):
        async def check(page):
            await page.click("#navToggle")
            expanded = await page.evaluate("""() => ({
              nav: document.body.dataset.nav,
              label: document.getElementById('navToggle').getAttribute('aria-label'),
              spilling: [...document.querySelectorAll('.panel')]
                .filter(p => !p.hidden && p.offsetParent && !p.classList.contains('feedwrap')
                             && p.scrollHeight > p.clientHeight + 1).length })""")
            await page.reload()
            await page.wait_for_timeout(400)
            after_reload = await page.evaluate("document.body.dataset.nav")
            await page.click("#navToggle")
            return expanded, after_reload, await page.evaluate("document.body.dataset.nav")

        expanded, after_reload, again = _render(check, viewport=(1280, 800))
        assert expanded["nav"] == "full" and expanded["label"] == "Collapse the sidebar"
        assert expanded["spilling"] == 0, "Home still fits with the labels showing"
        assert after_reload == "full"
        assert again == "rail"

    def test_the_bottom_bar_has_four_sections_and_more(self, browser_ok):
        async def check(page):
            bar = await page.evaluate("""() => {
              const shown = [...document.querySelectorAll('#sidenav .navlink')]
                .filter(el => el.offsetParent !== null);
              const nav = document.getElementById('sidenav').getBoundingClientRect();
              const cmd = document.querySelector('.cmdbar').getBoundingClientRect();
              return { names: shown.map(el => el.textContent.trim()),
                       heights: shown.map(el => el.getBoundingClientRect().height),
                       below: nav.top >= cmd.bottom, more: document.getElementById('navMore')
                         .classList.contains('is-current') };
            }""")
            await page.click("#navMore")
            opened = await page.evaluate("!document.getElementById('paletteVeil').hidden")
            return {**bar, "opened": opened}

        seen = _render(check, viewport=(390, 800), route="memory")
        assert seen["names"] == ["Home", "Chat", "Tasks", "Jobs", "More"]
        assert min(seen["heights"]) >= 44, "touch targets are at least 44px"
        assert seen["below"], "the bar sits under the command box"
        assert seen["more"], "More reads as current when the section lives behind it"
        assert seen["opened"], "More opens the palette"


class TestNothingOverlapsInTheShell:
    @pytest.mark.parametrize("route", IDS[1:])
    @pytest.mark.parametrize("size", [(1040, 660), (1920, 1080)], ids=lambda s: f"{s[0]}x{s[1]}")
    def test_each_section_stays_above_the_command_box(self, browser_ok, route, size):
        seen = _render(lambda page: page.evaluate(f"""() => {{
            const view = document.querySelector('[data-view="{route}"]').getBoundingClientRect();
            const cmd = document.querySelector('.cmdbar').getBoundingClientRect();
            const top = document.querySelector('.topbar').getBoundingClientRect();
            return {{ clear: view.bottom <= cmd.top && view.top >= top.bottom,
                      sideways: document.documentElement.scrollWidth > window.innerWidth }};
        }}"""), route=route, viewport=size)
        assert seen["clear"] and not seen["sideways"]
