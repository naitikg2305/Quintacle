"""DRAFT 2026-11-11 — expectations written by Claude from docs/testing/graph-linking-38-categories.md; NOT confirmed by the owner.

LIVE: real local models via Ollama (tests.claude.harness.make_client, cloud
blocked), sandboxed data dir (never ~/.quintacle), registries seeded first.
Each test types/drops what the owner would, runs POST /drop, then performs
the SAME Save the review card performs (a Python mirror of
frontend/lib/entries.ts commitEntry + linkBatchAsEvent), then checks filing
and graph links. Vault categories also check invisibility.

Categories: #7 Laptop setup, #8 Phone setup and apps, #9 Grooming plans,
#10 Document drop, #15 AI setup, #23 House plan and catalog, #30 Docs on
IRS/DHS, #31 CX-5 things, #34 Outfit drop.

Known before running (see core/tests/claude/existing/test_graph_categories_items_vault.py):
the "project named" links (#7/#8/#15) and every Document Vault invisibility
check (#10/#30) are code gaps today and are expected to fail until fixed.

Run (owner, after confirming): QUINTACLE_USER_DRAFTS=1 .venv/bin/python -m pytest -q tests/user/test_draft_items_vault.py
"""
from __future__ import annotations

import json
import os
import re

import pytest

from quintacle_core.graph_capture import wardrobe_item_note_id

from tests.claude.harness import drop, first, make_client, make_pdf, missing_requirements, types

pytestmark = pytest.mark.skipif(os.environ.get("QUINTACLE_USER_DRAFTS") != "1", reason="draft: owner hasn't confirmed")

PROVIDER = "local"
DAY = "2026-11-11"
PERSON = "Laura Chen"
PERSON_ID = "note:people/laura-chen/profile"
EXPERIENCE = "Carbone"
DOC_FOLDER = "organisation/document-vault"


# --- client + seed -----------------------------------------------------------


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    reason = missing_requirements()
    if reason:
        pytest.skip(reason)
    c = make_client(tmp_path_factory.mktemp("user-draft-items-vault"))
    _seed(c)
    return c


def _ok(r):
    assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
    return r.json()


def _seed(c):
    """Registries first (CLAUDE.md: model-quality tests run on seeded data)."""
    _ok(c.post("/people", json={"name": PERSON, "category": "friend", "how_met": "college"}))
    _ok(c.post("/travel/experiences", json={"name": EXPERIENCE, "city": "New York", "kind": "restaurant", "visited_date": "2026-10-02"}))
    _ok(c.post("/home/residences", json={"name": "Iris 307", "city": "Arlington", "moved_in": "2024-08-01"}))
    for name, cat, desc in [("Uniqlo Navy Chinos", "pants", "Navy slim-fit chinos."), ("White Oxford Shirt", "shirt", "White button-down oxford.")]:
        _ok(c.post("/wardrobe/items", data={"name": name, "category": cat, "description": desc}))
    _ok(c.post("/grooming/items", data={"name": "CeraVe Foaming Cleanser", "category": "skincare", "description": "Foaming cleanser."}))
    for folder, title, content in [
        ("Projects/Quintacle", "Quintacle", "Local-first personal life OS (FastAPI + Next.js). repo: github.com/naitikg2305/Quintacle"),
        ("Technology", "Dotfiles", "My dotfiles repo: zsh, nvim, kitty configs, bootstrap script."),
        ("Organisation/Car", "CX-5 pricing", "2021 Mazda CX-5 Touring. KBB trade-in range $19k-21k as of Oct 2026."),
    ]:
        _ok(c.post("/kb/entries", json={"folder": folder, "title": title, "content": content}))


# --- the Save step (mirror of frontend/lib/entries.ts) ---------------------------


