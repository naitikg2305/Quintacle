"""§10 time grounding + the Me lane (next-wave-plan, 2026-10-20):

- detect_dates: the pure deterministic date-word parser (explicit forms,
  relative words, year inference = most recent past occurrence);
- day_bundle: one day's full record as finished context text, assembled from
  the real stores — journal (incl. the photo-journal who-with line), SQLite
  log rows as their already-computed one-liners, graph edge labels;
- me_context: curated `Me` notes + live SQL-computed facts (PRs, this
  month's money, latest body stats) with exact arithmetic asserted;
- context assembly: the Now line on EVERY provider (KB on or off), day
  bundles hydrating only when the newest user message mentions dates, the
  deep-link instruction, and the Me block prepended everywhere.

No live model calls anywhere — provider runners are stubbed. Seeding goes
through the real endpoints on a sandboxed tmp DATA_DIR (CLAUDE.md: never
~/.quintacle, never an unseeded store for quality judgments).
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.retrieval as retrieval
from quintacle_core import clock
from quintacle_core.graph import create_edge
from quintacle_core.nodes.kb import chat
from quintacle_core.nodes.kb.day_context import day_bundle, detect_dates, me_context
from quintacle_core.nodes.kb.api import get_store as get_kb_store

# A fixed, known "today": Tuesday 2026-10-20 (Eastern).
TODAY = date(2026, 10, 20)


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def frozen_clock(monkeypatch):
    """clock.today()/now() pinned to the fixed date — chat and day_context
    import the clock module itself, so patching its functions covers both."""
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 10, 20, 19, 45, tzinfo=clock.TIME_ZONE))


@pytest.fixture
def client(tmp_path, monkeypatch, frozen_clock):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


def _seed_april_day(client):
    """One fully recorded day (2026-04-14): a journal with the auto
    photo-journal who-with line, log rows, a person, and a graph edge."""
    client.post("/people", json={"name": "Laura", "category": "friend", "how_met": "college"})
    client.post(
        "/journal/2026-04-14",
        content=(
            "Long lifting day, then the park.\n"
            "📷 2:14 PM — with Laura at Hermann Park · sunny (photo: Lake walk)\n"
        ),
    )
    client.post(
        "/logs/expenses", json={"date": "2026-04-14", "amount": 14.5, "merchant": "Chipotle", "category": "food"}
    )
    client.post(
        "/logs/exercise",
        json={"date": "2026-04-14", "exercise_name": "Deadlift", "sets": [{"reps": 5, "weight": 315}]},
    )
    create_edge("journal:2026-04-14", "note:people/laura/profile", "mentions_person", "test")


def _capture_contexts(monkeypatch) -> list[str | None]:
    captured: list[str | None] = []

    def runner(model, messages, kb_text):
        captured.append(kb_text)
        return "stub-reply"

    for name in ("_run_anthropic", "_run_openai", "_run_bedrock", "_run_local"):
        monkeypatch.setattr(chat, name, runner)
    return captured


def _chat(client, text: str, **extra) -> dict:
    resp = client.post("/kb/chat", json={"messages": [{"role": "user", "content": text}], **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- detect_dates: explicit forms ---------------------------------------------


def test_iso_date():
    assert detect_dates("what happened on 2026-04-14?", TODAY) == [date(2026, 4, 14)]


def test_numeric_month_day_infers_most_recent_past_year():
    assert detect_dates("remember 4/14?", TODAY) == [date(2026, 4, 14)]  # past this year
    assert detect_dates("remember 12/25?", TODAY) == [date(2025, 12, 25)]  # future → last year


def test_numeric_with_explicit_year_two_and_four_digit():
    assert detect_dates("on 4/14/2025 we met", TODAY) == [date(2025, 4, 14)]
    assert detect_dates("on 04/14/25 we met", TODAY) == [date(2025, 4, 14)]
    # The explicit year is NEVER also parsed as a bare month/day.
    assert len(detect_dates("4/14/2025", TODAY)) == 1


def test_month_name_forms():
    assert detect_dates("what did I do on April 14?", TODAY) == [date(2026, 4, 14)]
    assert detect_dates("oct 7th was rough", TODAY) == [date(2026, 10, 7)]
    assert detect_dates("December 25 plans", TODAY) == [date(2025, 12, 25)]  # year inference: past
    assert detect_dates("Oct 7, 2024 notes", TODAY) == [date(2024, 10, 7)]


def test_day_first_month_forms():
    assert detect_dates("the 14th of April", TODAY) == [date(2026, 4, 14)]
    assert detect_dates("14 April again", TODAY) == [date(2026, 4, 14)]


def test_feb_29_resolves_to_the_last_real_leap_day():
    assert detect_dates("feb 29", TODAY) == [date(2024, 2, 29)]


def test_invalid_dates_are_skipped():
    assert detect_dates("feb 30 and 24/7 support", TODAY) == []


# --- detect_dates: relative words ----------------------------------------------


def test_today_yesterday_and_friends():
    assert detect_dates("what did I eat today?", TODAY) == [TODAY]
    assert detect_dates("yesterday's workout", TODAY) == [date(2026, 10, 19)]
    assert detect_dates("the day before yesterday", TODAY) == [date(2026, 10, 18)]
    assert detect_dates("what's due tomorrow?", TODAY) == [date(2026, 10, 21)]


def test_last_weekday_is_strictly_before_today():
    # TODAY is a Tuesday — "last tuesday" is a full week back, never today.
    assert detect_dates("last tuesday's session", TODAY) == [date(2026, 10, 13)]
    assert detect_dates("last friday", TODAY) == [date(2026, 10, 16)]


def test_n_days_and_weeks_ago():
    assert detect_dates("two weeks ago", TODAY) == [date(2026, 10, 6)]
    assert detect_dates("3 days ago", TODAY) == [date(2026, 10, 17)]
    assert detect_dates("a week ago I benched", TODAY) == [date(2026, 10, 13)]


def test_last_week_expands_to_that_whole_week():
    days = detect_dates("how was last week?", TODAY)
    assert days == [date(2026, 10, 12 + i) for i in range(7)]  # Mon..Sun
    assert days[0].weekday() == 0 and days[-1].weekday() == 6


# --- detect_dates: order, dedupe, none ------------------------------------------


def test_no_dates_means_empty_list():
    assert detect_dates("how much protein should I eat?", TODAY) == []
    assert detect_dates("", TODAY) == []


def test_multiple_dates_keep_mention_order_and_dedupe():
    assert detect_dates("compare April 14 and 2026-01-02, then April 14 again", TODAY) == [
        date(2026, 4, 14),
        date(2026, 1, 2),
    ]


# --- day_bundle: assembled from the seeded stores -------------------------------


def test_day_bundle_carries_journal_rows_and_edge_labels(client):
    _seed_april_day(client)
    bundle = day_bundle(date(2026, 4, 14))
    # The journal section — including the photo-journal who-with line.
    assert "with Laura at Hermann Park" in bundle
    assert "Long lifting day" in bundle
    # Log rows as their ALREADY-COMPUTED one-liners (retrieval's summaries).
    assert "Chipotle — $14.50 — food — 2026-04-14" in bundle
    assert "Deadlift — 5@315.0lb — 2026-04-14" in bundle
    # The day's 1-hop person edge label, straight from the graph.
    assert "Laura (mentions_person, note:people/laura/profile)" in bundle


def test_day_bundle_of_an_empty_day_is_empty(client):
    assert day_bundle(date(2024, 1, 1)) == ""


def test_day_bundle_respects_the_char_cap(client):
    client.post("/journal/2026-05-01", content=("ramble " * 2000))
    bundle = day_bundle(date(2026, 5, 1))
    assert len(bundle) <= 6100  # cap + the truncation marker
    assert "(…truncated)" in bundle


# --- me_context: curated + computed --------------------------------------------


def _seed_me(client):
    client.post(
        "/kb/entries",
        json={"folder": "Me", "title": "Me", "content": "Lives in Houston. Left knee acts up on deep squats."},
    )
    # PRs: two deadlift sessions (max must win), one bench.
    client.post(
        "/logs/exercise",
        json={"date": "2026-09-14", "exercise_name": "Deadlift", "sets": [{"reps": 5, "weight": 315}]},
    )
    client.post(
        "/logs/exercise",
        json={"date": "2026-10-01", "exercise_name": "Deadlift", "sets": [{"reps": 8, "weight": 225}]},
    )
    client.post(
        "/logs/exercise",
        json={"date": "2026-10-05", "exercise_name": "Bench Press", "sets": [{"reps": 5, "weight": 185}]},
    )
    # Money: this month = Oct 2026 (TODAY is pinned). September stays out.
    client.post("/logs/income", json={"date": "2026-10-01", "amount": 5000, "source": "salary"})
    client.post("/logs/expenses", json={"date": "2026-10-03", "amount": 1000, "merchant": "Rent"})
    client.post("/logs/expenses", json={"date": "2026-10-12", "amount": 250, "merchant": "Groceries"})
    client.post("/logs/expenses", json={"date": "2026-09-20", "amount": 999, "merchant": "LastMonth"})
    # Body stats: latest row per metric only.
    client.post("/logs/body-stats", json={"date": "2026-10-01", "metric": "weight", "value": 178, "unit": "lb"})
    client.post("/logs/body-stats", json={"date": "2026-10-15", "metric": "weight", "value": 176, "unit": "lb"})
    client.post("/logs/body-stats", json={"date": "2026-10-10", "metric": "bodyfat", "value": 18, "unit": "%"})


def test_me_context_computes_live_facts_with_exact_arithmetic(client):
    _seed_me(client)
    me = me_context(get_kb_store())
    assert me is not None and me.startswith("## About the user")
    # Curated half: the Me note's content.
    assert "Left knee acts up on deep squats." in me
    # PRs: the MAX weight per exercise, with the set's own date.
    assert "- Deadlift: 315 lb × 5 (as of 2026-09-14)" in me
    assert "- Bench Press: 185 lb × 5 (as of 2026-10-05)" in me
    assert "225" not in me  # the lighter session never surfaces
    # Money: SQL totals + savings rate (5000 − 1250) / 5000 = 75%.
    assert "income $5,000.00, spend $1,250.00, savings rate 75%" in me
    assert "999" not in me  # September stays out of "this month"
    # Body stats: latest per metric only.
    assert "- weight: 176 lb (as of 2026-10-15)" in me
    assert "- bodyfat: 18 % (as of 2026-10-10)" in me
    assert "178" not in me
    # The instruction: these are finished numbers.
    assert "never recalculate" in me


def test_me_context_empty_store_is_none(client):
    assert me_context(get_kb_store()) is None


def test_me_context_curated_only_without_sql_rows(client):
    client.post("/kb/entries", json={"folder": "Me", "title": "Me", "content": "Allergic to shellfish."})
    me = me_context(get_kb_store())
    assert "Allergic to shellfish." in me
    assert "strength PRs" not in me  # empty tables → sections omitted silently
    assert "income" not in me
    assert "body stats" not in me


# --- context assembly: Now line, Me block, day hydration, deep links ------------

NOW_LINE = "Now: Tuesday 2026-10-20, 7:45 PM (America/New_York)."


def test_now_line_heads_the_context_for_every_provider(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    for model in ("claude-sonnet-5-5", "gpt-4o-mini", "bedrock:us.amazon.nova-lite-v1:0", "local:qwen3:4b"):
        _chat(client, "hello", model=model)
    assert len(captured) == 4
    for kb_text in captured:
        assert kb_text.startswith(NOW_LINE)


def test_now_line_present_even_with_the_kb_off(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    _chat(client, "hello", use_kb=False)
    [kb_text] = captured
    assert kb_text == NOW_LINE  # knows now; no KB material leaks in


def test_me_block_prepends_to_every_scope(client, monkeypatch):
    _seed_me(client)
    client.post("/kb/entries", json={"folder": "Fitness", "title": "Cues", "content": "Brace hard."})
    captured = _capture_contexts(monkeypatch)
    _chat(client, "anything new?")
    _chat(client, "cues?", folder="fitness")
    _chat(client, "brace?", folder="fitness", slug="cues")
    for kb_text in captured:
        assert "## About the user" in kb_text
        assert "income $5,000.00" in kb_text


def test_date_words_hydrate_that_days_record_alongside_retrieval(client, monkeypatch):
    _seed_april_day(client)
    captured = _capture_contexts(monkeypatch)
    _chat(client, "what did I do on April 14?")
    [kb_text] = captured
    assert "## 2026-04-14 — that day's record" in kb_text
    assert "with Laura at Hermann Park" in kb_text
    assert "Chipotle — $14.50 — food — 2026-04-14" in kb_text


def test_no_dates_means_no_day_blocks(client, monkeypatch):
    _seed_april_day(client)
    captured = _capture_contexts(monkeypatch)
    _chat(client, "how do I brace for a deadlift?")
    [kb_text] = captured
    assert "that day's record" not in kb_text


def test_day_hydration_caps_at_three_dates(client, monkeypatch):
    for day in ("2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17"):
        client.post(f"/journal/{day}", content=f"journal for {day}")
    captured = _capture_contexts(monkeypatch)
    _chat(client, "compare 2026-04-14, 2026-04-15, 2026-04-16 and 2026-04-17")
    [kb_text] = captured
    assert kb_text.count("— that day's record") == 3
    assert "## 2026-04-17 — that day's record" not in kb_text


def test_folder_scoped_chat_gets_no_day_bundles(client, monkeypatch):
    _seed_april_day(client)
    client.post("/kb/entries", json={"folder": "Fitness", "title": "Cues", "content": "Brace hard."})
    captured = _capture_contexts(monkeypatch)
    _chat(client, "what about April 14?", folder="fitness")
    [kb_text] = captured
    # The scoped contract holds: nothing outside the folder enters.
    assert "that day's record" not in kb_text
    assert kb_text.startswith(NOW_LINE)


def test_deep_link_instruction_rides_in_every_kb_context(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    _chat(client, "hello")
    [kb_text] = captured
    # The exact app routes the frontend renders as navigation (see chat._LINK_RULES).
    assert "/kb/browse?path=<folder>&open=<slug>" in kb_text
    assert "/kb/asset?folder=<folder>&path=<asset path>" in kb_text


def test_escalation_carries_the_identical_time_grounded_context(client, monkeypatch):
    _seed_april_day(client)
    captured = _capture_contexts(monkeypatch)
    _chat(client, "what happened on April 14?", model="local:qwen3:8b")
    _chat(client, "what happened on April 14?", model="claude-sonnet-5-5")
    local_ctx, cloud_ctx = captured
    assert local_ctx == cloud_ctx
    assert "## 2026-04-14 — that day's record" in cloud_ctx
