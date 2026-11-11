"""Graph-linking expectations for the owner's LOGS + FINANCE categories
(docs/testing/graph-linking-38-categories.md, DRAFT 2026-11-11):

  #3 Food, workout set · #5 Financial goals · #17 Plan a meal ·
  #24 Discuss a financial plan · #25 How much I make right now ·
  #26 Subscriptions · #27 Random expense · #28 Random food drop ·
  #29 Reflection dashboard · #33 Monthly budgeting

Each test performs the SAME save the app performs: POST /drop (models faked
at the llm_dispatch seam, so every deterministic post-pass — meal-preset
linking, routine expansion, the income gate — really runs), then the review
→ Save step as frontend/lib/entries.ts does it (commitEntry per proposal,
graphIdFor on each response, then POST /graph/event for a batch of 2+).

Expectations come from the spec, never from what the code happens to do.
Where the code doesn't do what the spec says, the assertion stays and the
test is `xfail(strict=True)` with the gap named. Sandboxed tmp DATA_DIR,
seeded registries (meals, a routine, ingredients, a person, an account) —
CLAUDE.md's entity-grounded rule. No real model is ever reached.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.llm_dispatch as llm_dispatch
from quintacle_core import clock, retrieval
from quintacle_core.graph import get_graph_store, neighborhood
from quintacle_core.nodes.journal.llm import (
    ExerciseEntry,
    FinanceEntry,
    FoodEntry,
    ParsedJournal,
    _DateResolutions,
    _FinanceKindResolution,
    _FinanceKindResolutions,
)
from quintacle_core.nodes.kb import chat
from quintacle_core.nodes.kb.api import get_store as get_kb_store
from quintacle_core.nodes.logs.meal_composer import ComposedComponent, MealCompositionSuggestion

TODAY = date(2026, 11, 11)  # a Wednesday, Eastern
D = TODAY.isoformat()


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _fresh_retrieval():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def models(monkeypatch):
    """The local model, faked at llm_dispatch's backend seam: canned answers
    by schema class name; cloud raises (owner default is local-first)."""
    answers: dict[str, object] = {}
    calls: list[str] = []

    def fake_local(system, user_content, output_format, max_tokens):
        calls.append(output_format.__name__)
        answer = answers.get(output_format.__name__)
        if answer is None:
            raise llm_dispatch.LocalParseError(f"no canned answer for {output_format.__name__}")
        return answer(user_content) if callable(answer) else answer

    def no_cloud(*a, **k):
        raise AssertionError("cloud was called in a faked, local-first test")

    monkeypatch.setattr(llm_dispatch, "_parse_local", fake_local)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", no_cloud)
    return answers, calls


@pytest.fixture
def client(tmp_path, monkeypatch, models):
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 11, 11, 20, 30, tzinfo=clock.TIME_ZONE))
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    # The additive experience/person checks are other categories' business;
    # here they'd only add unrelated model calls.
    monkeypatch.setattr(api_module, "maybe_structure_experience", lambda *a, **k: None)
    monkeypatch.setattr(api_module, "maybe_structure_person_mention", lambda *a, **k: None)
    c = TestClient(api_module.create_app())
    c.data_dir = tmp_path
    _seed(c)
    return c


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def _seed(c):
    """Entity-grounded registries the owner actually has (shapes, not his data)."""
    c.meals = {}
    for name, kcal, p, cbs, f in [
        ("Chicken rice bowl", 650, 45, 70, 15),
        ("Chipotle bowl", 800, 48, 85, 28),
        ("Greek yogurt bowl", 320, 25, 35, 8),
    ]:
        c.meals[name] = _ok(c.post("/logs/meals", json={"name": name, "kcal": kcal, "protein_g": p, "carbs_g": cbs, "fat_g": f}))["id"]
    _ok(c.post("/logs/routines", json={"name": "Pull day", "exercises": ["Pull-ups", "Barbell row", "Bicep curl"]}))
    c.ingredients = {}
    for name, kcal, p, cbs, f in [("Basmati rice", 130, 2.7, 28, 0.3), ("Chicken breast", 165, 31, 0, 3.6)]:
        c.ingredients[name] = _ok(
            c.post("/logs/ingredients", json={"name": name, "basis_amount_g": 100, "kcal": kcal, "protein_g": p, "carbs_g": cbs, "fat_g": f})
        )["id"]
    _ok(c.post("/people", json={"name": "Priya Shah", "category": "friend", "how_met": "college"}))
    _ok(c.post("/finance/accounts", json={"name": "Ally Savings", "account_type": "savings", "institution": "Ally", "balance": 12000, "as_of": D}))


# ----------------------------------------------------- the app's Save (entries.ts port)


def _graph_id_for(entry: dict, result: dict) -> str | None:
    """frontend/lib/entries.ts graphIdFor, for the types these categories save."""
    t = entry["type"]
    if t in ("food", "exercise", "activity", "substance", "body_stat"):
        return f"{t}:{result['id']}" if "id" in result else None
    if t == "finance":
        return f"expense:{result['id']}" if "id" in result else None
    if t == "income":
        return f"income:{result['id']}" if "id" in result else None
    if t == "kb_entry":
        return f"note:{result['folder']}/{result['slug']}" if "folder" in result and "slug" in result else None
    if t == "meal_composition":
        return f"meal:{result['id']}" if "id" in result else None
    return None


def _commit_entry(c, day: str, entry: dict) -> dict:
    """frontend/lib/entries.ts commitEntry, for the types these categories save."""
    t = entry["type"]
    when = entry.get("entry_date") or day
    if t == "food":
        if entry.get("meal_id"):
            body = {"date": when, "meal_type": entry["meal_type"], "meal_id": entry["meal_id"], "notes": entry["description"]}
        else:
            body = {"date": when, "meal_type": entry["meal_type"], "freeform_kcal": entry["estimated_kcal"], "notes": entry["description"]}
        return _ok(c.post("/logs/food", json={"servings": 1, **body}))
    if t == "exercise":
        return _ok(c.post("/logs/exercise", json={"date": when, "exercise_name": entry["exercise_name"], "sets": entry["sets"], "notes": entry.get("notes", "")}))
    if t == "finance":
        return _ok(c.post("/logs/expenses", json={
            "date": when, "amount": entry["amount"], "merchant": entry["merchant"], "category": entry["category"],
            "notes": entry["notes"], "kind": entry["kind"],
        }))
    if t == "income":
        return _ok(c.post("/logs/income", json={
            "date": when, "amount": entry["amount"], "source": entry["source"], "kind": entry["kind"], "notes": entry["notes"],
        }))
    if t == "kb_entry":
        return _ok(c.post("/kb/entries", json={"folder": entry["folder"], "title": entry["title"], "content": entry["content"], "links": entry.get("links")}))
    if t == "meal_composition":
        comps = []
        for comp in entry["components"]:
            if comp.get("ingredient_id") is not None:
                comps.append({"ingredient_id": comp["ingredient_id"], "quantity_g": comp["quantity_g"]})
            elif comp.get("meal_id") is not None:
                comps.append({"meal_id": comp["meal_id"], "servings": comp.get("servings") or 1, "quantity_g": comp["quantity_g"]})
            else:
                comps.append({k: comp.get(k) for k in ("name", "quantity_g", "basis_amount_g", "protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")})
        return _ok(c.post("/logs/meals/from-ingredients", json={"name": entry["meal_name"], "notes": "", "components": comps}))
    raise AssertionError(f"this test file doesn't save {t}")


def save_all(c, day: str, entries: list[dict]) -> list[str | None]:
    """commitDropEntries: every proposal committed, then ONE /graph/event for
    the batch when it has 2+ graph-addressable members (linkBatchAsEvent)."""
    members = [_graph_id_for(e, _commit_entry(c, day, e)) for e in entries]
    real = [m for m in members if m is not None]
    if len(real) >= 2:
        _ok(c.post("/graph/event", json={"members": real, "date": day}))
    return members


def drop(c, text: str) -> list[dict]:
    return _ok(c.post("/drop", data={"text": text, "reference_date": D}))["entries"]


# --------------------------------------------------------------------- graph helpers


def _edges(kind: str | None = None) -> list[dict]:
    return [e for e in get_graph_store().all() if kind in (None, e["kind"])]


def _events_of(member: str) -> set[str]:
    return {e["target_id"] for e in _edges("part_of") if e["source_id"] == member and e["target_id"].startswith("event:")}


def _assert_one_shared_event(members: list[str]) -> str:
    events = [_events_of(m) for m in members]
    assert all(len(ev) == 1 for ev in events), f"each member must be part_of exactly one event: {dict(zip(members, events))}"
    assert len(set().union(*events)) == 1, f"members are part_of DIFFERENT events: {dict(zip(members, events))}"
    return next(iter(events[0]))


def _parsed(*entries) -> ParsedJournal:
    return ParsedJournal(entries=list(entries))


def _kinds(*pairs) -> _FinanceKindResolutions:
    return _FinanceKindResolutions(resolutions=[_FinanceKindResolution(index=i, kind=k) for i, k in pairs])


def _rows(c, table: str) -> list[sqlite3.Row]:
    from quintacle_core.nodes.logs.api import get_repo

    return get_repo().conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()  # noqa: S608 — fixed names


def _capture_chat(monkeypatch) -> list[str | None]:
    captured: list[str | None] = []

    def runner(model, messages, kb_text):
        captured.append(kb_text)
        return "stub-reply"

    for name in ("_run_anthropic", "_run_openai", "_run_bedrock", "_run_local"):
        monkeypatch.setattr(chat, name, runner)
    return captured


def _snapshot(c) -> dict:
    """Everything persistent: every SQLite table's row count + every file's
    content hash under the data dir (the db files themselves excluded — their
    rows are counted instead)."""
    from quintacle_core.nodes.logs.api import get_repo

    conn = get_repo().conn
    tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    counts = {t: conn.execute(f'SELECT COUNT(*) AS n FROM "{t}"').fetchone()["n"] for t in tables}  # noqa: S608
    files = {}
    for p in sorted(c.data_dir.rglob("*")):
        if p.is_file() and ".db" not in p.name:
            files[str(p.relative_to(c.data_dir))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"tables": counts, "files": files}


# =========================================================================== #3


def test_3_food_and_workout_drop_is_one_event_with_meal_and_routine_matched(client, models):
    """#3: "lunch was my chicken rice bowl, then pull day at the gym" — the
    known meal is matched by meal_id (not a fresh freeform/duplicate meal),
    the known routine is matched by name (its exercises, no 'pull day' row,
    no new routine), and every row from the drop is part_of ONE event."""
    answers, _ = models
    # What a small local model typically returns: the meal unlinked, the
    # routine as one header entry — the deterministic post-passes fix both.
    answers["ParsedJournal"] = _parsed(
        FoodEntry(type="food", meal_type="lunch", description="chicken rice bowl", meal_id=None, estimated_kcal=640),
        ExerciseEntry(type="exercise", exercise_name="pull day", sets=[]),
    )
    meals_before = len(_rows(client, "meals"))
    routines_before = client.get("/logs/routines").json()

    entries = drop(client, "lunch was my chicken rice bowl, then pull day at the gym")

    foods = [e for e in entries if e["type"] == "food"]
    exercises = [e for e in entries if e["type"] == "exercise"]
    assert len(foods) == 1 and foods[0]["meal_id"] == client.meals["Chicken rice bowl"]
    assert [e["exercise_name"] for e in exercises] == ["Pull-ups", "Barbell row", "Bicep curl"]
    assert not any(e["type"] in ("meal_composition", "workout_routine") for e in entries)  # ✗ no duplicate preset proposed

    members = save_all(client, D, entries)
    assert all(members)
    _assert_one_shared_event(members)

    # Matched, not duplicated.
    assert len(_rows(client, "meals")) == meals_before
    assert client.get("/logs/routines").json() == routines_before
    food_row = _rows(client, "food_log")[-1]
    assert food_row["meal_id"] == client.meals["Chicken rice bowl"]
    assert "pull day" not in {r["exercise_name"].lower() for r in _rows(client, "exercise_sets")}  # ✗ no header row
    # The logged exercise names ARE the routine's exercise nodes in /graph.
    graph = client.get("/graph").json()
    includes = {e["target"] for e in graph["edges"] if e["source"] == "routine:Pull day" and e["kind"] == "includes"}
    assert includes == {f"exercise:{r['exercise_name']}" for r in _rows(client, "exercise_sets")}


def test_3_numeric_rows_are_not_keyword_linked(client, models):
    """#3 ✗ (how-linking-works): numeric logs are never keyword-linked — a
    food note naming a known person makes no mentions_person edge."""
    answers, _ = models
    answers["ParsedJournal"] = _parsed(
        FoodEntry(type="food", meal_type="dinner", description="pasta Priya Shah made", estimated_kcal=700),
        ExerciseEntry(type="exercise", exercise_name="Pull-ups", sets=[{"reps": 8}, {"reps": 6}]),
    )
    members = save_all(client, D, drop(client, "dinner was pasta Priya Shah made, did pull-ups 8 and 6"))
    assert not [e for e in _edges("mentions_person") if e["source_id"] in members]


# =========================================================================== #5


def _goals_note(client):
    # The Save of a sorted "financial goals" drop — a kb_entry under Finance.
    entry = {
        "type": "kb_entry",
        "folder": "Organisation/Finance/Goals",
        "title": "Financial goals 2027",
        "content": (
            "Emergency fund: grow Ally Savings to $20,000 by June 2027.\n"
            "Max the Roth IRA ($7,000).\nPay Priya Shah back the $500 from the Lisbon trip."
        ),
        "links": [],
    }
    [member] = save_all(client, D, [entry])
    return member


def test_5_financial_goals_note_links_the_named_person(client):
    """#5: a finance-goals note → the people it names (mentions_person)."""
    note = _goals_note(client)
    targets = {e["target_id"] for e in _edges("mentions_person") if e["source_id"] == note}
    assert any(t.endswith("/profile") and "priya" in t for t in targets), targets


