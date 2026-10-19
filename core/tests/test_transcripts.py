"""The transcript archive (nodes/kb/transcripts.py — next-wave-plan.md §4):
verbatim archive-on-close into <data_dir>/conversations/ (OUTSIDE kb/), a
deterministic topic slug, a private FTS5 index with the explicit
/transcripts/search lane, the "don't keep" toggle, the transcript_of edge,
and — the invariant that matters most — the archive staying invisible to
every KB/model-facing surface."""
import re

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.db import connect
from quintacle_core.graph import init_graph_store
from quintacle_core.mcp_server import server as mcp
from quintacle_core.nodes.kb.transcripts import TranscriptStore, link_transcript_topic

TURNS = [
    {"role": "user", "content": "should I rebalance the pull day routine?"},
    {"role": "assistant", "content": "Probably — your rows outnumber your curls 3:1 right now."},
]


def make_store(tmp_path) -> TranscriptStore:
    return TranscriptStore(tmp_path)


# --- archive write + verbatim fidelity ---


def test_archive_writes_file_under_conversations_with_frontmatter(tmp_path):
    store = make_store(tmp_path)
    result = store.archive(TURNS, subject="Pull Day Planning")

    assert result["topic"] == "pull-day-planning"
    assert result["message_count"] == 2
    path = tmp_path / "conversations" / result["path"]
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "topic: pull-day-planning" in text
    assert "message_count: 2" in text
    assert "date:" in text
    # the file sits under conversations/<topic-slug>/<stamp>.md
    assert path.parent.name == "pull-day-planning"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{4}", path.stem)


def test_transcript_body_is_verbatim(tmp_path):
    store = make_store(tmp_path)
    gnarly = 'He said: "use **bold**, `code`, #headings & <tags> — verbatim!"\n\n  (indent kept too)'
    result = store.archive(
        [{"role": "user", "content": gnarly}, {"role": "assistant", "content": "Noted."}],
        subject="Fidelity Check",
    )

    text = (tmp_path / "conversations" / result["path"]).read_text(encoding="utf-8")
    assert gnarly in text  # character-for-character, nothing normalized
    assert "### You" in text and "### Assistant" in text


def test_attachment_turns_keep_text_but_never_base64(tmp_path):
    store = make_store(tmp_path)
    blocks = [
        {"type": "text", "text": "what's in this photo?"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJDREVGRw=="}},
    ]
    result = store.archive([{"role": "user", "content": blocks}], subject="photo chat")

    text = (tmp_path / "conversations" / result["path"]).read_text(encoding="utf-8")
    assert "what's in this photo?" in text
    assert "QUJDREVGRw==" not in text


def test_empty_transcript_archives_nothing(tmp_path):
    store = make_store(tmp_path)
    assert store.archive([], subject="nothing happened") is None
    assert list((tmp_path / "conversations").rglob("*.md")) == []


# --- deterministic slug ---


def test_topic_slug_is_deterministic_from_subject(tmp_path):
    store = make_store(tmp_path)
    assert store.topic_slug("Pull Day Planning") == "pull-day-planning"
    assert store.topic_slug("Pull Day Planning") == store.topic_slug("Pull Day Planning")
    assert store.topic_slug("  Stocks: NVDA thesis?! ") == "stocks-nvda-thesis"


def test_topic_slug_falls_back_to_date_time(tmp_path):
    store = make_store(tmp_path)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{4}", store.topic_slug(None))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{4}", store.topic_slug("   "))


def test_two_archives_in_the_same_minute_never_collide(tmp_path):
    store = make_store(tmp_path)
    first = store.archive(TURNS, subject="same topic")
    second = store.archive(TURNS, subject="same topic")

    assert first["path"] != second["path"]
    root = tmp_path / "conversations" / "same-topic"
    assert len(list(root.glob("*.md"))) == 2


# --- FTS search + topic scoping (the one read lane) ---


def test_fts_search_returns_ranked_hits_with_snippets(tmp_path):
    store = make_store(tmp_path)
    store.archive(TURNS, subject="Pull Day Planning")
    store.archive([{"role": "user", "content": "thinking about the NVDA thesis again"}], subject="Stocks")

    hits = store.search("rebalance pull")
    assert len(hits) == 1
    assert hits[0]["topic"] == "pull-day-planning"
    assert "rebalance" in hits[0]["snippet"]
    assert hits[0]["path"].startswith("pull-day-planning/")
    assert set(hits[0]) == {"path", "topic", "date", "snippet"}


