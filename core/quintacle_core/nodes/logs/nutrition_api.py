"""/nutrition — the offline USDA db (status, install, match, food profile)
and full nutrient panels for an ingredient, a meal, a composer draft or a
day (2026-11-05). Every number is computed in code from stored presets /
the USDA db (nutrition_db.panel); nothing here calls a model except the
optional index-only candidate pick in /nutrition/match.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...nutrition_db import fetch as usda_fetch
from ...nutrition_db import store as usda
from ...nutrition_db.panel import build_panel
from .nutrition_targets import IS_LIMIT, REFERENCE_TARGETS, TARGET_KIND

router = APIRouter(prefix="/nutrition", tags=["nutrition"])

_MACROS = ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")


def _repo():
    from .api import get_repo  # lazy: logs.api imports this module's siblings

    return get_repo()


def current_targets() -> dict[str, dict]:
    from .api import _current_rda

    return {
        name: {"amount": amount, "unit": unit, "kind": TARGET_KIND.get(name, "RDA/DV"), "is_limit": name in IS_LIMIT}
        for name, (amount, unit) in _current_rda().items()
    }


def _panel(components: list[dict]) -> dict:
    return build_panel(components, current_targets(), REFERENCE_TARGETS)


# --- component resolvers (pure scaling of stored values) ---


def component_from_ingredient(repo, ingredient_id: int, grams: float, name: str | None = None) -> dict | None:
    ing = repo.get_ingredient(ingredient_id)
    if ing is None:
        return None
    ratio = grams / ing["basis_amount_g"] if ing["basis_amount_g"] else 0
    source = ing["source"] or "estimated"
    return {
        "name": name or ing["name"],
        "quantity_g": grams,
        "source": source,
        "fdc_id": ing["fdc_id"],
        "usda_description": ing["usda_description"],
        "macros": {k: ing[k] * ratio for k in _MACROS},
        "micros": [
            {"nutrient": m["nutrient"], "amount": m["amount"] * ratio, "unit": m["unit"],
             "source": m["source"] or source, "approx": bool(m["approx"])}
            for m in repo.micros_for_ingredient(ingredient_id)
        ],
    }


def component_from_fdc(fdc_id: int, grams: float, name: str | None = None) -> dict | None:
    fields = usda.preset_from_usda(fdc_id, grams)
    if fields is None:
        return None
    return {
        "name": name or fields["usda_description"],
        "quantity_g": grams,
        "source": "usda",
        "fdc_id": fdc_id,
        "usda_description": fields["usda_description"],
        "macros": {k: fields[k] for k in _MACROS},
        "micros": fields["micros"],
        "usda_fill": fields.get("usda_fill") or [],
    }


def components_for_meal(repo, meal_id: int, servings: float = 1) -> list[dict]:
    """A composed meal breaks down per ingredient; a flat preset is one
    component carrying its own stored micros."""
    meal = repo.get_meal(meal_id)
    if meal is None:
        return []
    parts = repo.meal_components(meal_id)
    if parts:
        out = []
        for p in parts:
            comp = component_from_ingredient(repo, p["ingredient_id"], p["quantity_g"] * servings)
            if comp:
                out.append(comp)
        return out
    return [{
        "name": meal["name"],
        "source": "estimated",
        "macros": {k: meal[k] * servings for k in _MACROS},
        "micros": [
            {"nutrient": m["nutrient"], "amount": m["amount"] * servings, "unit": m["unit"], "source": m["source"] or "estimated"}
            for m in repo.micros_for_meal(meal_id)
        ],
    }]


def components_for_day(repo, day: date) -> list[dict]:
    """Every food log entry of the day, flattened to ingredients so a
    contribution reads "Calcium: 62% from Greek yogurt". The same ingredient
    across meals merges into one contributor."""
    merged: dict[str, dict] = {}
    rows = repo.conn.execute(
        "SELECT meal_id, freeform_kcal, servings, meal_type FROM food_log WHERE date = ? ORDER BY id", (day.isoformat(),)
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        if r["meal_id"] is None:
            if r["freeform_kcal"]:
                out.append({"name": f"{r['meal_type']} (kcal only)", "source": "estimated",
                            "macros": {"kcal": r["freeform_kcal"] * r["servings"]}, "micros": []})
            continue
        for comp in components_for_meal(repo, r["meal_id"], r["servings"]):
            key = comp["name"]
            if key in merged:
                tgt = merged[key]
                for k, v in comp["macros"].items():
                    tgt["macros"][k] = tgt["macros"].get(k, 0) + v
                tgt["micros"] += comp["micros"]
                if "quantity_g" in comp:
                    tgt["quantity_g"] = tgt.get("quantity_g", 0) + comp["quantity_g"]
            else:
                merged[key] = {**comp, "macros": dict(comp["macros"]), "micros": list(comp["micros"])}
                out.append(merged[key])
    return out


# --- endpoints ---


@router.get("/db/status")
def db_status() -> dict:
    return {
        "installed": usda.is_installed(),
        "path": str(usda.db_path()),
        "summary": usda.summary(),
        "approx_download_mb": usda_fetch.APPROX_DOWNLOAD_MB,
        "job": usda_fetch.job_status(),
    }


@router.post("/db/install")
def db_install() -> dict:
    """Downloads the official USDA releases and builds the db in a
    background thread; poll /nutrition/db/status."""
    started = usda_fetch.start_install_job()
    return {"started": started, "job": usda_fetch.job_status()}


@router.get("/match")
def match(q: str, pick: bool = True) -> dict:
    """Ranked candidates (deterministic). pick=true also returns the chosen
    one — a model may only choose an index among these, never a number."""
    if not usda.is_installed():
        return {"installed": False, "candidates": [], "pick": None}
    candidates = usda.match_food(q)
    chosen = usda.pick_candidate(q, candidates) if pick else None
    return {"installed": True, "candidates": candidates, "pick": chosen}


@router.get("/food/{fdc_id}")
def food(fdc_id: int, grams: float = 100) -> dict:
    fields = usda.preset_from_usda(fdc_id, grams)
    if fields is None:
        raise HTTPException(404, "food not in the USDA db (or db not installed)")
    return fields


class BreakdownComponent(BaseModel):
    name: str = ""
    quantity_g: float = 100
    ingredient_id: int | None = None
    fdc_id: int | None = None
    # Inline values (an unsaved estimated component), already for quantity_g.
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0
    kcal: float = 0
    micros: list[dict] = []
    source: str = ""


class BreakdownRequest(BaseModel):
    components: list[BreakdownComponent]


@router.post("/breakdown")
def breakdown(body: BreakdownRequest) -> dict:
    """The composer's live panel: library ingredient → its stored values;
    fdc_id → the USDA db; otherwise the inline (estimated) values."""
    repo = _repo()
    comps = []
    for c in body.components:
        comp = None
        if c.ingredient_id is not None:
            comp = component_from_ingredient(repo, c.ingredient_id, c.quantity_g, c.name or None)
        elif c.fdc_id is not None:
            comp = component_from_fdc(c.fdc_id, c.quantity_g, c.name or None)
        if comp is None:
            comp = {
                "name": c.name or "unnamed",
                "quantity_g": c.quantity_g,
                "source": c.source or "estimated",
                "macros": {k: getattr(c, k) for k in _MACROS},
                "micros": c.micros,
            }
        comps.append(comp)
    return _panel(comps)


@router.get("/ingredient/{ingredient_id}")
def ingredient_panel(ingredient_id: int, grams: float | None = None) -> dict:
    repo = _repo()
    ing = repo.get_ingredient(ingredient_id)
    if ing is None:
        raise HTTPException(404, "no such ingredient")
    comp = component_from_ingredient(repo, ingredient_id, grams if grams is not None else ing["basis_amount_g"])
    return {**_panel([comp]), "source": comp["source"], "fdc_id": comp["fdc_id"], "usda_description": comp["usda_description"]}


@router.get("/meal/{meal_id}")
def meal_panel(meal_id: int, servings: float = 1) -> dict:
    repo = _repo()
    if repo.get_meal(meal_id) is None:
        raise HTTPException(404, "no such meal")
    return _panel(components_for_meal(repo, meal_id, servings))


@router.get("/day/{for_date}")
def day_panel(for_date: date) -> dict:
    return {"date": for_date.isoformat(), **_panel(components_for_day(_repo(), for_date))}
