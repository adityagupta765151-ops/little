"""Chapter 26 — resume intelligence.

Four things, as chosen:

  Reading more: the degree's CGPA or %, Class 12 and 10 marks,
  achievements and links — each held to the resume's own text, so a score,
  link or achievement the model made up is left out.

  Correcting the profile by command only: set, add, remove, clear. A new
  resume scan replaces the corrections with what that resume says, and
  says so. The job-search preferences keep working exactly as before.

  A posting's academic bar ("CGPA of 7.5 and above", "60% throughout") as a
  concern on the job, never a score change and never a hidden job. Scales
  are never converted.

  A resume health check on this computer — nothing sent to the model.
"""
from __future__ import annotations

import json
import time

import pytest

from jarvis.ai import provider
from jarvis.app import bridge, tasks
from jarvis.jobs import engine, grades, matching, resume, resume_check, store
from jarvis.routing.router import fast_route
from jarvis.tools import permissions
from jarvis.tools.registry import FUNCTIONS, TOOL_SCHEMAS, execute_tool

import _ui

PROFILE = {
    "candidate": {
        "name": "Aditya Gupta", "email": "aditya@example.com", "phone": "9999999999",
        "location": "Prayagraj, Uttar Pradesh, India", "degree": "B.Tech CSE",
        "graduation_year": "2026", "education": ["B.Tech CSE, UCER Prayagraj, 2026"],
        "skills": ["React", "Node.js", "MongoDB", "Docker"], "languages": ["JavaScript"],
        "frameworks": ["Next.js"],
        "projects": ["BloodBridge AI - emergency blood requests in Node.js and React",
                     "QuantDesk - paper trading dashboard in Next.js"],
        "experience": [], "internships": [], "certifications": [],
        "degree_score": "", "class_12": "", "class_10": "", "achievements": [], "links": [],
    },
    "preferences": {"roles": ["Full Stack Developer"], "locations": ["Bangalore"],
                    "work_modes": ["remote"], "countries": ["India"], "employment_types": []},
    "set_by_you": ["locations"],
    "source_file": "aditya-resume.pdf",
    "raw_text_chars": 3200,
}

RESUME_TEXT = """Aditya Gupta
aditya@example.com | +91 99999 99999 | github.com/aditya-g | linkedin.com/in/aditya-g
B.Tech Computer Science, UCER Prayagraj, 2022-2026 — CGPA: 7.0/10
Class XII (CBSE), 2022 — 85.4%
Class X (CBSE), 2020 — CGPA 9.2
Skills: React, Node.js, MongoDB
Projects: BloodBridge AI — emergency blood requests for 3 hospitals, in Node.js
Achievements: Smart India Hackathon 2024 — national finalist
"""

ATTACK = '<img src=x onerror="window.__ran=1">'


class Quiet:
    muted, running = False, False
    brain = None

    def handle(self, text): ...


@pytest.fixture(autouse=True)
def fresh(monkeypatch, workspace):
    monkeypatch.chdir(workspace)
    tasks.reset()
    resume.save_profile(json.loads(json.dumps(PROFILE)))
    yield
    tasks.reset()


@pytest.fixture
def no_model(monkeypatch):
    """Any call to Gemini fails the test that makes it."""
    def refuse(*_a, **_k):
        raise AssertionError("the model was asked")
    monkeypatch.setattr(provider, "call_gemini", refuse)
    monkeypatch.setattr(resume, "ask_text", refuse)


def _job(company, title, description, **extra):
    job = {"job_id": store.job_id_for(company, title), "company": company, "title": title,
           "location": "Bangalore, India", "description": description, "platform": "adzuna",
           "url": f"https://example.com/{company}", **extra}
    store.upsert_job(matching.score_job(job, resume.load_profile()))
    return job["job_id"]


def _person():
    return resume.load_profile()["candidate"]


# ================================================================== grades

