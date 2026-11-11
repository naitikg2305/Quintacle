"""MCP-server checks for the LIVE suites: the tools the owner calls from
Claude sessions (quintacle_core/mcp_server/server.py), exercised in-process
on the SANDBOX data dir that harness.make_client set up.

Expectations encode the product contract (CLAUDE.md: "MCP: auto-write but
every push is one ledger entry with staged-snapshot undo"; private notes are
invisible to every model-facing surface), fixed up front — a failure is a
finding about the code, never a reason to re-fit the expectation.

Data-dir resolution: server.py runs `init()` AT IMPORT, reading
QUINTACLE_DATA_DIR once into module globals (DATA_DIR, kb_store, ledger,
db_conn, ...). The @mcp.tool functions look those globals up at call time,
so `load_server()` (a) imports only AFTER make_client set the sandbox env and
(b) calls `server.init(sandbox)` explicitly anyway, because the module may
already be cached in sys.modules from an earlier import with another env.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from quintacle_core import clock
from tests.claude.harness import REAL_STORE

# --- the end-to-end (real Claude) case, used by subscription_or_api/test_mcp_max.py
E2E_PROMPT = "save a note titled 'MCP live test' in folder Tests/MCP saying hello"
E2E_FOLDER = "Tests/MCP"
E2E_SLUG = "mcp-live-test"
E2E_TITLE = "MCP live test"
E2E_CLIENT = "claude-code-live-test"  # QUINTACLE_MCP_CLIENT for the sandbox server
CORE_DIR = Path(__file__).resolve().parents[2]


def assert_sandbox(data: Path) -> Path:
    """Refuse to run anything MCP against the owner's real store."""
    data = Path(data).resolve()
    real = REAL_STORE.resolve()
    assert data != real and real not in data.parents, f"refusing to point MCP at the real store: {data}"
    return data


def sandbox_dir() -> Path:
    return assert_sandbox(Path(os.environ["QUINTACLE_DATA_DIR"]))


def load_server():
    """The MCP server module, re-pointed at the sandbox (see module doc)."""
    data = sandbox_dir()
    from quintacle_core.mcp_server import server as s  # import-time init() reads the (sandbox) env

    s.init(data)  # explicit: a cached import would still hold the old DATA_DIR/stores
    assert Path(s.DATA_DIR).resolve() == data
    assert Path(s.ledger.path).resolve().is_relative_to(data)
    return s


def _ids(results: list[dict]) -> list[str]:
    return [r.get("id") for r in results]


# --- checks: each takes (client, server) ------------------------------------


def check_create_get_ledger_undo(c, s):
    """Round-trip, then ledger + undo: CLAUDE.md requires every MCP push to be one ledger entry with snapshot undo."""
    title, body = "Torque spec for the brake calipers", "Caliper bracket bolts: 80 ft-lb. Slider pins: 25 ft-lb."
    created = s.kb_create_entry(folder="Organisation/Car", title=title, content=body)
    # Folder/slug are slugified the same way every KB write path does.
    assert (created["folder"], created["slug"]) == ("organisation/car", "torque-spec-for-the-brake-calipers"), created
    assert created.get("ledger_id"), "every MCP write must return its ledger id (undo handle)"

    entry = s.kb_get_entry(folder=created["folder"], slug=created["slug"])
    # A structured write stores exactly what was passed — no AI rewrite.
    assert entry["title"] == title, entry
    assert "80 ft-lb" in entry["content"] and "25 ft-lb" in entry["content"], entry["content"]

    recent = s.list_recent_writes(limit=5)
    # Newest first, and it is this push, still active.
    assert recent and recent[0]["id"] == created["ledger_id"], [r["id"] for r in recent]
    assert recent[0]["tool"] == "kb.create_entry" and recent[0]["undone_at"] is None, recent[0]
    assert recent[0]["result"] == {"folder": created["folder"], "slug": created["slug"]}, recent[0]

    s.undo_write(ledger_id=created["ledger_id"])
    # Undo restores "before": the note did not exist, so it must be gone.
    with pytest.raises(ValueError, match="no such entry"):
        s.kb_get_entry(folder=created["folder"], slug=created["slug"])
    assert not s.kb_store.entry_path(created["folder"], created["slug"]).exists()
    assert not any(h["slug"] == created["slug"] for h in s.kb_search_entries(query="caliper bracket"))
    # The ledger is append-only: the entry stays, flagged undone (not deleted).
    after = next(r for r in s.list_recent_writes(limit=20) if r["id"] == created["ledger_id"])
    assert after["undone_at"] is not None, after


