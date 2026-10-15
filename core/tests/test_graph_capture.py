"""The graph-capture coverage retrofit end to end (graph_capture.py):
journal saves link what they mention through BOTH entry paths (REST and MCP,
one shared helper), item-shaped stores link their description prose, the
startup backfill content-scans pre-existing journal days/notes, places emerge
deterministically at PLACE_EMERGENCE_THRESHOLD distinct mentions, and /graph
types person/place nodes for the hub view."""
from datetime import date

from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.db import connect
from quintacle_core.graph import get_graph_store, init_graph_store, reverse_lookup
from quintacle_core.graph_capture import (
    PLACE_EMERGENCE_THRESHOLD,
    run_graph_capture_backfill,
    wardrobe_item_note_id,
)
from quintacle_core.mcp_server import server as mcp_server
from quintacle_core.nodes.journal.api import init_store as init_journal_store, save_journal
from quintacle_core.nodes.kb.api import EntryCreate, create_entry, init_store as init_kb_store
from quintacle_core.nodes.kb.store import KBStore
from quintacle_core.nodes.people.api import init_store as init_people_store
from quintacle_core.nodes.people.store import PersonStore
from quintacle_core.nodes.travel.api import ExperienceCreate, create_experience, init_store as init_travel_store
from quintacle_core.nodes.travel.store import ExperienceStore


def setup_stores(tmp_path):
    kb_root = tmp_path / "kb"
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))
    init_journal_store(tmp_path / "journal")
    init_kb_store(kb_root)
    init_travel_store(kb_root)
    init_people_store(kb_root)
    return kb_root


# --- the shared journal helper: REST and MCP create identical edges ---


def test_rest_journal_save_links_people_and_experiences(tmp_path):
    kb_root = setup_stores(tmp_path)
    PersonStore(kb_root).write("Laura", category="friend")
    ExperienceStore(kb_root).write("Carbone", "New York", "restaurant")

    save_journal(date(2026, 10, 14), "Dinner at Carbone with Laura tonight.")

    edges = get_graph_store().edges_from("journal:2026-10-14")
    by_kind = {e["kind"]: e["target_id"] for e in edges}
    assert by_kind["mentions_person"] == "note:people/laura/profile"
    assert by_kind["at_location"] == "experience:planning/travel/new-york/restaurants/carbone"


def test_rest_journal_resave_does_not_duplicate_edges(tmp_path):
    kb_root = setup_stores(tmp_path)
    PersonStore(kb_root).write("Laura", category="friend")

    save_journal(date(2026, 10, 14), "Coffee with Laura.")
    save_journal(date(2026, 10, 14), "Laura stayed for dinner too.")

    edges = get_graph_store().edges_from("journal:2026-10-14")
    assert len(edges) == 1  # create_edge dedupes on (source, target, kind)
    assert len(list((tmp_path / "graph" / "edges").glob("*.md"))) == 1


def test_mcp_journal_append_creates_the_same_edges_as_rest(tmp_path):
    rest_dir, mcp_dir = tmp_path / "rest", tmp_path / "mcp"
    for d in (rest_dir, mcp_dir):
        PersonStore(d / "kb").write("Laura", category="friend")
        ExperienceStore(d / "kb").write("Carbone", "New York", "restaurant")
    content = "Dinner at Carbone with Laura tonight."

    kb_root = rest_dir / "kb"
    init_graph_store(rest_dir, connect(rest_dir / "test.db"))
    init_journal_store(rest_dir / "journal")
    init_kb_store(kb_root)
    init_travel_store(kb_root)
    init_people_store(kb_root)
    save_journal(date(2026, 10, 14), content)
    rest_edges = {(e["kind"], e["target_id"]) for e in get_graph_store().edges_from("journal:2026-10-14")}

    mcp_server.init(mcp_dir)  # repoints the graph store singleton at mcp_dir
    mcp_server.journal_append(for_date="2026-10-14", content=content)
    mcp_edges = {(e["kind"], e["target_id"]) for e in get_graph_store().edges_from("journal:2026-10-14")}

    assert rest_edges == mcp_edges
    assert ("mentions_person", "note:people/laura/profile") in mcp_edges


# --- item-shaped stores: description prose links to people/experiences ---


def test_wardrobe_item_description_links_to_person(tmp_path, monkeypatch):
    PersonStore(tmp_path / "kb").write("Laura", category="friend")
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())

    res = client.post(
        "/wardrobe/items",
        data={"name": "Leather Jacket", "category": "jacket", "description": "The jacket Laura got me."},
    )
    assert res.status_code == 200

    edges = get_graph_store().edges_from(wardrobe_item_note_id("Leather Jacket"))
    assert [(e["kind"], e["target_id"]) for e in edges] == [("mentions_person", "note:people/laura/profile")]


