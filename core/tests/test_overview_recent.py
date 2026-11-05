"""Overview page backend: /kb/recent (newest-saved strip) and
/kb/recent-graph (this week's nodes + their 1-hop neighbors)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.retrieval as retrieval
from quintacle_core.db import connect
from quintacle_core.graph import create_edge, init_graph_store
from quintacle_core.retrieval import init_retrieval_index


@pytest.fixture(autouse=True)
def _reset_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


def test_recent_is_newest_first_with_since_and_type_filters(tmp_path):
    index = init_retrieval_index(connect(tmp_path / "test.db"))
    index.index_node("note:Knowledge/old", "note", "Old", updated_at="2026-10-01T09:00:00-04:00")
    index.index_node("note:Knowledge/mid", "note", "Mid", updated_at="2026-10-20T09:00:00-04:00")
    index.index_node("todo:1", "todo", "Pay rent", updated_at="2026-10-30T09:00:00-04:00")

    assert [r["id"] for r in index.recent(limit=10)] == ["todo:1", "note:Knowledge/mid", "note:Knowledge/old"]
    assert [r["id"] for r in index.recent(limit=1)] == ["todo:1"]
    assert [r["id"] for r in index.recent(since="2026-10-15")] == ["todo:1", "note:Knowledge/mid"]
    assert [r["id"] for r in index.recent(types=["note"])] == ["note:Knowledge/mid", "note:Knowledge/old"]


def test_recent_graph_pulls_in_hubs_and_never_transcripts(tmp_path):
    conn = connect(tmp_path / "test.db")
    init_graph_store(tmp_path, conn)
    index = init_retrieval_index(conn)
    index.index_node("note:Daily Log/Work Logs/2026-10-30", "note", "Work log - 2026-10-30", updated_at="2026-10-30T18:00:00-04:00")
    index.index_node("note:Career/Minfy", "note", "Minfy", updated_at="2026-10-01T09:00:00-04:00")
    create_edge("note:Daily Log/Work Logs/2026-10-30", "note:Career/Minfy", "related", "ai_link")
    create_edge("note:Daily Log/Work Logs/2026-10-30", "transcript:2026-10-30/chat", "transcript_of", "ai_link")

    from quintacle_core.nodes.kb.api import kb_recent_graph

    out = kb_recent_graph(since="2026-10-26")
    by_id = {n["id"]: n for n in out["nodes"]}
    assert by_id["note:Daily Log/Work Logs/2026-10-30"]["recent"] is True
    assert by_id["note:Career/Minfy"] == {"id": "note:Career/Minfy", "type": "note", "title": "Minfy", "recent": False}
    assert not any(n.startswith("transcript:") for n in by_id)
    assert out["edges"] == [{"source": "note:Daily Log/Work Logs/2026-10-30", "target": "note:Career/Minfy", "kind": "related"}]


def test_recent_endpoint_over_http(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())
    assert client.post("/kb/entries", json={"folder": "Knowledge", "title": "Deadlift Cues", "content": "Brace."}).status_code == 200
    res = client.get("/kb/recent?limit=5")
    assert res.status_code == 200
    assert any(r["title"] == "Deadlift Cues" for r in res.json())
