"""The "what was I doing that day" recall chain: photos in the /day bundle
(resolved through real `on_day` edges in the edges table), the shared
day_recall MCP tool, and the on-demand /kb/asset/describe vision endpoint
(vision stubbed — no live API calls here)."""
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.mcp_server import server as s
from quintacle_core.nodes.journal.store import JournalStore
from quintacle_core.nodes.kb import api as kb_api
from quintacle_core.nodes.kb.store import KBStore


# --- photos in GET /day/{date} (REST, full app, real edges) ---


def test_day_bundle_includes_photo_note_linked_via_real_edge(tmp_path, monkeypatch):
    kb = KBStore(tmp_path / "kb")
    JournalStore(tmp_path / "journal").save(date(2026, 10, 10), "lake day with friends")

    # Written the same way a committed photo drop lands: body description +
    # trailing [asset](...) line, journal date in frontmatter links. The
    # app's startup catch-up materializes that link into an on_day edge.
    folder, slug = kb.write(
        "Media/Photos/2026/October",
        "Lake hike",
        "A misty morning hike around the lake.",
        links=["2026-10-10"],
    )
    asset_path = kb.save_asset(folder, "lake.jpg", b"fake-jpeg-bytes")
    kb.write(
        "Media/Photos/2026/October",
        "Lake hike",
        f"A misty morning hike around the lake.\n\n[asset]({asset_path})",
        links=["2026-10-10"],
    )
    # A linked note with no image assets is still relevant recall.
    kb.write("Thoughts", "Lake reflections", "Felt great being outside all day.", links=["2026-10-10"])

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())

    res = client.get("/day/2026-10-10")
    assert res.status_code == 200
    bundle = res.json()
    assert "lake day with friends" in bundle["journal"]

    photos = {p["slug"]: p for p in bundle["photos"]}
    assert set(photos) == {"lake-hike", "lake-reflections"}

    hike = photos["lake-hike"]
    assert hike["folder"] == folder
    assert hike["title"] == "Lake hike"
    assert "misty morning" in hike["description"]
    assert "[asset]" not in hike["description"]  # plumbing lines stripped
    assert hike["assets"] == [asset_path]

    assert photos["lake-reflections"]["assets"] == []

    # A day nothing links to has an empty, not missing, photos list.
    assert client.get("/day/2026-10-11").json()["photos"] == []


# --- day_recall MCP tool (shared bundle code path) ---


@pytest.fixture
def mcp_stores(tmp_path):
    s.init(tmp_path)
    yield tmp_path


def test_day_recall_mcp_round_trip(mcp_stores):
    s.journal_append(for_date="2026-10-12", content="long day of sync work")
    created = s.kb_create_entry(
        folder="Media/Photos/2026/October",
        title="Harbor sunset",
        content="Golden light over the harbor.",
        links=["2026-10-12"],
    )

    bundle = s.day_recall(for_date="2026-10-12")

    assert bundle["date"] == "2026-10-12"
    assert "long day of sync work" in bundle["journal"]
    assert [p["slug"] for p in bundle["photos"]] == [created["slug"]]
    photo = bundle["photos"][0]
    assert photo["folder"] == created["folder"]
    assert "Golden light over the harbor." in photo["description"]
    assert photo["assets"] == []
    # The rest of the bundle keeps the /day/{date} shape.
    for key in ("todos_due", "activities", "exercise", "food", "body_stats", "substances", "expenses"):
        assert key in bundle

    assert s.day_recall(for_date="2026-10-13")["photos"] == []


# --- describe_photo MCP tool (vision stubbed) ---


