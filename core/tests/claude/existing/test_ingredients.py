from datetime import date

from quintacle_core.db import connect
from quintacle_core.nodes.logs.log_store import IngredientPresetStore, LogFileStore, rebuild_sqlite_index
from quintacle_core.nodes.logs.repository import LogsRepository


def make(tmp_path):
    conn = connect(tmp_path / "test.db")
    log_store = LogFileStore(tmp_path / "kb")
    return LogsRepository(conn, log_store), log_store, conn


def test_add_ingredient_writes_markdown_preset(tmp_path):
    repo, log_store, _ = make(tmp_path)
    repo.add_ingredient("Lamb", protein_g=25, carbs_g=0, fat_g=17, kcal=258, basis_amount_g=100)

    presets = IngredientPresetStore(log_store.kb_root).all()
    assert len(presets) == 1
    assert presets[0]["name"] == "Lamb"
    assert presets[0]["basis_amount_g"] == 100


def test_redefining_an_ingredient_upserts_not_duplicates(tmp_path):
    repo, log_store, conn = make(tmp_path)
    first_id = repo.add_ingredient("Lamb", protein_g=25, carbs_g=0, fat_g=17, kcal=258)
    second_id = repo.add_ingredient("Lamb", protein_g=26, carbs_g=0, fat_g=18, kcal=265)

    assert first_id == second_id
    rows = conn.execute("SELECT * FROM ingredients WHERE name = 'Lamb'").fetchall()
    assert len(rows) == 1
    assert rows[0]["kcal"] == 265


def test_fuzzy_name_match_updates_existing_ingredient_instead_of_forking(tmp_path):
    repo, log_store, conn = make(tmp_path)
    first_id = repo.add_ingredient("Ground Lamb", protein_g=25, carbs_g=0, fat_g=17, kcal=258)
    # A second label photo phrases the name slightly differently — should
    # correct to the existing name and update it, not create "ground-lamb-2".
    second_id = repo.add_ingredient("ground lamb", protein_g=27, carbs_g=0, fat_g=18, kcal=270)

    assert first_id == second_id
    assert conn.execute("SELECT COUNT(*) AS n FROM ingredients").fetchone()["n"] == 1


def test_ingredient_id_survives_rebuild_so_meal_ingredients_stay_valid(tmp_path):
    repo, log_store, conn = make(tmp_path)
    ingredient_id = repo.add_ingredient("Greek Yogurt", protein_g=17, carbs_g=6, fat_g=0.7, kcal=100, basis_amount_g=170)
    meal_id = repo.add_meal_from_ingredients("Yogurt Bowl", [{"ingredient_id": ingredient_id, "quantity_g": 170}])

    rebuild_sqlite_index(log_store, conn, repo.preset_store, repo.ingredient_store)

    ing_row = conn.execute("SELECT id FROM ingredients WHERE name = 'Greek Yogurt'").fetchone()
    assert ing_row["id"] == ingredient_id
    components = repo.meal_components(meal_id)
    assert len(components) == 1
    assert components[0]["ingredient_id"] == ingredient_id
    assert components[0]["quantity_g"] == 170


def test_compute_meal_totals_scales_by_quantity_over_basis(tmp_path):
    repo, log_store, conn = make(tmp_path)
    # Per 100g: 10 protein, 20 carbs, 5 fat, 2 fiber, 150 kcal
    ingredient_id = repo.add_ingredient("Rice", protein_g=10, carbs_g=20, fat_g=5, kcal=150, fiber_g=2, basis_amount_g=100)

    totals = repo.compute_meal_totals([{"ingredient_id": ingredient_id, "quantity_g": 250}])

    assert totals["protein_g"] == 25
    assert totals["carbs_g"] == 50
    assert totals["fat_g"] == 12.5
    assert totals["fiber_g"] == 5
    assert totals["kcal"] == 375


def test_meal_from_ingredients_sums_multiple_components_deterministically(tmp_path):
    repo, log_store, conn = make(tmp_path)
    yogurt_id = repo.add_ingredient("Greek Yogurt", protein_g=17, carbs_g=6, fat_g=0.7, kcal=100, basis_amount_g=170)
    honey_id = repo.add_ingredient("Honey", protein_g=0, carbs_g=17, fat_g=0, kcal=64, basis_amount_g=21)

    meal_id = repo.add_meal_from_ingredients(
        "Yogurt + Honey Bowl",
        [
            {"ingredient_id": yogurt_id, "quantity_g": 170},  # exactly 1x basis
            {"ingredient_id": honey_id, "quantity_g": 21},  # exactly 1x basis
        ],
    )

    meal = repo.get_meal(meal_id)
    assert meal["protein_g"] == 17
    assert meal["carbs_g"] == 23
    assert meal["kcal"] == 164

    # Fix the honey ingredient's macros later — the composed meal should
    # reflect the correction next time it's recomputed from ingredients.
    repo.add_ingredient("Honey", protein_g=0, carbs_g=17.3, fat_g=0, kcal=64, basis_amount_g=21)
    recomputed = repo.compute_meal_totals([{"ingredient_id": yogurt_id, "quantity_g": 170}, {"ingredient_id": honey_id, "quantity_g": 21}])
    assert recomputed["carbs_g"] == 23.3


def test_composed_meal_components_recorded_in_markdown_by_name(tmp_path):
    repo, log_store, conn = make(tmp_path)
    yogurt_id = repo.add_ingredient("Greek Yogurt", protein_g=17, carbs_g=6, fat_g=0.7, kcal=100, basis_amount_g=170)
    repo.add_meal_from_ingredients("Yogurt Bowl", [{"ingredient_id": yogurt_id, "quantity_g": 170}])

    presets = repo.preset_store.all()
    bowl = next(p for p in presets if p["name"] == "Yogurt Bowl")
    assert bowl["components"] == [{"ingredient_name": "Greek Yogurt", "quantity_g": 170}]
