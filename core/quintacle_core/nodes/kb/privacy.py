"""The `private` note flag — the one shared definition every surface checks.

Owner rule (2026-11-05): a KB note with `private: true` in its frontmatter
NEVER reaches a cloud model and is NEVER proposed for publishing. Concretely:

- local chat (local:* models) MAY pull it as context;
- cloud chat, the MCP server (its clients are cloud models), the website
  suggester and the career-record updater MUST NOT see it;
- a chat that pulled private notes locally and then escalates to cloud has
  them stripped from the handoff, with a visible notice;
- the owner always sees it (Browse, own graph view, editor).

Unlike the Vault this is not encryption — it is an AI-visibility boundary.
Everything that filters notes for a model surface goes through these helpers
so there is exactly one definition of "private".
"""
from __future__ import annotations

PRIVATE_KEY = "private"


def is_private_meta(meta: dict | None) -> bool:
    """True when a note's frontmatter marks it private. Accepts real booleans
    and the obvious hand-typed spellings (`private: yes`, `"true"`)."""
    if not meta:
        return False
    value = meta.get(PRIVATE_KEY)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "on"}
    return bool(value) if isinstance(value, int) else False


def note_node_id(folder_slug: str, slug: str) -> str:
    """Graph/retrieval id for a KB note (`note:<slugified folder>/<slug>`)."""
    return f"note:{folder_slug}/{slug}"
