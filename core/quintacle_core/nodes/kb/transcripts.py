"""The transcript archive — the second-tier store from
docs/next-wave-plan.md §4 ("Transcripts: second-tier archive", 2026-10-19).

When a chat session closes, its raw transcript lands verbatim in
`<data_dir>/conversations/<topic-slug>/<YYYY-MM-DD-HHMM>.md` — a plain file
write, ZERO model calls in the hot path. `conversations/` sits at the data-dir
root, deliberately OUTSIDE `kb/`, the same structural-invisibility trick the
vault uses: every model-facing surface (KB chat context, /kb/search, /kb
listings, MCP tools, drop, graph note rendering) only ever walks `kb/`, so the
archive can never leak into a prompt or a default search result.

Retrieval is explicitly second-tier:
- a dedicated FTS5 table lives in its OWN sqlite file
  (`conversations/transcripts.db`) — separate from `quintacle.db` and from any
  main retrieval index (§3's engine never touches this), populated at archive
  time;
- `GET /transcripts/search?q=...&topic=...` is the ONE lane in — the "dive
  deeper on explicit ask" endpoint. Nothing else reads the archive.

The graph gets a single `transcript_of` edge from
`transcript:<topic-slug>/<stamp>` to the topic's node when the chat's subject
confidently names a real node (title_mentioned — THE matcher — against note
titles and experience names; best = longest matching title). No match, or no
subject: no edge — never guess.

Topic slugs are deterministic (slugify of the subject, else a date-time slug).
A local model proposing a nicer slug via llm_dispatch was considered and
deliberately left out of this wave: the archive's whole contract is "zero
model calls in the hot path", and the deterministic slug is mandatory anyway.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

import frontmatter
from fastapi import APIRouter
from pydantic import BaseModel

from ... import clock
from ...graph import get_graph_store, title_mentioned
from ...markdown_paths import slugify
from .chat_store import _as_text

# One virtual table, nothing else — rebuildable from the markdown files, which
# stay the source of truth (same folder-first contract as graph.py's edges).
_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts USING fts5(
    path, topic, date, body
);
"""


def _render_turns(messages: list[dict]) -> str:
    """The verbatim body: one `### You` / `### Assistant` section per turn,
    same heading convention the scratch ChatStore already writes. Plain-string
    turns pass through untouched; attachment blocks collapse to their text
    plus a note of what was attached (_as_text — the archive never hoards raw
    base64)."""
    sections = []
    for m in messages:
        heading = "### You" if m["role"] == "user" else "### Assistant"
        sections.append(f"{heading}\n\n{_as_text(m['content'])}")
    return "\n\n".join(sections)


def _match_query(q: str) -> str:
    """User text -> a safe FTS5 MATCH expression over the body column: each
    whitespace token becomes a quoted term (quotes doubled), implicitly ANDed
    — no way for `"`, `-`, `NEAR` etc. to break the query syntax."""
    terms = [t.replace('"', '""') for t in q.split()]
    return "body : " + " ".join(f'"{t}"' for t in terms)


class TranscriptStore:
    """Owns the conversations/ folder (real data) and its private FTS5 index
    (derived, disposable) — construct one per data_dir, same shape as every
    other node store."""

    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "conversations"
        self.root.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.root / "transcripts.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_FTS_SCHEMA)
        self.conn.commit()

    def topic_slug(self, subject: str | None) -> str:
        """Deterministic, always: the slugified subject when the session has
        one, else a date-time slug. No model anywhere near this."""
        subject = (subject or "").strip()
        if subject:
            return slugify(subject)
        return clock.now().strftime("%Y-%m-%d-%H%M")

    def archive(self, messages: list[dict], subject: str | None = None) -> dict | None:
        """Writes the verbatim transcript file + its FTS row. Returns the
        archive record ({path, topic, date, stamp, message_count}) or None for
        an empty transcript (nothing worth a file)."""
        if not messages:
            return None
        now = clock.now()
        topic = self.topic_slug(subject)
        topic_dir = self.root / topic
        topic_dir.mkdir(parents=True, exist_ok=True)

        stamp = now.strftime("%Y-%m-%d-%H%M")
        path = topic_dir / f"{stamp}.md"
        if path.exists():
            # Two closes of the same topic inside one minute — fall back to
            # second resolution, then a counter. Never overwrite an archive.
            stamp = now.strftime("%Y-%m-%d-%H%M%S")
            path = topic_dir / f"{stamp}.md"
        n = 2
        while path.exists():
            path = topic_dir / f"{stamp}-{n}.md"
            n += 1
        stamp = path.stem

        body = _render_turns(messages)
        post = frontmatter.Post(body)
        post["date"] = now.isoformat()
        post["topic"] = topic
        post["message_count"] = len(messages)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

        rel_path = f"{topic}/{path.name}"
        self.conn.execute(
            "INSERT INTO transcript_fts (path, topic, date, body) VALUES (?, ?, ?, ?)",
            (rel_path, topic, now.isoformat(), body),
        )
        self.conn.commit()
        return {
            "path": rel_path,
            "topic": topic,
            "date": now.isoformat(),
            "stamp": stamp,
            "message_count": len(messages),
        }

    def search(self, q: str, topic: str | None = None) -> list[dict]:
        """Ranked FTS5 hits, optionally scoped to one topic slug. This is the
        archive's ONLY read lane."""
        q = (q or "").strip()
        if not q:
            return []
        sql = (
            "SELECT path, topic, date, snippet(transcript_fts, 3, '**', '**', '…', 12) AS snippet "
            "FROM transcript_fts WHERE transcript_fts MATCH ?"
        )
        params: list = [_match_query(q)]
        if topic:
            sql += " AND topic = ?"
            params.append(slugify(topic))
        sql += " ORDER BY rank"
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []  # a query FTS5 still can't parse reads as "no hits", not a 500
        return [dict(r) for r in rows]


