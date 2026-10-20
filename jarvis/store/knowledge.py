"""Your knowledge base (Chapter 31): documents you add, asked in words.

    parse  ->  chunk  ->  embed  ->  store  ->  retrieve  ->  answer

- **Parse.** Text, Markdown, code, CSV, JSON, HTML, PDF and Word files from
  inside the workspace — the same sandbox every file tool uses. A PDF keeps
  its page numbers.
- **Chunk.** Paragraphs packed into parts of about 900 characters, with a
  little overlap so a sentence cut at a boundary is still found whole.
- **Embed.** On this computer: each part becomes a sparse vector of its
  word stems and word pairs. Nothing is sent anywhere to add a document.
- **Store.** `knowledge.db` in the memory folder: documents and their parts
  with their vectors. The file itself is never changed or copied.
- **Retrieve.** A part must hold at least half the question's words to
  count at all; those that do are ranked by BM25 (rarer words count for
  more, a long part doesn't win by length). When none does, nothing is
  retrieved — and the model isn't asked.
- **Answer.** Only the parts retrieved go to the model, numbered. What it
  says is checked: a fact must cite a part, and the part must hold most of
  its words. What passes is a RETRIEVED FACT with its source; anything
  else is shown as a GENERATED SUGGESTION — the model's own, not in your
  documents. With the model unreachable, the passages themselves are the
  answer.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import re
import sqlite3
import threading
from collections import Counter
from pathlib import Path

from ..app import config
from ..app.config import log

DB_PATH = config.MEMORY_DIR / "knowledge.db"

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".yaml", ".yml", ".ini", ".cfg", ".toml",
                 ".log", ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".go", ".rs", ".rb",
                 ".php", ".sql", ".sh", ".bat", ".ps1", ".css", ".xml"}
HTML_SUFFIXES = {".html", ".htm"}
SUFFIXES = TEXT_SUFFIXES | HTML_SUFFIXES | {".pdf", ".docx"}

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PAGES = 500
MAX_PARTS = 2000                 # per document
MAX_FILES = 200                  # per folder added
PART_CHARS, OVERLAP = 900, 150
TOP = 4                          # parts handed to the model
MIN_COVERAGE = 0.5               # share of the question's words a part must hold
K1, B = 1.5, 0.75                # BM25's usual settings
FACT_SUPPORT = 0.6               # share of a fact's words its cited parts must hold

_lock = threading.RLock()

STOP = set("""a about above after again against all am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having he her
here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not of off
on once only or other our ours ourselves out over own same she should so some such than that the their theirs them
themselves then there these they this those through to too under until up very was we were what when where which
while who whom why will with would you your yours yourself yourselves hai ka ki ke ko se me mein kya""".split())


# ------------------------------------------------------------------- parse

def _html_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|h\d|li|tr)>", "\n", raw)
    text = re.sub(r"<[^>]+>", " ", raw)
    import html
    return html.unescape(text)


def parse(path: Path) -> list[tuple[int | None, str]]:
    """The file's text as (page, text) pieces — page numbers for a PDF,
    None otherwise. Raises ValueError with a sentence to say."""
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        raise ValueError(f"I can't read {suffix or 'files without an extension'} files into the knowledge base.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"{path.name} is over {MAX_FILE_BYTES // (1024 * 1024)} MB, too big to add.")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise ValueError("Reading PDFs needs pypdf. Run: pip install pypdf") from e
        try:
            reader = PdfReader(str(path))
            return [(n, page.extract_text() or "") for n, page in enumerate(reader.pages[:MAX_PAGES], 1)]
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"I couldn't read that PDF: {e}") from e
    if suffix == ".docx":
        try:
            import docx
        except ImportError as e:
            raise ValueError("Reading Word files needs python-docx. Run: pip install python-docx") from e
        try:
            return [(None, "\n".join(p.text for p in docx.Document(str(path)).paragraphs))]
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"I couldn't read that document: {e}") from e
    raw = path.read_text(encoding="utf-8", errors="replace")
    return [(None, _html_text(raw) if suffix in HTML_SUFFIXES else raw)]


# ------------------------------------------------------------------- chunk

def chunk(pieces: list[tuple[int | None, str]]) -> list[dict]:
    """Paragraphs packed into parts of about PART_CHARS, each carrying the
    tail of the one before so a sentence at a boundary is found whole. A
    part never spans two pages."""
    parts: list[dict] = []
    for page, text in pieces:
        paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text or "")]
        paragraphs = [p for p in paragraphs if p]
        current = ""
        for paragraph in paragraphs:
            while len(paragraph) > PART_CHARS:           # a paragraph longer than a part
                cut = paragraph.rfind(" ", 0, PART_CHARS) or PART_CHARS
                if current:
                    parts.append({"page": page, "text": current})
                    current = ""
                parts.append({"page": page, "text": paragraph[:cut]})
                paragraph = paragraph[max(cut - OVERLAP, 1):].lstrip()
            if current and len(current) + 1 + len(paragraph) > PART_CHARS:
                parts.append({"page": page, "text": current})
                tail = current[-OVERLAP:]
                current = (tail[tail.find(" ") + 1:] if " " in tail else tail) + " " + paragraph
            else:
                current = f"{current} {paragraph}".strip()
        if current:
            parts.append({"page": page, "text": current})
    return parts[:MAX_PARTS]


# ------------------------------------------------------------------- embed

def _stem(word: str) -> str:
    """A crude stem, the same for a word's usual forms: deadline, deadlines;
    match, matches, matched, matching; deploy, deployed, deployment."""
    for suffix in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ied", "ers", "er", "ed", "es", "ly", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            if suffix == "es" and not word[:-2].endswith(("s", "x", "z", "ch", "sh")):
                continue                      # "deadlines" is deadline + s
            word = word[: -len(suffix)] + ("y" if suffix in ("ies", "ied") else "")
            break
    return word[:-1] if len(word) > 3 and word.endswith("e") else word


def terms(text: str) -> list[str]:
    """Word stems, then adjacent pairs of them, without the little words."""
    words = [_stem(w) for w in re.findall(r"[a-z0-9][a-z0-9+#.]*[a-z0-9+#]|[a-z0-9]", str(text or "").lower())
             if w not in STOP]
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


def embed(text: str) -> dict[str, int]:
    """A part's sparse vector: how often each term occurs in it."""
    return dict(Counter(terms(text)))


