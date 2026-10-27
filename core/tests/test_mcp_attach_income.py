"""MCP kb_attach_file + log_income: validation, the shared KBStore/
LogsRepository write paths, retrieval indexing, and one-ledger-entry undo."""
from datetime import date

import pytest

from quintacle_core import retrieval
from quintacle_core.markdown_paths import resolve_nested
from quintacle_core.mcp_server import server as s
from quintacle_core.nodes.finance.insights import monthly_breakdown


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path):
    s.init(tmp_path / "data")
    yield


@pytest.fixture
def note():
    created = s.kb_create_entry(folder="Career/Documents", title="Offer letter", content="Acme offer, Oct 2026.")
    path = s.kb_store.entry_path(created["folder"], created["slug"])
    return created["folder"], created["slug"], path


def _src(tmp_path, name="Contract Final.PDF", data=b"%PDF-1.7 fake contract bytes"):
    src_dir = tmp_path / "elsewhere"
    src_dir.mkdir(exist_ok=True)
    p = src_dir / name
    p.write_bytes(data)
    return p


# --- kb_attach_file ---


def test_attach_success_bytes_identical_and_note_references_it(tmp_path, note):
    folder, slug, note_path = note
    src = _src(tmp_path)

    result = s.kb_attach_file(folder=folder, slug=slug, local_path=str(src))

    assert result["folder"] == folder and result["slug"] == slug
    assert result["asset_path"] == "assets/contract-final.pdf"
    assert result["bytes"] == len(src.read_bytes())
    assert "ledger_id" in result
    assert s.kb_store.read_asset(folder, result["asset_path"]) == src.read_bytes()
    # Same layout as REST POST /kb/entry/asset (KBStore.add_asset_to_entry)
    assert "[asset](assets/contract-final.pdf)" in note_path.read_text()
    assert "assets/contract-final.pdf" in s.kb_store.list_entries_meta(folder)[0]["assets"]
    # Ledger: exactly one entry for the attach
    assert s.list_recent_writes(limit=1)[0]["tool"] == "kb.attach_file"


def test_attach_missing_note_never_creates_one(tmp_path):
    src = _src(tmp_path)
    with pytest.raises(ValueError, match="no such entry"):
        s.kb_attach_file(folder="Career", slug="ghost", local_path=str(src))
    assert not (s.kb_store.root / "career" / "ghost.md").exists()
    assert not (s.kb_store.root / "career" / "assets").exists()


def test_attach_rejects_missing_relative_dir_and_symlink(tmp_path, note):
    folder, slug, _ = note
    with pytest.raises(ValueError, match="no such file"):
        s.kb_attach_file(folder=folder, slug=slug, local_path=str(tmp_path / "nope.pdf"))
    with pytest.raises(ValueError, match="absolute"):
        s.kb_attach_file(folder=folder, slug=slug, local_path="relative/file.pdf")
    d = tmp_path / "a-dir"
    d.mkdir()
    with pytest.raises(ValueError, match="directory"):
        s.kb_attach_file(folder=folder, slug=slug, local_path=str(d))
    link = tmp_path / "link.pdf"
    link.symlink_to(_src(tmp_path))
    with pytest.raises(ValueError, match="symlink"):
        s.kb_attach_file(folder=folder, slug=slug, local_path=str(link))
    assert s.list_recent_writes(limit=5)[0]["tool"] == "kb.create_entry"  # nothing ledgered


def test_attach_oversize_rejected(tmp_path, note, monkeypatch):
    folder, slug, note_path = note
    before = note_path.read_bytes()
    monkeypatch.setattr(s, "KB_ATTACH_MAX_BYTES", 10)
    with pytest.raises(ValueError, match="attach limit"):
        s.kb_attach_file(folder=folder, slug=slug, local_path=str(_src(tmp_path, data=b"x" * 11)))
    assert note_path.read_bytes() == before


def test_attach_rejects_vault_source(tmp_path, note):
    folder, slug, _ = note
    vault = s.DATA_DIR / "vault"
    vault.mkdir(parents=True)
    secret = vault / "blob.bin"
    secret.write_bytes(b"ciphertext")
    with pytest.raises(ValueError, match="Vault"):
        s.kb_attach_file(folder=folder, slug=slug, local_path=str(secret))


