"""Launching and closing desktop applications, whatever the OS."""
from __future__ import annotations

import platform
import re
import shutil
import subprocess

from ..app.config import log

SYSTEM = platform.system()

# What the user says -> what to actually launch, per OS.
APPS = {
    "chrome": {"Windows": "chrome", "Darwin": "Google Chrome", "Linux": "google-chrome"},
    "edge": {"Windows": "msedge", "Darwin": "Microsoft Edge", "Linux": "microsoft-edge"},
    "firefox": {"Windows": "firefox", "Darwin": "Firefox", "Linux": "firefox"},
    "vs code": {"Windows": "code", "Darwin": "Visual Studio Code", "Linux": "code"},
    "vscode": {"Windows": "code", "Darwin": "Visual Studio Code", "Linux": "code"},
    "whatsapp": {"Windows": "whatsapp", "Darwin": "WhatsApp", "Linux": "whatsapp"},
    "spotify": {"Windows": "spotify", "Darwin": "Spotify", "Linux": "spotify"},
    "notepad": {"Windows": "notepad", "Darwin": "TextEdit", "Linux": "gedit"},
    "calculator": {"Windows": "calc", "Darwin": "Calculator", "Linux": "gnome-calculator"},
    "explorer": {"Windows": "explorer", "Darwin": "Finder", "Linux": "nautilus"},
    "terminal": {"Windows": "wt", "Darwin": "Terminal", "Linux": "gnome-terminal"},
    "settings": {"Windows": "ms-settings:", "Darwin": "System Settings", "Linux": "gnome-control-center"},
}

# Processes to kill, by app name, on Windows.
PROCESSES = {
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "vs code": "Code.exe",
    "vscode": "Code.exe",
    "whatsapp": "WhatsApp.exe",
    "spotify": "Spotify.exe",
    "notepad": "notepad.exe",
}


# Chapter 48: on Windows an app is started through the command line
# (`start "" "<name>"`), so a name with a quote, &, |, <, >, ^ or % in it
# could run a second command. No app name needs them, so they're refused.
# The model can call open_app without asking you, which is why this matters.
UNSAFE_FOR_THE_COMMAND_LINE = re.compile(r'["&|<>^%\r\n\t\x00]')
# Closing is by process name: only letters, digits, spaces, dots, + and -,
# starting with a letter or digit — so no wildcard ("*" closed everything).
CLOSABLE = re.compile(r"[a-z0-9][a-z0-9 ._+-]{0,59}")


def resolve(name: str) -> str | None:
    key = name.lower().strip()
    entry = APPS.get(key)
    return entry.get(SYSTEM) if entry else None


def open_app(name: str) -> str:
    """Open an application by its everyday name."""
    target = resolve(name) or name
    if UNSAFE_FOR_THE_COMMAND_LINE.search(str(target)):
        log("refused to open an app whose name has command-line characters in it")
        return "I won't open that: an app's name doesn't have quotes, &, |, <, >, ^ or % in it."
    try:
        if SYSTEM == "Windows":
            subprocess.Popen(f'start "" "{target}"', shell=True)
        elif SYSTEM == "Darwin":
            subprocess.Popen(["open", "-a", target])
        else:
            if not shutil.which(target):
                return f"I couldn't open {name} because it doesn't seem to be installed."
            subprocess.Popen([target])
        return f"Opening {name}."
    except Exception as e:  # noqa: BLE001
        log(f"open_app({name}) failed: {e}")
        return f"I couldn't open {name}. It may not be installed."


def close_app(name: str) -> str:
    """Close an application."""
    key = name.lower().strip()
    if not CLOSABLE.fullmatch(key):
        return f"I won't close “{name[:40]}”: say the app's name, like Chrome or Spotify."
    try:
        if SYSTEM == "Windows":
            process = PROCESSES.get(key, f"{key}.exe")
            result = subprocess.run(
                ["taskkill", "/im", process, "/f"], capture_output=True, text=True
            )
            if result.returncode != 0:
                return f"{name} doesn't seem to be running."
        elif SYSTEM == "Darwin":
            subprocess.run(["osascript", "-e", f'quit app "{resolve(name) or name}"'])
        else:
            subprocess.run(["pkill", "-f", re.sub(r"([.+])", r"\\\1", key)])   # a dot is a dot, not "anything"
        return f"Closed {name}."
    except Exception as e:  # noqa: BLE001
        log(f"close_app({name}) failed: {e}")
        return f"I couldn't close {name}."
