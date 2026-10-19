"""Universal triple-hybrid retrieval over every node type in the store —
docs/next-wave-plan.md §3, decided 2026-10-19.

Three lanes, all merged IN CODE (no model anywhere in the retrieve path):

- **FTS5** — `nodes_fts`, a virtual table over title + summary + body text,
  bm25-ranked. Built into SQLite, always available.
- **Vectors (optional)** — `nodes_vec` via sqlite-vec + LOCAL Ollama
  embeddings (`QUINTACLE_EMBED_MODEL`, default an EmbeddingGemma-class
  model). sqlite-vec lives in its own `core/requirements-retrieval.txt`
  (lazy import — `core/requirements.txt` stays phone/Termux-safe), and the
  embedding call reuses the same Ollama host resolution as the `local:`
  chat provider. ANY failure — package missing, extension won't load,
  daemon down, model not pulled — silently turns this lane off;
  `retrieve()` then runs FTS5 + graph only.
- **Graph expansion** — for the top fused hits, 1-hop neighbors via
  `graph.neighborhood()` attached as `{id, title, edge_type}` labels.

Lanes are merged by reciprocal-rank fusion (`rrf_merge`, plain arithmetic).

The index itself is two tables in the existing `quintacle.db`:

- `nodes_index(id, type, title, summary, updated_at)` — id is EXACTLY the
  graph id scheme from `graph.py`'s module docstring ("note:<folder>/<slug>",
  "journal:<iso-date>", "expense:<int>", "experience:<folder>/<slug>",
  "todo:<id>", "event:<12hex>", "meal:<int>", "routine:<name>", ...). A
  person deliberately has NO person: prefix — their id is their profile
  note's id, "note:people/<slug>/profile", with `type` = "person", same as
  `/graph` labels that node. No parallel id scheme is ever invented here.
- `nodes_fts` — the FTS5 mirror (title weighted over summary over body).

Summaries follow "deterministic core, models at the edges": every
structured row's one-liner is COMPUTED IN CODE from its fields (e.g.
"Chipotle — $14.50 — food — 2026-10-12"); only prose nodes (KB notes,
journal days) may get a LOCAL-model one-liner (`prose_summary`), and even
those fall back deterministically (first non-empty content line, ~120
chars) whenever the local model is unreachable — and ALWAYS in tests
(`QUINTACLE_SUMMARY_PROVIDER=off`, set suite-wide in tests/conftest.py).

Write-path hooks (`safe_index_*`) are failure-isolated: an indexing error
is logged and swallowed, never failing the user's write — same contract as
`graph_capture.safe_entry_graph_links`. When the retrieval singleton isn't
initialized (bare store tests, processes that never wired retrieval) the
hooks are silent no-ops.

Exclusions (structural, hard rules):
- the Vault stays invisible — it lives OUTSIDE kb/ so no walker here can
  reach it, and `is_excluded()` additionally refuses any vault-prefixed id.
- any `conversations/` folder is excluded by prefix — the transcript
  archive (next wave) must never enter the default index.

Backfill: `python -m quintacle_core.retrieval_backfill` (idempotent, walks
the whole store, prints per-type counts).
"""
from __future__ import annotations

import functools
import json
import logging
import os
import re
import sqlite3
import struct
import urllib.request
from datetime import date

from pydantic import BaseModel

from . import clock

logger = logging.getLogger(__name__)

EMBED_MODEL_ENV = "QUINTACLE_EMBED_MODEL"
# EmbeddingGemma-class local embedding model (docs/on-device-s25u.md) — used
# only if Ollama actually serves it; never required.
DEFAULT_EMBED_MODEL = "embeddinggemma"
SUMMARY_PROVIDER_ENV = "QUINTACLE_SUMMARY_PROVIDER"  # "local" (default) | "off"

