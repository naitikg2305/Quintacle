"""Manual LAN sync — docs/deployment-and-privacy.md's "sync button", v1.

Two devices (laptop + phone running the same backend via Termux), each with
its own full data dir, on the same wifi. The user presses a button and THIS
device pulls from the peer: fetch its manifest, diff, merge/copy what
differs, then rebuild every derived SQLite index from the markdown that just
landed. Manual trigger only — no daemon, no background sync, no discovery.

Trust model: same as the rest of the API (see docs/self-hosting.md) — no
auth, the LAN is the auth. These endpoints must never be exposed off-box.

Semantics, in one place:
- Journal day files (journal/YYYY-MM-DD.md) union-merge by timestamped
  block — never overwrite, so two devices appending to the same day both
  keep their text. MCP-append markers inside blocks survive byte-for-byte.
- Everything else is last-writer-wins by mtime, and the losing local copy is
  snapshotted into _sync_snapshots/<timestamp>/<original path> first —
  nothing is ever silently destroyed.
- Additive only: a file only the peer has gets copied in; a file only this
  device has is kept. DELETIONS DO NOT PROPAGATE in v1 — deleting a file on
  one device does not delete it on the other, it comes back on the next
  two-way sync. (Real tombstones are a v2 problem.)
- The peer file's mtime is preserved on the written copy, so repeated syncs
  converge instead of ping-ponging LWW.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

import httpx  # already installed transitively (anthropic/openai SDKs in requirements.txt)
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from . import clock
from .graph import get_graph_store, rebuild_from_folder
from .nodes.logs.api import get_log_store, get_repo
from .nodes.logs.log_store import rebuild_sqlite_index

SNAPSHOT_DIR = "_sync_snapshots"

# Everything under the data dir syncs EXCEPT these top-level names — the
# syncable set is defined by exclusion, so new content trees (vault/, a
# future node's folder) sync automatically without touching this module.
EXCLUDED_TOP_LEVEL = frozenset(
    {
        "quintacle.db",  # derived SQLite cache — fully rebuilt from markdown after every pull
        "quintacle.db-wal",  # SQLite WAL sidecar of the cache above (db.py sets journal_mode=WAL)
        "quintacle.db-shm",  # SQLite shared-memory sidecar of the cache above
        "mcp-log.md",  # MCP write ledger — each device keeps its own undo history
        SNAPSHOT_DIR,  # this module's own pre-overwrite snapshots — device-local safety net
        "_trash",  # device-local discard bin, never meant to travel
    }
)

_JOURNAL_DAY_RE = re.compile(r"^journal/\d{4}-\d{2}-\d{2}\.md$")
_STAMP_RE = re.compile(r"^### (\d{2}:\d{2})")
_SEPARATOR = "\n\n---\n\n"  # same block separator JournalStore.save() writes


def is_syncable(rel_path: str) -> bool:
    """Whether a data-dir-relative posix path is real synced data (vs the
    derived/device-local exclusions above, hidden files, or tmp droppings)."""
    parts = rel_path.split("/")
    if parts[0] in EXCLUDED_TOP_LEVEL:
        return False
    if any(part.startswith(".") for part in parts):
        return False  # .DS_Store, .nomedia, editor dotfiles
    if parts[-1].endswith(("~", ".tmp", ".swp", ".part")):
        return False  # tmp-ish leftovers
    return True


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(data_dir: Path) -> dict[str, dict]:
    """relative_path -> {mtime, size, sha256} for every syncable file."""
    root = Path(data_dir).resolve()
    manifest: dict[str, dict] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not is_syncable(rel):
            continue
        st = path.stat()
        manifest[rel] = {"mtime": st.st_mtime, "size": st.st_size, "sha256": _sha256(path)}
    return manifest


def merge_journal_days(local_text: str, peer_text: str) -> str:
    """Union-merge of one day's journal file: every local block + every peer
    block the local side doesn't already contain, deduped by exact block
    text, in a stable order both devices independently converge on.

    A day's file is `### HH:MM` blocks separated by `\\n\\n---\\n\\n` (see
    nodes/journal/store.py). Blocks are kept byte-for-byte — in particular
    the `<!-- mcp-append:id -->` markers an MCP write wraps around its text
    must survive so undo on the originating device still finds its span.

    Ordering: by each block's own HH:MM stamp (an unstamped hand-edited
    block inherits the stamp of the block above it in its source file), ties
    broken by block text — deterministic, so A-pulls-B and B-pulls-A produce
    the identical file and the pair converges in one round trip.
    """

    def blocks_with_keys(text: str) -> list[tuple[str, str]]:
        if not text.strip():
            return []
        keyed = []
        last_stamp = "00:00"
        for block in text.split(_SEPARATOR):
            m = _STAMP_RE.match(block)
            if m:
                last_stamp = m.group(1)
            keyed.append((last_stamp, block))
        return keyed

    local_blocks = blocks_with_keys(local_text)
    seen = {block for _, block in local_blocks}
    merged = list(local_blocks)
    for key, block in blocks_with_keys(peer_text):
        if block not in seen:
            seen.add(block)
            merged.append((key, block))
    merged.sort(key=lambda kb: (kb[0], kb[1]))
    return _SEPARATOR.join(block for _, block in merged)


class HttpPeer:
    """The real peer: another Quintacle backend on the LAN, same endpoints."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def manifest(self) -> dict[str, dict]:
        r = httpx.get(f"{self.base_url}/sync/manifest", timeout=30)
        r.raise_for_status()
        return r.json()

    def fetch(self, rel_path: str) -> bytes:
        r = httpx.get(f"{self.base_url}/sync/file", params={"path": rel_path}, timeout=120)
        r.raise_for_status()
        return r.content


