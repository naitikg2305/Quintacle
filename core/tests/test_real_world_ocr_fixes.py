"""2026-11-07 fixes from running the owner's REAL files through the golden
check (none of his files are here — every fixture below is synthetic):

1. a tilted, two-column Toast receipt read total $19.00 (real $510.13) —
   OCR deskew + label/value pairing by row + total sanity in code;
2. a chicken-burger label lost "Calories 170" to row chaining, then the
   local LLM's name ("Onion") and a derived 169 kcal won — calories read
   across panel words, parser values always win, the LLM never names a
   label, a name match the printed numbers contradict is dropped;
3. a Greek-yogurt label got the OCR-noise name "ada ice. If you'te" —
   tightened name heuristic, else a name from the USDA profile match.
"""
from __future__ import annotations

import math
import sqlite3

import pytest

from quintacle_core.nodes.finance.receipt_parser import parse_receipt, rows_from_fragments
from quintacle_core.nodes.logs.label_parser import (
    guess_product_name,
    name_from_usda_description,
    overlay_parsed,
    parse_label,
)
from quintacle_core.nutrition_db import store
from quintacle_core.perception.ocr import _Frag, deskew, group_rows, page_angle

# ------------------------------------------------------------------ helpers

# The receipt's printed rows: label column left, price column right.
TOAST_ROWS = [
    ("PINK TIGER", None),
    ("751 Wharf St", None),
    ("Washington, DC 20024", None),
    ("Ordered: 9/20/26 2:27 PM", None),
    ("1 Our Old Fashioned", "$18.00"),
    ("1 Ahi Tuna Nachos", "$22.00"),
    ("1 Pad Thai, Add Chicken", "$36.00"),
    ("3 Mimosa", "$51.00"),
    ("1 Joe's Smash Burger", "$19.00"),
    ("Operations Fee (5.00%)", "$18.55"),
    ("Subtotal", "$389.55"),
    ("Auto gratuity (20.00%)", "$74.20"),
    ("Tax", "$46.38"),
    ("Total", "$510.13"),
    ("Suggested Tip:", None),
    ("20%: (Tip $83.48 Total $593.61)", None),
    ("22%: (Tip $91.82 Total $601.95)", None),
]


def _tilted(text: str, x: float, y: float, w: float, h: float, deg: float) -> _Frag:
    """A level text box (x, y, w, h) rotated by `deg` about the origin, as
    RapidOCR reports it: the axis-aligned extent of the rotated quad plus
    the text's angle and true width/height."""
    r = math.radians(deg)
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    rot = [(px * math.cos(r) - py * math.sin(r), px * math.sin(r) + py * math.cos(r)) for px, py in pts]
    xs, ys = [p[0] for p in rot], [p[1] for p in rot]
    return _Frag(text, min(xs), min(ys), max(xs), max(ys), 0.99, deg, w, h)


def _toast_fragments(deg: float = 9.0) -> list[_Frag]:
    frags = []
    for i, (label, value) in enumerate(TOAST_ROWS):
        y = 300 + 33 * i
        frags.append(_tilted(label, 400, y, 12 * len(label), 34, deg))
        if value:
            frags.append(_tilted(value, 950, y, 90, 34, deg))
    return frags


# ------------------------------------------------------------------ 1. receipt


def test_deskew_groups_a_tilted_two_column_receipt_into_its_rows():
    frags = _toast_fragments(9.0)
    assert abs(page_angle(frags) - 9.0) < 0.01
    lines = [ln.text for ln in group_rows(frags)]
    assert "Subtotal $389.55" in lines and "Total $510.13" in lines and "Tax $46.38" in lines
    assert "1 Joe's Smash Burger $19.00" in lines
    r = parse_receipt("\n".join(lines))
    assert r.total == 510.13 and r.subtotal == 389.55 and r.tax == 46.38 and r.tip == 74.20
    assert r.merchant == "Pink Tiger" and r.entry_date == "2026-09-20"
    assert r.confidence["total"] == 0.95  # equals subtotal + tax + tip, checked in code


def test_without_deskew_the_tilted_receipt_misreads():
    # The pre-fix behaviour: axis-aligned boxes chained into giant rows.
    flat = [_Frag(f.text, f.x0, f.y0, f.x1, f.y1, f.conf) for f in _toast_fragments(9.0)]
    lines = [ln.text for ln in group_rows(flat)]
    assert "Total $510.13" not in lines


