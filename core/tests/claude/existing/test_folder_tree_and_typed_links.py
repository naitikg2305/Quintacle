"""Owner decisions 2026-11-13: the graph has no gaps for AI navigation, fully
automatic — the owner never creates links or parent nodes by hand.

1. Every KB folder is a graph node (`folder:<slug path>`) and the folder tree
   is in the graph: note -> part_of -> its folder -> part_of -> parent … ->
   top-level folder; a folder's charter (about-*) note -> describes -> it.
2. Typed links (`links:` frontmatter) resolve EXACTLY — case-insensitive,
   trimmed title equality ("travel" = "Travel", "Travels" != "Travel") — and
   immediately: creating "Travel" after a note typed "travel" links it now.

Models FAKED / none involved: every write here is the structured Save
(POST /kb/entries etc.). Sandboxed: tmp DATA_DIR per test.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def c(tmp_path, monkeypatch):
    import quintacle_core.api as api_module

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path / "data")
    return TestClient(api_module.create_app())


def note(c, folder, title, content="", links=None, private=False) -> str:
    r = c.post(
        "/kb/entries",
        json={"folder": folder, "title": title, "content": content, "links": links, "private": private},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    return f"note:{j['folder']}/{j['slug']}"


def gs():
    from quintacle_core.graph import get_graph_store

    return get_graph_store()


def out_edges(source: str, kind: str | None = None, provenance: str | None = None) -> set[str]:
    rows = gs().edges_from(source)
    return {
        r["target_id"]
        for r in rows
        if (kind is None or r["kind"] == kind) and (provenance is None or r["source_of_edge"] == provenance)
    }


def edge_set() -> set[tuple[str, str, str, str]]:
    return {(e["source_id"], e["target_id"], e["kind"], e["source_of_edge"]) for e in gs().all()}


# --- 1. folder nodes ---------------------------------------------------------


def test_note_chains_up_through_every_folder_to_the_top(c):
    nid = note(c, "Fun/Travel/Planned/Europe 2027", "Central Europe", "Vienna, Prague, Budapest.")
    assert out_edges(nid, "part_of", "folder_tree") == {"folder:fun/travel/planned/europe-2027"}
    assert out_edges("folder:fun/travel/planned/europe-2027", "part_of") == {"folder:fun/travel/planned"}
    assert out_edges("folder:fun/travel/planned", "part_of") == {"folder:fun/travel"}
    assert out_edges("folder:fun/travel", "part_of") == {"folder:fun"}
    assert out_edges("folder:fun") == set()  # top level: no parent


def test_done_trip_shares_the_travel_ancestor(c):
    note(c, "Fun/Travel/Planned/Europe 2027", "Central Europe", "")
    done = note(c, "Fun/Travel/Done/Japan 2025", "Japan Trip", "Kyoto temples.")
    # ExperienceStore reads Fun/Travel/<City>/<Kind>/ notes as experiences and
    # /graph draws them under that id — the membership edge follows the id
    # the graph actually shows.
    done_id = done.replace("note:", "experience:", 1)
    assert out_edges(done_id, "part_of", "folder_tree") == {"folder:fun/travel/done/japan-2025"}
    assert out_edges(done, provenance="folder_tree") == set()
    assert out_edges("folder:fun/travel/done", "part_of") == {"folder:fun/travel"}
    members = {r["source_id"] for r in gs().reverse_edges("folder:fun/travel") if r["kind"] == "part_of"}
    assert {"folder:fun/travel/planned", "folder:fun/travel/done"} <= members


def test_about_note_describes_its_folder(c):
    about = note(c, "Fun/Travel", "About Travel", "Trips, plans and places.")
    assert out_edges(about, "describes", "folder_tree") == {"folder:fun/travel"}
    # It is also a member of that folder like any other note.
    assert out_edges(about, "part_of", "folder_tree") == {"folder:fun/travel"}
    plain = note(c, "Fun/Travel", "Packing List", "socks")
    assert out_edges(plain, "describes") == set()


def test_existing_folder_hub_edges_are_kept(c):
    """folder_hub (note -> about-<folder> note) is kept alongside the tree."""
    about = note(c, "Fun/Travel", "About Travel", "Charter.")
    member = note(c, "Fun/Travel", "Packing List", "socks")
    assert about in out_edges(member, "part_of", "folder_hub")


def test_moved_note_loses_its_old_folder_edge(c):
    nid = note(c, "Fun/Travel/Unsorted", "Iceland Idea", "Ring road.")
    assert out_edges(nid, "part_of", "folder_tree") == {"folder:fun/travel/unsorted"}
    r = c.post("/travel/planned/move", json={"folder": "fun/travel/unsorted", "slug": "iceland-idea", "group": "Iceland 2028"})
    assert r.status_code == 200, r.text
    new_id = f"note:{r.json()['folder']}/{r.json()['slug']}"
    assert new_id != nid
    assert out_edges(nid) == set()
    assert out_edges(new_id, "part_of", "folder_tree") == {"folder:fun/travel/planned/iceland-2028"}
    assert out_edges("folder:fun/travel/planned/iceland-2028", "part_of") == {"folder:fun/travel/planned"}


def test_graph_endpoint_emits_labelled_folder_nodes(c):
    nid = note(c, "Fun/Travel/Planned/Europe 2027", "Central Europe", "")
    g = c.get("/graph").json()
    by_id = {n["id"]: n for n in g["nodes"]}
    for fid, label in (
        ("folder:fun", "Fun"),
        ("folder:fun/travel", "Travel"),
        ("folder:fun/travel/planned", "Planned"),
        ("folder:fun/travel/planned/europe-2027", "Europe 2027"),
    ):
        assert by_id[fid]["type"] == "folder"
        assert by_id[fid]["label"] == label
    drawn = {(e["source"], e["target"], e["kind"]) for e in g["edges"]}
    assert (nid, "folder:fun/travel/planned/europe-2027", "part_of") in drawn
    assert ("folder:fun/travel", "folder:fun", "part_of") in drawn


def test_private_note_under_a_folder_is_not_exposed_to_cloud_neighbor_labels(c):
    from quintacle_core.nodes.kb.api import get_store
    from quintacle_core.nodes.kb.privacy import is_private_node, private_filter
    from quintacle_core.retrieval import neighbor_labels

    public = note(c, "Health/Therapy", "Session Logistics", "Tuesdays.")
    secret = note(c, "Health/Therapy", "Secret Diary", "Very private.", private=True)
    folder = "folder:health/therapy"
    assert folder in out_edges(secret, "part_of", "folder_tree")  # the tree still has no gap
    assert not is_private_node(get_store(), folder)  # a folder node is never private

    cloud = neighbor_labels(folder, private_filter(get_store()))
    ids = {n["id"] for n in cloud}
    titles = {n["title"] for n in cloud}
    assert public in ids and "folder:health" in ids
    assert secret not in ids and "Secret Diary" not in titles
    # The owner's own (local) view still sees it.
    assert secret in {n["id"] for n in neighbor_labels(folder)}
    # And the folder node itself reads as a name, not a slug path.
    assert any(n["id"] == "folder:health" and n["title"] == "Health" for n in cloud)


def test_startup_backfill_builds_the_tree_and_is_idempotent(c):
    from quintacle_core.graph_capture import run_graph_capture_backfill
    from quintacle_core.nodes.kb.api import get_store

    # Written straight to disk (a hand-dropped file): no save hook ran.
    get_store().write("Knowledge/Tech Notes/Graphs", "Graph Theory", "Edges and nodes.")
    get_store().write("Fun/Travel/Peru/Hikes", "Machu Picchu", "Hike.")  # an experience file
    nid = "note:knowledge/tech-notes/graphs/graph-theory"
    assert out_edges(nid) == set()

    run_graph_capture_backfill()
    assert out_edges(nid, "part_of", "folder_tree") == {"folder:knowledge/tech-notes/graphs"}
    assert out_edges("folder:knowledge/tech-notes/graphs", "part_of") == {"folder:knowledge/tech-notes"}
    assert out_edges("folder:knowledge/tech-notes", "part_of") == {"folder:knowledge"}
    assert out_edges("experience:fun/travel/peru/hikes/machu-picchu", "part_of", "folder_tree") == {
        "folder:fun/travel/peru/hikes"
    }
    first = edge_set()
    run_graph_capture_backfill()
    assert edge_set() == first


def test_stale_cleanup_removes_a_vanished_folder_node(c):
    import shutil

    import quintacle_core.api as api_module
    from quintacle_core import maintenance

    note(c, "Fun/Keep", "Keeper", "stays")
    nid = note(c, "Fun/Gone/Deep", "Doomed", "goes")
    data_dir = api_module.DATA_DIR
    shutil.rmtree(data_dir / "kb" / "fun" / "gone")
    report = maintenance.clean_stale(data_dir, gs().conn, dry_run=False)
    stale = {s["id"] for s in report["stale"]}
    assert {nid, "folder:fun/gone", "folder:fun/gone/deep"} <= stale
    remaining = {e for e in edge_set() if "folder:fun/gone" in e[0] or "folder:fun/gone" in e[1]}
    assert remaining == set()
    assert out_edges("folder:fun/keep", "part_of") == {"folder:fun"}


# --- 2. typed links: exact + instant -------------------------------------------


def test_typed_link_resolves_case_insensitively_but_never_fuzzily(c):
    travel = note(c, "Fun", "Travel", "All trips.")
    a = note(c, "Fun/Ideas", "Trip Ideas", "", links=["travel"])
    b = note(c, "Fun/Ideas", "Other Ideas", "", links=["Travels"])
    assert travel in out_edges(a, "related", "frontmatter_links")
    assert travel not in out_edges(b)


def test_drop_proposal_filter_uses_the_same_exact_rule():
    from quintacle_core.drop_fixups import existing_links_only

    assert existing_links_only(["travel", "Travels", " TRAVEL "], ["Travel"]) == ["Travel"]


def test_creating_the_target_later_links_the_waiting_note_immediately(c):
    waiting = note(c, "Fun/Ideas", "Trip Ideas", "", links=["travel"])
    assert out_edges(waiting, provenance="frontmatter_links") == set()
    travel = note(c, "Fun", "Travel", "All trips.")
    assert travel in out_edges(waiting, "related", "frontmatter_links")


def test_pending_journal_date_link_resolves_when_the_day_is_written(c):
    waiting = note(c, "Fun/Ideas", "Day Plan", "", links=["2026-11-20"])
    assert out_edges(waiting, provenance="frontmatter_links") == set()
    r = c.post("/journal/2026-11-20", content="Planned the trip.", headers={"Content-Type": "text/plain"})
    assert r.status_code == 200, r.text
    assert "journal:2026-11-20" in out_edges(waiting, "on_day", "frontmatter_links")


def test_typed_link_to_an_experience_name_still_resolves(c):
    r = c.post("/travel/experiences", json={"name": "Blue Lagoon", "city": "Grindavik", "kind": "attraction"})
    assert r.status_code == 200, r.text
    exp_id = f"experience:{r.json()['folder']}/{r.json()['slug']}"
    nid = note(c, "Fun/Ideas", "Iceland Notes", "", links=["blue lagoon"])
    assert exp_id in out_edges(nid, "related", "frontmatter_links")


def test_mcp_write_joins_the_tree_and_undo_removes_its_edges(tmp_path):
    """MCP kb_create_entry goes through the same hook; undoing the push removes
    every edge it created (the staged-snapshot undo contract). A later save or
    the startup backfill rebuilds the chain for notes still in the folder."""
    from quintacle_core.graph_capture import run_graph_capture_backfill
    from quintacle_core.mcp_server import server as s

    s.init(tmp_path / "data")
    first = s.kb_create_entry(folder="Fun/Hobbies/Climbing", title="Bouldering Grades", content="V0-V17.")
    second = s.kb_create_entry(folder="Fun/Hobbies/Climbing", title="Gyms", content="Local ones.")
    first_id = f"note:{first['folder']}/{first['slug']}"
    second_id = f"note:{second['folder']}/{second['slug']}"
    assert out_edges(first_id, "part_of", "folder_tree") == {"folder:fun/hobbies/climbing"}
    s.undo_write(first["ledger_id"])
    assert out_edges(first_id) == set()
    assert out_edges(second_id, "part_of", "folder_tree") == {"folder:fun/hobbies/climbing"}
    run_graph_capture_backfill()
    assert out_edges("folder:fun/hobbies/climbing", "part_of") == {"folder:fun/hobbies"}
    assert out_edges("folder:fun/hobbies", "part_of") == {"folder:fun"}
