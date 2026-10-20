"""Local memory: who you are, what you like, who your contacts are.

Plain JSON files under memory/ so you can read and edit them yourself.
Nothing secret goes in here: a password, one-time code, PIN, card or ID
number or key is refused, and hidden from the conversation log.

Memory comes in tiers (Chapter 30), each kept only as long as it's useful:

  short-term   the conversation in progress — the model's own history,
               in RAM, gone with "New conversation" or a restart
  task         notes for one task while it runs — RAM, the last 20 tasks,
               each task reads only its own
  project      facts about one named project — project_memory.json
  long-term    facts you asked to be remembered — preferences.json "facts"
  preferences  how you like things — preferences.json "preferred"

Nothing here goes to the model with every request. A piece reaches it only
when a request needs it and it's looked up.
"""
from __future__ import annotations

import json
import re
import threading
from collections import OrderedDict
from typing import Any

from ..app.config import MEMORY_DIR, log

PROFILE = MEMORY_DIR / "user_profile.json"
PREFERENCES = MEMORY_DIR / "preferences.json"
CONTACTS = MEMORY_DIR / "contacts.json"
HISTORY = MEMORY_DIR / "conversation_history.json"
PROJECT_MEMORY = MEMORY_DIR / "project_memory.json"
HISTORY_KEEP = 200
TASKS_KEPT = 20          # tasks whose notes are held; older ones are dropped
KEY_CHARS, VALUE_CHARS = 80, 500

TIERS = ("long-term", "preference", "project", "task")

# One change at a time: a command remembering something and the Memory
# section forgetting something must not each save over the other.
_lock = threading.RLock()

DEFAULTS = {
    PROFILE: {"name": "", "language": "en-IN"},
    PREFERENCES: {"browser": "chrome", "editor": "code", "facts": {}},
    CONTACTS: {"example": "+911234567890"},
    HISTORY: [],
    PROJECT_MEMORY: {},
}

# What memory refuses to keep, by what it's called ...
SECRET_KEY = re.compile(
    r"\b(passwords?|passcodes?|passphrases?|pwd|otps?|one[- ]time (?:codes?|passwords?)|cvv|cvc|"
    r"m?pin(?!\s*-?\s*codes?)|pin numbers?|api[ _-]?keys?|access[ _-]?keys?|(?:access |auth |bearer )?tokens?|"
    r"(?:gemini|openai|groq|adzuna|anthropic|claude|github|gitlab|aws|azure|google|stripe|razorpay) (?:api )?keys?|"
    r"private keys?|secret keys?|client secrets?|recovery (?:codes?|phrases?)|seed phrases?|"
    r"(?:credit |debit )?card (?:numbers?|details)|credit cards?|debit cards?|"
    r"aadh?aa?r|pan (?:numbers?|card|no)|passport (?:numbers?|no)|bank accounts?|account (?:numbers?|no)|"
    r"net ?banking|upi ids?)\b", re.I)
# ... and by what it looks like: keys in their published shapes.
SECRET_VALUE = re.compile(
    r"AIza[0-9A-Za-z_\-]{20,}|\bsk-[A-Za-z0-9_\-]{16,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgsk_[A-Za-z0-9]{20,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}|\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----")
# A run of 13-19 digits that passes the card checksum. A phone number
# (10 digits, or 12 with the country code) is never one.
CARDISH = re.compile(r"(?<![\d+])(?:\d[ -]?){12,18}\d(?!\d)")
SAID_SECRET = re.compile(SECRET_KEY.pattern + r"(\s*(?:is|was|=|:|hai)\s*)(\S+)", re.I)
REFUSED = ("I don't keep passwords, codes, PINs, card or ID numbers, or keys in memory — it's a plain "
           "file on this computer. A password manager is the place for those.")
HIDDEN = "[hidden]"


