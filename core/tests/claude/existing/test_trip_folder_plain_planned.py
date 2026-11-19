"""2026-11-17 (owner, T2): a trip plan left in plain Fun/Travel/Planned gets its trip folder from code."""
import pytest

from quintacle_core.drop_fixups import planned_folder_with_year, trip_folder_for_plain_planned


def _both(title, content, folder="Fun/Travel/Planned"):
    f = trip_folder_for_plain_planned(folder, title, content)
    return planned_folder_with_year(f, title, content)


@pytest.mark.parametrize("title,content,want", [
    ("5-Day NYC Itinerary 2028", "Day 1 in Manhattan, New York City, May 2028. Day 2 Brooklyn.", "Fun/Travel/Planned/New York 2028"),
    ("2027 Central Europe 10-Day Trip", "Budapest, Vienna, Salzburg and Prague, May 12-21, 2027.", "Fun/Travel/Planned/Europe 2027"),
    ("Brazil 2027", "Rio de Janeiro and Sao Paulo in 2027", "Fun/Travel/Planned/Brazil 2027"),
])
def test_plain_planned_gets_the_trip_folder_and_year(title, content, want):
    assert _both(title, content) == want


def test_no_places_stays_put():
    assert _both("Packing list", "socks, charger") == "Fun/Travel/Planned"


def test_a_trip_folder_the_model_chose_is_kept():
    assert trip_folder_for_plain_planned("Fun/Travel/Planned/Europe 2027", "x", "Vienna") == "Fun/Travel/Planned/Europe 2027"


def test_other_folders_untouched():
    assert trip_folder_for_plain_planned("Knowledge", "x", "Vienna") == "Knowledge"


# ------------------------------------------------------------------ 2026-11-17 food fixes (owner)

from quintacle_core.drop_fixups import nutrition_note_folder  # noqa: E402
from quintacle_core.nodes.drop_router import looks_like_preset  # noqa: E402

_TOPS = ["fun", "personal-development", "personal-development/physical/nutrition", "knowledge"]


@pytest.mark.parametrize("folder", ["Nutrition/Meal_Plans", "Health/Nutrition", "Nutrition/Meal_Planning"])
def test_new_top_nutrition_folder_goes_home(folder):
    assert nutrition_note_folder(folder, _TOPS) == "Personal Development/Physical/Nutrition/Meal Plans"


@pytest.mark.parametrize("folder", ["Personal Development/Physical/Nutrition", "Knowledge/Food Science", "Fun/Travel/Planned"])
def test_existing_top_folders_are_kept(folder):
    assert nutrition_note_folder(folder, _TOPS) == folder


@pytest.mark.parametrize("text", [
    "Lamb (230g), Salmon (70g), Eggs (100g)",
    "**Grilled Lamb Chops (230g)**: marinated. **Roasted Salmon (70g)**. **Brown Rice (50g)**",
    "| Lamb, 230 g | 431 |\n| Salmon, 70 g | 99 |\n| Rice, 50 g dry | 179 |",
])
def test_amounts_after_the_food_still_suggest_a_meal(text):
    assert looks_like_preset(text) == "meal_composition"


def test_nutrient_lines_alone_are_not_a_meal():
    assert looks_like_preset("Protein (74.9g), Fat: 40.9g, Carbs (40.3g)") is None
