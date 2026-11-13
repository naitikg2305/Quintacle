"""Stale-reference cleanup (maintenance.py): files deleted OUTSIDE the app
(file manager) must stop surfacing in search/chat/graph — their retrieval
rows go, their edges move to graph/edges-removed/<ts>/ (undoable), and
nothing virtual or still-alive is touched. All on a tmp data dir."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core import maintenance
from quintacle_core.db import connect
from quintacle_core.graph import get_graph_store, init_graph_store, rebuild_from_folder
from quintacle_core.retrieval import RetrievalIndex, init_retrieval_index


def _write(path: Path, text: str = "# x\n\nbody\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path):
    conn = connect(tmp_path / "quintacle.db")
    init_graph_store(tmp_path, conn)
    index = init_retrieval_index(conn)
    kb = tmp_path / "kb"
    _write(kb / "knowledge" / "tech" / "keep.md", "# Keep\n\nstill here\n")
    _write(kb / "knowledge" / "tech" / "gone.md", "# Gone\n\nabout to be deleted\n")
    _write(kb / "people" / "laura" / "profile.md", "# Laura\n")
    _write(kb / "fun" / "travel" / "vienna" / "restaurants" / "figlmueller.md", "schnitzel")
    _write(tmp_path / "journal" / "2026-11-01.md", "a day")
    for node_id, t in [
        ("note:knowledge/tech/keep", "note"),
        ("note:knowledge/tech/gone", "note"),
        ("note:people/laura/profile", "person"),
        ("experience:fun/travel/vienna/restaurants/figlmueller", "experience"),
        ("journal:2026-11-01", "journal_day"),
    ]:
        index.index_node(node_id, t, node_id, summary="s", body="unique words " + node_id)
    return {"dir": tmp_path, "conn": conn, "index": index, "kb": kb, "graph": get_graph_store()}


def _edge(env, s, t, kind="mentions"):
    return env["graph"].create_edge(s, t, kind, "test")


def _index_ids(conn):
    return {r[0] for r in conn.execute("SELECT id FROM nodes_index")}


def _fts_ids(conn):
    return {r[0] for r in conn.execute("SELECT id FROM nodes_fts")}


def _edge_files(env):
    return {p.stem for p in (env["dir"] / "graph" / "edges").glob("*.md")}


def test_deleted_note_index_rows_and_edges_cleaned_files_moved(env):
    stale = _edge(env, "note:knowledge/tech/gone", "note:people/laura/profile", "mentions_person")
    stale2 = _edge(env, "journal:2026-11-01", "note:knowledge/tech/gone", "on_day")
    alive = _edge(env, "note:knowledge/tech/keep", "note:people/laura/profile", "mentions_person")
    (env["kb"] / "knowledge" / "tech" / "gone.md").unlink()

    report = maintenance.clean_stale(env["dir"], env["conn"], dry_run=False)

    assert [s["id"] for s in report["stale"]] == ["note:knowledge/tech/gone"]
    assert {e["id"] for e in report["edges"]} == {stale["id"], stale2["id"]}
    assert report["counts"] == {**report["counts"], "stale_ids": 1, "index_rows": 1, "edges": 2}
    assert "note:knowledge/tech/gone" not in _index_ids(env["conn"])
    assert "note:knowledge/tech/gone" not in _fts_ids(env["conn"])
    assert all(h["id"] != "note:knowledge/tech/gone" for h in env["index"].retrieve("unique words"))
    # Edge files MOVED, not deleted — and the alive edge stays put.
    assert _edge_files(env) == {alive["id"]}
    moved = Path(report["moved_to"])
    assert moved.parent == env["dir"] / "graph" / "edges-removed"
    assert {p.stem for p in moved.glob("*.md")} == {stale["id"], stale2["id"]}
    assert (moved / "manifest.json").exists()
    assert {r["id"] for r in env["graph"].all()} == {alive["id"]}
    # Everything that still exists is untouched.
    assert {"note:knowledge/tech/keep", "note:people/laura/profile", "journal:2026-11-01",
            "experience:fun/travel/vienna/restaurants/figlmueller"} <= _index_ids(env["conn"])
    assert (env["kb"] / "knowledge" / "tech" / "keep.md").exists()


def test_moved_edges_are_undoable_by_moving_back_and_rebuilding(env):
    e = _edge(env, "note:knowledge/tech/gone", "note:knowledge/tech/keep")
    (env["kb"] / "knowledge" / "tech" / "gone.md").unlink()
    report = maintenance.clean_stale(env["dir"], env["conn"], dry_run=False)
    moved = Path(report["moved_to"]) / f"{e['id']}.md"
    moved.rename(env["dir"] / "graph" / "edges" / moved.name)
    rebuild_from_folder(env["dir"], env["conn"])
    assert {r["id"] for r in env["graph"].all()} == {e["id"]}


def test_people_profiles_experiences_and_journal_resolve_to_their_files(env):
    _edge(env, "note:people/laura/profile", "experience:fun/travel/vienna/restaurants/figlmueller")
    _edge(env, "journal:2026-11-01", "note:people/laura/profile")
    report = maintenance.find_stale(env["dir"], env["conn"])
    assert report["stale"] == [] and report["edges"] == []

    (env["kb"] / "people" / "laura" / "profile.md").unlink()
    (env["dir"] / "journal" / "2026-11-01.md").unlink()
    _write(env["dir"] / "journal" / "2026-11-02.md")  # journal dir not empty
    ids = {s["id"] for s in maintenance.find_stale(env["dir"], env["conn"])["stale"]}
    assert ids == {"note:people/laura/profile", "journal:2026-11-01"}


def test_hand_named_file_is_not_stale(env):
    _write(env["kb"] / "knowledge" / "tech" / "My Note.md")
    env["index"].index_node("note:knowledge/tech/My Note", "note", "My Note")
    assert maintenance.find_stale(env["dir"], env["conn"])["stale"] == []


def test_virtual_place_kept_while_referenced_removed_when_orphaned(env):
    _edge(env, "note:knowledge/tech/gone", "place:europe/austria/vienna", "located_in")
    _edge(env, "experience:fun/travel/vienna/restaurants/figlmueller", "place:europe/austria/vienna", "located_in")
    _edge(env, "place:europe/austria/vienna", "place:europe/austria", "part_of")
    _edge(env, "place:europe/austria", "place:europe", "part_of")
    # A place only the deleted note pointed at — orphaned, cascades up.
    _edge(env, "note:knowledge/tech/gone", "place:_/_/graz", "located_in")
    _edge(env, "note:knowledge/tech/gone", "place:asia/japan/tokyo", "located_in")
    _edge(env, "place:asia/japan/tokyo", "place:asia/japan", "part_of")
    _edge(env, "place:asia/japan", "place:asia", "part_of")
    # An untouched place with no incoming edges is never judged.
    _edge(env, "place:africa/kenya", "place:africa", "part_of")
    env["index"].index_node("place:_/_/graz", "place", "Graz")
    env["index"].index_node("place:europe/austria/vienna", "place", "Vienna")
    (env["kb"] / "knowledge" / "tech" / "gone.md").unlink()

    report = maintenance.clean_stale(env["dir"], env["conn"], dry_run=False)
    ids = {s["id"] for s in report["stale"]}

    assert ids == {"note:knowledge/tech/gone", "place:_/_/graz", "place:asia/japan/tokyo",
                   "place:asia/japan", "place:asia"}
    remaining = {(e["source_id"], e["target_id"]) for e in env["graph"].all()}
    assert ("place:europe/austria/vienna", "place:europe/austria") in remaining
    assert ("place:europe/austria", "place:europe") in remaining
    assert ("place:africa/kenya", "place:africa") in remaining
    assert "place:europe/austria/vienna" in _index_ids(env["conn"])
    assert "place:_/_/graz" not in _index_ids(env["conn"])


def test_event_kept_while_any_member_alive_removed_when_all_gone(env):
    _edge(env, "note:knowledge/tech/gone", "event:aaaaaaaaaaaa", "part_of")
    _edge(env, "note:knowledge/tech/keep", "event:aaaaaaaaaaaa", "part_of")
    _edge(env, "note:knowledge/tech/gone", "event:bbbbbbbbbbbb", "part_of")
    _edge(env, "journal:2026-11-01", "event:bbbbbbbbbbbb", "part_of")
    env["index"].index_node("event:bbbbbbbbbbbb", "event", "event")
    (env["kb"] / "knowledge" / "tech" / "gone.md").unlink()
    (env["dir"] / "journal" / "2026-11-01.md").unlink()
    _write(env["dir"] / "journal" / "2026-11-02.md")

    report = maintenance.clean_stale(env["dir"], env["conn"], dry_run=False)
    ids = {s["id"] for s in report["stale"]}
    assert "event:bbbbbbbbbbbb" in ids and "event:aaaaaaaaaaaa" not in ids
    remaining = {(e["source_id"], e["target_id"]) for e in env["graph"].all()}
    assert remaining == {("note:knowledge/tech/keep", "event:aaaaaaaaaaaa")}
    assert "event:bbbbbbbbbbbb" not in _index_ids(env["conn"])


def test_numeric_log_ids_judged_by_sqlite_row(env):
    cur = env["conn"].execute("INSERT INTO expense_log (date, amount, merchant) VALUES ('2026-11-01', 5, 'cafe')")
    env["conn"].commit()
    live = f"expense:{cur.lastrowid}"
    _edge(env, live, "journal:2026-11-01", "on_day")
    _edge(env, "expense:999", "journal:2026-11-01", "on_day")
    _edge(env, "exercise:bench press", "routine:push", "member_of")  # synthesized, never judged
    env["index"].index_node(live, "expense", "cafe")
    env["index"].index_node("expense:999", "expense", "ghost")

    report = maintenance.clean_stale(env["dir"], env["conn"], dry_run=False)
    assert {s["id"] for s in report["stale"]} == {"expense:999"}
    assert live in _index_ids(env["conn"]) and "expense:999" not in _index_ids(env["conn"])
    remaining = {(e["source_id"], e["target_id"]) for e in env["graph"].all()}
    assert (live, "journal:2026-11-01") in remaining
    assert ("exercise:bench press", "routine:push") in remaining


def test_dry_run_writes_nothing(env):
    _edge(env, "note:knowledge/tech/gone", "note:knowledge/tech/keep")
    (env["kb"] / "knowledge" / "tech" / "gone.md").unlink()
    before = (_index_ids(env["conn"]), _fts_ids(env["conn"]), _edge_files(env), len(env["graph"].all()))

    report = maintenance.clean_stale(env["dir"], env["conn"], dry_run=True)

    assert report["dry_run"] is True
    assert report["counts"]["stale_ids"] == 1 and report["counts"]["edges"] == 1
    assert report["moved_to"] is None
    assert before == (_index_ids(env["conn"]), _fts_ids(env["conn"]), _edge_files(env), len(env["graph"].all()))
    assert not (env["dir"] / "graph" / "edges-removed").exists()


def test_second_run_is_a_no_op(env):
    _edge(env, "note:knowledge/tech/gone", "note:knowledge/tech/keep")
    (env["kb"] / "knowledge" / "tech" / "gone.md").unlink()
    first = maintenance.clean_stale(env["dir"], env["conn"], dry_run=False)
    assert first["counts"]["stale_ids"] == 1
    second = maintenance.clean_stale(env["dir"], env["conn"], dry_run=False)
    assert second["stale"] == [] and second["edges"] == []
    assert second["moved_to"] is None
    assert len(list((env["dir"] / "graph" / "edges-removed").iterdir())) == 1


def test_edge_file_without_sqlite_row_is_also_judged(env):
    e = _edge(env, "note:knowledge/tech/gone", "note:knowledge/tech/keep")
    env["conn"].execute("DELETE FROM edges")
    env["conn"].commit()
    (env["kb"] / "knowledge" / "tech" / "gone.md").unlink()
    report = maintenance.clean_stale(env["dir"], env["conn"], dry_run=False)
    assert [x["id"] for x in report["edges"]] == [e["id"]]
    assert _edge_files(env) == set()


def test_empty_kb_is_never_read_as_everything_deleted(env):
    _edge(env, "note:knowledge/tech/keep", "note:people/laura/profile")
    for p in env["kb"].rglob("*.md"):
        p.unlink()
    assert maintenance.find_stale(env["dir"], env["conn"])["stale"] == []


def test_startup_guard_refuses_mass_staleness(env):
    for name in ("a", "b", "c", "d", "e", "f"):
        env["index"].index_node(f"note:knowledge/tech/{name}", "note", name)
    report = maintenance.run_startup_cleanup(env["dir"], env["conn"])
    assert report["skipped"]
    assert "note:knowledge/tech/a" in _index_ids(env["conn"])
    # Manual run (no fraction guard) does clean them.
    manual = maintenance.clean_stale(env["dir"], env["conn"], dry_run=False)
    assert manual["counts"]["stale_ids"] == 6


def test_startup_cleanup_never_raises(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(maintenance, "clean_stale", boom)
    assert maintenance.run_startup_cleanup(env["dir"], env["conn"]) is None


def test_create_app_runs_startup_cleanup(tmp_path, monkeypatch):
    calls = []
    real = maintenance.run_startup_cleanup
    monkeypatch.setattr(maintenance, "run_startup_cleanup", lambda d, c: calls.append(d) or real(d, c))
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    api_module.create_app()
    assert calls == [tmp_path]


def test_startup_and_endpoint_clean_a_deleted_note(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    for name in ("keep", "keep2", "keep3", "gone"):
        _write(tmp_path / "kb" / "knowledge" / f"{name}.md", f"# {name}\n")
    client = TestClient(api_module.create_app())
    get_graph_store().create_edge("note:knowledge/gone", "note:knowledge/keep", "mentions", "test")
    (tmp_path / "kb" / "knowledge" / "gone.md").unlink()

    dry = client.post("/maintenance/cleanup", params={"dry_run": "true"}).json()
    assert dry["dry_run"] is True
    assert "note:knowledge/gone" in [s["id"] for s in dry["stale"]]
    # 2026-11-13: the startup backfill also put the note in the folder tree
    # (note:knowledge/gone -> part_of -> folder:knowledge); both edges go.
    assert {(e["target"], e["kind"]) for e in dry["edges"]} == {
        ("note:knowledge/keep", "mentions"),
        ("folder:knowledge", "part_of"),
    }
    assert len(get_graph_store().all()) >= 1

    real = client.post("/maintenance/cleanup", params={"dry_run": "false"}).json()
    assert real["dry_run"] is False and real["counts"]["edges"] == 2
    assert "folder:knowledge" not in [s["id"] for s in real["stale"]]  # the folder still exists
    assert all("note:knowledge/gone" not in (e["source_id"], e["target_id"]) for e in get_graph_store().all())

    # Next startup: an edge created to a since-deleted note is cleaned automatically.
    get_graph_store().create_edge("note:knowledge/keep2", "note:knowledge/keep3", "mentions", "test")
    (tmp_path / "kb" / "knowledge" / "keep3.md").unlink()
    TestClient(api_module.create_app())
    assert all("note:knowledge/keep3" not in (e["source_id"], e["target_id"]) for e in get_graph_store().all())
