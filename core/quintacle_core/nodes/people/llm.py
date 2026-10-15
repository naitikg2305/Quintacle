from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel

from ... import clock
from ...llm_dispatch import parse_structured

PERSON_CATEGORIES = ("friend", "dating", "family", "coworker", "acquaintance", "other")


class PersonEstimate(BaseModel):
    suggested_name: str
    category: str
    how_met: str = ""
    met_date: str | None = None
    notes: str = ""


_STRUCTURE_SYSTEM_PROMPT = (
    "Structure this into a person entry for a personal relationship tracker: suggested_name (their "
    f"name), category (one of {', '.join(PERSON_CATEGORIES)}, or another short lowercase word if "
    "none fit), how_met (a short description of how/where you met, if stated), met_date (YYYY-MM-DD "
    "if stated), and notes (what's worth remembering about them — interests, job, how things are "
    "going, whatever was said)."
)


def structure_person(description: str, reference_date: date | None = None, provider: str | None = None) -> PersonEstimate:
    """For the explicit "person:"/"friend:" prefix — intent already stated,
    so no relevance gate, always extracts fields."""
    ref = reference_date or clock.today()
    result = parse_structured(
        _STRUCTURE_SYSTEM_PROMPT
        + f"\n\nReference date (resolve relative dates like \"today\"/\"last week\" against this): {ref.isoformat()}",
        description,
        PersonEstimate,
        provider=provider,
        max_tokens=1024,
    )
    return result.parsed


# Deterministic, local, no API call — same two-signal shape as travel/llm.py's
# _EXPERIENCE_SIGNAL_RE, but a person mention has two genuinely different
# triggers: introducing someone brand new (a fixed keyword pattern works,
# same reasoning as Experience — a missed match silently loses a contact
# forever, a false match just costs one cheap call) vs. saying something new
# about someone ALREADY tracked (which can't be keyword-matched in advance —
# it has to check the actual known-names list, built fresh per request).
_NEW_PERSON_SIGNAL_RE = re.compile(
    r"\b("
    r"met|new friend|introduced (?:me|us)|coworker named|classmate named|"
    r"her name is|his name is|their name is|went on a date with|"
    r"matched with|swiped|first date"
    r")\b",
    re.IGNORECASE,
)


def _known_name_re(known_names: list[str]) -> re.Pattern | None:
    escaped = [re.escape(n) for n in known_names if n.strip()]
    if not escaped:
        return None
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)


class PersonMentionEstimate(BaseModel):
    is_person_mention: bool
    is_new_person: bool = False
    person_name: str = ""
    category: str = ""
    how_met: str = ""
    met_date: str | None = None
    notes: str = ""


_MENTION_SYSTEM_PROMPT = (
    "Decide whether this text says something SUBSTANTIVE and worth remembering about a specific "
    "person — a fact you learned, how a date/hangout went, a life update — not just a passing "
    "mention with no real content (\"talked to mom\" alone isn't substantive; \"mom said she's "
    "considering retiring next year\" is). If genuinely not, set is_person_mention false and leave "
    "the rest blank.\n\n"
    "If it IS: check whether the person matches one of the known people below (fuzzy match on "
    "name — a nickname or first-name-only is fine) — if so, set is_new_person false and "
    "person_name to their EXACT name from the list. If they're not in the list, set is_new_person "
    "true, person_name to their name as stated, and fill in category/how_met/met_date if inferable. "
    "In both cases, notes is the specific substantive thing learned, written as a short standalone "
    "note — not a restatement of the whole input."
)


def maybe_structure_person_mention(
    description: str, known_names: list[str], reference_date: date | None = None, provider: str | None = None
) -> PersonMentionEstimate | None:
    """Two-tier gate, same shape as travel's maybe_structure_experience(): a
    free local pre-filter first (either signal), then — only if that
    matches — one AI call that decides relevance AND extracts fields in a
    single pass. Used for the ADDITIVE "propose everything plausible" check
    on drops/journal entries that already classified as something else."""
    known_re = _known_name_re(known_names)
    if not (_NEW_PERSON_SIGNAL_RE.search(description) or (known_re and known_re.search(description))):
        return None
    ref = reference_date or clock.today()
    library = "Known people: " + ", ".join(known_names) if known_names else "Known people: (none tracked yet)"
    result = parse_structured(
        _MENTION_SYSTEM_PROMPT
        + f"\n\nReference date (resolve relative dates like \"today\"/\"last week\" against this): {ref.isoformat()}"
        + "\n\n"
        + library,
        description,
        PersonMentionEstimate,
        provider=provider,
        max_tokens=1024,
    )
    estimate = result.parsed
    return estimate if estimate.is_person_mention else None
