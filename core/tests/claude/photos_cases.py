"""PHOTO drops (POST /drop with an image), written once and run by BOTH live
suites (each suite's test module binds `client` + `provider`).

Every image is rendered here with PIL — never the owner's files. Every
number on an image is PRINTED, so the reading must match it exactly; only
free text (names, notes, titles) is matched loosely. Expectations are fixed
from product intent up front; a failure is a finding, never a reason to
re-fit the expectation.

Each check returns the /drop response so the suite can add mode-specific
assertions (local: pipeline is never "cloud"; Max: pipeline is "cloud")."""
from __future__ import annotations

import io
from pathlib import Path

from tests.claude.harness import drop, first, folder_of, label_png, types

FONT = "/usr/share/fonts/TTF/DejaVuSans.ttf"
MONO = "/usr/share/fonts/TTF/DejaVuSansMono.ttf"  # receipts/MRZ are printed monospaced


# ------------------------------------------------------------------ images


def _render(lines: list[str], *, width: int = 900, size: int = 30, bg: str = "white", font_path: str = FONT) -> bytes:
    """Plain black text on a flat background, one line per row (real pixels for OCR/vision)."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(font_path, size)
    step = int(size * 1.55)
    img = Image.new("RGB", (width, 70 + step * len(lines)), bg)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((40, 35 + step * i), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def receipt_png() -> bytes:
    return _render(RECEIPT, width=760, size=28, font_path=MONO if Path(MONO).exists() else FONT)


def passport_png() -> bytes:
    """A passport data page: pale card, a grey 'photo' box, the printed fields and an MRZ."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(FONT, 26)
    mono = ImageFont.truetype(MONO, 26) if Path(MONO).exists() else font
    img = Image.new("RGB", (1200, 760), (236, 240, 228))
    d = ImageDraw.Draw(img)
    d.rectangle((40, 120, 320, 480), fill=(170, 170, 170), outline="black")  # the holder's photo slot
    d.text((40, 40), PASSPORT[0], fill="black", font=font)
    for i, line in enumerate(PASSPORT[1:]):
        d.text((360, 120 + 52 * i), line, fill="black", font=font)
    for i, line in enumerate(PASSPORT_MRZ):
        d.text((40, 620 + 44 * i), line, fill="black", font=mono)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _dms(value: tuple[int, int, int]):
    from PIL.TiffImagePlugin import IFDRational

    return tuple(IFDRational(v, 1) for v in value)


