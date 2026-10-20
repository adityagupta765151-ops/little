"""The fast lane.

Simple commands ("open Chrome") are handled here in milliseconds, with no
model call at all. Anything this doesn't recognise falls through to the AI.
Understands plain English and common Hinglish phrasing.
"""
from __future__ import annotations

import datetime
import re
import threading
import webbrowser

from ..app import health
from ..store import memory
from ..tools import (apps, browser, contacts, reminders, screen,
                     whatsapp, whatsapp_web)
from ..jobs import dashboard as job_dashboard, engine as jobs

# Everything health.py can check, plus the words people actually use for
# them, so "check the microphone" and "check mic" both land.
COMPONENTS = "|".join(sorted(
    set(health.PROBES) | {"ai", "model", "voice", "speaker", "microphone",
                          "db", "internet"},
    key=len, reverse=True))

SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "linkedin": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com",
    "chatgpt": "https://chat.openai.com",
    "stackoverflow": "https://stackoverflow.com",
    "leetcode": "https://leetcode.com",
    "whatsapp web": "https://web.whatsapp.com",
}

OPEN = r"(?:open|launch|start|kholo|khol do|chalu karo)"
CLOSE = r"(?:close|quit|exit|band karo|band kar do)"

# Hindi and Hinglish put the verb after the thing: "chrome kholo".
OPEN_AFTER = re.compile(r"^(.+?)\s+(?:kholo|khol do|chalu karo|open karo|start karo)\.?$", re.I)
CLOSE_AFTER = re.compile(r"^(.+?)\s+(?:band karo|band kar do|close karo|bandh karo)\.?$", re.I)


def _clean(name: str) -> str:
    return name.strip(" .,!?").removeprefix("the ").strip()


# Correcting the resume profile by command (Chapter 26). Matched on what you
# typed, not lowercased, so "set my name to Aditya Gupta" keeps its capitals.
# "location" stays the job-search preference it already was; your own
# address is "address" or "city".
PROFILE_FIELD = (r"full name|name|email address|email id|email|e-mail|phone number|phone|mobile number|mobile|"
                 r"contact number|home address|address|home location|current location|home city|city|"
                 r"graduation year|passing year|year of graduation|batch|degree cgpa|degree score|"
                 r"degree percentage|college cgpa|b\.?tech cgpa|degree|cgpa|gpa|cpi|percentage|"
                 r"class 12th|class 12 marks|class 12|12th marks|12th percentage|12th|class xii|intermediate|"
                 r"class 10th|class 10 marks|class 10|10th marks|10th percentage|10th|class x|high school|matric|"
                 r"github|linkedin|portfolio|website")
LIST_FIELD = (r"skills?|programming languages?|languages?|frameworks?|librar(?:y|ies)|projects?|"
              r"work experience|experience|internships?|certifications?|certificates?|education|"
              r"achievements?|awards?|links?")


def _profile_edit(command: str) -> tuple[str, str, str] | None:
    """(field, value, change) for a command that corrects the profile."""
    c = command.strip().rstrip(".!")
    m = re.fullmatch(rf"(?:set|change|update|correct|fix)\s+(?:my\s+)?({PROFILE_FIELD}|{LIST_FIELD})"
                     rf"\s+(?:to|as|=)\s+(.+)", c, re.I)
    if m:
        return m.group(1), m.group(2), "set"
    m = re.fullmatch(rf"(?:meri|mera|mere)\s+({PROFILE_FIELD})\s+(.+?)\s+(?:kar do|kardo|karo|set karo|set kar do)",
                     c, re.I)
    if m:
        return m.group(1), m.group(2), "set"
    m = re.fullmatch(rf"(?:clear|remove|delete)\s+my\s+({PROFILE_FIELD})", c, re.I)
    if m:
        return m.group(1), "", "clear"
    m = re.fullmatch(rf"clear\s+my\s+({LIST_FIELD})", c, re.I)
    if m:
        return m.group(1), "", "clear"
    m = re.fullmatch(rf"add\s+(.+?)\s+(?:to|in)\s+my\s+({LIST_FIELD})", c, re.I)
    if m:
        return m.group(2), m.group(1), "add"
    m = re.fullmatch(rf"add\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?({LIST_FIELD})\s*[:\-–]?\s+(.+)", c, re.I)
    if m:
        return m.group(1), m.group(2), "add"
    m = re.fullmatch(rf"remove\s+(.+?)\s+from\s+my\s+({LIST_FIELD})", c, re.I)
    if m:
        return m.group(2), m.group(1), "remove"
    m = re.fullmatch(rf"remove\s+(?:the\s+)?({LIST_FIELD})\s*[:\-–]?\s+(.+)", c, re.I)
    if m:
        return m.group(1), m.group(2), "remove"
    return None