@pytest.mark.xfail(
    strict=True,
    reason="GAP: accounts aren't link candidates — graph_capture.mention_candidates() only offers people + "
    "experiences, so naming 'Ally Savings' (finance/accounts.py, Organisation/Finance/Accounts) makes no edge",
)
def test_5_financial_goals_note_links_the_named_account(client):
    """#5: a finance-goals note → the account it names (Ally Savings)."""
    note = _goals_note(client)
    account = next(n for n in get_kb_store().notes_index() if n["title"] == "Ally Savings")
    account_id = f"note:{account['folder']}/{account['slug']}"
    linked = {e["target_id"] for e in _edges() if e["source_id"] == note} | {e["source_id"] for e in _edges() if e["target_id"] == note}
    assert account_id in linked


def test_5_financial_goals_are_findable_from_a_finance_question(client, monkeypatch):
    """#5: "findable from finance questions" — asking chat about savings
    goals retrieves the goals note into the model's context."""
    note = _goals_note(client)
    captured = _capture_chat(monkeypatch)
    _ok(client.post("/kb/chat", json={"messages": [{"role": "user", "content": "what are my savings goals for the emergency fund?"}]}))
    ctx = captured[-1] or ""
    assert note in ctx or "Financial goals 2027" in ctx
    assert "$20,000" in ctx