def link_transcript_topic(transcript_id: str, subject: str | None, candidates: list[dict]) -> dict | None:
    """One `transcript_of` edge from the archived transcript to the topic's
    node — only when the chat's subject confidently names a real node.
    title_mentioned (THE matcher) decides "named"; among several matches the
    longest title wins (most specific), ties broken alphabetically for
    determinism. No subject or no match: None, never a guessed edge."""
    subject = (subject or "").strip()
    if not subject:
        return None
    matches = [
        c for c in candidates if c.get("id") and (c.get("title") or "").strip() and title_mentioned(c["title"], subject)
    ]
    if not matches:
        return None
    best = sorted(matches, key=lambda c: (-len(c["title"]), c["title"]))[0]
    return get_graph_store().create_edge(transcript_id, best["id"], "transcript_of", "transcript_archive")


_store: TranscriptStore | None = None


def init_transcript_store(data_dir: Path) -> None:
    global _store
    _store = TranscriptStore(data_dir)


def get_transcript_store() -> TranscriptStore:
    if _store is None:
        raise RuntimeError("transcript store not initialized — call init_transcript_store() first")
    return _store


# --- the two endpoints — archive-on-close in, explicit deep search out ------

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


class TranscriptTurn(BaseModel):
    role: Literal["user", "assistant"]
    # Same shape as kb/api.py's ChatMessage: a plain string, or Anthropic-style
    # content blocks when a photo/PDF was attached to a turn.
    content: str | list[dict]


class ArchiveRequest(BaseModel):
    messages: list[TranscriptTurn]
    subject: str | None = None  # the chat's subject, if the session had one
    keep: bool = True  # the per-chat "don't keep" toggle — False archives nothing


def _edge_candidates() -> list[dict]:
    """Nodes a transcript's topic could confidently name: every KB note title
    (people's profiles included — they ARE notes) plus experience names.
    Gathered defensively — an uninitialized store in a partial app just means
    fewer candidates, never a failed archive."""
    candidates: list[dict] = []
    try:
        from .api import get_store

        for n in get_store().notes_index():
            candidates.append({"id": f"note:{n['folder']}/{n['slug']}", "title": n["title"]})
    except Exception:
        pass
    try:
        from ..travel.api import get_store as get_travel_store

        for e in get_travel_store().all():
            candidates.append({"id": f"experience:{e['folder']}/{e['slug']}", "title": e["name"]})
    except Exception:
        pass
    return candidates


@router.post("/archive")
def archive_transcript(body: ArchiveRequest) -> dict:
    """The archive-on-close hook the chat page calls — a file write + an FTS
    row, zero model calls. keep=false (the "don't keep" toggle) archives
    nothing at all."""
    if not body.keep:
        return {"archived": False, "reason": "keep is off for this chat"}
    result = get_transcript_store().archive([m.model_dump() for m in body.messages], body.subject)
    if result is None:
        return {"archived": False, "reason": "empty transcript"}
    # The graph edge is additive — a hiccup here (graph store not up in some
    # partial test app) must never fail an archive that already landed.
    try:
        edge = link_transcript_topic(f"transcript:{result['topic']}/{result['stamp']}", body.subject, _edge_candidates())
    except Exception:
        edge = None
    return {"archived": True, **result, "edge_id": edge["id"] if edge else None}


@router.get("/search")
def search_transcripts(q: str, topic: str | None = None) -> list[dict]:
    """The explicit "dive deeper / refer to transcripts" lane — the only
    surface anywhere that reads the archive. Not part of any default search."""
    return get_transcript_store().search(q, topic)
