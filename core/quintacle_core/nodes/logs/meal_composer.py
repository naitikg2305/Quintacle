from __future__ import annotations

from pydantic import BaseModel

from ...llm_dispatch import parse_structured
from ..journal.normalize import canonicalize_name
from .nutrition_targets import NUTRIENT_UNITS

_SYSTEM_PROMPT = (
    "You help assemble a meal preset out of ingredients. Given a description of a dish being "
    "put together and a library of known ingredient presets, list every component: its name "
    "(match the library's naming if it's clearly the same thing), and the quantity used in "
    "grams. Also give your own best-guess nutrition estimate for that quantity of each "
    "component (protein/carbs/fat/fiber/kcal, plus every one of these micronutrients in the "
    "exact unit given, 0 if truly negligible) — this is only used as a fallback for anything "
    "not actually in the library, so it's fine if it's approximate for library items:\n"
    + "\n".join(f"- {nutrient}: {unit}" for nutrient, unit in NUTRIENT_UNITS.items())
    + "\n\nAlso propose meal_name, a short name for the finished dish."
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
    micros: list[MicroEstimate]


class MealCompositionSuggestion(BaseModel):
    meal_name: str
    components: list[ComposedComponent]


def _format_ingredient_library(known_ingredients: list[dict]) -> str:
    if not known_ingredients:
        return "Known ingredient library: (none saved yet)"
    lines = [f"id={i['id']} name={i['name']!r} (per {i['basis_amount_g']}g: {i['kcal']}kcal)" for i in known_ingredients]
    return "Known ingredient library:\n" + "\n".join(lines)


def suggest_meal_composition(
    description: str, known_ingredients: list[dict], provider: str | None = None
) -> MealCompositionSuggestion:
    system = _SYSTEM_PROMPT + "\n\n" + _format_ingredient_library(known_ingredients)
    return parse_structured(system, description, MealCompositionSuggestion, provider=provider, max_tokens=4096).parsed


def resolve_composition(
    suggestion: MealCompositionSuggestion, known_ingredients: list[dict]
) -> dict:
    """Deterministic pass, not AI: matches each proposed component's name
    against the real ingredient library via the same fuzzy-match used for
    exercise/substance names. A match means the component uses that
    ingredient's REAL stored macros (scaled to the proposed quantity) instead
    of the model's fallback guess — only genuinely new components keep the
    AI's estimate, staged for review as a new ingredient preset."""
    known_names = [i["name"] for i in known_ingredients]
    by_name = {i["name"]: i for i in known_ingredients}
    resolved = []
    for comp in suggestion.components:
        matched_name = canonicalize_name(comp.name, known_names)
        ingredient = by_name.get(matched_name)
        if ingredient is not None:
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
                }
            )
        else:
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
                    "new_ingredient_micros": [m.model_dump() for m in comp.micros],
                }
            )
    totals = {
        field: sum(c[field] for c in resolved) for field in ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")
    }
    return {"meal_name": suggestion.meal_name, "components": resolved, "totals": totals}
