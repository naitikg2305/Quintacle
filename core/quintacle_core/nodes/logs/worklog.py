from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

import frontmatter

from ...graph import title_mentioned
from ...markdown_paths import resolve_nested, slugify
from ...retrieval import safe_index_log_row, safe_index_note, safe_remove_node
from .log_store import LogFileStore, home_for

# The work-log lane (docs/next-wave-plan.md §10): the owner's daily
# ~/work-logs/YYYY-MM-DD.md files land in the KB verbatim, in ONE home, with
# deterministic productivity rows derived from each session's own header —
# hours computed in code from the start–end times, the one-liner lifted from
# the Summary. Zero model calls anywhere in this module: the files are
# already written prose; everything extractable from them is extractable by
# rules.

WORKLOG_FOLDER = "Daily Log/Work Logs"
WORKLOG_KIND = "work-log"
# Tags every auto-emitted activity row (markdown frontmatter `source` field
# AND the activity_log.source column) so re-imports can delete exactly their
# own prior rows — deterministic dedupe, never fuzzy matching, and manually
# logged rows (source='') are untouchable by construction.
WORKLOG_SOURCE = "worklog-auto"
# Entity hub notes live under these KB roots (§10 file map: Career = one
# folder per employer, Projects = one per endeavor) — a work log mentioning
# one of their titles gets a graph edge to it ("what did I do for Minfy this
# year" = walk edges).
ENTITY_ROOTS = ("career", "projects")


def note_title_for(file_date: date) -> str:
    return f"Work log - {file_date.isoformat()}"


# --- deterministic session parser --------------------------------------------

