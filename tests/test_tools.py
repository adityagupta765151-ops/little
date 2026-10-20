"""The sandbox and the confirmation gate are the two things that keep
JARVIS from doing damage, so they get tested hardest."""
from __future__ import annotations

import pytest

from jarvis import tools
from jarvis.tools import files, system, workspace


class TestSandbox:
    """The one rule that keeps JARVIS off the rest of the disk."""

    def test_relative_paths_land_in_the_workspace(self, workspace):
        files.write_file("notes/todo.txt", "hello")
        assert (workspace / "notes" / "todo.txt").read_text() == "hello"

    @pytest.mark.parametrize("escape", [
        "../outside.txt",
        "../../etc/passwd",
        "notes/../../escape.txt",
    ])
    def test_paths_outside_the_workspace_are_refused(self, escape):
        with pytest.raises(PermissionError):
            workspace.safe_path(escape)

    def test_escape_through_a_tool_returns_an_error_not_a_crash(self):
        result = tools.execute_tool("read_file", {"path": "../../etc/passwd"})
        assert "outside the workspace" in result

    def test_absolute_path_inside_the_workspace_is_allowed(self, workspace):
        target = workspace / "fine.txt"
        files.write_file(str(target), "ok")
        assert target.read_text() == "ok"


class TestFiles:
    def test_overwriting_keeps_a_backup(self, workspace):
        files.write_file("app.py", "first")
        files.write_file("app.py", "second")
        assert (workspace / "app.py").read_text() == "second"
        assert (workspace / "app.py.bak").read_text() == "first"

    def test_read_file_numbers_the_lines(self):
        files.write_file("a.txt", "one\ntwo")
        out = files.read_file("a.txt")
        assert "1 | one" in out and "2 | two" in out

    def test_edit_replaces_a_unique_block(self, workspace):
        files.write_file("a.py", "x = 1\ny = 2\n")
        files.edit_file("a.py", "y = 2", "y = 3")
        assert (workspace / "a.py").read_text() == "x = 1\ny = 3\n"

    def test_edit_refuses_when_the_text_is_not_unique(self):
        files.write_file("a.py", "dup\ndup\n")
        assert "appears 2 times" in files.edit_file("a.py", "dup", "new")

    def test_edit_refuses_when_the_text_is_missing(self):
        files.write_file("a.py", "hello")
        assert "not found" in files.edit_file("a.py", "goodbye", "x")

    def test_search_finds_text_inside_files(self):
        files.write_file("src/login.py", "def login():\n    pass\n")
        files.write_file("src/other.py", "def other():\n    pass\n")
        hits = files.search_files("*.py", contains="def login")
        assert "login.py" in hits and "other.py" not in hits


class TestConfirmation:
    def test_delete_does_nothing_when_refused(self, workspace, refuse):
        files.write_file("keep.txt", "data")
        result = files.delete_path("keep.txt")
        assert "declined" in result
        assert (workspace / "keep.txt").exists()

    def test_delete_removes_the_file_when_allowed(self, workspace, allow):
        files.write_file("gone.txt", "data")
        files.delete_path("gone.txt")
        assert not (workspace / "gone.txt").exists()

    def test_the_workspace_itself_can_never_be_deleted(self, workspace, allow):
        assert "Refused" in files.delete_path(str(workspace))
        assert workspace.exists()

    def test_shell_commands_do_not_run_when_refused(self, refuse):
        assert "declined" in system.run_command("echo should-not-happen")

    def test_every_dangerous_tool_is_listed_as_needing_confirmation(self):
        assert {"delete_path", "run_command", "send_whatsapp_message"} <= tools.NEEDS_CONFIRMATION


class TestRegistry:
    def test_every_tool_has_a_schema_and_every_schema_has_a_tool(self):
        described = {t["name"] for t in tools.TOOL_SCHEMAS}
        implemented = set(tools.FUNCTIONS)
        assert described == implemented

    def test_required_arguments_are_declared_properties(self):
        for tool in tools.TOOL_SCHEMAS:
            schema = tool["input_schema"]
            missing = set(schema.get("required", [])) - set(schema.get("properties", {}))
            assert not missing, f"{tool['name']} requires undeclared {missing}"

    def test_an_unknown_tool_is_reported_not_raised(self):
        assert "Unknown tool" in tools.execute_tool("no_such_tool", {})

    def test_wrong_arguments_are_reported_not_raised(self):
        assert "Wrong arguments" in tools.execute_tool("create_folder", {"nope": 1})


class TestProjectPaths:
    """config.py moved packages once and took the project root with it,
    which silently pointed .env, memory/ and the dashboard at the wrong
    folder. These pin it down."""

    def test_the_base_directory_is_the_project_not_the_package(self):
        from jarvis.app import config
        assert (config.BASE_DIR / "requirements.txt").exists()
        assert config.BASE_DIR.name != "jarvis", "BASE_DIR points at the package"

    def test_memory_and_the_log_sit_beside_the_launcher(self):
        """The default, read in a fresh interpreter without the tests' own
        temporary folders — these tests never use the real ones."""
        import os
        import subprocess
        import sys
        from pathlib import Path

        from jarvis.app import config
        env = {k: v for k, v in os.environ.items()
               if k not in ("JARVIS_MEMORY_DIR", "JARVIS_LOG_FILE")}
        out = subprocess.run(
            [sys.executable, "-B", "-c",
             "from jarvis.app import config; print(config.MEMORY_DIR); print(config.LOG_FILE)"],
            cwd=config.BASE_DIR, env=env, capture_output=True, text=True, check=True)
        memory, log = out.stdout.splitlines()[:2]
        assert Path(memory) == config.BASE_DIR / "memory"
        assert Path(log) == config.BASE_DIR / "jarvis.log"

    def test_the_dashboard_can_find_its_own_files(self):
        from jarvis.jobs import dashboard
        assert (dashboard.UI_DIR / "index.html").exists()