def _luhn(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def _cards(text: str) -> list[str]:
    return [m.group(0) for m in CARDISH.finditer(text) if _luhn(re.sub(r"\D", "", m.group(0)))]


def is_sensitive(*texts: str) -> bool:
    """Would keeping this store a secret? Judged on the words used for it
    and on the shape of the value."""
    joined = " ".join(str(t or "") for t in texts)
    return bool(SECRET_KEY.search(joined) or SECRET_VALUE.search(joined) or _cards(joined))


def redact(text: str) -> str:
    """The text with anything secret-looking replaced by [hidden]: a value
    said after "password is", a key in its published shape, a card
    number. Everything else is left as it was."""
    text = str(text or "")
    text = SAID_SECRET.sub(lambda m: m.group(0)[: m.start(m.lastindex) - m.start(0)] + HIDDEN, text)
    text = SECRET_VALUE.sub(HIDDEN, text)
    for card in _cards(text):
        text = text.replace(card, HIDDEN)
    return text


def _key(key: str) -> str:
    return " ".join(str(key or "").lower().split())[:KEY_CHARS]


def _value(value: str) -> str:
    return " ".join(str(value or "").split())[:VALUE_CHARS]


def _load(path) -> Any:
    if not path.exists():
        _save(path, DEFAULTS[path])
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log(f"memory read failed for {path.name}: {e}")
        return DEFAULTS[path]


def _save(path, data) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        log(f"memory write failed for {path.name}: {e}")


def profile() -> dict:
    return _load(PROFILE)


def preferences() -> dict:
    return _load(PREFERENCES)


def contacts() -> dict:
    return _load(CONTACTS)


def remember(key: str, value: str) -> str:
    """Long-term: a fact you asked to be remembered. Saying it again with a
    new value updates it and says what it was."""
    key, value = _key(key), _value(value)
    if not key or not value:
        return "Tell me what to remember, like: remember that my editor is VS Code."
    if is_sensitive(key, value):
        return REFUSED
    with _lock:
        prefs = preferences()
        stored = prefs.setdefault("facts", {})
        before = stored.get(key)
        if before == value:
            return f"I already have that: {key} is {value}."
        stored[key] = value
        _save(PREFERENCES, prefs)
    if before is not None:
        return f"Updated: {key} is now {value} (it was {before})."
    return f"Noted: {key} is {value}."


def forget(key: str) -> str:
    with _lock:
        prefs = preferences()
        stored = prefs.get("facts", {})
        # As saved first (a key edited by hand may have capitals), then as
        # remember() saves it.
        found = next((k for k in (key, key.lower().strip(), _key(key)) if k in stored), None)
        if found is None:
            return f"I had nothing stored under {key}."
        del stored[found]
        _save(PREFERENCES, prefs)
    return f"Forgotten: {key}."


def facts() -> dict:
    """What you asked to be remembered, as stored."""
    found = preferences().get("facts", {})
    return {str(k): str(v) for k, v in found.items()} if isinstance(found, dict) else {}


def recall(key: str | None = None) -> str:
    """One thing by its name (a fact, then a preference), or everything
    kept about you, tier by tier."""
    if key:
        name = _key(key)
        found = facts().get(name, preferred().get(name))
        return found if found is not None else f"Nothing stored under {key}."
    parts = []
    if facts():
        parts.append("You asked me to remember: " + "; ".join(f"{k}: {v}" for k, v in facts().items()) + ".")
    if preferred():
        parts.append("Your preferences: " + "; ".join(f"{k}: {v}" for k, v in preferred().items()) + ".")
    for name, notes in project_memory().items():
        parts.append(f"Project {name}: " + "; ".join(f"{k}: {v}" for k, v in notes.items()) + ".")
    if not parts:
        return "I haven't stored anything about you yet. Say: remember that my editor is VS Code."
    return " ".join(parts)


# ------------------------------------------------------------ preferences

def preferred() -> dict:
    """How you said you like things, as stored."""
    found = preferences().get("preferred", {})
    return {str(k): str(v) for k, v in found.items()} if isinstance(found, dict) else {}


def set_preference(key: str, value: str) -> str:
    key, value = _key(re.sub(r"^(?:my )?(?:preferred|favou?rite) ", "", str(key or "").strip(), flags=re.I)), _value(value)
    if not key or not value:
        return "Tell me the preference, like: remember that my preferred browser is Firefox."
    if is_sensitive(key, value):
        return REFUSED
    with _lock:
        prefs = preferences()
        stored = prefs.setdefault("preferred", {})
        if not isinstance(stored, dict):
            stored = prefs["preferred"] = {}
        before = stored.get(key)
        if before == value:
            return f"I already have that: you prefer {value} for {key}."
        stored[key] = value
        _save(PREFERENCES, prefs)
    if before is not None:
        return f"Updated: you now prefer {value} for {key} (it was {before})."
    return f"Noted: you prefer {value} for {key}."


def forget_preference(key: str) -> str:
    name = _key(re.sub(r"^(?:my )?(?:preferred|favou?rite) ", "", str(key or "").strip(), flags=re.I))
    with _lock:
        prefs = preferences()
        stored = prefs.get("preferred", {})
        if not isinstance(stored, dict) or name not in stored:
            return f"I had no preference stored for {key}."
        del stored[name]
        _save(PREFERENCES, prefs)
    return f"Forgotten: your preference for {name}."


# ---------------------------------------------------------------- projects

def project_memory() -> dict[str, dict[str, str]]:
    """Facts by project, as stored: {project: {key: value}}."""
    found = _load(PROJECT_MEMORY)
    if not isinstance(found, dict):
        return {}
    return {str(p): {str(k): str(v) for k, v in notes.items()}
            for p, notes in found.items() if isinstance(notes, dict) and notes}


def _project(name: str) -> str:
    """A project's name as you said it, capitals kept; matched ignoring case."""
    name = re.sub(r"^(?:the |my )?(?:project )?", "", str(name or "").strip(), flags=re.I)
    return " ".join(name.split())[:KEY_CHARS]


def _stored_project(stored: dict, name: str) -> str | None:
    """The name a project is stored under, whatever its capitals."""
    return next((p for p in stored if p.lower() == name.lower()), None) if name else None


def remember_for_project(project: str, key: str, value: str) -> str:
    project, key, value = _project(project), _key(key), _value(value)
    if not project or not key or not value:
        return "Tell me the project and the fact, like: remember for project Blood Bridge that the deadline is Friday."
    if is_sensitive(project, key, value):
        return REFUSED
    with _lock:
        stored = _load(PROJECT_MEMORY)
        if not isinstance(stored, dict):
            stored = {}
        project = _stored_project(stored, project) or project
        notes = stored.setdefault(project, {})
        before = notes.get(key)
        if before == value:
            return f"I already have that for {project}: {key} is {value}."
        notes[key] = value
        _save(PROJECT_MEMORY, stored)
    if before is not None:
        return f"Updated for {project}: {key} is now {value} (it was {before})."
    return f"Noted for {project}: {key} is {value}."


def recall_project(project: str) -> str:
    kept = project_memory()
    name = _stored_project(kept, _project(project))
    if not name:
        known = ", ".join(kept) or "none yet"
        return f"I have nothing stored for project {_project(project) or project}. Projects I have notes for: {known}."
    return f"Project {name}: " + "; ".join(f"{k}: {v}" for k, v in kept[name].items()) + "."


def forget_for_project(project: str, key: str) -> str:
    name, key = _project(project), _key(key)
    with _lock:
        stored = _load(PROJECT_MEMORY)
        if not isinstance(stored, dict):
            stored = {}
        name = _stored_project(stored, name) or name
        notes = stored.get(name)
        key = _variant(key, notes) if isinstance(notes, dict) else key
        if not isinstance(notes, dict) or key not in notes:
            return f"I had nothing stored under {key} for {name}."
        del notes[key]
        if not notes:
            del stored[name]
        _save(PROJECT_MEMORY, stored)
    return f"Forgotten: {key} for {name}."


def forget_project(project: str) -> str:
    """Everything stored for one project. Asks first: it's several facts
    at once."""
    from ..tools.permissions import Ask, confirm_fn
    kept = project_memory()
    name = _stored_project(kept, _project(project))
    if not name:
        return f"I have nothing stored for project {_project(project) or project}."
    notes = kept[name]
    things = f"{len(notes)} thing{'' if len(notes) == 1 else 's'}"
    ask = Ask(f"Forget the {things} stored for {name}?", action="Forget a project's memory",
              target=name, details="; ".join(f"{k}: {v}" for k, v in notes.items()),
              consequence="They're deleted from project_memory.json; there's no undo.",
              tone="caution", verb="Forget", tool="forget_project")
    if confirm_fn(ask) is not True:
        return f"Kept everything for {name}."
    with _lock:
        stored = _load(PROJECT_MEMORY)
        if isinstance(stored, dict):
            stored.pop(name, None)
            _save(PROJECT_MEMORY, stored)
    return f"Forgotten: everything for {name} ({things})."


# -------------------------------------------------------------------- tasks
# RAM only, by task id. A task reads and writes only its own notes; a thread
# with no task has none.

_task_notes: "OrderedDict[int, dict[str, str]]" = OrderedDict()


def _task_id(task_id: int | None) -> int | None:
    if task_id is not None:
        return task_id
    from ..app import tasks
    return tasks.current_id()


def note_for_task(key: str, value: str, task_id: int | None = None) -> str:
    """Task memory: something to hold on to while this task runs."""
    task_id, key, value = _task_id(task_id), _key(key), _value(value)
    if task_id is None:
        return "There's no task running to note that against."
    if not key or not value:
        return "Tell me what to note."
    if is_sensitive(key, value):
        return REFUSED
    with _lock:
        notes = _task_notes.setdefault(task_id, {})
        _task_notes.move_to_end(task_id)
        notes[key] = value
        while len(_task_notes) > TASKS_KEPT:
            _task_notes.popitem(last=False)
    return f"Noted for this task: {key} is {value}."


def task_notes(task_id: int | None = None) -> dict[str, str]:
    task_id = _task_id(task_id)
    with _lock:
        return dict(_task_notes.get(task_id, {})) if task_id is not None else {}


def forget_task(task_id: int | None = None) -> None:
    task_id = _task_id(task_id)
    with _lock:
        _task_notes.pop(task_id, None)


# -------------------------------------------------------- finding things

STOP_WORDS = {"a", "an", "the", "my", "me", "i", "is", "are", "of", "for", "to", "in", "on", "about", "what",
              "do", "you", "your", "remember", "know", "and", "or", "it", "that", "this"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w/.:+-]+", str(text or "").lower()) if w not in STOP_WORDS}


def search(query: str, task_id: int | None = None) -> list[dict]:
    """Everything kept that shares a word with the query, best first:
    [{"tier", "project", "key", "value"}]. Only this task's notes, never
    another's."""
    wanted = _words(query)
    if not wanted:
        return []
    items = [{"tier": "long-term", "project": "", "key": k, "value": v} for k, v in facts().items()]
    items += [{"tier": "preference", "project": "", "key": k, "value": v} for k, v in preferred().items()]
    items += [{"tier": "project", "project": p, "key": k, "value": v}
              for p, notes in project_memory().items() for k, v in notes.items()]
    items += [{"tier": "task", "project": "", "key": k, "value": v} for k, v in task_notes(task_id).items()]
    scored = []
    for item in items:
        have = _words(f"{item['project']} {item['key']} {item['value']}")
        score = len(wanted & have) * 2 + len(wanted & _words(item["key"]))
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: -pair[0])
    return [item for _, item in scored]


