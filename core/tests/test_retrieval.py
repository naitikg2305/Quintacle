"""retrieval.py — the triple-hybrid index: CRUD, deterministic summaries,
FTS-only retrieval, RRF fusion (vector lane stubbed — the suite must pass
without sqlite-vec or Ollama installed), graph expansion, the vault/
conversations exclusions, failure isolation of the write hooks, the REST
endpoint + MCP tool, and the backfill. End-to-end tests run on
preset-seeded data (meals/routines/people/experiences) per CLAUDE.md."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.retrieval as retrieval
from quintacle_core.db import connect
from quintacle_core.graph import create_edge, init_graph_store
from quintacle_core.nodes.schedule.models import Priority, Todo
from quintacle_core.retrieval import (
    RetrievalIndex,
    deterministic_prose_summary,
    init_retrieval_index,
    is_excluded,
    log_row_title_and_summary,
    prose_summary,
    rrf_merge,
)
from quintacle_core.retrieval_backfill import run_backfill


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Each test wires its own index (or none) — never inherit another
    test's connection through the module global."""
    retrieval._index = None
    yield
    retrieval._index = None


def make_index(tmp_path) -> RetrievalIndex:
    return init_retrieval_index(connect(tmp_path / "test.db"))


# --- index CRUD ---


def test_index_node_upsert_and_remove_round_trip(tmp_path):
    index = make_index(tmp_path)
    assert index.index_node("note:fitness/deadlift-cues", "note", "Deadlift Cues", summary="Brace first", body="Brace before you pull.")

    row = index.get_node("note:fitness/deadlift-cues")
    assert row["type"] == "note"
    assert row["title"] == "Deadlift Cues"
    assert row["summary"] == "Brace first"
    assert row["updated_at"]  # Eastern-time stamp from clock.now()

    # Upsert, not duplicate: same id re-indexed replaces both tables' rows.
    index.index_node("note:fitness/deadlift-cues", "note", "Deadlift Cues", summary="Updated line", body="New body text.")
    assert index.get_node("note:fitness/deadlift-cues")["summary"] == "Updated line"
    assert index.conn.execute("SELECT COUNT(*) AS n FROM nodes_fts").fetchone()["n"] == 1
    assert [r["id"] for r in index.retrieve("deadlift")] == ["note:fitness/deadlift-cues"]

    index.remove_node("note:fitness/deadlift-cues")
    assert index.get_node("note:fitness/deadlift-cues") is None
    assert index.retrieve("deadlift") == []


def test_empty_title_falls_back_to_the_ids_rest(tmp_path):
    index = make_index(tmp_path)
    index.index_node("journal:2026-10-12", "journal_day", "", body="a day")
    assert index.get_node("journal:2026-10-12")["title"] == "2026-10-12"


# --- deterministic summaries, per type (all computed in code) ---


