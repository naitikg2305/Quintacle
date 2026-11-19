"""T1 (TESTING-LOG.md): the owner drops Austria_drop.pdf (a 10-day
Budapest → Vienna → Salzburg → Prague plan) and presses Sort with AI.

Same request the app makes: POST /drop with the file and no text. It runs on
a sandbox copy of the owner's real store (~/.quintacle is only read).

Expectations (owner, 2026-11-13):
- a travel-plan KB entry under Fun/Travel/Planned, never the Document Vault;
- destinations are the trip's cities: Budapest, Vienna, Salzburg, Prague;
- the optional excursion (Hallstatt) may be listed;
- a flight layover (Frankfurt) must not be. A train change (Linz) is treated
  like a layover (owner confirmed 2026-11-17: "preferrably no it shouldnt show up").
- the trip's year is in its folder (owner: "yeah i want the year");
- linked notes only name notes that exist (no "About Travel" when there is none);
- after Save (the same request the app's Save makes), the graph has no gaps:
  - the trip sits in its folder tree: trip → Europe 2027 → Planned → Travel → Fun;
  - each trip city chains to its country, then to Europe;
  - no node for Frankfurt or Linz is touched;
  - nothing goes to the Document Vault.

Run one provider per pytest call (each sets process-wide model routing):
    cd core && .venv/bin/python -m pytest tests/user/travel/test_t01_austria_drop.py -q                      # local
    cd core && QUINTACLE_USER_PROVIDER=cloud .venv/bin/python -m pytest tests/user/travel/test_t01_austria_drop.py -q  # Claude via Max
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.claude.harness import REAL_STORE, drop, first, folder_of, make_client, missing_max, missing_requirements, sandbox_before, types

PDF = Path(__file__).parents[1] / "files" / "travel" / "Austria_drop.pdf"
PROVIDER = os.environ.get("QUINTACLE_USER_PROVIDER", "local")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    reason = missing_max() if PROVIDER == "cloud" else missing_requirements()
    if reason:
        pytest.skip(reason)
    # His data as it was when he dropped the PDF (2026-11-13 ~03:30, right after the 03:19 wipe:
    # Fun/Travel/Planned was empty, no ingredients). Everything saved since is left out.
    return sandbox_before(tmp_path_factory.mktemp("t01"), chats_from="2026-11-13-0300",
                          leave_out=("fun/travel/planned/europe-2027", "fun/travel/planned/europe-2026",
                                     "fun/travel/planned/new-york-2028"),
                          leave_out_ingredients=("Costco Lean Lamb", "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)"), cloud=PROVIDER == "cloud")


@pytest.fixture(scope="module")
def result(client):
    return drop(client, path=PDF, provider=PROVIDER)


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


# ------------------------------------------------------------------ after Save


@pytest.fixture(scope="module")
def saved(client, result):
    """Save the proposal exactly as the app's review card does
    (frontend/lib/api.ts pushKBEntryWithAsset → POST /kb/entries/with-asset)."""
    import json

    entry = first(result, "kb_entry")
    c = client
    form = {"folder": entry["folder"], "title": entry["title"], "content": entry["content"],
            "links": ",".join(entry.get("links") or []), "on_conflict": entry.get("on_conflict") or "new"}
    if entry.get("fields"):
        form["fields"] = json.dumps(entry["fields"])
    r = c.post("/kb/entries/with-asset", data=form,
               files=[("files", (PDF.name, PDF.read_bytes(), "application/pdf"))])
    assert r.status_code == 200, r.text[:400]
    out = r.json()
    return f"note:{out['folder']}/{out['slug']}", out["folder"]


def _edges():
    from quintacle_core.graph import get_graph_store

    return [(e["source_id"], e["target_id"]) for e in get_graph_store().all()]


def _reachable(start: str) -> set[str]:
    out, todo, edges = set(), [start], _edges()
    while todo:
        n = todo.pop()
        for s, t in edges:
            if s == n and t not in out:
                out.add(t)
                todo.append(t)
    return out


def test_saved_trip_sits_in_its_folder_tree(saved):
    note_id, folder = saved
    assert folder.startswith("fun/travel/planned/") and "2027" in folder, folder
    up = _reachable(note_id)
    for f in (f"folder:{folder}", "folder:fun/travel/planned", "folder:fun/travel", "folder:fun"):
        assert f in up, (f, sorted(up))


def test_saved_trip_cities_chain_to_country_and_europe(saved):
    note_id, _ = saved
    up = _reachable(note_id)
    for city, country in (("budapest", "hungary"), ("vienna", "austria"), ("salzburg", "austria"), ("prague", "czechia")):
        assert any(n.startswith("place:") and n.endswith(f"/{city}") for n in up), (city, sorted(up))
        assert any(n.startswith("place:") and n.endswith(f"/{country}") for n in up), (country, sorted(up))
    assert "place:europe" in up, sorted(up)


def test_saved_trip_touches_no_layover_city_or_vault(saved):
    note_id, _ = saved
    touched = {t for s, t in _edges() if s == note_id} | {s for s, t in _edges() if t == note_id}
    assert not any(n.endswith("/frankfurt") or n.endswith("/linz") for n in _reachable(note_id) | touched)
    assert not any("document-vault" in n or n.startswith("vault") for n in touched)