def recall_about(query: str) -> str:
    """The tool and the command: what's kept about something, with where
    each piece is kept."""
    if re.fullmatch(r"\s*(me|myself|us|everything|anything)?\s*\??", str(query or ""), re.I):
        return recall()
    found = search(query)
    if not found:
        return f"I don't have anything stored about {query.strip() or 'that'}."
    where = {"long-term": "", "preference": "your preference: ", "task": "this task: "}

    def line(item):
        place = f"project {item['project']}: " if item["tier"] == "project" else where[item["tier"]]
        return f"{place}{item['key']}: {item['value']}"
    return "; ".join(line(item) for item in found[:8]) + "."


def _variant(name: str, stored) -> str:
    """The name as stored, allowing only for a leading "my": "editor" finds
    "my editor" and the other way round. Never a nearer match than that."""
    for candidate in (name, f"my {name}", name.removeprefix("my ")):
        if candidate in stored:
            return candidate
    return name


def forget_anything(key: str) -> str:
    """"forget X": the one thing stored under exactly that name, wherever it
    is. If it's in more than one place, says where and forgets nothing."""
    name = _key(re.sub(r"^(?:that|about) ", "", str(key or "").strip(), flags=re.I))
    preference = _key(re.sub(r"^(?:my )?(?:preferred|favou?rite) ", "", name))
    places = []
    if _variant(name, facts()) in facts():
        places.append(("long-term", "", _variant(name, facts())))
    if preference in preferred():
        places.append(("preference", "", preference))
    places += [("project", p, _variant(name, notes)) for p, notes in project_memory().items()
               if _variant(name, notes) in notes]
    if not places:
        return f"I had nothing stored under {name}."
    if len(places) > 1:
        said = ", ".join(f"project {p}" if tier == "project" else tier for tier, p, _ in places)
        return f"“{name}” is stored in more than one place ({said}). Say which, like: forget {name} for project …"
    tier, project, stored_as = places[0]
    if tier == "long-term":
        return forget(stored_as)
    if tier == "preference":
        return forget_preference(stored_as)
    return forget_for_project(project, stored_as)


