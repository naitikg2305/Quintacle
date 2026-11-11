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


def _item_tokens(name: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", name.lower())


def _same_token(a: str, b: str) -> bool:
    """Spelling variants of ONE word: equal, plural/singular, or a typo of
    a long word. Short tokens (sizes, SPF numbers, "XL") must match exactly."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(short) > 3 and long_ in (short + "s", short + "es"):
        return True
    return min(len(a), len(b)) > 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def same_item_name(a: str, b: str) -> bool:
    """True when two product/item names differ only in spelling — never when
    one has a distinguishing word the other lacks ("CeraVe Hydrating
    Cleanser" vs "CeraVe Foaming Cleanser", "SPF 30" vs "SPF 50")."""
    ta, tb = _item_tokens(a), _item_tokens(b)
    if not ta or not tb:
        return False
    if "".join(ta) == "".join(tb):  # "Ray-Ban" / "RayBan", "T-Shirt" / "Tshirt"
        return True
    return all(any(_same_token(x, y) for y in tb) for x in ta) and all(any(_same_token(y, x) for x in ta) for y in tb)


def canonicalize_item_name(name: str, known_names: list[str], cutoff: float = 0.8) -> str:
    """canonicalize_name for item LIBRARIES (wardrobe items, grooming
    products), 2026-11-11. Product names share most of their characters —
    brand + one descriptor + noun — so the plain 0.8 character-ratio merged
    "CeraVe Hydrating Cleanser" into the seeded "CeraVe Foaming Cleanser", a
    different product. Here a fuzzy candidate must ALSO pass a word-by-word
    check (same_item_name). Exercise/substance/meal canonicalization keeps
    the looser canonicalize_name — "Pull Ups" vs "Pullups" drift is what it
    exists for."""
    if not known_names:
        return name
    lookup = {_normalize_key(n): n for n in known_names}
    for match in difflib.get_close_matches(_normalize_key(name), list(lookup.keys()), n=5, cutoff=cutoff):
        if same_item_name(name, lookup[match]):
            return lookup[match]
    return name


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


_MEAL_SPLIT = re.compile(r"\s*(?:,|\+|&|/|\bplus\b|\band\b|\bwith\b|\balso\b|\bthen\b)\s*", re.IGNORECASE)
_MEAL_LEAD = re.compile(r"^(?:(?:a|an|the|my|some|one|two|half|another|\d+(?:\.\d+)?)\s+)+", re.IGNORECASE)


def meals_named_in(text: str, known_meals: list[dict]) -> list[dict]:
    """Saved meal presets that `text` names, in order of first appearance
    (2026-11-11). Two deterministic signals, either is enough:
      - the preset's name appears as a whole word (graph.title_mentioned —
        the app's one definition of "mentioned"), or
      - a piece of the text, cut at list separators (",", "plus", "and",
        "with", "+", "&"), leading articles/counts stripped, matches the
        name under canonicalize_name — the same fuzzy match meal_composer
        uses to resolve a component to a saved meal.
    A preset whose name sits inside a longer matched preset's name is
    dropped ("Rice bowl" and "Chicken rice bowl" both hitting one mention)."""
    from ...graph import title_mentioned

    by_name = {m["name"]: m for m in known_meals or [] if (m.get("name") or "").strip()}
    if not by_name or not (text or "").strip():
        return []
    names = list(by_name)
    lowered = text.lower()
    hits: dict[str, int] = {}
    for name in names:
        if title_mentioned(name, text):
            hits[name] = lowered.find(name.lower())
    for piece in _MEAL_SPLIT.split(text):
        candidate = _MEAL_LEAD.sub("", piece.strip()).strip()
        if not candidate:
            continue
        matched = canonicalize_name(candidate, names)
        if matched in by_name and matched not in hits:
            pos = lowered.find(piece.strip().lower())
            hits[matched] = pos if pos >= 0 else len(text)
    kept = [n for n in hits if not any(o != n and n.lower() in o.lower() for o in hits)]
    return [by_name[n] for n in sorted(kept, key=lambda n: hits[n])]


_LEAD_SPLIT = re.compile(r"\s*(?:,|;|\s-\s|\s—\s|\(|\bper\b|\bsize\b|\bbought\b|\buse\b|\bfrom\b)", re.IGNORECASE)


def keep_typed_name(model_name: str, text: str) -> str:
    """2026-11-11: the user's own words win for an item's name. When the
    model's name is just a subset of what was typed up front ("Hydrating
    Cleanser" from "CeraVe hydrating cleanser, use AM and PM") it dropped
    a detail — usually the brand — so the typed phrase is the name. Code,
    not a model: the leading phrase up to the first comma/qualifier."""
    lead = _LEAD_SPLIT.split(text.strip(), maxsplit=1)[0].strip(" .:")
    words = lambda s: re.findall(r"[a-z0-9]+", s.lower())  # noqa: E731
    lead_w, model_w = words(lead), words(model_name)
    if not lead_w or not model_w or len(lead_w) > 8:
        return model_name
    if set(model_w) <= set(lead_w) and len(lead_w) > len(model_w):
        return lead[0].upper() + lead[1:]
    return model_name