def test_log_row_summaries_are_computed_from_the_real_rows(tmp_path):
    conn = connect(tmp_path / "test.db")
    conn.execute(
        "INSERT INTO expense_log (id, date, amount, merchant, category) VALUES (1, '2026-10-12', 14.5, 'Chipotle', 'food')"
    )
    conn.execute("INSERT INTO meals (id, name, kcal, protein_g) VALUES (3, 'Chipotle bowl', 800, 45)")
    conn.execute(
        "INSERT INTO food_log (id, date, meal_type, meal_id, servings, notes) VALUES (2, '2026-10-12', 'lunch', 3, 2, '')"
    )
    conn.execute(
        "INSERT INTO exercise_sets (id, date, exercise_name, performance_text) VALUES (4, '2026-10-12', 'Bench Press', '3x8 @ 185lb')"
    )
    conn.execute(
        "INSERT INTO activity_log (id, date, category, description, hours) VALUES (5, '2026-10-12', 'Work', 'Wrote the retrieval wave', 6)"
    )
    conn.execute("INSERT INTO substance_log (id, date, substance, amount) VALUES (6, '2026-10-12', 'Caffeine', 200)")
    conn.execute("INSERT INTO body_stats (id, date, metric, value, unit) VALUES (7, '2026-10-12', 'weight', 172.5, 'lb')")
    conn.execute(
        "INSERT INTO ingredients (id, name, basis_amount_g, kcal) VALUES (8, 'Chicken thigh', 100, 209)"
    )
    conn.commit()

    assert log_row_title_and_summary(conn, "expense:1")[:2] == ("Chipotle", "Chipotle — $14.50 — food — 2026-10-12")
    # kcal x servings is arithmetic done in SQL, never re-derived by a model.
    assert log_row_title_and_summary(conn, "food:2")[:2] == (
        "Chipotle bowl",
        "Chipotle bowl — lunch — 1600 kcal — 2026-10-12",
    )
    assert log_row_title_and_summary(conn, "exercise:4")[1] == "Bench Press — 3x8 @ 185lb — 2026-10-12"
    assert log_row_title_and_summary(conn, "activity:5")[1] == "Wrote the retrieval wave — Work — 6h — 2026-10-12"
    assert log_row_title_and_summary(conn, "substance:6")[1] == "Caffeine 200 — 2026-10-12"
    assert log_row_title_and_summary(conn, "body_stat:7")[1] == "weight 172.5 lb — 2026-10-12"
    assert log_row_title_and_summary(conn, "meal:3")[1] == "Chipotle bowl — 800 kcal — 45g protein — meal preset"
    assert log_row_title_and_summary(conn, "ingredient:8")[1] == "Chicken thigh — 209 kcal / 100 g — ingredient preset"
    assert log_row_title_and_summary(conn, "expense:999") is None  # row gone
    assert log_row_title_and_summary(conn, "exercise:Bench Press") is None  # name-keyed, not a row
    assert log_row_title_and_summary(conn, "note:a/b") is None


def test_structured_node_summaries_todo_person_experience_routine_event(tmp_path):
    index = make_index(tmp_path)
    todo = Todo(title="Renew lease", category="home", priority=Priority.HIGH, due_date=date(2026, 11, 1))
    retrieval.safe_index_todo(todo)
    assert index.get_node(f"todo:{todo.id}")["summary"] == "Renew lease — home — due 2026-11-01"

    retrieval.safe_index_person("Laura", "People/Laura", "friend", "college", "Loves hiking.")
    person = index.get_node("note:People/Laura/profile")
    assert person["type"] == "person"
    assert person["summary"] == "Laura — friend — college"

    retrieval.safe_index_experience("Mia Italina Kitchen", "planning/travel/alexandria/restaurants", "mia-italina-kitchen", "Alexandria", "restaurant", "9/10")
    exp = index.get_node("experience:planning/travel/alexandria/restaurants/mia-italina-kitchen")
    assert exp["summary"] == "Mia Italina Kitchen — Alexandria — restaurant — 9/10"

    retrieval.safe_index_routine("Pull Day", ["Deadlift", "Pull Ups"])
    assert index.get_node("routine:Pull Day")["summary"] == "Pull Day — Deadlift, Pull Ups — workout routine"

    retrieval.safe_index_event("event:abc123def456", 3, date(2026, 10, 12))
    assert index.get_node("event:abc123def456")["summary"] == "event — 2026-10-12 — 3 records"


def test_deterministic_prose_fallback_skips_headings_assets_and_markers():
    body = "# A Title\n\n<!-- mcp-append:xyz -->\n[asset](assets/pic.jpg)\n\nThe actual first line of content.\nSecond line."
    assert deterministic_prose_summary(body, "A Title") == "The actual first line of content."
    assert deterministic_prose_summary("x" * 500) == "x" * 120  # ~120-char truncation
    assert deterministic_prose_summary("", "Only A Title") == "Only A Title"  # empty body -> title


# --- the prose-summary model seam (local-only, fallback always safe) ---


