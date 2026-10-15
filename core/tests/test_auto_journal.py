"""The auto photo-journal: deterministic composer (zero LLM calls), the
marker-tagged journal append on photo commit (dedup'd, strippable), the
pictured_with/at_location graph edges (reference, never duplication), the
unknown-face tag flow, and /people/{name}/appearances.

The perception module is a seam built in a parallel worktree — every test
here stubs it (sys.modules injection, same lazy-import path production
takes), in both matched-face and unknown-face shapes, plus absent entirely."""
from __future__ import annotations

import io
import json
import sys
import types
from datetime import date, datetime

from fastapi.testclient import TestClient
from PIL import Image

import quintacle_core.api as api_module
from quintacle_core.graph import get_graph_store, reverse_lookup
from quintacle_core.nodes.journal.store import JournalStore
from quintacle_core.nodes.kb.auto_journal import (
    add_person_to_line,
    auto_journal_line,
    photo_marker,
    place_from_photo_folder,
    split_faces,
)
from quintacle_core.nodes.kb.drop import extract_photo_date, extract_photo_datetime


# --------------------------------------------------------------- fixtures


def jpeg_with_exif(stamp: str = "2026:10:10 14:14:00") -> bytes:
    img = Image.new("RGB", (4, 4), "red")
    exif = Image.Exif()
    exif[306] = stamp  # DateTime, base IFD
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def jpeg_without_exif() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, format="JPEG")
    return buf.getvalue()


def stub_perception(monkeypatch, result=None, enroll_calls: list | None = None, perceive=None):
    """Installs a fake quintacle_core.perception module — the exact import
    path auto_journal's lazy import resolves."""
    mod = types.ModuleType("quintacle_core.perception")
    mod.perceive_photo = perceive if perceive is not None else (lambda data, mime: result)

    def enroll_face(embedding_id: str, person_name: str) -> None:
        if enroll_calls is not None:
            enroll_calls.append((embedding_id, person_name))

    mod.enroll_face = enroll_face
    monkeypatch.setitem(sys.modules, "quintacle_core.perception", mod)
    return mod


MATCHED = {
    "tags": ["dog", "frisbee"],
    "scene": {"daylight": True, "outdoor_hint": True, "brightness": 0.8},
    "faces": [{"box": [0, 0, 2, 2], "embedding_id": "emb-1", "match": {"person_name": "Alex", "score": 0.95}}],
}

UNKNOWN = {
    "tags": ["lake"],
    "scene": {"daylight": True, "outdoor_hint": True, "brightness": 0.4},
    "faces": [{"box": [1, 1, 3, 3], "embedding_id": "emb-9", "match": None}],
}


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


def commit_photo(client, data: bytes, folder="Media/Photos/2026/October/Hermann Park", title="Lake hike", perception=""):
    form = {"folder": folder, "title": title, "content": "A great afternoon out.", "links": ""}
    if perception:
        form["perception"] = perception
    res = client.post("/kb/entries/with-asset", data=form, files=[("files", ("lake.jpg", data, "image/jpeg"))])
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------- the composer


def test_composer_full_line():
    line = auto_journal_line(
        MATCHED,
        exif_time=datetime(2026, 10, 10, 14, 14),
        place_name="Hermann Park",
        people_names=["Alex"],
        photo_title="Lake hike",
    )
    assert line == "📷 2:14 PM — with Alex at Hermann Park · sunny · dog, frisbee (photo: Lake hike)"


def test_composer_is_deterministic():
    args = dict(exif_time=datetime(2026, 10, 10, 9, 5), place_name="Shibuya", people_names=["Riya", "Sam"])
    assert auto_journal_line(MATCHED, **args) == auto_journal_line(MATCHED, **args)


def test_composer_omits_absent_parts():
    assert auto_journal_line(None, photo_title="Lake hike") == "📷 (photo: Lake hike)"
    assert auto_journal_line(None, exif_time=datetime(2026, 1, 2, 8, 30)) == "📷 8:30 AM"
    assert (
        auto_journal_line(None, exif_time=datetime(2026, 1, 2, 18, 0), people_names=["Sam", "Riya", "Alex"])
        == "📷 6:00 PM — with Sam, Riya and Alex"
    )


