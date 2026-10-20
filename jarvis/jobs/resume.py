"""Reading a resume into a structured profile.

Takes a PDF, a Word file or a photo of a printed resume, pulls the text
out, and has the model turn it into fields. Nothing is invented: if the
resume doesn't say it, the field stays empty, because every later step
(matching, filling application forms) treats this profile as the only
truth about the candidate.
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from ..app.config import MEMORY_DIR, log
from . import grades
from ..ai.provider import ask_about_image, ask_text
from .normalise import TYPES as JOB_TYPES

PROFILE_PATH = MEMORY_DIR / "resume_profile.json"

EMPTY_PROFILE = {
    "candidate": {
        "name": "", "email": "", "phone": "", "location": "",
        "education": [], "graduation_year": "", "degree": "",
        "skills": [], "languages": [], "frameworks": [],
        "projects": [], "experience": [], "internships": [], "certifications": [],
        # Chapter 26: marks as the resume writes them ("7.0/10", "85%"),
        # achievements, and the web addresses on it.
        "degree_score": "", "class_12": "", "class_10": "",
        "achievements": [], "links": [],
    },
    "preferences": {"roles": [], "locations": [], "work_modes": [], "countries": [],
                    "employment_types": []},
    "source_file": "",
    "raw_text_chars": 0,
}

# Less text than this and the file wasn't really read.
MIN_TEXT = 120
UNREADABLE = ("I couldn't get readable text out of that file. If it's a scan, "
              "install Tesseract OCR, or export the resume as a PDF with real text.")

EXTRACT_PROMPT = """Read this resume and return the facts it contains as JSON.

Return exactly this shape, with no commentary and no markdown fence:

{{
  "candidate": {{
    "name": "", "email": "", "phone": "", "location": "",
    "education": ["degree, institution, year"],
    "graduation_year": "", "degree": "",
    "skills": [], "languages": [], "frameworks": [],
    "projects": ["name - one line"],
    "experience": ["role, company, dates"],
    "internships": ["role, company, dates"],
    "certifications": [],
    "degree_score": "", "class_12": "", "class_10": "",
    "achievements": [],
    "links": []
  }},
  "preferences": {{ "roles": [], "locations": [], "work_modes": [], "countries": [] }}
}}

Rules that matter more than completeness:
- Only write what the resume actually says. Leave a field empty rather than guessing.
- "languages" means programming languages. "frameworks" means libraries and frameworks.
- "roles" under preferences: job titles this person is plainly aiming for, drawn from
  the resume's own objective or the roles they have held. If it doesn't say, leave empty.
- "work_modes" only if stated, one of remote, hybrid, onsite.
- "countries": countries the resume says they can work in. If it doesn't say,
  put the country of their own address, or leave empty.
- "degree_score": the CGPA, GPA or percentage for the degree, exactly as the resume
  writes it, with its scale if written ("7.0/10", "8.2 CGPA", "72%"). Never convert
  a CGPA to a percentage or back. Empty if the resume doesn't state one.
- "class_12" and "class_10": the Class XII (intermediate) and Class X (high school)
  marks, exactly as written. Empty if not written.
- "achievements": awards, hackathon results, ranks, scholarships and contest ratings,
  as the resume states them. Not skills, not duties.
- "links": every web address on the resume (GitHub, LinkedIn, portfolio), as written.

Resume text:
{text}"""


def _from_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:10])
    except Exception as e:  # noqa: BLE001
        log(f"resume pdf read failed: {e}")
        return ""


def _from_docx(path: Path) -> str:
    try:
        import docx
    except ImportError:
        return ""
    try:
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    except Exception as e:  # noqa: BLE001
        log(f"resume docx read failed: {e}")
        return ""


def _from_image(path: Path) -> str:
    """Local OCR first; the model's own vision is the fallback, since it
    reads a photographed resume better than Tesseract usually does."""
    try:
        import pytesseract
        from PIL import Image
        text = pytesseract.image_to_string(Image.open(path))
        if len(text.strip()) > 120:
            return text
    except Exception as e:  # noqa: BLE001
        log(f"tesseract unavailable or failed: {e}")
    try:
        return ask_about_image(
            path.read_bytes(),
            "Transcribe every word of this resume as plain text. No commentary.")
    except Exception as e:  # noqa: BLE001
        log(f"vision transcription failed: {e}")
        return ""


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _from_pdf(path)
        # A scanned PDF has pages but almost no extractable text.
        return text if len(text.strip()) > 120 else _from_image(path)
    if suffix in (".docx", ".doc"):
        return _from_docx(path)
    if suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        return _from_image(path)
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _parse_json(raw: str) -> dict | None:
    """Models sometimes wrap JSON in a fence or add a sentence."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        log(f"resume json parse failed: {e}")
        return None


