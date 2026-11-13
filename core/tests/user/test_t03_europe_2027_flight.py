"""T3 (TESTING-LOG.md): the owner drops sample_dc_europe_flight_2027.pdf (a
round trip Washington Dulles -> Vienna, 15-25 May 2027, via Frankfurt both
ways) and presses Sort with AI. In his session (2026-11-13) it filed itself
into the trip folder that already existed from T1: Fun/Travel/Planned/Europe 2027.

Same request the app makes: POST /drop with the file and no text. It runs on
a sandbox copy of the owner's real store (~/.quintacle is only read), with the
note his own session saved left out, so the sort is not handed the answer.

Expectations (owner, 2026-11-13):
- a travel KB entry, never the Document Vault;
- it goes into the EXISTING trip folder fun/travel/planned/europe-2027,
  not a new folder next to it;
- it links to the trip's itinerary note from T1 ("2027 Central Europe 10-Day
  Trip Itinerary");
- destination is Vienna. Frankfurt is a layover and Washington is home: never
  destinations;
- *(draft, owner to confirm)* it is not offered as a version of the itinerary
  (a ticket is not a revision of the plan), so no Append/Replace choice;
- after Save (the same request the app's Save makes):
  - the ticket sits in the folder tree: ticket -> Europe 2027 -> Planned -> Travel -> Fun;
  - it has a graph edge to the itinerary note;
  - Vienna chains to Austria, then to Europe;
  - no node for Frankfurt or Washington is touched, nothing goes to the Document Vault.

Run one provider per pytest call (each sets process-wide model routing):
    cd core && .venv/bin/python -m pytest tests/user/test_t03_europe_2027_flight.py -q                      # local
    cd core && QUINTACLE_USER_PROVIDER=cloud .venv/bin/python -m pytest tests/user/test_t03_europe_2027_flight.py -q  # Claude via Max
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from tests.claude.harness import REAL_STORE, drop, first, folder_of, make_client, missing_max, missing_requirements, types

PDF = Path(__file__).parent / "files" / "travel" / "sample_dc_europe_flight_2027.pdf"
PROVIDER = os.environ.get("QUINTACLE_USER_PROVIDER", "local")
TRIP_FOLDER = "fun/travel/planned/europe-2027"
ITINERARY_TITLE = "2027 Central Europe 10-Day Trip Itinerary"
ITINERARY_NOTE = f"note:{TRIP_FOLDER}/2027-central-europe-10-day-trip-itinerary"
# What the owner's own session saved: left out of the sandbox (files, graph, index).
LEFT_OUT_SLUG = "2027-europe-travel-itinerary-sample"
LEFT_OUT_ASSET = "sample-dc-europe-flight-2027"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    reason = missing_max() if PROVIDER == "cloud" else missing_requirements()
    if reason:
        pytest.skip(reason)
    if not (REAL_STORE / "kb" / TRIP_FOLDER / f"{ITINERARY_NOTE.rsplit('/', 1)[1]}.md").exists():
        pytest.skip("the T1 itinerary note is not in the real store")
    tmp = tmp_path_factory.mktemp("t03")
    seed = tmp / "seed"
    shutil.copytree(REAL_STORE, seed, ignore=shutil.ignore_patterns(
        f"{LEFT_OUT_SLUG}*", f"{LEFT_OUT_ASSET}*", "models", "*.onnx", "*.zip", "*.lock", "*-shm", "*-wal"))
    c = make_client(tmp, seed_store=seed, cloud=PROVIDER == "cloud")
    # The copied database still knows the left-out note: forget it (sandbox only).
    from quintacle_core.graph import get_graph_store
    from quintacle_core.retrieval import get_retrieval_index

    gone = f"note:{TRIP_FOLDER}/{LEFT_OUT_SLUG}"
    get_graph_store().remove_edges_for(gone)
    get_retrieval_index().remove_node(gone)
    return c


@pytest.fixture(scope="module")
def result(client):
    return drop(client, path=PDF, provider=PROVIDER)


def test_sorted_as_travel_not_a_document(result):
    assert "document_entry" not in types(result), types(result)
    first(result, "kb_entry")


def test_goes_into_the_existing_2027_trip_folder(result):
    entry = first(result, "kb_entry")
    assert folder_of(entry) == TRIP_FOLDER, entry.get("folder")


def test_links_to_the_trip_itinerary(result):
    links = first(result, "kb_entry").get("links") or []
    assert ITINERARY_TITLE in links, links


def _destinations(result) -> str:
    return ((first(result, "kb_entry").get("fields") or {}).get("destinations") or "").lower()


def test_destination_is_vienna(result):
    assert "vienna" in _destinations(result), _destinations(result)


def test_layover_and_home_are_not_destinations(result):
    dest = _destinations(result)
    for not_dest in ("frankfurt", "washington", "dulles"):
        assert not_dest not in dest, dest


def test_not_offered_as_a_version_of_the_itinerary(result):
    """Draft (owner to confirm): a ticket is not a revision of the plan."""
    match = first(result, "kb_entry").get("existing_match")
    assert not match, match


# ------------------------------------------------------------------ after Save


@pytest.fixture(scope="module")
def saved(client, result):
    """Save the proposal exactly as the app's review card does
    (frontend/lib/api.ts pushKBEntryWithAsset -> POST /kb/entries/with-asset)."""
    entry = first(result, "kb_entry")
    form = {"folder": entry["folder"], "title": entry["title"], "content": entry["content"],
            "links": ",".join(entry.get("links") or []), "on_conflict": entry.get("on_conflict") or "new"}
    if entry.get("fields"):
        form["fields"] = json.dumps(entry["fields"])
    r = client.post("/kb/entries/with-asset", data=form,
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


def test_saved_ticket_sits_in_the_trip_folder_tree(saved):
    note_id, folder = saved
    assert folder == TRIP_FOLDER, folder
    up = _reachable(note_id)
    for f in (f"folder:{TRIP_FOLDER}", "folder:fun/travel/planned", "folder:fun/travel", "folder:fun"):
        assert f in up, (f, sorted(up))


def test_saved_ticket_is_linked_to_the_itinerary(saved):
    note_id, _ = saved
    assert (note_id, ITINERARY_NOTE) in _edges(), [e for e in _edges() if note_id in e]


def test_saved_vienna_chains_to_austria_and_europe(saved):
    up = _reachable(saved[0])
    assert any(n.startswith("place:") and n.endswith("/vienna") for n in up), sorted(up)
    assert any(n.startswith("place:") and n.endswith("/austria") for n in up), sorted(up)
    assert "place:europe" in up, sorted(up)


def test_saved_ticket_touches_no_layover_home_or_vault(saved):
    note_id, _ = saved
    touched = {t for s, t in _edges() if s == note_id} | {s for s, t in _edges() if t == note_id}
    reach = _reachable(note_id) | touched
    assert not any(n.endswith(("/frankfurt", "/washington", "/dulles")) for n in reach), sorted(reach)
    assert not any("document-vault" in n or n.startswith("vault") for n in touched)