def _open_url(url: str, reply: str) -> str:
    webbrowser.open(url)
    return reply


# Memory by tier (Chapter 30). Matched on what you typed, so values keep
# their capitals ("VS Code", "D:/dev"); names are lowercased when stored.
MEMORY_COMMANDS = (
    (r"remember (?:for|in) (?:the |my )?project (.+?)(?:,|:| that) (.+?) (?:is|are) (.+)", "project"),
    (r"remember that (?:my )?(?:preferred|favou?rite) (.+?) (?:is|are) (.+)", "preference"),
    (r"remember that (.+?) (?:is|are) (.+)", "long-term"),
    (r"(?:what do you (?:remember|know)|what have you stored) (?:about|for) (?:the |my )?project (.+?)\??", "project?"),
    (r"(?:what do you (?:remember|know)|what have you stored) about (.+?)\??", "about?"),
    (r"(?:what are|show|list) my preferences\??", "preferences?"),
    (r"(?:what do you remember|what have you stored).*", "all?"),
    (r"forget (?:everything (?:about|for) )?(?:the |my )?project (.+?)[.!]?", "forget project"),
    (r"forget (?:that |about )?(.+?) (?:for|from|in) (?:the |my )?project (.+?)[.!]?", "forget in project"),
    (r"forget (?:that |about )?(?!(?:it|that|this|everything|all)\b)(.+?)[.!]?", "forget"),
)


def _memory_command(command: str) -> str | None:
    for pattern, kind in MEMORY_COMMANDS:
        match = re.fullmatch(pattern, command, re.I | re.S)
        if not match:
            continue
        got = [_clean(g) for g in match.groups()]
        if kind == "project":
            return memory.remember_for_project(got[0], got[1], got[2])
        if kind == "preference":
            return memory.set_preference(got[0], got[1])
        if kind == "long-term":
            return memory.remember(got[0], got[1])
        if kind == "project?":
            return memory.recall_project(got[0])
        if kind == "about?":
            return memory.recall_about(got[0])
        if kind == "preferences?":
            found = memory.preferred()
            return ("Your preferences: " + "; ".join(f"{k}: {v}" for k, v in found.items()) + "."
                    if found else "You haven't told me any preferences yet. Say: remember that my preferred "
                                  "browser is Firefox.")
        if kind == "all?":
            return memory.recall()
        if kind == "forget project":
            return memory.forget_project(got[0])
        if kind == "forget in project":
            return memory.forget_for_project(got[1], got[0])
        if len(got[0].split()) > 6:        # a sentence for the model, not a name
            return None
        return memory.forget_anything(got[0])
    return None