class TestReadingAScore:
    @pytest.mark.parametrize("text,value,scale", [
        ("7.0/10", 7.0, 10), ("7/10 CGPA", 7.0, 10), ("8.2 CGPA", 8.2, 10), ("CGPA: 7.5", 7.5, 10),
        ("8.1 CPI", 8.1, 10), ("72%", 72.0, 100), ("88.4 percent", 88.4, 100), ("3.6/4 GPA", 3.6, 4),
        ("GPA 3.6", 3.6, 4), ("9.2", 9.2, 10), ("85", 85.0, 100), ("65 out of 100", 65.0, 100),
    ])
    def test_what_it_means(self, text, value, scale):
        assert grades.grade(text) == (value, scale)

    @pytest.mark.parametrize("text", ["", "2026", "first class", "11/10", "distinction", "120%", "0"])
    def test_what_isnt_a_score(self, text):
        assert grades.grade(text) is None

    def test_a_score_is_stated_only_if_its_number_is_in_the_text(self):
        assert grades.stated_in("7.0/10", "CGPA 7 out of 10")
        assert not grades.stated_in("8.5", "CGPA 7.0/10")
        assert not grades.stated_in("7.0/10", "graduated 2026")


class TestReadingABarInAPosting:
    @pytest.mark.parametrize("posting,expected", [
        ("Eligibility: B.Tech with CGPA of 7.5 and above.", [("degree", 7.5, 10)]),
        ("Candidates should have 7+ CGPA.", [("degree", 7.0, 10)]),
        ("CGPA 8 and above required", [("degree", 8.0, 10)]),
        ("Must have a CGPA of at least 8/10", [("degree", 8.0, 10)]),
        ("GPA 3.5/4.0 or higher preferred", [("degree", 3.5, 4)]),
        ("Minimum 60% throughout 10th, 12th and graduation.", [("throughout", 60.0, 100)]),
        ("10th, 12th and graduation: 60% each", [("throughout", 60.0, 100)]),
        ("Min. 65% in 12th and 60% in graduation", [("class_12", 65.0, 100), ("degree", 60.0, 100)]),
        ("12th: 70%, B.Tech: 7 CGPA", [("class_12", 70.0, 100), ("degree", 7.0, 10)]),
        ("Academic criteria: 60% in class X and XII, 6 CGPA in B.Tech",
         [("school", 60.0, 100), ("degree", 6.0, 10)]),
    ])
    def test_the_bars_it_states(self, posting, expected):
        got = sorted((c.kind, c.grade.value, c.grade.scale) for c in grades.cutoffs(posting))
        assert got == sorted(expected)

    @pytest.mark.parametrize("posting", [
        "Salary 7 LPA, 30% hike after a year.",
        "70% remote, 30% travel.",
        "We offer 100% remote work and a 20% bonus.",
        "No CGPA cutoff. Anyone can apply.",
        "CGPA is not a criteria for this role.",
        "CGPA is not a criteria, whether it's 6 or 9 CGPA.",
        "Requirements: 2+ years experience, 90% uptime SLAs, B.Tech degree",
        "Graduates of the 2024/2025 batch, 5 days a week",
        "Improve test coverage to 80% and cut latency by 40%.",
    ])
    def test_money_remote_and_growth_are_not_bars(self, posting):
        assert grades.cutoffs(posting) == []


class TestWhatABarMeansForYou:
    ME = {"degree_score": "7.0/10", "class_12": "58%", "class_10": ""}

    def test_below_it(self):
        assert grades.concerns("CGPA of 7.5 and above", self.ME) == ["Asks for 7.5 CGPA; your resume says 7.0/10"]

    def test_meeting_it_is_no_concern(self):
        assert grades.concerns("CGPA of 7.0 and above", self.ME) == []
        assert grades.concerns("7+ CGPA", self.ME) == []

    def test_not_stated(self):
        assert grades.concerns("CGPA of 7.5 and above", {}) == [
            "Asks for 7.5 CGPA; your resume doesn't state your degree score"]

    def test_scales_are_never_converted(self):
        out = grades.concerns("Minimum 65% in graduation", self.ME)
        assert out == ["Asks for 65%; your degree score (7.0/10) is on a different scale — "
                       "check how your university converts it"]

    def test_meeting_one_alternative_is_enough(self):
        assert grades.concerns("Must have 65% or 6.5 CGPA in graduation", self.ME) == []
        assert grades.concerns("Must have 65% or 7.5 CGPA in graduation", self.ME)[0] == \
            "Asks for 7.5 CGPA; your resume says 7.0/10"

    def test_throughout_checks_each_exam(self):
        out = grades.concerns("Minimum 60% throughout 10th, 12th and graduation.", self.ME)
        assert "Asks for 60% throughout; your Class 12 marks are 58%" in out
        assert "Asks for 60% throughout; your Class 10 marks aren’t on your resume" in out

    def test_school_bars_leave_the_degree_alone(self):
        out = grades.concerns("60% in class X and XII", {"degree_score": "5.0/10", "class_12": "90%",
                                                         "class_10": "91%"})
        assert out == []

    def test_at_most_three(self):
        text = "60% in 10th. 70% in 12th. 8 CGPA. 3.8/4 GPA. 75% throughout."
        assert len(grades.concerns(text, {})) <= grades.MAX_CONCERNS


