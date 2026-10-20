"""Where the jobs come from.

Only public APIs that are published for this purpose. LinkedIn, Naukri,
Indeed and Internshala have no open job API and their terms forbid
scraping, so JARVIS does not pretend to search them: it builds the search
URL and opens it for you to look through yourself.

Each source degrades on its own. One board being down or missing a key
never stops the others.
"""
from __future__ import annotations

import html
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout

import requests

from ..app.config import log
from . import normalise
from .store import job_id_for

# Long enough for a slow board, short enough that one hanging board doesn't
# hold up the answer. They run in parallel, so this is the whole wait.
TIMEOUT = 15
# The whole search, however many boards are slow. One that never answers
# gets left behind rather than holding everyone up.
DEADLINE = 25
HEADERS = {"User-Agent": "JARVIS-job-assistant/1.0 (personal use)"}

# Boards with no API. JARVIS opens these for the user instead of scraping.
MANUAL_BOARDS = {
    "linkedin": "https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}",
    "naukri": "https://www.naukri.com/{q}-jobs-in-{loc}",
    "indeed": "https://in.indeed.com/jobs?q={q}&l={loc}",
    "internshala": "https://internshala.com/internships/keywords-{q}",
    "wellfound": "https://wellfound.com/jobs?query={q}",
}


def _clean(text: str, limit: int = 2500) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _work_mode(text: str) -> str:
    lowered = text.lower()
    if "remote" in lowered or "work from home" in lowered:
        return "remote"
    if "hybrid" in lowered:
        return "hybrid"
    return "onsite"


def _job(company: str, title: str, location: str, url: str,
         description: str, platform: str, salary: str = "",
         posted=None, job_type: str = "") -> dict:
    """One shape, whatever the board called its fields.

    `posted` and `job_type` are whatever the board sent — an epoch, an RSS
    date string, "FULL_TIME", None. Reading them is normalise.py's job, and
    anything it can't read comes back empty rather than invented.
    """
    company, title = company.strip(), title.strip()
    text = f"{location} {description[:600]}"
    city, country = normalise.split_location(location)
    return {
        "job_id": job_id_for(company, title, url),
        "company": company, "title": title,
        "location": location.strip(), "url": url,
        "description": description,
        "work_mode": _work_mode(text),
        "salary": salary, "platform": platform,
        "posted_at": normalise.parse_date(posted),
        "employment_type": normalise.employment_type(job_type, title, description),
        "seniority": normalise.seniority(title, description),
        "city": city, "country": country,
    }


# ---------------------------------------------------------------- Adzuna