def test_fts_search_scopes_to_topic(tmp_path):
    store = make_store(tmp_path)
    store.archive([{"role": "user", "content": "routine volume talk"}], subject="Pull Day")
    store.archive([{"role": "user", "content": "routine for taxes maybe"}], subject="Finance")

    assert {h["topic"] for h in store.search("routine")} == {"pull-day", "finance"}
    scoped = store.search("routine", topic="Pull Day")  # un-slugified input scopes too
    assert [h["topic"] for h in scoped] == ["pull-day"]
    assert store.search("routine", topic="nope") == []


def test_fts_search_survives_hostile_query_syntax(tmp_path):
    store = make_store(tmp_path)
    store.archive(TURNS, subject="Pull Day")
    # FTS5 operators/quotes in user text must not 500 or leak syntax errors
    assert store.search('"NEAR( OR -') == []
    assert store.search("") == []


# --- the transcript_of edge ---


def test_transcript_of_edge_lands_on_the_confidently_named_node(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))
    candidates = [
        {"id": "note:fitness/pull-day", "title": "Pull Day"},
        {"id": "note:fitness/pull-day-planning", "title": "Pull Day Planning"},
        {"id": "note:finance/taxes", "title": "Taxes"},
    ]
    edge = link_transcript_topic("transcript:pull-day-planning/2026-10-19-1400", "Pull Day Planning", candidates)

    # Longest matching title wins — the most specific node, deterministically.
    assert edge["target_id"] == "note:fitness/pull-day-planning"
    assert edge["kind"] == "transcript_of"
    assert edge["source_of_edge"] == "transcript_archive"


def test_no_edge_without_a_confident_match(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))
    candidates = [{"id": "note:finance/taxes", "title": "Taxes"}]

    assert link_transcript_topic("transcript:x/2026-10-19-1400", "Pull Day Planning", candidates) is None
    assert link_transcript_topic("transcript:x/2026-10-19-1400", None, candidates) is None
    conn = connect(tmp_path / "test.db")
    assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0


# --- the REST lane end to end (archive-on-close -> file -> deep search) ---


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


def test_archive_endpoint_writes_search_finds_and_edge_links(client, tmp_path):
    # a real KB note for the topic to map onto
    client.post("/kb/entries", json={"folder": "Fitness", "title": "Pull Day", "content": "rows and curls"})

    resp = client.post("/transcripts/archive", json={"messages": TURNS, "subject": "Pull Day", "keep": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["archived"] is True
    assert body["topic"] == "pull-day"
    assert (tmp_path / "conversations" / body["path"]).exists()

    hits = client.get("/transcripts/search", params={"q": "rebalance", "topic": "pull-day"}).json()
    assert len(hits) == 1 and hits[0]["topic"] == "pull-day"

    conn = connect(tmp_path / "quintacle.db")
    rows = conn.execute("SELECT * FROM edges WHERE kind = 'transcript_of'").fetchall()
    assert len(rows) == 1
    assert rows[0]["source_id"] == f"transcript:{body['topic']}/{body['stamp']}"
    assert rows[0]["target_id"] == "note:fitness/pull-day"


def test_dont_keep_toggle_archives_nothing(client, tmp_path):
    resp = client.post("/transcripts/archive", json={"messages": TURNS, "subject": "Private Yap", "keep": False})
    assert resp.json()["archived"] is False
    assert list((tmp_path / "conversations").rglob("*.md")) == []
    assert client.get("/transcripts/search", params={"q": "rebalance"}).json() == []


# --- invisibility: the archive never surfaces anywhere model-facing ---


def test_archive_is_invisible_to_kb_endpoints(client, tmp_path):
    distinctive = "xyzzy-transcript-only-word"
    client.post(
        "/transcripts/archive",
        json={"messages": [{"role": "user", "content": f"remember {distinctive} forever"}], "subject": "Secret Yap"},
    )
    assert (tmp_path / "conversations" / "secret-yap").exists()

    folders = client.get("/kb/folders").json()
    assert all("conversation" not in f for f in folders)
    assert client.get("/kb/search", params={"q": distinctive}).json() == []
    assert client.get("/kb/entries", params={"folder": "conversations"}).json() == []
    assert client.get("/kb/entries", params={"folder": "../conversations"}).json() == []
    # the graph page's note list never includes transcript bodies either
    notes = client.get("/kb/graph").json()["notes"]
    assert all(distinctive not in str(n) for n in notes)


def test_archive_is_invisible_to_mcp_tools(tmp_path):
    mcp.init(tmp_path)
    store = TranscriptStore(tmp_path)
    store.archive([{"role": "user", "content": "xyzzy-mcp-should-never-see-this"}], subject="Secret Yap")

    assert all("conversation" not in f for f in mcp.kb_list_folders())
    assert mcp.kb_search_entries("xyzzy-mcp-should-never-see-this") == []