def _merge(parsed: dict, source: str, chars: int) -> dict:
    """Keep the known shape whatever the model returns, so later code can
    rely on every key existing."""
    profile = json.loads(json.dumps(EMPTY_PROFILE))
    for section in ("candidate", "preferences"):
        for key, default in profile[section].items():
            value = (parsed.get(section) or {}).get(key, default)
            if isinstance(default, list):
                profile[section][key] = [str(v).strip() for v in value if str(v).strip()] \
                    if isinstance(value, list) else []
            else:
                profile[section][key] = str(value).strip() if value else ""
    profile["source_file"] = source
    profile["raw_text_chars"] = chars
    return profile


# ------------------------------------------- Chapter 26: only what it says

SCORE_FIELDS = ("degree_score", "class_12", "class_10")
MAX_LINKS = 8
MAX_ACHIEVEMENTS = 12
ITEM_CHARS = 300
_COMMON = {"with", "from", "that", "this", "have", "were", "been", "into", "over", "among",
           "their", "about", "under", "which", "while", "where", "also", "than", "them"}
LINK = re.compile(r"^(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:[/?#]\S*)?$", re.I)


def _core(link: str) -> str:
    """A web address without its scheme, www. and last slash, lowercased."""
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", link.strip().lower()).rstrip("/")


def link_ok(link: str) -> bool:
    """A web address: a domain with a dot, maybe a path. Not an email, not a
    javascript: or file: link, not a sentence."""
    link = link.strip()
    return 0 < len(link) <= 200 and bool(LINK.match(link))


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _COMMON}


def only_what_it_says(profile: dict, text: str) -> list[str]:
    """Hold the new fields to the resume's own text. A score whose number
    isn't in it, a link that isn't in it, an achievement whose words aren't
    in it — each was made up, however plausible, and is left out. A score
    the model missed but the text plainly states on one line is taken from
    the text. Returns what was left out."""
    person = profile["candidate"]
    dropped: list[str] = []
    found = grades.scores_in(text)
    for field in SCORE_FIELDS:
        value = " ".join(str(person.get(field) or "").split())[:40]
        if value and not grades.stated_in(value, text):
            dropped.append(f"{field} {value!r}")
            value = ""
        person[field] = value or found.get(field, "")

    haystack = re.sub(r"https?://|www\.", "", (text or "").lower())
    links: list[str] = []
    for link in person.get("links", []):
        link = str(link).strip().rstrip(".,;)")
        if not link_ok(link) or _core(link) not in haystack:
            dropped.append(f"link {link!r}")
        elif _core(link) not in (_core(have) for have in links):
            links.append(link)
    person["links"] = links[:MAX_LINKS]

    words = _words(text)
    kept: list[str] = []
    for item in person.get("achievements", []):
        item = " ".join(str(item).split())[:ITEM_CHARS]
        mine = _words(item)
        if mine and len(mine & words) >= max(1, (len(mine) + 1) // 2):
            kept.append(item)
        else:
            dropped.append(f"achievement {item[:40]!r}")
    person["achievements"] = kept[:MAX_ACHIEVEMENTS]

    for item in dropped:
        log(f"resume: left out {item} — it isn't in the resume's text")
    return dropped


def load_profile() -> dict:
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return json.loads(json.dumps(EMPTY_PROFILE))


def save_profile(profile: dict) -> None:
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False),
                            encoding="utf-8")


