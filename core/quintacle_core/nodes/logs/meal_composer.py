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


def _format_meal_library(known_meals: list[dict]) -> str:
    lines = [f"name={m['name']!r} (one serving: {m['kcal']}kcal)" for m in known_meals]
    return (
        "Saved meal presets (each is one serving; a dish can include a whole saved meal as ONE "
        "component — use its exact name, don't break it into ingredients):\n" + "\n".join(lines)
    )


def suggest_meal_composition(
    description: str, known_ingredients: list[dict], provider: str | None = None,
    known_meals: list[dict] | None = None,
) -> MealCompositionSuggestion:
    system = _SYSTEM_PROMPT + "\n\n" + _format_ingredient_library(known_ingredients)
    if known_meals:
        system += "\n\n" + _format_meal_library(known_meals)
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


def _meal_component(meal: dict, comp: ComposedComponent) -> dict:
    """2026-11-11: a component that IS a saved meal preset. A meals row has
    no gram weight — its stored macros are ONE SERVING — so the component is
    one serving of that meal at the meal's own numbers (the model's gram and
    macro guess is discarded, exactly like a library-ingredient match).
    quantity_g is for display/scaling only: the composed meal's real
    ingredient weight when the caller knows it (`serving_g`), else the
    model's gram guess. basis_amount_g == quantity_g, so the review editor's
    rescale turns a quantity edit into a servings fraction (it scales
    `servings` along with the macros). Save sends {meal_id, servings}; the
    backend expands it (logs/api.py create_meal_from_ingredients) — it never
    becomes a duplicate new ingredient preset."""
    grams = float(meal.get("serving_g") or 0) or float(comp.quantity_g or 0) or 100.0
    return {
        "name": meal["name"],
        "ingredient_id": None,
        "meal_id": meal["id"],
        "servings": 1.0,
        "quantity_g": grams,
        "basis_amount_g": grams,
        "is_new": False,
        **{k: float(meal.get(k) or 0) for k in ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")},
        "source": "meal",
    }


def resolve_composition(
    suggestion: MealCompositionSuggestion, known_ingredients: list[dict], provider: str | None = None,
    use_usda: bool = True, known_meals: list[dict] | None = None,
) -> dict:
    """Deterministic pass, not AI: matches each proposed component's name
    against the real ingredient library via the same fuzzy-match used for
    exercise/substance names. A match means the component uses that
    ingredient's REAL stored macros (scaled to the proposed quantity) instead
    of the model's fallback guess — only genuinely new components keep the
    AI's estimate, staged for review as a new ingredient preset.

    2026-11-11: a component matching no ingredient but a SAVED MEAL preset
    (`known_meals`: meals-table rows, optionally with `serving_g`) is that
    meal, one serving — see _meal_component. Ingredients match first."""
    known_names = [i["name"] for i in known_ingredients]
    by_name = {i["name"]: i for i in known_ingredients}
    meal_names = [m["name"] for m in known_meals or []]
    meals_by_name = {m["name"]: m for m in known_meals or []}
    resolved = []
    for comp in suggestion.components:
        matched_name = canonicalize_name(comp.name, known_names)
        ingredient = by_name.get(matched_name)
        meal = None if ingredient is not None else meals_by_name.get(canonicalize_name(comp.name, meal_names))
        if meal is not None:
            resolved.append(_meal_component(meal, comp))
        elif ingredient is not None:
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
                        # 2026-11-11: micros the match lacked, filled from the same food's
                        # other USDA entry (each such micro carries from_fdc_id).
                        "usda_fill": usda.get("usda_fill") or [],
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
