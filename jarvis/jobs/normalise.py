"""Turning six boards' idea of a job posting into one.

Every board sends a date; no two send it the same way. Adzuna sends ISO with
a timezone, RemoteOK sends a unix epoch, Jobicy sends RFC-822 out of an RSS
feed, and one of them occasionally sends nothing at all. The same is true of
employment type, which three boards name and three leave in the prose.

The rule throughout: a field that can't be read is left empty, never
guessed into existence and never a reason to drop the job. A posting with no
date is still a posting, and an empty cell is honest in a way that
`datetime.now()` is not.
"""
from __future__ import annotations

import datetime
import re

# ------------------------------------------------------------------ dates

# The formats the six boards actually send, most common first.
DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%a, %d %b %Y %H:%M:%S %z",      # RSS, as Jobicy sends it
    "%a, %d %b %Y %H:%M:%S %Z",
    "%d %b %Y",
    "%Y/%m/%d",
)


def parse_date(value) -> str:
    """Any board's date into a plain ISO day, or "" if it can't be read.

    Returns the day only. The hour a posting went up is noise — nobody
    sorts jobs by the minute — and dropping it makes every board comparable.
    """
    if value is None or value == "":
        return ""

    # RemoteOK sends a unix epoch, sometimes as a string.
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        try:
            seconds = float(value)
            if seconds > 1e11:            # milliseconds
                seconds /= 1000
            if not 946_684_800 < seconds < 4_102_444_800:   # 2000..2100
                return ""
            return datetime.datetime.fromtimestamp(
                seconds, datetime.timezone.utc).date().isoformat()
        except (ValueError, OverflowError, OSError):
            return ""

    if not isinstance(value, str):
        return ""
    text = value.strip()

    # Python's %z won't take the colon in "+05:30" before 3.11 everywhere.
    normalised = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", text)
    for pattern in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(normalised, pattern).date().isoformat()
        except ValueError:
            continue

    try:                                   # anything else ISO-shaped
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def days_since(posted_at: str) -> int | None:
    """Whole days since the posting went up, or None if there's no date."""
    if not posted_at:
        return None
    try:
        posted = datetime.date.fromisoformat(posted_at[:10])
    except ValueError:
        return None
    return max(0, (datetime.date.today() - posted).days)


def age_phrase(posted_at: str) -> str:
    """How old it is, in the words someone would actually use.

    A job hunter never wants the date. They want to know whether it is worth
    applying to, and "posted 2 months ago" answers that where "2026-07-14"
    makes them do the arithmetic themselves.
    """
    days = days_since(posted_at)
    if days is None:
        return ""
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 14:
        return "last week"
    if days < 60:
        return f"{days // 7} weeks ago"
    return f"{days // 30} months ago"


STALE_DAYS = 45


def is_stale(posted_at: str) -> bool:
    """Old enough that the role has probably gone. A job with no date is
    not called stale — not knowing is not the same as knowing it's old."""
    days = days_since(posted_at)
    return days is not None and days > STALE_DAYS


# -------------------------------------------------------- employment type

TYPES = ("internship", "contract", "part-time", "temporary", "full-time")

# Ordered: internship wins over full-time, because an unpaid six-month
# internship is described as full-time on half the boards that list it.
TYPE_PATTERNS = (
    ("internship", r"\bintern(ship|e)?\b|\btrainee\b|\bsummer analyst\b|\bapprentice"),
    ("contract", r"\bcontract(or|ual)?\b|\bfreelance\b|\bb2b\b|\bconsultan(t|cy)\b|\bc2h\b"),
    ("part-time", r"\bpart[\s-]?time\b|\bparttime\b"),
    ("temporary", r"\btemporary\b|\btemp\b|\bseasonal\b|\bfixed[\s-]term\b"),
    ("full-time", r"\bfull[\s-]?time\b|\bfulltime\b|\bpermanent\b"),
)

# What the boards call these in their own fields.
TYPE_ALIASES = {
    "full_time": "full-time", "fulltime": "full-time", "full time": "full-time",
    "permanent": "full-time",
    "part_time": "part-time", "parttime": "part-time", "part time": "part-time",
    "contract": "contract", "contractor": "contract", "freelance": "contract",
    "internship": "internship", "intern": "internship",
    "temporary": "temporary", "temp": "temporary",
}


def employment_type(declared: str = "", title: str = "", description: str = "") -> str:
    """What kind of engagement this is, or "" when nothing says.

    A board's own field is taken at its word. Otherwise the title is read
    before the description, because "Software Engineering Intern" is a fact
    and "our interns love it here" in the blurb is not.
    """
    key = (declared or "").strip().lower().replace("-", "_")
    if key in TYPE_ALIASES:
        return TYPE_ALIASES[key]
    if key.replace("_", " ") in TYPE_ALIASES:
        return TYPE_ALIASES[key.replace("_", " ")]

    # Some boards don't have a type field but put it in their tags, which
    # arrive here as the declared value without matching an alias exactly.
    for name, pattern in TYPE_PATTERNS:
        if declared and re.search(pattern, declared, re.I):
            return name
    for name, pattern in TYPE_PATTERNS:
        if re.search(pattern, title or "", re.I):
            return name
    for name, pattern in TYPE_PATTERNS:
        if re.search(pattern, (description or "")[:600], re.I):
            return name
    return ""


