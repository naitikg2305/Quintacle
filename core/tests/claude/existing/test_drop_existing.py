"""2026-11-13 (owner, T2): a dropped note that already exists is never
silently overwritten. The card offers keep both (a nearby AI name, never
"(2)") / append / replace; the match is the same name (code) or the AI's pick
(kept only if it names a real note)."""
import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core import drop_existing, llm_dispatch
from quintacle_core.nodes.kb import api as kb_api

FOLDER = "Fun/Travel/Planned/New York 2028"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    r = c.post("/kb/entries", json={"folder": FOLDER, "title": "NYC 2028 Itinerary",
                                    "content": "Day 1: Central Park.", "links": ["Travel"],
                                    "fields": {"destinations": "New York, United States"}})
    assert r.status_code == 200
    return c


def _ai(monkeypatch, **out):
    monkeypatch.setenv(drop_existing.PROVIDER_ENV, "")
    seen = {}

    def fake(system, user, fmt, *, provider=None, max_tokens=0):
        seen["provider"], seen["user"] = provider, user
        return llm_dispatch.ParseResult(fmt(**out), "local")

    monkeypatch.setattr(llm_dispatch, "parse_structured", fake)
    return seen


# ------------------------------------------------------------------ matching


def test_same_name_is_caught_by_code_with_no_model(client):
    found = drop_existing.match_existing(kb_api.get_store(), FOLDER, "nyc 2028 itinerary", "new text")
    assert found["match"]["by"] == "same_name" and found["match"]["slug"] == "nyc-2028-itinerary"
    assert "(2)" not in found["alt_title"] and found["alt_title"] != "NYC 2028 Itinerary"


def test_same_name_switches_the_card_to_the_ai_nearby_name(client, monkeypatch):
    _ai(monkeypatch, same_as=None, new_title="NYC 2028 Itinerary, revised", reason="")
    entry = {"type": "kb_entry", "folder": FOLDER, "title": "NYC 2028 Itinerary", "content": "x"}
    drop_existing.apply_to_proposal(kb_api.get_store(), entry, provider="local")
    assert entry["title"] == "NYC 2028 Itinerary, revised"
    assert entry["on_conflict"] == "new" and entry["existing_match"]["original_title"] == "NYC 2028 Itinerary"


def test_ai_nearby_name_with_a_number_or_taken_is_replaced(client, monkeypatch):
    _ai(monkeypatch, same_as=None, new_title="NYC 2028 Itinerary (2)")
    assert "(2)" not in drop_existing.match_existing(kb_api.get_store(), FOLDER, "NYC 2028 Itinerary", "x")["alt_title"]
    _ai(monkeypatch, same_as=None, new_title="nyc 2028 itinerary")
    assert drop_existing.match_existing(kb_api.get_store(), FOLDER, "NYC 2028 Itinerary", "x")["alt_title"].lower() != "nyc 2028 itinerary"


def test_ai_pick_kept_only_when_the_note_exists(client, monkeypatch):
    _ai(monkeypatch, same_as="nyc-2028-itinerary", new_title="NYC plan, Claude version", reason="same trip")
    found = drop_existing.match_existing(kb_api.get_store(), FOLDER, "New York trip plan", "x")
    assert found["match"]["by"] == "ai" and found["match"]["slug"] == "nyc-2028-itinerary"
    _ai(monkeypatch, same_as="made-up-note", new_title="whatever")
    assert drop_existing.match_existing(kb_api.get_store(), FOLDER, "New York trip plan", "x") is None


def test_ai_pick_does_not_rename_the_card(client, monkeypatch):
    _ai(monkeypatch, same_as="nyc-2028-itinerary", new_title="NYC plan, v2")
    entry = {"type": "kb_entry", "folder": FOLDER, "title": "New York trip plan", "content": "x"}
    drop_existing.apply_to_proposal(kb_api.get_store(), entry)
    assert entry["title"] == "New York trip plan" and entry["existing_match"]["by"] == "ai"


def test_empty_folder_no_match_no_model_call(client, monkeypatch):
    seen = _ai(monkeypatch, same_as=None)
    assert drop_existing.match_existing(kb_api.get_store(), "Fun/Travel/Planned/Tokyo 2029", "Tokyo", "x") is None
    assert not seen


def test_private_card_never_calls_the_model(client, monkeypatch):
    seen = _ai(monkeypatch, same_as="nyc-2028-itinerary")
    entry = {"type": "kb_entry", "folder": FOLDER, "title": "Other plan", "content": "x", "private": True}
    drop_existing.apply_to_proposal(kb_api.get_store(), entry, provider="cloud")
    assert not seen and "existing_match" not in entry


# ------------------------------------------------------------------ saving


def _note(c):
    return kb_api.get_store().read_full(FOLDER, "nyc-2028-itinerary")


def test_new_refuses_to_overwrite(client):
    r = client.post("/kb/entries", json={"folder": FOLDER, "title": "NYC 2028 Itinerary", "content": "other",
                                         "on_conflict": "new"})
    assert r.status_code == 409
    assert "Central Park" in _note(client)["content"]