# =========================================================================== #17


def test_17_plan_a_meal_references_existing_ingredients_and_saved_meals(client, models, monkeypatch):
    """#17: "recipe: chicken + rice plate with a greek yogurt bowl" — the
    meal preset is made_of its ingredients (meal_ingredients → /graph
    made_of edges), known ingredients are referenced not re-created, and a
    saved meal used inside it is reused (no duplicate meal; at most ONE
    ingredient standing for it, never re-forked on the next recipe)."""

    def suggest(description, known, provider=None, known_meals=None):
        return MealCompositionSuggestion(meal_name="Post-workout plate", components=[
            ComposedComponent(name="basmati rice", quantity_g=150, protein_g=9, carbs_g=9, fat_g=9, fiber_g=0, kcal=999),
            ComposedComponent(name="Chicken Breast", quantity_g=200, protein_g=9, carbs_g=9, fat_g=9, fiber_g=0, kcal=999),
            ComposedComponent(name="greek yogurt bowl", quantity_g=250, protein_g=9, carbs_g=9, fat_g=9, fiber_g=0, kcal=999),
        ])

    monkeypatch.setattr(api_module, "suggest_meal_composition", suggest)
    entries = drop(client, "recipe: post-workout plate - 150g basmati rice, 200g chicken breast, plus a greek yogurt bowl")
    [plan] = [e for e in entries if e["type"] == "meal_composition"]
    comps = plan["components"]
    assert comps[0]["ingredient_id"] == client.ingredients["Basmati rice"]
    assert comps[1]["ingredient_id"] == client.ingredients["Chicken breast"]
    assert comps[2].get("meal_id") == client.meals["Greek yogurt bowl"]
    assert not any(c.get("is_new") for c in comps)

    meals_before = {m["name"] for m in client.get("/logs/meals").json()}
    [member] = save_all(client, D, entries)
    assert member and member.startswith("meal:")
    meal_id = int(member.partition(":")[2])

    meals_after = [m["name"] for m in client.get("/logs/meals").json()]
    assert sorted(meals_after) == sorted(meals_before | {"Post-workout plate"})  # no duplicate saved meal
    ingredients = [i["name"] for i in client.get("/logs/ingredients").json()]
    assert ingredients.count("Basmati rice") == 1 and ingredients.count("Chicken breast") == 1
    assert ingredients.count("Greek yogurt bowl") <= 1

    made_of = {e["target"] for e in client.get("/graph").json()["edges"] if e["source"] == member and e["kind"] == "made_of"}
    rows = client.get(f"/logs/meals/{meal_id}/components").json()
    assert made_of == {f"ingredient:{r['ingredient_id']}" for r in rows}
    assert {f"ingredient:{client.ingredients['Basmati rice']}", f"ingredient:{client.ingredients['Chicken breast']}"} <= made_of

    # A second plan using the same saved meal reuses — never re-forks.
    n_ing = len(ingredients)
    save_all(client, D, [{**plan, "meal_name": "Post-workout plate 2"}])
    assert len(client.get("/logs/ingredients").json()) == n_ing


