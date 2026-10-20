"""Nine dimensions, each defensible on its own, combined by weight.

Two things get the most tests here. The score must never claim more than
the arithmetic supports — a total is a percentage of a perfect fit, not an
opinion — and a job that cannot realistically be got must be capped however
well the keywords line up, so the top of the list stays worth applying to.
"""
from __future__ import annotations

import pytest

from jarvis.jobs import matching, resume, store


@pytest.fixture
def profile():
    return {
        "candidate": {
            "name": "Aditya Gupta", "location": "Prayagraj, India",
            "degree": "B.Tech CSE", "graduation_year": "2026",
            "education": ["B.Tech CSE, 2026"],
            "skills": ["React", "Node.js", "MongoDB", "Express", "Python", "TypeScript"],
            "languages": ["Python"], "frameworks": ["Next.js"],
            "projects": ["BloodBridge AI", "JARVIS", "QuantDesk"],
            "experience": [], "internships": [], "certifications": [],
        },
        "preferences": {"roles": ["full stack developer"],
                        "locations": ["Bangalore", "Remote"],
                        "work_modes": ["remote"],
                        "countries": ["india"], "employment_types": []},
    }


def job(company, title, location="", description="", **extra):
    return {"job_id": store.job_id_for(company, title), "company": company,
            "title": title, "location": location, "description": description,
            "platform": "test", "url": f"https://example.com/{company}", **extra}


# --------------------------------------------------------------- weights

def test_the_weights_sum_to_one_hundred():
    """The total is a percentage of a perfect fit. If the weights don't sum
    to 100, a flawless job on every dimension would not score 100."""
    assert sum(matching.WEIGHTS.values()) == 100


def test_every_dimension_the_spec_asks_for_is_present():
    for name in ("skills", "role", "experience", "education", "location",
                "work_mode", "employment_type", "seniority", "projects"):
        assert name in matching.WEIGHTS


# ---------------------------------------------------------------- shape

class TestTheBreakdownItself:
    def test_every_dimension_is_scored_out_of_a_hundred(self, profile):
        scored = matching.score_job(
            job("A", "Full Stack Developer", "Remote", "React, Node.js."), profile)
        dims = scored["score_breakdown"]["dimensions"]
        assert set(dims) == set(matching.WEIGHTS)
        for value in dims.values():
            assert 0 <= value <= 100

    def test_every_dimension_carries_a_reason(self, profile):
        scored = matching.score_job(
            job("A", "Full Stack Developer", "Remote", "React, Node.js."), profile)
        notes = scored["score_breakdown"]["notes"]
        for name in matching.WEIGHTS:
            assert notes.get(name), f"{name} gave no reason"

    def test_the_weighted_total_matches_the_arithmetic(self, profile):
        scored = matching.score_job(
            job("A", "Full Stack Developer", "Remote", "React, Node.js."), profile)
        dims = scored["score_breakdown"]["dimensions"]
        expected = round(sum(matching.WEIGHTS[k] * dims[k] / 100 for k in matching.WEIGHTS))
        assert scored["score_breakdown"]["weighted"] == expected

    def test_the_score_stays_within_range(self, profile):
        for description in ["", "React " * 200, "Nothing relevant at all"]:
            scored = matching.score_job(job("F", "Developer", "X", description), profile)
            assert 0 <= scored["match_score"] <= 100

    def test_explain_never_calls_a_job_suitable(self, profile):
        """The spec's own line: never claim a job is suitable with
        certainty. Whatever the score, the sentence hands the decision
        back."""
        for title, desc in [("Full Stack Developer", "React, Node.js, 0-1 years."),
                            ("Senior Architect", "10 years required.")]:
            text = matching.explain(matching.score_job(job("X", title, "Remote", desc), profile))
            assert "your call" in text
            for word in ("suitable", "perfect fit", "you should apply", "great match"):
                assert word not in text.lower()


# ----------------------------------------------------------------- skills

