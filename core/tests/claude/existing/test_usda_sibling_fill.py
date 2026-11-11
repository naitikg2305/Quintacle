"""2026-11-11 live-test fix: "how much selenium is in 200g of lamb?" answered
"USDA has no selenium value" because the best match was the Foundation row
"Lamb, ground, raw" (FDC 2727570, ~15 nutrients), while the SR Legacy row of
the SAME food (FDC 174370, same NDB 17224) publishes 18.8 mcg/100 g.

Faked: a tiny USDA db built here with the real schema and the real numbers
of those two rows (plus a different lamb food that must NOT be used as a
sibling). No network, no model (the picker is off suite-wide)."""
from __future__ import annotations

import sqlite3

import pytest

from quintacle_core.nutrition_db import store as usda
from quintacle_core.nutrition_db.chat_lane import asked_nutrients, chat_nutrition_block
from quintacle_core.nutrition_db.nutrients import NUTRIENTS

FOUNDATION, SR, OTHER, NO_NDB = 2727570, 174370, 172617, 9000001

FOODS = [
    (FOUNDATION, "Lamb, ground, raw", "Lamb, Veal, and Game Products", "foundation", "17224",
     {"Energy": 236.6, "Protein": 17.4, "Fat": 18.6, "Calcium": 6.6, "Iron": 1.6, "Zinc": 3.1}),
    (SR, "Lamb, ground, raw", "Lamb, Veal, and Game Products", "sr_legacy", "17224",
     {"Energy": 282, "Protein": 16.56, "Fat": 23.41, "Calcium": 16, "Iron": 1.55, "Zinc": 3.41,
      "Selenium": 18.8, "ALA (omega-3)": 0.42, "Vitamin B12": 2.31}),
    # A different food (other NDB, other description): never a sibling.
    (OTHER, "Lamb, New Zealand, imported, ground lamb, raw", "Lamb, Veal, and Game Products", "sr_legacy", "17393",
     {"Energy": 287, "Protein": 16.4, "Fat": 24.6, "Selenium": 3.0}),
    # Same description, no NDB on either side: still the same food.
    (NO_NDB, "Spinach, raw", "Vegetables", "foundation", "", {"Energy": 23, "Protein": 2.9}),
    (NO_NDB + 1, "Spinach,  raw", "Vegetables", "sr_legacy", "", {"Energy": 23, "Protein": 2.86, "Vitamin K": 482.9}),
]


@pytest.fixture
def lamb_db(tmp_path, monkeypatch):
    path = tmp_path / "usda.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE foods (fdc_id INTEGER PRIMARY KEY, description TEXT NOT NULL,
                            category TEXT NOT NULL DEFAULT '', source TEXT NOT NULL, ndb TEXT NOT NULL DEFAULT '');
        CREATE TABLE nutrients (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, unit TEXT NOT NULL, grp TEXT NOT NULL);
        CREATE TABLE food_nutrient (fdc_id INTEGER NOT NULL, nutrient_id INTEGER NOT NULL,
                                    amount REAL NOT NULL, approx INTEGER NOT NULL DEFAULT 0,
                                    PRIMARY KEY (fdc_id, nutrient_id)) WITHOUT ROWID;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE VIRTUAL TABLE foods_fts USING fts5(description, category, content='foods', content_rowid='fdc_id');
        """
    )
    ids = {}
    for i, n in enumerate(NUTRIENTS, start=1):
        conn.execute("INSERT INTO nutrients VALUES (?,?,?,?)", (i, n.name, n.unit, n.group))
        ids[n.name] = i
    for fdc, desc, cat, src, ndb, values in FOODS:
        conn.execute("INSERT INTO foods VALUES (?,?,?,?,?)", (fdc, desc, cat, src, ndb))
        for name, amount in values.items():
            conn.execute("INSERT INTO food_nutrient VALUES (?,?,?,0)", (fdc, ids[name], amount))
    conn.execute("INSERT INTO foods_fts (foods_fts) VALUES ('rebuild')")
    conn.commit()
    conn.close()
    monkeypatch.setenv("QUINTACLE_USDA_DB", str(path))
    return path


def test_siblings_are_same_ndb_or_same_description(lamb_db):
    assert [s["fdc_id"] for s in usda.siblings(FOUNDATION)] == [SR]
    assert [s["fdc_id"] for s in usda.siblings(SR)] == [FOUNDATION]
    assert usda.siblings(OTHER) == []
    assert [s["fdc_id"] for s in usda.siblings(NO_NDB)] == [NO_NDB + 1]


def test_preset_fills_missing_micros_from_sibling_and_marks_the_fdc_id(lamb_db):
    p = usda.preset_from_usda(FOUNDATION, 200)
    micros = {m["nutrient"]: m for m in p["micros"]}
    assert micros["Selenium"]["amount"] == pytest.approx(37.6)
    assert micros["Selenium"]["from_fdc_id"] == SR and micros["Selenium"]["source"] == "usda"
    assert micros["ALA (omega-3)"]["from_fdc_id"] == SR
    # The matched row's own values win and carry no from_fdc_id.
    assert micros["Calcium"]["amount"] == pytest.approx(13.2) and "from_fdc_id" not in micros["Calcium"]
    assert p["kcal"] == pytest.approx(473.2) and p["fdc_id"] == FOUNDATION
    assert p["usda_fill"] == [{"fdc_id": SR, "description": "Lamb, ground, raw", "source": "sr_legacy",
                               "nutrients": ["ALA (omega-3)", "Selenium", "Vitamin B12"]}]
    # Opt-out gives the raw row; the raw per-100 g profile is unchanged.
    assert "Selenium" not in {m["nutrient"] for m in usda.preset_from_usda(FOUNDATION, 200, fill_from_siblings=False)["micros"]}
    assert "Selenium" not in usda.profile_per_100g(FOUNDATION)
    # A food with no sibling has nothing filled (unknown stays absent).
    assert usda.preset_from_usda(OTHER, 100)["usda_fill"] == []


def test_asked_nutrients():
    assert asked_nutrients("how much selenium is in 200g of lamb?") == ["Selenium"]
    got = asked_nutrients("omega-3 and saturated fat in salmon")
    assert "DHA (omega-3)" in got and "Saturated Fat" in got and "Fat" not in got
    assert asked_nutrients("what's in 200g lamb") == []


def test_chat_lane_answers_selenium_from_the_sibling_entry_and_names_it(lamb_db):
    block = chat_nutrition_block("how much selenium is in 200g of lamb?")
    assert block is not None
    assert 'USDA match: "Lamb, ground, raw" (FDC 2727570, Foundation)' in block
    assert '- Selenium: 37.6 mcg (from "Lamb, ground, raw", FDC 174370, SR Legacy)' in block
    assert "Selenium 37.6 mcg" in block  # the panel total carries it too
    assert "no published value for: " not in block.split("Selenium 37.6")[0]  # not reported missing first
    tail = block.rsplit("USDA has no published value for:", 1)
    assert len(tail) == 1 or "Selenium" not in tail[1]


def test_chat_lane_says_unknown_when_no_entry_has_it(lamb_db):
    block = chat_nutrition_block("how much iodine is in 200g of lamb?")
    assert "- Iodine: USDA publishes no value for this food in any entry" in block
