from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Body
from pydantic import BaseModel

from ... import clock
from ...graph_capture import safe_journal_graph_links
from ..profile.store import ProfileStore
from ..profile.targets import age_years
from .log_store import LogFileStore, rebuild_sqlite_index
from .meal_composer import resolve_composition, suggest_meal_composition
from .nutrition_llm import estimate_nutrition
from .nutrition_targets import IS_LIMIT, rda_for, to_canonical_unit
from .quotas import habit_history, habit_progress
from .repository import LogsRepository
from .routine_llm import resolve_workout_routine, suggest_workout_routine

# Graph write-rule coverage decision (docs/graph-model.md, graph_capture.py):
# the NUMERIC log endpoints here — food, exercise, substances, body stats,
# expenses — deliberately do NOT run the keyword linker. Their day-association
# already lives in SQLite rows keyed by date (that's the whole point of this
# module), and their text fields are names of things ("bench press", a
# merchant string), not prose about people/places — matching those against
# person names would manufacture edges, not capture them. ACTIVITIES are the
# one exception: their description is real narrative ("Went to Mia Italina
# Kitchen in Alexandria with Sam"), so log_activity links it from the day it
# happened — the same journal: day anchor and shared helper the journal
# write paths use.
router = APIRouter(prefix="/logs", tags=["logs"])
_repo: LogsRepository | None = None
_log_store: LogFileStore | None = None
_profile_store: ProfileStore | None = None


def init_repo(conn, log_store: LogFileStore | None = None) -> None:
    global _repo, _log_store
    _log_store = log_store
    _repo = LogsRepository(conn, log_store)


def get_repo() -> LogsRepository:
    if _repo is None:
        raise RuntimeError("logs repository not initialized — call init_repo() first")
    return _repo


def get_log_store() -> LogFileStore | None:
    return _log_store


def init_profile_ref(profile_store: ProfileStore) -> None:
    """Wired by the main app after both stores exist — logs needs the profile's
    sex/age to personalize %RDA targets, but importing profile.api directly
    would create a cycle (profile.api already imports logs.api)."""
    global _profile_store
    _profile_store = profile_store


def _current_rda() -> dict[str, tuple[float, str]]:
    if _profile_store is None:
        return rda_for(None, None)
    profile = _profile_store.load()
    age = age_years(profile.birthdate, clock.today()) if profile.birthdate else None
    return rda_for(profile.sex, age)


class MicroInput(BaseModel):
    nutrient: str
    amount: float
    unit: str


class MealCreate(BaseModel):
    name: str
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0
    kcal: float
    notes: str = ""
    micros: list[MicroInput] = []


class IngredientCreate(BaseModel):
    name: str
    basis_amount_g: float = 100
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0
    kcal: float
    notes: str = ""
    micros: list[MicroInput] = []


class MealComponentInput(BaseModel):
    ingredient_id: int | None = None
    name: str = ""
    quantity_g: float
    # Only used when ingredient_id is None — creates this as a new ingredient
    # preset first, then uses it in the meal.
    basis_amount_g: float = 100
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0
    kcal: float = 0
    micros: list[MicroInput] = []


class MealFromIngredientsCreate(BaseModel):
    name: str
    notes: str = ""
    components: list[MealComponentInput]


class SuggestCompositionRequest(BaseModel):
    description: str


class FoodLogCreate(BaseModel):
    date: date
    meal_type: str
    meal_id: int | None = None
    freeform_kcal: float | None = None
    servings: float = 1
    notes: str = ""


class SubstanceLogCreate(BaseModel):
    date: date
    substance: str
    amount: float
    notes: str = ""


class ExpenseLogCreate(BaseModel):
    date: date
    amount: float
    merchant: str = ""
    category: str = ""
    notes: str = ""
    kind: str = "regular"


class IncomeLogCreate(BaseModel):
    date: date
    amount: float
    source: str = ""
    kind: str = "salary"  # salary | other (next-wave-plan §1 decision 3)
    notes: str = ""


class ActivityLogCreate(BaseModel):
    date: date
    category: str
    description: str
    hours: float = 0