class TestSkillScoring:
    def test_a_full_match_scores_a_hundred(self, profile):
        scored = matching.score_job(
            job("A", "Developer", "Remote", "React and Node.js required."), profile)
        assert scored["score_breakdown"]["dimensions"]["skills"] == 100

    def test_a_related_skill_counts_as_partial_not_full_or_zero(self, profile):
        """Next.js when they know React (but not Next.js itself) is worth
        something — not nothing, and not the same as actually knowing it."""
        profile["candidate"]["frameworks"] = []       # only React, no Next.js
        scored = matching.score_job(
            job("A", "Frontend Developer", "Remote", "Next.js required."), profile)
        assert "next.js" in scored["skills_partial"]
        assert "next.js" not in scored["skills_matched"]
        assert 0 < scored["score_breakdown"]["dimensions"]["skills"] < 100

    def test_the_bridge_names_the_actual_skill_they_have(self, profile):
        """"you have something close" is not an answer anyone can act on."""
        profile["candidate"]["frameworks"] = []
        scored = matching.score_job(
            job("A", "Frontend Developer", "Remote", "Next.js required."), profile)
        bridges = scored["score_breakdown"]["skill_bridges"]
        assert bridges.get("next.js") == ["react"]

    def test_a_posting_naming_no_technology_scores_low_but_not_zero(self, profile):
        scored = matching.score_job(
            job("A", "Writer", "Remote", "Write articles."), profile)
        assert scored["score_breakdown"]["dimensions"]["skills"] == 15

    def test_matched_partial_and_missing_are_three_distinct_sets(self, profile):
        profile["candidate"]["frameworks"] = []
        scored = matching.score_job(
            job("A", "Developer", "Remote",
               "React, Next.js, AWS, Kubernetes needed."), profile)
        assert "react" in scored["skills_matched"]
        assert "next.js" in scored["skills_partial"]
        assert "aws" in scored["skills_missing"]
        assert not (set(scored["skills_matched"]) & set(scored["skills_partial"]))
        assert not (set(scored["skills_matched"]) & set(scored["skills_missing"]))

    def test_a_skill_is_not_matched_inside_another_word(self):
        found = matching.skills_in("We want a good engineer with strong algorithms")
        assert "go" not in found


# --------------------------------------------------------------- seniority

class TestSeniorityScoring:
    def test_a_senior_title_scores_low_for_a_fresher(self, profile):
        scored = matching.score_job(
            job("A", "Senior Staff Engineer", "Remote", "React, Node.js."), profile)
        assert scored["score_breakdown"]["dimensions"]["seniority"] <= 10

    def test_an_intern_title_scores_high_for_a_fresher(self, profile):
        scored = matching.score_job(
            job("A", "Software Engineering Intern", "Remote", "React."), profile)
        assert scored["score_breakdown"]["dimensions"]["seniority"] == 100

    def test_chapter_24_s_seniority_field_is_trusted_over_a_guess_from_the_title(self, profile):
        """A posting whose title says nothing can still carry a seniority
        field from Chapter 24's normaliser, and that should be read first."""
        scored = matching.score_job(
            job("A", "Engineer II", "Remote", "React.", seniority="senior"), profile)
        assert scored["score_breakdown"]["dimensions"]["seniority"] <= 10

    def test_an_unlabelled_title_does_not_score_as_confidently_as_a_labelled_one(self, profile):
        plain = matching.score_job(job("A", "Software Engineer", "Remote", "React."), profile)
        junior = matching.score_job(job("B", "Junior Developer", "Remote", "React."), profile)
        assert plain["score_breakdown"]["dimensions"]["seniority"] < \
               junior["score_breakdown"]["dimensions"]["seniority"]


# -------------------------------------------------------------- experience

class TestExperienceScoring:
    def test_no_bar_stated_is_not_penalised(self, profile):
        scored = matching.score_job(job("A", "Developer", "Remote", "React."), profile)
        assert scored["score_breakdown"]["dimensions"]["experience"] >= 60

    def test_a_high_bar_scores_zero_for_a_fresher(self, profile):
        scored = matching.score_job(
            job("A", "Developer", "Remote", "8+ years experience required."), profile)
        assert scored["score_breakdown"]["dimensions"]["experience"] == 0

    def test_a_low_bar_scores_high(self, profile):
        scored = matching.score_job(
            job("A", "Developer", "Remote", "0-1 years experience."), profile)
        assert scored["score_breakdown"]["dimensions"]["experience"] == 100


# ---------------------------------------------------------------- location

class TestLocationScoring:
    def test_a_job_closed_to_your_country_scores_zero(self, profile):
        scored = matching.score_job(
            job("A", "Developer", "USA, Canada", "React."), profile)
        assert scored["score_breakdown"]["dimensions"]["location"] == 0

    def test_a_worldwide_job_scores_high(self, profile):
        scored = matching.score_job(
            job("A", "Developer", "Worldwide", "Remote worldwide. React."), profile)
        assert scored["score_breakdown"]["dimensions"]["location"] >= 90

    def test_a_listed_city_scores_perfectly(self, profile):
        scored = matching.score_job(
            job("A", "Developer", "Bangalore, India", "React.", city="Bangalore",
               country="India"), profile)
        assert scored["score_breakdown"]["dimensions"]["location"] == 100

    def test_an_eligible_but_unlisted_place_scores_moderately(self, profile):
        scored = matching.score_job(
            job("A", "Developer", "Hyderabad, India", "React. Onsite.",
               city="Hyderabad", country="India"), profile)
        assert 70 <= scored["score_breakdown"]["dimensions"]["location"] < 100


