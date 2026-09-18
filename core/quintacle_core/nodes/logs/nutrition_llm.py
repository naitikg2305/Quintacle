from __future__ import annotations

import anthropic
from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL
from ..vision import image_content_blocks
from .nutrition_targets import NUTRIENT_UNITS

_SYSTEM_PROMPT = (
    "Estimate full nutrition for a described food. Give macros (protein, carbs, fat, fiber, "
    "kcal in grams/kcal) and an amount for every one of these micronutrients, each in the "
    "exact unit specified — do not substitute a different unit (e.g. copper must be in mcg, "
    "not mg):\n"
    + "\n".join(f"- {nutrient}: {unit}" for nutrient, unit in NUTRIENT_UNITS.items())
    + "\n\nUse realistic food-composition knowledge. Include every micronutrient listed, "
    "even if the amount is 0 — don't skip any. Also state basis_amount_g: the weight in "
    "grams that your numbers above correspond to (the amount mentioned in the text, or 100 "
    "if none was given) — this is an ingredient preset, reusable at any quantity later by "
    "scaling against this basis."
)

_IMAGE_SYSTEM_PROMPT = (
    _SYSTEM_PROMPT
    + "\n\nYou're reading this from one or two photos of the SAME product/food (e.g. the front "
    "of a package plus its nutrition facts label, or a dish from two angles) — either a "
    "nutrition facts label (read the stated values directly; basis_amount_g is the label's "
    "serving size in grams, or 100 if it states per-100g) or a raw/prepared food item (estimate "
    "from what's visibly in the photo(s), plus any text given alongside it; basis_amount_g is "
    "your best estimate of the pictured quantity's weight in grams — when a label photo is "
    "present, prefer its printed values over a visual estimate). Also propose a short "
    "suggested_name for this ingredient (e.g. the product name on a label, or a plain "
    "description of the food)."
)


class MicroEstimate(BaseModel):
    nutrient: str
    amount: float
    unit: str


class NutritionEstimate(BaseModel):
    basis_amount_g: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    kcal: float
    micros: list[MicroEstimate]


class NutritionEstimateFromImage(NutritionEstimate):
    suggested_name: str


def estimate_nutrition(description: str) -> NutritionEstimate:
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": description}],
        output_format=NutritionEstimate,
    )
    return response.parsed_output


def estimate_nutrition_from_image(photos: list[tuple[bytes, str]], user_description: str = "") -> NutritionEstimateFromImage:
    """Vision-based counterpart to estimate_nutrition() — for one or two
    photographed nutrition labels/prepared meals (e.g. front of package +
    its label), not typed text. Feeds the same preset-creation flow
    (POST /logs/meals) once reviewed."""
    client = anthropic.Anthropic()
    content: list[dict] = image_content_blocks(photos)
    if user_description.strip():
        content.append({"type": "text", "text": user_description.strip()})
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=4096,
        system=_IMAGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_format=NutritionEstimateFromImage,
    )
    return response.parsed_output