def adzuna(query: str, location: str = "", limit: int = 30) -> list[dict]:
    """Adzuna covers Indian listings and has a free developer tier.
    Keys: https://developer.adzuna.com — put them in .env."""
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []

    country = os.getenv("ADZUNA_COUNTRY", "in")
    params = {
        "app_id": app_id, "app_key": app_key,
        "results_per_page": min(50, limit), "what": query,
        "content-type": "application/json",
    }
    if location:
        params["where"] = location

    try:
        response = requests.get(
            f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
            params=params, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code != 200:
            log(f"adzuna {response.status_code}: {response.text[:200]}")
            return []
        results = response.json().get("results", [])
    except Exception as e:  # noqa: BLE001
        log(f"adzuna failed: {e}")
        return []

    jobs = []
    for item in results:
        salary = ""
        low, high = item.get("salary_min"), item.get("salary_max")
        if low:
            salary = f"{round(low/100000, 1)}-{round((high or low)/100000, 1)} LPA"
        jobs.append(_job(
            company=(item.get("company") or {}).get("display_name", "Unknown"),
            title=item.get("title", ""),
            location=(item.get("location") or {}).get("display_name", ""),
            url=item.get("redirect_url", ""),
            description=_clean(item.get("description", "")),
            platform="adzuna", salary=salary,
            posted=item.get("created"),
            job_type=item.get("contract_time") or item.get("contract_type") or ""))
    return jobs


# ---------------------------------------------------------------- Remotive

def remotive(query: str, limit: int = 30) -> list[dict]:
    """Remote software roles. Public, no key needed."""
    try:
        response = requests.get("https://remotive.com/api/remote-jobs",
                                params={"search": query, "limit": limit},
                                headers=HEADERS, timeout=TIMEOUT)
        if response.status_code != 200:
            log(f"remotive {response.status_code}")
            return []
        results = response.json().get("jobs", [])
    except Exception as e:  # noqa: BLE001
        log(f"remotive failed: {e}")
        return []

    return [_job(
        company=item.get("company_name", "Unknown"),
        title=item.get("title", ""),
        location=item.get("candidate_required_location", "Remote"),
        url=item.get("url", ""),
        description=_clean(item.get("description", "")),
        platform="remotive",
        salary=item.get("salary", "") or "",
        posted=item.get("publication_date"),
        job_type=item.get("job_type", "") or "",
    ) for item in results[:limit]]


# ---------------------------------------------------------------- Arbeitnow

def arbeitnow(query: str, limit: int = 30) -> list[dict]:
    """Open job board feed. No key. Filtered locally, since the feed
    itself has no search parameter."""
    try:
        response = requests.get("https://www.arbeitnow.com/api/job-board-api",
                                headers=HEADERS, timeout=TIMEOUT)
        if response.status_code != 200:
            return []
        results = response.json().get("data", [])
    except Exception as e:  # noqa: BLE001
        log(f"arbeitnow failed: {e}")
        return []

    words = [w for w in query.lower().split() if len(w) > 2]
    jobs = []
    for item in results:
        haystack = f"{item.get('title','')} {' '.join(item.get('tags') or [])}".lower()
        if words and not any(w in haystack for w in words):
            continue
        jobs.append(_job(
            company=item.get("company_name", "Unknown"),
            title=item.get("title", ""),
            location=item.get("location", ""),
            url=item.get("url", ""),
            description=_clean(item.get("description", "")),
            platform="arbeitnow",
            posted=item.get("created_at"),
            job_type=(item.get("job_types") or [""])[0]))
        if len(jobs) >= limit:
            break
    return jobs


# ---------------------------------------------------------------- Jobicy

def jobicy(query: str, limit: int = 30) -> list[dict]:
    """Remote roles with a geography filter, so Indian-eligible listings can
    actually be asked for. Public, no key."""
    params = {"count": min(50, limit), "industry": "engineering"}
    country = os.getenv("JARVIS_JOB_GEO", "india").strip().lower()
    if country and country not in ("worldwide", "any"):
        params["geo"] = country
    if query:
        params["tag"] = query.split()[0]

    try:
        response = requests.get("https://jobicy.com/api/v2/remote-jobs",
                                params=params, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code != 200:
            log(f"jobicy {response.status_code}")
            return []
        results = response.json().get("jobs", [])
    except Exception as e:  # noqa: BLE001
        log(f"jobicy failed: {e}")
        return []

    return [_job(
        company=item.get("companyName", "Unknown"),
        title=item.get("jobTitle", ""),
        location=item.get("jobGeo", "Remote"),
        url=item.get("url", ""),
        description=_clean(item.get("jobExcerpt", "") + " " + item.get("jobDescription", "")),
        platform="jobicy",
        posted=item.get("pubDate"),
        job_type=(item.get("jobType") or [""])[0] if isinstance(item.get("jobType"), list)
                 else (item.get("jobType") or ""),
        salary=str(item.get("annualSalaryMin") or "") and
               f"{item.get('annualSalaryMin')}-{item.get('annualSalaryMax')} "
               f"{item.get('salaryCurrency', '')}".strip(),
    ) for item in results[:limit]]


# ---------------------------------------------------------------- The Muse

def themuse(query: str, location: str = "", limit: int = 30) -> list[dict]:
    """The Muse lists Indian offices of a lot of companies. The key is
    optional; without one the rate limit is lower but it still answers."""
    params: dict = {"page": 0, "level": "Entry Level,Internship"}
    where = location or os.getenv("JARVIS_JOB_CITY", "")
    if where:
        params["location"] = where if "," in where else f"{where}, India"
    if os.getenv("MUSE_API_KEY"):
        params["api_key"] = os.getenv("MUSE_API_KEY")

    try:
        response = requests.get("https://www.themuse.com/api/public/jobs",
                                params=params, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code != 200:
            log(f"themuse {response.status_code}")
            return []
        results = response.json().get("results", [])
    except Exception as e:  # noqa: BLE001
        log(f"themuse failed: {e}")
        return []

    words = [w for w in query.lower().split() if len(w) > 2]
    jobs = []
    for item in results:
        title = item.get("name", "")
        if words and not any(w in title.lower() for w in words):
            continue
        places = ", ".join(p.get("name", "") for p in (item.get("locations") or [])[:2])
        jobs.append(_job(
            company=(item.get("company") or {}).get("name", "Unknown"),
            title=title,
            location=places,
            url=(item.get("refs") or {}).get("landing_page", ""),
            description=_clean(item.get("contents", "")),
            platform="themuse",
            posted=item.get("publication_date"),
            job_type=(item.get("levels") or [{}])[0].get("name", "")))
        if len(jobs) >= limit:
            break
    return jobs


# ---------------------------------------------------------------- RemoteOK

def remoteok(query: str, limit: int = 30) -> list[dict]:
    """Public feed, no key. Remote-first, often open worldwide."""
    try:
        response = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=TIMEOUT)
        if response.status_code != 200:
            return []
        payload = response.json()
    except Exception as e:  # noqa: BLE001
        log(f"remoteok failed: {e}")
        return []

    words = [w for w in query.lower().split() if len(w) > 2]
    jobs = []
    for item in payload:
        if not isinstance(item, dict) or not item.get("position"):
            continue                      # the first element is a legal notice
        haystack = f"{item.get('position','')} {' '.join(item.get('tags') or [])}".lower()
        if words and not any(w in haystack for w in words):
            continue
        jobs.append(_job(
            company=item.get("company", "Unknown"),
            title=item.get("position", ""),
            location=item.get("location") or "Remote",
            url=item.get("url", ""),
            description=_clean(item.get("description", "")),
            platform="remoteok",
            salary=item.get("salary", "") or "",
            posted=item.get("epoch") or item.get("date"),
            job_type=" ".join(item.get("tags") or [])))
        if len(jobs) >= limit:
            break
    return jobs


# Adzuna is the one that needs a key; the rest work straight away.
SOURCES = {"adzuna": adzuna, "jobicy": jobicy, "themuse": themuse,
           "remotive": remotive, "remoteok": remoteok, "arbeitnow": arbeitnow}
NEEDS_LOCATION = {"adzuna", "themuse"}


def search(query: str, location: str = "", limit: int = 30) -> tuple[list[dict], list[str]]:
    """Ask every source. Returns the jobs and a note per source, so the
    user can see which board gave what rather than a single total.

    All six are asked at once. Asked one after another, a slow board makes
    everyone wait for it, and six boards at 25 seconds each is two and a
    half minutes of a voice assistant saying nothing at all. They don't
    depend on each other, so there is no reason to queue them.
    """
    def ask(name, fetch) -> tuple[str, list[dict] | None]:
        try:
            return name, (fetch(query, location, limit) if name in NEEDS_LOCATION
                          else fetch(query, limit))
        except Exception as e:  # noqa: BLE001
            log(f"{name} raised: {e}")
            return name, None

    # A board that never answers must not hold the whole search. Each request
    # has its own timeout, but a hung DNS lookup or a socket that neither
    # closes nor replies gets past that, and an assistant that says nothing
    # for five minutes is worse than one that says five boards answered.
    results: dict[str, list[dict] | None] = {}
    pool = ThreadPoolExecutor(max_workers=len(SOURCES))
    try:
        pending = {pool.submit(ask, name, fetch): name
                   for name, fetch in SOURCES.items()}
        try:
            for future in as_completed(pending, timeout=DEADLINE):
                name, found = future.result()
                results[name] = found
        except FuturesTimeout:
            for future, name in pending.items():
                if not future.done():
                    log(f"{name} did not answer within {DEADLINE}s")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    jobs: list[dict] = []
    notes: list[str] = []
    # Reported in a fixed order, not the order they happened to finish, so
    # the same search reads the same way twice.
    for name in SOURCES:
        if name not in results:
            notes.append(f"{name}: too slow, skipped")
            continue
        found = results[name]
        if found is None:
            notes.append(f"{name}: failed")
            continue
        if name == "adzuna" and not found and not os.getenv("ADZUNA_APP_ID"):
            notes.append("adzuna: no key set, skipped")
            continue
        notes.append(f"{name}: {len(found)}")
        jobs.extend(found)

    # The same posting on two boards collapses to one, first seen wins.
    unique: dict[str, dict] = {}
    for job in jobs:
        unique.setdefault(job["job_id"], job)
    return list(unique.values()), notes


def manual_search_url(board: str, query: str, location: str = "") -> str | None:
    """A search link for the boards JARVIS is not allowed to automate."""
    template = MANUAL_BOARDS.get(board.lower().strip())
    if not template:
        return None
    if board.lower() in ("naukri", "internshala"):
        # These two put the search terms in the path, hyphen separated.
        def slug(text: str) -> str:
            return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "software"
        return template.format(q=slug(query), loc=slug(location or "india"))
    return template.format(q=urllib.parse.quote_plus(query),
                           loc=urllib.parse.quote_plus(location))
