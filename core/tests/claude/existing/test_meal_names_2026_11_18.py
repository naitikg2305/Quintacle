"""Meal-drop names, 2026-11-18 (owner-approved): names are what he typed, cooked stays cooked,
saved ingredients are never renamed; egg whites don't size whole eggs. Deterministic, no model."""
from __future__ import annotations

import pytest

from quintacle_core.nodes.logs.meal_composer import (
    ComposedComponent,
    MealCompositionSuggestion,
    _keep_stated_qualifier,
    apply_stated_amounts,
)

BREAKFAST = "I have 230 grams of costco lamb, 70 grams atlantic salmon, 2 eggs and 50 grams of uncooked rice."


def _meal(*comps):
    return MealCompositionSuggestion(meal_name="Breakfast", components=[
        ComposedComponent(name=n, quantity_g=g, protein_g=1, carbs_g=1, fat_g=1, fiber_g=0, kcal=10) for n, g in comps])


def _names(out):
    return [c.name for c in out.components]


# 1: the name is his phrase (words after the amount/unit up to the food word), never numbers/filler
@pytest.mark.parametrize("name,text,want", [
    ("Salmon", BREAKFAST, "Atlantic salmon"),
    ("salmon, raw", BREAKFAST, "Atlantic salmon, raw"),
    ("rice", "100g basmati rice", "Basmati rice"),
    ("milk", "200 ml low fat milk", "Low fat milk"),
    ("Egg, whole, raw", "two eggs", "Egg, whole, raw"),
    ("rice", "then 50 g rice", "rice"),
    ("Costco Lean Lamb", "230 grams of the lamb(costco)", "Costco Lean Lamb"),
    ("Costco Lean Lamb", BREAKFAST, "Costco Lean Lamb"),
    ("eggs", BREAKFAST, "eggs"),
    ("rice", "50 grams of uncooked rice", "rice"),
    ("rice", BREAKFAST, "rice"),
    ("tofu", "I had some tofu", "tofu"),  # no amount phrase -> untouched
])
def test_name_keeps_his_phrase(name, text, want):
    assert _keep_stated_qualifier(name, text) == want


def test_prep_words_are_never_qualifiers():
    for text in ("50 grams of uncooked rice", "50 g cooked rice", "50 g dry rice", "50 g raw rice", "50 g dried rice"):
        assert _keep_stated_qualifier("rice", text) == "rice", text


# 2: each food is judged inside its own segment
def test_cooked_chicken_is_not_made_raw_by_dry_oats():
    out = apply_stated_amounts(_meal(("chicken breast, cooked", 150), ("oats", 40)),
                               "150 g cooked chicken breast and 40 g dry oats")
    assert _names(out) == ["chicken breast, cooked", "oats, raw"]


def test_cooked_salmon_is_not_made_raw_by_uncooked_rice():
    out = apply_stated_amounts(_meal(("rice", 50), ("salmon, cooked", 100)),
                               "50 g uncooked rice with 100 g cooked salmon")
    assert _names(out) == ["rice, raw", "salmon, cooked"]


def test_cooked_rice_the_owner_said_cooked_stays_cooked():
    out = apply_stated_amounts(_meal(("rice, cooked", 150)), "150 g cooked rice and 2 eggs")
    assert _names(out) == ["rice, cooked"]


@pytest.mark.parametrize("name,want", [("basmati rice, cooked", "basmati rice, raw"),
                                       ("white rice (cooked)", "white rice (raw)"), ("rice", "rice, raw")])
def test_rice_his_segment_says_uncooked_is_raw(name, want):
    assert _names(apply_stated_amounts(_meal((name, 50)), BREAKFAST)) == [want]


def test_decimal_amount_does_not_split_a_segment():
    out = apply_stated_amounts(_meal(("oats", 30)), "1.5 scoops whey and 30 g dry oats")
    assert _names(out) == ["oats, raw"]


# 3: a saved ingredient/meal name is left alone; egg grams still fixed
def test_saved_oats_are_not_renamed_raw():
    out = apply_stated_amounts(_meal(("Oats", 40)), "40 g dry oats", ["Oats"])
    assert _names(out) == ["Oats"]


def test_saved_name_gets_no_qualifier():
    out = apply_stated_amounts(_meal(("Salmon", 70)), BREAKFAST, ["Salmon", "Costco Lean Lamb"])
    assert _names(out) == ["Salmon"]


def test_saved_egg_still_gets_count_grams():
    out = apply_stated_amounts(_meal(("Egg, whole, raw", 2)), "2 eggs", ["Egg, whole, raw"])
    egg = out.components[0]
    assert egg.name == "Egg, whole, raw" and egg.quantity_g == 100 and egg.kcal == pytest.approx(500)


def test_unsaved_name_still_renamed_when_known_names_given():
    out = apply_stated_amounts(_meal(("Salmon", 70)), BREAKFAST, ["Costco Lean Lamb"])
    assert _names(out) == ["Atlantic salmon"]


# reviewer: egg whites/yolks counts don't size whole eggs
def test_egg_whites_count_does_not_size_whole_eggs():
    out = apply_stated_amounts(_meal(("egg whites", 60), ("Egg, whole, raw", 3)), "2 egg whites and 3 eggs")
    assert [c.quantity_g for c in out.components] == [60, 150]


def test_egg_yolk_count_is_skipped():
    out = apply_stated_amounts(_meal(("Egg, whole, raw", 2)), "3 egg yolks, 2 eggs")
    assert out.components[0].quantity_g == 100


def test_only_egg_whites_leaves_whole_egg_alone():
    out = apply_stated_amounts(_meal(("Egg, whole, raw", 2)), "2 egg whites")
    assert out.components[0].quantity_g == 2
