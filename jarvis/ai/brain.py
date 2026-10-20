"""The AI layer: history, tool calling, and the loop that keeps going
until the job is done. The HTTP side lives in llm.py."""
from __future__ import annotations

from ..app import tasks
from ..tools.registry import TOOL_SCHEMAS, execute_tool
from .prompts import SYSTEM
from .provider import call_gemini

MAX_STEPS = 25
MAX_MESSAGES = 40
NOT_RUN = "Not run: the user stopped this before it started."
STOPPED_NOTE = "Stopped by the user."
TYPE_MAP = {"string": "STRING", "integer": "INTEGER", "number": "NUMBER", "boolean": "BOOLEAN"}


def _to_gemini_tools() -> list[dict]:
    declarations = []
    for tool in TOOL_SCHEMAS:
        schema = tool["input_schema"]
        declaration = {"name": tool["name"], "description": tool["description"]}
        if schema.get("properties"):
            declaration["parameters"] = {
                "type": "OBJECT",
                "properties": {
                    key: {"type": TYPE_MAP.get(value.get("type", "string"), "STRING")}
                    for key, value in schema["properties"].items()
                },
                "required": schema.get("required", []),
            }
        declarations.append(declaration)
    return [{"functionDeclarations": declarations}]


GEMINI_TOOLS = _to_gemini_tools()


class Brain:
    def __init__(self) -> None:
        self.history: list[dict] = []

    def reset(self) -> None:
        self.history.clear()

    def forget_last(self, text: str) -> bool:
        """Take back the last question and its answer, so the same question
        can be asked afresh. Only if the history ends with exactly that
        question and a plain answer — no tool calls in between, since those
        already happened and can't be taken back."""
        h = self.history
        if (len(h) >= 2
                and h[-2]["role"] == "user" and h[-2]["parts"] == [{"text": text}]
                and h[-1]["role"] == "model"
                and not any("functionCall" in p for p in h[-1]["parts"])):
            del h[-2:]
            return True
        return False

    def note_exchange(self, asked: str, answered: str) -> None:
        """Add a question answered elsewhere — a resume review from the
        Resume section — as if it had been asked here, so a follow-up in
        the conversation knows what was said. Only the short question goes
        in, not the resume that was sent with it."""
        if not asked.strip() or not answered.strip():
            return
        self.history.append({"role": "user", "parts": [{"text": asked}]})
        self.history.append({"role": "model", "parts": [{"text": answered}]})
        self._trim()

    def _trim(self) -> None:
        """Drop old turns, cutting only at a plain user message so a
        function call is never separated from its response."""
        while len(self.history) > MAX_MESSAGES:
            self.history.pop(0)
            while self.history and not (
                self.history[0]["role"] == "user" and "text" in self.history[0]["parts"][0]
            ):
                self.history.pop(0)

    def _stop(self) -> None:
        """You asked to stop. Close the exchange so the history still reads
        as a conversation — every tool call answered, the model having the
        last word — and the next question works as normal. Tools that ran,
        ran; the history says so."""
        if self.history and self.history[-1]["role"] == "user":
            self.history.append({"role": "model", "parts": [{"text": STOPPED_NOTE}]})
        raise tasks.Stopped()

    def ask(self, text: str, on_action=None) -> str:
        self.history.append({"role": "user", "parts": [{"text": text}]})
        self._trim()

        for _ in range(MAX_STEPS):
            # Between steps is where a stop is honoured: before asking the
            # model again, and before each tool it asked for.
            if tasks.stop_requested():
                self._stop()
            data = call_gemini({
                "systemInstruction": {"parts": [{"text": SYSTEM}]},
                "contents": self.history,
                "tools": GEMINI_TOOLS,
            })
            candidates = data.get("candidates")
            if not candidates:
                return "The model returned nothing. It may have blocked that request."

            parts = candidates[0].get("content", {}).get("parts", [])
            self.history.append({"role": "model", "parts": parts})

            calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not calls:
                reply = " ".join(p["text"] for p in parts if "text" in p).strip()
                return reply or "Done."

            responses = []
            for call in calls:
                name, args = call["name"], call.get("args") or {}
                if tasks.stop_requested():
                    result = NOT_RUN
                else:
                    if on_action:
                        on_action(name, args)
                    result = execute_tool(name, args)
                responses.append({"functionResponse": {
                    "name": name, "response": {"result": result}}})
            self.history.append({"role": "user", "parts": responses})

        return "That took more steps than I allow in one go. Tell me to continue if you want."
