"""Reads the offline USDA db: where it lives, deterministic food matching
(FTS5 + code scoring), per-100 g profiles, and the model-picks-only-among-
candidates step (2026-11-05).

Principle (CLAUDE.md "deterministic core, models at the edges"): numbers
only ever come from the db. A model may at most choose WHICH of the top
candidates a description means, by index — it never sees a field it could
return a number in, and an out-of-range answer is rejected in code.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
from pathlib import Path

from pydantic import BaseModel

from .nutrients import BY_NAME, MACRO_FIELDS

logger = logging.getLogger(__name__)

PICK_PROVIDER_ENV = "QUINTACLE_USDA_PICK_PROVIDER"  # off | auto | local | cloud
MIN_SCORE = 0.5  # below this the deterministic top candidate isn't trusted
CONFIDENT_SCORE = 0.8  # at/above this with a clear margin: no model call
CONFIDENT_MARGIN = 0.06

_STOP = {
    "a", "an", "and", "the", "of", "with", "in", "on", "for", "to", "my", "some", "g", "gram", "grams",
    "oz", "ounce", "ounces", "lb", "lbs", "kg", "ml", "cup", "cups", "tbsp", "tsp", "piece", "pieces",
    "slice", "slices", "serving", "servings", "x", "about", "approx", "per", "ate", "had", "how", "much",
    "many", "is", "are", "there", "what", "whats", "does", "do", "contain", "contains", "have", "has",
}
# Words that make a USDA row a poor default unless the user asked for them.
_UNLESS_ASKED = {"native", "babyfood", "babyfoods", "infant", "formula", "fast", "restaurant", "school", "lunch"}
_COOKED = {"cooked", "roasted", "boiled", "baked", "fried", "grilled", "broiled", "braised", "stewed", "steamed",
           "sauteed", "pan", "microwaved", "toasted", "scrambled", "poached", "simmered", "smoked"}


def db_path() -> Path:
    """Resolved per call so a sandboxed QUINTACLE_DATA_DIR (tests) is honoured."""
    override = os.environ.get("QUINTACLE_USDA_DB")
    if override:
        return Path(override)
    data_dir = Path(os.environ.get("QUINTACLE_DATA_DIR", Path.home() / ".quintacle"))
    return data_dir / "nutrition" / "usda.db"


_conns: dict[str, sqlite3.Connection] = {}
_lock = threading.Lock()


def _connect() -> sqlite3.Connection | None:
    path = db_path()
    if not path.exists():
        return None
    key = f"{path}:{path.stat().st_mtime_ns}"
    with _lock:
        conn = _conns.get(key)
        if conn is None:
            for old in list(_conns):
                if old.startswith(f"{path}:"):
                    _conns.pop(old).close()
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            _conns[key] = conn
        return conn


def is_installed() -> bool:
    return _connect() is not None


def summary() -> dict | None:
    conn = _connect()
    if conn is None:
        return None
    with _lock:
        row = conn.execute("SELECT value FROM meta WHERE key='summary'").fetchone()
    out = json.loads(row["value"]) if row else {}
    out["size_bytes"] = db_path().stat().st_size
    return out


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def _query_terms(text: str) -> list[str]:
    seen: list[str] = []
    for w in _words(text):
        if w in _STOP or len(w) < 2:
            continue
        s = _SYNONYMS.get(w) or _stem(w)
        s = _SYNONYMS.get(s, s)
        if s not in seen:
            seen.append(s)
    return seen


_SYNONYMS = {"roast": "roasted", "grill": "grilled", "boil": "boiled", "bake": "baked", "fry": "fried",
             "steam": "steamed", "broil": "broiled", "braise": "braised", "stew": "stewed", "poach": "poached",
             "smoke": "smoked", "toast": "toasted", "yoghurt": "yogurt", "eggs": "egg"}
# Forms that make a row a poor default for a plain ingredient name.
_PROCESSED = {"breaded", "nuggets", "mix", "canned", "frozen", "heated", "prepared", "dehydrated", "muffin",
              "muffins", "pie", "fillings", "filling", "imitation", "sweetened", "flavored", "artificial", "sticks",
              "patties", "substitute", "battered", "candied", "sauce", "soup", "drink", "beverage", "spread",
              "dried", "smoked", "salted", "cured", "pickled", "powder", "flour", "oil", "concentrate"}
# Leading segments that are USDA's category convention, not a different food
# ("Nuts, almonds", "Fish, salmon, …"). Any other leading word before the hit
# ("Flour, almond", "Oil, almond") means it's a different product.
_CATEGORY_HEADS = {"nuts", "seeds", "fish", "mollusks", "crustaceans", "spices", "beans", "peas", "lentils",
                   "cheese", "game", "meat", "veal", "beef", "pork", "vegetables", "fruit", "cereals", "grains",
                   "seaweed", "mushrooms", "squash", "lettuce", "cabbage", "peppers", "onions", "melons"}


def _hit_index(term: str, desc_words: list[str]) -> int:
    """Index of the first whole-word (or same-stem) occurrence, -1 if none.
    Whole words on purpose: "egg" must not hit "eggplant"/"eggnog"."""
    for i, d in enumerate(desc_words):
        if d == term or _stem(d) == term:
            return i
    return -1


def _score(terms: list[str], description: str, source: str) -> float:
    """0..1, pure code. Coverage of the query's terms dominates; then
    precision (a description that says little beyond the query wins — the
    plainest row is the default); then how early the first hit sits (USDA
    puts the food first: "Lamb, leg, …", "Nuts, almonds"). Derived products
    ("Almond butter", "Salmon nuggets": the hit's comma segment carries words
    the user didn't say) and processed/branded forms cost points unless the
    user asked for them."""
    if not terms:
        return 0.0
    desc_words = _words(description)
    if not desc_words:
        return 0.0
    asked = set(terms)
    hits = [_hit_index(t, desc_words) for t in terms]
    covered = sum(1 for h in hits if h >= 0)
    if covered == 0:
        return 0.0
    coverage = covered / len(terms)
    unique = set(desc_words)
    first = min(h for h in hits if h >= 0)
    score = 0.55 * coverage + 0.2 * (covered / len(unique)) + 0.15 / (1 + first)
    segments = description.split(",")
    lead = _words(segments[0])
    if lead and not any(_hit_index(t, lead) >= 0 for t in terms) and not set(lead).issubset(_CATEGORY_HEADS):
        score -= 0.1
    # The comma segment holding the first hit: unasked words there = derived product.
    for segment in segments:
        seg_words = _words(segment)
        if any(_hit_index(t, seg_words) >= 0 for t in terms):
            if any(_hit_index(w, list(asked)) < 0 and _stem(w) not in asked for w in seg_words):
                score -= 0.1
            break
    processed = sum(1 for w in unique if w in _PROCESSED and w not in asked)
    score -= min(0.2, 0.08 * processed)
    if any(w in _UNLESS_ASKED for w in unique) and not (asked & _UNLESS_ASKED):
        score -= 0.25
    if re.search(r"\b[A-Z]{3,}\b", description) and not any(t.upper() in description for t in terms):
        score -= 0.15  # brand-name rows (SR Legacy carries a few)
    wants_cooked = bool(asked & _COOKED)
    if "raw" in unique:
        score += -0.1 if wants_cooked else 0.02  # a bare ingredient name most often means raw
    if "only" in unique and "lean" in unique and not (asked & {"fat", "fatty"}):
        score += 0.005  # meat: "separable lean only" is the default cut unless fat was asked for (owner's example)
    if "whole" in unique and "whole" not in asked:
        score += 0.01  # whole egg / whole milk as the plain default
    if source == "foundation":
        score += 0.01  # newer analytical data for the same food
    return round(max(0.0, min(1.0, score)), 4)


def match_food(text: str, limit: int = 8) -> list[dict]:
    """Ranked USDA candidates for a free-text food description. Empty list
    when the db isn't installed or nothing matches."""
    conn = _connect()
    terms = _query_terms(text)
    if conn is None or not terms:
        return []
    # Prefix query wide enough for plurals (blueberry → "blueberr"* hits
    # "blueberries"); _score then judges whole words.
    fts = " OR ".join(f'"{t[:-1] if t.endswith("y") and len(t) > 3 else t}"*' for t in terms)
    with _lock:
        rows = conn.execute(
            """SELECT f.fdc_id, f.description, f.category, f.source
               FROM foods_fts JOIN foods f ON f.fdc_id = foods_fts.rowid
               WHERE foods_fts MATCH ? ORDER BY bm25(foods_fts) LIMIT 600""",
            (fts,),
        ).fetchall()
    scored = [
        {"fdc_id": r["fdc_id"], "description": r["description"], "category": r["category"], "source": r["source"],
         "score": _score(terms, r["description"], r["source"])}
        for r in rows
    ]
    scored = [c for c in scored if c["score"] > 0]
    scored.sort(key=lambda c: (-c["score"], len(c["description"])))
    return scored[:limit]


def food(fdc_id: int) -> dict | None:
    conn = _connect()
    if conn is None:
        return None
    with _lock:
        row = conn.execute("SELECT * FROM foods WHERE fdc_id=?", (fdc_id,)).fetchone()
    return dict(row) if row else None


def profile_per_100g(fdc_id: int) -> dict[str, dict] | None:
    """{nutrient name: {amount, unit, approx}} per 100 g, or None if unknown."""
    conn = _connect()
    if conn is None:
        return None
    with _lock:
        rows = conn.execute(
            """SELECT n.name, n.unit, fn.amount, fn.approx FROM food_nutrient fn
               JOIN nutrients n ON n.id = fn.nutrient_id WHERE fn.fdc_id=?""",
            (fdc_id,),
        ).fetchall()
        exists = conn.execute("SELECT 1 FROM foods WHERE fdc_id=?", (fdc_id,)).fetchone()
    if not exists:
        return None
    return {r["name"]: {"amount": r["amount"], "unit": r["unit"], "approx": bool(r["approx"])} for r in rows}


def preset_from_usda(fdc_id: int, grams: float = 100) -> dict | None:
    """An ingredient-preset-shaped dict for `grams` of this food: macro
    columns + every other tracked nutrient as a micro tagged source=usda.
    Pure scaling of db values."""
    prof = profile_per_100g(fdc_id)
    if prof is None:
        return None
    meta = food(fdc_id) or {}
    ratio = grams / 100.0
    out = {field: round(prof.get(name, {}).get("amount", 0.0) * ratio, 4) for field, name in MACRO_FIELDS.items()}
    micros = []
    for name, v in prof.items():
        if BY_NAME[name].macro_field:
            continue
        micro = {"nutrient": name, "amount": round(v["amount"] * ratio, 6), "unit": v["unit"], "source": "usda"}
        if v["approx"]:
            micro["approx"] = True
        micros.append(micro)
    micros.sort(key=lambda m: m["nutrient"])
    return {
        **out,
        "basis_amount_g": grams,
        "micros": micros,
        "source": "usda",
        "fdc_id": fdc_id,
        "usda_description": meta.get("description", ""),
    }


class _Pick(BaseModel):
    # 1-based index into the numbered list, or 0 for "none of these".
    choice: int


_PICK_SYSTEM = (
    "You match a food description to a USDA food-composition entry. You get the description and a "
    "numbered list of candidate USDA entries. Answer with the number of the entry that best means the "
    "same food in the same state (raw/cooked, cut, lean/fat), or 0 if none of them is that food. "
    "Answer only with the number."
)


def pick_candidate(text: str, candidates: list[dict], provider: str | None = None) -> dict | None:
    """The deterministic ranking decides when it is confident; otherwise a
    model picks an INDEX among the shown candidates (or none). Its answer is
    validated in code — out of range = ignored. No model / model failure →
    the deterministic top candidate when it clears MIN_SCORE."""
    if not candidates:
        return None
    top = candidates[0]
    runner_up = candidates[1]["score"] if len(candidates) > 1 else 0.0
    deterministic = top if top["score"] >= MIN_SCORE else None
    if top["score"] >= CONFIDENT_SCORE and top["score"] - runner_up >= CONFIDENT_MARGIN:
        return top
    mode = (provider or os.environ.get(PICK_PROVIDER_ENV) or "auto").strip().lower()
    if mode == "off":
        return deterministic
    from ..llm_dispatch import parse_structured  # lazy: keeps this module import-light

    listing = "\n".join(f"{i}. {c['description']} ({c['category']})" for i, c in enumerate(candidates, start=1))
    try:
        result = parse_structured(
            _PICK_SYSTEM, f"Food: {text}\n\nCandidates:\n{listing}", _Pick,
            provider=None if mode == "auto" else mode, max_tokens=64,
        ).parsed
    except Exception as e:  # never block ingredient creation on the picker
        logger.info("usda pick model failed (%s); using deterministic top", e)
        return deterministic
    if result.choice == 0:
        return None
    if 1 <= result.choice <= len(candidates):
        return candidates[result.choice - 1]
    return deterministic


def match_and_pick(text: str, provider: str | None = None) -> tuple[dict | None, list[dict]]:
    candidates = match_food(text)
    return pick_candidate(text, candidates, provider), candidates
