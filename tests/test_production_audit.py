"""Chapter 48 — the final production audit.

What the audit found and fixed, held in place, and the checks that keep the
project honest from here: nothing a model or a web page can put in a tool's
arguments reaches a command line; the local dashboard answers only this
computer; every setting the code reads is documented; no secret is in the
project; the documents exist and say what the code does.
"""
from __future__ import annotations

import ast
import http.server
import inspect
import re
import threading
import urllib.request
from pathlib import Path

import pytest

from jarvis.app import bridge
from jarvis.jobs import dashboard
from jarvis.store import memory
from jarvis.tools import apps, registry, system, whatsapp

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [p for p in (ROOT / "jarvis").rglob("*.py")] + [ROOT / "launcher.py", ROOT / "launcher_web.py"]


@pytest.fixture
def popen(monkeypatch):
    calls = []

    class Process:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))
    monkeypatch.setattr(apps.subprocess, "Popen", Process)
    monkeypatch.setattr(apps.subprocess, "run", lambda *a, **k: calls.append((a, k)) or
                        type("Done", (), {"returncode": 0})())
    return calls


# ======================================================= the command line

class TestOpeningAnApp:
    ATTACKS = ['chrome" & calc & "', "x | whoami", "a > C:/out.txt", "%COMSPEC%", "a ^& b", 'x"\r\ncalc']

    @pytest.mark.parametrize("name", ATTACKS)
    def test_command_line_characters_are_refused(self, popen, monkeypatch, name):
        monkeypatch.setattr(apps, "SYSTEM", "Windows")
        assert apps.open_app(name).startswith("I won't open that")
        assert popen == []

    @pytest.mark.parametrize("name", ATTACKS[:2])
    def test_also_when_the_model_asks(self, popen, monkeypatch, name):
        monkeypatch.setattr(apps, "SYSTEM", "Windows")
        assert registry.execute_tool("open_app", {"name": name}).startswith("I won't open that")
        assert popen == []

    @pytest.mark.parametrize("name,target", [("chrome", "chrome"), ("settings", "ms-settings:"),
                                             ("C:/Program Files (x86)/Tool/tool.exe",
                                              "C:/Program Files (x86)/Tool/tool.exe")])
    def test_real_names_open_exactly_as_before(self, popen, monkeypatch, name, target):
        monkeypatch.setattr(apps, "SYSTEM", "Windows")
        assert apps.open_app(name) == f"Opening {name}."
        assert popen == [((f'start "" "{target}"',), {"shell": True})]


class TestClosingAnApp:
    @pytest.mark.parametrize("name", ["*", "?", "*.exe", ".", "..", "chrome*", "a;b", "", " "])
    def test_wildcards_and_symbols_are_refused(self, popen, monkeypatch, name):
        monkeypatch.setattr(apps, "SYSTEM", "Windows")
        assert apps.close_app(name).startswith("I won't close")
        assert popen == []

    def test_a_real_name_closes_that_app(self, popen, monkeypatch):
        monkeypatch.setattr(apps, "SYSTEM", "Windows")
        assert apps.close_app("Chrome") == "Closed Chrome."
        assert popen[0][0][0] == ["taskkill", "/im", "chrome.exe", "/f"]

    def test_on_linux_a_dot_is_only_a_dot(self, popen, monkeypatch):
        monkeypatch.setattr(apps, "SYSTEM", "Linux")
        apps.close_app("node.js")
        assert popen[0][0][0] == ["pkill", "-f", r"node\.js"]


