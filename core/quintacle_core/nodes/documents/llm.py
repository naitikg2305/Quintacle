from __future__ import annotations

import re
from datetime import date

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
    est = parse_structured(
        (
            "Turn this into a Document Vault entry: a short suggested_name, doc_type "
            f"({_DOC_TYPES}), issued_date and expiry_date as YYYY-MM-DD if stated or visible in "
            "the text (null if not — don't guess; 'Date of expiration', 'Expires', 'Exp', "
            "'Valid until' are the expiry_date, 'Date of issue', 'Issued' the issued_date), and "
            "brief notes (what it's for, key details)."
        ),
        description,
        DocumentEstimate,
        provider=provider,
        max_tokens=512,
    ).parsed
    return apply_labeled_dates(est, description)


# --- Deterministic issue/expiry extraction (2026-11-11 live finding: a
# passport photo through the cloud came back with expiry_date=None). A date
# printed next to an issue/expiry label is read by code and wins over the
# model; the model's value is kept only where code finds nothing. ---------

_MONTHS = {name: i + 1 for i, name in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_DATE_RE = re.compile(
    r"(?P<iso>(?P<iy>\d{4})[-/.](?P<im>\d{1,2})[-/.](?P<id>\d{1,2}))"
    rf"|(?P<dmy>(?P<dd>\d{{1,2}})(?:st|nd|rd|th)?[\s\-/]*{_MON.replace('(', '(?P<dm>', 1)}[\s,\-/]*(?P<dy>\d{{4}}))"
    rf"|(?P<mdy>{_MON.replace('(', '(?P<mm>', 1)}[\s\-/]*(?P<md>\d{{1,2}})(?:st|nd|rd|th)?[\s,\-/]+(?P<my>\d{{4}}))"
    r"|(?P<num>(?P<n1>\d{1,2})[-/.](?P<n2>\d{1,2})[-/.](?P<ny>\d{4}))",
    re.IGNORECASE,
)
_EXPIRY_LABEL = re.compile(
    r"\b(?:date\s+of\s+expir(?:y|ation)|expir(?:y|ation|es|ed|ing)(?:\s+date|\s+on)?|exp\b\.?(?:\s*date)?"
    r"|valid\s+(?:until|thru|through|till|to)|good\s+(?:thru|through)|renew\s+by)",
    re.IGNORECASE,
)
_ISSUE_LABEL = re.compile(
    r"\b(?:date\s+of\s+issue|issue\s+date|issued(?:\s+on)?|doi\b|valid\s+from)",
    re.IGNORECASE,
)
# Between a label and its date: punctuation/markdown, or a short "(DD MMM YYYY)"-style hint.
_GAP = re.compile(r"(?:[\s:*_|=\-–—>]|\([^)\n]{0,20}\))*")
# Passport (TD3) MRZ line 2: doc no, check, nationality, DOB, check, sex, EXPIRY YYMMDD.
_MRZ_TD3 = re.compile(r"[A-Z0-9<]{9}\d[A-Z<]{3}\d{6}\d[MFX<](\d{2})(\d{2})(\d{2})\d")


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _date_from_match(m: re.Match) -> str | None:
    if m.group("iso"):
        return _iso(int(m.group("iy")), int(m.group("im")), int(m.group("id")))
    if m.group("dmy"):
        return _iso(int(m.group("dy")), _MONTHS[m.group("dm").lower()[:3]], int(m.group("dd")))
    if m.group("mdy"):
        return _iso(int(m.group("my")), _MONTHS[m.group("mm").lower()[:3]], int(m.group("md")))
    a, b, y = int(m.group("n1")), int(m.group("n2")), int(m.group("ny"))
    # US default (MM/DD/YYYY); a first part > 12 can only be a day.
    return _iso(y, b, a) if a > 12 else _iso(y, a, b)


def _labeled_date(label: re.Pattern, text: str) -> str | None:
    for hit in label.finditer(text):
        gap = _GAP.match(text, hit.end())
        m = _DATE_RE.match(text, gap.end() if gap else hit.end())
        if m:
            value = _date_from_match(m)
            if value:
                return value
    return None


def _mrz_expiry(text: str) -> str | None:
    m = _MRZ_TD3.search(re.sub(r"[ \t]", "", text))
    if not m:
        return None
    return _iso(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))  # passports expire after 2000


def labeled_document_dates(text: str) -> tuple[str | None, str | None]:
    """(issued, expiry) read deterministically from labels in the text
    ('Date of issue: 02 JAN 2020', 'Expires 01/2030'-style full dates,
    'valid until ...'), falling back to a passport MRZ for expiry."""
    return _labeled_date(_ISSUE_LABEL, text), _labeled_date(_EXPIRY_LABEL, text) or _mrz_expiry(text)


def apply_labeled_dates(est: DocumentEstimate, text: str) -> DocumentEstimate:
    issued, expiry = labeled_document_dates(text or "")
    if issued:
        est.issued_date = issued
    if expiry:
        est.expiry_date = expiry
    return est
