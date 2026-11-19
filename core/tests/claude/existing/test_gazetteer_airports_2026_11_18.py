"""2026-11-18 (owner, code review): an airport name is how a ticket names the
destination, so "<City> (International) Airport" is not a layover by itself, and
"transit pass" is not a transit stop. Layovers still drop out via the existing
rules (coded mid-route arrow, via, connecting, layover, flying through)."""
import pytest

from quintacle_core.gazetteer import find_places


def _cities(text):
    return [m.city for m in find_places(text) if m.city]


@pytest.mark.parametrize("text", [
    "Washington Dulles International Airport (IAD) to Vienna International Airport (VIE), 15 May 2027",
    "Arrive Vienna Airport, then hotel",
    "Day 3: Vienna - transit pass and museums",
])
def test_airport_or_transit_pass_city_is_a_destination(text):
    assert "Vienna" in _cities(text)


@pytest.mark.parametrize("text", [
    "Washington Dulles (IAD) → Frankfurt (FRA) → Vienna (VIE)",
    "Frankfurt (FRA) layover 2h. Vienna 5 days.",
    "Leg 1: IAD to Frankfurt (FRA) - 1h 35m connection. Leg 2 to Vienna (VIE)",
    "Vienna (VIE), connecting through Frankfurt (FRA)",
    "Vienna 5 days, flying home through Frankfurt Airport.",
])
def test_layover_city_still_skipped(text):
    assert _cities(text) == ["Vienna"]


def test_airport_mention_on_its_own_counts_per_mention():
    # owner rule: each mention judged on its own
    assert _cities("Washington Dulles (IAD) → Frankfurt (FRA) → Vienna (VIE). Frankfurt airport has lounges.") == ["Vienna", "Frankfurt"]


def test_city_chain_without_codes_keeps_every_stop():
    assert _cities("Budapest → Vienna → Salzburg → Prague") == ["Budapest", "Vienna", "Salzburg", "Prague"]


def test_layover_city_named_elsewhere_still_counts():
    text = "Prague (PRG) to Frankfurt (FRA) to IAD.\nDay 9: two nights in Frankfurt for the book fair."
    assert "Frankfurt" in _cities(text)
