"""The auto photo-journal: when a photo commits, a DETERMINISTIC one-liner
(no LLM call — that's the point) lands in that day's journal, and the photo/
people/place get graph-connected by reference (edges), never by copying text
anywhere.

Three pieces live here:

- `auto_journal_line(...)` — the pure composer. Facts in (perception dump,
  EXIF time, place, matched people, photo title), one line out, e.g.
  `📷 2:14 PM — with Alex at Hermann Park · sunny · dog, frisbee (photo: Lake hike)`.
  Absent parts are omitted, never guessed.
- `process_photo_commit(...)` — the commit hook `/kb/entries/with-asset`
  calls after persisting a photo entry: runs (or receives) perception,
  appends the journal line under an `auto-photo:<folder>/<slug>` marker
  (strippable/undoable exactly like MCP appends, and dedup-checked so a
  re-commit never double-appends), and creates the `pictured_with` /
  `at_location` edges with source_of_edge="photo_perception".
- `tag_unknown_face(...)` — the "who is this?" flow: enroll the face,
  create the person if new, wire the edges, and fold the name into the
  photo's existing journal line in place (one line per photo, not a trail
  of correction lines — see `add_person_to_line`).

The perception module (`quintacle_core.perception`) is a seam built in a
parallel worktree — it is imported lazily and its absence (or any failure
inside it) degrades to the no-perception path, same safe-adapter spirit as
`mcp_server/graph_link.py`: a photo save must never fail because face
recognition isn't installed.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime

from ...graph import create_edge
from ..journal.api import get_store as get_journal_store
from ..journal.normalize import canonicalize_name
from ..people.api import get_store as get_people_store
from ..travel.api import get_store as get_travel_store
from .drop import _IMAGE_MIME, extract_photo_date, extract_photo_datetime, is_image
from .store import _ASSET_LINES_RE

# Below this similarity score a "match" is treated as unknown — it goes to
# the tag flow instead of being guessed into the journal/graph.
MATCH_THRESHOLD = float(os.environ.get("QUINTACLE_FACE_MATCH_THRESHOLD", "0.8"))

SOURCE_OF_EDGE = "photo_perception"

# Journal-line tags come from perception's full tag list — cap what lands in
# the line so it stays a glanceable one-liner, not an inventory.
_MAX_LINE_TAGS = 4

_MARKER_PREFIX = "auto-photo"


def photo_marker(folder: str, slug: str) -> str:
    """The journal-append marker id for one photo entry — derived from its
    folder/slug (stable across re-commits), which is what makes the
    check-before-append dedup and the per-photo undo both possible."""
    return f"{_MARKER_PREFIX}:{folder}/{slug}"


# ---------------------------------------------------------------- the seam


def _as_dict(obj) -> dict:
    """Perception results may arrive as pydantic models, dataclass-ish
    objects, or already-dumped dicts (the drop proposal's `perception`
    payload travels as JSON) — normalize to plain dicts so everything
    downstream handles exactly one shape."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return {k: getattr(obj, k) for k in ("tags", "scene", "faces", "box", "embedding_id", "match") if hasattr(obj, k)}


def perception_dict(result) -> dict | None:
    if result is None:
        return None
    p = _as_dict(result)
    return {
        "tags": list(p.get("tags") or []),
        "scene": dict(p.get("scene") or {}),
        "faces": [_as_dict(f) for f in (p.get("faces") or [])],
    }


def perceive_photo_safe(data: bytes, mime: str) -> dict | None:
    """Lazy, failure-tolerant call into the perception seam. Returns the
    normalized PerceptionResult dict, or None when the module is absent
    (deps not installed), declines (returns None), or raises — all three
    read identically as "no perception" to callers."""
    try:
        from ...perception import perceive_photo
    except Exception:
        return None
    try:
        return perception_dict(perceive_photo(data, mime))
    except Exception:
        return None


def enroll_face_safe(embedding_id: str, person_name: str) -> bool:
    """True iff the perception module exists and enrollment succeeded. A
    missing module doesn't block the rest of the tag flow — the person
    entry, edges, and journal update are all still worth having; enrollment
    simply catches up once perception is installed."""
    try:
        from ...perception import enroll_face
    except Exception:
        return False
    try:
        enroll_face(embedding_id, person_name)
        return True
    except Exception:
        return False


