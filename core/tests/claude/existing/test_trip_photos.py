"""Trip ↔ photos (trip_photos.py, 2026-11-05): a photo taken during a planned
trip gets a `during_trip` edge to the plan — capture day in [start, end] and
destination match (or no destinations). Sandbox only; geocode stubbed, no
network or models. Seeded registries per CLAUDE.md."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core import retrieval
from quintacle_core.graph import get_graph_store
from quintacle_core.nodes.kb import photo_organizer
from quintacle_core.nodes.kb.photo_organizer import GeocodedLocation
from quintacle_core.trip_photos import KIND, parse_body_dates

from test_photo_place import jpeg

VIENNA = (48.2082, 16.3738)
PARIS = (48.8566, 2.3522)


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    table = {
        round(VIENNA[0], 1): GeocodedLocation(country="Austria", state="Vienna", city="Vienna"),
        round(PARIS[0], 1): GeocodedLocation(country="France", state="Île-de-France", city="Paris"),
    }
    monkeypatch.setattr(photo_organizer, "geocode", lambda lat, lon: table[round(lat, 1)])
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    c.post("/people", json={"name": "Laura", "category": "friend", "how_met": "college"})
    c.post("/logs/meals", json={"name": "Chipotle bowl", "kcal": 800, "protein_g": 45})
    c.post("/travel/experiences", json={"name": "Cafe Central", "city": "Vienna", "kind": "cafe"})
    return c


def photo(client, gps=VIENNA, stamp="2027:05:14 15:32:00", title="Stephansdom"):
    form = {"folder": "Media/Photos/2027/May", "title": title, "content": "A photo.", "links": ""}
    res = client.post("/kb/entries/with-asset", data=form, files=[("files", ("p.jpg", jpeg(gps, stamp), "image/jpeg"))])
    assert res.status_code == 200, res.text
    out = res.json()
    return f"note:{out['folder']}/{out['slug']}"


def plan(client, title, content="Itinerary.", **fields):
    res = client.post("/kb/entries", json={"folder": "Fun/Travel/Planned", "title": title, "content": content, "fields": fields or None})
    assert res.status_code == 200, res.text
    out = res.json()
    return f"note:{out['folder']}/{out['slug']}"


def trip_edges():
    return {(e["source_id"], e["target_id"]) for e in get_graph_store().all() if e["kind"] == KIND}


def test_in_range_destination_match_links_and_out_of_range_does_not(client):
    trip = plan(client, "Central Europe", start="2027-05-10", end="2027-05-20", destinations="Vienna, Prague")
    inside = photo(client)
    outside = photo(client, stamp="2027:06:01 10:00:00", title="Later")
    elsewhere = photo(client, gps=PARIS, title="Eiffel")  # in range, wrong city
    e = trip_edges()
    assert (inside, trip) in e
    assert (outside, trip) not in e
    assert (elsewhere, trip) not in e


def test_country_destination_matches_city_in_it(client):
    trip = plan(client, "Austria loop", start="2027-05-10", end="2027-05-20", destinations="Austria")
    p = photo(client)
    assert (p, trip) in trip_edges()


def test_no_destination_plan_links_by_date_only(client):
    trip = plan(client, "Mystery trip", start="2027-05-14", end="2027-05-14")
    a = photo(client)
    b = photo(client, gps=PARIS, title="Eiffel")
    assert {(a, trip), (b, trip)} <= trip_edges()


def test_body_date_parsing():
    assert parse_body_dates("We go May 12 – May 21, 2027!") == (date(2027, 5, 12), date(2027, 5, 21))
    assert parse_body_dates("Dates: May 12–21, 2027") == (date(2027, 5, 12), date(2027, 5, 21))
    assert parse_body_dates("2027-05-12 to 2027-05-21") == (date(2027, 5, 12), date(2027, 5, 21))
    assert parse_body_dates("12–21 May 2027") == (date(2027, 5, 12), date(2027, 5, 21))
    assert parse_body_dates("Dec 28 – Jan 3, 2028") == (date(2027, 12, 28), date(2028, 1, 3))
    assert parse_body_dates("Fly out 2027-05-12, hotel, fly back May 18, 2027") == (date(2027, 5, 12), date(2027, 5, 18))
    assert parse_body_dates("Booked 2026-01-01; trip 2027-05-12") == (None, None)  # >60-day spread
    assert parse_body_dates("no dates here") == (None, None)


def test_plan_without_fields_uses_body_dates_and_known_city(client):
    p_vienna = photo(client)  # creates the Vienna place node
    p_paris = photo(client, gps=PARIS, title="Eiffel")
    trip = plan(client, "AI-dropped plan", content="Trip to Vienna, May 12 – May 21, 2027. Maybe Atlantis.")
    e = trip_edges()
    assert (p_vienna, trip) in e
    assert (p_paris, trip) not in e  # body names a known city → destination-filtered


def test_idempotent_and_stale_removed(client):
    trip = plan(client, "Central Europe", start="2027-05-10", end="2027-05-20", destinations="Vienna")
    p = photo(client)
    folder, slug = p.removeprefix("note:").rsplit("/", 1)
    before = [e for e in get_graph_store().all() if e["kind"] == KIND]
    client.post("/kb/entries", json={"folder": "Fun/Travel/Planned", "title": "Central Europe", "content": "Itinerary.",
                                     "fields": {"start": "2027-05-10", "end": "2027-05-20", "destinations": "Vienna"}})
    after = [e for e in get_graph_store().all() if e["kind"] == KIND]
    assert len(before) == len(after) == 1
    # Plan moves its dates away → the edge goes.
    client.post("/kb/entries", json={"folder": "Fun/Travel/Planned", "title": "Central Europe", "content": "Itinerary.",
                                     "fields": {"start": "2027-07-01", "end": "2027-07-05", "destinations": "Vienna"}})
    assert (p, trip) not in trip_edges()


def test_plan_saved_after_photos_links_them(client):
    p = photo(client)
    assert not trip_edges()
    trip = plan(client, "Late plan", start="2027-05-13", end="2027-05-15", destinations="vienna")
    assert (p, trip) in trip_edges()


def test_move_into_planned_links_photos(client):
    p = photo(client)
    client.post("/kb/entries", json={"folder": "Fun/Travel", "title": "Loose trip", "content": "x",
                                     "fields": {"start": "2027-05-13", "end": "2027-05-15"}})
    assert not trip_edges()
    res = client.post("/travel/planned/move", json={"folder": "Fun/Travel", "slug": "loose-trip"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert (p, f"note:{out['folder']}/{out['slug']}") in trip_edges()


def test_backfill_dry_and_apply(client):
    p = photo(client)
    trip = plan(client, "Central Europe", start="2027-05-10", end="2027-05-20")
    gs = get_graph_store()
    for e in gs.all():
        if e["kind"] == KIND:
            gs.remove_edge(e["id"])
    dry = client.post("/travel/planned/backfill-photos").json()
    assert dry["dry_run"] is True and dry["created"] == 1
    assert not trip_edges()
    applied = client.post("/travel/planned/backfill-photos?dry_run=false").json()
    assert applied["created"] == 1
    assert (p, trip) in trip_edges()
    again = client.post("/travel/planned/backfill-photos?dry_run=false").json()
    assert again["created"] == 0 and again["removed"] == 0


def test_api_photo_count_and_thumbs(client):
    plan(client, "Central Europe", start="2027-05-10", end="2027-05-20", destinations="Austria")
    for i in range(7):
        photo(client, title=f"Shot {i}")
    rows = client.get("/travel/planned").json()
    row = next(r for r in rows if r["title"] == "Central Europe")
    assert row["photo_count"] == 7
    assert len(row["photos"]) == 6
    assert all(ph["asset"].startswith("assets/") and ph["folder"] and ph["slug"] for ph in row["photos"])
    assert row["start"] == "2027-05-10" and row["destinations"] == "Austria"  # existing fields unchanged
