"""The health check has to be the one thing that never breaks, because it is
what you run when everything else has.

So these tests care less about what each probe concludes — that depends on the
machine — and more about the contract: three states only, never an exception,
and every complaint carrying a cause and a fix. Nothing here touches the
network or the model.
"""
from __future__ import annotations

import shutil
import socket
from pathlib import Path

import pytest

from jarvis.app import config, health
from jarvis.tools import registry

STATES = {health.OK, health.WARN, health.FAIL}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No probe may reach out during tests, so DNS is answered locally."""
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])


@pytest.fixture
def no_live_call(monkeypatch):
    """Stands in for the one probe that costs a real request."""
    calls = []

    def fake():
        calls.append(1)
        return health.Check("ai", detail="stubbed")

    monkeypatch.setattr(health, "check_model_live", fake)
    return calls


# ---------------------------------------------------------------- contract

def test_every_probe_returns_one_of_three_states():
    for name, probe in health.PROBES.items():
        check = probe()
        assert check.state in STATES, f"{name} returned {check.state!r}"
        assert check.group, f"{name} returned a check with no group"


def test_no_probe_raises_when_nothing_is_installed(monkeypatch):
    """The report has to survive a machine with none of the optional
    packages — that is exactly the machine someone runs it on."""
    monkeypatch.setattr(health, "_importable", lambda _name: False)
    for name, probe in health.PROBES.items():
        try:
            check = probe()
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"{name} raised {type(e).__name__}: {e}")
        assert check.state in STATES


def test_every_complaint_carries_a_problem_cause_and_fix():
    for check in health.run_checks():
        if check.state == health.OK:
            continue
        assert check.problem, f"{check.group} says {check.state} with no problem"
        assert check.cause, f"{check.group} names no cause"
        assert check.fix, f"{check.group} names no fix"


def test_a_probe_that_raises_becomes_a_failed_check(monkeypatch):
    def exploding():
        raise RuntimeError("boom")

    monkeypatch.setattr(health, "PROBES", {"runtime": health.check_runtime,
                                           "broken": exploding})
    checks = health.run_checks()
    broken = [c for c in checks if c.group == "broken"]
    assert len(broken) == 1
    assert broken[0].state == health.FAIL
    assert "boom" in broken[0].cause
    # The rest of the report still ran.
    assert any(c.group == "runtime" for c in checks)


# ---------------------------------------------------------------- config

def test_a_blank_api_key_fails_rather_than_crashing(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=\n")
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "API_KEY", "")
    check = health.check_config()
    assert check.state == health.FAIL
    assert "key" in check.problem.lower()
    assert check.fix


def test_a_missing_env_file_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    check = health.check_config()
    assert check.state == health.FAIL
    assert ".env" in check.problem


def test_the_project_root_must_not_be_the_package(monkeypatch, tmp_path):
    """The bug this exists to catch: after the package refactor, BASE_DIR
    pointed at jarvis/ and .env was silently never read."""
    monkeypatch.setattr(config, "BASE_DIR", tmp_path / "jarvis")
    assert health.check_project().state == health.FAIL


def test_the_shipped_project_root_is_fine():
    assert health.check_project().state == health.OK


# ---------------------------------------------------------------- packages

def test_a_missing_optional_package_warns_but_does_not_fail(monkeypatch):
    monkeypatch.setattr(health, "PACKAGES", {"nonexistent_pkg": ("a nicety", False)})
    check = health.check_packages()
    assert check.state == health.WARN
    assert "nonexistent_pkg" in check.problem


def test_a_missing_required_package_fails(monkeypatch):
    monkeypatch.setattr(health, "PACKAGES", {"nonexistent_pkg": ("everything", True)})
    check = health.check_packages()
    assert check.state == health.FAIL
    assert "pip install" in check.fix


def test_the_install_name_is_used_not_the_import_name(monkeypatch):
    """You install python-dotenv and import dotenv; the fix line has to say
    the one you can actually type."""
    monkeypatch.setattr(health, "PACKAGES", {"dotenv": ("reading .env", True)})
    monkeypatch.setattr(health, "_importable", lambda _name: False)
    assert "python-dotenv" in health.check_packages().fix


def test_a_package_purpose_reads_as_a_sentence(monkeypatch):
    monkeypatch.setattr(health, "PACKAGES", {"pyttsx3": ("the offline fallback voice", False)})
    monkeypatch.setattr(health, "_importable", lambda _name: False)
    cause = health.check_packages().cause
    assert "no the" not in cause and "the the" not in cause


# ---------------------------------------------------------------- browser

def test_a_browser_that_is_installed_but_not_on_path_still_counts(monkeypatch, tmp_path):
    """Windows puts neither Chrome nor Edge on PATH, and Playwright finds
    them through the registry — so a PATH-only check calls a machine with
    two browsers browserless."""
    edge = tmp_path / "msedge.exe"
    edge.write_text("")
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)
    assert health._find_browser("msedge", str(edge)) is True


def test_nothing_anywhere_is_still_nothing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)
    assert health._find_browser("msedge", "/no/such/place/msedge.exe") is False


def test_an_installed_browser_without_the_bundled_one_warns_rather_than_fails(monkeypatch):
    """JARVIS falls back to the installed browser, so this is degraded,
    not broken — and the difference decides whether someone sits through a
    200 MB download they don't need."""
    monkeypatch.setattr(health, "_importable", lambda name: name == "playwright")
    monkeypatch.setattr(health, "_find_browser", lambda cmd, *places: cmd == "msedge")
    monkeypatch.setattr(health, "_bundled_chromium", lambda: False)
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)
    check = health.check_browser()
    assert check.state == health.WARN
    assert "Edge" in check.detail