class TestVsCode:
    @pytest.fixture
    def windows(self, monkeypatch, workspace):
        calls = []
        monkeypatch.setattr(system, "_windows", lambda: True)
        monkeypatch.setattr(system.shutil, "which", lambda _n: "C:/VS Code/bin/code.cmd")
        monkeypatch.setattr(system.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
        return calls

    def test_a_path_the_command_line_would_split_is_refused(self, windows, workspace):
        (workspace / "a&calc.txt").write_text("x", encoding="utf-8")
        assert "command line would read as a command" in system.open_in_vscode("a&calc.txt")
        assert windows == []

    def test_an_ordinary_file_opens(self, windows, workspace):
        (workspace / "notes.txt").write_text("x", encoding="utf-8")
        assert system.open_in_vscode("notes.txt", line=3) == "Opened notes.txt in VS Code."
        (args, kwargs), = windows
        assert args[0][:2] == ["C:/VS Code/bin/code.cmd", "-g"] and args[0][2].endswith("notes.txt:3")
        assert kwargs == {"shell": True}


class TestWhatsAppLinks:
    @pytest.fixture
    def opened(self, monkeypatch):
        links = []
        monkeypatch.setattr(whatsapp.os, "startfile", links.append, raising=False)
        monkeypatch.setattr(whatsapp.webbrowser, "open", lambda *_a, **_k: pytest.fail("the browser was used"))
        return links

    def test_a_link_goes_to_windows_own_handler_with_no_command_line(self, opened):
        memory.add_contact("rahul", "+919812345678")
        assert whatsapp.open_contact("rahul") == "Opening your chat with rahul."
        assert opened == ["whatsapp://send?phone=919812345678"]
        assert "subprocess" not in inspect.getsource(whatsapp)

    def test_a_crafted_number_opens_nothing(self, opened):
        memory.add_contact("evil", '1" & calc & "')
        assert whatsapp.open_contact("evil") == whatsapp.BAD_NUMBER
        assert whatsapp.draft_whatsapp_message("evil", "hi") == whatsapp.BAD_NUMBER
        assert opened == [] and not whatsapp.has_draft()

    def test_so_nothing_is_sent_after_it(self, opened, allow, monkeypatch):
        memory.add_contact("evil", '1"\r\ncalc')
        monkeypatch.setattr(whatsapp, "pyautogui", type("Keys", (), {"press": lambda *_a: pytest.fail("sent")}))
        assert whatsapp.send_whatsapp_message("evil", "hi") == whatsapp.BAD_NUMBER

    def test_elsewhere_the_system_opener_is_used(self, monkeypatch):
        links = []
        monkeypatch.delattr(whatsapp.os, "startfile", raising=False)
        monkeypatch.setattr(whatsapp.webbrowser, "open", links.append)
        assert whatsapp._open_link("whatsapp://") and links == ["whatsapp://"]


class TestTheShellIsUsedOnlyWhereReviewed:
    def test_only_the_reviewed_places(self):
        """Any new `shell=` or string command fails here until it's reviewed:
        run_command asks you every time; open_app refuses command-line
        characters; open_in_vscode refuses them in the path on Windows."""
        found = []
        for path in SOURCES:
            for line in path.read_text(encoding="utf-8").splitlines():
                if re.search(r"shell\s*=|os\.system\(|os\.popen\(|Popen\(f", line):
                    found.append((path.relative_to(ROOT).as_posix(), line.strip()))
        assert sorted(found) == sorted([
            ("jarvis/tools/apps.py", "subprocess.Popen(f'start \"\" \"{target}\"', shell=True)"),
            ("jarvis/tools/system.py", "result = subprocess.run(command, shell=True, cwd=folder,"),
            ("jarvis/tools/system.py", 'subprocess.Popen([code, "-g", target], shell=_windows())'),
        ])

    def test_no_eval_exec_or_pickle(self):
        for path in SOURCES:
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"(?<![\w.])(eval|exec)\(|\bpickle\b|yaml\.load\(", text), path


# ========================================================= the dashboard

