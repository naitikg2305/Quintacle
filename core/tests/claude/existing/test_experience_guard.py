"""2026-11-11: the local model invented a city and a visit date for
"dinner at Compass". guard_experience keeps only what the text states."""
from __future__ import annotations

from datetime import date

from quintacle_core.nodes.travel.llm import ExperienceEstimate, guard_experience

REF = date(2026, 11, 11)


def _est(**kw):
    return ExperienceEstimate(is_experience=True, suggested_name="Compass", kind="restaurant", **kw)


def test_unstated_city_and_date_dropped():
    e = guard_experience(_est(city="San Francisco", visited_date="2023-10-15"), "dinner with Arjun at Compass, great food", REF)
    assert e.city == "" and e.visited_date is None


def test_stated_city_and_date_kept():
    e = guard_experience(_est(city="Arlington", visited_date="2026-10-03"), "dinner at Compass in Arlington on Oct 3 2026", REF)
    assert e.city == "Arlington" and e.visited_date == "2026-10-03"


def test_relative_date_resolved_in_code():
    e = guard_experience(_est(visited_date="2025-01-01"), "dinner at Compass yesterday, loved it", REF)
    assert e.visited_date == "2026-11-10"
