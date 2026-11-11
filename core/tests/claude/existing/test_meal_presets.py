from datetime import date

from quintacle_core.db import connect
from quintacle_core.nodes.logs.log_store import LogFileStore, MealPresetStore, rebuild_sqlite_index
from quintacle_core.nodes.logs.repository import LogsRepository


def make(tmp_path):
    conn = connect(tmp_path / "test.db")
    log_store = LogFileStore(tmp_path / "kb")
    return LogsRepository(conn, log_store), log_store, conn


def test_add_meal_writes_markdown_preset(tmp_path):
    repo, log_store, _ = make(tmp_path)
    repo.add_meal("Lamb Meal", protein_g=75.5, carbs_g=1.2, fat_g=42.3, kcal=687, fiber_g=0)

    preset_store = MealPresetStore(log_store.kb_root)
    presets = preset_store.all()
    assert len(presets) == 1
    assert presets[0]["name"] == "Lamb Meal"
    assert presets[0]["kcal"] == 687


def test_meal_id_survives_rebuild_so_food_log_references_stay_valid(tmp_path):
    repo, log_store, conn = make(tmp_path)
    meal_id = repo.add_meal("Smoothie", protein_g=32, carbs_g=58, fat_g=16, kcal=485, fiber_g=12)
    repo.log_food(date(2026, 9, 8), "breakfast", meal_id=meal_id, servings=1)

    # Rebuilding must NOT reassign meal_id — food_log (SQLite and the
    # markdown snapshot) already points at the original id.
    rebuild_sqlite_index(log_store, conn, repo.preset_store)

    row = conn.execute("SELECT id FROM meals WHERE name = 'Smoothie'").fetchone()
    assert row["id"] == meal_id

    food_row = conn.execute("SELECT meal_id FROM food_log WHERE date = '2026-09-08'").fetchone()
    assert food_row["meal_id"] == meal_id


def test_redefining_an_existing_preset_upserts_not_duplicates(tmp_path):
    repo, log_store, conn = make(tmp_path)
    first_id = repo.add_meal("Lamb Meal", protein_g=70, carbs_g=1, fat_g=40, kcal=650)
    second_id = repo.add_meal("Lamb Meal", protein_g=75.5, carbs_g=1.2, fat_g=42.3, kcal=687)

    assert first_id == second_id
    rows = conn.execute("SELECT * FROM meals WHERE name = 'Lamb Meal'").fetchall()
    assert len(rows) == 1
    assert rows[0]["kcal"] == 687


def test_meal_micros_round_trip_through_rebuild(tmp_path):
    repo, log_store, conn = make(tmp_path)
    meal_id = repo.add_meal(
        "Lamb Meal", protein_g=75.5, carbs_g=1.2, fat_g=42.3, kcal=687,
        micros=[{"nutrient": "Selenium", "amount": 76.0, "unit": "mcg"}],
    )

    rebuild_sqlite_index(log_store, conn, repo.preset_store)

    micros = repo.micros_for_meal(meal_id)
    assert len(micros) == 1
    assert micros[0]["nutrient"] == "Selenium"
    assert micros[0]["amount"] == 76.0


def test_deleted_preset_file_removed_from_index_on_rebuild(tmp_path):
    repo, log_store, conn = make(tmp_path)
    repo.add_meal("Temp Meal", protein_g=10, carbs_g=10, fat_g=10, kcal=170)
    repo.preset_store.delete("Temp Meal")

    rebuild_sqlite_index(log_store, conn, repo.preset_store)

    assert conn.execute("SELECT * FROM meals WHERE name = 'Temp Meal'").fetchone() is None