class TestTheDashboardAnswersOnlyThisComputer:
    @pytest.fixture
    def served(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield server.server_address[1]
        server.shutdown()

    def _get(self, port, host):
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/state", headers={"Host": host})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_localhost_is_answered(self, served):
        assert self._get(served, f"127.0.0.1:{served}") == 200
        assert self._get(served, f"localhost:{served}") == 200

    @pytest.mark.parametrize("host", ["evil.example", "evil.example:{port}", "127.0.0.1.evil.example",
                                      "localhost:1", ""])
    def test_a_site_pointing_its_name_here_is_not(self, served, host):
        assert self._get(served, host.format(port=served)) == 403


# ====================================================== settings and secrets

class TestSettingsAreDocumented:
    def test_every_setting_the_code_reads_is_in_env_example(self):
        read = set()
        for path in SOURCES:
            read |= set(re.findall(r"getenv\(\s*\"([A-Z][A-Z_0-9]+)\"", path.read_text(encoding="utf-8")))
            read |= set(re.findall(r"environ(?:\.get)?[\[(]\s*\"([A-Z][A-Z_0-9]+)\"",
                                   path.read_text(encoding="utf-8")))
        documented = set(re.findall(r"^#? ?([A-Z][A-Z_0-9]+)=", (ROOT / ".env.example").read_text(encoding="utf-8"),
                                    re.M))
        assert read and read - documented == set()

    def test_the_example_holds_no_real_key(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert re.search(r"^GEMINI_API_KEY=your-key", text, re.M)
        assert not re.search(r"AIza[0-9A-Za-z_\-]{35}", text)
        assert re.search(r"^ADZUNA_APP_KEY=$", text, re.M) and re.search(r"^MUSE_API_KEY=$", text, re.M)

    def test_folders_left_blank_would_mean_here_so_theyre_commented_out(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert not re.search(r"^JARVIS_(MEMORY_DIR|LOG_FILE|WORKSPACE)=", text, re.M)


class TestNoSecretsInTheProject:
    PATTERNS = re.compile(r"AIza[0-9A-Za-z_\-]{35}|ghp_[A-Za-z0-9]{36}|sk-[A-Za-z0-9]{32,}|"
                          r"-----BEGIN [A-Z ]*PRIVATE KEY")
    SKIP = {"memory", "browser_profile", ".git", "__pycache__", ".venv", "venv", "node_modules"}

    def test_none_in_any_file(self):
        found = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or self.SKIP & set(path.relative_to(ROOT).parts) or path.name == ".env":
                continue
            if path.suffix in (".png", ".ico", ".db", ".zip", ".pyc", ".jpg"):
                continue
            if self.PATTERNS.search(path.read_text(encoding="utf-8", errors="ignore")):
                found.append(path.name)
        assert found == []

    def test_your_things_are_never_committed(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
        for kept_out in (".env", "memory/", "browser_profile/", "jarvis.log"):
            assert kept_out in ignored, kept_out


class TestDependencies:
    MINIMUM = {"pillow": (12, 3), "urllib3": (2, 7), "idna": (3, 15)}

    def test_minimums_past_known_vulnerabilities(self):
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        for name, (major, minor) in self.MINIMUM.items():
            found = re.search(rf"^{name}>=(\d+)\.(\d+)", text, re.M | re.I)
            assert found and (int(found[1]), int(found[2])) >= (major, minor), name

    def test_an_extra_that_may_need_compiling_cant_stop_the_install(self):
        """pocketsphinx 5.1.1 has no Windows build for Python 3.12, and with
        --upgrade pip tried to compile it and stopped the whole install."""
        main = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        extra = (ROOT / "requirements-optional.txt").read_text(encoding="utf-8")
        assert not re.search(r"^pocketsphinx", main, re.M) and re.search(r"^pocketsphinx>=", extra, re.M)
        for text in (main, extra):
            assert re.search(r"^--prefer-binary$", text, re.M)

    def test_the_core_set_has_them_too(self):
        core = (ROOT / "requirements-core.txt").read_text(encoding="utf-8")
        assert re.search(r"^urllib3>=2\.7", core, re.M) and re.search(r"^idna>=3\.15", core, re.M)

    def test_every_third_party_import_is_a_requirement(self):
        wanted = {line.split(">=")[0].split("==")[0].strip().lower()
                  for name in ("requirements.txt", "requirements-optional.txt")
                  for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith(("#", "-"))}
        known_as = {"dotenv": "python-dotenv", "docx": "python-docx", "speech_recognition": "speechrecognition",
                    "webview": "pywebview", "edge_tts": "edge-tts", "pyaudio": "pyaudio", "PIL": "pillow",
                    "playsound3": "playsound3"}
        # Used only if you happen to have it, never required: a second way to
        # play the neural voice's audio when playsound3 can't.
        optional_extras = {"pygame"}
        standard = set(__import__("sys").stdlib_module_names)
        imported = set()
        for path in SOURCES:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    tops = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                    tops = [node.module.split(".")[0]]
                else:
                    continue
                imported |= {t for t in tops if t not in standard and t not in ("jarvis", "__future__")}
        assert imported - optional_extras, "found the imports"
        assert {known_as.get(name, name).lower() for name in imported - optional_extras} <= wanted


# =============================================================== the documents

class TestTheDocuments:
    @pytest.mark.parametrize("name", ["README.md", "ARCHITECTURE.md", "SECURITY.md", "INSTALLATION.md", "API.md",
                                      "CHANGELOG.md", "DEMO_SCRIPT.md", "JARVIS_PHASE2_PLAN.md"])
    def test_each_exists_and_says_something(self, name):
        assert len((ROOT / name).read_text(encoding="utf-8").split()) > 150

    def test_the_plan_marks_every_chapter_of_the_batch_done(self):
        plan = (ROOT / "JARVIS_PHASE2_PLAN.md").read_text(encoding="utf-8")
        for chapter in range(27, 49):
            assert re.search(rf"^\| {chapter} \| [^|]+ \| ✅ \|", plan, re.M), chapter

    def test_every_call_the_window_can_make_is_in_api_md(self):
        api = (ROOT / "API.md").read_text(encoding="utf-8")
        public = [n for n, _ in inspect.getmembers(bridge.Api, inspect.isfunction) if not n.startswith("_")]
        assert public and [n for n in public if f"`{n}(" not in api] == []

    def test_the_changelog_has_every_chapter(self):
        log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        for chapter in range(27, 49):
            assert re.search(rf"Chapter {chapter}\b", log), chapter

    def test_security_md_names_the_fixes(self):
        text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        for fix in ("open_app", "close_app", "open_in_vscode", "WhatsApp", "DNS rebinding", "pillow", "urllib3"):
            assert fix in text, fix
