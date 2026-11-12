"""Graph linking for the owner's categories #7, #8, #9, #10, #15, #23, #30, #31,
#34 (docs/testing/graph-linking-38-categories.md, DRAFT 2026-11-11).

Each test performs the SAME save the app's review -> Save step performs
(frontend/lib/entries.ts commitEntry: POST /kb/entries, /grooming/items,
/grooming/routines, /documents, /home/items, /wardrobe/items,
/wardrobe/outfits, /logs/expenses, then POST /graph/event for the batch) on a
sandboxed, preset-seeded data dir, then asserts the links the spec asks for.
No model is called anywhere: these endpoints are the post-review structured
writes, and the conftest blocks Ollama.

Expectations come from the spec, never from current behaviour. Where the
code does not do what the spec says, the assertion stays and the test is
marked xfail(strict=True) with the gap and its code location.

Vault finding (2026-11-11): there are TWO things called "vault".
- nodes/vault (secrets: passwords, API keys) lives at <data>/vault/, OUTSIDE
  kb/ -> invisible everywhere (tests below prove it).
- nodes/documents ("Document Vault": passport, IRS/DHS letters) writes into
  kb/Organisation/Document Vault/ (graph_capture.DOCUMENTS_FOLDER =
  "organisation/document-vault"), INSIDE kb/. A passport / IRS / DHS drop
  lands here (drop_router "doc:"/"document:" -> document_entry ->
  POST /documents). It is keyword-linked (documents/api.py
  safe_entry_graph_links), emitted by /graph (KBStore.graph_entries walks
  all of kb/), returned by /kb/search and MCP kb_search_entries, and indexed
  by retrieval_backfill (retrieval.is_excluded deliberately keeps
  "organisation/document-vault" indexable). Spec #10/#30 says these must be
  invisible -> those tests are xfail(strict) GAPs.

Correction 2026-11-12 (owner decision): "Documents can be visible to AI
unless deemed private (which I have an option of doing when uploading)."
The visibility above is CORRECT by default; the former xfail tests now
assert it, and a document uploaded with `private` gets the KB private flag
(never cloud/MCP, still the owner's). Only the secrets vault is invisible.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core import retrieval
from quintacle_core.graph import get_graph_store
from quintacle_core.graph_capture import (
    DOCUMENTS_FOLDER,
    document_note_id,
    grooming_item_note_id,
    home_item_note_id,
    run_graph_capture_backfill,
    wardrobe_item_note_id,
)
from quintacle_core.nodes.people.store import PersonStore
from quintacle_core.nodes.travel.store import ExperienceStore
from quintacle_core.retrieval_backfill import run_backfill

PERSON = "Laura Chen"
PERSON_ID = "note:people/laura-chen/profile"
EXPERIENCE = "Carbone"
DAY = "2026-11-10"


# --- sandbox + seed ----------------------------------------------------------


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fresh app over a sandboxed data dir, seeded with the registries
    linking keys off: one person, one experience, a project hub, a residence,
    and existing notes the new notes can `links:` to."""
    data = tmp_path / "data"
    kb_root = data / "kb"
    monkeypatch.setenv("QUINTACLE_DATA_DIR", str(data))
    monkeypatch.setattr(api_module, "DATA_DIR", data)

    PersonStore(kb_root).write(PERSON, category="friend")
    ExperienceStore(kb_root).write(EXPERIENCE, "New York", "restaurant")

    client = TestClient(api_module.create_app())

    def post_note(folder, title, content, links=None):
        r = client.post("/kb/entries", json={"folder": folder, "title": title, "content": content, "links": links or []})
        assert r.status_code == 200, r.text
        return f"note:{r.json()['folder']}/{r.json()['slug']}"

    project = post_note("Projects/Quintacle", "Quintacle", "Local-first personal life OS. repo: github.com/x/Quintacle")
    r = client.post("/home/residences", json={"name": "Iris 307", "city": "Washington DC", "address": "", "notes": ""})
    assert r.status_code == 200, r.text
    residence = r.json()

    class Env:
        pass

    e = Env()
    e.client, e.data, e.kb_root = client, data, kb_root
    e.post_note, e.project_id, e.residence = post_note, project, residence
    return e