def test_attach_clamp_blocks_assets_symlinked_into_vault(tmp_path, note):
    folder, slug, note_path = note
    vault = s.DATA_DIR / "vault"
    vault.mkdir(parents=True)
    (resolve_nested(s.kb_store.root, folder) / "assets").symlink_to(vault, target_is_directory=True)
    before = note_path.read_bytes()
    with pytest.raises(ValueError, match="outside the KB"):
        s.kb_attach_file(folder=folder, slug=slug, local_path=str(_src(tmp_path)))
    assert list(vault.iterdir()) == []
    assert note_path.read_bytes() == before


def test_attach_traversal_filename_is_sanitized(tmp_path, note):
    folder, slug, _ = note
    src = _src(tmp_path)
    result = s.kb_attach_file(folder=folder, slug=slug, local_path=str(src), filename="../../vault/Evil Name.pdf")
    assert result["asset_path"] == "assets/evil-name.pdf"
    assert (resolve_nested(s.kb_store.root, folder) / "assets" / "evil-name.pdf").is_file()
    assert not (s.DATA_DIR / "vault").exists()

    # "/" or ".." hidden after the last dot can't survive either
    weird = s.kb_attach_file(folder=folder, slug=slug, local_path=str(src), filename="x.p/../df")
    assert "/" not in weird["asset_path"].removeprefix("assets/")
    assert ".." not in weird["asset_path"]


def test_attach_custom_name_without_extension_keeps_source_extension(tmp_path, note):
    folder, slug, _ = note
    result = s.kb_attach_file(folder=folder, slug=slug, local_path=str(_src(tmp_path)), filename="Signed Contract")
    assert result["asset_path"] == "assets/signed-contract.pdf"


def test_attach_collision_gets_suffix_never_overwrites(tmp_path, note):
    folder, slug, note_path = note
    first = s.kb_attach_file(folder=folder, slug=slug, local_path=str(_src(tmp_path, data=b"v1")))
    second = s.kb_attach_file(folder=folder, slug=slug, local_path=str(_src(tmp_path, data=b"v2")))
    third = s.kb_attach_file(folder=folder, slug=slug, local_path=str(_src(tmp_path, data=b"v3")))
    assert [first["asset_path"], second["asset_path"], third["asset_path"]] == [
        "assets/contract-final.pdf",
        "assets/contract-final-2.pdf",
        "assets/contract-final-3.pdf",
    ]
    assert s.kb_store.read_asset(folder, first["asset_path"]) == b"v1"
    assert s.kb_store.read_asset(folder, second["asset_path"]) == b"v2"
    assert s.kb_store.read_asset(folder, third["asset_path"]) == b"v3"


def test_attach_undo_restores_note_exactly_and_removes_asset(tmp_path, note):
    folder, slug, note_path = note
    before = note_path.read_bytes()
    folders_before = s.kb_list_folders()
    result = s.kb_attach_file(folder=folder, slug=slug, local_path=str(_src(tmp_path)))

    s.undo_write(result["ledger_id"])

    assert note_path.read_bytes() == before
    assets_dir = resolve_nested(s.kb_store.root, folder) / "assets"
    assert not assets_dir.exists()  # the dir the attach created is gone too
    assert s.kb_list_folders() == folders_before


def test_attach_two_level_undo(tmp_path, note):
    folder, slug, note_path = note
    original = note_path.read_bytes()
    a = s.kb_attach_file(folder=folder, slug=slug, local_path=str(_src(tmp_path, "resume.docx", b"A")))
    after_a = note_path.read_bytes()
    b = s.kb_attach_file(folder=folder, slug=slug, local_path=str(_src(tmp_path, "resume.docx", b"B")))
    assert b["asset_path"] == "assets/resume-2.docx"
    assets_dir = resolve_nested(s.kb_store.root, folder) / "assets"

    s.undo_write(b["ledger_id"])
    assert note_path.read_bytes() == after_a
    assert not (assets_dir / "resume-2.docx").exists()
    assert (assets_dir / "resume.docx").read_bytes() == b"A"

    s.undo_write(a["ledger_id"])
    assert note_path.read_bytes() == original
    assert not assets_dir.exists()

    with pytest.raises(ValueError, match="already undone"):
        s.undo_write(a["ledger_id"])