def add_contact(name: str, number: str) -> str:
    with _lock:
        book = contacts()
        book[name.lower().strip()] = number.strip()
        _save(CONTACTS, book)
    return f"Saved {name} in your contacts."


def remove_contact(name: str) -> str | None:
    """Remove one contact, by its exact saved name. None if there was no
    such contact — never a near match, since this deletes."""
    with _lock:
        book = contacts()
        if name not in book:
            return None
        del book[name]
        _save(CONTACTS, book)
    return f"Removed {name} from your contacts."


def is_sample(name: str, number: str) -> bool:
    """The made-up entry a fresh memory folder starts with."""
    return DEFAULTS[CONTACTS].get(name) == number


def mask(number: str) -> str:
    """A phone number with all but its last four digits hidden, and the
    country code kept, so you can tell numbers apart without showing them."""
    digits = re.sub(r"\D", "", str(number))
    if len(digits) <= 4:
        return "•" * len(digits)
    code = ""
    if str(number).strip().startswith("+") and len(digits) > 10:
        code, digits = "+" + digits[:-10] + " ", digits[-10:]
    return code + "•" * (len(digits) - 4) + digits[-4:]


def find_contact(name: str) -> str | None:
    book = contacts()
    key = name.lower().strip()
    if key in book:
        return book[key]
    for alias, number in book.items():
        if key in alias or alias in key:
            return number
    return None


def log_turn(user: str, assistant: str) -> None:
    """One exchange into the conversation log, with anything
    secret-looking hidden first."""
    with _lock:
        history = _load(HISTORY)
        history.append({"user": redact(user), "assistant": redact(assistant)})
        _save(HISTORY, history[-HISTORY_KEEP:])


def history() -> list[dict]:
    """The conversation log, oldest first. Written, never read back by
    LITTLE — a record for you."""
    found = _load(HISTORY)
    return [t for t in found if isinstance(t, dict)] if isinstance(found, list) else []


def clear_history() -> int:
    """Empty the conversation log. Returns how many turns were in it."""
    with _lock:
        count = len(history())
        _save(HISTORY, [])
    return count
