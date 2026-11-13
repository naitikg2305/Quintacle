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
