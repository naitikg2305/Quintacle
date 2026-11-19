from __future__ import annotations

import re

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from ...llm_dispatch import parse_structured
from ..journal.normalize import canonicalize_name
from .nutrition_targets import NUTRIENT_UNITS
from .usda_sourcing import usda_proposal

# 2026-11-11: the model no longer guesses 30 micronutrients per component —
# that was ~4,000 output tokens (a 5-minute local call) thrown away whenever
# the component matched the library or USDA, i.e. almost always. It names
# components + grams + macros; micros come from USDA, and only an unmatched
# component gets a separate micro estimate (resolve_composition).
_SYSTEM_PROMPT = (
    "You help assemble a meal preset out of ingredients. Given a description of a dish being "
    "put together and a library of known ingredient presets, list every component: its name "
    "(match the library's naming if it's clearly the same thing; otherwise a plain food name "
    "like 'basmati rice'), and the quantity used in grams. Keep the state the user gave: an amount "
    "stated uncooked/dry stays raw (name it '..., raw'), never 'cooked'. A count becomes grams "
    "(one large egg is about 50 g). Also give a rough macro "
    "estimate for that quantity (protein/carbs/fat/fiber/kcal) — only a fallback, approximate "
    "is fine. Also propose meal_name, a short name for the finished dish."
    # 2026-11-19 (owner fix 5, diagnosed): on long recipes (Equipment / Toppings / Seasoning sections)
    # qwen3:8b looped the component list until it ran out of tokens -> cut-off JSON -> the meal card
    # failed. Foods only, each once, then stop.
    " List only foods that are eaten, each ONCE: never equipment, tools, paper, or optional "
    "alternatives repeated; fold salt/pepper/spices into one 'Seasoning' component or skip them. "
    "Stop after the last distinct food."
)


class MicroEstimate(BaseModel):
    nutrient: str
    amount: float
    unit: str


class ComposedComponent(BaseModel):
    name: str
    quantity_g: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    kcal: float
    # Never asked of the model (see _SYSTEM_PROMPT note); filled for an
    # unmatched component by resolve_composition.
    micros: SkipJsonSchema[list[MicroEstimate]] = []


class MealCompositionSuggestion(BaseModel):
    meal_name: str
    # 2026-11-19: a hard cap so a looping local model must close the list (maxItems in the schema).
    components: list[ComposedComponent] = Field(min_length=1, max_length=20)


def _format_ingredient_library(known_ingredients: list[dict]) -> str:
    if not known_ingredients:
        return "Known ingredient library: (none saved yet)"
    lines = [f"id={i['id']} name={i['name']!r} (per {i['basis_amount_g']}g: {i['kcal']}kcal)" for i in known_ingredients]
    return "Known ingredient library:\n" + "\n".join(lines)


def _format_meal_library(known_meals: list[dict]) -> str:
    lines = [f"name={m['name']!r} (one serving: {m['kcal']}kcal)" for m in known_meals]
    return (
        "Saved meal presets (each is one serving; a dish can include a whole saved meal as ONE "
        "component — use its exact name, don't break it into ingredients):\n" + "\n".join(lines)
    )


def suggest_meal_composition(
    description: str, known_ingredients: list[dict], provider: str | None = None,
    known_meals: list[dict] | None = None,
) -> MealCompositionSuggestion:
    system = _SYSTEM_PROMPT + "\n\n" + _format_ingredient_library(known_ingredients)
    if known_meals:
        system += "\n\n" + _format_meal_library(known_meals)
    return parse_structured(system, description, MealCompositionSuggestion, provider=provider, max_tokens=4096).parsed


# 2026-11-18 (owner, T7): code guards for the two misses on his breakfast cards.
_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
# 2026-11-18 (reviewer): a count followed by white(s)/yolk(s) is not whole eggs — "2 egg whites and
# 3 eggs" sizes whole eggs from "3", not the first number in the sentence.
_EGG_COUNT_RE = re.compile(
    r"\b(\d+|a|an|one|two|three|four|five|six|seven|eight)\s+(?:(?:large|medium|whole|big|boiled|fried|scrambled|poached)\s+)*"
    r"eggs?\b(?![\s-]*(?:whites?|yolks?)\b)",
    re.IGNORECASE)
