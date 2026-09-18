from __future__ import annotations

import difflib
import re


def _normalize_key(name: str) -> str:
    return re.sub(r"[\s\-_]+", " ", name.strip().lower())


def canonicalize_name(name: str, known_names: list[str], cutoff: float = 0.8) -> str:
    """Deterministic, local — no API call. Corrects "Pull Ups" / "pull-ups" /
    "Pullups" into whatever name is already established in the logs, so
    repeat entries don't fragment into separate things trend tracking can't
    reconcile. Not AI: this runs *after* the LLM parse, as a safety net."""
    if not known_names:
        return name
    lookup = {_normalize_key(n): n for n in known_names}
    matches = difflib.get_close_matches(_normalize_key(name), list(lookup.keys()), n=1, cutoff=cutoff)
    return lookup[matches[0]] if matches else name


def canonicalize_entries(entries: list[dict], log_store) -> None:
    """Applies canonicalize_name() to exercise/substance names in place, using
    history from the given log_store. Shared by the journal parse endpoint and
    the general drop endpoint so both get the same name-drift correction."""
    if log_store is None:
        return
    known_exercises = sorted({e["exercise_name"] for e in log_store.all_entries("exercise")})
    known_substances = sorted({e["substance"] for e in log_store.all_entries("substance")})
    for entry in entries:
        if entry["type"] == "exercise":
            entry["exercise_name"] = canonicalize_name(entry["exercise_name"], known_exercises)
        elif entry["type"] == "substance":
            entry["substance"] = canonicalize_name(entry["substance"], known_substances)
