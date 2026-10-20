"""LITTLE with the web interface.

The window is a real browser view, so the panel can be styled properly.
What the page may ask Python to do lives in jarvis/app/bridge.py; this file
only opens the window.

If pywebview won't install, launcher.py still runs the plain window.
"""
from __future__ import annotations

try:
    import webview
except ImportError:
    raise SystemExit(
        "The web interface needs pywebview. In the project folder run:\n"
        "    pip install pywebview\n"
        "Or run the plain window instead:  python launcher.py"
    )

from jarvis.app.bridge import Api
from jarvis.app.config import APP_DIR, ASSISTANT_NAME

UI = APP_DIR / "ui" / "index.html"


def main() -> None:
    api = Api()
    # Now and then, a suggestion from what's already on this computer
    # (Chapter 36). Never acts; off with JARVIS_PROACTIVE=off or "stop suggestions".
    # Outside tools over MCP (Chapter 39), only if mcp_servers.json lists some.
    from jarvis.tools import external
    for problem in external.load():
        api.lines.put(f"Outside tools: {problem}")
    from jarvis.app import proactive
    proactive.start(lambda text: api.lines.put(f"Suggestion: {text}"), speak=api.jarvis.say,
                    muted=lambda: api.jarvis.muted)
    window = webview.create_window(
        ASSISTANT_NAME,
        str(UI),
        js_api=api,
        width=1280,
        height=800,
        # Narrow enough to sit beside another window or be phone-width; every
        # section has a layout down to this (tests/test_final_polish.py).
        min_size=(480, 560),
        background_color="#060910",
    )

    def shutdown():
        api.jarvis.stop()
        proactive.stop()
        external.unload()
        try:
            from jarvis.tools import browser
            browser.close_browser()
        except Exception:  # noqa: BLE001
            pass

    window.events.closing += shutdown
    webview.start()


if __name__ == "__main__":
    main()