def test_receipt_pairs_labels_with_values_from_boxes():
    # Deskewed fragments whose price column drifts ~12 px below its labels
    # (perspective) — rows_from_fragments pairs each price with the nearest row.
    frags = []
    for i, (label, value) in enumerate(TOAST_ROWS):
        y = 300 + 40 * i
        frags.append((label, (400.0, float(y), 200.0, 34.0), 0.99))
        if value:
            frags.append((value, (950.0, float(y + 12), 90.0, 34.0), 0.99))
    rows = rows_from_fragments(frags)
    assert "Total $510.13" in rows and "Auto gratuity (20.00%) $74.20" in rows
    r = parse_receipt("ignored when fragments are given", frags)
    assert r.total == 510.13 and r.subtotal == 389.55
    assert {"name": "1 Joe's Smash Burger", "price": 19.0} in r.items
    assert all(i["price"] != 510.13 for i in r.items)


def test_text_only_column_dump_is_zipped_back_into_rows():
    text = "PINK TIGER\n1 Burger\n$19.00\nSubtotal\nAuto gratuity (20.00%)\nTax\nTotal\n$389.55\n$74.20\n$46.38\n$510.13"
    r = parse_receipt(text)
    assert r.total == 510.13 and r.subtotal == 389.55 and r.tip == 74.20


def test_suggested_tip_table_and_percentages_are_not_totals():
    r = parse_receipt("CAFE\nSoup 10.00\nSubtotal 10.00\nTax 1.00\nTotal 11.00\n20%: (Tip $2.20 Total $13.20)\nService (18.00%)")
    assert r.total == 11.00 and r.tip is None


def test_total_below_subtotal_is_rejected_and_never_an_item_price():
    # An OCR'd "Total" that can't be right (below the subtotal) and no other
    # total: computed from subtotal + tax + tip, never the biggest item.
    r = parse_receipt("BAR\nSteak 48.00\nWine 30.00\nSubtotal 78.00\nTax 7.80\nGratuity 15.60\nTotal 7.80")
    assert r.total == 101.40 and r.confidence["total"] == 0.6


def test_receipt_drop_hands_fragments_to_the_parser(monkeypatch):
    from quintacle_core.nodes import drop_router
    from quintacle_core.perception import ocr

    frags = _toast_fragments(9.0)
    lines = group_rows(frags)
    reading = ocr.OcrResult(lines=lines, text="garbled sequential text\nTotal\n$19.00", engine="fake", fragments=deskew(frags))
    monkeypatch.setattr(ocr, "ocr_image", lambda data: reading)
    entry, pipeline = drop_router._extract_receipt_local([(b"x", "image/jpeg")], "")
    assert pipeline == "ocr+parser" and entry.amount == 510.13 and entry.merchant == "Pink Tiger"


# ------------------------------------------------------------------ 2. label


BURGER_ROWS = """Nutrition Facts INGREDIENTS
8 servings per container
Serving Size 1 Burger (112g)
Amount per serving Calories % Daily Value* 170
Total Fat 9g 12%
Saturated Fat 3g 15%
Trans Fat 0g
Cholesterol 100mg 33%
Sodium 620mg 27%
Total Carbohydrate 3g 1%
Dietary Fiber 0g 0%
Total Sugars 1g
Includes 1g Added Sugars 2%
Protein 19g
*The % Daily Value (DV) tells you how much a nutrient in
a serving of food contributes to a daily diet. 2,000 calories"""


def test_calories_read_across_panel_words_on_one_row():
    parse = parse_label(BURGER_ROWS)
    assert parse.values["kcal"].amount == 170 and parse.values["kcal"].how == "stated"
    assert parse.core_complete
    assert (parse.values["protein_g"].amount, parse.values["carbs_g"].amount, parse.values["fat_g"].amount) == (19, 3, 9)


def test_footnote_2000_calories_is_never_the_calorie_count():
    parse = parse_label("Total Fat 9g\nProtein 19g\nTotal Carbohydrate 3g\na daily diet. 2,000 calories a day is used")
    assert parse.values["kcal"].how == "derived"  # 4/4/9 in code, not 2000


def test_tall_box_no_longer_chains_rows():
    frags = [
        ("Amount per serving", 478, 714, 738, 750, 1.0),
        ("Calories", 477, 744, 722, 799, 1.0),
        ("170", 805, 747, 941, 818, 1.0),
        ("% Daily Value*", 773, 825, 944, 855, 0.97),
        ("Total Fat 9g", 472, 844, 649, 880, 0.98),
        ("12%", 866, 865, 937, 901, 1.0),
    ]
    lines = [ln.text for ln in group_rows(frags)]
    assert "Calories 170" in lines and "Amount per serving" in lines


