import pytest

from quintacle_core.mcp_server import server as s


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path):
    """Every test gets its own on-disk data dir — server.init() repoints the
    module-level stores the @mcp.tool() functions call into."""
    s.init(tmp_path)
    yield


def test_journal_append_and_get_round_trip():
    result = s.journal_append(for_date="2026-10-13", content="worked on the MCP server today")

    assert result["date"] == "2026-10-13"
    assert "ledger_id" in result
    loaded = s.journal_get(for_date="2026-10-13")
    assert "worked on the MCP server today" in loaded["content"]


def test_journal_append_is_undoable_without_losing_other_entries():
    first = s.journal_append(for_date="2026-10-13", content="morning check-in")
    s.journal_append(for_date="2026-10-13", content="evening check-in")

    s.undo_write(first["ledger_id"])

    content = s.journal_get(for_date="2026-10-13")["content"]
    assert "morning check-in" not in content
    assert "evening check-in" in content


def test_kb_create_get_search_and_list_folders_round_trip():
    created = s.kb_create_entry(
        folder="Organisation/Car",
        title="Sway bar links replaced",
        content="184k miles, $220, DIY.",
        links=["2026-10-13"],
        fields={"mileage": "184000", "cost": "220"},
    )

    assert created["folder"] == "organisation/car"
    assert created["slug"] == "sway-bar-links-replaced"

    assert created["folder"] in s.kb_list_folders()

    entry = s.kb_get_entry(folder=created["folder"], slug=created["slug"])
    assert entry["title"] == "Sway bar links replaced"
    assert entry["fields"]["mileage"] == "184000"
    assert s.kb_store.read_links(created["folder"], created["slug"]) == ["2026-10-13"]

    hits = s.kb_search_entries(query="sway bar")
    assert any(h["slug"] == created["slug"] for h in hits)


def test_kb_create_entry_is_undoable():
    created = s.kb_create_entry(folder="Temp", title="Scratch note", content="delete me")
    assert s.kb_get_entry(folder=created["folder"], slug=created["slug"]) is not None

    s.undo_write(created["ledger_id"])

    with pytest.raises(ValueError):
        s.kb_get_entry(folder=created["folder"], slug=created["slug"])


def test_log_expense_and_list_in_range_round_trip():
    logged = s.log_expense(for_date="2026-10-13", amount=14.5, merchant="Chipotle", category="dining")

    rows = s.expenses_in_range(start="2026-10-01", end="2026-10-31")
    assert len(rows) == 1
    assert rows[0]["id"] == logged["expense_id"]
    assert rows[0]["merchant"] == "Chipotle"
    assert rows[0]["amount"] == 14.5


def test_log_expense_is_undoable_in_both_sqlite_and_markdown():
    from quintacle_core.markdown_paths import resolve_nested
    from quintacle_core.nodes.logs.log_store import home_for

    logged = s.log_expense(for_date="2026-10-13", amount=9.99, merchant="Netflix", category="subscription", kind="subscription")
    logs_dir = resolve_nested(s.log_file_store.kb_root, home_for("finance")) / "logs"
    markdown_files_before_undo = list(logs_dir.glob("2026-10-13-*.md"))
    assert len(markdown_files_before_undo) == 1

    assert s.expenses_in_range(start="2026-10-01", end="2026-10-31") != []

    s.undo_write(logged["ledger_id"])

    assert s.expenses_in_range(start="2026-10-01", end="2026-10-31") == []
    assert list(logs_dir.glob("2026-10-13-*.md")) == []


def test_todo_create_update_delete_list_and_undo():
    created = s.todo_create(title="Buy groceries", priority=3, due_date="2026-10-15")
    assert any(t["id"] == created["id"] for t in s.todo_list())

    updated = s.todo_update(todo_id=created["id"], done=True)
    assert updated["done"] is True
    assert all(t["id"] != created["id"] for t in s.todo_list())  # done todos excluded by default
    assert any(t["id"] == created["id"] for t in s.todo_list(include_done=True))

    s.undo_write(updated["ledger_id"])
    restored = next(t for t in s.todo_list(include_done=True) if t["id"] == created["id"])
    assert restored["done"] is False

    deleted = s.todo_delete(todo_id=created["id"])
    assert deleted["deleted"] == created["id"]
    assert all(t["id"] != created["id"] for t in s.todo_list(include_done=True))

    s.undo_write(deleted["ledger_id"])
    assert any(t["id"] == created["id"] for t in s.todo_list(include_done=True))


def test_each_write_tool_call_produces_exactly_one_ledger_entry():
    before_count = len(s.list_recent_writes(limit=1000))
    s.kb_create_entry(folder="Car", title="Maintenance log", content="engine stuff")
    after_count = len(s.list_recent_writes(limit=1000))
    assert after_count == before_count + 1  # grouping multiple staged steps into one entry is exercised at the
    # WriteSession level in test_mcp_undo.py's test_multi_part_push_undoes_as_one_unit — no tool in this
    # first pass actually creates more than one thing per call to exercise it end-to-end here.


def test_list_recent_writes_shows_newest_first_and_undo_status():
    first = s.todo_create(title="first")
    second = s.todo_create(title="second")

    recent = s.list_recent_writes(limit=2)
    assert recent[0]["id"] == second["ledger_id"]
    assert recent[1]["id"] == first["ledger_id"]
    assert recent[0]["undone_at"] is None

    s.undo_write(first["ledger_id"])
    recent = s.list_recent_writes(limit=2)
    undone_entry = next(e for e in recent if e["id"] == first["ledger_id"])
    assert undone_entry["undone_at"] is not None


# --- MCP write -> graph edge seam (graph_link.py adapter) ---


def test_mcp_write_creates_graph_edges_and_undo_removes_them(tmp_path):
    from quintacle_core.graph import get_graph_store
    from quintacle_core.nodes.people.store import PersonStore

    # A known person the keyword linker should match against.
    PersonStore(tmp_path / "kb").write("Alex", "friend", how_met="college")

    created = s.kb_create_entry(
        folder="Planning/Travel",
        title="Houston trip",
        content="Planned the Houston bars crawl with Alex.",
    )
    note_id = f"note:{created['folder']}/{created['slug']}"

    store = get_graph_store()
    edges = store.edges_from(note_id) if hasattr(store, "edges_from") else store.conn.execute(
        "SELECT * FROM edges WHERE source_id = ?", (note_id,)
    ).fetchall()
    edges = [dict(e) for e in edges]
    assert any(e["kind"] == "mentions_person" for e in edges), edges

    edge_files = list((tmp_path / "graph" / "edges").glob("*.md"))
    assert edge_files

    # Undoing the push removes the edge files AND their SQLite rows, not
    # just the note.
    s.undo_write(created["ledger_id"])
    assert not list((tmp_path / "graph" / "edges").glob("*.md"))
    remaining = store.conn.execute("SELECT * FROM edges WHERE source_id = ?", (note_id,)).fetchall()
    assert remaining == []


def test_mcp_declared_links_materialize_as_edges(tmp_path):
    s.journal_append(for_date="2026-10-12", content="long day")
    created = s.kb_create_entry(
        folder="Planning/Travel",
        title="Flight booking",
        content="Booked the flight.",
        links=["2026-10-12"],
    )
    note_id = f"note:{created['folder']}/{created['slug']}"
    from quintacle_core.graph import get_graph_store

    rows = [dict(r) for r in get_graph_store().conn.execute("SELECT * FROM edges WHERE source_id = ?", (note_id,)).fetchall()]
    assert any(r["target_id"] == "journal:2026-10-12" and r["kind"] == "on_day" for r in rows), rows
