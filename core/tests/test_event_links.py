"""Same-event provenance (graph_capture.link_event + POST /graph/event +
the MCP link_event tool): every batch of records committed from one capture
is ONE real-world event, interlinked by construction — a shared event node —
never by keyword inference. Covers the deterministic event-id dedupe, the
guards, /graph's lazy event/log-row emission, the day bundle's `events`
grouping, and the MCP write + undo round trip."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.day_bundle import day_events
from quintacle_core.db import connect
from quintacle_core.graph import init_graph_store, neighborhood
from quintacle_core.graph_capture import event_id_for, link_event, log_row_label
from quintacle_core.mcp_server import server as s
from quintacle_core.nodes.journal.store import JournalStore


@pytest.fixture
def graph_env(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))
    return tmp_path


# --- the core function (one implementation, two doors) ---


def test_link_event_creates_part_of_edges_with_same_event_provenance(graph_env):
    result = link_event(["expense:12", "food:7", "note:planning/x"])

    assert result["event_id"].startswith("event:")
    assert result["edges_created"] == 3
    assert result["skipped"] == []

    store_conn = connect(graph_env / "test.db")
    rows = store_conn.execute("SELECT * FROM edges").fetchall()
    assert {r["source_id"] for r in rows} == {"expense:12", "food:7", "note:planning/x"}
    assert {r["target_id"] for r in rows} == {result["event_id"]}
    assert {r["kind"] for r in rows} == {"part_of"}
    assert {r["source_of_edge"] for r in rows} == {"same_event"}


def test_event_id_is_deterministic_hash_of_sorted_members_and_date(graph_env):
    # Order-independent, date-sensitive — the dedupe contract.
    assert event_id_for(["food:7", "expense:12"], None) == event_id_for(["expense:12", "food:7"], None)
    assert event_id_for(["food:7", "expense:12"], None) != event_id_for(["expense:12", "food:7"], date(2026, 10, 15))

    first = link_event(["expense:12", "food:7"])
    assert first["event_id"] == event_id_for(["expense:12", "food:7"], None)


def test_resave_of_same_batch_never_double_mints(graph_env):
    first = link_event(["expense:12", "food:7"])
    again = link_event(["food:7", "expense:12"])  # retried Save, different order

    assert again["event_id"] == first["event_id"]
    assert again["edges_created"] == 0
    edge_files = list((graph_env / "graph" / "edges").glob("*.md"))
    assert len(edge_files) == 2  # still just the first call's two edges


def test_fewer_than_two_members_is_a_noop(graph_env):
    assert link_event([]) == {"event_id": None, "edges_created": 0, "skipped": []}
    assert link_event(["expense:12"])["event_id"] is None
    # Duplicates collapse BEFORE the guard — one real member is not a grouping.
    assert link_event(["expense:12", "expense:12"])["event_id"] is None
    assert not (graph_env / "graph" / "edges").exists() or not list((graph_env / "graph" / "edges").glob("*.md"))


def test_malformed_ids_are_skipped_with_a_warning_list(graph_env):
    result = link_event(["expense:12", "no-colon-here", ":missing-type", "food:", "food:7", "bad type:x"])

    assert result["edges_created"] == 2
    assert result["skipped"] == ["no-colon-here", ":missing-type", "food:", "bad type:x"]
    store_conn = connect(graph_env / "test.db")
    sources = {r["source_id"] for r in store_conn.execute("SELECT source_id FROM edges")}
    assert sources == {"expense:12", "food:7"}


def test_on_day_edge_only_when_journal_day_exists(graph_env):
    JournalStore(graph_env / "journal").save(date(2026, 10, 15), "burrito day")

    linked = link_event(["expense:12", "food:7"], date(2026, 10, 15))
    unlinked = link_event(["expense:13", "food:8"], date(2026, 10, 16))  # no journal that day

    store_conn = connect(graph_env / "test.db")
    on_day = store_conn.execute("SELECT * FROM edges WHERE kind = 'on_day'").fetchall()
    assert len(on_day) == 1
    assert on_day[0]["source_id"] == linked["event_id"]
    assert on_day[0]["target_id"] == "journal:2026-10-15"
    assert on_day[0]["source_of_edge"] == "same_event"
    assert linked["edges_created"] == 3  # 2 part_of + 1 on_day
    assert unlinked["edges_created"] == 2  # part_of only


# --- log-row labels (shared by /graph and the day bundle) ---


def test_log_row_label_reads_the_real_sqlite_rows(tmp_path):
    conn = connect(tmp_path / "test.db")
    conn.execute("INSERT INTO expense_log (id, date, amount, merchant) VALUES (1, '2026-10-15', 14.5, 'Chipotle')")
    conn.execute("INSERT INTO meals (id, name, kcal) VALUES (3, 'Chipotle bowl', 800)")
    conn.execute("INSERT INTO food_log (id, date, meal_type, meal_id, notes) VALUES (2, '2026-10-15', 'lunch', 3, '')")
    conn.execute(
        "INSERT INTO exercise_sets (id, date, exercise_name, performance_text) VALUES (4, '2026-10-15', 'Bench Press', '')"
    )
    conn.commit()

    assert log_row_label(conn, "expense:1") == "$14.50 Chipotle"
    assert log_row_label(conn, "food:2") == "Chipotle bowl"  # notes empty -> preset name
    assert log_row_label(conn, "exercise:4") == "Bench Press"
    assert log_row_label(conn, "expense:999") is None  # stale edge, row gone
    assert log_row_label(conn, "exercise:Bench Press") is None  # name-keyed routine node, not a row
    assert log_row_label(conn, "note:a/b") is None


# --- end to end over REST: commit twins, link, walk, surface ---


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


def test_rest_end_to_end_chipotle_twins_know_each_other(client):
    # One capture: "chipotle 14.50" is correctly both a food row and an
    # expense row — committed through their own endpoints, then linked.
    client.post("/journal/2026-10-15", content="chipotle day", headers={"content-type": "text/plain"})
    food = client.post(
        "/logs/food", json={"date": "2026-10-15", "meal_type": "lunch", "freeform_kcal": 800, "notes": "chipotle bowl"}
    ).json()
    expense = client.post("/logs/expenses", json={"date": "2026-10-15", "amount": 14.5, "merchant": "Chipotle"}).json()

    res = client.post(
        "/graph/event",
        json={"members": [f"expense:{expense['id']}", f"food:{food['id']}"], "date": "2026-10-15"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["edges_created"] == 3  # 2 part_of + on_day (journal exists)
    assert body["skipped"] == []

    # The twins reach each other through their shared birth certificate.
    walk = neighborhood(f"expense:{expense['id']}", 2)
    assert body["event_id"] in walk["nodes"]
    assert f"food:{food['id']}" in walk["nodes"]

    # Re-POSTing the same batch (a retried Save) is a no-op, same event id.
    again = client.post(
        "/graph/event",
        json={"members": [f"food:{food['id']}", f"expense:{expense['id']}"], "date": "2026-10-15"},
    ).json()
    assert again["event_id"] == body["event_id"]
    assert again["edges_created"] == 0


def test_graph_view_emits_event_and_log_row_nodes_and_clamp_holds(client):
    client.post("/journal/2026-10-15", content="chipotle day", headers={"content-type": "text/plain"})
    food = client.post(
        "/logs/food", json={"date": "2026-10-15", "meal_type": "lunch", "freeform_kcal": 800, "notes": "chipotle bowl"}
    ).json()
    expense = client.post("/logs/expenses", json={"date": "2026-10-15", "amount": 14.5, "merchant": "Chipotle"}).json()
    event = client.post(
        "/graph/event",
        json={"members": [f"expense:{expense['id']}", f"food:{food['id']}", "bogus:999"], "date": "2026-10-15"},
    ).json()

    graph = client.get("/graph").json()
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}

    event_node = nodes_by_id[event["event_id"]]
    assert event_node["type"] == "event"
    assert event_node["label"] == "event · 2026-10-15"

    assert nodes_by_id[f"expense:{expense['id']}"]["label"] == "$14.50 Chipotle"
    assert nodes_by_id[f"expense:{expense['id']}"]["type"] == "expense"
    assert nodes_by_id[f"food:{food['id']}"]["label"] == "chipotle bowl"

    # "bogus:999" has no node — the clamp keeps its stored edge out of the view.
    assert "bogus:999" not in nodes_by_id
    emitted = {n["id"] for n in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["source"] in emitted and edge["target"] in emitted
    event_edges = [e for e in graph["edges"] if e["target"] == event["event_id"] and e["kind"] == "part_of"]
    assert {e["source"] for e in event_edges} == {f"expense:{expense['id']}", f"food:{food['id']}"}
    assert {"source": event["event_id"], "target": "journal:2026-10-15", "kind": "on_day"} in graph["edges"]


def test_undated_event_label_falls_back_to_member_count(client):
    client.post("/graph/event", json={"members": ["expense:1", "food:2"]})
    # Rows don't exist for these ids — the event node still appears; the
    # unresolvable members just aren't drawn.
    graph = client.get("/graph").json()
    event_nodes = [n for n in graph["nodes"] if n["type"] == "event"]
    assert len(event_nodes) == 1
    assert event_nodes[0]["label"] == "event · 2 entries"


def test_day_bundle_groups_the_days_events_with_labels(client):
    client.post("/journal/2026-10-15", content="chipotle day", headers={"content-type": "text/plain"})
    food = client.post(
        "/logs/food", json={"date": "2026-10-15", "meal_type": "lunch", "freeform_kcal": 800, "notes": "chipotle bowl"}
    ).json()
    expense = client.post("/logs/expenses", json={"date": "2026-10-15", "amount": 14.5, "merchant": "Chipotle"}).json()
    note = client.post(
        "/kb/entries", json={"folder": "Planning", "title": "Burrito run", "content": "lunch at Chipotle"}
    ).json()
    event = client.post(
        "/graph/event",
        json={
            "members": [f"expense:{expense['id']}", f"food:{food['id']}", f"note:{note['folder']}/{note['slug']}"],
            "date": "2026-10-15",
        },
    ).json()

    bundle = client.get("/day/2026-10-15").json()
    assert len(bundle["events"]) == 1
    day_event = bundle["events"][0]
    assert day_event["event_id"] == event["event_id"]
    members = {m["id"]: m["label"] for m in day_event["members"]}
    assert members == {
        f"expense:{expense['id']}": "$14.50 Chipotle",
        f"food:{food['id']}": "chipotle bowl",
        f"note:{note['folder']}/{note['slug']}": "Burrito run",
    }
    # Deterministic: members come back sorted by id.
    assert [m["id"] for m in day_event["members"]] == sorted(members)

    # A day with no linked events has an empty, not missing, list.
    assert client.get("/day/2026-10-16").json()["events"] == []


def test_day_events_is_deterministic_across_calls(graph_env):
    JournalStore(graph_env / "journal").save(date(2026, 10, 15), "busy day")
    link_event(["expense:1", "food:2"], date(2026, 10, 15))
    link_event(["activity:3", "note:a/b"], date(2026, 10, 15))

    from quintacle_core.graph import get_graph_store
    from quintacle_core.nodes.kb.store import KBStore
    from quintacle_core.nodes.schedule.store import TodoStore

    conn = get_graph_store().conn
    kb = KBStore(graph_env / "kb")
    todos = TodoStore(graph_env / "schedule" / "todos")
    first = day_events(date(2026, 10, 15), conn, kb, todos)
    assert first == day_events(date(2026, 10, 15), conn, kb, todos)
    assert [e["event_id"] for e in first] == sorted(e["event_id"] for e in first)
    # Unresolvable members degrade to their id as the label, never a crash.
    labels = {m["id"]: m["label"] for e in first for m in e["members"]}
    assert labels["note:a/b"] == "note:a/b"


# --- MCP parity: same implementation, staged for undo ---


@pytest.fixture
def mcp_stores(tmp_path):
    s.init(tmp_path)
    yield tmp_path


def test_mcp_link_event_round_trip_and_undo_removes_the_events_edges(mcp_stores):
    s.journal_append(for_date="2026-10-15", content="chipotle day")
    expense = s.log_expense(for_date="2026-10-15", amount=14.5, merchant="Chipotle")
    members = [f"expense:{expense['expense_id']}", "food:7"]

    result = s.link_event(members=members, for_date="2026-10-15")
    assert result["edges_created"] == 3  # 2 part_of + on_day
    assert "ledger_id" in result

    event_edges = s.db_conn.execute(
        "SELECT id FROM edges WHERE source_id = ? OR target_id = ?", (result["event_id"], result["event_id"])
    ).fetchall()
    assert len(event_edges) == 3

    # Re-linking the same batch is a no-op and writes NO ledger entry.
    again = s.link_event(members=list(reversed(members)), for_date="2026-10-15")
    assert again["edges_created"] == 0
    assert "ledger_id" not in again

    undone = s.undo_write(ledger_id=result["ledger_id"])
    assert undone["undone_at"] is not None
    remaining = s.db_conn.execute(
        "SELECT id FROM edges WHERE source_id = ? OR target_id = ?", (result["event_id"], result["event_id"])
    ).fetchall()
    assert remaining == []
    event_files = [
        p for p in (mcp_stores / "graph" / "edges").glob("*.md") if result["event_id"] in p.read_text(encoding="utf-8")
    ]
    assert event_files == []


def test_mcp_link_event_noop_under_two_members_writes_nothing(mcp_stores):
    before = s.ledger.recent(50)
    result = s.link_event(members=["expense:1"])
    assert result == {"event_id": None, "edges_created": 0, "skipped": []}
    assert len(s.ledger.recent(50)) == len(before)