EGG_G = 50.0  # one large whole egg without shell (USDA "Egg, whole, raw, fresh": 1 large = 50 g)
_RAW_WORDS = r"(?:uncooked|dry|dried|raw)"
_STATE_WORDS = {"raw", "uncooked", "cooked", "dry", "dried"}


def _is_whole_egg(name: str) -> bool:
    n = name.lower()
    return bool(re.search(r"\beggs?\b", n)) and not re.search(r"eggplant|white|yolk|noodle|substitute", n)


# 2026-11-18 (owner, T8): his phrase for a food = the words AFTER an amount (+ optional unit, + optional
# "of"/"the"/"a") up to and including the food word. A grammar, not a skip-list: "then 50 g rice" has
# "then" BEFORE the amount, so it is never mistaken for a qualifier.
# 2026-11-19 (owner): a word amount must be a WHOLE word — without the closing \b the "a" of "and"
# in "salt and pepper" was read as the amount "a", naming the food "Black nd pepper". A number may
# still touch its unit ("100g").
_AMOUNT = (r"(?:~\s*)?(?:\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?|(?:a\s+couple\s+of|a\s+couple|couple\s+of|a\s+few|a\s+half|half\s+an?|half"
           r"|one|two|three|four|five|six|seven|eight|nine|ten|a|an)\b)")
_UNIT = (r"(?:g|gr|grams?|kg|kilos?|kilograms?|oz|ounces?|lbs?|pounds?|ml|millilit(?:er|re)s?|l|lit(?:er|re)s?|cups?|"
         r"tbsps?|tablespoons?|tsps?|teaspoons?|slices?|pieces?|pcs?|scoops?|servings?|cans?|bowls?|handfuls?|fillets?)")
_CONNECTORS = r"(?:and|with|plus|or|then|of|in|on|for|to|at|from)"
# Words of his phrase that are never added to a name: raw/cooked state (handled by the raw rule
# below) and possessives/determiners.
_NOT_QUALIFIER = _STATE_WORDS | {"my", "our", "his", "her", "their", "this", "that", "these", "those", "some", "the"}


def _food_stem(word: str) -> str:
    """Pattern for a food word, singular or plural ("egg"/"eggs", "oats"/"oat", "tomato"/"tomatoes")."""
    stem = word[:-2] if word.endswith("es") and len(word) > 4 else word[:-1] if word.endswith("s") and len(word) > 3 else word
    return rf"{re.escape(stem)}(?:e?s)?"