# ------------------------------------------------------------- seniority

LEVELS = ("intern", "junior", "mid", "senior", "lead")

# Titles only. Descriptions say "work with senior engineers" in half the
# junior postings ever written.
LEVEL_PATTERNS = (
    ("intern", r"\bintern(ship)?\b|\btrainee\b|\bapprentice\b"),
    ("lead", r"\blead\b|\bprincipal\b|\bstaff\b|\bhead of\b|\barchitect\b|\bmanager\b|"
             r"\bdirector\b|\bvp\b|\bchief\b"),
    ("senior", r"\bsenior\b|\bsr\.?\b|\bsde\s*[23]\b|\bii+i\b|\bexperienced\b"),
    ("junior", r"\bjunior\b|\bjr\.?\b|\bentry[\s-]level\b|\bgraduate\b|\bfresher\b|"
               r"\bassociate\b|\bsde\s*1\b|\btrainee\b|\bcampus\b"),
)


def seniority(title: str = "", description: str = "") -> str:
    """intern / junior / mid / senior / lead, or "" when the title is silent.

    "mid" is only ever returned when a description says so outright. A plain
    "Software Engineer" is genuinely unlabelled, and calling that mid-level
    would be inventing a fact the posting didn't state.
    """
    for name, pattern in LEVEL_PATTERNS:
        if re.search(pattern, title or "", re.I):
            return name
    if re.search(r"\bmid[\s-]?(level|senior)\b", f"{title} {description[:400]}", re.I):
        return "mid"
    return ""


# -------------------------------------------------------------- location

COUNTRIES = {
    "india": "India", "in": "India", "bharat": "India",
    "united states": "United States", "usa": "United States", "us": "United States",
    "u.s.": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "united kingdom": "United Kingdom", "england": "United Kingdom",
    "canada": "Canada", "germany": "Germany", "deutschland": "Germany",
    "australia": "Australia", "singapore": "Singapore", "ireland": "Ireland",
    "netherlands": "Netherlands", "france": "France", "spain": "Spain",
    "poland": "Poland", "portugal": "Portugal", "brazil": "Brazil", "mexico": "Mexico",
    "japan": "Japan", "china": "China", "uae": "UAE",
    "united arab emirates": "UAE", "philippines": "Philippines", "indonesia": "Indonesia",
    "worldwide": "Worldwide", "anywhere": "Worldwide", "global": "Worldwide",
    "remote": "Worldwide", "emea": "EMEA", "apac": "APAC", "latam": "LATAM",
    "europe": "Europe", "european union": "Europe", "eu": "Europe",
}

# Indian cities a board might name without naming the country.
INDIAN_CITIES = {
    "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "bombay", "delhi",
    "new delhi", "noida", "gurgaon", "gurugram", "chennai", "madras", "kolkata",
    "ahmedabad", "jaipur", "lucknow", "prayagraj", "allahabad", "indore", "kochi",
    "coimbatore", "chandigarh", "bhubaneswar", "nagpur", "surat", "vadodara", "ncr",
}


def split_location(text: str) -> tuple[str, str]:
    """Free-text location into (city, country), either of which may be "".

    Boards write "Bengaluru, India", "Remote (India Only)", "Worldwide" and
    "Berlin" and mean four different things by them. Only what is actually
    written is returned; nothing is inferred beyond an Indian city implying
    India, which is safe because no other country has a Bengaluru.
    """
    raw = (text or "").strip()
    if not raw:
        return "", ""

    # "Remote (India Only)" and "Remote - India" both name a country.
    cleaned = re.sub(r"\b(remote|hybrid|on-?site|work from home|wfh)\b", " ", raw, flags=re.I)
    cleaned = re.sub(r"[()\[\]]", " ", cleaned)
    cleaned = re.sub(r"\bonly\b|\bbased\b|\bpreferred\b", " ", cleaned, flags=re.I)

    parts = [p.strip(" ,-–—/|") for p in re.split(r"[,/|]|\s+-\s+", cleaned) if p.strip(" ,-–—/|")]
    city = country = ""

    for part in parts:
        key = part.lower().strip(". ")
        if key in COUNTRIES and not country:
            country = COUNTRIES[key]
        elif key in INDIAN_CITIES and not city:
            city, country = part.strip().title(), country or "India"
        elif not city and len(part) > 1 and not re.fullmatch(r"[\d\s]+", part):
            city = part.strip()

    if not country and raw.lower().strip() in COUNTRIES:
        country = COUNTRIES[raw.lower().strip()]
    if city and city.lower() in COUNTRIES:      # "India" alone isn't a city
        country, city = country or COUNTRIES[city.lower()], ""
    return city, country
