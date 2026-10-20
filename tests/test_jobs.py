"""The job hunter.

Two things matter most here and get the most tests: the score has to be
defensible, and JARVIS must never record an application it didn't make.
"""
from __future__ import annotations

import pytest

from jarvis.jobs import apply as job_apply, engine, matching, resume, sources, store


@pytest.fixture
def profile():
    data = {
        "candidate": {
            "name": "Aditya Gupta", "email": "a@example.com", "phone": "+910000000000",
            "location": "Prayagraj, India", "degree": "B.Tech CSE", "graduation_year": "2026",
            "education": ["B.Tech CSE, 2026"],
            "skills": ["React", "Node.js", "MongoDB", "Express", "Python", "TypeScript"],
            "languages": ["Python", "Java"], "frameworks": ["Next.js"],
            "projects": ["BloodBridge AI", "JARVIS", "QuantDesk"],
            "experience": [], "internships": [], "certifications": [],
        },
        "preferences": {"roles": ["full stack developer"],
                        "locations": ["Bangalore", "Remote"],
                        "work_modes": ["remote", "hybrid"],
                        "countries": ["india"]},
    }
    resume.save_profile(data)
    return data


def job(company, title, location="", description="", **extra):
    return {"job_id": store.job_id_for(company, title), "company": company,
            "title": title, "location": location, "description": description,
            "platform": "test", "url": f"https://example.com/{company}", **extra}


class TestScoring:
    def test_a_close_fit_beats_a_poor_one(self, profile):
        good = job("A", "Full Stack Developer", "Remote",
                   "React, Node.js, TypeScript. Remote. 1 year experience.")
        poor = job("B", "Data Entry Operator", "Kanpur", "Excel and typing speed.")
        assert matching.score_job(good, profile)["match_score"] > \
               matching.score_job(poor, profile)["match_score"]

    def test_a_senior_role_scores_low_for_a_fresher(self, profile):
        senior = job("C", "Senior Staff Engineer", "Pune",
                     "8+ years experience. React, Node.js, MongoDB.")
        scored = matching.score_job(senior, profile)
        assert scored["match_score"] < 50
        assert scored["score_breakdown"]["dimensions"]["experience"] == 0

    def test_matched_and_missing_skills_are_separated(self, profile):
        scored = matching.score_job(
            job("D", "Developer", "Remote", "React, Node.js, AWS, Kubernetes needed."), profile)
        assert "react" in scored["skills_matched"]
        assert "aws" in scored["skills_missing"]
        assert "react" not in scored["skills_missing"]

    def test_the_breakdown_adds_up_to_the_score(self, profile):
        scored = matching.score_job(
            job("E", "Full Stack Developer", "Remote", "React and Node.js."), profile)
        assert "capped_at" not in scored["score_breakdown"]
        assert scored["score_breakdown"]["weighted"] == scored["match_score"]
        dims = scored["score_breakdown"]["dimensions"]
        recomputed = round(sum(matching.WEIGHTS[k] * dims[k] / 100 for k in matching.WEIGHTS))
        assert recomputed == scored["match_score"]

    def test_a_capped_job_says_so_in_its_breakdown(self, profile):
        scored = matching.score_job(
            job("H", "Senior Engineer", "Remote",
                "10+ years experience. React, Node.js, MongoDB, TypeScript."), profile)
        assert scored["score_breakdown"]["capped_at"] == matching.REACH_CAP
        assert "capped" in scored["why"]
        assert scored["score_breakdown"]["cap_reason"]

    def test_the_score_stays_within_range(self, profile):
        for description in ["", "React " * 200, "Nothing relevant at all"]:
            scored = matching.score_job(job("F", "Developer", "X", description), profile)
            assert 0 <= scored["match_score"] <= 100

    def test_a_skill_is_not_matched_inside_another_word(self, profile):
        # "go" must not match "good", "algorithms" must not make "r" a hit
        found = matching.skills_in("We want a good engineer with strong algorithms")
        assert "go" not in found

    def test_ranking_puts_the_best_first(self, profile):
        jobs = [job("Z", "Data Entry", "X", "Excel"),
                job("Y", "Full Stack Developer", "Remote", "React Node.js TypeScript")]
        assert matching.rank(jobs, profile)[0]["company"] == "Y"

    def test_explain_names_every_component(self, profile):
        text = matching.explain(matching.score_job(
            job("G", "Developer", "Remote", "React"), profile))
        for part in matching.WEIGHTS:
            assert part.replace("_", " ").title() in text
        assert "MATCH ANALYSIS" in text
        assert "your call" in text  # never claims a job is suitable outright


