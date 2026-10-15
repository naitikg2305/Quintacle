# Manual LAN sync

Derived from code at commit `884d057` on 2026-10-15.

Code: [core/quintacle_core/sync.py](../../core/quintacle_core/sync.py)
(319 lines, one module). Frontend: `frontend/app/sync/page.tsx`. Design
origin: `docs/deployment-and-privacy.md`'s "sync button" — note the design
doc describes an auto-sync-when-both-live, line-level-diff mechanic; what's
built is simpler and different: **manual pull only, whole-file transfer,
with a journal-specific block merge.** No daemon, no discovery, no
background sync.

Trust model: same as the rest of the API — no auth, the LAN is the auth.
These endpoints must never be exposed off-box.

## Endpoints

| Route | What it does |
|---|---|
| `GET /sync/manifest` | `build_manifest(data_dir)`: `{rel_path: {mtime, size, sha256}}` for every syncable file (full-file SHA-256, 1 MiB chunks) |
| `GET /sync/file?path=` | Raw bytes of one file. Re-validates: resolved path must stay under the data dir (403), must pass `is_syncable` (403), must exist (404) |
| `POST /sync/pull {peer_url, push_back?, self_url?}` | THE operation: pull from the peer, rebuild derived indexes, optionally ask the peer to pull back. 502 if the peer is unreachable |

The peer is just another Quintacle backend (`HttpPeer`: httpx GETs against
those same two read endpoints, 30 s manifest / 120 s file timeouts).

## The exclusion list, verbatim (`EXCLUDED_TOP_LEVEL`)

The syncable set is defined by exclusion — new content trees (vault/, a
future node's folder) sync automatically without touching this module:

```python
EXCLUDED_TOP_LEVEL = frozenset({
    "quintacle.db",      # derived SQLite cache — fully rebuilt from markdown after every pull
    "quintacle.db-wal",  # SQLite WAL sidecar of the cache above (db.py sets journal_mode=WAL)
    "quintacle.db-shm",  # SQLite shared-memory sidecar of the cache above
    "mcp-log.md",        # MCP write ledger — each device keeps its own undo history
    SNAPSHOT_DIR,        # "_sync_snapshots" — this module's own pre-overwrite snapshots, device-local
    "_trash",            # device-local discard bin, never meant to travel
})
```

(`_trash` is reserved; nothing in the codebase creates it yet.)
`is_syncable()` additionally rejects any path with a dot-prefixed component
(`.DS_Store`, editor dotfiles) and tmp-ish suffixes (`~`, `.tmp`, `.swp`,
`.part`). Note what this implies: `vault/` ciphertext, `kb_chats/`,
`profile.json`, `graph/edges/`, and every log/preset file all sync.

## `pull_from_peer` — the merge rules

Diff the peer's manifest against ours, then per remote path (sorted; one
bad file appends to `errors` instead of aborting the sync):

1. **Re-validate everything the peer claims**: `is_syncable(rel)` is
   re-applied and the resolved target must stay inside our data dir
   ("path escapes the data dir — refused") — a peer manifest is never
   trusted blindly.
2. **Peer-only file** → fetched and written, **with the peer's mtime
   preserved** (`os.utime`) → `pulled`.
3. **Identical SHA-256** → `skipped_identical`.
4. **Journal day file** (`journal/\d{4}-\d{2}-\d{2}\.md`) → union-merge
   (below) → `merged_journals`, or `skipped_identical` when the peer's
   blocks were a subset.
5. **Peer newer by mtime** → the losing local copy is first copied
   (`shutil.copy2`, metadata preserved) into
   `_sync_snapshots/<YYYYmmdd-HHMMSS>/<original relative path>`, then
   overwritten with the peer's bytes + mtime → `overwritten_with_snapshot`.
   Nothing is ever silently destroyed.
6. **Local newer or tied** → keep ours → `kept_local_newer` (the peer picks
   our copy up when IT pulls — that's what push_back is for).

**LWW-with-snapshot semantics**: last-writer-wins by file mtime, but every
losing version survives in the snapshot dir. **Mtime preservation** is what
makes repeated syncs converge instead of ping-ponging — the written copy
carries the peer's mtime, so the next comparison is equal, not "newer".

**Additive only — deletions do not propagate** (v1, by design): a file only
the peer has gets copied in; a file only this device has is kept; a file
you deleted locally comes back on the next two-way sync. Real tombstones
are explicitly a v2 problem.

## Journal union-merge (`merge_journal_days`)

A day's file is `### HH:MM` blocks separated by `\n\n---\n\n` (exactly what
`JournalStore.save()` writes). The merge:

1. **Block splitting**: split both files on the separator. Each block gets
   a sort key = its own `HH:MM` stamp; an unstamped block (hand-edited)
   inherits the stamp of the block above it in its source file (initial
   `last_stamp = "00:00"`).
2. **Dedupe**: blocks are kept **byte-for-byte**; a peer block is added only
   if its exact text isn't already present locally. In particular the
   `<!-- mcp-append:id -->` markers survive unchanged, so undo on the
   originating device still finds its span.
3. **Ordering**: the union is sorted by `(stamp, block text)` — fully
   deterministic, so A-pulls-B and B-pulls-A independently produce the
   identical file and the pair converges in one round trip.

Never overwrite: two devices appending to the same day both keep their text.

## push_back (convenience two-way)

`POST /sync/pull` with `push_back: true` + `self_url` (the client must
supply our own LAN-reachable base URL — the server can't reliably guess its
LAN IP; the Sync page computes it from `window.location` and lets the user
edit it). After our pull succeeds, we POST `/sync/pull {peer_url: self_url}`
to the peer (30 s connect / 600 s read timeout). This works because the
pull endpoint is a sync (threadpool) handler — the server still answers the
peer's manifest/file requests while its own request waits. push_back
failure is a warning, not a failure: our pull already landed. Missing
`self_url` → warning, peer not asked.

## Index rebuilds after pull

`rebuild_derived_indexes()` runs unconditionally after every pull (reported
under `rebuilt`): `rebuild_sqlite_index(...)` regenerates every log/preset
table from the markdown that just landed, and `rebuild_from_folder(...)`
regenerates the `edges` table from the synced `graph/edges/` files. No
frontmatter re-backfill is needed — the peer already materialized its links
into edge files, which arrive as data.

## The report shape

```
{ pulled: [...], merged_journals: [...], overwritten_with_snapshot: [...],
  skipped_identical: n, kept_local_newer: n, errors: [...],
  rebuilt: {logs: {...counts}, graph_edges: n},
  push_back?: <the peer's own report>, warnings: [...] }
```

The Sync page renders this as a readable report and remembers the peer
address in localStorage.
