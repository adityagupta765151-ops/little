"""LITTLE's design system: one source of values, readable text, and an orb
whose seven states each look like what they mean.

Most of these read the stylesheets, so they run anywhere. The ones that need
to see the page render it in a browser engine, and skip where there isn't one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import _ui

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "ui" / "css"
TOKENS = (CSS / "tokens.css").read_text(encoding="utf-8")
# Every stylesheet that must take its values from tokens.css.
CONSUMERS = [CSS / "base.css", CSS / "components.css", ROOT / "ui" / "app.css",
             ROOT / "ui" / "jobs" / "app.css"]


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _token(name: str) -> str:
    match = re.search(rf"--{re.escape(name)}:\s*([^;]+);", TOKENS)
    assert match, f"--{name} isn't defined in tokens.css"
    return match.group(1).strip()


# ----------------------------------------------------------- contrast maths

def _rgb(hex_colour: str) -> tuple[int, int, int]:
    value = hex_colour.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(rgb) -> float:
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _over(rgba: str, base) -> tuple[int, int, int]:
    """A translucent surface as it actually looks over the floor."""
    r, g, b, a = (float(x) for x in re.findall(r"[\d.]+", rgba))
    return tuple(round(c * a + d * (1 - a)) for c, d in zip((r, g, b), base))


FLOOR = _rgb(_token("bg-1"))
LIGHTEST_GLASS = _over(_token("surface-3"), FLOOR)
BACKGROUNDS = {
    "window": _rgb(_token("bg-0")),
    "floor": FLOOR,
    "lightest glass": LIGHTEST_GLASS,
    "dialog": _rgb(_token("surface-solid")),
}


# ------------------------------------------------------------------ tokens

class TestTheTokens:
    @pytest.mark.parametrize("name", [
        "bg-0", "bg-1", "surface-1", "surface-2", "surface-3", "surface-solid", "line",
        "ink-1", "ink-2", "ink-3", "brand",
        "st-idle", "st-listening", "st-thinking", "st-executing", "st-speaking",
        "st-success", "st-error",
        "font-ui", "font-display", "font-mono",
        "fs-2xs", "fs-md", "sp-1", "sp-4", "r-md", "r-lg", "shadow-1",
        "dur-1", "dur-3", "ease", "focus-ring",
    ])
    def test_it_is_defined(self, name):
        assert _token(name)

    def test_no_text_size_is_below_twelve_pixels(self):
        sizes = {name: int(float(px)) for name, px in
                 re.findall(r"--(fs-[\w-]+):\s*([\d.]+)px", TOKENS)}
        assert sizes, "no font sizes defined"
        for name, px in sizes.items():
            assert px >= 12, f"--{name} is {px}px; nothing on screen goes below 12"

    def test_interface_transitions_stay_between_120_and_240_ms(self):
        for name, ms in re.findall(r"--(dur-\d):\s*(\d+)ms", TOKENS):
            assert 120 <= int(ms) <= 240, f"--{name} is {ms}ms"

    def test_no_root_token_freezes_the_state_colour(self):
        """A token defined on :root that mentions var(--now) resolves once,
        at the root, and never changes with state. The orb's glow did
        exactly that in the first draft of this file."""
        root = _strip_comments(TOKENS).split("}", 1)[0]
        for line in root.splitlines():
            if "var(--now)" in line:
                pytest.fail(f"a root token depends on --now: {line.strip()}")


# ---------------------------------------------------------------- contrast

class TestTextIsReadable:
    @pytest.mark.parametrize("ink", ["ink-1", "ink-2", "ink-3"])
    @pytest.mark.parametrize("where", list(BACKGROUNDS))
    def test_text_meets_four_and_a_half_to_one(self, ink, where):
        ratio = _contrast(_rgb(_token(ink)), BACKGROUNDS[where])
        assert ratio >= 4.5, f"--{ink} on the {where} is {ratio:.2f}:1"

    @pytest.mark.parametrize("state", ["idle", "listening", "thinking", "executing",
                                       "speaking", "success", "error"])
    def test_every_state_colour_is_readable_as_text(self, state):
        """The state word under the orb is written in the state's colour."""
        ratio = _contrast(_rgb(_token(f"st-{state}")), LIGHTEST_GLASS)
        assert ratio >= 4.5, f"--st-{state} on glass is {ratio:.2f}:1"

    @pytest.mark.parametrize("fill", ["brand", "st-executing"])
    def test_text_on_filled_buttons_is_readable(self, fill):
        ratio = _contrast(_rgb(_token("ink-on-accent")), _rgb(_token(fill)))
        assert ratio >= 4.5


