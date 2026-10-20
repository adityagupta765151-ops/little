"""Running the tests must never touch your own data.

Until UI-7 the tests used the project's own memory folder — the one that
holds your resume profile, your jobs, your contacts and what LITTLE
remembers — and emptied it before every test. Running `python -m pytest`
on your computer deleted all of it. Now tests/conftest.py points the memory
folder and the log at temporary places before anything is imported, and
stops the run if they aren't.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from jarvis.app import config
from jarvis.jobs import resume, store
from jarvis.store import memory


def _outside_the_project(path: Path) -> bool:
    return not Path(path).resolve().is_relative_to(config.BASE_DIR.resolve())


class TestTheTestsUseTemporaryFolders:
    def test_the_memory_folder_is_not_the_projects(self):
        assert _outside_the_project(config.MEMORY_DIR)
        assert config.MEMORY_DIR != config.BASE_DIR / "memory"

    def test_every_file_the_tests_empty_is_inside_it(self):
        """These are the files conftest deletes before every test."""
        for path in (resume.PROFILE_PATH, store.DB_PATH, memory.PREFERENCES,
                     memory.CONTACTS, memory.HISTORY, memory.PROFILE):
            assert Path(path).resolve().is_relative_to(config.MEMORY_DIR), path
            assert _outside_the_project(path), path

    def test_your_folders_are_not_searched_for_a_resume(self):
        """A resume in your Downloads made two resume tests read it — and
        fail — on your computer."""
        assert resume.SEARCH_FOLDERS == ()
        assert resume.list_candidate_resumes() == []

    def test_the_log_is_not_yours_either(self):
        """Test runs used to write their made-up failures into your
        jarvis.log, where they read like real ones."""
        assert _outside_the_project(config.LOG_FILE)


class TestTheSetting:
    def _paths(self, **env):
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("JARVIS_MEMORY_DIR", "JARVIS_LOG_FILE")}
        out = subprocess.run(
            [sys.executable, "-B", "-c",
             "from jarvis.app import config; print(config.MEMORY_DIR); print(config.LOG_FILE)"],
            cwd=config.BASE_DIR, env={**clean, **env}, capture_output=True, text=True, check=True)
        return [Path(p) for p in out.stdout.splitlines()[:2]]

    def test_the_memory_folder_can_be_moved(self, tmp_path):
        memory_dir, log = self._paths(JARVIS_MEMORY_DIR=str(tmp_path / "mem"),
                                      JARVIS_LOG_FILE=str(tmp_path / "little.log"))
        assert memory_dir == (tmp_path / "mem").resolve() and memory_dir.is_dir()
        assert log == (tmp_path / "little.log").resolve()

    def test_without_it_nothing_changes_for_you(self):
        memory_dir, log = self._paths()
        assert memory_dir == config.BASE_DIR / "memory"
        assert log == config.BASE_DIR / "jarvis.log"
