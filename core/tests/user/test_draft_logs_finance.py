"""DRAFT 2026-11-11 — expectations written by Claude from docs/testing/graph-linking-38-categories.md; NOT confirmed by the owner.

LIVE end-to-end drafts for the logs + finance categories (#3, #5, #17, #24,
#25, #26, #27, #28, #29, #33): what the owner would actually type → POST
/drop with the REAL local model (provider=local, cloud blocked by
tests.claude.harness.make_client) → the review→Save step the app performs
(frontend/lib/entries.ts: commit each proposal, then POST /graph/event for a
batch of 2+) → assert filing + graph links.

Skipped unless QUINTACLE_USER_DRAFTS=1 (and Ollama + qwen3:8b are up). Runs
on a fresh sandbox data dir seeded with presets; never touches ~/.quintacle.
The owner's files under "~/Desktop/Quintacle Product Testing, files and
commands/" are only READ by path.

Known gaps (from the faked suite, tests/claude/existing/
test_graph_categories_logs_finance.py) these drafts will hit as written:
a lone saved record gets no event (link_event needs 2+ members); accounts
are not link candidates; a new meal plan named close to a saved meal
overwrites it (LogsRepository.add_meal fuzzy upsert).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.claude.harness import drop, first, make_client, missing_requirements, types

pytestmark = pytest.mark.skipif(os.environ.get("QUINTACLE_USER_DRAFTS") != "1", reason="draft: owner hasn't confirmed")

TESTING = Path.home() / "Desktop" / "Quintacle Product Testing, files and commands"
RECEIPT = TESTING / "Finances" / "inputs" / "20260920_154949.jpg"  # Pink Tiger, Washington DC, 9/20/26, total $510.13
CHAT_MODEL = "local:qwen3:8b"


# --------------------------------------------------------------------------- setup


@pytest.fixture(scope="module")
def c(tmp_path_factory):
    reason = missing_requirements()
    if reason:
        pytest.skip(reason)
    client = make_client(tmp_path_factory.mktemp("user-draft-logs-finance"))
    _seed(client)
    return client


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def _seed(c):
    """Preset-seeded (CLAUDE.md): meals, a routine, ingredients, a person, an account."""
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
        c.ingredients[name] = _ok(c.post("/logs/ingredients", json={
            "name": name, "basis_amount_g": 100, "kcal": kcal, "protein_g": p, "carbs_g": cbs, "fat_g": f,
        }))["id"]
    _ok(c.post("/people", json={"name": "Priya Shah", "category": "friend", "how_met": "college"}))
    _ok(c.post("/finance/accounts", json={"name": "Ally Savings", "account_type": "savings", "institution": "Ally", "balance": 12000}))


def _today() -> str:
    from quintacle_core import clock

    return clock.today().isoformat()


# ----------------------------------------------------- the app's Save (entries.ts port)


def _commit(c, day: str, e: dict) -> str | None:
    """commitEntry + graphIdFor for the types these categories save."""
    t = e["type"]
    when = e.get("entry_date") or day
    if t == "food":
        body = {"date": when, "meal_type": e["meal_type"], "notes": e["description"], "servings": 1}
        body.update({"meal_id": e["meal_id"]} if e.get("meal_id") else {"freeform_kcal": e["estimated_kcal"]})
        return f"food:{_ok(c.post('/logs/food', json=body))['id']}"
    if t == "exercise":
        r = _ok(c.post("/logs/exercise", json={"date": when, "exercise_name": e["exercise_name"], "sets": e["sets"], "notes": e.get("notes", "")}))
        return f"exercise:{r['id']}"
    if t == "finance":
        r = _ok(c.post("/logs/expenses", json={
            "date": when, "amount": e["amount"], "merchant": e["merchant"], "category": e["category"], "notes": e["notes"], "kind": e["kind"],
        }))
        return f"expense:{r['id']}"
    if t == "income":
        r = _ok(c.post("/logs/income", json={"date": when, "amount": e["amount"], "source": e["source"], "kind": e["kind"], "notes": e["notes"]}))
        return f"income:{r['id']}"
    if t == "kb_entry":
        r = _ok(c.post("/kb/entries", json={"folder": e["folder"], "title": e["title"], "content": e["content"], "links": e.get("links")}))
        return f"note:{r['folder']}/{r['slug']}"
    if t == "meal_composition":
        comps = []
        for x in e["components"]:
            if x.get("ingredient_id") is not None:
                comps.append({"ingredient_id": x["ingredient_id"], "quantity_g": x["quantity_g"]})
            elif x.get("meal_id") is not None:
                comps.append({"meal_id": x["meal_id"], "servings": x.get("servings") or 1, "quantity_g": x["quantity_g"]})
            else:
                comps.append({k: x.get(k) for k in ("name", "quantity_g", "basis_amount_g", "protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")})
        return f"meal:{_ok(c.post('/logs/meals/from-ingredients', json={'name': e['meal_name'], 'notes': '', 'components': comps}))['id']}"
    if t == "habit_entry":
        _ok(c.post("/logs/habits", json={k: e[k] for k in (
            "name", "target_amount", "target_period", "metric", "direction", "unit", "match_category", "match_kind")}))
        return None
    raise AssertionError(f"draft doesn't save {t}")


def save(c, entries: list[dict], keep: tuple[str, ...] | None = None) -> list[str]:
    """Save the proposals (optionally only the kept types — the owner pruning
    in review), then link the batch as one event like linkBatchAsEvent."""
    day = _today()
    kept = [e for e in entries if keep is None or e["type"] in keep]
    members = [m for m in (_commit(c, day, e) for e in kept) if m]
    if len(members) >= 2:
        _ok(c.post("/graph/event", json={"members": members, "date": day}))
    return members


def live_drop(c, text: str = "", path: Path | None = None) -> list[dict]:
    return drop(c, text=text, path=path, provider="local")["entries"]


def _edges(kind=None):
    from quintacle_core.graph import get_graph_store

    return [e for e in get_graph_store().all() if kind in (None, e["kind"])]


def _events_of(member: str) -> set[str]:
    return {e["target_id"] for e in _edges("part_of") if e["source_id"] == member and e["target_id"].startswith("event:")}


def _one_shared_event(members: list[str]) -> None:
    events = [_events_of(m) for m in members]
    assert all(len(ev) == 1 for ev in events) and len(set().union(*events)) == 1, dict(zip(members, events))


def _money(a, b) -> bool:
    return a is not None and abs(float(a) - float(b)) < 0.005


def _snapshot(c) -> dict:
    import hashlib

    from quintacle_core.nodes.logs.api import get_repo

    conn = get_repo().conn
    tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    data = Path(os.environ["QUINTACLE_DATA_DIR"])
    return {
        "tables": {t: conn.execute(f'SELECT COUNT(*) AS n FROM "{t}"').fetchone()["n"] for t in tables},  # noqa: S608
        "files": {str(p.relative_to(data)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(data.rglob("*")) if p.is_file() and ".db" not in p.name and "usda" not in str(p)},
    }


# =========================================================================== drafts


def test_3_food_and_workout_set(c):
    """#3: "lunch was my chicken rice bowl, then pull day at the gym, pull-ups
    8, 6, 5" → the food row uses the saved Chicken rice bowl (meal_id, no new
    meal), the exercises are the Pull day routine's (no new routine, no
    'pull day' row), and every saved row is part_of ONE event."""
    meals_before = len(c.get("/logs/meals").json())
    routines_before = c.get("/logs/routines").json()
    entries = live_drop(c, "lunch was my chicken rice bowl, then pull day at the gym, pull-ups 8, 6, 5")
    food = first({"entries": entries}, "food")
    assert food["meal_id"] == c.meals["Chicken rice bowl"], food
    names = {e["exercise_name"].lower() for e in entries if e["type"] == "exercise"}
    assert {"pull-ups", "barbell row", "bicep curl"} <= names and "pull day" not in names, names

    members = save(c, entries, keep=("food", "exercise"))
    _one_shared_event(members)
    assert len(c.get("/logs/meals").json()) == meals_before
    assert c.get("/logs/routines").json() == routines_before


def test_5_financial_goals(c):
    """#5: "my financial goals for 2027: ..." → one note filed under a
    finance folder, linked to Priya Shah (mentions_person) and to the Ally
    Savings account it names; a later finance question in chat finds it."""
    entries = live_drop(c, (
        "my financial goals for 2027: grow Ally Savings to a $20,000 emergency fund, "
        "max out my Roth IRA, and pay Priya Shah back the $500 from Lisbon"
    ))
    note = first({"entries": entries}, "kb_entry")
    assert "financ" in note["folder"].lower(), note["folder"]
    [member] = save(c, entries, keep=("kb_entry",))
    linked = {e["target_id"] for e in _edges() if e["source_id"] == member}
    assert "note:people/priya-shah/profile" in linked, linked
    assert any("finance/accounts/ally-savings" in t for t in linked), linked  # known gap today

    reply = _ok(c.post("/kb/chat", json={"model": CHAT_MODEL, "web": False, "messages": [
        {"role": "user", "content": "What's my emergency fund goal?"}]}))["reply"]
    assert "20,000" in reply or "20000" in reply or "20k" in reply.lower(), reply


def test_17_plan_a_meal(c):
    """#17: "recipe: post-workout plate - 150g basmati rice, 200g chicken
    breast, plus a greek yogurt bowl" → a meal preset made_of the EXISTING
    Basmati rice + Chicken breast ingredients and reusing the saved Greek
    yogurt bowl; no duplicate meals or ingredients."""
    entries = live_drop(c, "recipe: post-workout plate - 150g basmati rice, 200g chicken breast, plus a greek yogurt bowl")
    plan = first({"entries": entries}, "meal_composition")
    comps = plan["components"]
    assert {x.get("ingredient_id") for x in comps} >= {c.ingredients["Basmati rice"], c.ingredients["Chicken breast"]}, comps
    assert any(x.get("meal_id") == c.meals["Greek yogurt bowl"] for x in comps), comps
    meals_before = {m["name"] for m in c.get("/logs/meals").json()}
    [member] = save(c, entries, keep=("meal_composition",))
    after = [m["name"] for m in c.get("/logs/meals").json()]
    assert len(after) == len(meals_before) + 1 and len(set(after)) == len(after), after
    made_of = {e["target"] for e in c.get("/graph").json()["edges"] if e["source"] == member and e["kind"] == "made_of"}
    assert {f"ingredient:{c.ingredients['Basmati rice']}", f"ingredient:{c.ingredients['Chicken breast']}"} <= made_of, made_of


def test_25_how_much_i_make(c):
    """#25: "got paid $3,200 from Minfy" → proposed and saved as INCOME
    ($3,200, source Minfy, today); no $3,200 expense is proposed or saved;
    the income is part_of its capture's event."""
    entries = live_drop(c, "got paid $3,200 from Minfy")
    income = first({"entries": entries}, "income")
    assert _money(income["amount"], 3200) and "minfy" in income["source"].lower(), income
    assert not [e for e in entries if e["type"] == "finance" and _money(e["amount"], 3200)], types({"entries": entries})
    [member] = save(c, entries, keep=("income",))
    assert member.startswith("income:")
    rows = c.get("/logs/income", params={"start": _today(), "end": _today()}).json()
    assert any(_money(r["amount"], 3200) for r in rows), rows
    assert len(_events_of(member)) == 1  # known gap: lone records get no event today