def _head_words(comp_name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{3,}", comp_name.lower()) if w not in _STATE_WORDS]


def _stated_phrase(head: str, text: str) -> list[str] | None:
    """His own words in front of `head` inside an amount phrase, or None if he gave no amount for it."""
    word = rf"(?!{_CONNECTORS}\b)[a-z][a-z'-]*"
    pat = (rf"(?<![\w.]){_AMOUNT}\s*(?:{_UNIT}\b\.?)?\s*(?:of\s+)?(?:(?:the|a|an)\s+)?"
           rf"(?P<pre>(?:{word}\s+){{0,4}}?){_food_stem(head)}\b")
    m = re.search(pat, text or "", re.IGNORECASE)
    return m.group("pre").lower().split() if m else None


def _keep_stated_qualifier(comp_name: str, text: str) -> str:
    """Prepend the words of his phrase the model's name lacks ("70 grams atlantic salmon" + "Salmon"
    -> "Atlantic salmon"); the rest of the model's name stays. No amount phrase -> name unchanged."""
    low = comp_name.lower()
    have = set(re.findall(r"[a-z]+", low))
    squashed = re.sub(r"[^a-z]", "", low)
    for head in _head_words(comp_name):
        pre = _stated_phrase(head, text)
        if pre is None:
            continue
        missing = [w for w in pre if w not in have and w not in _NOT_QUALIFIER]
        if not missing or "".join(missing) in squashed:
            return comp_name
        q = " ".join(missing)
        if low.startswith(head):
            return f"{q.capitalize()} {comp_name[:1].lower()}{comp_name[1:]}"
        at = re.search(rf"\b{re.escape(head)}", comp_name, re.IGNORECASE)
        return f"{comp_name[:at.start()]}{q} {comp_name[at.start():]}"
    return comp_name


# 2026-11-18 (owner): each food is judged only inside ITS OWN part of the text — "150 g cooked chicken
# breast and 40 g dry oats" must not make the chicken raw. Split at . , ; newline (not inside "1.5"),
# and/with/plus, and before each new amount.
_SEGMENT_SPLIT = re.compile(
    r"(?<!\d)[.,;]|[.,;](?!\d)|\n|\b(?:and|with|plus)\b|(?=(?<![\w.~])~?\d)"
    r"|(?=\b(?:one|two|three|four|five|six|seven|eight|nine|ten|half)\b)",
    re.IGNORECASE)


def _ordered_name_words(name: str) -> list[str]:
    """The name's content words in order, normalized like chat_lane._name_words (lowercase, plural
    "s" dropped, filler like raw/the/my removed), ignoring parenthetical serving text ("(2/3 cup)")."""
    from ...nutrition_db.chat_lane import _name_words

    plain = re.sub(r"\([^)]*\)", " ", name or "")
    return [w for tok in re.findall(r"[a-z0-9]+", plain.lower()) for w in _name_words(tok)]


def _saved_head(name: str) -> str | None:
    """The head food word of a saved name: the first word of a USDA-style comma name ("Egg, whole,
    raw"), else the last word ("Kirkland ... Greek Yogurt", "Salmon burger sauce" -> sauce)."""
    words = _ordered_name_words(name.split(",")[0] if "," in name else name)
    return (words[0] if "," in name else words[-1]) if words else None


def saved_ingredient_match(comp_name: str, saved_names: list[str]) -> str | None:
    """2026-11-19 (owner): the saved ingredient a model's component name means, or None.
    First the strict canonicalize_name match; then a tolerant one for a shortened/partial name
    ("Kirkland Plain Nonfat" -> "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)"):
    EVERY content word of the component is in the saved name (parentheticals, punctuation, case and
    plural ignored) and EXACTLY ONE saved name qualifies, and either >= 2 words are shared or the
    component is one food word that is that saved name's head ("Salmon" never picks "Salmon burger
    sauce"). Ambiguous -> None (a new component, reviewed by him)."""
    names = list(saved_names or [])
    if not names or not (comp_name or "").strip():
        return None
    strict = canonicalize_name(comp_name, names)
    if strict in names:
        return strict
    want = set(_ordered_name_words(comp_name))
    if not want:
        return None
    hits = [n for n in names if want <= set(_ordered_name_words(n))]
    if len(hits) != 1:
        return None
    if len(want) >= 2 or _saved_head(hits[0]) in want:
        return hits[0]
    return None


def _segments_for(words: list[str], text: str) -> list[str]:
    segs = [s for s in _SEGMENT_SPLIT.split(text or "") if s and s.strip()]
    return [s for s in segs if any(re.search(rf"\b{_food_stem(w)}\b", s, re.IGNORECASE) for w in words)]


def _stated_raw(words: list[str], text: str) -> bool:
    """His segment for this food says uncooked/dry/raw/dried ("50 g of uncooked rice", "rice (dry)")
    and none of its segments says cooked (not "uncooked")."""
    segs = _segments_for(words, text)
    if any(re.search(r"\b(?<!un)cooked\b", s, re.IGNORECASE) for s in segs):
        return False
    return any(re.search(rf"\b{_RAW_WORDS}\b", s, re.IGNORECASE) for s in segs)


def apply_stated_amounts(
    suggestion: MealCompositionSuggestion, text: str, known_names: list[str] | None = None,
) -> MealCompositionSuggestion:
    """Deterministic: (a) "2 eggs" means 2 x 50 g, so an egg component the model sized at a
    count's worth of grams ("2 g") is set to the count x 50 g (macros scaled with it);
    (b) the words he typed for a food are kept in its name (_keep_stated_qualifier);
    (c) a food HIS segment states uncooked/dry is never "cooked": "cooked" becomes "raw" (and
    ", raw" is added) so the USDA match is the raw food his grams are for. A food his segment
    says cooked is never made raw.
    2026-11-18 (owner): a component that already resolves to one of his saved ingredients/meals
    (`known_names`, the same saved_ingredient_match check resolve_composition uses) is never renamed —
    "Oats" -> "Oats, raw" would stop matching his Oats and save a duplicate. (a) still applies."""
    text = text or ""
    known = list(known_names or [])
    m = _EGG_COUNT_RE.search(text)
    eggs = None
    if m:
        tok = m.group(1).lower()
        eggs = int(tok) if tok.isdigit() else _NUM_WORDS.get(tok)
    for comp in suggestion.components:
        if eggs and _is_whole_egg(comp.name) and comp.quantity_g < eggs * EGG_G * 0.5:
            want = eggs * EGG_G
            ratio = want / comp.quantity_g if comp.quantity_g > 0 else 0.0
            for f in ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal"):
                setattr(comp, f, getattr(comp, f) * ratio)
            comp.quantity_g = want
        # 2026-11-19: the same tolerant saved-name match resolve_composition uses — a matched saved
        # item is never renamed.
        if known and saved_ingredient_match(comp.name, known) is not None:
            continue
        comp.name = _keep_stated_qualifier(comp.name, text)
        words = [w for w in _head_words(comp.name) if w not in ("white", "brown", "long", "grain", "short")]
        if words and _stated_raw(words, text):
            name = re.sub(r"\b(?<!un)cooked\b", "raw", comp.name, flags=re.IGNORECASE)
            if not re.search(rf"\b{_RAW_WORDS}\b", name, re.IGNORECASE):
                name = f"{name.rstrip(', ')}, raw"
            comp.name = re.sub(r"\s*,\s*,", ",", name)
    return suggestion


def _estimate_micros(name: str, quantity_g: float, provider: str | None) -> list[dict]:
    """Micros for a component neither the library nor USDA knows — one
    small estimate call for just that food, scaled to the quantity used."""
    from .nutrition_llm import estimate_nutrition

    try:
        est = estimate_nutrition(f"{quantity_g:g} g {name}", provider=provider)
    except Exception:
        return []
    ratio = quantity_g / est.basis_amount_g if est.basis_amount_g else 1.0
    return [{"nutrient": m.nutrient, "amount": m.amount * ratio, "unit": m.unit} for m in est.micros]


def _meal_component(meal: dict, comp: ComposedComponent) -> dict:
    """2026-11-11: a component that IS a saved meal preset. A meals row has
    no gram weight — its stored macros are ONE SERVING — so the component is
    one serving of that meal at the meal's own numbers (the model's gram and
    macro guess is discarded, exactly like a library-ingredient match).
    quantity_g is for display/scaling only: the composed meal's real
    ingredient weight when the caller knows it (`serving_g`), else the
    model's gram guess. basis_amount_g == quantity_g, so the review editor's
    rescale turns a quantity edit into a servings fraction (it scales
    `servings` along with the macros). Save sends {meal_id, servings}; the
    backend expands it (logs/api.py create_meal_from_ingredients) — it never
    becomes a duplicate new ingredient preset."""
    grams = float(meal.get("serving_g") or 0) or float(comp.quantity_g or 0) or 100.0
    return {
        "name": meal["name"],
        "ingredient_id": None,
        "meal_id": meal["id"],
        "servings": 1.0,
        "quantity_g": grams,
        "basis_amount_g": grams,
        "is_new": False,
        **{k: float(meal.get(k) or 0) for k in ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")},
        "source": "meal",
    }


def resolve_composition(
    suggestion: MealCompositionSuggestion, known_ingredients: list[dict], provider: str | None = None,
    use_usda: bool = True, known_meals: list[dict] | None = None,
) -> dict:
    """Deterministic pass, not AI: matches each proposed component's name
    against the real ingredient library via the same fuzzy-match used for
    exercise/substance names. A match means the component uses that
    ingredient's REAL stored macros (scaled to the proposed quantity) instead
    of the model's fallback guess — only genuinely new components keep the
    AI's estimate, staged for review as a new ingredient preset.

    2026-11-11: a component matching no ingredient but a SAVED MEAL preset
    (`known_meals`: meals-table rows, optionally with `serving_g`) is that
    meal, one serving — see _meal_component. Ingredients match first."""
    known_names = [i["name"] for i in known_ingredients]
    by_name = {i["name"]: i for i in known_ingredients}
    meal_names = [m["name"] for m in known_meals or []]
    meals_by_name = {m["name"]: m for m in known_meals or []}
    resolved = []
    for comp in suggestion.components:
        # 2026-11-19 (owner): tolerant of a shortened saved name (saved_ingredient_match); saved
        # meals keep the strict canonicalize_name match below.
        matched_name = saved_ingredient_match(comp.name, known_names)
        ingredient = by_name.get(matched_name) if matched_name is not None else None
        meal = None if ingredient is not None else meals_by_name.get(canonicalize_name(comp.name, meal_names))
        if meal is not None:
            resolved.append(_meal_component(meal, comp))
        elif ingredient is not None:
            ratio = comp.quantity_g / ingredient["basis_amount_g"] if ingredient["basis_amount_g"] else 0
            resolved.append(
                {
                    "name": ingredient["name"],
                    "ingredient_id": ingredient["id"],
                    "quantity_g": comp.quantity_g,
                    # What amount the macros below are FOR — lets the frontend
                    # rescale live on a quantity edit without another API call.
                    "basis_amount_g": comp.quantity_g,
                    "is_new": False,
                    "protein_g": ingredient["protein_g"] * ratio,
                    "carbs_g": ingredient["carbs_g"] * ratio,
                    "fat_g": ingredient["fat_g"] * ratio,
                    "fiber_g": ingredient["fiber_g"] * ratio,
                    "kcal": ingredient["kcal"] * ratio,
                    "source": ingredient.get("source") or "estimated",
                }
            )
        else:
            # 2026-11-05: a genuinely new component is matched against the
            # offline USDA db first — a match replaces the model's fallback
            # numbers entirely (scaled to the proposed quantity); only an
            # unmatched component keeps the estimate.
            usda = usda_proposal(comp.name, comp.quantity_g, provider) if use_usda else None
            if usda and usda.get("matched"):
                resolved.append(
                    {
                        "name": comp.name,
                        "ingredient_id": None,
                        "quantity_g": comp.quantity_g,
                        "basis_amount_g": comp.quantity_g,
                        "is_new": True,
                        **{k: usda[k] for k in ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")},
                        "new_ingredient_micros": usda["micros"],
                        "source": "usda",
                        "fdc_id": usda["fdc_id"],
                        "usda_description": usda["usda_description"],
                        # 2026-11-11: micros the match lacked, filled from the same food's
                        # other USDA entry (each such micro carries from_fdc_id).
                        "usda_fill": usda.get("usda_fill") or [],
                        "usda_candidates": usda["usda_candidates"],
                    }
                )
                continue
            resolved.append(
                {
                    "name": comp.name,
                    "ingredient_id": None,
                    "quantity_g": comp.quantity_g,
                    "basis_amount_g": comp.quantity_g,
                    "is_new": True,
                    "protein_g": comp.protein_g,
                    "carbs_g": comp.carbs_g,
                    "fat_g": comp.fat_g,
                    "fiber_g": comp.fiber_g,
                    "kcal": comp.kcal,
                    "new_ingredient_micros": [
                        {**m, "source": "estimated"}
                        for m in ([mm.model_dump() for mm in comp.micros] or _estimate_micros(comp.name, comp.quantity_g, provider))
                    ],
                    "source": "estimated",
                    "usda_candidates": (usda or {}).get("usda_candidates", []),
                }
            )
    totals = {
        field: sum(c[field] for c in resolved) for field in ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")
    }
    return {"meal_name": suggestion.meal_name, "components": resolved, "totals": totals}
