"""Owner-approved fixes, 2026-11-18 (TESTING-LOG.md, fixes a-j). Deterministic, no model."""
from __future__ import annotations

import pytest

from quintacle_core.drop_fixups import trip_folder_matches_plan
from quintacle_core.gazetteer import find_places
from quintacle_core.nodes.kb.chat import _RECENT_HEADING, strip_past_chat_numbers
from quintacle_core.nodes.logs.label_parser import guess_product_name, parse_label
from quintacle_core.nodes.logs.meal_composer import ComposedComponent, MealCompositionSuggestion, apply_stated_amounts


def _meal(*comps):
    return MealCompositionSuggestion(meal_name="Breakfast", components=[
        ComposedComponent(name=n, quantity_g=g, protein_g=1, carbs_g=1, fat_g=1, fiber_g=0, kcal=10) for n, g in comps])


BREAKFAST = "I have 230 grams of costco lamb, 70 grams of atlantic salmon, 2 eggs and 50 grams of uncooked rice."


# a: eggs by count -> grams
def test_two_eggs_sized_as_two_grams_become_100_g():
    out = apply_stated_amounts(_meal(("eggs", 2), ("costco lamb", 230)), BREAKFAST)
    egg = out.components[0]
    assert egg.quantity_g == 100 and egg.kcal == pytest.approx(500)
    assert out.components[1].quantity_g == 230


def test_eggs_already_in_grams_are_left_alone():
    out = apply_stated_amounts(_meal(("Egg, whole, raw", 100)), BREAKFAST)
    assert out.components[0].quantity_g == 100


def test_egg_whites_and_eggplant_are_not_eggs():
    out = apply_stated_amounts(_meal(("egg whites", 2), ("eggplant", 3)), "2 eggs, 1 eggplant")
    assert [c.quantity_g for c in out.components] == [2, 3]


# b: uncooked / dry -> raw, never cooked
@pytest.mark.parametrize("name", ["basmati rice, cooked", "rice", "white rice (cooked)"])
def test_rice_stated_uncooked_is_raw(name):
    out = apply_stated_amounts(_meal((name, 50)), BREAKFAST)
    n = out.components[0].name.lower()
    assert "raw" in n and "cooked" not in n.replace("uncooked", ""), n


def test_cooked_rice_the_owner_said_cooked_stays_cooked():
    out = apply_stated_amounts(_meal(("rice, cooked", 150)), "150 g cooked rice and 2 eggs")
    assert out.components[0].name == "rice, cooked"


# d: an existing trip folder must be this trip (places + year)
def test_nyc_plan_leaves_europe_2027():
    assert trip_folder_matches_plan("Fun/Travel/Planned/Europe 2027", "New York City 4-Day Trip 2028",
                                    "Day 1 in New York: Central Park. Day 2 Brooklyn.") == "Fun/Travel/Planned/New York"


def test_vienna_ticket_stays_in_europe_2027():
    f = "fun/travel/planned/europe-2027"
    assert trip_folder_matches_plan(f, "Flight IAD to VIE May 2027",
                                    "Washington Dulles (IAD) → Frankfurt (FRA) → Vienna (VIE), 15 May 2027") == f


def test_2028_plan_does_not_go_into_the_2027_folder():
    assert trip_folder_matches_plan("Fun/Travel/Planned/Europe 2027", "London Paris trip 2028",
                                    "Day 1 London, Day 2 Paris") == "Fun/Travel/Planned/Europe"


def test_non_place_trip_folder_only_checks_year():
    f = "Fun/Travel/Planned/Honeymoon 2027"
    assert trip_folder_matches_plan(f, "Honeymoon in Bali 2027", "Bali, Indonesia") == f


# f: a layover city is a layover everywhere in the text
@pytest.mark.parametrize("text", [
    "Washington Dulles (IAD) → Frankfurt (FRA) → Vienna (VIE).",  # "airport" alone is not a layover (2026-11-18 review)
    "Vienna 5 days, flying home through Frankfurt Airport.",
    "Frankfurt (FRA) layover 2h. Vienna 5 days.",
    "Leg 1: IAD to Frankfurt (FRA) - 1h 35m connection. Leg 2 to Vienna (VIE)",
    "Vienna (VIE), connecting through Frankfurt (FRA)",
])
def test_layover_city_is_not_a_destination(text):
    assert [m.city for m in find_places(text) if m.city] == ["Vienna"]


def test_city_chain_without_airport_codes_keeps_every_stop():
    assert [m.city for m in find_places("Budapest → Vienna → Salzburg → Prague")] == ["Budapest", "Vienna", "Salzburg", "Prague"]


# g: local turns get the past-chat block without numbers
def test_past_chat_numbers_are_removed_only_inside_that_block():
    text = (f"## Notes\nI eat 200 g.\n\n{_RECENT_HEADING}\n\n- [2026-11-06] targets about 200 g protein and 2,400 kcal, 3x8\n"
            "\n## Nutrition facts\n50 g rice")
    out = strip_past_chat_numbers(text)
    assert "- [2026-11-06] targets about … protein and …, …" in out
    assert "I eat 200 g." in out and "50 g rice" in out


