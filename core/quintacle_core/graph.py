"""Quintacle's graph engine — Stage 1-3 of docs/graph-model.md's "graph
engine plan". Deliberately small and bespoke (see that doc's "this is,
honestly, a small bespoke graph system" section): no query language beyond
the handful of functions below, no external graph database (Neo4j/Kùzu are
explicitly Stage 4, not built here).

Two things working together, neither a second source of truth for the other:

- A folder of edge files — `<data_dir>/graph/edges/<timestamp>-<short-id>.md`,
  one per edge, frontmatter only (source, target, kind, source_of_edge,
  created_at). This is the real data; deleting a file undoes an edge the
  same simple way undoing any other Quintacle write already works.
- A SQLite `edges` table (schema in `db.py`) — a derived, fast-query cache
  rebuilt incrementally (one row per edge file) and recoverable from scratch
  via `rebuild_from_folder()`.

Node ids reuse the exact scheme `/graph` (`api.py`) already produces. Any
string of the form "<type>:<rest>" works; this module never invents or
validates types, it just stores/queries them. The full scheme in use:

- "note:<folder>/<slug>" — any KB entry. A person has no dedicated prefix —
  PersonStore shares the KB's root, so a person's profile is itself a
  KBStore entry at "note:people/<slug>/profile", same id a generic note
  would get. Item-shaped stores (wardrobe/grooming/documents/home items)
  also live here, under their fixed folders (see graph_capture.py).
- "journal:<iso-date>" — a journal day.
- "experience:<folder>/<slug>" — a travel experience.
- "todo:<id>" — a schedule todo (ids are already strings, uuid4-hex[:12]).
- Numeric log rows, "<kind>:<int sqlite id>" each in its own table:
  "expense:<id>" (expense_log), "food:<id>" (food_log), "exercise:<id>"
  (exercise_sets), "activity:<id>" (activity_log), "substance:<id>"
  (substance_log), "body_stat:<id>" (body_stats). Note /graph ALSO
  synthesizes name-keyed "exercise:<name>" nodes for routine members —
  a log row's rest is always an integer, a routine member's never is.
- "event:<12-hex hash>" — a same-event grouping minted by
  graph_capture.link_event: every record committed from ONE capture (one
  Drop sort, one journal parse) gets a `part_of` edge to its event node.
  The id is a deterministic hash of the sorted member ids + date, so
  re-linking the same batch never mints a duplicate event.
- Synthesized by /graph per request, never stored as edge endpoints:
  "asset:<folder>/<slug>", "ingredient:<id>", "meal:<id>",
  "routine:<name>", "exercise:<name>", "item:<name>", "outfit:<name>".

## Wiring this in (for MCP or any other write path)

Call `init_graph_store(data_dir, conn)` once at process startup — same
pattern as every other node store in this codebase (`init_kb_store`,
`init_journal_store`, ...). `conn` is a `db.connect(...)` connection; the
`edges` table is already in `db.py`'s shared schema, so no extra migration
step is needed.

After that, the one function every write path should call is:

    link_new_entry(entry_id, entry_type, text, candidates, *, source_of_edge="ai_link") -> list[dict]

See its docstring below for the exact contract. This is the "write rule"
hook from graph-model.md: call it right after persisting anything new (or
re-saving something whose text changed), passing whatever existing entries
are plausible link targets. It is a pure deterministic keyword matcher today
— no AI, no network call — intentionally simple so the plumbing (edge files
+ SQLite + this callable) is solid first; swapping in a smarter matcher
later doesn't need to change this signature.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
from pathlib import Path
from typing import Callable

import frontmatter

from . import clock

EDGE_KIND_BY_CANDIDATE_TYPE = {
    "person": "mentions_person",
    "experience": "at_location",
    "journal_day": "on_day",
}
DEFAULT_EDGE_KIND = "related"


def _split_id(node_id: str) -> tuple[str, str]:
    node_type, _, rest = node_id.partition(":")
    return node_type, rest


def title_mentioned(title: str, text: str) -> bool:
    """THE matcher — a candidate's title/name appears in `text` as a whole
    word, case-insensitive, nothing fuzzier. Exposed as its own function so
    every deterministic mention decision in the app (link_new_entry here,
    the mention backfill and place-emergence scans in graph_capture.py)
    shares exactly one definition of "mentioned"."""
    title = (title or "").strip()
    if not title:
        return False
    return re.search(r"\b" + re.escape(title) + r"\b", text or "", re.IGNORECASE) is not None


class GraphEdgeStore:
    """Owns both halves of Stage 1: the edges/ folder (real data) and the
    SQLite mirror (fast-query cache). Construct one per (data_dir, conn)
    pair — same shape as every other node store (KBStore, PersonStore, ...)."""

    def __init__(self, data_dir: Path, conn: sqlite3.Connection):
        self.data_dir = Path(data_dir)
        self.edges_dir = self.data_dir / "graph" / "edges"
        self.edges_dir.mkdir(parents=True, exist_ok=True)
        self.conn = conn

    def _existing_edge_id(self, source: str, target: str, kind: str) -> str | None:
        row = self.conn.execute(
            "SELECT id FROM edges WHERE source_id = ? AND target_id = ? AND kind = ?",
            (source, target, kind),
        ).fetchone()
        return row["id"] if row is not None else None

    def create_edge(self, source: str, target: str, kind: str, source_of_edge: str) -> dict:
        """Writes one edge file + its SQLite row. Idempotent: an identical
        (source, target, kind) edge already present is returned as-is rather
        than duplicated — a keyword matcher re-run against the same text
        shouldn't pile up repeat edges."""
        existing_id = self._existing_edge_id(source, target, kind)
        if existing_id is not None:
            row = self.conn.execute("SELECT * FROM edges WHERE id = ?", (existing_id,)).fetchone()
            return dict(row)

        now = clock.now()
        edge_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
        created_at = now.isoformat()
        source_type, _ = _split_id(source)
        target_type, _ = _split_id(target)

        post = frontmatter.Post("")
        post["source"] = source
        post["target"] = target
        post["kind"] = kind
        post["source_of_edge"] = source_of_edge
        post["created_at"] = created_at
        (self.edges_dir / f"{edge_id}.md").write_text(frontmatter.dumps(post), encoding="utf-8")

        self.conn.execute(
            """INSERT INTO edges (id, source_type, source_id, target_type, target_id, kind, source_of_edge, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (edge_id, source_type, source, target_type, target, kind, source_of_edge, created_at),
        )
        self.conn.commit()
        return {
            "id": edge_id,
            "source_type": source_type,
            "source_id": source,
            "target_type": target_type,
            "target_id": target,
            "kind": kind,
            "source_of_edge": source_of_edge,
            "created_at": created_at,
        }

    def remove_edge(self, edge_id: str) -> bool:
        """Deletes the edge file + its row. Same mechanism as undoing any
        other Quintacle write — delete the file — so this is what an MCP
        undo of a write-that-created-edges calls per edge id."""
        path = self.edges_dir / f"{edge_id}.md"
        existed = path.exists()
        if existed:
            path.unlink()
        self.conn.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
        self.conn.commit()
        return existed

    def remove_edges_for(self, node_id: str, source_of_edge: str | None = None) -> int:
        """Removes every edge touching `node_id` (either direction),
        optionally restricted to one `source_of_edge` — e.g. re-syncing a
        note's frontmatter `links` only wants to clear the edges THAT note's
        links previously produced, not an `ai_link`/`structural` edge some
        other write created pointing at the same node."""
        if source_of_edge is None:
            rows = self.conn.execute(
                "SELECT id FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id FROM edges WHERE (source_id = ? OR target_id = ?) AND source_of_edge = ?",
                (node_id, node_id, source_of_edge),
            ).fetchall()
        for row in rows:
            self.remove_edge(row["id"])
        return len(rows)

    def all(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute("SELECT * FROM edges ORDER BY created_at")]

    def edges_from(self, node_id: str) -> list[dict]:
        return [dict(row) for row in self.conn.execute("SELECT * FROM edges WHERE source_id = ?", (node_id,))]

    def reverse_edges(self, node_id: str) -> list[dict]:
        """"What links to X" — not computable at all today without a full
        scan; one indexed query once edges are materialized."""
        return [dict(row) for row in self.conn.execute("SELECT * FROM edges WHERE target_id = ?", (node_id,))]

    def neighborhood(self, node_id: str, hops: int) -> dict:
        """Everything within `hops` hops of node_id, either edge direction —
        a `WITH RECURSIVE` walk over the adjacency the edges table already
        is. Deterministic traversal code deciding exactly what to fetch, per
        architecture.md — never an open-ended query engine wandering on its
        own. Returns {"nodes": [ids], "edges": [...]}."""
        if hops < 0:
            raise ValueError("hops must be >= 0")
        rows = self.conn.execute(
            """
            WITH RECURSIVE walk(node_id, depth) AS (
                SELECT ?, 0
                UNION
                SELECT
                    CASE WHEN e.source_id = walk.node_id THEN e.target_id ELSE e.source_id END,
                    walk.depth + 1
                FROM edges e
                JOIN walk ON e.source_id = walk.node_id OR e.target_id = walk.node_id
                WHERE walk.depth < ?
            )
            SELECT DISTINCT node_id FROM walk
            """,
            (node_id, hops),
        ).fetchall()
        node_ids = sorted({row["node_id"] for row in rows})
        if not node_ids:
            return {"nodes": [], "edges": []}
        placeholders = ",".join("?" * len(node_ids))
        edge_rows = self.conn.execute(
            f"""SELECT * FROM edges
                WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})""",
            node_ids + node_ids,
        ).fetchall()
        return {"nodes": node_ids, "edges": [dict(r) for r in edge_rows]}


def rebuild_from_folder(data_dir: Path, conn: sqlite3.Connection) -> int:
    """Wipes and repopulates the `edges` table by scanning graph/edges/*.md —
    the disposable-cache half of the folder-is-source-of-truth contract,
    same relationship `log_store.py`'s `rebuild_sqlite_index` has to the
    markdown activity logs. Safe to run any time; returns the row count."""
    edges_dir = Path(data_dir) / "graph" / "edges"
    conn.execute("DELETE FROM edges")
    n = 0
    if edges_dir.exists():
        for path in sorted(edges_dir.glob("*.md")):
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
            source = post.metadata.get("source")
            target = post.metadata.get("target")
            if not source or not target:
                continue
            source_type, _ = _split_id(source)
            target_type, _ = _split_id(target)
            conn.execute(
                """INSERT OR REPLACE INTO edges
                   (id, source_type, source_id, target_type, target_id, kind, source_of_edge, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    path.stem,
                    source_type,
                    source,
                    target_type,
                    target,
                    post.metadata.get("kind") or DEFAULT_EDGE_KIND,
                    post.metadata.get("source_of_edge") or "unknown",
                    post.metadata.get("created_at") or "",
                ),
            )
            n += 1
    conn.commit()
    return n


_store: GraphEdgeStore | None = None


def init_graph_store(data_dir: Path, conn: sqlite3.Connection) -> None:
    global _store
    _store = GraphEdgeStore(data_dir, conn)


def get_graph_store() -> GraphEdgeStore:
    if _store is None:
        raise RuntimeError("graph store not initialized — call init_graph_store() first")
    return _store


def create_edge(source: str, target: str, kind: str, source_of_edge: str) -> dict:
    return get_graph_store().create_edge(source, target, kind, source_of_edge)


def remove_edge(edge_id: str) -> bool:
    return get_graph_store().remove_edge(edge_id)


def reverse_lookup(node_id: str) -> list[dict]:
    """"What links to X" — see GraphEdgeStore.reverse_edges."""
    return get_graph_store().reverse_edges(node_id)


def neighborhood(node_id: str, hops: int) -> dict:
    return get_graph_store().neighborhood(node_id, hops)


def link_new_entry(
    entry_id: str,
    entry_type: str,
    text: str,
    candidates: list[dict],
    *,
    source_of_edge: str = "ai_link",
) -> list[dict]:
    """THE write-rule hook — call this once, right after persisting anything
    new (an MCP write, a KB note, an experience, a person, ...), to decide
    which existing entries it should link to and create those edges.

    Parameters
    ----------
    entry_id:
        Full graph id of the just-written entry — "note:<folder>/<slug>",
        "journal:<iso-date>", "experience:<folder>/<slug>" (a person's own
        id is "note:people/<slug>/profile" — see the module docstring), or
        any other "<type>:<rest>" id already in use.
    entry_type:
        The entry's own node type (e.g. "note", "experience", "person",
        "journal_day") — informational only; not required to match anything
        in `candidates`.
    text:
        The entry's own text — title + body/notes is plenty — that
        `candidates` get keyword-matched against. No AI call is made: a
        candidate is linked iff its title appears in `text` as a whole word
        (case-insensitive). This is deliberately the simplest thing that
        works — swapping in a smarter (e.g. AI-assisted) matcher later never
        needs to change this signature, since the decision of WHAT counts as
        a candidate and WHAT `text` means stays entirely in the caller.
    candidates:
        Existing entries this one could plausibly link to. Each a dict with:
          - "id": full graph id (required)
          - "title": the name/label to keyword-match against `text` (required)
          - "type": the candidate's node type, e.g. "person"/"experience"/
            "journal_day" — used to pick a default edge `kind` (see
            EDGE_KIND_BY_CANDIDATE_TYPE below); optional, defaults to
            DEFAULT_EDGE_KIND ("related") when missing/unrecognized.
          - "kind": an explicit override for the edge kind, if the caller
            already knows better than the type-based default (optional).
        This function never queries any store itself — callers (API
        handlers, future MCP write tools) gather candidates from whichever
        stores make sense for the entry just written. Keeping it this way
        means it's trivially unit-testable with a hand-built list and has
        zero import-time coupling to any particular node.
    source_of_edge:
        Provenance tag stored on each created edge — "ai_link" (default),
        "structural", "exif_day_match", etc. Use whatever best describes how
        this particular call decided to link.

    Returns the list of edges actually created (each the same shape
    `GraphEdgeStore.create_edge` returns) — callers may ignore the return
    value; it exists for logging/tests. Creates zero edges, silently, when
    nothing in `candidates` matches — "always attempts" does not mean
    "always produces an edge" (see graph-model.md's write rule).
    """
    store = get_graph_store()
    haystack = text or ""
    created: list[dict] = []
    for candidate in candidates:
        target_id = candidate.get("id")
        title = (candidate.get("title") or "").strip()
        if not target_id or not title or target_id == entry_id:
            continue
        if not title_mentioned(title, haystack):
            continue
        kind = candidate.get("kind") or EDGE_KIND_BY_CANDIDATE_TYPE.get(candidate.get("type"), DEFAULT_EDGE_KIND)
        created.append(store.create_edge(entry_id, target_id, kind, source_of_edge))
    return created


def sync_frontmatter_links(
    entry_id: str,
    link_titles: list[str],
    title_lookup: dict[str, str],
    kind_for_target: Callable[[str], str] | None = None,
    source_of_edge: str = "frontmatter_links",
) -> list[dict]:
    """Materializes an entry's own `links` frontmatter (free-text titles, as
    authored) into real edges — the Stage 1 fix for `/graph` recomputing
    this fuzzy-match-every-title walk on every single request. Re-syncs
    rather than only appends: any previously-materialized `frontmatter_links`
    edge from `entry_id` that isn't in the current `link_titles` is removed,
    so editing a note's links list stays correct instead of growing forever.

    `title_lookup` maps every candidate title to its full graph id — build
    it the same way `/graph` already does (note titles + journal dates +
    experience names) and resolve fuzzy drift (e.g. a slightly-off AI title)
    against `list(title_lookup)` with `journal.normalize.canonicalize_name`
    BEFORE calling this — kept out of this function so graph.py has no
    dependency on the journal module.

    `kind_for_target(target_id) -> str` lets the caller pick the edge kind
    per target (default: "on_day" for a "journal:"-prefixed target, else
    "related" — the same two kinds `/graph` already used for this)."""
    store = get_graph_store()
    if kind_for_target is None:
        kind_for_target = lambda tid: "on_day" if tid.startswith("journal:") else DEFAULT_EDGE_KIND  # noqa: E731

    resolved_targets = {
        title_lookup[title] for title in link_titles if title in title_lookup and title_lookup[title] != entry_id
    }

    current = {
        e["target_id"]: e
        for e in store.conn.execute(
            "SELECT * FROM edges WHERE source_id = ? AND source_of_edge = ?", (entry_id, source_of_edge)
        ).fetchall()
    }
    for stale_target, row in current.items():
        if stale_target not in resolved_targets:
            store.remove_edge(row["id"])

    created = []
    for target_id in resolved_targets:
        if target_id in current:
            continue
        created.append(store.create_edge(entry_id, target_id, kind_for_target(target_id), source_of_edge))
    return created
