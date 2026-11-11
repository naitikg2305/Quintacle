from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel

from ... import clock
from ...llm_dispatch import parse_structured

EXPERIENCE_KINDS = ("restaurant", "bar", "club", "activity", "historic", "other")
ExperienceKind = Literal["restaurant", "bar", "club", "activity", "historic", "other"]

# Deterministic, local, no API call — same principle as journal/llm.py's
# _DATE_SIGNAL_RE: only pay for the AI relevance check below when the text
# plausibly mentions a place/visit at all. An ordinary "logged today's
# weight" drop never touches this. Deliberately broad/permissive — a missed
# match means silently losing an experience with no recovery; a false match
# just costs one cheap Haiku call the AI's own is_experience judgment then
# correctly rejects (e.g. "had dinner, chicken and rice, 500kcal" — no place,
# no opinion — matches "dinner" here but the model still says not relevant).
_EXPERIENCE_SIGNAL_RE = re.compile(
    r"\b("
    r"restaurant|bar|caf[eé]|bistro|pub|brewery|diner|bakery|food\s*truck|"
    r"museum|park|tour|hik(?:e|ing)|bowling|(?:ice\s*)?skating|arcade|"
    r"attraction|landmark|exhibit|show|concert|club|lounge|"
    r"dinner|lunch|brunch|breakfast|drinks|dessert|"
    r"ate\s+at|went\s+to|visited|tried|checked\s+out|stopped\s+by|grabbed|hit\s+up|"
    r"trip|vacation|sightseeing"
    r")\b",
    re.IGNORECASE,
)


class ExperienceEstimate(BaseModel):
    is_experience: bool
    suggested_name: str = ""
    # A real constrained field, not just prompt wording — verified live that
    # prompt instruction alone wasn't reliable (the model drifted to
    # "nightclub"/"touristy_spot" instead of the exact "club"/"historic"),
    # which would silently break the frontend's exact-match kind filter.
    kind: ExperienceKind = "other"
    city: str = ""
    rating: str = ""  # short qualitative take, e.g. "loved it, would return"
    would_return: bool | None = None
    visited_date: str | None = None  # YYYY-MM-DD if stated
    notes: str = ""


_SYSTEM_PROMPT = (
    "Decide whether this text describes visiting a real-world place worth remembering — a "
    "restaurant, bar, club, activity, historic/touristy site, anything you'd want a record of "
    "later (not just a food/expense log entry, but the actual experience/place). If genuinely "
    "not (e.g. it's just describing a meal's macros with no place/opinion, or an unrelated "
    "topic), set is_experience false and leave the rest blank. If it IS, also give: "
    "suggested_name (the place/activity's name), kind — exactly one of restaurant, bar (a bar, "
    "not a nightclub), club (a nightclub/dance venue), activity (bowling, hiking, an "
    "amusement park, a class, anything you DO), historic (a museum, monument, landmark, historic "
    "site or building), or \"other\" if genuinely none of those fit — city (if stated), rating "
    "(a short qualitative take), would_return (true/false if it can be inferred), visited_date "
    "(YYYY-MM-DD if stated), and notes (what made it worth remembering)."
)


def _call_experience_model(description: str, provider: str | None = None) -> ExperienceEstimate:
    return parse_structured(_SYSTEM_PROMPT, description, ExperienceEstimate, provider=provider, max_tokens=512).parsed


def guard_experience(est: ExperienceEstimate, text: str, reference_date: date | None = None) -> ExperienceEstimate:
    """Keep only the facts the text actually states (2026-11-11: the local
    model turned "dinner at Compass" into "San Francisco, 2023-10-15").
    Pure code, the same rules as the home-item guard: a city only when its
    words are in the text; a visit date only when the text states it, either
    as a date or as one relative phrase ("yesterday", "last Friday")
    resolved against the reference date."""
    from ..home.llm import _location_supported, _supported_date
    from ..journal.relative_dates import find_relative_dates

    if (est.city or "").strip() and not _location_supported(est.city, text):
        est.city = ""
    if est.visited_date:
        stated = _supported_date(est.visited_date, text)
        if stated is None:
            rel = find_relative_dates(text, reference_date or clock.today())
            stated = rel[0][2].isoformat() if len(rel) == 1 else None
        est.visited_date = stated
    return est


def maybe_structure_experience(
    description: str, provider: str | None = None, reference_date: date | None = None
) -> ExperienceEstimate | None:
    """Two-tier gate: a free regex pre-filter first, then — only if that
    matches — one cheap AI call that both decides relevance AND extracts
    fields in a single pass (cheaper than a separate gate-then-extract pair
    of calls). Returns None whenever this isn't experience-worthy, so
    callers can just `if result: entries.append(...)`. Used for the
    ADDITIVE "propose everything plausible" check on drops that already
    classified as something else."""
    if not _EXPERIENCE_SIGNAL_RE.search(description):
        return None
    result = _call_experience_model(description, provider=provider)
    return guard_experience(result, description, reference_date) if result.is_experience else None


def structure_experience(
    description: str, provider: str | None = None, reference_date: date | None = None
) -> ExperienceEstimate:
    """For the explicit "experience:"/"visit:" prefix — intent is already
    stated deterministically, so no gate, no regex pre-filter: always
    extracts fields."""
    result = _call_experience_model(description, provider=provider)
    result.is_experience = True
    return guard_experience(result, description, reference_date)