def test_no_browser_at_all_fails(monkeypatch):
    monkeypatch.setattr(health, "_importable", lambda name: name == "playwright")
    monkeypatch.setattr(health, "_find_browser", lambda cmd, *places: False)
    monkeypatch.setattr(health, "_bundled_chromium", lambda: False)
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)
    check = health.check_browser()
    assert check.state == health.FAIL
    assert "playwright install" in check.fix


# ---------------------------------------------------------------- registry

def test_the_registry_is_in_step_as_shipped():
    assert health.check_registry().state == health.OK


def test_a_tool_with_no_schema_is_caught(monkeypatch):
    monkeypatch.setitem(registry.FUNCTIONS, "undescribed_tool", lambda: "")
    check = health.check_registry()
    assert check.state == health.FAIL
    assert "undescribed_tool" in check.cause


def test_a_gated_tool_that_does_not_exist_is_caught(monkeypatch):
    from jarvis.tools import permissions
    monkeypatch.setattr(permissions, "NEEDS_CONFIRMATION",
                        permissions.NEEDS_CONFIRMATION | {"ghost_tool"})
    check = health.check_registry()
    assert check.state == health.FAIL
    assert "ghost_tool" in check.cause


# ---------------------------------------------------------------- lazy imports

def test_every_internal_import_resolves_as_shipped():
    check = health.check_imports()
    assert check.state == health.OK, check.cause


def test_a_module_that_moved_during_a_refactor_is_caught():
    """The bug this exists for: assistant.py kept importing .brain after
    brain.py moved to jarvis/ai/, and only the one command that needed it
    ever found out."""
    from jarvis.app import health as health_module

    planted = Path(health_module.__file__).parent / "_health_probe_fixture.py"
    planted.write_text("from .brain import Brain\n", encoding="utf-8")
    try:
        check = health.check_imports()
    finally:
        planted.unlink()
    assert check.state == health.FAIL
    assert "jarvis.app.brain" in check.cause
    assert health.check_imports().state == health.OK  # and it cleans up after itself


def test_a_missing_third_party_package_is_not_this_probes_business():
    """That is the packages probe's job; this one only reads the project's
    own wiring, so an uninstalled extra must not show up here."""
    from jarvis.app import health as health_module

    planted = Path(health_module.__file__).parent / "_health_probe_fixture.py"
    planted.write_text("from nonexistent_third_party import thing\n", encoding="utf-8")
    try:
        assert health.check_imports().state == health.OK
    finally:
        planted.unlink()


@pytest.mark.parametrize("module,function", [
    ("jarvis.tools.whatsapp", "send_whatsapp_message"),
    ("jarvis.tools.whatsapp_web", "wa_send_web"),
    ("jarvis.tools.browser", "click_text"),
])
def test_the_confirmation_gate_is_reachable_from_every_tool_behind_it(module, function):
    """All three imported confirm_fn from a module that no longer existed,
    so the gated tools failed on the import rather than on the gate. They
    failed closed, but they failed."""
    import importlib
    mod = importlib.import_module(module)
    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "from .tools import" not in source
    assert "from .permissions import confirm_fn" in source


def test_a_gated_tool_runs_far_enough_to_reach_the_gate(refuse):
    """Called with nothing drafted, it must answer — not die on an import."""
    reply = registry.execute_tool("send_whatsapp_message", {})
    assert "Error in" not in reply and "ModuleNotFound" not in reply


def test_the_brain_lives_where_the_assistant_looks_for_it():
    from jarvis.ai.brain import Brain
    assert Brain().history == []
    source = Path(__import__("jarvis.app.assistant", fromlist=["x"]).__file__).read_text(
        encoding="utf-8")
    assert "from .brain import" not in source
    assert "from ..ai.brain import Brain" in source


# ---------------------------------------------------------------- the report

def test_the_report_renders_offline_and_names_every_group():
    report = health.system_check()
    assert "SYSTEM HEALTH" in report
    for group in health.PROBES:
        assert group.upper() in report


def test_the_report_explains_each_trouble_it_lists():
    checks = [health.Check("mic").failed("No microphone found",
                                         "Windows reports no input devices",
                                         "Plug one in")]
    report = health.format_report(checks)
    assert "Problem:" in report and "Cause:" in report and "Fix:" in report
    assert "Plug one in" in report


