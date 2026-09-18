from quintacle_core.nodes.kb.store import KBStore, slugify


def make_store(tmp_path):
    return KBStore(tmp_path / "kb")


def test_write_then_read_round_trip(tmp_path):
    store = make_store(tmp_path)
    folder_slug, entry_slug = store.write("Fitness", "Deadlift Cues", "Brace before you pull.")

    assert folder_slug == "fitness"
    assert entry_slug == "deadlift-cues"
    assert store.read("Fitness", "Deadlift Cues") == "# Deadlift Cues\n\nBrace before you pull."


def test_list_folders_and_entries(tmp_path):
    store = make_store(tmp_path)
    store.write("Fitness", "Deadlift Cues", "notes")
    store.write("Fitness", "Squat Cues", "notes")
    store.write("Travel", "Bahamas Wishlist", "notes")

    assert store.list_folders() == ["fitness", "travel"]
    assert store.list_entries("Fitness") == ["deadlift-cues", "squat-cues"]


def test_missing_entry_returns_none(tmp_path):
    store = make_store(tmp_path)
    assert store.read("nope", "nothing") is None


def test_slugify_strips_path_traversal_characters():
    assert slugify("../../etc/passwd") == "etc-passwd"
    assert "/" not in slugify("a/b/../c")


def test_save_asset_then_read_round_trip(tmp_path):
    store = make_store(tmp_path)
    rel_path = store.save_asset("Fitness", "Deadlift Form.jpg", b"fake-jpeg-bytes")

    assert rel_path == "assets/deadlift-form.jpg"
    assert store.read_asset("Fitness", rel_path) == b"fake-jpeg-bytes"


def test_save_asset_lands_next_to_the_folders_markdown_entries(tmp_path):
    store = make_store(tmp_path)
    store.write("Fitness", "Deadlift Cues", "notes")
    store.save_asset("Fitness", "form-check.stl", b"fake-stl-bytes")

    expected = tmp_path / "kb" / "fitness" / "assets" / "form-check.stl"
    assert expected.exists()


def test_missing_asset_returns_none(tmp_path):
    store = make_store(tmp_path)
    assert store.read_asset("Fitness", "assets/nope.jpg") is None


def test_links_are_frontmatter_not_body_content(tmp_path):
    store = make_store(tmp_path)
    store.write("Fitness", "Deadlift Cues", "Brace before you pull.", links=["Squat Cues"])

    # The body a keep-as-is document depends on staying untouched — links
    # must never leak into it.
    assert store.read("Fitness", "Deadlift Cues") == "# Deadlift Cues\n\nBrace before you pull."
    assert store.read_links("Fitness", "Deadlift Cues") == ["Squat Cues"]


def test_entry_with_no_links_reads_back_empty_list(tmp_path):
    store = make_store(tmp_path)
    store.write("Fitness", "Deadlift Cues", "notes")

    assert store.read_links("Fitness", "Deadlift Cues") == []


def test_pre_existing_file_with_no_frontmatter_still_reads_fine(tmp_path):
    # Real entries written before links existed have no frontmatter at all —
    # read()/read_links() must handle that, not just newly-written ones.
    store = make_store(tmp_path)
    folder_path = tmp_path / "kb" / "fitness"
    folder_path.mkdir(parents=True)
    (folder_path / "old-note.md").write_text("# Old Note\n\nWritten before links existed.\n", encoding="utf-8")

    assert store.read("Fitness", "old-note") == "# Old Note\n\nWritten before links existed."
    assert store.read_links("Fitness", "old-note") == []


def test_graph_entries_includes_links_and_asset(tmp_path):
    store = make_store(tmp_path)
    store.write("Fitness", "Squat Cues", "notes")
    store.write("Fitness", "Deadlift Cues", "Brace before you pull.", links=["Squat Cues"])
    folder_slug, entry_slug = "fitness", "deadlift-cues"
    asset_path = store.save_asset(folder_slug, "form.jpg", b"fake")
    store.write("Fitness", "Deadlift Cues", f"Brace before you pull.\n\n[asset]({asset_path})", links=["Squat Cues"])

    entries = {e["slug"]: e for e in store.graph_entries()}
    assert entries["deadlift-cues"]["links"] == ["Squat Cues"]
    assert entries["deadlift-cues"]["asset"] == "assets/form.jpg"
    assert entries["squat-cues"]["links"] == []
