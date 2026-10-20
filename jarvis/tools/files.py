"""Reading, writing and finding files, all inside the workspace."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..app.config import WORKSPACE, log
from .permissions import Ask, confirm
from .workspace import SKIP_DIRS, clip, safe_path


def list_dir(path: str = ".", depth: int = 2) -> str:
    """Show the folder tree."""
    root = safe_path(path)
    if not root.is_dir():
        return f"Not a folder: {root}"
    lines: list[str] = []

    def walk(folder: Path, level: int) -> None:
        for item in sorted(folder.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            if item.name in SKIP_DIRS or len(lines) > 400:
                continue
            lines.append("  " * level + item.name + ("/" if item.is_dir() else ""))
            if item.is_dir() and level + 1 < depth:
                walk(item, level + 1)

    walk(root, 0)
    return clip("\n".join(lines) or "(empty folder)")


def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
    """Read a text file, PDF or Word document."""
    p = safe_path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(p)
    if suffix == ".docx":
        return _read_docx(p)
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    end = end_line or len(lines)
    numbered = [f"{i:>4} | {lines[i - 1]}"
                for i in range(max(1, start_line), min(end, len(lines)) + 1)]
    return clip("\n".join(numbered) or "(empty file)")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "Reading PDFs needs pypdf. Run: pip install pypdf"
    try:
        reader = PdfReader(str(path))
        return clip("\n".join((page.extract_text() or "") for page in reader.pages[:40]))
    except Exception as e:  # noqa: BLE001
        log(f"pdf read failed: {e}")
        return f"I couldn't read that PDF: {e}"


def _read_docx(path: Path) -> str:
    try:
        import docx
    except ImportError:
        return "Reading Word files needs python-docx. Run: pip install python-docx"
    try:
        return clip("\n".join(p.text for p in docx.Document(str(path)).paragraphs))
    except Exception as e:  # noqa: BLE001
        return f"I couldn't read that document: {e}"


def write_file(path: str, content: str) -> str:
    """Create or overwrite a file. An existing file is backed up first."""
    p = safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        backup = p.with_suffix(p.suffix + ".bak")
        shutil.copy2(p, backup)
        p.write_text(content, encoding="utf-8")
        return f"Overwrote {p} (previous version kept as {backup.name})."
    p.write_text(content, encoding="utf-8")
    return f"Created {p} ({len(content.splitlines())} lines)."


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace one exact, unique block of text."""
    p = safe_path(path)
    source = p.read_text(encoding="utf-8")
    count = source.count(old_text)
    if count == 0:
        return "Edit failed: old_text not found. Read the file again and copy the exact text."
    if count > 1:
        return f"Edit failed: old_text appears {count} times. Include more surrounding lines."
    p.write_text(source.replace(old_text, new_text, 1), encoding="utf-8")
    return f"Edited {p}."


def create_folder(path: str) -> str:
    p = safe_path(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"Folder ready: {p}"


def move_path(source: str, destination: str) -> str:
    src, dst = safe_path(source), safe_path(destination)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"Moved {src.name} to {dst}."


def copy_path(source: str, destination: str) -> str:
    src, dst = safe_path(source), safe_path(destination)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True) if src.is_dir() else shutil.copy2(src, dst)
    return f"Copied {src.name} to {dst}."


def _deletion(p) -> Ask:
    """What deleting this would remove, said before it happens."""
    if p.is_dir():
        inside = 0
        for inside, _ in enumerate(p.rglob("*"), start=1):
            if inside >= 10000:
                break
        what = ("an empty folder" if not inside else
                f"a folder with {'over 10,000' if inside >= 10000 else inside} "
                f"thing{'' if inside == 1 else 's'} inside")
        action = "Delete a folder and everything in it"
    else:
        size = p.stat().st_size
        what = f"a file, {size:,} bytes" if size < 1024 else f"a file, {size / 1024:,.0f} KB"
        action = "Delete a file"
    return Ask(f"Delete {p}? This can't be undone.",
               action=action, target=str(p), details=f"{p.name} — {what}",
               consequence="It's deleted for good, not moved to the Recycle Bin.",
               tone="danger", verb="Delete", tool="delete_path")


def delete_path(path: str) -> str:
    """Delete a file or folder. Always asks first."""
    p = safe_path(path)
    if p == WORKSPACE:
        return "Refused: I won't delete the whole workspace."
    if not p.exists():
        return f"Nothing at {p}."
    if not confirm(_deletion(p)):
        return "You declined, so nothing was deleted."
    shutil.rmtree(p) if p.is_dir() else p.unlink()
    return f"Deleted {p}."


def search_files(name_pattern: str = "*", contains: str | None = None,
                 path: str = ".") -> str:
    """Find files by glob, and optionally by text inside them."""
    root = safe_path(path)
    hits: list[str] = []
    for f in root.rglob(name_pattern):
        if any(part in SKIP_DIRS for part in f.parts) or not f.is_file():
            continue
        if contains:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if contains.lower() in line.lower():
                    hits.append(f"{f.relative_to(WORKSPACE)}:{n}: {line.strip()[:120]}")
        else:
            hits.append(str(f.relative_to(WORKSPACE)))
        if len(hits) >= 200:
            break
    return clip("\n".join(hits) or "No matches.")
