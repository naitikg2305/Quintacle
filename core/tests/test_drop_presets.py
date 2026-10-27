"""The additive preset suggestion in POST /drop: the deterministic gate
(drop_router.looks_like_preset) plus the unprefixed-text-only proposal that
rides alongside the primary classification. Extractors are monkeypatched at
the api module — deterministic, no model call. Registry dedupe tests seed real
meals/routines/ingredients through the logs endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.nodes.drop_router import looks_like_preset
from quintacle_core.nodes.journal.llm import FoodEntry
from quintacle_core.nodes.logs.meal_composer import ComposedComponent, MealCompositionSuggestion
from quintacle_core.nodes.logs.nutrition_llm import NutritionEstimate
from quintacle_core.nodes.logs.routine_llm import WorkoutRoutineSuggestion

# --- gate matrix ----------------------------------------------------------

POSITIVE = [
    ("meal_composition", "200g rice, 150g chicken breast, 100g broccoli"),
    ("meal_composition", "my usual bowl: 1 cup of rice, 6 oz of salmon, 2 tbsp of soy sauce"),
    ("meal_composition", "recipe: 300 g pasta and 200 g tomato sauce"),
    ("meal_composition", "I make a smoothie with 1 cup of oats, 250 ml milk and 30 g protein powder"),
    ("meal_composition", "chicken 200g\nrice 150g\nbeans 80g"),
    ("meal_composition", "ate 200g chicken, 100g rice and 50g broccoli"),
    ("workout_routine", "bench press 3x8, overhead press 3x10, tricep pushdown 3x12"),
    ("workout_routine", "squat 4 sets of 5\nromanian deadlift 3 sets of 8\nleg press 3x12"),
    ("workout_routine", "my push pull legs split: bench 3x8"),
    ("workout_routine", "pull day = pull-ups, rows, lat pulldown, curls"),
    ("workout_routine", "new routine: deadlift 5x3"),
    ("workout_routine", "Day 1: squat 5x5, bench 5x5"),
    ("ingredient_preset", "Nutrition facts: calories 120, protein 20g, carbs 4g, fat 2g"),
    ("ingredient_preset", "greek yogurt macros per 100g: 59 kcal, 10g protein"),
    ("ingredient_preset", "serving size 30g: protein 24g, carbs 3g, fat 1.5g"),
    ("ingredient_preset", "oat milk per serving 120 kcal"),
]

NEGATIVE = [
    "ate a burrito",
    "bench 3x8 today",
    "had 200g of rice for lunch",
    "ran 5 miles this morning",
    "leg day today, felt great",
    "went to the gym and did squats",
    "I make about 5000 a month",
    "chicken and rice for dinner",
    "bought a 500g bag of coffee and 2 cups",
    "deadlift 225 lbs for 5 reps",
    "remember to buy milk",
    "my routine is exhausting lately",
    "protein shake after lifting",
    "met Sarah for coffee at 3",
    "spent 40 on groceries",
    "",
    "   ",
]


@pytest.mark.parametrize("expected,text", POSITIVE)
def test_gate_positive(expected, text):
    assert looks_like_preset(text) == expected


@pytest.mark.parametrize("text", NEGATIVE)
def test_gate_negative(text):
    assert looks_like_preset(text) is None


# --- /drop ----------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    # Primary classifier: always one plain food log (deterministic, no model).
    monkeypatch.setattr(
        api_module,
        "parse_journal_dump",
        lambda *a, **k: [FoodEntry(type="food", meal_type="lunch", description="a bowl", estimated_kcal=500)],
    )
    return c


def _must_not_run(name):
    def fail(*args, **kwargs):
        raise AssertionError(f"{name} must not be called on this path")

    return fail


def _comp(name):
    return ComposedComponent(
        name=name, quantity_g=100, protein_g=10, carbs_g=10, fat_g=1, fiber_g=1, kcal=100, micros=[]
    )


def _stub_extractors(monkeypatch, calls, meal_name="Power Bowl", routine_name="Upper Day"):
    def meal(description, known, provider=None):
        calls.append(("meal", provider))
        return MealCompositionSuggestion(meal_name=meal_name, components=[_comp("rice"), _comp("chicken")])

    def routine(description, names, provider=None):
        calls.append(("routine", provider))
        return WorkoutRoutineSuggestion(name=routine_name, exercises=["Bench Press", "Overhead Press"])

    def nutrition(description, provider=None):
        calls.append(("nutrition", provider))
        return NutritionEstimate(basis_amount_g=100, protein_g=10, carbs_g=4, fat_g=2, fiber_g=0, kcal=120, micros=[])

    monkeypatch.setattr(api_module, "suggest_meal_composition", meal)
    monkeypatch.setattr(api_module, "suggest_workout_routine", routine)
    monkeypatch.setattr(api_module, "estimate_nutrition", nutrition)


def _types(resp):
    return [e["type"] for e in resp.json()["entries"]]


def test_meal_shaped_text_adds_meal_preset_after_primary(client, monkeypatch):
    calls = []
    _stub_extractors(monkeypatch, calls)
    resp = client.post("/drop", data={"text": "200g rice, 150g chicken breast, 100g broccoli", "provider": "cloud"})
    assert resp.status_code == 200
    assert _types(resp) == ["food", "meal_composition"]
    preset = resp.json()["entries"][1]
    assert preset["meal_name"] == "Power Bowl" and len(preset["components"]) == 2 and "totals" in preset
    assert calls == [("meal", "cloud")]  # provider passed through


def test_routine_shaped_text_adds_routine_preset(client, monkeypatch):
    calls = []
    _stub_extractors(monkeypatch, calls)
    resp = client.post("/drop", data={"text": "bench press 3x8, overhead press 3x10, tricep pushdown 3x12"})
    assert _types(resp) == ["food", "workout_routine"]
    assert resp.json()["entries"][1] == {
        "type": "workout_routine",
        "name": "Upper Day",
        "exercises": ["Bench Press", "Overhead Press"],
    }
    assert calls == [("routine", None)]


def test_equals_form_routine_uses_deterministic_parser_no_model(client, monkeypatch):
    monkeypatch.setattr(api_module, "suggest_workout_routine", _must_not_run("suggest_workout_routine"))
    resp = client.post("/drop", data={"text": "pull day = pull-ups, rows, lat pulldown, curls"})
    assert _types(resp) == ["food", "workout_routine"]
    assert resp.json()["entries"][1]["name"] == "pull day"


def test_label_shaped_text_adds_ingredient_preset(client, monkeypatch):
    calls = []
    _stub_extractors(monkeypatch, calls)
    resp = client.post("/drop", data={"text": "Greek yogurt macros per 100g: 59 kcal, 10g protein"})
    assert _types(resp) == ["food", "ingredient_preset"]
    preset = resp.json()["entries"][1]
    assert preset["suggested_name"] == "Greek yogurt macros per 100g"[:60]
    assert preset["basis_amount_g"] == 100 and preset["kcal"] == 120
    assert calls == [("nutrition", None)]


def test_plain_log_text_gets_no_extra_and_no_extractor_call(client, monkeypatch):
    for name in ("suggest_meal_composition", "suggest_workout_routine", "estimate_nutrition"):
        monkeypatch.setattr(api_module, name, _must_not_run(name))
    for text in ("ate a burrito", "bench 3x8 today"):
        resp = client.post("/drop", data={"text": text})
        assert resp.status_code == 200
        assert _types(resp) == ["food"]


def test_duplicate_meal_name_is_skipped(client, monkeypatch):
    calls = []
    _stub_extractors(monkeypatch, calls, meal_name="power bowl")
    assert client.post("/logs/meals", json={"name": "Power Bowl", "kcal": 600}).status_code == 200
    resp = client.post("/drop", data={"text": "200g rice, 150g chicken breast, 100g broccoli"})
    assert _types(resp) == ["food"]
    assert calls == [("meal", None)]  # extractor ran, result deduped


def test_duplicate_routine_name_is_skipped(client, monkeypatch):
    calls = []
    _stub_extractors(monkeypatch, calls, routine_name="Upper Day")
    assert client.post("/logs/routines", json={"name": "upper day", "exercises": ["Bench Press"]}).status_code == 200
    resp = client.post("/drop", data={"text": "bench press 3x8, overhead press 3x10"})
    assert _types(resp) == ["food"]


def test_duplicate_ingredient_name_is_skipped(client, monkeypatch):
    calls = []
    _stub_extractors(monkeypatch, calls)
    name = "Greek yogurt macros per 100g"
    assert client.post("/logs/ingredients", json={"name": name, "kcal": 59}).status_code == 200
    resp = client.post("/drop", data={"text": f"{name}: 59 kcal, 10g protein"})
    assert _types(resp) == ["food"]


def test_prefixed_text_gets_no_additional_suggestion(client, monkeypatch):
    calls = []
    _stub_extractors(monkeypatch, calls)
    resp = client.post("/drop", data={"text": "recipe: 200g rice, 150g chicken breast, 100g broccoli"})
    assert _types(resp) == ["meal_composition"]
    assert calls == [("meal", None)]  # exactly the prefix lane's own call, no second one

    calls.clear()
    resp = client.post("/drop", data={"text": "routine: bench press 3x8, overhead press 3x10"})
    assert _types(resp) == ["workout_routine"]
    assert calls == []


def test_extractor_failure_never_fails_the_drop(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model fell over")

    for name in ("suggest_meal_composition", "suggest_workout_routine", "estimate_nutrition"):
        monkeypatch.setattr(api_module, name, boom)
    for text in (
        "200g rice, 150g chicken breast, 100g broccoli",
        "bench press 3x8, overhead press 3x10",
        "Greek yogurt macros per 100g: 59 kcal, 10g protein",
    ):
        resp = client.post("/drop", data={"text": text})
        assert resp.status_code == 200
        assert _types(resp) == ["food"]


def test_extra_call_is_counted_by_provider_collector(client, monkeypatch):
    """The extra preset call goes through parse_structured, so it lands in the
    request's provider-used collector (Redo-with-cloud steps back correctly)."""
    from quintacle_core import llm_dispatch
    from quintacle_core.llm_dispatch import ParseResult

    monkeypatch.setattr(
        llm_dispatch,
        "_parse_local",
        lambda *a, **k: WorkoutRoutineSuggestion(name="Upper Day", exercises=["Bench Press"]),
    )
    resp = client.post("/drop", data={"text": "bench press 3x8, overhead press 3x10", "provider": "local"})
    assert _types(resp) == ["food", "workout_routine"]
    assert resp.json()["provider_used"] == "local"
    assert ParseResult  # imported for clarity of intent


# --- routine presets hold exercise NAMES, never set/rep schemes -------------

import pytest as _pytest

from quintacle_core.nodes.drop_router import strip_set_scheme


@_pytest.mark.parametrize(
    "raw, expected",
    [
        ("Bench Press 4x8", "Bench Press"),
        ("Overhead Press 3 x 10", "Overhead Press"),
        ("Tricep Dips 3×12", "Tricep Dips"),
        ("Squat 5x5-8", "Squat"),
        ("Deadlift - 3 sets of 5", "Deadlift"),
        ("Rows (4 sets x 10 reps)", "Rows"),
        ("Pull-ups", "Pull-ups"),
        ("21s Curls", "21s Curls"),
        ("4x8", "4x8"),
    ],
)
def test_strip_set_scheme(raw, expected):
    assert strip_set_scheme(raw) == expected
