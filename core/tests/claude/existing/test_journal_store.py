from datetime import date

from quintacle_core.nodes.journal.store import JournalStore


def test_second_save_same_day_appends_not_overwrites(tmp_path):
    store = JournalStore(tmp_path / "journal")
    d = date(2026, 9, 8)

    store.save(d, "had lamb for breakfast, feeling good")
    store.save(d, "did pull day in the evening")

    content = store.load(d)
    assert "had lamb for breakfast, feeling good" in content
    assert "did pull day in the evening" in content


def test_first_save_of_the_day_has_no_leading_separator(tmp_path):
    store = JournalStore(tmp_path / "journal")
    d = date(2026, 9, 8)

    store.save(d, "first dump of the day")

    assert store.load(d).strip().endswith("first dump of the day")
    assert "---" not in store.load(d)


def test_different_days_stay_independent(tmp_path):
    store = JournalStore(tmp_path / "journal")

    store.save(date(2026, 9, 8), "day one stuff")
    store.save(date(2026, 9, 9), "day two stuff")

    assert "day two stuff" not in store.load(date(2026, 9, 8))
    assert "day one stuff" not in store.load(date(2026, 9, 9))


def test_load_strips_mcp_append_markers_but_keeps_content(tmp_path):
    from datetime import date

    store = JournalStore(tmp_path)
    store.save(date(2026, 10, 13), "from the app")
    store.save(date(2026, 10, 13), "from mcp", marker="abc123def456")

    content = store.load(date(2026, 10, 13))
    assert "from the app" in content
    assert "from mcp" in content
    assert "mcp-append" not in content
