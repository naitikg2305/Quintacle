"""File metadata baking (nodes/kb/file_meta.py): deterministic extraction
per type (PDF incl. compressed object streams, DOCX/XLSX/PPTX core.xml,
image EXIF, MP4 boxes), date normalization, the 🗂 line (format,
idempotency, coexistence with 📍), the drop-step proposals, every save
path, the on_day journal edge, backfill, and summary-vs-FTS. Fixtures are
built in-test; no network, no models."""
from __future__ import annotations

import io
import struct
import zipfile
import zlib
from datetime import date, datetime, timezone

import openpyxl
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import quintacle_core.api as api_module
from quintacle_core import retrieval
from quintacle_core.graph import get_graph_store
from quintacle_core.mcp_server import server as s
from quintacle_core.nodes.journal.api import get_store as get_journal_store
from quintacle_core.nodes.kb import api as kb_api
from quintacle_core.nodes.kb import photo_organizer
from quintacle_core.nodes.kb.file_meta import (
    FILEMETA_MARKER,
    compose_file_meta_line,
    extract_file_meta,
    insert_file_meta_lines,
    is_file_meta_line,
    parse_iso_date,
    parse_pdf_date,
)
from quintacle_core.nodes.kb.llm import BatchDropSuggestion, BatchFileSuggestion, KBSuggestion
from quintacle_core.nodes.kb.photo_organizer import GeocodedLocation
from quintacle_core.nodes.kb.photo_place import insert_place_line

# --------------------------------------------------------------- fixtures


def pdf_bytes(
    title: bytes = b"(Austria itinerary)",
    author: bytes = b"(Naitik)",
    created: bytes = b"(D:20261104093000-05'00')",
    pages: int = 12,
) -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count " + str(pages).encode() + b" >>\nendobj\n"
        b"3 0 obj\n<< /Title " + title + b" /Author " + author + b" /Subject (Trip plan)"
        b" /CreationDate " + created + b" /ModDate (D:20261105120000Z) /Producer (Writer) >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R /Info 3 0 R >>\n%%EOF\n"
    )


def pdf_objstm_bytes() -> bytes:
    """PDF 1.5 style: Pages + Info live inside a Flate object stream."""
    o2 = b"<< /Type /Pages /Kids [] /Count 3 >>"
    o5 = b"<< /Title <FEFF00560069007300610020007000610067 0065> /Author (Clerk \\(HR\\)) /CreationDate (D:20260512) >>"
    header = f"2 0 5 {len(o2) + 1} ".encode()
    content = header + o2 + b" " + o5
    comp = zlib.compress(content)
    return (
        b"%PDF-1.5\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Type /ObjStm /N 2 /First " + str(len(header)).encode() + b" /Filter /FlateDecode /Length "
        + str(len(comp)).encode() + b" >>\nstream\n" + comp + b"\nendstream\nendobj\n"
        b"6 0 obj\n<< /Type /XRef /Root 1 0 R /Info 5 0 R >>\nendobj\n%%EOF\n"
    )


_CORE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    "<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator><cp:lastModifiedBy>Naitik</cp:lastModifiedBy>"
    '<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>'
    '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-06-01T10:00:00Z</dcterms:modified>'
    "</cp:coreProperties>"
)
_APP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">{body}</Properties>'
)


def ooxml_bytes(title="Lease agreement", author="Jane Landlord", created="2026-05-12T14:00:00Z", app="<Pages>3</Pages>") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("docProps/core.xml", _CORE.format(title=title, author=author, created=created))
        z.writestr("docProps/app.xml", _APP.format(body=app))
    return buf.getvalue()


def xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    wb.create_sheet("Two")
    wb.properties.title = "Budget 2026"
    wb.properties.creator = "Naitik"
    wb.properties.created = datetime(2026, 5, 12, 14, 0, 0)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def jpeg_bytes(stamp="2027:05:14 15:32:00") -> bytes:
    img = Image.new("RGB", (40, 30), "red")
    exif = Image.Exif()
    exif[271] = "Apple"
    exif[272] = "iPhone 15 Pro"
    if stamp:
        exif[306] = stamp
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), typ) + payload