def test_26_subscriptions(c):
    """#26: "netflix $15.49 monthly and spotify $11.99 monthly" → two expense
    rows of kind subscription on today's date, both part_of one event."""
    entries = live_drop(c, "netflix $15.49 monthly and spotify $11.99 monthly")
    fin = [e for e in entries if e["type"] == "finance"]
    assert sorted(round(float(e["amount"]), 2) for e in fin) == [11.99, 15.49], fin
    assert all(e["kind"] == "subscription" for e in fin), fin
    members = save(c, entries, keep=("finance",))
    _one_shared_event(members)
    rows = c.get("/logs/expenses", params={"start": _today(), "end": _today()}).json()
    subs = [r for r in rows if r["kind"] == "subscription"]
    assert {round(r["amount"], 2) for r in subs} >= {11.99, 15.49}, rows


def test_27_random_expense_text(c):
    """#27: "parking $8" → one $8 expense dated today, part_of its event, and
    no keyword edges from the expense row."""
    entries = live_drop(c, "parking $8")
    fin = first({"entries": entries}, "finance")
    assert _money(fin["amount"], 8), fin
    [member] = save(c, entries, keep=("finance",))
    assert not [e for e in _edges() if e["source_id"] == member and e["kind"] != "part_of"]
    assert len(_events_of(member)) == 1  # known gap: lone records get no event today


