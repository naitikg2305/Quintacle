"""next-wave-plan §12 backend: serious/unserious chat modes (deterministic
phrase switching), the soft record, dated notes in context, and the
transcript-invisibility guarantees. No live model calls: provider runners and
the soft-fact extractor are monkeypatched. Context tests run on a seeded
sandbox store (registries + notes + log rows) per CLAUDE.md."""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.retrieval as retrieval
from quintacle_core import clock
from quintacle_core.graph import get_graph_store
from quintacle_core.mcp_server import server as mcp
from quintacle_core.nodes.kb import chat, soft_record
from quintacle_core.nodes.kb.chat import detect_mode_phrase, resolve_mode
from quintacle_core.nodes.kb.soft_record import SoftRecordStore
from quintacle_core.nodes.kb.transcripts import get_transcript_store

TODAY = clock.today()


def _d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())
    client.post("/logs/meals", json={"name": "Chipotle bowl", "kcal": 800, "protein_g": 45})
    client.post("/logs/routines", json={"name": "Pull Day", "exercises": ["Deadlift", "Pull Ups"]})
    client.post("/people", json={"name": "Laura", "category": "friend", "how_met": "college"})
    client.post("/travel/experiences", json={"name": "Mia Italina Kitchen", "city": "Alexandria", "kind": "restaurant"})
    client.post("/kb/entries", json={"folder": "Fitness", "title": "Deadlift Cues", "content": "Brace before you pull. Lats tight."})
    client.post(
        "/kb/entries",
        json={"folder": "Fitness", "title": "Pull Day Notes", "content": "Volume feels right at four sets.", "links": ["Deadlift Cues"]},
    )
    return client


def _capture(monkeypatch) -> list[str | None]:
    captured: list[str | None] = []

    def runner(model, messages, kb_text):
        captured.append(kb_text)
        return "stub-reply"

    for name in ("_run_anthropic", "_run_openai", "_run_bedrock", "_run_local"):
        monkeypatch.setattr(chat, name, runner)
    return captured


def _chat(client, text, **extra) -> dict:
    r = client.post("/kb/chat", json={"messages": [{"role": "user", "content": text}], **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _seed_recent():
    """Soft facts (in/out of the 30-day window) + transcripts (in/out of the
    14-day window) in the live sandbox stores."""
    sr = soft_record.get_soft_record_store()
    sr.add(_d(1), "Started a 4-day split with kettlebell swings", "kettle/2026-x.md")
    sr.add(_d(10), "Knee is sore after running", "knee/2026-y.md")
    sr.add(_d(45), "Ancient fact from long ago", "old/2026-z.md")
    ts = get_transcript_store()
    ts.archive([{"role": "user", "content": "the kettlebell swing progression is my new plan"}], subject="Kettle")
    old = ts.archive([{"role": "user", "content": "the kettlebell dinosaur routine from ages ago"}], subject="Old Kettle")
    ts.conn.execute("UPDATE transcript_fts SET date = ? WHERE path = ?", (f"{_d(40)}T09:00:00-04:00", old["path"]))
    ts.conn.commit()


# --- phrase detection --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "serious mode", "Serious Mode please", "SERIOUS MODE", "switch to serious mode.", "kb only", "KB only: what's my deadlift cue?",
        "knowledge base only", "just from my notes, what did I say?", "Only from my notes", "only what I've recorded",
        "only what I’ve recorded", "only what i recorded", "strictly from my notes", "Stick to my notes",
        "let's go serious   mode now", "ok (serious mode) go",
    ],
)
def test_serious_phrases_trigger(text):
    assert detect_mode_phrase(text) == "serious"


@pytest.mark.parametrize(
    "text", ["unserious mode", "Casual mode", "normal mode", "ok back to normal", "BACK TO NORMAL!", "go back to normal mode now"]
)
def test_unserious_phrases_trigger(text):
    assert detect_mode_phrase(text) == "unserious"


@pytest.mark.parametrize(
    "text",
    [
        "", "hello", "that's a serious injury", "this is serious", "I'm serious about the split", "serious business",
        "seriously, what is a kb", "knowledge basement only", "the abnormal mode of the engine",
        "stick to my notebook", "just from my notebooks", "they are unserious people", "casual modeling",
        "normal modes of vibration", "back to normalcy",
    ],
)
def test_negatives_do_not_trigger(text):
    assert detect_mode_phrase(text) is None


def test_unserious_is_not_read_as_serious_and_last_phrase_wins():
    assert detect_mode_phrase("unserious mode") == "unserious"
    assert detect_mode_phrase("serious mode ... actually back to normal") == "unserious"
    assert detect_mode_phrase("casual mode, no wait, serious mode") == "serious"