def _commit(c, e: dict) -> str | None:
    """commitEntry + graphIdFor for the entry types these categories produce.
    Returns the graph id the frontend would put in the event batch."""
    t = e["type"]
    if t == "kb_entry":
        body = {k: e.get(k) for k in ("folder", "title", "content", "links")}
        if e.get("fields"):
            body["fields"] = e["fields"]
        r = _ok(c.post("/kb/entries", json=body))
        return f"note:{r['folder']}/{r['slug']}"
    if t == "finance":
        r = _ok(c.post("/logs/expenses", json={
            "date": e.get("entry_date") or DAY, "amount": e["amount"], "merchant": e.get("merchant") or "",
            "category": e.get("category") or "", "notes": e.get("notes") or "", "kind": e.get("kind") or "regular",
        }))
        return f"expense:{r['id']}"
    if t == "wardrobe_item":
        r = _ok(c.post("/wardrobe/items", data={"name": e["suggested_name"], "category": e["category"], "description": e.get("description") or ""}))
        return r.get("graph_id") or wardrobe_item_note_id(r["name"])
    if t == "outfit_composition":
        for it in e["items"]:
            if it.get("is_new"):
                _ok(c.post("/wardrobe/items", data={"name": it["name"], "category": it.get("category") or "", "description": it.get("description") or ""}))
        r = _ok(c.post("/wardrobe/outfits", data={"name": e["outfit_name"], "items": json.dumps([it["name"] for it in e["items"]])}))
        return f"outfit:{r['name']}"
    if t == "grooming_item":
        _ok(c.post("/grooming/items", data={"name": e["suggested_name"], "category": e["category"], "description": e.get("description") or ""}))
        return None
    if t == "grooming_routine_composition":
        for s in e["steps"]:
            if s.get("is_new"):
                _ok(c.post("/grooming/items", data={"name": s["name"], "category": s.get("category") or "", "description": s.get("description") or ""}))
        _ok(c.post("/grooming/routines", json={"name": e["routine_name"], "steps": [s["name"] for s in e["steps"]]}))
        return None
    if t == "document_entry":
        _ok(c.post("/documents", data={
            "name": e["suggested_name"], "doc_type": e.get("doc_type") or "", "issued_date": e.get("issued_date") or "",
            "expiry_date": e.get("expiry_date") or "", "status": "active", "notes": e.get("notes") or "",
        }))
        return None
    if t == "home_item":
        form = {"name": e["suggested_name"], "residence_name": e.get("residence_name") or "", "category": e.get("category") or "",
                "location": e.get("location") or "", "purchase_date": e.get("purchase_date") or "", "notes": e.get("notes") or ""}
        if e.get("purchase_price") is not None:
            form["purchase_price"] = str(e["purchase_price"])
        _ok(c.post("/home/items", data=form))
        return None
    if t == "experience_entry":
        r = _ok(c.post("/travel/experiences", json={k: e.get(k) for k in ("city", "kind", "rating", "would_return", "visited_date", "notes", "links")} | {"name": e["suggested_name"]}))
        return f"experience:{r['folder']}/{r['slug']}"
    if t == "person_entry":
        r = _ok(c.post("/people", json={"name": e["suggested_name"], "category": e.get("category") or "", "how_met": e.get("how_met") or "", "notes": e.get("notes") or ""}))
        return f"note:{r['folder']}/profile"
    raise AssertionError(f"draft Save mirror has no branch for {t}: {json.dumps(e)[:300]}")


def save(c, result: dict) -> list[str | None]:
    """Save every proposed entry, then link the batch as one event (>= 2 ids)."""
    ids = [_commit(c, e) for e in result["entries"]]
    real = [i for i in ids if i]
    if len(real) >= 2:
        _ok(c.post("/graph/event", json={"members": real, "date": DAY}))
    return ids


def edges(c) -> list[dict]:
    return _ok(c.get("/graph"))["edges"]


def linked(c, a: str, b: str, kind: str | None = None) -> bool:
    return any({e["source"], e["target"]} == {a, b} and (kind is None or e["kind"] == kind) for e in edges(c))


def touching(c, node_id: str) -> list[dict]:
    return [e for e in edges(c) if node_id in (e["source"], e["target"])]


# --- #7 / #8 / #15 setup notes ------------------------------------------------------

SETUP_DROPS = [
    pytest.param(
        "note: Laptop setup. Arch on the ThinkPad X1. Cloned Quintacle into ~/code, made core/.venv, "
        "Ollama runs as a systemd user service. Bootstrapped zsh/nvim from my Dotfiles.", id="7-laptop",
    ),
    pytest.param(
        "note: Phone setup and apps. Pixel 8: Termux runs the Quintacle backend, Tailscale to reach the laptop, "
        "Obsidian, Signal, Google Authenticator. Same shell config as my Dotfiles.", id="8-phone",
    ),
    pytest.param(
        "note: AI setup. Ollama with qwen3:8b for parsing and qwen2.5vl:3b for photos; Claude Code with the "
        "Quintacle MCP registered user-scope. Prompts and aliases live in my Dotfiles.", id="15-ai",
    ),
]


@pytest.mark.parametrize("text", SETUP_DROPS)
def test_setup_note_files_and_links(client, text):
    """A setup note is ONE note (no person/experience invented), filed in a
    technology/setup-style folder (not People, not Projects/Quintacle itself),
    and after Save it links to the Quintacle project hub it names and to the
    Dotfiles note it references (`related`)."""
    r = drop(client, text=text, provider=PROVIDER)
    assert types(r).count("kb_entry") == 1 and "person_entry" not in types(r) and "experience_entry" not in types(r), types(r)
    folder = (first(r, "kb_entry").get("folder") or "").lower()
    assert folder and not folder.startswith("people") and folder.strip("/") != "projects/quintacle", folder
    note = save(client, r)[0]
    assert linked(client, note, "note:projects/quintacle/quintacle"), "no edge to the Quintacle project hub"
    assert linked(client, note, "note:technology/dotfiles", "related"), "no related edge to Dotfiles"


