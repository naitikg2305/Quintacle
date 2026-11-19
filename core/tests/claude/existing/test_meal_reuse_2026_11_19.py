"""2026-11-19 (owner-approved): (1) word amounts are whole words ("salt and pepper" is not the amount
"a" + "nd pepper"); (3) a shortened saved-ingredient name reuses the saved ingredient instead of
proposing a new one. Deterministic, models faked/not called."""
import pytest

from quintacle_core.nodes.logs.meal_composer import (
    ComposedComponent,
    MealCompositionSuggestion,
    _keep_stated_qualifier,
    apply_stated_amounts,
    resolve_composition,
    saved_ingredient_match,
)

# The lamb smash-burger answer (turn 4) the bug came from, trimmed to the lines that matter.
BURGER = """\
| Costco Lean Lamb | 230 g, made into 2 balls of 115 g | Patties |
| Atlantic salmon | 70 g | On the side |
- Black pepper, to taste
- 70 g cooked salmon, flaked
- 2-3 tbsp Kirkland Plain Nonfat Greek Yogurt
- Juice of 1/4-1/2 lemon
- A pinch of salt and pepper
- Salt and pepper
- A lemon wedge
"""

YOGURT = "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)"
SAVED_NAMES = [YOGURT, "Costco Lean Lamb", "Atlantic Salmon", "Egg, whole, raw", "Oats", "Costco buns"]


def _ing(i, name, basis=100.0, kcal=100.0):
    return {"id": i, "name": name, "basis_amount_g": basis, "protein_g": 10.0, "carbs_g": 5.0, "fat_g": 1.0,
            "fiber_g": 0.0, "kcal": kcal, "source": "label"}


def _meal(*comps):
    return MealCompositionSuggestion(meal_name="Burger", components=[
        ComposedComponent(name=n, quantity_g=g, protein_g=1, carbs_g=1, fat_g=1, fiber_g=0, kcal=10) for n, g in comps])


# --- Fix 1: amount words need word boundaries --------------------------------

@pytest.mark.parametrize("name,text,want", [
    ("Black pepper", BURGER, "Black pepper"),
    ("pepper", BURGER, "pepper"),
    ("pepper", "salt and pepper", "pepper"),
    ("Salt", BURGER, "Salt"),
    ("Lemon", BURGER, "Lemon"),
    ("onion", "an onion", "onion"),
    ("lemons", "2 lemons", "lemons"),
    # 2026-11-18 behaviour kept
    ("Salmon", "70 grams atlantic salmon", "Atlantic salmon"),
    ("rice", "100g basmati rice", "Basmati rice"),
    ("milk", "200 ml low fat milk", "Low fat milk"),
    ("Egg, whole, raw", "two eggs", "Egg, whole, raw"),
    ("rice", "then 50 g rice", "rice"),
    ("Costco Lean Lamb", "230 grams of the lamb(costco)", "Costco Lean Lamb"),
])
def test_amount_words_are_whole_words(name, text, want):
    assert _keep_stated_qualifier(name, text) == want


# --- Fix 3: tolerant saved-ingredient match ----------------------------------

@pytest.mark.parametrize("comp,want", [
    ("Kirkland Plain Nonfat", YOGURT),
    ("Greek yogurt", YOGURT),
    ("Greek Yogurt, plain, nonfat", YOGURT),
    ("yogurt", YOGURT),
    ("Lamb", "Costco Lean Lamb"),
    ("Salmon", "Atlantic Salmon"),
    ("Eggs", "Egg, whole, raw"),
    ("Oats, raw", "Oats"),
    ("Costco", None),          # one word that is no saved name's head food
    ("Basmati rice", None),
])
def test_saved_ingredient_match(comp, want):
    assert saved_ingredient_match(comp, SAVED_NAMES) == want


def test_single_word_never_picks_a_non_head_match():
    assert saved_ingredient_match("Salmon", ["Salmon burger sauce"]) is None


def test_ambiguous_partial_match_is_new():
    assert saved_ingredient_match("Salmon", ["Atlantic Salmon", "Smoked Salmon"]) is None
    assert saved_ingredient_match("Plain nonfat", ["Kirkland Plain Nonfat Greek Yogurt", "Fage Plain Nonfat Greek Yogurt"]) is None


def test_resolve_reuses_saved_yogurt_for_shortened_name():
    saved = [_ing(5, YOGURT, basis=170.0, kcal=90.0), _ing(2, "Costco Lean Lamb", basis=112.0, kcal=210.0)]
    out = resolve_composition(_meal(("Kirkland Plain Nonfat", 170)), saved, use_usda=False)
    comp = out["components"][0]
    assert comp["ingredient_id"] == 5 and comp["name"] == YOGURT and comp["is_new"] is False
    assert comp["kcal"] == pytest.approx(90.0)


def test_saved_meals_keep_strict_match():
    meals = [{"id": 7, "name": "Greek yogurt bowl with berries", "protein_g": 25, "carbs_g": 35, "fat_g": 8,
              "fiber_g": 0, "kcal": 320}]
    out = resolve_composition(_meal(("Greek yogurt bowl", 200)), [], known_meals=meals, use_usda=False)
    comp = out["components"][0]
    assert comp.get("meal_id") is None


def test_matched_saved_item_is_never_renamed():
    out = apply_stated_amounts(_meal(("Kirkland Plain Nonfat", 40), ("Salmon", 70)),
                               "40 g dry kirkland plain nonfat and 70 grams atlantic salmon", SAVED_NAMES)
    assert [c.name for c in out.components] == ["Kirkland Plain Nonfat", "Salmon"]