def test_resolve_mode_switch_flag():
    def msg(t):
        return [{"role": "user", "content": t}]

    assert resolve_mode("unserious", msg("serious mode")) == ("serious", True)
    assert resolve_mode("serious", msg("serious mode")) == ("serious", False)  # already there
    assert resolve_mode("serious", msg("what's up")) == ("serious", False)  # sticky
    assert resolve_mode("serious", msg("back to normal")) == ("unserious", True)
    assert resolve_mode(None, msg("hi")) == ("unserious", False)
    # only the NEWEST user message counts
    older = [{"role": "user", "content": "serious mode"}, {"role": "assistant", "content": "ok"}, {"role": "user", "content": "hi"}]
    assert resolve_mode("unserious", older) == ("unserious", False)


# --- endpoint: mode + mode_switched -------------------------------------------


def test_chat_response_carries_mode_and_switch_flag(client, monkeypatch):
    _capture(monkeypatch)
    assert _chat(client, "hello there") == {"reply": "stub-reply", "mode": "unserious", "mode_switched": False}
    r = _chat(client, "kb only please", mode="unserious")
    assert (r["mode"], r["mode_switched"]) == ("serious", True)
    r = _chat(client, "what next?", mode="serious")  # frontend echoes the sticky mode
    assert (r["mode"], r["mode_switched"]) == ("serious", False)
    r = _chat(client, "back to normal", mode="serious")
    assert (r["mode"], r["mode_switched"]) == ("unserious", True)


def test_switch_phrase_changes_the_context_used_this_very_turn(client, monkeypatch):
    captured = _capture(monkeypatch)
    _seed_recent()
    # Nothing in the KB matches "kettlebell" (it only lives in recent chats):
    # the switched-to serious turn short-circuits without a model call
    # (§12 correction 2026-10-27) — the soft material can't leak in.
    r = _chat(client, "serious mode: what is my kettlebell plan?")
    assert r["reply"] == chat.SERIOUS_NOTHING_REPLY and captured == []
    _chat(client, "serious mode: what is my kettlebell plan and deadlift cue?")
    assert "From recent chats" not in captured[-1]


# --- context: serious vs unserious ---------------------------------------------


def test_serious_context_has_no_recent_chats_and_a_strict_instruction(client, monkeypatch):
    captured = _capture(monkeypatch)
    _seed_recent()
    _chat(client, "what is my kettlebell plan and deadlift cue?", mode="serious")
    [text] = captured
    assert "Brace before you pull. Lats tight." in text  # KB retrieval exactly as before
    assert "From recent chats" not in text
    assert "kettlebell swings" not in text and "kettlebell swing progression" not in text
    assert "that's not in your notes" in text
    assert "never guess" in text


def test_unserious_context_has_soft_facts_and_in_window_snippets_only(client, monkeypatch):
    captured = _capture(monkeypatch)
    _seed_recent()
    _chat(client, "what is my kettlebell plan?", mode="unserious")
    [text] = captured
    assert "## From recent chats (not recorded in your notes)" in text
    # soft facts: in-window, dated, newest first; the 45-day-old one excluded
    assert f"- [{_d(1)}] Started a 4-day split with kettlebell swings" in text
    assert f"- [{_d(10)}] Knee is sore after running" in text
    assert text.index(_d(1)) < text.index(_d(10))
    assert "Ancient fact" not in text
    # transcript snippet: in-window included and dated, 40-day-old excluded
    assert f"- [{TODAY.isoformat()}] …" in text and "kettlebell swing progression" in text
    assert "dinosaur" not in text
    # the instruction labels it and never lets it pass as notes
    assert "from a past chat, not in your notes" in text
    assert "Record that" in text
    assert "NOT part of their notes" in text


def test_default_mode_is_unserious(client, monkeypatch):
    captured = _capture(monkeypatch)
    _seed_recent()
    _chat(client, "kettlebell?")
    assert "## From recent chats" in captured[0]


def test_empty_soft_record_and_archive_omit_the_block(client, monkeypatch):
    captured = _capture(monkeypatch)
    _chat(client, "what is my deadlift cue?")
    assert "From recent chats" not in captured[0]
    assert "past chat" not in captured[0]


def test_recent_block_failure_degrades_never_500(client, monkeypatch):
    captured = _capture(monkeypatch)
    _seed_recent()
    monkeypatch.setattr(soft_record, "_store", None)  # soft store "down"
    monkeypatch.setattr("quintacle_core.nodes.kb.transcripts._store", None)  # transcript store "down"
    r = client.post("/kb/chat", json={"messages": [{"role": "user", "content": "kettlebell plan?"}]})
    assert r.status_code == 200
    assert "From recent chats" not in captured[0]