# ------------------------------------------------------------- work mode

class TestWorkModeScoring:
    def test_the_preferred_mode_scores_perfectly(self, profile):
        scored = matching.score_job(
            job("A", "Developer", "Remote", "React.", work_mode="remote"), profile)
        assert scored["score_breakdown"]["dimensions"]["work_mode"] == 100

    def test_an_unwanted_mode_scores_low(self, profile):
        scored = matching.score_job(
            job("A", "Developer", "Office", "React.", work_mode="onsite"), profile)
        assert scored["score_breakdown"]["dimensions"]["work_mode"] < 50

    def test_no_mode_stated_is_not_penalised_to_zero(self, profile):
        scored = matching.score_job(job("A", "Developer", "", "React."), profile)
        assert scored["score_breakdown"]["dimensions"]["work_mode"] >= 50


# --------------------------------------------------------- employment type

class TestEmploymentTypeScoring:
    def test_a_stated_preference_that_matches_scores_perfectly(self, profile):
        profile["preferences"]["employment_types"] = ["internship"]
        scored = matching.score_job(
            job("A", "Developer", "Remote", "React.", employment_type="internship"), profile)
        assert scored["score_breakdown"]["dimensions"]["employment_type"] == 100

    def test_a_stated_preference_that_conflicts_scores_low(self, profile):
        profile["preferences"]["employment_types"] = ["internship"]
        scored = matching.score_job(
            job("A", "Developer", "Remote", "React.", employment_type="contract"), profile)
        assert scored["score_breakdown"]["dimensions"]["employment_type"] < 50

    def test_with_nothing_stated_a_fresher_default_is_assumed_and_said_so(self, profile):
        scored = matching.score_job(
            job("A", "Developer", "Remote", "React.", employment_type="internship"), profile)
        assert scored["score_breakdown"]["notes"]["employment_type"] == "internship"
        assert scored["score_breakdown"]["dimensions"]["employment_type"] >= 80


# ---------------------------------------------------------------- capping

class TestCapping:
    def test_a_capped_job_says_so_and_names_why(self, profile):
        scored = matching.score_job(
            job("A", "Senior Engineer", "Remote", "10+ years. React, Node.js."), profile)
        assert scored["score_breakdown"]["capped_at"] == matching.REACH_CAP
        assert scored["score_breakdown"]["cap_reason"]
        assert "capped" in scored["why"]

    def test_a_job_closed_to_your_country_is_capped_lower_than_the_reach_cap(self, profile):
        scored = matching.score_job(
            job("A", "Developer", "USA", "React."), profile)
        assert scored["match_score"] <= matching.ELIGIBILITY_CAP

    def test_an_off_field_job_is_capped(self, profile):
        scored = matching.score_job(
            job("A", "Freelance Writer", "Worldwide", "Write articles."), profile)
        assert scored["match_score"] <= matching.OFF_FIELD_CAP

    def test_a_good_fit_is_never_capped(self, profile):
        scored = matching.score_job(
            job("A", "Full Stack Developer", "Bangalore, India",
               "React, Node.js, MongoDB. 0-1 years.", city="Bangalore",
               country="India", work_mode="remote", employment_type="full-time",
               seniority="junior"), profile)
        assert "capped_at" not in scored["score_breakdown"]


# --------------------------------------------------------------- concerns

class TestConcerns:
    def test_a_capped_job_surfaces_the_cap_as_a_concern(self, profile):
        scored = matching.score_job(
            job("A", "Senior Engineer", "Remote", "10+ years. React."), profile)
        concerns = scored["score_breakdown"]["concerns"]
        assert any("senior" in c.lower() or "experience" in c.lower() for c in concerns)

    def test_a_stale_posting_is_a_concern(self, profile):
        scored = matching.score_job(
            job("A", "Full Stack Developer", "Remote", "React, Node.js.",
               posted_at="2026-01-01"), profile)
        concerns = scored["score_breakdown"]["concerns"]
        assert any("posted" in c.lower() for c in concerns)

    def test_a_fresh_well_fitting_job_has_no_concerns(self, profile):
        scored = matching.score_job(
            job("A", "Full Stack Developer", "Bangalore, India",
               "React, Node.js. 0-1 years.", city="Bangalore", country="India",
               work_mode="remote", employment_type="full-time", seniority="junior",
               posted_at="2026-09-25"), profile)
        assert scored["score_breakdown"]["concerns"] == []

    def test_concerns_are_never_duplicated(self, profile):
        scored = matching.score_job(
            job("A", "Senior Engineer", "USA", "10+ years."), profile)
        concerns = scored["score_breakdown"]["concerns"]
        assert len(concerns) == len(set(concerns))


# -------------------------------------------------------------- ranking

