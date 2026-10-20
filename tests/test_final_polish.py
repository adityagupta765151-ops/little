"""The final UI phase (UI-10): responsive, accessible, lighter, and one app.

Responsive: every section at eight window sizes, from a wide desktop down
to phone width — nothing off the side, the command box always in reach and
never under the bottom bar, and Home's tablet layout giving LITTLE and the
activity room instead of a sliver.

Accessible: a name on every control in every section, the confirmation
dialog keeping focus inside itself with the page behind it out of reach and
focus given back after, replies said to a screen reader, and motion stopped
when Windows asks.

Lighter: measured first — idle, the page rebuilt about 360 elements a
second on every section. Readings are now drawn only when they change and
only while Home shows them.

One app: no section is a placeholder any more; Tools has its own view.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from jarvis.app import bridge, tasks
from jarvis.tools import permissions

import _ui

ROOT = Path(__file__).resolve().parent.parent
ROUTES = ["home", "chat", "tasks", "jobs", "resume", "projects", "memory", "tools", "system"]
SIZES = [(1440, 900), (1280, 800), (1040, 660), (900, 700), (768, 1024), (600, 900), (480, 560), (390, 844)]
ATTACK = '<img src=x onerror="window.__ran=1">'

STATS = {"identity": {"name": "LITTLE", "call": "Little"},
         "system": {"available": True, "cpu": 23, "ram": 64, "disk": 48, "ram_used": 10.8,
                    "ram_total": 16.8, "disk_free": 151},
         "session": {"uptime": "00:12:40", "commands": 7, "tools": 3, "os": "Windows 11"},
         "voice": {"mic": "on", "speech": "on", "voice": "Neerja", "lang": "en-IN",
                   "model": "gemini-flash-latest"},
         "tools": [{"name": "find_jobs", "ms": 11840}], "reminders": [{"text": "call mom", "at": "20:00"}],
         "plan": None, "browser": "closed", "contacts": 3, "workspace": "C:/w", "warnings": []}


class Quiet:
    muted, running = False, False
    brain = None

    def handle(self, text): ...


@pytest.fixture(scope="module")
def browser_ok():
    if not _ui.available():
        pytest.skip("Playwright isn't installed")


@pytest.fixture(scope="module")
def snapshots():
    """Real answers from the Python side for every section, built once."""
    from jarvis.jobs import matching, resume, store
    from jarvis.store import memory
    tasks.reset()
    profile = {"candidate": {"name": "Aditya Gupta", "email": "a.very.long.address@example-university.ac.in",
                             "phone": "+91 98765 43210", "location": "Prayagraj, Uttar Pradesh, India",
                             "degree": "B.Tech CSE", "graduation_year": "2026", "education": ["B.Tech CSE, 2026"],
                             "skills": ["React", "Node.js", "Python"], "languages": ["JavaScript"],
                             "frameworks": ["Next.js"], "projects": ["Blood Bridge AI - blood requests in Node.js"],
                             "experience": [], "internships": [], "certifications": []},
               "preferences": {"roles": ["Full Stack Developer"]}, "source_file": "cv.pdf"}
    resume.save_profile(profile)
    job = {"job_id": "j1", "company": "Razorpay", "title": "Full Stack Developer", "location": "Bangalore",
           "description": "React, Node.js, AWS. Hybrid.", "platform": "adzuna", "url": "https://example.com"}
    store.upsert_job(matching.score_job(job, profile))
    memory.remember("editor", "VS Code")
    memory.add_contact("mom", "+919876543210")
    memory.log_turn("find jobs for me", "Found 1 job.")
    api = bridge.Api(assistant=Quiet())
    tid = tasks.start("find jobs for me")
    tasks.route("local", task_id=tid)
    n = tasks.step_started("find_jobs", '{"query": ""}', task_id=tid)
    tasks.step_finished(n, task_id=tid)
    tasks.reply("Found 1 job.", task_id=tid)
    tasks.finish(tasks.DONE, task_id=tid)
    _, changed = tasks.changed_since(0)
    out = {"jobs": api.jobs(), "resume": api.resume(), "projects": api.projects(),
           "memory": api.memory_view(), "system": api.system(), "health": api.health(),
           "tools": api.tools(), "tasks": {"v": tasks.version(), "changed": changed}}
    tasks.reset()
    return json.loads(json.dumps(out, default=str))


def _script(snap, opening=None, extra=""):
    opening = opening or {"status": "listening", "lines": ["You: hi"], "stats": STATS, "tasks": snap["tasks"]}
    return _ui.bridge(opening) + "".join(
        f"window.__{name}={json.dumps(snap[key])};" for name, key in
        [("jobs", "jobs"), ("resume", "resume"), ("projects", "projects"), ("memory", "memory"),
         ("system", "system"), ("health", "health"), ("tools", "tools")]) + extra


def _render(check, script, **kw):
    result, errors = _ui.open_panel(check, script=script, **kw)
    if result is _ui.NO_BROWSER:
        pytest.skip("no browser to render the panel with")
    assert errors == [], errors
    return result


# ============================================================== responsive

FIT = """(route) => {
  const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
  const clippedBy = (el) => { for (let p = el.parentElement; p; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (['auto', 'scroll', 'hidden'].includes(s.overflowX) && p.getBoundingClientRect().right <= vw + 1) return true; }
    return false; };
  const wide = [...document.querySelectorAll('body *')].filter(el => {
    const r = el.getBoundingClientRect();
    return r.width && r.height && getComputedStyle(el).visibility !== 'hidden' && r.right > vw + 1 && !clippedBy(el);
  }).slice(0, 5).map(el => el.id || el.className || el.tagName);
  const cmd = document.querySelector('.cmdbar').getBoundingClientRect();
  const nav = document.getElementById('sidenav').getBoundingClientRect();
  const view = document.querySelector(`#main > [data-view="${route}"]`).getBoundingClientRect();
  return {nav: document.body.dataset.nav, overflow: document.documentElement.scrollWidth - vw, wide,
          cmdInView: cmd.top >= 0 && cmd.bottom <= vh + 1,
          navOverCmd: nav.top < cmd.bottom - 1 && nav.bottom > cmd.top + 1 && nav.left < cmd.right && nav.right > cmd.left,
          viewHeight: view.height};
}"""


class TestEverySectionAtEverySize:
    @pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
    @pytest.mark.parametrize("route", ROUTES)
    def test_it_fits(self, browser_ok, snapshots, route, size):
        seen = _render(lambda page: page.evaluate(FIT, route), _script(snapshots), route=route, viewport=size)
        assert seen["overflow"] <= 0 and seen["wide"] == [], seen
        assert seen["cmdInView"] and not seen["navOverCmd"], "the command box is always in reach"
        assert seen["viewHeight"] >= 200, "the section gets real room"
        width = size[0]
        expected = "bottom" if width < 720 else ("full" if width >= 1440 else "rail")
        assert seen["nav"] == expected

    def test_the_window_can_be_this_small(self):
        source = (ROOT / "launcher_web.py").read_text(encoding="utf-8")
        width, height = map(int, re.search(r"min_size=\((\d+), (\d+)\)", source).groups())
        assert (width, height) == (480, 560)
        assert (width, height) in SIZES, "the smallest window is one of the sizes checked above"


HOME = """() => {
  const r = (s) => { const b = document.querySelector(s).getBoundingClientRect();
                     return {top: Math.round(b.top), bottom: Math.round(b.bottom), left: Math.round(b.left),
                             right: Math.round(b.right), width: Math.round(b.width), height: Math.round(b.height)}; };
  return {center: r('.home .center'), left: r('.home .left'), right: r('.home .right'), feed: r('.feedwrap')};
}"""


class TestHomeAtTabletWidth:
    """Between 720 and 1023px the three columns squeezed LITTLE and the
    activity to under 50px wide."""

    @pytest.mark.parametrize("size", [(768, 1024), (900, 700), (1000, 700)], ids=lambda s: f"{s[0]}")
    def test_little_and_the_activity_get_the_room(self, browser_ok, snapshots, size):
        seen = _render(lambda page: page.evaluate(HOME), _script(snapshots), route="home", viewport=size)
        assert seen["center"]["width"] >= 330 and seen["feed"]["height"] >= 300
        assert seen["right"]["left"] >= seen["center"]["right"], "what needs you, beside it"
        assert seen["right"]["top"] == seen["center"]["top"]
        assert seen["left"]["top"] >= seen["center"]["bottom"], "the readings underneath, never over it"
        assert seen["left"]["top"] >= seen["feed"]["bottom"], "nor over the activity, even if its row were squeezed"

    def test_on_a_phone_little_then_what_needs_you_then_the_readings(self, browser_ok, snapshots):
        seen = _render(lambda page: page.evaluate(HOME), _script(snapshots), route="home", viewport=(390, 844))
        assert seen["center"]["top"] < seen["right"]["top"] < seen["left"]["top"]

    def test_the_desktop_keeps_its_three_columns(self, browser_ok, snapshots):
        seen = _render(lambda page: page.evaluate(HOME), _script(snapshots), route="home", viewport=(1280, 800))
        assert seen["left"]["right"] <= seen["center"]["left"] <= seen["center"]["right"] <= seen["right"]["left"]


# =========================================================== accessibility

NAMES = """(route) => {
  const view = document.querySelector(`#main > [data-view="${route}"]`);
  const name = (el) => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const by = el.getAttribute('aria-labelledby');
    if (by) return by.split(/\\s+/).map(id => (document.getElementById(id) || {}).textContent || '').join(' ').trim();
    if (el.id) { const l = document.querySelector(`label[for="${el.id}"]`); if (l) return l.textContent.trim(); }
    const wrap = el.closest('label'); if (wrap) return wrap.textContent.trim();
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return '';
    return (el.textContent || '').trim() || el.getAttribute('title') || '';
  };
  const unnamed = [];
  [view, document.querySelector('.sidenav'), document.querySelector('.topbar'), document.querySelector('.cmdbar')]
    .forEach(root => root.querySelectorAll('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
      .forEach(el => { const r = el.getBoundingClientRect();
                       if ((r.width || r.height) && !name(el)) unnamed.push(el.outerHTML.slice(0, 100)); }));
  return {unnamed, h1: document.querySelectorAll('h1').length,
          landmarks: ['nav', 'header', 'main'].map(t => document.querySelectorAll(t).length)};
}"""


class TestEveryControlHasAName:
    @pytest.mark.parametrize("route", ROUTES)
    def test_in_every_section(self, browser_ok, snapshots, route):
        seen = _render(lambda page: page.evaluate(NAMES, route), _script(snapshots), route=route)
        assert seen["unnamed"] == []
        assert seen["h1"] == 1, "one heading names where you are"
        assert all(n >= 1 for n in seen["landmarks"])


CONTRAST = r"""(route) => {
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const lum = ([r, g, b]) => { const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const over = (top, base) => [0, 1, 2].map(i => top[i] * top[3] + base[i] * (1 - top[3]));
  const behind = (el) => { const layers = [];
    for (let p = el; p; p = p.parentElement) { const c = parse(getComputedStyle(p).backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } }
    let base = [0, 0, 0]; for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return base; };
  const roots = [document.querySelector(`#main > [data-view="${route}"]`), document.querySelector('.sidenav'),
                 document.querySelector('.topbar'), document.querySelector('.cmdbar'), document.getElementById('veil')];
  const low = [];
  let checked = 0;
  roots.forEach(root => root.querySelectorAll('*').forEach(el => {
    const text = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
    const r = el.getBoundingClientRect();
    if (!text || !r.width || !r.height || getComputedStyle(el).visibility === 'hidden') return;
    if (el.closest('[disabled], [aria-hidden="true"]')) return;       // inactive controls are exempt
    const s = getComputedStyle(el);
    let fade = 1; for (let p = el; p; p = p.parentElement) fade *= +getComputedStyle(p).opacity;
    if (fade === 0) return;                 // not drawn at all (the rail's labels, kept for screen readers)
    const bg = behind(el), c = parse(s.color), fg = over([c[0], c[1], c[2], c[3] * fade], bg);
    const a = lum(fg), b = lum(bg), ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const size = parseFloat(s.fontSize), large = size >= 24 || (+s.fontWeight >= 700 && size >= 18.66);
    checked += 1;
    if (ratio < (large ? 3 : 4.5)) low.push(`${text.slice(0, 30)} (${el.className || el.tagName}) ${ratio.toFixed(2)}:1`);
  }));
  return {low, checked};
}"""


class TestTextIsReadableEverywhere:
    """The tokens are checked on their own in test_design_system; this checks
    the text as it's actually drawn, over the surfaces it's actually on."""

    @pytest.mark.parametrize("route", ROUTES)
    def test_every_section(self, browser_ok, snapshots, route):
        seen = _render(lambda page: page.evaluate(CONTRAST, route), _script(snapshots), route=route, wait_ms=1200)
        assert seen["checked"] >= 10, "it measured real text"
        assert seen["low"] == [], "text under 4.5:1 (3:1 when large)"

    def test_the_dialog(self, browser_ok, snapshots):
        opening = {"status": "listening", "lines": [], "stats": STATS, "tasks": snapshots["tasks"], "ask": ASK}
        seen = _render(lambda page: page.evaluate(CONTRAST, "home"), _script(snapshots, opening), wait_ms=1500)
        assert seen["low"] == []


DIALOG = """() => ({focus: document.activeElement.id, open: !document.getElementById('veil').hidden,
                   inert: document.querySelector('.shell').inert, calls: window.__calls})"""

ASK = {"id": 7, "message": "Delete x?", "action": "Delete a file", "target": "x", "details": "x — a file",
       "consequence": "Gone for good.", "tone": "danger", "verb": "Delete", "tool": "delete_path"}


class TestTheDialogHoldsFocus:
    def _with_ask(self, snap):
        return {"status": "listening", "lines": [], "stats": STATS, "tasks": snap["tasks"], "ask": ASK}

    def test_tab_goes_round_its_own_buttons(self, browser_ok, snapshots):
        async def check(page):
            await page.wait_for_timeout(800)
            stops = []
            for key in ["Tab", "Tab", "Tab", "Shift+Tab", "Shift+Tab"]:
                await page.keyboard.press(key)
                stops.append(await page.evaluate("document.activeElement.id"))
            return stops, await page.evaluate(DIALOG)

        stops, seen = _render(check, _script(snapshots, self._with_ask(snapshots)))
        assert stops == ["askReviewBtn", "askYes", "askNo", "askYes", "askReviewBtn"]
        assert seen["open"] and seen["inert"] is True, "the page behind is out of reach"

    def test_tab_passes_over_confirm_until_it_arms(self, browser_ok, snapshots):
        async def check(page):
            await page.evaluate("window.__nextAsk = %s" % json.dumps(ASK))
            await page.wait_for_function("!document.getElementById('veil').hidden")
            armed = await page.evaluate("!document.getElementById('askYes').disabled")
            stops = []
            for _ in range(3):
                await page.keyboard.press("Tab")
                stops.append(await page.evaluate("document.activeElement.id"))
            return armed, stops

        armed, stops = _render(check, _script(snapshots))
        assert not armed, "measured inside the moment before Confirm arms"
        assert stops == ["askReviewBtn", "askNo", "askReviewBtn"], "never stuck on a button that can't be pressed"

    def test_the_page_behind_cant_be_reached(self, browser_ok, snapshots):
        async def check(page):
            await page.wait_for_timeout(300)
            await page.evaluate("document.getElementById('input').value = 'hello'")
            await page.evaluate("document.getElementById('input').focus()")
            focus = await page.evaluate("document.activeElement.id")
            x, y = await page.evaluate("""() => { const b = document.getElementById('send').getBoundingClientRect();
                                                  return [b.x + b.width / 2, b.y + b.height / 2]; }""")
            await page.mouse.click(x, y)
            await page.wait_for_timeout(100)
            return focus, await page.evaluate(DIALOG)

        focus, seen = _render(check, _script(snapshots, self._with_ask(snapshots)))
        assert seen["inert"] is True and seen["open"]
        assert focus != "input", "the command box can't take focus behind the dialog"
        assert not any(c[0] == "send" for c in seen["calls"]), "a click behind the dialog sends nothing"

    def test_focus_goes_back_where_it_was(self, browser_ok, snapshots):
        async def check(page):
            await page.focus("#jobsSearch")
            await page.evaluate("window.__nextAsk = %s" % json.dumps(ASK))
            await page.wait_for_timeout(400)
            during = await page.evaluate(DIALOG)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(60)
            return during, await page.evaluate(DIALOG)

        during, after = _render(check, _script(snapshots), route="jobs")
        assert during["focus"] == "askNo" and during["inert"] is True
        assert after["focus"] == "jobsSearch" and after["inert"] is False and not after["open"]
        assert ["confirm_reply", 7, False] in after["calls"]


ANNOUNCED = "() => document.getElementById('announcer').textContent"


def _ended(tid, status, reply, error=""):
    return {"id": tid, "text": "x", "source": "typed", "status": status, "route": "model", "started": 1,
            "ms": 900, "steps": [], "reply": reply, "error": error, "plan": None, "reset": False,
            "again_of": None, "stopping": False, "stop_at": None, "v": tid}


class TestRepliesAreSaid:
    @pytest.mark.parametrize("task,said", [
        (_ended(21, "done", "It's 3 pm."), "Little: It's 3 pm."),
        (_ended(22, "failed", "", "The model is busy."), "Little: Didn't finish: The model is busy."),
        (_ended(23, "stopped", "Stopped."), "Little: Stopped."),
        (_ended(24, "done", "word " * 100), "Little: " + ("word " * 100).strip()[:240] + "…"),
    ])
    def test_when_a_task_ends(self, browser_ok, snapshots, task, said):
        async def check(page):
            await page.evaluate("window.__queue.push({status: 'listening', lines: [], tasks: %s})"
                                % json.dumps({"v": 30, "changed": [task]}))
            await page.wait_for_timeout(400)
            return await page.evaluate(ANNOUNCED)

        assert _render(check, _script(snapshots)) == said

    def test_the_announcer_is_outside_the_page_and_polite(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        shell_end = html.index('<div class="veil veil--top"')
        announcer = html.index('id="announcer"')
        assert announcer > shell_end, "outside the part that goes out of reach behind a dialog"
        assert 'role="status" aria-live="polite"' in html[announcer - 80:announcer + 80]

    def test_what_was_there_before_the_page_opened_isnt_said(self, browser_ok, snapshots):
        assert _render(lambda page: page.evaluate(ANNOUNCED), _script(snapshots)) == ""


class TestMotion:
    def test_nothing_moves_when_windows_asks(self, browser_ok, snapshots):
        async def check(page):
            await page.emulate_media(reduced_motion="reduce")
            await page.wait_for_timeout(300)
            return await page.evaluate("""() => document.getAnimations()
                .filter(a => a.playState === 'running' && (a.effect.getTiming().duration || 0) > 1).length""")

        assert _render(check, _script(snapshots)) == 0

    def test_touch_screens_get_bigger_targets(self):
        css = (ROOT / "ui" / "css" / "components.css").read_text(encoding="utf-8")
        block = css[css.index("@media (pointer: coarse)"):]
        assert "min-height: 44px" in block[:block.index("}\n}")]


# ============================================================= performance

MUTATIONS = """async (inside) => {
  let nodes = 0;
  const root = inside ? document.querySelector(inside) : document.body;
  const obs = new MutationObserver((list) => list.forEach(m => { nodes += m.addedNodes.length + m.removedNodes.length
                                                                          + (m.type === 'characterData' ? 1 : 0); }));
  obs.observe(root, {subtree: true, childList: true, characterData: true});
  await new Promise(r => setTimeout(r, 2000));
  obs.disconnect();
  return nodes;
}"""


def _every_poll(stats_js):
    """As Python does: the latest readings on every poll."""
    return """
      const realPoll = window.pywebview.api.poll;
      window.__tick = 0;
      window.pywebview.api.poll = async (since) => {
        const out = await realPoll(since); window.__tick += 1;
        out.status = 'listening';
        if (!window.__noStats) { out.stats = %s; window.__lastStats = out.stats; }
        return out; };""" % stats_js


class TestTheIdlePageDoesNoWork:
    """Measured before UI-10: about 360 elements rebuilt a second, on every
    section, with nothing changing."""

    @pytest.mark.parametrize("route", ["home", "jobs", "chat"])
    def test_unchanged_readings_redraw_nothing(self, browser_ok, snapshots, route):
        extra = _every_poll(json.dumps(STATS))
        nodes = _render(lambda page: page.evaluate(MUTATIONS, None), _script(snapshots, extra=extra),
                        route=route, wait_ms=900)
        assert nodes <= 10, f"{nodes} changes in 2 s with nothing new — only the clock should tick"

    def test_changing_readings_arent_drawn_where_nobody_sees_them(self, browser_ok, snapshots):
        stats = "Object.assign({}, %s, {system: Object.assign({}, %s.system, {cpu: window.__tick %% 100})})" % (
            json.dumps(STATS), json.dumps(STATS))

        async def check(page):
            hidden = await page.evaluate(MUTATIONS, ".home")
            # No more readings from here on, so only going back can draw them.
            await page.evaluate("window.__noStats = true")
            await page.wait_for_timeout(250)
            cpu_last = await page.evaluate("window.__lastStats.system.cpu")
            await page.click('.navlink[data-route="home"]')
            await page.wait_for_timeout(300)
            shown = await page.evaluate("document.querySelector('#gauges').textContent")
            return hidden, cpu_last, shown

        hidden, cpu_last, shown = _render(check, _script(snapshots, extra=_every_poll(stats)), route="jobs",
                                          wait_ms=900)
        assert hidden == 0, "Home's panels untouched while you're on Jobs"
        assert re.search(r"CPU.*?(\d+)%", shown), shown
        assert int(re.search(r"CPU.*?(\d+)%", shown).group(1)) == cpu_last, "the newest, on arrival"

    def test_on_home_they_are_drawn_as_they_change(self, browser_ok, snapshots):
        stats = "Object.assign({}, %s, {system: Object.assign({}, %s.system, {cpu: window.__tick %% 100})})" % (
            json.dumps(STATS), json.dumps(STATS))
        nodes = _render(lambda page: page.evaluate(MUTATIONS, "#gauges"),
                        _script(snapshots, extra=_every_poll(stats)), route="home", wait_ms=600)
        assert nodes > 10

    def test_the_mute_state_still_follows_everywhere(self, browser_ok, snapshots):
        muted = dict(STATS, voice=dict(STATS["voice"], speech="muted"))
        seen = _render(lambda page: page.evaluate(
            "[...document.querySelectorAll('#turns button')].filter(b => b.textContent === 'Speak').map(b => b.disabled)"),
            _script(snapshots, extra=_every_poll(json.dumps(muted))), route="chat", wait_ms=900)
        assert seen and all(seen), "Speak is off in Chat when voice is muted, though Home isn't showing"


# ================================================================== tools

class TestTheToolsList:
    def test_every_tool_once_with_its_words_and_whether_it_asks(self):
        from jarvis.tools.registry import FUNCTIONS, TOOL_SCHEMAS
        out = bridge.Api(assistant=Quiet()).tools()["tools"]
        assert sorted(t["name"] for t in out) == sorted(FUNCTIONS) == sorted(t["name"] for t in TOOL_SCHEMAS)
        assert {t["name"] for t in out if t["asks"]} == permissions.NEEDS_CONFIRMATION
        assert all(t["does"] for t in out)
        assert "Other" not in {t["group"] for t in out}, "every tool has a group"


TOOLS = """() => ({
  calls: window.__calls,
  summary: document.getElementById('toolsSummary').textContent,
  groups: [...document.querySelectorAll('#toolsList .tools-group')].map(g => g.dataset.group),
  names: [...document.querySelectorAll('#toolsList .tools-item')].map(i => i.dataset.tool),
  asking: [...document.querySelectorAll('#toolsList .tools-item')].filter(i => i.querySelector('.badge')).map(i => i.dataset.tool),
  runs: [...document.querySelectorAll('#toolsRuns .tools-run')].map(r => r.textContent),
  images: document.querySelectorAll('[data-view="tools"] img').length, ran: window.__ran || 0,
})"""


def _after(snap):
    """An id and a version newer than anything in the snapshot — ids keep
    counting across the whole suite."""
    return max(t["id"] for t in snap["tasks"]["changed"]) + 10, snap["tasks"]["v"] + 10


class TestTheToolsSection:
    def test_the_whole_list_grouped(self, browser_ok, snapshots):
        seen = _render(lambda page: page.evaluate(TOOLS), _script(snapshots), route="tools")
        assert len(seen["names"]) == len(snapshots["tools"]["tools"])
        assert seen["summary"] == f"{len(seen['names'])} tools · {len(permissions.NEEDS_CONFIRMATION)} ask first"
        assert sorted(seen["asking"]) == sorted(permissions.NEEDS_CONFIRMATION)
        assert seen["groups"] == sorted(seen["groups"])

    def test_search_and_the_ask_first_filter(self, browser_ok, snapshots):
        async def check(page):
            await page.fill("#toolsSearch", "whatsapp")
            await page.wait_for_timeout(200)
            searched = await page.evaluate(TOOLS)
            await page.fill("#toolsSearch", "")
            await page.check("#toolsAsking")
            await page.wait_for_timeout(200)
            return searched, await page.evaluate(TOOLS)

        searched, asking = _render(check, _script(snapshots), route="tools")
        said = [t["name"] for t in snapshots["tools"]["tools"]
                if "whatsapp" in f"{t['name']} {t['does']} {t['group']}".lower()]
        assert "send_whatsapp_message" in said and len(said) < len(snapshots["tools"]["tools"])
        assert sorted(searched["names"]) == sorted(said), "by name, its words, or its group — nothing else"
        assert sorted(asking["names"]) == sorted(permissions.NEEDS_CONFIRMATION)

    def test_what_ran_this_session_comes_from_the_task_record(self, browser_ok, snapshots):
        async def check(page):
            seen = await page.evaluate(TOOLS)
            await page.click("#toolsRuns .tools-task")
            await page.wait_for_timeout(150)
            return seen, await page.evaluate("location.hash")

        seen, where = _render(check, _script(snapshots), route="tools")
        assert len(seen["runs"]) == 1 and seen["runs"][0].startswith("find_jobs")
        assert "find jobs for me" in seen["runs"][0]
        assert where == "#/tasks", "a run opens its task"

    def test_your_answers_arent_tool_runs(self, browser_ok, snapshots):
        newer, v = _after(snapshots)
        task = dict(_ended(newer, "done", "Deleted."), text="delete old.txt", v=v, steps=[
            {"n": 0, "name": "delete_path", "detail": '{"path": "old.txt"}', "status": "done", "ms": 12,
             "at": 0.1, "part": None},
            {"n": 1, "name": "your answer", "detail": "approved", "question": "Delete old.txt?",
             "status": "done", "ms": None, "at": 0.2, "part": None}])

        async def check(page):
            await page.evaluate("window.__queue.push({status: 'listening', lines: [], tasks: %s})"
                                % json.dumps({"v": v, "changed": [task]}))
            await page.wait_for_timeout(400)
            return await page.evaluate(TOOLS)

        runs = _render(check, _script(snapshots), route="tools")["runs"]
        assert len(runs) == 2, runs
        assert runs[0].startswith("delete_path") and runs[1].startswith("find_jobs")
        assert not any("your answer" in r for r in runs), "a yes or no is yours, not a tool's"

    def test_the_checks_reply_comes_from_its_own_task(self, browser_ok, snapshots):
        first, v = _after(snapshots)

        def task(tid, text, status, reply, version):
            return dict(_ended(tid, status, reply), text=text, v=version)
        check_task, later = first, first + 1

        async def check(page):
            await page.click("#toolsCheck")
            await page.evaluate("window.__queue.push({status: 'listening', lines: [], tasks: %s})"
                                % json.dumps({"v": v + 1, "changed": [
                                    task(check_task, "check the tools", "active", "", v),
                                    task(later, "what time is it", "done", "It's 3 pm.", v + 1)]}))
            await page.wait_for_timeout(400)
            during = await page.evaluate("document.getElementById('toolsOut').textContent")
            await page.evaluate("window.__queue.push({status: 'listening', lines: [], tasks: %s})"
                                % json.dumps({"v": v + 2, "changed": [task(check_task, "check the tools", "done",
                                                                           "All 67 tools load.", v + 2)]}))
            await page.wait_for_timeout(400)
            return during, await page.evaluate("document.getElementById('toolsOut').textContent"), \
                await page.evaluate("window.__calls")

        during, after, calls = _render(check, _script(snapshots), route="tools")
        assert ["send", "check the tools"] in calls
        assert during == "Checking…", "a newer, unrelated reply isn't the check's"
        assert after == "All 67 tools load."

    def test_text_is_shown_as_text(self, browser_ok, snapshots):
        snap = json.loads(json.dumps(snapshots))
        snap["tools"]["tools"][0]["does"] = ATTACK
        snap["tools"]["tools"][0]["name"] = ATTACK
        seen = _render(lambda page: page.evaluate(TOOLS), _script(snap), route="tools")
        assert seen["images"] == 0 and seen["ran"] == 0
