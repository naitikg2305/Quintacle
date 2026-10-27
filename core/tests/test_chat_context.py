"""The rebuilt chat context (next-wave-plan §3 decision 2 + §4, 2026-10-19):
index→select→fetch over the retrieval engine instead of dump-everything,
topic hydration for note-scoped chats, legacy fallbacks when retrieval is
down, the explicit transcripts lane staying out of default context, and the
"record that" propose→review→Save fold.

No live model calls anywhere: the provider runners and the distillation
parse are monkeypatched. End-to-end tests run on preset-seeded data
(meals/routines/people/experiences + notes + log rows) per CLAUDE.md —
retrieval quality over an empty store is not valid evidence.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.retrieval as retrieval
from quintacle_core import clock
from quintacle_core.nodes.kb import api as kb_api
from quintacle_core.nodes.kb import chat
from quintacle_core.nodes.kb.chat import _last_user_text, _system_text
from quintacle_core.nodes.kb.store import KBStore


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    """Each test wires its own index via create_app (or none) — never
    inherit another test's connection through the module global."""
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())
    # Seed the registries first (CLAUDE.md: entity-grounded, never scratch):
    # meal preset, routine, person, experience — then notes and log rows.
    client.post("/logs/meals", json={"name": "Chipotle bowl", "kcal": 800, "protein_g": 45})
    client.post("/logs/routines", json={"name": "Pull Day", "exercises": ["Deadlift", "Pull Ups"]})
    client.post("/people", json={"name": "Laura", "category": "friend", "how_met": "college"})
    client.post(
        "/travel/experiences",
        json={"name": "Mia Italina Kitchen", "city": "Alexandria", "kind": "restaurant", "rating": "9/10"},
    )
    client.post(
        "/kb/entries",
        json={"folder": "Fitness", "title": "Deadlift Cues", "content": "Brace before you pull. Lats tight."},
    )
    client.post(
        "/kb/entries",
        json={
            "folder": "Fitness",
            "title": "Pull Day Notes",
            "content": "Volume feels right at four sets.",
            "links": ["Deadlift Cues"],
        },
    )
    client.post(
        "/kb/entries",
        json={"folder": "Planning/Travel", "title": "Tokyo Itinerary", "content": "Shinjuku ramen crawl on arrival night."},
    )
    client.post(
        "/logs/expenses", json={"date": "2026-10-12", "amount": 14.5, "merchant": "Chipotle", "category": "food"}
    )
    return client


def _capture_contexts(monkeypatch) -> list[str | None]:
    """Stub every provider runner, recording the kb_text each call got —
    the context assembly is the thing under test, never a live model."""
    captured: list[str | None] = []

    def runner(model, messages, kb_text):
        captured.append(kb_text)
        return "stub-reply"

    for name in ("_run_anthropic", "_run_openai", "_run_bedrock", "_run_local"):
        monkeypatch.setattr(chat, name, runner)
    return captured


