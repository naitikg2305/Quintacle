"""Faked regressions for two 2026-11-11 live-test journal-parse findings
(journal_cases.check_relative_date_* / presets_cases.check_meal_prefix_seeded):

1. "yesterday I spent $15 on lunch" @ 2026-11-10 came back undated from both
   providers -> relative dates are now resolved in code
   (nodes/journal/relative_dates.py) after the parse, overriding the model.
2. "meal: chicken rice bowl plus a greek yogurt bowl" with both meals saved
   linked one (local) or none (Claude) -> food entries naming 2+ saved meals
   split into one linked entry per meal (llm._link_meal_presets).

No model calls: parse_structured is faked at the journal llm module."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.nodes.journal import api as journal_api_module
from quintacle_core.nodes.journal import llm as journal_llm
from quintacle_core.nodes.journal.normalize import meals_named_in
from quintacle_core.nodes.journal.relative_dates import apply_relative_dates, find_relative_dates

REF = date(2026, 11, 10)  # a Tuesday
MEALS = [{"id": 1, "name": "Chicken rice bowl", "kcal": 650}, {"id": 2, "name": "Greek yogurt bowl", "kcal": 320}]


class _Result:
    def __init__(self, parsed):
        self.parsed = parsed
        self.provider_used = "local"


def _fake_parse(entries, model_dates: dict[int, str] | None = None):
    """parse_structured stand-in: the main call returns `entries` (fresh
    copies each call), the date pass returns `model_dates`, the finance-kind
    pass returns nothing."""

    def fake(system, user, schema, **kwargs):
        if schema is journal_llm.ParsedJournal:
            return _Result(journal_llm.ParsedJournal(entries=[e.model_copy(deep=True) for e in entries]))
        if schema is journal_llm._DateResolutions:
            res = [journal_llm._DateResolution(index=i, entry_date=d) for i, d in (model_dates or {}).items()]
            return _Result(journal_llm._DateResolutions(resolutions=res))
        if schema is journal_llm._FinanceKindResolutions:
            return _Result(journal_llm._FinanceKindResolutions(resolutions=[]))
        raise AssertionError(f"unexpected schema {schema}")

    return fake


def _finance(amount=15, **kw):
    return journal_llm.FinanceEntry(type="finance", amount=amount, **kw)


def _food(description, meal_id=None, kcal=500, meal_type="lunch"):
    return journal_llm.FoodEntry(type="food", meal_type=meal_type, description=description, meal_id=meal_id, estimated_kcal=kcal)


# --- relative-date phrases ---------------------------------------------------

@pytest.mark.parametrize("text,want", [
    ("yesterday I spent $15", "2026-11-09"),
    ("the day before yesterday", "2026-11-08"),
    ("day before yesterday", "2026-11-08"),
    ("today", "2026-11-10"),
    ("this morning", "2026-11-10"),
    ("last night", "2026-11-09"),
    ("last Monday", "2026-11-09"),
    ("last tuesday", "2026-11-03"),  # same weekday as the reference -> a week back
    ("last Sunday", "2026-11-08"),
    ("3 days ago", "2026-11-07"),
    ("two days ago", "2026-11-08"),
    ("a day ago", "2026-11-09"),
])
def test_find_relative_dates(text, want):
    found = find_relative_dates(text, REF)
    assert [d.isoformat() for _, _, d in found] == [want]


@pytest.mark.parametrize("text", [
    "woke up 7:10 after 7h sleep, felt great 8/10",  # the old Aug-10 misread
    "scored 8-10 on the quiz",
    "last week was busy",
    "next friday",
    "",
])
def test_no_relative_phrase_no_date(text):
    assert find_relative_dates(text, REF) == []


def test_single_phrase_dates_every_entry():
    entries = [{"type": "finance", "amount": 15, "merchant": "", "notes": "", "entry_date": None},
               {"type": "food", "description": "lunch", "entry_date": None},
               {"type": "todo", "title": "x", "due_date": None}]
    apply_relative_dates(entries, "yesterday I spent $15 on lunch", REF)
    assert [e.get("entry_date") for e in entries[:2]] == ["2026-11-09", "2026-11-09"]
    assert "entry_date" not in entries[2]  # todos keep due_date, untouched


def test_dates_follow_their_own_clause_and_carry_forward():
    entries = [{"type": "exercise", "exercise_name": "running", "notes": "", "entry_date": None},
               {"type": "food", "description": "burrito", "entry_date": None},
               {"type": "activity", "description": "read a book", "entry_date": None}]
    apply_relative_dates(entries, "Yesterday I went running and had a burrito. Today I read a book", REF)
    assert [e["entry_date"] for e in entries] == ["2026-11-09", "2026-11-09", "2026-11-10"]


def test_own_clause_overrides_model_but_spillover_never_clobbers():
    # own clause: the model's wrong date is overridden
    entries = [{"type": "finance", "amount": 15, "notes": "lunch", "entry_date": "2026-11-01"}]
    apply_relative_dates(entries, "yesterday I spent $15 on lunch", REF)
    assert entries[0]["entry_date"] == "2026-11-09"
    # spill-over (entry sits in an undated clause before the phrase): only
    # fills an undated entry, keeps a date the model resolved elsewhere
    entries = [{"type": "food", "description": "pizza", "entry_date": None},
               {"type": "activity", "description": "concert", "entry_date": "2026-08-03"},
               {"type": "finance", "amount": 9, "notes": "", "entry_date": None}]
    apply_relative_dates(entries, "pizza for dinner. concert on August 3rd. yesterday $9 parking", REF)
    assert [e["entry_date"] for e in entries] == ["2026-11-09", "2026-08-03", "2026-11-09"]


def test_parse_journal_dump_resolves_yesterday_when_model_leaves_it_none(monkeypatch):
    monkeypatch.setattr(journal_llm, "parse_structured", _fake_parse([_finance(15, notes="lunch"), _food("lunch")]))
    entries = journal_llm.parse_journal_dump("yesterday I spent $15 on lunch", reference_date=REF)
    assert [e.entry_date for e in entries] == ["2026-11-09", "2026-11-09"]


def test_parse_journal_dump_overrides_a_wrong_model_date(monkeypatch):
    monkeypatch.setattr(journal_llm, "parse_structured", _fake_parse([_finance(15)], model_dates={0: "2026-11-08"}))
    entries = journal_llm.parse_journal_dump("yesterday I spent $15 on lunch", reference_date=REF)
    assert entries[0].entry_date == "2026-11-09"


def test_full_day_text_stays_on_day(monkeypatch):
    text = ("woke up 7:10 after 7h sleep, had the chicken rice bowl for lunch, did push day, "
            "felt great 8/10, paid $42 for groceries at Trader Joe's, read 30 pages of Dune")
    monkeypatch.setattr(journal_llm, "parse_structured", _fake_parse([_finance(42, merchant="Trader Joe's"), _food("chicken rice bowl")]))
    entries = journal_llm.parse_journal_dump(text, MEALS, reference_date=REF)
    assert all(e.entry_date is None for e in entries)


# --- meal preset linking ------------------------------------------------------

def test_meals_named_in():
    assert [m["id"] for m in meals_named_in("chicken rice bowl plus a greek yogurt bowl", MEALS)] == [1, 2]
    assert [m["id"] for m in meals_named_in("greek yoghurt bowl and 2 chicken rice bowls", MEALS)] == [2, 1]
    assert [m["id"] for m in meals_named_in("Chicken Rice Bowl", MEALS)] == [1]
    assert meals_named_in("rice bowl", MEALS) == []
    assert meals_named_in("burrito", MEALS) == []
    nested = [{"id": 1, "name": "Rice bowl"}, {"id": 2, "name": "Chicken rice bowl"}]
    assert [m["id"] for m in meals_named_in("a chicken rice bowl", nested)] == [2]


@pytest.mark.parametrize("model_entry", [
    _food("chicken rice bowl", meal_id=1),  # local: first meal only
    _food("chicken rice bowl plus a greek yogurt bowl", meal_id=None, kcal=970),  # Claude: none
])
def test_meal_prefix_two_presets_split(monkeypatch, model_entry):
    monkeypatch.setattr(journal_llm, "parse_structured", _fake_parse([model_entry]))
    entries = journal_llm.parse_journal_dump(
        "chicken rice bowl plus a greek yogurt bowl", MEALS, reference_date=REF, forced_type="food"
    )
    assert [(e.type, e.meal_id, e.description, e.estimated_kcal) for e in entries] == [
        ("food", 1, "Chicken rice bowl", 0), ("food", 2, "Greek yogurt bowl", 0)]
    assert all(e.meal_type == "lunch" for e in entries)


def test_unprefixed_description_naming_two_presets_splits(monkeypatch):
    monkeypatch.setattr(journal_llm, "parse_structured", _fake_parse([
        _food("chicken rice bowl and greek yogurt bowl"), _finance(12, merchant="Chipotle")]))
    entries = journal_llm.parse_journal_dump("had chicken rice bowl and greek yogurt bowl, $12 chipotle", MEALS, reference_date=REF)
    assert [(e.type, getattr(e, "meal_id", None)) for e in entries] == [("food", 1), ("food", 2), ("finance", None)]


def test_single_named_preset_gets_meal_id_and_no_duplicates(monkeypatch):
    monkeypatch.setattr(journal_llm, "parse_structured", _fake_parse([
        _food("the chicken rice bowl", meal_id=None), _food("greek yogurt bowl", meal_id=2, meal_type="breakfast"),
        _food("burrito")]))
    entries = journal_llm.parse_journal_dump("x", MEALS, reference_date=REF)
    assert [e.meal_id for e in entries] == [1, 2, None]
    assert entries[0].estimated_kcal == 500  # untouched; only the link is added


def test_split_skips_meal_another_entry_already_links(monkeypatch):
    monkeypatch.setattr(journal_llm, "parse_structured", _fake_parse([
        _food("chicken rice bowl and greek yogurt bowl"), _food("greek yogurt bowl", meal_id=2)]))
    entries = journal_llm.parse_journal_dump("x", MEALS, reference_date=REF)
    assert sorted(e.meal_id for e in entries) == [1, 2]


# --- through the real endpoints --------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api_module, "maybe_structure_experience", lambda *a, **k: None)
    monkeypatch.setattr(api_module, "maybe_structure_person_mention", lambda *a, **k: None)
    monkeypatch.setattr(journal_api_module, "maybe_structure_experience", lambda *a, **k: None)
    monkeypatch.setattr(journal_api_module, "maybe_structure_person_mention", lambda *a, **k: None)
    return TestClient(api_module.create_app())


def test_yesterday_through_drop_and_journal_parse(client, monkeypatch):
    monkeypatch.setattr(journal_llm, "parse_structured", _fake_parse([_finance(15), _food("lunch")]))
    r = client.post("/drop", data={"text": "yesterday I spent $15 on lunch", "reference_date": "2026-11-10"})
    assert r.status_code == 200, r.text
    dated = [e for e in r.json()["entries"] if "entry_date" in e]
    assert dated and all(e["entry_date"] == "2026-11-09" for e in dated), r.json()

    r = client.post("/journal/2026-11-10/parse", content=b"yesterday I spent $15 on lunch",
                    headers={"Content-Type": "text/plain"})
    assert r.status_code == 200, r.text
    dated = [e for e in r.json()["entries"] if "entry_date" in e]
    assert dated and all(e["entry_date"] == "2026-11-09" for e in dated), r.json()


def test_meal_prefix_drop_links_both_seeded_meals(client, monkeypatch):
    ids = {}
    for name, kcal in [("Chicken rice bowl", 650), ("Greek yogurt bowl", 320)]:
        r = client.post("/logs/meals", json={"name": name, "kcal": kcal, "protein_g": 30, "carbs_g": 40, "fat_g": 10})
        assert r.status_code == 200, r.text
    ids = {m["name"]: m["id"] for m in client.get("/logs/meals").json()}
    monkeypatch.setattr(journal_llm, "parse_structured", _fake_parse([_food("chicken rice bowl", meal_id=ids["Chicken rice bowl"])]))
    r = client.post("/drop", data={"text": "meal: chicken rice bowl plus a greek yogurt bowl"})
    assert r.status_code == 200, r.text
    food = [e for e in r.json()["entries"] if e["type"] == "food"]
    assert {e["meal_id"] for e in food} == set(ids.values()), food
