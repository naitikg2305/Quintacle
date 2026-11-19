"""2026-11-17 (owner, T7): chat's nutrition lane uses his saved ingredients before USDA."""
from quintacle_core.nutrition_db.chat_lane import parse_items, saved_ingredient_for

LIB = [{"id": 2, "name": "Costco Lean Lamb"},
       {"id": 3, "name": "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)"}]


def _name(food):
    return (saved_ingredient_for(food, LIB) or {}).get("name")


def test_his_breakfast_message_finds_his_lamb_only():
    text = ("okay so planning the balanced day m,eal. breakfast. I have 230 grams of costco lamb, "
            "70 grams of atlantic salmon, 2 eggs and 50 grams of uncooked rice.")
    got = {i["food"]: _name(i["food"]) for i in parse_items(text)}
    assert got["costco lamb"] == "Costco Lean Lamb"
    assert [v for k, v in got.items() if k != "costco lamb"] == [None, None, None]


def test_short_and_plural_names_match():
    assert _name("lamb") == "Costco Lean Lamb"
    assert _name("greek yogurt") == LIB[1]["name"]


def test_other_foods_go_to_usda():
    assert _name("salmon") is None and _name("ground lamb") is None and _name("") is None


def test_closest_saved_name_wins():
    lib = LIB + [{"id": 4, "name": "Lamb"}]
    assert (saved_ingredient_for("lamb", lib) or {}).get("id") == 4