# Your knowledge base (Chapter 31). Matched on what you typed, so a path or
# a question keeps its capitals.
# Adding, listing and removing need the words "knowledge base" — "add this
# to my documents" could mean the Documents folder. Asking takes any of them.
KB = r"(?:my |the )?(?:knowledge ?base|kb)"
KB_ANY = r"(?:my |the )?(?:knowledge ?base|kb|documents|docs|notes)"
KNOWLEDGE_COMMANDS = (
    (rf"(?:add|index|learn|read) (.+?) (?:to|into|in) {KB}\.?", "add"),
    (rf"(?:list|show)(?: me)? {KB}\.?|what(?:'s| is) in {KB}\??|what documents do you have\??", "list"),
    (rf"(?:remove|delete|drop) (.+?) from {KB}\.?", "remove"),
    (rf"search {KB_ANY} (?:for|about) (.+)", "search"),
    (rf"(?:ask {KB_ANY}|according to {KB_ANY}|check {KB_ANY})[,:]?\s+(.+)", "ask"),
)


def _knowledge_command(command: str) -> str | None:
    for pattern, kind in KNOWLEDGE_COMMANDS:
        match = re.fullmatch(pattern, command, re.I | re.S)
        if not match:
            continue
        from ..store import knowledge
        got = match.groups()
        if kind == "add":
            return knowledge.add_document(got[0].strip().strip("\"'"))
        if kind == "list":
            return knowledge.list_documents()
        if kind == "remove":
            return knowledge.remove_document(got[0].strip().strip("\"'"))
        if kind == "search":
            return knowledge.search_documents(got[0])
        return knowledge.ask_documents(got[0])
    return None


# Which path the last command on this thread took (Chapter 33): "fast" for
# what's answered from what LITTLE already holds, "normal" for the rest of
# what's answered here without the model.
_path = threading.local()


def _fast(reply: str | None) -> str | None:
    """Mark this answer as the fast path."""
    if reply is not None:
        _path.name = "fast"
    return reply


def last_path() -> str:
    """"fast" or "normal": how fast_route answered on this thread."""
    return getattr(_path, "name", "normal")