# ------------------------------------------------------------------- store

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL,
            added TEXT NOT NULL, pages INTEGER, parts INTEGER NOT NULL, chars INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS parts (
            id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            n INTEGER NOT NULL, page INTEGER, text TEXT NOT NULL, vector TEXT NOT NULL, length INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS parts_doc ON parts(doc_id);
    """)
    return conn


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def add_file(path: Path) -> dict:
    """Parse, chunk, embed and store one file. {"status": "added" |
    "updated" | "unchanged" | "empty", "name", "parts", "pages"}; raises
    ValueError with a sentence to say."""
    digest = _digest(path)
    key = str(path.resolve())
    with _lock, _connect() as conn:
        row = conn.execute("SELECT id, sha256 FROM documents WHERE path = ?", (key,)).fetchone()
        if row and row[1] == digest:
            parts = conn.execute("SELECT parts, pages FROM documents WHERE id = ?", (row[0],)).fetchone()
            return {"status": "unchanged", "name": path.name, "parts": parts[0], "pages": parts[1]}
    pieces = parse(path)
    parts = chunk(pieces)
    if not parts:
        return {"status": "empty", "name": path.name, "parts": 0, "pages": None}
    pages = len(pieces) if path.suffix.lower() == ".pdf" else None
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    with _lock, _connect() as conn:
        old = conn.execute("SELECT id FROM documents WHERE path = ?", (key,)).fetchone()
        if old:
            conn.execute("DELETE FROM documents WHERE id = ?", (old[0],))
        doc_id = conn.execute(
            "INSERT INTO documents (path, name, sha256, added, pages, parts, chars) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, path.name, digest, stamp, pages, len(parts), sum(len(p["text"]) for p in parts))).lastrowid
        for n, part in enumerate(parts, 1):
            vector = embed(part["text"])
            conn.execute("INSERT INTO parts (doc_id, n, page, text, vector, length) VALUES (?, ?, ?, ?, ?, ?)",
                         (doc_id, n, part["page"], part["text"], json.dumps(vector), sum(vector.values())))
    log(f"knowledge: {'updated' if old else 'added'} a document ({len(parts)} parts)")
    return {"status": "updated" if old else "added", "name": path.name, "parts": len(parts), "pages": pages}


def documents() -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT id, name, path, added, pages, parts, chars FROM documents ORDER BY name").fetchall()
    return [{"id": r[0], "name": r[1], "path": r[2], "added": r[3], "pages": r[4], "parts": r[5], "chars": r[6]}
            for r in rows]


def remove(name: str) -> list[str]:
    """Take documents out by file name (or path), exactly. Returns the
    names removed. The files themselves are untouched."""
    wanted = str(name or "").strip().strip("\"'")
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT id, name, path FROM documents").fetchall()
        hits = [r for r in rows if wanted and (r[1].lower() == wanted.lower() or r[2] == wanted)]
        for r in hits:
            conn.execute("DELETE FROM documents WHERE id = ?", (r[0],))
    return [r[1] for r in hits]


# ---------------------------------------------------------------- retrieve

def retrieve(question: str, top: int = TOP) -> list[dict]:
    """The parts that best answer the question, best first, each with its
    score, how much of the question it holds, and its source. Empty when no
    part holds MIN_COVERAGE of the question's words."""
    wanted = set(terms(question))
    words = {t for t in wanted if "_" not in t}
    if not words:
        return []
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT p.id, p.n, p.page, p.text, p.vector, p.length, d.name "
                            "FROM parts p JOIN documents d ON d.id = p.doc_id").fetchall()
    if not rows:
        return []
    vectors = [json.loads(r[4]) for r in rows]
    count = len(rows)
    average = sum(r[5] for r in rows) / count or 1
    df = Counter(t for v in vectors for t in wanted if t in v)
    found = []
    for row, vector in zip(rows, vectors):
        coverage = len(words & vector.keys()) / len(words)
        if coverage < MIN_COVERAGE:
            continue
        score = 0.0
        for term in wanted & vector.keys():
            idf = math.log(1 + (count - df[term] + 0.5) / (df[term] + 0.5))
            tf = vector[term]
            score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * row[5] / average))
        found.append({"score": round(score, 3), "coverage": round(coverage, 2), "name": row[6],
                      "page": row[2], "n": row[1], "text": row[3]})
    found.sort(key=lambda f: -f["score"])
    return found[:top]