@pytest.mark.xfail(
    strict=True,
    reason="GAP: LogsRepository.add_meal (nodes/logs/repository.py ~L77) canonicalize_name-upserts the new "
    "plan's name, so 'Chicken rice plate' folds into the saved 'Chicken rice bowl' and OVERWRITES its macros",
)
def test_17_new_plan_never_overwrites_a_similarly_named_saved_meal(client):
    """#17: planning a NEW meal ("Chicken rice plate") saves a new preset;
    the different saved meal "Chicken rice bowl" keeps its own numbers."""
    plan = {"type": "meal_composition", "meal_name": "Chicken rice plate", "components": [
        {"ingredient_id": client.ingredients["Basmati rice"], "quantity_g": 150},
        {"ingredient_id": client.ingredients["Chicken breast"], "quantity_g": 200},
    ]}
    save_all(client, D, [plan])
    meals = {m["name"]: m for m in client.get("/logs/meals").json()}
    assert "Chicken rice plate" in meals
    assert meals["Chicken rice bowl"]["kcal"] == pytest.approx(650)


# =========================================================================== #24


def _seed_money(c):
    for d, amt in [("2026-11-01", 3200), ("2026-11-08", 3200), ("2026-10-15", 3200)]:
        _ok(c.post("/logs/income", json={"date": d, "amount": amt, "source": "Minfy", "kind": "salary"}))
    for d, amt, merchant, kind in [
        ("2026-11-01", 1500, "Rent", "regular"),
        ("2026-11-03", 250, "Trader Joe's", "food"),
        ("2026-11-05", 15.49, "Netflix", "subscription"),
        ("2026-10-20", 999, "October thing", "shopping"),
    ]:
        _ok(c.post("/logs/expenses", json={"date": d, "amount": amt, "merchant": merchant, "kind": kind}))