def _chat(client, text: str, **extra) -> dict:
    resp = client.post("/kb/chat", json={"messages": [{"role": "user", "content": text}], **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- context assembly selects via retrieve() ---------------------------------


def test_context_is_selected_by_retrieval_not_dumped(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    _chat(client, "what were my deadlift cues again?")
    [kb_text] = captured
    # The selected note arrives in FULL...
    assert "Brace before you pull. Lats tight." in kb_text
    assert "[note:fitness/deadlift-cues]" in kb_text
    # ...and an unrelated note's body is NOT in context (no dump-everything).
    assert "Shinjuku ramen crawl" not in kb_text
    assert "a selection, not the whole knowledge base" in kb_text


def test_structured_rows_enter_as_finished_summary_lines(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    _chat(client, "how much was chipotle?")
    [kb_text] = captured
    # The expense row is the ALREADY-COMPUTED one-liner from SQLite, as-is —
    # the model gets finished numbers, nothing to re-derive.
    assert "Chipotle — $14.50 — food — 2026-10-12" in kb_text
    assert "never recalculate or re-derive" in kb_text


def test_hits_carry_their_graph_neighbor_labels(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    _chat(client, "pull day notes volume")
    [kb_text] = captured
    # Pull Day Notes links to Deadlift Cues — the 1-hop label (title + id)
    # rides along as a plain context line.
    assert "Connected:" in kb_text
    assert "note:fitness/deadlift-cues" in kb_text


def test_nothing_matched_is_said_plainly_not_dumped(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    _chat(client, "zzzqqqxxx")
    [kb_text] = captured
    assert "nothing in the knowledge base matched" in kb_text.lower()
    assert "Shinjuku ramen crawl" not in kb_text


# --- degradation: retrieval down → legacy behavior, never a 500 ---------------


def test_retrieval_uninitialized_falls_back_to_the_legacy_dump(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    retrieval._index = None  # the engine vanishes mid-process
    _chat(client, "what were my deadlift cues again?")
    [kb_text] = captured
    # Old behavior: every note's content is in context — degraded, not broken.
    assert "Brace before you pull. Lats tight." in kb_text
    assert "Shinjuku ramen crawl" in kb_text


def test_retrieval_error_falls_back_to_the_legacy_dump(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("index exploded")

    monkeypatch.setattr(retrieval.RetrievalIndex, "retrieve", boom)
    _chat(client, "deadlift cues?")
    [kb_text] = captured
    assert "Shinjuku ramen crawl" in kb_text  # the dump, not a 500


def test_empty_index_falls_back_to_the_legacy_dump(tmp_path):
    # A store with notes but a never-backfilled (empty) index must not answer
    # "nothing matched" — it degrades to the legacy dump instead.
    store = KBStore(tmp_path / "kb")
    store.write("Fitness", "Deadlift Cues", "Brace before you pull.")
    from quintacle_core.db import connect

    retrieval.init_retrieval_index(connect(tmp_path / "test.db"))  # exists, zero rows
    text = _system_text(store, True, None, None, [{"role": "user", "content": "deadlift?"}])
    assert "Brace before you pull." in text


# --- topic hydration (§4: "continue any topic like a human") ------------------


def test_note_scoped_chat_hydrates_the_topic_node_and_its_neighborhood(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    _chat(client, "should I change the volume?", folder="fitness", slug="pull-day-notes")
    [kb_text] = captured
    assert "## Current topic: Pull Day Notes [note:fitness/pull-day-notes]" in kb_text
    assert "Volume feels right at four sets." in kb_text
    # Its graph neighborhood labels ride along...
    assert "Connected:" in kb_text.split("## Retrieved")[0]
    assert "note:fitness/deadlift-cues" in kb_text
    # ...and no transcript content is ever loaded automatically (none exists
    # here, but the string marker of the archive lane must not appear either).
    assert "transcript" not in kb_text.lower()


def test_topic_chat_still_works_when_retrieval_is_down(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    retrieval._index = None
    _chat(client, "volume?", folder="fitness", slug="pull-day-notes")
    [kb_text] = captured
    # The topic note still hydrates; the folder's entries stand in for retrieval.
    assert "## Current topic: Pull Day Notes" in kb_text
    assert "Brace before you pull. Lats tight." in kb_text  # same folder
    assert "Shinjuku ramen crawl" not in kb_text  # other folders stay out


def test_folder_scoped_chat_is_unchanged_and_sees_only_its_folder(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    _chat(client, "deadlift and tokyo?", folder="fitness")
    [kb_text] = captured
    assert "Brace before you pull. Lats tight." in kb_text
    assert "Volume feels right at four sets." in kb_text
    assert "Shinjuku ramen crawl" not in kb_text  # scoped contract intact
    assert "Retrieved for the latest question" not in kb_text  # no global lane


# --- transcripts: explicit lane only ------------------------------------------


def test_transcripts_never_enter_default_chat_context(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    client.post(
        "/transcripts/archive",
        json={
            "messages": [{"role": "user", "content": "the xylophone gambit is the plan"}],
            "subject": "Scheme Talk",
        },
    )
    # 2026-10-27 (§12): the default (unserious) mode now recalls recent chats
    # by design — see test_chat_modes.py. SERIOUS mode keeps the original
    # §4 guarantee: the archive never enters context.
    _chat(client, "what was the xylophone gambit?", mode="serious")
    # Nothing in the notes matches, so serious mode short-circuits (§12
    # correction) and may not call the model at all — either way the archive
    # must never reach a model context.
    assert all("xylophone" not in kb_text for kb_text in captured)  # serious: KB + notes only

    # The explicit lane DOES reach it — topic, date, snippet for the next turn.
    hits = client.get("/transcripts/search", params={"q": "xylophone gambit"}).json()
    assert len(hits) == 1
    assert hits[0]["topic"] == "scheme-talk"
    assert "xylophone" in hits[0]["snippet"]


# --- escalation: same context, different provider -----------------------------


def test_escalation_gets_the_identical_context(client, monkeypatch):
    captured = _capture_contexts(monkeypatch)
    _chat(client, "deadlift cues?", model="local:qwen3:8b")
    _chat(client, "deadlift cues?", model="claude-sonnet-5-5")
    local_ctx, cloud_ctx = captured
    assert local_ctx == cloud_ctx
    assert "Brace before you pull. Lats tight." in cloud_ctx


# --- "record that": propose (no write) → review → explicit save (append) ------


def _fitness_note(client, slug="pull-day-notes") -> str:
    return client.get("/kb/entry", params={"folder": "fitness", "slug": slug}).json()["content"]


def test_record_that_proposes_a_dated_append_and_writes_nothing(client, monkeypatch):
    monkeypatch.setattr(
        kb_api, "suggest_record_fold", lambda convo, title, provider=None: type("F", (), {"points": "- deload next week"})()
    )
    before = _fitness_note(client)
    resp = client.post(
        "/kb/record-that",
        json={
            "messages": [
                {"role": "user", "content": "I think I should deload"},
                {"role": "assistant", "content": "A deload next week makes sense."},
            ],
            "folder": "fitness",
            "slug": "pull-day-notes",
        },
    )
    assert resp.status_code == 200, resp.text
    proposal = resp.json()
    today = clock.today().isoformat()
    assert proposal["title"] == "Pull Day Notes"
    assert proposal["date"] == today
    assert proposal["append"] == f"### {today} — from chat\n\n- deload next week"
    # Propose NEVER writes — the note on disk is untouched.
    assert _fitness_note(client) == before


def test_record_that_unscoped_proposes_folder_and_title(client, monkeypatch):
    monkeypatch.setattr(
        kb_api,
        "suggest_record_fold_new",
        lambda convo, folders, notes, provider=None: type(
            "F", (), {"folder": "Fitness", "title": "Pull Day Notes", "points": "- bar speed matters"}
        )(),
    )
    resp = client.post("/kb/record-that", json={"messages": [{"role": "user", "content": "bar speed chat"}]})
    assert resp.status_code == 200, resp.text
    proposal = resp.json()
    assert proposal["folder"] == "Fitness"
    assert proposal["title"] == "Pull Day Notes"
    assert proposal["slug"] is None
    assert proposal["append"].startswith(f"### {clock.today().isoformat()} — from chat")


def test_record_that_empty_conversation_is_a_400(client):
    assert client.post("/kb/record-that", json={"messages": []}).status_code == 400


def test_record_that_missing_target_is_a_404(client, monkeypatch):
    resp = client.post(
        "/kb/record-that",
        json={"messages": [{"role": "user", "content": "hi"}], "folder": "fitness", "slug": "no-such-note"},
    )
    assert resp.status_code == 404


def test_record_that_save_appends_without_rewriting_history(client):
    today = clock.today().isoformat()
    resp = client.post(
        "/kb/record-that/save",
        json={"folder": "Fitness", "title": "Pull Day Notes", "append": f"### {today} — from chat\n\n- deload next week"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"folder": "fitness", "slug": "pull-day-notes", "appended": True}
    content = _fitness_note(client)
    # History intact, dated entry at the end, heading not duplicated.
    assert "Volume feels right at four sets." in content
    assert content.rstrip().endswith("- deload next week")
    assert content.index("Volume feels right") < content.index(f"### {today}")
    assert content.count("# Pull Day Notes") == 1

    # The appended words are retrievable — the save re-indexed the note.
    hits = client.get("/retrieve", params={"q": "deload"}).json()["results"]
    assert any(h["id"] == "note:fitness/pull-day-notes" for h in hits)


def test_record_that_save_without_a_matching_note_creates_one(client):
    today = clock.today().isoformat()
    resp = client.post(
        "/kb/record-that/save",
        json={"folder": "Fitness", "title": "Bench Notes", "append": f"### {today} — from chat\n\n- pause reps"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["appended"] is False
    content = _fitness_note(client, "bench-notes")
    assert "- pause reps" in content


def test_record_that_save_empty_append_is_a_400(client):
    assert (
        client.post("/kb/record-that/save", json={"folder": "Fitness", "title": "Pull Day Notes", "append": "  "}).status_code
        == 400
    )


# --- small pure helpers --------------------------------------------------------


def test_last_user_text_takes_the_newest_nonempty_user_turn():
    messages = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": [{"type": "text", "text": "about the deadlift"}, {"type": "image", "source": {}}]},
    ]
    assert _last_user_text(messages) == "about the deadlift"
    assert _last_user_text([]) == ""
