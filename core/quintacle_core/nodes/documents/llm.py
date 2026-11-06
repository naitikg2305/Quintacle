from __future__ import annotations

import anthropic
from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL
from ...llm_dispatch import parse_structured
from ...max_backend import cloud_client  # noqa: F401  (kept importable; monkeypatched by older tests)

_DOC_TYPES = "lease, id, passport, immigration, insurance, medical, financial, warranty, or another short lowercase category"


class DocumentEstimate(BaseModel):
    suggested_name: str
    doc_type: str
    issued_date: str | None = None  # YYYY-MM-DD if stated/visible
    expiry_date: str | None = None  # YYYY-MM-DD if stated/visible
    notes: str = ""


def structure_document(description: str, provider: str | None = None) -> DocumentEstimate:
    """Takes an already-extracted description — vision caption, native PDF
    read, DOCX text, or a typed description (kb/drop.py's describe_drop()
    already handles dispatching by file type; this is the one-step-later
    "structure it" pass, reused so image/PDF/DOCX extraction isn't
    duplicated here) — and turns it into a Document Vault entry: name,
    doc_type, issued/expiry dates if stated, brief notes.

    2026-11-06: routed through llm_dispatch.parse_structured like every
    other structure_* text extractor (local first) — a document photo's
    text now comes from LOCAL OCR, and it shouldn't then be shipped to the
    cloud just to be structured. /drop passes provider="local" for
    image-derived text when the image policy is local."""
    return parse_structured(
        (
            "Turn this into a Document Vault entry: a short suggested_name, doc_type "
            f"({_DOC_TYPES}), issued_date and expiry_date as YYYY-MM-DD if stated or visible in "
            "the text (null if not — don't guess), and brief notes (what it's for, key details)."
        ),
        description,
        DocumentEstimate,
        provider=provider,
        max_tokens=512,
    ).parsed