def test_new_refuses_before_writing_assets(client, tmp_path):
    r = client.post("/kb/entries/with-asset",
                    data={"folder": FOLDER, "title": "NYC 2028 Itinerary", "content": "other", "on_conflict": "new"},
                    files=[("files", ("chat-draft.md", b"other", "text/markdown"))])
    assert r.status_code == 409
    assert not list(tmp_path.rglob("chat-draft*"))


def test_append_keeps_history_and_adds_a_dated_section(client):
    r = client.post("/kb/entries", json={"folder": FOLDER, "title": "ignored title", "content": "Day 2: the Met.",
                                         "links": ["Europe"], "on_conflict": "append",
                                         "target_slug": "nyc-2028-itinerary"})
    assert r.status_code == 200 and r.json()["slug"] == "nyc-2028-itinerary"
    note = _note(client)
    body = note["content"]
    assert body.count("# NYC 2028 Itinerary") == 1
    assert body.index("Central Park") < body.index("## Added") < body.index("the Met")
    links = kb_api.get_store().read_links(FOLDER, "nyc-2028-itinerary")
    assert links == ["Travel", "Europe"]
    assert note["fields"]["destinations"] == "New York, United States"
    assert kb_api.get_store().list_entries(FOLDER) == ["nyc-2028-itinerary"]


def test_append_with_asset(client):
    r = client.post("/kb/entries/with-asset",
                    data={"folder": FOLDER, "title": "x", "content": "Day 3: Bronx Zoo.", "on_conflict": "append",
                          "target_slug": "nyc-2028-itinerary"},
                    files=[("files", ("chat-draft.md", b"Day 3: Bronx Zoo.", "text/markdown"))])
    assert r.status_code == 200, r.text
    body = _note(client)["content"]
    assert "Central Park" in body and "Bronx Zoo" in body and "[asset](" in body


def test_replace_swaps_text_keeps_links_and_name(client):
    r = client.post("/kb/entries", json={"folder": FOLDER, "title": "card title", "content": "A new plan.",
                                         "links": [], "on_conflict": "replace", "target_slug": "nyc-2028-itinerary"})
    assert r.status_code == 200 and r.json()["slug"] == "nyc-2028-itinerary"
    body = _note(client)["content"]
    assert "A new plan." in body and "Central Park" not in body
    assert kb_api.get_store().read_links(FOLDER, "nyc-2028-itinerary") == ["Travel"]


def test_append_to_a_missing_note_is_404(client):
    r = client.post("/kb/entries", json={"folder": FOLDER, "title": "t", "content": "c", "on_conflict": "append",
                                         "target_slug": "nope"})
    assert r.status_code == 404


def test_no_choice_keeps_the_old_write_by_name(client):
    """Browse's edit-save sends no on_conflict and must still update in place."""
    r = client.post("/kb/entries", json={"folder": FOLDER, "title": "NYC 2028 Itinerary", "content": "edited"})
    assert r.status_code == 200
    assert "edited" in _note(client)["content"]


def test_each_note_keeps_its_own_attached_file(client):
    """Two notes in one folder, both sent from chat as chat-draft.md: each
    note's [asset] points at its own bytes (save_asset never overwrites)."""
    store = kb_api.get_store()
    paths = []
    for title, body in (("Plan A", b"local plan"), ("Plan B", b"claude plan")):
        r = client.post("/kb/entries/with-asset", data={"folder": FOLDER, "title": title, "content": body.decode(),
                                                         "on_conflict": "new"},
                        files=[("files", ("chat-draft.md", body, "text/markdown"))])
        assert r.status_code == 200, r.text
        paths.append(r.json()["assets"][0])
    assert paths[0] != paths[1], paths
    assert store.read_asset(FOLDER, paths[0]) == b"local plan"
    assert store.read_asset(FOLDER, paths[1]) == b"claude plan"


# 2026-11-13 (owner, T3): a note going into a Planned trip folder links to
# the notes already there (the same trip), decided by code.
def test_trip_folder_links_add_the_trips_notes(client):
    from quintacle_core.drop_fixups import trip_folder_links

    store = kb_api.get_store()
    assert trip_folder_links(store, FOLDER, []) == ["NYC 2028 Itinerary"]
    assert trip_folder_links(store, FOLDER, ["Travel", "nyc 2028 itinerary"]) == ["Travel", "nyc 2028 itinerary"]


def test_trip_folder_links_only_inside_a_planned_trip_folder(client):
    from quintacle_core.drop_fixups import trip_folder_links

    store = kb_api.get_store()
    assert trip_folder_links(store, "Fun/Travel/Planned", ["X"]) == ["X"]
    assert trip_folder_links(store, "Projects/Quintacle", []) == []
    assert trip_folder_links(store, "Fun/Travel/Planned/Tokyo 2029", []) == []
