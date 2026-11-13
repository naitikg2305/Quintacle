"""T1 (TESTING-LOG.md): the owner drops Austria_drop.pdf (a 10-day
Budapest → Vienna → Salzburg → Prague plan) and presses Sort with AI.

Same request the app makes: POST /drop with the file and no text. It runs on
a sandbox copy of the owner's real store (~/.quintacle is only read).

Expectations (owner, 2026-11-13):
- a travel-plan KB entry under Fun/Travel/Planned, never the Document Vault;
- destinations are the trip's cities: Budapest, Vienna, Salzburg, Prague;
- the optional excursion (Hallstatt) may be listed;
- a flight layover (Frankfurt) must not be. A train change (Linz) is treated
  like a layover *(draft, owner to confirm)*.
- the trip's year is in its folder (owner: "yeah i want the year");
- linked notes only name notes that exist (no "About Travel" when there is none).

Run one provider per pytest call (each sets process-wide model routing):
    cd core && .venv/bin/python -m pytest tests/user/test_t01_austria_drop.py -q                      # local
    cd core && QUINTACLE_USER_PROVIDER=cloud .venv/bin/python -m pytest tests/user/test_t01_austria_drop.py -q  # Claude via Max
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.claude.harness import REAL_STORE, drop, first, folder_of, make_client, missing_max, missing_requirements, types

PDF = Path(__file__).parent / "files" / "travel" / "Austria_drop.pdf"
PROVIDER = os.environ.get("QUINTACLE_USER_PROVIDER", "local")


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    reason = missing_max() if PROVIDER == "cloud" else missing_requirements()
    if reason:
        pytest.skip(reason)
    c = make_client(tmp_path_factory.mktemp("t01"), seed_store=REAL_STORE, cloud=PROVIDER == "cloud")
    return drop(c, path=PDF, provider=PROVIDER)


def test_sorted_as_a_planned_trip_not_a_document(result):
    assert "document_entry" not in types(result), types(result)
    entry = first(result, "kb_entry")
    assert folder_of(entry).startswith("fun/travel/planned"), entry.get("folder")


def test_trip_year_is_in_the_folder(result):
    assert "2027" in first(result, "kb_entry").get("folder", ""), first(result, "kb_entry").get("folder")


def test_links_name_existing_notes_only(result):
    assert "About Travel" not in (first(result, "kb_entry").get("links") or [])


def _destinations(result) -> str:
    entry = first(result, "kb_entry")
    return ((entry.get("fields") or {}).get("destinations") or "").lower()


def test_destinations_are_the_four_trip_cities(result):
    dest = _destinations(result)
    for city in ("budapest", "vienna", "salzburg", "prague"):
        assert city in dest, dest


def test_layover_and_train_change_are_not_destinations(result):
    dest = _destinations(result)
    assert "frankfurt" not in dest, dest  # flight layover PRG-FRA-IAD
    assert "linz" not in dest, dest  # train change Salzburg → Prague
