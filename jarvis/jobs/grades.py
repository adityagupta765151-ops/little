"""Marks, the way resumes and job postings write them.

A CGPA out of 10, a GPA out of 4, a percentage. Two rules hold everything
here together:

  Never convert between scales. Universities turn a CGPA into a percentage
  in different ways (x 9.5, x 10, a table), so 7.0/10 and 65% are not
  compared — the candidate is told the scales differ and to check.

  Never invent. A score read from a resume must be a number the resume
  actually contains; a cutoff read from a posting must be a number that
  sits next to a word like CGPA or marks, so "70% remote" or "7 LPA" is
  never mistaken for an academic bar.
"""
from __future__ import annotations

import re
from typing import NamedTuple

NUM = r"(\d{1,3}(?:\.\d{1,2})?)"
POINTS = r"(?:c\.?g\.?p\.?a|cpi|sgpa|gpa)"


class Grade(NamedTuple):
    value: float
    scale: int          # 10, 4 or 100


def _num(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def grade(text: str) -> Grade | None:
    """What a score written on a resume means: 7.0/10, 8.2 CGPA, 72%, 3.6/4
    GPA. None if it isn't a score this can read."""
    t = " ".join(str(text or "").lower().split())
    if not t:
        return None
    m = re.search(rf"(?<![\d.]){NUM}\s*(?:/|out of)\s*(10|4|100)(?:\.0+)?(?![\d.])", t)
    if m:
        value, scale = _num(m.group(1)), int(m.group(2))
        return Grade(value, scale) if value is not None and 0 < value <= scale else None
    m = re.search(rf"(?<![\d.]){NUM}\s*(?:%|percent|per cent)", t)
    if m:
        value = _num(m.group(1))
        return Grade(value, 100) if value is not None and 0 < value <= 100 else None
    m = re.search(rf"(?<![\d.]){NUM}(?![\d.])", t)
    if not m:
        return None
    value = _num(m.group(1))
    if value is None or value <= 0:
        return None
    if re.search(r"\b(c\.?g\.?p\.?a|cpi|sgpa)\b", t):
        return Grade(value, 10) if value <= 10 else None
    if re.search(r"\bgpa\b", t):
        return Grade(value, 4) if value <= 4 else (Grade(value, 10) if value <= 10 else None)
    if re.search(r"percent|percentage|marks|aggregate", t):
        return Grade(value, 100) if value <= 100 else None
    # A bare number: under 10 on an Indian resume is a CGPA, 10–100 a percentage.
    if value <= 10:
        return Grade(value, 10)
    return Grade(value, 100) if value <= 100 else None


def describe(g: Grade) -> str:
    value = f"{g.value:g}"
    return {10: f"{value} CGPA", 4: f"{value}/4 GPA"}.get(g.scale, f"{value}%")


def numbers_in(text: str) -> set[float]:
    """Every number in a text, as a value, so 7 and 7.0 are the same."""
    out = set()
    for raw in re.findall(r"(?<![\d.])\d{1,3}(?:\.\d{1,2})?(?![\d])", text or ""):
        value = _num(raw)
        if value is not None:
            out.add(value)
    return out


def stated_in(score: str, text: str) -> bool:
    """Is the score's own number actually in the resume's text? A score the
    text doesn't contain was made up, however plausible."""
    g = grade(score)
    return g is not None and g.value in numbers_in(text)


# ------------------------------------------------------ reading a resume

CLASS_12 = r"(?:class\s*(?:xii|12)(?:th)?|12th|xii\b|intermediate|senior secondary|\bhsc\b|\bisc\b|plus two|\+2)"
CLASS_10 = r"(?:class\s*(?:x|10)(?:th)?\b|10th|\bssc\b|\bicse\b|matric(?:ulation)?|high school|secondary school)"


def _line_score(line: str) -> str:
    """The score written on one line, as written, or ""."""
    m = (re.search(rf"{POINTS}\s*[:\-–=]?\s*(?:of\s*)?{NUM}(?:\s*/\s*(?:10|4)(?:\.0+)?)?", line, re.I)
         or re.search(rf"(?<![\d.]){NUM}\s*(?:/\s*(?:10|4)(?:\.0+)?)?\s*{POINTS}\b", line, re.I)
         or re.search(rf"(?<![\d.]){NUM}\s*(?:/\s*(?:10|4)(?:\.0+)?)", line, re.I)
         or re.search(rf"(?<![\d.]){NUM}\s*%", line, re.I)
         or re.search(rf"(?:percentage|marks|aggregate)\s*[:\-–=]?\s*{NUM}", line, re.I))
    if not m:
        return ""
    found = " ".join(m.group(0).split())
    return found if grade(found) else ""


def scores_in(text: str) -> dict[str, str]:
    """The degree score and Class 12 and 10 marks a resume states, found on
    this computer. Only an unambiguous line counts: a field with two
    different candidates is left empty rather than guessed."""
    found: dict[str, set[str]] = {"degree_score": set(), "class_12": set(), "class_10": set()}
    for line in (text or "").splitlines():
        score = _line_score(line)
        if not score:
            continue
        low = line.lower()
        is_12, is_10 = bool(re.search(CLASS_12, low)), bool(re.search(CLASS_10, low))
        if is_12 and not is_10:
            found["class_12"].add(score)
        elif is_10 and not is_12:
            found["class_10"].add(score)
        elif not is_12 and not is_10 and re.search(
                rf"{POINTS}|b\.?\s?tech|b\.?\s?e\b|bachelor|degree|graduat|b\.?sc|bca|mca|m\.?\s?tech|"
                r"university|college|institute", low):
            found["degree_score"].add(score)
    return {field: next(iter(values)) if len(values) == 1 else "" for field, values in found.items()}


# ------------------------------------------------------ reading a posting

class Cutoff(NamedTuple):
    kind: str           # "degree", "class_12", "class_10", "school" or "throughout"
    grade: Grade
    text: str           # the words it was read from


ACADEMIC = re.compile(
    rf"{POINTS}|percentage|marks|aggregate|academic|10th|12th|class\s*(?:x|xii|10|12)\b|"
    r"graduation|\bssc\b|\bhsc\b|throughout|b\.?\s?tech|b\.?\s?e\b|degree|eligib|criteria|cut-?off",
    re.I)
NOT_A_BAR = re.compile(r"\bno\s+(?:minimum\s+)?(?:cgpa|gpa|percentage|academic)\s*(?:cut-?off|criteria|bar|requirement)|"
                       r"(?:cgpa|percentage|gpa)\s+(?:is\s+)?not\s+(?:a\s+)?(?:criteria|criterion|required|mandatory|a bar)|"
                       r"no\s+(?:cgpa|percentage)\s+(?:criteria|bar)", re.I)
NOT_ACADEMIC = re.compile(r"remote|travel|hike|equity|discount|bonus|salary|ctc|lpa|stipend|growth|"
                          r"revenue|commission|off\b|uptime|accuracy|coverage|probability|increase", re.I)


DEGREE_WORDS = r"(?:graduation|graduate|b\.?\s?tech|b\.?\s?e\b|bachelor|degree|\bug\b|b\.?sc|bca|mca|m\.?\s?tech|engineering)"


def _which(words: str) -> str:
    """Which exams a few words name: "school" is Class 10 and 12 together."""
    w = words.lower()
    has_12, has_10 = bool(re.search(CLASS_12, w)), bool(re.search(CLASS_10, w))
    has_degree = bool(re.search(DEGREE_WORDS, w))
    if re.search(r"throughout|all academics?|entire academic|every (?:academic|exam)", w):
        return "throughout"
    if has_12 and has_10:
        return "throughout" if has_degree else "school"
    if has_12:
        return "class_12"
    if has_10:
        return "class_10"
    return "degree" if has_degree else ""


LISTED_ALL = re.compile(r"(?:10th|class\s*(?:x|10)|\bx)\s*,\s*(?:12th|class\s*(?:xii|12)|xii)\s*(?:,|and|&)\s*"
                        rf"{DEGREE_WORDS}", re.I)


def _kind(sentence: str, start: int, end: int) -> str:
    """What a bar applies to, from the words nearest it: "65% in 12th and 60%
    in graduation" is one bar for each, and so is "12th: 70%, B.Tech: 7
    CGPA". The words just after, up to a comma, win; then those just before,
    back to a comma or the previous bar; then the whole sentence. A bar that
    names nothing is the degree's."""
    bar = rf"(?<![\d.]){NUM}\s*(?:%|{POINTS})"
    after = re.split(bar, sentence[end:end + 50], maxsplit=1, flags=re.I)[0]
    before = re.split(bar, sentence[max(0, start - 50):start], flags=re.I)[-1]
    if LISTED_ALL.search(before + " " + after):          # "10th, 12th and graduation: 60%"
        return "throughout"
    for words in (after.split(",")[0], before.split(",")[-1], sentence):
        kind = _which(words)
        if kind:
            return kind
    return "degree"


def cutoffs(text: str) -> list[Cutoff]:
    """The academic bars a posting states: "CGPA of 7.5 and above", "7+ CGPA",
    "60% throughout", "minimum 65% in 12th". Money, remote-work and growth
    percentages are not bars, and a sentence saying there is no bar has none."""
    out: list[Cutoff] = []
    seen = set()
    for sentence in re.split(r"[.;\n•●▪·|]+(?=\s|$)|\n", text or ""):
        s = " ".join(sentence.split())
        if not s or not ACADEMIC.search(s) or NOT_A_BAR.search(s):
            continue
        found: list[tuple[str, Grade]] = []
        for pattern in (
                rf"{POINTS}\s*(?:of|:|-|>=|≥|>)?\s*(?:minimum|min\.?|at\s+least|above|over|of|atleast)?\s*(?:of\s+)?"
                rf"(?<![\d.]){NUM}(?:\s*/\s*(10|4)(?:\.0+)?)?(?![\d%])",
                rf"(?:minimum|min\.?|at\s+least|atleast|above|over)\s*(?:of\s+)?(?<![\d.]){NUM}"
                rf"(?:\s*/\s*(10|4)(?:\.0+)?)?\s*\+?\s*{POINTS}",
                rf"(?<![\d.]){NUM}(?:\s*/\s*(10|4)(?:\.0+)?)?\s*\+?\s*{POINTS}\b"):
            for m in re.finditer(pattern, s, re.I):
                value = _num(m.group(1))
                if value is None:
                    continue
                words = m.group(0).lower()
                if m.group(2):
                    scale = int(m.group(2))
                elif re.search(r"\bgpa\b", words) and not re.search(r"c\.?g\.?p\.?a|cpi|sgpa", words) and value <= 4:
                    scale = 4
                else:
                    scale = 10
                if 1 <= value <= scale:
                    found.append((m.group(0), Grade(value, scale)))
        for m in re.finditer(rf"(?<![\d.]){NUM}\s*%", s):
            value = _num(m.group(1))
            around = s[max(0, m.start() - 60): m.end() + 60]
            if value is None or not 33 <= value <= 100:
                continue
            if NOT_ACADEMIC.search(around) or not ACADEMIC.search(around):
                continue
            found.append((m.group(0), Grade(value, 100)))
        for words, g in found:
            at = s.lower().find(words.lower())
            kind = _kind(s, at, at + len(words))
            key = (kind, g)
            if key in seen:
                continue
            seen.add(key)
            out.append(Cutoff(kind, g, s[:120]))
    return out


LABELS = {"degree_score": "degree score", "class_12": "Class 12 marks", "class_10": "Class 10 marks"}
APPLIES_TO = {"degree": ("degree_score",), "class_12": ("class_12",), "class_10": ("class_10",),
              "school": ("class_10", "class_12"),
              "throughout": ("class_10", "class_12", "degree_score")}
WHERE = {"throughout": " throughout", "school": " in Class 10 and 12",
         "class_12": " in Class 12", "class_10": " in Class 10", "degree": ""}
MAX_CONCERNS = 3


def _is(label: str, negative: bool = False) -> str:
    plural = label.endswith("marks")
    return ("aren’t" if plural else "isn’t") if negative else ("are" if plural else "is")


def concerns(text: str, person: dict) -> list[str]:
    """What a posting's academic bars mean for this candidate, in plain
    words: below it, not stated on the resume, or on a different scale.
    Nothing when they meet it. Never a verdict — the job stays listed."""
    out: list[str] = []
    found = cutoffs(text)
    # "65% or 6.5 CGPA": alternatives in one sentence. Meeting one on your
    # own scale means the other, on a scale you can't compare, is no concern.
    met = set()
    for cut in found:
        for field in APPLIES_TO[cut.kind]:
            g = grade(str(person.get(field) or ""))
            if g and g.scale == cut.grade.scale and g.value >= cut.grade.value:
                met.add((cut.text, cut.kind, field))
    for cut in found:
        asks = describe(cut.grade) + WHERE[cut.kind]
        fields = APPLIES_TO[cut.kind]
        single = len(fields) == 1
        below, missing, other_scale = [], [], []
        for field in fields:
            mine = str(person.get(field) or "").strip()
            g = grade(mine) if mine else None
            if not mine:
                missing.append(field)
            elif g is None:
                continue
            elif g.scale != cut.grade.scale:
                if (cut.text, cut.kind, field) not in met:
                    other_scale.append((field, mine))
            elif g.value < cut.grade.value:
                below.append((field, mine))
        for field, mine in below:
            out.append(f"Asks for {asks}; your resume says {mine}" if single else
                       f"Asks for {asks}; your {LABELS[field]} {_is(LABELS[field])} {mine}")
        for field, mine in other_scale:
            out.append(f"Asks for {asks}; your {LABELS[field]} ({mine}) is on a different scale — "
                       f"check how your university converts it")
        if missing:
            labels = [LABELS[f] for f in missing]
            if len(missing) == len(fields):
                out.append(f"Asks for {asks}; your resume doesn't state your {' or '.join(labels)}")
            else:
                last = labels[-1]
                out.append(f"Asks for {asks}; your {' and '.join(labels)} "
                           f"{_is(last, True) if len(labels) == 1 else 'aren’t'} on your resume")
    unique: list[str] = []
    for item in out:
        if item not in unique:
            unique.append(item)
    return unique[:MAX_CONCERNS]