def test_prose_summary_off_mode_is_the_deterministic_fallback(monkeypatch):
    monkeypatch.setenv("QUINTACLE_SUMMARY_PROVIDER", "off")
    assert prose_summary("T", "# T\n\nFirst real line.") == "First real line."


def test_prose_summary_falls_back_when_the_local_model_is_unreachable(monkeypatch):
    monkeypatch.setenv("QUINTACLE_SUMMARY_PROVIDER", "local")
    import quintacle_core.llm_dispatch as llm_dispatch

    def boom(*args, **kwargs):
        raise llm_dispatch.OllamaError("daemon down")

    monkeypatch.setattr(llm_dispatch, "parse_structured", boom)
    assert prose_summary("T", "First real line.") == "First real line."


def test_prose_summary_uses_the_local_model_and_never_cloud(monkeypatch):
    monkeypatch.setenv("QUINTACLE_SUMMARY_PROVIDER", "local")
    import quintacle_core.llm_dispatch as llm_dispatch

    seen = {}

    def fake_parse(system, user_content, output_format, *, provider=None, max_tokens=0):
        seen["provider"] = provider
        return llm_dispatch.ParseResult(output_format(summary="A crisp model-written line."), "local")

    monkeypatch.setattr(llm_dispatch, "parse_structured", fake_parse)
    assert prose_summary("T", "whatever body") == "A crisp model-written line."
    assert seen["provider"] == "local"  # pinned — a summary never bills a silent cloud call


# --- FTS-only retrieval (no sqlite-vec, no Ollama anywhere) ---


def test_fts_retrieval_ranks_and_filters_by_type(tmp_path):
    index = make_index(tmp_path)
    index.index_node("note:fitness/deadlift-cues", "note", "Deadlift Cues", summary="Brace first", body="Brace before you pull. Deadlift daily.")
    index.index_node("note:fitness/squat-cues", "note", "Squat Cues", body="Knees out. A deadlift is not a squat.")
    index.index_node("journal:2026-10-12", "journal_day", "2026-10-12", body="Hit a deadlift PR today.")

    results = index.retrieve("deadlift")
    assert [r["id"] for r in results][0] == "note:fitness/deadlift-cues"  # title match outranks body-only
    assert {r["id"] for r in results} == {"note:fitness/deadlift-cues", "note:fitness/squat-cues", "journal:2026-10-12"}
    for r in results:
        assert set(r) == {"id", "type", "title", "summary", "score", "updated_at", "neighbors"}  # updated_at added 2026-10-27 (§12 note dates)

    only_days = index.retrieve("deadlift", types=["journal_day"])
    assert [r["id"] for r in only_days] == ["journal:2026-10-12"]

    assert index.retrieve("") == []
    assert index.retrieve('"unbalanced (fts* syntax" AND NEAR(') == []  # operators neutralized, no 500


def test_retrieve_respects_k(tmp_path):
    index = make_index(tmp_path)
    for i in range(30):
        index.index_node(f"note:things/thing-{i}", "note", f"Thing {i}", body="a common word everywhere")
    assert len(index.retrieve("common", k=7)) == 7


# --- RRF fusion (vector lane stubbed) ---


def test_rrf_merge_is_plain_rank_arithmetic():
    fused = rrf_merge([["a", "b", "c"], ["b", "a"]])
    scores = dict(fused)
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["c"] == pytest.approx(1 / 63)
    # a and b tie exactly -> deterministic id tiebreak, c last.
    assert [node_id for node_id, _ in fused] == ["a", "b", "c"]


def test_vector_lane_votes_are_fused_with_fts(tmp_path, monkeypatch):
    index = make_index(tmp_path)
    index.index_node("note:a/x", "note", "Alpha", body="shared keyword")
    index.index_node("note:a/y", "note", "Beta", body="shared keyword shared keyword")
    index.index_node("note:a/z", "note", "Gamma", body="nothing matching the words")

    # Stub: the vector lane "understands" Gamma is most similar — no
    # sqlite-vec, no Ollama, pure rank lists into rrf_merge.
    monkeypatch.setattr(index, "_vector_ids", lambda query, limit: ["note:a/z", "note:a/y"])

    results = index.retrieve("shared keyword")
    ids = [r["id"] for r in results]
    assert "note:a/z" in ids  # FTS alone would never return it
    # Two lane votes beat one: y (fts + vec) outranks x (fts only).
    assert ids.index("note:a/y") < ids.index("note:a/x")


