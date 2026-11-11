"""Deterministic nutrition-label parser (nodes/logs/label_parser.py) over
fixture OCR texts — no OCR engine, no model."""

from __future__ import annotations

import pytest

from quintacle_core.nodes.logs.label_parser import guess_product_name, normalize_ocr, overlay_parsed, parse_label, to_estimate

US_PANEL = """Nutrition Facts
8 servings per container
Serving size 2/3 cup (55g)
Calories 230
% Daily Value*
Total Fat 8g 10%
Saturated Fat 1g 5%
Trans Fat 0g
Cholesterol 0mg 0%
Sodium 160mg 7%
Total Carbohydrate 37g 13%
Dietary Fiber 4g 14%
Total Sugars 12g
Includes 10g Added Sugars 20%
Protein 3g
Vitamin D 2mcg 10%
Calcium 260mg 20%
Iron 8mg 45%
Potassium 240mg 6%"""

# The same kind of panel as a cheap phone OCR actually returns it: O for 0,
# "rng", glued numbers, Calories' value pushed to its own line, and the old
# bullet-separated %DV-only vitamin row.
NOISY_PANEL = """NUTRITI0N FACTS
Serving Size 1 bar (4Og)
Calories
190
Total Fat7g 9%
Saturated Fat 1.5g 8%
Trans Fat Og
Cholesterol Omg O%
Sodium15Orng 7%
Total Carb. 26g 9%
Dietary Fiber 3g 11%
Total Sugars 12g
Incl. 1Og Added Sugars 2O%
Protein 4g
Vitamin D 0% • Calcium 2% • Iron 6% • Potassium 4%"""

EU_PANEL = """Nutrition information
Typical values per 100g
Energy 1046kJ / 250kcal
Fat 8,5 g
of which saturates 1,2 g
Carbohydrate 37 g
of which sugars 12 g
Fibre 4,1 g
Protein 7 g
Salt 0,40 g"""


def _micro(est: dict, name: str) -> dict:
    return next(m for m in est["micros"] if m["nutrient"] == name)


def test_us_panel_every_row():
    parse = parse_label(US_PANEL)
    assert parse.core_complete
    assert parse.serving_g == 55 and parse.servings_per_container == 8
    est = to_estimate(parse, "Granola")
    assert est["from_label"] is True and est["basis_amount_g"] == 55
    assert (est["kcal"], est["protein_g"], est["carbs_g"], est["fat_g"], est["fiber_g"]) == (230, 3, 37, 8, 4)
    assert _micro(est, "Saturated Fat") == {"nutrient": "Saturated Fat", "amount": 1.0, "unit": "g"}
    assert _micro(est, "Trans Fat")["amount"] == 0
    assert _micro(est, "Cholesterol") == {"nutrient": "Cholesterol", "amount": 0.0, "unit": "mg"}
    assert _micro(est, "Sodium")["amount"] == 160
    assert _micro(est, "Total Sugars")["amount"] == 12
    assert _micro(est, "Added Sugars")["amount"] == 10
    assert _micro(est, "Vitamin D") == {"nutrient": "Vitamin D", "amount": 2.0, "unit": "mcg"}
    assert _micro(est, "Calcium")["amount"] == 260
    assert _micro(est, "Iron")["amount"] == 8
    assert _micro(est, "Potassium")["amount"] == 240
    assert est["label_dv"]["Iron"] == 45 and est["label_dv"]["fat_g"] == 10 and est["label_dv"]["Added Sugars"] == 20
    assert est["field_confidence"]["kcal"] >= 0.9
    assert est["serving_size_text"] == "2/3 cup (55g)"


def test_noisy_ocr_and_dv_only_minerals():
    parse = parse_label(NOISY_PANEL)
    assert parse.core_complete
    assert parse.serving_g == 40
    est = to_estimate(parse, "Bar")
    assert (est["kcal"], est["protein_g"], est["carbs_g"], est["fat_g"], est["fiber_g"]) == (190, 4, 26, 7, 3)
    assert _micro(est, "Sodium")["amount"] == 150
    assert _micro(est, "Cholesterol")["amount"] == 0
    assert _micro(est, "Trans Fat")["amount"] == 0
    assert _micro(est, "Added Sugars")["amount"] == 10
    # %DV-only rows convert through the FDA LABEL DVs, in code:
    # calcium 2% of 1300 mg, iron 6% of 18 mg, potassium 4% of 4700 mg.
    assert _micro(est, "Calcium")["amount"] == pytest.approx(26)
    assert _micro(est, "Iron")["amount"] == pytest.approx(1.08)
    assert _micro(est, "Potassium")["amount"] == pytest.approx(188)
    assert _micro(est, "Vitamin D")["amount"] == 0
    assert est["field_confidence"]["Calcium"] == pytest.approx(0.7)  # from %DV, lower than stated


