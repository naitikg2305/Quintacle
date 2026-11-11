from quintacle_core.db import connect
from quintacle_core.graph import (
    GraphEdgeStore,
    init_graph_store,
    link_new_entry,
    neighborhood,
    rebuild_from_folder,
    reverse_lookup,
    sync_frontmatter_links,
)


def make(tmp_path):
    conn = connect(tmp_path / "test.db")
    return GraphEdgeStore(tmp_path, conn), conn


def test_create_edge_writes_file_and_sqlite_row(tmp_path):
    store, conn = make(tmp_path)
    edge = store.create_edge("note:fitness/deadlift-cues", "journal:2026-09-08", "on_day", "ai_link")

    edge_files = list((tmp_path / "graph" / "edges").glob("*.md"))
    assert len(edge_files) == 1
    assert edge_files[0].stem == edge["id"]

    row = conn.execute("SELECT * FROM edges WHERE id = ?", (edge["id"],)).fetchone()
    assert row["source_type"] == "note"
    assert row["target_type"] == "journal"
    assert row["kind"] == "on_day"
    assert row["source_of_edge"] == "ai_link"


def test_create_edge_is_idempotent(tmp_path):
    store, _ = make(tmp_path)
    first = store.create_edge("note:a/a", "note:b/b", "related", "ai_link")
    second = store.create_edge("note:a/a", "note:b/b", "related", "ai_link")

    assert first["id"] == second["id"]
    assert len(list((tmp_path / "graph" / "edges").glob("*.md"))) == 1


def test_remove_edge_deletes_file_and_row(tmp_path):
    store, conn = make(tmp_path)
    edge = store.create_edge("note:a/a", "note:b/b", "related", "ai_link")

    assert store.remove_edge(edge["id"]) is True
    assert not list((tmp_path / "graph" / "edges").glob("*.md"))
    assert conn.execute("SELECT * FROM edges WHERE id = ?", (edge["id"],)).fetchone() is None


def test_remove_edge_missing_id_returns_false(tmp_path):
    store, _ = make(tmp_path)
    assert store.remove_edge("nope") is False


def test_reverse_edges_finds_incoming_only(tmp_path):
    store, _ = make(tmp_path)
    store.create_edge("note:a/a", "note:b/b", "related", "ai_link")
    store.create_edge("note:c/c", "note:b/b", "related", "ai_link")

    incoming = store.reverse_edges("note:b/b")
    assert {e["source_id"] for e in incoming} == {"note:a/a", "note:c/c"}
    assert store.reverse_edges("note:a/a") == []


def test_rebuild_from_folder_reproduces_sqlite_from_edge_files_alone(tmp_path):
    store, conn = make(tmp_path)
    store.create_edge("note:a/a", "note:b/b", "related", "ai_link")
    store.create_edge("note:a/a", "journal:2026-09-08", "on_day", "ai_link")

    conn.execute("DELETE FROM edges")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) AS n FROM edges").fetchone()["n"] == 0

    count = rebuild_from_folder(tmp_path, conn)

    assert count == 2
    rows = conn.execute("SELECT * FROM edges").fetchall()
    assert {r["kind"] for r in rows} == {"related", "on_day"}


def test_neighborhood_zero_hops_is_just_the_node(tmp_path):
    store, _ = make(tmp_path)
    store.create_edge("note:a/a", "note:b/b", "related", "ai_link")

    result = store.neighborhood("note:a/a", 0)
    assert result == {"nodes": ["note:a/a"], "edges": []}


def test_neighborhood_walks_multiple_hops(tmp_path):
    store, _ = make(tmp_path)
    store.create_edge("note:a/a", "note:b/b", "related", "ai_link")
    store.create_edge("note:b/b", "note:c/c", "related", "ai_link")
    # Unrelated edge, should not show up within 1 hop of a.
    store.create_edge("note:x/x", "note:y/y", "related", "ai_link")

    one_hop = store.neighborhood("note:a/a", 1)
    assert set(one_hop["nodes"]) == {"note:a/a", "note:b/b"}

    two_hops = store.neighborhood("note:a/a", 2)
    assert set(two_hops["nodes"]) == {"note:a/a", "note:b/b", "note:c/c"}
    assert len(two_hops["edges"]) == 2


def test_link_new_entry_matches_candidate_title_as_whole_word(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))

    candidates = [
        {"id": "note:people/laura/profile", "type": "person", "title": "Laura"},
        {"id": "experience:nyc/restaurants/carbone", "type": "experience", "title": "Carbone"},
    ]
    created = link_new_entry(
        "experience:nyc/restaurants/carbone",
        "experience",
        "Dinner at Carbone with Laura, would return",
        candidates,
        source_of_edge="structural",
    )

    assert len(created) == 1  # Carbone never links to itself
    assert created[0]["source_id"] == "experience:nyc/restaurants/carbone"
    assert created[0]["target_id"] == "note:people/laura/profile"
    assert created[0]["kind"] == "mentions_person"
    assert created[0]["source_of_edge"] == "structural"


def test_link_new_entry_skips_non_matching_candidates(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))

    candidates = [{"id": "note:people/alex/profile", "type": "person", "title": "Alex"}]
    created = link_new_entry("note:a/a", "note", "nothing about anyone here", candidates)

    assert created == []


def test_link_new_entry_avoids_partial_word_false_match(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))

    candidates = [{"id": "note:people/al/profile", "type": "person", "title": "Al"}]
    created = link_new_entry("note:a/a", "note", "had a great time at Albany station", candidates)

    assert created == []


def test_reverse_lookup_module_function(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))
    from quintacle_core.graph import create_edge

    create_edge("note:a/a", "note:b/b", "related", "ai_link")
    assert [e["source_id"] for e in reverse_lookup("note:b/b")] == ["note:a/a"]


def test_neighborhood_module_function(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))
    from quintacle_core.graph import create_edge

    create_edge("note:a/a", "note:b/b", "related", "ai_link")
    result = neighborhood("note:a/a", 1)
    assert set(result["nodes"]) == {"note:a/a", "note:b/b"}


def test_sync_frontmatter_links_resolves_titles_to_ids(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))

    title_lookup = {"Deadlift Cues": "note:fitness/deadlift-cues", "2026-09-08": "journal:2026-09-08"}
    created = sync_frontmatter_links("note:fitness/squat-cues", ["Deadlift Cues", "2026-09-08"], title_lookup)

    kinds = {e["target_id"]: e["kind"] for e in created}
    assert kinds["note:fitness/deadlift-cues"] == "related"
    assert kinds["journal:2026-09-08"] == "on_day"


def test_sync_frontmatter_links_removes_stale_edges_on_resync(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))

    title_lookup = {"A": "note:a/a", "B": "note:b/b"}
    sync_frontmatter_links("note:src/src", ["A", "B"], title_lookup)
    second = sync_frontmatter_links("note:src/src", ["B"], title_lookup)

    remaining = reverse_lookup("note:a/a")
    assert remaining == []
    assert second == []  # B was already synced, nothing new created
    assert [e["source_id"] for e in reverse_lookup("note:b/b")] == ["note:src/src"]


def test_sync_frontmatter_links_ignores_unresolved_titles(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))

    created = sync_frontmatter_links("note:src/src", ["Nonexistent Title"], {})
    assert created == []


def test_sync_frontmatter_links_skips_self_link(tmp_path):
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))

    title_lookup = {"Self": "note:src/src"}
    created = sync_frontmatter_links("note:src/src", ["Self"], title_lookup)
    assert created == []