@pytest.mark.skipif(not RECEIPT.exists(), reason="owner's receipt photo not on this machine")
def test_27_random_expense_receipt_photo(c):
    """#27: the Pink Tiger receipt photo (Finances/inputs) → one expense of
    $510.13 at Pink Tiger, dated 2026-09-20 (the receipt's own date, not
    today), findable by that date."""
    entries = live_drop(c, path=RECEIPT)
    fin = first({"entries": entries}, "finance")
    assert _money(fin["amount"], 510.13), fin
    assert "pink tiger" in fin["merchant"].lower(), fin
    assert fin.get("entry_date") == "2026-09-20", fin
    save(c, entries, keep=("finance",))
    rows = c.get("/logs/expenses", params={"start": "2026-09-20", "end": "2026-09-20"}).json()
    assert any(_money(r["amount"], 510.13) for r in rows), rows


def test_28_random_food_drop(c):
    """#28: "chipotle bowl $14.50" → a food row on the saved Chipotle bowl
    (its 800 kcal) AND a $14.50 expense row, both part_of the SAME event."""
    entries = live_drop(c, "chipotle bowl $14.50")
    food = first({"entries": entries}, "food")
    fin = first({"entries": entries}, "finance")
    assert food["meal_id"] == c.meals["Chipotle bowl"], food
    assert _money(fin["amount"], 14.5), fin
    members = save(c, entries, keep=("food", "finance"))
    assert {m.split(":")[0] for m in members} == {"food", "expense"}
    _one_shared_event(members)