def mp4_bytes(created=datetime(2026, 5, 12, 16, 0, tzinfo=timezone.utc), duration_ms=83_000, xyz=b"+48.2082+016.3738/") -> bytes:
    secs = int((created - datetime(1904, 1, 1, tzinfo=timezone.utc)).total_seconds())
    mvhd = _box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">IIII", secs, secs, 1000, duration_ms) + b"\x00" * 80)
    udta = _box(b"udta", _box(b"\xa9xyz", struct.pack(">HH", len(xyz), 0x15C7) + xyz)) if xyz else b""
    return _box(b"ftyp", b"isom\x00\x00\x02\x00isom") + _box(b"moov", mvhd + udta) + _box(b"mdat", b"\x00" * 16)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(photo_organizer, "geocode", lambda lat, lon: GeocodedLocation(country="Austria", state="Vienna", city="Vienna"))
    return TestClient(api_module.create_app())


def commit(client, name, data, title="Austria trip doc", folder="Travel/Austria", mime="application/pdf"):
    form = {"folder": folder, "title": title, "content": "Planning notes.", "links": ""}
    res = client.post("/kb/entries/with-asset", data=form, files=[("files", (name, data, mime))])
    assert res.status_code == 200, res.text
    return res.json()


def note_text(tmp_path, folder_slug, slug) -> str:
    return (tmp_path / "kb" / folder_slug / f"{slug}.md").read_text()


def hit_ids(query):
    return [h["id"] for h in retrieval.retrieve(query, k=10)]


def on_day_targets(note_id):
    rows = get_graph_store().conn.execute(
        "SELECT target_id FROM edges WHERE source_id = ? AND kind = 'on_day'", (note_id,)
    ).fetchall()
    return sorted(r["target_id"] for r in rows)


# --------------------------------------------------------------- dates


@pytest.mark.parametrize(
    "raw,iso",
    [
        ("D:20261104093000-05'00'", "2026-11-04T09:30:00-05:00"),
        ("D:20261105120000Z", "2026-11-05T07:00:00-05:00"),  # UTC → Eastern
        ("D:20260512", "2026-05-12T00:00:00"),
        ("D:2026", "2026-01-01T00:00:00"),
        ("20260512143000+02'00", "2026-05-12T08:30:00-04:00"),
        ("garbage", None),
        ("", None),
    ],
)
def test_pdf_date_normalization(raw, iso):
    assert parse_pdf_date(raw) == iso


def test_iso_date_normalization():
    assert parse_iso_date("2026-05-12T14:00:00Z") == "2026-05-12T10:00:00-04:00"
    assert parse_iso_date("2026-05-12T14:00:00+0200") == "2026-05-12T08:00:00-04:00"
    assert parse_iso_date("2026-05-12") == "2026-05-12T00:00:00"
    assert parse_iso_date("nope") is None


# --------------------------------------------------------------- extraction


def test_extract_pdf():
    m = extract_file_meta("austria.pdf", pdf_bytes())
    assert m["kind"] == "pdf" and m["mime"] == "application/pdf"
    assert m["title"] == "Austria itinerary" and m["author"] == "Naitik" and m["subject"] == "Trip plan"
    assert m["created"] == "2026-11-04T09:30:00-05:00" and m["modified"] == "2026-11-05T07:00:00-05:00"
    assert m["pages"] == 12 and m["producer"] == "Writer" and m["day"] == "2026-11-04"
    assert m["filename"] == "austria.pdf" and m["size"] == len(pdf_bytes())


def test_extract_pdf_object_stream_hex_utf16_and_escapes():
    m = extract_file_meta("visa.pdf", pdf_objstm_bytes())
    assert m["title"] == "Visa page" and m["author"] == "Clerk (HR)"
    assert m["pages"] == 3 and m["day"] == "2026-05-12"


def test_extract_garbage_pdf_degrades_to_common_fields():
    m = extract_file_meta("c.pdf", b"%PDF-1.7 x")
    assert m["kind"] == "pdf" and "title" not in m and m["size"] == 10


def test_extract_docx():
    m = extract_file_meta("lease.docx", ooxml_bytes())
    assert m["kind"] == "document"
    assert m["title"] == "Lease agreement" and m["author"] == "Jane Landlord" and m["last_modified_by"] == "Naitik"
    assert m["created"] == "2026-05-12T10:00:00-04:00" and m["modified"] == "2026-06-01T06:00:00-04:00"
    assert m["pages"] == 3 and m["day"] == "2026-05-12"


