"""PEOPLE + PHOTO-PERCEPTION + FOOD-PHOTO + IMAGE-KIND checks, written once
and run by BOTH live suites (each suite's test module binds `client` +
`provider`). Closes coverage rows #6, #41, #33 and the partial #30 in
docs/testing/model-coverage-2026-11-11.md.

Images: real CC0 photos that ship with plasma-workspace
(/usr/share/plasma/avatars/photos/*.png; each has a .license file saying
CC0-1.0, sourced from Pexels) are used where a drawing can't be recognised
(a cat, a car, a stack of pancakes, sushi). Text pages are rendered with
PIL. Nothing is downloaded. A check whose image isn't on this machine skips
with the reason.

Expectations are fixed from product intent up front; a failure is a
finding about the model or the code, never a reason to re-fit the
expectation. Every check returns a dict carrying `pipeline` (the /drop
response, or the image-policy summary for a direct call) so the suites can
add mode assertions; PHOTO_CHECKS lists the ones that read an image (Max:
pipeline must be "cloud")."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.claude.harness import drop, first, folder_of, types
from tests.claude.photos_cases import _render, gps_photo_jpg

CC0 = Path("/usr/share/plasma/avatars/photos")

# ------------------------------------------------------------------ people

# The people registry has no alias field (PersonCreate: name, category,
# how_met, met_date, notes, links), so "Arjun" can't be stored as an alias.
# A first-name mention of a tracked person must still link to them — the
# mention prompt itself says "a nickname or first-name-only is fine".
PERSON = {"name": "Arjun Mehta", "category": "friend", "how_met": "college roommate at UVA",
          "notes": "Lives in Arlington. Into climbing and fintech."}

KNOWN_FULL = "dinner with Arjun Mehta at Compass, he told me his startup just closed its seed round"
KNOWN_FIRST = "coffee with Arjun at Compass, talked about his startup"
NEW_PERSON = "met a new guy named Theo Park at the climbing gym"
JOURNAL_DATE = "2026-11-10"
JOURNAL_KNOWN = "Long day. Dinner with Arjun Mehta after work, he's moving to Austin next month to grow the startup."


def _seed_person(c) -> None:
    """Idempotent: the session client is shared, so seed only once."""
    r = c.get("/people")
    assert r.status_code == 200, r.text[:300]
    if not any(p.get("name") == PERSON["name"] for p in r.json()):
        r = c.post("/people", json=PERSON)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["name"] == PERSON["name"], r.json()


def _mentions(r: dict, who: str) -> list[dict]:
    """kb_entry proposals filed under a tracked person's People/<Name>/Mentions folder."""
    return [e for e in r.get("entries", []) if e.get("type") == "kb_entry"
            and folder_of(e).startswith("people/") and folder_of(e).endswith("/mentions") and who in folder_of(e)]


def _new_people(r: dict, who: str) -> list[dict]:
    return [e for e in r.get("entries", []) if e.get("type") == "person_entry"
            and who in (e.get("suggested_name") or "").lower()]


def _assert_links_arjun(r: dict) -> None:
    m = _mentions(r, "arjun mehta")
    assert m, f"no People/Arjun Mehta/Mentions proposal; got {types(r)}: {r.get('entries')}"
    assert not _new_people(r, "arjun"), f"a tracked person was proposed as NEW: {_new_people(r, 'arjun')}"
    content = (m[0].get("content") or "").lower()
    assert any(w in content for w in ("startup", "start-up", "company")), f"mention note lost the fact: {m[0].get('content')!r}"


def check_person_known_full_name(c, provider):
    """A drop naming a tracked person in full with a real update links to THEIR Mentions folder and proposes no new person."""
    _seed_person(c)
    r = drop(c, text=KNOWN_FULL, provider=provider)
    _assert_links_arjun(r)
    return r


def check_person_known_first_name(c, provider):
    """'coffee with Arjun …' is the tracked Arjun Mehta (first name only): it links to his Mentions folder, never a new 'Arjun'."""
    _seed_person(c)
    r = drop(c, text=KNOWN_FIRST, provider=provider)
    _assert_links_arjun(r)
    return r