def test_24_discuss_a_financial_plan(c):
    """#24: chatting "how much can I save each month from my salary?" →
    the reply uses the code-computed month totals (the Me block's income /
    spend / savings rate), and the chat writes nothing."""
    from quintacle_core.nodes.kb.day_context import me_context
    from quintacle_core.nodes.kb.api import get_store

    me = me_context(get_store()) or ""
    assert "income $" in me, "seed income/expenses first (the #25-#28 drafts do)"
    before = _snapshot(c)
    reply = _ok(c.post("/kb/chat", json={"model": CHAT_MODEL, "web": False, "messages": [
        {"role": "user", "content": "Looking at my salary this month, how much can I put into savings each month?"}]}))["reply"]
    import re

    income = re.search(r"income \$([\d,]+)\.\d\d", me).group(1)  # e.g. "3,200"
    assert income in reply or income.replace(",", "") in reply, (me, reply)
    assert _snapshot(c) == before


def test_33_monthly_budgeting(c):
    """#33: "budget: food $400 a month" → a spend budget line (metric spend,
    kind food, $400/month, at most); its progress equals the code sum of
    this month's food-kind expenses."""
    entries = live_drop(c, "budget: food $400 a month")
    habit = first({"entries": entries}, "habit_entry")
    assert habit["metric"] == "spend" and _money(habit["target_amount"], 400), habit
    assert habit["target_period"] == "month" and habit["match_kind"] == "food", habit
    save(c, entries, keep=("habit_entry",))
    hid = next(h["id"] for h in c.get("/logs/habits").json() if h["name"] == habit["name"])
    today = _today()
    month_start = today[:8] + "01"
    food_spend = sum(r["amount"] for r in c.get("/logs/expenses", params={"start": month_start, "end": today}).json() if r["kind"] == "food")
    assert _money(c.get(f"/logs/habits/{hid}/progress").json()["current"], food_spend)


def test_29_reflection_dashboard(c):
    """#29: the reflection reads (day record, calendar counts, graph,
    nutrition, money insights, budgets, accounts) show today's events and
    rows, and reading them writes NOTHING."""
    today = _today()
    before = _snapshot(c)
    day = _ok(c.get(f"/day/{today}"))
    for path, params in [
        ("/day/counts", {"start": today[:8] + "01", "end": today}), ("/graph", None), (f"/logs/nutrition/{today}", None),
        ("/finance/insights/monthly", None), ("/finance/insights/subscriptions", None), ("/logs/habits/ledger", None),
        ("/finance/accounts", None),
    ]:
        _ok(c.get(path, params=params))
    assert _snapshot(c) == before
    assert day["events"], "today's drops should show as events on the day record"
