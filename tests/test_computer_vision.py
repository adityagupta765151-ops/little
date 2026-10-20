"""Chapter 29 — understanding the screen, and acting on it only when sure.

Screenshots are captured (and scaled back to the screen), the model's
answer about where something is is checked before anything uses it, and a
click from a picture needs all three: the model sure, the target not
something that could pay, send, submit or delete, and your yes. A page in
LITTLE's own browser is clicked by its words, with no picture at all.
"""
from __future__ import annotations

import json
import sys
import types

import pytest
from PIL import Image

from jarvis import tools
from jarvis.app import config
from jarvis.routing.router import fast_route
from jarvis.tools import browser_agent, screen
from jarvis.tools.registry import FUNCTIONS, TOOL_SCHEMAS


@pytest.fixture
def display(monkeypatch):
    """A 3200 x 1800 screen; the picture the model sees is 1600 x 900."""
    import PIL.ImageGrab
    monkeypatch.setattr(PIL.ImageGrab, "grab", lambda *a, **k: Image.new("RGB", (3200, 1800), "white"))
    monkeypatch.setattr(browser_agent, "observe", lambda start=False: {"error": "No page is open in my browser."})


@pytest.fixture
def model(monkeypatch):
    said = {"reply": "", "asked": []}

    def ask(data, question):
        said["asked"].append((len(data), question))
        if isinstance(said["reply"], Exception):
            raise said["reply"]
        return said["reply"] if isinstance(said["reply"], str) else json.dumps(said["reply"])
    monkeypatch.setattr(screen, "ask_about_image", ask)
    return said


@pytest.fixture
def mouse(monkeypatch):
    clicks = []
    fake = types.SimpleNamespace(click=lambda x, y: clicks.append((x, y)))
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return clicks


@pytest.fixture
def answer():
    asked = {"asks": [], "yes": False}
    tools.set_confirm(lambda ask: asked["asks"].append(ask) or asked["yes"])
    yield asked
    tools.set_confirm(lambda _m: False)


def found(element="Save", box=(700, 400, 200, 100), confidence=0.95, risky=False):
    return {"found": True, "element": element, "box": list(box), "confidence": confidence, "risky": risky}


class TestCapturing:
    def test_a_screenshot_is_saved_in_the_memory_folder(self, display):
        reply = screen.take_screenshot()
        assert reply.startswith("Screenshot saved to ") and str(config.MEMORY_DIR) in reply
        path = reply.removeprefix("Screenshot saved to ").rstrip(".")
        assert Image.open(path).size == (1600, 900)

    def test_the_sizes_come_with_it(self, display):
        data, screen_size, picture_size = screen._capture()
        assert data.startswith(b"\x89PNG") and screen_size == (3200, 1800) and picture_size == (1600, 900)

    def test_no_way_to_capture(self, monkeypatch):
        import PIL.ImageGrab
        monkeypatch.setattr(PIL.ImageGrab, "grab", lambda *a, **k: (_ for _ in ()).throw(OSError("no display")))
        monkeypatch.setitem(sys.modules, "pyautogui", None)
        assert screen.take_screenshot().startswith("I couldn't capture the screen.")
        assert screen.locate("Save")["why"].startswith("I couldn't capture the screen.")


class TestRecognising:
    def test_a_position_is_scaled_back_to_the_screen(self, display, model):
        model["reply"] = found()
        seen = screen.locate("the Save button")
        assert seen == {"found": True, "element": "Save", "center": (1600, 900), "confidence": 0.95,
                        "risky": False, "why": ""}
        assert "Don't guess a position." in model["asked"][0][1]

    def test_said_plainly_with_how_sure(self, display, model):
        model["reply"] = found()
        assert screen.find_on_screen("Save") == \
            "“Save” looks to be at (1600, 900) on your screen — sure (95% by the model's own estimate)."
        model["reply"] = found(confidence=0.6)
        assert "— not sure (60%" in screen.find_on_screen("Save")

    def test_risky_things_are_named_as_such(self, display, model):
        model["reply"] = found("Delete account", confidence=0.99)
        assert screen.find_on_screen("Delete account").endswith("so I won't click it.")

    @pytest.mark.parametrize("reply,why", [
        ("I think it's in the top left", "I couldn't read an answer about the screen."),
        ("{not json}", "I couldn't read an answer about the screen."),
        ({"found": True, "element": "Save", "box": [1, 1, 5, 5]}, "The answer didn't say how sure it was."),
        ({"found": True, "element": "Save", "box": [1, 1, 5, 5], "confidence": "high"},
         "The answer didn't say how sure it was."),
        (found(box=(1500, 800, 400, 200)), "The position given wasn't on the screenshot, so I won't use it."),
        (found(box=(10, 10, 0, 20)), "The position given wasn't on the screenshot, so I won't use it."),
        (found(box=(-5, 10, 20, 20)), "The position given wasn't on the screenshot, so I won't use it."),
        ({"found": False, "confidence": 0.9}, "I can't see “Save” on the screen."),
    ])
    def test_an_answer_that_cant_be_used_counts_as_not_found(self, display, model, reply, why):
        model["reply"] = reply
        seen = screen.locate("Save")
        assert seen["found"] is False and seen["why"] == why

    def test_the_model_unreachable(self, display, model):
        model["reply"] = RuntimeError("I can't reach the internet right now.")
        assert screen.locate("Save")["why"] == "I can't reach the internet right now."