class ExerciseSetInput(BaseModel):
    reps: int | None = None
    weight: float | None = None
    weight_unit: str = "lb"
    duration_min: float | None = None
    distance: float | None = None
    distance_unit: str = "mi"
    calories_burned: float | None = None


class ExerciseLogCreate(BaseModel):
    date: date
    exercise_name: str
    sets: list[ExerciseSetInput] = []
    notes: str = ""


class BodyStatCreate(BaseModel):
    date: date
    metric: str
    value: float
    unit: str = ""


class HabitCreate(BaseModel):
    name: str
    target_amount: float
    target_period: str
    match_category: str | None = None
    unit: str = ""
    metric: str = "activity_hours"
    direction: str = "at_least"
    # Budget lines: for metric="spend", match_kind narrows to one of the 7
    # expense kinds and match_category holds comma-separated whole-word text
    # terms (merchant/category/notes) — see repository.spend_for_habit_between.
    match_kind: str | None = None


@router.post("/meals")
def create_meal(body: MealCreate) -> dict:
    repo = get_repo()
    # Convert to the RDA reference table's canonical unit — a model that answers
    # a known nutrient in the wrong unit (this bit us once: Copper in mg instead
    # of mcg) would otherwise silently corrupt the %RDA math later.
    micros = _canonicalize_micros(body.micros)
    meal_id = repo.add_meal(body.name, body.protein_g, body.carbs_g, body.fat_g, body.kcal, body.fiber_g, body.notes, micros)
    return {"id": meal_id, **body.model_dump()}


@router.get("/meals")
def list_meals() -> list[dict]:
    return [dict(row) for row in get_repo().list_meals()]


@router.get("/meals/{meal_id}/micros")
def meal_micros(meal_id: int) -> list[dict]:
    return [dict(row) for row in get_repo().micros_for_meal(meal_id)]


@router.post("/meals/estimate")
def estimate_meal(content: str = Body(..., media_type="text/plain")) -> dict:
    """Proposes full macro+micro nutrition for a described food — never writes.
    Review/edit, then POST /logs/meals to actually create the preset."""
    return estimate_nutrition(content).model_dump()


def _canonicalize_micros(micros: list[MicroInput]) -> list[dict]:
    result = []
    for micro in micros:
        amount, unit = to_canonical_unit(micro.amount, micro.unit, micro.nutrient)
        result.append({"nutrient": micro.nutrient, "amount": amount, "unit": unit})
    return result


@router.post("/ingredients")
def create_ingredient(body: IngredientCreate) -> dict:
    repo = get_repo()
    micros = _canonicalize_micros(body.micros)
    ingredient_id = repo.add_ingredient(
        body.name, body.protein_g, body.carbs_g, body.fat_g, body.kcal, body.fiber_g, body.basis_amount_g, body.notes, micros
    )
    return {"id": ingredient_id, **body.model_dump()}


@router.get("/ingredients")
def list_ingredients() -> list[dict]:
    return [dict(row) for row in get_repo().list_ingredients()]


class RoutineCreate(BaseModel):
    name: str
    exercises: list[str]


@router.post("/routines")
def create_routine(body: RoutineCreate) -> dict:
    name = get_repo().add_routine(body.name, body.exercises)
    return {"name": name, "exercises": body.exercises}


@router.get("/routines")
def list_routines() -> list[dict]:
    return get_repo().list_routines()


class SuggestRoutineRequest(BaseModel):
    description: str


@router.post("/routines/suggest")
def suggest_routine_endpoint(body: SuggestRoutineRequest) -> dict:
    """AI proposes an ordered exercise list for a routine from a freeform
    description (e.g. discussed in chat); resolve_workout_routine() then
    deterministically matches each exercise against the real exercise-name
    library. Never writes."""
    known_names = sorted({e["exercise_name"] for e in (get_log_store().all_entries("exercise") if get_log_store() else [])})
    suggestion = suggest_workout_routine(body.description, known_names)
    return resolve_workout_routine(suggestion, known_names)


@router.get("/ingredients/{ingredient_id}/micros")
def ingredient_micros(ingredient_id: int) -> list[dict]:
    return [dict(row) for row in get_repo().micros_for_ingredient(ingredient_id)]