def gps_photo_jpg() -> bytes:
    """A camera-style JPEG: a drawn outdoor scene (sky, sun, grass, a tree —
    no text, no food, no person) with EXIF DateTimeOriginal + GPS, exactly
    what a phone writes."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1024, 768), (135, 190, 235))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 500, 1024, 768), fill=(70, 150, 60))
    d.ellipse((800, 60, 920, 180), fill=(250, 220, 80))
    d.rectangle((230, 330, 270, 520), fill=(110, 70, 40))
    d.ellipse((150, 200, 350, 380), fill=(40, 120, 40))
    d.polygon([(560, 520), (640, 250), (720, 520)], fill=(120, 110, 100))  # a distant hill/tower shape

    exif = Image.Exif()
    exif[0x0110] = "Pixel 8"  # Model
    exif[0x0132] = GPS_TAKEN  # DateTime (base IFD)
    exif.get_ifd(0x8769)[36867] = GPS_TAKEN  # DateTimeOriginal
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = _dms(GPS_LAT_DMS)
    gps[3] = "E"
    gps[4] = _dms(GPS_LON_DMS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, exif=exif)
    return buf.getvalue()


# ------------------------------------------------------------------ inputs + right answers

# A US per-serving panel. Serving = 40 g, so basis_amount_g is 40 (the label
# lane's contract: basis = serving size in grams).
LABEL_SERVING = [
    "Nutrition Facts",
    "Peanut Butter Granola Bar",
    "Serving size 1 bar (40g)",
    "Calories 190",
    "Total Fat 7g",
    "Sodium 125mg",
    "Total Carbohydrate 29g",
    "Dietary Fiber 2g",
    "Total Sugars 12g",
    "Protein 4g",
]
LABEL_SERVING_EXPECT = {"basis_amount_g": 40, "kcal": 190, "protein_g": 4, "carbs_g": 29, "fat_g": 7}
LABEL_SERVING_SODIUM_MG = 125

# A European per-100 g panel: the numbers ARE per 100 g, so basis is 100
# and kcal is the kcal figure (not the kJ one).
LABEL_100G = [
    "Nutrition information",
    "Rolled Oats",
    "Typical values per 100 g",
    "Energy 1580 kJ / 375 kcal",
    "Fat 7 g",
    "Carbohydrate 60 g",
    "Fibre 10 g",
    "Protein 13 g",
    "Sodium 5 mg",
]
LABEL_100G_EXPECT = {"basis_amount_g": 100, "kcal": 375, "protein_g": 13, "carbs_g": 60, "fat_g": 7}
LABEL_100G_SODIUM_MG = 5

# 16.00 + 11.50 + 3.75 = 31.25; tax 6% = 1.875 -> 1.88; + tip 6.00 = 39.13.
RECEIPT = [
    "BLUE HERON BISTRO",
    "1420 King St, Alexandria VA",
    "Date: 09/27/2026   7:42 PM",
    "Server: Maria      Table 12",
    "Margherita Pizza          16.00",
    "Caesar Salad              11.50",
    "Iced Tea                   3.75",
    "Subtotal                  31.25",
    "Tax 6%                     1.88",
    "Tip                        6.00",
    "TOTAL                     39.13",
    "VISA ****4417             39.13",
    "Thank you for dining with us!",
]
RECEIPT_TOTAL = 39.13
RECEIPT_DATE = "2026-09-27"
RECEIPT_MERCHANT_WORDS = ("blue heron",)

PASSPORT = [
    "UNITED STATES OF AMERICA                 PASSPORT",
    "Type P    Code USA    Passport No. 912345678",
    "Surname: DOE",
    "Given names: JANE",
    "Nationality: UNITED STATES OF AMERICA",
    "Date of birth: 14 MAR 1990",
    "Date of issue: 02 JAN 2020",
    "Date of expiration: 01 JAN 2030",
    "Authority: United States Department of State",
]
PASSPORT_MRZ = [
    "P<USADOE<<JANE<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<",
    "9123456784USA9003141F3001015<<<<<<<<<<<<<<00",
]
PASSPORT_ISSUED = "2020-01-02"
PASSPORT_EXPIRES = "2030-01-01"

# Champ de Mars, Paris: 48°51'30" N, 2°17'40" E (whole-second DMS, so the
# decimal is exact: 48.858333, 2.294444 -> the line prints 4 dp).
GPS_LAT_DMS = (48, 51, 30)
GPS_LON_DMS = (2, 17, 40)
GPS_COORDS_TEXT = "48.8583, 2.2944"
GPS_TAKEN = "2026:06:14 15:32:10"
GPS_TAKEN_TEXT = "taken 2026-06-14 15:32"
GPS_FOLDER_PREFIX = "media/photos/2026/june"


# ------------------------------------------------------------------ helpers


def _nutrition_entry(r: dict) -> dict:
    """The ingredient_preset proposal a label photo must become."""
    e = first(r, "ingredient_preset")
    assert e.get("kcal") is not None, f"no nutrition reading; pipeline={r.get('pipeline')} entry={e}"
    return e


def _assert_label(e: dict, expect: dict, sodium_mg: float) -> None:
    got = {k: e.get(k) for k in expect}
    bad = {k: (got[k], v) for k, v in expect.items() if got[k] is None or abs(float(got[k]) - v) > 0.5}
    assert not bad, f"(got, want) per field: {bad}; full={got}"
    assert e.get("source") == "label", f"printed label numbers must win (source=label), got source={e.get('source')!r}"
    sodium = [m for m in e.get("micros") or [] if (m.get("nutrient") or "").strip().lower() == "sodium"]
    assert sodium, f"sodium is printed but missing from micros: {e.get('micros')}"
    s = sodium[0]
    assert (s.get("unit") or "").lower() == "mg", s
    assert abs(float(s["amount"]) - sodium_mg) <= 0.5, f"sodium {s} != {sodium_mg} mg"


# ------------------------------------------------------------------ checks


def check_label_per_serving(c, provider):
    """A per-serving panel: every macro + sodium is printed, so the preset must carry exactly those numbers on a 40 g basis."""
    r = drop(c, data=label_png(LABEL_SERVING), filename="granola_label.png", provider=provider)
    _assert_label(_nutrition_entry(r), LABEL_SERVING_EXPECT, LABEL_SERVING_SODIUM_MG)
    return r


def check_label_per_100g(c, provider):
    """A per-100 g panel: the preset's basis is 100 g and the numbers are the printed per-100 g ones (kcal, not kJ)."""
    r = drop(c, data=label_png(LABEL_100G), filename="oats_label.png", provider=provider)
    _assert_label(_nutrition_entry(r), LABEL_100G_EXPECT, LABEL_100G_SODIUM_MG)
    return r