def test_vector_lane_silently_off_without_sqlite_vec(tmp_path):
    index = make_index(tmp_path)
    index.index_node("note:a/x", "note", "Alpha", body="hello world")
    # sqlite-vec isn't installed in the test venv — search/upsert/remove all
    # no-op and retrieve() still answers from FTS5 alone.
    assert index.vectors.search("hello", 10) == []
    assert [r["id"] for r in index.retrieve("hello")] == ["note:a/x"]
    index.remove_node("note:a/x")  # vector remove path must not blow up either


# --- graph expansion ---


def test_retrieve_attaches_one_hop_neighbors_with_edge_types(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_graph_store(tmp_path, conn)
    index = init_retrieval_index(conn)

    index.index_node("journal:2026-10-12", "journal_day", "2026-10-12", body="Dinner with Laura at Mia Italina.")
    index.index_node("note:people/laura/profile", "person", "Laura", summary="Laura — friend")
    create_edge("journal:2026-10-12", "note:people/laura/profile", "mentions_person", "ai_link")
    create_edge("journal:2026-10-12", "expense:12", "related", "ai_link")  # unindexed neighbor

    [hit] = index.retrieve("dinner")
    assert hit["id"] == "journal:2026-10-12"
    neighbors = {(n["id"], n["edge_type"], n["title"]) for n in hit["neighbors"]}
    assert ("note:people/laura/profile", "mentions_person", "Laura") in neighbors
    assert ("expense:12", "related", "12") in neighbors  # falls back to the id's rest


def test_retrieve_without_a_graph_store_degrades_to_no_neighbors(tmp_path):
    import quintacle_core.graph as graph

    old = graph._store
    graph._store = None
    try:
        index = make_index(tmp_path)
        index.index_node("note:a/x", "note", "Alpha", body="hello")
        assert index.retrieve("hello")[0]["neighbors"] == []
    finally:
        graph._store = old


# --- exclusions: the vault stays invisible, conversations/ stays out ---


def test_excluded_ids_are_refused_at_the_index_chokepoint(tmp_path):
    index = make_index(tmp_path)
    assert is_excluded("vault:secrets")
    assert is_excluded("note:vault/anything")
    assert is_excluded("note:conversations/schemes/2026-10-19")
    assert is_excluded("journal:conversations/x")  # prefix rule holds for any type
    assert not is_excluded("note:organisation/document-vault/lease")  # a real KB folder, not the Vault

    assert index.index_node("note:conversations/schemes/2026-10-19", "note", "Transcript", body="yap yap") is False
    assert index.index_node("vault:secrets", "vault", "Secrets", body="hunter2") is False
    assert index.conn.execute("SELECT COUNT(*) AS n FROM nodes_index").fetchone()["n"] == 0


def test_backfill_never_indexes_vault_or_conversations(tmp_path):
    # The vault is OUTSIDE kb/ (structural invisibility) — plant a secret
    # there and a transcript under kb/conversations/; neither may surface.
    (tmp_path / "vault").mkdir(parents=True)
    (tmp_path / "vault" / "secrets.md").write_text("# Passwords\nhunter2", encoding="utf-8")
    conv_dir = tmp_path / "kb" / "conversations" / "schemes"
    conv_dir.mkdir(parents=True)
    (conv_dir / "2026-10-19.md").write_text("# Transcript\nraw yapping", encoding="utf-8")
    (tmp_path / "kb" / "fitness").mkdir(parents=True)
    (tmp_path / "kb" / "fitness" / "deadlift-cues.md").write_text("# Deadlift Cues\nBrace.", encoding="utf-8")

    counts = run_backfill(tmp_path)
    assert counts == {"note": 1}
    index = retrieval.get_retrieval_index()
    all_ids = [r["id"] for r in index.conn.execute("SELECT id FROM nodes_index")]
    assert all_ids == ["note:fitness/deadlift-cues"]
    assert index.retrieve("hunter2") == []
    assert index.retrieve("yapping") == []


# --- failure isolation of the hooks ---


def test_hooks_are_noops_when_retrieval_was_never_initialized():
    # No init_retrieval_index anywhere in this process (autouse fixture
    # reset it) — every safe_* hook must silently do nothing.
    retrieval.safe_index_note("fitness", "x", "X", "body")
    retrieval.safe_index_journal(date(2026, 10, 12), "content")
    retrieval.safe_index_log_row("expense:1")
    retrieval.safe_remove_node("todo:abc")


def test_an_indexing_error_never_fails_the_users_write(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())

    def boom(*args, **kwargs):
        raise RuntimeError("index exploded")

    monkeypatch.setattr(RetrievalIndex, "index_node", boom)

    res = client.post("/kb/entries", json={"folder": "Fitness", "title": "Deadlift Cues", "content": "Brace."})
    assert res.status_code == 200  # the save landed
    res = client.post("/logs/expenses", json={"date": "2026-10-12", "amount": 14.5, "merchant": "Chipotle"})
    assert res.status_code == 200
    res = client.post("/journal/2026-10-12", content="a day", headers={"content-type": "text/plain"})
    assert res.status_code == 200


# --- end to end over REST, on preset-seeded data ---


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())
    # Seed the registries first (CLAUDE.md: entity-grounded, never scratch):
    # a meal preset, a routine, a person, an experience.
    client.post("/logs/meals", json={"name": "Chipotle bowl", "kcal": 800, "protein_g": 45})
    client.post("/logs/routines", json={"name": "Pull Day", "exercises": ["Deadlift", "Pull Ups"]})
    client.post("/people", json={"name": "Laura", "category": "friend", "how_met": "college"})
    client.post(
        "/travel/experiences",
        json={"name": "Mia Italina Kitchen", "city": "Alexandria", "kind": "restaurant", "rating": "9/10"},
    )
    return client


