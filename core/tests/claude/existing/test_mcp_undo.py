import sqlite3
from datetime import date

from quintacle_core.mcp_server.ledger import Ledger
from quintacle_core.mcp_server.undo import WriteSession, undo
from quintacle_core.nodes.journal.store import JournalStore


def make_ledger(tmp_path):
    return Ledger(tmp_path / "mcp-log.md")


def test_file_step_undoes_a_fresh_create(tmp_path):
    ledger = make_ledger(tmp_path)
    target = tmp_path / "note.md"
    session = WriteSession(ledger, tool="kb.create_entry", client="test", summary="made a note")
    session.stage_file(target)  # didn't exist yet
    target.write_text("# Note\n\nbody")
    entry_id = session.commit()

    assert target.exists()
    undo(ledger, entry_id)
    assert not target.exists()


def test_file_step_undoes_an_edit_back_to_prior_bytes(tmp_path):
    ledger = make_ledger(tmp_path)
    target = tmp_path / "note.md"
    target.write_text("original")
    session = WriteSession(ledger, tool="kb.edit", client="test", summary="edited a note")
    session.stage_file(target)
    target.write_text("overwritten")
    entry_id = session.commit()

    undo(ledger, entry_id)
    assert target.read_text() == "original"


def test_journal_append_undo_leaves_other_appends_alone(tmp_path):
    ledger = make_ledger(tmp_path)
    store = JournalStore(tmp_path / "journal")
    d = date(2026, 10, 13)

    store.save(d, "not from mcp, no marker")

    session1 = WriteSession(ledger, tool="journal.append", client="test", summary="first mcp append")
    store.save(d, "first mcp dump", marker="marker-one")
    session1.stage_journal_append(store.root, d, "marker-one")
    entry1 = session1.commit()

    session2 = WriteSession(ledger, tool="journal.append", client="test", summary="second mcp append")
    store.save(d, "second mcp dump", marker="marker-two")
    session2.stage_journal_append(store.root, d, "marker-two")
    entry2 = session2.commit()

    undo(ledger, entry1)

    content = store.load(d)
    assert "not from mcp, no marker" in content
    assert "first mcp dump" not in content
    assert "second mcp dump" in content

    # undoing an already-undone entry is an error, not a silent no-op
    import pytest

    with pytest.raises(ValueError):
        undo(ledger, entry1)

    undo(ledger, entry2)
    content = store.load(d)
    assert "not from mcp, no marker" in content
    assert "mcp dump" not in content
    assert "---" not in content  # no other entry left to separate from


def test_journal_append_undo_deletes_file_if_it_was_the_only_entry(tmp_path):
    ledger = make_ledger(tmp_path)
    store = JournalStore(tmp_path / "journal")
    d = date(2026, 10, 13)

    session = WriteSession(ledger, tool="journal.append", client="test", summary="only entry")
    store.save(d, "the only dump", marker="solo-marker")
    session.stage_journal_append(store.root, d, "solo-marker")
    entry_id = session.commit()

    assert store.load(d) is not None
    undo(ledger, entry_id)
    assert store.load(d) is None


def test_sqlite_row_step_undoes_an_insert(tmp_path):
    ledger = make_ledger(tmp_path)
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE expense_log (id INTEGER PRIMARY KEY, amount REAL)")
    conn.commit()

    session = WriteSession(ledger, tool="logs.log_expense", client="test", summary="logged an expense")
    cur = conn.execute("INSERT INTO expense_log (amount) VALUES (?)", (12.5,))
    conn.commit()
    row_id = cur.lastrowid
    session.stage_sqlite_insert(db_path, "expense_log", "id", row_id)
    entry_id = session.commit()

    undo(ledger, entry_id)
    conn2 = sqlite3.connect(db_path)
    assert conn2.execute("SELECT * FROM expense_log").fetchall() == []


def test_multi_part_push_undoes_as_one_unit(tmp_path):
    ledger = make_ledger(tmp_path)
    note_path = tmp_path / "car.md"
    receipt_path = tmp_path / "receipt.md"

    session = WriteSession(ledger, tool="kb.create_entry", client="test", summary="car + receipt, one push")
    session.stage_file(note_path)
    note_path.write_text("car note")
    session.stage_file(receipt_path)
    receipt_path.write_text("receipt note")
    entry_id = session.commit()

    assert note_path.exists() and receipt_path.exists()
    undo(ledger, entry_id)
    assert not note_path.exists() and not receipt_path.exists()


def test_ledger_renders_readable_markdown_and_marks_undone_in_place(tmp_path):
    ledger = make_ledger(tmp_path)
    target = tmp_path / "note.md"
    session = WriteSession(ledger, tool="kb.create_entry", client="claude-code", summary="Created KB entry 'Test'")
    session.stage_file(target)
    target.write_text("hi")
    entry_id = session.commit(result={"folder": "test", "slug": "test"})

    text = ledger.path.read_text()
    assert "# Quintacle MCP write ledger" in text
    assert "kb.create_entry" in text
    assert "client: claude-code" in text
    assert "status: active" in text

    undo(ledger, entry_id)
    text = ledger.path.read_text()
    assert "status: active" not in text
    assert "undone at" in text
    # exactly one entry, still — undo updates it in place, doesn't duplicate
    assert len(ledger.all()) == 1
