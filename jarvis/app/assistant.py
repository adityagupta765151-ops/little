"""The loop that ties it together.

voice -> wake word -> fast router -> (if needed) AI brain -> speech
"""
from __future__ import annotations

import os
import re
import threading
import time

from . import demo, latency, recovery, stats, tasks
from ..ai import planner
from ..routing import router as _router
from ..routing.router import fast_route
from ..store import memory
from ..tools import reminders
from ..voice import Listener, conversation, speak, stop_speaking, wake_position
from ..voice.brief import for_speech
from .config import ASSISTANT_CALL, ASSISTANT_NAME, VOICE_ENABLED, WAKE_WORDS, log

# Showing every phrase it heard is the difference between "the mic is
# broken" and "it hears me but not my name".
SHOW_HEARD = os.getenv("JARVIS_SHOW_HEARD", "true").lower() != "false"

# How the assistant's own lines are marked in the activity log. The panel
# reads this prefix to tell its replies from everything else.
REPLY = f"{ASSISTANT_NAME}: "

SLEEP_PHRASES = ("go to sleep", "stop listening", "so jao",
                 f"goodbye {ASSISTANT_CALL.lower()}", "goodbye jarvis")
RESET_PHRASES = ("new conversation", "clear memory", "start fresh")
CALIBRATE_PHRASES = ("recalibrate mic", "calibrate mic", "recalibrate microphone",
                     "tune the mic", "mic calibrate")
STOP_PHRASES = ("stop", "cancel", "ruko", "chup")
# "Status report" was already the system health check before Chapter 40,
# and stays that; these are the dashboard's own words.
STATUS_PHRASES = ("everything at a glance", "show me everything at a glance", "how is everything",
                  "dashboard summary", "give me a dashboard summary")
DEMO_PHRASES = ("start the demo", "run the demo", "demo mode", "show me a demo", "start demo", "run demo",
                "demo dikhao", "demo chalao")
WAKE_CALIBRATE_PHRASES = ("calibrate the wake word", "calibrate wake word", "test the wake word",
                          "wake word test")

def strip_address(command: str) -> str:
    """Drop a leading "Little," and any stray quotes around the command.

    Speech already arrives with the wake word removed, but a typed command
    keeps it — and the panel invites you to type one. "Little, find jobs
    for me" would then miss every local pattern, fall through to the model,
    and take eighty seconds to do what the router does instantly.

    Only an opening address is removed. "What does little mean" is a
    question, not an instruction. The old name is stripped the same way.
    """
    text = (command or "").strip().strip("\"'“”‘’").strip()
    head = text[:40].lower()
    if head.startswith(("hey ", "ok ", "okay ")):
        text = text.split(" ", 1)[1] if " " in text else text

    end = wake_position(text[:40].lower())
    if end is not None and text[:end].strip().lower().rstrip(",.!?:; ") in _ADDRESS_FORMS:
        text = text[end:]
    return text.strip().lstrip(",.:;- ").strip().strip("\"'“”‘’").strip()


# The exact things someone says to get its attention, so only those are
# stripped and a sentence that merely mentions the name is left alone.
_ADDRESS_FORMS = {w.lower() for w in WAKE_WORDS} | {
    f"hey {w.lower()}" for w in WAKE_WORDS} | {f"ok {w.lower()}" for w in WAKE_WORDS}


# Local commands that still take real time, because they go to the network.
# Everything else on the fast path answers in milliseconds.
SLOW_COMMANDS = re.compile(
    r"\b(find|search)\b.*\bjobs?\b|\bjobs?\b.*\b(find|search)\b|"
    r"\bsummari[sz]e\b|\bresearch\b|\blook up\b|\bfind out\b|\bread (this |the )?page\b|"
    r"\bimport contacts?\b|nayi jobs", re.I)