PROSE_SUMMARY_CHARS = 120
_RRF_K = 60  # the standard reciprocal-rank-fusion constant
_NEIGHBOR_LIMIT = 10

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes_index (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(id UNINDEXED, title, summary, body);
"""


def embed_model() -> str:
    return os.environ.get(EMBED_MODEL_ENV, "").strip() or DEFAULT_EMBED_MODEL


def is_excluded(node_id: str) -> bool:
    """Hard exclusions, checked on every index write: vault-prefixed ids
    (defense in depth — the Vault lives outside kb/ so nothing here should
    ever even produce one) and anything under a conversations/ folder (the
    transcript archive is second-tier by decision, see next-wave-plan §4).
    Note "Document Vault" slugifies to "organisation/document-vault", which
    does NOT start with "vault/" — that KB folder stays indexable."""
    node_type, _, rest = node_id.partition(":")
    rest_l = rest.lower()
    if node_type == "vault" or rest_l == "vault" or rest_l.startswith("vault/"):
        return True
    if rest_l == "conversations" or rest_l.startswith("conversations/"):
        return True
    return False


def _fts_query(query: str) -> str:
    """User text → a safe FTS5 MATCH expression: bare word tokens, each
    double-quoted (so FTS5 operators/punctuation in the query can't break
    or hijack the parse), OR-joined — recall over precision, bm25 ranks."""
    tokens = re.findall(r"[^\W_]+", query or "", re.UNICODE)
    return " OR ".join(f'"{t}"' for t in tokens)


def rrf_merge(ranked_lists: list[list[str]], rrf_k: int = _RRF_K) -> list[tuple[str, float]]:
    """Reciprocal-rank fusion: score(id) = Σ over lanes 1/(k + rank). Plain
    arithmetic in code — the lanes' raw scores (bm25, cosine distance) are
    not comparable, their ranks are. Ties break on id for determinism."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, node_id in enumerate(ranked):
            scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (rrf_k + rank + 1)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


class _VectorLane:
    """The optional lane: sqlite-vec KNN over local Ollama embeddings.
    Fully lazy — nothing is imported, loaded, or contacted until the first
    upsert/search — and self-disabling: the first hard failure (package
    missing, extension won't load, embeddings endpoint unreachable) flips
    the lane off for the rest of the process so a down daemon can't slow
    every subsequent write with a fresh connection attempt."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._available: bool | None = None  # None = not probed yet

    def _ensure_extension(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import sqlite_vec  # requirements-retrieval.txt, never in requirements.txt
        except ImportError:
            logger.debug("sqlite-vec not installed — vector lane off (FTS5+graph only)")
            self._available = False
            return False
        try:
            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            self._available = True
        except Exception:
            logger.info("sqlite-vec present but failed to load — vector lane off", exc_info=True)
            self._available = False
        return self._available

    def _embed(self, texts: list[str]) -> list[list[float]]:
        # Same daemon + host resolution as the local: chat provider and
        # llm_dispatch's local parse (QUINTACLE_OLLAMA_HOST / OLLAMA_HOST).
        from .nodes.kb.chat import ollama_host

        payload = {"model": embed_model(), "input": texts}
        req = urllib.request.Request(
            f"{ollama_host()}/api/embed",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
        return [[float(x) for x in e] for e in (data.get("embeddings") or [])]

    def _ensure_table(self, dim: int) -> None:
        # Created lazily on the first successful embedding — vec0 needs a
        # fixed dimension, which is whatever the configured model produces.
        self.conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS nodes_vec USING vec0(id TEXT PRIMARY KEY, embedding float[{dim}] distance_metric=cosine)"
        )

    def upsert(self, node_id: str, text: str) -> None:
        if not text or not self._ensure_extension():
            return
        try:
            vectors = self._embed([text])
            if not vectors:
                return
            self._ensure_table(len(vectors[0]))
            self.conn.execute("DELETE FROM nodes_vec WHERE id = ?", (node_id,))
            self.conn.execute("INSERT INTO nodes_vec (id, embedding) VALUES (?, ?)", (node_id, _pack(vectors[0])))
            self.conn.commit()
        except Exception as e:
            logger.info("embeddings unavailable (%s) — vector lane off for this process", e)
            self._available = False

    def remove(self, node_id: str) -> None:
        if not self._ensure_extension():
            return
        try:
            self.conn.execute("DELETE FROM nodes_vec WHERE id = ?", (node_id,))
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # nodes_vec never created (no embedding ever succeeded)

    def search(self, query: str, limit: int) -> list[str]:
        if not query or not self._ensure_extension():
            return []
        try:
            vectors = self._embed([query])
            if not vectors:
                return []
            rows = self.conn.execute(
                "SELECT id FROM nodes_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (_pack(vectors[0]), limit),
            ).fetchall()
            return [r["id"] for r in rows]
        except sqlite3.OperationalError:
            return []  # nodes_vec doesn't exist yet — nothing embedded so far
        except Exception as e:
            logger.info("vector search unavailable (%s) — FTS5+graph only for this query", e)
            self._available = False
            return []


class RetrievalIndex:
    """Owns nodes_index + nodes_fts (+ the optional vector lane) on the one
    shared quintacle.db connection — same construct-per-(data, conn) shape
    as GraphEdgeStore."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        conn.executescript(_SCHEMA)
        conn.commit()
        self.vectors = _VectorLane(conn)

    # --- index CRUD ---

    def index_node(
        self,
        node_id: str,
        node_type: str,
        title: str,
        *,
        summary: str = "",
        body: str = "",
        updated_at: str | None = None,
    ) -> bool:
        """Upserts one node. Returns False (indexing nothing) for excluded
        ids — the vault/conversations guard is enforced HERE, at the single
        chokepoint every indexer goes through, not in each caller."""
        if is_excluded(node_id):
            return False
        title = (title or "").strip() or node_id.partition(":")[2]
        summary = (summary or "").strip()
        updated_at = updated_at or clock.now().isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO nodes_index (id, type, title, summary, updated_at) VALUES (?, ?, ?, ?, ?)",
            (node_id, node_type, title, summary, updated_at),
        )
        self.conn.execute("DELETE FROM nodes_fts WHERE id = ?", (node_id,))
        self.conn.execute(
            "INSERT INTO nodes_fts (id, title, summary, body) VALUES (?, ?, ?, ?)",
            (node_id, title, summary, body or ""),
        )
        self.conn.commit()
        # Embedding text = title + summary: the dense, entity-bearing line —
        # bodies are already covered exactly by FTS5.
        self.vectors.upsert(node_id, f"{title}\n{summary}".strip())
        return True

    def remove_node(self, node_id: str) -> None:
        self.conn.execute("DELETE FROM nodes_index WHERE id = ?", (node_id,))
        self.conn.execute("DELETE FROM nodes_fts WHERE id = ?", (node_id,))
        self.conn.commit()
        self.vectors.remove(node_id)

    def get_node(self, node_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM nodes_index WHERE id = ?", (node_id,)).fetchone()
        return dict(row) if row is not None else None

    def counts_by_type(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT type, COUNT(*) AS n FROM nodes_index GROUP BY type ORDER BY type")
        return {r["type"]: r["n"] for r in rows}

    # --- the three lanes + fusion ---

    def _fts_ids(self, query: str, limit: int) -> list[str]:
        match = _fts_query(query)
        if not match:
            return []
        try:
            rows = self.conn.execute(
                # Column weights (id is UNINDEXED → 0): title 5, summary 2, body 1.
                "SELECT id FROM nodes_fts WHERE nodes_fts MATCH ? ORDER BY bm25(nodes_fts, 0.0, 5.0, 2.0, 1.0) LIMIT ?",
                (match, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []  # a query FTS5 still rejects degrades to no FTS lane, not a 500
        return [r["id"] for r in rows]

    def _vector_ids(self, query: str, limit: int) -> list[str]:
        """Separated for exactly one reason: tests stub this to exercise the
        RRF merge without sqlite-vec or Ollama installed."""
        return self.vectors.search(query, limit)

    def _neighbors(self, node_id: str) -> list[dict]:
        """1-hop graph expansion via graph.neighborhood — labels only
        ({id, title, edge_type}), titles resolved from this index when the
        neighbor is indexed, else the id's own rest. No graph store wired
        (bare tests) degrades to no neighbors, never an error."""
        try:
            from .graph import get_graph_store

            hood = get_graph_store().neighborhood(node_id, 1)
        except Exception:
            return []
        neighbors: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for edge in hood["edges"]:
            if edge["source_id"] == node_id:
                other = edge["target_id"]
            elif edge["target_id"] == node_id:
                other = edge["source_id"]
            else:
                continue  # an edge among the neighbors themselves
            key = (other, edge["kind"])
            if other == node_id or key in seen:
                continue
            seen.add(key)
            row = self.conn.execute("SELECT title FROM nodes_index WHERE id = ?", (other,)).fetchone()
            title = row["title"] if row is not None else other.partition(":")[2]
            neighbors.append({"id": other, "title": title, "edge_type": edge["kind"]})
            if len(neighbors) >= _NEIGHBOR_LIMIT:
                break
        return neighbors

    def retrieve(self, query: str, k: int = 10, types: list[str] | None = None) -> list[dict]:
        """FTS5 bm25 + vector cosine (when the lane is up), RRF-fused, then
        graph-expanded. Pure code end to end — no model call anywhere."""
        k = max(1, int(k))
        pool = max(k * 5, 25)
        lanes = [lane for lane in (self._fts_ids(query, pool), self._vector_ids(query, pool)) if lane]
        type_filter = {t.strip() for t in types if t.strip()} if types else None
        results: list[dict] = []
        for node_id, score in rrf_merge(lanes):
            row = self.conn.execute("SELECT * FROM nodes_index WHERE id = ?", (node_id,)).fetchone()
            if row is None:
                continue  # stale lane row — nodes_index is the authority
            if type_filter and row["type"] not in type_filter:
                continue
            results.append(
                {
                    "id": row["id"],
                    "type": row["type"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "score": round(score, 6),
                    "neighbors": self._neighbors(node_id),
                }
            )
            if len(results) >= k:
                break
        return results


# --- singleton wiring (same pattern as graph.init_graph_store) ---

_index: RetrievalIndex | None = None


def init_retrieval_index(conn: sqlite3.Connection) -> RetrievalIndex:
    global _index
    _index = RetrievalIndex(conn)
    return _index


def get_retrieval_index() -> RetrievalIndex:
    if _index is None:
        raise RuntimeError("retrieval index not initialized — call init_retrieval_index() first")
    return _index


def retrieve(query: str, k: int = 10, types: list[str] | None = None) -> list[dict]:
    return get_retrieval_index().retrieve(query, k=k, types=types)


# --- summaries: deterministic core, models at the edges ---


def _join(*parts) -> str:
    return " — ".join(str(p).strip() for p in parts if p is not None and str(p).strip())


def deterministic_prose_summary(body: str, title: str = "") -> str:
    """THE fallback for prose nodes: first non-empty content line (headings,
    asset links and marker comments skipped), truncated to ~120 chars; the
    title when the body has nothing usable. Used whenever no local model is
    reachable, and ALWAYS in tests."""
    for line in (body or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("[asset](") or stripped.startswith("<!--"):
            continue
        return stripped[:PROSE_SUMMARY_CHARS]
    return (title or "").strip()[:PROSE_SUMMARY_CHARS]


class ProseSummary(BaseModel):
    summary: str


def prose_summary(title: str, body: str) -> str:
    """One-liner for a prose node (KB note, journal day) — the ONLY
    model-touched seam in this module, and only at ingest, never in the
    retrieve path. provider is pinned to "local": a search-index one-liner
    is an easy task (local-first), and it must never bill a silent cloud
    call behind a routine save. ANY failure — daemon down, model missing,
    schema-invalid output — falls back to the deterministic line, so a
    write is never blocked on a model. QUINTACLE_SUMMARY_PROVIDER=off
    forces the deterministic path (tests/conftest.py sets it suite-wide)."""
    fallback = deterministic_prose_summary(body, title)
    mode = (os.environ.get(SUMMARY_PROVIDER_ENV) or "local").strip().lower()
    if mode == "off" or not (body or "").strip():
        return fallback
    try:
        from . import llm_dispatch

        result = llm_dispatch.parse_structured(
            "Write ONE plain, specific line (under 20 words) summarizing this note for a search index. "
            "No preamble, no markdown, no quotes — just the line.",
            f"Title: {title}\n\n{(body or '')[:4000]}",
            ProseSummary,
            provider="local",
            max_tokens=200,
        )
        line = " ".join(result.parsed.summary.split()).strip()
        return line[:PROSE_SUMMARY_CHARS] if line else fallback
    except Exception:
        return fallback


def log_row_title_and_summary(conn: sqlite3.Connection, member_id: str) -> tuple[str, str, str] | None:
    """(title, summary, body) for a "<kind>:<int>" SQLite-backed node —
    expenses, food, exercise, activities, substances, body stats, plus the
    meal/ingredient preset libraries. COMPUTED IN CODE from the real row
    (any arithmetic — kcal × servings — done in SQL), never a model call.
    None when the kind is unknown, the rest isn't an int, or the row is
    gone. The fuller sibling of graph_capture.log_row_label."""
    kind, _, rest = member_id.partition(":")
    if not rest.isdigit():
        return None
    row_id = int(rest)
    if kind == "expense":
        row = conn.execute("SELECT * FROM expense_log WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None
        title = row["merchant"] or row["notes"] or "expense"
        return title, _join(row["merchant"] or "expense", f"${row['amount']:.2f}", row["category"], row["date"]), row["notes"]
    if kind == "food":
        row = conn.execute(
            """SELECT f.*, m.name AS meal_name,
                      COALESCE(m.kcal, f.freeform_kcal, 0) * f.servings AS total_kcal
               FROM food_log f LEFT JOIN meals m ON f.meal_id = m.id WHERE f.id = ?""",
            (row_id,),
        ).fetchone()
        if row is None:
            return None
        title = row["notes"] or row["meal_name"] or row["meal_type"]
        kcal = f"{row['total_kcal']:g} kcal" if row["total_kcal"] else ""
        return title, _join(title, row["meal_type"] if row["meal_type"] != title else "", kcal, row["date"]), row["notes"]
    if kind == "exercise":
        row = conn.execute("SELECT * FROM exercise_sets WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None
        return row["exercise_name"], _join(row["exercise_name"], row["performance_text"], row["date"]), row["notes"]
    if kind == "activity":
        row = conn.execute("SELECT * FROM activity_log WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None
        hours = f"{row['hours']:g}h" if row["hours"] else ""
        return row["description"][:80], _join(row["description"], row["category"], hours, row["date"]), row["description"]
    if kind == "substance":
        row = conn.execute("SELECT * FROM substance_log WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None
        return row["substance"], _join(f"{row['substance']} {row['amount']:g}", row["notes"], row["date"]), row["notes"]
    if kind == "body_stat":
        row = conn.execute("SELECT * FROM body_stats WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None
        return row["metric"], _join(f"{row['metric']} {row['value']:g} {row['unit']}".strip(), row["date"]), ""
    if kind == "meal":
        row = conn.execute("SELECT * FROM meals WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None
        return row["name"], _join(row["name"], f"{row['kcal']:g} kcal", f"{row['protein_g']:g}g protein", "meal preset"), row["notes"]
    if kind == "ingredient":
        row = conn.execute("SELECT * FROM ingredients WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None
        per = f"{row['kcal']:g} kcal / {row['basis_amount_g']:g} g"
        return row["name"], _join(row["name"], per, "ingredient preset"), row["notes"]
    if kind == "income":
        row = conn.execute("SELECT * FROM income_log WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None
        title = row["source"] or "income"
        return title, _join(title, f"+${row['amount']:.2f}", row["kind"], row["date"]), row["notes"]
    return None


# --- failure-isolated write-path hooks ---
#
# Every hook: no-op when retrieval was never initialized in this process,
# and ANY exception is logged and swallowed — an indexing error must never
# fail the user's write (same contract as graph_capture's safe_* helpers).


def _never_fails(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if _index is None:
            return None
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("retrieval indexing failed in %s (the write itself succeeded)", fn.__name__)
            return None

    return wrapper


@_never_fails
def safe_index_node(node_id: str, node_type: str, title: str, summary: str = "", body: str = "") -> None:
    get_retrieval_index().index_node(node_id, node_type, title, summary=summary, body=body)


@_never_fails
def safe_remove_node(node_id: str) -> None:
    get_retrieval_index().remove_node(node_id)


@_never_fails
def safe_index_note(folder_slug: str, entry_slug: str, title: str, body: str) -> None:
    """A KB entry (prose). Emergent Places/ notes get type "place" — same
    classification /graph applies to that folder."""
    node_type = "place" if folder_slug == "places" or folder_slug.startswith("places/") else "note"
    get_retrieval_index().index_node(
        f"note:{folder_slug}/{entry_slug}", node_type, title, summary=prose_summary(title, body), body=body or ""
    )


@_never_fails
def safe_index_journal(entry_date: date, content: str) -> None:
    """A journal day (prose) — pass the FULL day content (store.load), so a
    second append re-indexes the whole day, not just the delta."""
    iso = entry_date.isoformat()
    get_retrieval_index().index_node(
        f"journal:{iso}", "journal_day", iso, summary=prose_summary(iso, content), body=content or ""
    )


@_never_fails
def safe_index_log_row(member_id: str) -> None:
    """Any "<kind>:<int>" SQLite-backed node (see log_row_title_and_summary)
    — reads the row back from the index's own connection (the same
    quintacle.db the logs repo writes), so hooks just pass the id."""
    index = get_retrieval_index()
    parts = log_row_title_and_summary(index.conn, member_id)
    if parts is None:
        return
    title, summary, body = parts
    index.index_node(member_id, member_id.partition(":")[0], title, summary=summary, body=body or "")


@_never_fails
def safe_index_todo(todo) -> None:
    """A schedule Todo (the pydantic model) — deterministic one-liner from
    its own fields."""
    due = f"due {todo.due_date.isoformat()}" if todo.due_date else ""
    status = "done" if todo.done else ""
    summary = _join(todo.title, todo.category, due, status)
    get_retrieval_index().index_node(f"todo:{todo.id}", "todo", todo.title, summary=summary, body=todo.notes or "")


@_never_fails
def safe_index_person(name: str, folder: str, category: str = "", how_met: str = "", notes: str = "") -> None:
    """A person — id is their profile note's id (graph.py: a person has no
    dedicated prefix), type "person", titled with their real name."""
    summary = _join(name, category, how_met)
    get_retrieval_index().index_node(f"note:{folder}/profile", "person", name, summary=summary, body=notes or "")


@_never_fails
def safe_index_experience(
    name: str, folder: str, slug: str, city: str = "", kind: str = "", rating: str = "", notes: str = ""
) -> None:
    summary = _join(name, city, kind, rating)
    get_retrieval_index().index_node(f"experience:{folder}/{slug}", "experience", name, summary=summary, body=notes or "")


@_never_fails
def safe_index_routine(name: str, exercises: list[str]) -> None:
    summary = _join(name, ", ".join(exercises), "workout routine")
    get_retrieval_index().index_node(f"routine:{name}", "routine", name, summary=summary, body="")


@_never_fails
def safe_index_event(event_id: str, member_count: int, for_date: date | None = None) -> None:
    label = _join("event", for_date.isoformat() if for_date else "", f"{member_count} records")
    get_retrieval_index().index_node(event_id, "event", label, summary=label, body="")
