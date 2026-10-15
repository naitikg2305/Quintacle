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


def expand_routine_mentions(entries: list[dict], raw_text: str, known_routines: list[dict]) -> None:
    """Deterministic safety net for the prompt rule "a known routine mentioned
    by name -> one exercise entry per routine exercise": cloud models follow
    the instruction, small local models reliably don't — and whether "pull
    day" names a known preset is string matching, not judgment, so code does
    it. Runs after any parse (both providers; a no-op when the model already
    expanded). Appends empty-set exercise entries (the user fills reps/weight,
    same contract as the prompt rule) and never duplicates an exercise the
    parse already produced."""
    from ...graph import title_mentioned

    existing = {e.get("exercise_name", "").strip().lower() for e in entries if e.get("type") == "exercise"}
    for routine in known_routines or []:
        name = (routine.get("name") or "").strip()
        if not name or not title_mentioned(name, raw_text):
            continue
        for exercise_name in routine.get("exercises") or []:
            if exercise_name.strip().lower() in existing:
                continue
            existing.add(exercise_name.strip().lower())
            entries.append(
                {
                    "type": "exercise",
                    "exercise_name": exercise_name,
                    "sets": [],
                    "notes": f"from routine '{name}'",
                    "entry_date": None,
                }
            )
