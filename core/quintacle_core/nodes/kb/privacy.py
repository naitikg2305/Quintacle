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


# --- shared filtering helpers (2026-11-05) -----------------------------------
#
# Every model-facing surface filters through these, so "is this node a
# private note?" has one answer everywhere. Only `note:` ids can be private
# (people/places are notes too — `note:<folder>/profile` etc.); every other
# node type (log rows, journal days, todos, events…) is never private.


def note_parts(node_id: str) -> tuple[str, str] | None:
    """(folder, slug) for a `note:<folder>/<slug>` id, else None."""
    kind, _, rest = (node_id or "").partition(":")
    if kind != "note":
        return None
    folder, _, slug = rest.rpartition("/")
    if not folder or not slug:
        return None
    return folder, slug


def is_private_node(store, node_id: str) -> bool:
    """True when `node_id` names a KB note whose frontmatter is private.
    Unknown/stale ids and every non-note id read as not private."""
    parts = note_parts(node_id)
    if parts is None:
        return False
    try:
        return store.is_private(*parts)
    except Exception:
        return False


def private_filter(store):
    """A cached `node_id -> bool` predicate, True for private notes — the
    `exclude` hook retrieval.retrieve()/neighbor_labels() take, so a cloud
    surface's top-k is drawn from public nodes only (never k-then-filter)."""
    cache: dict[str, bool] = {}

    def excluded(node_id: str) -> bool:
        if node_id not in cache:
            cache[node_id] = is_private_node(store, node_id)
        return cache[node_id]

    return excluded


def public_notes_index(store) -> list[dict]:
    """store.notes_index() minus private notes — the titles list the sort /
    drop / record-that suggesters hand a model (which may be cloud: `auto`
    falls back to it), so a private note's title never rides along."""
    return [n for n in store.notes_index() if not store.is_private(n["folder"], n["slug"])]


def without_private_hits(store, hits: list[dict]) -> list[dict]:
    """Drops private notes from a list of retrieval-shaped hits ({id, …,
    neighbors}) AND from each hit's neighbor labels. Defense in depth for a
    result list built without retrieval's `exclude` hook."""
    excluded = private_filter(store)
    out = []
    for h in hits:
        if excluded(h.get("id", "")):
            continue
        if h.get("neighbors"):
            h = {**h, "neighbors": [n for n in h["neighbors"] if not excluded(n.get("id", ""))]}
        out.append(h)
    return out


class PrivacyGate:
    """Per-request gate for assembling model context. `allow_private` is True
    ONLY when the resolved model is local. admit(node_id) is called right
    before a node's content (or title) enters the context: False means leave
    it out (cloud + private); True means include it — and a private note
    that gets in is recorded in `used`, which the chat endpoint returns so
    the frontend can mark that reply and a later cloud handoff strips it."""

    def __init__(self, store, allow_private: bool):
        self.allow_private = bool(allow_private)
        self._excluded = private_filter(store)
        self.used: set[str] = set()

    def is_private(self, node_id: str) -> bool:
        return self._excluded(node_id)

    def hides(self, node_id: str) -> bool:
        return not self.allow_private and self._excluded(node_id)

    def exclude_hook(self):
        """retrieval's `exclude` argument: the private predicate for cloud,
        None for local (nothing hidden)."""
        return None if self.allow_private else self._excluded

    def admit(self, node_id: str) -> bool:
        if not self._excluded(node_id):
            return True
        if not self.allow_private:
            return False
        self.used.add(node_id)
        return True


def private_manual_entry(text: str, filename: str | None = None) -> dict:
    """The "Private, skip AI" drop proposal — pure code, zero model calls:
    one kb_entry with the text verbatim, `private: True`, NO folder (the
    owner picks one in the review card) and a first-line title suggestion
    (the attached file's name when there's no text). Nothing is written —
    the review card's Save commits it like any other kb_entry."""
    text = (text or "").strip()
    first = next((line.strip().lstrip("#").strip() for line in text.splitlines() if line.strip()), "")
    if not first and filename:
        first = filename.rsplit(".", 1)[0]
    return {
        "type": "kb_entry",
        "folder": "",
        "title": first[:60],
        "content": text,
        "links": [],
        PRIVATE_KEY: True,
    }


PRIVATE_MARKER = "private_notes"


def strip_private_turns(messages: list[dict], marker: str = PRIVATE_MARKER) -> tuple[list[dict], int]:
    """The cloud-handoff strip. Every assistant turn that was answered with
    private-note context (its `marker` list non-empty) is removed together
    with the user turn that prompted it — keeping user/assistant alternation
    valid for every provider — except the newest message, which is always
    the question being asked now. Returns (clean messages, number of
    DISTINCT private notes left out). The marker key is removed from every
    returned message (providers reject unknown keys)."""
    drop: set[int] = set()
    left_out: set[str] = set()
    last = len(messages) - 1
    for i, m in enumerate(messages):
        notes = m.get(marker) or []
        if m.get("role") == "assistant" and notes:
            left_out.update(notes)
            drop.add(i)
            if i > 0 and messages[i - 1].get("role") == "user" and i - 1 != last:
                drop.add(i - 1)
    clean = [{k: v for k, v in m.items() if k != marker} for i, m in enumerate(messages) if i not in drop]
    return clean, len(left_out)