def _write_with_mtime(target: Path, data: bytes, mtime: float) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    # Keep the peer's mtime: repeated syncs must converge, not ping-pong LWW.
    os.utime(target, (mtime, mtime))


def pull_from_peer(data_dir: Path, peer) -> dict:
    """THE operation — diff the peer's manifest against ours and apply the
    semantics from the module docstring. `peer` is anything with .manifest()
    and .fetch(rel_path) (HttpPeer in production, a filesystem stub in tests).

    Local-only files are deliberately untouched: additive sync, deletions do
    not propagate in v1."""
    root = Path(data_dir).resolve()
    local = build_manifest(root)
    remote = peer.manifest()
    report: dict = {
        "pulled": [],
        "merged_journals": [],
        "overwritten_with_snapshot": [],
        "skipped_identical": 0,
        "kept_local_newer": 0,
        "errors": [],
    }
    snapshot_root = root / SNAPSHOT_DIR / clock.now().strftime("%Y%m%d-%H%M%S")

    for rel in sorted(remote):
        # Never trust a peer manifest blindly: re-apply the exclusion rules
        # and the traversal check on every path it claims to have.
        if not is_syncable(rel):
            continue
        target = root / rel
        if not target.resolve().is_relative_to(root):
            report["errors"].append(f"{rel}: path escapes the data dir — refused")
            continue
        try:
            info = remote[rel]
            if rel not in local:
                _write_with_mtime(target, peer.fetch(rel), info["mtime"])
                report["pulled"].append(rel)
            elif local[rel]["sha256"] == info["sha256"]:
                report["skipped_identical"] += 1
            elif _JOURNAL_DAY_RE.match(rel):
                local_text = target.read_text(encoding="utf-8")
                merged = merge_journal_days(local_text, peer.fetch(rel).decode("utf-8"))
                if merged == local_text:
                    # Peer's blocks were a subset of ours — nothing new.
                    report["skipped_identical"] += 1
                else:
                    target.write_text(merged, encoding="utf-8")
                    report["merged_journals"].append(rel)
            elif info["mtime"] > local[rel]["mtime"]:
                data = peer.fetch(rel)
                snap = snapshot_root / rel
                snap.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, snap)  # the losing version, never silently destroyed
                _write_with_mtime(target, data, info["mtime"])
                report["overwritten_with_snapshot"].append(rel)
            else:
                # Local is newer (or tied): keep ours; the peer picks our copy
                # up when IT pulls (that's what two-way / push_back is for).
                report["kept_local_newer"] += 1
        except Exception as e:  # one bad file must not abort the whole sync
            report["errors"].append(f"{rel}: {e}")
    return report


