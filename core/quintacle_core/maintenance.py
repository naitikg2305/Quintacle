"""Stale-reference cleanup (2026-11-11) — the derived data catching up with
files the owner deleted OUTSIDE the app (file manager, `rm`, a sync).

The markdown files are the source of truth; the SQLite retrieval index
(`nodes_index` + `nodes_fts` + optional `nodes_vec`, retrieval.py) and the
graph's edges (edge files in `graph/edges/` + the derived `edges` table,
graph.py) are derived from them. Nothing notices a file vanishing from
under the app, so before this module those rows lived on and chat/search
kept surfacing notes that no longer exist.

## What counts as stale (per id type, graph.py's id scheme)

Only ids that MAP TO SOMETHING CHECKABLE are ever judged:

- `note:<folder>/<slug>` — stale when neither `kb/<folder>/<slug>.md` (the
  raw path, for hand-named files) nor KBStore.entry_path's slugified path
  exists. Covers people profiles (`note:people/<slug>/profile` →
  `kb/people/<slug>/profile.md`), item-store notes and real Places notes.
- `experience:<folder>/<slug>` — same rule (ExperienceStore keeps
  experiences under kb/ too).
- `journal:<YYYY-MM-DD>` — `journal/<date>.md` gone.
- `todo:<id>` — `schedule/todos/<id>.md` gone.
- Numeric SQLite rows `<kind>:<int>` (expense, food, exercise, activity,
  substance, body_stat, income, meal, ingredient) — the ROW is gone from its
  table (no file involved). `exercise:<name>` is a synthesized routine
  member, never judged.
- `event:<hash>` — stale only when it has members (sources of edges into
  it) and EVERY member is stale. Unknown/virtual members count as alive.
- `place:<...>` — virtual places are legit with no file. One is removed
  only when this run removed an edge touching it AND nothing points INTO it
  anymore (no located_in, no child part_of); its own part_of edges then go
  too, cascading up city → country → continent the same way.
- Everything else (`asset:`, `meal:<name>`, `routine:`, `item:`, ...) is
  never judged.

## What cleanup does (and how it's undoable)

- Edges with a stale endpoint: the edge FILE moves to
  `graph/edges-removed/<timestamp>/` (with a manifest.json) — never
  deleted — and its SQLite row is removed. Undo = move the files back and
  `graph.rebuild_from_folder()`.
- Stale ids' retrieval rows (index + FTS + vectors) are removed. Those are
  a pure cache: restoring the file and re-saving / running
  retrieval_backfill re-derives them.

Safety: when kb/ (or journal/) holds no markdown at all, its ids aren't
judged — an unmounted or mis-pointed data dir must never read as "the owner
deleted everything". The automatic startup run additionally refuses when
more than half of the judged file-backed ids look stale (`max_fraction`).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
from pathlib import Path

import frontmatter

from . import clock
from .markdown_paths import resolve_nested, slugify

logger = logging.getLogger(__name__)

# "<kind>:<int>" → the SQLite table holding that row (retrieval.log_row_title_and_summary).
NUMERIC_TABLES = {
    "expense": "expense_log",
    "food": "food_log",
    "exercise": "exercise_sets",
    "activity": "activity_log",
    "substance": "substance_log",
    "body_stat": "body_stats",
    "income": "income_log",
    "meal": "meals",
    "ingredient": "ingredients",
}
FILE_BACKED_TYPES = {"note", "experience", "journal", "todo"}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Startup auto-run guard: refuse when this fraction of judged file-backed ids
# looks stale — that smells like a broken data dir, not deliberate deletes.
STARTUP_MAX_FRACTION = 0.5


def _has_markdown(root: Path) -> bool:
    if not root.is_dir():
        return False
    return next(root.rglob("*.md"), None) is not None


def _safe_rel(rest: str) -> bool:
    parts = rest.split("/")
    return bool(rest) and all(p not in ("", ".", "..") for p in parts) and not rest.startswith("/")


class _Checker:
    """Answers "is this id stale?" → True (stale) / False (alive) / None
    (not judged: virtual, unknown, or its backing store looks absent)."""

    def __init__(self, data_dir: Path, conn: sqlite3.Connection):
        self.data_dir = Path(data_dir)
        self.conn = conn
        self.kb_root = self.data_dir / "kb"
        self.journal_root = self.data_dir / "journal"
        self.todo_root = self.data_dir / "schedule" / "todos"
        self.kb_ok = _has_markdown(self.kb_root)
        self.journal_ok = _has_markdown(self.journal_root)
        self.todo_ok = _has_markdown(self.todo_root)

    def _kb_file_exists(self, rest: str) -> bool:
        if (self.kb_root / f"{rest}.md").is_file():
            return True
        folder, _, slug = rest.rpartition("/")
        return (resolve_nested(self.kb_root, folder) / f"{slugify(slug)}.md").is_file()

    def stale(self, node_id: str) -> tuple[bool | None, str]:
        kind, _, rest = node_id.partition(":")
        if kind in ("note", "experience"):
            if not self.kb_ok or not _safe_rel(rest):
                return None, ""
            if self._kb_file_exists(rest):
                return False, ""
            return True, f"kb/{rest}.md missing"
        if kind == "journal":
            if not self.journal_ok or not _ISO_DATE.match(rest):
                return None, ""
            if (self.journal_root / f"{rest}.md").is_file():
                return False, ""
            return True, f"journal/{rest}.md missing"
        if kind == "todo":
            if not self.todo_ok or not _safe_rel(rest) or "/" in rest:
                return None, ""
            if (self.todo_root / f"{rest}.md").is_file():
                return False, ""
            return True, f"schedule/todos/{rest}.md missing"
        if kind in NUMERIC_TABLES and rest.isdigit():
            try:
                row = self.conn.execute(
                    f"SELECT 1 FROM {NUMERIC_TABLES[kind]} WHERE id = ?", (int(rest),)
                ).fetchone()
            except sqlite3.OperationalError:
                return None, ""
            if row is not None:
                return False, ""
            return True, f"{NUMERIC_TABLES[kind]} row {rest} missing"
        return None, ""


def _index_ids(conn: sqlite3.Connection) -> tuple[set[str], set[str]]:
    def ids(sql: str) -> set[str]:
        try:
            return {r[0] for r in conn.execute(sql)}
        except sqlite3.OperationalError:
            return set()

    return ids("SELECT id FROM nodes_index"), ids("SELECT id FROM nodes_fts")


def _all_edges(data_dir: Path, conn: sqlite3.Connection) -> dict[str, dict]:
    """Every edge, keyed by id: the SQLite rows plus any edge FILE whose row
    is missing (a file without a row would come back on the next
    rebuild_from_folder, so it has to be judged too)."""
    edges: dict[str, dict] = {}
    try:
        for r in conn.execute("SELECT id, source_id, target_id, kind, source_of_edge FROM edges"):
            edges[r["id"]] = {
                "id": r["id"], "source": r["source_id"], "target": r["target_id"],
                "kind": r["kind"], "source_of_edge": r["source_of_edge"], "in_sqlite": True,
            }
    except sqlite3.OperationalError:
        pass
    edges_dir = Path(data_dir) / "graph" / "edges"
    if edges_dir.is_dir():
        for path in edges_dir.glob("*.md"):
            if path.stem in edges:
                continue
            try:
                meta = frontmatter.loads(path.read_text(encoding="utf-8")).metadata
            except Exception:
                continue
            if meta.get("source") and meta.get("target"):
                edges[path.stem] = {
                    "id": path.stem, "source": meta["source"], "target": meta["target"],
                    "kind": meta.get("kind") or "", "source_of_edge": meta.get("source_of_edge") or "",
                    "in_sqlite": False,
                }
    return edges


def find_stale(data_dir: Path, conn: sqlite3.Connection) -> dict:
    """Read-only scan. Returns the report clean_stale(dry_run=True) returns."""
    data_dir = Path(data_dir)
    checker = _Checker(data_dir, conn)
    index_ids, fts_ids = _index_ids(conn)
    edges = _all_edges(data_dir, conn)

    candidates = set(index_ids) | fts_ids
    for e in edges.values():
        candidates.add(e["source"])
        candidates.add(e["target"])

    stale: dict[str, str] = {}
    judged_file_backed = 0
    for node_id in sorted(candidates):
        verdict, reason = checker.stale(node_id)
        if verdict is not None and node_id.partition(":")[0] in FILE_BACKED_TYPES:
            judged_file_backed += 1
        if verdict:
            stale[node_id] = reason

    # Events: stale once every member is.
    members: dict[str, set[str]] = {}
    for e in edges.values():
        for ev, other in ((e["target"], e["source"]), (e["source"], e["target"])):
            if ev.startswith("event:"):
                members.setdefault(ev, set()).add(other)
    for ev, mems in sorted(members.items()):
        if mems and all(m in stale for m in mems):
            stale[ev] = "every member is gone"

    def removed_edge_ids() -> set[str]:
        return {eid for eid, e in edges.items() if e["source"] in stale or e["target"] in stale}

    # Places: only ones this run touched, only when nothing points into them
    # anymore; cascade up the part_of chain to a fixpoint.
    incoming_by_target: dict[str, list[str]] = {}
    for eid, e in edges.items():
        incoming_by_target.setdefault(e["target"], []).append(eid)
    while True:
        gone = removed_edge_ids()
        touched = {
            endpoint
            for eid in gone
            for endpoint in (edges[eid]["source"], edges[eid]["target"])
            if endpoint.startswith("place:") and endpoint not in stale
        }
        newly = set()
        for place in touched:
            if all(eid in gone for eid in incoming_by_target.get(place, [])):
                newly.add(place)
        if not newly:
            break
        for place in newly:
            stale[place] = "virtual place no longer referenced"

    gone = removed_edge_ids()
    stale_edges = [
        {k: edges[eid][k] for k in ("id", "source", "target", "kind", "source_of_edge")}
        for eid in sorted(gone)
    ]
    index_hits = sorted(i for i in stale if i in index_ids or i in fts_ids)
    by_type: dict[str, int] = {}
    for node_id in stale:
        t = node_id.partition(":")[0]
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "dry_run": True,
        "stale": [{"id": i, "reason": stale[i], "indexed": i in index_ids or i in fts_ids} for i in sorted(stale)],
        "edges": stale_edges,
        "counts": {
            "stale_ids": len(stale),
            "index_rows": len(index_hits),
            "edges": len(stale_edges),
            "by_type": by_type,
            "file_backed_judged": judged_file_backed,
        },
        "moved_to": None,
        "skipped": None,
    }


def clean_stale(
    data_dir: Path,
    conn: sqlite3.Connection,
    dry_run: bool = True,
    max_fraction: float | None = None,
) -> dict:
    """find_stale + (unless dry_run) the removal. `max_fraction`: refuse to
    write when more than that share of judged file-backed ids is stale."""
    data_dir = Path(data_dir)
    report = find_stale(data_dir, conn)
    report["dry_run"] = dry_run
    counts = report["counts"]
    stale_file_backed = sum(1 for s in report["stale"] if s["id"].partition(":")[0] in FILE_BACKED_TYPES)
    if (
        max_fraction is not None
        and counts["file_backed_judged"]
        and stale_file_backed / counts["file_backed_judged"] > max_fraction
    ):
        report["skipped"] = (
            f"{stale_file_backed} of {counts['file_backed_judged']} file-backed ids look stale "
            f"(> {max_fraction:.0%}) — refusing to auto-clean; check the data dir, then run it manually"
        )
        logger.warning("stale cleanup skipped: %s", report["skipped"])
        return report
    if dry_run or (not report["stale"] and not report["edges"]):
        return report

    # Edges: move files (undoable), drop rows.
    if report["edges"]:
        edges_dir = data_dir / "graph" / "edges"
        stamp = clock.now().strftime("%Y%m%d-%H%M%S")
        dest = data_dir / "graph" / "edges-removed" / stamp
        n = 1
        while dest.exists():
            n += 1
            dest = data_dir / "graph" / "edges-removed" / f"{stamp}-{n}"
        dest.mkdir(parents=True)
        for e in report["edges"]:
            src = edges_dir / f"{e['id']}.md"
            try:
                if src.exists():
                    shutil.move(str(src), str(dest / src.name))
            except OSError:
                logger.exception("could not move edge file %s", src)
            conn.execute("DELETE FROM edges WHERE id = ?", (e["id"],))
        conn.commit()
        (dest / "manifest.json").write_text(
            json.dumps(
                {
                    "cleaned_at": clock.now().isoformat(),
                    "why": "endpoint's file/row no longer exists (maintenance.clean_stale)",
                    "undo": "move these .md files back into graph/edges/ and run graph.rebuild_from_folder()",
                    "stale_ids": report["stale"],
                    "edges": report["edges"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        report["moved_to"] = str(dest)

    # Retrieval rows (index + FTS + vectors).
    from .retrieval import RetrievalIndex

    index = RetrievalIndex(conn)
    for s in report["stale"]:
        if s["indexed"]:
            index.remove_node(s["id"])

    logger.info(
        "stale cleanup: %d stale ids (%s), %d index rows removed, %d edges moved to %s: %s",
        counts["stale_ids"], counts["by_type"], counts["index_rows"], counts["edges"],
        report["moved_to"], ", ".join(s["id"] for s in report["stale"]),
    )
    return report


def run_startup_cleanup(data_dir: Path, conn: sqlite3.Connection) -> dict | None:
    """The automatic run at backend / MCP startup — never raises; a failure
    is logged and startup carries on."""
    try:
        report = clean_stale(data_dir, conn, dry_run=False, max_fraction=STARTUP_MAX_FRACTION)
        if report["counts"]["stale_ids"] == 0:
            logger.debug("stale cleanup: nothing stale")
        return report
    except Exception:
        logger.exception("stale cleanup failed at startup (startup continues)")
        return None