def test_attach_undo_keeps_preexisting_assets_dir(tmp_path, note):
    folder, slug, _ = note
    s.kb_attach_file(folder=folder, slug=slug, local_path=str(_src(tmp_path, "a.pdf", b"a")))
    second = s.kb_attach_file(folder=folder, slug=slug, local_path=str(_src(tmp_path, "b.pdf", b"b")))
    s.undo_write(second["ledger_id"])
    assets_dir = resolve_nested(s.kb_store.root, folder) / "assets"
    assert sorted(p.name for p in assets_dir.iterdir()) == ["a.pdf"]


# --- log_income ---


def _income_files():
    logs_dir = resolve_nested(s.log_file_store.kb_root, "Organisation/Finance") / "logs"
    return sorted(logs_dir.glob("*.md")) if logs_dir.exists() else []


def test_log_income_row_markdown_and_retrieval_index():
    result = s.log_income(for_date="2026-10-01", amount=4200.0, source="Acme", kind="salary", notes="October paycheck")

    assert result["date"] == "2026-10-01"
    rows = s.logs_repo.income_between(date(2026, 10, 1), date(2026, 10, 1))
    assert [dict(r)["amount"] for r in rows] == [4200.0]
    assert rows[0]["id"] == result["income_id"]
    assert rows[0]["source"] == "Acme" and rows[0]["kind"] == "salary"

    files = _income_files()
    assert len(files) == 1
    text = files[0].read_text()
    assert "type: income" in text and "October paycheck" in text

    conn = retrieval.get_retrieval_index().conn
    indexed = conn.execute("SELECT id, type FROM nodes_index WHERE id = ?", (f"income:{result['income_id']}",)).fetchone()
    assert indexed is not None and indexed["type"] == "income"


def test_log_income_feeds_monthly_insights():
    s.log_income(for_date="2026-10-01", amount=4000.0, source="Acme")
    s.log_income(for_date="2026-10-15", amount=250.0, source="sold a lens", kind="other")
    s.log_expense(for_date="2026-10-03", amount=1000.0, merchant="Landlord")

    months = monthly_breakdown(s.db_conn, months=1, today=date(2026, 10, 27))
    october = months[-1]
    assert october["income"] == 4250.0
    assert october["savings_rate_pct"] == round((4250 - 1000) / 4250 * 100, 1)


def test_log_income_rejects_unknown_kind():
    with pytest.raises(ValueError, match="kind must be one of"):
        s.log_income(for_date="2026-10-01", amount=10.0, kind="bonus")
    assert _income_files() == []


def test_log_income_undo_removes_row_and_file_only():
    s.log_expense(for_date="2026-10-01", amount=12.0, merchant="Cafe")  # shares the logs dir
    keep = s.log_income(for_date="2026-10-01", amount=100.0, source="gig", kind="other")
    gone = s.log_income(for_date="2026-10-01", amount=4200.0, source="Acme")
    assert len(_income_files()) == 3

    s.undo_write(gone["ledger_id"])

    rows = s.logs_repo.income_between(date(2026, 10, 1), date(2026, 10, 1))
    assert [r["id"] for r in rows] == [keep["income_id"]]
    assert len(_income_files()) == 2
    assert len(s.expenses_in_range("2026-10-01", "2026-10-01")) == 1

    s.undo_write(keep["ledger_id"])
    assert s.logs_repo.income_between(date(2026, 10, 1), date(2026, 10, 1)) == []
    assert len(_income_files()) == 1  # the expense's file stays


def test_safe_asset_name_never_keeps_separators_in_the_extension():
    from quintacle_core.nodes.kb.store import safe_asset_name

    assert safe_asset_name("Deadlift Form.JPG") == "deadlift-form.jpg"  # unchanged behavior
    assert safe_asset_name("evil./../../x") == "evil.x"
    weird = safe_asset_name("a.b/../../c")
    assert "/" not in weird and ".." not in weird
