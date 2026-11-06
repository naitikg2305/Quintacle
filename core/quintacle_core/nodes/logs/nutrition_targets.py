from __future__ import annotations

from ...nutrition_db.nutrients import UNITS as _USDA_UNITS

# Real NIH ODS / FDA Daily Value reference data, banded by sex and the two
# adult age brackets where the numbers actually diverge (19-50 vs 51+) — the
# same simplification the FDA's own "51+" label variant uses. Weight/height
# already drive calorie/protein targets separately (Mifflin-St Jeor, see
# profile/targets.py) — real RDA tables aren't defined as a function of body
# weight, so bolting weight/height onto *these* numbers would just be
# inventing precision that doesn't exist in the actual guidance.
#
# {nutrient: (amount, unit)}
MALE_RDA_19_50: dict[str, tuple[float, str]] = {
    "Vitamin A": (900, "mcg"),
    "Vitamin C": (90, "mg"),
    "Vitamin D": (15, "mcg"),
    "Vitamin E": (15, "mg"),
    "Vitamin K": (120, "mcg"),
    "Vitamin B6": (1.3, "mg"),
    "Vitamin B12": (2.4, "mcg"),
    "Folate": (400, "mcg"),
    "Thiamin (B1)": (1.2, "mg"),
    "Riboflavin (B2)": (1.3, "mg"),
    "Niacin (B3)": (16, "mg"),
    "Biotin": (30, "mcg"),
    "Pantothenic Acid (B5)": (5, "mg"),
    "Calcium": (1000, "mg"),
    "Iron": (8, "mg"),
    "Magnesium": (420, "mg"),
    "Zinc": (11, "mg"),
    "Selenium": (55, "mcg"),
    "Potassium": (3400, "mg"),
    "Sodium": (2300, "mg"),
    "Phosphorus": (700, "mg"),
    "Copper": (900, "mcg"),
    "Iodine": (150, "mcg"),
    "Manganese": (2.3, "mg"),
    "Molybdenum": (45, "mcg"),
    "Choline": (550, "mg"),
    "Chloride": (2300, "mg"),
    "Saturated Fat": (20, "g"),
    "Cholesterol": (300, "mg"),
    "Added Sugars": (50, "g"),
    # 2026-11-05: ALA has a real Adequate Intake (NIH ODS omega-3 fact sheet:
    # 1.6 g/day men, 1.1 g/day women). The only fatty acid/compound with
    # official guidance — everything else new is "no official target".
    "ALA (omega-3)": (1.6, "g"),
}

MALE_RDA_51_PLUS: dict[str, tuple[float, str]] = {
    **MALE_RDA_19_50,
    "Vitamin B6": (1.7, "mg"),
    "Vitamin D": (20, "mcg"),
    "Iron": (8, "mg"),  # unchanged for men, listed for clarity
}

FEMALE_RDA_19_50: dict[str, tuple[float, str]] = {
    **MALE_RDA_19_50,
    "Vitamin A": (700, "mcg"),
    "Vitamin C": (75, "mg"),
    "Vitamin K": (90, "mcg"),
    "Thiamin (B1)": (1.1, "mg"),
    "Riboflavin (B2)": (1.1, "mg"),
    "Niacin (B3)": (14, "mg"),
    "Iron": (18, "mg"),  # menstruating adult
    "Magnesium": (320, "mg"),
    "Zinc": (8, "mg"),
    "Potassium": (2600, "mg"),
    "Manganese": (1.8, "mg"),
    "Choline": (425, "mg"),
    "ALA (omega-3)": (1.1, "g"),
}

FEMALE_RDA_51_PLUS: dict[str, tuple[float, str]] = {
    **FEMALE_RDA_19_50,
    "Vitamin B6": (1.5, "mg"),
    "Vitamin D": (20, "mcg"),
    "Iron": (8, "mg"),  # post-menopause drop — the biggest sex/age swing in this table
    "Calcium": (1200, "mg"),
}

IS_LIMIT = {"Sodium", "Saturated Fat", "Cholesterol", "Added Sugars"}