def check_person_new(c, provider):
    """'met a new guy named Theo Park at the climbing gym' proposes a NEW person_entry for Theo Park (how_met: the climbing gym), not a mention of anyone tracked."""
    _seed_person(c)
    r = drop(c, text=NEW_PERSON, provider=provider)
    theo = _new_people(r, "theo")
    assert theo, f"no new person proposed; got {types(r)}: {r.get('entries')}"
    e = theo[0]
    assert "park" in (e.get("suggested_name") or "").lower(), f"suggested_name={e.get('suggested_name')!r} want Theo Park"
    assert "climb" in (e.get("how_met") or "").lower(), f"how_met={e.get('how_met')!r} should name the climbing gym"
    assert not _mentions(r, "arjun"), "Theo was filed as a mention of the tracked Arjun"
    return r


def check_person_known_journal(c, provider):
    """The Journal page's parse runs the same detection: a life update about tracked Arjun Mehta becomes a Mentions note dated that day."""
    _seed_person(c)
    resp = c.post(f"/journal/{JOURNAL_DATE}/parse", params={"provider": provider},
                  content=JOURNAL_KNOWN.encode(), headers={"Content-Type": "text/plain"})
    assert resp.status_code == 200, f"/journal/parse {resp.status_code}: {resp.text[:400]}"
    r = resp.json()
    m = _mentions(r, "arjun mehta")
    assert m, f"no Mentions proposal from the journal parse; got {types(r)}: {r.get('entries')}"
    assert JOURNAL_DATE in (m[0].get("title") or ""), f"mention title should carry the journal date: {m[0].get('title')!r}"
    assert "austin" in (m[0].get("content") or "").lower(), f"mention note lost the fact: {m[0].get('content')!r}"
    assert not _new_people(r, "arjun"), _new_people(r, "arjun")
    return r


# ------------------------------------------------------------------ perception (#41)

_PHOTO_BEARING = {"kb_entry", "document_entry", "wardrobe_item", "grooming_item", "home_item", "outfit_photo"}


def _cc0(name: str) -> Path:
    p = CC0 / name
    if not p.exists():
        pytest.skip(f"CC0 photo {p} isn't on this machine (ships with plasma-workspace)")
    return p


def _need_perception() -> None:
    from quintacle_core.perception import perception_available

    if not perception_available():
        pytest.skip("perception deps not installed (pip install -r core/perception-requirements.txt)")


def _perception(r: dict) -> dict:
    """The perception payload the drop attached to its photo-bearing proposal."""
    bearing = [e for e in r.get("entries", []) if e.get("type") in _PHOTO_BEARING]
    assert bearing, f"no photo-bearing proposal to carry perception; got {types(r)}"
    p = bearing[0].get("perception")
    assert p is not None, f"photo drop has no perception field: {bearing[0]}"
    assert set(p) >= {"tags", "scene", "faces"}, p
    return p


def check_perception_cat_photo(c, provider):
    """A real photo of a cat: YOLO tags it 'cat', no human face is found, no EXIF means daylight is unknown (None), and it files as a plain note."""
    _need_perception()
    r = drop(c, path=_cc0("Cat.png"), filename="cat.png", provider=provider)
    p = _perception(r)
    assert "cat" in p["tags"], f"tags={p['tags']}"
    assert p["faces"] == [], f"a cat is not a human face: {p['faces']}"
    assert p["scene"].get("daylight") is None, f"no EXIF timestamp -> daylight must be None, got {p['scene']}"
    assert 0.0 <= float(p["scene"]["brightness"]) <= 1.0, p["scene"]
    # Routing: a pet photo is generic -> kb_entry (not food, receipt, paperwork or clothing).
    first(r, "kb_entry")
    assert not {"ingredient_preset", "finance", "document_entry", "wardrobe_item"} & set(types(r)), types(r)
    return r


def check_perception_car_photo(c, provider):
    """A real photo of a white sports car on a street: YOLO tags it 'car'."""
    _need_perception()
    r = drop(c, path=_cc0("Car.png"), filename="car.png", provider=provider)
    p = _perception(r)
    assert "car" in p["tags"], f"tags={p['tags']}"
    assert not {"ingredient_preset", "finance", "document_entry"} & set(types(r)), types(r)
    return r


