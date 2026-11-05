"""Entity hubs (`Career/<Employer>`, `Projects/<Name>`) as the career
updaters see them — the deterministic alias table and hub -> record-entry
mapping. Nothing here is ever model-decided.

A hub is a KB note that is either directly in the `career` / `projects`
root folder, or the folder-hub pattern one level down (`Projects/Quintacle/
quintacle.md` — the note's slug equals its folder's last segment). Deeper
documents under a hub folder are NOT hubs (a note titled "Design" must not
become an alias that blocks every mention of the word). The record note
itself is never a hub.

Per-hub fields (stored in the note's `fields`, written without restamping
`edited` — KBStore.set_fields):

  record_entry   "7.7"  explicit record entry this hub's work logs fold into
  public         bool   only `public: true` hubs may appear on the website
  public_name    str    the name the site uses (default: the hub title)
  public_repo    str    the repo link the site may show
  public_slug    str    website file slug (default: slugify(public_name))

Company work defaults to NOT public: an absent `public` is False.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ...graph import title_mentioned
from ...markdown_paths import slugify
from ..kb.privacy import is_private_meta
from .record import ParsedRecord

HUB_ROOTS = ("career", "projects")
HUB_FIELDS = ("record_entry", "public", "public_name", "public_repo", "public_slug")


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "on"}
    return bool(value) if isinstance(value, int) else False


@dataclass
class Hub:
    folder: str
    slug: str
    title: str
    kind: str  # "career" | "projects"
    private: bool
    record_entry: str | None
    public: bool
    public_name: str
    public_repo: str
    public_slug: str

    @property
    def id(self) -> str:
        return f"note:{self.folder}/{self.slug}"

    def to_dict(self) -> dict:
        return {**asdict(self), "id": self.id}


def is_hub_location(folder: str, slug: str) -> bool:
    parts = folder.split("/")
    if parts[0] not in HUB_ROOTS:
        return False
    return len(parts) == 1 or (len(parts) == 2 and parts[1] == slug)


def list_hubs(kb, record_location: tuple[str, str] | None = None) -> list[Hub]:
    """Every hub, private ones included (callers decide; the UI shows them
    greyed out, the updaters skip them)."""
    hubs = []
    for n in kb.notes_index():
        if not is_hub_location(n["folder"], n["slug"]):
            continue
        if record_location and (n["folder"], n["slug"]) == record_location:
            continue
        meta = kb.read_meta(n["folder"], n["slug"]) or {}
        fields = meta.get("fields") or {}

        def get(key):
            return fields.get(key, meta.get(key))

        public_name = str(get("public_name") or "").strip() or n["title"]
        record_entry = get("record_entry")
        hubs.append(
            Hub(
                folder=n["folder"],
                slug=n["slug"],
                title=n["title"],
                kind=n["folder"].split("/", 1)[0],
                private=is_private_meta(meta),
                record_entry=str(record_entry).strip() if record_entry not in (None, "") else None,
                public=_truthy(get("public")),
                public_name=public_name,
                public_repo=str(get("public_repo") or "").strip(),
                public_slug=str(get("public_slug") or "").strip() or slugify(public_name),
            )
        )
    return sorted(hubs, key=lambda h: (h.kind, h.title.lower()))


def map_hub(hub: Hub, rec: ParsedRecord | None) -> dict:
    """Deterministic hub -> record entry:
    1. an explicit `record_entry` field naming an entry that exists;
    2. exactly one entry whose title mentions the hub title (whole word);
    3. otherwise candidates — entries whose title mentions it, else the
       entries of period sections whose heading mentions it ("Minfy" ->
       every 7.x) — for the owner to pick (or propose a new entry)."""
    if rec is None:
        return {"entry_id": None, "how": None, "candidates": [], "note": "no record note"}
    if hub.record_entry:
        if rec.entry(hub.record_entry) is not None:
            return {"entry_id": hub.record_entry, "how": "field", "candidates": []}
        note = f"record_entry {hub.record_entry!r} is not in the record"
    else:
        note = ""
    by_title = [e.id for e in rec.entries if title_mentioned(hub.title, e.title)]
    if len(by_title) == 1 and not note:
        return {"entry_id": by_title[0], "how": "title", "candidates": []}
    candidates = by_title
    if not candidates:
        sections = {s.num for s in rec.sections if title_mentioned(hub.title, s.title)}
        candidates = [e.id for e in rec.entries if e.section in sections]
    return {"entry_id": None, "how": None, "candidates": candidates, "note": note or ("ambiguous" if candidates else "no match")}
