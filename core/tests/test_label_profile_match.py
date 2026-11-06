"""2026-11-06: backtrack a label's food from its numbers (+ ingredient words)."""
import sqlite3

import pytest

from quintacle_core.nutrition_db import store


@pytest.fixture
def tiny_usda(tmp_path, monkeypatch):
    db = tmp_path / "usda.db"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE foods (fdc_id INTEGER PRIMARY KEY, description TEXT, category TEXT, source TEXT);
    CREATE TABLE nutrients (id INTEGER PRIMARY KEY, name TEXT, unit TEXT);
    CREATE TABLE food_nutrient (fdc_id INTEGER, nutrient_id INTEGER, amount REAL, approx INTEGER DEFAULT 0);
    INSERT INTO nutrients VALUES (1,'Energy','kcal'),(2,'Protein','g'),(3,'Carbohydrates','g'),(4,'Fat','g'),(22,'Calcium','mg');
    INSERT INTO foods VALUES (10,'Yogurt, Greek, plain, nonfat','Dairy and Egg Products','sr_legacy'),
                             (11,'Cheese, cottage, lowfat, 1% milkfat','Dairy and Egg Products','sr_legacy'),
                             (12,'Egg, white, raw','Dairy and Egg Products','sr_legacy'),
                             (13,'Bread, white','Baked Products','sr_legacy');
    """)
    for fid, vals in {10: (59, 10.2, 3.6, 0.4, 110), 11: (72, 12.4, 2.7, 1.0, 61), 12: (52, 10.9, 0.7, 0.2, 7), 13: (266, 7.6, 50, 3.3, 151)}.items():
        for nid, v in zip((1, 2, 3, 4, 22), vals):
            c.execute("INSERT INTO food_nutrient VALUES (?,?,?,0)", (fid, nid, v))
    c.commit(); c.close()
    monkeypatch.setenv("QUINTACLE_USDA_DB", str(db))
    store._conns.clear()
    yield
    store._conns.clear()


def test_numbers_narrow_to_high_protein_dairy(tiny_usda):
    got = store.nearest_by_profile({"kcal": 60, "protein_g": 10, "carbs_g": 3.5, "fat_g": 0.3})
    assert got[-1]["description"].startswith("Bread")  # far away
    assert {g["fdc_id"] for g in got[:3]} == {10, 11, 12}


def test_ingredient_words_break_the_tie(tiny_usda):
    got = store.nearest_by_profile({"kcal": 60, "protein_g": 10, "carbs_g": 3.5, "fat_g": 0.3},
                                   ["cultured", "pasteurized", "nonfat", "milk"])
    assert got[0]["fdc_id"] == 10


def test_too_little_data_returns_nothing(tiny_usda):
    assert store.nearest_by_profile({"kcal": 60}) == []


def test_ambiguous_label_leaves_choice_to_owner(tiny_usda):
    from quintacle_core.api import _label_profile_match
    out = _label_profile_match({"basis_amount_g": 100, "kcal": 62, "protein_g": 11.3, "carbs_g": 2.0, "fat_g": 0.6})
    assert out["fdc_id"] is None and len(out["usda_candidates"]) >= 2
    clear = _label_profile_match({"basis_amount_g": 150, "kcal": 90, "protein_g": 15, "carbs_g": 5.4, "fat_g": 0.6},
                                 "INGREDIENTS: CULTURED PASTEURIZED NONFAT MILK")
    assert clear["fdc_id"] == 10 and clear["usda_match_by"] == "nutrition profile"