# ============================================================= reading more

EXTRACTED = {
    "candidate": {"name": "Aditya Gupta", "email": "aditya@example.com", "phone": "+91 99999 99999",
                  "skills": ["React", "Node.js", "MongoDB"], "degree": "B.Tech Computer Science",
                  "degree_score": "7.0/10", "class_12": "85.4%", "class_10": "CGPA 9.2",
                  "achievements": ["Smart India Hackathon 2024 — national finalist"],
                  "links": ["https://github.com/aditya-g", "linkedin.com/in/aditya-g"]},
    "preferences": {},
}


def _structure(monkeypatch, workspace, reply, text=RESUME_TEXT):
    monkeypatch.setattr(resume, "ask_text", lambda *_a, **_k: json.dumps(reply))
    path = workspace / "cv.txt"
    path.write_text(text, encoding="utf-8")
    profile, why = resume.structure(text, path)
    assert why == ""
    return profile["candidate"]


class TestReadingMore:
    def test_the_prompt_asks_for_them_and_never_to_convert(self):
        prompt = resume.EXTRACT_PROMPT
        for field in ("degree_score", "class_12", "class_10", "achievements", "links"):
            assert f'"{field}"' in prompt
        assert "Never convert" in prompt and "Empty if the resume doesn't state one" in prompt

    def test_what_the_resume_states_comes_through(self, monkeypatch, workspace):
        person = _structure(monkeypatch, workspace, EXTRACTED)
        assert (person["degree_score"], person["class_12"], person["class_10"]) == ("7.0/10", "85.4%", "CGPA 9.2")
        assert person["achievements"] == ["Smart India Hackathon 2024 — national finalist"]
        assert person["links"] == ["https://github.com/aditya-g", "linkedin.com/in/aditya-g"]

    def test_a_made_up_score_is_left_out(self, monkeypatch, workspace):
        reply = json.loads(json.dumps(EXTRACTED))
        reply["candidate"]["degree_score"] = "8.5/10"
        text = RESUME_TEXT.replace(" — CGPA: 7.0/10", "")
        assert _structure(monkeypatch, workspace, reply, text)["degree_score"] == ""

    def test_a_score_the_model_got_wrong_is_taken_from_the_text(self, monkeypatch, workspace):
        reply = json.loads(json.dumps(EXTRACTED))
        reply["candidate"]["degree_score"] = "8.5/10"
        assert _structure(monkeypatch, workspace, reply)["degree_score"] == "CGPA: 7.0/10"

    def test_a_score_the_model_missed_is_read_from_the_text(self, monkeypatch, workspace):
        reply = json.loads(json.dumps(EXTRACTED))
        for field in ("degree_score", "class_12", "class_10"):
            reply["candidate"][field] = ""
        person = _structure(monkeypatch, workspace, reply)
        assert (person["degree_score"], person["class_12"], person["class_10"]) == \
            ("CGPA: 7.0/10", "85.4%", "CGPA 9.2")

    def test_two_different_scores_for_one_field_leave_it_empty(self, monkeypatch, workspace):
        reply = json.loads(json.dumps(EXTRACTED))
        reply["candidate"]["degree_score"] = ""
        text = RESUME_TEXT + "B.Tech semester 5 — SGPA 8.1\n"
        assert _structure(monkeypatch, workspace, reply, text)["degree_score"] == ""

    def test_made_up_and_unsafe_links_are_left_out(self, monkeypatch, workspace):
        reply = json.loads(json.dumps(EXTRACTED))
        reply["candidate"]["links"] = ["github.com/someone-else", "javascript:alert(1)",
                                       "aditya@example.com", "https://github.com/aditya-g",
                                       "github.com/aditya-g/"]
        assert _structure(monkeypatch, workspace, reply)["links"] == ["https://github.com/aditya-g"]

    def test_a_made_up_achievement_is_left_out(self, monkeypatch, workspace):
        reply = json.loads(json.dumps(EXTRACTED))
        reply["candidate"]["achievements"] = ["Smart India Hackathon 2024 — national finalist",
                                              "Winner of Google Code Jam world finals"]
        assert _structure(monkeypatch, workspace, reply)["achievements"] == [
            "Smart India Hackathon 2024 — national finalist"]

    def test_a_sparse_reply_still_has_every_field(self):
        merged = resume._merge({"candidate": {"name": "C"}}, "cv.pdf", 100)
        assert merged["candidate"]["degree_score"] == "" and merged["candidate"]["links"] == []
        assert merged["candidate"]["achievements"] == []

    def test_show_profile_says_them(self):
        profile = resume.load_profile()
        profile["candidate"].update(degree_score="7.0/10", class_12="85%", achievements=["SIH finalist"],
                                    links=["github.com/a"])
        resume.save_profile(profile)
        shown = resume.show_profile()
        assert "CGPA or %: 7.0/10" in shown and "Class 12 marks: 85%" in shown
        assert "Achievements: 1" in shown and "Links: github.com/a" in shown

    def test_the_profile_as_text_carries_them_for_advice(self):
        profile = resume.load_profile()
        profile["candidate"].update(degree_score="7.0/10", achievements=["SIH finalist"])
        text = resume.profile_as_text(profile)
        assert "Degree CGPA or %: 7.0/10" in text and "Achievements: SIH finalist" in text
        assert "9999999999" not in text, "the phone still only says given or not"


