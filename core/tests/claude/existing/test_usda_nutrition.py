"""USDA FoodData Central as the nutrition source of truth (2026-11-05).

No network: the db is built from tiny fixture CSVs (tests/fixtures/usda —
real FDC column layouts, a handful of foods). The candidate picker's model
seam is stubbed; conftest keeps it off everywhere else.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.nodes.logs.log_store import rebuild_sqlite_index
from quintacle_core.nodes.logs.nutrition_targets import rda_for, to_canonical_unit
from quintacle_core.nutrition_db import fetch as usda_fetch
from quintacle_core.nutrition_db import store as usda
from quintacle_core.nutrition_db.build import build_db, release_is_complete
from quintacle_core.nutrition_db.chat_lane import chat_nutrition_block, parse_items
from quintacle_core.nutrition_db.panel import build_panel

FIX = Path(__file__).parent / "fixtures" / "usda"
LAMB_LEAN = 174314
YOGURT = 330137
SALMON = 175139
BLUEBERRY = 171711


@pytest.fixture
def usda_db(tmp_path, monkeypatch):
    out = tmp_path / "nutrition" / "usda.db"
    summary = build_db([FIX / "foundation", FIX / "sr_legacy"], out, flavonoid_csv=FIX / "flavonoid" / "FLAV_DAT.csv")
    monkeypatch.setenv("QUINTACLE_USDA_DB", str(out))
    return summary


@pytest.fixture
def client(tmp_path, monkeypatch, usda_db):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path / "data")
    return TestClient(api_module.create_app())


# --- build + mapping ---------------------------------------------------------


def test_build_keeps_only_foundation_and_sr_foods_and_mapped_nutrients(usda_db, tmp_path):
    assert usda_db["foods"] == 9  # the sub_sample_food row is dropped
    assert usda_db["sources"] == ["foundation", "sr_legacy"]
    assert usda_db["flavonoids"].startswith("imported 6 values")  # unknown NDB 99999 skipped
    conn = sqlite3.connect(tmp_path / "nutrition" / "usda.db")
    assert conn.execute("SELECT COUNT(*) FROM foods WHERE fdc_id=330138").fetchone()[0] == 0
    names = {r[0] for r in conn.execute("SELECT name FROM nutrients")}
    for n in ("Calcium", "Selenium", "ALA (omega-3)", "EPA (omega-3)", "DPA (omega-3)", "DHA (omega-3)",
              "Linoleic acid (omega-6)", "Flavan-3-ols", "Flavonols", "Flavones", "Flavanones", "Anthocyanidins",
              "Isoflavones", "Beta-carotene", "Alpha-carotene", "Lycopene", "Lutein + zeaxanthin", "Beta-cryptoxanthin"):
        assert n in names


def test_units_and_fallbacks_are_converted_in_code(usda_db):
    lamb = usda.profile_per_100g(LAMB_LEAN)
    assert lamb["Copper"] == {"amount": 120.0, "unit": "mcg", "approx": False}  # 0.12 mg → mcg
    assert lamb["ALA (omega-3)"]["amount"] == 0.05 and lamb["ALA (omega-3)"]["approx"] is True  # 18:3 stand-in
    assert lamb["Linoleic acid (omega-6)"]["approx"] is True
    salmon = usda.profile_per_100g(SALMON)
    assert salmon["ALA (omega-3)"] == {"amount": 0.295, "unit": "g", "approx": False}  # isomer wins over total
    yogurt = usda.profile_per_100g(YOGURT)
    assert yogurt["Energy"]["amount"] == 61 and yogurt["Fat"]["amount"] == 0.37  # Atwater + NLEA fallbacks
    berry = usda.profile_per_100g(BLUEBERRY)
    assert berry["Anthocyanidins"]["amount"] == pytest.approx(8.5 + 35.4 + 67.6)  # class = sum of compounds
    assert berry["Flavonols"]["amount"] == 7.7 and berry["Flavan-3-ols"]["amount"] == pytest.approx(1.7)
    assert berry["Lutein + zeaxanthin"]["amount"] == 80
    assert berry["Vitamin D"]["amount"] == pytest.approx(1.0)  # 40 IU ÷ 40
    assert "Iodine" not in berry  # unknown is absent, never 0


def test_canonical_unit_knows_new_compounds():
    assert to_canonical_unit(500, "mg", "DHA (omega-3)") == (0.5, "g")
    assert to_canonical_unit(0.2, "mg", "Lycopene") == (200, "mcg")


def test_release_completeness_check(tmp_path):
    assert release_is_complete(FIX / "sr_legacy")
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "nutrient.csv").write_text("id\n")
    assert not release_is_complete(partial)


# --- matching ----------------------------------------------------------------


def test_match_ranks_the_plain_description_first(usda_db):
    top = usda.match_food("lamb leg roasted")
    assert top[0]["fdc_id"] == LAMB_LEAN  # lean only: shorter than "lean and fat"
    assert {c["fdc_id"] for c in top[:2]} == {LAMB_LEAN, 174312}
    assert usda.match_food("roast lamb")[0]["fdc_id"] in (LAMB_LEAN, 174312)  # roast → roasted, not raw liver
    assert usda.match_food("egg")[0]["fdc_id"] == 171287  # whole word: not Eggplant
    assert usda.match_food("blueberries")[0]["fdc_id"] == BLUEBERRY
    assert all(c["fdc_id"] != 170500 for c in usda.match_food("lamb")[:3])  # babyfood demoted
    assert usda.match_food("") == []


def test_no_db_means_no_candidates(monkeypatch):
    monkeypatch.setenv("QUINTACLE_USDA_DB", "/nonexistent/x.db")
    assert usda.match_food("lamb") == [] and not usda.is_installed()


def test_model_may_only_pick_an_index_among_candidates(usda_db, monkeypatch):
    import quintacle_core.llm_dispatch as dispatch

    candidates = usda.match_food("lamb leg roasted")
    seen = {}

    def fake(system, user, fmt, **kw):
        seen["fields"] = set(fmt.model_fields)
        seen["user"] = user
        return dispatch.ParseResult(fmt(choice=2), "local")

    monkeypatch.setattr(dispatch, "parse_structured", fake)
    assert usda.pick_candidate("lamb leg roasted", candidates, provider="local") == candidates[1]
    assert seen["fields"] == {"choice"}  # no field a number could come back in
    assert "1. Lamb, leg" in seen["user"]

    monkeypatch.setattr(dispatch, "parse_structured", lambda s, u, fmt, **k: dispatch.ParseResult(fmt(choice=99), "local"))
    assert usda.pick_candidate("lamb leg roasted", candidates, provider="local") == candidates[0]  # rejected → det.
    monkeypatch.setattr(dispatch, "parse_structured", lambda s, u, fmt, **k: dispatch.ParseResult(fmt(choice=0), "local"))
    assert usda.pick_candidate("lamb leg roasted", candidates, provider="local") is None  # "none of these"

    def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(dispatch, "parse_structured", boom)
    assert usda.pick_candidate("lamb leg roasted", candidates, provider="local") == candidates[0]


# --- presets -----------------------------------------------------------------


def test_ingredient_from_fdc_id_ignores_client_numbers(client, tmp_path):
    resp = client.post("/logs/ingredients", json={
        "name": "Roast lamb leg", "basis_amount_g": 200, "kcal": 9999, "protein_g": 1, "source": "usda", "fdc_id": LAMB_LEAN,
    }).json()
    assert resp["source"] == "usda" and resp["fdc_id"] == LAMB_LEAN
    assert resp["kcal"] == 382 and resp["protein_g"] == pytest.approx(56.6)
    micros = {m["nutrient"]: m for m in client.get(f"/logs/ingredients/{resp['id']}/micros").json()}
    assert micros["Selenium"]["amount"] == pytest.approx(60.2) and micros["Selenium"]["source"] == "usda"
    assert micros["ALA (omega-3)"]["approx"] == 1
    md = next((tmp_path / "data" / "kb").rglob("roast-lamb-leg.md")).read_text()
    assert "source: usda" in md and f"fdc_id: {LAMB_LEAN}" in md


def test_auto_match_and_estimated_fallback(client):
    hit = client.post("/logs/ingredients", json={"name": "greek yogurt", "kcal": 0, "auto_match": True}).json()
    assert hit["source"] == "usda" and hit["fdc_id"] == YOGURT and hit["kcal"] == 61
    miss = client.post("/logs/ingredients", json={
        "name": "grandma's mystery stew", "kcal": 300, "auto_match": True, "source": "estimated",
        "micros": [{"nutrient": "Iron", "amount": 2, "unit": "mg"}],
    }).json()
    assert miss["source"] == "estimated" and miss["fdc_id"] is None and miss["kcal"] == 300
    assert miss["micros"][0]["source"] == "estimated"


def test_label_values_win_and_gaps_fill_from_usda(client):
    resp = client.post("/logs/ingredients", json={
        "name": "Brand X Greek Yogurt", "basis_amount_g": 170, "kcal": 90, "protein_g": 16, "source": "label",
        "fdc_id": YOGURT, "micros": [{"nutrient": "Calcium", "amount": 200, "unit": "mg"}],
    }).json()
    assert resp["source"] == "label" and resp["kcal"] == 90  # label macros untouched
    micros = {m["nutrient"]: m for m in resp["micros"]}
    assert micros["Calcium"] == {"nutrient": "Calcium", "amount": 200, "unit": "mg", "source": "label"}
    assert micros["Selenium"]["source"] == "usda" and micros["Selenium"]["amount"] == pytest.approx(9.7 * 1.7)


def test_sources_survive_markdown_rebuild(client):
    client.post("/logs/ingredients", json={"name": "Lamb", "kcal": 0, "source": "usda", "fdc_id": LAMB_LEAN})
    repo = api_module.get_logs_repo()
    rebuild_sqlite_index(repo.log_store, repo.conn, repo.preset_store, repo.ingredient_store)
    row = repo.conn.execute("SELECT source, fdc_id FROM ingredients WHERE name='Lamb'").fetchone()
    assert (row["source"], row["fdc_id"]) == ("usda", LAMB_LEAN)
    m = repo.conn.execute("SELECT source FROM ingredient_micros WHERE nutrient='Selenium'").fetchone()
    assert m["source"] == "usda"


def test_composer_new_components_use_usda(client, monkeypatch):
    from quintacle_core.nodes.logs import api as logs_api
    from quintacle_core.nodes.logs.meal_composer import ComposedComponent, MealCompositionSuggestion

    def comp(name, q):
        return ComposedComponent(name=name, quantity_g=q, protein_g=1, carbs_g=1, fat_g=1, fiber_g=0, kcal=5, micros=[])

    monkeypatch.setattr(logs_api, "suggest_meal_composition", lambda d, k, provider=None: MealCompositionSuggestion(
        meal_name="Lamb plate", components=[comp("lamb leg roasted", 200), comp("unobtainium paste", 10)]))
    out = client.post("/logs/meals/suggest-composition", json={"description": "lamb plate"}).json()
    lamb, paste = out["components"]
    assert lamb["source"] == "usda" and lamb["fdc_id"] == LAMB_LEAN and lamb["kcal"] == 382
    assert paste["source"] == "estimated" and paste["kcal"] == 5
    saved = client.post("/logs/meals/from-ingredients", json={"name": "Lamb plate", "components": [
        {"name": "Roast lamb", "quantity_g": 200, "fdc_id": LAMB_LEAN, "kcal": 1},
        {"name": "Paste", "quantity_g": 10, "kcal": 5, "basis_amount_g": 10},
    ]}).json()
    panel = client.get(f"/nutrition/meal/{saved['id']}").json()
    energy = _find(panel, "Energy")
    assert energy["amount"] == pytest.approx(387) and energy["source"] == "mixed"
    sel = _find(panel, "Selenium")
    assert sel["contributions"][0]["name"] == "Roast lamb" and sel["contributions"][0]["pct"] == 100


def _find(panel, name):
    return next(n for g in panel["groups"] for n in g["nutrients"] if n["nutrient"] == name)


# --- panel / targets / ratio -------------------------------------------------


def test_ala_has_an_official_adequate_intake():
    assert rda_for("male", 30)["ALA (omega-3)"] == (1.6, "g")
    assert rda_for("female", 30)["ALA (omega-3)"] == (1.1, "g")
    assert rda_for("female", 60)["ALA (omega-3)"] == (1.1, "g")


def test_panel_contributions_ratio_and_reference_labels(client):
    comps = [
        {"name": "Salmon", "source": "usda", "macros": {"kcal": 208}, "micros": usda.preset_from_usda(SALMON, 100)["micros"]},
        {"name": "Lamb", "source": "usda", "macros": {"kcal": 191}, "micros": usda.preset_from_usda(LAMB_LEAN, 100)["micros"]},
    ]
    from quintacle_core.nodes.logs.nutrition_api import current_targets
    from quintacle_core.nodes.logs.nutrition_targets import REFERENCE_TARGETS

    panel = build_panel(comps, current_targets(), REFERENCE_TARGETS)
    ala = _find(panel, "ALA (omega-3)")
    assert ala["target"]["kind"] == "AI (NIH ODS)" and ala["pct"] == pytest.approx((0.295 + 0.05) / 1.6 * 100, abs=0.1)
    assert ala["approx"] is True  # lamb's share is the 18:3 stand-in
    assert _find(panel, "DHA (omega-3)")["target"] is None  # no official target
    flav = _find(panel, "Flavan-3-ols")
    assert flav["has_data"] is False and flav["reference"]["low"] == 400
    ratio = panel["computed"]["omega6_to_omega3"]
    assert ratio["value"] == pytest.approx((0.944 + 0.41) / (0.295 + 0.862 + 0.393 + 1.104 + 0.05), abs=0.01)
    assert panel["computed"]["epa_dha"]["amount_mg"] == pytest.approx(1966)
    sel = _find(panel, "Selenium")
    assert [c["name"] for c in sel["contributions"]] == ["Lamb", "Salmon"]
    assert sel["coverage"] == {"with_data": 2, "of": 2}


def test_day_panel_flattens_to_ingredients(client):
    yid = client.post("/logs/ingredients", json={"name": "Yogurt", "kcal": 0, "source": "usda", "fdc_id": YOGURT}).json()["id"]
    lid = client.post("/logs/ingredients", json={"name": "Lamb", "kcal": 0, "source": "usda", "fdc_id": LAMB_LEAN}).json()["id"]
    mid = client.post("/logs/meals/from-ingredients", json={"name": "Plate", "components": [
        {"ingredient_id": yid, "quantity_g": 200}, {"ingredient_id": lid, "quantity_g": 100}]}).json()["id"]
    client.post("/logs/food", json={"date": "2026-11-05", "meal_type": "lunch", "meal_id": mid, "servings": 1})
    panel = client.get("/nutrition/day/2026-11-05").json()
    calcium = _find(panel, "Calcium")
    assert calcium["amount"] == pytest.approx(222 + 8)
    assert calcium["contributions"][0]["name"] == "Yogurt" and calcium["contributions"][0]["pct"] == pytest.approx(96.5, abs=0.1)
    assert calcium["pct"] == pytest.approx(23.0)
    # The old per-day endpoint now also reports ALA against its AI.
    old = client.get("/logs/nutrition/2026-11-05").json()
    assert any(m["nutrient"] == "ALA (omega-3)" for m in old["micros"])


def test_breakdown_mixes_library_usda_and_inline(client):
    lid = client.post("/logs/ingredients", json={"name": "Lamb", "kcal": 0, "source": "usda", "fdc_id": LAMB_LEAN}).json()["id"]
    panel = client.post("/nutrition/breakdown", json={"components": [
        {"ingredient_id": lid, "quantity_g": 50},
        {"fdc_id": SALMON, "quantity_g": 100, "name": "salmon"},
        {"name": "sauce", "kcal": 40, "source": "estimated"},
    ]}).json()
    assert _find(panel, "Energy")["amount"] == pytest.approx(95.5 + 208 + 40)
    assert [c["source"] for c in panel["components"]] == ["usda", "usda", "estimated"]


# --- backfill ----------------------------------------------------------------


def test_backfill_dry_run_then_apply(client):
    client.post("/logs/ingredients", json={"name": "Greek Yogurt", "kcal": 59, "protein_g": 10})  # legacy, no source
    client.post("/logs/ingredients", json={"name": "Zorbleberry jam", "kcal": 250})
    ing_id = api_module.get_logs_repo().conn.execute("SELECT id FROM ingredients WHERE name='Greek Yogurt'").fetchone()["id"]
    mid = client.post("/logs/meals/from-ingredients", json={"name": "Bowl", "components": [
        {"ingredient_id": ing_id, "quantity_g": 200}]}).json()["id"]

    dry = client.post("/logs/ingredients/backfill-usda?dry_run=true").json()
    assert dry["dry_run"] and [c["name"] for c in dry["changes"]] == ["Greek Yogurt"]
    assert dry["changes"][0]["kcal_before"] == 59 and dry["changes"][0]["kcal_after"] == 61
    assert any(s["name"] == "Zorbleberry jam" for s in dry["skipped"])
    assert api_module.get_logs_repo().get_ingredient(ing_id)["kcal"] == 59  # nothing written

    applied = client.post("/logs/ingredients/backfill-usda?dry_run=false").json()
    assert applied["meals_recomputed"] == ["Bowl"]
    row = api_module.get_logs_repo().get_ingredient(ing_id)
    assert (row["kcal"], row["source"], row["fdc_id"]) == (61, "usda", YOGURT)
    assert api_module.get_logs_repo().get_meal(mid)["kcal"] == 122
    again = client.post("/logs/ingredients/backfill-usda?dry_run=true").json()
    assert again["changes"] == []


# --- drop proposal -----------------------------------------------------------


def test_drop_ingredient_text_uses_usda_without_estimate(client, monkeypatch):
    def fail(*a, **k):
        raise AssertionError("estimate must not run when USDA matches")

    monkeypatch.setattr(api_module, "estimate_nutrition", fail)
    resp = client.post("/drop", data={"text": "ingredient: greek yogurt"}).json()
    entry = next(e for e in resp["entries"] if e["type"] == "ingredient_preset")
    assert entry["source"] == "usda" and entry["fdc_id"] == YOGURT and entry["kcal"] == 61
    assert entry["usda_candidates"][0]["fdc_id"] == YOGURT


# --- status / install --------------------------------------------------------


def test_db_status_and_install_job(client, monkeypatch):
    status = client.get("/nutrition/db/status").json()
    assert status["installed"] and status["summary"]["foods"] == 9
    ran = []
    monkeypatch.setattr(usda_fetch, "_job", {"state": "idle", "step": "", "error": None, "result": None})
    assert usda_fetch.start_install_job(runner=lambda log: ran.append(1) or {"ok": True})
    import time

    for _ in range(50):
        if usda_fetch.job_status()["state"] == "done":
            break
        time.sleep(0.02)
    assert ran == [1] and usda_fetch.job_status()["result"] == {"ok": True}


def test_install_skips_incomplete_foundation_release(tmp_path, monkeypatch):
    """fetch.install with downloads stubbed to local fixture copies: an
    incomplete newest release falls back to the next one."""
    import shutil
    import zipfile

    def zip_dir(src: Path, dest: Path, skip=()):
        with zipfile.ZipFile(dest, "w") as z:
            for p in src.iterdir():
                if p.name not in skip:
                    z.write(p, f"rel/{p.name}")
        return dest

    files = {
        "new.zip": lambda d: zip_dir(FIX / "foundation", d, skip=("food.csv", "food_nutrient.csv")),
        "old.zip": lambda d: zip_dir(FIX / "foundation", d),
        "sr_legacy.zip": lambda d: zip_dir(FIX / "sr_legacy", d),
    }
    monkeypatch.setattr(usda_fetch, "foundation_candidates", lambda: ["https://x/new.zip", "https://x/old.zip"])
    monkeypatch.setattr(usda_fetch, "SR_LEGACY_URL", "https://x/sr_legacy.zip")
    monkeypatch.setattr(usda_fetch, "_get", lambda url, dest, timeout=300: files[url.rsplit("/", 1)[-1]](dest))
    monkeypatch.setattr(shutil, "which", lambda name: None)  # no mdbtools → flavonoids skipped, said so
    result = usda_fetch.install(tmp_path / "n" / "usda.db", log=lambda m: None)
    assert result["foods"] == 9 and result["source_urls"] == ["https://x/old.zip", "https://x/sr_legacy.zip"]
    assert result["flavonoids"].startswith("skipped")


# --- chat lane ---------------------------------------------------------------


def test_chat_lane_scales_named_food(usda_db):
    block = chat_nutrition_block("how much selenium in 200g roast lamb leg")
    assert block and block.startswith("## Nutrition facts (USDA FoodData Central, per stated amounts)")
    assert "Selenium 60.2 mcg" in block  # 30.1 mcg/100 g × 2
    assert "Lamb, leg, whole" in block and "200 g" in block
    assert "% of target" in block


def test_chat_lane_silent_for_non_food_and_without_db(usda_db, monkeypatch):
    assert chat_nutrition_block("summarize my trip to Kyoto") is None
    assert chat_nutrition_block("ran 5 miles this morning") is None
    monkeypatch.setenv("QUINTACLE_USDA_DB", "/nonexistent/x.db")
    assert chat_nutrition_block("how much selenium in 200g roast lamb") is None


def test_chat_item_parsing():
    assert parse_items("how much selenium in 200g roast lamb") == [{"food": "roast lamb", "grams": 200.0, "assumed": False}]
    items = parse_items("2 eggs and 150 g of spinach")
    assert [(i["food"], i["grams"]) for i in items] == [("eggs", 100), ("spinach", 150.0)]
    assert parse_items("omega-3 in salmon?")[0] == {"food": "salmon", "grams": 100.0, "assumed": True,
                                                    "note": "no amount given — per 100 g"}
    assert parse_items("8 oz salmon")[0]["grams"] == pytest.approx(226.8)