def test_recent_block_shrinks_first_under_budget(client):
    sr = soft_record.get_soft_record_store()
    for i in range(80):
        sr.add(_d(1), f"fact number {i} " + "x" * 60, "t/a.md")
    block = chat._recent_chats_block("anything", 600)
    assert block is not None and len(block) <= 600
    assert chat._recent_chats_block("anything", 100) is None  # no room -> dropped
    big = chat._recent_chats_block("anything", 20000)
    assert len(big) <= chat._RECENT_FACT_CHARS + 400  # facts keep their own ~2,000 char cap


def test_note_sections_carry_their_date(client, monkeypatch):
    captured = _capture(monkeypatch)
    _chat(client, "what were my deadlift cues?")
    assert f"### Deadlift Cues [note:fitness/deadlift-cues] (note) — updated {TODAY.isoformat()}" in captured[0]
    _chat(client, "volume?", folder="fitness", slug="pull-day-notes")
    assert f"## Current topic: Pull Day Notes [note:fitness/pull-day-notes] — updated {TODAY.isoformat()}" in captured[1]


def test_persona_is_human_in_unserious_and_strict_in_serious(client, monkeypatch):
    captured = _capture(monkeypatch)
    _chat(client, "deadlift?", mode="unserious")
    _chat(client, "deadlift?", mode="serious")
    assert "like someone who was there" in captured[0] and "you told me" in captured[0]
    assert "instead of inventing a memory" in captured[0]
    assert "strictly from their own personal knowledge base" in captured[1]
    assert "like someone who was there" not in captured[1]


def test_kb_off_is_still_only_the_now_line(client, monkeypatch):
    captured = _capture(monkeypatch)
    _seed_recent()
    _chat(client, "kettlebell?", use_kb=False)
    assert captured[0].startswith("Now:") and "From recent chats" not in captured[0]


# --- soft record store + endpoints -----------------------------------------------


def test_soft_record_crud_and_dedup(client):
    sr = soft_record.get_soft_record_store()
    a = sr.add(_d(2), "Likes oat milk", "a/1.md")
    b = sr.add(_d(0), "Booked a dentist visit", "b/2.md")
    assert sr.add(_d(2), "Likes oat milk", "other/9.md") is None  # same text same date -> skipped
    assert sr.add(_d(0), "Likes oat milk", "c/3.md") is not None  # same text, new date -> kept

    rows = client.get("/soft-record").json()
    assert len(rows) == 3
    assert [r["date"] for r in rows] == sorted((r["date"] for r in rows), reverse=True)  # newest first
    assert rows[-1] == {"id": a, "date": _d(2), "text": "Likes oat milk", "transcript": "a/1.md"}

    assert client.delete(f"/soft-record/{b}").json() == {"deleted": b}
    assert client.delete(f"/soft-record/{b}").status_code == 404
    assert b not in [r["id"] for r in client.get("/soft-record").json()]


def test_soft_record_is_invisible_to_kb_graph_retrieval_and_mcp(client, tmp_path):
    word = "zzqx-softfact-only-word"
    soft_record.get_soft_record_store().add(_d(0), f"remember {word}", "t/1.md")
    assert (tmp_path / "conversations" / "soft_record.db").exists()
    assert client.get("/kb/search", params={"q": word}).json() == []
    assert all("conversation" not in f for f in client.get("/kb/folders").json())
    assert word not in str(client.get("/kb/graph").json())
    assert word not in str(client.get("/graph").json())
    assert client.get("/retrieve", params={"q": word}).json()["results"] == []
    mcp.init(tmp_path)
    assert mcp.kb_search_entries(word) == []
    assert all("conversation" not in f for f in mcp.kb_list_folders())


def test_store_survives_reopen(tmp_path):
    SoftRecordStore(tmp_path).add("2026-10-01", "persisted", "t/1.md")
    assert [r["text"] for r in SoftRecordStore(tmp_path).rows()] == ["persisted"]


# --- archive -> extraction (background, failure-isolated) --------------------------

TURNS = [
    {"role": "user", "content": "I'm switching to a four day split starting Monday."},
    {"role": "assistant", "content": "Nice, that sounds good."},
]


def test_kept_archive_extracts_facts_in_background(client, monkeypatch):
    seen = []

    def fake(text):
        seen.append(text)
        return ["Switching to a four day split starting Monday", "Switching to a four day split starting Monday", "  "]

    monkeypatch.setattr(soft_record, "extract_facts", fake)
    r = client.post("/transcripts/archive", json={"messages": TURNS, "subject": "Split"}).json()
    assert r["archived"] is True
    assert r["soft_facts_added"] == 0 and r["soft_facts_pending"] is True  # deferred past the response
    # only the USER's turns are sent to the extractor
    assert seen and "four day split" in seen[0] and "Nice, that sounds good" not in seen[0]
    facts = client.get("/soft-record").json()
    assert [f["text"] for f in facts] == ["Switching to a four day split starting Monday"]  # deduped
    assert facts[0]["date"] == r["date"][:10] == TODAY.isoformat()
    assert facts[0]["transcript"] == r["path"]


