"""Faked regressions for the 2026-11-11 live-test findings (presets_cases /
finance_cases): prefix lanes honour `provider`, the ingredient: name is the
food, a recipe made from SAVED MEALS reuses them, and unprefixed income
becomes an income entry (never a same-amount expense). No model calls —
every extractor is monkeypatched at the api module."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.nodes.drop_router import ingredient_name_from_text, looks_like_income, parse_income_natural
from quintacle_core.nodes.journal.llm import FinanceEntry, FoodEntry
from quintacle_core.nodes.logs.meal_composer import ComposedComponent, MealCompositionSuggestion, resolve_composition
from quintacle_core.nodes.logs.nutrition_llm import NutritionEstimate


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


def _comp(name, grams=300, kcal=999):
    return ComposedComponent(name=name, quantity_g=grams, protein_g=99, carbs_g=99, fat_g=99, fiber_g=9, kcal=kcal)


def _seed_meals(c):
    for name, kcal, p, cbs, f in [("Chicken rice bowl", 650, 45, 70, 15), ("Greek yogurt bowl", 320, 25, 35, 8)]:
        assert c.post("/logs/meals", json={"name": name, "kcal": kcal, "protein_g": p, "carbs_g": cbs, "fat_g": f}).status_code == 200


# --- Bug 2: ingredient name -------------------------------------------------

@pytest.mark.parametrize("text,name", [
    ("Fage 0% greek yogurt, per 170g: 90 kcal, 18g protein, 5g carbs, 0g fat", "Fage 0% greek yogurt"),
    ("greek yogurt macros per 100g: 59 kcal", "greek yogurt"),
    ("basmati rice, cooked, per 100g: 130 kcal", "basmati rice, cooked"),
    ("Quest bar 60g 200 kcal 21g protein", "Quest bar"),
    ("2% milk 244g: 122 kcal", "2% milk"),
    ("lamb", "lamb"),
    ("Nutrition facts: calories 120", ""),
])
def test_ingredient_name_from_text(text, name):
    assert ingredient_name_from_text(text) == name


# --- Bug 1 + 2: ingredient: prefix -------------------------------------------

def test_ingredient_prefix_names_the_food_and_passes_provider(client, monkeypatch):
    calls = []

    def nutrition(text, provider=None):
        calls.append(("nutrition", provider))
        return NutritionEstimate(basis_amount_g=170, protein_g=18, carbs_g=5, fat_g=0, fiber_g=0, kcal=90, micros=[])

    def usda(name, basis=100, provider=None):
        calls.append(("usda", name, provider))
        return None

    monkeypatch.setattr(api_module, "estimate_nutrition", nutrition)
    monkeypatch.setattr(api_module, "usda_proposal", usda)
    r = client.post("/drop", data={
        "text": "ingredient: Fage 0% greek yogurt, per 170g: 90 kcal, 18g protein, 5g carbs, 0g fat", "provider": "cloud",
    })
    assert r.status_code == 200, r.text
    e = next(x for x in r.json()["entries"] if x["type"] == "ingredient_preset")
    assert e["suggested_name"] == "Fage 0% greek yogurt"
    assert e["source"] == "label" and e["kcal"] == 90 and e["basis_amount_g"] == 170
    assert ("nutrition", "cloud") in calls
    assert ("usda", "Fage 0% greek yogurt", "cloud") in calls


# --- Bug 1 + 3: recipe: prefix from saved meals ------------------------------

def test_recipe_from_saved_meals_reuses_them_and_passes_provider(client, monkeypatch):
    _seed_meals(client)
    seen = {}

    def meal(description, known, provider=None, known_meals=None):
        seen["provider"] = provider
        seen["meals"] = [m["name"] for m in known_meals or []]
        return MealCompositionSuggestion(meal_name="Combo", components=[_comp("chicken rice bowl"), _comp("Greek Yogurt Bowl", 200)])

    monkeypatch.setattr(api_module, "suggest_meal_composition", meal)
    r = client.post("/drop", data={"text": "recipe: chicken rice bowl plus a greek yogurt bowl", "provider": "cloud"})
    assert r.status_code == 200, r.text
    e = next(x for x in r.json()["entries"] if x["type"] == "meal_composition")
    assert seen == {"provider": "cloud", "meals": ["Chicken rice bowl", "Greek yogurt bowl"]}
    comps = e["components"]
    assert [c["name"] for c in comps] == ["Chicken rice bowl", "Greek yogurt bowl"]
    assert all(c["is_new"] is False and c["meal_id"] and c["servings"] == 1.0 for c in comps)
    # One serving each at the meals' OWN numbers; the model's 999 guess is gone.
    assert [c["kcal"] for c in comps] == [650, 320]
    assert e["totals"]["kcal"] == 970 and e["totals"]["protein_g"] == 70

    # Save path: {meal_id, servings} expands — flat meals become one reusable
    # one-serving ingredient each (created once), totals stay exact.
    payload = {"name": "Combo", "components": [
        {"meal_id": comps[0]["meal_id"], "servings": 1, "quantity_g": comps[0]["quantity_g"]},
        {"meal_id": comps[1]["meal_id"], "servings": 0.5, "quantity_g": comps[1]["quantity_g"] / 2},
    ]}
    saved = client.post("/logs/meals/from-ingredients", json=payload)
    assert saved.status_code == 200, saved.text
    combo = next(m for m in client.get("/logs/meals").json() if m["name"] == "Combo")
    assert combo["kcal"] == pytest.approx(650 + 160) and combo["protein_g"] == pytest.approx(45 + 12.5)
    names = sorted(i["name"] for i in client.get("/logs/ingredients").json())
    assert names == ["Chicken rice bowl", "Greek yogurt bowl"]
    # Saving a second recipe reuses those ingredients — no duplicates.
    assert client.post("/logs/meals/from-ingredients", json={**payload, "name": "Combo 2"}).status_code == 200
    assert len(client.get("/logs/ingredients").json()) == 2


def test_composed_saved_meal_expands_into_its_ingredients(client):
    ing = client.post("/logs/ingredients", json={"name": "Oats", "basis_amount_g": 100, "kcal": 380, "protein_g": 13}).json()
    base = client.post("/logs/meals/from-ingredients", json={"name": "Oat bowl", "components": [{"ingredient_id": ing["id"], "quantity_g": 80}]})
    assert base.status_code == 200, base.text
    r = client.post("/logs/meals/from-ingredients", json={"name": "Double oats", "components": [
        {"meal_id": base.json()["id"], "servings": 2, "quantity_g": 160},
    ]})
    assert r.status_code == 200, r.text
    assert r.json()["components"] == [{"ingredient_id": ing["id"], "ingredient_name": "Oats", "quantity_g": 160}]
    assert len(client.get("/logs/ingredients").json()) == 1


def test_resolve_composition_meal_match_and_ingredient_precedence():
    ingredients = [{"id": 1, "name": "Greek yogurt bowl", "basis_amount_g": 200, "protein_g": 20, "carbs_g": 30,
                    "fat_g": 5, "fiber_g": 0, "kcal": 250}]
    meals = [{"id": 7, "name": "Chicken rice bowl", "protein_g": 45, "carbs_g": 70, "fat_g": 15, "fiber_g": 0, "kcal": 650,
              "serving_g": 420},
             {"id": 8, "name": "Greek yogurt bowl", "protein_g": 25, "carbs_g": 35, "fat_g": 8, "fiber_g": 0, "kcal": 320}]
    s = MealCompositionSuggestion(meal_name="x", components=[_comp("Chicken Rice Bowl"), _comp("greek yogurt bowl", 200)])
    out = resolve_composition(s, ingredients, known_meals=meals, use_usda=False)
    meal_c, ing_c = out["components"]
    assert meal_c["meal_id"] == 7 and meal_c["quantity_g"] == 420 and meal_c["kcal"] == 650 and meal_c["is_new"] is False
    assert ing_c["ingredient_id"] == 1 and "meal_id" not in ing_c  # ingredients match first


# --- Bug 4: unprefixed income ----------------------------------------------

@pytest.mark.parametrize("text", [
    "got paid $3,200 from Minfy today",
    "paycheck came in, $2,400",
    "received $500 from Acme for the logo job",
    "client invoice was paid, $1,200",
    "direct deposit of $1,850 hit",
])
def test_income_gate_positive(text):
    assert looks_like_income(text)


@pytest.mark.parametrize("text", [
    "spent $200 of my salary on shoes",
    "I paid $50 for dinner",
    "my salary is great",
    "got paid today",  # no amount
    "paid my AWS invoice $120",
    "bought 10 shares of AAPL at $150",
])
def test_income_gate_negative(text):
    assert not looks_like_income(text)


def test_parse_income_natural_source_and_yesterday():
    e = parse_income_natural("got paid $3,200 from Minfy today", date(2026, 11, 11))
    assert e == {"type": "income", "amount": 3200.0, "source": "Minfy", "kind": "other", "notes": "", "entry_date": None}
    assert parse_income_natural("received $500 from Acme yesterday", date(2026, 11, 11))["entry_date"] == "2026-11-10"


def test_unprefixed_income_is_income_never_a_same_amount_expense(client, monkeypatch):
    monkeypatch.setattr(api_module, "parse_journal_dump", lambda *a, **k: [
        FinanceEntry(type="finance", amount=3200, merchant="Minfy"),
        FinanceEntry(type="finance", amount=12, merchant="Chipotle"),
        FoodEntry(type="food", meal_type="lunch", description="burrito", estimated_kcal=900),
    ])
    r = client.post("/drop", data={"text": "got paid $3,200 from Minfy today, then $12 Chipotle burrito"})
    assert r.status_code == 200, r.text
    entries = r.json()["entries"]
    assert entries[0]["type"] == "income" and entries[0]["amount"] == 3200 and entries[0]["source"] == "Minfy"
    finance = [e for e in entries if e["type"] == "finance"]
    assert [f["amount"] for f in finance] == [12]  # the real expense stays
    assert any(e["type"] == "food" for e in entries)


def test_plain_expense_text_gets_no_income(client, monkeypatch):
    monkeypatch.setattr(api_module, "parse_journal_dump", lambda *a, **k: [FinanceEntry(type="finance", amount=50, merchant="Safeway")])
    r = client.post("/drop", data={"text": "I paid $50 for groceries"})
    assert [e["type"] for e in r.json()["entries"]][:1] == ["finance"]
    assert all(e["type"] != "income" for e in r.json()["entries"])