def test_composer_scene_words_and_tag_cap():
    night = {"tags": ["a", "b", "c", "d", "e", "f"], "scene": {"daylight": False}, "faces": []}
    assert auto_journal_line(night) == "📷 · night · a, b, c, d"  # tags capped at 4
    indoor = auto_journal_line({"tags": [], "scene": {"daylight": True, "outdoor_hint": False}, "faces": []})
    assert indoor == "📷 · indoors"


def test_split_faces_threshold_sends_low_scores_to_tag_flow():
    low = {"tags": [], "scene": {}, "faces": [{"box": [], "embedding_id": "e2", "match": {"person_name": "Sam", "score": 0.4}}]}
    matched, unknown = split_faces(low)
    assert matched == []
    assert unknown[0]["embedding_id"] == "e2"
    assert unknown[0]["suggested_name"] == "Sam"  # offered, never asserted

    matched, unknown = split_faces(MATCHED)
    assert matched == ["Alex"] and unknown == []


def test_add_person_to_line_all_shapes():
    base = "📷 2:14 PM — with Alex at Hermann Park · sunny (photo: Lake hike)"
    assert add_person_to_line(base, "Sam") == "📷 2:14 PM — with Alex and Sam at Hermann Park · sunny (photo: Lake hike)"
    assert add_person_to_line(add_person_to_line(base, "Sam"), "Riya").startswith("📷 2:14 PM — with Alex, Sam and Riya at ")
    assert add_person_to_line(base, "Alex") == base  # dedup — already there
    assert add_person_to_line("📷 2:14 PM — at Hermann Park", "Sam") == "📷 2:14 PM — with Sam at Hermann Park"
    assert add_person_to_line("📷 2:14 PM · sunny", "Sam") == "📷 2:14 PM — with Sam · sunny"
    assert add_person_to_line("📷 (photo: X)", "Sam") == "📷 — with Sam (photo: X)"


def test_place_from_photo_folder():
    assert place_from_photo_folder("media/photos/2026/october/hermann-park") == "Hermann Park"
    assert place_from_photo_folder("media/photos/2026/october/japan/tokyo/shibuya") == "Shibuya"
    assert place_from_photo_folder("media/photos/2026/october") is None  # everyday home life
    assert place_from_photo_folder("fitness") is None


def test_exif_datetime_extraction():
    data = jpeg_with_exif("2026:10:10 14:14:00")
    assert extract_photo_date(data) == date(2026, 10, 10)
    assert extract_photo_datetime(data) == datetime(2026, 10, 10, 14, 14, 0)
    assert extract_photo_datetime(jpeg_without_exif()) is None


# ------------------------------------------- journal store marker plumbing


def test_namespaced_marker_round_trip(tmp_path):
    store = JournalStore(tmp_path / "journal")
    d = date(2026, 10, 10)
    marker = photo_marker("media/photos/2026/october/hermann-park", "lake-hike")
    store.save(d, "morning pages")
    store.save(d, "📷 2:14 PM — with Alex at Hermann Park", marker=marker)

    assert store.has_marked_append(d, marker)
    assert store.read_marked_append(d, marker) == "📷 2:14 PM — with Alex at Hermann Park"
    # load() strips namespaced markers the same way it strips hex MCP ones
    loaded = store.load(d)
    assert "mcp-append" not in loaded and "auto-photo" not in loaded
    assert "📷 2:14 PM — with Alex at Hermann Park" in loaded

    assert store.rewrite_marked_append(d, marker, "📷 2:14 PM — with Alex and Sam at Hermann Park")
    assert store.read_marked_append(d, marker) == "📷 2:14 PM — with Alex and Sam at Hermann Park"

    # and the span is undoable exactly like an MCP append
    assert store.strip_marked_append(d, marker)
    assert not store.has_marked_append(d, marker)
    assert "morning pages" in store.load(d) and "📷" not in store.load(d)


# ------------------------------------------------------- the commit flow


