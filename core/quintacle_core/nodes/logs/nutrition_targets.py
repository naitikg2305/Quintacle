from __future__ import annotations

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
}

FEMALE_RDA_51_PLUS: dict[str, tuple[float, str]] = {
    **FEMALE_RDA_19_50,
    "Vitamin B6": (1.5, "mg"),
    "Vitamin D": (20, "mcg"),
    "Iron": (8, "mg"),  # post-menopause drop — the biggest sex/age swing in this table
    "Calcium": (1200, "mg"),
}

IS_LIMIT = {"Sodium", "Saturated Fat", "Cholesterol", "Added Sugars"}

# Units don't change by sex/age, only target amounts do — this is what
# to_canonical_unit() and the AI prompts (which just need "what unit is X
# measured in", not a personalized target) actually need.
NUTRIENT_UNITS: dict[str, str] = {nutrient: unit for nutrient, (_, unit) in MALE_RDA_19_50.items()}

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
    canonical_unit = NUTRIENT_UNITS.get(nutrient)
    if canonical_unit is None:
        return amount, from_unit
    if from_unit == canonical_unit:
        return amount, canonical_unit
    if from_unit not in _MCG_PER_UNIT or canonical_unit not in _MCG_PER_UNIT:
        # Can't convert (e.g. the model answered in IU) — keep the model's own unit
        # rather than mislabeling an unconverted number as canonical.
        return amount, from_unit
    return amount * _MCG_PER_UNIT[from_unit] / _MCG_PER_UNIT[canonical_unit], canonical_unit