# --- #9 Grooming plans -----------------------------------------------------------


def test_grooming_product_links_person(client):
    """'product:' with a person named -> one grooming item, and its item note
    links to Laura Chen (mentions_person)."""
    r = drop(client, text=f"product: Vanicream daily moisturizer, {PERSON} recommended it, use every night", provider=PROVIDER)
    e = first(r, "grooming_item")
    assert "vanicream" in e["suggested_name"].lower(), e
    save(client, r)
    slug = re.sub(r"[^a-z0-9]+", "-", e["suggested_name"].lower()).strip("-")
    assert linked(client, f"note:personal-development/physical/grooming/items/{slug}", PERSON_ID, "mentions_person")


def test_grooming_routine_references_items_by_name(client):
    """'grooming:' PM routine -> the routine's steps are the EXISTING items by
    name (seeded CeraVe Foaming Cleanser reused, not duplicated); the routine
    holds names only."""
    r = drop(client, text="grooming: PM routine - CeraVe foaming cleanser, then Vanicream moisturizer", provider=PROVIDER)
    e = first(r, "grooming_routine_composition")
    save(client, r)
    routines = _ok(client.get("/grooming/routines"))
    routine = next(x for x in routines if x["name"] == e["routine_name"])
    assert "CeraVe Foaming Cleanser" in routine["steps"], routine
    names = [i["name"] for i in _ok(client.get("/grooming/items"))]
    assert sum("cerave" in n.lower() and "foaming" in n.lower() for n in names) == 1, names


# --- #23 House plan and catalog ------------------------------------------------------


def test_home_item_nests_under_residence_and_links_person(client):
    """'home:' item, no residence named -> filed under the current residence
    (Iris 307) folder, and the person in its notes gets a mentions_person edge."""
    r = drop(client, text=f"home: walnut bookshelf in the living room, {PERSON} helped me carry it up, paid $180", provider=PROVIDER)
    e = first(r, "home_item")
    assert e.get("residence_name") == "Iris 307", e
    save(client, r)
    items = _ok(client.get("/home/items", params={"residence_name": "Iris 307"}))
    item = next(i for i in items if "bookshelf" in i["name"].lower())
    note_id = f"note:organisation/home/arlington/iris-307/items/{item['slug']}"
    assert linked(client, note_id, PERSON_ID, "mentions_person")


# --- #31 CX-5 things --------------------------------------------------------------


def test_cx5_repair_drop_expense_and_car_note_one_event(client):
    """An unprefixed repair line -> an expense ($320, Firestone) AND a car note
    under Organisation/Car; the car note links CX-5 pricing; both saved records
    are part_of the same event."""
    r = drop(client, text="CX-5 brake pads and rotors replaced at Firestone today, $320, 42,180 miles. See CX-5 pricing.", provider=PROVIDER)
    assert "finance" in types(r) and "kb_entry" in types(r), types(r)
    assert first(r, "finance")["amount"] == 320, first(r, "finance")
    assert (first(r, "kb_entry").get("folder") or "").lower().startswith("organisation/car"), first(r, "kb_entry")
    ids = save(client, r)
    expense = next(i for i in ids if i and i.startswith("expense:"))
    note = next(i for i in ids if i and i.startswith("note:"))
    ev_exp = {e["target"] for e in touching(client, expense) if e["kind"] == "part_of"}
    ev_note = {e["target"] for e in touching(client, note) if e["kind"] == "part_of"}
    assert ev_exp and ev_exp == ev_note
    assert linked(client, note, "note:organisation/car/cx-5-pricing", "related")


# --- #34 Outfit drop ----------------------------------------------------------------


def test_wardrobe_item_links_person_and_experience(client):
    """'wardrobe:' item whose description names Laura Chen and Carbone -> its
    item note links to both (mentions_person, at_location)."""
    r = drop(client, text=f"wardrobe: navy wool blazer {PERSON} picked out, wore it to dinner at {EXPERIENCE}", provider=PROVIDER)
    e = first(r, "wardrobe_item")
    save(client, r)
    slug = re.sub(r"[^a-z0-9]+", "-", e["suggested_name"].lower()).strip("-")
    note_id = f"note:personal-development/physical/style-dressing/items/{slug}"
    assert linked(client, note_id, PERSON_ID, "mentions_person")
    assert any(x["kind"] == "at_location" and x["target"].startswith("experience:") for x in touching(client, note_id))