def _parts(n: int) -> str:
    return f"{n} part{'' if n == 1 else 's'}"


def _source(part: dict) -> str:
    return f"{part['name']}, page {part['page']}" if part["page"] else f"{part['name']}, part {part['n']}"


# ------------------------------------------------------------------ answer

ANSWER = """Answer the question using ONLY the numbered excerpts from the user's own documents.

Question: {question}

Excerpts:
{excerpts}

Reply with one JSON object and nothing else:
{{"facts": [{{"text": "one statement taken from the excerpts", "sources": [excerpt numbers]}}],
  "suggestion": "anything you add that is NOT in the excerpts, or an empty string"}}
Every fact must be stated in the excerpts and cite them. If the excerpts don't answer the question,
give no facts. Don't put your own advice in facts."""


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if w not in STOP and len(w) > 1}


def supported(fact: str, parts: list[dict]) -> bool:
    """Do the cited parts hold most of the fact's words? A fact the parts
    don't hold is the model's, whatever it says."""
    said = _words(fact)
    if not said or not parts:
        return False
    held = _words(" ".join(p["text"] for p in parts))
    return len(said & held) / len(said) >= FACT_SUPPORT


def answer(question: str) -> dict:
    """{"facts": [{"text", "sources": [str]}], "suggestion": str,
    "retrieved": [part], "note": str}. Every fact is checked against the
    parts it cites; one that fails becomes part of the suggestion."""
    from ..ai.provider import ask_text
    parts = retrieve(question)
    if not parts:
        return {"facts": [], "suggestion": "", "retrieved": [], "note": "nothing"}
    excerpts = "\n\n".join(f"[{i}] ({_source(p)})\n{p['text']}" for i, p in enumerate(parts, 1))
    try:
        raw = ask_text(ANSWER.format(question=question.strip(), excerpts=excerpts), empty="")
    except Exception as e:  # noqa: BLE001
        return {"facts": [], "suggestion": "", "retrieved": parts, "note": f"unreachable: {e}"}
    match = re.search(r"\{.*\}", raw or "", re.S)
    try:
        said = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        said = None
    if not isinstance(said, dict):
        return {"facts": [], "suggestion": "", "retrieved": parts, "note": "unreadable"}
    facts, unbacked = [], []
    for fact in said.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        text = " ".join(str(fact.get("text") or "").split())
        cited = [n for n in fact.get("sources") or [] if isinstance(n, int) and 1 <= n <= len(parts)]
        if text and cited and supported(text, [parts[n - 1] for n in cited]):
            facts.append({"text": text, "sources": [_source(parts[n - 1]) for n in dict.fromkeys(cited)]})
        elif text:
            unbacked.append(text)
    suggestion = " ".join([" ".join(str(said.get("suggestion") or "").split())] + unbacked).strip()
    return {"facts": facts, "suggestion": suggestion, "retrieved": parts, "note": ""}


