"""Travel's Planned / Unsorted / Bucket-list states (2026-11-05,
nodes/travel/states.py + travel/api.py). Every store is a tmp sandbox; no
model calls (all deterministic file work)."""
from __future__ import annotations

import frontmatter
import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.retrieval as retrieval
from quintacle_core.nodes.kb import llm as kb_llm
from quintacle_core.nodes.travel.states import experience_matches


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    c.kb_root = tmp_path / "kb"
    return c


def _write_note(root, folder, slug, title, body="", fields=None, extra=None):
    d = root.joinpath(*folder.split("/"))
    d.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(f"# {title}\n\n{body}\n")
    if fields:
        post["fields"] = fields
    for k, v in (extra or {}).items():
        post[k] = v
    (d / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
    return d / f"{slug}.md"


def test_planned_listing_groups_fields_and_sort(client):
    root = client.kb_root
    _write_note(root, "fun/travel/planned/europe", "central-europe-2027", "Central Europe 2027",
                fields={"start": "2027-05-10", "end": "2027-05-24", "destinations": "Vienna, Prague", "status": "booked"})
    _write_note(root, "fun/travel/planned", "weekend-away", "Weekend Away")
    _write_note(root, "fun/travel/planned/japan", "kyoto", "Kyoto Trip", fields={"start": "2027-03-01"})
    _write_note(root, "fun/travel/planned", "about-planned", "About Planned")  # charter
    rows = client.get("/travel/planned").json()
    assert [r["slug"] for r in rows] == ["kyoto", "central-europe-2027", "weekend-away"]
    ce = rows[1]
    assert ce["group"] == "europe" and ce["folder"] == "fun/travel/planned/europe"
    assert ce["title"] == "Central Europe 2027"
    assert (ce["start"], ce["end"], ce["destinations"], ce["status"]) == ("2027-05-10", "2027-05-24", "Vienna, Prague", "booked")
    assert rows[2]["group"] == "" and rows[2]["start"] is None and rows[2]["status"] is None
    # Planned notes never leak into the experience registry.
    assert client.get("/travel/experiences").json() == []


def test_unsorted_lists_notes_directly_in_travel(client):
    root = client.kb_root
    _write_note(root, "fun/travel", "budapest-itinerary", "Budapest Itinerary")
    _write_note(root, "fun/travel", "about-travel", "About Travel")
    _write_note(root, "fun/travel/planned", "other", "Other")
    rows = client.get("/travel/unsorted").json()
    assert [(r["slug"], r["group"], r["folder"]) for r in rows] == [("budapest-itinerary", "", "fun/travel")]


def test_move_carries_assets_and_refuses_overwrite(client):
    root = client.kb_root
    _write_note(root, "fun/travel", "vienna-trip", "Vienna Trip", body="Plan\n[asset](assets/ticket.pdf)",
                extra={"assets": ["assets/map.png"]})
    _write_note(root, "fun/travel", "other-trip", "Other Trip", body="[asset](assets/shared.jpg)")
    assets = root / "fun/travel/assets"
    assets.mkdir(parents=True)
    (assets / "ticket.pdf").write_bytes(b"pdf")
    (assets / "map.png").write_bytes(b"png")
    (assets / "shared.jpg").write_bytes(b"jpg")
    # vienna also references the asset other-trip uses -> copied, not moved
    p = root / "fun/travel/vienna-trip.md"
    p.write_text(p.read_text().replace("Plan", "Plan ![](assets/shared.jpg)"))

    r = client.post("/travel/planned/move", json={"folder": "fun/travel", "slug": "vienna-trip", "group": "Europe"})
    assert r.status_code == 200, r.text
    assert r.json() == {"folder": "fun/travel/planned/europe", "slug": "vienna-trip"}
    dest = root / "fun/travel/planned/europe"
    assert (dest / "vienna-trip.md").exists() and not p.exists()
    assert (dest / "assets/ticket.pdf").read_bytes() == b"pdf" and not (assets / "ticket.pdf").exists()
    assert (dest / "assets/map.png").exists() and not (assets / "map.png").exists()
    assert (dest / "assets/shared.jpg").exists() and (assets / "shared.jpg").exists()
    assert client.get("/kb/asset", params={"folder": "fun/travel/planned/europe", "path": "assets/ticket.pdf"}).status_code == 200
    rows = client.get("/travel/planned").json()
    assert rows[0]["group"] == "europe"

    # A second note with the same slug can't overwrite the moved one.
    _write_note(root, "fun/travel", "vienna-trip", "Vienna Trip")
    r = client.post("/travel/planned/move", json={"folder": "fun/travel", "slug": "vienna-trip", "group": "europe"})
    assert r.status_code == 409
    assert (root / "fun/travel/vienna-trip.md").exists()
    # Missing note -> 404; empty group -> directly in Planned.
    assert client.post("/travel/planned/move", json={"folder": "fun/travel", "slug": "nope"}).status_code == 404
    r = client.post("/travel/planned/move", json={"folder": "fun/travel", "slug": "vienna-trip"})
    assert r.json() == {"folder": "fun/travel/planned", "slug": "vienna-trip"}


def test_move_rekeys_graph_edges(client):
    from quintacle_core.graph import create_edge, get_graph_store

    root = client.kb_root
    _write_note(root, "fun/travel", "rome-trip", "Rome Trip")
    create_edge("note:somewhere/x", "note:fun/travel/rome-trip", "related", "frontmatter_link")
    client.post("/travel/planned/move", json={"folder": "fun/travel", "slug": "rome-trip", "group": "Italy"})
    targets = [e["target_id"] for e in get_graph_store().all()]
    assert "note:fun/travel/planned/italy/rome-trip" in targets
    assert "note:fun/travel/rome-trip" not in targets


def test_bucket_crud_and_visited(client):
    client.post("/travel/experiences", json={"name": "Figlmüller", "city": "Vienna", "kind": "restaurant", "visited_date": "2026-06-02"})
    client.post("/travel/experiences", json={"name": "Café Central", "city": "Vienna", "kind": "cafe", "visited_date": "2026-06-01"})
    r = client.post("/travel/bucket", json={"place": "Vienna", "notes": "Opera night"})
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["place"] == "Vienna" and row["notes"] == "Opera night" and row["folder"] == "fun/travel/bucket-list"
    assert row["visited"] is True and row["visited_on"] == "2026-06-01" and len(row["experience_ids"]) == 2
    assert row["added"]
    assert client.post("/travel/bucket", json={"place": "Vienna"}).status_code == 409

    client.post("/travel/bucket", json={"place": "Kyoto, Japan"})
    rows = {r["slug"]: r for r in client.get("/travel/bucket").json()}
    assert rows["kyoto-japan"]["visited"] is False and rows["kyoto-japan"]["visited_on"] is None
    # bucket notes aren't experiences
    assert len(client.get("/travel/experiences").json()) == 2

    assert client.delete("/travel/bucket/vienna").json() == {"deleted": "vienna"}
    assert "vienna" not in {r["slug"] for r in client.get("/travel/bucket").json()}
    assert client.delete("/travel/bucket/vienna").status_code == 404


def test_visited_matching_whole_word():
    assert experience_matches("Kyoto, Japan", {"city": "Kyoto", "name": "Fushimi Inari"})
    assert experience_matches("vienna", {"city": "Vienna", "name": "x"})
    assert experience_matches("Rome", {"city": "Rome, Italy", "name": "x"})
    assert not experience_matches("Rome", {"city": "Romeoville", "name": "x"})
    assert not experience_matches("Romeoville", {"city": "Rome", "name": "x"})
    assert not experience_matches("Paris", {"city": "New York", "name": "Paris Baguette"})
    assert experience_matches("Eiffel Tower, Paris", {"city": "", "name": "Eiffel Tower"})


def test_seed_folders_and_placement_travel_rule():
    assert "Fun/Travel/Planned" in kb_llm.SEED_FOLDERS and "Fun/Travel/Bucket List" in kb_llm.SEED_FOLDERS
    for prompt in (kb_llm._PLACEMENT_SYSTEM_PROMPT, kb_llm._SYSTEM_PROMPT, kb_llm._BATCH_SYSTEM_PROMPT):
        assert "Fun/Travel/Planned/<Region or Trip>" in prompt
        assert "Fun/Travel/Bucket List" in prompt
        assert "NEW SUBFOLDER" in prompt
