"""Preset upserts (meals, ingredients, workout routines) are keyed by name —
only a spelling variant of the SAME name may update an existing preset; a
distinguishing word makes a new one (2026-11-11: "Chicken rice plate" used
to overwrite the saved "Chicken rice bowl" incl. its macros)."""

from quintacle_core.db import connect
from quintacle_core.nodes.logs.log_store import LogFileStore
from quintacle_core.nodes.logs.repository import LogsRepository


def make(tmp_path):
    conn = connect(tmp_path / "test.db")
    return LogsRepository(conn, LogFileStore(tmp_path / "kb")), conn


def test_meal_with_a_distinguishing_word_is_a_new_meal(tmp_path):
    repo, _ = make(tmp_path)
    bowl = repo.add_meal("Chicken rice bowl", protein_g=50, carbs_g=70, fat_g=15, kcal=650)
    plate = repo.add_meal("Chicken rice plate", protein_g=60, carbs_g=40, fat_g=10, kcal=500)
    assert plate != bowl
    meals = {m["name"]: m for m in repo.list_meals()}
    assert set(meals) == {"Chicken rice bowl", "Chicken rice plate"}
    assert meals["Chicken rice bowl"]["kcal"] == 650
    presets = {p["name"]: p for p in repo.preset_store.all()}
    assert presets["Chicken rice bowl"]["kcal"] == 650


def test_meal_spelling_variant_updates_the_same_meal(tmp_path):
    repo, _ = make(tmp_path)
    first = repo.add_meal("Chicken Rice Bowls", protein_g=50, carbs_g=70, fat_g=15, kcal=650)
    second = repo.add_meal("chicken rice bowl", protein_g=55, carbs_g=70, fat_g=15, kcal=670)
    assert second == first
    [meal] = repo.list_meals()
    assert meal["name"] == "Chicken Rice Bowls" and meal["kcal"] == 670


def test_ingredient_with_a_distinguishing_word_is_a_new_ingredient(tmp_path):
    repo, _ = make(tmp_path)
    greek = repo.add_ingredient("Greek yogurt", protein_g=10, carbs_g=4, fat_g=0, kcal=59)
    plain = repo.add_ingredient("Plain yogurt", protein_g=3.5, carbs_g=5, fat_g=3.3, kcal=61)
    assert plain != greek
    by_name = {i["name"]: i for i in repo.list_ingredients()}
    assert by_name["Greek yogurt"]["kcal"] == 59 and by_name["Plain yogurt"]["kcal"] == 61


def test_ingredient_spelling_variant_updates_the_same_ingredient(tmp_path):
    repo, _ = make(tmp_path)
    first = repo.add_ingredient("Chicken breast", protein_g=31, carbs_g=0, fat_g=3.6, kcal=165)
    second = repo.add_ingredient("chicken breasts", protein_g=31, carbs_g=0, fat_g=3.6, kcal=166)
    assert second == first
    [ing] = repo.list_ingredients()
    assert ing["name"] == "Chicken breast" and ing["kcal"] == 166


def test_routine_with_a_distinguishing_word_is_a_new_routine(tmp_path):
    repo, _ = make(tmp_path)
    assert repo.add_routine("Push day A", ["Bench press"]) == "Push day A"
    assert repo.add_routine("Push day B", ["Overhead press"]) == "Push day B"
    routines = {r["name"]: r["exercises"] for r in repo.list_routines()}
    assert routines == {"Push day A": ["Bench press"], "Push day B": ["Overhead press"]}


def test_routine_spelling_variant_updates_the_same_routine(tmp_path):
    repo, _ = make(tmp_path)
    repo.add_routine("Leg Day", ["Squat"])
    assert repo.add_routine("leg day", ["Squat", "Lunge"]) == "Leg Day"
    assert [(r["name"], r["exercises"]) for r in repo.list_routines()] == [("Leg Day", ["Squat", "Lunge"])]