# j: label reading
def test_vitamin_d_read_without_spaces_and_mog_misread():
    v = parse_label("VitaminD0.4mog 2% Calcium 10mg").values["Vitamin D"]
    assert (v.amount, v.unit) == (0.4, "mcg")


@pytest.mark.parametrize("text,amount", [("Vitamin D 30mcg 150%", 30.0), ("Vitamin D3 10mcg", 10.0)])
def test_vitamin_d_spacing_variants(text, amount):
    assert parse_label(text).values["Vitamin D"].amount == amount


def test_safe_handling_heading_is_not_a_product_name():
    lines = [("Safe Handling Instructions", (0, 0, 100, 30), 0.99), ("Spring Lamb", (0, 0, 100, 28), 0.99)]
    assert guess_product_name(lines) == "Spring Lamb"


def test_usda_filled_rows_from_the_card_are_not_saved_as_label(monkeypatch):
    from quintacle_core.nodes.logs import usda_sourcing

    monkeypatch.setattr(usda_sourcing.usda, "preset_from_usda", lambda fdc, g: {"micros": [
        {"nutrient": "Zinc", "amount": 3.0, "unit": "mg", "source": "usda"}]})
    out = usda_sourcing.merge_label_with_usda(
        [{"nutrient": "Iron", "amount": 2.1, "unit": "mg", "source": "label"},
         {"nutrient": "Zinc", "amount": 4.9, "unit": "mg", "source": "usda"}], 1, 112)
    assert {(m["nutrient"], m["amount"], m["source"]) for m in out} == {("Iron", 2.1, "label"), ("Zinc", 3.0, "usda")}


# label photos: the label's one ingredient, naming, saved look-alikes; typed qualifiers (owner 2026-11-18)
from quintacle_core.api import ingredient_existing_match, label_ingredient_name, label_single_ingredient  # noqa: E402
from quintacle_core.nodes.logs.meal_composer import _keep_stated_qualifier  # noqa: E402
from quintacle_core.nutrition_db import store as usda  # noqa: E402

needs_usda = pytest.mark.skipif(not usda.is_installed(), reason="offline USDA db not installed")


@needs_usda
@pytest.mark.parametrize("text,word", [
    ("Monounsaturated Fat 5g INGREDIENTS: LAMB\nCholesterol 75mg", "lamb"),
    ("Ingredients: Atlantic salmon.", "salmon"),
    ("INGREDIENTS: CULTURED PASTEURIZED NONFAT MILK", "milk"),
    ("Ingredients: flour, water, salt, yeast", None),
    ("Total Fat 13g", None),
])
def test_label_single_ingredient(text, word):
    assert label_single_ingredient(text) == word


@needs_usda
@pytest.mark.parametrize("name,desc,want", [
    ("Safe Handling Instructions", "Lamb, New Zealand, imported, ground lamb, raw", "Lamb"),
    ("Chobani", "Yogurt, Greek, plain, nonfat", "Chobani (Greek yogurt)"),
    ("Costco Lean Lamb", "Lamb, New Zealand, imported, ground lamb, raw", "Costco Lean Lamb"),
    ("Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)", "Yogurt, Greek, plain, nonfat",
     "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)"),
])
def test_label_ingredient_name(name, desc, want):
    assert label_ingredient_name(name, desc) == want


@needs_usda
def test_lamb_label_numbers_with_lamb_ingredient_match_only_lamb():
    per100 = {"kcal": 187.5, "protein_g": 19.6, "carbs_g": 0.0, "fat_g": 11.6}
    cands = usda.nearest_by_profile(per100, [], require_word="lamb")
    assert cands and all("lamb" in c["description"].lower() for c in cands)


SAVED = [{"id": 2, "name": "Costco Lean Lamb", "basis_amount_g": 112, "kcal": 210, "protein_g": 22, "fat_g": 13, "carbs_g": 0,
          "fdc_id": 172617, "source": "label"}]


def test_same_name_is_flagged():
    assert ingredient_existing_match({"suggested_name": "Costco Lean Lamb", "basis_amount_g": 100, "kcal": 1}, SAVED)["by"] == "same_name"


def test_same_numbers_under_another_name_is_flagged():
    m = ingredient_existing_match({"suggested_name": "Spring Lamb", "basis_amount_g": 112, "kcal": 212, "protein_g": 22,
                                   "fat_g": 13.5, "carbs_g": 0}, SAVED)
    assert m == {"id": 2, "name": "Costco Lean Lamb", "by": "same_numbers"}


def test_a_different_food_is_not_flagged():
    assert ingredient_existing_match({"suggested_name": "Greek yogurt", "basis_amount_g": 170, "kcal": 90, "protein_g": 17,
                                      "fat_g": 0, "carbs_g": 6}, SAVED) is None


@pytest.mark.parametrize("name,want", [("Salmon", "Atlantic salmon"), ("salmon, raw", "Atlantic salmon, raw"),
                                       ("Costco Lean Lamb", "Costco Lean Lamb"), ("eggs", "eggs"), ("rice", "rice")])
def test_typed_qualifier_is_kept(name, want):
    text = "I have 230 grams of costco lamb, 70 grams atlantic salmon, 2 eggs and 50 grams of uncooked rice."
    assert _keep_stated_qualifier(name, text) == want