def check_private_note_invisible(c, s):
    """Private notes must read over MCP exactly like a missing note (every MCP client is a cloud model)."""
    folder, title, word = "Personal/Health", "Therapist session notes", "zephyrquartz"
    r = c.post("/kb/entries", json={"folder": folder, "title": title, "content": f"Private thoughts, codeword {word}.", "private": True})
    assert r.status_code == 200, r.text
    fs, slug = r.json()["folder"], r.json()["slug"]
    assert s.kb_store.is_private(fs, slug), "precondition: the app saved it private"

    # Substring search over every note must skip it.
    assert s.kb_search_entries(query=word) == []
    assert s.kb_search_entries(query="therapist session") == []
    # The ranked index (search_index) is model-facing too.
    assert not any(slug in (i or "") for i in _ids(s.search_index(query=word))), "private note leaked via search_index"
    # Get: the SAME message a genuinely missing note gets, so even its existence doesn't leak.
    with pytest.raises(ValueError) as private_err:
        s.kb_get_entry(folder=fs, slug=slug)
    with pytest.raises(ValueError) as missing_err:
        s.kb_get_entry(folder=fs, slug="no-such-note-here")
    assert str(private_err.value) == f"no such entry: {fs}/{slug}"
    assert str(missing_err.value) == f"no such entry: {fs}/no-such-note-here"


def check_day_recall(c, s):
    """day_recall must bundle today's note + expense, but never chats (MCP passes no conversations root) or private notes."""
    today = clock.today().isoformat()  # notes_saved keys off the ET `edited` stamp
    pub = c.post("/kb/entries", json={"folder": "Knowledge/Recipes", "title": "Cold brew ratio", "content": "1:8 coarse grind, 16 hours in the fridge."})
    assert pub.status_code == 200, pub.text
    priv = c.post("/kb/entries", json={"folder": "Personal/Journal Extras", "title": "Salary negotiation worries", "content": "Nervous about the offer.", "private": True})
    assert priv.status_code == 200, priv.text
    exp = c.post("/logs/expenses", json={"date": today, "amount": 6.75, "merchant": "Blue Bottle Coffee", "category": "coffee"})
    assert exp.status_code == 200, exp.text
    # An archived chat from today, in the layout transcripts.py writes.
    chat = s.DATA_DIR / "conversations" / "cold-brew-chat" / f"{today}-0930.md"
    chat.parent.mkdir(parents=True, exist_ok=True)
    chat.write_text("### You\nquokkaberry: how strong should cold brew be?\n\n### Claude\nTry 1:8.\n", encoding="utf-8")

    bundle = s.day_recall(for_date=today)
    blob = json.dumps(bundle, default=str)
    assert bundle["date"] == today
    titles = [n["title"] for n in bundle["notes_saved"]]
    # Saved today -> part of today's recall.
    assert "Cold brew ratio" in titles, titles
    # Private notes never leave over MCP (not even the title or the flag).
    assert "Salary negotiation worries" not in titles and "Salary negotiation" not in blob, titles
    assert all("private" not in n for n in bundle["notes_saved"])
    # The finance row logged for today is in the day, with code-computed money totals.
    assert any(e.get("merchant") == "Blue Bottle Coffee" and abs(float(e["amount"]) - 6.75) < 1e-9 for e in bundle["expenses"]), bundle["expenses"]
    assert bundle["money"]["spent"] >= 6.75, bundle["money"]
    # Chats are never exposed over MCP, even when a transcript exists that day.
    assert bundle.get("chats", []) == [], bundle.get("chats")
    assert "quokkaberry" not in blob


def check_search_index_finds_seeded_note(c, s):
    """'Nikko' appears only in the seeded 'Tokyo spring plan' note, so FTS must return that note first."""
    want = "note:fun/travel/planned/japan/tokyo-spring-plan"
    hits = s.search_index(query="Nikko")
    # The only record containing the word must be returned, ranked first.
    assert hits and hits[0]["id"] == want, _ids(hits)
    assert hits[0]["type"] == "note" and hits[0]["title"] == "Tokyo spring plan", hits[0]
    # The types filter keeps it (it IS a note).
    assert want in _ids(s.search_index(query="Nikko", types=["note"]))


ALL = [
    check_create_get_ledger_undo,
    check_private_note_invisible,
    check_day_recall,
    check_search_index_finds_seeded_note,
]
