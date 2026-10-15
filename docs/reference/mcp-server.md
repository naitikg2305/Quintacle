# The MCP server

Derived from code at commit `884d057` on 2026-10-15.

> *Moved since the stamp: commit `cc29b0a` added two tools — `day_recall`
> (the deterministic day bundle, shared with `GET /day/{date}`) and
> `describe_photo` (billed on-demand vision, read-only, no ledger entry) —
> so "14 tools" below is now 16.*

Code: [core/quintacle_core/mcp_server/](../../core/quintacle_core/mcp_server/)
— `server.py` (tools), `ledger.py` (the write log), `undo.py` (snapshots +
reversal), `graph_link.py` (the graph adapter). Design history:
`docs/mcp-angle.md` (whose status lines still say "not started" — stale; it
is built).

## Running and registering it

- **Run**: `python -m quintacle_core.mcp_server` (from `core/`, with the
  venv's Python). Transport is **stdio only** — `mcp.run(transport="stdio")`
  via `FastMCP("quintacle")` (SDK pin: `mcp==1.30.0`). No HTTP/SSE/remote
  transport exists.
- **Data dir**: `QUINTACLE_DATA_DIR`, default `~/.quintacle` — the same
  convention as the API. `init()` runs at import time and points every
  store at it; the server imports the real store classes directly and opens
  its own connection to the same `quintacle.db` (it does NOT proxy the
  FastAPI app). Tests re-call `init(tmp_path)` for isolation — the tool
  functions resolve stores from module globals at call time.
- **Client identity**: `QUINTACLE_MCP_CLIENT` env var (e.g. `claude-code`),
  default `unknown-mcp-client` — recorded on every ledger entry, since the
  MCP initialize handshake doesn't carry a client name reliably across SDKs.
- **Register with a client** (Claude Code example — any stdio MCP client is
  equivalent):

```json
{
  "mcpServers": {
    "quintacle": {
      "command": "/path/to/quintacle/core/.venv/bin/python",
      "args": ["-m", "quintacle_core.mcp_server"],
      "env": { "QUINTACLE_MCP_CLIENT": "claude-code" }
    }
  }
}
```

(No `.mcp.json` is checked into the repo; registration is per-client.)

## The write model

Per the 2026-10-13 decision in `docs/mcp-angle.md`: **every write commits
immediately — no approval queue — and every write is exactly undoable.**
Each write tool builds a `WriteSession`, stages a snapshot of everything it
is about to touch (or just created), performs the real store writes, calls
the graph link hook, and commits ONE ledger entry grouping all staged steps
— so a multi-part push undoes as a single unit, never partially.

## The 14 tools (`server.py`), exact parameters

Read tools take/return plain JSON; write tools return their result plus a
`ledger_id`.

| Tool | Parameters | Behavior |
|---|---|---|
| `journal_append` | `for_date: str` (ISO), `content: str` | Appends the exact text to the day's journal, wrapped in a unique `mcp-append` marker; stages a JournalAppendStep; runs graph linking on the content |
| `journal_get` | `for_date: str` | `{date, content|null}` (markers stripped) |
| `kb_list_folders` | — | Every KB folder, `/`-joined |
| `kb_create_entry` | `folder: str`, `title: str`, `content: str`, `links: list[str]|None`, `fields: dict|None` | Create/overwrite-by-title a note; stages the target file; materializes `links` + keyword-links people/experiences |
| `kb_get_entry` | `folder: str`, `slug: str` | Full entry (raises on missing) |
| `kb_search_entries` | `query: str` | Substring search → `{folder, slug, snippet}[]` (same `KBStore.search` as REST) |
| `log_expense` | `for_date: str`, `amount: float`, `merchant=""`, `category=""`, `notes=""`, `kind="regular"` | Writes the markdown log file + `expense_log` row; stages both (file via before/after dir snapshot, row via `stage_sqlite_insert`) |
| `expenses_in_range` | `start: str`, `end: str` | Expense rows between dates inclusive |
| `todo_create` | `title: str`, `priority: int = 2`, `due_date: str|None`, `start_time: str|None`, `end_time: str|None`, `notes=""` | Creates a todo; stages its file |
| `todo_update` | `todo_id: str` + any of title/priority/due_date/start_time/end_time/done/notes | Partial update; the staged before-file means undo restores every prior field |
| `todo_delete` | `todo_id: str` | Stages the file bytes, deletes; undo recreates the exact file |
| `todo_list` | `include_done: bool = False` | Open todos ranked like the app (or everything, unranked) |
| `list_recent_writes` | `limit: int = 20` | Newest-first ledger entries (what/where/client/when/undone?) |
| `undo_write` | `ledger_id: str` | Reverses one write completely (below) |

**The structured-input rule** (docstrings enforce it): every write tool's
parameters are the final, decided shape — `journal_append` "never classifies
or rewrites", `kb_create_entry` "never classifies freeform text into a
folder/title itself", `log_expense` "never guesses a category from a
receipt". Rationale (mcp-angle.md): the thinking already happened in the
(subscription-billed) client conversation; re-classifying server-side would
bill Quintacle's own API key a second time. The planned *convenience* class
of tools (a `drop` tool that DOES spend Quintacle's AI budget) is referenced
by the docstrings but **not built** — today's 14 tools include zero
LLM-calling tools; the MCP server makes no Anthropic calls at all.

## The ledger (`ledger.py`, `<data_dir>/mcp-log.md`)

One append-only, human-readable markdown file; each entry is prose headers
plus a fenced JSON block carrying everything undo needs
(`_ENTRY_RE = ```json … ``` `). `append()` appends; `mark_undone()` rewrites
the whole small file to flip one entry's `undone_at` (nothing is removed).
`recent(limit)` parses all blocks and returns the newest first. Excluded
from sync — each device keeps its own undo history.

A real-shaped entry (constructed from `LedgerEntry.render_markdown()` and
`journal_append`'s staging):

```markdown
## 2026-10-15T14:21:07.113829-04:00 · `3f9c2a7b1d` · journal.append
- client: claude-code
- status: active
- summary: Appended to journal for 2026-10-15

```json
{
  "id": "3f9c2a7b1d",
  "timestamp": "2026-10-15T14:21:07.113829-04:00",
  "client": "claude-code",
  "tool": "journal.append",
  "summary": "Appended to journal for 2026-10-15",
  "steps": [
    {
      "kind": "journal_append",
      "root": "/home/naitikg/.quintacle/journal",
      "entry_date": "2026-10-15",
      "marker": "a1b2c3d4e5f6"
    }
  ],
  "result": {"date": "2026-10-15"},
  "undone_at": null
}
```

---
```

After `undo_write("3f9c2a7b1d")`, the same entry's `status` line and
`undone_at` field show the undo timestamp; a second undo of the same id
raises.

## Undo mechanics (`undo.py`), per step type

`undo(ledger, entry_id)` replays the entry's steps **in reverse order**,
then marks it undone. No time limit at this layer — the 24 h window is a
(future) UI policy only; snapshots work indefinitely.

- **`FileStep {path, before: bytes|None}`** — the file's full bytes right
  before the write. `before=None` (file didn't exist) → undo deletes it;
  otherwise undo rewrites the exact bytes (covers create, edit/overwrite,
  and delete — the step is staged before the delete). Serialized with
  base64 `before_b64`.
- **`JournalAppendStep {root, entry_date, marker}`** — undo calls
  `JournalStore.strip_marked_append`, removing exactly the marker-wrapped
  block (plus its one separator) and leaving every other append — earlier
  or later, MCP or not — untouched. Returns False silently if the block is
  already gone.
- **`SqliteRowStep {db_path, table, pk_column, pk_value, before: dict|None}`**
  — `before=None` (fresh insert) → undo `DELETE`s by primary key; otherwise
  undo `INSERT OR REPLACE`s the complete prior row. The table name is
  validated against `_ALLOWED_TABLES = {edges, expense_log, food_log,
  substance_log, activity_log, exercise_sets, body_stats}` to guard the
  f-string SQL. Opens its own short-lived connection.

## `WriteSession` grouping

One per tool call: `_session(tool, summary)` → stage via
`stage_file(path)` (snapshot BEFORE touching), `stage_new_file(path)`
(AFTER a create whose path the store chose — e.g. `_stage_new_log_files`
diffs the log dir's filenames around the write, since `LogFileStore.write`
picks `<date>-<seq>.md` itself), `stage_journal_append(...)`,
`stage_sqlite_insert(...)` (AFTER, once the PK is known), or
`stage_sqlite_row(...)` (BEFORE an update/delete — currently unused by the
built tools, available for future ones). `commit(result)` writes one
`LedgerEntry` (id = 10-hex uuid, Eastern timestamp) and returns its id.

## The graph_link seam (`graph_link.py`)

The adapter between write tools and the graph engine. `configure(...)` is
called from `init()` with the same data dir/connection. Its
`link_new_entry(entry_type, entry_id, text, *, session, links, **context)`:

1. Snapshots the edge directory's filenames *before* linking — the dir
   diff, not the engine's return value, decides what gets staged for undo
   (because `create_edge` is idempotent: re-returning a pre-existing edge
   must not stage it as "new", or undo would wrongly delete it).
2. Gathers candidates: every person (`note:<folder>/profile`) and every
   experience, and runs the engine's deterministic keyword matcher
   (`source_of_edge="ai_link"`).
3. For a `note:` entry with declared `links`, resolves titles against the
   same note/journal/experience pool `/kb/entries` uses
   (`canonicalize_name` + `sync_frontmatter_links`).
4. Stages every new edge file (`stage_new_file`) AND its `edges` row
   (`stage_sqlite_insert`) on the session — undoing the push removes its
   edges too.
5. Any exception anywhere is swallowed into "no edges": a write must never
   fail because linking broke (the same additive-never-blocking rule as the
   drop router's experience/person checks).

## Code-vs-doc deltas worth knowing

- `docs/mcp-angle.md` / `docs/00-index.md` say the auto-write/undo design is
  "not started" — it is fully built (this file documents the built thing).
- The doc's full per-domain tool table (meals, logs, habits, wardrobe, …)
  is the roadmap; only the 14 tools above exist.
- The "recent writes" UI page over the ledger, and the 24 h undo-offer
  window, are not built; `list_recent_writes`/`undo_write` are the only
  consumers today.