SEARCH_FOLDERS = ("Downloads", "Documents", "Desktop", "OneDrive/Documents")
RESUME_SUFFIXES = (".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".md")


def find_resume_file(name: str) -> Path | None:
    """Find the file the user means, forgivingly.

    Windows hides known extensions, so someone reading "aditya-resume.pdf"
    off the screen may be looking at a file actually called
    aditya-resume.pdf.pdf. Case varies too. So the stem is matched rather
    than the exact name, across the folders a resume normally lives in.
    """
    given = Path(name).expanduser()
    if given.exists():
        return given

    def base(name: str) -> str:
        """Strip every known extension, so aditya-resume.pdf.pdf,
        aditya-resume.pdf and aditya-resume all reduce to one key."""
        name = name.lower()
        changed = True
        while changed:
            changed = False
            for suffix in RESUME_SUFFIXES:
                if name.endswith(suffix):
                    name = name[: -len(suffix)]
                    changed = True
        return name

    wanted = given.name.lower()
    stem = base(given.name)
    folders = [Path.home() / f for f in SEARCH_FOLDERS] + [MEMORY_DIR, Path.cwd()]

    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue

        for entry in entries:                       # exact name, any case
            if entry.is_file() and entry.name.lower() == wanted:
                return entry
        for entry in entries:                       # same base name, any extension
            if (entry.is_file() and entry.suffix.lower() in RESUME_SUFFIXES
                    and base(entry.name) == stem):
                return entry
    return None


def list_candidate_resumes(limit: int = 6) -> list[str]:
    """Files that look like a resume, to suggest when the name was wrong."""
    found: list[str] = []
    for folder_name in SEARCH_FOLDERS:
        folder = Path.home() / folder_name
        if not folder.is_dir():
            continue
        try:
            for entry in sorted(folder.iterdir(), key=lambda p: -p.stat().st_mtime):
                if (entry.is_file() and entry.suffix.lower() in RESUME_SUFFIXES
                        and re.search(r"resume|cv|curriculum", entry.stem, re.I)):
                    found.append(entry.name)
                    if len(found) >= limit:
                        return found
        except OSError:
            continue
    return found


def scan_hint() -> str:
    """How to scan a resume, named after files that are actually there.

    Telling someone to say "scan my resume resume.pdf" when no such file
    exists sends them to type a filename that will fail. If something on
    the disk looks like a resume, the instruction names it.
    """
    found = list_candidate_resumes(3)
    if not found:
        return ("Say: scan my resume followed by the file name, and keep the file "
                "in Downloads, Documents or Desktop.")
    if len(found) == 1:
        return f"Say: scan my resume {found[0]}"
    return ("Say one of these:\n"
            + "\n".join(f"    scan my resume {name}" for name in found))


def scan_resume(path: str) -> str:
    """Read a resume file and build the candidate profile from it."""
    file = find_resume_file(path)
    if file is None:
        suggestions = list_candidate_resumes()
        if suggestions:
            # Every option is a complete command. A message that says
            # "scan my resume <one of those>" gets typed back verbatim,
            # placeholder and all — and rightly so, since that is what it
            # asked for.
            lines = [f"I couldn't find {path}. These look like resumes — "
                     f"say or type one of these lines:"]
            lines += [f"    scan my resume {name}" for name in suggestions[:6]]
            return "\n".join(lines)
        return (f"I couldn't find {path}, and nothing resume-shaped is in your "
                f"Downloads, Documents or Desktop.")

    text = extract_text(file)
    if len(text.strip()) < MIN_TEXT:
        return UNREADABLE

    profile, why_not = structure(text, file)
    if profile is None:
        return why_not
    return save_scanned(profile)


def structure(text: str, file: Path) -> tuple[dict | None, str]:
    """The model's reading of a resume's text, as a profile — or None and
    why not. Nothing is saved here."""
    try:
        raw = ask_text(EXTRACT_PROMPT.format(text=text[:18000]))
    except RuntimeError as e:
        return None, str(e)

    parsed = _parse_json(raw)
    if not parsed:
        return None, "I read the resume but couldn't structure it. Try again in a moment."

    profile = _merge(parsed, file.name, len(text))
    only_what_it_says(profile, text)
    profile["source_path"] = str(Path(file).resolve())
    return profile, ""


def keep_and_save(profile: dict) -> list[str]:
    """Save a freshly read profile, keeping the job preferences you set
    yourself. Returns which ones were kept.

    A new resume replaces what the resume says, not what you told Little:
    roles you typed stay yours even if the new file suggests others. A field
    you never set is taken from the new resume. For a profile saved before
    this was tracked, any preference with a value counts as yours — losing
    something you typed is worse than keeping something the old resume said.
    """
    old = load_profile()
    before = old.get("preferences", {})
    kept = [field for field in yours(old) if before.get(field)]
    for field in kept:
        profile["preferences"][field] = list(before[field])
    profile["set_by_you"] = kept
    # Corrections you made by command are not kept: the new resume is the
    # truth about you now (Chapter 26's choice). save_scanned says so.
    profile["edited"] = []
    profile["scanned_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    save_profile(profile)
    return kept


def save_scanned(profile: dict) -> str:
    """Save a freshly read profile and say what happened: the preferences
    you set are kept, corrections you made by command give way to what the
    new resume says, and the stored jobs are scored again against it."""
    replaced = edited(load_profile())
    kept = keep_and_save(profile)
    message = saved_message(profile, kept)
    if replaced:
        message += (" Your corrections to " + _and([CHANGEABLE[f] for f in replaced])
                    + " were replaced with what this resume says.")
    rescored = _rescore(profile)
    if rescored:
        message += f" Re-scored {rescored} stored job{'' if rescored == 1 else 's'}."
    return message


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _rescore(profile: dict) -> int:
    """Score the stored jobs again, so a changed CGPA or skill shows on the
    jobs you already have. Never fails the edit it follows."""
    try:
        from .engine import rescore_stored
        return rescore_stored(profile)
    except Exception as e:  # noqa: BLE001
        log(f"re-scoring stored jobs failed: {e}")
        return 0


def saved_message(profile: dict, kept: list[str]) -> str:
    person = profile["candidate"]

    def count(items, noun: str, plural: str = "") -> str:
        n = len(items)
        return f"{n} {noun if n == 1 else (plural or noun + 's')}"

    message = (f"Read {profile['source_file']}. Profile saved for {person['name'] or 'you'}: "
               f"{count(person['skills'], 'skill')}, "
               f"{count(person['projects'], 'project')}, "
               f"{count(person['education'], 'education entry', 'education entries')}.")
    if kept:
        message += f" Kept the preferences you set: {', '.join(FIELD_WORDS[f] for f in kept)}."
    return message


def show_profile() -> str:
    """What JARVIS currently believes about the candidate."""
    profile = load_profile()
    person = profile["candidate"]
    if not person["name"] and not person["skills"]:
        return "No resume has been scanned yet. " + scan_hint()

    lines = [f"Name: {person['name'] or 'not stated'}",
             f"Degree: {person['degree'] or 'not stated'} ({person['graduation_year'] or '-'})",
             f"Location: {person['location'] or 'not stated'}",
             f"Skills ({len(person['skills'])}): {', '.join(person['skills'][:18])}"]
    for field in SCORE_FIELDS:
        if person.get(field):
            lines.append(f"{CHANGEABLE[field][0].upper() + CHANGEABLE[field][1:]}: {person[field]}")
    if person["projects"]:
        lines.append(f"Projects: {len(person['projects'])}")
    if person.get("achievements"):
        lines.append(f"Achievements: {len(person['achievements'])}")
    if person.get("links"):
        lines.append(f"Links: {', '.join(person['links'])}")
    if profile["preferences"]["roles"]:
        lines.append(f"Target roles: {', '.join(profile['preferences']['roles'])}")
    changed = edited(profile)
    if changed:
        lines.append("Corrected by you: " + ", ".join(CHANGEABLE[f] for f in changed)
                     + " (a new resume scan replaces these)")
    return "\n".join(lines)


FIELDS = ("roles", "locations", "work_modes", "countries", "employment_types")
FIELD_WORDS = {"roles": "roles", "locations": "locations", "work_modes": "work modes",
               "countries": "countries", "employment_types": "job types"}

# What the job boards' postings are sorted into, so the only values that
# can ever match (jobs/sources.py and jobs/normalise.py).
WORK_MODES = ("remote", "hybrid", "onsite")
# Every type a posting can be given, most asked-for first.
_MOST_ASKED = ("full-time", "internship", "part-time", "contract", "temporary")
JOB_TYPE_CHOICES = tuple(sorted(JOB_TYPES, key=lambda t: _MOST_ASKED.index(t)
                                if t in _MOST_ASKED else len(_MOST_ASKED)))
CHOICES = {"work_modes": WORK_MODES, "employment_types": JOB_TYPE_CHOICES}
MAX_ITEMS = 12                 # per preference
MAX_CHARS = 60                 # per value


def yours(profile: dict) -> list[str]:
    """The preferences you set yourself, which a new scan keeps. A profile
    saved before this was tracked counts every preference with a value."""
    marked = profile.get("set_by_you")
    if isinstance(marked, list):
        return [f for f in FIELDS if f in marked]
    return [f for f in FIELDS if profile.get("preferences", {}).get(f)]


def _mark_yours(profile: dict, field: str) -> None:
    """Remember that you set this one, so a new scan keeps it. A field you
    cleared is the resume's to fill again."""
    mine = [f for f in yours(profile) if f != field]
    if profile["preferences"].get(field):
        mine.append(field)
    profile["set_by_you"] = [f for f in FIELDS if f in mine]


def set_preference(field: str, value: str) -> str:
    """Set a job-search preference the resume didn't state."""
    field = field.lower().strip().replace(" ", "_")
    field = {"role": "roles", "location": "locations", "country": "countries",
             "work_mode": "work_modes", "mode": "work_modes",
             "employment_type": "employment_types", "type": "employment_types",
             "job_type": "employment_types"}.get(field, field)
    if field not in FIELDS:
        return "I can set roles, locations, countries, work_modes or employment_types."

    profile = load_profile()
    profile["preferences"].setdefault(field, [])
    profile["preferences"][field] = [v.strip() for v in value.split(",") if v.strip()]
    _mark_yours(profile, field)
    save_profile(profile)

    note = ""
    if field == "countries":
        note = (" Jobs open only to other countries will be scored down, "
                "since you couldn't take them.")
    return f"Noted. {field}: {', '.join(profile['preferences'][field])}.{note}"


def countries() -> list[str]:
    """Where the candidate can actually work. Falls back to the country in
    their own address, so this is never empty in practice."""
    profile = load_profile()
    listed = [c.lower().strip() for c in profile["preferences"].get("countries", []) if c.strip()]
    if listed:
        return listed
    home = profile["candidate"].get("location", "")
    tail = home.split(",")[-1].strip().lower()
    return [tail] if tail else []


# ------------------------------------------------ the Resume section (UI-7)

def is_ready(profile: dict) -> bool:
    """Has a resume been read? The same test show_profile uses."""
    person = profile.get("candidate", {})
    return bool(person.get("name") or person.get("skills"))


def preferences(profile: dict) -> dict:
    """All five preferences, each a list, whatever the saved file holds."""
    saved = profile.get("preferences", {})
    return {field: [str(v) for v in saved.get(field, []) if str(v).strip()]
            if isinstance(saved.get(field), list) else [] for field in FIELDS}


def set_preferences(values) -> tuple[dict | None, str]:
    """The Resume section's Save: several preferences at once, checked the
    way the job search will read them. Returns the saved preferences and
    what changed — or None and why nothing was saved. All or nothing: one
    bad field saves none of them."""
    if not isinstance(values, dict) or not values:
        return None, "There was nothing to save."
    if any(field not in FIELDS for field in values):
        return None, "I can set roles, locations, work modes, countries and job types."

    cleaned: dict[str, list[str]] = {}
    for field, given in values.items():
        words = FIELD_WORDS[field]
        if not isinstance(given, list) or not all(isinstance(v, str) for v in given):
            return None, f"The {words} weren't a list of words."
        items: list[str] = []
        for value in given:
            value = " ".join(value.split())
            if not value:
                continue
            if len(value) > MAX_CHARS:
                return None, (f"“{value[:30]}…” is too long for {words}. "
                              f"Keep each one under {MAX_CHARS} characters.")
            if field in CHOICES:
                if value.lower() not in CHOICES[field]:
                    return None, f"{words.capitalize()} can only be {', '.join(CHOICES[field])}."
                value = value.lower()
            if value.lower() not in (v.lower() for v in items):
                items.append(value)
        if len(items) > MAX_ITEMS:
            return None, f"That's more than {MAX_ITEMS} {words}. Keep the ones that matter most."
        cleaned[field] = items

    profile = load_profile()
    now = preferences(profile)
    changed = [field for field in FIELDS if field in cleaned and cleaned[field] != now[field]]
    if not changed:
        return now, "Nothing changed."
    for field in changed:
        profile["preferences"][field] = cleaned[field]
        _mark_yours(profile, field)
    save_profile(profile)
    return preferences(profile), "Saved " + ", ".join(FIELD_WORDS[f] for f in changed) + "."


def resume_file(profile: dict) -> Path | None:
    """The file the profile was read from, if it's still on this computer."""
    where = str(profile.get("source_path") or "")
    if where and Path(where).is_file():
        return Path(where)
    name = str(profile.get("source_file") or "").strip()
    return find_resume_file(name) if name else None


def profile_as_text(profile: dict) -> str:
    """The saved profile written out, for when the file itself is gone.
    Says whether an email and phone are on it, not what they are."""
    person = profile.get("candidate", {})

    def line(label: str, value) -> str:
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        return f"{label}: {value or 'not stated'}"

    return "\n".join([
        line("Name", person.get("name")),
        line("Location", person.get("location")),
        f"Email: {'given' if person.get('email') else 'not given'}",
        f"Phone: {'given' if person.get('phone') else 'not given'}",
        line("Degree", person.get("degree")),
        line("Graduation year", person.get("graduation_year")),
        line("Education", person.get("education")),
        line("Skills", person.get("skills")),
        line("Programming languages", person.get("languages")),
        line("Frameworks and libraries", person.get("frameworks")),
        line("Projects", person.get("projects")),
        line("Experience", person.get("experience")),
        line("Internships", person.get("internships")),
        line("Certifications", person.get("certifications")),
        line("Degree CGPA or %", person.get("degree_score")),
        line("Class 12 marks", person.get("class_12")),
        line("Class 10 marks", person.get("class_10")),
        line("Achievements", person.get("achievements")),
        line("Links", person.get("links")),
    ])


def resume_text(profile: dict) -> tuple[str, str]:
    """The resume as text for advice, and where it came from: the file
    itself while it's still here, since advice is about its own wording —
    otherwise the saved profile, and the answer says so."""
    file = resume_file(profile)
    if file is not None:
        try:
            text = extract_text(file)
        except Exception as e:  # noqa: BLE001
            log(f"resume re-read failed: {e}")
            text = ""
        if len(text.strip()) >= MIN_TEXT:
            return text[:18000], file.name
    return profile_as_text(profile), "your saved profile"


# ------------------------------------ Chapter 26: correcting the profile

# What you can correct by command, in the words the replies use. Single
# values are set; lists are added to and removed from.
CHANGEABLE = {
    "name": "name", "email": "email", "phone": "phone", "location": "address",
    "degree": "degree", "graduation_year": "graduation year",
    "degree_score": "CGPA or %", "class_12": "Class 12 marks", "class_10": "Class 10 marks",
    "skills": "skills", "languages": "programming languages", "frameworks": "frameworks",
    "projects": "projects", "experience": "experience", "internships": "internships",
    "certifications": "certifications", "education": "education",
    "achievements": "achievements", "links": "links",
}
SINGLE = ("name", "email", "phone", "location", "degree", "graduation_year") + SCORE_FIELDS
# Short items, written in one line with commas: "add Docker, AWS to my skills".
COMMA_LISTS = ("skills", "languages", "frameworks", "links")
# What the job match reads; changing one of these re-scores the stored jobs.
SCORED = ("skills", "languages", "frameworks", "projects", "experience", "internships",
          "education", "degree", "location") + SCORE_FIELDS
MAX_LIST = 40

# The words people use for each, including the ones the router hears.
FIELD_NAMES = {
    "name": "name", "full name": "name",
    "email": "email", "email address": "email", "e-mail": "email", "email id": "email", "mail": "email",
    "phone": "phone", "phone number": "phone", "mobile": "phone", "mobile number": "phone",
    "number": "phone", "contact number": "phone",
    "address": "location", "home address": "location", "city": "location",
    "home location": "location", "current location": "location", "home city": "location",
    "degree": "degree",
    "graduation year": "graduation_year", "passing year": "graduation_year",
    "year of graduation": "graduation_year", "batch": "graduation_year",
    "cgpa": "degree_score", "gpa": "degree_score", "cpi": "degree_score",
    "percentage": "degree_score", "degree score": "degree_score", "degree percentage": "degree_score",
    "degree cgpa": "degree_score", "college cgpa": "degree_score", "btech cgpa": "degree_score",
    "b.tech cgpa": "degree_score",
    "class 12": "class_12", "class 12th": "class_12", "12th": "class_12", "12th marks": "class_12",
    "12th percentage": "class_12", "class xii": "class_12", "xii": "class_12",
    "intermediate": "class_12", "inter": "class_12", "class 12 marks": "class_12",
    "class 10": "class_10", "class 10th": "class_10", "10th": "class_10", "10th marks": "class_10",
    "10th percentage": "class_10", "class x": "class_10", "high school": "class_10",
    "matric": "class_10", "class 10 marks": "class_10",
    "skill": "skills", "skills": "skills",
    "language": "languages", "languages": "languages", "programming language": "languages",
    "programming languages": "languages",
    "framework": "frameworks", "frameworks": "frameworks", "library": "frameworks", "libraries": "frameworks",
    "project": "projects", "projects": "projects",
    "experience": "experience", "work experience": "experience", "job": "experience", "jobs": "experience",
    "internship": "internships", "internships": "internships",
    "certification": "certifications", "certifications": "certifications",
    "certificate": "certifications", "certificates": "certifications",
    "education": "education",
    "achievement": "achievements", "achievements": "achievements", "award": "achievements",
    "awards": "achievements",
    "link": "links", "links": "links", "website": "links", "portfolio": "links",
    "github": "links", "linkedin": "links",
}


def field_for(words: str) -> str | None:
    """Which profile field someone means: "12th percentage" is class_12."""
    key = " ".join(str(words or "").lower().replace("my ", " ").split())
    return FIELD_NAMES.get(key) or (key if key in CHANGEABLE else None)


def edited(profile: dict) -> list[str]:
    """The profile fields you corrected by command since the last scan."""
    marked = profile.get("edited")
    return [f for f in CHANGEABLE if isinstance(marked, list) and f in marked]


def _checked(field: str, value: str) -> tuple[str, str]:
    """A single value as it will be saved, or "" and why it can't be."""
    label = CHANGEABLE[field]
    if field == "name":
        if not (2 <= len(value) <= 80) or re.search(r"[\d@/\\<>]", value):
            return "", "That doesn't look like a name. Say it the way the resume should."
    elif field == "email":
        if len(value) > 120 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", value):
            return "", "That isn't an email address."
    elif field == "phone":
        digits = re.sub(r"\D", "", value)
        if not re.fullmatch(r"\+?[\d\s\-()]{7,20}", value) or not 7 <= len(digits) <= 15:
            return "", "That isn't a phone number. Use digits, with +91 if you like."
    elif field == "graduation_year":
        if not re.fullmatch(r"(19[5-9]\d|20\d\d|2100)", value):
            return "", "Say the graduation year as four digits, like 2026."
    elif field in SCORE_FIELDS:
        g = grades.grade(value)
        if g is None or len(value) > 40:
            return "", ("I couldn't read that as a score. Say it like 7.8/10, 8.2 CGPA or 85%.")
        # A bare number says what it was taken as, so it isn't misread later.
        if not re.search(r"/|%|percent|cgpa|gpa|cpi", value, re.I):
            value = f"{g.value:g}/{g.scale}" if g.scale != 100 else f"{g.value:g}%"
    elif not (1 <= len(value) <= 120):
        return "", f"Keep the {label} under 120 characters."
    return value, ""


def _items(field: str, value: str) -> list[str]:
    parts = value.split(",") if field in COMMA_LISTS else value.split(";")
    return [" ".join(p.split()) for p in parts if p.strip()]


def edit_profile(field: str, value: str = "", change: str = "set") -> str:
    """Correct what the profile says about you: set a single value (your
    phone, your CGPA), or add to and remove from a list (skills, projects,
    links). Only what you said is saved; a new resume scan replaces it with
    what that resume says."""
    key = field_for(field)
    if not key:
        return ("I can correct your name, email, phone, address, degree, graduation year, "
                "CGPA or %, Class 12 and Class 10 marks, and add to or remove from skills, "
                "languages, frameworks, projects, experience, internships, certifications, "
                "education, achievements and links.")
    change = str(change or "set").lower().strip()
    if change not in ("set", "add", "remove", "clear"):
        return "I can set, add, remove or clear."
    value = " ".join(str(value or "").split())
    label = CHANGEABLE[key]
    # "set my github to …" replaces your GitHub link, not every link; "set
    # my portfolio to …" adds one.
    slot = " ".join(str(field or "").lower().replace("my ", " ").split())
    if slot in ("portfolio", "website", "link") and change == "set":
        change = "add"
    slot = slot if slot in ("github", "linkedin") and change == "set" else ""

    profile = load_profile()
    person = profile.setdefault("candidate", json.loads(json.dumps(EMPTY_PROFILE["candidate"])))
    before = edited(profile)

    if key in SINGLE:
        if change == "add":
            return f"Your {label} is a single value. Say: set my {label} to …"
        if change in ("clear", "remove") or not value:
            if not person.get(key):
                return f"Your {label} {'are' if label.endswith('marks') else 'is'} already empty."
            person[key] = ""
            said = f"Cleared your {label}."
        else:
            value, why = _checked(key, value)
            if why:
                return why
            if person.get(key) == value:
                return f"Your {label} {'are' if label.endswith('marks') else 'is'} already {value}."
            person[key] = value
            said = f"Updated your {label}: {value}."
    else:
        have = [str(v) for v in person.get(key, []) if str(v).strip()]
        if change == "clear":
            if not have:
                return f"Your {label} list is already empty."
            person[key] = []
            said = f"Cleared your {label}."
        elif change == "remove":
            wanted = _items(key, value)
            if not wanted:
                return f"Say which one to remove from your {label}."
            gone: list[str] = []
            for want in wanted:
                exact = [v for v in have if v.lower() == want.lower()]
                close = exact or [v for v in have if want.lower() in v.lower()]
                if not close:
                    listed = "; ".join(have[:10]) or "nothing yet"
                    return f"“{want}” isn't in your {label}. They are: {listed}."
                if len(close) > 1 and not exact:
                    return (f"“{want}” matches {len(close)} of your {label}: "
                            + "; ".join(close[:5]) + ". Say more of it.")
                have.remove(close[0])
                gone.append(close[0])
            person[key] = have
            said = f"Removed from your {label}: {'; '.join(gone)}."
        else:                                   # set replaces the list, add appends
            items = _items(key, value)
            if not items:
                return f"Say what to put in your {label}."
            for item in items:
                if len(item) > ITEM_CHARS:
                    return f"“{item[:30]}…” is too long. Keep each under {ITEM_CHARS} characters."
                if key == "links" and not link_ok(item):
                    return f"“{item}” isn't a web address. Say it like github.com/yourname."
            if slot and not all(_core(i).startswith(f"{slot}.com") for i in items):
                return f"That isn't a {slot}.com address."
            base = ([v for v in have if not _core(v).startswith(f"{slot}.com")] if slot
                    else [] if change == "set" else have)
            added = [i for i in items if i.lower() not in (v.lower() for v in base)
                     and i.lower() not in [x.lower() for x in items[:items.index(i)]]]
            if change == "add" and not added:
                return f"Already in your {label}: {', '.join(items)}."
            if len(base) + len(added) > MAX_LIST:
                return f"That's more than {MAX_LIST} {label}. Remove some first."
            person[key] = base + added
            said = (f"Your {'GitHub' if slot == 'github' else 'LinkedIn'} link is now {added[0]}."
                    if slot and added else
                    f"Your {label} are now: {', '.join(person[key])}." if change == "set"
                    else f"Added to your {label}: {', '.join(added)}.")
            there = [i for i in items if i not in added and change == "add"]
            if there and not slot:
                said += f" ({', '.join(there)} {'was' if len(there) == 1 else 'were'} already there.)"
            if slot and not added:
                return f"Your {label} already have {items[0]}."

    profile["edited"] = [f for f in CHANGEABLE if f in before or f == key]
    save_profile(profile)
    if key in SCORED:
        rescored = _rescore(profile)
        if rescored:
            said += f" Re-scored {rescored} stored job{'' if rescored == 1 else 's'}."
    if key not in before:
        said += " A new resume scan replaces this with what that resume says."
    return said
