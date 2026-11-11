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


@pytest.mark.xfail(
    strict=True,
    reason="GAP: a note naming a project ('Quintacle') in its body gets no edge to the project hub — "
    "graph_capture.mention_candidates only offers people + experiences, never projects/<slug>/<slug> hubs "
    "(kb/api._sync_note_graph_links -> safe_entry_graph_links).",
)
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
# Spec: Vault document. ✗ any edge, ✗ search index, ✗ graph (vault invisible).
# A passport / IRS letter / DHS notice drop is routed to document_entry and
# saved through POST /documents (entries.ts createDocument).

VAULT_DOCS = [
    pytest.param("US Passport", "passport", f"Passport renewed; {PERSON} was my emergency contact.", "passport", id="10-passport"),
    pytest.param("IRS CP575 EIN letter", "financial", f"EIN assignment for the LLC; {PERSON} is the registered agent.", "CP575", id="30-irs"),
    pytest.param("DHS I-797 approval notice", "immigration", f"H-1B approval notice, receipt WAC2612345678; filed by attorney {PERSON}.", "I-797", id="30-dhs"),
]


def _post_document(client, name, doc_type, notes):
    r = client.post(
        "/documents",
        data={"name": name, "doc_type": doc_type, "issued_date": "", "expiry_date": "", "status": "active", "notes": notes},
        files=[("files", ("scan.png", io.BytesIO(b"\x89PNG fake"), "image/png"))],
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_document_drop_lands_in_kb_document_vault_folder(env):
    """Records WHERE the document goes (fact, not a spec expectation): the
    kb/ tree, which is what makes it model-visible."""
    doc = _post_document(env.client, "US Passport", "passport", "")
    assert (env.kb_root / DOCUMENTS_FOLDER / f"{doc['slug']}.md").exists()
    assert not (env.data / "vault" / "entries").exists() or not any((env.data / "vault" / "entries").iterdir())


_DOC_GAP = (
    "GAP: Document Vault documents live INSIDE kb/ (documents/store.py _HOME='Organisation/Document Vault'; "
    "graph_capture.DOCUMENTS_FOLDER) so they are model-visible: "
)


@pytest.mark.xfail(strict=True, reason=_DOC_GAP + "documents/api.py create_document calls safe_entry_graph_links "
                   "(and graph_capture.run_graph_capture_backfill re-links via _item_description_sources).")
@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_has_no_edges(env, name, doc_type, notes, query):
    _post_document(env.client, name, doc_type, notes)
    run_graph_capture_backfill()  # the startup pass must not add any either
    assert edges_touching(document_note_id(name)) == []


@pytest.mark.xfail(strict=True, reason=_DOC_GAP + "api.py graph() emits every KBStore.graph_entries() note, "
                   "including organisation/document-vault/*.")
@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_absent_from_graph(env, name, doc_type, notes, query):
    _post_document(env.client, name, doc_type, notes)
    g = graph(env.client)
    assert not any(n["id"].startswith(f"note:{DOCUMENTS_FOLDER}/") for n in g["nodes"])


@pytest.mark.xfail(strict=True, reason=_DOC_GAP + "KBStore.search walks all of kb/ (REST /kb/search and MCP "
                   "kb_search_entries share it).")
@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_absent_from_kb_search(env, name, doc_type, notes, query):
    _post_document(env.client, name, doc_type, notes)
    hits = env.client.get("/kb/search", params={"q": query}).json()
    assert not any(h["folder"].startswith(DOCUMENTS_FOLDER) for h in hits)


@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_not_indexed_at_write_time(env, name, doc_type, notes, query):
    """POST /documents itself never calls safe_index_note — at write time
    the retrieval index stays clean (the leak is the backfill, below)."""
    _post_document(env.client, name, doc_type, notes)
    results = env.client.get("/retrieve", params={"q": query}).json()["results"]
    assert not any(DOCUMENTS_FOLDER in r["id"] for r in results)


@pytest.mark.xfail(strict=True, reason=_DOC_GAP + "retrieval_backfill.run_backfill indexes every graph_entries() "
                   "note, and retrieval.is_excluded explicitly keeps 'organisation/document-vault' indexable.")
@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_absent_from_retrieval_index_after_backfill(env, name, doc_type, notes, query):
    _post_document(env.client, name, doc_type, notes)
    run_backfill(env.data)
    assert retrieval.get_retrieval_index().get_node(document_note_id(name)) is None
    results = env.client.get("/retrieve", params={"q": query}).json()["results"]
    assert not any(DOCUMENTS_FOLDER in r["id"] for r in results)


@pytest.mark.xfail(strict=True, reason=_DOC_GAP + "mcp_server/server.py kb_search_entries -> KBStore.search walks kb/; "
                   "kb_list_folders lists organisation/document-vault.")
@pytest.mark.parametrize("name,doc_type,notes,query", VAULT_DOCS)
def test_vault_document_absent_from_mcp(env, name, doc_type, notes, query):
    from quintacle_core.mcp_server import server as mcp

    _post_document(env.client, name, doc_type, notes)
    run_backfill(env.data)
    mcp.init(env.data)
    assert not any(h["folder"].startswith(DOCUMENTS_FOLDER) for h in mcp.kb_search_entries(query))
    assert not any(DOCUMENTS_FOLDER in r["id"] for r in mcp.search_index(query))
    assert not any(f.startswith(DOCUMENTS_FOLDER) for f in mcp.kb_list_folders())


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