# ================================================ correcting by command

class TestCorrectingByCommand:
    def test_a_name_keeps_its_capitals(self):
        reply = fast_route("Set my name to Aditya Kumar Gupta")
        assert reply.startswith("Updated your name: Aditya Kumar Gupta.")
        assert _person()["name"] == "Aditya Kumar Gupta"

    @pytest.mark.parametrize("command,field,value", [
        ("set my phone to +91 98765 43210", "phone", "+91 98765 43210"),
        ("change my mobile number to 9876543210", "phone", "9876543210"),
        ("set my email to adi@example.in", "email", "adi@example.in"),
        ("set my address to Lucknow, India", "location", "Lucknow, India"),
        ("set my degree to B.Tech Computer Science", "degree", "B.Tech Computer Science"),
        ("set my graduation year to 2025", "graduation_year", "2025"),
        ("set my cgpa to 7.8/10", "degree_score", "7.8/10"),
        ("set my cgpa to 7", "degree_score", "7/10"),
        ("set my percentage to 72", "degree_score", "72%"),
        ("set my 12th percentage to 85%", "class_12", "85%"),
        ("set my class xii to 88.2%", "class_12", "88.2%"),
        ("set my 10th marks to 9.4 CGPA", "class_10", "9.4 CGPA"),
        ("meri cgpa 7.2 kar do", "degree_score", "7.2/10"),
    ])
    def test_single_values(self, command, field, value):
        assert fast_route(command).startswith("Updated your ")
        assert _person()[field] == value

    @pytest.mark.parametrize("command,reply", [
        ("set my email to not-an-email", "That isn't an email address."),
        ("set my phone to call me", "That isn't a phone number. Use digits, with +91 if you like."),
        ("set my phone to 12", "That isn't a phone number. Use digits, with +91 if you like."),
        ("set my graduation year to 26", "Say the graduation year as four digits, like 2026."),
        ("set my cgpa to excellent", "I couldn't read that as a score. Say it like 7.8/10, 8.2 CGPA or 85%."),
        ("set my cgpa to 11/10", "I couldn't read that as a score. Say it like 7.8/10, 8.2 CGPA or 85%."),
        ("set my name to aditya@example.com", "That doesn't look like a name. Say it the way the resume should."),
    ])
    def test_what_isnt_valid_is_refused_and_nothing_changes(self, command, reply):
        before = resume.load_profile()
        assert fast_route(command) == reply
        assert resume.load_profile() == before

    def test_adding_skills_splits_on_commas_and_skips_what_is_there(self):
        reply = fast_route("add Docker, AWS, kubernetes to my skills")
        assert reply.startswith("Added to your skills: AWS, kubernetes.")
        assert "(Docker was already there.)" in reply
        assert _person()["skills"] == ["React", "Node.js", "MongoDB", "Docker", "AWS", "kubernetes"]

    def test_a_project_is_one_item_whatever_its_commas(self):
        fast_route("add project LittleAI - a voice assistant in Python, with 67 tools")
        assert _person()["projects"][-1] == "LittleAI - a voice assistant in Python, with 67 tools"

    def test_removing_by_part_of_it(self):
        assert fast_route("remove QuantDesk from my projects").startswith(
            "Removed from your projects: QuantDesk - paper trading dashboard in Next.js.")
        assert len(_person()["projects"]) == 1

    def test_an_ambiguous_remove_removes_nothing(self):
        fast_route("add project Blood donor map")
        before = _person()["projects"]
        reply = fast_route("remove blood from my projects")
        assert "matches 2 of your projects" in reply and reply.endswith("Say more of it.")
        assert _person()["projects"] == before

    def test_removing_what_isnt_there_lists_what_is(self):
        reply = fast_route("remove skill Rust")
        assert reply.startswith("“Rust” isn't in your skills. They are: React; Node.js")

    def test_clearing(self):
        fast_route("set my cgpa to 7.8/10")
        assert fast_route("clear my cgpa").startswith("Cleared your CGPA or %.")
        assert _person()["degree_score"] == ""
        assert fast_route("clear my cgpa") == "Your CGPA or % is already empty."
        assert fast_route("clear my certifications") == "Your certifications list is already empty."

    def test_github_and_linkedin_have_one_slot_each(self):
        fast_route("set my github to github.com/old")
        fast_route("set my linkedin to linkedin.com/in/me")
        assert fast_route("set my github to github.com/new").startswith("Your GitHub link is now github.com/new.")
        assert _person()["links"] == ["linkedin.com/in/me", "github.com/new"]
        assert fast_route("set my github to linkedin.com/in/x") == "That isn't a github.com address."
        fast_route("set my portfolio to aditya.dev")
        assert _person()["links"][-1] == "aditya.dev", "a portfolio is added, not a replacement"

    def test_a_link_must_be_a_web_address(self):
        assert fast_route("add link javascript:alert(1)").startswith("“javascript:alert(1)” isn't a web address.")
        assert _person()["links"] == []

    def test_location_is_still_the_job_search_preference(self):
        assert fast_route("set my location to Pune").startswith("Noted. locations:")
        assert resume.load_profile()["preferences"]["locations"] == ["pune"]
        assert _person()["location"] == PROFILE["candidate"]["location"]

    def test_only_the_field_named_changes(self):
        fast_route("set my phone to 9876543210")
        after = resume.load_profile()
        before = json.loads(json.dumps(PROFILE))
        before["candidate"]["phone"] = "9876543210"
        assert after["candidate"] == before["candidate"]
        assert after["preferences"] == PROFILE["preferences"] and after["set_by_you"] == ["locations"]

    def test_corrections_are_marked_and_the_first_says_a_scan_replaces_them(self):
        first = fast_route("set my phone to 9876543210")
        again = fast_route("set my phone to 9876543211")
        assert first.endswith("A new resume scan replaces this with what that resume says.")
        assert "new resume scan" not in again
        fast_route("add Rust to my skills")
        assert resume.edited(resume.load_profile()) == ["phone", "skills"]

    def test_the_model_can_correct_it_too_without_asking_first(self):
        assert "update_resume_profile" in FUNCTIONS and "check_resume" in FUNCTIONS
        assert {"update_resume_profile", "check_resume"} <= {t["name"] for t in TOOL_SCHEMAS}
        assert "update_resume_profile" not in permissions.NEEDS_CONFIRMATION
        reply = execute_tool("update_resume_profile", {"field": "cgpa", "value": "8.1 CGPA", "change": "set"})
        assert reply.startswith("Updated your CGPA or %: 8.1 CGPA.")
        assert execute_tool("update_resume_profile", {"field": "salary", "value": "10 LPA"}).startswith(
            "I can correct your name")

    def test_the_tools_section_groups_them_under_resume(self):
        out = bridge.Api(assistant=Quiet()).tools()["tools"]
        groups = {t["name"]: t["group"] for t in out}
        assert groups["update_resume_profile"] == groups["check_resume"] == "Resume"