def check_perception_scene_exif(c, provider):
    """A camera JPEG shot at 15:32 (EXIF) under a clear blue sky: scene says daylight=True and outdoor_hint=True, and no face is found."""
    _need_perception()
    r = drop(c, data=gps_photo_jpg(), filename="IMG_20260614_153211.jpg", provider=provider)
    p = _perception(r)
    assert p["scene"].get("daylight") is True, f"EXIF 15:32 is daylight: {p['scene']}"
    assert p["scene"].get("outdoor_hint") is True, f"top quarter is blue sky: {p['scene']}"
    assert p["faces"] == [], p["faces"]
    return r


def check_perception_face_match(c, provider):
    """Enroll a face, drop a second photo of the same person -> faces[0].match.person_name is that person."""
    pytest.skip("needs real faces — tests/user (no CC0 face photo on this machine; "
                "the only person among the plasma CC0 photos, Astronaut.png, wears a mirrored visor)")


# ------------------------------------------------------------------ food photo without a label (#33)

FOOD_PHOTO_ENV = "QUINTACLE_TEST_FOOD_PHOTO"        # path to the owner's own plated-food photo
FOOD_NAME_ENV = "QUINTACLE_TEST_FOOD_NAME"          # optional: a word the food name must contain
FOOD_COMMON_ENV = "QUINTACLE_TEST_FOOD_COMMON"      # optional: "1" when the food is common (USDA must match)
_GENERIC_FOOD_NAMES = {"", "food", "labeled food", "meal", "dish", "plate", "a plate of food"}


def _food_preset(r: dict) -> dict:
    assert not {"finance", "document_entry", "wardrobe_item"} & set(types(r)), types(r)
    e = first(r, "ingredient_preset")
    name = (e.get("suggested_name") or "").strip().lower()
    assert name not in _GENERIC_FOOD_NAMES, f"the food must be named, got {e.get('suggested_name')!r}"
    assert float(e.get("kcal") or 0) > 0, f"no calories for a plated food: {e}"
    assert e.get("source") != "label", f"there's no label in this photo, source={e.get('source')!r}"
    return e


def check_food_photo_pancakes(c, provider):
    """A real (CC0) photo of a stack of cooked pancakes, no label: an ingredient_preset named pancakes, USDA-matched to a cooked pancake (not a dry mix), weighed above the 100 g default."""
    r = drop(c, path=_cc0("Pancakes.png"), filename="pancakes.png", provider=provider)
    e = _food_preset(r)
    assert "pancake" in (e.get("suggested_name") or "").lower(), f"suggested_name={e.get('suggested_name')!r}"
    assert e.get("source") == "usda" and e.get("fdc_id") is not None, (
        f"pancakes are in USDA; want source=usda with an fdc_id, got source={e.get('source')!r} fdc_id={e.get('fdc_id')!r}")
    desc = (e.get("usda_description") or "").lower()
    assert "pancake" in desc, f"usda_description={e.get('usda_description')!r}"
    assert "dry mix" not in desc, f"cooked pancakes are not the dry mix: {e.get('usda_description')!r}"
    # Several pancakes are stacked on the plate; 100 g is the code's no-estimate default.
    assert float(e.get("basis_amount_g") or 0) > 100, f"basis_amount_g={e.get('basis_amount_g')} — the stack wasn't weighed"
    return r


def check_food_photo_env(c, provider):
    """The owner's own plain food photo ($QUINTACLE_TEST_FOOD_PHOTO): a named ingredient_preset with calories; USDA-matched when flagged common."""
    raw = os.environ.get(FOOD_PHOTO_ENV, "").strip()
    if not raw:
        pytest.skip(f"set {FOOD_PHOTO_ENV}=/path/to/plated_food.jpg (optional {FOOD_NAME_ENV}=<word>, {FOOD_COMMON_ENV}=1)")
    path = Path(raw).expanduser()
    if not path.exists():
        pytest.skip(f"{FOOD_PHOTO_ENV}={raw} doesn't exist")
    r = drop(c, path=path, provider=provider)
    e = _food_preset(r)
    want = os.environ.get(FOOD_NAME_ENV, "").strip().lower()
    if want:
        assert want in (e.get("suggested_name") or "").lower(), f"suggested_name={e.get('suggested_name')!r} want {want!r}"
    if os.environ.get(FOOD_COMMON_ENV, "").strip() == "1":
        assert e.get("source") == "usda" and e.get("fdc_id") is not None, (
            f"a common food must match USDA: source={e.get('source')!r} fdc_id={e.get('fdc_id')!r}")
    return r


