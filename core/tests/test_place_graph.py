"""The place hierarchy in the graph (place_graph.py, 2026-11-05): photo /
experience / trip plan → city (located_in), city → country → continent
(part_of), real Places notes preferred over virtual nodes, idempotency,
the backfill endpoint, /graph emission, retrieval's place-member graph lane,
privacy for cloud neighbors, and chat context. Sandbox only — geocode is
stubbed, no network or models."""
from __future__ import annotations

import frontmatter
import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core import retrieval
from quintacle_core.graph import get_graph_store
from quintacle_core.mcp_server import server as s
from quintacle_core.nodes.kb import chat, photo_organizer
from quintacle_core.nodes.kb import api as kb_api
from quintacle_core.nodes.kb.photo_organizer import GeocodedLocation
from quintacle_core.nodes.kb.privacy import private_filter
from quintacle_core.place_graph import destination_chains, level_of, place_slug, _Ctx

from test_photo_place import jpeg

VIENNA = (48.2082, 16.3738)
GRAZ = (47.0707, 15.4395)
PARIS = (48.8566, 2.3522)

EU, AT, VIE = "place:europe", "place:europe/austria", "place:europe/austria/vienna"


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def geo(monkeypatch):
    table = {
        round(VIENNA[0], 1): GeocodedLocation(country="Austria", state="Vienna", city="Vienna"),
        round(GRAZ[0], 1): GeocodedLocation(country="Austria", state="Styria", city="Graz"),
        round(PARIS[0], 1): GeocodedLocation(country="France", state="Île-de-France", city="Paris"),
    }
    monkeypatch.setattr(photo_organizer, "geocode", lambda lat, lon: table[round(lat, 1)])


@pytest.fixture
def client(tmp_path, monkeypatch, geo):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    # Seeded registries (CLAUDE.md: entity-grounded, never scratch).
    c.post("/people", json={"name": "Laura", "category": "friend", "how_met": "college"})
    c.post("/logs/meals", json={"name": "Chipotle bowl", "kcal": 800, "protein_g": 45})
    c.post("/kb/entries", json={"folder": "Fitness", "title": "Deadlift Cues", "content": "Brace."})
    return c


def commit_photo(client, gps=VIENNA, title="Stephansdom", private=False, folder="Media/Photos/2027/May"):
    form = {"folder": folder, "title": title, "content": "A big cathedral.", "links": ""}
    if private:
        form["private"] = "true"
    res = client.post("/kb/entries/with-asset", data=form, files=[("files", ("p.jpg", jpeg(gps), "image/jpeg"))])
    assert res.status_code == 200, res.text
    out = res.json()
    return f"note:{out['folder']}/{out['slug']}"


def edges(kind=None):
    rows = get_graph_store().all()
    return {(e["source_id"], e["target_id"], e["kind"]) for e in rows if kind is None or e["kind"] == kind}