# A session heading: "## Session 2", "## Session 12 (main-session close-out)".
_SESSION_HEADING_RE = re.compile(r"^##\s+Session\b[^\n]*$", re.MULTILINE)
# The header line inside a block:
# **Session:** ~14:30–18:45 (local) · **Where:** ~/code/quintacle (…) · **Who:** …
_HEADER_RE = re.compile(r"^\*\*Session:\*\*\s*(?P<rest>.+)$", re.MULTILINE)
# A start–end time pair. Separators seen in the real files: en-dash, em-dash,
# plain hyphen, and "→"; either side may carry a "~" (approximate) prefix.
_TIME_RANGE_RE = re.compile(
    r"~?\s*(?P<h1>\d{1,2}):(?P<m1>\d{2})\s*(?:–|—|−|->|→|-)\s*~?\s*(?P<h2>\d{1,2}):(?P<m2>\d{2})"
)
# "the project": the first ~/code/<name> (or any .../code/<name>) in Where.
_CODE_REPO_RE = re.compile(r"(?:^|[\s`(,·])[~/][^\s`(),·]*?/code/(?P<name>[A-Za-z0-9._-]+)")
_PAREN_RE = re.compile(r"\([^)]*\)")
# Summary marker: "**Summary**", "**Summary.**", "**Summary:**", "## Summary";
# "**Summary.** Inline text…" carries the text on the same line.
_SUMMARY_RE = re.compile(r"^(?:\*\*Summary[.:]?\*\*|##\s+Summary)[.:]?\s*(?P<inline>.*)$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


@dataclass
class WorkSession:
    """One parsed `## Session` block (or the whole file when a log has no
    session headings). hours is None whenever either end of the time range is
    missing or unparseable ("evening", "~afternoon", "continuation") — never
    guessed."""

    date: date
    label: str  # the "## Session N…" heading text, "" for an unnumbered file
    start: str | None  # "HH:MM" as written (without any ~)
    end: str | None
    hours: float | None  # (end - start) minutes / 60, rounded to 2 decimals
    where: str  # the raw **Where:** text ("" when absent)
    repos: list[str]  # Where split into location strings (parentheticals dropped)
    project: str | None  # <name> from the first …/code/<name> in Where
    description: str  # Summary's first sentence (fallback: first line after the header)


def _clean_inline(text: str) -> str:
    """Markdown bold/backticks don't belong in an activity-row one-liner."""
    return _BOLD_RE.sub(r"\1", text).replace("`", "").strip()


def _first_sentence(paragraph: str) -> str:
    return re.split(r"(?<=[.!?])\s+", paragraph.strip(), maxsplit=1)[0].strip()


def _parse_times(time_text: str) -> tuple[str | None, str | None, float | None]:
    """Hours from a header's time segment, in code: "14:30–18:45" → 4.25.
    An end at-or-before the start means the session ran past midnight (the
    real "23:15–00:10 (local, ran past midnight)" case) → +24h. Anything
    without BOTH a parseable start and end ("evening Oct 7 → ~01:50 Oct 8",
    "continuation", "~afternoon") yields hours=None — never guessed."""
    m = _TIME_RANGE_RE.search(_PAREN_RE.sub("", time_text))
    if m is None:
        return None, None, None
    h1, m1, h2, m2 = (int(m.group(g)) for g in ("h1", "m1", "h2", "m2"))
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        return None, None, None
    start_min, end_min = h1 * 60 + m1, h2 * 60 + m2
    if end_min <= start_min:
        end_min += 24 * 60
    return f"{h1:02d}:{m1:02d}", f"{h2:02d}:{m2:02d}", round((end_min - start_min) / 60, 2)


def _parse_where(rest: str) -> tuple[str, list[str], str | None]:
    """The **Where:** segment of a header line → (raw text, locations,
    project). Locations: parentheticals stripped (they hold worktree/branch
    asides with commas of their own), then split on '·' and ','. Project:
    the <name> after the FIRST '/code/' anywhere in the raw Where text; an
    all-lowercase name gets its first letter capitalized ("quintacle" →
    "Quintacle"), anything cased ("AWS_Hackathon_Minfy") stays verbatim."""
    where = ""
    for segment in rest.split("·"):
        segment = segment.strip()
        if segment.startswith("**Where:**"):
            where = segment.removeprefix("**Where:**").strip()
            break
    repos = [
        part.strip().strip("`")
        for chunk in _PAREN_RE.sub("", where).split("·")
        for part in chunk.split(",")
        if part.strip().strip("`")
    ]
    m = _CODE_REPO_RE.search(where)
    project = None
    if m is not None:
        name = m.group("name")
        project = name[:1].upper() + name[1:] if name.islower() else name
    return _clean_inline(where), repos, project


def _block_description(block: str, header_match: re.Match | None) -> str:
    """The one-liner: the Summary's first sentence; when a block has no
    Summary section (or an empty one), the first non-empty line after the
    **Session:** header line; last resort, the first non-empty non-heading
    line of the block."""
    m = _SUMMARY_RE.search(block)
    if m is not None:
        inline = m.group("inline").strip()
        if inline:
            paragraph = inline
        else:
            lines = []
            for line in block[m.end():].lstrip("\n").split("\n"):
                if not line.strip():
                    break
                lines.append(line.strip())
            paragraph = " ".join(lines)
        if paragraph.strip():
            return _clean_inline(_first_sentence(paragraph))
    search_from = block[header_match.end():] if header_match is not None else block
    for line in search_from.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if header_match is None and _HEADER_RE.match(f"{line}"):
            continue
        return _clean_inline(_first_sentence(line))
    return ""


def parse_work_log(text: str, file_date: date) -> list[WorkSession]:
    """Pure, deterministic, zero model calls. Splits on `## Session…`
    headings (the whole file is one session when there are none), and per
    block reads the `**Session:** <times> · **Where:** … · **Who:** …`
    header: start/end → hours computed in code (missing/unparseable side →
    hours=None), Where → repos + project, and the Summary's first sentence
    (fallback: first non-empty line after the header) as the one-liner."""
    headings = list(_SESSION_HEADING_RE.finditer(text))
    if headings:
        blocks = []
        for i, h in enumerate(headings):
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            blocks.append((h.group(0).removeprefix("##").strip(), text[h.end():end]))
    else:
        blocks = [("", text)]

    sessions = []
    for label, block in blocks:
        header = _HEADER_RE.search(block)
        if header is not None:
            rest = header.group("rest")
            time_text = rest.split("·")[0]
            start, end, hours = _parse_times(time_text)
            where, repos, project = _parse_where(rest)
        else:
            start = end = hours = None
            where, repos, project = "", [], None
        sessions.append(
            WorkSession(
                date=file_date,
                label=label,
                start=start,
                end=end,
                hours=hours,
                where=where,
                repos=repos,
                project=project,
                description=_block_description(block, header),
            )
        )
    return sessions


# --- import: KB note + auto productivity rows --------------------------------


def mentioned_entity_titles(kb_store, text: str) -> list[str]:
    """Deterministic in code: every Career/* and Projects/* note whose title
    appears in the log as a whole word (graph.title_mentioned — THE one
    matcher) becomes a declared link, materialized into edges by the same
    graph-sync call the KB create path runs."""
    titles = set()
    for n in kb_store.notes_index():
        if n["folder"].split("/", 1)[0] not in ENTITY_ROOTS:
            continue
        if n["title"] and title_mentioned(n["title"], text):
            titles.add(n["title"])
    return sorted(titles)


def _activity_logs_dir(log_store: LogFileStore) -> Path:
    return resolve_nested(log_store.kb_root, home_for("activity", "productivity")) / "logs"


def _next_seq(logs_dir: Path, iso: str) -> int:
    """max+1, NOT count+1: after the dedupe pass deletes this import's old
    files, count+1 could re-use a sequence number a surviving MANUAL file
    already holds and silently overwrite it."""
    seqs = []
    for p in logs_dir.glob(f"{iso}-*.md"):
        tail = p.stem.rsplit("-", 1)[-1]
        if tail.isdigit():
            seqs.append(int(tail))
    return max(seqs, default=0) + 1


def row_description(session: WorkSession) -> str:
    """Prefixed with the project name when Where: implies one — "Quintacle:
    fired five build waves"."""
    description = session.description or "Work session"
    return f"{session.project}: {description}" if session.project else description


def replace_auto_rows(
    conn: sqlite3.Connection,
    log_store: LogFileStore,
    file_date: date,
    sessions: list[WorkSession],
    *,
    staging=None,
    db_path: Path | None = None,
) -> dict:
    """The auto-productivity-rows half of an import (§10): per parsed session
    WITH hours, one activity row — markdown file (source of truth) + SQLite +
    retrieval index. Dedupe is deterministic by tag: every row this function
    ever wrote carries source=WORKLOG_SOURCE, and a re-import first deletes
    exactly those rows for this date — manual rows (empty source) are never
    candidates. `staging` (an MCP WriteSession) + db_path stage every
    deletion/insert for single-ledger-entry undo; None for the in-app path."""
    iso = file_date.isoformat()
    logs_dir = _activity_logs_dir(log_store)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # 1) delete this date's previous auto rows — SQLite first (snapshot the
    # full prior rows for undo), then their markdown files, then the index.
    old_ids = [
        r["id"]
        for r in conn.execute("SELECT id FROM activity_log WHERE date = ? AND source = ?", (iso, WORKLOG_SOURCE))
    ]
    for rid in old_ids:
        if staging is not None and db_path is not None:
            staging.stage_sqlite_row(conn, db_path, "activity_log", "id", rid)
        safe_remove_node(f"activity:{rid}")
    conn.execute("DELETE FROM activity_log WHERE date = ? AND source = ?", (iso, WORKLOG_SOURCE))
    for path in sorted(logs_dir.glob(f"{iso}-*.md")):
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        if post.metadata.get("type") != "activity" or post.metadata.get("source") != WORKLOG_SOURCE:
            continue
        if staging is not None:
            staging.stage_file(path)
        path.unlink()

    # 2) emit one row per session with computed hours.
    written: list[int] = []
    skipped = 0
    for session in sessions:
        if session.hours is None:
            skipped += 1
            continue
        description = row_description(session)
        filename = f"{iso}-{_next_seq(logs_dir, iso):03d}.md"
        post = frontmatter.Post("")
        post["type"] = "activity"
        post["date"] = iso
        post["category"] = "productivity"
        post["description"] = description
        post["hours"] = session.hours
        post["source"] = WORKLOG_SOURCE
        (logs_dir / filename).write_text(frontmatter.dumps(post), encoding="utf-8")
        if staging is not None:
            staging.stage_new_file(logs_dir / filename)
        cur = conn.execute(
            "INSERT INTO activity_log (date, category, description, hours, source) VALUES (?, ?, ?, ?, ?)",
            (iso, "productivity", description, session.hours, WORKLOG_SOURCE),
        )
        row_id = cur.lastrowid
        if staging is not None and db_path is not None:
            staging.stage_sqlite_insert(db_path, "activity_log", "id", row_id)
        safe_index_log_row(f"activity:{row_id}")  # failure-isolated
        written.append(row_id)
    conn.commit()
    return {"rows_written": len(written), "rows_skipped": skipped, "rows_replaced": len(old_ids), "row_ids": written}


def import_work_log(
    file_date: date,
    text: str,
    *,
    kb_store,
    conn: sqlite3.Connection,
    log_store: LogFileStore,
    link_note: Callable[[str, str, str, list[str]], None],
    staging=None,
    db_path: Path | None = None,
) -> dict:
    """One day's work log into Quintacle: the KB note (folder
    `Daily Log/Work Logs`, title `Work log - YYYY-MM-DD`, full text VERBATIM,
    fields {date, kind}) through KBStore + the caller's graph-linking
    machinery + the retrieval index — same calls as the KB create path — plus
    the auto productivity rows (replace_auto_rows). Overwrite-by-title: the
    slugified title maps to one file, so re-importing a day replaces its note
    and (by tag) its rows, duplicating nothing.

    `link_note(note_id, title, content, link_titles)` is the environment's
    note-graph sync — kb.api._sync_note_graph_links for the REST app,
    mcp_server.graph_link.link_new_entry for the MCP server — so both lanes
    form the same mentions edges without this module importing either."""
    sessions = parse_work_log(text, file_date)
    title = note_title_for(file_date)
    links = mentioned_entity_titles(kb_store, text)

    note_path = resolve_nested(kb_store.root, WORKLOG_FOLDER) / f"{slugify(title)}.md"
    if staging is not None:
        staging.stage_file(note_path)
    folder_slug, entry_slug = kb_store.write(
        WORKLOG_FOLDER, title, text, links, fields={"date": file_date.isoformat(), "kind": WORKLOG_KIND}
    )
    link_note(f"note:{folder_slug}/{entry_slug}", title, text, links)
    safe_index_note(folder_slug, entry_slug, title, text)  # failure-isolated

    rows = replace_auto_rows(conn, log_store, file_date, sessions, staging=staging, db_path=db_path)
    return {
        "folder": folder_slug,
        "slug": entry_slug,
        "date": file_date.isoformat(),
        "sessions_parsed": len(sessions),
        "links": links,
        **rows,
    }
