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


# 2026-11-06: "backtrack from the macros". A Nutrition Facts panel names no
# food, so a label photo had nothing to match USDA by name. Instead compare
# the label's per-100 g profile against every USDA food (pure arithmetic) and
# rank the nearest. Scales are typical spreads, so 1 g of fat, 1 g of protein
# and ~15 kcal weigh about the same; sugar/sodium/calcium join when known.
_PROFILE_KEYS = {  # label field -> (USDA nutrient name, scale per 100 g)
    "kcal": ("Energy", 15.0),
    "protein_g": ("Protein", 1.5),
    "carbs_g": ("Carbohydrates", 2.0),
    "fat_g": ("Fat", 1.0),
    "sugars_g": ("Total Sugars", 2.0),
    "sodium_mg": ("Sodium", 60.0),
    "calcium_mg": ("Calcium", 40.0),
}


# Label-panel / package words that name no food — never a description hint.
_HINT_STOP = {
    "nutrition", "facts", "serving", "servings", "size", "amount", "calories", "daily", "value", "values", "total",
    "includes", "added", "sugars", "sugar", "protein", "sodium", "cholesterol", "carbohydrate", "dietary", "fiber",
    "vitamin", "calcium", "iron", "potassium", "contains", "ingredients", "organic", "certified", "natural", "food",
    "foods", "with", "from", "that", "this", "your", "diet", "advice", "general", "used", "tells", "much", "nutrient",
    "contributes", "except", "those", "naturally", "occurring", "real", "simple", "free", "gluten", "trans",
    "saturated", "container", "per", "about", "product", "distributed", "where", "comes", "raised", "kitchen",
}


def nearest_by_profile(per100: dict[str, float], hint_words: list[str] | None = None, limit: int = 8) -> list[dict]:
    """USDA foods closest to a per-100 g nutrition profile. Needs at least
    kcal + two macros. `hint_words` (e.g. OCR'd 'milk', 'cultures', a typed
    'yogurt') boost foods whose description contains them."""
    conn = _connect()
    usable = {k: float(v) for k, v in per100.items() if k in _PROFILE_KEYS and v is not None}
    if conn is None or "kcal" not in usable or len(usable) < 3:
        return []
    names = [_PROFILE_KEYS[k][0] for k in usable]
    marks = ",".join("?" * len(names))
    with _lock:
        rows = conn.execute(
            f"""SELECT f.fdc_id, f.description, f.category, f.source, n.name, fn.amount
                FROM food_nutrient fn JOIN nutrients n ON n.id = fn.nutrient_id
                JOIN foods f ON f.fdc_id = fn.fdc_id WHERE n.name IN ({marks})""",
            names,
        ).fetchall()
    foods: dict[int, dict] = {}
    for r in rows:
        f = foods.setdefault(r["fdc_id"], {"fdc_id": r["fdc_id"], "description": r["description"],
                                            "category": r["category"], "source": r["source"], "vals": {}})
        f["vals"][r["name"]] = float(r["amount"] or 0)
    hints = [w.lower() for w in (hint_words or []) if len(w) > 2]
    hint_set = {w for w in hints if len(w) >= 4 and w not in _HINT_STOP}
    # Ingredient-line words → the USDA food group they imply (an OCR'd
    # "cultured pasteurized nonfat milk" means dairy even though no USDA
    # yogurt description contains "milk").
    implied: set[str] = set()
    for w in hints:
        if w.startswith(("cultur", "yogurt", "yoghurt", "milk", "cream", "whey", "cheese", "casein", "lact")):
            implied |= {"dairy", "yogurt"} if w.startswith(("cultur", "yogurt", "yoghurt")) else {"dairy"}
        elif w.startswith("egg"):
            implied.add("egg")
        elif w.startswith(("chicken", "beef", "pork", "lamb", "turkey")):
            implied.add(w[:4])
    scored = []
    for f in foods.values():
        if not all(_PROFILE_KEYS[k][0] in f["vals"] for k in ("kcal", "protein_g", "fat_g") if k in usable):
            continue
        dist = 0.0
        for k, v in usable.items():
            name, scale = _PROFILE_KEYS[k]
            if name in f["vals"]:
                dist += ((f["vals"][name] - v) / scale) ** 2
        dist = dist ** 0.5
        desc = f["description"].lower()
        cat = (f["category"] or "").lower()
        # 2026-11-07: whole-word (prefix) hits from distinct words of 4+
        # letters — a raw substring test let OCR'd "the"/"per"/"ern" hit
        # "Fish, pike, northern, liver" on a chicken-burger label.
        desc_words = set(re.findall(r"[a-z]+", desc))
        hits = sum(1 for w in hint_set if any(d.startswith(w) or (len(d) >= 4 and w.startswith(d) and len(w) - len(d) <= 1) for d in desc_words))
        hits += sum(1 for g in implied if g in desc or g in cat)
        odd = 1.35 if ("alaska native" in desc or "food distribution" in desc or "usda commodity" in desc) else 1.0
        if implied and hits == 0:
            # 2026-11-07: the ingredient words SAY what the food is (chicken,
            # milk, egg ...) — a numbers-only neighbour that matches none of
            # them (a chicken-burger label → "Fish, pike, liver") ranks lower.
            odd *= 2.0
        scored.append({"fdc_id": f["fdc_id"], "description": f["description"], "category": f["category"],
                       "source": f["source"], "distance": round(dist, 3), "hint_hits": hits,
                       "score": round(dist * odd / (1 + 0.6 * hits), 3)})
    scored.sort(key=lambda c: (c["score"], len(c["description"])))
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