def write_note(tmp_path, folder_slug, slug, meta, body="Some text."):
    d = tmp_path / "kb" / folder_slug
    d.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body, **meta)
    (d / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
    return f"note:{folder_slug}/{slug}"


# --------------------------------------------------------------- pure parts


def test_slug_and_level():
    assert place_slug("Zürich") == "zurich"
    assert place_slug("North America") == "north-america"
    assert level_of(EU) == "continent" and level_of(AT) == "country" and level_of(VIE) == "city"
    assert level_of("note:places/vienna") is None


# --------------------------------------------------------------- photos


def test_photo_save_builds_the_hierarchy(client):
    nid = commit_photo(client)
    e = edges()
    assert (nid, VIE, "located_in") in e
    assert (VIE, AT, "part_of") in e and (AT, EU, "part_of") in e
    idx = retrieval.get_retrieval_index()
    assert idx.get_node(VIE)["title"] == "Vienna"
    assert idx.get_node(VIE)["summary"].startswith("City in Austria, Europe")
    assert "1 photo" in idx.get_node(EU)["summary"]


def test_idempotent_resave_and_backfill(client):
    commit_photo(client)
    before = edges()
    n_files = len(list(get_graph_store().edges_dir.glob("*.md")))
    res = client.post("/kb/graph/backfill-places?dry_run=false").json()
    assert res["edges"] == 0
    assert edges() == before
    assert len(list(get_graph_store().edges_dir.glob("*.md"))) == n_files


def test_real_places_note_is_preferred(client):
    client.post("/kb/entries", json={"folder": "Places", "title": "Vienna", "content": "The city."})
    nid = commit_photo(client)
    e = edges()
    assert (nid, "note:places/vienna", "located_in") in e
    assert ("note:places/vienna", AT, "part_of") in e
    assert not any(t == VIE for _, t, _ in e)


def test_rest_add_asset_links(client):
    created = client.post("/kb/entries", json={"folder": "Trips", "title": "Weekend", "content": "Nice."}).json()
    client.post(
        "/kb/entry/asset",
        data={"folder": created["folder"], "slug": created["slug"]},
        files={"file": ("v.jpg", jpeg(PARIS), "image/jpeg")},
    )
    assert (f"note:{created['folder']}/{created['slug']}", "place:europe/france/paris", "located_in") in edges()


# --------------------------------------------------------------- experiences + plans


def test_experience_borrows_country_from_existing_city(client):
    commit_photo(client)
    client.post("/travel/experiences", json={"name": "Figlmüller", "city": "Vienna", "kind": "restaurant"})
    [exp] = [x for x in client.get("/travel/experiences").json() if x["name"] == "Figlmüller"]
    assert (f"experience:{exp['folder']}/{exp['slug']}", VIE, "located_in") in edges()


def test_city_only_experience_is_rekeyed_when_country_learned(client):
    client.post("/travel/experiences", json={"name": "Schlossberg", "city": "Graz", "kind": "sight"})
    [exp] = client.get("/travel/experiences").json()
    exp_id = f"experience:{exp['folder']}/{exp['slug']}"
    assert (exp_id, "place:_/_/graz", "located_in") in edges()
    commit_photo(client, gps=GRAZ, title="Clock tower")
    e = edges()
    assert (exp_id, "place:europe/austria/graz", "located_in") in e
    assert not any("place:_/_/graz" in (a, b) for a, b, _ in e)


def test_planned_trip_links_each_destination(client):
    commit_photo(client)
    res = client.post(
        "/kb/entries",
        json={"folder": "Fun/Travel/Planned", "title": "Austria 2027", "content": "Plan.", "fields": {"destinations": "Vienna, Salzburg"}},
    ).json()
    plan = f"note:{res['folder']}/{res['slug']}"
    e = edges()
    assert (plan, VIE, "located_in") in e
    assert (plan, "place:_/_/salzburg", "located_in") in e
    # editing destinations re-syncs (stale edge removed)
    client.post(
        "/kb/entries",
        json={"folder": "Fun/Travel/Planned", "title": "Austria 2027", "content": "Plan.", "fields": {"destinations": "Vienna"}},
    )
    e = edges()
    assert (plan, VIE, "located_in") in e and (plan, "place:_/_/salzburg", "located_in") not in e


def test_destination_country_token_assigns_country(client):
    ctx = _Ctx(None, get_graph_store(), dry_run=True)
    chains = destination_chains(ctx, "Lyon, France; Japan")
    ids = [[r.id for r in c] for c in chains]
    assert ids == [["place:europe/france/lyon", "place:europe/france", EU], ["place:asia/japan", "place:asia"]]


def test_move_into_planned_links(client):
    res = client.post(
        "/kb/entries",
        json={"folder": "Fun/Travel", "title": "Paris trip", "content": "Ideas.", "fields": {"destinations": "Paris, France"}},
    ).json()
    assert not any(k == "located_in" for _, _, k in edges())
    moved = client.post("/travel/planned/move", json={"folder": res["folder"], "slug": res["slug"]}).json()
    assert (f"note:{moved['folder']}/{moved['slug']}", "place:europe/france/paris", "located_in") in edges()


# --------------------------------------------------------------- backfill


def test_backfill_dry_run_then_apply(client, tmp_path):
    photo = write_note(tmp_path, "media/photos", "old-photo", {"place": {"city": "Vienna", "state": "", "country": "Austria", "continent": "Europe"}})
    plan = write_note(tmp_path, "fun/travel/planned", "trip", {"title": "Trip", "fields": {"destinations": "Vienna, Graz"}})
    client.post("/travel/experiences", json={"name": "Prater", "city": "Vienna", "kind": "sight"})
    # the experience save made Vienna city-only (no country yet)
    get_graph_store().conn.execute("SELECT 1")
    dry = client.post("/kb/graph/backfill-places").json()
    assert dry["dry_run"] is True and dry["counts"]["photos"] == 1 and dry["counts"]["plans"] == 1
    assert (photo, VIE, "located_in") not in edges()
    applied = client.post("/kb/graph/backfill-places?dry_run=false").json()
    assert applied["counts"]["photos"] == 1 and applied["sample"]
    e = edges()
    assert (photo, VIE, "located_in") in e and (plan, VIE, "located_in") in e
    assert any(s.startswith("experience:") and t == VIE for s, t, _ in e)  # rekeyed off place:_/_/vienna
    again = client.post("/kb/graph/backfill-places?dry_run=false").json()
    assert again["edges"] == 0


# --------------------------------------------------------------- /graph


def test_graph_emits_place_nodes_and_edges(client):
    nid = commit_photo(client)
    g = client.get("/graph").json()
    by_id = {n["id"]: n for n in g["nodes"]}
    assert by_id[EU]["level"] == "continent" and by_id[EU]["label"] == "Europe" and by_id[EU]["type"] == "place"
    assert by_id[AT]["level"] == "country" and by_id[VIE]["level"] == "city"
    assert "folder" not in by_id[VIE]
    got = {(e["source"], e["target"], e["kind"]) for e in g["edges"]}
    assert {(nid, VIE, "located_in"), (VIE, AT, "part_of"), (AT, EU, "part_of")} <= got


# --------------------------------------------------------------- retrieval / privacy / chat


def test_retrieval_europe_and_austria_reach_photo_via_place_node(client, tmp_path):
    # A photo whose BODY names no place — only its frontmatter does — so the
    # only route from "Europe" to it is the place node's graph lane.
    photo = write_note(tmp_path, "media/photos", "quiet", {"title": "Quiet Morning", "place": {"city": "Vienna", "country": "Austria", "continent": "Europe"}}, body="# Quiet Morning\n\nCoffee.")
    client.post("/kb/graph/backfill-places?dry_run=false")
    for q in ("Europe", "Austria", "Vienna"):
        hits = retrieval.retrieve(q, k=5)
        place_hit = next(h for h in hits if h["id"].startswith("place:"))
        assert photo in [n["id"] for n in place_hit["neighbors"]], q


def test_private_photo_kept_out_of_cloud_neighbors(client, tmp_path):
    private = write_note(tmp_path, "media/photos", "secret", {"title": "Secret", "private": True, "place": {"city": "Vienna", "country": "Austria"}})
    public = write_note(tmp_path, "media/photos", "open", {"title": "Open", "place": {"city": "Vienna", "country": "Austria"}})
    client.post("/kb/graph/backfill-places?dry_run=false")
    local = retrieval.retrieve("Europe", k=5)
    eu = next(h for h in local if h["id"] == EU)
    assert {private, public} <= {n["id"] for n in eu["neighbors"]}
    cloud = retrieval.retrieve("Europe", k=5, exclude=private_filter(kb_api.get_store()))
    eu = next(h for h in cloud if h["id"] == EU)
    ids = {n["id"] for n in eu["neighbors"]}
    assert public in ids and private not in ids
    # the model-visible summary never counts the private photo
    assert "1 photo" in retrieval.get_retrieval_index().get_node(EU)["summary"]


def test_chat_photos_from_europe_surfaces_photo_via_place(client, tmp_path, monkeypatch):
    photo = write_note(tmp_path, "media/photos", "quiet", {"title": "Quiet Morning", "place": {"city": "Vienna", "country": "Austria", "continent": "Europe"}}, body="# Quiet Morning\n\nCoffee.")
    client.post("/kb/graph/backfill-places?dry_run=false")
    captured = []

    def runner(model, messages, kb_text):
        captured.append(kb_text)
        return "stub-reply"

    for name in ("_run_anthropic", "_run_openai", "_run_bedrock", "_run_local"):
        monkeypatch.setattr(chat, name, runner)
    resp = client.post("/kb/chat", json={"messages": [{"role": "user", "content": "photos from Europe"}]})
    assert resp.status_code == 200, resp.text
    [kb_text] = captured
    assert f"id: {photo}" in kb_text


# --------------------------------------------------------------- MCP


def test_mcp_attach_links_and_undo_removes_edges(tmp_path, geo):
    s.init(tmp_path / "data")
    created = s.kb_create_entry(folder="Trips", title="Vienna trip", content="Walked a lot.")
    src = tmp_path / "elsewhere"
    src.mkdir()
    (src / "IMG_1.jpg").write_bytes(jpeg(VIENNA))
    result = s.kb_attach_file(folder=created["folder"], slug=created["slug"], local_path=str(src / "IMG_1.jpg"))
    nid = f"note:{created['folder']}/{created['slug']}"
    assert (nid, VIE, "located_in") in edges()
    s.undo_write(result["ledger_id"])
    assert not any(k in ("located_in", "part_of") for _, _, k in edges())
    assert not list((tmp_path / "data" / "graph" / "edges").glob("*.md")) or all(
        "place:" not in p.read_text() for p in (tmp_path / "data" / "graph" / "edges").glob("*.md")
    )


def test_mcp_create_planned_note_links_destinations(tmp_path):
    s.init(tmp_path / "data")
    created = s.kb_create_entry(folder="Fun/Travel/Planned", title="Japan", content="Plan.", fields={"destinations": "Tokyo, Japan"})
    assert (f"note:{created['folder']}/{created['slug']}", "place:asia/japan/tokyo", "located_in") in edges()
