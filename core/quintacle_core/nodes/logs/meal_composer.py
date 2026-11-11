from __future__ import annotations

from pydantic import BaseModel
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
    "like 'basmati rice, cooked'), and the quantity used in grams. Also give a rough macro "
    "estimate for that quantity (protein/carbs/fat/fiber/kcal) — only a fallback, approximate "
    "is fine. Also propose meal_name, a short name for the finished dish."
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
    return parse_structured(system, description, MealCompositionSuggestion, provider=provider, max_tokens=1024).parsed


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


def resolve_composition(
    suggestion: MealCompositionSuggestion, known_ingredients: list[dict], provider: str | None = None,
    use_usda: bool = True,
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