def test_rest_writes_land_in_the_index_and_retrieve_finds_them(client):
    client.post("/logs/expenses", json={"date": "2026-10-12", "amount": 14.5, "merchant": "Chipotle", "category": "food"})
    client.post("/kb/entries", json={"folder": "Fitness", "title": "Deadlift Cues", "content": "Brace before you pull."})
    client.post("/journal/2026-10-12", content="Dinner with Laura at Mia Italina Kitchen.", headers={"content-type": "text/plain"})
    todo = client.post("/schedule/todos", json={"title": "Renew lease", "category": "home"}).json()

    res = client.get("/retrieve", params={"q": "chipotle"}).json()
    hit = res["results"][0]
    assert hit["id"].startswith("expense:")
    assert hit["summary"] == "Chipotle — $14.50 — food — 2026-10-12"

    # The preset registries themselves are retrievable nodes too.
    types_found = {r["type"] for r in client.get("/retrieve", params={"q": "chipotle bowl deadlift laura"}).json()["results"]}
    assert {"expense", "meal", "routine", "person", "note"} <= types_found

    # Graph expansion: the journal day's write-rule edges come back as labels.
    [day] = client.get("/retrieve", params={"q": "dinner", "types": "journal_day"}).json()["results"]
    neighbor_ids = {n["id"] for n in day["neighbors"]}
    assert "note:people/laura/profile" in neighbor_ids

    # Todo delete removes it from the index.
    assert client.get("/retrieve", params={"q": "lease"}).json()["results"]
    client.delete(f"/schedule/todos/{todo['id']}")
    assert client.get("/retrieve", params={"q": "lease", "types": "todo"}).json()["results"] == []


