from quintacle_core.nodes.logs.nutrition_targets import rda_for, to_canonical_unit


def test_converts_mismatched_unit_to_canonical():
    # Copper's canonical unit is mcg — a model answering in mg must be converted,
    # not just relabeled (this was a real bug: 0.48 "mg" silently became 0.48 "mcg").
    amount, unit = to_canonical_unit(0.48, "mg", "Copper")
    assert unit == "mcg"
    assert amount == 480.0


def test_already_canonical_unit_passes_through():
    amount, unit = to_canonical_unit(55.0, "mcg", "Selenium")
    assert (amount, unit) == (55.0, "mcg")


def test_unrecognized_unit_keeps_its_own_label_instead_of_mislabeling():
    amount, unit = to_canonical_unit(400.0, "IU", "Vitamin D")
    assert (amount, unit) == (400.0, "IU")


def test_unknown_nutrient_passes_through_unchanged():
    amount, unit = to_canonical_unit(10.0, "mg", "Fluoride")
    assert (amount, unit) == (10.0, "mg")


def test_rda_differs_by_sex_for_iron():
    # The biggest real sex difference in the table — menstruating women need
    # more than double the iron men do at the same age.
    assert rda_for("male", 30)["Iron"][0] == 8
    assert rda_for("female", 30)["Iron"][0] == 18


def test_rda_iron_drops_for_women_after_51():
    # Post-menopause, women's iron RDA falls back to the same as men's.
    assert rda_for("female", 60)["Iron"][0] == 8


def test_rda_calcium_rises_for_women_after_51():
    assert rda_for("female", 30)["Calcium"][0] == 1000
    assert rda_for("female", 60)["Calcium"][0] == 1200


def test_rda_defaults_to_male_19_50_when_profile_incomplete():
    assert rda_for(None, None)["Iron"][0] == 8
    assert rda_for(None, None)["Vitamin A"][0] == 900


def test_rda_includes_label_limit_nutrients():
    table = rda_for("male", 30)
    assert table["Saturated Fat"] == (20, "g")
    assert table["Cholesterol"] == (300, "mg")
    assert table["Added Sugars"] == (50, "g")