def test_photo_commit_appends_journal_line_once_with_edges(tmp_path, monkeypatch):
    stub_perception(monkeypatch, result=MATCHED)
    client = make_client(tmp_path, monkeypatch)
    client.post("/people", json={"name": "Alex", "category": "friend"})

    data = jpeg_with_exif()
    result = commit_photo(client, data)
    summary = result["perception"]
    assert summary["people"] == ["Alex"]
    assert summary["unknown_faces"] == []
    assert summary["journal_date"] == "2026-10-10"
    assert summary["journal_appended"] is True
    assert summary["auto_line"] == "📷 2:14 PM — with Alex at Hermann Park · sunny · dog, frisbee (photo: Lake hike)"

    journal = client.get("/journal/2026-10-10").json()["content"]
    assert journal.count("📷") == 1
    assert "with Alex at Hermann Park" in journal
    assert "mcp-append" not in journal  # markers are plumbing, stripped on read

    person_id = "note:people/alex/profile"
    kinds = [(e["kind"], e["source_id"]) for e in reverse_lookup(person_id)]
    note_id = f"note:{result['folder']}/{result['slug']}"
    assert ("pictured_with", note_id) in kinds
    assert ("pictured_with", "journal:2026-10-10") in kinds
    pictured = [e for e in reverse_lookup(person_id) if e["kind"] == "pictured_with"]
    assert all(e["source_of_edge"] == "photo_perception" for e in pictured)

    # Re-committing the same photo: no second line, no duplicate edges.
    commit_photo(client, data)
    journal = client.get("/journal/2026-10-10").json()["content"]
    assert journal.count("📷") == 1
    assert len([e for e in reverse_lookup(person_id) if e["kind"] == "pictured_with"]) == len(pictured)


def test_photo_commit_links_resolved_experience(tmp_path, monkeypatch):
    stub_perception(monkeypatch, result=None)  # perception declining still links place
    client = make_client(tmp_path, monkeypatch)
    client.post(
        "/travel/experiences",
        json={"name": "Hermann Park", "city": "Houston", "kind": "park", "notes": "the park"},
    )
    result = commit_photo(client, jpeg_with_exif())

    exp = [e for e in get_graph_store().all() if e["kind"] == "at_location" and e["source_of_edge"] == "photo_perception"]
    assert len(exp) == 1
    assert exp[0]["source_id"] == f"note:{result['folder']}/{result['slug']}"
    assert exp[0]["target_id"].startswith("experience:")


def test_photo_commit_without_perception_module_still_journals(tmp_path, monkeypatch):
    # Module made unimportable (None in sys.modules raises ImportError) —
    # that must read as "no perception", not an error: EXIF + the folder
    # place still make a line.
    monkeypatch.setitem(sys.modules, "quintacle_core.perception", None)
    client = make_client(tmp_path, monkeypatch)
    result = commit_photo(client, jpeg_with_exif())
    summary = result["perception"]
    assert summary["people"] == [] and summary["unknown_faces"] == []
    assert summary["auto_line"] == "📷 2:14 PM — at Hermann Park (photo: Lake hike)"
    assert "at Hermann Park" in client.get("/journal/2026-10-10").json()["content"]


def test_photo_without_exif_date_writes_no_journal_line(tmp_path, monkeypatch):
    stub_perception(monkeypatch, result=MATCHED)
    client = make_client(tmp_path, monkeypatch)
    client.post("/people", json={"name": "Alex"})
    result = commit_photo(client, jpeg_without_exif(), folder="Media/Photos/2026/October")
    summary = result["perception"]
    assert summary["journal_date"] is None and summary["auto_line"] is None
    # the person edge to the photo note still exists — only the day link needs a date
    assert any(e["kind"] == "pictured_with" for e in reverse_lookup("note:people/alex/profile"))


def test_commit_uses_proposal_perception_payload_without_rerunning(tmp_path, monkeypatch):
    def boom(data, mime):
        raise AssertionError("perceive_photo must not re-run when the proposal carried a perception payload")

    stub_perception(monkeypatch, perceive=boom)
    client = make_client(tmp_path, monkeypatch)
    client.post("/people", json={"name": "Alex"})
    result = commit_photo(client, jpeg_with_exif(), perception=json.dumps(MATCHED))
    assert result["perception"]["people"] == ["Alex"]


# ------------------------------------------------------- the tag flow