class TestWhereYouCanActuallyWork:
    """A remote job open only to the USA is not a match for someone in
    Prayagraj, however well the stack lines up."""

    def test_a_job_closed_to_your_country_is_capped(self, profile):
        scored = matching.score_job(
            job("KoboToolbox", "Frontend Web Application Developer",
                "USA, Canada, Argentina, Mexico, Peru",
                "Remote. React, TypeScript, Node.js."), profile)
        assert scored["match_score"] <= matching.ELIGIBILITY_CAP
        assert "can't work" in scored["why"]

    def test_a_worldwide_job_is_not_capped(self, profile):
        scored = matching.score_job(
            job("GlobalCo", "React Developer", "Worldwide",
                "Remote worldwide. React, TypeScript, Node.js. 1 year."), profile)
        assert scored["match_score"] > 70

    def test_a_job_in_your_country_is_not_capped(self, profile):
        scored = matching.score_job(
            job("Indian Startup", "Full Stack Developer", "Bangalore, India",
                "React, Node.js, MongoDB, Express. 0-1 years."), profile)
        assert scored["match_score"] > 80

    def test_with_no_country_set_the_address_decides(self, profile):
        profile["preferences"]["countries"] = []
        scored = matching.score_job(
            job("USOnly", "Developer", "USA", "React and Node.js."), profile)
        assert scored["match_score"] <= matching.ELIGIBILITY_CAP

    def test_a_candidate_in_that_country_is_eligible(self):
        us = {"candidate": {"location": "Austin, USA", "skills": ["React"],
                            "degree": "BS", "projects": [], "experience": [],
                            "internships": []},
              "preferences": {"roles": [], "locations": [], "work_modes": [],
                              "countries": []}}
        scored = matching.score_job(
            job("K", "Frontend Developer", "USA, Canada", "Remote. React."), us)
        assert "capped_at" not in scored["score_breakdown"]

    def test_a_job_naming_no_country_is_left_alone(self, profile):
        eligible, _ = matching.can_work_there(
            job("X", "Developer", "", "React and Node.js."), ["india"])
        assert eligible is True


class TestOffFieldJobs:
    """A search for "software developer" brings back sales and writing roles;
    they should not sit near the top just because nothing contradicted them."""

    def test_a_job_naming_no_technology_is_capped(self, profile):
        scored = matching.score_job(
            job("IAPWE", "Freelance Writer", "Worldwide",
                "Write articles. Paid per piece."), profile)
        assert scored["match_score"] <= matching.OFF_FIELD_CAP

    def test_a_sales_role_ranks_below_a_developer_role(self, profile):
        ranked = matching.rank([
            job("Sales Co", "Inside Sales Contractor", "Worldwide", "Cold calling."),
            job("Dev Co", "Full Stack Developer", "Bangalore, India",
                "React, Node.js, MongoDB."),
        ], profile)
        assert ranked[0]["company"] == "Dev Co"


class TestPreferences:
    def test_countries_can_be_set(self, profile):
        assert "countries" in resume.set_preference("countries", "india, singapore")
        assert resume.load_profile()["preferences"]["countries"] == ["india", "singapore"]

    def test_a_singular_field_name_is_accepted(self, profile):
        resume.set_preference("country", "india")
        assert resume.load_profile()["preferences"]["countries"] == ["india"]

    def test_an_unknown_field_is_refused(self, profile):
        assert "I can set" in resume.set_preference("favourite colour", "blue")


class TestDeduplication:
    def test_the_same_role_at_one_company_collapses(self):
        assert store.job_id_for("Google India Pvt Ltd", "Software Engineer") == \
               store.job_id_for("Google", "software engineer")

    def test_different_companies_stay_separate(self):
        assert store.job_id_for("Google", "SWE") != store.job_id_for("Infosys", "SWE")

    def test_storing_a_duplicate_does_not_add_a_second_row(self):
        first = job("Dup Co", "Engineer")
        assert store.upsert_job(first) is True
        assert store.upsert_job(dict(first, match_score=99)) is False
        assert len([j for j in store.top_jobs(50) if j["company"] == "Dup Co"]) == 1

    def test_a_rescored_duplicate_keeps_its_status(self):
        entry = job("Keep Co", "Engineer")
        store.upsert_job(entry)
        store.set_status(entry["job_id"], "SHORTLISTED")      # the old name, still accepted
        store.upsert_job(dict(entry, match_score=50))
        assert store.get_job(entry["job_id"])["status"] == "SAVED"   # SHORTLISTED since Chapter 27