def test_24_financial_plan_chat_gets_code_computed_totals_and_writes_nothing(client, monkeypatch):
    """#24: discussing salary/savings in chat — the model is handed the
    month's income/spend/savings rate as FINISHED numbers computed in code
    (6400 income, 1765.49 spend, 72% saved; October excluded), and the chat
    itself writes nothing (no rows, no edges, no files)."""
    _seed_money(client)
    before = _snapshot(client)
    captured = _capture_chat(monkeypatch)

    _ok(client.post("/kb/chat", json={"messages": [
        {"role": "user", "content": "Given my salary, how much can I put into savings each month? Help me plan it."}
    ]}))

    ctx = captured[-1] or ""
    assert "income $6,400.00, spend $1,765.49, savings rate 72%" in ctx
    assert "never recalculate" in ctx  # handed over as final numbers
    assert "999" not in ctx.split("## About the user", 1)[-1].split("\n\n## ", 1)[0]  # October stays out of "this month"
    assert _snapshot(client) == before


# =========================================================================== #25


def test_25_income_drop_is_income_and_the_same_amount_expense_is_removed(client, models):
    """#25: "got paid $3,200 from Minfy" — proposed and saved as an INCOME
    row; the model's same-amount expense misread is removed (✗ no $3,200
    expense row)."""
    answers, _ = models
    answers["ParsedJournal"] = _parsed(FinanceEntry(type="finance", amount=3200, merchant="Minfy", category="salary"))
    answers["_FinanceKindResolutions"] = _kinds((0, "regular"))

    entries = drop(client, "got paid $3,200 from Minfy")
    assert [e["type"] for e in entries] == ["income"]
    assert entries[0]["amount"] == 3200 and entries[0]["source"] == "Minfy"

    save_all(client, D, entries)
    [income] = _rows(client, "income_log")
    assert income["amount"] == 3200 and income["date"] == D and income["source"] == "Minfy"
    assert not [r for r in _rows(client, "expense_log") if abs(r["amount"] - 3200) < 0.005]


