"""Deterministic relative-date resolution for journal/drop parses (2026-11-11).

Live tests caught "yesterday I spent $15 on lunch" (reference 2026-11-10)
coming back with entry_date None from BOTH the local model and Claude.
Which calendar day "yesterday" is relative to a known reference date is
arithmetic, not judgment — so code resolves it after the parse and the
model's answer for these words is never trusted.

Phrases handled (case-insensitive, whole words): "the day before
yesterday", "yesterday", "last night" (-> the day before), "today", "this
morning/afternoon/evening", "tonight", "last <weekday>" (the most recent
such weekday strictly before the reference day; "last Tuesday" said on a
Tuesday is 7 days back), "N days ago" (digits or one..ten, plus "a day ago").

Deliberately NOT here: numeric shorthand like "8/10" / "8-10" — that is how
the old date-signal regex misread a mood score as Aug 10. Absolute dates
("on August 3rd") stay with the model's second date pass in llm.py.

THE application rule (one, simple):
  1. The text is cut into segments (sentences, then commas / "and" / "but"
     / "then"). A segment's date is the last relative phrase seen at or
     before it — a date stated earlier carries forward ("yesterday I ran
     5k and had a burrito" puts BOTH on yesterday) until another phrase
     replaces it.
  2. Each dateable entry is matched to the segment that best shares its
     words (description / merchant / amount / ...). If that segment has a
     date, the entry gets it — overriding whatever the model said.
  3. Spill-over: when the whole text holds exactly ONE relative phrase,
     entries that couldn't be placed in a dated segment also get that date,
     but only if the model left them undated (None / the reference day) —
     a lone "yesterday" sets the dump's day, yet never clobbers a date the
     model resolved from something else.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_NUM_WORDS = {
    "a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

RELATIVE_DATE_RE = re.compile(
    r"\b(?:"
    r"(?P<dby>(?:the\s+)?day\s+before\s+yesterday)"
    r"|(?P<yesterday>yesterday|last\s+night)"
    r"|(?P<today>today|tonight|this\s+(?:morning|afternoon|evening))"
    r"|last\s+(?P<weekday>" + "|".join(_WEEKDAYS) + r")"
    r"|(?P<n>\d{1,3}|" + "|".join(_NUM_WORDS) + r")\s+days?\s+ago"
    r")\b",
    re.IGNORECASE,
)


def _resolve(m: re.Match, ref: date) -> date:
    if m.group("dby"):
        return ref - timedelta(days=2)
    if m.group("yesterday"):
        return ref - timedelta(days=1)
    if m.group("today"):
        return ref
    if m.group("weekday"):
        target = _WEEKDAYS.index(m.group("weekday").lower())
        back = (ref.weekday() - target) % 7 or 7
        return ref - timedelta(days=back)
    n = m.group("n").lower()
    return ref - timedelta(days=int(n) if n.isdigit() else _NUM_WORDS[n])


def find_relative_dates(text: str, ref: date) -> list[tuple[int, int, date]]:
    """(start, end, resolved date) for every relative-date phrase in text."""
    return [(m.start(), m.end(), _resolve(m, ref)) for m in RELATIVE_DATE_RE.finditer(text or "")]


_SENTENCE_SPLIT = re.compile(r"[.!?;\n]+")
_SEGMENT_SPLIT = re.compile(r",|\b(?:and|but|then)\b", re.IGNORECASE)


def _segments(text: str, ref: date) -> list[tuple[str, date | None]]:
    """Text cut into (segment, carried date) pairs — see rule 1 above."""
    out: list[tuple[str, date | None]] = []
    current: date | None = None
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        for seg in _SEGMENT_SPLIT.split(sentence):
            if not seg.strip():
                continue
            found = find_relative_dates(seg, ref)
            if found:
                current = found[-1][2]
            out.append((seg, current))
    return out


_STOP = {"the", "and", "for", "with", "had", "was", "did", "got", "some", "this", "that", "from", "spent", "paid", "on", "at"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 3 and t not in _STOP}


def _tok_match(a: str, b: str) -> bool:
    return a == b or (len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4])


def _amount_strings(amount) -> set[str]:
    if amount in (None, ""):
        return set()
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return set()
    out = {f"{value:.2f}"}
    if value == int(value):
        out.add(str(int(value)))
    return out


def _label_text(entry) -> tuple[str, set[str]]:
    get = entry.get if isinstance(entry, dict) else (lambda k, d=None: getattr(entry, k, d))
    words = " ".join(
        str(get(k) or "") for k in ("description", "exercise_name", "substance", "merchant", "category", "metric", "notes")
    )
    return words, _amount_strings(get("amount"))


def _score(entry, segment: str) -> int:
    words, amounts = _label_text(entry)
    seg_tokens = _tokens(segment)
    score = sum(1 for t in _tokens(words) if any(_tok_match(t, s) for s in seg_tokens))
    seg_numbers = set(re.findall(r"\d+(?:\.\d+)?", segment))
    score += 2 * len(amounts & seg_numbers)
    return score


def apply_relative_dates(entries: list, raw_text: str, ref: date) -> None:
    """Sets entry_date in place on entries that have the attribute/key
    (pydantic models or dicts); todos (due_date) are left to the model."""
    phrases = find_relative_dates(raw_text, ref)
    if not phrases:
        return
    segments = _segments(raw_text, ref)
    single = phrases[0][2] if len(phrases) == 1 else None

    def get_date(e):
        return e.get("entry_date") if isinstance(e, dict) else getattr(e, "entry_date", None)

    def set_date(e, value: str) -> None:
        if isinstance(e, dict):
            e["entry_date"] = value
        else:
            e.entry_date = value

    for entry in entries:
        if not (("entry_date" in entry) if isinstance(entry, dict) else hasattr(entry, "entry_date")):
            continue
        best_score, best_date = 0, None
        for seg, seg_date in segments:
            s = _score(entry, seg)
            if s > best_score:
                best_score, best_date = s, seg_date
        if best_date is not None:
            set_date(entry, best_date.isoformat())
        elif single is not None and get_date(entry) in (None, "", ref.isoformat()):
            set_date(entry, single.isoformat())
