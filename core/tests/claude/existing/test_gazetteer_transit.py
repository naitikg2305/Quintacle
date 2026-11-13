"""2026-11-13 (owner, T1 Austria drop): a city only passed through (flight
layover, train change) isn't a destination; named any other way, it is."""
import pytest

from quintacle_core.gazetteer import find_places


def cities(text):
    return [m.city for m in find_places(text)]


@pytest.mark.parametrize("text,gone", [
    ("Prague (PRG) to Frankfurt (FRA) to Washington Dulles (IAD).", "Frankfurt"),
    ("Salzburg to Prague by train via Linz, budget roughly 6 hours", "Linz"),
    ("Salzburg -> Prague | 1 change, often Linz", "Linz"),
    ("a short layover in Frankfurt before Vienna", "Frankfurt"),
    ("connecting in Munich, then Vienna", "Munich"),
])
def test_transit_city_is_skipped(text, gone):
    assert gone not in cities(text)


def test_flight_chain_keeps_its_endpoints():
    assert cities("Washington Dulles (IAD) to Vienna (VIE) to Budapest (BUD).") == ["Budapest"]
    assert "Prague" in cities("Prague (PRG) to Frankfurt (FRA) to Washington Dulles (IAD).")


def test_a_city_named_normally_elsewhere_still_counts():
    text = "Prague (PRG) to Frankfurt (FRA) to IAD.\nDay 9: two nights in Frankfurt for the book fair."
    assert "Frankfurt" in cities(text)


def test_optional_excursion_still_counts():
    assert cities("or Hallstatt for the iconic village") == ["Hallstatt"]


# 2026-11-13 (owner, T2 NYC drop): a place inside a neighborhood name isn't
# that place.
@pytest.mark.parametrize("text,gone", [
    ("Lunch on Arthur Avenue, the Bronx's real Little Italy.", "Italy"),
    ("Dinner in Little India, Singapore", "India"),
])
def test_neighborhood_name_is_not_the_country(text, gone):
    assert gone not in [m.country for m in find_places(text) if m.city is None]


def test_country_named_normally_still_counts():
    assert "Italy" in [m.country for m in find_places("Next spring: two weeks in Italy.")]


# 2026-11-13 (owner, Brazil drop): connection lists and comparisons.
BRAZIL = (
    "Flights would be open-jaw like your Europe trip: Dulles into Rio de Janeiro, home from wherever you finish. "
    "You'd probably connect once in the US (Miami, Atlanta, Houston or New York), with domestic flights "
    "between cities in Brazil.\n"
    "3. Are you leaning toward cities and nightlife (like Budapest), nature and wildlife, or beaches?"
)


def test_brazil_plan_keeps_only_rio():
    found = cities(BRAZIL)
    assert "Rio de Janeiro" in found, found
    for gone in ("Miami", "Atlanta", "Houston", "New York", "Budapest"):
        assert gone not in found, found


@pytest.mark.parametrize("text,gone", [
    ("You'd connect once in the US (Miami, Atlanta or New York).", "Atlanta"),
    ("Possible stopovers: Lisbon or Madrid.", "Madrid"),
    ("cities and nightlife (like Budapest)", "Budapest"),
    ("a food scene similar to Lisbon", "Lisbon"),
    ("compared to Prague it is cheaper", "Prague"),
    ("old towns such as Krakow", "Krakow"),
])
def test_connection_list_and_comparison_are_skipped(text, gone):
    assert gone not in cities(text)


@pytest.mark.parametrize("text,kept", [
    ("Fly via Frankfurt to Vienna.", "Vienna"),
    ("connecting in Munich, then Vienna", "Vienna"),
    ("Buy Budapest-Vienna and Vienna-Salzburg via OBB; compare Salzburg-Prague with Czech Railways", "Prague"),
    ("Budapest is well connected to Vienna by train.", "Vienna"),
])
def test_onward_city_after_a_connection_still_counts(text, kept):
    assert kept in cities(text)


def test_comparison_country_is_skipped_but_named_country_counts():
    assert [m.country for m in find_places("a coast like Portugal")] == []
    assert "Portugal" in [m.country for m in find_places("Two weeks in Portugal.")]
