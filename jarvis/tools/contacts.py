"""Bulk-import contacts instead of adding them one at a time.

Works with a Google Contacts CSV export (contacts.google.com, Export,
Google CSV or Outlook CSV) and with a .vcf vCard file, which is what a
phone exports. Only names and phone numbers are kept.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from ..store import memory
from ..app.config import MEMORY_DIR, log

NAME_COLUMNS = ("name", "display name", "first name", "given name", "organization name")
PHONE_HINT = re.compile(r"phone|mobile|number", re.I)
# Google's CSV has both "Phone 1 - Type" and "Phone 1 - Value"; only the
# second holds digits, so the type columns have to be ruled out.
PHONE_LABEL = re.compile(r"type|label", re.I)
DIGITS = re.compile(r"[^\d+]")


def _clean_number(raw: str, default_code: str = "+91") -> str | None:
    """Turn whatever the file holds into something WhatsApp accepts."""
    number = DIGITS.sub("", (raw or "").split(":::")[0].strip())
    if not number:
        return None
    if number.startswith("+"):
        digits = number[1:]
    elif number.startswith("00"):
        digits = number[2:]
    elif len(number) == 10:              # a bare Indian mobile
        digits = default_code.lstrip("+") + number
    elif number.startswith("0") and len(number) == 11:
        digits = default_code.lstrip("+") + number[1:]
    else:
        digits = number
    return "+" + digits if 10 <= len(digits) <= 15 else None


def _rows_from_csv(text: str) -> list[tuple[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    found: list[tuple[str, str]] = []
    for row in reader:
        lower = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        name = next((lower[c] for c in NAME_COLUMNS if lower.get(c)), "")
        if not name:
            name = " ".join(filter(None, [lower.get("first name", ""), lower.get("last name", "")]))
        phones = [v for k, v in lower.items()
                  if PHONE_HINT.search(k) and not PHONE_LABEL.search(k) and v]
        phone = next((p for p in phones if any(c.isdigit() for c in p)), "")
        if name:
            found.append((name, phone))   # a blank number is counted as skipped
    return found


def _rows_from_vcard(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    name = ""
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("FN:"):
            name = line[3:].strip()
        elif line.upper().startswith("TEL") and ":" in line:
            phone = line.split(":", 1)[1]
            if name and phone:
                found.append((name, phone))
        elif line.upper() == "END:VCARD":
            name = ""
    return found


def import_contacts(path: str, country_code: str = "+91") -> str:
    """Load a contacts file so you can say people's names instead of numbers."""
    file = Path(path).expanduser()
    if not file.exists():
        # Be forgiving: look in the usual places before giving up.
        for folder in (Path.home() / "Downloads", Path.home() / "Documents", MEMORY_DIR):
            guess = folder / file.name
            if guess.exists():
                file = guess
                break
        else:
            return f"I couldn't find {path}. Put the file in your Downloads folder and try again."

    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"I couldn't read that file: {e}"

    rows = _rows_from_vcard(text) if file.suffix.lower() == ".vcf" else _rows_from_csv(text)
    if not rows:
        return ("I read the file but found no names with phone numbers in it. "
                "Export again as Google CSV or vCard.")

    book = memory.contacts()
    added = skipped = 0
    for name, phone in rows:
        number = _clean_number(phone, country_code)
        if not number:
            skipped += 1
            continue
        key = name.lower().strip()
        if key and book.get(key) != number:
            book[key] = number
            added += 1

    memory._save(memory.CONTACTS, book)
    log(f"imported {added} contacts from {file.name}, skipped {skipped}")
    note = f" Skipped {skipped} without a usable number." if skipped else ""
    if not added:
        return f"Those {len(rows)} contacts were already saved.{note}"
    return f"Imported {added} contacts. You can now say their names.{note}"


def find_contacts(query: str) -> str:
    """Search your saved contacts by part of a name."""
    book = memory.contacts()
    q = query.lower().strip()
    hits = [f"{name}: {number}" for name, number in book.items() if q in name]
    if not hits:
        return f"No saved contact matches '{query}'. You have {len(book)} contacts saved."
    return "\n".join(sorted(hits)[:25])


def count_contacts() -> str:
    """How many contacts are saved."""
    return f"You have {len(memory.contacts())} contacts saved."
