import hashlib
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.sync as sync_module
from quintacle_core.db import connect
from quintacle_core.graph import GraphEdgeStore
from quintacle_core.sync import build_manifest, merge_journal_days, pull_from_peer


class DirPeer:
    """Test stand-in for sync.HttpPeer — reads a second data dir directly
    instead of going over HTTP (TestClient isn't real networking anyway)."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

    def manifest(self):
        return build_manifest(self.data_dir)

    def fetch(self, rel_path):
        return (self.data_dir / rel_path).read_bytes()


def write(root: Path, rel: str, text: str, mtime: float | None = None) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


# --- manifest ---


def test_manifest_respects_exclusions_and_hashes(tmp_path):
    write(tmp_path, "journal/2026-10-10.md", "### 09:00\nhello")
    write(tmp_path, "kb/fitness/deadlift.md", "cues")
    write(tmp_path, "vault/secret.bin", "opaque bytes")
    write(tmp_path, "quintacle.db", "derived")
    write(tmp_path, "quintacle.db-wal", "derived")
    write(tmp_path, "mcp-log.md", "device-local ledger")
    write(tmp_path, "_sync_snapshots/20261010-090000/kb/old.md", "snapshot")
    write(tmp_path, "_trash/gone.md", "trashed")
    write(tmp_path, "kb/.DS_Store", "junk")
    write(tmp_path, "kb/note.md.tmp", "half-written")

    manifest = build_manifest(tmp_path)

    assert set(manifest) == {"journal/2026-10-10.md", "kb/fitness/deadlift.md", "vault/secret.bin"}
    entry = manifest["journal/2026-10-10.md"]
    raw = (tmp_path / "journal/2026-10-10.md").read_bytes()
    assert entry["sha256"] == hashlib.sha256(raw).hexdigest()
    assert entry["size"] == len(raw)
    assert entry["mtime"] == (tmp_path / "journal/2026-10-10.md").stat().st_mtime


def test_file_endpoint_rejects_traversal_and_excluded(tmp_path):
    data_dir = tmp_path / "data"
    write(data_dir, "journal/2026-10-10.md", "### 09:00\nhello")
    write(data_dir, "quintacle.db", "derived")
    write(tmp_path, "secret.txt", "outside the data dir")

    app = FastAPI()
    sync_module.init_sync(data_dir)
    app.include_router(sync_module.router)
    client = TestClient(app)

    ok = client.get("/sync/file", params={"path": "journal/2026-10-10.md"})
    assert ok.status_code == 200
    assert ok.content == b"### 09:00\nhello"

    assert client.get("/sync/file", params={"path": "../secret.txt"}).status_code == 403
    assert client.get("/sync/file", params={"path": "quintacle.db"}).status_code == 403
    assert client.get("/sync/file", params={"path": "journal/nope.md"}).status_code == 404


# --- journal union-merge ---

MCP_BLOCK = "### 21:30\n<!-- mcp-append:abc123def456 -->\nevening from phone\n<!-- /mcp-append:abc123def456 -->"


def test_journal_union_merge_keeps_both_devices_blocks(tmp_path):
    local, peer = tmp_path / "laptop", tmp_path / "phone"
    write(local, "journal/2026-10-10.md", "### 08:00\nmorning run")
    write(peer, "journal/2026-10-10.md", MCP_BLOCK)

    report = pull_from_peer(local, DirPeer(peer))

    assert report["merged_journals"] == ["journal/2026-10-10.md"]
    assert report["errors"] == []
    merged = (local / "journal/2026-10-10.md").read_text(encoding="utf-8")
    assert merged.count("morning run") == 1
    # MCP markers survive byte-for-byte, so undo on the phone still works.
    assert merged.count(MCP_BLOCK) == 1
    # chronological block order
    assert merged.index("08:00") < merged.index("21:30")

    # Pulling again adds nothing — the peer's blocks are now a subset.
    again = pull_from_peer(local, DirPeer(peer))
    assert again["merged_journals"] == []
    assert again["skipped_identical"] == 1
    assert (local / "journal/2026-10-10.md").read_text(encoding="utf-8") == merged


def test_journal_merge_converges_in_both_directions(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, "journal/2026-10-10.md", "### 09:15\nfrom laptop\n\n---\n\n### 14:00\nalso laptop")
    write(b, "journal/2026-10-10.md", "### 07:30\nfrom phone")

    pull_from_peer(a, DirPeer(b))
    pull_from_peer(b, DirPeer(a))

    text_a = (a / "journal/2026-10-10.md").read_text(encoding="utf-8")
    text_b = (b / "journal/2026-10-10.md").read_text(encoding="utf-8")
    assert text_a == text_b
    assert text_a.index("07:30") < text_a.index("09:15") < text_a.index("14:00")


def test_identical_journal_days_skip(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    content = "### 08:00\nsame everywhere"
    write(a, "journal/2026-10-10.md", content)
    write(b, "journal/2026-10-10.md", content)

    report = pull_from_peer(a, DirPeer(b))

    assert report["skipped_identical"] == 1
    assert report["merged_journals"] == []
    assert (a / "journal/2026-10-10.md").read_text(encoding="utf-8") == content


def test_merge_journal_days_dedupes_by_exact_block_text():
    merged = merge_journal_days(
        "### 08:00\nshared block",
        "### 08:00\nshared block\n\n---\n\n### 08:00\nshared block but different",
    )
    assert merged.count("shared block but different") == 1
    assert merged.count("### 08:00\nshared block\n") == 1  # not duplicated


# --- last-writer-wins for everything else ---


def test_lww_newer_peer_overwrites_and_snapshots_local(tmp_path):
    local, peer = tmp_path / "laptop", tmp_path / "phone"
    write(local, "kb/fitness/deadlift.md", "old local cues", mtime=1_000_000.0)
    write(peer, "kb/fitness/deadlift.md", "newer phone cues", mtime=2_000_000.0)

    report = pull_from_peer(local, DirPeer(peer))

    assert report["overwritten_with_snapshot"] == ["kb/fitness/deadlift.md"]
    target = local / "kb/fitness/deadlift.md"
    assert target.read_text(encoding="utf-8") == "newer phone cues"
    # peer's mtime preserved so repeated syncs converge instead of ping-ponging
    assert target.stat().st_mtime == 2_000_000.0
    snapshots = list((local / "_sync_snapshots").rglob("deadlift.md"))
    assert len(snapshots) == 1
    assert snapshots[0].read_text(encoding="utf-8") == "old local cues"
    assert "kb/fitness/deadlift.md" in str(snapshots[0])


def test_lww_older_peer_file_does_not_overwrite(tmp_path):
    local, peer = tmp_path / "laptop", tmp_path / "phone"
    write(local, "kb/fitness/deadlift.md", "newer local cues", mtime=2_000_000.0)
    write(peer, "kb/fitness/deadlift.md", "stale phone cues", mtime=1_000_000.0)

    report = pull_from_peer(local, DirPeer(peer))

    assert report["kept_local_newer"] == 1
    assert report["overwritten_with_snapshot"] == []
    assert (local / "kb/fitness/deadlift.md").read_text(encoding="utf-8") == "newer local cues"
    assert not (local / "_sync_snapshots").exists()


def test_additive_local_only_files_survive_and_peer_only_copy_in(tmp_path):
    local, peer = tmp_path / "laptop", tmp_path / "phone"
    write(local, "kb/laptop-only.md", "only here")
    write(peer, "kb/phone-only.md", "only there", mtime=1_500_000.0)
    write(peer, "vault/blob.bin", "opaque encrypted bytes", mtime=1_500_000.0)

    report = pull_from_peer(local, DirPeer(peer))

    assert sorted(report["pulled"]) == ["kb/phone-only.md", "vault/blob.bin"]
    assert report["errors"] == []
    # additive: deletions do NOT propagate — local-only files are kept
    assert (local / "kb/laptop-only.md").read_text(encoding="utf-8") == "only here"
    pulled = local / "kb/phone-only.md"
    assert pulled.read_text(encoding="utf-8") == "only there"
    assert pulled.stat().st_mtime == 1_500_000.0


def test_pull_never_copies_peers_excluded_files(tmp_path):
    local, peer = tmp_path / "laptop", tmp_path / "phone"
    local.mkdir()
    write(peer, "quintacle.db", "peer's derived cache")
    write(peer, "mcp-log.md", "peer's undo ledger")
    write(peer, "journal/2026-10-10.md", "### 08:00\nreal data")

    report = pull_from_peer(local, DirPeer(peer))

    assert report["pulled"] == ["journal/2026-10-10.md"]
    assert not (local / "quintacle.db").exists()
    assert not (local / "mcp-log.md").exists()


# --- end to end: pull + derived-index rebuild through the real app ---


def test_end_to_end_pull_rebuilds_sqlite_and_graph(tmp_path, monkeypatch):
    local_dir, peer_dir = tmp_path / "laptop", tmp_path / "phone"
    local_dir.mkdir()

    # Seed the "phone": a journal day, a markdown activity log (the SQLite
    # activity_log index is rebuilt from these), and a graph edge file.
    write(peer_dir, "journal/2026-10-10.md", "### 09:00\nphone-only day")
    write(
        peer_dir,
        "kb/daily-log/productivity/logs/2026-10-10-001.md",
        '---\ntype: activity\ndate: "2026-10-10"\ncategory: productivity\ndescription: wrote sync code\nhours: 2\n---\n',
    )
    peer_conn = connect(peer_dir / "quintacle.db")
    GraphEdgeStore(peer_dir, peer_conn).create_edge("note:a/a", "journal:2026-10-10", "on_day", "test")
    peer_conn.close()

    monkeypatch.setattr(api_module, "DATA_DIR", local_dir)
    client = TestClient(api_module.create_app())
    monkeypatch.setattr(sync_module, "HttpPeer", lambda url: DirPeer(peer_dir))

    res = client.post("/sync/pull", json={"peer_url": "http://192.168.1.99:8000"})
    assert res.status_code == 200
    report = res.json()
    assert report["errors"] == []
    assert "journal/2026-10-10.md" in report["pulled"]
    assert all("quintacle.db" not in p for p in report["pulled"])
    assert report["rebuilt"]["graph_edges"] == 1
    assert report["warnings"] == []

    # The rebuilt SQLite log index reflects the pulled markdown.
    acts = client.get("/logs/activities/2026-10-10").json()
    assert any(a["description"] == "wrote sync code" for a in acts)
    # The rebuilt edges table reflects the pulled edge file.
    graph = client.get("/graph").json()
    assert {"source": "note:a/a", "target": "journal:2026-10-10", "kind": "on_day"} in graph["edges"]
    # And the journal content is readable through the normal endpoint.
    assert "phone-only day" in client.get("/journal/2026-10-10").json()["content"]

    # The manifest this device now serves includes the pulled files but
    # still excludes its own derived db.
    manifest = client.get("/sync/manifest").json()
    assert "journal/2026-10-10.md" in manifest
    assert "quintacle.db" not in manifest


def test_push_back_failure_is_warning_not_failure(tmp_path, monkeypatch):
    local_dir, peer_dir = tmp_path / "laptop", tmp_path / "phone"
    local_dir.mkdir()
    write(peer_dir, "journal/2026-10-10.md", "### 09:00\nphone day")

    monkeypatch.setattr(api_module, "DATA_DIR", local_dir)
    client = TestClient(api_module.create_app())
    monkeypatch.setattr(sync_module, "HttpPeer", lambda url: DirPeer(peer_dir))

    def boom(*args, **kwargs):
        raise RuntimeError("peer can't reach us")

    monkeypatch.setattr(sync_module.httpx, "post", boom)

    res = client.post(
        "/sync/pull",
        json={"peer_url": "http://192.168.1.99:8000", "push_back": True, "self_url": "http://192.168.1.50:8000"},
    )
    assert res.status_code == 200
    report = res.json()
    assert report["pulled"] == ["journal/2026-10-10.md"]
    assert len(report["warnings"]) == 1
    assert "push_back failed" in report["warnings"][0]
