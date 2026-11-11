"""WARDROBE / GROOMING / HOME drops — inputs, registry seeds and the RIGHT
answers, written once and run by BOTH live suites (tests/claude/local with
qwen, tests/claude/subscription_or_api with Claude via Max). Each suite's
test module binds `client` + `provider`.

Expectations are fixed from product intent up front; a failure is a finding
about the model/code, never a reason to re-fit the expectation.

Prefixes are the REAL ones from nodes/drop_router.PREFIX_TYPES:
  wardrobe:/item: -> wardrobe_item
  product:        -> grooming_item   ("grooming:" is the ROUTINE composer,
                                      grooming_routine_composition)
  home:           -> home_item
"""
from __future__ import annotations

import io
import re

import pytest

from tests.claude.harness import drop, first, types

# --- registry seeds (CLAUDE.md: model-quality tests run on preset-seeded data)

WARDROBE_SEED = [
    ("Black Bomber Jacket", "jacket", "Black nylon bomber jacket with ribbed cuffs."),
    ("Uniqlo Navy Chinos", "pants", "Navy slim-fit cotton chinos from Uniqlo."),
]
GROOMING_SEED = [
    ("CeraVe Foaming Cleanser", "skincare", "Foaming facial cleanser for normal to oily skin."),
    ("Head & Shoulders Classic Clean", "haircare", "Anti-dandruff shampoo."),
]
RESIDENCE_SEED = {"name": "Iris 307", "city": "Arlington", "address": "", "moved_in": "2024-08-01", "notes": ""}


def seed(c):
    """Seed wardrobe/grooming/home registries once per client, so name
    resolution and residence fallback are judged against a real library
    (an empty registry would let the model freelance)."""
    if getattr(c, "_lifestyle_seeded", False):
        return
    for name, cat, desc in WARDROBE_SEED:
        r = c.post("/wardrobe/items", data={"name": name, "category": cat, "description": desc})
        assert r.status_code == 200, r.text
    for name, cat, desc in GROOMING_SEED:
        r = c.post("/grooming/items", data={"name": name, "category": cat, "description": desc})
        assert r.status_code == 200, r.text
    r = c.post("/home/residences", json=RESIDENCE_SEED)
    assert r.status_code == 200, r.text
    c._lifestyle_seeded = True


# --- inputs

WARDROBE_TEXT = "wardrobe: navy wool overcoat from Uniqlo, size M"
GROOMING_TEXT = "product: CeraVe hydrating cleanser, use AM and PM"
HOME_TEXT = "home: Dyson V15 vacuum, bought 2025, warranty 2 years"

OUTFIT_SKIP = "needs a real outfit photo — covered in tests/user"


