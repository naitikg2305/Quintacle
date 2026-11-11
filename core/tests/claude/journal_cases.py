"""Journal parsing + the Day view: inputs, the RIGHT answers, and the checks,
written once and run by BOTH live suites (tests/claude/local binds
provider="local", tests/claude/subscription_or_api binds provider="cloud").

Expectations come from the product's intent (the journal prompt in
nodes/journal/llm.py, the frontend commit path in frontend/lib/entries.ts,
day_bundle.py) — never fitted to a model's output. A failure is a finding.

The Entry union (nodes/journal/llm.py) has NO sleep / mood / reading / habit
type: activity | food | exercise | substance | todo | body_stat | finance |
kb_entry. So the right proposals for the full-day dump are:
  sleep    -> an activity (or a body_stat) about sleep, ~7 hours
  meal     -> a food entry pointing at the seeded "Chicken rice bowl" preset
  workout  -> the seeded "Push day" routine expanded into its exercises
  mood     -> an activity with category "emotional" (the prompt's mood bucket)
  money    -> one finance entry, amount 42, merchant Trader Joe's
  reading  -> an activity with category "leisure" (the prompt files books there)
Habits are created only by an explicit "habit:" prefix, never from a dump.

Each check returns the HTTP JSON responses whose model calls it relied on, so
the suite modules can assert WHO answered (provider_used local vs cloud).
"""
from __future__ import annotations

import re

import json

from quintacle_core import clock
from tests.claude.harness import first, types

FULL_DAY = (
    "woke up 7:10 after 7h sleep, had the chicken rice bowl for lunch, did push day, "
    "felt great 8/10, paid $42 for groceries at Trader Joe's, read 30 pages of Dune"
)
FULL_DAY_REF = "2026-11-10"

RELATIVE = "yesterday I spent $15 on lunch"
RELATIVE_REF = "2026-11-10"
RELATIVE_EXPECT_DATE = "2026-11-09"

DAY_EXPENSE = "spent $23.50 on dinner at Chipotle"
DAY_EXPENSE_AMOUNT = 23.50
DAY_NOTE = "Reference note: my road bike takes 700x28c tires and Presta valves."

PUSH_DAY = {"bench press", "overhead press", "dips"}


# ---------------------------------------------------------------- helpers

def drop_dated(c, text: str, reference_date: str, provider: str) -> dict:
    """POST /drop the way the scratchpad does when the user picked a day."""
    r = c.post("/drop", data={"text": text, "reference_date": reference_date, "provider": provider})
    assert r.status_code == 200, f"/drop {r.status_code}: {r.text[:400]}"
    return r.json()


def journal_parse(c, text: str, for_date: str, provider: str) -> dict:
    """POST /journal/{date}/parse — the Journal page's own parse call."""
    r = c.post(f"/journal/{for_date}/parse", params={"provider": provider},
               content=text.encode(), headers={"Content-Type": "text/plain"})
    assert r.status_code == 200, f"/journal/parse {r.status_code}: {r.text[:400]}"
    return r.json()


def _of(result: dict, entry_type: str) -> list[dict]:
    return [e for e in result.get("entries", []) if e.get("type") == entry_type]


def _dump(result: dict) -> str:
    return json.dumps(result.get("entries"))[:900]


def _text(e: dict) -> str:
    return " ".join(str(e.get(k) or "") for k in ("description", "metric", "notes", "exercise_name", "title")).lower()


_FULL_DAY_CACHE: dict[tuple[int, str], dict] = {}


def full_day(c, provider: str) -> dict:
    """One real parse of the full-day dump per (client, provider) — every
    full-day check judges the SAME proposal, so a single GPU/Max call."""
    key = (id(c), provider)
    if key not in _FULL_DAY_CACHE:
        _FULL_DAY_CACHE[key] = drop_dated(c, FULL_DAY, FULL_DAY_REF, provider)
    return _FULL_DAY_CACHE[key]


# ---------------------------------------------------------------- full day dump