def test_extract_xlsx_real_openpyxl():
    m = extract_file_meta("budget.xlsx", xlsx_bytes())
    assert m["kind"] == "spreadsheet" and m["title"] == "Budget 2026" and m["author"] == "Naitik"
    assert m["sheets"] == 2 and m["created"].startswith("2026-05-12")


def test_extract_pptx():
    m = extract_file_meta("deck.pptx", ooxml_bytes(title="Q3 review", app="<Slides>7</Slides>"))
    assert m["kind"] == "presentation" and m["slides"] == 7
    assert "7 slides" in compose_file_meta_line(m)


def test_extract_image():
    m = extract_file_meta("IMG_1.jpg", jpeg_bytes())
    assert m["kind"] == "image" and m["camera_make"] == "Apple" and m["camera_model"] == "iPhone 15 Pro"
    assert (m["width"], m["height"]) == (40, 30) and m["taken"] == "2027-05-14T15:32:00" and m["day"] == "2027-05-14"


def test_extract_mp4():
    m = extract_file_meta("clip.mp4", mp4_bytes())
    assert m["kind"] == "video" and m["duration_s"] == 83.0
    assert m["created"] == "2026-05-12T12:00:00-04:00" and m["day"] == "2026-05-12"
    assert m["location"] == {"lat": 48.2082, "lon": 16.3738}
    assert "1:23" in compose_file_meta_line(m)


def test_extract_unknown_and_webm():
    assert extract_file_meta("part.stl", b"solid x")["ext"] == "stl"
    w = extract_file_meta("v.webm", b"\x1aE\xdf\xa3 junk")
    assert w["kind"] == "video" and "duration_s" not in w


# --------------------------------------------------------------- the line


def test_line_format():
    line = compose_file_meta_line(extract_file_meta("austria.pdf", pdf_bytes()))
    assert line.startswith('🗂 PDF · "Austria itinerary" · subject: Trip plan · 12 pages · created 2026-11-04 by Naitik')
    assert line.endswith(f" B) {FILEMETA_MARKER}") and "· austria.pdf (" in line
    assert is_file_meta_line(line)
    assert "modified 2026-11-05" in line


def test_insert_idempotent_and_coexists_with_place_line():
    body = "# T\n\nHello.\n\n[asset](assets/a.jpg)\n"
    place = "📍 Vienna, Austria · Europe <!-- place -->"
    fm = f"🗂 JPG · a.jpg (1 KB) {FILEMETA_MARKER}"
    both = insert_file_meta_lines(insert_place_line(body, place), [fm])
    assert both == f"# T\n\nHello.\n\n{place}\n\n{fm}\n\n[asset](assets/a.jpg)\n"
    assert insert_file_meta_lines(both, [fm]) == both
    # re-running the place bake keeps 📍 before 🗂
    assert insert_place_line(both, place) == both
    # reverse order of first bake lands in the same shape
    assert insert_place_line(insert_file_meta_lines(body, [fm]), place) == both


# --------------------------------------------------------------- save paths


def test_create_with_asset_bakes_frontmatter_and_fts(client, tmp_path):
    out = commit(client, "Austria Itinerary.pdf", pdf_bytes())
    text = note_text(tmp_path, out["folder"], out["slug"])
    assert '🗂 PDF · "Austria itinerary"' in text and "Austria Itinerary.pdf" in text
    assert text.index("🗂") < text.index("[asset](")
    assert "file_meta:" in text
    note_id = f"note:{out['folder']}/{out['slug']}"
    assert note_id in hit_ids("Naitik")  # the PDF's author is only in the 🗂 line
    # summary skips the line
    row = retrieval.retrieve("Naitik", k=5)
    hit = next(h for h in row if h["id"] == note_id)
    assert "🗂" not in hit["summary"]
    assert retrieval.deterministic_prose_summary(text.split("---", 2)[2], "x") == "Planning notes."