def siblings(fdc_id: int) -> list[dict]:
    """The SAME food published in another USDA release (2026-11-11). USDA
    re-analysed some SR Legacy foods for Foundation Foods and kept the SR
    NDB number, but the Foundation row often carries only ~15 nutrients
    (no selenium, omega-3s, ...) where the SR Legacy row has ~46. Same food
    = same NDB number, or (when a row has none) the identical description.
    Pure lookup; ordered by how many nutrients each row publishes."""
    conn = _connect()
    if conn is None:
        return []
    with _lock:
        # An older/hand-built db may lack the ndb column → description only.
        has_ndb = any(r[1] == "ndb" for r in conn.execute("PRAGMA table_info(foods)"))
        ndb_sel = "ndb" if has_ndb else "'' AS ndb"
        me = conn.execute(f"SELECT {ndb_sel}, description FROM foods WHERE fdc_id=?", (fdc_id,)).fetchone()
        if me is None:
            return []
        norm = " ".join(_words(me["description"]))
        rows = conn.execute(
            f"""SELECT f.fdc_id, f.description, f.source, {'f.ndb' if has_ndb else "''"} AS ndb,
                       COUNT(fn.nutrient_id) AS n
               FROM foods f LEFT JOIN food_nutrient fn ON fn.fdc_id = f.fdc_id
               WHERE f.fdc_id != ? AND ((? != '' AND {'f.ndb' if has_ndb else "''"} = ?) OR lower(f.description) LIKE ?)
               GROUP BY f.fdc_id""",
            (fdc_id, me["ndb"], me["ndb"], f"%{(_words(me['description']) or [''])[0]}%"),
        ).fetchall()
    out = [dict(r) for r in rows
           if (me["ndb"] and r["ndb"] == me["ndb"]) or " ".join(_words(r["description"])) == norm]
    out.sort(key=lambda r: (-r["n"], r["fdc_id"]))
    return [{k: r[k] for k in ("fdc_id", "description", "source")} for r in out]


def profile_filled(fdc_id: int) -> tuple[dict[str, dict], list[dict]] | None:
    """profile_per_100g, with every nutrient the row doesn't publish filled
    from a sibling row of the same food (siblings()). Filled entries carry
    `from_fdc_id`; the second value lists each sibling used:
    [{fdc_id, description, source, nutrients}]. Unknown stays absent."""
    prof = profile_per_100g(fdc_id)
    if prof is None:
        return None
    prof = {k: dict(v) for k, v in prof.items()}
    fills: list[dict] = []
    for sib in siblings(fdc_id):
        extra = {k: v for k, v in (profile_per_100g(sib["fdc_id"]) or {}).items() if k not in prof}
        if not extra:
            continue
        for k, v in extra.items():
            prof[k] = {**v, "from_fdc_id": sib["fdc_id"]}
        fills.append({**sib, "nutrients": sorted(extra)})
    return prof, fills


def preset_from_usda(fdc_id: int, grams: float = 100, fill_from_siblings: bool = True) -> dict | None:
    """An ingredient-preset-shaped dict for `grams` of this food: macro
    columns + every other tracked nutrient as a micro tagged source=usda.
    Pure scaling of db values. 2026-11-11: nutrients the matched row lacks
    are filled from the same food's other USDA release (profile_filled);
    such a micro carries `from_fdc_id`, and `usda_fill` lists which sibling
    supplied which nutrients (re-derivable from fdc_id, so not stored)."""
    if fill_from_siblings:
        got = profile_filled(fdc_id)
        if got is None:
            return None
        prof, fills = got
    else:
        prof, fills = profile_per_100g(fdc_id), []
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
        if v.get("from_fdc_id"):
            micro["from_fdc_id"] = v["from_fdc_id"]
        micros.append(micro)
    micros.sort(key=lambda m: m["nutrient"])
    return {
        **out,
        "basis_amount_g": grams,
        "micros": micros,
        "source": "usda",
        "fdc_id": fdc_id,
        "usda_description": meta.get("description", ""),
        "usda_fill": fills,
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