class TestRanking:
    def test_a_close_fit_beats_a_poor_one(self, profile):
        good = job("A", "Full Stack Developer", "Remote",
                   "React, Node.js, TypeScript. Remote. 1 year experience.")
        poor = job("B", "Data Entry Operator", "Kanpur", "Excel and typing speed.")
        assert matching.score_job(good, profile)["match_score"] > \
               matching.score_job(poor, profile)["match_score"]

    def test_ranking_puts_the_best_first(self, profile):
        jobs = [job("Z", "Data Entry", "X", "Excel"),
                job("Y", "Full Stack Developer", "Remote", "React Node.js TypeScript")]
        assert matching.rank(jobs, profile)[0]["company"] == "Y"


# ----------------------------------------------------------- preferences

class TestEmploymentTypePreference:
    def test_it_can_be_set_by_its_own_name(self):
        resume.save_profile(resume.load_profile())
        reply = resume.set_preference("employment_types", "internship, full-time")
        assert "employment_types" in reply
        assert resume.load_profile()["preferences"]["employment_types"] == \
               ["internship", "full-time"]

    def test_a_singular_or_aliased_field_name_is_accepted(self):
        resume.set_preference("employment_type", "internship")
        assert resume.load_profile()["preferences"]["employment_types"] == ["internship"]
        resume.set_preference("job_type", "contract")
        assert resume.load_profile()["preferences"]["employment_types"] == ["contract"]

    @pytest.mark.parametrize("said", [
        "set employment type to internship, full-time",
        "set job types to internship",
    ])
    def test_it_is_settable_by_voice(self, said):
        from jarvis.routing import router
        reply = router.fast_route(said)
        assert reply is not None and "employment_types" in reply


# -------------------------------------------------------------- storage

class TestSkillsPartialRoundTrips:
    def test_a_scored_job_s_partial_skills_survive_being_stored(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DB_PATH", tmp_path / "partial.db")
        job_row = {"job_id": "p1", "company": "Acme", "title": "Engineer",
                  "match_score": 70, "skills_matched": ["react"],
                  "skills_partial": ["next.js"], "skills_missing": ["docker"]}
        store.upsert_job(job_row)
        stored = store.get_job("p1")
        assert stored["skills_partial"] == ["next.js"]
        assert stored["skills_matched"] == ["react"]


# ------------------------------------------------------- previously untested paths

class TestPathsNothingWasCoveringBefore:
    """open_board raised NameError after a rename and nothing caught it,
    because nothing called it. why_this_job is the only caller of
    matching.explain() outside a direct test, so it needs the same
    guarantee — a real function, not a placeholder someone forgot to wire.
    """

    def test_open_board_does_not_raise(self, profile, tmp_path, monkeypatch):
        from jarvis.jobs import engine

        resume.save_profile(profile)
        reply = engine.open_board("linkedin", "", "")
        assert "linkedin" in reply.lower()
        assert "NameError" not in reply and "Traceback" not in reply

    def test_open_board_uses_the_first_target_role(self, profile):
        from jarvis.jobs import engine

        resume.save_profile(profile)
        reply = engine.open_board("naukri", "", "")
        assert "full stack developer" in reply

    def test_why_this_job_explains_a_stored_job(self, profile, tmp_path, monkeypatch):
        from jarvis.jobs import engine

        monkeypatch.setattr(store, "DB_PATH", tmp_path / "why.db")
        resume.save_profile(profile)
        scored = matching.score_job(
            job("Acme", "Full Stack Developer", "Remote", "React, Node.js."), profile)
        store.upsert_job(scored)

        reply = engine.why_this_job("1")
        assert "MATCH ANALYSIS" in reply
        assert "your call" in reply


class TestTheWhyLineIsTrue:
    """UI-6 showed a 29 whose explanation said "capped at 45". A cap is only
    mentioned when it actually brought the score down."""

    def test_a_score_already_below_the_cap_doesnt_claim_one(self, profile):
        scored = matching.score_job(job("Freshworks", "Senior Backend Engineer", "Bangalore",
                                        "Java, Spring Boot, Kafka. 5+ years experience."), profile)
        assert scored["match_score"] < 45
        assert "capped at" not in scored["why"]
        assert "capped_at" not in scored["score_breakdown"]
        assert scored["score_breakdown"]["concerns"], "the reason is still worth knowing"

    def test_a_score_the_cap_brought_down_says_so(self, profile):
        scored = matching.score_job(job("Acme", "Senior Full Stack Developer", "Remote",
                                        "React, Node.js, MongoDB, TypeScript, Express. 5+ years experience."),
                                    profile)
        assert scored["score_breakdown"]["weighted"] > scored["match_score"] == 45
        assert "capped at 45" in scored["why"]
