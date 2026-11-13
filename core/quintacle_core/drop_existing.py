"""Does a dropped note already exist? (2026-11-13, owner testing T2.)

Before this, a drop whose folder + title matched an existing note silently
REPLACED it on Save. Now the review card is told about the match and the
owner chooses:
- **Keep both** (the default): saved as a new note under a nearby name the AI
  suggests ("…, revised"), never "(2)". The name is editable.
- **Append** to the existing note: a dated section, history kept.
- **Replace** the existing note's text.

How a match is found (AI suggests, code decides):
- **Same name:** the proposed title slugifies to a note already in that folder.
  Code, always, even with no model.
- **AI:** the model sees the notes already in the folder (title + snippet) and
  may say the drop is a version of one of them. Code keeps its pick only if
  it names a note that is really there.

`QUINTACLE_DROP_MATCH_PROVIDER=off` skips the model (faked tests); the
same-name check still runs.
"""
from __future__ import annotations

import os

from pydantic import BaseModel

from . import clock, llm_dispatch
from .markdown_paths import slugify

PROVIDER_ENV = "QUINTACLE_DROP_MATCH_PROVIDER"
_MAX_CANDIDATES = 40

_SYSTEM = """You compare a NEW note with the notes already in the same folder of a personal knowledge base.

1. same_as: if the new note is another version, revision, or update of ONE existing note (same subject, same
   plan, same document), return that note's slug exactly as listed. If it is about something different, return null.
   Two notes merely on the same topic are NOT the same note; they must be versions of one thing.
2. new_title: a title for keeping the new note as a SEPARATE note next to the existing ones. Keep it close
   to the new note's title but distinguishable by what is different about it (e.g. "revised", the source, a
   date, the scope). Never add a number like "(2)". It must differ from every existing title.
3. reason: one short sentence.

Return JSON only."""


class _Match(BaseModel):
    same_as: str | None = None
    new_title: str = ""
    reason: str = ""


def _fallback_title(title: str, taken: set[str]) -> str:
    base = f"{title}, {clock.today().strftime('%b %-d %Y')}"
    if slugify(base) not in taken:
        return base
    return f"{title}, {clock.now().strftime('%b %-d %Y %-I.%M %p')}"


def match_existing(store, folder: str, title: str, content: str, *, provider: str | None = None, use_model: bool = True) -> dict | None:
    """The card's `existing_match` (+ `alt_title`) for a proposed kb_entry, or
    None when the folder has nothing it could be."""
    rows = store.list_entries_meta(folder) if folder else []
    rows = [r for r in rows if not r["slug"].startswith("_")]
    if not rows:
        return None
    by_slug = {r["slug"]: r for r in rows}
    taken = set(by_slug)
    exact = by_slug.get(slugify(title))

    ai: _Match | None = None
    if use_model and os.environ.get(PROVIDER_ENV, "").strip().lower() != "off":
        listing = "\n".join(f"- slug: {r['slug']} | title: {r['title']} | starts: {r['snippet'][:120]}" for r in rows[:_MAX_CANDIDATES])
        user = f"EXISTING NOTES in {folder}:\n{listing}\n\nNEW NOTE\ntitle: {title}\ncontent:\n{(content or '')[:1500]}"
        try:
            ai = llm_dispatch.parse_structured(_SYSTEM, user, _Match, provider=provider, max_tokens=512).parsed
        except Exception:
            ai = None  # a model failure never blocks the drop; same-name still holds

    alt = (ai.new_title.strip() if ai and ai.new_title else "")
    if not alt or slugify(alt) in taken or "(2)" in alt:
        alt = _fallback_title(title, taken)

    if exact is not None:
        target, by = exact, "same_name"
    elif ai and ai.same_as and ai.same_as.strip() in by_slug:
        target, by = by_slug[ai.same_as.strip()], "ai"
    else:
        return None
    return {
        "match": {
            "folder": "/".join(slugify(p) for p in folder.split("/") if p.strip()),
            "slug": target["slug"],
            "title": target["title"],
            "by": by,
            "reason": (ai.reason.strip() if ai and ai.reason else ""),
        },
        "alt_title": alt,
    }


def apply_to_proposal(store, entry: dict, *, provider: str | None = None) -> None:
    """Annotate one kb_entry proposal in place. A same-name match switches the
    card's title to the nearby name up front, so Save can never overwrite by
    accident; the owner picks Append / Replace to touch the existing note."""
    # A private card never reaches a model here (same-name check only).
    found = match_existing(store, entry.get("folder") or "", entry.get("title") or "", entry.get("content") or "",
                           provider=provider, use_model=not entry.get("private"))
    if not found:
        return
    entry["existing_match"] = found["match"]
    entry["alt_title"] = found["alt_title"]
    entry["on_conflict"] = "new"
    if found["match"]["by"] == "same_name":
        entry["existing_match"]["original_title"] = entry.get("title") or ""
        entry["title"] = found["alt_title"]