def check_full_day_sleep(c, provider):
    """'7h sleep' happened and is trackable: it must become an activity (or a
    body_stat) about sleep carrying ~7 hours, not be silently dropped."""
    r = full_day(c, provider)
    # "sleep"/"slept"/"sleeping" — the word, any tense (fixed 2026-11-11:
    # Claude wrote "Slept 7h" and the old substring check missed it).
    is_sleep = lambda e: re.search(r"\bsle(e)?p", _text(e)) is not None  # noqa: E731
    hits = [e for e in _of(r, "activity") if is_sleep(e) and abs(float(e.get("hours") or 0) - 7) <= 0.5]
    hits += [e for e in _of(r, "body_stat") if is_sleep(e) and abs(float(e.get("value") or 0) - 7) <= 0.5]
    assert hits, f"no ~7h sleep entry; got {types(r)}: {_dump(r)}"
    return [r]


def check_full_day_meal_preset(c, provider):
    """The text names a SEEDED meal preset, so the food entry must point at
    'Chicken rice bowl' by meal_id (real macros, not a kcal guess) as lunch."""
    r = full_day(c, provider)
    meals = {m["name"]: m["id"] for m in c.get("/logs/meals").json()}
    want = meals["Chicken rice bowl"]
    food = _of(r, "food")
    assert any(e.get("meal_id") == want for e in food), f"meal_id != {want} (Chicken rice bowl); food={food}"
    hit = next(e for e in food if e.get("meal_id") == want)
    assert hit.get("meal_type") == "lunch", f"'for lunch' was said; got meal_type={hit.get('meal_type')!r}"
    return [r]


def check_full_day_push_routine(c, provider):
    """'did push day' names the SEEDED routine: the proposal is its exact
    exercises (Bench press, Overhead press, Dips), with no invented reps or
    weights — the user fills those in (prompt + expand_routine_mentions)."""
    r = full_day(c, provider)
    ex = _of(r, "exercise")
    names = {(e.get("exercise_name") or "").strip().lower() for e in ex}
    assert PUSH_DAY <= names, f"push day exercises missing: {PUSH_DAY - names}; got {sorted(names)}"
    for e in ex:
        if (e.get("exercise_name") or "").strip().lower() in PUSH_DAY:
            invented = [s for s in e.get("sets") or [] if s.get("reps") or s.get("weight")]
            assert not invented, f"invented sets for {e['exercise_name']}: {invented}"
    return [r]


def check_full_day_mood(c, provider):
    """'felt great 8/10' is a mood report; the prompt's bucket for how you
    felt is an activity with category 'emotional'."""
    r = full_day(c, provider)
    assert any(e.get("category") == "emotional" for e in _of(r, "activity")), f"no emotional activity; {_dump(r)}"
    return [r]


def check_full_day_finance(c, provider):
    """Exactly $42 was spent once, at Trader Joe's, on groceries — one finance
    entry (no double counting), the merchant kept, the category inferable."""
    r = full_day(c, provider)
    fin = _of(r, "finance")
    total = sum(float(e.get("amount") or 0) for e in fin)
    assert abs(total - 42) < 0.01, f"finance total {total} != 42; finance={fin}"
    e = first(r, "finance")
    assert "trader joe" in (e.get("merchant") or "").lower(), f"merchant={e.get('merchant')!r}"
    assert "grocer" in (e.get("category") or "").lower(), f"category={e.get('category')!r}"
    return [r]


def check_full_day_reading(c, provider):
    """Reading Dune is leisure (the prompt files books under leisure); there
    is no reading/habit type in a dump, so it must be a leisure activity."""
    r = full_day(c, provider)
    hits = [e for e in _of(r, "activity") if e.get("category") == "leisure"
            and ("dune" in _text(e) or "read" in _text(e))]
    assert hits, f"no leisure reading activity; {_dump(r)}"
    return [r]


