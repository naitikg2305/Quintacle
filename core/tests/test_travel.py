from quintacle_core.nodes.travel.llm import _EXPERIENCE_SIGNAL_RE
from quintacle_core.nodes.travel.store import ExperienceStore, _kind_folder_name


def test_kind_folder_pluralization():
    assert _kind_folder_name("restaurant") == "Restaurants"
    assert _kind_folder_name("bar") == "Bars"
    assert _kind_folder_name("") == "Experiences"
    assert _kind_folder_name("activities") == "Activities"  # already plural, don't double-pluralize


def test_experience_write_then_all(tmp_path):
    store = ExperienceStore(tmp_path)
    folder, slug = store.write(
        "Nobu", "Tokyo", "restaurant", rating="loved it", would_return=True, visited_date="2026-04-11"
    )

    experiences = store.all()
    assert len(experiences) == 1
    assert experiences[0]["name"] == "Nobu"
    assert experiences[0]["city"] == "Tokyo"
    assert experiences[0]["kind"] == "restaurant"
    assert experiences[0]["would_return"] is True
    assert experiences[0]["folder"] == folder
    assert slug == "nobu"


def test_experiences_nested_by_city_and_kind(tmp_path):
    store = ExperienceStore(tmp_path)
    folder, _ = store.write("Nobu", "Tokyo", "restaurant")

    assert folder == "planning/travel/tokyo/restaurants"


def test_different_kinds_get_different_subfolders(tmp_path):
    store = ExperienceStore(tmp_path)
    restaurant_folder, _ = store.write("Nobu", "Tokyo", "restaurant")
    bar_folder, _ = store.write("Golden Gai Bar", "Tokyo", "bar")

    assert restaurant_folder != bar_folder
    assert "restaurants" in restaurant_folder
    assert "bars" in bar_folder


def test_by_city_filters_correctly(tmp_path):
    store = ExperienceStore(tmp_path)
    store.write("Nobu", "Tokyo", "restaurant")
    store.write("Joe's Pizza", "New York", "restaurant")

    tokyo_only = store.by_city("Tokyo")
    assert len(tokyo_only) == 1
    assert tokyo_only[0]["name"] == "Nobu"


def test_links_persisted(tmp_path):
    store = ExperienceStore(tmp_path)
    store.write("Nobu", "Tokyo", "restaurant", links=["Miso Black Cod Photo"])

    experiences = store.all()
    assert experiences[0]["links"] == ["Miso Black Cod Photo"]


def test_experience_signal_regex_matches_restaurant_language():
    assert _EXPERIENCE_SIGNAL_RE.search("had dinner at this amazing restaurant")
    assert _EXPERIENCE_SIGNAL_RE.search("went to a great bar last night")
    assert _EXPERIENCE_SIGNAL_RE.search("had dinner at Nobu tonight")
    assert not _EXPERIENCE_SIGNAL_RE.search("logged today's weight, 181.2 lbs")
    assert not _EXPERIENCE_SIGNAL_RE.search("did chest and triceps at the gym")
