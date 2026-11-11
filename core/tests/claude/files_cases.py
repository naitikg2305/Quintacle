"""FILE drops beyond plain text PDFs — written once, run by BOTH live suites
(tests/claude/local = qwen via Ollama, tests/claude/subscription_or_api =
Claude via Max). Each check takes (client, provider) and returns the /drop
response. Expectations are the RIGHT product behaviour, fixed up front; a
failure is a finding about the model/code, never a reason to re-fit.

Every file is built in-test (python-docx / openpyxl / python-pptx / pypdf /
Pillow from core/.venv); a missing optional lib skips with the reason.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

from tests.claude.harness import drop, first, folder_of, make_pdf, types

NO_DESC = "no description given"


# ------------------------------------------------------------------ inputs

RESUME = [
    "Naitik Gupta",
    "Software Engineer | Washington, DC | naitik@example.com",
    "Experience: Minfy, Software Engineer 2025-present",
    "Built a serverless document-processing pipeline on AWS Lambda and Step Functions.",
    "Led migration of a customer data platform from on-prem Postgres to Aurora.",
    "Experience: University of Maryland, Undergraduate Research Assistant 2023-2024",
    "Education: University of Maryland, B.S. Computer Science, 2024",
    "Skills: Python, FastAPI, TypeScript, React, AWS, SQLite",
]

# (category, monthly amount) — the line items the description must reflect.
BUDGET_ROWS = [
    ("Rent", 1850),
    ("Groceries", 420),
    ("Car insurance", 138),
    ("Gym membership", 45),
    ("Internet", 70),
    ("Savings transfer", 600),
]
BUDGET_ITEMS = [name for name, _ in BUDGET_ROWS]

RAFT_MD_IMAGE = "raft_roles.png"  # real-world name: underscore, as a phone/OS saves it
RAFT_MD = (
    "# Raft roles cheat sheet\n\n"
    "Every server is a follower, a candidate, or the leader. A follower that hears no "
    "heartbeat before its randomized election timeout becomes a candidate and asks for votes.\n\n"
    f"![Raft roles diagram]({RAFT_MD_IMAGE})\n\n"
    "The leader appends entries and commits once a majority has replicated them.\n"
)
RAFT_DIAGRAM_LINES = ["Follower -> Candidate -> Leader", "timeout     majority vote"]

META_PDF_LINES = [
    "Reading notes - Designing Data-Intensive Applications, chapter 9",
    "Consistency and consensus: linearizability vs. causal ordering.",
    "Total order broadcast is equivalent to consensus.",
    "Two-phase commit blocks if the coordinator crashes; ZooKeeper and etcd implement consensus.",
    "Takeaway: use a coordination service instead of rolling my own leader election.",
]
META_TITLE = "DDIA chapter 9 reading notes"
META_AUTHOR = "Naitik Gupta"
META_CREATED_PDF = "D:20260512093000-04'00'"  # 09:30 Eastern, nowhere near a day boundary
META_DAY = "2026-05-12"

SCAN_LINES = [
    "Lecture 9 - Consistent hashing",
    "Keys and servers are placed on the same hash ring.",
    "Each key belongs to the next server clockwise.",
    "Adding a server only moves the keys of one arc.",
    "Virtual nodes smooth out the load imbalance.",
]

DECK_SLIDES = [
    ("Q3 side-project review", "Quintacle progress, July to September"),
    ("Shipped", "Local OCR pipeline, file metadata baking, graph on_day edges"),
    ("Next quarter", "Phone shell, local VLM, weekly focus planning"),
]


# ------------------------------------------------------------------ builders


def _docx_by_hand(paragraphs: list[str]) -> bytes:
    """Minimal valid WordprocessingML package (used only if python-docx is absent)."""
    from xml.sax.saxutils import escape

    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(p)}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}</w:body></w:document>",
        )
    return buf.getvalue()


def make_docx(paragraphs: list[str]) -> bytes:
    try:
        from docx import Document
    except ImportError:
        return _docx_by_hand(paragraphs)
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_xlsx(rows: list[tuple[str, int]]) -> bytes:
    try:
        import openpyxl
    except ImportError:
        pytest.skip("openpyxl isn't installed in core/.venv — can't build the .xlsx budget sheet")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Monthly 2027"
    ws.append(["Category", "Monthly ($)", "Yearly ($)"])
    for name, amount in rows:
        ws.append([name, amount, amount * 12])
    ws.append(["Total", sum(a for _, a in rows), sum(a for _, a in rows) * 12])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pptx_by_hand(slides: list[tuple[str, str]]) -> bytes:
    """Minimal PresentationML package — title + body placeholder per slide,
    the same XML shape python-pptx writes (used only if python-pptx is absent;
    core reads .pptx with stdlib zipfile/ElementTree, so it isn't a dependency)."""
    from xml.sax.saxutils import escape

    ns = (
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
    )

    def shape(i: int, ph: str, text: str) -> str:
        return (
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="s{i}"/><p:cNvSpPr/><p:nvPr><p:ph {ph}/></p:nvPr></p:nvSpPr>'
            f'<p:spPr/><p:txBody><a:bodyPr/><a:p><a:r><a:t>{escape(text)}</a:t></a:r></a:p></p:txBody></p:sp>'
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        overrides = "".join(
            f'<Override PartName="/ppt/slides/slide{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for n in range(1, len(slides) + 1)
        )
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            f"{overrides}</Types>",
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
            "</Relationships>",
        )
        ids = "".join(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>' for n in range(1, len(slides) + 1))
        z.writestr("ppt/presentation.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation {ns}><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>')
        rels = "".join(
            f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{n}.xml"/>'
            for n in range(1, len(slides) + 1)
        )
        z.writestr("ppt/_rels/presentation.xml.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for n, (title, body) in enumerate(slides, start=1):
            z.writestr(
                f"ppt/slides/slide{n}.xml",
                f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld {ns}><p:cSld><p:spTree>'
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
                + shape(2, 'type="title"', title) + shape(3, 'idx="1"', body) +
                "</p:spTree></p:cSld></p:sld>",
            )
    return buf.getvalue()


def make_pptx(slides: list[tuple[str, str]]) -> bytes:
    try:
        from pptx import Presentation
    except ImportError:
        return _pptx_by_hand(slides)
    prs = Presentation()
    for title, body in slides:
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = title
        s.placeholders[1].text = body
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _text_png(lines: list[str], size: tuple[int, int] = (900, 260), font_px: int = 34) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans.ttf", font_px)
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((40, 40 + int(font_px * 1.6) * i), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def make_diagram_png() -> bytes:
    return _text_png(RAFT_DIAGRAM_LINES)


def make_meta_pdf() -> bytes:
    """A text PDF whose Info dict carries Title/Author/CreationDate."""
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(META_PDF_LINES))))
    w.add_metadata({"/Title": META_TITLE, "/Author": META_AUTHOR, "/CreationDate": META_CREATED_PDF})
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def make_scanned_pdf() -> bytes:
    """An image-only PDF (no text layer): one rendered page saved by Pillow,
    which embeds it as a JPEG — what a phone scanner app produces."""
    from PIL import Image

    page = Image.open(io.BytesIO(_text_png(SCAN_LINES, size=(1700, 900), font_px=44))).convert("RGB")
    buf = io.BytesIO()
    page.save(buf, "PDF", resolution=200.0)
    return buf.getvalue()


# ------------------------------------------------------------------ helpers


def _data_dir() -> Path:
    import quintacle_core.api as api_module

    return Path(api_module.DATA_DIR)


def _content(entry: dict) -> str:
    return entry.get("content") or ""


def _real_description(entry: dict) -> None:
    c = _content(entry)
    assert c.strip(), "empty proposal content"
    assert NO_DESC not in c.lower(), f"the file was never read: {c[:200]!r}"


def save_with_assets(c, entry: dict, files: list[tuple[str, bytes, str]]) -> dict:
    """Commit a kb_entry proposal exactly like the frontend's Save does
    (lib/entries.ts commitDropEntries -> /kb/entries/with-asset with the
    dropped file + its extra files as repeated `files` parts)."""
    form = {
        "folder": entry.get("folder") or "Inbox",
        "title": entry.get("title") or "Untitled",
        "content": _content(entry),
        "links": ",".join(entry.get("links") or []),
    }
    r = c.post("/kb/entries/with-asset", data=form, files=[("files", f) for f in files])
    assert r.status_code == 200, f"/kb/entries/with-asset {r.status_code}: {r.text[:400]}"
    return r.json()


def _note_path(saved: dict) -> Path:
    return _data_dir() / "kb" / saved["folder"] / f"{saved['slug']}.md"


def _on_day_targets(note_id: str) -> list[str]:
    from quintacle_core.graph import get_graph_store

    rows = get_graph_store().conn.execute(
        "SELECT target_id FROM edges WHERE source_id = ? AND kind = 'on_day'", (note_id,)
    ).fetchall()
    return sorted(r["target_id"] for r in rows)


# ------------------------------------------------------------------ checks


def check_docx_resume(c, provider):
    """A resume is the owner's own career writing, not an ID/contract: KB note (never the vault), described from its real text (Minfy)."""
    r = drop(c, data=make_docx(RESUME), filename="resume_2026.docx", provider=provider)
    assert "document_entry" not in types(r), f"a resume isn't a vault document: {types(r)}"
    e = first(r, "kb_entry")
    _real_description(e)
    assert "minfy" in _content(e).lower(), f"description doesn't reflect the resume: {_content(e)[:300]!r}"
    assert not folder_of(e).startswith("fun/travel"), e.get("folder")
    return r


def check_xlsx_budget(c, provider):
    """A budget sheet is KB reference data; its description must come from the cells (>=2 real line items), not the filename."""
    r = drop(c, data=make_xlsx(BUDGET_ROWS), filename="budget_2027.xlsx", provider=provider)
    assert "document_entry" not in types(r), types(r)
    e = first(r, "kb_entry")
    _real_description(e)
    body = _content(e).lower()
    hits = [k for k in BUDGET_ITEMS if k.lower() in body]
    assert len(hits) >= 2, f"description doesn't reflect the sheet's rows (found {hits}): {_content(e)[:300]!r}"
    return r


def check_pptx_deck(c, provider):
    """A slide deck is KB material; its description must come from the slide text, not a 'no description' placeholder."""
    r = drop(c, data=make_pptx(DECK_SLIDES), filename="q3_review.pptx", provider=provider)
    e = first(r, "kb_entry")
    _real_description(e)
    body = _content(e).lower()
    assert any(k in body for k in ("ocr", "phone shell", "on_day", "metadata", "vlm")), _content(e)[:300]
    return r


def check_md_with_local_image(c, provider):
    """An .md dropped with the image it embeds is one self-contained note: image copied into assets/, note references it, .md link still resolves."""
    png = make_diagram_png()
    r = c.post(
        "/drop",
        data={"text": "", "provider": provider},
        files={"file": ("raft_cheatsheet.md", RAFT_MD.encode(), "text/markdown"), "file2": (RAFT_MD_IMAGE, png, "image/png")},
    )
    assert r.status_code == 200, f"/drop {r.status_code}: {r.text[:400]}"
    r = r.json()
    e = first(r, "kb_entry")
    _real_description(e)
    assert "raft" in _content(e).lower() or "raft" in (e.get("title") or "").lower(), e

    saved = save_with_assets(c, e, [("raft_cheatsheet.md", RAFT_MD.encode(), "text/markdown"), (RAFT_MD_IMAGE, png, "image/png")])
    folder_dir = _data_dir() / "kb" / saved["folder"]
    image_assets = [a for a in saved["assets"] if a.lower().endswith(".png")]
    md_assets = [a for a in saved["assets"] if a.lower().endswith(".md")]
    assert image_assets, f"the image wasn't attached: {saved['assets']}"
    assert md_assets, f"the markdown file wasn't attached: {saved['assets']}"
    img_path = folder_dir / image_assets[0]
    assert img_path.is_file() and img_path.read_bytes() == png, f"image copy missing/altered at {img_path}"

    note = _note_path(saved).read_text(encoding="utf-8")
    assert image_assets[0] in note, f"saved note doesn't reference {image_assets[0]}:\n{note[-600:]}"

    md_path = folder_dir / md_assets[0]
    stored_md = md_path.read_text(encoding="utf-8")
    links = re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", stored_md)
    assert links, f"stored markdown lost its image embed:\n{stored_md}"
    for link in links:
        target = (md_path.parent / link).resolve()
        assert target.is_file(), f"stored markdown's image link {link!r} is broken (no {target})"
        assert target.read_bytes() == png, f"{link!r} resolves to a different file"
    return r


def check_pdf_file_metadata(c, provider):
    """Embedded title/author/created are facts nobody typed: proposal + saved note carry the 🗂 line, and an on_day edge links the creation day."""
    from quintacle_core.nodes.kb.file_meta import is_file_meta_line

    jr = c.post(f"/journal/{META_DAY}", content="Read DDIA chapter 9 on the train.", headers={"Content-Type": "text/plain"})
    assert jr.status_code == 200, jr.text
    pdf = make_meta_pdf()
    r = drop(c, data=pdf, filename="ddia_ch9_notes.pdf", provider=provider)
    assert "document_entry" not in types(r), types(r)
    e = first(r, "kb_entry")
    _real_description(e)

    metas = e.get("file_meta") or []
    assert metas, f"proposal carries no file_meta: {list(e)}"
    m = metas[0]
    assert m.get("author") == META_AUTHOR, m
    assert (m.get("created") or "")[:10] == META_DAY, m
    assert m.get("title") == META_TITLE, m
    expected = f"created {META_DAY} by {META_AUTHOR}"
    assert expected in (m.get("line") or ""), m.get("line")
    assert f'"{META_TITLE}"' in (m.get("line") or ""), m.get("line")

    saved = save_with_assets(c, e, [("ddia_ch9_notes.pdf", pdf, "application/pdf")])
    note = _note_path(saved).read_text(encoding="utf-8")
    meta_lines = [l for l in note.splitlines() if is_file_meta_line(l)]
    assert meta_lines, f"saved note has no 🗂 line:\n{note[-600:]}"
    assert any(expected in l for l in meta_lines), meta_lines

    note_id = f"note:{saved['folder']}/{saved['slug']}"
    assert f"journal:{META_DAY}" in _on_day_targets(note_id), f"no on_day edge {note_id} -> journal:{META_DAY}"
    return r


def check_scanned_pdf(c, provider):
    """An image-only PDF must still be read (local mode: local OCR, never cloud), and the proposal reflects the scanned words."""
    pdf = make_scanned_pdf()
    r = drop(c, data=pdf, filename="lecture9_scan.pdf", provider=provider)
    assert not r.get("local_unavailable"), f"scan couldn't be read: {r.get('local_unavailable')}"
    if provider == "local":
        p = r.get("pipeline") or ""
        assert p != "cloud" and "ocr" in p, f"local mode must read the scan by local OCR; pipeline={r.get('pipeline')!r}"
    assert "document_entry" not in types(r), types(r)
    e = first(r, "kb_entry")
    _real_description(e)
    body = (_content(e) + " " + (e.get("title") or "")).lower()
    assert "hash" in body, f"description doesn't reflect the scanned text: {_content(e)[:300]!r}"
    return r


ALL = [
    check_docx_resume,
    check_xlsx_budget,
    check_pptx_deck,
    check_md_with_local_image,
    check_pdf_file_metadata,
    check_scanned_pdf,
]