class TestANewScanReplacesCorrections:
    def test_it_replaces_them_says_so_and_keeps_your_preferences(self, monkeypatch, workspace):
        fast_route("set my phone to 9876543210")
        fast_route("set my cgpa to 6.0/10")
        monkeypatch.setattr(resume, "ask_text", lambda *_a, **_k: json.dumps(EXTRACTED))
        path = workspace / "cv.txt"
        path.write_text(RESUME_TEXT, encoding="utf-8")
        reply = resume.scan_resume(str(path))
        after = resume.load_profile()
        assert after["candidate"]["phone"] == "+91 99999 99999"
        assert after["candidate"]["degree_score"] == "7.0/10"
        assert after["edited"] == []
        assert "Your corrections to phone and CGPA or % were replaced with what this resume says." in reply
        assert after["preferences"]["locations"] == ["Bangalore"], "preferences you set are still kept"

    def test_the_windows_scan_says_it_too(self, monkeypatch, workspace):
        fast_route("set my phone to 9876543210")
        monkeypatch.setattr(resume, "ask_text", lambda *_a, **_k: json.dumps(EXTRACTED))
        path = workspace / "cv.txt"
        path.write_text(RESUME_TEXT, encoding="utf-8")
        monkeypatch.setattr(bridge, "_pick_file", lambda: str(path))
        api = bridge.Api(assistant=Quiet())
        out = api.scan_picked(api.choose_resume()["token"])
        end = time.time() + 5
        while time.time() < end and tasks.get(out["task"])["status"] not in tasks.ENDED:
            time.sleep(0.01)
        assert "Your corrections to phone were replaced" in tasks.get(out["task"])["reply"]
        assert api.resume()["edited"] == []