# ------------------------------------------------------------------ image kind routing (#30)

LEASE = [
    "RESIDENTIAL LEASE AGREEMENT",
    "This Lease Agreement is made between Landlord: Harbor Point Properties LLC",
    "and Tenant: Jane Doe, for the residential premises described below.",
    "Premises: 2200 Wilson Blvd, Apt 714, Arlington, VA 22201",
    "Lease start date: 08/01/2026",
    "Lease end date: 07/31/2027",
    "Monthly rent: $2,150 due on the first day of each month",
    "Security deposit: $2,150, refundable per Virginia law",
    "Tenant shall not sublet the premises without the written consent of Landlord.",
    "Either party may end this agreement with 60 days written notice.",
    "Landlord signature: ____________________",
    "Tenant signature: ____________________",
]
LEASE_EXPIRES = "2027-07-31"


def lease_png() -> bytes:
    """A dense printed lease page (real pixels for OCR)."""
    return _render(LEASE, width=1400, size=26)


def _kind(c, data: bytes, mime: str, provider: str) -> dict:
    """classify_image_type -> entry_type_for_image_kind, called directly, with the image pipeline it recorded."""
    from quintacle_core.nodes.drop_router import classify_image_type, entry_type_for_image_kind
    from quintacle_core.perception import image_policy

    used = image_policy.collect_pipelines()
    kind = classify_image_type(data, mime, provider=provider)
    return {"kind": kind, "entry_type": entry_type_for_image_kind(kind), "pipeline": image_policy.summarize_pipeline(used)}


def check_kind_pancakes_prepared_meal(c, provider):
    """A photo of plated pancakes is kind prepared_meal, which routes to ingredient_preset."""
    out = _kind(c, _cc0("Pancakes.png").read_bytes(), "image/png", provider)
    assert out["kind"] == "prepared_meal", out
    assert out["entry_type"] == "ingredient_preset", out
    return out


def check_kind_sushi_prepared_meal(c, provider):
    """A photo of maki sushi is kind prepared_meal, which routes to ingredient_preset."""
    out = _kind(c, _cc0("Sushi.png").read_bytes(), "image/png", provider)
    assert out["kind"] == "prepared_meal", out
    assert out["entry_type"] == "ingredient_preset", out
    return out


def check_kind_lease_document(c, provider):
    """A dense printed lease page is kind document, which routes to document_entry."""
    out = _kind(c, lease_png(), "image/png", provider)
    assert out["kind"] == "document", out
    assert out["entry_type"] == "document_entry", out
    return out


def check_kind_cat_generic(c, provider):
    """A pet photo is none of the special kinds: generic, which routes to kb_entry."""
    out = _kind(c, _cc0("Cat.png").read_bytes(), "image/png", provider)
    assert out["kind"] == "generic", out
    assert out["entry_type"] == "kb_entry", out
    return out


def check_lease_photo_drop(c, provider):
    """Dropping the lease page proposes a document_entry typed lease that expires at the printed end date."""
    r = drop(c, data=lease_png(), filename="lease_page.png", provider=provider)
    assert not {"finance", "ingredient_preset"} & set(types(r)), types(r)
    e = first(r, "document_entry")
    assert "lease" in (e.get("doc_type") or "").strip().lower(), f"doc_type={e.get('doc_type')!r}"
    assert e.get("expiry_date") == LEASE_EXPIRES, f"expiry_date={e.get('expiry_date')!r} want {LEASE_EXPIRES}"
    return r


ALL = [
    check_person_known_full_name, check_person_known_first_name, check_person_new, check_person_known_journal,
    check_perception_cat_photo, check_perception_car_photo, check_perception_scene_exif, check_perception_face_match,
    check_food_photo_pancakes, check_food_photo_env,
    check_kind_pancakes_prepared_meal, check_kind_sushi_prepared_meal, check_kind_lease_document, check_kind_cat_generic,
    check_lease_photo_drop,
]

# Checks that read an image: in Max mode their pipeline must be "cloud".
PHOTO_CHECKS = {
    check_perception_cat_photo, check_perception_car_photo, check_perception_scene_exif,
    check_food_photo_pancakes, check_food_photo_env,
    check_kind_pancakes_prepared_meal, check_kind_sushi_prepared_meal, check_kind_lease_document, check_kind_cat_generic,
    check_lease_photo_drop,
}
