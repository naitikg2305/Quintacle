"""The soft record — docs/next-wave-plan.md §12 (2026-10-27).

A single running log of STRAIGHT FACTS the user stated in archived chats
("I'm switching to a 4-day split", "my knee has been sore since Tuesday"),
each carrying its date (Eastern Time) and the path of the transcript it came
from — checkable, or it is slop. It is the cheap "knows you" layer for
unserious chat mode and it NEVER becomes KB knowledge without an explicit
Record that.

Storage: `<data_dir>/conversations/soft_record.db` (its own sqlite file, next
to transcripts.db). Like the transcript archive it lives OUTSIDE `kb/` and is
never indexed into the main retrieval index or the graph — structurally
invisible to /kb/*, MCP kb tools and /retrieve. Only chat's unserious-mode
context (read-only) and the /soft-record endpoints touch it.

Extraction is the one model-touched seam, run AFTER an archive lands and off
the request path (see transcripts.archive_transcript): ONE
llm_dispatch.parse_structured call, provider pinned local (an easy task —
local-first; never a silent cloud bill). Any failure -> no facts, never an
error. QUINTACLE_SOFT_RECORD_PROVIDER=off disables it (tests/conftest.py sets
this suite-wide, same pattern as the retrieval summary seam).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import clock

SOFT_RECORD_PROVIDER_ENV = "QUINTACLE_SOFT_RECORD_PROVIDER"
_MAX_FACT_CHARS = 300
_MAX_FACTS_PER_CHAT = 20

_SCHEMA = """
CREATE TABLE IF NOT EXISTS soft_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    text TEXT NOT NULL,
    transcript TEXT NOT NULL,
    UNIQUE (date, text)
);
"""


class SoftRecordStore:
    def __init__(self, data_dir: Path):
        root = Path(data_dir) / "conversations"
        root.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(root / "soft_record.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def add(self, fact_date: str, text: str, transcript: str) -> int | None:
        """Insert one fact; returns its id, or None when the same text is
        already recorded for that date (dedup) or the text is blank."""
        text = " ".join((text or "").split())[:_MAX_FACT_CHARS]
        if not text:
            return None
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO soft_facts (date, text, transcript) VALUES (?, ?, ?)",
            (fact_date, text, transcript),
        )
        self.conn.commit()
        return cur.lastrowid if cur.rowcount else None

    def add_many(self, fact_date: str, texts: list[str], transcript: str) -> int:
        return sum(1 for t in texts if self.add(fact_date, t, transcript) is not None)

    def rows(self, since: str | None = None) -> list[dict]:
        """Newest first (date desc, then insertion order desc)."""
        sql = "SELECT id, date, text, transcript FROM soft_facts"
        params: list = []
        if since:
            sql += " WHERE date >= ?"
            params.append(since)
        sql += " ORDER BY date DESC, id DESC"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def recent(self, days: int = 30) -> list[dict]:
        since = (clock.today() - timedelta(days=days)).isoformat()
        return self.rows(since=since)

    def delete(self, fact_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM soft_facts WHERE id = ?", (fact_id,))
        self.conn.commit()
        return cur.rowcount > 0


_store: SoftRecordStore | None = None


def init_soft_record_store(data_dir: Path) -> None:
    global _store
    _store = SoftRecordStore(data_dir)


def get_soft_record_store() -> SoftRecordStore:
    if _store is None:
        raise RuntimeError("soft record store not initialized — call init_soft_record_store() first")
    return _store


# --- extraction: the one model seam -------------------------------------------


class SoftFacts(BaseModel):
    facts: list[str]


_EXTRACT_SYSTEM = (
    "You extract straight facts from a chat. List ONLY facts the USER explicitly stated "
    "about themselves: their plans, decisions, health, work, routines, or circumstances. "
    "One short factual sentence each, in third-person-free plain wording (e.g. \"Switching to "
    "a 4-day split next week\"). Do NOT infer, guess, summarize the assistant's advice, or "
    "include pleasantries, questions, or opinions about general topics. If the user stated "
    "nothing of this kind, return an empty list."
)


def extract_facts(user_text: str) -> list[str]:
    """ONE local-first structured parse over the user's turns. Returns [] on
    any failure or when disabled — extraction must never raise."""
    mode = (os.environ.get(SOFT_RECORD_PROVIDER_ENV) or "local").strip().lower()
    if mode == "off" or not (user_text or "").strip():
        return []
    try:
        from ... import llm_dispatch

        result = llm_dispatch.parse_structured(
            _EXTRACT_SYSTEM, user_text[:12000], SoftFacts, provider="local", max_tokens=800
        )
        return [f for f in result.parsed.facts if isinstance(f, str) and f.strip()][:_MAX_FACTS_PER_CHAT]
    except Exception:
        return []


def extract_and_store(user_text: str, fact_date: str, transcript: str) -> int:
    """Background job body: extract + dedup-insert. Fully failure-isolated;
    returns how many facts were actually written."""
    try:
        facts = extract_facts(user_text)  # looked up at call time so tests can monkeypatch it
        return get_soft_record_store().add_many(fact_date, facts, transcript)
    except Exception:
        return 0


# --- endpoints -----------------------------------------------------------------

router = APIRouter(prefix="/soft-record", tags=["soft-record"])


@router.get("")
def list_soft_record() -> list[dict]:
    return get_soft_record_store().rows()


@router.delete("/{fact_id}")
def delete_soft_fact(fact_id: int) -> dict:
    if not get_soft_record_store().delete(fact_id):
        raise HTTPException(404, f"no soft-record fact {fact_id}")
    return {"deleted": fact_id}