def fast_route(command: str) -> str | None:
    """Return a reply if we can handle this locally, else None."""
    _path.name = "normal"
    text = command.lower().strip()
    if not text:
        return None

    if re.fullmatch(r"(what(?:'s| is) the )?time\b.*|time kya h(?:ai)?\??", text):   # not "timeline"
        return _fast(datetime.datetime.now().strftime("It's %I:%M %p."))
    if re.fullmatch(r"(what(?:'s| is) the )?date.*|aaj ki date.*|today'?s date.*", text):
        return _fast(datetime.datetime.now().strftime("Today is %A, %d %B %Y."))
    if re.fullmatch(r"(?:how fast are you|show (?:me )?(?:your )?(?:speed|latency)|latency report|speed report)\??",
                    text):
        from ..app import latency
        return _fast(latency.report())
    # Benchmarks (Chapter 46).
    if re.fullmatch(r"(?:run a |run the )?benchmark(?: yourself)?\.?|benchmark yourself\.?|how fast is everything\??", text):
        from ..app import benchmark
        return benchmark.benchmark(include_model=False)
    if re.fullmatch(r"benchmark (?:the model|the models|everything)(?: too)?\.?", text):
        from ..app import benchmark
        return benchmark.benchmark(include_model=True)

    # The coding agent (Chapter 44).
    match = re.fullmatch(r"(?:in|to) (?:the|my) code,?\s+(.+)", command.strip(), re.I | re.S)
    if match:
        from ..ai import coder
        return coder.code_change(match.group(1))
    if re.fullmatch(r"undo (?:the |my )?last code change\.?", text):
        from ..ai import coder
        return coder.undo_last()

    # Which model answers what (Chapter 43).
    if re.fullmatch(r"which models? (?:do you use|answers?)(?: for what)?\??|what models? do you use\??|"
                    r"(?:show )?(?:the )?model rout(?:er|ing)\??", text):
        from ..ai import models
        return _fast(models.report())

    # Failures and recoveries (Chapter 42).
    if re.fullmatch(r"what(?:'s| has)? (?:gone|went) wrong(?: lately| today| recently)?\??|any (?:errors|failures)"
                    r"(?: lately| today| recently)?\??|what failed(?: lately| today)?\??", text):
        from ..app import recovery
        return _fast(recovery.report())

    # The audit log (Chapter 41).
    if re.fullmatch(r"(?:show me |tell me )?what (?:did you do|you did) (?:for|on|in) (?:my|the) last (?:task|command)\??|"
                    r"what did you (?:just )?do\??", text):
        from ..app import audit
        return _fast(audit.last_task())
    if re.fullmatch(r"(?:show (?:me )?)?(?:the |your )?audit (?:log|trail)\??", text):
        from ..app import audit
        return _fast(audit.recent_report())

    # Outside tools over MCP (Chapter 39).
    if re.fullmatch(r"(?:what|which|list|show)(?: me)? (?:your )?(?:outside|external|mcp) tools(?: do you have)?\??", text):
        from ..tools import external
        return _fast(external.report())
    if re.fullmatch(r"(?:reload|restart) (?:the )?(?:outside|external|mcp) tools\.?", text):
        from ..tools import external
        external.load()
        return external.report()

    # The tool registry, asked about (Chapter 38).
    if re.fullmatch(r"(?:what|which) tools do you have\??|(?:list|show) (?:me )?(?:your|all|all your) tools\.?|"
                    r"how many tools do you have\??", text):
        from ..tools import catalog
        return _fast(catalog.what_tools())
    if re.fullmatch(r"which tools (?:require|need|ask for) (?:confirmation|permission|your (?:yes|permission))\??|"
                    r"which tools ask (?:first|before (?:they|acting))\??", text):
        from ..tools import catalog
        return _fast(catalog.asking())
    match = re.fullmatch(r"which tools (?:use|need|touch|open|go to|talk to) (.+?)\??", text)
    if match:
        from ..tools import catalog
        return _fast(catalog.using(match.group(1)))
    if re.fullmatch(r"(?:security (?:report|center|centre|status)|show (?:me )?(?:the )?security(?: center| centre)?|"
                    r"what (?:tools )?(?:can you do without asking|needs? my (?:yes|permission)))\??", text):
        from ..app import security
        return _fast(security.report())

    # Suggestions (Chapter 36): on, off, per kind, or everything now.
    if re.fullmatch(r"(?:stop|turn off|no more|disable) (?:your )?suggestions\.?", text):
        from ..app import proactive
        return _fast(proactive.set_enabled(False))
    if re.fullmatch(r"(?:turn on|start|enable) (?:your )?suggestions\.?", text):
        from ..app import proactive
        return _fast(proactive.set_enabled(True))
    match = re.fullmatch(r"(?:stop|don't keep) suggesting (?:about )?(.+?)\.?", text)
    if match:
        from ..app import proactive
        return _fast(proactive.set_kind(match.group(1), False))
    match = re.fullmatch(r"(?:start|resume) suggesting (?:about )?(.+?)\.?", text)
    if match:
        from ..app import proactive
        return _fast(proactive.set_kind(match.group(1), True))
    if re.fullmatch(r"(?:any suggestions|what should i (?:look at|do next)|anything (?:i should|to) (?:know|look at)|"
                    r"what needs my attention)\??", text):
        from ..app import proactive
        return proactive.list_now()
    if re.fullmatch(r"(?:wake word (?:status|report)|how do you hear your name|"
                    r"(?:is|are) (?:the )?wake word (?:local|offline|on this computer))\??", text):
        from ..voice import local_wake
        return _fast(local_wake.report())

    # ------------------------------------------------ your documents (Chapter 31)
    said = _knowledge_command(command.strip())
    if said is not None:
        return said

    # ------------------------------------------------ browser
    if re.fullmatch(r"(close|quit) (the )?browser.*|browser band karo.*", text):
        return browser.close_browser()

    match = re.match(r"(?:summari[sz]e|summary of) (?:this |the )?(?:page|website|site|article)"
                     r"(?: (?:at |on )?(\S+))?", text)
    if match:
        return browser.summarize_page(match.group(1))

    match = re.match(r"(?:summari[sz]e|read) (https?://\S+|www\.\S+)", text)
    if match:
        return browser.summarize_page(match.group(1))

    match = re.match(r"(?:read|padho) (?:this |the )?page.*", text) or \
        re.fullmatch(r"(?:this |the |yeh |ye )?page (?:padho|padh do|read karo)\.?", text)   # Hinglish order
    if match:
        return browser.read_page()

    # The browser agent (Chapter 28): look at the page, or reach a goal on it.
    if re.fullmatch(r"(?:what'?s on|what is on|describe|inspect|look at) (?:this |the )?(?:web ?)?page\??", text):
        from ..tools import browser_agent
        return browser_agent.look_at_page()
    match = re.fullmatch(r"(?:in the browser|on the web ?page|browser),?\s+(.+)", command.strip(), re.I)
    if match:
        from ..tools import browser_agent
        return browser_agent.run_task(match.group(1))

    match = re.match(r"(?:look up|research|find out(?: about)?)\s+(.+)", text)
    if match:
        return browser.search_web_and_read(_clean(match.group(1)))

    # ------------------------------------------------ screen
    match = re.fullmatch(r"(?:where is|find|locate) (?:the )?(.+?) on (?:the |my )?screen\??", text)
    if match:
        return screen.find_on_screen(_clean(match.group(1)))
    match = re.fullmatch(r"click (?:on )?(?:the )?(.+?) on (?:the |my )?screen\.?", command.strip(), re.I)
    if match:
        return screen.click_on_screen(_clean(match.group(1)))
    if "screenshot" in text and "explain" not in text:
        return screen.take_screenshot()
    if re.search(r"(look at|read|check).*(screen|display)|screen (par|pe) kya", text):
        return screen.describe_screen()

    # ------------------------------------------------ search and sites
    match = re.search(r"(?:search|find|play)\s+(?:for\s+)?(.+?)\s+on\s+youtube", text) or \
            re.search(r"youtube\s+(?:par|pe|on)?\s*(?:search|play)?\s*(.+)", text)
    if match and "youtube" in text:
        query = _clean(match.group(1))
        if query:
            return _open_url(f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}",
                             f"Searching YouTube for {query}.")

    match = re.match(r"(?:google|search(?: for)?|dhundo)\s+(.+)", text)
    if match and "youtube" not in text:
        query = _clean(match.group(1))
        return _open_url(f"https://www.google.com/search?q={query.replace(' ', '+')}",
                         f"Searching for {query}.")

    # ------------------------------------------------ job hunting
    match = re.match(r"scan (?:my )?resume\s*(.*)", text)
    if match:
        from ..jobs import resume as resume_module
        target = _clean(match.group(1))
        return resume_module.scan_resume(target or "resume.pdf")

    if re.fullmatch(r"(show|what'?s in) (my )?(resume )?profile.*", text):
        from ..jobs import resume as resume_module
        return resume_module.show_profile()

    match = re.match(r"set (?:my )?(roles?|locations?|countr(?:y|ies)|work[ _]?modes?|"
                     r"(?:employment|job)[ _]?types?)\s+(?:to|as|=)\s+(.+)", text)
    if match:
        from ..jobs import resume as resume_module
        field = match.group(1).replace("country", "countries").rstrip("s") + "s"
        field = {"countriess": "countries", "work modes": "work_modes",
                 "workmodes": "work_modes", "work_modes": "work_modes",
                 "employment types": "employment_types",
                 "employment_types": "employment_types",
                 "job types": "employment_types",
                 "job_types": "employment_types"}.get(field, field)
        return resume_module.set_preference(field, match.group(2))

    if re.fullmatch(r"(?:check|review) (?:my )?resume(?: health)?\.?|resume (?:health|check)(?: check)?\.?|"
                    r"is my resume (?:ok|okay|good|fine)\??|mera resume check karo\.?", text):
        from ..jobs import resume_check
        return resume_check.check_resume()

    edit = _profile_edit(command)
    if edit:
        from ..jobs import resume as resume_module
        return resume_module.edit_profile(*edit)

    if re.fullmatch(r"(what )?(voice|which voice).*|list voices.*|voice settings.*", text):
        from ..voice import voice_report
        return voice_report()

    # ------------------------------------------------ self-diagnostics
    # "full" means also make one real call to the model, so it is opt-in.
    if re.fullmatch(r"(?:run |do )?(?:a |the )?(?:full|complete|deep)\s+"
                    r"(?:system |self )?(?:check|checkup|diagnostics?|health check).*", text):
        return health.system_check(live=True)

    if re.fullmatch(r"(?:run |do |perform )?(?:a |the )?(?:system|self|health)\s+"
                    r"(?:check|checkup|diagnostics?|test|report)\.?|"
                    r"(?:run )?(?:the )?diagnostics\.?|"
                    r"check (?:yourself|your health|everything)\.?|"
                    r"are you (?:ok|okay|alright|healthy|well|working|fine)\??|"
                    r"is everything (?:ok|okay|working|fine|alright)\??|"
                    r"sab (?:kuch )?th(?:ee|i)k hai\??|status report\.?", text):
        return health.system_check()

    match = re.fullmatch(rf"(?:check|test) (?:the |my )?({COMPONENTS})"
                         rf"(?: working)?\??|"
                         rf"is (?:the |my )?({COMPONENTS}) (?:working|ok|okay|fine)\??", text)
    if match:
        return health.check_component(match.group(1) or match.group(2))

    if re.fullmatch(r"(open )?(my )?(job )?dashboard.*", text):
        return job_dashboard.open_dashboard()

    if re.fullmatch(r"(find|search)( me)?( today'?s)? jobs.*|find jobs for me.*", text):
        return jobs.find_jobs()

    match = re.match(r"(?:find|search) (.+?) jobs(?: in (.+))?$", text)
    if match:
        return jobs.find_jobs(_clean(match.group(1)), _clean(match.group(2) or ""))

    if re.fullmatch(r"(show )?(my )?top (matches|jobs|10|ten).*", text):
        return jobs.top_matches()

    match = re.fullmatch(r"(?:show )?jobs (?:where |with )?(?:my )?(?:match |score )?"
                         r"(?:is )?(?:above|over|at least) (\d+).*", text)
    if match:
        return jobs.top_matches(count=15, min_score=int(match.group(1)))

    # Freshness: a month-old backlog and this week's postings are different
    # questions, and until now there was no way to ask the second one.
    if re.fullmatch(r"(?:show |any )?(?:new|fresh|recent|latest) jobs"
                    r"(?: (?:from )?(?:this week|today))?\.?|"
                    r"(?:show )?jobs posted (?:this week|recently|today)\.?|"
                    r"(?:kuch )?nayi jobs.*", text):
        days = 1 if "today" in text else 7
        return jobs.top_matches(count=15, max_age_days=days)

    match = re.fullmatch(r"(?:show )?jobs posted in the last (\d+) days?\.?", text)
    if match:
        return jobs.top_matches(count=15, max_age_days=int(match.group(1)))

    match = re.match(r"why (?:did you (?:pick|select|choose) )?(?:this |job )?(.+)", text)
    if match and "job" in text:
        return jobs.why_this_job(_clean(match.group(1).replace("job", "")))

    if re.fullmatch(r"(which |what )?skills (am i |i am )?missing.*", text):
        return jobs.missing_skills()

    # The application tracker (Chapter 27).
    match = re.fullmatch(r"(?:show )?(?:the )?(?:history|timeline) (?:of|for) (?:job )?(.+?)\??", text) or \
        re.fullmatch(r"(?:show )?job (\d+)(?:'s)? (?:history|timeline)\??", text)
    if match:
        return jobs.job_history(_clean(match.group(1)))
    match = re.fullmatch(r"verify (?:my )?(?:application|submission) (?:to|for|at) (?:job )?(.+?)\??", text)
    if match:
        from ..jobs import apply as job_apply
        return job_apply.verify_submission(_clean(match.group(1)))
    match = re.fullmatch(r"mark (?:job )?(.+?) (?:as )?submitted,? with (?:the )?"
                         r"(?:confirmation|reference)(?: number| no\.?| id)?:? (\S+)", command.strip().rstrip("."), re.I)
    if match:
        from ..jobs import apply as job_apply
        return job_apply.mark_submitted(_clean(match.group(1)), match.group(2))

    if re.fullmatch(r"(show )?(my )?application status.*|where (did|have) you applied.*", text):
        return jobs.application_status()

    if re.fullmatch(r"how effective.*|(show )?(my )?effectiveness.*", text):
        return jobs.effectiveness()

    match = re.match(r"(?:open|search) (linkedin|naukri|indeed|internshala|wellfound)"
                     r"(?: for (.+?))?(?: in (.+))?$", text)
    if match:
        return jobs.open_board(match.group(1), _clean(match.group(2) or ""),
                               _clean(match.group(3) or ""))

    # ------------------------------------------------ contacts
    match = re.match(r"import contacts?(?: from)?\s+(.+)", text)
    if match:
        return contacts.import_contacts(_clean(match.group(1)))
    if re.fullmatch(r"how many contacts.*|count (my )?contacts.*", text):
        return contacts.count_contacts()
    match = re.match(r"(?:find|search) contacts?\s+(?:for\s+)?(.+)", text)
    if match:
        return contacts.find_contacts(_clean(match.group(1)))

    # ------------------------------------------------ whatsapp in the browser
    if re.fullmatch(r"(open )?whatsapp web.*", text):
        return whatsapp_web.wa_open()
    if re.fullmatch(r"(list|show)( me)? (my )?(whatsapp )?(chats|contacts).*", text):
        return whatsapp_web.wa_contacts()
    if re.fullmatch(r"read (this |the )?chat.*|last messages.*", text):
        return whatsapp_web.wa_read_chat()

    match = re.search(rf"{OPEN}\s+(.+?)(?:'s)?\s*(?:chat|whatsapp chat)$", text)
    if match and "whatsapp" in text:
        return whatsapp.open_contact(_clean(match.group(1).replace("whatsapp", "")))

    match = re.match(rf"{OPEN}\s+(.+)", text) or OPEN_AFTER.match(text)
    if match:
        target = _clean(match.group(1))
        if target in SITES:
            return _open_url(SITES[target], f"Opening {target}.")
        if target.startswith(("http://", "https://", "www.")) or target.endswith((".com", ".in", ".org")):
            url = target if target.startswith("http") else f"https://{target}"
            return _open_url(url, f"Opening {target}.")
        if apps.resolve(target):
            return apps.open_app(target)
        return None  # unknown target, let the AI work it out

    match = re.match(rf"{CLOSE}\s+(.+)", text) or CLOSE_AFTER.match(text)
    if match:
        target = _clean(match.group(1))
        if apps.resolve(target):
            return apps.close_app(target)
        return None

    # ------------------------------------------------ reminders and memory
    match = re.match(r"remind me (?:to )?(.+?) (?:at|in) (.+)", text)
    if match:
        return _fast(reminders.set_reminder(_clean(match.group(1)), match.group(2)))
    if re.fullmatch(r"(list|show|what are my) reminders.*", text):
        return _fast(reminders.list_reminders())
    if re.fullmatch(r"cancel (all )?reminders.*", text):
        return _fast(reminders.cancel_reminders())

    said = _memory_command(command.strip())
    if said is not None:
        return _fast(said)

    if re.fullmatch(r"(send it|send|bhej do|haan bhej do)\.?", text):
        # Finish whichever draft is actually waiting: browser or desktop app.
        if whatsapp_web.has_draft():
            return whatsapp_web.wa_send_web()
        return whatsapp.send_whatsapp_message()

    return None
