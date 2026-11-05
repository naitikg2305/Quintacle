"""The hard fact rule, enforced in code (same rule as TailorCV): employers,
titles, dates, degrees and metrics in a drafted bullet come only from the
existing record entry or the source log lines — the model never invents.

Checks (all deterministic; a bullet failing any is REJECTED, with reasons):

- every number (digits, incl. decimals / percentages / year parts of dates)
  and every spelled-out number word must occur in the corpus;
- every month name must occur in the corpus (any spelling of that month);
- every known employer/institution (Career hub titles + names the record
  states) must occur in the corpus;
- job-title words (Engineer, Intern, Architect...) and degree words
  (B.S., PhD, Master's...) must occur in the corpus.

Limitation (documented): an organisation the record has never heard of is
not detectable without NER — the reviewer remains the last gate for those.
"""
from __future__ import annotations

import re

from ...graph import title_mentioned

_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50", "hundred": "100",
    "thousand": "1000", "million": "1000000", "billion": "1000000000", "dozen": "12",
    "half": "0.5", "double": "2", "twice": "2", "triple": "3",
}
_MONTHS = [
    ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may", "may"),
    ("june", "jun"), ("july", "jul"), ("august", "aug"), ("september", "sep"), ("october", "oct"),
    ("november", "nov"), ("december", "dec"),
]
_TITLE_WORDS = (
    "intern", "engineer", "architect", "developer", "manager", "director", "analyst",
    "scientist", "consultant", "founder", "ceo", "cto", "senior", "associate", "president", "vp",
)
_DEGREE_RE = re.compile(r"\b(?:B\.?S\.?|M\.?S\.?|B\.?A\.?|M\.?A\.?|Ph\.?D\.?|MBA|bachelor'?s?|master'?s|masters|doctorate|degree)(?=\W|$)", re.IGNORECASE)


def _numbers(text: str) -> set[str]:
    text = _THOUSANDS_RE.sub("", text)
    out = set()
    for tok in _NUMBER_RE.findall(text):
        if "." in tok:
            out.add(tok.rstrip("0").rstrip(".") if tok.rstrip("0").rstrip(".") else "0")
        else:
            out.add(str(int(tok)))
    return out


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z']+", text.lower()))


def _months_in(text: str, *, capitalized_only: bool) -> set[int]:
    found = set()
    for i, (full, abbr) in enumerate(_MONTHS):
        flags = 0 if capitalized_only else re.IGNORECASE
        pat = rf"\b(?:{full.capitalize()}|{abbr.capitalize()})\b\.?" if capitalized_only else rf"\b(?:{full}|{abbr})\b"
        if re.search(pat, text, flags):
            found.add(i)
    return found


def check_bullet(text: str, corpus: str, employers: set[str] | list[str]) -> list[str]:
    """Reasons the bullet breaks the fact rule; [] = OK. `corpus` = the
    source log lines + the target entry's existing text."""
    reasons: list[str] = []
    corpus_numbers = _numbers(corpus)
    corpus_words = _words(corpus)
    for word, digit in _NUMBER_WORDS.items():
        if word in corpus_words:
            corpus_numbers.add(digit)

    missing = sorted(n for n in _numbers(text) if n not in corpus_numbers)
    if missing:
        reasons.append(f"number(s) not in the sources or record: {', '.join(missing)}")
    words = _words(text)
    for word, digit in _NUMBER_WORDS.items():
        if word in words and word not in corpus_words and digit not in corpus_numbers:
            reasons.append(f"number word not in the sources or record: {word}")

    # "May" doubles as a verb, so the bullet side only counts capitalized
    # month names; the corpus side accepts any case.
    corpus_months = _months_in(corpus, capitalized_only=False)
    for m in sorted(_months_in(text, capitalized_only=True) - corpus_months):
        reasons.append(f"date/month not in the sources or record: {_MONTHS[m][0].capitalize()}")

    for name in sorted(set(employers)):
        if name and title_mentioned(name, text) and not title_mentioned(name, corpus):
            reasons.append(f"employer/organisation not in the sources or record: {name}")

    for word in _TITLE_WORDS:
        if re.search(rf"\b{word}s?\b", text, re.IGNORECASE) and not re.search(rf"\b{word}s?\b", corpus, re.IGNORECASE):
            reasons.append(f"job title word not in the sources or record: {word}")

    corpus_degrees = {d.lower().replace(".", "") for d in _DEGREE_RE.findall(corpus)}
    for d in _DEGREE_RE.findall(text):
        if d.lower().replace(".", "") not in corpus_degrees:
            reasons.append(f"degree not in the sources or record: {d}")
    return reasons