# ================================================ the bar, on your jobs

class TestTheBarOnYourJobs:
    POSTING = "React, Node.js and MongoDB. Eligibility: CGPA of 7.5 and above."

    def test_a_concern_not_a_lower_score(self):
        fast_route("set my cgpa to 7.0/10")
        profile = resume.load_profile()
        base = {"company": "Acme", "title": "Full Stack Developer", "location": "Bangalore, India"}
        with_bar = matching.score_job({**base, "description": self.POSTING}, profile)
        without = matching.score_job({**base, "description": "React, Node.js and MongoDB."}, profile)
        assert "Asks for 7.5 CGPA; your resume says 7.0/10" in with_bar["score_breakdown"]["concerns"]
        assert with_bar["match_score"] == without["match_score"], "said, never scored"
        assert "⚠ Asks for 7.5 CGPA; your resume says 7.0/10" in matching.explain(with_bar)

    def test_a_correction_re_scores_the_jobs_you_have_and_keeps_their_status(self):
        job_id = _job("Acme", "Full Stack Developer", self.POSTING)
        store.set_status(job_id, "APPLIED")
        assert store.get_job(job_id)["score_breakdown"]["concerns"] == [
            "Asks for 7.5 CGPA; your resume doesn't state your degree score"]
        reply = fast_route("set my cgpa to 7.0/10")
        assert "Re-scored 1 stored job." in reply
        job = store.get_job(job_id)
        assert "Asks for 7.5 CGPA; your resume says 7.0/10" in job["score_breakdown"]["concerns"]
        assert job["status"] == "USER_APPROVED"   # set as APPLIED, its pre-Chapter 27 name
        fast_route("set my cgpa to 8.0/10")
        assert not any(c.startswith("Asks for") for c in store.get_job(job_id)["score_breakdown"]["concerns"])
        assert any(a["action"] == "rescore" for a in store.audit_trail())

    def test_the_job_stays_listed(self):
        job_id = _job("Acme", "Full Stack Developer", self.POSTING)
        fast_route("set my cgpa to 5.0/10")
        assert job_id in {j["job_id"] for j in store.top_jobs(50)}

    def test_a_name_or_phone_change_doesnt_re_score(self, monkeypatch):
        _job("Acme", "Full Stack Developer", self.POSTING)
        monkeypatch.setattr(engine, "rescore_stored", lambda *_a: pytest.fail("re-scored"))
        assert "Re-scored" not in fast_route("set my phone to 9876543210")

    def test_nothing_to_re_score_without_a_resume(self):
        resume.PROFILE_PATH.unlink()
        assert engine.rescore_stored() == 0


# ======================================================== resume health

def _check(profile_changes=None, candidate=None) -> dict:
    profile = resume.load_profile()
    profile.update(profile_changes or {})
    profile["candidate"].update(candidate or {})
    resume.save_profile(profile)
    return {c["id"]: c for c in resume_check.run()}