@router.get("/meals/{meal_id}/components")
def meal_components(meal_id: int) -> list[dict]:
    return [dict(row) for row in get_repo().meal_components(meal_id)]


@router.post("/meals/suggest-composition")
def suggest_composition(body: SuggestCompositionRequest) -> dict:
    """AI proposes a component list + fallback estimates from a freeform
    description; resolve_composition() then deterministically matches each
    component against the real ingredient library — a match uses the
    library's real macros, not the model's guess. Never writes."""
    known = [dict(row) for row in get_repo().list_ingredients()]
    suggestion = suggest_meal_composition(body.description, known)
    return resolve_composition(suggestion, known)


@router.post("/meals/from-ingredients")
def create_meal_from_ingredients(body: MealFromIngredientsCreate) -> dict:
    """Commits a composed meal preset. Any component with no ingredient_id is
    created as a new ingredient preset first; totals are then computed
    deterministically (see LogsRepository.compute_meal_totals) — never re-guessed."""
    repo = get_repo()
    resolved_components = []
    for comp in body.components:
        if comp.ingredient_id is not None:
            resolved_components.append({"ingredient_id": comp.ingredient_id, "quantity_g": comp.quantity_g})
        else:
            micros = _canonicalize_micros(comp.micros)
            ingredient_id = repo.add_ingredient(
                comp.name or body.name, comp.protein_g, comp.carbs_g, comp.fat_g, comp.kcal,
                comp.fiber_g, comp.basis_amount_g, "", micros,
            )
            resolved_components.append({"ingredient_id": ingredient_id, "quantity_g": comp.quantity_g})
    meal_id = repo.add_meal_from_ingredients(body.name, resolved_components, body.notes)
    return {"id": meal_id, "components": [dict(row) for row in repo.meal_components(meal_id)]}


@router.post("/food")
def log_food(body: FoodLogCreate) -> dict:
    entry_id = get_repo().log_food(
        body.date, body.meal_type, body.meal_id, body.freeform_kcal, body.servings, body.notes
    )
    return {"id": entry_id, **body.model_dump(mode="json")}


@router.get("/food/{for_date}")
def food_for_date(for_date: date) -> dict:
    entries = [dict(row) for row in get_repo().food_log_for_date(for_date)]
    totals = dict(get_repo().daily_totals(for_date))
    return {"date": for_date.isoformat(), "entries": entries, "totals": totals}


@router.post("/substances")
def log_substance(body: SubstanceLogCreate) -> dict:
    entry_id = get_repo().log_substance(body.date, body.substance, body.amount, body.notes)
    return {"id": entry_id, **body.model_dump(mode="json")}


@router.post("/expenses")
def log_expense(body: ExpenseLogCreate) -> dict:
    entry_id = get_repo().log_expense(body.date, body.amount, body.merchant, body.category, body.notes, body.kind)
    return {"id": entry_id, **body.model_dump(mode="json")}


@router.get("/expenses")
def expenses_between(start: date, end: date) -> list[dict]:
    return [dict(row) for row in get_repo().expenses_between(start, end)]


@router.post("/income")
def log_income(body: IncomeLogCreate) -> dict:
    entry_id = get_repo().log_income(body.date, body.amount, body.source, body.kind, body.notes)
    return {"id": entry_id, **body.model_dump(mode="json")}


@router.get("/income")
def income_between(start: date, end: date) -> list[dict]:
    return [dict(row) for row in get_repo().income_between(start, end)]


@router.post("/activities")
def log_activity(body: ActivityLogCreate) -> dict:
    entry_id = get_repo().log_activity(body.date, body.category, body.description, body.hours)
    # See the module-top coverage note: activity descriptions are narrative,
    # so they link (people/experiences/place emergence) from their day's
    # journal: node — additive, never blocking the log write itself.
    safe_journal_graph_links(body.date, body.description)
    return {"id": entry_id, **body.model_dump(mode="json")}


@router.get("/activities/{for_date}")
def activities_for_date(for_date: date) -> list[dict]:
    return [dict(row) for row in get_repo().activities_for_date(for_date)]


