"""The private note flag (owner rule 2026-11-05, nodes/kb/privacy.py): a KB
note with `private: true` never reaches a cloud model and is never served by
the MCP server; local chat may use it; a local→cloud handoff strips it with
a count for the UI notice. No live model calls anywhere — provider runners,
suggesters and vision are monkeypatched; every store is a tmp sandbox."""
from __future__ import annotations

import io

import frontmatter
import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.llm_dispatch as llm_dispatch
import quintacle_core.retrieval as retrieval
from quintacle_core.nodes.kb import api as kb_api
from quintacle_core.nodes.kb import chat
from quintacle_core.nodes.kb.privacy import (
    PrivacyGate,
    is_private_meta,
    private_manual_entry,
    public_notes_index,
    strip_private_turns,
)
from quintacle_core.nodes.kb.store import KBStore

PROVIDER_RUNNERS = ("_run_anthropic", "_run_openai", "_run_bedrock", "_run_local")
SECRET = "therapist said the panic attacks started in March"
PUBLIC = "Deadlift cues: brace before you pull, lats tight"
PRIVATE_ID = "note:health/therapy-notes"


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A seeded sandbox: a public note, a private note that links to it (a
    graph edge, so the public note's neighbor label names the private one),
    a private Me note and a public Me note."""
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    c.post("/logs/routines", json={"name": "Pull Day", "exercises": ["Deadlift", "Pull Ups"]})
    c.post("/people", json={"name": "Laura", "category": "friend", "how_met": "college"})
    assert c.post("/kb/entries", json={"folder": "Fitness", "title": "Deadlift Cues", "content": PUBLIC}).status_code == 200
    r = c.post(
        "/kb/entries",
        json={
            "folder": "Health",
            "title": "Therapy Notes",
            "content": f"{SECRET}. Deadlift sessions help.",
            "links": ["Deadlift Cues"],
            "private": True,
        },
    )
    assert r.json() == {"folder": "health", "slug": "therapy-notes"}
    c.post("/kb/entries", json={"folder": "Me", "title": "Diagnosis", "content": "zebrafinch condition", "private": True})
    c.post("/kb/entries", json={"folder": "Me", "title": "Basics", "content": "I live in Maryland"})
    return c


def _spy(monkeypatch, reply: str = "stub-reply") -> list[dict]:
    calls: list[dict] = []

    def make(name):
        def runner(model, messages, kb_text):
            calls.append({"runner": name, "messages": messages, "kb_text": kb_text or ""})
            return reply

        return runner

    for name in PROVIDER_RUNNERS:
        monkeypatch.setattr(chat, name, make(name))
    return calls


def _chat(client, messages, model, **extra) -> dict:
    r = client.post("/kb/chat", json={"messages": messages, "model": model, **extra})
    assert r.status_code == 200, r.text
    return r.json()


# --- the shared definition ---------------------------------------------------


@pytest.mark.parametrize("value", [True, "true", "True", "yes", " YES ", "1", "on", 1])
def test_is_private_meta_truthy_spellings(value):
    assert is_private_meta({"private": value}) is True


@pytest.mark.parametrize("value", [False, "false", "no", "0", "off", "", None, 0, [], "maybe"])
def test_is_private_meta_falsy_spellings(value):
    assert is_private_meta({"private": value}) is False


def test_is_private_meta_missing_or_empty():
    assert is_private_meta(None) is False
    assert is_private_meta({}) is False
    assert is_private_meta({"title": "x"}) is False


def test_store_reads_hand_typed_private_yes(tmp_path):
    store = KBStore(tmp_path / "kb")
    store.write("Health", "Hand Typed", "body")
    path = tmp_path / "kb" / "health" / "hand-typed.md"
    path.write_text(path.read_text().replace("links: []", "links: []\nprivate: yes"))
    assert store.is_private("Health", "hand-typed")
    assert public_notes_index(store) == []


def test_gate_records_only_admitted_private_notes(tmp_path):
    store = KBStore(tmp_path / "kb")
    store.write("Health", "Secret", "s")
    store.write("Health", "Open", "o")
    store.set_private("health", "secret", True)
    cloud = PrivacyGate(store, allow_private=False)
    assert cloud.admit("note:health/open") and not cloud.admit("note:health/secret")
    assert cloud.used == set() and cloud.exclude_hook() is not None
    local = PrivacyGate(store, allow_private=True)
    assert local.admit("note:health/secret") and local.used == {"note:health/secret"}
    assert local.exclude_hook() is None
    assert not cloud.admit("note:health/secret") and cloud.admit("expense:1") and cloud.admit("journal:2026-11-05")


# --- chat context: cloud excludes, local includes -----------------------------


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "gpt-5-mini", "bedrock:us.amazon.nova-lite-v1:0"])
def test_cloud_chat_context_never_contains_private_notes(client, monkeypatch, model):
    calls = _spy(monkeypatch)
    r = _chat(client, [{"role": "user", "content": "what about deadlift and the therapist panic attacks? zebrafinch?"}], model)
    [call] = calls
    text = call["kb_text"]
    assert "brace before you pull" in text  # public material still flows
    assert SECRET not in text
    assert "Therapy Notes" not in text and PRIVATE_ID not in text  # not even as a neighbor label
    assert "zebrafinch" not in text  # private Me note stays out of the Me lane
    assert "I live in Maryland" in text  # public Me note still there
    assert "private_notes" not in r


def test_local_chat_context_includes_private_notes_and_reports_them(client, monkeypatch):
    calls = _spy(monkeypatch)
    r = _chat(client, [{"role": "user", "content": "what did the therapist say about panic attacks? zebrafinch"}], "local:qwen3:8b")
    [call] = calls
    assert call["runner"] == "_run_local"
    assert SECRET in call["kb_text"]
    assert "zebrafinch" in call["kb_text"]
    assert PRIVATE_ID in r["private_notes"] and "note:me/diagnosis" in r["private_notes"]


def test_cloud_topic_chat_on_a_private_note_does_not_hydrate_it(client, monkeypatch):
    calls = _spy(monkeypatch)
    _chat(client, [{"role": "user", "content": "summarize this"}], "claude-sonnet-5-5", folder="health", slug="therapy-notes")
    assert SECRET not in calls[0]["kb_text"]
    _chat(client, [{"role": "user", "content": "summarize this"}], "local:qwen3:8b", folder="health", slug="therapy-notes")
    assert SECRET in calls[1]["kb_text"]


def test_cloud_folder_scoped_chat_skips_private_notes(client, monkeypatch):
    calls = _spy(monkeypatch)
    _chat(client, [{"role": "user", "content": "what's in here?"}], "claude-sonnet-5-5", folder="health")
    assert SECRET not in calls[0]["kb_text"]
    _chat(client, [{"role": "user", "content": "what's in here?"}], "local:qwen3:8b", folder="health")
    assert SECRET in calls[1]["kb_text"]


def test_legacy_dump_everything_fallback_skips_private_for_cloud(client, monkeypatch):
    calls = _spy(monkeypatch)

    def down(*a, **k):
        raise RuntimeError("retrieval index not initialized")

    monkeypatch.setattr(chat, "_kb_context", down)
    _chat(client, [{"role": "user", "content": "anything?"}], "claude-sonnet-5-5")
    assert "brace before you pull" in calls[0]["kb_text"] and SECRET not in calls[0]["kb_text"]


def test_default_build_context_is_cloud_safe(client):
    # No gate passed = the cloud-safe default.
    store = kb_api.get_store()
    text, _ = chat._build_context(store, True, None, None, [{"role": "user", "content": "therapist panic attacks"}])
    assert SECRET not in text


def test_retrieval_exclude_hook_applies_before_k_and_to_neighbors(client):
    store = kb_api.get_store()
    from quintacle_core.nodes.kb.privacy import private_filter

    hits = retrieval.retrieve("deadlift", k=1, exclude=private_filter(store))
    assert [h["id"] for h in hits] == ["note:fitness/deadlift-cues"]
    assert all(n["id"] != PRIVATE_ID for n in hits[0]["neighbors"])
    unfiltered = retrieval.retrieve("deadlift therapist", k=5)
    assert PRIVATE_ID in {h["id"] for h in unfiltered}  # the owner's own /retrieve still sees it


# --- the cloud handoff strip -------------------------------------------------


def test_strip_private_turns_unit():
    msgs = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1 quoting secret", "private_notes": ["note:a/x", "note:a/y"]},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2 public", "private_notes": []},
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": "a3 secret again", "private_notes": ["note:a/x"]},
        {"role": "user", "content": "q4 now"},
    ]
    clean, n = strip_private_turns(msgs)
    assert [m["content"] for m in clean] == ["q2", "a2 public", "q4 now"]
    assert n == 2  # distinct notes
    assert all("private_notes" not in m for m in clean)
    assert strip_private_turns([{"role": "user", "content": "hi"}]) == ([{"role": "user", "content": "hi"}], 0)


def test_escalation_to_cloud_strips_private_turns_and_counts_them(client, monkeypatch):
    calls = _spy(monkeypatch, reply="cloud answer")
    history = [
        {"role": "user", "content": "what did the therapist say?"},
        {"role": "assistant", "content": f"Your note says: {SECRET}", "private_notes": [PRIVATE_ID]},
        {"role": "user", "content": "and how should I cue my deadlift?"},
    ]
    r = _chat(client, history, "claude-opus-5-5")
    sent = calls[0]["messages"]
    assert [m["content"] for m in sent] == ["and how should I cue my deadlift?"]
    assert all(SECRET not in str(m) for m in sent) and SECRET not in calls[0]["kb_text"]
    assert all("private_notes" not in m for m in sent)
    assert r["private_stripped"] == 1


def test_local_turn_keeps_history_but_never_forwards_the_marker(client, monkeypatch):
    calls = _spy(monkeypatch)
    history = [
        {"role": "user", "content": "what did the therapist say?"},
        {"role": "assistant", "content": "earlier local answer", "private_notes": [PRIVATE_ID]},
        {"role": "user", "content": "more?"},
    ]
    r = _chat(client, history, "local:qwen3:8b")
    sent = calls[0]["messages"]
    assert len(sent) == 3 and all("private_notes" not in m for m in sent)
    assert "private_stripped" not in r


def test_record_that_with_private_turns_is_pinned_local(client, monkeypatch):
    seen = {}

    def fake_fold(convo, folders, notes, provider=None):
        seen["provider"], seen["notes"] = provider, notes

        class F:
            folder, title, points = "Health", "Fold", "- point"

        return F()

    monkeypatch.setattr(kb_api, "suggest_record_fold_new", fake_fold)
    msgs = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a", "private_notes": [PRIVATE_ID]},
    ]
    assert client.post("/kb/record-that", json={"messages": msgs}).status_code == 200
    assert seen["provider"] == "local"
    assert all(n["slug"] != "therapy-notes" for n in seen["notes"])
    r = client.post("/kb/record-that", json={"messages": msgs, "provider": "cloud"})
    assert r.status_code == 400


def test_transcript_archive_keeps_private_turn_in_file_but_not_in_search(client, tmp_path):
    msgs = [
        {"role": "user", "content": "therapist question"},
        {"role": "assistant", "content": "quoting quokkaword from the note", "private_notes": [PRIVATE_ID]},
        {"role": "user", "content": "thanks"},
        {"role": "assistant", "content": "public wombatword reply"},
    ]
    body = client.post("/transcripts/archive", json={"messages": msgs, "subject": "Therapy chat"}).json()
    assert body["archived"]
    assert client.get("/transcripts/search", params={"q": "quokkaword"}).json() == []
    assert client.get("/transcripts/search", params={"q": "wombatword"}).json() != []
    post = frontmatter.load(tmp_path / "conversations" / body["path"])
    assert "quokkaword" in post.content and post["private_turns"] == 1


# --- suggesters never see private titles ---------------------------------------


def test_sort_suggesters_get_no_private_titles_and_private_target_is_local_only(client, monkeypatch):
    seen = {}

    def fake_suggest(content, folders, notes, provider=None):
        seen["notes"] = notes

        class Suggestion:
            def model_dump(self):
                return {"folder": "x", "title": "t", "content": content}

        return Suggestion()

    monkeypatch.setattr(kb_api, "suggest_kb_entry", fake_suggest)
    assert client.post("/kb/sort", content="hello", headers={"content-type": "text/plain"}).status_code == 200
    assert {n["slug"] for n in seen["notes"]} >= {"deadlift-cues"}
    assert all(n["slug"] != "therapy-notes" for n in seen["notes"])

    providers = []
    monkeypatch.setattr(kb_api, "suggest_kb_update", lambda old, new, provider=None: providers.append(provider) or "merged")
    params = {"target_folder": "health", "target_slug": "therapy-notes"}
    r = client.post("/kb/sort", params=params, content="add this", headers={"content-type": "text/plain"})
    assert r.status_code == 200 and providers == ["local"]
    r = client.post("/kb/sort", params={**params, "provider": "cloud"}, content="x", headers={"content-type": "text/plain"})
    assert r.status_code == 400


# --- "Private, skip AI": zero model calls --------------------------------------


def _boom(*a, **k):
    raise AssertionError("a model was called in skip-AI mode")


def test_private_skip_ai_drop_makes_zero_model_calls(client, monkeypatch):
    monkeypatch.setattr(llm_dispatch, "parse_structured", _boom)
    monkeypatch.setattr(llm_dispatch, "_parse_local", _boom)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _boom)
    for name in ("describe_drop", "classify_image_type", "perceive_photo", "suggest_kb_entry", "suggest_kb_placement", "parse_journal_dump"):
        monkeypatch.setattr(api_module, name, _boom)
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _boom)
    r = client.post(
        "/drop",
        data={"text": "# Dream journal\nweird dream about the ocean", "private_skip_ai": "true"},
        files={"file": ("sketch.png", io.BytesIO(b"\x89PNG fake"), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider_used"] is None
    [entry] = body["entries"]
    assert entry == {
        "type": "kb_entry",
        "folder": "",
        "title": "Dream journal",
        "content": "# Dream journal\nweird dream about the ocean",
        "links": [],
        "private": True,
    }


def test_private_manual_entry_title_fallbacks():
    assert private_manual_entry("", "scan.pdf")["title"] == "scan"
    assert private_manual_entry("x" * 100)["title"] == "x" * 60


def test_saving_a_private_drop_with_asset_writes_flag_and_skips_auto_journal(client, monkeypatch):
    monkeypatch.setattr(kb_api, "process_photo_commit", _boom)
    r = client.post(
        "/kb/entries/with-asset",
        data={"folder": "Private/Sketches", "title": "Ocean Dream", "content": "dream", "private": "true"},
        files={"files": ("sketch.png", io.BytesIO(b"\x89PNG fake"), "image/png")},
    )
    assert r.status_code == 200, r.text
    assert kb_api.get_store().is_private("private/sketches", "ocean-dream")


# --- MCP: private notes don't exist ---------------------------------------------


@pytest.fixture
def mcp(tmp_path):
    from quintacle_core.mcp_server import server as s

    s.init(tmp_path / "mcp")
    s.kb_create_entry(folder="Fitness", title="Deadlift Cues", content=PUBLIC)
    s.kb_create_entry(folder="Health", title="Therapy Notes", content=f"{SECRET} deadlift", links=["Deadlift Cues"])
    s.kb_store.set_private("health", "therapy-notes", True)
    return s


def test_mcp_kb_get_entry_on_private_is_not_found(mcp):
    with pytest.raises(ValueError, match="no such entry"):
        mcp.kb_get_entry(folder="health", slug="therapy-notes")
    assert PUBLIC in mcp.kb_get_entry(folder="fitness", slug="deadlift-cues")["content"]


def test_mcp_search_tools_never_return_private_notes(mcp):
    assert mcp.kb_search_entries("therapist") == []
    assert [h["slug"] for h in mcp.kb_search_entries("deadlift")] == ["deadlift-cues"]
    hits = mcp.search_index("deadlift therapist panic", k=10)
    assert all(h["id"] != PRIVATE_ID for h in hits)
    assert all(n["id"] != PRIVATE_ID for h in hits for n in h["neighbors"])
    assert "Therapy Notes" not in str(hits) and SECRET not in str(hits)


def test_mcp_photo_and_write_tools_treat_private_as_missing(mcp, tmp_path):
    with pytest.raises(ValueError, match="no such entry"):
        mcp.describe_photo(folder="health", slug_or_path="therapy-notes")
    with pytest.raises(ValueError, match="no such entry"):
        mcp.perceive_photo(folder="health", slug_or_path="therapy-notes")
    f = tmp_path / "doc.txt"
    f.write_text("x")
    with pytest.raises(ValueError, match="no such entry"):
        mcp.kb_attach_file(folder="health", slug="therapy-notes", local_path=str(f))
    with pytest.raises(ValueError, match="refusing to overwrite"):
        mcp.kb_create_entry(folder="Health", title="Therapy Notes", content="overwritten")
    assert SECRET in mcp.kb_store.read("health", "therapy-notes")


def test_mcp_day_recall_hides_private_day_notes(mcp):
    mcp.journal_append(for_date="2026-11-05", content="a day")
    mcp.kb_create_entry(folder="Media/Photos", title="Beach", content="beach photo", links=["2026-11-05"])
    mcp.kb_create_entry(folder="Media/Photos", title="Hidden", content="secret photo", links=["2026-11-05"])
    mcp.kb_store.set_private("media/photos", "hidden", True)
    photos = mcp.day_recall(for_date="2026-11-05")["photos"]
    slugs = {p["slug"] for p in photos}
    assert "hidden" not in slugs


# --- set/clear from Browse ---------------------------------------------------------


def test_set_private_endpoint_preserves_body_and_frontmatter(client, tmp_path):
    path = tmp_path / "kb" / "fitness" / "deadlift-cues.md"
    before = frontmatter.load(path)
    r = client.post("/kb/entry/private", json={"folder": "fitness", "slug": "deadlift-cues", "private": True})
    assert r.json() == {"folder": "fitness", "slug": "deadlift-cues", "private": True}
    after = frontmatter.load(path)
    assert after.content == before.content
    assert {k: v for k, v in after.metadata.items() if k != "private"} == before.metadata
    assert after["private"] is True and after["edited"] == before["edited"]
    assert client.get("/kb/entry", params={"folder": "fitness", "slug": "deadlift-cues"}).json()["meta"]["private"] is True

    client.post("/kb/entry/private", json={"folder": "fitness", "slug": "deadlift-cues", "private": False})
    cleared = frontmatter.load(path)
    assert cleared.content == before.content and cleared.metadata == before.metadata

    missing = client.post("/kb/entry/private", json={"folder": "fitness", "slug": "nope", "private": True})
    assert missing.status_code == 404