def test_browse_meta_hides_file_meta(client, tmp_path):
    from quintacle_core.nodes.kb.api import get_store

    out = commit(client, "a.pdf", pdf_bytes())
    full = get_store().read_full(out["folder"], out["slug"])
    assert "file_meta" not in full["meta"]


def test_photo_gets_both_lines(client, tmp_path):
    out = commit(client, "v.jpg", jpeg_bytes(), folder="Media/Photos/2027/May", mime="image/jpeg")
    text = note_text(tmp_path, out["folder"], out["slug"])
    assert text.count("🗂") == 1 and "Apple iPhone 15 Pro · 40×30 · taken 2027-05-14 15:32" in text


def test_save_never_trusts_client_meta(client, tmp_path):
    res = client.post(
        "/kb/entries/with-asset",
        data={"folder": "Docs", "title": "Lease", "content": "x", "links": "", "file_meta": '[{"title": "FAKE"}]'},
        files=[("files", ("lease.docx", ooxml_bytes(), "application/octet-stream"))],
    )
    text = note_text(tmp_path, res.json()["folder"], res.json()["slug"])
    assert "FAKE" not in text and '"Lease agreement"' in text and "by Jane Landlord" in text


def test_rest_add_asset_bakes_and_indexes(client, tmp_path):
    created = client.post("/kb/entries", json={"folder": "Docs", "title": "Home", "content": "My lease."}).json()
    res = client.post(
        "/kb/entry/asset",
        data={"folder": created["folder"], "slug": created["slug"]},
        files={"file": ("lease.docx", ooxml_bytes(), "application/octet-stream")},
    )
    assert res.status_code == 200
    assert '"Lease agreement"' in note_text(tmp_path, created["folder"], created["slug"])
    assert f"note:{created['folder']}/{created['slug']}" in hit_ids("Landlord")


def test_mcp_attach_bakes_links_day_and_undo_restores(tmp_path):
    s.init(tmp_path / "data")
    s.journal_store.save(date(2026, 5, 12), "Got the lease signed.")
    created = s.kb_create_entry(folder="Docs", title="Lease", content="Lease.")
    path = s.kb_store.entry_path(created["folder"], created["slug"])
    before = path.read_bytes()
    src = tmp_path / "elsewhere"
    src.mkdir()
    (src / "lease.docx").write_bytes(ooxml_bytes())
    result = s.kb_attach_file(folder=created["folder"], slug=created["slug"], local_path=str(src / "lease.docx"))
    assert '"Lease agreement"' in path.read_text() and "lease.docx" in path.read_text()
    note_id = f"note:{created['folder']}/{created['slug']}"
    assert on_day_targets(note_id) == ["journal:2026-05-12"]
    assert note_id in [h["id"] for h in s.search_index("Landlord")]
    s.undo_write(result["ledger_id"])
    assert path.read_bytes() == before
    assert on_day_targets(note_id) == []


# --------------------------------------------------------------- graph: on_day


def test_on_day_only_when_journal_exists_and_day_bundle_surfaces_it(client, tmp_path):
    out = commit(client, "pass.pdf", pdf_bytes(title=b"(Boarding pass)", created=b"(D:20260512080000-04'00')"))
    note_id = f"note:{out['folder']}/{out['slug']}"
    assert on_day_targets(note_id) == []  # no journal for that day yet
    get_journal_store().save(date(2026, 5, 12), "Flew to Vienna.")
    out2 = commit(client, "pass2.pdf", pdf_bytes(title=b"(Boarding pass 2)", created=b"(D:20260512080000-04'00')"), title="Pass two")
    note2 = f"note:{out2['folder']}/{out2['slug']}"
    assert on_day_targets(note2) == ["journal:2026-05-12"]
    day = client.get("/day/2026-05-12").json()
    assert note2.removeprefix("note:").rsplit("/", 1)[1] in [p["slug"] for p in day["photos"]]


# --------------------------------------------------------------- drop step