def test_activity_description_links_from_its_day(tmp_path, monkeypatch):
    ExperienceStore(tmp_path / "kb").write("Mia Italina Kitchen", "Alexandria", "restaurant")
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())

    res = client.post(
        "/logs/activities",
        json={"date": "2026-09-11", "category": "social", "description": "Went to Mia Italina Kitchen with friends"},
    )
    assert res.status_code == 200

    edges = get_graph_store().edges_from("journal:2026-09-11")
    assert [(e["kind"], e["target_id"]) for e in edges] == [
        ("at_location", "experience:planning/travel/alexandria/restaurants/mia-italina-kitchen")
    ]


# --- the backfill: OLD content gets content-scanned at startup ---


def test_backfill_scans_existing_journal_and_notes_for_mentions(tmp_path, monkeypatch):
    kb = KBStore(tmp_path / "kb")
    PersonStore(tmp_path / "kb").write("Laura", category="friend")
    (tmp_path / "journal").mkdir()
    (tmp_path / "journal" / "2026-09-01.md").write_text("### 21:00\nLong walk with Laura.", encoding="utf-8")
    kb.write("Thoughts", "Gift ideas", "Laura mentioned she wants pottery classes.")

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    TestClient(api_module.create_app())  # startup backfill runs in create_app

    person_edges = reverse_lookup("note:people/laura/profile")
    sources = {(e["source_id"], e["source_of_edge"]) for e in person_edges if e["kind"] == "mentions_person"}
    assert ("journal:2026-09-01", "mention_backfill") in sources
    assert ("note:thoughts/gift-ideas", "mention_backfill") in sources

    # Idempotent: a second startup over the same data creates nothing new.
    n_before = len(get_graph_store().all())
    TestClient(api_module.create_app())
    assert len(get_graph_store().all()) == n_before


# --- emergent places ---


def test_place_emerges_at_exactly_the_threshold(tmp_path):
    kb_root = setup_stores(tmp_path)
    assert PLACE_EMERGENCE_THRESHOLD == 3

    # Mention 1: the experience itself (its own city field counts).
    create_experience(ExperienceCreate(name="Pastel Bakery", city="Lisbon", kind="bakery", notes="Great tarts."))
    # Mention 2: a journal day.
    save_journal(date(2026, 10, 1), "Booked the flight to Lisbon today.")

    kb = KBStore(kb_root)
    assert kb.read("Places", "lisbon") is None
    assert reverse_lookup("note:places/lisbon") == []

    # Mention 3: a note — this write pushes Lisbon over the threshold and
    # emerges the place immediately (no restart needed).
    create_entry(EntryCreate(folder="Thoughts", title="Lisbon packing list", content="Shorts. Sunscreen."))

    assert kb.read("Places", "lisbon") is not None
    assert kb.read_fields("places", "lisbon") == {"kind": "place", "city": "Lisbon"}
    edges = reverse_lookup("note:places/lisbon")
    assert len(edges) == 3
    assert {e["kind"] for e in edges} == {"at_location"}
    assert {e["source_of_edge"] for e in edges} == {"emergent_place"}
    assert {e["source_id"] for e in edges} == {
        "experience:planning/travel/lisbon/bakerys/pastel-bakery",
        "journal:2026-10-01",
        "note:thoughts/lisbon-packing-list",
    }


def test_place_emergence_rerun_is_idempotent(tmp_path):
    kb_root = setup_stores(tmp_path)
    create_experience(ExperienceCreate(name="Pastel Bakery", city="Lisbon", kind="bakery"))
    save_journal(date(2026, 10, 1), "Booked the flight to Lisbon today.")
    create_entry(EntryCreate(folder="Thoughts", title="Lisbon packing list", content="Shorts."))

    kb = KBStore(kb_root)
    note_before = kb.read("Places", "lisbon")
    edges_before = len(list((tmp_path / "graph" / "edges").glob("*.md")))

    run_graph_capture_backfill()
    run_graph_capture_backfill()

    assert kb.read("Places", "lisbon") == note_before  # never rewritten
    assert len(list((tmp_path / "graph" / "edges").glob("*.md"))) == edges_before
    # A FOURTH mention later still tops up one new edge, no duplicates.
    save_journal(date(2026, 10, 2), "Lisbon again, can't wait.")
    assert len(reverse_lookup("note:places/lisbon")) == 4


# --- /graph typing ---


def test_graph_endpoint_types_person_and_place_nodes(tmp_path, monkeypatch):
    kb = KBStore(tmp_path / "kb")
    PersonStore(tmp_path / "kb").write("Laura", category="friend", notes="Met at a party.")
    ExperienceStore(tmp_path / "kb").write("Carbone", "New York", "restaurant")
    kb.write("Places", "Lisbon", "Emergent place — first seen across 3 entries.", fields={"kind": "place", "city": "Lisbon"})

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())
    nodes = {n["id"]: n for n in client.get("/graph").json()["nodes"]}

    person = nodes["note:people/laura/profile"]
    assert person["type"] == "person"
    assert person["label"] == "Laura"

    assert nodes["note:places/lisbon"]["type"] == "place"

    # An experience's own KB file appears once, under its experience: id —
    # not again as an untyped duplicate note.
    assert "experience:planning/travel/new-york/restaurants/carbone" in nodes
    assert "note:planning/travel/new-york/restaurants/carbone" not in nodes