# 2026-11-06: the FDA's LABEL Daily Values (21 CFR 101.9(c), the 2016 rule
# in force on every current US "Nutrition Facts" panel, adults & children
# ≥4). These are what a printed "%DV" is a percentage OF — deliberately a
# separate table from the personalized RDAs above (calcium's label DV is
# 1300 mg even though a 30-year-old man's RDA is 1000 mg). Used ONLY to turn
# a %DV-only label line back into an amount (nodes/logs/label_parser.py).
# Keys use Quintacle's nutrient names; the macro keys are the label rows.
FDA_LABEL_DV: dict[str, tuple[float, str]] = {
    "Total Fat": (78, "g"),
    "Saturated Fat": (20, "g"),
    "Cholesterol": (300, "mg"),
    "Sodium": (2300, "mg"),
    "Total Carbohydrate": (275, "g"),
    "Dietary Fiber": (28, "g"),
    "Added Sugars": (50, "g"),
    "Protein": (50, "g"),
    "Vitamin A": (900, "mcg"),
    "Vitamin C": (90, "mg"),
    "Vitamin D": (20, "mcg"),
    "Vitamin E": (15, "mg"),
    "Vitamin K": (120, "mcg"),
    "Thiamin (B1)": (1.2, "mg"),
    "Riboflavin (B2)": (1.3, "mg"),
    "Niacin (B3)": (16, "mg"),
    "Vitamin B6": (1.7, "mg"),
    "Folate": (400, "mcg"),
    "Vitamin B12": (2.4, "mcg"),
    "Biotin": (30, "mcg"),
    "Pantothenic Acid (B5)": (5, "mg"),
    "Calcium": (1300, "mg"),
    "Iron": (18, "mg"),
    "Phosphorus": (1250, "mg"),
    "Iodine": (150, "mcg"),
    "Magnesium": (420, "mg"),
    "Zinc": (11, "mg"),
    "Selenium": (55, "mcg"),
    "Copper": (900, "mcg"),
    "Manganese": (2.3, "mg"),
    "Molybdenum": (45, "mcg"),
    "Chloride": (2300, "mg"),
    "Potassium": (4700, "mg"),
    "Choline": (550, "mg"),
}

# Units don't change by sex/age, only target amounts do — this is what
# to_canonical_unit() and the AI prompts (which just need "what unit is X
# measured in", not a personalized target) actually need.
#
# NUTRIENT_UNITS is ALSO the list the AI-estimate prompts ask for — kept to
# the original 30 on purpose (2026-11-05): fatty acids, flavonoids and
# carotenoids come ONLY from USDA data, never from a model's guess.
_DB_ONLY = {"ALA (omega-3)"}
NUTRIENT_UNITS: dict[str, str] = {
    nutrient: unit for nutrient, (_, unit) in MALE_RDA_19_50.items() if nutrient not in _DB_ONLY
}

# Every nutrient Quintacle knows a canonical unit for: the estimate set plus
# the USDA registry (nutrition_db/nutrients.py — omega-3/6, flavonoid
# classes, carotenoids, …). Canonicalization uses this.
ALL_NUTRIENT_UNITS: dict[str, str] = {
    **{k: v for k, v in _USDA_UNITS.items() if v != "kcal"},
    **{nutrient: unit for nutrient, (_, unit) in MALE_RDA_19_50.items()},
}

# Officially-sourced kinds, for the UI label next to a target.
TARGET_KIND: dict[str, str] = {"ALA (omega-3)": "AI (NIH ODS)"}

# Clearly-labelled REFERENCE figures — not RDAs, never shown as "% of RDA".
# "EPA + DHA" is a computed figure (EPA + DHA, mg) rather than a nutrient row.
REFERENCE_TARGETS: dict[str, dict] = {
    "EPA + DHA": {
        "low": 250, "high": 500, "unit": "mg",
        "label": "common guidance (250–500 mg/day, e.g. ~2 servings of fatty fish a week) — not an RDA",
    },
    "Flavan-3-ols": {
        "low": 400, "high": 600, "unit": "mg",
        "label": "research suggestion (400–600 mg/day, 2022 flavan-3-ol guideline) — not an RDA",
    },
}

_MCG_PER_UNIT = {"g": 1_000_000, "mg": 1_000, "mcg": 1}


def rda_for(sex: str | None, age: int | None) -> dict[str, tuple[float, str]]:
    """The real, personalized reference table for this person — falls back to
    the male/19-50 table if the profile isn't set up yet, same numbers this
    app always showed before personalization existed."""
    older = (age if age is not None else 30) >= 51
    if sex == "female":
        return FEMALE_RDA_51_PLUS if older else FEMALE_RDA_19_50
    return MALE_RDA_51_PLUS if older else MALE_RDA_19_50


def to_canonical_unit(amount: float, from_unit: str, nutrient: str) -> tuple[float, str]:
    """Converts a model-supplied (amount, unit) into the nutrient's canonical unit.
    A model that answers a known nutrient in the wrong unit (e.g. Copper in mg
    instead of mcg) gets converted, not silently mislabeled."""
    canonical_unit = ALL_NUTRIENT_UNITS.get(nutrient)
    if canonical_unit is None:
        return amount, from_unit
    if from_unit == canonical_unit:
        return amount, canonical_unit
    if from_unit not in _MCG_PER_UNIT or canonical_unit not in _MCG_PER_UNIT:
        # Can't convert (e.g. the model answered in IU) — keep the model's own unit
        # rather than mislabeling an unconverted number as canonical.
        return amount, from_unit
    return amount * _MCG_PER_UNIT[from_unit] / _MCG_PER_UNIT[canonical_unit], canonical_unit
