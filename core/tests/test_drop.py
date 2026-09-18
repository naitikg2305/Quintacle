import io

from docx import Document

from quintacle_core.nodes.kb.drop import describe_drop


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_docx_text_is_extracted_and_combined_with_user_description():
    data = _make_docx_bytes(["Lease agreement for 123 Main St.", "Move-in date: Oct 1."])

    description = describe_drop("lease.docx", data, user_description="my new lease")

    assert "my new lease" in description
    assert "Lease agreement for 123 Main St." in description
    assert "Move-in date: Oct 1." in description


def test_docx_with_no_user_description_still_extracts_text():
    data = _make_docx_bytes(["Just the document content."])

    description = describe_drop("notes.docx", data)

    assert "Just the document content." in description


def test_stl_with_no_description_falls_back_to_filename_note():
    description = describe_drop("bracket.stl", b"not-real-stl-bytes")

    assert "bracket.stl" in description


def test_stl_with_user_description_uses_it_verbatim():
    description = describe_drop("bracket.stl", b"not-real-stl-bytes", user_description="phone mount bracket v2")

    assert description == "phone mount bracket v2"