def split_faces(perception) -> tuple[list[str], list[dict]]:
    """(matched_names, unknown_faces). A face counts as matched ONLY with a
    person_name at/above MATCH_THRESHOLD — anything else (no match, or a
    low-score guess) is unknown and goes to the tag flow, carrying the
    low-score name as `suggested_name` so the UI can offer it without the
    journal ever asserting it."""
    p = perception_dict(perception)
    matched: list[str] = []
    unknown: list[dict] = []
    for face in (p or {}).get("faces") or []:
        match = face.get("match") or {}
        name = match.get("person_name")
        score = match.get("score") or 0
        if name and score >= MATCH_THRESHOLD:
            if name not in matched:
                matched.append(name)
        else:
            unknown.append({"embedding_id": face.get("embedding_id"), "box": face.get("box"), "suggested_name": name})
    return matched, unknown


# ------------------------------------------------------------ the composer


def _join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def _format_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _scene_word(scene: dict) -> str | None:
    """One deterministic word from perception's scene hints. Conservative:
    anything ambiguous maps to nothing rather than a wrong-mood guess."""
    daylight = scene.get("daylight")
    outdoor = scene.get("outdoor_hint")
    brightness = scene.get("brightness")
    if daylight is False:
        return "night"
    if daylight and outdoor and isinstance(brightness, (int, float)) and brightness >= 0.6:
        return "sunny"
    if outdoor:
        return "outdoors"
    if outdoor is False:
        return "indoors"
    return None


def auto_journal_line(
    perception=None,
    exif_time: datetime | None = None,
    place_name: str | None = None,
    people_names: list[str] | None = None,
    photo_title: str | None = None,
) -> str:
    """The deterministic composer — zero LLM calls, same facts in → same
    line out, absent parts omitted. e.g.
    `📷 2:14 PM — with Alex at Hermann Park · sunny · dog, frisbee (photo: Lake hike)`."""
    p = perception_dict(perception) or {}
    line = "📷"
    if exif_time is not None:
        line += f" {_format_time(exif_time)}"
    context = []
    if people_names:
        context.append(f"with {_join_names(list(people_names))}")
    if place_name:
        context.append(f"at {place_name}")
    if context:
        line += f" — {' '.join(context)}"
    scene = _scene_word(p.get("scene") or {})
    if scene:
        line += f" · {scene}"
    tags = [t for t in p.get("tags") or [] if t][:_MAX_LINE_TAGS]
    if tags:
        line += f" · {', '.join(tags)}"
    if photo_title:
        line += f" (photo: {photo_title})"
    return line


# "— with <names>" up to the first " at ", "·", "(photo:" or end-of-line —
# the exact clause auto_journal_line produces, so add_person_to_line can
# extend it in place.
_WITH_CLAUSE_RE = re.compile(r"— with (.+?)(?= at |\s*·|\s*\(photo:|$)")


def add_person_to_line(line: str, name: str) -> str:
    """Folds a newly-tagged person into an existing composed line, in place —
    ONE line per photo stays the record (chosen over appending a second
    'also with X' line: the reader sees a single coherent fact, and undo via
    the one marker still removes everything about this photo at once)."""
    m = _WITH_CLAUSE_RE.search(line)
    if m:
        names = [n.strip() for chunk in m.group(1).split(" and ") for n in chunk.split(",") if n.strip()]
        if name in names:
            return line
        names.append(name)
        return f"{line[: m.start()]}— with {_join_names(names)}{line[m.end():]}"
    if " — " in line:  # an "at <place>" clause exists but no people yet
        return line.replace(" — ", f" — with {name} ", 1)
    for sep in (" · ", " (photo:"):
        idx = line.find(sep)
        if idx != -1:
            return f"{line[:idx]} — with {name}{line[idx:]}"
    return f"{line} — with {name}"


# EXIF-derived photo folders are media/photos/<year>/<month>[/<trip or
# country/state/city>] (compute_photo_folder) — the trailing segment, when
# present, is the most specific place we already deterministically know.
_PHOTO_FOLDER_PLACE_RE = re.compile(r"^media/photos/\d{4}/[^/]+/(.+)$")


