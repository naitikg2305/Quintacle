"""Build A, step 4 — the one model step: per record entry, propose new
bullets from that hub's work-log lines. Local-first through
llm_dispatch.parse_structured (provider override = the usual step-back
"redo with cloud"). Everything around the call is code: the source lines
are numbered and handed over, the `[WL YYYY-MM-DD]` tag date is computed
from the cited lines, and validate.check_bullet rejects anything with a
number/date/employer/title/degree the sources and record don't contain.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from ...llm_dispatch import parse_structured
from .record import DETAIL, PHRASING, strip_tags
from .validate import check_bullet

MAX_PROMPT_LINES = 240

SYSTEM = """You update a person's master career record from their own work logs.
You get ONE record entry (may be empty for a new entry) and numbered work-log lines.
Propose a few NEW bullets (0-6) capturing work in the log lines that the entry does not already say.

Rules — these are checked in code and violations are thrown away:
- Use ONLY facts in the numbered lines or the existing entry. Never invent employers,
  job titles, dates, degrees, numbers, metrics, team sizes or outcomes.
- Copy any number exactly as written in the lines. If a line has no number, write none.
- Do not restate something the entry already says.
- section "phrasing" = one concise resume-style bullet (past tense, starts with a verb);
  section "detail" = a longer factual what-I-did bullet.
- sources = the line numbers each bullet is based on (at least one).
- No provenance tags, no markdown headings, one sentence-ish per bullet.
- If nothing new is worth adding, return an empty list."""


class DraftBullet(BaseModel):
    text: str
    section: Literal["phrasing", "detail"]
    sources: list[int] = Field(default_factory=list)


class EntryDraft(BaseModel):
    bullets: list[DraftBullet] = Field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def number_lines(sessions: list[dict]) -> list[dict]:
    """Flatten a group's sessions into numbered {n, date, text} lines, the
    newest last; capped (oldest dropped first) so a long backlog can't blow
    the local model's context."""
    out = [{"date": s["date"], "text": line} for s in sessions for line in s["lines"]]
    out = out[-MAX_PROMPT_LINES:]
    for i, line in enumerate(out, start=1):
        line["n"] = i
    return out


def draft_group(
    *,
    hub_title: str,
    entry_title: str | None,
    entry_text: str,
    existing_bullets: list[str],
    sessions: list[dict],
    employers: set[str],
    provider: str | None = None,
) -> dict:
    """{bullets: [...accepted], rejected: [...with reasons], lines: [...]}.
    Accepted bullet = {text, section, date, sources: [{n, date, text}]}."""
    lines = number_lines(sessions)
    if not lines:
        return {"bullets": [], "rejected": [], "lines": []}
    entry_block = entry_text.strip() or f"(no entry yet — work for {hub_title})"
    user = (
        f"Hub: {hub_title}\nRecord entry: {entry_title or '(new entry)'}\n\n"
        f"=== Existing entry ===\n{entry_block}\n\n=== Work-log lines ===\n"
        + "\n".join(f"[{x['n']}] ({x['date']}) {x['text']}" for x in lines)
    )
    result = parse_structured(SYSTEM, user, EntryDraft, provider=provider, max_tokens=2048)
    by_n = {x["n"]: x for x in lines}
    corpus = entry_text + "\n" + "\n".join(x["text"] for x in lines)
    existing = {_norm(b) for b in existing_bullets}
    accepted, rejected, seen = [], [], set()
    for b in result.parsed.bullets:
        text = re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", strip_tags(b.text)).lstrip("-•* ").strip()
        if not text:
            continue
        cited = [by_n[n] for n in b.sources if n in by_n]
        reasons = []
        if not cited:
            reasons.append("cites no source line")
        if _norm(text) in existing or _norm(text) in seen:
            reasons.append("already in the record")
        reasons += check_bullet(text, corpus, employers)
        item = {
            "text": text,
            "section": b.section if b.section in (PHRASING, DETAIL) else PHRASING,
            # The tag date is computed, never model-chosen: the newest log
            # day the bullet cites.
            "date": max(x["date"] for x in cited) if cited else max(x["date"] for x in lines),
            "sources": [{"n": x["n"], "date": x["date"], "text": x["text"]} for x in cited],
        }
        if reasons:
            rejected.append({**item, "reasons": reasons})
        else:
            seen.add(_norm(text))
            accepted.append(item)
    return {"bullets": accepted, "rejected": rejected, "lines": lines, "provider_used": result.provider_used}