def edges_touching(node_id: str) -> list[dict]:
    conn = get_graph_store().conn
    return [dict(r) for r in conn.execute("SELECT * FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id))]


def has_edge(a: str, b: str, kind: str | None = None) -> bool:
    """An edge between a and b in either direction (optionally of `kind`)."""
    for e in edges_touching(a):
        if {e["source_id"], e["target_id"]} == {a, b} and (kind is None or e["kind"] == kind):
            return True
    return False


def graph(client) -> dict:
    r = client.get("/graph")
    assert r.status_code == 200, r.text
    return r.json()


def graph_has_edge(g: dict, a: str, b: str, kind: str | None = None) -> bool:
    return any({e["source"], e["target"]} == {a, b} and (kind is None or e["kind"] == kind) for e in g["edges"])


# --- #7 Laptop setup, #8 Phone setup and apps, #15 AI setup ------------------
# Spec: Note (setup) -> projects named; `links:` -> related.

SETUP_NOTES = [
    pytest.param(
        "Technology/Laptop Setup", "Arch laptop setup",
        "Installed Arch on the ThinkPad. Cloned Quintacle and set up the venv; Ollama runs as a user service.",
        id="7-laptop-setup",
    ),
    pytest.param(
        "Technology/Phone Setup", "Pixel phone setup and apps",
        "Termux installed for running the Quintacle backend on the phone; apps: Obsidian, Signal, Tailscale.",
        id="8-phone-setup",
    ),
    pytest.param(
        "Technology/AI Setup", "Local AI setup",
        "qwen3:8b and qwen2.5vl:3b pulled in Ollama; Claude Code with the Quintacle MCP registered user-scope.",
        id="15-ai-setup",
    ),
]


@pytest.mark.parametrize("folder,title,content", SETUP_NOTES)
def test_setup_note_links_frontmatter_related(env, folder, title, content):
    """`links:` frontmatter on a setup note becomes a `related` edge."""
    other = env.post_note("Technology", "Dotfiles", "My dotfiles repo and how to bootstrap them.")
    note = env.post_note(folder, title, content, links=["Dotfiles"])
    assert has_edge(note, other, "related")
    assert graph_has_edge(graph(env.client), note, other, "related")


@pytest.mark.parametrize("folder,title,content", SETUP_NOTES)
def test_setup_note_links_named_project(env, folder, title, content):
    note = env.post_note(folder, title, content)
    assert has_edge(note, env.project_id)


# --- #9 Grooming plans ---------------------------------------------------------
# Spec: Grooming items + routine note. Item notes -> people named; the routine
# references its items by name, not copies.


def _post_grooming_item(client, name, category, description):
    r = client.post("/grooming/items", data={"name": name, "category": category, "description": description})
    assert r.status_code == 200, r.text
    return r.json()


def test_grooming_item_links_person_named(env):
    item = _post_grooming_item(env.client, "CeraVe Foaming Cleanser", "skincare", f"{PERSON} recommended this for oily skin.")
    note_id = grooming_item_note_id(item["name"])
    assert has_edge(note_id, PERSON_ID, "mentions_person")
    assert graph_has_edge(graph(env.client), note_id, PERSON_ID, "mentions_person")


def test_grooming_item_without_person_has_no_person_edge(env):
    item = _post_grooming_item(env.client, "Nivea Lip Balm", "skincare", "Night only.")
    assert not any(e["kind"] == "mentions_person" for e in edges_touching(grooming_item_note_id(item["name"])))


def test_grooming_routine_references_items_by_name_not_copies(env):
    _post_grooming_item(env.client, "CeraVe Foaming Cleanser", "skincare", "Long description that must not be copied into the routine.")
    _post_grooming_item(env.client, "Vanicream Moisturizer", "skincare", "Fragrance free.")
    r = env.client.post("/grooming/routines", json={"name": "PM routine", "steps": ["cerave foaming cleanser", "Vanicream Moisturizer"]})
    assert r.status_code == 200, r.text
    # Names canonicalize to the existing items — no near-duplicate items.
    assert r.json()["steps"] == ["CeraVe Foaming Cleanser", "Vanicream Moisturizer"]
    items = env.client.get("/grooming/items").json()
    assert sorted(i["name"] for i in items) == ["CeraVe Foaming Cleanser", "Vanicream Moisturizer"]
    # The routine file carries the names only, never the item text.
    routine_file = next((env.kb_root / "personal-development/physical/grooming/routines").glob("*.md"))
    text = routine_file.read_text(encoding="utf-8")
    assert "CeraVe Foaming Cleanser" in text
    assert "must not be copied" not in text


def test_grooming_routine_items_reachable_in_graph(env):
    item = _post_grooming_item(env.client, "CeraVe Foaming Cleanser", "skincare", "")
    env.client.post("/grooming/routines", json={"name": "PM routine", "steps": [item["name"]]})
    g = graph(env.client)
    item_ids = {grooming_item_note_id(item["name"])}
    assert any(e["kind"] == "includes" and e["target"] in item_ids for e in g["edges"])


# --- #23 House plan and catalog -----------------------------------------------
# Spec: Residence + home items. Items -> their residence (folder nesting);
# -> people named.


def _post_home_item(client, name, notes, residence_name=""):
    r = client.post("/home/items", data={"name": name, "residence_name": residence_name, "category": "furniture", "notes": notes})
    assert r.status_code == 200, r.text
    return r.json()


def test_home_item_nests_under_its_residence(env):
    item = _post_home_item(env.client, "Standing desk", "Bought for the office corner.")
    res_folder = env.residence["folder"]
    assert item["residence"] == "Iris 307"
    assert (env.kb_root / res_folder / "items" / f"{item['slug']}.md").exists()
    # Its graph identity sits inside the residence's folder too.
    note_id = home_item_note_id(res_folder, item["slug"])
    g = graph(env.client)
    node = next(n for n in g["nodes"] if n["id"] == note_id)
    assert node["folder"].startswith(res_folder + "/")


def test_home_item_links_person_named(env):
    item = _post_home_item(env.client, "Walnut bookshelf", f"{PERSON} helped me carry it up three floors.")
    note_id = home_item_note_id(env.residence["folder"], item["slug"])
    assert has_edge(note_id, PERSON_ID, "mentions_person")
    assert graph_has_edge(graph(env.client), note_id, PERSON_ID, "mentions_person")


# --- #31 CX-5 things -----------------------------------------------------------
# Spec: Notes under Organisation/Car + expenses. Car notes -> each other via
# `links:`; repair expenses `part_of` their event.


def test_car_notes_link_each_other(env):
    pricing = env.post_note("Organisation/Car", "CX-5 pricing", "2021 CX-5 Touring trade-in KBB range $19k-21k.")
    fixing = env.post_note(
        "Organisation/Car", "CX-5 maintenance", "Brake pads replaced at 42k miles. See pricing.", links=["CX-5 pricing"]
    )
    assert has_edge(fixing, pricing, "related")
    assert graph_has_edge(graph(env.client), fixing, pricing, "related")


def test_car_repair_expense_part_of_its_event(env):
    """One drop 'CX-5 brake pads at Firestone $320' -> a car note + an expense;
    the batch Save links both to one event (entries.ts linkBatchAsEvent)."""
    note = env.post_note("Organisation/Car", "CX-5 brake job", "Front brake pads + rotors at Firestone, 42,180 miles.")
    r = env.client.post("/logs/expenses", json={"date": DAY, "amount": 320.0, "merchant": "Firestone", "category": "car", "notes": "CX-5 brakes"})
    assert r.status_code == 200, r.text
    expense = f"expense:{r.json()['id']}"
    ev = env.client.post("/graph/event", json={"members": [note, expense], "date": DAY}).json()
    assert ev["event_id"]
    assert has_edge(expense, ev["event_id"], "part_of")
    assert has_edge(note, ev["event_id"], "part_of")
    g = graph(env.client)
    assert graph_has_edge(g, expense, ev["event_id"], "part_of")
    # Numeric logs are never keyword-linked (spec "How linking works").
    assert [e["kind"] for e in edges_touching(expense)] == ["part_of"]


# --- #34 Outfit drop -------------------------------------------------------------
# Spec: Wardrobe items / outfit. Item notes -> people/experiences named in the
# description.


def _post_wardrobe_item(client, name, description, category="top"):
    r = client.post("/wardrobe/items", data={"name": name, "category": category, "description": description})
    assert r.status_code == 200, r.text
    return r.json()


def test_wardrobe_item_links_person_and_experience_named(env):
    item = _post_wardrobe_item(env.client, "Navy Blazer", f"{PERSON} picked it out; wore it to dinner at {EXPERIENCE}.")
    note_id = wardrobe_item_note_id(item["name"])
    exp_id = next(n["id"] for n in graph(env.client)["nodes"] if n["type"] == "experience" and n["label"] == EXPERIENCE)
    assert has_edge(note_id, PERSON_ID, "mentions_person")
    assert has_edge(note_id, exp_id, "at_location")


def test_outfit_items_saved_once_and_included(env):
    _post_wardrobe_item(env.client, "Navy Blazer", "")
    r = env.client.post("/wardrobe/outfits", data={"name": "Dinner look", "items": '["navy blazer", "White Oxford Shirt"]'})
    assert r.status_code == 200, r.text
    assert r.json()["items"][0] == "Navy Blazer"  # canonicalized to the existing item, not a copy
    g = graph(env.client)
    # One node per item: the outfit includes the item's own KB-note id (2026-11-11).
    assert graph_has_edge(g, "outfit:Dinner look", wardrobe_item_note_id("Navy Blazer"), "includes")


def test_outfit_reaches_person_named_by_its_item(env):
    _post_wardrobe_item(env.client, "Navy Blazer", f"{PERSON} picked it out.")
    env.client.post("/wardrobe/outfits", data={"name": "Dinner look", "items": '["Navy Blazer"]'})
    g = graph(env.client)
    adj: dict[str, set[str]] = {}
    for e in g["edges"]:
        adj.setdefault(e["source"], set()).add(e["target"])
        adj.setdefault(e["target"], set()).add(e["source"])
    two_hops = {m for n in adj.get("outfit:Dinner look", set()) for m in adj.get(n, set())}
    assert PERSON_ID in two_hops


# --- #10 Document drop, #30 Docs on IRS, DHS ----------------------------------
# Spec (DRAFT 2026-11-11) said: Vault document. ✗ any edge, ✗ search index,
# ✗ graph (vault invisible). CORRECTED by owner decision 2026-11-12:
# "Documents can be visible to AI unless deemed private (which I have an
# option of doing when uploading)." So a Document Vault document is
# model-visible by default — keyword-linked, in /graph, /kb/search, the
# retrieval index and MCP — and a document uploaded with `private` checked
# carries the KB `private: true` flag (nodes/kb/privacy.py): never reaches a
# cloud model or MCP, still shown to the owner. The SECRETS vault
# (nodes/vault) stays invisible everywhere (test further down).
# A passport / IRS letter / DHS notice drop is routed to document_entry and
# saved through POST /documents (entries.ts createDocument).

VAULT_DOCS = [
    pytest.param("US Passport", "passport", f"Passport renewed; {PERSON} was my emergency contact.", "passport", id="10-passport"),
    pytest.param("IRS CP575 EIN letter", "financial", f"EIN assignment for the LLC; {PERSON} is the registered agent.", "CP575", id="30-irs"),
    pytest.param("DHS I-797 approval notice", "immigration", f"H-1B approval notice, receipt WAC2612345678; filed by attorney {PERSON}.", "I-797", id="30-dhs"),
]


# Retrieval-index queries come from the notes BODY: the index entry a
# document gets from the backfill is titled by its first body line, not by
# its `name` frontmatter (a document stores its name as `name:`, not
# `title:`) — so "CP575"/"I-797", which only appear in the name, are found
# by /kb/search and kb_search_entries (filename match) but not by /retrieve.
# Recorded fact, 2026-11-12.
BODY_QUERY = {"US Passport": "passport", "IRS CP575 EIN letter": "EIN", "DHS I-797 approval notice": "WAC2612345678"}


def _post_document(client, name, doc_type, notes, private=None):
    data = {"name": name, "doc_type": doc_type, "issued_date": "", "expiry_date": "", "status": "active", "notes": notes}
    if private is not None:
        data["private"] = "true" if private else "false"
    r = client.post("/documents", data=data, files=[("files", ("scan.png", io.BytesIO(b"\x89PNG fake"), "image/png"))])
    assert r.status_code == 200, r.text
    return r.json()


def test_document_drop_lands_in_kb_document_vault_folder(env):
    """Records WHERE the document goes (fact, not a spec expectation): the
    kb/ tree, which is what makes it model-visible."""
    doc = _post_document(env.client, "US Passport", "passport", "")
    assert (env.kb_root / DOCUMENTS_FOLDER / f"{doc['slug']}.md").exists()
    assert not (env.data / "vault" / "entries").exists() or not any((env.data / "vault" / "entries").iterdir())


@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_is_keyword_linked_to_the_person_it_names(env, name, doc_type, notes, query):
    """2026-11-12: visible by default -> linked like any note, and the
    startup backfill keeps (does not duplicate or drop) the link."""
    _post_document(env.client, name, doc_type, notes)
    run_graph_capture_backfill()
    assert has_edge(document_note_id(name), PERSON_ID, "mentions_person")


@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_present_in_graph(env, name, doc_type, notes, query):
    _post_document(env.client, name, doc_type, notes)
    g = graph(env.client)
    assert any(n["id"] == document_note_id(name) for n in g["nodes"])
    assert graph_has_edge(g, document_note_id(name), PERSON_ID)


@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_present_in_kb_search(env, name, doc_type, notes, query):
    _post_document(env.client, name, doc_type, notes)
    hits = env.client.get("/kb/search", params={"q": query}).json()
    assert any(h["folder"].startswith(DOCUMENTS_FOLDER) for h in hits)


@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_not_indexed_at_write_time(env, name, doc_type, notes, query):
    """Fact, unchanged by the 2026-11-12 decision: POST /documents itself
    never calls safe_index_note, so a new document reaches the retrieval
    index at the next backfill (startup), not at write time."""
    _post_document(env.client, name, doc_type, notes)
    results = env.client.get("/retrieve", params={"q": query}).json()["results"]
    assert not any(DOCUMENTS_FOLDER in r["id"] for r in results)


@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_present_in_retrieval_index_after_backfill(env, name, doc_type, notes, query):
    _post_document(env.client, name, doc_type, notes)
    run_backfill(env.data)
    assert retrieval.get_retrieval_index().get_node(document_note_id(name)) is not None
    results = env.client.get("/retrieve", params={"q": BODY_QUERY[name]}).json()["results"]
    assert any(r["id"] == document_note_id(name) for r in results)


@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_present_in_mcp(env, name, doc_type, notes, query):
    from quintacle_core.mcp_server import server as mcp

    _post_document(env.client, name, doc_type, notes)
    run_backfill(env.data)
    mcp.init(env.data)
    assert any(h["folder"].startswith(DOCUMENTS_FOLDER) for h in mcp.kb_search_entries(query))
    assert any(r["id"] == document_note_id(name) for r in mcp.search_index(BODY_QUERY[name]))
    assert any(f.startswith(DOCUMENTS_FOLDER) for f in mcp.kb_list_folders())


# --- the upload-time "Private (no cloud AI)" option (2026-11-12) -------------

PRIVATE_DOC = ("Therapist intake form", "medical", f"Intake for panic attacks; emergency contact {PERSON}. zebrafinch-7731")


def test_private_flag_is_written_to_the_document_frontmatter(env):
    name, doc_type, notes = PRIVATE_DOC
    out = _post_document(env.client, name, doc_type, notes, private=True)
    assert out["private"] is True
    text = (env.kb_root / DOCUMENTS_FOLDER / f"{out['slug']}.md").read_text()
    assert "private: true" in text
    public = _post_document(env.client, "US Passport", "passport", "")
    assert public["private"] is False
    assert "private" not in (env.kb_root / DOCUMENTS_FOLDER / f"{public['slug']}.md").read_text()


def test_private_document_never_reaches_mcp(env):
    from quintacle_core.mcp_server import server as mcp

    name, doc_type, notes = PRIVATE_DOC
    out = _post_document(env.client, name, doc_type, notes, private=True)
    _post_document(env.client, "US Passport", "passport", f"Passport renewed; {PERSON} was my emergency contact.")
    run_backfill(env.data)
    mcp.init(env.data)
    assert mcp.kb_search_entries("zebrafinch") == []
    assert not any(h["slug"] == out["slug"] for h in mcp.kb_search_entries("intake"))
    hits = mcp.search_index("therapist intake panic zebrafinch", k=20)
    assert all(h["id"] != document_note_id(name) for h in hits)
    assert all(n["id"] != document_note_id(name) for h in hits for n in h.get("neighbors", []))
    assert "zebrafinch" not in str(hits)
    with pytest.raises(ValueError, match="no such entry"):
        mcp.kb_get_entry(folder=DOCUMENTS_FOLDER, slug=out["slug"])
    # an unmarked document still flows to MCP
    assert any(h["slug"] == "us-passport" for h in mcp.kb_search_entries("passport"))


def _spy_chat(monkeypatch) -> list[dict]:
    from quintacle_core.nodes.kb import chat

    calls: list[dict] = []

    def make(runner_name):
        def runner(model, messages, kb_text):
            calls.append({"runner": runner_name, "kb_text": kb_text or ""})
            return "stub-reply"

        return runner

    for runner_name in ("_run_anthropic", "_run_openai", "_run_bedrock", "_run_local"):
        monkeypatch.setattr(chat, runner_name, make(runner_name))
    return calls


def test_private_document_stays_out_of_cloud_chat_but_local_chat_may_use_it(env, monkeypatch):
    name, doc_type, notes = PRIVATE_DOC
    _post_document(env.client, name, doc_type, notes, private=True)
    _post_document(env.client, "US Passport", "passport", "Passport renewed in 2026; zebrafinch-free.")
    run_backfill(env.data)
    calls = _spy_chat(monkeypatch)
    question = [{"role": "user", "content": "what does my therapist intake form say? zebrafinch passport"}]

    r = env.client.post("/kb/chat", json={"messages": question, "model": "claude-sonnet-5-5"})
    assert r.status_code == 200, r.text
    cloud_text = calls[-1]["kb_text"]
    assert "zebrafinch-7731" not in cloud_text and "Therapist intake form" not in cloud_text
    assert "Passport renewed" in cloud_text  # public documents still flow to cloud

    r = env.client.post("/kb/chat", json={"messages": question, "model": "local:qwen3:8b"})
    assert r.status_code == 200, r.text
    assert calls[-1]["runner"] == "_run_local" and "zebrafinch-7731" in calls[-1]["kb_text"]
    assert document_note_id(name) in r.json()["private_notes"]


def test_private_document_still_shown_to_the_owner(env):
    """The owner always sees it: the Documents list (flagged), Browse search,
    and his own graph view."""
    name, doc_type, notes = PRIVATE_DOC
    out = _post_document(env.client, name, doc_type, notes, private=True)
    [doc] = [d for d in env.client.get("/documents").json() if d["slug"] == out["slug"]]
    assert doc["private"] is True and doc["notes"] == notes
    assert any(h["slug"] == out["slug"] for h in env.client.get("/kb/search", params={"q": "zebrafinch"}).json())
    assert any(n["id"] == document_note_id(name) for n in graph(env.client)["nodes"])


# The SECRETS vault (nodes/vault) — the thing CLAUDE.md's invisibility rule
# was written for. Must be invisible on every surface; stored outside kb/.


def test_secrets_vault_entry_invisible_everywhere(env):
    from quintacle_core.mcp_server import server as mcp

    c = env.client
    assert c.post("/vault/init", json={"passphrase": "correct horse"}).status_code == 200
    r = c.put("/vault/entries/irs-ip-pin", json={"name": "IRS IP PIN", "username": "ssa-login", "secret": "ZETA-449120",
                                                 "url": "https://irs.gov", "notes": f"{PERSON} has the backup copy"})
    assert r.status_code == 200, r.text
    run_graph_capture_backfill()
    run_backfill(env.data)

    assert (env.data / "vault").is_dir() and not (env.kb_root / "vault").exists()
    blob = " ".join(p.read_text(errors="ignore") for p in env.kb_root.rglob("*.md"))
    assert "ZETA-449120" not in blob and "IRS IP PIN" not in blob
    conn = get_graph_store().conn
    assert conn.execute("SELECT COUNT(*) FROM edges WHERE source_id LIKE '%vault%' OR target_id LIKE '%irs-ip-pin%'").fetchone()[0] == 0
    g = graph(c)
    assert not any("irs-ip-pin" in n["id"] or n["label"] == "IRS IP PIN" for n in g["nodes"])
    for q in ("ZETA-449120", "IRS IP PIN"):
        assert c.get("/kb/search", params={"q": q}).json() == []
        assert c.get("/retrieve", params={"q": q}).json()["results"] == []
    mcp.init(env.data)
    assert mcp.kb_search_entries("ZETA-449120") == []
    assert mcp.search_index("IRS IP PIN") == []