class Jarvis:
    def __init__(self, log_fn=print, status_fn=lambda s: None) -> None:
        self.log = log_fn
        self.status = status_fn
        self.brain = None
        self.listener: Listener | None = None
        self.running = False
        self.muted = not VOICE_ENABLED       # JARVIS_VOICE_ENABLED=false starts it silent
        self._busy = threading.Lock()
        self.conversation_open = False       # listening for a follow-up without the name
        reminders.set_speaker(self.say)

    # ------------------------------------------------------------ control

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._voice_loop, daemon=True).start()

    def stop(self) -> None:
        self.running = False
        stop_speaking()
        self.status("offline")

    def interrupt(self) -> None:
        """Esc, the Stop button, or saying "stop": stop talking, and ask
        whatever is running to stop at its next step — a plan before its next
        step, the model before its next call or tool. Not the "stop" command
        itself, which is a task too."""
        stop_speaking()
        planner.cancel()
        demo.cancel()                        # Chapter 47: before its next step
        tasks.stop_open(exclude=tasks.current_id())

    # ------------------------------------------------------------ voice loop

    def _voice_loop(self) -> None:
        try:
            if self.listener is None:
                self.status("calibrating")
                self.listener = Listener()
        except Exception as e:  # noqa: BLE001
            log(f"mic init failed: {e}")
            self.log("I couldn't reach your microphone, so voice is off. Typed commands still work.")
            self.stop()
            return

        self.say(f"Hi, {ASSISTANT_CALL} here.")
        self.status("listening")
        misses = 0

        while self.running:
            try:
                heard = self.listener.listen(timeout=5, phrase_limit=10, wake=True)
            except ConnectionError:
                self.log("I can't reach the speech service. Check your internet.")
                time.sleep(5)
                continue
            if not self.running:
                continue
            if not heard:
                if getattr(self.listener, "kept_here", False):
                    misses = 0              # it heard someone; just not its name
                    continue
                misses += 1
                # Long silence usually means the mic is on the wrong device
                # or the room got louder than it was at startup.
                if misses == 25:
                    self.log("I haven't made out anything in a while. Say "
                             "recalibrate mic, or list microphones to pick another.")
                continue
            misses = 0

            end = wake_position(heard)
            if end is None:
                if SHOW_HEARD:
                    self.log(f"   heard: {heard}")
                continue

            command = heard[end:].strip(" ,.!?")
            if not command:
                self.status("waiting for command")
                self.say("Yes?")
                command = self.listener.listen(timeout=7, phrase_limit=20) or ""

            if command:
                self.handle(command, source="voice")
                self._follow_up()
            if self.running:
                self.status("listening")

    def _follow_up(self) -> None:
        """Conversation mode (Chapter 35): after answering, listen a little
        longer without needing the name — up to a few follow-ups in a row,
        until a silence, or until stop / never mind."""
        self.conversation_open = True
        turns = 0
        while (self.running and self.conversation_open and conversation.FOLLOW_UP > 0
               and turns < conversation.MAX_FOLLOW_UPS):
            self.status("waiting for command")
            try:
                heard = self.listener.listen(timeout=conversation.FOLLOW_UP, phrase_limit=15)
            except ConnectionError:
                break
            if not heard or not self.running:
                break
            end = wake_position(heard)
            command = (heard[end:] if end is not None else heard).strip(" ,.!?")
            if not command:
                break
            turns += 1
            self.handle(command, source="voice")
        self.conversation_open = False

    # ------------------------------------------------------------ commands

    def handle(self, command: str, source: str = "typed", again_of: int | None = None) -> None:
        """One command, start to finish, recorded as one task.

        The task is what the window's Home shows: what's running, how it's
        going, and how it ended. Its outcome is decided here, from what the
        code knows — an error raised, a plan that stopped on a failed step —
        never from how the reply happens to be worded. Its reply is what
        Chat shows.
        """
        self.log(f"You: {command}")
        stats.note_command()
        task = tasks.start(command, source, again_of=again_of)
        outcome = {"status": tasks.DONE, "error": ""}
        try:
            self._handle(command, outcome)
        except Exception as e:  # noqa: BLE001
            outcome.update(status=tasks.FAILED, error=str(e) or type(e).__name__)
            raise
        finally:
            tasks.finish(outcome["status"], outcome["error"], task_id=task)

    def _handle(self, command: str, outcome: dict) -> None:
        command = conversation.resolve(strip_address(command))    # "close it" -> "close chrome"
        low = command.lower().strip()

        # Each early answer is also recorded as the task's reply, so Chat
        # shows what was said — even the ones that are only spoken.
        if not low:                      # someone just said or typed the name
            tasks.route("local")
            tasks.path("fast")
            tasks.reply("Yes?")
            self.say("Yes?")
            return
        if low in STOP_PHRASES:
            tasks.route("local")
            tasks.path("fast")
            self.interrupt()
            self.conversation_open = False
            tasks.reply("Stopped.")
            self.log(f"{REPLY}Stopped.")
            return
        if conversation.never_mind(low):
            # Not sent to the model: it means "drop it", not a question.
            tasks.route("local")
            tasks.path("fast")
            self.interrupt()
            self.conversation_open = False
            tasks.reply("Okay.")
            self.log(f"{REPLY}Okay.")
            return
        if any(p in low for p in SLEEP_PHRASES):
            tasks.route("local")
            tasks.path("fast")
            tasks.reply("Okay, going to sleep.")
            self.say("Okay, going to sleep.")
            self.stop()
            return
        if low.strip(" ?.!") in STATUS_PHRASES:
            # Dashboard 2.0 in words (Chapter 40), with this assistant's own
            # microphone and voice state, which only it knows.
            from . import overview
            tasks.route("local")
            tasks.path("fast")
            said = overview.report(self)
            tasks.reply(said)
            self.log(f"{REPLY}{said}")
            self.say("Here's where everything stands. It's on screen.")
            return
        if low.strip(" ?.!") in DEMO_PHRASES:
            # Demo mode (Chapter 47): about fifty seconds of real commands,
            # on its own thread, each one its own task.
            tasks.route("local")
            tasks.path("fast")
            def first(said):
                tasks.reply(said)
                self.log(f"{REPLY}{said}")
            demo.start(self, first)
            return
        if any(p in low for p in WAKE_CALIBRATE_PHRASES):
            tasks.route("local")
            tasks.path("fast")
            if self.listener is None or not hasattr(self.listener, "calibrate_wake"):
                said = "The mic isn't on yet. Click the core first."
                outcome.update(status=tasks.FAILED, error="The mic isn't on yet.")
            else:
                self.say("Stay quiet for a few seconds while I listen to the room.")
                said = self.listener.calibrate_wake()
            tasks.reply(said)
            self.log(f"{REPLY}{said}")
            return
        if any(p in low for p in CALIBRATE_PHRASES):
            tasks.route("local")
            tasks.path("fast")
            if self.listener is None:
                tasks.reply("The mic isn't on yet. Click the core first.")
                self.log(f"{REPLY}The mic isn't on yet. Click the core first.")
                outcome.update(status=tasks.FAILED, error="The mic isn't on yet.")
                return
            self.say("Stay quiet for a moment.")
            result = self.listener.calibrate(1.8)
            tasks.reply(result)
            self.log(f"{REPLY}{result}")
            self.say("Done. Try me again.")
            return

        if re.fullmatch(r"(list |show )?(my )?(microphones|mics|mic list)\.?", low):
            tasks.route("local")
            tasks.path("fast")
            from ..voice import microphones
            found = microphones()
            tasks.reply(found)
            self.log(found)
            return

        if any(p in low for p in RESET_PHRASES):
            tasks.route("local")
            tasks.path("fast")
            if self.brain:
                self.brain.reset()
            tasks.mark_reset()
            tasks.reply("Fresh start. What's next?")
            self.say("Fresh start. What's next?")
            return

        with self._busy:
            self.status("executing")
            # Most local commands answer instantly, but a job search calls six
            # boards and a page summary downloads a page. Silence for fifteen
            # seconds is indistinguishable from being broken, so say so first.
            if SLOW_COMMANDS.search(low):
                self._announce("On it, one moment.")
            started = time.perf_counter()
            try:
                reply = fast_route(command)  # usually milliseconds, no model call
            except Exception as e:  # noqa: BLE001
                log(f"router failed: {e}")
                reply = None
            latency.record("router", (time.perf_counter() - started) * 1000)
            if reply is not None:
                tasks.route("local")
                tasks.path(_router.last_path())

            if reply is None:
                self.status("thinking")
                try:
                    if self.brain is None:
                        from ..ai.brain import Brain
                        self.brain = Brain()

                    if conversation.wants_to_continue(low) and planner.resumable():
                        # Pick a stopped plan up where it stopped.
                        tasks.route("plan")
                        tasks.path("agent")
                        planned = {}
                        reply = planner.resume(self._planning_brain(), self.log, self.status, outcome=planned)
                        if planned.get("status") in (tasks.FAILED, tasks.STOPPED):
                            outcome.update(status=planned["status"], error=planned.get("error", ""))
                    elif planner.should_plan(command):
                        # Several parts to this one: plan it, then work through.
                        tasks.route("plan")
                        tasks.path("agent")
                        planned: dict = {}
                        reply = planner.run(command, self._planning_brain(),
                                            self.log, self.status, outcome=planned)
                        if planned.get("status") in (tasks.FAILED, tasks.STOPPED):
                            outcome.update(status=planned["status"],
                                           error=planned.get("error", ""))
                    else:
                        tasks.route("model")
                        tasks.path("ai")
                        reply = self.brain.ask(command, on_action=self._show_action)
                except tasks.Stopped:
                    reply = "Stopped."
                    outcome.update(status=tasks.STOPPED)
                except Exception as e:  # noqa: BLE001
                    log(f"brain failed: {e}")
                    reply = str(e) if str(e) else "Something went wrong on my side."
                    outcome.update(status=tasks.FAILED, error=reply)

            self.status("listening" if self.running else "offline")

        # The panel shows all of it; the voice says a sentence or two.
        tasks.reply(reply)
        self.log(f"{REPLY}{reply}")
        if outcome["status"] == tasks.FAILED and recovery.with_offline_help(reply) != reply:
            # Chapter 42: the model is out of reach — say what still works.
            self.log(recovery.STILL_WORKS)
        if demo.quiet_here():
            return                           # a demo step: on screen only, and not in your history
        memory.log_turn(command, reply)
        done = tasks.get(tasks.current_id()) if tasks.current_id() else None
        conversation.note(command, reply, (done or {}).get("route") or "")
        self.say(for_speech(reply))

    def _planning_brain(self):
        """The planner calls ask() without knowing about the activity log,
        so hand it a brain that already reports its tool calls."""
        brain = self.brain
        show = self._show_action

        class Reporting:
            def ask(self, text):
                return brain.ask(text, on_action=show)

            @property
            def history(self):           # the planner reads what the tools returned
                return brain.history

        return Reporting()

    def _show_action(self, name: str, args: dict) -> None:
        # As much of the arguments as the tool's logging policy allows
        # (Chapter 38): a message's text or a contact's number isn't shown.
        from ..tools.catalog import log_policy
        self.log(f"   > {name} {tasks.preview(args if isinstance(args, dict) else {}, log_policy(name))}")

    def say(self, text: str) -> None:
        if self.muted:
            return
        self.status("speaking")
        speak(text)
        # Back to what it was doing. With the mic off that's offline — left
        # at "speaking", the window read LITTLE as awake, and the next click
        # on the orb switched it off instead of on.
        self.status("listening" if self.running else "offline")

    def regenerate(self, command: str, task_id: int) -> str:
        """Chat's "Ask again": the model answers the same question afresh,
        as if its last answer hadn't happened.

        Only for the model's latest plain answer — one that ran no tools —
        so asking again can't repeat an action. Returns "" when it has
        started, or why it can't.
        """
        if self.brain is None:
            return "There's no answer from the model to ask again."
        with self._busy:
            forgotten = self.brain.forget_last(strip_address(command))
        if not forgotten:
            return "Only the latest answer can be asked again."
        threading.Thread(target=self.handle, args=(command,),
                         kwargs={"again_of": task_id}, daemon=True).start()
        return ""

    def _announce(self, text: str) -> None:
        """A heads-up spoken before the work, not after it.

        say() ends by putting the status back to speaking or listening,
        which is right when the reply is the last thing that happens and
        wrong here: the work is still to come, and a panel that reads
        SPEAKING while six job boards are being called tells the user
        nothing is happening.
        """
        self.say(text)
        self.status("executing")