def test_25_income_in_a_mixed_drop_is_part_of_that_drops_event(client, models):
    """#25: income saved with other records from the same drop is part_of
    the same event as them."""
    answers, _ = models
    answers["ParsedJournal"] = _parsed(
        FinanceEntry(type="finance", amount=3200, merchant="Minfy"),
        FinanceEntry(type="finance", amount=12, merchant="Chipotle"),
        FoodEntry(type="food", meal_type="lunch", description="chipotle bowl", estimated_kcal=0),
    )
    answers["_FinanceKindResolutions"] = _kinds((0, "regular"), (1, "food"))

    entries = drop(client, "got paid $3,200 from Minfy, then a $12 chipotle bowl for lunch")
    assert [e["type"] for e in entries].count("income") == 1
    assert [e["amount"] for e in entries if e["type"] == "finance"] == [12]
    members = save_all(client, D, entries)
    assert any(m.startswith("income:") for m in members)
    _assert_one_shared_event(members)


@pytest.mark.xfail(
    strict=True,
    reason="GAP: a lone record never gets an event — graph_capture.link_event no-ops below 2 members and "
    "frontend/lib/entries.ts linkBatchAsEvent skips <2; the spec says every record saved from one Save is part_of an event",
)
@pytest.mark.parametrize("category,text,parsed,kind", [
    ("25-income", "got paid $3,200 from Minfy", FinanceEntry(type="finance", amount=3200, merchant="Minfy"), "regular"),
    ("26-subscription", "netflix $15.49 monthly", FinanceEntry(type="finance", amount=15.49, merchant="Netflix"), "subscription"),
    ("27-expense", "parking $8", FinanceEntry(type="finance", amount=8, merchant="parking"), "regular"),
])
def test_lone_money_record_is_part_of_its_event(client, models, category, text, parsed, kind):
    """#25/#26/#27: the one record a single-item drop saves is part_of an
    event (spec: 'one capture is one event')."""
    answers, _ = models
    answers["ParsedJournal"] = _parsed(parsed)
    answers["_FinanceKindResolutions"] = _kinds((0, kind))
    answers["_DateResolutions"] = _DateResolutions(resolutions=[])
    [member] = save_all(client, D, drop(client, text))
    assert len(_events_of(member)) == 1