def rebuild_derived_indexes() -> dict:
    """SQLite is never the record — after files change under it, regenerate
    every derived index from the markdown, exactly like api.py's startup and
    /logs/rebuild-index do. Graph edges rebuild from the synced graph/edges/
    files (the peer already materialized its frontmatter links into edge
    files, so those arrive as data — no need to re-run api.py's one-time
    frontmatter backfill here)."""
    repo = get_repo()
    log_store = get_log_store()
    logs_counts = (
        rebuild_sqlite_index(log_store, repo.conn, repo.preset_store, repo.ingredient_store)
        if log_store is not None
        else {}
    )
    graph_store = get_graph_store()
    edge_count = rebuild_from_folder(graph_store.data_dir, graph_store.conn)
    return {"logs": logs_counts, "graph_edges": edge_count}


# --- router ---

router = APIRouter(prefix="/sync", tags=["sync"])
_data_dir: Path | None = None


def init_sync(data_dir: Path) -> None:
    global _data_dir
    _data_dir = Path(data_dir)


def get_data_dir() -> Path:
    if _data_dir is None:
        raise RuntimeError("sync not initialized — call init_sync() first")
    return _data_dir


@router.get("/manifest")
def sync_manifest() -> dict[str, dict]:
    return build_manifest(get_data_dir())


@router.get("/file")
def sync_file(path: str) -> Response:
    """Raw bytes of one syncable file — what a peer's pull fetches. Rejects
    anything outside the data dir (resolve + prefix check) or excluded."""
    root = get_data_dir().resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(403, "path escapes the data dir")
    rel = candidate.relative_to(root).as_posix()
    if not is_syncable(rel):
        raise HTTPException(403, f"{rel!r} is not a syncable file")
    if not candidate.is_file():
        raise HTTPException(404, f"no such file: {rel!r}")
    return Response(content=candidate.read_bytes(), media_type="application/octet-stream")


class PullRequest(BaseModel):
    peer_url: str
    push_back: bool = False
    # Our own LAN-reachable base URL, supplied by the client — the server
    # can't reliably guess its own LAN IP. Required for push_back to work.
    self_url: str | None = None


@router.post("/pull")
def sync_pull(body: PullRequest) -> dict:
    peer = HttpPeer(body.peer_url)
    try:
        report = pull_from_peer(get_data_dir(), peer)
    except Exception as e:
        raise HTTPException(502, f"could not pull from peer {body.peer_url!r}: {e}")
    report["rebuilt"] = rebuild_derived_indexes()

    # Convenience two-way: after our pull, ask the peer to pull from us.
    # Failure here is a warning, not a failure — our own pull already landed.
    warnings: list[str] = []
    if body.push_back:
        if not body.self_url:
            warnings.append("push_back requested but no self_url provided — peer was not asked to pull")
        else:
            try:
                # This endpoint runs sync (threadpool), so the server still
                # answers the peer's /sync/manifest + /sync/file calls while
                # this request waits.
                r = httpx.post(
                    f"{body.peer_url.rstrip('/')}/sync/pull",
                    json={"peer_url": body.self_url},
                    timeout=httpx.Timeout(30, read=600),
                )
                r.raise_for_status()
                report["push_back"] = r.json()
            except Exception as e:
                warnings.append(f"push_back failed (peer couldn't pull from {body.self_url!r}): {e}")
    report["warnings"] = warnings
    return report