def test_overlay_parser_wins_llm_fills_gaps_and_never_names():
    parse = parse_label("Serving size 1 burger (112g)\nTotal Fat 9g\nTotal Carbohydrate 3g\nProtein 19g\nSodium 620mg")
    assert parse.values["kcal"].how == "derived" and parse.values["kcal"].amount == 169
    model = {"basis_amount_g": 100, "protein_g": 25, "carbs_g": 9, "fat_g": 1, "fiber_g": 2, "kcal": 170,
             "micros": [{"nutrient": "Sodium", "amount": 1, "unit": "mg"}, {"nutrient": "Iron", "amount": 1, "unit": "mg"}],
             "suggested_name": "Onion"}
    out = overlay_parsed(model, parse, "")
    assert (out["protein_g"], out["carbs_g"], out["fat_g"]) == (19, 3, 9)  # read by code — model ignored
    assert out["kcal"] == 170 and out["field_confidence"]["kcal"] == 0.5  # unread → the model's printed read
    assert out["fiber_g"] == 2  # unread → model fills
    assert next(m for m in out["micros"] if m["nutrient"] == "Sodium")["amount"] == 620
    assert out["suggested_name"] == "" and out["basis_amount_g"] == 112
    # The model gave nothing for kcal → code's derived 4/4/9 value.
    out = overlay_parsed({**model, "kcal": 0}, parse, "Chicken Burger")
    assert out["kcal"] == 169 and out["suggested_name"] == "Chicken Burger"


def test_local_label_with_missing_core_field_keeps_parsed_values_and_name(monkeypatch):
    from quintacle_core.nodes.logs import nutrition_llm
    from quintacle_core.perception import ocr

    text = "Nutrition Facts\nServing size 1 burger (112g)\nTotal Fat 9g\nTotal Carbohydrate 3g\nProtein 19g"
    lines = [ocr.OcrLine(t, (0.0, 40.0 * i, 300.0, 30.0), 0.99) for i, t in enumerate(text.splitlines())]
    frags = [ocr.OcrLine("Onion", (1230.0, -30.0, 250.0, 120.0), 1.0, -17.4, True), *lines]
    monkeypatch.setattr(ocr, "ocr_image", lambda data: ocr.OcrResult(lines=lines, text=text, engine="fake", fragments=frags))

    class _M:
        parsed = nutrition_llm.NutritionEstimateFromImage(
            basis_amount_g=100, protein_g=1, carbs_g=9, fat_g=0, fiber_g=1, kcal=170, micros=[], suggested_name="Onion")

    monkeypatch.setattr(nutrition_llm, "parse_structured", lambda *a, **k: _M())
    reading, pipeline = nutrition_llm._estimate_from_image_local([(b"x", "image/jpeg")], "")
    assert pipeline == "ocr+local-llm"
    assert reading.suggested_name == "Labeled food"  # not the model's, not the clipped/tilted "Onion"
    assert (reading.protein_g, reading.carbs_g, reading.fat_g, reading.kcal) == (19, 3, 9, 170)
    assert reading.basis_amount_g == 112


# ------------------------------------------------------------------ 3. names


def test_guess_product_name_rejects_ocr_noise_and_boilerplate():
    panel = [(t, (0, 0, 300, 35), 0.98) for t in ("Total Fat 0g", "Sodium 65mg", "Protein 18g", "Calcium 220mg", "Iron 0mg")]
    assert guess_product_name(panel + [("ada ice. If you'te", (0, 0, 300, 65), 0.55)]) == ""
    assert guess_product_name(panel + [("ada ice. If you'te", (0, 0, 300, 65), 0.95)]) == ""  # garble, even if confident
    for junk in ("WWW.COSTCO.COM", "DISTRIBUTED BY KIRKLAND", "NO ANTIBIOTICS", "CHICKEN RAISED WITH", "GLUTEN-FREE",
                 "CERTIFIED ORGANIC BY", "Extract of Rosemary, Organic Garlic.", "ORGANIC", "lnecls eg Sgars", "Consumers wih"):
        assert guess_product_name(panel + [(junk, (0, 0, 300, 70), 0.99)]) == "", junk
    assert guess_product_name(panel + [("Onion", (0, 0, 250, 120), 1.0, -17.4, False)]) == ""  # tilted off the page
    assert guess_product_name(panel + [("BURGERS", (0, 0, 230, 90), 1.0, 0.6, True)]) == ""  # cut off by the frame
    assert guess_product_name(panel + [("Lacto Bacillus", (0, 0, 120, 35), 0.99)]) == ""  # panel-sized print
    assert guess_product_name(panel + [("KIRKLAND SIGNATURE", (0, 0, 400, 80), 0.99)]) == "Kirkland Signature"
    assert guess_product_name(panel + [("Joe's Smash Burger", (0, 0, 400, 80), 0.99)]) == "Joe's Smash Burger"


@pytest.mark.parametrize(
    "desc,name",
    [("Yogurt, Greek, plain, nonfat", "Greek yogurt"), ("Onions, raw", "Onions"), ("Cheese, cheddar", "Cheddar cheese"),
     ("Chicken, broilers or fryers, breast, meat only, raw", "Chicken"), ("Bread, white", "White bread"), ("", "")],
)
def test_name_from_usda_description(desc, name):
    assert name_from_usda_description(desc) == name