class TestClickingOnlyWhenSure:
    def test_sure_safe_and_you_say_yes(self, display, model, mouse, answer):
        model["reply"] = found()
        answer["yes"] = True
        assert screen.click_on_screen("Save") == "Clicked “Save” at (1600, 900)."
        assert mouse == [(1600, 900)]
        parts = answer["asks"][0].parts()
        assert parts["action"] == "Click on your screen" and "95% sure" in parts["details"]

    def test_you_say_no(self, display, model, mouse, answer):
        model["reply"] = found()
        assert screen.click_on_screen("Save") == "You said no, so I didn't click."
        assert mouse == []

    def test_no_answer_is_a_no(self, display, model, mouse):
        tools.set_confirm(lambda ask: None)
        try:
            model["reply"] = found()
            assert screen.click_on_screen("Save") == "You said no, so I didn't click."
        finally:
            tools.set_confirm(lambda _m: False)
        assert mouse == []

    def test_not_sure_enough_asks_nothing_and_clicks_nothing(self, display, model, mouse, answer):
        model["reply"] = found(confidence=0.7)
        reply = screen.click_on_screen("Save")
        assert "only 70% sure, so I didn't click" in reply
        assert mouse == [] and answer["asks"] == []

    @pytest.mark.parametrize("element,flag", [("Delete account", False), ("Pay now", False),
                                              ("Install update", False), ("Continue", True)])
    def test_risky_is_never_clicked_from_a_picture(self, display, model, mouse, answer, element, flag):
        model["reply"] = found(element, confidence=0.99, risky=flag)
        answer["yes"] = True
        assert screen.click_on_screen(element).endswith("click it yourself.")
        assert mouse == [] and answer["asks"] == []

    def test_not_found_clicks_nothing(self, display, model, mouse, answer):
        model["reply"] = {"found": False, "confidence": 0.2}
        assert screen.click_on_screen("Save") == "I can't see “Save” on the screen. I didn't click anything."
        assert mouse == []

    def test_nothing_named_clicks_nothing(self, display, model, mouse, answer):
        assert screen.click_on_screen("  ") == "Tell me what to click."
        assert screen.find_on_screen("") == "Tell me what to look for."
        assert mouse == [] and model["asked"] == []

    def test_no_way_to_click(self, display, model, answer, monkeypatch):
        monkeypatch.setitem(sys.modules, "pyautogui", None)
        model["reply"] = found()
        answer["yes"] = True
        assert screen.click_on_screen("Save").startswith("I couldn't click")


class TestTheBrowserFirst:
    def test_a_page_in_littles_browser_is_clicked_by_its_words(self, monkeypatch, mouse):
        page = {"url": "https://example.com", "buttons": [{"text": "Save draft", "submit": False}], "links": []}
        monkeypatch.setattr(browser_agent, "observe", lambda start=False: page)
        done = []
        monkeypatch.setattr(browser_agent, "act", lambda step, seen: done.append(step) or (True, "Clicked “Save”."))
        monkeypatch.setattr(screen, "_capture", lambda: pytest.fail("a screenshot was taken"))
        assert screen.click_on_screen("Save") == "Clicked “Save”. (in my browser, by its words — no picture needed)"
        assert done == [{"do": "click", "target": "Save"}] and mouse == []

    def test_its_checks_still_apply(self, monkeypatch, mouse):
        page = {"url": "https://example.com", "buttons": [{"text": "Place order", "submit": True}], "links": []}
        monkeypatch.setattr(browser_agent, "observe", lambda start=False: page)
        monkeypatch.setattr(browser_agent, "_ask", lambda *a: False)
        assert screen.click_on_screen("Place order").startswith("You said no, so I didn't.")


class TestReachingIt:
    def test_the_tools(self):
        assert FUNCTIONS["find_on_screen"] is screen.find_on_screen
        assert FUNCTIONS["click_on_screen"] is screen.click_on_screen
        described = {t["name"]: t["description"] for t in TOOL_SCHEMAS}
        assert "clicks nothing" in described["find_on_screen"]
        assert "only after the user says yes" in described["click_on_screen"]

    def test_by_command(self, monkeypatch):
        monkeypatch.setattr(screen, "find_on_screen", lambda what: f"<find {what}>")
        monkeypatch.setattr(screen, "click_on_screen", lambda what: f"<click {what}>")
        assert fast_route("where is the save button on screen?") == "<find save button>"
        assert fast_route("Click the OK button on my screen") == "<click OK button>"
        assert fast_route("look at my screen") != "<find>", "describing the screen is unchanged"
