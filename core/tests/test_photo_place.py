"""Photo place baking (nodes/kb/photo_place.py): the 📍 line in the note
BODY (so retrieval finds photos by city/country/continent), the continent
table, the geocode cache, privacy (no cloud geocode), idempotency, every
save path, and the backfill endpoint. Geocode + EXIF are stubbed / built in
memory — never real network or models."""
from __future__ import annotations

import io
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import quintacle_core.api as api_module
from quintacle_core import retrieval
from quintacle_core.mcp_server import server as s
from quintacle_core.nodes.kb import photo_organizer
from quintacle_core.nodes.kb.photo_organizer import GeocodedLocation
from quintacle_core.nodes.kb.photo_place import (
    PLACE_MARKER,
    compose_place_line,
    continent_for,
    insert_place_line,
    is_place_line,
)

VIENNA = (48.2082, 16.3738)


def _dms(v: float):
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    sec = round(((v - d) * 60 - m) * 60, 4)
    return (float(d), float(m), sec)


def jpeg(gps: tuple[float, float] | None = VIENNA, stamp: str | None = "2027:05:14 15:32:00") -> bytes:
    img = Image.new("RGB", (4, 4), "red")
    exif = Image.Exif()
    if stamp:
        exif[306] = stamp
    if gps:
        lat, lon = gps
        exif[0x8825] = {1: "N" if lat >= 0 else "S", 2: _dms(lat), 3: "E" if lon >= 0 else "W", 4: _dms(lon)}
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


@pytest.fixture
def geo_calls(monkeypatch):
    calls: list[tuple[float, float]] = []

    def fake(lat, lon):
        calls.append((lat, lon))
        return GeocodedLocation(country="Austria", state="Vienna", city="Vienna")

    monkeypatch.setattr(photo_organizer, "geocode", fake)
    return calls


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


def commit(client, data: bytes, title="Stephansdom", private=False, name="vienna.jpg", folder="Media/Photos/2027/May"):
    form = {"folder": folder, "title": title, "content": "A big cathedral.", "links": ""}
    if private:
        form["private"] = "true"
    res = client.post("/kb/entries/with-asset", data=form, files=[("files", (name, data, "image/jpeg"))])
    assert res.status_code == 200, res.text
    return res.json()


def note_text(tmp_path, folder_slug, slug) -> str:
    return (tmp_path / "kb" / folder_slug / f"{slug}.md").read_text()


def hit_ids(query):
    return [h["id"] for h in retrieval.retrieve(query, k=10)]


# --------------------------------------------------------------- pure parts


def test_line_format():
    line = compose_place_line(
        {"city": "Vienna", "state": "Vienna", "country": "Austria", "continent": "Europe"},
        {"lat": 48.20821, "lon": 16.37381},
        datetime(2027, 5, 14, 15, 32),
    )
    assert line == f"📍 Vienna, Austria · Europe · 48.2082, 16.3738 · taken 2027-05-14 15:32 {PLACE_MARKER}"
    assert is_place_line(line)
    assert compose_place_line(None, None, None) is None


@pytest.mark.parametrize(
    "country,continent",
    [
        ("USA", "North America"),
        ("United States", "North America"),
        ("the United States of America", "North America"),
        ("UK", "Europe"),
        ("United Kingdom", "Europe"),
        ("Czechia", "Europe"),
        ("Czech Republic", "Europe"),
        ("Japan", "Asia"),
        ("Côte d'Ivoire", "Africa"),
        ("Brazil", "South America"),
        ("New Zealand", "Oceania"),
        ("Atlantis", None),
        ("", None),
    ],
)
def test_continent_table(country, continent):
    assert continent_for(country) == continent


def test_insert_place_line_idempotent_and_before_assets():
    body = "# T\n\nHello.\n\n[asset](assets/a.jpg)\n[asset](assets/b.jpg)\n"
    line = f"📍 Vienna · 1.0000, 2.0000 {PLACE_MARKER}"
    once = insert_place_line(body, line)
    twice = insert_place_line(once, f"📍 Graz {PLACE_MARKER}")
    assert once == f"# T\n\nHello.\n\n{line}\n\n[asset](assets/a.jpg)\n[asset](assets/b.jpg)\n"
    assert twice.count("📍") == 1 and "Graz" in twice and "Vienna" not in twice
    assert insert_place_line(once, line) == once


# --------------------------------------------------------------- drop save


def test_drop_save_bakes_line_place_and_is_retrievable(client, tmp_path, geo_calls):
    out = commit(client, jpeg())
    text = note_text(tmp_path, out["folder"], out["slug"])
    assert "📍 Vienna, Austria · Europe · 48.2082, 16.3738 · taken 2027-05-14 15:32" in text
    assert text.index("📍") < text.index("[asset](")
    assert "continent: Europe" in text and "country: Austria" in text
    nid = f"note:{out['folder']}/{out['slug']}"
    for q in ("Vienna", "Austria", "Europe"):
        assert nid in hit_ids(q), q
    # the summary skips the place line like asset lines
    assert "📍" not in retrieval.deterministic_prose_summary(text)


def test_batch_from_one_place_costs_one_geocode(client, tmp_path, geo_calls):
    commit(client, jpeg(), title="One")
    commit(client, jpeg(gps=(48.20825, 16.37385)), title="Two")
    commit(client, jpeg(), title="Three")
    assert len(geo_calls) == 1
    assert (tmp_path / "geocode-cache.json").exists()


def test_private_never_calls_geocoder(client, tmp_path, geo_calls):
    out = commit(client, jpeg(), private=True)
    assert geo_calls == []
    text = note_text(tmp_path, out["folder"], out["slug"])
    assert f"📍 48.2082, 16.3738 · taken 2027-05-14 15:32 {PLACE_MARKER}" in text
    assert "Austria" not in text and "Europe" not in text


