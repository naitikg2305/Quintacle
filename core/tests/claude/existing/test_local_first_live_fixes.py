"""2026-11-11 fixes for local-first violations the live suites exposed.
Every model is FAKED — never a real Ollama/Claude call, never the network.

1. Wardrobe/grooming TEXT drops (and the outfit/routine composers) go through
   llm_dispatch.parse_structured with the drop's provider — local by default,
   cloud only on provider=cloud.
2. Item-library name matching (canonicalize_item_name) no longer merges
   products that differ in a distinguishing word ("CeraVe Hydrating
   Cleanser" vs the seeded "CeraVe Foaming Cleanser"); exercise
   canonicalization keeps its looser drift correction.
3. GPS photos geocode local-first: the offline GeoNames gazetteer
   (geo_offline.py), coordinates-only when it has no answer in local mode,
   and the drop never makes a cloud call in local mode."""
from __future__ import annotations

import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import quintacle_core.api as api_module
from quintacle_core import geo_offline, llm_dispatch
from quintacle_core.nodes.grooming import llm as grooming_llm
from quintacle_core.nodes.journal.normalize import canonicalize_item_name, canonicalize_name, same_item_name
from quintacle_core.nodes.kb import photo_organizer, photo_place
from quintacle_core.nodes.kb.llm import KBSuggestion
from quintacle_core.nodes.wardrobe import llm as wardrobe_llm
from quintacle_core.perception import image_policy

EIFFEL = (48.858333, 2.294444)


def _no_cloud(*a, **k):
    raise AssertionError("cloud call in local mode")


@pytest.fixture
def local_parses(monkeypatch):
    """Fake the LOCAL structured parse; any cloud parse fails the test."""
    calls: list[str] = []
    answers: dict[str, object] = {}

    def fake_local(system, user_content, output_format, max_tokens):
        calls.append(output_format.__name__)
        return answers[output_format.__name__]

    monkeypatch.setattr(llm_dispatch, "_parse_local", fake_local)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _no_cloud)
    return answers, calls


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("QUINTACLE_DATA_DIR", str(tmp_path))
    image_policy.set_request_provider(None)
    return TestClient(api_module.create_app())


# ------------------------------------------------- 1. text drops are local


def test_wardrobe_text_parse_is_local_by_default(local_parses):
    answers, calls = local_parses
    answers["WardrobeItemEstimate"] = wardrobe_llm.WardrobeItemEstimate(
        suggested_name="Black Bomber Jacket", category="jacket", description="black leather bomber"
    )
    out = wardrobe_llm.describe_wardrobe_item_from_text("black leather bomber jacket", provider="local")
    assert out.suggested_name == "Black Bomber Jacket" and calls == ["WardrobeItemEstimate"]


def test_grooming_text_parse_cloud_only_when_chosen(monkeypatch):
    seen = []

    def fake_cloud(system, user_content, output_format, max_tokens):
        seen.append("cloud")
        return output_format(suggested_name="X", category="skincare", description="d")

    monkeypatch.setattr(llm_dispatch, "_parse_local", lambda *a, **k: (_ for _ in ()).throw(AssertionError("local on cloud")))
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", fake_cloud)
    grooming_llm.describe_grooming_item_from_text("some cleanser", provider="cloud")
    assert seen == ["cloud"]