# =========================================================================== #26


def test_26_subscriptions_drop_saves_kind_subscription_date_keyed_one_event(client, models):
    """#26: "netflix $15.49 monthly and spotify $11.99 monthly" — two expense
    rows of kind subscription, keyed to today's date, both part_of one event."""
    answers, _ = models
    answers["ParsedJournal"] = _parsed(
        FinanceEntry(type="finance", amount=15.49, merchant="Netflix", category="streaming"),
        FinanceEntry(type="finance", amount=11.99, merchant="Spotify", category="streaming"),
    )
    answers["_FinanceKindResolutions"] = _kinds((0, "subscription"), (1, "subscription"))
    # "monthly" trips the date-signal regex ("mon…"): the model names no specific day.
    answers["_DateResolutions"] = _DateResolutions(resolutions=[])

    entries = drop(client, "netflix $15.49 monthly and spotify $11.99 monthly")
    assert [e["kind"] for e in entries if e["type"] == "finance"] == ["subscription", "subscription"]
    members = save_all(client, D, entries)
    _assert_one_shared_event(members)

    rows = client.get("/logs/expenses", params={"start": D, "end": D}).json()
    assert {(r["merchant"], r["amount"], r["kind"]) for r in rows} == {("Netflix", 15.49, "subscription"), ("Spotify", 11.99, "subscription")}
    assert all(r["date"] == D for r in rows)


# =========================================================================== #27


def test_27_random_expense_is_date_keyed_and_never_keyword_linked(client, models):
    """#27: "lunch from Priya Shah's food truck $9" — one expense row on
    today's date (findable by date range), and ✗ no keyword edge to the
    person its merchant text happens to name (numeric logs aren't
    keyword-linked)."""
    answers, _ = models
    answers["ParsedJournal"] = _parsed(FinanceEntry(type="finance", amount=9, merchant="Priya Shah's food truck"))
    answers["_FinanceKindResolutions"] = _kinds((0, "food"))

    [member] = save_all(client, D, [e for e in drop(client, "lunch from Priya Shah's food truck $9") if e["type"] == "finance"])
    assert member.startswith("expense:")
    rows = client.get("/logs/expenses", params={"start": D, "end": D}).json()
    assert [(r["amount"], r["date"]) for r in rows] == [(9, D)]
    assert not client.get("/logs/expenses", params={"start": "2026-11-10", "end": "2026-11-10"}).json()
    assert not [e for e in _edges() if e["source_id"] == member and e["kind"] != "part_of"]


# =========================================================================== #28


def test_28_food_drop_with_price_is_food_and_expense_in_the_same_event(client, models):
    """#28: "chipotle bowl $14.50" — BOTH a food row (the saved Chipotle bowl
    meal, so its real calories count) and a $14.50 expense row, and both are
    part_of the SAME event, reachable from each other in the graph."""
    answers, _ = models
    answers["ParsedJournal"] = _parsed(
        FoodEntry(type="food", meal_type="lunch", description="chipotle bowl", estimated_kcal=900),
        FinanceEntry(type="finance", amount=14.5, merchant="Chipotle", category="restaurant"),
    )
    answers["_FinanceKindResolutions"] = _kinds((1, "food"))

    entries = drop(client, "chipotle bowl $14.50")
    assert sorted(e["type"] for e in entries) == ["finance", "food"]
    food = next(e for e in entries if e["type"] == "food")
    assert food["meal_id"] == client.meals["Chipotle bowl"]

    members = save_all(client, D, entries)
    food_id = next(m for m in members if m.startswith("food:"))
    expense_id = next(m for m in members if m.startswith("expense:"))
    event = _assert_one_shared_event([food_id, expense_id])
    assert expense_id in neighborhood(food_id, 2)["nodes"] and event in neighborhood(food_id, 2)["nodes"]

    assert client.get(f"/logs/food/{D}").json()["totals"]["total_kcal"] == pytest.approx(800)  # the preset's calories
    [exp] = _rows(client, "expense_log")
    assert exp["amount"] == 14.5 and exp["kind"] == "food"