def test_rest_event_link_indexes_the_event_node(client):
    food = client.post("/logs/food", json={"date": "2026-10-12", "meal_type": "lunch", "freeform_kcal": 800, "notes": "chipotle bowl"}).json()
    expense = client.post("/logs/expenses", json={"date": "2026-10-12", "amount": 14.5, "merchant": "Chipotle"}).json()
    linked = client.post("/graph/event", json={"members": [f"food:{food['id']}", f"expense:{expense['id']}"], "date": "2026-10-12"}).json()

    [event] = client.get("/retrieve", params={"q": "event records", "types": "event"}).json()["results"]
    assert event["id"] == linked["event_id"]
    assert "2 records" in event["summary"]


# --- MCP: write hooks + the read-only search_index tool ---


def test_mcp_writes_feed_the_index_and_search_index_reads_it(tmp_path):
    from quintacle_core.mcp_server import server as s

    s.init(tmp_path)
    s.kb_create_entry(folder="Fitness", title="Deadlift Cues", content="Brace before you pull.")
    s.log_expense(for_date="2026-10-12", amount=14.5, merchant="Chipotle", category="food")
    s.journal_append(for_date="2026-10-12", content="Dinner with Laura.")
    todo = s.todo_create(title="Renew lease", category="home")

    hits = s.search_index(query="chipotle")
    assert hits[0]["summary"] == "Chipotle — $14.50 — food — 2026-10-12"
    assert {h["type"] for h in s.search_index(query="deadlift dinner lease")} == {"note", "journal_day", "todo"}
    assert s.search_index(query="deadlift", types=["journal_day"]) == []

    s.todo_delete(todo_id=todo["id"])
    assert s.search_index(query="lease", types=["todo"]) == []


# --- backfill: idempotent, whole store, per-type counts ---


def test_backfill_walks_the_whole_store_and_is_idempotent(tmp_path, monkeypatch):
    # Build a store through the real app (preset-seeded), then wipe the
    # index tables and prove the backfill reconstructs everything.
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())
    client.post("/logs/meals", json={"name": "Chipotle bowl", "kcal": 800, "protein_g": 45})
    client.post("/logs/routines", json={"name": "Pull Day", "exercises": ["Deadlift", "Pull Ups"]})
    client.post("/people", json={"name": "Laura", "category": "friend"})
    client.post("/travel/experiences", json={"name": "Mia Italina Kitchen", "city": "Alexandria", "kind": "restaurant"})
    client.post("/kb/entries", json={"folder": "Fitness", "title": "Deadlift Cues", "content": "Brace."})
    client.post("/journal/2026-10-12", content="Dinner with Laura.", headers={"content-type": "text/plain"})
    client.post("/schedule/todos", json={"title": "Renew lease"})
    food = client.post("/logs/food", json={"date": "2026-10-12", "meal_type": "lunch", "meal_id": 1, "notes": ""}).json()
    expense = client.post("/logs/expenses", json={"date": "2026-10-12", "amount": 14.5, "merchant": "Chipotle"}).json()
    client.post("/graph/event", json={"members": [f"food:{food['id']}", f"expense:{expense['id']}"], "date": "2026-10-12"})

    conn = retrieval.get_retrieval_index().conn
    conn.execute("DELETE FROM nodes_index")
    conn.execute("DELETE FROM nodes_fts")
    conn.commit()

    counts = run_backfill(tmp_path)
    assert counts["note"] == 1
    assert counts["journal_day"] == 1
    assert counts["person"] == 1
    assert counts["experience"] == 1
    assert counts["todo"] == 1
    assert counts["meal"] == 1
    assert counts["routine"] == 1
    assert counts["food"] == 1
    assert counts["expense"] == 1
    assert counts["event"] == 1

    assert run_backfill(tmp_path) == counts  # idempotent — same totals, no duplicates

    index = retrieval.get_retrieval_index()
    assert index.retrieve("chipotle", types=["expense"])[0]["summary"] == "Chipotle — $14.50 — 2026-10-12"
    assert index.get_node("note:people/laura/profile")["type"] == "person"