class TestTheResumeCheck:
    def test_nothing_goes_to_the_model(self, no_model):
        out = resume_check.check_resume()
        assert out.startswith("RESUME CHECK — on this computer; nothing is sent anywhere.")
        assert "Resume: aditya-resume.pdf" in out

    def test_contact_details(self):
        assert _check()["contact"]["state"] == "ok"
        c = _check(candidate={"phone": "", "email": "adi at mail"})["contact"]
        assert c["state"] == "warn" and "Missing: phone" in c["detail"] and "doesn't look like an address" in c["detail"]
        assert "set my phone to" in c["fix"]

    def test_links(self):
        assert _check()["links"]["state"] == "warn"
        assert _check(candidate={"links": ["github.com/a"]})["links"]["state"] == "note"
        assert _check(candidate={"links": ["github.com/a", "linkedin.com/in/a"]})["links"]["state"] == "ok"

    def test_degree_and_batch(self):
        assert _check()["degree"]["state"] == "ok"
        c = _check(candidate={"graduation_year": ""})["degree"]
        assert c["state"] == "warn" and c["detail"] == "Missing: graduation year."

    def test_cgpa_missing_and_what_your_jobs_ask(self):
        _job("Acme", "Full Stack Developer", "React. CGPA of 7.5 and above.")
        c = _check()["score"]
        assert c["state"] == "warn" and c["detail"] == "Not on your profile. 1 of your stored jobs state a bar."
        fast_route("set my cgpa to 7.0/10")
        c = _check()["score"]
        assert c["state"] == "ok"
        assert c["detail"] == ("7.0/10. 1 of your stored jobs asks for more than your resume states — "
                               "their cards say which.")

    def test_projects_need_real_numbers_not_years(self):
        c = _check()["projects"]
        assert c["state"] == "warn" and "none of their lines has a number" in c["detail"]
        assert "Never estimate" in c["fix"]
        years = _check(candidate={"projects": ["Site built in 2024", "App made 2025"]})["projects"]
        assert years["state"] == "warn", "a year isn't a result"
        assert _check(candidate={"projects": ["BloodBridge - 3 hospitals", "QuantDesk"]})["projects"]["state"] == "ok"
        assert _check(candidate={"projects": ["One"]})["projects"]["detail"] == "Only one project listed."

    def test_skills_no_project_shows(self):
        c = _check()["evidence"]
        assert c["state"] == "warn"
        assert c["detail"] == "Listed, but no project or job mentions them: MongoDB, Docker, JavaScript."
        shown = _check(candidate={"skills": ["React", "Node.js"], "languages": [], "frameworks": ["Next.js"]})
        assert shown["evidence"] == {**shown["evidence"], "state": "ok",
                                     "detail": "3 of 3 skills appear in a project or job."}
        two = _check(candidate={"skills": ["React", "Node.js", "Go", "Rust"], "languages": [], "frameworks": []})
        assert two["evidence"]["state"] == "ok", "one or two unshown skills aren't worth a flag"

    def test_length(self):
        assert _check()["length"] == {**_check()["length"], "state": "ok", "detail": "About 490 words."}
        assert _check({"raw_text_chars": 600})["length"]["state"] == "warn"
        assert "long for a fresher" in _check({"raw_text_chars": 12000})["length"]["detail"]
        assert _check({"raw_text_chars": 0})["length"]["state"] == "note"

    def test_achievements_are_a_note_not_a_demand(self):
        assert _check()["achievements"]["state"] == "note"
        assert "Nothing to add is fine." in _check()["achievements"]["fix"]
        assert _check(candidate={"achievements": ["SIH finalist"]})["achievements"]["state"] == "ok"

    def test_what_your_jobs_ask_for_comes_from_your_jobs(self):
        assert "gaps" not in _check()
        _job("Acme", "Full Stack Developer", "React, Node.js, Kubernetes and Terraform.")
        assert "terraform" in _check()["gaps"]["detail"].lower()

    def test_corrections_are_mentioned(self):
        assert "edited" not in _check()
        fast_route("set my phone to 9876543210")
        assert _check()["edited"]["detail"] == "You corrected: phone."

    def test_the_count_at_the_end(self):
        out = resume_check.check_resume()
        looks = sum(1 for c in resume_check.run() if c["state"] == "warn")
        assert out.endswith(f"{looks} things to look at.")

    def test_without_a_resume(self):
        resume.PROFILE_PATH.unlink()
        assert resume_check.check_resume().startswith("No resume has been scanned yet")

    @pytest.mark.parametrize("command", ["check my resume", "review my resume", "resume health check",
                                         "is my resume ok?", "mera resume check karo"])
    def test_said_any_way(self, command):
        assert fast_route(command).startswith("RESUME CHECK")

    def test_as_a_task_from_the_resume_section(self):
        api = bridge.Api(assistant=Quiet())
        out = api.resume_action("health")
        end = time.time() + 5
        while time.time() < end and tasks.get(out["task"])["status"] not in tasks.ENDED:
            time.sleep(0.01)
        task = tasks.get(out["task"])
        assert task["text"] == "Check my resume" and task["route"] == "local"
        assert task["reply"].startswith("RESUME CHECK") and task["steps"][0]["name"] == "check_resume"


