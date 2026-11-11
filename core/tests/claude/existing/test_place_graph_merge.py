"""2026-11-07 place-graph gap: with a real Places/<City> note, trip plans
and experiences must land on THAT note (the same rule photos use), and an
orphan virtual `place:_/_/<city>` node (made before the note existed, or by
a plan/experience saved before it emerged) is merged into it — on save and
by the backfill. Sandbox only — geocode stubbed, no models."""
from __future__ import annotations

from test_place_graph import AT, EU, _reset_retrieval_singleton, client, commit_photo, edges, geo  # noqa: F401

from quintacle_core import retrieval
from quintacle_core.graph import get_graph_store
from quintacle_core.nodes.kb import api as kb_api
from quintacle_core.place_graph import backfill_places, link_note_places

ORPHAN = "place:_/_/vienna"
NOTE = "note:places/vienna"


def _plan(client, destinations="Vienna, Salzburg"):
    res = client.post("/kb/entries", json={
        "folder": "Fun/Travel/Planned/Central Europe", "title": "Central Europe 2027", "content": "Trains and museums.",
        "fields": {"start": "2027-05-12", "end": "2027-05-21", "destinations": destinations},
    }).json()
    return f"note:{res['folder']}/{res['slug']}"


def _experience(client, name="Cafe Central", city="Vienna"):
    client.post("/travel/experiences", json={"name": name, "city": city, "kind": "restaurant"})
    [exp] = [x for x in client.get("/travel/experiences").json() if x["name"] == name]
    return f"experience:{exp['folder']}/{exp['slug']}"


def test_plan_and_experience_use_existing_places_note(client):
    client.post("/kb/entries", json={"folder": "Places", "title": "Vienna", "content": "The city."})
    plan_id = _plan(client)
    exp_id = _experience(client)
    photo_id = commit_photo(client)
    e = edges()
    for src in (plan_id, exp_id, photo_id):
        assert (src, NOTE, "located_in") in e, src
    assert not any(ORPHAN in (a, b) for a, b, _ in e)
    assert (NOTE, AT, "part_of") in e and (AT, EU, "part_of") in e


def test_places_note_with_differently_cased_slug_title_still_matches(client):
    # A Places note whose title carries the country ("Vienna, Austria") or a
    # different casing still IS the city note — matched by its slug/city field.
    kb_api.get_store().write("Places", "Vienna", "The city.", links=[], fields={"kind": "place", "city": "Vienna"})
    plan_id = _plan(client)
    assert (plan_id, NOTE, "located_in") in edges()


def test_orphan_virtual_city_is_merged_into_places_note_on_save(client):
    exp_id = _experience(client)  # no Places note yet, country unknown → orphan virtual city
    assert (exp_id, ORPHAN, "located_in") in edges()
    store = kb_api.get_store()
    store.write("Places", "Vienna", "Emergent place.", links=[], fields={"kind": "place", "city": "Vienna"})
    plan_id = _plan(client)  # the next save that resolves Vienna to the note merges the orphan
    e = edges()
    assert (plan_id, NOTE, "located_in") in e
    assert (exp_id, NOTE, "located_in") in e
    assert not any(ORPHAN in (a, b) for a, b, _ in e)
    assert retrieval.get_retrieval_index().get_node(ORPHAN) is None


def test_backfill_merges_existing_orphans(client):
    exp_id = _experience(client)
    plan_id = _plan(client)
    assert (plan_id, ORPHAN, "located_in") in edges()
    # The Places note appears out of band (emergence writes the file directly).
    kb_api.get_store().write("Places", "Vienna", "Emergent place.", links=[], fields={"kind": "place", "city": "Vienna"})
    dry = client.post("/kb/graph/backfill-places?dry_run=true").json()
    assert dry["dry_run"] is True and (plan_id, ORPHAN, "located_in") in edges()  # dry run writes nothing
    client.post("/kb/graph/backfill-places?dry_run=false")
    e = edges()
    assert (exp_id, NOTE, "located_in") in e and (plan_id, NOTE, "located_in") in e
    assert not any(ORPHAN in (a, b) for a, b, _ in e)
    # Then a geocoded photo gives the note its country — the same chain photos always had.
    photo_id = commit_photo(client)
    e = edges()
    assert (photo_id, NOTE, "located_in") in e and (NOTE, AT, "part_of") in e
    # Idempotent: a second backfill changes nothing.
    before = edges()
    assert client.post("/kb/graph/backfill-places?dry_run=false").json()["edges"] == 0
    assert edges() == before


def test_hierarchical_virtual_city_merged_into_places_note(client):
    # A photo saved before the Places note existed sits on place:europe/austria/vienna;
    # once the note exists, a re-link moves it (and the city's part_of) onto the note.
    photo_id = commit_photo(client)
    assert (photo_id, "place:europe/austria/vienna", "located_in") in edges()
    store = kb_api.get_store()
    store.write("Places", "Vienna", "The city.", links=[], fields={"kind": "place", "city": "Vienna"})
    folder, slug = photo_id[5:].rsplit("/", 1)
    link_note_places(store, folder, slug, graph_store=get_graph_store())
    e = edges()
    assert (photo_id, NOTE, "located_in") in e and (NOTE, AT, "part_of") in e
    assert not any("place:europe/austria/vienna" in (a, b) for a, b, _ in e)