def test_kb_drop_and_batch_drop_carry_file_meta(client, monkeypatch):
    monkeypatch.setattr(kb_api, "describe_drop", lambda name, data, desc: "a pdf")
    monkeypatch.setattr(kb_api, "suggest_kb_entry", lambda *a, **k: KBSuggestion(folder="Travel", title="It", content="c"))
    r = client.post("/kb/drop", files={"file": ("austria.pdf", pdf_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    [fm] = r.json()["file_meta"]
    assert fm["title"] == "Austria itinerary" and fm["pages"] == 12 and fm["line"].startswith("🗂 PDF")

    monkeypatch.setattr(
        kb_api,
        "suggest_kb_batch",
        lambda entries, *a, **k: BatchDropSuggestion(
            files=[BatchFileSuggestion(file_id=e["file_id"], folder="Docs", title=e["file_id"], content="c") for e in entries]
        ),
    )
    r = client.post(
        "/kb/batch-drop",
        files=[("files", ("a.pdf", pdf_bytes(), "application/pdf")), ("files", ("l.docx", ooxml_bytes(), "application/octet-stream"))],
    )
    assert r.status_code == 200, r.text
    files = r.json()["buckets"][0]["files"]
    titles = {f["filename"]: f["file_meta"][0].get("title") for f in files}
    assert titles == {"a.pdf": "Austria itinerary", "l.docx": "Lease agreement"}


def test_general_drop_kb_entry_carries_file_meta(client, monkeypatch):
    monkeypatch.setattr(api_module, "describe_drop", lambda *a, **k: "an itinerary pdf")
    monkeypatch.setattr(api_module, "suggest_kb_entry", lambda *a, **k: KBSuggestion(folder="Travel", title="It", content="c"))
    monkeypatch.setattr(api_module, "structure_experience", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("off")), raising=False)
    r = client.post("/drop", data={"text": "note: austria plan"}, files={"file": ("austria.pdf", pdf_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    kb = [e for e in r.json()["entries"] if e["type"] == "kb_entry"]
    assert kb and kb[0]["file_meta"][0]["title"] == "Austria itinerary"


def test_private_skip_ai_drop_carries_file_meta(client):
    r = client.post(
        "/drop",
        data={"text": "secret", "private_skip_ai": "true"},
        files={"file": ("lease.docx", ooxml_bytes(), "application/octet-stream")},
    )
    [entry] = r.json()["entries"]
    assert entry["file_meta"][0]["author"] == "Jane Landlord"


# --------------------------------------------------------------- backfill


def test_backfill_dry_run_then_apply(client, tmp_path):
    folder = tmp_path / "kb" / "docs"
    (folder / "assets").mkdir(parents=True)
    (folder / "assets" / "old.pdf").write_bytes(pdf_bytes(created=b"(D:20260512080000-04'00')"))
    note = folder / "old-doc.md"
    note.write_text("---\nlinks: []\n---\n# Old doc\n\nSome itinerary.\n\n[asset](assets/old.pdf)\n")
    get_journal_store().save(date(2026, 5, 12), "Trip day.")
    original = note.read_text()
    dry = client.post("/kb/files/backfill-meta").json()
    assert dry["dry_run"] is True and dry["count"] == 1 and dry["changes"][0]["days"] == ["2026-05-12"]
    assert note.read_text() == original
    assert on_day_targets("note:docs/old-doc") == []
    applied = client.post("/kb/files/backfill-meta?dry_run=false").json()
    assert applied["count"] == 1 and applied["changes"][0]["new_edges"] == 1
    text = note.read_text()
    assert text.count("🗂") == 1 and '"Austria itinerary"' in text and "old.pdf" in text
    assert on_day_targets("note:docs/old-doc") == ["journal:2026-05-12"]
    assert "note:docs/old-doc" in hit_ids("Naitik")
    assert client.post("/kb/files/backfill-meta?dry_run=false").json()["count"] == 0


# --- 2026-11-05: text files are READ at the drop step ------------------------


def test_markdown_drop_is_read_not_no_description():
    from quintacle_core.nodes.kb.drop import describe_drop

    text = "# Austria plan\n\nVienna 3 nights, then Salzburg."
    out = describe_drop("chat-answer.md", text.encode())
    assert "no description" not in out and "Vienna 3 nights" in out


def test_text_drop_keeps_user_words_and_caps_huge_files():
    from quintacle_core.nodes.kb.drop import describe_drop

    out = describe_drop("big.txt", b"x" * 50_000, "my notes")
    assert out.startswith("my notes") and "truncated" in out and len(out) < 25_000