# ============================================================ the section

SECTION = """() => ({
  calls: window.__calls,
  contact: [...document.querySelectorAll('#cvContact dd')].map(d => d.textContent),
  scores: Object.fromEntries([...document.querySelectorAll('#cvScores dd')].map(d => [d.dataset.field, d.textContent])),
  marked: [...document.querySelectorAll('[data-edited]')].map(b => b.dataset.edited),
  lists: Object.fromEntries([...document.querySelectorAll('#cvLists .cv-group')].map(g =>
    [g.dataset.list, [...g.querySelectorAll('li')].map(li => li.textContent)])),
  anchors: document.querySelectorAll('#cvLists a').length,
  images: document.querySelectorAll('[data-view="resume"] img').length, ran: window.__ran || 0,
  health: !!document.querySelector('#cvActions [data-action="health"]'),
})"""


def _render(check, snapshot, **kw):
    kw.setdefault("route", "resume")
    script = _ui.bridge({"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}) + \
        "window.__resume = %s;" % json.dumps(snapshot)
    result, errors = _ui.open_panel(check, script=script, **kw)
    if result is _ui.NO_BROWSER:
        pytest.skip("no browser to render the panel with")
    assert errors == [], errors
    return result


def _snapshot():
    return json.loads(json.dumps(bridge.Api(assistant=Quiet()).resume(), default=str))


@pytest.fixture(scope="module")
def browser_ok():
    if not _ui.available():
        pytest.skip("Playwright isn't installed")


class TestTheSection:
    def test_the_snapshot_carries_them(self):
        fast_route("set my cgpa to 7.0/10")
        snap = _snapshot()
        assert snap["candidate"]["degree_score"] == "7.0/10" and snap["edited"] == ["degree_score"]
        assert {"class_12", "class_10", "achievements", "links"} <= set(snap["candidate"])

    def test_marks_achievements_and_links_shown_and_corrections_marked(self, browser_ok):
        fast_route("set my cgpa to 7.0/10")
        fast_route("set my github to github.com/aditya-g")
        fast_route("add achievement Smart India Hackathon 2024 finalist")
        seen = _render(lambda page: page.evaluate(SECTION), _snapshot())
        assert seen["contact"] == ["aditya@example.com", "9999999999", "Prayagraj, Uttar Pradesh, India"]
        assert seen["scores"] == {"degree_score": "7.0/10 corrected by you", "class_12": "Not on your resume",
                                  "class_10": "Not on your resume"}
        assert sorted(seen["marked"]) == ["achievements", "degree_score", "links"]
        assert seen["lists"]["achievements"] == ["Smart India Hackathon 2024 finalist"]
        assert seen["lists"]["links"] == ["github.com/aditya-g"]
        assert seen["anchors"] == 0, "links are shown as text, never as something to click"
        assert seen["health"]

    def test_the_rescan_question_names_your_corrections(self, browser_ok):
        fast_route("set my phone to 9876543210")
        fast_route("set my cgpa to 7.0/10")

        async def check(page):
            await page.click("#cvChoose")
            await page.wait_for_timeout(200)
            return await page.evaluate("document.getElementById('cvConfirmQ').textContent")

        question = _render(check, _snapshot())
        assert "including what you corrected (phone, CGPA or %)" in question
        assert question.endswith("Preferences you set yourself are kept.")

    def test_the_health_card_runs_the_check(self, browser_ok):
        async def check(page):
            await page.click('#cvActions [data-action="health"]')
            await page.wait_for_timeout(200)
            return await page.evaluate("window.__calls")

        calls = _render(check, _snapshot())
        assert ["resume_action", "health", None] in calls

    def test_text_is_shown_as_text(self, browser_ok):
        snap = _snapshot()
        snap["candidate"]["achievements"] = [ATTACK]
        snap["candidate"]["links"] = [ATTACK]
        snap["candidate"]["degree_score"] = ATTACK
        seen = _render(lambda page: page.evaluate(SECTION), snap)
        assert seen["images"] == 0 and seen["ran"] == 0
        assert seen["lists"]["achievements"] == [ATTACK]
