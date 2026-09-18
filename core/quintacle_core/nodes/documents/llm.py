from __future__ import annotations

import anthropic
from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL

_DOC_TYPES = "lease, id, passport, immigration, insurance, medical, financial, warranty, or another short lowercase category"


class DocumentEstimate(BaseModel):
    suggested_name: str
    doc_type: str
    issued_date: str | None = None  # YYYY-MM-DD if stated/visible
    expiry_date: str | None = None  # YYYY-MM-DD if stated/visible
    notes: str = ""


def structure_document(description: str) -> DocumentEstimate:
    """Takes an already-extracted description — vision caption, native PDF
    read, DOCX text, or a typed description (kb/drop.py's describe_drop()
    already handles dispatching by file type; this is the one-step-later
    "structure it" pass, reused so image/PDF/DOCX extraction isn't
    duplicated here) — and turns it into a Document Vault entry: name,
    doc_type, issued/expiry dates if stated, brief notes."""
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=512,
        system=(
            "Turn this into a Document Vault entry: a short suggested_name, doc_type "
            f"({_DOC_TYPES}), issued_date and expiry_date as YYYY-MM-DD if stated or visible in "
            "the text (null if not — don't guess), and brief notes (what it's for, key details)."
        ),
        messages=[{"role": "user", "content": description}],
        output_format=DocumentEstimate,
    )
    return response.parsed_output