@pytest.mark.parametrize("flags", [{"keep": False}, {"incognito": True}, {"keep": False, "incognito": True}])
def test_incognito_or_dont_keep_never_extracts_or_archives(client, tmp_path, monkeypatch, flags):
    calls = []
    monkeypatch.setattr(soft_record, "extract_facts", lambda t: calls.append(t) or ["should never exist"])
    r = client.post("/transcripts/archive", json={"messages": TURNS, "subject": "Private", **flags}).json()
    assert r["archived"] is False and r["soft_facts_added"] == 0
    assert calls == []
    assert client.get("/soft-record").json() == []
    assert list((tmp_path / "conversations").rglob("*.md")) == []


def test_empty_transcript_never_extracts(client, monkeypatch):
    calls = []
    monkeypatch.setattr(soft_record, "extract_facts", lambda t: calls.append(t) or ["x"])
    r = client.post("/transcripts/archive", json={"messages": []}).json()
    assert r["archived"] is False and calls == []


def test_extractor_failure_never_fails_the_archive(client, monkeypatch):
    def boom(text):
        raise RuntimeError("ollama is down")

    monkeypatch.setattr(soft_record, "extract_facts", boom)
    r = client.post("/transcripts/archive", json={"messages": TURNS, "subject": "Split"})
    assert r.status_code == 200 and r.json()["archived"] is True
    assert client.get("/soft-record").json() == []


def test_extract_facts_uses_local_parse_and_swallows_errors(monkeypatch):
    from quintacle_core import llm_dispatch

    monkeypatch.setenv("QUINTACLE_SOFT_RECORD_PROVIDER", "local")
    got = {}

    class R:
        parsed = soft_record.SoftFacts(facts=["Has a sore knee", "", "Runs 5k"])

    def fake_parse(system, user, fmt, **kw):
        got.update(kw=kw, user=user)
        return R()

    monkeypatch.setattr(llm_dispatch, "parse_structured", fake_parse)
    assert soft_record.extract_facts("my knee hurts") == ["Has a sore knee", "Runs 5k"]
    assert got["kw"]["provider"] == "local"

    def boom(*a, **k):
        raise RuntimeError("no model")

    monkeypatch.setattr(llm_dispatch, "parse_structured", boom)
    assert soft_record.extract_facts("my knee hurts") == []
    monkeypatch.setenv("QUINTACLE_SOFT_RECORD_PROVIDER", "off")
    assert soft_record.extract_facts("my knee hurts") == []


# --- transcripts never leak through the graph / neighbor labels ----------------------


def _archive_linked_transcript(client):
    r = client.post(
        "/transcripts/archive",
        json={"messages": [{"role": "user", "content": "thinking about volume"}], "subject": "Pull Day Notes"},
    ).json()
    assert r["edge_id"]  # a real transcript_of edge exists in the edges table
    return f"transcript:{r['topic']}/{r['stamp']}"


def test_transcript_ids_never_appear_in_connected_lines(client, monkeypatch):
    captured = _capture(monkeypatch)
    tid = _archive_linked_transcript(client)
    hood = get_graph_store().neighborhood("note:fitness/pull-day-notes", 1)
    assert any(tid in (e["source_id"], e["target_id"]) for e in hood["edges"])  # edge DOES exist
    _chat(client, "volume?", folder="fitness", slug="pull-day-notes")
    _chat(client, "what is my pull day volume?")
    for text in captured:
        assert "transcript:" not in text
    assert "note:fitness/deadlift-cues" in captured[0]  # real neighbors still listed


def test_retrieve_and_neighbor_labels_hide_transcripts(client):
    tid = _archive_linked_transcript(client)
    results = client.get("/retrieve", params={"q": "volume"}).json()["results"]
    assert results
    assert all(not n["id"].startswith("transcript:") for r in results for n in r["neighbors"])
    assert tid not in str(results)
    assert all(not n["id"].startswith("transcript:") for n in retrieval.neighbor_labels("note:fitness/pull-day-notes"))


def test_graph_endpoint_has_no_transcript_nodes_or_edges(client):
    tid = _archive_linked_transcript(client)
    g = client.get("/graph").json()
    assert all(not n["id"].startswith("transcript:") for n in g["nodes"])
    assert tid not in str(g)