def test_eu_per_100g_panel():
    parse = parse_label(EU_PANEL)
    assert parse.per_100g and parse.basis_amount_g == 100
    assert parse.core_complete
    est = to_estimate(parse, "Cereal")
    assert (est["kcal"], est["protein_g"], est["carbs_g"], est["fat_g"]) == (250, 7, 37, 8.5)
    assert est["fiber_g"] == pytest.approx(4.1)
    assert _micro(est, "Saturated Fat")["amount"] == pytest.approx(1.2)
    assert _micro(est, "Total Sugars")["amount"] == 12
    assert _micro(est, "Sodium")["amount"] == pytest.approx(160)  # salt 0.40 g / 2.5
    assert est["field_confidence"]["Sodium"] == pytest.approx(0.5)  # derived


def test_missing_core_fields_is_not_complete():
    partial = "Nutrition Facts\nServing size 1 cup (240mL)\nTotal Fat 2g\nSodium 120mg 5%\nProtein 8g"
    parse = parse_label(partial)
    assert not parse.core_complete
    assert parse.serving_g == 240
    est = to_estimate(parse, "")
    assert est["field_confidence"]["kcal"] == 0 and est["carbs_g"] == 0


def test_calories_derived_from_macros_is_not_core():
    text = "Serving size 30g\nTotal Fat 1g\nTotal Carbohydrate 20g\nProtein 2g"
    parse = parse_label(text)
    assert parse.values["kcal"].how == "derived" and parse.values["kcal"].amount == pytest.approx(97)
    assert not parse.core_complete  # derived calories don't count as READ


def test_calories_from_fat_and_footnote_ignored():
    text = (
        "Amount Per Serving\nCalories 120 Calories from Fat 45\nTotal Fat 5g 8%\nTotal Carbohydrate 15g 5%\n"
        "Protein 3g\n*Percent Daily Values are based on a 2,000 calorie diet."
    )
    est = to_estimate(parse_label(text), "x")
    assert est["kcal"] == 120 and est["fat_g"] == 5


def test_less_than_reads_as_half():
    est = to_estimate(parse_label("Calories 10\nTotal Fat 0g\nTotal Carbohydrate 2g\nDietary Fiber <1g\nProtein 0g"), "x")
    assert est["fiber_g"] == 0.5


def test_normalize_ocr_fixes():
    assert normalize_ocr("Sodium 15Orng") == "sodium 150mg"
    assert normalize_ocr("Vitamin D 5 µg") == "vitamin d 5 mcg"
    assert normalize_ocr("Iron l2mg O%") == "iron 12mg 0%"
    assert normalize_ocr("2,000 calories, fat 8,5 g") == "2000 calories, fat 8.5 g"


def test_overlay_code_wins_over_model():
    parse = parse_label("Serving size 1 cup (30g)\nCalories 110\nTotal Fat 2g\nIron 8mg 45%")
    model = {
        "basis_amount_g": 100, "protein_g": 3, "carbs_g": 22, "fat_g": 9, "fiber_g": 2, "kcal": 400,
        "micros": [{"nutrient": "Iron", "amount": 1, "unit": "mg"}, {"nutrient": "Sodium", "amount": 200, "unit": "mg"}],
        "suggested_name": "Cereal",
    }
    out = overlay_parsed(model, parse)
    assert out["kcal"] == 110 and out["fat_g"] == 2  # read by code
    assert out["carbs_g"] == 22 and out["protein_g"] == 3  # model filled
    assert out["basis_amount_g"] == 30
    iron = next(m for m in out["micros"] if m["nutrient"] == "Iron")
    assert iron["amount"] == 8
    assert out["field_confidence"]["carbs_g"] == 0.5 and out["field_confidence"]["kcal"] >= 0.9
    assert out["from_label"] is True


def test_guess_product_name_picks_tallest_non_panel_line():
    lines = [
        ("Nutrition Facts", (0, 0, 300, 60), 0.99),
        ("Honey Oat Crunch", (0, 0, 300, 80), 0.98),
        ("Net Wt 12 oz", (0, 0, 100, 20), 0.97),
    ]
    assert guess_product_name(lines) == "Honey Oat Crunch"
    assert guess_product_name([("Calories 230", (0, 0, 1, 90), 1.0)]) == ""