# =========================================================================== #29


def test_29_reflection_views_read_graph_and_logs_and_write_nothing(client, models):
    """#29: the reflection views (day record, calendar counts, graph,
    nutrition, money insights, budgets, accounts) read the graph + logs —
    the day shows the drop's event and its rows — and reading them writes
    NOTHING (every table count and every file byte unchanged)."""
    answers, _ = models
    answers["ParsedJournal"] = _parsed(
        FoodEntry(type="food", meal_type="lunch", description="chipotle bowl", estimated_kcal=0),
        FinanceEntry(type="finance", amount=14.5, merchant="Chipotle"),
    )
    answers["_FinanceKindResolutions"] = _kinds((1, "food"))
    _ok(client.post(f"/journal/{D}", content="long day, chipotle for lunch", headers={"content-type": "text/plain"}))
    members = save_all(client, D, drop(client, "chipotle bowl $14.50"))
    _seed_money(client)

    before = _snapshot(client)
    day = _ok(client.get(f"/day/{D}"))
    reads = [
        client.get("/day/counts", params={"start": "2026-11-01", "end": "2026-11-30"}),
        client.get("/graph"),
        client.get(f"/logs/nutrition/{D}"),
        client.get("/finance/insights/monthly"),
        client.get("/finance/insights/subscriptions"),
        client.get("/finance/insights/merchants", params={"start": "2026-11-01", "end": "2026-11-30"}),
        client.get("/logs/habits/ledger"),
        client.get("/finance/accounts"),
        client.get(f"/day/{D}"),
    ]
    assert all(r.status_code == 200 for r in reads), [r.text for r in reads if r.status_code != 200]
    assert _snapshot(client) == before

    [event] = day["events"]
    assert {m["id"] for m in event["members"]} == set(members)  # from the graph
    graph = reads[1].json()
    assert {n["id"] for n in graph["nodes"]} >= set(members)


# =========================================================================== #33


def test_33_monthly_budget_reads_code_computed_totals(client, monkeypatch):
    """#33: monthly budgeting reads totals computed in code — the month's
    insights row equals the hand sum per kind (Nov: 1500 regular + 250 food
    + 15.49 subscription = 1765.49; income 6400; savings 4634.51), a food
    budget line's spend is the code sum, and chat about the budget is
    handed those finished numbers."""
    _seed_money(client)
    nov = next(m for m in client.get("/finance/insights/monthly", params={"months": 2}).json() if m["month"] == "2026-11")
    assert nov["total"] == pytest.approx(1765.49)
    assert nov["by_kind"]["regular"] == pytest.approx(1500)
    assert nov["by_kind"]["food"] == pytest.approx(250)
    assert nov["by_kind"]["subscription"] == pytest.approx(15.49)
    assert nov["by_kind"]["shopping"] == 0  # October's $999 stays in October
    assert nov["income"] == pytest.approx(6400)

    habit = _ok(client.post("/logs/habits", json={
        "name": "Food budget", "target_amount": 400, "target_period": "month",
        "metric": "spend", "direction": "at_most", "match_kind": "food",
    }))
    progress = _ok(client.get(f"/logs/habits/{habit['id']}/progress"))
    assert progress["current"] == pytest.approx(250), progress

    captured = _capture_chat(monkeypatch)
    _ok(client.post("/kb/chat", json={"messages": [{"role": "user", "content": "how is my monthly budget looking?"}]}))
    assert "income $6,400.00, spend $1,765.49, savings rate 72%" in (captured[-1] or "")