def test_unknown_face_tag_flow_end_to_end(tmp_path, monkeypatch):
    enroll_calls: list = []
    stub_perception(monkeypatch, result=UNKNOWN, enroll_calls=enroll_calls)
    client = make_client(tmp_path, monkeypatch)

    result = commit_photo(client, jpeg_with_exif())
    unknowns = result["perception"]["unknown_faces"]
    assert unknowns == [{"embedding_id": "emb-9", "box": [1, 1, 3, 3], "suggested_name": None}]
    # unknowns are never guessed into the journal
    journal = client.get("/journal/2026-10-10").json()["content"]
    assert "with" not in journal

    res = client.post(
        "/perception/tag",
        json={"embedding_id": "emb-9", "person_name": "Riya", "photo": {"folder": result["folder"], "slug": result["slug"]}},
    )
    assert res.status_code == 200, res.text
    tag = res.json()
    assert tag["person_name"] == "Riya"
    assert tag["created_person"] is True
    assert tag["enrolled"] is True
    assert tag["journal_updated"] is True
    assert enroll_calls == [("emb-9", "Riya")]

    # person entry exists now
    assert any(p["name"] == "Riya" for p in client.get("/people").json())
    # journal line gained the person, in place — still exactly one line
    journal = client.get("/journal/2026-10-10").json()["content"]
    assert journal.count("📷") == 1
    assert "with Riya at Hermann Park" in journal
    # edges: photo → person and day → person
    kinds = {(e["kind"], e["source_id"]) for e in reverse_lookup("note:people/riya/profile")}
    assert ("pictured_with", f"note:{result['folder']}/{result['slug']}") in kinds
    assert ("pictured_with", "journal:2026-10-10") in kinds

    # tagging the same face again with the same name: idempotent, no dupes
    client.post(
        "/perception/tag",
        json={"embedding_id": "emb-9", "person_name": "Riya", "photo": {"folder": result["folder"], "slug": result["slug"]}},
    )
    journal = client.get("/journal/2026-10-10").json()["content"]
    assert journal.count("📷") == 1 and journal.count("Riya") == 1


def test_tag_matches_existing_person_and_survives_missing_perception(tmp_path, monkeypatch):
    stub_perception(monkeypatch, result=UNKNOWN)
    client = make_client(tmp_path, monkeypatch)
    client.post("/people", json={"name": "Alex", "category": "friend"})
    result = commit_photo(client, jpeg_with_exif())

    # Perception module gone by tag time (e.g. phone install) — enrollment is
    # skipped but person/edges/journal still happen.
    monkeypatch.setitem(sys.modules, "quintacle_core.perception", None)
    res = client.post(
        "/perception/tag",
        json={"embedding_id": "emb-9", "person_name": "alex", "photo": {"folder": result["folder"], "slug": result["slug"]}},
    )
    tag = res.json()
    assert tag["person_name"] == "Alex"  # canonicalized, no second Alex forked
    assert tag["created_person"] is False
    assert tag["enrolled"] is False
    assert "with Alex" in client.get("/journal/2026-10-10").json()["content"]


def test_tag_unknown_photo_404s(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    res = client.post(
        "/perception/tag",
        json={"embedding_id": "e", "person_name": "Riya", "photo": {"folder": "nope", "slug": "nothing"}},
    )
    assert res.status_code == 404


# ------------------------------------------------- computed appearances


def test_person_appearances_computed_from_graph(tmp_path, monkeypatch):
    stub_perception(monkeypatch, result=MATCHED)
    client = make_client(tmp_path, monkeypatch)
    client.post("/people", json={"name": "Alex", "category": "friend"})
    result = commit_photo(client, jpeg_with_exif())

    res = client.get("/people/Alex/appearances")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Alex"
    assert body["dates"] == ["2026-10-10"]
    assert [(p["folder"], p["slug"], p["title"]) for p in body["photos"]] == [
        (result["folder"], result["slug"], "Lake hike")
    ]
    # nothing was written into the person's own file — computed, not copied
    profile = (tmp_path / "kb" / "people" / "alex" / "profile.md").read_text(encoding="utf-8")
    assert "Lake hike" not in profile and "📷" not in profile

    assert client.get("/people/Nobody/appearances").status_code == 404