# ------------------------------------------------------------------- tools

def _resolve(path: str) -> Path:
    from ..tools.workspace import safe_path
    return safe_path(str(path or "").strip().strip("\"'"))


def add_document(path: str) -> str:
    """The tool: add a file, or every readable file in a folder, to the
    knowledge base."""
    if not str(path or "").strip():
        return "Tell me which file or folder to add."
    try:
        target = _resolve(path)
    except Exception as e:  # noqa: BLE001
        return str(e)
    if not target.exists():
        return f"I can't find {target}."
    if target.is_dir():
        from ..tools.workspace import SKIP_DIRS
        files = [f for f in sorted(target.rglob("*")) if f.is_file() and f.suffix.lower() in SUFFIXES
                 and not any(part in SKIP_DIRS for part in f.relative_to(target).parts)]
        if not files:
            return f"Nothing in {target.name} I can read into the knowledge base."
        done, problems = Counter(), []
        for f in files[:MAX_FILES]:
            try:
                done[add_file(f)["status"]] += 1
            except (ValueError, OSError) as e:
                problems.append(f"{f.name}: {e}")
        said = ", ".join(f"{n} {status}" for status, n in done.items()) or "none added"
        more = f" I stopped at {MAX_FILES} files." if len(files) > MAX_FILES else ""
        trouble = f" Couldn't read {len(problems)}: {'; '.join(problems[:3])}." if problems else ""
        return f"From {target.name}: {said}.{more}{trouble}"
    try:
        result = add_file(target)
    except (ValueError, OSError) as e:
        return str(e)
    pages = f"{result['pages']} pages, " if result["pages"] else ""
    return {
        "added": f"Added {result['name']} to your knowledge base ({pages}{_parts(result['parts'])}).",
        "updated": f"Updated {result['name']}: it had changed, so it's read again ({pages}{_parts(result['parts'])}).",
        "unchanged": f"{result['name']} is already in your knowledge base, unchanged.",
        "empty": f"{result['name']} has no text I can read, so nothing was added.",
    }[result["status"]]


def list_documents() -> str:
    found = documents()
    if not found:
        return "Your knowledge base is empty. Say: add notes.pdf to my knowledge base."
    return f"{len(found)} document{'' if len(found) == 1 else 's'}: " + "; ".join(
        f"{d['name']} ({str(d['pages']) + ' pages, ' if d['pages'] else ''}{_parts(d['parts'])})" for d in found) + "."


def remove_document(name: str) -> str:
    gone = remove(name)
    if not gone:
        return f"No document called {name} in your knowledge base."
    return f"Removed {', '.join(gone)} from your knowledge base. The file itself is untouched."


def search_documents(query: str) -> str:
    """The tool: the passages that match, with sources. No model."""
    parts = retrieve(query)
    if not parts:
        return f"Nothing in your documents matches “{query.strip()}”."
    return "\n".join(f"RETRIEVED [{_source(p)}]: {p['text'][:400]}" for p in parts)


def ask_documents(question: str) -> str:
    """The tool and the command: answer from your documents, with what was
    retrieved kept apart from what the model added."""
    if not documents():
        return "Your knowledge base is empty. Say: add notes.pdf to my knowledge base."
    said = answer(question)
    if said["note"] == "nothing":
        return "Nothing in your documents answers that. I didn't guess."
    lines = [f"RETRIEVED FACT: {f['text']} [{'; '.join(f['sources'])}]" for f in said["facts"]]
    if said["note"]:
        lines.append("I couldn't get an answer from the model, so here are the passages that match:")
        lines += [f"RETRIEVED [{_source(p)}]: {p['text'][:400]}" for p in said["retrieved"]]
    elif not said["facts"]:
        lines.append("The passages I found don't answer it: " + "; ".join(_source(p) for p in said["retrieved"]) + ".")
    if said["suggestion"]:
        lines.append(f"GENERATED SUGGESTION (the model's own, not in your documents): {said['suggestion']}")
    return "\n".join(lines)
