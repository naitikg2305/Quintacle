"""The Knowledge page (2026-11-05, nodes/knowledge/). Sandbox data dir; no
model calls — everything is deterministic file work over kb/knowledge."""
from __future__ import annotations

import frontmatter
import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.retrieval as retrieval
from quintacle_core.graph import get_graph_store
from quintacle_core.nodes.knowledge.page import first_paragraph, topic_label


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    c.kb_root = tmp_path / "kb"
    return c


def _write(root, folder, slug, title, body="", **meta):
    d = root.joinpath(*folder.split("/"))
    d.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(f"# {title}\n\n{body}\n")
    for k, v in meta.items():
        post[k] = v
    (d / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")


def _seed(root):
    _write(root, "knowledge/tech-notes", "about-tech-notes", "About Tech Notes", "Engineering notes I keep.")
    _write(root, "knowledge/tech-notes", "sqlite-fts", "SQLite FTS5", "BM25 ranking with **column weights**.\n\nMore.",
           tags=["databases", "Search"], edited="2026-11-01T10:00:00-04:00")
    _write(root, "knowledge/tech-notes/graphs", "force-directed-graph-layout", "Force-Directed Graph Layout",
           "## Intro\n\nSprings and charges settle the layout.", fields={"tags": "graphs, search"},
           edited="2026-11-04T09:00:00-05:00")
    _write(root, "knowledge/lectures", "linear-algebra", "Linear Algebra", "Eigenvalues.",
           category="Math", private=True, edited="2026-10-01T09:00:00-04:00")
    # Outside Knowledge — never listed.
    _write(root, "projects/quintacle", "design", "Design", "Not knowledge.")


def test_topics_tags_notes_and_charters(client):
    _seed(client.kb_root)
    data = client.get("/knowledge").json()

    slugs = [n["slug"] for n in data["notes"]]
    assert slugs == ["force-directed-graph-layout", "sqlite-fts", "linear-algebra"]  # edited desc, charter skipped
    assert all(not s.startswith("about-") for s in slugs)

    tops = {t["topic"]: t for t in data["topics"]}
    assert set(tops) == {"lectures", "tech-notes"}
    tech = tops["tech-notes"]
    assert tech["count"] == 2 and tech["direct_count"] == 1 and tech["name"] == "Tech Notes"
    assert tech["description"] == "Engineering notes I keep."
    child = tech["children"][0]
    assert child["topic"] == "tech-notes/graphs" and child["label"] == "Tech Notes › Graphs" and child["count"] == 1

    tags = {t["tag"].lower(): t["count"] for t in data["tags"]}
    assert tags["search"] == 2  # "Search" + "search" grouped case-insensitively
    assert tags["databases"] == 1 and tags["graphs"] == 1 and tags["math"] == 1

    fdg = data["notes"][0]
    assert fdg["topic_label"] == "Tech Notes › Graphs"
    assert fdg["summary"] == "Springs and charges settle the layout."
    assert data["notes"][1]["summary"] == "BM25 ranking with column weights."
    la = data["notes"][2]
    assert la["private"] is True  # owner surface: shown, flagged
    assert data["total"] == 3


def test_new_folder_appears_as_topic(client):
    _seed(client.kb_root)
    before = {t["topic"] for t in client.get("/knowledge").json()["topics"]}
    assert "planes" not in before
    _write(client.kb_root, "knowledge/planes", "boeing-747", "Boeing 747", "The queen of the skies.", tags=["aviation"])
    data = client.get("/knowledge").json()
    assert "planes" in {t["topic"] for t in data["topics"]}
    assert any(t["tag"] == "aviation" for t in data["tags"])


def test_filters_topic_tag_and_q(client):
    _seed(client.kb_root)
    by_topic = client.get("/knowledge", params={"topic": "tech-notes"}).json()
    assert {n["slug"] for n in by_topic["notes"]} == {"sqlite-fts", "force-directed-graph-layout"}
    assert len(by_topic["topics"]) == 2  # the filter bar always shows the whole tree
    nested = client.get("/knowledge", params={"topic": "knowledge/tech-notes/graphs"}).json()
    assert [n["slug"] for n in nested["notes"]] == ["force-directed-graph-layout"]

    by_tag = client.get("/knowledge", params={"tag": "SEARCH"}).json()
    assert {n["slug"] for n in by_tag["notes"]} == {"sqlite-fts", "force-directed-graph-layout"}

    by_q = client.get("/knowledge", params={"q": "eigenvalues"}).json()
    assert [n["slug"] for n in by_q["notes"]] == ["linear-algebra"]
    assert client.get("/knowledge", params={"q": "zzz-nothing"}).json()["notes"] == []


def test_q_uses_retrieval_index_for_indexed_notes(client):
    """A note written through POST /kb/entries is in the FTS index; q finds it."""
    r = client.post("/kb/entries", json={"folder": "Knowledge/Research", "title": "Transformer Attention", "content": "Scaled dot product."})
    assert r.status_code == 200, r.text
    hits = client.get("/knowledge", params={"q": "transformer"}).json()["notes"]
    assert [n["slug"] for n in hits] == ["transformer-attention"]
    assert hits[0]["edited"]  # stamped by KBStore.write


def test_hub_tags_and_related(client):
    _seed(client.kb_root)
    _write(client.kb_root, "places/vienna", "profile", "Vienna", "City.")
    store = get_graph_store()
    store.create_edge("note:knowledge/tech-notes/sqlite-fts", "note:places/vienna/profile", "mentions", "test")
    store.create_edge("note:knowledge/tech-notes/sqlite-fts", "note:knowledge/tech-notes/graphs/force-directed-graph-layout", "related", "test")
    data = client.get("/knowledge").json()
    assert {"tag": "Vienna", "count": 1, "kind": "place"} in data["tags"]
    assert client.get("/knowledge", params={"tag": "vienna"}).json()["notes"][0]["slug"] == "sqlite-fts"

    note = client.get("/knowledge/note", params={"folder": "knowledge/tech-notes", "slug": "sqlite-fts"}).json()
    assert note["title"] == "SQLite FTS5" and note["topic_label"] == "Tech Notes"
    rel = {r["id"]: r for r in note["related"]}
    fdg = rel["note:knowledge/tech-notes/graphs/force-directed-graph-layout"]
    assert fdg["knowledge"] is True and fdg["slug"] == "force-directed-graph-layout"
    assert rel["note:places/vienna/profile"]["knowledge"] is False
    assert client.get("/knowledge/note", params={"folder": "knowledge", "slug": "nope"}).status_code == 404


def test_empty_kb_and_helpers(client):
    assert client.get("/knowledge").json()["notes"] == []
    assert topic_label("tech-notes/graphs") == "Tech Notes › Graphs"
    assert first_paragraph("![img](x.png)\n\n```\ncode\n```\n\n- See [the docs](http://x) and [[Other]]") == "See the docs and Other"
