"""Stored preferences and contacts, which survive between sessions."""
from __future__ import annotations

from jarvis.store import memory


class TestPreferences:
    def test_a_fact_can_be_stored_and_read_back(self):
        memory.remember("project folder", "D:/dev")
        assert "D:/dev" in memory.recall("project folder")

    def test_forgetting_removes_only_that_fact(self):
        memory.remember("editor", "neovim")
        memory.remember("browser", "chrome")
        assert "Forgotten" in memory.forget("editor")
        assert "Nothing stored" in memory.recall("editor")
        assert "chrome" in memory.recall("browser")

    def test_forgetting_something_never_stored_says_so(self):
        assert "had nothing" in memory.forget("never set")

    def test_recall_with_nothing_stored_is_honest(self):
        assert "haven't stored" in memory.recall()


class TestContacts:
    def test_a_contact_round_trips(self):
        memory.add_contact("Rahul", "+919876543210")
        assert memory.find_contact("rahul") == "+919876543210"

    def test_lookup_ignores_case_and_matches_part_of_a_name(self):
        memory.add_contact("rahul sharma", "+919876543210")
        assert memory.find_contact("RAHUL") == "+919876543210"
        assert memory.find_contact("sharma") == "+919876543210"

    def test_an_unknown_name_returns_nothing_rather_than_a_guess(self):
        memory.add_contact("rahul", "+919876543210")
        assert memory.find_contact("zzz nobody") is None


class TestHistory:
    def test_turns_are_kept_and_the_log_stays_bounded(self):
        for i in range(250):
            memory.log_turn(f"command {i}", f"reply {i}")
        history = memory._load(memory.HISTORY)
        assert len(history) == 200
        assert history[-1]["user"] == "command 249"