class TestApplicationsAreNeverInvented:
    def test_nothing_is_applied_until_the_user_says_so(self, profile):
        entry = job("Honest Co", "Developer")
        store.upsert_job(entry)
        assert store.already_applied(entry["job_id"]) is False
        assert store.counts()["applied"] == 0

    def test_marking_applied_records_it(self, profile):
        entry = job("Real Co", "Developer")
        store.upsert_job(entry)
        assert "Recorded" in job_apply.mark_applied("real")
        assert store.already_applied(entry["job_id"]) is True

    def test_the_same_job_is_not_applied_to_twice(self, profile):
        entry = job("Once Co", "Developer")
        store.upsert_job(entry)
        job_apply.mark_applied("once")
        assert "already recorded" in job_apply.mark_applied("once").lower()

    def test_preparing_a_job_already_applied_to_is_refused(self, profile):
        entry = job("Twice Co", "Developer")
        store.upsert_job(entry)
        job_apply.mark_applied("twice")
        assert "already applied" in job_apply.prepare_application("twice").lower()

    def test_an_unknown_reference_is_reported_not_guessed(self, profile):
        assert "couldn't find" in job_apply.mark_applied("no such company").lower()

    def test_an_invalid_status_is_refused(self, profile):
        store.upsert_job(job("Status Co", "Developer"))
        assert "must be one of" in job_apply.mark_status("status", "pending")

    def test_a_valid_status_moves_the_job(self, profile):
        entry = job("Move Co", "Developer")
        store.upsert_job(entry)
        job_apply.mark_status("move", "interview")
        assert store.get_job(entry["job_id"])["status"] == "INTERVIEW"


class TestGuards:
    def test_searching_without_a_resume_says_so(self):
        resume.save_profile(resume.load_profile().__class__())  # empty dict
        result = engine.find_jobs()
        assert "resume" in result.lower()

    def test_boards_without_an_api_get_a_search_link_not_a_scrape(self):
        for board in ("linkedin", "naukri", "indeed", "internshala"):
            url = sources.manual_search_url(board, "python developer", "Bangalore")
            assert url and url.startswith("https://")

    def test_an_unknown_board_returns_nothing_rather_than_a_guess(self):
        assert sources.manual_search_url("monster", "python") is None


class TestResumeParsing:
    def test_json_is_recovered_from_a_fenced_reply(self):
        parsed = resume._parse_json('```json\n{"candidate": {"name": "A"}}\n```')
        assert parsed["candidate"]["name"] == "A"

    def test_json_is_recovered_when_the_model_adds_a_sentence(self):
        parsed = resume._parse_json('Here you go:\n{"candidate": {"name": "B"}}\nHope that helps')
        assert parsed["candidate"]["name"] == "B"

    def test_unparseable_output_returns_nothing_rather_than_half_a_profile(self):
        assert resume._parse_json("I could not read that resume") is None

    def test_the_profile_shape_survives_a_sparse_reply(self):
        merged = resume._merge({"candidate": {"name": "C"}}, "cv.pdf", 100)
        assert merged["candidate"]["skills"] == []
        assert merged["preferences"]["roles"] == []
        assert merged["source_file"] == "cv.pdf"

    def test_a_missing_file_is_reported_plainly(self):
        assert "couldn't find" in resume.scan_resume("nowhere-at-all.pdf")


class TestInstructionsAreTypeable:
    """A message that tells someone what to say has to be something they can
    actually say. "Say: scan my resume <one of those>" got typed back
    verbatim, placeholder and all — which was the right response to what it
    asked for.
    """

    def test_no_message_asks_the_user_to_type_a_placeholder(self, monkeypatch):
        from jarvis.jobs import resume as resume_module
        monkeypatch.setattr(resume_module, "list_candidate_resumes",
                            lambda limit=6: ["Aditya-Gupta-Resume.pdf", "cv-2026.pdf"])
        reply = resume_module.scan_resume("nonexistent-file.pdf")
        assert "<" not in reply and ">" not in reply

    def test_every_suggestion_is_a_complete_command(self, monkeypatch):
        from jarvis.jobs import resume as resume_module
        names = ["Aditya-Gupta-Resume.pdf", "aditya-resume.pdf.pdf"]
        monkeypatch.setattr(resume_module, "list_candidate_resumes", lambda limit=6: names)
        reply = resume_module.scan_resume("wrong-name.pdf")
        for name in names:
            assert f"scan my resume {name}" in reply

    def test_the_hint_names_a_real_file_when_there_is_one(self, monkeypatch):
        from jarvis.jobs import resume as resume_module
        monkeypatch.setattr(resume_module, "list_candidate_resumes",
                            lambda limit=3: ["Aditya-Gupta-Resume.pdf"])
        assert resume_module.scan_hint() == "Say: scan my resume Aditya-Gupta-Resume.pdf"

    def test_the_hint_does_not_invent_a_file_when_there_is_none(self, monkeypatch):
        """Telling someone to say "scan my resume resume.pdf" when no such
        file exists sends them to type a name that will fail."""
        from jarvis.jobs import resume as resume_module
        monkeypatch.setattr(resume_module, "list_candidate_resumes", lambda limit=3: [])
        hint = resume_module.scan_hint()
        assert "resume.pdf" not in hint
        assert "Downloads" in hint

    def test_the_job_search_complaint_names_real_files_too(self, monkeypatch):
        from jarvis.jobs import engine, resume as resume_module
        monkeypatch.setattr(resume_module, "list_candidate_resumes",
                            lambda limit=3: ["Aditya-Gupta-Resume.pdf"])
        reply = engine.find_jobs()
        assert "scan my resume Aditya-Gupta-Resume.pdf" in reply