def test_a_clean_report_says_so():
    report = health.format_report([health.Check("runtime", detail="Python 3.12")])
    assert "Everything checks out." in report


def test_the_summary_counts_broken_and_degraded_separately():
    report = health.format_report([
        health.Check("mic").failed("p", "c", "f"),
        health.Check("jobs").warned("p", "c", "f"),
    ])
    assert "1 broken, 1 degraded but working." in report


def test_warnings_alone_do_not_read_as_breakage():
    report = health.format_report([health.Check("jobs").warned("p", "c", "f")])
    assert "Nothing broken" in report


# ---------------------------------------------------------------- live probe

def test_the_model_is_not_called_unless_asked(no_live_call):
    health.run_checks()
    assert no_live_call == []


def test_the_model_is_called_when_asked(no_live_call):
    report = health.system_check(live=True)
    assert no_live_call == [1]
    assert "AI" in report


def test_check_component_can_ask_for_the_model_alone(no_live_call):
    health.check_component("model")
    assert no_live_call == [1]


# ---------------------------------------------------------------- one at a time

def test_check_component_reports_only_that_component():
    report = health.check_component("router")
    assert "ROUTER" in report
    assert "BROWSER" not in report


@pytest.mark.parametrize("said,group", [
    ("microphone", "MIC"), ("mic", "MIC"), ("voice", "TTS"),
    ("speaker", "TTS"), ("db", "DATABASE"), ("internet", "NETWORK"),
    ("Browser", "BROWSER"), ("  tools  ", "TOOLS"),
])
def test_check_component_understands_the_words_people_use(said, group):
    assert group in health.check_component(said)


@pytest.mark.parametrize("said", ["", "kitchen sink", None])
def test_an_unknown_component_lists_the_real_ones(said):
    reply = health.check_component(said)
    assert "I can check" in reply
    assert "mic" in reply and "ai" in reply


# ---------------------------------------------------------------- wiring

def test_both_tools_are_registered_and_described():
    described = {t["name"] for t in registry.TOOL_SCHEMAS}
    for name in ("system_check", "check_component"):
        assert name in registry.FUNCTIONS
        assert name in described


def test_the_model_can_run_a_check_through_the_registry():
    assert "SYSTEM HEALTH" in registry.execute_tool("check_component", {"name": "router"})


def test_a_health_check_needs_no_confirmation():
    """It only reads, so it must not stop and ask."""
    from jarvis.tools.permissions import NEEDS_CONFIRMATION
    assert "system_check" not in NEEDS_CONFIRMATION
    assert "check_component" not in NEEDS_CONFIRMATION


# ---------------------------------------------------------------- routing

@pytest.mark.parametrize("said", [
    "run a system check", "system check", "run diagnostics", "diagnostics",
    "health check", "check yourself", "check everything",
    "are you okay?", "are you healthy", "is everything working",
    "sab theek hai", "status report",
])
def test_these_all_route_to_the_health_check_locally(said):
    from jarvis.routing import router
    reply = router.fast_route(said)
    assert reply and "SYSTEM HEALTH" in reply


def test_asking_about_one_part_routes_to_that_part():
    from jarvis.routing import router
    reply = router.fast_route("check the microphone")
    assert reply and "MIC" in reply and "BROWSER" not in reply


def test_a_full_check_is_the_only_phrasing_that_calls_the_model(no_live_call):
    from jarvis.routing import router
    router.fast_route("system check")
    assert no_live_call == []
    router.fast_route("run a full system check")
    assert no_live_call == [1]


def test_unrelated_check_commands_still_fall_through_to_the_model():
    from jarvis.routing import router
    assert router.fast_route("check my email") is None
    assert router.fast_route("check the weather in prayagraj") is None


# ------------------------------------------------------- undefined names

def test_every_name_the_code_reaches_for_exists():
    check = health.check_names()
    assert check.state == health.OK, check.cause


def test_a_function_calling_a_renamed_function_is_caught():
    """The accident this exists for: `_query_from` was renamed to
    `_queries_from`, one caller was left behind, and "open linkedin" raised
    NameError while every test and every other command passed. An import
    check can't see this — the name is not an import."""
    from jarvis.app import health as health_module

    planted = Path(health_module.__file__).parent / "_names_probe_fixture.py"
    planted.write_text("def caller():\n    return a_function_that_was_renamed()\n",
                       encoding="utf-8")
    try:
        check = health.check_names()
    finally:
        planted.unlink()
        import sys
        sys.modules.pop("jarvis.app._names_probe_fixture", None)
    assert check.state == health.FAIL
    assert "a_function_that_was_renamed" in check.cause


def test_builtins_are_not_reported_as_missing():
    """A probe that flags `len` and `print` is noise nobody reads."""
    check = health.check_names()
    assert "len" not in check.cause and "print" not in check.cause