# ------------------------------------------------------------- consistency

class TestEverythingComesFromTheTokens:
    @pytest.mark.parametrize("sheet", CONSUMERS, ids=lambda p: p.name)
    def test_no_stylesheet_but_tokens_writes_a_colour(self, sheet):
        css = _strip_comments(sheet.read_text(encoding="utf-8"))
        for pattern in (r"#[0-9a-fA-F]{3,8}\b", r"\brgba?\(", r"\bhsla?\("):
            found = re.findall(pattern, css)
            assert not found, f"{sheet.name} writes {found[:3]} — use a token"

    @pytest.mark.parametrize("sheet", CONSUMERS, ids=lambda p: p.name)
    def test_font_sizes_come_from_the_scale(self, sheet):
        css = _strip_comments(sheet.read_text(encoding="utf-8"))
        for value in re.findall(r"font-size:\s*([^;]+);", css):
            assert value.strip().startswith("var(--fs-"), \
                f"{sheet.name} sets font-size: {value} — use the type scale"

    def test_the_page_writes_no_inline_colours(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        assert "style=" not in html

    def test_base_stops_all_motion_when_asked(self):
        base = (CSS / "base.css").read_text(encoding="utf-8")
        assert "prefers-reduced-motion: reduce" in base
        block = base[base.index("prefers-reduced-motion"):]
        assert "animation-duration" in block and "transition-duration" in block


# ------------------------------------------------------------------- page

class TestThePageIsWiredUp:
    HTML = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")

    def test_styles_load_values_first_and_layout_last(self):
        order = [self.HTML.index(f'href="{f}"') for f in
                 ("css/tokens.css", "css/base.css", "css/components.css", "app.css")]
        assert order == sorted(order)

    def test_the_safe_builder_loads_before_the_page_script(self):
        assert self.HTML.index('src="js/core/h.js"') < self.HTML.index('src="app.js"')

    @pytest.mark.parametrize("script", sorted(
        [ROOT / "ui" / "app.js", *(ROOT / "ui" / "js").rglob("*.js")]),
        ids=lambda p: p.name)
    def test_every_element_a_script_reaches_for_exists(self, script):
        """The first draft removed the dial's tick marks and would have left
        the script reaching for an element that was gone."""
        code = script.read_text(encoding="utf-8")
        wanted = set(re.findall(r'\$\("([\w-]+)"\)', code))
        wanted |= set(re.findall(r'getElementById\("([\w-]+)"\)', code))
        for element_id in wanted:
            assert f'id="{element_id}"' in self.HTML, \
                f"{script.name} uses #{element_id}, which isn't on the page"

    @pytest.mark.parametrize("selector", [
        'body[data-state="offline"]', 'body[data-state="listening"]',
        'body[data-state="thinking"]', 'body[data-state="executing"]',
        'body[data-state="speaking"]', 'body[data-flash="success"]', 'body[data-flash="error"]',
    ])
    def test_the_orb_has_all_seven_states(self, selector):
        components = (CSS / "components.css").read_text(encoding="utf-8")
        assert f"{selector} .face" in components or f"{selector} .orb" in components

    def test_the_radar_that_measured_nothing_is_gone(self):
        assert "radar" not in self.HTML and "r-sweep" not in self.HTML


# ------------------------------------------------------------ in a browser

@pytest.fixture(scope="module")
def browser_ok():
    if not _ui.available():
        pytest.skip("Playwright isn't installed")


def _render(check, **kw):
    result, errors = _ui.open_panel(check, **kw)
    if result is _ui.NO_BROWSER:
        pytest.skip("no browser to render the panel with")
    return result, errors


class TestTheSafeBuilder:
    """h() is how every later screen will put things on the page."""

    def test_it_keeps_text_as_text_and_refuses_code(self, browser_ok):
        async def check(page):
            return await page.evaluate("""() => {
              const { h, safeUrl } = window.Little;
              const text = h("div", null, "<img src=x onerror=alert(1)>");
              const handler = h("div", { onclick: "window.__ran = 1", attrs: 1 });
              const bad = h("a", { href: "javascript:window.__ran=1" }, "x");
              const good = h("a", { href: "https://example.com/job" }, "x");
              const styled = h("div", { style: { width: "40%" } });
              const labelled = h("button", { aria: { label: "Close" }, data: { act: "stop" } });
              const kids = h("ul", "list", h("li", null, "a"), [h("li", null, "b"), null, false]);
              return {
                text: text.textContent, images: text.querySelectorAll("img").length,
                handler: handler.hasAttribute("onclick"),
                badHref: bad.hasAttribute("href"), goodHref: good.getAttribute("href"),
                width: styled.style.width,
                aria: labelled.getAttribute("aria-label"), act: labelled.dataset.act,
                kids: kids.children.length, cls: kids.className,
                urls: [safeUrl("https://a.b/c"), safeUrl("javascript:x"), safeUrl("data:text/html,x"),
                       safeUrl("not a url"), safeUrl(null)],
              };
            }""")
        seen, errors = _render(check)
        assert errors == []
        assert seen["text"] == "<img src=x onerror=alert(1)>" and seen["images"] == 0
        assert seen["handler"] is False
        assert seen["badHref"] is False and seen["goodHref"] == "https://example.com/job"
        assert seen["width"] == "40%"
        assert seen["aria"] == "Close" and seen["act"] == "stop"
        assert seen["kids"] == 2 and seen["cls"] == "list"
        assert seen["urls"] == ["https://a.b/c", None, None, None, None]


class TestTheOrbInEachState:
    STATES = [("offline", None), ("listening", None), ("thinking", None),
              ("executing", None), ("speaking", None), ("listening", "success"),
              ("listening", "error")]

    def _snapshot(self, state, flash):
        async def check(page):
            await page.evaluate("""([s, f]) => { document.body.dataset.state = s;
                if (f) document.body.dataset.flash = f; }""", [state, flash])
            await page.wait_for_timeout(450)
            return await page.evaluate("""() => {
              const op = (sel) => parseFloat(getComputedStyle(document.querySelector(sel)).opacity);
              return {
                now: getComputedStyle(document.body).getPropertyValue("--now").trim(),
                orbit: op(".orb-orbit"), activity: op(".orb-activity"), done: op(".orb-done"),
                wave: op(".face .wave"), happy: op(".face .eye-happy"), hmm: op(".face .hmm"),
                eye: getComputedStyle(document.querySelector(".eye-l")).transform,
              };
            }""")
        seen, errors = _render(check)
        assert errors == []
        return seen

    def test_every_state_has_its_own_colour(self, browser_ok):
        colours = [self._snapshot(s, f)["now"] for s, f in self.STATES]
        assert len(set(colours)) == len(colours), f"two states share a colour: {colours}"

    @pytest.mark.parametrize("state,flash,shown", [
        ("thinking", None, "orbit"),
        ("executing", None, "activity"),
        ("speaking", None, "wave"),
        ("listening", "success", "happy"),
        ("listening", "error", "hmm"),
    ])
    def test_each_state_shows_its_own_sign_and_no_other(self, browser_ok, state, flash, shown):
        seen = self._snapshot(state, flash)
        signs = ["orbit", "activity", "wave", "happy", "hmm"]
        assert seen[shown] > 0.5, f"{state}/{flash}: {shown} isn't showing"
        for other in signs:
            if other != shown:
                assert seen[other] < 0.1, f"{state}/{flash}: {other} shows too"

    def test_idle_is_asleep(self, browser_ok):
        seen = self._snapshot("offline", None)
        # eyes squashed nearly shut: scaleY around 0.12
        assert seen["eye"].startswith("matrix(1, 0, 0, 0.1")


class TestThePanelRenders:
    def test_real_readings_render_with_no_errors(self, browser_ok):
        poll = {
            "status": "listening",
            "lines": ["You: open chrome", "LITTLE: Opening Chrome.", "   heard: a little bit"],
            "stats": {
                "identity": {"name": "LITTLE", "call": "Little"},
                "system": {"available": True, "cpu": 23, "ram": 64, "disk": 48,
                           "ram_used": 10.8, "ram_total": 16.8, "disk_free": 151},
                "session": {"uptime": "00:12:40", "commands": 7, "tools": 1, "os": "Windows 11"},
                "voice": {"mic": "on", "speech": "on", "voice": "Neerja", "lang": "en-IN",
                          "model": "gemini-flash-latest"},
                "tools": [{"name": "open_app", "ms": 42}],
                "reminders": [{"text": "call mom", "at": "20:00"}],
                "plan": None, "browser": "closed", "contacts": 3, "workspace": "C:/w",
            },
        }

        async def check(page):
            return await page.evaluate("""() => ({
              state: document.body.dataset.state,
              meters: [...document.querySelectorAll('#gauges .bar i')].map(i => i.style.width),
              rows: [...document.querySelectorAll('#feed .row')].map(r => r.className),
              note: [...document.querySelectorAll('#feed .row.note .m')].pop().textContent,
              voice: document.getElementById('voiceKv').textContent,
            })""")
        seen, errors = _render(check, script=_ui.bridge(poll))
        assert errors == []
        assert seen["state"] == "listening"
        assert seen["meters"] == ["23%", "64%", "48%"]
        # the first row is always the greeting note, then the conversation
        assert seen["rows"][:3] == ["row note", "row you", "row assistant"]
        assert seen["note"] == "heard: a little bit"          # no leading spaces
        assert "Neerja" in seen["voice"]


class TestNothingOverlaps:
    """The first draft's larger type made panels squeeze below their own
    content on the smallest window the app allows, so rows slid under the
    next panel and the Resources buttons under the command bar. Side
    columns now scroll instead of squeezing."""

    @pytest.mark.parametrize("size", [(1040, 660), (1280, 800), (1920, 1080)],
                             ids=lambda s: f"{s[0]}x{s[1]}")
    def test_no_panel_spills_at_any_window_size(self, browser_ok, size):
        poll = {
            "status": "listening", "lines": [],
            "stats": {
                "identity": {"name": "LITTLE", "call": "Little"},
                "system": {"available": True, "cpu": 23, "ram": 64, "disk": 48,
                           "ram_used": 10.8, "ram_total": 16.8, "disk_free": 151},
                "session": {"uptime": "00:12:40", "commands": 7, "tools": 3, "os": "Windows 11"},
                "voice": {"mic": "on", "speech": "on", "voice": "Neerja", "lang": "en-IN",
                          "model": "gemini-flash-latest"},
                "tools": [{"name": "find_jobs", "ms": 11840}, {"name": "open_app", "ms": 42},
                          {"name": "set_reminder", "ms": 3}],
                "reminders": [{"text": "call mom", "at": "20:00"}],
                "plan": {"at": 2, "steps": ["Open VS Code", "Create app.py", "Run the tests"],
                         "done": [{"ok": True}]},
                "browser": "open", "contacts": 214, "workspace": "C:/w",
            },
        }

        async def check(page):
            return await page.evaluate("""() => ({
              spilling: [...document.querySelectorAll('.panel')]
                .filter(p => !p.classList.contains('feedwrap') && p.scrollHeight > p.clientHeight + 1)
                .map(p => p.querySelector('h2').textContent),
              clear: ['.left', '.right'].every(sel =>
                document.querySelector(sel).getBoundingClientRect().bottom
                  <= document.querySelector('.cmdbar').getBoundingClientRect().top),
            })""")
        seen, errors = _render(check, script=_ui.bridge(poll), viewport=size)
        assert errors == []
        assert seen["spilling"] == [], f"content spills out of: {seen['spilling']}"
        assert seen["clear"], "a side column runs under the command bar"