def place_from_photo_folder(folder: str) -> str | None:
    """Deterministic place name from where the photo FILE itself landed —
    reuses the compute_photo_folder placement already decided at propose
    time (trip name, or geocoded city) instead of spending a second
    geocoding call. A bare Media/Photos/<Year>/<Month> folder (everyday
    home life) yields no place, deliberately."""
    m = _PHOTO_FOLDER_PLACE_RE.match(folder)
    if m is None:
        return None
    segment = m.group(1).split("/")[-1]
    return " ".join(w.capitalize() for w in segment.replace("-", " ").split()) or None


def maybe_polish(line: str) -> str:
    """Optional, OFF by default: QUINTACLE_AUTOJOURNAL_POLISH=1 routes the
    already-composed FACTS through one small DEFAULT_MODEL call to phrase a
    nicer sentence. BILLED — one metered API call per photo commit. Facts
    in, sentence out only; any failure falls back to the deterministic
    line, which is always the source of those facts."""
    if os.environ.get("QUINTACLE_AUTOJOURNAL_POLISH") != "1":
        return line
    try:
        import anthropic

        from ...llm_config import DEFAULT_MODEL

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=200,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Rewrite this photo journal line as one natural sentence. Keep every fact, "
                        f"add none, keep the leading 📷. Reply with only the sentence.\n\n{line}"
                    ),
                }
            ],
        )
        polished = next((b.text for b in response.content if b.type == "text"), "").strip()
        return polished or line
    except Exception:
        return line


# ------------------------------------------------- commit + tag-flow glue


def _people_store():
    try:
        return get_people_store()
    except RuntimeError:
        return None


def _resolve_person_folder(name: str) -> str | None:
    store = _people_store()
    if store is None:
        return None
    person = store.find(name)
    return person["folder"] if person else None


def _experience_for_place(place_name: str | None) -> dict | None:
    if not place_name:
        return None
    try:
        experiences = get_travel_store().all()
    except RuntimeError:
        return None
    for e in experiences:
        if e["name"].strip().lower() == place_name.strip().lower():
            return e
    return None


def process_photo_commit(
    folder_slug: str,
    entry_slug: str,
    title: str,
    file_data: list[tuple[str, bytes]],
    perception_payload: dict | None = None,
) -> dict | None:
    """The whole post-commit step for a photo entry — called by
    /kb/entries/with-asset (which both the single Drop and the batch-drop
    review commit through) right after the note + assets are written.

    - perception: the proposal's `perception` payload when the frontend
      carried one through review, else one fresh perceive_photo_safe() pass
      over the first image's bytes (None when the seam is absent).
    - journal: with an EXIF date, the composed line is appended to that
      DATE's journal under the auto-photo marker — but only if that marker
      isn't already in the file (committing the same photo twice must not
      double-append).
    - edges: photo note → person (pictured_with), journal day → person
      (pictured_with), photo note → experience (at_location), all
      source_of_edge="photo_perception", all idempotent via create_edge.

    Returns the summary the commit response carries (unknown faces feed the
    Drop page's tag flow), or None when no image file was committed."""
    first_image = next(((name, data) for name, data in file_data if is_image(name)), None)
    if first_image is None:
        return None
    name, data = first_image
    mime = _IMAGE_MIME.get(name.rsplit(".", 1)[-1].lower(), "image/jpeg")

    perception = perception_dict(perception_payload) if perception_payload else perceive_photo_safe(data, mime)
    matched_names, unknown_faces = split_faces(perception)

    exif_dt = extract_photo_datetime(data)
    exif_date = extract_photo_date(data)
    place = place_from_photo_folder(folder_slug)
    note_id = f"note:{folder_slug}/{entry_slug}"

    edges: list[dict] = []
    for person_name in matched_names:
        person_folder = _resolve_person_folder(person_name)
        if person_folder is None:
            continue
        person_id = f"note:{person_folder}/profile"
        edges.append(create_edge(note_id, person_id, "pictured_with", SOURCE_OF_EDGE))
        if exif_date is not None:
            edges.append(create_edge(f"journal:{exif_date.isoformat()}", person_id, "pictured_with", SOURCE_OF_EDGE))

    experience = _experience_for_place(place)
    if experience is not None:
        edges.append(
            create_edge(note_id, f"experience:{experience['folder']}/{experience['slug']}", "at_location", SOURCE_OF_EDGE)
        )

    auto_line = None
    journal_appended = False
    if exif_date is not None:
        marker = photo_marker(folder_slug, entry_slug)
        journal = get_journal_store()
        if not journal.has_marked_append(exif_date, marker):
            auto_line = maybe_polish(
                auto_journal_line(
                    perception,
                    exif_time=exif_dt,
                    place_name=place,
                    people_names=matched_names,
                    photo_title=title,
                )
            )
            journal.save(exif_date, auto_line, marker=marker)
            journal_appended = True

    return {
        "people": matched_names,
        "unknown_faces": unknown_faces,
        "journal_date": exif_date.isoformat() if exif_date else None,
        "journal_appended": journal_appended,
        "auto_line": auto_line,
        "place": place,
        "edges": [e["id"] for e in edges],
    }