def tshirt_png() -> bytes:
    """A single red crew-neck t-shirt laid flat on a plain light background
    (a product-shot stand-in: no person, no text, no other objects)."""
    from PIL import Image, ImageDraw, ImageFilter

    w = h = 768
    img = Image.new("RGB", (w, h), (244, 244, 242))
    body = [(250, 150), (330, 128), (355, 160), (384, 170), (413, 160), (438, 128), (518, 150),
            (640, 250), (585, 320), (530, 280), (530, 640), (238, 640), (238, 280), (183, 320), (128, 250)]
    shadow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shadow).polygon([(x + 10, y + 14) for x, y in body], fill=90)
    img.paste((180, 180, 178), mask=shadow.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(img)
    d.polygon(body, fill=(196, 38, 46), outline=(140, 24, 30))
    d.arc((330, 100, 438, 200), 20, 160, fill=(150, 26, 32), width=10)  # ribbed collar
    d.line([(238, 625), (530, 625)], fill=(150, 26, 32), width=6)  # bottom hem
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _blob(e: dict, *keys: str) -> str:
    return " ".join(str(e.get(k) or "") for k in keys).lower()


def _no_person(r: dict):
    """None of these drops mention a person; an additive person_entry would be invented."""
    assert "person_entry" not in types(r), types(r)


# --- checks


def check_wardrobe_text(c, provider):
    """'wardrobe:' fixes the type; the model must describe a navy wool Uniqlo
    overcoat as outerwear, keep the stated size, and not collapse it into the
    seeded 'Uniqlo Navy Chinos' (a different garment)."""
    r = drop(c, text=WARDROBE_TEXT, provider=provider)
    e = first(r, "wardrobe_item")
    name = (e.get("suggested_name") or "").lower()
    # An overcoat is outerwear: the closest of the offered categories is jacket.
    assert (e.get("category") or "").lower() in {"jacket", "coat", "outerwear"}, e
    # The name must say what the item is.
    assert re.search(r"\b(over)?coat\b", name), e
    # Colour + material are the details a wardrobe description exists to record.
    blob = _blob(e, "suggested_name", "description")
    assert "navy" in blob and "wool" in blob, e
    # The brand the owner typed is a fact about the item; dropping it loses data.
    assert "uniqlo" in blob, e
    # Size is the one fit fact typed; with no size field it must survive in the description.
    assert re.search(r"\bsize\s*m\b|\bmedium\b|\bsize:?\s*\(?m\)?", blob), e
    # A coat is not the seeded chinos — canonicalize_name must not merge them.
    assert e.get("suggested_name") not in {n for n, _, _ in WARDROBE_SEED}, e
    _no_person(r)


def check_grooming_text(c, provider):
    """'product:' fixes grooming_item; a CeraVe hydrating cleanser is skincare,
    keeps its brand/product identity, and is NOT the seeded CeraVe FOAMING
    cleanser (a different product)."""
    r = drop(c, text=GROOMING_TEXT, provider=provider)
    assert "grooming_routine_composition" not in types(r), types(r)  # one product, not a routine
    e = first(r, "grooming_item")
    name = (e.get("suggested_name") or "").lower()
    # A facial cleanser is skincare in the offered category list.
    assert (e.get("category") or "").lower() == "skincare", e
    # Brand + product type identify the bottle.
    assert "cerave" in name and "cleanser" in name, e
    # "hydrating" is what distinguishes it from the other CeraVe cleanser.
    assert "hydrat" in _blob(e, "suggested_name", "description"), e
    # Usage timing the owner typed belongs in the description, not discarded.
    assert re.search(r"\bam\b.*\bpm\b|morning.*(night|evening)|twice (a |per )?day|daily", _blob(e, "description")), e
    # Different product from the seed: must not be merged into "CeraVe Foaming Cleanser".
    assert e.get("suggested_name") != "CeraVe Foaming Cleanser", e
    _no_person(r)


def check_home_text(c, provider):
    """'home:' fixes home_item; a Dyson vacuum is an appliance, the warranty
    must be kept, nothing unstated (price, a specific purchase day) may be
    invented, and with no home named it files under the current residence."""
    r = drop(c, text=HOME_TEXT, provider=provider)
    e = first(r, "home_item")
    # The product identity.
    assert "dyson" in (e.get("suggested_name") or "").lower(), e
    assert re.search(r"v\s?15", (e.get("suggested_name") or "").lower()), e
    # A vacuum cleaner is an appliance (electronics/cleaning are the only defensible alternates).
    assert (e.get("category") or "").lower() in {"appliance", "appliances", "electronics", "cleaning"}, e
    # No price was stated: a number here is invented.
    assert e.get("purchase_price") in (None, 0, 0.0), e
    # Only the year was stated: if a date is set it must be in 2025.
    pd = e.get("purchase_date")
    assert pd is None or str(pd).startswith("2025"), e
    # The warranty is the reason to log an appliance; no field exists, so notes must carry it.
    assert re.search(r"warrant", _blob(e, "notes", "suggested_name")) and re.search(r"\b2\b|two", _blob(e, "notes")), e
    # No location was stated.
    assert not (e.get("location") or "").strip(), e
    # No residence named -> deterministic fallback to the current home (the seeded one).
    assert e.get("residence_name") == RESIDENCE_SEED["name"], e
    _no_person(r)


def check_outfit_photo(c, provider):
    """Known owner bug: a PERSON wearing a full outfit sorted as one
    wardrobe_item; the right answer is outfit_photo. No CC0 photo of a person
    in everyday clothes exists on this machine (the only CC0 person image,
    plasma's Apollo 11 astronaut, is a spacesuit on the moon — not an outfit,
    so it would test the wrong thing)."""
    pytest.skip(OUTFIT_SKIP)


def check_tshirt_photo(c, provider):
    """An unprefixed photo of ONE garment alone on a plain background is a
    single wardrobe item (outfit_item -> wardrobe_item), never a worn outfit,
    a meal or a generic note, and a t-shirt's category is shirt."""
    r = drop(c, data=tshirt_png(), filename="tshirt.png", provider=provider)
    assert not r.get("local_unavailable"), r.get("local_unavailable")
    t = types(r)
    # One garment, no person: not an outfit photo, not a KB note.
    assert "outfit_photo" not in t and "kb_entry" not in t, t
    e = first(r, "wardrobe_item")
    # A t-shirt is a shirt in the offered category list.
    assert (e.get("category") or "").lower() in {"shirt", "t-shirt", "tshirt", "top"}, e
    # The garment is plainly red; the description should say so.
    assert "red" in _blob(e, "suggested_name", "description"), e
    # A new t-shirt is not the seeded bomber jacket or chinos.
    assert e.get("suggested_name") not in {n for n, _, _ in WARDROBE_SEED}, e
    return r


ALL = [check_wardrobe_text, check_grooming_text, check_home_text, check_outfit_photo, check_tshirt_photo]
IMAGE_CHECKS = {check_outfit_photo, check_tshirt_photo}