def test_describe_photo_resolves_slug_to_first_image_asset(mcp_stores, monkeypatch):
    created = s.kb_create_entry(folder="Media", title="Pier", content="Wooden pier at dusk.")
    # A non-image asset first proves the tool skips to the first IMAGE.
    s.kb_store.add_asset_to_entry(created["folder"], created["slug"], "notes.pdf", b"%PDF")
    asset = s.kb_store.add_asset_to_entry(created["folder"], created["slug"], "pier.png", b"png-bytes")

    calls = {}

    def fake_describe(photos, question=None):
        calls["photos"], calls["question"] = photos, question
        return "a wooden pier, three boats visible"

    monkeypatch.setattr(s, "describe_images", fake_describe)

    out = s.describe_photo(folder=created["folder"], slug_or_path=created["slug"], question="how many boats?")

    assert out == {"folder": created["folder"], "path": asset, "description": "a wooden pier, three boats visible"}
    assert calls["photos"] == [(b"png-bytes", "image/png")]
    assert calls["question"] == "how many boats?"


def test_describe_photo_accepts_direct_asset_path(mcp_stores, monkeypatch):
    path = s.kb_store.save_asset("media", "loose.jpg", b"jpeg-bytes")
    monkeypatch.setattr(s, "describe_images", lambda photos, question=None: "a loose photo")

    out = s.describe_photo(folder="media", slug_or_path=path)
    assert out["path"] == path
    assert out["description"] == "a loose photo"


def test_describe_photo_errors_without_spending(mcp_stores, monkeypatch):
    def explode(*args, **kwargs):  # any vision call here would be a real bill
        raise AssertionError("describe_images must not be called on error paths")

    monkeypatch.setattr(s, "describe_images", explode)

    with pytest.raises(ValueError, match="no such entry"):
        s.describe_photo(folder="media", slug_or_path="nope")

    created = s.kb_create_entry(folder="Media", title="Text only", content="No photo here.")
    with pytest.raises(ValueError, match="no image asset"):
        s.describe_photo(folder=created["folder"], slug_or_path=created["slug"])

    with pytest.raises(ValueError, match="asset not found"):
        s.describe_photo(folder="media", slug_or_path="assets/missing.jpg")


# --- POST /kb/asset/describe (REST, vision stubbed) ---


def make_kb_client(tmp_path) -> TestClient:
    app = FastAPI()
    kb_api.init_store(tmp_path / "kb")
    app.include_router(kb_api.router)
    return TestClient(app)


def test_describe_asset_answers_question_about_image(tmp_path, monkeypatch):
    client = make_kb_client(tmp_path)
    path = kb_api.get_store().save_asset("trips", "sunset.jpg", b"jpeg-bytes")

    calls = {}

    def fake_describe(photos, question=None):
        calls["photos"], calls["question"] = photos, question
        return "an orange sky over water"

    monkeypatch.setattr(kb_api, "describe_images", fake_describe)

    res = client.post("/kb/asset/describe", json={"folder": "trips", "path": path, "question": "what color is the sky?"})

    assert res.status_code == 200
    assert res.json() == {"folder": "trips", "path": path, "description": "an orange sky over water"}
    assert calls["photos"] == [(b"jpeg-bytes", "image/jpeg")]
    assert calls["question"] == "what color is the sky?"


def test_describe_asset_error_paths_never_call_vision(tmp_path, monkeypatch):
    client = make_kb_client(tmp_path)
    store = kb_api.get_store()
    pdf_path = store.save_asset("trips", "itinerary.pdf", b"%PDF")
    # A real file OUTSIDE the KB root an escaping path would otherwise reach.
    (tmp_path / "vault").mkdir()
    (tmp_path / "vault" / "secret.jpg").write_bytes(b"ciphertext")

    def explode(*args, **kwargs):
        raise AssertionError("describe_images must not be called on error paths")

    monkeypatch.setattr(kb_api, "describe_images", explode)

    # Non-image asset -> 400.
    res = client.post("/kb/asset/describe", json={"folder": "trips", "path": pdf_path})
    assert res.status_code == 400

    # Missing asset -> 404.
    res = client.post("/kb/asset/describe", json={"folder": "trips", "path": "assets/missing.jpg"})
    assert res.status_code == 404

    # Escaping path -> clamped to a plain 404, even though the file exists.
    res = client.post("/kb/asset/describe", json={"folder": "trips", "path": "../../vault/secret.jpg"})
    assert res.status_code == 404
