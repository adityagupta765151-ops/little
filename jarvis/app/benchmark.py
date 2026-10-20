"""Performance benchmarking (Chapter 46): measure before optimising.

Two kinds of number, never mixed up:

- **measured in use** — every command, model request, tool run, browser
  step, wake-word check and transcription is timed as it happens
  (`latency`), so these are what you actually waited for.
- **measured just now** — "benchmark yourself" times what can be timed on
  this computer without sending anything anywhere or changing anything: the
  router on a fixed set of commands (nothing it would open is opened), a
  read-only tool, a search of your documents. "Benchmark the model too" adds one request to
  each model tier — two real requests, said up front.

Each run is kept in `benchmarks.jsonl` (memory folder) so a later run can be
compared with this one: an optimisation is only one if the numbers say so.
"""
from __future__ import annotations

import datetime
import json
import time

from . import config, latency
from .config import log

PATH = config.MEMORY_DIR / "benchmarks.jsonl"
ROUTER_COMMANDS = ("what's the time", "what's the date", "what do you remember about nothing in particular",
                   "list reminders",
                   "tell me a story about the sea", "create a react app and then run it", "chrome kholo",
                   "which tools use the browser", "how fast are you")
ROUNDS = 20
NAMES = {"router": "Router (trying locally first)",
         "tool": "A read-only tool", "documents": "Searching your documents", "model_fast": "The fast model",
         "model_strong": "The strong model", "wake": "Hearing its name (on this computer)",
         "stt": "Speech to text (cloud)", "browser": "A browser step", "fast": "Commands answered here",
         "normal": "Commands with this computer's tools", "ai": "Commands with the model",
         "agent": "Plans"}


def _time(fn, rounds: int) -> list[float]:
    out = []
    for _ in range(rounds):
        started = time.perf_counter()
        fn()
        out.append((time.perf_counter() - started) * 1000)
    return out


def _stats(samples: list[float]) -> dict:
    ordered = sorted(samples)
    if not ordered:
        return {"count": 0, "p50": None, "p95": None, "max": None}
    pick = latency._percentile
    return {"count": len(ordered), "p50": round(pick(ordered, 0.5), 2), "p95": round(pick(ordered, 0.95), 2),
            "max": round(ordered[-1], 2)}


def _router() -> list[float]:
    from ..routing import router
    from ..tools import apps
    real_open, real_close = apps.open_app, apps.close_app
    apps.open_app = apps.close_app = lambda *_a, **_k: "benchmark"      # nothing opens during a benchmark
    samples: list[float] = []
    try:
        for command in ROUTER_COMMANDS:
            samples += _time(lambda c=command: router.fast_route(c), ROUNDS)
    finally:
        apps.open_app, apps.close_app = real_open, real_close
    return samples


def _tool() -> list[float]:
    from ..tools import registry
    return _time(lambda: registry.FUNCTIONS["get_datetime"](), ROUNDS)


def _documents() -> list[float]:
    from ..store import knowledge
    if not knowledge.documents():
        return []
    return _time(lambda: knowledge.retrieve("deadline for the project"), ROUNDS)


def _model(tier: str) -> list[float]:
    from ..ai import models
    from ..ai.provider import ask_text
    started = time.perf_counter()
    with models.use(tier):
        ask_text("Reply with the single word: ok")
    return [(time.perf_counter() - started) * 1000]


def run(include_model: bool = False) -> dict:
    """Time what can be timed here; keep the run; return it."""
    now = {"router": _router(), "tool": _tool(), "documents": _documents()}
    problems = []
    if include_model:
        for tier in ("fast", "strong"):
            try:
                now[f"model_{tier}"] = _model(tier)
            except Exception as e:  # noqa: BLE001
                problems.append(f"the {tier} model: {e}")
    in_use = latency.summary()
    result = {"at": datetime.datetime.now().isoformat(timespec="seconds"),
              "now": {k: _stats(v) for k, v in now.items()},
              "in_use": {k: {"count": v["count"], "p50": v["p50"], "p95": v["p95"], "max": v["max"]}
                         for k, v in in_use.items() if v["count"]},
              "problems": problems}
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result) + "\n")
    except OSError as e:
        log(f"benchmark not kept: {e}")
    return result


def history(limit: int = 10) -> list[dict]:
    if not PATH.exists():
        return []
    out = []
    for line in PATH.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _ms(value) -> str:
    if value is None:
        return "—"
    if value < 0.01:
        return "under 0.01 ms"                  # below what's kept, not zero
    return f"{value:g} ms" if value < 1000 else f"{value / 1000:.2f} s"


def report(result: dict) -> str:
    lines = ["Measured just now, on this computer:"]
    for key, s in result["now"].items():
        if s["count"]:
            lines.append(f"  {NAMES.get(key, key)}: typically {_ms(s['p50'])}, slowest 1 in 20 {_ms(s['p95'])} "
                         f"({s['count']} runs)")
        elif key == "documents":
            lines.append(f"  {NAMES[key]}: not measured — no documents added yet")
    if result["in_use"]:
        lines.append("Measured in use this session:")
        for key, s in result["in_use"].items():
            lines.append(f"  {NAMES.get(key, key)}: typically {_ms(s['p50'])}, slowest 1 in 20 {_ms(s['p95'])} "
                         f"({s['count']} measured)")
    here, model = result["in_use"].get("fast"), result["in_use"].get("ai")
    if here and model and here["p50"]:
        lines.append(f"Answering here is about {model['p50'] / max(here['p50'], 1):.0f}× faster than asking the model.")
    for problem in result["problems"]:
        lines.append(f"Couldn't time {problem}")
    earlier = history(2)
    if len(earlier) == 2 and earlier[0]["now"].get("router", {}).get("p50") and result["now"]["router"]["p50"]:
        before, after = earlier[0]["now"]["router"]["p50"], result["now"]["router"]["p50"]
        lines.append(f"The router was {_ms(before)} last time, {_ms(after)} now.")
    return "\n".join(lines)


def benchmark(include_model: bool = False) -> str:
    """The command."""
    return report(run(include_model))
