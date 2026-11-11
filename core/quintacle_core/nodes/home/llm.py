from __future__ import annotations

import re

from pydantic import BaseModel

from ...llm_dispatch import parse_structured

_CATEGORIES = "furniture, decor, electronics, kitchen, appliance, storage, or another short lowercase category"


class HomeItemEstimate(BaseModel):
    suggested_name: str
    category: str
    location: str = ""  # room/container it's kept in, e.g. "closet, box 3" — empty if not stated
    purchase_price: float | None = None
    purchase_date: str | None = None  # YYYY-MM-DD if stated
    residence_name: str | None = None  # only if the text specifies WHICH home — else defaults to current
    notes: str = ""


def structure_home_item(description: str, known_residences: list[str], provider: str | None = None) -> HomeItemEstimate:
    """Same pattern as documents/llm.py's structure_document() — takes an
    already-extracted description (vision/PDF/DOCX/typed, via kb/drop.py's
    describe_drop) and structures it into a home inventory entry."""
    residence_hint = (
        f"Known residences: {', '.join(known_residences)}. Only set residence_name if the text "
        "clearly refers to one of these (or explicitly names a different, new one) — leave it "
        "null otherwise, it'll default to your current home."
        if known_residences
        else "No residences saved yet — leave residence_name null unless one is explicitly named."
    )
    result = parse_structured(
        (
            "Turn this into a home inventory item: a short suggested_name, category "
            f"({_CATEGORIES}), location (which room/container it's kept in, e.g. 'closet, box 3' "
            "— empty if not stated), purchase_price and purchase_date (YYYY-MM-DD) if stated, "
            f"and brief notes (what it is, why you got it). {residence_hint} "
            "Use ONLY what the text says — never invent. Leave every field the text doesn't "
            "state empty/null: no guessed price, no guessed room, no made-up month or day (if "
            "only a year is given, use YYYY-01-01). Keep stated facts such as a warranty, model "
            "or serial number in the notes; don't add marketing copy or opinions."
        ),
        description,
        HomeItemEstimate,
        provider=provider,
        max_tokens=512,
    )
    return guard_home_item(result.parsed, description)


# --- Deterministic anti-invention guard. 2026-11-11 live finding: local
# qwen3:8b made up a $599.99 price, a "living room" location and a
# 2025-01-15 day for "Dyson V15 vacuum, bought 2025, warranty 2 years", and
# dropped the warranty. The prompt asks nicely; this code makes sure. ------

_MONEY_RE = re.compile(
    r"[$€£₹¥]\s*\d"
    r"|\d[\d,]*(?:\.\d+)?\s*(?:usd|eur|gbp|inr|dollars?|bucks|rs\.?|rupees?|euros?|pounds?)\b"
    r"|\b(?:usd|eur|gbp|inr|rs\.?)\s*\d"
    r"|\b(?:paid|cost|costs|price|priced)\s*:?\s*\d",
    re.IGNORECASE,
)
_WARRANTY_RE = re.compile(
    r"[^,;.\n]*\b(?:warrant(?:y|ies|eed)|guarantee[d]?|applecare)\b[^,;.\n]*",
    re.IGNORECASE,
)
_LOCATION_STOPWORDS = {"the", "a", "an", "in", "on", "at", "of", "and", "my", "under", "inside"}
_MONTHS = {
    name: i + 1
    for i, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
         ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
         ("oct", "october"), ("nov", "november"), ("dec", "december")]
    )
    for name in names
}


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def _location_supported(location: str, text: str) -> bool:
    """Every meaningful word of the location must appear in the text."""
    text_words = set(_words(text))
    loc_words = [w for w in _words(location) if w not in _LOCATION_STOPWORDS] or _words(location)
    return bool(loc_words) and all(w in text_words for w in loc_words)


def _supported_date(model_date: str, text: str) -> str | None:
    """Keep only as much of the model's date as the text backs: no year in
    the text -> None; the month must be stated (by name, or in a numeric date
    carrying that year) else the date becomes YYYY-01-01 (year-only); the day
    must sit next to that month else it becomes the 1st."""
    m = re.match(r"\s*(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", model_date or "")
    if not m:
        return None
    year = m.group(1)
    if not re.search(rf"(?<!\d){year}(?!\d)", text):
        return None
    month = int(m.group(2)) if m.group(2) else None
    day = int(m.group(3)) if m.group(3) else None
    low = text.lower()
    if month is not None and day is not None:
        numeric = (
            rf"(?<!\d){year}[-/.]0?{month}[-/.]0?{day}(?!\d)"
            rf"|(?<!\d)0?{month}[-/.]0?{day}[-/.]{year}(?!\d)"
            rf"|(?<!\d)0?{day}[-/.]0?{month}[-/.]{year}(?!\d)"
        )
        if re.search(numeric, text):
            return f"{year}-{month:02d}-{day:02d}"
    month_names = [n for n, v in _MONTHS.items() if v == month]
    month_hits = [mm for n in month_names for mm in re.finditer(rf"\b{n}\b", low)]
    if month is None or not (month_hits or re.search(rf"(?<!\d){year}[-/.]0?{month}(?!\d)|(?<!\d)0?{month}[-/.]{year}(?!\d)", text)):
        return f"{year}-01-01"
    if day is not None:
        for hit in month_hits:  # "15 Jan" / "Jan 15th"
            window = low[max(0, hit.start() - 6): hit.end() + 7]
            if re.search(rf"(?<!\d)0?{day}(?:st|nd|rd|th)?(?!\d)", window):
                return f"{year}-{month:02d}-{day:02d}"
    return f"{year}-{month:02d}-01"


def guard_home_item(est: HomeItemEstimate, text: str) -> HomeItemEstimate:
    """Drop every factual field the source text doesn't back and restore
    warranty phrases the model left out. Pure code, no model call."""
    if est.purchase_price is not None and not _MONEY_RE.search(text):
        est.purchase_price = None
    if (est.location or "").strip() and not _location_supported(est.location, text):
        est.location = ""
    if est.purchase_date:
        est.purchase_date = _supported_date(est.purchase_date, text)
    notes = (est.notes or "").strip()
    for hit in _WARRANTY_RE.finditer(text):
        phrase = hit.group(0).strip()
        if phrase and phrase.lower() not in notes.lower():
            phrase = phrase[0].upper() + phrase[1:]
            notes = f"{notes.rstrip('.')}. {phrase}." if notes else f"{phrase}."
    est.notes = notes
    return est


class ResidenceEstimate(BaseModel):
    suggested_name: str
    city: str
    address: str = ""
    moved_in: str | None = None
    moved_out: str | None = None
    notes: str = ""


def structure_residence(description: str, provider: str | None = None) -> ResidenceEstimate:
    result = parse_structured(
        (
            "Turn this into a residence/apartment record: a short suggested_name (e.g. 'Iris "
            "307' or 'Standard'), city, address if stated, moved_in and moved_out dates as "
            "YYYY-MM-DD if stated (moved_out null if still living there), and brief notes."
        ),
        description,
        ResidenceEstimate,
        provider=provider,
        max_tokens=512,
    )
    return result.parsed
