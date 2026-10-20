"""LITTLE launcher — the plain window, for when pywebview isn't installed.

Click the core to wake Little. Ctrl+Space does the same from the window,
Esc stops whatever it's saying. Type in the box if you'd rather not talk.
"""
from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

from jarvis import tools
from jarvis.app.config import API_KEY, ASSISTANT_CALL, ASSISTANT_NAME, WORKSPACE
from jarvis.app.assistant import Jarvis

BG = "#070b10"
PANEL = "#0f1821"
CYAN = "#39d0ff"
CORE_GLOW = "#0e5a75"
DIM = "#173848"
TEXT = "#d4e9f2"
MUTED = "#6a8795"

STATUS_TEXT = {
    "offline": "Offline. Click the core to wake me up.",
    "calibrating": "Tuning the mic to your room. Stay quiet for a second.",
    "listening": f"Listening. Say \"{ASSISTANT_CALL}\" followed by a command.",
    "waiting for command": "I'm listening...",
    "thinking": "Thinking...",
    "executing": "Working on it...",
    "speaking": "Speaking. Press Esc to cut me off.",
}


def mix(a: str, b: str, t: float) -> str:
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


class Launcher:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.online = False
        self.phase = 0.0

        root.title(ASSISTANT_NAME)
        root.configure(bg=BG)
        root.geometry("540x740")
        root.minsize(440, 600)

        tk.Label(root, text=ASSISTANT_NAME, font=("Segoe UI", 22, "bold"), fg=CYAN, bg=BG).pack(pady=(16, 0))
        tk.Label(root, text=f"Workspace: {WORKSPACE}", font=("Segoe UI", 9), fg=MUTED, bg=BG).pack()

        self.canvas = tk.Canvas(root, width=230, height=230, bg=BG, highlightthickness=0, cursor="hand2")
        self.canvas.pack(pady=12)
        self.ring_outer = self.canvas.create_oval(10, 10, 220, 220, outline=DIM, width=3)
        self.ring_mid = self.canvas.create_oval(34, 34, 196, 196, outline=DIM, width=2, dash=(8, 5))
        self.core = self.canvas.create_oval(68, 68, 162, 162, fill=PANEL, outline=DIM, width=2)
        self.core_label = self.canvas.create_text(115, 115, text="Activate", fill=MUTED,
                                                  font=("Segoe UI", 12, "bold"))
        self.canvas.bind("<Button-1>", lambda _e: self.toggle())
        root.bind("<Control-space>", lambda _e: self.toggle())
        root.bind("<Escape>", lambda _e: self.jarvis.interrupt())

        self.status_var = tk.StringVar(value=STATUS_TEXT["offline"])
        tk.Label(root, textvariable=self.status_var, font=("Segoe UI", 11), fg=TEXT, bg=BG,
                 wraplength=480).pack()

        controls = tk.Frame(root, bg=BG)
        controls.pack(pady=(8, 0))
        self.mute_var = tk.StringVar(value="Mute voice")
        for label, command in (
            (self.mute_var, self.toggle_mute),
            ("Stop", lambda: self.jarvis.interrupt()),
            ("Close browser", self.close_browser),
            ("Clear log", self.clear_log),
        ):
            options = {"textvariable": label} if isinstance(label, tk.StringVar) else {"text": label}
            tk.Button(controls, command=command, bg=PANEL, fg=TEXT, relief="flat",
                      font=("Segoe UI", 9), padx=10, **options).pack(side="left", padx=3)

        self.logbox = scrolledtext.ScrolledText(root, height=13, bg=PANEL, fg=TEXT, relief="flat",
                                                font=("Consolas", 10), wrap="word", state="disabled",
                                                padx=10, pady=8)
        self.logbox.tag_config("you", foreground=CYAN)
        self.logbox.tag_config("tool", foreground=MUTED)
        self.logbox.pack(fill="both", expand=True, padx=16, pady=(12, 8))

        row = tk.Frame(root, bg=BG)
        row.pack(fill="x", padx=16, pady=(0, 16))
        self.entry = tk.Entry(row, bg=PANEL, fg=TEXT, insertbackground=CYAN, relief="flat",
                              font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.entry.bind("<Return>", lambda _e: self.send_typed())
        tk.Button(row, text="Send", command=self.send_typed, bg=CYAN, fg=BG, relief="flat",
                  activebackground=TEXT, font=("Segoe UI", 10, "bold"), padx=16).pack(side="left", padx=(8, 0))

        self.jarvis = Jarvis(log_fn=lambda m: self.events.put(("log", m)),
                             status_fn=lambda s: self.events.put(("status", s)))
        tools.set_confirm(self.confirm)

        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(100, self._poll)
        root.after(40, self._animate)

        if not API_KEY:
            self._log("No GEMINI_API_KEY found. Add it to the .env file, then restart.")

    # ------------------------------------------------------------ actions

    def toggle(self) -> None:
        if self.online:
            self.jarvis.stop()
        else:
            self.online = True
            self.jarvis.start()

    def toggle_mute(self) -> None:
        self.jarvis.muted = not self.jarvis.muted
        self.mute_var.set("Unmute voice" if self.jarvis.muted else "Mute voice")

    def close_browser(self) -> None:
        def job():
            from jarvis.tools import browser
            self.events.put(("log", browser.close_browser()))
        threading.Thread(target=job, daemon=True).start()

    def send_typed(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        threading.Thread(target=self.jarvis.handle, args=(text,), daemon=True).start()

    def confirm(self, message: str) -> bool:
        """Called from a worker thread, so the dialog opens on the UI thread."""
        answer = {}
        done = threading.Event()

        def ask():
            # Opens on No, as the panel's dialog does: Enter alone must
            # never approve something that can't be undone.
            answer["ok"] = messagebox.askyesno(f"{ASSISTANT_CALL} needs your OK", message,
                                               parent=self.root, default=messagebox.NO)
            done.set()

        self.root.after(0, ask)
        done.wait()
        return answer.get("ok", False)

    def clear_log(self) -> None:
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")

    def quit(self) -> None:
        self.jarvis.stop()
        try:
            from jarvis.tools import browser
            browser.close_browser()
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()

    # ------------------------------------------------------------ UI updates

    def _log(self, message: str) -> None:
        tag = "you" if message.startswith("You:") else "tool" if message.startswith("   >") else None
        self.logbox.configure(state="normal")
        self.logbox.insert("end", message + "\n", tag)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _poll(self) -> None:
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == "log":
                self._log(value)
            else:
                self.online = value != "offline"
                self.status_var.set(STATUS_TEXT.get(value, value))
        self.root.after(100, self._poll)

    def _animate(self) -> None:
        c = self.canvas
        if self.online:
            self.phase += 0.12
            glow = (math.sin(self.phase) + 1) / 2
            c.itemconfig(self.ring_outer, outline=CYAN, width=2 + glow * 3)
            c.itemconfig(self.ring_mid, outline=mix(DIM, CYAN, 0.6), dashoffset=int(self.phase * 12) % 13)
            c.itemconfig(self.core, outline=CYAN, fill=mix(PANEL, CORE_GLOW, glow))
            c.itemconfig(self.core_label, text="Online", fill=CYAN)
        else:
            c.itemconfig(self.ring_outer, outline=DIM, width=3)
            c.itemconfig(self.ring_mid, outline=DIM)
            c.itemconfig(self.core, outline=DIM, fill=PANEL)
            c.itemconfig(self.core_label, text="Activate", fill=MUTED)
        self.root.after(40, self._animate)


if __name__ == "__main__":
    root = tk.Tk()
    Launcher(root)
    root.mainloop()