def test_text_drops_thread_provider_and_never_reach_cloud(client, local_parses, monkeypatch):
    answers, calls = local_parses
    monkeypatch.setattr(wardrobe_llm, "cloud_client", _no_cloud)
    monkeypatch.setattr(grooming_llm, "cloud_client", _no_cloud)
    monkeypatch.setattr(api_module, "maybe_structure_experience", lambda *a, **k: None)
    monkeypatch.setattr(api_module, "maybe_structure_person_mention", lambda *a, **k: None)
    answers["WardrobeItemEstimate"] = wardrobe_llm.WardrobeItemEstimate(suggested_name="Navy Chinos", category="pants", description="d")
    answers["GroomingItemEstimate"] = grooming_llm.GroomingItemEstimate(
        suggested_name="CeraVe Hydrating Cleanser", category="skincare", description="d"
    )
    answers["OutfitSuggestion"] = wardrobe_llm.OutfitSuggestion(outfit_name="Fit", items=[])
    answers["GroomingRoutineSuggestion"] = grooming_llm.GroomingRoutineSuggestion(routine_name="AM Routine", steps=[])

    for text, kind in [
        ("item: navy chinos", "wardrobe_item"),
        ("product: cerave hydrating cleanser", "grooming_item"),
    ]:
        r = client.post("/drop", data={"text": text, "provider": "local"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["entries"][0]["type"] == kind and body["provider_used"] == "local"
    assert calls == ["WardrobeItemEstimate", "GroomingItemEstimate"]

    # The composers' endpoints are local-first too.
    assert client.post("/wardrobe/outfits/suggest", json={"description": "chill fit"}).status_code == 200
    assert client.post("/grooming/routines/suggest", json={"description": "am", "provider": "local"}).status_code == 200
    assert calls[-2:] == ["OutfitSuggestion", "GroomingRoutineSuggestion"]


def test_grooming_text_drop_keeps_a_different_product_separate(client, local_parses, monkeypatch):
    answers, _ = local_parses
    monkeypatch.setattr(api_module, "maybe_structure_experience", lambda *a, **k: None)
    monkeypatch.setattr(api_module, "maybe_structure_person_mention", lambda *a, **k: None)
    created = client.post("/grooming/items", data={"name": "CeraVe Foaming Cleanser", "category": "skincare"})
    assert created.status_code == 200, created.text
    answers["GroomingItemEstimate"] = grooming_llm.GroomingItemEstimate(
        suggested_name="CeraVe Hydrating Cleanser", category="skincare", description="cream cleanser"
    )
    r = client.post("/drop", data={"text": "product: CeraVe hydrating cleanser", "provider": "local"})
    assert r.json()["entries"][0]["suggested_name"] == "CeraVe Hydrating Cleanser"
    # Saving it creates a second product instead of overwriting the first.
    client.post("/grooming/items", data={"name": "CeraVe Hydrating Cleanser", "category": "skincare"})
    names = sorted(i["name"] for i in client.get("/grooming/items").json())
    assert names == ["CeraVe Foaming Cleanser", "CeraVe Hydrating Cleanser"]


# ------------------------------------------------- 2. stricter item matching


@pytest.mark.parametrize(
    "name, expected",
    [
        ("CeraVe Hydrating Cleanser", "CeraVe Hydrating Cleanser"),  # different product — kept
        ("cerave foaming cleanser", "CeraVe Foaming Cleanser"),
        ("CeraVe Foaming Cleansers", "CeraVe Foaming Cleanser"),  # plural
        ("Cerave Foamng Cleanser", "CeraVe Foaming Cleanser"),  # typo
        ("RayBan Aviators", "Ray-Ban Aviators"),  # spacing/hyphen
        ("Sunscreen SPF 50", "Sunscreen SPF 50"),  # a number is distinguishing
        ("Blue Bomber Jacket", "Blue Bomber Jacket"),
        ("PM Routine", "PM Routine"),
    ],
)
def test_canonicalize_item_name(name, expected):
    known = ["CeraVe Foaming Cleanser", "Ray-Ban Aviators", "Sunscreen SPF 30", "Black Bomber Jacket", "AM Routine"]
    assert canonicalize_item_name(name, known) == expected


def test_item_resolvers_use_the_strict_match():
    known = [{"name": "CeraVe Foaming Cleanser", "category": "skincare"}]
    suggestion = grooming_llm.GroomingRoutineSuggestion(
        routine_name="PM",
        steps=[grooming_llm.GroomingRoutineComponent(name="CeraVe Hydrating Cleanser", category="skincare")],
    )
    assert grooming_llm.resolve_grooming_routine(suggestion, known)["steps"][0]["is_new"] is True
    outfit = wardrobe_llm.OutfitSuggestion(outfit_name="x", items=[wardrobe_llm.OutfitComponent(name="Blue Bomber Jacket", category="jacket")])
    assert wardrobe_llm.resolve_outfit(outfit, [{"name": "Black Bomber Jacket", "category": "jacket"}])["items"][0]["is_new"] is True


def test_exercise_canonicalization_unchanged():
    assert canonicalize_name("Pull Ups", ["Pullups"]) == "Pullups"
    assert canonicalize_name("pull-ups", ["Pull Ups"]) == "Pull Ups"
    assert not same_item_name("", "x")


# ------------------------------------------------- 3. offline geocoding


@pytest.fixture
def gazetteer(tmp_path, monkeypatch):
    """A tiny GeoNames-format dataset built through the real build_* path."""
    raw = tmp_path / "raw.txt"

    def row(gid, name, lat, lon, code, cc, admin1, pop):
        cols = [str(gid), name, name, "", str(lat), str(lon), "P", code, cc, "", admin1, "", "", "", str(pop)] + [""] * 4
        return "\t".join(cols) + "\n"

    raw.write_text(
        row(1, "Paris", 48.85341, 2.3488, "PPLC", "FR", "11", 2138551)
        + row(2, "Paris 16 Passy", 48.8637, 2.2769, "PPLX", "FR", "11", 159386)  # a city section — skipped
        + row(3, "Issy-les-Moulineaux", 48.82104, 2.27718, "PPL", "FR", "11", 68000)
        + row(4, "Vienna", 48.20849, 16.37208, "PPLC", "AT", "09", 1691468),
        encoding="utf-8",
    )
    folder = tmp_path / "geonames"
    folder.mkdir()
    with open(raw, encoding="utf-8") as fh:
        assert geo_offline.build_cities_tsv(fh, folder / geo_offline.CITIES_FILE) == 3
    geo_offline.build_admin1_tsv("FR.11\tÎle-de-France\tIle-de-France\t3012874\nAT.09\tVienna\tVienna\t2761367\n", folder / geo_offline.ADMIN1_FILE)
    info = "#ISO\tISO3\tnum\tfips\tCountry\tCapital\tArea\tPop\tContinent\n"
    info += "FR\tFRA\t250\tFR\tFrance\tParis\t0\t0\tEU\nAT\tAUT\t40\tAU\tAustria\tVienna\t0\t0\tEU\n"
    geo_offline.build_countries_tsv(info, folder / geo_offline.COUNTRIES_FILE)
    monkeypatch.setenv(geo_offline.GEONAMES_DIR_ENV, str(folder))
    geo_offline.clear_cache()
    yield folder
    geo_offline.clear_cache()


def test_offline_reverse_prefers_the_city_the_photo_is_in(gazetteer):
    assert geo_offline.available()
    got = geo_offline.reverse(*EIFFEL)
    assert got == {"city": "Paris", "state": "Île-de-France", "country": "France", "continent": "Europe"}
    assert geo_offline.reverse(0.5, -30.0) is None  # mid-ocean: nothing within MAX_KM
    assert geo_offline.reverse(float("nan"), 2.0) is None


def test_offline_reverse_without_data_is_none(monkeypatch, tmp_path):
    monkeypatch.setenv(geo_offline.GEONAMES_DIR_ENV, str(tmp_path / "missing"))
    geo_offline.clear_cache()
    assert not geo_offline.available() and geo_offline.reverse(*EIFFEL) is None


def test_geocode_local_mode_uses_gazetteer_never_cloud(gazetteer, monkeypatch):
    monkeypatch.setattr(photo_organizer, "_geocode_cloud", _no_cloud)
    monkeypatch.delenv(image_policy.IMAGE_PROVIDER_ENV, raising=False)
    image_policy.set_request_provider(None)
    geo = photo_organizer.geocode(*EIFFEL)
    assert (geo.city, geo.state, geo.country) == ("Paris", "Île-de-France", "France")


def test_geocode_local_mode_without_data_refuses_without_cloud(monkeypatch):
    monkeypatch.setattr(photo_organizer, "_geocode_cloud", _no_cloud)
    image_policy.set_request_provider("local")
    try:
        with pytest.raises(photo_organizer.GeocodeUnavailable):
            photo_organizer.geocode(*EIFFEL)
        # Never fails the caller: the folder falls back to the month, the cache helper to None.
        assert photo_organizer.compute_photo_folder(date(2026, 6, 14), {"lat": EIFFEL[0], "lon": EIFFEL[1]}, None, ["United States"]) == "Media/Photos/2026/June"
        assert photo_place.cached_geocode(*EIFFEL, None) is None
    finally:
        image_policy.set_request_provider(None)


def test_geocode_auto_and_cloud_modes(monkeypatch, gazetteer):
    cloud = photo_organizer.GeocodedLocation(country="France", state="Paris", city="7th arrondissement")
    calls = []

    def fake_cloud(lat, lon):
        calls.append((lat, lon))
        return cloud

    monkeypatch.setattr(photo_organizer, "_geocode_cloud", fake_cloud)
    try:
        image_policy.set_request_provider("auto")
        assert photo_organizer.geocode(*EIFFEL).city == "Paris" and calls == []  # offline answered
        image_policy.set_request_provider("cloud")
        assert photo_organizer.geocode(*EIFFEL) is cloud and len(calls) == 1  # the user chose cloud
        monkeypatch.setattr(photo_organizer, "_geocode_cloud", lambda *a: (_ for _ in ()).throw(RuntimeError("down")))
        assert photo_organizer.geocode(*EIFFEL).city == "Paris"  # cloud down: offline still answers
    finally:
        image_policy.set_request_provider(None)


def test_geocode_auto_without_data_falls_back_to_cloud(monkeypatch):
    monkeypatch.setattr(photo_organizer, "_geocode_cloud", lambda lat, lon: photo_organizer.GeocodedLocation(country="France", state="IDF", city="Paris"))
    image_policy.set_request_provider("auto")
    try:
        assert photo_organizer.geocode(*EIFFEL).city == "Paris"
    finally:
        image_policy.set_request_provider(None)


def test_private_place_uses_gazetteer_only(gazetteer, monkeypatch):
    monkeypatch.setattr(photo_organizer, "geocode", _no_cloud)
    got = photo_place.cached_geocode(*EIFFEL, None, allow_cloud=False)
    assert got == {"city": "Paris", "state": "Île-de-France", "country": "France"}


def _dms(v: float):
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    return (float(d), float(m), round(((v - d) * 60 - m) * 60, 4))


def _gps_jpeg() -> bytes:
    img = Image.new("RGB", (8, 8), "skyblue")
    exif = Image.Exif()
    exif[306] = "2026:06:14 15:32:10"
    exif.get_ifd(0x8769)[36867] = "2026:06:14 15:32:10"
    exif[0x8825] = {1: "N", 2: _dms(EIFFEL[0]), 3: "E", 4: _dms(EIFFEL[1])}
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _stub_photo_drop(monkeypatch):
    monkeypatch.setattr(api_module, "describe_drop", lambda *a, **k: "a sunny park with a tree")
    monkeypatch.setattr(
        api_module, "suggest_kb_entry", lambda *a, **k: KBSuggestion(folder="Media/Photos", title="Park", content="a sunny park", links=[])
    )
    monkeypatch.setattr(api_module, "maybe_structure_experience", lambda *a, **k: None)
    monkeypatch.setattr(api_module, "maybe_structure_person_mention", lambda *a, **k: None)
    monkeypatch.setattr(photo_organizer, "_geocode_cloud", _no_cloud)
    monkeypatch.setattr(photo_organizer, "cloud_client", _no_cloud)


def _drop_and_save(client):
    jpg = _gps_jpeg()
    r = client.post("/drop", data={"text": "note: park", "provider": "local"}, files={"file": ("IMG_1.jpg", jpg, "image/jpeg")})
    assert r.status_code == 200, r.text
    e = next(x for x in r.json()["entries"] if x["type"] == "kb_entry")
    saved = client.post(
        "/kb/entries/with-asset",
        data={"folder": e["folder"], "title": e["title"], "content": e["content"], "links": ""},
        files={"files": ("IMG_1.jpg", jpg, "image/jpeg")},
    )
    assert saved.status_code == 200, saved.text
    s = saved.json()
    note = client.get("/kb/entry", params={"folder": s["folder"], "slug": s["slug"]}).json()["content"]
    return e, [l for l in note.splitlines() if l.strip().startswith("📍")]


def test_local_gps_drop_without_gazetteer_is_coords_only_and_never_cloud(client, monkeypatch):
    _stub_photo_drop(monkeypatch)
    e, lines = _drop_and_save(client)
    assert e["folder"] == "Media/Photos/2026/June"
    assert len(lines) == 1 and "48.8583, 2.2944" in lines[0] and "taken 2026-06-14 15:32" in lines[0]
    assert "Paris" not in lines[0]


def test_local_gps_drop_with_gazetteer_names_the_place(client, monkeypatch, gazetteer):
    _stub_photo_drop(monkeypatch)
    e, lines = _drop_and_save(client)
    assert e["folder"] == "Media/Photos/2026/June/France/Île-de-France/Paris"
    assert len(lines) == 1 and "Paris" in lines[0] and "France" in lines[0] and "Europe" in lines[0]
