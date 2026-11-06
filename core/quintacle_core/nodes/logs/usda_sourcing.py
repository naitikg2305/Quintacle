"""Ingredient presets sourced from USDA when a match exists (2026-11-05).

Precedence: a printed nutrition label wins for packaged products (source
"label"), with any nutrient the label doesn't list filled from the generic
USDA match (tagged per nutrient). Otherwise a USDA match supplies every
number (source "usda"). Only when nothing matches does the AI estimate
stand (source "estimated"). Matching is deterministic; the model at most
picks an index among candidates (nutrition_db.store.pick_candidate).
"""
from __future__ import annotations

import re

from ...nutrition_db import store as usda

_LABEL_CUES = re.compile(
    r"\b(nutrition facts|serving size|per serving|calories|kcal|cal\b|protein\s*\d|\d+(\.\d+)?\s*g\s*(protein|carbs?|fat|fiber)|"
    r"(protein|carbs?|fat|fiber)\s*:?\s*\d)",
    re.I,
)
_GRAMS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:g|grams?)\b", re.I)


def looks_like_label_text(text: str) -> bool:
    """Typed-out label numbers ("protein 20g, 120 kcal") — those values are
    the owner's own data and win; a plain food name goes to USDA."""
    return bool(_LABEL_CUES.search(text or ""))


def basis_from_text(text: str, default: float = 100) -> float:
    m = _GRAMS.search(text or "")
    return float(m.group(1)) if m else default


def slim(candidates: list[dict]) -> list[dict]:
    return [{k: c[k] for k in ("fdc_id", "description", "category", "source", "score")} for c in candidates]


def usda_proposal(name: str, basis_amount_g: float = 100, provider: str | None = None) -> dict | None:
    """Preset fields from the picked USDA match, with the candidate list for
    the UI's override picker; None when the db is missing or nothing fits."""
    if not usda.is_installed():
        return None
    pick, candidates = usda.match_and_pick(name, provider)
    if pick is None:
        return {"usda_candidates": slim(candidates), "matched": False} if candidates else None
    fields = usda.preset_from_usda(pick["fdc_id"], basis_amount_g)
    if fields is None:
        return None
    return {**fields, "usda_candidates": slim(candidates), "matched": True}


def merge_label_with_usda(label_micros: list[dict], fdc_id: int, basis_amount_g: float) -> list[dict]:
    """Label micros (tagged source=label) + every USDA nutrient the label
    didn't state (tagged source=usda), scaled to the label's basis."""
    out = [{**m, "source": "label"} for m in label_micros]
    have = {m["nutrient"] for m in label_micros}
    fill = usda.preset_from_usda(fdc_id, basis_amount_g)
    if fill:
        out += [m for m in fill["micros"] if m["nutrient"] not in have]
    return out


def resolve_ingredient_numbers(
    *,
    name: str,
    basis_amount_g: float,
    macros: dict,
    micros: list[dict],
    source: str = "",
    fdc_id: int | None = None,
    auto_match: bool = False,
    provider: str | None = None,
) -> dict:
    """The write-time authority for an ingredient preset's numbers. Returns
    {macros, micros, source, fdc_id, usda_description}. For source=usda the
    client's numbers are IGNORED and re-read from the db — a proposal can't
    smuggle edited/guessed numbers in under a USDA badge."""
    if fdc_id is None and auto_match and source != "label" and usda.is_installed():
        pick, _ = usda.match_and_pick(name, provider)
        if pick is not None:
            fdc_id = pick["fdc_id"]
            source = "usda"
    if fdc_id is not None and usda.is_installed():
        meta = usda.food(fdc_id)
        if meta is not None:
            if source == "label":
                return {
                    "macros": macros,
                    "micros": merge_label_with_usda(micros, fdc_id, basis_amount_g),
                    "source": "label",
                    "fdc_id": fdc_id,
                    "usda_description": meta["description"],
                }
            fields = usda.preset_from_usda(fdc_id, basis_amount_g)
            return {
                "macros": {k: fields[k] for k in ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")},
                "micros": fields["micros"],
                "source": "usda",
                "fdc_id": fdc_id,
                "usda_description": meta["description"],
            }
    if source == "usda":  # asked for USDA but the db/food isn't there
        source = "estimated"
    tag = source or ""
    return {
        "macros": macros,
        "micros": [{**m, "source": m.get("source") or tag} for m in micros] if tag else micros,
        "source": source,
        "fdc_id": None,
        "usda_description": "",
    }


def backfill(repo, dry_run: bool = True, provider: str | None = None) -> dict:
    """Re-sources existing presets: estimated/legacy → USDA numbers; label →
    gaps filled from USDA. Composed meals using a changed ingredient are
    recomputed (deterministic totals). Dry run reports the plan only."""
    if not usda.is_installed():
        return {"installed": False, "dry_run": dry_run, "changes": [], "skipped": []}
    changes, skipped = [], []
    for ing in [dict(r) for r in repo.list_ingredients()]:
        current = ing.get("source") or ""
        if current == "usda":
            skipped.append({"id": ing["id"], "name": ing["name"], "reason": "already usda"})
            continue
        pick, candidates = usda.match_and_pick(ing["name"], provider)
        if pick is None:
            skipped.append({"id": ing["id"], "name": ing["name"], "reason": "no confident match",
                            "candidates": slim(candidates[:3])})
            continue
        new_source = "label" if current == "label" else "usda"
        micros = [dict(m) for m in repo.micros_for_ingredient(ing["id"])]
        resolved = resolve_ingredient_numbers(
            name=ing["name"], basis_amount_g=ing["basis_amount_g"],
            macros={k: ing[k] for k in ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")},
            micros=[{k: m[k] for k in ("nutrient", "amount", "unit")} for m in micros if (m.get("source") or "") != "usda"]
            if new_source == "label" else [],
            source=new_source, fdc_id=pick["fdc_id"],
        )
        change = {
            "id": ing["id"], "name": ing["name"], "from_source": current or "unknown", "to_source": resolved["source"],
            "fdc_id": pick["fdc_id"], "usda_description": pick["description"], "score": pick["score"],
            "kcal_before": ing["kcal"], "kcal_after": resolved["macros"]["kcal"],
            "micros_before": len(micros), "micros_after": len(resolved["micros"]),
        }
        changes.append(change)
        if dry_run:
            continue
        repo.add_ingredient(
            ing["name"], resolved["macros"]["protein_g"], resolved["macros"]["carbs_g"], resolved["macros"]["fat_g"],
            resolved["macros"]["kcal"], resolved["macros"]["fiber_g"], ing["basis_amount_g"], ing.get("notes", ""),
            resolved["micros"], source=resolved["source"], fdc_id=resolved["fdc_id"],
            usda_description=resolved["usda_description"], exact_name=True,
        )
    recomputed = []
    if not dry_run and changes:
        changed_ids = {c["id"] for c in changes}
        for meal in [dict(r) for r in repo.list_meals()]:
            comps = [dict(c) for c in repo.meal_components(meal["id"])]
            if comps and any(c["ingredient_id"] in changed_ids for c in comps):
                repo.add_meal_from_ingredients(
                    meal["name"], [{"ingredient_id": c["ingredient_id"], "quantity_g": c["quantity_g"]} for c in comps],
                    meal.get("notes", ""),
                )
                recomputed.append(meal["name"])
    return {"installed": True, "dry_run": dry_run, "changes": changes, "skipped": skipped, "meals_recomputed": recomputed}