def test_no_gps_writes_date_only(client, tmp_path, geo_calls):
    out = commit(client, jpeg(gps=None))
    text = note_text(tmp_path, out["folder"], out["slug"])
    assert f"📍 taken 2027-05-14 15:32 {PLACE_MARKER}" in text
    assert geo_calls == []


def test_no_exif_at_all_writes_no_line(client, tmp_path, geo_calls):
    out = commit(client, jpeg(gps=None, stamp=None))
    assert "📍" not in note_text(tmp_path, out["folder"], out["slug"])


def test_geocode_failure_does_not_break_save(client, tmp_path, monkeypatch):
    def boom(lat, lon):
        raise RuntimeError("cloud down")

    monkeypatch.setattr(photo_organizer, "geocode", boom)
    out = commit(client, jpeg())
    text = note_text(tmp_path, out["folder"], out["slug"])
    assert f"📍 48.2082, 16.3738 · taken 2027-05-14 15:32 {PLACE_MARKER}" in text


def test_pdf_untouched(client, tmp_path, geo_calls):
    res = client.post(
        "/kb/entries/with-asset",
        data={"folder": "Docs", "title": "Contract", "content": "x", "links": ""},
        files=[("files", ("c.pdf", b"%PDF-1.7 x", "application/pdf"))],
    )
    out = res.json()
    assert "📍" not in note_text(tmp_path, out["folder"], out["slug"])


def test_rest_add_asset_bakes_and_indexes(client, tmp_path, geo_calls):
    created = client.post("/kb/entries", json={"folder": "Trips", "title": "Weekend", "content": "Nice."}).json()
    res = client.post(
        "/kb/entry/asset",
        data={"folder": created["folder"], "slug": created["slug"]},
        files={"file": ("v.jpg", jpeg(), "image/jpeg")},
    )
    assert res.status_code == 200
    assert "📍 Vienna, Austria" in note_text(tmp_path, created["folder"], created["slug"])
    assert f"note:{created['folder']}/{created['slug']}" in hit_ids("Europe")


# --------------------------------------------------------------- MCP attach


def test_mcp_attach_image_bakes_and_undo_restores(tmp_path, geo_calls):
    s.init(tmp_path / "data")
    created = s.kb_create_entry(folder="Trips", title="Vienna trip", content="Walked a lot.")
    path = s.kb_store.entry_path(created["folder"], created["slug"])
    before = path.read_bytes()
    src = tmp_path / "elsewhere"
    src.mkdir()
    (src / "IMG_1.jpg").write_bytes(jpeg())
    result = s.kb_attach_file(folder=created["folder"], slug=created["slug"], local_path=str(src / "IMG_1.jpg"))
    text = path.read_text()
    assert "📍 Vienna, Austria · Europe" in text
    assert f"note:{created['folder']}/{created['slug']}" in [h["id"] for h in s.search_index("Austria")]
    s.undo_write(result["ledger_id"])
    assert path.read_bytes() == before


def test_mcp_attach_pdf_no_line(tmp_path, geo_calls):
    s.init(tmp_path / "data")
    created = s.kb_create_entry(folder="Docs", title="Lease", content="Lease.")
    src = tmp_path / "elsewhere"
    src.mkdir()
    (src / "lease.pdf").write_bytes(b"%PDF-1.7 lease")
    s.kb_attach_file(folder=created["folder"], slug=created["slug"], local_path=str(src / "lease.pdf"))
    assert "📍" not in s.kb_store.entry_path(created["folder"], created["slug"]).read_text()


# --------------------------------------------------------------- backfill


def _legacy_photo_note(tmp_path, private=False):
    """A photo note saved before this feature: asset + frontmatter location, no 📍 line."""
    folder = tmp_path / "kb" / "media" / "photos" / "2027" / "may"
    (folder / "assets").mkdir(parents=True)
    (folder / "assets" / "old.jpg").write_bytes(jpeg())
    extra = "private: true\n" if private else ""
    (folder / "old-photo.md").write_text(
        f"---\nlinks: []\nlocation:\n  lat: 48.2082\n  lon: 16.3738\n{extra}---\n# Old photo\n\nA cathedral.\n\n[asset](assets/old.jpg)\n"
    )
    return folder / "old-photo.md"


def test_backfill_dry_run_then_apply(client, tmp_path, geo_calls):
    note = _legacy_photo_note(tmp_path)
    original = note.read_text()
    dry = client.post("/kb/photos/backfill-place").json()
    assert dry["dry_run"] is True and dry["count"] == 1
    assert dry["changes"][0]["place"]["continent"] == "Europe"
    assert note.read_text() == original
    applied = client.post("/kb/photos/backfill-place?dry_run=false").json()
    assert applied["count"] == 1
    text = note.read_text()
    assert text.count("📍") == 1 and "Vienna, Austria · Europe" in text
    assert "note:media/photos/2027/may/old-photo" in hit_ids("Europe")
    # idempotent: nothing left to change, geocoded once overall (cache)
    assert client.post("/kb/photos/backfill-place?dry_run=false").json()["count"] == 0
    assert len(geo_calls) == 1


def test_backfill_private_note_skips_geocode(client, tmp_path, geo_calls):
    note = _legacy_photo_note(tmp_path, private=True)
    client.post("/kb/photos/backfill-place?dry_run=false")
    assert geo_calls == []
    assert f"📍 48.2082, 16.3738 · taken 2027-05-14 15:32 {PLACE_MARKER}" in note.read_text()