def check_restaurant_receipt(c, provider):
    """A restaurant receipt is a spend: one finance entry for the final TOTAL (not subtotal), the printed date, the merchant, kind=food."""
    r = drop(c, data=receipt_png(), filename="receipt.png", provider=provider)
    e = first(r, "finance")
    assert abs(float(e.get("amount") or 0) - RECEIPT_TOTAL) < 0.005, f"amount={e.get('amount')} want {RECEIPT_TOTAL}"
    assert e.get("entry_date") == RECEIPT_DATE, f"entry_date={e.get('entry_date')!r} want {RECEIPT_DATE}"
    merchant = (e.get("merchant") or "").lower()
    assert any(w in merchant for w in RECEIPT_MERCHANT_WORDS), f"merchant={e.get('merchant')!r}"
    assert e.get("kind") == "food", f"a non-alcoholic restaurant meal is kind=food, got {e.get('kind')!r}"
    return r


def check_passport_photo(c, provider):
    """A passport data page is vault paperwork: a document_entry typed passport with the printed issue/expiry dates."""
    r = drop(c, data=passport_png(), filename="passport.png", provider=provider)
    assert "finance" not in types(r), types(r)
    e = first(r, "document_entry")
    assert (e.get("doc_type") or "").strip().lower() == "passport", f"doc_type={e.get('doc_type')!r}"
    assert e.get("expiry_date") == PASSPORT_EXPIRES, f"expiry_date={e.get('expiry_date')!r}"
    assert e.get("issued_date") == PASSPORT_ISSUED, f"issued_date={e.get('issued_date')!r}"
    return r


def check_gps_photo_place(c, provider):
    """A camera photo with EXIF date+GPS is filed under Media/Photos/<year>/<month> and, once saved, its note carries the 📍 place line (coords + capture time from EXIF; city/country when geocoded).

    The /drop PROPOSAL never carries the 📍 line — by design it's baked at
    Save (nodes/kb/api.py create_entry_with_asset -> photo_place.bake_photo_place),
    so this check drops, then saves the proposal exactly as the review card
    would, then reads the note back.

    Network/model note: reverse geocoding (photo_organizer.geocode) is a
    CLOUD Claude call, not a geocoding web API; there is no local geocoder.
    So in local mode only the deterministic part of the line (coords +
    taken) is required, and the drop itself must not need the cloud — a
    local drop that dies with "cloud call blocked" here is a finding
    (compute_photo_folder geocodes every GPS photo, home or abroad)."""
    jpg = gps_photo_jpg()
    r = drop(c, data=jpg, filename="IMG_20260614_153210.jpg", provider=provider)
    e = first(r, "kb_entry")
    assert folder_of(e).startswith(GPS_FOLDER_PREFIX), f"folder={e.get('folder')!r} want under {GPS_FOLDER_PREFIX}"
    assert "document_entry" not in types(r) and "finance" not in types(r), types(r)

    saved = c.post(
        "/kb/entries/with-asset",
        data={"folder": e["folder"], "title": e.get("title") or "Photo", "content": e.get("content") or "",
              "links": ",".join(e.get("links") or [])},
        files={"files": ("IMG_20260614_153210.jpg", jpg, "image/jpeg")},
    )
    assert saved.status_code == 200, saved.text[:400]
    s = saved.json()
    loc = s.get("location") or {}
    assert abs(float(loc.get("lat", 0)) - 48.858333) < 1e-4 and abs(float(loc.get("lon", 0)) - 2.294444) < 1e-4, loc

    note = c.get("/kb/entry", params={"folder": s["folder"], "slug": s["slug"]})
    assert note.status_code == 200, note.text[:400]
    lines = [l for l in note.json()["content"].splitlines() if l.strip().startswith("📍")]
    assert len(lines) == 1, f"want exactly one 📍 line, got {lines}"
    line = lines[0]
    assert GPS_COORDS_TEXT in line, line
    assert GPS_TAKEN_TEXT in line, line
    if provider == "cloud":
        # Claude geocodes the coords: the place names + the code-table continent.
        assert "Paris" in line and "France" in line and "Europe" in line, line
    return r


ALL = [check_label_per_serving, check_label_per_100g, check_restaurant_receipt, check_passport_photo,
       check_gps_photo_place]