def tag_unknown_face(embedding_id: str, person_name: str, folder: str, slug: str) -> dict:
    """The "who is this?" resolution for one unknown face on one committed
    photo: (a) enroll the embedding (lazy seam — tolerated absent),
    (b) create the person entry if the name is new (canonicalized against
    known people first, so "alex" doesn't fork a second Alex), (c) create
    the pictured_with edges, (d) fold the name into the photo's existing
    marker-tagged journal line in place — or compose a fresh one if that
    photo never got a line (no marker found but the photo has an EXIF
    date). Raises LookupError if the photo entry doesn't exist."""
    from .api import get_store as get_kb_store  # runtime import — kb.api imports this module

    kb = get_kb_store()
    content = kb.read(folder, slug)
    if content is None:
        raise LookupError("photo entry not found")
    title = content.split("\n", 1)[0].lstrip("# ").strip() or slug

    people = get_people_store()
    known_names = [p["name"] for p in people.all()]
    resolved_name = canonicalize_name(person_name, known_names)
    person = people.find(resolved_name)
    created_person = False
    if person is None:
        person_folder, _ = people.write(resolved_name)
        created_person = True
    else:
        person_folder = person["folder"]

    enrolled = enroll_face_safe(embedding_id, resolved_name)

    # The photo's own EXIF (re-read from the stored asset — deterministic)
    # dates the journal line and the day edge, same as at commit time.
    exif_dt: datetime | None = None
    exif_date: date | None = None
    for asset_path in _ASSET_LINES_RE.findall(content):
        asset_data = kb.read_asset(folder, asset_path)
        if asset_data is not None and is_image(asset_path):
            exif_dt = extract_photo_datetime(asset_data)
            exif_date = extract_photo_date(asset_data)
            break

    note_id = f"note:{folder}/{slug}"
    person_id = f"note:{person_folder}/profile"
    edges = [create_edge(note_id, person_id, "pictured_with", SOURCE_OF_EDGE)]
    if exif_date is not None:
        edges.append(create_edge(f"journal:{exif_date.isoformat()}", person_id, "pictured_with", SOURCE_OF_EDGE))

    journal_updated = False
    if exif_date is not None:
        marker = photo_marker(folder, slug)
        journal = get_journal_store()
        existing_line = journal.read_marked_append(exif_date, marker)
        if existing_line is not None:
            updated = add_person_to_line(existing_line, resolved_name)
            if updated != existing_line:
                journal.rewrite_marked_append(exif_date, marker, updated)
                journal_updated = True
        else:
            line = auto_journal_line(
                None,
                exif_time=exif_dt,
                place_name=place_from_photo_folder(folder),
                people_names=[resolved_name],
                photo_title=title,
            )
            journal.save(exif_date, line, marker=marker)
            journal_updated = True

    return {
        "person_name": resolved_name,
        "created_person": created_person,
        "enrolled": enrolled,
        "edges": [e["id"] for e in edges],
        "journal_date": exif_date.isoformat() if exif_date else None,
        "journal_updated": journal_updated,
    }