@pytest.fixture
def tiny_usda(tmp_path, monkeypatch):
    db = tmp_path / "usda.db"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE foods (fdc_id INTEGER PRIMARY KEY, description TEXT, category TEXT, source TEXT);
    CREATE TABLE nutrients (id INTEGER PRIMARY KEY, name TEXT, unit TEXT);
    CREATE TABLE food_nutrient (fdc_id INTEGER, nutrient_id INTEGER, amount REAL, approx INTEGER DEFAULT 0);
    INSERT INTO nutrients VALUES (1,'Energy','kcal'),(2,'Protein','g'),(3,'Carbohydrates','g'),(4,'Fat','g'),(22,'Calcium','mg');
    INSERT INTO foods VALUES (10,'Yogurt, Greek, plain, nonfat','Dairy and Egg Products','sr_legacy'),
                             (12,'Egg, white, raw','Dairy and Egg Products','sr_legacy'),
                             (14,'Onions, raw','Vegetables and Vegetable Products','sr_legacy'),
                             (15,'Chicken, ground, raw','Poultry Products','sr_legacy'),
                             (16,'Fish, pike, northern, liver (Alaska Native)','American Indian/Alaska Native Foods','sr_legacy');
    """)
    for fid, vals in {10: (59, 10.2, 3.6, 0.4, 110), 12: (52, 10.9, 0.7, 0.2, 7), 14: (40, 1.1, 9.3, 0.1, 23),
                      15: (143, 17.4, 0.0, 8.1, 6), 16: (150, 16.5, 2.5, 7.8, 10)}.items():
        for nid, v in zip((1, 2, 3, 4, 22), vals):
            c.execute("INSERT INTO food_nutrient VALUES (?,?,?,0)", (fid, nid, v))
    c.commit()
    c.close()
    monkeypatch.setenv("QUINTACLE_USDA_DB", str(db))
    store._conns.clear()
    yield
    store._conns.clear()


def test_label_without_a_name_is_named_from_its_usda_profile_match(tiny_usda):
    from quintacle_core.api import _source_ingredient_image

    fields = {"from_label": True, "suggested_name": "Labeled food", "basis_amount_g": 170, "kcal": 100, "protein_g": 18,
              "carbs_g": 7, "fat_g": 0, "fiber_g": 0, "micros": [], "ocr_text": "INGREDIENTS: CULTURED PASTEURIZED NONFAT MILK"}
    out = _source_ingredient_image(fields)
    assert out["fdc_id"] == 10 and out["usda_match_by"] == "nutrition profile"
    assert out["suggested_name"] == "Greek yogurt"
    assert (out["kcal"], out["protein_g"]) == (100, 18)  # the label's numbers stay


def test_name_match_contradicted_by_printed_numbers_falls_back_to_profile(tiny_usda, monkeypatch):
    import quintacle_core.api as api_module

    def fake_proposal(name, basis=100, provider=None):
        return {"fdc_id": 14, "usda_description": "Onions, raw", "matched": True,
                "usda_candidates": [{"fdc_id": 14, "description": "Onions, raw", "category": "", "source": "sr_legacy", "score": 1}]}

    monkeypatch.setattr(api_module, "usda_proposal", fake_proposal)
    fields = {"from_label": True, "suggested_name": "Onion", "basis_amount_g": 112, "kcal": 170, "protein_g": 19,
              "carbs_g": 3, "fat_g": 9, "fiber_g": 0, "micros": [], "ocr_text": "Organic Chicken, Organic White Cheddar"}
    out = api_module._source_ingredient_image(fields)
    assert out["fdc_id"] == 15 and out["usda_description"] == "Chicken, ground, raw"
    assert out["kcal"] == 170 and out["suggested_name"] == "Onion"  # an owner/OCR name is kept, never replaced


def test_profile_hints_are_whole_words_and_ingredients_outrank_numbers_alone(tiny_usda):
    # OCR'd "the"/"per" used to substring-hit "northern"; the label's
    # ingredient word "chicken" now outranks a numbers-only neighbour.
    per100 = {"kcal": 152, "protein_g": 17, "carbs_g": 2.7, "fat_g": 8}
    got = store.nearest_by_profile(per100, ["The", "per", "serving", "Organic", "Chicken", "Cheddar"])
    pike = next(c for c in got if c["fdc_id"] == 16)
    assert pike["hint_hits"] == 0
    assert got[0]["fdc_id"] == 15
    assert store.nearest_by_profile(per100)[0]["fdc_id"] == 16  # numbers alone still rank by distance