@router.get("/activities")
def activities_between(start: date, end: date) -> list[dict]:
    return [dict(row) for row in get_repo().activities_between(start, end)]


@router.post("/exercise")
def log_exercise(body: ExerciseLogCreate) -> dict:
    sets = [s.model_dump() for s in body.sets]
    entry_id = get_repo().log_exercise(body.date, body.exercise_name, sets, body.notes)
    return {"id": entry_id, **body.model_dump(mode="json")}


@router.get("/exercise-names")
def known_exercise_names() -> list[str]:
    """For an autocomplete on manual entry — everything you've already
    logged, deduplicated. Not a separate presets table; your own history is
    the preset list."""
    rows = get_repo().conn.execute("SELECT DISTINCT exercise_name FROM exercise_sets ORDER BY exercise_name").fetchall()
    return [r["exercise_name"] for r in rows]


@router.post("/body-stats")
def log_body_stat(body: BodyStatCreate) -> dict:
    entry_id = get_repo().log_body_stat(body.date, body.metric, body.value, body.unit)
    return {"id": entry_id, **body.model_dump(mode="json")}


@router.post("/habits")
def create_habit(body: HabitCreate) -> dict:
    habit_id = get_repo().add_habit(
        body.name, body.target_amount, body.target_period, body.match_category, body.unit, body.metric, body.direction,
        body.match_kind,
    )
    return {"id": habit_id, **body.model_dump()}


@router.get("/habits")
def list_habits() -> list[dict]:
    return [dict(row) for row in get_repo().list_habits()]


@router.get("/habits/{habit_id}/progress")
def get_habit_progress(habit_id: int) -> dict:
    return habit_progress(get_repo(), habit_id)


@router.get("/habits/{habit_id}/history")
def get_habit_history(habit_id: int, periods: int = 8) -> list[dict]:
    return habit_history(get_repo(), habit_id, periods)


@router.post("/rebuild-index")
def rebuild_index() -> dict:
    """Regenerates every SQLite log table from the markdown files — proves
    (and restores, if the db is ever lost/corrupted) that markdown, not
    SQLite, is the real record."""
    if _log_store is None:
        return {"error": "no log store configured"}
    return rebuild_sqlite_index(_log_store, get_repo().conn, get_repo().preset_store, get_repo().ingredient_store)


@router.get("/nutrition/{for_date}")
def nutrition_for_date(for_date: date) -> dict:
    """Full picture for one day: macros (incl. fiber) + every tracked micronutrient
    against YOUR real RDA reference (sex + age from Profile), so 0-intake
    nutrients still show up at 0%."""
    repo = get_repo()
    macros = dict(repo.daily_totals(for_date))
    logged = {row["nutrient"]: row for row in repo.micros_between(for_date, for_date)}

    micros = []
    for nutrient, (target_amount, unit) in _current_rda().items():
        amount = logged[nutrient]["total_amount"] if nutrient in logged else 0.0
        micros.append(
            {
                "nutrient": nutrient,
                "amount": amount,
                "unit": unit,
                "rda": target_amount,
                "pct_of_rda": round(amount / target_amount * 100, 1),
                "is_limit": nutrient in IS_LIMIT,
            }
        )

    calories_burned = repo.total_calories_burned(for_date)
    energy_balance = {
        "kcal_in": macros["total_kcal"],
        "kcal_burned": calories_burned,
        "net_kcal": macros["total_kcal"] - calories_burned,
    }

    return {"date": for_date.isoformat(), "macros": macros, "micros": micros, "energy_balance": energy_balance}


@router.get("/nutrition-history")
def nutrition_history(days: int = 8) -> list[dict]:
    """Last N days of kcal/protein actuals, oldest first — the dashboard's
    trend line against your personalized target from /profile/targets."""
    repo = get_repo()
    today = clock.today()
    history = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        totals = repo.daily_totals(d)
        history.append(
            {
                "date": d.isoformat(),
                "kcal": totals["total_kcal"],
                "protein_g": totals["total_protein_g"],
                "kcal_burned": repo.total_calories_burned(d),
            }
        )
    return history