def test_outfit_reuses_items(client):
    """'outfit:' naming items I own -> the outfit includes the seeded items by
    their exact names (no duplicate Oxford/chinos)."""
    r = drop(client, text="outfit: Carbone dinner look - navy wool blazer, white oxford shirt, uniqlo navy chinos", provider=PROVIDER)
    e = first(r, "outfit_composition")
    names = {it["name"] for it in e["items"]}
    assert {"White Oxford Shirt", "Uniqlo Navy Chinos"} <= names, e
    save(client, r)
    outfit = f"outfit:{e['outfit_name']}"
    assert linked(client, outfit, wardrobe_item_note_id("White Oxford Shirt"), "includes")
    assert linked(client, outfit, wardrobe_item_note_id("Uniqlo Navy Chinos"), "includes")


# --- #10 / #30 vault documents -------------------------------------------------------

PASSPORT_TEXT = (
    "doc: United States passport. Surname GUPTA, given names NAITIK. Passport no. 5XXXXXXX1. "
    f"Date of issue 12 Mar 2022. Date of expiration 11 Mar 2032. Emergency contact {PERSON}."
)
IRS_PDF = [
    "Department of the Treasury  Internal Revenue Service",
    "Notice CP575 A   Date of this notice: 03-15-2026",
    "WE ASSIGNED YOU AN EMPLOYER IDENTIFICATION NUMBER",
    "Employer Identification Number: 99-XXXXXXX",
    f"Responsible party: NAITIK GUPTA. Registered agent: {PERSON.upper()}",
    "Keep this notice in your permanent records.",
]
DHS_PDF = [
    "Department of Homeland Security  U.S. Citizenship and Immigration Services",
    "Form I-797, Notice of Action   THE UNITED STATES OF AMERICA",
    "Receipt Number WAC26XXXXXXXX   Case Type I-129 Petition for a Nonimmigrant Worker",
    "Notice Type: Approval Notice   Class: H1B",
    "Valid from 10/01/2026 to 09/30/2029",
    f"Beneficiary: GUPTA, NAITIK   Attorney: {PERSON}",
]


def _assert_invisible(c, name: str, query: str):
    """A vault document: no graph edges, no /graph node, not in /kb/search,
    /retrieve, or the MCP search tools."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    doc_id = f"note:{DOC_FOLDER}/{slug}"
    g = _ok(c.get("/graph"))
    assert not any(n["id"].startswith(f"note:{DOC_FOLDER}/") for n in g["nodes"]), "document is a /graph node"
    assert not [e for e in g["edges"] if doc_id in (e["source"], e["target"])], "document has graph edges"
    assert not any(h["folder"].startswith(DOC_FOLDER) for h in _ok(c.get("/kb/search", params={"q": query}))), "in /kb/search"
    assert not any(DOC_FOLDER in x["id"] for x in _ok(c.get("/retrieve", params={"q": query}))["results"]), "in /retrieve"
    from quintacle_core.mcp_server import server as mcp
    from quintacle_core.retrieval_backfill import run_backfill

    data = __import__("quintacle_core.api", fromlist=["DATA_DIR"]).DATA_DIR
    run_backfill(data)  # the real store gets this pass too
    mcp.init(data)
    assert not any(h["folder"].startswith(DOC_FOLDER) for h in mcp.kb_search_entries(query)), "in MCP kb_search_entries"
    assert not any(DOC_FOLDER in x["id"] for x in mcp.search_index(query)), "in MCP search_index"


def test_passport_drop_is_a_vault_document_and_invisible(client):
    """A typed passport -> document_entry with the printed expiry 2032-03-11;
    after Save it is invisible: no edges (even though it names Laura Chen),
    not in the graph, search, retrieval index or MCP."""
    r = drop(client, text=PASSPORT_TEXT, provider=PROVIDER)
    e = first(r, "document_entry")
    assert e.get("expiry_date") == "2032-03-11", e
    save(client, r)
    _assert_invisible(client, e["suggested_name"], "passport")


@pytest.mark.parametrize("lines,query,doc_word", [
    pytest.param(IRS_PDF, "CP575", "irs", id="30-irs-cp575"),
    pytest.param(DHS_PDF, "I-797", "i-797", id="30-dhs-i797"),
])
def test_irs_dhs_pdf_is_a_vault_document_and_invisible(client, lines, query, doc_word):
    """An unprefixed IRS/DHS letter PDF -> classified as a document_entry (not
    a KB note), then invisible after Save: no edges, not in graph/search/
    retrieval/MCP."""
    r = drop(client, data=make_pdf(lines), filename=f"{doc_word}-letter.pdf", provider=PROVIDER)
    assert "kb_entry" not in types(r), types(r)
    e = first(r, "document_entry")
    save(client, r)
    _assert_invisible(client, e["suggested_name"], query)
