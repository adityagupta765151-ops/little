"""Is a project ready to go on GitHub? (Chapter 32)

Looked at on this computer, file by file, without the model: a README, a
.gitignore that keeps secrets and bulky folders out, no secret files or
keys in what would be committed, nothing too big for GitHub, and git set
up. Reads only; changes nothing. The planner uses it to see where a project
stands before it starts and to check the result at the end.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

from ..store.memory import SECRET_VALUE
from .workspace import safe_path

MAX_FILES = 3000
TOO_BIG = 50 * 1024 * 1024          # GitHub warns at 50 MB and refuses 100 MB
SCAN_BYTES = 256 * 1024             # read at most this much of a file for keys
SECRET_FILES = (".env", ".env.*", "*.pem", "*.key", "id_rsa", "id_ed25519", "credentials.json",
                "service-account*.json", "*.p12", "*.pfx")
BULKY = ("node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next")
TEXTISH = {".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".env", ".yml", ".yaml", ".toml", ".ini", ".cfg",
           ".md", ".txt", ".html", ".css", ".java", ".go", ".rb", ".php", ".sh", ".bat", ".ps1", ".xml", ""}


def _matches(pattern: str, relative: str) -> bool:
    parts = relative.split("/")
    anchored = pattern.startswith("/")
    pattern = pattern.strip("/")
    if anchored or "/" in pattern:
        return fnmatch.fnmatch(relative, pattern) or relative.startswith(pattern + "/")
    return any(fnmatch.fnmatch(part, pattern) for part in parts)


def _ignored(patterns: list[str], relative: str) -> bool:
    """Would .gitignore keep this path out? The common forms: a name, a
    folder with a trailing slash, a glob, a leading slash, and "!" to let
    something back in — the last pattern that matches decides, as in git."""
    ignored = False
    for raw in patterns:
        pattern = raw.strip()
        if not pattern or pattern.startswith("#"):
            continue
        if pattern.startswith("!"):
            if _matches(pattern[1:], relative):
                ignored = False
        elif _matches(pattern, relative):
            ignored = True
    return ignored


def check(path: str = ".") -> dict:
    """{"root", "items": [{"ok", "what", "detail"}], "ready", "files"}.
    Raises the sandbox's PermissionError for a path outside the workspace."""
    root = safe_path(path or ".")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a folder: {root}")
    gitignore = root / ".gitignore"
    patterns = gitignore.read_text(encoding="utf-8", errors="replace").splitlines() if gitignore.exists() else []

    files, secret_files, big, keyed = [], [], [], []
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root).as_posix()
        if ".git" in item.relative_to(root).parts or not item.is_file():
            continue
        if _ignored(patterns, relative):
            continue
        files.append(relative)
        if len(files) > MAX_FILES:
            break
        if any(fnmatch.fnmatch(item.name, p) for p in SECRET_FILES) and item.name not in (".env.example",
                                                                                         ".env.sample"):
            secret_files.append(relative)
        size = item.stat().st_size
        if size > TOO_BIG:
            big.append(f"{relative} ({size // (1024 * 1024)} MB)")
        if item.suffix.lower() in TEXTISH and size:
            try:
                with item.open("rb") as handle:
                    text = handle.read(SCAN_BYTES).decode("utf-8", errors="ignore")
            except OSError:
                continue
            if SECRET_VALUE.search(text):
                keyed.append(relative)

    committed_bulky = sorted({f.split("/")[0] for f in files if f.split("/")[0] in BULKY})
    readme = next((f for f in files if f.lower() in ("readme.md", "readme.rst", "readme.txt", "readme")), None)
    items = [
        {"ok": bool(readme), "what": "README",
         "detail": readme or "No README at the top. Say what it is, how to run it."},
        {"ok": gitignore.exists(), "what": ".gitignore",
         "detail": "present" if gitignore.exists() else "None — secrets and bulky folders would be committed."},
        {"ok": not secret_files, "what": "Secret files kept out",
         "detail": ", ".join(secret_files[:5]) + " would be committed" if secret_files else "none would be committed"},
        {"ok": not keyed, "what": "No keys in the code",
         "detail": "something shaped like a key in " + ", ".join(keyed[:5]) if keyed else "none found"},
        {"ok": not committed_bulky, "what": "Bulky folders kept out",
         "detail": ", ".join(committed_bulky) + " would be committed" if committed_bulky else "none would be committed"},
        {"ok": not big, "what": "No file over 50 MB", "detail": ", ".join(big[:5]) if big else "none"},
        {"ok": (root / ".git").is_dir(), "what": "git set up",
         "detail": "yes" if (root / ".git").is_dir() else "not yet — git init"},
    ]
    return {"root": str(root), "items": items, "ready": all(i["ok"] for i in items), "files": len(files)}


def check_github_ready(path: str = ".") -> str:
    """The tool: the checklist, in words. Reads only."""
    try:
        found = check(path)
    except (PermissionError, NotADirectoryError) as e:
        return str(e)
    lines = [f"{'✓' if i['ok'] else '✗'} {i['what']}: {i['detail']}" for i in found["items"]]
    todo = sum(not i["ok"] for i in found["items"])
    head = (f"{Path(found['root']).name} looks ready for GitHub ({found['files']} files would be committed)."
            if found["ready"] else
            f"{Path(found['root']).name}: {todo} thing{'' if todo == 1 else 's'} to sort before GitHub.")
    return "\n".join([head] + lines)