def check_full_day_dates_stay_on_day(c, provider):
    """Nothing in the dump points at another day ('8/10' is a mood score,
    '7:10' a wake time), so no entry may be re-dated away from the reference day."""
    r = full_day(c, provider)
    moved = [e for e in r.get("entries", []) if e.get("entry_date") not in (None, "", FULL_DAY_REF)]
    assert not moved, f"entries moved off {FULL_DAY_REF}: {moved}"
    return [r]


# ---------------------------------------------------------------- relative dates

def _check_yesterday(r: dict) -> None:
    fin = _of(r, "finance")
    assert len(fin) == 1, f"want one finance entry; got {types(r)}: {_dump(r)}"
    assert abs(float(fin[0].get("amount") or 0) - 15) < 0.01, fin[0]
    dated = [e for e in r.get("entries", []) if "entry_date" in e]
    wrong = [e for e in dated if e.get("entry_date") != RELATIVE_EXPECT_DATE]
    assert not wrong, f"'yesterday' from {RELATIVE_REF} is {RELATIVE_EXPECT_DATE}; got {wrong}"


def check_relative_date_drop(c, provider):
    """Scratchpad drop backfilling 2026-11-10: 'yesterday' is 2026-11-09, so the
    $15 finance entry (and anything else proposed from it) is dated 11-09."""
    r = drop_dated(c, RELATIVE, RELATIVE_REF, provider)
    _check_yesterday(r)
    return [r]


def check_relative_date_journal(c, provider):
    """Journal page parse for 2026-11-10: same rule — the date is resolved
    against the page's day, so 'yesterday' lands on 2026-11-09."""
    r = journal_parse(c, RELATIVE, RELATIVE_REF, provider)
    _check_yesterday(r)
    return [r]


# ---------------------------------------------------------------- day view

def check_day_bundle_after_commit(c, provider):
    """Parse -> Save through the real endpoints -> GET /day: the committed
    expense counts toward money.spent and the saved note is under notes_saved
    (notes_saved keys off the note's ET 'edited' stamp, so the day is today)."""
    today = clock.today().isoformat()

    r_fin = drop_dated(c, DAY_EXPENSE, today, provider)
    fin = first(r_fin, "finance")
    assert abs(float(fin["amount"]) - DAY_EXPENSE_AMOUNT) < 0.01, fin
    # Commit exactly as frontend/lib/entries.ts does: date = entry_date ?? picked day.
    body = {"date": fin.get("entry_date") or today, "amount": fin["amount"], "merchant": fin.get("merchant") or "",
            "category": fin.get("category") or "", "notes": fin.get("notes") or "", "kind": fin.get("kind") or "regular"}
    assert body["date"] == today, f"nothing in '{DAY_EXPENSE}' says another day; date={body['date']}"
    saved = c.post("/logs/expenses", json=body)
    assert saved.status_code == 200, saved.text
    expense_id = saved.json()["id"]

    r_note = drop_dated(c, DAY_NOTE, today, provider)
    note = first(r_note, "kb_entry")
    w = c.post("/kb/entries", json={"folder": note["folder"], "title": note["title"],
                                    "content": note["content"], "links": note.get("links") or []})
    assert w.status_code == 200, w.text
    ref = w.json()

    d = c.get(f"/day/{today}")
    assert d.status_code == 200, d.text
    day = d.json()
    assert any(e.get("id") == expense_id for e in day["expenses"]), f"committed expense missing: {day['expenses']}"
    spent = round(sum(float(e.get("amount") or 0) for e in day["expenses"]), 2)
    assert day["money"]["spent"] == spent and spent >= DAY_EXPENSE_AMOUNT, day["money"]
    assert any(n["folder"] == ref["folder"] and n["slug"] == ref["slug"] for n in day["notes_saved"]), \
        f"saved note {ref} not in notes_saved: {day['notes_saved']}"
    return [r_fin, r_note]


ALL = [
    check_full_day_sleep, check_full_day_meal_preset, check_full_day_push_routine, check_full_day_mood,
    check_full_day_finance, check_full_day_reading, check_full_day_dates_stay_on_day,
    check_relative_date_drop, check_relative_date_journal, check_day_bundle_after_commit,
]
