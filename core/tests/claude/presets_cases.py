"""PRESET checks (routine / ingredient / meal), written once and run by BOTH
live suites (each suite's test module binds `client` + `provider`).

Seeded by cases.seed: meals "Chicken rice bowl" + "Greek yogurt bowl", routine
"Push day" (Bench press, Overhead press, Dips). Expectations are the RIGHT
product answers, fixed up front; a failure is a finding about the model or
the code, never a reason to re-fit the expectation.
"""
import re

from tests.claude.harness import drop, first, types

PULL_DAY = "my pull day: deadlift 3x5, barbell row 4x8, pull-ups 3x10, face pulls"
PULL_DAY_EXERCISES = ["Deadlift", "Barbell row", "Pull-ups", "Face pulls"]
PUSH_DAY_LOG = "did push day today"
PUSH_DAY_EXERCISES = ["Bench press", "Overhead press", "Dips"]
ROUTINE_PREFIX = "routine: Pull day = Deadlift, Barbell row, Pull-ups, Face pulls"
INGREDIENT_PREFIX = "ingredient: Fage 0% greek yogurt, per 170g: 90 kcal, 18g protein, 5g carbs, 0g fat"
INGREDIENT_EXPECT = {"basis_amount_g": 170, "kcal": 90, "protein_g": 18, "carbs_g": 5, "fat_g": 0}
MEAL_PREFIX = "meal: chicken rice bowl plus a greek yogurt bowl"
RECIPE_PREFIX = "recipe: chicken rice bowl plus a greek yogurt bowl"
SEEDED_MEALS = ["Chicken rice bowl", "Greek yogurt bowl"]


def _key(name: str) -> str:
    """'Pull-ups' / 'pull ups' / 'Pullup' -> 'pullup' (spelling-tolerant, meaning-strict)."""
    k = re.sub(r"[^a-z]", "", (name or "").lower())
    return k[:-1] if k.endswith("s") else k


def _covers(actual: list[str], expected: list[str]) -> list[str]:
    """Expected names with no matching actual name (each actual used once)."""
    pool = [_key(a) for a in actual]
    missing = []
    for e in expected:
        hit = next((i for i, a in enumerate(pool) if _key(e) in a), None)
        if hit is None:
            missing.append(e)
        else:
            pool.pop(hit)
    return missing


def _seeded_meal_ids(c) -> dict[str, int]:
    r = c.get("/logs/meals")
    assert r.status_code == 200, r.text
    return {m["name"]: m["id"] for m in r.json() if m["name"] in SEEDED_MEALS}


def check_pull_day_unprefixed(c, provider):
    """Text naming a day and listing 4 exercises with set schemes DEFINES a reusable routine: propose it, named for the day, with exactly those 4 exercises."""
    r = drop(c, text=PULL_DAY, provider=provider)
    e = first(r, "workout_routine")
    name = e.get("name") or ""
    assert "pull" in name.lower() and len(name) <= 30 and not re.search(r"\d", name), f"name={name!r}"
    ex = e.get("exercises") or []
    assert len(ex) == 4 and not _covers(ex, PULL_DAY_EXERCISES), f"exercises={ex!r}"
    assert not any(re.search(r"\d\s*[x×]\s*\d", x) for x in ex), f"set schemes leaked into names: {ex!r}"


def check_push_day_log_not_preset(c, provider):
    """'did push day today' LOGS the existing Push day routine: its exercises as an exercise log, never a second (duplicate) routine preset."""
    r = drop(c, text=PUSH_DAY_LOG, provider=provider)
    t = types(r)
    assert "workout_routine" not in t, f"duplicate routine preset proposed: {t}"
    logged = [e.get("exercise_name") or "" for e in r.get("entries", []) if e.get("type") == "exercise"]
    assert not _covers(logged, PUSH_DAY_EXERCISES), f"exercise log={logged!r} types={t}"


def check_routine_prefix(c, provider):
    """'routine: Name = a, b, c' is the typed, unambiguous shape: deterministic, the name and exercises exactly as written."""
    e = first(drop(c, text=ROUTINE_PREFIX, provider=provider), "workout_routine")
    assert e.get("name") == "Pull day", e
    assert e.get("exercises") == PULL_DAY_EXERCISES, e


def check_ingredient_prefix_label(c, provider):
    """Typed label numbers are the owner's own data: the preset carries them EXACTLY (per 170g), source=label, named for the food alone."""
    e = first(drop(c, text=INGREDIENT_PREFIX, provider=provider), "ingredient_preset")
    got = {k: e.get(k) for k in INGREDIENT_EXPECT}
    assert all(got[k] is not None and abs(float(got[k]) - v) < 1e-6 for k, v in INGREDIENT_EXPECT.items()), got
    assert e.get("source") == "label", f"source={e.get('source')!r}"
    name = (e.get("suggested_name") or "").lower()
    assert "yogurt" in name and "kcal" not in name and "protein" not in name, f"suggested_name={e.get('suggested_name')!r}"


def check_meal_prefix_seeded(c, provider):
    """'meal:' means 'I ate this': two food logs pointing at the two seeded meals (meal_id), no new meal/ingredient presets."""
    ids = _seeded_meal_ids(c)
    assert len(ids) == 2, ids
    r = drop(c, text=MEAL_PREFIX, provider=provider)
    t = types(r)
    assert "meal_composition" not in t and "ingredient_preset" not in t, f"new presets proposed: {t}"
    food = [e for e in r.get("entries", []) if e.get("type") == "food"]
    linked = {e.get("meal_id") for e in food}
    assert set(ids.values()) <= linked, f"meal_ids={linked} want {ids}; food={food}"


def check_recipe_from_seeded(c, provider):
    """A composition built from the seeded presets reuses them (is_new False); re-creating them as new ingredients is duplicate noise."""
    e = first(drop(c, text=RECIPE_PREFIX, provider=provider), "meal_composition")
    comps = e.get("components") or []
    assert len(comps) == 2, f"components={comps}"
    assert all(comp.get("is_new") is False for comp in comps), f"new components: {[(x.get('name'), x.get('is_new')) for x in comps]}"
    assert not _covers([x.get("name") or "" for x in comps], SEEDED_MEALS), [x.get("name") for x in comps]


ALL = [check_pull_day_unprefixed, check_push_day_log_not_preset, check_routine_prefix,
       check_ingredient_prefix_label, check_meal_prefix_seeded, check_recipe_from_seeded]

# Need no model at all, so the Max suite must not demand a Claude call for them.
DETERMINISTIC = {check_routine_prefix}
